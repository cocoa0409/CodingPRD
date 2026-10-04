"""Investigation phase machine and the public docket: declared-order hops,
phase gates, docket release side effects and pipeline-ordered gates, the
ANALYSIS -> FACTUAL reopen cycle, and the completeness percentage (PRD §3.5).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_phase,
    advance_phase_payload,
    complete_group,
    create_designation,
    create_factual_report,
    create_group,
    create_org,
    create_recorder,
    create_seat,
    find_report,
    find_seat,
    get_designation,
    get_group,
    get_investigation,
    get_recorder,
    make_iic_headers,
    release_docket,
    reopen_factual,
    schedule_readout_session,
    set_clock,
    setup_analysis,
    setup_docket_released,
    setup_factual,
    setup_group_completed,
    setup_launched_investigation,
    setup_recorder_with_pending_session,
    validate_error,
    verify_report,
)

DOCKET_OFFICER = TEST_USERS["docket_officer_headers"]


class TestPhaseHopsAndGates:
    def test_advance_on_scene_without_any_group_fails_gate(self, api):
        """PRD §3.5: "Moving to `ON_SCENE` requires at least one of the
        investigation's groups to be `ACTIVE`." PRD §3.5: "An unmet gate is
        rejected with `ERR_PHASE_GATE_UNSATISFIED`, and every successful hop
        increments the investigation's `version`."

        Design: Corner/state_machines/advance_on_scene_without_any_group_fails_gate
        """
        ctx = setup_launched_investigation()
        inv_id = ctx["investigation"]["id"]

        resp = api.advance_phase(
            inv_id, advance_phase_payload("ON_SCENE"), make_iic_headers(ctx["iic_user_id"])
        )
        validate_error(resp, ApiErrorId.ERR_PHASE_GATE_UNSATISFIED)

        create_group(inv_id, specialty="STRUCTURES", chairman_user_id="gc-2")
        investigation = advance_phase(inv_id, "ON_SCENE", iic_user_id=ctx["iic_user_id"])
        assert investigation["phase"] == "ON_SCENE"

    def test_advance_phase_skipping_on_scene_returns_phase_invalid(self, api):
        """PRD §3.5: "Phase progression follows one declared order —
        `GO_TEAM_ASSEMBLED` → `ON_SCENE` → `FACTUAL` → `ANALYSIS` →
        `BOARD_REVIEW` — with each hop an `IIC` action naming its target as
        `to_phase`; any hop outside the declared order is rejected with
        `ERR_INVESTIGATION_PHASE_INVALID`."

        Design: Corner/state_machines/advance_phase_skipping_on_scene_returns_phase_invalid
        """
        ctx = setup_launched_investigation()
        inv_id = ctx["investigation"]["id"]

        resp = api.advance_phase(
            inv_id, advance_phase_payload("FACTUAL"), make_iic_headers(ctx["iic_user_id"])
        )
        error_data = validate_error(resp, ApiErrorId.ERR_INVESTIGATION_PHASE_INVALID)
        # The bad hop is detected before any gate evaluation.
        assert error_data["error_id"] != ApiErrorId.ERR_PHASE_GATE_UNSATISFIED
        assert get_investigation(inv_id)["phase"] == "GO_TEAM_ASSEMBLED"

    def test_advance_to_analysis_without_open_docket_returns_docket_not_open(self, api):
        """PRD §3.5: "Moving to `ANALYSIS` requires the docket to be `OPEN`
        (`ERR_DOCKET_NOT_OPEN` when it is not) with every group `COMPLETE` or
        `DISBANDED`."

        Design: Corner/errors/advance_to_analysis_without_open_docket_returns_docket_not_open
        """
        ctx = setup_group_completed()
        inv_id = ctx["investigation"]["id"]
        assert ctx["investigation"]["docket_status"] == "SEALED"

        resp = api.advance_phase(
            inv_id, advance_phase_payload("ANALYSIS"), make_iic_headers(ctx["iic_user_id"])
        )
        validate_error(resp, ApiErrorId.ERR_DOCKET_NOT_OPEN)

        investigation = get_investigation(inv_id)
        assert investigation["phase"] == "FACTUAL"
        assert investigation["docket_status"] == "SEALED"


class TestDocketRelease:
    def test_release_docket_flips_reports_and_releases_recorders(self, api):
        """PRD §3.5: "A successful release moves every `VERIFIED` report across
        the investigation's groups to `DOCKETED`, moves every recorder whose
        readout is complete to `RELEASED`, opens the docket (`SEALED` →
        `OPEN`), and recomputes the completeness figure — which by construction
        reads 100 at that point." PRD §2.4: "A recorder package becomes
        `READOUT_COMPLETE` once at least one session exists on it and every
        session's `window_end_utc` has been reached."

        Design: Corner/state_machines/release_docket_flips_reports_and_releases_recorders
        """
        ctx = setup_group_completed()
        inv_id = ctx["investigation"]["id"]

        cvr = create_recorder(inv_id, recorder_type="CVR", condition="INTACT")
        schedule_readout_session(
            cvr["id"],
            bench_id="bench-1",
            window_start_utc="2026-09-02T10:00:00Z",
            window_end_utc="2026-09-02T12:00:00Z",
        )
        fdr = create_recorder(inv_id, recorder_type="FDR", condition="SEVERELY_DAMAGED")
        # Move the logical clock to the session end so the CVR's readout is
        # complete; the FDR never had a session, so it has nothing to release.
        set_clock("2026-09-02T12:00:00Z")

        investigation = release_docket(inv_id)
        assert investigation["docket_status"] == "OPEN"
        assert investigation["docket_completeness_pct"] == 100

        group = get_group(ctx["group"]["id"])
        assert find_report(group, report_id=ctx["report_id"])["status"] == "DOCKETED"
        assert get_recorder(cvr["id"])["status"] == "RELEASED"
        assert get_recorder(fdr["id"])["status"] == "SECURED"

    def test_second_release_docket_returns_docket_state_invalid(self, api):
        """PRD §3.5: "A `DocketOfficer` releases it only while the
        investigation is in the `FACTUAL` phase (`ERR_INVESTIGATION_PHASE_INVALID`)
        and the docket is still `SEALED` (`ERR_DOCKET_STATE_INVALID`)".

        Design: Corner/errors/second_release_docket_returns_docket_state_invalid
        """
        ctx = setup_docket_released()
        inv_id = ctx["investigation"]["id"]
        assert ctx["investigation"]["docket_status"] == "OPEN"

        resp = api.release_docket(inv_id, DOCKET_OFFICER)
        validate_error(resp, ApiErrorId.ERR_DOCKET_STATE_INVALID)

        investigation = get_investigation(inv_id)
        assert investigation["docket_status"] == "OPEN"
        group = get_group(ctx["group"]["id"])
        assert find_report(group, report_id=ctx["report_id"])["status"] == "DOCKETED"

    def test_docket_release_recorder_safety_shadows_group_completeness(self, api):
        """PRD §3.5: "two further gates then apply in pipeline order. The
        recorder-safety gate rejects the release with
        `ERR_RECORDER_READOUT_INCOMPLETE` when any readout session embedded in
        any of the investigation's recorders has a `window_end_utc` lying
        strictly after the current logical clock. The completeness gate rejects
        with `ERR_DOCKET_INCOMPLETE` unless every group is `COMPLETE` and holds
        at least one `VERIFIED` or `DOCKETED` report." PRD §2.8: "Every request
        is evaluated against a fixed pipeline of checks; when several checks
        would fail, the earliest stage's error is the one returned."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_docket_safety_beats_group_completeness
        """
        ctx = setup_factual()
        inv_id = ctx["investigation"]["id"]
        # Group never completed (its report is only SUBMITTED) AND a recorder
        # readout window is still open: both gates fail, and pipeline order
        # surfaces the recorder-safety error.
        setup_recorder_with_pending_session(inv_id)

        resp = api.release_docket(inv_id, DOCKET_OFFICER)
        error_data = validate_error(resp, ApiErrorId.ERR_RECORDER_READOUT_INCOMPLETE)
        assert error_data["error_id"] != ApiErrorId.ERR_DOCKET_INCOMPLETE
        assert get_investigation(inv_id)["docket_status"] == "SEALED"

    def test_docket_release_incomplete_groups_alone_returns_docket_incomplete(self, api):
        """PRD §3.5: "The completeness gate rejects with `ERR_DOCKET_INCOMPLETE`
        unless every group is `COMPLETE` and holds at least one `VERIFIED` or
        `DOCKETED` report."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_docket_safety_beats_group_completeness
        """
        ctx = setup_factual()
        inv_id = ctx["investigation"]["id"]
        # No recorders at all, so the safety gate passes in isolation; the
        # seated-but-never-completed group trips the completeness gate alone.
        resp = api.release_docket(inv_id, DOCKET_OFFICER)
        validate_error(resp, ApiErrorId.ERR_DOCKET_INCOMPLETE)
        assert get_investigation(inv_id)["docket_status"] == "SEALED"


class TestFactualReopenCycle:
    def test_factual_analysis_revert_cycle_reverts_groups_and_recompletes(self, api):
        """PRD §3.5: "the `IIC` can reopen the factual phase, moving the
        investigation from `ANALYSIS` back to `FACTUAL`. Every `COMPLETE` group
        reverts to `ACTIVE`, the completeness percentage is recomputed, and an
        `OPEN` docket stays `OPEN` — reopening never reseals the public
        record." PRD §3.5: "Because a `DOCKETED` report also satisfies the
        evidence condition, a group can re-complete after a factual reopening."

        Design: Difficulty/non_linear_state_machine/non_linear_investigation_factual_analysis_revert
        """
        ctx = setup_analysis()
        inv_id = ctx["investigation"]["id"]
        group_id = ctx["group"]["id"]

        reopened = reopen_factual(inv_id, iic_user_id=ctx["iic_user_id"])
        assert reopened["phase"] == "FACTUAL"
        assert reopened["docket_status"] == "OPEN", "the docket is not re-sealed"

        group = get_group(group_id)
        assert group["status"] == "ACTIVE", "COMPLETE group reverted"
        assert find_report(group, report_id=ctx["report_id"])["status"] == "DOCKETED"
        # The reverted (ACTIVE) group is unsatisfied, so pct drops from 100.
        assert get_investigation(inv_id)["docket_completeness_pct"] == 0

        # The DOCKETED report still satisfies the evidence condition.
        group = complete_group(group_id, chairman_user_id=ctx["chairman_user_id"])
        assert group["status"] == "COMPLETE"
        investigation = advance_phase(inv_id, "ANALYSIS", iic_user_id=ctx["iic_user_id"])
        assert investigation["phase"] == "ANALYSIS", "the cycle closes forward"
        assert (
            find_report(get_group(group_id), report_id=ctx["report_id"])["status"]
            == "DOCKETED"
        )

    def test_reopen_factual_from_factual_phase_is_rejected(self, api):
        """PRD §3.5: "the `IIC` can reopen the factual phase, moving the
        investigation from `ANALYSIS` back to `FACTUAL`" — the reopen is
        declared only from `ANALYSIS`; PRD §3.5: "any hop outside the declared
        order is rejected with `ERR_INVESTIGATION_PHASE_INVALID`." PRD §3.4:
        seating survives a reopen — only `COMPLETE` groups revert.

        Design: Difficulty/non_linear_state_machine/non_linear_investigation_factual_analysis_revert
        """
        ctx = setup_analysis()
        inv_id = ctx["investigation"]["id"]
        group_id = ctx["group"]["id"]

        reopen_factual(inv_id, iic_user_id=ctx["iic_user_id"])
        # Seats are untouched by the reopen: the party stays SEATED and the
        # reverted group keeps its seated_count.
        designation = get_designation(ctx["designation"]["id"])
        assert find_seat(designation, seat_id=ctx["seat_id"])["status"] == "SEATED"
        assert get_group(group_id)["seated_count"] == 1

        resp = api.reopen_factual(inv_id, make_iic_headers(ctx["iic_user_id"]))
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_PHASE_INVALID)
        assert get_investigation(inv_id)["phase"] == "FACTUAL"


class TestDocketCompletenessComputation:
    def test_docket_completeness_pct_thirds_rounding(self, api):
        """PRD §3.5: "The second pass counts the investigation's groups in
        `ACTIVE` or `COMPLETE` status — `DISBANDED` groups are excluded
        entirely — and records zero when none exist, otherwise the satisfied
        share of that count, rounded half-up to a whole percent." PRD §3.5:
        "counts the group as satisfied when its stored status is `COMPLETE` and
        at least one of its embedded reports is `VERIFIED` or `DOCKETED`."

        Design: Corner/calculations/docket_completeness_pct_thirds_rounding
        """
        ctx = setup_launched_investigation()
        inv_id = ctx["investigation"]["id"]
        iic = ctx["iic_user_id"]

        group1 = create_group(inv_id, specialty="OPERATIONS", chairman_user_id="gc-1")
        group2 = create_group(inv_id, specialty="STRUCTURES", chairman_user_id="gc-2")
        group3 = create_group(inv_id, specialty="HUMAN_PERFORMANCE", chairman_user_id="gc-3")
        advance_phase(inv_id, "ON_SCENE", iic_user_id=iic)
        org = create_org(legal_name="Blue Ridge Transit Authority", org_type="OPERATOR")
        designation = create_designation(inv_id, org["id"])
        # One designation may seat the same party on three different groups.
        for group in (group1, group2, group3):
            designation = create_seat(designation["id"], group["id"], iic_user_id=iic)
        advance_phase(inv_id, "FACTUAL", iic_user_id=iic)

        # Only group 1 gathers a VERIFIED report and completes.
        group1 = create_factual_report(group1["id"], chairman_user_id="gc-1")
        report_id = find_report(group1)["report_id"]
        verify_report(group1["id"], report_id, iic_user_id=iic)
        complete_group(group1["id"], chairman_user_id="gc-1")

        investigation = get_investigation(inv_id)
        # round_half_up(100 * 1 / 3) == 33 — not 34 and not a fractional value.
        assert investigation["docket_completeness_pct"] == 33
        assert get_group(group2["id"])["status"] == "ACTIVE"
        assert get_group(group3["id"])["status"] == "ACTIVE"
        assert investigation["docket_status"] == "SEALED"
