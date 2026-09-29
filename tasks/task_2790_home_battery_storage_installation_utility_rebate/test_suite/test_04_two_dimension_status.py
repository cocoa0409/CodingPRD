"""
Two status dimensions on one row, moving independently.

A bank's build story and its utility story live on the same record and never imply each
other. These tests walk the whole interconnection sequence with the build dimension
frozen, then move the build dimension with the utility dimension frozen.
"""

from test_helpers import (
    UTILITY_REVIEWER_HEADERS,
    ApplicationStatus,
    BuildStatus,
    GridStatus,
    WarrantyStatus,
    assert_quantity,
    assert_status_pair,
    assert_unset,
    factories,
    fixtures,
    validate_success,
)


class TestDimensionsAdvanceIndependently:
    """Neither dimension is derivable from the other."""

    def _approved_application(self, api, project):
        project = fixtures.submitted_application(api, project)
        return validate_success(
            api.review_application(
                project.application_id,
                factories.application_approval_payload(approved_export_kw=6.5),
                headers=UTILITY_REVIEWER_HEADERS,
            )
        )

    def test_the_interconnection_sequence_moves_only_the_grid_dimension(self, api):
        """Filing, submitting and winning approval leaves the build dimension untouched.

        The bank starts design-locked with no utility relationship at all. Submitting the
        application and taking it to approval carries the grid dimension two steps forward,
        while the build dimension is still exactly where locking left it.

        PRD 2.8: "Neither dimension implies anything about the other."
        PRD 3.5: "Submission also advances the bank's grid dimension to `APPLICATION_SUBMITTED`, whether the bank was previously at `NOT_APPLIED` or already at `APPLICATION_SUBMITTED`."
        PRD 3.5: "`APPROVE_TO_INSTALL` moves the application `SUBMITTED → APPROVED_TO_INSTALL` and the bank `APPLICATION_SUBMITTED → APPROVED_TO_INSTALL`."

        Design: Difficulty/non_linear_state_machine/battery_system_build_and_grid_dimensions_advance_independently
        """
        project = fixtures.permit_issued_project(api)
        before = fixtures.read_system(api, project)
        assert_status_pair(before, BuildStatus.DESIGN_LOCKED, GridStatus.NOT_APPLIED)

        application = self._approved_application(api, project)

        assert application["status"] == ApplicationStatus.APPROVED_TO_INSTALL
        assert_quantity(application, "approved_export_kw", 6.5)
        system = fixtures.read_system(api, project)
        assert_status_pair(
            system, BuildStatus.DESIGN_LOCKED, GridStatus.APPROVED_TO_INSTALL
        )

    def test_marking_installed_moves_only_the_build_dimension(self, api):
        """Physical completion advances the build story and leaves the grid story alone.

        With the utility's approval already on record, marking the bank installed moves the
        build dimension one step and holds the grid dimension where the approval put it. The
        warranty dimension has not started at all and there is no commissioning instant yet.

        PRD 2.8: "advancing one dimension never advances the other by itself"
        PRD 3.3: "Physical completion advances the bank `DESIGN_LOCKED → INSTALLED`, and it is the first place where the two status dimensions interlock."
        PRD 3.3: "Like locking, marking installed writes nothing outside the bank row."

        Design: Difficulty/non_linear_state_machine/battery_system_build_and_grid_dimensions_advance_independently
        """
        project = fixtures.permit_issued_project(api)
        self._approved_application(api, project)

        validate_success(
            api.mark_installed(project.battery_system_id, headers=project.installer_headers)
        )

        system = fixtures.read_system(api, project)
        assert_status_pair(system, BuildStatus.INSTALLED, GridStatus.APPROVED_TO_INSTALL)
        assert system["warranty_status"] == WarrantyStatus.UNREGISTERED
        assert_unset(system, "commissioned_at", "verified_capacity_kwh")
