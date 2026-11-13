package cn.creator.workbench.service;

import cn.creator.workbench.persistence.WorkspaceMapper;
import com.google.gson.*;
import org.springframework.stereotype.Service;
import java.time.Instant;
import java.util.*;

/** 通用画面需求与采用决定。采用记录不等于渲染结果，也不完成业务节点。 */
@Service
public class VisualCandidateService {
    private final WorkspaceMapper mapper;
    private final MediaService media;
    public VisualCandidateService(WorkspaceMapper mapper,MediaService media){this.mapper=mapper;this.media=media;}

    public Set<String> execute(JsonObject state,JsonObject project,String type,JsonObject p,JsonObject catalog){
        var w=workbench(project);
        return switch(type){
            case "CREATE_VISUAL_NEED", "UPDATE_VISUAL_NEED" -> saveNeed(w,p,catalog,type.equals("CREATE_VISUAL_NEED"));
            case "REMOVE_EMPTY_VISUAL_NEED" -> {var need=find(w,"needs",string(p,"needId",100,true));if(has(w,"batches","needId",need.get("id"))||has(w,"placements","needId",need.get("id")))throw bad("已有批次或采用历史的需求不能删除");w.getAsJsonArray("needs").remove(need);yield Set.of();}
            case "CREATE_VISUAL_BATCH" -> {createBatch(state,w,p);yield Set.of();}
            case "IMPORT_VISUAL_CANDIDATE" -> {importCandidate(state,project,w,p);yield Set.of();}
            case "SET_VISUAL_CANDIDATE_STATUS" -> {var candidate=find(w,"candidates",string(p,"candidateId",100,true));String status=string(p,"status",20,true);if(!Set.of("PENDING","KEPT","REJECTED").contains(status))throw bad("候选状态无效");if(status.equals("REJECTED")&&hasActive(w,"candidateId",candidate.get("id")))throw bad("正在使用的候选不能淘汰，请先撤销或替换采用");candidate.addProperty("status",status);yield Set.of();}
            case "ADOPT_VISUAL_CANDIDATE" -> adopt(w,p);
            case "USE_VISUAL_PLAN" -> usePlan(w,p);
            case "REMOVE_VISUAL_PLACEMENT" -> {var placement=find(w,"placements",string(p,"placementId",100,true));if(!placement.get("active").getAsBoolean())yield Set.of();placement.addProperty("removeReason",string(p,"reason",2000,true));placement.addProperty("removedAt",now());placement.addProperty("active",false);yield changed(w,find(w,"needs",placement.get("needId").getAsString()));}
            default -> throw bad("不支持的画面操作");
        };
    }

    private Set<String> saveNeed(JsonObject w,JsonObject p,JsonObject catalog,boolean create){
        var value=new JsonObject();value.addProperty("title",string(p,"title",120,true));value.addProperty("description",string(p,"description",10000,false));
        if(p.has("sourceNodeId")||p.has("consumerNodeIds"))throw bad("请使用制作任务归属，不再接受任意节点绑定");
        String owner=owner(string(p,"productionNodeId",5,true));value.addProperty("productionNodeId",owner);String shot=string(p,"shotId",100,false);if(!shot.isEmpty())value.addProperty("shotId",shot);
        if(p.has("desiredStartMs")||p.has("desiredEndMs")){var range=range(p,"desiredStartMs","desiredEndMs","目标范围");value.addProperty("desiredStartMs",range[0]);value.addProperty("desiredEndMs",range[1]);}
        if(create){value.addProperty("id",identifier(p,"id"));value.addProperty("revision",0);value.addProperty("createdAt",now());insert(w,"needs",value,300);return Set.of();}
        var need=find(w,"needs",string(p,"needId",100,true));if(need.has("productionNodeId")&&!need.get("productionNodeId").getAsString().equals(owner)&&hasActive(w,"needId",need.get("id")))throw bad("已有采用时不能更换归属，请先撤销采用");
        if(value.has("desiredStartMs"))for(var item:w.getAsJsonArray("placements")){var x=item.getAsJsonObject();if(active(x)&&x.get("needId").equals(need.get("id"))&&x.get("purpose").getAsString().equals("TIMELINE")&&(x.get("targetStartMs").getAsLong()<value.get("desiredStartMs").getAsLong()||x.get("targetEndMs").getAsLong()>value.get("desiredEndMs").getAsLong()))throw bad("新目标范围不能排除已有采用，请先调整采用区间");}
        need.remove("shotId");need.remove("desiredStartMs");need.remove("desiredEndMs");value.entrySet().forEach(e->need.add(e.getKey(),e.getValue()));
        boolean used=hasActive(w,"needId",need.get("id"));var current=changed(w,need);return used?current:Set.of();
    }

    private void createBatch(JsonObject state,JsonObject w,JsonObject p){
        var need=find(w,"needs",string(p,"needId",100,true));owner(string(need,"productionNodeId",5,true));String kind=string(p,"mediaKind",10,true);if(!Set.of("IMAGE","VIDEO").contains(kind))throw bad("候选类型无效");
        JsonElement parameters=p.has("parameters")?p.get("parameters"):new JsonObject();ModelParameterPolicy.validateRecordingParameters(parameters);if(parameters.toString().length()>20000)throw bad("参数过长");
        var batch=new JsonObject();batch.addProperty("id",identifier(p,"id"));batch.add("needId",need.get("id").deepCopy());batch.addProperty("mediaKind",kind);batch.addProperty("prompt",string(p,"prompt",10000,true));batch.add("parameters",parameters.deepCopy());batch.addProperty("budgetCents",number(p,"budgetCents",100000000));batch.addProperty("createdAt",now());
        var snapshot=new JsonObject();String modelId=string(p,"modelId",100,false);
        if(!modelId.isEmpty()){var model=find(state,"models",modelId);if(!contains(model.getAsJsonArray("capabilities"),kind.equals("IMAGE")?"IMAGE_GENERATION":"VIDEO_GENERATION"))throw bad("模型不支持此候选类型");for(String key:List.of("id","name","provider","remoteModelId","protocol"))snapshot.addProperty(key,string(model,key,200,false));}
        else{snapshot.addProperty("name",string(p,"externalModel",200,true));snapshot.addProperty("provider","MANUAL_IMPORT");}
        var references=new JsonArray();if(p.has("references")){if(!p.get("references").isJsonArray()||p.getAsJsonArray("references").size()>8)throw bad("参考图最多8张");for(var raw:p.getAsJsonArray("references")){var ref=raw.getAsJsonObject();var c=find(w,"candidates",string(ref,"candidateId",100,true));if(!"IMAGE".equals(c.get("mediaKind").getAsString())||"REJECTED".equals(c.get("status").getAsString()))throw bad("请选择未淘汰的图片参考");String role=string(ref,"role",30,true);if(!Set.of("FIRST_FRAME","LAST_FRAME","CHARACTER","STYLE","GENERAL").contains(role))throw bad("参考用途无效");var frozen=new JsonObject();frozen.add("candidateId",c.get("id").deepCopy());frozen.add("fileRef",c.get("fileRef").deepCopy());frozen.add("sha256",c.get("sha256").deepCopy());frozen.addProperty("role",role);references.add(frozen);}}batch.add("references",references);
        batch.add("modelSnapshot",snapshot);String source=string(p,"sourceBatchId",100,false);if(!source.isEmpty()){if(!find(w,"batches",source).get("needId").equals(need.get("id")))throw bad("来源批次不属于当前需求");batch.addProperty("sourceBatchId",source);}insert(w,"batches",batch,600);
    }

    private void importCandidate(JsonObject state,JsonObject project,JsonObject w,JsonObject p){
        var batch=find(w,"batches",string(p,"batchId",100,true));owner(string(find(w,"needs",batch.get("needId").getAsString()),"productionNodeId",5,true));var asset=find(state,"assets",string(p,"assetId",100,true));String type=string(asset,"type",120,true),kind=kind(type);
        if(!project.get("id").equals(asset.get("projectId"))||kind.isEmpty()||!kind.equals(batch.get("mediaKind").getAsString()))throw bad("请选择本作品且与批次类型一致的图片或视频");
        String ref=string(asset,"fileRef",150,true);if(!ref.matches("/api/v1/files/[A-Za-z0-9_-]+"))throw bad("只接受本机上传文件引用");var file=mapper.findFile(ref.substring(ref.lastIndexOf('/')+1));if(file==null||!file.getMediaType().equals(type))throw bad("素材原件不存在或类型不一致");media.resource(file);
        long spent=0;for(var item:w.getAsJsonArray("candidates")){var c=item.getAsJsonObject();if(c.get("batchId").equals(batch.get("id"))){if(c.get("assetId").equals(asset.get("id")))throw bad("素材已登记到此批次");spent+=c.get("costCents").getAsLong();}}
        long cost=number(p,"costCents",100000000);if(spent+cost>batch.get("budgetCents").getAsLong())throw bad("登记费用超过批次预算");
        var candidate=new JsonObject();candidate.addProperty("id",identifier(p,"id"));candidate.add("needId",batch.get("needId").deepCopy());candidate.add("batchId",batch.get("id").deepCopy());candidate.add("assetId",asset.get("id").deepCopy());candidate.addProperty("fileRef",ref);candidate.addProperty("sha256",file.getSha256());candidate.addProperty("mediaKind",kind);candidate.addProperty("seed",string(p,"seed",100,false));candidate.addProperty("costCents",cost);candidate.addProperty("note",string(p,"note",2000,false));candidate.addProperty("status","PENDING");candidate.addProperty("createdAt",now());
        if(p.has("durationMs")){long duration=number(p,"durationMs",86400000);if(duration==0)throw bad("素材时长必须大于零");candidate.addProperty("durationMs",duration);}insert(w,"candidates",candidate,2000);
    }

    private Set<String> adopt(JsonObject w,JsonObject p){
        JsonObject candidate=find(w,"candidates",string(p,"candidateId",100,true)),need=find(w,"needs",candidate.get("needId").getAsString());if(candidate.get("status").getAsString().equals("REJECTED"))throw bad("请先恢复已淘汰候选");
        owner(string(need,"productionNodeId",5,true));String purpose=string(p,"purpose",20,true);if(!Set.of("TIMELINE","REFERENCE").contains(purpose))throw bad("请指定采用用途和片段范围");
        var value=new JsonObject();value.addProperty("id",identifier(p,"id"));value.add("needId",need.get("id").deepCopy());value.add("candidateId",candidate.get("id").deepCopy());value.addProperty("purpose",purpose);value.addProperty("reason",string(p,"reason",2000,true));
        if(candidate.get("mediaKind").getAsString().equals("VIDEO")){var source=range(p,"sourceInMs","sourceOutMs","素材范围");long duration=candidate.has("durationMs")?candidate.get("durationMs").getAsLong():number(p,"sourceDurationMs",86400000);if(source[1]>duration)throw bad("素材出点超过素材时长");value.addProperty("sourceInMs",source[0]);value.addProperty("sourceOutMs",source[1]);value.addProperty("sourceDurationMs",duration);}
        if(purpose.equals("TIMELINE")){
            var target=range(p,"targetStartMs","targetEndMs","成片范围");if(need.has("desiredStartMs")&&(target[0]<need.get("desiredStartMs").getAsLong()||target[1]>need.get("desiredEndMs").getAsLong()))throw bad("采用位置超出此需求的目标范围");
            if(value.has("sourceInMs")&&target[1]-target[0]!=value.get("sourceOutMs").getAsLong()-value.get("sourceInMs").getAsLong())throw bad("原速采用时，成片时长须与素材片段时长一致");
            value.addProperty("targetStartMs",target[0]);value.addProperty("targetEndMs",target[1]);value.addProperty("trackId",p.has("trackId")?identifier(p,"trackId"):"V1");
        }else{String reference=p.has("referenceRole")?string(p,"referenceRole",30,true):"GENERAL";if(!Set.of("GENERAL","FIRST_FRAME","LAST_FRAME","CHARACTER","STYLE").contains(reference))throw bad("参考用途无效");value.addProperty("referenceRole",reference);}
        JsonObject replaced=null;String replace=string(p,"replacesId",100,false);if(!replace.isEmpty()){replaced=find(w,"placements",replace);value.addProperty("replacesId",replace);}
        for(var item:w.getAsJsonArray("placements")){var existing=item.getAsJsonObject();if(existing.get("id").equals(value.get("id"))){if(!active(existing)||value.entrySet().stream().anyMatch(e->!e.getValue().equals(existing.get(e.getKey()))))throw new BusinessException(409,"采用编号已用于其他决定");return Set.of();}}
        if(replaced!=null&&(!active(replaced)||!replaced.get("needId").equals(need.get("id"))))throw bad("只能替换此需求下仍在使用的采用记录");
        if(purpose.equals("TIMELINE"))for(var item:w.getAsJsonArray("placements")){var x=item.getAsJsonObject();if(active(x)&&x!=replaced&&x.get("purpose").getAsString().equals("TIMELINE")&&x.get("trackId").equals(value.get("trackId"))&&x.get("targetStartMs").getAsLong()<value.get("targetEndMs").getAsLong()&&value.get("targetStartMs").getAsLong()<x.get("targetEndMs").getAsLong())throw bad("同一画面轨道已有重叠采用，请替换现有记录或调整范围");}
        String ref=candidate.get("fileRef").getAsString();var file=media.find(ref.substring(ref.lastIndexOf('/')+1));media.verify(file);if(!file.getSha256().equals(candidate.get("sha256").getAsString()))throw new BusinessException(409,"候选文件校验值已变化，请重新登记");
        value.addProperty("active",true);value.addProperty("createdAt",now());insert(w,"placements",value,2000);if(replaced!=null){replaced.addProperty("active",false);replaced.add("supersededBy",value.get("id").deepCopy());}candidate.addProperty("status","KEPT");return changed(w,need);
    }

    /** 旧绑定归档；迁移不修改节点状态与产物。 */
    public static boolean migrate(JsonObject state){boolean changed=false;for(var raw:state.getAsJsonArray("projects")){var project=raw.getAsJsonObject();
        if(!project.has("visualWorkbench")&&project.has("videoWorkbench")){var old=project.getAsJsonObject("videoWorkbench");var w=empty();for(var x:old.getAsJsonArray("shots")){var shot=x.getAsJsonObject();var n=new JsonObject();for(String k:List.of("id","title","createdAt"))n.add(k,shot.get(k).deepCopy());n.addProperty("description","");n.add("revision",shot.get("selectionRevision").deepCopy());if(shot.has("selectedCandidateId"))n.add("legacySelectedCandidateId",shot.get("selectedCandidateId").deepCopy());var binding=new JsonObject();binding.add("sourceNodeId",shot.get("nodeId").deepCopy());binding.add("consumerNodeIds",new JsonArray());n.add("legacyBinding",binding);if(isOwner(shot.get("nodeId").getAsString()))n.add("productionNodeId",shot.get("nodeId").deepCopy());w.getAsJsonArray("needs").add(n);}for(String k:List.of("batches","candidates"))for(var x:old.getAsJsonArray(k)){var c=x.getAsJsonObject().deepCopy();c.add("needId",c.get("shotId").deepCopy());c.addProperty("mediaKind","VIDEO");w.getAsJsonArray(k).add(c);}w.add("legacyAdoptions",old.get("adoptions").deepCopy());project.add("visualWorkbench",w);changed=true;}
        if(project.has("visualWorkbench")){var w=project.getAsJsonObject("visualWorkbench");if(w.get("schemaVersion").getAsInt()!=3){for(var x:w.getAsJsonArray("needs")){var n=x.getAsJsonObject();var binding=new JsonObject();for(String k:List.of("sourceNodeId","consumerNodeIds"))if(n.has(k))binding.add(k,n.get(k).deepCopy());String source=n.has("sourceNodeId")?n.get("sourceNodeId").getAsString():"";n.add("legacyBinding",binding);if(isOwner(source))n.addProperty("productionNodeId",source);n.remove("sourceNodeId");n.remove("consumerNodeIds");}w.addProperty("schemaVersion",3);w.add("uses",new JsonArray());changed=true;}}
    }return changed;}
    public static JsonObject inputs(JsonObject project,String nodeId){if(!project.has("visualWorkbench"))return null;var w=project.getAsJsonObject("visualWorkbench");var result=new JsonObject();var needs=new JsonArray();var placements=new JsonArray();var candidates=new JsonArray();var ids=new HashSet<String>();var selected=new HashSet<String>();for(var raw:w.getAsJsonArray("uses")){var u=raw.getAsJsonObject();if(u.get("nodeId").getAsString().equals(nodeId))for(var id:u.getAsJsonArray("placementIds"))selected.add(id.getAsString());}for(var x:w.getAsJsonArray("placements")){var p=x.getAsJsonObject();if(selected.contains(p.get("id").getAsString()))ids.add(p.get("needId").getAsString());}for(var x:w.getAsJsonArray("needs")){var n=x.getAsJsonObject();if(ids.contains(n.get("id").getAsString())||nodeId.equals(n.has("productionNodeId")?n.get("productionNodeId").getAsString():"")){needs.add(n.deepCopy());ids.add(n.get("id").getAsString());}}if(needs.isEmpty())return null;var candidateIds=new HashSet<String>();for(var raw:w.getAsJsonArray("placements")){var p=raw.getAsJsonObject();if(selected.contains(p.get("id").getAsString())||(isOwner(nodeId)&&active(p)&&ids.contains(p.get("needId").getAsString()))){placements.add(p.deepCopy());candidateIds.add(p.get("candidateId").getAsString());}}for(var raw:w.getAsJsonArray("candidates"))if(candidateIds.contains(raw.getAsJsonObject().get("id").getAsString()))candidates.add(raw.deepCopy());result.add("needs",needs);result.add("placements",placements);result.add("candidates",candidates);return result;}
    private static JsonObject empty(){var w=new JsonObject();w.addProperty("schemaVersion",3);w.addProperty("revision",0);for(String key:List.of("needs","batches","candidates","placements","uses","legacyAdoptions"))w.add(key,new JsonArray());return w;}
    private static JsonObject workbench(JsonObject project){if(!project.has("visualWorkbench"))project.add("visualWorkbench",empty());return project.getAsJsonObject("visualWorkbench");}
    private static Set<String> changed(JsonObject w,JsonObject need){need.addProperty("revision",need.get("revision").getAsLong()+1);w.addProperty("revision",w.get("revision").getAsLong()+1);var result=new LinkedHashSet<String>();if(need.has("productionNodeId"))result.add(owner(need.get("productionNodeId").getAsString()));for(var raw:w.getAsJsonArray("uses")){var u=raw.getAsJsonObject();for(var id:u.getAsJsonArray("placementIds"))if(find(w,"placements",id.getAsString()).get("needId").equals(need.get("id")))result.add(u.get("nodeId").getAsString());}return result;}
    private static Set<String> usePlan(JsonObject w,JsonObject p){String nodeId=string(p,"nodeId",5,true);if(!Set.of("N31","N32").contains(nodeId))throw bad("采用方案只能交给粗剪或精剪");if(!p.has("placementIds")||!p.get("placementIds").isJsonArray()||p.getAsJsonArray("placementIds").isEmpty()||p.getAsJsonArray("placementIds").size()>2000)throw bad("请选择实际使用的成片画面");var ids=new JsonArray();var unique=new HashSet<String>();for(var id:p.getAsJsonArray("placementIds")){var x=find(w,"placements",id.getAsString());if(!active(x)||!x.get("purpose").getAsString().equals("TIMELINE"))throw bad("只能交接有效成片画面");owner(string(find(w,"needs",x.get("needId").getAsString()),"productionNodeId",5,true));if(unique.add(id.getAsString()))ids.add(id.deepCopy());}var uses=w.getAsJsonArray("uses");uses.asList().removeIf(x->x.getAsJsonObject().get("nodeId").getAsString().equals(nodeId));var use=new JsonObject();use.addProperty("nodeId",nodeId);use.add("placementIds",ids);uses.add(use);return Set.of(nodeId);}
    private static boolean isOwner(String id){return Set.of("N27","N29").contains(id);}
    private static String owner(String id){if(!isOwner(id))throw bad("画面需求只能归属主体内容 N27 或辅助画面 N29");return id;}
    private static boolean active(JsonObject p){return p.get("active").getAsBoolean();}
    private static boolean has(JsonObject w,String list,String key,JsonElement id){for(var item:w.getAsJsonArray(list))if(id.equals(item.getAsJsonObject().get(key)))return true;return false;}
    private static boolean hasActive(JsonObject w,String key,JsonElement id){for(var item:w.getAsJsonArray("placements")){var x=item.getAsJsonObject();if(active(x)&&id.equals(x.get(key)))return true;}return false;}
    private static String kind(String type){return Set.of("image/png","image/jpeg","image/webp").contains(type)?"IMAGE":Set.of("video/mp4","video/webm").contains(type)?"VIDEO":"";}
    private static boolean contains(JsonArray values,String value){for(var item:values)if(item.getAsString().equals(value))return true;return false;}
    private static JsonObject find(JsonObject parent,String list,String id){for(var item:parent.getAsJsonArray(list))if(item.getAsJsonObject().get("id").getAsString().equals(id))return item.getAsJsonObject();throw bad("找不到对应的"+list+"记录");}
    private static void insert(JsonObject w,String list,JsonObject item,int limit){var values=w.getAsJsonArray(list);if(values.size()>=limit)throw bad("当前记录数量已达上限");for(var x:values)if(x.getAsJsonObject().get("id").equals(item.get("id")))throw bad("编号已存在");values.add(item);}
    private static String identifier(JsonObject p,String key){String value=string(p,key,100,true);if(!value.matches("[A-Za-z0-9_-]+"))throw bad("编号格式无效");return value;}
    private static String string(JsonObject p,String key,int max,boolean required){var value=p.get(key);if(value==null||value.isJsonNull()){if(required)throw bad(key+"不能为空");return "";}if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isString())throw bad(key+"格式无效");String result=value.getAsString().trim();if(result.length()>max||(required&&result.isEmpty()))throw bad(key+"为空或过长");return result;}
    private static long number(JsonObject p,String key,long max){try{var value=p.get(key);if(value==null||!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isNumber())throw bad(key+"须为有效整数");long n=value.getAsBigDecimal().longValueExact();if(n<0||n>max)throw bad(key+"超出范围");return n;}catch(ArithmeticException e){throw bad(key+"须为有效整数");}}
    private static long[] range(JsonObject p,String start,String end,String label){long a=number(p,start,86400000),b=number(p,end,86400000);if(b<=a)throw bad(label+"终点必须晚于起点");return new long[]{a,b};}
    private static String now(){return Instant.now().toString();}
    private static BusinessException bad(String message){return new BusinessException(400,message);}
}
