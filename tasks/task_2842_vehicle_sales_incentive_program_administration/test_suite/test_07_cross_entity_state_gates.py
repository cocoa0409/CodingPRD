"""Cross-entity state gates: a write is refused because of the state of a
DIFFERENT entity, and the identical call succeeds once that other entity moves.

Three entity pairs are exercised here — (Claim, RetailDelivery),
(RetailDelivery, Dealer) and (DealerObjective, IncentiveProgram).
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, BUILD_FROM, BUILD_TO, SEP_01

# --- (Claim, RetailDelivery) -------------------------------------------------

CED_CLOCK = "2026-08-08T00:00:00.000Z"


def _setup_claim_on_a_still_reported_delivery():
    """An ACTIVE CUSTOMER_CASH program, an ACTIVE dealer, one delivery left in
    REPORTED and one claim submitted against it. Claim submission does not
    require a validated delivery — only adjudication does."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-860",
        name="Willow Bend Autos",
        region_code="WEST",
        historical_volume_units=6,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CED-CASH",
            name="Cross Entity Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=130000,
            budget_cents=40000000,
            stack_group="CED",
            priority_rank=101,
            accrual_method="UNIT_BASED",
        )
    )
    fx.set_clock(CED_CLOCK)
    delivery = fx.report_delivery(
        dealer["id"],
        vin=f.unique_vin(),
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-12T00:00:00.000Z",
        msrp_cents=3150000,
        sale_date=CED_CLOCK,
        customer_region_code="WEST",
        deal_type="CASH",
    )
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 130000)
    return dealer, program, delivery, claim


def test_adjudication_is_refused_while_only_the_delivery_is_out_of_state():
    """Approving a claim whose delivery is still REPORTED is refused, and the
    refusal is a complete no-op on the impeccably SUBMITTED claim.

    PRD: "Approval further requires that the claim's delivery is in `VALIDATED`
    — a delivery still in `REPORTED`, or one rejected or unwound, is refused
    with `ERR_DELIVERY_NOT_VALIDATED` — and that the claimed program is still
    `ACTIVE`, failing which the adjudication is refused with
    `ERR_PROGRAM_NOT_ACTIVE`."
    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails."

    Design: Difficulty/cross_entity_state_dependency/claim_adjudication_blocked_until_its_delivery_is_validated
    """
    _dealer, program, delivery, claim = _setup_claim_on_a_still_reported_delivery()

    a.assert_status(delivery, "REPORTED")
    assert delivery["back_dated_flag"] is False, delivery
    a.assert_claim_dimensions(claim, "SUBMITTED", "UNPAID")

    before = validate_success(api_client.get_claim(claim["id"], fx.ADJUDICATOR))

    validate_error(
        api_client.adjudicate_claim(
            claim["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        ),
        ApiErrorId.ERR_DELIVERY_NOT_VALIDATED.value,
    )

    after = validate_success(api_client.get_claim(claim["id"], fx.ADJUDICATOR))
    a.assert_identical_entity(before, after)
    a.assert_claim_dimensions(after, "SUBMITTED", "UNPAID")
    assert after["adjudicated_by_user_id"] is None, after

    summary = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_money(summary, "committed_cents", 0)
    a.assert_int_field(summary, "claimed_units", 0)


def test_the_byte_identical_adjudication_succeeds_once_the_delivery_is_validated():
    """The only thing that changes between the refused and the accepted call is
    the delivery's own REPORTED -> VALIDATED transition.

    PRD: "Approval further requires that the claim's delivery is in `VALIDATED`
    — a delivery still in `REPORTED`, or one rejected or unwound, is refused
    with `ERR_DELIVERY_NOT_VALIDATED` — and that the claimed program is still
    `ACTIVE`, failing which the adjudication is refused with
    `ERR_PROGRAM_NOT_ACTIVE`."
    PRD: "`committed_cents` is the sum of `approved_amount_cents` over the
    program's claims whose `validation_status` is `VALIDATED` and whose
    `payment_status` is `UNPAID`, `SCHEDULED` or `PAID`, plus the sum of
    `amount_cents` over every chargeback reachable through the program's claims
    whose `status` is `WRITTEN_OFF`."

    Design: Difficulty/cross_entity_state_dependency/claim_adjudication_blocked_until_its_delivery_is_validated
    """
    _dealer, program, delivery, claim = _setup_claim_on_a_still_reported_delivery()

    payload = f.adjudicate_payload("APPROVE")
    validate_error(
        api_client.adjudicate_claim(claim["id"], payload, fx.ADJUDICATOR),
        ApiErrorId.ERR_DELIVERY_NOT_VALIDATED.value,
    )

    validated = fx.validate_delivery(delivery["id"])
    a.assert_status(validated, "VALIDATED")

    approved = validate_success(
        api_client.adjudicate_claim(claim["id"], payload, fx.ADJUDICATOR)
    )
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")
    a.assert_money(approved, "approved_amount_cents", 130000)
    assert approved["rate_basis"] == "AS_SOLD_SNAPSHOT", approved

    summary = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_money(summary, "committed_cents", 130000)
    a.assert_int_field(summary, "claimed_units", 1)
    a.assert_money(summary, "per_unit_spend_cents", 130000)


# --- (RetailDelivery, Dealer) ------------------------------------------------

STD_CLOCK = "2026-08-12T00:00:00.000Z"
STD_SALE_DATE = "2026-08-11T00:00:00.000Z"


def _setup_standing_program_and_dealer():
    """An ACTIVE CUSTOMER_CASH program and an ACTIVE WEST dealer, with the clock
    pinned so every report in this scenario has a clean reporting lag."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-870",
        name="Ridgemont Auto Sales",
        region_code="WEST",
        historical_volume_units=3,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="STD-CASH",
            name="Standing Gate Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=125000,
            budget_cents=40000000,
            stack_group="STD",
            priority_rank=111,
            accrual_method="UNIT_BASED",
        )
    )
    fx.set_clock(STD_CLOCK)
    return dealer, program


def _standing_delivery_payload(dealer_id, vin, build_date):
    return f.create_delivery_payload(
        dealer_id,
        vin=vin,
        model_code="MX5",
        trim_code="BASE",
        build_date=build_date,
        msrp_cents=3050000,
        sale_date=STD_SALE_DATE,
        customer_region_code="WEST",
        deal_type="CASH",
    )


def _report_standing_delivery(dealer_id, vin, build_date):
    return validate_success(
        api_client.create_delivery(
            _standing_delivery_payload(dealer_id, vin, build_date),
            make_dealer_headers(dealer_id),
        ),
        201,
    )


def test_suspended_standing_blocks_neither_reporting_nor_validation_nor_claiming():
    """SUSPENDED is the discriminating middle standing: it keeps the whole top of
    the funnel open, so the gate must key on TERMINATED alone.

    PRD: "A `SUSPENDED` dealer, by contrast, is **not** blocked by that rule at
    all: it keeps reporting deliveries, its deliveries keep being validated, and
    its claims keep being submitted and adjudicated normally."

    Design: Difficulty/cross_entity_state_dependency/terminated_dealer_standing_blocks_delivery_reporting_and_claim_submission
    """
    dealer, program = _setup_standing_program_and_dealer()
    a.assert_status(dealer, "ACTIVE")

    suspended = validate_success(
        api_client.set_dealer_status(
            dealer["id"],
            f.set_dealer_status_payload(
                "SUSPENDED", note="Floorplan audit in progress."
            ),
            fx.CONTROLLER,
        )
    )
    a.assert_status(suspended, "SUSPENDED")
    a.assert_version(suspended, 2)

    reported = _report_standing_delivery(
        dealer["id"], f.unique_vin(), "2026-06-19T00:00:00.000Z"
    )
    a.assert_status(reported, "REPORTED")

    validated = fx.validate_delivery(reported["id"])
    a.assert_status(validated, "VALIDATED")

    claim = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                reported["id"], program["id"], 125000, fx.program_version(program["id"])
            ),
            make_dealer_headers(dealer["id"]),
        ),
        201,
    )
    a.assert_claim_dimensions(claim, "SUBMITTED", "UNPAID")

    adjudicated = fx.adjudicate_claim(claim["id"])
    a.assert_claim_dimensions(adjudicated, "VALIDATED", "UNPAID")


def test_terminated_standing_blocks_reporting_validation_and_claim_submission():
    """A TERMINATED dealer is cut off at all three points of the funnel, and the
    gate reads the dealer's CURRENT standing rather than the standing frozen at
    the moment the delivery arrived.

    PRD: "A `TERMINATED` dealer is cut off at the top of the funnel: it may not
    report retail deliveries, none of its already-reported deliveries may be
    validated, and it may not submit claims — all three attempts are refused
    with `ERR_DEALER_NOT_IN_GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/terminated_dealer_standing_blocks_delivery_reporting_and_claim_submission
    """
    dealer, program = _setup_standing_program_and_dealer()

    active_era = _report_standing_delivery(
        dealer["id"], f.unique_vin(), "2026-06-18T00:00:00.000Z"
    )
    fx.set_dealer_status(dealer["id"], "SUSPENDED", note="Floorplan audit in progress.")
    suspended_era = _report_standing_delivery(
        dealer["id"], f.unique_vin(), "2026-06-19T00:00:00.000Z"
    )
    fx.validate_delivery(suspended_era["id"])

    terminated = validate_success(
        api_client.set_dealer_status(
            dealer["id"],
            f.set_dealer_status_payload(
                "TERMINATED", note="Franchise agreement terminated."
            ),
            fx.CONTROLLER,
        )
    )
    a.assert_status(terminated, "TERMINATED")

    third_vin = f.unique_vin()
    validate_error(
        api_client.create_delivery(
            _standing_delivery_payload(
                dealer["id"], third_vin, "2026-06-20T00:00:00.000Z"
            ),
            make_dealer_headers(dealer["id"]),
        ),
        ApiErrorId.ERR_DEALER_NOT_IN_GOOD_STANDING.value,
    )

    validate_error(
        api_client.create_claim(
            f.create_claim_payload(
                suspended_era["id"],
                program["id"],
                125000,
                fx.program_version(program["id"]),
            ),
            make_dealer_headers(dealer["id"]),
        ),
        ApiErrorId.ERR_DEALER_NOT_IN_GOOD_STANDING.value,
    )

    validate_error(
        api_client.validate_delivery(active_era["id"], fx.VALIDATOR),
        ApiErrorId.ERR_DEALER_NOT_IN_GOOD_STANDING.value,
    )
    still_reported = validate_success(
        api_client.get_delivery(active_era["id"], fx.VALIDATOR)
    )
    a.assert_status(still_reported, "REPORTED")

    rows, meta = validate_paginated(
        api_client.list_deliveries(fx.VALIDATOR, {"dealer_id": dealer["id"]})
    )
    a.assert_list_length(rows, 2, "deliveries")
    assert meta["total_count"] == 2, meta
    listed_vins = {row["vin"] for row in rows}
    assert listed_vins == {active_era["vin"], suspended_era["vin"]}, listed_vins
    assert third_vin not in listed_vins, listed_vins


# --- (DealerObjective, IncentiveProgram) -------------------------------------


def _setup_draft_stair_step_program_and_dealer():
    """A DEALER_STAIR_STEP program left in DRAFT with one NORTH/TRK9 footprint
    row, plus the dealer the objective will bind."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-880",
        name="Northgate Truck Sales",
        region_code="NORTH",
        historical_volume_units=12,
        market_opportunity_bps=2500,
    )
    program = fx.create_draft_program(
        payload=f.create_program_payload(
            program_code="OBJ-GATE",
            name="Objective Gate Stair Step",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=60000000,
            stack_group="OBJG",
            priority_rank=121,
            tier_schedule=[
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 40000}
            ],
            tier_bonus_mode="FULL_VOLUME",
        )
    )
    fx.add_eligibility_rule(
        program["id"],
        model_code="TRK9",
        region_code="NORTH",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    return dealer, fx.read_program(program["id"])


def test_neither_a_draft_nor_a_pending_program_is_a_valid_objective_parent():
    """Two of the three program states refuse the child creation with the same
    error, and neither refusal leaves a DealerObjective row behind.

    PRD: "The owning program is the one named in the path, which the objective
    records as `program_id`, and that program must be `ACTIVE`; assigning an
    objective under a program in any other status is refused with
    `ERR_PROGRAM_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/objective_creation_requires_an_active_owning_program
    """
    dealer, program = _setup_draft_stair_step_program_and_dealer()
    a.assert_status(program, "DRAFT")

    payload = f.create_objective_payload(dealer["id"], stretch_bps=0)
    validate_error(
        api_client.create_objective(program["id"], payload, fx.FSM),
        ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value,
    )

    pending = fx.submit_program(program["id"])
    a.assert_status(pending, "PENDING_APPROVAL")
    validate_error(
        api_client.create_objective(program["id"], payload, fx.FSM),
        ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value,
    )

    rows, meta = validate_paginated(
        api_client.list_program_objectives(program["id"], fx.FSM)
    )
    a.assert_list_length(rows, 0, "objectives")
    assert meta["total_count"] == 0, meta


def test_the_same_objective_creation_is_admitted_once_the_program_is_active():
    """Only ACTIVE admits the child, and the admitted objective is computed from
    the dealer's own basis and market opportunity.

    PRD: "The owning program is the one named in the path, which the objective
    records as `program_id`, and that program must be `ACTIVE`; assigning an
    objective under a program in any other status is refused with
    `ERR_PROGRAM_NOT_ACTIVE`."
    PRD: "Fourth, `objective_units` is the raw unit target rounded half-up to a
    whole number, and then raised to 1 if that rounding produced anything
    smaller — the floor of one unit guarantees that attainment can always be
    divided by the objective without a division error."

    Design: Difficulty/cross_entity_state_dependency/objective_creation_requires_an_active_owning_program
    """
    dealer, program = _setup_draft_stair_step_program_and_dealer()

    payload = f.create_objective_payload(dealer["id"], stretch_bps=0)
    validate_error(
        api_client.create_objective(program["id"], payload, fx.FSM),
        ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value,
    )
    fx.submit_program(program["id"])
    validate_error(
        api_client.create_objective(program["id"], payload, fx.FSM),
        ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value,
    )

    active = fx.approve_program(program["id"])
    a.assert_status(active, "ACTIVE")

    objective = validate_success(
        api_client.create_objective(program["id"], payload, fx.FSM), 201
    )
    a.assert_objective_shape(objective)
    a.assert_status(objective, "PROPOSED")
    a.assert_int_field(objective, "basis_units", 12)
    a.assert_int_field(objective, "objective_units", 15)
    a.assert_int_field(objective, "protest_round", 0)
    assert objective["program_id"] == program["id"], objective
    assert objective["dealer_id"] == dealer["id"], objective

    rows, meta = validate_paginated(
        api_client.list_program_objectives(program["id"], fx.FSM)
    )
    a.assert_list_length(rows, 1, "objectives")
    assert meta["total_count"] == 1, meta
    a.assert_ids_equal(rows, [objective["id"]], "objectives")
    a.assert_int_field(rows[0], "objective_units", 15)
