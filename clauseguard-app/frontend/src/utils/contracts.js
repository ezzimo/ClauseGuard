const STATUS_LABELS = {
  uploaded: { label: "Importé", class: "badge-unknown" },
  processing: { label: "Analyse…", class: "badge-accent" },
  awaiting_human_review: { label: "En revue", class: "badge-orange" },
  pending_human_validation: { label: "Validation", class: "badge-orange" },
  decisions_recorded: { label: "Décisions", class: "badge-vert" },
  report_processing: { label: "Rapport…", class: "badge-accent" },
  completed: { label: "Terminé", class: "badge-vert" },
  parse_error: { label: "Erreur", class: "badge-rouge" },
  flow_error: { label: "Erreur", class: "badge-rouge" },
  report_error: { label: "Erreur", class: "badge-rouge" },
  error: { label: "Erreur", class: "badge-rouge" },
};

function statusMeta(status) {
  return STATUS_LABELS[status] || { label: status, class: "badge-unknown" };
}

const STATUS_FILTER_GROUPS = {
  tous: () => true,
  importe: (status) => status === "uploaded",
  analyse: (status) => status === "processing",
  revue: (status) =>
    ["awaiting_human_review", "pending_human_validation", "decisions_recorded", "report_processing"].includes(
      status
    ),
  termine: (status) => status === "completed",
  erreur: (status) => ["parse_error", "flow_error", "report_error", "error"].includes(status),
};

const STATUS_FILTER_OPTIONS = [
  { value: "tous", label: "Tous" },
  { value: "importe", label: "Importé" },
  { value: "analyse", label: "En analyse" },
  { value: "revue", label: "En revue" },
  { value: "termine", label: "Terminé" },
  { value: "erreur", label: "Erreur" },
];

function matchesStatusFilter(status, filterValue) {
  const predicate = STATUS_FILTER_GROUPS[filterValue] || STATUS_FILTER_GROUPS.tous;
  return predicate(status);
}

function contractRoute(contract) {
  if (contract.status === "completed") return `/report/${contract.contract_id}`;
  return `/review/${contract.contract_id}`;
}

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

export { statusMeta, STATUS_FILTER_OPTIONS, matchesStatusFilter, contractRoute, formatDate, formatTime };
