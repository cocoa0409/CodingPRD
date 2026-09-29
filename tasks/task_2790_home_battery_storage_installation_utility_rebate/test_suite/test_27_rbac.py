"""
Who may act: the whole role table once through, then the three ways a caller is refused.

The first pass proves each of the six roles can perform the operation reserved to it. The
next proves those reservations are exclusive. The last two prove that holding the right role
is only the beginning: an entity-backed role must also own what it touches, and on the two
countersigned decisions the acting operator must not be the one being countersigned.
"""

from test_helpers import (
    AHJ_HEADERS,
    REBATE_ADMIN_2_HEADERS,
    REBATE_ADMIN_HEADERS,
    REBATE_ADMIN_ID,
    UTILITY_REVIEWER_2_HEADERS,
    UTILITY_REVIEWER_2_ID,
    UTILITY_REVIEWER_HEADERS,
    UTILITY_REVIEWER_ID,
    WARRANTY_AGENT_HEADERS,
    ApiErrorId,
    ApplicationStatus,
    BuildStatus,
    CertificationLevel,
    ClaimStatus,
    ExportMode,
    GridStatus,
    PermitStatus,
    assert_cents,
    assert_program_ledger,
    assert_quantity,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

MISSING_PROGRAM = "dddddddd-dddd-dddd-dddd-dddddddddddd"

RIVAL_COMPANY = dict(company_name="Rival Storage Co")


class TestEachRolePerformsTheOperationReservedToIt:
    """Six callers, six endpoints, six successes, no refusals anywhere."""

    def test_authority_installer_reviewer_administrator_desk_and_household_all_succeed(
        self, api
    ):
        """The bank goes from tested to energized through five different pairs of hands.

        The jurisdiction records the passing inspection; the accountable installer commissions
        the bank; a reviewer other than the approving one grants permission to operate and is
        recorded as having done so; the rebate desk publishes a funded program, the one creation
        among the six and therefore the one 201; the manufacturer's warranty desk demotes the
        certification level it granted, leaving the covered models it did not mention alone; and
        the household reads its own bank. Every one of the six is authorized for exactly the
        endpoint it called.

        PRD 2.1: "If both headers are well formed but the named role is not among the roles authorized for the target endpoint (see the authorization column of §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 3.4: "A `PASS` may be recorded from `ISSUED` or from `INSPECTION_FAILED`, in both cases landing on `INSPECTION_PASSED`; recording a pass from `INSPECTION_FAILED` is the re-inspection path."
        PRD 3.5: "On success the grant records `pto_granted_by_user_id` from the caller's `X-User-ID` and stamps `pto_granted_at` from the logical clock."
        PRD 3.1: "Only the fields present in the amendment are replaced; anything omitted keeps its stored value, and the amendment advances the installer account's `version` by one."
        PRD 4: "An operation that brings a new resource into existence answers with HTTP 201 and the created resource in `data`; that includes the expansion endpoint, which creates a new battery system, and the participation endpoint, which creates a new dispatch performance."

        Design: Corner/rbac/each_of_the_six_roles_performs_its_own_exclusive_operation
        """
        project = fixtures.tests_recorded_project(api)
        project = fixtures.advance_clock(api, project, fixtures.COMMISSIONING_INSTANT)

        inspected = validate_success(
            api.record_inspection_result(
                project.permit_id, factories.inspection_pass_payload(), headers=AHJ_HEADERS
            )
        )
        commissioned = validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )
        energized = validate_success(
            api.grant_pto(project.application_id, headers=UTILITY_REVIEWER_2_HEADERS)
        )
        validate_success(
            api.create_program(
                factories.state_program_payload(), headers=REBATE_ADMIN_HEADERS
            ),
            expected_status=201,
        )
        installer_before = get_success_data(
            api.get_installer(project.installer_id, headers=WARRANTY_AGENT_HEADERS)
        )
        amended = validate_success(
            api.amend_certification(
                project.installer_id,
                factories.certification_amendment_payload(
                    certification_level=CertificationLevel.CERTIFIED
                ),
                headers=WARRANTY_AGENT_HEADERS,
            )
        )
        seen_by_household = validate_success(
            api.get_battery_system(
                project.battery_system_id, headers=project.homeowner_headers
            )
        )

        assert inspected["status"] == PermitStatus.INSPECTION_PASSED
        assert commissioned["build_status"] == BuildStatus.COMMISSIONED
        assert energized["status"] == ApplicationStatus.PTO_GRANTED
        assert energized["pto_granted_by_user_id"] == UTILITY_REVIEWER_2_ID
        assert amended["certification_level"] == CertificationLevel.CERTIFIED
        assert amended["certified_model_codes"] == installer_before["certified_model_codes"]
        assert amended["version"] == installer_before["version"] + 1
        assert seen_by_household["id"] == project.battery_system_id
        assert seen_by_household["grid_status"] == GridStatus.PTO_GRANTED


class TestThoseReservationsAreExclusive:
    """Four callers with the wrong role for the endpoint, refused before anything else."""

    def test_four_misdirected_calls_are_all_refused_on_the_role_alone(self, api):
        """None of the four gets far enough for its other defects to matter.

        The installer reviewing its own permit, the jurisdiction reserving an incentive, the
        household commissioning its own bank and the utility reviewer publishing a program are
        each refused for the role they hold. Two of the four would have failed for other reasons
        as well — the incentive reservation names a program that does not exist, and the bank is
        not ready to commission — but the role objection is decided before existence and before
        state, so the identifier returned is the role one in all four cases. Nothing was written:
        the permit is still issued, the bank is still merely installed, and no program exists.

        PRD 2.1: "If both headers are well formed but the named role is not among the roles authorized for the target endpoint (see the authorization column of §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.12: "**Role authorization.** The authenticated role is listed for the target endpoint, else `ERR_ROLE_NOT_PERMITTED`."
        PRD 2.12: "**Existence.** Every referenced resource resolves, path parameters left to right and then body foreign keys in declaration order, each miss raising that entity's own 404."
        PRD 2.12: "When more than one objection applies to a single request, exactly one is reported, and the choice is not arbitrary."

        Design: Corner/rbac/cross_role_exclusive_operations_rejected_with_role_not_permitted
        """
        project = fixtures.installed_project(api)
        version = fixtures.system_version(api, project)

        attempts = [
            api.review_permit(
                project.permit_id,
                factories.permit_issue_payload(),
                headers=project.installer_headers,
            ),
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id,
                    MISSING_PROGRAM,
                    version,
                    capacity_commitment_kw=8.0,
                    export_commitment=ExportMode.LIMITED_EXPORT,
                ),
                headers=AHJ_HEADERS,
            ),
            api.commission(project.battery_system_id, headers=project.homeowner_headers),
            api.create_program(
                factories.state_program_payload(name="Illegitimate Program"),
                headers=UTILITY_REVIEWER_HEADERS,
            ),
        ]

        for response in attempts:
            validate_error(
                response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403
            )

        permit = get_success_data(
            api.get_permit(project.permit_id, headers=project.installer_headers)
        )
        assert permit["status"] == PermitStatus.ISSUED
        system = fixtures.read_system(api, project)
        assert system["build_status"] == BuildStatus.INSTALLED
        programs, meta = validate_paginated(
            api.list_programs(headers=REBATE_ADMIN_HEADERS)
        )
        assert programs == [], "a refused creation published a program"
        assert meta["total_count"] == 0


class TestTheRightRoleIsNotEnoughForAnEntityBackedOne:
    """A second, equally certified company is still a stranger to this bank."""

    def test_a_rival_installer_is_refused_as_a_non_owner_before_the_permit_state_is_read(
        self, api
    ):
        """The permit is not submittable either, and that is not what the caller is told.

        The rival company holds exactly the role the endpoint requires, so the role check
        passes; what it does not hold is the bank the permit covers, and ownership is decided
        before state. The permit is in issued standing, from which submission is not declared, so
        a server that checked state first would answer with the permit's own state objection.
        The answer is the ownership one, and the permit is untouched.

        PRD 2.1: "For requests that name an existing resource in the path, an entity-backed role must own the resource it is acting on."
        PRD 2.1: "A `CertifiedInstaller`'s `X-User-ID` must equal the `installer_id` of the battery system in question, or the `installer_id` of the system reachable from the target load calculation, permit, interconnection application, rebate claim, commissioning test, monitoring alert or BYOD enrollment."
        PRD 2.12: "**Ownership.** Entity-backed roles own the addressed resource, else `ERR_NOT_RESOURCE_OWNER`."
        PRD 3.4: "Reviewing a permit that is not `SUBMITTED`, or submitting one that is neither `DRAFT` nor `CORRECTIONS_REQUIRED`, is rejected with `ERR_PERMIT_STATE_INVALID`."

        Design: Corner/rbac/installer_acting_on_another_installers_system_rejected_as_not_owner
        """
        project = fixtures.installed_project(api)
        rival = fixtures.certified_installer(api, **RIVAL_COMPANY)
        assert rival.installer_id != project.installer_id

        validate_error(
            api.submit_permit(project.permit_id, headers=rival.installer_headers),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )

        permit = get_success_data(
            api.get_permit(project.permit_id, headers=project.installer_headers)
        )
        assert permit["status"] == PermitStatus.ISSUED


class TestTheTwoPersonRuleOnEnergisation:
    """The reviewer who approved the interconnection may not also energize it."""

    def test_the_approving_reviewer_is_refused_and_a_colleague_in_the_same_role_succeeds(
        self, api
    ):
        """Same role, same endpoint, same bank: the only difference is the person.

        The first reviewer recorded the approval, so its own identity is the one the grant
        excludes; the refusal is not about roles, because a second reviewer holding precisely the
        same role goes through immediately afterwards. Both identities end up on the
        application — the approver's where it always was, the granter's newly written — and the
        bank's grid dimension follows the application to permission granted.

        PRD 2.1: "The operator who grants permission to operate must not be the operator whose `X-User-ID` was recorded as the application's `reviewed_by_user_id`, and the operator who releases payment on a rebate claim must not be the operator whose `X-User-ID` was recorded as the claim's `approved_by_user_id`."
        PRD 2.12: "**Segregation of duties.** The acting operator is not the one whose decision is being countersigned, else `ERR_SEGREGATION_OF_DUTIES`. This applies to the permission-to-operate grant and to claim payment."
        PRD 3.5: "And the granting operator's `X-User-ID` must differ from the `reviewed_by_user_id` recorded at the approval, else `ERR_SEGREGATION_OF_DUTIES`. On success the grant records `pto_granted_by_user_id` from the caller's `X-User-ID` and stamps `pto_granted_at` from the logical clock."
        PRD 3.5: "The final utility step is the permission-to-operate grant, which moves the application `APPROVED_TO_INSTALL → PTO_GRANTED` and the bank's `grid_status` likewise from `APPROVED_TO_INSTALL` to `PTO_GRANTED`."

        Design: Corner/rbac/grant_pto_by_the_reviewer_who_approved_returns_segregation_of_duties
        """
        project = fixtures.commissioned_project(api)

        validate_error(
            api.grant_pto(project.application_id, headers=UTILITY_REVIEWER_HEADERS),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        granted = validate_success(
            api.grant_pto(project.application_id, headers=UTILITY_REVIEWER_2_HEADERS)
        )

        assert granted["status"] == ApplicationStatus.PTO_GRANTED
        assert granted["reviewed_by_user_id"] == UTILITY_REVIEWER_ID
        assert granted["pto_granted_by_user_id"] == UTILITY_REVIEWER_2_ID
        system = fixtures.read_system(api, project)
        assert system["grid_status"] == GridStatus.PTO_GRANTED


class TestTheTwoPersonRuleOnMoney:
    """The administrator who approved the award may not also release it."""

    def test_the_approving_administrator_is_refused_and_a_colleague_disburses_the_final_award(
        self, api
    ):
        """Four hundred and ten thousand eight hundred and fifty cents move, in a second pair of hands.

        The claim was reserved against the design energy for 423000 cents and re-priced at
        commissioning against the smaller measured 25.65 kilowatt-hours to 410850, so the sum
        that moves is the final figure and not the reservation. The administrator who approved is
        refused; a second administrator in the identical role releases the money. Both identities
        are on the claim afterwards, and the pool shows the whole final award disbursed, nothing
        held, and the unencumbered balance carrying back the 12150 cents the re-pricing released.

        PRD 2.1: "The operator who grants permission to operate must not be the operator whose `X-User-ID` was recorded as the application's `reviewed_by_user_id`, and the operator who releases payment on a rebate claim must not be the operator whose `X-User-ID` was recorded as the claim's `approved_by_user_id`."
        PRD 2.1: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD 3.7: "Payment moves an approved claim `APPROVED → PAID`. It must be performed by an operator whose `X-User-ID` differs from `approved_by_user_id`, records `paid_by_user_id` and stamps `paid_at` from the logical clock, and moves exactly `final_amount_cents` out of `reserved_budget_cents` and into `paid_budget_cents`."
        PRD 3.7: "At commissioning the basis is the smaller of the bank's design `usable_kwh` and its measured `verified_capacity_kwh`."
        PRD 3.7: "At commissioning the results are written as `basis_kwh_final` and `final_amount_cents`, and the final figure is clamped to the `reserved_amount_cents` already held, because the reservation is a ceiling and never a floor."

        Design: Corner/rbac/pay_claim_by_the_approving_administrator_returns_segregation_of_duties
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project)
        claim = fixtures.reserve_claim(api, project, program_id)
        assert_cents(claim, "reserved_amount_cents", 423000)
        project = fixtures.schedule_four_tests(api, project)
        project = fixtures.record_four_results(api, project)
        project = fixtures.pass_inspection(api, project)
        project = fixtures.advance_clock(api, project, fixtures.COMMISSIONING_INSTANT)
        validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )
        project = fixtures.grant_pto(api, project)
        project = fixtures.register_warranty(api, project)
        fixtures.submit_claim(api, project, claim["id"])
        approved = fixtures.approve_claim(api, claim["id"])
        assert approved["approved_by_user_id"] == REBATE_ADMIN_ID
        assert_cents(approved, "final_amount_cents", 410850)

        validate_error(
            api.pay_claim(claim["id"], headers=REBATE_ADMIN_HEADERS),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        paid = validate_success(api.pay_claim(claim["id"], headers=REBATE_ADMIN_2_HEADERS))

        assert paid["status"] == ClaimStatus.PAID
        assert_quantity(paid, "basis_kwh_final", 25.65)
        assert_cents(paid, "final_amount_cents", 410850)
        assert paid["approved_by_user_id"] == REBATE_ADMIN_ID
        assert paid["paid_by_user_id"] != REBATE_ADMIN_ID
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=4589150, reserved=0, paid=410850)
