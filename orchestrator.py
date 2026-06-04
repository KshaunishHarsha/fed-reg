"""
Unified pipeline orchestrator.

Calls Phase 1 → Phase 2 → Phase 3 sequentially via direct function calls.
No HTTP requests between phases — all in-process.

Phase 3 interface assumed (Phase 3 team must expose these):
  phase_3.validator.validate(xml_blob: str) -> object with .is_valid (bool) + .error_detail (str)
  phase_3.persistence.save_ingested(doc: DocumentRecord, xml_blob: str) -> None  [async]
  phase_3.digest_query.get_documents_for_date(run_date: date) -> List[dict]       [async]
  phase_3.digest_builder.build_digest(docs: List[dict]) -> DigestPackage          [async]
"""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_cls
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Thread executor for running Phase 1's synchronous code inside an async context
_executor = ThreadPoolExecutor(max_workers=1)


# ── Phase 3 ingest (called per document from Phase 2) ──────────────────────

async def _phase3_validate_and_save(doc, xml_blob: str) -> tuple[bool, Optional[str]]:
    """Call Phase 3's validator + persistence directly. No HTTP.

    Returns (True, None) on success or (False, error_detail) on validation failure.
    If Phase 3 modules aren't available yet, passes through silently.
    """
    try:
        from phase_3.validator import validate
        from phase_3.persistence import save_ingested

        result = validate(xml_blob)
        if not result.is_valid:
            return False, result.error_detail

        await save_ingested(doc, xml_blob)
        return True, None

    except ImportError:
        # Phase 3 not yet integrated — don't block Phase 2 processing
        return True, None
    except Exception as exc:
        return False, str(exc)


async def _phase2_ingest_callback(doc, xml_blob: str) -> None:
    """Injected into Phase 2 as the per-document delivery function.

    Drives the Phase 3 validation + correction loop entirely within this process.
    Phase 2 never imports Phase 3; the orchestrator is the only bridge.
    """
    from phase_2.pipeline import handle_correction

    current_blob = xml_blob

    for attempt in range(3):  # 1 initial attempt + up to 2 corrections
        success, error_detail = await _phase3_validate_and_save(doc, current_blob)

        if success:
            return

        if attempt < 2:
            print(
                f"[Orchestrator] Phase 3 rejected {doc.document_number} "
                f"(attempt {attempt + 1}/2): {error_detail}"
            )
            new_blob = await handle_correction(doc.document_number, error_detail)
            if new_blob:
                current_blob = new_blob
            else:
                break  # Phase 2 exhausted its retries

    print(f"[Orchestrator] {doc.document_number} — Phase 3 validation failed after corrections")


# ── Full pipeline ───────────────────────────────────────────────────────────

async def run_full_pipeline(target_date: Optional[str] = None) -> dict:
    """Sequential Phase 1 → Phase 2 → Phase 3 via direct in-process calls."""
    run_date = date_cls.fromisoformat(target_date) if target_date else date_cls.today()
    print(f"\n[Orchestrator] Starting full pipeline for {run_date}")

    # ── Phase 1 ─────────────────────────────────────────────────────────────
    # Phase 1 uses supabase-py and requests (synchronous). Run in a thread.
    sys.path.insert(0, str(Path(__file__).parent / "phase_1"))
    from phase_1.pipeline import run_pipeline as phase1_run

    loop = asyncio.get_event_loop()
    phase1_docs = await loop.run_in_executor(_executor, lambda: phase1_run(run_date))
    confirmed = len(phase1_docs) if phase1_docs else 0
    print(f"[Orchestrator] Phase 1 complete — {confirmed} confirmed documents")

    if not confirmed:
        print(f"[Orchestrator] No relevant documents for {run_date} — skipping Phase 2/3")
        return {
            "run_date": run_date.isoformat(),
            "phase1_confirmed": 0,
            "phase2": {"processed": 0, "failed": 0, "total": 0},
            "digest_built": False,
        }

    # ── Phase 2 ─────────────────────────────────────────────────────────────
    # Async. The callback delivers each completed document directly to Phase 3.
    sys.path.insert(0, str(Path(__file__).parent / "phase_2"))
    from phase_2.pipeline import run_pipeline as phase2_run

    phase2_result = await phase2_run(phase3_ingest_fn=_phase2_ingest_callback)
    print(f"[Orchestrator] Phase 2 complete — {phase2_result}")

    # ── Phase 3 digest ───────────────────────────────────────────────────────
    # Build and send the daily digest from all SUMMARY_GENERATED documents.
    digest_built = False
    try:
        from phase_3.digest_query import get_documents_for_date
        from phase_3.digest_builder import build_digest

        docs = await get_documents_for_date(run_date)
        if docs:
            package = await build_digest(docs)
            print(f"[Orchestrator] Phase 3 digest built — {len(docs)} documents")
            # TODO Step 4: await platform_handoff.send_digest(package)
            digest_built = True
        else:
            print(f"[Orchestrator] No summarized documents for digest on {run_date}")

    except ImportError as exc:
        print(f"[Orchestrator] Phase 3 digest skipped (not yet available): {exc}")

    return {
        "run_date": run_date.isoformat(),
        "phase1_confirmed": confirmed,
        "phase2": phase2_result,
        "digest_built": digest_built,
    }