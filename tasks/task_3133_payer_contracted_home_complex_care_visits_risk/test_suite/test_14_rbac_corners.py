"""Corner-queue tests: RBAC matrix (section 4 role column is authoritative)."""
import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    CONTRACT_ADMIN,
    COORDINATOR,
    SPECIALIST,
    api_client,
    create_capitated_contract_payload,
    create_care_program_payload,
    create_clinician,
    create_member_payload,
    create_member_with_enrollment,
    create_pcp,
    create_program,
    create_scheduled_visit,
    make_clinician_headers,
    setup_active_enrollment,
    setup_basic_reference,
    validate_error,
    validate_success,
)


def _program_payload():
    return create_care_program_payload()


class TestCareProgramRBAC:
    def test_platform_admin_can_create_care_program(self, api):
        """PRD section 4: "POST | /care-programs | Create a care program | PlatformAdmin"

        Design: Corner/rbac/platform_admin_can_create_care_program
        """
        resp = api.create_care_program(_program_payload(), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["id"]

    def test_contract_admin_cannot_create_care_program(self, api):
        """PRD section 4: "POST | /care-programs | Create a care program | PlatformAdmin"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/contract_admin_cannot_create_care_program
        """
        resp = api.create_care_program(_program_payload(), CONTRACT_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_engagement_specialist_cannot_create_care_program(self, api):
        """PRD section 4: "POST | /care-programs | Create a care program | PlatformAdmin"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/engagement_specialist_cannot_create_care_program
        """
        resp = api.create_care_program(_program_payload(), SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_care_coordinator_cannot_create_care_program(self, api):
        """PRD section 4: "POST | /care-programs | Create a care program | PlatformAdmin"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/care_coordinator_cannot_create_care_program
        """
        resp = api.create_care_program(_program_payload(), COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_clinician_cannot_create_care_program(self, api):
        """PRD section 4: "POST | /care-programs | Create a care program | PlatformAdmin"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/clinician_cannot_create_care_program
        """
        # The Clinician role is identity-bound; use a registered clinician's id.
        program = create_program()
        clinician = create_clinician(program["id"])
        resp = api.create_care_program(
            _program_payload(), make_clinician_headers(clinician["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_performance_analyst_cannot_create_care_program(self, api):
        """PRD section 4: "POST | /care-programs | Create a care program | PlatformAdmin"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/performance_analyst_cannot_create_care_program
        """
        resp = api.create_care_program(_program_payload(), ANALYST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestPayerContractRBAC:
    def test_contract_admin_can_create_payer_contract(self, api):
        """PRD section 4: "POST | /payer-contracts | Create a payer contract | ContractAdministrator"

        Design: Corner/rbac/contract_admin_can_create_payer_contract
        """
        program = create_program()
        resp = api.create_payer_contract(
            create_capitated_contract_payload(program["id"]), CONTRACT_ADMIN
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"]

    def test_platform_admin_cannot_create_payer_contract(self, api):
        """PRD section 4: "POST | /payer-contracts | Create a payer contract | ContractAdministrator"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/platform_admin_cannot_create_payer_contract
        """
        program = create_program()
        resp = api.create_payer_contract(
            create_capitated_contract_payload(program["id"]), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestMemberRBAC:
    def test_engagement_specialist_can_create_member(self, api):
        """PRD section 4: "POST | /members | Register a member from payer data feed | PlatformAdmin, EngagementSpecialist"

        Design: Corner/rbac/engagement_specialist_can_create_member
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        resp = api.create_member(
            create_member_payload(program["id"], contract["id"], pcp["id"]),
            SPECIALIST,
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"]

    def test_care_coordinator_cannot_create_member(self, api):
        """PRD section 4: "POST | /members | Register a member from payer data feed | PlatformAdmin, EngagementSpecialist"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/care_coordinator_cannot_create_member
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        resp = api.create_member(
            create_member_payload(program["id"], contract["id"], pcp["id"]),
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_clinician_cannot_create_member(self, api):
        """PRD section 4: "POST | /members | Register a member from payer data feed | PlatformAdmin, EngagementSpecialist"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/clinician_cannot_create_member
        """
        program, contract, pcp, np = setup_basic_reference()
        resp = api.create_member(
            create_member_payload(program["id"], contract["id"], pcp["id"]),
            make_clinician_headers(np["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestEnrollmentRBAC:
    def test_engagement_specialist_can_create_enrollment(self, api):
        """PRD section 4: "POST | /members/{memberId}/enrollments | Create a new enrollment (CREATE-with-supersede; OCC on member) | EngagementSpecialist"

        Design: Corner/rbac/engagement_specialist_can_create_enrollment
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        assert enrollment["id"]

    def test_care_coordinator_cannot_create_enrollment(self, api):
        """PRD section 4: "POST | /members/{memberId}/enrollments | Create a new enrollment (CREATE-with-supersede; OCC on member) | EngagementSpecialist"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/care_coordinator_cannot_create_enrollment
        """
        from test_helpers import create_member
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        member = create_member(program["id"], contract["id"], pcp["id"])
        resp = api.create_enrollment(
            member["id"],
            {"outreach_channel": "PHONE", "expected_member_version": member["version"]},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestVisitRBAC:
    def test_care_coordinator_can_create_visit(self, api):
        """PRD section 4: "POST | /visits | Schedule a new visit | CareCoordinator"

        Design: Corner/rbac/care_coordinator_can_create_visit
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        assert visit["id"]
        assert visit["status"] == "SCHEDULED"

    def test_engagement_specialist_cannot_create_visit(self, api):
        """PRD section 4: "POST | /visits | Schedule a new visit | CareCoordinator"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/engagement_specialist_cannot_create_visit
        """
        ctx = setup_active_enrollment()
        resp = api.create_visit(
            {
                "enrollment_id": ctx["enrollment"]["id"],
                "visit_type": "ROUTINE_FOLLOWUP",
                "scheduled_start": "2026-09-02T09:00:00Z",
                "scheduled_end": "2026-09-02T10:00:00Z",
            },
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_clinician_can_depart_own_visit(self, api):
        """PRD section 3.5: "The clinician marks departure, moving the visit to `EN_ROUTE`; the call requires the visit really be `SCHEDULED` (else `ERR_VISIT_NOT_SCHEDULED`) and the caller's `X-User-ID` to equal the visit's `clinician_id` (else `ERR_NOT_ASSIGNED_CLINICIAN`)."

        Design: Corner/rbac/clinician_can_depart_own_visit
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        data = validate_success(api.depart_visit(
            visit["id"], make_clinician_headers(visit["clinician_id"])
        ))
        assert data["status"] == "EN_ROUTE"

    def test_care_coordinator_cannot_depart_visit(self, api):
        """PRD section 4: "POST | /visits/{visitId}/depart | Clinician departs for visit (SCHEDULED → EN_ROUTE) | Clinician"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/care_coordinator_cannot_depart_visit
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        resp = api.depart_visit(visit["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestPerformanceAnalystRBAC:
    def test_performance_analyst_read_only(self, api):
        """PRD section 4: "POST | /care-programs | Create a care program | PlatformAdmin"
        PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/performance_analyst_read_only
        """
        resp = api.create_care_program(_program_payload(), ANALYST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_performance_analyst_can_read_performance_measurements(self, api):
        """PRD section 4: "GET | /performance-measurements | List performance measurement rows | PlatformAdmin, ContractAdministrator, PerformanceAnalyst"

        Design: Corner/rbac/performance_analyst_can_read_performance_measurements
        """
        resp = api.list_performance_measurements(ANALYST)
        validate_success(resp)
