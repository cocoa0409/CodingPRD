"""Enrollments and the fraud-risk pipeline: risk routing thresholds, MOD-7
checksum, watchlist, velocity counter, review branch, document uniqueness,
age floor, and enrollment terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    create_enrollment_center,
    create_airport,
    enroll_member_at_center,
    make_member_headers,
    mod7_passing_document_number,
    open_enrollment,
    register_member,
    review_enrollment,
    setup_airport_with_active_agreement,
    submit_document,
    capture_biometric,
    validate_error,
    validate_success,
    watchlist_add,
)
from test_helpers.fixtures import OPS, PM, CO, drive_member_to_three_rejections


class TestUnderagePriorityOverDocumentExpiry:
    def test_underage_and_expired_document_reports_underage(self, api):
        """PRD §2.8: "Only after those four come the business rules, in this sequence: age
        floors and venue age gates; document validity (expiry, format, uniqueness)" —
        the age floor is evaluated before document validity, so a request failing both
        reports the age error.
        PRD §3.3: "First, the member must be at least 18 years old — the `date_of_birth`
        must fall at least eighteen years before the logical clock date — failing
        `ERR_MEMBER_UNDERAGE`."

        Design: Difficulty/priority_pair_validation_conflict/expired_document_and_underage_both_fail_safety_order_pinned
        """
        airport, _ = setup_airport_with_active_agreement("PHX")
        center = create_enrollment_center(airport["id"])
        kid = register_member(
            email="kid@x.com", full_name="Kid Member", date_of_birth="2015-01-01"
        )
        enrollment = open_enrollment(
            kid, "ENROLLMENT_CENTER", center["id"],
            document_number="P5555555", document_expiry="2026-01-01",
            biometric_capture_ok=True,
        )
        resp = api.submit_document(enrollment["id"], make_member_headers(kid["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_UNDERAGE)
        enrollment_after = validate_success(
            api.get_enrollment(enrollment["id"], CO)
        )
        assert enrollment_after["status"] == "DRAFT", "no transition fired"

    def test_expired_document_alone_reports_document_expired(self, api):
        """PRD §3.3: "Second, unless this is a re-enrollment, `document_expiry` must lie
        strictly after the logical clock date, failing `ERR_DOCUMENT_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/expired_document_and_underage_both_fail_safety_order_pinned
        """
        airport, _ = setup_airport_with_active_agreement("PHX")
        center = create_enrollment_center(airport["id"])
        member = register_member(
            email="old@x.com", full_name="Of Age", date_of_birth="1990-01-01"
        )
        enrollment = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_number="P5555556", document_expiry="2026-01-01",
            biometric_capture_ok=True,
        )
        resp = api.submit_document(enrollment["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_EXPIRED)


class TestFraudReviewBranch:
    def test_score_17_routes_to_fraud_review_then_reject(self, api):
        """PRD §3.3: "Routing is by threshold, with inclusive boundaries: a score of exactly
        15 or more but below 20 routes the enrollment to `FRAUD_REVIEW` instead of
        `DOCUMENT_VERIFIED`" and "rejection moves the enrollment to `REJECTED`,
        increments the member's `document_reject_count_90d`, and recomputes the
        velocity component of the member's risk score."

        Score construction (no prior rejections, so VELOCITY stays silent and the
        four-check gate is not tripped): WATCHLIST +8 (watchlisted pair), DOC_FORMAT
        +4 ('D1000001' digit sum 2 fails the MOD-7 checksum), SELFIE_MISMATCH +5
        (biometric_capture_ok=false on the draft) = 17.

        Design: Difficulty/non_linear_state_machine/enrollment_fraud_review_branch_approve_vs_reject
        """
        airport, _ = setup_airport_with_active_agreement("LAX")
        center = create_enrollment_center(airport["id"])
        member = register_member(
            email="risky@x.com", full_name="Risky Member", date_of_birth="1988-05-05"
        )
        watchlist_add("D1000001", "1988-05-05")
        enrollment = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_type="DRIVERS_LICENSE", document_number="D1000001",
            biometric_capture_ok=False,
        )
        submitted = validate_success(
            api.submit_document(enrollment["id"], make_member_headers(member["id"]))
        )
        assert submitted["status"] == "FRAUD_REVIEW", (
            f"score 17 must route to FRAUD_REVIEW, got {submitted['status']}"
        )
        rejected = review_enrollment(submitted, "REJECT")
        assert rejected["status"] == "REJECTED"
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["document_reject_count_90d"] == 1
        assert member_after["status"] == "PENDING_ENROLLMENT", (
            "no activation cascade fires on the reject branch"
        )

    def test_score_17_routes_to_fraud_review_then_approve_completes(self, api):
        """PRD §3.3: "approval runs the same completion cascades as an ordinary completion"
        — approving a FRAUD_REVIEW enrollment completes it and activates the member.
        PRD §3.3: "`WATCHLIST` contributes 8 points when the pairing of
        `document_number` and `date_of_birth` appears on the fraud watchlist (an
        `OpsAdmin` maintains that list, adding or removing a pair by `action`)" —
        here the pair is removed before the member's enrollment, so only this
        member's enrollment sees the WATCHLIST points.

        Score construction: WATCHLIST +8, DOC_FORMAT +4 ('D2000001' digit sum 3
        fails MOD-7), SELFIE_MISMATCH +5 = 17 -> FRAUD_REVIEW.

        Design: Difficulty/non_linear_state_machine/enrollment_fraud_review_branch_approve_vs_reject
        """
        airport, _ = setup_airport_with_active_agreement("LAX")
        center = create_enrollment_center(airport["id"])
        member = register_member(
            email="risky2@x.com", full_name="Risky Two", date_of_birth="1988-05-05"
        )
        watchlist_add("D2000001", "1988-05-05")
        enrollment = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_type="DRIVERS_LICENSE", document_number="D2000001",
            biometric_capture_ok=False,
        )
        submitted = validate_success(
            api.submit_document(enrollment["id"], make_member_headers(member["id"]))
        )
        assert submitted["status"] == "FRAUD_REVIEW", (
            f"score 17 must route to FRAUD_REVIEW, got {submitted['status']}"
        )
        completed = review_enrollment(submitted, "APPROVE")
        assert completed["status"] == "COMPLETED"
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["status"] == "ACTIVE", (
            "approval runs the same completion cascade: member activates"
        )


class TestRiskBoundaryBelowReviewThreshold:
    def test_watchlist_only_score_8_proceeds_to_document_verified(self, api):
        """PRD §3.3: "`WATCHLIST` contributes 8 points when the pairing of `document_number`
        and `date_of_birth` appears on the fraud watchlist" and "Below 15, the
        enrollment proceeds to `DOCUMENT_VERIFIED`."

        'D1000006' has digit sum 7, which passes the MOD-7 checksum, keeping the
        score at exactly WATCHLIST's 8 points.

        Design: Corner/calculations/risk_score_boundary_fifteen_reviews_nineteen_reviews_twenty_blocks
        """
        airport, _ = setup_airport_with_active_agreement("GEG")
        center = create_enrollment_center(airport["id"])
        member = register_member(
            email="r8@x.com", full_name="Risk Eight", date_of_birth="1988-01-01"
        )
        watchlist_add("D1000006", "1988-01-01")
        enrollment = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_type="DRIVERS_LICENSE", document_number="D1000006",
            biometric_capture_ok=True,
        )
        submitted = validate_success(
            api.submit_document(enrollment["id"], make_member_headers(member["id"]))
        )
        assert submitted["status"] == "DOCUMENT_VERIFIED", (
            f"score 8 (WATCHLIST only) is below the review threshold 15, "
            f"got {submitted['status']}"
        )
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["risk_score"] == 8


class TestVelocityHardBlock:
    def test_third_rejection_blocks_new_submission(self, api):
        """PRD §3.3: "Fourth, the member's `document_reject_count_90d` — the count of this
        member's enrollments that flipped to `REJECTED` within the trailing ninety
        logical days, recomputed on every rejection — must be below three, failing
        `ERR_TOO_MANY_REJECTED_ENROLLMENTS`."

        Design: Corner/validations/third_rejected_enrollment_blocks_new_submission
        """
        airport, _ = setup_airport_with_active_agreement("MCI")
        center = create_enrollment_center(airport["id"])
        member = register_member(
            email="vel@x.com", full_name="Vel Member", date_of_birth="1990-01-01"
        )
        member, _ = drive_member_to_three_rejections(member, center, doc_prefix="V")
        fourth = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_number="P0000004", biometric_capture_ok=True,
        )
        resp = api.submit_document(fourth["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_TOO_MANY_REJECTED_ENROLLMENTS)

    def test_two_rejections_do_not_block_submission(self, api):
        """PRD §3.3: "Fourth, the member's `document_reject_count_90d` — the count of this
        member's enrollments that flipped to `REJECTED` within the trailing ninety
        logical days, recomputed on every rejection — must be below three, failing
        `ERR_TOO_MANY_REJECTED_ENROLLMENTS`." A count of 2 is below three, so the
        submission itself is not hard-blocked (the risk score may still route it).

        Design: Corner/validations/third_rejected_enrollment_blocks_new_submission
        """
        airport, _ = setup_airport_with_active_agreement("MCI")
        center = create_enrollment_center(airport["id"])
        member = register_member(
            email="vel2@x.com", full_name="Vel Two", date_of_birth="1990-01-01"
        )
        for i in (1, 2):
            doc = f"W10000{i}1"  # digit sums 3 and 4 -> both fail MOD-7
            watchlist_add(doc, "1990-01-01")
            e = open_enrollment(
                member, "ENROLLMENT_CENTER", center["id"],
                document_type="DRIVERS_LICENSE", document_number=doc,
                biometric_capture_ok=False,
            )
            e = submit_document(e, member)
            assert e["status"] == "FRAUD_REVIEW"
            review_enrollment(e, "REJECT")
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["document_reject_count_90d"] == 2
        # Third submission is not velocity-blocked (count 2 < 3); a clean,
        # unwatchlisted, MOD-7-passing document scores 0 -> DOCUMENT_VERIFIED.
        third = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_number="P1000006", biometric_capture_ok=True,
        )
        submitted = validate_success(
            api.submit_document(third["id"], make_member_headers(member["id"]))
        )
        assert submitted["status"] == "DOCUMENT_VERIFIED"


class TestDocumentNumberUniqueness:
    def test_second_member_with_same_document_number_rejected(self, api):
        """PRD §3.3: "Third, the `document_number` must not appear on any other enrollment
        that ever reached `DOCUMENT_VERIFIED`, failing `ERR_DOCUMENT_ALREADY_ENROLLED`."

        Design: Corner/validations/document_number_uniqueness_across_verified_enrollments
        """
        airport, _ = setup_airport_with_active_agreement("ICT")
        center = create_enrollment_center(airport["id"])
        member_a = register_member(
            email="da@x.com", full_name="Doc A", date_of_birth="1990-01-01"
        )
        enrollment_a = open_enrollment(
            member_a, "ENROLLMENT_CENTER", center["id"],
            document_number="PDUP0001", biometric_capture_ok=True,
        )
        submit_document(enrollment_a, member_a)  # reaches DOCUMENT_VERIFIED
        member_b = register_member(
            email="db@x.com", full_name="Doc B", date_of_birth="1991-01-01"
        )
        enrollment_b = open_enrollment(
            member_b, "ENROLLMENT_CENTER", center["id"],
            document_number="PDUP0001", biometric_capture_ok=True,
        )
        resp = api.submit_document(enrollment_b["id"], make_member_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_ALREADY_ENROLLED)
        enrollment_b_after = validate_success(api.get_enrollment(enrollment_b["id"], CO))
        assert enrollment_b_after["status"] == "DRAFT"


class TestEnrollmentTerminalLockdown:
    def test_completed_enrollment_rejects_capture_biometric(self, api):
        """PRD §3.3: "From `DOCUMENT_VERIFIED`, the member records the biometric capture."
        — capture is defined only from DOCUMENT_VERIFIED, and per PRD §2.8 state
        legality failures surface `ERR_INVALID_STATE`; a COMPLETED enrollment has no
        capture transition.

        Design: Corner/state_machines/enrollment_terminal_completed_rejects_capture
        """
        airport, _ = setup_airport_with_active_agreement("SLC")
        center = create_enrollment_center(airport["id"])
        member, enrollment = enroll_member_at_center(
            center, email="term@x.com", document_number="PL200001"
        )
        assert enrollment["status"] == "COMPLETED"
        resp = api.capture_biometric(enrollment["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        enrollment_after = validate_success(api.get_enrollment(enrollment["id"], CO))
        assert enrollment_after["status"] == "COMPLETED", "terminal state unchanged"


class TestReviewGate:
    def test_review_on_document_verified_enrollment_rejected(self, api):
        """PRD §3.3: "Review requires the enrollment to actually be in `FRAUD_REVIEW`
        (`ERR_ENROLLMENT_NOT_IN_REVIEW` otherwise) and takes a `decision`"

        Design: Corner/endpoints/enrollment_review_is_compliance_only
        """
        airport, _ = setup_airport_with_active_agreement("FSD")
        center = create_enrollment_center(airport["id"])
        member = register_member(
            email="clean@x.com", full_name="Clean Member", date_of_birth="1990-01-01"
        )
        enrollment = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_number="PC000001", biometric_capture_ok=True,
        )
        enrollment = submit_document(enrollment, member)
        assert enrollment["status"] == "DOCUMENT_VERIFIED"
        resp = api.review_enrollment(enrollment["id"], "APPROVE", CO)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_IN_REVIEW)
