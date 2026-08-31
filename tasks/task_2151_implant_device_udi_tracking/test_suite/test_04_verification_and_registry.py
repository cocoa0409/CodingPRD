"""Verification, the registry obligation and the case close gate."""

from test_helpers import (
    ApiErrorId,
    CC,
    CC2,
    CO,
    IL,
    RI,
    RI2,
    RT,
    add_unit,
    adjudicate_registry,
    agreement_version,
    amend_record,
    assert_readiness_payload,
    assert_registry_submission,
    assert_same_instant,
    create_active_agreement,
    create_case,
    create_catalog_item,
    create_lot,
    create_patient,
    create_vendor,
    document_implant,
    get_case,
    get_lot,
    get_readiness,
    get_record,
    get_submission,
    make_vendor_rep_headers,
    match_invoice,
    release_lot,
    set_clock,
    setup_documented_implant,
    setup_verified_implant,
    start_case,
    submission_for,
    submit_registry,
    validate_error,
    validate_paginated,
    validate_success,
    verify_record,
)

REGISTRY_CATALOG = {
    "device_identifier": "00812345678950",
    "description": "Hip Cup",
    "category": "HIGH_COST_IMPLANT",
    "list_charge_cents": 900_000,
    "charge_code": "CDM-77190",
    "registry_required": True,
}


class TestRegistryAdjudicationCycle:
    def test_resubmission_after_a_rejection_increments_the_lap_counter(self, api):
        """PRD §3.7: "Submission is legal from `REQUIRED` and from `REJECTED`; from
        any other status it is rejected with `ERR_INVALID_LIFECYCLE_STATE`."
        PRD §3.7: "The two source states differ in exactly one side effect: coming
        from `REJECTED` the submission also increments `resubmission_count` by one,
        counting the laps of the `SUBMITTED → REJECTED → SUBMITTED` cycle; coming
        from `REQUIRED` the counter is untouched."
        PRD §3.7: "A `REJECTED` outcome does exactly the same three things and
        additionally stores the supplied `rejection_reason` — which for that outcome
        is not optional at all: an adjudication of `REJECTED` without a present,
        non-empty `rejection_reason` is a malformed request and is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Difficulty/non_linear_state_machine/registry_submission_reject_resubmit_accept_cycle
        """
        world = setup_verified_implant(
            unit_cost=500_000,
            catalog_overrides=REGISTRY_CATALOG,
            lot_overrides={"lot_number": "L-7701", "expiration_date": "2027-06-30"},
        )
        submission = submission_for(world["record"]["id"])
        assert submission is not None
        assert_registry_submission(submission)
        assert submission["resubmission_count"] == 0

        submit_registry(submission["id"], "AJRR-0001")
        adjudicate_registry(
            submission["id"], "REJECTED", "laterality documentation illegible"
        )
        assert get_submission(submission["id"])["status"] == "REJECTED"

        resubmitted = validate_success(
            api.submit_registry_submission(
                submission["id"], {"registry_code": "AJRR-0001"}, CO
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["resubmission_count"] == 1
        assert resubmitted["completeness_score"] == 100

    def test_accepted_adjudication_is_terminal_and_leaves_the_case_ready(self, api):
        """PRD §3.7: "An `ACCEPTED` outcome moves the submission to the terminal
        `ACCEPTED`, stamps `adjudicated_at_utc` from the logical clock and
        re-derives the case's `readiness_status`."
        PRD §3.11: "Otherwise, if any registry submission belonging to this case's
        records has a `status` of `REQUIRED` or `REJECTED`, the posture is
        `BLOCKED_REGISTRY`."

        Design: Difficulty/non_linear_state_machine/registry_submission_reject_resubmit_accept_cycle
        """
        world = setup_verified_implant(
            unit_cost=500_000,
            catalog_overrides=REGISTRY_CATALOG,
            lot_overrides={"lot_number": "L-7701", "expiration_date": "2027-06-30"},
        )
        submission = submission_for(world["record"]["id"])

        submit_registry(submission["id"], "AJRR-0001")
        adjudicate_registry(submission["id"], "REJECTED", "laterality illegible")
        submit_registry(submission["id"], "AJRR-0001")

        accepted = validate_success(
            api.adjudicate_registry_submission(
                submission["id"], {"outcome": "ACCEPTED"}, CO
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["adjudicated_at_utc"] is not None
        assert accepted["resubmission_count"] == 1
        assert get_case(world["case"]["id"])["readiness_status"] == "READY"


class TestCaseCloseGate:
    def test_close_is_refused_while_a_registry_submission_is_still_required(self, api):
        """PRD §3.11: "The close gate then maps each blocked posture to its own
        error, tried in exactly the same top-to-bottom order as the derivation
        above: `BLOCKED_RESERVATION` and `BLOCKED_DOCUMENTATION` both surface as
        `ERR_CASE_READINESS_UNMET`, `BLOCKED_REGISTRY` as `ERR_REGISTRY_OUTSTANDING`,
        and `BLOCKED_CHARGE` as `ERR_CHARGE_VARIANCE_UNRESOLVED`."
        PRD §3.11: "Otherwise, if any registry submission belonging to this case's
        records has a `status` of `REQUIRED` or `REJECTED`, the posture is
        `BLOCKED_REGISTRY`."

        Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_required_registry_submission
        """
        world = setup_verified_implant(
            unit_cost=500_000,
            catalog_overrides=REGISTRY_CATALOG,
            lot_overrides={"lot_number": "L-7701", "expiration_date": "2027-06-30"},
        )

        validate_error(
            api.close_case(world["case"]["id"], CC),
            ApiErrorId.ERR_REGISTRY_OUTSTANDING,
            409,
        )

        case = get_case(world["case"]["id"])
        assert case["status"] == "IN_PROGRESS"
        assert case["readiness_status"] == "BLOCKED_REGISTRY"
        assert get_record(world["record"]["id"])["status"] == "VERIFIED"

    def test_the_child_submission_alone_is_what_blocks_an_otherwise_finished_case(
        self, api
    ):
        """PRD §3.5: "When the implanted model's `registry_required` is true and no
        registry submission yet exists for this record, verification creates one,
        and which state it opens in depends on the patient."
        PRD §3.5: "If the patient's `registry_consent` is anything other than
        `DECLINED` — that is, `GRANTED` or `UNKNOWN` — the submission is created in
        `REQUIRED` with `deadline_utc` set to this verification's `verified_at_utc`
        plus 30 days."
        PRD §3.11: "A dedicated read exposes that posture together with the four
        counters behind it: `readiness_status`, the case's
        `blocked_reservation_count`, an `unverified_record_count` giving the number
        of this case's implant records in `DOCUMENTED` or `AMENDED`, an
        `outstanding_registry_count` giving the number of registry submissions of
        those records in `REQUIRED` or `REJECTED`, an `unfinalized_charge_count`
        giving the number of charge lines of those records in `DRAFT`, `POSTED` or
        `CORRECTION_REQUIRED`, and the case's `total_posted_charge_cents`."

        Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_required_registry_submission
        """
        world = setup_verified_implant(
            unit_cost=500_000,
            catalog_overrides=REGISTRY_CATALOG,
            lot_overrides={"lot_number": "L-7701", "expiration_date": "2027-06-30"},
        )
        rows, meta = validate_paginated(
            api.list_registry_submissions(
                CO, {"implant_record_id": world["record"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "REQUIRED"

        readiness = get_readiness(world["case"]["id"])
        assert_readiness_payload(readiness)
        assert readiness["readiness_status"] == "BLOCKED_REGISTRY"
        assert readiness["unverified_record_count"] == 0
        assert readiness["outstanding_registry_count"] == 1
        assert readiness["unfinalized_charge_count"] == 0
        assert readiness["blocked_reservation_count"] == 0
        assert readiness["total_posted_charge_cents"] == 0

        submit_registry(rows[0]["id"], "AJRR-0001")
        adjudicate_registry(rows[0]["id"], "ACCEPTED")
        closed = validate_success(api.close_case(world["case"]["id"], CC), 200)
        assert closed["status"] == "CLOSED"

    def test_close_is_refused_while_a_record_is_only_documented(self, api):
        """PRD §3.11: "Otherwise, if any implant record of this case has a `status`
        of `DOCUMENTED` or `AMENDED`, the posture is `BLOCKED_DOCUMENTATION`."
        PRD §3.11: "The close gate then maps each blocked posture to its own error,
        tried in exactly the same top-to-bottom order as the derivation above:
        `BLOCKED_RESERVATION` and `BLOCKED_DOCUMENTATION` both surface as
        `ERR_CASE_READINESS_UNMET`, `BLOCKED_REGISTRY` as `ERR_REGISTRY_OUTSTANDING`,
        and `BLOCKED_CHARGE` as `ERR_CHARGE_VARIANCE_UNRESOLVED`."

        Design: Corner/validations/case_close_blocked_while_a_record_is_only_documented
        """
        world = setup_documented_implant()

        validate_error(
            api.close_case(world["case"]["id"], CC),
            ApiErrorId.ERR_CASE_READINESS_UNMET,
            409,
        )
        assert get_case(world["case"]["id"])["status"] == "IN_PROGRESS"

        readiness = get_readiness(world["case"]["id"])
        assert_readiness_payload(readiness)
        assert readiness["readiness_status"] == "BLOCKED_DOCUMENTATION"
        assert readiness["unverified_record_count"] == 1
        assert readiness["outstanding_registry_count"] == 0
        assert readiness["unfinalized_charge_count"] == 0
        assert readiness["blocked_reservation_count"] == 0
        assert readiness["total_posted_charge_cents"] == 0


class TestVerificationTransitions:
    def test_verifying_a_verified_record_a_second_time_is_rejected(self, api):
        """PRD §3.5: "Either a `CircClinician` or a `ComplianceOfficer` may verify,
        from `DOCUMENTED → VERIFIED` or from `AMENDED → VERIFIED`, and in both cases
        the acting `X-User-ID` must differ from the record's `documented_by_user_id`
        or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. A record in any
        other status is rejected with `ERR_INVALID_RECORD_STATE`."

        Design: Corner/state_machines/verify_an_already_verified_record_returns_invalid_record_state
        """
        world = setup_verified_implant()
        record = world["record"]
        assert record["status"] == "VERIFIED"
        assert record["verified_by_user_id"] == "cc-02"

        validate_error(
            api.verify_implant_record(record["id"], CO),
            ApiErrorId.ERR_INVALID_RECORD_STATE,
            409,
        )

        after = get_record(record["id"])
        assert after["status"] == "VERIFIED"
        assert after["verified_by_user_id"] == "cc-02"
        assert after["amendment_count"] == 0

    def test_amending_pulls_a_submitted_registry_row_back_to_required(self, api):
        """PRD §3.5: "Amending increments `amendment_count` by one, moves any
        registry submission for this record that is sitting in `SUBMITTED` back to
        `REQUIRED` — because the registry was told something that has now changed —
        and re-derives the case's `readiness_status`."
        PRD §3.11: "Otherwise, if any implant record of this case has a `status` of
        `DOCUMENTED` or `AMENDED`, the posture is `BLOCKED_DOCUMENTATION`."

        Design: Corner/state_machines/amend_reverts_submitted_registry_submission_to_required
        """
        world = setup_verified_implant(
            unit_cost=500_000,
            catalog_overrides=REGISTRY_CATALOG,
            lot_overrides={"lot_number": "L-7701", "expiration_date": "2027-06-30"},
        )
        submission = submission_for(world["record"]["id"])
        submit_registry(submission["id"], "AJRR-0001")
        assert get_submission(submission["id"])["status"] == "SUBMITTED"

        amended = validate_success(
            api.amend_implant_record(world["record"]["id"], CC), 200
        )
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1

        reverted = get_submission(submission["id"])
        assert reverted["status"] == "REQUIRED"
        assert reverted["resubmission_count"] == 0
        assert get_case(world["case"]["id"])["readiness_status"] == "BLOCKED_DOCUMENTATION"

    def test_declined_consent_opens_the_submission_directly_in_exempt(self, api):
        """PRD §3.5: "If the patient's `registry_consent` is `DECLINED`, the
        submission is created directly in the terminal `EXEMPT` state, recording
        that the obligation was recognised and lawfully waived."
        PRD §3.11: "Otherwise, if any registry submission belonging to this case's
        records has a `status` of `REQUIRED` or `REJECTED`, the posture is
        `BLOCKED_REGISTRY`."

        Design: Corner/state_machines/registry_submission_created_exempt_when_patient_consent_declined
        """
        world = setup_documented_implant(
            unit_cost=500_000,
            catalog_overrides=REGISTRY_CATALOG,
            lot_overrides={"lot_number": "L-7701", "expiration_date": "2027-06-30"},
            patient_overrides={
                "mrn": "MRN-6006",
                "display_name": "Pat Six",
                "registry_consent": "DECLINED",
            },
        )

        verify_record(world["record"]["id"])

        rows, meta = validate_paginated(
            api.list_registry_submissions(
                CO, {"implant_record_id": world["record"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "EXEMPT"

        assert get_case(world["case"]["id"])["readiness_status"] == "READY"
        closed = validate_success(api.close_case(world["case"]["id"], CC), 200)
        assert closed["status"] == "CLOSED"


class TestCompletenessScore:
    def test_score_of_eighty_submits_and_seventy_five_is_refused(self, api):
        """PRD §3.7: "Thirty points are awarded when both the record's `udi_di` and
        its `udi_pi_serial` are non-empty; if exactly one of the two is non-empty, a
        partial fifteen points are awarded instead; if neither is, nothing is
        awarded. Twenty-five points are awarded when the patient's
        `registry_consent` is `GRANTED`, and nothing when it is `DECLINED` or
        `UNKNOWN`. Twenty points are awarded when the record's `anatomic_site` is
        non-empty **and** its `laterality` is anything other than `NOT_APPLICABLE`;
        both conditions must hold. Fifteen points are awarded when the verification
        turnaround was prompt — take the interval from the record's
        `documented_at_utc` to its `verified_at_utc`, express it in whole hours
        discarding any fraction, and award the points when that number of hours is
        at most 72, which is three days. Ten points are awarded when the lot carries
        an `expiration_date` at all."
        PRD §3.7: "Only after those state checks pass is the freshly recomputed
        `completeness_score` compared against the threshold: a score of at least 80
        may be submitted, and a score of 79 or less is rejected with
        `ERR_REGISTRY_SUBMISSION_INCOMPLETE`."
        PRD §3.7: "Every submission also carries a `deadline_utc`, fixed at creation
        to the verification instant plus 30 days."

        Design: Corner/calculations/registry_completeness_score_eighty_passes_seventy_five_fails
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor = create_vendor()
        catalog_item = create_catalog_item(vendor["id"], **REGISTRY_CATALOG)
        lot = create_lot(
            catalog_item["id"], lot_number="L-7701", expiration_date="2027-06-30"
        )
        unit_a = add_unit(lot["id"], "SN-A1", 500_000)
        unit_b = add_unit(lot["id"], "SN-B1", 500_000)
        release_lot(lot["id"])

        patient_a = create_patient(
            mrn="MRN-A", display_name="Pat A", registry_consent="GRANTED"
        )
        patient_b = create_patient(
            mrn="MRN-B", display_name="Pat B", registry_consent="UNKNOWN"
        )
        case_a = create_case(
            patient_a["id"],
            case_number="CASE-A",
            or_room_code="OR-3",
            scheduled_start_utc="2026-09-10T08:00:00Z",
            scheduled_end_utc="2026-09-10T10:00:00Z",
        )
        case_b = create_case(
            patient_b["id"],
            case_number="CASE-B",
            or_room_code="OR-4",
            scheduled_start_utc="2026-09-11T08:00:00Z",
            scheduled_end_utc="2026-09-11T10:00:00Z",
        )

        start_case(case_a["id"])
        record_a = document_implant(
            case_a["id"], unit_a, anatomic_site="ACETABULUM", laterality="NOT_APPLICABLE"
        )
        start_case(case_b["id"])
        record_b = document_implant(
            case_b["id"], unit_b, anatomic_site="ACETABULUM", laterality="LEFT"
        )

        verify_record(record_a["id"])
        verify_record(record_b["id"])

        submission_a = submission_for(record_a["id"])
        submission_b = submission_for(record_b["id"])
        assert submission_a["completeness_score"] == 80
        assert submission_b["completeness_score"] == 75

        submitted = validate_success(
            api.submit_registry_submission(
                submission_a["id"], {"registry_code": "AJRR-A"}, CO
            ),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["registry_code"] == "AJRR-A"
        assert_same_instant(
            submitted["deadline_utc"], "2026-10-01T00:00:00Z", "deadline_utc"
        )

        validate_error(
            api.submit_registry_submission(
                submission_b["id"], {"registry_code": "AJRR-B"}, CO
            ),
            ApiErrorId.ERR_REGISTRY_SUBMISSION_INCOMPLETE,
            422,
        )
        refused = get_submission(submission_b["id"])
        assert refused["status"] == "REQUIRED"
        assert refused["submitted_at_utc"] is None


class TestSegregationOfDuties:
    def test_all_three_separated_pairs_reject_the_same_acting_user(self, api):
        """PRD §2.8: "Releasing a lot from quarantine requires that `X-User-ID`
        differ from the lot's `received_by_user_id`. Verifying an implant record
        requires that `X-User-ID` differ from that record's
        `documented_by_user_id`. Approving a vendor invoice requires that
        `X-User-ID` differ from that invoice's `matched_by_user_id`. Any of the
        three attempted by the same user is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and because that check sits at step
        9 of the ladder it fires only after the target resource has already been
        confirmed to be in a legal state for the transition."
        PRD §2.8: "The check is on `X-User-ID`, not on `X-User-Role`, which has two
        consequences: two different users holding the same role satisfy the
        separation, and one user cannot satisfy it by switching roles between the
        two halves."

        Design: Corner/rbac/three_segregation_of_duties_pairs_reject_the_same_actor
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor = create_vendor()
        agreement = create_active_agreement(vendor["id"])
        catalog_item = create_catalog_item(vendor["id"])
        lot = create_lot(catalog_item["id"])
        unit = add_unit(
            lot["id"], "SN-0001", 462_500, consignment_agreement_id=agreement["id"]
        )

        # 1. The receiver may not release.
        validate_error(
            api.release_lot(lot["id"], RT),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert get_lot(lot["id"])["status"] == "QUARANTINE"

        released = release_lot(lot["id"])
        assert released["released_by_user_id"] == "il-01"

        patient = create_patient()
        case = create_case(patient["id"])
        start_case(case["id"])
        record = document_implant(case["id"], unit)

        # 2. The documenter may not verify.
        validate_error(
            api.verify_implant_record(record["id"], CC),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert get_record(record["id"])["status"] == "DOCUMENTED"

        verified = verify_record(record["id"])
        assert verified["verified_by_user_id"] == "cc-02"

        invoice = validate_success(
            api.create_vendor_invoice(
                {
                    "vendor_id": vendor["id"],
                    "consignment_agreement_id": agreement["id"],
                    "invoice_number": "INV-1",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [unit["id"]],
                    "expected_agreement_version": agreement_version(agreement["id"]),
                },
                make_vendor_rep_headers(vendor["id"]),
            ),
            201,
        )
        matched = match_invoice(invoice["id"], RI)
        assert matched["status"] == "MATCHED"
        assert matched["matched_by_user_id"] == "ri-01"

        # 3. The matcher may not approve.
        validate_error(
            api.approve_invoice(invoice["id"], {}, RI),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert validate_success(api.get_vendor_invoice(invoice["id"], RI))["status"] == (
            "MATCHED"
        )

        approved = validate_success(api.approve_invoice(invoice["id"], {}, RI2), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "ri-02"
