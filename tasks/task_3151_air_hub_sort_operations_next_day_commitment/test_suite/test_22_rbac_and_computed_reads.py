"""Peer-role exclusivity, the shared read surface, and computed reads."""
import pytest

from test_helpers import (
    confirm_list,
    CLOCK_1540,
    TEST_USERS as H,
    api_client as api,
    assert_version_incremented,
    begin_staging,
    confirm,
    create_buildup,
    create_feeder,
    create_lane,
    create_move,
    create_package,
    create_shift,
    declare_contingency,
    failed_error_id,
    get_lane,
    get_package,
    headers_for,
    headers_without_role,
    induct,
    onboard_package,
    plan_move,
    primary_sort,
    secondary_sort,
    set_clock,
    setup_six_lane_night,
    stage_package,
    begin_feeder_loading,
)

CLOCK_1414 = "2026-09-01T23:34:00Z"
CLOCK_1430 = "2026-09-01T23:50:00Z"


def test_a_recognised_but_unpermitted_role_is_refused_for_hub_creation():
    """PRD §2.1: "Authorization is enforced after authentication. Each role owns a disjoint
    set of exclusive operations, and a call to an operation outside the acting role's set is
    refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`HubOpsManager` owns the logical-clock pin, clearing a contingency, the
    ground-stop escalation, aircraft cancellation and reinstatement, bank
    abandonment, and the two ops-checkpoint dispositions;"

    Design: Corner/rbac/onboarding_channel_cannot_create_a_hub
    """
    set_clock("2026-09-01T23:20:00Z")
    body = {"iata_code": "SDF", "name": "Worldport Louisville",
            "sort_window_open_minutes": 1380, "sort_window_close_minutes": 1560}
    refused = api.create_hub(body, H["gateway_coordinator_headers"])
    assert refused.status_code == 403
    assert failed_error_id(refused) == "ERR_UNAUTHORIZED"
    assert refused.json()["data"]["error_id"] != "ERR_UNAUTHENTICATED", (
        "the role was recognised and merely not permitted"
    )

    admitted = confirm(api.create_hub(body, H["hub_ops_manager_headers"]), 201)
    assert admitted["version"] >= 1
    hubs, meta = confirm_list(api.list_hubs(H["hub_ops_manager_headers"]))
    assert meta["total_count"] == 1


def test_the_contingency_authority_is_exclusive_to_the_weather_officer():
    """PRD §2.1: "`WeatherOfficer` owns contingency declaration, weather-driven aircraft
    diversion, and may append a claim to a failure;"

    Design: Corner/rbac/sort_operator_cannot_declare_a_contingency
    """
    night = setup_six_lane_night()
    refused = api.declare_contingency(night["hub_id"], H["sort_operator_headers"])
    assert refused.status_code == 403
    assert failed_error_id(refused) == "ERR_UNAUTHORIZED"

    hub = confirm(api.get_hub(night["hub_id"], H["sort_operator_headers"]))
    assert hub["contingency_mode"] is False
    assert hub["posture"] == "OPEN"

    admitted = confirm(api.declare_contingency(night["hub_id"],
                                               H["weather_officer_headers"]))
    assert admitted["posture"] == "LOCKDOWN", (
        "the same operator may still read the hub, so the refusal is operation-specific"
    )


def test_authentication_precedes_authorization_and_existence():
    """PRD §2.1: "A request that omits `X-User-Role`, or that supplies a role outside this
    set, fails with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    set_clock("2026-09-01T23:20:00Z")
    with_role = api.get_hub("00000000-0000-4000-8000-000000000000",
                            H["hub_ops_manager_headers"])
    assert with_role.status_code == 404, "authentication passed and the existence check bit"
    assert failed_error_id(with_role) == "ERR_RESOURCE_NOT_FOUND"

    without_role = api.get_hub("00000000-0000-4000-8000-000000000000",
                               headers_without_role())
    assert without_role.status_code == 401
    assert failed_error_id(without_role) == "ERR_UNAUTHENTICATED"

    unknown_role = api.get_hub("00000000-0000-4000-8000-000000000000",
                               headers_for("NightAuditor"))
    assert unknown_role.status_code == 401
    assert failed_error_id(unknown_role) == "ERR_UNAUTHENTICATED"


def test_the_listing_surface_is_shared_across_the_peer_roles():
    """PRD §2.1: "Read endpoints across all of the resource collections are shared by all ten
    roles, and appending a claim to a failure is shared by `RefundAdjuster`,
    `HubOpsManager` and `WeatherOfficer`."

    Design: Corner/rbac/readonly_roles_share_every_listing_endpoint
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-SH-0001",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    failure = confirm(api.create_failure(
        {"hub_id": night["hub_id"], "package_id": package["id"], "cause_code": "SORT_MISS",
         "failure_minutes": 1500}, H["refund_adjuster_headers"]), 201)

    shifts, _ = confirm_list(api.list_shifts(H["refund_adjuster_headers"],
                                        {"hub_id": night["hub_id"]}))
    assert shifts[0]["id"] == night["shift_id"], "a refund adjuster may read labor shifts"

    failures, _ = confirm_list(api.list_failures(H["sort_supervisor_headers"],
                                            {"hub_id": night["hub_id"]}))
    assert failures[0]["id"] == failure["id"], "a sort supervisor may read service failures"

    refused = api.create_failure(
        {"hub_id": night["hub_id"], "package_id": package["id"], "cause_code": "SORT_MISS",
         "failure_minutes": 1500}, H["sort_supervisor_headers"])
    assert refused.status_code == 403, "creating a failure is still exclusive"


def test_the_duty_manager_role_is_a_peer_rather_than_a_superset():
    """PRD §2.1: "`SortOperator` owns package creation, induction and induction rejection,
    primary and secondary sort, and lane reclaim;"

    Design: Corner/rbac/hub_ops_manager_cannot_onboard_a_package
    """
    night = setup_six_lane_night()
    body = {"hub_id": night["hub_id"], "aircraft_id": night["ac1_id"],
            "tracking_number": "1Z-HO-0001", "commodity_class": "GENERAL",
            "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
            "planned_weight_grams": 20000, "dimension_weight_grams": 20000}

    refused = api.create_package(body, H["hub_ops_manager_headers"])
    assert refused.status_code == 403
    assert failed_error_id(refused) == "ERR_UNAUTHORIZED"

    admitted = confirm(api.create_package(body, H["sort_operator_headers"]), 201)
    packages, meta = confirm_list(api.list_packages(H["sort_operator_headers"],
                                               {"hub_id": night["hub_id"]}))
    assert meta["total_count"] == 1
    assert confirm(api.get_hub(night["hub_id"],
                               H["hub_ops_manager_headers"]))["live_planned_package_total"] == 20000
    assert admitted["tracking_number"] == "1Z-HO-0001"


def test_the_volume_override_is_not_reachable_by_an_operational_peer():
    """PRD §2.1: "`LoadPlanner` owns the entire load-move lifecycle, buildup creation and
    lifecycle, package onboarding and offboarding, buildup assignment, and both
    manual tier overrides;"

    Design: Corner/rbac/load_planner_cannot_force_a_posture
    """
    night = setup_six_lane_night()
    refused = api.volume_override(night["hub_id"], {"live_planned_package_total": 400000},
                                  H["load_planner_headers"])
    assert refused.status_code == 403
    assert failed_error_id(refused) == "ERR_UNAUTHORIZED"
    assert confirm(api.get_hub(night["hub_id"],
                               H["hub_ops_manager_headers"]))["posture"] == "OPEN"

    admitted = confirm(api.volume_override(night["hub_id"],
                                           {"live_planned_package_total": 400000},
                                           H["hub_ops_manager_headers"]))
    assert admitted["posture"] == "CONGESTED"
    assert admitted["live_planned_package_total"] == 400000


def test_a_lane_round_trips_its_configuration_and_defaults_its_state():
    """PRD §3.3: "A lane carries a `lane_code` unique within the hub, a `lane_kind` of
    `PRIMARY`, `SECONDARY`, `IRREGULAR` or `HAZMAT`, a `commodity_capability`
    naming the one commodity class it is certified to handle, an hourly
    `capacity_weight_grams`, a `certified_until_minutes` instant, and a
    `turnout_start_minutes` / `turnout_end_minutes` pair describing when its face
    is open."

    Design: Corner/endpoints/sort_lane_create_and_read_round_trip
    """
    night = setup_six_lane_night()
    created = confirm(api.create_lane(
        {"hub_id": night["hub_id"], "lane_code": "P-X1", "lane_kind": "PRIMARY",
         "commodity_capability": "GENERAL", "capacity_weight_grams": 60000,
         "certified_until_minutes": 1700, "turnout_start_minutes": 1400,
         "turnout_end_minutes": 1500}, H["sort_supervisor_headers"]), 201)
    read = confirm(api.get_lane(created["id"], H["sort_operator_headers"]))
    assert read["lane_code"] == "P-X1"
    assert read["lane_kind"] == "PRIMARY"
    assert read["commodity_capability"] == "GENERAL"
    assert read["capacity_weight_grams"] == 60000
    assert read["certified_until_minutes"] == 1700
    assert read["turnout_start_minutes"] == 1400
    assert read["turnout_end_minutes"] == 1500
    assert read["status"] == "AVAILABLE"
    assert read["lane_load_grams"] == 0
    assert read["version"] >= 1


def test_the_failure_axis_cycles_between_open_and_disputed():
    """PRD §3.12: "Disputing moves the failure to `DISPUTED` and changes nothing else."

    Design: Corner/endpoints/service_failure_reopen_from_a_disputed_failure_succeeds
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RO-0001",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    failure = confirm(api.create_failure(
        {"hub_id": night["hub_id"], "package_id": package["id"],
         "cause_code": "BAD_ADDRESS", "failure_minutes": 1500},
        H["refund_adjuster_headers"]), 201)
    assert failure["attributed_role"] == "CUSTOMER"
    assert failure["refund_eligible"] is False

    disputed = confirm(api.dispute_failure(failure["id"], H["refund_adjuster_headers"]))
    assert disputed["status"] == "DISPUTED"
    reopened = confirm(api.reopen_failure(failure["id"], H["refund_adjuster_headers"]))
    assert reopened["status"] == "OPEN"
    redisputed = confirm(api.dispute_failure(failure["id"], H["refund_adjuster_headers"]))
    assert redisputed["status"] == "DISPUTED", "the axis is a cycle rather than a pipeline"
    assert_version_incremented(redisputed["version"], failure["version"])


def test_the_triage_read_classifies_the_next_wave_before_any_package_is_tendered():
    """PRD §3.7: "If no shift covers the current minute, the triage is `NO_SHIFT`. If the
    covering shift is `RED`, the triage is `SHED_TO_NEXT_WINDOW`. If it is `SATURATED`, the
    triage is `THROTTLE_INDUCTION`. Otherwise the triage is `ACCEPT`."

    Design: Corner/endpoints/hub_triage_accept_path_when_no_shift_is_saturated
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1414)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-TR-0001",
                             planned_weight_grams=380000, dimension_weight_grams=380000)

    read = confirm(api.get_triage(night["hub_id"], H["hub_ops_manager_headers"]))
    assert read["staffing_posture"] == "GREEN"
    assert read["triage"] == "ACCEPT"
    assert confirm(api.get_shift(night["shift_id"],
                                 H["sort_supervisor_headers"]))["volume_variance_pct"] == pytest.approx(0.0)
    assert get_package(package["id"])["commitment_status"] == "COMMITTED", (
        "the triage is derived on read and no package state changed"
    )


def test_the_refund_summary_exposes_three_separate_computed_figures():
    """PRD §3.11: "For each failure the gross figure is computed as above — the
    weight-times-rate term rounded half up, plus the perishable surcharge where it applies."

    Design: Corner/endpoints/hub_refund_summary_tracks_a_single_provisional_failure
    """
    night = setup_six_lane_night()
    set_clock("2026-09-02T01:00:00Z")
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RS-0001",
                             planned_weight_grams=250050, dimension_weight_grams=250050)
    failure = confirm(api.create_failure(
        {"hub_id": night["hub_id"], "package_id": package["id"], "cause_code": "SORT_MISS",
         "failure_minutes": 1500}, H["refund_adjuster_headers"]), 201)

    summary = confirm(api.get_refund_summary(night["hub_id"], H["refund_adjuster_headers"]))
    assert summary["batch_total_cents"] == 96270

    confirm(api.finalize_failure(failure["id"], H["refund_adjuster_headers"]))
    finalized = confirm(api.get_refund_summary(night["hub_id"], H["refund_adjuster_headers"]))
    assert finalized["batch_total_cents"] == 137528


def test_departure_voids_the_staged_volume_and_emits_one_revenue_prorate_failure():
    """PRD §3.8: "When it succeeds, every staged package has its commitment voided, its
    handling moved to `DIVERTED`, and its final commitment minute cleared, each
    emits exactly one failure with a `REVENUE_PRORATE` cause attributed to the
    customer, in `OPEN` status and not refund-eligible, and the hub's live volume
    recomputes."

    Design: Corner/endpoints/ground_feeder_depart_voids_staged_volume_and_emits_revenue_prorate
    """
    night = setup_six_lane_night()
    # The turnout clause admits a minute at or after departure minus the window and
    # strictly before departure; 1540 sits inside both that clause and the hub's
    # own 1380..1560 sort window.
    set_clock("2026-09-02T01:40:00Z")
    feeder = create_feeder(night["hub_id"], feeder_code="F-1", scheduled_departure_minutes=1560,
                           stage_capacity_grams=100000, window_minutes=20)
    begin_staging(feeder["id"])
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-FV-0001",
                             destination_hub_code="LEX", service_level="GROUND",
                             planned_weight_grams=50000, dimension_weight_grams=50000)
    stage_package(feeder["id"], package["id"])
    begin_feeder_loading(feeder["id"])

    departed = confirm(api.depart_feeder(feeder["id"], H["feeder_coordinator_headers"]))
    assert departed["status"] == "DEPARTED"
    assert departed["staged_weight_grams"] == 0

    read = get_package(package["id"])
    assert read["commitment_status"] == "VOIDED"
    assert read["handling_status"] == "DIVERTED"
    assert read["final_commitment_minutes"] is None

    failures, _ = confirm_list(api.list_failures(H["refund_adjuster_headers"],
                                            {"package_id": package["id"]}))
    assert len(failures) == 1, "exactly one failure exists for the package"
    assert failures[0]["cause_code"] == "REVENUE_PRORATE"
    assert failures[0]["attributed_role"] == "CUSTOMER"
    assert failures[0]["refund_eligible"] is False

    summary = confirm(api.get_refund_summary(night["hub_id"], H["refund_adjuster_headers"]))
    assert summary["batch_total_cents"] == 0, "a CUSTOMER attribution contributes nothing"


def test_departure_is_refused_while_the_hub_is_locked_and_resumes_after_the_clear():
    """PRD §3.8: "Departure additionally requires the hub to be `OPEN` or `CONGESTED`."

    Design: Corner/endpoints/feeder_depart_under_lockdown_returns_invalid_state
    """
    night = setup_six_lane_night()
    set_clock("2026-09-02T00:00:00Z")  # minute 1440
    feeder = create_feeder(night["hub_id"], feeder_code="F-1", scheduled_departure_minutes=1460,
                           stage_capacity_grams=100000, window_minutes=20)
    begin_staging(feeder["id"])
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CD-0001",
                             destination_hub_code="LEX", service_level="GROUND",
                             planned_weight_grams=50000, dimension_weight_grams=50000)
    staged = stage_package(feeder["id"], package["id"])
    assert staged["staged_weight_grams"] == 50000
    begin_feeder_loading(feeder["id"])

    locked = confirm(api.declare_contingency(night["hub_id"], H["weather_officer_headers"]))
    assert locked["posture"] == "LOCKDOWN"

    refusal = api.depart_feeder(feeder["id"], H["feeder_coordinator_headers"])
    assert refusal.status_code == 409
    assert failed_error_id(refusal) == "ERR_INVALID_STATE"
    from test_helpers import get_feeder
    held = get_feeder(feeder["id"])
    assert held["status"] == "LOADING"
    assert held["staged_weight_grams"] == 50000, "the volume was not lost"

    confirm(api.clear_contingency(night["hub_id"], H["hub_ops_manager_headers"]))
    departed = confirm(api.depart_feeder(feeder["id"], H["feeder_coordinator_headers"]))
    assert departed["status"] == "DEPARTED"


def test_every_cascaded_field_is_already_updated_in_the_mutating_response():
    """PRD §2.10: "whenever a mutation changes an input to a derived value, the derived value is
    recomputed in the same operation — the hub's live planning total and posture,
    a lane's load and saturation status, a move's weights and reserve tier, a
    buildup's rated weight and tier, a feeder's staged weight, a shift's variance
    and posture, and a failure's refund figure are all recomputed at the moment
    their inputs move rather than on a later read."
    PRD §2.10: "Second, each such recomputation is an ordinary mutation: it refreshes the
    affected resource's `updated_at` and increments its `version`."

    Design: Corner/consistency_model/all_effects_are_visible_in_the_same_response
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-IM-0001",
                             planned_weight_grams=40000, dimension_weight_grams=40000)

    mutation = confirm(api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"]))
    assert mutation["commitment_status"] == "DOWNGRADED"
    assert mutation["final_commitment_minutes"] == 1920
    assert mutation["commitment_posture"] == "DOWNGRADE_PENDING", (
        "the derived posture is carried in the same response envelope"
    )
    assert mutation["handling_posture"] == "STANDARD"
    assert mutation["sort_status"] == "UNSORTED"

    immediate = confirm(api.get_package(package["id"], H["sort_supervisor_headers"]))
    assert immediate["commitment_posture"] == mutation["commitment_posture"]
    assert immediate["final_commitment_minutes"] == mutation["final_commitment_minutes"], (
        "no field lags and no re-read is needed"
    )


def test_lane_selection_is_never_substituted_by_the_server():
    """PRD §3.3: "the lane's hourly capacity must not be exceeded — if the lane's load plus
    this package's rated weight would exceed the lane's `capacity_weight_grams`,
    the sort is refused with `ERR_LANE_CAPACITY_EXCEEDED`."
    PRD §3.3: "requires the target lane — named in the request by its `lane_id` — to exist
    on this hub, to be `AVAILABLE`, to be certified for this package's commodity
    class, and to be certified at the current instant — strict certification means
    the current minute is strictly before the lane's `certified_until_minutes`,
    and a lapsed certificate is refused with `ERR_LANE_CERTIFICATION_LAPSED`."

    Design: Corner/cross_cutting_complexity_layers/selector_policy_sort_lane_capability_filter
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1414)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-SL-0001",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    induct(package["id"])

    refusal = api.primary_sort(package["id"], {"lane_id": night["lane_hz1_id"]},
                               H["sort_operator_headers"])
    assert refusal.status_code == 409
    assert failed_error_id(refusal) == "ERR_LANE_NOT_AVAILABLE"
    assert get_package(package["id"])["assigned_lane_id"] is None, (
        "no lane was silently substituted"
    )

    admitted = primary_sort(package["id"], night["lane_p1_id"])
    assert admitted["assigned_lane_id"] == night["lane_p1_id"]
    assert get_lane(night["lane_p1_id"])["lane_load_grams"] == 20000