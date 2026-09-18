/**
 * CyberDrishti AI — Case Edit Modal
 * Inline modal for updating case title, description, status, priority, etc.
 */
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { casesApi, type CreateCasePayload } from "../../api/cases";
import { Button } from "../primitives/Button";
import s from "./case.module.css";

interface CaseEditModalProps {
  caseId: string;
  current: {
    title?: string;
    description?: string;
    status?: string;
    priority?: string;
    crime_type?: string;
    fir_number?: string;
    police_station?: string;
  };
  onClose: () => void;
  onSaved: () => void;
}

// These values MUST match the backend's ck_cases_status / ck_cases_priority
// CHECK constraints (db/models.py) — options outside them cause HTTP 500.
const STATUSES = ["open", "in_progress", "under_review", "closed", "on_hold"];
const PRIORITIES = ["high", "medium", "low"];
const CRIME_TYPES = [
  "cyber_fraud", "financial_fraud", "identity_theft", "phishing",
  "ransomware", "data_breach", "online_harassment", "other",
];

export function CaseEditModal({ caseId, current, onClose, onSaved }: CaseEditModalProps) {
  const [title, setTitle] = useState(current.title || "");
  const [description, setDescription] = useState(current.description || "");
  const [status, setStatus] = useState(current.status || "open");
  const [priority, setPriority] = useState(current.priority || "high");
  const [crimeType, setCrimeType] = useState(current.crime_type || "");
  const [firNumber, setFirNumber] = useState(current.fir_number || "");
  const [policeStation, setPoliceStation] = useState(current.police_station || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("Title is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await casesApi.update(caseId, {
        title: title.trim(),
        description: description.trim() || undefined,
        priority: priority as CreateCasePayload["priority"],
        crime_type: crimeType || undefined,
        fir_number: firNumber.trim() || undefined,
        police_station: policeStation.trim() || undefined,
        status,
      } as any);
      onSaved();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to update case";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const fieldStyle: React.CSSProperties = {
    width: "100%",
    padding: "10px 14px",
    background: "var(--surface-0)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-sm)",
    color: "var(--text-primary)",
    font: "var(--type-body-sm)",
    outline: "none",
    transition: "border-color 0.15s",
  };

  const labelStyle: React.CSSProperties = {
    font: "var(--type-mono-xs)",
    color: "var(--text-secondary)",
    letterSpacing: "0.06em",
    textTransform: "uppercase" as const,
    marginBottom: 6,
    display: "block",
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        style={{
          position: "fixed", inset: 0, zIndex: 1000,
          background: "rgba(0, 0, 0, 0.6)", backdropFilter: "blur(4px)",
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: "var(--space-6)",
        }}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 8 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          onClick={(e) => e.stopPropagation()}
          style={{
            background: "var(--surface-1)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-card)",
            padding: "var(--space-8)",
            width: "100%", maxWidth: 560,
            maxHeight: "85vh", overflowY: "auto",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-6)" }}>
            <h2 className="t-title-3" style={{ margin: 0, color: "var(--text-primary)" }}>Edit Investigation</h2>
            <button
              onClick={onClose}
              style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: 20, padding: 4 }}
              aria-label="Close"
            >✕</button>
          </div>

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
            <div>
              <label style={labelStyle}>Case Title</label>
              <input style={fieldStyle} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Investigation title" />
            </div>

            <div>
              <label style={labelStyle}>Description</label>
              <textarea
                style={{ ...fieldStyle, minHeight: 80, resize: "vertical" }}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of the investigation"
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
              <div>
                <label style={labelStyle}>Status</label>
                <select style={fieldStyle} value={status} onChange={(e) => setStatus(e.target.value)}>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>{s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={labelStyle}>Priority</label>
                <select style={fieldStyle} value={priority} onChange={(e) => setPriority(e.target.value)}>
                  {PRIORITIES.map((p) => (
                    <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label style={labelStyle}>Crime Type</label>
              <select style={fieldStyle} value={crimeType} onChange={(e) => setCrimeType(e.target.value)}>
                <option value="">— Select —</option>
                {CRIME_TYPES.map((ct) => (
                  <option key={ct} value={ct}>{ct.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}</option>
                ))}
              </select>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
              <div>
                <label style={labelStyle}>FIR Number</label>
                <input style={fieldStyle} value={firNumber} onChange={(e) => setFirNumber(e.target.value)} placeholder="e.g. 123/2026" />
              </div>
              <div>
                <label style={labelStyle}>Police Station</label>
                <input style={fieldStyle} value={policeStation} onChange={(e) => setPoliceStation(e.target.value)} placeholder="e.g. Cyber Cell" />
              </div>
            </div>

            {error && (
              <div style={{ padding: "10px 14px", background: "var(--critical-tint)", border: "1px solid rgba(255,92,92,0.4)", borderRadius: "var(--radius-sm)", color: "var(--critical)", font: "var(--type-body-sm)" }}>
                {error}
              </div>
            )}

            <div style={{ display: "flex", gap: "var(--space-3)", justifyContent: "flex-end", marginTop: "var(--space-2)" }}>
              <Button variant="ghost" type="button" onClick={onClose}>Cancel</Button>
              <Button variant="primary" type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save Changes"}
              </Button>
            </div>
          </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
