"""The later rungs of the ladder: temporal partitions, one-shot steps, money gates.

PRD 2.8 numbers its rejection rules so that a request breaking two of them at
once has exactly one right answer, and PRD 3.5 to PRD 3.9 make several steps
consumable only once. These tests break each rule deliberately and then read the
rows back to prove the refusal moved nothing.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    ACCOUNTING_CLERK_ALT,
    ACCOUNTING_CLERK_ALT_ID,
    CONTRACT_ADMIN,
    RESERVATIONS_AGENT,
    REVENUE_MANAGER,
    REVENUE_MANAGER_ALT,
    REVENUE_MANAGER_ALT_ID,
    REVENUE_MANAGER_THIRD,
    AnalysisStatus,
    ApiErrorId,
    BlockBillingStatus,
    BlockInventoryStatus,
    ChargeCategory,
    ChargeStatus,
    ContractStatus,
    LeadStatus,
    ReconciliationStatus,
    assert_ancillary_charge,
    assert_displacement_analysis,
    assert_group_account,
    assert_group_contract,
    assert_lead,
    assert_receivable_identity,
    assert_reconciliation,
    assert_room_block,
    assert_waterfall_identities,
    committed_rooms,
    constants as C,
    factories as F,
    held_rooms,
    lead_version,
    read_block,
    read_contract,
    read_lead,
    seed_ancillary_charge,
    seed_cleared_lead,
    seed_cut_off_master,
    seed_draft_reconciliation,
    seed_open_master_block,
    seed_sent_contract,
    seed_signed_contract,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_cutoff_date_partitions_the_block_timeline_from_both_sides(api):
    """One date, two mirrored rules, and a state gate that outranks one of them.

    PRD 3.6 derives cutoff_date as the arrival date less
    cutoff_days_before_arrival, which is 2026-10-19 for a 21-day term, and PRD 3.7
    refuses a cutoff before that date with ERR_CUTOFF_DATE_NOT_REACHED, "the exact
    mirror of the rule that stops rooming-list additions on or after the same
    date". The boundary date itself therefore belongs to the cutoff: on 2026-10-19
    a rooming-list write is already ERR_PAST_CUTOFF_DATE while the cutoff is
    admissible. PRD 2.8 then settles the double violation - a reservation into a
    CUT_OFF block breaks both the block-open rule at priority 12 and the
    before-cutoff rule at priority 14, and the lower-numbered ERR_BLOCK_NOT_OPEN
    is the answer. Re-opening or re-cutting is an undeclared transition, which PRD
    2.8 answers at priority 10.

    Design: Corner/validations/block_lifecycle_temporal_rules_and_their_priority_order
    """
    world = seed_open_master_block(api)
    block_id = world["master_block_id"]
    assert_room_block(read_block(api, block_id), cutoff_date="2026-10-19")

    validate_error(
        api.cutoff_room_block(block_id, RESERVATIONS_AGENT),
        ApiErrorId.CUTOFF_DATE_NOT_REACHED,
        422,
    )
    validate_error(
        api.open_room_block(block_id, RESERVATIONS_AGENT),
        ApiErrorId.BLOCK_INVALID_STATE,
        409,
    )

    set_clock(api, "2026-10-19T00:00:00Z")

    validate_error(
        api.create_reservation(
            F.reservation_payload(
                block_id,
                guest_name="Late Arrival",
                arrival_date="2026-11-09",
                departure_date="2026-11-10",
            ),
            RESERVATIONS_AGENT,
        ),
        ApiErrorId.PAST_CUTOFF_DATE,
        422,
    )

    cut = validate_success(api.cutoff_room_block(block_id, RESERVATIONS_AGENT))
    assert_room_block(
        cut,
        inventory_status=BlockInventoryStatus.CUT_OFF,
        released_room_nights=12,
    )

    validate_error(
        api.create_reservation(
            F.reservation_payload(
                block_id,
                guest_name="Too Late",
                arrival_date="2026-11-09",
                departure_date="2026-11-10",
            ),
            RESERVATIONS_AGENT,
        ),
        ApiErrorId.BLOCK_NOT_OPEN,
        409,
    )
    validate_error(
        api.cutoff_room_block(block_id, RESERVATIONS_AGENT),
        ApiErrorId.BLOCK_INVALID_STATE,
        409,
    )
    validate_error(
        api.open_room_block(block_id, RESERVATIONS_AGENT),
        ApiErrorId.BLOCK_INVALID_STATE,
        409,
    )
    assert committed_rooms(api, C.STAY_DATES) == [0, 0, 0], (
        "the cutoff handed every unsold room back to the house"
    )


def test_a_credit_hold_stops_the_signature_and_the_whole_cascade_with_it(api):
    """The last gate of the ladder aborts the most consequential step atomically.

    PRD 2.8 places the account's credit standing at priority 32 and says why:
    "this is the last gate of all: financial standing is checked only after every
    other reason to reject has been exhausted" - so the flag stops nothing on the
    way to a SENT contract, being reached only by walking "the contract's quote,
    that quote's lead, and that lead's account_id". PRD 3.5 makes countersignature
    "where soft holds become hard commitments and where the room block tree comes
    into existence", so the 402 must leave all of it undone: no master block, no
    committed rooms, and the accepted quote's soft hold still standing on every
    occupied date.

    Design: Corner/validations/an_account_on_credit_hold_cannot_reach_a_signed_contract
    """
    world = seed_sent_contract(api, account={"credit_hold": True})

    validate_error(
        api.sign_contract(world["contract_id"], F.sign_payload(), CONTRACT_ADMIN),
        ApiErrorId.ACCOUNT_CREDIT_HOLD,
        402,
    )

    assert_group_contract(
        read_contract(api, world["contract_id"]),
        status=ContractStatus.SENT,
        signed_at=None,
    )
    _, meta = validate_paginated(
        api.list_room_blocks(CONTRACT_ADMIN, contract_id=world["contract_id"])
    )
    assert meta["total_count"] == 0, "the room block tree must not exist yet"
    assert held_rooms(api, C.STAY_DATES) == [4, 4, 4], (
        "the accepted quote's soft hold is untouched by the refusal"
    )
    assert committed_rooms(api, C.STAY_DATES) == [0, 0, 0]


def test_posting_and_voiding_a_charge_are_each_available_exactly_once(api):
    """Two refused replays, and the ledger moves 450000 in and 450000 out.

    PRD 3.8 declares posting only from QUOTED - "posting a charge that is not
    QUOTED is refused with ERR_CHARGE_INVALID_STATE" - and makes VOIDED terminal:
    "voiding an already-VOIDED charge is refused with ERR_CHARGE_INVALID_STATE".
    The ledger is what makes the replays worth refusing: PRD 3.8 raises
    ancillary_posted_cents by the charge's net_amount_cents on the post and lowers
    it by the same figure on the compensating void, so a second post that quietly
    succeeded would double-count 450000 and a second void would drive the ledger
    negative.

    Design: Corner/validations/charge_post_and_void_are_each_one_shot
    """
    world = seed_signed_contract(api)
    charge = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
        post=True,
    )
    assert_ancillary_charge(
        charge, status=ChargeStatus.POSTED, net_amount_cents=450000
    )

    validate_error(
        api.post_ancillary_charge(charge["id"], ACCOUNTING_CLERK),
        ApiErrorId.CHARGE_INVALID_STATE,
        409,
    )
    assert_group_contract(
        read_contract(api, world["contract_id"]), ancillary_posted_cents=450000
    )

    voided = validate_success(
        api.void_ancillary_charge(charge["id"], ACCOUNTING_CLERK)
    )
    assert_ancillary_charge(voided, status=ChargeStatus.VOIDED)

    validate_error(
        api.void_ancillary_charge(charge["id"], ACCOUNTING_CLERK),
        ApiErrorId.CHARGE_INVALID_STATE,
        409,
    )

    final = read_contract(api, world["contract_id"])
    assert_group_contract(
        final, ancillary_posted_cents=0, receivable_total_cents=0
    )
    assert_receivable_identity(final)


def test_a_decided_study_cannot_be_re_approved_or_flipped(api):
    """The one-shot guard answers below the version check and above the outcome.

    PRD 2.8 puts the replay guard at priority 11, below the version guard at
    priority 8, so both replays here carry the lead version as it stands after the
    first decision - a stale guard would have produced a 412 and hidden the rule
    under test. PRD 3.3 refuses "a second decision against an already-decided
    study" with ERR_ANALYSIS_ALREADY_DECIDED, and that covers the contradicting
    REJECT as much as the identical APPROVE: a third revenue manager cannot flip a
    settled question, so the lead stays CLEARED instead of being dragged to LOST,
    and its version does not move.

    Design: Corner/validations/deciding_an_already_decided_analysis_is_refused
    """
    world = seed_cleared_lead(api)
    settled = lead_version(api, world["lead_id"])

    validate_error(
        api.decide_displacement_analysis(
            world["analysis_id"],
            F.decide_payload(decision="APPROVE", expected_lead_version=settled),
            REVENUE_MANAGER_ALT,
        ),
        ApiErrorId.ANALYSIS_ALREADY_DECIDED,
        409,
    )
    validate_error(
        api.decide_displacement_analysis(
            world["analysis_id"],
            F.decide_payload(decision="REJECT", expected_lead_version=settled),
            REVENUE_MANAGER_THIRD,
        ),
        ApiErrorId.ANALYSIS_ALREADY_DECIDED,
        409,
    )

    assert_displacement_analysis(
        validate_success(
            api.get_displacement_analysis(world["analysis_id"], REVENUE_MANAGER)
        ),
        status=AnalysisStatus.APPROVED,
        decided_by_user_id=REVENUE_MANAGER_ALT_ID,
    )
    assert_lead(
        read_lead(api, world["lead_id"]),
        status=LeadStatus.CLEARED,
        version=settled,
    )


def test_finalizing_the_settlement_freezes_the_charge_and_the_block(api):
    """One irreversible step, and three different rows refuse to move afterwards.

    PRD 3.9 walks the waterfall in order: with no reservations at all the
    commitment is ceil(12 * 0.75) = 9 room nights, all of them short, so the
    damages are 9 * 20880 * 0.85 = 159732; the 450000 banquet net joins them in
    gross_settlement_cents; the rebate is "750 cents per billable room night,
    capped at 25% of the group room revenue actually earned" and billable room
    nights are 0, so nothing is paid out; and the incentive is the account's own
    standing of 0.01, giving 6097 and a total of 603635. PRD 3.9 then makes
    finalization the point of no return - a second finalize is
    ERR_RECONCILIATION_ALREADY_FINALIZED - and PRD 3.8 refuses to unwind settled
    money: "voiding a posted charge whose contract already carries a FINALIZED
    settlement is refused with ERR_RECEIVABLE_ALREADY_SETTLED". PRD 3.7 closes the
    third door, since "waiving a block whose billing_status is already WAIVED or
    already SETTLED is refused with ERR_BLOCK_ALREADY_BILLED". The completed
    programme is what lifts the account to the middle rung of PRD 3.1.

    Design: Corner/validations/a_settled_receivable_freezes_every_downstream_write
    """
    world = seed_open_master_block(api)
    charge = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
        post=True,
    )
    seed_cut_off_master(api, world)
    seed_draft_reconciliation(api, world)

    settlement = validate_success(
        api.finalize_reconciliation(world["reconciliation_id"], ACCOUNTING_CLERK_ALT)
    )

    assert_reconciliation(
        settlement,
        status=ReconciliationStatus.FINALIZED,
        finalized_by_user_id=ACCOUNTING_CLERK_ALT_ID,
        attrition_shortfall_room_nights=9,
        attrition_damages_cents=159732,
        ancillary_net_cents=450000,
        gross_settlement_cents=609732,
        rebate_payable_cents=0,
        net_before_incentive_cents=609732,
        incentive_rate_snapshot=0.01,
        rebooking_incentive_cents=6097,
        total_settlement_cents=603635,
    )
    assert_waterfall_identities(settlement)

    validate_error(
        api.finalize_reconciliation(world["reconciliation_id"], ACCOUNTING_CLERK_ALT),
        ApiErrorId.RECONCILIATION_ALREADY_FINALIZED,
        409,
    )
    validate_error(
        api.void_ancillary_charge(charge["id"], ACCOUNTING_CLERK),
        ApiErrorId.RECEIVABLE_ALREADY_SETTLED,
        409,
    )
    validate_error(
        api.waive_attrition(
            world["master_block_id"],
            F.waive_attrition_payload(
                waiver_reason="Long-standing account, GM approved"
            ),
            REVENUE_MANAGER,
        ),
        ApiErrorId.BLOCK_ALREADY_BILLED,
        409,
    )

    contract = read_contract(api, world["contract_id"])
    assert_group_contract(
        contract,
        status=ContractStatus.COMPLETED,
        assessed_damages_cents=159732,
        rebate_paid_cents=0,
        receivable_total_cents=609732,
    )
    assert_receivable_identity(contract)
    assert_room_block(
        read_block(api, world["master_block_id"]),
        inventory_status=BlockInventoryStatus.CLOSED,
        billing_status=BlockBillingStatus.SETTLED,
    )
    assert_group_account(
        validate_success(api.get_account(world["account_id"], REVENUE_MANAGER)),
        repeat_group_count=1,
        rebooking_incentive_pct=0.03,
    )
