"""Optimistic-concurrency guards observed across entity boundaries.

Each test drives a full read-then-conflicting-write-then-retry chain and pins
both the refusal and the exact version arithmetic the retry has to work from.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

MX5_ZZOC1_FOOTPRINT = [
    {
        "model_code": "MX5",
        "region_code": "ZZOC1",
        "build_date_from": "2026-05-01T00:00:00.000Z",
        "build_date_to": "2026-07-31T00:00:00.000Z",
        "allowed_deal_types": ["CASH"],
    }
]


def _claim_staleness_world() -> dict:
    """One ACTIVE CUSTOMER_CASH program at per_unit 30000, one ACTIVE dealer and
    one VALIDATED delivery. No claims yet."""
    fx.set_clock("2026-08-18T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-OC1",
        name="OCC One Motors",
        region_code="ZZOC1",
        historical_volume_units=3,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-X-OC1",
            name="OCC One Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from="2026-08-01T00:00:00.000Z",
            effective_to="2026-09-01T00:00:00.000Z",
            per_unit_amount_cents=30000,
            budget_cents=900000,
            stack_group="CRNOC1",
            priority_rank=449,
            accrual_method="UNIT_BASED",
        ),
        rules=MX5_ZZOC1_FOOTPRINT,
    )
    delivery = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-01T00:00:00.000Z",
        msrp_cents=3000000,
        sale_date="2026-08-17T00:00:00.000Z",
        customer_region_code="ZZOC1",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery["id"])
    return {"dealer": dealer, "program": program, "delivery": delivery}


def test_a_repricing_between_the_dealers_read_and_its_claim_forces_a_re_read():
    """The dealer's in-flight submission carries the pre-repricing version and is
    refused, and the version it must resend is the one the repricing produced —
    which the successful claim then bumps again.

    PRD: "If that value does not equal the program's current `version`, the
    submission is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412) and no
    claim row is created."

    Design: Corner/cross_cutting_complexity_layers/claim_submission_carries_a_program_version_that_a_repricing_invalidates
    """
    world = _claim_staleness_world()
    program_id = world["program"]["id"]
    delivery_id = world["delivery"]["id"]
    dealer_headers = make_dealer_headers(world["dealer"]["id"])

    first_read = validate_success(api_client.get_program(program_id, dealer_headers))
    v1 = first_read["version"]
    a.assert_money(first_read, "per_unit_amount_cents", 30000)

    repricing = validate_success(
        api_client.create_repricing(
            program_id,
            f.create_repricing_payload("PROSPECTIVE", 35000, v1),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_repricing_shape(repricing)
    a.assert_money(repricing, "previous_per_unit_amount_cents", 30000)
    a.assert_int_field(repricing, "affected_claim_count", 0)
    a.assert_money(repricing, "net_adjustment_cents", 0)

    validate_error(
        api_client.create_claim(
            f.create_claim_payload(delivery_id, program_id, 30000, v1),
            dealer_headers,
        ),
        "ERR_STALE_PROGRAM_VERSION",
        412,
    )

    second_read = validate_success(api_client.get_program(program_id, dealer_headers))
    v2 = second_read["version"]
    assert v2 == v1 + 1, f"the repricing must bump the version exactly once: {v1} -> {v2}"
    a.assert_money(second_read, "per_unit_amount_cents", 35000)

    claim = validate_success(
        api_client.create_claim(
            f.create_claim_payload(delivery_id, program_id, 35000, v2),
            dealer_headers,
        ),
        201,
    )
    a.assert_claim_shape(claim)
    a.assert_money(claim, "snapshot_per_unit_cents", 35000)

    third_read = validate_success(api_client.get_program(program_id, dealer_headers))
    v3 = third_read["version"]
    assert v3 == v2 + 1, (
        f"a successful claim creation must also bump the program version: {v2} -> {v3}"
    )

    rows, meta = validate_paginated(
        api_client.list_claims(
            fx.VALIDATOR, params={"program_id": program_id, "limit": 10}
        )
    )
    assert meta["total_count"] == 1, f"the refused submission created nothing: {meta}"
    a.assert_list_length(rows, 1, "claims")
    assert rows[0]["id"] == claim["id"]


def _repricing_chain_world() -> dict:
    """One ACTIVE CUSTOMER_CASH program at per_unit 20000 and no claims at all,
    so every version movement in the chain is attributable to a repricing."""
    fx.set_clock("2026-08-18T00:00:00.000Z")
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-X-OC2",
            name="OCC Two Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from="2026-08-01T00:00:00.000Z",
            effective_to="2026-09-01T00:00:00.000Z",
            per_unit_amount_cents=20000,
            budget_cents=600000,
            stack_group="CRNOC2",
            priority_rank=450,
            accrual_method="UNIT_BASED",
        ),
        rules=[
            {
                "model_code": "SDN3",
                "region_code": "ZZOC2",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
                "allowed_deal_types": ["CASH"],
            }
        ],
    )
    return {"program": program}


def test_two_repricings_from_one_read_chain_without_a_gap_after_the_retry():
    """The second repricing authored from the same read is refused, and the retry
    records the first event's outcome as its own baseline, so the recorded
    baselines chain 20000 -> 24000 -> 26000 with no invented figure in between.

    PRD: "The event records `previous_per_unit_amount_cents` as the program's
    `per_unit_amount_cents` immediately before the write, stamps `effective_at`
    from the logical clock, and computes `month_start` as the first instant of the
    calendar month containing `effective_at`."

    Design: Corner/cross_cutting_complexity_layers/a_second_repricing_must_re_read_or_it_would_record_a_baseline_that_never_existed
    """
    program_id = _repricing_chain_world()["program"]["id"]

    first_read = validate_success(api_client.get_program(program_id, fx.DESIGNER))
    v1 = first_read["version"]
    a.assert_money(first_read, "per_unit_amount_cents", 20000)

    first_event = validate_success(
        api_client.create_repricing(
            program_id,
            f.create_repricing_payload("PROSPECTIVE", 24000, v1),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_repricing_shape(first_event)
    a.assert_money(first_event, "previous_per_unit_amount_cents", 20000)
    a.assert_money(first_event, "new_per_unit_amount_cents", 24000)
    assert first_event["effective_at"] == "2026-08-18T00:00:00.000Z", (
        f"effective_at must be stamped from the logical clock: {first_event['effective_at']!r}"
    )
    assert first_event["month_start"] == "2026-08-01T00:00:00.000Z", (
        f"month_start must be the first instant of August 2026: {first_event['month_start']!r}"
    )

    validate_error(
        api_client.create_repricing(
            program_id,
            f.create_repricing_payload("PROSPECTIVE", 26000, v1),
            fx.DESIGNER,
        ),
        "ERR_STALE_PROGRAM_VERSION",
        412,
    )

    second_read = validate_success(api_client.get_program(program_id, fx.DESIGNER))
    v2 = second_read["version"]
    assert v2 == v1 + 1, (
        f"the refused event must neither write the rate nor move the version: {v1} -> {v2}"
    )
    a.assert_money(second_read, "per_unit_amount_cents", 24000)

    second_event = validate_success(
        api_client.create_repricing(
            program_id,
            f.create_repricing_payload("PROSPECTIVE", 26000, v2),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_money(second_event, "previous_per_unit_amount_cents", 24000)
    a.assert_money(second_event, "new_per_unit_amount_cents", 26000)

    third_read = validate_success(api_client.get_program(program_id, fx.DESIGNER))
    assert third_read["version"] == v2 + 1, (
        f"the retried event must bump the version once: {v2} -> {third_read['version']}"
    )
    a.assert_money(third_read, "per_unit_amount_cents", 26000)

    rows, meta = validate_paginated(
        api_client.list_repricings(program_id, fx.CONTROLLER, params={"limit": 10})
    )
    assert meta["total_count"] == 2, (
        f"exactly two repricing events must exist, not three: {meta}"
    )
    a.assert_list_length(rows, 2, "repricing events")


def _protest_staleness_world() -> dict:
    """One ACTIVE stair-step program, one dealer with historical_volume_units 4,
    one objective with an OPEN protest claiming 3 basis units, one VALIDATED
    delivery already counted and one REPORTED delivery not yet counted."""
    fx.set_clock("2026-08-10T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-OC3",
        name="OCC Three Motors",
        region_code="ZZOC3",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_stair_step_program_payload(
            program_code="CRN-X-OC3",
            name="OCC Three Stair",
            effective_from="2026-08-01T00:00:00.000Z",
            effective_to="2026-09-01T00:00:00.000Z",
            per_unit_amount_cents=0,
            budget_cents=700000,
            stack_group="CRNOC3",
            priority_rank=451,
            tier_schedule=[
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 20000}
            ],
            tier_bonus_mode="MARGINAL",
            accrual_method="UNIT_BASED",
        ),
        rules=[
            {
                "model_code": "MX5",
                "region_code": "ZZOC3",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
                "allowed_deal_types": ["CASH"],
            }
        ],
    )
    objective = fx.assign_objective(program["id"], dealer["id"], stretch_bps=0)
    counted = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-01T00:00:00.000Z",
        msrp_cents=2500000,
        sale_date="2026-08-05T00:00:00.000Z",
        customer_region_code="ZZOC3",
        deal_type="CASH",
    )
    fx.validate_delivery(counted["id"])
    pending = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-02T00:00:00.000Z",
        msrp_cents=2500000,
        sale_date="2026-08-06T00:00:00.000Z",
        customer_region_code="ZZOC3",
        deal_type="CASH",
    )
    protest = fx.file_protest(
        objective["id"],
        dealer["id"],
        3,
        reason="One of the four historical units was a fleet sale.",
    )
    return {
        "dealer": dealer,
        "program": program,
        "objective": objective,
        "pending_delivery": pending,
        "protest": protest,
    }


def test_an_auditors_validation_invalidates_the_managers_pending_resolution():
    """The staleness arrives from another entity's write: validating a delivery
    moves the objective's attainment and version, so the manager's pending UPHELD
    decision is refused and succeeds only after a re-read.

    PRD: "A mismatch with the objective's current `version` is rejected with
    `ERR_STALE_OBJECTIVE_VERSION` (HTTP 412) and neither the protest nor the
    objective is touched."

    Design: Corner/cross_cutting_complexity_layers/validating_a_delivery_makes_an_in_flight_protest_resolution_stale
    """
    world = _protest_staleness_world()
    objective_id = world["objective"]["id"]
    protest_id = world["protest"]["id"]
    a.assert_int_field(world["objective"], "objective_units", 4)

    first_read = validate_success(api_client.get_objective(objective_id, fx.FSM))
    ov1 = first_read["version"]
    a.assert_int_field(first_read, "achieved_units", 1)
    a.assert_bps(first_read, "attainment_bps", 2500)

    validated = validate_success(
        api_client.validate_delivery(world["pending_delivery"]["id"], fx.VALIDATOR)
    )
    a.assert_status(validated, "VALIDATED")

    validate_error(
        api_client.resolve_protest(
            objective_id,
            protest_id,
            f.resolve_protest_payload("UPHELD", ov1),
            fx.FSM,
        ),
        "ERR_STALE_OBJECTIVE_VERSION",
        412,
    )

    rows, _meta = validate_paginated(
        api_client.list_protests(objective_id, fx.FSM, params={"limit": 10})
    )
    a.assert_list_length(rows, 1, "protests")
    a.assert_status(rows[0], "OPEN")
    a.assert_null_fields(rows[0], ["resolved_units"])

    second_read = validate_success(api_client.get_objective(objective_id, fx.FSM))
    ov2 = second_read["version"]
    assert ov2 == ov1 + 1, (
        f"the validation must move the objective exactly once: {ov1} -> {ov2}"
    )
    a.assert_int_field(second_read, "achieved_units", 2)
    a.assert_bps(second_read, "attainment_bps", 5000)
    a.assert_int_field(second_read, "objective_units", 4)

    resolved = validate_success(
        api_client.resolve_protest(
            objective_id,
            protest_id,
            f.resolve_protest_payload("UPHELD", ov2),
            fx.FSM,
        )
    )
    a.assert_protest_shape(resolved)
    a.assert_status(resolved, "UPHELD")
    a.assert_int_field(resolved, "resolved_units", 3)

    third_read = validate_success(api_client.get_objective(objective_id, fx.FSM))
    assert third_read["version"] == ov2 + 1, (
        f"the resolution must bump the objective once: {ov2} -> {third_read['version']}"
    )
    a.assert_status(third_read, "REVISED")
    a.assert_int_field(third_read, "objective_units", 3)
    a.assert_objective_attainment(third_read, 2, 6666, 0, 0)
