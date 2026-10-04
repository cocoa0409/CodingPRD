"""Tests for practice/provider onboarding: defaults, schema rejection, 404s,
system-field handling, the bookability derivation, and the provider/practice
state machines (PRD §3.1 and §2.7).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_practice,
    assert_provider,
    create_practice,
    create_provider,
    get_provider,
    make_practice_staff_headers,
    make_provider_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    activate_provider,
    create_active_practice_with_provider,
    create_and_activate_practice,
)


class TestPracticeCreateAppliesDefaults:
    def test_optional_fields_default(self, api):
        """PRD §3.1: "The practice's `billing_mode` is `PER_BOOKING` unless the operator passes `SUBSCRIPTION` at creation; `subscription_fee_cents` carries a default of 30000 (a flat monthly fee of 300.00 in the subscription currency unit) and is only meaningful in `SUBSCRIPTION` mode. Two scheduling thresholds default on the practice: `new_patient_lead_time_hours` defaults to 24 hours and `existing_patient_lead_time_hours` defaults to 4 hours. A new practice starts in `DRAFT` status."

        Design: Corner/entities/practice_create_applies_defaults
        """
        practice = create_practice()
        assert_practice(practice)
        assert practice["billing_mode"] == "PER_BOOKING"
        assert practice["new_patient_lead_time_hours"] == 24
        assert practice["existing_patient_lead_time_hours"] == 4
        assert practice["subscription_fee_cents"] == 30000
        assert practice["status"] == "DRAFT"

    def test_version_starts_at_one_and_fields_visible_on_get(self, api):
        """PRD §2.4: "`version` is an integer that starts at creation and increments by 1 on every mutation of the resource."
        PRD §3.1: "A new practice starts in `DRAFT` status."

        Design: Corner/entities/practice_create_applies_defaults
        """
        practice = create_practice()
        assert practice["version"] == 1
        resp = api_client.get_practice(practice["id"], TEST_USERS["ops_admin_headers"])
        data = validate_success(resp)
        assert data["billing_mode"] == "PER_BOOKING"
        assert data["status"] == "DRAFT"


class TestPracticeCreateSchemaValidation:
    def test_missing_required_name_returns_400(self, api):
        """PRD §2.8: "Request schema.** Required fields present, types correct, enum members valid, `rating` within its 1-to-5 range, `end_at` strictly after `start_at`, and attestation `effective_to` strictly after `effective_from` (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/practice_create_missing_required_name_returns_400
        """
        resp = api_client.create_practice({"timezone": "America/New_York"}, TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_enum_billing_mode_rejected(self, api):
        """PRD §2.8: "Request schema.** Required fields present, types correct, enum members valid, `rating` within its 1-to-5 range, `end_at` strictly after `start_at`, and attestation `effective_to` strictly after `effective_from` (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/practice_create_invalid_enum_billing_mode_rejected
        """
        resp = api_client.create_practice(
            {"name": "P1", "timezone": "America/New_York", "billing_mode": "GOLD"},
            TEST_USERS["ops_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPracticeGetNotFound:
    def test_get_nonexistent_practice_returns_404(self, api):
        """PRD §2.7: "The first identifier that does not resolve to an existing resource short-circuits the request with the corresponding 404 error (`ERR_PRACTICE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`, or `ERR_TYPE_NOT_FOUND`)."

        Design: Corner/entities/practice_get_not_found_returns_404
        """
        resp = api_client.get_practice(NON_EXISTENT_UUID, TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_FOUND)


class TestProviderCreateSystemFields:
    def test_client_supplied_id_and_version_ignored(self, api):
        """PRD §2.4: "`id` is a server-minted UUID string with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at creation and increments by 1 on every mutation of the resource."
        PRD §3.1: "A new provider starts in `PENDING` status, with `insurance_mismatch_count` at 0."

        Design: Corner/entities/provider_create_system_fields_input_ignored
        """
        practice = create_practice()
        resp = api_client.create_provider(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "version": 99,
                "practice_id": practice["id"],
                "display_name": "Dr A",
                "specialty": "DERM",
            },
            make_practice_staff_headers(practice["id"]),
        )
        data = validate_success(resp, 201)
        assert data["id"] != "11111111-1111-1111-1111-111111111111", (
            "the server must mint its own id"
        )
        assert data["version"] == 1
        assert data["status"] == "PENDING"


class TestBookableInDirectoryDerivation:
    def test_input_ignored_and_tracks_state_changes(self, api):
        """PRD §3.1: "The derived field `bookable_in_directory` on a provider is true exactly when the provider's own `status` is `ACTIVE` and the owning practice's `status` is `ACTIVE`. It is recomputed on every provider status change and on every practice status change, which is why practice activation, suspension, and reinstatement each re-evaluate every provider of the practice."

        Design: Corner/entities/provider_bookable_in_directory_input_ignored
        """
        practice = create_and_activate_practice()
        resp = api_client.create_provider(
            {
                "practice_id": practice["id"],
                "display_name": "Dr A",
                "specialty": "DERM",
                "bookable_in_directory": True,
            },
            make_practice_staff_headers(practice["id"]),
        )
        provider = validate_success(resp, 201)
        assert provider["bookable_in_directory"] is False, (
            "PENDING provider is not bookable regardless of the client-supplied value"
        )
        activate_provider(provider["id"])
        after_activate = get_provider(provider["id"])
        assert after_activate["bookable_in_directory"] is True
        api_client.suspend_practice(practice["id"], TEST_USERS["ops_admin_headers"])
        after_suspend = get_provider(provider["id"])
        assert after_suspend["bookable_in_directory"] is False

    def test_bookable_true_requires_both_active(self, api):
        """PRD §3.1: "The derived field `bookable_in_directory` on a provider is true exactly when the provider's own `status` is `ACTIVE` and the owning practice's `status` is `ACTIVE`."

        Design: Corner/entities/provider_bookable_in_directory_input_ignored
        """
        practice, provider = create_active_practice_with_provider()
        prov = get_provider(provider["id"])
        assert prov["status"] == "ACTIVE"
        assert prov["bookable_in_directory"] is True


class TestSlotCreateUnderWrongProvider:
    def test_slot_create_with_nonexistent_provider_returns_404(self, api):
        """PRD §2.7: "The first identifier that does not resolve to an existing resource short-circuits the request with the corresponding 404 error (`ERR_PRACTICE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`, or `ERR_TYPE_NOT_FOUND`). No later check runs once an existence check has failed."

        Design: Corner/entities/slot_create_with_wrong_path_provider_not_found
        """
        resp = api_client.create_slot(
            NON_EXISTENT_UUID,
            {"start_at": "2026-09-03T10:00:00Z", "end_at": "2026-09-03T10:30:00Z"},
            make_provider_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND)


class TestProviderInitialStatePending:
    def test_pending_provider_cannot_publish_slot(self, api):
        """PRD §3.1: "A new provider starts in `PENDING` status, with `insurance_mismatch_count` at 0."
        PRD §3.2: "Publication requires the provider to be bookable — the provider `ACTIVE` (`ERR_PROVIDER_NOT_BOOKABLE` when not) and the owning practice `ACTIVE` (`ERR_PRACTICE_NOT_ACTIVE` when not), with the provider check evaluated before the practice check."

        Design: Corner/state_machines/provider_initial_state_pending
        """
        practice = create_and_activate_practice()
        provider = create_provider(practice["id"])
        assert provider["status"] == "PENDING"
        resp = api_client.create_slot(
            provider["id"],
            {"start_at": "2026-09-03T10:00:00Z", "end_at": "2026-09-03T10:30:00Z"},
            make_provider_headers(provider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_BOOKABLE)


class TestPracticeStateMachine:
    def test_activate_from_active_rejected(self, api):
        """PRD §2.8: "State-machine admissibility.** The target entity must be in a state from which the requested transition exists — this includes a slot being `OPEN` for booking (`ERR_SLOT_NOT_OPEN`), a booking being `CONFIRMED` for cancellation (`ERR_BOOKING_NOT_CANCELLABLE`), an invoice being `ISSUED` for dispute (`ERR_INVOICE_NOT_DISPUTABLE`) or for payment with a positive balance (`ERR_INVOICE_NOT_PAYABLE`), a complaint being `OPEN` for a response or `UNDER_REVIEW` for resolution (`ERR_COMPLAINT_NOT_OPEN`), and the generic `ERR_INVALID_STATE` for all other illegal transitions."

        Design: Corner/state_machines/practice_activate_from_active_rejected
        """
        practice = create_and_activate_practice()
        resp = api_client.activate_practice(practice["id"], TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_suspend_reinstate_cycle(self, api):
        """PRD §3.1: "Both provider and practice support a suspension cycle: `ACTIVE` to `SUSPENDED`, and `SUSPENDED` back to `ACTIVE` via reinstatement — which for a provider again requires the owning practice to be `ACTIVE`."

        Design: Corner/state_machines/practice_suspend_reinstate_cycle
        """
        practice = create_and_activate_practice()
        r1 = api_client.suspend_practice(practice["id"], TEST_USERS["ops_admin_headers"])
        d1 = validate_success(r1)
        assert d1["status"] == "SUSPENDED"
        r2 = api_client.reinstate_practice(practice["id"], TEST_USERS["ops_admin_headers"])
        d2 = validate_success(r2)
        assert d2["status"] == "ACTIVE"


class TestProviderStateMachine:
    def test_delist_terminal_lockdown(self, api):
        """PRD §3.1: "Suspension and delisting of a practice are operator actions; delisting is permitted from either `ACTIVE` or `SUSPENDED` and moves the practice to terminal `DELISTED`."
        PRD §2.8: "State-machine admissibility.** The target entity must be in a state from which the requested transition exists — this includes a slot being `OPEN` for booking (`ERR_SLOT_NOT_OPEN`), a booking being `CONFIRMED` for cancellation (`ERR_BOOKING_NOT_CANCELLABLE`), an invoice being `ISSUED` for dispute (`ERR_INVOICE_NOT_DISPUTABLE`) or for payment with a positive balance (`ERR_INVOICE_NOT_PAYABLE`), a complaint being `OPEN` for a response or `UNDER_REVIEW` for resolution (`ERR_COMPLAINT_NOT_OPEN`), and the generic `ERR_INVALID_STATE` for all other illegal transitions."

        Design: Corner/state_machines/provider_delist_terminal_lockdown_rejected
        """
        practice, provider = create_active_practice_with_provider()
        api_client.delist_provider(provider["id"], TEST_USERS["ops_admin_headers"])
        resp = api_client.reinstate_provider(provider["id"], TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_activate_blocked_when_practice_suspended(self, api):
        """PRD §3.1: "Provider activation additionally requires the owning practice to be `ACTIVE`; otherwise the request is rejected with `ERR_PRACTICE_NOT_ACTIVE`."

        Design: Corner/state_machines/provider_activate_blocked_when_practice_suspended
        """
        practice = create_and_activate_practice()
        provider = create_provider(practice["id"])
        api_client.suspend_practice(practice["id"], TEST_USERS["ops_admin_headers"])
        resp = api_client.activate_provider(provider["id"], TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_ACTIVE)
        prov_after = get_provider(provider["id"])
        assert prov_after["status"] == "PENDING"
