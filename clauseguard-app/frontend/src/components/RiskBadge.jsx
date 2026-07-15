const RISK_COLORS = {
  vert: "#16a34a",
  orange: "#ea580c",
  rouge: "#dc2626",
  unknown: "#64748b",
};

function normalize(level) {
  const key = level?.toLowerCase() || "";
  if (key === "vert" || key === "green" || key === "faible" || key === "low") return "vert";
  if (key === "orange" || key === "moyen" || key === "medium" || key === "modéré") return "orange";
  if (key === "rouge" || key === "red" || key === "élevé" || key === "high" || key === "critique" || key === "critical") return "rouge";
  return "unknown";
}

export default function RiskBadge({ level, label }) {
  const normalized = normalize(level);
  const color = RISK_COLORS[normalized];
  const text = label || level || "Inconnu";
  return (
    <span className="risk-badge" style={{ backgroundColor: color, color: "#fff" }}>
      {text}
    </span>
  );
}

export { normalize };
