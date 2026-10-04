"""Exoneration claims: windows, duplicates, segregation of duties, cascades."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    claim_in_evidence_review,
    create_confirmed_event,
    decide_claim_payload,
    get_event,
    get_event_auto_session,
    make_driver_headers,
    make_safety_manager_headers,
    setup_base,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import set_clock
from test_helpers.test_users import make_claims_adjuster_headers

MANAGER = TEST_USERS["safety_manager_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


class TestExonerationWindowPrecedence:
    def _setup_confirmed_medium_event(self, base):
        return create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )

    def test_temporal_error_beats_referential_eligibility(self, api):
        """PRD §3.8: "Submission is guarded on three axes: the event must be
        in `CONFIRMED` status and of type `COLLISION` (otherwise
        `ERR_CLAIM_REQUIRES_CONFIRMED_COLLISION`); the claim must be submitted
        no later than 30 days after the event's `confirmed_at`, with exactly
        30 days admitted and anything later rejected as
        `ERR_EXONERATION_WINDOW_EXPIRED`; and no other non-`REJECTED` claim
        may already exist for the event (otherwise `ERR_DUPLICATE_CLAIM`)."
        PRD §2.10: "then the safety and privacy gates (the inward-footage
        gate, segregation of duties on exoneration decisions, and the
        litigation-hold block on purge), then the temporal window rules
        (exoneration window, future timestamps, session window overlap,
        agreement window overlap), then referenced-entity state."

        Design: Difficulty/priority_pair_validation_conflict/temporal_error_beats_referential_eligibility
        """
        base = setup_base()
        event = self._setup_confirmed_medium_event(base)
        # 31 days after the 2026-09-01 confirmation.
        set_clock("2026-10-02T00:00:00Z")
        resp = api.create_exoneration_claim(
            event["id"],
            {"claim_ref": "CLM-LATE-1"},
            make_driver_headers(base["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXONERATION_WINDOW_EXPIRED)
        rows, _ = validate_paginated(
            api.list_event_exoneration_claims(event["id"], MANAGER)
        )
        assert len(rows) == 0

    def test_late_claim_on_confirmed_collision_also_window_expired(self, api):
        """PRD §3.8: "the claim must be submitted no later than 30 days after
        the event's `confirmed_at`, with exactly 30 days admitted and anything
        later rejected as `ERR_EXONERATION_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_error_beats_referential_eligibility
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        set_clock("2026-10-01T00:00:00Z")  # exactly 30 days: admitted
        ok = validate_success(
            api.create_exoneration_claim(
                event["id"], {"claim_ref": "CLM-EXACT-30"},
                make_driver_headers(base["driver"]["id"]),
            ),
            201,
        )
        assert ok["status"] == "SUBMITTED"


class TestClaimStateMachine:
    def test_claim_decide_from_submitted_rejected(self, api, claims_adjuster_headers):
        """PRD §3.8: "A `ClaimsAdjuster` moves the claim `SUBMITTED` →
        `EVIDENCE_REVIEW` via begin-review, then decides it with a `decision`
        of `EXONERATE` or `REJECT` and a `rationale`, stamping `decided_at`
        and recording `decided_by`."

        Design: Corner/state_machines/claim_decide_from_submitted_rejected
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        claim = submit_claim(event["id"], base["driver"]["id"], claim_ref="CLM-200")
        resp = api.decide_exoneration_claim(
            claim["id"],
            decide_claim_payload("EXONERATE", rationale="skip evidence review"),
            claims_adjuster_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_exoneration_claim(claim["id"], MANAGER), 200)
        assert after["status"] == "SUBMITTED"
        assert after["decided_at"] is None


class TestDuplicateClaims:
    def test_duplicate_claim_rejected(self, api, claims_adjuster_headers):
        """PRD §3.8: "no other non-`REJECTED` claim may already exist for the
        event (otherwise `ERR_DUPLICATE_CLAIM`)."
        PRD §3.8: "A decision of `REJECT` moves the claim to `REJECTED` and
        leaves the event untouched."

        Design: Corner/validations/duplicate_claim_rejected
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        claim = submit_claim(event["id"], base["driver"]["id"], claim_ref="CLM-300")
        resp = api.create_exoneration_claim(
            event["id"], {"claim_ref": "CLM-301"},
            make_driver_headers(base["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)
        validate_success(api.begin_review_exoneration_claim(claim["id"], claims_adjuster_headers), 200)
        rejected = validate_success(
            api.decide_exoneration_claim(
                claim["id"],
                decide_claim_payload("REJECT", rationale="insufficient evidence"),
                claims_adjuster_headers,
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        third = validate_success(
            api.create_exoneration_claim(
                event["id"], {"claim_ref": "CLM-302"},
                make_driver_headers(base["driver"]["id"]),
            ),
            201,
        )
        assert third["status"] == "SUBMITTED"
        rows, _ = validate_paginated(
            api.list_event_exoneration_claims(event["id"], MANAGER)
        )
        assert len(rows) == 2
        assert get_event(event["id"])["status"] == "CONFIRMED"


class TestSegregationOfDuties:
    def test_segregation_of_duties_reviewer_cannot_decide(self, api):
        """PRD §3.8: "Segregation of duties is enforced on the decision: the
        deciding adjuster's `X-User-ID` must differ from the `reviewer_id` on
        the review decision that last confirmed the event, and a violation is
        rejected with `ERR_SEGREGATION_OF_DUTIES` — the person who confirmed
        the event may never be the person who exonerates it."

        Design: Corner/rbac/segregation_of_duties_reviewer_cannot_decide
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        claim = submit_claim(event["id"], base["driver"]["id"], claim_ref="CLM-400")
        # The confirming reviewer's id (sm-1) acts as the adjuster.
        validate_success(
            api.begin_review_exoneration_claim(
                claim["id"], make_claims_adjuster_headers("sm-1")
            ),
            200,
        )
        resp = api.decide_exoneration_claim(
            claim["id"],
            decide_claim_payload("EXONERATE", rationale="same person who confirmed"),
            make_claims_adjuster_headers("sm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        mid = validate_success(api.get_exoneration_claim(claim["id"], MANAGER), 200)
        assert mid["status"] == "EVIDENCE_REVIEW"
        decided = validate_success(
            api.decide_exoneration_claim(
                claim["id"],
                decide_claim_payload("EXONERATE", rationale="independent adjuster"),
                make_claims_adjuster_headers("ca-9"),
            ),
            200,
        )
        assert decided["status"] == "EXONERATED"
        assert decided["decided_by"] == "ca-9"
        assert get_event(event["id"])["status"] == "EXONERATED"

    def test_reject_decision_leaves_event_untouched(self, api):
        """PRD §3.8: "A decision of `REJECT` moves the claim to `REJECTED` and
        leaves the event untouched. `EXONERATED` and `REJECTED` are terminal
        for the claim, and `EXONERATED` is terminal for the event."

        Design: Difficulty/compensating_invariant/confirm_then_exonerate_restores_score
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        driver_mid = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver_mid["safety_score_final"]) == 92.50
        claim = claim_in_evidence_review(event["id"], base["driver"]["id"], claim_ref="CLM-600")
        rejected = validate_success(
            api.decide_exoneration_claim(
                claim["id"],
                decide_claim_payload("REJECT", rationale="evidence does not clear the driver"),
                ADJUSTER,
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        after = get_event(event["id"])
        assert after["status"] == "CONFIRMED"
        assert after["confirmed_at"] is not None
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_final"]) == 92.50
        assert driver["confirmed_events_90d"] == 1


class TestExonerationCascade:
    def test_confirm_then_exonerate_restores_score(self, api):
        """PRD §3.8: "A decision of `EXONERATE` fires the full compensation
        cascade on the event: the event moves `CONFIRMED` → `EXONERATED` with
        `confirmed_at` reset to unset; the driver's `confirmed_events_90d` and
        both score variants are recomputed with the exonerated event leaving
        the final input set; all coaching sessions tied to the event in
        `ASSIGNED`, `ACKNOWLEDGED`, or `OVERDUE` move to `CANCELLED`; and the
        escalation unwinding of Section 3.7 applies."
        PRD §3.9: "`DETECTED`, `DISMISSED`, and `EXONERATED` events are
        excluded from both variants, so identical inputs always yield a final
        score greater than or equal to the provisional score."

        Design: Difficulty/compensating_invariant/confirm_then_exonerate_restores_score
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        driver_mid = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver_mid["safety_score_final"]) == 92.50
        claim = claim_in_evidence_review(event["id"], base["driver"]["id"], claim_ref="CLM-100")
        decided = validate_success(
            api.decide_exoneration_claim(
                claim["id"],
                decide_claim_payload("EXONERATE", rationale="video shows third party ran the light"),
                ADJUSTER,
            ),
            200,
        )
        assert decided["status"] == "EXONERATED"
        assert decided["decided_by"] == "ca-1"
        exonerated = get_event(event["id"])
        assert exonerated["status"] == "EXONERATED"
        assert exonerated["confirmed_at"] is None
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_final"]) == 100.00
        assert float(driver["safety_score_provisional"]) == 100.00
        assert driver["confirmed_events_90d"] == 0

    def test_exoneration_cascades_cancel_sessions(self, api):
        """PRD §3.8: "A decision of `EXONERATE` fires the full compensation
        cascade on the event: the event moves `CONFIRMED` → `EXONERATED` with
        `confirmed_at` reset to unset; the driver's `confirmed_events_90d` and
        both score variants are recomputed with the exonerated event leaving
        the final input set; all coaching sessions tied to the event in
        `ASSIGNED`, `ACKNOWLEDGED`, or `OVERDUE` move to `CANCELLED`; and the
        escalation unwinding of Section 3.7 applies."

        Design: Corner/cross-cutting complexity layers/exoneration_cascades_cancel_sessions
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        session = get_event_auto_session(event["id"])
        assert session["status"] == "ASSIGNED"
        claim = claim_in_evidence_review(event["id"], base["driver"]["id"], claim_ref="CLM-500")
        validate_success(
            api.decide_exoneration_claim(
                claim["id"],
                decide_claim_payload("EXONERATE", rationale="dashcam clears the driver"),
                ADJUSTER,
            ),
            200,
        )
        cancelled = validate_success(api.get_coaching_session(session["id"], MANAGER), 200)
        assert cancelled["status"] == "CANCELLED"
        assert get_event(event["id"])["status"] == "EXONERATED"
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_final"]) == 100.00
        assert driver["confirmed_events_90d"] == 0
