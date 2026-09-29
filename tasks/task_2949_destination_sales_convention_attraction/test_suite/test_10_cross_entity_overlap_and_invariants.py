"""Gates that live on a third entity, per-night contention, and conserved sums.

Queue A (difficulty index) translations for the ``cross_entity_state_dependency``,
``resource_temporal_overlap`` and ``compensating_invariant`` rules: a submission
refused by hold state rather than by anything on the package, a commit refused by
participation state re-read at commit time, room inventory contended per night
rather than per event, one promotion chosen out of two eligible second options,
and the fund and hotel counters returning to their exact prior values after a
reversal.
"""
from test_helpers import api_client, same_instant, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fund_conservation_identity,
    assert_money_equals,
)
from test_helpers import fixtures as fx
from test_helpers.factories import submit_payload
from test_helpers.types import (
    BidPackageStatus,
    CommitmentStatus,
    FundPosture,
    HoldPosture,
    HoldRank,
    ParticipationStatus,
    ReleaseReason,
    SalesStage,
    SpaceHoldStatus,
)


# --- cross_entity_state_dependency -------------------------------------------

def _approved_bid_whose_hold_was_given_back() -> dict:
    """Every package-local submission gate green, but no live hold anywhere."""
    scenario = fx.setup_bid_approved()
    released = fx.release_hold(scenario["hold_id"])
    scenario["released_hold"] = released
    return scenario


def test_submission_fails_on_hold_state_held_by_a_third_entity(api):
    """The package is flawless; the missing live hold sinks the submission.

    PRD: "The lead must hold at least one space hold in status `HELD`,
    `CHALLENGED` or `CONFIRMED`, or the submission fails with
    `ERR_NO_ACTIVE_SPACE_HOLD`" (PRD 3.8).
    PRD: "29. An active space hold existing at submission time --
    `ERR_NO_ACTIVE_SPACE_HOLD`, 422, on submission" (PRD 2.7).

    Design: Difficulty/cross_entity_state_dependency/bid_submission_depends_on_a_live_space_hold_on_another_entity
    """
    scenario = _approved_bid_whose_hold_was_given_back()
    bid_before = fx.read_bid(scenario["bid_id"])
    # Every gate that lives on the package itself is satisfied.
    assert bid_before["status"] == BidPackageStatus.APPROVED.value
    assert bid_before["support_letter_type_count"] == 2
    assert_money_equals(
        fx.read_opportunity(scenario["opportunity_id"])["block_coverage_pct"],
        90.00, "block_coverage_pct",
    )
    assert fx.read_opportunity(scenario["opportunity_id"])["cutoff_alignment_spread_days"] == 0
    assert scenario["released_hold"]["status"] == SpaceHoldStatus.RELEASED.value
    assert fx.read_opportunity(scenario["opportunity_id"])["hold_posture"] == (
        HoldPosture.RELEASED.value
    )

    response = api_client.submit_bid_package(
        scenario["bid_id"], submit_payload("2027-04-01T00:00:00Z"), fx.SALES
    )

    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_SPACE_HOLD.value, 422)
    bid_after = fx.read_bid(scenario["bid_id"])
    assert bid_after["status"] == BidPackageStatus.APPROVED.value
    assert bid_after["submitted_at"] is None
    assert bid_after["response_due_at"] is None
    assert fx.read_opportunity(scenario["opportunity_id"])["sales_stage"] == (
        SalesStage.QUALIFIED.value
    )


def test_re_holding_the_hall_makes_the_identical_submission_succeed(api):
    """The dependency is on live hold state, not on hold history.

    PRD: "Holds in `RELEASED` or `EXPIRED` never block anything" and "the hold is
    created in status `HELD`, with `hold_rank` set to `FIRST` when the blocking
    set was empty" (PRD 3.3).
    PRD: "A successful submission stamps `submitted_at` from the logical clock,
    stores `response_due_at`, and moves the package from `APPROVED` to `SUBMITTED`
    ... the lead's `sales_stage` moves from `QUALIFIED` to `BIDDING`" (PRD 3.8).

    Design: Difficulty/cross_entity_state_dependency/bid_submission_depends_on_a_live_space_hold_on_another_entity
    """
    scenario = _approved_bid_whose_hold_was_given_back()
    replacement = fx.place_hold(scenario["opportunity_id"], scenario["hall_id"])
    assert replacement["hold_rank"] == HoldRank.FIRST.value
    assert replacement["status"] == SpaceHoldStatus.HELD.value

    submitted = fx.submit_bid(scenario["bid_id"], "2027-04-01T00:00:00Z")

    assert submitted["status"] == BidPackageStatus.SUBMITTED.value
    assert same_instant(submitted["submitted_at"], "2027-03-01T00:00:00Z")
    assert same_instant(submitted["response_due_at"], "2027-04-01T00:00:00Z")
    assert fx.read_opportunity(scenario["opportunity_id"])["sales_stage"] == (
        SalesStage.BIDDING.value
    )
    # The released hold is still on file and still not active.
    assert fx.read_hold(scenario["hold_id"])["status"] == SpaceHoldStatus.RELEASED.value


def _offered_block_at_a_suspended_property() -> dict:
    """A legitimately OFFERED row whose hotel was suspended afterwards."""
    scenario = fx.setup_lead()
    harborview = scenario["hotels"][0]
    commitment = fx.invite_hotel(scenario["opportunity_id"], harborview["id"], 500)
    offered = fx.offer_block(commitment["id"], harborview["id"], 500, 214.33, 30)
    suspended = fx.suspend_hotel(harborview["id"])
    scenario["hotel_id"] = harborview["id"]
    scenario["commitment_id"] = commitment["id"]
    scenario["offered"] = offered
    scenario["suspended"] = suspended
    return scenario


def test_commit_reads_hotel_participation_at_commit_time(api):
    """The offer was legal; the hotel's later suspension still stops the commit.

    PRD: "Committing is the bureau's decision, taken by a `SalesManager` on a
    commitment in status `OFFERED`, with the lead still in `QUALIFIED` or
    `BIDDING` and the property still `PARTICIPATING`" (PRD 3.5).
    PRD: "17. The hotel's `participation_status` being `PARTICIPATING` --
    `ERR_HOTEL_NOT_PARTICIPATING`, 409, on room-block-commitment creation, offer
    and commit" (PRD 2.7).

    Design: Difficulty/cross_entity_state_dependency/commit_depends_on_hotel_participation_state_at_commit_time
    """
    scenario = _offered_block_at_a_suspended_property()
    assert scenario["offered"]["status"] == CommitmentStatus.OFFERED.value
    # 2028-04-10 less 30 days.
    assert scenario["offered"]["cutoff_date"] == "2028-03-11"
    assert scenario["suspended"]["participation_status"] == (
        ParticipationStatus.SUSPENDED.value
    )

    response = api_client.commit_room_block_commitment(
        scenario["commitment_id"], fx.SALES
    )

    validate_error(response, ApiErrorId.ERR_HOTEL_NOT_PARTICIPATING.value, 409)
    assert fx.read_commitment(scenario["commitment_id"])["status"] == (
        CommitmentStatus.OFFERED.value
    )
    # Nothing was applied anywhere.
    assert fx.read_hotel(scenario["hotel_id"])["committed_peak_rooms"] == 0
    opportunity = fx.read_opportunity(scenario["opportunity_id"])
    assert_money_equals(opportunity["block_coverage_pct"], 0.00, "block_coverage_pct")
    assert opportunity["committed_peak_rooms"] == 0


def test_reinstating_the_property_lets_the_same_commit_move_the_counters(api):
    """Participation is re-read, so the identical call succeeds after a reinstate.

    PRD: "A successful commit freezes `rooms_peak_committed` at the value of
    `rooms_peak_offered` and sets `committed_room_nights` to `rooms_peak_committed`
    multiplied by the lead's `event_nights`" (PRD 3.5).
    PRD: "`block_coverage_pct` is that committed peak multiplied by 100 and divided
    by `peak_rooms_requested`, rounded half-up to two decimals" (PRD 3.5).

    Design: Difficulty/cross_entity_state_dependency/commit_depends_on_hotel_participation_state_at_commit_time
    """
    scenario = _offered_block_at_a_suspended_property()
    reinstated = fx.reinstate_hotel(scenario["hotel_id"])
    assert reinstated["participation_status"] == ParticipationStatus.PARTICIPATING.value

    committed = fx.commit_block(scenario["commitment_id"])

    assert committed["status"] == CommitmentStatus.COMMITTED.value
    assert committed["rooms_peak_committed"] == 500
    # 500 rooms over the two occupied nights 2028-04-10 and 2028-04-11.
    assert committed["committed_room_nights"] == 1_000
    assert fx.read_hotel(scenario["hotel_id"])["committed_peak_rooms"] == 500
    opportunity = fx.read_opportunity(scenario["opportunity_id"])
    assert_money_equals(opportunity["block_coverage_pct"], 50.00, "block_coverage_pct")


def test_the_participation_gate_also_guards_a_fresh_invitation(api):
    """A brand-new invitation for a suspended property is refused too.

    PRD: "17. The hotel's `participation_status` being `PARTICIPATING` --
    `ERR_HOTEL_NOT_PARTICIPATING`, 409, on room-block-commitment creation, offer
    and commit" (PRD 2.7).

    Design: Difficulty/cross_entity_state_dependency/commit_depends_on_hotel_participation_state_at_commit_time
    """
    scenario = _offered_block_at_a_suspended_property()

    response = api_client.create_room_block_commitment(
        {
            "opportunity_id": scenario["opportunity_id"],
            "hotel_id": scenario["hotel_id"],
            "rooms_peak_invited": 100,
            "expected_opportunity_version": fx.opportunity_version(
                scenario["opportunity_id"]
            ),
        },
        fx.SALES,
    )

    validate_error(response, ApiErrorId.ERR_HOTEL_NOT_PARTICIPATING.value, 409)
    rows, _meta = validate_paginated(
        api_client.list_room_block_commitments(
            fx.SALES, params={"opportunity_id": scenario["opportunity_id"]}
        )
    )
    assert [row["id"] for row in rows] == [scenario["commitment_id"]]


# --- resource_temporal_overlap -----------------------------------------------

def _bayside_loaded_across_touching_windows() -> dict:
    """Bayside Suites (400 rooms) carries 300 early nights and 400 late nights."""
    scenario = fx.setup_inventory()
    bayside_id = scenario["hotels"][1]["id"]

    early = fx.qualify_lead(
        fx.create_lead(
            scenario["planner_id"], event_name="Early Dentistry Congress 2028",
            arrival_date="2028-04-10", departure_date="2028-04-12",
        )["id"]
    )
    early_commitment = fx.add_committed_block(early["id"], bayside_id, 300, 209.77, 30)

    late = fx.qualify_lead(
        fx.create_lead(
            scenario["planner_id"], event_name="Late Orthodontics Forum 2028",
            arrival_date="2028-04-12", departure_date="2028-04-14",
        )["id"]
    )
    late_commitment = fx.add_committed_block(late["id"], bayside_id, 400, 214.33, 30)

    single = fx.qualify_lead(
        fx.create_lead(
            scenario["planner_id"], event_name="One Night Hygienists Meeting 2028",
            arrival_date="2028-04-11", departure_date="2028-04-12",
        )["id"]
    )
    single_commitment = fx.invite_hotel(single["id"], bayside_id, 101)
    single_offer = fx.offer_block(single_commitment["id"], bayside_id, 101, 205.00, 30)

    return {
        "bayside_id": bayside_id,
        "early_commitment": early_commitment,
        "late_commitment": late_commitment,
        "single_id": single["id"],
        "single_commitment_id": single_commitment["id"],
        "single_offer": single_offer,
    }


def test_touching_windows_never_contend_and_the_peak_is_a_nightly_maximum(api):
    """300 early rooms and 400 late rooms coexist; the hotel peak is 400, not 700.

    PRD: "A useful consequence of the half-open night convention: two conventions
    whose windows merely touch, one's `departure_date` equalling the other's
    `arrival_date`, share no occupied night and therefore never contend for the
    same room" (PRD 3.5).
    PRD: "`committed_peak_rooms` on the hotel is the **maximum** over every night
    of that night's occupied load -- an aggregate over dates, never a sum across
    them -- while `committed_room_nights` on the hotel is the plain sum of
    `committed_room_nights` across all of that property's commitments in status
    `COMMITTED`" (PRD 3.5).

    Design: Difficulty/resource_temporal_overlap/hotel_nightly_capacity_admits_touching_windows_and_rejects_a_shared_night
    """
    ctx = _bayside_loaded_across_touching_windows()
    assert ctx["early_commitment"]["status"] == CommitmentStatus.COMMITTED.value
    assert ctx["late_commitment"]["status"] == CommitmentStatus.COMMITTED.value

    hotel = fx.read_hotel(ctx["bayside_id"])
    # Nights 04-12 and 04-13 carry 400; nights 04-10 and 04-11 carry 300.
    assert hotel["committed_peak_rooms"] == 400
    # 300 * 2 + 400 * 2, a plain sum across commitments.
    assert hotel["committed_room_nights"] == 1_400
    assert ctx["single_offer"]["status"] == CommitmentStatus.OFFERED.value
    assert ctx["single_offer"]["offer_round"] == 1


def test_a_shared_night_is_contended_to_the_last_room(api):
    """101 rooms on the shared night is refused; exactly 100 lands on the ceiling.

    PRD: "For each of those nights, the property's already-occupied load is the sum
    of `rooms_peak_committed` across every commitment of that same hotel in status
    `COMMITTED` whose own opportunity occupies that same night. If that load plus
    the `rooms_peak_offered` now being committed would come out **strictly greater**
    than the property's `committable_rooms` on even one of those nights, the commit
    is refused with `ERR_HOTEL_CAPACITY_EXCEEDED` and HTTP 422; landing exactly on
    `committable_rooms` is allowed" (PRD 3.5).
    PRD: "from `OFFERED` it is a **self-loop** that leaves the status at `OFFERED`,
    overwrites the three offer fields and increments `offer_round` again" (PRD 3.5).

    Design: Difficulty/resource_temporal_overlap/hotel_nightly_capacity_admits_touching_windows_and_rejects_a_shared_night
    """
    ctx = _bayside_loaded_across_touching_windows()

    # Night 2028-04-11 already carries 300, so 300 + 101 = 401 > 400.
    refused = api_client.commit_room_block_commitment(
        ctx["single_commitment_id"], fx.SALES
    )
    validate_error(refused, ApiErrorId.ERR_HOTEL_CAPACITY_EXCEEDED.value, 422)
    assert fx.read_commitment(ctx["single_commitment_id"])["status"] == (
        CommitmentStatus.OFFERED.value
    )

    reoffered = fx.offer_block(
        ctx["single_commitment_id"], ctx["bayside_id"], 100, 205.00, 30
    )
    assert reoffered["rooms_peak_offered"] == 100
    assert reoffered["offer_round"] == 2

    committed = fx.commit_block(ctx["single_commitment_id"])

    assert committed["status"] == CommitmentStatus.COMMITTED.value
    assert committed["rooms_peak_committed"] == 100
    # One occupied night only.
    assert committed["committed_room_nights"] == 100
    hotel = fx.read_hotel(ctx["bayside_id"])
    # Night 04-11 now carries 300 + 100 = 400, still the maximum.
    assert hotel["committed_peak_rooms"] == 400
    # 300 * 2 + 400 * 2 + 100 * 1.
    assert hotel["committed_room_nights"] == 1_500


def _two_second_options_around_one_incumbent() -> dict:
    """Two SECOND holds that each conflict with the incumbent but not each other."""
    scenario = fx.setup_lead()
    hall_id = scenario["hall_id"]
    incumbent = fx.place_hold(scenario["opportunity_id"], hall_id)

    small = fx.qualify_lead(
        fx.create_lead(
            scenario["planner_id"], event_name="Small Prosthodontics Clinic 2028",
            peak_rooms_requested=400, total_room_nights_requested=800,
        )["id"]
    )
    # 2028-04-05 pulled back 48h is 2028-04-03, strictly before the incumbent's
    # 2028-04-13; the incumbent's 2028-04-08 pulled back is 2028-04-06, strictly
    # before 2028-04-07.  So H1 conflicts with the incumbent.
    small_hold = fx.place_hold(
        small["id"], hall_id,
        move_in_start="2028-04-05T00:00:00Z", move_out_end="2028-04-07T00:00:00Z",
    )

    large = fx.qualify_lead(
        fx.create_lead(
            scenario["planner_id"], event_name="Large Implantology Congress 2028",
            peak_rooms_requested=900, total_room_nights_requested=1_800,
        )["id"]
    )
    # 2028-04-14 pulled back 48h is 2028-04-12, strictly before 2028-04-13.  H2
    # conflicts with the incumbent, but 2028-04-12 is not before H1's 2028-04-07,
    # so H1 and H2 do not conflict with each other.
    large_hold = fx.place_hold(
        large["id"], hall_id,
        move_in_start="2028-04-14T00:00:00Z", move_out_end="2028-04-16T00:00:00Z",
    )

    fx.set_clock("2027-04-01T00:00:00Z")
    return {
        "hall_id": hall_id,
        "incumbent_id": scenario["opportunity_id"],
        "incumbent_hold": incumbent,
        "small_id": small["id"],
        "small_hold": small_hold,
        "large_id": large["id"],
        "large_hold": large_hold,
    }


def test_the_release_promotes_the_larger_opportunity_and_restamps_its_expiry(api):
    """Both second options are eligible; the 900-room lead wins and gets 30 days.

    PRD: "Candidates are exactly those holds on the same hall as the departing hold
    that are in status `HELD`, carry `hold_rank` `SECOND`, and whose buffered window
    conflicts with the departing hold's ... the winner is chosen by sorting the
    candidates by the `peak_rooms_requested` of their opportunity in descending
    order, breaking ties by the hold's own `created_at` in ascending order, and
    taking the first" (PRD 3.4).
    PRD: "The winner's `hold_rank` becomes `FIRST`, its `expires_at` is re-stamped
    at 30 days after the current logical clock, and its opportunity's
    `hold_posture` becomes `TENTATIVE`" (PRD 3.4).

    Design: Difficulty/resource_temporal_overlap/released_window_promotes_the_larger_of_two_overlapping_second_holds
    """
    ctx = _two_second_options_around_one_incumbent()
    assert ctx["incumbent_hold"]["hold_rank"] == HoldRank.FIRST.value
    assert same_instant(ctx["incumbent_hold"]["expires_at"], "2027-05-30T00:00:00Z")
    assert ctx["small_hold"]["hold_rank"] == HoldRank.SECOND.value
    assert ctx["large_hold"]["hold_rank"] == HoldRank.SECOND.value

    released = fx.release_hold(ctx["incumbent_hold"]["id"])

    assert released["status"] == SpaceHoldStatus.RELEASED.value
    assert released["release_reason"] == ReleaseReason.SCHEDULER_RELEASE.value
    promoted = fx.read_hold(ctx["large_hold"]["id"])
    assert promoted["hold_rank"] == HoldRank.FIRST.value
    assert promoted["status"] == SpaceHoldStatus.HELD.value
    # 2027-04-01 plus 30 days, not the incumbent's inherited 90-day expiry.
    assert same_instant(promoted["expires_at"], "2027-05-01T00:00:00Z")
    assert not same_instant(promoted["expires_at"], "2027-05-30T00:00:00Z")
    assert fx.read_opportunity(ctx["large_id"])["hold_posture"] == (
        HoldPosture.TENTATIVE.value
    )


def test_only_one_hold_is_promoted_per_vacated_window(api):
    """The 400-room lead keeps rank SECOND even though nothing blocks it now.

    PRD: "Exactly one hold is promoted per vacated window" (PRD 3.4).
    PRD: "Because the released hold left the active set, the releasing
    opportunity's `hold_posture` becomes `RELEASED`, but only once no hold of that
    opportunity remains in status `HELD` or `CHALLENGED`" (PRD 3.4).

    Design: Difficulty/resource_temporal_overlap/released_window_promotes_the_larger_of_two_overlapping_second_holds
    """
    ctx = _two_second_options_around_one_incumbent()

    fx.release_hold(ctx["incumbent_hold"]["id"])

    loser = fx.read_hold(ctx["small_hold"]["id"])
    assert loser["hold_rank"] == HoldRank.SECOND.value
    assert loser["status"] == SpaceHoldStatus.HELD.value
    assert fx.read_opportunity(ctx["small_id"])["hold_posture"] == HoldPosture.NONE.value
    assert fx.read_opportunity(ctx["incumbent_id"])["hold_posture"] == (
        HoldPosture.RELEASED.value
    )

    firsts, _meta = validate_paginated(
        api_client.list_space_holds(
            fx.SCHEDULER,
            params={"center_hall_id": ctx["hall_id"],
                    "hold_rank": HoldRank.FIRST.value,
                    "status": SpaceHoldStatus.HELD.value},
        )
    )
    assert [row["id"] for row in firsts] == [ctx["large_hold"]["id"]]


# --- compensating_invariant --------------------------------------------------

def _fund_charged_then_reversed_by_a_lost_lead() -> dict:
    """9450.00 charged against a 500000.00 fund, then reversed from the lead side."""
    scenario = fx.setup_lead()
    scenario["fund_at_cp0"] = fx.read_fund(scenario["fund_id"])
    bid = fx.open_bid(scenario["opportunity_id"])
    fx.ask_for_incentive(bid["id"], 9_000.00)
    scenario["decision_one"] = fx.decide_incentive(
        bid["id"], scenario["fund_id"], "APPROVED", 9_000.00,
        rationale="First charge, later reversed by losing the lead",
    )
    scenario["bid_one_id"] = bid["id"]
    scenario["fund_at_cp1"] = fx.read_fund(scenario["fund_id"])
    return scenario


def test_the_fund_ledger_returns_to_its_opening_values_after_a_reversal(api):
    """The 450.00 fee is unwound with the 9000.00 principal, to the cent.

    PRD: "Any live fund charge is decommitted: the fund's `committed_amount` falls
    by the package's `total_fund_charge_amount`, `uncommitted_amount` rises by the
    same amount, and `posture` is re-derived" (PRD 3.8).
    PRD: "`uncommitted_amount` is the residual: `budget_amount` less
    `committed_amount` less `disbursed_amount`" (PRD 2.10).

    Design: Difficulty/compensating_invariant/fund_ledger_identity_survives_charge_decommit_receipt_and_recharge
    """
    scenario = _fund_charged_then_reversed_by_a_lost_lead()

    cp0 = scenario["fund_at_cp0"]
    assert_money_equals(cp0["budget_amount"], 500_000.00, "CP0 budget_amount")
    assert_money_equals(cp0["committed_amount"], 0.00, "CP0 committed_amount")
    assert_money_equals(cp0["disbursed_amount"], 0.00, "CP0 disbursed_amount")
    assert_money_equals(cp0["uncommitted_amount"], 500_000.00, "CP0 uncommitted_amount")
    assert_money_equals(cp0["lodging_tax_receipts_total"], 0.00, "CP0 receipts total")
    assert_fund_conservation_identity(cp0)

    decision = scenario["decision_one"]
    assert_money_equals(decision["admin_fee_amount"], 450.00, "CP1 admin_fee_amount")
    assert_money_equals(decision["total_charge_amount"], 9_450.00, "CP1 total_charge_amount")
    cp1 = scenario["fund_at_cp1"]
    assert_money_equals(cp1["committed_amount"], 9_450.00, "CP1 committed_amount")
    assert_money_equals(cp1["disbursed_amount"], 0.00, "CP1 disbursed_amount")
    assert_money_equals(cp1["uncommitted_amount"], 490_550.00, "CP1 uncommitted_amount")
    assert_fund_conservation_identity(cp1)

    lost = fx.lose_lead(scenario["opportunity_id"], "RATE_TOO_HIGH")
    assert lost["sales_stage"] == SalesStage.LOST.value

    cp2 = fx.read_fund(scenario["fund_id"])
    assert_money_equals(cp2["budget_amount"], 500_000.00, "CP2 budget_amount")
    assert_money_equals(cp2["committed_amount"], 0.00, "CP2 committed_amount")
    assert_money_equals(cp2["disbursed_amount"], 0.00, "CP2 disbursed_amount")
    assert_money_equals(cp2["uncommitted_amount"], 500_000.00, "CP2 uncommitted_amount")
    assert cp2["posture"] == FundPosture.OPEN.value
    assert_fund_conservation_identity(cp2)


def test_a_receipt_raises_the_budget_and_a_fresh_charge_keeps_the_identity(api):
    """The ledger survives a receipt and a second charge with no cent of drift.

    PRD: "`budget_amount` is the fund's total appropriation and grows by the amount
    of every lodging-tax receipt posted to the fund; `lodging_tax_receipts_total`
    separately accumulates the same receipt amounts so the appropriation's origin
    remains auditable" (PRD 2.10).
    PRD: "`committed_amount` rises by `total_charge_amount`, `uncommitted_amount`
    falls by the same amount, and `posture` is re-derived" (PRD 3.7).

    Design: Difficulty/compensating_invariant/fund_ledger_identity_survives_charge_decommit_receipt_and_recharge
    """
    scenario = _fund_charged_then_reversed_by_a_lost_lead()
    fx.lose_lead(scenario["opportunity_id"], "RATE_TOO_HIGH")

    fx.post_receipt(scenario["fund_id"], 3_400.00, "2027-03-01T00:00:00Z")

    cp3 = fx.read_fund(scenario["fund_id"])
    assert_money_equals(cp3["lodging_tax_receipts_total"], 3_400.00, "CP3 receipts total")
    assert_money_equals(cp3["budget_amount"], 503_400.00, "CP3 budget_amount")
    assert_money_equals(cp3["uncommitted_amount"], 503_400.00, "CP3 uncommitted_amount")
    assert_fund_conservation_identity(cp3)

    second_lead = fx.qualify_lead(
        fx.create_lead(scenario["planner_id"], event_name="CDA Annual 2029",
                       arrival_date="2028-11-10", departure_date="2028-11-12")["id"]
    )
    bid_two = fx.open_bid(second_lead["id"])
    fx.ask_for_incentive(bid_two["id"], 9_000.00)
    decision_two = fx.decide_incentive(
        bid_two["id"], scenario["fund_id"], "APPROVED", 9_000.00,
        rationale="Fresh charge after the reversal",
    )

    assert_money_equals(decision_two["total_charge_amount"], 9_450.00, "CP4 charge")
    cp4 = fx.read_fund(scenario["fund_id"])
    assert_money_equals(cp4["budget_amount"], 503_400.00, "CP4 budget_amount")
    assert_money_equals(cp4["committed_amount"], 9_450.00, "CP4 committed_amount")
    assert_money_equals(cp4["disbursed_amount"], 0.00, "CP4 disbursed_amount")
    assert_money_equals(cp4["uncommitted_amount"], 493_950.00, "CP4 uncommitted_amount")
    assert_fund_conservation_identity(cp4)

    # The reversal moved the ledger; it deleted no history.
    rows, _meta = validate_paginated(
        api_client.list_fund_incentive_decisions(scenario["fund_id"], fx.APPROVER)
    )
    assert len(rows) == 2


def _two_properties_committed_then_one_ready_to_leave() -> dict:
    """Bayside at 300 rooms is the baseline; Harborview's 100 rooms sit on top."""
    scenario = fx.setup_lead()
    bayside_id = scenario["hotels"][1]["id"]
    harborview_id = scenario["hotels"][0]["id"]

    fx.add_committed_block(scenario["opportunity_id"], bayside_id, 300, 209.77, 30)
    scenario["baseline_bayside"] = fx.read_hotel(bayside_id)
    scenario["baseline_opportunity"] = fx.read_opportunity(scenario["opportunity_id"])

    beta = fx.add_committed_block(
        scenario["opportunity_id"], harborview_id, 100, 214.33, 30
    )
    scenario["bayside_id"] = bayside_id
    scenario["harborview_id"] = harborview_id
    scenario["beta_id"] = beta["id"]
    return scenario


def test_a_withdrawal_puts_all_three_derived_counters_back_to_the_baseline(api):
    """Harborview's exit inverts the nightly max, the sum and the coverage exactly.

    PRD: "**Hop 2.** Because rooms have left the block, `rooms_peak_committed` and
    `committed_room_nights` on the commitment are both reset to 0, the property's
    `committed_peak_rooms` and `committed_room_nights` are recomputed, and the
    lead's `committed_peak_rooms`, `block_coverage_pct` and
    `cutoff_alignment_spread_days` are recomputed from the commitments that remain
    committed" (PRD 3.5).
    PRD: "From `COMMITTED`, the reason must likewise be `PROPERTY_SOLD_OUT` or
    `RATE_DISPUTE`" (PRD 3.5).

    Design: Difficulty/compensating_invariant/hotel_room_counters_return_to_their_prior_values_after_withdraw
    """
    scenario = _two_properties_committed_then_one_ready_to_leave()
    baseline_hotel = scenario["baseline_bayside"]
    assert baseline_hotel["committed_peak_rooms"] == 300
    assert baseline_hotel["committed_room_nights"] == 600
    assert_money_equals(
        scenario["baseline_opportunity"]["block_coverage_pct"], 30.00, "baseline coverage"
    )
    harborview_before = fx.read_hotel(scenario["harborview_id"])
    assert harborview_before["committed_peak_rooms"] == 100
    assert harborview_before["committed_room_nights"] == 200
    before = fx.read_opportunity(scenario["opportunity_id"])
    assert before["committed_peak_rooms"] == 400
    assert_money_equals(before["block_coverage_pct"], 40.00, "coverage before")

    withdrawn = fx.withdraw_block(
        scenario["beta_id"], scenario["harborview_id"], "RATE_DISPUTE"
    )

    assert withdrawn["status"] == CommitmentStatus.WITHDRAWN.value
    assert withdrawn["rooms_peak_committed"] == 0
    assert withdrawn["committed_room_nights"] == 0
    harborview_after = fx.read_hotel(scenario["harborview_id"])
    assert harborview_after["committed_peak_rooms"] == 0
    assert harborview_after["committed_room_nights"] == 0
    after = fx.read_opportunity(scenario["opportunity_id"])
    assert after["committed_peak_rooms"] == 300
    assert_money_equals(after["block_coverage_pct"], 30.00, "coverage after")
    # The untouched property keeps its own nightly maximum and its own sum.
    bayside_after = fx.read_hotel(scenario["bayside_id"])
    assert bayside_after["committed_peak_rooms"] == 300
    assert bayside_after["committed_room_nights"] == 600


def test_the_counters_climb_back_through_a_new_commitment_row(api):
    """The round trip restores 100 / 200 / 40.00 without reviving the old row.

    PRD: "A successful commit freezes `rooms_peak_committed` at the value of
    `rooms_peak_offered` and sets `committed_room_nights` to `rooms_peak_committed`
    multiplied by the lead's `event_nights`. The property's aggregates are then
    re-derived" (PRD 3.5).
    PRD: "the lead's citywide figures are re-derived from its commitments in status
    `COMMITTED` only, with commitments in `INVITED`, `OFFERED`, `WITHDRAWN` and
    `RELEASED` all excluded" (PRD 3.5).

    Design: Difficulty/compensating_invariant/hotel_room_counters_return_to_their_prior_values_after_withdraw
    """
    scenario = _two_properties_committed_then_one_ready_to_leave()
    fx.withdraw_block(scenario["beta_id"], scenario["harborview_id"], "RATE_DISPUTE")

    gamma = fx.add_committed_block(
        scenario["opportunity_id"], scenario["harborview_id"], 100, 214.33, 30
    )

    assert gamma["status"] == CommitmentStatus.COMMITTED.value
    assert gamma["id"] != scenario["beta_id"]
    harborview = fx.read_hotel(scenario["harborview_id"])
    assert harborview["committed_peak_rooms"] == 100
    assert harborview["committed_room_nights"] == 200
    restored = fx.read_opportunity(scenario["opportunity_id"])
    assert restored["committed_peak_rooms"] == 400
    assert_money_equals(restored["block_coverage_pct"], 40.00, "coverage restored")

    rows, _meta = validate_paginated(
        api_client.list_room_block_commitments(
            fx.SALES, params={"opportunity_id": scenario["opportunity_id"]}
        )
    )
    statuses = sorted(row["status"] for row in rows)
    assert statuses == [
        CommitmentStatus.COMMITTED.value,
        CommitmentStatus.COMMITTED.value,
        CommitmentStatus.WITHDRAWN.value,
    ]
