"""Declared initial states, the partner cascade the review drives, and the
wrong-state and terminal-state refusals around the diligence machine."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_complaint_payload,
    create_diligence_review_payload,
    create_partner,
    open_cycle,
    read_partner,
    validate_error,
    validate_success,
    CO,
    PO,
)

NORTHBEAM = {
    "legal_name": "Northbeam Pay Inc",
    "business_model": "CARD_ISSUING",
    "funding_stage": "SERIES_B_PLUS",
    "months_runway": 24,
    "disclosed_complaints_per_10k": 12.50,
    "end_user_account_count": 100000,
}
SCORES = {
    "business_model_score": 80,
    "funding_score": 80,
    "compliance_capability_score": 90,
    "complaint_history_score": 85,
}


def _draft_review(partner):
    return validate_success(
        api_client.create_diligence_review(
            create_diligence_review_payload(
                partner["id"], partner["version"], review_type="INITIAL", **SCORES
            ),
            PO,
        ),
        201,
    )


class TestInitialStates:
    def test_each_machine_lands_on_its_own_declared_initial_state(self):
        """The complaint is stored in `RECEIVED` with `root_cause_code` null, `escalation_count` at
        0, `redress_cents` at 0, and `resolved_at` null. The file is stored with a `status` of
        `DRAFT`, a `revision_round` of 0, a `composite_score` of 0.0, a `tier` of `UNRATED`, an empty
        `requested_info_items` array, and both `submitted_by_user_id` and `decided_by_user_id` null.

        Design: Corner/state_machines/every_state_machine_starts_at_its_declared_initial_state
        """
        cycle = open_cycle("2026-08")
        assert cycle["status"] == "OPEN"

        partner = create_partner(**NORTHBEAM)
        assert partner["status"] == "PROSPECT"
        assert partner["oversight_posture"] == "OPEN"
        assert partner["capability_tier"] == "UNRATED"
        assert partner["version"] == 1

        review = _draft_review(partner)
        assert review["status"] == "DRAFT"
        assert review["revision_round"] == 0
        assert float(review["composite_score"]) == 0.0
        assert review["tier"] == "UNRATED"
        assert review["requested_info_items"] == []
        assert review["submitted_by_user_id"] is None
        assert review["decided_by_user_id"] is None

        complaint = validate_success(
            api_client.create_complaint(
                create_complaint_payload(
                    partner["id"],
                    channel="CFPB_PORTAL",
                    category="UNAUTHORIZED_TRANSACTION",
                    severity="HIGH",
                    received_at="2026-08-01T00:00:00Z",
                    narrative="Cardholder reports three unauthorized debits totalling 240.00 USD.",
                    is_reg_e_dispute=True,
                ),
                CO,
            ),
            201,
        )
        assert complaint["status"] == "RECEIVED"
        assert complaint["root_cause_code"] is None
        assert complaint["escalation_count"] == 0
        assert complaint["redress_cents"] == 0
        assert complaint["resolved_at"] is None

        alert = validate_success(
            api_client.create_alert(
                {
                    "partner_id": partner["id"],
                    "alert_type": "SANCTIONS_HIT",
                    "triggered_at": "2026-08-01T00:00:00Z",
                    "transaction_volume_cents": 250_000,
                    "detection_note": "Beneficiary name matched an OFAC SDN entry at 92 percent confidence.",
                },
                CO,
            ),
            201,
        )
        assert alert["disposition"] == "OPEN"


class TestDiligenceEdges:
    def test_submitting_the_review_is_what_drags_the_partner_into_diligence(self):
        """It also drags the partner along: a partner in `PROSPECT` advances
        `PROSPECT → IN_DILIGENCE`, and a partner in `DILIGENCE_PASSED` advances
        `DILIGENCE_PASSED → IN_DILIGENCE`, in each case incrementing the partner's `version` by 1 and
        refreshing its `updated_at`.

        Design: Corner/state_machines/diligence_submit_advances_the_review_and_cascades_the_partner_into_in_diligence
        """
        partner = create_partner(**NORTHBEAM)
        review = _draft_review(partner)
        assert read_partner(partner["id"])["version"] == 2, "the review create bumped the partner"

        submitted = validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Initial underwrite package complete."}, PO
            ),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_round"] == 1
        assert submitted["submitted_by_user_id"] == PO["X-User-ID"]

        after = read_partner(partner["id"])
        assert after["status"] == "IN_DILIGENCE"
        assert after["version"] == 3, f"1 at create, 2 from the review create, 3 from submit: {after['version']}"
        assert after["capability_tier"] == "UNRATED", "the tier is written only by a PASSED decision"

    def test_the_two_diligence_actions_report_their_own_wrong_state_error(self):
        """A decision may only be taken on a file in `SUBMITTED`, else `ERR_REVIEW_NOT_SUBMITTED`.
        Submission requires the file to be in `DRAFT` and the owning partner's `status` to be
        `PROSPECT` or `DILIGENCE_PASSED`; a file in the wrong state reports
        `ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED`.

        Design: Corner/state_machines/deciding_a_draft_review_and_submitting_a_passed_review_both_return_their_own_wrong_state_error
        """
        partner = create_partner(**NORTHBEAM)
        review = _draft_review(partner)

        validate_error(
            api_client.decide_diligence_review(
                review["id"],
                {"outcome": "PASSED", "decision_note": "Attempting to decide a review that was never submitted."},
                CO,
            ),
            ApiErrorId.ERR_REVIEW_NOT_SUBMITTED,
            409,
        )

        validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Initial underwrite package complete."}, PO
            ),
            200,
        )
        passed = validate_success(
            api_client.decide_diligence_review(
                review["id"], {"outcome": "PASSED", "decision_note": "Composite 84.5, TIER_2."}, CO
            ),
            200,
        )
        assert passed["status"] == "PASSED"

        validate_error(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Attempting to resubmit a terminal review."}, PO
            ),
            ApiErrorId.ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED,
            409,
        )

        final = validate_success(api_client.get_diligence_review(review["id"], PO), 200)
        assert final["status"] == "PASSED", "neither rejected call mutated the row"
        assert final["revision_round"] == 1
        assert read_partner(partner["id"])["status"] == "DILIGENCE_PASSED"

    def test_a_replayed_submit_is_refused_rather_than_silently_reapplied(self):
        """Submitting the file moves it `DRAFT → SUBMITTED`, optionally carrying a
        `submission_note`. It sets `revision_round` to 1, records the acting `X-User-ID` as
        `submitted_by_user_id`, and recomputes `effective_complaint_history_score`, `composite_score`
        and `tier`.

        Design: Corner/state_machines/submitting_the_same_diligence_review_twice_fails_on_the_second_attempt
        """
        partner = create_partner(**NORTHBEAM)
        review = _draft_review(partner)
        validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Initial underwrite package complete."}, PO
            ),
            200,
        )

        validate_error(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Duplicate submit from a retried client."}, PO
            ),
            ApiErrorId.ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED,
            409,
        )
        assert read_partner(partner["id"])["version"] == 3, "the replay bumped nothing"
        replayed = validate_success(api_client.get_diligence_review(review["id"], PO), 200)
        assert replayed["revision_round"] == 1, "not 2 — the action endpoint is not idempotent"

    def test_a_failed_partner_is_terminal_for_every_child_collection(self):
        """`DILIGENCE_FAILED` is terminal for the partner: no further diligence file, program
        agreement, marketing review, settlement batch, ledger entry, complaint, monitoring alert or
        wind-down plan may ever be created for it, and every such attempt is refused with
        `ERR_PARTNER_TERMINAL`.

        Design: Corner/state_machines/a_diligence_failed_partner_is_terminal_and_refuses_every_downstream_create
        """
        partner = create_partner(**NORTHBEAM)
        review = _draft_review(partner)
        validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Initial underwrite package complete."}, PO
            ),
            200,
        )
        failed = validate_success(
            api_client.decide_diligence_review(
                review["id"],
                {"outcome": "FAILED", "decision_note": "Board declined the program on concentration grounds."},
                CO,
            ),
            200,
        )
        assert failed["status"] == "FAILED"

        after = read_partner(partner["id"])
        assert after["status"] == "DILIGENCE_FAILED"
        assert after["capability_tier"] == "UNRATED"
        assert float(after["latest_composite_score"]) == 84.5, (
            "the failing composite is still copied onto the record"
        )

        validate_error(
            api_client.create_diligence_review(
                create_diligence_review_payload(
                    partner["id"],
                    after["version"],
                    review_type="RENEWAL",
                    business_model_score=90,
                    funding_score=90,
                    compliance_capability_score=90,
                    complaint_history_score=90,
                ),
                PO,
            ),
            ApiErrorId.ERR_PARTNER_TERMINAL,
            409,
        )
        validate_error(
            api_client.create_complaint(
                create_complaint_payload(
                    partner["id"],
                    channel="EMAIL",
                    category="FEES",
                    severity="LOW",
                    received_at="2026-08-01T00:00:00Z",
                    narrative="Consumer disputes a 5.00 USD monthly maintenance fee.",
                ),
                CO,
            ),
            ApiErrorId.ERR_PARTNER_TERMINAL,
            409,
        )
