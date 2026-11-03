"""Read access to structured clinical data, shaped for the API, charts and the LLM."""

from __future__ import annotations

from datetime import date

from app.clinical.catalog import OBS, ObsDef, resolve_obs
from app.store.db import Database


def age_of(birth_date: str, on: date | None = None) -> int:
    b, on = date.fromisoformat(birth_date), on or date.today()
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


class ClinicalRepo:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ patients

    def list_patients(self, q: str = "") -> list[dict]:
        sql = """
          SELECT p.*, (SELECT COUNT(*) FROM conditions c WHERE c.patient_id = p.id AND c.status = 'active') AS n_conditions,
                 (SELECT MAX(date) FROM encounters e WHERE e.patient_id = p.id) AS last_visit,
                 (SELECT type FROM encounters e WHERE e.patient_id = p.id ORDER BY date DESC LIMIT 1) AS last_visit_type,
                 (SELECT COUNT(*) FROM observations o WHERE o.patient_id = p.id AND o.interpretation IN ('HH','LL')
                    AND o.date = (SELECT MAX(date) FROM encounters e WHERE e.patient_id = p.id)) AS n_critical
          FROM patients p"""
        params: tuple = ()
        if q:
            sql += " WHERE p.first_name || ' ' || p.last_name LIKE ? OR p.mrn LIKE ? OR p.id IN" \
                   " (SELECT patient_id FROM conditions WHERE display LIKE ? OR code LIKE ?)"
            like = f"%{q}%"
            params = (like, like, like, like)
        rows = self.db.query(sql + " ORDER BY n_critical DESC, last_visit DESC", params)
        for r in rows:
            r["age"] = age_of(r["birth_date"])
            r["conditions"] = [c["display"] for c in self.db.query(
                "SELECT display FROM conditions WHERE patient_id = ? AND status = 'active'", (r["id"],))]
        return rows

    def patient(self, pid: str) -> dict | None:
        p = self.db.one("SELECT * FROM patients WHERE id = ?", (pid,))
        if p:
            p["age"] = age_of(p["birth_date"])
        return p

    def conditions(self, pid: str) -> list[dict]:
        return self.db.query("SELECT * FROM conditions WHERE patient_id = ? ORDER BY status, onset_date", (pid,))

    def medications(self, pid: str, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM medications WHERE patient_id = ?" + (" AND status = 'active'" if active_only else "")
        return self.db.query(sql + " ORDER BY start_date", (pid,))

    def allergies(self, pid: str) -> list[dict]:
        return self.db.query("SELECT * FROM allergies WHERE patient_id = ?", (pid,))

    def encounters(self, pid: str) -> list[dict]:
        return self.db.query("SELECT * FROM encounters WHERE patient_id = ? ORDER BY date DESC", (pid,))

    def notes(self, pid: str) -> list[dict]:
        return self.db.query("SELECT * FROM notes WHERE patient_id = ? ORDER BY date DESC", (pid,))

    def note(self, note_id: str) -> dict | None:
        return self.db.one("SELECT * FROM notes WHERE id = ?", (note_id,))

    # ------------------------------------------------------------------ observations

    def series(self, pid: str, code: str) -> dict | None:
        o = OBS.get(code)
        if not o:
            return None
        rows = self.db.query("SELECT date, value, interpretation, encounter_id FROM observations"
                             " WHERE patient_id = ? AND code = ? ORDER BY date", (pid, code))
        return {"code": code, "name": o.name, "unit": o.unit, "category": o.category, "ref_low": o.ref_low,
                "ref_high": o.ref_high, "panel": o.panel,
                "points": [{"date": r["date"], "value": r["value"], "flag": r["interpretation"]} for r in rows]}

    def available_codes(self, pid: str) -> list[dict]:
        rows = self.db.query("SELECT code, COUNT(*) AS n, MAX(date) AS last FROM observations WHERE patient_id = ?"
                             " GROUP BY code", (pid,))
        out = []
        for r in rows:
            o = OBS[r["code"]]
            out.append({"code": r["code"], "name": o.name, "category": o.category, "panel": o.panel, "count": r["n"], "last": r["last"]})
        return sorted(out, key=lambda x: (x["category"] != "vital", x["panel"], x["name"]))

    def latest(self, pid: str, category: str | None = None) -> list[dict]:
        sql = """SELECT o.* FROM observations o JOIN (
                   SELECT code, MAX(date) AS d FROM observations WHERE patient_id = ? GROUP BY code
                 ) m ON o.code = m.code AND o.date = m.d WHERE o.patient_id = ?"""
        params: list = [pid, pid]
        if category:
            sql += " AND o.category = ?"
            params.append(category)
        return self.db.query(sql + " ORDER BY o.category DESC, o.name", params)

    def latest_encounter_obs(self, pid: str) -> tuple[dict | None, list[dict]]:
        enc = self.db.one("SELECT * FROM encounters WHERE patient_id = ? ORDER BY date DESC LIMIT 1", (pid,))
        if not enc:
            return None, []
        return enc, self.db.query("SELECT * FROM observations WHERE encounter_id = ?", (enc["id"],))

    def trend(self, pid: str, code: str) -> dict | None:
        s = self.series(pid, code)
        if not s or not s["points"]:
            return None
        pts = s["points"]
        first, last = pts[0], pts[-1]
        change = last["value"] - first["value"]
        days = max((date.fromisoformat(last["date"]) - date.fromisoformat(first["date"])).days, 1)
        return {**{k: s[k] for k in ("code", "name", "unit", "ref_low", "ref_high")}, "first": first, "last": last,
                "n": len(pts), "change": round(change, 3), "per_year": round(change / days * 365.25, 3),
                "min": min(p["value"] for p in pts), "max": max(p["value"] for p in pts)}

    def resolve_series(self, pid: str, term: str) -> dict | None:
        o: ObsDef | None = resolve_obs(term)
        return self.series(pid, o.code) if o else None

    # ------------------------------------------------------------------ summaries

    def summary(self, pid: str) -> dict | None:
        p = self.patient(pid)
        if not p:
            return None
        latest = self.latest(pid)
        enc, last_obs = self.latest_encounter_obs(pid)
        return {
            "patient": p,
            "conditions": self.conditions(pid),
            "medications": self.medications(pid),
            "allergies": self.allergies(pid),
            "latest_vitals": [o for o in latest if o["category"] == "vital"],
            "latest_labs": [o for o in latest if o["category"] == "lab"],
            "abnormal_labs": [o for o in latest if o["category"] == "lab" and o["interpretation"] != "N"],
            "last_encounter": enc,
            "last_encounter_obs": last_obs,
            "encounters": self.encounters(pid)[:12],
        }

    def summary_text(self, pid: str) -> str:
        """Compact, LLM-friendly patient summary (the structured "chart" the assistant can cite)."""
        s = self.summary(pid)
        if not s:
            return ""
        p = s["patient"]
        lines = [f"Patient: {p['first_name']} {p['last_name']}, {p['age']}-year-old {p['sex']}, MRN {p['mrn']} (synthetic record)."]
        lines.append("Active problems: " + ("; ".join(f"{c['display']} [{c['code']}] since {c['onset_date']}"
                                                       for c in s["conditions"] if c["status"] == "active") or "none recorded"))
        lines.append("Medications: " + ("; ".join(f"{m['name']} {m['dose']} {m['frequency']} (since {m['start_date']})"
                                                  for m in s["medications"] if m["status"] == "active") or "none"))
        lines.append("Allergies: " + ("; ".join(f"{a['substance']} ({a['reaction']}, {a['severity']})" for a in s["allergies"]) or "NKDA"))
        if s["last_encounter"]:
            e = s["last_encounter"]
            lines.append(f"Most recent encounter: {e['date']} {e['type']} — {e['reason']}.")
        lines.append("Latest vitals: " + "; ".join(f"{o['name']} {o['value']} {o['unit']} ({o['date']})" for o in s["latest_vitals"]))
        lines.append("Latest labs: " + "; ".join(
            f"{o['name']} {o['value']} {o['unit']}{'' if o['interpretation'] == 'N' else ' [' + o['interpretation'] + ']'} ({o['date']})"
            for o in s["latest_labs"]))
        return "\n".join(lines)

    def trend_text(self, pid: str, code: str) -> str:
        t = self.trend(pid, code)
        if not t:
            return ""
        s = self.series(pid, code)
        lo, hi = t["ref_low"], t["ref_high"]
        rng = ("reference " + (f"{lo}–{hi}" if lo is not None and hi is not None else f"≤ {hi}" if hi is not None
                                else f"≥ {lo}" if lo is not None else "not defined") + f" {t['unit']}")
        pts = ", ".join(f"{p['date']}: {p['value']}{'' if p['flag'] == 'N' else ' (' + p['flag'] + ')'}" for p in s["points"][-12:])
        return (f"{t['name']} trend ({t['unit']}, {rng}). {t['n']} results from {t['first']['date']} to {t['last']['date']}; "
                f"changed {t['change']:+} ({t['per_year']:+}/year), range {t['min']}–{t['max']}. Values: {pts}.")

    # ------------------------------------------------------------------ cohort analytics

    def cohort(self) -> dict:
        db = self.db
        patients = db.query("SELECT id, sex, birth_date FROM patients")
        bands = {"<50": 0, "50-59": 0, "60-69": 0, "70-79": 0, "80+": 0}
        for p in patients:
            a = age_of(p["birth_date"])
            bands["<50" if a < 50 else "50-59" if a < 60 else "60-69" if a < 70 else "70-79" if a < 80 else "80+"] += 1
        prevalence = db.query("SELECT display AS condition, code, COUNT(DISTINCT patient_id) AS patients FROM conditions"
                              " WHERE status = 'active' GROUP BY code ORDER BY patients DESC")
        control = []
        for code, target, cond in [("4548-4", 7.0, "E11"), ("8480-6", 130, "I10"), ("13457-7", 100, "E78")]:
            rows = db.query(f"""SELECT o.patient_id, o.value FROM observations o JOIN (
                    SELECT patient_id, MAX(date) d FROM observations WHERE code = ? GROUP BY patient_id) m
                  ON o.patient_id = m.patient_id AND o.date = m.d AND o.code = ?
                  WHERE o.patient_id IN (SELECT patient_id FROM conditions WHERE code LIKE ?)""", (code, code, cond + "%"))
            if rows:
                ok = sum(1 for r in rows if r["value"] < target)
                control.append({"measure": f"{OBS[code].name} < {target:g} {OBS[code].unit}", "condition_code": cond,
                                "controlled": ok, "uncontrolled": len(rows) - ok})
        a1c_by_quarter = db.query("""SELECT substr(date,1,4) || '-Q' || ((CAST(substr(date,6,2) AS INTEGER)+2)/3) AS period,
                 ROUND(AVG(value),2) AS mean, COUNT(*) AS n FROM observations WHERE code = '4548-4' AND patient_id IN
                 (SELECT patient_id FROM conditions WHERE code LIKE 'E11%') GROUP BY period ORDER BY period""")
        abnormal = db.query("""SELECT name, COUNT(*) AS n FROM observations WHERE interpretation != 'N' AND category = 'lab'
                 AND date >= date('now', '-365 day') GROUP BY name ORDER BY n DESC LIMIT 10""")
        return {"n_patients": len(patients), "sex": {s: sum(1 for p in patients if p["sex"] == s) for s in ("female", "male")},
                "age_bands": [{"band": k, "patients": v} for k, v in bands.items()], "prevalence": prevalence,
                "control": control, "a1c_trend": a1c_by_quarter, "abnormal_labs": abnormal,
                "encounters_by_month": db.query("SELECT substr(date,1,7) AS month, COUNT(*) AS n FROM encounters"
                                                " WHERE date >= date('now','-24 month') GROUP BY month ORDER BY month")}
