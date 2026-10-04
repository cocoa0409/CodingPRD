"""Corner queue — state_machines (ProjectClearance): terminal-state lockdown,
the EIS 45-day window boundary, and non-REJECTED uniqueness with replacement
(PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_clearance,
    create_clearance_payload,
    determine_project_eligible,
    set_clock,
    setup_stip_pipeline,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


def _eligible_project(api, cost_cents=1_000):
    """Approved STIP (default apportionment covers the estimate) with one
    project determined ELIGIBLE."""
    pipeline = setup_stip_pipeline(
        program_code="NHPP",
        eligible_activity_codes=["ROAD_RESURFACING"],
        state_code="AZ",
        project_specs=[{"total_estimated_cost_cents": cost_cents}],
    )
    project = pipeline["projects"][0]
    determine_project_eligible(project["id"])
    return project


class TestClearanceStateMachine:
    def test_clearance_decide_twice_returns_invalid_state(self, api):
        """PRD §3.4: "A `decision` of `REJECT` moves the clearance to the
        terminal `REJECTED` status".
        PRD §2.7: "6. State gate: the target resource must be in a valid
        from-state for the requested action, else `ERR_INVALID_STATE` (409)."
        PRD §3.4: "An `FHWAReviewer` decides a `SUBMITTED` clearance by
        supplying a `decision`."

        The decide action is defined only on SUBMITTED; a second decide on the
        terminal REJECTED row is a wrong-state call.

        Design: Corner/state_machines/clearance_decide_twice_returns_invalid_state
        """
        project = _eligible_project(api)
        created = api.create_clearance(
            create_clearance_payload(project["id"], "ENVIRONMENTAL", "CE"),
            H["state_dot_engineer"],
        )
        clearance = validate_success(created, expected_status=201)
        rejected = api.decide_clearance(
            clearance["id"], {"decision": "REJECT"}, H["fhwa_reviewer"]
        )
        assert validate_success(rejected)["status"] == "REJECTED"

        resp = api.decide_clearance(
            clearance["id"], {"decision": "CLEARED"}, H["fhwa_reviewer"]
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"
        rows = api.list_project_clearances(project["id"], H["fhwa_reviewer"])
        data = rows.json()["data"]
        assert len(data) == 1 and data[0]["status"] == "REJECTED"

    def test_eis_clearance_requires_forty_five_day_window(self, api):
        """PRD §3.4: "For an environmental clearance whose `nepa_class` is
        `EIS`, the logical clock must have reached at least 45 days after the
        clearance's `created_at` — exactly 45 days passes — else
        `ERR_COMMENT_PERIOD_OPEN` (409); `CE` and `EA` classes carry no waiting
        period."

        The EIS clearance is created at 2026-10-15: the CLEARED decide fails at
        +44 days (2026-11-28) and succeeds at exactly +45 (2026-11-29).

        Design: Corner/state_machines/eis_clearance_requires_forty_five_day_window
        """
        project = _eligible_project(api)
        set_clock("2026-10-15T00:00:00Z")
        created = api.create_clearance(
            create_clearance_payload(project["id"], "ENVIRONMENTAL", "EIS"),
            H["state_dot_engineer"],
        )
        clearance = validate_success(created, expected_status=201)
        assert_clearance(clearance)

        set_clock("2026-11-28T00:00:00Z")  # +44 days
        early = api.decide_clearance(
            clearance["id"], {"decision": "CLEARED"}, H["fhwa_reviewer"]
        )
        error = validate_error(early, ApiErrorId.ERR_COMMENT_PERIOD_OPEN)
        assert early.status_code == 409, (
            f"+44 days must still be inside the window, got {early.status_code} ({error})"
        )

        set_clock("2026-11-29T00:00:00Z")  # exactly +45 days
        decided = api.decide_clearance(
            clearance["id"], {"decision": "CLEARED"}, H["fhwa_reviewer"]
        )
        cleared = validate_success(decided)
        assert_clearance(cleared)
        assert cleared["status"] == "CLEARED", (
            "exactly 45 days elapsed must pass the EIS window"
        )

    def test_clearance_second_active_same_kind_rejected_then_replacement_allowed(self, api):
        """PRD §3.4: "Only one non-`REJECTED` clearance may exist per (project,
        kind) pair: a second open or cleared clearance of the same kind is
        rejected with `ERR_CLEARANCE_KIND_EXISTS` (409)."
        PRD §3.4: "A `decision` of `REJECT` moves the clearance to the terminal
        `REJECTED` status; because the uniqueness rule counts only
        non-`REJECTED` rows, a replacement clearance of the same kind may then
        be created."

        Design: Corner/state_machines/clearance_second_active_same_kind_rejected_then_replacement_allowed
        """
        project = _eligible_project(api)
        first = api.create_clearance(
            create_clearance_payload(project["id"], "ENVIRONMENTAL", "EA"),
            H["state_dot_engineer"],
        )
        clearance1 = validate_success(first, expected_status=201)

        dup = api.create_clearance(
            create_clearance_payload(project["id"], "ENVIRONMENTAL", "CE"),
            H["state_dot_engineer"],
        )
        error = validate_error(dup, ApiErrorId.ERR_CLEARANCE_KIND_EXISTS)
        assert dup.status_code == 409, (
            "a second non-REJECTED clearance of the same kind must be rejected; "
            f"got {dup.status_code} ({error})"
        )

        rejected = api.decide_clearance(
            clearance1["id"], {"decision": "REJECT"}, H["fhwa_reviewer"]
        )
        assert validate_success(rejected)["status"] == "REJECTED"

        replacement = api.create_clearance(
            create_clearance_payload(project["id"], "ENVIRONMENTAL", "CE"),
            H["state_dot_engineer"],
        )
        clearance2 = validate_success(replacement, expected_status=201)
        assert_clearance(clearance2)
        assert clearance2["id"] != clearance1["id"]
        assert clearance2["status"] == "SUBMITTED"
