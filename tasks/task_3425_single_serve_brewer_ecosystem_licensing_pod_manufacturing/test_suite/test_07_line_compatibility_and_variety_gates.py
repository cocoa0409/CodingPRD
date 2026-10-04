"""Filling-line capability gates, run-variety state gate, and velocity windows."""
from test_helpers import (
    LICENSING,
    OPS,
    PLANNER,
    ApiErrorId,
    create_active_agreement,
    create_brand,
    create_facility_with_line,
    create_variety,
    get_success_data,
    reserve_run,
    set_clock,
    transition_run,
    transition_variety,
    validate_error,
    validate_success,
)


def test_line_rejects_mismatched_roast(api):
    """PRD §3.4: "its `supported_roast` must match the variety's `roast_level`
    unless it is `UNIVERSAL`, its `supports_flavored` must be true when the
    variety is `FLAVORED`, and its `material_capability` must cover the
    variety's `material` (`BOTH` covers either material); a shortfall anywhere
    is `ERR_LINE_INCOMPATIBLE` (HTTP 422)."

    Design: Corner/validations/line_rejects_mismatched_roast
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Roast Brand")
    variety = create_variety(brand["id"], name="Roast Var", roast_level="DARK")
    _, line = create_facility_with_line(supported_roast="LIGHT")

    resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_LINE_INCOMPATIBLE)


def test_line_rejects_flavored_when_unsupported(api):
    """PRD §3.4: "its `supports_flavored` must be true when the variety is
    `FLAVORED`, and its `material_capability` must cover the variety's
    `material` (`BOTH` covers either material); a shortfall anywhere is
    `ERR_LINE_INCOMPATIBLE` (HTTP 422)."

    Design: Corner/validations/line_rejects_flavored_when_unsupported
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Flavor Brand")
    variety = create_variety(brand["id"], name="Hazelnut Medium",
                             flavor_family="FLAVORED")
    _, line = create_facility_with_line(supports_flavored=False)

    resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_LINE_INCOMPATIBLE)


def test_run_create_rejects_phase_out_variety(api):
    """PRD §3.4: "The variety must currently be `ACTIVE`; any other status is
    `ERR_VARIETY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/run_requires_variety_active
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Phaseout Beans")
    variety = create_variety(brand["id"], name="Old Faithful")
    get_success_data(transition_variety(variety["id"], brand["id"], "PHASE_OUT"))

    _, line = create_facility_with_line()
    resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_VARIETY_NOT_ACTIVE)


def test_run_create_rejects_supply_blocked_variety(api):
    """PRD §3.4: "The variety must currently be `ACTIVE`; any other status is
    `ERR_VARIETY_NOT_ACTIVE`."
    PRD §3.2: "Every pod variety of the agreement's brand that is currently
    `ACTIVE` flips to `SUPPLY_BLOCKED`"

    Design: Difficulty/cross_entity_state_dependency/run_requires_variety_active
    """
    brand = create_brand(kind="LICENSED", name="Blocked Beans")
    agreement = create_active_agreement(brand["id"])
    variety = create_variety(brand["id"], name="Blocked Var")
    get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "SUSPENDED"}, LICENSING))

    _, line = create_facility_with_line()
    resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_VARIETY_NOT_ACTIVE)


def test_velocity_counts_only_completed_runs(api, planner_headers):
    """PRD §3.3: "`velocity_units_90d` is the sum of `actual_units` across this
    variety's production runs that have reached `COMPLETED` and whose
    `window_end` falls inside the trailing ninety-day window"
    PRD §3.3: "runs in `RESERVED`, `IN_PROGRESS`, or `CANCELLED` never
    contribute."

    Design: Corner/calculations/velocity_counts_only_completed_runs
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Velocity Brand")
    variety = create_variety(brand["id"], name="Velocity Var")
    facility, line1 = create_facility_with_line(capacity_pods_per_day=100000)
    line2 = get_success_data(api.create_filling_line(
        facility["id"],
        {"line_code": "L2", "supported_roast": "UNIVERSAL",
         "supports_flavored": True, "material_capability": "BOTH",
         "capacity_pods_per_day": 100000, "changeover_hours": 0},
        OPS), 201)

    cancelled = reserve_run(line1["id"], variety["id"],
                            window_start="2026-09-08T00:00:00Z",
                            window_end="2026-09-09T00:00:00Z",
                            planned_units=40000)
    get_success_data(transition_run(cancelled["id"], "CANCELLED"))

    completed = reserve_run(line2["id"], variety["id"],
                            window_start="2026-09-10T00:00:00Z",
                            window_end="2026-09-11T00:00:00Z",
                            planned_units=10000)
    set_clock("2026-09-10T12:00:00Z")
    get_success_data(transition_run(completed["id"], "IN_PROGRESS"))
    get_success_data(transition_run(completed["id"], "COMPLETED",
                                    actual_units=10000))

    set_clock("2026-09-12T00:00:00Z")
    read_back = get_success_data(api.get_pod_variety(variety["id"], planner_headers))
    assert read_back["velocity_units_90d"] == 10000
    # Only 11 days old: the ninety-day age gate keeps slow_mover false.
    assert read_back["slow_mover"] is False


def test_velocity_window_lower_edge_is_inclusive(api, planner_headers):
    """PRD §3.3: "whose `window_end` falls inside the trailing ninety-day
    window — inclusively on both ends, so a run ending exactly ninety days
    before the clock or exactly at the clock still counts"
    PRD §3.3: "`slow_mover` is true when the variety is at least ninety days
    old — its `created_at` is no later than the clock minus ninety days —
    **and** its `velocity_units_90d` is below 50,000 units."

    Design: Corner/calculations/velocity_window_lower_edge_is_inclusive
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Edge Brand")
    variety = create_variety(brand["id"], name="Edge Var")
    _, line = create_facility_with_line(capacity_pods_per_day=100000)

    # Ends one second before the trailing window's lower edge: excluded.
    outside = reserve_run(line["id"], variety["id"],
                          window_start="2026-09-03T00:00:00Z",
                          window_end="2026-09-10T23:59:59Z",
                          planned_units=90000)
    # Ends exactly at the lower edge (clock 2026-12-10 minus 90 days): counted.
    edge = reserve_run(line["id"], variety["id"],
                       window_start="2026-09-10T23:59:59Z",
                       window_end="2026-09-11T00:00:00Z",
                       planned_units=40000)

    set_clock("2026-09-03T12:00:00Z")
    get_success_data(transition_run(outside["id"], "IN_PROGRESS"))
    get_success_data(transition_run(outside["id"], "COMPLETED",
                                    actual_units=90000))

    set_clock("2026-09-10T23:59:59Z")
    get_success_data(transition_run(edge["id"], "IN_PROGRESS"))
    get_success_data(transition_run(edge["id"], "COMPLETED", actual_units=40000))

    set_clock("2026-12-10T00:00:00Z")
    read_back = get_success_data(api.get_pod_variety(variety["id"], planner_headers))
    assert read_back["velocity_units_90d"] == 40000
    assert read_back["slow_mover"] is True
