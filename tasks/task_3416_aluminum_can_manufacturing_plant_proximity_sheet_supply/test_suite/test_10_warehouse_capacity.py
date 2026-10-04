"""Warehouse projection capacity gate and plant posture thresholds
(PRD §2.10)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, publish_index, setup_run_env, create_run, start_run,
    complete_run, get_plant, get_agreement_version, scheduler, api_client,
)


def _capacity_env(api, capacity):
    """Plant of `capacity`, ACTIVE agreement, line, QUALIFIED format."""
    return setup_run_env(capacity=capacity)


def _body(env, qty, start, end, graphics="G1"):
    return {"line_id": env["line"]["id"], "format_id": env["format"]["id"],
            "scheduled_qty": qty, "graphics_code": graphics,
            "window_start": start, "window_end": end,
            "expected_agreement_version": get_agreement_version(
                env["agreement"]["id"])}


class TestCapacityBoundary:
    def _boundary_env(self, api):
        """projected == 150000 on a 250000-capacity plant.

        R1 (50000) completed -> on_hand 50000; R2 (100000) SCHEDULED.
        """
        set_clock()
        publish_index("2026-08", 128.0)
        env = _capacity_env(api, 250000)
        r1 = create_run(env["agreement"]["id"], env["line"]["id"],
                        env["format"]["id"], scheduled_qty=50000,
                        window_start="2026-09-10T08:00:00Z",
                        window_end="2026-09-10T16:00:00Z")
        start_run(r1["id"])
        complete_run(r1["id"], 50000, 0)
        create_run(env["agreement"]["id"], env["line"]["id"],
                   env["format"]["id"], scheduled_qty=100000,
                   window_start="2026-09-12T08:00:00Z",
                   window_end="2026-09-12T16:00:00Z")
        return env

    def test_warehouse_projection_one_over_capacity_rejected(self, api):
        """PRD §2.10: "a new run with a given `scheduled_qty` is allowed only
        when the current `projected_warehouse_units` plus that `scheduled_qty`
        does not exceed `warehouse_capacity_units`. Equality with the capacity
        is allowed; any strict excess is rejected with
        `ERR_WAREHOUSE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/warehouse_projection_equals_capacity_allowed_one_over_rejected
        """
        env = self._boundary_env(api)
        # 150000 + 100001 == 250001 > 250000: strict excess.
        resp = api.create_run(env["agreement"]["id"],
                              _body(env, 100001, "2026-09-13T08:00:00Z",
                                    "2026-09-13T16:00:00Z"), scheduler())
        validate_error(resp, ApiErrorId.ERR_WAREHOUSE_CAPACITY_EXCEEDED, 409)

    def test_warehouse_projection_exact_fit_allowed_then_lockdown(self, api):
        """PRD §2.10: "Equality with the capacity is allowed" and "`LOCKDOWN`
        when free units are zero or negative ... `LOCKDOWN` blocks the creation
        of new production runs with `ERR_PLANT_LOCKDOWN`."

        Design: Difficulty/boundary_precision_check/warehouse_projection_equals_capacity_allowed_one_over_rejected
        """
        env = self._boundary_env(api)
        # 150000 + 100000 == 250000 == capacity: exact fit allowed.
        exact = validate_success(api.create_run(
            env["agreement"]["id"],
            _body(env, 100000, "2026-09-13T08:00:00Z", "2026-09-13T16:00:00Z"),
            scheduler()), 201)
        assert exact["status"] == "SCHEDULED"
        plant = get_plant(env["plant"]["id"])
        assert plant["projected_warehouse_units"] == 250000
        assert plant["posture"] == "LOCKDOWN"
        # Free units are 0: the posture gate now rejects any further create.
        resp = api.create_run(env["agreement"]["id"],
                              _body(env, 5000, "2026-09-14T08:00:00Z",
                                    "2026-09-14T16:00:00Z"), scheduler())
        validate_error(resp, ApiErrorId.ERR_PLANT_LOCKDOWN, 409)


class TestCongestedThreshold:
    def test_posture_congested_at_exact_threshold_boundary(self, api):
        """PRD §2.10: "`CONGESTED` when free units are positive but do not
        exceed the integer floor of one fifth (20 percent) of
        `warehouse_capacity_units`; and `OPEN` otherwise."

        Design: Corner/calculations/posture_congested_at_exact_threshold_boundary
        """
        set_clock()
        publish_index("2026-08", 128.0)
        env = _capacity_env(api, 250000)
        r1 = create_run(env["agreement"]["id"], env["line"]["id"],
                        env["format"]["id"], scheduled_qty=100000,
                        window_start="2026-09-10T08:00:00Z",
                        window_end="2026-09-10T16:00:00Z")
        start_run(r1["id"])
        complete_run(r1["id"], 100000, 0)
        # on_hand 100000, projected 100000 -> free 150000 > 50000: OPEN.
        assert get_plant(env["plant"]["id"])["posture"] == "OPEN"
        ok = validate_success(api.create_run(
            env["agreement"]["id"],
            _body(env, 100000, "2026-09-12T08:00:00Z", "2026-09-12T16:00:00Z"),
            scheduler()), 201)
        assert ok["status"] == "SCHEDULED"
        plant = get_plant(env["plant"]["id"])
        # projected 200000 -> free 50000 == floor(250000 * 0.20): CONGESTED.
        assert plant["projected_warehouse_units"] == 200000
        assert plant["posture"] == "CONGESTED"
