"""Registries: candidate and jurisdiction creation rules (PRD §2.5, §3.1)."""
from test_helpers import (
    ApiErrorId, DEFAULT_CE_HOURS_REQUIRED, DEFAULT_CE_HSW_HOURS_REQUIRED,
    DEFAULT_MIN_TOTAL_EXPERIENCE_HOURS, NON_EXISTENT_UUID, assert_candidate,
    assert_jurisdiction, create_candidate_payload,
    create_jurisdiction_payload, validate_error, validate_success,
)


class TestCandidateRegistration:
    def test_candidate_creation_applies_system_defaults(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §3.1: "A fresh candidate carries four guarded sub-statuses —
        `education_status` starting at `NONE`, `experience_status` at
        `NOT_STARTED`, `exam_status` at `NOT_AUTHORIZED`, and `record_standing`
        at `CLEAR` — plus a persisted `certificate_eligible` flag that starts
        at false and is recomputed after every event that could change it."

        Design: Corner/entities/candidate_creation_applies_system_defaults
        """
        validate_success(api.create_jurisdiction(
            create_jurisdiction_payload(code="J1"), ncarb_admin_headers,
        ), expected_status=201)
        data = validate_success(api.create_candidate(
            create_candidate_payload(home_jurisdiction_code="J1"),
            anonymous_headers,
        ), expected_status=201)
        assert_candidate(data)
        assert data["education_status"] == "NONE"
        assert data["experience_status"] == "NOT_STARTED"
        assert data["exam_status"] == "NOT_AUTHORIZED"
        assert data["record_standing"] == "CLEAR"
        assert data["certificate_eligible"] is False

    def test_candidate_register_with_unknown_jurisdiction_returns_422(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §3.1: "The `home_jurisdiction_code` must resolve to an existing
        jurisdiction's `code`, or registration fails with
        `ERR_JURISDICTION_UNKNOWN`."

        Design: Corner/entities/candidate_register_with_unknown_jurisdiction_returns_422
        """
        validate_error(
            api.create_candidate(
                create_candidate_payload(home_jurisdiction_code="ZZ"),
                anonymous_headers,
            ),
            ApiErrorId.ERR_JURISDICTION_UNKNOWN,
        )
        # The rejection created nothing: with a jurisdiction registered, the
        # same registration succeeds from a clean state.
        validate_success(api.create_jurisdiction(
            create_jurisdiction_payload(code="J1"), ncarb_admin_headers,
        ), expected_status=201)
        data = validate_success(api.create_candidate(
            create_candidate_payload(home_jurisdiction_code="J1"),
            anonymous_headers,
        ), expected_status=201)
        assert_candidate(data)

    def test_candidate_register_missing_email_returns_invalid_request(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §3.1: "An `Anonymous` caller opens a candidate record by
        supplying `email`, `full_name`, `password`, and a
        `home_jurisdiction_code` naming the board where initial licensure is
        sought."
        PRD §2.6: "Required fields, enum membership, numeric ranges, and
        conditional-field presence are swept last as `ERR_INVALID_REQUEST`
        (HTTP 400)".

        Design: Corner/entities/candidate_register_missing_email_returns_invalid_request
        """
        validate_success(api.create_jurisdiction(
            create_jurisdiction_payload(code="J1"), ncarb_admin_headers,
        ), expected_status=201)
        payload = create_candidate_payload(home_jurisdiction_code="J1")
        del payload["email"]
        validate_error(
            api.create_candidate(payload, anonymous_headers),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_candidate_register_client_supplied_system_fields_input_ignored(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §2.5: "Client-supplied `id`, `created_at`, or `version` values
        sent at registration time are ignored."

        Design: Corner/entities/candidate_register_client_supplied_system_fields_input_ignored
        """
        validate_success(api.create_jurisdiction(
            create_jurisdiction_payload(code="J1"), ncarb_admin_headers,
        ), expected_status=201)
        payload = create_candidate_payload(home_jurisdiction_code="J1")
        payload["id"] = "11111111-1111-4111-8111-111111111111"
        payload["created_at"] = "1999-01-01T00:00:00.000Z"
        payload["version"] = 99
        data = validate_success(
            api.create_candidate(payload, anonymous_headers), expected_status=201,
        )
        assert_candidate(data)
        assert data["id"] != "11111111-1111-4111-8111-111111111111", (
            "server must mint its own id"
        )
        assert data["created_at"] != "1999-01-01T00:00:00.000Z", (
            "server must mint its own created_at"
        )
        assert data["version"] != 99, "server must mint its own version"


class TestJurisdictionRegistry:
    def test_jurisdiction_creation_applies_national_defaults(self, api, ncarb_admin_headers):
        """PRD §3.1: "`requires_supplemental_exam` (default false),
        `min_total_experience_hours` (default 3740), `ce_hours_required`
        (default 24, the total continuing-education hours required per renewal
        period), `ce_hsw_hours_required` (default 12, the Health-Safety-Welfare
        subset of that total), and `ce_carry_over_allowed` (default false,
        governing whether surplus hours from the previous period may roll
        forward)."

        Design: Corner/entities/jurisdiction_creation_applies_national_defaults
        """
        data = validate_success(api.create_jurisdiction(
            {"code": "J1", "name": "Board One"}, ncarb_admin_headers,
        ), expected_status=201)
        assert_jurisdiction(data)
        assert data["requires_supplemental_exam"] is False
        assert data["min_total_experience_hours"] == DEFAULT_MIN_TOTAL_EXPERIENCE_HOURS
        assert data["ce_hours_required"] == DEFAULT_CE_HOURS_REQUIRED
        assert data["ce_hsw_hours_required"] == DEFAULT_CE_HSW_HOURS_REQUIRED
        assert data["ce_carry_over_allowed"] is False

    def test_jurisdiction_duplicate_code_rejected(self, api, ncarb_admin_headers):
        """PRD §3.1: "Creating a jurisdiction takes a unique `code` (a
        duplicate is rejected with `ERR_JURISDICTION_CODE_EXISTS`) and a
        `name`".

        Design: Corner/entities/jurisdiction_duplicate_code_rejected
        """
        validate_success(api.create_jurisdiction(
            {"code": "J1", "name": "Board One"}, ncarb_admin_headers,
        ), expected_status=201)
        validate_error(
            api.create_jurisdiction(
                {"code": "J1", "name": "Board One Duplicate"},
                ncarb_admin_headers,
            ),
            ApiErrorId.ERR_JURISDICTION_CODE_EXISTS,
        )

    def test_get_unknown_candidate_returns_not_found(self, api, ncarb_admin_headers):
        """PRD §2.5: "When a request touches a nested path, path identifiers
        are resolved from left to right, and the first identifier that does
        not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP
        404)."

        Design: Corner/entities/get_unknown_candidate_returns_not_found
        """
        validate_error(
            api.get_candidate(NON_EXISTENT_UUID, ncarb_admin_headers),
            ApiErrorId.ERR_NOT_FOUND,
        )
