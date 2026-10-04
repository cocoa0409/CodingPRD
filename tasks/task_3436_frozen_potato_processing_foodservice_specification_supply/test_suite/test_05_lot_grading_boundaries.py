"""Lot grading composition and boundary precision, plus the two validation
priority pairs where one failing gate must mask a later one."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_contracted_lot_payload,
    create_reading_payload,
    deliver_lot,
    make_contract,
    make_facility,
    make_grower,
    make_grower_headers,
    record_reading,
    set_clock,
    setup_procurement,
    validate_error,
    validate_paginated,
    validate_success,
)

GRM = TEST_USERS["grower_relations_manager_headers"]


def _deliver_with_metrics(api, world, defect, gravity, sugar):
    resp = api.create_potato_lot(
        create_contracted_lot_payload(
            world["contract"]["id"], world["facility"]["id"],
            defect_pct=defect, specific_gravity=gravity, sugar_end_rating=sugar,
        ),
        make_grower_headers(world["grower"]["id"]),
    )
    return validate_success(resp, 201)


def test_quality_grade_worst_of_three_metrics_with_reject_override(api):
    """PRD §3.2: "The lot's `grade` is the worst of the three tiers on the
    ordering where `A` outranks `B`, `B` outranks `C`, and `C` outranks
    `REJECT`; any `REJECT` tier makes the lot `REJECT`."
    PRD §3.2: "A lot whose `defect_pct` is 8.0 or greater is `REJECT`
    regardless of its other metrics — the defect override is evaluated first."
    PRD §3.2: "A `REJECT` lot is still persisted like any other."

    Design: Difficulty/combinatorial_formula/quality_grade_worst_of_three_metrics_with_reject_override
    """
    world = setup_procurement(api=api)
    # defect B (4.0) / gravity A (1.085) / sugar C (3.5) -> worst is C.
    lot_c = _deliver_with_metrics(api, world, 4.0, 1.085, 3.5)
    assert lot_c["grade"] == "C", f"worst of B/A/C must be C, got {lot_c['grade']}"
    assert lot_c["provisional_payment_cents"] == 2200000, "1000.0 x 2500 x 0.88"

    # defect 8.0 triggers the override despite A-grade gravity and sugar.
    lot_r = _deliver_with_metrics(api, world, 8.0, 1.085, 1.5)
    assert lot_r["grade"] == "REJECT"
    assert lot_r["provisional_payment_cents"] == 0
    assert lot_r["status"] == "IN_STORAGE", "a REJECT lot is still persisted and stored"


def test_quality_grade_gravity_and_sugar_alone_can_reject(api):
    """PRD §3.2: "The gravity tier is `A` when `specific_gravity` is at least
    1.080, `B` when at least 1.070, `C` when at least 1.060, and `REJECT`
    below that. The sugar tier is `A` when `sugar_end_rating` is at most 2.0,
    `B` when at most 3.0, `C` when at most 4.0, and `REJECT` above that."
    PRD §3.2: "The defect tier is `A` when `defect_pct` is below 3.0, `B` when
    below 5.0, and `C` otherwise."

    Design: Difficulty/combinatorial_formula/quality_grade_worst_of_three_metrics_with_reject_override
    """
    world = setup_procurement(api=api)
    # gravity 1.059 (< 1.060) is a REJECT tier even with A defect and sugar.
    lot_g = _deliver_with_metrics(api, world, 1.0, 1.059, 1.5)
    assert lot_g["grade"] == "REJECT", f"gravity below 1.060 rejects, got {lot_g['grade']}"
    assert lot_g["provisional_payment_cents"] == 0

    # all-B metrics compose to B and pay the B multiplier.
    lot_b = _deliver_with_metrics(api, world, 3.0, 1.075, 2.5)
    assert lot_b["grade"] == "B"
    assert lot_b["provisional_payment_cents"] == 2575000, "1000.0 x 2500 x 1.03"


def test_defect_pct_exactly_at_reject_threshold_rejects(api):
    """PRD §3.2: "A lot whose `defect_pct` is 8.0 or greater is `REJECT`
    regardless of its other metrics — the defect override is evaluated first."
    PRD §3.2: "Inputs are compared exactly as given, with no rounding."

    Design: Difficulty/boundary_precision_check/defect_pct_exactly_at_reject_threshold_rejects
    """
    world = setup_procurement(api=api)
    below = _deliver_with_metrics(api, world, 7.99, 1.085, 1.5)
    assert below["grade"] == "C", "7.99 stays in the C tier (below 8.0)"
    assert below["provisional_payment_cents"] == 2200000

    at = _deliver_with_metrics(api, world, 8.0, 1.085, 1.5)
    assert at["grade"] == "REJECT", "the threshold is inclusive: exactly 8.0 rejects"
    assert at["provisional_payment_cents"] == 0


def test_defect_pct_five_percent_boundary_b_becomes_c(api):
    """PRD §3.2: "The defect tier is `A` when `defect_pct` is below 3.0, `B`
    when below 5.0, and `C` otherwise."
    PRD §3.2: "Inputs are compared exactly as given, with no rounding."

    Design: Difficulty/boundary_precision_check/defect_pct_exactly_at_reject_threshold_rejects
    """
    world = setup_procurement(api=api)
    below = _deliver_with_metrics(api, world, 4.99, 1.085, 1.5)
    assert below["grade"] == "B", "4.99 is below 5.0 so the defect tier is B"
    assert below["provisional_payment_cents"] == 2575000, "1000.0 x 2500 x 1.03"

    at = _deliver_with_metrics(api, world, 5.0, 1.085, 1.5)
    assert at["grade"] == "C", "exactly 5.0 is not 'below 5.0' so the tier is C"
    assert at["provisional_payment_cents"] == 2200000, "1000.0 x 2500 x 0.88"


def test_lot_create_draft_contract_state_gate_beats_capacity_gate(api):
    """PRD §2.10: "When several checks could reject the same request, the
    server evaluates them in a fixed priority order and returns the first
    failure encountered." The fixed order lists "6. **State preconditions**"
    (all HTTP 409) ahead of "10. **Capacity, inventory, and quality
    thresholds**" (all HTTP 422).
    PRD §3.2: "the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`
    otherwise)".

    Design: Difficulty/priority_pair_validation_conflict/lot_create_draft_contract_and_overcapacity_state_beats_fiscal
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    tiny = make_facility(api=api, facility_code="CELL-TINY", capacity_cwt=500)
    contract = make_contract(grower["id"], api=api)  # stays DRAFT

    resp = api.create_potato_lot(
        create_contracted_lot_payload(contract["id"], tiny["id"]),
        make_grower_headers(grower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
    assert resp.status_code == 409, (
        "the priority-6 state error must win even though 1000.0 cwt also "
        "exceeds the 500-cwt facility (priority 10)"
    )
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED
    rows, _ = validate_paginated(api.list_potato_lots(GRM, params={"contract_id": contract["id"]}))
    assert rows == []


def test_lot_create_overcapacity_alone_fires_capacity_error(api):
    """PRD §3.2: "The destination facility must not be `QUARANTINED`
    (`ERR_FACILITY_QUARANTINED`), and its free capacity — `capacity_cwt` minus
    its `current_stock_cwt` — must be at least the lot's `net_weight_cwt`,
    else `ERR_FACILITY_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/lot_create_draft_contract_and_overcapacity_state_beats_fiscal
    """
    world = setup_procurement(api=api, facility_overrides={
        "facility_code": "CELL-TINY", "capacity_cwt": 500,
    })  # contract ACTIVE; only the capacity gate can fail
    resp = api.create_potato_lot(
        create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"]),
        make_grower_headers(world["grower"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)
    assert resp.status_code == 422, "500 free < 1000.0 net"
    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"contract_id": world["contract"]["id"]})
    )
    assert rows == []


def test_lot_create_quarantine_gate_beats_delivery_window_gate(api):
    """PRD §2.10: "When several checks could reject the same request, the
    server evaluates them in a fixed priority order and returns the first
    failure encountered." The fixed order lists "7. **Quarantine
    isolation**" (HTTP 409) ahead of "9. **Delivery timing and variety**"
    (HTTP 422).
    PRD §2.8: "Receiving a new lot into a `QUARANTINED` facility is rejected
    with `ERR_FACILITY_QUARANTINED` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/lot_create_quarantined_and_outside_window_safety_beats_temporal
    """
    world = setup_procurement(api=api)  # window ends 2026-10-15
    record_reading(
        world["facility"]["id"], api=api,
        recorded_at="2026-09-03T00:00:00Z", temperature_f=42.0, humidity_pct=95.0,
        co2_pct=4.5, sprout_index=4.2, disease_incidence_pct=8.0,
    )  # disease 8.0 >= 6.0 -> QUARANTINED
    set_clock("2026-11-01T00:00:00Z", api=api)  # also outside the window

    resp = api.create_potato_lot(
        create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"]),
        make_grower_headers(world["grower"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_QUARANTINED)
    assert resp.status_code == 409, (
        "the priority-7 safety error must win even though the clock is also "
        "outside the delivery window (priority 9)"
    )
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW
    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"facility_id": world["facility"]["id"]})
    )
    assert rows == []


def test_lot_create_outside_window_alone_fires_after_posture_clears(api):
    """PRD §3.3: "Each new reading recomputes the facility's `posture` from
    the latest reading alone — the one with the greatest `recorded_at`, with
    ties broken in favor of the reading appended last."
    PRD §3.2: "the logical clock must fall inside the contract's delivery
    window — from `delivery_window_start` through `delivery_window_end`,
    inclusive at both ends (`ERR_OUTSIDE_DELIVERY_WINDOW` otherwise)".

    Design: Difficulty/priority_pair_validation_conflict/lot_create_quarantined_and_outside_window_safety_beats_temporal
    """
    world = setup_procurement(api=api)
    record_reading(
        world["facility"]["id"], api=api,
        recorded_at="2026-09-03T00:00:00Z", temperature_f=42.0, humidity_pct=95.0,
        co2_pct=4.5, sprout_index=4.2, disease_incidence_pct=8.0,
    )  # QUARANTINED
    record_reading(
        world["facility"]["id"], api=api,
        recorded_at="2026-09-04T00:00:00Z", temperature_f=38.0, humidity_pct=90.0,
        co2_pct=3.0, sprout_index=1.0, disease_incidence_pct=1.0,
    )  # later reading clears every threshold -> NORMAL
    set_clock("2026-11-01T00:00:00Z", api=api)  # outside the window only

    resp = api.create_potato_lot(
        create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"]),
        make_grower_headers(world["grower"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW)
    assert resp.status_code == 422, "with the quarantine cleared, the temporal gate fires alone"
