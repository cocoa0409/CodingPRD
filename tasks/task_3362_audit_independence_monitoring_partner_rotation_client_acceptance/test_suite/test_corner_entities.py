"""Breadth claims about resource creation, listing and schema shape."""

import pytest

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN_HEADERS,
    assert_client,
    fixtures,
    get_acceptance_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    service_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClientRegistration:
    """Registration fills every field the caller did not supply."""

    def test_client_registration_applies_the_declared_defaults(self, api):
        """PRD §3.1: "Registration leaves the new record in `PROSPECT` status,
        and its `naf_approved_fee_cents` is computed through the fee pool rule
        of §3.6 — zero at this point, since no service has been approved."

        Design: Corner/entities/client_create_applies_defaults_and_system_fields
        """
        fixtures.set_clock(api)
        response = api.create_client(
            {
                "legal_name": "Harbor Point Shipping",
                "industry_code": "MANUFACTURING",
                "jurisdiction_country": "US",
            },
            PLATFORM_ADMIN_HEADERS,
        )
        client = validate_success(response, 201)
        assert response.json()["response_type"] == "object"

        assert client["legal_name"] == "Harbor Point Shipping"
        assert client["industry_code"] == "MANUFACTURING"
        assert client["jurisdiction_country"] == "US"
        assert client["is_public_interest_entity"] is False
        assert client["naf_annual_cap_cents"] == 0
        assert client["naf_approved_fee_cents"] == 0
        assert client["status"] == "PROSPECT"
        assert client["aggregate_independence_status"] == "CLEAR"
        assert client["open_finding_count"] == 0
        assert client["parent_client_id"] is None

    def test_client_registration_mints_the_system_fields(self, api):
        """PRD §2.4: "`id` (string) — a unique, server-minted identifier for the
        resource, formatted as a UUID with no type prefix and no embedded
        resource name."
        PRD §2.4: "Every entity in this API carries the complete set of four
        fields; no resource omits `updated_at` or `version`."

        Design: Corner/entities/client_create_applies_defaults_and_system_fields
        """
        fixtures.set_clock(api)
        client = fixtures.seed_client(api, legal_name="Harbor Point Shipping")
        assert_client(client)
        assert is_valid_uuid(client["id"])
        assert is_iso8601_timestamp(client["created_at"])
        assert is_iso8601_timestamp(client["updated_at"])
        assert isinstance(client["version"], int)


class TestEngagementListing:
    """Pages are bounded while the totals describe the whole filtered set."""

    def test_engagement_list_pages_with_total_count_and_has_more(self, api):
        """PRD §2.3: "`total_count` reports the total number of records matching
        the request's filters before pagination is applied, and `has_more` is a
        boolean that is true when further records remain beyond the returned
        page."

        Design: Corner/entities/engagement_list_paginates_with_total_count_and_has_more
        """
        fixtures.scenario_pagination(api)

        first_page, first_meta = validate_paginated(
            api.list_engagements(PLATFORM_ADMIN_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 4
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_engagements(PLATFORM_ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 2
        assert second_meta["total_count"] == 4
        assert second_meta["has_more"] is False

    def test_engagement_list_defaults_to_ten_and_zero(self, api):
        """PRD §2.3: "`limit` is the maximum number of records returned in one
        page; it defaults to 10, must be at least 1 and must not exceed 100.
        `offset` is the number of records to skip from the beginning of the
        result set and defaults to 0."

        Design: Corner/entities/engagement_list_paginates_with_total_count_and_has_more
        """
        fixtures.scenario_pagination(api)

        data, meta = validate_paginated(api.list_engagements(PLATFORM_ADMIN_HEADERS))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        assert len(data) == 4
        # Records come back ordered by created_at ascending.
        created = [row["created_at"] for row in data]
        assert created == sorted(created)


class TestIntegrityAssessmentSchema:
    """The assessed_on date is required, not optional."""

    def test_missing_assessed_on_is_a_schema_violation(self, api):
        """PRD §2.10: "The body must match the endpoint's schema: required
        fields present, every enum-valued field carrying a member of its
        declared set, and numeric ranges respected"."

        Design: Corner/entities/integrity_assessment_missing_required_field_returns_invalid_request
        """
        fixtures.set_clock(api)
        world = fixtures.seed_reference_data(api, legal_name="Fenwick Robotics")
        acceptance = fixtures.open_acceptance(
            api, world["client"]["id"], world["engagement"]["id"],
            industry_expertise_required="TECH",
        )
        before = get_acceptance_data(api, acceptance["id"])
        assert before["integrity_score"] == pytest.approx(100.0)

        response = api.create_integrity_assessment(
            acceptance["id"],
            {"source_type": "LITIGATION", "severity": "HIGH", "score_impact": 15},
            fixtures.COMMITTEE_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        assert fixtures.list_assessments_for(api, acceptance["id"]) == []
        after = get_acceptance_data(api, acceptance["id"])
        assert after["integrity_score"] == pytest.approx(100.0)


class TestServiceCategorySchema:
    """Enum membership is checked before anything else about the request."""

    def test_unknown_service_category_is_rejected(self, api):
        """PRD §3.6: "The request names the `service_category` — one of
        `BOOKKEEPING`, `INTERNAL_AUDIT_OUTSOURCING`, `VALUATION`,
        `TAX_PREPARATION`, `TAX_ADVISORY`, `IT_SYSTEMS_DESIGN`, `ACTUARIAL`,
        `MANAGEMENT_FUNCTION`, `LEGAL` or `OTHER`".

        Design: Corner/entities/non_audit_service_invalid_enum_returns_400
        """
        fixtures.set_clock(api)
        client = fixtures.seed_client(api, legal_name="Quarry Lake Cement")

        rejected = api.create_service(
            service_payload(
                client["id"], service_category="TAX_PREPARATION_AND_PLANNING", fee_cents=250000
            ),
            fixtures.LIAISON_HEADERS,
        )
        validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST, 400)

        accepted = fixtures.create_service(
            api, client["id"], service_category="TAX_PREPARATION", fee_cents=250000
        )
        assert accepted["status"] == "DRAFT"
        assert accepted["service_category"] == "TAX_PREPARATION"

    def test_negative_fee_is_rejected(self, api):
        """PRD §2.10: "numeric ranges respected, including `score_impact`
        between 0 and 40 inclusive, `fee_cents` not negative, and `value_cents`
        not negative."

        Design: Corner/entities/non_audit_service_invalid_enum_returns_400
        """
        fixtures.set_clock(api)
        client = fixtures.seed_client(api, legal_name="Quarry Lake Cement")

        response = api.create_service(
            service_payload(client["id"], service_category="TAX_PREPARATION", fee_cents=-1),
            fixtures.LIAISON_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
