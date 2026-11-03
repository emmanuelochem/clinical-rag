"""Seed the database: synthetic patients, their indexed notes, and the bundled reference library.

    python -m app.seed                     # 30 synthetic patients + bundled knowledge base
    python -m app.seed --patients 60 --reset
    python -m app.seed --medlineplus mplus_topics_2026-11-01.xml   # add MedlinePlus topics
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
from pathlib import Path

from app.clinical.synthetic import generate
from app.config import get_settings
from app.ingest.parsers import parse_bytes
from app.ingest.pipeline import doc_id_for, parse_medlineplus_xml
from app.services import Services, build_services

log = logging.getLogger("seed")
KB_DIR = Path(__file__).resolve().parent.parent / "knowledge"
TABLES = ["patients", "encounters", "conditions", "observations", "medications", "allergies", "notes"]

# MedlinePlus topics relevant to the synthetic cohort's conditions and acute presentations.
MEDLINEPLUS_TOPICS = {
    "Diabetes Type 2", "High Blood Pressure", "Chronic Kidney Disease", "Heart Failure", "Atrial Fibrillation",
    "COPD", "Asthma", "Hypothyroidism", "Anemia", "Iron", "Cholesterol", "Heart Attack", "Chest Pain", "Pneumonia",
    "Sepsis", "Pulmonary Embolism", "Stroke", "Gastrointestinal Bleeding", "Potassium", "Hyperglycemia",
    "Depression", "GERD", "Obesity", "Shortness of Breath", "Fatigue", "Dizziness and Vertigo", "Fever", "Headache",
}


def load_patients(svc: Services, n: int, seed: int, reset: bool) -> dict[str, int]:
    existing = svc.db.one("SELECT COUNT(*) AS n FROM patients")["n"]
    if existing and not reset:
        log.info("Patients already present (%d); use --reset to regenerate", existing)
        return {}
    with svc.db.tx() as c:
        for t in reversed(TABLES):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM documents WHERE scope = 'patient'")
    data = generate(n, seed)
    for t in TABLES:
        svc.db.insert_many(t, data[t])
    return {t: len(data[t]) for t in TABLES}


async def ingest_bundled_kb(svc: Services) -> int:
    n = 0
    for path in sorted(KB_DIR.glob("**/*")):
        if path.is_dir() or path.suffix.lower() not in (".md", ".pdf", ".html", ".docx", ".txt"):
            continue
        data = path.read_bytes()
        did = doc_id_for(data, path.name)
        if svc.db.one("SELECT 1 FROM documents WHERE id = ? AND status = 'ready'", (did,)):
            continue
        doc = parse_bytes(data, path.name)
        svc.ingestor.register(did, title=doc.title, source=f"bundled:{path.name}", mime=doc.mime, size=len(data))
        await svc.ingestor.ingest_file(did, data, path.name)
        n += 1
    return n


async def ingest_medlineplus(svc: Services, xml_path: Path, all_topics: bool) -> int:
    docs = parse_medlineplus_xml(xml_path.read_bytes(), None if all_topics else MEDLINEPLUS_TOPICS)
    for doc in docs:
        did = doc_id_for(doc.source.encode(), "medlineplus")
        svc.ingestor.register(did, title=doc.title, source=doc.source, mime="text/html", size=sum(len(b.text) for b in doc.blocks))
        svc.ingestor._status(did, "processing")
        n = await svc.ingestor.index_parsed(doc, did)
        svc.ingestor._status(did, "ready", num_chunks=n)
    svc.store.refresh_fts()
    return len(docs)


async def seed(svc: Services, patients: int = 30, rng_seed: int = 42, reset: bool = False) -> dict:
    counts = load_patients(svc, patients, rng_seed, reset)
    chunks = 0
    if counts:
        if reset:
            for row in svc.db.query("SELECT id FROM notes"):
                svc.store.delete_doc(row["id"])
        chunks = await svc.ingestor.index_patient_notes()
    kb = await ingest_bundled_kb(svc)
    return {"records": counts, "note_chunks": chunks, "kb_documents_added": kb}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patients", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true", help="wipe and regenerate synthetic patients")
    ap.add_argument("--wipe-all", action="store_true", help="delete the entire data directory first")
    ap.add_argument("--medlineplus", type=Path, help="path to a MedlinePlus health topics XML file")
    ap.add_argument("--all-topics", action="store_true", help="with --medlineplus, ingest every English topic")
    args = ap.parse_args()
    s = get_settings()
    if args.wipe_all and s.data_dir.exists():
        shutil.rmtree(s.data_dir)
        get_settings.cache_clear()
        s = get_settings()
    svc = build_services(s)

    async def go():
        print(await seed(svc, args.patients, args.seed, args.reset or args.wipe_all))
        if args.medlineplus:
            print("MedlinePlus topics ingested:", await ingest_medlineplus(svc, args.medlineplus, args.all_topics))

    asyncio.run(go())


if __name__ == "__main__":
    main()
