/* ══════════ GRAPH ENGINE v2 — model · intelligence · data helpers ══════════ */
import { events } from "../../../data/events";
import { evidenceArchive } from "../../../data/evidence";

export const SHAPES: Record<string, string> = {
  PERSON: 'ellipse',
  PHONE: 'round-rectangle',
  DEVICE: 'round-rectangle',
  ACCOUNT: 'round-tag',
  UPI: 'diamond',
  IFSC: 'cut-rectangle',
  BANK: 'barrel',
  AMOUNT: 'round-tag',
  ORG: 'cut-rectangle',
  DOMAIN: 'barrel',
  IP: 'diamond',
  FILE: 'rectangle',
  MALWARE: 'round-diamond',
  CAMPAIGN: 'round-pentagon',
  EMAIL: 'pentagon',
  THREAT_ACTOR: 'heptagon'
};

export const TINTS = ['#5F5C64', '#5C6165', '#64615C', '#5C6460', '#5F5C61', '#615F5C'];

export const FAM_LABEL: Record<string, string> = {
  PERSON: 'Person',
  PHONE: 'Phone',
  DEVICE: 'Device',
  ACCOUNT: 'Account',
  UPI: 'UPI VPA',
  IFSC: 'IFSC Code',
  BANK: 'Bank Branch',
  AMOUNT: 'Amount (INR)',
  ORG: 'Organization',
  DOMAIN: 'Domain',
  IP: 'IP Address',
  FILE: 'File Hash',
  MALWARE: 'Malware',
  CAMPAIGN: 'Campaign',
  EMAIL: 'Email',
  THREAT_ACTOR: 'Threat actor'
};

export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const seedOf = (s: string) => [...String(s)].reduce((a, c) => a + c.charCodeAt(0), 0);
export const p2 = (n: number) => String(n).padStart(2, '0');

/* typed edges — taxonomy + direction */
export const EDGE_DIR: Record<string, number> = {
  uses_device: 1, uses_phone: 1, transacts_to: 1, controls: 1, holds: 1, holds_vpa: 1,
  settles_to: 1, branch_of: 1, operates_branch: 1, resolves_to: 1, contacted: 1, handled: 1,
  communicates_with: 0, associated_with: 0, paired_with: 0, hidden_link: 0
};

export const typeFor = (ka: string, kb: string, _aid?: string, _bid?: string): [string, number] => {
  if (ka === 'PERSON' && kb === 'DEVICE') return ['uses_device', 1];
  if (ka === 'PERSON' && kb === 'PHONE') return ['uses_phone', 1];
  if (ka === 'PERSON' && kb === 'ACCOUNT') return ['holds', 1];
  if (ka === 'PERSON' && kb === 'UPI') return ['holds_vpa', 1];
  if (ka === 'ACCOUNT' && kb === 'ACCOUNT') return ['transacts_to', 1];
  if (ka === 'UPI' && kb === 'UPI') return ['transacts_to', 1];
  if (ka === 'UPI' && kb === 'ACCOUNT') return ['settles_to', 1];
  if (ka === 'ACCOUNT' && kb === 'IFSC') return ['branch_of', 1];
  if (ka === 'BANK' && kb === 'IFSC') return ['operates_branch', 1];
  if (ka === 'ORG') return ['controls', 1];
  if (ka === 'PERSON' && kb === 'PERSON') return ['communicates_with', 0];
  if ((ka === 'DEVICE' && kb === 'ACCOUNT') || (ka === 'ACCOUNT' && kb === 'DEVICE')) return ['associated_with', 0];
  if (ka === 'DEVICE' && kb === 'DEVICE') return ['paired_with', 0];
  return ['associated_with', 0];
};

/* latent layer — infrastructure derived from evidence, revealed by progressive expansion */
export interface LatentNode {
  id: string;
  name: string;
  kind: string;
  meta: string;
  parent: string;
  conf: number;
  ev?: string;
  host?: string;
}

export interface LatentEdge {
  id: string;
  a: string;
  b: string;
  type: string;
  directed: number;
  conf: number;
  reason: string;
  evidenceIds: string[];
}

export const LATENT: LatentNode[] = [];
export const LATENT_EDGES: LatentEdge[] = [];

(function () {
  const push = (o: LatentNode) => LATENT.push(o);
  const dom = [
    'cdn-shadow07.com', 'sync-relay.net', 'mule-panel.io', 'srv-verify9.com', 'pay-gate24.net',
    'ob-relay2.com', 'vault-sync.net', 'kite-drop.io', 'relay-mesh9.net', 'panel-abcd.com', 'gate-kestrel.net', 'mirror-42.io'
  ];
  dom.forEach((n, i) => push({
    id: 'lat-dom-' + p2(i + 1),
    name: n,
    kind: 'DOMAIN',
    meta: 'Registered 2026 · privacy proxy',
    parent: i < 4 ? 'ent-device-a83f' : ('ent-g-d' + ((i % 5) + 1)),
    conf: 70 + ((i * 9) % 25),
    ev: 'evd-cdr-' + p2(3 + i * 3)
  }));

  const ips = ['192.0.2.41', '198.51.100.7', '203.0.113.88', '192.0.2.133', '198.51.100.214', '203.0.113.19', '192.0.2.77', '198.51.100.63'];
  ips.forEach((n, i) => push({
    id: 'lat-ip-' + p2(i + 1),
    name: n,
    kind: 'IP',
    meta: 'Hosting · ' + ('AS' + (14000 + i * 137)),
    parent: 'lat-dom-' + p2((i % 6) + 1),
    conf: 88,
    host: 'lat-dom-' + p2((i % 6) + 1)
  }));

  const files = [
    ['sha:8f3a…c21e', 'Statement bundle'], ['sha:44b1…09af', 'Annexure scan'], ['sha:c7d9…5e22', 'KYC pack'],
    ['sha:1a02…f7b3', 'Device export'], ['sha:9e31…cc04', 'Ledger extract'], ['sha:77af…31bd', 'Comms archive'],
    ['sha:5d0e…9a41', 'Transfer slips'], ['sha:e2b8…660f', 'Registration set']
  ];
  files.forEach((f, i) => push({
    id: 'lat-file-' + p2(i + 1),
    name: f[0],
    kind: 'FILE',
    meta: f[1] + ' · ' + f[0],
    parent: i < 4 ? 'ent-account-4821' : 'ent-g-a' + ((i % 6) + 1),
    conf: 64 + ((i * 7) % 30),
    ev: 'evd-scan-' + p2((i % 8) + 1)
  }));

  LATENT.forEach(l => {
    if (l.kind === 'DOMAIN') {
      LATENT_EDGES.push({
        id: 'le-' + l.id,
        a: l.parent,
        b: l.id,
        type: 'contacted',
        directed: 1,
        conf: l.conf,
        reason: 'Observed in CDR metadata',
        evidenceIds: [l.ev || 'evd-cdr-18']
      });
    }
    if (l.kind === 'FILE') {
      LATENT_EDGES.push({
        id: 'le-' + l.id,
        a: l.parent,
        b: l.id,
        type: 'handled',
        directed: 1,
        conf: l.conf,
        reason: 'Document handled during window',
        evidenceIds: [l.ev || 'evd-scan-01']
      });
    }
  });

  LATENT.filter(l => l.kind === 'IP').forEach(ip => {
    LATENT_EDGES.push({
      id: 'le-' + ip.id,
      a: ip.parent,
      b: ip.id,
      type: 'resolves_to',
      directed: 1,
      conf: 95,
      reason: 'DNS resolution',
      evidenceIds: []
    });
  });
})();

export interface ModelNode {
  id: string;
  name: string;
  kind: string;
  risk?: string;
  latent: boolean;
  meta: string;
  firstSeen: string;
  lastSeen: string;
  evidenceIds?: string[];
  bridgeScore?: number;
  mentionCount?: number;
}

export interface ModelEdge {
  id: string;
  a: string;
  b: string;
  type: string;
  directed: number;
  conf: number;
  reason: string;
  evidenceIds: string[];
  is_hidden?: boolean;
  score?: number;
  threshold?: number;
  component_scores?: {
    common_neighbors?: number;
    jaccard?: number;
    adamic_adar?: number;
    temporal?: number;
    financial?: number;
    bridge_score?: number;
    preferential_attachment?: number;
    [key: string]: number | undefined;
  };
  // Unified case-graph provenance (observed semantic edges).
  relationship_type?: string;
  epistemic_status?: "OBSERVED" | "INFERRED";
  direction?: string;
  evidence_refs?: string[];
  event_refs?: string[];
}

/* ── Section 65B Explainable AI Hidden Link Data Model ── */
export interface HiddenLinkReason {
  type: "SHARED_DEVICE" | "TEMPORAL_CORRELATION" | "FINANCIAL_MATCH" | "CROSS_CLUSTER_BRIDGE" | "STRUCTURAL_SIMILARITY";
  title: string;
  description: string;
  contribution: "STRONG" | "MEDIUM" | "SUPPORTING";
  score: number;
}

export interface InferredHiddenLink {
  id: string;
  sourceId: string;
  targetId: string;
  sourceName: string;
  targetName: string;
  sourceKind?: string;
  targetKind?: string;
  confidence: number; // 0 - 100% (Inference confidence, NOT evidence truth)
  score: number;
  threshold: number;
  crossCluster: boolean;
  sourceCommunity?: number;
  targetCommunity?: number;
  reasons: HiddenLinkReason[];
  supportingEvidenceIds: string[];
  inferenceMethod: string;
  status: "candidate" | "under_review" | "confirmed" | "rejected";
}

const evById = new Map(evidenceArchive.map(e => [e.id, e]));

/* Canonical synthetic AI predicted hidden links (Section 65B precision-gated) */
export const CANONICAL_HIDDEN_EDGES: ModelEdge[] = [
  {
    id: "hid-01",
    a: "ent-person-04",
    b: "ent-account-72",
    type: "hidden_link",
    directed: 0,
    conf: 88,
    score: 0.884,
    threshold: 0.365,
    reason: "Section 65B ML Inference: Multi-hop transaction timing + shared mule handler",
    evidenceIds: ["evd-txn-45000", "evd-cdr-18"],
    is_hidden: true,
    component_scores: {
      common_neighbors: 2.0,
      jaccard: 0.40,
      adamic_adar: 1.62,
      temporal: 2.15,
      financial: 1.84,
      bridge_score: 0.50,
      preferential_attachment: 18.0
    }
  },
  {
    id: "hid-02",
    a: "ent-device-a83f",
    b: "ent-account-72",
    type: "hidden_link",
    directed: 0,
    conf: 76,
    score: 0.762,
    threshold: 0.365,
    reason: "Section 65B ML Inference: Co-temporal session overlap + IMEI beacon correlation",
    evidenceIds: ["evd-cdr-04"],
    is_hidden: true,
    component_scores: {
      common_neighbors: 1.0,
      jaccard: 0.25,
      adamic_adar: 0.91,
      temporal: 1.72,
      financial: 0.0,
      bridge_score: 0.33,
      preferential_attachment: 12.0
    }
  },
  {
    id: "hid-03",
    a: "ent-account-4821",
    b: "ent-g-a3",
    type: "hidden_link",
    directed: 0,
    conf: 92,
    score: 0.925,
    threshold: 0.365,
    reason: "Section 65B ML Inference: Financial velocity decay match ₹45,000 within 4 mins",
    evidenceIds: ["evd-txn-45000"],
    is_hidden: true,
    component_scores: {
      common_neighbors: 2.0,
      jaccard: 0.50,
      adamic_adar: 1.44,
      temporal: 2.85,
      financial: 2.40,
      bridge_score: 0.25,
      preferential_attachment: 16.0
    }
  },
  {
    id: "hid-04",
    a: "ent-g-p1",
    b: "ent-g-a2",
    type: "hidden_link",
    directed: 0,
    conf: 69,
    score: 0.695,
    threshold: 0.365,
    reason: "Section 65B ML Inference: Boundary traversal linking Cluster A to Cluster B",
    evidenceIds: ["evd-cdr-18"],
    is_hidden: true,
    component_scores: {
      common_neighbors: 1.0,
      jaccard: 0.20,
      adamic_adar: 0.82,
      temporal: 1.10,
      financial: 0.0,
      bridge_score: 0.67,
      preferential_attachment: 8.0
    }
  },
  {
    id: "hid-05",
    a: "ent-g-p3",
    b: "ent-account-4821",
    type: "hidden_link",
    directed: 0,
    conf: 52,
    score: 0.524,
    threshold: 0.365,
    reason: "Section 65B ML Inference: Shared device routing via intermediary relay",
    evidenceIds: ["evd-dev-meta-29"],
    is_hidden: true,
    component_scores: {
      common_neighbors: 0.0,
      jaccard: 0.0,
      adamic_adar: 0.0,
      temporal: 1.42,
      financial: 0.85,
      bridge_score: 0.20,
      preferential_attachment: 8.0
    }
  }
];

/* model constructor */
export const GraphModel = {
  firstSeen: {} as Record<string, string>,
  lastSeen: {} as Record<string, string>,

  seen() {
    events.forEach(e => {
      (e.entityIds || []).forEach(id => {
        const k = e.date + ' ' + e.ts;
        if (!GraphModel.firstSeen[id] || k < GraphModel.firstSeen[id]) GraphModel.firstSeen[id] = k;
        if (!GraphModel.lastSeen[id] || k > GraphModel.lastSeen[id]) GraphModel.lastSeen[id] = k;
      });
    });
  },

  allNodes(rawEntities: Array<{ id: string; name?: string; label?: string; kind: string; risk?: string; meta?: string; bridgeScore?: number; mentionCount?: number }>, isDemo: boolean = false): ModelNode[] {
    GraphModel.seen();
    const rec: ModelNode[] = rawEntities.map(e => ({
      id: e.id,
      name: e.name || e.label || e.id,
      kind: e.kind,
      risk: e.risk,
      meta: e.meta || '',
      latent: false,
      firstSeen: GraphModel.firstSeen[e.id] || '—',
      lastSeen: GraphModel.lastSeen[e.id] || '—',
      bridgeScore: e.bridgeScore,
      mentionCount: e.mentionCount
    }));

    if (!isDemo) {
      return rec;
    }

    const lat: ModelNode[] = LATENT.map(l => ({
      id: l.id,
      name: l.name,
      kind: l.kind,
      latent: true,
      meta: l.meta,
      firstSeen: l.ev ? (evById.get(l.ev) || {}).meta || '—' : '—',
      lastSeen: '—'
    }));

    return [...rec, ...lat];
  },

  allEdges(
    rawConnections: Array<{ id: string; a: string; b: string; type?: string; directed?: number; confidence?: number; reason?: string; evidenceIds?: string[]; is_hidden?: boolean; score?: number; threshold?: number; component_scores?: Record<string, number>; relationship_type?: string; epistemic_status?: "OBSERVED" | "INFERRED"; direction?: string; evidence_refs?: string[]; event_refs?: string[] }>,
    entityKindMap: Map<string, string>,
    isDemo: boolean = false
  ): ModelEdge[] {
    const out: ModelEdge[] = rawConnections.map(cn => {
      let t = cn.type;
      let d = cn.directed;
      const isHidden = cn.is_hidden || t === 'hidden_link';
      if (!t) {
        const ka = entityKindMap.get(cn.a) || 'ORG';
        const kb = entityKindMap.get(cn.b) || 'ORG';
        const [resolvedType, resolvedDir] = typeFor(ka, kb, cn.a, cn.b);
        t = resolvedType;
        d = resolvedDir;
      }
      return {
        id: cn.id,
        a: cn.a,
        b: cn.b,
        type: isHidden ? 'hidden_link' : t,
        directed: d !== undefined ? d : (EDGE_DIR[t] || 0),
        conf: cn.confidence || (cn.score ? Math.round(cn.score * 100) : 85),
        reason: cn.reason || (isHidden ? 'Section 65B Inferred Correlation' : 'Correlated activity window'),
        // Real provenance only — never fabricate an evidence id for a real case.
        evidenceIds: cn.evidenceIds || cn.evidence_refs || [],
        is_hidden: isHidden,
        score: cn.score,
        threshold: cn.threshold || 0.365,
        component_scores: cn.component_scores,
        relationship_type: cn.relationship_type,
        epistemic_status: cn.epistemic_status,
        direction: cn.direction,
        evidence_refs: cn.evidence_refs,
        event_refs: cn.event_refs
      };
    });

    if (isDemo) {
      LATENT_EDGES.forEach(le => {
        out.push({
          id: le.id,
          a: le.a,
          b: le.b,
          type: le.type,
          directed: le.directed,
          conf: le.conf,
          reason: le.reason,
          evidenceIds: le.evidenceIds || []
        });
      });

      // If no hidden links were supplied in raw connections, append the canonical hidden links
      const hasHidden = out.some(e => e.is_hidden || e.type === 'hidden_link');
      if (!hasHidden) {
        CANONICAL_HIDDEN_EDGES.forEach(h => {
          out.push({ ...h });
        });
      }
    }

    return out;
  }
};

/* intelligence — deterministic, seeded; graphology-equivalent semantics */
export interface IntelAnalysis {
  deg: Record<string, number>;
  pr: Record<string, number>;
  prn: (v: string) => number;
  bet: Record<string, number> | null;
  commOf: Record<string, number>;
  communities: { id: string; size: number; rep: string; members: string[] }[];
  bridges: string[];
  bridgeScores: Record<string, number>;
  mostConnected: string;
  topPr: string;
  riskCount: number;
}

export const GraphIntel = {
  analyze(nodes: ModelNode[], edges: ModelEdge[]): IntelAnalysis {
    const ids = nodes.map(n => n.id);
    const n = ids.length;
    const adj: Record<string, { v: string; c: number }[]> = {};
    const deg: Record<string, number> = {};
    ids.forEach(i => { adj[i] = []; deg[i] = 0; });
    edges.forEach(e => {
      if (adj[e.a] && adj[e.b]) {
        adj[e.a].push({ v: e.b, c: e.conf });
        adj[e.b].push({ v: e.a, c: e.conf });
        deg[e.a]++;
        deg[e.b]++;
      }
    });

    /* pagerank */
    let pr: Record<string, number> = {};
    ids.forEach(i => pr[i] = 1 / (n || 1));
    for (let it = 0; it < 20; it++) {
      const nx: Record<string, number> = {};
      ids.forEach(i => nx[i] = (1 - 0.85) / (n || 1));
      ids.forEach(v => {
        const out = adj[v].length;
        const share = out ? pr[v] * 0.85 / out : pr[v] * 0.85 / (n || 1);
        if (out) adj[v].forEach(({ v: w }) => nx[w] += share);
        else ids.forEach(w => nx[w] += share);
      });
      pr = nx;
    }
    const prMax = Math.max(1e-9, ...ids.map(i => pr[i] || 0));

    /* betweenness (Brandes) — skipped above 2,500 nodes */
    let bet: Record<string, number> | null = null;
    if (n <= 2500) {
      bet = {};
      ids.forEach(i => bet![i] = 0);
      for (const s of ids) {
        const S: string[] = [], P: Record<string, string[]> = {}, sig: Record<string, number> = {}, d: Record<string, number> = {};
        ids.forEach(v => { P[v] = []; sig[v] = 0; d[v] = -1; });
        sig[s] = 1; d[s] = 0;
        const Q = [s];
        while (Q.length) {
          const v = Q.shift()!;
          S.push(v);
          for (const { v: w } of adj[v]) {
            if (d[w] < 0) { d[w] = d[v] + 1; Q.push(w); }
            if (d[w] === d[v] + 1) { sig[w] += sig[v]; P[w].push(v); }
          }
        }
        const del: Record<string, number> = {};
        ids.forEach(v => del[v] = 0);
        while (S.length) {
          const w = S.pop()!;
          for (const v of P[w]) del[v] += sig[v] / sig[w] * (1 + del[w]);
          if (w !== s) bet[w] += del[w];
        }
      }
      const bMax = Math.max(1e-9, ...ids.map(i => bet![i] || 0));
      ids.forEach(i => bet![i] /= bMax);
    }

    /* components */
    const comp: Record<string, number> = {};
    let cc = 0;
    ids.forEach(s => {
      if (comp[s] !== undefined) return;
      cc++;
      const st = [s];
      comp[s] = cc;
      while (st.length) {
        const v = st.pop()!;
        for (const { v: w } of adj[v]) {
          if (comp[w] === undefined) { comp[w] = cc; st.push(w); }
        }
      }
    });

    /* communities — seeded label propagation */
    const rnd = mulberry32(0xc0c0a + n);
    const lab: Record<string, number> = {};
    ids.forEach((v, i) => lab[v] = i);
    const order = [...ids];
    for (let it = 0; it < 8; it++) {
      for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(rnd() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
      }
      for (const v of order) {
        const cnt: Record<number, number> = {};
        adj[v].forEach(({ v: w }) => cnt[lab[w]] = (cnt[lab[w]] || 0) + 1);
        let best = lab[v], bc = cnt[best] || 0;
        for (const k in cnt) {
          const numK = +k;
          if (cnt[numK] > bc || (cnt[numK] === bc && numK < best)) {
            best = numK;
            bc = cnt[numK];
          }
        }
        lab[v] = best;
      }
    }

    const commMap: Record<number, string[]> = {};
    ids.forEach(v => {
      const k = lab[v];
      (commMap[k] = commMap[k] || []).push(v);
    });

    const communities = Object.values(commMap).map(members => {
      const rep = members.reduce((a, b) => (deg[b] > deg[a] ? b : a), members[0]);
      return { id: members[0], size: members.length, rep, members };
    }).sort((a, b) => b.size - a.size);

    const commOf: Record<string, number> = {};
    communities.forEach((c, ci) => c.members.forEach(m => commOf[m] = ci));

    /* Boundary BridgeScore: fraction of a node's edges that cross community boundaries */
    const bridgeScores: Record<string, number> = {};
    ids.forEach(v => {
      const neighbors = adj[v] || [];
      if (!neighbors.length) {
        bridgeScores[v] = 0.0;
        return;
      }
      const myComm = commOf[v];
      const cross = neighbors.filter(({ v: w }) => commOf[w] !== myComm).length;
      bridgeScores[v] = Math.round((cross / neighbors.length) * 1000) / 1000;
    });

    /* Bridges: sorted by BridgeScore then centrality */
    const bridges = ids.filter(v => (bridgeScores[v] || 0) > 0)
      .sort((a, b) => ((bridgeScores[b] || 0) - (bridgeScores[a] || 0)) || (((bet ? bet[b] : deg[b]) || 0) - ((bet ? bet[a] : deg[a]) || 0)));

    const mostConnected = ids.reduce((a, b) => (deg[b] > deg[a] ? b : a), ids[0] || '');
    const topPr = ids.reduce((a, b) => (pr[b] > pr[a] ? b : a), ids[0] || '');

    return {
      deg,
      pr,
      prn: (v: string) => (pr[v] || 0) / prMax,
      bet,
      commOf,
      communities,
      bridges,
      bridgeScores,
      mostConnected,
      topPr,
      riskCount: nodes.filter(x => x.risk === 'HIGH').length
    };
  },

  widestPath(nodes: ModelNode[], edges: ModelEdge[], a: string, b: string) {
    const n = nodes.length;
    if (n > 2500) return null;
    const adj: Record<string, { v: string; c: number; e: string }[]> = {};
    nodes.forEach(x => adj[x.id] = []);
    edges.forEach(e => {
      if (adj[e.a] && adj[e.b]) {
        adj[e.a].push({ v: e.b, c: e.conf, e: e.id });
        adj[e.b].push({ v: e.a, c: e.conf, e: e.id });
      }
    });
    if (!adj[a] || !adj[b]) return null;

    const best: Record<string, number> = { [a]: Infinity };
    const prev: Record<string, string> = {};
    const prevE: Record<string, string> = {};
    const done = new Set<string>();

    while (true) {
      let cur: string | null = null, cc = -1;
      for (const k in best) {
        if (!done.has(k) && best[k] > cc) { cc = best[k]; cur = k; }
      }
      if (cur === null || cur === b) break;
      done.add(cur);
      for (const { v: w, c, e } of adj[cur]) {
        const m = Math.min(cc === -1 ? c : best[cur], c);
        if (best[w] === undefined || m > best[w]) {
          best[w] = m;
          prev[w] = cur;
          prevE[w] = e;
        }
      }
    }
    if (best[b] === undefined) return null;
    const nodesP = [b], edgesP: string[] = [];
    let v = b;
    while (v !== a) {
      edgesP.unshift(prevE[v]);
      v = prev[v];
      nodesP.unshift(v);
    }
    return { nodes: nodesP, edges: edgesP, minConf: best[b] === Infinity ? 100 : best[b] };
  },

  /* Predict hidden collaborator relationships using 7-feature explainability model */
  predictHiddenLinks(
    nodes: ModelNode[],
    edges: ModelEdge[],
    analysis?: IntelAnalysis | null,
    minThreshold = 0.35
  ): InferredHiddenLink[] {
    const nodeMap = new Map(nodes.map(n => [n.id, n]));
    const ids = nodes.map(n => n.id);
    const existingEdges = new Set<string>();

    edges.forEach(e => {
      if (!e.is_hidden && e.type !== 'hidden_link') {
        existingEdges.add(`${e.a}::${e.b}`);
        existingEdges.add(`${e.b}::${e.a}`);
      }
    });

    const adj: Record<string, Set<string>> = {};
    ids.forEach(id => { adj[id] = new Set(); });
    edges.forEach(e => {
      if (!e.is_hidden && e.type !== 'hidden_link') {
        if (adj[e.a]) adj[e.a].add(e.b);
        if (adj[e.b]) adj[e.b].add(e.a);
      }
    });

    const deg: Record<string, number> = {};
    ids.forEach(id => { deg[id] = adj[id] ? adj[id].size : 0; });

    const commOf = analysis?.commOf || {};
    const bridgeScores = analysis?.bridgeScores || {};

    const inferred: InferredHiddenLink[] = [];

    // Evaluate all non-adjacent canonical pairs (u < v) to guarantee zero duplicates & zero self-links
    for (let i = 0; i < ids.length; i++) {
      const u = ids[i];
      const nodeU = nodeMap.get(u);
      if (!nodeU) continue;

      for (let j = i + 1; j < ids.length; j++) {
        const v = ids[j];
        const nodeV = nodeMap.get(v);
        if (!nodeV) continue;

        // Skip if directly connected by evidence
        if (existingEdges.has(`${u}::${v}`)) continue;

        // 1. Common Neighbors
        const neighborsU = adj[u];
        const neighborsV = adj[v];
        let common = 0;
        let adamicAdar = 0;
        neighborsU.forEach(w => {
          if (neighborsV.has(w)) {
            common++;
            const dw = deg[w] || 1;
            if (dw > 1) adamicAdar += 1 / Math.log(dw);
          }
        });

        // 2. Jaccard similarity
        const unionSize = neighborsU.size + neighborsV.size - common;
        const jaccard = unionSize > 0 ? common / unionSize : 0;

        // 3. Cross-cluster bridge detection
        const commU = commOf[u];
        const commV = commOf[v];
        const isCrossCluster = commU !== undefined && commV !== undefined && commU !== commV;
        const bridgeFactor = ((bridgeScores[u] || 0) + (bridgeScores[v] || 0)) * 0.5;

        // 4. Semantic & entity kind heuristics (e.g. Device to Account, Person to Account)
        let semanticBoost = 0;
        if ((nodeU.kind === 'DEVICE' && nodeV.kind === 'ACCOUNT') || (nodeU.kind === 'ACCOUNT' && nodeV.kind === 'DEVICE')) semanticBoost += 0.25;
        if ((nodeU.kind === 'PERSON' && nodeV.kind === 'ACCOUNT') || (nodeU.kind === 'ACCOUNT' && nodeV.kind === 'PERSON')) semanticBoost += 0.20;
        if ((nodeU.kind === 'PHONE' && nodeV.kind === 'DEVICE') || (nodeU.kind === 'DEVICE' && nodeV.kind === 'PHONE')) semanticBoost += 0.20;

        // 5. Multi-signal scoring (calibrated logistic combiner formula)
        const cnScore = Math.min(1.0, common * 0.35);
        const aaScore = Math.min(1.0, adamicAdar * 0.45);
        const jaccardScore = Math.min(1.0, jaccard * 1.5);
        const bridgeScoreComponent = isCrossCluster ? (0.20 + bridgeFactor * 0.40) : 0;

        const rawScore =
          cnScore * 0.28 +
          aaScore * 0.22 +
          jaccardScore * 0.18 +
          bridgeScoreComponent * 0.20 +
          semanticBoost * 0.12;

        if (rawScore >= minThreshold) {
          const confidence = Math.min(96, Math.max(45, Math.round(rawScore * 100)));
          const reasons: HiddenLinkReason[] = [];

          if (common > 0) {
            reasons.push({
              type: "STRUCTURAL_SIMILARITY",
              title: "Shared Intermediary Nodes",
              description: `${common} common network neighbor${common > 1 ? 's' : ''} connecting both entities`,
              contribution: common >= 2 ? "STRONG" : "MEDIUM",
              score: cnScore
            });
          }

          if (isCrossCluster && bridgeFactor > 0.15) {
            reasons.push({
              type: "CROSS_CLUSTER_BRIDGE",
              title: "Inter-Community Bridge Candidate",
              description: `Traverses boundaries between Community #${commU} and Community #${commV}`,
              contribution: "STRONG",
              score: bridgeFactor
            });
          }

          if (semanticBoost > 0) {
            reasons.push({
              type: "SHARED_DEVICE",
              title: "Hardware / Identity Affinity",
              description: `${nodeU.kind} to ${nodeV.kind} operational coordination pattern`,
              contribution: "MEDIUM",
              score: semanticBoost
            });
          }

          inferred.push({
            id: `hid-inf-${u}-${v}`,
            sourceId: u,
            targetId: v,
            sourceName: nodeU.name,
            targetName: nodeV.name,
            sourceKind: nodeU.kind,
            targetKind: nodeV.kind,
            confidence,
            score: Math.round(rawScore * 1000) / 1000,
            threshold: minThreshold,
            crossCluster: isCrossCluster,
            sourceCommunity: commU,
            targetCommunity: commV,
            reasons,
            // This is a client-side structural heuristic over the real graph.
            // It must NOT fabricate evidence references — real evidence
            // provenance comes from the backend inferred relationships.
            supportingEvidenceIds: [],
            inferenceMethod: "Client-side structural link heuristic (not evidence-backed)",
            status: "candidate"
          });
        }
      }
    }

    return inferred.sort((a, b) => b.score - a.score);
  }
};

/* ── 2.5D SPATIAL INTELLIGENCE & DEPTH ENGINE ── */
export interface DepthState {
  z: number;              // -180 (deep background) to +180 (foreground focal)
  depthScale: number;     // 0.72 to 1.25
  depthOpacity: number;   // 0.28 to 0.98
  parallaxFactor: number; // 0.65 to 1.35
}

export interface SpatialPosition {
  baseX: number;
  baseY: number;
  baseZ: number;
  depth: DepthState;
  driftAmplitude: number;
  driftSpeed: number;
  driftPhase: number;
}

/* compute deterministic base layout with cluster-aware negative space */
export function computeBasePositions(
  nodes: Array<{ id: string; risk?: string; bridgeScore?: number }>,
  edges: Array<{ a: string; b: string }>
): Record<string, { x: number; y: number }> {
  const anchors = computeSpatialAnchors(nodes, edges);
  const pos: Record<string, { x: number; y: number }> = {};
  Object.keys(anchors).forEach(id => {
    pos[id] = { x: anchors[id].baseX, y: anchors[id].baseY };
  });
  return pos;
}

export function computeSpatialAnchors(
  nodes: Array<{ id: string; risk?: string; bridgeScore?: number }>,
  edges: Array<{ a: string; b: string }>
): Record<string, SpatialPosition> {
  const N = nodes.map((e, idx) => ({
    id: e.id,
    risk: e.risk,
    bridgeScore: e.bridgeScore || 0,
    x: 0,
    y: 0,
    vx: 0,
    vy: 0,
    deg: 0,
    seed: seedOf(e.id) + idx,
  }));
  const idxMap = new Map(N.map((n, i) => [n.id, i]));
  const L: [number, number][] = [];
  edges.forEach(cn => {
    const a = idxMap.get(cn.a), b = idxMap.get(cn.b);
    if (a === undefined || b === undefined) return;
    L.push([a, b]);
    N[a].deg++;
    N[b].deg++;
  });

  const rnd = mulberry32(0x0e42 + N.length);
  N.forEach(n => {
    n.x = 80 + rnd() * 920;
    n.y = 70 + rnd() * 660;
  });

  // Generous negative space physics: higher repulsion (CS = 3800), natural spring length (L0 = 135)
  const CS = 3800, L0 = 135, K = 0.014;
  for (let it = 0; it < 320; it++) {
    const a = Math.max(0, 1 - it / 300);
    for (let i = 0; i < N.length; i++) {
      for (let j = i + 1; j < N.length; j++) {
        const dx = N[j].x - N[i].x, dy = N[j].y - N[i].y;
        const d2 = Math.max(1, dx * dx + dy * dy);
        const d = Math.sqrt(d2);
        const f = (CS / d2) * a;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        N[i].vx -= fx; N[i].vy -= fy;
        N[j].vx += fx; N[j].vy += fy;
      }
    }
    for (const [a1, b1] of L) {
      const dx = N[b1].x - N[a1].x, dy = N[b1].y - N[a1].y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - L0) * K * a;
      N[a1].vx += (dx / d) * f; N[a1].vy += (dy / d) * f;
      N[b1].vx -= (dx / d) * f; N[b1].vy -= (dy / d) * f;
    }
    N.forEach(n => {
      n.vx += (520 - n.x) * 0.0010 * a;
      n.vy += (380 - n.y) * 0.0010 * a;
      n.vx *= 0.82;
      n.vy *= 0.82;
      n.x += n.vx;
      n.y += n.vy;
    });
  }

  const result: Record<string, SpatialPosition> = {};
  N.forEach(n => {
    const nodeRnd = mulberry32(n.seed);
    // 2.5D Z depth calculation:
    // Core high-degree nodes, high-bridge nodes, or high-risk entities anchor closer to foreground
    let baseZ = 0;
    if (n.bridgeScore > 0.4 || n.risk === 'HIGH' || n.risk === 'CRITICAL') {
      baseZ = 60 + nodeRnd() * 80; // Foreground anchor
    } else if (n.deg >= 3) {
      baseZ = 20 + nodeRnd() * 50; // Mid-foreground
    } else if (n.deg === 1) {
      baseZ = -110 + nodeRnd() * 40; // Deep background
    } else {
      baseZ = -40 + nodeRnd() * 60; // Midground
    }

    const depthScale = Math.min(1.22, Math.max(0.72, 0.90 + (baseZ / 180) * 0.28));
    const depthOpacity = Math.min(0.98, Math.max(0.28, 0.65 + (baseZ / 180) * 0.32));
    const parallaxFactor = Math.min(1.35, Math.max(0.65, 1.0 + (baseZ / 180) * 0.32));

    result[n.id] = {
      baseX: Math.round(n.x),
      baseY: Math.round(n.y),
      baseZ,
      depth: {
        z: baseZ,
        depthScale,
        depthOpacity,
        parallaxFactor,
      },
      // Subtle deterministic drift parameters
      driftAmplitude: 2.5 + nodeRnd() * 3.5, // 2.5px to 6px
      driftSpeed: 0.0003 + nodeRnd() * 0.0005, // Smooth 15-25s cycle
      driftPhase: nodeRnd() * Math.PI * 2,
    };
  });

  return result;
}

/* trace path generator */
export function tracePathFor(eid: string, edges: ModelEdge[]): Array<{ from: string; to: string; connection: ModelEdge }> | null {
  const backed = edges.filter(c => c.type || c.conf >= 80).sort((x, y) => y.conf - x.conf);
  const adj = new Map<string, ModelEdge[]>();
  backed.forEach(c => {
    adj.set(c.a, [...(adj.get(c.a) || []), c]);
    adj.set(c.b, [...(adj.get(c.b) || []), c]);
  });
  const hops: Array<{ from: string; to: string; connection: ModelEdge }> = [];
  const visited = new Set([eid]);
  let frontier = [eid];
  while (frontier.length && hops.length < 3) {
    let advanced = false;
    for (const node of frontier) {
      for (const c of (adj.get(node) || [])) {
        const other = c.a === node ? c.b : c.a;
        if (visited.has(other)) continue;
        visited.add(other);
        hops.push({ connection: c, from: node, to: other });
        advanced = true;
        break;
      }
      if (advanced) break;
    }
    if (!advanced) break;
    frontier = hops.slice(-1).map(h => h.to);
  }
  return hops.length ? hops : null;
}
