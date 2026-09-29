"""Write responses are already the settled state, across aggregates.

Nothing in these chains needs a retry, a sleep or a second read to become true:
each write body is compared field-for-field with the read that follows it, and
each parent aggregate is checked on its FIRST read after the write.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import USER_AUDITOR_1


def _consistency_world() -> dict:
    """One ACTIVE CUSTOMER_CASH program at per_unit 45000 with budget 500000, one
    ACTIVE dealer, one VALIDATED delivery, one SUBMITTED claim and one OPEN batch,
    keeping the approval and validation write bodies for comparison."""
    fx.set_clock("2026-08-21T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-CON",
        name="Consistent Motors",
        region_code="ZZCON",
        historical_volume_units=2,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program_with_rules(
        f.create_program_payload(
            program_code="CRN-X-CON",
            name="Consistent Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from="2026-08-01T00:00:00.000Z",
            effective_to="2026-09-01T00:00:00.000Z",
            per_unit_amount_cents=45000,
            budget_cents=500000,
            stack_group="CRNCON",
            priority_rank=452,
            accrual_method="UNIT_BASED",
        ),
        rules=[
            {
                "model_code": "MX5",
                "region_code": "ZZCON",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
                "allowed_deal_types": ["CASH"],
            }
        ],
    )
    fx.submit_program(program["id"])
    approved = validate_success(
        api_client.approve_program(program["id"], fx.CONTROLLER)
    )
    # Read the program back immediately, before the claim submission below moves
    # its version again ("the claimed program's version increments by 1"), so the
    # comparison stays a write-body-versus-its-own-following-read check.
    approve_read = get_success_data(api_client.get_program(program["id"], fx.CONTROLLER))
    delivery = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-01T00:00:00.000Z",
        msrp_cents=3400000,
        sale_date="2026-08-20T00:00:00.000Z",
        customer_region_code="ZZCON",
        deal_type="CASH",
    )
    validated = validate_success(
        api_client.validate_delivery(delivery["id"], fx.VALIDATOR)
    )
    dealer_headers = make_dealer_headers(dealer["id"])
    program_version = get_success_data(
        api_client.get_program(program["id"], dealer_headers)
    )["version"]
    claim = get_success_data(
        api_client.create_claim(
            f.create_claim_payload(delivery["id"], program["id"], 45000, program_version),
            dealer_headers,
        )
    )
    batch = get_success_data(
        api_client.create_payment_batch(
            f.create_payment_batch_payload(
                batch_code="CRN-B-CON",
                region_code="ZZCON",
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-08-31T00:00:00.000Z",
                scheduled_pay_date="2026-08-31T00:00:00.000Z",
            ),
            fx.CONTROLLER,
        )
    )
    return {
        "dealer": dealer,
        "program": program,
        "approved": approved,
        "approve_read": approve_read,
        "delivery": validated,
        "claim": claim,
        "batch": batch,
    }


def test_each_write_body_already_equals_the_read_that_follows_it():
    """A five-write chain: every action response is already the post-transition
    state of its own resource, and every parent aggregate — program projection,
    batch, claim, dealer — is current on its first read afterwards.

    PRD: "The rule for all of them is that a cascade is **complete and
    immediate**: by the time a response is returned, every derived field on every
    affected entity reflects the operation, every affected entity's `version` has
    incremented by 1 and its `updated_at` has been refreshed, and no follow-up
    call is needed to settle the books."

    Design: Corner/consistency_model/every_write_response_already_equals_the_read_that_follows_it
    """
    world = _consistency_world()
    program_id = world["program"]["id"]
    claim_id = world["claim"]["id"]
    batch_id = world["batch"]["id"]

    # Write 1: the approval body is already the ACTIVE program.
    approve_read = world["approve_read"]
    a.assert_status(world["approved"], "ACTIVE")
    a.assert_echoes(world["approved"], approve_read, ["status", "version"])

    # Write 2: the validation body is already the VALIDATED delivery.
    validate_read = validate_success(
        api_client.get_delivery(world["delivery"]["id"], fx.VALIDATOR)
    )
    a.assert_status(world["delivery"], "VALIDATED")
    assert world["delivery"]["validated_by_user_id"] == USER_AUDITOR_1
    a.assert_echoes(
        world["delivery"],
        validate_read,
        ["status", "validated_by_user_id", "version"],
    )

    # Write 3: adjudication computes the money inside the write response.
    adjudicated = validate_success(
        api_client.adjudicate_claim(
            claim_id, f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )
    a.assert_money(adjudicated, "approved_amount_cents", 45000)
    a.assert_claim_dimensions(adjudicated, "VALIDATED", "UNPAID")
    assert adjudicated["rate_basis"] == "AS_SOLD_SNAPSHOT", adjudicated["rate_basis"]
    adjudicate_read = validate_success(api_client.get_claim(claim_id, fx.ADJUDICATOR))
    a.assert_echoes(
        adjudicated,
        adjudicate_read,
        ["approved_amount_cents", "validation_status", "rate_basis", "version"],
    )

    # The cross-aggregate projection is right on its FIRST read after the write.
    summary = validate_success(api_client.get_spend_summary(program_id, fx.CONTROLLER))
    a.assert_money(summary, "committed_cents", 45000)
    a.assert_int_field(summary, "claimed_units", 1)
    a.assert_money(summary, "per_unit_spend_cents", 45000)

    # Write 4: scheduling recomputes the batch totals inside its own response,
    # and the child claim already reflects a write addressed to the parent.
    scheduled = validate_success(
        api_client.schedule_claims(
            batch_id, f.schedule_claims_payload([claim_id]), fx.CONTROLLER
        )
    )
    a.assert_int_field(scheduled, "claim_count", 1)
    a.assert_money(scheduled, "total_cents", 45000)
    schedule_read = validate_success(api_client.get_payment_batch(batch_id, fx.CONTROLLER))
    a.assert_echoes(scheduled, schedule_read, ["claim_count", "total_cents", "version"])
    scheduled_claim = validate_success(api_client.get_claim(claim_id, fx.CONTROLLER))
    a.assert_claim_dimensions(scheduled_claim, "VALIDATED", "SCHEDULED")
    assert scheduled_claim["payment_batch_id"] == batch_id

    # Write 5: lock, then disburse at the scheduled pay date.
    locked = validate_success(api_client.lock_batch(batch_id, fx.CONTROLLER))
    a.assert_status(locked, "LOCKED")

    fx.set_clock("2026-08-31T00:00:00.000Z")
    disbursed = validate_success(api_client.disburse_batch(batch_id, fx.CONTROLLER))
    a.assert_status(disbursed, "DISBURSED")
    assert disbursed["disbursed_at"] == "2026-08-31T00:00:00.000Z", (
        f"disbursed_at must be stamped from the logical clock: {disbursed['disbursed_at']!r}"
    )
    a.assert_money(disbursed, "total_cents", 45000)
    disburse_read = validate_success(api_client.get_payment_batch(batch_id, fx.CONTROLLER))
    a.assert_echoes(disbursed, disburse_read, ["status", "disbursed_at", "total_cents"])

    # Two further aggregates are current on their first read as well.
    paid_claim = validate_success(api_client.get_claim(claim_id, fx.CONTROLLER))
    a.assert_claim_dimensions(paid_claim, "VALIDATED", "PAID")
    assert paid_claim["paid_at"] == "2026-08-31T00:00:00.000Z", paid_claim["paid_at"]
    paid_dealer = validate_success(
        api_client.get_dealer(world["dealer"]["id"], fx.CONTROLLER)
    )
    a.assert_dealer_money(paid_dealer, 45000, 0)


def _born_reconciled_world() -> dict:
    """One ACTIVE stair-step program (single tier at 8000 bps paying 20000 per
    unit, MARGINAL), one dealer with historical_volume_units 4, and four reported
    deliveries of which the first two are already VALIDATED. No objective yet."""
    fx.set_clock("2026-08-08T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-BRN",
        name="Born Reconciled Motors",
        region_code="ZZBRN",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_stair_step_program_payload(
            program_code="CRN-X-BRN",
            name="Born Reconciled Stair",
            effective_from="2026-08-01T00:00:00.000Z",
            effective_to="2026-09-01T00:00:00.000Z",
            per_unit_amount_cents=0,
            budget_cents=600000,
            stack_group="CRNBRN",
            priority_rank=453,
            tier_schedule=[
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 20000}
            ],
            tier_bonus_mode="MARGINAL",
            accrual_method="UNIT_BASED",
        ),
        rules=[
            {
                "model_code": "MX5",
                "region_code": "ZZBRN",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
                "allowed_deal_types": ["CASH"],
            }
        ],
    )
    deliveries = []
    for build_date, sale_date in (
        ("2026-06-01T00:00:00.000Z", "2026-08-03T00:00:00.000Z"),
        ("2026-06-02T00:00:00.000Z", "2026-08-04T00:00:00.000Z"),
        ("2026-06-03T00:00:00.000Z", "2026-08-05T00:00:00.000Z"),
        ("2026-06-04T00:00:00.000Z", "2026-08-06T00:00:00.000Z"),
    ):
        deliveries.append(
            fx.report_delivery(
                dealer["id"],
                model_code="MX5",
                trim_code="BASE",
                build_date=build_date,
                msrp_cents=2400000,
                sale_date=sale_date,
                customer_region_code="ZZBRN",
                deal_type="CASH",
            )
        )
    fx.validate_delivery(deliveries[0]["id"])
    fx.validate_delivery(deliveries[1]["id"])
    return {"dealer": dealer, "program": program, "deliveries": deliveries}


def test_a_new_objective_is_born_reconciled_with_earlier_validated_deliveries():
    """The creation response itself already carries achieved_units 2 and the
    matching attainment, and each later validation moves the objective inside a
    request whose own body is a delivery.

    PRD: "It is not, however, born at zero attainment: creation immediately
    computes `achieved_units` from the dealer's deliveries that are already
    `VALIDATED`, and derives `attainment_bps`, `tier_attained` and `payout_cents`
    from that count by the tier arithmetic of §3.7."

    Design: Corner/consistency_model/a_new_objective_is_born_already_reconciled_with_deliveries_that_predate_it
    """
    world = _born_reconciled_world()
    program_id = world["program"]["id"]

    created = validate_success(
        api_client.create_objective(
            program_id,
            f.create_objective_payload(world["dealer"]["id"], stretch_bps=0),
            fx.FSM,
        ),
        201,
    )
    a.assert_objective_shape(created)
    a.assert_int_field(created, "basis_units", 4)
    a.assert_int_field(created, "objective_units", 4)
    a.assert_objective_attainment(created, 2, 5000, 0, 0)
    created_version = created["version"]

    # The follow-up read adds nothing the write body did not already carry.
    first_read = validate_success(api_client.get_objective(created["id"], fx.FSM))
    a.assert_echoes(
        created,
        first_read,
        ["achieved_units", "attainment_bps", "tier_attained", "payout_cents", "version"],
    )

    third = validate_success(
        api_client.validate_delivery(world["deliveries"][2]["id"], fx.VALIDATOR)
    )
    a.assert_status(third, "VALIDATED")
    mid_read = validate_success(api_client.get_objective(created["id"], fx.FSM))
    a.assert_objective_attainment(mid_read, 3, 7500, 0, 0)
    a.assert_version(mid_read, created_version + 1)

    fourth = validate_success(
        api_client.validate_delivery(world["deliveries"][3]["id"], fx.VALIDATOR)
    )
    a.assert_status(fourth, "VALIDATED")
    final_read = validate_success(api_client.get_objective(created["id"], fx.FSM))
    a.assert_objective_attainment(final_read, 4, 10000, 1, 20000)
    a.assert_version(final_read, created_version + 2)

    rows, meta = validate_paginated(
        api_client.list_objectives(
            fx.FSM, params={"program_id": program_id, "status": "PROPOSED", "limit": 10}
        )
    )
    assert meta["total_count"] == 1, f"exactly one objective must exist: {meta}"
    a.assert_list_length(rows, 1, "objectives")
    a.assert_money(rows[0], "payout_cents", 20000)
