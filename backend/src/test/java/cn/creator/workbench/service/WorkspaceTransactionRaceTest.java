package cn.creator.workbench.service;

import cn.creator.workbench.persistence.WorkspaceMapper;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.*;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class WorkspaceTransactionRaceTest {
    @Test void initialLoadWaitsUntilFirstInitializationCommits() throws Exception {
        var mapper=mock(WorkspaceMapper.class);var reads=new AtomicInteger();
        when(mapper.findWorkspace("local")).thenAnswer(call->{reads.incrementAndGet();return null;});
        var source=new JdbcDataSource();source.setURL("jdbc:h2:mem:workspace_race;DB_CLOSE_DELAY=-1");
        var delegate=new DataSourceTransactionManager(source);
        var commitStarted=new CountDownLatch(1);var release=new CountDownLatch(1);var commits=new AtomicInteger();
        PlatformTransactionManager manager=new PlatformTransactionManager(){
            public TransactionStatus getTransaction(TransactionDefinition definition){return delegate.getTransaction(definition);}
            public void commit(TransactionStatus status){
                if(commits.getAndIncrement()==0){commitStarted.countDown();try{if(!release.await(5,TimeUnit.SECONDS))throw new AssertionError("提交未释放");}catch(InterruptedException e){Thread.currentThread().interrupt();throw new AssertionError(e);}}
                delegate.commit(status);
            }
            public void rollback(TransactionStatus status){delegate.rollback(status);}
        };
        var service=new WorkspaceService(mapper,mock(VisualCandidateService.class));
        var factory=new ProxyFactory(service);factory.setProxyTargetClass(true);
        factory.addAdvice(new TransactionInterceptor(manager,new AnnotationTransactionAttributeSource()));
        var proxied=(WorkspaceService)factory.getProxy();
        var executor=Executors.newFixedThreadPool(2);
        try {
            var first=executor.submit(proxied::load);
            assertTrue(commitStarted.await(5,TimeUnit.SECONDS));
            var started=new CountDownLatch(1);var second=executor.submit(()->{started.countDown();return proxied.load();});
            assertTrue(started.await(5,TimeUnit.SECONDS));Thread.sleep(150);
            int beforeCommit=reads.get();release.countDown();
            first.get(5,TimeUnit.SECONDS);second.get(5,TimeUnit.SECONDS);
            assertEquals(1,beforeCommit,"初始记录提交前不应并发执行第二次初始化");
        } finally {release.countDown();executor.shutdownNow();}
    }

    @Test void nestedWorkspaceCallsInOneTransactionDoNotDeadlockAConcurrentReader() throws Exception {
        var mapper=mock(WorkspaceMapper.class);
        when(mapper.findWorkspace("local")).thenReturn(null);
        var source=new JdbcDataSource();source.setURL("jdbc:h2:mem:workspace_nested;DB_CLOSE_DELAY=-1");
        var manager=new DataSourceTransactionManager(source);
        var service=new WorkspaceService(mapper,mock(VisualCandidateService.class));
        var factory=new ProxyFactory(service);factory.setProxyTargetClass(true);
        factory.addAdvice(new TransactionInterceptor(manager,new AnnotationTransactionAttributeSource()));
        var proxied=(WorkspaceService)factory.getProxy();
        var firstRead=new CountDownLatch(1);var secondStarted=new CountDownLatch(1);
        var executor=Executors.newFixedThreadPool(2);
        try {
            var first=executor.submit(()->new TransactionTemplate(manager).execute(status->{
                proxied.load();firstRead.countDown();
                try{if(!secondStarted.await(5,TimeUnit.SECONDS))throw new AssertionError("并发请求未启动");}
                catch(InterruptedException e){Thread.currentThread().interrupt();throw new AssertionError(e);}
                proxied.load();return null;
            }));
            assertTrue(firstRead.await(5,TimeUnit.SECONDS));
            var second=executor.submit(()->{secondStarted.countDown();return proxied.load();});
            first.get(5,TimeUnit.SECONDS);second.get(5,TimeUnit.SECONDS);
        } finally {executor.shutdownNow();}
    }

    @Test void workspaceLockIsReleasedAfterRollback() throws Exception {
        var mapper=mock(WorkspaceMapper.class);when(mapper.findWorkspace("local")).thenReturn(null);
        var source=new JdbcDataSource();source.setURL("jdbc:h2:mem:workspace_rollback;DB_CLOSE_DELAY=-1");
        var manager=new DataSourceTransactionManager(source);
        var service=new WorkspaceService(mapper,mock(VisualCandidateService.class));
        var factory=new ProxyFactory(service);factory.setProxyTargetClass(true);
        factory.addAdvice(new TransactionInterceptor(manager,new AnnotationTransactionAttributeSource()));
        var proxied=(WorkspaceService)factory.getProxy();
        assertThrows(IllegalStateException.class,()->new TransactionTemplate(manager).execute(status->{proxied.load();throw new IllegalStateException("rollback");}));
        var executor=Executors.newSingleThreadExecutor();
        try{assertNotNull(executor.submit(proxied::load).get(5,TimeUnit.SECONDS));}
        finally{executor.shutdownNow();}
    }
}
