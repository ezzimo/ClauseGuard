import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FileCheck, Loader2, Search } from "lucide-react";
import { listContracts } from "../api";
import RiskBadge from "../components/RiskBadge";
import Pagination from "../components/Pagination";
import { formatDate } from "../utils/contracts";

const PAGE_SIZE = 15;

export default function Reports() {
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    listContracts()
      .then((data) => setContracts(data.filter((c) => c.status === "completed")))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return [...contracts]
      .filter((c) => !query || (c.filename || "").toLowerCase().includes(query))
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
  }, [contracts, search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageItems = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const handleSearchChange = (value) => {
    setSearch(value);
    setPage(1);
  };

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

      <div className="card" style={{ marginBottom: "var(--space-4)" }}>
        <div style={{ position: "relative", maxWidth: 360 }}>
          <Search
            size={16}
            style={{
              position: "absolute",
              left: "var(--space-3)",
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--color-text-muted)",
              pointerEvents: "none",
            }}
          />
          <input
            type="text"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Rechercher par nom de contrat…"
            style={{ paddingLeft: "var(--space-8)", width: "100%" }}
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <Search />
          <h3>Aucun résultat</h3>
          <p>Aucun rapport ne correspond à votre recherche.</p>
        </div>
      ) : (
        <div className="card" style={{ overflow: "hidden" }}>
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
              {pageItems.map((c) => (
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
          <Pagination page={currentPage} pageCount={pageCount} onChange={setPage} />
        </div>
      )}
    </div>
  );
}
