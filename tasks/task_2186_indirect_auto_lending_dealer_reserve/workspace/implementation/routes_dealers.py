"""Routes: logical clock, dealers, dealer status, reserve adjustments,
scorecards."""
from fractions import Fraction

from flask import Blueprint, g

import core
from core import (
    store, clock, new_rec, bump, stamp, putdt, dtv, fail, ok, list_response,
    require_roles, scope_dealer_id, get_body, v_str, v_int, v_enum, v_dt,
    get_dealer, get_scorecard, qfilter, is_dealer_principal, serialize,
    ALL_ROLES, PROBATION_MIN_FUNDED_COUNT, PROBATION_EARLY_PAYOFF_RATE_BPS,
)
import services as S

bp = Blueprint("dealers", __name__)

DEALER_ACTIONS = ("SUSPEND", "REINSTATE", "TERMINATE", "COMPLIANCE_HOLD", "RELEASE_HOLD")
ADMIN_ACTIONS = ("SUSPEND", "REINSTATE", "TERMINATE")
COMPLIANCE_ACTIONS = ("COMPLIANCE_HOLD", "RELEASE_HOLD")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/lending/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PortfolioAdmin")
    body = get_body()
    _raw, parsed = v_dt(body, "to_iso8601", required=True)
    clock.set(parsed)
    return ok({"current_utc": core.fmt_dt(clock.now())})


# ---------------------------------------------------------------------------
# Dealers
# ---------------------------------------------------------------------------
def new_dealer(legal_name, state_code, program_code, funding_line_cents):
    dealer = new_rec()
    dealer["legal_name"] = legal_name
    dealer["state_code"] = state_code
    dealer["program_code"] = program_code
    dealer["funding_line_cents"] = funding_line_cents
    dealer["status"] = "PROSPECT"
    dealer["compliance_hold"] = False
    dealer["suspension_reason"] = None
    dealer["reserve_balance_cents"] = 0
    dealer["outstanding_principal_cents"] = 0
    dealer["funded_contract_count"] = 0
    dealer["total_funded_ever_count"] = 0
    dealer["early_payoff_count"] = 0
    dealer["default_count"] = 0
    dealer["repurchase_count"] = 0
    dealer["chargeback_count"] = 0
    dealer["early_payoff_rate_bps"] = 0
    dealer["latest_scorecard_grade"] = None
    dealer["scorecard_stale"] = False
    return dealer


@bp.route("/lending/dealers", methods=["POST"])
def create_dealer():
    require_roles("PortfolioAdmin")
    body = get_body()
    legal_name = v_str(body, "legal_name", required=True, min_len=1, max_len=120)
    state_code = v_str(body, "state_code", required=True, min_len=2, max_len=2, pattern=r"^[A-Z]{2}$")
    program_code = v_str(body, "program_code", required=False, min_len=1, max_len=None, default="PS-STANDARD")
    funding_line = v_int(body, "funding_line_cents", required=False, minimum=0, default=50000000)
    dealer = new_dealer(legal_name, state_code, program_code, funding_line)
    store.dealers[dealer["id"]] = dealer
    return ok(serialize(dealer), 201)


@bp.route("/lending/dealers/<dealer_id>", methods=["GET"])
def read_dealer(dealer_id):
    require_roles(*ALL_ROLES)
    scope_dealer_id(dealer_id)
    dealer = get_dealer(dealer_id)
    return ok(serialize(dealer))


@bp.route("/lending/dealers/<dealer_id>/status", methods=["POST"])
def dealer_status(dealer_id):
    require_roles("PortfolioAdmin", "ComplianceOfficer")
    body = get_body()
    action = body.get("action")
    if isinstance(action, str) and action in DEALER_ACTIONS:
        if action in ADMIN_ACTIONS and g.role != "PortfolioAdmin":
            fail("ERR_FORBIDDEN_ROLE", "Action %s requires PortfolioAdmin." % action)
        if action in COMPLIANCE_ACTIONS and g.role != "ComplianceOfficer":
            fail("ERR_FORBIDDEN_ROLE", "Action %s requires ComplianceOfficer." % action)
    scope_dealer_id(dealer_id)
    dealer = get_dealer(dealer_id)

    action = v_enum(body, "action", DEALER_ACTIONS, required=True)
    reason = v_str(body, "reason", required=False, min_len=1, max_len=None, default=None)

    if action == "SUSPEND":
        if dealer["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "Only an ACTIVE dealer may be suspended.")
        dealer["status"] = "SUSPENDED"
        dealer["suspension_reason"] = reason if reason else "MANUAL_SUSPENSION"
        S.hold_open_applications(dealer)
    elif action == "REINSTATE":
        if dealer["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE", "Only a SUSPENDED dealer may be reinstated.")
        if dealer["compliance_hold"]:
            fail("ERR_INVALID_STATE", "Dealer is under a compliance hold.")
        for review in S.dealer_reviews(dealer["id"]):
            if review["status"] == "REMEDIATION_ORDERED":
                fail("ERR_INVALID_STATE", "An open remediation order blocks reinstatement.")
        dealer["status"] = "ACTIVE"
        dealer["suspension_reason"] = None
        S.release_held_applications(dealer)
    elif action == "TERMINATE":
        if dealer["status"] not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "Only an ACTIVE or SUSPENDED dealer may be terminated.")
        S.terminate_dealer(dealer, reason)
    elif action == "COMPLIANCE_HOLD":
        dealer["compliance_hold"] = True
    elif action == "RELEASE_HOLD":
        dealer["compliance_hold"] = False

    bump(dealer)
    return ok(serialize(dealer))


@bp.route("/lending/dealers/<dealer_id>/reserve-adjustments", methods=["POST"])
def reserve_adjustment(dealer_id):
    require_roles("PortfolioAdmin")
    scope_dealer_id(dealer_id)
    dealer = get_dealer(dealer_id)
    body = get_body()
    amount = v_int(body, "amount_cents", required=True)
    reason = v_str(body, "reason", required=True, min_len=1, max_len=120)
    expected = v_int(body, "expected_dealer_version", required=True)
    if expected != dealer["version"]:
        fail("ERR_STALE_DEALER_VERSION", "Dealer version has advanced.")
    if dealer["reserve_balance_cents"] + amount < 0:
        fail("ERR_RESERVE_BALANCE_NEGATIVE", "Adjustment would drive the reserve balance below zero.")
    entry = S.post_entry(dealer, None, "MANUAL_ADJUSTMENT", amount, reason)
    bump(dealer)
    return ok(serialize(entry), 201)


# ---------------------------------------------------------------------------
# Scorecards
# ---------------------------------------------------------------------------
@bp.route("/lending/dealers/<dealer_id>/scorecards", methods=["POST"])
def create_scorecard(dealer_id):
    require_roles("PortfolioAdmin")
    scope_dealer_id(dealer_id)
    dealer = get_dealer(dealer_id)
    body = get_body()
    start_raw, start = v_dt(body, "period_start", required=True)
    end_raw, end = v_dt(body, "period_end", required=True)
    basis = v_enum(body, "basis", ("TRAILING_WINDOW", "INCEPTION_TO_DATE"), required=True)
    if end <= start:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly after period_start.")

    card = new_rec()
    card["dealer_id"] = dealer["id"]
    putdt(card, "period_start", start_raw, start)
    putdt(card, "period_end", end_raw, end)
    card["basis"] = basis
    population = S.scorecard_population(dealer["id"], basis, start, end)
    S.compute_scorecard(card, population)
    card["status"] = "DRAFT"
    stamp(card, "finalized_at", None)
    store.scorecards[card["id"]] = card
    return ok(serialize(card), 201)


@bp.route("/lending/dealers/<dealer_id>/scorecards", methods=["GET"])
def list_scorecards(dealer_id):
    require_roles(*ALL_ROLES)
    scope_dealer_id(dealer_id)
    get_dealer(dealer_id)
    records = [c for c in store.scorecards.values() if c["dealer_id"] == dealer_id]
    basis = qfilter("basis")
    if basis is not None:
        records = [c for c in records if c["basis"] == basis]
    status = qfilter("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    records.sort(key=lambda c: (c.get("created_at") or "", c.get("_seq") or 0))
    records.sort(key=lambda c: dtv(c, "period_start"), reverse=True)
    return list_response(records)


@bp.route("/lending/scorecards/<scorecard_id>/finalize", methods=["POST"])
def finalize_scorecard(scorecard_id):
    require_roles("PortfolioAdmin")
    card = get_scorecard(scorecard_id)
    scope_dealer_id(card["dealer_id"])
    if card["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT scorecard may be finalized.")
    dealer = store.dealers.get(card["dealer_id"])
    card["status"] = "FINALIZED"
    stamp(card, "finalized_at", clock.now())
    bump(card)
    if dealer is not None:
        dealer["latest_scorecard_grade"] = card["grade"]
        dealer["scorecard_stale"] = False
        if card["grade"] == "D" and dealer["status"] == "ACTIVE":
            S.auto_suspend(dealer, "AUTO_SCORECARD_GRADE_D")
        bump(dealer)
    return ok(serialize(card))
