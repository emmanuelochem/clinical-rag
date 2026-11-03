"""Retrieval evaluation harness.

Compares vector-only, keyword-only (BM25) and hybrid (RRF + rerank) retrieval over the
knowledge base on a gold set of clinical questions, reporting hit@k and MRR.

    python -m app.eval.run                    # uses app/eval/gold.jsonl
    python -m app.eval.run --gold my.jsonl -k 5

Gold format (JSONL): {"question": "...", "expected": ["substring of expected doc title", ...]}
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.providers.rerank import NoopReranker
from app.retrieval.hybrid import HybridRetriever
from app.services import build_services
from app.store.vectors import build_filter

GOLD = Path(__file__).with_name("gold.jsonl")


def _rank(titles: list[str], expected: list[str]) -> int | None:
    for i, t in enumerate(titles, start=1):
        if any(e.lower() in t.lower() for e in expected):
            return i
    return None


async def evaluate(gold_path: Path, k: int) -> dict:
    s = get_settings()
    svc = build_services(s)
    where = build_filter("kb")
    gold = [json.loads(line) for line in gold_path.read_text().splitlines() if line.strip()]
    noop = HybridRetriever(s, svc.store, svc.embedder, NoopReranker())
    results: dict[str, list[int | None]] = {"vector": [], "keyword": [], "hybrid": [], f"hybrid+{svc.reranker.name}": []}
    for g in gold:
        q, exp = g["question"], g["expected"]
        vec = await svc.embedder.embed_query(q)
        results["vector"].append(_rank([r["doc_title"] for r in svc.store.vector_search(vec, k, where)], exp))
        results["keyword"].append(_rank([r["doc_title"] for r in svc.store.keyword_search(q, k, where)], exp))
        results["hybrid"].append(_rank([r.doc_title for r in await noop.search(q, where=where, top_k=k, rerank=False)], exp))
        results[f"hybrid+{svc.reranker.name}"].append(
            _rank([r.doc_title for r in await svc.retriever.search(q, where=where, top_k=k)], exp))
    report = {}
    for name, ranks in results.items():
        n = len(ranks) or 1
        report[name] = {
            "hit@1": round(sum(1 for r in ranks if r == 1) / n, 3),
            f"hit@{k}": round(sum(1 for r in ranks if r) / n, 3),
            "MRR": round(sum(1 / r for r in ranks if r) / n, 3),
        }
    return {"questions": len(gold), "k": k, "results": report}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", type=Path, default=GOLD)
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()
    out = asyncio.run(evaluate(args.gold, args.k))
    print(f"{out['questions']} questions, k={out['k']}\n")
    print(f"{'retriever':<26}{'hit@1':>8}{'hit@' + str(out['k']):>8}{'MRR':>8}")
    for name, m in out["results"].items():
        vals = list(m.values())
        print(f"{name:<26}{vals[0]:>8}{vals[1]:>8}{vals[2]:>8}")


if __name__ == "__main__":
    main()
