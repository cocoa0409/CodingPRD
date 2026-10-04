"""Clock, lender lifecycle, and financial filing endpoints."""
from flask import Blueprint

from auth import authenticate, require_role, check_ownership
from services import (recompute_net_worth, filings_of_lender, cases_of_lender,
                      cascade_suspend, cascade_reinstate, sweep_clock)
from store import db, make_entity, bump, public, iso_clock, logical_date
from util import (ApiError, ok_object, paginate, get_body, is_int, need_int,
                  need_str, verr, parse_date, parse_dt, add_months_date, MISSING)

bp = Blueprint("lenders", __name__)

INSTITUTION_TYPES = ("MORTGAGEE_SUPERVISED", "MORTGAGEE_NONSUPERVISED", "MORTGAGEE_INVESTING")

LENDER_NONTERMINAL_CASE_STATES = (
    "CASE_NUMBER_ASSIGNED", "UNDERWRITE_SUBMITTED", "DEFICIENT", "BLOCKED",
    "ENDORSED", "IN_DEFAULT", "CLAIM_FILED",
)

ACTION_ROLE = {
    "RESUBMIT": "LenderOfficer",
    "ADVANCE_TO_FIELD_REVIEW": "FhaReviewer",
    "RETURN": "FhaReviewer",
    "APPROVE": "FhaApprover",
    "SUSPEND": "FhaApprover",
    "REINSTATE": "FhaApprover",
    "TERMINATE": "FhaApprover",
}


def _get_lender_or_404(lender_id):
    lender = db.lenders.get(lender_id)
    if lender is None:
        raise ApiError("ERR_NOT_FOUND", "lender %s does not exist" % lender_id)
    return lender


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    b = get_body()
    to = b.get("to_iso8601", MISSING)
    if to is MISSING:
        verr("missing required field: to_iso8601")
    try:
        dt = parse_dt(to)
    except (ValueError, TypeError):
        verr("to_iso8601 must be an ISO 8601 timestamp")
    db.clock = dt
    sweep_clock()
    return ok_object({"current_utc": iso_clock(dt)}, 200)


# ---------------------------------------------------------------------------
# Lenders
# ---------------------------------------------------------------------------
@bp.post("/mi/lenders")
def create_lender():
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    b = get_body()
    legal_name = need_str(b, "legal_name")
    institution_type = b.get("institution_type", MISSING)
    if institution_type is MISSING:
        verr("missing required field: institution_type")
    if institution_type not in INSTITUTION_TYPES:
        verr("institution_type must be one of %s" % ", ".join(INSTITUTION_TYPES))
    home_state = need_str(b, "home_state")
    if len(home_state) != 2 or not home_state.isalpha():
        verr("home_state must be a two-letter state code")
    qc = b.get("qc_plan_on_file", MISSING)
    if qc is MISSING:
        verr("missing required field: qc_plan_on_file")
    if not isinstance(qc, bool):
        verr("qc_plan_on_file must be a boolean")
    lender = make_entity({
        "legal_name": legal_name,
        "institution_type": institution_type,
        "home_state": home_state,
        "qc_plan_on_file": qc,
        "status": "DESK_REVIEW",
        "advanced_by_user_id": None,
        "approved_by_user_id": None,
        "endorsed_volume_cents": 0,
        "net_worth_variant": None,
        "required_net_worth_cents": None,
        "last_accepted_filing_id": None,
    })
    recompute_net_worth(lender)
    db.lenders[lender["id"]] = lender
    return ok_object(public(lender), 201)


@bp.get("/mi/lenders/<lenderId>")
def get_lender(lenderId):
    authenticate()
    return ok_object(public(_get_lender_or_404(lenderId)), 200)


# ---------------------------------------------------------------------------
# Lender lifecycle
# ---------------------------------------------------------------------------
@bp.post("/mi/lenders/<lenderId>/status-change")
def lender_status_change(lenderId):
    uid, role = authenticate()
    require_role(role, ["LenderOfficer", "FhaReviewer", "FhaApprover"])
    b = get_body()
    action = b.get("action")
    # Priority 2: role-to-action matrix (only evaluable for a known action).
    if isinstance(action, str) and action in ACTION_ROLE and ACTION_ROLE[action] != role:
        raise ApiError("ERR_UNAUTHORIZED_ROLE",
                       "role %s may not perform action %s" % (role, action))
    # Priority 3: entity-backed ownership (LenderOfficer resubmits its own id).
    check_ownership(uid, role, lenderId)
    # Priority 4: existence.
    lender = _get_lender_or_404(lenderId)
    # Priority 5: payload shape.
    if not isinstance(action, str) or action not in ACTION_ROLE:
        verr("action must be one of %s" % ", ".join(sorted(ACTION_ROLE)))

    status = lender["status"]
    if status == "TERMINATED":
        raise ApiError("ERR_ALREADY_TERMINAL", "lender is TERMINATED")

    if action == "ADVANCE_TO_FIELD_REVIEW":
        if status != "DESK_REVIEW":
            raise ApiError("ERR_INVALID_STATE",
                           "ADVANCE_TO_FIELD_REVIEW requires DESK_REVIEW, got %s" % status)
        lender["status"] = "FIELD_REVIEW"
        lender["advanced_by_user_id"] = uid
    elif action == "RETURN":
        if status not in ("DESK_REVIEW", "FIELD_REVIEW"):
            raise ApiError("ERR_INVALID_STATE",
                           "RETURN requires DESK_REVIEW or FIELD_REVIEW, got %s" % status)
        lender["status"] = "RETURNED"
    elif action == "RESUBMIT":
        if status != "RETURNED":
            raise ApiError("ERR_INVALID_STATE",
                           "RESUBMIT requires RETURNED, got %s" % status)
        lender["status"] = "DESK_REVIEW"
    elif action == "APPROVE":
        _approve_lender(lender, uid)
    elif action == "SUSPEND":
        if status != "APPROVED":
            raise ApiError("ERR_INVALID_STATE",
                           "SUSPEND requires APPROVED, got %s" % status)
        lender["status"] = "SUSPENDED"
        cascade_suspend(lender)
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE",
                           "REINSTATE requires SUSPENDED, got %s" % status)
        lender["status"] = "APPROVED"
        cascade_reinstate(lender)
    elif action == "TERMINATE":
        if status not in ("APPROVED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE",
                           "TERMINATE requires APPROVED or SUSPENDED, got %s" % status)
        if any(c["status"] in LENDER_NONTERMINAL_CASE_STATES
               for c in cases_of_lender(lender["id"])):
            raise ApiError("ERR_LENDER_HAS_ACTIVE_CASES",
                           "lender has loan cases in non-terminal states")
        lender["status"] = "TERMINATED"
    bump(lender)
    return ok_object(public(lender), 200)


def _approve_lender(lender, uid):
    if lender["status"] != "FIELD_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       "APPROVE requires FIELD_REVIEW, got %s" % lender["status"])
    # Priority 8: segregation of duties.
    if uid == lender["advanced_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the approver must differ from the reviewer who advanced the application")
    # Priority 10: filing freshness window (15 months).
    filing = None
    if lender["last_accepted_filing_id"]:
        filing = db.filings.get(lender["last_accepted_filing_id"])
    if filing is None or filing["status"] != "ACCEPTED":
        raise ApiError("ERR_FILING_STALE",
                       "no ACCEPTED filing on record for this lender")
    fye = parse_date(filing["fiscal_year_end"])
    if fye < add_months_date(logical_date(), -15):
        raise ApiError("ERR_FILING_STALE",
                       "latest ACCEPTED filing fiscal_year_end is not within 15 months")
    # Priority 12: financial sufficiency.
    required = lender["required_net_worth_cents"]
    if filing["adjusted_net_worth_cents"] < required:
        raise ApiError("ERR_NET_WORTH_DEFICIENT",
                       "adjusted net worth below the required floor")
    if filing["liquid_assets_cents"] * 5 < required:
        raise ApiError("ERR_LIQUIDITY_DEFICIENT",
                       "liquid assets fail the 20% liquidity test")
    if not lender["qc_plan_on_file"]:
        raise ApiError("ERR_QC_PLAN_MISSING", "no quality control plan on file")
    lender["status"] = "APPROVED"
    lender["approved_by_user_id"] = uid
    recompute_net_worth(lender)


# ---------------------------------------------------------------------------
# Financial filings
# ---------------------------------------------------------------------------
@bp.post("/mi/lenders/<lenderId>/financial-filings")
def create_filing(lenderId):
    uid, role = authenticate()
    require_role(role, ["LenderOfficer"])
    check_ownership(uid, role, lenderId)
    lender = _get_lender_or_404(lenderId)
    b = get_body()
    fye_raw = b.get("fiscal_year_end", MISSING)
    if fye_raw is MISSING:
        verr("missing required field: fiscal_year_end")
    try:
        parse_date(fye_raw)
    except (ValueError, TypeError):
        verr("fiscal_year_end must be an ISO date YYYY-MM-DD")
    ta = need_int(b, "total_assets_cents", minimum=0)
    tl = need_int(b, "total_liabilities_cents", minimum=0)
    la = need_int(b, "liquid_assets_cents", minimum=0)
    elv = b.get("expected_lender_version", MISSING)
    if elv is MISSING or not is_int(elv):
        verr("expected_lender_version is required and must be an integer")
    # Priority 6: optimistic concurrency on the parent lender version.
    if elv != lender["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_lender_version does not match the lender's current version")
    filing = make_entity({
        "lender_id": lender["id"],
        "fiscal_year_end": fye_raw,
        "total_assets_cents": ta,
        "total_liabilities_cents": tl,
        "liquid_assets_cents": la,
        "adjusted_net_worth_cents": ta - tl,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
    })
    db.filings[filing["id"]] = filing
    bump(lender)
    return ok_object(public(filing), 201)


@bp.get("/mi/lenders/<lenderId>/financial-filings")
def list_filings(lenderId):
    authenticate()
    _get_lender_or_404(lenderId)
    return paginate(filings_of_lender(lenderId))


@bp.post("/mi/financial-filings/<filingId>/decide")
def decide_filing(filingId):
    uid, role = authenticate()
    require_role(role, ["FhaReviewer"])
    filing = db.filings.get(filingId)
    if filing is None:
        raise ApiError("ERR_NOT_FOUND", "financial filing %s does not exist" % filingId)
    lender = db.lenders[filing["lender_id"]]
    b = get_body()
    decision = b.get("decision", MISSING)
    if decision is MISSING:
        verr("missing required field: decision")
    if decision not in ("ACCEPT", "REJECT"):
        verr("decision must be ACCEPT or REJECT")
    elv = b.get("expected_lender_version", MISSING)
    if elv is MISSING or not is_int(elv):
        verr("expected_lender_version is required and must be an integer")
    # Priority 6: OCC before state legality.
    if elv != lender["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_lender_version does not match the lender's current version")
    # Priority 7: ACCEPTED / REJECTED / SUPERSEDED are all terminal.
    if filing["status"] != "SUBMITTED":
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "filing is %s; no further decisions" % filing["status"])
    filing["decided_by_user_id"] = uid
    if decision == "ACCEPT":
        filing["status"] = "ACCEPTED"
        # Accept-with-supersede: prior ACCEPTED filing, same lender + fiscal year.
        for other in filings_of_lender(lender["id"]):
            if (other["id"] != filing["id"] and other["status"] == "ACCEPTED"
                    and other["fiscal_year_end"] == filing["fiscal_year_end"]):
                other["status"] = "SUPERSEDED"
                bump(other)
        lender["last_accepted_filing_id"] = filing["id"]
        recompute_net_worth(lender)
    else:
        filing["status"] = "REJECTED"
    bump(filing)
    bump(lender)
    return ok_object(public(filing), 200)
