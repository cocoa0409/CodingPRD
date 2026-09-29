"""
Where a lifecycle begins, where it refuses to go, and where it forks and rejoins.

Each record opens in one declared state with its counters at zero; each transition is
declared from a named set of states and from nowhere else. These tests take the first
step, take a step that is not on the map, and walk the one review fork that comes back
with different numbers than it left with.
"""

from test_helpers import (
    AHJ_HEADERS,
    CLOCK_EPOCH,
    ApiErrorId,
    ApplicationStatus,
    BuildStatus,
    EnrollmentStatus,
    GridStatus,
    JurisdictionCode,
    LoadCalcStatus,
    PermitStatus,
    assert_instant_equals,
    assert_quantity,
    assert_stamped_from_clock,
    assert_status_pair,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

PERMIT_EXPIRY = "2027-06-30T00:00:00.000Z"


class TestOpeningStates:
    """The first state of a record, and the counters that start at zero with it."""

    def test_a_new_permit_opens_as_a_draft_with_no_correction_rounds(self, api):
        """The permit starts where the authority has not yet seen it.

        Opening a permit against a frozen design leaves it in the authority's inbox as a draft
        rather than as a submission, with no correction rounds behind it and neither the
        issuance instant nor the validity window nor any findings recorded yet. The bank's own
        state does not colour the permit's.

        PRD 3.4: "The permit opens in `DRAFT` with `correction_round_count` at zero and with `issued_at`, `expires_on` and `inspection_findings` all unset."

        Design: Corner/state_machines/newly_created_permit_starts_in_draft_with_zero_correction_rounds
        """
        project = fixtures.design_locked_project(api)

        permit = validate_success(
            api.create_permit(
                factories.permit_payload(
                    project.battery_system_id,
                    jurisdiction_code=JurisdictionCode.AHJ_COUNTY,
                    plan_set_ref="PS-2790-B",
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert permit["status"] == PermitStatus.DRAFT
        assert permit["correction_round_count"] == 0
        assert_unset(permit, "issued_at", "expires_on", "inspection_findings")

    def test_issuing_a_permit_stamps_the_untouched_logical_clock(self, api):
        """No client has moved the clock, so the issuance instant is the mandated default.

        The authority issues the permit with a validity window a year out. The issuance instant
        is taken from the logical clock, which has never been set in this scenario and therefore
        still reads its startup value rather than any wall-clock time, and the supplied expiry is
        stored as given. Issuing is not a correction, so the correction counter stays at zero.

        PRD 3.4: "On issuance the permit moves `SUBMITTED → ISSUED`, `issued_at` is stamped from the logical clock and `expires_on` takes the supplied value."
        PRD 2.5: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/state_machines/permit_issue_stamps_issued_at_from_the_default_logical_clock_and_expiry
        """
        project = fixtures.design_locked_project(api)
        project = fixtures.submitted_permit(api, project)

        permit = validate_success(
            api.review_permit(
                project.permit_id,
                factories.permit_issue_payload(expires_on=PERMIT_EXPIRY),
                headers=AHJ_HEADERS,
            )
        )

        assert permit["status"] == PermitStatus.ISSUED
        assert_stamped_from_clock(permit, "issued_at", CLOCK_EPOCH)
        assert permit["expires_on"] == PERMIT_EXPIRY
        assert permit["correction_round_count"] == 0

    def test_submitting_the_application_advances_only_the_grid_dimension(self, api):
        """One request writes two rows, and leaves the build dimension alone.

        Filing the application with the utility moves the application itself to submitted and,
        in the same request, moves the bank's interconnection dimension to match. The bank's
        physical dimension is untouched: it is still a frozen design that has not been built.
        No supplemental round has been requested.

        PRD 3.5: "Submission also advances the bank's grid dimension to `APPLICATION_SUBMITTED`, whether the bank was previously at `NOT_APPLIED` or already at `APPLICATION_SUBMITTED`."
        PRD 3.5: "The application opens in `DRAFT` with `supplemental_round_count` at zero and with `approved_export_kw`, `reviewed_by_user_id`, `pto_granted_by_user_id` and `pto_granted_at` all unset."
        PRD 2.8: "Neither dimension implies anything about the other."

        Design: Corner/state_machines/submit_application_moves_system_grid_status_to_application_submitted
        """
        project = fixtures.permit_issued_project(api)
        project = fixtures.open_application(api, project)

        application = validate_success(
            api.submit_application(
                project.application_id, headers=project.installer_headers
            )
        )

        assert application["status"] == ApplicationStatus.SUBMITTED
        assert application["supplemental_round_count"] == 0
        system = fixtures.read_system(api, project)
        assert_status_pair(
            system, BuildStatus.DESIGN_LOCKED, GridStatus.APPLICATION_SUBMITTED
        )


class TestTransitionsThatAreNotOnTheMap:
    """A transition declared from one set of states is available from nowhere else."""

    def test_freezing_a_design_that_has_already_been_built_is_refused(self, api):
        """Locking runs from draft only, so a built bank cannot be locked again.

        The bank has been through permitting, the utility's approval and physical installation.
        Locking is declared out of the draft state alone, so it is not available here, and the
        refusal is the build dimension's own objection. Neither dimension moves.

        PRD 3.3: "A bank in `DESIGN_HOLD` or `SUPERSEDED` accepts no further build-lifecycle operation; attempts are rejected with `ERR_SYSTEM_BUILD_STATE_INVALID`, as is any build operation requested from a build state that does not declare it — commissioning a merely design-locked bank, for instance, or expanding one that is not yet commissioned."
        PRD 3.3: "**Locking the design.** Freezing the design advances the bank `DESIGN_DRAFT → DESIGN_LOCKED`, and it re-checks the same three prerequisites in the same order — the approved-calculation check, the capacity-sufficiency check, and the installer's certification standing, including that the certification has not expired since the design was drawn and that the model is still covered."
        PRD 2.8: "an operation blocked by the build dimension is rejected with `ERR_SYSTEM_BUILD_STATE_INVALID`, while an operation blocked by the grid dimension is rejected with `ERR_SYSTEM_GRID_STATE_INVALID`. Both carry HTTP 409."

        Design: Corner/state_machines/lock_design_from_installed_state_rejected
        """
        project = fixtures.installed_project(api)

        validate_error(
            api.lock_design(project.battery_system_id, headers=project.installer_headers),
            ApiErrorId.ERR_SYSTEM_BUILD_STATE_INVALID,
            expected_status=409,
        )

        system = fixtures.read_system(api, project)
        assert_status_pair(system, BuildStatus.INSTALLED, GridStatus.APPROVED_TO_INSTALL)

    def test_consenting_twice_is_refused_and_does_not_restamp_the_first_consent(self, api):
        """The household has already said yes, and saying it again is not a transition.

        Consent is declared out of the awaiting-consent state only, so replaying it against an
        active enrollment is rejected. The identity and the instant recorded by the first
        consent are exactly as they were, not overwritten by the refused second call.

        PRD 3.9: "Consent moves the enrollment `PENDING_CONSENT → ENROLLED`, requires the caller's `X-User-ID` to equal the `site_id` of the bank being enrolled, requires the bank's `grid_status` to still be `PTO_GRANTED`, and records `consented_by_user_id` from the caller's `X-User-ID` together with `consented_at` from the logical clock."
        PRD 3.9: "An enrollment that a cascade has moved to `SUSPENDED` accepts neither consent nor withdrawal; those and any other undeclared transition are rejected with `ERR_ENROLLMENT_STATE_INVALID`."

        Design: Corner/state_machines/second_consent_on_an_already_enrolled_enrollment_rejected
        """
        project = fixtures.enrolled_project(api)
        before = get_success_data(
            api.get_enrollment(project.enrollment_id, headers=project.homeowner_headers)
        )

        validate_error(
            api.consent_enrollment(
                project.enrollment_id, headers=project.homeowner_headers
            ),
            ApiErrorId.ERR_ENROLLMENT_STATE_INVALID,
            expected_status=409,
        )

        after = get_success_data(
            api.get_enrollment(project.enrollment_id, headers=project.homeowner_headers)
        )
        assert after["status"] == EnrollmentStatus.ENROLLED
        assert after["consented_by_user_id"] == project.site_id
        assert_instant_equals(
            after["consented_at"], before["consented_at"], "consented_at"
        )

    def test_resubmitting_an_approved_calculation_is_refused_and_recomputes_nothing(self, api):
        """Approval is the end of the sizing story, overrides and all.

        The submission carries an override that would change the heating input and therefore the
        connected load, but submission is declared only out of the draft and revision-required
        states. The calculation stays approved with the figures the authority signed off, and
        no revision round is recorded.

        PRD 3.2: "`APPROVE` moves the calculation `SUBMITTED → APPROVED`, which is terminal — an approved calculation can neither be resubmitted nor reviewed again."
        PRD 3.2: "Submitting a calculation that is not in `DRAFT` or `REVISION_REQUIRED`, or reviewing one that is not `SUBMITTED`, is rejected with `ERR_LOAD_CALC_STATE_INVALID`."

        Design: Corner/state_machines/approved_load_calculation_is_terminal_and_rejects_resubmit
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)
        project = fixtures.approved_load_calculation(api, project)

        validate_error(
            api.submit_load_calculation(
                project.load_calculation_id,
                {"heating_va": 1200},
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_LOAD_CALC_STATE_INVALID,
            expected_status=409,
        )

        calculation = get_success_data(
            api.get_load_calculation(
                project.load_calculation_id, headers=project.installer_headers
            )
        )
        assert calculation["status"] == LoadCalcStatus.APPROVED
        assert_quantity(calculation, "connected_load_kw", 21.48)
        assert calculation["revision_round_count"] == 0

    def test_a_pledge_larger_than_the_banks_continuous_rating_is_refused(self, api):
        """Twelve kilowatts offered from a bank that can hold ten is not a pledge.

        The bank is energized and eligible, and the reserve floor is in range, so the only thing
        wrong with the enrollment is the size of the pledge, which exceeds what the two-unit bank
        can sustain. Nothing is enrolled.

        PRD 3.9: "The pledge itself is bounded: `pledged_kw` must be greater than zero and must not exceed the bank's `continuous_kw`, and `reserve_soc_pct` must lie between 0 and 50 inclusive; either violation is rejected with `ERR_PLEDGE_EXCEEDS_CAPACITY`."
        PRD 2.11: "A bank's `usable_kwh` is its `unit_count` multiplied by the per-unit usable energy of its model, and its `continuous_kw` is its `unit_count` multiplied by the per-unit continuous power of its model, each rounded half up to two decimals."

        Design: Corner/state_machines/enrollment_pledge_above_bank_continuous_capacity_rejected
        """
        project = fixtures.pto_granted_project(api)

        validate_error(
            api.create_enrollment(
                factories.enrollment_payload(project.battery_system_id, pledged_kw=12.0),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_PLEDGE_EXCEEDS_CAPACITY,
            expected_status=422,
        )

        enrollments, _ = validate_paginated(
            api.list_enrollments(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert enrollments == [], "a refused enrollment left a row behind"


class TestTheReviewFork:
    """The revision arm of the review decision, and the join back through approval."""

    def test_the_revision_loop_recomputes_the_sizing_and_keeps_one_round(self, api):
        """Sent back once, resized on the way in, and approved with the count still at one.

        The authority sends the calculation back, which is what advances the round counter and
        stores the note. The installer resubmits with a corrected heating figure, and the sizing
        re-runs against the post-override inputs: the cooling figure now dominates the HVAC term,
        so the connected load falls from 21.48 to 19.08 while the essential-circuit requirements,
        which do not depend on it here, stay at 7.00 and 9.25. Approval closes the loop without
        touching the counter, which records only how many times the work was sent back.

        PRD 3.2: "`REQUEST_REVISION` moves it `SUBMITTED → REVISION_REQUIRED` and increments `revision_round_count` by one; the counter records how many times the authority sent the work back, so it advances on the review decision and not on the installer's resubmission."
        PRD 3.2: "any of `method`, `backup_scope`, `lighting_area_sqft`, `appliance_load_va`, `heating_va`, `cooling_va`, `measured_peak_kw` or `essential_circuits` supplied on the submission replaces the stored value first, and the sizing arithmetic then re-runs against the post-override values."
        PRD 3.2: "Separately, the HVAC term is the larger of `heating_va` and `cooling_va` — the smaller of the two is discarded, not added."

        Design: Corner/state_machines/load_calculation_revision_branch_recomputes_sizing_and_then_approves
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)
        created = validate_success(
            api.create_load_calculation(
                factories.load_calculation_payload(project.site_id),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )
        calc_id = created["id"]
        validate_success(
            api.submit_load_calculation(calc_id, headers=project.installer_headers)
        )

        sent_back = validate_success(
            api.review_load_calculation(
                calc_id,
                factories.load_calc_revision_payload(
                    reviewer_notes="Heating load overstated."
                ),
                headers=AHJ_HEADERS,
            )
        )
        assert sent_back["status"] == LoadCalcStatus.REVISION_REQUIRED
        assert sent_back["revision_round_count"] == 1
        assert sent_back["reviewer_notes"] == "Heating load overstated."

        resubmitted = validate_success(
            api.submit_load_calculation(
                calc_id, {"heating_va": 4800}, headers=project.installer_headers
            )
        )
        assert resubmitted["status"] == LoadCalcStatus.SUBMITTED
        assert_quantity(resubmitted, "connected_load_kw", 19.08)
        assert_quantity(resubmitted, "required_continuous_kw", 7.00)
        assert_quantity(resubmitted, "required_surge_kw", 9.25)

        approved = validate_success(
            api.review_load_calculation(
                calc_id,
                factories.load_calc_approval_payload(
                    reviewer_notes="Revised sizing verified."
                ),
                headers=AHJ_HEADERS,
            )
        )
        assert approved["status"] == LoadCalcStatus.APPROVED
        assert approved["revision_round_count"] == 1
