"""Maintenance turnarounds: lifecycle, overlap semantics, and cascades."""
import pytest

from test_helpers import (
    CM,
    OP,
    ApiErrorId,
    add_cargo_slot,
    begin_turnaround_at,
    create_berth_payload,
    create_commercial_train,
    create_confirmed_adp_with_slots,
    create_customer,
    create_draft_adp,
    create_pipeline_payload,
    create_spa_payload,
    create_turnaround_payload,
    get_success_data,
    make_operator_headers,
    propose_and_approve_turnaround,
    validate_error,
    validate_success,
)


class TestTurnaroundValidation:
    def test_turnaround_same_user_approve_rejected(self, api):
        """PRD §3.8: "Approval is a segregated duty: a `TerminalOperator` approves
        a `PROPOSED` turnaround, but the approver's `X-User-ID` must differ from
        `proposed_by_user_id`, with violations rejected as
        `ERR_TURNAROUND_SOD_VIOLATION`".

        Design: Corner/validations/turnaround_same_user_approve_rejected
        """
        train = get_success_data(
            api.create_train(
                {
                    "name": "Train 1",
                    "design_capacity_mtpa": 5.0,
                    "daily_capacity_mmbtu": 700000,
                    "commissioning_cargoes_required": 0,
                },
                OP,
            )
        )
        ta = get_success_data(
            api.propose_turnaround(
                train["id"],
                create_turnaround_payload(),
                make_operator_headers("op-1"),
            )
        )
        resp = api.approve_turnaround(ta["id"], make_operator_headers("op-1"))
        err = validate_error(resp, ApiErrorId.ERR_TURNAROUND_SOD_VIOLATION.value)
        assert err["error_id"] == "ERR_TURNAROUND_SOD_VIOLATION"
        assert resp.status_code == 403

    def test_turnaround_different_user_approve_succeeds(self, api):
        """PRD §3.8: "a `TerminalOperator` approves a `PROPOSED` turnaround, but
        the approver's `X-User-ID` must differ from `proposed_by_user_id`".
        PRD §3.8: "Approval records `approved_by_user_id` and computes the
        `lost_production_mmbtu` as the turnaround length in days — end date minus
        start date plus one, since both endpoints count — multiplied by the
        train's `daily_capacity_mmbtu`."

        Design: Corner/validations/turnaround_same_user_approve_rejected
        """
        train = get_success_data(
            api.create_train(
                {
                    "name": "Train 1",
                    "design_capacity_mtpa": 5.0,
                    "daily_capacity_mmbtu": 700000,
                    "commissioning_cargoes_required": 0,
                },
                OP,
            )
        )
        ta = get_success_data(
            api.propose_turnaround(
                train["id"],
                create_turnaround_payload(),
                make_operator_headers("op-1"),
            )
        )
        validate_error(
            api.approve_turnaround(ta["id"], make_operator_headers("op-1")),
            ApiErrorId.ERR_TURNAROUND_SOD_VIOLATION.value,
        )
        ta = get_success_data(
            api.approve_turnaround(ta["id"], make_operator_headers("op-2"))
        )
        assert ta["status"] == "APPROVED"
        # 5 days (03-01..03-05 inclusive) * 700,000 == 3,500,000
        assert ta["lost_production_mmbtu"] == 3500000
        assert ta["approved_by_user_id"] == "op-2"

    def test_turnaround_approve_twice_rejected(self, api):
        """PRD §3.8: "Approving twice, or completing before beginning, is rejected
        with `ERR_TURNAROUND_INVALID_STATE`."

        Design: Corner/state_machines/turnaround_approve_twice_rejected
        """
        train = create_commercial_train()
        ta = propose_and_approve_turnaround(train["id"])
        resp = api.approve_turnaround(ta["id"], make_operator_headers("op-3"))
        err = validate_error(resp, ApiErrorId.ERR_TURNAROUND_INVALID_STATE.value)
        assert err["error_id"] == "ERR_TURNAROUND_INVALID_STATE"
        ta = get_success_data(api.get_turnaround(ta["id"], OP))
        assert ta["status"] == "APPROVED"
        assert ta["approved_by_user_id"] == "op-2"

    def test_turnaround_closed_interval_touch_overlap(self, api):
        """PRD §3.8: "The new interval must not intersect any non-`CANCELLED`
        turnaround of the same train — touching end and start dates count as
        overlap — and a clash is rejected with `ERR_TURNAROUND_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/turnaround_closed_interval_touch_overlap
        """
        train = create_commercial_train()
        get_success_data(
            api.propose_turnaround(
                train["id"],
                {
                    "planned_start_date": "2027-03-01",
                    "planned_end_date": "2027-03-10",
                },
                make_operator_headers("op-1"),
            )
        )
        # touching: starts on the day the other ends
        resp = api.propose_turnaround(
            train["id"],
            {
                "planned_start_date": "2027-03-10",
                "planned_end_date": "2027-03-20",
            },
            make_operator_headers("op-1"),
        )
        err = validate_error(resp, ApiErrorId.ERR_TURNAROUND_OVERLAP.value)
        assert err["error_id"] == "ERR_TURNAROUND_OVERLAP"

    def test_turnaround_next_day_start_accepted(self, api):
        """PRD §3.8: "The new interval must not intersect any non-`CANCELLED`
        turnaround of the same train — touching end and start dates count as
        overlap — and a clash is rejected with `ERR_TURNAROUND_OVERLAP`."
        PRD §3.8: "the interval is closed — both the first and the last day are
        out of service."

        Design: Difficulty/resource_temporal_overlap/turnaround_closed_interval_touch_overlap
        """
        train = create_commercial_train()
        get_success_data(
            api.propose_turnaround(
                train["id"],
                {
                    "planned_start_date": "2027-03-01",
                    "planned_end_date": "2027-03-10",
                },
                make_operator_headers("op-1"),
            )
        )
        ta2 = get_success_data(
            api.propose_turnaround(
                train["id"],
                {
                    "planned_start_date": "2027-03-11",
                    "planned_end_date": "2027-03-20",
                },
                make_operator_headers("op-1"),
            )
        )
        assert ta2["status"] == "PROPOSED"


class TestTurnaroundCycle:
    def test_train_commercial_turnaround_cycle(self, api):
        """PRD §2.10: "While any maintenance turnaround on any train is in
        progress, every berth is taken `OUT_OF_SERVICE` and every pipeline enters
        `OUTAGE`; when the last in-progress turnaround completes, all berths
        return to `IN_SERVICE` and all pipelines return to `IN_SERVICE`."
        PRD §3.8: "The begin transition sets off the terminal-wide cascade: the
        train moves from `COMMERCIAL_OPERATION` to `TURNAROUND`".

        Design: Difficulty/non_linear_state_machine/train_commercial_turnaround_cycle
        """
        train = create_commercial_train()
        berth = get_success_data(api.create_berth(create_berth_payload(), OP))
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        ta = propose_and_approve_turnaround(train["id"], "2027-03-01", "2027-03-05")
        begin_turnaround_at(ta["id"], "2027-03-01T00:00:00Z")

        train = get_success_data(api.get_train(train["id"], OP))
        berth = get_success_data(api.get_berth(berth["id"], OP))
        pipeline = get_success_data(api.get_pipeline(pipeline["id"], OP))
        assert train["status"] == "TURNAROUND"
        assert berth["status"] == "OUT_OF_SERVICE"
        assert pipeline["status"] == "OUTAGE"

        ta = get_success_data(
            api.complete_turnaround(ta["id"], make_operator_headers("op-3"))
        )
        train = get_success_data(api.get_train(train["id"], OP))
        berth = get_success_data(api.get_berth(berth["id"], OP))
        pipeline = get_success_data(api.get_pipeline(pipeline["id"], OP))
        assert train["status"] == "COMMERCIAL_OPERATION", (
            f"complete must close the cycle, got {train['status']}"
        )
        assert berth["status"] == "IN_SERVICE"
        assert pipeline["status"] == "IN_SERVICE"
        assert ta["lost_production_mmbtu"] == 3500000

    def test_train_turnaround_cycle_restores_service_only_when_last_completes(self, api):
        """PRD §3.8: "Completing the `IN_PROGRESS` turnaround returns the train
        from `TURNAROUND` to `COMMERCIAL_OPERATION`, moves the turnaround to
        `COMPLETED`, and — when no turnaround anywhere remains `IN_PROGRESS` —
        returns every berth to `IN_SERVICE` and every pipeline to `IN_SERVICE`."

        Design: Difficulty/non_linear_state_machine/train_commercial_turnaround_cycle
        """
        train = create_commercial_train()
        berth = get_success_data(api.create_berth(create_berth_payload(), OP))
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        ta = propose_and_approve_turnaround(train["id"], "2027-03-01", "2027-03-05")
        begin_turnaround_at(ta["id"], "2027-03-01T00:00:00Z")
        ta = get_success_data(
            api.complete_turnaround(ta["id"], make_operator_headers("op-3"))
        )
        assert ta["status"] == "COMPLETED"
        train = get_success_data(api.get_train(train["id"], OP))
        assert train["status"] == "COMMERCIAL_OPERATION"
        berth = get_success_data(api.get_berth(berth["id"], OP))
        pipeline = get_success_data(api.get_pipeline(pipeline["id"], OP))
        assert berth["status"] == "IN_SERVICE"
        assert pipeline["status"] == "IN_SERVICE"


class TestTurnaroundCascade:
    def test_turnaround_begin_depth3_cascade(self, api):
        """PRD §3.8: "every cargo slot terminal-wide whose half-open window
        intersects the turnaround's closed interval — intersection meaning the
        window starts before the day after the turnaround's end date and ends
        after the turnaround's start date — and whose `lift_status` is `SCHEDULED`
        or `VESSEL_NOMINATED` is shifted forward: both `window_start` and
        `window_end` advance by the turnaround length in days, the slot passes
        through `RESCHEDULED` and immediately back to `SCHEDULED` once the shift
        completes". PRD §3.8: "The turnaround records how many slots were shifted
        in `shifted_cargo_slot_count`." PRD §2.10: "Cargo slots whose windows
        collide with a turnaround are shifted automatically by the system, and
        each such shift recomputes the owning delivery program's quantities."

        Design: Difficulty/transitive_cascade/turnaround_begin_depth3_cascade
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-03-05T00:00:00Z",
                    "window_end": "2027-03-12T00:00:00Z",
                    "quantity_mmbtu": 3600000,
                },
                {
                    "window_start": "2027-06-01T00:00:00Z",
                    "window_end": "2027-06-08T00:00:00Z",
                    "quantity_mmbtu": 3600000,
                },
            ]
        )
        adp = get_success_data(api.lock_adp(ctx["adp"]["id"], CM))
        adp_v_pre = adp["version"]
        train = create_commercial_train()
        ta = propose_and_approve_turnaround(train["id"], "2027-03-01", "2027-03-10")
        begin_turnaround_at(ta["id"], "2027-03-01T00:00:00Z")

        train = get_success_data(api.get_train(train["id"], OP))
        assert train["status"] == "TURNAROUND"

        slot = get_success_data(api.get_cargo_slot(ctx["slots"][0]["id"], CM))
        # shifted forward by 10 days (closed interval 03-01..03-10)
        assert slot["window_start"] == "2027-03-15T00:00:00Z", (
            f"window_start must advance by the turnaround length, got "
            f"{slot['window_start']}"
        )
        assert slot["window_end"] == "2027-03-22T00:00:00Z"
        assert slot["lift_status"] == "SCHEDULED", (
            "the system restores RESCHEDULED slots to SCHEDULED after the shift"
        )
        slot2 = get_success_data(api.get_cargo_slot(ctx["slots"][1]["id"], CM))
        assert slot2["window_start"] == "2027-06-01T00:00:00Z", (
            "non-overlapping slot must be untouched"
        )

        adp_after = get_success_data(api.get_adp(adp["id"], CM))
        assert adp_after["version"] == adp_v_pre + 1, (
            f"slot shift must recompute the owning ADP (version {adp_v_pre} -> "
            f"{adp_v_pre + 1}), got {adp_after['version']}"
        )
        assert adp_after["scheduled_quantity_mmbtu"] == 7200000, (
            "the shift conserves quantity"
        )
        ta = get_success_data(api.get_turnaround(ta["id"], OP))
        assert ta["shifted_cargo_slot_count"] == 1
        # 10 days * 700,000 == 7,000,000
        assert ta["lost_production_mmbtu"] == 7000000

    def test_turnaround_begin_takes_berths_and_pipelines_out(self, api):
        """PRD §3.8: "The begin transition sets off the terminal-wide cascade:
        the train moves from `COMMERCIAL_OPERATION` to `TURNAROUND`; every berth
        in the terminal goes `OUT_OF_SERVICE` and every pipeline goes `OUTAGE`".
        PRD §2.10: "Cargo slots whose windows collide with a turnaround are
        shifted automatically by the system, and each such shift recomputes the
        owning delivery program's quantities."

        Design: Difficulty/transitive_cascade/turnaround_begin_depth3_cascade
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-03-05T00:00:00Z",
                    "window_end": "2027-03-12T00:00:00Z",
                    "quantity_mmbtu": 3600000,
                },
                {
                    "window_start": "2027-06-01T00:00:00Z",
                    "window_end": "2027-06-08T00:00:00Z",
                    "quantity_mmbtu": 3600000,
                },
            ]
        )
        get_success_data(api.lock_adp(ctx["adp"]["id"], CM))
        berth = get_success_data(api.create_berth(create_berth_payload(), OP))
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        train = create_commercial_train()
        ta = propose_and_approve_turnaround(train["id"], "2027-03-01", "2027-03-10")
        begin_turnaround_at(ta["id"], "2027-03-01T00:00:00Z")

        berth = get_success_data(api.get_berth(berth["id"], OP))
        pipeline = get_success_data(api.get_pipeline(pipeline["id"], OP))
        assert berth["status"] == "OUT_OF_SERVICE"
        assert pipeline["status"] == "OUTAGE"
        adp_after = get_success_data(api.get_adp(ctx["adp"]["id"], CM))
        assert adp_after["scheduled_quantity_mmbtu"] == 7200000
        ta = get_success_data(api.get_turnaround(ta["id"], OP))
        assert ta["shifted_cargo_slot_count"] == 1
