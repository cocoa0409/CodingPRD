"""Rejection rules of the validation ladder, probed one rule at a time.

PRD 2.8 orders every refusal into a numbered ladder and names the error each
level answers with. These tests put a request one step over each line - an
empty interval, a floor missed by one, a plan that sums wrong - and then send
the admissible variant through the same endpoint to prove the rule and not the
endpoint did the refusing.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    RESERVATIONS_AGENT,
    REVENUE_MANAGER,
    REVENUE_MANAGER_ALT,
    REVENUE_MANAGER_ALT_ID,
    REVENUE_MANAGER_ID,
    SALES_MANAGER,
    AnalysisStatus,
    ApiErrorId,
    BlockInventoryStatus,
    ContractStatus,
    LeadStatus,
    ReservationStatus,
    SpaceCode,
    Verdict,
    assert_block_night,
    assert_concession_package,
    assert_displacement_analysis,
    assert_group_contract,
    assert_lead,
    assert_rate_quote,
    assert_reservation,
    assert_room_block,
    block_version,
    constants as C,
    factories as F,
    lead_version,
    night_on,
    read_lead,
    reset_clock,
    seed_accepted_quote,
    seed_account,
    seed_calendar_and_package,
    seed_cleared_lead,
    seed_displacement_analysis,
    seed_inventory_days,
    seed_lead,
    seed_open_master_block,
    seed_qualified_lead,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_empty_interval_is_refused_wherever_the_contract_declares_one(api):
    """Three date rules, three equalities, three refusals.

    PRD 2.8 puts intra-request date sanity at priority 7 and states all three
    comparisons strictly: "departure_date strictly after arrival_date on leads
    and reservations; end_at strictly after start_at on function-space holds;
    expires_at strictly after the current logical clock on quote creation and
    revision", each violation being ERR_INVALID_DATE_RANGE. Equality is the case
    a non-strict comparison lets through: a stay that departs on its arrival
    date, a session that ends when it starts, and a quote expiring on the very
    instant the clock stands at. The control quote then draws on the same lead
    and the same package, so only the date literal separated it from the
    refusals.

    Design: Corner/validations/date_range_rules_reject_empty_and_backwards_intervals
    """
    world = seed_cleared_lead(api)

    validate_error(
        api.create_lead(
            F.lead_payload(
                world["account_id"],
                program_name="Zero Night Stay",
                arrival_date="2026-11-09",
                departure_date="2026-11-09",
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.INVALID_DATE_RANGE,
        422,
    )
    validate_error(
        api.create_function_space_hold(
            F.function_space_hold_payload(
                world["lead_id"],
                space_code=SpaceCode.SALON_A,
                start_at="2026-11-09T09:00:00Z",
                end_at="2026-11-09T09:00:00Z",
                attendee_count=40,
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.INVALID_DATE_RANGE,
        422,
    )

    current = lead_version(api, world["lead_id"])
    validate_error(
        api.create_rate_quote(
            F.rate_quote_payload(
                world["lead_id"],
                world["package_id"],
                current,
                expires_at=C.CLOCK_DEFAULT,
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.INVALID_DATE_RANGE,
        422,
    )

    admissible = validate_success(
        api.create_rate_quote(
            F.rate_quote_payload(world["lead_id"], world["package_id"], current),
            SALES_MANAGER,
        ),
        201,
    )
    assert_rate_quote(admissible, effective_net_rate_cents=20880)

    _, meta = validate_paginated(
        api.list_rate_quotes(SALES_MANAGER, lead_id=world["lead_id"])
    )
    assert meta["total_count"] == 1, "only the admissible quote may exist"


def test_the_concession_floors_and_the_discount_cap_are_both_inclusive(api):
    """One unit under each floor is refused; the floors themselves are not.

    PRD 3.1 computes discount_stack_pct as "the sum of exactly four fractions -
    the room-rate discount, the banquet discount, the audiovisual discount, and
    the parking discount", refusing the package with ERR_DISCOUNT_STACK_EXCEEDED
    when that sum exceeds its cap, so 0.2 + 0.2 + 0.2 + 0.1 cannot be stored
    against a cap of 0.45. PRD 3.4 checks the package's floors when the quote is
    drafted: "quoted_peak_rooms must be at least min_peak_rooms and
    quoted_room_nights must be at least min_total_room_nights, both inclusive, or
    the draft is refused with ERR_CONCESSION_INELIGIBLE" - so 3 rooms and 11
    room nights fail while exactly 4 and exactly 12 succeed. The admitted quote
    also carries the pinned comp_room_ratio, which PRD 3.4 copies from the
    package at creation.

    Design: Corner/validations/package_eligibility_and_discount_stack_are_both_enforced
    """
    world = seed_cleared_lead(api)

    validate_error(
        api.create_package(
            F.package_payload(
                name="Over Stacked",
                room_rate_discount_pct=0.2,
                banquet_discount_pct=0.2,
                av_discount_pct=0.2,
                parking_discount_pct=0.1,
            ),
            REVENUE_MANAGER,
        ),
        ApiErrorId.DISCOUNT_STACK_EXCEEDED,
        422,
    )

    current = lead_version(api, world["lead_id"])
    validate_error(
        api.create_rate_quote(
            F.rate_quote_payload(
                world["lead_id"], world["package_id"], current, quoted_peak_rooms=3
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.CONCESSION_INELIGIBLE,
        422,
    )
    validate_error(
        api.create_rate_quote(
            F.rate_quote_payload(
                world["lead_id"], world["package_id"], current, quoted_room_nights=11
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.CONCESSION_INELIGIBLE,
        422,
    )

    admissible = validate_success(
        api.create_rate_quote(
            F.rate_quote_payload(world["lead_id"], world["package_id"], current),
            SALES_MANAGER,
        ),
        201,
    )
    assert_rate_quote(
        admissible, effective_net_rate_cents=20880, comp_room_ratio=40
    )
    assert_concession_package(
        validate_success(api.get_package(world["package_id"], REVENUE_MANAGER)),
        discount_stack_pct=0.3725,
    )


_SOLD_OUT_HOUSE = {
    "total_rooms": 400,
    "transient_demand_rooms": 400,
    "transient_adr_cents": 60000,
}


def test_approving_a_loss_making_program_needs_a_written_reason(api):
    """The gate is conditional on the arithmetic, and the refusal costs nothing.

    PRD 3.3 displaces "the smaller of the lead's peak_rooms and the rooms that
    would otherwise have been sold" on every occupied date, so a house with 400
    rooms and 400 transient rooms of demand at 60000 cents displaces all four
    rooms a night: 12 room nights at 60000 is 720000 against a group revenue of
    590400 plus an ancillary projection of 4500 per room night, leaving
    net_benefit_cents at -75600 and the verdict at OVERRIDE_REQUIRED. PRD 3.3
    then requires "either the study's verdict is ACCEPT, or the payload supplies a
    non-blank override_reason", refusing the bare approval with
    ERR_DISPLACEMENT_NET_BENEFIT_NEGATIVE. PRD 2.5 advances version only on a
    successful mutation, which is why the retry may reuse the very same
    expected_lead_version.

    Design: Corner/validations/negative_net_benefit_requires_an_override_reason
    """
    world = seed_qualified_lead(
        api, seed_calendar_and_package(api, inventory=_SOLD_OUT_HOUSE)
    )
    assert_lead(
        read_lead(api, world["lead_id"]),
        qualification_score=35,
        estimated_room_night_value_cents=590400,
    )
    analysis = seed_displacement_analysis(api, world)
    assert_displacement_analysis(
        analysis,
        displaced_room_nights=12,
        displaced_revenue_cents=720000,
        group_revenue_cents=590400,
        ancillary_projection_cents=54000,
        net_benefit_cents=-75600,
        verdict=Verdict.OVERRIDE_REQUIRED,
    )
    before = lead_version(api, world["lead_id"])

    validate_error(
        api.decide_displacement_analysis(
            analysis["id"],
            F.decide_payload(decision="APPROVE", expected_lead_version=before),
            REVENUE_MANAGER_ALT,
        ),
        ApiErrorId.DISPLACEMENT_NET_BENEFIT_NEGATIVE,
        422,
    )

    approved = validate_success(
        api.decide_displacement_analysis(
            analysis["id"],
            F.decide_payload(
                decision="APPROVE",
                expected_lead_version=before,
                override_reason="Strategic account, board-level relationship",
            ),
            REVENUE_MANAGER_ALT,
        )
    )

    assert_displacement_analysis(
        approved,
        status=AnalysisStatus.APPROVED,
        override_reason="Strategic account, board-level relationship",
    )
    assert_lead(
        read_lead(api, world["lead_id"]), status=LeadStatus.CLEARED, version=4
    )


def test_a_hole_in_the_house_calendar_stops_qualification_dead(api):
    """The last date of the range counts as much as the first.

    PRD 2.9 states that "nothing in the service invents a calendar date" and that
    "any gap in that range stops the operation with ERR_INVENTORY_DAY_MISSING
    rather than being treated as an empty day"; PRD 3.2 requires an inventory day
    for every date of the half-open stay range "even though the score itself
    reads no inventory figure". The missing date here is the last of the three, so
    an implementation that checks only the arrival date would score the lead. The
    refusal writes nothing, and once the hole is filled the identical call scores
    35 with a room-night value of 206640.

    Design: Corner/validations/a_gap_in_the_inventory_calendar_blocks_qualification
    """
    reset_clock(api)
    account = seed_account(api)
    seed_inventory_days(api, ["2026-11-09", "2026-11-10"])
    lead = seed_lead(api, account["id"])

    validate_error(
        api.qualify_lead(lead["id"], SALES_MANAGER),
        ApiErrorId.INVENTORY_DAY_MISSING,
        422,
    )

    assert_lead(
        read_lead(api, lead["id"]),
        status=LeadStatus.NEW,
        qualification_score=None,
        version=1,
    )

    validate_success(
        api.create_inventory_day(
            F.inventory_day_payload("2026-11-11"), REVENUE_MANAGER
        ),
        201,
    )

    assert_lead(
        validate_success(api.qualify_lead(lead["id"], SALES_MANAGER)),
        status=LeadStatus.QUALIFIED,
        qualification_score=35,
        estimated_room_night_value_cents=206640,
    )


def test_the_person_who_asked_the_question_may_not_answer_it(api):
    """Same role, different person: the refusal is a duty rule, not an RBAC one.

    PRD 3.3 requires that "the acting X-User-ID must differ from the study's
    requested_by_user_id, or the call is refused with
    ERR_SEGREGATION_OF_DUTIES - the person who asked the question may not answer
    it, even though one role covers both operations". PRD 2.6 answers a role that
    may not reach an operation with ERR_UNAUTHORIZED, so answering that here
    would be wrong: the requester holds exactly the role the decision needs. Only
    the header changes between the refusal and the approval that clears the lead.

    Design: Corner/validations/the_analysis_requester_may_not_decide_their_own_study
    """
    world = seed_qualified_lead(api)
    analysis = seed_displacement_analysis(api, world)
    assert_displacement_analysis(
        analysis, requested_by_user_id=REVENUE_MANAGER_ID, verdict=Verdict.ACCEPT
    )
    before = lead_version(api, world["lead_id"])

    validate_error(
        api.decide_displacement_analysis(
            analysis["id"],
            F.decide_payload(decision="APPROVE", expected_lead_version=before),
            REVENUE_MANAGER,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    approved = validate_success(
        api.decide_displacement_analysis(
            analysis["id"],
            F.decide_payload(decision="APPROVE", expected_lead_version=before),
            REVENUE_MANAGER_ALT,
        )
    )

    assert_displacement_analysis(
        approved,
        status=AnalysisStatus.APPROVED,
        decided_by_user_id=REVENUE_MANAGER_ALT_ID,
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.CLEARED)


def test_the_allotment_plan_must_agree_with_the_headline_on_all_three_counts(api):
    """Sum, peak and date range are one rule with three ways to fail it.

    PRD 3.5 requires that "the plan's rooms values must sum to
    contracted_room_nights, the largest single rooms value must equal
    contracted_peak_rooms, and the plan's dates must be exactly the lead's
    half-open stay range - no more and no less", answering any disagreement with
    ERR_ALLOTMENT_PLAN_MISMATCH. Each probe satisfies the other two parts: 4/4/3
    sums to 11, a peak of 5 contradicts a maximum of 4, and 2026-11-10 to -12 is
    distinct and contiguous and sums to 12 - so it clears the priority 7
    contiguity rule of PRD 2.8 and can only fail on the range equality. PRD 3.5
    then derives the contract's own dates from the lead, giving three nights from
    2026-11-09.

    Design: Corner/validations/the_allotment_plan_must_reconcile_with_the_contract_totals
    """
    world = seed_accepted_quote(api)

    validate_error(
        api.create_contract(
            F.contract_payload(
                world["quote_id"],
                nightly_allotments=F.allotment_plan(
                    ("2026-11-09", 4), ("2026-11-10", 4), ("2026-11-11", 3)
                ),
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.ALLOTMENT_PLAN_MISMATCH,
        422,
    )
    validate_error(
        api.create_contract(
            F.contract_payload(world["quote_id"], contracted_peak_rooms=5),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.ALLOTMENT_PLAN_MISMATCH,
        422,
    )
    validate_error(
        api.create_contract(
            F.contract_payload(
                world["quote_id"],
                nightly_allotments=F.allotment_plan(
                    ("2026-11-10", 4), ("2026-11-11", 4), ("2026-11-12", 4)
                ),
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.ALLOTMENT_PLAN_MISMATCH,
        422,
    )

    contract = validate_success(
        api.create_contract(F.contract_payload(world["quote_id"]), CONTRACT_ADMIN), 201
    )

    assert_group_contract(
        contract,
        status=ContractStatus.DRAFT,
        contracted_rate_cents=20880,
        arrival_date="2026-11-09",
        nights_count=3,
    )
    _, meta = validate_paginated(
        api.list_contracts(CONTRACT_ADMIN, quote_id=world["quote_id"])
    )
    assert meta["total_count"] == 1, "the three rejected plans created nothing"


def test_a_rooming_list_entry_must_fit_the_block_and_not_repeat_a_guest(api):
    """A partly covered stay is refused whole; the same guest on another night is not.

    PRD 3.6 requires that "the reservation's half-open stay range must be fully
    covered by nights of that block, or ERR_STAY_DATE_OUTSIDE_BLOCK; a guest may
    not shoulder a night the block does not hold, even when the contract's own
    dates cover it" - so a stay arriving 2026-11-08 is rejected rather than
    truncated to the nights that do exist. The duplicate guard is keyed
    precisely: "no other non-cancelled reservation on the same contract may
    already carry the same guest_name with the same arrival_date, or
    ERR_DUPLICATE_ROOMING_LIST_ENTRY", so the same guest arriving a day later is
    a different entry and must be accepted. Exactly two entries land, one room
    night each.

    Design: Corner/validations/rooming_list_writes_must_fit_the_block_and_stay_unique
    """
    world = seed_open_master_block(api)
    block_id = world["master_block_id"]

    validate_error(
        api.create_reservation(
            F.reservation_payload(
                block_id,
                guest_name="Edge Case",
                arrival_date="2026-11-08",
                departure_date="2026-11-10",
            ),
            RESERVATIONS_AGENT,
        ),
        ApiErrorId.STAY_DATE_OUTSIDE_BLOCK,
        422,
    )

    first = validate_success(
        api.create_reservation(
            F.reservation_payload(
                block_id,
                guest_name="Alpha",
                arrival_date="2026-11-09",
                departure_date="2026-11-10",
            ),
            RESERVATIONS_AGENT,
        ),
        201,
    )
    assert_reservation(first, room_nights=1)

    validate_error(
        api.create_reservation(
            F.reservation_payload(
                block_id,
                guest_name="Alpha",
                arrival_date="2026-11-09",
                departure_date="2026-11-10",
            ),
            RESERVATIONS_AGENT,
        ),
        ApiErrorId.DUPLICATE_ROOMING_LIST_ENTRY,
        409,
    )

    second = validate_success(
        api.create_reservation(
            F.reservation_payload(
                block_id,
                guest_name="Alpha",
                arrival_date="2026-11-10",
                departure_date="2026-11-11",
            ),
            RESERVATIONS_AGENT,
        ),
        201,
    )
    assert_reservation(second, status=ReservationStatus.PENDING, room_nights=1)

    assert_block_night(
        night_on(api, block_id, "2026-11-09"), rooms_picked_up=1, rooms_open=3
    )
    assert_block_night(night_on(api, block_id, "2026-11-10"), rooms_picked_up=1)


def test_a_sub_block_is_carved_night_by_night_out_of_what_remains(api):
    """The remainder shrinks as sub-blocks are carved, and the next carve sees it.

    PRD 3.6 validates a sub-block plan "in ascending stay_date order": the
    parent's night for each stay_date must exist, or the request is
    ERR_SUB_BLOCK_DATES_OUTSIDE_PARENT, and then "the parent night's unallocated
    rooms are computed as its rooms_allotted less rooms_sub_allocated less
    rooms_picked_up less rooms_released, and the entry's rooms must not exceed
    that figure, or the request is refused with
    ERR_SUB_BLOCK_ALLOTMENT_EXCEEDED". That makes the second refusal the telling
    one: 3 rooms are refused on a night whose rooms_allotted is 4, because 2 have
    already been carved. PRD 3.6 also fixes the new block's shape - is_master
    false, inventory_status SETUP - and shrinks the parent night's rooms_open "by
    exactly the same amount". Every write carries a freshly read parent version,
    so no refusal can be an optimistic-concurrency conflict in disguise.

    Design: Corner/validations/sub_block_plans_must_fit_inside_the_parent_night_by_night
    """
    world = seed_open_master_block(api)
    parent = world["master_block_id"]
    parent_version = block_version(api, parent)

    validate_error(
        api.create_room_block(
            F.sub_block_payload(
                parent,
                parent_version,
                name="SUB-OUTSIDE",
                nightly_allotments=F.allotment_plan(("2026-11-12", 2)),
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.SUB_BLOCK_DATES_OUTSIDE_PARENT,
        422,
    )
    validate_error(
        api.create_room_block(
            F.sub_block_payload(
                parent,
                parent_version,
                name="SUB-TOO-BIG",
                nightly_allotments=F.allotment_plan(("2026-11-09", 5)),
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.SUB_BLOCK_ALLOTMENT_EXCEEDED,
        409,
    )

    sub_a = validate_success(
        api.create_room_block(
            F.sub_block_payload(
                parent,
                parent_version,
                name="SUB-A",
                nightly_allotments=F.allotment_plan(
                    ("2026-11-09", 2), ("2026-11-10", 2)
                ),
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    assert_room_block(
        sub_a,
        is_master=False,
        inventory_status=BlockInventoryStatus.SETUP,
        allotted_room_nights=4,
    )
    assert_block_night(
        night_on(api, parent, "2026-11-09"), rooms_sub_allocated=2, rooms_open=2
    )
    assert_block_night(night_on(api, parent, "2026-11-11"), rooms_sub_allocated=0)

    parent_version = block_version(api, parent)
    validate_error(
        api.create_room_block(
            F.sub_block_payload(
                parent,
                parent_version,
                name="SUB-B",
                nightly_allotments=F.allotment_plan(("2026-11-09", 3)),
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.SUB_BLOCK_ALLOTMENT_EXCEEDED,
        409,
    )

    sub_b = validate_success(
        api.create_room_block(
            F.sub_block_payload(
                parent,
                parent_version,
                name="SUB-B",
                nightly_allotments=F.allotment_plan(("2026-11-09", 2)),
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    assert_room_block(sub_b, allotted_room_nights=2)
    assert_block_night(
        night_on(api, parent, "2026-11-09"), rooms_sub_allocated=4, rooms_open=0
    )
