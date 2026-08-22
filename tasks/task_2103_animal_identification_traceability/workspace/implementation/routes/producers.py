"""Producer registration, enrolment and award reverse-lookup (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import derive
import shape
from authz import PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST, require_roles, require_owner
from db import base_record, store, touch
from errors import conflict, invalid_state
from respond import success
from routes._common import page, producer_or_404
from serialize import public

bp = Blueprint("producers", __name__)


@bp.post("/producers")
def create_producer():
    uid, role = require_roles(PROGRAM_ADMIN)
    body = shape.body()
    legal_name = shape.s_str(body, "legal_name")
    contact_email = shape.s_str(body, "contact_email", contains="@")
    state_code = shape.s_str(body, "state_code", pattern=shape.STATE_CODE_RE)
    privacy_level = shape.s_enum(body, "privacy_level", ("STANDARD", "RESTRICTED"),
                                 required=False) or "STANDARD"

    rec = base_record()
    rec.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "state_code": state_code,
        "privacy_level": privacy_level,
        "enrollment_status": "NOT_ENROLLED",
        "enrolled_at": None,
        "enrolled_head_count": 0,
        "incentive_tier": "TIER_0",
        "on_time_movement_pct": Decimal("100.00"),
        "incentive_balance_cents": 0,
        "lifetime_clawback_cents": 0,
    })
    store.producers[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/producers/<producer_id>")
def read_producer(producer_id):
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST)
    return success(public(producer_or_404(producer_id)))


@bp.post("/producers/<producer_id>/enroll")
def enroll_producer(producer_id):
    uid, role = require_roles(PRODUCER)
    producer = producer_or_404(producer_id)
    # Band 6 - enrolment is self-service only.
    require_owner(uid == producer["id"])
    # Band 10 - ENROLLED may not re-enrol.
    if producer["enrollment_status"] not in ("NOT_ENROLLED", "LAPSED"):
        raise invalid_state("Producer is already enrolled")
    # Band 11 - at least one ACTIVE premises.
    if not any(p["registration_status"] == "ACTIVE"
               for p in derive.producer_premises(producer["id"])):
        raise conflict("ERR_NO_ACTIVE_PREMISES",
                       "Enrolment requires at least one ACTIVE premises")
    head, tier = derive.compute_head_and_tier(producer["id"])
    producer.update({
        "enrollment_status": "ENROLLED",
        "enrolled_at": store.now(),
        "enrolled_head_count": head,
        "incentive_tier": tier,
    })
    touch(producer)
    return success(public(producer))


@bp.get("/producers/<producer_id>/incentive-awards")
def list_producer_awards(producer_id):
    require_roles(PRODUCER, PROGRAM_ADMIN)
    limit, offset = shape.pagination_params()
    producer = producer_or_404(producer_id)
    status = shape.q("status")
    rows = [a for a in store.awards.values() if a["producer_id"] == producer["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return page(rows, limit, offset)
