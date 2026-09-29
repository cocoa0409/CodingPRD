"""
Writes blocked by the state of a neighbouring record.

In each case the request itself is impeccable and the target record is in the right state;
what refuses the write is a second entity, often owned by a different role. The gate is
proved twice over: the refusal while the neighbour is unready, and the success once it is.
"""

from test_helpers import (
    AHJ_HEADERS,
    UTILITY_REVIEWER_2_HEADERS,
    ApiErrorId,
    ApplicationStatus,
    BuildStatus,
    EnrollmentStatus,
    GridStatus,
    LoadCalcStatus,
    PermitStatus,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPermissionToOperateNeedsAPassedInspection:
    """The utility will not energize a bank whose inspection has not passed."""

    def _commissioned_without_an_inspection(self, api):
        """A fully tested, commissioned bank whose permit is still merely issued."""
        project = fixtures.tests_recorded_project(api)
        project = fixtures.advance_clock(api, project, fixtures.COMMISSIONING_INSTANT)
        validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )
        return project

    def test_the_grant_is_refused_while_the_permit_has_only_been_issued(self, api):
        """A different entity, owned by a different role, blocks the utility's own write.

        The application is exactly where the grant expects it and the bank has been
        commissioned, so the only unmet condition is the state of the permit: the authority
        has issued it but has recorded no inspection outcome. The application keeps its
        status and neither permission field is written.

        PRD 3.5: "The bank's permit must be in `INSPECTION_PASSED`, else `ERR_PERMIT_NOT_PASSED`."
        PRD 3.5: "The application opens in `DRAFT` with `supplemental_round_count` at zero and with `approved_export_kw`, `reviewed_by_user_id`, `pto_granted_by_user_id` and `pto_granted_at` all unset."

        Design: Difficulty/cross_entity_state_dependency/grant_pto_rejected_until_permit_reaches_inspection_passed
        """
        project = self._commissioned_without_an_inspection(api)

        validate_error(
            api.grant_pto(project.application_id, headers=UTILITY_REVIEWER_2_HEADERS),
            ApiErrorId.ERR_PERMIT_NOT_PASSED,
            expected_status=422,
        )

        application = get_success_data(
            api.get_application(project.application_id, headers=UTILITY_REVIEWER_2_HEADERS)
        )
        assert application["status"] == ApplicationStatus.APPROVED_TO_INSTALL
        assert_unset(application, "pto_granted_by_user_id", "pto_granted_at")

    def test_the_same_grant_succeeds_once_the_inspection_has_passed(self, api):
        """Recording the pass is the only change, and it is enough.

        The refused grant left the bank's grid dimension at the utility's approval. Once the
        authority records a passing inspection — nothing else about the bank or the
        application changes — the identical request advances both the application and the
        bank's grid dimension to permission granted.

        PRD 3.5: "The final utility step is the permission-to-operate grant, which moves the application `APPROVED_TO_INSTALL → PTO_GRANTED` and the bank's `grid_status` likewise from `APPROVED_TO_INSTALL` to `PTO_GRANTED`."
        PRD 3.4: "A `PASS` may be recorded from `ISSUED` or from `INSPECTION_FAILED`, in both cases landing on `INSPECTION_PASSED`"

        Design: Difficulty/cross_entity_state_dependency/grant_pto_rejected_until_permit_reaches_inspection_passed
        """
        project = self._commissioned_without_an_inspection(api)
        validate_error(
            api.grant_pto(project.application_id, headers=UTILITY_REVIEWER_2_HEADERS),
            ApiErrorId.ERR_PERMIT_NOT_PASSED,
        )
        blocked_system = fixtures.read_system(api, project)
        assert blocked_system["grid_status"] == GridStatus.APPROVED_TO_INSTALL

        permit = validate_success(
            api.record_inspection_result(
                project.permit_id, factories.inspection_pass_payload(), headers=AHJ_HEADERS
            )
        )
        assert permit["status"] == PermitStatus.INSPECTION_PASSED

        granted = validate_success(
            api.grant_pto(project.application_id, headers=UTILITY_REVIEWER_2_HEADERS)
        )
        assert granted["status"] == ApplicationStatus.PTO_GRANTED
        system = fixtures.read_system(api, project)
        assert system["grid_status"] == GridStatus.PTO_GRANTED


class TestEnrollmentNeedsPermissionToOperate:
    """A commissioned bank is not a dispatchable bank until the utility says so."""

    def _commissioned_without_permission(self, api):
        return fixtures.commissioned_project(api)

    def _enrollment_attempt(self, api, project):
        return api.create_enrollment(
            factories.enrollment_payload(project.battery_system_id),
            headers=project.installer_headers,
        )

    def test_enrollment_is_refused_while_the_grid_dimension_stops_at_approval(self, api):
        """Both dimensions are read, and only one of them is far enough along.

        The pledge is within the bank's continuous rating and the reserve floor is in range,
        so the enrollment's own inputs are sound. The build dimension has reached
        commissioning but the grid dimension has only reached the utility's approval, and
        dispatch enrollment requires permission to operate.

        PRD 3.9: "Enrollment presupposes a fully energized bank: the bank must be both `COMMISSIONED` on the build dimension and `PTO_GRANTED` on the grid dimension, else `ERR_ENROLLMENT_REQUIRES_PTO`."
        PRD 2.12: "BYOD enrollment requires a commissioned, permission-granted bank (`ERR_ENROLLMENT_REQUIRES_PTO`)"

        Design: Difficulty/cross_entity_state_dependency/byod_enrollment_rejected_when_system_commissioned_without_pto
        """
        project = self._commissioned_without_permission(api)

        validate_error(
            self._enrollment_attempt(api, project),
            ApiErrorId.ERR_ENROLLMENT_REQUIRES_PTO,
            expected_status=422,
        )

        system = fixtures.read_system(api, project)
        assert system["build_status"] == BuildStatus.COMMISSIONED
        assert system["grid_status"] == GridStatus.APPROVED_TO_INSTALL

    def test_no_enrollment_row_is_written_and_the_grant_unblocks_it(self, api):
        """The refusal leaves nothing behind, and permission is the only missing ingredient.

        Listing the bank's enrollments after the refusal returns nothing at all. Once the
        utility grants permission to operate, the identical enrollment request is accepted and
        opens awaiting the household's consent.

        PRD 3.9: "A new enrollment opens in `PENDING_CONSENT` with `cumulative_credited_kw`, `cumulative_pledged_kw`, `season_compliance_ratio`, `settled_event_count` and `performance_payment_cents_total` all at zero and with `consented_by_user_id` and `consented_at` unset."
        PRD 2.4: "Because relationships are not visible in the URL structure, every foreign key has a corresponding filtered-list read."

        Design: Difficulty/cross_entity_state_dependency/byod_enrollment_rejected_when_system_commissioned_without_pto
        """
        project = self._commissioned_without_permission(api)
        validate_error(
            self._enrollment_attempt(api, project),
            ApiErrorId.ERR_ENROLLMENT_REQUIRES_PTO,
        )

        enrollments, _ = validate_paginated(
            api.list_enrollments(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert enrollments == [], "a refused enrollment left a row behind"

        fixtures.grant_pto(api, project)
        enrollment = validate_success(
            self._enrollment_attempt(api, project), expected_status=201
        )
        assert enrollment["status"] == EnrollmentStatus.PENDING_CONSENT


class TestDesignNeedsAnApprovedCalculation:
    """A creation-time gate on the parent's state, not on its existence."""

    def _submitted_calculation(self, api):
        """A sizing calculation filed with the authority but not yet reviewed."""
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)
        calc = validate_success(
            api.create_load_calculation(
                factories.load_calculation_payload(project.site_id),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )
        project.load_calculation_id = calc["id"]
        validate_success(
            api.submit_load_calculation(
                project.load_calculation_id, headers=project.installer_headers
            )
        )
        return project

    def _design_attempt(self, api, project):
        return api.create_battery_system(
            factories.battery_system_payload(
                project.site_id, project.installer_id, project.load_calculation_id
            ),
            headers=project.installer_headers,
        )

    def test_a_design_on_an_unapproved_calculation_is_refused(self, api):
        """The referenced calculation exists and matches the site; it is simply not approved.

        The installer is in good standing and the payload names a real calculation for the
        right premises, but that calculation is still waiting on the electrical authority.
        The calculation is left exactly where it was.

        PRD 3.3: "Second, the referenced load calculation must be `APPROVED` and must belong to the same site as the bank, else `ERR_LOAD_CALC_NOT_APPROVED`."
        PRD 2.12: "In this internal order: installer certification (`ERR_INSTALLER_NOT_CERTIFIED`), then load-calculation approval (`ERR_LOAD_CALC_NOT_APPROVED`), then capacity sufficiency (`ERR_CAPACITY_BELOW_REQUIRED`)"

        Design: Difficulty/cross_entity_state_dependency/battery_system_creation_rejected_while_load_calculation_only_submitted
        """
        project = self._submitted_calculation(api)

        validate_error(
            self._design_attempt(api, project),
            ApiErrorId.ERR_LOAD_CALC_NOT_APPROVED,
            expected_status=422,
        )

        calculation = get_success_data(
            api.get_load_calculation(
                project.load_calculation_id, headers=project.installer_headers
            )
        )
        assert calculation["status"] == LoadCalcStatus.SUBMITTED

    def test_no_bank_is_written_and_approval_unblocks_the_identical_design(self, api):
        """The refusal creates nothing, and the authority's approval is what changes.

        Nothing is discoverable against the calculation after the refusal. Once the authority
        approves it, the same design payload is accepted and the bank opens as a draft.

        PRD 3.2: "`APPROVE` moves the calculation `SUBMITTED → APPROVED`"
        PRD 3.3: "A new bank opens at `build_status` of `DESIGN_DRAFT` and `grid_status` of `NOT_APPLIED`, with `warranty_status` of `UNREGISTERED`, `verified_capacity_kwh` unset, and `expands_system_id` null because it is an original build rather than an expansion."

        Design: Difficulty/cross_entity_state_dependency/battery_system_creation_rejected_while_load_calculation_only_submitted
        """
        project = self._submitted_calculation(api)
        validate_error(
            self._design_attempt(api, project), ApiErrorId.ERR_LOAD_CALC_NOT_APPROVED
        )

        banks, _ = validate_paginated(
            api.list_battery_systems(
                {"load_calculation_id": project.load_calculation_id},
                headers=project.installer_headers,
            )
        )
        assert banks == [], "a refused design left a bank behind"

        validate_success(
            api.review_load_calculation(
                project.load_calculation_id,
                factories.load_calc_approval_payload(),
                headers=AHJ_HEADERS,
            )
        )
        system = validate_success(self._design_attempt(api, project), expected_status=201)
        assert system["build_status"] == BuildStatus.DESIGN_DRAFT
        assert system["grid_status"] == GridStatus.NOT_APPLIED
