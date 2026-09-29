"""Closing out visits, and what the goodwill pot does to the service diary.

Completion and cancellation are clock-sensitive and terminal, and the contract's
derived coverage posture decides which visit types may be booked at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    create_pm_visit_payload,
    move_clock,
    read_contract,
    read_visit,
    seed_field_engineer,
    setup_accepted_machine,
    setup_active_contract,
    setup_adjudicated_claim,
    setup_reference_data,
    setup_scheduled_visit,
)

MORNING_SLOT = {
    "start_ts": "2026-08-10T08:00:00.000Z",
    "end_ts": "2026-08-10T12:00:00.000Z",
}


def test_a_visit_cannot_be_closed_out_before_its_own_window_has_elapsed():
    """The clock still reads the first of August while the visit runs on the tenth, so
    the closeout is premature rather than mis-staffed.

    PRD: "Completing a visit is permitted from `SCHEDULED` and equally from
    `BILLABLE_HOLD`, and requires the logical clock's UTC timestamp to have reached the
    visit's `end_ts`; closing out early is refused with `ERR_VISIT_NOT_ELAPSED`."

    Design: Corner/errors/pm_visit_complete_before_end_ts_returns_422_visit_not_elapsed
    """
    env = setup_scheduled_visit(visit_overrides=dict(MORNING_SLOT))

    response = api_client.complete_pm_visit(
        env["visit"]["id"], {"findings_code": "OK"}, SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_VISIT_NOT_ELAPSED.value, 422)
    visit = read_visit(env["visit"]["id"])
    assert visit["status"] == "SCHEDULED"
    assert visit["billable"] is False

    move_clock("2026-08-10T12:00:00.000Z")
    data = validate_success(
        api_client.complete_pm_visit(
            env["visit"]["id"], {"findings_code": "OK"}, SERVICE_MANAGER
        )
    )

    assert data["status"] == "COMPLETED"
    assert data["findings_code"] == "OK"


def test_a_completed_visit_cannot_be_cancelled_to_win_the_entitlement_back():
    """COMPLETED is terminal, so the cancellation is refused and the preventive
    entitlement the visit consumed is not returned.

    PRD: "`COMPLETED` and `CANCELLED` are terminal, and any completion or cancellation
    addressed to a visit in another state is refused with `ERR_INVALID_VISIT_STATE`."

    Design: Corner/errors/pm_visit_cancel_after_completion_returns_409_invalid_visit_state
    """
    env = setup_scheduled_visit(visit_overrides=dict(MORNING_SLOT))
    move_clock("2026-08-10T13:00:00.000Z")
    validate_success(
        api_client.complete_pm_visit(
            env["visit"]["id"], {"findings_code": "OK"}, SERVICE_MANAGER
        )
    )

    response = api_client.cancel_pm_visit(env["visit"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_INVALID_VISIT_STATE.value, 409)
    assert read_visit(env["visit"]["id"])["status"] == "COMPLETED"
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 1


def test_a_cancelled_visit_hands_back_both_its_entitlement_and_its_engineer_window():
    """The replacement re-uses the cancelled visit's exact window on the same engineer
    and lands non-billable against a single included visit, so the cancelled row counts
    for neither the diary nor the entitlement.

    PRD: "Cancelled visits are excluded from the count and therefore hand their
    entitlement slot back."

    Design: Corner/calculations/cancelled_pm_visit_frees_entitlement_and_engineer_interval
    """
    env = setup_scheduled_visit(
        contract_overrides={
            "tier": "SILVER",
            "pm_visits_included": 1,
            "goodwill_budget_initial_cents": 500_000,
        },
        engineer_overrides={
            "full_name": "Dana Reyes",
            "region_code": "NA",
            "certifications": ["FILLER"],
            "travel_buffer_minutes": 60,
        },
        visit_overrides=dict(MORNING_SLOT),
    )
    cancelled_id = env["visit"]["id"]
    validate_success(api_client.cancel_pm_visit(cancelled_id, SERVICE_MANAGER))

    payload = create_pm_visit_payload(env["contract"]["id"], **MORNING_SLOT)
    payload["field_engineer_id"] = env["engineer"]["id"]
    data = validate_success(api_client.create_pm_visit(payload, SERVICE_MANAGER), 201)

    assert data["status"] == "SCHEDULED"
    assert data["billable"] is False
    assert data["findings_code"] == "NONE"
    assert read_visit(cancelled_id)["status"] == "CANCELLED"
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 1
    _rows, meta = validate_paginated(
        api_client.list_pm_visits(
            SERVICE_MANAGER,
            params={"service_contract_id": env["contract"]["id"], "status": "SCHEDULED"},
        )
    )
    assert meta["total_count"] == 1


GOLD_EXHAUSTING_CLAIM = {
    "contract_overrides": {
        "tier": "GOLD",
        "start_date": "2026-08-01",
        "end_date": "2027-07-31",
        "pm_visits_included": 2,
        "goodwill_budget_initial_cents": 300_000,
    },
    "lines": [
        {
            "line_label": "Turret bearing set",
            "amount_cents": 400_000,
            "defect_attribution_pct": 100.00,
        }
    ],
    "claim_overrides": {"failure_summary": "Turret bearing seizure"},
}


def _exhausted_contract():
    """A GOLD contract whose whole 300,000-cent pot has been consumed by one claim."""
    env = setup_accepted_machine(setup_reference_data(line={}))
    return setup_adjudicated_claim(env, **GOLD_EXHAUSTING_CLAIM)


def _pm_payload(env, engineer, start_ts, end_ts):
    payload = create_pm_visit_payload(
        env["contract"]["id"], visit_type="PM", start_ts=start_ts, end_ts=end_ts
    )
    payload["field_engineer_id"] = engineer["id"]
    return payload


def test_a_faultlessly_staffed_visit_is_refused_by_the_parent_contracts_empty_pot():
    """Certification, region, availability and the coverage window are all correct, so
    the refusal can only be coming from the contract's derived fiscal posture.

    PRD: "The fiscal gates come first in business terms even though they sit last in the
    precedence ladder: a contract whose posture is `BUDGET_EXHAUSTED` accepts no visits
    at all (`ERR_COVERAGE_EXHAUSTED`, HTTP 402), and a contract whose posture is
    `RESTRICTED` accepts preventive and remote work but refuses a `CORRECTIVE` booking
    (`ERR_POSTURE_RESTRICTED`, HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/pm_visit_blocked_by_contract_coverage_posture_returns_402
    """
    env = _exhausted_contract()
    engineer = seed_field_engineer(
        full_name="Dana Reyes",
        region_code="NA",
        certifications=["FILLER"],
        travel_buffer_minutes=60,
    )

    response = api_client.create_pm_visit(
        _pm_payload(env, engineer, "2026-08-10T08:00:00.000Z", "2026-08-10T12:00:00.000Z"),
        SERVICE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_COVERAGE_EXHAUSTED.value, 402)
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 0
    assert contract["coverage_posture"] == "BUDGET_EXHAUSTED"
    assert contract["pm_visits_used"] == 0
    rows, meta = validate_paginated(
        api_client.list_pm_visits(
            SERVICE_MANAGER, params={"service_contract_id": env["contract"]["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_same_booking_was_accepted_before_the_claim_drained_the_pot():
    """Booking the identical visit type with the identical engineer succeeds while the
    posture is still OPEN, and the appointment already on the books is put on a billable
    hold rather than cancelled when the pot empties.

    PRD: "Hop three re-derives `coverage_posture` from the new balance, and if the
    posture has just become `BUDGET_EXHAUSTED` in this request, every visit on that
    contract still sitting in `SCHEDULED` is moved to `BILLABLE_HOLD` with its
    `billable` flag set to true — the OEM keeps the appointment but the customer now
    pays for it."

    Design: Difficulty/cross_entity_state_dependency/pm_visit_blocked_by_contract_coverage_posture_returns_402
    """
    env = setup_accepted_machine(setup_reference_data(line={}))
    env = setup_active_contract(
        env, contract_overrides=dict(GOLD_EXHAUSTING_CLAIM["contract_overrides"])
    )
    engineer = seed_field_engineer(
        full_name="Dana Reyes",
        region_code="NA",
        certifications=["FILLER"],
        travel_buffer_minutes=60,
    )
    booked = validate_success(
        api_client.create_pm_visit(
            _pm_payload(env, engineer, "2026-08-10T08:00:00.000Z", "2026-08-10T12:00:00.000Z"),
            SERVICE_MANAGER,
        ),
        201,
    )
    assert booked["status"] == "SCHEDULED"
    assert booked["billable"] is False
    assert read_contract(env["contract"]["id"])["coverage_posture"] == "OPEN"

    setup_adjudicated_claim(
        env,
        lines=GOLD_EXHAUSTING_CLAIM["lines"],
        claim_overrides=GOLD_EXHAUSTING_CLAIM["claim_overrides"],
    )

    held = read_visit(booked["id"])
    assert held["status"] == "BILLABLE_HOLD"
    assert held["billable"] is True
    response = api_client.create_pm_visit(
        _pm_payload(env, engineer, "2026-08-12T08:00:00.000Z", "2026-08-12T12:00:00.000Z"),
        SERVICE_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_COVERAGE_EXHAUSTED.value, 402)


def test_a_restricted_contract_refuses_corrective_work_but_still_takes_preventive():
    """With exactly 50,000 cents left the posture is a partial block: the corrective
    booking is refused while the identical preventive booking goes through.

    PRD: "It reads `BUDGET_EXHAUSTED` when `goodwill_budget_cents` is exactly 0,
    `RESTRICTED` when the remaining pot is above 0 but no more than 50,000 cents — that
    is, five hundred dollars or less still available — and `OPEN` otherwise."

    Design: Corner/errors/corrective_visit_on_restricted_contract_returns_402_posture_restricted
    """
    env = setup_accepted_machine(setup_reference_data(line={}))
    env = setup_adjudicated_claim(
        env,
        contract_overrides={
            "tier": "SILVER",
            "start_date": "2026-08-01",
            "end_date": "2027-07-31",
            "pm_visits_included": 2,
            "goodwill_budget_initial_cents": 350_000,
        },
        lines=[
            {
                "line_label": "Nozzle block replacement",
                "amount_cents": 400_000,
                "defect_attribution_pct": 100.00,
            }
        ],
        claim_overrides={"failure_summary": "Nozzle block cracked during production"},
    )
    engineer = seed_field_engineer()

    corrective = create_pm_visit_payload(
        env["contract"]["id"],
        visit_type="CORRECTIVE",
        start_ts="2026-08-12T08:00:00.000Z",
        end_ts="2026-08-12T12:00:00.000Z",
    )
    corrective["field_engineer_id"] = engineer["id"]

    response = api_client.create_pm_visit(corrective, SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_POSTURE_RESTRICTED.value, 402)
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 50_000
    assert contract["coverage_posture"] == "RESTRICTED"

    preventive = dict(corrective, visit_type="PM")
    data = validate_success(api_client.create_pm_visit(preventive, SERVICE_MANAGER), 201)

    assert data["status"] == "SCHEDULED"
    assert data["visit_type"] == "PM"
