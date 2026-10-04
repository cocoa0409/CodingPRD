"""Repayment-period minimum evaluation, delinquency/default cascades, and
catch-up payments."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_loan,
    create_catch_up_payload,
    drive_loan_missed_periods,
    evaluate_period_at,
    get_loan,
    initiate_and_settle_catch_up,
    make_merchant_owner_headers,
    record_finalized_batch,
    repay_loan_fully,
    set_clock,
    post_sweep,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
SERVICER = TEST_USERS["servicer_agent_headers"]


def _iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware instant; PRD pins the
    instant (`window_end` exactly 30 days after the demand), not the string
    rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _active_standard_bundle():
    """ACTIVE loan at 1,050,000 @ 0.10: total 1,165,500, minimum 64,750."""
    bundle = create_active_loan(principal_cents=1_050_000)
    assert bundle["loan"]["per_period_minimum_cents"] == 64_750
    return bundle


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / period_minimum_exact_equality
# ---------------------------------------------------------------------------

def test_period_minimum_exact_equality_is_met(api):
    """PRD Section 3.5: "When effective paid is greater than or equal to `per_period_minimum_cents` — the boundary is inclusive — the period is MET: the excess over the minimum becomes the new `carried_surplus_cents`, and `consecutive_missed_periods` resets to 0."

    Design: Difficulty/boundary_precision_check/period_minimum_exact_equality
    """
    bundle = _active_standard_bundle()
    loan_id = bundle["loan"]["id"]
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 647_500)
    post_sweep(loan_id, batch["id"])  # holdback exactly 64,750

    evaluated = evaluate_period_at(loan_id, "2026-10-31T00:00:00Z")
    assert evaluated["repayment_period_index"] == 1
    assert evaluated["carried_surplus_cents"] == 0
    assert evaluated["consecutive_missed_periods"] == 0
    assert evaluated["status"] == "ACTIVE"


def test_period_minimum_one_cent_below_is_missed(api):
    """PRD Section 3.5: "When effective paid falls short, `consecutive_missed_periods` increments by 1, the shortfall (minimum minus effective paid) is added to `cumulative_shortfall_cents`, and `carried_surplus_cents` resets to 0. Either way, `repayment_period_index` then increments by 1."

    Design: Difficulty/boundary_precision_check/period_minimum_exact_equality
    """
    bundle = _active_standard_bundle()
    loan_id = bundle["loan"]["id"]
    batch = record_finalized_batch(bundle["merchant"]["id"], "2026-09-02", 647_490)
    post_sweep(loan_id, batch["id"])  # holdback 64,749: one cent below

    evaluated = evaluate_period_at(loan_id, "2026-10-31T00:00:00Z")
    assert evaluated["repayment_period_index"] == 1
    assert evaluated["cumulative_shortfall_cents"] == 1
    assert evaluated["consecutive_missed_periods"] == 1


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / loan_delinquency_cure_cycle
# ---------------------------------------------------------------------------

def test_two_missed_periods_drive_delinquency(api):
    """PRD Section 3.5: "Misses cascade. When `consecutive_missed_periods` reaches 2, the loan moves from `ACTIVE` to `DELINQUENT` and the merchant cascades to `SUSPENDED`, blocking new offer creation."

    Design: Difficulty/non_linear_state_machine/loan_delinquency_cure_cycle
    """
    bundle = _active_standard_bundle()
    loan_id = bundle["loan"]["id"]

    first = evaluate_period_at(loan_id, "2026-10-31T00:00:00Z")
    assert first["status"] == "ACTIVE", "first miss alone is not yet delinquent"
    assert first["consecutive_missed_periods"] == 1

    second = evaluate_period_at(loan_id, "2026-12-30T00:00:00Z")
    assert second["status"] == "DELINQUENT"
    assert second["consecutive_missed_periods"] == 2


def test_delinquency_cured_by_catch_up_and_met_period(api):
    """PRD Section 3.5: "Curing works in reverse: when a `DELINQUENT` loan evaluates a period as MET and `cumulative_shortfall_cents` is 0, the loan returns to `ACTIVE` and `consecutive_missed_periods` resets — but the merchant stays `SUSPENDED` until a `PlatformAdmin` explicitly reinstates it."
    PRD Section 3.5: "Settlement moves the payment to `APPLIED`, stamps `period_index_credited` with the loan's current `repayment_period_index`, reduces `remaining_balance_cents` and increases `paid_to_date_cents` by `amount_cents`, and applies the amount shortfall-first: it reduces `cumulative_shortfall_cents` before any excess counts toward the current period's minimum evaluation."

    Design: Difficulty/non_linear_state_machine/loan_delinquency_cure_cycle
    """
    bundle = _active_standard_bundle()
    loan_id = bundle["loan"]["id"]

    drive_loan_missed_periods(loan_id, 2)
    loan = get_loan(loan_id)
    assert loan["status"] == "DELINQUENT"
    assert loan["cumulative_shortfall_cents"] == 129_500

    # 194,250 = shortfall 129,500 + current period minimum 64,750 exactly.
    initiate_and_settle_catch_up(bundle, 194_250)

    cured = evaluate_period_at(loan_id, "2027-02-28T00:00:00Z")
    assert cured["status"] == "ACTIVE"
    assert cured["consecutive_missed_periods"] == 0
    assert cured["cumulative_shortfall_cents"] == 0


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / delinquency_suspension_cascade
# ---------------------------------------------------------------------------

def test_delinquency_suspends_merchant(api):
    """PRD Section 3.5: "Misses cascade. When `consecutive_missed_periods` reaches 2, the loan moves from `ACTIVE` to `DELINQUENT` and the merchant cascades to `SUSPENDED`, blocking new offer creation."

    Design: Difficulty/transitive_cascade/delinquency_suspension_cascade
    """
    bundle = _active_standard_bundle()
    drive_loan_missed_periods(bundle["loan"]["id"], 2)

    loan = get_loan(bundle["loan"]["id"])
    assert loan["status"] == "DELINQUENT"

    merchant = validate_success(api.get_merchant(bundle["merchant"]["id"], ADMIN))
    assert merchant["status"] == "SUSPENDED"


def test_suspended_merchant_offer_generation_blocked(api):
    """PRD Section 3.1: "Suspension is the inverse state and arrives only through cascades: confirming a processor-migration signal (Section 3.7) or a loan reaching delinquency or default (Section 3.5) moves an `ELIGIBLE` merchant to `SUSPENDED`. While a merchant is `SUSPENDED`, new offer generation for that merchant is blocked with `ERR_MERCHANT_SUSPENDED`; existing loans are unaffected."

    Design: Difficulty/transitive_cascade/delinquency_suspension_cascade
    """
    bundle = _active_standard_bundle()
    drive_loan_missed_periods(bundle["loan"]["id"], 2)

    resp = api.create_offer(bundle["merchant"]["id"], UNDERWRITER)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_SUSPENDED)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / enforcement_demand_window_closed_interval
# ---------------------------------------------------------------------------

def _two_defaulted_loans_shared_guarantor_email(api):
    """Two merchants, each with a DEFAULTED loan under guarantor email
    shared@x.com; returns (bundle1, bundle2)."""
    bundle1 = create_active_loan(
        principal_cents=1_050_000,
        guarantor_email="shared@x.com",
        legal_name="D1 Co",
        owner_name="D One",
    )
    bundle2 = create_active_loan(
        principal_cents=1_050_000,
        guarantor_email="shared@x.com",
        legal_name="D2 Co",
        owner_name="D Two",
    )
    clocks = ["2026-10-31T00:00:00Z", "2026-12-30T00:00:00Z",
              "2027-02-28T00:00:00Z", "2027-04-29T00:00:00Z"]
    for clock in clocks:
        set_clock(clock)
        for b in (bundle1, bundle2):
            get_success = validate_success(
                api.evaluate_period(b["loan"]["id"], SERVICER))
            b["loan"] = get_success
    for b in (bundle1, bundle2):
        assert b["loan"]["status"] == "DEFAULTED"
        actions = validate_success(
            api.list_loan_enforcement_actions(b["loan"]["id"], ADMIN))
        assert len(actions) == 1 and actions[0]["status"] == "DRAFT"
        b["action"] = actions[0]
    return bundle1, bundle2


def test_enforcement_demand_blocked_through_closed_window_end(api):
    """PRD Section 3.6: "Demands are mutually exclusive per guarantor identity across loans: a demand is rejected with `ERR_ENFORCEMENT_WINDOW_OPEN` when any other action exists whose guarantor has the same `email`, in `DEMANDED` or `ESCALATED` status, whose closed window from its `demanded_at` through its `window_end` contains the current clock."

    Design: Difficulty/resource_temporal_overlap/enforcement_demand_window_closed_interval
    """
    bundle1, bundle2 = _two_defaulted_loans_shared_guarantor_email(api)

    set_clock("2027-04-29T00:00:00Z")
    demanded = validate_success(api.demand_enforcement(bundle1["action"]["id"], SERVICER))
    assert demanded["status"] == "DEMANDED"
    assert _iso_instant(demanded["window_end"]) == _iso_instant("2027-05-29T00:00:00Z")

    # At exactly window_end the closed interval still blocks the second demand.
    set_clock("2027-05-29T00:00:00Z")
    resp = api.demand_enforcement(bundle2["action"]["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_ENFORCEMENT_WINDOW_OPEN)


def test_enforcement_demand_succeeds_after_window_end(api):
    """PRD Section 3.6: "A `ServicerAgent` issues a demand, moving the action from `DRAFT` to `DEMANDED` and stamping `demanded_at`; `window_end` is set to exactly 30 days after the demand."
    PRD Section 3.6: "Demands are mutually exclusive per guarantor identity across loans: a demand is rejected with `ERR_ENFORCEMENT_WINDOW_OPEN` when any other action exists whose guarantor has the same `email`, in `DEMANDED` or `ESCALATED` status, whose closed window from its `demanded_at` through its `window_end` contains the current clock."

    Design: Difficulty/resource_temporal_overlap/enforcement_demand_window_closed_interval
    """
    bundle1, bundle2 = _two_defaulted_loans_shared_guarantor_email(api)

    set_clock("2027-04-29T00:00:00Z")
    validate_success(api.demand_enforcement(bundle1["action"]["id"], SERVICER))

    # One day past window_end the first window no longer contains the clock.
    set_clock("2027-05-30T00:00:00Z")
    second = validate_success(api.demand_enforcement(bundle2["action"]["id"], SERVICER))
    assert second["status"] == "DEMANDED"


# ---------------------------------------------------------------------------
# Queue B: state_machines — default cascade side effect
# ---------------------------------------------------------------------------

def test_default_creates_enforcement_draft_side_effect(api):
    """PRD Section 3.5: "When it reaches 4, the loan moves to `DEFAULTED` and an `EnforcementAction` is created in `DRAFT` referencing the loan and its guarantor; the merchant remains `SUSPENDED`."

    Design: Corner/state_machines/default_creates_enforcement_draft_side_effect
    """
    bundle = _active_standard_bundle()
    loan = drive_loan_missed_periods(bundle["loan"]["id"], 4)
    assert loan["status"] == "DEFAULTED"

    actions = validate_success(
        api.list_loan_enforcement_actions(bundle["loan"]["id"], ADMIN))
    assert len(actions) == 1, "exactly one auto-created enforcement action"
    assert actions[0]["status"] == "DRAFT"
    assert actions[0]["guarantor_id"] == bundle["guarantor"]["id"]


# ---------------------------------------------------------------------------
# Queue B: validations — catch-up and evaluation gates
# ---------------------------------------------------------------------------

def test_catchup_exceeds_outstanding_rejected(api):
    """PRD Section 3.5: "A `ServicerAgent` settles it — permitted while the loan is `ACTIVE`, `DELINQUENT`, or `DEFAULTED`, else `ERR_LOAN_ALREADY_TERMINAL` — provided the amount does not exceed the loan's `remaining_balance_cents`, else `ERR_CATCHUP_EXCEEDS_OUTSTANDING`."

    Design: Corner/validations/catchup_exceeds_outstanding_rejected
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    assert bundle["loan"]["remaining_balance_cents"] == 555_000

    payment = validate_success(api.create_catch_up(
        loan_id, create_catch_up_payload(555_001),
        make_merchant_owner_headers(bundle["merchant"]["id"])), expected_status=201)
    resp = api.settle_catch_up(payment["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_CATCHUP_EXCEEDS_OUTSTANDING)
    assert validate_success(
        api.get_catch_up(payment["id"], SERVICER))["status"] == "INITIATED"


def test_evaluate_period_too_early_rejected(api):
    """PRD Section 3.5: "Evaluation requires the period to have fully elapsed: the clock must have reached `activated_at` plus 60 times the current `repayment_period_index` plus one days — otherwise `ERR_PERIOD_NOT_ELAPSED`."

    Design: Corner/validations/evaluate_period_too_early_rejected
    """
    bundle = _active_standard_bundle()
    loan_id = bundle["loan"]["id"]

    set_clock("2026-10-30T00:00:00Z")  # day 59 of period 0
    resp = api.evaluate_period(loan_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ELAPSED)
    assert get_loan(loan_id)["repayment_period_index"] == 0, "period not advanced"


def test_loan_already_terminal_error_on_catchup(api):
    """PRD Section 3.5: "A `ServicerAgent` settles it — permitted while the loan is `ACTIVE`, `DELINQUENT`, or `DEFAULTED`, else `ERR_LOAN_ALREADY_TERMINAL` — provided the amount does not exceed the loan's `remaining_balance_cents`, else `ERR_CATCHUP_EXCEEDS_OUTSTANDING`."

    Design: Corner/errors/loan_already_terminal_error_on_catchup
    """
    bundle = create_active_loan(principal_cents=500_000)
    repay_loan_fully(bundle)
    assert get_loan(bundle["loan"]["id"])["status"] == "REPAID"

    payment = validate_success(api.create_catch_up(
        bundle["loan"]["id"], create_catch_up_payload(1000),
        make_merchant_owner_headers(bundle["merchant"]["id"])), expected_status=201)
    resp = api.settle_catch_up(payment["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_LOAN_ALREADY_TERMINAL)
    assert validate_success(
        api.get_catch_up(payment["id"], SERVICER))["status"] == "INITIATED"
