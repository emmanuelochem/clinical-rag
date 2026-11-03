export type Flag = "N" | "H" | "L" | "HH" | "LL";

export interface Obs {
  id: string; patient_id: string; encounter_id: string; date: string; category: "lab" | "vital";
  code: string; name: string; value: number; unit: string; ref_low: number | null; ref_high: number | null;
  interpretation: Flag;
}
export interface Series {
  code: string; name: string; unit: string; category: string; panel: string;
  ref_low: number | null; ref_high: number | null;
  points: { date: string; value: number; flag: Flag }[];
  companion?: Series;
}
export interface PatientRow {
  id: string; mrn: string; first_name: string; last_name: string; sex: string; birth_date: string; age: number;
  primary_provider: string; conditions: string[]; last_visit: string | null; last_visit_type: string | null; n_critical: number;
}
export interface Alert { severity: "critical" | "warning" | "info"; title: string; detail: string; rule: string; evidence: string[] }
export interface News2 { score: number; risk: string; components: Record<string, number>; assumptions: string[] }
export interface Condition { id: string; code: string; display: string; onset_date: string; status: string }
export interface Medication { id: string; name: string; dose: string; frequency: string; start_date: string; end_date: string | null; status: string; indication: string }
export interface Allergy { id: string; substance: string; reaction: string; severity: string }
export interface Encounter { id: string; date: string; type: string; reason: string; provider: string; department: string }
export interface Note { id: string; patient_id: string; encounter_id: string; date: string; type: string; author: string; text: string }

export interface PatientDetail {
  patient: PatientRow & { blood_type: string; phone: string; address: string };
  conditions: Condition[]; medications: Medication[]; allergies: Allergy[];
  latest_vitals: Obs[]; latest_labs: Obs[]; abnormal_labs: Obs[];
  last_encounter: Encounter | null; last_encounter_obs: Obs[]; encounters: Encounter[];
  alerts: Alert[]; news2: News2 | null;
  available: { code: string; name: string; category: string; panel: string; count: number; last: string }[];
}

export interface Source {
  n: number; kind: "record" | "note" | "kb"; title: string; text: string;
  source?: string; date?: string; doc_id?: string; chunk_id?: string; headings?: string[]; page?: number | null;
  score?: number; rerank_score?: number | null; vector_rank?: number | null; keyword_rank?: number | null;
  matched_queries?: string[]; context_before?: string; context_after?: string; patient_id?: string; chart_code?: string | null;
}

export interface Plan {
  standalone_question?: string; note_queries?: string[]; kb_queries?: string[]; lab_tests?: string[]; chart?: boolean;
  followup_queries?: string[]; missing?: string;
}

export type AgentEvent =
  | { type: "status"; step: string; message: string }
  | { type: "plan"; plan: Plan }
  | { type: "alerts"; alerts: Alert[]; news2?: News2 | null }
  | { type: "chart"; chart: Series }
  | { type: "sources"; sources: Source[] }
  | { type: "token"; text: string }
  | { type: "done"; citations?: number[] }
  | { type: "result"; result: DifferentialResult }
  | { type: "error"; message: string };

export interface Finding { finding: string; source: number | null }
export interface Differential {
  condition: string; icd10: string; likelihood: "high" | "moderate" | "low"; cant_miss: boolean; reasoning: string;
  supporting: Finding[]; against: Finding[]; next_steps: string[]; evidence_strength: number;
}
export interface DifferentialResult {
  summary: string; differentials: Differential[]; recommended_workup: string[]; information_gaps: string[];
  presentation: string; disclaimer: string;
}

export interface KbDocument {
  id: string; title: string; source: string; mime: string; size_bytes: number; status: string; error: string | null;
  num_chunks: number; created_at: string; has_file: boolean;
}
