package cn.creator.workbench.api;

import cn.creator.workbench.service.BusinessException;
import cn.creator.workbench.service.WorkspaceService;
import com.google.gson.*;
import jakarta.validation.Validator;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import java.util.UUID;

@RestController
@RequestMapping(value="/api/v1",produces=MediaType.APPLICATION_JSON_VALUE)
public class ApiController {
    private final WorkspaceService service;
    private final Validator validator;
    private final Gson gson=new GsonBuilder().disableHtmlEscaping().create();
    public ApiController(WorkspaceService service,Validator validator){this.service=service;this.validator=validator;}
    @GetMapping("/workspace") public String workspace(){return ok(service.load());}
    @GetMapping("/catalog") public String catalog(){return ok(service.catalog());}
    @GetMapping("/health") public String health(){var data=new JsonObject();data.addProperty("status","UP");data.addProperty("version","0.2.0");data.addProperty("externalExecutionEnabled",false);data.addProperty("localComfyConnectorImplemented",true);return ok(data);}
    @PostMapping(value="/commands",consumes=MediaType.APPLICATION_JSON_VALUE)
    public String command(@RequestBody String body){
        if(body.length()>2_000_000)throw new BusinessException(413,"请求内容过长");
        var dto=gson.fromJson(body,WorkspaceCommand.class);
        if(dto==null||!validator.validate(dto).isEmpty())throw new BusinessException(400,"操作类型、参数和工作区版本不能为空");
        return ok(service.execute(dto));
    }
    public static String ok(JsonElement data){var response=new JsonObject();response.addProperty("code","OK");response.addProperty("message","成功");response.add("data",data);response.addProperty("requestId",UUID.randomUUID().toString());return response.toString();}
}
