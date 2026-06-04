from models import DocumentRecord
import boilerplate_pruner


def route_and_prepare(doc: DocumentRecord) -> tuple[int, str]:
    """Return (tier, prepared_text) for a document.

    Tier 1 (< 15 pages):  use abstract directly.
    Tier 2 (15-50 pages): fetch HTML, strip boilerplate, use pruned text.
    Tier 3 (> 50 pages):  use context_block already stored in DB — never re-fetch PDF.

    Falls back to abstract, then title if the primary source is empty.
    """
    page_length = doc.page_length or 0

    if page_length > 50:
        text = _tier3_text(doc)
        return 3, text

    if page_length >= 15:
        text = _tier2_text(doc)
        return 2, text

    return 1, _fallback(doc, doc.abstract)


def _tier3_text(doc: DocumentRecord) -> str:
    if doc.context_block:
        return doc.context_block
    # Degrade gracefully if Phase 1 didn't assemble a context_block
    return _fallback(doc, doc.abstract)


def _tier2_text(doc: DocumentRecord) -> str:
    pruned = boilerplate_pruner.prune(doc.document_number)
    if pruned:
        return pruned
    return _fallback(doc, doc.abstract)


def _fallback(doc: DocumentRecord, primary: str | None) -> str:
    return primary or doc.title