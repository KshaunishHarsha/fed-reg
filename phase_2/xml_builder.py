import xml.etree.ElementTree as ET

from phase_2.models import DocumentSummary


def build_xml(summary: DocumentSummary) -> str:
    """Serialize a DocumentSummary to the canonical XML blob Phase 3 expects.
    Deterministic — no LLM involvement.
    """
    root = ET.Element("regulatory_document_summary")

    ET.SubElement(root, "plain_language_summary").text = summary.plain_language_summary
    ET.SubElement(root, "advocacy_relevance").text = summary.advocacy_relevance

    actions_el = ET.SubElement(root, "suggested_actions")
    for action in summary.suggested_actions:
        ET.SubElement(actions_el, "action").text = action

    points_el = ET.SubElement(root, "suggested_talking_points")
    for point in summary.suggested_talking_points:
        ET.SubElement(points_el, "point").text = point

    deadlines_el = ET.SubElement(root, "deadlines")
    ET.SubElement(deadlines_el, "comment_close_date").text = (
        summary.comment_close_date.isoformat() if summary.comment_close_date else ""
    )
    ET.SubElement(deadlines_el, "hearing_date").text = (
        summary.hearing_date.isoformat() if summary.hearing_date else ""
    )
    ET.SubElement(deadlines_el, "effective_date").text = (
        summary.effective_date.isoformat() if summary.effective_date else ""
    )

    ET.SubElement(root, "disclaimer").text = summary.disclaimer

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode")
