"""End-of-term elections: the window, the three prices and the three futures.

Twenty or twenty-five years in the homeowner picks one of three outcomes, and
the choice is boxed in on every side: a window that is inclusive at both edges,
three exclusivity conditions, one depreciation figure that prices all three
options, and an execution step that is blocked by physical work in flight.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import assert_credit_counters, assert_instant_equals
from test_helpers.fixtures import (
    accept_election,
    activate,
    approve_roof_order,
    book_ppa,
    execute_election,
    make_filing,
    make_homeowner,
    make_tariff,
    open_prepayment,
    open_roof_order,
    quote_roof_order,
    read_agreement,
    record_period,
    set_clock,
    submit_election,
)

# A ten-year PPA that started 2016-09-01 ends 2026-08-31, so its election
# window runs 2026-03-04 through 2026-08-01 with both edges inside it. Nine
# whole years have elapsed on every one of those days.
TEN_YEAR_TERMS = {
    "term_years": 10,
    "contract_start_date": "2016-09-01",
    "escalator_pct": 0.029,
    "base_ppa_rate_per_kwh_millicents": 14750,
    "guaranteed_annual_kwh": 9600,
    "system_dc_kw": 7.2,
    "guarantee_band_pct": 0.05,
}
CONTRACT_END_DATE = "2026-08-31"
WINDOW_OPEN_DATE = "2026-03-04"
WINDOW_CLOSE_DATE = "2026-08-01"
ELAPSED_FULL_YEARS = 9
RESIDUAL_PCT = 0.595
# 7.20 kW installs for 2304000 cents at 320000 cents per kilowatt, and 0.5950
# of that is the purchase price.
FAIR_MARKET_VALUE_CENTS = 1370880
# Three quarters of the contract-year-10 payment of 15262 cents.
RENEWAL_PAYMENT_CENTS = 11447
# 7.20 kW at 45000 cents per kilowatt plus the 120000-cent mobilization charge.
REMOVAL_COST_CENTS = 444000
RENEWED_CONTRACT_END_DATE = "2031-08-31"


def _active_ppa(api, homeowner_id, tariff_id, **overrides):
    terms = dict(TEN_YEAR_TERMS)
    terms.update(overrides)
    agreement = book_ppa(api, homeowner_id, tariff_id, **terms)
    activate(api, agreement["id"])
    return read_agreement(api, agreement["id"])


def _one_active_ppa(api, clock=WINDOW_CLOSE_DATE + "T00:00:00Z", **overrides):
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    return owner, _active_ppa(api, owner["id"], schedule["id"], **overrides)


def _two_active_ppas(api, clock):
    """Two identically termed agreements under one owner, differing by address."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    first = _active_ppa(api, owner["id"], schedule["id"])
    second = _active_ppa(
        api, owner["id"], schedule["id"], site_address="19 Cedar Loop, Fremont, CA"
    )
    return owner, first, second


def _read_election(api, election_id):
    return validate_success(api.get_election(election_id, U.agent_headers()), 200)


def _election_count(api, agreement_id):
    _, meta = validate_paginated(
        api.list_elections(U.agent_headers(), {"agreement_id": agreement_id})
    )
    return meta["total_count"]


def _assert_window(election):
    assert election["window_open_date"] == WINDOW_OPEN_DATE
    assert election["window_close_date"] == WINDOW_CLOSE_DATE
    assert election["elapsed_full_years"] == ELAPSED_FULL_YEARS
    assert float(election["residual_pct"]) == RESIDUAL_PCT


def test_both_edges_of_the_election_window_are_inside_it(api):
    """The open day prices a removal and the close day prices a purchase.

    §3.10: "Every agreement carries an election window derived from its
    `contract_end_date`: `window_open_date` is 180 days before the end of the
    contract and `window_close_date` is 30 days before it, and the window is closed
    at both ends, so an election submitted exactly on either boundary date is in
    time." §3.10: "`elapsed_full_years` is the number of whole years from
    `contract_start_date` to `elected_on_date`, discarding any partial year."
    §3.10: "Whichever figure the `election_type` selects is also copied into
    `elected_amount_cents`, and the two figures the type did not select stay at 0, so
    exactly one of the three price fields is ever populated."

    Design: Difficulty/boundary_precision_check/election_submitted_exactly_on_window_close_date_is_accepted
    """
    _, removing, buying = _two_active_ppas(api, WINDOW_OPEN_DATE + "T00:00:00Z")
    assert removing["contract_end_date"] == CONTRACT_END_DATE
    assert buying["contract_end_date"] == CONTRACT_END_DATE

    on_the_open_edge = submit_election(api, removing["id"], C.ELECTION_REMOVAL)

    assert on_the_open_edge["status"] == C.ELECTION_SUBMITTED
    assert on_the_open_edge["elected_on_date"] == WINDOW_OPEN_DATE
    assert on_the_open_edge["elected_by_user_id"] == U.AGENT_1
    assert on_the_open_edge["accepted_at"] is None
    assert on_the_open_edge["executed_at"] is None
    _assert_window(on_the_open_edge)
    assert on_the_open_edge["removal_cost_cents"] == REMOVAL_COST_CENTS
    assert on_the_open_edge["elected_amount_cents"] == REMOVAL_COST_CENTS
    assert on_the_open_edge["fair_market_value_cents"] == 0
    assert on_the_open_edge["renewal_monthly_payment_cents"] == 0
    assert (
        read_agreement(api, removing["id"])["lifecycle_state"]
        == C.LIFECYCLE_END_OF_TERM_PENDING
    )

    set_clock(api, WINDOW_CLOSE_DATE + "T00:00:00Z")
    on_the_close_edge = submit_election(api, buying["id"], C.ELECTION_PURCHASE)

    assert on_the_close_edge["status"] == C.ELECTION_SUBMITTED
    assert on_the_close_edge["elected_on_date"] == WINDOW_CLOSE_DATE
    _assert_window(on_the_close_edge)
    assert on_the_close_edge["fair_market_value_cents"] == FAIR_MARKET_VALUE_CENTS
    assert on_the_close_edge["elected_amount_cents"] == FAIR_MARKET_VALUE_CENTS
    assert on_the_close_edge["removal_cost_cents"] == 0
    assert on_the_close_edge["renewal_monthly_payment_cents"] == 0

    settled = read_agreement(api, buying["id"])
    assert settled["lifecycle_state"] == C.LIFECYCLE_END_OF_TERM_PENDING
    assert settled["service_status"] == C.SERVICE_IN_SERVICE


def test_neither_day_outside_the_window_is_in_time(api):
    """One day early and one day late are both refused, and nothing is written.

    §3.10: "A submission before `window_open_date` or strictly after
    `window_close_date` is rejected with `ERR_ELECTION_WINDOW_CLOSED`." §3.10: "On
    success the election lands in `status` `SUBMITTED`, records `elected_on_date` as
    the current clock date and `elected_by_user_id` as the acting `X-User-ID`, leaves
    `accepted_at` and `executed_at` null, and moves the agreement `ACTIVE →
    END_OF_TERM_PENDING`."

    Design: Difficulty/boundary_precision_check/election_submitted_exactly_on_window_close_date_is_accepted
    """
    _, agreement = _one_active_ppa(api, clock="2026-03-03T00:00:00Z")
    first_version = agreement["version"]

    validate_error(
        api.create_election(
            F.election_payload(agreement["id"], C.ELECTION_REMOVAL),
            U.agent_headers(),
        ),
        E.ERR_ELECTION_WINDOW_CLOSED,
        422,
    )
    still_active = read_agreement(api, agreement["id"])
    assert still_active["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert still_active["version"] == first_version
    assert _election_count(api, agreement["id"]) == 0

    set_clock(api, "2026-08-02T00:00:00Z")
    validate_error(
        api.create_election(
            F.election_payload(agreement["id"], C.ELECTION_RENEW),
            U.agent_headers(),
        ),
        E.ERR_ELECTION_WINDOW_CLOSED,
        422,
    )

    unchanged = read_agreement(api, agreement["id"])
    assert unchanged["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert unchanged["version"] == first_version
    assert unchanged["renewal_count"] == 0
    assert _election_count(api, agreement["id"]) == 0


def test_the_day_before_the_window_opens_is_refused_and_the_edge_day_renews(api):
    """The identical request is worthless on 2026-03-03 and priced on 2026-03-04.

    §3.10: "A submission before `window_open_date` or strictly after
    `window_close_date` is rejected with `ERR_ELECTION_WINDOW_CLOSED`." §3.10: "A
    `RENEW` sets `renewal_monthly_payment_cents` to the notional monthly payment for
    the agreement's final contract year — `term_years` plus five times
    `renewal_count` — multiplied by 0.75 and rounded to a whole cent, a twenty-five
    percent discount off the last escalated rate." §3.2: "The notional monthly
    payment for that contract year is then the already-rounded escalated rate
    multiplied by one twelfth of `guaranteed_annual_kwh`, divided by 1000 to convert
    millicents to cents, and rounded to a whole cent."

    Design: Corner/validations/election_submitted_one_day_before_the_window_opens_is_rejected
    """
    _, agreement = _one_active_ppa(api, clock="2026-03-03T00:00:00Z")
    body = F.election_payload(agreement["id"], C.ELECTION_RENEW)

    validate_error(
        api.create_election(body, U.agent_headers()),
        E.ERR_ELECTION_WINDOW_CLOSED,
        422,
    )
    assert read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE

    set_clock(api, WINDOW_OPEN_DATE + "T00:00:00Z")
    accepted = validate_success(api.create_election(body, U.agent_headers()), 201)

    assert accepted["status"] == C.ELECTION_SUBMITTED
    assert accepted["election_type"] == C.ELECTION_RENEW
    assert accepted["elected_on_date"] == WINDOW_OPEN_DATE
    _assert_window(accepted)
    assert accepted["renewal_monthly_payment_cents"] == RENEWAL_PAYMENT_CENTS
    assert accepted["elected_amount_cents"] == RENEWAL_PAYMENT_CENTS
    assert accepted["fair_market_value_cents"] == 0
    assert accepted["removal_cost_cents"] == 0
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_END_OF_TERM_PENDING
    )


ROOF_REMOVAL_DATE = "2026-09-05"
ROOF_REINSTALL_DATE = "2026-09-15"


def _accepted_renewal(api):
    """A RENEW election sitting in ACCEPTED at the close edge of the window."""
    owner, agreement = _one_active_ppa(api)
    election = submit_election(api, agreement["id"], C.ELECTION_RENEW)
    assert election["renewal_monthly_payment_cents"] == RENEWAL_PAYMENT_CENTS
    assert election["elected_amount_cents"] == RENEWAL_PAYMENT_CENTS
    accepted = accept_election(api, election["id"])
    assert accepted["status"] == C.ELECTION_ACCEPTED
    assert_instant_equals(
        accepted["accepted_at"], WINDOW_CLOSE_DATE + "T00:00:00Z", "accepted_at"
    )
    assert accepted["executed_at"] is None
    return owner, agreement, accepted


def test_an_approved_roof_order_blocks_the_renewal_until_it_is_cancelled(api):
    """Nothing about the election is wrong, and cancelling the roof job fixes it.

    §3.10: "Roof work in flight — a roof-work order on the agreement in `APPROVED`,
    `PANELS_REMOVED` or `ROOF_COMPLETE` — is refused with `ERR_ROOF_WORK_IN_PROGRESS`,
    because the array's physical disposition is already committed elsewhere." §3.10:
    "A `RENEW` returns the agreement `END_OF_TERM_PENDING → ACTIVE`, increments
    `renewal_count` by one, and extends `contract_end_date` by five years, which
    reopens a fresh election window five years later." §3.7: "Abandonment is
    available to a `Homeowner`, `ServicingAgent` or `PortfolioAdmin` from any of the
    three pre-physical states, moving the order `REQUESTED → CANCELLED`, `QUOTED →
    CANCELLED` or `APPROVED → CANCELLED`."

    Design: Difficulty/cross_entity_state_dependency/election_execution_requires_no_live_roof_work_order
    """
    _, agreement, election = _accepted_renewal(api)
    order = open_roof_order(api, agreement["id"], ROOF_REMOVAL_DATE, ROOF_REINSTALL_DATE)
    quote_roof_order(api, order["id"], 480000, U.ops_headers())
    approved = approve_roof_order(api, order["id"])
    assert approved["status"] == C.ROOF_APPROVED

    validate_error(
        api.execute_election(election["id"], U.admin_headers()),
        E.ERR_ROOF_WORK_IN_PROGRESS,
        422,
    )

    blocked = _read_election(api, election["id"])
    assert blocked["status"] == C.ELECTION_ACCEPTED
    assert blocked["executed_at"] is None
    held = read_agreement(api, agreement["id"])
    assert held["lifecycle_state"] == C.LIFECYCLE_END_OF_TERM_PENDING
    assert held["renewal_count"] == 0
    assert held["contract_end_date"] == CONTRACT_END_DATE

    cancelled = validate_success(
        api.cancel_roof_work_order(order["id"], U.agent_headers()), 200
    )
    assert cancelled["status"] == C.ROOF_CANCELLED

    executed = execute_election(api, election["id"])
    assert executed["status"] == C.ELECTION_EXECUTED
    assert_instant_equals(
        executed["executed_at"], WINDOW_CLOSE_DATE + "T00:00:00Z", "executed_at"
    )

    renewed = read_agreement(api, agreement["id"])
    assert renewed["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert renewed["renewal_count"] == 1
    assert renewed["contract_end_date"] == RENEWED_CONTRACT_END_DATE
    assert renewed["service_status"] == C.SERVICE_IN_SERVICE


def test_a_roof_order_that_is_only_quoted_is_not_work_in_flight(api):
    """The blocking set is three states wide, and QUOTED is not one of them.

    §3.10: "Roof work in flight — a roof-work order on the agreement in `APPROVED`,
    `PANELS_REMOVED` or `ROOF_COMPLETE` — is refused with `ERR_ROOF_WORK_IN_PROGRESS`,
    because the array's physical disposition is already committed elsewhere." §3.7:
    "A `FieldOpsCoordinator` or `ServicingAgent` attaches the roofer's price,
    supplying a `quote_cents` figure that must be present and may not be negative; the
    order moves `REQUESTED → QUOTED`." §3.10: "Execution is exclusive to the
    `PortfolioAdmin`, moves the election `ACCEPTED → EXECUTED`, which is terminal, and
    stamps `executed_at` with the current clock instant."

    Design: Difficulty/cross_entity_state_dependency/election_execution_requires_no_live_roof_work_order
    """
    _, agreement, election = _accepted_renewal(api)
    order = open_roof_order(api, agreement["id"], ROOF_REMOVAL_DATE, ROOF_REINSTALL_DATE)
    quoted = quote_roof_order(api, order["id"], 480000, U.ops_headers())
    assert quoted["status"] == C.ROOF_QUOTED
    assert quoted["quote_cents"] == 480000

    executed = execute_election(api, election["id"])

    assert executed["status"] == C.ELECTION_EXECUTED
    assert executed["renewal_monthly_payment_cents"] == RENEWAL_PAYMENT_CENTS
    assert_instant_equals(
        executed["executed_at"], WINDOW_CLOSE_DATE + "T00:00:00Z", "executed_at"
    )

    renewed = read_agreement(api, agreement["id"])
    assert renewed["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert renewed["renewal_count"] == 1
    assert renewed["contract_end_date"] == RENEWED_CONTRACT_END_DATE
    assert (
        validate_success(api.get_roof_work_order(order["id"], U.agent_headers()), 200)[
            "status"
        ]
        == C.ROOF_QUOTED
    )


def _read_filing(api, ucc_filing_id):
    return validate_success(api.get_ucc_filing(ucc_filing_id, U.title_headers()), 200)


def test_executing_a_purchase_terminates_every_surviving_lien_at_once(api):
    """One execute request closes the contract and releases both county filings.

    §3.10: "A `PURCHASE` moves the agreement `END_OF_TERM_PENDING →
    PURCHASED_CLOSED` and terminates every `UccFiling` on it that is not already
    `TERMINATED`." §3.9: "Executing a `PURCHASE` or a `REMOVAL` election terminates
    every filing out of `FILED` or `SUBORDINATED`, stamping `terminated_date` in each
    case, as described in §3.10." §3.9: "Recording the termination is exclusive to
    the `TitleAgent`, moves the filing `TERMINATION_REQUESTED → TERMINATED`, and
    stamps `terminated_date` with the current clock date."

    Design: Corner/state_machines/purchase_execution_cascades_termination_to_every_open_ucc_filing
    """
    _, agreement = _one_active_ppa(api)
    first = make_filing(api, agreement["id"], "2025-06-10")
    second = make_filing(api, agreement["id"], "2025-07-11")
    assert first["status"] == C.FILING_FILED
    assert second["status"] == C.FILING_FILED

    election = submit_election(api, agreement["id"], C.ELECTION_PURCHASE)
    accept_election(api, election["id"])
    executed = execute_election(api, election["id"])

    assert executed["status"] == C.ELECTION_EXECUTED
    assert_instant_equals(
        executed["executed_at"], WINDOW_CLOSE_DATE + "T00:00:00Z", "executed_at"
    )
    _assert_window(executed)
    assert executed["fair_market_value_cents"] == FAIR_MARKET_VALUE_CENTS
    assert executed["elected_amount_cents"] == FAIR_MARKET_VALUE_CENTS
    assert executed["renewal_monthly_payment_cents"] == 0
    assert executed["removal_cost_cents"] == 0

    bought = read_agreement(api, agreement["id"])
    assert bought["lifecycle_state"] == C.LIFECYCLE_PURCHASED_CLOSED
    assert bought["service_status"] == C.SERVICE_IN_SERVICE

    for filing in (first, second):
        released = _read_filing(api, filing["id"])
        assert released["status"] == C.FILING_TERMINATED
        assert released["terminated_date"] == WINDOW_CLOSE_DATE


def test_withdrawing_an_accepted_removal_puts_the_array_back_in_service(api):
    """The asset side effect is conditional on the type, and the undo rewinds it.

    §3.10: "Accepting a `REMOVAL` moves the agreement's asset dimension `IN_SERVICE
    → DECOMMISSION_PENDING`, scheduling the array for removal while leaving
    `lifecycle_state` in `END_OF_TERM_PENDING`." §3.10: "It returns the agreement
    `END_OF_TERM_PENDING → ACTIVE`, and withdrawing an already-accepted `REMOVAL`
    additionally rewinds the asset dimension `DECOMMISSION_PENDING → IN_SERVICE`,
    undoing the scheduling." §3.10: "A `REMOVAL` sets `removal_cost_cents` to
    `system_dc_kw` multiplied by 45000 cents per kilowatt, rounded to a whole cent,
    plus a flat mobilization and roof-patching charge of 120000 cents."

    Design: Corner/state_machines/withdrawing_an_accepted_removal_election_restores_in_service
    """
    _, agreement = _one_active_ppa(api)

    election = submit_election(api, agreement["id"], C.ELECTION_REMOVAL)
    assert election["removal_cost_cents"] == REMOVAL_COST_CENTS
    assert election["elected_amount_cents"] == REMOVAL_COST_CENTS
    assert election["fair_market_value_cents"] == 0
    assert election["renewal_monthly_payment_cents"] == 0
    scheduled_off = read_agreement(api, agreement["id"])
    assert scheduled_off["lifecycle_state"] == C.LIFECYCLE_END_OF_TERM_PENDING
    assert scheduled_off["service_status"] == C.SERVICE_IN_SERVICE

    accepted = accept_election(api, election["id"])
    assert accepted["status"] == C.ELECTION_ACCEPTED
    scheduled = read_agreement(api, agreement["id"])
    assert scheduled["lifecycle_state"] == C.LIFECYCLE_END_OF_TERM_PENDING
    assert scheduled["service_status"] == C.SERVICE_DECOMMISSION_PENDING

    withdrawn = validate_success(
        api.withdraw_election(election["id"], U.agent_headers()), 200
    )

    assert withdrawn["status"] == C.ELECTION_WITHDRAWN
    assert withdrawn["removal_cost_cents"] == REMOVAL_COST_CENTS
    restored = read_agreement(api, agreement["id"])
    assert restored["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert restored["service_status"] == C.SERVICE_IN_SERVICE


def test_a_twenty_five_year_old_array_hits_both_floors_in_one_calculation(api):
    """Straight-line decay would go negative, and the raw price would be too low.

    §3.10: "`residual_pct` is one minus 0.045 multiplied by `elapsed_full_years` —
    four and a half percent of straight-line depreciation per year — rounded to
    exactly four decimal places and then floored at 0.10, so the residual value never
    falls below ten percent of installed cost however old the system is." §3.10: "A
    `PURCHASE` sets `fair_market_value_cents` to that installed cost multiplied by
    `residual_pct`, rounded to a whole cent, and then floored at 150000 cents — a
    fifteen-hundred-dollar minimum sale price that binds on old, heavily depreciated
    systems." §3.10: "The installed cost is the agreement's `system_dc_kw` multiplied
    by 320000 cents per kilowatt and rounded to a whole cent, the same basis §3.8
    uses."

    Design: Corner/calculations/residual_decay_floors_the_percentage_and_then_the_market_value
    """
    owner, agreement = _one_active_ppa(
        api,
        term_years=25,
        contract_start_date="2001-09-01",
        system_dc_kw=4.0,
    )
    assert agreement["contract_end_date"] == CONTRACT_END_DATE

    election = submit_election(
        api,
        agreement["id"],
        C.ELECTION_PURCHASE,
        U.homeowner_headers(owner["id"]),
    )

    assert election["status"] == C.ELECTION_SUBMITTED
    assert election["elected_on_date"] == WINDOW_CLOSE_DATE
    assert election["elected_by_user_id"] == owner["id"]
    assert election["window_open_date"] == WINDOW_OPEN_DATE
    assert election["window_close_date"] == WINDOW_CLOSE_DATE
    assert election["elapsed_full_years"] == 24
    assert float(election["residual_pct"]) == 0.1
    assert election["fair_market_value_cents"] == 150000
    assert election["elected_amount_cents"] == 150000
    # 4.00 kW installs for 1280000 cents, a tenth of which is only 128000.
    assert election["fair_market_value_cents"] != 128000
    assert election["renewal_monthly_payment_cents"] == 0
    assert election["removal_cost_cents"] == 0

    elected = read_agreement(api, agreement["id"])
    assert elected["lifecycle_state"] == C.LIFECYCLE_END_OF_TERM_PENDING
    assert elected["contract_end_date"] == CONTRACT_END_DATE


MID_WINDOW_CLOCK = "2026-07-15T00:00:00Z"
MID_WINDOW_DATE = "2026-07-15"


def test_an_open_closing_speaks_for_itself_instead_of_the_generic_state_error(api):
    """`TRANSFER_PENDING` is carved out of the state rung so the client learns why.

    §3.10: "A pending sale takes precedence over an end-of-term decision, so a
    `TransferCase` on the agreement in `INITIATED`, `CREDIT_REVIEW`, `CREDIT_APPROVED`
    or `TITLE_CLEARED` blocks the election with `ERR_TRANSFER_IN_PROGRESS` — which is
    also what an agreement sitting in `TRANSFER_PENDING` reports, rather than the
    generic not-active error." §2.10 rung 8: "And an agreement sitting in
    `TRANSFER_PENDING` is *not* reported on this rung when an end-of-term election
    creation targets it; that case falls through to rung 12 and reports
    `ERR_TRANSFER_IN_PROGRESS` so the client learns which closing is in the way."

    Design: Corner/validations/election_submitted_during_an_open_closing_is_rejected_with_the_transfer_code
    """
    _, agreement = _one_active_ppa(api, clock=MID_WINDOW_CLOCK)
    case = open_prepayment(api, agreement["id"], "2026-09-15")
    assert case["status"] == C.TRANSFER_INITIATED
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )
    body = F.election_payload(agreement["id"], C.ELECTION_RENEW)

    response = api.create_election(body, U.agent_headers())

    validate_error(response, E.ERR_TRANSFER_IN_PROGRESS, 422)
    assert response.status_code != 409
    assert _election_count(api, agreement["id"]) == 0
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )

    cancelled = validate_success(
        api.cancel_transfer_case(case["id"], U.agent_headers()), 200
    )
    assert cancelled["status"] == C.TRANSFER_CANCELLED
    assert read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE

    admitted = validate_success(api.create_election(body, U.agent_headers()), 201)
    assert admitted["status"] == C.ELECTION_SUBMITTED
    assert admitted["elected_on_date"] == MID_WINDOW_DATE
    _assert_window(admitted)
    assert admitted["renewal_monthly_payment_cents"] == RENEWAL_PAYMENT_CENTS


def test_a_purchased_agreement_falls_back_to_the_generic_not_active_code(api):
    """The carve-out is specific to a pending sale, not to closed contracts.

    §2.10 rung 8: "`ERR_AGREEMENT_NOT_ACTIVE` when a child record is written against
    an agreement whose `lifecycle_state` is `DRAFT`, `PREPAID_CLOSED` or
    `PURCHASED_CLOSED`." §3.10: "A `PURCHASE` moves the agreement
    `END_OF_TERM_PENDING → PURCHASED_CLOSED` and terminates every `UccFiling` on it
    that is not already `TERMINATED`."

    Design: Corner/validations/election_submitted_during_an_open_closing_is_rejected_with_the_transfer_code
    """
    _, agreement = _one_active_ppa(api, clock=MID_WINDOW_CLOCK)
    purchase = submit_election(api, agreement["id"], C.ELECTION_PURCHASE)
    accept_election(api, purchase["id"])
    execute_election(api, purchase["id"])
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_PURCHASED_CLOSED
    )

    response = api.create_election(
        F.election_payload(agreement["id"], C.ELECTION_RENEW), U.agent_headers()
    )

    validate_error(response, E.ERR_AGREEMENT_NOT_ACTIVE, 409)
    assert response.status_code != 422
    assert _election_count(api, agreement["id"]) == 1
    assert _read_election(api, purchase["id"])["status"] == C.ELECTION_EXECUTED


def test_only_one_election_may_be_open_on_an_agreement_at_a_time(api):
    """Submitted blocks, accepted blocks, and only a withdrawal frees the slot.

    §2.10 rung 8: "`ERR_ELECTION_ALREADY_OPEN` when an end-of-term election is
    created while another for the same agreement is `SUBMITTED` or `ACCEPTED`".
    §3.10: "A second election while one is `SUBMITTED` or `ACCEPTED` is rejected with
    `ERR_ELECTION_ALREADY_OPEN`." §3.10: "A withdrawn election frees the agreement
    for a new submission, subject to the window still being open."

    Design: Corner/validations/second_open_election_is_rejected_with_the_specific_election_code
    """
    _, agreement = _one_active_ppa(api, clock=MID_WINDOW_CLOCK)
    renewal = submit_election(api, agreement["id"], C.ELECTION_RENEW)
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_END_OF_TERM_PENDING
    )

    validate_error(
        api.create_election(
            F.election_payload(agreement["id"], C.ELECTION_PURCHASE),
            U.agent_headers(),
        ),
        E.ERR_ELECTION_ALREADY_OPEN,
        409,
    )
    assert _read_election(api, renewal["id"])["status"] == C.ELECTION_SUBMITTED
    assert _election_count(api, agreement["id"]) == 1

    withdrawn = validate_success(
        api.withdraw_election(renewal["id"], U.agent_headers()), 200
    )
    assert withdrawn["status"] == C.ELECTION_WITHDRAWN
    assert read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE

    purchase = submit_election(api, agreement["id"], C.ELECTION_PURCHASE)
    assert purchase["fair_market_value_cents"] == FAIR_MARKET_VALUE_CENTS
    assert purchase["elected_amount_cents"] == FAIR_MARKET_VALUE_CENTS
    assert purchase["renewal_monthly_payment_cents"] == 0
    assert purchase["removal_cost_cents"] == 0
    assert _election_count(api, agreement["id"]) == 2

    accept_election(api, purchase["id"])
    validate_error(
        api.create_election(
            F.election_payload(agreement["id"], C.ELECTION_REMOVAL),
            U.agent_headers(),
        ),
        E.ERR_ELECTION_ALREADY_OPEN,
        409,
    )
    assert _election_count(api, agreement["id"]) == 2


# June 2026 is contract year 10, expects 1075 kWh gross and floors at 1021, so
# 950 metered kilowatt-hours fall 71 short at the year-10 rate of 19078.
JUNE_FLOOR_KWH = 1021
JUNE_SHORTFALL_KWH = 71
JUNE_CREDIT_CENTS = 1355
JUNE_GROSS_DUE_CENTS = 18124


def test_a_purchase_cannot_be_accepted_over_unspent_guarantee_credit(api):
    """The ledger blocks the sale, and the very same ledger lets a renewal through.

    §3.10: "A `PURCHASE` may only be accepted when the agreement's
    `credit_balance_cents` is exactly 0: unspent guarantee credit has to be refunded
    or applied before the homeowner buys the system, and an outstanding balance is
    refused with `ERR_UNAPPLIED_CREDIT_BLOCKS_PURCHASE`." §3.3: "If `metered_kwh` is
    **strictly** below that floor, `shortfall_kwh` is the floor minus the metered
    figure; otherwise `shortfall_kwh` is 0 — production exactly equal to the floor
    earns nothing." §2.9: "`credit_balance_cents` equals `credit_earned_cents` minus
    `credit_applied_cents`, and it is never negative."

    Design: Corner/validations/accepting_a_purchase_election_with_an_unapplied_credit_is_rejected
    """
    _, agreement = _one_active_ppa(api, clock=MID_WINDOW_CLOCK)
    june = record_period(
        api,
        agreement["id"],
        2026,
        6,
        950,
        auto_reconcile=True,
        auto_issue_credit=True,
    )
    assert june["status"] == C.PERIOD_CREDIT_ISSUED
    assert june["contract_year"] == 10
    assert june["guarantee_floor_kwh"] == JUNE_FLOOR_KWH
    assert june["shortfall_kwh"] == JUNE_SHORTFALL_KWH
    assert june["credit_cents"] == JUNE_CREDIT_CENTS
    assert june["gross_due_cents"] == JUNE_GROSS_DUE_CENTS
    assert june["credit_applied_cents"] == 0
    assert_credit_counters(
        read_agreement(api, agreement["id"]),
        earned=JUNE_CREDIT_CENTS,
        applied=0,
        balance=JUNE_CREDIT_CENTS,
    )

    purchase = submit_election(api, agreement["id"], C.ELECTION_PURCHASE)
    assert purchase["fair_market_value_cents"] == FAIR_MARKET_VALUE_CENTS

    validate_error(
        api.accept_election(purchase["id"], U.agent_headers()),
        E.ERR_UNAPPLIED_CREDIT_BLOCKS_PURCHASE,
        422,
    )

    refused = _read_election(api, purchase["id"])
    assert refused["status"] == C.ELECTION_SUBMITTED
    assert refused["accepted_at"] is None
    assert refused["fair_market_value_cents"] == FAIR_MARKET_VALUE_CENTS

    validate_success(api.withdraw_election(purchase["id"], U.agent_headers()), 200)
    renewal = submit_election(api, agreement["id"], C.ELECTION_RENEW)
    accepted = accept_election(api, renewal["id"])

    assert accepted["status"] == C.ELECTION_ACCEPTED
    assert_instant_equals(accepted["accepted_at"], MID_WINDOW_CLOCK, "accepted_at")
    assert accepted["renewal_monthly_payment_cents"] == RENEWAL_PAYMENT_CENTS
    assert_credit_counters(
        read_agreement(api, agreement["id"]),
        earned=JUNE_CREDIT_CENTS,
        applied=0,
        balance=JUNE_CREDIT_CENTS,
    )
