package cn.creator.workbench.api;

import cn.creator.workbench.service.*;
import com.google.gson.*;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;

/** 浏览器仅操作本地任务，不接收或保存远端认证信息。 */
@RestController
@RequestMapping(value="/api/v1/visual-jobs",produces=MediaType.APPLICATION_JSON_VALUE)
public class VisualGenerationController {
    private final VisualGenerationService service;
    public VisualGenerationController(VisualGenerationService service){this.service=service;}
    @GetMapping("/readiness") public String readiness(){return ApiController.ok(service.readiness());}
    @GetMapping public String list(@RequestParam String projectId){return ApiController.ok(service.list(projectId));}
    @GetMapping("/{id}") public String detail(@PathVariable String id){return ApiController.ok(service.detail(id));}
    @PostMapping(consumes=MediaType.APPLICATION_JSON_VALUE) public String create(@RequestBody String body){return ApiController.ok(service.create(parse(body)));}
    @PostMapping(value="/{id}/control",consumes=MediaType.APPLICATION_JSON_VALUE) public String control(@PathVariable String id,@RequestBody String body){return ApiController.ok(service.control(id,parse(body)));}
    private JsonObject parse(String body){if(body.length()>8000)throw new BusinessException(413,"请求过长");var parsed=JsonParser.parseString(body);if(!parsed.isJsonObject())throw new BusinessException(400,"请求必须为对象");return parsed.getAsJsonObject();}
}
