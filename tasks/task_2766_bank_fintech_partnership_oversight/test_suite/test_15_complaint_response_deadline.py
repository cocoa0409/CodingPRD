"""One intake instant, three deadlines: calendar channels do straight instant
arithmetic while business channels normalise to a midnight anchor."""
from test_helpers import (
    assert_complaint_bucket_partition,
    assert_same_instant,
    file_complaint,
    read_partner,
    setup_contracted_partner,
)

SATURDAY_INTAKE = "2026-07-04T15:00:00Z"
FOLLOWING_MONDAY_INTAKE = "2026-07-06T09:00:00Z"


def _lumen_contracted():
    return setup_contracted_partner(
        partner_overrides={
            "legal_name": "Lumen Lending Inc",
            "business_model": "LENDING",
            "funding_stage": "SEED",
            "months_runway": 14,
            "disclosed_complaints_per_10k": 30.00,
            "end_user_account_count": 160,
        },
        agreement_overrides={
            "kyc_owner": "SHARED",
            "dispute_owner": "PARTNER",
            "marketing_owner": "BANK",
            "oversight_rights_level": "STANDARD",
            "audit_access_notice_days": 20,
            "termination_triggers": ["COMPLAINT_RATE", "VOLUNTARY"],
            "monthly_growth_cap_pct": 25.00,
            "concentration_cap_pct": 60.00,
            "max_end_user_balance_cents": 500_000_000,
            "reserve_requirement_bps": 500,
        },
    )


class TestComplaintResponseDeadline:
    def test_a_calendar_channel_and_a_business_channel_diverge_from_one_instant(self):
        """Four channels count **calendar** days: `CFPB_PORTAL` allows 15 days, while
        `BANK_CALL_CENTER`, `PARTNER_APP` and `EMAIL` each allow 30 days. For these,
        `response_due_at` is simply `received_at` advanced by that many days as straight instant
        arithmetic — weekends are consumed like any other day, and the time of day of `received_at`
        is preserved exactly.

        Design: Difficulty/dual_variant_calc/complaint_sla_calendar_versus_business_basis_from_identical_intake_instant
        """
        ctx = _lumen_contracted()
        partner_id = ctx["partner"]["id"]

        cfpb = file_complaint(
            partner_id,
            channel="CFPB_PORTAL",
            category="FEES",
            severity="HIGH",
            received_at=SATURDAY_INTAKE,
            narrative="APR not disclosed at origination",
        )
        assert_same_instant(
            cfpb["response_due_at"], "2026-07-19T15:00:00.000Z", "CFPB_PORTAL response_due_at"
        )
        assert cfpb["status"] == "RECEIVED"
        assert cfpb["handling_owner"] == "PARTNER", (
            "the handling owner is frozen from the executed agreement's dispute owner"
        )
        assert cfpb["root_cause_code"] is None
        assert cfpb["escalation_count"] == 0
        assert cfpb["redress_cents"] == 0
        assert cfpb["resolved_at"] is None

        social = file_complaint(
            partner_id,
            channel="SOCIAL",
            category="SERVICING",
            severity="LOW",
            received_at=SATURDAY_INTAKE,
            narrative="public post about payoff delay",
        )
        assert_same_instant(
            social["response_due_at"], "2026-07-13T23:59:59.999Z", "SOCIAL response_due_at"
        )
        assert social["response_due_at"] != cfpb["response_due_at"], (
            "the same intake instant on a business channel must not reuse the calendar deadline"
        )
        assert social["handling_owner"] == "PARTNER"

    def test_the_midnight_anchor_collapses_a_saturday_and_the_following_monday(self):
        """From that anchor the system steps forward one day at a time, counting only Mondays
        through Fridays and never counting the anchor day itself, until the required number of
        business days has been consumed. The resulting date is pinned to `23:59:59.999Z`. A visible
        consequence of the midnight anchor is that a Saturday intake and the following Monday intake
        on the same channel produce **the same** due date.

        Design: Difficulty/dual_variant_calc/complaint_sla_calendar_versus_business_basis_from_identical_intake_instant
        """
        ctx = _lumen_contracted()
        partner_id = ctx["partner"]["id"]

        file_complaint(
            partner_id,
            channel="CFPB_PORTAL",
            category="FEES",
            severity="HIGH",
            received_at=SATURDAY_INTAKE,
            narrative="APR not disclosed at origination",
        )
        saturday_ag = file_complaint(
            partner_id,
            channel="STATE_AG",
            category="DISCLOSURE",
            severity="HIGH",
            received_at=SATURDAY_INTAKE,
            narrative="state attorney general inquiry",
        )
        file_complaint(
            partner_id,
            channel="SOCIAL",
            category="SERVICING",
            severity="LOW",
            received_at=SATURDAY_INTAKE,
            narrative="public post about payoff delay",
        )
        monday_ag = file_complaint(
            partner_id,
            channel="STATE_AG",
            category="CREDIT_REPORTING",
            severity="MEDIUM",
            received_at=FOLLOWING_MONDAY_INTAKE,
            narrative="furnishing dispute",
        )

        assert_same_instant(
            saturday_ag["response_due_at"],
            "2026-07-20T23:59:59.999Z",
            "Saturday STATE_AG response_due_at",
        )
        assert_same_instant(
            monday_ag["response_due_at"],
            "2026-07-20T23:59:59.999Z",
            "Monday STATE_AG response_due_at",
        )
        assert_same_instant(
            monday_ag["response_due_at"],
            saturday_ag["response_due_at"],
            "the two STATE_AG deadlines",
        )

        partner = read_partner(partner_id)
        assert partner["total_complaint_count"] == 4
        assert partner["open_complaint_count"] == 4
        assert_complaint_bucket_partition(partner, expected_total=4)
        assert partner["complaint_rate_bps"] == 250, (
            f"4 * 10000 / 160 is exactly 250 basis points, got {partner['complaint_rate_bps']}"
        )
        assert partner["oversight_posture"] == "RESTRICTED", (
            "a complaint rate of exactly 250 basis points is an inclusive RESTRICTED threshold"
        )
