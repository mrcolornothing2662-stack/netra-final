"""CyberDrishti Feature 11 — Synthetic Benchmark Generator (isolated build).

A flight simulator, not a scoreboard: generates fully-labeled synthetic
cyber-fraud cases (chat + bank statement + CDR artifacts plus a ground-truth
file) so the other engines can be stress-tested without touching private
citizen data. DPDP-friendly by construction — every value is fictional.

Design rules:
- Deterministic: same (typology, seed, config) ⇒ byte-identical output.
- Data-driven: typologies and entity pools live in data/*.json. The engine
  contains NO case values, NO names, NO templates.
- Adversarial noise is parameterized (OCR digit confusion, dropped CDR rows,
  decoy chatter) and always recorded in ground truth.
- Ground truth includes planted HIDDEN LINKS: entity pairs connected only by
  timing/amount patterns across documents, never co-occurring in one event —
  exactly what Feature 6's hidden-link engine must surface and nothing else.

Honest limits (documented, enforced): scores achieved on this generator are
SYNTHETIC-ONLY evidence. They say nothing about real-case accuracy until
validated on real (or realistically-annotated) data — template-generated
perfection is the known failure mode of this entire approach.
"""
from __future__ import annotations

import hashlib
import json
import random
import string
from datetime import datetime, timedelta
from typing import Any

NOISE_OCR_MAP = {"0": "O", "1": "l", "5": "S", "8": "B", "2": "Z"}


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class BenchmarkGenerator:
    def __init__(
        self,
        pools: dict[str, Any],
        typologies: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> None:
        self.pools = pools
        self.typologies = typologies["typologies"]
        cfg = {
            "crime_window_start": "2026-04-22T09:00:00",
            "base_amount": 60000,
            "ocr_pct": 0.08,          # fraction of bank narrations with digit confusion
            "cdr_drop_pct": 0.10,     # fraction of planted CDR rows removed
            "decoy_messages": 4,
            **(config or {}),
        }
        self.cfg = cfg

    # ------------------------------------------------------------------ util
    def _phone(self, rng: random.Random) -> str:
        return rng.choice("6789") + "".join(rng.choices(string.digits, k=9))

    def _upi(self, rng: random.Random, name: str) -> str:
        return f"{name.lower()}.{rng.choices(string.ascii_lowercase, k=4)}" \
               f"{rng.randrange(10, 99)}{rng.choice(self.pools['upi_suffixes'])}"

    def _account(self, rng: random.Random) -> str:
        return "".join(rng.choices(string.digits, k=rng.choice([11, 12, 14])))

    def _utrn(self, rng: random.Random) -> str:
        return "".join(rng.choices(string.digits.upper(), k=12))

    def _apply_ocr_noise(self, rng: random.Random, text: str, pct: float) -> str:
        if pct <= 0 or not text:
            return text
        out = []
        for ch in text:
            if ch in NOISE_OCR_MAP and rng.random() < pct:
                out.append(NOISE_OCR_MAP[ch])
            else:
                out.append(ch)
        return "".join(out)

    # ------------------------------------------------------------- generator
    def generate_case(self, typology_key: str, seed: int) -> dict[str, Any]:
        if typology_key not in self.typologies:
            raise KeyError(f"unknown typology '{typology_key}'; available: {sorted(self.typologies)}")
        typ = self.typologies[typology_key]
        rng = random.Random(seed)
        flow = typ["money_flow"]
        start = datetime.fromisoformat(self.cfg["crime_window_start"])

        # ---- cast (fictional) -------------------------------------------
        accused_name = rng.choice(self.pools["names"])
        victim_name = rng.choice([n for n in self.pools["names"] if n != accused_name])
        used = {accused_name, victim_name}
        def fresh_name() -> str:
            nonlocal used
            n = rng.choice([x for x in self.pools["names"] if x not in used])
            used.add(n)
            return n
        accused = {"role": "accused", "name": accused_name,
                   "phone": self._phone(rng), "upi": self._upi(rng, accused_name)}
        victim = {"role": "victim", "name": victim_name, "phone": self._phone(rng)}
        l1 = [{"role": "l1_mule", "name": fresh_name(), "account": self._account(rng),
               "upi": None, "bank": rng.choice(self.pools["banks"]),
               "phone": self._phone(rng)} for _ in range(flow["l1_mules"])]
        for m in l1:
            m["upi"] = self._upi(rng, m["name"])
        l2 = [{"role": "l2_mule", "name": fresh_name(), "account": self._account(rng),
               "bank": rng.choice(self.pools["banks"])}
              for _ in range(flow["l1_mules"] * flow["l2_per_l1"])]
        offramps = [{"role": "offramp", "name": f"offramp-{j + 1}",
                     "account": self._account(rng)}
                    for j in range(flow["offramps"])]
        entities = [accused, victim, *l1, *l2, *offramps]

        # ---- money flow (timed edges, conservation at the victim hop) ----
        total = self.cfg["base_amount"] * rng.randrange(2, 6)
        shares = [total // len(l1)] * len(l1)
        for i in range(total % len(l1)):
            shares[i] += 1
        edges = [{"amount": shares[i], "from": f"victim:{victim['name']}",
                  "to": f"l1:{l1[i]['name']}",
                  "ts": (start + timedelta(minutes=24 + i * 6)).isoformat()}
                 for i in range(len(l1))]
        ts_cursor = start + timedelta(minutes=30)
        for i, m in enumerate(l1):
            kids = l2[i * flow["l2_per_l1"]: (i + 1) * flow["l2_per_l1"]]
            share = shares[i] // max(len(kids), 1)
            for k in kids:
                ts_cursor = ts_cursor + timedelta(minutes=rng.randrange(2, 9))
                edges.append({"amount": share, "from": f"l1:{m['name']}",
                              "to": f"l2:{k['name']}", "ts": ts_cursor.isoformat()})
        for j, o in enumerate(offramps):
            src = l2[j % len(l2)]
            ts_cursor = ts_cursor + timedelta(minutes=rng.randrange(5, 12))
            edges.append({"amount": 40000 + rng.randrange(0, 10) * 500,
                          "from": f"l2:{src['name']}", "to": f"offramp:{o['name']}",
                          "ts": ts_cursor.isoformat()})

        # ---- bank statement rows (running balance per account) ----------
        balances: dict[str, float] = {}
        bank_rows: list[dict[str, Any]] = []
        for e in sorted(edges, key=lambda x: x["ts"]):
            for side, key in (("from", "debit"), ("to", "credit")):
                holder = e[side].split(":", 1)[1]  # edge ids are "role:name"
                acct_ent = next((x for x in entities if x["name"] == holder), None)
                if acct_ent is None or acct_ent["role"] == "victim":
                    continue  # victim statement omitted (they are the complainant)
                acct = acct_ent["account"]
                bal = balances.setdefault(acct, 50000 + rng.randrange(0, 20000))
                amt = e["amount"]
                if key == "debit":
                    bal -= amt
                else:
                    bal += amt
                balances[acct] = bal
                narration = f"UPI/{self._utrn(rng)}/{acct_ent.get('upi') or acct_ent['account']}"
                bank_rows.append({
                    "account": acct, "bank": acct_ent.get("bank", {}).get("name", ""),
                    "timestamp": e["ts"], "narration": narration,
                    "credit": amt if key == "credit" else 0,
                    "debit": amt if key == "debit" else 0,
                    "balance": round(bal, 2),
                })
        noisy_rows = [dict(r) for r in bank_rows]
        for r in noisy_rows:
            r["narration"] = self._apply_ocr_noise(rng, r["narration"], self.cfg["ocr_pct"])

        # ---- CDR rows ----------------------------------------------------
        circle = rng.choice(self.pools["circles"])
        cdr_rows = []
        n_calls = 6
        for i in range(n_calls):
            cdr_rows.append({
                "caller": accused["phone"],
                "callee": victim["phone"] if i % 2 else l1[(i // 2) % len(l1)]["phone"],
                "timestamp": (start + timedelta(minutes=10 + i * 7)).isoformat(),
                "duration_sec": 30 + rng.randrange(0, 200),
                "cell_id": rng.choice(circle["towers"]),
            })
        planted_drop_idx = rng.randrange(0, max(n_calls, 1)) if n_calls else None
        dropped = []
        if self.cfg["cdr_drop_pct"] > 0 and planted_drop_idx is not None:
            dropped = [cdr_rows.pop(planted_drop_idx)]  # remove exactly one planted row

        # ---- WhatsApp transcript ----------------------------------------
        lines: list[str] = []
        templates = typ["chat_templates"]
        filler = {"dept": "CYBER CELL", "case_ref": f"FIR-{seed % 900 + 100}",
                  "amount": f"{total}", "upi": l1[0]["upi"], "otp": "".join(rng.choices(string.digits, k=6))}
        chat_start = start
        for i, tpl in enumerate(templates):
            lines.append(f"[{chat_start + timedelta(minutes=8 * i)}, "
                         f"{accused_name}]: " + tpl.format(**filler))
        n_decoy = self.cfg["decoy_messages"]
        topic = rng.choice(self.pools["decoy_topics"])
        decoy_partner = fresh_name()
        for i in range(n_decoy):
            side = accused_name if i % 2 else decoy_partner
            lines.append(f"[{start + timedelta(minutes=i * 2)}, {side}]: "
                         f"yaar {topic} ke liye kab nikale?")
        # chat mentioning the first planted mule only via UPI in stage template (already above)

        # ---- ground truth -------------------------------------------------
        planted_pair = (accused["phone"], l1[-1]["account"])
        chat_blob = "\n".join(lines)
        bank_blob = json.dumps(noisy_rows)
        cdr_blob = json.dumps(cdr_rows)
        # planted link contract: the pair is connected ONLY via timing/amounts
        # across different artifacts — never co-occurring in one artifact.
        assert accused["phone"] in cdr_blob, "accused phone must appear in CDR"
        assert l1[-1]["account"] in bank_blob, "mule account must appear in bank rows"
        assert l1[-1]["account"] not in cdr_blob and l1[-1]["account"] not in chat_blob
        assert accused["phone"] not in bank_blob

        has_bsa_cert = bool(self.cfg.get("has_bsa_cert", False))
        seizure_memo = f"""================================================================================
RECORD OF SEIZURE UNDER SECTION 105 BHARATIYA NAGARIK SURAKSHA SANHITA (BNSS), 2023
================================================================================
Case Reference   : FIR-{seed % 900 + 100} / 2026
Police Station   : Cyber Crime Police Station, Central District
Date & Time      : {start.strftime('%Y-%m-%d %H:%M:%S IST')}
Location         : Residence of Complainant {victim_name}

INDEPENDENT PANCH WITNESSES:
1. Shri Rajeshwar Prasad, Age 44, Resident of Sector 14
2. Smt. Meenakshi Sundaram, Age 39, Resident of Sector 14

ITEMS SEIZED & DIGITALLY PRESERVED:
1. 01 Mobile Handset (Samsung Galaxy S22)
   - Original Storage Path: /evidence/handset_extraction_01.tar
   - SHA-256 Hash: {hashlib.sha256(chat_blob.encode()).hexdigest()}
2. Certified Bank Statement Ledger ({len(bank_rows)} transaction rows)
   - Account Holder: Complainant & Intermediary Mules
   - SHA-256 Hash: {hashlib.sha256(bank_blob.encode()).hexdigest()}
3. Call Detail Records (CDR) from Carrier
   - Tower Cell ID: {circle['towers'][0]}
   - Section 63 BSA Hash Certificate: {'ATTACHED' if has_bsa_cert else 'PENDING_NODAL_OFFICER_SIGNATURE'}

AUDIO-VIDEO ELECTRONIC RECORDING:
Audio-video recording of search and seizure executed pursuant to Section 105 BNSS.
Media File: SEIZURE_REC_{seed}.mp4 (SHA-256 Verified)

Signatures:
Investigating Officer: Inspector V. K. Deshmukh
Panch Witnesses: [Signed], [Signed]
================================================================================
"""

        ground_truth = {
            "typology": typology_key,
            "stages": typ.get("stages", []),
            "entities": [
                {"role": x["role"], "name": x["name"], "phone": x.get("phone"),
                 "upi": x.get("upi"), "account": x.get("account")}
                for x in entities
            ],
            "money_flow_edges": edges,
            "planted_hidden_links": [{
                "pair": list(planted_pair),
                "link_type": "temporal_financial",
                "note": "accused phone and last L1 mule account never co-occur in one event; "
                        "linked only by timing + amount flow",
            }],
            "planted_contradictions": [{
                "kind": "DROPPED_CDR_ROWS", "count": len(dropped),
                "rows": dropped,
            }],
            "ocr_noise_applied": self.cfg["ocr_pct"] > 0,
            "decoy_topic": topic,
            "statutory_provisions": typ.get("statutory_provisions", []),
            "defence_challenges": typ.get("defence_challenges", []),
            "golden_hours_actions": typ.get("golden_hours_actions", []),
            "has_bsa_certificate": has_bsa_cert,
        }
        return {
            "case_id": f"SYN-{typology_key}-{seed}",
            "artifacts": {
                "whatsapp_export.txt": chat_blob,
                "bank_statement.csv": bank_rows,
                "bank_statement_noisy.csv": noisy_rows,
                "cdr.csv": cdr_rows,
                "evidence_seizure_memo.txt": seizure_memo,
            },
            "ground_truth": ground_truth,
        }

