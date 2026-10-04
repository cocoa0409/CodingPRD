"""Breadth tests: entity creation, retrieval, pagination, defaults and the
request-shape checks of the priority ladder."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_enrollment_payload, create_payer_payload, create_provider_payload
from test_helpers.fixtures import create_payer, create_provider, set_clock
from test_helpers.test_users import CLEARINGHOUSE_OPS_HEADERS, make_provider_admin_headers


class TestProviderCreation:
    def test_provider_create_returns_declared_fields_and_starts_onboarding(self, api: ApiClient):
        """PRD §3.1: "New providers start in `ONBOARDING` status with
        `account_balance_cents` at zero and `volume_tier_code` at `TIER_1`."

        Design: Corner/entities/provider_create_returns_all_declared_fields_and_starts_onboarding
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        resp = api.create_provider(
            create_provider_payload(
                legal_name="Onboard Health",
                tax_identification_number="101010101",
                national_provider_identifier="1101010100",
            ),
            CLEARINGHOUSE_OPS_HEADERS,
        )
        provider = validate_success(resp, expected_status=201)
        assert provider["status"] == "ONBOARDING"
        assert provider["version"] == 1
        assert provider["account_balance_cents"] == 0
        assert provider["volume_tier_code"] == "TIER_1"
        assert is_valid_uuid(provider["id"])
        assert is_iso8601_timestamp(provider["created_at"])
        assert is_iso8601_timestamp(provider["updated_at"])
        body = resp.json()
        assert body["meta"].get("api_request_id")
        assert body["meta"].get("api_request_timestamp")


class TestPayerRetrieval:
    def test_payer_get_round_trips_stored_configuration(self, api: ApiClient):
        """PRD §3.2: "Payers are registered by `ClearinghouseOps` with a
        `payer_id_code` — exactly five characters drawn from uppercase letters
        and digits, unique across payers — plus a `display_name` and three
        contractual lead times ... Registration also fixes the `pricing_model`
        ... and, only when the model is `SHARED`, the `shared_provider_pct`".
        PRD §3.2: "A newly registered payer's `connectivity_status` initializes
        to `ONLINE`."

        Design: Corner/entities/payer_get_returns_stored_configuration_unchanged
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        payer = create_payer(
            api,
            payer_id_code="PAYRT",
            display_name="Round Trip Payer",
            claims_lead_time_days=7,
            remittance_lead_time_days=9,
            eligibility_lead_time_seconds=90,
            pricing_model="SHARED",
            shared_provider_pct=0.6,
            monthly_minimum_cents=500,
        )

        fetched = validate_success(api.get_payer(payer["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert fetched["payer_id_code"] == "PAYRT"
        assert fetched["claims_lead_time_days"] == 7
        assert fetched["remittance_lead_time_days"] == 9
        assert fetched["eligibility_lead_time_seconds"] == 90
        assert fetched["shared_provider_pct"] == 0.6
        assert fetched["monthly_minimum_cents"] == 500
        assert fetched["connectivity_status"] == "ONLINE"


class TestProviderPagination:
    def test_providers_list_paginates_with_total_count_and_has_more(self, api: ApiClient):
        """PRD §2.3: "`limit` controls the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        controls how many items are skipped; it defaults to 0 ... The `meta`
        block of a list response carries exactly four pagination fields:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/providers_list_paginates_with_total_count_and_has_more
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        create_provider(
            api,
            legal_name="P1",
            tax_identification_number="111111111",
            national_provider_identifier="1111111112",
        )
        create_provider(
            api,
            legal_name="P2",
            tax_identification_number="222222222",
            national_provider_identifier="1222222220",
            billing_model="PAYER_FUNDED",
        )
        create_provider(
            api,
            legal_name="P3",
            tax_identification_number="333333333",
            national_provider_identifier="1333333338",
            billing_model="HYBRID",
        )

        first_page, meta = validate_paginated(
            api.list_providers(CLEARINGHOUSE_OPS_HEADERS, params={"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        second_page, meta = validate_paginated(
            api.list_providers(CLEARINGHOUSE_OPS_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        default_page, meta = validate_paginated(api.list_providers(CLEARINGHOUSE_OPS_HEADERS))
        assert len(default_page) == 3


class TestClaimNotFound:
    def test_unknown_claim_id_returns_claim_not_found(self, api: ApiClient):
        """PRD §2.6: "a claim submission naming a `payer_id` or
        `submitter_credential_id` that does not resolve is rejected with the
        corresponding not-found error (`ERR_PAYER_NOT_FOUND`,
        `ERR_CREDENTIAL_NOT_FOUND`, and so on through `ERR_ENROLLMENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND` ...), each HTTP 404."

        Design: Corner/entities/claim_get_with_unknown_id_returns_claim_not_found
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        resp = api.get_claim(NON_EXISTENT_UUID, CLEARINGHOUSE_OPS_HEADERS)
        error_data = validate_error(resp, ApiErrorId.CLAIM_NOT_FOUND)
        assert error_data.get("message"), "error responses carry a human-readable message"
        assert resp.json()["response_type"] == "error"


class TestRequiredFieldsAndDefaults:
    def test_provider_create_missing_tin_returns_invalid_request(self, api: ApiClient):
        """PRD §3.1: "A provider's life begins when a `ClearinghouseOps`
        operator registers it with its `legal_name`,
        `tax_identification_number`, `national_provider_identifier`, and
        `billing_model` ... A registration failing any of these is rejected
        with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/provider_create_missing_tin_returns_invalid_request
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        resp = api.create_provider(
            {
                "legal_name": "No TIN",
                "national_provider_identifier": "1101010100",
                "billing_model": "PROVIDER_FUNDED",
            },
            CLEARINGHOUSE_OPS_HEADERS,
        )
        validate_error(resp, ApiErrorId.INVALID_REQUEST)

        rows, meta = validate_paginated(api.list_providers(CLEARINGHOUSE_OPS_HEADERS))
        assert len(rows) == 0

    def test_payer_create_omitting_monthly_minimum_defaults_to_zero(self, api: ApiClient):
        """PRD §3.2: "Provider-funded payers may additionally carry a
        `monthly_minimum_cents` floor (defaulting to 0) that §3.8's billing
        math enforces."

        Design: Corner/entities/payer_create_omitting_monthly_minimum_defaults_to_zero
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        # The factory supplies monthly_minimum_cents; drop it to test the default.
        payload = create_payer_payload(payer_id_code="PAYDF", display_name="Default Payer")
        payload.pop("monthly_minimum_cents", None)
        resp = api.create_payer(payload, CLEARINGHOUSE_OPS_HEADERS)
        payer = validate_success(resp, expected_status=201)
        assert payer["monthly_minimum_cents"] == 0

    def test_payer_create_out_of_enum_pricing_model_rejected(self, api: ApiClient):
        """PRD §2.7: "Format and uniqueness — TIN shape, NPI shape and check
        digit, payer code shape, enum membership, effective-window ordering on
        edit rules; violations yield `ERR_INVALID_REQUEST`." PRD §3.2 fixes
        `pricing_model` to "`PAYER_FUNDED`, `PROVIDER_FUNDED`, or `SHARED`".

        Design: Corner/entities/payer_create_with_out_of_enum_pricing_model_returns_invalid_request
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        payload = create_payer_payload(payer_id_code="PAYEN", pricing_model="CAPITATED")
        resp = api.create_payer(payload, CLEARINGHOUSE_OPS_HEADERS)
        validate_error(resp, ApiErrorId.INVALID_REQUEST)

        rows, meta = validate_paginated(api.list_payers(CLEARINGHOUSE_OPS_HEADERS))
        assert len(rows) == 0


class TestPathResolution:
    def test_enrollment_create_under_unknown_provider_returns_provider_not_found(
        self, api: ApiClient
    ):
        """PRD §2.6: "Endpoints whose paths contain multiple identifiers
        validate them left to right ... the first segment that fails to resolve
        determines the error — for example, a credential lookup under a
        nonexistent provider returns `ERR_PROVIDER_NOT_FOUND`."

        Design: Corner/entities/enrollment_create_requires_provider_in_path_to_exist
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        payer = create_payer(api, payer_id_code="PAYPT", display_name="Parent Payer")

        resp = api.create_enrollment(
            NON_EXISTENT_UUID,
            create_enrollment_payload(payer_id=payer["id"], transaction_type="CLAIMS_837"),
            make_provider_admin_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.PROVIDER_NOT_FOUND)
