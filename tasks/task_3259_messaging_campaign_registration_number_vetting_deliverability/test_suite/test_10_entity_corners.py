"""Entity creation corners: defaults, computed fields, not-found
responses, and the list pagination envelope.
"""

from test_helpers import NON_EXISTENT_UUID, validate_error, validate_paginated
from test_helpers.api_errors import ERR_NOT_FOUND, ERR_VALIDATION
from test_helpers.assertions import assert_account, assert_brand, assert_consent_record
from test_helpers.factories import account_payload, brand_payload
from test_helpers.fixtures import (
    create_account,
    create_brand,
    set_clock,
)
from test_helpers.test_users import ADMIN, BRAND_MANAGER


class TestAccountCreationDefaults:
    def test_new_account_is_active_with_version_one(self, client):
        """PRD section 3.1: "New accounts begin ACTIVE with an empty
        suspend_reason." PRD section 2.4: "version (an integer starting at
        1 that increments by exactly 1 on every mutation of that
        resource)".

        Design: Corner/entities/account_create_applies_defaults_and_enum_validation
        """
        created = client.create_account(
            account_payload(plan_tier="STANDARD"), headers=ADMIN
        )
        assert created.status_code == 201
        account = created.json()["data"]
        assert_account(account)
        assert account["status"] == "ACTIVE"
        assert account["plan_tier"] == "STANDARD"
        assert account["version"] == 1

        fetched = client.get_account(account["id"], headers=ADMIN).json()["data"]
        assert fetched == account

    def test_invalid_plan_tier_is_rejected(self, client):
        """PRD section 2.8: "14. Field-shape validation — required fields
        present, enum membership, formats ... (ERR_VALIDATION, 400)."
        plan_tier must be STANDARD or PREMIUM (PRD section 3.1).

        Design: Corner/entities/account_create_applies_defaults_and_enum_validation
        """
        created = client.create_account(
            account_payload(plan_tier="ENTERPRISE"), headers=ADMIN
        )
        validate_error(created, ERR_VALIDATION)


class TestAccountNotFound:
    def test_get_account_with_unknown_id_returns_404(self, client):
        """PRD section 2.10: "Nested paths are validated left to right: the
        account id must exist ... any break in the chain yields
        ERR_NOT_FOUND."

        Design: Corner/entities/get_account_not_found_returns_404
        """
        response = client.get_account(NON_EXISTENT_UUID, headers=ADMIN)
        validate_error(response, ERR_NOT_FOUND)


class TestBrandComputedIdentityScore:
    def test_identity_score_is_zero_at_create_and_computed_at_submit(self, client):
        """PRD section 3.2: "The brand is born DRAFT with identity_score 0
        and resubmission_count 0." Submission "computes the brand's
        identity_score" from the weighted sum with "a base of 50".

        Design: Corner/entities/brand_computed_identity_score_ignores_client_input
        """
        set_clock(client)
        account = create_account(client, plan_tier="STANDARD")
        brand = create_brand(client, account["id"], profile="charity90")
        assert brand["identity_score"] == 0
        assert brand["status"] == "DRAFT"

        submitted = client.submit_brand(
            account["id"], brand["id"], headers=BRAND_MANAGER
        ).json()["data"]
        assert submitted["identity_score"] == 90
        assert submitted["status"] == "PENDING_VERIFICATION"
        assert_brand(submitted)


class TestBrandCountryMismatch:
    def test_submit_brand_in_wrong_country_is_rejected(self, client):
        """PRD section 3.2: "the brand's country_code must equal the
        account's country_code; a violation is rejected with
        ERR_VALIDATION".

        Design: Corner/entities/brand_country_mismatch_rejected
        """
        account = create_account(client, plan_tier="STANDARD", country_code="US")
        brand = create_brand(client, account["id"], country_code="GB")
        submitted = client.submit_brand(
            account["id"], brand["id"], headers=BRAND_MANAGER
        )
        validate_error(submitted, ERR_VALIDATION)
        after = client.get_brand(account["id"], brand["id"]).json()["data"]
        assert after["status"] == "DRAFT"


class TestConsentRetentionComputed:
    def test_retention_expires_exactly_1460_days_after_capture(self, client):
        """PRD section 3.6: "The record is born ACTIVE, and its
        retention_expires_at is computed as captured_at plus 1460 days:
        the evidence must be retained until that instant."

        Design: Corner/entities/consent_record_retention_computed
        """
        account = create_account(client, plan_tier="STANDARD")
        brand = create_brand(client, account["id"])
        created = client.create_consent_record(
            account["id"],
            {
                "brand_id": brand["id"],
                "phone_number": "+15550000900",
                "evidence_url": "https://e/900",
                "evidence_text": "web",
                "captured_at": "2026-09-01T00:00:00Z",
                "consent_method": "WEB_FORM",
            },
            headers=BRAND_MANAGER,
        )
        assert created.status_code == 201
        record = created.json()["data"]
        assert_consent_record(record)
        assert record["retention_expires_at"].startswith("2030-08-31T00:00:00"), (
            "2026-09-01 + 1460 days is 2030-08-31"
        )
        assert record["status"] == "ACTIVE"


class TestAccountListPagination:
    def test_list_accounts_paginates_with_envelope_meta(self, client):
        """PRD section 2.3: "Responses for list endpoints carry limit,
        offset, total_count, and has_more in the meta envelope."

        Design: Corner/entities/list_accounts_pagination_envelope
        """
        client.create_account(
            account_payload(name="A1", plan_tier="STANDARD"), headers=ADMIN
        )
        client.create_account(
            account_payload(name="A2", plan_tier="PREMIUM", country_code="CA"),
            headers=ADMIN,
        )

        response = client.list_accounts(
            headers=ADMIN, params={"limit": 1, "offset": 0}
        )
        data, meta = validate_paginated(response)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1
