"""Lenders, lender programs and targeting criteria."""

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("lenders", __name__)

READ_ROLES = ["Consumer", "LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"]
COMPLIANCE_VALUES = ("APPROVED", "SUSPENDED", "BANNED")
CRITERION_FIELDS = ("SCORE", "DTI_PCT", "UTILIZATION_PCT", "STATE_CODE")
OPERATORS = ("GTE", "LTE", "EQ", "IN")


# ---------------------------------------------------------------------------
# Lenders
# ---------------------------------------------------------------------------
@bp.route("/lenders", methods=["POST"])
def create_lender():
    require(["PlatformAdmin"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    name = data.get("lender_name")
    if not name:
        fail("ERR_INVALID_REQUEST", "lender_name is required.")
    states = data.get("states_served")
    if not isinstance(states, list) or not states:
        fail("ERR_INVALID_REQUEST", "states_served must be a non-empty array.")
    row = store.make_row({
        "lender_name": str(name),
        "compliance_status": "APPROVED",
        "states_served": [str(s).upper() for s in states],
        "status": "ONBOARDING",
    })
    store.lenders[row["id"]] = row
    return ok(models.lender(row), store.now(), 201)


@bp.route("/lenders", methods=["GET"])
def list_lenders():
    require(READ_ROLES)
    rows = list(store.lenders.values())
    compliance = request.args.get("compliance_status")
    if compliance:
        rows = [r for r in rows if r["compliance_status"] == compliance]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.lender(r) for r in window], store.now(), pagination)


@bp.route("/lenders/<lid>", methods=["GET"])
def get_lender(lid):
    require(READ_ROLES)
    row = helpers.lender(lid)
    return ok(models.lender(row), store.now())


def _cascade_ban(lender_id):
    """BANNED pauses every ACTIVE program and ineligibles its open decisions."""
    moment = store.now()
    for prog in store.lender_programs.values():
        if prog["lender_id"] != lender_id or prog["status"] != "ACTIVE":
            continue
        prog["status"] = "PAUSED"
        prog["updated_at"] = moment
        prog["version"] = int(prog.get("version", 0)) + 1
        _ineligible_decisions_of_program(prog["id"], "PROGRAM_PAUSED")


def _ineligible_decisions_of_program(program_id, reason):
    """Pausing (or a BANNED cascade) ineligibles the program's open decisions.

    ELIGIBLE decisions are set INELIGIBLE with the pause reason; decisions that
    already carried consent (PREQUALIFIED legally, CONSENTED in practice) are
    returned to INELIGIBLE with their odds restored (scaffold LenderProgram pause
    cascade).
    """
    moment = store.now()
    for dec in store.pre_qual_decisions.values():
        if dec["lender_program_id"] != program_id:
            continue
        if dec["decision_status"] not in ("ELIGIBLE", "PREQUALIFIED", "CONSENTED"):
            continue
        dec["decision_status"] = "INELIGIBLE"
        dec["reason"] = reason
        if reason == "PROGRAM_PAUSED":
            dec["modeled_odds_pct"] = None
        dec["updated_at"] = moment
        dec["version"] = int(dec.get("version", 0)) + 1


@bp.route("/lenders/<lid>/compliance-status", methods=["POST"])
def set_compliance(lid):
    require(["ComplianceOfficer", "PlatformAdmin"])
    row = helpers.lender(lid)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    value = data.get("compliance_status")
    if value not in COMPLIANCE_VALUES:
        fail("ERR_INVALID_REQUEST", "compliance_status must be APPROVED, SUSPENDED or BANNED.")
    if row["status"] == "OFFBOARDED":
        fail("ERR_INVALID_STATE_TRANSITION", "An offboarded lender cannot be updated.")
    row["compliance_status"] = value
    models.touch(row)
    if value == "BANNED":
        _cascade_ban(lid)
    return ok(models.lender(row), store.now())


@bp.route("/lenders/<lid>/activate", methods=["POST"])
def activate_lender(lid):
    require(["PlatformAdmin"])
    row = helpers.lender(lid)
    if row["status"] != "ONBOARDING":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ONBOARDING lender may be activated.")
    if row["compliance_status"] != "APPROVED":
        fail("ERR_LENDER_NOT_COMPLIANT")
    row["status"] = "ACTIVE"
    models.touch(row)
    return ok(models.lender(row), store.now())


@bp.route("/lenders/<lid>/offboard", methods=["POST"])
def offboard_lender(lid):
    require(["PlatformAdmin"])
    row = helpers.lender(lid)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE lender may be offboarded.")
    for prog in store.lender_programs.values():
        if prog["lender_id"] == lid and prog["status"] == "ACTIVE":
            fail("ERR_LENDER_HAS_ACTIVE_PROGRAM")
    row["status"] = "OFFBOARDED"
    models.touch(row)
    return ok(models.lender(row), store.now())


# ---------------------------------------------------------------------------
# Lender programs
# ---------------------------------------------------------------------------
PROGRAM_REQUIRED = ("lender_id", "product_catalog_item_id", "program_name",
                    "program_code", "min_modeled_score", "max_dti_pct",
                    "max_eligible_utilization_pct", "annual_fee_cents",
                    "intro_apr_bps", "go_live_at", "expiry_at",
                    "revenue_share_bps", "clawback_rate_bps", "clawback_days")


@bp.route("/lender-programs", methods=["POST"])
def create_program():
    require(["PlatformAdmin"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    for field in PROGRAM_REQUIRED:
        if data.get(field) in (None, ""):
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    helpers.lender(str(data["lender_id"]))
    helpers.catalog_item(str(data["product_catalog_item_id"]))
    code = str(data["program_code"])
    go_live = parse_instant(data["go_live_at"])
    expiry = parse_instant(data["expiry_at"])
    row = store.make_row({
        "lender_id": str(data["lender_id"]),
        "product_catalog_item_id": str(data["product_catalog_item_id"]),
        "program_name": str(data["program_name"]),
        "program_code": code,
        "min_modeled_score": int(data["min_modeled_score"]),
        "max_dti_pct": float(data["max_dti_pct"]),
        "max_eligible_utilization_pct": float(data["max_eligible_utilization_pct"]),
        "annual_fee_cents": int(data["annual_fee_cents"]),
        "intro_apr_bps": int(data["intro_apr_bps"]),
        "go_live_at": go_live,
        "expiry_at": expiry,
        "revenue_share_bps": int(data["revenue_share_bps"]),
        "clawback_rate_bps": int(data["clawback_rate_bps"]),
        "clawback_days": int(data["clawback_days"]),
        "status": "DRAFT",
    })
    store.lender_programs[row["id"]] = row
    return ok(models.program(row), store.now(), 201)


def parse_instant(raw):
    from datetime import datetime, timezone
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        text = str(raw).replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "An ISO 8601 instant is required.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


@bp.route("/lender-programs", methods=["GET"])
def list_programs():
    require(READ_ROLES)
    rows = list(store.lender_programs.values())
    lid = request.args.get("lender_id")
    if lid:
        rows = [r for r in rows if r["lender_id"] == lid]
    iid = request.args.get("product_catalog_item_id")
    if iid:
        rows = [r for r in rows if r["product_catalog_item_id"] == iid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.program(r) for r in window], store.now(), pagination)


@bp.route("/lender-programs/<pid>", methods=["GET"])
def get_program(pid):
    require(READ_ROLES)
    row = helpers.program(pid)
    return ok(models.program(row), store.now())


@bp.route("/lenders/<lid>/lender-programs", methods=["GET"])
def lender_programs(lid):
    require(READ_ROLES)
    helpers.lender(lid)
    rows = [p for p in store.lender_programs.values() if p["lender_id"] == lid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.program(r) for r in window], store.now(), pagination)


@bp.route("/lender-programs/<pid>/activate", methods=["POST"])
def activate_program(pid):
    require(["PlatformAdmin"])
    row = helpers.program(pid)
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT program may be activated.")
    sponsor = helpers.lender(row["lender_id"])
    if sponsor["status"] != "ACTIVE":
        fail("ERR_LENDER_NOT_ACTIVE")
    for other in store.lender_programs.values():
        if other["id"] == pid or other["status"] != "ACTIVE":
            continue
        if other["program_code"] == row["program_code"]:
            fail("ERR_PROGRAM_CODE_DUPLICATE")
    row["status"] = "ACTIVE"
    models.touch(row)
    return ok(models.program(row), store.now())


@bp.route("/lender-programs/<pid>/pause", methods=["POST"])
def pause_program(pid):
    require(["ComplianceOfficer", "PlatformAdmin"])
    row = helpers.program(pid)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE program may be paused.")
    row["status"] = "PAUSED"
    models.touch(row)
    _ineligible_decisions_of_program(pid, "PROGRAM_PAUSED")
    return ok(models.program(row), store.now())


@bp.route("/lender-programs/<pid>/resume", methods=["POST"])
def resume_program(pid):
    require(["ComplianceOfficer", "PlatformAdmin"])
    row = helpers.program(pid)
    if row["status"] != "PAUSED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PAUSED program may be resumed.")
    sponsor = helpers.lender(row["lender_id"])
    if sponsor["status"] != "ACTIVE":
        fail("ERR_LENDER_NOT_ACTIVE")
    row["status"] = "ACTIVE"
    models.touch(row)
    return ok(models.program(row), store.now())


# ---------------------------------------------------------------------------
# Targeting criteria
# ---------------------------------------------------------------------------
@bp.route("/lender-programs/<pid>/targeting-criteria", methods=["POST"])
def create_criterion(pid):
    require(["LenderOps", "PlatformAdmin"])
    prog = helpers.program(pid)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    field = data.get("criterion_field")
    operator = data.get("operator")
    value = data.get("criterion_value")
    if field not in CRITERION_FIELDS:
        fail("ERR_INVALID_REQUEST", "criterion_field is not a declared field.")
    if operator not in OPERATORS:
        fail("ERR_INVALID_REQUEST", "operator is not a declared operator.")
    if value in (None, ""):
        fail("ERR_INVALID_REQUEST", "criterion_value is required.")
    hard = data.get("is_hard_requirement")
    if not isinstance(hard, bool):
        fail("ERR_INVALID_REQUEST", "is_hard_requirement must be a boolean.")
    row = store.make_row({
        "lender_program_id": prog["id"],
        "criterion_field": field,
        "operator": operator,
        "criterion_value": str(value),
        "is_hard_requirement": hard,
    })
    store.targeting_criteria[row["id"]] = row
    return ok(models.criterion(row), store.now(), 201)


@bp.route("/targeting-criteria", methods=["GET"])
def list_criteria():
    require(READ_ROLES)
    rows = list(store.targeting_criteria.values())
    pid = request.args.get("lender_program_id")
    if pid:
        rows = [r for r in rows if r["lender_program_id"] == pid]
    hard = request.args.get("is_hard_requirement")
    if hard not in (None, ""):
        wanted = str(hard).lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r["is_hard_requirement"]) == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.criterion(r) for r in window], store.now(), pagination)


@bp.route("/targeting-criteria/<tid>", methods=["GET"])
def get_criterion(tid):
    require(READ_ROLES)
    row = store.targeting_criteria.get(tid)
    if row is None:
        fail("ERR_CONSUMER_NOT_FOUND", "TargetingCriterion not found.")
    return ok(models.criterion(row), store.now())


@bp.route("/lender-programs/<pid>/targeting-criteria", methods=["GET"])
def program_criteria(pid):
    require(READ_ROLES)
    helpers.program(pid)
    rows = [c for c in store.targeting_criteria.values() if c["lender_program_id"] == pid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.criterion(r) for r in window], store.now(), pagination)