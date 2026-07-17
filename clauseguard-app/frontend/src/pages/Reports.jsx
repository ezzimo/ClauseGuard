import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileCheck, Loader2 } from "lucide-react";
import { listContracts } from "../api";
import RiskBadge from "../components/RiskBadge";

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function Reports() {
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    listContracts()
      .then((data) => setContracts(data.filter((c) => c.status === "completed")))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="loading">
        <Loader2 className="spin" size={24} style={{ marginRight: "var(--space-2)" }} />
        Chargement…
      </div>
    );
  }

  if (error) return <div className="alert alert-error">{error}</div>;

  if (contracts.length === 0) {
    return (
      <div className="empty-state">
        <FileCheck />
        <h3>Aucun rapport disponible</h3>
        <p>Les rapports apparaissent ici une fois la revue terminée et le rapport généré.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Rapports</h1>
        <p>Consultez les rapports d'analyse finalisés.</p>
      </div>
      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Nom du contrat</th>
              <th>Risque global</th>
              <th>Date</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {contracts.map((c) => (
              <tr key={c.contract_id}>
                <td>{c.filename}</td>
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
                <td>
                  <Link to={`/report/${c.contract_id}`} className="btn-text">
                    Ouvrir le rapport
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
