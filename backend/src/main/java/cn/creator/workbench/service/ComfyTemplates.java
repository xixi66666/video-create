package cn.creator.workbench.service;

import com.google.gson.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** 受信任的本地工作流登记；业务节点不包含模型名或工作流节点号。 */
@Component
public class ComfyTemplates {
    private final Path registry;
    public ComfyTemplates(@Value("${workbench.comfy.templates:config/comfy-templates.json}") String path){registry=Path.of(path).toAbsolutePath().normalize();}
    public List<JsonObject> all(){
        try{
            if(!Files.isRegularFile(registry))return List.of();
            var root=JsonParser.parseString(Files.readString(registry,StandardCharsets.UTF_8)).getAsJsonObject();
            var result=new ArrayList<JsonObject>();for(var e:root.getAsJsonArray("templates"))result.add(e.getAsJsonObject());return result;
        }catch(Exception e){throw new BusinessException(503,"ComfyUI 工作流登记文件无效");}
    }
    public JsonObject find(String id){return all().stream().filter(t->id.equals(t.get("id").getAsString())).findFirst().orElseThrow(()->new BusinessException(400,"工作流模板不存在"));}
    public JsonObject workflow(JsonObject template){
        try{
            Path base=registry.getParent().toRealPath();Path relative=Path.of(template.get("workflowFile").getAsString());
            if(relative.isAbsolute())throw new IllegalArgumentException();
            Path path=base.resolve(relative).normalize().toRealPath();if(!path.startsWith(base)||!Files.isRegularFile(path)||Files.size(path)>1_000_000)throw new IllegalArgumentException();
            var workflow=JsonParser.parseString(Files.readString(path,StandardCharsets.UTF_8)).getAsJsonObject();
            if(workflow.isEmpty()||workflow.size()>100)throw new IllegalArgumentException();
            for(var field:List.of("promptBinding","seedBinding")){
                var binding=template.getAsJsonObject(field);String node=binding.get("nodeId").getAsString(),input=binding.get("inputName").getAsString();
                if(!workflow.has(node)||!workflow.getAsJsonObject(node).getAsJsonObject("inputs").has(input))throw new IllegalArgumentException();
            }
            if(!template.has("outputNodeIds")||template.getAsJsonArray("outputNodeIds").isEmpty())throw new IllegalArgumentException();
            for(var id:template.getAsJsonArray("outputNodeIds"))if(!workflow.has(id.getAsString()))throw new IllegalArgumentException();
            return workflow;
        }catch(Exception e){throw new BusinessException(503,"工作流模板路径或参数绑定无效");}
    }
    public void apply(JsonObject workflow,JsonObject template,String key,JsonElement value){var b=template.getAsJsonObject(key);workflow.getAsJsonObject(b.get("nodeId").getAsString()).getAsJsonObject("inputs").add(b.get("inputName").getAsString(),value);}
}
