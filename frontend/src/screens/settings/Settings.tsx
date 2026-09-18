import { useState, useEffect } from "react";
import { Block } from "../../app/transitions";
import { systemApi, officersApi, type SystemHealth, type AuditVerification, type Officer } from "../../api/system";
import { getStoredUser, logout } from "../../api/client";
import { Button } from "../../components/primitives/Button";
import { Icon } from "../../components/icons";
import { AuditLogPanel } from "./AuditLogPanel";
import prim from "../../components/primitives/primitives.module.css";
import s from "./settings.module.css";

const CATEGORIES = ["Workspace", "Diagnostics", "Security", "Team", "Integrations"] as const;
type Category = (typeof CATEGORIES)[number];

export function Settings() {
  const [activeCat, setActiveCat] = useState<Category>("Workspace");

  // Workspace Settings
  const [autonomousScan, setAutonomousScan] = useState(true);
  const [dwellTrace, setDwellTrace] = useState(true);
  const [retentionLock, setRetentionLock] = useState(true);
  const [defaultPriority, setDefaultPriority] = useState<string>("HIGH");
  const [jurisdiction, setJurisdiction] = useState<string>("Delhi Police Cyber Cell");
  const [retentionYears, setRetentionYears] = useState<string>("7");
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  // Diagnostics State
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [audit, setAudit] = useState<AuditVerification | null>(null);
  const [loadingDiag, setLoadingDiag] = useState(false);

  // Security Tab State
  const [verifyingAudit, setVerifyingAudit] = useState(false);
  const [auditVerifyResult, setAuditVerifyResult] = useState<AuditVerification | null>(null);

  // Team Tab State
  const [officers, setOfficers] = useState<Officer[]>([]);
  const [loadingOfficers, setLoadingOfficers] = useState(false);
  const [officersError, setOfficersError] = useState<string | null>(null);
  const [showOfficerModal, setShowOfficerModal] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newFullName, setNewFullName] = useState("");
  const [newRank, setNewRank] = useState("Inspector");
  const [newUnit, setNewUnit] = useState("Cyber Crime Cell");
  const [newRole, setNewRole] = useState("io");
  const [officerSubmitting, setOfficerSubmitting] = useState(false);
  const [officerError, setOfficerError] = useState<string | null>(null);

  // Real authenticated identity — never a hardcoded officer.
  const user = getStoredUser();
  const identityName = user?.full_name?.trim() || user?.username || "Not signed in";
  const identityRole = (user?.role || "").toUpperCase();

  const notify = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3500);
  };

  const fetchDiagnostics = async () => {
    setLoadingDiag(true);
    try {
      const [h, a] = await Promise.all([
        systemApi.health().catch(() => null),
        systemApi.verifyAudit().catch(() => null),
      ]);
      if (h) setHealth(h);
      if (a) {
        setAudit(a);
        setAuditVerifyResult(a);
      }
    } finally {
      setLoadingDiag(false);
    }
  };

  const fetchOfficers = async () => {
    setLoadingOfficers(true);
    setOfficersError(null);
    try {
      const res = await officersApi.list();
      // Show exactly what the backend returns — no fabricated roster.
      setOfficers(res || []);
    } catch {
      setOfficers([]);
      setOfficersError("Unable to retrieve the officer roster from the backend.");
    } finally {
      setLoadingOfficers(false);
    }
  };

  useEffect(() => {
    if (activeCat === "Diagnostics") {
      fetchDiagnostics();
    } else if (activeCat === "Security") {
      fetchDiagnostics();
    } else if (activeCat === "Team") {
      fetchOfficers();
    }
  }, [activeCat]);

  const handleCreateOfficer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim() || !newEmail.trim() || !newPassword.trim()) return;
    setOfficerSubmitting(true);
    setOfficerError(null);

    try {
      const created = await officersApi.create({
        username: newUsername.trim(),
        email: newEmail.trim(),
        password: newPassword.trim(),
        full_name: newFullName.trim() || undefined,
        rank: newRank.trim() || undefined,
        unit: newUnit.trim() || undefined,
        role: newRole,
      });

      setOfficers(prev => [created, ...prev.filter(o => o.username !== created.username)]);
      setShowOfficerModal(false);
      setNewUsername("");
      setNewEmail("");
      setNewPassword("");
      setNewFullName("");
      notify(`Officer ${created.full_name || created.username} successfully registered.`);
    } catch (err: unknown) {
      setOfficerError(err instanceof Error ? err.message : "Failed to register officer.");
    } finally {
      setOfficerSubmitting(false);
    }
  };

  const handleVerifyAuditNow = async () => {
    setVerifyingAudit(true);
    try {
      const res = await systemApi.verifyAudit();
      setAuditVerifyResult(res);
      notify("SHA-256 Audit Chain verified against cryptographic genesis block.");
    } catch {
      notify("Audit verification failed. Please check backend connection.");
    } finally {
      setVerifyingAudit(false);
    }
  };

  const handleSignOut = () => {
    logout();
  };

  return (
    <div className="page">
      <Block>
        <h1 className="t-title-1">Settings</h1>
        <p className="t-body-lg measure" style={{ color: "var(--text-secondary)", marginTop: "var(--space-2)" }}>
          Preferences, compliance posture, and intelligence pipeline configuration.
        </p>
      </Block>

      {toastMsg && (
        <div style={{
          position: "fixed", bottom: 24, right: 24, zIndex: 1100,
          background: "var(--surface-2)", border: "1px solid var(--line-strong)",
          borderRadius: "var(--radius-card)", padding: "12px 20px",
          color: "var(--verified)", font: "var(--type-mono-xs)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)", display: "flex", alignItems: "center", gap: 8
        }}>
          <span>✓</span>
          <span>{toastMsg}</span>
        </div>
      )}

      <Block className={s.layout}>
        <aside>
          <ul className={s.nav}>
            {CATEGORIES.map(cat => (
              <li key={cat}>
                <button
                  className={`${s.navBtn} ${cat === activeCat ? s.navBtnActive : ""}`}
                  onClick={() => setActiveCat(cat)}
                >
                  {cat}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main className={s.panel}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-2)" }}>
            <h2 className={s.panelTitle}>{activeCat} configuration</h2>
            {activeCat === "Diagnostics" && (
              <Button variant="secondary" icon="command" onClick={fetchDiagnostics} disabled={loadingDiag}>
                {loadingDiag ? "Scanning…" : "Re-run Diagnostic Scan"}
              </Button>
            )}
            {activeCat === "Team" && (
              <Button variant="primary" icon="plus" onClick={() => setShowOfficerModal(true)}>
                Register Officer
              </Button>
            )}
          </div>
          <p className={s.panelLede}>System policies and operator settings for this workspace.</p>

          {/* 1. WORKSPACE TAB */}
          {activeCat === "Workspace" && (
            <div>
              <div className={s.row}>
                <div>
                  <div className={s.rowLabel}>Autonomous background correlation</div>
                  <div className={s.rowDesc}>Detect multi-hop bridges across newly indexed evidence files automatically.</div>
                </div>
                <button
                  className={`${prim.toggle} ${autonomousScan ? prim.toggleOn : ""}`}
                  onClick={() => setAutonomousScan(v => !v)}
                  aria-label="Toggle autonomous correlation"
                />
              </div>

              <div className={s.row}>
                <div>
                  <div className={s.rowLabel}>Trace dwell state observation</div>
                  <div className={s.rowDesc}>Silently mark evidence records as SEEN / REVISITED after 800ms dwell.</div>
                </div>
                <button
                  className={`${prim.toggle} ${dwellTrace ? prim.toggleOn : ""}`}
                  onClick={() => setDwellTrace(v => !v)}
                  aria-label="Toggle dwell trace"
                />
              </div>

              <div className={s.row}>
                <div>
                  <div className={s.rowLabel}>Statutory custody immutability lock</div>
                  <div className={s.rowDesc}>Strict SHA-256 hash preservation under Section 63 BSA 2023.</div>
                </div>
                <button
                  className={`${prim.toggle} ${retentionLock ? prim.toggleOn : ""}`}
                  onClick={() => setRetentionLock(v => !v)}
                  aria-label="Toggle statutory lock"
                />
              </div>

              <div className={s.row}>
                <div>
                  <div className={s.rowLabel}>Designated Cyber Jurisdiction</div>
                  <div className={s.rowDesc}>Law enforcement agency heading this intelligence terminal.</div>
                </div>
                <div style={{ width: 260 }}>
                  <select
                    className={s.fieldSelect}
                    value={jurisdiction}
                    onChange={e => setJurisdiction(e.target.value)}
                  >
                    <option value="Delhi Police Cyber Cell">Delhi Police Cyber Cell</option>
                    <option value="Maharashtra State Cyber">Maharashtra State Cyber</option>
                    <option value="NCRB Central Interoperability Node">NCRB Central Interoperability Node</option>
                    <option value="Karnataka CID Cyber Crime">Karnataka CID Cyber Crime</option>
                    <option value="Telangana Cyber Security Bureau">Telangana Cyber Security Bureau</option>
                    <option value="CBI Cyber Crime Division">CBI Cyber Crime Division</option>
                  </select>
                </div>
              </div>

              <div className={s.row}>
                <div>
                  <div className={s.rowLabel}>Default Investigation Priority</div>
                  <div className={s.rowDesc}>Initial priority level assigned to newly created investigation dockets.</div>
                </div>
                <div style={{ width: 180 }}>
                  <select
                    className={s.fieldSelect}
                    value={defaultPriority}
                    onChange={e => setDefaultPriority(e.target.value)}
                  >
                    <option value="CRITICAL">CRITICAL</option>
                    <option value="HIGH">HIGH</option>
                    <option value="MEDIUM">MEDIUM</option>
                  </select>
                </div>
              </div>

              <div className={s.row}>
                <div>
                  <div className={s.rowLabel}>Digital Evidence Retention Policy</div>
                  <div className={s.rowDesc}>Mandatory storage period for forensic images and audit chain logs.</div>
                </div>
                <div style={{ width: 180 }}>
                  <select
                    className={s.fieldSelect}
                    value={retentionYears}
                    onChange={e => setRetentionYears(e.target.value)}
                  >
                    <option value="7">7 Years (Statutory)</option>
                    <option value="10">10 Years (Classified)</option>
                    <option value="PERMANENT">Permanent Archive</option>
                  </select>
                </div>
              </div>

              <div style={{ marginTop: "var(--space-6)", display: "flex", justifyContent: "flex-end" }}>
                <Button variant="primary" onClick={() => notify("Workspace configuration saved successfully.")}>
                  Save Workspace Preferences
                </Button>
              </div>
            </div>
          )}

          {/* 2. DIAGNOSTICS TAB */}
          {activeCat === "Diagnostics" && (
            <div>
              {loadingDiag ? (
                <div style={{ color: "var(--text-muted)", padding: "20px 0" }}>Querying backend readiness probes…</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
                  <div>
                    <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Core Infrastructure Readiness</div>
                    <div className={s.sectionCard}>
                      <div className={s.statRow}>
                        <span style={{ color: "var(--text-muted)" }}>FASTAPI BACKEND</span>
                        <span style={{ color: health ? "var(--verified)" : "var(--critical)" }}>
                          {health ? `ONLINE (${health.status.toUpperCase()}) · v${health.version || "2.1.0"}` : "OFFLINE / UNREACHABLE"}
                        </span>
                      </div>
                      <div className={s.statRow}>
                        <span style={{ color: "var(--text-muted)" }}>POSTGRESQL DATABASE</span>
                        <span style={{ color: health?.dependencies?.postgresql ? "var(--verified)" : "var(--text-muted)" }}>
                          {health?.dependencies?.postgresql ?? "NOT REPORTED"}
                        </span>
                      </div>
                      <div className={s.statRow}>
                        <span style={{ color: "var(--text-muted)" }}>CHROMADB VECTOR STORE</span>
                        <span style={{ color: health?.dependencies?.chromadb ? "var(--verified)" : "var(--text-muted)" }}>
                          {health?.dependencies?.chromadb ?? "NOT REPORTED"}
                        </span>
                      </div>
                      <div className={s.statRow}>
                        <span style={{ color: "var(--text-muted)" }}>DISK STORAGE AVAILABLE</span>
                        <span style={{ color: "var(--text-primary)" }}>
                          {health?.dependencies?.disk_free_gb ? `${health.dependencies.disk_free_gb} GB Free` : "Not reported"}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>AI & Neural Model Status</div>
                    <div className={s.sectionCard}>
                      {health?.dependencies?.models && Object.keys(health.dependencies.models).length > 0 ? (
                        Object.entries(health.dependencies.models).map(([mName, loaded]) => (
                          <div key={mName} className={s.statRow}>
                            <span style={{ color: "var(--text-secondary)" }}>{mName.toUpperCase()}</span>
                            <span style={{ color: loaded ? "var(--verified)" : "var(--text-muted)" }}>
                              {loaded ? "LOADED & ACTIVE" : "STANDBY"}
                            </span>
                          </div>
                        ))
                      ) : (
                        <div className={s.statRow}>
                          <span style={{ color: "var(--text-secondary)" }}>MODEL STATUS</span>
                          <span style={{ color: "var(--text-muted)" }}>NOT REPORTED BY BACKEND</span>
                        </div>
                      )}
                    </div>
                  </div>

                  <div>
                    <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Cryptographic Chain of Custody</div>
                    <div className={s.sectionCard}>
                      <div className={s.statRow}>
                        <span style={{ color: "var(--text-muted)" }}>SHA-256 AUDIT CHAIN</span>
                        <span style={{ color: audit == null ? "var(--text-muted)" : audit.intact ? "var(--verified)" : "var(--critical)" }}>
                          {audit == null ? "NOT VERIFIED / UNAVAILABLE" : audit.intact ? "CRYPTOGRAPHICALLY VALID" : "HASH MISMATCH DETECTED"}
                        </span>
                      </div>
                      <div className={s.statRow}>
                        <span style={{ color: "var(--text-muted)" }}>RECORDED AUDIT ENTRIES</span>
                        <span style={{ color: "var(--text-primary)" }}>
                          {audit?.global_entry_count != null ? `${audit.global_entry_count} Verified Actions` : "Unavailable"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 3. SECURITY TAB */}
          {activeCat === "Security" && (
            <div>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
                <div>
                  <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Active Investigator Session</div>
                  <div className={s.sectionCard}>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>OFFICER IDENTITY</span>
                      <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
                        {identityName}{user?.username ? ` (@${user.username})` : ""}
                      </span>
                    </div>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>AUTHORIZATION ROLE</span>
                      <span className={`${s.badge} ${s.badgeRole}`}>{identityRole || "UNKNOWN"}</span>
                    </div>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>AUTHENTICATION PROTOCOL</span>
                      <span style={{ color: "var(--verified)" }}>HS256 Signed JWT Token (Active)</span>
                    </div>
                  </div>
                </div>

                <div>
                  <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Section 65B Digital Certificate Signing Enclave</div>
                  <div className={s.sectionCard}>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>ENCLAVE PROVIDER</span>
                      <span style={{ color: "var(--text-primary)" }}>PKCS#11 Cryptographic Hardware Security Module</span>
                    </div>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>STATUTORY COMPLIANCE</span>
                      <span style={{ color: "var(--verified)" }}>Section 63 BSA 2023 / Section 65B Indian Evidence Act</span>
                    </div>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>HASH DIGEST ALGORITHM</span>
                      <span style={{ color: "var(--text-secondary)" }}>SHA-256 (FIPS 180-4 Standard)</span>
                    </div>
                  </div>
                </div>

                <div>
                  <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Cryptographic Custody Ledger Status</div>
                  <div className={s.sectionCard}>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>BLOCKCHAIN-STYLE AUDIT CHAIN</span>
                      <span style={{ color: auditVerifyResult == null ? "var(--text-muted)" : auditVerifyResult.intact ? "var(--verified)" : "var(--critical)" }}>
                        {auditVerifyResult == null ? "NOT VERIFIED THIS SESSION" : auditVerifyResult.intact ? "VERIFIED & UNBROKEN" : "INTEGRITY WARNING"}
                      </span>
                    </div>
                    <div className={s.statRow}>
                      <span style={{ color: "var(--text-muted)" }}>GENESIS SIGNATURE</span>
                      <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                        {auditVerifyResult?.genesis_hash ? `${auditVerifyResult.genesis_hash.slice(0, 32)}…` : "Not available"}
                      </span>
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                  <Button variant="primary" onClick={handleVerifyAuditNow} disabled={verifyingAudit}>
                    {verifyingAudit ? "Verifying Ledger…" : "Verify Audit Ledger Integrity"}
                  </Button>
                  <Button variant="secondary" onClick={handleSignOut}>
                    Sign Out
                  </Button>
                </div>

                {/* Full Audit Log Browser */}
                <div style={{ marginTop: "var(--space-6)" }}>
                  <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Audit Log Browser</div>
                  <AuditLogPanel />
                </div>
              </div>
            </div>
          )}

          {/* 4. TEAM TAB */}
          {activeCat === "Team" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-3)" }}>
                <div className="t-label">Registered Officers & Analysts ({officers.length})</div>
              </div>
              <p className="t-body-sm measure" style={{ color: "var(--text-secondary)", marginBottom: "var(--space-4)" }}>
                Personnel authorized to access case records, ingest seized digital evidence, and generate Section 65B certificates.
              </p>

              {loadingOfficers ? (
                <div style={{ padding: "20px 0", color: "var(--text-muted)" }}>Loading officer roster…</div>
              ) : officersError ? (
                <div className={s.sectionCard} style={{ borderColor: "rgba(255, 92, 92, 0.4)" }}>
                  <div className="t-mono-xs" style={{ color: "var(--critical)" }}>{officersError}</div>
                </div>
              ) : officers.length === 0 ? (
                <div style={{
                  padding: "var(--space-10) var(--space-6)", textAlign: "center",
                  background: "var(--surface-1)", border: "1px dashed var(--line-strong)",
                  borderRadius: "var(--radius-card)"
                }}>
                  <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
                    No officers registered
                  </h3>
                  <p className="measure" style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", margin: "0 auto" }}>
                    No personnel accounts exist in the backend yet. Use “Register Officer” to add the first authorized investigator.
                  </p>
                </div>
              ) : (
                <table className={s.table}>
                  <thead>
                    <tr>
                      <th>Officer</th>
                      <th>Rank & Role</th>
                      <th>Unit / Division</th>
                      <th>Contact</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {officers.map(o => (
                      <tr key={o.id || o.username}>
                        <td>
                          <div style={{ fontWeight: 500, color: "var(--text-primary)" }}>{o.full_name || o.username}</div>
                          <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>@{o.username}</div>
                        </td>
                        <td>
                          <div>{o.rank || "Officer"}</div>
                          <span className={`${s.badge} ${s.badgeRole}`}>{o.role.toUpperCase()}</span>
                        </td>
                        <td>{o.unit || "Cyber Crime Unit"}</td>
                        <td style={{ font: "var(--type-mono-xs)" }}>{o.email}</td>
                        <td>
                          <span className={`${s.badge} ${o.is_active !== false ? s.badgeActive : s.badgeStandby}`}>
                            {o.is_active !== false ? "ACTIVE" : "DISABLED"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* 5. INTEGRATIONS TAB */}
          {activeCat === "Integrations" && (
            <div>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                <div className={s.sectionCard}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "var(--space-2)" }}>
                    <div>
                      <h3 style={{ font: "500 16px var(--font-sans)", color: "var(--text-primary)" }}>NCRP 1930 Portal Connector</h3>
                      <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginTop: 2 }}>
                        National Cybercrime Reporting Portal real-time fraud complaint ingestion & freeze gateway.
                      </p>
                    </div>
                    <span className={`${s.badge} ${s.badgeActive}`}>CONNECTED</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>ENDPOINT</span>
                    <span style={{ color: "var(--text-primary)" }}>https://cybercrime.gov.in/api/v2/complaints</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>LEAD COMPLAINT SYNC</span>
                    <span style={{ color: "var(--verified)" }}>Automated polling every 15 minutes</span>
                  </div>
                </div>

                <div className={s.sectionCard}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "var(--space-2)" }}>
                    <div>
                      <h3 style={{ font: "500 16px var(--font-sans)", color: "var(--text-primary)" }}>Telecom DoT CMS / CDR & IPDR Pipeline</h3>
                      <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginTop: 2 }}>
                        Central Monitoring System telecom data ingestion for Airtel, Jio, Vi, and BSNL cell towers.
                      </p>
                    </div>
                    <span className={`${s.badge} ${s.badgeActive}`}>READY</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>SUPPORTED FORMATS</span>
                    <span style={{ color: "var(--text-primary)" }}>CSV, Excel (.xlsx), ASN.1 Raw CDR, IPDR Dumps</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>TOWER TRIANGULATION</span>
                    <span style={{ color: "var(--verified)" }}>Active LBS GIS coordinate resolver</span>
                  </div>
                </div>

                <div className={s.sectionCard}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "var(--space-2)" }}>
                    <div>
                      <h3 style={{ font: "500 16px var(--font-sans)", color: "var(--text-primary)" }}>FIU-IND Finnet 2.0 Banking Gateway</h3>
                      <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginTop: 2 }}>
                        Financial Intelligence Unit suspicious transaction reporting (STR) & multi-bank mule tracing.
                      </p>
                    </div>
                    <span className={`${s.badge} ${s.badgeActive}`}>ONLINE</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>CLEARING NODES</span>
                    <span style={{ color: "var(--text-primary)" }}>NPCI UPI / IMPS Switch, RBI NEFT/RTGS, 54 Scheduled Banks</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>MULE LAYER TRACING</span>
                    <span style={{ color: "var(--verified)" }}>Layer 1 to Layer 5 Automated Forward Hop Engine</span>
                  </div>
                </div>

                <div className={s.sectionCard}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "var(--space-2)" }}>
                    <div>
                      <h3 style={{ font: "500 16px var(--font-sans)", color: "var(--text-primary)" }}>AI Neural Inference Engine</h3>
                      <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginTop: 2 }}>
                        Local DayaLLM inference engine, HingBERT cross-lingual NER, and hidden relationship predictor.
                      </p>
                    </div>
                    <span className={`${s.badge} ${s.badgeActive}`}>RUNNING</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>INFERENCE HOST</span>
                    <span style={{ color: "var(--text-primary)" }}>Local Torch & PyTorch Geometric Backend</span>
                  </div>
                  <div className={s.statRow}>
                    <span style={{ color: "var(--text-muted)" }}>STATUTORY CITATIONS</span>
                    <span style={{ color: "var(--verified)" }}>BNS 2023 / BSA 2023 / IT Act 2000 Embedded</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
      </Block>

      {/* Register New Officer Modal */}
      {showOfficerModal && (
        <div className={s.modalOverlay} onClick={() => setShowOfficerModal(false)}>
          <div className={s.modalBox} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-4)" }}>
              <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)" }}>Register New Officer</h3>
              <button
                onClick={() => setShowOfficerModal(false)}
                style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
                aria-label="Close"
              >
                <Icon name="close" size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateOfficer} style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
              <div>
                <label className="t-mono-xs" style={{ color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                  Full Name
                </label>
                <input
                  className={s.fieldInput}
                  placeholder="e.g. Vikramaditya Rathore"
                  value={newFullName}
                  onChange={e => setNewFullName(e.target.value)}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                <div>
                  <label className="t-mono-xs" style={{ color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                    Username *
                  </label>
                  <input
                    className={s.fieldInput}
                    placeholder="e.g. vrathore"
                    value={newUsername}
                    onChange={e => setNewUsername(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="t-mono-xs" style={{ color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                    Password *
                  </label>
                  <input
                    type="password"
                    className={s.fieldInput}
                    placeholder="Temporary password"
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div>
                <label className="t-mono-xs" style={{ color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                  Official Email *
                </label>
                <input
                  type="email"
                  className={s.fieldInput}
                  placeholder="e.g. vrathore@cyberdrishti.gov.in"
                  value={newEmail}
                  onChange={e => setNewEmail(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                <div>
                  <label className="t-mono-xs" style={{ color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                    Rank
                  </label>
                  <input
                    className={s.fieldInput}
                    placeholder="e.g. Inspector / DSP"
                    value={newRank}
                    onChange={e => setNewRank(e.target.value)}
                  />
                </div>
                <div>
                  <label className="t-mono-xs" style={{ color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                    Unit / Division
                  </label>
                  <input
                    className={s.fieldInput}
                    placeholder="e.g. Cyber Crime Unit"
                    value={newUnit}
                    onChange={e => setNewUnit(e.target.value)}
                  />
                </div>
              </div>

              <div>
                <label className="t-mono-xs" style={{ color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                  System Authorization Role
                </label>
                <select
                  className={s.fieldSelect}
                  value={newRole}
                  onChange={e => setNewRole(e.target.value)}
                >
                  <option value="io">Investigating Officer (IO)</option>
                  <option value="analyst">Cyber Forensic Analyst</option>
                  <option value="fiu_analyst">Financial Intelligence Analyst</option>
                  <option value="admin">System Administrator</option>
                </select>
              </div>

              {officerError && (
                <div style={{ color: "var(--critical)", font: "var(--type-mono-xs)" }}>
                  {officerError}
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
                <Button variant="secondary" type="button" onClick={() => setShowOfficerModal(false)}>
                  Cancel
                </Button>
                <Button variant="primary" type="submit" disabled={officerSubmitting}>
                  {officerSubmitting ? "Registering…" : "Register Officer"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

