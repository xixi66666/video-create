package cn.creator.workbench.service;

import com.sun.net.httpserver.HttpServer;
import com.google.gson.*;
import org.junit.jupiter.api.Test;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class MediaExecutorClientTest {
    @Test void remoteProtocolTransfersReferencesAndRetrievesOwnedOutputs()throws Exception{
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);var seen=new ArrayList<String>();byte[] image={1,2,3};
        server.createContext("/v1",exchange->{seen.add(exchange.getRequestMethod()+" "+exchange.getRequestURI().getPath());String path=exchange.getRequestURI().getPath();byte[] result;if(path.endsWith("/health"))result="{\"protocol\":\"creator-media-v1\",\"mediaKinds\":[\"IMAGE\",\"VIDEO\"]}".getBytes(StandardCharsets.UTF_8);else if(path.endsWith("/inputs/ref")){assertArrayEquals(image,exchange.getRequestBody().readAllBytes());result="{}".getBytes();}else if(path.endsWith("/outputs/out"))result=image;else result="{\"id\":\"draw_example_0\",\"state\":\"RUNNING\"}".getBytes();exchange.sendResponseHeaders(200,result.length);exchange.getResponseBody().write(result);exchange.close();});server.start();
        try{var client=new MediaExecutorClient("http://127.0.0.1:"+server.getAddress().getPort(),true);assertTrue(client.readiness().get("online").getAsBoolean());client.uploadInput("draw_example_0","ref",image);client.submit(JsonParser.parseString("{\"id\":\"draw_example_0\"}").getAsJsonObject());client.status("draw_example_0");assertArrayEquals(image,client.output("draw_example_0","out"));assertTrue(seen.contains("POST /v1/jobs/draw_example_0/inputs/ref"));assertTrue(seen.contains("GET /v1/jobs/draw_example_0/outputs/out"));assertThrows(BusinessException.class,()->client.status("../other"));}finally{server.stop(0);}
    }
    @Test void disabledConfigurationDoesNotPretendOnline(){var client=new MediaExecutorClient("",false);assertFalse(client.readiness().get("online").getAsBoolean());assertFalse(client.configured());assertThrows(BusinessException.class,()->client.status("draw_test_0"));assertThrows(IllegalArgumentException.class,()->new MediaExecutorClient("https://name:secret@example.invalid",true));}
}
