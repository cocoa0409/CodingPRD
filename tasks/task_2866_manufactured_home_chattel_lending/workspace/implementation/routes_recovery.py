"""Default, enforcement, refurbishment, remarketing and settlement (PRD 3.9)."""

from flask import Blueprint, request

import constants as K
import core
import domain
import envelope
import security
import shape
import store
from errors import ApiError
from routes_servicing import _release_on_settlement
from routes_units import query_enum

bp = Blueprint("recovery", __name__)

CASE_READ_ROLES = security.STAFF + (security.BORROWER,)


def _require_status(case, *allowed):
    if case["status"] not in allowed:
        raise ApiError("ERR_RECOVERY_CASE_INVALID_STATE")


def _clear_hold(loan):
    unit = store.units.get(loan["unit_id"])
    if unit is not None and unit["recovery_hold"]:
        unit["recovery_hold"] = False
        store.touch(unit)
    return unit


# --------------------------------------------------------------------------
# default declaration
# --------------------------------------------------------------------------

@bp.post("/loans/<loan_id>/default-declare")
def declare_default(loan_id):
    security.require(security.RECOVERY_MANAGER)
    loan = store.get_loan(loan_id)

    if loan["servicing_state"] != "DELINQUENT":
        raise ApiError("ERR_LOAN_SERVICING_INVALID_STATE")

    if loan["delinquent_days"] < domain.default_threshold_days(loan):
        raise ApiError("ERR_DEFAULT_NOT_ELIGIBLE")

    path = ("REPOSSESSION" if loan["collateral_classification"] == "PERSONAL_PROPERTY"
            else "FORECLOSURE")
    seed = (K.REPOSSESSION_EXPENSE_CENTS if path == "REPOSSESSION"
            else K.FORECLOSURE_EXPENSE_CENTS)

    record = {
        "id": core.new_id(),
        "loan_id": loan["id"],
        "recovery_valuation_id": None,
        "resale_loan_id": None,
        "path": path,
        "status": "OPENED",
        "notice_reference": None,
        "cure_deadline_date": None,
        "redemption_window_ends_at": None,
        "possession_date": None,
        "recovery_expense_cents": seed,
        "refurbishment_line_items": [],
        "refurbishment_cost_cents": 0,
        "asking_price_cents": None,
        "resale_price_cents": None,
        "gross_proceeds_cents": None,
        "commission_bps": None,
        "commission_cents": None,
        "net_proceeds_cents": None,
        "payoff_amount_cents": None,
        "deficiency_balance_cents": None,
        "surplus_cents": None,
    }
    store.stamp_new(record)
    store.cases[record["id"]] = record

    loan["servicing_state"] = "DEFAULT"
    unit = store.units.get(loan["unit_id"])
    if unit is not None:
        unit["recovery_hold"] = True
        unit["title_status"] = "TITLE_ENCUMBERED"
        store.touch(unit)
    store.touch(loan)
    domain.recompute_exposure_for_loan(loan)
    return envelope.created(store.serialize(record))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/recovery-cases/<case_id>")
def read_case(case_id):
    actor = security.require(*CASE_READ_ROLES)
    case = store.get_case(case_id)
    loan = store.loans.get(case["loan_id"])
    if loan is not None:
        security.check_loan_scope(actor, loan)
    return envelope.ok(store.serialize(case))


@bp.get("/recovery-cases")
def list_cases():
    actor = security.require(*CASE_READ_ROLES)
    loan_id = request.args.get("loan_id")
    recovery_valuation_id = request.args.get("recovery_valuation_id")
    resale_loan_id = request.args.get("resale_loan_id")
    path = query_enum("path", K.RECOVERY_PATHS)
    status = query_enum("status", K.RECOVERY_STATUSES)

    rows = store.ordered(list(store.cases.values()))
    if loan_id:
        rows = [c for c in rows if c["loan_id"] == loan_id]
    if recovery_valuation_id:
        rows = [c for c in rows if c["recovery_valuation_id"] == recovery_valuation_id]
    if resale_loan_id:
        rows = [c for c in rows if c["resale_loan_id"] == resale_loan_id]
    if path:
        rows = [c for c in rows if c["path"] == path]
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows = security.narrow_by_loan(actor, rows)
    return envelope.paginate(rows, store.serialize)


# --------------------------------------------------------------------------
# the two enforcement arms
# --------------------------------------------------------------------------

@bp.post("/recovery-cases/<case_id>/issue-notice")
def issue_notice(case_id):
    security.require(security.RECOVERY_MANAGER)
    case = store.get_case(case_id)
    data = shape.body()
    notice_reference = shape.req_string(data, "notice_reference")
    _require_status(case, "OPENED")

    case["notice_reference"] = notice_reference
    if case["path"] == "REPOSSESSION":
        case["status"] = "REPO_NOTICE_ISSUED"
        case["cure_deadline_date"] = core.add_days(core.now(), K.RIGHT_TO_CURE_DAYS)
    else:
        case["status"] = "REDEMPTION_WINDOW"
        case["redemption_window_ends_at"] = core.add_days(core.now(),
                                                         K.STATUTORY_REDEMPTION_DAYS)
    store.touch(case)

    loan = store.loans.get(case["loan_id"])
    if loan is not None and loan["servicing_state"] == "DEFAULT":
        loan["servicing_state"] = "RECOVERY"
        store.touch(loan)
    return envelope.ok(store.serialize(case))


@bp.post("/recovery-cases/<case_id>/redeem")
def redeem(case_id):
    security.require(security.RECOVERY_MANAGER)
    case = store.get_case(case_id)

    # the path check precedes the status check: a repossession-path case can
    # never reach a redemption window at all (PRD 2.7).
    if case["path"] != "FORECLOSURE":
        raise ApiError("ERR_CLASSIFICATION_PATH_MISMATCH")
    _require_status(case, "REDEMPTION_WINDOW")

    ends_at = case["redemption_window_ends_at"]
    if ends_at is not None and core.now() >= ends_at:
        raise ApiError("ERR_REDEMPTION_WINDOW_CLOSED")

    case["status"] = "CLOSED_REDEEMED"
    store.touch(case)

    loan = store.loans.get(case["loan_id"])
    if loan is not None:
        if loan["servicing_state"] == "RECOVERY":
            loan["servicing_state"] = "CURRENT"
        _clear_hold(loan)
        store.touch(loan)
        domain.recompute_exposure_for_loan(loan)
    return envelope.ok(store.serialize(case))


@bp.post("/recovery-cases/<case_id>/obtain-possession")
def obtain_possession(case_id):
    security.require(security.RECOVERY_MANAGER)
    case = store.get_case(case_id)
    _require_status(case, "REPO_NOTICE_ISSUED", "REDEMPTION_WINDOW")

    loan = store.loans.get(case["loan_id"])
    unit = store.units.get(loan["unit_id"]) if loan is not None else None

    if unit is not None and unit.get("community_id"):
        community = store.communities.get(unit["community_id"])
        if community is None or not community["lender_access_rights"]:
            raise ApiError("ERR_LENDER_ACCESS_NOT_GRANTED")

    recorded = [f for f in store.filings_of_loan(case["loan_id"])
                if f["status"] == "RECORDED"]
    if loan is None or loan["perfection_state"] != "PERFECTED" or not recorded:
        raise ApiError("ERR_PERFECTION_NOT_ESTABLISHED")

    if case["path"] == "REPOSSESSION":
        deadline = case["cure_deadline_date"]
        if deadline is None or core.now() < deadline:
            raise ApiError("ERR_CURE_PERIOD_ACTIVE")
    else:
        ends_at = case["redemption_window_ends_at"]
        if ends_at is None or core.now() < ends_at:
            raise ApiError("ERR_REDEMPTION_WINDOW_OPEN")

    case["status"] = "POSSESSION_OBTAINED"
    case["possession_date"] = core.now()
    store.touch(case)
    return envelope.ok(store.serialize(case))


# --------------------------------------------------------------------------
# refurbishment and remarketing
# --------------------------------------------------------------------------

@bp.post("/recovery-cases/<case_id>/begin-refurbishment")
def begin_refurbishment(case_id):
    security.require(security.RECOVERY_MANAGER)
    case = store.get_case(case_id)
    data = shape.body()
    valuation = store.get_valuation(shape.req_id(data, "recovery_valuation_id"))
    _require_status(case, "POSSESSION_OBTAINED")

    loan = store.loans.get(case["loan_id"])
    unit_id = loan["unit_id"] if loan is not None else None
    if (valuation["status"] != "CERTIFIED"
            or valuation["variant"] != "RECOVERY_LIQUIDATION"
            or valuation["unit_id"] != unit_id):
        raise ApiError("ERR_VALUATION_VARIANT_MISMATCH")

    case["recovery_valuation_id"] = valuation["id"]
    case["status"] = "REFURBISHING"
    store.touch(case)
    return envelope.ok(store.serialize(case))


@bp.post("/recovery-cases/<case_id>/refurbishment-costs")
def record_refurbishment_cost(case_id):
    security.require(security.RECOVERY_MANAGER)
    case = store.get_case(case_id)
    data = shape.body()
    category = shape.req_string(data, "category")
    cost_cents = shape.req_int(data, "cost_cents", minimum=0)
    cost_class = shape.req_enum(data, "cost_class", K.COST_CLASSES)
    _require_status(case, "REFURBISHING")

    case["refurbishment_line_items"].append({
        "category": category,
        "cost_cents": cost_cents,
        "cost_class": cost_class,
        "recorded_at": core.now(),
    })
    if cost_class == "CAPITALIZED":
        case["refurbishment_cost_cents"] += cost_cents
    else:
        case["recovery_expense_cents"] += cost_cents
    store.touch(case)
    return envelope.ok(store.serialize(case))


@bp.post("/recovery-cases/<case_id>/list-for-resale")
def list_for_resale(case_id):
    security.require(security.RECOVERY_MANAGER)
    case = store.get_case(case_id)
    data = shape.body()
    asking_price_cents = shape.req_int(data, "asking_price_cents", minimum=1)
    _require_status(case, "REFURBISHING")

    case["asking_price_cents"] = asking_price_cents
    case["status"] = "REMARKETING"
    store.touch(case)
    return envelope.ok(store.serialize(case))


@bp.post("/recovery-cases/<case_id>/finalize-sale")
def finalize_sale(case_id):
    security.require(security.RECOVERY_MANAGER)
    case = store.get_case(case_id)
    data = shape.body()
    resale_loan_id = shape.opt_id(data, "resale_loan_id")
    if resale_loan_id is not None:
        store.get_loan(resale_loan_id)
    resale_price_cents = shape.req_int(data, "resale_price_cents", minimum=0)
    _require_status(case, "REMARKETING")

    loan = store.get_loan(case["loan_id"])
    unit = store.units.get(loan["unit_id"])

    case["resale_price_cents"] = resale_price_cents
    case["resale_loan_id"] = resale_loan_id
    settlement = domain.settle(case, loan, unit)
    case.update(settlement)

    if settlement["deficiency_balance_cents"] > 0:
        case["status"] = "CLOSED_DEFICIENCY"
        loan["servicing_state"] = "CHARGED_OFF"
    elif settlement["surplus_cents"] > 0:
        case["status"] = "CLOSED_SURPLUS"
        loan["servicing_state"] = "PAID_OFF"
    else:
        case["status"] = "CLOSED_SETTLED"
        loan["servicing_state"] = "PAID_OFF"

    loan["principal_balance_cents"] = 0
    loan["interest_accrued_unpaid_cents"] = 0
    loan["fees_outstanding_cents"] = 0
    loan["force_placed_premium_outstanding_cents"] = 0
    _release_on_settlement(loan)

    if unit is not None:
        unit["recovery_hold"] = False
        unit["title_status"] = "ACTIVE_TITLE"
        store.touch(unit)

    store.touch(case)
    store.touch(loan)
    domain.recompute_exposure_for_loan(loan)
    return envelope.ok(store.serialize(case))
