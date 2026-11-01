package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.AgentRunMapper;
import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.UUID;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:agenttest;MODE=MySQL;DB_CLOSE_DELAY=-1"})
class AgentRunServiceTest {
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
    JsonObject decision(){var p=new JsonObject();p.addProperty("decision","ACCEPT");return p;}
    void waiting(String id){
        doReturn(JsonParser.parseString("""
            {"status":"WAITING_ACCEPTANCE","artifacts":[{"kind":"CANDIDATE","content":{"body":"测试候选，不可发布","fields":{"idea":"测试"},"fixture":true}}]}
            """).getAsJsonObject()).when(runtime).get("/runs/"+id);
    }
    @Test void dependenciesLiveSwitchAndIdempotentOutbox(){
        assertEquals(409,assertThrows(BusinessException.class,()->service.create(request("N15"))).getStatus());
        var p=request("N08");var first=service.create(p);assertEquals(0,first.getAsJsonObject("limits").get("maxTotalTokens").getAsInt());assertEquals(first,service.create(p));
        service.dispatch();assertEquals("SUBMITTED",mapper.find(p.get("id").getAsString()).getState());
        p.addProperty("nodeId","N02");assertThrows(BusinessException.class,()->service.create(p));
        var live=request("N08");live.addProperty("mode","LIVE");assertThrows(BusinessException.class,()->service.create(live));
    }
    @Test void tokenLimitIsDisabledByDefaultAndCanBeExplicitlySet(){
        var request=new JsonObject();
        assertEquals(0,AgentRunService.limitsForRequest(request).get("maxTotalTokens").getAsInt());
        request.addProperty("maxTotalTokens",50000);
        assertEquals(50000,AgentRunService.limitsForRequest(request).get("maxTotalTokens").getAsInt());
        request.addProperty("maxTotalTokens",0);
        assertEquals(0,AgentRunService.limitsForRequest(request).get("maxTotalTokens").getAsInt());
    }
    @Test void customTokenLimitRejectsInvalidValuesAndIdReuseCannotChangeLimits(){
        for(String json:java.util.List.of("null","\"20000\"","-1","99","100001","1.5","true")){
            var requested=new JsonObject();requested.add("maxTotalTokens",JsonParser.parseString(json));
            assertEquals(400,assertThrows(BusinessException.class,()->AgentRunService.limitsForRequest(requested)).getStatus());
        }
        var original=request("N08");service.create(original);original.addProperty("maxTotalTokens",50000);
        assertEquals(409,assertThrows(BusinessException.class,()->service.create(original)).getStatus());
    }
    @Test void existingRunKeepsItsSavedLimitOnIdempotentRequest(){
        var request=request("N08");var result=service.create(request);String id=result.get("id").getAsString();
        var payload=JsonParser.parseString(mapper.find(id).getPayload()).getAsJsonObject();payload.getAsJsonObject("limits").addProperty("maxTotalTokens",20000);
        jdbc.update("UPDATE agent_run SET payload=? WHERE id=?",payload.toString(),id);
        assertEquals(20000,service.create(request).getAsJsonObject("limits").get("maxTotalTokens").getAsInt());
    }
    @Test void adoptionWritesDraftOnlyAndIsIdempotent(){
        var p=request("N08");String id=p.get("id").getAsString();service.create(p);service.dispatch();waiting(id);
        service.decide(id,decision());long version=workspace.load().get("version").getAsLong();
        var project=workspace.load().getAsJsonArray("projects").get(0).getAsJsonObject();var node=project.getAsJsonObject("nodes").getAsJsonObject("N08");
        assertEquals("DRAFT",node.get("status").getAsString());assertEquals("",node.get("output").getAsString());assertTrue(node.get("draft").getAsString().contains("测试候选"));
        service.decide(id,decision());assertEquals(version,workspace.load().get("version").getAsLong());
        service.dispatch();assertEquals("ADOPTED",mapper.find(id).getState());
    }
    @Test void changedInputRejectsLateCandidateAndDeletionIsReversible(){
        var p=request("N08");String id=p.get("id").getAsString();service.create(p);service.dispatch();waiting(id);
        var edit=new JsonObject();edit.addProperty("projectId",projectId);edit.addProperty("nodeId","N08");edit.addProperty("text","人工新草稿");edit.addProperty("complete",false);
        workspace.execute(new WorkspaceCommand("SAVE_NODE",edit,workspace.load().get("version").getAsLong()));
        assertThrows(BusinessException.class,()->service.decide(id,decision()));
        var control=new JsonObject();control.addProperty("action","DELETE");service.control(id,control);assertNotNull(mapper.find(id).getDeletedAt());
        control.addProperty("action","RESTORE");service.control(id,control);assertNull(mapper.find(id).getDeletedAt());
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
}
