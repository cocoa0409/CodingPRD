"""Difficulty-queue tests for precedence, boundary precision and temporal overlap.

Every window here is measured against the logical clock, which each test sets
explicitly before the call under test.
"""
from test_helpers import (
    SETUP_CLOCK,
    api_client,
    award_contract,
    begin_hand_back,
    create_obligation,
    create_pm_schedule,
    create_standard,
    employee_payload,
    evaluate_pm_schedule,
    freeze_baseline,
    get_success_data,
    measurement_payload,
    pm_schedule_payload,
    read_pm_schedule,
    register_asset,
    register_municipality,
    set_clock,
    setup_operating_contract,
    setup_operating_contract_with_permit,
    setup_under_review_contract,
    staffing_commitment_payload,
    submit_baseline_assessment,
    validate_error,
    validate_success,
    work_order_payload,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_employee_headers

# A well-formed identifier that no obligation can carry.
UNKNOWN_OBLIGATION_ID = "9f1c7d20-0000-4000-8000-000000000000"


def _operating_contract_with_live_schedule(schedule=True, frequency_days=30,
                                           duration_hours=3.0,
                                           first_due_at="2026-05-31T00:00:00Z"):
    """OPERATING contract whose asset optionally carries a live PM schedule.

    The schedule is created before the contract commences so the commence
    fan-out makes it ACTIVE with next_due_at = contract_start + frequency_days.
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    set_clock(SETUP_CLOCK)
    create_standard(contract["id"], contract_headers, activate=True)
    asset = register_asset(
        contract["id"],
        municipality_headers,
        asset_tag="BLW-902",
        asset_class="BLOWER",
        install_year=2019,
        useful_life_years=20,
        criticality_rank=2,
    )
    submit_baseline_assessment(
        asset["id"], contract_headers, municipality_headers=municipality_headers
    )
    live = None
    if schedule:
        live = create_pm_schedule(
            asset["id"],
            contract_headers,
            frequency_days=frequency_days,
            duration_hours=duration_hours,
            first_due_at=first_due_at,
        )
    get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=4.0), contract_headers
        )
    )
    # PRD §3.1: mobilization requires `baseline_frozen` to still be false, so the
    # freeze follows it; PRD §3.3: the transfer below requires the frozen baseline.
    get_success_data(api_client.mobilize_contract(contract["id"], contract_headers))
    freeze_baseline(contract["id"], municipality_headers)
    employee = get_success_data(
        api_client.register_employee(contract["id"], employee_payload(), contract_headers)
    )
    get_success_data(api_client.offer_transfer(contract["id"], employee["id"], contract_headers))
    get_success_data(
        api_client.accept_transfer_offer(employee["id"], make_employee_headers(employee["id"]))
    )
    get_success_data(api_client.transfer_employee(employee["id"], contract_headers))
    get_success_data(api_client.begin_induction(employee["id"], contract_headers))
    get_success_data(api_client.complete_induction(employee["id"], contract_headers))
    response = api_client.commence_operating(contract["id"], contract_headers)
    assert response.status_code in (200, 201), (
        f"Setup failed: commence: {response.status_code} {response.text}"
    )
    if live is not None:
        live = read_pm_schedule(live["id"], contract_headers)
    return contract, contract_headers, municipality_headers, asset, live


def test_start_of_a_draft_work_order_reports_the_state_error_not_the_fiscal_one(api):
    """PRD §2.10: "The practical consequence is that a request which is both unauthorised and aimed at a missing record reports the authentication failure, not the 404; a request against a resource in the wrong state reports the state error rather than a downstream constraint error; and a request that violates two business rules reports the higher-priority one."
    PRD §3.6: "Starting work requires the order to be `SCHEDULED` and its expense class not to be `REJECTED_AS_CAPITAL`."
    PRD §2.10: "State-machine guards come after existence: whether the resource is in the required from-state, whether it is already terminal for the requested operation, and the specific state predicates described per entity in §3."

    Design: Difficulty/priority_pair_validation_conflict/work_order_start_state_precondition_beats_capital_threshold_check
    """
    scenario = setup_operating_contract()
    order = validate_success(
        api_client.raise_work_order(
            scenario.asset["id"],
            work_order_payload(work_type="CORRECTIVE", estimated_cost_cents=6000000),
            scenario.con_h,
        ),
        201,
    )
    assert order["status"] == "DRAFT", "a newly raised work order is DRAFT"

    response = api_client.start_work_order(order["id"], scenario.con_h)
    validate_error(response, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE)

    unchanged = get_success_data(api_client.get_work_order(order["id"], scenario.con_h))
    assert unchanged["status"] == "DRAFT", (
        "a refused start leaves the work order in DRAFT"
    )


def test_waiving_an_unknown_obligation_reports_not_found_before_waivability(api):
    """PRD §2.10: "Existence checks come next, walking the path left to right as described in §2.6. State-machine guards come after existence"
    PRD §3.9: "Waiving is the municipality's act from `DISPUTED` or from `OVERDUE` and requires the obligation's `is_critical` to be false; a critical obligation cannot be waived and an attempt is rejected with `ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE` (HTTP 403)."
    PRD §2.6: "A failure at any segment produces the not-found error for that segment's entity, and no later segment is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/obligate_existence_precedes_waivability_authorization_check
    """
    scenario = setup_under_review_contract()
    begin_hand_back(scenario.con["id"], scenario.mun_h)
    scenario.refresh_contract()

    critical = create_obligation(
        scenario.con["id"],
        scenario.mun_h,
        obligation_type="ASSET_HANDOVER",
        due_at="2026-06-01T00:00:00Z",
        is_critical=True,
        penalty_per_day_cents=50000,
    )
    set_clock("2026-06-05T00:00:00Z")
    overdue = get_success_data(
        api_client.evaluate_obligation(critical["id"], scenario.mun_h)
    )
    assert overdue["status"] == "OVERDUE"

    missing = api_client.waive_obligation(
        UNKNOWN_OBLIGATION_ID,
        {"waiver_basis": "Attempted waiver of an unknown obligation."},
        scenario.mun_h,
    )
    validate_error(missing, ApiErrorId.ERR_OBLIGATION_NOT_FOUND)

    refused = api_client.waive_obligation(
        critical["id"],
        {"waiver_basis": "Attempted waiver of the critical hand-over obligation."},
        scenario.mun_h,
    )
    validate_error(refused, ApiErrorId.ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE)

    still_overdue = get_success_data(
        api_client.get_obligation(critical["id"], scenario.mun_h)
    )
    assert still_overdue["status"] == "OVERDUE", (
        "a refused waiver leaves the obligation outstanding"
    )


def test_notification_filed_at_the_deadline_is_late_and_cites_the_permit(api):
    """PRD §3.7: "A `MAIN_BREAK` within 4 hours when its severity is `HIGH` or `CRITICAL`, and within 24 hours otherwise."
    PRD §3.7: "When the notification is later filed, `notification_late` is true when the filing instant is at or after the computed deadline — the boundary is inclusive, so a notification filed at exactly the deadline is late."
    PRD §3.7: "It stamps `notified_at`, computes `notification_late` by the deadline rules above, moves the event to `NOTIFIED`, and — on the path from `CONTAINED` only — drags the owning permit from `ACTIVE` to `NOTICE_OF_VIOLATION` when the notification was late."

    Design: Difficulty/boundary_precision_check/notification_deadline_inclusive_boundary_on_main_break
    """
    scenario = setup_operating_contract_with_permit()
    set_clock("2026-10-01T00:00:00Z")
    event = validate_success(
        api_client.report_emergency(
            scenario.con["id"],
            {
                "asset_id": scenario.asset["id"],
                "event_type": "MAIN_BREAK",
                "severity": "MEDIUM",
                "occurred_at": "2026-10-01T00:00:00Z",
            },
            scenario.con_h,
        ),
        201,
    )
    dispatched = validate_success(api_client.dispatch_emergency(event["id"], scenario.con_h))
    assert dispatched["notify_deadline_at"].startswith("2026-10-02T00:00:00"), (
        "a MEDIUM main break carries a 24 hour notification deadline"
    )

    set_clock("2026-10-01T03:00:00Z")
    contained = validate_success(
        api_client.contain_emergency(
            event["id"], {"contained_at": "2026-10-01T03:00:00Z"}, scenario.con_h
        )
    )
    assert contained["status"] == "CONTAINED"

    # Filing at exactly the deadline: the boundary is inclusive, so this is late.
    set_clock("2026-10-02T00:00:00Z")
    notified = validate_success(
        api_client.notify_emergency(
            event["id"],
            {"notification_reference": "OH-ENV-2026-4471"},
            scenario.con_h,
        )
    )
    assert notified["status"] == "NOTIFIED"
    assert notified["notified_at"].startswith("2026-10-02T00:00:00")
    assert notified["notification_late"] is True, (
        "a notification filed at exactly the deadline is late"
    )

    permit = get_success_data(api_client.get_permit(scenario.permit["id"], scenario.con_h))
    assert permit["status"] == "NOTICE_OF_VIOLATION", (
        "a late notification from CONTAINED drags the owning permit into violation"
    )


def test_pm_compliance_rate_is_zero_when_no_grace_window_has_closed(api):
    """PRD §3.6: "The PM compliance percentage (`compliance_rate_pct`) is the fraction of closed occurrences that met their grace window, rounded half-up to two decimal places, and it is computed over every occurrence generated since the schedule first became `ACTIVE`, in ascending due order with ties broken by the occurrence's creation instant and never by id."
    PRD §3.6: "An occurrence whose grace window has not yet closed is excluded from both the numerator and the denominator, and an empty set yields exactly 0.00."
    PRD §3.6: "When the logical clock reaches `next_due_at`, the schedule moves from `ACTIVE` to `DUE`, stamps `status_changed_at`, and, if no preventive work order already exists for that occurrence, creates one in `SCHEDULED` state against the schedule's asset."

    Design: Difficulty/boundary_precision_check/pm_compliance_rate_empty_set_boundary_on_schedule
    """
    contract, contract_headers, municipality_headers, asset, schedule = (
        _operating_contract_with_live_schedule()
    )
    assert schedule["next_due_at"].startswith("2026-05-31")

    # The clock reaches next_due_at exactly; the seven day grace window is still open.
    set_clock("2026-05-31T00:00:00Z")
    evaluated = evaluate_pm_schedule(schedule["id"], contract_headers)

    assert evaluated["status"] == "DUE"
    assert evaluated["missed_occurrence_count"] == 0
    assert evaluated["compliance_rate_pct"] == 0.0, (
        "an empty evaluated set yields exactly 0.00, never a division error or 100.00"
    )


def test_measurement_period_adjacency_is_accepted_but_true_overlap_is_not(api):
    """PRD §3.4: "A measurement is recorded under a standard, citing that standard's `performance_standard_id`, with a `period_start` that is inclusive, a `period_end` that is exclusive and must be strictly after `period_start`, and the `measured_value` observed for the period."
    PRD §3.4: "The measurement period must not overlap any existing measurement period on the same standard; an overlap is rejected with `ERR_MEASUREMENT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/measurement_period_adjacency_rejected_on_standard
    """
    scenario = setup_operating_contract()
    standard = scenario.std
    first = validate_success(
        api_client.record_measurement(
            standard["id"],
            measurement_payload(
                period_start="2026-06-01T00:00:00Z",
                period_end="2026-07-01T00:00:00Z",
                measured_value=9.0,
            ),
            scenario.con_h,
        ),
        201,
    )

    # One second before the existing period's exclusive end: a true intersection.
    overlapping = api_client.record_measurement(
        standard["id"],
        measurement_payload(
            period_start="2026-06-30T23:59:59Z",
            period_end="2026-07-31T00:00:00Z",
            measured_value=9.0,
        ),
        scenario.con_h,
    )
    validate_error(overlapping, ApiErrorId.ERR_MEASUREMENT_PERIOD_OVERLAP)

    # Starting exactly at the existing period's end is adjacency, not overlap.
    second = validate_success(
        api_client.record_measurement(
            standard["id"],
            measurement_payload(
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                measured_value=9.0,
            ),
            scenario.con_h,
        ),
        201,
    )
    assert second["period_start"].startswith("2026-07-01T00:00:00"), (
        "a period that starts exactly at the previous period_end is accepted"
    )

    measurements = get_success_data(
        api_client.list_standard_measurements(standard["id"], scenario.con_h)
    )
    assert len(measurements) == 2, (
        "the rejected overlap must not have created a measurement row"
    )
    assert first["id"] in [row["id"] for row in measurements]


def test_pm_schedule_occupation_overlap_on_the_same_asset_is_rejected(api):
    """PRD §3.6: "And the occupancy must not collide with another schedule or an open preventive work order on the same asset — an overlapping occupation is rejected with `ERR_PM_OCCUPATION_OVERLAP` (HTTP 409)."
    PRD §3.6: "A schedule is created under an asset by the operator with a `frequency_days` of at least 1, a `duration_hours` greater than 0, and a `first_due_at`; the schedule starts at `DRAFT` and its `next_due_at` is set from the supplied `first_due_at`."

    Design: Difficulty/resource_temporal_overlap/pm_occupation_buffer_conflict_on_asset
    """
    contract, contract_headers, municipality_headers, asset, _ = (
        _operating_contract_with_live_schedule(schedule=False)
    )
    set_clock("2026-10-01T00:00:00Z")

    first = create_pm_schedule(
        asset["id"],
        contract_headers,
        frequency_days=30,
        duration_hours=4.0,
        first_due_at="2026-10-10T00:00:00Z",
    )
    assert first["status"] == "DRAFT"

    # A four hour occupation starting two hours into the existing one collides.
    overlapping = api_client.create_pm_schedule(
        asset["id"],
        pm_schedule_payload(
            frequency_days=30, duration_hours=4.0, first_due_at="2026-10-10T02:00:00Z"
        ),
        contract_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_PM_OCCUPATION_OVERLAP)

    second = validate_success(
        api_client.create_pm_schedule(
            asset["id"],
            pm_schedule_payload(
                frequency_days=30, duration_hours=4.0, first_due_at="2026-10-11T00:00:00Z"
            ),
            contract_headers,
        ),
        201,
    )
    assert second["status"] == "DRAFT", "a non-conflicting schedule is created in DRAFT"

    schedules = get_success_data(
        api_client.list_asset_pm_schedules(asset["id"], contract_headers)
    )
    assert len(schedules) == 2, "the rejected schedule must not have been persisted"
