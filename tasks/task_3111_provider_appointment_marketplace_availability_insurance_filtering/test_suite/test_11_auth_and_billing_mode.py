"""Tests for auth (headers, role denial, ownership), the response envelope, the
subscription billing variant, the patient registration role allowance, and
immediate booking write-back consistency (PRD §2.1, §2.2, §2.8, §3.4, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_slot,
    create_attestation,
    create_patient,
    create_plan,
    get_invoice,
    list_ledger_entries_for_invoice,
    make_patient_headers,
    make_practice_staff_headers,
    make_provider_headers,
    setup_bookable_practice,
    setup_invoiced_practice,
    slot_time,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    activate_provider,
    create_and_activate_practice,
    create_provider,
    generate_invoice,
)


class TestMissingAuthHeader:
    def test_missing_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api_client.create_practice(
            {"name": "P1", "timezone": "America/New_York"},
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_invalid_role_value_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api_client.create_practice(
            {"name": "P1", "timezone": "America/New_York"},
            headers={"X-User-ID": "test-x", "X-User-Role": "SuperUser"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestForbiddenRole:
    def test_patient_cannot_create_practice(self, api):
        """PRD §2.1: "A request whose role is valid but not listed among the roles authorized for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/patient_cannot_create_practice_forbidden
        """
        patient = create_patient()
        resp = api_client.create_practice(
            {"name": "P1", "timezone": "America/New_York"},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_practice_staff_cannot_verify_attestation(self, api):
        """PRD §2.1: "A request whose role is valid but not listed among the roles authorized for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.3: "An `OpsAdmin` reviews it through the verification action, which takes a `decision`: `VERIFY` moves the attestation to `VERIFIED` and records the operator's identity in `verified_by`, while `REJECT` moves it to terminal `REJECTED`."

        Design: Corner/rbac/practice_staff_cannot_verify_attestation_forbidden
        """
        ctx = setup_bookable_practice(slot_windows=[])
        plan = create_plan()
        att = create_attestation(ctx["provider"]["id"], plan["id"])
        resp = api_client.verify_attestation(
            att["id"], {"decision": "VERIFY"}, make_practice_staff_headers(ctx["practice"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        from test_helpers import get_attestation
        att_after = get_attestation(att["id"])
        assert att_after["status"] == "ATTESTED"


class TestOwnershipMismatch:
    def test_patient_cannot_cancel_other_patients_booking(self, api):
        """PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a patient (a booking, a review, a complaint, the patient's own record) compare the resource's `patient_id` to `X-User-ID`."
        PRD §2.1: "Acting outside this ownership scope is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/patient_cannot_cancel_other_patients_booking
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        pat_a = create_patient(email="pa@x.com", full_name="Pat A")
        pat_b = create_patient(email="pb@x.com", full_name="Pat B")
        booking = book_slot(ctx["slots"][0]["id"], pat_a["id"], ctx["type"]["id"])
        resp = api_client.cancel_booking(booking["id"], make_patient_headers(pat_b["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        from test_helpers import get_booking
        assert get_booking(booking["id"])["status"] == "CONFIRMED"

    def test_provider_cannot_publish_slots_for_other_provider(self, api):
        """PRD §2.1: "When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on provider-scoped resources compare the relevant `provider_id` to `X-User-ID`."
        PRD §2.1: "Acting outside this ownership scope is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/provider_cannot_publish_slots_for_other_provider
        """
        practice = create_and_activate_practice()
        prov_a = activate_provider(create_provider(practice["id"], display_name="Dr A")["id"])
        prov_b = activate_provider(create_provider(practice["id"], display_name="Dr B")["id"])
        resp = api_client.create_slot(
            prov_b["id"],
            {"start_at": "2026-09-03T10:00:00Z", "end_at": "2026-09-03T10:30:00Z"},
            make_provider_headers(prov_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


class TestAnonymousRole:
    def test_anonymous_can_register_patient(self, api):
        """PRD §3.4: "Patient registration is open: an `Anonymous` caller creates a patient with a `full_name` and an `email` that must be unique across all patients, plus an optional self-declared `plan_id` — null means self-pay. New patients start with both `reliability_score` and `provisional_score` at 100 and an empty `strikes` array."

        Design: Corner/rbac/anonymous_can_register_patient_and_read_directory
        """
        resp = api_client.create_patient(
            {"full_name": "Pat One", "email": "p1@x.com"}, TEST_USERS["anonymous_headers"]
        )
        data = validate_success(resp, 201)
        assert data["reliability_score"] == 100
        assert data["provisional_score"] == 100
        assert data["strikes"] == []

    def test_anonymous_can_read_directory(self, api):
        """PRD §2.1: "A pseudo-role `Any` is used in endpoint definitions to indicate a public read endpoint callable by any declared role, including `Anonymous`; even on `Any` endpoints the two headers are still required."

        Design: Corner/rbac/anonymous_can_register_patient_and_read_directory
        """
        resp = api_client.list_providers(TEST_USERS["anonymous_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 0
        assert data == []


class TestErrorEnvelopeShape:
    def test_error_envelope_fields(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        resp = api_client.get_practice(
            "00000000-0000-0000-0000-000000000000", TEST_USERS["ops_admin_headers"]
        )
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_PRACTICE_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]


class TestSubscriptionPractice:
    def _setup_subscription_practice(self):
        practice = create_and_activate_practice(
            billing_mode="SUBSCRIPTION", subscription_fee_cents=30000
        )
        provider = activate_provider(create_provider(practice["id"])["id"])
        from test_helpers import create_appointment_type, create_slot
        appt_type = create_appointment_type(provider["id"])
        slot = create_slot(provider["id"], "2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")
        patient = create_patient()
        booking = book_slot(slot["id"], patient["id"], appt_type["id"])
        return practice, provider, patient, booking

    def test_no_charge_created_for_subscription_booking(self, api):
        """PRD §3.4: "A `Charge` is created at booking time only when the booking is `ATTRIBUTED` and the practice's `billing_mode` is `PER_BOOKING`. Two variants suppress the charge entirely: a subscription practice is billed its flat monthly fee instead of per booking, and an organic booking is never billed regardless of billing mode."

        Design: Corner/cross_cutting_layers/subscription_practice_bills_flat_fee_not_per_booking
        """
        practice, provider, patient, booking = self._setup_subscription_practice()
        from test_helpers import list_charges_for_booking
        charges = list_charges_for_booking(booking["id"])
        assert len(charges) == 0

    def test_generate_invoices_posts_single_subscription_fee_entry(self, api):
        """PRD §3.7: "For a `SUBSCRIPTION` practice the sweep skips charges entirely: a single `SUBSCRIPTION_FEE` entry is posted for the practice's `subscription_fee_cents`, `charge_count` stays 0, and per-booking charges are never swept."

        Design: Corner/cross_cutting_layers/subscription_practice_bills_flat_fee_not_per_booking
        """
        practice, provider, patient, booking = self._setup_subscription_practice()
        invoice = generate_invoice(practice["id"], "2026-09")
        assert invoice["charge_count"] == 0
        assert invoice["amount_due_cents"] == 30000
        entries = list_ledger_entries_for_invoice(invoice["id"])
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "SUBSCRIPTION_FEE"
        assert entries[0]["amount_cents"] == 30000

    def test_dispute_on_subscription_invoice_returns_402(self, api):
        """PRD §3.7: "Disputing against an invoice belonging to a `SUBSCRIPTION`-mode practice is rejected with `ERR_BILLING_MODE_MISMATCH` after the existence and state checks."

        Design: Corner/consistency_model/error_billing_mode_mismatch_on_subscription_dispute
        """
        practice, provider, patient, booking = self._setup_subscription_practice()
        invoice = generate_invoice(practice["id"], "2026-09")
        resp = api_client.dispute_invoice(
            invoice["id"],
            {"charge_ids": [], "reason": "no charge lines exist"},
            make_practice_staff_headers(practice["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_MODE_MISMATCH)
        invoice_after = get_invoice(invoice["id"])
        assert invoice_after["status"] == "ISSUED"


class TestBookingWriteBackImmediatelyVisible:
    def test_booking_response_carries_computed_fields(self, api):
        """PRD §3.4: "A successful booking is created in `CONFIRMED` status, pins `booked_copay_cents` from the appointment type, flips the slot from `OPEN` to `BOOKED`, and sets the slot's `current_booking_id`."

        Design: Corner/consistency_model/booking_write_back_immediately_visible
        """
        ctx = setup_bookable_practice(copay_cents=10000, slot_windows=[slot_time(48)])
        patient = create_patient()
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "CONFIRMED"
        assert data["attribution_status"] == "ATTRIBUTED"
        assert data["booked_copay_cents"] == 10000

    def test_slot_get_shows_booked_immediately(self, api):
        """PRD §3.4: "A successful booking is created in `CONFIRMED` status, pins `booked_copay_cents` from the appointment type, flips the slot from `OPEN` to `BOOKED`, and sets the slot's `current_booking_id`."

        Design: Corner/consistency_model/booking_write_back_immediately_visible
        """
        from test_helpers import get_slot
        ctx = setup_bookable_practice(copay_cents=10000, slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        slot_after = get_slot(ctx["slots"][0]["id"])
        assert slot_after["status"] == "BOOKED"
        assert slot_after["current_booking_id"] == booking["id"]


class TestSlotInPast:
    def test_slot_start_before_clock_rejected(self, api):
        """PRD §3.2: "A provider account, or the `PracticeStaff` of the owning practice, publishes an individual slot by supplying `start_at` and `end_at` in ISO 8601 UTC; `end_at` must be strictly after `start_at`, and `start_at` must be strictly after the current logical time, otherwise the publish is rejected with `ERR_SLOT_IN_PAST`."

        Design: Corner/validations/slot_create_in_past_rejected
        """
        from test_helpers import set_clock
        ctx = setup_bookable_practice(slot_windows=[])
        set_clock("2026-09-05T00:00:00Z")
        resp = api_client.create_slot(
            ctx["provider"]["id"],
            {"start_at": "2026-09-03T10:00:00Z", "end_at": "2026-09-03T10:30:00Z"},
            make_provider_headers(ctx["provider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST)
