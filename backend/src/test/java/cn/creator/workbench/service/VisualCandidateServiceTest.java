package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.WorkspaceMapper;
import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:visualneeds;MODE=MySQL;DB_CLOSE_DELAY=-1"})
class VisualCandidateServiceTest {
    @TempDir static Path files;
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry){registry.add("workbench.files-dir",()->files.toString());}
    @Autowired WorkspaceService workspace;
    @Autowired MediaService media;
    @Autowired WorkspaceMapper mapper;
    String projectId;
    JsonObject json(String value){return JsonParser.parseString(value).getAsJsonObject();}
    JsonObject project(){return workspace.load().getAsJsonArray("projects").asList().stream().map(JsonElement::getAsJsonObject).filter(p->p.get("id").getAsString().equals(projectId)).findFirst().orElseThrow();}
    void command(String type,JsonObject p){p.addProperty("projectId",projectId);workspace.execute(new WorkspaceCommand(type,p,workspace.load().get("version").getAsLong()));}
    @BeforeEach void prepare(){projectId="visual_"+UUID.randomUUID();var p=new JsonObject();p.addProperty("id",projectId);p.addProperty("title","通用画面需求测试");command("CREATE_PROJECT",p);}
    void video()throws Exception{command("CREATE_VISUAL_NEED",json("{\"id\":\"n\",\"title\":\"第12秒表情\",\"productionNodeId\":\"N27\",\"desiredStartMs\":12000,\"desiredEndMs\":15000}"));batch("b","VIDEO");asset("a","video/webm",projectId);command("IMPORT_VISUAL_CANDIDATE",json("{\"id\":\"c\",\"batchId\":\"b\",\"assetId\":\"a\",\"durationMs\":10000,\"costCents\":20}"));}
    void batch(String id,String kind){command("CREATE_VISUAL_BATCH",json("{\"id\":\""+id+"\",\"needId\":\"n\",\"mediaKind\":\""+kind+"\",\"prompt\":\"测试画面\",\"externalModel\":\"fixture-v1\",\"parameters\":{},\"budgetCents\":100}"));}
    String asset(String id,String type,String owner)throws Exception{var record=media.save(new MockMultipartFile("file","fixture",type,new byte[]{26,69,-33,-93,1,2,3,4}));var asset=new JsonObject();asset.addProperty("id",id);asset.addProperty("name",id);asset.addProperty("type",type);asset.addProperty("size",8);asset.addProperty("fileRef","/api/v1/files/"+record.getId());asset.addProperty("sha256",record.getSha256());asset.addProperty("projectId",owner);var p=new JsonObject();p.add("asset",asset);command("ADD_ASSET",p);return record.getId();}
    JsonObject adopt(){return json("{\"id\":\"p1\",\"candidateId\":\"c\",\"purpose\":\"TIMELINE\",\"sourceInMs\":2400,\"sourceOutMs\":3600,\"targetStartMs\":12000,\"targetEndMs\":13200,\"trackId\":\"V1\",\"reason\":\"表情自然\"}");}
    @Test void productionOwnershipIsRequiredAndSelectionDoesNotCompleteNode()throws Exception{
        video();var before=project().get("nodes").deepCopy();command("CREATE_VISUAL_NEED",json("{\"id\":\"independent\",\"title\":\"待定画面\",\"productionNodeId\":\"N29\"}"));command("ADOPT_VISUAL_CANDIDATE",adopt());var second=adopt();second.addProperty("id","p2");second.addProperty("sourceInMs",4000);second.addProperty("sourceOutMs",5800);second.addProperty("targetStartMs",13200);second.addProperty("targetEndMs",15000);command("ADOPT_VISUAL_CANDIDATE",second);assertEquals(before.getAsJsonObject().getAsJsonObject("N27").get("output"),project().getAsJsonObject("nodes").getAsJsonObject("N27").get("output"));assertEquals("NOT_STARTED",project().getAsJsonObject("nodes").getAsJsonObject("N27").get("status").getAsString());assertEquals(2,project().getAsJsonObject("visualWorkbench").getAsJsonArray("placements").size());
    }
    @Test void rangeOverlapReplacementIdempotencyAndRemovalAreEnforced()throws Exception{
        video();var invalid=adopt();invalid.addProperty("sourceOutMs",11000);assertEquals(400,assertThrows(BusinessException.class,()->command("ADOPT_VISUAL_CANDIDATE",invalid)).getStatus());command("ADOPT_VISUAL_CANDIDATE",adopt());command("ADOPT_VISUAL_CANDIDATE",adopt());assertEquals(1,project().getAsJsonObject("visualWorkbench").getAsJsonArray("placements").size());var overlap=adopt();overlap.addProperty("id","overlap");assertEquals(400,assertThrows(BusinessException.class,()->command("ADOPT_VISUAL_CANDIDATE",overlap)).getStatus());
        var replacement=adopt();replacement.addProperty("id","p2");replacement.addProperty("replacesId","p1");command("ADOPT_VISUAL_CANDIDATE",replacement);command("ADOPT_VISUAL_CANDIDATE",replacement);command("REMOVE_VISUAL_PLACEMENT",json("{\"placementId\":\"p2\",\"reason\":\"换其他画面\"}"));var placements=project().getAsJsonObject("visualWorkbench").getAsJsonArray("placements");assertEquals(2,placements.size());assertFalse(placements.get(0).getAsJsonObject().get("active").getAsBoolean());assertFalse(placements.get(1).getAsJsonObject().get("active").getAsBoolean());
    }
    @Test void imagesCanBeReferencesOrTimedStillsAndKindsCannotBeMixed()throws Exception{
        video();batch("images","IMAGE");asset("pic","image/png",projectId);command("IMPORT_VISUAL_CANDIDATE",json("{\"id\":\"image\",\"batchId\":\"images\",\"assetId\":\"pic\",\"costCents\":0}"));command("ADOPT_VISUAL_CANDIDATE",json("{\"id\":\"ref\",\"candidateId\":\"image\",\"purpose\":\"REFERENCE\",\"referenceRole\":\"FIRST_FRAME\",\"reason\":\"人物一致\"}"));command("ADOPT_VISUAL_CANDIDATE",json("{\"id\":\"still\",\"candidateId\":\"image\",\"purpose\":\"TIMELINE\",\"targetStartMs\":12000,\"targetEndMs\":13000,\"reason\":\"静态画面\"}"));assertEquals(400,assertThrows(BusinessException.class,()->command("IMPORT_VISUAL_CANDIDATE",json("{\"id\":\"wrong\",\"batchId\":\"images\",\"assetId\":\"a\",\"costCents\":0}"))).getStatus());assertEquals(2,project().getAsJsonObject("visualWorkbench").getAsJsonArray("placements").size());
    }
    @Test void actualEditingUseInvalidatesWithoutOverwritingOutputs()throws Exception{
        video();command("ADOPT_VISUAL_CANDIDATE",adopt());command("USE_VISUAL_PLAN",json("{\"nodeId\":\"N31\",\"placementIds\":[\"p1\"]}"));var state=workspace.load();var p=state.getAsJsonArray("projects").asList().stream().map(JsonElement::getAsJsonObject).filter(x->x.get("id").getAsString().equals(projectId)).findFirst().orElseThrow();for(var entry:p.getAsJsonObject("nodes").entrySet()){var node=entry.getValue().getAsJsonObject();node.addProperty("status","COMPLETED");node.addProperty("revision",1);node.addProperty("draft","原草稿");node.addProperty("output","原产物");}p.getAsJsonObject("nodes").getAsJsonObject("N37").add("dependencies",json("{\"N31\":1}"));long version=state.get("version").getAsLong();state.addProperty("version",version+1);assertEquals(1,mapper.updateWorkspace("local",state.toString(),version));
        var replacement=adopt();replacement.addProperty("id","replacement");replacement.addProperty("replacesId","p1");replacement.addProperty("sourceInMs",3000);replacement.addProperty("sourceOutMs",4200);command("ADOPT_VISUAL_CANDIDATE",replacement);var nodes=project().getAsJsonObject("nodes");assertEquals("NEEDS_REVALIDATION",nodes.getAsJsonObject("N31").get("status").getAsString());assertEquals("NEEDS_REVALIDATION",nodes.getAsJsonObject("N37").get("status").getAsString());assertEquals("COMPLETED",nodes.getAsJsonObject("N29").get("status").getAsString());assertEquals("原草稿",nodes.getAsJsonObject("N31").get("draft").getAsString());assertEquals("原产物",nodes.getAsJsonObject("N31").get("output").getAsString());assertEquals(1,nodes.getAsJsonObject("N31").get("revision").getAsInt());assertEquals(2,nodes.getAsJsonObject("N31").get("visualInputRevision").getAsInt());assertEquals(1,VisualCandidateService.inputs(project(),"N31").getAsJsonArray("placements").size());assertNull(VisualCandidateService.inputs(project(),"N08"));assertEquals("COMPLETED",nodes.getAsJsonObject("N08").get("status").getAsString());
    }
    @Test void legacyMigrationPreservesOriginalDataAndPersistsExactlyOnce(){
        var state=workspace.load();var p=state.getAsJsonArray("projects").get(0).getAsJsonObject();var legacy=json("{\"shots\":[{\"id\":\"old\",\"title\":\"旧镜头\",\"nodeId\":\"N29\",\"selectionRevision\":2,\"selectedCandidateId\":\"old-c\",\"createdAt\":\"\"}],\"batches\":[],\"candidates\":[],\"adoptions\":[{\"previousOutput\":\"旧产物\",\"previousDraft\":\"旧草稿\"}]}");p.add("videoWorkbench",legacy);var before=p.get("nodes").deepCopy();long version=state.get("version").getAsLong();state.addProperty("version",version+1);assertEquals(1,mapper.updateWorkspace("local",state.toString(),version));var migrated=workspace.load();assertEquals(version+2,migrated.get("version").getAsLong());var next=migrated.getAsJsonArray("projects").get(0).getAsJsonObject();assertEquals(legacy,next.get("videoWorkbench"));assertEquals(before,next.get("nodes"));assertEquals(0,next.getAsJsonObject("visualWorkbench").getAsJsonArray("placements").size());assertEquals("old-c",next.getAsJsonObject("visualWorkbench").getAsJsonArray("needs").get(0).getAsJsonObject().get("legacySelectedCandidateId").getAsString());assertEquals(migrated,workspace.load());
    }
    @Test void fileIntegrityBudgetAndCredentialsRemainProtected()throws Exception{
        video();String other=asset("extra","video/webm",projectId);assertEquals(400,assertThrows(BusinessException.class,()->command("IMPORT_VISUAL_CANDIDATE",json("{\"id\":\"over\",\"batchId\":\"b\",\"assetId\":\"extra\",\"costCents\":81}"))).getStatus());assertEquals(400,assertThrows(BusinessException.class,()->command("CREATE_VISUAL_BATCH",json("{\"id\":\"bad\",\"needId\":\"n\",\"mediaKind\":\"VIDEO\",\"prompt\":\"x\",\"externalModel\":\"x\",\"budgetCents\":0,\"parameters\":{\"token\":\"EXAMPLE_ONLY\"}}"))).getStatus());
        String ref=project().getAsJsonObject("visualWorkbench").getAsJsonArray("candidates").get(0).getAsJsonObject().get("fileRef").getAsString();Files.write(files.resolve(ref.substring(ref.lastIndexOf('/')+1)),new byte[]{0});assertEquals(409,assertThrows(BusinessException.class,()->command("ADOPT_VISUAL_CANDIDATE",adopt())).getStatus());assertEquals(0,project().getAsJsonObject("visualWorkbench").getAsJsonArray("placements").size());assertNotNull(other);
    }
}
