#!/usr/bin/env python3
"""Move test-fixture contracts out of production storage.

Before tests/conftest.py's isolated_storage fixture existed, running pytest
wrote real ContractState files into clauseguard-app/backend/storage/ — the
same directory the app serves /api/contracts from. This script finds those
leftovers and moves (never deletes) them out of the way.

Usage:
    python scripts/cleanup_storage.py              # dry run (default): list matches only
    python scripts/cleanup_storage.py --apply       # move matches + filter audit_log.jsonl

Matching rules (a contract is flagged if ANY apply):
  1. Its filename is one used by a pytest upload fixture (grepped from
     tests/*.py — see DEFINITE_TEST_FILENAMES below). A human would not name
     a real contract "contrat.txt" or "activity-test.txt".
  2. Its filename starts with "contrat_test_e2e" AND it was uploaded today.
     This name is also used for real manual e2e demo runs, so only today's
     uploads are treated as leftovers from a just-run pytest session.
  3. Its analysis_result (or raw_analysis_response) carries the exact
     fingerprint of tests/sample_finding.json's mock clause (clause_id
     "ART_1" / clause_text "Le Prestataire est seul responsable de ses
     employés.") — this is the fixture used by nearly every test that mocks
     the analysis flow, and it does not occur in real platform output.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE_DIR = BACKEND_DIR / "storage"

# Upload filenames used by pytest fixtures across tests/*.py (grep:
# grep -rohE '"[a-zA-Z0-9_. -]+\.(txt|pdf|docx)"' tests/*.py). A real user
# would never happen to name an upload exactly one of these.
DEFINITE_TEST_FILENAMES = {
    "activity-test.txt",
    "big.txt",
    "c.pdf",
    "c.txt",
    "contrat.txt",
    "contrat_accents.txt",
    "contrat_cp1252.txt",
    "contrat_crlf.txt",
    "contrat_e2e.txt",
    "empty.txt",
    "list-test.txt",
    "random.txt",
    "test.txt",
    "test1.pdf",
}

# Also used for real manual e2e demo runs — only flagged when uploaded today.
DATE_CONDITIONAL_PREFIXES = ("contrat_test_e2e",)

MOCK_CLAUSE_ID = "ART_1"
MOCK_CLAUSE_TEXT = "Le Prestataire est seul responsable de ses employés."


def _has_mock_signature(data: dict) -> bool:
    findings = (data.get("analysis_result") or {}).get("audited_findings") or []
    for f in findings:
        if f.get("clause_id") == MOCK_CLAUSE_ID and f.get("clause_text") == MOCK_CLAUSE_TEXT:
            return True
    raw = data.get("raw_analysis_response") or ""
    return MOCK_CLAUSE_TEXT in raw


def _match_reason(data: dict, today: str) -> str | None:
    filename = (data.get("filename") or "").strip()

    if filename in DEFINITE_TEST_FILENAMES:
        return f"filename={filename!r}"

    if filename.startswith(DATE_CONDITIONAL_PREFIXES):
        created = (data.get("created_at") or "")[:10]
        if created == today:
            return f"filename={filename!r}; uploaded_today={created}"

    if _has_mock_signature(data):
        return "mock_analysis_signature(clause_id=ART_1)"

    return None


def _dashboard_counts(storage_dir: Path) -> dict:
    total = 0
    by_status: dict[str, int] = {}
    for path in storage_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        total += 1
        by_status[data.get("status", "?")] = by_status.get(data.get("status", "?"), 0) + 1
    return {"total_contracts": total, "by_status": by_status}


def _filter_audit_log(audit_log_path: Path, matched_ids: set[str]) -> tuple[int, int]:
    """Drop audit lines attributable to a matched contract_id.

    Note: only human-decision lines carry a top-level contract_id today —
    system lines (critic_scored, report_payload_size, ...) don't reference
    a contract at all in the current schema, so we also fall back to a
    substring match against the raw line as best effort.
    """
    backup_path = audit_log_path.with_suffix(audit_log_path.suffix + ".bak")
    shutil.copy2(audit_log_path, backup_path)
    cleaned_path = audit_log_path.with_name("audit_log.cleaned.jsonl")

    kept: list[str] = []
    dropped = 0
    for raw_line in audit_log_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue

        contract_id = entry.get("contract_id") or ""
        if contract_id in matched_ids or any(cid in line for cid in matched_ids):
            dropped += 1
            continue
        kept.append(line)

    content = "\n".join(kept) + ("\n" if kept else "")
    cleaned_path.write_text(content, encoding="utf-8")
    shutil.copy2(cleaned_path, audit_log_path)
    return len(kept), dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Move matched files (default: dry-run, list only)")
    parser.add_argument("--storage-dir", default=str(DEFAULT_STORAGE_DIR), help="Storage directory to clean")
    args = parser.parse_args(argv)

    storage_dir = Path(args.storage_dir).resolve()
    archive_dir = storage_dir / "_archive_tests"
    audit_log_path = storage_dir / "audit_log.jsonl"
    today = datetime.now(timezone.utc).date().isoformat()

    print(f"Storage dir : {storage_dir}")
    print(f"Today (UTC) : {today}")
    print(f"Mode        : {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    print("=== BEFORE ===")
    before = _dashboard_counts(storage_dir)
    print(json.dumps(before, indent=2, ensure_ascii=False))
    print()

    matches: list[tuple[Path, str, str]] = []
    unreadable = 0
    for path in sorted(storage_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            unreadable += 1
            print(f"SKIP (unreadable, left in place): {path.name}: {exc}")
            continue
        reason = _match_reason(data, today)
        if reason:
            matches.append((path, data.get("contract_id", path.stem), reason))

    print(f"=== MATCHES: {len(matches)} of {before['total_contracts']} contracts ===")
    for path, contract_id, reason in matches:
        print(f"  {path.name}  [{reason}]")
    print()

    if not args.apply:
        print(f"Dry run only — {len(matches)} file(s) would move to {archive_dir.name}/.")
        print("Re-run with --apply to actually move them and filter the audit log.")
        return 0

    archive_dir.mkdir(parents=True, exist_ok=True)
    for path, _contract_id, _reason in matches:
        shutil.move(str(path), str(archive_dir / path.name))
    print(f"Moved {len(matches)} file(s) to {archive_dir}")

    if audit_log_path.exists():
        matched_ids = {contract_id for _, contract_id, _ in matches}
        kept, dropped = _filter_audit_log(audit_log_path, matched_ids)
        print(
            f"Audit log: kept {kept} line(s), dropped {dropped}. "
            f"Backup: {audit_log_path.name}.bak — filtered copy: audit_log.cleaned.jsonl"
        )
    else:
        print("No audit_log.jsonl present, nothing to filter.")

    print()
    print("=== AFTER ===")
    after = _dashboard_counts(storage_dir)
    print(json.dumps(after, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
