"""Quality incidents: escalate/resolve fork, line holds, and the hold-resume
cycle (PRD §3.5, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_run_env, setup_in_progress_run, create_run, start_run,
    create_incident, get_run, get_agreement_version,
    scheduler, manager, engineer, api_client,
)


def _line_status(api, plant_id):
    rows, _ = validate_paginated(api.list_lines(plant_id, manager()))
    assert len(rows) == 1
    return rows[0]["operational_status"]


class TestDirectResolveBranch:
    def test_incident_direct_resolve_leaves_run_and_line_untouched(self, api):
        """PRD §3.9: "Resolving an `OPEN` incident directly — without
        escalation — moves it straight to `RESOLVED` and leaves the run and the
        line untouched."

        Design: Corner/state_machines/incident_direct_resolve_leaves_run_and_line_untouched
        """
        env = setup_in_progress_run()
        incident = create_incident(env["run"]["id"], severity="MINOR",
                                   defect_class="FILLING_LINE_PERFORMANCE",
                                   note="filler valve trips")
        resolved = validate_success(
            api.resolve_incident(incident["id"], engineer()))
        assert resolved["status"] == "RESOLVED"
        assert get_run(env["run"]["id"])["status"] == "IN_PROGRESS"
        assert _line_status(api, env["plant"]["id"]) == "RUNNING"


class TestStartBlockedOnHold:
    def test_start_blocked_on_quality_hold_line(self, api):
        """PRD §3.5: "It is permitted only while the line's
        `operational_status` is `RUNNING` — a line under `QUALITY_HOLD` rejects
        the start with `ERR_LINE_QUALITY_HOLD`".

        Design: Corner/validations/start_blocked_on_quality_hold_line
        """
        env = setup_run_env()
        agr, line, fmt = (env["agreement"]["id"], env["line"]["id"],
                          env["format"]["id"])
        r0 = create_run(agr, line, fmt, scheduled_qty=100000,
                        window_start="2026-09-10T08:00:00Z",
                        window_end="2026-09-10T16:00:00Z")
        start_run(r0["id"])
        r1 = create_run(agr, line, fmt, scheduled_qty=50000,
                        window_start="2026-09-11T08:00:00Z",
                        window_end="2026-09-11T16:00:00Z")
        incident = create_incident(r0["id"], note="seam rating below spec")
        validate_success(api.escalate_incident(incident["id"], engineer()))
        resp = api.start_run(r1["id"], scheduler())
        validate_error(resp, ApiErrorId.ERR_LINE_QUALITY_HOLD, 409)
        assert get_run(r0["id"])["status"] == "HELD"
        assert get_run(r1["id"])["status"] == "SCHEDULED"
        assert _line_status(api, env["plant"]["id"]) == "QUALITY_HOLD"


class TestEscalateCascade:
    def test_escalate_holds_run_then_line(self, api):
        """PRD §3.9: "Escalating an `OPEN` incident moves it to `ESCALATED` and,
        when the linked run stands `IN_PROGRESS`, drives that run to `HELD` ...
        while the run's line enters `QUALITY_HOLD`".

        Design: Difficulty/transitive_cascade/incident_escalate_holds_run_then_line_then_gates_new_work
        """
        env = setup_in_progress_run(run_overrides={"scheduled_qty": 100000})
        incident = create_incident(env["run"]["id"], severity="CRITICAL",
                                   note="leaker at customer filler")
        escalated = validate_success(
            api.escalate_incident(incident["id"], engineer()))
        assert escalated["status"] == "ESCALATED"
        assert get_run(env["run"]["id"])["status"] == "HELD"
        assert _line_status(api, env["plant"]["id"]) == "QUALITY_HOLD"

    def test_escalated_line_gates_new_work(self, api):
        """PRD §3.9: "the run's line enters `QUALITY_HOLD`, which blocks new
        run creation and run starts on that line with `ERR_LINE_QUALITY_HOLD`
        until the hold clears."

        Design: Difficulty/transitive_cascade/incident_escalate_holds_run_then_line_then_gates_new_work
        """
        env = setup_in_progress_run(run_overrides={"scheduled_qty": 100000})
        incident = create_incident(env["run"]["id"], severity="CRITICAL")
        api.escalate_incident(incident["id"], engineer())
        resp = api.create_run(
            env["agreement"]["id"],
            {"line_id": env["line"]["id"], "format_id": env["format"]["id"],
             "scheduled_qty": 50000, "graphics_code": "G1",
             "window_start": "2026-09-12T08:00:00Z",
             "window_end": "2026-09-12T16:00:00Z",
             "expected_agreement_version": get_agreement_version(
                 env["agreement"]["id"])},
            scheduler())
        validate_error(resp, ApiErrorId.ERR_LINE_QUALITY_HOLD, 409)


class TestHoldResumeCycle:
    def test_hold_resume_cycle_closes_once(self, api):
        """PRD §3.9: "Resolving an `ESCALATED` incident releases the hold it
        caused: the held run returns from `HELD` to `IN_PROGRESS` ... and the
        line's `operational_status` returns to `RUNNING` only when no
        `ESCALATED` incident remains on any run of the line."

        Design: Difficulty/non_linear_state_machine/production_run_hold_resume_cycle_driven_by_incidents
        """
        env = setup_in_progress_run(run_overrides={"scheduled_qty": 250000})
        run_id = env["run"]["id"]
        inc1 = create_incident(run_id, note="seam wrinkle at filler")
        api.escalate_incident(inc1["id"], engineer())
        assert get_run(run_id)["status"] == "HELD"
        assert _line_status(api, env["plant"]["id"]) == "QUALITY_HOLD"
        resolved = validate_success(api.resolve_incident(inc1["id"], engineer()))
        assert resolved["status"] == "RESOLVED"
        assert get_run(run_id)["status"] == "IN_PROGRESS"
        assert _line_status(api, env["plant"]["id"]) == "RUNNING"

    def test_hold_resume_cycle_repeats_with_second_incident(self, api):
        """PRD §3.9: "`RESOLVED` is terminal" for an incident, so a second hold
        requires a second incident; escalating it drives the same run back to
        `HELD` (PRD §3.9 escalate side effect).

        Design: Difficulty/non_linear_state_machine/production_run_hold_resume_cycle_driven_by_incidents
        """
        env = setup_in_progress_run(run_overrides={"scheduled_qty": 250000})
        run_id = env["run"]["id"]
        inc1 = create_incident(run_id, severity="MAJOR", note="seam wrinkle")
        api.escalate_incident(inc1["id"], engineer())
        api.resolve_incident(inc1["id"], engineer())
        inc2 = create_incident(run_id, severity="CRITICAL",
                               defect_class="COATING", note="inside spray void")
        escalated = validate_success(api.escalate_incident(inc2["id"],
                                                           engineer()))
        assert escalated["status"] == "ESCALATED"
        assert get_run(run_id)["status"] == "HELD"
        first = validate_success(api.get_incident(inc1["id"], engineer()))
        assert first["status"] == "RESOLVED"
