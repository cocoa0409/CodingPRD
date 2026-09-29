"""Funder grant and supportive-services endpoints — PRD sections 3.8 and 3.9."""

from flask import Blueprint, request

from common import list_result, match_filters, READ_ROLES, resolve
from domain import (
    GRANT_CATEGORIES, OUTCOME_VARIANTS, REVIEW_DECISIONS, SETTLE_STATUSES,
    SUPPORT_CATEGORIES, SUPPORT_MAX_LINE_ITEMS, INFO_MAX_ROUNDS, pct1, rows,
)
from envelope import created, ok
from errors import ApiError, fail
from ledger import (
    ledger_view, outcome_report, participant_charged_cents, price_request,
    recompute_grant_by_id,
)
from store import db, new_row, now_str, public, touch
from validation import (
    body, caller_id, opt_str, present, req_enum, req_enum_array, req_int,
    req_num, req_str, require_roles,
)

bp = Blueprint("grants", __name__)

ANALYST = ["FunderAnalyst"]
MANAGER = ["CaseManager"]
DIRECTOR = ["ProgramDirector"]
MONEY_READERS = ["ProgramDirector", "FunderAnalyst"]


def _validate_line_items(payload, required=True):
    if "line_items" not in payload or payload["line_items"] is None:
        if required:
            fail("ERR_VALIDATION", "line_items is required")
        return None
    items = payload["line_items"]
    if not isinstance(items, list):
        fail("ERR_VALIDATION", "line_items must be an array")
    if len(items) < 1:
        fail("ERR_VALIDATION", "line_items must carry at least one element")
    if len(items) > SUPPORT_MAX_LINE_ITEMS:
        fail("ERR_VALIDATION",
             "line_items may carry at most %d elements" % SUPPORT_MAX_LINE_ITEMS)
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", "each line item must be an object")
        description = req_str(item, "description")
        unit_cost = req_int(item, "unit_cost_cents", minimum=1)
        quantity = req_int(item, "quantity", minimum=1, maximum=20)
        cleaned.append({
            "description": description,
            "unit_cost_cents": unit_cost,
            "quantity": quantity,
        })
    return cleaned


# --------------------------------------------------------------------------
# grants
# --------------------------------------------------------------------------

@bp.post("/grants")
def create_grant():
    require_roles(ANALYST)
    payload = body()
    funder_name = req_str(payload, "funder_name")
    program_year = req_int(payload, "program_year", minimum=2000, maximum=2100)
    authorized = req_int(payload, "authorized_cents", minimum=1)
    allowed = req_enum_array(payload, "allowed_categories", GRANT_CATEGORIES)
    cap = req_int(payload, "per_participant_cap_cents", minimum=1)
    benchmark = req_num(payload, "retention_benchmark_pct", minimum=0,
                        maximum=100)

    row = new_row(
        funder_name=funder_name,
        program_year=program_year,
        authorized_cents=authorized,
        allowed_categories=allowed,
        per_participant_cap_cents=cap,
        retention_benchmark_pct=pct1(benchmark),
        committed_cents=0,
        disbursed_cents=0,
        available_cents=authorized,
        open_request_count=0,
        funding_posture="OPEN",
    )
    db.grants[row["id"]] = row
    return created(public(row))


@bp.get("/grants/<grant_id>")
def read_grant(grant_id):
    require_roles(READ_ROLES)
    grant = resolve("grants", db.grants, grant_id)
    return ok(public(grant))


@bp.get("/grants")
def list_grants():
    require_roles(READ_ROLES)
    result = match_filters(rows(db.grants), string_filters=["funding_posture"],
                           int_filters=["program_year"])
    return list_result(result)


@bp.get("/grants/<grant_id>/ledger")
def read_ledger(grant_id):
    require_roles(MONEY_READERS)
    grant = resolve("grants", db.grants, grant_id)
    return ok(ledger_view(grant))


@bp.get("/grants/<grant_id>/outcome-report")
def read_outcome_report(grant_id):
    require_roles(MONEY_READERS)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "COHORT"
    if variant not in OUTCOME_VARIANTS:
        fail("ERR_VALIDATION", "variant must be COHORT or EXIT_BASED")
    grant = resolve("grants", db.grants, grant_id)
    return ok(outcome_report(grant, variant))


# --------------------------------------------------------------------------
# support requests
# --------------------------------------------------------------------------

@bp.post("/support-requests")
def create_support_request():
    require_roles(MANAGER)
    payload = body()
    participant_id = req_str(payload, "participant_id")
    grant_id = req_str(payload, "grant_id")
    category = req_enum(payload, "category", SUPPORT_CATEGORIES)
    expected_version = req_int(payload, "expected_grant_version")
    line_items = _validate_line_items(payload)
    justification = req_str(payload, "justification")

    if participant_id not in db.participants:
        fail("ERR_PARTICIPANT_NOT_FOUND", "participant_id matches no participant")
    if grant_id not in db.grants:
        fail("ERR_GRANT_NOT_FOUND", "grant_id matches no grant")
    participant = db.participants[participant_id]
    grant = db.grants[grant_id]

    if expected_version != grant["version"]:
        fail("ERR_STALE_GRANT_VERSION",
             "The grant has been modified since it was last read")
    if participant["suspension_status"] == "SUSPENDED":
        fail("ERR_PARTICIPANT_SUSPENDED",
             "A suspended participant may not receive supportive services")
    if grant["funding_posture"] == "EXHAUSTED":
        fail("ERR_GRANT_EXHAUSTED", "The grant is exhausted")
    if category not in (grant["allowed_categories"] or []):
        fail("ERR_CATEGORY_NOT_FUNDABLE",
             "The grant does not fund this support category")

    priced, requested, admin_fee, total = price_request(category, line_items)
    prior = participant_charged_cents(grant_id, participant_id)
    if prior + total > int(grant["per_participant_cap_cents"]):
        fail("ERR_PARTICIPANT_CAP_EXCEEDED",
             "The participant's cumulative charges would exceed the grant cap")

    row = new_row(
        participant_id=participant_id,
        grant_id=grant_id,
        category=category,
        line_items=priced,
        justification=justification,
        requested_cents=requested,
        admin_fee_cents=admin_fee,
        total_charge_cents=total,
        status="SUBMITTED",
        info_rounds_used=0,
        submitted_by_user_id=caller_id(),
        reviewed_by_user_id=None,
        settled_by_user_id=None,
        review_note=None,
        settlement_note=None,
        deferred_at=None,
        promoted_at=None,
    )
    db.support_requests[row["id"]] = row
    recompute_grant_by_id(grant_id, allow_waterfall=False)
    return created(public(row))


@bp.get("/support-requests/<request_id>")
def read_support_request(request_id):
    require_roles(READ_ROLES)
    row = resolve("support_requests", db.support_requests, request_id)
    return ok(public(row))


@bp.get("/support-requests")
def list_support_requests():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.support_requests),
        string_filters=["participant_id", "grant_id", "status"],
    )
    if request.args.get("status") == "DEFERRED":
        result = sorted(result, key=lambda r: (r["deferred_at"] or "",
                                               r["created_at"], r["_seq"]))
    return list_result(result)


@bp.post("/support-requests/<request_id>/review")
def review_support_request(request_id):
    require_roles(DIRECTOR)
    payload = body()
    decision = req_enum(payload, "decision", REVIEW_DECISIONS)
    review_note = opt_str(payload, "review_note")

    row = resolve("support_requests", db.support_requests, request_id)
    status = row["status"]
    if decision == "DENIED":
        if status not in ("SUBMITTED", "INFO_REQUESTED"):
            fail("ERR_SUPPORT_REQUEST_INVALID_STATE",
                 "Only an open request may be denied")
    elif status != "SUBMITTED":
        fail("ERR_SUPPORT_REQUEST_INVALID_STATE",
             "Only a SUBMITTED request may be reviewed this way")

    if caller_id() == row["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The submitter may not review their own request")

    if decision == "INFO_REQUESTED":
        if int(row["info_rounds_used"]) >= INFO_MAX_ROUNDS:
            fail("ERR_INFO_ROUNDS_EXHAUSTED",
                 "No information-request rounds remain")

    row["reviewed_by_user_id"] = caller_id()
    row["review_note"] = review_note
    if decision == "INFO_REQUESTED":
        row["status"] = "INFO_REQUESTED"
    elif decision == "DENIED":
        row["status"] = "DENIED"
    else:
        grant = db.grants.get(row["grant_id"])
        covered = (grant is not None
                   and grant["funding_posture"] != "EXHAUSTED"
                   and int(grant["available_cents"])
                   >= int(row["total_charge_cents"]))
        if covered:
            row["status"] = "APPROVED"
        else:
            row["status"] = "DEFERRED"
            row["deferred_at"] = now_str()
    touch(row)
    recompute_grant_by_id(row["grant_id"], allow_waterfall=False)
    return ok(public(row))


@bp.post("/support-requests/<request_id>/resubmit")
def resubmit_support_request(request_id):
    require_roles(MANAGER)
    payload = body()
    line_items = _validate_line_items(payload, required=False)
    justification = None
    if present(payload, "justification"):
        justification = req_str(payload, "justification")

    row = resolve("support_requests", db.support_requests, request_id)
    if row["status"] != "INFO_REQUESTED":
        fail("ERR_SUPPORT_REQUEST_INVALID_STATE",
             "Only an INFO_REQUESTED request may be resubmitted")
    if int(row["info_rounds_used"]) >= INFO_MAX_ROUNDS:
        fail("ERR_INFO_ROUNDS_EXHAUSTED",
             "No information-request rounds remain")

    grant = db.grants.get(row["grant_id"])
    if line_items is not None:
        if grant is not None and row["category"] not in (
                grant["allowed_categories"] or []):
            fail("ERR_CATEGORY_NOT_FUNDABLE",
                 "The grant does not fund this support category")
        priced, requested, admin_fee, total = price_request(
            row["category"], line_items)
        if grant is not None:
            prior = participant_charged_cents(
                row["grant_id"], row["participant_id"],
                exclude_request_id=row["id"])
            if prior + total > int(grant["per_participant_cap_cents"]):
                fail("ERR_PARTICIPANT_CAP_EXCEEDED",
                     "The participant's cumulative charges would exceed the cap")
        row["line_items"] = priced
        row["requested_cents"] = requested
        row["admin_fee_cents"] = admin_fee
        row["total_charge_cents"] = total
    if justification is not None:
        row["justification"] = justification

    row["status"] = "SUBMITTED"
    row["info_rounds_used"] = int(row["info_rounds_used"]) + 1
    touch(row)
    recompute_grant_by_id(row["grant_id"], allow_waterfall=False)
    return ok(public(row))


@bp.post("/support-requests/<request_id>/settle")
def settle_support_request(request_id):
    require_roles(DIRECTOR)
    payload = body()
    to_status = req_enum(payload, "to_status", SETTLE_STATUSES)
    settlement_note = opt_str(payload, "settlement_note")

    row = resolve("support_requests", db.support_requests, request_id)
    status = row["status"]
    legal = ((status == "APPROVED" and to_status in ("DISBURSED", "VOIDED"))
             or (status == "DEFERRED" and to_status == "VOIDED"))
    if not legal:
        fail("ERR_SUPPORT_REQUEST_INVALID_STATE",
             "That settlement transition is not declared")

    if row["reviewed_by_user_id"] is not None and caller_id() == row[
            "reviewed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The reviewer may not settle their own decision")

    row["settled_by_user_id"] = caller_id()
    row["settlement_note"] = settlement_note
    row["status"] = to_status
    touch(row)
    waterfall = (to_status == "VOIDED" and status == "APPROVED")
    recompute_grant_by_id(row["grant_id"], allow_waterfall=waterfall)
    return ok(public(row))
