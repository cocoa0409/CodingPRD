"""Execution economics: provisional vs final allocation variants, the pinned
lead-cost evaluation order, per-line floor-then-remainder rounding, basis
selection, snapshot immutability, and lapse handling at execution.
"""
from test_helpers import (
    ApiErrorId,
    CANONICAL_OFFICES,
    api_client,
    assert_line_gross_invariant,
    assert_weights_sum_to_total,
    execute_settlement,
    get_allocation_line,
    get_settlement,
    list_allocation_lines,
    patch_state_office_payload,
    record_sign_ons,
    setup_executed_world,
    setup_sign_on_open_world,
    validate_error,
    validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]


def _lines_by_state(lines):
    return {line["state_code"]: line for line in lines}


def test_provisional_vs_final_weight_divergence():
    """PRD section 2.7: "The provisional variant runs when a settlement is
    proposed ... over the investigation's `ACTIVE` participations at proposal
    time ... and stores its outputs on the settlement as
    `provisional_distributable_cents` and `provisional_weight_bps_by_state`."
    PRD section 2.7: "The final variant runs only at settlement execution: it
    evaluates the same formulas over the locked sign-on set alone — so states
    that declined or lapsed are excluded and their weight is redistributed
    among the locked states."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_weight_divergence
    """
    world = setup_sign_on_open_world()
    stl_id = world["settlement"]["id"]
    proposed = get_settlement(stl_id)
    # Provisional variant over the four ACTIVE participations (pops 100/300/
    # 400/200, sum 1000): CA 1000 / TX 3000 / NY 4000 / FL 2000 bps.
    assert proposed["provisional_weight_bps_by_state"] == {
        "CA": 1000, "TX": 3000, "NY": 4000, "FL": 2000,
    }
    assert proposed["provisional_distributable_cents"] == 85500000
    record_sign_ons(world)
    executed = execute_settlement(stl_id)
    # Same pool, different inclusion set: distributable identical, weights not.
    assert executed["distributable_cents"] == 85500000
    assert executed["provisional_distributable_cents"] == 85500000
    assert executed["provisional_weight_bps_by_state"]["CA"] == 1000
    lines = _lines_by_state(list_allocation_lines(stl_id))
    assert lines["CA"]["weight_bps"] == 1250, (
        "final variant renormalizes over the three LOCKED sign-ons "
        "(100/300/400 of 800), so CA moves 1000 -> 1250 bps"
    )
    assert lines["TX"]["weight_bps"] == 3750
    assert lines["NY"]["weight_bps"] == 5000
    assert "FL" not in lines


def test_circular_lead_cost_order_pinned():
    """PRD section 3.3: "First, the base is the `monetary_total_cents` minus
    the `restitution_reserve_cents`. Second, the lead-state cost pool is the
    smaller of 25000000 cents and the base multiplied by 500 basis points out
    of 10000, rounded half up to a whole cent — that is, the lead pool is 5
    percent of the base, capped at $250,000. Third, the distributable pool is
    the base minus that lead cost pool."
    PRD section 3.4: "The lead cost pool is split equally among locked lines
    whose offices hold `committee_role` `LEAD`."

    Design: Difficulty/combinatorial_formula/circular_lead_cost_order_pinned
    """
    world = setup_executed_world()
    settlement = world["settlement"]
    # base 90,000,000; lead pool min(25,000,000, round_half_up(4,500,000)).
    assert settlement["lead_cost_cents"] == 4500000
    assert settlement["distributable_cents"] == 85500000
    lines = _lines_by_state(world["lines"])
    assert lines["CA"]["lead_bonus_cents"] == 2250000
    assert lines["TX"]["lead_bonus_cents"] == 2250000
    assert lines["NY"]["lead_bonus_cents"] == 0, (
        "NY holds no LEAD seat and takes no lead bonus"
    )


def test_per_line_floor_then_remainder_cents():
    """PRD section 3.4: "Per-line shares follow a pinned rounding order: first
    each line's `share_cents` is the settlement's `distributable_cents`
    multiplied by the line's `weight_bps` out of 10000, rounded down to a
    whole cent; then the remainder — the distributable pool minus the sum of
    those floors — is dealt out one cent at a time in order of `weight_bps`
    descending, ties broken by `decided_at` ascending, never by id."

    Design: Difficulty/combinatorial_formula/per_line_floor_then_remainder_cents
    """
    world = setup_executed_world(monetary_total_cents=100000007)
    settlement = world["settlement"]
    # base 90,000,007; lead pool round_half_up(4,500,000.35) = 4,500,000.
    assert settlement["distributable_cents"] == 85500007
    lines = _lines_by_state(world["lines"])
    # floors: 10,687,500 / 32,062,502 / 42,750,003 leave 2 cents, dealt in
    # weight_bps descending order: NY (5000) then TX (3750).
    assert lines["CA"]["share_cents"] == 10687500
    assert lines["TX"]["share_cents"] == 32062503
    assert lines["NY"]["share_cents"] == 42750004
    assert sum(l["share_cents"] for l in world["lines"]) == 85500007
    assert lines["CA"]["gross_share_cents"] == 12937500   # + 2,250,000 bonus
    assert lines["TX"]["gross_share_cents"] == 34312503
    assert lines["NY"]["gross_share_cents"] == 42750004
    for line in world["lines"]:
        assert_line_gross_invariant(line)


def test_harm_measure_basis_computes_expected_weights():
    """PRD section 3.4: "Using each office's raw basis value — its
    `population` under a `POPULATION` basis, its `harm_measure_cents` under
    `HARM_MEASURE`, or its `negotiated_shares` entry under `NEGOTIATED`."
    PRD section 3.4: "Each state's `basis_value_snapshot` captures its raw
    basis value at execution time."

    Design: Corner/calculations/harm_measure_basis_computes_expected_weights
    """
    world = setup_executed_world(allocation_basis="HARM_MEASURE")
    lines = _lines_by_state(world["lines"])
    # Locked harms 50/150/200 (sum 400): 1250 / 3750 / 5000 bps.
    assert (lines["CA"]["weight_bps"], lines["TX"]["weight_bps"],
            lines["NY"]["weight_bps"]) == (1250, 3750, 5000)
    assert lines["NY"]["basis_value_snapshot"] == 200, (
        "HARM_MEASURE snapshots harm_measure_cents, not population"
    )
    assert lines["NY"]["share_cents"] == 42750000


def test_negotiated_weight_renormalization_conserves_10000_bps():
    """PRD section 3.4: "each locked state's raw basis value is divided by the
    sum of raw values over the locked set, scaled by 10000, and rounded down
    to a whole basis point; the shortfall between 10000 and the sum of the
    floored weights is then distributed one basis point at a time to the
    largest raw values, breaking ties by sign-on `decided_at` ascending —
    earlier deciders first — and never by id."
    PRD section 2.6: "all allocation weights are carried as integer basis
    points, and the weights of the allocation lines belonging to one
    settlement always sum to exactly 10000 basis points."

    Design: Difficulty/compensating_invariant/negotiated_weight_renormalization_conserves_10000_bps
    """
    world = setup_executed_world(
        allocation_basis="NEGOTIATED",
        negotiated_shares={"CA": 2000, "TX": 3000, "NY": 4000, "FL": 1000},
    )
    lines = _lines_by_state(world["lines"])
    # FL's 1000 negotiated bps leave the pool with its DECLINED decision; the
    # locked set renormalizes over 2000+3000+4000 = 9000: floors 2222/3333/
    # 4444, and the 1-bps shortfall goes to the largest raw value (NY 4000).
    assert lines["CA"]["weight_bps"] == 2222
    assert lines["TX"]["weight_bps"] == 3333
    assert lines["NY"]["weight_bps"] == 4445
    assert "FL" not in lines
    assert_weights_sum_to_total(world["lines"])


def test_basis_snapshot_survives_later_registry_patch():
    """PRD section 3.1: "Updates increment the office's `version` by 1 and
    never retroactively alter allocation snapshots already captured at a
    settlement's execution."
    PRD section 3.4: "Each state's `basis_value_snapshot` captures its raw
    basis value at execution time."

    Design: Corner/calculations/basis_snapshot_survives_later_registry_patch
    """
    world = setup_executed_world()
    ny = world["offices"]["NY"]
    resp = api_client.patch_state_office(
        ny["id"],
        patch_state_office_payload(ny["version"], population=999),
        CHAIR,
    )
    patched = validate_success(resp)
    assert patched["population"] == 999
    assert patched["version"] == ny["version"] + 1
    ny_line = _lines_by_state(world["lines"])["NY"]
    line = get_allocation_line(ny_line["id"])
    assert line["basis_value_snapshot"] == 400, (
        "the execution-time snapshot is immutable against later registry edits"
    )
    assert line["weight_bps"] == 5000


def test_execute_lapses_silent_eligible_state():
    """PRD section 3.4: "Every `sign_ons` entry in `SIGNED` status becomes
    `LOCKED`, and every office holding an `ACTIVE` participation that never
    recorded a decision receives an embedded entry with status `LAPSED` —
    lapsed and declined offices take nothing."

    Design: Corner/endpoints/execute_lapses_silent_eligible_state
    """
    specs = {code: dict(spec) for code, spec in CANONICAL_OFFICES.items()}
    specs["NV"] = {"state_code": "NV", "population": 50,
                   "harm_measure_cents": 25,
                   "appropriation_rule": "PREAPPROPRIATED",
                   "cia_tier": "STANDARD"}
    world = setup_executed_world(
        office_codes=("CA", "TX", "NY", "FL", "NV"),
        lead_codes=("CA", "TX"),
        office_specs=specs,
        decisions={"CA": "SIGNED", "TX": "SIGNED",
                   "NY": "SIGNED", "FL": "SIGNED"},
    )
    settlement = world["settlement"]
    # signed 1000 of 1050 eligible population -> 9524 bps and 4 states: quorum
    # met; NV recorded no decision and is lapsed.
    assert settlement["term_status"] == "EXECUTED"
    assert len(settlement["sign_ons"]) == 5
    by_code = {e["state_code"]: e for e in settlement["sign_ons"]}
    assert by_code["NV"]["status"] == "LAPSED"
    for code in ("CA", "TX", "NY", "FL"):
        assert by_code[code]["status"] == "LOCKED"
    lines = _lines_by_state(world["lines"])
    assert set(lines) == {"CA", "TX", "NY", "FL"}, "a lapsed office takes no line"
    assert (lines["CA"]["weight_bps"], lines["TX"]["weight_bps"],
            lines["NY"]["weight_bps"], lines["FL"]["weight_bps"]
            ) == (1000, 3000, 4000, 2000)


def test_execute_twice_returns_invalid_state():
    """PRD section 3.4: "Execution is the moment of truth, performed by the
    `CommitteeChair` on a settlement in `SIGN_ON_OPEN` while the investigation
    is in `SETTLEMENT_PENDING`."
    PRD section 2.8: "the target resource's own state machine must admit the
    trigger (`ERR_INVALID_STATE`, ...)."

    Design: Corner/state_machines/execute_twice_returns_invalid_state
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    resp = api_client.execute_settlement(stl_id, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    settlement = get_settlement(stl_id)
    assert settlement["term_status"] == "EXECUTED"
    assert len(list_allocation_lines(stl_id)) == 3, (
        "the first execution's allocation lines are untouched by the replay"
    )
