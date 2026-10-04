"""Corner tests for entity creation defaults, required fields, computed fields,
pagination envelope, and audit-event immutability."""
from __future__ import annotations

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_standard_service_period,
    assert_veteran,
    create_coe_request_payload,
    create_loan_payload,
    create_service_period_payload,
    create_veteran_payload,
    get_entitlement_account,
    setup_veteran_with_issued_coe,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVeteranCreateDefaults:
    def test_veteran_create_defaults_and_account_cascade_readback(self, api):
        """PRD §3.1: "An optional `is_surviving_spouse` flag, defaulting to false,
        marks an eligible surviving spouse applying in place of the veteran.
        Registration cascade-creates the veteran's 1:1 `EntitlementAccount` with
        the fixed constants described in §2.6"
        PRD §2.6: "The account holds two system-fixed constants:
        `basic_entitlement_cents` of 3,600,000 cents (the fixed basic entitlement
        of $36,000.00) and `county_limit_cents` of 76,655,000 cents"

        Design: Corner/entities/veteran_create_defaults_and_account_cascade
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload()), expected_status=201
        )
        assert_veteran(veteran)
        assert veteran["is_surviving_spouse"] is False
        assert veteran["total_qualifying_service_days"] == 0
        assert veteran["has_issued_coe"] is False
        assert veteran["version"] == 1

        account = get_entitlement_account(veteran["id"])
        assert account["basic_entitlement_cents"] == 3600000
        assert account["remaining_with_bonus_cents"] == 19163750

    def test_veteran_create_defaults_account_constants(self, api):
        """PRD §2.6: "The base-only variant, `remaining_base_cents`, is the
        greater of zero and the basic entitlement minus the entitlement in use"
        and "The with-bonus variant, `remaining_with_bonus_cents`, is the greater
        of zero and one quarter of the county limit minus the entitlement in use"

        Design: Corner/entities/veteran_create_defaults_and_account_cascade
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(is_surviving_spouse=True)),
            expected_status=201,
        )
        assert veteran["is_surviving_spouse"] is True
        account = get_entitlement_account(veteran["id"])
        assert account["county_limit_cents"] == 76655000
        assert account["total_charged_cents"] == 0
        assert account["total_restored_cents"] == 0
        assert account["remaining_base_cents"] == 3600000
        assert account["remaining_with_bonus_cents"] == 19163750


class TestVeteranValidation:
    def test_veteran_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.11: "Request-shape validation is next — a missing required
        field, a mistyped value, or an `ssn_last4` that is not exactly four
        digits yields `ERR_VALIDATION`"

        Design: Corner/entities/veteran_create_missing_required_field_returns_invalid_request
        """
        payload = {
            "full_name": "V Miss",
            "service_category": "REGULAR_MILITARY",
            "character_of_discharge": "HONORABLE",
            "receives_disability_compensation": False,
        }
        resp = api.create_veteran(payload)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_veteran_create_invalid_enum_rejected(self, api):
        """PRD §2.11: "an enum field carrying a value outside its declared
        membership yields `ERR_INVALID_ENUM`"

        Design: Corner/entities/veteran_create_invalid_enum_rejected
        """
        payload = create_veteran_payload(character_of_discharge="EXEMPLARY")
        resp = api.create_veteran(payload)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, expected_status=400)

    def test_veteran_get_not_found_returns_404(self, api):
        """PRD §2.8: "rejects the request immediately with the not-found error
        corresponding to the first segment that does not resolve:
        `ERR_VETERAN_NOT_FOUND` for an unresolvable veteran id"

        Design: Corner/entities/veteran_get_not_found_returns_404
        """
        resp = api.get_veteran(NON_EXISTENT_UUID)
        validate_error(resp, ApiErrorId.ERR_VETERAN_NOT_FOUND, expected_status=404)


class TestServicePeriodListing:
    def test_service_period_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter bounds the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips that many items from the start of the result set and
        defaults to 0."
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by `created_at` in ascending order."

        Design: Corner/entities/service_period_list_pagination_envelope
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Page")),
            expected_status=201,
        )
        api.create_service_period(
            veteran["id"],
            create_service_period_payload(
                branch="ARMY", start_date="2010-01-01", end_date="2011-01-01",
            ),
        )
        api.create_service_period(
            veteran["id"],
            create_service_period_payload(
                branch="ARMY", start_date="2012-01-01", end_date="2013-01-01",
            ),
        )
        api.create_service_period(
            veteran["id"],
            create_service_period_payload(
                branch="NAVY", start_date="2014-01-01", end_date="2015-01-01",
                discharge_character="GENERAL",
            ),
        )
        data, meta = validate_paginated(
            api.list_service_periods(veteran["id"], params={"limit": 2, "offset": 2})
        )
        assert len(data) == 1, f"expected 1 entry at offset 2 of 3, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert data[0]["branch"] == "NAVY"
        assert data[0]["discharge_character"] == "GENERAL"


class TestLoanComputedFields:
    def test_loan_computed_fields_ignore_client_input(self, api):
        """PRD §3.3: "The `loan_amount_cents` is the purchase price minus the
        down payment."
        PRD §3.3: "The `loan_use` is `FIRST_USE` when the borrower's
        `charged_loan_count` is zero at creation and `SUBSEQUENT_USE` otherwise"
        PRD §3.3: "The `down_payment_pct` is the down payment divided by the
        purchase price, expressed as a percentage rounded half up to four
        decimal places."

        Design: Corner/entities/loan_computed_fields_ignore_client_input
        """
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Comp"})
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(
                    ctx["coe"]["id"],
                    purchase_price_cents=25000000,
                    down_payment_cents=5000000,
                ),
            ),
            expected_status=201,
        )
        assert loan["loan_amount_cents"] == 20000000
        assert loan["loan_use"] == "FIRST_USE"
        assert float(loan["down_payment_pct"]) == 20.0000


class TestServicePeriodQualifyingDays:
    def test_service_period_qualifying_days_inclusive_endpoints(self, api):
        """PRD §3.1: "A period's `qualifying_days` is computed at creation: when
        the period's `discharge_character` is `HONORABLE` or `GENERAL`, it is the
        number of days from `start_date` through `end_date` inclusive (the
        difference in days plus one); for any other discharge character it is
        zero."

        Design: Corner/entities/service_period_qualifying_days_inclusive_endpoints
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Days")),
            expected_status=201,
        )
        first = validate_success(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    start_date="2019-03-01", end_date="2019-06-30",
                ),
            ),
            expected_status=201,
        )
        assert first["qualifying_days"] == 122

        second = validate_success(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    start_date="2020-01-01", end_date="2020-12-31",
                    discharge_character="DISHONORABLE",
                ),
            ),
            expected_status=201,
        )
        assert second["qualifying_days"] == 0

    def test_total_qualifying_service_days_excludes_dishonorable(self, api):
        """PRD §3.1: "The veteran's `total_qualifying_service_days` is the sum of
        `qualifying_days` across all of the veteran's service periods, recomputed
        whenever a period is added."

        Design: Corner/entities/service_period_qualifying_days_inclusive_endpoints
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Days2")),
            expected_status=201,
        )
        api.create_service_period(
            veteran["id"],
            create_service_period_payload(
                start_date="2019-03-01", end_date="2019-06-30",
            ),
        )
        api.create_service_period(
            veteran["id"],
            create_service_period_payload(
                start_date="2020-01-01", end_date="2020-12-31",
                discharge_character="DISHONORABLE",
            ),
        )
        readback = validate_success(api.get_veteran(veteran["id"]))
        assert readback["total_qualifying_service_days"] == 122


class TestAuditEventImmutability:
    def test_audit_event_immutable_no_version(self, api):
        """PRD §2.4: "`AuditEvent` is an append-only record carrying only `id`
        and `created_at`; both `updated_at` and `version` are absent on audit
        events, because an audit record, once written, is never mutated."
        PRD §2.10: "Each audit event records the `entity_type` and `entity_id`
        of the mutated resource, the `action` (the endpoint action name, such as
        issue, deny, close, or refund), the `actor_role` taken from the caller's
        `X-User-Role` header, the `actor_user_id` taken from `X-User-ID`"

        Design: Corner/entities/audit_event_immutable_no_version
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Aud")),
            expected_status=201,
        )
        events, _meta = validate_paginated(
            api.list_audit_events(params={"entity_id": veteran["id"]})
        )
        assert len(events) == 1, f"expected exactly 1 audit event, got {len(events)}"
        event = events[0]
        assert event["id"]
        assert event["created_at"]
        assert "version" not in event
        assert "updated_at" not in event
        assert event["actor_role"] == "LoanOfficer"
        assert event["actor_user_id"] == "lo-1"
