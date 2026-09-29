"""Approved disclosure runs on one channel need a gap strictly greater than three days."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_same_instant,
    decide_marketing_review,
    file_marketing_review,
    get_success_data,
    make_fintech_partner_headers,
    resubmit_marketing_review_payload,
    setup_live_partner,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CO, PO

INCUMBENT_FROM = "2026-09-01T00:00:00Z"
INCUMBENT_UNTIL = "2026-09-10T00:00:00Z"
CANDIDATE_FROM = "2026-08-20T00:00:00Z"
EXACTLY_THREE_DAYS_END = "2026-08-29T00:00:00Z"
CLEARING_END = "2026-08-28T23:59:59.999Z"
DISCLOSURE_ELEMENTS = ["BANK_NAME", "FEE_SCHEDULE", "DISPUTE_RIGHTS"]


def _partner_with_an_approved_disclosure():
    ctx = setup_live_partner(
        partner_overrides={
            "legal_name": "Solstice Cards Inc",
            "business_model": "CARD_ISSUING",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 2.00,
            "end_user_account_count": 4000,
        },
        agreement_overrides={"reserve_requirement_bps": 500},
        fbo_balance_cents=5_000_000,
        reserve_balance_cents=312_500,
    )
    incumbent = file_marketing_review(
        ctx["partner"]["id"],
        ctx["agreement"]["id"],
        material_type="DISCLOSURE",
        placement_channel="PARTNER_SITE",
        disclosure_elements=DISCLOSURE_ELEMENTS,
        apr_disclosed=False,
        fdic_signage_correct=True,
        effective_from=INCUMBENT_FROM,
        effective_until=INCUMBENT_UNTIL,
    )
    assert incumbent["status"] == "SUBMITTED"
    assert incumbent["risk_flags"] == [], (
        "a card issuer with dispute rights present raises no flag that could mask the buffer rule"
    )
    ctx["incumbent"] = decide_marketing_review(
        incumbent["id"], "APPROVE", decision_note="incumbent disclosure"
    )
    assert ctx["incumbent"]["status"] == "APPROVED"
    return ctx


def _candidate(ctx, placement_channel, effective_until):
    return file_marketing_review(
        ctx["partner"]["id"],
        ctx["agreement"]["id"],
        material_type="DISCLOSURE",
        placement_channel=placement_channel,
        disclosure_elements=DISCLOSURE_ELEMENTS,
        apr_disclosed=False,
        fdic_signage_correct=True,
        effective_from=CANDIDATE_FROM,
        effective_until=effective_until,
    )


class TestDisclosureCoolingBuffer:
    def test_a_gap_of_exactly_three_days_conflicts_and_a_resubmission_clears_it(self):
        """Concretely, a conflict exists when the new `effective_from` is at or before the existing
        `effective_until` plus three days *and* the existing `effective_from` is at or before the new
        `effective_until` plus three days; a conflict is refused with
        `ERR_DISCLOSURE_WINDOW_CONFLICT`. Unlike the settlement windows of §3.5, touching endpoints
        conflict here, and so does a gap of exactly three days — only a gap strictly greater than
        three days clears.

        Design: Difficulty/resource_temporal_overlap/approved_disclosure_windows_need_a_gap_strictly_greater_than_three_days
        """
        ctx = _partner_with_an_approved_disclosure()
        partner_id = ctx["partner"]["id"]
        candidate = _candidate(ctx, "PARTNER_SITE", EXACTLY_THREE_DAYS_END)

        validate_error(
            api_client.decide_marketing_review(
                candidate["id"],
                {"decision": "APPROVE", "decision_note": "attempt at exactly three days"},
                CO,
            ),
            ApiErrorId.ERR_DISCLOSURE_WINDOW_CONFLICT,
            409,
        )

        changes = decide_marketing_review(
            candidate["id"],
            "CHANGES_REQUESTED",
            change_requests=["PULL_EFFECTIVE_UNTIL_OUT_OF_THE_COOLING_BUFFER"],
            decision_note="the window ends inside the three-day buffer ahead of September",
        )
        assert changes["status"] == "CHANGES_REQUESTED"

        resubmitted = validate_success(
            api_client.resubmit_marketing_review(
                candidate["id"],
                resubmit_marketing_review_payload(
                    disclosure_elements=DISCLOSURE_ELEMENTS,
                    apr_disclosed=False,
                    fdic_signage_correct=True,
                    effective_from=CANDIDATE_FROM,
                    effective_until=CLEARING_END,
                ),
                make_fintech_partner_headers(partner_id),
            )
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["review_round"] == 2
        assert resubmitted["change_requests"] == []
        assert_same_instant(resubmitted["effective_until"], CLEARING_END, "effective_until")
        assert_same_instant(resubmitted["effective_from"], CANDIDATE_FROM, "effective_from")

        approved = decide_marketing_review(
            candidate["id"], "APPROVE", decision_note="gap now exceeds three days"
        )
        assert approved["status"] == "APPROVED"
        assert ctx["incumbent"]["review_round"] == 1

    def test_the_same_window_is_free_on_a_different_placement_channel(self):
        """The cooling buffer prevents two approved runs of the same material type on the same
        channel from crowding each other. For a given combination of `partner_id`, `material_type`
        and `placement_channel`, the closed interval running from the new filing's `effective_from`
        through its `effective_until` must be separated from the closed interval of every
        already-`APPROVED` filing on that same combination by **more than three days on both sides**.

        Design: Difficulty/resource_temporal_overlap/approved_disclosure_windows_need_a_gap_strictly_greater_than_three_days
        """
        ctx = _partner_with_an_approved_disclosure()
        partner_id = ctx["partner"]["id"]

        same_channel = _candidate(ctx, "PARTNER_SITE", EXACTLY_THREE_DAYS_END)
        validate_error(
            api_client.decide_marketing_review(
                same_channel["id"], {"decision": "APPROVE"}, CO
            ),
            ApiErrorId.ERR_DISCLOSURE_WINDOW_CONFLICT,
            409,
        )

        other_channel = file_marketing_review(
            partner_id,
            ctx["agreement"]["id"],
            material_type="DISCLOSURE",
            placement_channel="SEARCH",
            disclosure_elements=DISCLOSURE_ELEMENTS,
            apr_disclosed=False,
            fdic_signage_correct=True,
            effective_from=INCUMBENT_FROM,
            effective_until=INCUMBENT_UNTIL,
        )
        approved = decide_marketing_review(
            other_channel["id"], "APPROVE", decision_note="different placement channel"
        )
        assert approved["status"] == "APPROVED", (
            "a byte-identical window is free because the resource key includes the channel"
        )
        assert approved["review_round"] == 1

        rows = get_success_data(
            api_client.list_marketing_reviews(
                PO, {"partner_id": partner_id, "status": "APPROVED", "limit": 100}
            )
        )
        assert len(rows) == 2, [r["placement_channel"] for r in rows]
