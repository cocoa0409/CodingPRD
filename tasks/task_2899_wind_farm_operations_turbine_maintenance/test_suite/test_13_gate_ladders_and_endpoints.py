"""Scheduling gates read at their exact limits, and the endpoints that link two rows at once."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CREW_CERTIFICATION_MISSING,
    ERR_CREW_FARM_MISMATCH,
    ERR_INVALID_STATE,
    ERR_RESET_NOT_PERMITTED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant_equals,
    assert_one_dp,
    assert_total_count,
    assert_turbine_dimensions,
    assert_two_dp,
    assert_version_unchanged,
)
from test_helpers.constants import (
    AVAILABILITY_FAULTED,
    CERT_GWO_BASIC,
    AVAILABILITY_ONLINE,
    CRANE_DEMOBILIZED,
    CRANE_MOBILIZED,
    CRANE_REQUESTED,
    CREW_AVAILABLE,
    CREW_ON_SHIFT,
    DISPOSITION_REMOTE_RESET,
    PATH_CRANE_LIFT,
    REPLACEMENT_CRANE_RESERVED,
    REPLACEMENT_EXECUTED,
    REPLACEMENT_PLANNED,
    SEVERITY_LOCKOUT,
    SEVERITY_RESETTABLE,
    TRIAGE_DISPATCH_REQUIRED,
    TRIAGE_DISPATCHED,
    TRIAGE_RAISED,
    TRIAGE_RESET_PENDING,
    WINDOW_CONFIRMED,
    WO_DRAFT,
    WO_SCHEDULED,
    WO_SUBMITTED,
    WORK_TYPE_FAULT_DISPATCH,
)
from test_helpers.factories import scada_payload, schedule_payload, work_order_payload
from test_helpers.fixtures import (
    amend_fault_rule,
    base_site,
    execute_replacement,
    raise_fault,
    read_crane,
    read_crew,
    read_fault_event,
    read_replacement,
    read_turbine,
    read_window,
    read_work_order,
    reserve_crane,
    set_clock,
    setup_crane_lifecycle_site,
    setup_dispatch_required_lockout,
    setup_exact_limit_schedule,
    setup_pinning_pair_site,
    setup_two_farm_crew_pair,
    triage,
)
from test_helpers.test_users import (
    make_control_room_headers,
    make_engineer_headers,
    make_planner_headers,
)


def test_two_scheduling_refusals_on_one_order_name_two_different_conditions(api):
    """The local crew fails on certifications; the crew from the other site fails on ownership.

    Each candidate violates exactly one condition, so the reported code identifies which
    gate closed, and neither refusal may leave the window carrying an occupant.

    PRD §3.4: "The crew's `certifications` array must contain the order's
    `required_certification`, failing which the request is refused with
    `ERR_CREW_CERTIFICATION_MISSING`."
    PRD §3.4: "The crew and the window must both belong to the same farm as the order's
    turbine, and a crew rostered elsewhere is refused with `ERR_CREW_FARM_MISMATCH`."
    PRD §3.4: "A successful schedule stores `crew_id`, `weather_window_id`,
    `planned_start_utc` and `planned_end_utc` on the order, sets the crew's `status` to
    `ON_SHIFT`, and increments the window's `active_work_order_count` by 1 while **leaving
    the window in `CONFIRMED`** — which is precisely what allows a second crew to be
    scheduled into the same window."
    PRD §2.12: "A rejected request writes nothing at all — no counter moves, no `version`
    advances, no partial cascade survives."

    Design: Corner/validations/schedule_rejects_an_uncertified_crew_and_a_foreign_farm_crew_with_distinct_codes
    """
    site = setup_two_farm_crew_pair(api)
    order_id = site["order"]["id"]
    window_id = site["window"]["id"]
    before_order = read_work_order(api, order_id)
    before_window = read_window(api, window_id)

    validate_error(
        api.schedule_work_order(
            order_id,
            schedule_payload(
                site["crew_local"]["id"],
                window_id,
                "2026-08-10T08:00:00Z",
                "2026-08-10T16:00:00Z",
            ),
            make_planner_headers(),
        ),
        ERR_CREW_CERTIFICATION_MISSING,
        expected_status=422,
    )

    validate_error(
        api.schedule_work_order(
            order_id,
            schedule_payload(
                site["crew_foreign"]["id"],
                window_id,
                "2026-08-10T08:00:00Z",
                "2026-08-10T16:00:00Z",
            ),
            make_planner_headers(),
        ),
        ERR_CREW_FARM_MISMATCH,
        expected_status=422,
    )

    order = read_work_order(api, order_id)
    assert order["state"] == WO_SUBMITTED
    assert order["crew_id"] is None
    assert order["weather_window_id"] is None
    assert order["planned_start_utc"] is None
    assert order["planned_end_utc"] is None
    assert_version_unchanged(before_order, order)

    window = read_window(api, window_id)
    assert window["state"] == WINDOW_CONFIRMED
    assert window["active_work_order_count"] == 0
    assert_version_unchanged(before_window, window)

    assert read_crew(api, site["crew_local"]["id"])["status"] == CREW_AVAILABLE
    assert read_crew(api, site["crew_foreign"]["id"])["status"] == CREW_AVAILABLE


def test_a_schedule_that_lands_exactly_on_three_limits_is_accepted(api):
    """Wind ceiling, interval containment and daily capacity are each met by equality.

    PRD §3.4: "The crew's `max_work_wind_speed_ms` must be at least as large as the
    window's `forecast_wind_speed_ms` — equality is acceptable — and a crew whose limit
    falls below the forecast is refused with `ERR_CREW_WIND_LIMIT_EXCEEDED`."
    PRD §3.4: "The proposed interval must be **contained** inside the window's interval,
    meaning `planned_start_utc` is at or after the window's `start_utc` and
    `planned_end_utc` is at or before its `end_utc`; anything protruding is refused with
    `ERR_WORK_ORDER_OUTSIDE_WINDOW`."
    PRD §3.4: "Landing exactly on capacity is permitted."
    PRD §3.4: "It is reachable only from `SUBMITTED`, moving the order `SUBMITTED →
    SCHEDULED`."
    PRD §3.4: "A successful schedule stores `crew_id`, `weather_window_id`,
    `planned_start_utc` and `planned_end_utc` on the order, sets the crew's `status` to
    `ON_SHIFT`, and increments the window's `active_work_order_count` by 1 while **leaving
    the window in `CONFIRMED`** — which is precisely what allows a second crew to be
    scheduled into the same window."

    Design: Corner/validations/schedule_succeeds_when_every_gate_is_satisfied_exactly_at_its_limit
    """
    site = setup_exact_limit_schedule(api)
    crew = site["crew"]
    window = site["window"]
    assert_one_dp(crew["max_work_wind_speed_ms"], window["forecast_wind_speed_ms"], "wind ceiling")

    scheduled = validate_success(
        api.schedule_work_order(
            site["order"]["id"],
            schedule_payload(
                crew["id"], window["id"], "2026-08-10T06:00:00Z", "2026-08-10T18:00:00Z"
            ),
            make_planner_headers(),
        )
    )
    assert scheduled["state"] == WO_SCHEDULED
    assert scheduled["crew_id"] == crew["id"]
    assert scheduled["weather_window_id"] == window["id"]
    assert_instant_equals(
        scheduled["planned_start_utc"], "2026-08-10T06:00:00Z", "planned_start_utc"
    )
    assert_instant_equals(scheduled["planned_end_utc"], "2026-08-10T18:00:00Z", "planned_end_utc")
    assert_two_dp(scheduled["estimated_hours"], 12, "estimated_hours")

    assert read_crew(api, crew["id"])["status"] == CREW_ON_SHIFT

    after_window = read_window(api, window["id"])
    assert after_window["state"] == WINDOW_CONFIRMED
    assert after_window["active_work_order_count"] == 1


def test_amending_a_rule_leaves_the_older_event_judged_by_its_own_snapshot(api):
    """One fault code, two live events, two different verdicts on the same disposition.

    PRD §3.2: "A rule may later be amended, and the amendable subset is exactly
    `max_remote_resets_per_24h`, `requires_dispatch` and `contractual_exclusion` — all
    three optional on the amendment request."
    PRD §3.2: "Amending a rule increments that rule's own `version` by 1 and changes nothing
    on any fault event already raised."
    PRD §3.2: "The submitted code must match a registered rule; the resolved rule is
    recorded as the event's `fault_code_rule_id`, and its parameters are **pinned** onto the
    event at that moment — `severity_class_pinned`, `max_remote_resets_pinned`,
    `requires_dispatch_pinned` and `contractual_exclusion_pinned` copy the rule's severity
    class, reset quota, dispatch requirement and exclusion flag respectively, and
    `fault_code_rule_version_pinned` records the rule's `version` as observed at raise time."
    PRD §3.2: "A later amendment of the rule never rewrites any pinned value; the event is
    judged for the rest of its life by the snapshot it was born with."
    PRD §3.2: "A `disposition` of `REMOTE_RESET` moves the event `RAISED → RESET_PENDING`;
    it is permitted only when the event's `severity_class_pinned` is `RESETTABLE` and its
    `requires_dispatch_pinned` is false, and any other combination — `ADVISORY`, `LOCKOUT`,
    or a code the rule marks dispatch-only — is refused with `ERR_RESET_NOT_PERMITTED`."

    Design: Corner/endpoints/patching_a_fault_code_rule_binds_only_faults_raised_afterwards
    """
    site = setup_pinning_pair_site(api)
    rule = site["rule"]
    older = site["event"]

    amended = amend_fault_rule(
        api,
        rule["id"],
        max_remote_resets_per_24h=5,
        requires_dispatch=True,
        contractual_exclusion=True,
    )
    assert amended["max_remote_resets_per_24h"] == 5
    assert amended["requires_dispatch"] is True
    assert amended["contractual_exclusion"] is True
    assert amended["version"] == rule["version"] + 1
    assert amended["fault_code"] == "F-3001"
    assert amended["severity_class"] == SEVERITY_RESETTABLE

    still_pinned = read_fault_event(api, older["id"])
    assert still_pinned["max_remote_resets_pinned"] == 2
    assert still_pinned["requires_dispatch_pinned"] is False
    assert still_pinned["contractual_exclusion_pinned"] is False
    assert still_pinned["fault_code_rule_version_pinned"] == rule["version"]

    set_clock(api, "2026-08-01T02:00:00Z")
    newer = raise_fault(api, site["turbine_two"]["id"], "F-3001", "2026-08-01T02:00:00Z")
    assert newer["max_remote_resets_pinned"] == 5
    assert newer["requires_dispatch_pinned"] is True
    assert newer["contractual_exclusion_pinned"] is True
    assert newer["fault_code_rule_version_pinned"] == amended["version"]

    older_triaged = triage(api, older["id"], DISPOSITION_REMOTE_RESET)
    assert older_triaged["triage_state"] == TRIAGE_RESET_PENDING

    validate_error(
        api.triage_fault_event(newer["id"], DISPOSITION_REMOTE_RESET, make_control_room_headers()),
        ERR_RESET_NOT_PERMITTED,
        expected_status=422,
    )
    assert read_fault_event(api, newer["id"])["triage_state"] == TRIAGE_RAISED


def test_raising_a_dispatch_order_links_the_event_and_advances_it_in_the_same_request(api):
    """The create writes a link on the new order and a transition on the event it names.

    PRD §3.3: "`fault_event_id` is **required** when `work_type` is `FAULT_DISPATCH` and
    must be omitted for every other work type; the named event must be sitting in
    `DISPATCH_REQUIRED`, and raising the order moves it `DISPATCH_REQUIRED → DISPATCHED`
    while changing no other field on the event."
    PRD §3.3: "A new order starts in `state` `DRAFT` with `revision_round` at 0,
    `priority_score` at 0 and `labor_cost_cents` at 0, and with `crew_id`,
    `weather_window_id`, `planned_start_utc`, `planned_end_utc`, `actual_hours` and
    `submitted_by_user_id` all null."
    PRD §3.5: "The start writes the availability dimension according to work type, and each
    branch is a distinct declared transition: a `FAULT_DISPATCH` order drives `FAULTED →
    DOWN_DISPATCH`, a `SCHEDULED_SERVICE` or `BLADE_REPAIR` order drives `ONLINE →
    DOWN_SERVICE`, and a `MAJOR_COMPONENT` order drives `ONLINE → DOWN_MAJOR`."
    PRD §4: "List work orders filtered by any of their foreign keys or by state."

    Design: Corner/endpoints/creating_a_fault_dispatch_order_links_the_event_and_advances_it_to_dispatched
    """
    site = setup_dispatch_required_lockout(api)
    turbine_id = site["turbine"]["id"]
    event_id = site["event"]["id"]
    assert site["event"]["triage_state"] == TRIAGE_DISPATCH_REQUIRED

    order = validate_success(
        api.create_work_order(
            work_order_payload(
                turbine_id,
                work_type=WORK_TYPE_FAULT_DISPATCH,
                required_certification=CERT_GWO_BASIC,
                estimated_hours=6,
                fault_event_id=event_id,
            ),
            make_engineer_headers(),
        ),
        expected_status=201,
    )
    assert order["state"] == WO_DRAFT
    assert order["work_type"] == WORK_TYPE_FAULT_DISPATCH
    assert order["fault_event_id"] == event_id
    assert order["crew_id"] is None
    assert order["submitted_by_user_id"] is None

    event = read_fault_event(api, event_id)
    assert event["triage_state"] == TRIAGE_DISPATCHED
    assert event["cleared_at"] is None
    assert event["reset_attempt_count"] == 0
    assert event["severity_class_pinned"] == SEVERITY_LOCKOUT

    turbine = read_turbine(api, turbine_id)
    assert_turbine_dimensions(turbine, AVAILABILITY_FAULTED)
    assert turbine["active_fault_code"] == "F-4002"

    linked = assert_total_count(
        api.list_work_orders(make_engineer_headers(), fault_event_id=event_id), 1
    )
    assert linked[0]["id"] == order["id"]


def test_three_telemetry_posts_accumulate_and_the_third_reply_carries_the_service_verdict(api):
    """Telemetry is additive, and the service figures are re-derived inside the same reply.

    Four thousand two hundred hours has reached the four-thousand-hour interval but has not
    passed the two-hundred-and-fifty-hour tolerance, so exactly one of the two flags turns.

    PRD §3.2: "The payload is purely additive: `operating_hours_delta` is added to the
    turbine's `operating_hours`, `actual_energy_kwh` is added to
    `period_actual_energy_kwh`, and `potential_energy_kwh` is added to
    `period_potential_energy_kwh`."
    PRD §3.2: "Telemetry is the only path by which `operating_hours` advances."
    PRD §3.2: "`service_due_operating_hours` is the turbine's `last_service_operating_hours`
    plus the model's `service_interval_hours`."
    PRD §3.2: "`service_due_flag` is true when the turbine's `operating_hours` has reached or
    passed `service_due_operating_hours`, using an at-or-above comparison."
    PRD §3.2: "`service_interval_breached` is true only when `operating_hours` has passed
    `service_due_operating_hours` plus the model's `service_interval_tolerance_hours`
    **strictly** — landing exactly on the tolerated boundary is not yet a breach."

    Design: Corner/endpoints/scada_sync_returns_the_turbine_with_every_derived_field_recomputed
    """
    site = base_site(api)
    turbine_id = site["turbine"]["id"]

    first = validate_success(
        api.scada_sync(
            turbine_id, scada_payload(1500.0, 2800000.0, 3000000.0), make_control_room_headers()
        )
    )
    assert_one_dp(first["operating_hours"], 1500.0, "operating_hours")
    assert first["service_due_flag"] is False
    assert_one_dp(first["service_due_operating_hours"], 4000, "service_due_operating_hours")

    second = validate_success(
        api.scada_sync(
            turbine_id, scada_payload(1500.0, 2900000.0, 3000000.0), make_control_room_headers()
        )
    )
    assert_one_dp(second["operating_hours"], 3000.0, "operating_hours")
    assert_two_dp(second["period_actual_energy_kwh"], 5700000.0, "period_actual_energy_kwh")
    assert_two_dp(second["period_potential_energy_kwh"], 6000000.0, "period_potential_energy_kwh")
    assert second["service_due_flag"] is False

    third = validate_success(
        api.scada_sync(
            turbine_id, scada_payload(1200.0, 2000000.0, 2400000.0), make_control_room_headers()
        )
    )
    assert_one_dp(third["operating_hours"], 4200.0, "operating_hours")
    assert_two_dp(third["period_actual_energy_kwh"], 7700000.0, "period_actual_energy_kwh")
    assert_two_dp(third["period_potential_energy_kwh"], 8400000.0, "period_potential_energy_kwh")
    assert third["service_due_flag"] is True
    assert third["service_interval_breached"] is False
    assert_one_dp(third["last_service_operating_hours"], 0, "last_service_operating_hours")
    assert_turbine_dimensions(third, AVAILABILITY_ONLINE)

    assert read_turbine(api, turbine_id)["service_due_flag"] is True


def test_a_crane_can_only_leave_site_once_a_reservation_has_brought_it_on_and_been_executed(api):
    """Demobilization is refused from the requested state and permitted from the mobilized one.

    Nothing on the crane itself mobilizes it: the reservation cascade does, and the crane may
    not stand down while a replacement still holds it.

    PRD §3.7: "A mobilization begins in `state` `REQUESTED` with `reserved_replacement_count`
    at 0 and every cost figure — `lift_days`, `standby_days`, `billable_days`,
    `subtotal_cents`, `volume_credit_cents` and `total_crane_cost_cents` — at 0."
    PRD §2.8: "The target row must be in a state from which the requested transition is
    declared."
    PRD §2.8: "Every other action endpoint, covering crane mobilizations, component
    replacements, weather windows, curtailment orders, service agreements, blade findings
    and landowner settlements, yields `ERR_INVALID_STATE`."
    PRD §3.7: "A successful reservation sets `execution_path` to `CRANE_LIFT`, stores the
    `crane_mobilization_id`, moves the mobilization `REQUESTED → MOBILIZED` if it was still
    `REQUESTED`, increments its `reserved_replacement_count` by 1, and reprices the whole
    mobilization."
    PRD §3.7: "Demobilizing a `MOBILIZED` crane drives it `MOBILIZED → DEMOBILIZED` and frees
    the slot for a new buffered mobilization, but it is permitted only once every replacement
    holding that crane is in `EXECUTED`, `CLOSED` or `CANCELLED`."
    PRD §3.7: "Demobilization changes no money at all: `total_crane_cost_cents` and every
    per-replacement `allocated_crane_cost_cents` are left exactly as they stand, because the
    crane cost was already charged at execution time."

    Design: Corner/endpoints/crane_demobilize_is_rejected_until_a_reservation_mobilizes_it
    """
    site = setup_crane_lifecycle_site(api)
    crane_id = site["crane"]["id"]
    replacement_id = site["replacement"]["id"]
    assert site["crane"]["state"] == CRANE_REQUESTED
    assert site["crane"]["reserved_replacement_count"] == 0
    assert_cents(site["crane"]["total_crane_cost_cents"], 0, "total_crane_cost_cents")
    assert site["replacement"]["state"] == REPLACEMENT_PLANNED

    before = read_crane(api, crane_id)
    validate_error(
        api.demobilize_crane(crane_id, make_planner_headers()),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    unchanged = read_crane(api, crane_id)
    assert unchanged["state"] == CRANE_REQUESTED
    assert unchanged["reserved_replacement_count"] == 0
    assert_version_unchanged(before, unchanged)

    reserved = reserve_crane(api, replacement_id, crane_id)
    assert reserved["state"] == REPLACEMENT_CRANE_RESERVED
    assert reserved["execution_path"] == PATH_CRANE_LIFT
    assert reserved["crane_mobilization_id"] == crane_id

    mobilized = read_crane(api, crane_id)
    assert mobilized["state"] == CRANE_MOBILIZED
    assert mobilized["reserved_replacement_count"] == 1

    executed = execute_replacement(api, replacement_id)
    assert executed["state"] == REPLACEMENT_EXECUTED

    priced = read_crane(api, crane_id)
    demobilized = validate_success(api.demobilize_crane(crane_id, make_planner_headers()))
    assert demobilized["state"] == CRANE_DEMOBILIZED
    assert_cents(
        demobilized["total_crane_cost_cents"],
        priced["total_crane_cost_cents"],
        "total_crane_cost_cents",
    )

    still_executed = read_replacement(api, replacement_id)
    assert still_executed["state"] == REPLACEMENT_EXECUTED
    assert_cents(
        still_executed["allocated_crane_cost_cents"],
        executed["allocated_crane_cost_cents"],
        "allocated_crane_cost_cents",
    )
