package cn.creator.workbench.api;

import cn.creator.workbench.service.AgentRuntimeClient;
import cn.creator.workbench.service.BusinessException;
import com.google.gson.JsonParser;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping(value="/api/v1/speech",produces=MediaType.APPLICATION_JSON_VALUE)
public class SpeechController {
    private final AgentRuntimeClient runtime;
    public SpeechController(AgentRuntimeClient runtime){this.runtime=runtime;}
    @PostMapping(value="/mimo",consumes=MediaType.APPLICATION_JSON_VALUE)
    public String mimo(@RequestBody String body){
        if(body.length()>5000)throw new BusinessException(413,"语音请求过长");
        var request=JsonParser.parseString(body);
        if(!request.isJsonObject())throw new BusinessException(400,"请求必须为 JSON 对象");
        return ApiController.ok(runtime.speech(request.getAsJsonObject()));
    }
}
