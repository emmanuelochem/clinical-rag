import json

import httpx
import numpy as np
import pytest

from app.config import Settings
from app.models import Chunk
from app.providers import llm as llm_mod
from app.providers.embeddings import LocalEmbedder
from app.providers.llm import LLMError, OpenAICompatLLM, ThinkFilter
from app.store.vectors import EmbeddingMismatch, VectorStore


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _sleep(_):
        return None
    monkeypatch.setattr(llm_mod.asyncio, "sleep", _sleep)


def test_presets_and_key_aliases(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GEMINI_API_KEY", "gem_test")
    g = Settings(data_dir=tmp_path, _env_file=None)
    assert g.llm_provider == "groq" and g.llm_base_url == "https://api.groq.com/openai/v1"
    assert g.chat_model == "openai/gpt-oss-120b" and g.planner == "openai/gpt-oss-20b" and g.api_key == "gsk_test"
    m = Settings(data_dir=tmp_path, llm_provider="gemini", chat_model="gemini-x", _env_file=None)
    assert m.llm_base_url.endswith("/v1beta/openai") and m.chat_model == "gemini-x" and m.api_key == "gem_test"
    assert m.embed_id == "local:BAAI/bge-small-en-v1.5" and m.embed_query_prefix.startswith("Represent")
    o = Settings(data_dir=tmp_path, llm_provider="ollama", embed_provider="ollama", _env_file=None)
    assert o.llm_base_url == "http://localhost:11434" and o.embed_query_prefix == "search_query: "
    c = Settings(data_dir=tmp_path, embed_model="BAAI/bge-base-en-v1.5", _env_file=None)
    assert c.embed_query_prefix == "" and c.embed_doc_prefix == ""


def make_llm(handler, tmp_path, **kw) -> tuple[OpenAICompatLLM, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(req: httpx.Request):
        seen.append(req)
        return handler(req, len(seen))

    s = Settings(data_dir=tmp_path, groq_api_key="gsk_x", _env_file=None, **kw)
    client = httpx.AsyncClient(base_url=s.llm_base_url + "/", transport=httpx.MockTransport(wrapped),
                               headers={"Authorization": f"Bearer {s.api_key}"})
    return OpenAICompatLLM(s, client=client), seen


def sse(*pieces: str) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in pieces]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


async def test_stream_parses_sse_and_strips_reasoning(tmp_path):
    llm, seen = make_llm(lambda r, n: httpx.Response(200, content=sse("Hel", "lo <thi", "nk>hidden</think>", " world [1]")), tmp_path)
    out = "".join([p async for p in llm.stream([{"role": "user", "content": "hi"}])])
    assert out == "Hello  world [1]"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/openai/v1/chat/completions" and body["stream"] is True
    assert body["model"] == "openai/gpt-oss-120b" and seen[0].headers["authorization"] == "Bearer gsk_x"


def chat_resp(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


async def test_retries_rate_limit_then_succeeds(tmp_path):
    def h(r, n):
        return httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "slow down"}}) if n < 3 else chat_resp("ok")
    llm, seen = make_llm(h, tmp_path)
    assert await llm.complete([{"role": "user", "content": "x"}]) == "ok" and len(seen) == 3


async def test_rate_limit_exhausted_gives_clear_error(tmp_path):
    llm, seen = make_llm(lambda r, n: httpx.Response(429, json={"error": {"message": "TPD exceeded"}}), tmp_path, max_retries=2)
    with pytest.raises(LLMError, match="rate limit.*TPD exceeded"):
        await llm.complete([{"role": "user", "content": "x"}])
    assert len(seen) == 3


async def test_bad_key_and_missing_model_errors(tmp_path):
    llm, _ = make_llm(lambda r, n: httpx.Response(401, json={"error": {"message": "Invalid API Key"}}), tmp_path)
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        await llm.complete([{"role": "user", "content": "x"}])
    llm, _ = make_llm(lambda r, n: httpx.Response(404, json={"error": {"message": "model does not exist"}}), tmp_path)
    with pytest.raises(LLMError, match="openai/gpt-oss-120b.*not found"):
        await llm.complete([{"role": "user", "content": "x"}])


async def test_json_mode_fallback_and_repair(tmp_path):
    def h(r, n):
        body = json.loads(r.content)
        if n == 1:
            assert body["response_format"] == {"type": "json_object"}
            return httpx.Response(400, json={"error": {"message": "json mode not supported"}})
        assert "response_format" not in body
        return chat_resp("Sure! ```json\n{\"sufficient\": true}\n```")
    llm, seen = make_llm(h, tmp_path)
    assert await llm.complete_json([{"role": "user", "content": "JSON please"}]) == {"sufficient": True}

    replies = iter(["not json at all", '{"ok": 1}'])
    llm, seen = make_llm(lambda r, n: chat_resp(next(replies)), tmp_path)
    assert await llm.complete_json([{"role": "user", "content": "JSON"}]) == {"ok": 1}
    assert "not valid JSON" in json.loads(seen[1].content)["messages"][-1]["content"]


async def test_list_models_strips_gemini_prefix(tmp_path):
    llm, _ = make_llm(lambda r, n: httpx.Response(200, json={"data": [{"id": "models/gemini-flash-latest"}, {"id": "b"}]}), tmp_path)
    assert await llm.list_models() == ["b", "gemini-flash-latest"]


def test_think_filter_edge_cases():
    def run(chunks):
        f = ThinkFilter()
        return "".join(f(c) for c in chunks) + f.flush()
    assert run(["a<th", "ink>x</thi", "nk>b"]) == "ab"
    assert run(["5 < 6 <b>"]) == "5 < 6 <b>"
    assert run(["trailing <"]) == "trailing <"
    assert run(["<think>never closed"]) == ""


async def test_local_embedder_applies_prefixes(tmp_path):
    calls = []

    class FakeModel:
        def embed(self, texts, batch_size):
            calls.append(list(texts))
            return [np.ones(4, dtype=np.float32) * len(t) for t in texts]

    s = Settings(data_dir=tmp_path, _env_file=None)
    e = LocalEmbedder(s, model=FakeModel())
    q = await e.embed_query("chest pain")
    d = await e.embed_documents(["a", "bb"])
    assert calls[0][0].startswith("Represent this sentence") and calls[1] == ["a", "bb"]
    assert isinstance(q[0], float) and len(d) == 2 and await e.dimension() == 4


def test_vector_store_refuses_mixed_embedding_models(tmp_path):
    c = Chunk(id="c1", doc_id="d", ordinal=0, text="hello")
    a = VectorStore(tmp_path / "ldb", embed_id="local:model-a")
    a.add([c], [[0.1, 0.2, 0.3]], doc_title="t", source="s", scope="kb")
    assert VectorStore(tmp_path / "ldb", embed_id="local:model-a").mismatch is None
    b = VectorStore(tmp_path / "ldb", embed_id="ollama:nomic-embed-text")
    assert "Re-index" in b.mismatch
    with pytest.raises(EmbeddingMismatch):
        b.vector_search([0.1, 0.2, 0.3], 3, None)
    with pytest.raises(EmbeddingMismatch, match="does not match"):
        a.add([c], [[0.1, 0.2]], doc_title="t", source="s", scope="kb")
