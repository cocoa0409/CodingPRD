"""Derived money: which inputs go in, and when they are re-derived.

PRD 2.10 warns that "derived quantities are recomputed rather than adjusted by
inference", and PRD 3.8 and PRD 3.9 pin each figure to a named input set - the
package discount for a category, the POSTED charges for the ledger, the notice
tier for damages, and the repeat history for the incentive ladder.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    ACCOUNTING_CLERK_ALT,
    CONTRACT_ADMIN,
    RESERVATIONS_AGENT,
    REVENUE_MANAGER,
    CancellationReason,
    ChargeCategory,
    ChargeStatus,
    ContractStatus,
    ForceMajeureClause,
    ReconciliationStatus,
    ReservationStatus,
    assert_ancillary_charge,
    assert_group_account,
    assert_group_contract,
    assert_receivable_identity,
    assert_reconciliation,
    assert_reservation,
    assert_room_block,
    committed_rooms,
    constants as C,
    factories as F,
    night_on,
    read_block,
    read_contract,
    seed_accepted_quote,
    seed_ancillary_charge,
    seed_calendar_and_package,
    seed_cleared_lead,
    seed_cut_off_master,
    seed_draft_contract,
    seed_draft_quote,
    seed_draft_reconciliation,
    seed_finalized_reconciliation,
    seed_open_master_block,
    seed_proposed_quote,
    seed_qualified_lead,
    seed_reservations,
    seed_sent_contract,
    seed_signed_contract,
    set_clock,
    validate_success,
)

_COMP_RICH = F.package_payload(
    name="Comp Rich",
    room_rate_discount_pct=0.05,
    comp_room_ratio=2,
    rebate_per_room_night_cents=0,
    banquet_discount_pct=0.05,
    av_discount_pct=0.1,
    parking_discount_pct=0.02,
    min_peak_rooms=1,
    min_total_room_nights=1,
    max_discount_stack_pct=0.3,
)
_ONE_NIGHT = {"arrival_date": "2026-11-09", "departure_date": "2026-11-10"}
_ROOMING_LIST = [dict(_ONE_NIGHT, guest_name=name) for name in ("Alpha", "Bravo", "Charlie", "Delta")]


def _walk_to_open_master(api, world):
    """Carry one world from a cleared lead all the way to an OPEN master block."""
    seed_cleared_lead(api, world)
    seed_draft_quote(api, world, quote={"base_rate_cents": 20000})
    seed_proposed_quote(api, world)
    seed_accepted_quote(api, world)
    seed_draft_contract(api, world)
    seed_sent_contract(api, world)
    seed_signed_contract(api, world)
    seed_open_master_block(api, world)
    return world


def test_cancelling_the_second_guest_moves_the_comp_onto_the_fourth(api):
    """The comp walk restarts from scratch, so the freebie changes hands.

    PRD 3.6 re-derives the designation "across the contract's entire reservation
    set ... whenever a reservation is created or cancelled", walking the
    non-cancelled rows "in ascending created_at order (the row id is never
    consulted)" and awarding the freebie whenever the paid room nights so far
    divided by the ratio, fraction discarded, exceeds the count already awarded.
    With a ratio of 2 the third of four one-night guests is the earned freebie;
    once the second guest is cancelled the same walk lands on the fourth, and
    "cancelling one guest can move the complimentary designation onto a
    completely different guest, flipping that guest's rate_cents from the
    contracted rate to zero". The contracted rate here is 20000 less the 1000
    rate discount less the 6667 comp amortization spread over one more than the
    ratio.

    Design: Corner/calculations/comp_designation_moves_when_an_earlier_reservation_is_cancelled
    """
    world = seed_qualified_lead(api, seed_calendar_and_package(api, package=_COMP_RICH))
    _walk_to_open_master(api, world)
    assert_group_contract(
        read_contract(api, world["contract_id"]), contracted_rate_cents=12333
    )
    alpha, bravo, charlie, delta = seed_reservations(
        api, world["master_block_id"], _ROOMING_LIST
    )
    assert [row["is_comp"] for row in (alpha, bravo, charlie, delta)] == [
        False,
        False,
        True,
        False,
    ], "the third guest earns the first freebie"
    assert [row["rate_cents"] for row in (alpha, charlie, delta)] == [12333, 0, 12333]

    cancelled = validate_success(
        api.cancel_reservation(
            bravo["id"],
            F.cancel_reservation_payload(disposition_reason="Traveller dropped out"),
            RESERVATIONS_AGENT,
        )
    )

    assert_reservation(cancelled, status=ReservationStatus.CANCELLED)
    assert_reservation(
        validate_success(api.get_reservation(charlie["id"], RESERVATIONS_AGENT)),
        is_comp=False,
        rate_cents=12333,
    )
    assert_reservation(
        validate_success(api.get_reservation(delta["id"], RESERVATIONS_AGENT)),
        is_comp=True,
        rate_cents=0,
    )
    assert_room_block(
        read_block(api, world["master_block_id"]),
        comp_room_nights=1,
        picked_up_room_nights=3,
    )
    night = night_on(api, world["master_block_id"], "2026-11-09")
    assert (night["rooms_picked_up"], night["rooms_open"]) == (3, 1), (
        f"the cancel returned one room to the night: {night}"
    )


def test_each_category_takes_its_own_discount_and_internet_takes_none(api):
    """Four categories, four discounts, and none of them touch the ledger yet.

    PRD 3.8 reads the package "reached from the contract through its quote_id to
    that quote's concession_package_id" and takes discount_pct "directly from
    that package: the banquet_discount_pct for a BANQUET charge, the
    av_discount_pct for an AUDIOVISUAL charge, the parking_discount_pct for a
    PARKING charge, and exactly 0.0 for an INTERNET charge - internet is never
    discounted, whatever the package says". Each net is one rounding of gross
    times one less the discount. "A new charge starts in QUOTED, which means it
    sits outside the settlement input set until it is posted", so the contract's
    ledger stays at zero.

    Design: Corner/calculations/ancillary_net_uses_the_package_discount_for_each_category
    """
    world = seed_signed_contract(api)

    banquet = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
    )
    audiovisual = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.AUDIOVISUAL,
        gross_amount_cents=200000,
    )
    parking = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.PARKING,
        gross_amount_cents=100000,
    )
    internet = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.INTERNET,
        gross_amount_cents=100000,
    )

    assert_ancillary_charge(
        banquet,
        discount_pct=0.10,
        net_amount_cents=450000,
        status=ChargeStatus.QUOTED,
    )
    assert_ancillary_charge(audiovisual, discount_pct=0.15, net_amount_cents=170000)
    assert_ancillary_charge(parking, discount_pct=0.05, net_amount_cents=95000)
    assert_ancillary_charge(internet, discount_pct=0.0, net_amount_cents=100000)

    contract = read_contract(api, world["contract_id"])
    assert_group_contract(
        contract, ancillary_posted_cents=0, receivable_total_cents=0
    )
    assert_receivable_identity(contract)


def test_the_ledger_follows_only_the_posted_charges_and_unwinds_cleanly(api):
    """Quoted money is invisible, and a posted void gives back the net exactly.

    PRD 3.8 sums ancillary_posted_cents over the contract's POSTED charges only,
    so a QUOTED charge is outside the input set and voiding one moves no money at
    all, while voiding a charge that had been posted must take its own
    net_amount_cents - not its gross - back out again. PRD 3.8 keeps
    receivable_total_cents equal to the posted total plus assessed damages less
    the rebate paid throughout, so the round trip returns the ledger to exactly
    the value it had before the parking charge existed.

    Design: Corner/calculations/only_posted_charges_move_the_contract_ledger
    """
    world = seed_signed_contract(api)

    banquet = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
        post=True,
    )
    assert_ancillary_charge(banquet, status=ChargeStatus.POSTED)
    assert_group_contract(
        read_contract(api, world["contract_id"]),
        ancillary_posted_cents=450000,
        receivable_total_cents=450000,
    )

    audiovisual = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.AUDIOVISUAL,
        gross_amount_cents=200000,
    )
    assert_group_contract(
        read_contract(api, world["contract_id"]), ancillary_posted_cents=450000
    )
    assert_ancillary_charge(
        validate_success(
            api.void_ancillary_charge(audiovisual["id"], ACCOUNTING_CLERK)
        ),
        status=ChargeStatus.VOIDED,
    )
    assert_group_contract(
        read_contract(api, world["contract_id"]), ancillary_posted_cents=450000
    )

    parking = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.PARKING,
        gross_amount_cents=100000,
        post=True,
    )
    assert_group_contract(
        read_contract(api, world["contract_id"]), ancillary_posted_cents=545000
    )

    assert_ancillary_charge(
        validate_success(api.void_ancillary_charge(parking["id"], ACCOUNTING_CLERK)),
        status=ChargeStatus.VOIDED,
    )

    final = read_contract(api, world["contract_id"])
    assert_group_contract(
        final,
        ancillary_posted_cents=450000,
        receivable_total_cents=450000,
        assessed_damages_cents=0,
        rebate_paid_cents=0,
    )
    assert_receivable_identity(final)


def _walk_to_sent_contract(api, world, *, contract=None, override_reason=None):
    """Carry one world from a qualified lead to a SENT contract at base 23950.

    ``override_reason`` is threaded through to the clearing decision because PRD
    3.3 measures displacement against "the day's total_rooms less its
    committed_group_rooms less its held_group_rooms": a second programme booked
    onto the same calendar while the first still holds rooms displaces more
    transient demand, and PRD 3.3 then admits the approval only when "the
    payload supplies a non-blank override_reason".
    """
    seed_cleared_lead(api, world, override_reason=override_reason)
    seed_draft_quote(api, world)
    seed_proposed_quote(api, world)
    seed_accepted_quote(api, world)
    seed_draft_contract(api, world, contract=contract)
    seed_sent_contract(api, world)
    return world


def test_ninety_days_notice_prices_one_tier_and_no_clause_halves_it(api):
    """The same date, the same rate, two different cancellation branches.

    PRD 3.9 measures the notice as "the whole days from the current logical clock
    date to the contract's arrival_date" and sets "0.50 at 90 days or more ...
    every boundary inclusive", so a cancellation exactly 90 days out buys the
    cheaper of the two adjacent tiers. The mitigated base is contracted_room_nights
    less the room nights the master block picked up - "zero when no block exists
    yet, as on a SENT contract" - times contracted_rate_cents. CLIENT_CANCEL then
    "yields the mitigated base multiplied by the tier percentage", while
    FORCE_MAJEURE against a clause of NONE "yields the mitigated base multiplied
    by the tier percentage multiplied by the no-clause factor of 0.50 ... because
    the event was genuinely beyond control but the contract bought no
    protection". Neither contract was ever countersigned, so the house calendar
    never took a commitment.

    Design: Corner/calculations/cancellation_tier_is_inclusive_at_ninety_days_and_the_no_clause_factor_halves_it
    """
    base = seed_calendar_and_package(api)
    protected = _walk_to_sent_contract(api, seed_qualified_lead(api, base))
    unprotected = _walk_to_sent_contract(
        api,
        seed_qualified_lead(
            api, base, lead={"program_name": "Northwind Regional Summit"}
        ),
        contract={"force_majeure_clause": ForceMajeureClause.NONE},
        override_reason="Second programme on the same nights; GM accepts the displacement",
    )
    assert unprotected["quote"]["effective_net_rate_cents"] == 20880, (
        "both programmes must price identically for the comparison to mean anything"
    )
    set_clock(api, "2026-08-11T00:00:00Z")

    cancelled = validate_success(
        api.cancel_contract(
            protected["contract_id"],
            F.cancel_contract_payload(
                cancellation_reason=CancellationReason.CLIENT_CANCEL,
                note="Programme moved to a competitor",
            ),
            CONTRACT_ADMIN,
        )
    )
    terminated = validate_success(
        api.cancel_contract(
            unprotected["contract_id"],
            F.cancel_contract_payload(
                cancellation_reason=CancellationReason.FORCE_MAJEURE,
                note="Regional travel ban",
            ),
            CONTRACT_ADMIN,
        )
    )

    assert_group_contract(
        cancelled,
        status=ContractStatus.CANCELLED,
        assessed_damages_cents=125280,
        receivable_total_cents=125280,
    )
    assert_receivable_identity(cancelled)
    assert_group_contract(
        terminated,
        status=ContractStatus.TERMINATED_FORCE_MAJEURE,
        assessed_damages_cents=62640,
        receivable_total_cents=62640,
    )
    assert_receivable_identity(terminated)
    assert committed_rooms(api, C.STAY_DATES) == [0, 0, 0]


def test_the_incentive_ladder_decays_one_rung_the_day_after_two_years(api):
    """One stored row answers three different rates as the clock moves.

    PRD 3.1 re-derives the standing "on every single read of the organization,
    against the logical clock, rather than being cached at the moment a contract
    completes": one completed contract lifts the base rung to 0.03, and the
    account "is then treated as lapsed when last_completed_departure_date is not
    null and the whole days from that date to the current logical clock date
    exceed 730". 730 days after a 2026-11-12 departure is not yet more than 730,
    so the rate holds; one day later "a lapsed account decays exactly one tier -
    0.05 becomes 0.03, 0.03 becomes 0.01". No reservation ever actualized, so the
    lifetime room nights stay at 0, and because a read is not a write the
    account's version never moves.

    Design: Corner/calculations/rebooking_tier_decays_one_step_once_the_lapse_window_is_exceeded
    """
    world = seed_open_master_block(api)
    seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
        post=True,
    )
    seed_cut_off_master(api, world)
    seed_draft_reconciliation(api, world, at_clock="2026-11-12T00:00:00Z")
    seed_finalized_reconciliation(api, world, finalizer=ACCOUNTING_CLERK_ALT)
    assert_reconciliation(
        world["reconciliation"], status=ReconciliationStatus.FINALIZED
    )

    completed = validate_success(
        api.get_account(world["account_id"], REVENUE_MANAGER)
    )
    assert_group_account(
        completed,
        repeat_group_count=1,
        lifetime_actualized_room_nights=0,
        last_completed_departure_date="2026-11-12",
        rebooking_incentive_pct=0.03,
    )

    set_clock(api, "2028-11-11T00:00:00Z")
    assert_group_account(
        validate_success(api.get_account(world["account_id"], REVENUE_MANAGER)),
        rebooking_incentive_pct=0.03,
    )

    set_clock(api, "2028-11-12T00:00:00Z")
    lapsed = validate_success(api.get_account(world["account_id"], REVENUE_MANAGER))
    assert_group_account(lapsed, rebooking_incentive_pct=0.01)
    assert lapsed["version"] == completed["version"], (
        "re-tiering is derived on read and must not write the row"
    )
