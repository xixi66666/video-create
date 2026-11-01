package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.ComfyRunMapper;
import com.google.gson.*;
import java.io.IOException;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.UUID;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:comfytest;MODE=MySQL;DB_CLOSE_DELAY=-1","workbench.comfy.poll-ms=1000000","workbench.files-dir=target/comfy-test-files"})
class ComfyRunServiceTest {
    @Autowired ComfyRunService service;
    @Autowired ComfyRunMapper mapper;
    @Autowired ComfyTemplates templates;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean ComfyClient client;
    @MockitoBean WorkspaceService workspace;
    JsonObject state,project,request;
    String id;

    @BeforeEach void prepare()throws Exception{
        jdbc.update("DELETE FROM comfy_run");
        id="comfy_"+UUID.randomUUID();
        project=JsonParser.parseString("""
          {"id":"project_test","title":"test","brief":"brief","template":"AI_STORY","platforms":[],
           "nodes":{"N24":{"revision":1,"status":"COMPLETED"},"N25":{"revision":1,"status":"SKIPPED"},"N26":{"revision":1,"status":"SKIPPED"},"N27":{"revision":0,"status":"NOT_STARTED"}},"approvals":{"G03":{"decision":"APPROVED"}}}
          """).getAsJsonObject();
        state=new JsonObject();state.addProperty("version",1);var projects=new JsonArray();projects.add(project);state.add("projects",projects);when(workspace.load()).thenReturn(state);
        var template=templates.find("local-h3-video-v1");var graph=templates.workflow(template);var info=new JsonObject();for(var entry:graph.entrySet()){var spec=new JsonObject();spec.add("input",new JsonObject());info.add(entry.getValue().getAsJsonObject().get("class_type").getAsString(),spec);}
        when(client.get("/object_info")).thenReturn(info);
        request=JsonParser.parseString("{\"projectId\":\"project_test\",\"nodeId\":\"N27\",\"templateId\":\"local-h3-video-v1\",\"prompt\":\"forest\",\"seed\":42}").getAsJsonObject();request.addProperty("id",id);
    }
    @SuppressWarnings("unchecked") void accepted()throws Exception{
        HttpResponse<String> response=mock(HttpResponse.class);when(response.statusCode()).thenReturn(200);when(response.body()).thenAnswer(a->"{\"prompt_id\":\""+mapper.find(id).getPromptId()+"\"}");when(client.submit(any())).thenReturn(response);
    }
    void completedHistory()throws Exception{
        String promptId=mapper.find(id).getPromptId();var root=new JsonObject();var history=JsonParser.parseString("""
          {"status":{"status_str":"success","completed":true},"outputs":{"14":{"images":[{"filename":"test.mp4","subfolder":"","type":"output"}]}}}
          """).getAsJsonObject();root.add(promptId,history);when(client.get("/history/"+promptId)).thenReturn(root);when(client.video("test.mp4","")).thenReturn(new byte[]{0,0,0,12,'f','t','y','p',0,0,0,0});
    }
    @Test void submitsOnceCollectsAndAdoptsOnlyOnRequest()throws Exception{
        var first=service.create(request);assertEquals("QUEUED",first.get("state").getAsString());assertEquals(first,service.create(request));accepted();service.poll();assertEquals("RUNNING",mapper.find(id).getState());
        completedHistory();service.poll();var done=service.detail(id);assertEquals("SUCCEEDED",done.get("state").getAsString());assertFalse(done.get("adopted").getAsBoolean());assertTrue(done.get("fileRef").getAsString().startsWith("/api/v1/files/"));verify(workspace,never()).execute(any());
        service.adopt(id);service.adopt(id);assertTrue(service.detail(id).get("adopted").getAsBoolean());verify(workspace,times(1)).execute(any(WorkspaceCommand.class));verify(client,times(1)).submit(any());
    }
    @Test void changedInputPreventsSubmissionAndCandidateAdoption()throws Exception{
        service.create(request);project.getAsJsonObject("nodes").getAsJsonObject("N24").addProperty("revision",2);service.poll();assertEquals("FAILED",mapper.find(id).getState());verify(client,never()).submit(any());
        project.getAsJsonObject("nodes").getAsJsonObject("N24").addProperty("revision",1);id="comfy_"+UUID.randomUUID();request.addProperty("id",id);service.create(request);accepted();service.poll();completedHistory();service.poll();project.getAsJsonObject("nodes").getAsJsonObject("N24").addProperty("revision",2);
        assertEquals(409,assertThrows(BusinessException.class,()->service.adopt(id)).getStatus());verify(workspace,never()).execute(any());
    }
    @Test void submissionTimeoutRemainsUnknownAndDoesNotResubmit()throws Exception{
        service.create(request);when(client.submit(any())).thenThrow(new IOException("timeout"));service.poll();assertEquals("UNKNOWN",mapper.find(id).getState());String promptId=mapper.find(id).getPromptId();when(client.get("/history/"+promptId)).thenReturn(new JsonObject());when(client.get("/queue")).thenReturn(JsonParser.parseString("{\"queue_running\":[],\"queue_pending\":[]}").getAsJsonObject());service.poll();service.poll();assertEquals("UNKNOWN",mapper.find(id).getState());verify(client,times(1)).submit(any());
        completedHistory();service.poll();assertEquals("SUCCEEDED",mapper.find(id).getState());verify(client,times(1)).submit(any());
    }
    @Test void rejectsAnotherActiveRunForSameProjectNode(){
        service.create(request);var duplicate=request.deepCopy();duplicate.addProperty("id","comfy_"+UUID.randomUUID());
        assertEquals(409,assertThrows(BusinessException.class,()->service.create(duplicate)).getStatus());
        assertEquals("QUEUED",service.create(request).get("state").getAsString());
    }
    @Test void simultaneousSubmissionsCreateOnlyOneRun()throws Exception{
        var second=request.deepCopy();second.addProperty("id","comfy_"+UUID.randomUUID());
        var start=new CountDownLatch(1);var executor=Executors.newFixedThreadPool(2);
        try{
            Callable<String> first=()->{start.await();try{return service.create(request).get("state").getAsString();}catch(BusinessException e){return "rejected:"+e.getStatus();}};
            Callable<String> other=()->{start.await();try{return service.create(second).get("state").getAsString();}catch(BusinessException e){return "rejected:"+e.getStatus();}};
            var a=executor.submit(first);var b=executor.submit(other);start.countDown();
            assertEquals(java.util.Set.of("QUEUED","rejected:409"),java.util.Set.of(a.get(15,TimeUnit.SECONDS),b.get(15,TimeUnit.SECONDS)));
            assertEquals(1,mapper.active().size());
        }finally{executor.shutdownNow();}
    }
    @Test void rejectsUnsafeUrlsAndOutputPaths(){
        assertThrows(IllegalArgumentException.class,()->new ComfyClient("http://example.com:8188"));var local=new ComfyClient("http://127.0.0.1:8192");assertThrows(IOException.class,()->local.video("clip.mp4","..\\private"));assertThrows(IOException.class,()->local.video("clip.mp4","a/../b"));assertThrows(IOException.class,()->local.video("../clip.mp4",""));
    }
    @Test void interruptedCollectionReusesOwnedFile()throws Exception{
        service.create(request);accepted();service.poll();completedHistory();String fileId=UUID.nameUUIDFromBytes(("comfy:"+id).getBytes(StandardCharsets.UTF_8)).toString();
        assertEquals(1,mapper.claimCollect(id,"RUNNING","/api/v1/files/"+fileId));Path partial=Path.of("target/comfy-test-files",fileId);Files.createDirectories(partial.getParent());Files.write(partial,new byte[]{1,2,3});
        service.recover();assertEquals("UNKNOWN",mapper.find(id).getState());service.poll();assertEquals("SUCCEEDED",mapper.find(id).getState());assertEquals(12,Files.size(partial));assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM media_file WHERE id=?",Integer.class,fileId));
        service.poll();assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM media_file WHERE id=?",Integer.class,fileId));
    }
    @Test void interruptedSubmitBecomesUnknownWithoutResubmission()throws Exception{
        service.create(request);assertEquals(1,mapper.transition(id,"QUEUED","SUBMITTING",""));service.recover();assertEquals("UNKNOWN",mapper.find(id).getState());service.poll();verify(client,never()).submit(any());
    }
}
