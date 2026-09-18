"""
CyberDrishti AI — Hidden-Link Graph Builder
Constructs a NetworkX graph from extracted entities + evidence events.
Handles fuzzy canonical merging (Levenshtein ≥ 0.85), exact hard-ID override,
and Union-Find transitive merging.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from rapidfuzz.distance import Levenshtein
from rapidfuzz import fuzz


# ── Merge threshold ───────────────────────────────────────────────────────────
FUZZY_THRESHOLD = 0.85

# ── Hard-identifier types (exact match only — regex is source of truth) ───────
HARD_ID_TYPES = {"PHONE", "UPI", "ACCOUNT", "EMAIL", "IFSC", "IP"}


# ── Union-Find ────────────────────────────────────────────────────────────────

class UnionFind:
    def __init__(self):
        self._parent: dict[str, str] = {}
        self._rank:   dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x]   = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])  # path compression
        return self._parent[x]

    def union(self, x: str, y: str):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for x in self._parent:
            root = self.find(x)
            groups.setdefault(root, []).append(x)
        return groups


# ── Canonicalisation ──────────────────────────────────────────────────────────

def _similarity(a: str, b: str, entity_type: str) -> float:
    """
    Compute similarity between two entity values.
    Hard-ID types: require exact match (similarity = 1.0 or 0.0).
    PER / LOCATION / BANK: Levenshtein-based normalised similarity.
    """
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return 1.0
    if entity_type in HARD_ID_TYPES:
        return 0.0
    # Token-set ratio for name/location matching (handles re-ordering)
    score = fuzz.token_set_ratio(a, b) / 100.0
    return score


def canonicalise_entities(
    raw_mentions: list[dict],
) -> dict[str, list[dict]]:
    """
    Given a list of raw entity mention dicts:
        {raw_value, entity_type, ...}
    Return a mapping {canonical_key → [list of raw mentions]}.

    Merging rules (in priority order):
    1. Exact match on normalised value → same canonical key.
    2. Hard-ID types (PHONE/UPI/ACCOUNT etc.): no fuzzy merging.
    3. Non-hard types with Levenshtein/token-set similarity ≥ FUZZY_THRESHOLD → same cluster.
    4. Union-Find for transitive closure (A~B, B~C → A~B~C).
    """
    uf  = UnionFind()
    ids = [m["raw_value"].strip().lower() for m in raw_mentions]

    for i in range(len(ids)):
        uf.find(ids[i])  # register all

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            etype_i = raw_mentions[i]["entity_type"]
            etype_j = raw_mentions[j]["entity_type"]
            if etype_i != etype_j:
                continue
            sim = _similarity(ids[i], ids[j], etype_i)
            if sim >= FUZZY_THRESHOLD:
                uf.union(ids[i], ids[j])

    groups = uf.groups()
    # canonical key = the most frequently seen value in the cluster
    result: dict[str, list[dict]] = {}
    for root, members in groups.items():
        member_set = set(members)
        # Choose canonical = most common raw_value in cluster
        freq: dict[str, int] = {}
        for m in raw_mentions:
            key = m["raw_value"].strip().lower()
            if key in member_set:
                freq[key] = freq.get(key, 0) + 1
        canonical = max(freq, key=freq.get)
        for m in raw_mentions:
            key = m["raw_value"].strip().lower()
            if key in member_set:
                result.setdefault(canonical, []).append(m)

    return result


# ── Graph Builder ─────────────────────────────────────────────────────────────

def build_case_graph(
    entities: list[dict],
    events:   list[dict],
) -> nx.Graph:
    """
    Build a NetworkX undirected graph for a case.

    Node attributes: entity_type, canonical_value, mention_count,
                     first_seen, last_seen, timestamps (list)
    Edge attributes: edge_type (co_occurrence / transaction / call),
                     weight (co-occurrence count),
                     timestamps (list of ISO strings)

    Args:
        entities: list of entity dicts {id, canonical_value, entity_type, ...}
    """
    G = nx.Graph()
    # Add nodes & build case-insensitive lookup
    node_lookup: dict[str, str] = {}
    for e in entities:
        cval = e["canonical_value"]
        G.add_node(
            cval,
            entity_type=e["entity_type"],
            canonical_value=cval,
            db_id=str(e.get("id", "")),
            mention_count=0,
            community_id=None,
            bridge_score=0.0,
            timestamps=[],
        )
        node_lookup[cval.lower()] = cval

    # Add edges from co-occurrence within events
    for event in events:
        raw_mentions = event.get("entity_mentions", [])
        # One event can repeat an entity many times; it must not inflate the
        # graph or create duplicate pair work.
        seen_mentions: set[tuple[str, str]] = set()
        mentions = []
        for mention in raw_mentions:
            value = str(mention.get("canonical_value") or "").strip()
            entity_type = str(mention.get("entity_type") or "UNKNOWN")
            key = (entity_type, value.lower())
            if value and key not in seen_mentions:
                seen_mentions.add(key)
                mentions.append(mention)
        ts = event.get("event_timestamp")
        evtype = event.get("event_type", "co_occurrence")

        # Ensure all mention entities exist in G
        for m in mentions:
            raw_cval = m.get("canonical_value")
            if not raw_cval:
                continue
            lower_cval = raw_cval.lower()
            if lower_cval not in node_lookup:
                G.add_node(
                    raw_cval,
                    entity_type=m.get("entity_type", "UNKNOWN"),
                    canonical_value=raw_cval,
                    db_id="",
                    mention_count=0,
                    community_id=None,
                    bridge_score=0.0,
                    timestamps=[],
                )
                node_lookup[lower_cval] = raw_cval

        if len(mentions) < 2:
            continue

        for i in range(len(mentions)):
            for j in range(i + 1, len(mentions)):
                raw_a = mentions[i].get("canonical_value")
                raw_b = mentions[j].get("canonical_value")
                if not raw_a or not raw_b or raw_a.lower() == raw_b.lower():
                    continue

                a = node_lookup.get(raw_a.lower(), raw_a)
                b = node_lookup.get(raw_b.lower(), raw_b)

                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                    if ts:
                        G[a][b]["timestamps"].append(ts)
                else:
                    G.add_edge(a, b,
                               edge_type=evtype,
                               weight=1,
                               timestamps=[ts] if ts else [])

    # Increment mention counts
    for event in events:
        for mention in event.get("entity_mentions", []):
            canon = mention.get("canonical_value")
            ts    = event.get("event_timestamp")
            if canon and G.has_node(canon):
                G.nodes[canon]["mention_count"] += 1
                if ts:
                    G.nodes[canon]["timestamps"].append(ts)

    # Compute degree centrality
    deg_centrality = nx.degree_centrality(G)
    for node, val in deg_centrality.items():
        if G.has_node(node):
            G.nodes[node]["degree_centrality"] = val

    # Louvain community detection
    try:
        import community as community_louvain
        partition = community_louvain.best_partition(G)
        for node, comm_id in partition.items():
            if G.has_node(node):
                G.nodes[node]["community_id"] = comm_id

        # BridgeScore: fraction of a node's edges that cross community boundaries
        for node in G.nodes():
            node_comm = G.nodes[node].get("community_id")
            if node_comm is None:
                continue
            neighbors = list(G.neighbors(node))
            if not neighbors:
                G.nodes[node]["bridge_score"] = 0.0
                continue
            cross = sum(
                1 for nb in neighbors
                if G.nodes[nb].get("community_id") != node_comm
            )
            G.nodes[node]["bridge_score"] = cross / len(neighbors)

    except ImportError:
        pass  # community package not installed; skip

    return G


def graph_to_json(G: nx.Graph) -> dict:
    """Serialise graph to a JSON-compatible dict for the frontend."""
    hidden_edges_count = {}
    for a, b, attrs in G.edges(data=True):
        if attrs.get("edge_type") == "hidden_link":
            hidden_edges_count[a] = hidden_edges_count.get(a, 0) + 1
            hidden_edges_count[b] = hidden_edges_count.get(b, 0) + 1

    nodes = []
    max_score = -1.0
    prominent_id = None
    for n, attrs in G.nodes(data=True):
        score = attrs.get("degree_centrality", 0.0) + attrs.get("bridge_score", 0.0)
        if score > max_score and score > 0:
            max_score = score
            prominent_id = n

    for n, attrs in G.nodes(data=True):
        nodes.append({
            "id":               n,
            "entity_type":      attrs.get("entity_type", "UNKNOWN"),
            "label":            n,
            "mention_count":    attrs.get("mention_count", 0),
            "degree_centrality": attrs.get("degree_centrality", 0.0),
            "community_id":     attrs.get("community_id"),
            "bridge_score":     attrs.get("bridge_score", 0.0),
            "is_prominent": (n == prominent_id) if prominent_id else False
        })

    edges = []
    for a, b, attrs in G.edges(data=True):
        evidence_refs = attrs.get("evidence_refs") or []
        edges.append({
            "source":    a,
            "target":    b,
            "edge_type": attrs.get("edge_type", "co_occurrence"),
            "weight":    attrs.get("weight", 1),
            # Semantic + epistemic provenance (present when the edge is backed by
            # a persisted observed/inferred Relationship).
            "relationship_type":  attrs.get("relationship_type"),
            "epistemic_status":   attrs.get("epistemic_status", "OBSERVED"),
            "direction":          attrs.get("direction"),
            "confidence":         attrs.get("confidence"),
            "amount":             attrs.get("amount"),
            "evidence_refs":      evidence_refs,
            "event_refs":         attrs.get("event_refs") or [],
            "observation_count":  attrs.get("observation_count"),
            "has_provenance":     bool(evidence_refs),
        })

    return {"nodes": nodes, "edges": edges}


def select_relevant_subgraph(
    G: nx.Graph,
    *,
    seed_nodes: list[str] | None = None,
    selected_node: str | None = None,
    hops: int = 1,
    max_nodes: int = 75,
    max_edges: int = 200,
) -> nx.Graph:
    """Return a deterministic evidence-relevant view while preserving the full graph in storage."""
    if len(G) <= max_nodes and G.number_of_edges() <= max_edges and not selected_node:
        return G.copy()

    seeds: list[str] = []
    if selected_node and selected_node in G:
        seeds.append(selected_node)
    for node in seed_nodes or []:
        if node in G and node not in seeds:
            seeds.append(node)

    rank = sorted(
        G.nodes,
        key=lambda node: (
            G.nodes[node].get("mention_count", 0),
            G.degree(node, weight="weight"),
            G.nodes[node].get("bridge_score", 0.0),
            str(node),
        ),
        reverse=True,
    )
    if not seeds:
        seeds = rank[: min(8, max_nodes)]

    selected: set[str] = set(seeds)
    frontier = set(seeds)
    for _ in range(max(1, min(hops, 2))):
        candidates: set[str] = set()
        for node in frontier:
            candidates.update(G.neighbors(node))
        candidates -= selected
        ordered = sorted(
            candidates,
            key=lambda node: (G.degree(node, weight="weight"), G.nodes[node].get("mention_count", 0), str(node)),
            reverse=True,
        )
        room = max_nodes - len(selected)
        added = set(ordered[:room])
        selected.update(added)
        frontier = added
        if not frontier or len(selected) >= max_nodes:
            break

    subgraph = G.subgraph(selected).copy()
    if subgraph.number_of_edges() > max_edges:
        strongest = sorted(
            subgraph.edges(data=True),
            key=lambda edge: (edge[2].get("weight", 1), str(edge[0]), str(edge[1])),
            reverse=True,
        )[:max_edges]
        bounded = nx.Graph()
        bounded.add_nodes_from((node, dict(subgraph.nodes[node])) for node in selected)
        bounded.add_edges_from((a, b, dict(attrs)) for a, b, attrs in strongest)
        subgraph = bounded
    return subgraph
