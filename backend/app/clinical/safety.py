"""Deterministic clinical safety rules: they never depend on the LLM.

* Critical (panic) lab/vital values
* NEWS2 early-warning score (Royal College of Physicians, 2017) from the latest vitals
* qSOFA sepsis screen (partial: mentation is not captured in structured data)
* Symptom red flags from presenting complaints
* Medication-lab safety checks (e.g. ACE inhibitor + hyperkalaemia, metformin + low eGFR)

These are screening aids for a clinician, not diagnostic conclusions.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class Alert:
    severity: str  # "critical" | "warning" | "info"
    title: str
    detail: str
    rule: str
    evidence: list[str] = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)


def _band(v: float, bands: list[tuple[float, int]], default: int) -> int:
    for upper, score in bands:
        if v <= upper:
            return score
    return default


def news2(vitals: dict[str, float]) -> dict | None:
    """Compute NEWS2 from available vitals (SpO₂ scale 1; assumes room air and 'alert' when unknown)."""
    parts: dict[str, int] = {}
    if (rr := vitals.get("9279-1")) is not None:
        parts["Respiratory rate"] = _band(rr, [(8, 3), (11, 1), (20, 0), (24, 2)], 3)
    if (sp := vitals.get("59408-5")) is not None:
        parts["SpO₂"] = _band(sp, [(91, 3), (93, 2), (95, 1)], 0)
    if (sbp := vitals.get("8480-6")) is not None:
        parts["Systolic BP"] = _band(sbp, [(90, 3), (100, 2), (110, 1), (219, 0)], 3)
    if (hr := vitals.get("8867-4")) is not None:
        parts["Heart rate"] = _band(hr, [(40, 3), (50, 1), (90, 0), (110, 1), (130, 2)], 3)
    if (t := vitals.get("8310-5")) is not None:
        parts["Temperature"] = _band(t, [(35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1)], 2)
    if len(parts) < 3:
        return None
    total = sum(parts.values())
    risk = "high" if total >= 7 else "medium" if total >= 5 else "low-medium" if any(v == 3 for v in parts.values()) else "low"
    return {"score": total, "risk": risk, "components": parts,
            "assumptions": ["Room air (no supplemental O₂ recorded)", "Consciousness assumed Alert (not captured)"]}


SYMPTOM_FLAGS: list[tuple[str, str, str]] = [
    (r"chest (pain|pressure|tightness)", r"radiat|diaphores|sweat|exert|nausea|jaw|left arm",
     "Possible acute coronary syndrome — obtain ECG within 10 minutes and serial troponin"),
    (r"chest pain|pleuritic|short(ness)? of breath|dyspn", r"tachycard|leg swelling|calf|immobil|haemoptysis|hemoptysis|recent surgery",
     "Consider pulmonary embolism — apply a validated pre-test probability score (Wells / PERC)"),
    (r"worst headache|thunderclap|sudden severe headache", r"", "Possible subarachnoid haemorrhage — urgent neuroimaging"),
    (r"facial droop|slurred speech|unilateral weakness|arm weakness|aphasia|hemiparesis", r"",
     "Possible stroke — activate stroke pathway; note last-known-well time"),
    (r"tarry|melena|melaena|hematemesis|haematemesis|vomiting blood|rectal bleeding|black stool", r"",
     "Possible gastrointestinal bleeding — assess haemodynamics, check Hb, review anticoagulants"),
    (r"suicid|self-harm|harm (my|him|her)self", r"", "Suicide/self-harm risk — perform an immediate risk assessment"),
    (r"fever|rigors|chills", r"confus|hypotens|tachypn|low blood pressure|mottled",
     "Possible sepsis — apply sepsis screening and escalation pathway"),
    (r"stiff neck|neck stiffness", r"fever|headache|photophob|rash", "Possible meningitis — urgent evaluation"),
    (r"anaphyla|throat swelling|lip swelling|angioedema", r"", "Possible anaphylaxis/angioedema — airway assessment"),
    (r"syncope|faint|passed out|collapse", r"exert|palpit|chest", "Syncope with cardiac features — ECG and cardiac evaluation"),
]

ACE_ARB = r"lisinopril|enalapril|ramipril|losartan|valsartan|candesartan|sacubitril|irbesartan"
ANTICOAG = r"apixaban|rivaroxaban|warfarin|dabigatran|edoxaban|heparin"
NSAID = r"ibuprofen|naproxen|diclofenac|celecoxib|nsaid|ketorolac"
SGLT2 = r"empagliflozin|dapagliflozin|canagliflozin"


def evaluate(*, latest_obs: list[dict], medications: list[dict], conditions: list[dict], presentation: str = "") -> dict:
    alerts: list[Alert] = []
    obs = {o["code"]: o for o in latest_obs}
    val = {c: o["value"] for c, o in obs.items()}

    # 1. Critical values
    for o in latest_obs:
        if o["interpretation"] in ("HH", "LL"):
            direction = "high" if o["interpretation"] == "HH" else "low"
            alerts.append(Alert("critical", f"Critical {direction} {o['name']}",
                                f"{o['name']} {o['value']} {o['unit']} on {o['date']} is beyond the critical threshold.",
                                "critical-value", [f"{o['name']} {o['value']} {o['unit']} ({o['date']})"]))

    # 2. NEWS2
    vit = {c: v for c, v in val.items() if obs[c]["category"] == "vital"}
    score = news2(vit)
    if score and score["risk"] in ("medium", "high", "low-medium"):
        sev = "critical" if score["risk"] == "high" else "warning"
        alerts.append(Alert(sev, f"NEWS2 {score['score']} ({score['risk']} clinical risk)",
                            "High: emergency assessment by a critical-care-competent team. Medium: urgent review by a clinician."
                            if score["risk"] != "low-medium" else "A single parameter scores 3: urgent ward-based response.",
                            "news2", [f"{k}: +{v}" for k, v in score["components"].items() if v]))

    # 3. qSOFA (partial)
    q = int(val.get("9279-1", 0) >= 22) + int(val.get("8480-6", 999) <= 100)
    if q >= 2 or (q == 1 and re.search(r"confus|altered|drows", presentation, re.I)):
        alerts.append(Alert("critical", "qSOFA positive", "≥2 qSOFA criteria: screen for sepsis and organ dysfunction.",
                            "qsofa", [f"RR {val.get('9279-1')}", f"SBP {val.get('8480-6')}"]))

    # 4. Symptom red flags
    text = presentation.lower()
    for primary, support, msg in SYMPTOM_FLAGS:
        if re.search(primary, text) and (not support or re.search(support, text)):
            title, _, action = msg.partition(" — ")
            alerts.append(Alert("critical" if "Possible" in msg else "warning", title, action[:1].upper() + action[1:] if action else msg, "symptom-red-flag",
                                [m.group(0) for m in re.finditer(primary + (("|" + support) if support else ""), text)][:5]))

    # 5. Medication-lab safety
    meds = " ".join(f"{m['name']}" for m in medications if m.get("status", "active") == "active").lower()
    meds_and_text = meds + " " + text
    conds = " ".join(f"{c['code']} {c['display']}" for c in conditions).lower()
    k, egfr, hb = val.get("2823-3"), val.get("33914-3"), val.get("718-7")
    if k is not None and k >= 5.5 and re.search(ACE_ARB, meds):
        alerts.append(Alert("critical" if k >= 6.0 else "warning", "Hyperkalaemia on RAAS inhibitor",
                            f"Potassium {k} mmol/L while on an ACE inhibitor/ARB/ARNI — review dose and repeat potassium.",
                            "med-lab", [f"K {k}", re.search(ACE_ARB, meds).group(0)]))
    if egfr is not None and "metformin" in meds:
        if egfr < 30:
            alerts.append(Alert("critical", "Metformin with eGFR < 30", "Metformin is contraindicated at eGFR < 30 mL/min/1.73m².",
                                "med-lab", [f"eGFR {egfr}"]))
        elif egfr < 45:
            alerts.append(Alert("warning", "Metformin dose review (eGFR 30–44)",
                                "Do not initiate; if already on metformin, assess benefit/risk and consider dose reduction.", "med-lab", [f"eGFR {egfr}"]))
    if re.search(NSAID, meds_and_text) and (egfr is not None and egfr < 60 or "n18" in conds or "i50" in conds or re.search(ANTICOAG, meds)):
        alerts.append(Alert("warning", "NSAID use with high-risk comorbidity",
                            "NSAIDs worsen renal function and heart failure and raise bleeding risk with anticoagulants.",
                            "med-lab", [re.search(NSAID, meds_and_text).group(0)]))
    if re.search(ANTICOAG, meds) and ((hb is not None and hb < 10) or re.search(r"tarry|melena|bleed|hematemesis", text)):
        alerts.append(Alert("critical", "Bleeding risk on anticoagulant",
                            "Low haemoglobin or bleeding symptoms in a patient on anticoagulation.", "med-lab",
                            [x for x in [f"Hb {hb}" if hb is not None else "", re.search(ANTICOAG, meds).group(0)] if x]))
    if re.search(SGLT2, meds) and re.search(r"vomit|nausea|abdominal pain|unwell|dehydrat", text):
        alerts.append(Alert("warning", "SGLT2 inhibitor in acute illness",
                            "Risk of euglycaemic DKA — check ketones; consider sick-day hold.", "med-lab", [re.search(SGLT2, meds).group(0)]))

    order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: order[a.severity])
    return {"alerts": [a.dict() for a in alerts], "news2": score}
