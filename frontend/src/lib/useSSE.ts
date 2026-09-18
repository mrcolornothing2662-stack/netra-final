/**
 * CyberDrishti AI — Server-Sent Events Hook
 *
 * Connects to the backend SSE endpoint for live case activity updates.
 * Auto-reconnects on disconnect with exponential backoff.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { getToken } from "../api/client";

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ||
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, "") ||
  "/api/v1";

export interface SSEEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface UseSSEResult {
  lastEvent: SSEEvent | null;
  events: SSEEvent[];
  connected: boolean;
  error: string | null;
}

export function useSSE(caseId: string | null, maxEvents = 50): UseSSEResult {
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retryRef = useRef(0);
  const sourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!caseId) return;
    const token = getToken();
    if (!token) {
      setError("Not authenticated");
      return;
    }

    // EventSource doesn't support Authorization headers natively.
    // Pass token as query param — the backend accepts both.
    const url = `${API_BASE}/events/cases/${caseId}?token=${encodeURIComponent(token)}`;

    try {
      const es = new EventSource(url);
      sourceRef.current = es;

      es.onopen = () => {
        setConnected(true);
        setError(null);
        retryRef.current = 0;
      };

      const handleFrame = (type: string, rawData: string) => {
        try {
          const parsed = JSON.parse(rawData);
          const event: SSEEvent = {
            type: parsed.type || type,
            data: parsed,
            timestamp: parsed.timestamp || new Date().toISOString(),
          };
          setLastEvent(event);
          setEvents((prev) => [event, ...prev].slice(0, maxEvents));
        } catch {
          // Non-JSON frame
        }
      };

      es.onmessage = (msg) => handleFrame("message", msg.data);
      es.addEventListener("connected", ((e: MessageEvent) => handleFrame("connected", e.data)) as EventListener);
      es.addEventListener("ping", ((e: MessageEvent) => handleFrame("ping", e.data)) as EventListener);

      es.onerror = () => {
        es.close();
        setConnected(false);
        // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
        const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30000);
        retryRef.current += 1;
        setTimeout(connect, delay);
      };
    } catch (err) {
      setError("Failed to connect to event stream");
    }
  }, [caseId, maxEvents]);

  useEffect(() => {
    connect();
    return () => {
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [connect]);

  return { lastEvent, events, connected, error };
}
