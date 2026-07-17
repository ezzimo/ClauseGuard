import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Download, FileDown, AlertTriangle, Clock, FileCheck, Scale, ChevronDown, ChevronUp, Shield, Loader2 } from "lucide-react";
import { getReport, downloadReportPdf } from "../api";
import RiskBadge, { normalize } from "../components/RiskBadge";

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const DECISION_LABELS = {
  approve: "Approuvé",
  reject: "Rejeté",
  reclassify: "Reclassé",
  request_lawyer_review: "Avis avocat",
};

export default function Report() {
  const { contractId } = useParams();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedAudits, setExpandedAudits] = useState({});
  const [exportingPdf, setExportingPdf] = useState(false);
  const [pdfError, setPdfError] = useState("");
  const decider = localStorage.getItem("X-User-Id") || "Revue humaine";

  useEffect(() => {
    getReport(contractId)
      .then((data) => setReport(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  if (loading) {
    return (
      <div className="page">
        <div className="skeleton" style={{ height: 120, marginBottom: "var(--space-6)" }} />
        <div className="skeleton" style={{ height: 80, marginBottom: "var(--space-6)" }} />
        <div className="skeleton" style={{ height: 300 }} />
      </div>
    );
  }

  if (error) return <div className="alert alert-error">{error}</div>;
  if (!report) return <div className="alert">Aucun rapport disponible.</div>;

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `clauseguard-report-${contractId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportPdf = async () => {
    setExportingPdf(true);
    setPdfError("");
    try {
      await downloadReportPdf(contractId);
    } catch (err) {
      setPdfError(err.message || "Échec de l'export PDF.");
    } finally {
      setExportingPdf(false);
    }
  };

  const metrics = report.dashboard_metrics || {};
  const toggleAudit = (idx) => setExpandedAudits((prev) => ({ ...prev, [idx]: !prev[idx] }));

  const riskCounts = (report.clauses || []).reduce(
    (acc, c) => {
      const level = normalize(c.risk_level);
      if (level === "rouge") acc.rouge += 1;
      else if (level === "orange") acc.orange += 1;
      else if (level === "vert") acc.vert += 1;
      return acc;
    },
    { rouge: 0, orange: 0, vert: 0 }
  );

  return (
    <div>
      <div className="page-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div className="mono" style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-1)" }}>
            RAPPORT D'ANALYSE · {contractId.slice(0, 8)}
          </div>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 600, lineHeight: 1.3 }}>{report.executive_summary}</h1>
        </div>
        <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
          <RiskBadge level={report.overall_risk} label={report.overall_risk} />
          <button className="btn-primary" onClick={exportPdf} disabled={exportingPdf}>
            {exportingPdf ? <Loader2 size={16} className="spin" /> : <FileDown size={16} />}
            Exporter en PDF
          </button>
          <button className="btn-secondary" onClick={exportJson}>
            <Download size={16} /> Export JSON (audit)
          </button>
        </div>
      </div>

      {pdfError && (
        <div className="alert alert-error" style={{ marginBottom: "var(--space-4)" }}>
          {pdfError}
        </div>
      )}

      {report.delivery && report.delivery !== "full" && (
        <div className="alert alert-warning" style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
          <AlertTriangle size={20} />
          <div>
            <strong>Rapport généré</strong>
            <div style={{ fontSize: "0.9rem" }}>
              {
                {
                  full_db: "Rapport récupéré depuis la base après un délai de réponse de la plateforme. Sauvegarde et notification email déjà effectuées.",
                  fallback_flow_response: "Rapport généré, mais la confirmation de sauvegarde/notification n'a pas pu être vérifiée.",
                  fallback_no_dispatch: "Sauvegarde externe et notification email différées (service indisponible).",
                }[report.delivery] || "Rapport généré via un circuit de secours."
              }
            </div>
          </div>
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: "var(--space-4)",
          marginBottom: "var(--space-6)",
        }}
      >
        <div className="card" style={{ textAlign: "center", borderTop: "3px solid var(--color-border)" }}>
          <div style={{ fontSize: "1.75rem", fontWeight: 600 }}>{metrics.total_clauses_processed ?? report.clauses.length}</div>
          <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>Clauses totales</div>
        </div>
        <div className="card" style={{ textAlign: "center", borderTop: "3px solid var(--color-critical)" }}>
          <div style={{ fontSize: "1.75rem", fontWeight: 600, color: "var(--color-critical)" }}>
            {riskCounts.rouge}
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>ROUGE</div>
        </div>
        <div className="card" style={{ textAlign: "center", borderTop: "3px solid var(--color-warning)" }}>
          <div style={{ fontSize: "1.75rem", fontWeight: 600, color: "var(--color-warning-dark)" }}>
            {riskCounts.orange}
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>ORANGE</div>
        </div>
        <div className="card" style={{ textAlign: "center", borderTop: "3px solid var(--color-success)" }}>
          <div style={{ fontSize: "1.75rem", fontWeight: 600, color: "var(--color-success)" }}>
            {riskCounts.vert}
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>VERT</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: "var(--space-6)", overflow: "hidden" }}>
        <h2 className="card-title">Clauses auditées</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Référence</th>
              <th>Type</th>
              <th>Risque</th>
              <th>Décision humaine</th>
              <th>Décideur</th>
            </tr>
          </thead>
          <tbody>
            {report.clauses.map((c) => (
              <tr key={c.clause_id}>
                <td className="mono">{c.reference}</td>
                <td>{c.type}</td>
                <td>
                  <RiskBadge level={c.risk_level} />
                </td>
                <td>{DECISION_LABELS[c.human_decision] || c.human_decision || "—"}</td>
                <td>{c.human_decision ? decider : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: "var(--space-6)", alignItems: "start" }}>
        <div className="card">
          <h2 className="card-title">
            <Clock size={18} style={{ verticalAlign: "text-bottom" }} /> Journal d'audit
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)", maxHeight: 400, overflowY: "auto" }}>
            {(report.audit_log || []).map((entry, idx) => (
              <div
                key={idx}
                style={{
                  borderLeft: "2px solid var(--color-border)",
                  paddingLeft: "var(--space-3)",
                }}
              >
                <div className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                  {formatDate(entry.timestamp)}
                </div>
                <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>{entry.action || entry.event || "—"}</div>
                {entry.request_id && (
                  <div className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                    req: {entry.request_id}
                  </div>
                )}
                {entry.latency_ms !== undefined && (
                  <div className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                    {entry.latency_ms} ms · status {entry.status}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h2 className="card-title">
            <Shield size={18} style={{ verticalAlign: "text-bottom" }} /> Métadonnées
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "var(--space-4)" }}>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-1)" }}>
                Généré le
              </div>
              <div className="mono">{formatDate(report.analysis_date)}</div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-1)" }}>
                Request ID
              </div>
              <div className="mono">
                {(report.request_id || (report.audit_log || []).find((e) => e.request_id)?.request_id || "").slice(0, 16) || "—"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-1)" }}>
                Modèles
              </div>
              <div>Groq, Gemini</div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-1)" }}>
                Taux de citation
              </div>
              <div>
                {metrics.citation_rate != null ? `${Math.round(metrics.citation_rate * 100)} %` : "—"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-1)" }}>
                Validé par
              </div>
              <div>Revue humaine</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
