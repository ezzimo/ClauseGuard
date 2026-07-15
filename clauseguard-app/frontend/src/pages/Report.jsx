import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getReport, API_URL } from "../api";
import RiskBadge from "../components/RiskBadge";

export default function Report() {
  const { contractId } = useParams();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAudit, setShowAudit] = useState(false);

  useEffect(() => {
    getReport(contractId)
      .then((data) => setReport(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  if (loading) return <div className="loading">Chargement du rapport...</div>;
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

  return (
    <div className="report-page">
      <div className="report-header">
        <h1>Rapport d'analyse</h1>
        <button className="btn-secondary" onClick={exportJson}>
          Exporter JSON
        </button>
      </div>

      <div className="executive-summary card">
        <h2>Résumé exécutif</h2>
        <p>{report.executive_summary}</p>
      </div>

      <div className="report-meta">
        <div className="meta-item">
          <span>Identifiant</span>
          <strong>{report.contract_id}</strong>
        </div>
        <div className="meta-item">
          <span>Date d'analyse</span>
          <strong>{new Date(report.analysis_date).toLocaleDateString("fr-FR")}</strong>
        </div>
        <div className="meta-item">
          <span>Risque global</span>
          <RiskBadge level={report.overall_risk} label={report.overall_risk} />
        </div>
      </div>

      <div className="metrics-grid">
        <div className="metric-card">
          <span>Clauses totales</span>
          <strong>{report.dashboard_metrics.total_clauses}</strong>
        </div>
        <div className="metric-card high">
          <span>Risques élevés</span>
          <strong>{report.dashboard_metrics.high_risk_count}</strong>
        </div>
        <div className="metric-card medium">
          <span>Risques moyens</span>
          <strong>{report.dashboard_metrics.medium_risk_count}</strong>
        </div>
        <div className="metric-card low">
          <span>Risques faibles</span>
          <strong>{report.dashboard_metrics.low_risk_count}</strong>
        </div>
        <div className="metric-card">
          <span>Décisions en attente</span>
          <strong>{report.dashboard_metrics.pending_decisions}</strong>
        </div>
      </div>

      <div className="card">
        <h2>Clauses auditées</h2>
        <table className="clauses-table report-table">
          <thead>
            <tr>
              <th>Référence</th>
              <th>Risque initial</th>
              <th>Risque corrigé</th>
              <th>Décision humaine</th>
              <th>Commentaire</th>
            </tr>
          </thead>
          <tbody>
            {report.clauses.map((c) => (
              <tr key={c.clause_id}>
                <td>{c.reference}</td>
                <td>
                  <RiskBadge level={c.original_risk_level} />
                </td>
                <td>
                  <RiskBadge level={c.corrected_risk_level} />
                </td>
                <td>{c.human_decision || "-"}</td>
                <td>{c.comment || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card audit-section">
        <button className="btn-text" onClick={() => setShowAudit(!showAudit)}>
          {showAudit ? "Masquer" : "Afficher"} le journal d'audit
        </button>
        {showAudit && (
          <pre className="audit-log">{JSON.stringify(report.audit_log, null, 2)}</pre>
        )}
      </div>

      <div className="report-disclaimer">
        <strong>Avertissement</strong>
        <p>{report.disclaimer}</p>
      </div>
    </div>
  );
}
