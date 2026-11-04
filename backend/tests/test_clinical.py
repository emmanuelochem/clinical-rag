from app.clinical import safety
from app.clinical.catalog import interpret, OBS, resolve_obs
from app.clinical.synthetic import generate


def test_generator_is_deterministic_and_coherent():
    a, b = generate(10, seed=3), generate(10, seed=3)
    assert [p["id"] for p in a["patients"]] == [p["id"] for p in b["patients"]]
    assert any(n["type"] == "ED triage note" for n in a["notes"])
    pids = {p["id"] for p in a["patients"]}
    assert all(o["patient_id"] in pids for o in a["observations"])
    big = generate(60, seed=11)
    assert all(o["value"] > 0 for o in big["observations"])


def test_catalog_resolution_and_flags():
    assert resolve_obs("a1c").code == "4548-4"
    assert resolve_obs("Kidney function").code == "33914-3"
    assert interpret(OBS["2823-3"], 6.4) == "HH"
    assert interpret(OBS["33914-3"], 52) == "L"


def test_news2_scoring():
    s = safety.news2({"9279-1": 26, "59408-5": 89, "8480-6": 102, "8867-4": 112, "8310-5": 37.0})
    assert s["score"] == 3 + 3 + 1 + 2 + 0 and s["risk"] == "high"
    assert safety.news2({"9279-1": 16, "59408-5": 98, "8480-6": 125, "8867-4": 72, "8310-5": 36.8})["risk"] == "low"


def test_rules_engine():
    obs = [{"code": "2823-3", "name": "Potassium", "value": 6.4, "unit": "mmol/L", "category": "lab", "interpretation": "HH", "date": "d"},
           {"code": "33914-3", "name": "eGFR", "value": 25, "unit": "", "category": "lab", "interpretation": "L", "date": "d"}]
    meds = [{"name": "Lisinopril", "status": "active"}, {"name": "Metformin", "status": "active"}]
    out = safety.evaluate(latest_obs=obs, medications=meds, conditions=[{"code": "N18.31", "display": "CKD"}],
                          presentation="weakness, taking ibuprofen, chest pain radiating to left arm")
    titles = {a["title"] for a in out["alerts"]}
    assert "Critical high Potassium" in titles
    assert "Hyperkalaemia on RAAS inhibitor" in titles
    assert "Metformin with eGFR < 30" in titles
    assert "NSAID use with high-risk comorbidity" in titles
    assert "Possible acute coronary syndrome" in titles
    assert out["alerts"][0]["severity"] == "critical"
