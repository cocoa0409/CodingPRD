"""Tests for the complaint lifecycle, the insurance-mismatch cascade into
provider auto-suspension, and the attestation state machine (PRD §3.9, §3.3).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_slot,
    create_attestation,
    create_patient,
    create_plan,
    create_slot,
    get_attestation,
    get_provider,
    get_slot,
    make_ops_admin_headers,
    make_patient_headers,
    make_practice_staff_headers,
    make_provider_headers,
    setup_bookable_practice,
    slot_time,
    validate_error,
    validate_success,
    verify_attestation,
)


class TestComplaintUpholdProviderSuspensionCascade:
    def _setup_three_upheld_complaints(self):
        """Three plans with VERIFIED attestations; three booked slots each with
        its own plan; one future OPEN slot left over; three INSURANCE_MISMATCH
        complaints filed and responded (UNDER_REVIEW)."""
        ctx = setup_bookable_practice(
            slot_windows=[
                ("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z"),
                ("2026-09-03T11:00:00Z", "2026-09-03T11:30:00Z"),
                ("2026-09-03T12:00:00Z", "2026-09-03T12:30:00Z"),
                ("2026-09-10T10:00:00Z", "2026-09-10T10:30:00Z"),
            ]
        )
        prov_id = ctx["provider"]["id"]
        plans = [create_plan(plan_name=f"A{i}", plan_code=f"A{i}") for i in (1, 2, 3)]
        attestations = [
            verify_attestation(create_attestation(prov_id, p["id"])["id"], "VERIFY")
            for p in plans
        ]
        patient = create_patient()
        bookings = [
            book_slot(
                ctx["slots"][i]["id"],
                patient["id"],
                ctx["type"]["id"],
                insurance_plan_id=plans[i]["id"],
            )
            for i in range(3)
        ]
        complaints = []
        for b in bookings:
            resp = api_client.create_complaint(
                {"booking_id": b["id"], "complaint_type": "INSURANCE_MISMATCH"},
                make_patient_headers(patient["id"]),
            )
            complaints.append(validate_success(resp, 201))
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        for i, c in enumerate(complaints):
            api_client.respond_complaint(
                c["id"], {"response": f"we do not take A{i+1}"}, staff
            )
        return ctx, plans, attestations, bookings, complaints

    def test_third_uphold_auto_suspends_provider_and_closes_future_open_slots(self, api):
        """PRD §3.9: "The counter is a tripwire. When a provider's `insurance_mismatch_count` reaches 3, the system suspends the provider — `ACTIVE` to `SUSPENDED` — with the full suspension cascade: every future `OPEN` slot closes with `close_reason` `PROVIDER_SUSPENDED`, and `bookable_in_directory` is recomputed to false."

        Design: Difficulty/transitive_cascade/complaint_uphold_provider_suspension_cascade
        """
        ctx, plans, attestations, bookings, complaints = self._setup_three_upheld_complaints()
        for c in complaints[:2]:
            api_client.resolve_complaint(c["id"], {"outcome": "UPHOLD"}, TEST_USERS["ops_admin_headers"])
        resp = api_client.resolve_complaint(
            complaints[2]["id"], {"outcome": "UPHOLD"}, TEST_USERS["ops_admin_headers"]
        )
        validate_success(resp)
        prov = get_provider(ctx["provider"]["id"])
        assert prov["insurance_mismatch_count"] == 3
        assert prov["status"] == "SUSPENDED"
        assert prov["bookable_in_directory"] is False
        s4 = get_slot(ctx["slots"][3]["id"])
        assert s4["status"] == "CLOSED"
        assert s4["close_reason"] == "PROVIDER_SUSPENDED"

    def test_each_uphold_revokes_the_matching_verified_attestation(self, api):
        """PRD §3.9: "That selected attestation is then moved from `VERIFIED` to `REVOKED`, and the provider's `insurance_mismatch_count` increases by 1."

        Design: Difficulty/transitive_cascade/complaint_uphold_provider_suspension_cascade
        """
        ctx, plans, attestations, bookings, complaints = self._setup_three_upheld_complaints()
        for i, c in enumerate(complaints):
            api_client.resolve_complaint(c["id"], {"outcome": "UPHOLD"}, TEST_USERS["ops_admin_headers"])
            att_after = get_attestation(attestations[i]["id"])
            assert att_after["status"] == "REVOKED", (
                f"attestation {i+1} must be REVOKED after its UPHOLD resolution"
            )
            prov = get_provider(ctx["provider"]["id"])
            assert prov["insurance_mismatch_count"] == i + 1


class TestComplaintRespond:
    def test_respond_twice_rejected(self, api):
        """PRD §3.9: "The practice gets the first word: a `PracticeStaff` response moves the complaint from `OPEN` to `UNDER_REVIEW` and stores the supplied `response` text; responding to a complaint that is not `OPEN` is rejected with `ERR_COMPLAINT_NOT_OPEN`."

        Design: Corner/state_machines/complaint_respond_from_under_review_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        resp = api_client.create_complaint(
            {"booking_id": booking["id"], "complaint_type": "DIRECTORY_INACCURACY"},
            make_patient_headers(patient["id"]),
        )
        complaint = validate_success(resp, 201)
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        api_client.respond_complaint(complaint["id"], {"response": "looking into it"}, staff)
        resp2 = api_client.respond_complaint(complaint["id"], {"response": "again"}, staff)
        validate_error(resp2, ApiErrorId.ERR_COMPLAINT_NOT_OPEN)

    def test_first_respond_moves_complaint_to_under_review(self, api):
        """PRD §3.9: "The practice gets the first word: a `PracticeStaff` response moves the complaint from `OPEN` to `UNDER_REVIEW` and stores the supplied `response` text; responding to a complaint that is not `OPEN` is rejected with `ERR_COMPLAINT_NOT_OPEN`."

        Design: Corner/state_machines/complaint_respond_from_under_review_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        resp = api_client.create_complaint(
            {"booking_id": booking["id"], "complaint_type": "DIRECTORY_INACCURACY"},
            make_patient_headers(patient["id"]),
        )
        complaint = validate_success(resp, 201)
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        resp2 = api_client.respond_complaint(complaint["id"], {"response": "looking into it"}, staff)
        data = validate_success(resp2)
        assert data["status"] == "UNDER_REVIEW"
        assert data["response"] == "looking into it"


class TestAttestationStateMachine:
    def _setup_attested_attestation(self):
        ctx = setup_bookable_practice(slot_windows=[])
        plan = create_plan()
        att = create_attestation(ctx["provider"]["id"], plan["id"])
        return ctx, plan, att

    def test_reject_is_terminal(self, api):
        """PRD §3.3: "An `OpsAdmin` reviews it through the verification action, which takes a `decision`: `VERIFY` moves the attestation to `VERIFIED` and records the operator's identity in `verified_by`, while `REJECT` moves it to terminal `REJECTED`."

        Design: Corner/state_machines/attestation_verify_reject_terminal
        """
        ctx, plan, att = self._setup_attested_attestation()
        resp = api_client.verify_attestation(att["id"], {"decision": "REJECT"}, TEST_USERS["ops_admin_headers"])
        data = validate_success(resp)
        assert data["status"] == "REJECTED"

    def test_verify_after_reject_is_invalid_state(self, api):
        """PRD §3.3: "An `OpsAdmin` reviews it through the verification action, which takes a `decision`: `VERIFY` moves the attestation to `VERIFIED` and records the operator's identity in `verified_by`, while `REJECT` moves it to terminal `REJECTED`."
        PRD §2.8: "State-machine admissibility.** The target entity must be in a state from which the requested transition exists — this includes a slot being `OPEN` for booking (`ERR_SLOT_NOT_OPEN`), a booking being `CONFIRMED` for cancellation (`ERR_BOOKING_NOT_CANCELLABLE`), an invoice being `ISSUED` for dispute (`ERR_INVOICE_NOT_DISPUTABLE`) or for payment with a positive balance (`ERR_INVOICE_NOT_PAYABLE`), a complaint being `OPEN` for a response or `UNDER_REVIEW` for resolution (`ERR_COMPLAINT_NOT_OPEN`), and the generic `ERR_INVALID_STATE` for all other illegal transitions."

        Design: Corner/state_machines/attestation_verify_reject_terminal
        """
        ctx, plan, att = self._setup_attested_attestation()
        api_client.verify_attestation(att["id"], {"decision": "REJECT"}, TEST_USERS["ops_admin_headers"])
        resp = api_client.verify_attestation(att["id"], {"decision": "VERIFY"}, TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_verify_blocked_when_plan_retired(self, api):
        """PRD §3.3: "Verification requires the referenced plan to be `ACTIVE`; verifying against a retired plan is rejected with `ERR_PLAN_NOT_ACTIVE`."

        Design: Corner/state_machines/attestation_verify_blocked_when_plan_retired
        """
        ctx, plan, att = self._setup_attested_attestation()
        api_client.retire_insurance_plan(plan["id"], TEST_USERS["ops_admin_headers"])
        resp = api_client.verify_attestation(att["id"], {"decision": "VERIFY"}, TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        att_after = get_attestation(att["id"])
        assert att_after["status"] == "ATTESTED"

    def test_verify_happy_path_sets_verified_by(self, api):
        """PRD §3.3: "An `OpsAdmin` reviews it through the verification action, which takes a `decision`: `VERIFY` moves the attestation to `VERIFIED` and records the operator's identity in `verified_by`, while `REJECT` moves it to terminal `REJECTED`."

        Design: Corner/state_machines/attestation_verify_blocked_when_plan_retired
        """
        ctx, plan, att = self._setup_attested_attestation()
        admin = make_ops_admin_headers("verify-admin-1")
        resp = api_client.verify_attestation(att["id"], {"decision": "VERIFY"}, admin)
        data = validate_success(resp)
        assert data["status"] == "VERIFIED"
        assert data["verified_by"] == "verify-admin-1"


class TestDuplicateAttestation:
    def test_duplicate_attested_pair_rejected(self, api):
        """PRD §3.3: "Submitting an attestation while another attestation for the same provider-and-plan pair is already `ATTESTED` or `VERIFIED` is rejected with `ERR_DUPLICATE_ATTESTATION`."

        Design: Corner/validations/duplicate_attestation_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[])
        plan = create_plan()
        create_attestation(ctx["provider"]["id"], plan["id"])
        resp = api_client.create_attestation(
            {
                "provider_id": ctx["provider"]["id"],
                "plan_id": plan["id"],
                "effective_from": "2026-06-01T00:00:00Z",
                "effective_to": "2027-06-01T00:00:00Z",
            },
            make_provider_headers(ctx["provider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ATTESTATION)

    def test_duplicate_verified_pair_rejected(self, api):
        """PRD §3.3: "Submitting an attestation while another attestation for the same provider-and-plan pair is already `ATTESTED` or `VERIFIED` is rejected with `ERR_DUPLICATE_ATTESTATION`."

        Design: Corner/validations/duplicate_attestation_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[])
        plan = create_plan()
        att = create_attestation(ctx["provider"]["id"], plan["id"])
        verify_attestation(att["id"], "VERIFY")
        resp = api_client.create_attestation(
            {
                "provider_id": ctx["provider"]["id"],
                "plan_id": plan["id"],
                "effective_from": "2026-06-01T00:00:00Z",
                "effective_to": "2027-06-01T00:00:00Z",
            },
            make_provider_headers(ctx["provider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ATTESTATION)
