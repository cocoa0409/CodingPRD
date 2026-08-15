"""Catalog curation and response-envelope tests (PRD §2.2, §2.3, §3.1).

Instances translated from the entities / state_machines / endpoints sections
of the corner index.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_program,
    create_partner_agreement,
    create_partner_agreement_payload,
    create_program_payload,
    create_student_payload,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    COORD_A_HEADERS,
)


class TestProgramCreation:
    def test_program_creation_defaults(self, api):
        """PRD §3.1: "New programs are born in `DRAFT` with `seats_taken` at 0."

        Design: Corner/entities/program_creation_defaults
        """
        agreement = create_partner_agreement()
        resp = api.create_program(
            create_program_payload(agreement["id"]), COORD_A_HEADERS,
        )
        program = validate_success(resp, expected_status=201)
        assert_program(program)
        assert program["status"] == "DRAFT", (
            f"New program must be born DRAFT, got {program['status']}"
        )
        assert program["seats_taken"] == 0, (
            f"New program seats_taken must be 0, got {program['seats_taken']}"
        )
        assert program["version"] == 1, (
            f"New program version must be 1, got {program['version']}"
        )
        assert is_valid_uuid(program["id"]), "Program.id must be a server-minted UUID"

    def test_program_computed_and_system_input_ignored(self, api):
        """PRD §3.1: "New programs are born in `DRAFT` with `seats_taken` at 0."

        Design: Corner/entities/program_computed_and_system_input_ignored
        """
        agreement = create_partner_agreement()
        injected_id = "11111111-1111-1111-1111-111111111111"
        payload = create_program_payload(
            agreement["id"], status="OPEN", seats_taken=99, id=injected_id,
        )
        resp = api.create_program(payload, COORD_A_HEADERS)
        program = validate_success(resp, expected_status=201)
        assert program["status"] == "DRAFT", (
            f"Client-injected status must be ignored; program is born DRAFT, got {program['status']}"
        )
        assert program["seats_taken"] == 0, (
            f"Client-injected seats_taken must be ignored; born at 0, got {program['seats_taken']}"
        )
        assert program["id"] != injected_id, (
            "Server mints the id; a client-supplied id must not be adopted"
        )


class TestStudentCreation:
    def test_student_create_missing_required_gpa(self, api):
        """PRD §2.10: "Required fields are present, types are valid, enum members are valid,
        and ranges hold ... Other schema failures also surface as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/student_create_missing_required_gpa
        """
        resp = api.create_student(
            {"full_name": "No Gpa", "email": "nogpa@uni.edu", "conduct_standing": "GOOD_STANDING"},
            COORD_A_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_student_defaults_applied(self, api):
        """PRD §3.2: "an optional `aid_award_cents` — the total financial aid award in cents
        considered for portability — defaulting to 0 and never negative."

        Design: Corner/entities/student_defaults_applied
        """
        payload = {
            "full_name": "Default Aid",
            "email": "default@uni.edu",
            "gpa": 3.00,
            "conduct_standing": "GOOD_STANDING",
        }
        resp = api.create_student(payload, COORD_A_HEADERS)
        student = validate_success(resp, expected_status=201)
        assert student["aid_award_cents"] == 0, (
            f"Omitted aid_award_cents must apply the declared default 0, got {student['aid_award_cents']}"
        )


class TestProgramReadAndValidation:
    def test_program_not_found_returns_404(self, api):
        """PRD §2.10: "Path identifiers resolve to existing resources, validated left to
        right — otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/program_not_found_returns_404
        """
        resp = api.get_program(NON_EXISTENT_UUID, COORD_A_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_program_invalid_enum_billing_model_returns_invalid_request(self, api):
        """PRD §2.10: "Required fields are present, types are valid, enum members are valid,
        and ranges hold ... Other schema failures also surface as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/program_invalid_enum_billing_model_returns_invalid_request
        """
        agreement = create_partner_agreement()
        payload = create_program_payload(agreement["id"], billing_model="MIXED")
        resp = api.create_program(payload, COORD_A_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_program_fee_conditional_requirement(self, api):
        """PRD §2.10: "a program whose `billing_model` is `PROGRAM_FEE` requires a positive
        `program_fee_cents` (`ERR_PROGRAM_FEE_REQUIRED`), while a `HOME_TUITION` program must
        omit `program_fee_cents` or set it to 0 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/program_fee_conditional_requirement
        """
        agreement = create_partner_agreement()
        payload = create_program_payload(agreement["id"], billing_model="PROGRAM_FEE")
        payload.pop("program_fee_cents", None)
        resp = api.create_program(payload, COORD_A_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_FEE_REQUIRED)


class TestProgramPublish:
    def test_program_publish_valid_transition(self, api):
        """PRD §3.1: "Publishing moves a program from `DRAFT` to `OPEN` and is gated on the
        partner agreement: the referenced agreement must exist (`ERR_NOT_FOUND`) and be
        `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)."

        Design: Corner/state_machines/program_publish_valid_transition
        """
        agreement = create_partner_agreement()
        program = get_success_data(
            api.create_program(create_program_payload(agreement["id"]), COORD_A_HEADERS)
        )
        resp = api.publish_program(program["id"], COORD_A_HEADERS)
        published = validate_success(resp, expected_status=200)
        assert published["status"] == "OPEN"
        assert published["version"] == 2, (
            f"Publish must bump version 1 -> 2, got {published['version']}"
        )
        reread = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert reread["status"] == "OPEN", (
            "Mutation must be visible on an immediate re-read (immediate consistency)"
        )

    def test_publish_with_draft_agreement_rejected(self, api):
        """PRD §3.1: "Publishing moves a program from `DRAFT` to `OPEN` and is gated on the
        partner agreement: the referenced agreement must exist (`ERR_NOT_FOUND`) and be
        `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)."

        Design: Corner/state_machines/publish_with_draft_agreement_rejected
        """
        agreement = create_partner_agreement(activate=False)
        program = get_success_data(
            api.create_program(create_program_payload(agreement["id"]), COORD_A_HEADERS)
        )
        resp = api.publish_program(program["id"], COORD_A_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        reread = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert reread["status"] == "DRAFT", (
            f"Failed publish must leave the program DRAFT, got {reread['status']}"
        )


class TestResponseEnvelope:
    def test_response_envelope_shape(self, api):
        """PRD §2.2: "The `response_type` is either \"object\" for a single resource or
        \"array\" for a list of resources." and "Pagination-related fields in `meta`
        (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/endpoints/response_envelope_shape
        """
        agreement = create_partner_agreement()
        program = get_success_data(
            api.create_program(create_program_payload(agreement["id"]), COORD_A_HEADERS)
        )
        single = api.get_program(program["id"], COORD_A_HEADERS)
        body = single.json()
        assert "meta" in body and "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object", (
            f"Single-entity read must carry response_type 'object', got {body['response_type']}"
        )
        assert body["data"]["id"] == program["id"]

        list_resp = api.list_programs(COORD_A_HEADERS, params={"limit": 5, "offset": 0})
        data, meta = validate_paginated(list_resp)
        assert meta["limit"] == 5 and meta["offset"] == 0
        assert meta["total_count"] == 1, (
            f"Exactly one program exists; total_count must be 1, got {meta['total_count']}"
        )
        assert meta["has_more"] is False
