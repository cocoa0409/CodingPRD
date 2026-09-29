"""Posture gates, the construction-halt freeze cascade and its compensating resume."""

from test_helpers import (
    ApiErrorId,
    assert_concession_ledger_identity,
    assert_instant_equals,
    assert_ratio_equals,
    complete_phase,
    create_amenity_phase,
    create_household,
    create_lease_payload,
    halt_payload,
    halt_phase,
    read_community,
    read_homesite,
    read_household,
    read_lease,
    read_phase,
    read_program,
    resume_phase,
    setup_frozen_community,
    setup_lease_with_approved_concession,
    setup_released_community,
    start_construction,
    validate_error,
    validate_paginated,
    validate_success,
)

HARROW_BEND_MIX = {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0}
FOUR_DETACHED_MIX = {"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0}


def _harrow_bend_with_committed_concession() -> dict:
    # Two released DETACHED homesites, one DRAFT lease on the first whose concession is
    # APPROVED, so both concession ledgers stand at 412685 cents and the posture is OPEN.
    scenario = setup_lease_with_approved_concession(
        homesite_count=2,
        total_planned_units=2,
        product_mix=dict(HARROW_BEND_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=5_000_000,
        facility_commitment_cents=40_000_000,
        program_overrides={
            "free_weeks": 6,
            "amortization_mode": "STRAIGHT_LINE_NET_EFFECTIVE",
            "max_budget_cents": 2_000_000,
        },
    )
    assert scenario["community"]["posture"] == "OPEN"
    assert scenario["community"]["committed_concession_cents"] == 412685
    assert scenario["program"]["committed_cents"] == 412685
    return scenario


def test_halting_a_released_housing_phase_freezes_the_posture_and_parks_the_inventory(
    api, construction_manager_headers
):
    """Halting a phase that had already released sections records SECTIONS_RELEASED as the
    pre-halt status, drives the community posture to FROZEN and pushes both available homes
    off the market without disturbing the released counter.

    "The zeroth hop touches the phase itself: `status` becomes `CONSTRUCTION_HALTED`, `pre_halt_status` records the status the phase held immediately before the halt — `UNDER_CONSTRUCTION` for a phase halted mid-build, `SECTIONS_RELEASED` for a phase that had already released sections — and `halt_count` increases by 1."
    "Halting a phase whose `kind` is `HOUSING` drives the posture to `FROZEN`; halting a phase whose `kind` is `AMENITY` drives it only to `RESTRICTED`."
    "Every homesite of the community whose `status` is `AVAILABLE`, taken in `created_at` ascending order, moves `AVAILABLE → OFF_MARKET` with `off_market_reason` set to `POSTURE_FREEZE`."
    "Their `released_at` values are left alone, so the community's `released_unit_count` does not move; only `available_unit_count` falls."

    Design: Difficulty/transitive_cascade/housing_phase_halt_cascade_freezes_posture_and_releases_committed_concession
    """
    scenario = _harrow_bend_with_committed_concession()

    halted = validate_success(
        api.halt_phase(
            scenario["phase"]["id"],
            halt_payload(halt_reason="Storm damage to the north drainage run"),
            construction_manager_headers,
        ),
        expected_status=201,
    )
    assert halted["status"] == "CONSTRUCTION_HALTED"
    assert halted["pre_halt_status"] == "SECTIONS_RELEASED"
    assert halted["halt_count"] == 1

    community = read_community(scenario["community"]["id"])
    assert community["posture"] == "FROZEN"

    for created in scenario["homesites"]:
        parked = read_homesite(created["id"])
        assert parked["status"] == "OFF_MARKET"
        assert parked["off_market_reason"] == "POSTURE_FREEZE"
        assert_instant_equals(parked["released_at"], created["released_at"], "released_at")

    assert community["available_unit_count"] == 0
    assert community["released_unit_count"] == 2


def test_the_freeze_cascade_cancels_the_unsigned_lease_and_revokes_its_concession():
    """The freeze reaches the DRAFT lease standing on a just-delisted home, cancelling it with
    reason POSTURE_FREEZE and revoking its approved concession.

    "Every lease on a just-delisted homesite whose `lease_status` is `DRAFT` or `PENDING_SIGNATURE`, again in `created_at` ascending order, moves to `CANCELLED` with `cancellation_reason` set to `POSTURE_FREEZE`."
    "If such a lease had a concession in flight — its `concession_status` being `REQUESTED` or `APPROVED` — that concession moves to `REVOKED`, and the community's `committed_concession_cents` is reduced by that lease's `concession_remaining_cents`."
    "That counter is derived: at any moment it is the number of leases for the household whose `lease_status` is `DRAFT`, `PENDING_SIGNATURE`, `EXECUTED`, `ACTIVE` or `ENDING`, and it is refreshed whenever any of that household's leases changes contract state — rising when a lease is signed, falling when one is cancelled."

    Design: Difficulty/transitive_cascade/housing_phase_halt_cascade_freezes_posture_and_releases_committed_concession
    """
    scenario = _harrow_bend_with_committed_concession()

    halt_phase(scenario["phase"]["id"], halt_reason="Storm damage to the north drainage run")

    lease = read_lease(scenario["lease"]["id"])
    assert lease["lease_status"] == "CANCELLED"
    assert lease["cancellation_reason"] == "POSTURE_FREEZE"
    assert lease["concession_status"] == "REVOKED"

    community = read_community(scenario["community"]["id"])
    assert community["committed_concession_cents"] == 0

    household = read_household(scenario["household"]["id"])
    assert household["active_lease_count"] == 0


def test_the_freeze_cascade_returns_the_program_level_committed_total_to_zero():
    """The program-level ledger settles in the same request: the concession program that backed
    the cancelled lease has its committed total recomputed downward to 0.

    "The fourth hop, caused by the third, settles the program-level ledger: each `ConcessionProgram` whose leases were revoked has its `committed_cents` recomputed downward by the same amounts and its `version` incremented."
    "The parallel invariant holds per program: a `ConcessionProgram`'s `committed_cents` must always equal the sum of `concession_remaining_cents` across the leases carrying that `concession_program_id` whose `concession_status` is `APPROVED` or `AMORTIZING`."

    Design: Difficulty/transitive_cascade/housing_phase_halt_cascade_freezes_posture_and_releases_committed_concession
    """
    scenario = _harrow_bend_with_committed_concession()
    program_version_before = scenario["program"]["version"]

    halt_phase(scenario["phase"]["id"], halt_reason="Storm damage to the north drainage run")

    program = read_program(scenario["program"]["id"])
    assert program["committed_cents"] == 0
    assert program["version"] > program_version_before

    community = read_community(scenario["community"]["id"])
    lease = read_lease(scenario["lease"]["id"])
    assert_concession_ledger_identity(community, [lease], program)


def test_resuming_a_halted_phase_restores_its_pre_halt_status_and_relists_the_parked_homes():
    """A halt-then-resume cycle on a phase that had released sections returns the phase to
    SECTIONS_RELEASED rather than UNDER_CONSTRUCTION, relists both parked homes and leaves the
    monotone halt counter and the released timestamps alone.

    "The phase returns to whatever `pre_halt_status` holds, which is either `CONSTRUCTION_HALTED → UNDER_CONSTRUCTION` or `CONSTRUCTION_HALTED → SECTIONS_RELEASED`, and `pre_halt_status` is then cleared to null; `halt_count` is a running total and is never decremented."
    "Only when the recomputed posture is no longer `FROZEN` does the compensating relist run: every homesite of the community whose `status` is `OFF_MARKET` and whose `off_market_reason` is `POSTURE_FREEZE`, in `created_at` ascending order, returns to `AVAILABLE` with `off_market_reason` set back to null, restoring `available_unit_count` to its pre-halt value."
    "Leases cancelled by the freeze are **not** restored — cancellation is terminal — and `released_at` is never rewritten, so `released_unit_count` is unaffected by either the halt or the resume."

    Design: Corner/state_machines/halt_then_resume_restores_the_pre_halt_status_and_relists_the_frozen_homesites
    """
    scenario = setup_released_community(
        homesite_count=2,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
    )
    community_id = scenario["community"]["id"]
    phase_id = scenario["phase"]["id"]
    assert scenario["community"]["available_unit_count"] == 2
    assert scenario["community"]["released_unit_count"] == 2

    halt_phase(phase_id, halt_reason="Sanitary sewer tie-in failed inspection")

    halted_phase = read_phase(phase_id)
    assert halted_phase["status"] == "CONSTRUCTION_HALTED"
    assert halted_phase["pre_halt_status"] == "SECTIONS_RELEASED"
    assert halted_phase["halt_count"] == 1

    halted_community = read_community(community_id)
    assert halted_community["posture"] == "FROZEN"
    assert halted_community["available_unit_count"] == 0
    assert halted_community["released_unit_count"] == 2
    for created in scenario["homesites"]:
        parked = read_homesite(created["id"])
        assert parked["status"] == "OFF_MARKET"
        assert parked["off_market_reason"] == "POSTURE_FREEZE"

    resume_phase(phase_id)

    resumed_phase = read_phase(phase_id)
    assert resumed_phase["status"] == "SECTIONS_RELEASED"
    assert resumed_phase["pre_halt_status"] is None
    assert resumed_phase["halt_count"] == 1

    for created in scenario["homesites"]:
        relisted = read_homesite(created["id"])
        assert relisted["status"] == "AVAILABLE"
        assert relisted["off_market_reason"] is None
        assert_instant_equals(relisted["released_at"], "2026-08-01T00:00:00Z", "released_at")

    resumed_community = read_community(community_id)
    assert resumed_community["posture"] == "OPEN"
    assert resumed_community["available_unit_count"] == 2
    assert resumed_community["released_unit_count"] == 2


def test_completing_the_amenity_phase_returns_the_community_posture_to_open():
    """Declaring an amenity phase against a community that already has released inventory drops
    the delivery ratio to 0.0000 and restricts it; completing that amenity phase drives the ratio
    back to 1.0000 and the posture back to OPEN.

    "`amenity_delivery_ratio` is the sum of `amenity_weight` over the community's `AMENITY` phases whose `status` is `COMPLETE`, divided by the sum of `amenity_weight` over all of the community's `AMENITY` phases, rounded half up to four decimal places; when the community has no `AMENITY` phase at all the ratio is exactly 1.0000 and no division is attempted."
    "Otherwise the posture is `RESTRICTED` if either of these two conditions holds: the community's `released_unit_count` is at least 1 while its `amenity_delivery_ratio` is strictly below 0.5000; or at least one phase of the community whose `kind` is `AMENITY` currently has `status` equal to `CONSTRUCTION_HALTED`."
    "The phase's `status` becomes `COMPLETE`, the community's `amenity_delivery_ratio` is recomputed upward because this phase's `amenity_weight` now counts as delivered, and the posture is recomputed — which is how a community moves `RESTRICTED → OPEN` once the delivered amenity weight reaches half of the planned amenity weight."

    Design: Corner/calculations/community_posture_returns_to_open_when_the_amenity_phase_completes
    """
    scenario = setup_released_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
    )
    community_id = scenario["community"]["id"]
    assert_ratio_equals(scenario["community"]["amenity_delivery_ratio"], 1.0000, "amenity_delivery_ratio")
    assert scenario["community"]["posture"] == "OPEN"

    amenity_phase = create_amenity_phase(
        community_id,
        sequence_index=2,
        amenity_weight=100,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-10-01T00:00:00Z",
    )
    restricted = read_community(community_id)
    assert_ratio_equals(restricted["amenity_delivery_ratio"], 0.0000, "amenity_delivery_ratio")
    assert restricted["posture"] == "RESTRICTED"
    assert restricted["released_unit_count"] == 1

    start_construction(amenity_phase["id"])
    completed = complete_phase(amenity_phase["id"])
    assert completed["status"] == "COMPLETE"

    reopened = read_community(community_id)
    assert_ratio_equals(reopened["amenity_delivery_ratio"], 1.0000, "amenity_delivery_ratio")
    assert reopened["posture"] == "OPEN"
    assert reopened["released_unit_count"] == 1
    assert reopened["available_unit_count"] == 1


def test_drafting_a_lease_before_the_first_section_release_reports_the_lifecycle_gate(
    api, leasing_agent_headers
):
    """A lease drafted while the community is still in CONSTRUCTION breaks both the lifecycle gate
    and the leasability gate — the only home that exists is still PLANNED — and the lifecycle
    error is the one reported.

    "The home's community must have `lifecycle_status` of `LEASE_UP` or `STABILIZED`; a community still in `PLANNING` or `CONSTRUCTION` refuses the draft with `ERR_INVALID_LIFECYCLE_STATE`."
    "When a request violates more than one rule, exactly one error is returned, and which one is fully determined by a fixed evaluation order."

    Design: Corner/validations/leasing_against_a_community_still_in_construction_is_rejected
    """
    scenario = setup_released_community(
        homesite_count=1,
        release=False,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        phase_overrides={"planned_unit_count": 4},
    )
    community_id = scenario["community"]["id"]
    homesite_id = scenario["homesites"][0]["id"]
    household = create_household()

    assert read_community(community_id)["lifecycle_status"] == "CONSTRUCTION"
    assert read_homesite(homesite_id)["status"] == "PLANNED"

    validate_error(
        api.create_lease(
            create_lease_payload(homesite_id, household["id"]), leasing_agent_headers
        ),
        ApiErrorId.ERR_INVALID_LIFECYCLE_STATE.value,
    )

    leases, meta = validate_paginated(api.list_leases(leasing_agent_headers))
    assert meta["total_count"] == 0
    assert leases == []
    assert read_household(household["id"])["active_lease_count"] == 0


def test_drafting_a_lease_while_the_posture_is_frozen_reports_the_freeze_not_the_home(
    api, leasing_agent_headers
):
    """After a housing halt the community is FROZEN and its only home has been pushed off the
    market, so a draft attempt breaks the freeze gate and the leasability gate at once; the freeze
    is the reported cause and no lease is stored.

    "The community must not be `FROZEN`, or the draft is `ERR_COMMUNITY_POSTURE_FROZEN`; a `RESTRICTED` posture does not block drafting."
    "The practical consequence worth internalising is that a posture freeze surfaces as a posture error rather than being masked by a downstream business rule, and that a stale `expected_community_version` surfaces before any state or posture reasoning is done."

    Design: Corner/validations/lease_creation_while_the_posture_is_frozen_is_rejected
    """
    scenario = setup_frozen_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    homesite_id = scenario["homesites"][0]["id"]
    household = create_household()

    assert scenario["phase"]["status"] == "CONSTRUCTION_HALTED"
    assert scenario["community"]["posture"] == "FROZEN"
    assert scenario["homesites"][0]["status"] == "OFF_MARKET"
    assert scenario["homesites"][0]["off_market_reason"] == "POSTURE_FREEZE"

    validate_error(
        api.create_lease(
            create_lease_payload(homesite_id, household["id"]), leasing_agent_headers
        ),
        ApiErrorId.ERR_COMMUNITY_POSTURE_FROZEN.value,
    )

    leases, meta = validate_paginated(api.list_leases(leasing_agent_headers))
    assert meta["total_count"] == 0
    assert leases == []
    assert read_household(household["id"])["active_lease_count"] == 0


def test_the_same_lease_request_succeeds_once_the_halt_is_resumed(api, leasing_agent_headers):
    """Resuming the halted phase clears the freeze and relists the home, and the identical draft
    request that was refused a moment earlier then prices off the published schedule.

    "The community's posture is recomputed, and if no housing phase of the community remains `CONSTRUCTION_HALTED` the freeze clears."
    "The winner's `asking_rent_cents` becomes the lease's `base_rent_cents` and the winner's identifier is stored as the lease's `priced_by_schedule_id`."

    Design: Corner/validations/lease_creation_while_the_posture_is_frozen_is_rejected
    """
    scenario = setup_frozen_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    community_id = scenario["community"]["id"]
    homesite_id = scenario["homesites"][0]["id"]
    household = create_household()

    validate_error(
        api.create_lease(
            create_lease_payload(homesite_id, household["id"]), leasing_agent_headers
        ),
        ApiErrorId.ERR_COMMUNITY_POSTURE_FROZEN.value,
    )

    resume_phase(scenario["phase"]["id"])

    assert read_phase(scenario["phase"]["id"])["status"] == "SECTIONS_RELEASED"
    assert read_community(community_id)["posture"] == "OPEN"
    relisted = read_homesite(homesite_id)
    assert relisted["status"] == "AVAILABLE"
    assert relisted["off_market_reason"] is None

    lease = validate_success(
        api.create_lease(
            create_lease_payload(homesite_id, household["id"]), leasing_agent_headers
        ),
        expected_status=201,
    )
    assert lease["lease_status"] == "DRAFT"
    assert lease["base_rent_cents"] == 285000
