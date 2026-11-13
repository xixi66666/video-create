package cn.creator.workbench.service;

import cn.creator.workbench.api.WorkspaceCommand;
import cn.creator.workbench.persistence.*;
import com.google.gson.*;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.web.multipart.MultipartFile;
import java.io.*;
import java.nio.file.*;
import java.time.Instant;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** 生成意图持久化、异步投递、原任务恢复与候选回收；不执行自动采用。 */
@Service
public class VisualGenerationService {
    private final VisualJobMapper jobs;
    private final WorkspaceService workspace;
    private final MediaExecutorClient executor;
    private final MediaService media;
    private final TransactionTemplate transaction;
    private final AtomicBoolean dispatching=new AtomicBoolean();
    private final Object[] jobLocks=new Object[64];
    public VisualGenerationService(VisualJobMapper jobs,WorkspaceService workspace,MediaExecutorClient executor,MediaService media,PlatformTransactionManager manager){this.jobs=jobs;this.workspace=workspace;this.executor=executor;this.media=media;transaction=new TransactionTemplate(manager);Arrays.setAll(jobLocks,i->new Object());}
    private Object jobLock(String id){return jobLocks[(id.hashCode()&0x7fffffff)%jobLocks.length];}
    public JsonObject detail(String id){return summary(require(id));}
    public JsonObject readiness(){return executor.readiness();}
    public JsonArray list(String projectId){find(workspace.load(),"projects",projectId);var result=new JsonArray();for(var job:jobs.list(projectId).stream().limit(200).toList())result.add(summary(job));return result;}

    public synchronized JsonArray create(JsonObject request){
        return transaction.execute(status->createInTransaction(request));
    }
    private JsonArray createInTransaction(JsonObject request){
        String id=text(request,"id"),projectId=text(request,"projectId"),batchId=text(request,"batchId");if(!id.matches("draw_[A-Za-z0-9_-]{8,70}"))throw bad("抽取编号无效");
        int count=(int)number(request,"count",8);if(count<1)throw bad("每次生成1至8条候选");long ceiling=number(request,"maxCostCents",100000000);Long seed=request.has("seedStart")?number(request,"seedStart",2147483639):null;
        var signature=new JsonObject();signature.addProperty("projectId",projectId);signature.addProperty("batchId",batchId);signature.addProperty("count",count);signature.addProperty("maxCostCents",ceiling);if(seed!=null)signature.addProperty("seedStart",seed);
        var first=jobs.find(id+"_0");if(first!=null){if(!JsonParser.parseString(first.getPayload()).getAsJsonObject().get("request").equals(signature))throw new BusinessException(409,"抽取编号已用于其他请求");var existing=new JsonArray();for(int i=0;i<count;i++){var saved=jobs.find(id+"_"+i);if(saved==null)throw new BusinessException(409,"抽取记录不完整，请核对任务");existing.add(summary(saved));}return existing;}
        if(jobs.list(projectId).size()+count>4000)throw bad("作品生成任务已达上限，请先归档核对历史");
        // 网络健康检查在获取工作区事务锁前执行，避免等待远端时阻塞整个工作区。
        var ready=executor.readiness();if(!ready.get("online").getAsBoolean())throw new BusinessException(503,ready.get("message").getAsString());
        var state=workspace.load();if(number(request,"expectedVersion",Long.MAX_VALUE)!=state.get("version").getAsLong())throw new BusinessException(409,"工作区已变化，请刷新后重试");var project=find(state,"projects",projectId);var w=project.getAsJsonObject("visualWorkbench");if(w==null)throw bad("请先建立制作需求与候选批次");var batch=find(w,"batches",batchId);var need=find(w,"needs",batch.get("needId").getAsString());String owner=text(need,"productionNodeId");if(!Set.of("N27","N29").contains(owner))throw bad("请先将需求归类到视频制作任务");workspace.requireExecutable(project,owner);
        String kind=text(batch,"mediaKind");if(!ready.has("mediaKinds")||!ready.getAsJsonArray("mediaKinds").contains(new JsonPrimitive(kind)))throw bad("执行端不支持此素材类型");if(seed!=null&&(!ready.has("supportsSeed")||!ready.get("supportsSeed").getAsBoolean()))throw bad("此执行端不支持指定 seed");
        long reserved=0;for(var item:w.getAsJsonArray("candidates")){var c=item.getAsJsonObject();if(batch.get("id").equals(c.get("batchId")))reserved+=c.get("costCents").getAsLong();}for(var job:jobs.list(projectId))if(job.getBatchId().equals(batchId)&&!job.getState().equals("SUCCEEDED")&&!(Set.of("FAILED","CANCELLED").contains(job.getState())&&job.getSubmittedAt()==null))reserved+=JsonParser.parseString(job.getPayload()).getAsJsonObject().get("maxCostCents").getAsLong();if(reserved+ceiling*count>batch.get("budgetCents").getAsLong())throw bad("已登记费用与待执行预留超过批次预算");
        var references=new JsonArray();if(batch.has("references"))for(var raw:batch.getAsJsonArray("references")){var ref=raw.getAsJsonObject();var candidate=find(w,"candidates",text(ref,"candidateId"));if("REJECTED".equals(text(candidate,"status")))throw bad("参考候选已淘汰，请重新建立批次");var file=media.find(fileId(text(ref,"fileRef")));media.verify(file);if(!file.getSha256().equals(text(ref,"sha256")))throw bad("参考原件校验值不匹配");references.add(ref.deepCopy());}
        var created=new JsonArray();for(int i=0;i<count;i++){var payload=new JsonObject();payload.addProperty("protocol","creator-media-v1");payload.addProperty("id",id+"_"+i);payload.addProperty("projectId",projectId);payload.addProperty("productionNodeId",owner);payload.add("need",need.deepCopy());payload.add("batch",batch.deepCopy());payload.addProperty("mediaKind",kind);payload.addProperty("prompt",text(batch,"prompt"));payload.add("parameters",batch.get("parameters").deepCopy());payload.add("references",references.deepCopy());payload.addProperty("maxCostCents",ceiling);if(seed!=null)payload.addProperty("seed",seed+i);payload.add("request",signature.deepCopy());
            var job=new VisualJobRecord();job.setId(id+"_"+i);job.setProjectId(projectId);job.setBatchId(batchId);job.setNeedId(text(need,"id"));job.setPayload(payload.toString());job.setState("QUEUED");job.setCreatedAt(now());job.setUpdatedAt(now());jobs.insert(job);created.add(summary(job));}
        return created;
    }

    public synchronized JsonObject control(String id,JsonObject request){
        synchronized(jobLock(id)){
        String action=text(request,"action");
        for(int attempt=0;attempt<4;attempt++){
            var job=require(id);String next;
            if(action.equals("CANCEL")){
                if(Set.of("SUCCEEDED","FAILED","CANCELLED","CANCEL_REQUESTED").contains(job.getState()))return summary(job);
                next=job.getState().equals("QUEUED")?"CANCELLED":"CANCEL_REQUESTED";
            }else if(action.equals("RECOVER")){
                if(!Set.of("UNKNOWN","COLLECTION_FAILED","SUBMITTING").contains(job.getState()))throw bad("当前任务不需要恢复");
                next="SUBMITTED";
            }else throw bad("支持 CANCEL 或 RECOVER；继续抽取请创建新任务");
            // 后台线程可能刚刚改变状态；重新读取并重试，不能静默丢失取消请求。
            if(change(job,next,null))return summary(require(id));
        }
        throw new BusinessException(409,"任务状态正在变化，请刷新后重试");
        }
    }

    @Scheduled(fixedDelay=2500)
    public void dispatch(){if(!executor.configured()||!dispatching.compareAndSet(false,true))return;try{for(var job:jobs.pending())process(job);}finally{dispatching.set(false);}}
    void process(VisualJobRecord job){
        try{
            if(job.getState().equals("QUEUED")){
                // 正式执行前再次检查项目状态、制作依赖与 G03，后台不会跨过人工拍板。
                var project=find(workspace.load(),"projects",job.getProjectId());workspace.requireExecutable(project,JsonParser.parseString(job.getPayload()).getAsJsonObject().get("productionNodeId").getAsString());
                if(jobs.state(job.getId(),"QUEUED","SUBMITTING",null,now())!=1)return;job.setState("SUBMITTING");
                var payload=JsonParser.parseString(job.getPayload()).getAsJsonObject();var references=payload.getAsJsonArray("references");
                if(stopBeforeSubmit(job))return;
                for(var raw:references){
                    if(stopBeforeSubmit(job))return;
                    var ref=raw.getAsJsonObject();var file=media.find(fileId(text(ref,"fileRef")));media.verify(file);byte[] bytes;try(var in=media.resource(file).getInputStream()){bytes=in.readNBytes(50*1024*1024+1);}if(bytes.length>50*1024*1024)throw bad("参考素材过大");String inputId=text(ref,"candidateId");executor.uploadInput(job.getId(),inputId,bytes);ref.remove("fileRef");ref.addProperty("inputId",inputId);
                }
                synchronized(jobLock(job.getId())){
                    // 与取消操作串行：取消先到时绝不发送生成请求；提交已开始则随后同步远端取消。
                    if(stopBeforeSubmit(job))return;
                    payload.remove("request");var accepted=executor.submit(payload);if(!job.getId().equals(text(accepted,"id")))throw new BusinessException(503,"执行端返回了不匹配的任务编号");change(job,"SUBMITTED",null);
                }
                return;
            }
            if(job.getState().equals("COLLECTION_FAILED")){change(job,"COLLECTION_FAILED",job.getError());return;} // 人工恢复文件回收，不重新生成。
            if(job.getState().equals("CANCEL_REQUESTED"))try{executor.cancel(job.getId());}catch(BusinessException unsupported){change(job,"CANCEL_REQUESTED","执行端尚未确认取消，继续查询原任务");}
            var remote=executor.status(job.getId());if(!job.getId().equals(text(remote,"id")))throw bad("执行端任务编号不匹配");String state=text(remote,"state");
            if(state.equals("SUCCEEDED")){collect(job,remote);return;}
            if(state.equals("FAILED")||state.equals("CANCELLED")){change(job,state,state.equals("FAILED")?"执行端生成失败，请检查任务；继续抽取会创建新任务":null);return;}
            if(!Set.of("QUEUED","RUNNING").contains(state))throw bad("执行端状态无效");if(!job.getState().equals("CANCEL_REQUESTED"))change(job,state.equals("RUNNING")?"RUNNING":"SUBMITTED",null);
        }catch(Exception failure){boolean submitting=job.getState().equals("SUBMITTING");String message=submitting?"提交结果未知，请查询原任务，系统不会自动重发生成请求":failure instanceof BusinessException?failure.getMessage():"执行端处理失败，请查询原任务";change(job,submitting?"UNKNOWN":job.getState().equals("QUEUED")?"FAILED":job.getState(),message);}
    }
    private boolean stopBeforeSubmit(VisualJobRecord job){
        var fresh=require(job.getId());
        if(fresh.getState().equals("CANCEL_REQUESTED")){
            // 尚未提交生成请求，可确认本机任务已取消；已上传的参考文件由执行端处理。
            if(change(fresh,"CANCELLED",null))job.setState("CANCELLED");
            return true;
        }
        return !fresh.getState().equals("SUBMITTING");
    }
    private void collect(VisualJobRecord job,JsonObject remote){
        try{var outputs=remote.getAsJsonArray("outputs");if(outputs==null||outputs.size()!=1)throw bad("每个生成任务必须返回一个原件");var output=outputs.get(0).getAsJsonObject();String type=text(output,"mediaType");var payload=JsonParser.parseString(job.getPayload()).getAsJsonObject();boolean image=payload.get("mediaKind").getAsString().equals("IMAGE");if(!(image?Set.of("image/png","image/jpeg","image/webp"):Set.of("video/mp4","video/webm")).contains(type))throw bad("执行端输出类型不匹配");byte[] bytes=executor.output(job.getId(),text(output,"id"));String checksum=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));if(!checksum.equals(text(output,"sha256")))throw bad("执行端输出校验失败");long cost=number(remote,"costCents",100000000);if(cost>payload.get("maxCostCents").getAsLong())throw bad("执行端报告费用超出本次预留，请人工核对");
            transaction.executeWithoutResult(status->{var fresh=require(job.getId());if(Set.of("SUCCEEDED","CANCELLED").contains(fresh.getState()))return;var state=workspace.load();var p=find(state,"projects",job.getProjectId());var w=p.getAsJsonObject("visualWorkbench");String candidateId="generated_"+job.getId();if(w.getAsJsonArray("candidates").asList().stream().noneMatch(x->candidateId.equals(x.getAsJsonObject().get("id").getAsString()))){try{
                var file=media.save(new GeneratedFile(text(output,"fileName"),type,bytes));var asset=new JsonObject();asset.addProperty("id","asset_"+job.getId());asset.addProperty("name",file.getOriginalName());asset.addProperty("type",type);asset.addProperty("size",bytes.length);asset.addProperty("projectId",job.getProjectId());asset.addProperty("fileRef","/api/v1/files/"+file.getId());asset.addProperty("sha256",checksum);asset.addProperty("source","远程生成任务 "+job.getId());asset.addProperty("createdAt",now());var add=new JsonObject();add.add("asset",asset);state=workspace.execute(new WorkspaceCommand("ADD_ASSET",add,state.get("version").getAsLong()));var data=new JsonObject();data.addProperty("projectId",job.getProjectId());data.addProperty("id",candidateId);data.addProperty("batchId",job.getBatchId());data.addProperty("assetId",asset.get("id").getAsString());data.addProperty("costCents",cost);data.addProperty("note","来自生成任务 "+job.getId());data.addProperty("seed",payload.has("seed")?payload.get("seed").getAsString():"");if(!image)data.addProperty("durationMs",number(output,"durationMs",86400000));workspace.execute(new WorkspaceCommand("IMPORT_VISUAL_CANDIDATE",data,state.get("version").getAsLong()));
            }catch(IOException e){throw new BusinessException(503,"生成原件保存失败，可恢复原任务回收");}}change(fresh,"SUCCEEDED",null);});
        }catch(Exception failure){change(require(job.getId()),"COLLECTION_FAILED",failure instanceof BusinessException?failure.getMessage():"文件回收失败，可恢复原任务；不会再次生成");}
    }
    private boolean change(VisualJobRecord job,String state,String error){if(error!=null&&error.length()>500)error=error.substring(0,500);if(jobs.state(job.getId(),job.getState(),state,error,now())==1){job.setState(state);job.setError(error);return true;}return false;}
    private VisualJobRecord require(String id){if(!id.matches("draw_[A-Za-z0-9_-]{8,85}"))throw bad("任务编号无效");var job=jobs.find(id);if(job==null)throw new BusinessException(404,"生成任务不存在");return job;}
    private static JsonObject summary(VisualJobRecord job){var d=new JsonObject();d.addProperty("id",job.getId());d.addProperty("projectId",job.getProjectId());d.addProperty("needId",job.getNeedId());d.addProperty("batchId",job.getBatchId());d.addProperty("state",job.getState());d.addProperty("createdAt",job.getCreatedAt());if(job.getError()!=null)d.addProperty("error",job.getError());var p=JsonParser.parseString(job.getPayload()).getAsJsonObject();d.addProperty("maxCostCents",p.get("maxCostCents").getAsLong());if(p.has("seed"))d.add("seed",p.get("seed"));return d;}
    private static JsonObject find(JsonObject parent,String key,String id){for(var raw:parent.getAsJsonArray(key)){var x=raw.getAsJsonObject();if(id.equals(x.get("id").getAsString()))return x;}throw bad("对应的"+key+"记录不存在");}
    private static String text(JsonObject p,String key){var v=p.get(key);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isString()||v.getAsString().isBlank()||v.getAsString().length()>10000)throw bad(key+"无效");return v.getAsString();}
    private static long number(JsonObject p,String key,long max){try{var v=p.get(key);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isNumber())throw bad(key+"须为整数");long n=v.getAsBigDecimal().longValueExact();if(n<0||n>max)throw bad(key+"超出范围");return n;}catch(ArithmeticException e){throw bad(key+"须为整数");}}
    private static String fileId(String ref){if(!ref.matches("/api/v1/files/[A-Za-z0-9_-]+"))throw bad("参考原件引用无效");return ref.substring(ref.lastIndexOf('/')+1);}
    private static String now(){return Instant.now().toString();}
    private static BusinessException bad(String message){return new BusinessException(400,message);}
    private record GeneratedFile(String name,String type,byte[] bytes) implements MultipartFile {
        public String getName(){return "file";}public String getOriginalFilename(){return name;}public String getContentType(){return type;}public boolean isEmpty(){return bytes.length==0;}public long getSize(){return bytes.length;}public byte[] getBytes(){return bytes;}public InputStream getInputStream(){return new ByteArrayInputStream(bytes);}public void transferTo(File file)throws IOException{Files.write(file.toPath(),bytes);}
    }
}
