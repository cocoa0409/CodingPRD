"""
Paired calculations where the same inputs feed two stored figures that must
disagree: the statutory day count read gross and net, and the family fee read
provisional and final.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    FISCAL_HEADERS,
    STATUTORY_TIMELINE_DAYS,
    assert_cents,
    assert_fpl_percent,
    assert_ledger,
    assert_timeline,
    add_service_line,
    build_active_services,
    build_ifsp_pending,
    author_ifsp,
    create_cost_share,
    factories,
    read_cost_share,
    read_referral,
    set_clock,
    validate_success,
)

# The divergent-timeline case: 54 raw days against 12 documented excluded days.
TIMELINE_COMPLETION_CLOCK = "2026-03-26T09:00:00Z"
TIMELINE_MEETING_CLOCK = "2026-04-25T09:00:00Z"
TIMELINE_MEETING_DATE = "2026-04-25"
TIMELINE_RECOMPUTE_CLOCK = "2026-04-25T15:00:00Z"


def _build_divergent_timeline_case(api):
    """
    A case whose initial plan met on day 54 but which documented 12 days of
    family unavailability, so the gross and net counts fall on opposite sides
    of the statutory ceiling.
    """
    case = build_ifsp_pending(
        api,
        completion_clock=TIMELINE_COMPLETION_CLOCK,
        evaluation_completion={
            "completion_date": "2026-03-18",
            "family_unavailable_days": 7,
        },
        family_completion={
            "completion_date": "2026-03-25",
            "family_unavailable_days": 5,
        },
        determination={"determination_date": "2026-03-26"},
        entry_outcomes={"measurement_date": "2026-03-26"},
    )
    set_clock(api, TIMELINE_MEETING_CLOCK)
    case.clock = TIMELINE_MEETING_CLOCK
    case.ifsp_id = author_ifsp(
        api,
        case.referral_id,
        case.coordinator_id,
        meeting_date=TIMELINE_MEETING_DATE,
    )
    # PRD 3.3 only lets a plan in PENDING_CONSENT, ACTIVE, AMENDMENT_PENDING,
    # SUPERSEDED or CLOSED supply the stop date, so the plan has to carry its
    # first service line and leave DRAFT before the clock counts as stopped.
    case.line_id = add_service_line(api, case.ifsp_id)
    # PRD 2.7 recomputes the elapsed-day counts and the timeline verdict for
    # every non-terminal case on every clock set, which is what writes the
    # stopped-clock verdict onto the stored referral row.
    set_clock(api, TIMELINE_RECOMPUTE_CLOCK)
    case.clock = TIMELINE_RECOMPUTE_CLOCK
    return case


class TestTimelineGrossVersusNet:
    """The statutory clock reported both ways off one set of stored facts."""

    def test_compliance_read_reports_both_counts_and_grades_on_the_net_one(self, api):
        """
        The compliance read must publish both day counts and grade only on the
        net one.

        PRD 3.3: "`net_elapsed_days` is the gross count minus the excluded
        total, floored at zero so that it never goes negative. Both counts are
        reported, and the difference between them is the point of the design:
        the gross count is the raw wall-clock span the state reports federally,
        while the net count is the only figure that determines compliance."

        Design: Difficulty/dual_variant_calc/timeline_gross_vs_net_divergence
        """
        case = _build_divergent_timeline_case(api)

        response = api.get_timeline_compliance(case.referral_id, ADMIN_HEADERS)
        compliance = validate_success(response, 200)

        assert compliance["referral_id"] == case.referral_id
        assert_timeline(
            compliance,
            statutory_deadline_date="2026-04-16",
            stop_date=TIMELINE_MEETING_DATE,
            gross_elapsed_days=54,
            excluded_delay_days=12,
            net_elapsed_days=42,
            initial_timeline_status="MET",
        )
        # The two variants are computed from the same row and must differ by
        # exactly the documented unavailability.
        assert (
            compliance["gross_elapsed_days"] - compliance["net_elapsed_days"] == 12
        )
        assert compliance["gross_elapsed_days"] > STATUTORY_TIMELINE_DAYS
        assert compliance["net_elapsed_days"] <= STATUTORY_TIMELINE_DAYS

    def test_stored_case_row_carries_the_net_verdict_not_the_gross_one(self, api):
        """
        The stored verdict follows the net count, so a case 54 raw days past
        intake is still MET.

        PRD 3.3: "`initial_timeline_status` follows from the net count alone.
        When `net_elapsed_days` is at most 45, the status is `MET` if the stop
        date came from an initial plan's meeting date and `IN_PROGRESS` if the
        stop date is merely today's logical clock date."

        Design: Difficulty/dual_variant_calc/timeline_gross_vs_net_divergence
        """
        case = _build_divergent_timeline_case(api)

        referral = read_referral(api, case.referral_id)

        assert referral["gross_elapsed_days"] == 54
        assert referral["excluded_delay_days"] == 12
        assert referral["net_elapsed_days"] == 42
        assert referral["initial_timeline_status"] == "MET"
        assert referral["initial_ifsp_meeting_date"] == TIMELINE_MEETING_DATE
        assert referral["statutory_deadline_date"] == "2026-04-16"


# The divergent-fee case: household of four, declared 120,000 dollars against a
# verified 155,000 dollars, which crosses a tier boundary.
DECLARED_INCOME_CENTS = 12_000_000
VERIFIED_INCOME_CENTS = 15_500_000
POLICY_ID = "POL-4471"
HOUSEHOLD_SIZE = 4
FPL_THRESHOLD_CENTS = 3_245_000


def _build_consented_determination_case(api):
    """A consented case carrying one 52,000-cent-per-month speech line and a
    provisional determination with insurance consent and a policy on file."""
    case = build_active_services(api)
    case.cost_share_id = create_cost_share(
        api,
        case.referral_id,
        household_size=HOUSEHOLD_SIZE,
        declared_annual_gross_income_cents=DECLARED_INCOME_CENTS,
        insurance_use_consent=True,
        insurance_policy_id=POLICY_ID,
    )
    return case


class TestCostShareProvisionalVersusFinal:
    """The sliding scale run twice: once on declared income, once on verified."""

    def test_provisional_variant_withholds_the_insurance_offset(self, api):
        """
        A determination created with consent and a policy on file still carries
        no offset while it is provisional.

        PRD 3.8: "The provisional variant **never** applies the insurance
        offset, even when `insurance_use_consent` is true and a policy is on
        file: `insurance_offset_cents` stays at 0 and `final_monthly_fee_cents`
        stays null."

        Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_fee_divergence
        """
        case = _build_consented_determination_case(api)

        determination = read_cost_share(api, case.cost_share_id)

        assert determination["status"] == "PROVISIONAL"
        assert_cents(
            determination["fpl_threshold_cents"],
            FPL_THRESHOLD_CENTS,
            "fpl_threshold_cents",
        )
        assert_fpl_percent(determination["fpl_percent"], 369.8)
        assert determination["tier_code"] == "TIER_1"
        assert float(determination["coinsurance_rate"]) == pytest.approx(
            0.05, abs=0.001
        )
        assert_cents(determination["monthly_cap_cents"], 12_000, "monthly_cap_cents")
        # 4 sessions x 2 units x 6500 cents x 0.05 = 2600 cents.
        assert_cents(
            determination["assessed_monthly_fee_cents"],
            2_600,
            "assessed_monthly_fee_cents",
        )
        assert float(determination["effective_coinsurance_rate"]) == pytest.approx(
            0.05, abs=0.001
        )
        assert_cents(
            determination["insurance_offset_cents"], 0, "insurance_offset_cents"
        )
        assert determination["final_monthly_fee_cents"] is None
        assert determination["insurance_use_consent"] is True
        assert determination["insurance_policy_id"] == POLICY_ID

    def test_final_variant_crosses_a_tier_and_applies_the_offset(self, api):
        """
        Finalization re-runs the whole scale from the verified income and only
        then reduces the family's figure by the insurance offset.

        PRD 3.8: "The insurance offset is applied here and only here: when
        `insurance_use_consent` is true **and** an `insurance_policy_id` is on
        file, `insurance_offset_cents` is 60 percent of the capped monthly
        figure, rounded half up to whole cents; otherwise it is 0."

        Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_fee_divergence
        """
        case = _build_consented_determination_case(api)

        response = api.finalize_cost_share(
            case.cost_share_id,
            factories.finalize_cost_share_payload(
                verified_annual_gross_income_cents=VERIFIED_INCOME_CENTS,
                verification_date="2026-03-20",
            ),
            FISCAL_HEADERS,
        )
        determination = validate_success(response, 200)

        assert determination["status"] == "VERIFIED"
        assert_cents(
            determination["verified_annual_gross_income_cents"],
            VERIFIED_INCOME_CENTS,
            "verified_annual_gross_income_cents",
        )
        assert determination["verification_date"] == "2026-03-20"
        # 155,000 dollars against a 32,450-dollar threshold is 477.7 percent.
        assert_fpl_percent(determination["fpl_percent"], 477.7)
        assert determination["tier_code"] == "TIER_2"
        assert float(determination["coinsurance_rate"]) == pytest.approx(
            0.10, abs=0.001
        )
        assert_cents(determination["monthly_cap_cents"], 30_000, "monthly_cap_cents")
        assert float(determination["effective_coinsurance_rate"]) == pytest.approx(
            0.10, abs=0.001
        )
        # 52,000 cents of monthly service at 0.10 is 5200, offset 3120, final 2080.
        assert_cents(
            determination["insurance_offset_cents"], 3_120, "insurance_offset_cents"
        )
        assert_cents(
            determination["final_monthly_fee_cents"], 2_080, "final_monthly_fee_cents"
        )
        # The provisional figure is a separate stored variant and is untouched.
        assert_cents(
            determination["assessed_monthly_fee_cents"],
            2_600,
            "assessed_monthly_fee_cents",
        )
        assert (
            determination["final_monthly_fee_cents"]
            != determination["assessed_monthly_fee_cents"]
        )
        assert_ledger(determination, 0, 0, 0)
