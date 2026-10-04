"""Removal-order apply/reverse cascades (PRD 3.8).

The cascade runs four levels deep: order -> document visibility -> citing
references -> cited-document citator recompute; plus permanent headnote
retraction on apply (never compensated on reverse).
"""

from db import store, touch
from services.citator import recompute_citator


def apply_order(order):
    """RECEIVED -> APPLIED: document leaves PUBLIC (SEAL->SEALED /
    REMOVE->REMOVED) with the full retroactive cascade."""
    doc = store.documents[order["document_id"]]
    order["status"] = "APPLIED"
    touch(order)

    doc["visibility_status"] = "SEALED" if order["scope"] == "SEAL" else "REMOVED"

    for ref in store.references.values():
        if ref["citing_document_id"] == doc["id"] and ref["status"] == "ACTIVE":
            ref["status"] = "INACTIVE"
            ref["deactivated_by_order_id"] = order["id"]
            touch(ref)
            cited = store.documents.get(ref["cited_document_id"])
            if cited is not None:
                recompute_citator(cited)

    for headnote in store.headnotes.values():
        if headnote["document_id"] == doc["id"] and headnote["status"] == "PUBLISHED":
            headnote["status"] = "RETRACTED"
            touch(headnote)

    touch(doc)


def reverse_order(order):
    """APPLIED -> REVERSED: visibility back to PUBLIC, references flipped back
    to ACTIVE (exactly the order's deactivated set), citator recomputed.
    Retracted headnotes are NOT restored."""
    doc = store.documents[order["document_id"]]
    order["status"] = "REVERSED"
    touch(order)

    doc["visibility_status"] = "PUBLIC"

    for ref in store.references.values():
        if ref["deactivated_by_order_id"] == order["id"]:
            ref["status"] = "ACTIVE"
            ref["deactivated_by_order_id"] = None
            touch(ref)
            cited = store.documents.get(ref["cited_document_id"])
            if cited is not None:
                recompute_citator(cited)

    touch(doc)
