import { ChevronLeft, ChevronRight } from "lucide-react";

export default function Pagination({ page, pageCount, onChange }) {
  if (pageCount <= 1) return null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: "var(--space-3)",
        padding: "var(--space-4)",
      }}
    >
      <span style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
        Page {page} sur {pageCount}
      </span>
      <button
        type="button"
        className="btn-secondary"
        style={{ padding: "var(--space-2) var(--space-3)" }}
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        aria-label="Page précédente"
      >
        <ChevronLeft size={16} />
      </button>
      <button
        type="button"
        className="btn-secondary"
        style={{ padding: "var(--space-2) var(--space-3)" }}
        onClick={() => onChange(page + 1)}
        disabled={page >= pageCount}
        aria-label="Page suivante"
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}
