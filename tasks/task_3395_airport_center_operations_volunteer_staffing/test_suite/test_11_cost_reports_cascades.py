"""Center cost accountability: empty-month nulls, actual-vs-loaded cost
per visit, per-lot partner-match rounding order, and the run_ops
screening-expiry cascade that walks screening -> volunteer -> assignment
-> shift -> posture."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    assert_cost_report,
    assert_donation_lot,
    assign_volunteer,
    check_in_guest,
    confirm_assignment,
    confirm_event,
    create_center_with_active_agreement,
    create_cleared_volunteer,
    create_donation_lot,
    create_event,
    create_funding_grant,
    create_guest,
    create_shift,
    get_assignment,
    get_center,
    get_cost_report,
    get_shift,
    get_volunteer,
    post_expense,
    run_ops,
    set_clock,
    validate_paginated,
)

MGR = TEST_USERS["manager_headers"]


def test_cost_report_empty_nulls(api: ApiClient):
    """PRD §3.8: "When `month_visits` is 0, both per-visit fields are null."
    PRD §3.8: "The report also totals donations: `donation_value_total_cents` sums `declared_value_cents` over the center's `AVAILABLE` and `DEPLETED` lots — `DISCARDED_EXPIRED` lots are excluded — and `partner_match_total_cents` sums the per-lot matches."
    PRD §2.6: "If the center has no `ACTIVE` site agreement, posture is `CLOSED`. Otherwise, when `coverage_ratio` is at least 0.75 the posture is `OPEN`, and below that threshold it is `RESTRICTED`."

    Design: Corner/calculations/cost_report_empty_nulls
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Yod Center",
            "airport_code": "BOI",
            "occupancy_cap": 25,
            "required_daily_confirmed_assignments": 1,
        }
    )

    report = get_cost_report(center["id"])
    assert_cost_report(report)
    assert report["month_expenses_cents"] == 0
    assert report["month_visits"] == 0
    assert report["cost_per_visit_actual_cents"] is None, (
        "with zero visits the actual per-visit figure is null, not a "
        "division by zero"
    )
    assert report["cost_per_visit_loaded_cents"] is None
    assert report["donation_value_total_cents"] == 0
    assert report["partner_match_total_cents"] == 0
    assert report["posture"] == "RESTRICTED", (
        "agreement ACTIVE with coverage 0 (< 0.75) yields RESTRICTED"
    )


def test_cost_per_visit_actual_vs_loaded(api: ApiClient):
    """PRD §3.8: "`cost_per_visit_actual_cents` divides month expenses by month visits, rounded half-up to whole cents. `cost_per_visit_loaded_cents` first adds the committed event budgets — the `event_budget_cents` of the center's `CONFIRMED` or `EXECUTED` events whose `start_at` falls in the current clock month — to the month expenses, then divides by month visits and rounds half-up to whole cents; the loaded figure therefore exceeds the actual one whenever any such event carries a positive budget."

    Design: Difficulty/dual_variant_calc/cost_per_visit_actual_vs_loaded
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Beta Center",
            "airport_code": "JFK",
            "occupancy_cap": 50,
            "required_daily_confirmed_assignments": 1,
        },
        agreement_overrides={"facility_space_sqft": 900, "security_level": 2},
    )
    # Four September visits (RESTRICTED posture still admits check-ins).
    guests = [
        create_guest(full_name="G One", category="ACTIVE_DUTY"),
        create_guest(full_name="G Two", category="DEPENDENT"),
        create_guest(full_name="G Three", category="RETIREE"),
        create_guest(full_name="G Four", category="VETERAN"),
    ]
    for guest in guests:
        check_in_guest(center["id"], guest["id"])

    create_funding_grant(
        center["id"], donor_name="Donor A", amount_cents=20000,
        spend_by_date="2026-12-31",
    )
    post_expense(
        center["id"], amount_cents=10000, description="September snacks"
    )

    # A CONFIRMED event in the current clock month with a committed budget
    # feeds only the loaded figure.
    event = create_event(
        center["id"],
        kind="HOMECOMING",
        name="Welcome Home 7th",
        start_at="2026-09-05T10:00:00Z",
        end_at="2026-09-05T12:00:00Z",
        min_volunteers=0,
        event_budget_cents=3000,
    )
    confirm_event(event["id"])

    report = get_cost_report(center["id"])
    assert_cost_report(report)
    assert report["month_expenses_cents"] == 10000
    assert report["month_visits"] == 4
    assert report["cost_per_visit_actual_cents"] == 2500, (
        f"round_half_up(10000 / 4) == 2500, got "
        f"{report['cost_per_visit_actual_cents']}"
    )
    assert report["cost_per_visit_loaded_cents"] == 3250, (
        f"round_half_up((10000 + 3000) / 4) == 3250, got "
        f"{report['cost_per_visit_loaded_cents']}"
    )


def test_partner_match_per_lot_rounding(api: ApiClient):
    """PRD §3.6: "When the donation rides a corporate partner program, the optional `partner_name` is supplied, and the lot's `partner_match_cents` is computed at intake as the declared value multiplied by 0.25, rounded half-up to whole cents; without `partner_name` the match is 0."
    PRD §3.8: "The rounding order is pinned: each lot's match is rounded half-up first — declared value multiplied by 0.25 — and only then summed. The alternative of summing declared values and rounding once is forbidden, because the two genuinely differ: three lots of 3 cents each yield a per-lot total of 3 cents (each 0.75 rounds up to 1) against a sum-first total of 2 cents (2.25 rounds to 2)."

    Design: Difficulty/combinatorial_formula/partner_match_per_lot_rounding
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Delta Center",
            "airport_code": "ATL",
            "occupancy_cap": 40,
            "required_daily_confirmed_assignments": 2,
        },
        agreement_overrides={"facility_space_sqft": 600, "security_level": 1},
    )
    matches = []
    for _ in range(3):
        lot = create_donation_lot(
            center["id"],
            item_name="granola bar",
            received_qty=5,
            expiry_date="2026-09-20",
            declared_value_cents=3,
            partner_name="Acme",
        )
        assert_donation_lot(lot)
        matches.append(lot["partner_match_cents"])

    assert matches == [1, 1, 1], (
        f"each 3-cent lot rounds half-up at intake: 0.75 -> 1, got {matches}"
    )

    report = get_cost_report(center["id"])
    assert report["donation_value_total_cents"] == 9
    assert report["partner_match_total_cents"] == 3, (
        "per-lot first, then sum: 3 * 1 == 3; the forbidden sum-first "
        f"order would give round_half_up(2.25) == 2, got "
        f"{report['partner_match_total_cents']}"
    )


def test_screening_expiry_cascade(api: ApiClient):
    """PRD §3.2: "Separately, screenings expire: when the operations checkpoint finds a `CLEARED` screening whose `expires_at` has been reached, that screening becomes `EXPIRED`, and a volunteer left with no other unexpired `CLEARED` screening lapses to `INACTIVE` — quietly from `CLEARED` or `SUSPENDED`, but from `ACTIVE` with the same future-assignment cancellation cascade as suspension."
    PRD §3.2: "Each no-show adds a strike to `no_show_strikes`, and when the count reaches the strike limit of 3 the volunteer is `SUSPENDED`: every future-dated `ASSIGNED` or `CONFIRMED` assignment of that volunteer is cancelled, each affected shift's `confirmed_count` is decremented where applicable — a `FILLED` shift that drops below `capacity` reopens to `OPEN` — and coverage and posture are recomputed for the affected centers."
    PRD §3.2: "A `CLEARED` verdict stamps `expires_at` at exactly 24 months after the decision time and moves the linked volunteer from `SCREENING` to `CLEARED`; a `REJECTED` verdict sends the volunteer back to `APPLIED`, making the apply–screen–reject loop cyclic."

    Design: Difficulty/transitive_cascade/screening_expiry_cascade
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Eta Center",
            "airport_code": "DEN",
            "occupancy_cap": 40,
            "required_daily_confirmed_assignments": 1,
        },
        agreement_overrides={"end_date": "2029-08-31"},
    )
    # The CLEARED verdict at 2026-09-01T00:00:00Z stamps expires_at exactly
    # 24 months later: 2028-09-01T00:00:00Z.
    volunteer = create_cleared_volunteer(center["id"], full_name="V Long")

    # Advance past expires_at. The lapse is checkpoint-driven, so the
    # volunteer is still CLEARED and can be assigned and confirmed.
    set_clock("2028-09-02T08:00:00Z")
    shift = create_shift(
        center["id"],
        start_at="2028-09-02T14:00:00Z",
        end_at="2028-09-02T18:00:00Z",
        role_required="DESK",
        capacity=1,
    )
    assignment = assign_volunteer(shift["id"], volunteer["id"])
    confirm_assignment(assignment["id"], volunteer["id"])

    pre_center = get_center(center["id"])
    assert pre_center["posture"] == "OPEN", (
        f"coverage 1/1 = 1.0 >= 0.75 with the agreement ACTIVE: OPEN, got "
        f"{pre_center['posture']!r}"
    )
    pre_shift = get_shift(shift["id"])
    assert pre_shift["confirmed_count"] == 1 and pre_shift["status"] == "FILLED"

    swept = run_ops(center["id"])
    assert swept["posture"] == "RESTRICTED", (
        "the cascade cancels today's only confirmed slot: coverage falls "
        f"to 0 and posture drops to RESTRICTED, got {swept['posture']!r}"
    )

    rows, _meta = validate_paginated(api.list_screenings(volunteer["id"], MGR))
    assert rows[0]["status"] == "EXPIRED", (
        "hop 1: the CLEARED screening past expires_at becomes EXPIRED"
    )
    volunteer_after = get_volunteer(volunteer["id"])
    assert volunteer_after["status"] == "INACTIVE", (
        "hop 2: no unexpired CLEARED screening remains, so the volunteer "
        f"lapses to INACTIVE, got {volunteer_after['status']!r}"
    )
    assignment_after = get_assignment(assignment["id"])
    assert assignment_after["status"] == "CANCELLED", (
        "hop 3: the future-dated (14:00 > 08:00 checkpoint time) CONFIRMED "
        f"assignment is cancelled, got {assignment_after['status']!r}"
    )
    post_shift = get_shift(shift["id"])
    assert post_shift["confirmed_count"] == 0
    assert post_shift["status"] == "OPEN", (
        "hop 4: the FILLED shift reopens to OPEN when its count drops "
        "below capacity"
    )
