"""Construction phasing, the overlapping-window cap, the same-kind gap and section releases."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    create_community,
    create_homesite,
    create_homesite_payload,
    create_household,
    create_lease_payload,
    create_phase,
    create_phase_payload,
    create_plat_approved_community,
    occupancy_certificate_payload,
    publish_schedule,
    read_community,
    read_homesite,
    read_phase,
    record_occupancy_certificate,
    release_section,
    section_release_payload,
    start_construction,
    submit_plat,
    validate_error,
    validate_paginated,
    validate_success,
)

UMBERFIELD_MIX = {"DETACHED": 8, "COTTAGE": 0, "TOWNHOME": 0}


def test_a_third_overlapping_construction_window_is_refused_by_the_concurrency_cap(
    api, construction_manager_headers
):
    """Two housing phases with overlapping windows are already under construction, so a third
    phase whose window overlaps both of them cannot start.

    "The concurrency cap says that at most one *other* phase of the same community whose `status` is `UNDER_CONSTRUCTION`, `SECTIONS_RELEASED` or `CONSTRUCTION_HALTED` may have a construction window overlapping this phase's closed window — in other words the community may have at most two phases with mutually overlapping windows in flight at once."
    "A predecessor that has not released sections and a third overlapping window both produce `ERR_PHASE_CONCURRENCY_LIMIT`."

    Design: Difficulty/resource_temporal_overlap/third_overlapping_construction_window_is_rejected_while_a_disjoint_fourth_phase_starts
    """
    community = create_plat_approved_community(
        name="Umberfield",
        market_code="TX-HOU",
        total_planned_units=8,
        product_mix=UMBERFIELD_MIX,
        concession_budget_cents=4_000_000,
        facility_commitment_cents=100_000_000,
    )
    phase_a = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=2,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-12-01T00:00:00Z",
    )
    phase_b = create_phase(
        community["id"],
        sequence_index=2,
        planned_unit_count=2,
        construction_window_start="2026-09-01T00:00:00Z",
        construction_window_end="2027-01-01T00:00:00Z",
    )
    phase_c = create_phase(
        community["id"],
        sequence_index=3,
        planned_unit_count=2,
        construction_window_start="2026-10-01T00:00:00Z",
        construction_window_end="2027-02-01T00:00:00Z",
    )
    start_construction(phase_a["id"])
    start_construction(phase_b["id"])

    assert read_phase(phase_a["id"])["status"] == "UNDER_CONSTRUCTION"
    assert read_phase(phase_b["id"])["status"] == "UNDER_CONSTRUCTION"
    assert read_community(community["id"])["lifecycle_status"] == "CONSTRUCTION"

    response = api.start_construction(phase_c["id"], {}, construction_manager_headers)
    validate_error(response, ApiErrorId.ERR_PHASE_CONCURRENCY_LIMIT.value)

    refused = read_phase(phase_c["id"])
    assert refused["status"] == "PLANNED"
    after = read_community(community["id"])
    assert after["lifecycle_status"] == "CONSTRUCTION"
    assert after["posture"] == "OPEN"


def test_a_disjoint_fourth_construction_window_starts_despite_two_phases_under_construction(
    api, construction_manager_headers
):
    """The cap counts overlapping windows rather than started phases, so a fourth phase whose
    window is disjoint from all three others starts even with two phases under construction.

    "The concurrency cap says that at most one *other* phase of the same community whose `status` is `UNDER_CONSTRUCTION`, `SECTIONS_RELEASED` or `CONSTRUCTION_HALTED` may have a construction window overlapping this phase's closed window — in other words the community may have at most two phases with mutually overlapping windows in flight at once."
    "Separately, any phase of the same community with the same `kind` whose window does **not** overlap this one must still be separated from this window by at least two full days — 48 hours — measured between the windows; a gap of exactly 48 hours is acceptable, anything smaller is `ERR_PHASE_GAP_VIOLATION`."
    "A successful start sets the phase `status` to `UNDER_CONSTRUCTION`, moves the community's `lifecycle_status` from `PLANNING` to `CONSTRUCTION` on the first start anywhere in that community (incrementing the community's `version`), and recomputes the community's `posture`."

    Design: Difficulty/resource_temporal_overlap/third_overlapping_construction_window_is_rejected_while_a_disjoint_fourth_phase_starts
    """
    community = create_plat_approved_community(
        name="Umberfield",
        market_code="TX-HOU",
        total_planned_units=8,
        product_mix=UMBERFIELD_MIX,
        concession_budget_cents=4_000_000,
        facility_commitment_cents=100_000_000,
    )
    phase_a = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=2,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-12-01T00:00:00Z",
    )
    phase_b = create_phase(
        community["id"],
        sequence_index=2,
        planned_unit_count=2,
        construction_window_start="2026-09-01T00:00:00Z",
        construction_window_end="2027-01-01T00:00:00Z",
    )
    phase_c = create_phase(
        community["id"],
        sequence_index=3,
        planned_unit_count=2,
        construction_window_start="2026-10-01T00:00:00Z",
        construction_window_end="2027-02-01T00:00:00Z",
    )
    phase_d = create_phase(
        community["id"],
        sequence_index=4,
        planned_unit_count=2,
        construction_window_start="2027-03-01T00:00:00Z",
        construction_window_end="2027-06-01T00:00:00Z",
    )
    start_construction(phase_a["id"])
    start_construction(phase_b["id"])

    refusal = api.start_construction(phase_c["id"], {}, construction_manager_headers)
    validate_error(refusal, ApiErrorId.ERR_PHASE_CONCURRENCY_LIMIT.value)

    accepted = validate_success(
        api.start_construction(phase_d["id"], {}, construction_manager_headers),
        expected_status=201,
    )
    assert accepted["status"] == "UNDER_CONSTRUCTION"
    assert read_phase(phase_d["id"])["status"] == "UNDER_CONSTRUCTION"
    assert read_phase(phase_a["id"])["status"] == "UNDER_CONSTRUCTION"
    assert read_phase(phase_b["id"])["status"] == "UNDER_CONSTRUCTION"
    assert read_phase(phase_c["id"])["status"] == "PLANNED"

    after = read_community(community["id"])
    assert after["lifecycle_status"] == "CONSTRUCTION"
    assert after["posture"] == "OPEN"


def test_first_section_release_flips_the_community_to_lease_up_and_the_facility_to_advance_eligible(
    api, construction_manager_headers
):
    """Releasing the first certificated home moves the phase to SECTIONS_RELEASED and advances
    both the community lifecycle and the financing facility inside the same request.

    "A successful release walks the listed homes in the order the client supplied them, moving each from `PLANNED` to `AVAILABLE` and stamping `released_at` with the current logical clock."
    "The phase's `released_homesite_count` is recomputed, the community's `released_unit_count` and `available_unit_count` are recomputed, and the community's posture is recomputed — which is where a community with an undelivered clubhouse moves `OPEN → RESTRICTED`, because `released_unit_count` has become at least 1 while `amenity_delivery_ratio` is still below 0.5000."
    "On the very first release anywhere in the community, two further things happen in the same request: the community's `lifecycle_status` moves `CONSTRUCTION → LEASE_UP`, and its `facility_status` moves `CONSTRUCTION_DRAW → ADVANCE_ELIGIBLE`, because a community with rentable inventory can start drawing against the facility on an advance basis."
    "Before the clock is ever set, it reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time."

    Design: Corner/state_machines/first_section_release_flips_the_community_to_lease_up_and_the_facility_to_advance_eligible
    """
    community = create_plat_approved_community(
        name="Mossbank",
        market_code="TX-DFW",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
    )
    publish_schedule(
        community["id"],
        product_type="DETACHED",
        effective_from="2026-08-01T00:00:00Z",
        asking_rent_cents=285_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=4,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    homesite = create_homesite(
        phase["id"], lot_number="M1", product_type="DETACHED", bedrooms=4, square_feet=2100
    )
    record_occupancy_certificate(
        homesite["id"],
        occupancy_certificate_number="CO-MB-M1",
        issued_at="2026-08-01T00:00:00Z",
    )

    released = validate_success(
        api.release_section(
            phase["id"], section_release_payload([homesite["id"]]), construction_manager_headers
        ),
        expected_status=201,
    )
    assert released["status"] == "SECTIONS_RELEASED"
    assert released["released_homesite_count"] == 1
    stored_phase = read_phase(phase["id"])
    assert stored_phase["status"] == "SECTIONS_RELEASED"
    assert stored_phase["released_homesite_count"] == 1

    home = read_homesite(homesite["id"])
    assert home["status"] == "AVAILABLE"
    assert_instant_equals(home["released_at"], "2026-08-01T00:00:00Z", "released_at")

    after = read_community(community["id"])
    assert after["released_unit_count"] == 1
    assert after["available_unit_count"] == 1
    assert after["leased_unit_count"] == 0
    assert after["lifecycle_status"] == "LEASE_UP"
    assert after["facility_status"] == "ADVANCE_ELIGIBLE"
    assert after["posture"] == "OPEN"
    assert round(float(after["amenity_delivery_ratio"]), 4) == 1.0000


def test_a_second_construction_start_on_the_same_phase_is_rejected(
    api, construction_manager_headers
):
    """Replaying construction-start against a phase that is already under construction is
    refused, and the rejected replay bumps nothing on the community.

    "A `ConstructionManager` starts construction on a phase that is still `PLANNED`; starting a phase in any other state is `ERR_INVALID_PHASE_STATE`."
    "A successful start sets the phase `status` to `UNDER_CONSTRUCTION`, moves the community's `lifecycle_status` from `PLANNING` to `CONSTRUCTION` on the first start anywhere in that community (incrementing the community's `version`), and recomputes the community's `posture`."

    Design: Corner/state_machines/a_second_construction_start_on_the_same_phase_is_rejected
    """
    community = create_plat_approved_community(
        name="Norbridge",
        market_code="TX-HOU",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=4,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    after_first = read_community(community["id"])
    assert after_first["lifecycle_status"] == "CONSTRUCTION"

    response = api.start_construction(phase["id"], {}, construction_manager_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_PHASE_STATE.value)

    replayed = read_phase(phase["id"])
    assert replayed["status"] == "UNDER_CONSTRUCTION"
    assert replayed["halt_count"] == 0

    after_replay = read_community(community["id"])
    assert after_replay["lifecycle_status"] == "CONSTRUCTION"
    assert after_replay["version"] == after_first["version"]


def test_newly_created_phase_homesite_and_lease_start_in_their_declared_initial_states(
    api, developer_principal_headers, construction_manager_headers, leasing_agent_headers
):
    """A community already in lease-up still mints fresh children at their own initial states:
    a new phase is PLANNED, a new homesite is PLANNED, and a new lease is DRAFT with no
    concession.

    "A new phase begins at `status` `PLANNED` with `halt_count` 0, `pre_halt_status` null, and `released_homesite_count` and `leased_homesite_count` both 0."
    "A new homesite starts at `status` `PLANNED` with `off_market_reason`, `occupancy_certificate_number`, `occupancy_certificate_issued_at`, `released_at` and `last_turn_ready_at` all null and `turn_cycle_count` 0."
    "The new lease sits at `lease_status` `DRAFT` and `concession_status` `NONE`, with `concession_program_id`, `concession_requested_by_user_id`, `concession_decided_by_user_id`, `cancellation_reason`, `signed_by_name`, `executed_at`, `notice_date` and `move_out_date` all null, with `concession_schedule` an empty list, and with `total_concession_cents`, `monthly_concession_credit_cents`, `first_period_charge_cents`, `net_effective_rent_cents`, `concession_applied_cents`, `concession_remaining_cents`, `credits_applied_count` and `construction_impact_credit_cents` all 0."

    Design: Corner/state_machines/newly_created_phase_homesite_and_lease_start_in_their_declared_initial_states
    """
    community = create_plat_approved_community(
        name="Oakhaven",
        market_code="TX-AUS",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
    )
    publish_schedule(
        community["id"],
        product_type="DETACHED",
        effective_from="2026-08-01T00:00:00Z",
        asking_rent_cents=285_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=2,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    homesite = create_homesite(
        phase["id"], lot_number="O1", product_type="DETACHED", bedrooms=4, square_feet=2100
    )
    record_occupancy_certificate(
        homesite["id"],
        occupancy_certificate_number="CO-OH-O1",
        issued_at="2026-08-01T00:00:00Z",
    )
    release_section(phase["id"], [homesite["id"]])
    household = create_household(
        primary_applicant_name="Omar Reyes",
        email="omar@example.com",
        household_size=4,
        monthly_income_cents=1_200_000,
        credit_tier="A",
    )
    assert read_community(community["id"])["lifecycle_status"] == "LEASE_UP"

    fresh_phase = validate_success(
        api.create_phase(
            create_phase_payload(
                community["id"],
                sequence_index=2,
                planned_unit_count=2,
                construction_window_start="2026-12-01T00:00:00Z",
                construction_window_end="2027-03-01T00:00:00Z",
            ),
            developer_principal_headers,
        ),
        expected_status=201,
    )
    assert fresh_phase["status"] == "PLANNED"
    assert fresh_phase["halt_count"] == 0
    assert fresh_phase["pre_halt_status"] is None
    assert fresh_phase["released_homesite_count"] == 0
    assert fresh_phase["leased_homesite_count"] == 0

    fresh_homesite = validate_success(
        api.create_homesite(
            create_homesite_payload(
                fresh_phase["id"],
                lot_number="O2",
                product_type="DETACHED",
                bedrooms=3,
                square_feet=1900,
            ),
            construction_manager_headers,
        ),
        expected_status=201,
    )
    assert fresh_homesite["status"] == "PLANNED"
    assert fresh_homesite["off_market_reason"] is None
    assert fresh_homesite["occupancy_certificate_number"] is None
    assert fresh_homesite["occupancy_certificate_issued_at"] is None
    assert fresh_homesite["released_at"] is None
    assert fresh_homesite["last_turn_ready_at"] is None
    assert fresh_homesite["turn_cycle_count"] == 0

    lease = validate_success(
        api.create_lease(
            create_lease_payload(
                homesite["id"],
                household["id"],
                term_months=12,
                start_date="2026-08-01T00:00:00Z",
            ),
            leasing_agent_headers,
        ),
        expected_status=201,
    )
    assert lease["lease_status"] == "DRAFT"
    assert lease["concession_status"] == "NONE"
    for field in (
        "concession_program_id",
        "concession_requested_by_user_id",
        "concession_decided_by_user_id",
        "cancellation_reason",
        "signed_by_name",
        "executed_at",
        "notice_date",
        "move_out_date",
    ):
        assert lease[field] is None, f"{field} starts null on a fresh lease"
    assert lease["concession_schedule"] == []
    for field in (
        "total_concession_cents",
        "monthly_concession_credit_cents",
        "first_period_charge_cents",
        "net_effective_rent_cents",
        "concession_applied_cents",
        "concession_remaining_cents",
        "credits_applied_count",
        "construction_impact_credit_cents",
    ):
        assert lease[field] == 0, f"{field} starts at 0 on a fresh lease"

    assert read_community(community["id"])["lifecycle_status"] == "LEASE_UP"


def test_a_duplicate_lot_number_in_the_same_phase_is_rejected(
    api, construction_manager_headers
):
    """A second homesite claiming a lot number already used inside the same phase is refused
    even though the community's product mix still has room for it.

    "A homesite carries a `lot_number` of 1 to 12 characters that must be unique within its phase — a duplicate is `ERR_DUPLICATE_RESOURCE` — a `product_type` of `DETACHED`, `COTTAGE` or `TOWNHOME`, a `bedrooms` count between 1 and 5 inclusive, and a `square_feet` figure of conditioned area between 400 and 4000 inclusive."
    "Homesites may be filtered by `phase_id`, `product_type` and `status`."

    Design: Corner/validations/a_duplicate_lot_number_in_the_same_phase_is_rejected
    """
    community = create_plat_approved_community(
        name="Harrowgate",
        market_code="TX-SAT",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=4,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    first = create_homesite(
        phase["id"], lot_number="H1", product_type="DETACHED", bedrooms=4, square_feet=2100
    )

    response = api.create_homesite(
        create_homesite_payload(
            phase["id"],
            lot_number="H1",
            product_type="DETACHED",
            bedrooms=3,
            square_feet=1900,
        ),
        construction_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    rows, meta = validate_paginated(
        api.list_homesites(construction_manager_headers, {"phase_id": phase["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["lot_number"] == "H1"
    assert rows[0]["bedrooms"] == 4
    assert rows[0]["square_feet"] == 2100
    assert rows[0]["version"] == 1


def test_homesites_beyond_the_declared_product_mix_are_rejected(
    api, construction_manager_headers
):
    """The per-type quota in the product mix is hard: a second detached home and a townhome are
    both refused while the cottage the mix allows is accepted, all in the same phase.

    "Three counting rules apply together at creation, and all three are enforced with `ERR_PRODUCT_MIX_EXCEEDED`: the homesite's `product_type` must be a key of its community's `product_mix` whose planned count is at least 1; the number of homesites of that product type across the whole community must not exceed that planned count; and the number of homesites in the phase must not exceed that phase's `planned_unit_count`."
    "A new homesite starts at `status` `PLANNED` with `off_market_reason`, `occupancy_certificate_number`, `occupancy_certificate_issued_at`, `released_at` and `last_turn_ready_at` all null and `turn_cycle_count` 0."

    Design: Corner/validations/homesites_beyond_the_declared_product_mix_are_rejected
    """
    community = create_plat_approved_community(
        name="Junipergate",
        market_code="TX-HOU",
        total_planned_units=2,
        product_mix={"DETACHED": 1, "COTTAGE": 1, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=2,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    create_homesite(
        phase["id"], lot_number="J1", product_type="DETACHED", bedrooms=4, square_feet=2100
    )

    second_detached = api.create_homesite(
        create_homesite_payload(
            phase["id"],
            lot_number="J2",
            product_type="DETACHED",
            bedrooms=3,
            square_feet=1950,
        ),
        construction_manager_headers,
    )
    validate_error(second_detached, ApiErrorId.ERR_PRODUCT_MIX_EXCEEDED.value)

    townhome = api.create_homesite(
        create_homesite_payload(
            phase["id"],
            lot_number="J3",
            product_type="TOWNHOME",
            bedrooms=3,
            square_feet=1500,
        ),
        construction_manager_headers,
    )
    validate_error(townhome, ApiErrorId.ERR_PRODUCT_MIX_EXCEEDED.value)

    cottage = validate_success(
        api.create_homesite(
            create_homesite_payload(
                phase["id"],
                lot_number="J4",
                product_type="COTTAGE",
                bedrooms=2,
                square_feet=1050,
            ),
            construction_manager_headers,
        ),
        expected_status=201,
    )
    assert cottage["status"] == "PLANNED"
    assert cottage["product_type"] == "COTTAGE"

    _rows, meta = validate_paginated(
        api.list_homesites(construction_manager_headers, {"phase_id": phase["id"]})
    )
    assert meta["total_count"] == 2


def test_a_predecessor_phase_from_another_community_is_rejected(
    api, developer_principal_headers
):
    """Naming a real phase that belongs to a different community is an illegal relationship
    rather than a missing identifier, while the same link inside the owning community is fine.

    "A phase may not name itself as its own predecessor, and the predecessor must belong to the same community; either mistake yields `ERR_INVALID_PHASE_PREDECESSOR`."
    "Phases may be filtered by `community_id`, by `predecessor_phase_id` — which is how a caller walks the phasing chain — and by `status` and `kind`."

    Design: Corner/validations/a_predecessor_phase_from_another_community_is_rejected
    """
    kilnbrook = create_plat_approved_community(
        name="Kilnbrook",
        market_code="NC-RAL",
        total_planned_units=6,
        product_mix={"DETACHED": 6, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    kilnbrook_phase = create_phase(
        kilnbrook["id"],
        sequence_index=1,
        planned_unit_count=3,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-09-01T00:00:00Z",
    )
    lanternhill = create_plat_approved_community(
        name="Lanternhill",
        market_code="NC-CLT",
        total_planned_units=6,
        product_mix={"DETACHED": 6, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )

    cross_community = api.create_phase(
        create_phase_payload(
            lanternhill["id"],
            predecessor_phase_id=kilnbrook_phase["id"],
            sequence_index=1,
            planned_unit_count=3,
            construction_window_start="2026-09-03T00:00:00Z",
            construction_window_end="2026-12-01T00:00:00Z",
        ),
        developer_principal_headers,
    )
    validate_error(cross_community, ApiErrorId.ERR_INVALID_PHASE_PREDECESSOR.value)

    _rows, meta = validate_paginated(
        api.list_phases(developer_principal_headers, {"community_id": lanternhill["id"]})
    )
    assert meta["total_count"] == 0

    sibling = validate_success(
        api.create_phase(
            create_phase_payload(
                kilnbrook["id"],
                predecessor_phase_id=kilnbrook_phase["id"],
                sequence_index=2,
                planned_unit_count=3,
                construction_window_start="2026-09-03T00:00:00Z",
                construction_window_end="2026-12-01T00:00:00Z",
            ),
            developer_principal_headers,
        ),
        expected_status=201,
    )
    assert sibling["predecessor_phase_id"] == kilnbrook_phase["id"]
    assert sibling["status"] == "PLANNED"

    chained, chained_meta = validate_paginated(
        api.list_phases(
            developer_principal_headers,
            {"predecessor_phase_id": kilnbrook_phase["id"]},
        )
    )
    assert chained_meta["total_count"] == 1
    assert chained[0]["id"] == sibling["id"]


def test_same_kind_phases_closer_than_48_hours_cannot_both_start(
    api, developer_principal_headers, construction_manager_headers
):
    """The same-kind separation rule bites at construction-start: a 24-hour gap is refused while
    a gap of exactly 48 hours is accepted.

    "Separately, any phase of the same community with the same `kind` whose window does **not** overlap this one must still be separated from this window by at least two full days — 48 hours — measured between the windows; a gap of exactly 48 hours is acceptable, anything smaller is `ERR_PHASE_GAP_VIOLATION`."
    "A successful start sets the phase `status` to `UNDER_CONSTRUCTION`, moves the community's `lifecycle_status` from `PLANNING` to `CONSTRUCTION` on the first start anywhere in that community (incrementing the community's `version`), and recomputes the community's `posture`."

    Design: Corner/validations/same_kind_phases_closer_than_48_hours_cannot_both_start
    """
    community = create_plat_approved_community(
        name="Mistwood",
        market_code="GA-ATL",
        total_planned_units=9,
        product_mix={"DETACHED": 9, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    started = validate_success(
        api.create_phase(
            create_phase_payload(
                community["id"],
                sequence_index=1,
                planned_unit_count=3,
                construction_window_start="2026-08-01T00:00:00Z",
                construction_window_end="2026-09-01T00:00:00Z",
            ),
            developer_principal_headers,
        ),
        expected_status=201,
    )
    start_construction(started["id"])

    # Each candidate phase is created immediately before its own start attempt: the PRD
    # scopes the same-kind separation rule to "any phase of the same community with the
    # same kind" without qualifying it by phase status, so a phase that merely exists is
    # already inside the compared set.
    too_close = validate_success(
        api.create_phase(
            create_phase_payload(
                community["id"],
                sequence_index=2,
                planned_unit_count=3,
                construction_window_start="2026-09-02T00:00:00Z",
                construction_window_end="2026-11-01T00:00:00Z",
            ),
            developer_principal_headers,
        ),
        expected_status=201,
    )
    refusal = api.start_construction(too_close["id"], {}, construction_manager_headers)
    validate_error(refusal, ApiErrorId.ERR_PHASE_GAP_VIOLATION.value)
    assert read_phase(too_close["id"])["status"] == "PLANNED"

    exactly_48_hours = validate_success(
        api.create_phase(
            create_phase_payload(
                community["id"],
                sequence_index=3,
                planned_unit_count=3,
                construction_window_start="2026-09-03T00:00:00Z",
                construction_window_end="2026-12-01T00:00:00Z",
            ),
            developer_principal_headers,
        ),
        expected_status=201,
    )
    accepted = validate_success(
        api.start_construction(exactly_48_hours["id"], {}, construction_manager_headers),
        expected_status=201,
    )
    assert accepted["status"] == "UNDER_CONSTRUCTION"

    assert read_community(community["id"])["lifecycle_status"] == "CONSTRUCTION"
    _rows, meta = validate_paginated(
        api.list_phases(
            construction_manager_headers,
            {"community_id": community["id"], "status": "UNDER_CONSTRUCTION"},
        )
    )
    assert meta["total_count"] == 2


def test_a_section_release_containing_an_uncertificated_home_is_rejected_whole(
    api, construction_manager_headers
):
    """A batch that mixes a certificated home with an uncertificated one is refused entirely —
    the certificated home does not slip through — and releasing it alone then succeeds.

    "Every listed home must have a non-null `occupancy_certificate_issued_at`, failing which the whole release is `ERR_OCCUPANCY_CERTIFICATE_REQUIRED`."
    "On the very first release anywhere in the community, two further things happen in the same request: the community's `lifecycle_status` moves `CONSTRUCTION → LEASE_UP`, and its `facility_status` moves `CONSTRUCTION_DRAW → ADVANCE_ELIGIBLE`, because a community with rentable inventory can start drawing against the facility on an advance basis."

    Design: Corner/validations/a_section_release_containing_an_uncertificated_home_is_rejected_whole
    """
    community = create_plat_approved_community(
        name="Quillhaven",
        market_code="SC-CHS",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    publish_schedule(
        community["id"],
        product_type="DETACHED",
        effective_from="2026-08-01T00:00:00Z",
        asking_rent_cents=285_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=4,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    certificated = create_homesite(
        phase["id"], lot_number="Q1", product_type="DETACHED", bedrooms=4, square_feet=2100
    )
    uncertificated = create_homesite(
        phase["id"], lot_number="Q2", product_type="DETACHED", bedrooms=3, square_feet=1900
    )
    record_occupancy_certificate(
        certificated["id"],
        occupancy_certificate_number="CO-QH-Q1",
        issued_at="2026-08-01T00:00:00Z",
    )

    alone = api.release_section(
        phase["id"],
        section_release_payload([uncertificated["id"]]),
        construction_manager_headers,
    )
    validate_error(alone, ApiErrorId.ERR_OCCUPANCY_CERTIFICATE_REQUIRED.value)

    mixed = api.release_section(
        phase["id"],
        section_release_payload([certificated["id"], uncertificated["id"]]),
        construction_manager_headers,
    )
    validate_error(mixed, ApiErrorId.ERR_OCCUPANCY_CERTIFICATE_REQUIRED.value)

    held_back = read_homesite(certificated["id"])
    assert held_back["status"] == "PLANNED"
    assert held_back["released_at"] is None
    stalled_phase = read_phase(phase["id"])
    assert stalled_phase["status"] == "UNDER_CONSTRUCTION"
    assert stalled_phase["released_homesite_count"] == 0
    assert read_community(community["id"])["lifecycle_status"] == "CONSTRUCTION"

    released = validate_success(
        api.release_section(
            phase["id"],
            section_release_payload([certificated["id"]]),
            construction_manager_headers,
        ),
        expected_status=201,
    )
    assert released["status"] == "SECTIONS_RELEASED"
    assert read_homesite(certificated["id"])["status"] == "AVAILABLE"
    assert read_homesite(uncertificated["id"])["status"] == "PLANNED"

    after = read_community(community["id"])
    assert after["lifecycle_status"] == "LEASE_UP"
    assert after["released_unit_count"] == 1


def test_releasing_or_certificating_a_homesite_that_left_planned_is_rejected(
    api, construction_manager_headers
):
    """Once a home is AVAILABLE both construction-side writes close: re-listing it in a release
    and re-issuing its certificate of occupancy are both refused on homesite state.

    "Every listed home must belong to the addressed phase and must currently be `PLANNED`, and a listed home that belongs to another phase or has already left `PLANNED` is `ERR_INVALID_HOMESITE_STATE`."
    "The homesite must still be `PLANNED` — issuing a certificate on a home that has already left `PLANNED` is `ERR_INVALID_HOMESITE_STATE` — and recording a certificate does not itself change the homesite's `status`, which stays `PLANNED`."
    "In particular, a homesite's `released_at` is never rewritten, so a community's `released_unit_count` is unchanged by a halt, by a resume, by a cancellation or by a turn — once a home has been released to leasing it stays counted as released for the rest of its life."

    Design: Corner/validations/releasing_or_certificating_a_homesite_that_left_planned_is_rejected
    """
    community = create_plat_approved_community(
        name="Rookwood",
        market_code="SC-GSP",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    publish_schedule(
        community["id"],
        product_type="DETACHED",
        effective_from="2026-08-01T00:00:00Z",
        asking_rent_cents=285_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=4,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    homesite = create_homesite(
        phase["id"], lot_number="R1", product_type="DETACHED", bedrooms=4, square_feet=2100
    )
    record_occupancy_certificate(
        homesite["id"],
        occupancy_certificate_number="CO-RW-R1",
        issued_at="2026-08-01T00:00:00Z",
    )
    release_section(phase["id"], [homesite["id"]])
    released_at = read_homesite(homesite["id"])["released_at"]

    replay = api.release_section(
        phase["id"], section_release_payload([homesite["id"]]), construction_manager_headers
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_HOMESITE_STATE.value)

    reissue = api.record_occupancy_certificate(
        homesite["id"],
        occupancy_certificate_payload(
            occupancy_certificate_number="CO-RW-R1-REISSUE",
            issued_at="2026-08-02T00:00:00Z",
        ),
        construction_manager_headers,
    )
    validate_error(reissue, ApiErrorId.ERR_INVALID_HOMESITE_STATE.value)

    home = read_homesite(homesite["id"])
    assert home["occupancy_certificate_number"] == "CO-RW-R1"
    assert_instant_equals(
        home["occupancy_certificate_issued_at"],
        "2026-08-01T00:00:00Z",
        "occupancy_certificate_issued_at",
    )
    assert home["status"] == "AVAILABLE"
    assert_instant_equals(home["released_at"], released_at, "released_at")
    assert read_phase(phase["id"])["released_homesite_count"] == 1

    after = read_community(community["id"])
    assert after["released_unit_count"] == 1
    assert after["available_unit_count"] == 1


def test_a_multi_home_section_release_moves_every_listed_home_in_request_order(
    api, construction_manager_headers, property_manager_headers
):
    """One release call carrying three homes moves all three and recomputes the parent counters
    once, and a second call on the same phase is a self-loop that does not re-promote the
    community.

    "A successful release walks the listed homes in the order the client supplied them, moving each from `PLANNED` to `AVAILABLE` and stamping `released_at` with the current logical clock."
    "The addressed phase must have `kind` equal to `HOUSING` and `status` equal to either `UNDER_CONSTRUCTION` — which is the first release and drives the transition `UNDER_CONSTRUCTION → SECTIONS_RELEASED` — or `SECTIONS_RELEASED`, which is the incremental self-loop `SECTIONS_RELEASED → SECTIONS_RELEASED` for a later section."
    "`released_unit_count` is the number of homesites of the community whose `released_at` is not null."
    "The `meta` object of a list response carries `limit` and `offset` as they were actually applied, `total_count` as the number of records matching the filters before the page window is taken, and `has_more` as a boolean that is true when records remain beyond the current window."

    Design: Corner/endpoints/a_multi_home_section_release_moves_every_listed_home_in_request_order
    """
    community = create_plat_approved_community(
        name="Jessamine",
        market_code="NV-LAS",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    publish_schedule(
        community["id"],
        product_type="DETACHED",
        effective_from="2026-08-01T00:00:00Z",
        asking_rent_cents=285_000,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        planned_unit_count=4,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-11-01T00:00:00Z",
    )
    start_construction(phase["id"])
    specs = [
        ("J1", 4, 2100),
        ("J2", 4, 2150),
        ("J3", 3, 1950),
        ("J4", 3, 1900),
    ]
    homes = []
    for lot_number, bedrooms, square_feet in specs:
        home = create_homesite(
            phase["id"],
            lot_number=lot_number,
            product_type="DETACHED",
            bedrooms=bedrooms,
            square_feet=square_feet,
        )
        record_occupancy_certificate(
            home["id"],
            occupancy_certificate_number=f"CO-JS-{lot_number}",
            issued_at="2026-08-01T00:00:00Z",
        )
        homes.append(home)
    first, second, third, fourth = homes

    batch = validate_success(
        api.release_section(
            phase["id"],
            section_release_payload([third["id"], first["id"], second["id"]]),
            construction_manager_headers,
        ),
        expected_status=201,
    )
    assert batch["status"] == "SECTIONS_RELEASED"
    assert batch["released_homesite_count"] == 3
    assert read_phase(phase["id"])["released_homesite_count"] == 3

    for home in (first, second, third):
        listed = read_homesite(home["id"])
        assert listed["status"] == "AVAILABLE"
        assert_instant_equals(listed["released_at"], "2026-08-01T00:00:00Z", "released_at")
    unlisted = read_homesite(fourth["id"])
    assert unlisted["status"] == "PLANNED"
    assert unlisted["released_at"] is None

    after_batch = read_community(community["id"])
    assert after_batch["released_unit_count"] == 3
    assert after_batch["available_unit_count"] == 3
    assert after_batch["lifecycle_status"] == "LEASE_UP"
    assert after_batch["facility_status"] == "ADVANCE_ELIGIBLE"

    page, meta = validate_paginated(
        api.list_homesites(
            property_manager_headers,
            {"phase_id": phase["id"], "status": "AVAILABLE", "limit": 2, "offset": 2},
        )
    )
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert len(page) == 1
    assert meta["has_more"] is False

    self_loop = validate_success(
        api.release_section(
            phase["id"],
            section_release_payload([fourth["id"]]),
            construction_manager_headers,
        ),
        expected_status=201,
    )
    assert self_loop["status"] == "SECTIONS_RELEASED"
    assert self_loop["released_homesite_count"] == 4
    assert read_homesite(fourth["id"])["status"] == "AVAILABLE"

    after_self_loop = read_community(community["id"])
    assert after_self_loop["released_unit_count"] == 4
    assert after_self_loop["lifecycle_status"] == "LEASE_UP"
    assert after_self_loop["facility_status"] == "ADVANCE_ELIGIBLE"
