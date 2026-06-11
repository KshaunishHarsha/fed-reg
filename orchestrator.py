"""
Unified pipeline orchestrator.

Calls Phase 1 → Phase 2 → Phase 3 sequentially via direct function calls.
No HTTP requests between phases — all in-process.

Phase 3 interface (confirmed from phase_3/ source):
  phase_3.validator.validate_blob(doc_number: str, xml_blob: str)
      → ValidationResult (.passed: bool, .error_detail: Optional[str])   [sync]

  phase_3.persistence.persist_validated_document(doc_number: str)
      → PersistenceResult (.promoted: bool, .was_cached: bool)            [async]

  phase_3.digest_query.fetch_digest_rows(run_date: date)
      → List[DigestRow]                                                    [async]

  phase_3.digest_builder.build_digest(rows: List[DigestRow], digest_date: date)
      → DigestPackage (.html_body, .text_body, .section_a/b/c_count,
                       .is_zero_result)                                    [sync — no await]
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
        # Actual Phase 3 interfaces (confirmed from phase_3/router.py):
        #   validate_blob(doc_number, xml_blob) -> ValidationResult (.passed, .error_detail)
        #   persist_validated_document(doc_number) -> PersistenceResult  [async]
        from phase_3.validator import validate_blob
        from phase_3.persistence import persist_validated_document

        result = validate_blob(doc.document_number, xml_blob)
        if not result.passed:
            return False, result.error_detail

        await persist_validated_document(doc.document_number)
        return True, None

    except ImportError:
        # Phase 3 not yet wired into this process — don't block Phase 2
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
        print(f"[Orchestrator] No relevant documents for {run_date} — skipping Phase 2")
        phase2_result = {"processed": 0, "failed": 0, "total": 0}
    else:
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
        # Actual Phase 3 interfaces (confirmed from phase_3/router.py):
        #   fetch_digest_rows(run_date) -> List[Row]  [async]
        #   build_digest(rows, run_date) -> DigestPackage  [sync]
        from phase_3.digest_query import fetch_digest_rows
        from phase_3.digest_builder import build_digest

        rows = await fetch_digest_rows(run_date)
        package = build_digest(rows, run_date)
        print(
            f"[Orchestrator] Phase 3 digest built — "
            f"A:{package.section_a_count} B:{package.section_b_count} "
            f"C:{package.section_c_count} (zero={package.is_zero_result})"
        )
        
        # Send personalized digest per subscriber based on their category preferences.
        # Cleanup fires ONLY after all sends complete.
        import os
        _demo = os.environ.get("DEMO", "").lower() == "true"

        try:
            from phase_3.digest_builder import build_digest
            from phase_3.mailing_list import get_active_recipients_with_prefs
            from phase_3.mail_test import send_test_digest

            subscribers = await get_active_recipients_with_prefs()
            if subscribers:
                all_sent = []
                all_failed = []

                for subscriber in subscribers:
                    email = subscriber["email"]
                    allowed_categories = subscriber["allowed_categories"]
                    allowed_agencies = subscriber.get("allowed_agencies", set())

                    if package.is_zero_result:
                        # Zero-result path — send the circuit-breaker email unfiltered
                        personalized_package = package
                    else:
                        # Filter each section by category AND agency preferences.
                        # A document passes if:
                        #   - its regulation_category is in the subscriber's allowed categories
                        #     (or allowed_categories is empty = no restriction)
                        #   - AND at least one of its publishing agencies matches an allowed
                        #     agency (or allowed_agencies is empty = no restriction)
                        # Returns (kept, drop_reason). drop_reason is "category" or
                        # "agency" so we can see WHY a doc was filtered, not just that
                        # it was. Empty pref set = no restriction on that axis.
                        def _keep(e, cats=allowed_categories, agencies=allowed_agencies):
                            # Edge case: If a user unchecks ALL categories and ALL agencies, 
                            # they are effectively pausing their subscription. Send nothing.
                            if not cats and not agencies:
                                return False, "none"
                            
                            if cats and (e.regulation_category or "other").lower() not in cats:
                                return False, "category"
                            if agencies and not any(
                                canon.lower() in actual.lower()
                                for canon in agencies
                                for actual in (e.agency_names or [])
                            ):
                                return False, "agency"
                            return True, ""

                        drops = {"category": 0, "agency": 0, "none": 0}

                        def _filter(entries):
                            kept = []
                            for e in entries:
                                ok, reason = _keep(e)
                                if ok:
                                    kept.append(e)
                                else:
                                    drops[reason] += 1
                            return kept

                        filtered_a = _filter(package._section_a)
                        filtered_b = _filter(package._section_b)
                        filtered_c = _filter(package._section_c)

                        total_in = len(package._section_a) + len(package._section_b) + len(package._section_c)
                        total_kept = len(filtered_a) + len(filtered_b) + len(filtered_c)
                        print(
                            f"[Orchestrator] Filter for {email}: kept {total_kept}/{total_in} "
                            f"(A:{len(filtered_a)} B:{len(filtered_b)}) — "
                            f"dropped {drops['category']} on category, {drops['agency']} on agency. "
                            f"prefs: {len(allowed_categories)} categories, {len(allowed_agencies)} agencies."
                        )

                        # If they have NO matching docs at all, skip — don't send a blank email
                        if not filtered_a and not filtered_b and not filtered_c:
                            print(f"[Orchestrator] No matching docs for {email} — skipping.")
                            continue

                        # Re-build a personalized digest package for this subscriber
                        personalized_package = build_digest(
                            filtered_a + filtered_b + filtered_c,
                            package.digest_date,
                            _pre_classified=True,
                            _section_a=filtered_a,
                            _section_b=filtered_b,
                            _section_c=filtered_c,
                        )

                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        _executor,
                        lambda p=personalized_package, e=email: send_test_digest(
                            html_body=p.html_body,
                            text_body=p.text_body,
                            digest_date=p.digest_date,
                            recipients=[e],
                        ),
                    )
                    all_sent.extend(result["sent"])
                    all_failed.extend(result["failed"])

                print(f"[Orchestrator] Emails sent to {all_sent} (failed: {all_failed})")

                # DEMO cleanup — only reachable after all sends complete
                if _demo:
                    try:
                        from phase_3.db import get_session_factory
                        from sqlalchemy import text as sa_text
                        session_factory = get_session_factory()
                        async with session_factory() as session:
                            await session.execute(sa_text("DELETE FROM documents;"))
                            await session.commit()
                        print("[Orchestrator] DEMO cleanup — documents table cleared for next run.")
                    except Exception as e:
                        print(f"[Orchestrator] DEMO cleanup failed: {e}")

            else:
                print("[Orchestrator] No active subscribers — email skipped, DEMO cleanup skipped.")
        except Exception as e:
            import traceback
            print(f"[Orchestrator] Failed to send email: {type(e).__name__}: {e}")
            traceback.print_exc()


        # TODO Step 4: platform_handoff.send_digest(package)
        digest_built = True

    except ImportError as exc:
        print(f"[Orchestrator] Phase 3 digest skipped (not yet available): {exc}")

    return {
        "run_date": run_date.isoformat(),
        "phase1_confirmed": confirmed,
        "phase2": phase2_result,
        "digest_built": digest_built,
    }