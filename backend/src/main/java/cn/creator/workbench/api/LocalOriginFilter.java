package cn.creator.workbench.api;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;
import java.util.*;

/** 本地单用户版：限制 Host 与写请求来源；不等同于多用户身份认证。 */
@Component
public class LocalOriginFilter extends OncePerRequestFilter {
    private final Set<String> allowed;
    @Value("${workbench.test-instance-id:}") private String testInstanceId="";
    public LocalOriginFilter(@Value("${workbench.allowed-origins}") String origins){allowed=new HashSet<>(Arrays.asList(origins.split(",")));}
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)throws ServletException,IOException{
        if(!testInstanceId.isBlank())response.setHeader("X-Workbench-Test-Instance",testInstanceId);
        // 监听回环地址并不能阻止 DNS 重绑定；未经检查的 Host 可能让其他站点同源读取本机数据。
        String host=request.getHeader("Host");
        if(host==null)host=request.getServerName(); // HTTP/1.0 客户端可能没有 Host 头。
        if(host==null||!host.toLowerCase(Locale.ROOT).matches("(?:localhost|127\\.0\\.0\\.1)(?::[0-9]{1,5})?|\\[::1\\](?::[0-9]{1,5})?|::1")){
            response.sendError(403,"请求主机未获允许");return;
        }
        String origin=request.getHeader("Origin");
        if(!Set.of("GET","HEAD","OPTIONS").contains(request.getMethod())&&origin!=null&&!allowed.contains(origin)){response.sendError(403,"请求来源未获允许");return;}
        response.setHeader("X-Content-Type-Options","nosniff");chain.doFilter(request,response);
    }
}
