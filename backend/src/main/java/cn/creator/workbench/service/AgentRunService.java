package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.*;
import com.google.gson.*;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** 业务快照、命令 outbox、采纳事务与模型继承规则。Agent 无权直接修改业务状态。 */
@Service
public class AgentRunService {
    private static final int MAX_INPUT_BYTES=400_000;
    private final WorkspaceService workspace;
    private final AgentRunMapper mapper;
    private final AgentRuntimeClient runtime;
    private final TransactionTemplate transaction;
    private final Gson gson=new Gson();
    private final AtomicBoolean dispatching=new AtomicBoolean();
    // 同一运行的投递和控制操作必须串行；固定分段锁避免逐运行永久占用内存。
    private final Object[] runLocks=new Object[64];
    public AgentRunService(WorkspaceService workspace,AgentRunMapper mapper,AgentRuntimeClient runtime,PlatformTransactionManager manager){this.workspace=workspace;this.mapper=mapper;this.runtime=runtime;this.transaction=new TransactionTemplate(manager);Arrays.setAll(runLocks,i->new Object());}
    private Object runLock(String id){return runLocks[(id.hashCode()&0x7fffffff)%runLocks.length];}

    public JsonObject readiness(){
        var data=new JsonObject();data.addProperty("online",false);data.addProperty("liveModelsEnabled",false);
        try{var health=runtime.get("/health").getAsJsonObject();health.entrySet().forEach(e->data.add(e.getKey(),e.getValue()));data.addProperty("online",true);data.add("profiles",runtime.get("/profiles"));}
        catch(BusinessException e){data.addProperty("message",e.getMessage());}
        return data;
    }

    public synchronized JsonObject create(JsonObject request){
        // 事务需在同步锁内提交，否则相同 ID 的请求可能在提交前读取不到记录。
        return transaction.execute(status->createInTransaction(request));
    }
    private JsonObject createInTransaction(JsonObject request){
        String id=text(request,"id",100),projectId=text(request,"projectId",90),nodeId=text(request,"nodeId",5),mode=text(request,"mode",10);
        if(!id.matches("run_[a-zA-Z0-9_-]{8,90}"))throw bad("运行 ID 无效");
        if(!Set.of("FIXTURE","LIVE").contains(mode))throw bad("运行模式无效");
        var consultationRoles=consultationRoles(request);
        var existing=mapper.find(id);
        if(existing!=null){var saved=JsonParser.parseString(existing.getPayload()).getAsJsonObject();var previous=saved.has("consultationRoles")?saved.getAsJsonArray("consultationRoles"):new JsonArray();if(!existing.getProjectId().equals(projectId)||!existing.getNodeId().equals(nodeId)||!saved.get("mode").getAsString().equals(mode)||!previous.equals(consultationRoles))throw new BusinessException(409,"运行 ID 已用于不同请求");return summary(existing);}
        if(mode.equals("LIVE")){
            var ready=readiness();if(!ready.get("online").getAsBoolean()||!ready.get("liveModelsEnabled").getAsBoolean())throw new BusinessException(409,"真实模型调用已关闭，本轮只允许测试模型验收。");
        }
        var state=workspace.load();var project=find(state.getAsJsonArray("projects"),projectId);var node=find(workspace.catalog().getAsJsonArray("nodes"),nodeId);
        if(project==null||node==null)throw bad("作品或节点不存在");
        for(var item:consultationRoles){String role=item.getAsString();if(role.equals(node.get("agentRole").getAsString())||find(workspace.catalog().getAsJsonArray("agents"),role)==null)throw bad("会诊角色无效或与主责角色重复");}
        workspace.requireExecutable(project,nodeId);
        var input=input(state,project,node);
        if(input.toString().getBytes(StandardCharsets.UTF_8).length>MAX_INPUT_BYTES)throw new BusinessException(413,"节点输入过大，请缩减依赖产物或材料后再运行。");
        var payload=new JsonObject();payload.addProperty("id",id);payload.addProperty("projectId",projectId);payload.addProperty("mode",mode);
        payload.add("consultationRoles",consultationRoles);
        if(consultationRoles.size()>=2)payload.addProperty("consultationComparison",true);
        payload.add("node",node);payload.add("input",input);payload.addProperty("inputFingerprint",sha(input));
        payload.addProperty("executionMode",planOnly(node)?"PLAN_ONLY":"GENERATE_TEXT");
        var models=new JsonObject();models.add("worker",resolveModel(state,project,node.get("agentRole").getAsString(),nodeId));
        models.add("supervisor",resolveModel(state,project,"PRODUCER",null));models.add("reviewer",resolveModel(state,project,"QUALITY",null));
        // 每位会诊专家按其角色继承绑定，固定独立快照；节点专属覆盖仅用于主责节点。
        for(var item:consultationRoles){String consultant=item.getAsString();models.add("consultant_"+consultant,resolveModel(state,project,consultant,null));}
        payload.add("models",models);
        if(mode.equals("LIVE")){
            // 白名单是操作者对供应商工具能力、数据边界与费用的明确授权，不冒充系统验证。
            var authorized=new HashSet<>(Arrays.asList(System.getenv().getOrDefault("CREATOR_APPROVED_AGENT_MODELS","").split(",")));
            for(var entry:models.entrySet()){
                var model=entry.getValue().getAsJsonObject();
                if(!model.has("id")||!authorized.contains(model.get("id").getAsString()))throw new BusinessException(409,"主管、主责专家、会诊专家和评审模型都必须配置，并由服务器白名单明确授权。");
                if(!Set.of("CHAT_COMPLETIONS_COMPATIBLE","RESPONSES").contains(model.get("protocol").getAsString()))throw new BusinessException(409,"所选协议尚无 Agent 调用适配器。");
                ModelParameterPolicy.validateLiveAgent(model.get("parameters"),model.get("protocol").getAsString());
            }
        }
        var limits=JsonParser.parseString("{\"maxModelCalls\":30,\"maxSeconds\":180,\"maxReworks\":1}").getAsJsonObject();
        if(!consultationRoles.isEmpty())limits.addProperty("maxModelCalls",60);
        payload.add("limits",limits);
        var record=new AgentRunRecord();record.setId(id);record.setProjectId(projectId);record.setNodeId(nodeId);record.setPayload(payload.toString());record.setInputFingerprint(sha(input));record.setState("PENDING_SUBMISSION");record.setCreatedAt(Instant.now().toString());record.setDispatchAttempts(0);mapper.insert(record);
        return summary(record);
    }

    /** 事务提交后再投递。超时重投相同 run ID，由运行服务持久幂等，不新建计费任务。 */
    @Scheduled(fixedDelay=2000)
    public void dispatch(){
        // 调度器本身是单线程；这里再防止测试或手工调用重叠。HTTP 调用不再持有 create/decide 的锁。
        if(!dispatching.compareAndSet(false,true))return;
        try{
            for(var listed:mapper.pending()){
                synchronized(runLock(listed.getId())) {
                // 列表快照可能已过期，必须在锁内重新读取当前状态。
                var record=mapper.find(listed.getId());
                if(record==null)continue;
                try{
                    if(record.getState().equals("PENDING_SUBMISSION")){
                        // 发送之前持久记录尝试：服务端受理后本进程崩溃，取消也不能误判为从未投递。
                        String at=Instant.now().toString();
                        if(mapper.bumpDispatch(record.getId(),"投递结果尚未确认",at)==0)mapper.insertDispatch(record.getId(),"投递结果尚未确认",at);
                        runtime.post("/runs",JsonParser.parseString(record.getPayload()).getAsJsonObject());mapper.state(record.getId(),"SUBMITTED");mapper.clearDispatch(record.getId(),Instant.now().toString());
                    }
                    else if(record.getState().equals("CANCEL_PENDING_SYNC")){
                        runtime.post("/runs/"+record.getId()+"/cancel",new JsonObject());mapper.state(record.getId(),"CANCELLED");mapper.clearDispatch(record.getId(),Instant.now().toString());
                    }
                    else if(Set.of("ACCEPT_PENDING_SYNC","REJECT_PENDING_SYNC").contains(record.getState())){
                        var command=new JsonObject();command.addProperty("decision",record.getState().startsWith("ACCEPT")?"ACCEPT":"REJECT");
                        runtime.post("/runs/"+record.getId()+"/decision",command);mapper.state(record.getId(),record.getState().startsWith("ACCEPT")?"ADOPTED":"REJECTED");mapper.clearDispatch(record.getId(),Instant.now().toString());
                    }
                }catch(BusinessException failure){
                    // 记录最后一次真实原因；永久错误停止重投，避免每 2 秒重复撞同一面墙。
                    String message=failure.getMessage()==null?"投递失败":failure.getMessage();if(message.length()>500)message=message.substring(0,500);
                    String at=Instant.now().toString();
                    if(record.getState().equals("PENDING_SUBMISSION"))mapper.noteDispatchFailure(record.getId(),message,at);
                    else if(mapper.bumpDispatch(record.getId(),message,at)==0)mapper.insertDispatch(record.getId(),message,at);
                    if(permanent(failure.getStatus())){
                        String next=switch(record.getState()){
                            case "PENDING_SUBMISSION"->"SUBMISSION_FAILED";
                            case "ACCEPT_PENDING_SYNC"->"ADOPTED_SYNC_FAILED";
                            case "REJECT_PENDING_SYNC"->"REJECTED_SYNC_FAILED";
                            case "CANCEL_PENDING_SYNC"->"CANCEL_SYNC_FAILED";
                            default->null;
                        };
                        if(next!=null)mapper.state(record.getId(),next);
                    }
                }
                }
            }
        }finally{dispatching.set(false);}
    }
    private static boolean permanent(int status){return Set.of(400,401,403,404,409,413,422).contains(status);}

    public JsonArray list(){var list=new JsonArray();mapper.list().forEach(r->list.add(summary(r)));return list;}
    public JsonObject detail(String id){var record=require(id);var result=summary(record);try{result.add("runtime",runtime.get("/runs/"+id));result.add("events",runtime.get("/runs/"+id+"/events"));}catch(BusinessException e){result.addProperty("runtimeMessage",e.getMessage());}return result;}

    public synchronized JsonObject decide(String id,JsonObject body){
        return transaction.execute(status->decideInTransaction(id,body));
    }
    private JsonObject decideInTransaction(String id,JsonObject body){
        var record=require(id);String choice=text(body,"decision",10);
        if(record.getDeletedAt()!=null)throw new BusinessException(409,"运行已删除，请先恢复后再处理候选");
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
            String candidateBody=candidate.get("body").getAsString();
            String draft=candidateBody+"\n\n"+new GsonBuilder().setPrettyPrinting().create().toJson(candidate);
            var provenance=new JsonObject();provenance.addProperty("runId",record.getId());
            boolean fixture="FIXTURE".equals(JsonParser.parseString(record.getPayload()).getAsJsonObject().get("mode").getAsString());
            provenance.addProperty("fixture",fixture);
            if(fixture)provenance.addProperty("fixtureBody",candidateBody);
            if(candidate.has("version")&&candidate.get("version").isJsonPrimitive()&&candidate.getAsJsonPrimitive("version").isNumber())provenance.add("candidateVersion",candidate.get("version"));
            if(candidate.has("sha256")&&candidate.get("sha256").isJsonPrimitive()&&candidate.getAsJsonPrimitive("sha256").isString())provenance.add("candidateHash",candidate.get("sha256"));
            provenance.add("uncertainties",candidate.has("uncertainties")&&candidate.get("uncertainties").isJsonArray()?candidate.getAsJsonArray("uncertainties").deepCopy():new JsonArray());
            workspace.saveAgentDraft(record.getProjectId(),record.getNodeId(),draft,provenance,state.get("version").getAsLong());
        }
        mapper.state(id,choice.equals("ACCEPT")?"ACCEPT_PENDING_SYNC":"REJECT_PENDING_SYNC");
        return summary(require(id));
    }

    public synchronized JsonObject control(String id,JsonObject body){
        synchronized(runLock(id)) {
        var record=require(id);String action=text(body,"action",20);
        switch(action){
            case "CANCEL" -> {
                if(record.getState().equals("CANCEL_PENDING_SYNC"))return summary(record);
                if(!Set.of("PENDING_SUBMISSION","SUBMITTED","SUBMISSION_FAILED").contains(record.getState()))throw new BusinessException(409,"此任务不能取消");
                // 投递曾失败时远端可能已受理。先持久化取消意图，之后只重试取消而不再投递运行。
                if(Set.of("SUBMITTED","SUBMISSION_FAILED").contains(record.getState())||(record.getDispatchAttempts()!=null&&record.getDispatchAttempts()>0)){
                    mapper.state(id,"CANCEL_PENDING_SYNC");
                    try{runtime.post("/runs/"+id+"/cancel",new JsonObject());mapper.state(id,"CANCELLED");mapper.clearDispatch(id,Instant.now().toString());}
                    catch(BusinessException failure){
                        String message=failure.getMessage()==null?"远端取消未确认":failure.getMessage();if(message.length()>500)message=message.substring(0,500);
                        String at=Instant.now().toString();if(mapper.bumpDispatch(id,message,at)==0)mapper.insertDispatch(id,message,at);
                        if(permanent(failure.getStatus()))mapper.state(id,"CANCEL_SYNC_FAILED");
                    }
                }else mapper.state(id,"CANCELLED");
            }
            case "DELETE" -> {if(Set.of("PENDING_SUBMISSION","SUBMISSION_FAILED","CANCEL_PENDING_SYNC","CANCEL_SYNC_FAILED").contains(record.getState()))throw new BusinessException(409,"请先确认取消结果再删除记录");if(record.getState().equals("SUBMITTED")){String status=runtime.get("/runs/"+id).getAsJsonObject().get("status").getAsString();if(Set.of("QUEUED","RUNNING").contains(status))throw new BusinessException(409,"请先取消运行再删除记录");}mapper.visibility(id,Instant.now().toString());}
            case "RESTORE" -> mapper.visibility(id,null);
            case "RETRY" -> {
                String next=switch(record.getState()){
                    case "SUBMISSION_FAILED"->"PENDING_SUBMISSION";
                    case "ADOPTED_SYNC_FAILED"->"ACCEPT_PENDING_SYNC";
                    case "REJECTED_SYNC_FAILED"->"REJECT_PENDING_SYNC";
                    case "CANCEL_SYNC_FAILED"->"CANCEL_PENDING_SYNC";
                    default->throw new BusinessException(409,"当前状态不能重试投递");
                };
                if(record.getState().equals("SUBMISSION_FAILED")&&(record.getDispatchAttempts()==null||record.getDispatchAttempts()==0)){
                    // 兼容旧数据：失败状态表明曾尝试，不能因缺少历史计数而误判未投递。
                    String at=Instant.now().toString();if(mapper.bumpDispatch(id,"投递历史待核对",at)==0)mapper.insertDispatch(id,"投递历史待核对",at);
                }
                mapper.state(id,next);
                // 提交重试不能抹去曾经发出请求的证据；此后取消仍须与远端确认。
                if(record.getState().equals("SUBMISSION_FAILED"))mapper.clearDispatchError(id,Instant.now().toString());
                else mapper.clearDispatch(id,Instant.now().toString());
            }
            default -> throw bad("控制命令无效");
        }
        return summary(require(id));
        }
    }

    private JsonObject summary(AgentRunRecord r){var result=gson.toJsonTree(r).getAsJsonObject();result.remove("payload");var p=JsonParser.parseString(r.getPayload()).getAsJsonObject();result.add("mode",p.get("mode"));result.add("executionMode",p.get("executionMode"));result.add("models",p.get("models"));result.add("limits",p.get("limits"));result.add("consultationRoles",p.has("consultationRoles")?p.get("consultationRoles"):new JsonArray());return result;}
    private static JsonArray consultationRoles(JsonObject request){
        var result=new JsonArray();if(!request.has("consultationRoles"))return result;
        var value=request.get("consultationRoles");if(!value.isJsonArray()||value.getAsJsonArray().size()>6)throw bad("会诊角色须为最多六个角色的数组");
        var seen=new HashSet<String>();for(var item:value.getAsJsonArray()){
            if(!item.isJsonPrimitive()||!item.getAsJsonPrimitive().isString())throw bad("会诊角色必须是角色标识");
            String role=item.getAsString();if(role.isBlank()||!seen.add(role))throw bad("会诊角色不能为空或重复");result.add(role);
        }return result;
    }
    private AgentRunRecord require(String id){if(!id.matches("run_[a-zA-Z0-9_-]{8,90}"))throw bad("运行 ID 无效");var r=mapper.find(id);if(r==null)throw new BusinessException(404,"运行不存在");return r;}
    private static JsonObject input(JsonObject state,JsonObject project,JsonObject node){
        var result=new JsonObject();for(String k:List.of("id","title","brief","template","platforms"))result.add(k,project.get(k));result.add("creatorProfile",state.get("profile"));
        var deps=new JsonObject();for(var d:node.getAsJsonArray("dependsOn"))deps.add(d.getAsString(),project.getAsJsonObject("nodes").get(d.getAsString()));result.add("dependencies",deps);
        result.add("currentNode",project.getAsJsonObject("nodes").get(node.get("id").getAsString()));result.add("approvals",project.get("approvals"));
        var visuals=VisualCandidateService.inputs(project,node.get("id").getAsString());if(visuals!=null)result.add("visualInputs",visuals);return result;
    }
    static JsonObject resolveModel(JsonObject state,JsonObject project,String role,String nodeId){
        var maps=new ArrayList<JsonObject>();if(nodeId!=null)maps.add(object(project.getAsJsonObject("nodeBindings"),nodeId));maps.add(project.getAsJsonObject("bindings"));maps.add(object(state.getAsJsonObject("agentBindings"),role));maps.add(state.getAsJsonObject("globalBindings"));
        for(var map:maps)for(String key:List.of("TEXT_REASONING","$default")){if(map.has(key)){var model=find(state.getAsJsonArray("models"),map.get(key).getAsString());if(model!=null&&model.getAsJsonArray("capabilities").asList().stream().anyMatch(c->c.getAsString().equals("TEXT_REASONING")))return model.deepCopy();}}
        return new JsonObject();
    }
    static boolean planOnly(JsonObject node){var kind=node.get("executorKind");return kind!=null&&!"AGENT".equals(kind.getAsString());}
    private static JsonObject object(JsonObject parent,String key){return parent.has(key)?parent.getAsJsonObject(key):new JsonObject();}
    private static JsonObject find(JsonArray array,String id){for(var item:array){var o=item.getAsJsonObject();if(o.get("id").getAsString().equals(id))return o;}return null;}
    private static String sha(JsonObject value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.toString().getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}}
    private static String text(JsonObject o,String key,int max){try{String s=o.get(key).getAsString();if(s.isBlank()||s.length()>max)throw bad("请求字段无效："+key);return s;}catch(NullPointerException|IllegalStateException e){throw bad("缺少请求字段："+key);}}
    private static BusinessException bad(String s){return new BusinessException(400,s);}
}
