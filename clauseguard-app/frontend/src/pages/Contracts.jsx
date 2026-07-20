import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileText, Loader2, Search, Upload } from "lucide-react";
import { listContracts } from "../api";
import RiskBadge from "../components/RiskBadge";
import Pagination from "../components/Pagination";
import { statusMeta, STATUS_FILTER_OPTIONS, matchesStatusFilter, contractRoute, formatDate } from "../utils/contracts";

const PAGE_SIZE = 15;

export default function Contracts() {
  const navigate = useNavigate();
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("tous");
  const [page, setPage] = useState(1);

  useEffect(() => {
    listContracts()
      .then((data) => setContracts(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return [...contracts]
      .filter((c) => matchesStatusFilter(c.status, statusFilter))
      .filter((c) => {
        if (!query) return true;
        return (
          (c.filename || "").toLowerCase().includes(query) ||
          (c.contract_id || "").toLowerCase().includes(query)
        );
      })
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
  }, [contracts, search, statusFilter]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageItems = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const handleSearchChange = (value) => {
    setSearch(value);
    setPage(1);
  };

  const handleStatusChange = (value) => {
    setStatusFilter(value);
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
        <FileText />
        <h3>Aucun contrat analysé</h3>
        <p>Commencez par téléverser votre premier contrat. Formats : PDF, DOCX, TXT.</p>
        <button type="button" className="btn-primary" style={{ marginTop: "var(--space-4)" }} onClick={() => navigate("/upload")}>
          <Upload size={18} /> Téléverser un contrat
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1>Contrats</h1>
          <p>Tous les contrats analysés par ClauseGuard.</p>
        </div>
        <button type="button" className="btn-primary" onClick={() => navigate("/upload")}>
          <Upload size={18} /> Nouveau contrat
        </button>
      </div>

      <div className="card" style={{ marginBottom: "var(--space-4)", display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 260px" }}>
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
            placeholder="Rechercher par nom ou identifiant…"
            style={{ paddingLeft: "var(--space-8)", width: "100%" }}
          />
        </div>
        <select value={statusFilter} onChange={(e) => handleStatusChange(e.target.value)} style={{ flex: "0 0 200px" }}>
          {STATUS_FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <Search />
          <h3>Aucun résultat</h3>
          <p>Aucun contrat ne correspond à votre recherche ou au filtre sélectionné.</p>
        </div>
      ) : (
        <div className="card" style={{ overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Nom</th>
                <th>Statut</th>
                <th>Risque global</th>
                <th>Décisions</th>
                <th>Mis à jour</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((c) => {
                const meta = statusMeta(c.status);
                return (
                  <tr
                    key={c.contract_id}
                    onClick={() => navigate(contractRoute(c))}
                    style={{ cursor: "pointer" }}
                  >
                    <td>
                      <div>{c.filename}</div>
                      <div className="mono" style={{ color: "var(--color-text-muted)", fontSize: "0.75rem" }}>
                        {c.contract_id.slice(0, 8)}
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${meta.class}`}>{meta.label}</span>
                    </td>
                    <td>
                      {c.final_report?.overall_risk ? (
                        <RiskBadge level={c.final_report.overall_risk} />
                      ) : (
                        <span className="badge badge-unknown">—</span>
                      )}
                    </td>
                    <td>{c.human_decisions?.length || 0}</td>
                    <td style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                      {formatDate(c.updated_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination page={currentPage} pageCount={pageCount} onChange={setPage} />
        </div>
      )}
    </div>
  );
}
