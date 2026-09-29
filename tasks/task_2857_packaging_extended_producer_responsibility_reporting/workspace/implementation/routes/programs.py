"""State program and reporting period endpoints (PRD 3.3)."""
import re

from flask import Blueprint

import calc
import store
import validation as v
from auth import OFFICER, PRO_ADMIN, REGULATOR, VERIFIER, endpoint, must, new_row
from envelope import ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, page_window, str_filter

bp = Blueprint("programs", __name__)

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


@bp.post("/epr/state-programs")
@endpoint([REGULATOR])
def create_state_program():
    body = v.body()
    state_code = v.req_str(body, "state_code")
    if not _STATE_CODE_RE.match(state_code):
        fail("ERR_INVALID_REQUEST", "Field 'state_code' must be two uppercase letters.")
    obligation_basis = v.req_enum(body, "obligation_basis", v.OBLIGATION_BASES)
    eco_mod_policy = v.req_enum(body, "eco_mod_policy", v.ECO_MOD_POLICIES)
    rounding_order = v.req_enum(body, "fee_rounding_order", v.FEE_ROUNDING_ORDERS)
    revenue_threshold = v.req_int(body, "small_producer_revenue_threshold_usd")
    if revenue_threshold <= 0:
        fail("ERR_INVALID_REQUEST", "Field 'small_producer_revenue_threshold_usd' must be > 0.")
    tonnage_threshold = v.req_decimal(
        body, "small_producer_tonnage_threshold_kg", 3, exclusive_min=0
    )
    categories = v.req_list(body, "exempt_product_categories")
    for entry in categories:
        if entry not in v.PRODUCT_CATEGORIES:
            fail(
                "ERR_INVALID_REQUEST",
                "Field 'exempt_product_categories' holds an unknown product category.",
            )
    verification_threshold = v.req_decimal(
        body, "verification_required_threshold_kg", 3, exclusive_min=0
    )
    deadline = v.req_instant(body, "registration_deadline")
    for existing in store.values("state_programs"):
        if existing["state_code"] == state_code:
            fail("ERR_INVALID_REQUEST", "state_code '%s' already exists." % state_code)
    row = new_row(
        "state_programs",
        {
            "state_code": state_code,
            "obligation_basis": obligation_basis,
            "eco_mod_policy": eco_mod_policy,
            "fee_rounding_order": rounding_order,
            "small_producer_revenue_threshold_usd": revenue_threshold,
            "small_producer_tonnage_threshold_kg": tonnage_threshold,
            "exempt_product_categories": list(categories),
            "verification_required_threshold_kg": verification_threshold,
            "registration_deadline": store.fmt_instant(deadline),
            "_registration_deadline": deadline,
        },
    )
    return ok_entity(row, 201)


@bp.get("/epr/state-programs/<pid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def get_state_program(pid):
    return ok_entity(must("state_programs", pid))


@bp.get("/epr/state-programs")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def list_state_programs():
    state_code = str_filter("state_code")
    basis = enum_filter("obligation_basis", v.OBLIGATION_BASES)
    rows = store.values("state_programs")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if basis is not None:
        rows = [r for r in rows if r["obligation_basis"] == basis]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/state-programs/<pid>/reporting-periods")
@endpoint([REGULATOR])
def create_reporting_period(pid):
    body = v.body()
    label = v.req_str(body, "period_label")
    data_start = v.req_date(body, "data_start")
    data_end = v.req_date(body, "data_end")
    submission_open = v.req_instant(body, "submission_open")
    submission_deadline = v.req_instant(body, "submission_deadline")
    correction_days = v.req_int(body, "correction_window_days", minimum=1)
    program = must("state_programs", pid)
    siblings = [
        p for p in store.values("reporting_periods") if p["state_program_id"] == program["id"]
    ]
    for existing in siblings:
        if existing["period_label"] == label:
            fail("ERR_INVALID_REQUEST", "period_label '%s' already exists in this program." % label)
    # Half-open [data_start, data_end): touching windows are allowed (PRD 3.3).
    for existing in siblings:
        if data_start < existing["_data_end"] and existing["_data_start"] < data_end:
            fail("ERR_PERIOD_WINDOW_OVERLAP")
    row = new_row(
        "reporting_periods",
        {
            "state_program_id": program["id"],
            "period_label": label,
            "data_start": data_start.isoformat(),
            "data_end": data_end.isoformat(),
            "submission_open": store.fmt_instant(submission_open),
            "submission_deadline": store.fmt_instant(submission_deadline),
            "correction_window_days": correction_days,
            "_data_start": data_start,
            "_data_end": data_end,
            "_submission_open": submission_open,
            "_submission_deadline": submission_deadline,
        },
    )
    return ok_entity(row, 201)


@bp.get("/epr/state-programs/<pid>/reporting-periods")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def list_reporting_periods(pid):
    page_window()
    program = must("state_programs", pid)
    rows = [
        p for p in store.values("reporting_periods") if p["state_program_id"] == program["id"]
    ]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.get("/epr/reporting-periods/<rid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def get_reporting_period(rid):
    return ok_entity(must("reporting_periods", rid))
