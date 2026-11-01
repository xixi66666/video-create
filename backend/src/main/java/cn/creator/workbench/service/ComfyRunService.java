package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.*;
import com.google.gson.*;
import jakarta.annotation.PostConstruct;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;

/** 本机媒体任务与 Agent 文本任务分开持久跟踪，不自动重投受理未知的请求。 */
@Service
public class ComfyRunService {
    private final WorkspaceService workspace;
    private final ComfyRunMapper mapper;
    private final ComfyClient client;
    private final ComfyTemplates templates;
    private final MediaService media;
    private final TransactionTemplate tx;
    public ComfyRunService(WorkspaceService workspace,ComfyRunMapper mapper,ComfyClient client,ComfyTemplates templates,MediaService media,PlatformTransactionManager tm){this.workspace=workspace;this.mapper=mapper;this.client=client;this.templates=templates;this.media=media;this.tx=new TransactionTemplate(tm);}

    @PostConstruct public void recover(){
        // 单机版本：崩溃点可能处于网络提交或文件落库之间，必须对账。
        for(var r:mapper.active())if(Set.of("SUBMITTING","COLLECTING").contains(r.getState()))mapper.transition(r.getId(),r.getState(),"UNKNOWN","服务重启后状态待对账，不会重复提交。");
    }

    public JsonObject readiness(){
        var out=new JsonObject();var list=new JsonArray();boolean online=false;JsonObject info=null;
        List<JsonObject> configured;
        try{configured=templates.all();}catch(BusinessException e){out.addProperty("enabled",false);out.addProperty("online",false);out.addProperty("message",e.getMessage());out.add("templates",list);return out;}
        try{client.get("/system_stats");info=client.get("/object_info");online=true;}catch(Exception ignored){/* 服务未启动，不暴露内部地址和异常详情 */}
        for(var t:configured){
            var item=new JsonObject();item.add("id",t.get("id"));item.add("name",t.get("name"));boolean ready=false;String message="ComfyUI 未连接";
            try{var graph=templates.workflow(t);if(online){message=validate(graph,info);ready=message.isEmpty();if(ready)message="工作流节点及模型可用";}}
            catch(Exception e){message="工作流登记或绑定无效";}
            item.addProperty("ready",ready);item.addProperty("message",message);list.add(item);
        }
        out.addProperty("enabled",!configured.isEmpty());out.addProperty("online",online);out.addProperty("message",configured.isEmpty()?"未登记工作流模板":online?"本机 ComfyUI 已连接":"本机 ComfyUI 未启动或不可达");out.add("templates",list);return out;
    }

    public synchronized JsonObject create(JsonObject request){
        return tx.execute(status->createInTransaction(request));
    }
    private JsonObject createInTransaction(JsonObject request){
        String id=text(request,"id",100),projectId=text(request,"projectId",90),nodeId=text(request,"nodeId",5),templateId=text(request,"templateId",100),prompt=text(request,"prompt",2000);
        if(!id.matches("comfy_[a-zA-Z0-9_-]{8,90}"))throw bad("任务 ID 无效");
        if(!"N27".equals(nodeId))throw bad("当前仅支持 N27 视频素材生成");
        long seed;try{String s=request.get("seed").getAsString();if(!s.matches("[0-9]{1,16}"))throw new IllegalArgumentException();seed=Long.parseLong(s);if(seed>9007199254740991L)throw new IllegalArgumentException();}catch(Exception e){throw bad("随机种子必须为 0 至 9007199254740991 的整数");}
        var existing=mapper.find(id);
        if(existing!=null){var old=JsonParser.parseString(existing.getPayload()).getAsJsonObject();if(!existing.getProjectId().equals(projectId)||!existing.getNodeId().equals(nodeId)||!existing.getTemplateId().equals(templateId)||!old.get("prompt").getAsString().equals(prompt)||old.get("seed").getAsLong()!=seed)throw new BusinessException(409,"任务 ID 已用于不同请求");return summary(existing);}
        if(mapper.active().stream().anyMatch(r->projectId.equals(r.getProjectId())&&nodeId.equals(r.getNodeId())))throw new BusinessException(409,"此节点已有运行中或待对账的任务，请先等待处理。");
        var state=workspace.load();var project=project(state,projectId);workspace.requireExecutable(project,nodeId);
        var template=templates.find(templateId);var graph=templates.workflow(template);templates.apply(graph,template,"promptBinding",new JsonPrimitive(prompt));templates.apply(graph,template,"seedBinding",new JsonPrimitive(seed));
        try{String error=validate(graph,client.get("/object_info"));if(!error.isEmpty())throw new BusinessException(409,error);}catch(BusinessException e){throw e;}catch(Exception e){throw new BusinessException(503,"ComfyUI 不可达，未提交任务");}
        var payload=new JsonObject();payload.addProperty("prompt",prompt);payload.addProperty("seed",seed);payload.add("workflow",graph);payload.add("outputs",template.getAsJsonArray("outputNodeIds").deepCopy());
        var r=new ComfyRunRecord();r.setId(id);r.setProjectId(projectId);r.setNodeId(nodeId);r.setTemplateId(templateId);r.setPromptId(UUID.randomUUID().toString());r.setPayload(payload.toString());r.setInputFingerprint(fingerprint(project,nodeId));r.setState("QUEUED");r.setCreatedAt(Instant.now().toString());mapper.insert(r);return summary(r);
    }

    public JsonArray list(String projectId){var result=new JsonArray();for(var r:projectId==null?mapper.list():mapper.byProject(projectId))result.add(summary(r));return result;}
    public JsonObject detail(String id){return summary(require(id));}

    @Scheduled(fixedDelayString="${workbench.comfy.poll-ms:3000}")
    public synchronized void poll(){
        for(var r:mapper.active()){
            try{
                if(r.getState().equals("QUEUED"))submit(r);
                else if(Set.of("RUNNING","UNKNOWN").contains(r.getState()))reconcile(r);
            }catch(Exception ignored){/* 任务本身保存安全状态，后续只对账不盲目提交 */}
        }
    }
    private void submit(ComfyRunRecord r){
        if(mapper.transition(r.getId(),"QUEUED","SUBMITTING","正在提交本地任务")!=1)return;
        try{var project=project(workspace.load(),r.getProjectId());workspace.requireExecutable(project,r.getNodeId());if(!fingerprint(project,r.getNodeId()).equals(r.getInputFingerprint()))throw new BusinessException(409,"输入已变化");}
        catch(BusinessException e){mapper.transition(r.getId(),"SUBMITTING","FAILED","制作输入或拍板已变化，任务未提交；请重新创建。");return;}
        try{
            var p=JsonParser.parseString(r.getPayload()).getAsJsonObject();var body=new JsonObject();body.add("prompt",p.get("workflow"));body.addProperty("prompt_id",r.getPromptId());body.addProperty("client_id",UUID.randomUUID().toString());
            var response=client.submit(body);
            if(response.statusCode()==400){mapper.transition(r.getId(),"SUBMITTING","FAILED","工作流被 ComfyUI 拒绝，请检查节点及参数。");return;}
            if(response.statusCode()>=200&&response.statusCode()<300){var reply=JsonParser.parseString(response.body()).getAsJsonObject();if(reply.has("prompt_id")&&r.getPromptId().equals(reply.get("prompt_id").getAsString())){mapper.transition(r.getId(),"SUBMITTING","RUNNING","已受理，等待生成完成。");return;}}
        }catch(Exception ignored){ }
        mapper.transition(r.getId(),"SUBMITTING","UNKNOWN","提交结果未知，正在对账；不会自动重复提交。");
    }
    private void reconcile(ComfyRunRecord r)throws Exception{
        JsonObject history;
        try{history=client.get("/history/"+r.getPromptId());}catch(Exception e){if(r.getState().equals("RUNNING"))mapper.transition(r.getId(),"RUNNING","UNKNOWN","连接中断，等待对账；不会重复提交。");return;}
        if(history.has(r.getPromptId())){
            var result=history.getAsJsonObject(r.getPromptId());var status=result.has("status")?result.getAsJsonObject("status"):new JsonObject();
            if(status.has("status_str")&&"error".equals(status.get("status_str").getAsString())){mapper.transition(r.getId(),r.getState(),"FAILED","ComfyUI 执行失败，请检查服务日志。");return;}
            if(status.has("completed")&&status.get("completed").getAsBoolean()){
                var file=output(r,result);if(file==null){mapper.transition(r.getId(),r.getState(),"FAILED","任务完成但未找到登记的 MP4 输出。");return;}
                String fileId=UUID.nameUUIDFromBytes(("comfy:"+r.getId()).getBytes(StandardCharsets.UTF_8)).toString();
                if(mapper.claimCollect(r.getId(),r.getState(),"/api/v1/files/"+fileId)!=1)return;
                try{
                    byte[] bytes=client.video(file.get("filename").getAsString(),file.has("subfolder")?file.get("subfolder").getAsString():"");
                    tx.executeWithoutResult(s->{try{var m=media.saveGeneratedVideo(bytes,fileId);if(mapper.result(r.getId(),"/api/v1/files/"+m.getId(),m.getSha256(),m.getByteSize(),"生成完成；请检查候选后决定是否采纳。")!=1)throw new IllegalStateException();}catch(java.io.IOException e){throw new IllegalStateException(e);}});
                }catch(BusinessException e){mapper.transition(r.getId(),"COLLECTING","FAILED",e.getMessage());}
                catch(Exception e){mapper.transition(r.getId(),"COLLECTING","UNKNOWN","候选素材回收暂不可用，将继续对账。");}
                return;
            }
        }
        try{if(inQueue(client.get("/queue"),r.getPromptId())){if(r.getState().equals("UNKNOWN"))mapper.transition(r.getId(),"UNKNOWN","RUNNING","已在队列或运行中找到原任务。");return;}}catch(Exception ignored){ }
        if(r.getState().equals("RUNNING"))mapper.transition(r.getId(),"RUNNING","UNKNOWN","未找到任务记录，等待对账；不会自动重试。");
    }
    private JsonObject output(ComfyRunRecord r,JsonObject result){
        if(!result.has("outputs"))return null;var outputs=result.getAsJsonObject("outputs");var allowed=JsonParser.parseString(r.getPayload()).getAsJsonObject().getAsJsonArray("outputs");
        for(var key:allowed){String id=key.getAsString();if(!outputs.has(id))continue;var node=outputs.getAsJsonObject(id);for(String list:List.of("images","videos")){if(!node.has(list)||!node.get(list).isJsonArray())continue;for(var e:node.getAsJsonArray(list)){var f=e.getAsJsonObject();if(f.has("filename")&&f.get("filename").getAsString().toLowerCase(Locale.ROOT).endsWith(".mp4")&&f.has("type")&&"output".equals(f.get("type").getAsString()))return f;}}}return null;
    }
    private static boolean inQueue(JsonObject queue,String id){for(String name:List.of("queue_running","queue_pending"))if(queue.has(name)&&queue.get(name).isJsonArray())for(var e:queue.getAsJsonArray(name)){var a=e.getAsJsonArray();if(a.size()>1&&id.equals(a.get(1).getAsString()))return true;}return false;}

    public synchronized JsonObject adopt(String id){
        return tx.execute(status->adoptInTransaction(id));
    }
    private JsonObject adoptInTransaction(String id){
        var r=require(id);if(r.isAdopted())return summary(r);if(!r.getState().equals("SUCCEEDED")||r.getFileRef()==null)throw new BusinessException(409,"候选尚未生成完成");
        var state=workspace.load();var project=project(state,r.getProjectId());workspace.requireExecutable(project,r.getNodeId());if(!fingerprint(project,r.getNodeId()).equals(r.getInputFingerprint()))throw new BusinessException(409,"制作输入或节点已变化，候选已过期，请重新生成。");
        var asset=new JsonObject();asset.addProperty("id","asset_"+UUID.randomUUID());asset.addProperty("name","ComfyUI 生成候选.mp4");asset.addProperty("type","video/mp4");asset.addProperty("size",r.getByteSize());asset.addProperty("source","ComfyUI 本机生成（候选采纳）");asset.addProperty("fileRef",r.getFileRef());asset.addProperty("projectId",r.getProjectId());asset.addProperty("createdAt",Instant.now().toString());
        var payload=new JsonObject();payload.add("asset",asset);workspace.execute(new WorkspaceCommand("ADD_ASSET",payload,state.get("version").getAsLong()));if(mapper.adopt(id)!=1)throw new BusinessException(409,"候选已被处理，请刷新。");return summary(require(id));
    }

    private static String validate(JsonObject workflow,JsonObject info){
        for(var entry:workflow.entrySet()){
            var node=entry.getValue().getAsJsonObject();String type=node.get("class_type").getAsString();if(!info.has(type))return "缺少工作流节点："+type;
            var spec=info.getAsJsonObject(type);if(!spec.has("input"))continue;var fields=spec.getAsJsonObject("input");var inputs=node.getAsJsonObject("inputs");
            for(String section:List.of("required","optional"))if(fields.has(section))for(var prop:fields.getAsJsonObject(section).entrySet()){
                if(!inputs.has(prop.getKey())||!inputs.get(prop.getKey()).isJsonPrimitive()||!prop.getValue().isJsonArray())continue;var args=prop.getValue().getAsJsonArray();if(args.isEmpty()||!args.get(0).isJsonArray())continue;
                boolean found=false;for(var option:args.get(0).getAsJsonArray())if(option.equals(inputs.get(prop.getKey()))){found=true;break;}if(!found)return "节点参数或模型不可用："+type+" / "+prop.getKey();
            }
        }return "";
    }
    private JsonObject summary(ComfyRunRecord r){var o=new JsonObject();o.addProperty("id",r.getId());o.addProperty("projectId",r.getProjectId());o.addProperty("nodeId",r.getNodeId());o.addProperty("templateId",r.getTemplateId());o.addProperty("state",r.getState());o.addProperty("promptId",r.getPromptId());o.addProperty("createdAt",r.getCreatedAt());o.addProperty("message",r.getMessage());o.addProperty("fileRef",r.getFileRef());o.addProperty("sha256",r.getSha256());o.addProperty("size",r.getByteSize());o.addProperty("adopted",r.isAdopted());return o;}
    private ComfyRunRecord require(String id){if(id==null||!id.matches("comfy_[a-zA-Z0-9_-]{8,90}"))throw bad("任务 ID 无效");var r=mapper.find(id);if(r==null)throw new BusinessException(404,"任务不存在");return r;}
    private static JsonObject project(JsonObject state,String id){for(var e:state.getAsJsonArray("projects"))if(id.equals(e.getAsJsonObject().get("id").getAsString()))return e.getAsJsonObject();throw new BusinessException(404,"作品不存在");}
    private static String fingerprint(JsonObject project,String nodeId){
        var snapshot=new JsonObject();for(String key:List.of("id","title","brief","template","platforms"))snapshot.add(key,project.get(key));var nodes=project.getAsJsonObject("nodes");for(String key:List.of("N24","N25","N26",nodeId))snapshot.add(key,nodes.get(key));snapshot.add("G03",project.getAsJsonObject("approvals").get("G03"));
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(snapshot.toString().getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}
    }
    private static String text(JsonObject data,String key,int max){try{String s=data.get(key).getAsString().trim();if(s.isEmpty()||s.length()>max)throw bad("请求字段无效："+key);return s;}catch(NullPointerException|IllegalStateException e){throw bad("缺少请求字段："+key);}}
    private static BusinessException bad(String message){return new BusinessException(400,message);}
}
