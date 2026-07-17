import { useEffect, useRef, useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { CheckCircle2, AlertTriangle, Scale, ChevronDown, ChevronUp, Loader2, FileText } from "lucide-react";
import { getContract, submitDecisions, generateReport, recoverReport } from "../api";
import RiskBadge, { normalize } from "../components/RiskBadge";

const REPORT_POLL_INTERVAL_MS = 4000;
const REPORT_POLL_TIMEOUT_MS = 4 * 60 * 1000;

const ACTION_LABELS = {
  approve: "Approuver",
  reject: "Rejeter",
  reclassify: "Reclasser",
  request_lawyer_review: "Avis avocat",
};

const RECLASS_OPTIONS = [
  { value: "vert", label: "Vert (faible)" },
  { value: "orange", label: "Orange (moyen)" },
  { value: "rouge", label: "Rouge (élevé)" },
];

function effectiveRisk(finding) {
  return normalize(finding.corrected_risk_level) !== "unknown"
    ? finding.corrected_risk_level
    : finding.original_risk_level;
}

function DecisionButton({ label, active, onClick, variant }) {
  const variants = {
    approve: { border: "var(--color-success)", bg: "var(--color-success-trans-8)", color: "var(--color-success)" },
    reject: { border: "var(--color-critical)", bg: "var(--color-critical-trans-6)", color: "var(--color-critical)" },
    default: { border: "var(--color-border)", bg: "var(--color-card)", color: "var(--color-text)" },
  };
  const v = variants[variant] || variants.default;
  const coloredOutline = variant === "approve" || variant === "reject";
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flex: 1,
        padding: "var(--space-3)",
        borderRadius: "var(--radius)",
        border: `1px solid ${active || coloredOutline ? v.border : "var(--color-border)"}`,
        backgroundColor: active ? v.bg : "var(--color-card)",
        color: active || coloredOutline ? v.color : "var(--color-text)",
        fontWeight: 500,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "var(--space-2)",
      }}
    >
      {active && <CheckCircle2 size={16} />}
      {label}
    </button>
  );
}

export default function Review() {
  const { contractId } = useParams();
  const navigate = useNavigate();
  const [contract, setContract] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [decisions, setDecisions] = useState({});
  const [comments, setComments] = useState({});
  const [reclassLevels, setReclassLevels] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [reportElapsed, setReportElapsed] = useState(0);
  const [reportError, setReportError] = useState("");
  const [reportFailedStatus, setReportFailedStatus] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showReason, setShowReason] = useState(false);
  const reportPollRef = useRef(null);
  const reportTimerRef = useRef(null);

  useEffect(() => {
    getContract(contractId)
      .then((data) => {
        setContract(data);
        const existing = {};
        const existingComments = {};
        const existingLevels = {};
        (data.human_decisions || []).forEach((d) => {
          existing[d.clause_id] = d.action;
          existingComments[d.clause_id] = d.comment || "";
          existingLevels[d.clause_id] = d.new_risk_level || "";
        });
        setDecisions(existing);
        setComments(existingComments);
        setReclassLevels(existingLevels);

        const findings = data.analysis_result?.audited_findings || [];
        const firstPending = findings.find(
          (f) => f.human_review_required && !existing[f.clause_id]
        );
        setSelectedId(firstPending?.clause_id || findings[0]?.clause_id);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  const findings = contract?.analysis_result?.audited_findings || [];

  const pending = useMemo(
    () => findings.filter((f) => f.human_review_required && !decisions[f.clause_id]),
    [findings, decisions]
  );

  const selected = findings.find((f) => f.clause_id === selectedId) || findings[0];

  const setDecision = (clauseId, action) => {
    setDecisions((prev) => ({ ...prev, [clauseId]: action }));
  };

  const advanceToNext = (currentId) => {
    const idx = findings.findIndex((f) => f.clause_id === currentId);
    const next = findings
      .slice(idx + 1)
      .find((f) => f.human_review_required && !decisions[f.clause_id]);
    if (next) setSelectedId(next.clause_id);
  };

  const saveDecisions = async () => {
    const payload = Object.entries(decisions).map(([clause_id, action]) => ({
      clause_id,
      action,
      comment: comments[clause_id] || "",
      new_risk_level: action === "reclassify" ? reclassLevels[clause_id] || undefined : undefined,
    }));
    setSaving(true);
    try {
      await submitDecisions(contractId, payload);
      const updated = await getContract(contractId);
      setContract(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const stopReportPolling = () => {
    if (reportPollRef.current) {
      clearInterval(reportPollRef.current);
      reportPollRef.current = null;
    }
    if (reportTimerRef.current) {
      clearInterval(reportTimerRef.current);
      reportTimerRef.current = null;
    }
  };

  useEffect(() => stopReportPolling, []);

  const handleGenerateReport = async () => {
    await saveDecisions();
    setGenerating(true);
    setReportError("");
    setReportFailedStatus(false);
    setReportElapsed(0);
    try {
      await generateReport(contractId);
    } catch (err) {
      setReportError(err.message);
      setGenerating(false);
      return;
    }

    reportTimerRef.current = setInterval(() => setReportElapsed((prev) => prev + 1), 1000);

    const check = async () => {
      try {
        const data = await getContract(contractId);
        if (data.status === "completed") {
          stopReportPolling();
          navigate(`/report/${contractId}`);
          return;
        }
        if (data.status === "report_error") {
          stopReportPolling();
          setGenerating(false);
          setReportFailedStatus(true);
          setReportError(data.error_message || "La génération du rapport a échoué. Veuillez réessayer.");
        }
      } catch (err) {
        stopReportPolling();
        setGenerating(false);
        setReportError(err.message || "Une erreur est survenue.");
      }
    };

    check();
    reportPollRef.current = setInterval(check, REPORT_POLL_INTERVAL_MS);

    setTimeout(() => {
      if (reportPollRef.current) {
        stopReportPolling();
        setGenerating(false);
        setReportError("La génération du rapport a dépassé le délai maximal. Veuillez réessayer.");
      }
    }, REPORT_POLL_TIMEOUT_MS);
  };

  const handleRecoverReport = async () => {
    setRecovering(true);
    setReportError("");
    try {
      await recoverReport(contractId);
      navigate(`/report/${contractId}`);
    } catch (err) {
      setReportError(err.message || "Échec de la récupération du rapport.");
      setRecovering(false);
    }
  };

  const formatReportElapsed = (seconds) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  if (loading) {
    return (
      <div className="loading">
        <Loader2 className="spin" size={24} style={{ marginRight: "var(--space-2)" }} />
        Chargement de la revue…
      </div>
    );
  }

  if (error) return <div className="alert alert-error">{error}</div>;
  if (!contract?.analysis_result) return <div className="alert">Aucune analyse disponible.</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - var(--topbar-height) - var(--space-8) * 2)" }}>
      <div className="page-header" style={{ flexShrink: 0 }}>
        <h1>Revue des clauses</h1>
        <p>Examinez chaque clause signalée et validez les décisions pour les risques ORANGE et ROUGE.</p>
      </div>

      <div style={{ display: "flex", gap: "var(--space-6)", flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* Left: clause blocks */}
        <div
          style={{
            flex: "0 0 55%",
            overflowY: "auto",
            paddingRight: "var(--space-2)",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
            {findings.map((f) => {
              const norm = normalize(effectiveRisk(f));
              const requiresDecision = f.human_review_required;
              const decided = decisions[f.clause_id];
              const isSelected = selected?.clause_id === f.clause_id;
              const riskColors = {
                vert: "var(--color-success)",
                orange: "var(--color-warning)",
                rouge: "var(--color-critical)",
                unknown: "var(--color-unknown)",
              };
              return (
                <div
                  key={f.clause_id}
                  onClick={() => setSelectedId(f.clause_id)}
                  style={{
                    border: `1px solid ${isSelected ? "var(--color-secondary)" : "var(--color-border)"}`,
                    borderLeft: `4px solid ${riskColors[norm]}`,
                    borderRadius: "var(--radius)",
                    padding: "var(--space-4)",
                    backgroundColor: isSelected ? "var(--color-bg)" : "var(--color-card)",
                    cursor: "pointer",
                    transition: "background-color 0.15s, border-color 0.15s",
                    position: "relative",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-2)" }}>
                    <span className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                      {f.reference}
                    </span>
                    <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                      <RiskBadge level={effectiveRisk(f)} />
                      {decided && <CheckCircle2 size={16} color="var(--color-success)" />}
                    </div>
                  </div>
                  <p style={{ fontSize: "0.95rem", color: "var(--color-text)", margin: 0 }}>{f.clause_text}</p>
                  {requiresDecision && !decided && (
                    <div style={{ marginTop: "var(--space-2)", fontSize: "0.8rem", color: "var(--color-warning)", fontWeight: 500 }}>
                      <AlertTriangle size={14} style={{ verticalAlign: "text-bottom", marginRight: 4 }} />
                      Décision requise
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: analysis panel */}
        <div
          style={{
            flex: "0 0 45%",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-4)",
          }}
        >
          {selected ? (
            <>
              <div className="card">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-4)" }}>
                  <div>
                    <div className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-1)" }}>
                      {selected.reference}
                    </div>
                    <h2 style={{ fontSize: "1.1rem" }}>{selected.type}</h2>
                  </div>
                  <RiskBadge level={effectiveRisk(selected)} />
                </div>

                <div style={{ marginBottom: "var(--space-4)" }}>
                  <h3 style={{ fontSize: "0.75rem", textTransform: "uppercase", color: "var(--color-text-muted)", marginBottom: "var(--space-2)" }}>
                    Constat
                  </h3>
                  <p style={{ fontSize: "0.95rem" }}>{selected.risk_summary}</p>
                </div>

                {selected.source_excerpts?.length > 0 && (
                  <div style={{ marginBottom: "var(--space-4)" }}>
                    <h3 style={{ fontSize: "0.75rem", textTransform: "uppercase", color: "var(--color-text-muted)", marginBottom: "var(--space-2)" }}>
                      Preuve
                    </h3>
                    {selected.source_excerpts.map((ex, i) => (
                      <blockquote
                        key={i}
                        style={{
                          margin: "0 0 var(--space-2) 0",
                          padding: "var(--space-3)",
                          borderLeft: "3px solid var(--color-accent)",
                          backgroundColor: "var(--color-bg)",
                          fontSize: "0.9rem",
                          color: "var(--color-text)",
                        }}
                      >
                        {ex}
                      </blockquote>
                    ))}
                  </div>
                )}

                {selected.proposed_rewrite && (
                  <div style={{ marginBottom: "var(--space-4)" }}>
                    <h3 style={{ fontSize: "0.75rem", textTransform: "uppercase", color: "var(--color-text-muted)", marginBottom: "var(--space-2)" }}>
                      Reformulation proposée
                    </h3>
                    <div
                      style={{
                        padding: "var(--space-3)",
                        border: "1px solid var(--color-border)",
                        borderRadius: "var(--radius)",
                        backgroundColor: "var(--color-card)",
                        fontSize: "0.9rem",
                      }}
                    >
                      {selected.proposed_rewrite}
                    </div>
                  </div>
                )}

                <div>
                  <button
                    type="button"
                    className="btn-text"
                    onClick={() => setShowReason((s) => !s)}
                    style={{ display: "flex", alignItems: "center", gap: "var(--space-1)" }}
                  >
                    Motif de l'audit {showReason ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                  {showReason && (
                    <p style={{ marginTop: "var(--space-2)", fontSize: "0.9rem", color: "var(--color-text-muted)" }}>
                      {selected.audit_reason}
                    </p>
                  )}
                </div>
              </div>

              <div className="card">
                <h2 className="card-title">Décision</h2>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "var(--space-3)", marginBottom: "var(--space-4)" }}>
                  <DecisionButton
                    action="approve"
                    label={ACTION_LABELS.approve}
                    variant="approve"
                    active={decisions[selected.clause_id] === "approve"}
                    onClick={() => setDecision(selected.clause_id, "approve")}
                  />
                  <DecisionButton
                    action="reject"
                    label={ACTION_LABELS.reject}
                    variant="reject"
                    active={decisions[selected.clause_id] === "reject"}
                    onClick={() => setDecision(selected.clause_id, "reject")}
                  />
                  <DecisionButton
                    action="reclassify"
                    label={ACTION_LABELS.reclassify}
                    active={decisions[selected.clause_id] === "reclassify"}
                    onClick={() => setDecision(selected.clause_id, "reclassify")}
                  />
                  <DecisionButton
                    action="request_lawyer_review"
                    label={ACTION_LABELS.request_lawyer_review}
                    active={decisions[selected.clause_id] === "request_lawyer_review"}
                    onClick={() => setDecision(selected.clause_id, "request_lawyer_review")}
                  />
                </div>

                {decisions[selected.clause_id] === "reclassify" && (
                  <div className="form-group" style={{ marginBottom: "var(--space-4)" }}>
                    <label>Nouveau niveau de risque</label>
                    <select
                      value={reclassLevels[selected.clause_id] || ""}
                      onChange={(e) => setReclassLevels({ ...reclassLevels, [selected.clause_id]: e.target.value })}
                    >
                      <option value="">Sélectionner…</option>
                      {RECLASS_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="form-group">
                  <label>Commentaire optionnel</label>
                  <textarea
                    rows={3}
                    value={comments[selected.clause_id] || ""}
                    onChange={(e) => setComments({ ...comments, [selected.clause_id]: e.target.value })}
                    placeholder="Ajouter un commentaire…"
                  />
                </div>

                <button
                  type="button"
                  className="btn-primary"
                  style={{ width: "100%", marginTop: "var(--space-4)" }}
                  onClick={() => {
                    advanceToNext(selected.clause_id);
                  }}
                  disabled={saving}
                >
                  {saving ? <Loader2 size={18} className="spin" /> : <CheckCircle2 size={18} />}
                  Enregistrer et suivant
                </button>
              </div>
            </>
          ) : (
            <div className="card empty-state">
              <Scale size={32} />
              <p>Sélectionnez une clause pour afficher son analyse.</p>
            </div>
          )}
        </div>
      </div>

      {reportError && (
        <div
          className="alert alert-error review-sticky-footer"
          style={{
            position: "fixed",
            bottom: 76,
            right: 0,
            margin: "0 var(--space-8)",
            zIndex: 51,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "var(--space-4)",
          }}
        >
          <span>{reportError}</span>
          {reportFailedStatus && (
            <button
              type="button"
              className="btn-secondary"
              onClick={handleRecoverReport}
              disabled={recovering}
              style={{ flexShrink: 0 }}
            >
              {recovering ? <Loader2 size={16} className="spin" /> : null}
              Récupérer le rapport
            </button>
          )}
        </div>
      )}

      {generating && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "var(--color-primary-trans-55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 200,
          }}
        >
          <div className="card" style={{ maxWidth: 420, textAlign: "center", padding: "var(--space-8)" }}>
            <FileText size={32} color="var(--color-secondary)" style={{ marginBottom: "var(--space-4)" }} />
            <h2 className="card-title" style={{ marginBottom: "var(--space-2)" }}>Génération du rapport en cours</h2>
            <p style={{ color: "var(--color-text-muted)", marginBottom: "var(--space-4)" }}>
              L'analyse finale est en cours de rédaction. Cette opération peut prendre jusqu'à 2 minutes.
              Ne fermez pas cette page.
            </p>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "var(--space-2)" }}>
              <Loader2 size={20} className="spin" color="var(--color-secondary)" />
              <span className="mono" style={{ color: "var(--color-text-muted)" }}>{formatReportElapsed(reportElapsed)}</span>
            </div>
          </div>
        </div>
      )}

      {/* Sticky footer */}
      <div
        className="review-sticky-footer"
        style={{
          position: "fixed",
          bottom: 0,
          right: 0,
          backgroundColor: "var(--color-card)",
          borderTop: "1px solid var(--color-border)",
          padding: "var(--space-4) var(--space-8)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          boxShadow: "var(--shadow-elevated)",
          zIndex: 50,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
          {pending.length > 0 ? (
            <>
              <AlertTriangle size={20} color="var(--color-warning)" />
              <span>
                <strong>{pending.length}</strong> clause{pending.length > 1 ? "s" : ""} en attente de décision
              </span>
            </>
          ) : (
            <>
              <CheckCircle2 size={20} color="var(--color-success)" />
              <span>Toutes les clauses ont été examinées</span>
            </>
          )}
        </div>
        <div style={{ display: "flex", gap: "var(--space-3)" }}>
          <button type="button" className="btn-secondary" onClick={saveDecisions} disabled={saving}>
            {saving ? <Loader2 size={16} className="spin" /> : null}
            Enregistrer
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={pending.length > 0 || generating}
            onClick={handleGenerateReport}
          >
            {generating ? <Loader2 size={18} className="spin" /> : null}
            Générer le rapport
          </button>
        </div>
      </div>
    </div>
  );
}
