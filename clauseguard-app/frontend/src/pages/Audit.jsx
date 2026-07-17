import { useEffect, useState } from "react";
import { ScrollText, Loader2 } from "lucide-react";
import { getActivity } from "../api";

function formatTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function Audit() {
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getActivity(50)
      .then((data) => setActivity(data))
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

  if (activity.length === 0) {
    return (
      <div className="empty-state">
        <ScrollText />
        <h3>Aucune entrée d'audit</h3>
        <p>L'activité apparaîtra après le premier traitement de contrat.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Journal d'audit</h1>
        <p>Historique des actions et appels au moteur d'analyse.</p>
      </div>
      <div className="card">
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          {activity.map((entry, idx) => (
            <div key={idx} style={{ display: "flex", gap: "var(--space-4)" }}>
              <div style={{ textAlign: "right", minWidth: 90 }}>
                <div className="mono" style={{ fontSize: "0.8rem", color: "var(--color-text)" }}>
                  {formatTime(entry.timestamp)}
                </div>
                <div className="mono" style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
                  {formatDate(entry.timestamp)}
                </div>
              </div>
              <div
                style={{
                  flex: 1,
                  borderLeft: "2px solid var(--color-border)",
                  paddingLeft: "var(--space-4)",
                }}
              >
                <div style={{ fontWeight: 500, marginBottom: "var(--space-1)" }}>
                  {entry.action || entry.event || "—"}
                </div>
                {entry.actor && (
                  <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
                    Acteur : {entry.actor}
                  </div>
                )}
                {entry.detail && (
                  <div className="mono" style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
                    {entry.detail}
                  </div>
                )}
                {(entry.flow_id || entry.status !== undefined) && (
                  <div className="mono" style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "var(--space-1)" }}>
                    {entry.flow_id} {entry.latency_ms !== undefined ? `· ${entry.latency_ms} ms` : ""}{" "}
                    {entry.status !== undefined ? `· ${entry.status}` : ""}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
