from flask import Blueprint

import calc
import db
import middleware as mw
import response
import util
from errors import ApiError

bp = Blueprint("placements", __name__)

FUNDING_ACTIONS = ("ACTIVATE", "EARLY_WITHDRAW", "CANCEL")
READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


def find_placement(placement_id):
    record = db.placements.get(placement_id)
    if record is None:
        raise ApiError("ERR_PLACEMENT_NOT_FOUND")
    return record


@bp.post("/deposit-placements")
def create_placement():
    user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer")
    data = mw.body()
    program_id = mw.req_id(data, "program_id")
    principal_cents = mw.req_int(data, "principal_cents", minimum=0)
    if principal_cents <= 0:
        raise mw.bad("principal_cents must be strictly greater than zero.")
    rate_bps = mw.req_int(data, "rate_bps", minimum=0)
    issue_date = mw.req_date(data, "issue_date")
    tenor_days = mw.req_int(data, "tenor_days", minimum=0)
    rolled_from_id = mw.opt_id(data, "rolled_from_placement_id")

    program = db.programs.get(program_id)
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    source = None
    if rolled_from_id is not None:
        source = db.placements.get(rolled_from_id)
        if source is None:
            raise ApiError("ERR_PLACEMENT_NOT_FOUND")

    institution = db.institutions.get(program["institution_id"])
    bucket = calc.tenor_bucket(program["product_type"], tenor_days)
    maturity_date = util.add_days(issue_date, tenor_days)
    cap, _pub = calc.effective_cap(institution, bucket,
                                   program.get("local_prevailing_rate_bps"),
                                   issue_date, require=True)

    determination_id = program.get("governing_classification_id")
    if not determination_id:
        raise ApiError("ERR_CLASSIFICATION_REQUIRED")
    if program["state"] != "OPEN_FOR_PLACEMENT":
        raise ApiError("ERR_PROGRAM_NOT_OPEN")
    if cap is not None and rate_bps > cap:
        raise ApiError("ERR_RATE_CAP_EXCEEDED")
    determination = db.classifications.get(determination_id)
    if (determination is None
            or determination["program_version_at_determination"] != program["version"]):
        raise ApiError("ERR_CLASSIFICATION_STALE")
    if institution["concentration_posture"] == "FROZEN":
        raise ApiError("ERR_CONCENTRATION_FROZEN")

    if bucket == "NON_MATURITY":
        if tenor_days != 0:
            raise ApiError("ERR_MATURITY_DATE_INVALID")
    elif tenor_days <= 0:
        raise ApiError("ERR_MATURITY_DATE_INVALID")

    agreement = db.broker_agreements.get(program.get("agreement_id")) \
        if program.get("agreement_id") else None
    if agreement is not None and issue_date < agreement["effective_date"]:
        raise ApiError("ERR_ISSUE_BEFORE_AGREEMENT")
    if issue_date < util.clock_date().isoformat():
        raise ApiError("ERR_ISSUE_BEFORE_AGREEMENT")

    if source is not None:
        already_rolled = any(p.get("rolled_from_placement_id") == rolled_from_id
                             for p in db.placements.values())
        if (source["program_id"] != program_id
                or source["funding_status"] != "MATURED"
                or already_rolled):
            raise ApiError("ERR_ROLLOVER_SOURCE_INVALID")

    determined_class = determination["determined_class"]
    if determined_class == "RECIPROCAL_EXCLUDED":
        if principal_cents > calc.reciprocal_capacity(institution):
            raise ApiError("ERR_RECIPROCAL_CAP_EXCEEDED")

    exposure, window_cap = calc.maturity_window_exposure(
        institution, maturity_date, principal_cents)
    if exposure >= window_cap:
        raise ApiError("ERR_MATURITY_WINDOW_CONCENTRATION")

    record = {
        "program_id": program_id,
        "rolled_from_placement_id": rolled_from_id,
        "principal_cents": principal_cents,
        "rate_bps": rate_bps,
        "issue_date": issue_date,
        "tenor_days": tenor_days,
        "maturity_date": maturity_date,
        "tenor_bucket": bucket,
        "funding_status": "PENDING",
        "compliance_status": "UNREVIEWED",
        "accrued_interest_cents": 0,
        "early_withdrawal_penalty_cents": 0,
        "net_settlement_cents": 0,
        "settlement_date": None,
        "fee_accrual_cents": 0,
        "classified_as": determined_class,
        "prepared_by_user_id": user_id,
    }
    db.stamp_new(record)
    db.placements[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/deposit-placements/<placement_id>")
def read_placement(placement_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(find_placement(placement_id)))


@bp.get("/deposit-placements")
def list_placements():
    mw.auth(*READ_ROLES)
    limit, offset = mw.page()
    rows = list(db.placements.values())
    for field in ("program_id", "rolled_from_placement_id", "funding_status",
                  "compliance_status", "classified_as"):
        wanted = mw.q(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    institution_id = mw.q("institution_id")
    if institution_id is not None:
        rows = [r for r in rows
                if (db.programs.get(r["program_id"]) or {}).get("institution_id")
                == institution_id]
    rows.sort(key=lambda r: (r["issue_date"], r["created_at"], r["_seq"]))
    return response.listing(db.public_list(rows), limit, offset)


@bp.post("/deposit-placements/<placement_id>/funding-actions")
def funding_actions(placement_id):
    _user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer")
    placement = find_placement(placement_id)
    data = mw.body()
    action = mw.req_enum(data, "action", FUNDING_ACTIONS)
    withdrawal_date = None
    if action == "EARLY_WITHDRAW":
        withdrawal_date = mw.req_date(data, "withdrawal_date")

    program = db.programs.get(placement["program_id"])
    institution = db.institutions.get(program["institution_id"])
    status = placement["funding_status"]

    if action == "ACTIVATE":
        if status != "PENDING":
            raise ApiError("ERR_PLACEMENT_STATE_INVALID")
        if program["state"] != "OPEN_FOR_PLACEMENT":
            raise ApiError("ERR_PROGRAM_NOT_OPEN")
        if institution["concentration_posture"] == "FROZEN":
            raise ApiError("ERR_CONCENTRATION_FROZEN")
        klass = calc.governing_class(program)
        if calc.would_breach_on_activation(institution, placement, klass):
            raise ApiError("ERR_CONCENTRATION_BREACH")
        placement["funding_status"] = "ACTIVE"
        placement["classified_as"] = klass
        db.bump(placement)
        program["outstanding_principal_cents"] += placement["principal_cents"]
        db.touch(program)
        calc.recompute_institution(institution)
        calc.recompute_fees_for_placement(placement)

    elif action == "EARLY_WITHDRAW":
        if status != "ACTIVE":
            raise ApiError("ERR_PLACEMENT_STATE_INVALID")
        if withdrawal_date >= placement["maturity_date"]:
            raise mw.bad("withdrawal_date must be strictly before maturity_date.")
        days = util.day_diff(withdrawal_date, placement["issue_date"])
        interest = calc.accrued_interest(placement["principal_cents"],
                                        placement["rate_bps"], days)
        contractual = calc.contractual_penalty(
            placement["principal_cents"], placement["rate_bps"],
            program["early_withdrawal_penalty_days"])
        if program["principal_erosion_allowed"]:
            penalty = contractual
        else:
            penalty = min(contractual, interest)
        placement["accrued_interest_cents"] = interest
        placement["early_withdrawal_penalty_cents"] = penalty
        placement["net_settlement_cents"] = (
            placement["principal_cents"] + interest - penalty)
        placement["settlement_date"] = withdrawal_date
        placement["funding_status"] = "WITHDRAWN_EARLY"
        placement["fee_accrual_cents"] = 0
        db.bump(placement)
        program["outstanding_principal_cents"] -= placement["principal_cents"]
        db.touch(program)
        calc.recompute_institution(institution)
        calc.recompute_fees_for_placement(placement)

    else:  # CANCEL
        if status != "PENDING":
            raise ApiError("ERR_PLACEMENT_STATE_INVALID")
        placement["funding_status"] = "CANCELLED"
        db.bump(placement)

    return response.ok(db.public(placement))


COMPLIANCE_MOVES = {
    ("UNREVIEWED", "PASS"): "RATE_CHECKED",
    ("UNREVIEWED", "EXEMPT_NO_CAP"): "RATE_CHECKED",
    ("UNREVIEWED", "BREACH"): "FLAGGED",
    ("RATE_CHECKED", "BREACH"): "FLAGGED",
    ("REMEDIATED", "BREACH"): "FLAGGED",
    ("FLAGGED", "PASS"): "REMEDIATED",
    ("FLAGGED", "EXEMPT_NO_CAP"): "REMEDIATED",
}


@bp.post("/deposit-placements/<placement_id>/rate-cap-checks")
def create_rate_cap_check(placement_id):
    user_id, _role = mw.auth("SystemAdmin", "ComplianceReviewer", "Examiner")
    placement = find_placement(placement_id)
    data = mw.body()
    check_date = mw.req_date(data, "check_date")

    program = db.programs.get(placement["program_id"])
    institution = db.institutions.get(program["institution_id"])
    bucket = placement["tenor_bucket"]
    local = program.get("local_prevailing_rate_bps")
    cap, pub = calc.effective_cap(institution, bucket, local, check_date,
                                  require=True)
    offered = placement["rate_bps"]
    if cap is None:
        breach_bps = 0
        outcome = "EXEMPT_NO_CAP"
    else:
        breach_bps = max(0, offered - cap)
        outcome = "BREACH" if breach_bps > 0 else "PASS"

    record = {
        "placement_id": placement["id"],
        "check_date": check_date,
        "applied_tenor_bucket": bucket,
        "national_rate_bps_snapshot": (pub["published_national_rate_bps"]
                                       if pub is not None else None),
        "local_prevailing_rate_bps_snapshot": local,
        "effective_cap_bps": cap,
        "offered_rate_bps": offered,
        "breach_bps": breach_bps,
        "outcome": outcome,
        "checked_by_user_id": user_id,
    }
    db.stamp_new(record, versioned=False)
    db.rate_cap_checks[record["id"]] = record

    moved = COMPLIANCE_MOVES.get((placement["compliance_status"], outcome))
    if moved is not None:
        placement["compliance_status"] = moved
        db.bump(placement)
    return response.created(db.public(record))


@bp.get("/deposit-placements/<placement_id>/rate-cap-checks")
def list_rate_cap_checks(placement_id):
    mw.auth(*READ_ROLES)
    find_placement(placement_id)
    limit, offset = mw.page()
    rows = [r for r in db.rate_cap_checks.values()
            if r["placement_id"] == placement_id]
    outcome = mw.q("outcome")
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    rows.sort(key=lambda r: (r["check_date"], r["created_at"], r["_seq"]))
    return response.listing(db.public_list(rows), limit, offset)
