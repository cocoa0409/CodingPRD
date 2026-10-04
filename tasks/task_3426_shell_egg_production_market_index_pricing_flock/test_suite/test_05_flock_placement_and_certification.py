"""Flock placement gates: landing state, timing window, capacity boundary,
specialty certification, occupancy half-open windows, quarantine and the
state-before-safety validation order.
"""

from test_helpers import (
    ADMIN,
    AUDITOR,
    HEALTH,
    PLANNER,
    api_client,
    assert_flock,
    assert_house,
    assert_instant_equal,
    complete_depopulation_order,
    confirm_disease_event,
    create_and_place_flock,
    create_certification,
    create_complex,
    create_depopulation_order,
    create_disease_event,
    create_house,
    create_planned_flock,
    place_flock,
    read_flock,
    read_house,
    record_certification_result,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_flock_place_valid_transition_to_growing(api):
    """Placing on the placement date lands in GROWING at age 0.

    PRD §3.2: "On success the flock's `age_weeks` is set to the whole weeks
    elapsed between `placement_date` and the clock, `current_hen_count`
    becomes `placed_hen_count`, the house's `hen_inventory` rises accordingly
    (bumping the house's `version`), and the flock's `version` increments. The
    landing state depends on that computed age: a flock placed younger than
    eighteen weeks lands in `GROWING`, one placed at eighteen weeks or older
    lands directly in `LAYING`."

    Design: Corner/state_machines/flock_place_valid_transition_to_growing
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_planned_flock(
        house["id"], placement_date="2026-09-01T00:00:00Z",
        placed_hen_count=10_000,
    )
    version_at_create = flock["version"]

    placed = validate_success(api.place_flock(flock["id"], PLANNER))
    assert_flock(placed)
    assert placed["status"] == "GROWING"
    assert placed["age_weeks"] == 0
    assert placed["current_hen_count"] == 10_000
    assert placed["version"] == version_at_create + 1

    assert read_house(house["id"])["hen_inventory"] == 10_000


def test_placement_not_due_and_window_missed(api):
    """Placement timing is two-sided: too early and more than thirty whole
    weeks late both fail; exactly thirty weeks is still allowed.

    PRD §3.2: "the clock must have reached `placement_date` (else
    `ERR_PLACEMENT_NOT_DUE`) yet lie no more than thirty whole weeks past it
    (else `ERR_PLACEMENT_WINDOW_MISSED`)".

    Design: Corner/validations/placement_not_due_and_window_missed
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house_a = create_house(complex_["id"], house_code="H1", capacity_hens=50_000)
    house_b = create_house(complex_["id"], house_code="H2", capacity_hens=50_000)
    house_c = create_house(complex_["id"], house_code="H3", capacity_hens=50_000)
    early = create_planned_flock(
        house_a["id"], flock_code="FA",
        placement_date="2026-09-10T00:00:00Z", placed_hen_count=10_000,
    )
    exact = create_planned_flock(
        house_b["id"], flock_code="FB",
        placement_date="2026-02-02T00:00:00Z", placed_hen_count=10_000,
    )
    late = create_planned_flock(
        house_c["id"], flock_code="FC",
        placement_date="2026-01-26T00:00:00Z", placed_hen_count=10_000,
    )

    # Clock 2026-09-01 is before 2026-09-10.
    validate_error(api.place_flock(early["id"], PLANNER), ERR.ERR_PLACEMENT_NOT_DUE)
    # Exactly thirty whole weeks after 2026-02-02: allowed, age 30 -> LAYING.
    placed = validate_success(api.place_flock(exact["id"], PLANNER))
    assert placed["status"] == "LAYING"
    assert placed["age_weeks"] == 30
    # Thirty-one whole weeks after 2026-01-26: missed.
    validate_error(
        api.place_flock(late["id"], PLANNER), ERR.ERR_PLACEMENT_WINDOW_MISSED
    )
    assert read_flock(late["id"])["status"] == "PLANNED"


def test_house_capacity_exact_fill_allowed(api):
    """A placed_hen_count exactly equal to the remaining capacity is accepted.

    PRD §3.2: "the house must have room — `hen_inventory` plus
    `placed_hen_count` must not exceed `capacity_hens`, with exact fill
    allowed (else `ERR_HOUSE_OVER_CAPACITY`)".

    Design: Difficulty/boundary_precision_check/house_capacity_exact_fill_allowed_plus_one_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], house_code="HA", capacity_hens=50_000)
    flock = create_planned_flock(
        house["id"], flock_code="FA",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=50_000,
    )

    placed = validate_success(api.place_flock(flock["id"], PLANNER))
    assert placed["status"] == "GROWING"
    assert placed["current_hen_count"] == 50_000
    assert read_house(house["id"])["hen_inventory"] == 50_000


def test_house_capacity_plus_one_rejected(api):
    """One hen over capacity is ERR_HOUSE_OVER_CAPACITY and places nothing.

    PRD §3.2: "the house must have room — `hen_inventory` plus
    `placed_hen_count` must not exceed `capacity_hens`, with exact fill
    allowed (else `ERR_HOUSE_OVER_CAPACITY`)".

    Design: Difficulty/boundary_precision_check/house_capacity_exact_fill_allowed_plus_one_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], house_code="HB", capacity_hens=50_000)
    flock = create_planned_flock(
        house["id"], flock_code="FB",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=50_001,
    )

    validate_error(api.place_flock(flock["id"], PLANNER), ERR.ERR_HOUSE_OVER_CAPACITY)
    after = read_flock(flock["id"])
    assert after["status"] == "PLANNED"
    assert after["current_hen_count"] == 0
    assert read_house(house["id"])["hen_inventory"] == 0


def test_specialty_placement_rejected_without_passed_certification(api):
    """Placing a CAGE_FREE flock without a PASSED house certification fails.

    PRD §3.2: "for a `CAGE_FREE` or `ORGANIC` program the house must hold a
    certification for the same program in `PASSED` status whose window
    currently contains the clock (else `ERR_CERTIFICATION_REQUIRED`)".

    Design: Difficulty/cross_entity_state_dependency/specialty_placement_requires_passed_certification
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(
        complex_["id"], house_code="H2", housing_style="CAGE_FREE",
        capacity_hens=80_000,
    )
    flock = create_planned_flock(
        house["id"], flock_code="F2", program="CAGE_FREE",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=60_000,
    )

    validate_error(
        api.place_flock(flock["id"], PLANNER), ERR.ERR_CERTIFICATION_REQUIRED
    )
    assert read_flock(flock["id"])["status"] == "PLANNED"
    assert read_house(house["id"])["hen_inventory"] == 0


def test_specialty_placement_succeeds_once_certification_passes(api):
    """A PASSED certification opens the validity window at the record clock,
    and the identical placement then succeeds.

    PRD §3.1: "a `result` of `PASSED` stamps `valid_from` with the logical
    clock at recording time and sets `valid_until` exactly 365 days later,
    opening a half-open validity window that includes `valid_from` and
    excludes `valid_until`".
    PRD §3.2: "for a `CAGE_FREE` or `ORGANIC` program the house must hold a
    certification for the same program in `PASSED` status whose window
    currently contains the clock (else `ERR_CERTIFICATION_REQUIRED`)".

    Design: Difficulty/cross_entity_state_dependency/specialty_placement_requires_passed_certification
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(
        complex_["id"], house_code="H2", housing_style="CAGE_FREE",
        capacity_hens=80_000,
    )
    flock = create_planned_flock(
        house["id"], flock_code="F2", program="CAGE_FREE",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=60_000,
    )
    cert = create_certification(house["id"], program="CAGE_FREE")
    passed = record_certification_result(cert["id"], "PASSED")
    assert passed["status"] == "PASSED"
    assert passed["result"] == "PASSED"
    assert_instant_equal(passed["valid_from"], "2026-09-01T00:00:00Z", "valid_from")
    assert_instant_equal(passed["valid_until"], "2027-09-01T00:00:00Z", "valid_until")

    placed = validate_success(api.place_flock(flock["id"], PLANNER))
    assert placed["status"] == "GROWING"
    assert placed["current_hen_count"] == 60_000
    assert read_house(house["id"])["hen_inventory"] == 60_000


def test_certification_expiry_via_run_ops_blocks_specialty_placement(api):
    """The half-open validity window excludes valid_until: a run-ops at that
    instant expires the cert and the placement fails.

    PRD §3.1: "Thereafter, any complex's operations checkpoint expires a
    `PASSED` certification into `EXPIRED` once the clock reaches
    `valid_until`."
    PRD §3.2: "for a `CAGE_FREE` or `ORGANIC` program the house must hold a
    certification for the same program in `PASSED` status whose window
    currently contains the clock (else `ERR_CERTIFICATION_REQUIRED`)".

    Design: Corner/state_machines/certification_expiry_via_run_ops_blocks_specialty_placement
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(
        complex_["id"], house_code="H2", housing_style="CAGE_FREE",
        capacity_hens=80_000,
    )
    cert = create_certification(house["id"], program="CAGE_FREE")
    record_certification_result(cert["id"], "PASSED")

    # Advance exactly to valid_until and checkpoint: the window has closed.
    set_clock("2027-09-01T00:00:00Z")
    run_ops(complex_["id"])

    expired_rows, expired_meta = validate_paginated(
        api.list_certifications(house["id"], ADMIN, params={"status": "EXPIRED"})
    )
    assert expired_meta["total_count"] == 1
    assert expired_rows[0]["id"] == cert["id"]
    assert expired_rows[0]["status"] == "EXPIRED"
    flock = create_planned_flock(
        house["id"], flock_code="F2", program="CAGE_FREE",
        placement_date="2027-09-01T00:00:00Z", placed_hen_count=60_000,
    )
    validate_error(
        api.place_flock(flock["id"], PLANNER), ERR.ERR_CERTIFICATION_REQUIRED
    )
    assert read_flock(flock["id"])["status"] == "PLANNED"


def test_certification_failed_is_terminal(api):
    """FAILED never opens a validity window, cannot be re-recorded, and does
    not satisfy the specialty gate.

    PRD §3.1: "a `result` of `FAILED` is terminal with no window. Recording
    the outcome is only legal from `SCHEDULED` (otherwise
    `ERR_INVALID_STATE`)".
    PRD §3.2: "for a `CAGE_FREE` or `ORGANIC` program the house must hold a
    certification for the same program in `PASSED` status whose window
    currently contains the clock (else `ERR_CERTIFICATION_REQUIRED`)".

    Design: Corner/state_machines/certification_failed_is_terminal
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(
        complex_["id"], house_code="H2", housing_style="CAGE_FREE",
        capacity_hens=80_000,
    )
    cert = create_certification(house["id"], program="CAGE_FREE")
    failed = record_certification_result(cert["id"], "FAILED")
    assert failed["status"] == "FAILED"
    assert failed["result"] == "FAILED"
    assert failed["valid_from"] is None
    assert failed["valid_until"] is None

    validate_error(
        api.record_certification_result(cert["id"], {"result": "PASSED"},
                                        AUDITOR),
        ERR.ERR_INVALID_STATE,
    )

    flock = create_planned_flock(
        house["id"], flock_code="F2", program="CAGE_FREE",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=60_000,
    )
    validate_error(
        api.place_flock(flock["id"], PLANNER), ERR.ERR_CERTIFICATION_REQUIRED
    )


def test_program_housing_mismatch_rejected_at_create(api):
    """A CAGE_FREE flock planned into a CONVENTIONAL house fails at creation.

    PRD §3.2: "First, the flock's `program` must equal the house's
    `housing_style`, else `ERR_PROGRAM_HOUSING_MISMATCH`."

    Design: Corner/validations/program_housing_mismatch_rejected_at_create
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=80_000)

    response = api.create_flock(
        house["id"],
        {
            "flock_code": "F2",
            "program": "CAGE_FREE",
            "ownership": "OWNED",
            "placement_date": "2026-12-01T00:00:00Z",
            "placed_hen_count": 60_000,
        },
        PLANNER,
    )
    validate_error(response, ERR.ERR_PROGRAM_HOUSING_MISMATCH)
    rows, meta = validate_paginated(api.list_flocks(house["id"], PLANNER))
    assert rows == [] and meta["total_count"] == 0


def test_contract_flock_without_grower_returns_grower_required(api):
    """grower_name is required exactly when ownership is CONTRACT.

    PRD §3.2: "Contract flocks must identify their grower: omitting
    `grower_name` when `ownership` is `CONTRACT` fails with
    `ERR_GROWER_REQUIRED`, while for owned flocks the name is optional and
    simply stored."

    Design: Corner/validations/contract_flock_without_grower_returns_grower_required
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=200_000)

    response = api.create_flock(
        house["id"],
        {
            "flock_code": "FC",
            "program": "CONVENTIONAL",
            "ownership": "CONTRACT",
            "placement_date": "2026-12-01T00:00:00Z",
            "placed_hen_count": 40_000,
        },
        PLANNER,
    )
    validate_error(response, ERR.ERR_GROWER_REQUIRED)

    owned = validate_success(
        api.create_flock(
            house["id"],
            {
                "flock_code": "FO",
                "program": "CONVENTIONAL",
                "ownership": "OWNED",
                "placement_date": "2026-12-01T00:00:00Z",
                "placed_hen_count": 40_000,
            },
            PLANNER,
        ),
        201,
    )
    assert_flock(owned)
    assert owned["ownership"] == "OWNED"


def test_place_into_quarantined_complex_rejected(api):
    """A valid PLANNED flock cannot place while its complex is QUARANTINE.

    PRD §2.7: "`QUARANTINE` is a hard gate on two operations — flock
    placement and packing-run creation both fail with
    `ERR_COMPLEX_QUARANTINED`".

    Design: Corner/errors/place_into_quarantined_complex_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house1 = create_house(complex_["id"], house_code="H1", capacity_hens=50_000)
    house2 = create_house(complex_["id"], house_code="H2", capacity_hens=50_000)
    create_and_place_flock(
        house1["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=10_000,
    )
    event = create_disease_event(complex_["id"], [house1["id"]])
    confirm_disease_event(event["id"])

    # F2 is planned AFTER the confirmation, so the cancel cascade cannot
    # reach it; the pure safety gate is what rejects its placement.
    flock2 = create_planned_flock(
        house2["id"], flock_code="F2",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=10_000,
    )
    validate_error(
        api.place_flock(flock2["id"], PLANNER), ERR.ERR_COMPLEX_QUARANTINED
    )
    assert read_flock(flock2["id"])["status"] == "PLANNED"


def _setup_depopulated_quarantined_flock(api):
    """LAYING flock, then HPAI confirm + completed INCINERATION order.

    Returns (complex, house, flock): the flock is DEPOPULATED and the complex
    is QUARANTINE.
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Quarantine Ridge")
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=10_000,
    )
    event = create_disease_event(complex_["id"], [house["id"]])
    confirm_disease_event(event["id"])
    order = create_depopulation_order(event["id"], house["id"], "INCINERATION")
    complete_depopulation_order(order["id"])
    return complex_, house, flock


def test_place_reports_state_before_quarantine_safety(api):
    """A DEPOPULATED flock inside a QUARANTINE complex reports the state
    failure, not the safety failure.

    PRD §3.2: "the checks run in a fixed order: the flock must be `PLANNED`
    (else `ERR_INVALID_STATE`); the complex's posture must not be `QUARANTINE`
    (else `ERR_COMPLEX_QUARANTINED`)".
    PRD §2.11: "validation proceeds in layers and the **first** failing layer
    determines the error."

    Design: Difficulty/priority_pair_validation_conflict/place_reports_state_before_quarantine_safety
    """
    _, _, flock = _setup_depopulated_quarantined_flock(api)
    assert read_flock(flock["id"])["status"] == "DEPOPULATED"

    response = api.place_flock(flock["id"], PLANNER)
    error = validate_error(response, ERR.ERR_INVALID_STATE)
    assert error["error_id"] != ERR.ERR_COMPLEX_QUARANTINED.value


def test_place_rejected_twice_leaves_depopulated_flock_untouched(api):
    """The rejected placement mutates nothing: the flock stays DEPOPULATED
    and the complex stays QUARANTINE.

    PRD §3.2: "the checks run in a fixed order: the flock must be `PLANNED`
    (else `ERR_INVALID_STATE`); the complex's posture must not be `QUARANTINE`
    (else `ERR_COMPLEX_QUARANTINED`)".
    PRD §3.3: "Completing an order ... depopulates every flock of the target
    house in `GROWING`, `LAYING`, or `MOLT` to `DEPOPULATED` with
    `current_hen_count` zeroed".

    Design: Difficulty/priority_pair_validation_conflict/place_reports_state_before_quarantine_safety
    """
    complex_, _, flock = _setup_depopulated_quarantined_flock(api)
    before = read_flock(flock["id"])
    assert before["status"] == "DEPOPULATED"
    assert before["current_hen_count"] == 0

    validate_error(api.place_flock(flock["id"], PLANNER), ERR.ERR_INVALID_STATE)

    after = read_flock(flock["id"])
    assert after["status"] == "DEPOPULATED"
    assert after["current_hen_count"] == 0
    assert after["version"] == before["version"]
    complex_after = validate_success(api.get_complex(complex_["id"], HEALTH))
    assert complex_after["biosecurity_posture"] == "QUARANTINE"


def test_house_occupancy_overlap_by_one_day_rejected(api):
    """A window starting one day before the predecessor's end collides.

    PRD §3.2: "the flock claims a half-open occupancy window of its house
    running from `placement_date` to 560 days later, and that window must not
    overlap the occupancy window of any other flock of the same house in
    `PLANNED`, `GROWING`, `LAYING`, or `MOLT`; because the windows are
    half-open, pure adjacency — one flock's start equal to another's end — is
    allowed, and an actual overlap is `ERR_HOUSE_OCCUPANCY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/house_occupancy_half_open_adjacency
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Occupancy House")
    house = create_house(complex_["id"], capacity_hens=200_000)
    create_planned_flock(
        house["id"], flock_code="FA",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=90_000,
    )

    # FA's window is [2026-09-01, 2028-03-14); 2028-03-13 is one day inside.
    response = api.create_flock(
        house["id"],
        {
            "flock_code": "FB",
            "program": "CONVENTIONAL",
            "ownership": "OWNED",
            "placement_date": "2028-03-13T00:00:00Z",
            "placed_hen_count": 90_000,
        },
        PLANNER,
    )
    validate_error(response, ERR.ERR_HOUSE_OCCUPANCY_CONFLICT)
    rows, meta = validate_paginated(api.list_flocks(house["id"], PLANNER))
    assert meta["total_count"] == 1


def test_house_occupancy_exact_adjacency_allowed(api):
    """A window starting exactly at the predecessor's end is accepted.

    PRD §3.2: "the flock claims a half-open occupancy window of its house
    running from `placement_date` to 560 days later, and that window must not
    overlap the occupancy window of any other flock of the same house in
    `PLANNED`, `GROWING`, `LAYING`, or `MOLT`; because the windows are
    half-open, pure adjacency — one flock's start equal to another's end — is
    allowed, and an actual overlap is `ERR_HOUSE_OCCUPANCY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/house_occupancy_half_open_adjacency
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Occupancy House")
    house = create_house(complex_["id"], capacity_hens=200_000)
    create_planned_flock(
        house["id"], flock_code="FA",
        placement_date="2026-09-01T00:00:00Z", placed_hen_count=90_000,
    )

    adjacent = validate_success(
        api.create_flock(
            house["id"],
            {
                "flock_code": "FC",
                "program": "CONVENTIONAL",
                "ownership": "OWNED",
                "placement_date": "2028-03-14T00:00:00Z",
                "placed_hen_count": 90_000,
            },
            PLANNER,
        ),
        201,
    )
    assert adjacent["status"] == "PLANNED"
    rows, meta = validate_paginated(api.list_flocks(house["id"], PLANNER))
    assert meta["total_count"] == 2


def test_depopulated_flock_rejects_all_actions(api):
    """DEPOPULATED is terminal: molt and place both fail and nothing changes.

    PRD §3.2: "Depletion (age eighty), depopulation (§3.3), and
    quarantine-driven cancellation of still-`PLANNED` flocks are the terminal
    exits; flocks in `DEPLETED`, `DEPOPULATED`, or `CANCELLED` contribute
    nothing to `hen_inventory`."
    PRD §2.11: "(7) state-machine legality, including cross-entity state
    gates, reported as `ERR_INVALID_STATE`".

    Design: Corner/state_machines/depopulated_flock_rejects_all_actions
    """
    _, _, flock = _setup_depopulated_quarantined_flock(api)

    validate_error(api.molt_flock(flock["id"], PLANNER), ERR.ERR_INVALID_STATE)
    validate_error(api.place_flock(flock["id"], PLANNER), ERR.ERR_INVALID_STATE)

    after = read_flock(flock["id"])
    assert after["status"] == "DEPOPULATED"
    assert after["current_hen_count"] == 0
