import type { BackendGraphData, BackendGraphNode, BackendGraphEdge } from "../api/graph";
import type { Connection, Entity, EntityKind } from "../data/types";

export interface NodeCoord {
  id: string;
  x: number;
  y: number;
  label: string;
  kind: string;
  mentionCount?: number;
  degreeCentrality?: number;
  bridgeScore?: number;
}

function normalizeKind(entityType: string): EntityKind {
  const upper = entityType.toUpperCase();
  if (upper === "UPI") return "UPI";
  if (upper === "IFSC") return "IFSC";
  if (upper === "BANK") return "BANK";
  if (upper === "AMOUNT") return "AMOUNT";
  if (upper === "PHONE") return "PHONE";
  if (upper === "DEVICE" || upper === "IMEI" || upper === "TOWER" || upper === "CELL_TOWER") return "DEVICE";
  if (upper === "ACCOUNT") return "ACCOUNT";
  if (upper === "ORG") return "ORG";
  if (upper === "IP") return "IP";
  if (upper === "DOMAIN") return "DOMAIN";
  if (upper === "FILE") return "FILE";
  if (upper === "MALWARE") return "MALWARE";
  if (upper === "EMAIL") return "EMAIL";
  return "PERSON";
}

export function adaptGraphData(
  graph: BackendGraphData,
  svgWidth = 840,
  svgHeight = 460,
): { nodes: NodeCoord[]; connections: Connection[]; entities: Entity[] } {
  const backendNodes = graph.nodes || [];
  const normalEdges = graph.edges || [];
  const hiddenEdges = graph.hidden_edges || [];

  const cx = svgWidth / 2;
  const cy = svgHeight / 2;
  const rx = (svgWidth - 140) / 2;
  const ry = (svgHeight - 120) / 2;

  // Position nodes in concentric rings / elliptical arrangement
  const total = Math.max(1, backendNodes.length);
  const nodes: NodeCoord[] = backendNodes.map((n, i) => {
    // Top 3 highest degree centrality or prominent nodes in center
    const isProminent = i < 3 && total > 5;
    let x: number;
    let y: number;

    if (isProminent) {
      const offsetAngle = (i / 3) * 2 * Math.PI - Math.PI / 2;
      x = cx + Math.cos(offsetAngle) * 70;
      y = cy + Math.sin(offsetAngle) * 50;
    } else {
      const angle = (i / total) * 2 * Math.PI - Math.PI / 2;
      // Slight radial jitter for organic constellation
      const jitter = 0.85 + ((i % 5) * 0.06);
      x = cx + Math.cos(angle) * rx * jitter;
      y = cy + Math.sin(angle) * ry * jitter;
    }

    return {
      id: n.id,
      x: Math.round(x),
      y: Math.round(y),
      label: n.label || n.id,
      kind: n.entity_type || "PERSON",
      mentionCount: n.mention_count,
      degreeCentrality: n.degree_centrality,
      bridgeScore: n.bridge_score,
    };
  });

  const nodeSet = new Set(nodes.map(n => n.id));

  // Convert normal edges
  const connections: Connection[] = [];
  normalEdges.forEach((e, idx) => {
    if (nodeSet.has(e.source) && nodeSet.has(e.target)) {
      const relType = e.relationship_type || undefined;
      const epistemic = e.epistemic_status || "OBSERVED";
      const evidenceRefs = e.evidence_refs || [];
      const provNote = evidenceRefs.length ? ` · ${evidenceRefs.length} evidence ref(s)` : "";
      connections.push({
        id: `edge-${idx}-${e.source}-${e.target}`,
        a: e.source,
        b: e.target,
        type: relType,
        relationship_type: relType,
        epistemic_status: epistemic,
        direction: e.direction || undefined,
        evidence_refs: evidenceRefs,
        event_refs: e.event_refs || [],
        has_provenance: e.has_provenance,
        evidenceIds: evidenceRefs,
        reason: relType
          ? `${relType} · ${epistemic === "INFERRED" ? "inferred" : "observed"}${provNote}`
          : `${e.edge_type.toUpperCase()} correlation (wt: ${e.weight})${provNote}`,
        confidence: e.confidence != null
          ? e.confidence
          : Math.min(0.99, 0.65 + (e.weight * 0.05)),
      });
    }
  });

  // Convert hidden links (topological predictions)
  hiddenEdges.forEach((h, idx) => {
    if (nodeSet.has(h.source) && nodeSet.has(h.target)) {
      const scoreVal = h.score !== undefined ? h.score : 0.85;
      const srcLabel = (h as any).source_label || h.source;
      const tgtLabel = (h as any).target_label || h.target;
      const srcType = (h as any).source_type || "";
      const tgtType = (h as any).target_type || "";
      connections.push({
        id: `hidden-${idx}-${h.source}-${h.target}`,
        a: h.source,
        b: h.target,
        type: "hidden_link",
        is_hidden: true,
        score: scoreVal,
        threshold: 0.365,
        component_scores: h.component_scores || {},
        reason: `AI Hidden Link · ${srcType}:${srcLabel} ↔ ${tgtType}:${tgtLabel} (${Math.round(scoreVal * 100)}% conf)`,
        confidence: Math.round(scoreVal * 100),
      });
    }
  });

  // Convert to entities list
  const entities: Entity[] = backendNodes.map(n => ({
    id: n.id,
    name: n.label || n.id,
    kind: normalizeKind(n.entity_type),
    meta: `${n.entity_type} · ${n.mention_count || 1} mentions · Centrality ${(n.degree_centrality || 0).toFixed(2)}${n.bridge_score ? ` · Bridge ${(n.bridge_score * 100).toFixed(0)}%` : ""}`,
    risk: (n.degree_centrality > 0.3 || n.bridge_score > 0.4) ? "HIGH" : undefined,
    mentionCount: n.mention_count || 1,
    bridgeScore: n.bridge_score,
  }));

  return { nodes, connections, entities };
}
