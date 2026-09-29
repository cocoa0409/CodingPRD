"""Multi-hop cascades, the regulatory hold and the incident fork-join.

A single failing checklist line moves four rows, a ride hold moves the workforce,
and the two investigation branches carry different clearance preconditions.
"""

from test_helpers import (
    MANAGER,
    SAFETY_OFFICER,
    TECHNICIAN,
    api_client,
    assert_downtime_event,
    assert_instant_equals,
    assert_inspection_counters,
    factories,
    fixtures,
    make_maintenance_technician_headers,
    make_qualified_inspector_headers,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"


def _template_with_lines(attraction_id, lines, effective_from_date="2026-07-01"):
    """Author and activate one revision of (severity, text, component_id) lines."""
    template = fixtures.create_template(
        attraction_id, effective_from_date=effective_from_date
    )
    items = []
    for index, line in enumerate(lines, start=1):
        severity_class, description = line[0], line[1]
        overrides = {}
        if len(line) > 2 and line[2] is not None:
            overrides["component_id"] = line[2]
        items.append(
            fixtures.append_line(
                template["id"],
                sequence_no=index,
                severity_class=severity_class,
                description=description,
                **overrides,
            )
        )
    fixtures.activate_template(template["id"], attraction_id)
    return items


def _frontier_runaway_walk():
    """A walk whose first line is safety-critical and bound to a brake caliper."""
    attraction = fixtures.create_attraction(
        name="Frontier Runaway",
        park_area="FRONTIER",
        manufacturer="Gerstlauer",
        model_code="EC-450",
        ride_class="THRILL",
        theoretical_hourly_capacity=720,
        min_operators_required=2,
        parts_budget_cents=2500000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Station brake caliper",
        component_type="BRAKE",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=60000,
        ndt_interval_days=400,
    )
    _template_with_lines(
        attraction["id"],
        [
            ("SAFETY_CRITICAL", "Station brake pad thickness", component["id"]),
            ("ADVISORY", "Platform gate paint", None),
        ],
    )
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01", "tech-2")
    results = fixtures.list_item_results(inspection["id"])
    return {
        "attraction": attraction,
        "component": component,
        "inspection": inspection,
        "results": results,
    }


def test_a_safety_critical_failure_propagates_through_four_hops():
    """One FAIL moves the component, the inspection, the posture and a new event.

    PRD §3.2: "**Hop one** of the cascade sets that component's `condition_flag` to
    `SUSPECT`, and this happens for any `FAIL` on any line whose `component_id` is
    non-null, regardless of `severity_class`."
    PRD §3.2: "**Hop four** opens a downtime event on the attraction automatically:
    the server creates one with `cause_category` `INSPECTION_FAIL`, `auto_opened`
    set to true, `started_at` set to the current logical clock instant and `status`
    `OPEN`".

    Design: Difficulty/transitive_cascade/safety_critical_fail_cascades_four_hops_and_walk_back_is_partial
    """
    bundle = _frontier_runaway_walk()

    fixtures.record_result(
        bundle["results"][0]["id"],
        "FAIL",
        "Pad at 2mm, below minimum",
        technician_badge="tech-2",
    )

    component = fixtures.read_component(bundle["component"]["id"])
    assert component["condition_flag"] == "SUSPECT"

    inspection = validate_success(
        api_client.get_daily_inspection(bundle["inspection"]["id"], TECHNICIAN)
    )
    assert_inspection_counters(inspection, status="BLOCKED", blocking=1)

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["operational_posture"] == "DOWN"

    auto_events = fixtures.auto_opened_downtime_events(bundle["attraction"]["id"])
    assert len(auto_events) == 1
    event = auto_events[0]
    assert_downtime_event(event)
    assert event["cause_category"] == "INSPECTION_FAIL"
    assert event["auto_opened"] is True
    assert event["status"] == "OPEN"
    assert event["ended_at"] is None
    assert_instant_equals(event["started_at"], CLOCK_START, "started_at")


def test_re_recording_the_blocking_line_as_a_pass_walks_back_only_part_of_it():
    """The walk-back frees the inspection but leaves the downtime event standing.

    PRD §3.2: "Re-recording the last remaining blocking line as `PASS` — that is, a
    re-record on a `SAFETY_CRITICAL` row whose current `outcome` is `FAIL`, against
    an inspection currently `BLOCKED`, where `blocking_item_count` would reach 0 as a
    result — decrements `blocking_item_count` to 0 and returns the inspection
    `BLOCKED` → `IN_PROGRESS`."
    PRD §3.2: "The attraction's `operational_posture` is recomputed, and here the
    domain is deliberately conservative: the downtime event that hop four opened is
    **not** closed automatically, so the attraction remains `DOWN` until a manager
    closes or voids that event."

    Design: Difficulty/transitive_cascade/safety_critical_fail_cascades_four_hops_and_walk_back_is_partial
    """
    bundle = _frontier_runaway_walk()
    fixtures.record_result(
        bundle["results"][0]["id"],
        "FAIL",
        "Pad at 2mm, below minimum",
        technician_badge="tech-2",
    )
    auto_event = fixtures.auto_opened_downtime_events(bundle["attraction"]["id"])[0]

    fixtures.record_result(
        bundle["results"][0]["id"], "PASS", technician_badge="tech-2"
    )

    inspection = validate_success(
        api_client.get_daily_inspection(bundle["inspection"]["id"], TECHNICIAN)
    )
    assert_inspection_counters(inspection, status="IN_PROGRESS", blocking=0)

    still_open = validate_success(
        api_client.get_downtime_event(auto_event["id"], TECHNICIAN)
    )
    assert still_open["status"] == "OPEN"

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["operational_posture"] == "DOWN"

    component = fixtures.read_component(bundle["component"]["id"])
    assert component["condition_flag"] == "OK", (
        "no other failed row still references the component"
    )


def _timber_twister_with_three_operators():
    attraction = fixtures.create_attraction(
        name="Timber Twister",
        park_area="FRONTIER",
        manufacturer="GCI",
        model_code="WD-88",
        ride_class="THRILL",
        theoretical_hourly_capacity=880,
        min_operators_required=2,
        parts_budget_cents=2200000,
    )
    graded = [("op-11", 90, 85), ("op-12", 96, 92), ("op-13", 70, 90)]
    certifications = [
        fixtures.create_certification(
            attraction["id"],
            operator_user_id=badge,
            effective_from="2026-07-01T00:00:00.000Z",
            expires_at="2026-12-31T00:00:00.000Z",
            restraint_verification_score=restraint,
            dispatch_procedure_score=dispatch,
        )
        for badge, restraint, dispatch in graded
    ]
    incident = fixtures.create_incident(
        attraction["id"],
        occurred_at="2026-08-01T09:15:00.000Z",
        injury_severity="MINOR",
        guest_count_affected=2,
        narrative="Two guests reported jolt at brake run",
    )
    return {
        "attraction": attraction,
        "certifications": certifications,
        "incident": incident,
    }


def test_the_ride_hold_suspends_only_the_certified_rows():
    """The hold cascade reaches the certified set and nothing else.

    PRD §3.8: "**Hop three** suspends the workforce: every operator certification of
    that attraction whose derived `status` is `CERTIFIED` moves to `SUSPENDED` with
    its `suspension_reason` set to `RIDE_HOLD` and its `suspended_at` stamped with
    the current logical clock instant, and the incident's
    `suspended_certification_count` records exactly how many certifications it
    suspended."
    PRD §3.7: "In every other case the status is `TRAINEE` — which is to say a
    failing score on either practical leaves the operator a trainee indefinitely
    rather than producing an error."

    Design: Difficulty/transitive_cascade/ride_hold_cascade_suspends_only_certified_rows_and_gates_cycle_logging
    """
    bundle = _timber_twister_with_three_operators()
    before = fixtures.read_attraction(bundle["attraction"]["id"])
    assert before["certified_operator_count"] == 2

    held = validate_success(
        api_client.hold_ride(bundle["incident"]["id"], SAFETY_OFFICER)
    )
    assert held["status"] == "RIDE_HELD"
    assert held["suspended_certification_count"] == 2

    first, second, third = bundle["certifications"]
    for certification in (first, second):
        row = validate_success(
            api_client.get_operator_certification(certification["id"], MANAGER)
        )
        assert row["status"] == "SUSPENDED"
        assert row["suspension_reason"] == "RIDE_HOLD"
        assert_instant_equals(row["suspended_at"], CLOCK_START, "suspended_at")

    trainee = validate_success(
        api_client.get_operator_certification(third["id"], MANAGER)
    )
    assert trainee["status"] == "TRAINEE"
    assert trainee["suspended_at"] is None

    after = fixtures.read_attraction(bundle["attraction"]["id"])
    assert after["regulatory_hold"] is True
    assert after["operational_posture"] == "HOLD"
    assert after["certified_operator_count"] == 0


def test_a_held_ride_refuses_cycle_logging():
    """A held ride accumulates no wear because it does not run.

    PRD §3.1: "While the attraction's `regulatory_hold` is true, cycle logging is
    refused with `ERR_REGULATORY_HOLD_ACTIVE` — a held ride does not accumulate wear
    because a held ride does not run."
    PRD §2.6: "`ERR_REGULATORY_HOLD_ACTIVE` (409) — operations that would return an
    attraction to guest service are refused while the attraction's
    `regulatory_hold` is true. This guards exactly two operations: inspection
    sign-off, and logging ride cycles."

    Design: Difficulty/transitive_cascade/ride_hold_cascade_suspends_only_certified_rows_and_gates_cycle_logging
    """
    bundle = _timber_twister_with_three_operators()
    fixtures.set_clock(CLOCK_START)
    validate_success(api_client.hold_ride(bundle["incident"]["id"], SAFETY_OFFICER))

    response = api_client.log_cycles(
        bundle["attraction"]["id"],
        factories.log_cycles_payload("2026-08-01", 40),
        make_maintenance_technician_headers("tech-4"),
    )
    validate_error(response, "ERR_REGULATORY_HOLD_ACTIVE", 409)

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["cumulative_cycles"] == 0


def _sunset_wheel_pending_sign_off_under_hold():
    """A submitted walk on an attraction that a minor incident later held."""
    attraction = fixtures.create_attraction(
        name="Sunset Wheel",
        park_area="LAGOON",
        manufacturer="Chance",
        model_code="GW-90",
        ride_class="FAMILY",
        theoretical_hourly_capacity=480,
        min_operators_required=2,
        parts_budget_cents=900000,
    )
    _template_with_lines(
        attraction["id"], [("ESSENTIAL", "Gondola door latch function")]
    )
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01", "tech-5")
    results = fixtures.list_item_results(inspection["id"])
    fixtures.record_outcomes(results, ["PASS"], technician_badge="tech-5")
    submitted = fixtures.submit_inspection(inspection["id"], "tech-5")
    incident = fixtures.create_incident(
        attraction["id"],
        occurred_at="2026-08-01T08:00:00.000Z",
        injury_severity="MINOR",
        guest_count_affected=1,
        narrative="Guest reported pinched finger at gondola door",
    )
    held = validate_success(api_client.hold_ride(incident["id"], SAFETY_OFFICER))
    return {"attraction": attraction, "inspection": submitted, "incident": held}


def test_sign_off_is_refused_while_the_attraction_carries_a_regulatory_hold():
    """The hold gate reaches across into the incident register.

    PRD §3.3: "The attraction's `regulatory_hold` must be false. A live hold yields
    `ERR_REGULATORY_HOLD_ACTIVE`. This gate reaches across into the incident
    register, because `regulatory_hold` is true exactly while the attraction has an
    incident report in `RIDE_HELD`, `UNDER_INVESTIGATION` or `REGULATOR_NOTIFIED`."
    PRD §2.8: "`HOLD` — if the attraction's `regulatory_hold` is true."

    Design: Difficulty/cross_entity_state_dependency/signoff_gated_by_incident_hold_on_the_attraction_until_the_incident_clears
    """
    bundle = _sunset_wheel_pending_sign_off_under_hold()

    response = api_client.sign_off_daily_inspection(
        bundle["inspection"]["id"], make_qualified_inspector_headers("insp-8")
    )
    validate_error(response, "ERR_REGULATORY_HOLD_ACTIVE", 409)

    inspection = validate_success(
        api_client.get_daily_inspection(bundle["inspection"]["id"], TECHNICIAN)
    )
    assert inspection["status"] == "PENDING_SIGN_OFF"

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["operational_posture"] == "HOLD"


def test_clearing_the_incident_releases_the_hold_and_the_sign_off_succeeds():
    """The same call that was refused succeeds once the incident clears.

    PRD §3.8: "The attraction's `regulatory_hold` becomes false — but only when no
    other incident report of that attraction remains in `RIDE_HELD`,
    `UNDER_INVESTIGATION` or `REGULATOR_NOTIFIED`, so a second live incident keeps
    the hold in place."
    PRD §3.3: "The attraction's `last_signed_off_service_date` is set to this
    inspection's `service_date`, and the attraction's `operational_posture` is
    recomputed — which is how an attraction leaves `CLOSED_PENDING_INSPECTION` for
    `OPEN`, provided nothing higher in the posture precedence still gates it."

    Design: Difficulty/cross_entity_state_dependency/signoff_gated_by_incident_hold_on_the_attraction_until_the_incident_clears
    """
    bundle = _sunset_wheel_pending_sign_off_under_hold()
    api_client.sign_off_daily_inspection(
        bundle["inspection"]["id"], make_qualified_inspector_headers("insp-8")
    )

    cleared = fixtures.clear_incident_internally(bundle["incident"]["id"])
    assert cleared["status"] == "CLEARED_TO_OPERATE"

    released = fixtures.read_attraction(bundle["attraction"]["id"])
    assert released["regulatory_hold"] is False

    signed = validate_success(
        api_client.sign_off_daily_inspection(
            bundle["inspection"]["id"], make_qualified_inspector_headers("insp-8")
        )
    )
    assert signed["status"] == "SIGNED_OFF"
    assert signed["signed_off_by_user_id"] == "insp-8"

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["last_signed_off_service_date"] == "2026-08-01"
    assert attraction["operational_posture"] == "OPEN"


def _two_incidents_on_two_attractions():
    """One serious incident and one minor incident, filed two days before the clock."""
    fixtures.set_clock("2026-08-02T12:00:00.000Z")
    first = fixtures.create_attraction(
        name="Vertigo Drop",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="GD-70",
        ride_class="THRILL",
        theoretical_hourly_capacity=500,
        min_operators_required=2,
        parts_budget_cents=1500000,
    )
    second = fixtures.create_attraction(
        name="Cove Carousel",
        park_area="KIDS_COVE",
        manufacturer="Chance",
        model_code="CR-36",
        ride_class="KIDDIE",
        theoretical_hourly_capacity=300,
        min_operators_required=1,
        parts_budget_cents=800000,
    )
    serious = fixtures.create_incident(
        first["id"],
        occurred_at="2026-08-02T09:00:00.000Z",
        injury_severity="SERIOUS",
        guest_count_affected=1,
        narrative="Guest reported arm injury on restraint release",
    )
    minor = fixtures.create_incident(
        second["id"],
        occurred_at="2026-08-02T10:30:00.000Z",
        injury_severity="MINOR",
        guest_count_affected=1,
        narrative="Guest scraped knee boarding",
    )
    return {
        "first": first,
        "second": second,
        "serious": serious,
        "minor": minor,
    }


def test_a_serious_filing_opens_held_with_a_notification_deadline():
    """Severity forks the opening state and the statutory clock at filing time.

    PRD §3.8: "An incident whose `injury_severity` is `SERIOUS` or `FATAL` opens
    directly at `status` `RIDE_HELD`. Its `regulator_notification_due_at` is set to
    its `occurred_at` plus the statutory notification window of 24 hours, and the
    full four-hop hold cascade described below runs at once."
    PRD §3.8: "An incident whose `injury_severity` is `NONE` or `MINOR` opens at
    `status` `REPORTED`, its `regulator_notification_due_at` stays null, and no
    cascade runs at all — the ride keeps operating."

    Design: Difficulty/non_linear_state_machine/incident_fork_join_branch_asymmetry_on_clearance_reference
    """
    bundle = _two_incidents_on_two_attractions()

    assert bundle["serious"]["status"] == "RIDE_HELD"
    assert_instant_equals(
        bundle["serious"]["regulator_notification_due_at"],
        "2026-08-03T09:00:00.000Z",
        "regulator_notification_due_at",
    )

    assert bundle["minor"]["status"] == "REPORTED"
    assert bundle["minor"]["regulator_notification_due_at"] is None

    held_unit = fixtures.read_attraction(bundle["first"]["id"])
    assert held_unit["regulatory_hold"] is True
    operating_unit = fixtures.read_attraction(bundle["second"]["id"])
    assert operating_unit["regulatory_hold"] is False


def test_the_regulator_branch_records_a_late_filing_and_demands_a_reference():
    """Branch A stamps lateness and adds a precondition to clearance.

    PRD §3.8: "The supplied `regulator_case_ref` is stored, `notified_at` is stamped
    with the current logical clock instant, and `notified_late` is set to true
    exactly when `notified_at` is strictly later than
    `regulator_notification_due_at` — filing precisely on the deadline instant is on
    time."
    PRD §3.8: "An incident that took Branch A must supply a non-empty
    `regulator_clearance_ref`, which is stored on the row; omitting it, or supplying
    an empty one, is refused with `ERR_REGULATOR_CLEARANCE_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/incident_fork_join_branch_asymmetry_on_clearance_reference
    """
    bundle = _two_incidents_on_two_attractions()
    fixtures.set_clock("2026-08-04T10:00:00.000Z")

    validate_success(
        api_client.investigate_incident(bundle["serious"]["id"], SAFETY_OFFICER)
    )
    notified = validate_success(
        api_client.notify_regulator(
            bundle["serious"]["id"],
            factories.notify_regulator_payload("STATE-2026-4471"),
            SAFETY_OFFICER,
        )
    )
    assert notified["status"] == "REGULATOR_NOTIFIED"
    assert notified["notified_late"] is True
    assert_instant_equals(
        notified["notified_at"], "2026-08-04T10:00:00.000Z", "notified_at"
    )

    refused = api_client.clear_incident(
        bundle["serious"]["id"], SAFETY_OFFICER, {}
    )
    validate_error(refused, "ERR_REGULATOR_CLEARANCE_REQUIRED", 422)
    still = validate_success(
        api_client.get_incident(bundle["serious"]["id"], MANAGER)
    )
    assert still["status"] == "REGULATOR_NOTIFIED"

    cleared = validate_success(
        api_client.clear_incident(
            bundle["serious"]["id"],
            SAFETY_OFFICER,
            factories.clear_incident_payload("SC-2026-0091"),
        )
    )
    assert cleared["status"] == "CLEARED_TO_OPERATE"
    assert fixtures.read_attraction(bundle["first"]["id"])["regulatory_hold"] is False


def test_the_internal_review_branch_clears_without_any_reference():
    """Branch B ignores the clearance reference entirely.

    PRD §3.8: "An incident that took Branch B ignores `regulator_clearance_ref`
    entirely and may omit it."
    PRD §3.8: "Clearance stamps `cleared_at` with the current logical clock instant
    and then compensates the hold cascade, in the same shape on both branches."

    Design: Difficulty/non_linear_state_machine/incident_fork_join_branch_asymmetry_on_clearance_reference
    """
    bundle = _two_incidents_on_two_attractions()
    fixtures.set_clock("2026-08-04T10:00:00.000Z")

    validate_success(api_client.hold_ride(bundle["minor"]["id"], SAFETY_OFFICER))
    validate_success(
        api_client.investigate_incident(bundle["minor"]["id"], SAFETY_OFFICER)
    )
    validate_success(
        api_client.close_internal_review(bundle["minor"]["id"], SAFETY_OFFICER)
    )

    cleared = validate_success(
        api_client.clear_incident(bundle["minor"]["id"], SAFETY_OFFICER, {})
    )
    assert cleared["status"] == "CLEARED_TO_OPERATE"
    assert_instant_equals(
        cleared["cleared_at"], "2026-08-04T10:00:00.000Z", "cleared_at"
    )
    assert cleared["regulator_case_ref"] is None
    assert cleared["notified_late"] is False

    assert fixtures.read_attraction(bundle["second"]["id"])["regulatory_hold"] is False
