"""Catalog of lab tests and vital signs (LOINC codes, units, adult reference ranges)
plus the condition list (ICD-10) used by the synthetic data generator.

Reference ranges are typical adult values for demonstration only; real deployments
must use the performing laboratory's ranges.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObsDef:
    code: str  # LOINC
    name: str
    unit: str
    category: str  # "lab" | "vital"
    ref_low: float | None
    ref_high: float | None
    panel: str = ""
    decimals: int = 1
    # Critical (panic) thresholds that trigger red-flag alerts.
    crit_low: float | None = None
    crit_high: float | None = None


OBS: dict[str, ObsDef] = {o.code: o for o in [
    # Metabolic / diabetes
    ObsDef("4548-4", "HbA1c", "%", "lab", 4.0, 5.6, "Diabetes", 1),
    ObsDef("2345-7", "Glucose (fasting)", "mg/dL", "lab", 70, 99, "Metabolic", 0, 54, 400),
    # Renal / electrolytes
    ObsDef("2160-0", "Creatinine", "mg/dL", "lab", 0.6, 1.3, "Renal", 2),
    ObsDef("33914-3", "eGFR", "mL/min/1.73m²", "lab", 60, None, "Renal", 0, 15, None),
    ObsDef("14959-1", "Urine albumin/creatinine", "mg/g", "lab", None, 30, "Renal", 0),
    ObsDef("2823-3", "Potassium", "mmol/L", "lab", 3.5, 5.1, "Electrolytes", 1, 2.8, 6.0),
    ObsDef("2951-2", "Sodium", "mmol/L", "lab", 135, 145, "Electrolytes", 0, 120, 160),
    # Lipids
    ObsDef("2093-3", "Total cholesterol", "mg/dL", "lab", None, 200, "Lipids", 0),
    ObsDef("13457-7", "LDL cholesterol", "mg/dL", "lab", None, 100, "Lipids", 0),
    ObsDef("2085-9", "HDL cholesterol", "mg/dL", "lab", 40, None, "Lipids", 0),
    ObsDef("2571-8", "Triglycerides", "mg/dL", "lab", None, 150, "Lipids", 0),
    # Hematology
    ObsDef("718-7", "Hemoglobin", "g/dL", "lab", 12.0, 17.5, "CBC", 1, 7.0, 20.0),
    ObsDef("6690-2", "WBC", "10³/µL", "lab", 4.0, 11.0, "CBC", 1, 2.0, 30.0),
    ObsDef("777-3", "Platelets", "10³/µL", "lab", 150, 400, "CBC", 0, 50, 1000),
    ObsDef("787-2", "MCV", "fL", "lab", 80, 100, "CBC", 0),
    ObsDef("2276-4", "Ferritin", "ng/mL", "lab", 20, 300, "Iron", 0),
    # Cardiac / inflammatory / other
    ObsDef("30934-4", "BNP", "pg/mL", "lab", None, 100, "Cardiac", 0),
    ObsDef("10839-9", "Troponin I", "ng/mL", "lab", None, 0.04, "Cardiac", 3, None, 0.4),
    ObsDef("1988-5", "CRP", "mg/L", "lab", None, 10, "Inflammatory", 1),
    ObsDef("3016-3", "TSH", "mIU/L", "lab", 0.4, 4.0, "Thyroid", 2),
    ObsDef("1742-6", "ALT", "U/L", "lab", 7, 56, "Liver", 0),
    ObsDef("1920-8", "AST", "U/L", "lab", 10, 40, "Liver", 0),
    # Vitals
    ObsDef("8480-6", "Systolic BP", "mmHg", "vital", 90, 130, "Vitals", 0, 80, 180),
    ObsDef("8462-4", "Diastolic BP", "mmHg", "vital", 60, 80, "Vitals", 0, None, 120),
    ObsDef("8867-4", "Heart rate", "bpm", "vital", 60, 100, "Vitals", 0, 40, 130),
    ObsDef("9279-1", "Respiratory rate", "/min", "vital", 12, 20, "Vitals", 0, 8, 30),
    ObsDef("59408-5", "SpO₂", "%", "vital", 95, 100, "Vitals", 0, 90, None),
    ObsDef("8310-5", "Temperature", "°C", "vital", 36.1, 37.5, "Vitals", 1, 35.0, 39.5),
    ObsDef("29463-7", "Weight", "kg", "vital", None, None, "Vitals", 1),
    ObsDef("39156-5", "BMI", "kg/m²", "vital", 18.5, 24.9, "Vitals", 1),
]}

BY_NAME = {o.name.lower(): o for o in OBS.values()}

ALIASES = {
    "a1c": "4548-4", "hba1c": "4548-4", "hemoglobin a1c": "4548-4", "glucose": "2345-7", "sugar": "2345-7",
    "creatinine": "2160-0", "egfr": "33914-3", "gfr": "33914-3", "kidney function": "33914-3",
    "uacr": "14959-1", "albuminuria": "14959-1", "potassium": "2823-3", "k": "2823-3", "sodium": "2951-2",
    "cholesterol": "2093-3", "ldl": "13457-7", "hdl": "2085-9", "triglycerides": "2571-8",
    "hemoglobin": "718-7", "hgb": "718-7", "hb": "718-7", "wbc": "6690-2", "white cells": "6690-2",
    "platelets": "777-3", "mcv": "787-2", "ferritin": "2276-4", "bnp": "30934-4", "troponin": "10839-9",
    "crp": "1988-5", "tsh": "3016-3", "thyroid": "3016-3", "alt": "1742-6", "ast": "1920-8",
    "blood pressure": "8480-6", "bp": "8480-6", "systolic": "8480-6", "diastolic": "8462-4",
    "heart rate": "8867-4", "pulse": "8867-4", "hr": "8867-4", "respiratory rate": "9279-1",
    "oxygen": "59408-5", "spo2": "59408-5", "o2 sat": "59408-5", "saturation": "59408-5",
    "temperature": "8310-5", "temp": "8310-5", "fever": "8310-5", "weight": "29463-7", "bmi": "39156-5",
}


def resolve_obs(term: str) -> ObsDef | None:
    t = term.strip().lower()
    if t in OBS:
        return OBS[t]
    if t in ALIASES:
        return OBS[ALIASES[t]]
    if t in BY_NAME:
        return BY_NAME[t]
    for name, o in BY_NAME.items():
        if t in name or name in t:
            return o
    for alias, code in ALIASES.items():
        if len(alias) > 3 and alias in t:
            return OBS[code]
    return None


def interpret(o: ObsDef, value: float) -> str:
    """HL7-style interpretation flag: N, L, H, LL (critical low), HH (critical high)."""
    if o.crit_low is not None and value <= o.crit_low:
        return "LL"
    if o.crit_high is not None and value >= o.crit_high:
        return "HH"
    if o.ref_low is not None and value < o.ref_low:
        return "L"
    if o.ref_high is not None and value > o.ref_high:
        return "H"
    return "N"
