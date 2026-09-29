"""Arithmetic at its edges: zero-discount pricing, half-point rounding and clamped sub-scores.

The undiscounted price, the inspection weighted sum that lands exactly on .5, the refresh term
that would go negative, and the statutory branches of the cancellation settlement.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    allocate_corporate_account,
    api_client,
    assert_corporate_pool_conserved,
    create_corporate_account,
    create_member,
    decide_transfer_request,
    file_transfer_request,
    fund_corporate_account,
    inspect_club,
    make_club_manager_headers,
    post_dues,
    post_payment,
    post_payment_failure,
    read_agreement,
    read_club,
    read_corporate_account,
    read_franchisee,
    read_inspection,
    read_member,
    request_cancellation,
    schedule_inspection,
    score_inspection,
    set_clock_date,
    setup_home_and_host_clubs,
    setup_single_club_franchise,
    setup_two_franchise_clubs,
    sign_active_agreement,
    sign_agreement,
    submit_royalty_report,
)


def _one_club_and_one_member() -> dict:
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    return scenario


def test_an_undiscounted_signing_prices_at_the_templates_list_dues():
    """No promotion, no corporate account and no multi-club rider means all three components are
    zero, so the base survives the subtraction untouched.

    PRD 3.3: "Each of the three discount components is computed and rounded half up to whole cents
    *independently*: `promo_discount_cents` is 0 when no `promotion_id` was quoted and otherwise
    the base multiplied by the promotion's `discount_pct`, rounded half up; `corporate_credit_cents`
    is 0 when no `corporate_account_id` was named and otherwise the base multiplied by the
    account's `corporate_credit_pct`, rounded half up; and `multi_club_credit_cents` is 0 when
    `multi_club_access` is false and otherwise the base multiplied by the multi-club credit rate of
    0.015 — one and a half percent — rounded half up."

    Design: Corner/calculations/corner_effective_dues_equals_the_base_price_when_no_discount_applies
    """
    scenario = _one_club_and_one_member()

    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    assert agreement["monthly_dues_base_cents"] == 4500
    assert agreement["promo_discount_cents"] == 0
    assert agreement["corporate_credit_cents"] == 0
    assert agreement["multi_club_credit_cents"] == 0


def test_the_floor_gate_does_not_lift_a_price_that_never_fell():
    """4500 sits well above the 3600 floor, so the gross figure is stored verbatim rather than
    being nudged anywhere by the floor rule.

    PRD 3.3: "When the gross figure is at or above the floor, it is stored verbatim as
    `effective_monthly_dues_cents`, and that figure — like every other pinned term — never moves
    again, not when the quoted promotion is later withdrawn by the brand, and not when the
    membership is transferred to another club."

    Design: Corner/calculations/corner_effective_dues_equals_the_base_price_when_no_discount_applies
    """
    scenario = _one_club_and_one_member()

    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    assert agreement["effective_monthly_dues_cents"] == 4500
    assert agreement["effective_monthly_dues_cents"] == agreement["monthly_dues_base_cents"]


def _scored(equipment: int, cleanliness: int, safety: int, age_months: int) -> dict:
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        with_plan=False,
    )
    scenario["inspection"] = inspect_club(
        scenario["club"]["id"], "2026-07-15", equipment, cleanliness, safety, age_months
    )
    return scenario


def test_a_modern_compliant_club_is_measured_against_the_brand_standard_cycle():
    """The club opened well after the cut-off and was `COMPLIANT` going in, so neither accelerating
    condition holds and the sixty-month cycle applies.

    PRD 3.9: "On the accelerated cycle, `refresh_cycle_months_applied` is 42 months and
    `variant_applied` is `ACCELERATED_CYCLE`; otherwise `refresh_cycle_months_applied` is the
    brand-standard 60 months and `variant_applied` is `STANDARD_CYCLE`."

    Design: Corner/calculations/corner_inspection_weighted_sum_of_exactly_half_a_point_rounds_up
    """
    scenario = _scored(90, 90, 90, 12)

    assert scenario["inspection"]["variant_applied"] == "STANDARD_CYCLE"
    assert scenario["inspection"]["refresh_cycle_months_applied"] == 60


def test_a_twelve_month_floor_against_the_sixty_month_cycle_earns_eighty_refresh_points():
    """One fifth of the cycle has elapsed, so twenty points come off the hundred before any
    weighting happens.

    PRD 3.9: "Then `refresh_pts` is computed: multiply 100 by `equipment_age_months_max`, divide
    by `refresh_cycle_months_applied`, round that quotient half up to a whole number, subtract it
    from 100, and floor the result at 0, so an over-age floor earns zero refresh points rather than
    negative ones."

    Design: Corner/calculations/corner_inspection_weighted_sum_of_exactly_half_a_point_rounds_up
    """
    scenario = _scored(90, 90, 90, 12)

    assert scenario["inspection"]["refresh_pts"] == 80


def test_a_weighted_total_of_exactly_eighty_eight_and_a_half_rounds_up_to_eighty_nine():
    """36 plus 22.5 plus 18 plus 12 is exactly 88.5, and the single half-up rounding at the end
    must resolve it upward rather than to the even 88.

    PRD 3.9: "The `score` is then a single weighted sum, rounded half up to an integer exactly
    once, at the very end: `equipment_condition_pts` weighted at 0.40, plus `cleanliness_pts` at
    0.25, plus `safety_pts` at 0.20, plus `refresh_pts` at 0.15. Rounding the individual weighted
    terms instead of the total changes the result and is wrong."

    Design: Corner/calculations/corner_inspection_weighted_sum_of_exactly_half_a_point_rounds_up
    """
    scenario = _scored(90, 90, 90, 12)

    assert scenario["inspection"]["score"] == 89


def test_the_passing_score_leaves_the_club_compliant_and_open():
    """89 is at or above 85, so the club is scored into the compliant band, the inspection closes
    itself, and its operator's failure streak stays empty.

    PRD 3.9: "The club's `last_inspection_score` is set to the new `score`, and its
    `equipment_compliance_state` is re-derived from that score alone: `COMPLIANT` at 85 or above,
    `WATCH` at 70 through 84, and `NON_COMPLIANT` below 70. A club that has just become
    `NON_COMPLIANT` and was `OPEN` moves to `SUSPENDED`; a club that was `SUSPENDED` and has just
    scored 70 or better moves back to `OPEN`. The franchisee's `inspection_fail_streak` and
    `compliance_score` are then recomputed, which may demote the franchisee and withdraw its
    approved promotions. Finally the inspection auto-resolves: `SCORED → CLOSED` when the `score`
    is 70 or higher, and `SCORED → REMEDIATION_REQUIRED` when it is below 70."

    Design: Corner/calculations/corner_inspection_weighted_sum_of_exactly_half_a_point_rounds_up
    """
    scenario = _scored(90, 90, 90, 12)

    assert scenario["inspection"]["status"] == "CLOSED"
    club = read_club(scenario["club"]["id"])
    assert club["last_inspection_score"] == 89
    assert club["equipment_compliance_state"] == "COMPLIANT"
    assert club["status"] == "OPEN"
    assert read_franchisee(scenario["franchisee"]["id"])["inspection_fail_streak"] == 0


def test_equipment_that_has_outlived_the_cycle_earns_zero_rather_than_negative_points():
    """Ninety months against a sixty-month cycle gives 100 minus 150, and the floor at zero is
    what stops the refresh term from dragging the score down twice.

    PRD 3.9: "Then `refresh_pts` is computed: multiply 100 by `equipment_age_months_max`, divide
    by `refresh_cycle_months_applied`, round that quotient half up to a whole number, subtract it
    from 100, and floor the result at 0, so an over-age floor earns zero refresh points rather than
    negative ones."

    Design: Corner/calculations/corner_refresh_points_clamp_at_zero_when_equipment_outlives_the_cycle
    """
    scenario = _scored(80, 80, 80, 90)

    assert scenario["inspection"]["refresh_cycle_months_applied"] == 60
    assert scenario["inspection"]["refresh_pts"] == 0


def test_the_clamped_refresh_term_lands_the_score_at_sixty_eight():
    """32 plus 20 plus 16 plus nothing is 68 — a failing score, but not the 60 an unclamped
    negative refresh term would produce.

    PRD 3.9: "The `score` is then a single weighted sum, rounded half up to an integer exactly
    once, at the very end: `equipment_condition_pts` weighted at 0.40, plus `cleanliness_pts` at
    0.25, plus `safety_pts` at 0.20, plus `refresh_pts` at 0.15. Rounding the individual weighted
    terms instead of the total changes the result and is wrong."

    Design: Corner/calculations/corner_refresh_points_clamp_at_zero_when_equipment_outlives_the_cycle
    """
    scenario = _scored(80, 80, 80, 90)

    assert scenario["inspection"]["score"] == 68


def test_a_score_of_sixty_eight_suspends_the_club_and_starts_the_failure_streak():
    """68 is below 70 on both the compliance band and the remediation threshold, so the club is
    taken out of service and its operator picks up its first failure.

    PRD 3.9: "The club's `last_inspection_score` is set to the new `score`, and its
    `equipment_compliance_state` is re-derived from that score alone: `COMPLIANT` at 85 or above,
    `WATCH` at 70 through 84, and `NON_COMPLIANT` below 70. A club that has just become
    `NON_COMPLIANT` and was `OPEN` moves to `SUSPENDED`; a club that was `SUSPENDED` and has just
    scored 70 or better moves back to `OPEN`. The franchisee's `inspection_fail_streak` and
    `compliance_score` are then recomputed, which may demote the franchisee and withdraw its
    approved promotions. Finally the inspection auto-resolves: `SCORED → CLOSED` when the `score`
    is 70 or higher, and `SCORED → REMEDIATION_REQUIRED` when it is below 70."

    Design: Corner/calculations/corner_refresh_points_clamp_at_zero_when_equipment_outlives_the_cycle
    """
    scenario = _scored(80, 80, 80, 90)

    assert scenario["inspection"]["status"] == "REMEDIATION_REQUIRED"
    club = read_club(scenario["club"]["id"])
    assert club["equipment_compliance_state"] == "NON_COMPLIANT"
    assert club["status"] == "SUSPENDED"
    assert read_franchisee(scenario["franchisee"]["id"])["inspection_fail_streak"] == 1


def test_a_single_failure_docks_twenty_points_without_costing_the_operator_its_standing():
    """One step of streak is twenty points off a clean hundred, and eighty is not strictly below
    the seventy threshold that would trigger probation.

    PRD 3.9: "`compliance_score` then starts at 100 and subtracts 20 for each step of
    `inspection_fail_streak`, a flat 20 if `collections_watch_club_count` is greater than zero —
    one flat penalty no matter how many clubs are on watch, not 20 per club — and 10 for each
    disputed royalty report, with the result clamped into 0 through 100. If the franchisee is
    `ACTIVE` and the freshly recomputed score is strictly below 70, the franchisee is demoted
    `ACTIVE → PROBATION`, which withdraws every `APPROVED` promotion it owns; a score of exactly
    70 keeps it `ACTIVE`."

    Design: Corner/calculations/corner_refresh_points_clamp_at_zero_when_equipment_outlives_the_cycle
    """
    scenario = _scored(80, 80, 80, 90)

    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["compliance_score"] == 80
    assert franchisee["status"] == "ACTIVE"


def test_the_scored_inspection_records_the_auditor_who_signed_it_off():
    """The scoring auditor is taken from the acting identity rather than from the payload, and the
    numbers as supplied are stored on the file.

    PRD 3.9: "Scoring writes `scored_by_user_id` from the `X-User-ID` header and then sets off the
    cascade described in §2.10, in order."

    Design: Corner/calculations/corner_inspection_weighted_sum_of_exactly_half_a_point_rounds_up
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        with_plan=False,
    )
    inspection = schedule_inspection(scenario["club"]["id"], "2026-07-15", auditor_id="auditor-1")
    score_inspection(inspection["id"], 90, 90, 90, 12, auditor_id="auditor-1")

    reread = read_inspection(inspection["id"])
    assert reread["scored_by_user_id"] == "auditor-1"
    assert reread["equipment_condition_pts"] == 90
    assert reread["equipment_age_months_max"] == 12


def _new_york_cancellation_after_the_cooling_off_window() -> dict:
    """A 24-month New York membership signed 2026-08-01, one month paid, cancelled on 2026-08-20 —
    nineteen days in, so well past New York's three-day rescission window."""
    scenario = setup_single_club_franchise(
        legal_name="Empire Iron Clubs LLC",
        contact_email="ops@empireiron.example",
        center_lat=40.75,
        center_lng=-73.99,
        protected_radius_km=3.0,
        state_code="NY",
        club_name="Empire Iron Midtown",
        plan_overrides={"code": "NY15", "term_months": 24, "cancellation_notice_days": 15},
    )
    member = create_member(
        scenario["club"]["id"],
        full_name="Dara Kim",
        email="dara.kim@example.com",
        home_state_code="NY",
    )
    agreement = sign_active_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    set_clock_date("2026-08-20")
    scenario["member"] = member
    scenario["agreement"] = agreement
    scenario["cancellation"] = request_cancellation(
        agreement["id"], member["id"], reason="Moving out of state."
    )
    return scenario


def test_a_twenty_four_month_term_ends_on_the_thirty_day_month_calendar():
    """Twenty-four thirty-day months from 2026-08-01 is 720 days, which lands in July 2028 rather
    than on the second anniversary.

    PRD 3.3: "`term_end_on` is the `signed_on` date plus 30 days multiplied by the template's
    `term_months`, using the 30-day month convention."

    Design: Corner/calculations/corner_new_york_notice_branch_pays_no_refund_and_caps_the_termination_fee
    """
    scenario = _new_york_cancellation_after_the_cooling_off_window()

    assert scenario["agreement"]["state_code"] == "NY"
    assert scenario["agreement"]["term_end_on"] == "2028-07-21"
    assert scenario["agreement"]["cancellation_notice_days"] == 15


def test_the_notice_branch_sets_the_effective_date_fifteen_days_out():
    """Nineteen days after signature is outside the statutory window, so the member owes notice and
    the contract runs on until the clock plus the pinned notice period.

    PRD 3.5: "When more than the statutory cooling-off days have elapsed since `signed_on`, the
    member owes notice instead. `cancellation_effective_on` becomes the logical clock date plus the
    agreement's pinned `cancellation_notice_days`."

    Design: Corner/calculations/corner_new_york_notice_branch_pays_no_refund_and_caps_the_termination_fee
    """
    scenario = _new_york_cancellation_after_the_cooling_off_window()

    assert scenario["cancellation"]["cancellation_requested_on"] == "2026-08-20"
    assert scenario["cancellation"]["cancellation_effective_on"] == "2026-09-04"


def test_a_new_york_membership_is_refunded_nothing_even_though_a_month_was_paid():
    """New York does not prorate on cancellation, so the paid-but-unused days are irrelevant and
    the refund is zero.

    PRD 3.5: "In every other case, including any `NY` agreement and any case where the paid-through
    date is on or before the effective date, `refund_cents` is 0."

    Design: Corner/calculations/corner_new_york_notice_branch_pays_no_refund_and_caps_the_termination_fee
    """
    scenario = _new_york_cancellation_after_the_cooling_off_window()

    assert scenario["agreement"]["dues_paid_cents"] == 4500
    assert scenario["cancellation"]["refund_cents"] == 0


def test_the_termination_fee_is_capped_after_the_multiplication_not_per_month():
    """Twenty-three remaining months at 2250 a month is 51750, and the cap bites on that total,
    leaving a settlement the member owes rather than one they receive.

    PRD 3.5: "The remaining months are the whole days from `cancellation_effective_on` to
    `term_end_on`, divided by 30 and rounded *up* to the next whole number, floored at 0 so that an
    effective date at or beyond `term_end_on` yields no remaining months. The monthly charge is
    `effective_monthly_dues_cents` multiplied by 0.5 — half a month's dues — rounded half up to
    whole cents, and that rounded monthly figure is then multiplied by the remaining months. Only
    after the multiplication is the cap applied: `early_termination_fee_cents` is the lesser of that
    product and 15000 cents. Rounding the product instead of the monthly charge, or applying the cap
    per month instead of to the total, produces a different figure and is wrong.
    `net_settlement_cents` is then `refund_cents` minus `early_termination_fee_cents`, and a
    negative result is meaningful: it means the member owes the club rather than the reverse."

    Design: Corner/calculations/corner_new_york_notice_branch_pays_no_refund_and_caps_the_termination_fee
    """
    scenario = _new_york_cancellation_after_the_cooling_off_window()

    assert scenario["cancellation"]["early_termination_fee_cents"] == 15000
    assert scenario["cancellation"]["net_settlement_cents"] == -15000


def test_a_notice_period_cancellation_leaves_the_membership_live():
    """The member keeps their membership through the notice period, so no counter anywhere moves on
    the request itself.

    PRD 3.5: "Branch B leaves the contract dimension at `CANCELLATION_PENDING` and touches nothing
    else. The club's `active_agreement_count`, the member's `agreement_count`, the franchisee's
    `compliance_score` and the corporate enrolment count all stay exactly where they were, because
    the membership is still live through the notice period, and only the agreement's own `version`
    increments."

    Design: Corner/calculations/corner_new_york_notice_branch_pays_no_refund_and_caps_the_termination_fee
    """
    scenario = _new_york_cancellation_after_the_cooling_off_window()

    assert scenario["cancellation"]["agreement_status"] == "CANCELLATION_PENDING"
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 1
    member = read_member(scenario["member"]["id"])
    assert member["status"] == "ACTIVE"
    assert member["agreement_count"] == 1


def _completed_intra_franchise_transfer() -> dict:
    """One operator moving its own member between its own two clubs."""
    scenario = setup_home_and_host_clubs(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
    )
    member = create_member(
        scenario["home_club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_active_agreement(
        member["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    request = file_transfer_request(
        agreement["id"],
        scenario["home_club"]["id"],
        scenario["host_club"]["id"],
        reason="Member relocated across town.",
    )
    decide_transfer_request(request["id"], scenario["host_club"]["id"], "APPROVE")
    scenario["member"] = member
    scenario["agreement"] = agreement
    scenario["request"] = validate_success(
        api_client.complete_transfer_request(
            request["id"], {}, make_club_manager_headers(scenario["host_club"]["id"])
        )
    )
    return scenario


def test_a_move_between_two_clubs_of_the_same_operator_carries_no_fee():
    """Both clubs share a `franchisee_id`, so the handover is an internal reshuffle and the fee
    pinned at approval is exactly zero rather than the cross-franchise 2500 plus half a month.

    PRD 3.6: "When the releasing club and the receiving club belong to the same franchisee — that
    is, both clubs carry the same `franchisee_id` — the move is intra-franchise and
    `transfer_fee_cents` is exactly 0."

    Design: Corner/calculations/corner_intra_franchise_transfer_carries_no_fee_and_posts_no_billing_event
    """
    scenario = _completed_intra_franchise_transfer()

    assert scenario["request"]["transfer_fee_cents"] == 0


def test_a_zero_fee_completion_appends_no_ledger_row_at_all():
    """The system-generated transfer charge is conditional on a positive fee, so the agreement's
    ledger still holds nothing of that type.

    PRD 3.6: "When the pinned `transfer_fee_cents` is greater than 0, completion also appends a
    system ledger entry of type `TRANSFER_FEE_POSTED` carrying that amount, with `due_on` set to the
    logical clock date plus 15 days and `source` `SYSTEM`, and then re-runs the dues projection of
    §3.4 over the whole ledger — so a cross-franchise transfer can, by itself, push a previously
    `CURRENT` membership towards `PAST_DUE` once the clock advances past that due date. When the fee
    is 0, no ledger entry is created at all."

    Design: Corner/calculations/corner_intra_franchise_transfer_carries_no_fee_and_posts_no_billing_event
    """
    scenario = _completed_intra_franchise_transfer()

    _, meta = validate_paginated(
        api_client.list_agreement_billing_events(
            scenario["agreement"]["id"],
            TEST_USERS["brand_administrator_headers"],
            params={"event_type": "TRANSFER_FEE_POSTED"},
        )
    )
    assert meta["total_count"] == 0
    assert read_agreement(scenario["agreement"]["id"])["outstanding_balance_cents"] == 0


def test_the_completed_move_hands_the_membership_and_its_counter_to_the_receiving_club():
    """Execution rewrites the billing club, counts the transfer, and swaps the live-membership row
    from one club's denominator to the other's.

    PRD 3.6: "Executing the approved move is also the receiving club's act, advancing the request
    `APPROVED → COMPLETED` with an optional `note`. It requires that the agreement's `home_club_id`
    still equals the request's `from_club_id`; if some other transfer got there first, the attempt
    is refused with `ERR_HOME_CLUB_MISMATCH`. Completion stamps `effective_on` with the logical
    clock date and then cascades through three levels. First, the agreement's `home_club_id` is
    rewritten to the `to_club_id` and its `transfer_count` increments by 1. Second, because the
    agreement's home club moved, both clubs' counters are recomputed from the share definition of
    §3.4 — the releasing club loses this agreement from its `active_agreement_count` and, where
    applicable, from its `delinquent_member_count`, the receiving club gains it, and
    `collections_watch` is recomputed on both."

    Design: Corner/calculations/corner_intra_franchise_transfer_carries_no_fee_and_posts_no_billing_event
    """
    scenario = _completed_intra_franchise_transfer()

    assert scenario["request"]["status"] == "COMPLETED"
    assert scenario["request"]["effective_on"] == "2026-08-01"
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["home_club_id"] == scenario["host_club"]["id"]
    assert agreement["transfer_count"] == 1
    assert read_club(scenario["home_club"]["id"])["active_agreement_count"] == 0
    assert read_club(scenario["host_club"]["id"])["active_agreement_count"] == 1


def test_the_transferred_membership_keeps_the_price_it_was_sold_at():
    """Moving clubs is not a repricing event: the pinned monthly figure survives the handover.

    PRD 3.6: "Two things stay exactly as signed: the agreement's `state_code` keeps the statute of
    the club where it was originally sold, and its `effective_monthly_dues_cents` keeps the price it
    was sold at, even when the receiving club's list pricing differs."

    Design: Corner/calculations/corner_intra_franchise_transfer_carries_no_fee_and_posts_no_billing_event
    """
    scenario = _completed_intra_franchise_transfer()

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["effective_monthly_dues_cents"] == 4500
    assert agreement["state_code"] == "CA"


def _equal_split_allocation() -> dict:
    """Two eligible operators, one enrolled membership each, and a 100000-cent pool distributed by
    head count of operators rather than by enrolled members."""
    setup = setup_two_franchise_clubs(
        first={
            "legal_name": "Harborline Fitness LLC",
            "contact_email": "ops@harborlinefit.example",
            "club_name": "Harborline Downtown",
            "national_account_eligible": True,
        },
        second={
            "legal_name": "Ridgeway Athletics LLC",
            "contact_email": "ops@ridgewayath.example",
            "club_name": "Ridgeway Valley",
            "center_lat": 34.5,
            "center_lng": -118.0,
            "national_account_eligible": True,
        },
    )
    account = create_corporate_account(
        name="Meridian Logistics",
        corporate_credit_pct=0.045,
        allocation_method="EQUAL_SPLIT",
    )
    agreements = []
    for side, full_name, email in [
        ("first", "Ana Reyes", "ana.reyes@example.com"),
        ("second", "Ben Oduya", "ben.oduya@example.com"),
    ]:
        club_id = setup[side]["club"]["id"]
        member = create_member(club_id, full_name=full_name, email=email)
        agreements.append(
            sign_active_agreement(
                member["id"],
                club_id,
                setup["plan_template"]["id"],
                multi_club_access=False,
                corporate_account_id=account["id"],
            )
        )
    fund_corporate_account(account["id"], 100000)
    setup["account"] = account
    setup["agreements"] = agreements
    setup["allocation"] = allocate_corporate_account(
        account["id"], note="August subsidy distribution"
    )
    return setup


def test_equal_split_divides_the_pool_by_head_count_of_operators():
    """Under `EQUAL_SPLIT` each eligible operator's weight becomes 1, so a 100000-cent pool halves
    exactly and leaves no remainder to waterfall.

    PRD 3.8: "When the method is `EQUAL_SPLIT`, every eligible franchisee's weight is replaced by 1
    before the split, so the pool divides by head count of operators rather than by enrolled
    members; when it is `USAGE_SHARE`, the weights computed above are used as they stand. Each
    franchisee's base share is the pool multiplied by that franchisee's weight, divided by the total
    weight across all eligible franchisees, with any fraction discarded."

    Design: Corner/calculations/corner_equal_split_allocation_ignores_enrolment_weights
    """
    setup = _equal_split_allocation()

    first = read_franchisee(setup["first"]["franchisee"]["id"])
    second = read_franchisee(setup["second"]["franchisee"]["id"])
    assert first["corporate_allocation_cents"] == 50000
    assert second["corporate_allocation_cents"] == 50000


def test_the_equal_split_allocation_empties_the_pool_without_losing_a_cent():
    """The whole undistributed pool moves into the allocated column and the two shares add back up
    to it exactly.

    PRD 3.8: "Every eligible franchisee's `corporate_allocation_cents` increases by its final share,
    `allocated_cents` increases by the whole pool, and `pool_balance_cents` is set to 0. Because of
    the explicit remainder waterfall, the distributed shares sum to the pool exactly — not one cent
    more or fewer."

    Design: Corner/calculations/corner_equal_split_allocation_ignores_enrolment_weights
    """
    setup = _equal_split_allocation()

    account = read_corporate_account(setup["account"]["id"])
    assert account["pool_balance_cents"] == 0
    assert account["allocated_cents"] == 100000
    assert account["lifetime_funded_cents"] == 100000
    assert_corporate_pool_conserved(account)


def test_the_four_and_a_half_percent_corporate_credit_prices_each_enrolment_at_4297():
    """The credit is rounded on its own before it is subtracted, so 4.5 percent of 4500 is 203 and
    the effective monthly figure is 4297.

    PRD 3.3: "Each of the three discount components is computed and rounded half up to whole cents
    *independently*: `promo_discount_cents` is 0 when no `promotion_id` was quoted and otherwise
    the base multiplied by the promotion's `discount_pct`, rounded half up; `corporate_credit_cents`
    is 0 when no `corporate_account_id` was named and otherwise the base multiplied by the
    account's `corporate_credit_pct`, rounded half up; and `multi_club_credit_cents` is 0 when
    `multi_club_access` is false and otherwise the base multiplied by the multi-club credit rate of
    0.015 — one and a half percent — rounded half up."

    Design: Corner/calculations/corner_equal_split_allocation_ignores_enrolment_weights
    """
    setup = _equal_split_allocation()

    for agreement in setup["agreements"]:
        assert agreement["corporate_credit_cents"] == 203
        assert agreement["effective_monthly_dues_cents"] == 4297


def _out_of_order_charges_with_one_payment() -> dict:
    """Two charges posted in the wrong order — the October row first, the September row second —
    and a single 4500-cent payment against them at a 2026-10-04 clock."""
    scenario = _one_club_and_one_member()
    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    set_clock_date("2026-10-04")
    post_dues(agreement["id"], 4500, "2026-09-01", "2026-10-05")
    post_dues(agreement["id"], 4500, "2026-08-01", "2026-09-05")
    scenario["agreement"] = agreement
    scenario["payment"] = post_payment(agreement["id"], 4500, "2026-09-05")
    return scenario


def test_the_credit_walk_takes_the_charges_in_due_date_order_not_insertion_order():
    """The single payment must satisfy the September row even though the October row was appended
    first, which leaves the not-yet-due October charge as the earliest unsatisfied one and the
    membership at no age at all.

    PRD 3.4: "Ageing is decided by first-in-first-out application, which is what identifies *which*
    charge is the oldest unsatisfied one. Available credit starts as the payment total plus the
    write-off total. Walking the charges in their strict due-date order, each charge whose full
    amount the remaining credit can cover consumes that amount from the credit and is treated as
    satisfied; the first charge the remaining credit cannot fully cover is the earliest unsatisfied
    charge, and the walk stops there. If `outstanding_balance_cents` is at or below zero, or if no
    unsatisfied charge was found, then `delinquency_days` is 0. Otherwise `delinquency_days` is the
    number of whole days from that earliest unsatisfied charge's `due_on` to the logical clock date,
    floored at 0 so that a charge not yet due never produces a negative age."

    Design: Corner/calculations/corner_out_of_order_billing_events_are_projected_in_due_date_order
    """
    scenario = _out_of_order_charges_with_one_payment()

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["outstanding_balance_cents"] == 4500
    assert agreement["delinquency_days"] == 0


def test_the_charge_ordering_is_by_due_date_with_creation_time_only_breaking_ties():
    """Both charges count towards the balance and the one payment counts once, so the projection
    totals are insensitive to the order the rows arrived in.

    PRD 3.4: "Charges are the entries whose type is `DUES_POSTED` or `TRANSFER_FEE_POSTED`, and they
    are considered in ascending `due_on`, with ascending `created_at` breaking ties.
    `dues_paid_cents` is the sum of `amount_cents` over every `PAYMENT_RECEIVED` entry."

    Design: Corner/calculations/corner_out_of_order_billing_events_are_projected_in_due_date_order
    """
    scenario = _out_of_order_charges_with_one_payment()

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["dues_paid_cents"] == 4500
    assert scenario["payment"]["resulting_outstanding_balance_cents"] == 4500


def test_an_outstanding_balance_that_is_not_yet_due_still_reads_as_current():
    """The cascade is driven by the age of the oldest unsatisfied charge rather than by the balance,
    so 4500 outstanding at zero days is `CURRENT` and no club counter reacts.

    PRD 3.4: "If `outstanding_balance_cents` is at or below zero, `dues_status` becomes `CURRENT`.
    Otherwise, if the prior `dues_status` was `IN_COLLECTIONS` or `WRITTEN_OFF`, it stays exactly
    where it was — those two states are sticky and a partial payment does not walk them back.
    Otherwise, if `delinquency_days` is at least 30, `dues_status` becomes `DELINQUENT`. Otherwise,
    if `delinquency_days` is at least 1, it becomes `PAST_DUE`. Otherwise it becomes `CURRENT`."

    Design: Corner/calculations/corner_out_of_order_billing_events_are_projected_in_due_date_order
    """
    scenario = _out_of_order_charges_with_one_payment()

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["agreement_status"] == "ACTIVE"
    assert agreement["dues_status"] == "CURRENT"
    club = read_club(scenario["club"]["id"])
    assert club["active_agreement_count"] == 1
    assert club["delinquent_member_count"] == 0
    assert club["collections_watch"] is False


def _aged_arrears(clock_date: str) -> dict:
    """One barely-activated membership carrying an unpaid 9000-cent charge due 2026-09-05,
    re-projected at the requested clock date by a zero-amount failure marker."""
    scenario = _one_club_and_one_member()
    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    post_dues(agreement["id"], 9000, "2026-08-01", "2026-09-05")
    post_payment(agreement["id"], 100, "2026-08-02")
    set_clock_date("2026-10-04")
    post_payment_failure(agreement["id"], "2026-10-04")
    scenario["at_29_days"] = read_agreement(agreement["id"])
    scenario["club_at_29_days"] = read_club(scenario["club"]["id"])
    scenario["franchisee_at_29_days"] = read_franchisee(scenario["franchisee"]["id"])
    if clock_date == "2026-10-05":
        set_clock_date("2026-10-05")
        post_payment_failure(agreement["id"], "2026-10-05")
    scenario["agreement"] = agreement
    return scenario


def test_a_charge_twenty_nine_days_overdue_is_only_past_due():
    """One day short of the threshold the membership is late but not yet delinquent, and the strict
    `at least 30` comparison is what keeps it there.

    PRD 3.4: "The boundary is exact and inclusive on the delinquency side: an age of 29 days is
    `PAST_DUE`, and an age of 30 days is `DELINQUENT`."

    Design: Corner/calculations/corner_delinquency_threshold_flips_past_due_to_delinquent_on_the_thirtieth_day
    """
    scenario = _aged_arrears("2026-10-04")

    assert scenario["at_29_days"]["delinquency_days"] == 29
    assert scenario["at_29_days"]["dues_status"] == "PAST_DUE"


def test_the_same_charge_one_day_later_is_delinquent():
    """At exactly 30 days the inclusive comparison flips the collections dimension, with the
    remaining 8900 cents unchanged by either failure marker.

    PRD 3.4: "The boundary is exact and inclusive on the delinquency side: an age of 29 days is
    `PAST_DUE`, and an age of 30 days is `DELINQUENT`."

    Design: Corner/calculations/corner_delinquency_threshold_flips_past_due_to_delinquent_on_the_thirtieth_day
    """
    scenario = _aged_arrears("2026-10-05")

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["delinquency_days"] == 30
    assert agreement["dues_status"] == "DELINQUENT"
    assert agreement["outstanding_balance_cents"] == 8900


def test_only_the_step_into_delinquency_moves_the_club_and_the_franchisee():
    """`PAST_DUE` does not count as delinquent, so the counters stay flat on the first marker and
    only the second one raises the club's watch flag and docks its operator.

    PRD 3.4: "Moving `CURRENT → PAST_DUE` recomputes the home club's `delinquent_member_count` and
    `collections_watch`, which may well leave both unchanged, because `PAST_DUE` does not count as
    delinquent. Moving `PAST_DUE → DELINQUENT` does count: the home club's
    `delinquent_member_count` increases and `collections_watch` is recomputed, and because that flag
    may have flipped to true, the owning franchisee's `compliance_score` is recomputed and the
    franchisee is demoted to `PROBATION` if the score fell below 70 — one event, three entities, and
    a `version` increment on the agreement, the club and the franchisee."

    Design: Corner/calculations/corner_delinquency_threshold_flips_past_due_to_delinquent_on_the_thirtieth_day
    """
    scenario = _aged_arrears("2026-10-05")

    assert scenario["club_at_29_days"]["delinquent_member_count"] == 0
    assert scenario["club_at_29_days"]["collections_watch"] is False
    assert scenario["franchisee_at_29_days"]["compliance_score"] == 100
    club = read_club(scenario["club"]["id"])
    assert club["delinquent_member_count"] == 1
    assert club["collections_watch"] is True
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["collections_watch_club_count"] == 1
    assert franchisee["compliance_score"] == 80
    assert franchisee["status"] == "ACTIVE"


def _one_delinquent_and_one_never_paid_membership() -> dict:
    """A club holding one delinquent live membership and one signed-but-never-paid membership at a
    2026-10-05 clock."""
    scenario = _one_club_and_one_member()
    second_member = create_member(
        scenario["club"]["id"], full_name="Ben Oduya", email="ben.oduya@example.com"
    )
    live = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    never_paid = sign_agreement(
        second_member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    post_dues(live["id"], 9000, "2026-08-01", "2026-09-05")
    post_payment(live["id"], 100, "2026-08-02")
    set_clock_date("2026-10-05")
    post_payment_failure(live["id"], "2026-10-05")
    scenario["live"] = live
    scenario["never_paid"] = never_paid
    return scenario


def test_the_arrears_share_counts_only_live_memberships_in_its_denominator():
    """Two agreements sit at the club but only one is live, so the denominator is 1 and the whole of
    it is in arrears — comfortably past the fifteen percent watch threshold.

    PRD 3.4: "The denominator is the number of agreements whose `home_club_id` is that club and
    whose `agreement_status` is `ACTIVE`, `FROZEN` or `CANCELLATION_PENDING`; that figure is stored
    as `active_agreement_count`. The numerator is how many of those same agreements have a
    `dues_status` of `DELINQUENT`, `IN_COLLECTIONS` or `WRITTEN_OFF`; that figure is stored as
    `delinquent_member_count`. `collections_watch` is true when the denominator is greater than 0
    and the numerator divided by the denominator is strictly greater than 0.15 — more than fifteen
    percent of live memberships in arrears."

    Design: Corner/calculations/corner_delinquency_share_denominator_excludes_pending_agreements
    """
    scenario = _one_delinquent_and_one_never_paid_membership()

    assert read_agreement(scenario["live"]["id"])["dues_status"] == "DELINQUENT"
    club = read_club(scenario["club"]["id"])
    assert club["active_agreement_count"] == 1
    assert club["delinquent_member_count"] == 1
    assert club["collections_watch"] is True


def test_the_never_paid_membership_stays_out_of_every_counter():
    """The second agreement has taken no payment, so it is signed but not live and contributes
    nothing to either side of the share.

    PRD 3.4: "Until that payment arrives the membership is signed but not live, and it contributes
    to no club counter."

    Design: Corner/calculations/corner_delinquency_share_denominator_excludes_pending_agreements
    """
    scenario = _one_delinquent_and_one_never_paid_membership()

    never_paid = read_agreement(scenario["never_paid"]["id"])
    assert never_paid["agreement_status"] == "PENDING"
    assert never_paid["dues_status"] == "CURRENT"
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["collections_watch_club_count"] == 1
    assert franchisee["compliance_score"] == 80


def _truthful_royalty_report() -> dict:
    """One undiscounted live membership and a perfectly accurate head count for a closed month."""
    scenario = _one_club_and_one_member()
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    set_clock_date("2026-09-05")
    scenario["report"] = submit_royalty_report(scenario["franchisee"]["id"], "2026-08", 1)
    return scenario


def test_the_verified_basis_is_summed_from_the_qualifying_agreements():
    """The one live membership signed inside the month qualifies, and its pinned effective dues are
    the whole verified basis.

    PRD 3.9: "The qualifying set is every membership agreement whose home club belongs to this
    franchisee, whose `agreement_status` is `ACTIVE` or `CANCELLATION_PENDING`, and whose `signed_on`
    date is on or before the last calendar day of the reported month; the agreement's status as it
    stands at submission time is used, with no historical replay, and `PENDING`, `FROZEN` and
    `CANCELLED` agreements are excluded outright. `verified_member_count` is the size of that set and
    `verified_dues_basis_cents` is the sum of the set's `effective_monthly_dues_cents` values —
    summed first and rounded once, never rounded per agreement."

    Design: Corner/calculations/corner_royalty_report_inside_the_variance_tolerance_is_accepted
    """
    scenario = _truthful_royalty_report()

    assert scenario["report"]["verified_member_count"] == 1
    assert scenario["report"]["verified_dues_basis_cents"] == 4500


def test_both_royalty_figures_agree_when_the_membership_carries_no_discount():
    """List price and pinned price coincide here, so the reported basis and the verified basis both
    produce 293 cents at 650 basis points.

    PRD 3.9: "The reported basis, `reported_dues_basis_cents`, is `reported_member_count` multiplied
    by the brand list price of 4500 cents per member per month, which ignores every promotion,
    corporate credit and multi-club credit; `reported_royalty_cents` is that basis multiplied by the
    franchisee's `royalty_rate_bps` divided by 10000, rounded half up to whole cents. The verified
    basis produces `royalty_due_cents` the same way, from `verified_dues_basis_cents` and the same
    rate."

    Design: Corner/calculations/corner_royalty_report_inside_the_variance_tolerance_is_accepted
    """
    scenario = _truthful_royalty_report()

    assert scenario["report"]["reported_dues_basis_cents"] == 4500
    assert scenario["report"]["reported_royalty_cents"] == 293
    assert scenario["report"]["royalty_due_cents"] == 293


def test_a_report_with_no_variance_is_accepted_and_costs_the_operator_nothing():
    """A truthful count gives a variance of exactly zero, which is inside the five percent
    tolerance, so the report resolves itself and no dispute is recorded.

    PRD 3.9: "The report is created `SUBMITTED` and immediately auto-resolves on the absolute value
    of `variance_pct` against a tolerance of 5.00 percent: a variance whose magnitude exceeds 5.00
    resolves to `DISPUTED`, and anything at or within 5.00 resolves to `ACCEPTED`. `ACCEPTED` is
    terminal. Resolving to `DISPUTED` increments the franchisee's `disputed_royalty_count` by 1,
    recomputes its `compliance_score` — demoting it to `PROBATION` if that drops it below 70 — and
    increments the franchisee's `version` by 1 on that path."

    Design: Corner/calculations/corner_royalty_report_inside_the_variance_tolerance_is_accepted
    """
    scenario = _truthful_royalty_report()

    assert scenario["report"]["variance_pct"] == 0.00
    assert scenario["report"]["status"] == "ACCEPTED"
    assert scenario["report"]["adjusted_royalty_cents"] is None
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["disputed_royalty_count"] == 0
    assert franchisee["compliance_score"] == 100
