"""
Derived numbers under conditions that separate a correct formula from a
plausible one: tier ceilings that must be inclusive, a contact requirement that
filters on method and calendar month rather than on count, outcome categories
gated by a service-duration floor, a selector that ranks on utilization rather
than on points, and a monthly cap applied session by session.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    FISCAL_HEADERS,
    assert_authorization_units,
    assert_caseload_summary,
    assert_case_weight,
    assert_cents,
    assert_fpl_percent,
    assert_ledger,
    assign_coordinator,
    build_active_services,
    build_authorized,
    create_child,
    create_coordinator,
    create_cost_share,
    create_referral,
    document_visit,
    factories,
    read_authorization,
    read_caseload_summary,
    read_coordinator,
    read_cost_share,
    read_referral,
    read_service_line,
    read_timeline,
    schedule_visit,
    set_clock,
    validate_error,
    validate_success,
)

PROVIDER = {
    "agency_name": "Riverbend Therapy",
    "qualified_service_types": ["SPEECH_THERAPY"],
    "credential_expiry_date": "2027-06-30",
}
HOUSEHOLD_THRESHOLD_CENTS = 3_245_000

# effective_month, clock to advance to first, declared income, fpl percent,
# tier, rate, cap, assessed fee
TIER_LADDER = (
    ("2026-03", None, 8_112_500, 250.0, "TIER_0", 0.00, 0, 0),
    (
        "2026-04", "2026-04-02T09:00:00Z", 12_980_000, 400.0,
        "TIER_1", 0.05, 12_000, 2_600,
    ),
    (
        "2026-05", "2026-05-04T09:00:00Z", 19_470_000, 600.0,
        "TIER_2", 0.10, 30_000, 5_200,
    ),
    (
        "2026-06", "2026-06-02T09:00:00Z", 20_000_000, 616.3,
        "TIER_3", 0.15, 60_000, 7_800,
    ),
)


class TestTierSelection:
    """Three incomes land exactly on a ceiling and one lands just past it."""

    def test_each_tier_ceiling_belongs_to_the_lower_tier(self, api):
        """
        Percentages of exactly 250.0, 400.0 and 600.0 stay in the tier they close
        rather than spilling into the next one, and a percentage just above the last
        ceiling reaches the top tier.

        PRD 3.8: "A percentage of exactly 250.0 is therefore `TIER_0`, not `TIER_1`,
        and a percentage of exactly 600.0 is `TIER_2`, not `TIER_3`."

        Design: Corner/calculations/cost_share_tier_ceilings_are_inclusive_upper_bounds
        """
        case = build_active_services(api)

        for month, clock, income, percent, tier, rate, cap, fee in TIER_LADDER:
            if clock is not None:
                set_clock(api, clock)
            row = validate_success(
                api.create_cost_share(
                    factories.cost_share_payload(
                        case.referral_id,
                        effective_month=month,
                        declared_annual_gross_income_cents=income,
                    ),
                    FISCAL_HEADERS,
                ),
                201,
            )
            assert_cents(
                row["fpl_threshold_cents"],
                HOUSEHOLD_THRESHOLD_CENTS,
                "fpl_threshold_cents",
            )
            assert_fpl_percent(row["fpl_percent"], percent)
            assert row["tier_code"] == tier
            assert float(row["coinsurance_rate"]) == pytest.approx(rate, abs=0.001)
            assert float(row["effective_coinsurance_rate"]) == pytest.approx(
                rate, abs=0.001
            )
            assert_cents(row["monthly_cap_cents"], cap, "monthly_cap_cents")
            assert_cents(
                row["assessed_monthly_fee_cents"], fee, "assessed_monthly_fee_cents"
            )
            assert row["status"] == "PROVISIONAL"
            assert_cents(
                row["insurance_offset_cents"], 0, "insurance_offset_cents"
            )
            assert row["final_monthly_fee_cents"] is None


# ─── The monthly contact requirement ──────────────────────────────────

CONTACT_DATE = "2026-03-20"
NEXT_MONTH_CLOCK = "2026-04-21T09:00:00Z"


def _log_contact(api, case, contact_method, summary):
    return validate_success(
        api.create_contact_log(
            case.referral_id,
            factories.contact_log_payload(
                CONTACT_DATE, contact_method=contact_method, summary=summary
            ),
            case.coordinator_headers,
        ),
        201,
    )


class TestMonthlyContactRequirement:
    """The filter is on method and on calendar month, never on contact count."""

    def test_an_email_never_satisfies_the_requirement_but_a_home_visit_does(
        self, api
    ):
        """
        A case with no contacts is due while the grace period is still open; an
        emailed contact is recorded faithfully yet leaves the case due; a home visit
        on the same day satisfies the month.

        PRD 3.9: "The server derives `contact_month` as the year-and-month prefix of
        `contact_date`, and derives `qualifies_for_monthly_requirement` as true
        exactly when the `contact_method` is `HOME_VISIT`, `PHONE` or `VIDEO`."

        Design: Corner/calculations/monthly_contact_status_counts_only_qualifying_methods
        """
        case = build_active_services(api)

        opening = read_timeline(api, case.referral_id)
        assert opening["monthly_contact_status"] == "DUE"
        assert opening["last_qualifying_contact_date"] is None

        emailed = _log_contact(
            api, case, "EMAIL", "Emailed the March service summary to the family."
        )
        assert emailed["qualifies_for_monthly_requirement"] is False
        assert emailed["contact_month"] == "2026-03"
        assert read_timeline(api, case.referral_id)["monthly_contact_status"] == "DUE"

        visited = _log_contact(
            api,
            case,
            "HOME_VISIT",
            "Home visit to review routines-based outcomes with both parents.",
        )
        assert visited["qualifies_for_monthly_requirement"] is True

        satisfied = read_timeline(api, case.referral_id)
        assert satisfied["monthly_contact_status"] == "COMPLIANT"
        assert satisfied["last_qualifying_contact_date"] == CONTACT_DATE

    def test_last_months_visit_leaves_the_new_month_delinquent(self, api):
        """
        Rolling the clock into a month with no qualifying contact past the twentieth
        makes the same case delinquent, while the earlier qualifying date is still
        reported.

        PRD 3.9: "A contact in a prior month never satisfies the current month."

        Design: Corner/calculations/monthly_contact_status_counts_only_qualifying_methods
        """
        case = build_active_services(api)
        _log_contact(
            api,
            case,
            "HOME_VISIT",
            "Home visit to review routines-based outcomes with both parents.",
        )
        assert (
            read_timeline(api, case.referral_id)["monthly_contact_status"]
            == "COMPLIANT"
        )

        set_clock(api, NEXT_MONTH_CLOCK)

        overdue = read_timeline(api, case.referral_id)
        assert overdue["monthly_contact_status"] == "DELINQUENT"
        assert overdue["last_qualifying_contact_date"] == CONTACT_DATE


# ─── Child outcome progress categories ────────────────────────────────

LONG_SERVICE_CLOCK = "2026-10-01T09:00:00Z"
LONG_SERVICE_EXIT_DATE = "2026-10-01"
SHORT_SERVICE_CLOCK = "2026-09-15T09:00:00Z"
SHORT_SERVICE_EXIT_DATE = "2026-09-15"
EXIT_RATINGS = {
    "exit_rating_social": 2,
    "exit_rating_knowledge": 5,
    "exit_rating_needs": 6,
}


def _exit_after(api, case, clock, exit_date):
    """Advance to the given clock and exit the case with the same three ratings."""
    set_clock(api, clock)
    return validate_success(
        api.exit_referral(
            case.referral_id,
            factories.exit_payload(
                exit_date, exit_reason="FAMILY_WITHDREW", **EXIT_RATINGS
            ),
            case.coordinator_headers,
        ),
        200,
    )


class TestProgressCategories:
    """Three areas, three verdicts — and a floor that suppresses all three."""

    def test_one_exit_produces_a_regression_a_gain_and_an_age_level_arrival(
        self, api
    ):
        """
        From entry ratings of 3, 4 and 3 to exit ratings of 2, 5 and 6 over a service
        period long enough to compare, the three areas are graded independently and
        land on three different categories.

        PRD 3.9: "When the exit rating is lower than the entry rating the category is
        `a`, a regression."

        Design: Corner/calculations/exit_progress_categories_span_regression_progress_and_age_level
        """
        case = build_active_services(api)

        exited = _exit_after(
            api, case, LONG_SERVICE_CLOCK, LONG_SERVICE_EXIT_DATE
        )
        assert exited["status"] == "EXITED"
        assert exited["service_duration_days"] == 195
        assert exited["progress_category_social"] == "a"
        assert exited["progress_category_knowledge"] == "c"
        assert exited["progress_category_needs"] == "d"
        assert exited["exit_date"] == LONG_SERVICE_EXIT_DATE
        assert exited["exit_rating_social"] == 2
        assert exited["exit_rating_knowledge"] == 5
        assert exited["exit_rating_needs"] == 6
        assert_case_weight(exited["case_weight_points"], 0)
        assert exited["monthly_contact_status"] == "NOT_APPLICABLE"

    def test_one_day_short_of_the_floor_suppresses_every_category(self, api):
        """
        The identical ratings one day short of the comparability floor report no
        category at all in any of the three areas, while the ratings themselves are
        still stored.

        PRD 3.9: "If a case received services for fewer than 180 days, no meaningful
        comparison is possible and all three of `progress_category_social`,
        `progress_category_knowledge` and `progress_category_needs` are recorded as
        `NOT_COMPARABLE`, whatever the ratings say."

        Design: Corner/calculations/progress_categories_are_not_comparable_below_180_service_days
        """
        case = build_active_services(api)

        exited = _exit_after(
            api, case, SHORT_SERVICE_CLOCK, SHORT_SERVICE_EXIT_DATE
        )
        assert exited["service_duration_days"] == 179
        assert exited["progress_category_social"] == "NOT_COMPARABLE"
        assert exited["progress_category_knowledge"] == "NOT_COMPARABLE"
        assert exited["progress_category_needs"] == "NOT_COMPARABLE"
        assert exited["exit_rating_social"] == 2
        assert exited["exit_rating_knowledge"] == 5
        assert exited["exit_rating_needs"] == 6


# ─── Choosing a coordinator ───────────────────────────────────────────

INTAKE_INSTANT = "2026-03-02T09:00:00Z"


class TestCoordinatorAutoSelection:
    """Two eligible candidates, and the ranking metric decides between them."""

    def test_the_larger_ceiling_wins_even_though_it_carries_the_same_points(
        self, api
    ):
        """
        A coordinator already carrying 1.50 points against a 4.00-point ceiling and
        an empty coordinator with a 12.00-point ceiling are both eligible for the
        case; the server picks the one whose projected utilization is lower, which is
        not the one with fewer points, since both would land on 1.50.

        PRD 3.2: "Each candidate is ranked by its **projected utilization** — the
        coordinator's current `weighted_caseload_points` plus the case's projected
        weight, divided by that coordinator's `max_weighted_caseload_points`, rounded
        half up to four decimal places — and the candidate with the lowest projected
        utilization wins."

        Design: Corner/calculations/coordinator_auto_selection_ranks_on_projected_utilization_not_points
        """
        set_clock(api, INTAKE_INSTANT)
        alpha_id = create_coordinator(
            api, full_name="Alpha Osei", max_weighted_caseload_points=4.00
        )
        bravo_id = create_coordinator(
            api, full_name="Bravo Lindqvist", max_weighted_caseload_points=12.00
        )

        first_referral_id = create_referral(api, create_child(api))
        assign_coordinator(api, first_referral_id, alpha_id)

        second_referral_id = create_referral(
            api,
            create_child(
                api,
                first_name="Beau",
                last_name="Ferris",
                date_of_birth="2024-08-02",
            ),
            primary_referral_source="CHILD_CARE",
            presenting_concern="Gross motor delay reported by the child care centre.",
        )

        assigned = validate_success(
            api.assign_coordinator(
                second_referral_id,
                factories.assign_coordinator_payload(),
                ADMIN_HEADERS,
            ),
            200,
        )
        assert assigned["coordinator_id"] == bravo_id
        assert assigned["status"] == "EVALUATION_PENDING"
        assert_case_weight(assigned["case_weight_points"], 1.50)

        assert_caseload_summary(
            read_caseload_summary(api, alpha_id),
            coordinator_id=alpha_id,
            active_case_count=1,
            weighted_caseload_points=1.50,
            max_weighted_caseload_points=4.00,
            utilization_ratio=0.3750,
            caseload_posture="OPEN",
        )
        assert_caseload_summary(
            read_caseload_summary(api, bravo_id),
            coordinator_id=bravo_id,
            active_case_count=1,
            weighted_caseload_points=1.50,
            max_weighted_caseload_points=12.00,
            utilization_ratio=0.1250,
            headroom_points=10.50,
        )


class TestInterpreterLanguageFilter:
    """The language clause only binds when the case needs an interpreter."""

    def test_a_language_the_roster_cannot_serve_empties_the_candidate_set(self, api):
        """
        With one English-speaking coordinator on the roster, a Somali-speaking case
        that requires an interpreter has no candidate at all, and naming that same
        coordinator explicitly fails the identical clause; nothing is written by
        either refusal.

        PRD 3.2: "A coordinator is a candidate for a case when four clauses all hold:
        the coordinator's `status` is `ACTIVE`; the coordinator's `county_code` equals
        the referral's `county_code`; either the case does not require an interpreter,
        or the case's family `primary_language` appears in the coordinator's
        `language_codes`; and the coordinator's current `weighted_caseload_points`
        plus the case's projected `case_weight_points` is less than or equal to the
        coordinator's `max_weighted_caseload_points`."

        Design: Corner/calculations/interpreter_language_filter_removes_every_candidate
        """
        set_clock(api, INTAKE_INSTANT)
        coordinator_id = create_coordinator(api, language_codes=["EN"])
        child_id = create_child(
            api,
            first_name="Nadifa",
            last_name="Warsame",
            date_of_birth="2024-07-01",
            primary_language="SO",
        )
        referral_id = create_referral(
            api,
            child_id,
            primary_referral_source="PARENT",
            presenting_concern="Parent reports no two-word combinations at 20 months.",
            interpreter_required=True,
        )

        validate_error(
            api.assign_coordinator(
                referral_id, factories.assign_coordinator_payload(), ADMIN_HEADERS
            ),
            ApiErrorId.NO_ELIGIBLE_COORDINATOR.value,
            409,
        )
        validate_error(
            api.assign_coordinator(
                referral_id,
                factories.assign_coordinator_payload(coordinator_id=coordinator_id),
                ADMIN_HEADERS,
            ),
            ApiErrorId.COORDINATOR_NOT_ELIGIBLE.value,
            422,
        )

        referral = read_referral(api, referral_id)
        assert referral["status"] == "INTAKE"
        assert referral["coordinator_id"] is None
        assert_case_weight(referral["case_weight_points"], 0)
        assert referral["version"] == 1

        coordinator = read_coordinator(api, coordinator_id)
        assert_case_weight(coordinator["weighted_caseload_points"], 0)
        assert coordinator["active_case_count"] == 0


# ─── The monthly cap, session by session ──────────────────────────────

EXPENSIVE_LINE = {"unit_rate_cents": 100_000}
CAP_SESSIONS = (
    ("2026-03-23T15:00:00Z", "2026-03-23T15:30:00Z"),
    ("2026-03-23T16:00:00Z", "2026-03-23T16:30:00Z"),
    ("2026-03-23T17:00:00Z", "2026-03-23T17:30:00Z"),
)
DOCUMENT_CLOCK = "2026-03-24T12:00:00Z"
# Raw share per session is 2 units x 100 000 cents x 0.05 = 10 000 cents, against
# a TIER_1 monthly cap of 12 000.
CAP_OUTCOMES = ((10_000, "ACCRUED"), (2_000, "CAPPED"), (0, "CAPPED"))


class TestMonthlyCapAcrossSessions:
    """The cap is a monthly remainder, not a per-session ceiling."""

    def test_the_remainder_clips_the_second_session_and_empties_the_third(self, api):
        """
        Three identical sessions compute the same raw share, but the first accrues
        whole, the second is truncated to what was left of the month's cap, and the
        third accrues nothing at all — and the month's total stops exactly at the cap.

        PRD 3.8: "Otherwise `family_share_cents` is the lesser of the raw share and
        the cap remainder, and `billing_status` is `ACCRUED` when the full raw share
        was charged or `CAPPED` when the remainder truncated it."

        Design: Corner/calculations/per_visit_family_share_is_clipped_by_the_monthly_cap_remainder
        """
        case = build_authorized(
            api,
            provider=PROVIDER,
            authorization={"authorized_units": 6},
            line=EXPENSIVE_LINE,
        )
        case.cost_share_id = create_cost_share(api, case.referral_id)
        assert_cents(
            read_cost_share(api, case.cost_share_id)["assessed_monthly_fee_cents"],
            12_000,
            "assessed_monthly_fee_cents",
        )

        for start, end in CAP_SESSIONS:
            case.visit_ids.append(
                schedule_visit(api, case.authorization_id, start, end)
            )
        set_clock(api, DOCUMENT_CLOCK)

        for visit_id, (share, billing) in zip(case.visit_ids, CAP_OUTCOMES):
            documented = document_visit(
                api, visit_id, case.provider_id, actual_units=2
            )
            assert documented["visit_status"] == "DELIVERED"
            assert documented["billing_status"] == billing
            assert_cents(documented["family_share_cents"], share, "family_share_cents")

        ledger = read_cost_share(api, case.cost_share_id)
        assert_cents(ledger["month_accrued_cents"], 12_000, "month_accrued_cents")
        assert_ledger(
            ledger,
            total_assessed_cents=12_000,
            family_balance_cents=12_000,
            family_waived_cents=0,
        )

        authorization = read_authorization(api, case.authorization_id)
        assert_authorization_units(authorization, units_consumed=6, units_remaining=0)
        assert authorization["status"] == "EXHAUSTED"
        assert read_service_line(api, case.line_id)["units_delivered"] == 6


# ─── The makeup obligation ────────────────────────────────────────────

FIRST_SESSION = ("2026-03-23T15:00:00Z", "2026-03-23T15:30:00Z")
CANCELLED_SESSION = ("2026-03-25T15:00:00Z", "2026-03-25T15:45:00Z")
SECOND_CANCELLED_SESSION = ("2026-03-27T15:00:00Z", "2026-03-27T15:45:00Z")
MAKEUP_SESSION = ("2026-04-02T15:00:00Z", "2026-04-02T15:45:00Z")
CANCELLATION_CLOCK = "2026-03-28T09:00:00Z"
MAKEUP_CLOCK = "2026-04-03T09:00:00Z"


def _cancel_by_provider(api, case, visit_id):
    return validate_success(
        api.document_visit(
            visit_id, {"visit_status": "CANCELLED_PROVIDER"}, case.provider_headers
        ),
        200,
    )


class TestMakeupObligation:
    """Only provider cancellations build the obligation, and 4 owed units is not
    yet at risk."""

    def test_a_makeup_session_discharges_the_obligation_and_clears_the_flag(
        self, api
    ):
        """
        Three owed units leave the line delivering; a second provider cancellation
        takes the total past the threshold and raises the case's service-gap flag; a
        makeup session against the first cancellation brings the total back under and
        the flag down, with the makeup's units counted as delivered.

        PRD 3.7: "A line is at risk when that owed figure is **strictly greater
        than** 4 units, so a line owing exactly 4 units is not at risk while a line
        owing 5 is."

        Design: Corner/calculations/makeup_visit_discharges_the_obligation_and_clears_at_risk
        """
        case = build_authorized(api, provider=PROVIDER)
        first_id = schedule_visit(api, case.authorization_id, *FIRST_SESSION)
        cancelled_id = schedule_visit(api, case.authorization_id, *CANCELLED_SESSION)
        second_cancelled_id = schedule_visit(
            api, case.authorization_id, *SECOND_CANCELLED_SESSION
        )
        case.visit_ids.extend([first_id, cancelled_id, second_cancelled_id])

        set_clock(api, DOCUMENT_CLOCK)
        document_visit(api, first_id, case.provider_id, actual_units=2)
        assert read_service_line(api, case.line_id)["status"] == "IN_DELIVERY"

        set_clock(api, CANCELLATION_CLOCK)
        cancelled = _cancel_by_provider(api, case, cancelled_id)
        assert cancelled["visit_status"] == "CANCELLED_PROVIDER"
        assert cancelled["billing_status"] == "CANCELLED_NO_CHARGE"
        assert cancelled["actual_units"] == 0

        owing_three = read_service_line(api, case.line_id)
        assert owing_three["makeup_owed_units"] == 3
        assert owing_three["status"] == "IN_DELIVERY"

        _cancel_by_provider(api, case, second_cancelled_id)
        at_risk = read_service_line(api, case.line_id)
        assert at_risk["makeup_owed_units"] == 6
        assert at_risk["status"] == "AT_RISK"
        assert at_risk["units_delivered"] == 2
        assert read_referral(api, case.referral_id)["service_gap_flag"] is True

        makeup = validate_success(
            api.create_visit(
                factories.visit_payload(
                    case.authorization_id,
                    *MAKEUP_SESSION,
                    makeup_for_visit_id=cancelled_id,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert makeup["makeup_for_visit_id"] == cancelled_id
        assert makeup["scheduled_units"] == 3
        case.visit_ids.append(makeup["id"])

        set_clock(api, MAKEUP_CLOCK)
        delivered = document_visit(
            api, makeup["id"], case.provider_id, actual_units=3
        )
        assert delivered["visit_status"] == "DELIVERED"
        assert delivered["actual_units"] == 3

        discharged = read_service_line(api, case.line_id)
        assert discharged["status"] == "IN_DELIVERY"
        assert discharged["makeup_owed_units"] == 3
        assert discharged["units_delivered"] == 5
        assert read_referral(api, case.referral_id)["service_gap_flag"] is False
