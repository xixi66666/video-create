package cn.creator.workbench.service;

import cn.creator.workbench.persistence.AgentRunMapper;
import cn.creator.workbench.persistence.AgentRunRecord;
import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AgentRunDispatchRaceTest {
    private static final String ID = "run_dispatch_race_123";
    private static AgentRunRecord record(String state) {
        var record = new AgentRunRecord();
        record.setId(ID);
        record.setState(state);
        record.setPayload("{\"mode\":\"FIXTURE\",\"executionMode\":\"GENERATE_TEXT\",\"models\":{},\"limits\":{}}");
        record.setDispatchAttempts(0);
        return record;
    }

    @Test void cancelDuringSubmissionIsNotOverwrittenAndCancelsRemoteRun() throws Exception {
        var mapper = mock(AgentRunMapper.class);
        var runtime = mock(AgentRuntimeClient.class);
        var state = new AtomicReference<>("PENDING_SUBMISSION");
        when(mapper.pending()).thenReturn(List.of(record("PENDING_SUBMISSION")));
        when(mapper.find(ID)).thenAnswer(call -> record(state.get()));
        doAnswer(call -> { state.set(call.getArgument(1)); return null; }).when(mapper).state(eq(ID), anyString());
        var started = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        when(runtime.post(eq("/runs"), any())).thenAnswer(call -> {
            started.countDown();
            if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("投递未释放");
            return new JsonObject();
        });
        when(runtime.post(eq("/runs/" + ID + "/cancel"), any())).thenReturn(new JsonObject());
        var service = new AgentRunService(null, mapper, runtime, mock(PlatformTransactionManager.class));
        var action = new JsonObject(); action.addProperty("action", "CANCEL");
        var executor = Executors.newFixedThreadPool(2);
        try {
            var dispatch = executor.submit(service::dispatch);
            assertTrue(started.await(5, TimeUnit.SECONDS));
            var cancelStarted = new CountDownLatch(1);
            var cancel = executor.submit(() -> { cancelStarted.countDown(); return service.control(ID, action); });
            assertTrue(cancelStarted.await(5, TimeUnit.SECONDS));
            Thread.sleep(150);
            release.countDown();
            dispatch.get(5, TimeUnit.SECONDS);
            cancel.get(5, TimeUnit.SECONDS);
            assertEquals("CANCELLED", state.get());
            verify(runtime).post(eq("/runs/" + ID + "/cancel"), any());
        } finally {
            release.countDown();
            executor.shutdownNow();
        }
    }

    @Test void cancellationPreventsDispatchOfAnAlreadyCancelledSnapshot() {
        var mapper = mock(AgentRunMapper.class);
        var runtime = mock(AgentRuntimeClient.class);
        when(mapper.pending()).thenReturn(List.of(record("PENDING_SUBMISSION")));
        when(mapper.find(ID)).thenReturn(record("CANCELLED"));
        new AgentRunService(null, mapper, runtime, mock(PlatformTransactionManager.class)).dispatch();
        verify(runtime, never()).post(anyString(), any());
    }

    @Test void uncertainSubmissionPersistsCancelIntentAndNeverResubmits() {
        var mapper = mock(AgentRunMapper.class);
        var runtime = mock(AgentRuntimeClient.class);
        var state=new AtomicReference<>("PENDING_SUBMISSION");
        when(mapper.find(ID)).thenAnswer(call->{var value=record(state.get());value.setDispatchAttempts(1);return value;});
        when(mapper.pending()).thenAnswer(call->List.of(record(state.get())));
        doAnswer(call->{state.set(call.getArgument(1));return null;}).when(mapper).state(eq(ID),anyString());
        when(runtime.post(eq("/runs/" + ID + "/cancel"), any()))
                .thenThrow(new BusinessException(503, "远端状态未知"));
        var action = new JsonObject(); action.addProperty("action", "CANCEL");
        var service=new AgentRunService(null, mapper, runtime, mock(PlatformTransactionManager.class));
        assertEquals("CANCEL_PENDING_SYNC",service.control(ID, action).get("state").getAsString());
        service.dispatch();
        assertEquals("CANCEL_PENDING_SYNC",state.get());
        verify(mapper, never()).state(eq(ID), eq("CANCELLED"));
        verify(runtime, never()).post(eq("/runs"), any());
    }

    @Test void crashAfterRemoteAcceptanceCannotMakeCancellationLookUnsubmitted() {
        var mapper=mock(AgentRunMapper.class);var runtime=mock(AgentRuntimeClient.class);
        var state=new AtomicReference<>("PENDING_SUBMISSION");var attempts=new AtomicInteger();
        when(mapper.find(ID)).thenAnswer(call->{var value=record(state.get());value.setDispatchAttempts(attempts.get());return value;});
        when(mapper.pending()).thenAnswer(call->List.of(record(state.get())));
        when(mapper.bumpDispatch(eq(ID),anyString(),anyString())).thenAnswer(call->{attempts.incrementAndGet();return 1;});
        doAnswer(call->{state.set(call.getArgument(1));return null;}).when(mapper).state(eq(ID),anyString());
        // 模拟远端已受理但进程在收到响应前异常中断；不经过 BusinessException 的正常错误处理。
        when(runtime.post(eq("/runs"),any())).thenThrow(new AssertionError("模拟进程中断"));
        when(runtime.post(eq("/runs/"+ID+"/cancel"),any())).thenThrow(new BusinessException(503,"远端未确认"));
        var service=new AgentRunService(null,mapper,runtime,mock(PlatformTransactionManager.class));
        assertThrows(AssertionError.class,service::dispatch);
        assertEquals(1,attempts.get(),"发送前必须持久化投递尝试");
        var action=new JsonObject();action.addProperty("action","CANCEL");
        assertEquals("CANCEL_PENDING_SYNC",service.control(ID,action).get("state").getAsString());
        verify(runtime).post(eq("/runs/"+ID+"/cancel"),any());
        verify(mapper,never()).state(eq(ID),eq("CANCELLED"));
    }

    @Test void missingRemoteRunRequiresManualRetryRatherThanClaimingCancellation() {
        var mapper=mock(AgentRunMapper.class);var runtime=mock(AgentRuntimeClient.class);
        var state=new AtomicReference<>("PENDING_SUBMISSION");
        when(mapper.find(ID)).thenAnswer(call->{var value=record(state.get());value.setDispatchAttempts(1);return value;});
        doAnswer(call->{state.set(call.getArgument(1));return null;}).when(mapper).state(eq(ID),anyString());
        when(runtime.post(eq("/runs/"+ID+"/cancel"),any())).thenThrow(new BusinessException(404,"任务未查到"));
        var service=new AgentRunService(null,mapper,runtime,mock(PlatformTransactionManager.class));
        var action=new JsonObject();action.addProperty("action","CANCEL");
        assertEquals("CANCEL_SYNC_FAILED",service.control(ID,action).get("state").getAsString());
        action.addProperty("action","RETRY");
        assertEquals("CANCEL_PENDING_SYNC",service.control(ID,action).get("state").getAsString());
        verify(runtime,never()).post(eq("/runs"),any());
    }

    @Test void failedSubmissionCanBeCancelledWithoutAssumingRemoteIsAbsent() {
        var mapper=mock(AgentRunMapper.class);var runtime=mock(AgentRuntimeClient.class);
        var state=new AtomicReference<>("SUBMISSION_FAILED");
        when(mapper.find(ID)).thenAnswer(call->record(state.get())); // 兼容旧数据的零计数
        doAnswer(call->{state.set(call.getArgument(1));return null;}).when(mapper).state(eq(ID),anyString());
        when(runtime.post(eq("/runs/"+ID+"/cancel"),any())).thenThrow(new BusinessException(503,"远端未确认"));
        var service=new AgentRunService(null,mapper,runtime,mock(PlatformTransactionManager.class));
        var action=new JsonObject();action.addProperty("action","DELETE");
        assertThrows(BusinessException.class,()->service.control(ID,action));
        action.addProperty("action","CANCEL");
        assertEquals("CANCEL_PENDING_SYNC",service.control(ID,action).get("state").getAsString());
        verify(runtime).post(eq("/runs/"+ID+"/cancel"),any());
        verify(mapper,never()).state(eq(ID),eq("CANCELLED"));
    }

    @Test void retryDoesNotEraseSubmissionHistoryBeforeLaterCancel() {
        var mapper=mock(AgentRunMapper.class);var runtime=mock(AgentRuntimeClient.class);
        var state=new AtomicReference<>("SUBMISSION_FAILED");
        when(mapper.find(ID)).thenAnswer(call->{var value=record(state.get());value.setDispatchAttempts(1);return value;});
        doAnswer(call->{state.set(call.getArgument(1));return null;}).when(mapper).state(eq(ID),anyString());
        when(runtime.post(eq("/runs/"+ID+"/cancel"),any())).thenThrow(new BusinessException(503,"远端未确认"));
        var service=new AgentRunService(null,mapper,runtime,mock(PlatformTransactionManager.class));
        var action=new JsonObject();action.addProperty("action","RETRY");
        assertEquals("PENDING_SUBMISSION",service.control(ID,action).get("state").getAsString());
        verify(mapper).clearDispatchError(eq(ID),anyString());
        verify(mapper,never()).clearDispatch(eq(ID),anyString());
        action.addProperty("action","CANCEL");
        assertEquals("CANCEL_PENDING_SYNC",service.control(ID,action).get("state").getAsString());
        verify(runtime).post(eq("/runs/"+ID+"/cancel"),any());
    }

    @Test void retryMigratesMissingLegacyAttemptHistoryBeforeRequeueing() {
        var mapper=mock(AgentRunMapper.class);var runtime=mock(AgentRuntimeClient.class);
        var state=new AtomicReference<>("SUBMISSION_FAILED");
        when(mapper.find(ID)).thenAnswer(call->record(state.get()));
        doAnswer(call->{state.set(call.getArgument(1));return null;}).when(mapper).state(eq(ID),anyString());
        var service=new AgentRunService(null,mapper,runtime,mock(PlatformTransactionManager.class));
        var action=new JsonObject();action.addProperty("action","RETRY");
        assertEquals("PENDING_SUBMISSION",service.control(ID,action).get("state").getAsString());
        var order=inOrder(mapper);
        order.verify(mapper).insertDispatch(eq(ID),eq("投递历史待核对"),anyString());
        order.verify(mapper).state(ID,"PENDING_SUBMISSION");
        verify(mapper,never()).clearDispatch(eq(ID),anyString());
    }

    @Test void sameIdCreateWaitsForPreviousTransactionCommit() throws Exception {
        var mapper=mock(AgentRunMapper.class);var runtime=mock(AgentRuntimeClient.class);
        var manager=mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenAnswer(call->new SimpleTransactionStatus());
        var count=new AtomicInteger();
        when(mapper.find(ID)).thenAnswer(call->{count.incrementAndGet();var r=record("SUBMITTED");r.setProjectId("p");r.setNodeId("N08");return r;});
        var commitStarted=new CountDownLatch(1);var release=new CountDownLatch(1);var commits=new AtomicInteger();
        doAnswer(call->{if(commits.getAndIncrement()==0){commitStarted.countDown();if(!release.await(5,TimeUnit.SECONDS))throw new AssertionError("提交未释放");}return null;}).when(manager).commit(any());
        var service=new AgentRunService(null,mapper,runtime,manager);
        var factory=new ProxyFactory(service);factory.setProxyTargetClass(true);
        factory.addAdvice(new TransactionInterceptor(manager,new AnnotationTransactionAttributeSource()));
        var proxied=(AgentRunService)factory.getProxy();
        var request=new JsonObject();request.addProperty("id",ID);request.addProperty("projectId","p");request.addProperty("nodeId","N08");request.addProperty("mode","FIXTURE");
        var executor=Executors.newFixedThreadPool(2);
        try {
            var first=executor.submit(()->proxied.create(request));
            assertTrue(commitStarted.await(5,TimeUnit.SECONDS));
            var secondStarted=new CountDownLatch(1);
            var second=executor.submit(()->{secondStarted.countDown();return proxied.create(request);});
            assertTrue(secondStarted.await(5,TimeUnit.SECONDS));Thread.sleep(150);
            int readsBeforeCommit=count.get();release.countDown();
            first.get(5,TimeUnit.SECONDS);second.get(5,TimeUnit.SECONDS);
            assertEquals(1,readsBeforeCommit,"前一次事务提交前不应执行第二次同 ID 读取");
        } finally {release.countDown();executor.shutdownNow();}
    }
}
