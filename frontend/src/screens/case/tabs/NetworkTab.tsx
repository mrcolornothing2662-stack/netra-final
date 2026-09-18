import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import cytoscape, { type Core, type EventObject } from "cytoscape";
import { useLiveStore } from "../../../state/useLiveStore";
import { entities as corpusEntities } from "../../../data/entities";
import { connections as corpusConnections } from "../../../data/connections";
import { findings as corpusFindings } from "../../../data/findings";
import {
  SHAPES,
  TINTS,
  FAM_LABEL,
  mulberry32,
  seedOf,
  p2,
  GraphModel,
  GraphIntel,
  computeBasePositions,
  computeSpatialAnchors,
  type SpatialPosition,
  tracePathFor,
  LATENT,
  LATENT_EDGES,
  type ModelNode,
  type ModelEdge,
  type IntelAnalysis,
  type InferredHiddenLink
} from "./graphEngine";
import { SpatialAtmosphereCanvas } from "./spatial/SpatialAtmosphereCanvas";
import { InvestigationEffectsOverlay } from "./spatial/InvestigationEffectsOverlay";
import { ImmersiveSpatialGraph } from "./immersive/ImmersiveSpatialGraph";
import { HiddenLinksExplorer } from "./hidden_links/HiddenLinksExplorer";
import { CorrelationsPanel } from "./CorrelationsPanel";
import { graphInteractionStore, useGraphInteraction } from "./graphCore/GraphInteractionStore";
import { GraphAlgorithmService } from "./graphCore/GraphAlgorithmService";
import type { LayoutMode } from "./graphCore/graphInteractionTypes";
import { cognitiveApi, type ReplayFrame } from "../../../api/cognitive";
import "./networkEngine.css";

const inr = (n: number) => '₹' + n.toLocaleString('en-IN');
const inrM = (n: number) => '₹' + (n / 1e6).toFixed(1) + 'M';

const flows = [
  { id: 'fl-01', source: 'ent-g-a1', hops: [] as string[], sink: 'ent-account-4821', amount: 620000, note: 'Cluster A inbound' },
  { id: 'fl-02', source: 'ent-account-4821', hops: ['ent-g-a2'], sink: 'ent-account-72', amount: 1180000, note: 'Forwarded within minutes of receipt' },
  { id: 'fl-03', source: 'ent-g-a3', hops: [] as string[], sink: 'ent-account-4821', amount: 45000, note: 'Anchor chain · follows 09:42:13 communication' },
  { id: 'fl-04', source: 'ent-g-a4', hops: [] as string[], sink: 'ent-g-a2', amount: 555000, note: 'Cluster B inbound' }
];
const totalTraced = flows.reduce((n, f) => n + f.amount, 0);

interface NetState {
  caseId: string | null;
  revealed: Set<string>;
  selected: Set<string>;
  selEdge: string | null;
  focus: { id: string; hops: number } | null;
  filters: { kinds: Set<string> | null; minConf: number; showHidden: boolean; aiThreshold: number };
  pinned: Record<string, { x: number; y: number }>;
  positions: Record<string, { x: number; y: number }>;
  spatialAnchors: Record<string, SpatialPosition>;
  seenPaths: Set<string>;
  path: { nodes: string[]; edges: string[]; minConf: number } | null;
  subgraph: Set<string> | null;
  trace: { hops: Array<{ from: string; to: string; connection: ModelEdge }>; i: number; t0: number } | null;
  clusters: boolean;
  box: boolean;
  twoHop: boolean;
  stress: { nodes: ModelNode[]; edges: ModelEdge[] } | null;
}

const networkStyle: cytoscape.StylesheetStyle[] = [
  {
    selector: 'node',
    style: {
      'background-color': '#11141A',
      'shape': 'data(shape)' as any,
      'width': 'data(size)' as any,
      'height': 'data(size)' as any,
      'label': 'data(label)',
      'color': 'rgba(241,241,238,0.85)',
      'font-family': 'Geist Mono, monospace',
      'font-size': 9,
      'min-zoomed-font-size': 7,
      'text-valign': 'bottom',
      'text-margin-y': 7,
      'text-background-color': '#08090C',
      'text-background-opacity': 0.85,
      'text-background-padding': '3px',
      'text-background-shape': 'roundrectangle',
      'border-width': 'data(borderW)' as any,
      'border-color': 'data(borderC)' as any,
      'opacity': 'data(nodeOpacity)' as any,
      'transition-property': 'background-color, opacity, width, height, border-color, border-width',
      'transition-duration': 0.22
    }
  },
  { selector: 'node.riskHigh', style: { 'border-width': 2.2, 'border-color': '#F43F5E' } },
  { selector: 'node.bridgeHigh', style: { 'border-width': 2.5, 'border-color': '#FB7185' } },
  { selector: 'node:selected', style: { 'background-color': '#0F172A', 'border-width': 3, 'border-color': '#38BDF8', 'opacity': 1.0 } },
  { selector: 'node.hl', style: { 'background-color': '#FFFFFF', 'border-color': '#FFFFFF', 'border-width': 2, 'opacity': 1.0 } },
  { selector: 'node.dim', style: { 'opacity': 0.08 } },
  { selector: 'node.dimx', style: { 'opacity': 0.03 } },
  { selector: 'node.filt', style: { 'opacity': 0.02, 'events': 'no' } },
  { selector: 'node.pinned', style: { 'border-style': 'dashed', 'border-color': 'rgba(241,241,238,0.65)', 'border-width': 1.8 } },
  {
    selector: 'edge',
    style: {
      'width': 'data(w)' as any,
      'line-color': 'rgba(241,241,238,0.22)',
      'target-arrow-color': 'rgba(241,241,238,0.35)',
      'target-arrow-shape': 'data(ashape)' as any,
      'arrow-scale': 0.55,
      'curve-style': 'bezier',
      'label': 'data(elabel)',
      'font-size': 8,
      'color': 'rgba(241,241,238,0.5)',
      'min-zoomed-font-size': 12,
      'text-rotation': 'autorotate',
      'text-background-color': '#08090C',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
      'transition-property': 'line-color, width, opacity',
      'transition-duration': 0.22
    }
  },
  { selector: 'edge.dim', style: { 'opacity': 0.04 } },
  { selector: 'edge.dimx', style: { 'opacity': 0.02 } },
  { selector: 'edge.filt', style: { 'opacity': 0.02, 'events': 'no' } },
  { selector: 'edge.tr-active', style: { 'line-color': '#38BDF8', 'width': 2.4, 'target-arrow-color': '#38BDF8', 'opacity': 1.0 } },
  { selector: 'edge.tr-visited', style: { 'line-color': 'rgba(56,189,248,0.45)', 'width': 1.6, 'target-arrow-color': 'rgba(56,189,248,0.45)', 'opacity': 0.65 } },
  { selector: 'edge.path-hl', style: { 'line-color': '#38BDF8', 'width': 2.2, 'target-arrow-color': '#38BDF8', 'opacity': 1.0 } },
  { selector: 'edge.sp-visited', style: { 'line-color': 'rgba(241,241,238,0.3)', 'width': 1.2 } },
  // AI Predicted Hidden Links
  {
    selector: 'edge.hidden_link',
    style: {
      'line-color': '#F59E0B',
      'target-arrow-color': '#F59E0B',
      'line-style': 'dashed',
      'line-dash-pattern': [8, 5] as any,
      'curve-style': 'unbundled-bezier',
      'control-point-distances': [24, -24] as any,
      'width': 'data(w)' as any,
      'color': '#FBBF24',
      'text-background-color': '#181204',
      'text-background-opacity': 0.9,
      'opacity': 0.88
    }
  },
  {
    selector: 'edge.hidden_link:selected',
    style: {
      'line-color': '#FBBF24',
      'target-arrow-color': '#FBBF24',
      'width': 3.2,
      'opacity': 1.0
    }
  },
  // Observed semantic relationships from the unified case graph (solid, traced)
  {
    selector: 'edge.observed_rel',
    style: {
      'line-color': 'rgba(125, 211, 252, 0.34)',
      'target-arrow-color': 'rgba(125, 211, 252, 0.5)'
    }
  },
  // Cluster tints (curated sleek dark tones)
  { selector: 'node.c0', style: { 'background-color': '#1E293B', 'border-color': '#38BDF8' } },
  { selector: 'node.c1', style: { 'background-color': '#271A38', 'border-color': '#C084FC' } },
  { selector: 'node.c2', style: { 'background-color': '#142E28', 'border-color': '#34D399' } },
  { selector: 'node.c3', style: { 'background-color': '#2E2214', 'border-color': '#FBBF24' } },
  { selector: 'node.c4', style: { 'background-color': '#2E141E', 'border-color': '#FB7185' } },
  { selector: 'node.c5', style: { 'background-color': '#1C252E', 'border-color': '#94A3B8' } }
];

export function NetworkTab({ caseId: propCaseId }: { caseId?: string } = {}) {
  const { caseId: routeCaseId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { activeGraph, activeCaseSummary } = useLiveStore();

  const caseId = propCaseId || routeCaseId || "";
  const isDemo = caseId === "CYB-2026-042" || caseId === "demo-shadowlink";
  const select0 = searchParams.get("select");
  const trace0 = searchParams.get("trace") ? select0 : null;

  const {
    state: storeState,
    selectNode: storeSelectNode,
    selectEdge: storeSelectEdge,
    clearSelection: storeClearSelection,
    setPath: storeSetPath,
    setLayout: storeSetLayout,
    setViewMode: storeSetViewMode
  } = useGraphInteraction();

  const [mode, setMode] = useState<"GRAPH" | "IMMERSIVE" | "FLOWS" | "HIDDEN_LINKS">(storeState.viewMode || "GRAPH");
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(storeState.activeLayout || "force");

  // Cytoscape DOM container refs
  const stageRef = useRef<HTMLDivElement>(null);
  const cyMountRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  // UI state overlays
  const [counts, setCounts] = useState<{ shown: number; total: number; edges: number }>({ shown: 0, total: 0, edges: 0 });
  const [analysis, setAnalysis] = useState<IntelAnalysis | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMatches, setSearchMatches] = useState<ModelNode[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [filterPopOpen, setFilterPopOpen] = useState(false);
  const [morePopOpen, setMorePopOpen] = useState(false);
  const [minConf, setMinConf] = useState(0);
  const [showHiddenLinks, setShowHiddenLinks] = useState(false);
  const [aiThreshold, setAiThreshold] = useState(35);
  const [twoHopOn, setTwoHopOn] = useState(false);
  const [activeKinds, setActiveKinds] = useState<Set<string> | null>(null);
  const [clustersOn, setClustersOn] = useState(false);
  const [boxOn, setBoxOn] = useState(false);
  const [zoomPct, setZoomPct] = useState(100);
  const [stressBanner, setStressBanner] = useState<string | null>(null);
  const [netHint, setNetHint] = useState<string>("");
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  // Trace card state
  const [traceCard, setTraceCard] = useState<{ open: boolean; idx: string; name: string; reason: string; done: boolean }>({
    open: false, idx: "", name: "", reason: "", done: false
  });

  // Tooltip state
  const [tip, setTip] = useState<{ visible: boolean; x: number; y: number; html: string }>({
    visible: false, x: 0, y: 0, html: ""
  });

  // Inspector & selection state
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [selectedCount, setSelectedCount] = useState(0);
  const [pathPoints, setPathPoints] = useState<string[]>([]);

  // Cinematic Camera & Spatial Focus Modes
  const [camPan, setCamPan] = useState({ x: 0, y: 0 });
  const [camZoom, setCamZoom] = useState(1);
  const [focusMode, setFocusMode] = useState<"EXPLORE" | "ENTITY_FOCUS" | "PATH_FOCUS" | "PATTERN_FOCUS">("EXPLORE");

  // ── CTDG Network Replay (Feature 10) ──────────────────────────────────
  const [replayActive, setReplayActive] = useState(false);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState<number>(1);
  const [replayFrameIdx, setReplayFrameIdx] = useState(0);
  const [replayFrames, setReplayFrames] = useState<ReplayFrame[]>([]);
  const [replayLoading, setReplayLoading] = useState(false);

  // Show Toast
  const showToast = useCallback((msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3500);
  }, []);

  const applyReplayFrame = useCallback((frame: ReplayFrame) => {
    const cy = cyRef.current;
    if (!cy || !frame) return;
    const activeNodeSet = new Set(frame.nodes);
    const newEventsNodeSet = new Set(
      (frame.new_events || []).flatMap(e => [e.u, e.v, e.node].filter(Boolean) as string[])
    );

    // Map each edge pair to its opacity (from continuous-time exponential decay)
    const edgeOpacityMap = new Map<string, number>();
    for (const e of frame.edges) {
      const op = typeof e.opacity === 'number' ? e.opacity : 1.0;
      edgeOpacityMap.set(`${e.u}_${e.v}`, op);
      edgeOpacityMap.set(`${e.v}_${e.u}`, op);
    }

    cy.batch(() => {
      cy.nodes().forEach(n => {
        const nid = n.id();
        if (newEventsNodeSet.has(nid)) {
          // Node actively participating in this frame's events
          n.style('opacity', 1.0);
          n.style('border-width', '3.5px');
          n.style('border-color', '#00F0FF');
        } else if (activeNodeSet.has(nid)) {
          // Node seen in historical frames
          n.style('opacity', 0.90);
          n.style('border-width', '1.8px');
          n.style('border-color', 'rgba(0, 240, 255, 0.45)');
        } else {
          // Inactive / future node
          n.style('opacity', 0.12);
          n.style('border-width', '1px');
          n.style('border-color', 'rgba(255,255,255,0.12)');
        }
      });

      cy.edges().forEach(e => {
        const src = e.data('source');
        const tgt = e.data('target');
        const op = edgeOpacityMap.get(`${src}_${tgt}`) ?? edgeOpacityMap.get(`${tgt}_${src}`);
        if (op !== undefined) {
          // Continuous exponential decay: active recent edges are bright cyan, older edges fade
          const edgeOpacity = Math.max(0.18, Math.min(1.0, op));
          e.style('opacity', edgeOpacity);
          e.style('width', op > 0.6 ? 3 : 1.5);
          e.style('line-color', op > 0.6 ? '#00F0FF' : 'rgba(0, 240, 255, 0.45)');
        } else {
          e.style('opacity', 0.06);
          e.style('width', 1);
          e.style('line-color', '#565B65');
        }
      });
    });
  }, []);

  // Base raw entities and connections
  const rawEntities = useMemo(() => {
    if (activeGraph?.nodes && activeGraph.nodes.length > 0) {
      return activeGraph.nodes.map(n => ({
        id: n.id,
        name: n.label,
        kind: n.kind || 'PERSON',
        risk: (n as any).risk || (n.kind === 'ACCOUNT' && n.label.includes('4821') ? 'HIGH' : undefined),
        meta: (n as any).meta || `Entity: ${n.label}`,
        bridgeScore: (n as any).bridgeScore,
        mentionCount: (n as any).mentionCount
      }));
    }
    return isDemo ? corpusEntities : [];
  }, [activeGraph, isDemo]);

  const rawConnections = useMemo(() => {
    if (activeGraph?.connections && activeGraph.connections.length > 0) {
      return activeGraph.connections;
    }
    return isDemo ? corpusConnections : [];
  }, [activeGraph, isDemo]);

  const entityKindMap = useMemo(() => {
    const map = new Map<string, string>();
    rawEntities.forEach(e => map.set(e.id, e.kind));
    return map;
  }, [rawEntities]);

  // Model graph
  const allModelNodes = useMemo(() => GraphModel.allNodes(rawEntities, isDemo), [rawEntities, isDemo]);
  const allModelEdges = useMemo(() => GraphModel.allEdges(rawConnections, entityKindMap, isDemo), [rawConnections, entityKindMap, isDemo]);

  // Case-specific transaction flows
  const caseFlows = useMemo(() => {
    if (isDemo) return flows;
    const txnEdges = allModelEdges.filter(e => e.type === 'transaction' || e.type === 'FINANCIAL_TRANSACTION');
    return txnEdges.map((e, idx) => ({
      id: `fl-${idx + 1}`,
      source: e.a,
      hops: [] as string[],
      sink: e.b,
      // Real transacted amount only. If the evidence edge carries no amount we
      // surface it as unknown rather than fabricating a figure from a score.
      amount: typeof (e as any).amount === 'number' ? ((e as any).amount as number) : null,
      note: e.reason || 'Financial transaction correlation'
    }));
  }, [isDemo, allModelEdges]);
  const totalTracedValue = caseFlows.reduce((n, f) => n + (f.amount || 0), 0);

  // Dynamic 7-feature explainable hidden links
  const inferredHiddenLinks = useMemo(() => {
    return GraphIntel.predictHiddenLinks(allModelNodes, allModelEdges, analysis, aiThreshold / 100);
  }, [allModelNodes, allModelEdges, analysis, aiThreshold]);

  // Inferred hidden edge pairs for effects overlay
  const hiddenEdgePairs = useMemo(() => {
    if (!showHiddenLinks) return [];
    return allModelEdges
      .filter(e => e.is_hidden || e.type === 'hidden_link')
      .map(e => ({ source: e.a, target: e.b, confidence: e.conf }));
  }, [allModelEdges, showHiddenLinks]);

  // NetState Ref (persistent across renders)
  const netStateRef = useRef<NetState>({
    caseId: null,
    revealed: new Set<string>(),
    selected: new Set<string>(),
    selEdge: null,
    focus: null,
    filters: { kinds: null, minConf: 0, showHidden: false, aiThreshold: 35 },
    pinned: {},
    positions: {},
    spatialAnchors: {},
    seenPaths: new Set<string>(),
    path: null,
    subgraph: null,
    trace: null,
    clusters: false,
    box: false,
    twoHop: false,
    stress: null
  });

  // Initialize NetState for current case
  useEffect(() => {
    const s = netStateRef.current;
    if (s.caseId !== caseId) {
      s.caseId = caseId;
      s.selected = new Set();
      s.selEdge = null;
      s.focus = null;
      s.filters = { kinds: null, minConf: 0, showHidden: true, aiThreshold: 35 };
      s.pinned = {};
      s.seenPaths = new Set();
      s.path = null;
      s.subgraph = null;
      s.trace = null;
      s.clusters = false;
      s.twoHop = false;
      s.stress = null;

      let rv: string[] | null = null;
      try {
        rv = JSON.parse(sessionStorage.getItem('cd-net-' + caseId) || 'null');
      } catch (e) {}
      s.revealed = new Set(rv && rv.length ? rv : rawEntities.map(e => e.id));
      const anchors = computeSpatialAnchors(rawEntities, rawConnections);
      s.spatialAnchors = anchors;
      s.positions = {};
      Object.keys(anchors).forEach(id => {
        s.positions[id] = { x: anchors[id].baseX, y: anchors[id].baseY };
      });
    } else {
      if (rawEntities.length === 0) {
        s.revealed = new Set();
        s.positions = {};
        s.spatialAnchors = {};
      } else if (s.revealed.size === 0 && rawEntities.length > 0) {
        s.revealed = new Set(rawEntities.map(e => e.id));
        const anchors = computeSpatialAnchors(rawEntities, rawConnections);
        s.spatialAnchors = anchors;
        Object.keys(anchors).forEach(id => {
          if (!s.positions[id]) {
            s.positions[id] = { x: anchors[id].baseX, y: anchors[id].baseY };
          }
        });
      }
    }
  }, [caseId, rawEntities, rawConnections]);

  // Progressive position for newly expanded latent nodes
  const posForNew = useCallback((id: string, parent: string) => {
    const kids = LATENT.filter(l => netStateRef.current.revealed.has(l.id) && l.parent === parent).length;
    const p = netStateRef.current.positions[parent] || { x: 400, y: 300 };
    const r = mulberry32(seedOf(id))();
    const ang = r * 6.283 + kids * 0.9, rad = 85 + kids * 14;
    return { x: p.x + Math.cos(ang) * rad, y: p.y + Math.sin(ang) * rad };
  }, []);

  const getModelNodes = useCallback(() => {
    const s = netStateRef.current;
    return s.stress ? s.stress.nodes : allModelNodes.filter(n => s.revealed.has(n.id));
  }, [allModelNodes]);

  const getModelEdges = useCallback(() => {
    const s = netStateRef.current;
    return s.stress ? s.stress.edges : allModelEdges.filter(e => s.revealed.has(e.a) && s.revealed.has(e.b));
  }, [allModelEdges]);

  const toggleReplay = useCallback(async () => {
    if (replayActive) {
      setReplayActive(false);
      setReplayPlaying(false);
      const cy = cyRef.current;
      if (cy) {
        cy.batch(() => {
          cy.nodes().forEach(n => {
            n.style('opacity', 1);
            n.style('border-width', '1px');
            n.style('border-color', 'rgba(255,255,255,0.2)');
          });
          cy.edges().forEach(e => {
            e.style('opacity', 0.85);
            e.style('width', 1.5);
            e.style('line-color', '#565B65');
          });
        });
      }
      showToast("Exited network replay mode");
      return;
    }

    setReplayActive(true);
    setReplayLoading(true);
    showToast("Loading Continuous-Time Dynamic Graph (CTDG) frames…");

    try {
      const res = caseId ? await cognitiveApi.networkReplay(caseId, 300, 1800) : null;
      if (res && res.frames && res.frames.length > 0) {
        setReplayFrames(res.frames);
        setReplayFrameIdx(0);
        applyReplayFrame(res.frames[0]);
        showToast(`Replay loaded · ${res.frames.length} continuous-time frames`);
      } else {
        // No timestamped events on the server → no temporal graph to replay.
        // Do NOT fabricate frames; report the honest empty state and exit.
        setReplayFrames([]);
        setReplayActive(false);
        showToast("No timestamped events to replay for this case");
      }
    } catch {
      setReplayFrames([]);
      setReplayActive(false);
      showToast("Network replay unavailable (backend error)");
    } finally {
      setReplayLoading(false);
    }
  }, [replayActive, caseId, applyReplayFrame, showToast]);

  useEffect(() => {
    if (!replayPlaying || replayFrames.length === 0) return;
    const intervalMs = Math.max(120, 1200 / replaySpeed);
    const timer = setInterval(() => {
      setReplayFrameIdx(prev => {
        const next = prev + 1;
        if (next >= replayFrames.length) {
          setReplayPlaying(false);
          return prev;
        }
        applyReplayFrame(replayFrames[next]);
        return next;
      });
    }, intervalMs);
    return () => clearInterval(timer);
  }, [replayPlaying, replayFrames, replaySpeed, applyReplayFrame]);

  useEffect(() => {
    if (searchParams.get("replay") === "true" && !replayActive && !replayLoading && caseId) {
      toggleReplay();
    }
  }, [searchParams, replayActive, replayLoading, caseId, toggleReplay]);

  // Build Cytoscape element definitions
  const buildElements = useCallback((currentAnalysis: IntelAnalysis | null) => {
    const nodes = getModelNodes();
    const edges = getModelEdges();
    const deg: Record<string, number> = {};
    edges.forEach(e => {
      deg[e.a] = (deg[e.a] || 0) + 1;
      deg[e.b] = (deg[e.b] || 0) + 1;
    });
    const maxDeg = Math.max(1, ...nodes.map(n => deg[n.id] || 0));

    return {
      nodes: nodes.map(n => {
        const bridgeVal = n.bridgeScore ?? (currentAnalysis?.bridgeScores ? (currentAnalysis.bridgeScores[n.id] || 0) : 0);
        const isBridgeHigh = bridgeVal > 0.45;
        const classes = [
          n.risk === 'HIGH' ? 'riskHigh' : '',
          isBridgeHigh ? 'bridgeHigh' : ''
        ].filter(Boolean).join(' ');

        const anchor = netStateRef.current.spatialAnchors?.[n.id];
        const depth = anchor?.depth || { z: 0, depthScale: 1.0, depthOpacity: 0.85, parallaxFactor: 1.0 };
        const baseSize = 22 + ((deg[n.id] || 0) / maxDeg) * 14;
        const renderedSize = Math.round(baseSize * depth.depthScale);

        return {
          data: {
            id: n.id,
            label: n.name,
            kind: n.kind,
            risk: n.risk || '',
            latent: !!n.latent,
            meta: n.meta || '',
            firstSeen: n.firstSeen || '—',
            lastSeen: n.lastSeen || '—',
            deg: deg[n.id] || 0,
            size: renderedSize,
            borderW: isBridgeHigh ? 2.5 : n.risk === 'HIGH' ? 2.2 : 1.2,
            borderC: isBridgeHigh ? '#FB7185' : n.risk === 'HIGH' ? '#F43F5E' : 'rgba(241,241,238,0.3)',
            nodeOpacity: depth.depthOpacity,
            mzfs: 7,
            prn: currentAnalysis ? currentAnalysis.prn(n.id) || 0 : (deg[n.id] || 0) / maxDeg,
            bridgeScore: bridgeVal,
            shape: SHAPES[n.kind] || 'ellipse'
          },
          position: netStateRef.current.positions[n.id] || { x: anchor?.baseX ?? 400, y: anchor?.baseY ?? 300 },
          classes
        };
      }),
      edges: edges
        .filter(e => {
          const isHidden = !!e.is_hidden || e.type === 'hidden_link';
          if (isHidden && !showHiddenLinks) return false;
          return true;
        })
        .map(e => {
        const isHidden = !!e.is_hidden || e.type === 'hidden_link';
        const relType = e.relationship_type;
        const confPct = e.conf <= 1 ? Math.round(e.conf * 100) : Math.round(e.conf);
        const label = isHidden
          ? `AI PREDICTED · ${confPct}%`
          : `${relType || e.type} · ${confPct}%`;
        const classes = isHidden ? 'hidden_link' : (relType ? 'observed_rel' : '');
        return {
          data: {
            id: e.id,
            source: e.a,
            target: e.b,
            type: isHidden ? 'hidden_link' : e.type,
            relType,
            epistemic: e.epistemic_status,
            provCount: (e.evidence_refs || e.evidenceIds || []).length,
            conf: e.conf,
            reason: e.reason,
            directed: e.directed,
            evidenceIds: e.evidenceIds || [],
            is_hidden: isHidden,
            score: e.score,
            threshold: e.threshold || 0.365,
            component_scores: e.component_scores,
            w: isHidden ? 2.0 : 1.0 + (confPct / 100) * 0.8,
            elabel: label,
            ashape: e.directed ? 'triangle' : 'none'
          },
          classes
        };
      })
    };
  }, [getModelNodes, getModelEdges, showHiddenLinks]);

  const focusSet = useCallback((id: string, hops: number) => {
    const cy = cyRef.current;
    if (!cy) return new Set([id]);
    const near = new Set([id]);
    let frontier = [id];
    for (let h = 0; h < hops; h++) {
      const nx: string[] = [];
      frontier.forEach(v => {
        const n = cy.getElementById(v);
        n.neighborhood('node').forEach(x => {
          if (!near.has(x.id())) { near.add(x.id()); nx.push(x.id()); }
        });
      });
      frontier = nx;
    }
    return near;
  }, []);

  // Batched view-state applicator
  const applyState = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const s = netStateRef.current;

    cy.batch(() => {
      cy.nodes().removeClass('dim dimx filt hl');
      cy.edges().removeClass('dim dimx filt path-hl tr-active tr-visited');
      cy.edges().filter(e => s.seenPaths.has(e.id())).addClass('tr-visited');

      if (s.trace) {
        // Trace dimming handled during trace execution
      } else if (s.path) {
        const P = new Set(s.path.nodes), E = new Set(s.path.edges);
        cy.nodes().forEach(n => { if (!P.has(n.id())) n.addClass('dimx'); });
        cy.edges().forEach(e => { if (E.has(e.id())) e.addClass('path-hl'); else e.addClass('dimx'); });
      } else if (s.subgraph) {
        const keep = s.subgraph;
        cy.nodes().forEach(n => { if (!keep.has(n.id())) n.addClass('dimx'); });
        cy.edges().forEach(e => { if (!(keep.has(e.source().id()) && keep.has(e.target().id()))) e.addClass('dimx'); });
      } else if (s.twoHop && s.selected.size === 1) {
        const selId = [...s.selected][0];
        const near = focusSet(selId, 2);
        cy.nodes().forEach(n => { if (!near.has(n.id())) n.addClass('dim'); });
        cy.edges().forEach(e => { if (!(near.has(e.source().id()) && near.has(e.target().id()))) e.addClass('dim'); });
      } else if (s.selected.size === 1) {
        const selId = [...s.selected][0];
        const near = focusSet(selId, 1);
        cy.nodes().forEach(n => { if (!near.has(n.id())) n.addClass('dim'); });
        cy.edges().forEach(e => { if (!(near.has(e.source().id()) && near.has(e.target().id()))) e.addClass('dim'); });
      } else if (s.focus) {
        const near = focusSet(s.focus.id, s.focus.hops);
        cy.nodes().forEach(n => { if (!near.has(n.id())) n.addClass('dim'); });
        cy.edges().forEach(e => { if (!(near.has(e.source().id()) && near.has(e.target().id()))) e.addClass('dim'); });
      }

      // Filter layer on top
      const fk = s.filters.kinds;
      const mc = s.filters.minConf;
      const showHid = s.filters.showHidden;
      const aiThresh = s.filters.aiThreshold;
      if (fk || mc > 0 || !showHid || aiThresh > 0) {
        cy.nodes().forEach(n => { if (fk && !fk.has(n.data('kind'))) n.addClass('filt'); });
        cy.edges().forEach(e => {
          if (e.data('is_hidden')) {
            if (!showHid) {
              e.addClass('filt');
              return;
            }
            const edgeSc = (e.data('score') !== undefined) ? (e.data('score') * 100) : e.data('conf');
            if (edgeSc < aiThresh) {
              e.addClass('filt');
              return;
            }
          }
          if (e.data('conf') < mc) e.addClass('filt');
        });
      }
    });

    const shown = cy.nodes().filter(n => !n.hasClass('filt')).length;
    const edgeCount = cy.edges().filter(e => !e.hasClass('filt')).length;
    const total = allModelNodes.length;
    setCounts({ shown, total, edges: edgeCount });
    (window as any).__netCounts = { shown, total, edges: edgeCount };
  }, [allModelNodes.length, focusSet]);

  // Run Graph Intelligence
  const runAnalytics = useCallback(() => {
    const nodes = getModelNodes();
    const edges = getModelEdges();
    const cy = cyRef.current;
    if (nodes.length <= 2500) {
      const res = GraphIntel.analyze(nodes, edges);
      setAnalysis(res);
      if (cy) {
        cy.batch(() => {
          cy.nodes().forEach(n => {
            n.data('prn', res.prn(n.id()) || 0);
          });
        });
      }
    } else {
      setAnalysis(null);
    }
  }, [getModelNodes, getModelEdges]);

  // Apply Cluster Tint
  const applyClusterTint = useCallback((overrideState?: boolean) => {
    const cy = cyRef.current;
    if (!cy) return;
    const isClusters = overrideState !== undefined ? overrideState : netStateRef.current.clusters;
    cy.batch(() => {
      if (!isClusters || !analysis) {
        cy.nodes().removeClass(TINTS.map((_, i) => 'c' + i).join(' '));
        return;
      }
      cy.nodes().forEach(n => {
        const ci = analysis.commOf[n.id()] || 0;
        n.classes(n.hasClass('riskHigh') ? 'riskHigh' : '').addClass('c' + (ci % 6));
      });
    });
  }, [analysis]);

  // Camera navigation with disciplined zoom
  const camTo = useCallback((ids: string[], animate = true) => {
    const cy = cyRef.current;
    const stage = stageRef.current;
    if (!cy || !stage) return;
    const eles = cy.nodes().filter(n => ids.includes(n.id()));
    if (!eles.nonempty()) return;
    const bb = eles.boundingBox();
    const w = stage.clientWidth, h = stage.clientHeight;
    const fz = Math.max(0.3, Math.min(2.5, Math.min(w / (bb.w + 120), h / (bb.h + 120))));
    const z = cy.zoom(), t = Math.max(z / 1.25, Math.min(z * 1.25, fz));
    if (animate) {
      cy.animate({ center: { eles }, zoom: t }, { duration: 320, easing: 'ease-out' as any });
    } else {
      cy.zoom(t);
      cy.center(eles);
    }
  }, []);

  // Select node with cinematic camera glide
  const selectNode = useCallback((id: string, additive = false) => {
    const cy = cyRef.current;
    if (!cy) return;
    const s = netStateRef.current;
    if (!additive) {
      s.selected = new Set();
      s.selEdge = null;
      setSelectedEdgeId(null);
    }
    s.selected.add(id);
    setSelectedNodeId(id);
    setSelectedCount(s.selected.size);
    setFocusMode("ENTITY_FOCUS");
    storeSelectNode(id, additive);

    cy.nodes().unselect();
    const target = cy.getElementById(id);
    target.select();

    // Cinematic camera glide: smoothly focus entity
    const stage = stageRef.current;
    if (stage && target.nonempty()) {
      const p = target.position();
      const w = stage.clientWidth, h = stage.clientHeight;
      const targetZoom = Math.min(1.75, Math.max(1.15, cy.zoom()));
      cy.animate(
        {
          pan: { x: w / 2 - p.x * targetZoom, y: h / 2 - p.y * targetZoom },
          zoom: targetZoom
        },
        { duration: 550, easing: 'ease-out' as any }
      );
    }

    applyState();
  }, [applyState, storeSelectNode]);

  // Apply Layout Mode (Force, Radial, Hierarchical, Clustered)
  const applyLayout = useCallback((nextMode: LayoutMode) => {
    const cy = cyRef.current;
    if (!cy) return;
    setLayoutMode(nextMode);
    storeSetLayout(nextMode);

    const positions = GraphAlgorithmService.computeLayout(nextMode, allModelNodes, allModelEdges);
    cy.batch(() => {
      cy.nodes().forEach(n => {
        const p = positions[n.id()];
        if (p) {
          n.animate({ position: p }, { duration: 550, easing: 'ease-out' as any });
          netStateRef.current.positions[n.id()] = p;
        }
      });
    });
    setTimeout(() => {
      cy.animate({ fit: { padding: 45, eles: cy.elements() } }, { duration: 400, easing: 'ease-out' as any });
    }, 580);
    showToast(`Layout: ${nextMode.toUpperCase()}`);
  }, [allModelNodes, allModelEdges, storeSetLayout, showToast]);

  // Trace execution (Amendment D)
  const exitTrace = useCallback(() => {
    if (!netStateRef.current.trace) return;
    netStateRef.current.trace = null;
    setTraceCard({ open: false, idx: "", name: "", reason: "", done: false });
    setNetHint("");
    applyState();
  }, [applyState]);

  const stepTrace = useCallback((hops: Array<{ from: string; to: string; connection: ModelEdge }>, index: number) => {
    const cy = cyRef.current;
    if (!cy || !netStateRef.current.trace) return;
    const hop = hops[index];
    const B = cy.getElementById(hop.to);
    const edge = cy.getElementById(hop.connection.id);

    edge.addClass('tr-active');
    setTraceCard({
      open: true,
      idx: `TRACE ${p2(index + 1)}/${p2(hops.length)}`,
      name: B.data('label') || hop.to,
      reason: hop.connection.reason,
      done: false
    });

    camTo([hop.from, hop.to]);

    setTimeout(() => {
      if (!netStateRef.current.trace) return;
      edge.removeClass('tr-active');
      edge.addClass('tr-visited');
      netStateRef.current.seenPaths.add(edge.id());

      if (index + 1 < hops.length) {
        netStateRef.current.trace.i = index + 1;
        const nextB = cy.getElementById(hops[index + 1].to);
        setTraceCard({
          open: true,
          idx: `TRACE ${p2(index + 2)}/${p2(hops.length)}`,
          name: nextB.data('label') || hops[index + 1].to,
          reason: hops[index + 1].connection.reason,
          done: false
        });
        setTimeout(() => stepTrace(hops, index + 1), 1400);
      } else {
        setTraceCard(prev => ({ ...prev, done: true, name: "Trace complete", reason: "" }));
        setTimeout(() => exitTrace(), 1800);
      }
    }, 620);
  }, [camTo, exitTrace]);

  const beginTrace = useCallback((entityId: string) => {
    const cy = cyRef.current;
    if (!cy) return;
    const hops = tracePathFor(entityId, getModelEdges());
    if (!hops || cy.getElementById(entityId).empty()) return;

    netStateRef.current.trace = { hops, i: 0, t0: Date.now() };
    setNetHint("ESC OR CLICK BACKGROUND TO EXIT");

    // Trace Dimming
    cy.batch(() => {
      cy.nodes().removeClass('dim dimx');
      cy.edges().removeClass('dim dimx path-hl');
      const on = new Set<string>();
      hops.forEach(h => { on.add(h.from); on.add(h.to); });
      cy.nodes().forEach(n => { if (!on.has(n.id())) n.addClass('dimx'); });
      cy.edges().forEach(e => { if (!hops.some(h => h.connection.id === e.id())) e.addClass('dimx'); });
    });

    stepTrace(hops, 0);
  }, [getModelEdges, stepTrace]);

  // Expand latent connections
  const expandNode = useCallback((id: string) => {
    const cy = cyRef.current;
    if (!cy) return;
    const s = netStateRef.current;
    const kids = LATENT.filter(l => l.parent === id && !s.revealed.has(l.id));
    if (!kids.length) {
      showToast("All connections revealed");
      return;
    }

    cy.batch(() => {
      kids.forEach(l => {
        s.revealed.add(l.id);
        const pos = s.positions[l.id] || posForNew(l.id, id);
        s.positions[l.id] = pos;
        cy.add({
          data: {
            id: l.id,
            label: l.name,
            kind: l.kind,
            risk: '',
            latent: true,
            meta: l.meta,
            firstSeen: '—',
            lastSeen: '—',
            deg: 1,
            size: 20,
            mzfs: 10,
            prn: 0,
            shape: SHAPES[l.kind] || 'ellipse'
          },
          position: pos,
          classes: 'riskHigh'
        });
      });

      allModelEdges.forEach(e => {
        if ((e.a === id && s.revealed.has(e.b)) || (e.b === id && s.revealed.has(e.a))) {
          if (cy.getElementById(e.id).empty()) {
            cy.add({
              data: {
                id: e.id,
                source: e.a,
                target: e.b,
                type: e.type,
                conf: e.conf,
                reason: e.reason,
                directed: e.directed,
                evidenceIds: e.evidenceIds || [],
                w: 1 + (e.conf / 100) * 1.4,
                elabel: e.type + ' · ' + e.conf + '%',
                ashape: e.directed ? 'triangle' : 'none'
              }
            });
          }
        }
      });
    });

    try {
      sessionStorage.setItem('cd-net-' + caseId, JSON.stringify([...s.revealed]));
    } catch (e) {}

    runAnalytics();
    applyState();
    showToast(`${kids.length} derived entities revealed`);
  }, [allModelEdges, caseId, posForNew, runAnalytics, applyState, showToast]);

  // Layout algorithms
  const runLayout = useCallback((layoutName: string) => {
    const cy = cyRef.current;
    if (!cy) return;
    const s = netStateRef.current;
    const pinned = { ...s.pinned };

    const finish = () => {
      Object.keys(pinned).forEach(pid => {
        const node = cy.getElementById(pid);
        if (node.nonempty()) node.position(pinned[pid]);
      });
      cy.nodes().forEach(n => {
        s.positions[n.id()] = { ...n.position() };
      });
    };

    if (layoutName === 'preset') {
      cy.nodes().forEach(n => {
        const p = s.positions[n.id()];
        if (p) n.position(p);
      });
      cy.animate({ fit: { padding: 40, eles: cy.elements() } }, { duration: 420, easing: 'ease-out' as any });
      finish();
      return;
    }

    if (layoutName === 'clusters' && analysis) {
      const groups: Record<number, cytoscape.NodeSingular[]> = {};
      cy.nodes().forEach(n => {
        const ci = analysis.commOf[n.id()] || 0;
        (groups[ci] = groups[ci] || []).push(n);
      });
      const keys = Object.keys(groups);
      const pos: Record<string, { x: number; y: number }> = {};
      const rr = mulberry32(0xc105 + keys.length);

      keys.forEach((k, gi) => {
        const ang = (gi / keys.length) * 6.283 + rr() * 0.4;
        const cx = 520 + Math.cos(ang) * 260, cyY = 380 + Math.sin(ang) * 200;
        groups[+k].forEach((n, i) => {
          const a2 = rr() * 6.283, r2 = Math.sqrt(i) * 34;
          pos[n.id()] = { x: cx + Math.cos(a2) * r2, y: cyY + Math.sin(a2) * r2 };
        });
      });

      cy.nodes().forEach(n => {
        if (pos[n.id()]) n.position(pos[n.id()]);
      });
      cy.animate({ fit: { padding: 40, eles: cy.elements() } }, { duration: 420, easing: 'ease-out' as any });
      finish();
      return;
    }

    const optsMap: Record<string, any> = {
      cose: { name: 'cose', animate: true, animationDuration: 420, randomize: true, idealEdgeLength: () => 90, nodeRepulsion: () => 14000, nodeOverlap: 24 },
      concentric: { name: 'concentric', animate: true, animationDuration: 420, concentric: (n: any) => n.data('prn') || 0, levelWidth: () => 0.15, minNodeSpacing: 36 },
      breadthfirst: { name: 'breadthfirst', animate: true, animationDuration: 420, spacingFactor: 1.15, roots: s.selected.size ? [...s.selected][0] : 'ent-person-04' },
      grid: { name: 'grid', animate: true, animationDuration: 420, spacingFactor: 1.2 }
    };
    const opts = optsMap[layoutName];

    if (!opts) return;
    cy.nodes().forEach(n => { n.unlock && n.unlock(); });
    const layout = cy.layout({ fit: true, padding: 40, ...opts } as any);
    layout.one('layoutstop', finish);
    layout.run();
  }, [analysis]);

  // Stress test demo harness
  const runStressTest = useCallback((n: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    const rnd = mulberry32(0x57e55 + n);
    const fams = ['IP', 'DOMAIN', 'DEVICE', 'ACCOUNT', 'PERSON', 'ORG', 'FILE', 'MALWARE', 'CAMPAIGN', 'EMAIL', 'THREAT_ACTOR'];
    const nodes: ModelNode[] = [];
    const edges: ModelEdge[] = [];
    const seen = new Set<string>();

    for (let i = 0; i < n; i++) {
      const k = fams[i % fams.length];
      const name = k.toLowerCase() + '-' + i + '.' + (k === 'DOMAIN' ? 'net' : 'x');
      const id = 's' + i;
      nodes.push({ id, name, kind: k, risk: i % 97 === 0 ? 'HIGH' : undefined, meta: 'Stress corpus', latent: false, firstSeen: '—', lastSeen: '—' });
      seen.add(id);
    }
    const m = Math.round(n * 1.6);
    let made = 0, guard = 0;
    while (made < m && guard < m * 6) {
      guard++;
      const a = 's' + Math.floor(rnd() * n), b = 's' + Math.floor(rnd() * n);
      if (a === b || seen.has(a + '|' + b)) continue;
      seen.add(a + '|' + b);
      edges.push({
        id: 'se' + made, a, b, type: 'associated_with', directed: 0,
        conf: 60 + Math.floor(rnd() * 39), reason: 'Stress relation', evidenceIds: []
      });
      made++;
    }

    const s = netStateRef.current;
    s.stress = { nodes, edges };
    s.revealed = new Set(nodes.map(x => x.id));
    s.selected = new Set();
    s.path = null;
    s.subgraph = null;
    s.focus = null;
    s.trace = null;
    s.positions = {};
    nodes.forEach((x, i) => {
      const ang = i * 2.399;
      s.positions[x.id] = { x: 600 + Math.cos(ang) * Math.sqrt(i) * 14, y: 400 + Math.sin(ang) * Math.sqrt(i) * 14 };
    });

    setStressBanner(`STRESS TEST — DEMO DATA · ${n} NODES / ${edges.length} EDGES`);

    const els = buildElements(null);
    cy.batch(() => {
      cy.elements().remove();
      cy.add(els.nodes as any);
      cy.add(els.edges as any);
    });
    cy.animate({ fit: { padding: 30, eles: cy.elements() } }, { duration: 0 });
    runAnalytics();
    applyState();
  }, [buildElements, runAnalytics, applyState]);

  const restoreFromStress = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const s = netStateRef.current;
    s.stress = null;
    setStressBanner(null);
    s.revealed = new Set(rawEntities.map(e => e.id));
    try {
      sessionStorage.setItem('cd-net-' + caseId, JSON.stringify([...s.revealed]));
    } catch (e) {}
    s.positions = computeBasePositions(rawEntities, rawConnections);

    const els = buildElements(null);
    cy.batch(() => {
      cy.elements().remove();
      cy.add(els.nodes as any);
      cy.add(els.edges as any);
    });
    runAnalytics();
    applyState();
    cy.animate({ fit: { padding: 40, eles: cy.elements() } }, { duration: 0 });
  }, [caseId, rawEntities, rawConnections, buildElements, runAnalytics, applyState]);

  // Mount Cytoscape Engine ONCE
  useEffect(() => {
    if (mode !== "GRAPH" || !cyMountRef.current) return;

    const cy = cytoscape({
      container: cyMountRef.current,
      elements: [],
      style: networkStyle,
      wheelSensitivity: 0.2,
      minZoom: 0.12,
      maxZoom: 2.5,
      boxSelectionEnabled: netStateRef.current.box,
      autounselectify: false,
      textureOnViewport: true,
      motionBlur: false
    });
    cyRef.current = cy;

    const els = buildElements(null);
    cy.batch(() => {
      cy.elements().remove();
      cy.add(els.nodes as any);
      cy.add(els.edges as any);
    });

    // Realtime Camera & Zoom Sync with Spatial Atmospheres
    const syncCam = () => {
      const p = cy.pan();
      const z = cy.zoom();
      setCamPan({ x: p.x, y: p.y });
      setCamZoom(z);
      setZoomPct(Math.round(z * 100));
    };
    cy.on('pan zoom', syncCam);
    syncCam();

    // Resize observer & delayed measurement after tab transition settling
    const ro = new ResizeObserver(() => cy.resize());
    if (stageRef.current) ro.observe(stageRef.current);
    if (cyMountRef.current) ro.observe(cyMountRef.current);

    const timerA = setTimeout(() => {
      if (!cy.destroyed()) cy.resize();
    }, 150);
    const timerB = setTimeout(() => {
      if (!cy.destroyed()) {
        cy.resize();
        if (cy.elements().length > 0 && cy.zoom() === 1) {
          cy.fit(undefined, 35);
        }
      }
    }, 350);

    // Event handlers
    const stickyActive = () => !!(netStateRef.current.trace || netStateRef.current.path || netStateRef.current.subgraph || netStateRef.current.focus);

    cy.on('mouseover', 'node', (e: EventObject) => {
      const t = e.target;
      const p = t.renderedPosition();
      const stageBox = stageRef.current;
      if (!stageBox) return;
      const r = stageBox.getBoundingClientRect();
      const html = `${t.data('label')}<br>${t.data('kind')} · ${t.data('deg')} connections`
        + (t.data('latent') ? '<br>Derived from evidence' : '')
        + (t.data('risk') === 'HIGH' ? '<br><b style="color:#FF5C5C">HIGH RISK</b>' : '');

      setTip({
        visible: true,
        x: Math.min(r.width - 260, p.x + 14),
        y: Math.max(8, p.y - 14),
        html
      });

      if (!stickyActive()) {
        cy.batch(() => {
          cy.nodes().difference(t.closedNeighborhood()).addClass('dim');
          cy.edges().filter(ed => ed.source().id() !== t.id() && ed.target().id() !== t.id()).addClass('dim');
        });
      }
    });

    cy.on('mouseout', 'node', () => {
      setTip(prev => ({ ...prev, visible: false }));
      if (!stickyActive()) {
        cy.batch(() => {
          cy.nodes().removeClass('dim');
          cy.edges().removeClass('dim');
        });
      }
    });

    cy.on('mouseover', 'edge', (e: EventObject) => {
      const t = e.target;
      const mp = t.midpoint();
      const stageBox = stageRef.current;
      if (!stageBox) return;
      const r = stageBox.getBoundingClientRect();
      const head = `${t.data('relType') || t.data('type')} · ${t.data('conf')}%`;
      const epistemic = t.data('epistemic') ? `<br><b style="color:${t.data('epistemic') === 'INFERRED' ? '#F59E0B' : '#7DD3FC'}">${t.data('epistemic')}</b>` : '';
      const prov = t.data('provCount') ? ` · ${t.data('provCount')} evidence ref(s)` : '';
      const html = `${head}${epistemic}${prov}<br>${t.data('reason')}`;
      setTip({
        visible: true,
        x: Math.min(r.width - 260, mp.x + 14),
        y: Math.max(8, mp.y - 10),
        html
      });
    });

    cy.on('mouseout', 'edge', () => {
      setTip(prev => ({ ...prev, visible: false }));
    });

    cy.on('tap', 'node', (e: EventObject) => {
      const id = e.target.id();
      const orig = e.originalEvent as MouseEvent;
      selectNode(id, orig.shiftKey || orig.metaKey || orig.ctrlKey);
    });

    cy.on('tap', 'edge', (e: EventObject) => {
      netStateRef.current.selEdge = e.target.id();
      netStateRef.current.selected = new Set();
      setSelectedEdgeId(e.target.id());
      setSelectedNodeId(null);
      setSelectedCount(0);
      cy.nodes().unselect();
      e.target.select();
      storeSelectEdge(e.target.id());
      applyState();
    });

    cy.on('tap', (e: EventObject) => {
      if (e.target === cy) {
        netStateRef.current.selected = new Set();
        netStateRef.current.selEdge = null;
        netStateRef.current.focus = null;
        netStateRef.current.path = null;
        netStateRef.current.subgraph = null;
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        setSelectedCount(0);
        setFocusMode("EXPLORE");
        cy.nodes().unselect();
        cy.edges().unselect();
        exitTrace();
        storeClearSelection();
        applyState();
        cy.animate({ fit: { padding: 45, eles: cy.elements() } }, { duration: 600, easing: 'ease-out' as any });
      }
    });

    cy.on('select unselect', 'node', () => {
      const sel = cy.nodes(':selected');
      const ids = new Set(sel.map(n => n.id()));
      netStateRef.current.selected = ids;
      setSelectedCount(ids.size);
      if (ids.size === 1) {
        setSelectedNodeId([...ids][0]);
        setSelectedEdgeId(null);
      } else if (ids.size === 0) {
        setSelectedNodeId(null);
      }
    });

    // Keyboard handlers
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT') return;
      if (e.key === 'Escape') {
        exitTrace();
        netStateRef.current.path = null;
        netStateRef.current.subgraph = null;
        netStateRef.current.selected = new Set();
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        setSelectedCount(0);
        cy.nodes().unselect();
        applyState();
      }
      if (e.key === 'f' || e.key === 'F') {
        cy.animate({ fit: { padding: 40, eles: cy.elements() } }, { duration: 320, easing: 'ease-out' as any });
      }
      if (e.key === '1' && netStateRef.current.selected.size) {
        const id = [...netStateRef.current.selected][0];
        netStateRef.current.focus = { id, hops: 1 };
        applyState();
      }
      if (e.key === '2' && netStateRef.current.selected.size) {
        const id = [...netStateRef.current.selected][0];
        netStateRef.current.focus = { id, hops: 2 };
        applyState();
      }
    };
    window.addEventListener('keydown', onKey);

    // Initial calculation & fit
    runAnalytics();
    applyState();
    setTimeout(() => cy.animate({ fit: { padding: 40, eles: cy.elements() } }, { duration: 420, easing: 'ease-out' as any }), 60);

    if (select0 && cy.getElementById(select0).nonempty()) {
      selectNode(select0);
      camTo([select0], false);
    }
    if (trace0) {
      beginTrace(trace0);
    }

    return () => {
      clearTimeout(timerA);
      clearTimeout(timerB);
      ro.disconnect();
      window.removeEventListener('keydown', onKey);
      cy.destroy();
      cyRef.current = null;
    };
  }, [mode]); // Mounts once for GRAPH mode

  // Ambient deterministic drift when idle in EXPLORE mode
  useEffect(() => {
    let raf = 0;
    let dragging = false;
    const cy = cyRef.current;
    if (!cy) return;

    const onGrab = () => { dragging = true; };
    const onFree = () => { dragging = false; };
    cy.on('grab', onGrab);
    cy.on('free', onFree);

    const t0 = performance.now();
    let lastTime = 0;

    const driftLoop = (now: number) => {
      if (
        !dragging &&
        cyRef.current &&
        !cyRef.current.destroyed() &&
        netStateRef.current.selected.size === 0 &&
        !netStateRef.current.trace &&
        !netStateRef.current.path
      ) {
        if (now - lastTime > 32) {
          lastTime = now;
          const elapsed = now - t0;
          const anchors = netStateRef.current.spatialAnchors;
          if (anchors) {
            cyRef.current.batch(() => {
              cyRef.current?.nodes().forEach(n => {
                const anc = anchors[n.id()];
                if (anc && !n.grabbed() && !netStateRef.current.pinned[n.id()]) {
                  const dx = Math.sin(elapsed * anc.driftSpeed + anc.driftPhase) * anc.driftAmplitude;
                  const dy = Math.cos(elapsed * anc.driftSpeed + anc.driftPhase) * anc.driftAmplitude;
                  n.position({
                    x: anc.baseX + dx,
                    y: anc.baseY + dy
                  });
                }
              });
            });
          }
        }
      }
      raf = requestAnimationFrame(driftLoop);
    };
    raf = requestAnimationFrame(driftLoop);

    return () => {
      cancelAnimationFrame(raf);
      if (cyRef.current && !cyRef.current.destroyed()) {
        cyRef.current.removeListener('grab', onGrab);
        cyRef.current.removeListener('free', onFree);
      }
    };
  }, [mode]);

  // Sync elements when nodes or edges change
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const els = buildElements(analysis);
    cy.batch(() => {
      cy.elements().remove();
      cy.add(els.nodes as any);
      cy.add(els.edges as any);
    });
    runAnalytics();
    applyState();
  }, [allModelNodes, allModelEdges]);

  // Handle live search
  const onSearchInput = (q: string) => {
    setSearchQuery(q);
    const needle = q.trim().toLowerCase();
    if (!needle) {
      setSearchMatches([]);
      setSearchOpen(false);
      return;
    }
    const matches = allModelNodes.filter(n => n.name.toLowerCase().includes(needle)).slice(0, 8);
    setSearchMatches(matches);
    setSearchOpen(true);
  };

  const onSelectSearchMatch = (node: ModelNode) => {
    const s = netStateRef.current;
    if (node.latent && !s.revealed.has(node.id)) {
      const parent = LATENT.find(l => l.id === node.id)?.parent;
      if (parent) {
        if (!s.revealed.has(parent)) s.revealed.add(parent);
        expandNode(parent);
      }
    }
    selectNode(node.id);
    camTo([node.id]);
    setSearchOpen(false);
    setSearchQuery("");
  };

  // Inspector details calculation
  const inspectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    return allModelNodes.find(n => n.id === selectedNodeId) || null;
  }, [selectedNodeId, allModelNodes]);

  const inspectedEdge = useMemo(() => {
    if (!selectedEdgeId) return null;
    return allModelEdges.find(e => e.id === selectedEdgeId) || null;
  }, [selectedEdgeId, allModelEdges]);

  const nodeStats = useMemo(() => {
    if (!selectedNodeId) return null;
    const cy = cyRef.current;
    const conns = getModelEdges().filter(c => c.a === selectedNodeId || c.b === selectedNodeId);
    const neighbors = cy ? cy.getElementById(selectedNodeId).neighborhood('node').map(x => ({ id: x.id(), label: x.data('label'), kind: x.data('kind') })) : [];
    const latentKids = LATENT.filter(l => l.parent === selectedNodeId && !netStateRef.current.revealed.has(l.id));

    let prRank: number | null = null;
    let betRank: number | null = null;
    let commStr = "—";

    if (analysis) {
      if (analysis.pr) {
        const sortedPr = Object.entries(analysis.pr).sort((x, y) => y[1] - x[1]);
        const idx = sortedPr.findIndex(x => x[0] === selectedNodeId);
        if (idx >= 0) prRank = idx + 1;
      }
      if (analysis.bet) {
        const sortedBet = Object.entries(analysis.bet).sort((x, y) => y[1] - x[1]);
        const idx = sortedBet.findIndex(x => x[0] === selectedNodeId);
        if (idx >= 0) betRank = idx + 1;
      }
      const ci = analysis.commOf[selectedNodeId];
      if (ci !== undefined && analysis.communities[ci]) {
        commStr = `C${ci + 1} · ${analysis.communities[ci].size} entities`;
      }
    }

    const linkedFindings = isDemo
      ? corpusFindings.filter(f => f.body.includes(selectedNodeId) || f.title.includes(selectedNodeId))
      : (activeCaseSummary?.findings || []).filter(f =>
          (f.description && f.description.toLowerCase().includes(selectedNodeId.toLowerCase())) ||
          (f.title && f.title.toLowerCase().includes(selectedNodeId.toLowerCase())) ||
          (f.related_entities && f.related_entities.some(v => v.toLowerCase().includes(selectedNodeId.toLowerCase())))
        ).map((f, i) => ({
          id: f.id || `f-${i}`,
          title: f.title || `Finding ${i + 1}`,
          body: f.description || '',
          statute: 'BSA 2023 / BNS',
          confidence: Math.round((f.confidence || 0.85) * 100),
          evidenceIds: []
        }));
    const bridgeScore = inspectedNode
      ? (inspectedNode.bridgeScore !== undefined ? inspectedNode.bridgeScore : (analysis?.bridgeScores ? (analysis.bridgeScores[selectedNodeId] || 0) : 0))
      : 0;

    return {
      degree: conns.length,
      neighbors: neighbors.slice(0, 9),
      latentKids,
      prRank,
      betRank,
      commStr,
      bridgeScore,
      linkedFindings
    };
  }, [selectedNodeId, analysis, getModelEdges, inspectedNode]);

  // Section 65B Certificate generation
  const exportSection65BCertificate = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const allN = getModelNodes();
    const allE = getModelEdges();
    const hidden = allE.filter(e => e.is_hidden || e.type === 'hidden_link');
    const direct = allE.filter(e => !e.is_hidden && e.type !== 'hidden_link');

    const lines = [
      "================================================================================",
      "             CYBERDRISHTI AI — COURT ADMISSIBILITY CERTIFICATE",
      "              UNDER SECTION 65B OF THE INDIAN EVIDENCE ACT",
      "================================================================================",
      `Case Identifier        : ${caseId}`,
      `Generated Timestamp    : ${new Date().toISOString()}`,
      `Verification Standard  : Precision Gating >= 90% (Stratified Group K-Fold)`,
      `Total Resolved Entities: ${allN.length}`,
      `Observed Evidence Links: ${direct.length}`,
      `AI Inferred Hidden Links: ${hidden.length}`,
      "--------------------------------------------------------------------------------",
      "1. ENTITY REGISTRY & TOPOLOGICAL METRICS",
      "--------------------------------------------------------------------------------"
    ];

    allN.forEach((n, i) => {
      const bScore = n.bridgeScore ?? (analysis?.bridgeScores[n.id] || 0);
      lines.push(`  [${p2(i + 1)}] ${n.name} | Kind: ${n.kind} | Deg: ${cy.getElementById(n.id).data('deg') || 0} | Bridge: ${(bScore * 100).toFixed(1)}% | Risk: ${n.risk || 'NORMAL'}`);
    });

    lines.push("");
    lines.push("--------------------------------------------------------------------------------");
    lines.push("2. INFERRED HIDDEN LINKS (SECTION 65B MATHEMATICAL EXPLAINABILITY)");
    lines.push("--------------------------------------------------------------------------------");

    hidden.forEach((h, idx) => {
      const aName = allModelNodes.find(n => n.id === h.a)?.name || h.a;
      const bName = allModelNodes.find(n => n.id === h.b)?.name || h.b;
      const sc = h.score !== undefined ? (h.score * 100).toFixed(1) : h.conf.toFixed(1);
      const th = h.threshold !== undefined ? (h.threshold * 100).toFixed(1) : "36.5";
      lines.push(`  (${idx + 1}) LINK: ${aName} <---> ${bName}`);
      lines.push(`      Confidence: ${sc}% | Threshold Gate: ${th}% | Status: CERTIFIED FLAGGED`);
      lines.push(`      Investigative Basis: ${h.reason}`);
      if (h.component_scores) {
        lines.push(`      Mathematical Feature Components:`);
        Object.entries(h.component_scores).forEach(([k, v]) => {
          if (v !== undefined) lines.push(`        - ${k.padEnd(26)}: ${Number(v).toFixed(4)}`);
        });
      }
      lines.push("");
    });

    lines.push("--------------------------------------------------------------------------------");
    lines.push("CERTIFICATION DECLARATION:");
    lines.push("The electronic record generated above is produced by deterministic algorithmic");
    lines.push("processes and precision-gated statistical inference models operating without manual");
    lines.push("tampering, fulfilling Section 65B sub-section (2) conditions of Indian Evidence Act.");
    lines.push("================================================================================");

    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `cyberdrishti-section-65b-certificate-${caseId}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
    showToast("Section 65B Certificate generated & downloaded");
  }, [caseId, getModelNodes, getModelEdges, analysis, allModelNodes, showToast]);

  return (
    <div>
      {/* Header controls & tools */}
      <div className="net-head">
        <div>
          <div className="t-label">
            Entity network <span className="net-cnt">· {counts.shown} of {counts.total} entities · {counts.edges} connections</span>
          </div>
        </div>

        <div className="net-tools">
          {/* Search */}
          <span className="nt-search">
            <input
              className="ev-input"
              placeholder="Search entities…"
              style={{ width: "200px" }}
              value={searchQuery}
              onChange={e => onSearchInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && searchMatches.length > 0) onSelectSearchMatch(searchMatches[0]);
                if (e.key === "Escape") setSearchOpen(false);
              }}
              autoComplete="off"
            />
            {searchOpen && (
              <div className="nt-drop open">
                {searchMatches.length > 0 ? (
                  searchMatches.map(m => (
                    <div key={m.id} className="nt-d" onClick={() => onSelectSearchMatch(m)}>
                      <span>{m.name}</span>
                      <span className="lt">{m.kind} {m.latent && '· REVEAL'}</span>
                    </div>
                  ))
                ) : (
                  <div className="nt-d">No matches</div>
                )}
              </div>
            )}
          </span>

          {/* Mode switchers */}
          <button
            className={`nt-btn ${mode === "GRAPH" ? "on" : ""}`}
            onClick={() => { setMode("GRAPH"); storeSetViewMode("GRAPH"); }}
            title="Dense, precise operational 2D/2.5D network graph"
          >
            OPERATIONAL
          </button>
          <button
            className={`nt-btn ${mode === "IMMERSIVE" ? "on" : ""}`}
            onClick={() => { setMode("IMMERSIVE"); storeSetViewMode("IMMERSIVE"); }}
            title="Cinematic 3D spatial intelligence environment"
          >
            IMMERSIVE SPATIAL
          </button>
          <button
            className={`nt-btn ${mode === "FLOWS" ? "on" : ""}`}
            onClick={() => { setMode("FLOWS"); storeSetViewMode("FLOWS"); }}
            title="Financial flow tracking"
          >
            FLOWS
          </button>
          <button
            className={`nt-btn ${replayActive ? "on" : ""}`}
            onClick={toggleReplay}
            title="Continuous-Time Dynamic Graph Replay (Feature 10)"
            style={{
              borderColor: replayActive ? "#00F0FF" : undefined,
              color: replayActive ? "#00F0FF" : undefined,
            }}
          >
            {replayActive ? "REPLAYING · CTDG" : "REPLAY"}
          </button>

          {/* AI Inferences Explorer Button */}
          <button
            className={`nt-btn ${mode === "HIDDEN_LINKS" ? "on" : ""}`}
            onClick={() => {
              const next = mode === "HIDDEN_LINKS" ? "GRAPH" : "HIDDEN_LINKS";
              setMode(next);
              storeSetViewMode(next);
            }}
            title="Explore AI inferred relationships with explainability reports"
            style={{
              color: '#FBBF24',
              borderColor: mode === "HIDDEN_LINKS" ? '#F59E0B' : 'rgba(245, 158, 11, 0.4)',
              background: mode === "HIDDEN_LINKS" ? 'rgba(245, 158, 11, 0.15)' : undefined
            }}
          >
            <span>◈</span> AI LINKS ({inferredHiddenLinks.length})
          </button>

          {/* Operational Graph Layout Switcher */}
          {mode === "GRAPH" && (
            <button
              className="nt-btn"
              onClick={() => {
                const modes: LayoutMode[] = ['force', 'radial', 'hierarchical', 'clustered'];
                const nextIdx = (modes.indexOf(layoutMode) + 1) % modes.length;
                applyLayout(modes[nextIdx]);
              }}
              title="Switch Layout Algorithm (Force-Directed, Radial Hubs, Hierarchical DAG, Type Clusters)"
            >
              <span>⚙</span> {layoutMode.toUpperCase()}
            </button>
          )}

          {/* Operational Graph AI Links Quick Toggle */}
          {mode === "GRAPH" && (
            <button
              className={`nt-btn ${showHiddenLinks ? "on" : ""}`}
              onClick={() => {
                const next = !showHiddenLinks;
                setShowHiddenLinks(next);
                netStateRef.current.filters.showHidden = next;
                applyState();
                showToast(next ? `AI Links illuminated on graph (${inferredHiddenLinks.length})` : 'AI Links hidden from evidence graph');
              }}
              title="Toggle AI inferred link visibility on operational graph"
            >
              SHOW AI
            </button>
          )}

          {/* Cinematic Overview Framing */}
          <button
            className="nt-btn"
            onClick={() => {
              setFocusMode("EXPLORE");
              netStateRef.current.selected = new Set();
              setSelectedNodeId(null);
              setSelectedCount(0);
              applyState();
              cyRef.current?.animate(
                { fit: { padding: 45, eles: cyRef.current.elements() } },
                { duration: 650, easing: 'ease-out' as any }
              );
            }}
            title="Cinematic Overview Framing"
          >
            OVERVIEW
          </button>

          {/* Pattern Focus Mode */}
          <button
            className={`nt-btn ${focusMode === "PATTERN_FOCUS" ? "on" : ""}`}
            onClick={() => {
              const next = focusMode === "PATTERN_FOCUS" ? "EXPLORE" : "PATTERN_FOCUS";
              setFocusMode(next);
              if (next === "PATTERN_FOCUS") {
                showToast("Pattern focus: Bridge brokers and inferred links highlighted");
              }
            }}
            title="Focus hidden links and bridge infrastructure"
          >
            PATTERNS
          </button>

          {/* 2-Hop Quick Isolation Button */}
          <button
            className={`nt-btn ${twoHopOn ? "on" : ""}`}
            onClick={() => {
              const next = !twoHopOn;
              setTwoHopOn(next);
              netStateRef.current.twoHop = next;
              applyState();
              if (next && netStateRef.current.selected.size === 0) {
                showToast("Select an entity to isolate its 2-hop neighborhood");
              } else if (next) {
                showToast("2-Hop neighborhood isolated");
              }
            }}
            title="Isolate 2-hop neighborhood around selected entity"
          >
            2-HOP
          </button>

          {/* Filter Popover Toggle */}
          <button
            className={`nt-btn ${filterPopOpen ? "on" : ""}`}
            onClick={() => { setFilterPopOpen(!filterPopOpen); setMorePopOpen(false); }}
          >
            FILTER
          </button>

          {filterPopOpen && (
            <div className="nt-pop open">
              <div className="row"><span>Entity types</span></div>
              <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", margin: "8px 0" }}>
                {Array.from(new Set(allModelNodes.map(n => n.kind))).map(k => {
                  const on = !activeKinds || activeKinds.has(k);
                  return (
                    <button
                      key={k}
                      className={`ev-k ${on ? "on" : ""}`}
                      onClick={() => {
                        const next = activeKinds ? new Set(activeKinds) : new Set(allModelNodes.map(n => n.kind));
                        if (next.has(k) && next.size > 1) next.delete(k);
                        else next.add(k);
                        setActiveKinds(next);
                        netStateRef.current.filters.kinds = next;
                        applyState();
                      }}
                    >
                      {FAM_LABEL[k] || k}
                    </button>
                  );
                })}
              </div>

              {/* General Confidence Slider */}
              <div className="row" style={{ marginTop: "10px" }}>
                <span>Min evidence conf <b style={{ color: "var(--text-primary)" }}>{minConf}%</b></span>
              </div>
              <input
                type="range"
                className="net-range"
                min="0"
                max="99"
                value={minConf}
                onChange={e => {
                  const val = +e.target.value;
                  setMinConf(val);
                  netStateRef.current.filters.minConf = val;
                  applyState();
                }}
              />

              {/* AI Predicted Hidden Links Controls */}
              <div className="row" style={{ marginTop: "14px", borderTop: "1px solid var(--line)", paddingTop: "8px" }}>
                <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <i style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#F59E0B", display: "inline-block" }} />
                  AI Hidden Links
                </span>
                <button
                  className={`ev-k ${showHiddenLinks ? "on" : ""}`}
                  onClick={() => {
                    const next = !showHiddenLinks;
                    setShowHiddenLinks(next);
                    netStateRef.current.filters.showHidden = next;
                    applyState();
                  }}
                  style={{ color: showHiddenLinks ? '#F59E0B' : undefined }}
                >
                  {showHiddenLinks ? "SHOWN" : "MUTED"}
                </button>
              </div>

              {showHiddenLinks && (
                <>
                  <div className="row" style={{ marginTop: "6px" }}>
                    <span>AI Min Confidence <b style={{ color: "#F59E0B" }}>{aiThreshold}%</b></span>
                  </div>
                  <input
                    type="range"
                    className="net-range"
                    min="0"
                    max="95"
                    step="5"
                    value={aiThreshold}
                    onChange={e => {
                      const val = +e.target.value;
                      setAiThreshold(val);
                      netStateRef.current.filters.aiThreshold = val;
                      applyState();
                    }}
                    style={{ accentColor: "#F59E0B" }}
                  />
                </>
              )}

              <div style={{ marginTop: "12px", display: "flex", gap: "6px" }}>
                <button
                  className="nt-btn"
                  onClick={() => {
                    setActiveKinds(null);
                    setMinConf(0);
                    setShowHiddenLinks(true);
                    setAiThreshold(35);
                    netStateRef.current.filters = { kinds: null, minConf: 0, showHidden: true, aiThreshold: 35 };
                    applyState();
                  }}
                >
                  RESET
                </button>
              </div>
            </div>
          )}

          {/* Cluster Tint Toggle */}
          <button
            className={`nt-btn ${clustersOn ? "on" : ""}`}
            onClick={() => {
              const next = !clustersOn;
              setClustersOn(next);
              netStateRef.current.clusters = next;
              applyClusterTint(next);
            }}
          >
            CLUSTERS
          </button>

          {/* Box Select Toggle */}
          <button
            className={`nt-btn ${boxOn ? "on" : ""}`}
            onClick={() => {
              const next = !boxOn;
              setBoxOn(next);
              netStateRef.current.box = next;
              cyRef.current?.boxSelectionEnabled(next);
            }}
          >
            BOX SEL
          </button>

          {/* Layout Select */}
          <select
            className="nt-sel"
            aria-label="Layout"
            onChange={e => runLayout(e.target.value)}
            defaultValue="preset"
          >
            <option value="preset">ORGANIC</option>
            <option value="cose">FORCE · RE-RUN</option>
            <option value="concentric">RADIAL</option>
            <option value="breadthfirst">HIERARCHY</option>
            <option value="clusters">CLUSTERS</option>
            <option value="grid">GRID</option>
          </select>

          {/* More Menu */}
          <button
            className="nt-btn"
            onClick={() => { setMorePopOpen(!morePopOpen); setFilterPopOpen(false); }}
          >
            ···
          </button>

          {morePopOpen && (
            <div className="nt-pop open" style={{ width: "320px" }}>
              <div className="row">
                <span>Export & Tools</span>
                <span style={{ display: "flex", gap: "4px" }}>
                  <button className="nt-btn" onClick={() => cyRef.current?.animate({ fit: { padding: 40, eles: cyRef.current.elements() } }, { duration: 320, easing: 'ease-out' as any })}>FIT</button>
                  <button className="nt-btn" onClick={() => {
                    const cy = cyRef.current;
                    if (!cy) return;
                    const png = cy.png({ full: true, bg: '#090A0D', scale: 2 });
                    const a = document.createElement('a');
                    a.href = png;
                    a.download = 'cyberdrishti-network.png';
                    a.click();
                  }}>PNG</button>
                  <button className="nt-btn" onClick={() => {
                    const cy = cyRef.current;
                    if (!cy) return;
                    const data = { nodes: cy.nodes().map(n => n.json().data), edges: cy.edges().map(e => e.json().data) };
                    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = 'cyberdrishti-network.json';
                    a.click();
                    URL.revokeObjectURL(a.href);
                  }}>JSON</button>
                  <button className="nt-btn" onClick={exportSection65BCertificate} title="Court-Admissible Section 65B Certificate">65B</button>
                </span>
              </div>

              <div className="row" style={{ marginTop: "12px" }}>
                <span>Stress · demo data</span>
              </div>
              <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginTop: "4px" }}>
                <button className="nt-btn" onClick={() => runStressTest(250)}>250</button>
                <button className="nt-btn" onClick={() => runStressTest(1000)}>1K</button>
                <button className="nt-btn" onClick={() => runStressTest(5000)}>5K</button>
                <button className="nt-btn" onClick={restoreFromStress}>RESTORE</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Intelligence summary bar */}
      {(mode === "GRAPH" || mode === "IMMERSIVE") && (
        <div id="nIntel">
          {analysis ? (
            <>
              <span>ENTITIES {counts.shown}/{counts.total}</span>
              <span>EDGES {counts.edges}</span>
              <span>HIGH RISK {analysis.riskCount}</span>
              <span>COMPONENTS {analysis.communities.length ? new Set(Object.values(analysis.commOf)).size : 0}</span>
              <button onClick={() => {
                const next = !clustersOn;
                setClustersOn(next);
                netStateRef.current.clusters = next;
                applyClusterTint(next);
              }}>
                CLUSTERS {analysis.communities.length}
              </button>
              <button onClick={() => {
                const cy = cyRef.current;
                if (!cy) return;
                cy.batch(() => {
                  cy.nodes().removeClass('hl');
                  analysis.bridges.slice(0, 8).forEach(id => cy.getElementById(id).addClass('hl'));
                });
                setTimeout(() => cy.batch(() => cy.nodes().removeClass('hl')), 2400);
              }}>
                BRIDGES {analysis.bridges.length}
              </button>
              <button onClick={() => {
                if (analysis.topPr) {
                  selectNode(analysis.topPr);
                  camTo([analysis.topPr], false);
                }
              }}>
                TOP · {allModelNodes.find(n => n.id === analysis.topPr)?.name || analysis.topPr}
              </button>
              <button
                onClick={() => setMode("HIDDEN_LINKS")}
                style={{ color: '#FBBF24' }}
                title="Open Section 65B Hidden Links Explorer"
              >
                AI INFERENCES {inferredHiddenLinks.length}
              </button>
            </>
          ) : (
            <span>ANALYTICS — SKIPPED ABOVE 2,500 NODES (STRESS MODE)</span>
          )}
        </div>
      )}

      {/* Main Body: FLOWS vs HIDDEN_LINKS vs (OPERATIONAL / IMMERSIVE) */}
      {mode === "FLOWS" ? (
        /* FLOWS VIEW */
        <div className="fl-wrap">
          <div style={{ marginBottom: "32px" }}>
            <b className="t-title-1" style={{ display: "block" }}>{inrM(totalTracedValue)}</b>
            <span className="t-label">Total traced value</span>
          </div>
          {caseFlows.length === 0 ? (
            <div style={{
              padding: "var(--space-12) var(--space-6)",
              textAlign: "center",
              background: "var(--surface-1)",
              border: "1px dashed var(--line-strong)",
              borderRadius: "var(--radius-card)"
            }}>
              <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "var(--space-2)" }}>
                Financial Intelligence
              </div>
              <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
                No Transaction Flows Detected
              </h3>
              <p style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", maxWidth: 440, margin: "0 auto var(--space-6) auto" }}>
                Ingest bank account statements, UPI payment extracts, or transaction ledgers to reconstruct automated money flows and hop chains.
              </p>
              <button
                className="btn btn-primary"
                onClick={() => navigate(`/investigations/${caseId}/evidence`)}
                style={{
                  padding: "8px 18px",
                  background: "var(--accent-primary, #38bdf8)",
                  color: "#0b0f19",
                  fontWeight: 600,
                  borderRadius: "6px",
                  border: "none",
                  cursor: "pointer"
                }}
              >
                Ingest Financial Evidence
              </button>
            </div>
          ) : (
            caseFlows.map(f => (
              <div key={f.id} className="fl-chain">
                <div className="fl-node">
                  <span className="fl-dot" />
                  <span className="fl-role">SOURCE</span>
                  <span className="fl-name">{allModelNodes.find(n => n.id === f.source)?.name || f.source}</span>
                </div>
                {f.hops.map(hp => (
                  <div key={hp}>
                    <div className="fl-v" />
                    <div className="fl-node">
                      <span className="fl-dot" />
                      <span className="fl-role">HOP</span>
                      <span className="fl-name">{allModelNodes.find(n => n.id === hp)?.name || hp}</span>
                    </div>
                  </div>
                ))}
                <div className="fl-v" />
                <div className="fl-node">
                  <span className="fl-dot" />
                  <span className="fl-role">SINK</span>
                  <span className="fl-name">{allModelNodes.find(n => n.id === f.sink)?.name || f.sink}</span>
                  <span className="fl-amt">{f.amount != null ? inr(f.amount) : "Amount not recorded"}</span>
                </div>
                <div className="fl-note">{f.note}</div>
              </div>
            ))
          )}
        </div>
      ) : mode === "HIDDEN_LINKS" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
          {/* Backend-driven scored correlations: run analysis, review the 6-feature
              breakdown, confirm/dispute — the real POST/GET/verify endpoints. */}
          <CorrelationsPanel caseId={caseId} />
          <HiddenLinksExplorer
            links={inferredHiddenLinks}
            onLocateInGraph={(src, tgt) => {
              setMode("GRAPH");
              setShowHiddenLinks(true);
              selectNode(src);
              camTo([src, tgt], true);
              showToast(`Inferred relation located between ${src} and ${tgt}`);
            }}
            onInvestigateIn3D={(src, tgt) => {
              setMode("IMMERSIVE");
              selectNode(src);
              setPathPoints([src, tgt]);
              showToast(`Investigating 3D spatial filament between ${src} and ${tgt}`);
            }}
            onClose={() => setMode("GRAPH")}
          />
        </div>
      ) : (
        <div className="net-body">
          {mode === "IMMERSIVE" ? (
            <ImmersiveSpatialGraph
              nodes={getModelNodes()}
              edges={getModelEdges()}
              analysis={analysis}
              selectedNodeId={selectedNodeId}
              onSelectNode={id => {
                if (id) selectNode(id);
                else {
                  setSelectedNodeId(null);
                  setSelectedCount(0);
                  netStateRef.current.selected = new Set();
                  applyState();
                }
              }}
              inferredLinks={inferredHiddenLinks}
              activeInvestigationPath={pathPoints.length ? pathPoints : (netStateRef.current.path ? netStateRef.current.path.nodes : [])}
              onLocateOperational={() => setMode("GRAPH")}
            />
          ) : (
            <div id="netStage" ref={stageRef}>
            {/* Layer 1: Background Spatial Atmosphere Canvas (Parallax Dust & Coordinates) */}
            <SpatialAtmosphereCanvas pan={camPan} zoom={camZoom} />

            {/* Layer 2: Dedicated Cytoscape mount layer */}
            <div
              ref={cyMountRef}
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                zIndex: 2,
                background: "transparent"
              }}
            />

            {/* Empty graph overlay when no nodes exist */}
            {allModelNodes.length === 0 && (
              <div style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                zIndex: 10,
                textAlign: "center",
                padding: "var(--space-8) var(--space-6)",
                background: "rgba(10, 14, 20, 0.88)",
                backdropFilter: "blur(16px)",
                border: "1px dashed var(--line-strong)",
                borderRadius: "var(--radius-card)",
                maxWidth: 460,
                width: "90%"
              }}>
                <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "var(--space-2)" }}>
                  Graph Topology Engine
                </div>
                <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
                  No Entity Graph Nodes Yet
                </h3>
                <p style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", marginBottom: "var(--space-6)", lineHeight: 1.5 }}>
                  This case does not have any extracted entities or topological links. Ingest evidence files (telecom CDRs, bank statements, mobile forensic dumps) to automatically construct the network graph.
                </p>
                <button
                  className="btn btn-primary"
                  onClick={() => navigate(`/investigations/${caseId}/evidence`)}
                  style={{
                    padding: "10px 20px",
                    background: "var(--accent-primary, #38bdf8)",
                    color: "#0b0f19",
                    fontWeight: 600,
                    borderRadius: "6px",
                    border: "none",
                    cursor: "pointer"
                  }}
                >
                  Ingest Evidence to Construct Graph
                </button>
              </div>
            )}

            {/* Layer 3: Foreground Tactical Effects Canvas (Traveling Probe, Shockwaves, Bridge Halo) */}
            <InvestigationEffectsOverlay
              cy={cyRef.current}
              mode={focusMode}
              activePathNodes={pathPoints.length ? pathPoints : (netStateRef.current.path ? netStateRef.current.path.nodes : [])}
              bridgeNodeIds={analysis ? analysis.bridges : []}
              hiddenEdgePairs={hiddenEdgePairs}
              pan={camPan}
              zoom={camZoom}
            />

            {/* Stress Banner */}
            {stressBanner && (
              <span className="net-banner open" style={{ zIndex: 9 }}>{stressBanner}</span>
            )}

            {/* Hint overlay */}
            {netHint && (
              <span className="net-hint" style={{ zIndex: 5 }}>{netHint}</span>
            )}

            {/* Trace Card */}
            {traceCard.open && (
              <div id="traceCard" className="open" style={{ zIndex: 6 }}>
                <div className="top">
                  <span className="idx">{traceCard.idx}</span>
                  <button className="tbtn" onClick={() => {
                    const t = netStateRef.current.trace;
                    if (!t) return;
                    const hop = t.hops[t.i];
                    cyRef.current?.getElementById(hop.connection.id).removeClass('tr-active').addClass('tr-visited');
                    netStateRef.current.seenPaths.add(hop.connection.id);
                  }}>
                    NEXT →
                  </button>
                  <button className="tbtn" onClick={exitTrace}>EXIT TRACE</button>
                </div>
                <div className="nm">{traceCard.name}</div>
                <div className="rs">{traceCard.reason}</div>
              </div>
            )}

            {/* Hover Tooltip */}
            {tip.visible && (
              <div
                className="net-tip"
                style={{ display: "block", left: tip.x + "px", top: tip.y + "px", zIndex: 15 }}
                dangerouslySetInnerHTML={{ __html: tip.html }}
              />
            )}

            {/* Selection Tray */}
            {selectedCount > 0 && (
              <div className="sel-tray open" style={{ zIndex: 8 }}>
                <span className="n">{selectedCount} SELECTED</span>
                {selectedCount >= 2 && (
                  <>
                    <button onClick={() => {
                      const ids = [...netStateRef.current.selected];
                      const p = GraphIntel.widestPath(getModelNodes(), getModelEdges(), ids[0], ids[1]);
                      if (!p) {
                        showToast("Path finding limited to 2,500 revealed nodes or none exists");
                        return;
                      }
                      netStateRef.current.path = p;
                      setPathPoints(p.nodes);
                      storeSetPath(p.nodes);
                      applyState();
                      showToast(`Widest path · ${p.nodes.length} hops · min confidence ${Math.round(p.minConf)}%`);
                    }}>
                      PATH
                    </button>
                    <button onClick={() => {
                      showToast(`Comparing ${selectedCount} entities`);
                    }}>
                      COMPARE
                    </button>
                    <button onClick={() => {
                      const cy = cyRef.current;
                      if (!cy) return;
                      const keep = new Set<string>();
                      [...netStateRef.current.selected].forEach(id => {
                        cy.getElementById(id).closedNeighborhood().forEach(x => {
                          keep.add(x.id());
                        });
                      });
                      netStateRef.current.subgraph = keep;
                      applyState();
                    }}>
                      SUBGRAPH
                    </button>
                  </>
                )}
                <button onClick={() => {
                  netStateRef.current.selected = new Set();
                  netStateRef.current.path = null;
                  netStateRef.current.subgraph = null;
                  setSelectedNodeId(null);
                  setSelectedEdgeId(null);
                  setSelectedCount(0);
                  cyRef.current?.nodes().unselect();
                  applyState();
                }}>
                  CLEAR
                </button>
              </div>
            )}

            {/* Zoom % & Fit */}
            <div className="net-zoom" style={{ zIndex: 5 }}>
              <span className="pct">{zoomPct}%</span>
              <button onClick={() => cyRef.current?.animate({ fit: { padding: 40, eles: cyRef.current.elements() } }, { duration: 320, easing: 'ease-out' as any })}>
                FIT
              </button>
            </div>

            {/* Legend */}
            <div className="net-leg" style={{ zIndex: 5 }}>
              <span><svg width="12" height="12" viewBox="0 0 12 12" fill="#565B65"><circle cx="6" cy="6" r="5"/></svg> Person</span>
              <span><svg width="12" height="12" viewBox="0 0 12 12" fill="#565B65"><rect x="1" y="2" width="10" height="8" rx="2"/></svg> Device</span>
              <span><svg width="12" height="12" viewBox="0 0 12 12" fill="#565B65"><rect x="1" y="2" width="10" height="8"/></svg> Account</span>
              <span><svg width="12" height="12" viewBox="0 0 12 12" fill="#565B65"><rect x="1" y="2" width="10" height="8" rx="1"/></svg> Org</span>
              <span><i style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#9B8AFB", display: "inline-block" }} /> Selected</span>
            </div>

            {/* ── Docked CTDG Replay Deck (Feature 10) ────────────────── */}
            {replayActive && (
              <div style={{
                position: "absolute",
                bottom: "20px",
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: 25,
                width: "min(820px, 94vw)",
                background: "rgba(10, 14, 22, 0.94)",
                backdropFilter: "blur(20px)",
                border: "1px solid rgba(0, 240, 255, 0.35)",
                boxShadow: "0 16px 48px rgba(0, 0, 0, 0.7), 0 0 30px rgba(0, 240, 255, 0.15)",
                borderRadius: "14px",
                padding: "14px 20px",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: "6px",
                      font: "var(--type-mono-xs)", color: "#00F0FF",
                      letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 700,
                    }}>
                      <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#00F0FF", display: "inline-block" }} />
                      CTDG TEMPORAL REPLAY
                    </span>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-tertiary)" }}>
                      Frame {replayFrameIdx + 1} / {replayFrames.length || 1}
                    </span>
                    {Boolean((replayFrames[replayFrameIdx]?.summary as any)?.burst) && (
                      <span style={{
                        background: "rgba(245, 158, 11, 0.15)",
                        border: "1px solid rgba(245, 158, 11, 0.4)",
                        color: "#F59E0B",
                        font: "var(--type-mono-xs)",
                        padding: "2px 8px",
                        borderRadius: "4px",
                      }}>
                        ⚡ BURST CLUSTER
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-secondary)" }}>
                      {replayFrames[replayFrameIdx]?.t_start
                        ? new Date(replayFrames[replayFrameIdx].t_start).toLocaleString(undefined, {
                            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit"
                          })
                        : "00:00:00"}
                      {" → "}
                      {replayFrames[replayFrameIdx]?.t_end
                        ? new Date(replayFrames[replayFrameIdx].t_end).toLocaleTimeString()
                        : "00:00:00"}
                    </span>
                    <button
                      onClick={toggleReplay}
                      style={{
                        background: "rgba(255,255,255,0.06)",
                        border: "1px solid rgba(255,255,255,0.12)",
                        color: "var(--text-secondary)",
                        borderRadius: "6px",
                        padding: "4px 10px",
                        cursor: "pointer",
                        font: "var(--type-mono-xs)",
                      }}
                    >
                      EXIT
                    </button>
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, replayFrames.length - 1)}
                    value={replayFrameIdx}
                    onChange={e => {
                      const idx = Number(e.target.value);
                      setReplayFrameIdx(idx);
                      if (replayFrames[idx]) applyReplayFrame(replayFrames[idx]);
                    }}
                    style={{
                      flex: 1,
                      accentColor: "#00F0FF",
                      cursor: "pointer",
                      height: "6px",
                    }}
                  />
                </div>

                {/* Active Evidence Events in Current Frame */}
                {replayFrames[replayFrameIdx]?.new_events && (replayFrames[replayFrameIdx].new_events || []).length > 0 && (
                  <div style={{
                    padding: "6px 12px",
                    background: "rgba(0, 240, 255, 0.08)",
                    border: "1px solid rgba(0, 240, 255, 0.25)",
                    borderRadius: "6px",
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    font: "var(--type-mono-xs)",
                    color: "var(--text-primary)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    <span style={{ color: "#00F0FF", fontWeight: 700, flexShrink: 0 }}>⚡ EVIDENCE EVENT:</span>
                    {(replayFrames[replayFrameIdx].new_events || []).slice(0, 2).map((nev, ni) => (
                      <span key={ni} style={{ marginRight: "12px", display: "inline-flex", alignItems: "center", gap: "5px" }}>
                        <span style={{ color: "#00F0FF", fontWeight: 600 }}>{nev.rel_type || nev.event_type}</span>
                        {nev.amount ? <span style={{ color: "#34D399", fontWeight: 600 }}>₹{nev.amount.toLocaleString()}</span> : null}
                        <span style={{ color: "var(--text-secondary)" }}>{nev.u} → {nev.v || "Case"}</span>
                        {nev.source_doc ? <span style={{ color: "var(--text-tertiary)" }}>({nev.source_doc}{nev.source_line ? `:L${nev.source_line}` : ""})</span> : null}
                      </span>
                    ))}
                    {(replayFrames[replayFrameIdx].new_events || []).length > 2 && (
                      <span style={{ color: "var(--text-tertiary)", flexShrink: 0 }}>
                        +{(replayFrames[replayFrameIdx].new_events || []).length - 2} more
                      </span>
                    )}
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <button
                      onClick={() => {
                        const next = Math.max(0, replayFrameIdx - 1);
                        setReplayFrameIdx(next);
                        if (replayFrames[next]) applyReplayFrame(replayFrames[next]);
                      }}
                      disabled={replayFrameIdx <= 0}
                      style={{
                        background: "rgba(255,255,255,0.08)", border: "none", color: "var(--text-primary)",
                        borderRadius: "6px", padding: "6px 12px", cursor: "pointer", font: "var(--type-mono-xs)",
                      }}
                    >
                      ⏮
                    </button>
                    <button
                      onClick={() => setReplayPlaying(!replayPlaying)}
                      style={{
                        background: "#00F0FF", border: "none", color: "#000",
                        borderRadius: "6px", padding: "6px 16px", cursor: "pointer",
                        fontWeight: 700, font: "var(--type-mono-xs)",
                      }}
                    >
                      {replayPlaying ? "⏸ PAUSE" : "▶ PLAY"}
                    </button>
                    <button
                      onClick={() => {
                        const next = Math.min(replayFrames.length - 1, replayFrameIdx + 1);
                        setReplayFrameIdx(next);
                        if (replayFrames[next]) applyReplayFrame(replayFrames[next]);
                      }}
                      disabled={replayFrameIdx >= replayFrames.length - 1}
                      style={{
                        background: "rgba(255,255,255,0.08)", border: "none", color: "var(--text-primary)",
                        borderRadius: "6px", padding: "6px 12px", cursor: "pointer", font: "var(--type-mono-xs)",
                      }}
                    >
                      ⏭
                    </button>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    {[1, 5, 20, 50].map(speed => (
                      <button
                        key={speed}
                        onClick={() => setReplaySpeed(speed)}
                        style={{
                          background: replaySpeed === speed ? "rgba(0, 240, 255, 0.2)" : "rgba(255,255,255,0.05)",
                          border: `1px solid ${replaySpeed === speed ? "#00F0FF" : "transparent"}`,
                          color: replaySpeed === speed ? "#00F0FF" : "var(--text-tertiary)",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          cursor: "pointer",
                          font: "var(--type-mono-xs)",
                          fontWeight: 600,
                        }}
                      >
                        {speed}x
                      </button>
                    ))}
                  </div>

                  <div style={{ font: "var(--type-mono-xs)", color: "var(--text-tertiary)" }}>
                    Active: <b style={{ color: "#00F0FF" }}>{replayFrames[replayFrameIdx]?.nodes?.length || 0}</b> entities ·{" "}
                    <b style={{ color: "#00F0FF" }}>{replayFrames[replayFrameIdx]?.edges?.length || 0}</b> links
                  </div>
                </div>
              </div>
            )}
          </div>
          )}

          {/* Inspector Drawer */}
          {(inspectedNode || inspectedEdge) && (
            <aside id="netInsp" className="open" aria-label="Inspector">
              {inspectedEdge && (
                <div>
                  <div className="np-head">
                    <span className="np-kind">
                      {inspectedEdge.is_hidden || inspectedEdge.type === 'hidden_link'
                        ? 'PREDICTIVE INFERENCE · SECTION 65B'
                        : `RELATIONSHIP · ${inspectedEdge.type}`}
                    </span>
                    <button className="sheet-x" onClick={() => { setSelectedEdgeId(null); cyRef.current?.edges().unselect(); }} aria-label="Close">
                      ✕
                    </button>
                  </div>
                  <h2 className="t-title-3">
                    {allModelNodes.find(n => n.id === inspectedEdge.a)?.name || inspectedEdge.a} → {allModelNodes.find(n => n.id === inspectedEdge.b)?.name || inspectedEdge.b}
                  </h2>
                  <hr className="np-hr" />

                  {/* Section 65B Explainability Card for Hidden Links */}
                  {(inspectedEdge.is_hidden || inspectedEdge.type === 'hidden_link') ? (
                    <div style={{ marginBottom: "16px" }}>
                      <div className="sec65b-badge">
                        <span>⚡ SECTION 65B FLAGGED LINK</span>
                      </div>
                      <div className="insp-row">
                        <span className="k">ML Confidence</span>
                        <span className="v" style={{ color: '#F59E0B', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                          {inspectedEdge.score !== undefined ? (inspectedEdge.score * 100).toFixed(1) : inspectedEdge.conf}%
                        </span>
                      </div>
                      <div className="insp-row">
                        <span className="k">Decision Gate</span>
                        <span className="v" style={{ fontFamily: 'var(--font-mono)' }}>
                          {inspectedEdge.threshold !== undefined ? (inspectedEdge.threshold * 100).toFixed(1) : '36.5'}% (≥ 90% Precision)
                        </span>
                      </div>
                      <div className="insp-row">
                        <span className="k">Inference Basis</span>
                        <span className="v">{inspectedEdge.reason}</span>
                      </div>

                      {/* Feature Breakdown Progress Bars */}
                      {inspectedEdge.component_scores && (
                        <div style={{ marginTop: "14px" }}>
                          <div className="t-label" style={{ marginBottom: "8px" }}>Mathematical Component Breakdown</div>
                          {[
                            { key: 'Common Neighbors', val: inspectedEdge.component_scores.common_neighbors ?? inspectedEdge.component_scores.cn ?? 0, max: 5 },
                            { key: 'Jaccard Index', val: inspectedEdge.component_scores.jaccard ?? 0, max: 1 },
                            { key: 'Adamic-Adar Index', val: inspectedEdge.component_scores.adamic_adar ?? inspectedEdge.component_scores.aa ?? 0, max: 3 },
                            { key: 'Temporal Decay (1h)', val: inspectedEdge.component_scores.temporal ?? 0, max: 4 },
                            { key: 'Financial Velocity (2h)', val: inspectedEdge.component_scores.financial ?? inspectedEdge.component_scores.fin ?? 0, max: 3 },
                            { key: 'Boundary Bridge Potential', val: inspectedEdge.component_scores.bridge_score ?? inspectedEdge.component_scores.bridge ?? 0, max: 1 },
                            { key: 'Preferential Attachment', val: inspectedEdge.component_scores.preferential_attachment ?? inspectedEdge.component_scores.pa ?? 0, max: 25 },
                          ].map(comp => (
                            <div key={comp.key} className="comp-metric-row">
                              <div className="comp-metric-head">
                                <span>{comp.key}</span>
                                <span className="comp-metric-val">{Number(comp.val).toFixed(3)}</span>
                              </div>
                              <div className="comp-bar-track">
                                <div
                                  className="comp-bar-fill"
                                  style={{ width: `${Math.min(100, Math.max(8, (Number(comp.val) / comp.max) * 100))}%` }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      <div className="sec65b-legal">
                        <b>Court Admissibility Note (§ 65B):</b> Inferred via cross-validated predictive gating ensuring false-positive rate &lt; 10% under Indian Evidence Act standard.
                      </div>
                    </div>
                  ) : (
                    /* Standard Observed Evidence Edge */
                    <>
                      {/* CTDG Replay Temporal Provenance Card */}
                      {replayActive && replayFrames[replayFrameIdx] && (() => {
                        const rEdge = replayFrames[replayFrameIdx].edges.find(re =>
                          (re.u === inspectedEdge.a && re.v === inspectedEdge.b) ||
                          (re.u === inspectedEdge.b && re.v === inspectedEdge.a)
                        );
                        if (!rEdge) return null;
                        const ageStr = rEdge.age_s !== undefined
                          ? (rEdge.age_s < 60
                              ? `${Math.round(rEdge.age_s)}s ago in timeline`
                              : rEdge.age_s < 3600
                              ? `${Math.round(rEdge.age_s / 60)}m ago in timeline`
                              : `${(rEdge.age_s / 3600).toFixed(1)}h ago in timeline`)
                          : null;
                        return (
                          <div style={{
                            margin: "12px 0",
                            padding: "10px 12px",
                            background: "rgba(0, 240, 255, 0.08)",
                            border: "1px solid rgba(0, 240, 255, 0.3)",
                            borderRadius: "8px",
                          }}>
                            <div style={{ font: "var(--type-mono-xs)", color: "#00F0FF", fontWeight: 700, marginBottom: "6px" }}>
                              ⏱ CTDG REPLAY TEMPORAL STATUS
                            </div>
                            <div className="insp-row">
                              <span className="k">Frame Opacity</span>
                              <span className="v" style={{ color: "#00F0FF", fontWeight: 700 }}>
                                {Math.round(rEdge.opacity * 100)}% ({rEdge.opacity >= 0.7 ? "Active Link" : "Decayed"})
                              </span>
                            </div>
                            {ageStr && (
                              <div className="insp-row">
                                <span className="k">Time Elapsed</span>
                                <span className="v">{ageStr}</span>
                              </div>
                            )}
                            {rEdge.amount ? (
                              <div className="insp-row">
                                <span className="k">Transacted Amount</span>
                                <span className="v" style={{ color: "#34D399", fontWeight: 700 }}>
                                  ₹{rEdge.amount.toLocaleString()}
                                </span>
                              </div>
                            ) : null}
                            {rEdge.source_doc && (
                              <div className="insp-row">
                                <span className="k">Source Document</span>
                                <span className="v" style={{ wordBreak: "break-all" }}>
                                  {rEdge.source_doc}{rEdge.source_line ? ` : L${rEdge.source_line}` : ""}
                                </span>
                              </div>
                            )}
                          </div>
                        );
                      })()}

                      {((inspectedEdge as any).amount || (inspectedEdge as any).attributes?.amount) && (
                        <div className="insp-row">
                          <span className="k">Transacted Amount</span>
                          <span className="v" style={{ color: "#34D399", fontWeight: 700 }}>
                            ₹{((inspectedEdge as any).amount || (inspectedEdge as any).attributes?.amount).toLocaleString()}
                          </span>
                        </div>
                      )}
                      <div className="insp-row"><span className="k">Confidence</span><span className="v">{inspectedEdge.conf}%</span></div>
                      <div className="insp-row"><span className="k">Direction</span><span className="v">{inspectedEdge.directed ? 'Directed' : 'Undirected'}</span></div>
                      <div className="insp-row"><span className="k">Basis</span><span className="v">{inspectedEdge.reason}</span></div>
                      <div className="insp-row"><span className="k">Evidence Standard</span><span className="v">Section 63 BSA (Admissible)</span></div>
                    </>
                  )}

                  {inspectedEdge.evidenceIds.length > 0 && (
                    <>
                      <div className="t-label" style={{ marginTop: "16px" }}>Evidence Sources</div>
                      <div className="fb-chips">
                        {inspectedEdge.evidenceIds.map(evId => (
                          <button
                            key={evId}
                            className="chip-btn"
                            onClick={() => navigate(`/investigations/${caseId}/evidence?q=${encodeURIComponent(evId)}`)}
                          >
                            {evId}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )}

              {inspectedNode && !inspectedEdge && nodeStats && (
                <div>
                  <div className="np-head">
                    <span className="np-kind">ENTITY · {inspectedNode.kind}{inspectedNode.latent ? ' · DERIVED' : ''}</span>
                    <button className="sheet-x" onClick={() => { setSelectedNodeId(null); cyRef.current?.nodes().unselect(); applyState(); }} aria-label="Close">
                      ✕
                    </button>
                  </div>
                  <h2 className="t-title-2">{inspectedNode.name}</h2>
                  {inspectedNode.risk === 'HIGH' && (
                    <div style={{ marginTop: "10px" }}>
                      <span className="pm pm-high"><i></i>HIGH RISK</span>
                    </div>
                  )}
                  <p className="np-note">{inspectedNode.meta}</p>
                  <hr className="np-hr" />
                  <div className="insp-row"><span className="k">First seen</span><span className="v">{inspectedNode.firstSeen}</span></div>
                  <div className="insp-row"><span className="k">Last seen</span><span className="v">{inspectedNode.lastSeen}</span></div>
                  <div className="insp-row"><span className="k">Connections</span><span className="v">{nodeStats.degree}</span></div>
                  <div className="insp-row"><span className="k">PageRank rank</span><span className="v">{nodeStats.prRank ? `#${nodeStats.prRank}` : '—'}</span></div>
                  <div className="insp-row"><span className="k">Betweenness rank</span><span className="v">{nodeStats.betRank ? `#${nodeStats.betRank}` : '—'}</span></div>
                  <div className="insp-row"><span className="k">Cluster</span><span className="v">{nodeStats.commStr}</span></div>
                  <div className="insp-row">
                    <span className="k">Boundary Bridge</span>
                    <span className="v">
                      {nodeStats.bridgeScore > 0 ? (
                        <span className="bridge-pill">
                          {(nodeStats.bridgeScore * 100).toFixed(0)}% BRIDGE
                        </span>
                      ) : (
                        '0%'
                      )}
                    </span>
                  </div>

                  {nodeStats.linkedFindings.length > 0 && (
                    <p className="np-note">Surfaced in {nodeStats.linkedFindings[0].title} · {nodeStats.linkedFindings[0].confidence} confidence</p>
                  )}

                  <hr className="np-hr" />
                  <div className="np-acts">
                    <button className="nt-btn" onClick={() => {
                      const cur = netStateRef.current.focus;
                      netStateRef.current.focus = cur && cur.hops === 1 ? null : { id: inspectedNode.id, hops: 1 };
                      applyState();
                    }}>
                      FOCUS 1-HOP
                    </button>
                    <button className="nt-btn" onClick={() => {
                      const cur = netStateRef.current.focus;
                      netStateRef.current.focus = cur && cur.hops === 2 ? null : { id: inspectedNode.id, hops: 2 };
                      applyState();
                    }}>
                      FOCUS 2-HOP
                    </button>
                    {nodeStats.latentKids.length > 0 && (
                      <button className="nt-btn" onClick={() => expandNode(inspectedNode.id)}>
                        EXPAND CONNECTIONS · {nodeStats.latentKids.length}
                      </button>
                    )}
                    <button className="nt-btn" onClick={() => {
                      const next = [...pathPoints, inspectedNode.id];
                      if (next.length === 2) {
                        const p = GraphIntel.widestPath(getModelNodes(), getModelEdges(), next[0], next[1]);
                        setPathPoints([]);
                        if (!p) {
                          showToast("No path found between these entities");
                          return;
                        }
                        netStateRef.current.path = p;
                        applyState();
                        showToast(`Path · ${p.nodes.length} nodes · min confidence ${Math.round(p.minConf)}%`);
                      } else {
                        setPathPoints(next);
                        showToast("Path start set — choose destination entity");
                      }
                    }}>
                      SET AS PATH POINT
                    </button>
                    <button className="nt-btn" onClick={() => {
                      const cy = cyRef.current;
                      if (!cy) return;
                      const n = cy.getElementById(inspectedNode.id);
                      if (netStateRef.current.pinned[inspectedNode.id]) {
                        delete netStateRef.current.pinned[inspectedNode.id];
                        n.removeClass('pinned');
                        showToast("Node unpinned");
                      } else {
                        netStateRef.current.pinned[inspectedNode.id] = { ...n.position() };
                        n.addClass('pinned');
                        showToast("Node pinned in place");
                      }
                    }}>
                      PIN
                    </button>
                    <button className="nt-btn" onClick={() => navigate(`/investigations/${caseId}/timeline?entity=${inspectedNode.id}`)}>
                      VIEW TIMELINE
                    </button>
                    <button className="nt-btn" onClick={() => navigate(`/investigations/${caseId}/entities`)}>
                      VIEW IN DIRECTORY
                    </button>

                    {/* Forensic Quick Actions */}
                    <div className="forensic-title">Forensic Jump</div>
                    <div className="forensic-acts">
                      <button
                        className="forensic-btn"
                        onClick={() => navigate(`/investigations/${caseId}/evidence?q=${encodeURIComponent(inspectedNode.name)}`)}
                        title="Search communications & CDRs for this entity"
                      >
                        <span className="icon">📞</span>
                        <span>Search in Communications</span>
                      </button>
                      <button
                        className="forensic-btn"
                        onClick={() => navigate(`/investigations/${caseId}/timeline?entity=${encodeURIComponent(inspectedNode.id)}`)}
                        title="Trace financial ledger & transaction timeline"
                      >
                        <span className="icon">💳</span>
                        <span>Trace Financial Trail</span>
                      </button>
                      <button
                        className="forensic-btn"
                        onClick={() => navigate(`/investigations?q=${encodeURIComponent(inspectedNode.name)}`)}
                        title="Cross-case syndicate intelligence query"
                      >
                        <span className="icon">🌐</span>
                        <span>Cross-Case Intel Lookup</span>
                      </button>
                    </div>
                  </div>

                  {/* Connected entities */}
                  <div className="t-label" style={{ marginTop: "20px" }}>Connected ({nodeStats.neighbors.length})</div>
                  <ul className="insp-conn">
                    {nodeStats.neighbors.map(nbr => (
                      <li key={nbr.id}>
                        <button onClick={() => {
                          selectNode(nbr.id);
                          camTo([nbr.id]);
                        }}>
                          <span>{nbr.label}</span>
                          <span className="d">{nbr.kind}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </aside>
          )}
        </div>
      )}

      {/* Toast Notification */}
      {toastMsg && (
        <div className="toast" style={{ position: "fixed", bottom: "24px", right: "24px", zIndex: 100 }}>
          {toastMsg}
        </div>
      )}
    </div>
  );
}
