package cn.creator.workbench.service;

import cn.creator.workbench.persistence.VisualJobMapper;
import cn.creator.workbench.persistence.VisualJobRecord;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class VisualGenerationControlRaceTest {
    private static final String ID="draw_abcdefgh_0";
    private static VisualJobRecord job(String state){
        var job=new VisualJobRecord();job.setId(ID);job.setProjectId("p");job.setNeedId("n");job.setBatchId("b");
        job.setState(state);job.setCreatedAt("2026-01-01T00:00:00Z");job.setPayload("{\"maxCostCents\":1}");return job;
    }
    @Test void cancelRetriesWhenQueuedJobStartsDuringCancellation(){
        var mapper=mock(VisualJobMapper.class);
        when(mapper.find(ID)).thenReturn(job("QUEUED"),job("SUBMITTING"),job("CANCEL_REQUESTED"));
        when(mapper.state(eq(ID),eq("QUEUED"),eq("CANCELLED"),isNull(),anyString())).thenReturn(0);
        when(mapper.state(eq(ID),eq("SUBMITTING"),eq("CANCEL_REQUESTED"),isNull(),anyString())).thenReturn(1);
        var service=new VisualGenerationService(mapper,null,null,null,mock(PlatformTransactionManager.class));
        var request=new JsonObject();request.addProperty("action","CANCEL");
        assertEquals("CANCEL_REQUESTED",service.control(ID,request).get("state").getAsString());
        verify(mapper).state(eq(ID),eq("SUBMITTING"),eq("CANCEL_REQUESTED"),isNull(),anyString());
    }
    @Test void cancelBeforeSubmissionDoesNotSendGenerationRequest(){
        var mapper=mock(VisualJobMapper.class);var workspace=mock(WorkspaceService.class);
        var executor=mock(MediaExecutorClient.class);
        when(workspace.load()).thenReturn(JsonParser.parseString("{\"projects\":[{\"id\":\"p\"}]}").getAsJsonObject());
        when(mapper.state(eq(ID),eq("QUEUED"),eq("SUBMITTING"),isNull(),anyString())).thenReturn(1);
        when(mapper.find(ID)).thenReturn(job("CANCEL_REQUESTED"));
        when(mapper.state(eq(ID),eq("CANCEL_REQUESTED"),eq("CANCELLED"),isNull(),anyString())).thenReturn(1);
        var queued=job("QUEUED");queued.setPayload("{\"productionNodeId\":\"N27\",\"references\":[]}");
        new VisualGenerationService(mapper,workspace,executor,null,mock(PlatformTransactionManager.class)).process(queued);
        verify(executor,never()).submit(any());
        verify(mapper).state(eq(ID),eq("CANCEL_REQUESTED"),eq("CANCELLED"),isNull(),anyString());
    }
    @Test void cancelDuringSubmitIsRecordedAfterSubmissionResult() throws Exception {
        var mapper=mock(VisualJobMapper.class);var workspace=mock(WorkspaceService.class);var executor=mock(MediaExecutorClient.class);
        var state=new AtomicReference<>("QUEUED");
        when(workspace.load()).thenReturn(JsonParser.parseString("{\"projects\":[{\"id\":\"p\"}]}").getAsJsonObject());
        when(mapper.find(ID)).thenAnswer(call->{var value=job(state.get());value.setPayload("{\"productionNodeId\":\"N27\",\"references\":[],\"maxCostCents\":1}");return value;});
        when(mapper.state(eq(ID),anyString(),anyString(),nullable(String.class),anyString())).thenAnswer(call->state.compareAndSet(call.getArgument(1),call.getArgument(2))?1:0);
        var started=new CountDownLatch(1);var release=new CountDownLatch(1);
        when(executor.submit(any())).thenAnswer(call->{started.countDown();if(!release.await(5,TimeUnit.SECONDS))throw new AssertionError("提交未释放");return JsonParser.parseString("{\"id\":\""+ID+"\"}").getAsJsonObject();});
        var service=new VisualGenerationService(mapper,workspace,executor,null,mock(PlatformTransactionManager.class));
        var request=new JsonObject();request.addProperty("action","CANCEL");
        var threads=Executors.newFixedThreadPool(2);
        try {
            var processing=threads.submit(()->service.process(mapper.find(ID)));
            assertTrue(started.await(5,TimeUnit.SECONDS));
            var cancelStarted=new CountDownLatch(1);var cancellation=threads.submit(()->{cancelStarted.countDown();return service.control(ID,request);});
            assertTrue(cancelStarted.await(5,TimeUnit.SECONDS));Thread.sleep(150);
            boolean returnedTooEarly=cancellation.isDone();release.countDown();
            processing.get(5,TimeUnit.SECONDS);assertEquals("CANCEL_REQUESTED",cancellation.get(5,TimeUnit.SECONDS).get("state").getAsString());
            assertFalse(returnedTooEarly,"提交进行中应先等待受理结果再同步取消");
        } finally {release.countDown();threads.shutdownNow();}
    }
}
