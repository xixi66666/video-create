package cn.creator.workbench.service;

import com.google.gson.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;

/** 只连接显式指定的本机回环地址；不调用全局中断或清队列。 */
@Component
public class ComfyClient {
    private final URI endpoint;
    private final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER).build();
    public ComfyClient(@Value("${workbench.comfy.url:http://127.0.0.1:8192}") String url){
        try{endpoint=URI.create(url);if(!"http".equals(endpoint.getScheme())||!"127.0.0.1".equals(endpoint.getHost())||endpoint.getPort()<1||endpoint.getPort()>65535||endpoint.getUserInfo()!=null||endpoint.getQuery()!=null||endpoint.getFragment()!=null||!(endpoint.getPath().isEmpty()||endpoint.getPath().equals("/")))throw new IllegalArgumentException();}
        catch(Exception e){throw new IllegalArgumentException("ComfyUI 地址必须为本机 HTTP 回环地址及端口");}
    }
    private HttpResponse<String> text(String method,String path,String body)throws IOException,InterruptedException{
        var b=HttpRequest.newBuilder(endpoint.resolve(path)).timeout(Duration.ofSeconds(8));
        if(body!=null)b.header("Content-Type","application/json");
        return client.send(b.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(body)).build(),HttpResponse.BodyHandlers.ofString());
    }
    public JsonObject get(String path)throws IOException,InterruptedException{
        var r=text("GET",path,null);if(r.statusCode()!=200||r.body().length()>25_000_000)throw new IOException("ComfyUI 读取失败");
        return JsonParser.parseString(r.body()).getAsJsonObject();
    }
    /** 仅 HTTP 400 代表 ComfyUI 明确拒绝，其余错误均不能证明未受理。 */
    public HttpResponse<String> submit(JsonObject payload)throws IOException,InterruptedException{return text("POST","/prompt",payload.toString());}
    public byte[] video(String filename,String subfolder)throws IOException,InterruptedException{
        if(!filename.matches("[a-zA-Z0-9_. -]{1,200}\\.mp4")||filename.contains("..")||subfolder.length()>200||subfolder.contains("\\")||subfolder.startsWith("/")||Arrays.stream(subfolder.split("/",-1)).anyMatch(s->s.equals("..")||s.equals(".")))throw new IOException("输出文件名无效");
        String path="/view?filename="+enc(filename)+"&subfolder="+enc(subfolder)+"&type=output";
        var req=HttpRequest.newBuilder(endpoint.resolve(path)).timeout(Duration.ofSeconds(60)).GET().build();
        var response=client.send(req,HttpResponse.BodyHandlers.ofInputStream());try(var in=response.body()){
            if(response.statusCode()!=200)throw new IOException("候选文件暂不可读取");
            byte[] bytes=in.readNBytes(50*1024*1024+1);if(bytes.length>50*1024*1024)throw new BusinessException(413,"生成视频超过 50MB 素材上限");return bytes;
        }
    }
    private static String enc(String s){return URLEncoder.encode(s,StandardCharsets.UTF_8);}
}
