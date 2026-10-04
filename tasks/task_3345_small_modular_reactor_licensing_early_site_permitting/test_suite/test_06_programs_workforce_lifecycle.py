"""Adequacy testing and the operator workforce pipeline: the failure loop's
cascade into procured lots, chronological result recording, attrition
regression of a graduating pipeline, DCA terminal lockdown, and role
authorization boundaries."""

from test_helpers import (
    ApiErrorId,
    APPLICANT,
    AUDITOR,
    COORDINATOR,
    DOE,
    INTERVENOR,
    NON_EXISTENT_UUID,
    PERMIT_APPLICANT,
    REVIEWER,
    SCM,
    assert_test_program,
    create_adequate_program,
    create_component_lot,
    create_dca,
    create_permit_in_hearings,
    create_pipeline,
    create_qualified_vendor,
    create_test_program,
    dca_payload,
    enroll_license,
    hearing_payload,
    read_component_lot,
    read_license,
    read_pipeline,
    read_test_program,
    test_program_payload,
    test_result_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramFailureCascade:
    """A FAIL on an ADEQUATE program rejects only its PROCURED lots."""

    def test_fail_cascades_rejection_to_procured_lots_only(self, api):
        """PRD §3.3: "if a `FAIL` is recorded against a program that had
        already reached `ADEQUATE`, the program likewise drops to
        `INSUFFICIENT` — and this regression cascades: every component lot
        referencing that program that is still in `PROCURED` status is
        transitioned to `REJECTED`, each lot's `version` incrementing."

        Design: Corner/state_machines/test_program_fail_cascade_rejects_procured_lots
        """
        dca = create_dca(api, docket_number="52-924")
        program = create_adequate_program(api, dca["id"], program_code="TP-9")
        vendor = create_qualified_vendor(api, name="Zeta Valves")
        lot_proc = create_component_lot(api, vendor["id"], program["id"], quantity=1)
        lot_del = create_component_lot(api, vendor["id"], program["id"], quantity=2)
        validate_success(api.deliver_component_lot(lot_del["id"], SCM))

        validate_success(
            api.record_test_result(
                program["id"],
                test_result_payload(outcome="FAIL", run_at="2026-09-10T00:00:00Z"),
                APPLICANT,
            ),
            201,
        )
        assert read_test_program(api, program["id"])["status"] == "INSUFFICIENT"
        assert read_component_lot(api, lot_proc["id"])["status"] == "REJECTED"
        # The conditional cascade touches only PROCURED lots.
        assert read_component_lot(api, lot_del["id"])["status"] == "DELIVERED"

    def test_fail_on_zero_pass_in_progress_leaves_status(self, api):
        """PRD §3.3: "A failing result on an `IN_PROGRESS` program with zero
        passes so far does not itself change the program's status."
        PRD §3.3: "If a `FAIL` is recorded against an `IN_PROGRESS` program
        that already has at least one passing result, the program drops to
        `INSUFFICIENT`."

        Design: Corner/state_machines/test_program_fail_cascade_rejects_procured_lots
        """
        dca = create_dca(api, docket_number="52-925")
        program = create_test_program(api, dca["id"], program_code="TP-2", required_tests=2)
        validate_success(api.start_test_program(program["id"], APPLICANT))
        # First recorded result is a FAIL with zero passes recorded.
        validate_success(
            api.record_test_result(
                program["id"],
                test_result_payload(outcome="FAIL", run_at="2026-09-05T00:00:00Z"),
                APPLICANT,
            ),
            201,
        )
        assert read_test_program(api, program["id"])["status"] == "IN_PROGRESS"
        # A FAIL after a pass drops the program to INSUFFICIENT.
        validate_success(
            api.record_test_result(
                program["id"],
                test_result_payload(outcome="PASS", run_at="2026-09-06T00:00:00Z"),
                APPLICANT,
            ),
            201,
        )
        validate_success(
            api.record_test_result(
                program["id"],
                test_result_payload(outcome="FAIL", run_at="2026-09-07T00:00:00Z"),
                APPLICANT,
            ),
            201,
        )
        assert read_test_program(api, program["id"])["status"] == "INSUFFICIENT"


class TestChronologicalResults:
    """Results may not be backfilled out of order."""

    def test_earlier_run_at_rejected_and_not_counted(self, api):
        """PRD §3.3: "Chronological recording is enforced: a result whose
        `run_at` precedes an earlier result of the same program is rejected
        with `ERR_OUT_OF_ORDER_RESULT` (HTTP 422) — the evidentiary record
        cannot be backfilled out of order."

        Design: Corner/calculations/out_of_order_test_result_rejected
        """
        dca = create_dca(api, docket_number="52-933")
        program = create_test_program(api, dca["id"], program_code="TP-1", required_tests=2)
        validate_success(api.start_test_program(program["id"], APPLICANT))
        validate_success(
            api.record_test_result(
                program["id"],
                test_result_payload(outcome="PASS", run_at="2026-09-10T00:00:00Z"),
                APPLICANT,
            ),
            201,
        )
        resp = api.record_test_result(
            program["id"],
            test_result_payload(outcome="PASS", run_at="2026-09-05T00:00:00Z"),
            APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_ORDER_RESULT, 422)
        assert read_test_program(api, program["id"])["completed_tests"] == 1

    def test_later_run_at_accepted_and_counted(self, api):
        """PRD §3.3: "Chronological recording is enforced: a result whose
        `run_at` precedes an earlier result of the same program is rejected
        with `ERR_OUT_OF_ORDER_RESULT` (HTTP 422) — the evidentiary record
        cannot be backfilled out of order."
        PRD §3.3: "When a `PASS` is recorded against an `IN_PROGRESS` program
        and the count of passing results thereby reaches `required_tests`, the
        program transitions to `ADEQUATE` — and that transition is the
        gate-opening event for procurement, since component lots may only be
        procured against an adequate program."

        Design: Corner/calculations/out_of_order_test_result_rejected
        """
        dca = create_dca(api, docket_number="52-934")
        program = create_test_program(api, dca["id"], program_code="TP-1", required_tests=2)
        validate_success(api.start_test_program(program["id"], APPLICANT))
        validate_success(
            api.record_test_result(
                program["id"],
                test_result_payload(outcome="PASS", run_at="2026-09-10T00:00:00Z"),
                APPLICANT,
            ),
            201,
        )
        validate_success(
            api.record_test_result(
                program["id"],
                test_result_payload(outcome="PASS", run_at="2026-09-11T00:00:00Z"),
                APPLICANT,
            ),
            201,
        )
        program = read_test_program(api, program["id"])
        assert program["completed_tests"] == 2
        assert program["status"] == "ADEQUATE"


class TestWorkforceAttrition:
    """Revocation below the requirement regresses a GRADUATING pipeline."""

    def test_revoke_regresses_graduating_pipeline_to_enrolling(self, api):
        """PRD §3.7: "A `LICENSED` or `ACTIVE` license may be revoked to the
        terminal `REVOKED` state; the pipeline's `graduates` is recomputed,
        and if the pipeline was `STAFFED` or `GRADUATING` and the count has
        fallen below `required_operators`, the pipeline regresses to
        `ENROLLING` and the cohort must be rebuilt before certification can
        proceed."

        Design: Corner/state_machines/workforce_attrition_regresses_pipeline
        """
        dca = create_dca(api, docket_number="52-923")
        pipeline = create_pipeline(api, dca["id"], required_operators=1)
        validate_success(api.start_training(pipeline["id"], COORDINATOR))
        lic = enroll_license(api, pipeline["id"], candidate_name="Op A")
        validate_success(api.license_operator(lic["id"], COORDINATOR))
        validate_success(api.advance_pipeline(pipeline["id"], COORDINATOR))
        mid = read_pipeline(api, pipeline["id"])
        assert mid["graduates"] == 1

        revoked = validate_success(api.revoke_operator(lic["id"], COORDINATOR))
        assert revoked["license_status"] == "REVOKED"
        after = read_pipeline(api, pipeline["id"])
        assert after["graduates"] == 0
        assert after["status"] == "ENROLLING"


class TestDcaTerminalLockdown:
    """A WITHDRAWN application accepts no further lifecycle transitions."""

    def test_enter_safety_review_on_withdrawn_rejected(self, api):
        """PRD §3.1: "A `DoeProgram` operator may withdraw the application
        from `SUBMITTED`, `SAFETY_REVIEW`, or `ADVANCED_REVIEW` — never from
        `CERTIFIED`, which is terminal alongside `WITHDRAWN`."

        Design: Corner/state_machines/dca_terminal_withdrawn_locks_transitions
        """
        dca = create_dca(api, docket_number="52-921")
        validate_success(api.withdraw_dca(dca["id"], DOE))
        resp = api.enter_safety_review(dca["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_certify_on_withdrawn_rejected(self, api):
        """PRD §3.1: "A `DoeProgram` operator may withdraw the application
        from `SUBMITTED`, `SAFETY_REVIEW`, or `ADVANCED_REVIEW` — never from
        `CERTIFIED`, which is terminal alongside `WITHDRAWN`."

        Design: Corner/state_machines/dca_terminal_withdrawn_locks_transitions
        """
        dca = create_dca(api, docket_number="52-927")
        validate_success(api.withdraw_dca(dca["id"], DOE))
        resp = api.certify_dca(dca["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestRbac:
    """Each operation admits only its declared role."""

    def test_intervenor_cannot_schedule_hearing(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted
        to perform the requested operation is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.6: "Hearings are scheduled by the applicant with a
        `scheduled_at` instant and a `location`."

        Design: Corner/rbac/intervenor_cannot_schedule_hearing
        """
        world = create_permit_in_hearings(api, docket_number="52-970")
        resp = api.schedule_hearing(
            world["permit"]["id"],
            hearing_payload(scheduled_at="2027-01-01T00:00:00Z", location="Hall"),
            INTERVENOR,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_intervenor_can_contend_hearing(self, api):
        """PRD §3.6: "Before that instant, a `PublicIntervenor` may contend
        the hearing — `SCHEDULED → CONTENDED` — and contention cascades: the
        parent permit, if in `HEARINGS`, regresses to `ENVIRONMENTAL_REVIEW`
        with its `version` incremented, forcing the owner to re-run
        environmental review before hearings resume."

        Design: Corner/rbac/intervenor_cannot_schedule_hearing
        """
        world = create_permit_in_hearings(
            api, hearing_at="2027-01-01T00:00:00Z", docket_number="52-972"
        )
        # The same role that may not schedule a hearing is the one role that
        # may contend it.
        contended = validate_success(api.contend_hearing(world["hearing"]["id"], INTERVENOR))
        assert contended["status"] == "CONTENDED"

    def test_dca_applicant_cannot_certify(self, api):
        """PRD §3.1: "The phase transitions belong to the regulator."
        PRD §2.1: "A request whose role is recognized but is not permitted to
        perform the requested operation is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/dca_applicant_cannot_certify
        """
        dca = create_dca(api, docket_number="52-971")
        resp = api.certify_dca(dca["id"], APPLICANT)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_dca_applicant_cannot_enter_safety_review(self, api):
        """PRD §3.1: "The phase transitions belong to the regulator. An
        `NrcReviewer` moves the application from `SUBMITTED` to
        `SAFETY_REVIEW` only when every safety analysis report section of the
        application has left its own `SUBMITTED` state — that is, all sections
        have been opened for review."
        PRD §2.1: "A request whose role is recognized but is not permitted to
        perform the requested operation is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/dca_applicant_cannot_certify
        """
        dca = create_dca(api, docket_number="52-973")
        resp = api.enter_safety_review(dca["id"], APPLICANT)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
