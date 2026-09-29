"""The declared state machines: openings, forward walks, terminals and refused triggers."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_FAULT_EVENT_INVALID_STATE,
    ERR_INVALID_STATE,
    ERR_RESET_NOT_PERMITTED,
    ERR_RESET_QUOTA_EXHAUSTED,
    ERR_TURBINE_DECOMMISSIONED,
    ERR_WORK_ORDER_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_total_count,
    assert_turbine_dimensions,
    assert_two_dp,
    assert_version_unchanged,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AVAILABILITY_DECOMMISSIONED,
    AVAILABILITY_DOWN_MAJOR,
    AVAILABILITY_FAULTED,
    AVAILABILITY_ONLINE,
    BLADE_OPEN,
    BLADE_WAIVED,
    CREW_AVAILABLE,
    CREW_ON_SHIFT,
    CURTAILMENT_PENDING,
    CURTAILMENT_REASON_NOISE,
    CURTAILMENT_RELEASED,
    CURTAILMENT_UNCONSTRAINED,
    DAMAGE_LEADING_EDGE_EROSION,
    DISPOSITION_DISPATCH,
    DISPOSITION_REMOTE_RESET,
    INSPECTION_DRONE,
    RESET_OUTCOME_FAILED,
    SETTLEMENT_DRAFT,
    TRIAGE_DISPATCH_REQUIRED,
    TRIAGE_RAISED,
    TRIAGE_RESET_PENDING,
    WINDOW_CONFIRMED,
    WINDOW_CONSUMED,
    WINDOW_EXPIRED,
    WINDOW_FORECAST,
    WO_DRAFT,
    WO_IN_PROGRESS,
    WO_COMPLETED,
    WO_SCHEDULED,
    WO_SUBMITTED,
)
from test_helpers.factories import (
    blade_damage_payload,
    curtailment_payload,
    fault_event_payload,
    schedule_payload,
    service_agreement_payload,
    weather_window_payload,
    work_order_payload,
)
from test_helpers.fixtures import (
    read_blade_damage,
    read_crew,
    read_curtailment,
    read_farm,
    read_fault_event,
    read_settlement,
    read_turbine,
    read_window,
    read_work_order,
    setup_decommissioned_turbine_with_draft_order,
    setup_faultable_site,
    setup_released_curtailment_and_waived_damage,
    setup_replay_targets,
    setup_reset_track_trio,
    setup_shared_window_two_orders,
    setup_three_machine_snapshot,
    setup_work_order_walk,
    turbine_version,
)
from test_helpers.test_users import (
    ENGINEER_2_USER_ID,
    PLANNER_USER_ID,
    make_commercial_headers,
    make_control_room_headers,
    make_crew_lead_headers,
    make_engineer_headers,
    make_planner_headers,
)


def test_one_order_walks_the_whole_declared_forward_path_one_hop_per_request(api):
    """Submit, schedule, start and complete, with the crew, window and turbine riding along.

    The contract states: "Submission moves an order `DRAFT → SUBMITTED`, and it is also
    the way an order re-enters planning from `REVISION_REQUESTED → SUBMITTED`."  It
    continues: "Either way the turbine must not be `DECOMMISSIONED`,
    `submitted_by_user_id` is set to the acting `X-User-ID` — overwriting whatever it held
    on a previous submission — and the order's `priority_score` is computed."  Of the next
    hop it states: "A successful schedule stores `crew_id`, `weather_window_id`,
    `planned_start_utc` and `planned_end_utc` on the order, sets the crew's `status` to
    `ON_SHIFT`, and increments the window's `active_work_order_count` by 1 while
    **leaving the window in `CONFIRMED`** — which is precisely what allows a second crew to
    be scheduled into the same window."  Of the start it states: "The start writes the
    availability dimension according to work type, and each branch is a distinct declared
    transition: a `FAULT_DISPATCH` order drives `FAULTED → DOWN_DISPATCH`, a
    `SCHEDULED_SERVICE` or `BLADE_REPAIR` order drives `ONLINE → DOWN_SERVICE`, and a
    `MAJOR_COMPONENT` order drives `ONLINE → DOWN_MAJOR`."  And: "If this is the first
    order to start inside the named window, that window moves `CONFIRMED → CONSUMED`,
    which closes it to new schedules; the window's `active_work_order_count` is **not**
    changed by starting."  Of the completion it states: "The order moves `IN_PROGRESS →
    COMPLETED` and its `labor_cost_cents` is set to `actual_hours` multiplied by the
    assigned crew's `hourly_rate_cents`, rounded half up to a whole cent."  And: "The
    turbine's availability dimension returns to `ONLINE` from whichever down state it held
    — `DOWN_DISPATCH → ONLINE`, `DOWN_SERVICE → ONLINE` or `DOWN_MAJOR → ONLINE` — with
    the curtailment dimension untouched."  Finally: "Alongside those hops, completion posts
    the labour cost to the site ledger, adding `labor_cost_cents` both to the farm's
    `maintenance_spend_cents` and to its `opex_accrued_cents`."  And: "It decrements the
    named window's `active_work_order_count` by 1, and when that count reaches 0 the window
    moves `CONSUMED → EXPIRED`."  And: "It returns the crew's `status` to `AVAILABLE`,
    provided the crew holds no other order in `SCHEDULED` or `IN_PROGRESS`."

    Design: Corner/state_machines/work_order_walks_draft_submitted_scheduled_in_progress_completed_end_to_end
    """
    site = setup_work_order_walk(api)
    order_id = site["order"]["id"]
    crew_id = site["crew"]["id"]
    window_id = site["window"]["id"]
    turbine_id = site["turbine"]["id"]

    submitted = validate_success(api.submit_work_order(order_id, make_planner_headers()))
    assert submitted["state"] == WO_SUBMITTED
    assert submitted["submitted_by_user_id"] == PLANNER_USER_ID
    assert submitted["priority_score"] is not None

    scheduled = validate_success(
        api.schedule_work_order(
            order_id,
            schedule_payload(
                crew_id, window_id, "2026-08-10T08:00:00Z", "2026-08-10T16:00:00Z"
            ),
            make_planner_headers(),
        )
    )
    assert scheduled["state"] == WO_SCHEDULED
    assert scheduled["crew_id"] == crew_id
    assert scheduled["weather_window_id"] == window_id
    after_schedule = read_window(api, window_id)
    assert after_schedule["active_work_order_count"] == 1
    assert after_schedule["state"] == WINDOW_CONFIRMED

    started = validate_success(api.start_work_order(order_id, make_crew_lead_headers(crew_id)))
    assert started["state"] == WO_IN_PROGRESS
    assert read_crew(api, crew_id)["status"] == CREW_ON_SHIFT
    after_start = read_window(api, window_id)
    assert after_start["state"] == WINDOW_CONSUMED
    assert after_start["active_work_order_count"] == 1
    assert_turbine_dimensions(
        read_turbine(api, turbine_id),
        availability_state=AVAILABILITY_DOWN_MAJOR,
        curtailment_state=CURTAILMENT_UNCONSTRAINED,
    )

    completed = validate_success(
        api.complete_work_order(order_id, 9, make_crew_lead_headers(crew_id))
    )
    assert completed["state"] == WO_COMPLETED
    assert_cents(completed["labor_cost_cents"], 810000, "labour cost from nine actual hours")
    assert_turbine_dimensions(
        read_turbine(api, turbine_id),
        availability_state=AVAILABILITY_ONLINE,
        curtailment_state=CURTAILMENT_UNCONSTRAINED,
    )
    assert read_crew(api, crew_id)["status"] == CREW_AVAILABLE
    farm = read_farm(api, site["farm"]["id"])
    assert_cents(farm["maintenance_spend_cents"], 810000, "maintenance spend")
    assert_cents(farm["opex_accrued_cents"], 810000, "opex accrued")
    after_complete = read_window(api, window_id)
    assert after_complete["active_work_order_count"] == 0
    assert after_complete["state"] == WINDOW_EXPIRED


def test_a_retired_turbine_locks_out_its_child_creations_and_the_submit_gate(api):
    """Retirement is terminal, and it refuses two child creations and one onward transition.

    The contract states: "Retiring a turbine is a `SiteAdmin` action that carries a
    `decommission_reason` and drives the availability dimension `ONLINE →
    DECOMMISSIONED`."  Of the fault path it states: "It is refused unless the turbine's
    `availability_state` is `ONLINE`, and refused with `ERR_TURBINE_DECOMMISSIONED` for a
    retired turbine."  Of the inspection path it states: "A finding may not be recorded
    against a retired turbine, and the attempt is refused with
    `ERR_TURBINE_DECOMMISSIONED`."  Of the onward transition it states: "Either way the
    turbine must not be `DECOMMISSIONED`, `submitted_by_user_id` is set to the acting
    `X-User-ID` — overwriting whatever it held on a previous submission — and the order's
    `priority_score` is computed."  The catalogue of refusals states: "**Turbine
    decommissioning**, yielding `ERR_TURBINE_DECOMMISSIONED`."  Of the order's opening it
    states: "A new order starts in `state` `DRAFT` with `revision_round` at 0,
    `priority_score` at 0 and `labor_cost_cents` at 0, and with `crew_id`,
    `weather_window_id`, `planned_start_utc`, `planned_end_utc`, `actual_hours` and
    `submitted_by_user_id` all null."

    Design: Corner/state_machines/fault_raise_and_work_order_submit_are_rejected_on_a_decommissioned_turbine
    """
    site = setup_decommissioned_turbine_with_draft_order(api)
    turbine_id = site["turbine"]["id"]
    order_id = site["order"]["id"]
    assert site["turbine"]["availability_state"] == AVAILABILITY_DECOMMISSIONED

    validate_error(
        api.raise_fault_event(
            turbine_id,
            fault_event_payload("F-3001", "2026-08-01T01:00:00Z"),
            make_control_room_headers(),
        ),
        ERR_TURBINE_DECOMMISSIONED,
        expected_status=409,
    )
    assert_total_count(
        api.list_fault_events(make_control_room_headers(), turbine_id=turbine_id), 0
    )

    validate_error(
        api.record_blade_damage(
            turbine_id,
            blade_damage_payload(
                inspection_method=INSPECTION_DRONE,
                blade_position="A",
                inspected_at="2026-08-01T02:00:00Z",
                damage_category=2,
                damage_type=DAMAGE_LEADING_EDGE_EROSION,
                chord_position_pct=30.0,
                damage_length_mm=400,
                exposed_area_cm2=90.0,
            ),
            make_engineer_headers(),
        ),
        ERR_TURBINE_DECOMMISSIONED,
        expected_status=409,
    )

    validate_error(
        api.submit_work_order(order_id, make_planner_headers()),
        ERR_TURBINE_DECOMMISSIONED,
        expected_status=409,
    )
    order = read_work_order(api, order_id)
    assert order["state"] == WO_DRAFT
    assert order["submitted_by_user_id"] is None
    assert_version_unchanged(site["order"], order)


def test_three_machines_report_three_distinct_codes_for_the_same_shape_of_mistake(api):
    """One undeclared trigger per machine, and each family answers with its own code.

    The contract states: "The target row must be in a state from which the requested
    transition is declared."  It continues: "Work-order transitions — submit,
    request-revision, schedule, start, complete and cancel — yield
    `ERR_WORK_ORDER_INVALID_STATE`."  And: "Fault-event transitions — triage, remote-reset
    and close — yield `ERR_FAULT_EVENT_INVALID_STATE`."  And: "Every other action endpoint,
    covering crane mobilizations, component replacements, weather windows, curtailment
    orders, service agreements, blade findings and landowner settlements, yields
    `ERR_INVALID_STATE`."  Of the three transitions attempted here it states: "Starting an
    order moves it `SCHEDULED → IN_PROGRESS` and may be done by the assigned `CrewLead` or
    by a `ReliabilityEngineer`."  And: "Closure is a `ReliabilityEngineer` decision that
    admits the event's downtime into the availability accounts, moving it `CLEARED →
    CLOSED`."  And: "Voiding an approved settlement drives it `APPROVED → VOID`, stores the
    `void_reason`, and is a pure compensating action: it subtracts `payment_cents` from
    `landowner_payable_cents`, `road_levy_cents` plus `road_damage_assessment_cents` from
    `road_maintenance_reserve_cents`, `community_levy_cents` from
    `community_fund_balance_cents`, and the same total from `opex_accrued_cents`."

    Design: Corner/state_machines/each_machine_rejects_an_undeclared_trigger_from_its_current_state
    """
    site = setup_three_machine_snapshot(api)
    order_id = site["order"]["id"]
    event_id = site["event"]["id"]
    settlement_id = site["settlement"]["id"]

    validate_error(
        api.start_work_order(order_id, make_engineer_headers()),
        ERR_WORK_ORDER_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.close_fault_event(event_id, make_engineer_headers()),
        ERR_FAULT_EVENT_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.void_landowner_settlement(
            settlement_id, "keyed against the wrong parcel", make_commercial_headers()
        ),
        ERR_INVALID_STATE,
        expected_status=409,
    )

    order = read_work_order(api, order_id)
    assert order["state"] == WO_SUBMITTED
    assert_version_unchanged(site["order"], order)
    event = read_fault_event(api, event_id)
    assert event["triage_state"] == TRIAGE_RAISED
    assert_version_unchanged(site["event"], event)
    settlement = read_settlement(api, settlement_id)
    assert settlement["state"] == SETTLEMENT_DRAFT
    assert settlement["void_reason"] is None
    assert_version_unchanged(site["settlement"], settlement)


def test_six_freshly_created_rows_each_sit_in_their_own_declared_opening_state(api):
    """Six machines seeded in one request sequence, none of them skipping its opening state.

    The contract states: "Raising a fault sets the event's `triage_state` to `RAISED` and
    its `reset_attempt_count` to 0, sets the turbine's `active_fault_code` to the submitted
    code, and drives the availability dimension `ONLINE → FAULTED` while leaving the
    curtailment dimension untouched."  It adds: "The event's `cleared_at`, `downtime_hours`
    and `lost_energy_kwh` all start null."  Of the work order it states: "A new order starts
    in `state` `DRAFT` with `revision_round` at 0, `priority_score` at 0 and
    `labor_cost_cents` at 0, and with `crew_id`, `weather_window_id`, `planned_start_utc`,
    `planned_end_utc`, `actual_hours` and `submitted_by_user_id` all null."  Of the
    curtailment order it states: "Issuance requires `expected_turbine_version` per §2.7,
    creates the order in `state` `PENDING` with `curtailed_hours` and `lost_energy_kwh` at
    0, and increments the turbine's `version` by 1."  Of the window it states: "A new window
    is created in `state` `FORECAST` with `active_work_order_count` at 0."  Of the blade
    finding it states: "Recording a finding sets its `state` to `OPEN`, stamps
    `recorded_by_user_id` with the acting `X-User-ID`, and leaves `waiver_rationale` null."
    Of the agreement it states: "A new agreement is created in `state` `ACTIVE` with
    `at_risk_flag` false and with `projected_shortfall_pct`,
    `time_based_availability_pct`, `energy_based_availability_pct` and `assessed_lda_cents`
    all at 0."  And because a pending order is not an active one: "Activation increments the
    turbine's `active_curtailment_count` by 1 and sets its `effective_power_limit_kw` to the
    smallest `power_limit_kw` across all of that turbine's active orders — the most
    restrictive instruction wins."

    Design: Corner/state_machines/every_machine_opens_in_its_declared_initial_state
    """
    site = setup_faultable_site(api)
    turbine_id = site["turbine"]["id"]
    farm_id = site["farm"]["id"]

    event = validate_success(
        api.raise_fault_event(
            turbine_id,
            fault_event_payload("F-3001", "2026-08-01T00:00:00Z"),
            make_control_room_headers(),
        ),
        expected_status=201,
    )
    assert event["triage_state"] == TRIAGE_RAISED
    assert event["reset_attempt_count"] == 0
    assert event["cleared_at"] is None
    assert event["downtime_hours"] is None
    assert event["lost_energy_kwh"] is None

    order = validate_success(
        api.create_work_order(work_order_payload(turbine_id), make_planner_headers()),
        expected_status=201,
    )
    assert order["state"] == WO_DRAFT
    assert order["revision_round"] == 0
    assert order["crew_id"] is None
    assert order["weather_window_id"] is None
    assert order["actual_hours"] is None
    assert order["submitted_by_user_id"] is None

    curtailment = validate_success(
        api.create_curtailment_order(
            turbine_id,
            curtailment_payload(
                turbine_version(api, turbine_id),
                reason=CURTAILMENT_REASON_NOISE,
                start_utc="2026-08-02T00:00:00Z",
                end_utc="2026-08-02T06:00:00Z",
                power_limit_kw=1500,
                deemed_kwh_per_hour=500,
            ),
            make_control_room_headers(),
        ),
        expected_status=201,
    )
    assert curtailment["state"] == CURTAILMENT_PENDING
    assert_two_dp(curtailment["curtailed_hours"], 0, "curtailed hours at issuance")
    assert_two_dp(curtailment["lost_energy_kwh"], 0, "lost energy at issuance")

    window = validate_success(
        api.create_weather_window(
            weather_window_payload(
                farm_id,
                start_utc="2026-08-10T06:00:00Z",
                end_utc="2026-08-10T18:00:00Z",
                forecast_wind_speed_ms=8.0,
                forecast_gust_ms=11.0,
            ),
            make_planner_headers(),
        ),
        expected_status=201,
    )
    assert window["state"] == WINDOW_FORECAST
    assert window["active_work_order_count"] == 0

    finding = validate_success(
        api.record_blade_damage(
            turbine_id,
            blade_damage_payload(
                inspection_method=INSPECTION_DRONE,
                blade_position="A",
                inspected_at="2026-08-01T02:00:00Z",
                damage_category=2,
                damage_type=DAMAGE_LEADING_EDGE_EROSION,
                chord_position_pct=30.0,
                damage_length_mm=400,
                exposed_area_cm2=90.0,
            ),
            make_engineer_headers(),
        ),
        expected_status=201,
    )
    assert finding["state"] == BLADE_OPEN
    assert finding["waiver_rationale"] is None

    agreement = validate_success(
        api.create_service_agreement(
            service_agreement_payload(
                farm_id,
                guaranteed_availability_pct=97.0,
                lda_rate_cents_per_pct_point=500000,
                lda_cap_cents=4000000,
                period_start_utc="2026-07-01T00:00:00Z",
                period_end_utc="2026-08-01T00:00:00Z",
            ),
            make_commercial_headers(),
        ),
        expected_status=201,
    )
    assert agreement["state"] == AGREEMENT_ACTIVE
    assert agreement["at_risk_flag"] is False
    assert_cents(agreement["assessed_lda_cents"], 0, "assessed liquidated damages at opening")

    turbine = read_turbine(api, turbine_id)
    assert_turbine_dimensions(
        turbine,
        availability_state=AVAILABILITY_FAULTED,
        curtailment_state=CURTAILMENT_UNCONSTRAINED,
    )
    assert turbine["active_fault_code"] == "F-3001"
    assert turbine["active_curtailment_count"] == 0
    assert turbine["effective_power_limit_kw"] == 4200


def test_a_released_order_and_a_waived_finding_refuse_every_further_trigger(api):
    """Two terminal rows, three refused triggers, and no side effect from any of them.

    The contract states: "`RELEASED` and `CANCELLED` are both terminal."  Of the finding it
    states: "Both `REPAIRED` and `WAIVED` are terminal."  The refusal code is fixed by:
    "Every other action endpoint, covering crane mobilizations, component replacements,
    weather windows, curtailment orders, service agreements, blade findings and landowner
    settlements, yields `ERR_INVALID_STATE`."  Of the accrual the release already made it
    states: "This is the one place where accrual is measured from what actually happened
    rather than from what was planned: `curtailed_hours` is the elapsed time from
    `start_utc` to `released_at` expressed in hours, **not** from `start_utc` to the order's
    `end_utc`, so an early release accrues strictly less than the order asked for."  And:
    "`lost_energy_kwh` is `curtailed_hours` multiplied by `deemed_kwh_per_hour`, rounded
    half up to two decimal places."  And: "The turbine's `active_curtailment_count` is
    decremented by 1, and `effective_power_limit_kw` is recomputed as the smallest
    `power_limit_kw` across the orders that remain active, or as the model's
    `rated_power_kw` — the uncurtailed nameplate ceiling — when none remain."  Of a refused
    request it states: "A rejected request writes nothing at all — no counter moves, no
    `version` advances, no partial cascade survives."

    Design: Corner/state_machines/terminal_released_order_and_waived_damage_rejects_every_further_trigger
    """
    site = setup_released_curtailment_and_waived_damage(api)
    order_id = site["curtailment"]["id"]
    finding_id = site["finding"]["id"]
    turbine_id = site["turbine"]["id"]

    validate_error(
        api.activate_curtailment_order(order_id, make_control_room_headers()),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.release_curtailment_order(
            order_id, "2026-08-01T07:00:00Z", make_control_room_headers()
        ),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.prioritize_blade_damage(finding_id, make_engineer_headers(ENGINEER_2_USER_ID)),
        ERR_INVALID_STATE,
        expected_status=409,
    )

    order = read_curtailment(api, order_id)
    assert order["state"] == CURTAILMENT_RELEASED
    assert_two_dp(order["curtailed_hours"], 6, "curtailed hours from the first release")
    assert_two_dp(order["lost_energy_kwh"], 3000, "lost energy from the first release")
    assert_version_unchanged(site["curtailment"], order)

    finding = read_blade_damage(api, finding_id)
    assert finding["state"] == BLADE_WAIVED
    assert_version_unchanged(site["finding"], finding)

    turbine = read_turbine(api, turbine_id)
    assert_turbine_dimensions(turbine, curtailment_state=CURTAILMENT_UNCONSTRAINED)
    assert turbine["active_curtailment_count"] == 0
    assert turbine["effective_power_limit_kw"] == 4200


def test_replaying_confirm_and_submit_is_refused_rather_than_silently_accepted(api):
    """These action endpoints are transitions, not idempotent setters.

    The contract states: "Confirming a window drives it `FORECAST → CONFIRMED` and is
    permitted only while its `end_utc` is still strictly after the current logical clock; a
    window that has already lapsed cannot be confirmed."  Of the order it states:
    "Submission moves an order `DRAFT → SUBMITTED`, and it is also the way an order
    re-enters planning from `REVISION_REQUESTED → SUBMITTED`."  And: "Either way the turbine
    must not be `DECOMMISSIONED`, `submitted_by_user_id` is set to the acting `X-User-ID` —
    overwriting whatever it held on a previous submission — and the order's `priority_score`
    is computed."  The two refusal codes are fixed by: "Work-order transitions — submit,
    request-revision, schedule, start, complete and cancel — yield
    `ERR_WORK_ORDER_INVALID_STATE`."  And: "Every other action endpoint, covering crane
    mobilizations, component replacements, weather windows, curtailment orders, service
    agreements, blade findings and landowner settlements, yields `ERR_INVALID_STATE`."  That
    a refusal is not a write follows from: "`updated_at` is refreshed on every mutation of
    the row, and `version` starts at 1 when the row is created and increments by exactly 1
    on every mutation of that row, including mutations that reach the row by cascade from an
    operation that named a different resource."  And: "A rejected request writes nothing at
    all — no counter moves, no `version` advances, no partial cascade survives."

    Design: Corner/state_machines/repeating_confirm_and_submit_is_rejected_rather_than_silently_accepted
    """
    site = setup_replay_targets(api)
    window_id = site["window"]["id"]
    order_id = site["order"]["id"]

    validate_error(
        api.confirm_weather_window(window_id, make_planner_headers()),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    window = read_window(api, window_id)
    assert window["state"] == WINDOW_CONFIRMED
    assert_version_unchanged(site["window"], window)

    validate_error(
        api.submit_work_order(order_id, make_engineer_headers()),
        ERR_WORK_ORDER_INVALID_STATE,
        expected_status=409,
    )
    order = read_work_order(api, order_id)
    assert order["state"] == WO_SUBMITTED
    assert order["submitted_by_user_id"] == PLANNER_USER_ID
    assert_version_unchanged(site["order"], order)


def test_the_window_counter_and_the_window_state_move_on_different_events(api):
    """Schedule moves the counter, the first start moves the state, the last finish expires it.

    The contract states: "A successful schedule stores `crew_id`, `weather_window_id`,
    `planned_start_utc` and `planned_end_utc` on the order, sets the crew's `status` to
    `ON_SHIFT`, and increments the window's `active_work_order_count` by 1 while
    **leaving the window in `CONFIRMED`** — which is precisely what allows a second crew to
    be scheduled into the same window."  It adds: "A confirmed window is **shared**, not
    exclusive: several crews may be scheduled into the same confirmed window at once, and
    crew contention is policed by the crew rules of §3.4 rather than by window
    exclusivity."  Of the start it states: "A window's onward lifecycle is entirely
    cascade-driven: the first work order to start in it moves it `CONFIRMED → CONSUMED`, at
    which point it stops backing new schedules and stops counting toward crane standby days,
    though `active_work_order_count` is not itself changed by starting."  Of the finish it
    states: "When the last order occupying a consumed window finishes or is cancelled and
    `active_work_order_count` reaches 0, the window moves `CONSUMED → EXPIRED`."  And: "It
    decrements the named window's `active_work_order_count` by 1, and when that count reaches
    0 the window moves `CONSUMED → EXPIRED`."  The gates a start does check are exactly:
    "The turbine must be in the availability state the work type expects: `ONLINE` for a
    `SCHEDULED_SERVICE`, `BLADE_REPAIR` or `MAJOR_COMPONENT` order, and `FAULTED` for a
    `FAULT_DISPATCH` order."  Of the money it states: "The order moves `IN_PROGRESS →
    COMPLETED` and its `labor_cost_cents` is set to `actual_hours` multiplied by the assigned
    crew's `hourly_rate_cents`, rounded half up to a whole cent."  And: "Alongside those
    hops, completion posts the labour cost to the site ledger, adding `labor_cost_cents` both
    to the farm's `maintenance_spend_cents` and to its `opex_accrued_cents`."

    Design: Corner/state_machines/weather_window_is_consumed_by_the_first_start_and_expires_only_when_the_last_order_leaves
    """
    site = setup_shared_window_two_orders(api)
    window_id = site["window"]["id"]
    order_a = site["order_a"]["id"]
    order_b = site["order_b"]["id"]
    crew_a = site["crew_a"]["id"]
    crew_b = site["crew_b"]["id"]
    turbine_id = site["turbine"]["id"]

    after_schedules = read_window(api, window_id)
    assert after_schedules["state"] == WINDOW_CONFIRMED
    assert after_schedules["active_work_order_count"] == 2

    validate_success(api.start_work_order(order_a, make_crew_lead_headers(crew_a)))
    after_first_start = read_window(api, window_id)
    assert after_first_start["state"] == WINDOW_CONSUMED
    assert after_first_start["active_work_order_count"] == 2

    validate_success(api.complete_work_order(order_a, 4, make_crew_lead_headers(crew_a)))
    after_first_completion = read_window(api, window_id)
    assert after_first_completion["state"] == WINDOW_CONSUMED
    assert after_first_completion["active_work_order_count"] == 1

    started_b = validate_success(api.start_work_order(order_b, make_crew_lead_headers(crew_b)))
    assert started_b["state"] == WO_IN_PROGRESS
    completed_b = validate_success(
        api.complete_work_order(order_b, 4, make_crew_lead_headers(crew_b))
    )
    assert completed_b["state"] == WO_COMPLETED
    assert_cents(completed_b["labor_cost_cents"], 320000, "second crew's labour cost")

    final_window = read_window(api, window_id)
    assert final_window["state"] == WINDOW_EXPIRED
    assert final_window["active_work_order_count"] == 0
    assert_turbine_dimensions(
        read_turbine(api, turbine_id), availability_state=AVAILABILITY_ONLINE
    )
    farm = read_farm(api, site["farm"]["id"])
    assert_cents(farm["maintenance_spend_cents"], 680000, "both crews' labour on the ledger")


def test_the_reset_track_is_guarded_by_two_different_pinned_refusals(api):
    """A dispatch-only code and a lockout code never reach the track, and a spent quota closes it.

    The contract states: "A `disposition` of `REMOTE_RESET` moves the event `RAISED →
    RESET_PENDING`; it is permitted only when the event's `severity_class_pinned` is
    `RESETTABLE` and its `requires_dispatch_pinned` is false, and any other combination —
    `ADVISORY`, `LOCKOUT`, or a code the rule marks dispatch-only — is refused with
    `ERR_RESET_NOT_PERMITTED`."  It continues: "A `disposition` of `DISPATCH` moves the event
    `RAISED → DISPATCH_REQUIRED`, and it may equally be applied to an event already sitting
    in `RESET_PENDING`, moving it `RESET_PENDING → DISPATCH_REQUIRED`; that escalation
    consumes no reset attempt and simply takes the event off the reset track."  And:
    "Neither disposition writes either turbine state dimension — the turbine stays `FAULTED`
    throughout triage."  Of the attempt itself it states: "An eligible attempt always
    increments both counters — the event's `reset_attempt_count` by 1 and the turbine's
    `remote_reset_count_24h` by 1 — and then branches on the outcome with equal weight on
    each branch."  And: "A `reset_outcome` of `FAILED` leaves the event in `RESET_PENDING`
    and the turbine in `FAULTED`, deliberately so: any remaining quota can still be spent on
    a further attempt from the same state, and escalation to `DISPATCH_REQUIRED` is a
    separate triage call rather than an automatic consequence of failure."  And: "A count
    exactly equal to the pinned maximum is not eligible and is refused with
    `ERR_RESET_QUOTA_EXHAUSTED`; an ineligible severity class or a dispatch-only code is
    refused with `ERR_RESET_NOT_PERMITTED`; and a force-stopped turbine is refused with
    `ERR_TURBINE_FORCE_STOPPED`, because a turbine held down for icing or wildlife protection
    must not be spun back up from a desk."  And: "A rejected request writes nothing at all —
    no counter moves, no `version` advances, no partial cascade survives."

    Design: Corner/state_machines/triage_and_reset_are_rejected_for_dispatch_only_and_lockout_codes_and_once_the_quota_is_spent
    """
    site = setup_reset_track_trio(api)
    dispatch_only = site["event_dispatch_only"]["id"]
    lockout = site["event_lockout"]["id"]
    quota = site["event_quota"]["id"]
    quota_turbine = site["turbine_quota"]["id"]

    validate_error(
        api.triage_fault_event(dispatch_only, DISPOSITION_REMOTE_RESET, make_control_room_headers()),
        ERR_RESET_NOT_PERMITTED,
        expected_status=422,
    )
    assert read_fault_event(api, dispatch_only)["triage_state"] == TRIAGE_RAISED

    validate_error(
        api.triage_fault_event(lockout, DISPOSITION_REMOTE_RESET, make_control_room_headers()),
        ERR_RESET_NOT_PERMITTED,
        expected_status=422,
    )
    assert read_fault_event(api, lockout)["triage_state"] == TRIAGE_RAISED

    triaged = validate_success(
        api.triage_fault_event(quota, DISPOSITION_REMOTE_RESET, make_control_room_headers())
    )
    assert triaged["triage_state"] == TRIAGE_RESET_PENDING
    assert triaged["reset_attempt_count"] == 0
    assert read_turbine(api, quota_turbine)["availability_state"] == AVAILABILITY_FAULTED

    first_attempt = validate_success(
        api.remote_reset(quota, RESET_OUTCOME_FAILED, make_control_room_headers())
    )
    assert first_attempt["triage_state"] == TRIAGE_RESET_PENDING
    assert first_attempt["reset_attempt_count"] == 1
    assert read_turbine(api, quota_turbine)["remote_reset_count_24h"] == 1

    validate_error(
        api.remote_reset(quota, RESET_OUTCOME_FAILED, make_control_room_headers()),
        ERR_RESET_QUOTA_EXHAUSTED,
        expected_status=422,
    )
    refused = read_fault_event(api, quota)
    assert refused["triage_state"] == TRIAGE_RESET_PENDING
    assert refused["reset_attempt_count"] == 1
    assert read_turbine(api, quota_turbine)["remote_reset_count_24h"] == 1

    escalated = validate_success(
        api.triage_fault_event(quota, DISPOSITION_DISPATCH, make_control_room_headers())
    )
    assert escalated["triage_state"] == TRIAGE_DISPATCH_REQUIRED
    assert escalated["reset_attempt_count"] == 1
