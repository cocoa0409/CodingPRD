"""The monthly cycle: recording a metered month, settling it, unwinding it.

Every figure asserted here is a figure the contract derives: the seasonality
expectation, the guarantee floor, the six-step invoice waterfall and the credit
ledger the waterfall moves.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import assert_credit_counters
from test_helpers.fixtures import (
    activate,
    book_lease,
    book_ppa,
    make_homeowner,
    make_tariff,
    read_agreement,
    reconcile,
    record_period,
    set_clock,
)


def _active_ppa_on_pinned_terms(api, clock, **overrides):
    """The shared PPA terms: start 2025-01-01, 0.029 escalator, 14750 base rate."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(
        api,
        owner["id"],
        schedule["id"],
        contract_start_date="2025-01-01",
        escalator_pct=0.029,
        base_ppa_rate_per_kwh_millicents=14750,
        guaranteed_annual_kwh=9600,
        guarantee_band_pct=0.05,
        **overrides,
    )
    activate(api, agreement["id"])
    return owner, schedule, agreement


def test_recording_the_same_month_twice_is_refused_while_neighbours_are_not(api):
    """The uniqueness key is the agreement plus the calendar month.

    §3.3: "At most one month may exist for a given agreement and calendar month;
    a second attempt is refused with `ERR_DUPLICATE_PERIOD`."

    Design: Corner/validations/second_production_period_for_the_same_month_is_rejected
    """
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-08-01T00:00:00Z")
    june = record_period(api, agreement["id"], 2026, 6, 950)

    validate_error(
        api.create_period(
            F.period_payload(agreement["id"], 2026, 6, 1010), U.admin_headers()
        ),
        E.ERR_DUPLICATE_PERIOD,
    )

    kept = validate_success(api.get_period(june["id"], U.agent_headers()), 200)
    assert kept["metered_kwh"] == 950

    may = validate_success(
        api.create_period(
            F.period_payload(agreement["id"], 2026, 5, 900), U.agent_headers()
        ),
        201,
    )
    last_june = validate_success(
        api.create_period(
            F.period_payload(agreement["id"], 2025, 6, 900), U.agent_headers()
        ),
        201,
    )
    assert may["period_month"] == 5
    assert last_june["period_year"] == 2025


def test_a_month_settles_only_from_the_first_instant_of_the_next_month(api):
    """One second before the boundary the month is still open.

    §3.3: "A month may only be reconciled once its month has fully elapsed
    against the logical clock: if the clock instant is still before the first
    instant of the month **after** the period month, the request is refused with
    `ERR_PERIOD_NOT_ELAPSED`."

    Design: Corner/validations/reconciling_a_month_that_has_not_fully_elapsed_is_rejected_until_the_boundary
    """
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-07-31T23:59:59Z")
    july = record_period(api, agreement["id"], 2026, 7, 1200)

    validate_error(
        api.reconcile_period(
            july["id"], F.reconcile_payload(True), U.agent_headers()
        ),
        E.ERR_PERIOD_NOT_ELAPSED,
    )
    assert validate_success(api.get_period(july["id"], U.agent_headers()), 200)[
        "status"
    ] == C.PERIOD_RECORDED

    set_clock(api, "2026-08-01T00:00:00Z")
    settled = reconcile(api, july["id"], issue_credit=True)

    assert settled["status"] == C.PERIOD_RECONCILED
    assert settled["gross_expected_kwh"] == 1085
    assert settled["guarantee_floor_kwh"] == 1031
    assert settled["shortfall_kwh"] == 0
    assert settled["credit_cents"] == 0
    assert settled["gross_due_cents"] == 18214
    assert settled["credit_applied_cents"] == 0
    assert settled["net_due_cents"] == 18214
    assert settled["due_date"] == "2026-08-21"
    assert settled["late_fee_cents"] == 0
    assert settled["total_invoiced_cents"] == 18214


def test_issuing_shortfall_credit_syncs_the_agreement_ledger(api):
    """The month earns credit for the agreement but never spends it on itself.

    §3.3: "the month instead moves `RECORDED → CREDIT_ISSUED`: every effect of
    the plain reconciliation applies, and in addition the agreement's
    `credit_earned_cents` and `credit_balance_cents` are each increased by the
    month's `credit_cents`." §3.3 step two: "the available credit is read as the
    agreement's `credit_balance_cents` **as it stood before this month issued any
    credit of its own**".

    Design: Corner/state_machines/issuing_shortfall_credit_syncs_the_agreement_ledger
    """
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-07-10T00:00:00Z")
    june = record_period(api, agreement["id"], 2026, 6, 950)

    settled = reconcile(api, june["id"], issue_credit=True)

    assert settled["status"] == C.PERIOD_CREDIT_ISSUED
    assert settled["contract_year"] == 2
    assert settled["escalated_rate_millicents"] == 15178
    assert settled["guarantee_floor_kwh"] == 1021
    assert settled["shortfall_kwh"] == 71
    assert settled["credit_rate_millicents"] == 15178
    assert settled["credit_cents"] == 1078
    assert settled["gross_due_cents"] == 14419
    assert settled["credit_applied_cents"] == 0
    assert settled["net_due_cents"] == 14419
    assert settled["late_fee_cents"] == 0
    assert settled["total_invoiced_cents"] == 14419

    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=1078, applied=0, balance=1078
    )


def test_reopening_a_credited_month_unwinds_the_settlement_and_the_ledger(api):
    """Reopening removes exactly the cents the settlement added.

    §3.3: "A month in `CREDIT_ISSUED` moves back to `RECORDED` with one additional
    unwinding: the agreement's `credit_earned_cents` is reduced by the month's
    `credit_cents` and its `credit_balance_cents` reduced by the same amount, the
    applied-credit reversal above is performed as well, and the month's
    `credit_cents` is reset to 0 alongside the five settlement figures."

    Design: Corner/endpoints/reopen_action_endpoint_unwinds_a_settled_month_completely
    """
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-08-01T00:00:00Z")
    june = record_period(api, agreement["id"], 2026, 6, 950)
    settled = reconcile(api, june["id"], issue_credit=True)

    assert settled["credit_cents"] == 1078
    assert settled["gross_due_cents"] == 14419
    assert settled["credit_applied_cents"] == 0
    assert settled["net_due_cents"] == 14419
    assert settled["late_fee_cents"] == 216
    assert settled["total_invoiced_cents"] == 14635

    reopened = validate_success(api.reopen_period(june["id"], U.admin_headers()), 200)

    assert reopened["status"] == C.PERIOD_RECORDED
    assert reopened["credit_cents"] == 0
    assert reopened["gross_due_cents"] == 0
    assert reopened["credit_applied_cents"] == 0
    assert reopened["net_due_cents"] == 0
    assert reopened["late_fee_cents"] == 0
    assert reopened["total_invoiced_cents"] == 0
    assert reopened["gross_expected_kwh"] == 1075
    assert reopened["adjusted_expected_kwh"] == 1075
    assert reopened["metered_kwh"] == 950

    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=0, applied=0, balance=0
    )


def test_reopening_a_month_is_reserved_to_the_portfolio_admin(api):
    """The agent settles the month; only the admin may unwind it.

    §3.3: "Reopening a month is the compensating operation, and only a
    `PortfolioAdmin` may perform it."

    Design: Corner/endpoints/reopen_action_endpoint_unwinds_a_settled_month_completely
    """
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-08-01T00:00:00Z")
    june = record_period(api, agreement["id"], 2026, 6, 950)
    reconcile(api, june["id"], issue_credit=True)

    validate_error(
        api.reopen_period(june["id"], U.agent_headers()), E.ERR_UNAUTHORIZED
    )

    untouched = validate_success(api.get_period(june["id"], U.agent_headers()), 200)
    assert untouched["status"] == C.PERIOD_CREDIT_ISSUED
    assert untouched["total_invoiced_cents"] == 14635
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=1078, applied=0, balance=1078
    )


def test_out_of_order_recording_still_settles_each_month_on_its_own_dates(api):
    """June recorded before May: each month keeps its own weight and due date.

    §3.3: "A month's `contract_year` is computed exactly like an agreement's
    current contract year, except that the month's own `period_year` and
    `period_month` stand in for the clock". §3.3 step five: "`late_fee_cents` is
    1.5 percent of `net_due_cents`, rounded to a whole cent, but only when the
    current clock date is past the month's `due_date`; otherwise it is 0."

    Design: Corner/calculations/out_of_order_period_creation_still_settles_each_month_on_its_own_dates
    """
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-07-10T00:00:00Z")
    june = record_period(api, agreement["id"], 2026, 6, 950)
    may = record_period(api, agreement["id"], 2026, 5, 900)

    settled_may = reconcile(api, may["id"], issue_credit=True)
    settled_june = reconcile(api, june["id"], issue_credit=True)

    assert settled_may["due_date"] == "2026-06-21"
    assert settled_may["gross_expected_kwh"] == 1046
    assert settled_may["guarantee_floor_kwh"] == 994
    assert settled_may["shortfall_kwh"] == 94
    assert settled_may["credit_cents"] == 1427
    assert settled_may["gross_due_cents"] == 13660
    assert settled_may["credit_applied_cents"] == 0
    assert settled_may["net_due_cents"] == 13660
    assert settled_may["late_fee_cents"] == 205
    assert settled_may["total_invoiced_cents"] == 13865

    assert settled_june["due_date"] == "2026-07-21"
    assert settled_june["gross_expected_kwh"] == 1075
    assert settled_june["guarantee_floor_kwh"] == 1021
    assert settled_june["shortfall_kwh"] == 71
    assert settled_june["credit_cents"] == 1078
    assert settled_june["gross_due_cents"] == 14419
    assert settled_june["credit_applied_cents"] == 1427
    assert settled_june["net_due_cents"] == 12992
    assert settled_june["late_fee_cents"] == 0
    assert settled_june["total_invoiced_cents"] == 12992

    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=2505, applied=1427, balance=1078
    )


def test_lease_rent_rounds_half_up_and_credits_at_the_retail_rate(api):
    """The lease variant escalates the rent, and its credit uses the tariff rate.

    §3.2: "Under a `LEASE`, `escalated_rate_millicents` stays 0, the escalated
    rent for a contract year is `base_monthly_lease_cents` multiplied by the
    factor and rounded to a whole cent". §3.3: "`credit_rate_millicents` is the
    contract-year `escalated_rate_millicents` for a `PPA` agreement and the
    agreement's current tariff `retail_rate_per_kwh_millicents` for a `LEASE`
    agreement."

    Design: Corner/calculations/lease_rent_rounds_half_up_in_the_third_contract_year
    """
    set_clock(api, "2026-07-10T00:00:00Z")
    owner = make_homeowner(api, full_name="Iris Kwan", fico_score=705, dti_ratio=0.31,
                           monthly_income_cents=980000)
    schedule = make_tariff(api)
    agreement = book_lease(
        api,
        owner["id"],
        schedule["id"],
        contract_start_date="2024-06-01",
        escalator_pct=0.019,
        base_monthly_lease_cents=12900,
        guaranteed_annual_kwh=8400,
        system_dc_kw=6.4,
        guarantee_band_pct=0.05,
    )
    activate(api, agreement["id"])

    month = record_period(
        api,
        agreement["id"],
        2026,
        6,
        800,
        auto_reconcile=True,
        auto_issue_credit=True,
    )

    assert month["contract_year"] == 3
    assert month["escalated_monthly_rent_cents"] == 13395
    assert month["escalated_rate_millicents"] == 0
    assert month["gross_expected_kwh"] == 941
    assert month["adjusted_expected_kwh"] == 941
    assert month["guarantee_floor_kwh"] == 894
    assert month["shortfall_kwh"] == 94
    assert month["credit_rate_millicents"] == 32500
    assert month["credit_cents"] == 3055
    assert month["gross_due_cents"] == 13395
    assert month["credit_applied_cents"] == 0
    assert month["net_due_cents"] == 13395
    assert month["late_fee_cents"] == 0
    assert month["total_invoiced_cents"] == 13395
    assert month["status"] == C.PERIOD_CREDIT_ISSUED
    assert read_agreement(api, agreement["id"])["credit_balance_cents"] == 3055


def test_credit_application_is_capped_by_the_smaller_of_the_month_and_the_balance(api):
    """Step three is a minimum, so the invoice never turns into a payout.

    §3.3 step three: "`credit_applied_cents` is the smaller of `gross_due_cents`
    and that available credit." §2.9: "`credit_balance_cents` equals
    `credit_earned_cents` minus `credit_applied_cents`, and it is never negative."

    Design: Corner/cross_cutting_complexity_layers/credit_application_is_capped_by_the_smaller_of_the_month_and_the_balance
    """
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-05-10T00:00:00Z")

    april = record_period(
        api, agreement["id"], 2026, 4, 0, auto_reconcile=True, auto_issue_credit=True
    )
    assert april["status"] == C.PERIOD_CREDIT_ISSUED
    assert april["gross_expected_kwh"] == 941
    assert april["guarantee_floor_kwh"] == 894
    assert april["shortfall_kwh"] == 894
    assert april["credit_cents"] == 13569
    assert april["gross_due_cents"] == 0
    assert april["credit_applied_cents"] == 0
    assert april["net_due_cents"] == 0
    assert april["total_invoiced_cents"] == 0
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=13569, applied=0, balance=13569
    )

    set_clock(api, "2027-01-05T00:00:00Z")
    december = record_period(
        api, agreement["id"], 2026, 12, 400, auto_reconcile=True
    )
    assert december["contract_year"] == 2
    assert december["gross_due_cents"] == 6071
    assert december["credit_applied_cents"] == 6071
    assert december["net_due_cents"] == 0
    assert december["late_fee_cents"] == 0
    assert december["total_invoiced_cents"] == 0
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=13569, applied=6071, balance=7498
    )

    november = record_period(
        api, agreement["id"], 2026, 11, 494, auto_reconcile=True
    )
    assert november["gross_due_cents"] == 7498
    assert november["credit_applied_cents"] == 7498
    assert november["net_due_cents"] == 0
    assert november["late_fee_cents"] == 0
    assert november["total_invoiced_cents"] == 0
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=13569, applied=13569, balance=0
    )

    set_clock(api, "2027-02-05T00:00:00Z")
    january = record_period(
        api, agreement["id"], 2027, 1, 500, auto_reconcile=True
    )
    assert january["contract_year"] == 3
    assert january["gross_due_cents"] == 7809
    assert january["credit_applied_cents"] == 0
    assert january["net_due_cents"] == 7809
    assert january["total_invoiced_cents"] == 7809
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=13569, applied=13569, balance=0
    )


def _three_identical_sites(api):
    """Three separately booked PPAs on identical terms for one homeowner."""
    set_clock(api, "2026-07-10T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreements = []
    for address in ("918 Alder Way, Fremont CA", "920 Alder Way, Fremont CA",
                    "922 Alder Way, Fremont CA"):
        agreement = book_ppa(
            api,
            owner["id"],
            schedule["id"],
            site_address=address,
            contract_start_date="2025-01-01",
            escalator_pct=0.029,
            base_ppa_rate_per_kwh_millicents=14750,
            guaranteed_annual_kwh=9600,
            guarantee_band_pct=0.05,
        )
        activate(api, agreement["id"])
        agreements.append(agreement)
    return agreements


def test_june_expectation_and_floor_round_half_up_to_the_same_integers(api):
    """9600 × 0.1120 is 1075.2 and 1075 × 0.95 is 1021.25: both round half up.

    §3.3: "`gross_expected_kwh` is `guaranteed_annual_kwh` multiplied by the
    weight for the month's `period_month` and rounded to a whole kilowatt-hour".
    §3.3: "`guarantee_floor_kwh` is `adjusted_expected_kwh` multiplied by one
    minus `guarantee_band_pct`, rounded to a whole kilowatt-hour, so the
    comparison boundary is always an integer."

    Design: Difficulty/boundary_precision_check/metered_kwh_exactly_at_guarantee_floor_earns_no_credit
    """
    agreements = _three_identical_sites(api)

    for agreement, metered in zip(agreements, (1022, 1021, 1020)):
        month = record_period(
            api,
            agreement["id"],
            2026,
            6,
            metered,
            auto_reconcile=True,
            auto_issue_credit=True,
        )
        assert month["gross_expected_kwh"] == 1075
        assert month["adjusted_expected_kwh"] == 1075
        assert month["guarantee_floor_kwh"] == 1021
        assert month["excused_days"] == 0
        assert month["due_date"] == "2026-07-21"


@pytest.mark.parametrize(
    "metered,shortfall,credit,status,gross_due,earned,balance",
    [
        (1022, 0, 0, C.PERIOD_RECONCILED, 15512, 0, 0),
        (1021, 0, 0, C.PERIOD_RECONCILED, 15497, 0, 0),
        (1020, 1, 15, C.PERIOD_CREDIT_ISSUED, 15482, 15, 15),
    ],
)
def test_production_exactly_at_the_floor_earns_nothing(
    api, metered, shortfall, credit, status, gross_due, earned, balance
):
    """Only production strictly below the floor is a shortfall.

    §3.3: "If `metered_kwh` is **strictly** below that floor, `shortfall_kwh` is
    the floor minus the metered figure; otherwise `shortfall_kwh` is 0 —
    production exactly equal to the floor earns nothing." §3.3: "`credit_cents`
    is `shortfall_kwh` multiplied by `credit_rate_millicents`, divided by 1000 and
    rounded to a whole cent."

    Design: Difficulty/boundary_precision_check/metered_kwh_exactly_at_guarantee_floor_earns_no_credit
    """
    agreement = _three_identical_sites(api)[0]

    month = record_period(
        api,
        agreement["id"],
        2026,
        6,
        metered,
        auto_reconcile=True,
        auto_issue_credit=True,
    )

    assert month["shortfall_kwh"] == shortfall
    assert month["credit_cents"] == credit
    assert month["status"] == status
    assert month["gross_due_cents"] == gross_due
    assert month["credit_applied_cents"] == 0
    assert month["net_due_cents"] == gross_due
    assert month["late_fee_cents"] == 0
    assert month["total_invoiced_cents"] == gross_due

    assert_credit_counters(
        read_agreement(api, agreement["id"]),
        earned=earned,
        applied=0,
        balance=balance,
    )


def _two_late_months_of_the_first_contract_year(api):
    """January and February 2025 recorded, then settled long after their due dates."""
    _, _, agreement = _active_ppa_on_pinned_terms(api, "2026-08-01T00:00:00Z")
    january = record_period(api, agreement["id"], 2025, 1, 400)
    february = record_period(api, agreement["id"], 2025, 2, 580)
    return agreement, january, february


def test_a_month_cannot_spend_the_credit_it_is_issuing_in_the_same_settlement(api):
    """January earns 1092 cents of credit and still pays its full gross amount.

    §3.3 step two: "the available credit is read as the agreement's
    `credit_balance_cents` **as it stood before this month issued any credit of its
    own**." §3.3: "And the credit available to a month is the balance before that
    same month's own shortfall credit is issued, so a month cannot pay itself with
    the credit it just earned." §3.3 step five: "`late_fee_cents` is 1.5 percent of
    `net_due_cents`, rounded to a whole cent, but only when the current clock date
    is past the month's `due_date`".

    Design: Difficulty/combinatorial_formula/late_fee_on_net_after_credit_and_credit_read_before_own_issue
    """
    agreement, january, _ = _two_late_months_of_the_first_contract_year(api)

    settled = reconcile(api, january["id"], issue_credit=True)

    assert settled["status"] == C.PERIOD_CREDIT_ISSUED
    assert settled["contract_year"] == 1
    assert settled["escalated_rate_millicents"] == 14750
    assert settled["shortfall_kwh"] == 74
    assert settled["credit_rate_millicents"] == 14750
    assert settled["credit_cents"] == 1092
    assert settled["gross_due_cents"] == 5900
    assert settled["credit_applied_cents"] == 0
    assert settled["net_due_cents"] == 5900
    assert settled["due_date"] == "2025-02-21"
    assert settled["late_fee_cents"] == 89
    assert settled["total_invoiced_cents"] == 5989

    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=1092, applied=0, balance=1092
    )


def test_the_late_fee_is_charged_on_the_net_amount_not_the_gross(api):
    """February draws January's credit first, so the fee is 112 cents, not 128.

    §3.3 step five: "`late_fee_cents` is 1.5 percent of `net_due_cents`, rounded to
    a whole cent". §3.3 step three: "`credit_applied_cents` is the smaller of
    `gross_due_cents` and that available credit" and step four: "`net_due_cents` is
    `gross_due_cents` minus `credit_applied_cents`".

    Design: Difficulty/combinatorial_formula/late_fee_on_net_after_credit_and_credit_read_before_own_issue
    """
    agreement, january, february = _two_late_months_of_the_first_contract_year(api)
    reconcile(api, january["id"], issue_credit=True)

    settled = reconcile(api, february["id"], issue_credit=False)

    assert settled["status"] == C.PERIOD_RECONCILED
    assert settled["shortfall_kwh"] == 0
    assert settled["credit_cents"] == 0
    assert settled["gross_due_cents"] == 8555
    assert settled["credit_applied_cents"] == 1092
    assert settled["net_due_cents"] == 7463
    assert settled["late_fee_cents"] == 112
    assert settled["late_fee_cents"] != 128
    assert settled["total_invoiced_cents"] == 7575

    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=1092, applied=1092, balance=0
    )
