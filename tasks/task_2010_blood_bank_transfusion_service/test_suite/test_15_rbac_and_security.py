"""Auth headers, role gating, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    collect_ts,
    create_transfusion_order_payload,
    get_order,
    make_order,
    make_patient,
    result_ts,
    set_clock,
    validate_error,
    validate_success,
    TECH_A,
    TECH_B,
    COORDINATOR,
    SUPERVISOR,
    QO_1,
    DOC_1,
    DOC_2,
    api_client,
)


class TestAuthHeaders:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_patients(None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleGating:
    def test_rbac_technologist_cannot_create_supplier(self, api):
        """PRD §4: "| POST | `/blood-bank/suppliers` | Register a blood supplier |
        BloodBankSupervisor |"
        PRD §2.1: "A request whose role is not permitted to invoke the targeted
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_technologist_cannot_create_supplier
        """
        resp = api.create_supplier(
            {"name": "BadActor Blood", "license_number": "LIC-999"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_rbac_physician_cannot_verify_order(self, api):
        """PRD §4: "| POST | `/blood-bank/transfusion-orders/{id}/verify` | Verify
        an order (typing, scarcity, and segregation gates) | BloodBankTechnologist
        |"
        PRD §2.1: "A request whose role is not permitted to invoke the targeted
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_physician_cannot_verify_order
        """
        patient = make_patient(mrn="M-5001", full_name="Uma Doe",
                               date_of_birth="1983-03-03")
        order = make_order(patient["id"], product_type="FFP", units_requested=1,
                           urgency="ROUTINE", indication_code="COAG")
        resp = api.verify_order(order["id"], DOC_2)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_order(order["id"])["status"] == "PENDING_VERIFICATION"

    def test_rbac_coordinator_cannot_create_recall(self, api):
        """PRD §4: "| POST | `/blood-bank/recall-cases` | Open a recall or
        look-back case | QualityOfficer |"
        PRD §2.1: "A request whose role is not permitted to invoke the targeted
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_coordinator_cannot_create_recall
        """
        resp = api.create_recall_case(
            {"scope_type": "DONOR", "donor_id": "D-1",
             "reason": "coordinator attempt", "disposition": "DESTRUCTION"},
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_rbac_quality_officer_cannot_issue(self, api):
        """PRD §4: "| POST | `/blood-bank/issue-records` | Issue a unit against an
        order | BloodBankTechnologist |"
        PRD §2.9: "Every request passes through a fixed validation pipeline, and
        when several rules are violated at once the earliest stage in this order
        wins. First, header presence (§2.1's
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role permission
        (`ERR_UNAUTHORIZED_ROLE`)"

        Design: Corner/rbac/rbac_quality_officer_cannot_issue
        """
        resp = api.create_issue_record(
            {"order_id": NON_EXISTENT_UUID, "verified_by_user_id": "tech-b"}, QO_1)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_rbac_supervisor_cannot_result_ts(self, api):
        """PRD §4: "| POST | `/blood-bank/type-and-screens/{id}/result` | Record
        ABO/Rh and antibody screen results | BloodBankTechnologist |"
        PRD §2.1: "A request whose role is not permitted to invoke the targeted
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_supervisor_cannot_result_ts
        """
        resp = api.result_type_and_screen(
            NON_EXISTENT_UUID,
            {"abo_result": "A", "rh_result": "POS", "antibody_screen": "NEGATIVE",
             "antibody_identifications": []},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestSegregationOfDuties:
    def test_sod_ts_validate_same_user_rejected(self, api):
        """PRD §3.1: "A second technologist then **validates** the result, moving
        the specimen from `RESULTED` to `ACTIVE`. Validation on a specimen not in
        `RESULTED` fails with `ERR_TS_NOT_RESULTED`, and — the first of this
        system's segregation-of-duties rules — the validator's `X-User-ID` must
        differ from `resulted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/rbac/sod_ts_validate_same_user_rejected
        """
        set_clock("2026-08-10T09:00:00Z")
        patient = make_patient(mrn="M-5002", full_name="Vera Doe",
                               date_of_birth="1972-02-02")
        ts = collect_ts(patient, "2026-08-10T08:00:00Z")
        result_ts(ts["id"], abo_result="B", rh_result="NEG")

        resp = api.validate_type_and_screen(ts["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        validated = validate_success(api.validate_type_and_screen(ts["id"], TECH_B))
        assert validated["status"] == "ACTIVE"
