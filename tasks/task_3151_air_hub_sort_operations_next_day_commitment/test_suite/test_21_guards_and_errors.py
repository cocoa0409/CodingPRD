"""Guards on the sort, load, induction, claim, and clock paths."""
import pytest

from test_helpers import (
    confirm_list,
    TEST_USERS as H,
    api_client as api,
    confirm,
    create_aircraft,
    create_bank,
    create_buildup,
    create_lane,
    create_move,
    create_package,
    create_shift,
    depart_and_land,
    failed_error_id,
    get_lane,
    get_package,
    induct,
    plan_move,
    primary_sort,
    secondary_sort,
    set_clock,
    setup_six_lane_night,
)

CLOCK_1450 = "2026-09-02T00:40:00Z"


def test_onboarding_into_a_zero_cap_buildup_is_refused_for_hazardous_content():
    """PRD §3.6: "The hazardous cap guard rejects onboarding a `HAZMAT` package whose rated
    weight, added to the target buildup's existing hazardous weight, would exceed
    that buildup's `hazardous_cap_grams`, with `ERR_HAZMAT_CAP_EXCEEDED` (HTTP
    409)."

    Design: Corner/validations/hazmat_package_into_a_zero_cap_buildup_returns_cap_exceeded
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000,
                             hazardous_cap_grams=0)
    plan_move(move["id"])

    hazmat = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-HC-0001",
                            commodity_class="HAZMAT", planned_weight_grams=30000,
                            dimension_weight_grams=30000)
    induct(hazmat["id"])
    # The primary sort carries the automatic commodity diversion (PRD 3.3).
    routed = primary_sort(hazmat["id"], night["lane_hz1_id"])
    assert routed["handling_status"] == "ROUTED_TO_HAZMAT"
    from test_helpers import create_lane as _lane
    hazmat_secondary = _lane(night["hub_id"], lane_code="S-HZ", lane_kind="HAZMAT",
                             commodity_capability="HAZMAT", capacity_weight_grams=400000,
                             certified_until_minutes=1700,
                             turnout_start_minutes=1400, turnout_end_minutes=1600)
    secondary_sort(hazmat["id"], hazmat_secondary["id"])

    from test_helpers import onboard_outcome, get_buildup
    attempt = onboard_outcome(move["id"], hazmat["id"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_HAZMAT_CAP_EXCEEDED"

    read = get_buildup(buildup["id"])
    assert read["hazardous_cap_grams"] == 0, "a cap of zero accepts no hazardous content"
    assert read["hazardous_weight_grams"] == 0, "the refused row was never taken in"
    assert read["status"] == "OPEN"
    assert get_package(hazmat["id"])["sort_status"] == "SECONDARY_SORTED"


def test_a_positive_hazardous_cap_is_breached_at_any_weight_above_it():
    """PRD §3.6: "an optional `hazardous_cap_grams` (defaulting to zero, and a cap of zero
    means the buildup accepts no hazardous content at all), and an optional
    `requires_container` flag defaulting to false."

    Design: Corner/errors/err_hazmat_cap_exceeded_reachable_when_the_buildup_declares_a_positive_cap
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=200000,
                             hazardous_cap_grams=10000)
    plan_move(move["id"])

    hazmat = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-HC-0002",
                            commodity_class="HAZMAT", planned_weight_grams=20000,
                            dimension_weight_grams=20000)
    induct(hazmat["id"])
    # The primary sort carries the automatic commodity diversion (PRD 3.3).
    primary_sort(hazmat["id"], night["lane_hz1_id"])
    hazmat_secondary = create_lane(night["hub_id"], lane_code="S-HZ", lane_kind="HAZMAT",
                                   commodity_capability="HAZMAT", capacity_weight_grams=400000,
                                   certified_until_minutes=1700,
                                   turnout_start_minutes=1400, turnout_end_minutes=1600)
    secondary_sort(hazmat["id"], hazmat_secondary["id"])

    from test_helpers import onboard_outcome, get_buildup
    attempt = onboard_outcome(move["id"], hazmat["id"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_HAZMAT_CAP_EXCEEDED"

    read = get_buildup(buildup["id"])
    assert read["hazardous_cap_grams"] == 10000
    assert read["hazardous_weight_grams"] == 0, "the refused row was never taken in"
    assert read["container_limit_grams"] == 200000, "only the hazardous cap failed"


def test_completing_an_overweight_move_is_refused_but_a_fitting_move_completes():
    """PRD §3.6: "The move's planned weight must not exceed its weight limit plus a
    use-it-or-lose-it tolerance of 10000 grams, with a breach reported as
    `ERR_LOAD_WEIGHT_EXCEEDED`."

    Design: Corner/validations/load_move_completion_refuses_an_overweight_manifest
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    from test_helpers import create_bank as _bank
    from test_helpers import setup_outbound_aircraft, onboard_package

    heavy = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=100000)
    plan_move(heavy["id"])
    fitting_aircraft = setup_outbound_aircraft(night, tail_number="N710UP")
    fitting = create_move(night["hub_id"], fitting_aircraft["aircraft_id"],
                          weight_limit_grams=100000)
    plan_move(fitting["id"])

    big = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-OW-0001",
                         planned_weight_grams=100000, dimension_weight_grams=100000)
    small = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-OW-0002",
                           planned_weight_grams=20000, dimension_weight_grams=20000)
    exact = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-OW-0003",
                           planned_weight_grams=100000, dimension_weight_grams=100000)
    # The three packages rate far above the standard concourse's 60000-gram lanes,
    # so they are sorted through dedicated wide lanes.
    wide_p = create_lane(night["hub_id"], lane_code="P-OW", lane_kind="PRIMARY",
                         commodity_capability="GENERAL", capacity_weight_grams=900000,
                         certified_until_minutes=1700,
                         turnout_start_minutes=1400, turnout_end_minutes=1500)
    wide_s = create_lane(night["hub_id"], lane_code="S-OW", lane_kind="SECONDARY",
                         commodity_capability="GENERAL", capacity_weight_grams=900000,
                         certified_until_minutes=1700,
                         turnout_start_minutes=1400, turnout_end_minutes=1600)
    for pkg in (big, small, exact):
        induct(pkg["id"])
        primary_sort(pkg["id"], wide_p["id"])
        secondary_sort(pkg["id"], wide_s["id"])

    # The over-manifest move carries 120000 grams against a 100000-gram limit, so
    # its planned weight breaches the use-it-or-lose-it tolerance when it seals.
    onboard_package(heavy["id"], big["id"])
    onboard_package(heavy["id"], small["id"])
    # Completing a load is itself a LOADING -> LOADED step, so the move has to be
    # physically loading before the seal guard is reachable.
    confirm(api.begin_loading(heavy["id"], H["load_planner_headers"]))
    confirm(api.begin_loading(fitting["id"], H["load_planner_headers"]))

    attempt = api.complete_load(heavy["id"], H["load_planner_headers"])
    assert attempt.status_code == 409, attempt.text
    assert failed_error_id(attempt) == "ERR_LOAD_WEIGHT_EXCEEDED"
    read = confirm(api.get_move(heavy["id"], H["load_planner_headers"]))
    assert read["status"] == "LOADING", "the completed-move guard refused the seal"
    assert read["planned_weight_grams"] == 120000, "120000 exceeds 100000 + 10000"

    onboard_package(fitting["id"], exact["id"])
    sealed = confirm(api.complete_load(fitting["id"], H["load_planner_headers"]))
    assert sealed["status"] == "LOADED", "100000 does not exceed the same limit plus the tolerance"


def test_resolving_an_irregular_routing_inside_the_budget_returns_to_normal():
    """PRD §3.5: "a package may be resolved while its last sort minute is null, or while
    the current minute is at or before that last sort minute plus 45."
    PRD §3.5: "Resolution back to normal is also the supervisor's — or, for a hazardous
    routing, the `HazmatCertifier`'s — and both resolutions are bounded by an
    irregular resolve budget of 45 minutes measured from `last_sort_minutes`: a
    package may be resolved while its last sort minute is null, or while the
    current minute is at or before that last sort minute plus 45."

    Design: Corner/validations/irregular_resolve_within_budget_returns_normal
    """
    night = setup_six_lane_night()
    fresh = create_lane(night["hub_id"], lane_code="P-IR", lane_kind="PRIMARY",
                        commodity_capability="PERISHABLE", capacity_weight_grams=60000,
                        certified_until_minutes=1700,
                        turnout_start_minutes=1400, turnout_end_minutes=1500)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-IR-0001",
                             commodity_class="PERISHABLE", planned_weight_grams=20000,
                             dimension_weight_grams=20000)
    induct(package["id"])
    sorted_pkg = primary_sort(package["id"], fresh["id"])
    assert sorted_pkg["handling_status"] == "ROUTED_TO_IRREGULAR"
    assert sorted_pkg["handling_posture"] == "IRREGULAR_LANE"

    set_clock("2026-09-01T23:40:00Z")  # minute 1420, nineteen minutes later
    resolved = confirm(api.resolve_irregular(package["id"], H["sort_supervisor_headers"]))
    assert resolved["handling_status"] == "NORMAL"
    assert resolved["handling_posture"] == "STANDARD"
    assert resolved["sort_status"] == "PRIMARY_SORTED", "the resolve did not disturb the sort plane"

    still_routed, _ = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                                {"handling_status": "ROUTED_TO_IRREGULAR"}))
    assert still_routed == []


def test_a_lane_closed_for_business_blocks_every_later_sort():
    """PRD §3.3: "A closed lane, or one whose capability does not match the package's commodity
    class, is refused with `ERR_LANE_NOT_AVAILABLE`;"

    Design: Corner/endpoints/lane_close_blocks_any_further_sort_onto_that_lane
    """
    night = setup_six_lane_night()
    set_clock("2026-09-01T23:30:00Z")
    first = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LB-0001",
                           planned_weight_grams=20000, dimension_weight_grams=20000)
    second = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LB-0002",
                            planned_weight_grams=20000, dimension_weight_grams=20000)
    induct(first["id"])
    induct(second["id"])

    closed = confirm(api.close_lane(night["lane_p1_id"], H["sort_supervisor_headers"]))
    assert closed["status"] == "CLOSED"

    attempt = api.primary_sort(first["id"], {"lane_id": night["lane_p1_id"]},
                               H["sort_operator_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_LANE_NOT_AVAILABLE"
    read = get_package(first["id"])
    assert read["sort_status"] == "UNSORTED"
    assert read["assigned_lane_id"] is None

    sibling = primary_sort(second["id"], night["lane_p2_id"])
    assert sibling["sort_status"] == "PRIMARY_SORTED", "the sibling lane still works"
    assert get_lane(night["lane_p1_id"])["lane_load_grams"] == 0, (
        "the refused sort consumed no capacity"
    )


def test_the_volume_override_moves_posture_until_the_next_package_event():
    """PRD §2.6: "An operator may also replace the value outright by declaring a figure;
    that override stands until the next package mutation recomputes the total in the
    ordinary way."

    Design: Corner/endpoints/hub_volume_override_replaces_the_planning_set_and_moves_posture
    """
    night = setup_six_lane_night()
    set_clock("2026-09-01T23:20:00Z")
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-VO-0001",
                   planned_weight_grams=100000, dimension_weight_grams=100000)

    derived = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert derived["live_planned_package_total"] == 100000
    assert derived["posture"] == "OPEN"

    overridden = confirm(api.volume_override(night["hub_id"],
                                             {"live_planned_package_total": 400000},
                                             H["hub_ops_manager_headers"]))
    assert overridden["live_planned_package_total"] == 400000
    assert overridden["posture"] == "CONGESTED"

    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-VO-0002",
                   planned_weight_grams=100, dimension_weight_grams=100)
    recomputed = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert recomputed["live_planned_package_total"] == 100100
    assert recomputed["posture"] == "OPEN", "a single 100-gram creation discards the override"


def test_a_ground_stop_forces_a_move_into_rework_and_replan_waits_for_the_clear():
    """PRD §3.6: "It can be forced into `REWORK_REQUIRED` — automatically when the hub's
    posture becomes `LOCKDOWN` or `GROUND_STOP` from `PLANNED`, or by the ground
    stop from `LOADING` — and it can be replanned back to `PLANNED` once the
    contingency has been cleared, or cancelled from `DRAFT`, from `PLANNED` while
    nothing on it is loaded, or from `REWORK_REQUIRED` at any time."

    Design: Corner/endpoints/rework_load_move_returns_to_planning_after_contingency_clears
    """
    night = setup_six_lane_night()
    set_clock("2026-09-02T00:40:00Z")
    from test_helpers import onboard_package
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    plan_move(move["id"])
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RW-0001",
                             planned_weight_grams=50000, dimension_weight_grams=50000)
    induct(package["id"])
    primary_sort(package["id"], night["lane_p1_id"])
    secondary_sort(package["id"], night["lane_s1_id"])
    loaded = onboard_package(move["id"], package["id"])
    assert loaded["status"] == "PLANNED", "onboarding does not begin the load"

    confirm(api.declare_contingency(night["hub_id"], H["weather_officer_headers"]))
    stopped = confirm(api.ground_stop(night["hub_id"], H["hub_ops_manager_headers"]))
    assert stopped["posture"] == "GROUND_STOP"

    reworked = confirm(api.get_move(move["id"], H["load_planner_headers"]))
    assert reworked["status"] == "REWORK_REQUIRED"
    assert reworked["loaded_weight_grams"] == 0
    assert get_package(package["id"])["sort_status"] == "SECONDARY_SORTED", (
        "the package returned to the sort surface"
    )

    # Replanning is available "once the contingency has been cleared" (PRD 3.6); the
    # PRD does not name the identifier for a replan attempted while it is still
    # declared, so either of the two admissible refusals is accepted.
    from test_helpers import validate_error_is_one_of
    locked = api.replan_move(move["id"], H["load_planner_headers"])
    assert locked.status_code == 409, locked.text
    assert validate_error_is_one_of(
        locked, ["ERR_INVALID_STATE", "ERR_CONTINGENCY_NOT_DECLARED"]) in (
            "ERR_INVALID_STATE", "ERR_CONTINGENCY_NOT_DECLARED")

    confirm(api.clear_contingency(night["hub_id"], H["hub_ops_manager_headers"]))
    replanned = confirm(api.replan_move(move["id"], H["load_planner_headers"]))
    assert replanned["status"] == "PLANNED"


def test_the_certification_error_is_reachable_from_the_secondary_sort_alone():
    """PRD §3.3: "The target secondary lane must exist, be `AVAILABLE`, be certified for the
    candidate's commodity class, and still be certified at the current minute."

    Design: Corner/errors/err_lane_certification_lapsed_is_reachable_beyond_its_priority_pair_use
    """
    night = setup_six_lane_night()
    already_lapsed = create_lane(night["hub_id"], lane_code="S-LAP", lane_kind="SECONDARY",
                                 commodity_capability="GENERAL", capacity_weight_grams=60000,
                                 certified_until_minutes=1560,
                                 turnout_start_minutes=1400, turnout_end_minutes=1600)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CL-0001",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    induct(package["id"])
    primary_sort(package["id"], night["lane_p1_id"])

    set_clock("2026-09-02T06:01:00Z")  # minute 1801
    attempt = api.secondary_sort(package["id"], {"lane_id": already_lapsed["id"]},
                                 H["sort_operator_headers"])
    assert attempt.status_code == 409
    assert failed_error_id(attempt) == "ERR_LANE_CERTIFICATION_LAPSED"
    assert get_lane(already_lapsed["id"])["certified_until_minutes"] == 1560
    assert get_package(package["id"])["sort_status"] == "PRIMARY_SORTED"


def test_the_stale_version_error_is_reachable_through_the_downgrade_write():
    """PRD §2.9: "A commitment downgrade sent against a package must carry
    `expected_package_version`, the client's last observed `version` of the target
    package."

    Design: Corner/errors/err_stale_version_surfaces_via_the_downgrade_write_endpoint
    """
    night = setup_six_lane_night()
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-SV-0001",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    stale_version = package["version"]
    set_clock("2026-09-02T01:40:00Z")
    inducted = induct(package["id"])
    current_version = inducted["version"]

    stale = api.downgrade_commitment(
        package["id"], {"expected_package_version": stale_version},
        H["commitment_controller_headers"])
    assert stale.status_code == 412
    assert failed_error_id(stale) == "ERR_STALE_VERSION"
    assert get_package(package["id"])["commitment_status"] == "COMMITTED"

    success = confirm(api.downgrade_commitment(
        package["id"], {"expected_package_version": current_version},
        H["commitment_controller_headers"]))
    assert success["commitment_status"] == "DOWNGRADED", (
        "the 412 was version staleness and not a state refusal"
    )


def test_the_single_unload_face_and_the_arrival_regression_are_both_refused():
    """PRD §3.2: "beginning an aircraft's unload while another aircraft on the same bank
    already holds `UNLOADING` is refused with `ERR_UNLOAD_FACE_OCCUPIED` (HTTP
    409), and beginning it while the bank itself is not `UNLOADING` is refused
    with `ERR_BANK_NOT_UNLOADING`."
    PRD §3.2: "an earlier figure is refused with `ERR_LATE_UNLOAD_REGRESSION`."

    Design: Corner/errors/err_unload_face_occupied_and_err_late_unload_regression_are_reachable
    """
    night = setup_six_lane_night()
    set_clock("2026-09-01T23:20:00Z")
    from test_helpers import (depart_and_land, get_aircraft, begin_aircraft_unload,
                              create_aircraft, open_unload_face)
    # A dedicated bank with two landed aircraft: opening its face puts BOTH into
    # UNLOADING, so each subsequently finds the other holding the single face.
    face_bank = create_bank(night["hub_id"], bank_code="BANK_F",
                            scheduled_start_minutes=1400, scheduled_end_minutes=1520)
    left = create_aircraft(face_bank["id"], tail_number="N720UP",
                           scheduled_arrival_minutes=1395)
    right = create_aircraft(face_bank["id"], tail_number="N721UP",
                            scheduled_arrival_minutes=1399)
    depart_and_land(left["id"], 40000)
    depart_and_land(right["id"], 40000)
    open_unload_face(face_bank["id"])

    face = api.begin_aircraft_unload(right["id"], H["sort_supervisor_headers"])
    assert face.status_code == 409, face.text
    assert failed_error_id(face) == "ERR_UNLOAD_FACE_OCCUPIED"

    # N720UP is on the face and landed at minute 1400, so an unload stamped 1390
    # precedes its own arrival.
    regression = api.complete_aircraft_unload(
        left["id"], {"unload_completed_minutes": 1390}, H["sort_supervisor_headers"])
    assert regression.status_code == 409, regression.text
    assert failed_error_id(regression) == "ERR_LATE_UNLOAD_REGRESSION"


def test_the_idempotency_key_is_enforced_rather_than_advisory():
    """PRD §3.1: "a client may supply an `acknowledgement_number` — an idempotency key — whose
    replay on the same hub returns the original package with a `200` rather than
    minting a second record;"
    PRD §3.1: "if this hub already carries a package with that number whose
    `commitment_status` is neither `VOIDED` nor `DIVERTED`, the creation is
    refused with `ERR_DUPLICATE_LIVE_PACKAGE` (HTTP 409)."

    Design: Corner/errors/err_ack_mismatch_is_reachable_on_package_creation
    """
    night = setup_six_lane_night()
    set_clock("2026-09-01T23:20:00Z")
    payload = {"hub_id": night["hub_id"], "aircraft_id": night["ac1_id"],
               "tracking_number": "1Z-AK-0001", "commodity_class": "GENERAL",
               "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
               "planned_weight_grams": 20000, "dimension_weight_grams": 20000,
               "acknowledgement_number": "ACK-0001"}
    original = confirm(api.create_package(payload, H["sort_operator_headers"]), 201)

    replay = confirm(api.create_package(payload, H["sort_operator_headers"]), 200)
    assert replay["id"] == original["id"], "the identical replay returns the original package"

    mismatched = dict(payload)
    mismatched["planned_weight_grams"] = 90000
    refusal = api.create_package(mismatched, H["sort_operator_headers"])
    assert refusal.status_code == 409
    assert failed_error_id(refusal) == "ERR_ACK_MISMATCH"

    packages, meta = confirm_list(api.list_packages(H["sort_operator_headers"],
                                               {"hub_id": night["hub_id"]}))
    assert meta["total_count"] == 1, "the replay did not create a second row"
    assert get_package(original["id"])["planned_weight_grams"] == 20000
    assert confirm(api.get_hub(night["hub_id"],
                               H["hub_ops_manager_headers"]))["live_planned_package_total"] == 20000


def test_a_tracking_number_is_unique_only_while_the_earlier_package_is_live():
    """PRD §3.1: "A hub may not hold two live packages with the same `tracking_number`: if
    this hub already carries a package with that number whose `commitment_status` is
    neither `VOIDED` nor `DIVERTED`, the creation is refused with
    `ERR_DUPLICATE_LIVE_PACKAGE` (HTTP 409)."

    Design: Corner/errors/err_duplicate_live_package_is_reachable_for_a_reused_tracking_number
    """
    night = setup_six_lane_night()
    set_clock("2026-09-01T23:20:00Z")
    payload = {"hub_id": night["hub_id"], "aircraft_id": night["ac1_id"],
               "tracking_number": "1Z-DP-0001", "commodity_class": "GENERAL",
               "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
               "planned_weight_grams": 20000, "dimension_weight_grams": 20000}
    original = confirm(api.create_package(payload, H["sort_operator_headers"]), 201)

    duplicate = dict(payload)
    duplicate["planned_weight_grams"] = 30000
    duplicate["dimension_weight_grams"] = 30000
    refusal = api.create_package(duplicate, H["sort_operator_headers"])
    assert refusal.status_code == 409
    assert failed_error_id(refusal) == "ERR_DUPLICATE_LIVE_PACKAGE"

    # The number is freed only when the earlier package reads VOIDED or DIVERTED in
    # its COMMITMENT dimension (PRD 3.1); a voided downgrade is the compensating
    # exit that produces exactly that.
    set_clock("2026-09-02T02:40:00Z")
    downgraded = confirm(api.downgrade_commitment(
        original["id"], {"expected_package_version": original["version"]},
        H["commitment_controller_headers"]))
    assert downgraded["commitment_status"] == "DOWNGRADED"
    failures, _ = confirm_list(api.list_package_failures(original["id"],
                                                         H["refund_adjuster_headers"]))
    voided = confirm(api.void_package(original["id"], H["commitment_controller_headers"]))
    assert voided["commitment_status"] == "VOIDED"

    reused = confirm(api.create_package(duplicate, H["sort_operator_headers"]), 201)
    assert reused["id"] != original["id"]
    packages, meta = confirm_list(api.list_packages(H["sort_operator_headers"],
                                               {"hub_id": night["hub_id"]}))
    assert meta["total_count"] == 2


def test_an_out_of_enum_commodity_class_never_reaches_the_routing_logic():
    """PRD §3.1: "a `commodity_class`, one of the four enumerated values `GENERAL`,
    `IRREGULAR`, `HAZMAT` or `PERISHABLE`;"

    Design: Corner/errors/err_invalid_request_for_an_out_of_enum_commodity_class
    """
    night = setup_six_lane_night()
    set_clock("2026-09-01T23:20:00Z")
    response = api.create_package(
        {"hub_id": night["hub_id"], "aircraft_id": night["ac1_id"],
         "tracking_number": "1Z-CM-0001", "commodity_class": "DRY_ICE",
         "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
         "planned_weight_grams": 20000, "dimension_weight_grams": 20000},
        H["sort_operator_headers"])
    assert response.status_code == 400
    assert failed_error_id(response) == "ERR_INVALID_REQUEST"
    packages, meta = confirm_list(api.list_packages(H["sort_operator_headers"],
                                               {"hub_id": night["hub_id"]}))
    assert meta["total_count"] == 0