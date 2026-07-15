import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getContract, submitDecisions, generateReport } from "../api";
import RiskBadge, { normalize } from "../components/RiskBadge";

export default function Review() {
  const { contractId } = useParams();
  const navigate = useNavigate();
  const [contract, setContract] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [decisions, setDecisions] = useState({});
  const [comments, setComments] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    getContract(contractId)
      .then((data) => {
        setContract(data);
        const existing = {};
        const existingComments = {};
        (data.human_decisions || []).forEach((d) => {
          existing[d.clause_id] = d.action;
          existingComments[d.clause_id] = d.comment || "";
        });
        setDecisions(existing);
        setComments(existingComments);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [contractId]);

  if (loading) return <div className="loading">Chargement...</div>;
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!contract?.analysis_result) return <div className="alert">Aucune analyse disponible.</div>;

  const findings = contract.analysis_result.audited_findings;

  const pending = findings.filter((f) => {
    const norm = normalize(f.corrected_risk_level);
    return (norm === "orange" || norm === "rouge") && !decisions[f.clause_id];
  });

  const canGenerate = pending.length === 0;

  const toggleExpand = (id) => {
    setExpanded({ ...expanded, [id]: !expanded[id] });
  };

  const setDecision = (clauseId, action) => {
    setDecisions({ ...decisions, [clauseId]: action });
  };

  const saveDecisions = async () => {
    const payload = Object.entries(decisions).map(([clause_id, action]) => ({
      clause_id,
      action,
      comment: comments[clause_id] || "",
    }));
    try {
      await submitDecisions(contractId, payload);
      const updated = await getContract(contractId);
      setContract(updated);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleGenerateReport = async () => {
    await saveDecisions();
    setGenerating(true);
    try {
      await generateReport(contractId);
      navigate(`/report/${contractId}`);
    } catch (err) {
      setError(err.message);
      setGenerating(false);
    }
  };

  return (
    <div className="review-page">
      <h1>Revue des clauses</h1>
      <p className="subtitle">
        Examinez chaque clause signalée et validez les décisions pour les risques ORANGE et ROUGE.
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="clauses-table-wrapper">
        <table className="clauses-table">
          <thead>
            <tr>
              <th>Référence</th>
              <th>Type</th>
              <th>Risque corrigé</th>
              <th>Décision</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f) => {
              const norm = normalize(f.corrected_risk_level);
              const requiresDecision = norm === "orange" || norm === "rouge";
              const decision = decisions[f.clause_id];
              return (
                <>
                  <tr key={f.clause_id} className={`risk-row risk-${norm}`}>
                    <td>{f.reference}</td>
                    <td>{f.type}</td>
                    <td>
                      <RiskBadge level={f.corrected_risk_level} />
                    </td>
                    <td>
                      {decision ? (
                        <span className="decision-label">{decision}</span>
                      ) : requiresDecision ? (
                        <span className="pending-label">En attente</span>
                      ) : (
                        <span className="na-label">-</span>
                      )}
                    </td>
                    <td>
                      <button
                        className="btn-text"
                        onClick={() => toggleExpand(f.clause_id)}
                      >
                        {expanded[f.clause_id] ? "Réduire" : "Détails"}
                      </button>
                    </td>
                  </tr>
                  {expanded[f.clause_id] && (
                    <tr className="expanded-row">
                      <td colSpan={5}>
                        <div className="clause-detail">
                          <div className="detail-section">
                            <h4>Texte de la clause</h4>
                            <p>{f.clause_text}</p>
                          </div>
                          <div className="detail-section">
                            <h4>Résumé du risque</h4>
                            <p>{f.risk_summary}</p>
                          </div>
                          {f.source_excerpts?.length > 0 && (
                            <div className="detail-section">
                              <h4>Extraits sources</h4>
                              {f.source_excerpts.map((ex, i) => (
                                <blockquote key={i}>{ex}</blockquote>
                              ))}
                            </div>
                          )}
                          {f.proposed_rewrite && (
                            <div className="detail-section">
                              <h4>Proposition de réécriture</h4>
                              <p className="rewrite">{f.proposed_rewrite}</p>
                            </div>
                          )}
                          <div className="detail-section">
                            <h4>Motif de l'audit</h4>
                            <p>{f.audit_reason}</p>
                          </div>
                          {requiresDecision && (
                            <div className="decision-panel">
                              <h4>Action requise</h4>
                              <div className="action-buttons">
                                {["approve", "reject", "reclassify", "request_lawyer_review"].map(
                                  (action) => (
                                    <button
                                      key={action}
                                      type="button"
                                      className={decision === action ? "active" : ""}
                                      onClick={() => setDecision(f.clause_id, action)}
                                    >
                                      {action === "approve" && "Approuver"}
                                      {action === "reject" && "Rejeter"}
                                      {action === "reclassify" && "Reclasser"}
                                      {action === "request_lawyer_review" && "Avis avocat"}
                                    </button>
                                  )
                                )}
                              </div>
                              <textarea
                                placeholder="Commentaire optionnel..."
                                value={comments[f.clause_id] || ""}
                                onChange={(e) =>
                                  setComments({ ...comments, [f.clause_id]: e.target.value })
                                }
                              />
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="review-footer">
        <div className="pending-info">
          <strong>{pending.length}</strong> clause{pending.length > 1 ? "s" : ""} en attente de
          décision
        </div>
        <button
          className="btn-primary"
          disabled={!canGenerate || generating}
          onClick={handleGenerateReport}
        >
          {generating ? "Génération..." : "Générer le rapport final"}
        </button>
      </div>
    </div>
  );
}
