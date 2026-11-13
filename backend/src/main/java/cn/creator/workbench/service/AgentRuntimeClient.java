package cn.creator.workbench.service;

import com.google.gson.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;

/** 内部回环通道，凭据只从进程环境读取；不向浏览器泄露。 */
@Component
public class AgentRuntimeClient {
    private final HttpClient http=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(2)).build();
    private final String endpoint,token;
    public AgentRuntimeClient(@Value("${workbench.agent-runtime-url:http://127.0.0.1:8090}") String endpoint){
        this.endpoint=endpoint;this.token=System.getenv().getOrDefault("CREATOR_RUNTIME_TOKEN","");
        if(!endpoint.matches("http://127\\.0\\.0\\.1:[0-9]{2,5}"))throw new IllegalArgumentException("运行服务必须使用本机回环地址");
    }
    public JsonElement get(String path){return request("GET",path,null);}
    public JsonElement post(String path,JsonObject body){return request("POST",path,body);}
    public JsonElement voice(JsonObject body){
        if(token.isBlank())throw new BusinessException(503,"Agent 运行服务未启动");
        try{
            var req=HttpRequest.newBuilder(URI.create(endpoint+"/voice/action")).timeout(Duration.ofSeconds(30))
                .header("X-Creator-Token",token).header("Content-Type","application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString())).build();
            var res=http.send(req,HttpResponse.BodyHandlers.ofString());
            if(res.statusCode()>=400){
                String message="配音服务请求失败，请检查服务状态";
                try{var json=JsonParser.parseString(res.body()).getAsJsonObject();if(json.has("detail")&&json.get("detail").isJsonPrimitive())message=json.get("detail").getAsString();}catch(Exception ignored){}
                throw new BusinessException(res.statusCode()==401?503:res.statusCode(),message);
            }
            return JsonParser.parseString(res.body());
        }catch(BusinessException e){throw e;}
        catch(InterruptedException e){Thread.currentThread().interrupt();throw new BusinessException(503,"配音服务请求被中断");}
        catch(Exception e){throw new BusinessException(503,"配音服务不可达，请检查本机运行服务");}
    }
    /** 同步语音合成单次请求，超时不能自动重试，因为供应商可能已受理。 */
    public JsonElement speech(JsonObject body){
        if(token.isBlank())throw new BusinessException(503,"Agent 运行服务未启动");
        try {
            var req=HttpRequest.newBuilder(URI.create(endpoint+"/speech/mimo"))
                .timeout(Duration.ofSeconds(95)).header("X-Creator-Token",token)
                .header("Content-Type","application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString())).build();
            var res=http.send(req,HttpResponse.BodyHandlers.ofString());
            if(res.statusCode()>=400){
                String message="语音合成失败，请检查配置；没有自动重试";
                try {var result=JsonParser.parseString(res.body()).getAsJsonObject();if(result.has("detail")&&result.get("detail").isJsonPrimitive())message=result.get("detail").getAsString();}catch(Exception ignored){}
                throw new BusinessException(res.statusCode()==401?503:res.statusCode(),message);
            }
            return JsonParser.parseString(res.body());
        } catch(BusinessException e){throw e;}
        catch(InterruptedException e){Thread.currentThread().interrupt();throw new BusinessException(504,"语音请求中断，供应商处理状态未知；没有自动重试");}
        catch(Exception e){throw new BusinessException(504,"语音请求超时或通道中断，供应商处理状态未知；没有自动重试");}
    }
    private JsonElement request(String method,String path,JsonObject body){
        if(token.isBlank())throw new BusinessException(503,"Agent 运行服务未启动，请使用新版 start-local.ps1 启动。");
        try{
            var builder=HttpRequest.newBuilder(URI.create(endpoint+path)).timeout(Duration.ofSeconds(8))
                .header("X-Creator-Token",token).header("Content-Type","application/json");
            builder.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(body.toString()));
            var response=http.send(builder.build(),HttpResponse.BodyHandlers.ofString());
            if(response.statusCode()>=400)throw new BusinessException(response.statusCode()==401?503:response.statusCode(),"Agent 运行服务拒绝请求，请检查状态或运行限制。");
            return JsonParser.parseString(response.body());
        }catch(BusinessException e){throw e;}catch(InterruptedException e){Thread.currentThread().interrupt();throw new BusinessException(503,"Agent 通道被中断");}
        catch(Exception e){throw new BusinessException(503,"Agent 运行服务暂不可达；任务意图已保留，不会重复创建运行。");}
    }
}
