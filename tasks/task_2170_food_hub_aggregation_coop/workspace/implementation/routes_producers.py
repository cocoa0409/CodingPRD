"""Producer onboarding, food-safety documents, review and member equity."""

from flask import Blueprint

import cascade
import domain
import fetch
import serializers
from constants import (DOC_DECISIONS, DOC_TYPES, MAX_REVIEW_CYCLES,
                       REQUIRED_DOC_TYPES, REVIEW_DECISIONS, ROLE_BOARD,
                       ROLE_COMPLIANCE, ROLE_HUB_ADMIN, ROLE_PRODUCER)
from envelope import list_response, ok
from errors import ApiError
from store import base_record, db, sorted_records, touch
from validators import (actor, body, endpoint, opt_int, opt_string, req_datetime,
                        req_enum, req_int, req_string)
import validators

bp = Blueprint("producers", __name__)


# ---------------------------------------------------------------------------
# POST /producers
# ---------------------------------------------------------------------------

@bp.post("/producers")
@endpoint([ROLE_HUB_ADMIN])
def create_producer():
    payload = body()
    legal_name = req_string(payload, "legal_name", min_len=1, max_len=120)
    region_code = req_string(payload, "region_code", min_len=3, max_len=3,
                             pattern=validators.REGION_RE)
    contact_email = req_string(payload, "contact_email")
    if "@" not in contact_email:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'contact_email' must contain an at sign.")

    producer = base_record({
        "legal_name": legal_name,
        "region_code": region_code,
        "contact_email": contact_email,
        "onboarding_status": "DRAFT",
        "food_safety_tier": "TIER_NONE",
        "compliance_ok": False,
        "review_cycles": 0,
        "suspension_count": 0,
        "paid_in_capital_cents": 0,
        "voting_shares": 0,
        "patronage_volume_cents": 0,
        "shrink_charge_cents": 0,
        "retained_patronage_cents": 0,
    })
    db.producers[producer["id"]] = producer
    return ok(serializers.producer_out(producer), 201)


@bp.get("/producers/<producer_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_COMPLIANCE, ROLE_PRODUCER, ROLE_BOARD])
def read_producer(producer_id):
    producer = fetch.get("producer", producer_id)
    return ok(serializers.producer_out(producer))


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------

@bp.get("/producers/<producer_id>/documents")
@endpoint([ROLE_HUB_ADMIN, ROLE_COMPLIANCE, ROLE_PRODUCER])
def list_documents(producer_id):
    fetch.get("producer", producer_id)
    from flask import request
    records = domain.producer_documents(producer_id)
    doc_type = request.args.get("doc_type")
    status = request.args.get("status")
    if doc_type is not None:
        records = [r for r in records if r["doc_type"] == doc_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, serializers.document_out)


@bp.post("/producers/<producer_id>/documents")
@endpoint([ROLE_PRODUCER, ROLE_HUB_ADMIN])
def attach_document(producer_id):
    producer = fetch.get("producer", producer_id)            # rung 4
    payload = body()
    doc_type = req_enum(payload, "doc_type", DOC_TYPES)      # rung 6
    issued_on = req_datetime(payload, "issued_on")
    expires_on = req_datetime(payload, "expires_on")
    if expires_on <= issued_on:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'expires_on' must be strictly after 'issued_on'.")
    user_id, role = actor()
    if role == ROLE_PRODUCER and user_id != producer["id"]:   # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    doc = base_record({
        "producer_id": producer["id"],
        "doc_type": doc_type,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "SUBMITTED",
        "adjudicated_by_user_id": None,
        "rejection_reason": None,
    })
    db.documents[doc["id"]] = doc
    return ok(serializers.document_out(doc), 201)


# ---------------------------------------------------------------------------
# POST /producers/{id}/application
# ---------------------------------------------------------------------------

@bp.post("/producers/<producer_id>/application")
@endpoint([ROLE_PRODUCER, ROLE_HUB_ADMIN])
def submit_application(producer_id):
    producer = fetch.get("producer", producer_id)            # rung 4
    user_id, role = actor()
    if role == ROLE_PRODUCER and user_id != producer["id"]:   # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if producer["onboarding_status"] not in ("DRAFT", "CHANGES_REQUESTED"):  # rung 10
        raise ApiError("ERR_INVALID_PRODUCER_STATE")

    # rung 14 — completeness gate, not adjudication
    held = set()
    for doc in domain.producer_documents(producer["id"]):
        if doc["status"] in ("SUBMITTED", "VERIFIED"):
            held.add(doc["doc_type"])
    if any(t not in held for t in REQUIRED_DOC_TYPES):
        raise ApiError("ERR_MISSING_REQUIRED_DOCUMENTS")

    producer["onboarding_status"] = "SUBMITTED"
    touch(producer)
    return ok(serializers.producer_out(producer))


# ---------------------------------------------------------------------------
# POST /producers/{id}/review
# ---------------------------------------------------------------------------

def _verified_adjudicators(producer_id):
    out = set()
    for doc in db.documents.values():
        if doc["producer_id"] != producer_id:
            continue
        if doc["status"] != "VERIFIED":
            continue
        if doc["adjudicated_by_user_id"]:
            out.add(doc["adjudicated_by_user_id"])
    return out


def _has_open_allocation(producer_id):
    product_ids = set(p["id"] for p in domain.producer_products(producer_id))
    for alloc in db.allocations.values():
        if alloc["product_id"] in product_ids and alloc["status"] in ("RESERVED", "STAGED"):
            return True
    return False


@bp.post("/producers/<producer_id>/review")
@endpoint([ROLE_COMPLIANCE, ROLE_HUB_ADMIN])
def review_producer(producer_id):
    producer = fetch.get("producer", producer_id)                 # rung 4
    payload = body()
    decision = req_enum(payload, "decision", REVIEW_DECISIONS)    # rung 6
    opt_string(payload, "note")
    user_id, role = actor()

    # rung 8 — decision authority
    if decision in ("APPROVE", "REQUEST_CHANGES") and role != ROLE_COMPLIANCE:
        raise ApiError("ERR_DECISION_ROLE_MISMATCH")
    if decision in ("SUSPEND", "REINSTATE", "TERMINATE") and role != ROLE_HUB_ADMIN:
        raise ApiError("ERR_DECISION_ROLE_MISMATCH")

    status = producer["onboarding_status"]

    # rung 10 — transition legality
    if decision in ("APPROVE", "REQUEST_CHANGES") and status != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PRODUCER_STATE")
    if decision == "SUSPEND" and status != "ACTIVE":
        raise ApiError("ERR_INVALID_PRODUCER_STATE")
    if decision == "REINSTATE" and status != "SUSPENDED":
        raise ApiError("ERR_INVALID_PRODUCER_STATE")
    if decision == "TERMINATE":
        if status not in ("ACTIVE", "SUSPENDED", "CHANGES_REQUESTED"):
            raise ApiError("ERR_INVALID_PRODUCER_STATE")
        if _has_open_allocation(producer["id"]):
            raise ApiError("ERR_INVALID_PRODUCER_STATE")

    # rung 12 — segregation of duties
    if decision == "APPROVE" and user_id in _verified_adjudicators(producer["id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # rung 13 — producer standing
    if decision in ("APPROVE", "REINSTATE") and not domain.compliance_ok(producer):
        raise ApiError("ERR_PRODUCER_NOT_COMPLIANT")

    # rung 17 — review-cycle ceiling
    if decision == "REQUEST_CHANGES" and producer["review_cycles"] >= MAX_REVIEW_CYCLES:
        raise ApiError("ERR_REVIEW_CYCLE_LIMIT")

    if decision == "APPROVE":
        producer["onboarding_status"] = "ACTIVE"
        domain.evaluate_compliance(producer)
        touch(producer)
    elif decision == "REQUEST_CHANGES":
        producer["onboarding_status"] = "CHANGES_REQUESTED"
        producer["review_cycles"] += 1
        touch(producer)
    elif decision == "SUSPEND":
        cascade.suspend_producer(producer)
    elif decision == "REINSTATE":
        producer["onboarding_status"] = "ACTIVE"
        domain.evaluate_compliance(producer)
        touch(producer)
    else:
        cascade.terminate_producer(producer, status)

    return ok(serializers.producer_out(producer))


# ---------------------------------------------------------------------------
# POST /producer-documents/{id}/adjudication
# ---------------------------------------------------------------------------

@bp.post("/producer-documents/<document_id>/adjudication")
@endpoint([ROLE_COMPLIANCE])
def adjudicate_document(document_id):
    doc = fetch.get("document", document_id)                     # rung 4
    payload = body()
    decision = req_enum(payload, "decision", DOC_DECISIONS)      # rung 6
    reason = opt_string(payload, "rejection_reason")
    user_id, _role = actor()

    # rung 10 — a document is adjudicated exactly once
    if doc["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_DOCUMENT_STATE")
    if decision == "VERIFY" and doc["expires_on"] <= domain.now_instant():
        raise ApiError("ERR_INVALID_DOCUMENT_STATE")

    producer = db.producers.get(doc["producer_id"])

    if decision == "VERIFY":
        doc["status"] = "VERIFIED"
        doc["adjudicated_by_user_id"] = user_id
        touch(doc)
        for sibling in domain.producer_documents(doc["producer_id"]):
            if sibling["id"] == doc["id"]:
                continue
            if sibling["doc_type"] != doc["doc_type"]:
                continue
            if sibling["status"] in ("VERIFIED", "REJECTED", "EXPIRED"):
                sibling["status"] = "SUPERSEDED"
                touch(sibling)
    else:
        doc["status"] = "REJECTED"
        doc["adjudicated_by_user_id"] = user_id
        doc["rejection_reason"] = reason
        touch(doc)

    # the first adjudication advances the producer BEFORE compliance is recomputed
    if producer is not None:
        if producer["onboarding_status"] == "SUBMITTED":
            producer["onboarding_status"] = "UNDER_REVIEW"
            touch(producer)
        domain.evaluate_compliance(producer)

    return ok(serializers.document_out(doc))


# ---------------------------------------------------------------------------
# POST /producers/{id}/equity-contributions
# ---------------------------------------------------------------------------

@bp.post("/producers/<producer_id>/equity-contributions")
@endpoint([ROLE_HUB_ADMIN])
def record_equity(producer_id):
    producer = fetch.get("producer", producer_id)                # rung 4
    payload = body()
    amount = req_int(payload, "amount_cents", minimum=0)         # rung 6
    opt_string(payload, "memo")

    producer["paid_in_capital_cents"] += amount
    producer["voting_shares"] = domain.voting_shares(producer)
    touch(producer)
    return ok(serializers.producer_out(producer), 201)
