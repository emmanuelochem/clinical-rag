"use client";

import { BookOpen } from "lucide-react";
import { Chat } from "@/components/Chat";

export default function AssistantPage() {
  return (
    <div className="mx-auto flex h-[calc(100vh-130px)] max-w-3xl flex-col">
      <div className="mb-3">
        <h1 className="flex items-center gap-2 text-xl font-semibold"><BookOpen size={20} className="text-accent" />Reference Q&amp;A</h1>
        <p className="text-sm text-muted">Questions answered from the medical knowledge base only, no patient data. Open a patient to ask about their record.</p>
      </div>
      <div className="min-h-0 flex-1">
        <Chat suggestions={[
          "How is NEWS2 interpreted and what response does each band require?",
          "What are the diagnostic criteria for DKA versus HHS?",
          "Emergency management of hyperkalaemia with ECG changes",
          "Which features distinguish ACS from pulmonary embolism in acute chest pain?",
          "When should metformin be stopped in CKD?",
        ]} placeholder="Ask the reference library…" />
      </div>
    </div>
  );
}
