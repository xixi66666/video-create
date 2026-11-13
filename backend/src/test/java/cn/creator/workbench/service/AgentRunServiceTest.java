package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.AgentRunMapper;
import cn.creator.workbench.persistence.AgentRunRecord;
import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.jdbc.core.JdbcTemplate;
import java.nio.file.Path;
import java.util.UUID;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:agenttest;MODE=MySQL;DB_CLOSE_DELAY=-1"})
class AgentRunServiceTest {
    @TempDir static Path files;
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry){registry.add("workbench.files-dir",()->files.toString());}
    @Autowired AgentRunService service;
    @Autowired WorkspaceService workspace;
    @Autowired AgentRunMapper mapper;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean AgentRuntimeClient runtime;
    String projectId;
    @BeforeEach void prepare(){
        when(runtime.post(anyString(),any())).thenReturn(new JsonObject());
        when(runtime.get(anyString())).thenThrow(new BusinessException(503,"隔离测试通道"));
        projectId="p_"+UUID.randomUUID();var payload=new JsonObject();payload.addProperty("id",projectId);payload.addProperty("title","Agent 业务隔离测试");
        workspace.execute(new WorkspaceCommand("CREATE_PROJECT",payload,workspace.load().get("version").getAsLong()));
    }
    JsonObject request(String node){var p=new JsonObject();p.addProperty("id","run_"+UUID.randomUUID());p.addProperty("projectId",projectId);p.addProperty("nodeId",node);p.addProperty("mode","FIXTURE");return p;}
    @Test void consultationRolesAreValidatedAndPersisted(){
        var req=request("N08");req.add("consultationRoles",JsonParser.parseString("[\"FACT_CHECK\",\"WRITER\"]"));
        var created=service.create(req);assertEquals(2,created.getAsJsonArray("consultationRoles").size());
        var saved=JsonParser.parseString(mapper.find(req.get("id").getAsString()).getPayload()).getAsJsonObject();
        assertEquals(req.get("consultationRoles"),saved.get("consultationRoles"));
        assertTrue(saved.getAsJsonObject("models").has("consultant_FACT_CHECK"));
        assertTrue(saved.getAsJsonObject("models").has("consultant_WRITER"));
        assertTrue(saved.get("consultationComparison").getAsBoolean());
        assertDoesNotThrow(()->service.create(req));
        req.add("consultationRoles",JsonParser.parseString("[\"WRITER\"]"));
        assertThrows(BusinessException.class,()->service.create(req));
        var six=request("N08");six.add("consultationRoles",JsonParser.parseString("[\"FACT_CHECK\",\"WRITER\",\"QUALITY\",\"AUDIO\",\"IMAGE\",\"VIDEO\"]"));
        var sixRun=service.create(six);assertEquals(6,sixRun.getAsJsonArray("consultationRoles").size());
        var sixPayload=JsonParser.parseString(mapper.find(six.get("id").getAsString()).getPayload()).getAsJsonObject();
        assertTrue(sixPayload.getAsJsonObject("models").has("consultant_VIDEO"));
        for(String roles:java.util.List.of("[\"FACT_CHECK\",\"FACT_CHECK\"]","[\"SUPERVISOR\"]","[\"TOPIC_RESEARCH\"]","[\"FACT_CHECK\",\"WRITER\",\"QUALITY\",\"AUDIO\",\"IMAGE\",\"VIDEO\",\"DIRECTOR\"]")){
            var invalid=request("N08");invalid.add("consultationRoles",JsonParser.parseString(roles));
            assertThrows(BusinessException.class,()->service.create(invalid));
        }
    }
    JsonObject decision(){var p=new JsonObject();p.addProperty("decision","ACCEPT");return p;}
    void waiting(String id){
        doReturn(JsonParser.parseString("""
            {"status":"WAITING_ACCEPTANCE","artifacts":[{"kind":"CANDIDATE","content":{"body":"测试候选，不可发布","fields":{"idea":"测试"},"fixture":true}}]}
            """).getAsJsonObject()).when(runtime).get("/runs/"+id);
    }
    JsonObject currentNode(){
        for(var item:workspace.load().getAsJsonArray("projects")){
            var project=item.getAsJsonObject();
            if(project.get("id").getAsString().equals(projectId))return project.getAsJsonObject("nodes").getAsJsonObject("N08");
        }
        throw new AssertionError("测试作品不存在");
    }
    void save(String text,boolean complete,JsonObject review,long expectedVersion){
        var payload=new JsonObject();payload.addProperty("projectId",projectId);payload.addProperty("nodeId","N08");payload.addProperty("text",text);payload.addProperty("complete",complete);
        if(review!=null)payload.add("agentReview",review);
        workspace.execute(new WorkspaceCommand("SAVE_NODE",payload,expectedVersion));
    }
    JsonObject review(String runId,boolean replaced){
        var value=new JsonObject();value.addProperty("runId",runId);value.addProperty("acknowledged",true);value.addProperty("fixtureReplaced",replaced);return value;
    }
    @Test void dependenciesLiveSwitchAndIdempotentOutbox(){
        assertEquals(409,assertThrows(BusinessException.class,()->service.create(request("N15"))).getStatus());
        var p=request("N08");var first=service.create(p);assertEquals(first,service.create(p));
        service.dispatch();assertEquals("SUBMITTED",mapper.find(p.get("id").getAsString()).getState());
        p.addProperty("nodeId","N02");assertThrows(BusinessException.class,()->service.create(p));
        var live=request("N08");live.addProperty("mode","LIVE");assertThrows(BusinessException.class,()->service.create(live));
    }
    @Test void adoptionWritesDraftOnlyAndIsIdempotent(){
        var p=request("N08");String id=p.get("id").getAsString();service.create(p);service.dispatch();waiting(id);
        service.decide(id,decision());long version=workspace.load().get("version").getAsLong();
        var project=workspace.load().getAsJsonArray("projects").get(0).getAsJsonObject();var node=project.getAsJsonObject("nodes").getAsJsonObject("N08");
        assertEquals("DRAFT",node.get("status").getAsString());assertEquals("",node.get("output").getAsString());assertTrue(node.get("draft").getAsString().contains("测试候选"));
        service.decide(id,decision());assertEquals(version,workspace.load().get("version").getAsLong());
        service.dispatch();assertEquals("ADOPTED",mapper.find(id).getState());
    }
    @Test void fixtureDraftRequiresReplacementAndExplicitReviewWithoutLosingProvenance(){
        var p=request("N08");String id=p.get("id").getAsString();service.create(p);service.dispatch();waiting(id);service.decide(id,decision());
        var node=currentNode();String fixture=node.get("draft").getAsString();var source=node.getAsJsonObject("agentDraftReview");
        assertEquals(id,source.get("runId").getAsString());assertTrue(source.get("fixture").getAsBoolean());assertTrue(source.getAsJsonArray("uncertainties").isEmpty());
        long version=workspace.load().get("version").getAsLong();
        assertEquals(409,assertThrows(BusinessException.class,()->save(fixture,true,null,version)).getStatus());
        assertEquals(409,assertThrows(BusinessException.class,()->save(fixture,true,review(id,true),version)).getStatus());
        assertEquals("DRAFT",currentNode().get("status").getAsString());
        String manual="我实际记录的创作想法";
        save(manual,false,null,version);
        assertEquals(id,currentNode().getAsJsonObject("agentDraftReview").get("runId").getAsString());
        long editedVersion=workspace.load().get("version").getAsLong();
        assertEquals(409,assertThrows(BusinessException.class,()->save(manual,true,review(id,true),version)).getStatus());
        assertEquals(409,assertThrows(BusinessException.class,()->save(manual,true,review("run_wrong",true),editedVersion)).getStatus());
        assertEquals(409,assertThrows(BusinessException.class,()->save(manual,true,review(id,false),editedVersion)).getStatus());
        save(manual,true,review(id,true),editedVersion);
        var completed=currentNode();assertEquals("COMPLETED",completed.get("status").getAsString());assertEquals(manual,completed.get("output").getAsString());
        assertTrue(completed.getAsJsonObject("agentDraftReview").get("reviewedByHuman").getAsBoolean());
        assertEquals(64,completed.getAsJsonObject("agentDraftReview").get("reviewedTextSha256").getAsString().length());
        long completedVersion=workspace.load().get("version").getAsLong();
        assertDoesNotThrow(()->save(manual,true,null,completedVersion));
    }
    @Test void expertDraftNeedsReviewButOrdinaryClientCannotSetOrEraseProvenance(){
        var p=new JsonObject();p.addProperty("projectId",projectId);p.addProperty("nodeId","N08");p.addProperty("text","手工内容");p.addProperty("complete",false);
        p.add("agentDraftReview",JsonParser.parseString("{\"runId\":\"forged\",\"fixture\":false}").getAsJsonObject());
        workspace.execute(new WorkspaceCommand("SAVE_NODE",p,workspace.load().get("version").getAsLong()));
        assertFalse(currentNode().has("agentDraftReview"));
        var source=JsonParser.parseString("{\"runId\":\"run_live_123\",\"fixture\":false,\"uncertainties\":[\"来源仍需复核\"]}").getAsJsonObject();
        workspace.saveAgentDraft(projectId,"N08","专家候选",source,workspace.load().get("version").getAsLong());
        p.addProperty("text","修改后的候选");p.add("agentDraftReview",new JsonObject());
        workspace.execute(new WorkspaceCommand("SAVE_NODE",p,workspace.load().get("version").getAsLong()));
        assertEquals("run_live_123",currentNode().getAsJsonObject("agentDraftReview").get("runId").getAsString());
        long version=workspace.load().get("version").getAsLong();
        assertEquals(409,assertThrows(BusinessException.class,()->save("修改后的候选",true,null,version)).getStatus());
        assertDoesNotThrow(()->save("修改后的候选",true,review("run_live_123",false),version));
    }
    @Test void ordinaryManualDraftStillCompletesWithoutReview(){
        assertDoesNotThrow(()->save("人工自由文本",true,null,workspace.load().get("version").getAsLong()));
        assertEquals("COMPLETED",currentNode().get("status").getAsString());
    }
    @Test void newExpertDraftMatchingExistingOutputStillRequiresReview(){
        String text="已有人工确认的内容";
        save(text,true,null,workspace.load().get("version").getAsLong());
        var source=JsonParser.parseString("{\"runId\":\"run_live_again\",\"fixture\":false,\"uncertainties\":[]}").getAsJsonObject();
        workspace.saveAgentDraft(projectId,"N08",text,source,workspace.load().get("version").getAsLong());
        long version=workspace.load().get("version").getAsLong();
        assertEquals(409,assertThrows(BusinessException.class,()->save(text,true,null,version)).getStatus());
        save(text,true,review("run_live_again",false),version);
        assertTrue(currentNode().getAsJsonObject("agentDraftReview").get("reviewedByHuman").getAsBoolean());
    }
    @Test void changedInputRejectsLateCandidateAndDeletionIsReversible(){
        var p=request("N08");String id=p.get("id").getAsString();service.create(p);service.dispatch();waiting(id);
        var edit=new JsonObject();edit.addProperty("projectId",projectId);edit.addProperty("nodeId","N08");edit.addProperty("text","人工新草稿");edit.addProperty("complete",false);
        workspace.execute(new WorkspaceCommand("SAVE_NODE",edit,workspace.load().get("version").getAsLong()));
        assertThrows(BusinessException.class,()->service.decide(id,decision()));
        var control=new JsonObject();control.addProperty("action","DELETE");service.control(id,control);assertNotNull(mapper.find(id).getDeletedAt());
        control.addProperty("action","RESTORE");service.control(id,control);assertNull(mapper.find(id).getDeletedAt());
    }
    @Test void deletedRunCannotBeAdoptedUntilRestored(){
        var p=request("N08");String id=p.get("id").getAsString();service.create(p);service.dispatch();waiting(id);
        var control=new JsonObject();control.addProperty("action","DELETE");service.control(id,control);
        assertEquals(409,assertThrows(BusinessException.class,()->service.decide(id,decision())).getStatus());
        assertNotEquals("DRAFT",currentNode().get("status").getAsString());
        control.addProperty("action","RESTORE");service.control(id,control);
        assertDoesNotThrow(()->service.decide(id,decision()));
    }
    @Test void permanentDispatchFailureIsVisibleAndRetryable(){
        when(runtime.post(anyString(),any())).thenThrow(new BusinessException(400,"测试永久投递错误"));
        var p=request("N08");String id=p.get("id").getAsString();service.create(p);
        service.dispatch();
        var failed=mapper.find(id);assertEquals("SUBMISSION_FAILED",failed.getState());assertEquals("测试永久投递错误",failed.getDispatchError());assertEquals(1,failed.getDispatchAttempts());
        var retry=new JsonObject();retry.addProperty("action","RETRY");service.control(id,retry);assertEquals("PENDING_SUBMISSION",mapper.find(id).getState());
    }
    @Test void olderPendingRunIsDispatchedDespiteMoreThan200RecentFinishedRuns() throws Exception {
        String prefix="run_outbox_"+UUID.randomUUID().toString().replace("-","");
        try {
            for(int i=0;i<200;i++){
                var finished=new AgentRunRecord();finished.setId(prefix+"_"+i);finished.setProjectId(projectId);finished.setNodeId("N08");
                finished.setPayload("{}");finished.setInputFingerprint("test");finished.setState("ADOPTED");finished.setCreatedAt("2099-01-01T00:00:00Z");mapper.insert(finished);
            }
            var pending=new AgentRunRecord();pending.setId(prefix+"_old");pending.setProjectId(projectId);pending.setNodeId("N08");
            pending.setPayload("{}");pending.setInputFingerprint("test");pending.setState("PENDING_SUBMISSION");pending.setCreatedAt("2000-01-01T00:00:00Z");mapper.insert(pending);
            assertFalse(mapper.list().stream().anyMatch(r->r.getId().equals(pending.getId())));
            assertTrue(mapper.pending().stream().anyMatch(r->r.getId().equals(pending.getId())));
            long end=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
            while(System.nanoTime()<end&&mapper.find(pending.getId()).getState().equals("PENDING_SUBMISSION")){service.dispatch();Thread.sleep(25);}
            assertEquals("SUBMITTED",mapper.find(pending.getId()).getState());
        } finally {
            jdbc.update("DELETE FROM agent_run_dispatch WHERE run_id LIKE ?",prefix+"%");
            jdbc.update("DELETE FROM agent_run WHERE id LIKE ?",prefix+"%");
        }
    }
    @Test void resolverInheritsCompatibleOverrides(){
        var state=JsonParser.parseString("""
        {"models":[{"id":"g","capabilities":["TEXT_REASONING"]},{"id":"p","capabilities":["TEXT_REASONING"]},{"id":"image","capabilities":["IMAGE_GENERATION"]}],"globalBindings":{"$default":"g"},"agentBindings":{"WRITER":{"$default":"g"}}}
        """).getAsJsonObject();
        var project=JsonParser.parseString("""
        {"bindings":{"$default":"p"},"nodeBindings":{"N22":{"$default":"image"}}}
        """).getAsJsonObject();
        assertEquals("p",AgentRunService.resolveModel(state,project,"WRITER","N22").get("id").getAsString());
        project.getAsJsonObject("nodeBindings").getAsJsonObject("N22").addProperty("TEXT_REASONING","g");
        assertEquals("g",AgentRunService.resolveModel(state,project,"WRITER","N22").get("id").getAsString());
    }
    @Test void consultantResolvesItsOwnRoleBinding(){
        var state=JsonParser.parseString("""
        {"models":[{"id":"global","capabilities":["TEXT_REASONING"]},{"id":"fact","capabilities":["TEXT_REASONING"]},{"id":"writer","capabilities":["TEXT_REASONING"]}],"globalBindings":{"$default":"global"},"agentBindings":{"FACT_CHECK":{"$default":"fact"},"WRITER":{"$default":"writer"}}}
        """).getAsJsonObject();
        var project=JsonParser.parseString("{\"bindings\":{},\"nodeBindings\":{}}").getAsJsonObject();
        assertEquals("fact",AgentRunService.resolveModel(state,project,"FACT_CHECK",null).get("id").getAsString());
        assertEquals("writer",AgentRunService.resolveModel(state,project,"WRITER",null).get("id").getAsString());
        assertEquals("global",AgentRunService.resolveModel(state,project,"ANALYST",null).get("id").getAsString());
    }
    @Test void unrelatedProductionNeedDoesNotInvalidateTextCandidate(){
        var need=JsonParser.parseString("{\"id\":\"visual-input\",\"title\":\"人物参考\",\"description\":\"第一版要求\",\"productionNodeId\":\"N27\"}").getAsJsonObject();need.addProperty("projectId",projectId);
        workspace.execute(new WorkspaceCommand("CREATE_VISUAL_NEED",need,workspace.load().get("version").getAsLong()));
        var request=request("N08");String id=request.get("id").getAsString();service.create(request);service.dispatch();waiting(id);
        need.remove("id");need.addProperty("needId","visual-input");need.addProperty("description","改为另一种人物风格");workspace.execute(new WorkspaceCommand("UPDATE_VISUAL_NEED",need,workspace.load().get("version").getAsLong()));
        assertDoesNotThrow(()->service.decide(id,decision()));
    }
}
