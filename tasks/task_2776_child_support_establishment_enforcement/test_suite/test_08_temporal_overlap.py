"""
Two intervals competing for the same resource, at both kinds of endpoint.

The support order's effective interval is closed on both ends and open-ended
while the order is live, so it collides in both time directions; the charge's
billing period is half-open, so two periods that merely touch are both legal.
Each scenario also crosses the scoping key, which is where the collision stops.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import FINANCE_OFFICER_HEADERS, SUPERVISING_ATTORNEY_HEADERS


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _live_order_with_three_calculated_neighbours() -> Tuple[fx.Scenario, Dict[str, Any]]:
    """
    One `ENTERED` current-support order effective 2026-08-01 with no termination
    date, and three further orders taken only as far as `CALCULATED`: a later
    current-support order at 2027-01-01, an earlier one at 2026-01-01, and a
    medical-support order at that same later date.

    No charge and no compromise offer is ever created, so the vacatur that ends
    the scenario is unguarded and cascades nowhere.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Pia Quill",
            "ssn_last4": "3030",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Rex Quill",
            "ssn_last4": "3131",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    neighbours: Dict[str, Any] = {}
    for key, order_type, effective_date, medical in (
        ("later", "CURRENT_SUPPORT", "2027-01-01", 0),
        ("earlier", "CURRENT_SUPPORT", "2026-01-01", 0),
        ("medical", "MEDICAL_SUPPORT", "2027-01-01", 20000),
    ):
        drafted = fx.draft_order(
            scenario.case_id,
            order_type=order_type,
            origin_state_code="MN",
            effective_date=effective_date,
            medical_support_monthly_cents=medical,
        )
        neighbours[key] = fx.calculate_order(drafted["id"])
    return scenario, neighbours


def _order_with_two_touching_current_support_periods() -> fx.Scenario:
    """
    An entered order at 75,000 cents carrying a 20,000-cent medical add-on and
    two current-support charges whose periods touch at 2026-09-01.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Sol Reyes",
            "ssn_last4": "3232",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Tam Reyes",
            "ssn_last4": "3333",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 20000,
        },
    )
    scenario.charges = [
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-15",
        ),
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-09-01",
            period_end_date="2026-10-01",
            due_date="2026-09-15",
        ),
    ]
    return scenario


# ---------------------------------------------------------------------------
# The order interval: closed on both ends, and open-ended while it is live
# ---------------------------------------------------------------------------


def test_01_a_later_order_collides_with_the_open_ended_live_interval():
    """
    The live order has no termination date, so its interval never runs out.

    No other `ENTERED` order of the same `order_type` on the case may have an overlapping effective interval; intervals are closed on both ends, running from `effective_date` to `terminated_date`, and abutment is legal only when the earlier order's `terminated_date` is exactly one day before the new order's `effective_date`.

    Design: Difficulty/resource_temporal_overlap/order_interval_overlap_closed_interval_semantics
    """
    scenario, neighbours = _live_order_with_three_calculated_neighbours()
    later = neighbours["later"]

    assert scenario.order["status"] == "ENTERED"
    assert scenario.order["effective_date"] == "2026-08-01"
    assert scenario.order.get("terminated_date") is None
    assert later["status"] == "CALCULATED"
    assert later["effective_date"] == "2027-01-01"

    response = api_client.enter_order(
        later["id"], f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS
    )
    validate_error(response, ApiErrorId.ORDER_INTERVAL_OVERLAP.value, 409)
    assert fx.read_order(later["id"])["status"] == "CALCULATED"


def test_02_an_earlier_order_collides_with_the_same_interval_from_the_other_side():
    """
    Five months before the live order is refused just as five months after is.

    An overlap is refused with `ERR_ORDER_INTERVAL_OVERLAP` (HTTP 409).

    Design: Difficulty/resource_temporal_overlap/order_interval_overlap_closed_interval_semantics
    """
    scenario, neighbours = _live_order_with_three_calculated_neighbours()
    earlier = neighbours["earlier"]

    assert earlier["effective_date"] == "2026-01-01"
    assert earlier["effective_date"] < scenario.order["effective_date"]

    response = api_client.enter_order(
        earlier["id"], f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS
    )
    validate_error(response, ApiErrorId.ORDER_INTERVAL_OVERLAP.value, 409)
    # The live order is untouched by the refusal.
    assert fx.read_order(scenario.order_id)["status"] == "ENTERED"
    assert fx.read_order(scenario.order_id).get("terminated_date") is None


def test_03_a_medical_order_at_the_refused_date_enters_freely():
    """
    The identical effective date passes because the scoping key differs.

    Interval-overlap checking, the controlling-order determination and the enforcement obligation lookup are all scoped per `order_type`, which means a case may legitimately carry one live `CURRENT_SUPPORT` order and one live `MEDICAL_SUPPORT` order at the same time without either colliding with the other.

    Design: Difficulty/resource_temporal_overlap/order_interval_overlap_closed_interval_semantics
    """
    scenario, neighbours = _live_order_with_three_calculated_neighbours()
    medical = neighbours["medical"]
    later = neighbours["later"]

    assert medical["effective_date"] == later["effective_date"]
    assert medical["order_type"] == "MEDICAL_SUPPORT"

    entered = fx.enter_order(medical["id"])
    assert entered["status"] == "ENTERED"
    assert entered["next_accrual_due_date"] == "2027-01-01"
    # The current-support order at that very date is still refused.
    validate_error(
        api_client.enter_order(later["id"], f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS),
        ApiErrorId.ORDER_INTERVAL_OVERLAP.value,
        409,
    )


def test_04_vacatur_one_day_before_the_new_date_makes_the_later_order_legal():
    """
    The live interval finally closes, and it closes exactly on the abutment day.

    From `ENTERED` it is guarded — no compromise offer on the case may be in `ACCEPTED` or `ACTIVE`, because a live settlement plan is priced against the very charges vacatur would destroy — and it cascades four ways.

    `terminated_date` is set to the current logical clock date.

    Design: Difficulty/resource_temporal_overlap/order_interval_overlap_closed_interval_semantics
    """
    scenario, neighbours = _live_order_with_three_calculated_neighbours()
    later = neighbours["later"]

    fx.set_clock("2026-12-31T00:00:00Z")
    vacated = fx.vacate_order(scenario.order_id, "CLERICAL_ERROR")

    assert vacated["status"] == "VACATED"
    # Exactly one day before 2027-01-01, which is the legal abutment.
    assert vacated["terminated_date"] == "2026-12-31"

    entered = fx.enter_order(later["id"])
    assert entered["status"] == "ENTERED"
    assert entered["monthly_obligation_cents"] == 75000
    assert entered["next_accrual_due_date"] == "2027-01-01"


# ---------------------------------------------------------------------------
# The charge period: half-open, so touching is legal
# ---------------------------------------------------------------------------


def test_05_two_charge_periods_that_touch_at_the_month_boundary_are_both_accepted():
    """
    The second period starts on the day the first one excludes.

    Because the period is half-open, adjacency is legal and overlap is not.

    A new charge's `[period_start_date, period_end_date)` interval may not overlap the interval of any existing non-`VOID` charge of the *same* `charge_type` on the *same* order; a new period whose start equals a previous period's end touches but does not overlap and is accepted.

    Design: Difficulty/resource_temporal_overlap/charge_period_overlap_half_open_interval_semantics
    """
    scenario = _order_with_two_touching_current_support_periods()
    first, second = scenario.charges

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert first["period_end_date"] == second["period_start_date"] == "2026-09-01"
    for charge in (first, second):
        assert charge["status"] == "OPEN"
        assert charge["charge_type"] == "CURRENT_SUPPORT"
        # Defaulted from the order rather than supplied by the caller.
        assert charge["amount_cents"] == 75000
        assert charge["unpaid_balance_cents"] == 75000
        assert charge["paid_cents"] == 0
        assert charge["interest_accrued_cents"] == 0


def test_06_a_period_that_straddles_both_accepted_periods_is_refused():
    """
    Mid-August to mid-September intersects each neighbour by half a month.

    An overlap answers with `ERR_CHARGE_PERIOD_OVERLAP` (HTTP 409).

    Design: Difficulty/resource_temporal_overlap/charge_period_overlap_half_open_interval_semantics
    """
    scenario = _order_with_two_touching_current_support_periods()

    response = api_client.post_charge(
        scenario.order_id,
        f.charge_payload(
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-15",
            period_end_date="2026-09-15",
            due_date="2026-08-20",
        ),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.CHARGE_PERIOD_OVERLAP.value, 409)

    # The refusal recorded nothing: the charged total still covers two charges.
    assert fx.read_case(scenario.case_id)["total_charged_principal_cents"] == 150000


def test_07_the_same_period_is_free_for_a_medical_charge_and_then_occupied():
    """
    August is available once more under the medical scope, and only once.

    The scoping matters twice over: a medical charge and a current-support charge may cover exactly the same month on the same order without conflict, and a voided charge leaves the interval free for a corrected re-post.

    `amount_cents` is optional: omitted, it defaults to the order's `monthly_obligation_cents` for a `CURRENT_SUPPORT` charge and to the order's `medical_support_monthly_cents` for a `MEDICAL_SUPPORT` charge.

    Design: Difficulty/resource_temporal_overlap/charge_period_overlap_half_open_interval_semantics
    """
    scenario = _order_with_two_touching_current_support_periods()

    medical = fx.post_charge(
        scenario.order_id,
        charge_type="MEDICAL_SUPPORT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-15",
    )
    assert medical["status"] == "OPEN"
    assert medical["period_start_date"] == scenario.charges[0]["period_start_date"]
    assert medical["period_end_date"] == scenario.charges[0]["period_end_date"]
    # The medical add-on, not the monthly obligation.
    assert medical["amount_cents"] == 20000

    response = api_client.post_charge(
        scenario.order_id,
        f.charge_payload(
            charge_type="MEDICAL_SUPPORT",
            period_start_date="2026-08-20",
            period_end_date="2026-09-20",
            due_date="2026-08-25",
        ),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.CHARGE_PERIOD_OVERLAP.value, 409)


def test_08_only_the_three_accepted_charges_reached_the_ledger():
    """
    Two refusals, three rows, and 170,000 cents of principal.

    It adds its `amount_cents` to the case's `total_charged_principal_cents` and advances the order's `next_accrual_due_date` by one month, and it increases both the case's and the order's `version` by 1.

    Reading a case is likewise a computing read: `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `interest_receivable_cents` are all recomputed before the row is returned, with `arrears_principal_cents` defined as the sum of `unpaid_balance_cents` across the case's charges whose `status` is `OPEN` and whose `due_date` falls on or before the current logical clock date.

    Design: Difficulty/resource_temporal_overlap/charge_period_overlap_half_open_interval_semantics
    """
    scenario = _order_with_two_touching_current_support_periods()

    fx.post_charge(
        scenario.order_id,
        charge_type="MEDICAL_SUPPORT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-15",
    )
    for payload in (
        f.charge_payload(
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-15",
            period_end_date="2026-09-15",
            due_date="2026-08-20",
        ),
        f.charge_payload(
            charge_type="MEDICAL_SUPPORT",
            period_start_date="2026-08-20",
            period_end_date="2026-09-20",
            due_date="2026-08-25",
        ),
    ):
        api_client.post_charge(scenario.order_id, payload, FINANCE_OFFICER_HEADERS)

    rows, meta = validate_paginated(
        api_client.list_charges(FINANCE_OFFICER_HEADERS, {"order_id": scenario.order_id})
    )
    assert len(rows) == 3
    assert meta["total_count"] == 3

    settled = fx.read_case(scenario.case_id)
    assert settled["total_charged_principal_cents"] == 170000
    # Every due date has now passed, so all of it is arrears principal.
    fx.set_clock("2026-10-01T00:00:00Z")
    assert fx.read_case(scenario.case_id)["arrears_principal_cents"] == 170000
