"""Licensing regimes, sellers, buyers and the logical clock (PRD §2.5, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_instant_equals


class TestStateLicenseProfileRegistry:
    """PRD §3.1 — the licensing regime of the state a route runs in."""

    def test_create_profile_echoes_every_declared_input(self, api, platform_admin_headers):
        """`required_permit_types` is a non-empty list drawn without repetition from
        `PESTICIDE_APPLICATOR`, `CONTRACTOR` and `BUSINESS_TAX`, `reciprocity_states`
        holds zero or more two-letter codes, `transfer_processing_days` is the length in
        days of the window a filed application occupies at the regulator, `cooling_off_days`
        is how long a rejected applicant must wait before re-filing, and
        `provisional_operation_allowed` records whether a buyer holding no licence
        anywhere may nevertheless file here. `version` is an integer that starts at 1.

        Design: Corner/entities/create_state_license_profile_returns_all_fields
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")

        response = api.create_state_license_profile(
            f.state_license_profile_payload(), platform_admin_headers)
        data = validate_success(response, 201)

        assert data["state_code"] == "AZ"
        assert data["required_permit_types"] == ["PESTICIDE_APPLICATOR", "BUSINESS_TAX"]
        assert data["reciprocity_states"] == ["NV"]
        assert data["transfer_processing_days"] == 21
        assert data["cooling_off_days"] == 14
        assert data["provisional_operation_allowed"] is False
        assert data["version"] == 1
        assert is_valid_uuid(data["id"]), f"id must be a UUID with no prefix: {data['id']}"
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_second_profile_for_the_same_state_is_refused(self, api, platform_admin_headers):
        """A `StateLicenseProfile` is keyed on `state_code`, exactly two uppercase letters,
        and no two profiles may describe the same state — a second seed for a state that
        already has one is refused with `ERR_DUPLICATE_STATE_PROFILE`.

        Design: Corner/validations/second_profile_for_the_same_state_code_rejected
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        first = fx.seed_az_profile(api)

        clashing = f.state_license_profile_payload(
            required_permit_types=["CONTRACTOR"], reciprocity_states=[],
            transfer_processing_days=180, cooling_off_days=0,
            provisional_operation_allowed=True)
        validate_error(api.create_state_license_profile(clashing, platform_admin_headers),
                       ApiErrorId.ERR_DUPLICATE_STATE_PROFILE, 409)

        nevada = f.state_license_profile_payload(
            state_code="NV", reciprocity_states=["AZ"])
        validate_success(api.create_state_license_profile(nevada, platform_admin_headers), 201)

        rows, meta = validate_paginated(api.list_state_license_profiles(platform_admin_headers))
        assert meta["total_count"] == 2
        stored = validate_success(api.get_state_license_profile(first["id"],
                                                               platform_admin_headers))
        assert stored["transfer_processing_days"] == 21
        assert stored["required_permit_types"] == ["PESTICIDE_APPLICATOR", "BUSINESS_TAX"]

    def test_out_of_range_numbers_and_unknown_enum_members_are_refused(
            self, api, platform_admin_headers, broker_headers):
        """`ERR_VALIDATION` — request-body shape: a required field is missing, a field has
        the wrong JSON type, an enum value is outside its declared set, an amount field
        ending in `_cents` is not an integer of at least zero, a date or instant fails to
        parse, or a scalar breaches a declared numeric range.

        Design: Corner/entities/state_profile_out_of_range_and_bad_enum_values_rejected
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")

        validate_error(
            api.create_state_license_profile(
                f.state_license_profile_payload(transfer_processing_days=0),
                platform_admin_headers),
            ApiErrorId.ERR_VALIDATION, 400)
        validate_error(
            api.create_state_license_profile(
                f.state_license_profile_payload(required_permit_types=["POOL_HEATER"]),
                platform_admin_headers),
            ApiErrorId.ERR_VALIDATION, 400)
        validate_success(
            api.create_state_license_profile(
                f.state_license_profile_payload(transfer_processing_days=1,
                                                cooling_off_days=0),
                platform_admin_headers),
            201)

        seller = fx.seed_seller(api)
        fx.seed_buyer(api)
        listing = fx.seed_listing(api, seller["id"])

        validate_error(
            api.create_service_account(
                f.service_account_payload(listing["id"], route_day="SUN"), broker_headers),
            ApiErrorId.ERR_VALIDATION, 400)
        validate_error(
            api.create_service_account(
                f.service_account_payload(listing["id"], avg_monthly_chemical_cents=-100),
                broker_headers),
            ApiErrorId.ERR_VALIDATION, 400)

        rows, meta = validate_paginated(
            api.list_service_accounts(broker_headers, {"listing_id": listing["id"]}))
        assert meta["total_count"] == 0
        assert rows == []


class TestPartyRegistration:
    """PRD §3.1 — route sellers and route buyers."""

    def test_seller_creation_mints_its_own_identity_and_status(self, api, broker_headers):
        """A newly registered seller's `status` is `ACTIVE` and its `suspension_reason_code`
        is null. Every resource in this API is identified by `id`, a server-minted UUID
        string. Identifiers carry no type prefix and are never supplied by the client.

        Design: Corner/entities/create_seller_system_fields_generated_input_ignored
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")

        injected = f.seller_payload(
            id="66666666-6666-4666-8666-666666666666",
            version=9,
            status="SUSPENDED",
            suspension_reason_code="LICENSE_LAPSED")
        data = validate_success(api.create_seller(injected, broker_headers), 201)

        assert data["status"] == "ACTIVE"
        assert data["suspension_reason_code"] is None
        assert data["version"] == 1
        assert data["id"] != "66666666-6666-4666-8666-666666666666"
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert data["legal_name"] == "Sun Valley Pools LLC"
        assert data["license_number"] == "AZ-PA-1001"

    def test_qualification_is_decided_once_and_a_rejected_buyer_cannot_bid(
            self, api, broker_headers):
        """Both `APPROVED` and `REJECTED` are terminal — only a buyer still in `PENDING`
        may be decided, and a second attempt is refused with
        `ERR_INVALID_BUYER_TRANSITION` rather than silently re-decided. An unqualified
        buyer can neither open a deal nor have one accepted, which surfaces as
        `ERR_BUYER_NOT_QUALIFIED`.

        Design: Corner/endpoints/qualify_is_a_one_shot_decision_and_a_rejected_buyer_cannot_bid
        """
        ctx = fx.listed_route(api)
        pending_buyer = fx.seed_buyer(api, decision=None)
        assert pending_buyer["qualification_status"] == "PENDING"

        denied = validate_success(
            api.qualify_buyer(pending_buyer["id"], f.qualify_buyer_payload("DENY"),
                              broker_headers))
        assert denied["qualification_status"] == "REJECTED"
        assert denied["qualified_on"] is None

        validate_error(
            api.qualify_buyer(pending_buyer["id"], f.qualify_buyer_payload("APPROVE"),
                              broker_headers),
            ApiErrorId.ERR_INVALID_BUYER_TRANSITION, 409)

        stored = validate_success(api.get_buyer(pending_buyer["id"], broker_headers))
        assert stored["qualification_status"] == "REJECTED"
        assert stored["qualified_on"] is None

        validate_error(
            api.create_deal(f.deal_payload(ctx["listing"]["id"], pending_buyer["id"]),
                            broker_headers),
            ApiErrorId.ERR_BUYER_NOT_QUALIFIED, 422)

        rows, meta = validate_paginated(
            api.list_deals(broker_headers, {"listing_id": ctx["listing"]["id"]}))
        assert meta["total_count"] == 0


class TestLogicalClock:
    """PRD §2.5 — the deterministic logical clock."""

    def test_clock_stands_still_or_moves_forward_but_never_back(
            self, api, platform_admin_headers):
        """The clock may only move forward or stand still: a requested `current_utc` at or
        after the present reading is accepted, setting it to exactly its present value
        succeeds as a no-op, and any earlier instant is refused with `ERR_CLOCK_REWIND`.

        Design: Corner/validations/clock_may_not_move_backwards_but_may_be_set_to_the_same_instant
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")

        validate_error(
            api.set_clock(f.clock_payload("2026-07-31T23:59:59Z"), platform_admin_headers),
            ApiErrorId.ERR_CLOCK_REWIND, 422)
        unchanged = validate_success(api.get_clock(platform_admin_headers))
        assert_instant_equals(unchanged["current_utc"], "2026-08-01T00:00:00Z", "current_utc")

        no_op = validate_success(
            api.set_clock(f.clock_payload("2026-08-01T00:00:00Z"), platform_admin_headers))
        assert_instant_equals(no_op["current_utc"], "2026-08-01T00:00:00Z", "current_utc")
        assert_instant_equals(no_op["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc")

        forward = validate_success(
            api.set_clock(f.clock_payload("2026-08-02T00:00:00Z"), platform_admin_headers))
        assert_instant_equals(forward["current_utc"], "2026-08-02T00:00:00Z", "current_utc")
        assert_instant_equals(forward["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc")

        final = validate_success(api.get_clock(platform_admin_headers))
        assert_instant_equals(final["current_utc"], "2026-08-02T00:00:00Z", "current_utc")


class TestNotFoundIsPerEntityFamily:
    """PRD §2.9 — the not-found checks are numbered one per entity family."""

    def test_each_single_row_read_reports_its_own_family_not_found_error(
            self, api, broker_headers):
        """`ERR_LISTING_NOT_FOUND` — a route listing identifier in the path or body resolves
        to nothing. `ERR_ACCOUNT_NOT_FOUND` — a service account identifier in the path or
        body resolves to nothing. `ERR_PARTY_NOT_FOUND` — a seller or buyer identifier in
        a path or body resolves to nothing.

        Design: Corner/entities/get_by_unknown_id_returns_the_entity_specific_not_found_error
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        unknown = NON_EXISTENT_UUID

        probes = [
            (api.get_route_listing(unknown, broker_headers), ApiErrorId.ERR_LISTING_NOT_FOUND),
            (api.get_service_account(unknown, broker_headers), ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
            (api.get_deal(unknown, broker_headers), ApiErrorId.ERR_DEAL_NOT_FOUND),
            (api.get_escrow_account(unknown, broker_headers), ApiErrorId.ERR_ESCROW_NOT_FOUND),
            (api.get_clawback_settlement(unknown, broker_headers),
             ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
            (api.get_seller(unknown, broker_headers), ApiErrorId.ERR_PARTY_NOT_FOUND),
            (api.get_buyer(unknown, broker_headers), ApiErrorId.ERR_PARTY_NOT_FOUND),
            (api.get_state_license_profile(unknown, broker_headers),
             ApiErrorId.ERR_LICENSE_PROFILE_NOT_FOUND),
            (api.get_license_transfer(unknown, broker_headers),
             ApiErrorId.ERR_LICENSE_TRANSFER_NOT_FOUND),
            (api.get_route_valuation(unknown, broker_headers),
             ApiErrorId.ERR_VALUATION_NOT_FOUND),
            (api.get_billing_history_record(unknown, broker_headers),
             ApiErrorId.ERR_BILLING_RECORD_NOT_FOUND),
            (api.get_attrition_event(unknown, broker_headers),
             ApiErrorId.ERR_ATTRITION_EVENT_NOT_FOUND),
        ]
        for response, expected in probes:
            validate_error(response, expected, 404)
            assert response.json()["response_type"] == "error"


class TestOperatorSurfaceIsExclusive:
    """PRD §2.1 and §4 — the `PlatformAdmin` operator surface."""

    def test_broker_cannot_drive_the_clock_seed_a_regime_or_suspend_a_seller(
            self, api, platform_admin_headers, broker_headers):
        """There is no hierarchical override anywhere in this API. If the role is
        recognised but is not one of the roles authorised for the endpoint being called,
        the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/rbac/platform_admin_exclusive_clock_and_registry_writes_are_forbidden_to_brokers
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)

        validate_error(
            api.set_clock(f.clock_payload("2026-09-01T00:00:00Z"), broker_headers),
            ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(
            api.create_state_license_profile(
                f.state_license_profile_payload(state_code="NV"), broker_headers),
            ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(
            api.suspend_seller(seller["id"], f.suspend_seller_payload(), broker_headers),
            ApiErrorId.ERR_UNAUTHORIZED, 403)

        validate_success(
            api.create_seller(f.seller_payload(legal_name="Cactus Clear Pools Inc",
                                               license_number="AZ-PA-2002"), broker_headers),
            201)

        clock = validate_success(api.get_clock(broker_headers))
        assert_instant_equals(clock["current_utc"], "2026-08-01T00:00:00Z", "current_utc")

        stored = validate_success(api.get_seller(seller["id"], broker_headers))
        assert stored["status"] == "ACTIVE"
        assert stored["suspension_reason_code"] is None
