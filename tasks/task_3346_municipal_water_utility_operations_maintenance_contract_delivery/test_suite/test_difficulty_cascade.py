"""Difficulty-queue tests for the cross-entity cascades.

Each test walks a chain in which every hop is caused by the previous hop, and
each hop is evaluated against the logical clock rather than wall-clock time.
"""
from test_helpers import (
    SETUP_CLOCK,
    api_client,
    award_contract,
    complete_work_order,
    create_pm_schedule,
    create_standard,
    employee_payload,
    evaluate_pm_schedule,
    freeze_baseline,
    get_success_data,
    raise_started_work_order,
    read_asset,
    read_pm_schedule,
    register_asset,
    register_municipality,
    set_clock,
    setup_operating_contract_with_permit,
    staffing_commitment_payload,
    submit_baseline_assessment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    work_order_payload,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_employee_headers
from test_helpers.types import CONDITION_BANDS


def _operating_contract(assessed_score, install_year=2010, useful_life_years=15,
                        asset_tag="PMP-501", pm_schedule=None):
    """Build an OPERATING contract with one asset carrying a known baseline score.

    The preventive maintenance schedule, when requested, is created before the
    contract commences so the commence fan-out makes it ACTIVE.
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    set_clock(SETUP_CLOCK)
    create_standard(contract["id"], contract_headers, activate=True)
    asset = register_asset(
        contract["id"],
        municipality_headers,
        asset_tag=asset_tag,
        asset_class="PUMP",
        install_year=install_year,
        useful_life_years=useful_life_years,
        criticality_rank=1,
    )
    submit_baseline_assessment(
        asset["id"],
        contract_headers,
        municipality_headers=municipality_headers,
        assessed_score=assessed_score,
    )
    schedule = None
    if pm_schedule:
        schedule = create_pm_schedule(asset["id"], contract_headers, **pm_schedule)
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
    if schedule is not None:
        schedule = read_pm_schedule(schedule["id"], contract_headers)
    return contract, contract_headers, municipality_headers, asset, schedule


def test_third_missed_pm_occurrence_flags_the_asset_and_raises_a_capital_work_order(api):
    """PRD §3.6: "When the logical clock passes `next_due_at` plus 7 days and the linked preventive work order is still not `CLOSED`, the schedule moves to `OVERDUE`: a missed occurrence is counted into `missed_occurrence_count`, the compliance rate is recomputed, and `next_due_at` is advanced by `frequency_days`."
    PRD §3.6: "If that recomputation brings `missed_occurrence_count` to exactly 3, the owning asset is dragged into `REPLACEMENT_FLAGGED`."
    PRD §3.2: "Flagging stamps `replacement_flagged_at` and, as a side effect, creates a new work order under the asset classified as `CORRECTIVE` work with an expense class of `CAPITAL_LIFE_EVENT`, in `DRAFT`."

    Design: Difficulty/transitive_cascade/pm_miss_cascade_through_schedule_to_asset_to_capital_work_order
    """
    contract, contract_headers, municipality_headers, asset, schedule = _operating_contract(
        assessed_score=45.0,
        pm_schedule={"frequency_days": 30, "duration_hours": 4.0, "first_due_at": "2026-05-31T00:00:00Z"},
    )
    # The commence fan-out makes the schedule live at contract_start + frequency_days.
    assert schedule["status"] == "ACTIVE"
    assert schedule["next_due_at"].startswith("2026-05-31"), (
        "a live schedule is due at the contract start plus its frequency"
    )

    set_clock("2026-05-31T01:00:00Z")
    due = evaluate_pm_schedule(schedule["id"], contract_headers)
    assert due["status"] == "DUE"
    assert due["missed_occurrence_count"] == 0

    set_clock("2026-06-07T02:00:00Z")
    first_miss = evaluate_pm_schedule(schedule["id"], contract_headers)
    assert first_miss["missed_occurrence_count"] == 1

    set_clock("2026-07-07T02:00:00Z")
    second_miss = evaluate_pm_schedule(schedule["id"], contract_headers)
    assert second_miss["missed_occurrence_count"] == 2

    set_clock("2026-08-07T02:00:00Z")
    third_miss = evaluate_pm_schedule(schedule["id"], contract_headers)
    assert third_miss["missed_occurrence_count"] == 3, (
        "each pass of next_due_at plus seven days counts one missed occurrence"
    )
    assert third_miss["status"] == "OVERDUE"

    flagged = read_asset(asset["id"], contract_headers)
    assert flagged["status"] == "REPLACEMENT_FLAGGED", (
        "the third missed occurrence drags the owning asset into REPLACEMENT_FLAGGED"
    )
    assert flagged["replacement_flagged_at"].startswith("2026-08-07T02:00:00"), (
        "flagging stamps the instant at which the evaluation crossed the third miss"
    )

    orders = get_success_data(
        api_client.list_asset_work_orders(asset["id"], contract_headers)
    )
    capital_drafts = [
        order
        for order in orders
        if order["work_type"] == "CORRECTIVE" and order["status"] == "DRAFT"
    ]
    assert len(capital_drafts) == 1, (
        "exactly one draft corrective work order is created by the replacement flag"
    )


def test_verification_condition_drop_flags_the_asset_and_raises_a_capital_life_event(api):
    """PRD §3.6: "On success the order moves to `VERIFIED`, `submitted_to_municipality_at` is stamped with the current logical instant, the owning asset's `condition_score` is adjusted by the `condition_delta` and its band recomputed, and if the adjusted score falls below 40.0 the asset is dragged from `IN_SERVICE` into `REPLACEMENT_FLAGGED`."
    PRD §3.6: "That drag in turn creates a draft capital work order under the asset, which is how an ordinary repair can escalate into a capital project."
    PRD §3.2: "Whenever an asset's `condition_score` changes — because an assessment was recorded, revised, accepted, or because a work order closure applied a condition delta — the `condition_band` is recomputed and stored alongside it."

    Design: Difficulty/transitive_cascade/work_order_verification_cascade_through_asset_condition_to_replacement
    """
    contract, contract_headers, municipality_headers, asset, _ = _operating_contract(
        assessed_score=42.0, asset_tag="PMP-601"
    )
    before = read_asset(asset["id"], contract_headers)
    assert before["condition_score"] == 42.0
    assert before["status"] == "IN_SERVICE"

    order = raise_started_work_order(
        asset["id"],
        contract_headers,
        work_type="CORRECTIVE",
        estimated_cost_cents=800000,
    )
    completed = complete_work_order(
        order["id"],
        contract_headers,
        labour_hours=4.0,
        materials_cents=300000,
        closure_narrative=(
            "Rebuilt the pump coupling and realigned the drive train; vibration "
            "readings recorded."
        ),
    )
    assert completed["status"] == "COMPLETED"

    response = api_client.verify_work_order(
        order["id"], {"condition_delta": -5.0}, municipality_headers
    )
    verified = validate_success(response)
    assert verified["status"] == "VERIFIED"

    adjusted = read_asset(asset["id"], contract_headers)
    assert adjusted["condition_score"] == 37.0, (
        "the owning asset's condition score is adjusted by the observed delta"
    )
    assert adjusted["condition_band"] in CONDITION_BANDS, (
        "the condition band is recomputed and stored alongside the adjusted score"
    )
    assert adjusted["status"] == "REPLACEMENT_FLAGGED", (
        "a score below 40.0 drags the asset out of IN_SERVICE"
    )

    orders = get_success_data(
        api_client.list_asset_work_orders(asset["id"], contract_headers)
    )
    assert len(orders) == 2, "the drag adds one work order to the repaired asset"
    assert (
        len([order for order in orders if order["expense_class"] == "CAPITAL_LIFE_EVENT"]) == 1
    ), "the drag creates exactly one draft capital life-event work order"


def test_transfer_of_an_accepted_employee_is_blocked_until_the_baseline_is_frozen(api):
    """PRD §3.3: "Transferring an accepted employee onto the operator's payroll requires the baseline to be frozen and the logical clock to have reached `contract_start_date`"
    PRD §3.10: "Any request whose path names a resource in the wrong from-state for the transition being attempted is rejected with that entity's invalid-state error: `ERR_CONTRACT_INVALID_STATE` for a contract transition"

    Design: Difficulty/cross_entity_state_dependency/employee_transfer_blocked_until_asset_baseline_frozen
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    create_standard(contract["id"], contract_headers, activate=True)
    get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=2.0), contract_headers
        )
    )
    get_success_data(api_client.mobilize_contract(contract["id"], contract_headers))
    employee = get_success_data(
        api_client.register_employee(contract["id"], employee_payload(), contract_headers)
    )
    get_success_data(api_client.offer_transfer(contract["id"], employee["id"], contract_headers))
    accepted = get_success_data(
        api_client.accept_transfer_offer(employee["id"], make_employee_headers(employee["id"]))
    )
    assert accepted["status"] == "ACCEPTED"

    # The logical clock is already past contract_start_date; only the unfrozen
    # baseline stands between the employee and the operator's payroll. PRD §3.3
    # requires the baseline to be frozen but names no error for the refusal, and
    # the request's path names an employee already in its correct from-state, so
    # §3.10's invalid-state mapping does not pin one either. Either PRD-traceable
    # reading is accepted: the contract is not in a state that permits the
    # transition, or the baseline is unresolved.
    response = api_client.transfer_employee(employee["id"], contract_headers)
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_CONTRACT_INVALID_STATE, ApiErrorId.ERR_ASSET_BASELINE_UNRESOLVED],
    )

    still_accepted = get_success_data(
        api_client.get_employee(employee["id"], contract_headers)
    )
    assert still_accepted["status"] == "ACCEPTED", (
        "a refused transfer leaves the employee in ACCEPTED"
    )


def test_notice_of_violation_lets_a_breaching_measurement_be_waived(api):
    """PRD §3.5: "Recording one requires that some allocation under the permit be in `ALLOCATED`, `CONTESTED` or `ADJUSTED`; it supplies the `citation_code` and `cited_at`, moves the permit to `NOTICE_OF_VIOLATION`, and sets the offending allocation from `ALLOCATED` to `CONTESTED` as a side effect — the citation and the contest are the same event viewed from two angles."
    PRD §3.4: "Waiving is the municipality's alternative: it requires the measurement to be in breach and the owning permit under the same contract to be in `NOTICE_OF_VIOLATION`; it supplies a `waiver_basis`, resets `in_breach` to false, and makes the owning standard recompute its `breach_reason_code` from whatever breaching measurements remain."

    Design: Difficulty/cross_entity_state_dependency/emergency_notification_permit_transition_requires_containment_first
    """
    from test_helpers import measurement_payload, penalty_allocation_payload

    scenario = setup_operating_contract_with_permit(
        standards=[
            {
                "code": "OVF-01",
                "title": "Collection overflows",
                "metric_type": "COLLECTION_OVERFLOW",
                "criticality_weight": 0.7,
                "threshold_value": 2.0,
                "threshold_direction": "AT_MOST",
                "breach_penalty_cents": 900000,
            }
        ]
    )
    standard = scenario.std
    measurement = validate_success(
        api_client.record_measurement(
            standard["id"], measurement_payload(measured_value=5.0), scenario.con_h
        ),
        201,
    )
    assessed = validate_success(
        api_client.assess_measurement(measurement["id"], scenario.con_h)
    )
    assert assessed["in_breach"] is True, (
        "an AT_MOST standard is breached when the observed value exceeds the threshold"
    )

    allocation = validate_success(
        api_client.create_penalty_allocation(
            scenario.permit["id"],
            penalty_allocation_payload(
                violation_code="OH-OVF-2026-31", total_penalty_cents=1500000
            ),
            scenario.mun_h,
        ),
        201,
    )
    assert allocation["status"] == "ALLOCATED"

    notice = validate_success(
        api_client.record_notice_of_violation(
            scenario.permit["id"],
            {"citation_code": "OH-OVF-2026-31", "cited_at": "2026-09-15T00:00:00Z"},
            scenario.mun_h,
        )
    )
    assert notice["status"] == "NOTICE_OF_VIOLATION"

    contested = get_success_data(
        api_client.get_penalty_allocation(allocation["id"], scenario.mun_h)
    )
    assert contested["status"] == "CONTESTED", (
        "the citation moves the offending allocation from ALLOCATED to CONTESTED"
    )

    waived = validate_success(
        api_client.waive_measurement(
            measurement["id"],
            {
                "waiver_basis": (
                    "The overflow was superseded by the regulator's own notice of violation."
                )
            },
            scenario.mun_h,
        )
    )
    assert waived["status"] == "WAIVED"
    assert waived["in_breach"] is False, "waiving resets in_breach to false"
