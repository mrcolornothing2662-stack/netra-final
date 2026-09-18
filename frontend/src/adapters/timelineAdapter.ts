import type { BackendTimelineEvent } from "../api/graph";
import type { CaseEvent } from "../data/types";

function classifyEventKind(eventType?: string | null, text?: string | null): "COMMUNICATION" | "TRANSACTION" | "LOCATION" | "DEVICE" {
  const t = `${eventType || ""} ${text || ""}`.toLowerCase();
  if (t.includes("upi") || t.includes("transfer") || t.includes("bank") || t.includes("inr") || t.includes("₹") || t.includes("rs") || t.includes("account") || t.includes("txn")) {
    return "TRANSACTION";
  }
  if (t.includes("tower") || t.includes("cell") || t.includes("location") || t.includes("lat") || t.includes("station") || t.includes("city")) {
    return "LOCATION";
  }
  if (t.includes("imei") || t.includes("imsi") || t.includes("device") || t.includes("ip") || t.includes("mac") || t.includes("login")) {
    return "DEVICE";
  }
  return "COMMUNICATION";
}

function parseDateTime(timestamp?: string | null): { date: string; ts: string } {
  if (!timestamp) {
    return { date: "Timeline", ts: "00:00" };
  }
  try {
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return { date: "Recorded", ts: timestamp.slice(0, 5) };
    const date = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const ts = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
    return { date, ts };
  } catch {
    return { date: "Recorded", ts: "00:00" };
  }
}

export function adaptTimelineEvent(e: BackendTimelineEvent): CaseEvent {
  const content = e.text_content || e.text || "Event logged";
  // Event time ONLY. Never fall back to the ingestion timestamp — that would
  // misrepresent when the activity happened.
  const eventTime = e.event_time ?? e.timestamp ?? null;
  const { date, ts } = parseDateTime(eventTime);
  const needsNormalization = e.time_status === "TIME_NORMALIZATION_REQUIRED" || !eventTime;

  // Extract entity names or references from metadata
  const entityIds: string[] = [];
  if (e.metadata) {
    if (typeof e.metadata.caller === "string") entityIds.push(e.metadata.caller);
    if (typeof e.metadata.callee === "string") entityIds.push(e.metadata.callee);
    if (typeof e.metadata.sender === "string" && e.metadata.sender !== "__system__") entityIds.push(e.metadata.sender);
  }

  const evidenceIds: string[] = [];
  if (e.source_doc) evidenceIds.push(e.source_doc);

  return {
    id: e.id,
    date: needsNormalization ? "Time unknown" : date,
    ts: needsNormalization ? "—" : ts,
    kind: classifyEventKind(e.event_type, content),
    label: content,
    entityIds,
    evidenceIds,
    timeStatus: e.time_status || (needsNormalization ? "TIME_NORMALIZATION_REQUIRED" : "OK"),
    ingestedAt: e.ingested_at ?? null,
    isRoutine: e.is_routine === true,
  };
}
