package cn.creator.workbench.api;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.*;

class LocalOriginFilterTest {
    private final LocalOriginFilter filter = new LocalOriginFilter("http://127.0.0.1:5178,http://localhost:5178");

    @Test
    void rejectsUntrustedHostEvenForReadOnlyRequests() throws Exception {
        for (String host : new String[]{"attacker.example:8088", "localhost.attacker.example", "127.0.0.1.attacker.example", "127.0.0.1@attacker.example"}) {
            var request = new MockHttpServletRequest("GET", "/api/v1/workspace");
            request.addHeader("Host", host);
            var response = new MockHttpServletResponse();
            var chain = new MockFilterChain();
            filter.doFilter(request, response, chain);
            assertEquals(403, response.getStatus(), host);
            assertNull(chain.getRequest(), host);
        }
    }

    @Test
    void allowsLoopbackHostsAndStillChecksWriteOrigin() throws Exception {
        for (String host : new String[]{"127.0.0.1:8088", "localhost:5178", "[::1]:8088"}) {
            var request = new MockHttpServletRequest("GET", "/api/v1/workspace");
            request.addHeader("Host", host);
            var response = new MockHttpServletResponse();
            var chain = new MockFilterChain();
            filter.doFilter(request, response, chain);
            assertNotNull(chain.getRequest(), host);
        }
        var request = new MockHttpServletRequest("POST", "/api/v1/commands");
        request.addHeader("Host", "127.0.0.1:8088");
        request.addHeader("Origin", "https://attacker.example");
        var response = new MockHttpServletResponse();
        var chain = new MockFilterChain();
        filter.doFilter(request, response, chain);
        assertEquals(403, response.getStatus());
        assertNull(chain.getRequest());
    }
}
