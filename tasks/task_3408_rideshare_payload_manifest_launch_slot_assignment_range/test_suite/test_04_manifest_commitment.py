"""Manifest commitment accounting: TOTAL vs FIRM variants, capacity boundary,
validation-priority pairs, and the assign/remove compensating invariant."""
from test_helpers import (
    ApiErrorId,
    assignment_payload,
    confirm_assignment,
    create_assignment,
    create_customer,
    create_mission,
    create_port,
    create_signed_contract,
    get_assignment,
    get_contract,
    get_mission,
    lock_manifest,
    mission_version,
    payload_entry,
    review_assignment,
    set_clock,
    setup_confirmed_mission,
    setup_provisional_assignments,
    validate_error,
    validate_paginated,
    validate_success,
    verify_assignment,
    api_client,
)
from test_helpers.test_users import TEST_USERS

MOPS = TEST_USERS["mission_ops_headers"]


def _setup_one_confirmed_one_provisional():
    """PL1 100 kg RING_15 CONFIRMED on DSP-A; PL2 50 kg CUBESAT PROVISIONAL on DSP-B."""
    ctx = setup_provisional_assignments(
        port_specs=[{}, {"port_code": "DSP-B", "stack_position": 3, "max_mass_kg": 100,
                         "supported_interface_classes": ["CUBESAT"]}],
        payload_specs=[{}, {"payload_name": "PL2", "mass_kg": 50, "volume_m3": 1.0,
                            "interface_class": "CUBESAT"}],
    )
    a1 = ctx["assignments"][0]
    verify_assignment(a1["id"])
    review_assignment(a1["id"])
    ctx["assignments"][0] = confirm_assignment(a1["id"])
    return ctx


def test_commitment_total_counts_provisional_and_confirmed(api):
    """PRD §2.9: "`committed_mass_kg` and `committed_volume_m3` implement the
    TOTAL variant of manifest commitment: they sum the `mass_kg` and `volume_m3`
    of payloads whose assignments to the mission stand in `PROVISIONAL`,
    `CONFIRMED`, or `INTEGRATED`."

    Design: Difficulty/dual_variant_calc/manifest_commitment_total_counts_provisional_firm_counts_confirmed_only
    """
    ctx = _setup_one_confirmed_one_provisional()
    mission = get_mission(ctx["mission"]["id"])
    assert mission["committed_mass_kg"] == 150, (
        f"TOTAL variant counts PROVISIONAL: expected 150, got {mission['committed_mass_kg']}"
    )
    assert mission["committed_volume_m3"] == 3.0


def test_commitment_firm_counts_confirmed_only(api):
    """PRD §2.9: "`firm_mass_kg` implements the FIRM variant: the same mass sum
    restricted to assignments in `CONFIRMED` or `INTEGRATED`, excluding
    provisional reservations. For a mission holding 100 kg of confirmed
    assignments and 50 kg of provisional ones, the committed mass reads 150 kg
    while the firm mass reads 100 kg."

    Design: Difficulty/dual_variant_calc/manifest_commitment_total_counts_provisional_firm_counts_confirmed_only
    """
    ctx = _setup_one_confirmed_one_provisional()
    mission = get_mission(ctx["mission"]["id"])
    assert mission["firm_mass_kg"] == 100, (
        f"FIRM variant excludes PROVISIONAL: expected 100, got {mission['firm_mass_kg']}"
    )
    assert mission["committed_mass_kg"] != mission["firm_mass_kg"]
    a1 = validate_success(api_client.get_assignment(ctx["assignments"][0]["id"], MOPS), 200)
    a2 = validate_success(api_client.get_assignment(ctx["assignments"][1]["id"], MOPS), 200)
    assert a1["status"] == "CONFIRMED" and a2["status"] == "PROVISIONAL"


def test_contract_advances_signed_to_manifested_on_first_assignment(api):
    """PRD §3.2: "From `SIGNED`, a contract automatically advances to
    `MANIFESTED` the moment the first live assignment is created for one of its
    payloads (§3.3)"
    PRD §3.3: "If this is the contract's first live assignment, the contract
    advances from `SIGNED` to `MANIFESTED`, incrementing its `version`."

    Design: Difficulty/non_linear_state_machine/contract_cycles_signed_manifested_signed_on_assignment_removal
    """
    ctx = setup_provisional_assignments()
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "MANIFESTED"
    assert contract["version"] == ctx["contract"]["version"] + 1, (
        "SIGNED -> MANIFESTED increments the contract version by exactly 1"
    )
    payload = validate_success(
        api_client.list_contract_payloads(contract["id"], MOPS), 200
    )[0]
    assert payload["status"] == "MANIFESTED"


def test_contract_falls_back_to_signed_on_last_assignment_removal(api):
    """PRD §3.2: "it falls back from `MANIFESTED` to `SIGNED` whenever its last
    live assignment leaves the manifest through any removal path — manual
    removal, the delay cascade, a license revocation cascade, or a scrub."
    PRD §3.3: "Removal releases capacity: the mission's commitment fields are
    recomputed, the payload returns from `MANIFESTED` to `REGISTERED` with a
    version increment, and — when the removed assignment was the contract's last
    live one — the contract falls back from `MANIFESTED` to `SIGNED` with its
    own increment."

    Design: Difficulty/non_linear_state_machine/contract_cycles_signed_manifested_signed_on_assignment_removal
    """
    ctx = setup_provisional_assignments()
    manifested = get_contract(ctx["contract"]["id"])
    resp = api_client.remove_assignment(
        ctx["assignments"][0]["id"], MOPS, reason_code="CUSTOMER_REQUEST"
    )
    removed = validate_success(resp, 200)
    assert removed["status"] == "REMOVED"
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "SIGNED", "cycle back, not forward"
    assert contract["version"] == manifested["version"] + 1
    payload = validate_success(
        api_client.list_contract_payloads(contract["id"], MOPS), 200
    )[0]
    assert payload["status"] == "REGISTERED"
    mission = get_mission(ctx["mission"]["id"])
    assert mission["committed_mass_kg"] == 0


def _setup_window_and_mass_conflict():
    """Mission 300 kg / 10 m3 with PL_A 100 kg assigned; PL_B 250 kg contract
    window [2026-10-01, 2026-10-15] that does not cover the mission window."""
    set_clock()
    customer = create_customer()
    mission = create_mission(
        mission_name="Transporter-X2", volume_capacity_m3=10.0
    )
    port_a = create_port(mission["id"])
    port_c = create_port(
        mission["id"], port_code="DSP-C", stack_position=2, max_mass_kg=150,
        supported_interface_classes=["RING_24"],
    )
    ct1, payloads1 = create_signed_contract(
        customer["id"], [payload_entry(payload_name="PL_A", mass_kg=100)]
    )
    create_assignment(mission["id"], payloads1[0]["id"], port_a["id"])
    ct2, payloads2 = create_signed_contract(
        customer["id"],
        [payload_entry(payload_name="PL_B", mass_kg=250, interface_class="RING_24")],
        window_close_utc="2026-10-15T00:00:00Z",
    )
    return mission, port_c, payloads2[0]


def test_window_incompatible_wins_over_mass_overflow(api):
    """PRD §2.6: "Every request passes through the same validation pipeline, and
    the stages run in a fixed order: a failure at an earlier stage masks every
    later check, so the response always carries the first applicable rejection."
    (window arithmetic, stage 9, precedes capacity, stage 11.)

    Design: Difficulty/priority_pair_validation_conflict/assignment_with_bad_window_and_mass_overflow_reports_window_error
    """
    mission, port_c, pl_b = _setup_window_and_mass_conflict()
    resp = api_client.create_assignment(
        assignment_payload(mission["id"], pl_b["id"], port_c["id"], mission_version(mission["id"])),
        MOPS,
    )
    err = validate_error(resp, ApiErrorId.ERR_WINDOW_INCOMPATIBLE)
    assert err["error_id"] != "ERR_MASS_CAPACITY_EXCEEDED", (
        "window coverage (stage 9) fires even though 100 + 250 > 300"
    )


def test_failed_window_check_persists_no_assignment(api):
    """PRD §2.6: "Every request passes through the same validation pipeline, and
    the stages run in a fixed order: a failure at an earlier stage masks every
    later check, so the response always carries the first applicable rejection."
    PRD §3.3: "The contract's launch-date window must cover the mission's
    window — the contract's `window_open_utc` on or before the mission's
    `window_open_utc`, and the contract's `window_close_utc` on or after the
    mission's `window_close_utc` — else `ERR_WINDOW_INCOMPATIBLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/assignment_with_bad_window_and_mass_overflow_reports_window_error
    """
    mission, port_c, pl_b = _setup_window_and_mass_conflict()
    resp = api_client.create_assignment(
        assignment_payload(mission["id"], pl_b["id"], port_c["id"], mission_version(mission["id"])),
        MOPS,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_INCOMPATIBLE)
    rows, meta = validate_paginated(
        api_client.list_assignments(MOPS, params={"mission_id": mission["id"]})
    )
    assert len(rows) == 1 and meta["total_count"] == 1, (
        "the rejected create leaves the earlier assignment untouched"
    )
    assert get_mission(mission["id"])["committed_mass_kg"] == 100


def _setup_mass_boundary():
    """Mission 300 kg / 10 m3; PL1 150 kg RING_15, PL2 150 kg RING_24,
    PL3 0.001 kg CUBESAT; ports DSP-A (150), DSP-C (150, RING_24), DSP-B (100, CUBESAT)."""
    set_clock()
    customer = create_customer()
    mission = create_mission(mission_name="Transporter-X3", volume_capacity_m3=10.0)
    port_a = create_port(mission["id"])
    port_c = create_port(
        mission["id"], port_code="DSP-C", stack_position=2, max_mass_kg=150,
        supported_interface_classes=["RING_24"],
    )
    port_b = create_port(
        mission["id"], port_code="DSP-B", stack_position=3, max_mass_kg=100,
        supported_interface_classes=["CUBESAT"],
    )
    contract, payloads = create_signed_contract(
        customer["id"],
        [
            payload_entry(payload_name="PL1", mass_kg=150),
            payload_entry(payload_name="PL2", mass_kg=150, interface_class="RING_24"),
            payload_entry(payload_name="PL3", mass_kg=0.001, volume_m3=0.001,
                          interface_class="CUBESAT"),
        ],
    )
    return mission, (port_a, port_c, port_b), payloads


def test_assignment_at_exact_mass_capacity_is_allowed(api):
    """PRD §3.3: "Capacity is judged last, on the TOTAL commitment variant of
    §2.9, with equality permitted. If adding the payload would push the mission's
    `committed_mass_kg` strictly above `mass_capacity_kg`, the create is rejected
    with `ERR_MASS_CAPACITY_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/assignment_at_exact_mass_capacity_allowed_fraction_over_rejected
    """
    mission, (port_a, port_c, _port_b), payloads = _setup_mass_boundary()
    r1 = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[0]["id"], port_a["id"], mission_version(mission["id"])),
        MOPS,
    )
    validate_success(r1, 201)
    r2 = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[1]["id"], port_c["id"], mission_version(mission["id"])),
        MOPS,
    )
    validate_success(r2, 201)
    mission = get_mission(mission["id"])
    assert mission["committed_mass_kg"] == 300, (
        "150 + 150 == 300 is exactly at capacity and must be allowed"
    )


def test_assignment_fraction_over_mass_capacity_is_rejected(api):
    """PRD §3.3: "If adding the payload would push the mission's
    `committed_mass_kg` strictly above `mass_capacity_kg`, the create is rejected
    with `ERR_MASS_CAPACITY_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/assignment_at_exact_mass_capacity_allowed_fraction_over_rejected
    """
    mission, (port_a, port_c, port_b), payloads = _setup_mass_boundary()
    create_assignment(mission["id"], payloads[0]["id"], port_a["id"])
    create_assignment(mission["id"], payloads[1]["id"], port_c["id"])
    resp = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[2]["id"], port_b["id"], mission_version(mission["id"])),
        MOPS,
    )
    validate_error(resp, ApiErrorId.ERR_MASS_CAPACITY_EXCEEDED)
    rows, meta = validate_paginated(
        api_client.list_assignments(MOPS, params={"mission_id": mission["id"]})
    )
    assert len(rows) == 2 and meta["total_count"] == 2, (
        "300.001 > 300 must be rejected; only the two boundary assignments persist"
    )


def test_assign_then_remove_restores_committed_mass_and_volume(api):
    """PRD §2.9: "These fields are recomputed immediately, within the same
    request, whenever the manifest changes: assignment creation, assignment
    confirmation (which moves mass from the provisional-only bucket into the
    firm set), manual or cascaded removal, manifest lock, and scrub."
    PRD §3.3: "Removal releases capacity: the mission's commitment fields are
    recomputed, the payload returns from `MANIFESTED` to `REGISTERED` with a
    version increment"

    Design: Difficulty/compensating_invariant/assign_then_remove_restores_committed_mass_and_volume
    """
    ctx = setup_provisional_assignments(
        port_specs=[{}, {"port_code": "DSP-B", "stack_position": 3, "max_mass_kg": 100,
                         "supported_interface_classes": ["CUBESAT"]}],
        payload_specs=[{}, {"payload_name": "PL2", "mass_kg": 50, "volume_m3": 1.0,
                            "interface_class": "CUBESAT"}],
    )
    resp = api_client.remove_assignment(ctx["assignments"][1]["id"], MOPS, reason_code="SCHEDULE_CHANGE")
    validate_success(resp, 200)
    mission = get_mission(ctx["mission"]["id"])
    assert mission["committed_mass_kg"] == 100, "exactly the pre-assign baseline, no drift"
    assert mission["committed_volume_m3"] == 2.0
    assert mission["firm_mass_kg"] == 0, (
        "A1 PROVISIONAL and A2 REMOVED both stand outside the FIRM set"
    )


def test_remove_bubbles_payload_but_not_contract_while_one_remains(api):
    """PRD §3.3: "Removal releases capacity: the mission's commitment fields are
    recomputed, the payload returns from `MANIFESTED` to `REGISTERED` with a
    version increment, and — when the removed assignment was the contract's last
    live one — the contract falls back from `MANIFESTED` to `SIGNED` with its
    own increment."

    Design: Difficulty/compensating_invariant/assign_then_remove_restores_committed_mass_and_volume
    """
    ctx = setup_provisional_assignments(
        port_specs=[{}, {"port_code": "DSP-B", "stack_position": 3, "max_mass_kg": 100,
                         "supported_interface_classes": ["CUBESAT"]}],
        payload_specs=[{}, {"payload_name": "PL2", "mass_kg": 50, "volume_m3": 1.0,
                            "interface_class": "CUBESAT"}],
    )
    resp = api_client.remove_assignment(ctx["assignments"][1]["id"], MOPS, reason_code="SCHEDULE_CHANGE")
    removed = validate_success(resp, 200)
    assert removed["status"] == "REMOVED"
    payloads = validate_success(
        api_client.list_contract_payloads(ctx["contract"]["id"], MOPS), 200
    )
    assert payloads[1]["status"] == "REGISTERED"
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "MANIFESTED", (
        "PL1 still live, so no contract revert"
    )


def _setup_two_cubesat_locked_mission():
    """Two 1.001 kg CUBESAT payloads, each CONFIRMED on its own port, then the
    manifest locked so both stand INTEGRATED."""
    ctx = setup_confirmed_mission(
        port_specs=[
            {"port_code": "DSP-B", "stack_position": 3, "max_mass_kg": 100,
             "supported_interface_classes": ["CUBESAT"]},
            {"port_code": "DSP-D", "stack_position": 1, "max_mass_kg": 100,
             "supported_interface_classes": ["RING_15", "CUBESAT"]},
        ],
        payload_specs=[
            {"payload_name": "Cube-1", "mass_kg": 1.001, "volume_m3": 0.1,
             "interface_class": "CUBESAT"},
            {"payload_name": "Cube-2", "mass_kg": 1.001, "volume_m3": 0.1,
             "interface_class": "CUBESAT"},
        ],
    )
    ctx["mission"] = lock_manifest(ctx["mission"]["id"])
    for i, assignment in enumerate(ctx["assignments"]):
        ctx["assignments"][i] = get_assignment(assignment["id"])
    return ctx


def test_integration_fee_rounds_per_line_then_sums(api):
    """PRD §3.3: "The per-line integration fee is computed and stored as
    `integration_fee_cents`: the payload's `mass_kg` multiplied by 12,000 cents
    per kilogram, multiplied by the interface factor of its `interface_class` —
    1.0 for `RING_15`, 1.25 for `RING_24`, and 0.8 for `CUBESAT` — then rounded
    half up to a whole cent."
    PRD §3.6: "`integration_revenue_cents` as the sum of the already-rounded
    per-line `integration_fee_cents` values across the assignments that reach
    `INTEGRATED` in this lock"

    Design: Difficulty/combinatorial_formula/integration_fee_round_per_line_sum_vs_sum_round_differ_by_one_cent
    """
    ctx = _setup_two_cubesat_locked_mission()
    for assignment in ctx["assignments"]:
        assert assignment["status"] == "INTEGRATED"
        assert assignment["integration_fee_cents"] == 9610, (
            "round_half_up(1.001 x 12000 x 0.8) = round_half_up(9609.6) = 9610 per line"
        )
    mission = get_mission(ctx["mission"]["id"])
    assert mission["integration_revenue_cents"] == 19220, (
        "round-per-line-then-sum: 9610 + 9610 = 19220"
    )


def test_revenue_estimate_sums_unrounded_then_rounds(api):
    """PRD §2.10: "When the manifest is locked, the mission's
    `integration_revenue_cents` is stored as the sum of those already-rounded
    per-line fees — round per line, then sum — while `revenue_estimate_cents`
    is stored as the sum of the unrounded per-line terms, rounded half up once
    at the end — sum, then round. The two totals legitimately differ by a few
    cents: two CUBESAT lines of 1.001 kg each store 19,220 cents of integration
    revenue against an estimate of 19,219 cents."

    Design: Difficulty/combinatorial_formula/integration_fee_round_per_line_sum_vs_sum_round_differ_by_one_cent
    """
    ctx = _setup_two_cubesat_locked_mission()
    mission = get_mission(ctx["mission"]["id"])
    assert mission["revenue_estimate_cents"] == 19219, (
        "sum-then-round: round_half_up(19219.2) = 19219"
    )
    assert mission["integration_revenue_cents"] == 19220
    assert mission["integration_revenue_cents"] != mission["revenue_estimate_cents"]


def test_assignment_create_response_is_immediately_consistent(api):
    """PRD §2.9: "These fields are recomputed immediately, within the same
    request, whenever the manifest changes"
    PRD §3.3: "The per-line integration fee is computed and stored as
    `integration_fee_cents`: the payload's `mass_kg` multiplied by 12,000 cents
    per kilogram, multiplied by the interface factor of its `interface_class` —
    1.0 for `RING_15`, 1.25 for `RING_24`, and 0.8 for `CUBESAT` — then rounded
    half up to a whole cent."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/writes_visible_immediately_in_same_response_and_read
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    port = create_port(mission["id"])
    contract, payloads = create_signed_contract(customer["id"], [payload_entry()])
    resp = api_client.create_assignment(
        assignment_payload(mission["id"], payloads[0]["id"], port["id"], mission_version(mission["id"])),
        MOPS,
    )
    created = validate_success(resp, 201)
    assert created["status"] == "PROVISIONAL"
    assert created["integration_fee_cents"] == 1_200_000, (
        "100 kg x 12000 x RING_15 factor 1.0"
    )
    assert created["version"] == 1

    reread = validate_success(api_client.get_assignment(created["id"], MOPS), 200)
    assert reread["status"] == created["status"]
    assert reread["integration_fee_cents"] == created["integration_fee_cents"]

    mission = get_mission(mission["id"])
    assert mission["committed_mass_kg"] == 100
    assert mission["committed_volume_m3"] == 2.0
