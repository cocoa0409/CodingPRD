"""Platform concerns: defaults, shape, existence, RBAC, OCC, derived fields."""
from test_helpers import (
    ADMIN,
    COUNSELOR,
    ApiErrorId,
    api_client,
    create_applicant,
    create_application_payload,
    create_center,
    create_center_payload,
    create_trade_program,
    open_application,
    validate_error,
    validate_success,
)


class TestDeclaredDefaults:
    def test_program_application_applicant_defaults(self):
        """PRD section 3.2: "an optional required_credential_types list whose
        members come from HSE, INDUSTRY_CERT, and DRIVER_LICENSE (empty means
        no prerequisites), and an optional supports_remediation flag defaulting
        to false. The program begins with enrolled_count at 0, open_seats
        equal to capacity, and status set to OPEN."
        PRD section 3.1: "The new applicant starts with assignment_status set
        to NONE" and "starts the case in SUBMITTED".

        Design: Corner/entities/created_entities_apply_declared_defaults
        """
        center = create_center(name="Default Center", total_beds=3)
        program = create_trade_program(center["id"], trade_code="CULINARY",
                                       capacity=4)
        assert program["required_credential_types"] == []
        assert program["supports_remediation"] is False
        assert program["status"] == "OPEN"
        assert program["enrolled_count"] == 0
        assert program["open_seats"] == 4
        applicant = create_applicant(full_name="Def Stu",
                                     desired_trade_code="CULINARY")
        assert applicant["assignment_status"] == "NONE"
        case = open_application(applicant)
        assert case["status"] == "SUBMITTED"


class TestSystemFieldInjection:
    def test_client_supplied_id_rejected(self):
        """PRD section 2.7: "A structurally malformed body — a missing required
        field, an undeclared field, an invalid enum member, or a field-domain
        violation such as an out-of-range household size, a bed label outside
        the center's valid label range, sanction points outside their allowed
        band, or out-of-range daily hours — produces ERR_INVALID_REQUEST."
        PRD section 2.5: "Every persisted resource carries an id that is a
        server-minted UUID".

        Design: Corner/entities/system_field_injection_rejected
        """
        payload = create_center_payload(name="Inject Center", total_beds=3)
        payload["id"] = "00000000-0000-0000-0000-000000000000"
        resp = api_client.create_center(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_unknown_applicant_returns_404(self):
        """PRD section 2.7: "Then path-templated identifiers are resolved left
        to right, and the first id that does not resolve produces
        ERR_NOT_FOUND."

        Design: Corner/entities/applicant_not_found_returns_404
        """
        resp = api_client.get_applicant(
            "11111111-2222-3333-4444-555555555555", ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestChildListing:
    def test_center_programs_subresource_scopes_to_parent(self):
        """PRD section 4: "List a center's trade programs" — the sub-resource
        returns exactly the programs of the addressed center.
        PRD section 2.7: "the first id that does not resolve produces
        ERR_NOT_FOUND."

        Design: Corner/entities/child_listing_via_parent_subresource
        """
        center_a = create_center(name="List A", total_beds=3)
        center_b = create_center(name="List B", region_code="R-SOUTH",
                                 total_beds=3)
        create_trade_program(center_a["id"], trade_code="WELDING", capacity=2)
        create_trade_program(center_a["id"], trade_code="CULINARY", capacity=2)
        create_trade_program(center_b["id"], trade_code="CARPENTRY", capacity=2)
        rows = validate_success(
            api_client.list_center_trade_programs(center_a["id"], ADMIN)
        )
        assert len(rows) == 2
        assert {row["trade_code"] for row in rows} == {"WELDING", "CULINARY"}
        assert all(row["center_id"] == center_a["id"] for row in rows)
        resp = api_client.list_center_trade_programs(
            "11111111-2222-3333-4444-555555555555", ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestImmediateConsistency:
    def test_create_and_patch_responses_carry_recomputed_fields(self):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object
        in the data field."
        PRD section 3.2: "the center starts with beds_in_use at 0 and
        beds_available equal to total_beds" and "open_seats is recomputed when
        capacity changes, and the update advances the program's version by 1".

        Design: Corner/consistency_model/immediate_read_after_write_computed_fields
        """
        center = validate_success(
            api_client.create_center(
                create_center_payload(name="Imm Center", total_beds=5), ADMIN
            ),
            201,
        )
        assert center["beds_in_use"] == 0
        assert center["beds_available"] == 5
        program = validate_success(
            api_client.create_trade_program(
                {"center_id": center["id"], "trade_code": "WELDING",
                 "capacity": 5},
                ADMIN,
            ),
            201,
        )
        assert program["open_seats"] == 5
        patched = validate_success(
            api_client.patch_trade_program(program["id"], {"capacity": 7},
                                           ADMIN),
            200,
        )
        assert patched["open_seats"] == 7
        assert patched["version"] == program["version"] + 1, (
            "the update advances the program's version by exactly 1"
        )


class TestAuthnAuthz:
    def test_missing_auth_headers_unauthenticated(self):
        """PRD section 2.1: "A request missing either header, or whose
        X-User-Role value does not name one of the declared roles, is rejected
        with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        resp = api_client.create_center(
            create_center_payload(name="NoHdr Center", total_beds=2),
            headers=None,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_counselor_cannot_create_center(self):
        """PRD section 2.1: "A request whose role is authenticated but is not
        listed among the roles authorized for the target endpoint is rejected
        with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/counselor_cannot_create_center
        """
        resp = api_client.create_center(
            create_center_payload(name="Forbidden Center", total_beds=2),
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


class TestImmutablePatchFields:
    def test_patch_center_id_rejected_and_program_unchanged(self):
        """PRD section 3.2: "That update may touch only capacity and status".
        PRD section 2.7: "an undeclared field ... produces
        ERR_INVALID_REQUEST."

        Design: Corner/validations/patch_program_immutable_field_rejected
        """
        center_a = create_center(name="Imm A", total_beds=2)
        center_b = create_center(name="Imm B", region_code="R-SOUTH",
                                 total_beds=2)
        program = create_trade_program(center_a["id"], capacity=3)
        resp = api_client.patch_trade_program(
            program["id"], {"center_id": center_b["id"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows = validate_success(
            api_client.list_center_trade_programs(center_a["id"], ADMIN)
        )
        assert [row["id"] for row in rows] == [program["id"]], (
            "the program still belongs to center A"
        )


class TestApplicationOcc:
    def test_stale_application_create_rejected_412(self):
        """PRD section 2.6: "Opening an eligibility case for an applicant, and
        running center assignment for an applicant, both require the request
        to carry expected_applicant_version holding the version of the
        Applicant as the client last observed it. If the applicant's current
        version has advanced beyond that observed value — because, for
        instance, another counselor filed a case or ran an assignment in the
        meantime — the write is rejected with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_application_create_returns_412
        """
        applicant = create_applicant(full_name="Occ Stu")
        first = api_client.create_application(
            create_application_payload(applicant["id"], applicant["version"]),
            COUNSELOR,
        )
        validate_success(first, 201)
        resp = api_client.create_application(
            create_application_payload(
                applicant["id"], applicant["version"], household_size=2,
                annual_income_cents=900000, barrier_flags=["HOMELESS"],
            ),
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
