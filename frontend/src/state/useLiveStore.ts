import { useState, useEffect } from "react";
import { liveStore } from "./LiveStore";

export function useLiveStore() {
  const [, setTick] = useState(0);

  useEffect(() => {
    const unsub = liveStore.subscribe(() => {
      setTick(t => t + 1);
    });
    return unsub;
  }, []);

  return {
    backendOnline: liveStore.backendOnline,
    loading: liveStore.loading,
    error: liveStore.error,
    empty: liveStore.empty,
    cases: liveStore.cases,
    activeCase: liveStore.activeCase,
    activeCaseSummary: liveStore.activeCaseSummary,
    activeEvidence: liveStore.activeEvidence,
    activeGraph: liveStore.activeGraph,
    activeTimeline: liveStore.activeTimeline,
    fetchCases: () => liveStore.fetchCases(),
    createCase: (payload: Parameters<typeof liveStore.createCase>[0]) => liveStore.createCase(payload),
    fetchCaseDetails: (id: string) => liveStore.fetchCaseDetails(id),
    uploadEvidence: (id: string, files: File[], src?: string) => liveStore.uploadEvidence(id, files, src),
    refreshEvidence: (id: string) => liveStore.refreshEvidence(id),
  };
}
