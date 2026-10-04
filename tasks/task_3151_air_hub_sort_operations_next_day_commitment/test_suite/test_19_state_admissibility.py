"""State admissibility on the package, bank, lane, hub and clock dimensions."""
import pytest

from test_helpers import (
    confirm_list,
    CLOCK_1414,
    CLOCK_1601,
    TEST_USERS as H,
    api_client as api,
    confirm,
    create_aircraft,
    create_bank,
    create_hub,
    create_lane,
    create_move,
    create_package,
    create_shift,
    declare_contingency,
    depart_and_land,
    failed_error_id,
    get_aircraft,
    get_bank,
    get_lane,
    ground_stop,
    induct,
    primary_sort,
    set_clock,
    setup_night,
    setup_six_lane_night,
)

CLOCK_1540 = "2026-09-02T01:40:00Z"
CLOCK_1581 = "2026-09-02T03:01:00Z"  # minute 1621, past cutoff+60


@pytest.fixture
def night():
    ctx = setup_six_lane_night()
    set_clock(CLOCK_1414)
    return ctx


def _fresh_package(night, tracking_number="1Z-ST-0001", **overrides):
    return create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                          planned_weight_grams=20000, dimension_weight_grams=20000,
                          **overrides)


def test_rejecting_induction_closes_the_dimension_for_the_rest_of_the_night(night):
    """PRD §3.1: "An operator may also refuse a package at the face, moving the induction
    dimension straight to `REJECTED`. That dimension is terminal: a rejected package can
    undertake no further sort, load or commitment action for the rest of the night."

    Design: Corner/state_machines/package_reject_induction_is_a_dead_end_dimension
    """
    package = _fresh_package(night, "1Z-ST-0002")
    rejected = confirm(api.reject_induction(package["id"], H["sort_operator_headers"]))
    assert rejected["induction_status"] == "REJECTED"

    repeat = api.reject_induction(package["id"], H["sort_operator_headers"])
    assert repeat.status_code == 409
    assert failed_error_id(repeat) == "ERR_INVALID_STATE"

    competing = api.induct_package(package["id"], {"dimension_weight_grams": 20000},
                                   H["sort_operator_headers"])
    assert competing.status_code == 409
    assert failed_error_id(competing) == "ERR_INVALID_STATE"

    from test_helpers import get_package
    read = get_package(package["id"])
    assert read["sort_status"] == "UNSORTED"
    assert read["rated_weight_grams"] is None


def test_a_second_induction_on_an_inducted_package_is_refused(night):
    """PRD §3.1: "When induction succeeds, the `induction_status` dimension moves to
    `INDUCTED`, the hub's live volume and the containing shift's variance both
    recompute, and the package's handling weight is established."

    Design: Corner/state_machines/package_induct_twice_returns_invalid_state
    """
    package = _fresh_package(night, "1Z-ST-0003")
    first = induct(package["id"])
    assert first["rated_weight_grams"] == 20000
    assert first["version"] == 2

    second = api.induct_package(package["id"], {"dimension_weight_grams": 90000},
                                H["sort_operator_headers"])
    assert second.status_code == 409
    assert failed_error_id(second) == "ERR_INVALID_STATE"

    from test_helpers import get_package
    assert get_package(package["id"])["rated_weight_grams"] == 20000, (
        "the 90000 payload was never applied"
    )


def test_a_downgrade_before_the_lead_window_is_refused(night):
    """PRD §3.9: "A downgrade attempted before the package has entered that window is refused
    with `ERR_CUTOFF_NOT_REACHED`, and one attempted after the grace window has
    closed is refused with `ERR_COMMITMENT_GRACE_EXCEEDED`."
    PRD §3.9: "The downgrade window is defined by two leads around the cutoff: it opens
    30 minutes before the cutoff and closes 60 minutes after it."

    Design: Corner/state_machines/package_downgrade_before_the_lead_window_returns_cutoff_not_reached
    """
    package = _fresh_package(night, "1Z-ST-0004")
    set_clock("2026-09-02T01:10:00Z")  # minute 1510
    attempt = api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_CUTOFF_NOT_REACHED"

    from test_helpers import get_package
    read = get_package(package["id"])
    assert read["commitment_status"] == "COMMITTED"
    assert read["final_commitment_minutes"] is None


def test_the_same_downgrade_succeeds_once_the_window_opens(night):
    """PRD §3.9: "It applies while the current minute is strictly after the cutoff minus 30
    and at or before the cutoff plus 60."

    Design: Corner/state_machines/package_downgrade_before_the_lead_window_returns_cutoff_not_reached
    """
    package = _fresh_package(night, "1Z-ST-0005")
    set_clock(CLOCK_1540)
    result = confirm(api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"]))
    assert result["commitment_status"] == "DOWNGRADED", (
        "the boundary is the lead window and not a blanket refusal"
    )


def test_a_downgrade_after_the_grace_clause_is_refused(night):
    """PRD §3.9: "one attempted after the grace window has closed is refused with
    `ERR_COMMITMENT_GRACE_EXCEEDED`."

    Design: Corner/state_machines/package_downgrade_after_the_grace_window_returns_commitment_grace_exceeded
    """
    package = _fresh_package(night, "1Z-ST-0006")
    set_clock(CLOCK_1581)
    attempt = api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_COMMITMENT_GRACE_EXCEEDED"

    from test_helpers import get_package
    assert get_package(package["id"])["commitment_status"] == "COMMITTED"
    failures, _ = confirm_list(api.list_failures(H["refund_adjuster_headers"],
                                            {"package_id": package["id"]}))
    assert failures == []


def test_opening_the_unload_face_requires_the_hydraulic_crew():
    """PRD §3.2: "Opening the bank's unload face is a `SortSupervisor` action, and it is
    refused on three grounds: the hydraulic crew must be available
    (`ERR_HYDRAULIC_CREW_UNAVAILABLE`), at least one aircraft in the bank must
    already be `LANDED`, and the hub must not be `GROUND_STOP`."

    Design: Corner/state_machines/bank_begin_unload_without_the_hydraulic_crew_returns_crew_unavailable
    """
    ctx = setup_six_lane_night()
    set_clock(CLOCK_1414)
    bank = create_bank(ctx["hub_id"], bank_code="BANK_H", hydraulic_crew_available=False)
    aircraft = create_aircraft(bank["id"], tail_number="N708UP")
    depart_and_land(aircraft["id"], 40000)

    attempt = api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_HYDRAULIC_CREW_UNAVAILABLE"
    assert get_bank(bank["id"])["status"] == "EN_ROUTE"
    assert get_bank(bank["id"])["actual_start_minutes"] is None
    assert get_aircraft(aircraft["id"])["status"] == "LANDED", (
        "the aircraft gate was satisfied and only the crew gate failed"
    )


def test_an_aircraft_may_not_begin_unload_before_the_bank_face_opens():
    """PRD §3.2: "beginning it while the bank itself is not `UNLOADING` is refused with
    `ERR_BANK_NOT_UNLOADING`."

    Design: Corner/state_machines/aircraft_begin_unload_while_the_bank_is_not_unloading_returns_bank_not_unloading
    """
    ctx = setup_night()
    set_clock(CLOCK_1414)
    bank = create_bank(ctx["hub_id"], bank_code="BANK_I")
    aircraft = create_aircraft(bank["id"], tail_number="N709UP")
    depart_and_land(aircraft["id"], 40000)

    attempt = api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_BANK_NOT_UNLOADING"
    assert get_bank(bank["id"])["status"] == "EN_ROUTE"

    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    opened = confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    assert opened["status"] == "UNLOADING"


def test_a_ground_stop_needs_a_lockdown_first():
    """PRD §3.4: "a ground stop attempted on a hub that is not locked down is refused with
    `ERR_HUB_NOT_LOCKED`."

    Design: Corner/state_machines/hub_ground_stop_requires_lockdown_first
    """
    ctx = setup_night()
    set_clock(CLOCK_1414)
    refusal = api.ground_stop(ctx["hub_id"], H["hub_ops_manager_headers"])
    assert refusal.status_code == 409
    assert failed_error_id(refusal) == "ERR_HUB_NOT_LOCKED"

    locked = confirm(api.declare_contingency(ctx["hub_id"], H["weather_officer_headers"]))
    assert locked["posture"] == "LOCKDOWN"
    stopped = confirm(api.ground_stop(ctx["hub_id"], H["hub_ops_manager_headers"]))
    assert stopped["posture"] == "GROUND_STOP"
    assert stopped["contingency_mode"] is True


def test_diversion_needs_a_declared_alternate_hub():
    """PRD §3.9: "requires the hub to actually have an `alternate_hub_id` — diving on a hub
    with none is refused with `ERR_NO_ALTERNATE_HUB` — requires the package not be
    parked at the hub, and requires the current minute be strictly past the
    cutoff."

    Design: Corner/state_machines/diverge_without_a_declared_alternate_hub_returns_no_alternate_hub
    """
    import test_helpers as th
    set_clock("2026-09-01T23:00:00Z")
    hub = create_hub()
    confirm(api.create_lane({"hub_id": hub["id"], "lane_code": "P-01", "lane_kind": "PRIMARY",
                             "commodity_capability": "GENERAL", "capacity_weight_grams": 60000,
                             "certified_until_minutes": 1700, "turnout_start_minutes": 1400,
                             "turnout_end_minutes": 1500}, H["sort_supervisor_headers"]), 201)
    bank = create_bank(hub["id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(hub["id"])
    set_clock("2026-09-01T23:20:00Z")
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))
    package = create_package(hub["id"], aircraft["id"], tracking_number="1Z-ST-0007",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    confirm(api.declare_contingency(hub["id"], H["weather_officer_headers"]))
    set_clock("2026-09-02T02:40:00Z")

    attempt = api.diverge_package(package["id"], H["commitment_controller_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_NO_ALTERNATE_HUB"
    read = confirm(api.get_package(package["id"], H["sort_operator_headers"]))
    assert read["commitment_status"] == "COMMITTED"
    assert read["handling_status"] == "NORMAL"
    assert read["handling_posture"] == "STANDARD"


def test_diversion_while_the_hub_is_not_locked_names_the_contingency_clause():
    """PRD §3.9: "Divergence is the decision to send the package somewhere other than here."

    Design: Corner/state_machines/diverge_while_the_hub_is_not_locked_returns_contingency_not_declared
    """
    night = setup_six_lane_night()
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-ST-0008",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    assert package["commitment_cutoff_minutes"] == 1560
    set_clock("2026-09-02T02:40:00Z")
    attempt = api.diverge_package(package["id"], H["commitment_controller_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_CONTINGENCY_NOT_DECLARED"

    hub = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert hub["contingency_mode"] is False
    assert hub["alternate_hub_id"] == night["alt_hub_id"]

    confirm(api.declare_contingency(night["hub_id"], H["weather_officer_headers"]))
    rerouted = confirm(api.diverge_package(package["id"], H["commitment_controller_headers"]))
    assert rerouted["commitment_status"] == "REROUTED"


def test_a_carrier_attributed_failure_is_not_a_dispute_candidate():
    """PRD §3.12: "Disputing is the opposite motion and is available only to a failure that is
    **not** carrier-attributed, because a carrier-attributed failure is a refund
    obligation rather than a dispute candidate;"

    Design: Corner/state_machines/service_failure_dispute_on_a_carrier_attribution_returns_not_disputable
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    first = _fresh_package(night, "1Z-ST-0009")
    second = _fresh_package(night, "1Z-ST-0010")
    carrier = confirm(api.create_failure(
        {"hub_id": night["hub_id"], "package_id": first["id"],
         "cause_code": "LATE_INBOUND", "failure_minutes": 1500},
        H["refund_adjuster_headers"]), 201)
    assert carrier["attributed_role"] == "CARRIER"

    refusal = api.dispute_failure(carrier["id"], H["refund_adjuster_headers"])
    assert refusal.status_code == 409
    assert failed_error_id(refusal) == "ERR_CARRIER_ATTRIBUTED_NOT_DISPUTABLE"
    assert confirm(api.get_failure(carrier["id"],
                                   H["refund_adjuster_headers"]))["status"] == "OPEN"

    customer = confirm(api.create_failure(
        {"hub_id": night["hub_id"], "package_id": second["id"],
         "cause_code": "BAD_ADDRESS", "failure_minutes": 1500},
        H["refund_adjuster_headers"]), 201)
    assert customer["attributed_role"] == "CUSTOMER"
    disputed = confirm(api.dispute_failure(customer["id"], H["refund_adjuster_headers"]))
    assert disputed["status"] == "DISPUTED", "the two failures differ only in cause_code"


def test_a_finalized_failure_blocks_the_package_void():
    """PRD §3.9: "provided it is not loaded and provided no failure on it has already been
    finalized — a finalized failure blocks the void with
    `ERR_FINALIZED_FAILURE_PRESENT` — whereupon the commitment becomes `VOIDED`
    and the handling `DIVERTED`, excluding the package from every load and feeder
    calculation."

    Design: Corner/state_machines/package_void_while_a_finalized_failure_exists_returns_finalized_failure_present
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = _fresh_package(night, "1Z-ST-0011")
    downgraded = confirm(api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"]))
    assert downgraded["commitment_status"] == "DOWNGRADED"

    failures, _ = confirm_list(api.list_package_failures(package["id"], H["refund_adjuster_headers"]))
    finalized = confirm(api.finalize_failure(failures[0]["id"], H["refund_adjuster_headers"]))
    assert finalized["status"] == "FINALIZED"

    attempt = api.void_package(package["id"], H["commitment_controller_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_FINALIZED_FAILURE_PRESENT"

    from test_helpers import get_package
    read = get_package(package["id"])
    assert read["commitment_status"] == "DOWNGRADED"
    assert read["sort_status"] == "UNSORTED"


def test_the_logical_clock_refuses_a_strictly_backward_move():
    """PRD §2.4: "Moving the clock strictly backwards is refused with
    `ERR_CLOCK_OUT_OF_ORDER` (HTTP 409), because the whole evening's arithmetic depends on
    a monotone minute."

    Design: Corner/state_machines/clock_backwards_move_returns_clock_out_of_order
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    attempt = api.set_clock("2026-09-02T00:00:00Z", H["hub_ops_manager_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_CLOCK_OUT_OF_ORDER"

    package = _fresh_package(night, "1Z-ST-0012")
    assert package["commitment_cutoff_minutes"] == 1560, "the clock remains where it was"

    forward = api.set_clock("2026-09-02T02:40:00Z", H["hub_ops_manager_headers"])
    assert forward.status_code == 200, "only strictly-backward moves are refused"


def test_feeder_staging_is_gated_on_the_owning_hub_sort_window():
    """PRD §3.8: "The owning hub must be inside its own sort window, meaning the current
    minute is at or after the hub's `sort_window_open_minutes` and strictly before its
    `sort_window_close_minutes`."

    Design: Corner/state_machines/feeder_staging_outside_the_owning_hub_sort_window_returns_invalid_state
    """
    night = setup_six_lane_night()
    from test_helpers import create_feeder, create_extension_shift
    create_extension_shift(night["hub_id"])
    late = create_feeder(night["hub_id"], feeder_code="F-late",
                         scheduled_departure_minutes=1610, window_minutes=20)
    ok = create_feeder(night["hub_id"], feeder_code="F-ok",
                       scheduled_departure_minutes=1560, window_minutes=20)

    # The admitted case is checked while the hub is still inside its own sort
    # window; the refused case needs a minute past the window's close, so it has
    # to come second (the logical clock is monotone).
    set_clock("2026-09-02T01:40:00Z")  # minute 1540
    admitted = confirm(api.begin_staging(ok["id"], H["feeder_coordinator_headers"]))
    assert admitted["status"] == "STAGING", "its own timing clause holds and the hub window is open"

    set_clock("2026-09-02T02:40:00Z")  # minute 1600, past the hub's 1560 close
    refusal = api.begin_staging(late["id"], H["feeder_coordinator_headers"])
    assert refusal.status_code == 409
    assert failed_error_id(refusal) == "ERR_INVALID_STATE"
    from test_helpers import get_feeder
    assert get_feeder(late["id"])["status"] == "SCHEDULED", (
        "its own timing clause holds, so the hub window is what refused it"
    )


def test_the_lane_axis_round_trips_and_refuses_a_repeat_on_both_sides():
    """PRD §3.3: "A lane starts `AVAILABLE` and moves to `SATURATED` automatically once its
    load reaches its capacity, back to `AVAILABLE` when the load falls below capacity, and
    to `CLOSED` or back by explicit supervisor action."

    Design: Corner/state_machines/lane_close_and_reopen_round_trip_refuses_a_second_close
    """
    night = setup_six_lane_night()
    lane_id = night["lane_p1_id"]
    assert get_lane(lane_id)["status"] == "AVAILABLE"
    assert get_lane(lane_id)["lane_load_grams"] == 0

    closed = confirm(api.close_lane(lane_id, H["sort_supervisor_headers"]))
    assert closed["status"] == "CLOSED"
    again = api.close_lane(lane_id, H["sort_supervisor_headers"])
    assert again.status_code == 409
    assert failed_error_id(again) == "ERR_INVALID_STATE"

    reopened = confirm(api.reopen_lane(lane_id, H["sort_supervisor_headers"]))
    assert reopened["status"] == "AVAILABLE"
    reopen_again = api.reopen_lane(lane_id, H["sort_supervisor_headers"])
    assert reopen_again.status_code == 409
    assert failed_error_id(reopen_again) == "ERR_INVALID_STATE"
    assert get_lane(lane_id)["status"] == "AVAILABLE"


def test_clearing_an_upgrade_hold_is_gated_on_the_inbound_aircraft():
    """PRD §3.9: "An `UPGRADED_HELD` package may have its hold cleared only while its aircraft
    is no longer cancelled and the contingency is clear;"

    Design: Corner/state_machines/clear_upgrade_hold_gated_on_the_inbound_aircraft_status
    """
    night = setup_six_lane_night()
    set_clock("2026-09-02T02:40:00Z")
    from test_helpers import cancel_aircraft, land_second_aircraft
    land_second_aircraft(night, inbound_weight_grams=40000, unload_minutes=1600, complete=True)
    package = create_package(night["hub_id"], night["ac2_id"], tracking_number="1Z-ST-0013",
                             destination_hub_code="ORD", planned_weight_grams=20000,
                             dimension_weight_grams=20000)
    cancelled = cancel_aircraft(night["ac2_id"], "MECHANICAL")
    assert cancelled["status"] == "CANCELLED"

    from test_helpers import get_package
    held = get_package(package["id"])
    assert held["commitment_status"] == "UPGRADED_HELD"
    assert held["handling_status"] == "HOLD_AT_HUB"

    attempt = api.clear_upgrade_hold(package["id"], H["commitment_controller_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_AIRCRAFT_NOT_CANCELLED"
    assert get_package(package["id"])["commitment_status"] == "UPGRADED_HELD"
    assert confirm(api.get_hub(night["hub_id"],
                               H["hub_ops_manager_headers"]))["contingency_mode"] is False


def test_a_maintenance_diversion_is_a_self_transition_that_clears_the_arrival_stamp():
    """PRD §3.4: "the diversion is a self-transition that leaves the aircraft `IN_FLIGHT` but
    sets its `maintenance_hold` and clears `actual_arrival_minutes` to null, so
    the aircraft is excluded from every unload computation while remaining
    nominally in the air — the bank's effective sort budget recomputes
    accordingly."

    Design: Corner/state_machines/aircraft_maintenance_diversion_is_a_self_transition_that_clears_the_arrival_stamp
    """
    night = setup_six_lane_night()
    set_clock("2026-09-01T23:20:00Z")
    bank_b = create_bank(night["hub_id"], bank_code="BANK_B", scheduled_end_minutes=1550)
    aircraft = create_aircraft(bank_b["id"], tail_number="N703UP",
                               origin_station_code="DFW", scheduled_arrival_minutes=1390)
    from test_helpers import depart_origin
    depart_origin(aircraft["id"])

    premature = api.divert_maintenance(aircraft["id"], H["weather_officer_headers"])
    assert premature.status_code == 409
    assert failed_error_id(premature) == "ERR_CONTINGENCY_NOT_DECLARED"

    confirm(api.declare_contingency(night["hub_id"], H["weather_officer_headers"]))
    diverted = confirm(api.divert_maintenance(aircraft["id"], H["weather_officer_headers"]))
    assert diverted["status"] == "IN_FLIGHT"
    assert diverted["maintenance_hold"] is True
    assert diverted["actual_arrival_minutes"] is None
    assert get_bank(bank_b["id"])["effective_sort_budget_minutes"] == 45