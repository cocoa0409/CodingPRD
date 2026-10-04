"""Citator scoring and citation normalization (PRD 2.6, 3.1)."""

from constants import CITATOR_WEIGHTS, SIGNAL_RED_MIN, SIGNAL_YELLOW_MIN
from db import store, touch


def normalize_citation(raw):
    """citation_normalization: trim, uppercase (ASCII), strip every '.',
    collapse every internal whitespace run to a single space.
    "123 F.3d  456" -> "123 F3D 456"."""
    trimmed = raw.strip()
    uppered = trimmed.upper()
    dotless = uppered.replace(".", "")
    return " ".join(dotless.split())


def eligible_references(document_id):
    """The eligible set of PRD 2.6: ACTIVE references citing this document whose
    citing document is both PUBLISHED and PUBLIC."""
    rows = []
    for ref in store.references.values():
        if ref["cited_document_id"] != document_id or ref["status"] != "ACTIVE":
            continue
        citing = store.documents.get(ref["citing_document_id"])
        if citing is None:
            continue
        if citing["ingestion_status"] != "PUBLISHED" or citing["visibility_status"] != "PUBLIC":
            continue
        rows.append(ref)
    return rows


def compute_citator(doc):
    """Return (score, signal) for a document. Score is always derived from the
    live eligible set; signal follows the override when one is pinned."""
    score = 0
    for ref in eligible_references(doc["id"]):
        score += CITATOR_WEIGHTS[ref["treatment"]][ref["depth"]]
    if doc["editorial_override_signal"] is not None:
        signal = doc["editorial_override_signal"]
    elif score >= SIGNAL_RED_MIN:
        signal = "RED"
    elif score >= SIGNAL_YELLOW_MIN:
        signal = "YELLOW"
    else:
        signal = "GREEN"
    return score, signal


def recompute_citator(doc):
    """Store freshly computed citator fields; a change counts as a mutation and
    bumps the document version (PRD 2.5 / publish and removal cascades)."""
    score, signal = compute_citator(doc)
    if score != doc["citator_score"] or signal != doc["citator_signal"]:
        doc["citator_score"] = score
        doc["citator_signal"] = signal
        touch(doc)
