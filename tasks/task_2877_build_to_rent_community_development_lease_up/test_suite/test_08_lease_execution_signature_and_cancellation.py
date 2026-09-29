"""Lease execution: the signature cascade, the authorisation ladder that guards it,
resident notice, and the cancellation compensation that reverses it all."""

from test_helpers import (
    CONSTRUCTION_MANAGER_USER_ID,
    DEFAULT_CLOCK,
    ApiErrorId,
    assert_concession_ledger_identity,
    assert_instant_equals,
    assert_ratio_equals,
    cancellation_payload,
    create_homesite,
    create_household,
    create_lease_payload,
    draft_lease,
    make_construction_manager_headers,
    make_household_headers,
    notice_payload,
    read_community,
    read_homesite,
    read_household,
    read_lease,
    read_phase,
    read_program,
    setup_active_lease,
    setup_draft_lease,
    setup_executed_lease,
    setup_released_community,
    sign_lease,
    signature_payload,
    submit_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

# Pricing chain used throughout: a published DETACHED asking rent of 285,000 cents takes
# the 300 bps fee bracket, so the fee is 8,550 + 4,500 and the gross charge is 298,050.
BASE_RENT_CENTS = 285_000
COMMUNITY_SERVICES_FEE_CENTS = 13_050
GROSS_MONTHLY_CHARGE_CENTS = 298_050
INCOME_BAR_CENTS = 894_150
UNDERQUALIFIED_INCOME_CENTS = 800_000
STRAIGHT_LINE_TOTAL_CONCESSION_CENTS = 412_685

MIX_ONE_DETACHED = {"DETACHED": 1, "COTTAGE": 0, "TOWNHOME": 0}
MIX_TWO_DETACHED = {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0}
MIX_FOUR_DETACHED = {"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0}


def test_third_signature_stabilizes_the_community_and_opens_facility_conversion(api):
    """The signature that lifts a four-unit community's occupancy to three quarters walks all
    the way from the lease to the financing facility inside the one request.

    "Hop one, caused by hop zero, moves the home `AVAILABLE → LEASED`."
    "Hop two, caused by hop one, recomputes the phase's `leased_homesite_count` and the community's `leased_unit_count` and `occupancy_ratio`."
    "Hop three, caused by hop two, moves the community's `lifecycle_status` `LEASE_UP → STABILIZED` if and only if the recomputed `occupancy_ratio` has reached 0.7500 or more — three quarters of the planned units occupied is the stabilization threshold."
    "Hop four, caused by hop three, moves the community's `facility_status` `ADVANCE_ELIGIBLE → CONVERSION_PENDING`, opening the door to permanent financing."
    Design: Difficulty/transitive_cascade/signature_cascade_propagates_four_hops_to_facility_conversion_pending
    """
    scenario = setup_released_community(
        homesite_count=3,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=5_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    homesites = scenario["homesites"]
    for homesite in homesites[:2]:
        household = create_household()
        lease = draft_lease(homesite["id"], household["id"])
        submit_lease(lease["id"])
        sign_lease(lease["id"], household["id"], household["primary_applicant_name"])

    before = read_community(scenario["community"]["id"])
    assert_ratio_equals(before["occupancy_ratio"], 0.5000, "occupancy_ratio before the signature")
    assert before["lifecycle_status"] == "LEASE_UP"
    assert before["facility_status"] == "ADVANCE_ELIGIBLE"

    third_household = create_household()
    third_lease = draft_lease(homesites[2]["id"], third_household["id"])
    submit_lease(third_lease["id"])

    signed = validate_success(
        api.sign_lease(
            third_lease["id"],
            signature_payload(third_household["primary_applicant_name"]),
            make_household_headers(third_household["id"]),
        ),
        expected_status=201,
    )
    assert signed["lease_status"] == "EXECUTED"
    assert_instant_equals(signed["executed_at"], DEFAULT_CLOCK, "executed_at")

    assert read_homesite(homesites[2]["id"])["status"] == "LEASED"
    assert read_phase(scenario["phase"]["id"])["leased_homesite_count"] == 3

    community = read_community(scenario["community"]["id"])
    assert community["leased_unit_count"] == 3
    assert_ratio_equals(community["occupancy_ratio"], 0.7500, "occupancy_ratio")
    assert community["lifecycle_status"] == "STABILIZED"
    assert community["facility_status"] == "CONVERSION_PENDING"
    assert community["posture"] == "OPEN"
    assert community["available_unit_count"] == 0
    assert read_household(third_household["id"])["active_lease_count"] == 1


def test_signature_leaving_occupancy_at_half_stops_after_the_counter_recomputation(api):
    """The same endpoint on the second of four planned units recomputes the counters but leaves
    the lifecycle and the facility exactly where they were.

    "Hop two, caused by hop one, recomputes the phase's `leased_homesite_count` and the community's `leased_unit_count` and `occupancy_ratio`."
    "Hops three and four fire only when their triggering condition is actually met; a signature that leaves occupancy below the threshold stops after hop two."
    Design: Difficulty/transitive_cascade/signature_cascade_propagates_four_hops_to_facility_conversion_pending
    """
    scenario = setup_released_community(
        homesite_count=3,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=5_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    homesites = scenario["homesites"]
    first_household = create_household()
    first_lease = draft_lease(homesites[0]["id"], first_household["id"])
    submit_lease(first_lease["id"])
    sign_lease(first_lease["id"], first_household["id"], first_household["primary_applicant_name"])

    second_household = create_household()
    second_lease = draft_lease(homesites[1]["id"], second_household["id"])
    submit_lease(second_lease["id"])

    signed = validate_success(
        api.sign_lease(
            second_lease["id"],
            signature_payload(second_household["primary_applicant_name"]),
            make_household_headers(second_household["id"]),
        ),
        expected_status=201,
    )
    assert signed["lease_status"] == "EXECUTED"

    assert read_homesite(homesites[1]["id"])["status"] == "LEASED"
    assert read_phase(scenario["phase"]["id"])["leased_homesite_count"] == 2

    community = read_community(scenario["community"]["id"])
    assert community["leased_unit_count"] == 2
    assert_ratio_equals(community["occupancy_ratio"], 0.5000, "occupancy_ratio")
    assert community["lifecycle_status"] == "LEASE_UP"
    assert community["facility_status"] == "ADVANCE_ELIGIBLE"
    assert community["available_unit_count"] == 1


def test_construction_manager_signature_is_refused_before_the_lease_state_is_examined(api):
    """A construction manager signing a lease that is still a draft is turned away on the role
    check, and the entitled household then proves the lease-state violation was there all along.

    "When a request violates more than one rule, exactly one error is returned, and which one is fully determined by a fixed evaluation order."
    "2. **Authorisation** — the role is on the endpoint's list (`ERR_UNAUTHORIZED`)."
    "The lease must be in `PENDING_SIGNATURE`, or the signature is `ERR_INVALID_LEASE_STATE`."
    Design: Difficulty/priority_pair_validation_conflict/signature_by_unauthorized_role_is_rejected_before_the_draft_lease_state_check
    """
    scenario = setup_draft_lease(
        homesite_count=1,
        total_planned_units=2,
        product_mix=MIX_TWO_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=1,
    )
    lease = scenario["lease"]
    assert lease["lease_status"] == "DRAFT"

    validate_error(
        api.sign_lease(
            lease["id"],
            signature_payload(scenario["household"]["primary_applicant_name"]),
            make_construction_manager_headers(CONSTRUCTION_MANAGER_USER_ID),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    validate_error(
        api.sign_lease(
            lease["id"],
            signature_payload(scenario["household"]["primary_applicant_name"]),
            make_household_headers(scenario["household"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_LEASE_STATE.value,
    )


def test_role_rejected_signature_leaves_the_draft_lease_and_its_home_untouched(api):
    """The role rejection is decided before anything is written, so neither the draft lease nor
    the home it stands on moves.

    "A role outside that set receives `ERR_UNAUTHORIZED` (HTTP 403)."
    "9. **Own-state legality** — the addressed entity is in a state from which the requested transition exists (`ERR_INVALID_PLAT_STATE`, `ERR_INVALID_PHASE_STATE`, `ERR_INVALID_HOMESITE_STATE`, `ERR_INVALID_LEASE_STATE`, `ERR_INVALID_CONCESSION_STATE`, `ERR_INVALID_TURN_STATE`, `ERR_INVALID_LIFECYCLE_STATE`, `ERR_INVALID_FACILITY_STATE`, `ERR_INVALID_MANAGEMENT_STATE`, `ERR_SCHEDULE_ALREADY_SUPERSEDED`)."
    Design: Difficulty/priority_pair_validation_conflict/signature_by_unauthorized_role_is_rejected_before_the_draft_lease_state_check
    """
    scenario = setup_draft_lease(
        homesite_count=1,
        total_planned_units=2,
        product_mix=MIX_TWO_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=1,
    )
    lease = scenario["lease"]
    homesite = scenario["homesites"][0]

    validate_error(
        api.sign_lease(
            lease["id"],
            signature_payload(scenario["household"]["primary_applicant_name"]),
            make_construction_manager_headers(CONSTRUCTION_MANAGER_USER_ID),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = read_lease(lease["id"])
    assert after["lease_status"] == "DRAFT"
    assert after["signed_by_name"] is None
    assert after["executed_at"] is None
    assert read_homesite(homesite["id"])["status"] == "AVAILABLE"

    community = read_community(scenario["community"]["id"])
    assert community["leased_unit_count"] == 0
    assert_ratio_equals(community["occupancy_ratio"], 0.0000, "occupancy_ratio")


def test_cancelling_an_executed_lease_releases_its_committed_concession(api, asset_manager_headers):
    """Cancelling the only executed lease of a single-home community revokes the concession and
    hands the committed money back to both the community budget and the program budget.

    "Revocation is the compensating exit and it never claws back money already applied."
    "A community's `committed_concession_cents` must always equal the sum of `concession_remaining_cents` across the leases of that community whose `concession_status` is `APPROVED` or `AMORTIZING`."
    "The parallel invariant holds per program: a `ConcessionProgram`'s `committed_cents` must always equal the sum of `concession_remaining_cents` across the leases carrying that `concession_program_id` whose `concession_status` is `APPROVED` or `AMORTIZING`."
    Design: Difficulty/compensating_invariant/lease_cancellation_reverses_the_whole_signature_cascade_and_the_concession_ledger
    """
    scenario = setup_executed_lease(
        with_concession=True,
        homesite_count=1,
        total_planned_units=1,
        product_mix=MIX_ONE_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=1,
        program_overrides={
            "program_code": "CP-WM",
            "tier": "AGGRESSIVE",
            "free_weeks": 6,
            "amortization_mode": "STRAIGHT_LINE_NET_EFFECTIVE",
            "eligible_product_types": ["DETACHED"],
            "restricted_posture_eligible": False,
            "max_budget_cents": 2_000_000,
        },
    )
    lease = scenario["lease"]
    assert lease["lease_status"] == "EXECUTED"
    assert lease["concession_status"] == "APPROVED"
    assert lease["gross_monthly_charge_cents"] == GROSS_MONTHLY_CHARGE_CENTS
    assert lease["total_concession_cents"] == STRAIGHT_LINE_TOTAL_CONCESSION_CENTS
    assert lease["concession_remaining_cents"] == STRAIGHT_LINE_TOTAL_CONCESSION_CENTS
    assert scenario["community"]["committed_concession_cents"] == STRAIGHT_LINE_TOTAL_CONCESSION_CENTS
    assert scenario["program"]["committed_cents"] == STRAIGHT_LINE_TOTAL_CONCESSION_CENTS

    cancelled = validate_success(
        api.cancel_lease(
            lease["id"], cancellation_payload("APPLICANT_WITHDREW"), asset_manager_headers
        ),
        expected_status=201,
    )
    assert cancelled["lease_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "APPLICANT_WITHDREW"
    assert cancelled["concession_status"] == "REVOKED"

    community = read_community(scenario["community"]["id"])
    program = read_program(scenario["program"]["id"])
    assert community["committed_concession_cents"] == 0
    assert program["committed_cents"] == 0
    assert program["status"] == "ACTIVE"
    assert_concession_ledger_identity(community, [read_lease(lease["id"])], program)


def test_cancelling_an_executed_lease_reverses_stabilization_and_the_facility(api, asset_manager_headers):
    """The executed branch of cancellation puts the home back on the market and unwinds the
    stabilization and financing steps the signature had triggered.

    "The `EXECUTED` branch does more, because it has more to undo: the home moves `LEASED → AVAILABLE` with its `released_at` left untouched, the phase's `leased_homesite_count` and the community's `leased_unit_count` and `occupancy_ratio` are recomputed, the community's `lifecycle_status` reverts `STABILIZED → LEASE_UP` when the recomputed `occupancy_ratio` has fallen below 0.7500, and in that same revert the community's `facility_status` moves `CONVERSION_PENDING → ADVANCE_ELIGIBLE`."
    "In particular, a homesite's `released_at` is never rewritten, so a community's `released_unit_count` is unchanged by a halt, by a resume, by a cancellation or by a turn — once a home has been released to leasing it stays counted as released for the rest of its life."
    Design: Difficulty/compensating_invariant/lease_cancellation_reverses_the_whole_signature_cascade_and_the_concession_ledger
    """
    scenario = setup_executed_lease(
        with_concession=True,
        homesite_count=1,
        total_planned_units=1,
        product_mix=MIX_ONE_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=1,
    )
    lease = scenario["lease"]
    homesite = scenario["homesites"][0]
    before = scenario["community"]
    assert_ratio_equals(before["occupancy_ratio"], 1.0000, "occupancy_ratio before cancellation")
    assert before["lifecycle_status"] == "STABILIZED"
    assert before["facility_status"] == "CONVERSION_PENDING"

    validate_success(
        api.cancel_lease(
            lease["id"], cancellation_payload("APPLICANT_WITHDREW"), asset_manager_headers
        ),
        expected_status=201,
    )

    assert read_homesite(homesite["id"])["status"] == "AVAILABLE"
    community = read_community(before["id"])
    assert community["leased_unit_count"] == 0
    assert community["available_unit_count"] == 1
    assert_ratio_equals(community["occupancy_ratio"], 0.0000, "occupancy_ratio")
    assert community["lifecycle_status"] == "LEASE_UP"
    assert community["facility_status"] == "ADVANCE_ELIGIBLE"
    assert community["released_unit_count"] == 1
    assert community["posture"] == "OPEN"
    assert read_household(scenario["household"]["id"])["active_lease_count"] == 0


def test_a_home_freed_by_cancellation_can_be_let_to_another_household(
    api, asset_manager_headers, leasing_agent_headers
):
    """Once the cancellation has run there is no residue on the home: a different household can
    be drafted onto it immediately and is priced from the same published schedule.

    "Cancellation is the `AssetManager`'s compensating action against a lease that has not yet activated, and it carries a `cancellation_reason` of `POSTURE_FREEZE`, `APPLICANT_WITHDREW` or `OPERATOR_CANCELLED`."
    "The home must have `status` `AVAILABLE` and its phase must be in `status` `SECTIONS_RELEASED` or `COMPLETE`, failing which the draft is `ERR_HOMESITE_NOT_LEASABLE` — which is what a caller sees when it tries to draft against a home that is still `PLANNED`, already `LEASED`, on `NOTICE_GIVEN`, `IN_TURN`, or parked `OFF_MARKET`."
    Design: Difficulty/compensating_invariant/lease_cancellation_reverses_the_whole_signature_cascade_and_the_concession_ledger
    """
    scenario = setup_executed_lease(
        with_concession=True,
        homesite_count=1,
        total_planned_units=1,
        product_mix=MIX_ONE_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=1,
    )
    homesite = scenario["homesites"][0]
    next_household = create_household()

    validate_success(
        api.cancel_lease(
            scenario["lease"]["id"],
            cancellation_payload("APPLICANT_WITHDREW"),
            asset_manager_headers,
        ),
        expected_status=201,
    )

    relet = validate_success(
        api.create_lease(
            create_lease_payload(homesite["id"], next_household["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )
    assert relet["base_rent_cents"] == BASE_RENT_CENTS
    assert relet["lease_status"] == "DRAFT"


def test_household_cannot_sign_its_own_lease_before_it_has_been_submitted(api):
    """A household signing its own never-submitted lease clears the ownership check and is still
    refused on the contract state, and none of the cascade hops fire.

    "The lease must be in `PENDING_SIGNATURE`, or the signature is `ERR_INVALID_LEASE_STATE`."
    "This ownership check guards exactly three operations — fetching a single lease, signing a lease, and giving notice on a lease."
    Design: Corner/state_machines/signature_on_a_lease_that_was_never_submitted_is_rejected
    """
    scenario = setup_draft_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 2},
    )
    lease = scenario["lease"]
    homesite = scenario["homesites"][0]

    validate_error(
        api.sign_lease(
            lease["id"],
            signature_payload(scenario["household"]["primary_applicant_name"]),
            make_household_headers(scenario["household"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_LEASE_STATE.value,
    )

    after = read_lease(lease["id"])
    assert after["lease_status"] == "DRAFT"
    assert after["executed_at"] is None
    assert after["signed_by_name"] is None
    assert read_homesite(homesite["id"])["status"] == "AVAILABLE"

    community = read_community(scenario["community"]["id"])
    assert community["leased_unit_count"] == 0
    assert_ratio_equals(community["occupancy_ratio"], 0.0000, "occupancy_ratio")
    assert community["lifecycle_status"] == "LEASE_UP"


def test_notice_moves_the_lease_to_ending_while_the_home_stays_counted_as_occupied(api):
    """A resident notice changes both the lease and the home, yet the occupancy arithmetic is
    identical before and after because a home on notice is still occupied.

    "On success `lease_status` moves `ACTIVE → ENDING` with both instants recorded, and the home moves `LEASED → NOTICE_GIVEN`."
    "`leased_unit_count` is the number of homesites whose `status` is either `LEASED` or `NOTICE_GIVEN` — a home on notice still counts as occupied."
    "Because a home on notice still counts as occupied, the community's `leased_unit_count` and `occupancy_ratio` are unchanged by the notice, so no lifecycle revert follows from giving notice alone."
    Design: Corner/state_machines/notice_given_keeps_the_home_counted_as_occupied_while_the_lease_moves_to_ending
    """
    scenario = setup_active_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 2},
    )
    lease = scenario["lease"]
    homesite = scenario["homesites"][0]
    before = scenario["community"]
    assert before["leased_unit_count"] == 1
    assert_ratio_equals(before["occupancy_ratio"], 0.2500, "occupancy_ratio before the notice")
    assert before["available_unit_count"] == 0

    noticed = validate_success(
        api.give_notice(
            lease["id"],
            notice_payload(
                notice_date="2026-08-01T00:00:00Z", move_out_date="2026-09-01T00:00:00Z"
            ),
            make_household_headers(scenario["household"]["id"]),
        ),
        expected_status=201,
    )
    assert noticed["lease_status"] == "ENDING"
    assert_instant_equals(noticed["notice_date"], "2026-08-01T00:00:00Z", "notice_date")
    assert_instant_equals(noticed["move_out_date"], "2026-09-01T00:00:00Z", "move_out_date")

    assert read_homesite(homesite["id"])["status"] == "NOTICE_GIVEN"

    community = read_community(before["id"])
    assert community["leased_unit_count"] == 1
    assert_ratio_equals(community["occupancy_ratio"], 0.2500, "occupancy_ratio after the notice")
    assert community["available_unit_count"] == 0
    assert community["lifecycle_status"] == "LEASE_UP"


def test_second_draft_for_a_household_that_already_holds_a_draft_is_rejected(
    api, leasing_agent_headers
):
    """A household holding a draft lease on one home cannot be drafted onto a second home,
    because a draft already counts as an open lease.

    "And the household must not already hold an open lease: at most one lease per household may sit in `DRAFT`, `PENDING_SIGNATURE`, `EXECUTED` or `ACTIVE` across the whole system, and a second draft is `ERR_HOUSEHOLD_ALREADY_LEASED`."
    "That counter is derived: at any moment it is the number of leases for the household whose `lease_status` is `DRAFT`, `PENDING_SIGNATURE`, `EXECUTED`, `ACTIVE` or `ENDING`, and it is refreshed whenever any of that household's leases changes contract state — rising when a lease is signed, falling when one is cancelled."
    Design: Corner/validations/a_second_open_lease_for_the_same_household_is_rejected
    """
    scenario = setup_draft_lease(
        homesite_count=2,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 4},
    )
    household = scenario["household"]
    first_lease = scenario["lease"]
    second_homesite = scenario["homesites"][1]

    validate_error(
        api.create_lease(
            create_lease_payload(second_homesite["id"], household["id"], term_months=18),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_HOUSEHOLD_ALREADY_LEASED.value,
    )

    assert read_lease(first_lease["id"])["lease_status"] == "DRAFT"
    assert read_household(household["id"])["active_lease_count"] == 1
    assert read_homesite(second_homesite["id"])["status"] == "AVAILABLE"

    leases, meta = validate_paginated(
        api.list_leases(leasing_agent_headers, {"household_id": household["id"]})
    )
    assert meta["total_count"] == 1
    assert [lease["id"] for lease in leases] == [first_lease["id"]]


def test_draft_against_a_home_never_released_from_its_phase_is_rejected(api, leasing_agent_headers):
    """A home that is still planned cannot be leased even though its phase has already released
    an earlier section.

    "The home must have `status` `AVAILABLE` and its phase must be in `status` `SECTIONS_RELEASED` or `COMPLETE`, failing which the draft is `ERR_HOMESITE_NOT_LEASABLE` — which is what a caller sees when it tries to draft against a home that is still `PLANNED`, already `LEASED`, on `NOTICE_GIVEN`, `IN_TURN`, or parked `OFF_MARKET`."
    Design: Corner/validations/a_lease_on_a_home_that_is_not_available_is_rejected
    """
    scenario = setup_released_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 4},
    )
    assert scenario["phase"]["status"] == "SECTIONS_RELEASED"
    unreleased = create_homesite(
        scenario["phase"]["id"], product_type="DETACHED", bedrooms=3, square_feet=1900
    )
    assert unreleased["status"] == "PLANNED"
    household = create_household()

    validate_error(
        api.create_lease(
            create_lease_payload(unreleased["id"], household["id"]), leasing_agent_headers
        ),
        ApiErrorId.ERR_HOMESITE_NOT_LEASABLE.value,
    )

    assert read_household(household["id"])["active_lease_count"] == 0
    _, meta = validate_paginated(
        api.list_leases(leasing_agent_headers, {"household_id": household["id"]})
    )
    assert meta["total_count"] == 0


def test_draft_against_a_home_already_leased_by_another_household_is_rejected(
    api, leasing_agent_headers
):
    """A home carrying an executed lease is no longer available, so a second household's
    application against it is refused and the sitting lease is untouched.

    "The home must have `status` `AVAILABLE` and its phase must be in `status` `SECTIONS_RELEASED` or `COMPLETE`, failing which the draft is `ERR_HOMESITE_NOT_LEASABLE` — which is what a caller sees when it tries to draft against a home that is still `PLANNED`, already `LEASED`, on `NOTICE_GIVEN`, `IN_TURN`, or parked `OFF_MARKET`."
    Design: Corner/validations/a_lease_on_a_home_that_is_not_available_is_rejected
    """
    scenario = setup_executed_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 4},
    )
    leased_homesite = scenario["homesites"][0]
    assert leased_homesite["status"] == "LEASED"
    other_household = create_household(credit_tier="B", household_size=2)

    validate_error(
        api.create_lease(
            create_lease_payload(leased_homesite["id"], other_household["id"]),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_HOMESITE_NOT_LEASABLE.value,
    )

    assert read_household(other_household["id"])["active_lease_count"] == 0
    assert read_homesite(leased_homesite["id"])["status"] == "LEASED"
    assert read_community(scenario["community"]["id"])["leased_unit_count"] == 1


def test_income_qualification_is_measured_against_the_gross_charge_not_the_base_rent(api):
    """A household earning 800,000 cents clears three times the 285,000-cent base rent yet still
    fails the signature, because the bar is three times the 298,050-cent gross charge.

    "Step three computes `community_services_fee_cents` as `base_rent_cents` multiplied by the selected rate in basis points and divided by 10,000, rounded half up to whole cents, plus a flat product surcharge keyed on the home's `product_type`: 4,500 cents for `DETACHED`, 3,000 cents for `COTTAGE` and 2,000 cents for `TOWNHOME`."
    "Step four computes `gross_monthly_charge_cents` as `base_rent_cents` plus `community_services_fee_cents`."
    "And the household must qualify on income: `monthly_income_cents` must be at least three times the lease's `gross_monthly_charge_cents`, failing which the signature is `ERR_INCOME_QUALIFICATION_FAILED`."
    Design: Corner/validations/a_signature_below_three_times_the_gross_charge_is_rejected
    """
    scenario = setup_draft_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 4},
        household_overrides={
            "monthly_income_cents": UNDERQUALIFIED_INCOME_CENTS,
            "credit_tier": "B",
            "household_size": 3,
        },
    )
    lease = scenario["lease"]
    assert lease["base_rent_cents"] == BASE_RENT_CENTS
    assert lease["community_services_fee_cents"] == COMMUNITY_SERVICES_FEE_CENTS
    assert lease["gross_monthly_charge_cents"] == GROSS_MONTHLY_CHARGE_CENTS
    submit_lease(lease["id"])

    validate_error(
        api.sign_lease(
            lease["id"],
            signature_payload(scenario["household"]["primary_applicant_name"]),
            make_household_headers(scenario["household"]["id"]),
        ),
        ApiErrorId.ERR_INCOME_QUALIFICATION_FAILED.value,
    )

    after = read_lease(lease["id"])
    assert after["lease_status"] == "PENDING_SIGNATURE"
    assert after["executed_at"] is None
    assert read_homesite(scenario["homesites"][0]["id"])["status"] == "AVAILABLE"
    assert read_community(scenario["community"]["id"])["leased_unit_count"] == 0


def test_income_exactly_three_times_the_gross_charge_qualifies_for_signature(api):
    """A household earning exactly 894,150 cents — three times the gross charge to the cent —
    signs successfully, showing the multiple is inclusive at the boundary.

    "And the household must qualify on income: `monthly_income_cents` must be at least three times the lease's `gross_monthly_charge_cents`, failing which the signature is `ERR_INCOME_QUALIFICATION_FAILED`."
    "Hop one, caused by hop zero, moves the home `AVAILABLE → LEASED`."
    Design: Corner/validations/a_signature_below_three_times_the_gross_charge_is_rejected
    """
    scenario = setup_draft_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 4},
        household_overrides={
            "monthly_income_cents": INCOME_BAR_CENTS,
            "credit_tier": "B",
            "household_size": 3,
        },
    )
    lease = scenario["lease"]
    assert lease["gross_monthly_charge_cents"] == GROSS_MONTHLY_CHARGE_CENTS
    assert scenario["household"]["monthly_income_cents"] == INCOME_BAR_CENTS
    submit_lease(lease["id"])

    signed = validate_success(
        api.sign_lease(
            lease["id"],
            signature_payload(scenario["household"]["primary_applicant_name"]),
            make_household_headers(scenario["household"]["id"]),
        ),
        expected_status=201,
    )
    assert signed["lease_status"] == "EXECUTED"

    assert read_homesite(scenario["homesites"][0]["id"])["status"] == "LEASED"
    community = read_community(scenario["community"]["id"])
    assert community["leased_unit_count"] == 1
    assert_ratio_equals(community["occupancy_ratio"], 0.2500, "occupancy_ratio")


def test_signature_cascade_is_visible_to_the_very_next_read(
    api, asset_manager_headers, leasing_agent_headers
):
    """Every row the signature touches — the lease, the home, the household counter and the
    community aggregates — already reflects the cascade on the first read after the write.

    "All hops of a cascade complete inside the originating request — consistency in this system is immediate, never deferred — and every entity a hop touches has its `version` incremented and its `updated_at` refreshed."
    "A signature reaches the homesite, the phase, the community counters, the community lifecycle and the financing facility."
    Design: Corner/consistency_model/the_signature_cascade_is_readable_immediately_after_the_write_returns
    """
    scenario = setup_draft_lease(
        homesite_count=2,
        total_planned_units=2,
        product_mix=MIX_TWO_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 2},
    )
    lease = scenario["lease"]
    household = scenario["household"]
    signed_homesite = scenario["homesites"][0]
    submit_lease(lease["id"])

    signed = validate_success(
        api.sign_lease(
            lease["id"],
            signature_payload(household["primary_applicant_name"]),
            make_household_headers(household["id"]),
        ),
        expected_status=201,
    )
    assert signed["lease_status"] == "EXECUTED"
    assert signed["signed_by_name"] == household["primary_applicant_name"]
    assert_instant_equals(signed["executed_at"], DEFAULT_CLOCK, "executed_at")

    community = validate_success(
        api.get_community(scenario["community"]["id"], asset_manager_headers)
    )
    assert community["leased_unit_count"] == 1
    assert community["available_unit_count"] == 1
    assert community["released_unit_count"] == 2
    assert_ratio_equals(community["occupancy_ratio"], 0.5000, "occupancy_ratio")
    assert community["lifecycle_status"] == "LEASE_UP"
    assert community["facility_status"] == "ADVANCE_ELIGIBLE"

    homesite = validate_success(api.get_homesite(signed_homesite["id"], asset_manager_headers))
    assert homesite["status"] == "LEASED"

    household_read = validate_success(api.get_household(household["id"], leasing_agent_headers))
    assert household_read["active_lease_count"] == 1

    leases, meta = validate_paginated(
        api.list_leases(asset_manager_headers, {"homesite_id": signed_homesite["id"]})
    )
    assert meta["total_count"] == 1
    assert leases[0]["lease_status"] == "EXECUTED"
