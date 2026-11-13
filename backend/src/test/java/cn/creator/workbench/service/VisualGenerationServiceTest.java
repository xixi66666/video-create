package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.*;
import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:visualjobs;MODE=MySQL;DB_CLOSE_DELAY=-1"})
class VisualGenerationServiceTest {
    @TempDir static Path directory;
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry){registry.add("workbench.files-dir",()->directory.toString());}
    @Autowired WorkspaceService workspace;
    @Autowired WorkspaceMapper workspaceMapper;
    @Autowired VisualGenerationService service;
    @Autowired VisualJobMapper jobs;
    @MockitoBean MediaExecutorClient executor;
    String projectId;
    JsonObject json(String value){return JsonParser.parseString(value).getAsJsonObject();}
    JsonObject command(String type,JsonObject data){data.addProperty("projectId",projectId);return workspace.execute(new WorkspaceCommand(type,data,workspace.load().get("version").getAsLong()));}
    JsonObject project(){return workspace.load().getAsJsonArray("projects").asList().stream().map(JsonElement::getAsJsonObject).filter(p->p.get("id").getAsString().equals(projectId)).findFirst().orElseThrow();}
    @BeforeEach void prepare(){
        when(executor.readiness()).thenReturn(json("{\"online\":true,\"mediaKinds\":[\"IMAGE\",\"VIDEO\"],\"supportsSeed\":true}"));when(executor.configured()).thenReturn(false);
        projectId="generation_"+UUID.randomUUID();command("CREATE_PROJECT",json("{\"id\":\""+projectId+"\",\"title\":\"制作队列隔离验收\"}"));command("CREATE_VISUAL_NEED",json("{\"id\":\"n\",\"title\":\"表情\",\"productionNodeId\":\"N27\"}"));command("CREATE_VISUAL_BATCH",json("{\"id\":\"b\",\"needId\":\"n\",\"mediaKind\":\"VIDEO\",\"prompt\":\"自然表情\",\"externalModel\":\"远端已登记模板\",\"parameters\":{\"templateId\":\"sample\"},\"budgetCents\":100}"));
        // 仅在测试内存库建立已确认前提，正式业务必须通过原流程与人工拍板。
        var state=workspace.load();var p=state.getAsJsonArray("projects").get(0).getAsJsonObject();p.getAsJsonObject("nodes").entrySet().forEach(e->{var n=e.getValue().getAsJsonObject();n.addProperty("status","COMPLETED");n.addProperty("revision",1);n.addProperty("draft","已确认测试材料");n.addProperty("output","已确认测试材料");});
        for(var item:workspace.catalog().getAsJsonArray("gates")){var gate=item.getAsJsonObject();boolean platform=gate.has("scope")&&gate.get("scope").getAsString().equals("PLATFORM");var platforms=platform?p.getAsJsonArray("platforms"):new JsonArray();if(!platform)platforms.add("");for(var value:platforms){String key=value.getAsString();var parts=new ArrayList<String>();p.getAsJsonArray("platforms").forEach(x->parts.add(x.getAsString()));var watched=new ArrayList<String>();gate.getAsJsonArray("watches").forEach(x->watched.add(x.getAsString()+"@1:COMPLETED"));String fp=projectId+"|"+(key.isEmpty()?"":key+"|")+String.join(",",parts)+"|"+String.join("|",watched);var approval=new JsonObject();approval.addProperty("decision","APPROVED");approval.addProperty("fingerprint",fp);p.getAsJsonObject("approvals").add(gate.get("id").getAsString()+(key.isEmpty()?"":":"+key),approval);}}
        long v=state.get("version").getAsLong();state.addProperty("version",v+1);assertEquals(1,workspaceMapper.updateWorkspace("local",state.toString(),v));
    }
    JsonObject request(){var p=json("{\"id\":\"draw_"+UUID.randomUUID()+"\",\"projectId\":\""+projectId+"\",\"batchId\":\"b\",\"count\":1,\"maxCostCents\":30,\"seedStart\":123}");p.addProperty("expectedVersion",workspace.load().get("version").getAsLong());return p;}
    @Test void boundedOwnershipAndUnconfiguredExecutorAreRejected(){
        assertThrows(BusinessException.class,()->command("CREATE_VISUAL_NEED",json("{\"id\":\"bad\",\"title\":\"x\",\"productionNodeId\":\"N08\"}")));
        when(executor.readiness()).thenReturn(json("{\"online\":false,\"message\":\"尚未配置\"}"));assertEquals(503,assertThrows(BusinessException.class,()->service.create(request())).getStatus());assertTrue(service.list(projectId).isEmpty());
    }
    @Test void queueIsPersistentIdempotentAndReservesBatchBudget(){var request=request();request.addProperty("count",2);var created=service.create(request);assertEquals(2,created.size());assertEquals(created,service.create(request));assertEquals(2,service.list(projectId).size());assertEquals(123,JsonParser.parseString(jobs.find(created.get(0).getAsJsonObject().get("id").getAsString()).getPayload()).getAsJsonObject().get("seed").getAsInt());var over=request();over.addProperty("count",2);assertThrows(BusinessException.class,()->service.create(over));request.addProperty("seedStart",300);assertEquals(409,assertThrows(BusinessException.class,()->service.create(request)).getStatus());}
    @Test void unknownSubmissionQueriesOriginalJobAndNeverResubmits(){String id=service.create(request()).get(0).getAsJsonObject().get("id").getAsString();when(executor.submit(any())).thenThrow(new BusinessException(503,"模拟受理超时"));service.process(jobs.find(id));assertEquals("UNKNOWN",jobs.find(id).getState());when(executor.status(id)).thenThrow(new BusinessException(404,"原任务尚未查到"));service.process(jobs.find(id));service.control(id,json("{\"action\":\"RECOVER\"}"));service.process(jobs.find(id));verify(executor,times(1)).submit(any());assertEquals(1,service.list(projectId).size());}
    @Test void resultIsCollectedOnceWithoutAdoptionOrNodeOverwrite()throws Exception{
        String id=service.create(request()).get(0).getAsJsonObject().get("id").getAsString();when(executor.submit(any())).thenReturn(json("{\"id\":\""+id+"\"}"));service.process(jobs.find(id));var before=project().get("nodes").deepCopy();byte[] bytes=Files.readAllBytes(Path.of("../frontend/tests/fixtures/blue.webm"));String sha=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));when(executor.status(id)).thenReturn(json("{\"id\":\""+id+"\",\"state\":\"SUCCEEDED\",\"costCents\":20,\"outputs\":[{\"id\":\"out\",\"fileName\":\"generated.webm\",\"mediaType\":\"video/webm\",\"durationMs\":600,\"sha256\":\""+sha+"\"}]}"));when(executor.output(id,"out")).thenReturn(bytes);service.process(jobs.find(id));assertEquals("SUCCEEDED",jobs.find(id).getState());assertEquals(1,project().getAsJsonObject("visualWorkbench").getAsJsonArray("candidates").size());assertEquals(0,project().getAsJsonObject("visualWorkbench").getAsJsonArray("placements").size());assertEquals(before,project().get("nodes"));assertEquals(1,workspace.load().getAsJsonArray("assets").size());
    }
    @Test void cancelQueuedDoesNotCallExecutorAndRunningWaitsForAcknowledgement(){String id=service.create(request()).get(0).getAsJsonObject().get("id").getAsString();service.control(id,json("{\"action\":\"CANCEL\"}"));assertEquals("CANCELLED",jobs.find(id).getState());verify(executor,never()).cancel(any());String running=service.create(request()).get(0).getAsJsonObject().get("id").getAsString();when(executor.submit(any())).thenReturn(json("{\"id\":\""+running+"\"}"));service.process(jobs.find(running));service.control(running,json("{\"action\":\"CANCEL\"}"));when(executor.status(running)).thenReturn(json("{\"id\":\""+running+"\",\"state\":\"RUNNING\"}"));service.process(jobs.find(running));assertEquals("CANCEL_REQUESTED",jobs.find(running).getState());when(executor.status(running)).thenReturn(json("{\"id\":\""+running+"\",\"state\":\"CANCELLED\"}"));service.process(jobs.find(running));assertEquals("CANCELLED",jobs.find(running).getState());}
}
