"""Entity baseline coverage: member registration defaults and envelope, resource
defaults and required fields, computed-field initialization, and list
pagination envelope."""
from test_helpers import (
    ApiErrorId,
    assert_member,
    assert_retention_log,
    create_airport,
    create_agreement,
    create_enrollment_center,
    open_enrollment,
    register_member,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPS, PM
from test_helpers.test_users import TEST_USERS


class TestMemberRegistrationDefaults:
    def test_register_returns_pending_member_with_envelope(self, api):
        """PRD §3.3: "The new member starts in `PENDING_ENROLLMENT` with `verification_level`
        of `NONE`, `risk_score` of zero, and `document_reject_count_90d` of zero."

        Design: Corner/entities/member_register_creation_defaults_and_envelope
        """
        resp = api.register_member(
            {"email": "fresh@x.com", "full_name": "Fresh Member",
             "date_of_birth": "1993-04-04"},
            TEST_USERS["member_headers"],
        )
        member = validate_success(resp, expected_status=201)
        assert_member(member)
        assert member["status"] == "PENDING_ENROLLMENT"
        assert member["verification_level"] == "NONE"
        assert member["risk_score"] == 0
        assert member["document_reject_count_90d"] == 0

    def test_register_envelope_meta_and_created_at(self, api):
        """PRD §2.4: "Every entity carries an `id` that is a server-minted UUID with no type
        prefix, and a `created_at` timestamp." and "Before any test-driving call, the
        logical clock reads exactly 2026-09-01T00:00:00Z."

        Design: Corner/entities/member_register_creation_defaults_and_envelope
        """
        resp = api.register_member(
            {"email": "fresh2@x.com", "full_name": "Fresh Two",
             "date_of_birth": "1993-04-04"},
            TEST_USERS["member_headers"],
        )
        body = resp.json()
        assert body.get("response_type") == "object"
        meta = body.get("meta", {})
        assert meta.get("api_request_id", "").startswith("req_"), (
            "envelope carries a req_-prefixed api_request_id"
        )
        assert "api_request_timestamp" in meta
        member = body["data"]
        assert member["created_at"] == "2026-09-01T00:00:00.000Z", (
            "created_at stamps the default logical clock (three fractional digits per PRD §2.4)"
        )
        assert member["version"] == 1


class TestEnrollmentCenterRequiredFields:
    def test_missing_ambassador_capacity_fails_validation(self, api):
        """PRD §3.2: "Enrollment centers are the staffed counterpart: created at an airport
        with a display `name` and an `ambassador_capacity` of at least one seat, and
        born `ACTIVE`." — `ambassador_capacity` is part of the creation contract, and
        per PRD §2.7 "like any other field-level shape failure, is rejected with
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/enrollment_center_default_and_required_fields
        """
        airport = create_airport("PHL")
        resp = api.create_enrollment_center(
            {"airport_id": airport["id"], "name": "PHL Center"}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_complete_center_creation_returns_active(self, api):
        """PRD §3.2: "Enrollment centers are the staffed counterpart: created at an airport
        with a display `name` and an `ambassador_capacity` of at least one seat, and
        born `ACTIVE`."

        Design: Corner/entities/enrollment_center_default_and_required_fields
        """
        airport = create_airport("PHL")
        center = validate_success(
            api.create_enrollment_center(
                {"airport_id": airport["id"], "name": "PHL Center",
                 "ambassador_capacity": 2},
                OPS,
            ),
            expected_status=201,
        )
        assert center["status"] == "ACTIVE"
        assert center["ambassador_capacity"] == 2


class TestAgreementLaneCapacityComputed:
    def test_lane_capacity_zero_at_create(self, api):
        """PRD §3.1: "A fresh draft carries `lane_capacity` of zero."

        Design: Corner/entities/partner_agreement_lane_capacity_computed_zero_at_create
        """
        airport = create_airport("TUL")
        agreement = create_agreement(airport["id"])
        assert agreement["lane_capacity"] == 0
        fetched = validate_success(api.get_agreement(agreement["id"], PM))
        assert fetched["lane_capacity"] == 0


class TestEnrollmentListPagination:
    def test_enrollments_list_pagination_envelope(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit` and `offset`.
        The default `limit` is 10; the minimum accepted value is 1 and the maximum is
        100. The default `offset` is 0. List responses include `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` envelope."

        Design: Corner/entities/enrollment_list_pagination_envelope
        """
        airport = create_airport("OMA")
        center = create_enrollment_center(airport["id"], name="OMA Center",
                                          ambassador_capacity=2)
        member = register_member(
            email="list@x.com", full_name="List Member", date_of_birth="1990-01-01"
        )
        open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_number="PL100001", biometric_capture_ok=True,
        )
        data, meta = validate_paginated(
            api.list_enrollments(OPS, params={"member_id": member["id"]})
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert data[0]["member_id"] == member["id"]
