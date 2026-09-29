"""The four complaint buckets partition the partner's complaints across a
cyclic escalate/reassign walk, and only a withdrawal lowers the rate."""
from test_helpers import (
    assign_root_cause,
    assert_complaint_bucket_partition,
    dispose_complaint,
    file_complaint,
    get_success_data,
    api_client,
    read_partner,
    seed_reserve_balance,
    setup_contracted_partner,
    PO,
)

ACCOUNT_COUNT = 160


def _meridian_with_two_complaints():
    ctx = setup_contracted_partner(
        partner_overrides={
            "legal_name": "Meridian Wallet Inc",
            "business_model": "DEPOSIT_WALLET",
            "funding_stage": "SERIES_A",
            "months_runway": 20,
            "disclosed_complaints_per_10k": 10.00,
            "end_user_account_count": ACCOUNT_COUNT,
        },
        agreement_overrides={"dispute_owner": "BANK", "reserve_requirement_bps": 500},
    )
    partner_id = ctx["partner"]["id"]
    # Fund the reserve to its requirement so the posture ladder is driven by the
    # complaint rate alone and not by a residual shortfall.
    seed_reserve_balance(partner_id, ctx["reserve"], 312_500)
    assert read_partner(partner_id)["reserve_shortfall_cents"] == 0

    ctx["c1"] = file_complaint(
        partner_id,
        channel="BANK_CALL_CENTER",
        category="FEES",
        severity="MEDIUM",
        received_at="2026-07-10T00:00:00Z",
        narrative="monthly fee charged twice",
    )
    ctx["c2"] = file_complaint(
        partner_id,
        channel="PARTNER_APP",
        category="SERVICING",
        severity="LOW",
        received_at="2026-07-11T00:00:00Z",
        narrative="no response to support ticket",
    )
    return ctx


class TestComplaintBucketPartition:
    def test_the_escalate_then_reassign_round_trip_restores_both_buckets_exactly(self):
        """Every complaint status change moves exactly one slot from one bucket to another and
        never creates or destroys a slot. In particular, escalating a complaint and then bringing it
        back by assigning a root cause leaves the sum unchanged and returns `open_complaint_count`
        and `escalated_complaint_count` to their pre-escalation values, while the complaint's own
        `escalation_count` records that the round trip happened.

        Design: Difficulty/compensating_invariant/escalate_then_reassign_root_cause_restores_the_complaint_bucket_partition
        """
        ctx = _meridian_with_two_complaints()
        partner_id = ctx["partner"]["id"]
        c1_id = ctx["c1"]["id"]

        assert ctx["c1"]["handling_owner"] == "BANK", (
            "the handling owner is frozen from the executed agreement's dispute owner"
        )
        assert ctx["c1"]["escalation_count"] == 0

        step0 = read_partner(partner_id)
        assert step0["total_complaint_count"] == 2
        assert step0["open_complaint_count"] == 2
        assert step0["escalated_complaint_count"] == 0
        assert step0["resolved_complaint_count"] == 0
        assert step0["withdrawn_complaint_count"] == 0
        assert_complaint_bucket_partition(step0, expected_total=2)
        assert step0["complaint_rate_bps"] == 125, step0["complaint_rate_bps"]
        assert step0["oversight_posture"] == "HEIGHTENED"

        assigned = assign_root_cause(
            c1_id,
            root_cause_code="FEE_CONFIG_ERROR",
            investigation_note="duplicate fee posting job double-charged the monthly maintenance fee",
        )
        assert assigned["status"] == "ROOT_CAUSE_ASSIGNED"
        step1 = read_partner(partner_id)
        assert step1["open_complaint_count"] == 2, (
            "RECEIVED and ROOT_CAUSE_ASSIGNED are both open buckets"
        )
        assert step1["escalated_complaint_count"] == 0
        assert_complaint_bucket_partition(step1, expected_total=2)

        escalated = dispose_complaint(
            c1_id, "ESCALATED", resolution_note="referred to the risk committee"
        )
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_count"] == 1
        step2 = read_partner(partner_id)
        assert step2["open_complaint_count"] == 1
        assert step2["escalated_complaint_count"] == 1
        assert_complaint_bucket_partition(step2, expected_total=2)

        reassigned = assign_root_cause(
            c1_id,
            root_cause_code="FEE_CONFIG_ERROR",
            investigation_note="re-scoped to the same fee configuration defect after committee review",
        )
        assert reassigned["status"] == "ROOT_CAUSE_ASSIGNED"
        assert reassigned["escalation_count"] == 1, (
            "the lifetime escalation count ratchets and never decrements"
        )
        assert reassigned["root_cause_code"] == "FEE_CONFIG_ERROR"
        step3 = read_partner(partner_id)
        assert step3["open_complaint_count"] == 2, "the slot returned to the bucket it left"
        assert step3["escalated_complaint_count"] == 0
        assert_complaint_bucket_partition(step3, expected_total=2)
        assert step3["complaint_rate_bps"] == 125, "the round trip never leaves the numerator"
        assert read_partner(partner_id)["status"] == "CONTRACTED"

    def test_only_the_withdrawal_leaves_the_numerator_and_lowers_the_rate(self):
        """A `WITHDRAWN` outcome is legal only from `RECEIVED`: it stamps `resolved_at`, decrements
        `open_complaint_count` by 1 and increments `withdrawn_complaint_count` by 1 — and because
        withdrawn complaints leave the numerator of the complaint rate entirely, a withdrawal is the
        one disposition that can lower `complaint_rate_bps`.

        Design: Difficulty/compensating_invariant/escalate_then_reassign_root_cause_restores_the_complaint_bucket_partition
        """
        ctx = _meridian_with_two_complaints()
        partner_id = ctx["partner"]["id"]
        c1_id = ctx["c1"]["id"]
        c2_id = ctx["c2"]["id"]

        assign_root_cause(c1_id, root_cause_code="FEE_CONFIG_ERROR")
        dispose_complaint(c1_id, "ESCALATED", resolution_note="referred to the risk committee")
        assign_root_cause(c1_id, root_cause_code="FEE_CONFIG_ERROR")
        resolved = dispose_complaint(
            c1_id,
            "RESOLVED",
            resolution_note="fee refunded and the posting job patched",
            redress_cents=1200,
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["redress_cents"] == 1200
        assert resolved["resolved_at"] is not None

        step4 = read_partner(partner_id)
        assert step4["open_complaint_count"] == 1
        assert step4["resolved_complaint_count"] == 1
        assert_complaint_bucket_partition(step4, expected_total=2)
        assert step4["complaint_rate_bps"] == 125, (
            f"a RESOLVED complaint stays in the numerator, got {step4['complaint_rate_bps']}"
        )
        assert step4["oversight_posture"] == "HEIGHTENED"

        withdrawn = dispose_complaint(
            c2_id, "WITHDRAWN", resolution_note="end user withdrew the complaint"
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["resolved_at"] is not None
        assert withdrawn["escalation_count"] == 0

        step5 = read_partner(partner_id)
        assert step5["open_complaint_count"] == 0
        assert step5["escalated_complaint_count"] == 0
        assert step5["resolved_complaint_count"] == 1
        assert step5["withdrawn_complaint_count"] == 1
        assert step5["total_complaint_count"] == 2, "no slot was created or destroyed"
        assert_complaint_bucket_partition(step5, expected_total=2)
        assert step5["complaint_rate_bps"] == 63, (
            f"1 * 10000 / 160 is 62.5 and rounds half up to 63, got {step5['complaint_rate_bps']}"
        )
        assert step5["oversight_posture"] == "OPEN", (
            "63 basis points is below the 120 heighten threshold"
        )
        assert step5["status"] == "CONTRACTED"
        listing = get_success_data(
            api_client.list_complaints(PO, {"partner_id": partner_id, "status": "WITHDRAWN"})
        )
        assert [row["id"] for row in listing] == [c2_id]
