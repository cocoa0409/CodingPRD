"""State machines of the incentive program, the dealer objective, the retail
delivery, the payment batch and the claim's two parallel dimensions.

Every test builds its own world from an empty database, because the server is
restarted before each test and the logical clock is reset with it.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, BUILD_FROM, BUILD_TO, SEP_01
from test_helpers.test_users import (
    USER_CONTROLLER,
    USER_DESIGNER,
    USER_DESIGNER_2,
    USER_FSM,
    make_program_designer_headers,
)

# Instants used by the recipes below, each a full ISO 8601 UTC instant with
# three fractional-second digits.
AUG_04 = "2026-08-04T00:00:00.000Z"
AUG_05 = "2026-08-05T00:00:00.000Z"
AUG_06 = "2026-08-06T00:00:00.000Z"
AUG_15 = "2026-08-15T00:00:00.000Z"
AUG_20 = "2026-08-20T00:00:00.000Z"
JUN_01 = "2026-06-01T00:00:00.000Z"
JUN_02 = "2026-06-02T00:00:00.000Z"

# The four write triggers of the program machine, with the role authorized to
# fire each one.
PROGRAM_TRIGGERS = {
    "submit": (api_client.submit_program, fx.DESIGNER),
    "revise": (api_client.revise_program, fx.DESIGNER),
    "approve": (api_client.approve_program, fx.CONTROLLER),
    "close": (api_client.close_program, fx.CONTROLLER),
}

MX5_WEST_CASH = {
    "model_code": "MX5",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["CASH"],
}


def _fire(trigger, program_id):
    """Fire one program trigger with the role authorized to call it."""
    method, headers = PROGRAM_TRIGGERS[trigger]
    return method(program_id, headers)


def test_submit_moves_a_draft_program_to_pending_approval_and_stamps_the_submitter():
    """A DRAFT program with one eligibility row submits, stamping the caller and bumping version.

    PRD: "On success the caller's `X-User-ID` is written to `submitted_by_user_id`
    and the program's `version` increments by 1." The approver field is not
    pre-filled, because "The audit fields `submitted_by_user_id` and
    `approved_by_user_id` both begin as null."

    Design: Corner/state_machines/submit_moves_a_draft_program_to_pending_approval_and_stamps_the_submitter
    """
    fx.set_clock(AUG_01)
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-1",
        name="Submit Happy",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNSM",
        priority_rank=301,
        accrual_method="UNIT_BASED",
    ))
    a.assert_status(program, "DRAFT")
    a.assert_version(program, 1)
    a.assert_null_fields(program, ["submitted_by_user_id", "approved_by_user_id"])
    fx.add_eligibility_rule(program["id"], **MX5_WEST_CASH)
    before = fx.read_program(program["id"])

    submitted = validate_success(api_client.submit_program(program["id"], fx.DESIGNER))

    a.assert_status(submitted, "PENDING_APPROVAL")
    assert submitted["submitted_by_user_id"] == USER_DESIGNER, (
        "submitted_by_user_id is taken from X-User-ID, never from a body field"
    )
    a.assert_null_fields(submitted, ["approved_by_user_id"])
    a.assert_version(submitted, before["version"] + 1)


@pytest.mark.parametrize("case", [
    "no_eligibility_footprint_row",
    "stair_step_without_tier_schedule",
    "lease_support_without_residual_support",
])
def test_submit_without_an_eligibility_rule_is_refused(case):
    """Each unmet submission precondition is a 409 refusal that leaves the DRAFT untouched.

    PRD: "The submission is admitted only when the program is in `DRAFT`, when the
    program has at least one eligibility footprint row, and when `effective_to` is
    strictly later than `effective_from`. Two type-specific gates apply: a program
    whose `incentive_type` is `DEALER_STAIR_STEP` must have at least one element in
    its `tier_schedule`, and a program whose `incentive_type` is `LEASE_SUPPORT`
    must have a `residual_support_bps` strictly greater than 0."

    Design: Corner/state_machines/submit_without_an_eligibility_rule_is_refused
    """
    fx.set_clock(AUG_01)
    if case == "no_eligibility_footprint_row":
        payload = f.create_program_payload(
            program_code="CRN-SM-2A",
            name="No Rules",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=100000,
            budget_cents=12000000,
            stack_group="CRNSM",
            priority_rank=302,
            accrual_method="UNIT_BASED",
        )
        rule = None
    elif case == "stair_step_without_tier_schedule":
        payload = f.create_program_payload(
            program_code="CRN-SM-2B",
            name="No Tiers",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=12000000,
            stack_group="CRNSM",
            priority_rank=303,
            tier_bonus_mode="MARGINAL",
        )
        rule = {
            "model_code": "TRK9",
            "region_code": "NORTH",
            "build_date_from": BUILD_FROM,
            "build_date_to": BUILD_TO,
            "allowed_deal_types": ["CASH"],
        }
    else:
        payload = f.create_program_payload(
            program_code="CRN-SM-2C",
            name="No Residual",
            incentive_type="LEASE_SUPPORT",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            residual_support_bps=0,
            budget_cents=12000000,
            stack_group="CRNSM",
            priority_rank=304,
            accrual_method="UNIT_BASED",
        )
        rule = {
            "model_code": "SDN3",
            "region_code": "SOUTH",
            "build_date_from": BUILD_FROM,
            "build_date_to": BUILD_TO,
            "allowed_deal_types": ["LEASE"],
        }

    program = fx.create_draft_program(payload)
    if rule is not None:
        fx.add_eligibility_rule(program["id"], **rule)
    before = fx.read_program(program["id"])

    validate_error(
        api_client.submit_program(program["id"], fx.DESIGNER),
        "ERR_PROGRAM_INVALID_STATE",
    )

    after = fx.read_program(program["id"])
    a.assert_status(after, "DRAFT")
    a.assert_version(after, before["version"])
    a.assert_null_fields(after, ["submitted_by_user_id"])


@pytest.mark.parametrize(("source_state", "trigger"), [
    ("DRAFT", "approve"),
    ("DRAFT", "close"),
    ("PENDING_APPROVAL", "close"),
    ("ACTIVE", "submit"),
    ("ACTIVE", "revise"),
])
def test_approve_from_draft_and_close_from_pending_approval_are_invalid_transitions(
        source_state, trigger):
    """A trigger absent from the source state's edge list is refused, moving nothing.

    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails." Rung ten is "the target resource is in a state
    from which the requested transition is declared, else the invalid-state code
    of that entity", and for approval the PRD is explicit: "The program must be in
    `PENDING_APPROVAL`; approval from any other status is
    `ERR_PROGRAM_INVALID_STATE`."

    Design: Corner/state_machines/approve_from_draft_and_close_from_pending_approval_are_invalid_transitions
    """
    fx.set_clock(AUG_01)
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-3",
        name="Invalid Triggers",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNSM",
        priority_rank=305,
        accrual_method="UNIT_BASED",
    ))
    fx.add_eligibility_rule(
        program["id"],
        model_code="MX5",
        region_code="EAST",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    if source_state in ("PENDING_APPROVAL", "ACTIVE"):
        pending = fx.submit_program(program["id"])
        a.assert_status(pending, "PENDING_APPROVAL")
    if source_state == "ACTIVE":
        active = fx.approve_program(program["id"])
        a.assert_status(active, "ACTIVE")
    before = fx.read_program(program["id"])
    a.assert_status(before, source_state)

    validate_error(_fire(trigger, program["id"]), "ERR_PROGRAM_INVALID_STATE")

    after = fx.read_program(program["id"])
    a.assert_status(after, source_state)
    a.assert_version(after, before["version"])


def test_newly_created_entities_start_in_their_declared_initial_state():
    """A fresh program, delivery, batch, objective and dealer each land on their declared seed state.

    PRD: "On creation the program's `status` is `DRAFT`, its `version` is 1, and
    every derived money and unit field is initialized to 0: `committed_cents`,
    `paid_cents`, `accrued_budget_cents`, `claimed_units`, `per_unit_spend_cents`
    and `residual_impact_bps`." Likewise "A new batch begins with `status` `OPEN`,
    `claim_count` of 0, `total_cents` of 0, `held_claim_count` of 0 and a null
    `disbursed_at`.", "The freshly proposed objective has `status` `PROPOSED`,
    `protest_round` of 0 and `paid_payout_cents` of 0." and "A newly registered
    dealer has `status` `ACTIVE`, `paid_cents` of 0 and `open_chargeback_cents` of 0."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-INIT",
        name="Initial State Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    a.assert_status(dealer, "ACTIVE")

    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-4",
        name="Initial Stair",
        incentive_type="DEALER_STAIR_STEP",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        budget_cents=12000000,
        stack_group="CRNSM",
        priority_rank=306,
        tier_schedule=[
            {"tier_index": 1, "threshold_bps": 5000, "per_unit_bonus_cents": 20000},
        ],
        tier_bonus_mode="MARGINAL",
    ))
    a.assert_status(program, "DRAFT")
    fx.add_eligibility_rule(program["id"], **MX5_WEST_CASH)
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])

    objective = validate_success(
        api_client.create_objective(
            program["id"], f.create_objective_payload(dealer["id"], stretch_bps=0), fx.FSM
        ),
        201,
    )
    delivery = validate_success(
        api_client.create_delivery(
            f.create_delivery_payload(
                dealer["id"],
                model_code="MX5",
                trim_code="BASE",
                build_date=JUN_01,
                msrp_cents=3100000,
                sale_date=AUG_01,
                customer_region_code="WEST",
                deal_type="CASH",
            ),
            make_dealer_headers(dealer["id"]),
        ),
        201,
    )
    batch = validate_success(
        api_client.create_payment_batch(
            f.create_payment_batch_payload(
                batch_code="CRN-B-INIT",
                region_code="WEST",
                period_start=AUG_01,
                period_end=AUG_15,
                scheduled_pay_date=AUG_20,
            ),
            fx.CONTROLLER,
        ),
        201,
    )

    a.assert_status(objective, "PROPOSED")
    a.assert_int_field(objective, "protest_round", 0)
    a.assert_int_field(objective, "achieved_units", 0)
    a.assert_money(objective, "paid_payout_cents", 0)
    a.assert_status(delivery, "REPORTED")
    a.assert_status(batch, "OPEN")
    a.assert_int_field(batch, "claim_count", 0)
    a.assert_money(batch, "total_cents", 0)
    a.assert_int_field(batch, "held_claim_count", 0)
    a.assert_null_fields(batch, ["disbursed_at"])


@pytest.mark.parametrize("trigger", ["submit", "revise", "approve", "close"])
def test_closed_and_superseded_programs_refuse_every_further_transition(trigger):
    """A CLOSED program refuses all four write triggers and its version stops moving.

    PRD: "Both `SUPERSEDED` and `CLOSED` are terminal program states, and no
    transition leads out of either one."

    Design: Corner/state_machines/closed_and_superseded_programs_refuse_every_further_transition
    """
    fx.set_clock(AUG_01)
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-5",
        name="Terminal Lockdown",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNSM",
        priority_rank=307,
        accrual_method="UNIT_BASED",
    ))
    fx.add_eligibility_rule(
        program["id"],
        model_code="MX5",
        region_code="CENTRAL",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])
    closed = fx.close_program(program["id"], closure_note="end of program")
    a.assert_status(closed, "CLOSED")

    validate_error(_fire(trigger, program["id"]), "ERR_PROGRAM_INVALID_STATE")

    # A terminal program is frozen, not deleted: the read still answers 200.
    after = validate_success(api_client.get_program(program["id"], fx.CONTROLLER))
    a.assert_status(after, "CLOSED")
    a.assert_version(after, closed["version"])


def test_repeating_a_completed_transition_is_refused_rather_than_silently_accepted():
    """A second validate on a VALIDATED delivery is refused and does not re-credit the objective.

    PRD: "The delivery must be in `REPORTED`; validating a delivery in any other
    status is refused with `ERR_DELIVERY_INVALID_STATE`." The refusal is total,
    because "no side effect of any kind is applied to any entity once a check fails."

    Design: Corner/state_machines/repeating_a_completed_transition_is_refused_rather_than_silently_accepted
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-IDEM",
        name="Idempotency Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-6",
        name="Idempotency Stair",
        incentive_type="DEALER_STAIR_STEP",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        budget_cents=12000000,
        stack_group="CRNSM",
        priority_rank=308,
        tier_schedule=[
            {"tier_index": 1, "threshold_bps": 2500, "per_unit_bonus_cents": 20000},
        ],
        tier_bonus_mode="MARGINAL",
    ))
    fx.add_eligibility_rule(program["id"], **MX5_WEST_CASH)
    pending = fx.submit_program(program["id"])
    a.assert_status(pending, "PENDING_APPROVAL")
    fx.approve_program(program["id"])
    objective = fx.assign_objective(program["id"], dealer["id"], stretch_bps=0)
    a.assert_int_field(objective, "objective_units", 4)
    delivery = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date=JUN_01,
        msrp_cents=3100000,
        sale_date=AUG_01,
        customer_region_code="WEST",
        deal_type="CASH",
    )

    first = fx.validate_delivery(delivery["id"])
    a.assert_status(first, "VALIDATED")
    objective_once = fx.read_objective(objective["id"])
    # objective_units 4, attainment 2500 bps, tier 1 attained inclusively.
    a.assert_int_field(objective_once, "achieved_units", 1)
    a.assert_bps(objective_once, "attainment_bps", 2500)
    a.assert_int_field(objective_once, "tier_attained", 1)
    a.assert_money(objective_once, "payout_cents", 20000)

    validate_error(
        api_client.validate_delivery(delivery["id"], fx.VALIDATOR),
        "ERR_DELIVERY_INVALID_STATE",
    )

    delivery_after = fx.read_delivery(delivery["id"])
    a.assert_status(delivery_after, "VALIDATED")
    a.assert_version(delivery_after, first["version"])
    objective_twice = fx.read_objective(objective["id"])
    a.assert_int_field(objective_twice, "achieved_units", 1)
    a.assert_money(objective_twice, "payout_cents", 20000)
    a.assert_version(objective_twice, objective_once["version"])


def test_revise_resubmit_loop_reopens_the_program_and_resets_the_approval_baseline():
    """Two laps of the DRAFT/PENDING_APPROVAL cycle clear the submitter each time while version only rises.

    PRD: "The revision clears `submitted_by_user_id` back to null, so that the next
    submission re-establishes the segregation-of-duties baseline from scratch, and
    increments `version` by 1." The loop has no lap limit, because "a program may
    be submitted, revised and re-submitted without limit, and each re-submission
    re-runs the overlap check against the world as it stands at that moment rather
    than against the world at first submission."

    Design: Corner/state_machines/revise_resubmit_loop_reopens_the_program_and_resets_the_approval_baseline
    """
    fx.set_clock(AUG_01)
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-7",
        name="Revision Loop",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNSM",
        priority_rank=309,
        accrual_method="UNIT_BASED",
    ))
    a.assert_version(program, 1)
    fx.add_eligibility_rule(
        program["id"],
        model_code="MX5",
        region_code="SOUTH",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    program_id = program["id"]
    designer_2 = make_program_designer_headers(USER_DESIGNER_2)
    baseline = fx.read_program(program_id)["version"]

    s1 = validate_success(api_client.submit_program(program_id, fx.DESIGNER))
    s2 = validate_success(api_client.revise_program(
        program_id, fx.DESIGNER, {"revision_note": "budget too small"}))
    s3 = validate_success(api_client.submit_program(program_id, designer_2))
    s4 = validate_success(api_client.revise_program(program_id, designer_2))
    s5 = validate_success(api_client.submit_program(program_id, fx.DESIGNER))
    s6 = validate_success(api_client.approve_program(program_id, fx.CONTROLLER))

    trace = [step["status"] for step in (s1, s2, s3, s4, s5, s6)]
    assert trace == [
        "PENDING_APPROVAL", "DRAFT", "PENDING_APPROVAL", "DRAFT",
        "PENDING_APPROVAL", "ACTIVE",
    ], f"unexpected state trace {trace}"
    assert s1["submitted_by_user_id"] == USER_DESIGNER
    a.assert_null_fields(s2, ["submitted_by_user_id"])
    assert s3["submitted_by_user_id"] == USER_DESIGNER_2
    a.assert_null_fields(s4, ["submitted_by_user_id"])
    assert s5["submitted_by_user_id"] == USER_DESIGNER
    # Version is monotonic across the cycle and never resets with the state.
    versions = [step["version"] for step in (s1, s2, s3, s4, s5, s6)]
    assert versions == [baseline + n for n in range(1, 7)], (
        f"expected six consecutive increments from {baseline}, got {versions}"
    )
    # The segregation-of-duties precondition reads the CURRENT submitter.
    assert s6["approved_by_user_id"] == USER_CONTROLLER
    assert s6["approved_by_user_id"] != s5["submitted_by_user_id"]


def test_approving_a_successor_supersedes_its_predecessor_and_rejects_the_predecessors_open_claims():
    """Approving the successor supersedes the predecessor, rejects its SUBMITTED claim and re-runs its ledger.

    PRD: "The first link drives the referenced program `ACTIVE → SUPERSEDED`. The
    second link, caused by the first rather than by the approval itself, walks
    every claim of the superseded program whose `validation_status` is `SUBMITTED`
    and drives each one to `validation_status` `REJECTED`, recording
    `ERR_PROGRAM_NOT_ACTIVE` in its `rejection_error_id`."

    Design: Corner/state_machines/approving_a_successor_supersedes_its_predecessor_and_rejects_the_predecessors_open_claims
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-SUP",
        name="Supersede Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    prog_a = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SUP-A",
        name="Predecessor Cash",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=130000,
        budget_cents=12000000,
        stack_group="CRNSUP",
        priority_rank=310,
        accrual_method="UNIT_BASED",
    ))
    fx.add_eligibility_rule(prog_a["id"], **MX5_WEST_CASH)
    fx.submit_program(prog_a["id"])
    fx.approve_program(prog_a["id"])

    fx.set_clock(AUG_05)
    delivery_1 = fx.report_delivery(
        dealer["id"], model_code="MX5", trim_code="BASE", build_date=JUN_01,
        msrp_cents=3100000, sale_date=AUG_04, customer_region_code="WEST",
        deal_type="CASH",
    )
    delivery_2 = fx.report_delivery(
        dealer["id"], model_code="MX5", trim_code="BASE", build_date=JUN_02,
        msrp_cents=3100000, sale_date=AUG_04, customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery_1["id"])
    fx.validate_delivery(delivery_2["id"])

    claim_1 = fx.submit_claim(dealer["id"], delivery_1["id"], prog_a["id"], 130000)
    adjudicated_1 = fx.adjudicate_claim(claim_1["id"], "APPROVE")
    a.assert_money(adjudicated_1, "approved_amount_cents", 130000)
    before = fx.read_program(prog_a["id"])
    a.assert_money(before, "committed_cents", 130000)
    a.assert_int_field(before, "claimed_units", 1)
    a.assert_money(before, "per_unit_spend_cents", 130000)

    claim_2 = fx.submit_claim(dealer["id"], delivery_2["id"], prog_a["id"], 130000)
    a.assert_claim_dimensions(claim_2, "SUBMITTED", "UNPAID")

    prog_b = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SUP-B",
        name="Successor Cash",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_06,
        effective_to=SEP_01,
        per_unit_amount_cents=90000,
        budget_cents=12000000,
        stack_group="CRNSUP",
        priority_rank=311,
        accrual_method="UNIT_BASED",
        supersedes_program_id=prog_a["id"],
    ))
    assert prog_b["supersedes_program_id"] == prog_a["id"]
    # The successor's footprint names a different model, so the two programs'
    # eligibility footprints do not intersect and the overlap check the PRD runs
    # on submission has nothing to report.
    fx.add_eligibility_rule(
        prog_b["id"],
        model_code="TRK9",
        region_code="WEST",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    pending_b = fx.submit_program(prog_b["id"])
    a.assert_status(pending_b, "PENDING_APPROVAL")

    approved_b = validate_success(api_client.approve_program(prog_b["id"], fx.CONTROLLER))

    a.assert_status(approved_b, "ACTIVE")
    after = fx.read_program(prog_a["id"], fx.CONTROLLER)
    a.assert_status(after, "SUPERSEDED")
    claim_2_after = fx.read_claim(claim_2["id"])
    a.assert_claim_dimensions(claim_2_after, "REJECTED", "UNPAID")
    assert claim_2_after["rejection_error_id"] == "ERR_PROGRAM_NOT_ACTIVE"
    a.assert_money(claim_2_after, "approved_amount_cents", 0)
    # An already-adjudicated claim of the superseded program is not clawed back.
    claim_1_after = fx.read_claim(claim_1["id"])
    a.assert_claim_dimensions(claim_1_after, "VALIDATED", "UNPAID")
    a.assert_money(claim_1_after, "approved_amount_cents", 130000)
    # The ledger genuinely re-runs, and the correct answer is unchanged because a
    # SUBMITTED claim was never in the committed input set.
    a.assert_money(after, "committed_cents", 130000)
    a.assert_int_field(after, "claimed_units", 1)
    a.assert_money(after, "per_unit_spend_cents", 130000)


def test_closing_a_program_voids_its_open_objectives_and_leaves_finalized_ones_alone():
    """Closure voids the PROPOSED objective and does not touch the FINAL one, not even its version.

    PRD: "Closure runs a conditional cascade over the program's dealer objectives:
    every objective whose `status` is `PROPOSED`, `PROTESTED` or `REVISED`
    transitions to `VOID`, while objectives already in `FINAL` or `VOID` are left
    untouched. Each objective that is voided has its `payout_cents` set to 0 and
    drives every one of its protests whose `status` is `OPEN` to `DENIED` with
    `resolved_units` left null, and each voided objective's `version` increments by 1."

    Design: Corner/state_machines/closing_a_program_voids_its_open_objectives_and_leaves_finalized_ones_alone
    """
    fx.set_clock(AUG_01)
    dealer_1 = fx.register_dealer(
        dealer_code="CRN-D-CD1",
        name="Cascade Dealer One",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    dealer_2 = fx.register_dealer(
        dealer_code="CRN-D-CD2",
        name="Cascade Dealer Two",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-CD",
        name="Cascade Down Stair",
        incentive_type="DEALER_STAIR_STEP",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        budget_cents=12000000,
        stack_group="CRNCD",
        priority_rank=312,
        tier_schedule=[
            {"tier_index": 1, "threshold_bps": 2500, "per_unit_bonus_cents": 20000},
        ],
        tier_bonus_mode="MARGINAL",
    ))
    fx.add_eligibility_rule(program["id"], **MX5_WEST_CASH)
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])
    objective_1 = fx.assign_objective(program["id"], dealer_1["id"], stretch_bps=0)
    objective_2 = fx.assign_objective(program["id"], dealer_2["id"], stretch_bps=0)
    delivery = fx.report_delivery(
        dealer_1["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date=JUN_01,
        msrp_cents=3100000,
        sale_date=AUG_01,
        customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery["id"])

    finalized = fx.finalize_objective(objective_1["id"])
    a.assert_status(finalized, "FINAL")
    # achieved 1 of objective_units 4 == 2500 bps, tier 1 inclusive, MARGINAL band
    # of 1 unit at 20000 cents each.
    a.assert_money(finalized, "payout_cents", 20000)
    proposed_before = fx.read_objective(objective_2["id"])
    a.assert_status(proposed_before, "PROPOSED")

    closed = validate_success(api_client.close_program(
        program["id"], fx.CONTROLLER, {"closure_note": "program closed mid-quarter"}))

    # Closure was admitted because no claim of this program is SCHEDULED.
    a.assert_status(closed, "CLOSED")
    voided = fx.read_objective(objective_2["id"])
    a.assert_status(voided, "VOID")
    a.assert_money(voided, "payout_cents", 0)
    a.assert_version(voided, proposed_before["version"] + 1)
    # The FINAL child is outside the cascade set: same status, same payout, and
    # not even a version bump.
    untouched = fx.read_objective(objective_1["id"])
    a.assert_status(untouched, "FINAL")
    a.assert_money(untouched, "payout_cents", 20000)
    a.assert_version(untouched, finalized["version"])


def test_voiding_an_objective_denies_only_its_still_open_protests():
    """The closure cascade denies the OPEN round-2 protest and skips the already-DENIED round-1 one.

    PRD: "Each objective that is voided has its `payout_cents` set to 0 and drives
    every one of its protests whose `status` is `OPEN` to `DENIED` with
    `resolved_units` left null, and each voided objective's `version` increments by 1."

    Design: Corner/state_machines/voiding_an_objective_denies_only_its_still_open_protests
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-CC1",
        name="Conditional Cascade Motors",
        region_code="WEST",
        historical_volume_units=8,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-CC",
        name="Conditional Cascade Stair",
        incentive_type="DEALER_STAIR_STEP",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        budget_cents=12000000,
        stack_group="CRNCC",
        priority_rank=313,
        tier_schedule=[
            {"tier_index": 1, "threshold_bps": 5000, "per_unit_bonus_cents": 15000},
        ],
        tier_bonus_mode="MARGINAL",
    ))
    fx.add_eligibility_rule(program["id"], **MX5_WEST_CASH)
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])
    objective = fx.assign_objective(program["id"], dealer["id"], stretch_bps=0)

    protest_1 = fx.file_protest(
        objective["id"], dealer["id"], 6, reason="market softened")
    resolved_1 = fx.resolve_protest(objective["id"], protest_1["id"], "DENIED")
    a.assert_status(resolved_1, "DENIED")
    assert resolved_1["resolved_by_user_id"] == USER_FSM
    protest_2 = fx.file_protest(
        objective["id"], dealer["id"], 5, reason="second attempt")
    a.assert_status(protest_2, "OPEN")
    a.assert_int_field(protest_2, "round_index", 2)

    closed = validate_success(api_client.close_program(program["id"], fx.CONTROLLER))

    a.assert_status(closed, "CLOSED")
    # PROTESTED is inside the cascade's {PROPOSED, PROTESTED, REVISED} set.
    voided = fx.read_objective(objective["id"])
    a.assert_status(voided, "VOID")
    a.assert_money(voided, "payout_cents", 0)
    # The protest counter is not reset by the void, so a later round cannot be
    # granted for free.
    a.assert_int_field(voided, "protest_round", 2)

    rows, meta = validate_paginated(
        api_client.list_protests(objective["id"], fx.FSM, {"status": "DENIED"}))
    a.assert_list_length(rows, 2, "DENIED protests")
    # The protest listing of one objective is ordered by round_index ascending.
    a.assert_int_field(rows[0], "round_index", 1)
    a.assert_int_field(rows[1], "round_index", 2)
    assert meta["total_count"] == 2, meta
    by_id = {row["id"]: row for row in rows}
    cascaded = by_id[protest_2["id"]]
    a.assert_status(cascaded, "DENIED")
    a.assert_null_fields(cascaded, ["resolved_units"])
    # The already-terminal round-1 protest was left alone, not re-denied.
    untouched = by_id[protest_1["id"]]
    a.assert_status(untouched, "DENIED")
    a.assert_version(untouched, resolved_1["version"])
    assert untouched["resolved_by_user_id"] == USER_FSM


def test_cancelling_an_open_batch_returns_its_scheduled_claims_to_unpaid():
    """Cancel undoes every side effect of scheduling and leaves the validation dimension alone.

    PRD: "Cancellation releases the queue: every claim of this batch in `SCHEDULED`
    returns to `payment_status` `UNPAID` with its `payment_batch_id` cleared to
    null, and the batch's `claim_count` and `total_cents` are both set to 0."

    Design: Corner/state_machines/cancelling_an_open_batch_returns_its_scheduled_claims_to_unpaid
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-CMP",
        name="Compensation Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-CMP",
        name="Compensation Cash",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=120000,
        budget_cents=12000000,
        stack_group="CRNCMP",
        priority_rank=314,
        accrual_method="UNIT_BASED",
    ))
    fx.add_eligibility_rule(program["id"], **MX5_WEST_CASH)
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])
    fx.set_clock(AUG_06)
    delivery = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date=JUN_01,
        msrp_cents=3100000,
        sale_date=AUG_05,
        customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 120000)
    adjudicated = fx.adjudicate_claim(claim["id"], "APPROVE")
    a.assert_claim_dimensions(adjudicated, "VALIDATED", "UNPAID")
    a.assert_money(adjudicated, "approved_amount_cents", 120000)
    a.assert_null_fields(adjudicated, ["payment_batch_id"])
    batch = fx.open_batch(
        batch_code="CRN-B-CMP",
        region_code="WEST",
        period_start=AUG_01,
        period_end=AUG_15,
        scheduled_pay_date=AUG_20,
    )

    scheduled_batch = fx.schedule_claims(batch["id"], [claim["id"]])
    a.assert_int_field(scheduled_batch, "claim_count", 1)
    a.assert_money(scheduled_batch, "total_cents", 120000)
    scheduled_claim = fx.read_claim(claim["id"], fx.CONTROLLER)
    a.assert_claim_dimensions(scheduled_claim, "VALIDATED", "SCHEDULED")
    assert scheduled_claim["payment_batch_id"] == batch["id"]

    cancelled = validate_success(api_client.cancel_batch(
        batch["id"], fx.CONTROLLER, {"cancel_note": "wrong region window"}))

    a.assert_status(cancelled, "CANCELLED")
    a.assert_int_field(cancelled, "claim_count", 0)
    a.assert_money(cancelled, "total_cents", 0)
    released = fx.read_claim(claim["id"], fx.CONTROLLER)
    # Back to exactly the pre-schedule payment dimension.
    a.assert_claim_dimensions(released, "VALIDATED", "UNPAID")
    a.assert_null_fields(released, ["payment_batch_id"])
    # The compensation touches only the payment dimension.
    a.assert_money(released, "approved_amount_cents", 120000)
    summary = fx.read_spend_summary(program["id"])
    # committed_cents never depended on scheduling, so the round trip leaves the
    # ledger identical.
    a.assert_money(summary, "committed_cents", 120000)
    a.assert_money(summary, "paid_cents", 0)


def test_disbursing_a_batch_holds_the_claims_of_suspended_and_terminated_dealers():
    """One disburse pays the ACTIVE dealer's claim and holds the SUSPENDED dealer's in SCHEDULED.

    PRD: "Every scheduled claim whose dealer has `status` `SUSPENDED` or
    `TERMINATED` is held instead: it stays in `SCHEDULED`, keeps its
    `payment_batch_id`, and is counted in the batch's `held_claim_count` as
    measured at the moment of this disbursement attempt."

    Design: Corner/state_machines/disbursing_a_batch_holds_the_claims_of_suspended_and_terminated_dealers
    """
    fx.set_clock(AUG_01)
    dealer_1 = fx.register_dealer(
        dealer_code="CRN-D-DS1",
        name="Disburse Dealer One",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    dealer_2 = fx.register_dealer(
        dealer_code="CRN-D-DS2",
        name="Disburse Dealer Two",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-DS",
        name="Disburse Cash",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=110000,
        budget_cents=12000000,
        stack_group="CRNDS",
        priority_rank=315,
        accrual_method="UNIT_BASED",
    ))
    fx.add_eligibility_rule(program["id"], **MX5_WEST_CASH)
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])
    fx.set_clock(AUG_06)
    delivery_1 = fx.report_delivery(
        dealer_1["id"], model_code="MX5", trim_code="BASE", build_date=JUN_01,
        msrp_cents=3100000, sale_date=AUG_05, customer_region_code="WEST",
        deal_type="CASH",
    )
    delivery_2 = fx.report_delivery(
        dealer_2["id"], model_code="MX5", trim_code="BASE", build_date=JUN_01,
        msrp_cents=3100000, sale_date=AUG_05, customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery_1["id"])
    fx.validate_delivery(delivery_2["id"])
    claim_1 = fx.submit_claim(dealer_1["id"], delivery_1["id"], program["id"], 110000)
    fx.adjudicate_claim(claim_1["id"], "APPROVE")
    claim_2 = fx.submit_claim(dealer_2["id"], delivery_2["id"], program["id"], 110000)
    fx.adjudicate_claim(claim_2["id"], "APPROVE")
    batch = fx.open_batch(
        batch_code="CRN-B-DS",
        region_code="WEST",
        period_start=AUG_01,
        period_end=AUG_15,
        scheduled_pay_date=AUG_20,
    )
    scheduled = fx.schedule_claims(batch["id"], [claim_1["id"], claim_2["id"]])
    a.assert_int_field(scheduled, "claim_count", 2)
    a.assert_money(scheduled, "total_cents", 220000)
    locked = fx.lock_batch(batch["id"])
    a.assert_status(locked, "LOCKED")
    # Dealer 2 was allowed to report, validate and claim; standing bites only at
    # disbursement.
    suspended = fx.set_dealer_status(dealer_2["id"], "SUSPENDED", note="audit in progress")
    a.assert_status(suspended, "SUSPENDED")
    fx.set_clock(AUG_20)

    disbursed = validate_success(api_client.disburse_batch(batch["id"], fx.CONTROLLER))

    a.assert_status(disbursed, "DISBURSED")
    assert disbursed["disbursed_at"] == AUG_20, disbursed["disbursed_at"]
    a.assert_int_field(disbursed, "held_claim_count", 1)
    # Held claims are still attached, so claim_count does not drop and total_cents
    # is recomputed over both of them.
    a.assert_int_field(disbursed, "claim_count", 2)
    a.assert_money(disbursed, "total_cents", 220000)
    paid_claim = fx.read_claim(claim_1["id"], fx.CONTROLLER)
    a.assert_claim_dimensions(paid_claim, "VALIDATED", "PAID")
    assert paid_claim["paid_at"] == AUG_20, paid_claim["paid_at"]
    held_claim = fx.read_claim(claim_2["id"], fx.CONTROLLER)
    a.assert_claim_dimensions(held_claim, "VALIDATED", "SCHEDULED")
    a.assert_null_fields(held_claim, ["paid_at"])
    assert held_claim["payment_batch_id"] == batch["id"]
    a.assert_money(fx.read_dealer(dealer_1["id"]), "paid_cents", 110000)
    a.assert_money(fx.read_dealer(dealer_2["id"]), "paid_cents", 0)
    summary = fx.read_spend_summary(program["id"])
    # A held claim stays committed but unpaid.
    a.assert_money(summary, "paid_cents", 110000)
    a.assert_money(summary, "committed_cents", 220000)


def test_an_unvalidated_claim_cannot_be_scheduled_into_a_batch():
    """A SUBMITTED claim is refused, the same call succeeds once adjudicated, and a REJECTED claim is refused forever.

    PRD: "A named claim that fails either half of that condition is refused with
    `ERR_CLAIM_NOT_VALIDATED` and **the whole call is a no-op**: no claim in the
    list is attached, no total is recomputed, and no version moves."

    Design: Corner/state_machines/an_unvalidated_claim_cannot_be_scheduled_into_a_batch
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-GRD",
        name="Guarded Motors",
        region_code="EAST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(f.create_program_payload(
        program_code="CRN-SM-GRD",
        name="Guarded Cash",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNGRD",
        priority_rank=316,
        accrual_method="UNIT_BASED",
    ))
    fx.add_eligibility_rule(
        program["id"],
        model_code="MX5",
        region_code="EAST",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])
    fx.set_clock(AUG_06)
    delivery_a = fx.report_delivery(
        dealer["id"], model_code="MX5", trim_code="BASE", build_date=JUN_01,
        msrp_cents=3100000, sale_date=AUG_05, customer_region_code="EAST",
        deal_type="CASH",
    )
    delivery_b = fx.report_delivery(
        dealer["id"], model_code="MX5", trim_code="BASE", build_date=JUN_01,
        msrp_cents=3100000, sale_date=AUG_05, customer_region_code="EAST",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery_a["id"])
    fx.validate_delivery(delivery_b["id"])
    claim_a = fx.submit_claim(dealer["id"], delivery_a["id"], program["id"], 100000)
    a.assert_claim_dimensions(claim_a, "SUBMITTED", "UNPAID")
    claim_b = fx.submit_claim(dealer["id"], delivery_b["id"], program["id"], 100000)
    batch = fx.open_batch(
        batch_code="CRN-B-GRD",
        region_code="EAST",
        period_start=AUG_01,
        period_end=AUG_15,
        scheduled_pay_date=AUG_20,
    )

    # The payment dimension may not leave UNPAID while validation_status is SUBMITTED.
    validate_error(
        api_client.schedule_claims(
            batch["id"], f.schedule_claims_payload([claim_a["id"]]), fx.CONTROLLER),
        "ERR_CLAIM_NOT_VALIDATED",
    )
    untouched_batch = fx.read_batch(batch["id"])
    a.assert_int_field(untouched_batch, "claim_count", 0)
    a.assert_money(untouched_batch, "total_cents", 0)
    a.assert_version(untouched_batch, batch["version"])
    still_submitted = fx.read_claim(claim_a["id"])
    a.assert_claim_dimensions(still_submitted, "SUBMITTED", "UNPAID")
    a.assert_version(still_submitted, claim_a["version"])

    approved = fx.adjudicate_claim(claim_a["id"], "APPROVE")
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")
    rejected = fx.adjudicate_claim(
        claim_b["id"], "REJECT", rejection_error_id="ERR_DUPLICATE_CLAIM")
    a.assert_claim_dimensions(rejected, "REJECTED", "UNPAID")
    a.assert_money(rejected, "approved_amount_cents", 0)

    # Adjudication is the only thing that changed, and the same call now succeeds.
    retried = fx.schedule_claims(batch["id"], [claim_a["id"]])
    a.assert_int_field(retried, "claim_count", 1)
    a.assert_money(retried, "total_cents", 100000)

    # REJECTED is terminal on the validation dimension, so this claim can never
    # be scheduled.
    validate_error(
        api_client.schedule_claims(
            batch["id"], f.schedule_claims_payload([claim_b["id"]]), fx.CONTROLLER),
        "ERR_CLAIM_NOT_VALIDATED",
    )
    final_batch = fx.read_batch(batch["id"])
    a.assert_int_field(final_batch, "claim_count", 1)
    a.assert_money(final_batch, "total_cents", 100000)
