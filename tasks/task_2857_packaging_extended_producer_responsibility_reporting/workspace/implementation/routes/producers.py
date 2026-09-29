"""Producer endpoints (PRD 3.1)."""
from flask import Blueprint

import calc
import store
import validation as v
from auth import OFFICER, PRO_ADMIN, REGULATOR, endpoint, must, new_row, touch
from envelope import ok, ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, str_filter

bp = Blueprint("producers", __name__)


@bp.post("/epr/producers")
@endpoint([REGULATOR])
def create_producer():
    body = v.body()
    legal_name = v.req_str(body, "legal_name")
    parent_id = v.opt_str(body, "parent_producer_id", allow_empty=False)
    brand_owner = v.req_bool(body, "brand_owner_flag")
    importer = v.req_bool(body, "importer_of_record_flag")
    licensor = v.req_bool(body, "domestic_licensor_flag")
    revenue = v.req_int(body, "annual_gross_revenue_usd", minimum=0)
    contact_email = v.req_str(body, "contact_email")
    if parent_id is not None:
        must("producers", parent_id)
    row = new_row(
        "producers",
        {
            "legal_name": legal_name,
            "parent_producer_id": parent_id,
            "brand_owner_flag": brand_owner,
            "importer_of_record_flag": importer,
            "domestic_licensor_flag": licensor,
            "annual_gross_revenue_usd": revenue,
            "contact_email": contact_email,
            "status": "DRAFT",
            "obligated_party_role": "UNDETERMINED",
            "annual_packaging_weight_kg": calc.ZERO_KG,
            "determination_stale": False,
            "assessed_fee_balance_cents": 0,
        },
    )
    return ok_entity(row, 201)


@bp.get("/epr/producers/<pid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def get_producer(pid):
    return ok_entity(must("producers", pid))


@bp.get("/epr/producers")
@endpoint([REGULATOR, PRO_ADMIN])
def list_producers():
    parent_id = str_filter("parent_producer_id")
    status = enum_filter("status", v.PRODUCER_STATUSES)
    role_filter = enum_filter("obligated_party_role", v.OBLIGATED_PARTY_ROLES)
    rows = store.values("producers")
    if parent_id is not None:
        rows = [r for r in rows if r["parent_producer_id"] == parent_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if role_filter is not None:
        rows = [r for r in rows if r["obligated_party_role"] == role_filter]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/producers/<pid>/determine-obligation")
@endpoint([REGULATOR])
def determine_obligation(pid):
    producer = must("producers", pid)
    if producer["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "The producer is not in DRAFT.")
    actives = [s for s in calc.skus_of(pid) if s["status"] == "ACTIVE"]
    if not actives:
        fail("ERR_PRODUCER_HAS_NO_ACTIVE_SKUS")
    if producer["brand_owner_flag"]:
        role_value = "BRAND_OWNER"
    elif producer["importer_of_record_flag"]:
        role_value = "IMPORTER"
    elif producer["domestic_licensor_flag"]:
        role_value = "DOMESTIC_LICENSOR"
    else:
        role_value = "NOT_OBLIGATED"
    producer["obligated_party_role"] = role_value
    producer["status"] = "OBLIGATION_DETERMINED"
    producer["annual_packaging_weight_kg"] = calc.producer_weight(pid)
    producer["determination_stale"] = False
    touch(producer)
    return ok_entity(producer)


@bp.post("/epr/producers/<pid>/restate-revenue")
@endpoint([REGULATOR])
def restate_revenue(pid):
    body = v.body()
    revenue = v.req_int(body, "annual_gross_revenue_usd", minimum=0)
    v.req_str(body, "reason")
    producer = must("producers", pid)
    if producer["status"] != "OBLIGATION_DETERMINED":
        fail("ERR_INVALID_STATE", "The producer is not in OBLIGATION_DETERMINED.")
    producer["annual_gross_revenue_usd"] = revenue
    producer["status"] = "DRAFT"
    producer["obligated_party_role"] = "UNDETERMINED"
    producer["determination_stale"] = False
    touch(producer)
    # CASCADE hop 1/2/3 (PRD 3.1)
    for registration in calc.registrations_of(pid):
        if registration["status"] not in ("SUBMITTED", "ACTIVE"):
            continue
        registration["status"] = "SUSPENDED"
        registration["suspension_reason"] = "PRODUCER_REDETERMINATION_REQUIRED"
        registration["exemption_status"] = "UNDETERMINED"
        touch(registration)
        for report in calc.reports_of(registration["id"]):
            if report["submission_status"] == "DRAFT":
                report["submission_status"] = "BLOCKED"
                touch(report)
        calc.set_posture(registration)
    return ok_entity(producer)
