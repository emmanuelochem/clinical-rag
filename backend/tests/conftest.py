import hashlib
import math
import re

import pytest

from app.config import Settings
from app.services import build_services


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder: lexical overlap ≈ cosine similarity."""

    dim = 256

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    async def embed_query(self, text):
        return self._vec(text)

    async def dimension(self):
        return self.dim


class FakeLLM:
    def __init__(self):
        self.calls: list[str] = []

    async def stream(self, messages, *, model=None):
        self.calls.append("stream")
        for piece in ["The record shows ", "rising values [1]", " and reference guidance [2]."]:
            yield piece

    async def complete(self, messages, *, model=None, **kw):
        return "ok"

    async def complete_json(self, messages, *, model=None):
        prompt = messages[-1]["content"]
        if "planning retrieval" in prompt:
            self.calls.append("plan")
            return {"standalone_question": "What is the HbA1c trend?", "note_queries": ["diabetes control"],
                    "kb_queries": ["HbA1c targets type 2 diabetes"], "lab_tests": ["HbA1c"], "chart": True}
        if "sufficient" in prompt:
            self.calls.append("reflect")
            return {"sufficient": True}
        if "differential diagnosis" in prompt:
            self.calls.append("differential")
            return {"summary": "Synthesis.", "differentials": [
                {"condition": "Acute coronary syndrome", "icd10": "I24.9", "likelihood": "high", "cant_miss": True,
                 "reasoning": "Troponin elevated.", "supporting": [{"finding": "Troponin high", "source": 1},
                                                                    {"finding": "bogus", "source": 999}],
                 "against": [], "next_steps": ["Serial ECG"]},
                {"condition": "GERD", "likelihood": "low", "supporting": [], "against": [{"finding": "x", "source": None}]},
            ], "recommended_workup": ["ECG"], "information_gaps": ["ECG findings"]}
        return {}


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, reranker="none", neighbor_expansion=1, chunk_tokens=120, chunk_overlap_tokens=20)


@pytest.fixture
def services(settings):
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    return build_services(settings, embedder=HashEmbedder(), llm=FakeLLM())


@pytest.fixture
async def seeded(services):
    from app.seed import seed

    await seed(services, patients=12, rng_seed=7)
    return services
