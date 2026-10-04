"""Creation envelopes, defaults, uniqueness and not-found resolution."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_region,
    assert_same_instant,
    create_applicant_payload,
    create_region_payload,
    err,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.fixtures import (
    ADMIN,
    PLACEMENT_COORDINATOR,
    SELECTION_MANAGER,
    create_applicant,
    create_district,
    create_region,
)


class TestRegionCreation:
    def test_creation_returns_201_with_echoed_and_server_fields(self, api):
        """PRD §4: "Operations that bring a new, independently addressable resource into existence — a region, an applicant, an application, a pathway, a placement, a milestone, a support record, a district, a school — answer with `201 Created`."
        PRD §2.5: "The `id` is a server-minted UUID with no type prefix and is the only address a client needs."
        PRD §2.4: "Creating a Region initializes its `version` to 1."

        Design: Corner/entities/region_creation_returns_201_with_server_fields
        """
        response = api.create_region(create_region_payload(), ADMIN)
        assert response.status_code == 201
        body = response.json()
        assert body["response_type"] == "object"

        data = body["data"]
        assert_region(data)
        assert data["region_code"] == "GULF-COAST"
        assert data["name"] == "Gulf Coast"
        assert data["state_code"] == "TX"
        assert_same_instant(
            data["term_start_date"], "2026-12-01T00:00:00Z", "term_start_date"
        )
        assert data["base_placement_fee_cents"] == 300000
        assert data["max_corps_members"] == 10
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])

    def test_missing_required_field_is_refused_and_persists_nothing(self, api):
        """PRD §2.10: "Every field the operation declares as required must be present; every enumerated field must carry a declared member; every numeric field must satisfy its declared range"
        PRD §2.10: "Any breach of this tier is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/region_create_missing_required_field_returns_400
        """
        payload = create_region_payload()
        payload.pop("max_corps_members")

        response = api.create_region(payload, ADMIN)
        validate_error(response, err(ApiErrorId.ERR_INVALID_REQUEST), 400)

        # The refused payload's region_code must still be free.
        replacement = create_region_payload(name="Gulf Coast Replacement")
        created = validate_success(api.create_region(replacement, ADMIN), 201)
        assert created["region_code"] == "GULF-COAST"


class TestUniqueness:
    def test_region_code_and_applicant_email_are_both_unique(self, api):
        """PRD §2.10: "A body field declared unique must not already be held by another row — this applies to a region's `region_code` and to an applicant's `email`."
        PRD §3.1: "The email is the applicant's identity as far as deduplication is concerned — it must be unique across every applicant on file — and a second registration attempt with an email already on file is refused with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/region_code_and_applicant_email_uniqueness
        """
        create_region()
        create_applicant(email="ada@x.edu")

        duplicate_region = api.create_region(
            create_region_payload(name="Gulf Coast Duplicate"), ADMIN
        )
        validate_error(duplicate_region, err(ApiErrorId.ERR_INVALID_REQUEST), 400)

        duplicate_applicant = api.create_applicant(
            create_applicant_payload(email="ada@x.edu", full_name="Ada Rivera Again"),
            SELECTION_MANAGER,
        )
        validate_error(duplicate_applicant, err(ApiErrorId.ERR_INVALID_REQUEST), 400)

        # A different code and a different email still go through.
        other_region = validate_success(
            api.create_region(create_region_payload(region_code="RIVER", name="River"), ADMIN),
            201,
        )
        assert other_region["region_code"] == "RIVER"
        other_applicant = validate_success(
            api.create_applicant(create_applicant_payload(email="bo@x.edu"), SELECTION_MANAGER),
            201,
        )
        assert other_applicant["email"] == "bo@x.edu"


class TestParentResolution:
    def test_application_with_unknown_applicant_is_refused(self, api):
        """PRD §2.10: "An Applicant that cannot be resolved is `ERR_APPLICANT_NOT_FOUND` (404), reported on application submission."

        Design: Corner/entities/application_create_with_unknown_applicant_returns_404
        """
        region = create_region()
        payload = {
            "applicant_id": NON_EXISTENT_UUID,
            "preferred_region_id": region["id"],
            "subject_area": "MATH",
            "grade_preference": "HIGH",
        }
        response = api.create_application(payload, SELECTION_MANAGER)
        validate_error(response, err(ApiErrorId.ERR_APPLICANT_NOT_FOUND), 404)

        rows, meta = validate_paginated(
            api.list_applications(SELECTION_MANAGER, {"preferred_region_id": region["id"]})
        )
        assert rows == [], "no Application row may be created"
        assert meta["total_count"] == 0


class TestDistrictDefaultsAndPagination:
    def test_new_district_defaults_and_filtered_list_metadata(self, api):
        """PRD §3.6: "A new agreement starts at `agreement_status` `DRAFT`, with `committed_placement_count` and `invoice_amount_cents` both at 0."
        PRD §2.3: "Paginated responses repeat the effective page window in the envelope's `meta` object through `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the full filtered collection rather than the size of the returned page."

        Design: Corner/entities/partner_district_create_defaults_and_list_pagination
        """
        region = create_region()
        district = create_district(region["id"])

        assert district["agreement_status"] == "DRAFT"
        assert district["committed_placement_count"] == 0
        assert district["invoice_amount_cents"] == 0

        response = api.list_partner_districts(
            ADMIN, {"region_id": region["id"], "limit": 1, "offset": 0}
        )
        assert response.json()["response_type"] == "array"
        rows, meta = validate_paginated(response)
        assert len(rows) == 1
        assert rows[0]["id"] == district["id"]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 1
        assert meta["offset"] == 0


class TestNotFoundEnvelope:
    def test_unknown_application_id_returns_the_error_envelope(self, api):
        """PRD §2.10: "An Application that cannot be resolved is `ERR_APPLICATION_NOT_FOUND` (404), reported on the application read and on all six application operations"
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/application_not_found_returns_404
        """
        response = api.get_application(NON_EXISTENT_UUID, SELECTION_MANAGER)
        assert response.status_code == 404
        body = response.json()
        assert body["response_type"] == "error"

        error_data = validate_error(response, err(ApiErrorId.ERR_APPLICATION_NOT_FOUND), 404)
        assert isinstance(error_data["message"], str) and error_data["message"].strip()
        assert body["meta"].get("api_request_id")
