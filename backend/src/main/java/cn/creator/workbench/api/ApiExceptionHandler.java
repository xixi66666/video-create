package cn.creator.workbench.api;

import cn.creator.workbench.service.BusinessException;
import com.google.gson.*;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import java.util.UUID;

@RestControllerAdvice
public class ApiExceptionHandler {
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<String> business(BusinessException e){return error(e.getStatus(),e.getMessage());}
    @ExceptionHandler({IllegalArgumentException.class,IllegalStateException.class,UnsupportedOperationException.class,NullPointerException.class,ArithmeticException.class,JsonParseException.class})
    public ResponseEntity<String> invalid(RuntimeException e){return error(400,"请求格式或字段类型无效，请检查输入。");}
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<String> upload(){return error(413,"单个素材文件最大 50MB。");}
    private ResponseEntity<String> error(int status,String message){var body=new JsonObject();body.addProperty("code",status==409?"VERSION_OR_STATE_CONFLICT":"REQUEST_ERROR");body.addProperty("message",message);body.add("data",JsonNull.INSTANCE);body.addProperty("requestId",UUID.randomUUID().toString());return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(body.toString());}
}
