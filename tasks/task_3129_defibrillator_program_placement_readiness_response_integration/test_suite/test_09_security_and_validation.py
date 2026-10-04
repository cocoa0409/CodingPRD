"""Security, validation ordering, and immutability: authn/authz, existence
ordering, self-test report shape, and role-exclusive denials.

Design: Corner/validations/missing_x_user_role_returns_unauthenticated,
        Corner/validations/forbidden_role_for_device_create_returns_403,
        Corner/validations/existence_check_validates_left_to_right,
        Corner/entities/self_test_report_is_immutable_no_update_endpoint,
        Corner/rbac/inspector_cannot_create_devices.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_self_test_report,
    create_campus,
    create_device,
    create_device_model,
    create_responder,
    create_self_test_report_payload,
    get_success_data,
    make_responder_headers,
    make_inspector_headers,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]
SYSTEM = TEST_USERS["system_headers"]


class TestAuthentication:

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD: "A request that omits either header, or names a role the system
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_x_user_role_returns_unauthenticated
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus()
        res = api.get_campus(campus["id"], headers={
            "Content-Type": "application/json",
        })
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestAuthorization:

    def test_responder_role_cannot_create_device(self, api):
        """PRD: "A request whose role is recognized but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        (endpoint table): "POST | `/api/devices` | Register a Device |
        ProgramManager".

        Design: Corner/validations/forbidden_role_for_device_create_returns_403
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        responder = create_responder(campus["id"],
                                     responder_role="LAY_RESPONDER",
                                     full_name="R", badge_number="R-RB")
        res = api.create_device(
            {"campus_id": campus["id"], "device_model_id": model["id"],
             "serial_number": "SN-RB-1"},
            make_responder_headers(responder["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_inspector_cannot_create_devices(self, api):
        """PRD: "A request whose role is recognized but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        (endpoint table): "POST | `/api/devices` | Register a Device |
        ProgramManager".

        Design: Corner/rbac/inspector_cannot_create_devices
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        inspector = create_responder(campus["id"], responder_role="INSPECTOR",
                                     full_name="Insp", badge_number="IN-IR")
        res = api.create_device(
            {"campus_id": campus["id"], "device_model_id": model["id"],
             "serial_number": "SN-IR-1"},
            make_inspector_headers(inspector["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestExistenceOrdering:

    def test_unknown_device_id_returns_not_found(self, api):
        """PRD: "the system validates the existence of each referenced resource
        in order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the
        first reference that does not resolve."

        Design: Corner/validations/existence_check_validates_left_to_right
        """
        set_clock("2026-09-01T00:00:00Z")
        res = api.get_device("11111111-1111-1111-1111-111111111111", PM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestSelfTestReportImmutability:

    def test_self_test_report_has_no_version_or_updated_at(self, api):
        """PRD: "the `SelfTestReport` carries only `id` and `created_at`.
        Because self-test reports are immutable telemetry records that are
        never modified after ingestion, both `updated_at` and `version` are
        absent from the resource — clients must not expect them in the response
        body."

        Design: Corner/entities/self_test_report_is_immutable_no_update_endpoint
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-IM-1")
        res = api.create_self_test_report(
            create_self_test_report_payload(device["id"], result="PASS"),
            SYSTEM,
        )
        report = validate_success(res, expected_status=201)
        assert_self_test_report(report)

    def test_self_test_report_has_no_update_endpoint(self, api):
        """PRD: "Because self-test reports are immutable telemetry records that
        are never modified after ingestion, both `updated_at` and `version` are
        absent from the resource". No PUT/PATCH endpoint is defined for
        self-test reports in the PRD endpoint table.

        Design: Corner/entities/self_test_report_is_immutable_no_update_endpoint
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-IM-2")
        report = get_success_data(
            api.create_self_test_report(
                create_self_test_report_payload(device["id"], result="PASS"),
                SYSTEM,
            )
        )
        res = api.put(
            f"/api/self-test-reports/{report['id']}",
            json={"result": "FAIL"},
            headers=SYSTEM,
        )
        # No such operation exists: 404 (no route) or 405 (method not allowed).
        assert res.status_code in (404, 405), (
            f"PUT on a self-test report must not exist, got {res.status_code}"
        )
