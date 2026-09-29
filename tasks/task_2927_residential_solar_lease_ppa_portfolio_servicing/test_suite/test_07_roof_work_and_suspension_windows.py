"""Roof work: the committed suspension window, its buffer, and its per-year cap.

A roof-work order is the only record that moves the agreement's asset dimension,
and its window is a closed date interval — which is what makes the buffered
conflict rule and the excused-day pro-ration behave the way they do.
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
from test_helpers.assertions import assert_state_dimensions
from test_helpers.fixtures import (
    activate,
    approve_roof_order,
    approved_roof_order,
    book_ppa,
    complete_roof_cycle,
    make_homeowner,
    make_tariff,
    open_roof_order,
    quote_roof_order,
    read_agreement,
    reconcile,
    record_period,
    set_clock,
)

A1_TERMS = {
    "contract_start_date": "2025-01-01",
    "escalator_pct": 0.029,
    "base_ppa_rate_per_kwh_millicents": 14750,
    "guaranteed_annual_kwh": 9600,
    "guarantee_band_pct": 0.05,
}


def _active_ppa(api, clock, **overrides):
    """An ACTIVE PPA on the A1 terms, with the logical clock already placed."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    terms = dict(A1_TERMS)
    terms.update(overrides)
    agreement = book_ppa(api, owner["id"], schedule["id"], **terms)
    activate(api, agreement["id"])
    return agreement


def _two_active_ppas(api, clock, **overrides):
    """Two identically termed PPAs at neighbouring addresses for one homeowner."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    terms = dict(A1_TERMS)
    terms.update(overrides)
    booked = []
    for address in ("918 Alder Way, Fremont, CA", "920 Alder Way, Fremont, CA"):
        agreement = book_ppa(
            api, owner["id"], schedule["id"], site_address=address, **terms
        )
        activate(api, agreement["id"])
        booked.append(agreement)
    return booked[0], booked[1]


def _read_order(api, roof_work_order_id):
    return validate_success(
        api.get_roof_work_order(roof_work_order_id, U.ops_headers()), 200
    )


def test_taking_the_panels_off_a_quoted_order_is_a_state_error(api):
    """remove-panels exists only from APPROVED, and the refusal suspends nothing.

    §3.7: "Taking the panels off moves the order `APPROVED → PANELS_REMOVED` and
    moves the agreement's asset dimension `IN_SERVICE → ROOF_WORK_SUSPENDED`,
    leaving `lifecycle_state` entirely alone." §3.7: "note the interaction with the
    ladder, since an order that is not `APPROVED` at all reports
    `ERR_INVALID_STATE_TRANSITION` first."

    Design: Corner/state_machines/remove_panels_on_a_quoted_roof_work_order_is_rejected
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    order = open_roof_order(api, agreement["id"], "2026-08-10", "2026-08-24")
    quoted = quote_roof_order(api, order["id"], 850000)
    assert quoted["status"] == C.ROOF_QUOTED

    validate_error(
        api.remove_panels(order["id"], U.ops_headers(U.OPS_1)),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    unchanged = _read_order(api, order["id"])
    assert unchanged["status"] == C.ROOF_QUOTED
    assert unchanged["quote_cents"] == 850000
    assert unchanged["approved_by_user_id"] is None

    assert_state_dimensions(
        read_agreement(api, agreement["id"]),
        lifecycle_state=C.LIFECYCLE_ACTIVE,
        service_status=C.SERVICE_IN_SERVICE,
    )


def test_only_a_committed_window_pro_rates_the_month(api):
    """A quoted order is not a commitment, so June keeps its whole expectation.

    §3.3: "The first source is roof work: every roof-work order on the agreement
    whose `status` is `APPROVED`, `PANELS_REMOVED`, `ROOF_COMPLETE` or `REINSTALLED`
    contributes the closed date interval running from its `suspension_start_date` to
    its `suspension_end_date`, both endpoints included; orders that are still
    `REQUESTED` or `QUOTED`, and orders that were `CANCELLED`, contribute nothing."
    §3.3: "Availability is the number of days in the month minus `excused_days`,
    divided by the number of days in the month, floored at zero; it is an exact ratio
    and is never rounded."

    Design: Corner/calculations/quoted_roof_work_order_is_excluded_from_the_excused_day_input_set
    """
    agreement, committed_site = _two_active_ppas(api, "2026-06-01T00:00:00Z")
    quoted = quote_roof_order(
        api,
        open_roof_order(api, agreement["id"], "2026-06-05", "2026-06-15")["id"],
    )
    assert quoted["status"] == C.ROOF_QUOTED
    assert quoted["suspension_days"] == 11

    # The neighbouring site's identical window was actually approved.
    committed = approved_roof_order(
        api, committed_site["id"], "2026-06-05", "2026-06-15"
    )
    assert committed["status"] == C.ROOF_APPROVED

    set_clock(api, "2026-07-10T00:00:00Z")
    june = record_period(
        api,
        agreement["id"],
        2026,
        6,
        1050,
        auto_reconcile=True,
        auto_issue_credit=True,
    )

    assert june["gross_expected_kwh"] == 1075
    assert june["excused_days"] == 0
    assert june["adjusted_expected_kwh"] == 1075
    assert june["guarantee_floor_kwh"] == 1021
    assert june["shortfall_kwh"] == 0
    assert june["credit_cents"] == 0
    assert june["status"] == C.PERIOD_RECONCILED

    settled = read_agreement(api, agreement["id"])
    assert settled["credit_balance_cents"] == 0
    assert settled["service_status"] == C.SERVICE_IN_SERVICE
    assert _read_order(api, quoted["id"])["status"] == C.ROOF_QUOTED

    pro_rated = record_period(
        api,
        committed_site["id"],
        2026,
        6,
        1050,
        auto_reconcile=True,
        auto_issue_credit=True,
    )
    assert pro_rated["gross_expected_kwh"] == 1075
    assert pro_rated["excused_days"] == 11
    assert pro_rated["adjusted_expected_kwh"] == 681


def test_forty_five_days_apart_is_accepted_and_forty_six_is_refused(api):
    """The span limit is inclusive, so the forty-fifth day still books.

    §3.7: "Three date conditions are enforced together and all three report
    `ERR_ROOF_DATES_INVALID`: the `requested_removal_date` may not fall strictly
    before the current clock date, the `reinstall_target_date` must fall strictly
    after the `requested_removal_date`, and the two dates may be no more than 45
    days apart." §3.7: "`suspension_start_date` equals the `requested_removal_date`,
    `suspension_end_date` equals the `reinstall_target_date`, and the interval
    between them is treated as closed — both endpoints are inside it."

    Design: Corner/validations/roof_dates_spanning_forty_six_days_are_rejected_while_forty_five_are_accepted
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.create_roof_work_order(
            F.roof_work_order_payload(
                agreement["id"],
                "2026-08-10",
                "2026-09-25",
                roofer_company="Bayview Roofing",
            ),
            U.agent_headers(),
        ),
        E.ERR_ROOF_DATES_INVALID,
        422,
    )

    accepted = open_roof_order(
        api,
        agreement["id"],
        "2026-08-10",
        "2026-09-24",
        roofer_company="Bayview Roofing",
    )
    assert accepted["status"] == C.ROOF_REQUESTED
    assert accepted["suspension_start_date"] == "2026-08-10"
    assert accepted["suspension_end_date"] == "2026-09-24"
    assert accepted["suspension_days"] == 46
    assert accepted["contract_year"] == 2
    assert accepted["quote_cents"] is None
    assert accepted["approved_by_user_id"] is None

    _, meta = validate_paginated(
        api.list_roof_work_orders(
            U.ops_headers(), {"agreement_id": agreement["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_a_past_removal_and_a_same_day_reinstall_are_both_refused(api):
    """The other two date conditions report the same code and write nothing.

    §3.7: "the `requested_removal_date` may not fall strictly before the current
    clock date, the `reinstall_target_date` must fall strictly after the
    `requested_removal_date`". §2.10 rung 11: "All carry HTTP 422:
    `ERR_ELECTION_WINDOW_CLOSED`, `ERR_CLOSING_DATE_IN_PAST`,
    `ERR_DETECTED_AT_IN_FUTURE`, `ERR_PERIOD_NOT_ELAPSED`,
    `ERR_WARRANTY_WINDOW_EXPIRED` and `ERR_ROOF_DATES_INVALID`."

    Design: Corner/validations/roof_dates_spanning_forty_six_days_are_rejected_while_forty_five_are_accepted
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.create_roof_work_order(
            F.roof_work_order_payload(agreement["id"], "2026-07-31", "2026-08-24"),
            U.agent_headers(),
        ),
        E.ERR_ROOF_DATES_INVALID,
        422,
    )
    validate_error(
        api.create_roof_work_order(
            F.roof_work_order_payload(agreement["id"], "2026-08-10", "2026-08-10"),
            U.agent_headers(),
        ),
        E.ERR_ROOF_DATES_INVALID,
        422,
    )

    rows, meta = validate_paginated(
        api.list_roof_work_orders(
            U.ops_headers(), {"agreement_id": agreement["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_committed_window_may_not_be_opened_ahead_of_its_start(api):
    """The order walks REQUESTED to APPROVED, but the array stays up until the tenth.

    §3.7: "`suspension_days` is the number of days from the start to the end plus
    one, for that inclusivity." §3.7: "The array may not come off ahead of its
    committed window: if the current clock date is strictly before the order's
    `suspension_start_date`, the request is refused with `ERR_ROOF_DATES_INVALID`".

    Design: Corner/endpoints/roof_work_order_walks_the_full_physical_sequence_back_into_service
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")

    order = open_roof_order(api, agreement["id"], "2026-08-10", "2026-08-24")
    assert order["status"] == C.ROOF_REQUESTED
    assert order["suspension_start_date"] == "2026-08-10"
    assert order["suspension_end_date"] == "2026-08-24"
    assert order["suspension_days"] == 15
    assert order["contract_year"] == 2
    assert order["quote_cents"] is None
    assert order["approved_by_user_id"] is None

    quoted = quote_roof_order(api, order["id"], 185000)
    assert quoted["status"] == C.ROOF_QUOTED
    assert quoted["quote_cents"] == 185000

    approved = approve_roof_order(api, order["id"])
    assert approved["status"] == C.ROOF_APPROVED
    assert approved["approved_by_user_id"] == U.AGENT_1

    validate_error(
        api.remove_panels(order["id"], U.ops_headers(U.OPS_1)),
        E.ERR_ROOF_DATES_INVALID,
        422,
    )

    assert _read_order(api, order["id"])["status"] == C.ROOF_APPROVED
    assert (
        read_agreement(api, agreement["id"])["service_status"]
        == C.SERVICE_IN_SERVICE
    )


def test_only_the_two_ends_of_the_sequence_touch_the_agreement(api):
    """Sign-off moves the order alone; reinstallation is terminal and frees the site.

    §3.7: "Signing off the roofer's work moves the order `PANELS_REMOVED →
    ROOF_COMPLETE` and changes nothing else." §3.7: "Reinstallation moves the order
    `ROOF_COMPLETE → REINSTALLED`, returns the agreement's asset dimension
    `ROOF_WORK_SUSPENDED → IN_SERVICE`, and freezes `suspension_end_date`".

    Design: Corner/endpoints/roof_work_order_walks_the_full_physical_sequence_back_into_service
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    order = approved_roof_order(
        api, agreement["id"], "2026-08-10", "2026-08-24", 185000
    )

    set_clock(api, "2026-08-10T13:00:00Z")
    removed = validate_success(
        api.remove_panels(order["id"], U.ops_headers(U.OPS_1)), 200
    )
    assert removed["status"] == C.ROOF_PANELS_REMOVED

    suspended = read_agreement(api, agreement["id"])
    assert_state_dimensions(
        suspended,
        lifecycle_state=C.LIFECYCLE_ACTIVE,
        monitoring_status=C.MONITORING_OK,
        service_status=C.SERVICE_ROOF_WORK_SUSPENDED,
    )
    version_while_suspended = suspended["version"]

    validate_error(
        api.roof_complete(order["id"], U.agent_headers()), E.ERR_UNAUTHORIZED, 403
    )
    signed_off = validate_success(
        api.roof_complete(order["id"], U.ops_headers(U.OPS_1)), 200
    )
    assert signed_off["status"] == C.ROOF_COMPLETE

    still_suspended = read_agreement(api, agreement["id"])
    assert still_suspended["version"] == version_while_suspended
    assert still_suspended["service_status"] == C.SERVICE_ROOF_WORK_SUSPENDED

    set_clock(api, "2026-08-24T17:00:00Z")
    validate_error(
        api.reinstall(order["id"], U.agent_headers()), E.ERR_UNAUTHORIZED, 403
    )
    back_up = validate_success(
        api.reinstall(order["id"], U.ops_headers(U.OPS_1)), 200
    )
    assert back_up["status"] == C.ROOF_REINSTALLED
    assert back_up["suspension_end_date"] == "2026-08-24"
    assert back_up["suspension_days"] == 15

    in_service = read_agreement(api, agreement["id"])
    assert in_service["service_status"] == C.SERVICE_IN_SERVICE
    assert in_service["version"] == version_while_suspended + 1

    validate_error(
        api.reinstall(order["id"], U.ops_headers(U.OPS_1)),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )


def test_the_frozen_window_excuses_fifteen_of_thirty_one_august_days(api):
    """Fifteen suspended days turn a 267 kWh shortfall into none at all.

    §3.7: "from then on, any metered month reconciled for a month that overlaps the
    window excuses the suspended days exactly as described in §3.3." §4: "Paginated
    roof-work list, filterable by `agreement_id`, `status` and `contract_year`."

    Design: Corner/endpoints/roof_work_order_walks_the_full_physical_sequence_back_into_service
    """
    agreement, untouched_site = _two_active_ppas(api, "2026-08-01T00:00:00Z")
    order = complete_roof_cycle(
        api,
        agreement["id"],
        "2026-08-10",
        "2026-08-24",
        remove_on="2026-08-10T13:00:00Z",
        reinstall_on="2026-08-24T17:00:00Z",
        quote_cents=185000,
    )
    assert order["status"] == C.ROOF_REINSTALLED

    set_clock(api, "2026-09-05T00:00:00Z")
    august = record_period(api, agreement["id"], 2026, 8, 700)
    assert august["gross_expected_kwh"] == 1018
    assert august["excused_days"] == 15
    assert august["adjusted_expected_kwh"] == 525
    assert august["due_date"] == "2026-09-21"

    settled = reconcile(api, august["id"], issue_credit=True)
    assert settled["guarantee_floor_kwh"] == 499
    assert settled["shortfall_kwh"] == 0
    assert settled["credit_cents"] == 0
    assert settled["status"] == C.PERIOD_RECONCILED
    assert settled["escalated_rate_millicents"] == 15178
    assert settled["gross_due_cents"] == 10625
    assert settled["credit_applied_cents"] == 0
    assert settled["net_due_cents"] == 10625
    assert settled["late_fee_cents"] == 0
    assert settled["total_invoiced_cents"] == 10625

    # The neighbour never suspended, so the same 700 kWh misses the guarantee.
    unexcused = record_period(api, untouched_site["id"], 2026, 8, 700)
    assert unexcused["excused_days"] == 0
    assert unexcused["adjusted_expected_kwh"] == 1018
    charged = reconcile(api, unexcused["id"], issue_credit=True)
    assert charged["guarantee_floor_kwh"] == 967
    assert charged["shortfall_kwh"] == 267
    assert charged["credit_cents"] == 4053
    assert charged["status"] == C.PERIOD_CREDIT_ISSUED

    rows, meta = validate_paginated(
        api.list_roof_work_orders(
            U.ops_headers(),
            {
                "agreement_id": agreement["id"],
                "status": C.ROOF_REINSTALLED,
                "contract_year": 2,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [order["id"]]


WINDOWS = [
    ("2026-09-01", "2026-09-10"),
    ("2026-09-13", "2026-09-20"),
    ("2026-09-18", "2026-09-25"),
    ("2026-10-05", "2026-10-12"),
]


def _four_quoted_windows(api):
    """Four quoted orders on one agreement: 10, 8, 8 and 8 suspended days."""
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    orders = []
    for removal, reinstall in WINDOWS:
        order = open_roof_order(api, agreement["id"], removal, reinstall)
        orders.append(quote_roof_order(api, order["id"], 480000))
    assert [order["suspension_days"] for order in orders] == [10, 8, 8, 8]
    assert all(order["contract_year"] == 2 for order in orders)
    assert all(order["status"] == C.ROOF_QUOTED for order in orders)
    return agreement, orders


def test_a_three_day_gap_still_conflicts_but_a_seven_day_gap_does_not(api):
    """Widening both closed windows by three days each side is what decides.

    §3.7: "no other roof-work order on the same agreement whose `status` is
    `APPROVED`, `PANELS_REMOVED` or `ROOF_COMPLETE` may have a suspension window
    that overlaps this one once **both** windows are widened by 3 days at each end;
    because the windows are closed date intervals, mere adjacency conflicts, a
    three-day gap between two windows still conflicts, and a seven-day gap does not.
    A conflict is refused with `ERR_ROOF_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/roof_suspension_closed_windows_buffered_three_days_and_capped_per_year
    """
    agreement, orders = _four_quoted_windows(api)

    first = approve_roof_order(api, orders[0]["id"])
    assert first["status"] == C.ROOF_APPROVED

    validate_error(
        api.approve_roof_work_order(orders[1]["id"], U.agent_headers()),
        E.ERR_ROOF_WINDOW_CONFLICT,
        409,
    )
    assert _read_order(api, orders[1]["id"])["status"] == C.ROOF_QUOTED
    assert _read_order(api, orders[1]["id"])["approved_by_user_id"] is None

    third = approve_roof_order(api, orders[2]["id"])
    assert third["status"] == C.ROOF_APPROVED
    assert third["approved_by_user_id"] == U.AGENT_1

    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    )


def test_a_quoted_order_never_consumed_one_of_the_two_annual_slots(api):
    """The cap counts commitments only, so the fourth window hears the cap error.

    §3.7: "approving the order may not push the number of roof-work orders on that
    agreement in the same `contract_year` whose `status` is `APPROVED`,
    `PANELS_REMOVED`, `ROOF_COMPLETE` or `REINSTALLED` above 2; orders still
    `REQUESTED` or `QUOTED`, and orders that were `CANCELLED`, are not counted at
    all. Exceeding the cap is refused with `ERR_ROOF_WORK_LIMIT_EXCEEDED`." §3.7:
    "`contract_year` is the contract year containing `suspension_start_date`, and it
    is the unit against which the per-year cap below is counted."

    Design: Difficulty/resource_temporal_overlap/roof_suspension_closed_windows_buffered_three_days_and_capped_per_year
    """
    agreement, orders = _four_quoted_windows(api)

    approve_roof_order(api, orders[0]["id"])
    validate_error(
        api.approve_roof_work_order(orders[1]["id"], U.agent_headers()),
        E.ERR_ROOF_WINDOW_CONFLICT,
        409,
    )
    approve_roof_order(api, orders[2]["id"])

    validate_error(
        api.approve_roof_work_order(orders[3]["id"], U.agent_headers()),
        E.ERR_ROOF_WORK_LIMIT_EXCEEDED,
        422,
    )

    assert _read_order(api, orders[3]["id"])["status"] == C.ROOF_QUOTED
    assert _read_order(api, orders[1]["id"])["status"] == C.ROOF_QUOTED
    assert _read_order(api, orders[0]["id"])["status"] == C.ROOF_APPROVED
    assert _read_order(api, orders[2]["id"])["status"] == C.ROOF_APPROVED

    _, meta = validate_paginated(
        api.list_roof_work_orders(
            U.ops_headers(),
            {"agreement_id": agreement["id"], "status": C.ROOF_APPROVED},
        )
    )
    assert meta["total_count"] == C.ROOF_ORDERS_PER_CONTRACT_YEAR
    assert_state_dimensions(
        read_agreement(api, agreement["id"]),
        lifecycle_state=C.LIFECYCLE_ACTIVE,
        service_status=C.SERVICE_IN_SERVICE,
    )
