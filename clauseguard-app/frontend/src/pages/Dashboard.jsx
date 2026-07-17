import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, Clock, AlertTriangle, CheckCircle, Activity, Upload } from "lucide-react";
import { listContracts, getActivity } from "../api";
import RiskBadge, { normalize } from "../components/RiskBadge";

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function formatTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusBadge(status) {
  const map = {
    uploaded: { label: "Importé", class: "badge-unknown" },
    processing: { label: "Analyse…", class: "badge-accent" },
    awaiting_human_review: { label: "En revue", class: "badge-orange" },
    pending_human_validation: { label: "Validation", class: "badge-orange" },
    decisions_recorded: { label: "Décisions", class: "badge-vert" },
    completed: { label: "Terminé", class: "badge-vert" },
    parse_error: { label: "Erreur", class: "badge-rouge" },
    flow_error: { label: "Erreur", class: "badge-rouge" },
    error: { label: "Erreur", class: "badge-rouge" },
  };
  const item = map[status] || { label: status, class: "badge-unknown" };
  return <span className={`badge ${item.class}`}>{item.label}</span>;
}

function KpiCard({ icon: Icon, label, value, accent }) {
  return (
    <div className="card" style={{ display: "flex", alignItems: "center", gap: "var(--space-4)" }}>
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: "var(--radius)",
          backgroundColor: accent,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--color-text-inverse)",
          flexShrink: 0,
        }}
      >
        <Icon size={22} />
      </div>
      <div>
        <div style={{ fontSize: "1.75rem", fontWeight: 600, color: "var(--color-primary)", lineHeight: 1.2 }}>
          {value}
        </div>
        <div style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>{label}</div>
      </div>
    </div>
  );
}

function SkeletonKpi() {
  return (
    <div className="card" style={{ display: "flex", alignItems: "center", gap: "var(--space-4)" }}>
      <div className="skeleton" style={{ width: 44, height: 44, borderRadius: "var(--radius)" }} />
      <div style={{ flex: 1 }}>
        <div className="skeleton" style={{ width: 60, height: 28, marginBottom: 8 }} />
        <div className="skeleton" style={{ width: "80%", height: 14 }} />
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [contracts, setContracts] = useState([]);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([listContracts().catch(() => []), getActivity().catch(() => [])])
      .then(([contractsData, activityData]) => {
        setContracts(contractsData);
        setActivity(activityData);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const kpis = (() => {
    const analyzed = contracts.filter((c) =>
      ["awaiting_human_review", "pending_human_validation", "decisions_recorded", "completed"].includes(c.status)
    ).length;
    const pendingReview = contracts.filter(
      (c) => c.status === "awaiting_human_review" || c.status === "pending_human_validation"
    ).length;
    const criticalClauses = contracts.reduce((sum, c) => {
      if (!c.analysis_result?.audited_findings) return sum;
      return (
        sum +
        c.analysis_result.audited_findings.filter((f) => {
          const risk = normalize(f.corrected_risk_level) !== "unknown"
            ? f.corrected_risk_level
            : f.original_risk_level;
          return normalize(risk) === "rouge";
        }).length
      );
    }, 0);
    const humanDecisions = contracts.reduce((sum, c) => sum + (c.human_decisions?.length || 0), 0);
    return { analyzed, pendingReview, criticalClauses, humanDecisions };
  })();

  const recentContracts = [...contracts]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 6);

  if (loading) {
    return (
      <div>
        <div className="page-header">
          <h1>Tableau de bord</h1>
          <p>Vue d'ensemble de votre activité contractuelle.</p>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "var(--space-4)",
            marginBottom: "var(--space-6)",
          }}
        >
          <SkeletonKpi />
          <SkeletonKpi />
          <SkeletonKpi />
          <SkeletonKpi />
        </div>
        <div className="skeleton" style={{ height: 200, marginBottom: "var(--space-6)" }} />
        <div className="skeleton" style={{ height: 200 }} />
      </div>
    );
  }

  if (error) {
    return <div className="alert alert-error">{error}</div>;
  }

  if (contracts.length === 0) {
    return (
      <div className="empty-state">
        <FileText />
        <h3>Aucun contrat analysé</h3>
        <p>Commencez par téléverser votre premier contrat. Formats : PDF, DOCX, TXT.</p>
        <Link to="/upload" className="btn-primary" style={{ marginTop: "var(--space-4)" }}>
          <Upload size={18} /> Téléverser un contrat
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Tableau de bord</h1>
        <p>Vue d'ensemble de votre activité contractuelle.</p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "var(--space-4)",
          marginBottom: "var(--space-6)",
        }}
      >
        <KpiCard
          icon={FileText}
          label="Contrats analysés"
          value={kpis.analyzed}
          accent="var(--color-secondary)"
        />
        <KpiCard
          icon={Clock}
          label="En attente de revue"
          value={kpis.pendingReview}
          accent="var(--color-warning)"
        />
        <KpiCard
          icon={AlertTriangle}
          label="Clauses critiques détectées"
          value={kpis.criticalClauses}
          accent="var(--color-critical)"
        />
        <KpiCard
          icon={CheckCircle}
          label="Décisions humaines enregistrées"
          value={kpis.humanDecisions}
          accent="var(--color-success)"
        />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
          gap: "var(--space-6)",
          alignItems: "start",
        }}
      >
        <div className="card">
          <h2 className="card-title">Contrats récents</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>Nom</th>
                <th>Statut</th>
                <th>Risque global</th>
                <th>Mis à jour</th>
              </tr>
            </thead>
            <tbody>
              {recentContracts.map((c) => (
                <tr key={c.contract_id}>
                  <td>
                    <Link
                      to={c.status === "completed" ? `/report/${c.contract_id}` : `/review/${c.contract_id}`}
                      className="btn-text"
                    >
                      {c.filename}
                    </Link>
                    <div className="mono" style={{ color: "var(--color-text-muted)", fontSize: "0.75rem" }}>
                      {c.contract_id.slice(0, 8)}
                    </div>
                  </td>
                  <td>{statusBadge(c.status)}</td>
                  <td>
                    {c.final_report?.overall_risk ? (
                      <RiskBadge level={c.final_report.overall_risk} />
                    ) : (
                      <span className="badge badge-unknown">—</span>
                    )}
                  </td>
                  <td style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                    {formatDate(c.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2 className="card-title">
            <Activity size={18} style={{ verticalAlign: "text-bottom" }} /> Activité récente
          </h2>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "var(--space-3)",
              maxHeight: 360,
              overflowY: "auto",
            }}
          >
            {activity.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>Aucune activité enregistrée.</p>
            ) : (
              activity.map((entry, idx) => (
                <div key={idx} style={{ display: "flex", gap: "var(--space-3)" }}>
                  <div style={{ textAlign: "right", minWidth: 50 }}>
                    <div className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                      {formatTime(entry.timestamp)}
                    </div>
                    <div className="mono" style={{ fontSize: "0.7rem", color: "var(--color-border)" }}>
                      {formatDate(entry.timestamp)}
                    </div>
                  </div>
                  <div
                    style={{
                      borderLeft: "2px solid var(--color-border)",
                      paddingLeft: "var(--space-3)",
                      flex: 1,
                    }}
                  >
                    <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>{entry.action}</div>
                    <div className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                      {entry.detail}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
