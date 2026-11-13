package cn.creator.workbench.service;

import com.google.gson.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;

/** 连接受管理员配置的远程媒体 Worker；这里的协议不是 ComfyUI 原生协议。 */
@Component
public class MediaExecutorClient {
    private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).followRedirects(HttpClient.Redirect.NEVER).build();
    private final String endpoint,token;
    private final boolean enabled;
    public MediaExecutorClient(@Value("${workbench.media-executor-url:}")String endpoint,@Value("${workbench.media-executor-enabled:false}")boolean enabled){
        this.endpoint=endpoint.replaceAll("/+$","");this.enabled=enabled;token=System.getenv().getOrDefault("CREATOR_MEDIA_EXECUTOR_TOKEN","");
        if(!endpoint.isBlank()){var uri=URI.create(endpoint);if(!java.util.Set.of("http","https").contains(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null)throw new IllegalArgumentException("媒体执行端须为不含凭据的 HTTP(S) 地址");}
    }
    public boolean configured(){return enabled&&!endpoint.isBlank();}
    public JsonObject readiness(){
        var data=new JsonObject();data.addProperty("configured",configured());data.addProperty("online",false);data.addProperty("message","尚未配置远程媒体执行端，可继续手工导入候选");
        if(configured())try{var health=request("GET","/v1/health",null);if(!health.has("protocol")||!"creator-media-v1".equals(health.get("protocol").getAsString()))throw new BusinessException(503,"执行端协议不匹配");data.addProperty("online",true);data.addProperty("message","远程媒体执行端可用");for(String key:java.util.List.of("mediaKinds","supportsSeed","referenceRoles"))if(health.has(key))data.add(key,health.get(key).deepCopy());}catch(BusinessException e){data.addProperty("message",e.getMessage());}
        return data;
    }
    public JsonObject submit(JsonObject payload){return request("POST","/v1/jobs",payload);}
    public JsonObject status(String id){return request("GET","/v1/jobs/"+safe(id),null);}
    public JsonObject cancel(String id){return request("POST","/v1/jobs/"+safe(id)+"/cancel",new JsonObject());}
    public void uploadInput(String id,String inputId,byte[] bytes){
        if(!configured())throw new BusinessException(503,"远程媒体执行端尚未启用");
        try{var b=HttpRequest.newBuilder(URI.create(endpoint+"/v1/jobs/"+safe(id)+"/inputs/"+safe(inputId))).timeout(Duration.ofSeconds(30)).header("Content-Type","application/octet-stream");if(!token.isBlank())b.header("Authorization","Bearer "+token);var response=http.send(b.POST(HttpRequest.BodyPublishers.ofByteArray(bytes)).build(),HttpResponse.BodyHandlers.discarding());if(response.statusCode()<200||response.statusCode()>=300)throw new BusinessException(503,"参考图传输失败，请核对执行端");}catch(InterruptedException e){Thread.currentThread().interrupt();throw new BusinessException(503,"参考图传输中断");}catch(IOException e){throw new BusinessException(503,"参考图传输失败");}
    }
    public byte[] output(String id,String outputId){return send("GET","/v1/jobs/"+safe(id)+"/outputs/"+safe(outputId),null,50*1024*1024);}
    private JsonObject request(String method,String path,JsonObject body){try{var json=JsonParser.parseString(new String(send(method,path,body,1024*1024),java.nio.charset.StandardCharsets.UTF_8));if(!json.isJsonObject())throw new IllegalArgumentException();return json.getAsJsonObject();}catch(BusinessException e){throw e;}catch(Exception e){throw new BusinessException(503,"媒体执行端响应格式无效");}}
    private byte[] send(String method,String path,JsonObject body,int limit){
        if(!configured())throw new BusinessException(503,"远程媒体执行端尚未配置或启用");
        try{var b=HttpRequest.newBuilder(URI.create(endpoint+path)).timeout(Duration.ofSeconds(15)).header("Content-Type","application/json");if(!token.isBlank())b.header("Authorization","Bearer "+token);b.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(body.toString()));var response=http.send(b.build(),HttpResponse.BodyHandlers.ofInputStream());try(var in=response.body()){if(response.statusCode()<200||response.statusCode()>=300)throw new BusinessException(response.statusCode()==404?404:503,"媒体执行端暂不可用，请核对原任务");var bytes=in.readNBytes(limit+1);if(bytes.length>limit)throw new BusinessException(413,"执行端返回内容超出限制");return bytes;}}
        catch(BusinessException e){throw e;}catch(InterruptedException e){Thread.currentThread().interrupt();throw new BusinessException(503,"媒体执行请求中断，需查询原任务");}catch(IOException e){throw new BusinessException(503,"媒体执行端连接失败，受理情况需核对");}
    }
    private static String safe(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{1,100}"))throw new BusinessException(400,"执行标识无效");return id;}
}
