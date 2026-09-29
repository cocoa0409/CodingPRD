"""Requests that fail two checks at once, where §2.8's ascending priority order decides which
single error the caller is allowed to see."""

from test_helpers import (
    ANALYST,
    ApiErrorId,
    make_partner_headers,
    read_account,
    read_allocation,
    read_partner,
    read_registration,
    seed_gold_with_overdue_audit,
    seed_partner_vs_partner_conflict,
    validate_error,
    validate_paginated,
)


class TestStateOutranksExclusivityOnSubmit:
    def test_a_held_registration_resubmitted_into_a_live_rival_window_reports_the_state_error(
        self, api
    ):
        """PRD §2.8: "When a single request would fail more than one check, exactly one error is
        returned, and which one is fully determined."
        PRD §2.8: "**State precondition.** The target row is in a state from which the requested
        transition is declared in §3, including the three loop caps: at most two completed revision
        rounds on a registration, at most two counter rounds on a mapping, and at most two proof
        rounds on a claim."

        Design: Difficulty/priority_pair_validation_conflict/state_transition_outranks_exclusivity_conflict_on_submit
        """
        seed = seed_partner_vs_partner_conflict()
        held = seed["counter_registration"]
        assert held["status"] == "CONFLICT_HELD"
        assert seed["subject_registration"]["status"] == "APPROVED"
        assert seed["subject_registration"]["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z"

        validate_error(
            api.submit_deal_registration(
                held["id"], make_partner_headers(seed["challenger"]["id"])
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

    def test_the_exclusivity_error_is_not_the_one_reported_and_nothing_is_written(self, api):
        """PRD §2.8: "**Exclusivity conflict.** No other approved registration holds a live
        exclusivity window on the same account-and-product-line pair, and the account's
        `coverage_state` is not `DIRECT_LOCKED` — otherwise `ERR_EXCLUSIVITY_CONFLICT` (409)."
        PRD §2.8: "Checks are evaluated in the ascending priority order below, and the first
        failing check wins."

        Design: Difficulty/priority_pair_validation_conflict/state_transition_outranks_exclusivity_conflict_on_submit
        """
        seed = seed_partner_vs_partner_conflict()
        held_id = seed["counter_registration"]["id"]
        submitted_at_before = seed["counter_registration"]["submitted_at"]

        body = api.submit_deal_registration(
            held_id, make_partner_headers(seed["challenger"]["id"])
        ).json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value

        refused = read_registration(held_id)
        assert refused["status"] == "CONFLICT_HELD"
        assert refused["revision_round"] == 0
        assert refused["submitted_at"] == submitted_at_before
        assert refused["submitted_at"] == "2026-04-01T00:00:00.000Z"

        assert read_registration(seed["subject_registration"]["id"])["status"] == "APPROVED"
        assert read_account(seed["account"]["id"])["coverage_state"] == "CHANNEL_PROTECTED"


class TestAuditRemediationOutranksFundAvailability:
    def test_an_overdue_audit_freezes_claim_filing_ahead_of_the_availability_check(self, api):
        """PRD §2.8: "**Audit remediation.** The partner has no `PerformanceReview` whose `status`
        is `FINDINGS_OPEN` and whose `remediation_due_at` is at or before the current logical
        instant — otherwise `ERR_AUDIT_REMEDIATION_OVERDUE` (409)."
        PRD §2.8: "Because program standing (13) and audit remediation (14) sit above every
        temporal and fiscal check, a frozen partner always sees the freeze rather than a downstream
        conflict."

        Design: Difficulty/priority_pair_validation_conflict/audit_remediation_overdue_outranks_mdf_insufficiency_on_claim_create
        """
        seed = seed_gold_with_overdue_audit()
        review = seed["findings_review"]
        assert review["status"] == "FINDINGS_OPEN"
        assert review["remediation_due_at"] == "2026-03-12T00:00:00.000Z"
        assert seed["allocation"]["available_cents"] == 273000

        validate_error(
            api.create_mdf_claim(
                {
                    "allocation_id": seed["allocation"]["id"],
                    "activity_type": "CONTENT_SYNDICATION",
                    "requested_cents": 500000,
                },
                make_partner_headers(seed["partner"]["id"]),
            ),
            ApiErrorId.ERR_AUDIT_REMEDIATION_OVERDUE.value,
            409,
        )

    def test_the_refused_claim_leaves_no_row_and_no_bucket_movement(self, api):
        """PRD §2.8: "**Fund availability.** `requested_cents` is at or below the fund period's
        `available_cents` — otherwise `ERR_MDF_ALLOCATION_INSUFFICIENT` (422), on claim creation."
        PRD §3.9: "While the deadline is unmet and the review stays `FINDINGS_OPEN`, that overdue
        finding freezes the partner out of registration submission, claim filing and mapping
        acceptance, as §2.8 sets out."

        Design: Difficulty/priority_pair_validation_conflict/audit_remediation_overdue_outranks_mdf_insufficiency_on_claim_create
        """
        seed = seed_gold_with_overdue_audit()
        allocation_id = seed["allocation"]["id"]
        partner_id = seed["partner"]["id"]

        response = api.create_mdf_claim(
            {
                "allocation_id": allocation_id,
                "activity_type": "CONTENT_SYNDICATION",
                "requested_cents": 500000,
            },
            make_partner_headers(partner_id),
        )
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_MDF_ALLOCATION_INSUFFICIENT.value
        )

        allocation = read_allocation(allocation_id)
        assert allocation["allocated_cents"] == 273000
        assert allocation["committed_cents"] == 0
        assert allocation["available_cents"] == 273000

        rows, _ = validate_paginated(api.list_allocation_mdf_claims(allocation_id, ANALYST))
        assert rows == []

        partner = read_partner(partner_id)
        assert partner["tier_status"] == "COMPLIANT"
        assert partner["standing_reason"] is None
