package cn.creator.workbench;

import com.google.gson.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import cn.creator.workbench.persistence.WorkspaceMapper;
import cn.creator.workbench.service.BusinessException;
import cn.creator.workbench.service.WorkspaceService;
import org.springframework.boot.test.context.SpringBootTest;
import java.net.URI;
import java.net.http.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={"spring.datasource.url=jdbc:h2:mem:workbenchtest;MODE=MySQL;DB_CLOSE_DELAY=-1","workbench.files-dir=${java.io.tmpdir}/creator-workbench-test-files"})
class WorkbenchIntegrationTest {
    @Value("${local.server.port}") int port;
    @Autowired WorkspaceMapper mapper;
    @Autowired WorkspaceService workspace;
    final HttpClient http=HttpClient.newHttpClient();
    JsonObject load()throws Exception{return JsonParser.parseString(http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/workspace")).GET().build(),HttpResponse.BodyHandlers.ofString()).body()).getAsJsonObject().getAsJsonObject("data");}
    HttpResponse<String> command(String type,JsonObject payload,long version)throws Exception{var body=new JsonObject();body.addProperty("type",type);body.add("payload",payload);body.addProperty("expectedVersion",version);return http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/commands")).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(body.toString())).build(),HttpResponse.BodyHandlers.ofString());}
    @Test void voiceCastPersistsAndRejectsStaleVersion()throws Exception{
        var create=new JsonObject();String id="voice_"+UUID.randomUUID();create.addProperty("id",id);create.addProperty("title","声音测试");
        assertEquals(200,command("CREATE_PROJECT",create,load().get("version").getAsLong()).statusCode());
        long version=load().get("version").getAsLong();
        var payload=JsonParser.parseString("{\"cast\":[{\"speaker\":\"旁白\",\"roleId\":\"narrator_one\",\"name\":\"朗诵\",\"version\":\"1.0.0\"}]}").getAsJsonObject();
        payload.addProperty("projectId",id);
        assertEquals(200,command("SET_VOICE_CAST",payload,version).statusCode());
        assertEquals("narrator_one",project(id).getAsJsonArray("voiceCast").get(0).getAsJsonObject().get("roleId").getAsString());
        assertEquals(409,command("SET_VOICE_CAST",payload,version).statusCode());
    }
    @Test void credentialParametersAreRejectedWithoutChangingWorkspace()throws Exception{
        var initial=load();long version=initial.get("version").getAsLong();
        var model=JsonParser.parseString("""
            {"id":"credential-policy-test","name":"凭据校验","provider":"test","protocol":"CUSTOM_HTTP","baseUrl":"https://example.invalid","remoteModelId":"fixture","credentialRef":"CREATOR_TEST_KEY","capabilities":["TEXT_REASONING"]}
            """).getAsJsonObject();
        String[] cases={"{\"token\":\"EXAMPLE_ONLY\"}","{\"headers\":\"Bearer EXAMPLE_ONLY\"}","{\"auth\":\"EXAMPLE_ONLY\"}","{\"x-api-key\":\"EXAMPLE_ONLY\"}","{\"response_format\":{\"headers\":{\"Authorization\":\"EXAMPLE_ONLY\"}}}","{\"stop\":[\"Bearer EXAMPLE_ONLY\"]}","{\"stop\":\"sk-AUDIT_EXAMPLE_ONLY_0000\"}","{\"stop\":\"eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ0ZXN0In0.EXAMPLE_ONLY_SIGNATURE\"}","{\"stop\":\"-----BEGIN PRIVATE KEY----- EXAMPLE_ONLY\"}","{\"custom_option\":1}"};
        for(String parameters:cases){
            model.add("parameters",JsonParser.parseString(parameters));var payload=new JsonObject();payload.add("model",model);
            var response=command("SAVE_MODEL",payload,version);assertEquals(400,response.statusCode(),response.body());
            assertEquals(initial,load(),"无效配置不得写入工作区");
            assertFalse(response.body().contains("EXAMPLE_ONLY"),"错误不能回显凭据值");
        }
        model.add("parameters",JsonParser.parseString("{\"temperature\":0.6,\"maxOutputTokens\":4096,\"response_format\":{\"type\":\"json_object\"}}"));
        var payload=new JsonObject();payload.add("model",model);assertEquals(200,command("SAVE_MODEL",payload,version).statusCode());
    }
    @Test void persistenceVersionConflictAndGatesAreEnforced()throws Exception{
        var initial=load();long version=initial.get("version").getAsLong();var p=new JsonObject();String id="test_"+UUID.randomUUID();p.addProperty("id",id);p.addProperty("title","集成测试作品");p.addProperty("template","SCREENCAST");var created=command("CREATE_PROJECT",p,version);assertEquals(200,created.statusCode(),created.body());var after=load();assertEquals(version+1,after.get("version").getAsLong());assertEquals(49,after.getAsJsonArray("projects").get(0).getAsJsonObject().getAsJsonObject("nodes").size());assertEquals(409,command("CREATE_PROJECT",p,version).statusCode());
        var result=new JsonObject();result.addProperty("projectId",id);result.addProperty("nodeId","N15");result.addProperty("text","不能越过立项");result.addProperty("complete",true);assertEquals(409,command("SAVE_NODE",result,version+1).statusCode());result.addProperty("nodeId","N02");result.addProperty("text","我的真实资源");assertEquals(200,command("SAVE_NODE",result,version+1).statusCode());assertEquals("我的真实资源",load().getAsJsonArray("projects").get(0).getAsJsonObject().getAsJsonObject("nodes").getAsJsonObject("N02").get("output").getAsString());
    }
    @Test void foreignBrowserOriginCannotWrite()throws Exception{
        var response=http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/commands")).header("Origin","https://untrusted.example.invalid").header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString("{}")).build(),HttpResponse.BodyHandlers.ofString());assertEquals(403,response.statusCode());
    }
    @Test void defaultModelAndRecoverableTaskDeletionArePersistent()throws Exception{
        String modelId="model_"+UUID.randomUUID();
        var model=JsonParser.parseString("""
            {"name":"测试默认模型","provider":"test","protocol":"CUSTOM_HTTP","baseUrl":"https://provider.example.invalid","remoteModelId":"writer","credentialRef":"CREATOR_TEST_KEY","capabilities":["TEXT_REASONING"],"parameters":{}}
            """).getAsJsonObject();model.addProperty("id",modelId);
        var payload=new JsonObject();payload.add("model",model);
        assertEquals(200,command("SAVE_MODEL",payload,load().get("version").getAsLong()).statusCode());
        payload=new JsonObject();payload.addProperty("scope","GLOBAL");payload.addProperty("modelId",modelId);
        assertEquals(200,command("SET_DEFAULT_MODEL",payload,load().get("version").getAsLong()).statusCode());
        assertEquals(modelId,load().getAsJsonObject("globalBindings").get("$default").getAsString());
        String projectId=load().getAsJsonArray("projects").get(0).getAsJsonObject().get("id").getAsString();
        payload=new JsonObject();payload.addProperty("projectId",projectId);
        assertEquals(200,command("PLAN_PROJECT",payload,load().get("version").getAsLong()).statusCode());
        var before=load();String taskId=before.getAsJsonArray("tasks").get(0).getAsJsonObject().get("id").getAsString();
        payload=new JsonObject();payload.addProperty("id",taskId);
        assertEquals(200,command("DELETE_TASK",payload,before.get("version").getAsLong()).statusCode());
        var deleted=load();assertTrue(deleted.getAsJsonArray("tasks").get(0).getAsJsonObject().has("deletedAt"));assertEquals(before.get("projects"),deleted.get("projects"));
        assertEquals(200,command("RESTORE_TASK",payload,deleted.get("version").getAsLong()).statusCode());
        assertFalse(load().getAsJsonArray("tasks").get(0).getAsJsonObject().has("deletedAt"));
        payload.addProperty("id","missing-task");assertEquals(404,command("DELETE_TASK",payload,load().get("version").getAsLong()).statusCode());
    }
    @Test void readingLegacyWorkspaceArchivesRetiredNodeOnceWithVersionChange()throws Exception{
        var legacy=load();long version=legacy.get("version").getAsLong();
        var project=legacy.getAsJsonArray("projects").get(0).getAsJsonObject();
        var node=JsonParser.parseString("""
            {"status":"COMPLETED","output":"历史目标原件","draft":"历史目标原件","revision":3,"dependencies":{}}
            """).getAsJsonObject();
        project.getAsJsonObject("nodes").add("N01",node);
        project.getAsJsonObject("nodes").getAsJsonObject("N02").getAsJsonObject("dependencies").addProperty("N01",3);
        legacy.addProperty("version",version+1);assertEquals(1,mapper.updateWorkspace("local",legacy.toString(),version));
        var migrated=load();assertEquals(version+2,migrated.get("version").getAsLong());
        var result=migrated.getAsJsonArray("projects").get(0).getAsJsonObject();
        assertEquals("历史目标原件",result.getAsJsonObject("archivedNodes").getAsJsonObject("N01").get("output").getAsString());
        assertFalse(result.getAsJsonObject("nodes").has("N01"));assertEquals(migrated,load());
    }
    @Test void projectStatusAndTemplateConditionalSkipAreEnforced()throws Exception{
        var initial=load();long version=initial.get("version").getAsLong();var p=new JsonObject();String id="project_"+UUID.randomUUID();p.addProperty("id",id);p.addProperty("title","真人口播状态测试");p.addProperty("template","REAL_PERSON");
        assertEquals(200,command("CREATE_PROJECT",p,version).statusCode());
        var skip=new JsonObject();skip.addProperty("projectId",id);skip.addProperty("nodeId","N25");skip.addProperty("reason","不想拍");assertEquals(400,command("SKIP_NODE",skip,load().get("version").getAsLong()).statusCode());
        skip.addProperty("nodeId","N26");assertEquals(200,command("SKIP_NODE",skip,load().get("version").getAsLong()).statusCode());
        var status=new JsonObject();status.addProperty("projectId",id);status.addProperty("status","PAUSED");assertEquals(200,command("SET_PROJECT_STATUS",status,load().get("version").getAsLong()).statusCode());
        var save=new JsonObject();save.addProperty("projectId",id);save.addProperty("nodeId","N02");save.addProperty("text","暂停时不能完成");save.addProperty("complete",true);assertEquals(409,command("SAVE_NODE",save,load().get("version").getAsLong()).statusCode());
        status.addProperty("status","ACTIVE");assertEquals(200,command("SET_PROJECT_STATUS",status,load().get("version").getAsLong()).statusCode());assertEquals(200,command("SAVE_NODE",save,load().get("version").getAsLong()).statusCode());
    }
    JsonObject project(String id)throws Exception{for(var item:load().getAsJsonArray("projects")){var p=item.getAsJsonObject();if(p.get("id").getAsString().equals(id))return p;}throw new AssertionError("project missing");}
    JsonObject gate(String id){for(var item:workspace.catalog().getAsJsonArray("gates")){var g=item.getAsJsonObject();if(g.get("id").getAsString().equals(id))return g;}throw new AssertionError("gate missing");}
    static String fingerprint(JsonObject project,JsonObject gate,String platform){
        var parts=new ArrayList<String>();project.getAsJsonArray("platforms").forEach(p->parts.add(p.getAsString()));
        StringBuilder b=new StringBuilder(project.get("id").getAsString()+"|"+(platform==null?"":platform+"|")+String.join(",",parts)+"|");var versions=new ArrayList<String>();
        gate.getAsJsonArray("watches").forEach(k->{var n=project.getAsJsonObject("nodes").getAsJsonObject(k.getAsString());versions.add(k.getAsString()+"@"+n.get("revision").getAsInt()+":"+n.get("status").getAsString());});
        return b+String.join("|",versions);
    }
    @Test void platformApprovalIsIndependentAndBlocksDownstreamUntilComplete()throws Exception{
        var initial=load();var create=new JsonObject();String id="platform_"+UUID.randomUUID();create.addProperty("id",id);create.addProperty("title","平台拍板测试");
        assertEquals(200,command("CREATE_PROJECT",create,initial.get("version").getAsLong()).statusCode());
        var state=load();var project=state.getAsJsonArray("projects").asList().stream().map(JsonElement::getAsJsonObject).filter(p->p.get("id").getAsString().equals(id)).findFirst().orElseThrow();
        for(int i=31;i<=41;i++){var node=project.getAsJsonObject("nodes").getAsJsonObject("N"+i);node.addProperty("status","COMPLETED");node.addProperty("draft","平台测试");node.addProperty("output","平台测试");node.addProperty("revision",1);}
        long version=state.get("version").getAsLong();state.addProperty("version",version+1);assertEquals(1,mapper.updateWorkspace("local",state.toString(),version));
        var g=gate("G04");var payload=new JsonObject();payload.addProperty("projectId",id);payload.addProperty("gateId","G04");payload.addProperty("platform","DOUYIN");payload.addProperty("fingerprint",fingerprint(project(id),g,"DOUYIN"));
        assertEquals(200,command("APPROVE_GATE",payload,load().get("version").getAsLong()).statusCode());
        assertEquals(409,assertThrows(BusinessException.class,()->workspace.requireExecutable(project(id),"N42")).getStatus());
        payload.addProperty("platform","XIAOHONGSHU");payload.addProperty("fingerprint",fingerprint(project(id),g,"XIAOHONGSHU"));
        assertEquals(200,command("APPROVE_GATE",payload,load().get("version").getAsLong()).statusCode());
        assertDoesNotThrow(()->workspace.requireExecutable(project(id),"N42"));
    }
    @Test void catalogAndHealthDoNotPretendExternalExecution()throws Exception{
        var response=http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/catalog")).GET().build(),HttpResponse.BodyHandlers.ofString());assertEquals(200,response.statusCode());assertEquals(49,JsonParser.parseString(response.body()).getAsJsonObject().getAsJsonObject("data").getAsJsonArray("nodes").size());
        var health=http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/health")).GET().build(),HttpResponse.BodyHandlers.ofString());assertFalse(JsonParser.parseString(health.body()).getAsJsonObject().getAsJsonObject("data").get("externalExecutionEnabled").getAsBoolean());
    }
}
