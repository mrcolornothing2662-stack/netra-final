# 📋 NETRA 5.0 Hardening — Items Requiring Human Decision & Verification
**Document Version:** 1.0.0  
**Target:** Smart India Hackathon Police & Security Evaluation Panel  
**Rule:** No fabricated claims, metrics, or citations. Every unverified item is recorded here.

---

## 1. Statutory & Legal Citations Requiring Formal Legal Review

| Item | Current Citation in Code/Docs | Proposed Statutory Mapping | Human Decision / Verification Required | Status |
|---|---|---|---|---|
| **F03 Syndicate Radar** | Section 94 BNSS ("Cross-Case Privacy Protection") | Summons to produce document or thing (Power to summon bank/telecom records across jurisdictions). | Confirm wording for F03. BNSS s.94 gives IO power to summon; it does NOT codify a "privacy protection" mechanism. The privacy protection is technical (keyed blind index). | `TODO(VERIFY)` |
| **F08 What-If Freeze Simulator** | Section 106 BNSS ("Attachment of Proceeds") | Section 107 BNSS (Attachment/forfeiture of property derived from crime) + Section 106(3) BNSS (Reporting seizure to Magistrate). | Confirm Section 107 vs Section 106 for bank account freezing under BNSS 2023. | `TODO(VERIFY)` |
| **F05 Confidence Meter** | "Proof beyond reasonable doubt" | Common law judicial standard (Indian Evidence Act / BSA precedent). | Removed from statutory groundings. Confirm evidentiary strength terminology approved by police reviewers. | `TODO(VERIFY)` |
| **F02 Defence Bot** | Section 105 BNSS & Section 63 BSA | Audio-video recording of search & seizure (s.105 BNSS) and electronic record certificate (s.63 BSA). | Verify standard defense counsel cross-examination templates and objection clauses with an active Public Prosecutor. | `TODO(VERIFY)` |
| **Section 63 BSA Certificate Schedule** | Generic single-page certificate | Two-part certificate pursuant to Schedule to BSA, 2023 (Part A: Producer of Record; Part B: Expert). | Review official Gazette Schedule text to verify exact statutory declaration phrasing. | `TODO(VERIFY)` |

---

## 2. Security & Operational Architecture Decisions

| Area | Decision Required | Trade-offs & Options | Status |
|---|---|---|---|
| **First Admin Credential Bootstrapping** | Method to create the initial admin account. | **Option A (Recommended):** CLI command `python -m backend.cli bootstrap-admin` generating a random high-entropy passphrase printed to terminal.<br>**Option B:** Environment variables (`INITIAL_ADMIN_USERNAME`, `INITIAL_ADMIN_PASSWORD`).<br>*Both force password change on first login and hash via Argon2id.* | `TODO(VERIFY)` |
| **MFA Delivery Channel for IOs** | Mechanism for TOTP MFA. | **Option A (Recommended):** Standard RFC 6238 app-based TOTP (Google Authenticator, Aegis, YubiKey) — works 100% on-prem and air-gapped.<br>**Option B:** SMS/Email OTP (introduces external gateway dependency and cellular vulnerability). | `TODO(VERIFY)` |
| **Per-Case Access Control & Admin Role** | Case isolation vs Admin troubleshooting. | Should Admin have read-access to case evidence, or should Admin strictly manage users/infrastructure with zero case read permissions unless explicitly granted by IO/SP? | `TODO(VERIFY)` |
| **Supervisor Approval for Dossier Export** | Role hierarchy for Section 63 Dossier sign-off. | Which role acts as "Supervisor"? (`sp`, `dsp`, `inspector`, or designated `approver`). | `TODO(VERIFY)` |
| **File Vault Key Provider** | Key management for envelope encryption at rest. | Development will use an environment master key (`VAULT_MASTER_KEY`). For production on-prem, which key provider interface should be prioritized (Local File Vault with OS keyring, HashiCorp Vault, or PKCS#11 HSM)? | `TODO(VERIFY)` |

---

## 3. Machine Learning & Model Transparency

| Model / Feature | Current Claim in Marketing Docs | Reality in Code | Action / Decision Required | Status |
|---|---|---|---|---|
| **CyberDrishtiLM** | "Proprietary CyberDrishtiLM" (implied LLM). | Custom ~2.3M parameter dual-head mini-transformer encoder for token classification (NER) and binary fraud classification. Generative text uses Ollama or Gemini. | Documentation must state plainly that CyberDrishtiLM is a 2.3M-param BERT-style encoder for NER, not an LLM. | `TODO(VERIFY)` |
| **HingBERT Fine-Tune** | Fine-tuned transformer for Hinglish cyber fraud. | Needs verification of training data provenance and weights location in `artifacts/hingbert`. | Verify whether model weights are committed or downloaded at setup. | `TODO(VERIFY)` |
| **Hidden Link Model (Phase 7 Gate)** | "≥ 90% Precision Guarantee". | Currently hardcoded in `hidden_link_engine.py` as default `0.5` with `MIN_PRECISION = 0.90` logic. Needs real saved validation report from synthetic benchmark. | Run benchmark in Phase 7 to generate genuine `latest.json` and gate inference strictly on that file. | `TODO(VERIFY)` |

---

## 4. Operational Comparison Section (Placeholder for User)

*Note: As requested by the user, this section is reserved for the user to complete with agency-specific nuances.*

```markdown
### Comparison with Existing Investigative Tools
- **IBM i2 Analyst's Notebook:** [TODO(USER_INPUT): Detail comparison on multi-modal ingestion and BSA S.63 compliance]
- **Maltego:** [TODO(USER_INPUT): Detail comparison on OSINT vs closed-case evidence graph]
- **I4C National Platforms (NCRP, CFCFRMS):** [TODO(USER_INPUT): Detail integration boundary and nodal officer workflow complement]
```
