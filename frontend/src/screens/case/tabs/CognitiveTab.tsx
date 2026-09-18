/**
 * CyberDrishti AI — Cognitive Forensic Intelligence Hub
 *
 * Master tab integrating all 11 cognitive engines into a single,
 * investigator-friendly interface with real-time data visualization.
 */
import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "../../../components/primitives/Button";
import { Icon } from "../../../components/icons";
import {
  cognitiveApi,
  type ContradictionsResponse,
  type HypothesesResponse,
  type HypothesisReportResponse,
  type NextBestActionsResponse,
  type MOFingerprintResponse,
  type CounterfactualResponse,
  type CounterfactualCandidate,
  type NetworkReplayResponse,
  type CrossCaseResponse,
  type SyndicateRadarResponse,
  type SyndicateCluster,
  type RadarBlip,
  type SyndicateCollisionItem,
  type VerifyDraftResponse,
  type CaseComplianceShieldResponse,
  type BenchmarkCase,
  type DefenceAuditResponse,
  type DefenceStressTestResponse,
  type DefenceChallenge,
  type RankedAction,
  type ActionDraftResponse,
  type ConfidenceMeterResponse,
  type FindingConfidenceBreakdown,
  type SuspectConformalSet,
  type ConformalCalibrationItem,
  type MOMatch,
  type MOStageAlignment,
  type MOStageEvidenceItem,
  type MOPlaybookSummary,
  type TrainingDrillSummary,
  type TrainingSessionResponse,
  type TrainingTask,
  type TrainingEvaluation,
  type TrainingEngineHintsResponse,
} from "../../../api/cognitive";
import { CaseIntelligence } from "./CaseIntelligence";
import s from "./CognitiveTab.module.css";

/* ── Engine Registry ─────────────────────────────────────────────────── */

const ENGINES = [
  { id: "contradictions", label: "Contradictions & Anomalies", icon: "⚡", desc: "Ledger audit, behavioral profiler & travel" },
  { id: "hypotheses", label: "🎯 Hypothesis Board", icon: "🎯", desc: "ACH competing theory evaluation & Heuer matrix" },
  { id: "confidence", label: "Confidence Meter", icon: "📊", desc: "Evidentiary health, split-conformal uncertainty & corroboration" },
  { id: "nextbest", label: "Golden Hours", icon: "⚡", desc: "Golden-Hours VoI action center & statutory notices" },
  { id: "mo", label: "MO Fingerprint", icon: "🔍", desc: "Crime script playbook matching" },
  { id: "counterfactual", label: "What-If Sandbox", icon: "💰", desc: "Counterfactual freeze sandbox & cascade simulation" },
  { id: "replay", label: "Replay", icon: "🎬", desc: "CTDG temporal network frames" },
  { id: "crosscase", label: "Syndicate Radar", icon: "🛰️", desc: "Cross-case blind index & criminal network detection" },
  { id: "verifier", label: "Compliance Shield", icon: "🛡️", desc: "Statutory firewall & Section 63 BSA integrity" },
  { id: "defence_bot", label: "Defence Bot", icon: "⚖️", desc: "Adversarial hypothesis stress-testing & evidence integrity verification" },
  { id: "benchmark", label: "Training Simulator", icon: "🎯", desc: "Interactive training drills, synthetic benchmarking & pedagogical evaluation" },
] as const;

type EngineId = (typeof ENGINES)[number]["id"];

/* ── Component ───────────────────────────────────────────────────────── */

export function CognitiveTab({ caseId }: { caseId: string }) {
  const [activeEngine, setActiveEngine] = useState<EngineId>("contradictions");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Engine-specific data
  const [contradictions, setContradictions] = useState<ContradictionsResponse | null>(null);
  const [hypotheses, setHypotheses] = useState<HypothesesResponse | null>(null);
  const [nextBest, setNextBest] = useState<NextBestActionsResponse | null>(null);
  const [moResult, setMoResult] = useState<MOFingerprintResponse | null>(null);
  const [cfResult, setCfResult] = useState<CounterfactualResponse | null>(null);
  const [replayResult, setReplayResult] = useState<NetworkReplayResponse | null>(null);
  const [crossCase, setCrossCase] = useState<CrossCaseResponse | null>(null);
  const [complianceShield, setComplianceShield] = useState<CaseComplianceShieldResponse | null>(null);
  const [verifyResult, setVerifyResult] = useState<VerifyDraftResponse | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkCase | null>(null);
  const [defenceAudit, setDefenceAudit] = useState<DefenceAuditResponse | null>(null);
  const [defenceClaim, setDefenceClaim] = useState("");
  const [defenceStressResult, setDefenceStressResult] = useState<DefenceStressTestResponse | null>(null);
  const [defenceStressLoading, setDefenceStressLoading] = useState(false);

  // Golden Hours Action Center state
  const [actionFilter, setActionFilter] = useState<"all" | "ready" | "blocked">("all");
  const [activeNoticeModal, setActiveNoticeModal] = useState<{
    actionCode: string;
    noticeText: string;
    statute: string;
    banner: string;
  } | null>(null);
  const [copiedDraft, setCopiedDraft] = useState(false);
  const [draftingActionCode, setDraftingActionCode] = useState<string | null>(null);

  // Feature 07: Crime Script Matcher state
  const [moThreshold, setMoThreshold] = useState<number>(0.60);
  const [selectedScriptPlaybook, setSelectedScriptPlaybook] = useState<string | null>(null);
  const [selectedStageName, setSelectedStageName] = useState<string | null>(null);
  const [showFormulaBreakdown, setShowFormulaBreakdown] = useState<boolean>(true);
  const [showAdhocTester, setShowAdhocTester] = useState<boolean>(false);
  const [adhocTranscript, setAdhocTranscript] = useState<string>("");
  const [adhocRunning, setAdhocRunning] = useState<boolean>(false);
  const [adhocResult, setAdhocResult] = useState<MOFingerprintResponse | null>(null);
  const [, setCatalogPlaybooks] = useState<MOPlaybookSummary[]>([]);

  // Input state for interactive engines
  const [freezeAccount, setFreezeAccount] = useState("");
  const [freezeTime, setFreezeTime] = useState("");
  const [cfCandidates, setCfCandidates] = useState<CounterfactualCandidate[]>([]);
  const [cfFilter, setCfFilter] = useState<"all" | "blocked" | "stopped" | "starved" | "completed">("all");
  const [verifyText, setVerifyText] = useState("");
  const [benchTypology, setBenchTypology] = useState("DIGITAL_ARREST");

  // Syndicate Radar state
  const [syndicateRadar, setSyndicateRadar] = useState<SyndicateRadarResponse | null>(null);
  const [radarFilter, setRadarFilter] = useState<string>("ALL");
  const [selectedSyndicate, setSelectedSyndicate] = useState<string | null>(null);
  const [hoveredBlip, setHoveredBlip] = useState<RadarBlip | null>(null);

  // Feature 04: Hypothesis Investigation Board state
  const [selectedSuspectEntity, setSelectedSuspectEntity] = useState<string | null>(null);
  const [hypothesisReportModal, setHypothesisReportModal] = useState<HypothesisReportResponse | null>(null);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [copiedReport, setCopiedReport] = useState(false);
  const [whatIfMode, setWhatIfMode] = useState(false);
  const [whatIfInputs, setWhatIfInputs] = useState<Record<string, number>>({});
  const [whatIfLoading, setWhatIfLoading] = useState(false);

  // Feature 05: Confidence Meter state
  const [confidenceData, setConfidenceData] = useState<ConfidenceMeterResponse | null>(null);
  const [conformalEpsilon, setConformalEpsilon] = useState<number>(0.05);
  const [tierFilter, setTierFilter] = useState<string>("ALL");
  const [calibrationsList, setCalibrationsList] = useState<ConformalCalibrationItem[]>([]);
  const [showCalibrationModal, setShowCalibrationModal] = useState(false);

  // Feature 11: Training Simulator state
  const [trainingDrills, setTrainingDrills] = useState<TrainingDrillSummary[]>([]);
  const [activeTrainingSession, setActiveTrainingSession] = useState<TrainingSessionResponse | null>(null);
  const [selectedDrillId, setSelectedDrillId] = useState<string>("DRILL-01-DIGITAL-ARREST");
  const [trainingDifficultyFilter, setTrainingDifficultyFilter] = useState<string>("ALL");
  const [trainingActiveArtifactTab, setTrainingActiveArtifactTab] = useState<string>("whatsapp_export.txt");
  const [trainingOfficerAnswers, setTrainingOfficerAnswers] = useState<Record<string, string>>({});
  const [trainingHints, setTrainingHints] = useState<TrainingEngineHintsResponse["hints"] | null>(null);
  const [loadingHints, setLoadingHints] = useState(false);
  const [submittingDrill, setSubmittingDrill] = useState(false);
  const [startingDrill, setStartingDrill] = useState(false);
  const [showSolutionModal, setShowSolutionModal] = useState(false);
  const [exportSuccessMessage, setExportSuccessMessage] = useState<string | null>(null);
  const [exportingCase, setExportingCase] = useState(false);

  const runEngine = useCallback(async (engineId: EngineId) => {
    setLoading(true);
    setError(null);
    try {
      switch (engineId) {
        case "contradictions": {
          const r = await cognitiveApi.contradictions(caseId);
          setContradictions(r);
          break;
        }
        case "hypotheses": {
          const r = await cognitiveApi.hypotheses(caseId, selectedSuspectEntity || undefined);
          setHypotheses(r);
          if (r.target_entity && !selectedSuspectEntity) {
            setSelectedSuspectEntity(r.target_entity);
          }
          if (r.observations) {
            setWhatIfInputs({ ...r.observations });
          }
          break;
        }
        case "confidence": {
          const r = await cognitiveApi.confidenceMeter(caseId, conformalEpsilon, selectedSuspectEntity || undefined);
          setConfidenceData(r);
          try {
            const cals = await cognitiveApi.getCalibrations();
            setCalibrationsList(cals.calibrations || []);
          } catch {
            // non-fatal
          }
          break;
        }
        case "nextbest": {
          const r = await cognitiveApi.nextBestActions(caseId);
          setNextBest(r);
          break;
        }
        case "mo": {
          const r = await cognitiveApi.moFingerprint(caseId, moThreshold);
          setMoResult(r);
          try {
            const pb = await cognitiveApi.getPlaybooks();
            setCatalogPlaybooks(pb.playbooks || []);
          } catch {
            // non-fatal
          }
          break;
        }
        case "replay": {
          const r = await cognitiveApi.networkReplay(caseId);
          setReplayResult(r);
          break;
        }
        case "crosscase": {
          try {
            const radar = await cognitiveApi.syndicateRadar(caseId);
            setSyndicateRadar(radar);
          } catch {
            const r = await cognitiveApi.crossCaseCollisions();
            setCrossCase(r);
          }
          break;
        }
        case "verifier": {
          const r = await cognitiveApi.complianceShield(caseId);
          setComplianceShield(r);
          break;
        }
        case "counterfactual": {
          const cand = await cognitiveApi.counterfactualCandidates(caseId);
          if (cand?.candidates?.length) {
            setCfCandidates(cand.candidates);
            const targetAcc = freezeAccount || cand.candidates[0].account;
            const targetTime = freezeTime || cand.candidates[0].suggested_freeze_time;
            if (!freezeAccount) setFreezeAccount(targetAcc);
            if (!freezeTime) setFreezeTime(targetTime);
            if (targetAcc && targetTime) {
              const r = await cognitiveApi.counterfactualFreeze(caseId, targetAcc, targetTime, [], true, false);
              setCfResult(r);
            }
          }
          break;
        }
        case "defence_bot": {
          const r = await cognitiveApi.defenceAudit(caseId);
          setDefenceAudit(r);
          break;
        }
        case "benchmark": {
          const r = await cognitiveApi.listTrainingDrills();
          if (r?.drills) {
            setTrainingDrills(r.drills);
          }
          break;
        }
      }
    } catch (err: unknown) {
      setError((err as Error)?.message || "Engine execution failed.");
    } finally {
      setLoading(false);
    }
  }, [caseId, freezeAccount, freezeTime, selectedSuspectEntity]);

  // Auto-run when engine changes (for non-interactive engines and sandbox initializers)
  useEffect(() => {
    const autoRun: EngineId[] = ["contradictions", "hypotheses", "confidence", "nextbest", "mo", "counterfactual", "replay", "crosscase", "verifier", "defence_bot", "benchmark"];
    if (autoRun.includes(activeEngine)) {
      runEngine(activeEngine);
    }
  }, [activeEngine, caseId, runEngine]);

  const handleEpsilonChange = async (newEps: number) => {
    setConformalEpsilon(newEps);
    setLoading(true);
    setError(null);
    try {
      const r = await cognitiveApi.confidenceMeter(caseId, newEps, selectedSuspectEntity || undefined);
      setConfidenceData(r);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to recalculate conformal confidence.");
    } finally {
      setLoading(false);
    }
  };

  const handleDefenceStressTest = async (overrideClaim?: string) => {
    const textToTest = overrideClaim !== undefined ? overrideClaim : defenceClaim;
    if (!textToTest.trim()) return;
    setDefenceStressLoading(true);
    setError(null);
    try {
      const r = await cognitiveApi.defenceStressTest(caseId, textToTest);
      setDefenceStressResult(r);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Defence stress test failed.");
    } finally {
      setDefenceStressLoading(false);
    }
  };

  const handleCounterfactual = async (overrideAcc?: string, overrideTime?: string) => {
    const acc = overrideAcc || freezeAccount;
    const tim = overrideTime || freezeTime;
    if (!acc.trim() || !tim.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const r = await cognitiveApi.counterfactualFreeze(caseId, acc, tim, [], true, false);
      setCfResult(r);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Counterfactual simulation failed.");
    } finally {
      setLoading(false);
    }
  };

  const handlePresetOffset = (minutes: number) => {
    const baseStr = freezeTime || (cfCandidates[0]?.suggested_freeze_time ?? "");
    if (!baseStr) return;
    try {
      const cleanIso = baseStr.replace("Z", "");
      const dt = new Date(cleanIso.includes("T") ? cleanIso : `${cleanIso}T00:00:00`);
      if (isNaN(dt.getTime())) return;
      dt.setMinutes(dt.getMinutes() + minutes);
      const newIso = dt.toISOString().slice(0, 19);
      setFreezeTime(newIso);
      handleCounterfactual(freezeAccount, newIso);
    } catch {
      // fallback
    }
  };

  const handleVerify = async () => {
    if (!verifyText.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const r = await cognitiveApi.verifyDraft(verifyText, caseId);
      setVerifyResult(r);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Verification failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleBenchmark = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await cognitiveApi.generateBenchmark(benchTypology);
      setBenchmark(r);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Benchmark generation failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleStartTrainingDrill = async (drillId?: string, seed?: number) => {
    setStartingDrill(true);
    setError(null);
    try {
      const targetDrill = drillId || selectedDrillId;
      const res = await cognitiveApi.startTrainingSession(targetDrill, seed);
      setActiveTrainingSession(res);
      setTrainingOfficerAnswers({});
      setTrainingHints(null);
      setShowSolutionModal(false);
      setExportSuccessMessage(null);
      const keys = Object.keys(res.artifacts || {});
      if (keys.length > 0) setTrainingActiveArtifactTab(keys[0]);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to start training session.");
    } finally {
      setStartingDrill(false);
    }
  };

  const handleFetchTrainingHints = async () => {
    if (!activeTrainingSession) return;
    setLoadingHints(true);
    try {
      const res = await cognitiveApi.getTrainingEngineHints(activeTrainingSession.session_id);
      setTrainingHints(res.hints);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to fetch NETRA AI engine hints.");
    } finally {
      setLoadingHints(false);
    }
  };

  const handleSubmitTrainingDrill = async () => {
    if (!activeTrainingSession) return;
    setSubmittingDrill(true);
    try {
      const res = await cognitiveApi.submitTrainingAnswers(activeTrainingSession.session_id, trainingOfficerAnswers);
      setActiveTrainingSession(prev => prev ? { ...prev, is_evaluated: true, evaluation: res.evaluation } : null);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to submit drill answers for evaluation.");
    } finally {
      setSubmittingDrill(false);
    }
  };

  const handleExportTrainingCase = async () => {
    if (!activeTrainingSession) return;
    setExportingCase(true);
    try {
      const res = await cognitiveApi.exportTrainingCase(activeTrainingSession.session_id);
      setExportSuccessMessage(`✓ Exported as sandbox case ${res.case_number} (ID: ${res.case_id.slice(0, 8)}...)`);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to export training case.");
    } finally {
      setExportingCase(false);
    }
  };


  const handleViewDraftNotice = async (action: RankedAction) => {
    setDraftingActionCode(action.action_code);
    try {
      const res = await cognitiveApi.actionDraft(caseId, action.action_code, action.target || {});
      setActiveNoticeModal({
        actionCode: action.action_code,
        noticeText: res.notice_text,
        statute: res.statute,
        banner: res.banner,
      });
    } catch (err: any) {
      setActiveNoticeModal({
        actionCode: action.action_code,
        noticeText: (action.banner || "") + "\n\n" + (action.draft || action.description) + "\n\n" + (action.banner || ""),
        statute: action.statutory_basis || "BNSS, 2023",
        banner: action.banner || "DRAFT — requires IO signature.",
      });
    } finally {
      setDraftingActionCode(null);
    }
  };

  const handleCopyNotice = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedDraft(true);
    setTimeout(() => setCopiedDraft(false), 2000);
  };

  const handleDraftInterStationRequisition = (col: SyndicateCollisionItem) => {
    const linkedCaseNums = col.foreign_cases.map(fc => fc.case_number).join(", ") || "External Cases";
    const tokenShort = col.blind_token.slice(0, 16) + "...";
    const localVal = col.local_anchor.has_local_anchor ? col.local_anchor.plaintext_value : "Identified Case Entity";

    const noticeText = `================================================================================
DRAFT — ZERO-KNOWLEDGE INTER-STATION REQUISITION UNDER SECTION 94 BNSS, 2023
================================================================================

TO:
  The Station House Officer / Investigating Officer
  Linked Case Reference(s): ${linkedCaseNums}

FROM:
  Investigating Officer, Cyber Crime Police Station
  Current Case Reference: ${caseId}

SUBJECT:
  Requisition for Electronic Corroboration & Zero-Knowledge Collision Verification
  Statutory Authority: Section 94, Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023

DETAILS OF CROSS-CASE COLLISION:
  1. Identified Entity Type: ${col.entity_type}
  2. Local Case Plaintext Identifier: ${localVal}
  3. Cryptographic Blind Index Token (HMAC-SHA256): ${tokenShort}
  4. Multi-Case Collision Count: Present across ${col.case_count} distinct cases
  5. Syndicate Ingress Score: ${col.syndicate_score}

STATUTORY REQUISITION:
  Whereas in the investigation of the above-referenced case, the cryptographic blind
  index has established a mathematical match between an active entity in our jurisdiction
  and suspect records in your station's ongoing case file(s) [${linkedCaseNums}];

  Now, therefore, in exercise of powers under Section 94 BNSS, 2023, you are hereby requested
  to furnish verified account statements, CDR/IPDR corroboration, and suspect KYC records
  associated with this identified identifier to establish syndicate nexus and coordinated
  fund dissipation.

  Dated: ${new Date().toLocaleDateString("en-IN")}
  Investigating Officer (Cyber Crime)
================================================================================
NOTE: Generated via CyberDrishti Syndicate Radar. Requires IO signature prior to transmission.`;

    setActiveNoticeModal({
      actionCode: "INTER_STATION_SEC_94",
      statute: "Section 94 BNSS (Inter-Station Requisition)",
      noticeText,
      banner: "DRAFT — Inter-Station Coordination Notice under Section 94 BNSS.",
    });
  };

  const handleSelectSuspect = async (entityVal: string) => {
    setSelectedSuspectEntity(entityVal);
    setLoading(true);
    setError(null);
    try {
      const r = await cognitiveApi.hypotheses(caseId, entityVal);
      setHypotheses(r);
      if (r.observations) {
        setWhatIfInputs({ ...r.observations });
      }
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to load hypotheses for selected entity");
    } finally {
      setLoading(false);
    }
  };

  const handleRunWhatIf = async () => {
    if (!hypotheses) return;
    setWhatIfLoading(true);
    try {
      const r = await cognitiveApi.evaluateHypothesisWhatIf(caseId, {
        target_entity: selectedSuspectEntity || hypotheses.target_entity || undefined,
        observations: whatIfInputs,
      });
      setHypotheses(r);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to run what-if simulation");
    } finally {
      setWhatIfLoading(false);
    }
  };

  const handleResetWhatIf = async () => {
    if (selectedSuspectEntity) {
      await handleSelectSuspect(selectedSuspectEntity);
    } else {
      await runEngine("hypotheses");
    }
  };

  const handleGenerateReport = async () => {
    if (!hypotheses) return;
    setGeneratingReport(true);
    try {
      const leading = hypotheses.ranked_labels && hypotheses.ranked_labels.length > 0
        ? hypotheses.ranked_labels[0]
        : (hypotheses.display_label || "LAYER1_MULE");
      const r = await cognitiveApi.generateHypothesisReport(caseId, {
        target_entity: selectedSuspectEntity || hypotheses.target_entity || undefined,
        leading_hypothesis: leading,
        police_station: hypotheses.police_station || undefined,
      });
      setHypothesisReportModal(r);
      setCopiedReport(false);
    } catch (err: unknown) {
      setError((err as Error)?.message || "Failed to generate Section 193 BNSS memorandum");
    } finally {
      setGeneratingReport(false);
    }
  };

  const handleCopyReport = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedReport(true);
    setTimeout(() => setCopiedReport(false), 3000);
  };

  const handleThresholdChange = async (newThreshold: number) => {
    setMoThreshold(newThreshold);
    try {
      const r = await cognitiveApi.moFingerprint(caseId, newThreshold, selectedScriptPlaybook || undefined);
      setMoResult(r);
    } catch {
      // non-fatal
    }
  };

  const handleRunAdhocScript = async () => {
    if (!adhocTranscript.trim()) return;
    setAdhocRunning(true);
    try {
      const r = await cognitiveApi.classifyMoScript(caseId, {
        text_content: adhocTranscript,
        threshold: moThreshold,
        playbook: selectedScriptPlaybook || undefined,
      });
      setAdhocResult(r);
    } catch {
      // non-fatal
    } finally {
      setAdhocRunning(false);
    }
  };

  const currentEngine = ENGINES.find(e => e.id === activeEngine)!;
  const analysisEngines = ENGINES.filter(e => e.id !== "benchmark");
  const validationEngines = ENGINES.filter(e => e.id === "benchmark");

  return (
    <div className={s.cogRoot}>
      {/* Primary experience: what NETRA found about this case. */}
      <CaseIntelligence caseId={caseId} />

      {/* Secondary: per-engine drill-down for the findings above. */}
      <div>
        <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>Engine detail</div>
        <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", margin: 0 }}>
          Run an individual engine to inspect the raw output behind the findings.
        </p>
      </div>

      {/* Engine Selector Ribbon */}
      <nav className={s.selectorRibbon} aria-label="Cognitive engines">
        {analysisEngines.map(eng => (
          <button
            key={eng.id}
            className={activeEngine === eng.id ? s.engineChipActive : s.engineChip}
            onClick={() => setActiveEngine(eng.id)}
            title={eng.desc}
          >
            <span>{eng.icon}</span>
            <span>{eng.label}</span>
          </button>
        ))}
      </nav>

      {/* System validation stays separate from the investigation flow. */}
      <nav className={s.selectorRibbon} aria-label="System validation">
        <span style={{ alignSelf: "center", padding: "0 var(--space-3)", font: "var(--type-mono-xs)", color: "var(--text-muted)", letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap" }}>
          System validation
        </span>
        {validationEngines.map(eng => (
          <button
            key={eng.id}
            className={activeEngine === eng.id ? s.engineChipActive : s.engineChip}
            onClick={() => setActiveEngine(eng.id)}
            title={eng.desc}
          >
            <span>{eng.icon}</span>
            <span>{eng.label}</span>
          </button>
        ))}
      </nav>

      {/* Panel */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeEngine}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
          className={s.panel}
        >
          <div className={s.panelHeader}>
            <div className={s.panelHeaderLeft}>
              <span className={s.engineBadge}>
                <span>{currentEngine.icon}</span>
                F{String(ENGINES.indexOf(currentEngine) + 2).padStart(2, "0")}
              </span>
              <div>
                <h3 className={s.panelTitle}>{currentEngine.label}</h3>
                <p className={s.panelSubtitle}>{currentEngine.desc}</p>
              </div>
            </div>
            {["contradictions", "hypotheses", "nextbest", "mo", "replay", "crosscase", "verifier", "defence_bot"].includes(activeEngine) && (
              <Button variant="secondary" onClick={() => runEngine(activeEngine)} disabled={loading}>
                {loading ? "Running…" : "Refresh"}
              </Button>
            )}
          </div>

          <div className={s.panelBody}>
            {error && (
              <div style={{ padding: "var(--space-4)", background: "var(--critical-tint)", border: "1px solid rgba(255,92,92,0.3)", borderRadius: "var(--radius-input)", marginBottom: "var(--space-4)", color: "var(--critical)", font: "var(--type-body-sm)" }}>
                {error}
              </div>
            )}

            {loading ? (
              <div className={s.loading}>
                <div className={s.spinner} />
                <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                  Running {currentEngine.label} engine…
                </span>
              </div>
            ) : (
              <>
                {/* ── Contradictions Panel ─────────────────────────── */}
                {activeEngine === "contradictions" && (
                  contradictions ? (
                    <div>
                      <div className={s.cardGrid}>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Ledger Rows Audited</div>
                          <div className={s.cardValue}>{contradictions.ledger_audit.input_rows}</div>
                        </div>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Balance Breaks</div>
                          <div className={s.cardValue} style={{ color: contradictions.ledger_audit.findings.length > 0 ? "var(--critical)" : "var(--verified)" }}>
                            {contradictions.ledger_audit.findings.length}
                          </div>
                        </div>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Entities Profiled</div>
                          <div className={s.cardValue} style={{ color: "var(--accent)" }}>
                            {contradictions.anomaly_summary?.total_entities_profiled ?? Object.keys(contradictions.entity_profiles || {}).length}
                          </div>
                        </div>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Behavioral Anomalies</div>
                          <div className={s.cardValue} style={{ color: ((contradictions.behavioral_anomalies?.length || 0) + contradictions.impossible_travel.findings.length) > 0 ? "var(--warning)" : "var(--verified)" }}>
                            {(contradictions.behavioral_anomalies?.length || 0) + contradictions.impossible_travel.findings.length}
                          </div>
                        </div>
                      </div>

                      {/* ── Behavioral Anomalies Section ── */}
                      {contradictions.behavioral_anomalies && contradictions.behavioral_anomalies.length > 0 && (
                        <div style={{ marginTop: "var(--space-6)" }}>
                          <div className="t-label" style={{ marginBottom: "var(--space-3)", display: "flex", alignItems: "center", gap: "8px" }}>
                            <span>Behavioral Anomalies & Baselines</span>
                            <span style={{ fontSize: "11px", color: "var(--text-muted)", fontStyle: "italic" }}>
                              (Empirical deviations from baseline · Zero presumption of guilt)
                            </span>
                          </div>
                          {contradictions.behavioral_anomalies.map((f, i) => (
                            <div key={i} className={s.findingRow}>
                              <div className={f.severity === "CRITICAL" ? s.findingSeverityCritical : s.findingSeverityWarning} />
                              <div className={s.findingBody}>
                                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                  <span className={s.findingKind} style={{ color: f.severity === "CRITICAL" ? "var(--critical)" : "var(--warning)" }}>
                                    {f.anomaly_type.replace(/_/g, " ")}
                                  </span>
                                  <span style={{ fontSize: "10px", padding: "1px 6px", borderRadius: "4px", background: "rgba(255,255,255,0.06)", color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                                    {f.epistemic_status}
                                  </span>
                                </div>
                                <div className={s.findingText} style={{ marginTop: "4px" }}>{f.description}</div>
                                <div className={s.findingMeta}>
                                  Entity: <strong style={{ color: "var(--text-primary)" }}>{f.entity}</strong>
                                  {f.component_scores.z_score !== undefined && ` · Z-Score: ${f.component_scores.z_score} (sample N=${f.component_scores.sample_size_n})`}
                                  {f.component_scores.time_gap_minutes !== undefined && ` · Turnaround: ${f.component_scores.time_gap_minutes}m (${(f.component_scores.turnover_ratio * 100).toFixed(0)}% drained)`}
                                  {f.component_scores.velocity_kmh !== undefined && ` · Lower-bound speed: ${f.component_scores.velocity_kmh} km/h`}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* ── Entity Behavioral Profiles Deck ── */}
                      {contradictions.entity_profiles && Object.keys(contradictions.entity_profiles).length > 0 && (
                        <div style={{ marginTop: "var(--space-6)" }}>
                          <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Entity Behavioral Baseline Profiles</div>
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "12px" }}>
                            {Object.values(contradictions.entity_profiles).map((p, i) => (
                              <div key={i} style={{ background: "rgba(255, 255, 255, 0.02)", border: "1px solid var(--line)", borderRadius: "var(--radius-md)", padding: "12px" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                                  <span style={{ fontWeight: 600, color: "var(--text-primary)", fontSize: "13px" }}>{p.entity}</span>
                                  <span style={{ fontSize: "10px", padding: "2px 6px", borderRadius: "4px", background: p.baseline_status === "established" ? "rgba(35, 134, 54, 0.15)" : "rgba(255, 255, 255, 0.05)", color: p.baseline_status === "established" ? "var(--verified)" : "var(--text-muted)" }}>
                                    {p.baseline_status === "established" ? "BASELINE ACTIVE" : "LOW SAMPLE"}
                                  </span>
                                </div>
                                <div style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "11px", color: "var(--text-secondary)" }}>
                                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                                    <span>Type / Txns:</span>
                                    <span style={{ color: "var(--text-primary)" }}>{p.entity_type} ({p.txn_count} txns)</span>
                                  </div>
                                  {p.txn_count > 0 && (
                                    <>
                                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                                        <span>Mean Amount:</span>
                                        <span style={{ color: "var(--text-primary)" }}>₹{p.mean_amount.toLocaleString()}</span>
                                      </div>
                                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                                        <span>Max Amount:</span>
                                        <span style={{ color: "var(--text-primary)" }}>₹{p.max_amount.toLocaleString()}</span>
                                      </div>
                                    </>
                                  )}
                                  {p.min_pass_through_min !== null && p.min_pass_through_min !== undefined && (
                                    <div style={{ display: "flex", justifyContent: "space-between", color: "var(--warning)" }}>
                                      <span>Pass-through Turnaround:</span>
                                      <strong>{p.min_pass_through_min} min</strong>
                                    </div>
                                  )}
                                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                                    <span>Daytime / Off-Hours:</span>
                                    <span>{p.daytime_count} daytime · {p.off_hours_count} night ({((p.off_hours_ratio || 0) * 100).toFixed(0)}%)</span>
                                  </div>
                                  {p.locations_seen && p.locations_seen.length > 0 && (
                                    <div style={{ display: "flex", justifyContent: "space-between", marginTop: "2px" }}>
                                      <span>Locations:</span>
                                      <span style={{ color: "var(--accent)" }}>{p.locations_seen.slice(0, 2).join(", ")}{p.locations_seen.length > 2 ? ` +${p.locations_seen.length - 2}` : ""}</span>
                                    </div>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* ── Ledger Breaks ── */}
                      {contradictions.ledger_audit.findings.length > 0 && (
                        <div style={{ marginTop: "var(--space-6)" }}>
                          <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Ledger Anomalies</div>
                          {contradictions.ledger_audit.findings.map((f, i) => (
                            <div key={i} className={s.findingRow}>
                              <div className={s.findingSeverityCritical} />
                              <div className={s.findingBody}>
                                <div className={s.findingKind} style={{ color: "var(--critical)" }}>{f.kind}</div>
                                <div className={s.findingText}>{f.explanation}</div>
                                <div className={s.findingMeta}>
                                  Row {f.row_index} · Expected ₹{f.expected_balance?.toLocaleString()} · Reported ₹{f.reported_balance?.toLocaleString()} · Gap ₹{f.discrepancy?.toLocaleString()}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* ── Impossible Travel ── */}
                      {contradictions.impossible_travel.findings.length > 0 && (
                        <div style={{ marginTop: "var(--space-6)" }}>
                          <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Impossible Travel Detections</div>
                          {contradictions.impossible_travel.findings.map((f, i) => (
                            <div key={i} className={s.findingRow}>
                              <div className={s.findingSeverityWarning} />
                              <div className={s.findingBody}>
                                <div className={s.findingKind} style={{ color: "var(--warning)" }}>{f.kind}</div>
                                <div className={s.findingText}>{f.explanation}</div>
                                <div className={s.findingMeta}>
                                  {f.entity} · {f.distance_km?.toFixed(1)}km in {f.time_gap_s}s ({f.velocity_kmh?.toFixed(0)} km/h)
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {contradictions.ledger_audit.findings.length === 0 &&
                       contradictions.impossible_travel.findings.length === 0 &&
                       (!contradictions.behavioral_anomalies || contradictions.behavioral_anomalies.length === 0) && (
                        <div className={s.emptyState} style={{ marginTop: "var(--space-6)" }}>
                          <div className={s.emptyIcon}>✅</div>
                          <div style={{ font: "var(--type-body)", color: "var(--verified)" }}>No contradictions or behavioral anomalies detected</div>
                          <div style={{ font: "var(--type-body-sm)" }}>All ledger rows pass continuity checks. Activity adheres to established baselines.</div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className={s.emptyState}>
                      <div className={s.emptyIcon}>⚡</div>
                      <div>No contradiction data available</div>
                      <div style={{ font: "var(--type-body-sm)" }}>Upload bank statements, CDRs, and location timelines to enable behavioral profiling and travel checks.</div>
                    </div>
                  )
                )}

                {/* ── Feature 04: Hypothesis Investigation Board ────────────────── */}
                {activeEngine === "hypotheses" && (
                  hypotheses ? (
                    <div>
                      {/* Suspect Candidate Selector */}
                      {hypotheses.candidates && hypotheses.candidates.length > 0 && (
                        <div className={s.hypoCandidateBar}>
                          <span className={s.hypoCandidateLabel}>🎯 Suspect Target:</span>
                          {hypotheses.candidates.map(cand => {
                            const isSelected = selectedSuspectEntity === cand.value || (!selectedSuspectEntity && hypotheses.target_entity === cand.value);
                            return (
                              <button
                                key={cand.id || cand.value}
                                type="button"
                                className={isSelected ? s.hypoCandidateChipActive : s.hypoCandidateChip}
                                onClick={() => handleSelectSuspect(cand.value)}
                                title={`Centrality Degree: ${cand.degree} | Role: ${cand.role_hint}`}
                              >
                                <span>
                                  {cand.entity_type === "PHONE" ? "📱" :
                                   cand.entity_type === "UPI" ? "⚡" :
                                   cand.entity_type === "ACCOUNT" ? "💳" :
                                   cand.entity_type === "IP" ? "🌐" : "👤"}
                                </span>
                                <strong>{cand.value}</strong>
                                {cand.role_hint && (
                                  <span style={{ opacity: 0.8, fontSize: "10px" }}>({cand.role_hint})</span>
                                )}
                                <span style={{ fontSize: "10px", opacity: 0.65 }}>
                                  Deg: {cand.degree}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {/* R v T [2010] & Section 193 BNSS Epistemic Notice */}
                      <div className={s.rvtBanner}>
                        <div style={{ fontSize: "22px", flexShrink: 0 }}>⚖️</div>
                        <div>
                          <div className={s.rvtBannerTitle}>
                            R v T [2010] EWCA Crim 2439 & Section 193 BNSS Forensic Standard
                          </div>
                          <div className={s.rvtBannerDesc}>
                            {hypotheses.epistemic_notice || (
                              "Under Richards Heuer's Analysis of Competing Hypotheses (ACH), investigative weight is determined by refuting inconsistencies rather than subjective belief. To eliminate confirmation bias and prevent fabricated probabilities, NETRA outputs rule-based rankings rather than uncalibrated percentage likelihoods."
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Action & Status Row */}
                      <div className={s.hypoActionRow}>
                        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap" }}>
                          <div>
                            <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase" }}>Target Entity: </span>
                            <strong style={{ font: "var(--type-mono-xs)", color: "var(--accent)" }}>{hypotheses.target_entity || "Primary Case Subject"}</strong>
                          </div>
                          <div style={{ width: "1px", height: "16px", background: "var(--line)" }} />
                          <div>
                            <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase" }}>Leading Theory: </span>
                            <span className={s.hypoRankBadgeLeading}>{hypotheses.display_label || "LAYER1_MULE"}</span>
                          </div>
                          <div style={{ width: "1px", height: "16px", background: "var(--line)" }} />
                          <div>
                            <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase" }}>Assessment: </span>
                            <span style={{ font: "var(--type-mono-xs)", color: "var(--text-secondary)" }}>{hypotheses.assessment_type}</span>
                          </div>
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                          <Button
                            variant="secondary"
                            onClick={() => setWhatIfMode(!whatIfMode)}
                          >
                            🧪 {whatIfMode ? "Hide What-If Sandbox" : "What-If Sandbox"}
                          </Button>
                          <Button
                            variant="primary"
                            onClick={handleGenerateReport}
                            disabled={generatingReport}
                          >
                            {generatingReport ? "Drafting Memo..." : "📄 Draft Sec. 193 BNSS Memo"}
                          </Button>
                        </div>
                      </div>

                      {/* Interactive What-If Simulation Sandbox */}
                      {whatIfMode && (
                        <div className={s.whatIfPanel}>
                          <div className={s.whatIfHeader}>
                            <div>
                              <div style={{ font: "var(--type-body)", fontWeight: 700, color: "var(--text-primary)" }}>
                                🧪 Interactive Counterfactual Indicator Sandbox
                              </div>
                              <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginTop: 2 }}>
                                Adjust forensic indicator values to simulate how suspect role rankings shift across competing theories.
                              </div>
                            </div>
                            <div style={{ display: "flex", gap: "var(--space-2)" }}>
                              <Button
                                variant="secondary"
                                onClick={handleResetWhatIf}
                                disabled={whatIfLoading}
                              >
                                ↺ Reset
                              </Button>
                              <Button
                                variant="primary"
                                onClick={handleRunWhatIf}
                                disabled={whatIfLoading}
                              >
                                {whatIfLoading ? "Simulating..." : "⚡ Simulate Theory Shift"}
                              </Button>
                            </div>
                          </div>

                          <div className={s.whatIfInputsGrid}>
                            <div className={s.whatIfInputGroup}>
                              <label className={s.whatIfInputLabel}>Pass-Through Speed (Minutes)</label>
                              <input
                                type="number"
                                step="1"
                                className={s.whatIfInput}
                                value={whatIfInputs.velocity_minutes ?? 10}
                                onChange={e => setWhatIfInputs({ ...whatIfInputs, velocity_minutes: parseFloat(e.target.value) || 0 })}
                              />
                            </div>
                            <div className={s.whatIfInputGroup}>
                              <label className={s.whatIfInputLabel}>Account Age (Days)</label>
                              <input
                                type="number"
                                step="1"
                                className={s.whatIfInput}
                                value={whatIfInputs.account_age_days ?? 15}
                                onChange={e => setWhatIfInputs({ ...whatIfInputs, account_age_days: parseFloat(e.target.value) || 0 })}
                              />
                            </div>
                            <div className={s.whatIfInputGroup}>
                              <label className={s.whatIfInputLabel}>Inbound Victim Calls (Count)</label>
                              <input
                                type="number"
                                step="1"
                                className={s.whatIfInput}
                                value={whatIfInputs.inbound_victim_calls ?? 0}
                                onChange={e => setWhatIfInputs({ ...whatIfInputs, inbound_victim_calls: parseFloat(e.target.value) || 0 })}
                              />
                            </div>
                            <div className={s.whatIfInputGroup}>
                              <label className={s.whatIfInputLabel}>Dormancy Before Crime (Days)</label>
                              <input
                                type="number"
                                step="1"
                                className={s.whatIfInput}
                                value={whatIfInputs.dormancy_before_crime_days ?? 0}
                                onChange={e => setWhatIfInputs({ ...whatIfInputs, dormancy_before_crime_days: parseFloat(e.target.value) || 0 })}
                              />
                            </div>
                            <div className={s.whatIfInputGroup}>
                              <label className={s.whatIfInputLabel}>Device Sharing (Count)</label>
                              <input
                                type="number"
                                step="1"
                                className={s.whatIfInput}
                                value={whatIfInputs.device_sharing_count ?? 1}
                                onChange={e => setWhatIfInputs({ ...whatIfInputs, device_sharing_count: parseFloat(e.target.value) || 0 })}
                              />
                            </div>
                            <div className={s.whatIfInputGroup}>
                              <label className={s.whatIfInputLabel}>Turnover Scale (INR)</label>
                              <input
                                type="number"
                                step="10000"
                                className={s.whatIfInput}
                                value={whatIfInputs.turnover_volume_inr ?? 250000}
                                onChange={e => setWhatIfInputs({ ...whatIfInputs, turnover_volume_inr: parseFloat(e.target.value) || 0 })}
                              />
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Competing Suspect Role Hypotheses Grid */}
                      <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>
                        Competing Suspect Role Hypotheses (Ranked by Minimum Inconsistency)
                      </div>
                      <div className={s.hypoDeckGrid}>
                        {hypotheses.hypotheses.map((h, i) => {
                          const isLeading = i === 0;
                          return (
                            <div key={h.label} className={isLeading ? s.hypoCardLeading : s.hypoCard}>
                              <div className={s.hypoCardHeader}>
                                <span className={isLeading ? s.hypoRankBadgeLeading : s.hypoRankBadgeOther}>
                                  {isLeading ? "👑 #1 Leading Theory" : `#${i + 1}`}
                                </span>
                                <span className={s.metaCategory} style={{
                                  background: h.classification === "SUSPECT" ? "rgba(255, 68, 68, 0.15)" :
                                              h.classification === "MULE" ? "rgba(255, 170, 0, 0.15)" :
                                              h.classification === "VICTIM" ? "rgba(46, 204, 113, 0.15)" : "rgba(88, 166, 255, 0.15)",
                                  color: h.classification === "SUSPECT" ? "#ff6b6b" :
                                         h.classification === "MULE" ? "#ffaa00" :
                                         h.classification === "VICTIM" ? "#2ecc71" : "#58a6ff",
                                  border: "1px solid currentColor"
                                }}>
                                  {h.classification || "ROLE"}
                                </span>
                              </div>

                              <div className={s.hypoRoleTitle}>{h.label}</div>
                              <div className={s.hypoRoleDesc}>{h.description}</div>

                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", font: "var(--type-mono-xs)", color: "var(--text-muted)", borderTop: "1px solid var(--line)", paddingTop: "var(--space-2)" }}>
                                <span>Inconsistency Score:</span>
                                <strong style={{ color: isLeading ? "#ffaa00" : "var(--text-primary)" }}>
                                  {typeof h.inconsistency_score === "number" ? h.inconsistency_score.toFixed(3) : "—"}
                                </strong>
                              </div>

                              {h.refuting_evidence ? (
                                <div className={s.hypoRefuteCallout}>
                                  <strong>⚠️ Refuting Evidence:</strong> {h.refuting_evidence.indicator} ({h.refuting_evidence.bucket})
                                  <div style={{ marginTop: 2, opacity: 0.85, fontSize: "11px" }}>
                                    Likelihood under this role: <strong>{h.refuting_evidence.likelihood_under_this_hypothesis ?? h.refuting_evidence.likelihood}</strong>
                                    {h.refuting_evidence.why && ` — ${h.refuting_evidence.why}`}
                                  </div>
                                </div>
                              ) : (
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--verified)", padding: "4px 8px", background: "rgba(46, 204, 113, 0.08)", borderRadius: "var(--radius-input)", border: "1px solid rgba(46, 204, 113, 0.2)" }}>
                                  ✓ No refuting inconsistencies observed
                                </div>
                              )}

                              {h.supporting_evidence && (
                                <div className={s.hypoSupportCallout}>
                                  <strong>🛡️ Strongest Support:</strong> {h.supporting_evidence.indicator} ({h.supporting_evidence.bucket})
                                  <div style={{ marginTop: 2, opacity: 0.85, fontSize: "11px" }}>
                                    Likelihood: <strong>{h.supporting_evidence.likelihood}</strong>
                                    {h.supporting_evidence.why && ` — ${h.supporting_evidence.why}`}
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>

                      {/* Richards Heuer's ACH Evidence & Diagnosticity Matrix */}
                      {hypotheses.evidence_matrix && hypotheses.evidence_matrix.length > 0 && (
                        <div style={{ marginBottom: "var(--space-6)" }}>
                          <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>
                            Richards Heuer's ACH Evidence & Diagnosticity Matrix
                          </div>
                          <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-3)" }}>
                            Forensic indicators observed in case records mapped against all competing theories.
                            Columns represent hypotheses; cells indicate conditional probability (<strong>++</strong> &ge; 0.70, <strong>+</strong> 0.30–0.69, <strong>-</strong> 0.11–0.29, <strong>--</strong> &le; 0.10 refuting).
                          </p>

                          <div className={s.achTableContainer}>
                            <table className={s.achTable}>
                              <thead>
                                <tr>
                                  <th>Forensic Indicator & Provenance</th>
                                  <th>Observed Value</th>
                                  <th>Bucket</th>
                                  <th>Diagnosticity (Δ)</th>
                                  {hypotheses.hypotheses.map(h => (
                                    <th key={h.label} style={{ textAlign: "center" }}>
                                      {h.label.replace(/_/g, " ")}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {hypotheses.evidence_matrix.map(row => {
                                  const diagDelta = row.diagnosticity;
                                  const diagClass = diagDelta >= 0.70 ? s.diagnosticityHigh :
                                                    diagDelta >= 0.40 ? s.diagnosticityMod : s.diagnosticityLow;
                                  const diagLabel = diagDelta >= 0.70 ? `High (Δ ${diagDelta.toFixed(2)})` :
                                                    diagDelta >= 0.40 ? `Mod (Δ ${diagDelta.toFixed(2)})` : `Low (Δ ${diagDelta.toFixed(2)})`;
                                  return (
                                    <tr key={row.indicator}>
                                      <td>
                                        <strong style={{ color: "var(--text-primary)" }}>{row.indicator}</strong>
                                        {row.provenance && (
                                          <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: 2 }}>
                                            📂 {row.provenance.source_file || "Evidence File"}
                                            {row.provenance.source_line ? ` : L${row.provenance.source_line}` : ""}
                                            {row.provenance.event_type ? ` [${row.provenance.event_type}]` : ""}
                                          </div>
                                        )}
                                      </td>
                                      <td style={{ font: "var(--type-mono-xs)" }}>
                                        {typeof row.observed_value === "number" ? row.observed_value.toLocaleString() : row.observed_value}
                                      </td>
                                      <td>
                                        <span className={s.metaCategory}>{row.bucket}</span>
                                      </td>
                                      <td>
                                        <span className={diagClass}>{diagLabel}</span>
                                      </td>
                                      {hypotheses.hypotheses.map(h => {
                                        const val = row.likelihoods?.[h.label] ?? 0;
                                        const cellClass = val <= 0.10 ? s.achCellRefuting :
                                                          val <= 0.29 ? s.achCellInconsistent :
                                                          val >= 0.70 ? s.achCellStrong : s.achCellConsistent;
                                        const cellSymbol = val <= 0.10 ? "--" :
                                                           val <= 0.29 ? "-" :
                                                           val >= 0.70 ? "++" : "+";
                                        return (
                                          <td key={h.label} style={{ textAlign: "center" }}>
                                            <span className={cellClass} title={`P(${row.indicator} | ${h.label}) = ${val}`}>
                                              {cellSymbol} ({val.toFixed(2)})
                                            </span>
                                          </td>
                                        );
                                      })}
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      {/* Statutory Evidence Gaps & Actions */}
                      {hypotheses.unobserved_details && hypotheses.unobserved_details.length > 0 && (
                        <div style={{ marginTop: "var(--space-6)" }}>
                          <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>
                            📋 Statutory Evidence Gaps & Investigative Actions (Section 193 BNSS)
                          </div>
                          <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-3)" }}>
                            Under Section 193 BNSS, unobserved indicators must not be imputed. Issue statutory notices to obtain primary records:
                          </p>

                          <div className={s.cardGrid}>
                            {hypotheses.unobserved_details.map(gap => (
                              <div key={gap.indicator} className={s.dataCard} style={{ borderLeft: "3px solid var(--warning)" }}>
                                <div className={s.cardLabel}>UNOBSERVED INDICATOR</div>
                                <div style={{ font: "var(--type-body)", fontWeight: 700, color: "var(--text-primary)", marginBottom: "var(--space-1)" }}>
                                  {gap.indicator}
                                </div>
                                <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-2)" }}>
                                  <strong>Required Evidence:</strong> {gap.required_evidence}
                                </div>
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--warning)", background: "rgba(255, 170, 0, 0.08)", padding: "4px 8px", borderRadius: "var(--radius-input)", marginBottom: "var(--space-2)" }}>
                                  <strong>Potential Impact:</strong> {gap.potential_impact}
                                </div>
                                {gap.note && (
                                  <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)" }}>
                                    ⚡ {gap.note}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className={s.emptyState}>
                      <div className={s.emptyIcon}>🎯</div>
                      <div>No hypothesis data available</div>
                      <div style={{ font: "var(--type-body-sm)" }}>Upload evidence to enable ACH suspect role classification.</div>
                    </div>
                  )
                )}

                {/* ── Feature 05: Confidence Meter & Evidentiary State Analyzer ── */}
                {activeEngine === "confidence" && (
                  confidenceData ? (
                    <div className={s.confidenceMeterRoot}>
                      {/* Evidentiary Health HUD */}
                      <div className={s.confidenceHealthHud}>
                        <div className={s.confidenceHealthTop}>
                          <div>
                            <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                              Case Evidentiary Health Index
                            </div>
                            <div className={s.confidenceScoreGauge}>
                              <span className={
                                confidenceData.overall_verdict === "ROBUST_CORROBORATED" ? s.confidenceScoreNumRobust :
                                confidenceData.overall_verdict === "PROCEED_WITH_CAUTION" ? s.confidenceScoreNumCaution :
                                s.confidenceScoreNumUncertain
                              }>
                                {Math.round(confidenceData.overall_evidentiary_health_score * 100)}%
                              </span>
                              <span className={
                                confidenceData.overall_verdict === "ROBUST_CORROBORATED" ? `${s.verdictBadge} ${s.verdictRobust}` :
                                confidenceData.overall_verdict === "PROCEED_WITH_CAUTION" ? `${s.verdictBadge} ${s.verdictCaution}` :
                                `${s.verdictBadge} ${s.verdictUncertain}`
                              }>
                                {confidenceData.overall_verdict.replace(/_/g, " ")}
                              </span>
                            </div>
                          </div>

                          <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
                            <div className={s.dataCard} style={{ padding: "var(--space-3) var(--space-4)" }}>
                              <div className={s.cardLabel}>Corroboration</div>
                              <div style={{ font: "var(--type-title-3)", color: "var(--verified, #10b981)" }}>
                                {confidenceData.findings_audit.multi_source_corroborated} / {confidenceData.findings_audit.total_findings}
                              </div>
                              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>Multi-source verified</div>
                            </div>
                            <div className={s.dataCard} style={{ padding: "var(--space-3) var(--space-4)" }}>
                              <div className={s.cardLabel}>Contradictions</div>
                              <div style={{ font: "var(--type-title-3)", color: confidenceData.findings_audit.contradiction_burdened > 0 ? "var(--critical, #ef4444)" : "var(--text-secondary)" }}>
                                {confidenceData.findings_audit.contradiction_burdened} / {confidenceData.findings_audit.total_findings}
                              </div>
                              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>Burdened findings</div>
                            </div>
                            <div className={s.dataCard} style={{ padding: "var(--space-3) var(--space-4)" }}>
                              <div className={s.cardLabel}>Active Calibrations</div>
                              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                                <div style={{ font: "var(--type-title-3)", color: "var(--accent)" }}>
                                  {calibrationsList.length || 3}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => setShowCalibrationModal(true)}
                                  className={s.epsilonChip}
                                  style={{ fontSize: "11px", padding: "2px 6px" }}
                                >
                                  Inspect Distributions
                                </button>
                              </div>
                              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>Split-conformal models</div>
                            </div>
                          </div>
                        </div>

                        {/* Health Meter Track */}
                        <div className={s.healthMeterTrack}>
                          <div
                            className={s.healthMeterFill}
                            style={{
                              width: `${Math.round(confidenceData.overall_evidentiary_health_score * 100)}%`,
                              background: confidenceData.overall_verdict === "ROBUST_CORROBORATED" ? "var(--verified, #10b981)" :
                                          confidenceData.overall_verdict === "PROCEED_WITH_CAUTION" ? "var(--warning, #f59e0b)" :
                                          "var(--critical, #ef4444)",
                            }}
                          />
                        </div>

                        {/* Interactive Conformal Epsilon Selector */}
                        <div className={s.conformalEpsilonBar}>
                          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                            <span style={{ font: "var(--type-mono-xs)", color: "var(--text-secondary)", textTransform: "uppercase" }}>
                              Target Marginal Coverage Guarantee (1 - ε):
                            </span>
                            <span style={{ font: "var(--type-mono-xs)", color: "var(--accent)", fontWeight: 600 }}>
                              {Math.round((1 - conformalEpsilon) * 100)}% Coverage (ε = {conformalEpsilon})
                            </span>
                          </div>
                          <div className={s.conformalEpsilonGroup}>
                            <button
                              type="button"
                              className={conformalEpsilon === 0.10 ? s.epsilonChipActive : s.epsilonChip}
                              onClick={() => handleEpsilonChange(0.10)}
                            >
                              90% Coverage (ε=0.10)
                            </button>
                            <button
                              type="button"
                              className={conformalEpsilon === 0.05 ? s.epsilonChipActive : s.epsilonChip}
                              onClick={() => handleEpsilonChange(0.05)}
                            >
                              95% Coverage (ε=0.05 Default)
                            </button>
                            <button
                              type="button"
                              className={conformalEpsilon === 0.01 ? s.epsilonChipActive : s.epsilonChip}
                              onClick={() => handleEpsilonChange(0.01)}
                            >
                              99% Coverage (ε=0.01 High Burden)
                            </button>
                          </div>
                        </div>
                      </div>

                      {/* R v T [2010] & Section 193 BNSS Statutory Judicial Notice */}
                      <div className={s.judicialNoticeBox}>
                        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: 4 }}>
                          <span style={{ fontSize: "16px" }}>⚖️</span>
                          <strong style={{ color: "var(--text-primary)" }}>
                            Judicial Epistemic Integrity Notice (R v T [2010] EWCA Crim 2439 & Section 193 BNSS)
                          </strong>
                        </div>
                        <div>{confidenceData.judicial_notices.rvt_compliance}</div>
                        <div style={{ marginTop: 6, font: "var(--type-mono-xs)", color: "var(--warning, #f59e0b)" }}>
                          ⚠️ {confidenceData.judicial_notices.synthetic_calibration_warning}
                        </div>
                      </div>

                      {/* Suspect Role Conformal Prediction Sets */}
                      {confidenceData.suspect_role_conformal_sets && confidenceData.suspect_role_conformal_sets.length > 0 && (
                        <div>
                          <h4 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", margin: "0 0 var(--space-3)" }}>
                            🎯 Suspect Role Split-Conformal Prediction Sets
                          </h4>
                          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                            {confidenceData.suspect_role_conformal_sets.map(sSet => (
                              <div key={sSet.target_entity} className={s.suspectConformalCard}>
                                <div className={s.suspectConformalHeader}>
                                  <div>
                                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase" }}>Target Subject: </span>
                                    <strong style={{ font: "var(--type-mono-sm)", color: "var(--accent)" }}>{sSet.target_entity}</strong>
                                  </div>
                                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                                    <span className={sSet.verdict === "SINGLE_LABEL" ? s.predictionSetPill : s.predictionSetPillAmbiguous}>
                                      Verdict: {sSet.verdict}
                                    </span>
                                    <span style={{
                                      padding: "2px 6px",
                                      borderRadius: 4,
                                      font: "var(--type-mono-xs)",
                                      background: sSet.valid_for_real_data ? "rgba(16, 185, 129, 0.12)" : "rgba(245, 158, 11, 0.12)",
                                      color: sSet.valid_for_real_data ? "#10b981" : "#f59e0b",
                                      border: "1px solid currentColor"
                                    }}>
                                      {sSet.valid_for_real_data ? "Certified Real Evidence" : "Synthetic Benchmark Only"}
                                    </span>
                                  </div>
                                </div>

                                <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                                  {sSet.message}
                                </div>

                                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", flexWrap: "wrap" }}>
                                  <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>Prediction Set C(X):</span>
                                  {sSet.prediction_set.length > 0 ? (
                                    sSet.prediction_set.map(role => (
                                      <span key={role} style={{
                                        padding: "3px 8px",
                                        borderRadius: 4,
                                        font: "var(--type-mono-xs)",
                                        fontWeight: 600,
                                        background: "rgba(88, 166, 255, 0.15)",
                                        color: "var(--accent)",
                                        border: "1px solid rgba(88, 166, 255, 0.3)"
                                      }}>
                                        {role}
                                      </span>
                                    ))
                                  ) : (
                                    <span style={{ font: "var(--type-mono-xs)", color: "var(--critical, #ef4444)" }}>
                                      [EMPTY SET — OUT OF DISTRIBUTION ABSTENTION]
                                    </span>
                                  )}
                                  <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginLeft: "auto" }}>
                                    Quantile Threshold q̂ = {sSet.quantile_threshold}
                                  </span>
                                </div>

                                {/* Non-conformity score breakdown */}
                                {sSet.non_conformity_scores && (
                                  <div style={{ marginTop: "var(--space-2)", display: "flex", flexDirection: "column", gap: "6px" }}>
                                    <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase" }}>
                                      Candidate Role Non-Conformity Scores α(x, y) (Included if α ≤ {sSet.quantile_threshold}):
                                    </div>
                                    {Object.entries(sSet.non_conformity_scores).map(([role, alpha]) => {
                                      const isIncluded = sSet.prediction_set.includes(role);
                                      return (
                                        <div key={role} className={s.nonConformityBarRow}>
                                          <div style={{ width: "160px", color: isIncluded ? "var(--text-primary)" : "var(--text-muted)" }}>
                                            {isIncluded ? "✓ " : "✗ "}{role}
                                          </div>
                                          <div className={s.nonConformityTrack}>
                                            <div
                                              className={s.nonConformityFill}
                                              style={{
                                                width: `${Math.min(100, (alpha / Math.max(0.5, sSet.quantile_threshold * 1.5)) * 100)}%`,
                                                background: isIncluded ? "var(--accent)" : "rgba(255, 255, 255, 0.2)",
                                              }}
                                            />
                                          </div>
                                          <div style={{ width: "60px", textAlign: "right", color: isIncluded ? "var(--accent)" : "var(--text-muted)" }}>
                                            α = {alpha}
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Epistemic Source Tier Filter Bar */}
                      <div>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-2)" }}>
                          <h4 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", margin: 0 }}>
                            📑 Finding Evidentiary State Breakdown
                          </h4>
                          <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                            Showing {
                              tierFilter === "ALL"
                                ? confidenceData.finding_breakdowns.length
                                : confidenceData.finding_breakdowns.filter(f => f.epistemic_tier === tierFilter).length
                            } findings
                          </span>
                        </div>

                        <div className={s.tierBar}>
                          <button
                            type="button"
                            className={tierFilter === "ALL" ? s.tierChipActive : s.tierChip}
                            onClick={() => setTierFilter("ALL")}
                          >
                            All Tiers ({confidenceData.findings_audit.total_findings})
                          </button>
                          {Object.entries(confidenceData.findings_audit.tier_distribution).map(([tier, cnt]) => (
                            <button
                              key={tier}
                              type="button"
                              className={tierFilter === tier ? s.tierChipActive : s.tierChip}
                              onClick={() => setTierFilter(tier)}
                            >
                              <span>{tier}</span>
                              <strong style={{ opacity: 0.8 }}>({cnt})</strong>
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* Finding Cards Grid */}
                      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                        {confidenceData.finding_breakdowns
                          .filter(f => tierFilter === "ALL" || f.epistemic_tier === tierFilter)
                          .map(fb => (
                            <div key={fb.finding_id} className={s.confidenceFindingCard}>
                              <div className={s.findingMetaRow}>
                                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", flexWrap: "wrap" }}>
                                  <span style={{
                                    padding: "2px 6px",
                                    borderRadius: 4,
                                    font: "var(--type-mono-xs)",
                                    fontWeight: 600,
                                    background: fb.epistemic_tier === "DIRECT_OBSERVATION" ? "rgba(6, 182, 212, 0.12)" :
                                                fb.epistemic_tier === "RULE_BASED" ? "rgba(245, 158, 11, 0.12)" :
                                                fb.epistemic_tier === "INFERRED" ? "rgba(168, 85, 247, 0.12)" :
                                                fb.epistemic_tier === "SCREENING" ? "rgba(59, 130, 246, 0.12)" :
                                                "rgba(148, 163, 184, 0.12)",
                                    color: fb.epistemic_tier === "DIRECT_OBSERVATION" ? "#06b6d4" :
                                           fb.epistemic_tier === "RULE_BASED" ? "#f59e0b" :
                                           fb.epistemic_tier === "INFERRED" ? "#c084fc" :
                                           fb.epistemic_tier === "SCREENING" ? "#60a5fa" :
                                           "var(--text-muted)",
                                    border: "1px solid currentColor",
                                  }}>
                                    {fb.epistemic_tier}
                                  </span>
                                  <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                    {fb.finding_type}
                                  </span>
                                  <span style={{ font: "var(--type-mono-xs)", color: fb.severity === "CRITICAL" ? "var(--critical)" : fb.severity === "HIGH" ? "var(--warning)" : "var(--intel)" }}>
                                    {fb.severity}
                                  </span>
                                </div>

                                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                                  {fb.corroboration.is_multi_source ? (
                                    <span className={s.corroborationTag} title={`Corroborated across: ${fb.corroboration.evidence_file_types.join(", ")}`}>
                                      ✓ Multi-Source ({fb.corroboration.distinct_source_types_count} types)
                                    </span>
                                  ) : (
                                    <span className={s.corroborationTagSingle}>
                                      Single Source ({fb.corroboration.evidence_file_types[0] || "unspecified"})
                                    </span>
                                  )}

                                  {fb.contradiction_burden.has_contradiction_burden ? (
                                    <span className={s.contradictionTag} title="Challenged by active contradiction">
                                      ⚠️ Contradiction Burden (-{fb.contradiction_burden.penalty.toFixed(2)})
                                    </span>
                                  ) : (
                                    <span style={{ font: "var(--type-mono-xs)", color: "var(--verified, #10b981)" }}>
                                      ✓ Clean
                                    </span>
                                  )}
                                </div>
                              </div>

                              <div style={{ font: "var(--type-body)", color: "var(--text-primary)", fontWeight: 600 }}>
                                {fb.title}
                              </div>

                              <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
                                {fb.tier_description}
                              </div>

                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "var(--space-1)", font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                <div>
                                  Raw Score: <strong style={{ color: "var(--accent)" }}>{fb.raw_score !== null ? fb.raw_score : "N/A"}</strong> ({fb.score_type})
                                </div>
                                {fb.conformal_assessment.applicable && (
                                  <div>
                                    Conformal Set: <strong style={{ color: "var(--text-primary)" }}>{fb.conformal_assessment.prediction_set?.join(", ") || "None"}</strong> ({fb.conformal_assessment.verdict})
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                      </div>

                      {/* Conformal Calibration Registry Modal */}
                      {showCalibrationModal && (
                        <div style={{
                          position: "fixed",
                          inset: 0,
                          backgroundColor: "rgba(0,0,0,0.75)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          zIndex: 1000,
                          padding: "var(--space-4)",
                        }}>
                          <div style={{
                            background: "var(--surface-1)",
                            border: "1px solid var(--line)",
                            borderRadius: "var(--radius-card)",
                            width: "100%",
                            maxWidth: "700px",
                            padding: "var(--space-6)",
                            maxHeight: "85vh",
                            overflowY: "auto",
                          }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-4)" }}>
                              <h3 style={{ margin: 0, font: "var(--type-title-3)", color: "var(--text-primary)" }}>
                                📊 Split-Conformal Calibration Registry
                              </h3>
                              <Button variant="ghost" onClick={() => setShowCalibrationModal(false)}>✕</Button>
                            </div>

                            <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-4)" }}>
                              Conformal prediction guarantees finite-sample marginal coverage P(Y ∈ C(X)) ≥ 1 - ε. In compliance with Section 193 BNSS, each model's empirical provenance is audited to ensure synthetic benchmarks are never misrepresented as real courtroom calibrations.
                            </p>

                            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                              {calibrationsList.map(cal => (
                                <div key={cal.model_name} className={s.dataCard} style={{ padding: "var(--space-4)" }}>
                                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-2)" }}>
                                    <strong style={{ font: "var(--type-mono-sm)", color: "var(--accent)" }}>{cal.model_name}</strong>
                                    <span style={{
                                      padding: "2px 8px",
                                      borderRadius: 4,
                                      font: "var(--type-mono-xs)",
                                      background: cal.coverage_guarantee.valid_for_real_data ? "rgba(16, 185, 129, 0.12)" : "rgba(245, 158, 11, 0.12)",
                                      color: cal.coverage_guarantee.valid_for_real_data ? "#10b981" : "#f59e0b",
                                      border: "1px solid currentColor",
                                    }}>
                                      {cal.coverage_guarantee.guarantee_status}
                                    </span>
                                  </div>
                                  <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-2)" }}>
                                    Guarantee: {cal.coverage_guarantee.statement}
                                  </div>
                                  <div style={{ display: "flex", gap: "var(--space-4)", font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                    <span>Sample Size N: {cal.sample_size}</span>
                                    <span>Quantile Threshold q̂: {cal.quantile_threshold}</span>
                                    <span>Target Coverage: {Math.round(cal.target_coverage * 100)}%</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className={s.emptyState}>
                      <div className={s.emptyIcon}>📊</div>
                      <div>No confidence audit data available</div>
                      <div style={{ font: "var(--type-body-sm)" }}>Upload case evidence to compute multi-source corroboration and split-conformal prediction sets.</div>
                    </div>
                  )
                )}

                {/* ── Feature 06: Golden Hours Action Center ────────── */}
                {activeEngine === "nextbest" && (
                  nextBest ? (
                    <div>
                      {/* Operational Banner */}
                      <div style={{
                        padding: "var(--space-4) var(--space-5)",
                        background: nextBest.window_phase === "CRITICAL_GOLDEN_HOURS"
                          ? "rgba(255, 68, 68, 0.08)"
                          : "rgba(88, 166, 255, 0.08)",
                        border: `1px solid ${
                          nextBest.window_phase === "CRITICAL_GOLDEN_HOURS"
                            ? "rgba(255, 68, 68, 0.25)"
                            : "rgba(88, 166, 255, 0.25)"
                        }`,
                        borderRadius: "var(--radius-input)",
                        marginBottom: "var(--space-6)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        flexWrap: "wrap",
                        gap: "var(--space-3)",
                      }}>
                        <div>
                          <div style={{ font: "var(--type-body)", fontWeight: 600, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: 8 }}>
                            <span>⚡</span>
                            <span>Golden Hours Action Center · Section 106 & 94 BNSS</span>
                          </div>
                          <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginTop: 4 }}>
                            Time-critical freeze orders and evidentiary gap closures. Urgency decays exponentially as funds layer across accounts.
                          </div>
                        </div>
                        <div style={{
                          padding: "4px 12px",
                          borderRadius: "var(--radius-pill)",
                          font: "var(--type-mono-xs)",
                          fontWeight: 700,
                          letterSpacing: "0.06em",
                          background: nextBest.window_phase === "CRITICAL_GOLDEN_HOURS" ? "var(--critical)" : nextBest.window_phase === "EXTENDED_WINDOW" ? "var(--warning)" : "var(--surface-3)",
                          color: "#fff",
                        }}>
                          {nextBest.window_phase === "CRITICAL_GOLDEN_HOURS"
                            ? "⏰ CRITICAL GOLDEN WINDOW (≤ 2.0h)"
                            : nextBest.window_phase === "EXTENDED_WINDOW"
                            ? "⚠️ EXTENDED WINDOW (≤ 24.0h)"
                            : "⌛ DECAYED WINDOW (> 24.0h)"}
                        </div>
                      </div>

                      {/* 4-Card Metric Grid */}
                      <div className={s.cardGrid} style={{ marginBottom: "var(--space-6)" }}>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Elapsed Time</div>
                          <div className={s.cardValue}>{nextBest.elapsed_hours}h</div>
                          <div className={s.cardMeta}>
                            Golden window threshold: {nextBest.golden_hours}h
                          </div>
                        </div>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Preservable Assets</div>
                          <div className={s.cardValue} style={{ color: (nextBest.financial_exposure || 0) > 0 ? "var(--verified)" : "var(--text-primary)" }}>
                            ₹{(nextBest.financial_exposure || 0).toLocaleString("en-IN")}
                          </div>
                          <div className={s.cardMeta}>Proceeds traced at risk</div>
                        </div>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Urgency Score</div>
                          <div className={s.cardValue} style={{ color: nextBest.urgency_factor >= 0.7 ? "var(--critical)" : "var(--warning)" }}>
                            {nextBest.urgency_factor?.toFixed(2)}
                          </div>
                          <div className={s.cardMeta}>Exponential decay factor U(t)</div>
                        </div>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Actions Status</div>
                          <div className={s.cardValue}>
                            {nextBest.summary?.ready_count ?? nextBest.ranked_actions.filter(a => a.status === "ready").length} / {nextBest.ranked_actions.length}
                          </div>
                          <div className={s.cardMeta}>
                            {nextBest.summary?.blocked_count ?? nextBest.ranked_actions.filter(a => a.status === "blocked_missing_fields").length} blocked by evidence gaps
                          </div>
                        </div>
                      </div>

                      {/* Filter Bar */}
                      <div className={s.filterBar}>
                        <button
                          className={`${s.filterBtn} ${actionFilter === "all" ? s.filterBtnActive : ""}`}
                          onClick={() => setActionFilter("all")}
                        >
                          All Ranked Actions ({nextBest.ranked_actions.length})
                        </button>
                        <button
                          className={`${s.filterBtn} ${actionFilter === "ready" ? s.filterBtnActive : ""}`}
                          onClick={() => setActionFilter("ready")}
                        >
                          ⚡ Ready Notices ({nextBest.ranked_actions.filter(a => a.status === "ready").length})
                        </button>
                        <button
                          className={`${s.filterBtn} ${actionFilter === "blocked" ? s.filterBtnActive : ""}`}
                          onClick={() => setActionFilter("blocked")}
                        >
                          🚧 Evidence Gaps & Blocked ({nextBest.ranked_actions.filter(a => a.status === "blocked_missing_fields").length})
                        </button>
                      </div>

                      {/* Ranked Action Deck */}
                      {nextBest.ranked_actions
                        .filter(a => actionFilter === "all" || (actionFilter === "ready" ? a.status === "ready" : a.status === "blocked_missing_fields"))
                        .map((a, i) => {
                          const isReady = a.status === "ready";
                          const decayPct = Math.min(100, Math.max(8, (a.urgency_factor || 0) * 100));
                          return (
                            <div key={i} className={s.actionCard} style={{
                              borderLeft: isReady ? "4px solid var(--verified)" : "4px solid var(--warning)",
                            }}>
                              <div className={s.actionRank} style={{
                                background: isReady ? "rgba(80, 200, 120, 0.15)" : "rgba(255, 170, 0, 0.15)",
                                color: isReady ? "var(--verified)" : "var(--warning)",
                              }}>
                                {i + 1}
                              </div>
                              <div className={s.actionBody}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 8, marginBottom: 6 }}>
                                  <div className={s.actionTitle}>
                                    {a.title || a.description || a.action}
                                  </div>
                                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                    {a.statutory_basis && (
                                      <span className={s.statuteBadge}>
                                        ⚖️ {a.statutory_basis.split("(")[0].trim()}
                                      </span>
                                    )}
                                    {isReady ? (
                                      <span className={s.readyBadge}>⚡ Ready to Issue</span>
                                    ) : (
                                      <span className={s.blockedBadge}>🚧 Missing Info</span>
                                    )}
                                  </div>
                                </div>

                                {/* Description & Gap Rationale */}
                                <div className={s.actionInstructions}>
                                  {a.why || a.description || a.instructions}
                                </div>

                                {a.gap && (
                                  <div style={{ marginTop: 6, font: "var(--type-mono-xs)", color: "var(--accent)" }}>
                                    🎯 Evidence Gap: <strong>{a.gap}</strong> · Resolves: {a.resolves || "Unresolved case question"}
                                  </div>
                                )}

                                {/* Blocked missing fields */}
                                {!isReady && a.missing_fields && a.missing_fields.length > 0 && (
                                  <div style={{
                                    marginTop: 8,
                                    padding: "6px 12px",
                                    background: "rgba(255, 170, 0, 0.08)",
                                    border: "1px solid rgba(255, 170, 0, 0.2)",
                                    borderRadius: "var(--radius-input)",
                                    font: "var(--type-mono-xs)",
                                    color: "var(--warning)",
                                  }}>
                                    ⚠️ Action blocked until evidence acquired: <strong>{a.missing_fields.join(", ")}</strong>
                                  </div>
                                )}

                                {/* Decay Progress Bar */}
                                <div className={s.decayContainer}>
                                  <div style={{ display: "flex", justifyContent: "space-between", font: "var(--type-mono-xs)", color: "var(--text-muted)", marginBottom: 2 }}>
                                    <span>Urgency & Decay U(t)</span>
                                    <span>Factor: {(a.urgency_factor || 0).toFixed(2)} · Half-life: {a.decay_half_life_hours || 2}h</span>
                                  </div>
                                  <div className={s.decayBarTrack}>
                                    <div
                                      className={s.decayBarFill}
                                      style={{
                                        width: `${decayPct}%`,
                                        background: (a.urgency_factor || 0) >= 0.7 ? "var(--critical)" : (a.urgency_factor || 0) >= 0.4 ? "var(--warning)" : "var(--verified)",
                                      }}
                                    />
                                  </div>
                                </div>

                                {/* Grounded references and actions */}
                                <div className={s.actionMeta} style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
                                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                                    {a.utility_score !== undefined && (
                                      <span className={s.metaUrgent}>Utility Score: {a.utility_score?.toFixed(2)}</span>
                                    )}
                                    <span className={s.metaCategory}>{a.category}</span>
                                    {a.entity_refs && a.entity_refs.map((ent, idx) => (
                                      <span key={idx} style={{
                                        font: "var(--type-mono-xs)",
                                        padding: "2px 6px",
                                        background: "var(--surface-3)",
                                        borderRadius: "var(--radius-pill)",
                                        color: "var(--text-secondary)",
                                      }}>
                                        👤 {ent}
                                      </span>
                                    ))}
                                  </div>

                                  <div>
                                    <Button
                                      variant="secondary"
                                      disabled={draftingActionCode === a.action_code}
                                      onClick={() => handleViewDraftNotice(a)}
                                    >
                                      {draftingActionCode === a.action_code ? "Preparing Draft..." : "📄 View Statutory Notice Draft"}
                                    </Button>
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  ) : (
                    <div className={s.emptyState}>
                      <div className={s.emptyIcon}>⚡</div>
                      <div>No golden-hours action data available</div>
                    </div>
                  )
                )}

                {/* ── Feature 07: Crime Script Matcher Command Deck ── */}
                {activeEngine === "mo" && (
                  <div>
                    {/* Epistemic & Judicial Notice Banner */}
                    <div className={s.scriptNoticeBanner}>
                      <div className={s.scriptNoticeHeader}>
                        <span>⚖️</span>
                        <span>Section 193 BNSS & Section 63 BSA Forensic Standard · Crime Script Screening</span>
                      </div>
                      <p className={s.scriptNoticeText}>
                        Crime script matching evaluates procedural behavioral concordance against documented cyber fraud typologies
                        (I4C, NITI Aayog, NCRP). In strict compliance with <em>R v T [2010] EWCA Crim 2439</em>, sequence similarity is an
                        investigative screening aid and does <strong>NOT</strong> constitute proof of guilt, individual attribution, or conclusive determination of criminal acts without independent corroboration.
                      </p>
                    </div>

                    {/* Threshold & Controls Bar */}
                    <div className={s.thresholdRow}>
                      <div className={s.thresholdGroup}>
                        <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase", marginRight: 6 }}>
                          Match Threshold:
                        </span>
                        {[
                          { val: 0.50, label: "0.50 (Permissive)" },
                          { val: 0.60, label: "0.60 (Standard · Recommended)" },
                          { val: 0.70, label: "0.70 (Strict)" },
                          { val: 0.80, label: "0.80 (High Burden)" },
                        ].map(t => (
                          <button
                            key={t.val}
                            type="button"
                            className={moThreshold === t.val ? s.thresholdChipActive : s.thresholdChip}
                            onClick={() => handleThresholdChange(t.val)}
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>

                      <div style={{ display: "flex", gap: "var(--space-2)" }}>
                        <Button
                          variant="ghost"
                          onClick={() => setShowFormulaBreakdown(!showFormulaBreakdown)}
                        >
                          {showFormulaBreakdown ? "Hide Math" : "Formula Inspector"}
                        </Button>
                        <Button
                          variant={showAdhocTester ? "primary" : "ghost"}
                          onClick={() => setShowAdhocTester(!showAdhocTester)}
                        >
                          {showAdhocTester ? "Close Tester" : "🧪 Script Tester"}
                        </Button>
                      </div>
                    </div>

                    {/* Interactive Script Tester Drawer */}
                    {showAdhocTester && (
                      <div className={s.adhocSimulatorCard}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <div className="t-label">Interactive Script Simulator</div>
                          <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                            Test custom transcripts or hypothesis lines against playbooks
                          </span>
                        </div>
                        <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
                          <Button
                            variant="ghost"
                            onClick={() => setAdhocTranscript("CBI arrest warrant notice issued in customs parcel case\nJoin Skype video call immediately camera on\nArrest warrant non bailable remand order\nTransfer clearance verification security deposit\nDelete chat and block official number")}
                          >
                            Fill Digital Arrest Sample
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() => setAdhocTranscript("Complete daily profit task 500 bonus\nUpgrade VIP level 3 prepaid task\nDeposit 50000 capital investment recharge\nWithdrawal pending pay 30 percent tax fee\nAccount closed agent offline group dissolved")}
                          >
                            Fill Investment Task Sample
                          </Button>
                        </div>
                        <textarea
                          className={s.adhocTextarea}
                          placeholder="Paste WhatsApp messages, SMS transcript, or procedural steps (one per line)..."
                          value={adhocTranscript}
                          onChange={e => setAdhocTranscript(e.target.value)}
                        />
                        <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-3)" }}>
                          <Button variant="ghost" onClick={() => { setAdhocTranscript(""); setAdhocResult(null); }}>
                            Clear
                          </Button>
                          <Button variant="primary" onClick={handleRunAdhocScript} disabled={adhocRunning || !adhocTranscript.trim()}>
                            {adhocRunning ? "Analyzing Sequence..." : "Evaluate Script"}
                          </Button>
                        </div>

                        {adhocResult && (
                          <div style={{ marginTop: "var(--space-4)", padding: "var(--space-4)", background: "var(--surface-1)", borderRadius: "var(--radius-input)", border: "1px solid var(--line)" }}>
                            <div style={{ font: "var(--type-mono-xs)", color: adhocResult.verdict === "MATCHED" ? "var(--verified)" : "var(--warning)", marginBottom: 4 }}>
                              TEST RESULT: {adhocResult.verdict} {adhocResult.best_match ? `— ${adhocResult.best_match.playbook} (${(adhocResult.best_match.similarity * 100).toFixed(1)}%)` : ""}
                            </div>
                            <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)" }}>
                              Observed Sequence: {adhocResult.observed_sequence.join(" ➔ ") || "None"}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Primary Case Analysis */}
                    {moResult ? (
                      (() => {
                        const activeMatch = (selectedScriptPlaybook
                          ? moResult.matches?.find(m => m.playbook === selectedScriptPlaybook)
                          : null) || moResult.best_match || moResult.matches?.[0] || null;
                        const activeAlignment = activeMatch?.alignment || [];
                        const activeStageEvidence = activeMatch && selectedStageName
                          ? (activeMatch.stage_evidence?.[selectedStageName] || [])
                          : [];

                        return (
                          <div>
                            {/* Matching HUD Metrics */}
                            <div className={s.cardGrid} style={{ marginBottom: "var(--space-6)" }}>
                              <div className={s.dataCard}>
                                <div className={s.cardLabel}>Primary Verdict</div>
                                <div className={s.cardValue} style={{
                                  color: moResult.verdict === "MATCHED" ? "var(--verified)" :
                                         moResult.verdict === "NO_CONFIDENT_MATCH" ? "var(--warning)" : "var(--text-muted)"
                                }}>
                                  {moResult.verdict}
                                </div>
                                <div className={s.cardMeta}>Threshold: {(moThreshold * 100).toFixed(0)}%</div>
                              </div>

                              <div className={s.dataCard}>
                                <div className={s.cardLabel}>Active Crime Script</div>
                                <div className={s.cardValue} style={{ fontSize: 16, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {activeMatch ? activeMatch.playbook : "NO PLAYBOOK MATCH"}
                                </div>
                                <div className={s.cardMeta}>
                                  {activeMatch ? `${(activeMatch.similarity * 100).toFixed(1)}% sequence similarity` : "No confident match"}
                                </div>
                              </div>

                              <div className={s.dataCard}>
                                <div className={s.cardLabel}>Stage Concordance</div>
                                <div className={s.cardValue}>
                                  {activeMatch ? `${activeMatch.alignment?.filter(a => a.observed_position !== null).length || 0} / ${activeMatch.expected_sequence?.length || activeMatch.alignment?.length || 0}` : "0 / 0"}
                                </div>
                                <div className={s.cardMeta}>
                                  {activeMatch ? `${((activeMatch.coverage_ratio || 0) * 100).toFixed(0)}% stage coverage` : "No stages"}
                                </div>
                              </div>

                              <div className={s.dataCard}>
                                <div className={s.cardLabel}>Evidence Footprint</div>
                                <div className={s.cardValue}>
                                  {moResult.trace_evidence?.length || 0}
                                </div>
                                <div className={s.cardMeta}>Multi-modal evidence hits</div>
                              </div>
                            </div>

                            {/* Active Playbook Header */}
                            {activeMatch && (
                              <div style={{
                                marginBottom: "var(--space-6)",
                                padding: "var(--space-5)",
                                background: activeMatch.is_confident ? "rgba(80, 200, 120, 0.05)" : "rgba(255, 255, 255, 0.02)",
                                border: `1px solid ${activeMatch.is_confident ? "rgba(80, 200, 120, 0.3)" : "var(--line)"}`,
                                borderRadius: "var(--radius-input)",
                              }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-3)" }}>
                                  <div>
                                    <div style={{ font: "var(--type-mono-xs)", color: activeMatch.is_confident ? "var(--verified)" : "var(--warning)", letterSpacing: "0.06em", marginBottom: "var(--space-1)" }}>
                                      {activeMatch.is_confident ? "CONFIDENT PLAYBOOK MATCH" : "INDICATIVE PATTERN (BELOW THRESHOLD)"}
                                    </div>
                                    <div style={{ font: "var(--type-heading-sm)", fontWeight: 600, color: "var(--text-primary)" }}>
                                      {activeMatch.playbook}
                                    </div>
                                    {activeMatch.description && (
                                      <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginTop: 4 }}>
                                        {activeMatch.description}
                                      </div>
                                    )}
                                    <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: 4 }}>
                                      Source: {activeMatch.source}
                                    </div>
                                  </div>
                                  <div style={{ textAlign: "right" }}>
                                    <div style={{ font: "var(--type-mono-xl)", fontWeight: 700, color: activeMatch.is_confident ? "var(--verified)" : "var(--warning)" }}>
                                      {(activeMatch.similarity * 100).toFixed(1)}%
                                    </div>
                                    <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>Normalized Similarity</div>
                                  </div>
                                </div>
                              </div>
                            )}

                            {/* Interactive Stage Pipeline Visualizer */}
                            {activeMatch && activeAlignment.length > 0 && (
                              <div style={{ marginBottom: "var(--space-6)" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-3)" }}>
                                  <div className="t-label">
                                    Procedural Crime Script Pipeline
                                    <span style={{ marginLeft: 8, font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "none" }}>
                                      (Click any stage to inspect supporting evidence)
                                    </span>
                                  </div>
                                  {selectedStageName && (
                                    <button
                                      type="button"
                                      onClick={() => setSelectedStageName(null)}
                                      style={{ background: "none", border: "none", color: "var(--accent)", font: "var(--type-mono-xs)", cursor: "pointer" }}
                                    >
                                      Clear Selection ✕
                                    </button>
                                  )}
                                </div>

                                <div className={s.scriptPipeline}>
                                  {activeAlignment.map((st, idx) => {
                                    const isSelected = selectedStageName === st.stage;
                                    const cardClass = st.status === "MATCHED_IN_ORDER"
                                      ? s.scriptStageMatched
                                      : st.status === "MATCHED_OUT_OF_ORDER"
                                      ? s.scriptStageOutOfOrder
                                      : s.scriptStageMissing;

                                    return (
                                      <div
                                        key={st.stage}
                                        className={`${cardClass} ${isSelected ? s.scriptStageSelected : ""}`}
                                        onClick={() => setSelectedStageName(isSelected ? null : st.stage)}
                                        title="Click to view evidence citations"
                                      >
                                        <div>
                                          <div className={s.stagePositionBadge}>
                                            Stage {String(st.expected_position || idx + 1).padStart(2, "0")}
                                            {st.observed_position ? ` · Observed #${st.observed_position}` : ""}
                                          </div>
                                          <div className={s.stageTitle}>{st.stage}</div>
                                        </div>

                                        <div>
                                          <div style={{ marginBottom: 6 }}>
                                            <span className={
                                              st.status === "MATCHED_IN_ORDER" ? s.statusMatched :
                                              st.status === "MATCHED_OUT_OF_ORDER" ? s.statusOutOfOrder :
                                              s.statusMissing
                                            }>
                                              {st.status === "MATCHED_IN_ORDER" ? "✓ In Sequence" :
                                               st.status === "MATCHED_OUT_OF_ORDER" ? "⇄ Out of Order" : "— Missing"}
                                            </span>
                                          </div>
                                          <div style={{ font: "var(--type-mono-xs)", color: st.evidence_count > 0 ? "var(--text-secondary)" : "var(--text-muted)" }}>
                                            {st.evidence_count} evidence item{st.evidence_count === 1 ? "" : "s"}
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>

                                {/* Stage Evidence Deep-Dive Drawer */}
                                {selectedStageName && (
                                  <div className={s.evidenceDrawer}>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                      <div style={{ font: "var(--type-body)", fontWeight: 600, color: "var(--text-primary)" }}>
                                        Supporting Evidence Citations: <span style={{ color: "var(--accent)" }}>{selectedStageName}</span>
                                      </div>
                                      <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                        {activeStageEvidence.length} direct hit{activeStageEvidence.length === 1 ? "" : "s"}
                                      </span>
                                    </div>

                                    {activeStageEvidence.length === 0 ? (
                                      <div style={{ font: "var(--type-body-sm)", color: "var(--text-muted)", marginTop: "var(--space-3)", fontStyle: "italic" }}>
                                        No explicit evidence event citations recorded for this stage. It may be missing in the case record.
                                      </div>
                                    ) : (
                                      <div className={s.evidenceGrid}>
                                        {activeStageEvidence.map((ev, evIdx) => (
                                          <div key={evIdx} className={s.evidenceCard}>
                                            <div className={s.evidenceCardHeader}>
                                              <span className={
                                                ev.source_type === "bank_txn" ? s.modalityBank :
                                                ev.source_type === "call" ? s.modalityCall :
                                                ev.source_type === "network_log" ? s.modalityNet :
                                                ev.source_type === "document_text" ? s.modalityDoc :
                                                s.modalityChat
                                              }>
                                                {ev.source_type || "message"}
                                              </span>
                                              <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                                {ev.timestamp || `Line #${ev.line_no || evIdx + 1}`}
                                              </span>
                                            </div>

                                            {ev.filename && (
                                              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-secondary)" }}>
                                                File: <span style={{ color: "var(--text-primary)" }}>{ev.filename}</span>
                                              </div>
                                            )}

                                            {ev.sender && (
                                              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                                Entity/Party: {ev.sender}
                                              </div>
                                            )}

                                            <div className={s.evidenceSnippet}>
                                              {ev.matched_text || "Matched detector criteria"}
                                            </div>

                                            {ev.event_id && (
                                              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", fontSize: 10 }}>
                                                Event ID: {ev.event_id}
                                              </div>
                                            )}
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Mathematical Calculation & Epistemic Transparency Inspector */}
                            {showFormulaBreakdown && activeMatch?.calculation_breakdown && (
                              <div className={s.formulaBox}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <div className="t-label">Sequence Similarity Calculation Transparency</div>
                                  <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                    Normalized Levenshtein Edit Distance on Categorical Stage Tokens
                                  </span>
                                </div>
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--text-secondary)", marginTop: "var(--space-2)", background: "var(--surface-1)", padding: "var(--space-3)", borderRadius: "var(--radius-input)" }}>
                                  <code>Similarity(Observed, Expected) = 1.0 - (Levenshtein_Distance / max(Observed_Length, Expected_Length))</code>
                                </div>

                                <div className={s.formulaGrid}>
                                  <div className={s.formulaItem}>
                                    <div className={s.formulaItemLabel}>Observed Sequence Length</div>
                                    <div className={s.formulaItemValue}>{activeMatch.calculation_breakdown.observed_length} stages</div>
                                  </div>
                                  <div className={s.formulaItem}>
                                    <div className={s.formulaItemLabel}>Expected Playbook Stages</div>
                                    <div className={s.formulaItemValue}>{activeMatch.calculation_breakdown.expected_length} stages</div>
                                  </div>
                                  <div className={s.formulaItem}>
                                    <div className={s.formulaItemLabel}>Levenshtein Edit Distance</div>
                                    <div className={s.formulaItemValue}>{activeMatch.calculation_breakdown.levenshtein_distance} edits</div>
                                  </div>
                                  <div className={s.formulaItem}>
                                    <div className={s.formulaItemLabel}>Stage Coverage Ratio</div>
                                    <div className={s.formulaItemValue}>{(activeMatch.calculation_breakdown.coverage_ratio * 100).toFixed(1)}%</div>
                                  </div>
                                  <div className={s.formulaItem}>
                                    <div className={s.formulaItemLabel}>Gate Threshold</div>
                                    <div className={s.formulaItemValue} style={{ color: activeMatch.is_confident ? "var(--verified)" : "var(--warning)" }}>
                                      {(activeMatch.calculation_breakdown.threshold * 100).toFixed(0)}% ({activeMatch.is_confident ? "PASSED" : "FAILED"})
                                    </div>
                                  </div>
                                </div>
                              </div>
                            )}

                            {/* Playbook Comparison Matrix */}
                            <div style={{ marginBottom: "var(--space-6)" }}>
                              <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>
                                Playbook Comparison Matrix
                                <span style={{ marginLeft: 8, font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                  SCREENING AID · NOT INDIVIDUAL ATTRIBUTION
                                </span>
                              </div>

                              <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--radius-input)", overflow: "hidden" }}>
                                <table className={s.playbookComparisonTable}>
                                  <thead>
                                    <tr>
                                      <th>Playbook</th>
                                      <th>Source / Advisory</th>
                                      <th>Observed Stages</th>
                                      <th>Coverage</th>
                                      <th>Similarity</th>
                                      <th>Status</th>
                                      <th>Action</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {moResult.matches?.map((m) => {
                                      const isCurrent = activeMatch?.playbook === m.playbook;
                                      return (
                                        <tr key={m.playbook} className={isCurrent ? s.playbookRowActive : ""}>
                                          <td style={{ fontWeight: 600, color: isCurrent ? "var(--accent)" : "var(--text-primary)" }}>
                                            {m.playbook}
                                            {m.description && (
                                              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", fontWeight: 400 }}>
                                                {m.description}
                                              </div>
                                            )}
                                          </td>
                                          <td style={{ font: "var(--type-mono-xs)" }}>{m.source}</td>
                                          <td>{m.observed_sequence?.length || 0}</td>
                                          <td>{((m.coverage_ratio || 0) * 100).toFixed(0)}%</td>
                                          <td style={{ minWidth: 140 }}>
                                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                              <div style={{ flex: 1, height: 6, background: "var(--surface-1)", borderRadius: 999, overflow: "hidden" }}>
                                                <div style={{ width: `${m.similarity * 100}%`, height: "100%", background: m.similarity >= moThreshold ? "var(--verified)" : "var(--accent)" }} />
                                              </div>
                                              <span style={{ font: "var(--type-mono-xs)", minWidth: 35, textAlign: "right" }}>
                                                {(m.similarity * 100).toFixed(0)}%
                                              </span>
                                            </div>
                                          </td>
                                          <td>
                                            <span style={{
                                              font: "var(--type-mono-xs)",
                                              padding: "2px 6px",
                                              borderRadius: 4,
                                              background: m.similarity >= moThreshold ? "rgba(52, 211, 153, 0.12)" : "rgba(255, 255, 255, 0.05)",
                                              color: m.similarity >= moThreshold ? "#34d399" : "var(--text-muted)",
                                            }}>
                                              {m.similarity >= moThreshold ? "MATCHED" : "BELOW THRESHOLD"}
                                            </span>
                                          </td>
                                          <td>
                                            <Button
                                              variant={isCurrent ? "primary" : "ghost"}
                                              onClick={() => {
                                                setSelectedScriptPlaybook(m.playbook);
                                                setSelectedStageName(null);
                                              }}
                                            >
                                              {isCurrent ? "Selected" : "Inspect Pipeline"}
                                            </Button>
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            </div>

                            {moResult.note && (
                              <p style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: "var(--space-4)", fontStyle: "italic" }}>
                                Note: {moResult.note}
                              </p>
                            )}
                          </div>
                        );
                      })()
                    ) : (
                      <div className={s.emptyState}>
                        <div className={s.emptyIcon}>🔍</div>
                        <div>No Crime Script Data Available</div>
                        <div style={{ font: "var(--type-body-sm)" }}>
                          Upload multi-modal case evidence (chat transcripts, bank statements, CDR logs) or run the script tester.
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* ── Feature 08: What-If Freeze Simulator Sandbox ── */}
                {activeEngine === "counterfactual" && (
                  <div>
                    {/* Epistemic Caution Banner */}
                    <div style={{
                      padding: "var(--space-4) var(--space-5)",
                      marginBottom: "var(--space-6)",
                      background: "rgba(255, 180, 0, 0.08)",
                      border: "1px solid rgba(255, 180, 0, 0.3)",
                      borderRadius: "var(--radius-input)",
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                    }}>
                      <span style={{ fontSize: 20 }}>⚠️</span>
                      <div>
                        <div style={{ font: "var(--type-body)", fontWeight: 600, color: "var(--warning)" }}>
                          HYPOTHETICAL SIMULATION SANDBOX · NOT OBSERVED EVIDENCE
                        </div>
                        <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginTop: 2 }}>
                          Calculates lower-bound recovery estimates under network interdiction. Does not modify authoritative case records, persistent graph edges, or forensic chain of custody.
                        </div>
                      </div>
                    </div>

                    {/* Stage 2: Intervention Builder */}
                    <div style={{
                      padding: "var(--space-5)",
                      background: "var(--surface-1)",
                      border: "1px solid var(--line)",
                      borderRadius: "var(--radius-card)",
                      marginBottom: "var(--space-6)",
                    }}>
                      <div className="t-label" style={{ marginBottom: "var(--space-3)", color: "var(--accent)" }}>
                        🎯 Counterfactual Intervention Setup (Section 106 BNSS / 1930 CFCFRMS)
                      </div>

                      {/* Candidate Accounts Row */}
                      {cfCandidates.length > 0 && (
                        <div>
                          <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginBottom: "var(--space-2)" }}>
                            DISCOVERED CASE ACCOUNTS & MULE NODES (1-CLICK SELECT):
                          </div>
                          <div className={s.cfCandidatesBar}>
                            {cfCandidates.map((cand, idx) => (
                              <button
                                key={idx}
                                className={`${s.cfCandidateChip} ${freezeAccount === cand.account ? s.cfCandidateChipActive : ""}`}
                                onClick={() => {
                                  setFreezeAccount(cand.account);
                                  if (cand.suggested_freeze_time) setFreezeTime(cand.suggested_freeze_time);
                                  handleCounterfactual(cand.account, cand.suggested_freeze_time);
                                }}
                              >
                                <span>🏦 {cand.account}</span>
                                <span style={{ color: "var(--text-muted)", font: "var(--type-mono-xs)" }}>
                                  ₹{cand.total_volume.toLocaleString()} ({cand.txn_count} txns)
                                </span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Custom Input Row */}
                      <div className={s.inputRow} style={{ marginTop: "var(--space-3)" }}>
                        <div style={{ flex: 1, minWidth: 240 }}>
                          <label style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                            Target Account / VPA
                          </label>
                          <input
                            className={s.inputField}
                            placeholder="Account to freeze (e.g. rohan@upi, ACC-003)"
                            value={freezeAccount}
                            onChange={e => setFreezeAccount(e.target.value)}
                          />
                        </div>
                        <div style={{ flex: 1, minWidth: 240 }}>
                          <label style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                            Freeze Timestamp (IST / ISO-8601)
                          </label>
                          <input
                            className={s.inputField}
                            placeholder="YYYY-MM-DDTHH:MM:SS"
                            value={freezeTime}
                            onChange={e => setFreezeTime(e.target.value)}
                          />
                        </div>
                        <div style={{ alignSelf: "flex-end" }}>
                          <Button variant="primary" onClick={() => handleCounterfactual()} disabled={loading}>
                            {loading ? "Simulating..." : "Simulate Freeze"}
                          </Button>
                        </div>
                      </div>

                      {/* Quick Time Offsets */}
                      {freezeTime && (
                        <div className={s.cfTimePresets}>
                          <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>Golden-Hours Response Presets:</span>
                          <button className={s.cfPresetBtn} onClick={() => handlePresetOffset(15)}>+15 min (Instant Action)</button>
                          <button className={s.cfPresetBtn} onClick={() => handlePresetOffset(30)}>+30 min</button>
                          <button className={s.cfPresetBtn} onClick={() => handlePresetOffset(60)}>+1 hour</button>
                          <button className={s.cfPresetBtn} onClick={() => handlePresetOffset(120)}>+2 hours (Golden Cutoff)</button>
                          <button className={s.cfPresetBtn} onClick={() => handlePresetOffset(360)}>+6 hours</button>
                          <button className={s.cfPresetBtn} onClick={() => handlePresetOffset(1440)}>+24 hours</button>
                        </div>
                      )}
                    </div>

                    {cfResult && (
                      <div>
                        {/* 4-Stage Comparative Deck */}
                        <div className={s.cfSummary} style={{ marginBottom: "var(--space-6)" }}>
                          <div className={s.cfMetric} style={{ borderColor: "rgba(46, 160, 67, 0.3)" }}>
                            <div className={s.cfMetricValue} style={{ color: "var(--verified)" }}>
                              ₹{cfResult.preserved_total?.toLocaleString()}
                            </div>
                            <div className={s.cfMetricLabel}>
                              Preserved Capital ({cfResult.stage_4_comparison?.preservation_percentage ?? 0}%)
                            </div>
                          </div>
                          <div className={s.cfMetric} style={{ borderColor: "rgba(255, 68, 68, 0.3)" }}>
                            <div className={s.cfMetricValue} style={{ color: "var(--critical)" }}>
                              ₹{(cfResult.stage_4_comparison?.dissipated_total ?? 0).toLocaleString()}
                            </div>
                            <div className={s.cfMetricLabel}>Dissipated / Lost Capital</div>
                          </div>
                          <div className={s.cfMetric} style={{ borderColor: "rgba(255, 180, 0, 0.3)" }}>
                            <div className={s.cfMetricValue} style={{ color: "var(--warning)" }}>
                              {cfResult.blocked_debits}
                            </div>
                            <div className={s.cfMetricLabel}>Blocked Outbound Debits</div>
                          </div>
                          <div className={s.cfMetric} style={{ borderColor: "rgba(168, 85, 247, 0.3)" }}>
                            <div className={s.cfMetricValue} style={{ color: "#c084fc" }}>
                              {cfResult.stage_4_comparison?.starved_attempts_count ?? cfResult.unfunded_attempts?.length ?? 0}
                            </div>
                            <div className={s.cfMetricLabel}>Starved Downstream Mules</div>
                          </div>
                        </div>

                        {/* Timeliness Sensitivity Decay Chart */}
                        {cfResult.timeliness_sweep && cfResult.timeliness_sweep.length > 0 && (
                          <div className={s.cfSweepSection}>
                            <div className="t-label" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                              <span>⏱️ Timeliness Sensitivity Analysis (Golden-Hours Preservation Decay)</span>
                              <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                Faster notification preserves higher capital before layering
                              </span>
                            </div>
                            <div className={s.cfSweepGrid}>
                              {cfResult.timeliness_sweep.map((step, idx) => (
                                <div
                                  key={idx}
                                  className={`${s.cfSweepCard} ${freezeTime === step.freeze_time ? s.cfSweepCardActive : ""}`}
                                  style={{ cursor: "pointer" }}
                                  onClick={() => {
                                    setFreezeTime(step.freeze_time);
                                    handleCounterfactual(freezeAccount, step.freeze_time);
                                  }}
                                >
                                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                    <span style={{ font: "var(--type-mono-xs)", fontWeight: 700 }}>{step.offset_label}</span>
                                    <span style={{
                                      padding: "1px 6px",
                                      borderRadius: "var(--radius-pill)",
                                      fontSize: 10,
                                      fontWeight: 700,
                                      background: step.status === "CRITICAL" ? "rgba(255, 68, 68, 0.2)" : step.status === "EXTENDED" ? "rgba(255, 180, 0, 0.2)" : "rgba(255, 255, 255, 0.08)",
                                      color: step.status === "CRITICAL" ? "var(--critical)" : step.status === "EXTENDED" ? "var(--warning)" : "var(--text-muted)",
                                    }}>
                                      {step.status}
                                    </span>
                                  </div>
                                  <div style={{ font: "var(--type-title-2)", color: "var(--verified)", marginTop: 4 }}>
                                    ₹{step.preserved_total.toLocaleString()}
                                  </div>
                                  <div style={{ font: "var(--type-mono-xs)", color: "var(--text-secondary)" }}>
                                    {step.preservation_percentage}% saved · {step.blocked_debits} blocked
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Node Classifications Bar */}
                        {cfResult.node_classifications && Object.keys(cfResult.node_classifications).length > 0 && (
                          <div style={{
                            marginTop: "var(--space-6)",
                            padding: "var(--space-4) var(--space-5)",
                            background: "var(--surface-1)",
                            border: "1px solid var(--line)",
                            borderRadius: "var(--radius-input)",
                          }}>
                            <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>
                              🌐 Downstream Network Node Cascade States
                            </div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
                              {Object.entries(cfResult.node_classifications).map(([node, status], idx) => {
                                const isTarget = status === "INTERVENTION_POINT";
                                const isPreserved = status === "PRESERVED_CAPITAL";
                                const isStarved = status === "STARVED_DOWNSTREAM";
                                return (
                                  <span
                                    key={idx}
                                    style={{
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: 6,
                                      padding: "3px 10px",
                                      borderRadius: "var(--radius-pill)",
                                      font: "var(--type-mono-xs)",
                                      background: isTarget ? "rgba(168, 85, 247, 0.2)" : isPreserved ? "rgba(46, 160, 67, 0.2)" : isStarved ? "rgba(255, 180, 0, 0.2)" : "var(--surface-2)",
                                      color: isTarget ? "#c084fc" : isPreserved ? "var(--verified)" : isStarved ? "var(--warning)" : "var(--text-muted)",
                                      border: `1px solid ${isTarget ? "#c084fc" : isPreserved ? "var(--verified)" : isStarved ? "var(--warning)" : "var(--line)"}`,
                                    }}
                                  >
                                    <span>{isTarget ? "🎯" : isPreserved ? "📥" : isStarved ? "⚠️" : "⚪"}</span>
                                    <span>{node}</span>
                                    <span style={{ opacity: 0.7, fontSize: 10 }}>({status.replace("_", " ")})</span>
                                  </span>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* Comparative Transfer Audit Table */}
                        {(() => {
                          const blockedList = cfResult.blocked_out_events || [];
                          const stoppedList = cfResult.stopped_in_events || [];
                          const starvedList = cfResult.unfunded_attempts || [];
                          const allTransfers = [
                            ...blockedList.map(t => ({ ...t, kind: "BLOCKED" })),
                            ...stoppedList.map(t => ({ ...t, kind: "STOPPED" })),
                            ...starvedList.map(t => ({ ...t, kind: "STARVED" })),
                          ].sort((a, b) => (a.timestamp > b.timestamp ? 1 : -1));

                          const filtered = allTransfers.filter(t => {
                            if (cfFilter === "all") return true;
                            if (cfFilter === "blocked") return t.kind === "BLOCKED";
                            if (cfFilter === "stopped") return t.kind === "STOPPED";
                            if (cfFilter === "starved") return t.kind === "STARVED";
                            return true;
                          });

                          return (
                            <div className={s.cfTableContainer}>
                              <div className={s.cfFilterRow}>
                                <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginRight: 8 }}>Filter Audit:</span>
                                <button
                                  className={`${s.cfFilterTab} ${cfFilter === "all" ? s.cfFilterTabActive : ""}`}
                                  onClick={() => setCfFilter("all")}
                                >
                                  All Impacted ({allTransfers.length})
                                </button>
                                <button
                                  className={`${s.cfFilterTab} ${cfFilter === "blocked" ? s.cfFilterTabActive : ""}`}
                                  onClick={() => setCfFilter("blocked")}
                                >
                                  🛑 Blocked Debits ({blockedList.length})
                                </button>
                                <button
                                  className={`${s.cfFilterTab} ${cfFilter === "stopped" ? s.cfFilterTabActive : ""}`}
                                  onClick={() => setCfFilter("stopped")}
                                >
                                  📥 Stopped Inbound ({stoppedList.length})
                                </button>
                                <button
                                  className={`${s.cfFilterTab} ${cfFilter === "starved" ? s.cfFilterTabActive : ""}`}
                                  onClick={() => setCfFilter("starved")}
                                >
                                  ⚠️ Starved Downstream ({starvedList.length})
                                </button>
                              </div>

                              <div style={{
                                display: "grid",
                                gridTemplateColumns: "140px 1fr 1fr 100px 140px",
                                gap: "var(--space-3)",
                                padding: "var(--space-2) var(--space-4)",
                                background: "var(--surface-3)",
                                font: "var(--type-mono-xs)",
                                fontWeight: 700,
                                color: "var(--text-muted)",
                                textTransform: "uppercase",
                              }}>
                                <div>Timestamp</div>
                                <div>From (Sender)</div>
                                <div>To (Receiver)</div>
                                <div style={{ textAlign: "right" }}>Amount</div>
                                <div style={{ textAlign: "center" }}>Interdiction State</div>
                              </div>

                              {filtered.length > 0 ? (
                                filtered.map((row, idx) => (
                                  <div key={idx} className={s.cfTableRow}>
                                    <div style={{ color: "var(--text-secondary)" }}>{row.timestamp?.replace("T", " ")}</div>
                                    <div style={{ color: "var(--text-primary)", fontWeight: 500 }}>{row.from}</div>
                                    <div style={{ color: "var(--text-primary)", fontWeight: 500 }}>{row.to}</div>
                                    <div style={{ textAlign: "right", color: "var(--verified)", fontWeight: 600 }}>
                                      ₹{row.amount?.toLocaleString()}
                                    </div>
                                    <div style={{ textAlign: "center" }}>
                                      {row.kind === "BLOCKED" && <span className={s.cfBadgeBlocked}>🛑 Blocked Debit</span>}
                                      {row.kind === "STOPPED" && <span className={s.cfBadgeStopped}>📥 Inbound Stopped</span>}
                                      {row.kind === "STARVED" && <span className={s.cfBadgeStarved}>⚠️ Starved (Unfunded)</span>}
                                    </div>
                                  </div>
                                ))
                              ) : (
                                <div style={{ padding: "var(--space-6)", textAlign: "center", color: "var(--text-muted)", font: "var(--type-body-sm)" }}>
                                  No transactions match the selected filter.
                                </div>
                              )}
                            </div>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                )}

                {/* ── Network Replay Panel ────────────────────────── */}
                {activeEngine === "replay" && (
                  replayResult ? (
                    <div>
                      <div className={s.cardGrid} style={{ marginBottom: "var(--space-6)" }}>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Total Events</div>
                          <div className={s.cardValue}>{replayResult.total_events}</div>
                        </div>
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Animation Frames</div>
                          <div className={s.cardValue}>{replayResult.total_frames}</div>
                        </div>
                      </div>

                      {replayResult.frames.length > 0 ? (
                        <div>
                          <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Frame Timeline</div>
                          {replayResult.frames.slice(0, 20).map((f, i) => (
                            <div key={i} className={s.findingRow}>
                              <div className={s.findingSeverityInfo} />
                              <div className={s.findingBody}>
                                <div className={s.findingKind} style={{ color: "var(--intel)" }}>Frame {i + 1}</div>
                                <div className={s.findingText}>
                                  {f.nodes?.length || 0} nodes · {f.edges?.length || 0} edges
                                </div>
                                <div className={s.findingMeta}>
                                  {f.t_start} → {f.t_end}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className={s.emptyState}>
                          <div className={s.emptyIcon}>🎬</div>
                          <div>No replay frames generated</div>
                          <div style={{ font: "var(--type-body-sm)" }}>Not enough timestamped events for temporal network reconstruction.</div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className={s.emptyState}>
                      <div className={s.emptyIcon}>🎬</div>
                      <div>No replay data available</div>
                    </div>
                  )
                )}

                {/* ── Feature 03: Syndicate Radar & Cross-Case Intelligence ──────── */}
                {activeEngine === "crosscase" && (
                  <div>
                    {/* Header & Threat Badge */}
                    <div className={s.radarHeader}>
                      <div>
                        <h3 style={{ margin: 0, font: "var(--type-ui-lg)", display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                          <span>🛰️ Syndicate Radar</span>
                          <span className={s.threatTag} style={{
                            background: syndicateRadar?.overall_threat_level === "CRITICAL"
                              ? "rgba(255, 77, 79, 0.15)"
                              : syndicateRadar?.overall_threat_level === "ELEVATED"
                              ? "rgba(250, 173, 20, 0.15)"
                              : "rgba(0, 230, 153, 0.12)",
                            color: syndicateRadar?.overall_threat_level === "CRITICAL"
                              ? "var(--critical)"
                              : syndicateRadar?.overall_threat_level === "ELEVATED"
                              ? "var(--warning)"
                              : "var(--verified)",
                            borderColor: "currentColor",
                          }}>
                            {syndicateRadar?.overall_threat_level || "MONITORED"} THREAT
                          </span>
                        </h3>
                        <p style={{ margin: "var(--space-1) 0 0", font: "var(--type-body-sm)", color: "var(--text-muted)" }}>
                          Zero-knowledge cross-case collision detection and criminal syndicate clustering.
                        </p>
                      </div>

                      <Button
                        variant="secondary"
                        onClick={() => runEngine("crosscase")}
                        disabled={loading}
                      >
                        <Icon name="command" size={14} /> Scan Blind Index
                      </Button>
                    </div>

                    {/* Zero-Knowledge Privacy & Security Banner */}
                    <div className={s.radarPrivacyCard}>
                      <span style={{ fontSize: 18 }}>🔒</span>
                      <div>
                        <strong>ZERO-KNOWLEDGE PRIVACY BOUNDARY ENFORCED (SECTION 94 BNSS)</strong> — Identifiers
                        across external cases are cryptographically shielded by one-way HMAC-SHA256 tokens.
                        Plaintext values for external case entities remain confidential unless shared via statutory
                        inter-station electronic requisitions.
                      </div>
                    </div>

                    {/* 4-Card Comparative Metrics Deck */}
                    <div className={s.cardGrid} style={{ marginBottom: "var(--space-6)" }}>
                      <div className={s.dataCard}>
                        <div className={s.cardLabel}>Local Entities Screened</div>
                        <div className={s.cardValue}>
                          {syndicateRadar?.total_entities_screened ?? crossCase?.total_entities_indexed ?? 0}
                        </div>
                        <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: 2 }}>
                          Hard IDs in this case
                        </div>
                      </div>

                      <div className={s.dataCard}>
                        <div className={s.cardLabel}>Cross-Case Collisions</div>
                        <div className={s.cardValue} style={{
                          color: (syndicateRadar?.total_collisions ?? crossCase?.total_collisions ?? 0) > 0 ? "var(--warning)" : "var(--verified)"
                        }}>
                          {syndicateRadar?.total_collisions ?? crossCase?.total_collisions ?? 0}
                        </div>
                        <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: 2 }}>
                          Shared HMAC blind tokens
                        </div>
                      </div>

                      <div className={s.dataCard}>
                        <div className={s.cardLabel}>Syndicate Clusters</div>
                        <div className={s.cardValue} style={{
                          color: (syndicateRadar?.total_syndicate_clusters ?? (crossCase?.syndicates?.length ?? 0)) > 0 ? "var(--critical)" : "var(--text-primary)"
                        }}>
                          {syndicateRadar?.total_syndicate_clusters ?? (crossCase?.syndicates?.length ?? 0)}
                        </div>
                        <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: 2 }}>
                          Multi-case criminal nexus
                        </div>
                      </div>

                      <div className={s.dataCard}>
                        <div className={s.cardLabel}>Peak Ingress Score</div>
                        <div className={s.cardValue} style={{ color: "var(--critical)" }}>
                          {syndicateRadar?.max_syndicate_score ? syndicateRadar.max_syndicate_score.toFixed(1) : "0.0"}
                        </div>
                        <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: 2 }}>
                          Degree-weighted threat ingress
                        </div>
                      </div>
                    </div>

                    {/* Visual Radar Scope & Blip Inspector Layout */}
                    <div className={s.radarVisualLayout}>
                      {/* Left: Concentric Polar Radar */}
                      <div>
                        <div className={s.radarScopeWrapper}>
                          <div className={s.radarSweepLine} />
                          <div className={s.radarCenterCross} />
                          <div className={s.radarRingCore} />
                          <div className={s.radarRingInner} />
                          <div className={s.radarRingOuter} />
                          <div className={s.radarAxisH} />
                          <div className={s.radarAxisV} />

                          {/* Render Radar Blips */}
                          {(syndicateRadar?.radar_blips || []).map((blip, bi) => {
                            const cx = 160;
                            const cy = 160;
                            const radiusPx = blip.r * 135;
                            const angleRad = (blip.theta * Math.PI) / 180;
                            const bx = cx + radiusPx * Math.cos(angleRad);
                            const by = cy + radiusPx * Math.sin(angleRad);

                            const blipColor = blip.risk_level === "CRITICAL"
                              ? "var(--critical)"
                              : blip.risk_level === "ELEVATED"
                              ? "var(--warning)"
                              : "var(--accent)";

                            return (
                              <div
                                key={bi}
                                className={s.radarBlipElement}
                                style={{
                                  left: `${bx}px`,
                                  top: `${by}px`,
                                  backgroundColor: blipColor,
                                  boxShadow: `0 0 10px ${blipColor}`,
                                }}
                                onMouseEnter={() => setHoveredBlip(blip)}
                                onClick={() => {
                                  if (blip.blip_type === "SYNDICATE_CLUSTER") {
                                    setSelectedSyndicate(blip.id);
                                  }
                                }}
                                title={`${blip.label} (${blip.risk_level} · ${blip.case_count} Cases)`}
                              />
                            );
                          })}
                        </div>

                        {/* Radar Range Legend */}
                        <div className={s.radarLegendGrid}>
                          <div className={s.radarLegendItem}>
                            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--critical)" }} />
                            <span>Core (&lt;30%)</span>
                          </div>
                          <div className={s.radarLegendItem}>
                            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--warning)" }} />
                            <span>Inner (30-65%)</span>
                          </div>
                          <div className={s.radarLegendItem}>
                            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--accent)" }} />
                            <span>Outer (65-90%)</span>
                          </div>
                        </div>
                      </div>

                      {/* Right: Blip / Selected Syndicate Details Card */}
                      <div>
                        {hoveredBlip ? (
                          <div className={s.syndicateClusterCard} style={{ borderColor: "var(--accent)" }}>
                            <div className={s.syndicateCardHeader}>
                              <span className={s.syndicateTitle}>
                                {hoveredBlip.blip_type === "SYNDICATE_CLUSTER" ? "🎯 Clustered Syndicate" : "📍 Colliding Identifier"}
                              </span>
                              <span className={s.threatTag} style={{
                                color: hoveredBlip.risk_level === "CRITICAL" ? "var(--critical)" : "var(--warning)"
                              }}>
                                {hoveredBlip.risk_level}
                              </span>
                            </div>
                            <div style={{ font: "var(--type-mono-sm)", color: "var(--text-primary)" }}>
                              {hoveredBlip.name || hoveredBlip.label}
                            </div>
                            <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                              Score: {hoveredBlip.score} · Cases Involved: {hoveredBlip.case_count}
                            </div>
                            {hoveredBlip.threat_indicators && (
                              <div className={s.threatTagList}>
                                {hoveredBlip.threat_indicators.map((t, ti) => (
                                  <span key={ti} className={s.threatTag}>{t}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className={s.syndicateClusterCard}>
                            <div className={s.syndicateCardHeader}>
                              <span className={s.syndicateTitle}>Radar Target Telemetry</span>
                              <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>Interactive Scope</span>
                            </div>
                            <p style={{ font: "var(--type-body-sm)", color: "var(--text-muted)", margin: 0 }}>
                              Hover over any radar blip on the polar crosshairs to inspect multi-case syndicate topology,
                              threat tags, and risk coordinates.
                            </p>
                            <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)", marginTop: "var(--space-2)" }}>
                              📡 Active Scanner: {syndicateRadar?.radar_blips?.length || 0} targets projected.
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Detected Syndicate Clusters Section */}
                    {(syndicateRadar?.syndicates || crossCase?.syndicates || []).length > 0 && (
                      <div style={{ marginBottom: "var(--space-6)" }}>
                        <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>
                          Coordinated Syndicate Networks ({syndicateRadar?.syndicates?.length || crossCase?.syndicates?.length || 0})
                        </div>
                        <div className={s.syndicateCardGrid}>
                          {(syndicateRadar?.syndicates || crossCase?.syndicates || []).map((syn, si) => (
                            <div
                              key={si}
                              className={s.syndicateClusterCard}
                              style={{
                                borderColor: selectedSyndicate === syn.cluster_id ? "var(--accent)" : undefined
                              }}
                              onClick={() => setSelectedSyndicate(selectedSyndicate === syn.cluster_id ? null : syn.cluster_id)}
                            >
                              <div className={s.syndicateCardHeader}>
                                <span className={s.syndicateTitle}>{syn.cluster_id}</span>
                                <span className={s.threatTag} style={{
                                  background: syn.risk_level === "CRITICAL" ? "rgba(255,77,79,0.15)" : "rgba(250,173,20,0.15)",
                                  color: syn.risk_level === "CRITICAL" ? "var(--critical)" : "var(--warning)"
                                }}>
                                  {syn.risk_level}
                                </span>
                              </div>

                              <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)" }}>
                                {syn.name}
                              </div>

                              <div className={s.cohesionMeter}>
                                <span>Cohesion Index: {(syn.cohesion_score * 100).toFixed(0)}% (Score: {syn.total_score})</span>
                                <div className={s.cohesionTrack}>
                                  <div className={s.cohesionFill} style={{ width: `${Math.min(100, syn.cohesion_score * 100)}%` }} />
                                </div>
                              </div>

                              {syn.threat_indicators?.length > 0 && (
                                <div className={s.threatTagList}>
                                  {syn.threat_indicators.map((tag, ti) => (
                                    <span key={ti} className={s.threatTag}>{tag}</span>
                                  ))}
                                </div>
                              )}

                              <div>
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginBottom: 4 }}>
                                  Linked Case Files ({syn.cases.length}):
                                </div>
                                <div className={s.memberCasesRow}>
                                  {syn.cases.map((mc, mci) => (
                                    <span key={mci} className={s.memberCaseChip} title={`${mc.case_title} (${mc.police_station})`}>
                                      {mc.case_number}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Filterable Collisions Audit Ledger */}
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-3)" }}>
                        <div className="t-label">Cross-Case Blind Index Collisions</div>
                        {/* Filter Tabs */}
                        <div style={{ display: "flex", gap: "var(--space-2)" }}>
                          {["ALL", "PHONE", "ACCOUNT", "UPI", "IP"].map(cat => (
                            <button
                              key={cat}
                              className={radarFilter === cat ? s.caseTag : s.memberCaseChip}
                              style={{ cursor: "pointer", border: "none" }}
                              onClick={() => setRadarFilter(cat)}
                            >
                              {cat}
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* Collision Rows */}
                      {(syndicateRadar?.collisions || []).length > 0 ? (
                        <div>
                          {syndicateRadar!.collisions
                            .filter(c => radarFilter === "ALL" || c.entity_type === radarFilter)
                            .map((col, idx) => (
                              <div key={idx} className={s.collisionRow}>
                                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                                  <span className={s.metaCategory}>{col.entity_type}</span>

                                  {/* Local Plaintext Anchor */}
                                  <div className={s.collisionAnchor}>
                                    <span style={{ fontWeight: 600 }}>
                                      {col.local_anchor.has_local_anchor ? col.local_anchor.plaintext_value : "[Local Entity Ref]"}
                                    </span>
                                    {col.local_anchor.provenance.source_file && (
                                      <span className={s.provenancePill}>
                                        📄 {col.local_anchor.provenance.source_file}
                                        {col.local_anchor.provenance.source_page ? ` (p.${col.local_anchor.provenance.source_page})` : ""}
                                      </span>
                                    )}
                                  </div>
                                </div>

                                {/* Blind Token */}
                                <div>
                                  <span className={s.collisionToken} title={col.blind_token}>
                                    HMAC:{col.blind_token.slice(0, 16)}…
                                  </span>
                                </div>

                                {/* Foreign Case Matches (Zero-Knowledge) */}
                                <div className={s.collisionCases}>
                                  {col.foreign_cases.map((fc, fci) => (
                                    <span key={fci} className={s.redactedCaseTag} title={`${fc.crime_type} · ${fc.police_station}`}>
                                      🔒 {fc.case_number}
                                    </span>
                                  ))}
                                </div>

                                {/* Ingress Score & Action */}
                                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                                  <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                    Score: <strong>{col.syndicate_score}</strong>
                                  </span>
                                  <Button
                                    variant="secondary"
                                    onClick={() => handleDraftInterStationRequisition(col)}
                                  >
                                    📄 Draft Sec. 94 Notice
                                  </Button>
                                </div>
                              </div>
                            ))}
                        </div>
                      ) : crossCase && crossCase.collisions.length > 0 ? (
                        /* Fallback: Global Cross-Case collisions if case-level radar is empty */
                        <div>
                          {crossCase.collisions.map((c, i) => (
                            <div key={i} className={s.collisionRow}>
                              <span className={s.metaCategory}>{c.entity_type}</span>
                              <span className={s.collisionToken}>{c.blind_token?.slice(0, 16)}…</span>
                              <div className={s.collisionCases}>
                                {(c.cases || c.case_ids || []).map((caseRef, j) => (
                                  <span key={j} className={s.caseTag}>{caseRef}</span>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className={s.emptyState} style={{ marginTop: "var(--space-4)" }}>
                          <div className={s.emptyIcon}>✅</div>
                          <div>No cross-case collisions detected for this case.</div>
                          <div style={{ font: "var(--type-body-sm)" }}>
                            All identifiers in this case appear isolated from other active case files.
                          </div>
                        </div>
                      )}

                      <p style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: "var(--space-4)", fontStyle: "italic" }}>
                        {syndicateRadar?.epistemic_notice || crossCase?.note || "Zero-Knowledge Blind Index Engine Active."}
                      </p>
                    </div>
                  </div>
                )}

                {/* ── Legal Compliance Shield Panel ─────────────────── */}
                {activeEngine === "verifier" && (
                  <div>
                    {/* Epistemic Humility Banner */}
                    <div className={s.shieldDisclaimer}>
                      <span style={{ fontSize: 18 }}>⚖️</span>
                      <div>
                        <strong>STATUTORY & TECHNICAL INTEGRITY AUDIT</strong> — In accordance with Section 63 of the
                        Bharatiya Sakshya Adhiniyam, 2023 (BSA), this compliance shield verifies cryptographic preservation,
                        chain of custody records, and in-force post-July-2024 statutory citations. Final evidentiary admissibility is strictly
                        determined by the trial court.
                      </div>
                    </div>

                    {/* Case Compliance Posture Cards */}
                    {complianceShield && (
                      <div className={s.shieldCardGrid}>
                        {/* Card 1: Section 63 BSA Evidence Integrity */}
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Section 63 BSA Evidence Integrity</div>
                          <div className={s.shieldScoreRow}>
                            <div className={s.cardValue} style={{ fontSize: "1.4rem" }}>
                              {complianceShield.evidence_integrity?.integrity_score ?? 0}%
                            </div>
                            <span className={
                              complianceShield.evidence_integrity?.status === "VERIFIED_INTEGRITY"
                                ? s.shieldVerdictCompliant
                                : s.shieldVerdictReview
                            }>
                              {complianceShield.evidence_integrity?.status === "VERIFIED_INTEGRITY"
                                ? "✅ Verified Integrity"
                                : "⚠️ Deficient Integrity"}
                            </span>
                          </div>
                          <div className={s.cardMeta} style={{ marginTop: "var(--space-2)", fontSize: "0.8rem" }}>
                            SHA-256 Preserved: {complianceShield.evidence_integrity?.hashed_files ?? 0} / {complianceShield.evidence_integrity?.total_files ?? 0} files
                          </div>
                          <div className={s.cardMeta} style={{ fontSize: "0.8rem", color: complianceShield.evidence_integrity?.has_custody_memo ? "var(--verified)" : "var(--warning)" }}>
                            {complianceShield.evidence_integrity?.has_custody_memo
                              ? "✓ File 10 Chain of Custody Memo Certified"
                              : "⚠ Custody Memo (File 10) Missing"}
                          </div>
                        </div>

                        {/* Card 2: Post-July-2024 Statutory Alignment */}
                        <div className={s.dataCard}>
                          <div className={s.cardLabel}>Statutory Alignment (July 1, 2024)</div>
                          <div className={s.shieldScoreRow}>
                            <div className={s.cardValue} style={{ fontSize: "1.1rem" }}>
                              {complianceShield.statutory_compliance?.statutory_framework}
                            </div>
                            <span className={
                              complianceShield.overall_status === "COMPLIANT"
                                ? s.shieldVerdictCompliant
                                : complianceShield.overall_status === "NEEDS_REVIEW"
                                ? s.shieldVerdictReview
                                : s.shieldVerdictBlocked
                            }>
                              {complianceShield.overall_status}
                            </span>
                          </div>
                          <div className={s.cardMeta} style={{ marginTop: "var(--space-2)", fontSize: "0.8rem" }}>
                            Findings Citations: {complianceShield.statutory_compliance?.in_force_count ?? 0} In-Force · {complianceShield.statutory_compliance?.legacy_citations_count ?? 0} Legacy
                          </div>
                          <div className={s.cardMeta} style={{ fontSize: "0.8rem" }}>
                            {complianceShield.governance_posture?.active_blocks > 0
                              ? `⛔ ${complianceShield.governance_posture.active_blocks} Active Governance Block`
                              : `🛡️ Zero struck-down statutes active`}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Interactive Legal AST & Grounding Studio */}
                    <div style={{ marginTop: "var(--space-4)", marginBottom: "var(--space-2)" }}>
                      <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>Interactive Statutory & Fact Grounding Studio</div>
                      <p className="t-body-sm" style={{ color: "var(--text-secondary)", margin: 0, marginBottom: "var(--space-3)" }}>
                        Paste draft FIRs, remand applications, chargesheets, or intelligence summaries to audit citations against post-July-2024 statutes and verify facts against case evidence.
                      </p>
                      <div className={s.presetRow}>
                        <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", alignSelf: "center", marginRight: 4 }}>
                          Quick Presets:
                        </span>
                        <button
                          type="button"
                          className={s.presetBtn}
                          onClick={() => setVerifyText(
                            "Investigation conducted under Section 173 BNSS confirms cyber fraud under Section 318(4) BNS and Section 66D IT Act. Electronic evidence preserved under Section 63 BSA with SHA-256 integrity verification."
                          )}
                        >
                          Compliant BNS/BSA Report
                        </button>
                        <button
                          type="button"
                          className={s.presetBtn}
                          onClick={() => setVerifyText(
                            "FIR registered under Section 420 IPC and Section 66D IT Act. Police requested bank freeze under Section 102 CrPC. Dual certificate u/s 65B of Evidence Act prepared for CDR logs."
                          )}
                        >
                          Legacy IPC / CrPC Draft
                        </button>
                        <button
                          type="button"
                          className={s.presetBtn}
                          onClick={() => setVerifyText(
                            "Accused charged under Section 66A of Information Technology Act 2000 for posting offensive messages on online social networks."
                          )}
                        >
                          Struck-Down Law (IT Act 66A)
                        </button>
                      </div>
                    </div>

                    <textarea
                      className={s.inputField}
                      style={{ minHeight: 110, resize: "vertical", padding: "var(--space-3) var(--space-4)", width: "100%", boxSizing: "border-box" }}
                      placeholder="Paste draft chargesheet, FIR, remand petition, or case summary to audit…"
                      value={verifyText}
                      onChange={e => setVerifyText(e.target.value)}
                    />
                    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "var(--space-3)" }}>
                      <Button variant="primary" onClick={handleVerify} disabled={loading || !verifyText.trim()}>
                        Audit Statutory Compliance & Grounding
                      </Button>
                    </div>

                    {/* Verification Result Display */}
                    {verifyResult && (
                      <div className={
                        verifyResult.governance_verdict === "GOVERNANCE_BLOCKED"
                          ? s.verifierFailed
                          : verifyResult.governance_verdict === "NEEDS_REVIEW"
                          ? s.verifierFailed
                          : s.verifierPassed
                      } style={{ marginTop: "var(--space-4)" }}>
                        {/* Governance Header */}
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-3)" }}>
                          <div className={
                            verifyResult.governance_verdict === "GOVERNANCE_BLOCKED"
                              ? s.verifierFailedTitle
                              : verifyResult.governance_verdict === "NEEDS_REVIEW"
                              ? s.verifierTitle
                              : s.verifierPassedTitle
                          }>
                            <span>
                              {verifyResult.governance_verdict === "COMPLIANT" ? "✅" : verifyResult.governance_verdict === "GOVERNANCE_BLOCKED" ? "⛔" : "⚠️"}
                            </span>
                            <span>
                              GOVERNANCE POSTURE: {verifyResult.governance_verdict || (verifyResult.passed ? "COMPLIANT" : "NEEDS_REVIEW")}
                            </span>
                          </div>
                          <span className={
                            verifyResult.governance_verdict === "COMPLIANT"
                              ? s.shieldVerdictCompliant
                              : verifyResult.governance_verdict === "GOVERNANCE_BLOCKED"
                              ? s.shieldVerdictBlocked
                              : s.shieldVerdictReview
                          }>
                            {verifyResult.governance_verdict}
                          </span>
                        </div>

                        {verifyResult.summary && (
                          <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-3)" }}>
                            {verifyResult.summary}
                          </div>
                        )}

                        {/* AST Citation Nodes */}
                        {verifyResult.citations && verifyResult.citations.length > 0 && (
                          <div style={{ marginTop: "var(--space-3)" }}>
                            <div className="t-label" style={{ fontSize: "0.75rem", marginBottom: "var(--space-2)" }}>
                              Parsed Statutory Citations (AST)
                            </div>
                            <div className={s.astChipGrid}>
                              {verifyResult.citations.map((c, i) => (
                                <div
                                  key={i}
                                  className={`${s.astChip} ${
                                    c.status === "in_force"
                                      ? s.astInForce
                                      : c.status === "struck_down"
                                      ? s.astStruckDown
                                      : s.astPreTransition
                                  }`}
                                >
                                  <div>
                                    <strong>{c.section} {c.act || ""}</strong>
                                    {c.title && <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>— {c.title}</span>}
                                  </div>
                                  <div>
                                    {c.status === "in_force" && (
                                      <span style={{ color: "var(--verified)", fontWeight: 600 }}>Post-2024 In-Force</span>
                                    )}
                                    {c.status === "pre_transition_act" && (
                                      <span style={{ color: "var(--warning)", fontWeight: 600 }}>
                                        Pre-Transition → Modernize to {c.replacement || "BNS / BNSS / BSA"}
                                      </span>
                                    )}
                                    {c.status === "struck_down" && (
                                      <span style={{ color: "var(--critical)", fontWeight: 600 }}>
                                        STRUCK DOWN ({c.judicial_authority || "Supreme Court"})
                                      </span>
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Grounded Evidence Spans */}
                        {verifyResult.grounded_spans && verifyResult.grounded_spans.length > 0 && (
                          <div style={{ marginTop: "var(--space-3)" }}>
                            <div className="t-label" style={{ fontSize: "0.75rem", marginBottom: "var(--space-2)" }}>
                              Case Evidence Fact Grounding
                            </div>
                            <div className={s.groundedSpansGrid}>
                              {verifyResult.grounded_spans.map((sp, i) => (
                                <span
                                  key={i}
                                  className={`${s.groundedSpanChip} ${sp.grounded ? s.groundedSuccess : s.groundedFailure}`}
                                >
                                  <span>{sp.grounded ? "✓" : "✗"}</span>
                                  <strong>{sp.claim_type}:</strong> {sp.raw_value}
                                  {!sp.grounded && <span style={{ opacity: 0.8 }}>(Missing from Evidence)</span>}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Flags List */}
                        {verifyResult.flags && verifyResult.flags.length > 0 && (
                          <div style={{ marginTop: "var(--space-3)" }}>
                            <div className="t-label" style={{ fontSize: "0.75rem", marginBottom: "var(--space-2)" }}>
                              Compliance Issues & Remediation Flags
                            </div>
                            {verifyResult.flags.map((f, i) => (
                              <div key={i} className={s.flagRow}>
                                <span className={
                                  f.severity === "error" ? s.flagError :
                                  f.severity === "warning" ? s.flagWarn : s.flagInfo
                                }>
                                  {f.severity}
                                </span>
                                <span className={s.flagMessage}>{f.message}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* ── Defence Bot Panel ─────────────────────────────── */}
                {activeEngine === "defence_bot" && (
                  <div>
                    {/* Epistemic Humility Banner */}
                    <div style={{
                      padding: "var(--space-4)",
                      background: "rgba(139, 92, 246, 0.06)",
                      border: "1px solid rgba(139, 92, 246, 0.25)",
                      borderRadius: "var(--radius-input)",
                      marginBottom: "var(--space-5)",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "var(--space-3)",
                    }}>
                      <span style={{ fontSize: 20 }}>⚖️</span>
                      <div>
                        <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 2 }}>
                          Adversarial Red-Team Simulator · Judicial Defensibility Disclaimer
                        </div>
                        <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", margin: 0, lineHeight: 1.5 }}>
                          {defenceAudit?.epistemic_notice || "Defence Bot simulates courtroom defense cross-examination to stress-test prosecution defensibility before chargesheet filing under Section 193 BNSS. It does NOT determine legal guilt or innocence, which remains exclusively within the purview of the trial court."}
                        </p>
                      </div>
                    </div>

                    {defenceAudit && (
                      <div>
                        {/* 4-Card Defensibility Metrics Grid */}
                        <div className={s.cardGrid} style={{ marginBottom: "var(--space-6)" }}>
                          <div className={s.dataCard}>
                            <div className={s.cardLabel}>Defensibility Index</div>
                            <div className={s.cardValue} style={{
                              color: defenceAudit.defensibility_score >= 0.75 ? "var(--verified)" : defenceAudit.defensibility_score >= 0.55 ? "var(--warning)" : "var(--critical)"
                            }}>
                              {Math.round(defenceAudit.defensibility_score * 100)}%
                            </div>
                            <div className={s.cardSubtext}>Trial court defensibility score</div>
                          </div>

                          <div className={s.dataCard}>
                            <div className={s.cardLabel}>Trial Risk Rating</div>
                            <div className={s.cardValue} style={{
                              fontSize: 18,
                              color: defenceAudit.risk_level === "LOW_RISK" ? "var(--verified)" : defenceAudit.risk_level === "MODERATE_RISK" ? "var(--warning)" : "var(--critical)"
                            }}>
                              {defenceAudit.risk_level.replace("_", " ")}
                            </div>
                            <div className={s.cardSubtext}>Vulnerability to defense dismissal</div>
                          </div>

                          <div className={s.dataCard}>
                            <div className={s.cardLabel}>Theories Red-Teamed</div>
                            <div className={s.cardValue} style={{ color: "var(--intel)" }}>
                              {defenceAudit.total_hypotheses_tested}
                            </div>
                            <div className={s.cardSubtext}>Active investigative hypotheses</div>
                          </div>

                          <div className={s.dataCard}>
                            <div className={s.cardLabel}>Section 63 BSA Custody</div>
                            <div className={s.cardValue} style={{
                              fontSize: 18,
                              color: defenceAudit.bsa_compliance_status.compliant_with_bsa_63 ? "var(--verified)" : "var(--warning)"
                            }}>
                              {Math.round((defenceAudit.bsa_compliance_status.preservation_score || 0) * 100)}% Hashed
                            </div>
                            <div className={s.cardSubtext}>
                              {defenceAudit.bsa_compliance_status.has_seizure_memo ? "File 10 Seizure Memo Attested" : "⚠️ Missing Seizure Panchnama"}
                            </div>
                          </div>
                        </div>

                        {/* Adversarial Hypothesis Stress-Test Deck */}
                        <h4 className="t-label" style={{ color: "var(--text-secondary)", marginBottom: "var(--space-3)", letterSpacing: "0.05em" }}>
                          ADVERSARIAL HYPOTHESIS STRESS TESTS ({defenceAudit.challenges.length})
                        </h4>

                        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)", marginBottom: "var(--space-8)" }}>
                          {defenceAudit.challenges.map((ch, idx) => (
                            <div key={ch.challenge_id || idx} style={{
                              background: "rgba(255, 255, 255, 0.02)",
                              border: `1px solid ${ch.vulnerability_severity === "CRITICAL" ? "rgba(255, 92, 92, 0.3)" : ch.vulnerability_severity === "HIGH" ? "rgba(255, 193, 7, 0.3)" : "rgba(88, 166, 255, 0.2)"}`,
                              borderRadius: "var(--radius-card)",
                              padding: "var(--space-4)",
                            }}>
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-3)" }}>
                                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                                  <span style={{
                                    padding: "2px 8px",
                                    borderRadius: "4px",
                                    font: "var(--type-mono-xs)",
                                    background: ch.vulnerability_severity === "CRITICAL" ? "rgba(255, 92, 92, 0.15)" : ch.vulnerability_severity === "HIGH" ? "rgba(255, 193, 7, 0.15)" : "rgba(88, 166, 255, 0.15)",
                                    color: ch.vulnerability_severity === "CRITICAL" ? "var(--critical)" : ch.vulnerability_severity === "HIGH" ? "var(--warning)" : "var(--intel)",
                                    letterSpacing: "0.04em",
                                  }}>
                                    {ch.vulnerability_severity}
                                  </span>
                                  <span style={{ font: "var(--type-mono-sm)", color: "var(--text-primary)", fontWeight: 600 }}>
                                    🎯 {ch.target_hypothesis}
                                  </span>
                                  {ch.target_entity && (
                                    <span style={{ font: "var(--type-mono-xs)", color: "var(--accent)" }}>
                                      · {ch.target_entity}
                                    </span>
                                  )}
                                </div>
                              </div>

                              {/* Defense Counter-Hypothesis */}
                              <div style={{
                                padding: "var(--space-3)",
                                background: "rgba(255, 255, 255, 0.02)",
                                borderLeft: "3px solid var(--intel)",
                                borderRadius: "0 var(--radius-input) var(--radius-input) 0",
                                marginBottom: "var(--space-3)",
                              }}>
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", marginBottom: 4 }}>
                                  ⚖️ DEFENSE COUNTER-HYPOTHESIS (ALTERNATIVE EXPLANATION)
                                </div>
                                <p style={{ font: "var(--type-body-sm)", color: "var(--text-primary)", margin: 0, lineHeight: 1.5 }}>
                                  {ch.defense_counter_hypothesis}
                                </p>
                              </div>

                              {/* Reasonable Doubts */}
                              {ch.reasonable_doubts.length > 0 && (
                                <div style={{ marginBottom: "var(--space-3)" }}>
                                  <div style={{ font: "var(--type-mono-xs)", color: "var(--warning)", marginBottom: 4 }}>
                                    🚩 REASONABLE DOUBTS (DEFENSE ATTACK POINTS)
                                  </div>
                                  <ul style={{ margin: 0, paddingLeft: "var(--space-4)", color: "var(--text-secondary)", font: "var(--type-body-sm)" }}>
                                    {ch.reasonable_doubts.map((rd, i) => (
                                      <li key={i} style={{ marginBottom: 2 }}>{rd}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              {/* Missing Critical Evidence */}
                              {ch.missing_evidence.length > 0 && (
                                <div style={{ marginBottom: "var(--space-3)" }}>
                                  <div style={{ font: "var(--type-mono-xs)", color: "var(--critical)", marginBottom: 6 }}>
                                    📄 MISSING CRITICAL EVIDENCE REQUIRED BY COURT
                                  </div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
                                    {ch.missing_evidence.map((m, i) => (
                                      <div key={i} style={{
                                        padding: "4px 8px",
                                        background: "rgba(255, 92, 92, 0.08)",
                                        border: "1px solid rgba(255, 92, 92, 0.2)",
                                        borderRadius: "var(--radius-input)",
                                        font: "var(--type-body-xs)",
                                        color: "var(--text-secondary)",
                                      }}>
                                        <strong style={{ color: "var(--text-primary)" }}>{m.item}</strong> — {m.reason} ({m.statutory_rule})
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {/* Rebuttal Action Plan */}
                              {ch.rebuttal_strategy.length > 0 && (
                                <div style={{
                                  padding: "var(--space-3)",
                                  background: "rgba(80, 200, 120, 0.04)",
                                  border: "1px solid rgba(80, 200, 120, 0.2)",
                                  borderRadius: "var(--radius-input)",
                                }}>
                                  <div style={{ font: "var(--type-mono-xs)", color: "var(--verified)", marginBottom: 4 }}>
                                    ⚔️ PROSECUTION REBUTTAL COUNTERMEASURES (BEFORE CHARGESHEET FILING)
                                  </div>
                                  <ul style={{ margin: 0, paddingLeft: "var(--space-4)", color: "var(--text-secondary)", font: "var(--type-body-sm)" }}>
                                    {ch.rebuttal_strategy.map((r, i) => (
                                      <li key={i} style={{ marginBottom: 2 }}>
                                        <strong style={{ color: "var(--text-primary)" }}>[{r.statute}]</strong> {r.recommendation}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Interactive Cross-Examination Studio */}
                    <div style={{
                      padding: "var(--space-5)",
                      background: "rgba(255, 255, 255, 0.015)",
                      border: "1px solid var(--line)",
                      borderRadius: "var(--radius-card)",
                    }}>
                      <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
                        CROSS-EXAMINATION SIMULATOR & ADVERSARIAL STRESS-TEST STUDIO
                      </h4>
                      <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginBottom: "var(--space-4)" }}>
                        Enter an investigator's hypothesis, accusation, or draft theory to simulate defense counsel scrutiny and expose evidentiary vulnerabilities.
                      </p>

                      {/* Presets */}
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)", marginBottom: "var(--space-3)" }}>
                        <button
                          type="button"
                          className={s.presetBtn}
                          onClick={() => {
                            const p = "Suspect Rohan received ₹48,500 and transferred ₹47,000 as a Layer-1 mule in the cyber extortion conspiracy.";
                            setDefenceClaim(p);
                            handleDefenceStressTest(p);
                          }}
                        >
                          ⚖️ Preset: Mule Role Challenge (rohan@upi)
                        </button>
                        <button
                          type="button"
                          className={s.presetBtn}
                          onClick={() => {
                            const p = "Seized digital records prove digital extortion without needing physical device examination.";
                            setDefenceClaim(p);
                            handleDefenceStressTest(p);
                          }}
                        >
                          🛡️ Preset: Section 63 BSA Chain of Custody
                        </button>
                        <button
                          type="button"
                          className={s.presetBtn}
                          onClick={() => {
                            const p = "Telecom tower ping proves suspect +91-98XXXX1201 was physically present at the crime location.";
                            setDefenceClaim(p);
                            handleDefenceStressTest(p);
                          }}
                        >
                          📡 Preset: Telecom Tower Alibi Challenge
                        </button>
                      </div>

                      <textarea
                        className={s.studioTextarea}
                        rows={3}
                        placeholder="Enter investigative theory or draft finding to red-team (e.g. 'Suspect was operating the mule account with full criminal knowledge...')"
                        value={defenceClaim}
                        onChange={e => setDefenceClaim(e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", marginBottom: "var(--space-3)" }}
                      />

                      <Button
                        variant="primary"
                        onClick={() => handleDefenceStressTest()}
                        disabled={defenceStressLoading || !defenceClaim.trim()}
                      >
                        {defenceStressLoading ? "Simulating Defense Cross-Examination…" : "Stress-Test Theory (⚖️ Red Team)"}
                      </Button>

                      {/* Stress Test Results */}
                      {defenceStressResult && (
                        <div style={{
                          marginTop: "var(--space-5)",
                          padding: "var(--space-4)",
                          background: "var(--surface-2)",
                          border: "1px solid var(--line)",
                          borderRadius: "var(--radius-card)",
                        }}>
                          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-3)" }}>
                            <span style={{ font: "var(--type-mono-xs)", color: "var(--intel)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                              Adversarial Cross-Examination Output ({defenceStressResult.model_used})
                            </span>
                            <span style={{
                              padding: "2px 8px",
                              borderRadius: "4px",
                              font: "var(--type-mono-xs)",
                              background: "rgba(139, 92, 246, 0.15)",
                              color: "var(--intel)",
                            }}>
                              {defenceStressResult.adversarial_posture}
                            </span>
                          </div>

                          <div style={{
                            font: "var(--type-body-sm)",
                            color: "var(--text-primary)",
                            lineHeight: 1.6,
                            whiteSpace: "pre-wrap",
                          }}>
                            {defenceStressResult.answer}
                          </div>

                          {defenceStressResult.verification && (
                            <div style={{
                              marginTop: "var(--space-4)",
                              padding: "var(--space-3)",
                              background: defenceStressResult.verification.passed ? "rgba(80, 200, 120, 0.05)" : "rgba(255, 193, 7, 0.05)",
                              border: `1px solid ${defenceStressResult.verification.passed ? "rgba(80, 200, 120, 0.2)" : "rgba(255, 193, 7, 0.2)"}`,
                              borderRadius: "var(--radius-input)",
                              font: "var(--type-mono-xs)",
                              color: defenceStressResult.verification.passed ? "var(--verified)" : "var(--warning)",
                            }}>
                              🛡️ Output Verifier: {defenceStressResult.verification.passed ? "All statutory & entity citations verified against case facts." : "Statutory / grounding warnings detected."}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* ── Feature 11: Training Simulator Panel ─────────────────────── */}
                {activeEngine === "benchmark" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                    {/* Statutory Notice Banner */}
                    <div className={s.trainingNoticeBanner}>
                      <span className={s.trainingNoticeIcon}>🎓</span>
                      <div>
                        <strong>NETRA TRAINING SIMULATOR & COGNITIVE BENCHMARK</strong> — DPDP Act 2023 Compliant.
                        All incident scenarios, CDRs, chats, and bank records are synthetically generated for officer skill development. Strictly isolated from active casework.
                      </div>
                    </div>

                    {/* Mission Catalog (Drill Selector) */}
                    {!activeTrainingSession ? (
                      <div>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-3)", flexWrap: "wrap", gap: "var(--space-2)" }}>
                          <div>
                            <h3 style={{ font: "var(--type-body)", fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
                              🎯 Select Investigation Drill Mission
                            </h3>
                            <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", margin: "4px 0 0 0" }}>
                              Choose a structured investigation drill to practice MO identification, hidden link discovery, BSA Section 63 audits, and golden hours response.
                            </p>
                          </div>
                          {/* Difficulty Filter */}
                          <div style={{ display: "flex", gap: "var(--space-1)" }}>
                            {["ALL", "BEGINNER", "INTERMEDIATE", "ADVANCED"].map(diff => (
                              <button
                                key={diff}
                                onClick={() => setTrainingDifficultyFilter(diff)}
                                className={trainingDifficultyFilter === diff ? s.filterBtnActive : s.filterBtn}
                                style={{ padding: "4px 10px", fontSize: "11px" }}
                              >
                                {diff}
                              </button>
                            ))}
                          </div>
                        </div>

                        {/* Drills Grid */}
                        <div className={s.drillSelectorGrid}>
                          {trainingDrills
                            .filter(d => trainingDifficultyFilter === "ALL" || d.difficulty === trainingDifficultyFilter)
                            .map(drill => (
                              <div
                                key={drill.id}
                                className={`${s.drillCard} ${selectedDrillId === drill.id ? s.drillCardActive : ""}`}
                                onClick={() => setSelectedDrillId(drill.id)}
                              >
                                <div>
                                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-2)" }}>
                                    <span className={`${s.difficultyBadge} ${
                                      drill.difficulty === "BEGINNER" ? s.diffBeginner :
                                      drill.difficulty === "INTERMEDIATE" ? s.diffIntermediate : s.diffAdvanced
                                    }`}>
                                      {drill.difficulty}
                                    </span>
                                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                      {drill.tasks_count} Tasks
                                    </span>
                                  </div>
                                  <h4 style={{ font: "var(--type-body-sm)", fontWeight: 700, color: "var(--text-primary)", margin: "0 0 var(--space-2) 0" }}>
                                    {drill.title}
                                  </h4>
                                  <p style={{ font: "var(--type-body-xs)", color: "var(--text-secondary)", margin: 0, lineHeight: 1.5 }}>
                                    {drill.incident_brief.slice(0, 140)}...
                                  </p>
                                </div>
                                <div style={{ marginTop: "var(--space-4)" }}>
                                  <Button
                                    variant="primary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleStartTrainingDrill(drill.id);
                                    }}
                                    disabled={startingDrill}
                                    style={{ width: "100%" }}
                                  >
                                    {startingDrill && selectedDrillId === drill.id ? "Initializing Drill..." : "🚀 Launch Mission"}
                                  </Button>
                                </div>
                              </div>
                            ))}
                        </div>

                        {/* Custom Raw Benchmark Generation (Legacy/Developer) */}
                        <div style={{ marginTop: "var(--space-5)", padding: "var(--space-4)", background: "var(--surface-1)", borderRadius: "var(--radius-card)", border: "1px dashed var(--line)" }}>
                          <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "var(--space-2)" }}>
                            🧪 Developer Benchmark Generator (Raw Case Seeder)
                          </div>
                          <div className={s.inputRow}>
                            <select
                              className={s.inputField}
                              value={benchTypology}
                              onChange={e => setBenchTypology(e.target.value)}
                              style={{ maxWidth: 260 }}
                            >
                              <option value="DIGITAL_ARREST">Digital Arrest Extortion</option>
                              <option value="INVESTMENT_TASK">Investment & Task Fraud</option>
                              <option value="MULE_OFFRAMP">Mule Harvesting & Offramping</option>
                              <option value="LOAN_APP_EXTORTION">Instant Loan Harassment</option>
                              <option value="ROMANCE_CRYPTO">Romance Baiting & Crypto</option>
                            </select>
                            <Button variant="secondary" onClick={handleBenchmark} disabled={loading}>
                              Generate Raw Synthetic Case
                            </Button>
                          </div>
                          {benchmark && (
                            <div style={{ marginTop: "var(--space-3)", font: "var(--type-mono-xs)", color: "var(--accent)" }}>
                              ✓ Generated raw case: {benchmark.case_id} ({benchmark.entities_count} entities, {benchmark.flow_edges_count} edges, {benchmark.hidden_links_count} hidden links)
                            </div>
                          )}
                        </div>
                      </div>
                    ) : (
                      /* Active Mission Workspace */
                      <div className={s.missionWorkspace}>
                        {/* Mission Header Card */}
                        <div className={s.missionHeaderCard}>
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: 4 }}>
                              <span className={`${s.difficultyBadge} ${
                                activeTrainingSession.difficulty === "BEGINNER" ? s.diffBeginner :
                                activeTrainingSession.difficulty === "INTERMEDIATE" ? s.diffIntermediate : s.diffAdvanced
                              }`}>
                                {activeTrainingSession.difficulty}
                              </span>
                              <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                Seed: #{activeTrainingSession.seed}
                              </span>
                              {activeTrainingSession.is_evaluated ? (
                                <span style={{
                                  padding: "2px 8px",
                                  borderRadius: 4,
                                  font: "var(--type-mono-xs)",
                                  fontWeight: 700,
                                  background: "rgba(52, 211, 153, 0.15)",
                                  color: "#34d399",
                                }}>
                                  ✓ GRADED: {activeTrainingSession.evaluation?.score_pct}%
                                </span>
                              ) : (
                                <span style={{
                                  padding: "2px 8px",
                                  borderRadius: 4,
                                  font: "var(--type-mono-xs)",
                                  background: "rgba(251, 191, 36, 0.15)",
                                  color: "#fbbf24",
                                }}>
                                  IN PROGRESS
                                </span>
                              )}
                            </div>
                            <h2 style={{ font: "var(--type-heading-sm)", fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
                              {activeTrainingSession.title}
                            </h2>
                          </div>

                          <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
                            <Button
                              variant="secondary"
                              onClick={() => {
                                setActiveTrainingSession(null);
                                setTrainingOfficerAnswers({});
                                setTrainingHints(null);
                              }}
                            >
                              ← Switch Mission
                            </Button>
                            {activeTrainingSession.is_evaluated && (
                              <Button
                                variant="secondary"
                                onClick={handleExportTrainingCase}
                                disabled={exportingCase}
                              >
                                {exportingCase ? "Exporting..." : "💾 Export to Case Sandbox"}
                              </Button>
                            )}
                          </div>
                        </div>

                        {exportSuccessMessage && (
                          <div style={{ padding: "var(--space-3)", background: "rgba(52, 211, 153, 0.1)", border: "1px solid rgba(52, 211, 153, 0.3)", borderRadius: "var(--radius-input)", font: "var(--type-mono-xs)", color: "#34d399" }}>
                            {exportSuccessMessage}
                          </div>
                        )}

                        {/* Incident Briefing Card */}
                        <div className={s.briefingCard}>
                          <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "var(--space-2)" }}>
                            📋 Incident Briefing & Complainant Statement
                          </div>
                          <p style={{ font: "var(--type-body-sm)", color: "var(--text-primary)", margin: 0, lineHeight: 1.6 }}>
                            {activeTrainingSession.incident_brief}
                          </p>
                        </div>

                        {/* Evidence Locker Viewer */}
                        <div className={s.evidenceLockerCard}>
                          <div className={s.evidenceLockerHeader}>
                            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                              <span style={{ font: "var(--type-body-sm)", fontWeight: 700, color: "var(--text-primary)" }}>
                                📁 Synthetic Evidence Locker
                              </span>
                              <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                ({Object.keys(activeTrainingSession.artifacts).length} files)
                              </span>
                            </div>
                            <Button
                              variant="secondary"
                              onClick={handleFetchTrainingHints}
                              disabled={loadingHints}
                              style={{ fontSize: "11px", padding: "4px 10px" }}
                            >
                              {loadingHints ? "Consulting AI..." : "🤖 Ask NETRA AI Co-Pilot"}
                            </Button>
                          </div>

                          {/* Artifacts Tab Navigation */}
                          <div className={s.evidenceTabBar}>
                            {Object.keys(activeTrainingSession.artifacts).map(k => (
                              <button
                                key={k}
                                onClick={() => setTrainingActiveArtifactTab(k)}
                                className={`${s.evidenceTabBtn} ${trainingActiveArtifactTab === k ? s.evidenceTabBtnActive : ""}`}
                              >
                                📄 {k}
                              </button>
                            ))}
                          </div>

                          {/* Artifact Content Preview */}
                          <div className={s.evidenceContentBox}>
                            {(() => {
                              const art = activeTrainingSession.artifacts[trainingActiveArtifactTab];
                              if (!art) return <div>No artifact selected.</div>;
                              if (art.type === "table" && Array.isArray(art.raw)) {
                                return (
                                  <table style={{ width: "100%", borderCollapse: "collapse", font: "var(--type-mono-xs)" }}>
                                    <thead>
                                      <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.1)", textAlign: "left", color: "var(--accent)" }}>
                                        {Object.keys(art.raw[0] || {}).map(col => (
                                          <th key={col} style={{ padding: "6px 8px" }}>{col}</th>
                                        ))}
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {art.raw.map((row: any, rIdx: number) => (
                                        <tr key={rIdx} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                                          {Object.values(row).map((val: any, cIdx: number) => (
                                            <td key={cIdx} style={{ padding: "6px 8px" }}>
                                              {typeof val === "object" ? JSON.stringify(val) : String(val)}
                                            </td>
                                          ))}
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                );
                              }
                              return <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{art.raw || art.preview}</pre>;
                            })()}
                          </div>
                        </div>

                        {/* NETRA AI Co-Pilot Hints */}
                        {trainingHints && (
                          <div className={s.hintsBox}>
                            <div style={{ font: "var(--type-mono-xs)", color: "#10b981", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "var(--space-3)", fontWeight: 700 }}>
                              🤖 NETRA Cognitive Engine Analysis & Co-Pilot Insights
                            </div>
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "var(--space-3)" }}>
                              <div style={{ background: "rgba(0,0,0,0.3)", padding: "var(--space-3)", borderRadius: "var(--radius-input)" }}>
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>MO FINGERPRINT</div>
                                <div style={{ font: "var(--type-body-sm)", color: "#10b981", fontWeight: 700 }}>
                                  {trainingHints.mo_engine.best_playbook || "No Confident Match"}
                                </div>
                                <div style={{ font: "var(--type-body-xs)", color: "var(--text-secondary)" }}>
                                  Similarity: {(trainingHints.mo_engine.similarity * 100).toFixed(0)}%
                                </div>
                              </div>

                              <div style={{ background: "rgba(0,0,0,0.3)", padding: "var(--space-3)", borderRadius: "var(--radius-input)" }}>
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>DEFENCE BOT</div>
                                <div style={{ font: "var(--type-body-sm)", color: "#f59e0b", fontWeight: 700 }}>
                                  Risk: {trainingHints.defence_bot_engine.risk_level}
                                </div>
                                <div style={{ font: "var(--type-body-xs)", color: "var(--text-secondary)" }}>
                                  Challenges: {trainingHints.defence_bot_engine.challenges_count} item(s)
                                </div>
                              </div>

                              <div style={{ background: "rgba(0,0,0,0.3)", padding: "var(--space-3)", borderRadius: "var(--radius-input)" }}>
                                <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>GOLDEN HOURS ACTION</div>
                                <div style={{ font: "var(--type-body-sm)", color: "var(--accent)", fontWeight: 700 }}>
                                  {trainingHints.nextbest_engine.top_action || "Notice u/s 94 BNSS"}
                                </div>
                                <div style={{ font: "var(--type-body-xs)", color: "var(--text-secondary)" }}>
                                  Statute: {trainingHints.nextbest_engine.statutory_basis || "Section 94 BNSS"}
                                </div>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Officer Answer Sheet / Questionnaire */}
                        {!activeTrainingSession.is_evaluated ? (
                          <div className={s.answerSheetCard}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-4)" }}>
                              <div>
                                <h3 style={{ font: "var(--type-body)", fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
                                  📝 Officer Investigation Answer Pad
                                </h3>
                                <p style={{ font: "var(--type-body-xs)", color: "var(--text-secondary)", margin: "2px 0 0 0" }}>
                                  Answer all 4 investigative prompts based on your review of the synthetic evidence locker.
                                </p>
                              </div>
                              <span style={{ font: "var(--type-mono-xs)", color: "var(--accent)" }}>
                                100 Total Points
                              </span>
                            </div>

                            {activeTrainingSession.tasks.map((task, idx) => (
                              <div key={task.task_id} className={s.taskQuestionBlock}>
                                <div className={s.taskMetaRow}>
                                  <span className={s.pillarTag}>
                                    Pillar {idx + 1}: {task.pillar.replace("_", " ").toUpperCase()}
                                  </span>
                                  <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                                    {task.points} pts
                                  </span>
                                </div>
                                <div style={{ font: "var(--type-body-sm)", fontWeight: 600, color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                                  {idx + 1}. {task.prompt}
                                </div>

                                <div className={s.optionsList}>
                                  {task.options.map(opt => {
                                    const isSelected = trainingOfficerAnswers[task.task_id] === opt.id;
                                    return (
                                      <label
                                        key={opt.id}
                                        className={`${s.optionLabel} ${isSelected ? s.optionLabelSelected : ""}`}
                                        onClick={() => {
                                          setTrainingOfficerAnswers(prev => ({
                                            ...prev,
                                            [task.task_id]: opt.id,
                                          }));
                                        }}
                                      >
                                        <input
                                          type="radio"
                                          name={task.task_id}
                                          value={opt.id}
                                          checked={isSelected}
                                          onChange={() => {}}
                                          style={{ marginTop: 3 }}
                                        />
                                        <span>{opt.label}</span>
                                      </label>
                                    );
                                  })}
                                </div>
                              </div>
                            ))}

                            <div style={{ marginTop: "var(--space-5)", display: "flex", justifyContent: "flex-end" }}>
                              <Button
                                variant="primary"
                                onClick={handleSubmitTrainingDrill}
                                disabled={submittingDrill || Object.keys(trainingOfficerAnswers).length < activeTrainingSession.tasks.length}
                              >
                                {submittingDrill ? "Evaluating Submissions..." : "📋 Submit Investigation for Grading & Debrief"}
                              </Button>
                            </div>
                          </div>
                        ) : (
                          /* Mission Scorecard & Pedagogical Debrief Dashboard */
                          <div>
                            {activeTrainingSession.evaluation && (
                              <div>
                                {/* Scorecard Hero Banner */}
                                <div className={s.scorecardHero}>
                                  <div>
                                    <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                                      DRILL EVALUATION SCORECARD
                                    </div>
                                    <h2 style={{ font: "var(--type-heading-md)", fontWeight: 800, color: "var(--text-primary)", margin: "0 0 6px 0" }}>
                                      {activeTrainingSession.evaluation.tier_badge}
                                    </h2>
                                    <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", maxWidth: 550, margin: 0, lineHeight: 1.5 }}>
                                      {activeTrainingSession.evaluation.tier_description}
                                    </p>
                                  </div>

                                  <div className={s.scoreCircle}>
                                    <div className={s.scoreNumber}>
                                      {activeTrainingSession.evaluation.score_pct}%
                                    </div>
                                    <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)" }}>
                                      {activeTrainingSession.evaluation.total_points_earned} / {activeTrainingSession.evaluation.total_points_possible}
                                    </div>
                                  </div>
                                </div>

                                {/* 4-Pillar Breakdown Cards */}
                                <div className={s.pillarGrid}>
                                  {Object.entries(activeTrainingSession.evaluation.pillar_breakdown).map(([pillarKey, pScore]) => (
                                    <div key={pillarKey} className={s.pillarCard}>
                                      <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase" }}>
                                        {pillarKey.replace("_", " ")}
                                      </div>
                                      <div style={{ font: "var(--type-body)", fontWeight: 700, color: pScore.earned === pScore.max ? "#34d399" : "#f43f5e", marginTop: 2 }}>
                                        {pScore.earned} / {pScore.max} pts
                                      </div>
                                      <div style={{ width: "100%", height: 4, background: "rgba(255,255,255,0.1)", borderRadius: 2, marginTop: 6, overflow: "hidden" }}>
                                        <div style={{ width: `${(pScore.earned / pScore.max) * 100}%`, height: "100%", background: pScore.earned === pScore.max ? "#34d399" : "#f43f5e" }} />
                                      </div>
                                    </div>
                                  ))}
                                </div>

                                {/* Task-by-Task Debrief Table */}
                                <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--radius-card)", overflow: "hidden", marginBottom: "var(--space-5)" }}>
                                  <div style={{ padding: "var(--space-4) var(--space-5)", background: "var(--surface-1)", borderBottom: "1px solid var(--line)", font: "var(--type-body-sm)", fontWeight: 700, color: "var(--text-primary)" }}>
                                    🔍 Question-by-Question Investigative Debrief
                                  </div>

                                  <table className={s.debriefTable}>
                                    <thead>
                                      <tr>
                                        <th style={{ width: "35%" }}>Investigative Question</th>
                                        <th style={{ width: "25%" }}>Your Selection vs Ground Truth</th>
                                        <th style={{ width: "15%" }}>Result</th>
                                        <th style={{ width: "25%" }}>Statutory & Pedagogical Lesson</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {activeTrainingSession.evaluation.task_evaluations.map((te) => (
                                        <tr key={te.task_id} className={te.is_correct ? s.debriefRowPass : s.debriefRowFail}>
                                          <td>
                                            <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)", textTransform: "uppercase", marginBottom: 2 }}>
                                              {te.pillar.replace("_", " ")}
                                            </div>
                                            <div style={{ font: "var(--type-body-xs)", color: "var(--text-primary)", fontWeight: 600 }}>
                                              {te.prompt}
                                            </div>
                                            <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: 4 }}>
                                              AI finding: {te.netra_engine_finding}
                                            </div>
                                          </td>
                                          <td>
                                            <div style={{ font: "var(--type-body-xs)", color: te.is_correct ? "#34d399" : "#f43f5e", fontWeight: 600 }}>
                                              You: {te.selected_label}
                                            </div>
                                            {!te.is_correct && (
                                              <div style={{ font: "var(--type-body-xs)", color: "#34d399", marginTop: 4 }}>
                                                Expected: {te.correct_label}
                                              </div>
                                            )}
                                          </td>
                                          <td>
                                            <span style={{
                                              padding: "2px 8px",
                                              borderRadius: 4,
                                              font: "var(--type-mono-xs)",
                                              fontWeight: 700,
                                              background: te.is_correct ? "rgba(52, 211, 153, 0.15)" : "rgba(244, 63, 94, 0.15)",
                                              color: te.is_correct ? "#34d399" : "#f43f5e",
                                            }}>
                                              {te.is_correct ? `✓ +${te.points_earned} pts` : `✗ 0/${te.max_points} pts`}
                                            </span>
                                          </td>
                                          <td>
                                            <div className={s.statutoryLessonBox}>
                                              {te.pedagogical_lesson}
                                            </div>
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>

                                {/* Statutory Provisions Recap Box */}
                                <div style={{ background: "var(--surface-1)", border: "1px solid var(--line)", borderRadius: "var(--radius-card)", padding: "var(--space-4) var(--space-5)", marginBottom: "var(--space-5)" }}>
                                  <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "var(--space-2)" }}>
                                    ⚖️ Governing Statutory Provisions (BNS / BNSS / BSA 2023)
                                  </div>
                                  <ul style={{ margin: 0, paddingLeft: 18, font: "var(--type-body-xs)", color: "var(--text-secondary)", lineHeight: 1.6 }}>
                                    {activeTrainingSession.evaluation.statutory_recap.map((sr, idx) => (
                                      <li key={idx}>{sr}</li>
                                    ))}
                                  </ul>
                                </div>

                                {/* Drill Actions */}
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <Button
                                    variant="secondary"
                                    onClick={() => {
                                      setActiveTrainingSession(null);
                                      setTrainingOfficerAnswers({});
                                      setTrainingHints(null);
                                    }}
                                  >
                                    ← Choose Another Drill
                                  </Button>
                                  <div style={{ display: "flex", gap: "var(--space-3)" }}>
                                    <Button
                                      variant="secondary"
                                      onClick={() => handleStartTrainingDrill(activeTrainingSession.drill_id, activeTrainingSession.seed + 1)}
                                    >
                                      🔄 Retry with New Seed (#{activeTrainingSession.seed + 1})
                                    </Button>
                                    <Button
                                      variant="primary"
                                      onClick={handleExportTrainingCase}
                                      disabled={exportingCase}
                                    >
                                      {exportingCase ? "Exporting..." : "💾 Export Case to Sandbox"}
                                    </Button>
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

              </>
            )}
          </div>
        </motion.div>
      </AnimatePresence>

      {/* ── Statutory Notice Draft Modal ─────────────────────────────── */}
      {activeNoticeModal && (
        <div className={s.draftNoticeModalOverlay} onClick={() => setActiveNoticeModal(null)}>
          <div className={s.draftNoticeModal} onClick={e => e.stopPropagation()}>
            <div className={s.draftNoticeHeader}>
              <div>
                <div style={{ font: "var(--type-body)", fontWeight: 700, color: "var(--text-primary)" }}>
                  📄 Statutory Notice Draft — {activeNoticeModal.statute}
                </div>
                <div style={{ font: "var(--type-mono-xs)", color: "var(--warning)", marginTop: 2 }}>
                  {activeNoticeModal.banner}
                </div>
              </div>
              <button
                onClick={() => setActiveNoticeModal(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--text-secondary)",
                  fontSize: "18px",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>

            <div className={s.draftNoticeBody}>
              <pre className={s.draftNoticePre}>
                {activeNoticeModal.noticeText}
              </pre>
            </div>

            <div className={s.draftNoticeFooter}>
              <Button
                variant="secondary"
                onClick={() => setActiveNoticeModal(null)}
              >
                Close
              </Button>
              <Button
                variant="primary"
                onClick={() => handleCopyNotice(activeNoticeModal.noticeText)}
              >
                {copiedDraft ? "✓ Copied to Clipboard" : "📋 Copy Notice Text"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Feature 04: Section 193 BNSS Hypothesis Report Modal ──────── */}
      {hypothesisReportModal && (
        <div className={s.draftNoticeModalOverlay} onClick={() => setHypothesisReportModal(null)}>
          <div className={s.draftNoticeModal} onClick={e => e.stopPropagation()}>
            <div className={s.draftNoticeHeader}>
              <div>
                <div style={{ font: "var(--type-body)", fontWeight: 700, color: "var(--text-primary)" }}>
                  📄 {hypothesisReportModal.report_title}
                </div>
                <div style={{ font: "var(--type-mono-xs)", color: "var(--accent)", marginTop: 2 }}>
                  Statutory Basis: {hypothesisReportModal.statutory_basis} | Target: {hypothesisReportModal.target_entity}
                </div>
              </div>
              <button
                onClick={() => setHypothesisReportModal(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--text-secondary)",
                  fontSize: "18px",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>

            <div className={s.draftNoticeBody}>
              <pre className={s.draftNoticePre}>
                {hypothesisReportModal.report_text}
              </pre>
            </div>

            <div className={s.draftNoticeFooter}>
              <Button
                variant="secondary"
                onClick={() => setHypothesisReportModal(null)}
              >
                Close
              </Button>
              <Button
                variant="primary"
                onClick={() => handleCopyReport(hypothesisReportModal.report_text)}
              >
                {copiedReport ? "✓ Copied to Clipboard" : "📋 Copy Memorandum Text"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
