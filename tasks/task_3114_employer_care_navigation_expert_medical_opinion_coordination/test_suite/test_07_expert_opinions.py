"""Expert medical opinion pipeline: revision cycle, segregation of duties,
withdrawal, attach gating, submit gates, and OCC on recommendations."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, setup_provider,
    setup_record_request, setup_authorization,
    setup_emo_member, setup_emo_case_compiling,
    setup_emo_case_ready_for_review, setup_emo_case_in_review,
)
from test_helpers.test_users import (
    make_member_headers,
    make_records_specialist_headers,
    make_expert_reviewer_headers,
    make_billing_advocate_headers,
)


class TestExpertOpinionRevisionCycle:
    def test_revision_cycle_recompiles_after_changes(self, api):
        """PRD §3.6: "From `IN_REVIEW`, that reviewer either sends the bundle
        back, moving the case to `CHANGES_REQUESTED` — from which a records
        specialist compiles it again, the revision loop cycling through
        `COMPILING` and `READY_FOR_REVIEW` — or writes the recommendation."
        PRD §3.6: "A successful submission stores the text, increments
        `recommendation_version` by one (superseding the prior draft),
        increments the case's `version`, and moves the case to
        `RECOMMENDATION_SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/expert_opinion_revision_cycle_recompiles_after_changes
        """
        set_clock()
        _, member = setup_emo_member()
        opinion, _, _ = setup_emo_case_in_review(
            member, specialist_id="rs-1", reviewer_id="er-2")

        changed = validate_success(api.request_changes(
            opinion["id"], make_expert_reviewer_headers("er-2")))
        assert changed["status"] == "CHANGES_REQUESTED"

        recompiled = validate_success(api.compile_expert_opinion(
            opinion["id"], make_records_specialist_headers("rs-1")))
        assert recompiled["status"] == "COMPILING"

        resubmitted = validate_success(api.submit_for_review(
            opinion["id"], make_records_specialist_headers("rs-1")))
        assert resubmitted["status"] == "READY_FOR_REVIEW"

        reclaimed = validate_success(api.claim_review(
            opinion["id"], make_expert_reviewer_headers("er-2")))
        assert reclaimed["status"] == "IN_REVIEW"

        submitted = validate_success(api.submit_recommendation(
            opinion["id"],
            {"recommendation_text": "Conservative management advised",
             "expected_opinion_version": reclaimed["version"]},
            make_expert_reviewer_headers("er-2")))
        assert submitted["status"] == "RECOMMENDATION_SUBMITTED"
        assert submitted["recommendation_version"] == 1

    def test_revision_cycle_returns_to_compiling_and_stamps_compiler(
            self, api):
        """PRD §3.6: "With at least one record attached, a records specialist
        compiles the bundle, moving the case to `COMPILING` and stamping
        `compiler_user_id`."

        Design: Difficulty/non_linear_state_machine/expert_opinion_revision_cycle_recompiles_after_changes
        """
        set_clock()
        _, member = setup_emo_member()
        opinion, _, _ = setup_emo_case_in_review(
            member, specialist_id="rs-1", reviewer_id="er-2")

        changed = validate_success(api.request_changes(
            opinion["id"], make_expert_reviewer_headers("er-2")))
        assert changed["status"] == "CHANGES_REQUESTED"

        recompiled = validate_success(api.compile_expert_opinion(
            opinion["id"], make_records_specialist_headers("rs-9")))
        assert recompiled["status"] == "COMPILING"
        assert recompiled["compiler_user_id"] == "rs-9"


class TestSegregationOfDuties:
    def test_emo_segregation_of_duties_compiler_cannot_review(self, api):
        """PRD §2.9: "Finally, the reviewer who claims a case must not be the
        same operator recorded as its compiler — a claim-review attempt where
        `X-User-ID` equals `compiler_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/state_machines/emo_segregation_of_duties_compiler_cannot_review
        """
        set_clock()
        _, member = setup_emo_member()
        opinion, _, _ = setup_emo_case_ready_for_review(
            member, specialist_id="rs-1")

        resp = api.claim_review(
            opinion["id"], make_expert_reviewer_headers("rs-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        current = validate_success(api.get_expert_opinion(
            opinion["id"], make_member_headers(member["id"])))
        assert current["status"] == "READY_FOR_REVIEW"


class TestWithdraw:
    def test_emo_withdraw_is_terminal_and_releases_assignments(self, api):
        """PRD §3.6: "At any point before delivery, the member — or a
        `PlatformAdmin` — may withdraw the case, moving it to terminal
        `WITHDRAWN` from any non-terminal state and releasing the compiler and
        reviewer assignments (both fields nulled)."
        PRD §2.6: "Sixth, state-machine legality: the target entity must be in
        a valid from-state (else `ERR_INVALID_STATE` or the more specific state
        error the workflow declares)."

        Design: Corner/state_machines/emo_withdraw_is_terminal_and_releases_assignments
        """
        set_clock()
        _, member = setup_emo_member()
        opinion = validate_success(api.create_expert_opinion(
            member["id"], {"condition_summary": "Raccoon City exposure"},
            make_member_headers(member["id"])), expected_status=201)

        withdrawn = validate_success(api.withdraw_expert_opinion(
            opinion["id"], make_member_headers(member["id"])))
        assert withdrawn["status"] == "WITHDRAWN"

        compile_resp = api.compile_expert_opinion(
            opinion["id"], make_records_specialist_headers("rs-1"))
        validate_error(compile_resp, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)

        deliver_resp = api.deliver_expert_opinion(
            opinion["id"], make_member_headers(member["id"]))
        validate_error(deliver_resp, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)


class TestAttachRecordsGate:
    def test_attach_record_not_received_rejected(self, api):
        """PRD §3.6: "The attached request must belong to the opinion's member,
        must be in `RECEIVED` status, and must not already be attached to
        another expert opinion case that is still live — that is, not in
        `DELIVERED` or `WITHDRAWN`; any violation is rejected with
        `ERR_RECORD_NOT_READY` (409). The first successful attachment moves the
        case from `INTAKE` to `RECORDS_COLLECTION`."

        Design: Corner/validations/attach_record_not_received_rejected
        """
        set_clock()
        _, member = setup_emo_member()
        provider = setup_provider(name="Attach Clinic")
        rr = setup_record_request(member, provider)
        emo = validate_success(api.create_expert_opinion(
            member["id"], {"condition_summary": "Attach test"},
            make_member_headers(member["id"])), expected_status=201)

        resp = api.attach_records(
            emo["id"], {"record_request_id": rr["id"]},
            make_records_specialist_headers("rs-1"))
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_READY,
                       expected_status=409)

        current = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert current["status"] == "INTAKE"


class TestSubmitForReviewGates:
    def test_submit_for_review_exactly_three_received_records(self, api):
        """PRD §3.6: "Submission is gated twice: the case must have
        `attached_received_count` of at least three (else
        `ERR_RECORDS_INSUFFICIENT`, 422)".

        Design: Difficulty/boundary_precision_check/submit_for_review_exactly_three_received_records
        """
        set_clock()
        _, member = setup_emo_member()
        # Case A: exactly 2 received records attached.
        emo_a, _, _ = setup_emo_case_compiling(
            member, num_received=2, num_providers=2,
            condition_summary="Case with 2 records")
        resp = api.submit_for_review(
            emo_a["id"], make_records_specialist_headers("rs-1"))
        validate_error(resp, ApiErrorId.ERR_RECORDS_INSUFFICIENT,
                       expected_status=422)
        current = validate_success(api.get_expert_opinion(
            emo_a["id"], make_member_headers(member["id"])))
        assert current["status"] == "COMPILING"

    def test_submit_for_review_with_two_records_leaves_case_compiling(
            self, api):
        """PRD §3.6: "Submission is gated twice: the case must have
        `attached_received_count` of at least three (else
        `ERR_RECORDS_INSUFFICIENT`, 422)".

        Design: Difficulty/boundary_precision_check/submit_for_review_exactly_three_received_records
        """
        set_clock()
        _, member = setup_emo_member()
        emo, requests, _ = setup_emo_case_compiling(
            member, num_received=2, num_providers=2,
            condition_summary="Two record case")
        assert emo["attached_received_count"] == 2

        resp = api.submit_for_review(
            emo["id"], make_records_specialist_headers("rs-1"))
        validate_error(resp, ApiErrorId.ERR_RECORDS_INSUFFICIENT,
                       expected_status=422)
        after = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert after["status"] == "COMPILING"
        assert after["attached_received_count"] == 2

    def test_submit_for_review_with_exactly_three_received_records_succeeds(
            self, api):
        """PRD §3.6: "Submission is gated twice: the case must have
        `attached_received_count` of at least three (else
        `ERR_RECORDS_INSUFFICIENT`, 422), and the member must hold a plan
        authorization whose `service_code` is `EXPERT_MEDICAL_OPINION` in
        `APPROVED` status (else `ERR_AUTHORIZATION_REQUIRED`, 409). Passing both
        moves the case to `READY_FOR_REVIEW`."

        Design: Corner/endpoints/submit_for_review_with_exactly_three_received_records_succeeds
        """
        set_clock()
        _, member = setup_emo_member()
        emo, _, _ = setup_emo_case_compiling(member, num_received=3)
        resp = api.submit_for_review(
            emo["id"], make_records_specialist_headers("rs-1"))
        data = validate_success(resp)
        assert data["status"] == "READY_FOR_REVIEW"
        assert data["attached_received_count"] == 3

    def test_submit_for_review_without_approved_authorization_rejected(
            self, api):
        """PRD §3.6: "and the member must hold a plan authorization whose
        `service_code` is `EXPERT_MEDICAL_OPINION` in `APPROVED` status (else
        `ERR_AUTHORIZATION_REQUIRED`, 409)."

        Design: Corner/validations/submit_for_review_without_approved_authorization_rejected
        """
        set_clock()
        _, member = setup_emo_member()
        # REQUESTED (never approved) authorization only.
        setup_authorization(member)
        emo, _, _ = setup_emo_case_compiling(
            member, num_received=3, with_approved_auth=False)

        resp = api.submit_for_review(
            emo["id"], make_records_specialist_headers("rs-1"))
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_REQUIRED,
                       expected_status=409)
        current = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert current["status"] == "COMPILING"


class TestRecommendationOcc:
    def test_occ_stale_opinion_version_on_submit_recommendation(self, api):
        """PRD §2.7: "a submission carrying an `expected_opinion_version` that
        does not match the case's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the reviewer from
        overwriting a draft superseded by one they have not observed."

        Design: Corner/validations/occ_stale_opinion_version_on_submit_recommendation
        """
        set_clock()
        _, member = setup_emo_member()
        opinion, _, _ = setup_emo_case_in_review(
            member, specialist_id="rs-1", reviewer_id="er-1")
        version_at_claim = opinion["version"]

        first = api.submit_recommendation(
            opinion["id"],
            {"recommendation_text": "Draft one",
             "expected_opinion_version": version_at_claim},
            make_expert_reviewer_headers("er-1"))
        first_data = validate_success(first)
        assert first_data["recommendation_version"] == 1

        stale = api.submit_recommendation(
            opinion["id"],
            {"recommendation_text": "Draft two",
             "expected_opinion_version": version_at_claim},
            make_expert_reviewer_headers("er-1"))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION,
                       expected_status=412)

        current = validate_success(api.get_expert_opinion(
            opinion["id"], make_expert_reviewer_headers("er-1")))
        assert current["recommendation_text"] == "Draft one"


class TestCrossRoleDenial:
    def test_billing_advocate_cannot_submit_recommendation(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
        PRD §4: "POST `/care/expert-opinions/{id}/submit-recommendation` ...
        ExpertReviewer".

        Design: Corner/rbac/billing_advocate_cannot_submit_recommendation
        """
        set_clock()
        _, member = setup_emo_member()
        opinion, _, _ = setup_emo_case_in_review(
            member, specialist_id="rs-1", reviewer_id="er-1")

        resp = api.submit_recommendation(
            opinion["id"],
            {"recommendation_text": "Fraudulent attempt",
             "expected_opinion_version": opinion["version"]},
            make_billing_advocate_headers("ba-9"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)

        current = validate_success(api.get_expert_opinion(
            opinion["id"], make_member_headers(member["id"])))
        assert current["status"] == "IN_REVIEW"
        assert current["recommendation_version"] == 0
