package cn.creator.workbench.api;

import cn.creator.workbench.service.*;
import com.google.gson.*;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping(value="/api/v1/comfy-runs",produces=MediaType.APPLICATION_JSON_VALUE)
public class ComfyRunController {
    private final ComfyRunService service;
    public ComfyRunController(ComfyRunService service){this.service=service;}
    @GetMapping("/readiness") public String readiness(){return ApiController.ok(service.readiness());}
    @GetMapping public String list(@RequestParam(required=false) String projectId){return ApiController.ok(service.list(projectId));}
    @PostMapping(consumes=MediaType.APPLICATION_JSON_VALUE) public String create(@RequestBody String body){if(body.length()>5000)throw new BusinessException(413,"请求过长");var data=JsonParser.parseString(body);if(!data.isJsonObject())throw new BusinessException(400,"请求必须为 JSON 对象");return ApiController.ok(service.create(data.getAsJsonObject()));}
    @GetMapping("/{id}") public String detail(@PathVariable String id){return ApiController.ok(service.detail(id));}
    @PostMapping("/{id}/adopt") public String adopt(@PathVariable String id){return ApiController.ok(service.adopt(id));}
}
