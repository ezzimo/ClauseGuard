function normalize(level) {
  const key = level?.toLowerCase() || "";
  if (key === "vert" || key === "green" || key === "faible" || key === "low") return "vert";
  if (key === "orange" || key === "moyen" || key === "medium" || key === "modéré" || key === "modere")
    return "orange";
  if (key === "rouge" || key === "red" || key === "élevé" || key === "eleve" || key === "high" || key === "critique" || key === "critical")
    return "rouge";
  return "unknown";
}

export default function RiskBadge({ level, label }) {
  const normalized = normalize(level);
  const text = label || level || "Inconnu";
  return <span className={`risk-badge badge-${normalized}`}>{text}</span>;
}

export { normalize };
