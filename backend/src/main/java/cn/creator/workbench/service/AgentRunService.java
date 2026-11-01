package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.*;
import com.google.gson.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.scheduling.annotation.Scheduled;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;

/** 业务快照、命令 outbox、采纳事务与模型继承规则。Agent 无权直接修改业务状态。 */
@Service
public class AgentRunService {
    private final WorkspaceService workspace;
    private final AgentRunMapper mapper;
    private final AgentRuntimeClient runtime;
    private final Gson gson=new Gson();
    public AgentRunService(WorkspaceService workspace,AgentRunMapper mapper,AgentRuntimeClient runtime){this.workspace=workspace;this.mapper=mapper;this.runtime=runtime;}

    public JsonObject readiness(){
        var data=new JsonObject();data.addProperty("online",false);data.addProperty("liveModelsEnabled",false);
        try{var health=runtime.get("/health").getAsJsonObject();health.entrySet().forEach(e->data.add(e.getKey(),e.getValue()));data.addProperty("online",true);data.add("profiles",runtime.get("/profiles"));}
        catch(BusinessException e){data.addProperty("message",e.getMessage());}
        return data;
    }

    @Transactional
    public synchronized JsonObject create(JsonObject request){
        String id=text(request,"id",100),projectId=text(request,"projectId",90),nodeId=text(request,"nodeId",5),mode=text(request,"mode",10);
        if(!id.matches("run_[a-zA-Z0-9_-]{8,90}"))throw bad("运行 ID 无效");
        if(!Set.of("FIXTURE","LIVE").contains(mode))throw bad("运行模式无效");
        var existing=mapper.find(id);
        if(existing!=null){var saved=JsonParser.parseString(existing.getPayload()).getAsJsonObject();if(!existing.getProjectId().equals(projectId)||!existing.getNodeId().equals(nodeId)||!saved.get("mode").getAsString().equals(mode))throw new BusinessException(409,"运行 ID 已用于不同请求");if(request.has("maxTotalTokens")&&limitsForRequest(request).get("maxTotalTokens").getAsInt()!=saved.getAsJsonObject("limits").get("maxTotalTokens").getAsInt())throw new BusinessException(409,"运行 ID 已用于不同运行限制");return summary(existing);}
        if(mode.equals("LIVE")){
            var ready=readiness();if(!ready.get("online").getAsBoolean()||!ready.get("liveModelsEnabled").getAsBoolean())throw new BusinessException(409,"真实模型调用已关闭，本轮只允许测试模型验收。");
        }
        var state=workspace.load();var project=find(state.getAsJsonArray("projects"),projectId);var node=find(workspace.catalog().getAsJsonArray("nodes"),nodeId);
        if(project==null||node==null)throw bad("作品或节点不存在");
        workspace.requireExecutable(project,nodeId);
        var input=input(state,project,node);
        var payload=new JsonObject();payload.addProperty("id",id);payload.addProperty("projectId",projectId);payload.addProperty("mode",mode);
        payload.add("node",node);payload.add("input",input);payload.addProperty("inputFingerprint",sha(input));
        payload.addProperty("executionMode",planOnly(node)?"PLAN_ONLY":"GENERATE_TEXT");
        var models=new JsonObject();models.add("worker",resolveModel(state,project,node.get("agentRole").getAsString(),nodeId));
        models.add("supervisor",resolveModel(state,project,"PRODUCER",null));models.add("reviewer",resolveModel(state,project,"QUALITY",null));payload.add("models",models);
        if(mode.equals("LIVE")){
            // 白名单是操作者对供应商工具能力、数据边界与费用的明确授权，不冒充系统验证。
            var authorized=new HashSet<>(Arrays.asList(System.getenv().getOrDefault("CREATOR_APPROVED_AGENT_MODELS","").split(",")));
            for(var entry:models.entrySet()){
                var model=entry.getValue().getAsJsonObject();
                if(!model.has("id")||!authorized.contains(model.get("id").getAsString()))throw new BusinessException(409,"主管、专家和评审模型都必须配置，并由服务器白名单明确授权。");
                if(!Set.of("CHAT_COMPLETIONS_COMPATIBLE","RESPONSES").contains(model.get("protocol").getAsString()))throw new BusinessException(409,"所选协议尚无 Agent 调用适配器。");
            }
        }
        payload.add("limits",limitsForRequest(request));
        var record=new AgentRunRecord();record.setId(id);record.setProjectId(projectId);record.setNodeId(nodeId);record.setPayload(payload.toString());record.setInputFingerprint(sha(input));record.setState("PENDING_SUBMISSION");record.setCreatedAt(Instant.now().toString());mapper.insert(record);
        return summary(record);
    }

    /** 事务提交后再投递。超时重投相同 run ID，由运行服务持久幂等，不新建计费任务。 */
    @Scheduled(fixedDelay=2000)
    public synchronized void dispatch(){
        for(var record:mapper.list()){
            try{
                if(record.getState().equals("PENDING_SUBMISSION")){runtime.post("/runs",JsonParser.parseString(record.getPayload()).getAsJsonObject());mapper.state(record.getId(),"SUBMITTED");}
                if(Set.of("ACCEPT_PENDING_SYNC","REJECT_PENDING_SYNC").contains(record.getState())){
                    var command=new JsonObject();command.addProperty("decision",record.getState().startsWith("ACCEPT")?"ACCEPT":"REJECT");
                    runtime.post("/runs/"+record.getId()+"/decision",command);mapper.state(record.getId(),record.getState().startsWith("ACCEPT")?"ADOPTED":"REJECTED");
                }
            }catch(BusinessException ignored){/* outbox 保留原意图；无隐式模型重试、无敏感日志。 */}
        }
    }

    public JsonArray list(){var list=new JsonArray();mapper.list().forEach(r->list.add(summary(r)));return list;}
    public JsonObject detail(String id){var record=require(id);var result=summary(record);try{result.add("runtime",runtime.get("/runs/"+id));result.add("events",runtime.get("/runs/"+id+"/events"));}catch(BusinessException e){result.addProperty("runtimeMessage",e.getMessage());}return result;}

    @Transactional
    public synchronized JsonObject decide(String id,JsonObject body){
        var record=require(id);String choice=text(body,"decision",10);
        if(!Set.of("ACCEPT","REJECT").contains(choice))throw bad("采纳决定无效");
        if((choice.equals("ACCEPT")&&Set.of("ADOPTED","ACCEPT_PENDING_SYNC").contains(record.getState()))||(choice.equals("REJECT")&&Set.of("REJECTED","REJECT_PENDING_SYNC").contains(record.getState())))return summary(record);
        if(!record.getState().equals("SUBMITTED"))throw new BusinessException(409,"当前不能处理候选");
        var remote=runtime.get("/runs/"+id).getAsJsonObject();if(!remote.get("status").getAsString().equals("WAITING_ACCEPTANCE"))throw new BusinessException(409,"请等待评审通过后再采纳");
        if(choice.equals("ACCEPT")){
            var state=workspace.load();var project=find(state.getAsJsonArray("projects"),record.getProjectId());var node=find(workspace.catalog().getAsJsonArray("nodes"),record.getNodeId());
            if(project==null||!sha(input(state,project,node)).equals(record.getInputFingerprint()))throw new BusinessException(409,"输入或草稿已变化，候选已过期，请按新版本重新运行。");
            workspace.requireExecutable(project,record.getNodeId());
            JsonObject candidate=null;for(var a:remote.getAsJsonArray("artifacts")){var item=a.getAsJsonObject();if(item.get("kind").getAsString().equals("CANDIDATE"))candidate=item.getAsJsonObject("content");}
            if(candidate==null)throw new BusinessException(409,"没有可采纳产物");
            var p=new JsonObject();p.addProperty("projectId",record.getProjectId());p.addProperty("nodeId",record.getNodeId());
            p.addProperty("text",candidate.get("body").getAsString()+"\n\n"+new GsonBuilder().setPrettyPrinting().create().toJson(candidate));p.addProperty("complete",false);
            workspace.execute(new WorkspaceCommand("SAVE_NODE",p,state.get("version").getAsLong()));
        }
        mapper.state(id,choice.equals("ACCEPT")?"ACCEPT_PENDING_SYNC":"REJECT_PENDING_SYNC");
        return summary(require(id));
    }

    public synchronized JsonObject control(String id,JsonObject body){
        var record=require(id);String action=text(body,"action",20);
        switch(action){
            case "CANCEL" -> {if(!Set.of("PENDING_SUBMISSION","SUBMITTED").contains(record.getState()))throw new BusinessException(409,"此任务不能取消");if(record.getState().equals("SUBMITTED"))runtime.post("/runs/"+id+"/cancel",new JsonObject());mapper.state(id,"CANCELLED");}
            case "DELETE" -> {if(record.getState().equals("PENDING_SUBMISSION"))throw new BusinessException(409,"请先取消排队任务再删除");if(record.getState().equals("SUBMITTED")){String status=runtime.get("/runs/"+id).getAsJsonObject().get("status").getAsString();if(Set.of("QUEUED","RUNNING").contains(status))throw new BusinessException(409,"请先取消运行再删除记录");}mapper.visibility(id,Instant.now().toString());}
            case "RESTORE" -> mapper.visibility(id,null);
            default -> throw bad("控制命令无效");
        }
        return summary(require(id));
    }

    private JsonObject summary(AgentRunRecord r){var result=gson.toJsonTree(r).getAsJsonObject();result.remove("payload");var p=JsonParser.parseString(r.getPayload()).getAsJsonObject();result.add("mode",p.get("mode"));result.add("executionMode",p.get("executionMode"));result.add("models",p.get("models"));result.add("limits",p.get("limits"));return result;}
    private AgentRunRecord require(String id){if(!id.matches("run_[a-zA-Z0-9_-]{8,90}"))throw bad("运行 ID 无效");var r=mapper.find(id);if(r==null)throw new BusinessException(404,"运行不存在");return r;}
    private static JsonObject input(JsonObject state,JsonObject project,JsonObject node){
        var result=new JsonObject();for(String k:List.of("id","title","brief","template","platforms"))result.add(k,project.get(k));result.add("creatorProfile",state.get("profile"));
        var deps=new JsonObject();for(var d:node.getAsJsonArray("dependsOn"))deps.add(d.getAsString(),project.getAsJsonObject("nodes").get(d.getAsString()));result.add("dependencies",deps);
        result.add("currentNode",project.getAsJsonObject("nodes").get(node.get("id").getAsString()));result.add("approvals",project.get("approvals"));return result;
    }
    static JsonObject resolveModel(JsonObject state,JsonObject project,String role,String nodeId){
        var maps=new ArrayList<JsonObject>();if(nodeId!=null)maps.add(object(project.getAsJsonObject("nodeBindings"),nodeId));maps.add(project.getAsJsonObject("bindings"));maps.add(object(state.getAsJsonObject("agentBindings"),role));maps.add(state.getAsJsonObject("globalBindings"));
        for(var map:maps)for(String key:List.of("TEXT_REASONING","$default")){if(map.has(key)){var model=find(state.getAsJsonArray("models"),map.get(key).getAsString());if(model!=null&&model.getAsJsonArray("capabilities").asList().stream().anyMatch(c->c.getAsString().equals("TEXT_REASONING")))return model.deepCopy();}}
        return new JsonObject();
    }
    static boolean planOnly(JsonObject node){return Set.of("CAPTURE","AUDIO","IMAGE","VIDEO","EDITOR","PUBLISHER").contains(node.get("agentRole").getAsString())||Set.of("N30","N41","N44","N45","N46","N49").contains(node.get("id").getAsString());}
    /** 零表示不设累计 token 上限；显式预算与旧运行快照中的正数仍生效。 */
    static JsonObject limitsForRequest(JsonObject request){
        var limits=JsonParser.parseString("{\"maxModelCalls\":30,\"maxTotalTokens\":0,\"maxOutputTokens\":1200,\"maxSeconds\":180,\"maxReworks\":1}").getAsJsonObject();
        if(!request.has("maxTotalTokens"))return limits;
        var value=request.get("maxTotalTokens");int max;
        try{if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isNumber()||!value.getAsString().matches("[0-9]{1,6}"))throw new IllegalArgumentException();max=Integer.parseInt(value.getAsString());if(max!=0&&(max<100||max>100000))throw new IllegalArgumentException();}
        catch(Exception e){throw bad("累计 token 上限须为 0（不设上限）或 100 至 100000 的整数");}
        limits.addProperty("maxTotalTokens",max);return limits;
    }
    private static JsonObject object(JsonObject parent,String key){return parent.has(key)?parent.getAsJsonObject(key):new JsonObject();}
    private static JsonObject find(JsonArray array,String id){for(var item:array){var o=item.getAsJsonObject();if(o.get("id").getAsString().equals(id))return o;}return null;}
    private static String sha(JsonObject value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.toString().getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}}
    private static String text(JsonObject o,String key,int max){try{String s=o.get(key).getAsString();if(s.isBlank()||s.length()>max)throw bad("请求字段无效："+key);return s;}catch(NullPointerException|IllegalStateException e){throw bad("缺少请求字段："+key);}}
    private static BusinessException bad(String s){return new BusinessException(400,s);}
}
