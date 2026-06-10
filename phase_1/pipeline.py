from datetime import date
from typing import List

import config
from ai_verification import verify_document
from database import is_already_processed, log_audit_entry, save_confirmed_document
from ingestion import fetch_documents
from keyword_filter import apply_keyword_filter
from models import ConfirmedDocument


def run_pipeline(target_date=None, dry_run: bool = False) -> List[ConfirmedDocument]:
    run_date = target_date or date.today()
    print(f"\n[Pipeline] Starting run for {run_date}")
    # Keywords are loaded from keywords.yaml at config import time — no DB call needed.

    if dry_run:
        print("[Pipeline] DRY RUN — no AI calls or DB writes")

    # Layer 1
    raw_docs = fetch_documents(run_date)
    print(f"[Layer 1] {len(raw_docs)} documents after agency + type filter")

    # Layer 2 + 2a
    filtered_docs = []
    for doc in raw_docs:
        result = apply_keyword_filter(doc)
        if result:
            filtered_docs.append(result)
    print(f"[Layer 2] {len(filtered_docs)} documents after keyword filter")

    if dry_run:
        print(f"\n[Dry Run] Would send {len(filtered_docs)} documents to Layer 3 (AI):")
        for doc in filtered_docs:
            print(f"  [{doc.confidence}] {doc.document_number} — {doc.title}")
        return []

    # Layer 3
    confirmed_docs = []
    cache_hits = 0
    for doc in filtered_docs:
        if is_already_processed(doc.document_number):
            cache_hits += 1
            log_audit_entry(
                doc.document_number, doc.title,
                doc.confidence, None, None,
                "cache hit", True, run_date,
            )
            continue

        result = verify_document(doc)
        log_audit_entry(
            doc.document_number, doc.title,
            doc.confidence, None,
            result.is_relevant, result.confidence_reason,
            False, run_date,
        )

        if result.is_relevant:
            # Hybrid relevancy: a strong anchor match (keyword confidence HIGH) is
            # trusted as HIGH; weaker context-only docs take the AI's MEDIUM/LOW grade.
            relevancy = "HIGH" if doc.confidence == "HIGH" else result.relevancy
            data = doc.model_dump()
            data["confidence"] = relevancy  # overwrite keyword tier with relevancy grade
            confirmed = ConfirmedDocument(
                **data,
                is_relevant=result.is_relevant,
                regulation_category=result.regulation_category,
                filter_reason=result.confidence_reason,
            )
            save_confirmed_document(confirmed)
            confirmed_docs.append(confirmed)

    # Summary
    print(f"[Layer 3] {len(confirmed_docs)} confirmed relevant documents")
    print(f"[Cache]   {cache_hits} documents skipped (already processed)")
    print(f"\n[Results]")
    for doc in confirmed_docs:
        print(f"  ✓ [{doc.regulation_category}] {doc.title}")
        if doc.comments_close_on:
            print(f"    Comment deadline: {doc.comments_close_on}")

    return confirmed_docs


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")

    parser = argparse.ArgumentParser(description="Federal Register Sentinel — Phase 1 Pipeline")
    parser.add_argument("--date", type=str, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Skip AI calls and DB writes; print what would be processed")
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else None
    run_pipeline(target, dry_run=args.dry_run)
