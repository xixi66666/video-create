package cn.creator.workbench.service;

import com.google.gson.*;
import org.springframework.core.io.ClassPathResource;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Pattern;

/** 与前端共用 specs 中的参数规则，服务端始终独立校验。 */
final class ModelParameterPolicy {
    private static final Set<String> ALLOWED = new HashSet<>();
    private static final Pattern SENSITIVE_KEY;
    private static final Pattern SENSITIVE_VALUE;
    static {
        try (var input = new ClassPathResource("model-parameter-policy.json").getInputStream()) {
            var policy = JsonParser.parseString(new String(input.readAllBytes(), StandardCharsets.UTF_8)).getAsJsonObject();
            policy.getAsJsonArray("allowedTopLevelKeys").forEach(key -> ALLOWED.add(key.getAsString()));
            SENSITIVE_KEY = Pattern.compile(policy.get("sensitiveKeyPattern").getAsString(), Pattern.CASE_INSENSITIVE);
            SENSITIVE_VALUE = Pattern.compile(policy.get("sensitiveValuePattern").getAsString(), Pattern.CASE_INSENSITIVE);
        } catch (Exception error) { throw new ExceptionInInitializerError(error); }
    }
    static void validate(JsonElement parameters) {
        if (parameters == null || !parameters.isJsonObject()) throw new BusinessException(400, "参数必须为 JSON 对象");
        if (containsCredential(parameters)) throw new BusinessException(400, "参数中不能保存密钥、密码或认证头，请使用环境变量引用");
        if (!ALLOWED.containsAll(parameters.getAsJsonObject().keySet())) throw new BusinessException(400, "参数包含尚未支持的选项，请只使用已支持的推理参数");
    }
    static void validateRecordingParameters(JsonElement parameters) {
        if(parameters==null||!parameters.isJsonObject())throw new BusinessException(400,"参数必须为 JSON 对象");
        if(containsCredential(parameters))throw new BusinessException(400,"生成参数不能包含密钥或认证信息");
    }
    /** 在业务受理前拒绝适配器不支持的参数，避免进入 outbox 后才失败。 */
    static void validateLiveAgent(JsonElement parameters, String protocol) {
        validate(parameters);
        var unsupported=new ArrayList<String>();
        for(var key:parameters.getAsJsonObject().keySet())if(!Set.of("temperature","top_p","reasoning_effort").contains(key))unsupported.add(key);
        if(!unsupported.isEmpty())throw new BusinessException(409,"实时 Agent 目前只支持 temperature/top_p/reasoning_effort 参数；请调整模型配置后再运行："+String.join("、",unsupported));
        var effort=parameters.getAsJsonObject().get("reasoning_effort");
        if(effort!=null && (!"CHAT_COMPLETIONS_COMPATIBLE".equals(protocol) || !effort.isJsonPrimitive() || !effort.getAsJsonPrimitive().isString() || !"none".equals(effort.getAsString())))
            throw new BusinessException(409,"reasoning_effort 当前仅支持 Chat Completions 协议的 none");
    }
    private static boolean containsCredential(JsonElement element) {
        if (element.isJsonObject()) {
            for (var entry : element.getAsJsonObject().entrySet()) {
                if (SENSITIVE_KEY.matcher(entry.getKey()).find() || containsCredential(entry.getValue())) return true;
            }
        } else if (element.isJsonArray()) {
            for (var item : element.getAsJsonArray()) if (containsCredential(item)) return true;
        } else if (element.isJsonPrimitive() && element.getAsJsonPrimitive().isString()) {
            return SENSITIVE_VALUE.matcher(element.getAsString()).find();
        }
        return false;
    }
}
