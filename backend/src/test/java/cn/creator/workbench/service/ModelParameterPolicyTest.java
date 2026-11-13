package cn.creator.workbench.service;

import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ModelParameterPolicyTest {
    @Test void reasoningEffortIsExplicitAndLimitedToChatCompletions() {
        var valid=JsonParser.parseString("{\"temperature\":0,\"reasoning_effort\":\"none\"}");
        assertDoesNotThrow(()->ModelParameterPolicy.validateLiveAgent(valid,"CHAT_COMPLETIONS_COMPATIBLE"));
        assertDoesNotThrow(()->ModelParameterPolicy.validateLiveAgent(JsonParser.parseString("{}"),"RESPONSES"));
        assertThrows(BusinessException.class,()->ModelParameterPolicy.validateLiveAgent(valid,"RESPONSES"));
        for(String value:new String[]{"\"low\"","\"high\"","\"max\"","\"\"","null","{}","0","false"}) {
            var invalid=JsonParser.parseString("{\"reasoning_effort\":"+value+"}");
            assertThrows(BusinessException.class,()->ModelParameterPolicy.validateLiveAgent(invalid,"CHAT_COMPLETIONS_COMPATIBLE"));
        }
    }
}
