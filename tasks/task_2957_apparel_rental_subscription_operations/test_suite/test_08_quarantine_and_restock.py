"""The biohazard quarantine hold, the certification gates and the restock cascade.

A quarantine hold is the warehouse's safety brake: while it is up nothing in
reconditioning may proceed, and only a repair-certified technician may lower it.
Restock is the other end of the pipeline, where a garment earns its turn, the
turn earns its revenue and the style's depth picture is rewritten.  These tests
pin the certification split, the precedence of the safety brake over the duty
split, the terminality of a restocked job, the claim guard on restock, and the
fact that the whole five-hop cascade is readable by the very next call.
"""

from __future__ import annotations

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_OPEN_CLAIM_BLOCKS_RESTOCK,
    ERR_QUARANTINE_HOLD_ACTIVE,
    ERR_RESOURCE_TERMINAL,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TECHNICIAN_NOT_CERTIFIED,
)
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null,
    assert_ok,
    assert_unit_position,
)
from test_helpers.fixtures import (
    Catalog,
    Scenario,
    Turn,
    completed_turn,
    finish_reconditioning,
    inspected_turn,
    standard_catalog,
)

JsonDict = dict

# Every circuit in this module is received at the same instant, so all the
# reconditioning stamps below are read from it.
RECEIPT_CLOCK = K.CLOCK_AUG_10_0900


def _quarantined_turn(
    scenario: Scenario,
    soil_level: str,
    damage_severity: str,
    condition_grade_after: str,
):
    """A received garment whose biohazard inspection put the safety brake on."""
    catalog = standard_catalog(scenario)
    turn = inspected_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_09,
        soil_level,
        damage_severity,
        condition_grade_after,
        biohazard_flag=True,
    )
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_QUARANTINED,
        condition_grade=condition_grade_after,
        quarantine_hold=True,
    )
    assert_fields(turn.job, state=K.JOB_PROCESSING)
    return catalog, turn


def test_quarantine_clearance_is_refused_without_the_repair_certification(
    scenario: Scenario,
) -> None:
    """The clearance reads `repair_certified`, so an ACTIVE outsider cannot lift the brake.

    PRD §2.10: "At rank 26, the required certification must be present: repair completion and quarantine clearance require `repair_certified` to be true, and photography requires `photography_certified` to be true, otherwise `ERR_TECHNICIAN_NOT_CERTIFIED` (403)."
    PRD §3.6: "A `biohazard_flag` of true outranks everything else: the unit moves `FLOOR_READY → QUARANTINED`, its `quarantine_hold` is set to true, and its `condition_grade` is updated from `condition_grade_after`."

    Design: Difficulty/cross_entity_state_dependency/quarantine_clearance_requires_repair_certified_technician
    """
    catalog, turn = _quarantined_turn(scenario, K.SOIL_HEAVY, K.DAMAGE_NONE, K.GRADE_B)
    outsider = scenario.create_uncertified_technician()
    # The refusal cannot be about employment or about the unit's position.
    assert_fields(outsider, status=K.TECH_ACTIVE, repair_certified=False)

    refused = scenario.client.clear_quarantine(
        turn.job_id, Scenario.tech_headers(outsider)
    )
    assert_error(refused, ERR_TECHNICIAN_NOT_CERTIFIED)

    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_QUARANTINED,
        condition_grade=K.GRADE_B,
        quarantine_hold=True,
    )
    frozen = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(
        frozen,
        state=K.JOB_PROCESSING,
        cleaning_required=True,
        repair_required=False,
    )


def test_a_repair_certified_technician_lifts_the_hold_and_moves_only_the_unit(
    scenario: Scenario,
) -> None:
    """Clearance walks the condition dimension one step and leaves the job alone.

    PRD §3.6: "The only way forward is a clearance by a technician whose `repair_certified` is true, which moves the unit `QUARANTINED → NEEDS_CLEANING` and sets `quarantine_hold` back to false."
    PRD §3.6: "A quarantined garment therefore always passes through the cleaning leg on its way out, regardless of what its `soil_level` said."

    Design: Difficulty/cross_entity_state_dependency/quarantine_clearance_requires_repair_certified_technician
    """
    catalog, turn = _quarantined_turn(scenario, K.SOIL_NONE, K.DAMAGE_NONE, K.GRADE_B)
    assert_fields(catalog.repairer, repair_certified=True, status=K.TECH_ACTIVE)

    scenario.clear_quarantine(catalog.repairer, turn.job_id)

    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_CLEANING,
        condition_grade=K.GRADE_B,
        quarantine_hold=False,
    )
    # An unsoiled garment still owes the cleaning leg, because the quarantine
    # route always exits through NEEDS_CLEANING.
    assert_fields(
        scenario.read_job(catalog.repairer, turn.job_id),
        state=K.JOB_PROCESSING,
        cleaning_required=True,
        repair_required=False,
    )


def test_the_hold_freezes_the_cleaning_signoff_until_it_is_lifted(
    scenario: Scenario,
) -> None:
    """The identical cleaning call is refused, then accepted, with nothing else changed.

    PRD §3.6: "While `quarantine_hold` is true, every reconditioning step on the unit is frozen: cleaning sign-off, repair sign-off, photography and restock are all refused at rank 20 with `ERR_QUARANTINE_HOLD_ACTIVE` (409)."
    PRD §3.6: "Signing off cleaning stamps `cleaning_completed_at`, moves the unit `NEEDS_CLEANING → FLOOR_READY`, and re-rolls `servicing_cost_cents`."

    Design: Corner/validations/validation_quarantine_hold_blocks_the_cleaning_signoff_until_it_is_cleared
    """
    catalog, turn = _quarantined_turn(scenario, K.SOIL_LIGHT, K.DAMAGE_NONE, K.GRADE_A)
    assert_fields(turn.job, cleaning_required=True, repair_required=False)

    braked = scenario.client.complete_cleaning(
        turn.job_id, Scenario.tech_headers(catalog.repairer)
    )
    assert_error(braked, ERR_QUARANTINE_HOLD_ACTIVE)
    held = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(held, state=K.JOB_PROCESSING)
    assert_null(held, "cleaning_completed_at")
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        condition_state=K.COND_QUARANTINED,
        quarantine_hold=True,
    )

    scenario.clear_quarantine(catalog.repairer, turn.job_id)
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        condition_state=K.COND_NEEDS_CLEANING,
        quarantine_hold=False,
    )

    cleaned = scenario.complete_cleaning(catalog.repairer, turn.job_id)
    assert_fields(cleaned, state=K.JOB_READY_FOR_PHOTO, repair_required=False)
    assert_instant(cleaned["cleaning_completed_at"], RECEIPT_CLOCK, "cleaning_completed_at")
    assert_money(
        cleaned, servicing_cost_cents=K.CLEANING_COST_BY_SOIL[K.SOIL_LIGHT]
    )
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
        quarantine_hold=False,
    )


def test_the_safety_hold_outranks_the_duty_split_on_a_repair_signoff(
    scenario: Scenario,
) -> None:
    """One call breaks two rules; the safety rule at rank 20 answers first.

    PRD §3.6: "The rules that guard it stack in ladder order: at rank 20 the unit's `quarantine_hold` must be false; at rank 25 the acting technician must not be the job's `inspecting_technician_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (403); at rank 26 the acting technician's `repair_certified` must be true, otherwise `ERR_TECHNICIAN_NOT_CERTIFIED` (403); at rank 27 the technician's `status` must be `ACTIVE`, otherwise `ERR_TECHNICIAN_SUSPENDED` (403); and at rank 28 the job's `repair_attempts` must be strictly below the cap of 2, otherwise `ERR_REPAIR_ATTEMPTS_EXHAUSTED` (409)."
    PRD §3.6: "While `quarantine_hold` is true, every reconditioning step on the unit is frozen: cleaning sign-off, repair sign-off, photography and restock are all refused at rank 20 with `ERR_QUARANTINE_HOLD_ACTIVE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_hold_outranks_segregation_of_duties_on_repair_signoff
    """
    catalog, turn = _quarantined_turn(
        scenario, K.SOIL_HEAVY, K.DAMAGE_MODERATE, K.GRADE_B
    )
    # The signer really is the inspector, so rank 25 is live on this call too.
    assert_fields(
        turn.job,
        inspecting_technician_id=catalog.inspector["id"],
        cleaning_required=True,
        repair_required=True,
        repair_attempts=0,
    )

    both_broken = scenario.client.complete_repair(
        turn.job_id,
        F.repair_completion_payload(K.REPAIR_ACCEPTED),
        Scenario.tech_headers(catalog.inspector),
    )
    assert_error(both_broken, ERR_QUARANTINE_HOLD_ACTIVE)

    untouched = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(untouched, state=K.JOB_PROCESSING, repair_attempts=0)
    assert_null(untouched, "repair_completed_at")
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        condition_state=K.COND_QUARANTINED,
        quarantine_hold=True,
    )


def test_with_the_hold_lifted_the_same_signoff_reports_the_duty_conflict(
    scenario: Scenario,
) -> None:
    """The duties rule was live all along: it surfaces the moment the brake is off.

    PRD §2.10: "At rank 25, on a repair sign-off, the acting technician's identifier must differ from the identifier of the technician who filed the job's inspection; if they are the same person, the response is `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.6: "The only way forward is a clearance by a technician whose `repair_certified` is true, which moves the unit `QUARANTINED → NEEDS_CLEANING` and sets `quarantine_hold` back to false."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_hold_outranks_segregation_of_duties_on_repair_signoff
    """
    catalog, turn = _quarantined_turn(
        scenario, K.SOIL_HEAVY, K.DAMAGE_MODERATE, K.GRADE_B
    )

    scenario.clear_quarantine(catalog.repairer, turn.job_id)
    lifted = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        lifted,
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_CLEANING,
        quarantine_hold=False,
    )
    assert_fields(
        scenario.read_job(catalog.repairer, turn.job_id),
        state=K.JOB_PROCESSING,
        repair_required=True,
        cleaning_required=True,
    )

    duty_conflict = scenario.client.complete_repair(
        turn.job_id,
        F.repair_completion_payload(K.REPAIR_ACCEPTED),
        Scenario.tech_headers(catalog.inspector),
    )
    assert_error(duty_conflict, ERR_SEGREGATION_OF_DUTIES)

    spared = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(spared, state=K.JOB_PROCESSING, repair_attempts=0)
    assert_null(spared, "repair_completed_at")


def test_photography_requires_the_photography_certification(
    scenario: Scenario,
) -> None:
    """Rank 26 reads a different flag per endpoint, and only the camera flag counts here.

    PRD §3.6: "It requires the job to be in `READY_FOR_PHOTO`, the acting technician's `photography_certified` to be true (rank 26), the unit's `condition_state` to be `FLOOR_READY`, and — at rank 21 — the unit not to be `CONDEMNED`, otherwise `ERR_UNIT_CONDEMNED` (409); rank 20's quarantine check applies as well."
    PRD §3.6: "It stamps `photographed_at` and moves the job `READY_FOR_PHOTO → PHOTOGRAPHED`."

    Design: Corner/validations/validation_photography_requires_the_photography_certification
    """
    catalog = standard_catalog(scenario)
    turn = inspected_turn(scenario, catalog, K.WINDOW_AUG_05_09)
    assert_fields(turn.job, state=K.JOB_READY_FOR_PHOTO)

    outsider = scenario.create_uncertified_technician()
    assert_fields(outsider, status=K.TECH_ACTIVE, photography_certified=False)

    refused = scenario.client.photograph(
        turn.job_id, Scenario.tech_headers(outsider)
    )
    assert_error(refused, ERR_TECHNICIAN_NOT_CERTIFIED)
    waiting = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(waiting, state=K.JOB_READY_FOR_PHOTO)
    assert_null(waiting, "photographed_at")
    assert_money(waiting, servicing_cost_cents=0)

    # The identical call by a photography-certified technician goes through.
    photographed = scenario.photograph(catalog.repairer, turn.job_id)
    assert_fields(photographed, state=K.JOB_PHOTOGRAPHED)
    assert_instant(photographed["photographed_at"], RECEIPT_CLOCK, "photographed_at")
    assert_money(photographed, servicing_cost_cents=K.PHOTOGRAPHY_COST_CENTS)
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
    )


def test_photography_after_the_restock_reports_terminality(
    scenario: Scenario,
) -> None:
    """A restocked job is done: the second camera pass neither charges nor moves anything.

    PRD §3.6: "Its pipeline `state` runs across `RECEIVED`, `INSPECTED`, `PROCESSING`, `READY_FOR_PHOTO`, `PHOTOGRAPHED`, `RESTOCKED` and `CONDEMNED_HOLD`, opening at `RECEIVED`, with `RESTOCKED` as its only terminal state."
    PRD §2.5: "Ranks 15 and 16 are the two generic state guards, and their order matters: rank 15 rejects a request whose trigger is not a declared transition out of the target resource's **current, non-terminal** state with `ERR_INVALID_STATE_TRANSITION` (409), while rank 16 rejects an action aimed at a resource that already sits in one of its declared terminal states with `ERR_RESOURCE_TERMINAL` (409)."

    Design: Corner/state_machines/state_photography_after_restock_returns_resource_terminal
    """
    catalog = standard_catalog(scenario)
    turn = completed_turn(scenario, catalog, K.WINDOW_AUG_05_09)
    assert_fields(turn.job, state=K.JOB_RESTOCKED)
    assert_money(turn.job, servicing_cost_cents=K.PHOTOGRAPHY_COST_CENTS)

    # A later clock would expose a second stamp if the call were honoured.
    scenario.set_clock(K.CLOCK_AUG_11_0900)
    again = scenario.client.photograph(
        turn.job_id, Scenario.tech_headers(catalog.repairer)
    )
    assert_error(again, ERR_RESOURCE_TERMINAL)

    closed = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(closed, state=K.JOB_RESTOCKED)
    assert_instant(closed["photographed_at"], RECEIPT_CLOCK, "photographed_at")
    assert_money(closed, servicing_cost_cents=K.PHOTOGRAPHY_COST_CENTS)

    home = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        home, availability_state=K.AVAIL_IN_STOCK, condition_state=K.COND_FLOOR_READY
    )
    assert_fields(home, turns_completed=1)
    assert_money(home, cumulative_servicing_cost_cents=K.PHOTOGRAPHY_COST_CENTS)


def _photographed_turn(
    scenario: Scenario,
    soil_level: str = K.SOIL_NONE,
    damage_severity: str = K.DAMAGE_NONE,
    condition_grade_after: str = K.GRADE_A,
):
    """A fully reconditioned garment waiting on the restock, legs signed and shot."""
    catalog = standard_catalog(scenario)
    turn = inspected_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_09,
        soil_level,
        damage_severity,
        condition_grade_after,
    )
    turn = finish_reconditioning(scenario, catalog, turn, restock=False)
    assert_fields(turn.job, state=K.JOB_PHOTOGRAPHED)
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
        quarantine_hold=False,
    )
    return catalog, turn


def test_restock_is_blocked_while_the_claim_is_open_and_while_it_is_assessed(
    scenario: Scenario,
) -> None:
    """The blocking set is a set of states, so the assessment does not unblock anything.

    PRD §3.6: "It requires the job to be in `PHOTOGRAPHED`, the unit to be `FLOOR_READY` with `quarantine_hold` false and not `CONDEMNED`, and — at rank 22 — that no damage claim on this unit and this reservation sits in `OPEN`, `ASSESSED` or `DISPUTED`, otherwise `ERR_OPEN_CLAIM_BLOCKS_RESTOCK` (409)."
    PRD §3.7: "A claims adjuster prices an `OPEN` claim, which requires that the linked job carry at least one inspection and moves the claim `OPEN → ASSESSED` with `assessed_at` stamped at the current logical clock."

    Design: Difficulty/cross_entity_state_dependency/restock_blocked_until_damage_claim_leaves_open_states
    """
    catalog, turn = _photographed_turn(
        scenario, K.SOIL_NONE, K.DAMAGE_MODERATE, K.GRADE_B
    )
    assert_fields(scenario.read_claim(turn.claim_id), state=K.CLAIM_OPEN)

    while_open = scenario.client.restock(
        turn.job_id, Scenario.tech_headers(catalog.repairer)
    )
    assert_error(while_open, ERR_OPEN_CLAIM_BLOCKS_RESTOCK)
    assert_fields(scenario.read_job(catalog.repairer, turn.job_id), state=K.JOB_PHOTOGRAPHED)
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
    )

    assessed = scenario.assess(turn.claim_id)
    assert_fields(assessed, state=K.CLAIM_ASSESSED)
    assert_instant(assessed["assessed_at"], RECEIPT_CLOCK, "assessed_at")

    while_assessed = scenario.client.restock(
        turn.job_id, Scenario.tech_headers(catalog.repairer)
    )
    assert_error(while_assessed, ERR_OPEN_CLAIM_BLOCKS_RESTOCK)

    stalled = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(stalled, state=K.JOB_PHOTOGRAPHED)
    parked = scenario.read_unit(turn.unit_id)
    assert_unit_position(parked, availability_state=K.AVAIL_PROCESSING)
    assert_fields(parked, turns_completed=0)
    assert_money(parked, cumulative_servicing_cost_cents=0)
    assert_fields(
        scenario.read_reservation(turn.reservation_id), state=K.RES_RETURNED
    )


def test_the_same_restock_succeeds_once_the_claim_is_charged(
    scenario: Scenario,
) -> None:
    """Money settled, the garment earns its turn and the depth picture is rewritten.

    PRD §3.6: "It requires the job to be in `PHOTOGRAPHED`, the unit to be `FLOOR_READY` with `quarantine_hold` false and not `CONDEMNED`, and — at rank 22 — that no damage claim on this unit and this reservation sits in `OPEN`, `ASSESSED` or `DISPUTED`, otherwise `ERR_OPEN_CLAIM_BLOCKS_RESTOCK` (409)."
    PRD §3.6: "The fourth hop re-derives the style's `floor_ready_unit_count`, `required_depth_units`, `depth_gap_units` and `replenishment_flag`, and the unit's `cumulative_servicing_cost_cents` is refreshed."

    Design: Difficulty/cross_entity_state_dependency/restock_blocked_until_damage_claim_leaves_open_states
    """
    catalog, turn = _photographed_turn(
        scenario, K.SOIL_NONE, K.DAMAGE_MODERATE, K.GRADE_B
    )
    scenario.assess(turn.claim_id)
    charged = scenario.charge(turn.claim_id)
    assert_fields(charged, state=K.CLAIM_CHARGED)
    assert_instant(charged["charged_at"], RECEIPT_CLOCK, "charged_at")
    # The debt is on the member's balance, which is what rank 22 was waiting for.
    assert_money(
        scenario.read_member(catalog.member),
        outstanding_fee_cents=charged["net_fee_cents"],
    )

    restocked = scenario.restock(catalog.repairer, turn.job_id)
    assert_fields(restocked, state=K.JOB_RESTOCKED)

    home = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        home, availability_state=K.AVAIL_IN_STOCK, condition_state=K.COND_FLOOR_READY
    )
    assert_fields(home, turns_completed=1)
    assert_money(
        home, cumulative_servicing_cost_cents=restocked["servicing_cost_cents"]
    )

    closed = scenario.read_reservation(turn.reservation_id)
    assert_fields(closed, state=K.RES_CLOSED)
    assert_money(
        closed, revenue_attributed_cents=K.PLAN_SIG4_BASE_REVENUE_PER_TURN_CENTS
    )
    assert_fields(
        scenario.read_style(catalog.style_id),
        floor_ready_unit_count=1,
        active_unit_count=1,
        required_depth_units=K.STYLE_GOWN_PLANNED_DEPTH,
        depth_gap_units=K.STYLE_GOWN_PLANNED_DEPTH - 1,
    )


def test_the_whole_restock_cascade_is_readable_by_the_very_next_call(
    scenario: Scenario,
) -> None:
    """Four entities, one request, no lag: every derived field is fresh straight away.

    PRD §2.9: "Derived values are never stale in a response: any computed field of any entity touched by a cascade is recomputed before the response is written, including a style's `floor_ready_unit_count`, `active_unit_count`, `required_depth_units`, `depth_gap_units`, `replenishment_flag` and `demand_score`; a member's `outstanding_fee_cents`, `units_out_count`, `swaps_used_current_month`, `late_return_count`, `fit_confidence_score`, `damage_risk_score` and `damage_risk_band`; a unit's `cumulative_servicing_cost_cents`, `realized_revenue_cents` and `occupied_until_date`; and a reservation's `waitlist_position`."
    PRD §3.6: "The fourth hop re-derives the style's `floor_ready_unit_count`, `required_depth_units`, `depth_gap_units` and `replenishment_flag`, and the unit's `cumulative_servicing_cost_cents` is refreshed."

    Design: Corner/consistency_model/consistency_restock_cascade_is_fully_visible_in_the_same_request
    """
    catalog, turn = _photographed_turn(scenario)
    # No claim exists on a clean turn, so nothing but the cascade is in play.

    restocked = scenario.restock(catalog.repairer, turn.job_id)
    assert_fields(restocked, state=K.JOB_RESTOCKED)
    assert_money(restocked, servicing_cost_cents=K.PHOTOGRAPHY_COST_CENTS)

    # The clock has not moved since the receipt, so every read below is taken at
    # the same logical instant as the write.
    unit = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        unit, availability_state=K.AVAIL_IN_STOCK, condition_state=K.COND_FLOOR_READY
    )
    assert_fields(unit, turns_completed=1)
    assert_money(
        unit,
        realized_revenue_cents=K.PLAN_SIG4_BASE_REVENUE_PER_TURN_CENTS,
        cumulative_servicing_cost_cents=K.PHOTOGRAPHY_COST_CENTS,
    )
    assert_instant(unit["last_returned_at"], RECEIPT_CLOCK, "last_returned_at")

    reservation = scenario.read_reservation(turn.reservation_id)
    assert_fields(reservation, state=K.RES_CLOSED, late_days=0)
    assert_money(
        reservation, revenue_attributed_cents=K.PLAN_SIG4_BASE_REVENUE_PER_TURN_CENTS
    )

    assert_fields(
        scenario.read_style(catalog.style_id),
        floor_ready_unit_count=1,
        active_unit_count=1,
        required_depth_units=K.STYLE_GOWN_PLANNED_DEPTH,
        depth_gap_units=K.STYLE_GOWN_PLANNED_DEPTH - 1,
    )


def test_the_servicing_rollup_reaches_the_unit_only_when_the_job_is_restocked(
    scenario: Scenario,
) -> None:
    """The job carries the whole bill while the unit's rollup still reads zero.

    PRD §3.6: "A unit's `cumulative_servicing_cost_cents` is the sum of `servicing_cost_cents` across the jobs on that unit whose `state` is `RESTOCKED`."
    PRD §3.6: "A job's `servicing_cost_cents` is re-rolled on every inspection, every repair sign-off, every cleaning sign-off, every photography sign-off and every restock, and it always reads from the **newest** inspection on the job — the one with the greatest `attempt_index`."

    Design: Corner/calculations/calc_servicing_rollup_reaches_the_unit_only_when_the_job_is_restocked
    """
    catalog, turn = _photographed_turn(
        scenario, K.SOIL_HEAVY, K.DAMAGE_MINOR, K.GRADE_B
    )
    expected_bill = (
        K.CLEANING_COST_BY_SOIL[K.SOIL_HEAVY]
        + K.REPAIR_RATE_BY_SEVERITY[K.DAMAGE_MINOR]
        + K.PHOTOGRAPHY_COST_CENTS
    )
    assert_money(turn.job, servicing_cost_cents=expected_bill)
    assert_fields(turn.job, repair_attempts=1)

    # The labour is fully accrued on the job, and none of it has reached the unit.
    before = scenario.read_unit(turn.unit_id)
    assert_unit_position(before, availability_state=K.AVAIL_PROCESSING)
    assert_money(before, cumulative_servicing_cost_cents=0)

    # The MINOR claim has to leave the blocking states before the garment moves.
    scenario.assess(turn.claim_id)
    scenario.charge(turn.claim_id)

    restocked = scenario.restock(catalog.repairer, turn.job_id)
    assert_fields(restocked, state=K.JOB_RESTOCKED, repair_attempts=1)
    assert_money(restocked, servicing_cost_cents=expected_bill)

    after = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        after,
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
        condition_grade=K.GRADE_B,
    )
    assert_fields(after, turns_completed=1)
    assert_money(after, cumulative_servicing_cost_cents=expected_bill)
