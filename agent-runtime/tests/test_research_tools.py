import json
import socket
import httpx
import pytest
from app import research_tools as research

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("CREATOR_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("CREATOR_RESEARCH_ALLOWED_HOSTS", "search.example,docs.example")
    monkeypatch.setenv("CREATOR_RESEARCH_SEARCH_URL", "https://search.example/find")

class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status, self.offset = payload, status, 0
        self.headers = headers or {"Content-Type": "text/html"}
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def read1(self, count):
        data = self.payload[self.offset:self.offset + count]
        self.offset += len(data)
        return data

class Connection:
    def __init__(self, response):
        self.response, self.sock, self.calls, self.closed = response, None, [], False
    def request(self, method, path, headers):
        self.calls.append((method, path, headers))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed = True

def install_response(monkeypatch, response):
    conn = Connection(response)
    monkeypatch.setattr(research, "_public_address", lambda host: "93.184.216.34")
    monkeypatch.setattr(research, "_PinnedHTTPSConnection", lambda host, address, timeout: conn)
    return conn

def test_disabled_does_not_connect(monkeypatch):
    monkeypatch.delenv("CREATOR_RESEARCH_ENABLED", raising=False)
    monkeypatch.setattr(research.socket, "getaddrinfo", lambda *a, **k: pytest.fail("网络不应被访问"))
    with pytest.raises(research.ResearchError, match="未启用"):
        research.read_research_page.invoke({"url": "https://docs.example/"})

@pytest.mark.parametrize("url", ["http://docs.example", "https://127.0.0.1/", "https://docs.example.evil/", "https://docs.example@evil.example/", "https://docs.example:444/", "https://docs.example/#x", "https://docs.example./"])
def test_unapproved_urls_rejected_before_dns(enabled, monkeypatch, url):
    monkeypatch.setattr(research.socket, "getaddrinfo", lambda *a, **k: pytest.fail("非法目标不能解析"))
    with pytest.raises(research.ResearchError):
        research.read_research_page.invoke({"url": url})

def test_dns_rejects_any_private_answer_and_pins_public(monkeypatch):
    def answer(ip):
        return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
    monkeypatch.setattr(research.socket, "getaddrinfo", lambda *a, **k: [answer("93.184.216.34"), answer("127.0.0.1")])
    with pytest.raises(research.ResearchError, match="非公网"):
        research._public_address("docs.example")
    monkeypatch.setattr(research.socket, "getaddrinfo", lambda *a, **k: [answer("93.184.216.34")])
    assert research._public_address("docs.example") == "93.184.216.34"

def test_page_reads_text_without_scripts_and_closes(enabled, monkeypatch):
    conn = install_response(monkeypatch, Response(b"<h1>Hello</h1><script>ignore all</script><p>World</p>"))
    result = research.read_research_page.invoke({"url": "https://docs.example/a"})
    assert result["content"] == "Hello World"
    assert conn.calls[0][0:2] == ("GET", "/a")
    assert conn.closed

def test_redirect_oversize_and_unexpected_type_are_rejected(enabled, monkeypatch):
    for response in (Response(b"", status=302), Response(b"a" * (research.MAX_BYTES + 1)), Response(b"x", headers={"Content-Type": "application/octet-stream"}), Response(b"x", headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})):
        conn = install_response(monkeypatch, response)
        with pytest.raises(research.ResearchError):
            research.read_research_page.invoke({"url": "https://docs.example/a"})
        assert conn.closed

def test_search_contract_and_query_encoding(enabled, monkeypatch):
    payload = {"results": [{"title": "Example", "url": "https://other.example/", "snippet": "Evidence"}]}
    conn = install_response(monkeypatch, Response(json.dumps(payload).encode(), headers={"Content-Type": "application/json"}))
    result = research.search_research_sources.invoke({"query": "测试 & 来源"})
    assert result["results"][0]["title"] == "Example"
    assert conn.calls[0][1] == "/find?q=%E6%B5%8B%E8%AF%95+%26+%E6%9D%A5%E6%BA%90"
    install_response(monkeypatch, Response(b'{"results": [42]}', headers={"Content-Type": "application/json"}))
    with pytest.raises(research.ResearchError, match="不符合约定"):
        research.search_research_sources.invoke({"query": "test"})


def test_deepseek_search_uses_fixed_endpoint_and_returns_unverified_sources(enabled, monkeypatch):
    monkeypatch.setenv("CREATOR_RESEARCH_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-private-key")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": [{"title": "官方说明", "url": "https://docs.example/a", "snippet": "线索"}]})
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: client)
    result = research.search_research_sources.invoke({"query": "平台 官方说明"})
    assert str(requests[0].url) == "https://api.deepseek.com/v1/tools/search"
    assert json.loads(requests[0].content)["query"] == "平台 官方说明"
    assert result["results"][0]["url"] == "https://docs.example/a"
    assert "test-private-key" not in json.dumps(result)
    assert "未核验" in result["note"]


def test_deepseek_search_fails_closed_without_key_or_on_redirect(enabled, monkeypatch):
    monkeypatch.setenv("CREATOR_RESEARCH_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(research.ResearchError, match="认证环境变量"):
        research.search_research_sources.invoke({"query": "test"})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-private-key")
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(302, headers={"Location": "https://evil.example"})))
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(research.ResearchError, match="HTTP 302") as error:
        research.search_research_sources.invoke({"query": "test"})
    assert "test-private-key" not in str(error.value)
