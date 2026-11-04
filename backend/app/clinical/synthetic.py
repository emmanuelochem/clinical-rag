"""Deterministic synthetic patient generator.

Produces clinically coherent (but entirely fictional) longitudinal records: chronic
conditions drive lab/vital trajectories over ~3 years, medications start and bend
those trajectories, and some patients end with an acute presentation (ED visit) to
exercise the differential-diagnosis workflow. All names and identifiers are fake.
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.clinical.catalog import OBS, interpret

FIRST_F = ["Maria", "Aisha", "Elena", "Grace", "Priya", "Sofia", "Hannah", "Mei", "Fatima", "Olivia", "Rosa", "Nora", "Leila", "Ingrid", "Chloe"]
FIRST_M = ["James", "Omar", "Daniel", "Hiroshi", "Carlos", "Samuel", "Arjun", "Lucas", "Kwame", "Peter", "Ivan", "Mateo", "Ethan", "Yusuf", "Noah"]
LAST = ["Alvarez", "Bennett", "Chen", "Diallo", "Eriksen", "Fischer", "Garcia", "Haddad", "Ito", "Johansson", "Kowalski",
        "Lopez", "Mensah", "Novak", "Okafor", "Patel", "Quinn", "Rossi", "Sato", "Thompson", "Usman", "Varga", "Williams", "Yilmaz", "Zhang"]
PROVIDERS = ["Dr. A. Rivera (Internal Medicine)", "Dr. K. Osei (Family Medicine)", "Dr. L. Brandt (Internal Medicine)", "Dr. S. Nakamura (Family Medicine)"]


@dataclass
class Traj:
    """Lab trajectory: start value, linear drift per year, noise SD; optional treatment
    target the value approaches exponentially after the condition's medication starts."""
    start: float
    slope: float = 0.0
    noise: float = 0.0
    tx_target: float | None = None
    tx_rate: float = 2.5  # per year


@dataclass
class Profile:
    key: str
    code: str
    display: str
    trajs: dict[str, Traj]
    meds: list[tuple[str, str, str]]  # (name, dose, frequency)
    second_line: tuple[str, str, str] | None = None
    complaints: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)


PROFILES: dict[str, Profile] = {p.key: p for p in [
    Profile("t2dm", "E11.9", "Type 2 diabetes mellitus without complications",
            {"4548-4": Traj(7.6, 0.25, 0.25, 7.0, 1.5)}, [("Metformin", "1000 mg", "twice daily")],
            ("Empagliflozin", "10 mg", "once daily"), ["polyuria", "fatigue"],
            ["Reinforce dietary counselling and 150 min/week activity", "Annual retinal exam and foot exam", "Repeat HbA1c in 3 months"]),
    Profile("htn", "I10", "Essential (primary) hypertension",
            {"8480-6": Traj(152, 1.5, 7, 132, 3.0), "8462-4": Traj(94, 0.5, 5, 82, 3.0)},
            [("Lisinopril", "10 mg", "once daily")], ("Amlodipine", "5 mg", "once daily"), ["occasional headaches"],
            ["Home BP monitoring, target <130/80", "Limit sodium intake to <2 g/day"]),
    Profile("ckd", "N18.31", "Chronic kidney disease, stage 3a",
            {"33914-3": Traj(54, -4.5, 2.5), "14959-1": Traj(110, 25, 15), "2823-3": Traj(4.9, 0.1, 0.2)},
            [], None, ["mild ankle swelling"],
            ["Avoid NSAIDs and nephrotoxins", "Monitor potassium on ACE inhibitor", "Nephrology referral if eGFR <45 or UACR rising"]),
    Profile("hf", "I50.22", "Chronic systolic (congestive) heart failure",
            {"30934-4": Traj(520, 40, 90, 260, 2.0), "29463-7": Traj(0, 0, 0.8)},
            [("Carvedilol", "12.5 mg", "twice daily"), ("Furosemide", "40 mg", "once daily")],
            ("Sacubitril/valsartan", "49/51 mg", "twice daily"), ["exertional dyspnea", "orthopnea"],
            ["Daily weights; call if gain >2 kg in 3 days", "Fluid restriction 1.5-2 L/day", "Echocardiogram follow-up"]),
    Profile("hld", "E78.5", "Hyperlipidemia, unspecified",
            {"13457-7": Traj(168, 2, 10, 92, 3.0), "2093-3": Traj(248, 2, 12, 175, 3.0), "2571-8": Traj(190, 3, 25, 140, 2.0)},
            [("Atorvastatin", "40 mg", "once daily at night")], None, [], ["Recheck lipid panel in 6-12 weeks after statin change"]),
    Profile("hypothyroid", "E03.9", "Hypothyroidism, unspecified",
            {"3016-3": Traj(8.8, 0.3, 0.8, 2.2, 3.0)}, [("Levothyroxine", "75 mcg", "once daily before breakfast")], None,
            ["fatigue", "cold intolerance", "weight gain"], ["Recheck TSH 6-8 weeks after dose change"]),
    Profile("ida", "D50.9", "Iron deficiency anemia, unspecified",
            {"718-7": Traj(10.1, -0.2, 0.3, 12.9, 2.5), "2276-4": Traj(9, 0, 2, 60, 2.0), "787-2": Traj(74, 0, 1.5, 86, 2.0)},
            [("Ferrous sulfate", "325 mg", "once daily")], None, ["fatigue", "exertional dyspnea"],
            ["Evaluate source of iron loss (GI evaluation if indicated)", "Repeat CBC and ferritin in 8 weeks"]),
    Profile("asthma", "J45.40", "Moderate persistent asthma, uncomplicated", {},
            [("Fluticasone/salmeterol", "250/50 mcg", "1 inhalation twice daily"), ("Albuterol HFA", "90 mcg", "2 puffs q4-6h PRN")],
            None, ["intermittent wheeze", "night-time cough"], ["Review inhaler technique", "Asthma action plan updated"]),
    Profile("copd", "J44.9", "Chronic obstructive pulmonary disease, unspecified",
            {"59408-5": Traj(94, -0.4, 0.8), "9279-1": Traj(19, 0.3, 1.5)},
            [("Tiotropium", "18 mcg", "inhaled once daily"), ("Albuterol HFA", "90 mcg", "2 puffs q4-6h PRN")],
            None, ["chronic productive cough", "exertional dyspnea"], ["Smoking cessation counselling", "Pulmonary rehabilitation referral"]),
    Profile("afib", "I48.91", "Atrial fibrillation, unspecified",
            {"8867-4": Traj(102, 0, 9, 78, 4.0)}, [("Apixaban", "5 mg", "twice daily"), ("Metoprolol succinate", "50 mg", "once daily")],
            None, ["palpitations"], ["Continue anticoagulation (CHA₂DS₂-VASc reviewed)", "Rate control target <110 bpm at rest"]),
    Profile("obesity", "E66.9", "Obesity, unspecified", {}, [], None, [], ["Nutrition referral", "Weight-loss goal 5-10% over 6 months"]),
    Profile("depression", "F32.A", "Depression, unspecified", {}, [("Sertraline", "50 mg", "once daily")], None,
            ["low mood", "poor sleep"], ["PHQ-9 reassessment at follow-up", "Psychotherapy referral offered"]),
    Profile("gerd", "K21.9", "Gastro-esophageal reflux disease without esophagitis", {}, [("Omeprazole", "20 mg", "once daily")],
            None, ["heartburn"], ["Avoid late meals; elevate head of bed"]),
]}

# Typical comorbidity bundles so records look realistic.
BUNDLES = [
    ["t2dm", "htn", "hld", "obesity"], ["t2dm", "ckd", "htn"], ["hf", "afib", "htn"], ["hf", "ckd", "t2dm"],
    ["copd", "hf"], ["copd", "depression"], ["asthma", "gerd"], ["hypothyroid", "hld"], ["ida", "gerd"],
    ["ida", "hypothyroid"], ["htn", "hld"], ["depression", "obesity", "t2dm"], ["afib", "htn", "hld"], ["ckd", "htn", "gerd"],
]

# Acute presentations: final ED encounter with abnormal values and a triage note.
ACUTE = {
    "acs": dict(reason="Chest pain", complaint="substernal chest pressure radiating to the left arm for 2 hours with diaphoresis and nausea",
                obs={"10839-9": 0.82, "8867-4": 104, "8480-6": 164, "8462-4": 96, "59408-5": 96, "9279-1": 20}),
    "hf_exac": dict(reason="Shortness of breath", complaint="worsening shortness of breath over 5 days, 3-pillow orthopnea, bilateral leg swelling and 4 kg weight gain",
                     obs={"30934-4": 1480, "59408-5": 89, "9279-1": 26, "8867-4": 112, "2160-0": None}),
    "pneumonia": dict(reason="Fever and cough", complaint="fever, productive cough with rust-colored sputum and right-sided pleuritic chest pain for 3 days",
                      obs={"8310-5": 38.9, "6690-2": 16.8, "1988-5": 142, "59408-5": 91, "9279-1": 24, "8867-4": 108}),
    "hyperglycemia": dict(reason="Hyperglycemia", complaint="excessive thirst, frequent urination, blurred vision and fatigue for 1 week",
                          obs={"2345-7": 418, "2951-2": 131, "8867-4": 98}),
    "hyperkalemia": dict(reason="Weakness", complaint="generalized muscle weakness and palpitations for 2 days; recently started ibuprofen for knee pain",
                         obs={"2823-3": 6.4, "33914-3": None, "8867-4": 54}),
    "anemia_sx": dict(reason="Fatigue and dizziness", complaint="progressive fatigue, light-headedness on standing and dark tarry stools for one week",
                      obs={"718-7": 7.6, "787-2": 71, "8867-4": 112, "8480-6": 102, "8462-4": 62}),
}
ACUTE_FIT = {"acs": ["htn", "hld", "t2dm"], "hf_exac": ["hf"], "pneumonia": ["copd", "asthma"],
             "hyperglycemia": ["t2dm"], "hyperkalemia": ["ckd"], "anemia_sx": ["ida", "gerd"]}

NORMAL_BASE = {  # mean, sd for values not driven by a condition
    "4548-4": (5.3, 0.2), "2345-7": (90, 6), "2160-0": (0.95, 0.12), "33914-3": (92, 8), "14959-1": (12, 5),
    "2823-3": (4.2, 0.3), "2951-2": (140, 2), "2093-3": (182, 15), "13457-7": (98, 14), "2085-9": (52, 8),
    "2571-8": (120, 25), "718-7": (14.0, 0.9), "6690-2": (7.0, 1.3), "777-3": (260, 45), "787-2": (89, 3),
    "2276-4": (110, 40), "30934-4": (45, 15), "10839-9": (0.01, 0.005), "1988-5": (2.5, 1.5), "3016-3": (1.8, 0.6),
    "1742-6": (25, 8), "1920-8": (24, 6), "8480-6": (122, 7), "8462-4": (76, 5), "8867-4": (74, 7),
    "9279-1": (15, 1.5), "59408-5": (98, 0.8), "8310-5": (36.7, 0.2),
}
ROUTINE_LABS = ["4548-4", "2345-7", "2160-0", "33914-3", "2823-3", "2951-2", "718-7", "6690-2", "777-3", "787-2",
                "2093-3", "13457-7", "2085-9", "2571-8", "1742-6", "1920-8", "3016-3"]
VITALS = ["8480-6", "8462-4", "8867-4", "9279-1", "59408-5", "8310-5", "29463-7", "39156-5"]


def _id() -> str:
    return uuid.UUID(int=_rng.getrandbits(128)).hex[:16]


_rng = random.Random(0)


def _clamp(code: str, v: float) -> float:
    # Physiological floor: noise must never produce zero/negative results (e.g. ALT 0 U/L).
    floor = NORMAL_BASE[code][0] * 0.3 if code in NORMAL_BASE else 0.0
    lo, hi = {"59408-5": (70, 100), "33914-3": (5, 130), "4548-4": (4.0, 15), "8310-5": (34, 42)}.get(code, (floor, 1e9))
    return max(lo, min(hi, v))


def generate(n_patients: int = 30, seed: int = 42, today: date | None = None) -> dict[str, list[dict]]:
    global _rng
    _rng = rng = random.Random(seed)
    today = today or date.today()
    out: dict[str, list[dict]] = {k: [] for k in ["patients", "encounters", "conditions", "observations", "medications", "allergies", "notes"]}
    acute_keys = list(ACUTE)

    for i in range(n_patients):
        sex = rng.choice(["female", "male"])
        first = rng.choice(FIRST_F if sex == "female" else FIRST_M)
        last = rng.choice(LAST)
        age = rng.randint(38, 86)
        birth = today - timedelta(days=age * 365 + rng.randint(0, 364))
        pid = _id()
        provider = rng.choice(PROVIDERS)
        out["patients"].append(dict(
            id=pid, mrn=f"SYN-{100000 + i * 37:06d}", first_name=first, last_name=last, sex=sex,
            birth_date=birth.isoformat(), blood_type=rng.choice(["A+", "O+", "B+", "AB+", "A-", "O-"]),
            phone=f"555-01{rng.randint(10, 99)}", address=f"{rng.randint(10, 999)} Example St, Springfield",
            primary_provider=provider, synthetic=1,
        ))
        conds = list(rng.choice(BUNDLES)) if i % 9 != 8 else []  # a few healthy patients
        height_m = rng.gauss(1.63 if sex == "female" else 1.77, 0.06)
        bmi0 = rng.gauss(33 if "obesity" in conds else 26.5, 2.5)
        weight0 = bmi0 * height_m ** 2

        start = today - timedelta(days=rng.randint(900, 1150))
        onset = {c: start - timedelta(days=rng.randint(30, 1500)) for c in conds}
        # Medication start: some treated from the beginning, others started mid-way (shows trajectory bend).
        tx_start = {c: (start + timedelta(days=rng.randint(120, 500))) if rng.random() < 0.55 else onset[c] for c in conds}
        escalate = {c: start + timedelta(days=rng.randint(500, 800)) for c in conds if PROFILES[c].second_line and rng.random() < 0.5}

        for c in conds:
            p = PROFILES[c]
            out["conditions"].append(dict(id=_id(), patient_id=pid, code=p.code, display=p.display,
                                          onset_date=onset[c].isoformat(), abatement_date=None, status="active"))
            for name, dose, freq in p.meds:
                out["medications"].append(dict(id=_id(), patient_id=pid, name=name, dose=dose, frequency=freq,
                                               start_date=tx_start[c].isoformat(), end_date=None, status="active", indication=p.display))
            if c in escalate:
                name, dose, freq = p.second_line
                out["medications"].append(dict(id=_id(), patient_id=pid, name=name, dose=dose, frequency=freq,
                                               start_date=escalate[c].isoformat(), end_date=None, status="active", indication=p.display))
        if rng.random() < 0.4:
            sub, rx, sev = rng.choice([("Penicillin", "Urticaria", "moderate"), ("Sulfonamides", "Rash", "mild"),
                                       ("Codeine", "Nausea/vomiting", "mild"), ("Iodinated contrast", "Anaphylaxis", "severe"),
                                       ("Peanuts", "Angioedema", "severe")])
            out["allergies"].append(dict(id=_id(), patient_id=pid, substance=sub, reaction=rx, severity=sev))

        # Encounter schedule: every ~3-5 months.
        visit_dates, d = [], start
        while d < today - timedelta(days=20):
            visit_dates.append(d)
            d += timedelta(days=rng.randint(90, 160) if conds else rng.randint(300, 420))

        acute = None
        fits = [k for k in acute_keys if any(c in conds for c in ACUTE_FIT[k])]
        if fits and rng.random() < 0.45:
            acute = rng.choice(fits)
        elif i < len(acute_keys) and fits:
            acute = fits[0]

        def value(code: str, when: date) -> float:
            t = (when - start).days / 365.25
            base_mean, base_sd = NORMAL_BASE.get(code, (0, 0))
            v = rng.gauss(base_mean, base_sd)
            for c in conds:
                tr = PROFILES[c].trajs.get(code)
                if tr is None:
                    continue
                if code == "29463-7":
                    continue
                v = tr.start + tr.slope * t + rng.gauss(0, tr.noise)
                if tr.tx_target is not None and when >= tx_start[c]:
                    dt = (when - max(tx_start[c], start)).days / 365.25
                    frac = 1 - math.exp(-tr.tx_rate * dt) if tx_start[c] > start else 1.0
                    untreated = v
                    v = untreated + (tr.tx_target + rng.gauss(0, tr.noise) - untreated) * frac
                    if c in escalate and when >= escalate[c]:
                        v -= (v - tr.tx_target) * 0.3
            return _clamp(code, v)

        weight = weight0
        for vi, vd in enumerate(visit_dates):
            eid = _id()
            is_annual = vi % 3 == 0
            out["encounters"].append(dict(id=eid, patient_id=pid, date=vd.isoformat(),
                                          type="Annual physical" if is_annual else "Follow-up visit",
                                          reason="Chronic disease management" if conds else "Routine check-up",
                                          provider=provider, department="Primary Care"))
            weight += rng.gauss(0.15 if "hf" in conds else 0, 0.9)
            obs_here: dict[str, float] = {}
            for code in VITALS:
                if code == "29463-7":
                    v = weight
                elif code == "39156-5":
                    v = weight / height_m ** 2
                else:
                    v = value(code, vd)
                obs_here[code] = v
            labs = set(ROUTINE_LABS) if is_annual else set()
            for c in conds:
                labs |= set(PROFILES[c].trajs)
                if c in ("t2dm",):
                    labs |= {"4548-4", "2345-7", "14959-1"}
                if c in ("ckd", "hf"):
                    labs |= {"2160-0", "33914-3", "2823-3", "2951-2"}
                if c == "ida":
                    labs |= {"718-7", "787-2", "2276-4"}
            for code in labs - set(VITALS):
                obs_here[code] = value(code, vd)
            # Derived correlations.
            if "4548-4" in obs_here and "2345-7" in obs_here:
                obs_here["2345-7"] = (28.7 * obs_here["4548-4"] - 46.7) * 0.9 + rng.gauss(0, 8)
            if "33914-3" in obs_here and "2160-0" in obs_here:
                obs_here["2160-0"] = 0.92 * (95 / max(obs_here["33914-3"], 5)) ** 0.9 + rng.gauss(0, 0.04)
            _emit_obs(out, pid, eid, vd, obs_here)
            out["notes"].append(dict(id=_id(), patient_id=pid, encounter_id=eid, date=vd.isoformat(),
                                     type="Progress note", author=provider,
                                     text=_progress_note(rng, conds, obs_here, out, pid, vd, is_annual)))

        if acute:
            spec = ACUTE[acute]
            ad = today - timedelta(days=rng.randint(0, 3))
            eid = _id()
            out["encounters"].append(dict(id=eid, patient_id=pid, date=ad.isoformat(), type="Emergency department visit",
                                          reason=spec["reason"], provider="Dr. M. Castillo (Emergency Medicine)", department="Emergency"))
            obs_here = {code: value(code, ad) for code in VITALS if code not in ("29463-7", "39156-5")}
            obs_here["29463-7"] = weight + (4.2 if acute == "hf_exac" else 0)
            obs_here["39156-5"] = obs_here["29463-7"] / height_m ** 2
            for code in ["718-7", "6690-2", "777-3", "2823-3", "2951-2", "2160-0", "33914-3", "2345-7", "10839-9", "1988-5"]:
                obs_here[code] = value(code, ad)
            if "t2dm" in conds:
                obs_here["2345-7"] = (28.7 * value("4548-4", ad) - 46.7) * 0.9 + rng.gauss(0, 10)
            for code, v in spec["obs"].items():
                if v is not None:
                    obs_here[code] = v
            if acute == "hyperkalemia":
                obs_here["33914-3"] = max(18, obs_here["33914-3"] - 14)
            if acute in ("hyperkalemia", "hf_exac"):
                obs_here["2160-0"] = 0.92 * (95 / max(obs_here["33914-3"], 5)) ** 0.9
            _emit_obs(out, pid, eid, ad, obs_here)
            age_now = (ad - birth).days // 365
            out["notes"].append(dict(id=_id(), patient_id=pid, encounter_id=eid, date=ad.isoformat(), type="ED triage note",
                                     author="Dr. M. Castillo (Emergency Medicine)",
                                     text=_ed_note(age_now, sex, spec, conds, obs_here)))
    return out


def _fmt(code: str, v: float) -> str:
    o = OBS[code]
    return f"{v:.{o.decimals}f} {o.unit}"


def _emit_obs(out, pid, eid, when: date, obs_here: dict[str, float]):
    for code, v in obs_here.items():
        o = OBS[code]
        v = round(v, o.decimals if o.decimals else 0)
        out["observations"].append(dict(
            id=_id(), patient_id=pid, encounter_id=eid, date=when.isoformat(), category=o.category, code=code,
            name=o.name, value=v, unit=o.unit, ref_low=o.ref_low, ref_high=o.ref_high, interpretation=interpret(o, v),
        ))


def _active_meds(out, pid, when: date) -> list[str]:
    return [f"{m['name']} {m['dose']} {m['frequency']}" for m in out["medications"]
            if m["patient_id"] == pid and m["start_date"] <= when.isoformat()]


def _progress_note(rng, conds, obs, out, pid, when: date, annual: bool) -> str:
    complaints = sorted({c for k in conds for c in PROFILES[k].complaints})
    if complaints:
        reported = rng.sample(complaints, k=min(len(complaints), rng.randint(1, 2)))
        subj = f"Patient reports {' and '.join(reported)}. "
    else:
        subj = "Patient reports feeling well with no new complaints. "
    subj += rng.choice(["Adherent to medications.", "Reports occasionally missing evening doses.", "No medication side effects reported."])
    vitals = (f"BP {obs['8480-6']:.0f}/{obs['8462-4']:.0f} mmHg, HR {obs['8867-4']:.0f} bpm, RR {obs['9279-1']:.0f}/min, "
              f"SpO₂ {obs['59408-5']:.0f}%, T {obs['8310-5']:.1f} °C, weight {obs['29463-7']:.1f} kg (BMI {obs['39156-5']:.1f}).")
    lab_lines = []
    for code, v in obs.items():
        o = OBS[code]
        if o.category != "lab":
            continue
        flag = interpret(o, v)
        lab_lines.append(f"- {o.name}: {_fmt(code, v)}" + ("" if flag == "N" else f" ({flag})"))
    meds = _active_meds(out, pid, when)
    ap = []
    for k in conds:
        p = PROFILES[k]
        detail = ""
        for code in p.trajs:
            if code in obs and code != "29463-7":
                detail += f" {OBS[code].name} {_fmt(code, obs[code])}."
        ap.append(f"**{p.display}** ({p.code}).{detail} " + " ".join(rng.sample(p.plan, k=min(2, len(p.plan)))) if p.plan else f"**{p.display}** ({p.code}).{detail}")
    if not ap:
        ap.append("Healthy adult. Age-appropriate screening discussed. Continue current lifestyle.")
    return (
        f"# {'Annual physical' if annual else 'Follow-up visit'} — {when.isoformat()}\n\n"
        f"## Subjective\n\n{subj}\n\n"
        f"## Objective\n\nVitals: {vitals}\n\n" + ("Labs:\n" + "\n".join(lab_lines) + "\n\n" if lab_lines else "")
        + "## Medications\n\n" + ("\n".join(f"- {m}" for m in meds) if meds else "- None") + "\n\n"
        + "## Assessment and Plan\n\n" + "\n\n".join(ap) + "\n"
    )


def _ed_note(age: int, sex: str, spec: dict, conds: list[str], obs: dict[str, float]) -> str:
    pmh = ", ".join(PROFILES[c].display for c in conds) or "no significant past medical history"
    vit = (f"BP {obs['8480-6']:.0f}/{obs['8462-4']:.0f}, HR {obs['8867-4']:.0f}, RR {obs['9279-1']:.0f}, "
           f"SpO₂ {obs['59408-5']:.0f}% on room air, T {obs['8310-5']:.1f} °C")
    labs = "\n".join(f"- {OBS[c].name}: {_fmt(c, v)}" + ("" if interpret(OBS[c], v) == "N" else f" ({interpret(OBS[c], v)})")
                     for c, v in obs.items() if OBS[c].category == "lab")
    return (
        f"# ED triage note — {spec['reason']}\n\n## Chief complaint\n\n{spec['reason']}.\n\n"
        f"## History of present illness\n\n{age}-year-old {sex} presenting with {spec['complaint']}. "
        f"Past medical history: {pmh}.\n\n## Triage vitals\n\n{vit}.\n\n## Initial labs\n\n{labs}\n\n"
        "## Disposition\n\nPending physician evaluation.\n"
    )
