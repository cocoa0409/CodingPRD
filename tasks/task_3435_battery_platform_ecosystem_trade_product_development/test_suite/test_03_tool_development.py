"""Tool development: stage machine, research gates, launch gates, runtime math."""
from test_helpers import (
    ApiErrorId,
    adopt_standard_research,
    create_certified_pack,
    create_launch_ready_tool,
    create_listing,
    create_pack,
    create_partner,
    create_platform,
    create_tool,
    get_listing,
    get_tool,
    issue_bulletin,  # noqa: F401
    set_clock,
    stage_tool_to_engineering_validation,
    submit_insight,
    adopt_insight,
    submit_pack,
    transition_tool,
    activate_listing,
    validate_error,
    validate_success,
)


def _setup_launch_gated_tool():
    """Platform, a pack stuck at SUBMITTED, and a launch-ready tool (window
    [1,2], not corded) staged to ENGINEERING_VALIDATION."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-GATE", pack_generation=1)
    submit_pack(pk["id"])
    tm = create_launch_ready_tool(
        pf["id"], model_code="T-GATE", trade="HVAC", tier="PROFESSIONAL",
        avg_power_draw_w=300, min_pack_generation=1, max_pack_generation=2,
        replacement_price_cents=20000, warranty_days=360, free_replacement_days=60,
        torque_min_nm=5, torque_max_nm=120,
    )
    return pf, pk, tm


def test_tool_launch_blocked_while_pack_not_certified(api, product_engineer_headers):
    """PRD §3.3: "the REGULATORY compatibility set must be non-empty, i.e.
    `regulatory_compatible_pack_count` at least 1 (`ERR_CERTIFICATION_REQUIRED`)"

    Design: Difficulty/cross_entity_state_dependency/tool_launch_gated_by_pack_certification_state
    """
    pf, pk, tm = _setup_launch_gated_tool()
    version = get_tool(tm["id"])["version"]
    resp = api.transition_tool_model(
        tm["id"], {"to_stage": "LAUNCHED", "expected_tool_model_version": version},
        product_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
    assert get_tool(tm["id"])["stage"] == "ENGINEERING_VALIDATION"


def test_tool_launch_succeeds_after_pack_certified_with_same_version(api, product_engineer_headers):
    """PRD §3.3: "the REGULATORY compatibility set must be non-empty, i.e.
    `regulatory_compatible_pack_count` at least 1 (`ERR_CERTIFICATION_REQUIRED`)"
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by exactly 1 on every mutation of that resource"

    Design: Difficulty/cross_entity_state_dependency/tool_launch_gated_by_pack_certification_state
    """
    from test_helpers import decide_pack
    pf, pk, tm = _setup_launch_gated_tool()
    version = get_tool(tm["id"])["version"]
    resp = api.transition_tool_model(
        tm["id"], {"to_stage": "LAUNCHED", "expected_tool_model_version": version},
        product_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
    # The rejected attempt mutated nothing, so the same OCC version still works.
    decide_pack(pk["id"], "CERTIFIED")
    launched = transition_tool(tm["id"], "LAUNCHED", expected_version=version)
    assert launched["stage"] == "LAUNCHED"
    tool = get_tool(tm["id"])
    assert tool["regulatory_compatible_pack_count"] == 1


def _setup_runtime_tools():
    """Platform with three CERTIFIED 100 Wh packs (gen 1/2/3) and two
    corded-conversion tools (500 W) staged to ENGINEERING_VALIDATION:
    tool A window [1,3] target 11.0; tool B window [3,3] target 12.1."""
    set_clock()
    pf = create_platform(code="MX18")
    for gen in (1, 2, 3):
        create_certified_pack(pf["id"], sku=f"R-G{gen}", pack_generation=gen,
                              rated_capacity_wh=100, max_charge_rate_w=200)
    ta = create_launch_ready_tool(
        pf["id"], model_code="T-A", trade="MASONRY", category="SAW", tier="TRADE_SPECIALIST",
        corded_conversion=True, avg_power_draw_w=500, runtime_target_min=11.0,
        min_pack_generation=1, max_pack_generation=3,
        replacement_price_cents=40000, warranty_days=360, free_replacement_days=60,
        torque_min_nm=5, torque_max_nm=300,
    )
    tb = create_launch_ready_tool(
        pf["id"], model_code="T-B", trade="MASONRY", category="SAW", tier="TRADE_SPECIALIST",
        corded_conversion=True, avg_power_draw_w=500, runtime_target_min=12.1,
        min_pack_generation=3, max_pack_generation=3,
        replacement_price_cents=40000, warranty_days=360, free_replacement_days=60,
        torque_min_nm=5, torque_max_nm=300,
    )
    return pf, ta, tb


def test_runtime_ladder_best_runtime_drives_launch_success(api):
    """PRD §3.3: "first compute the generation gap as the pack's
    `pack_generation` minus the tool's `min_pack_generation` (never negative for
    eligible packs); then cap the gap at 4 before scaling — each generation step
    subtracts 0.05 of efficiency, so the derate is 0.05 times the smaller of the
    gap and 4; then floor the resulting efficiency at 0.8"
    PRD §3.3: "a corded-conversion tool must show `best_runtime_min` of at least
    `runtime_target_min` (`ERR_RUNTIME_TARGET_UNMET`)"

    Note: under the PRD formula the gap is relative to the tool's own
    min_pack_generation, so the lowest-generation pack in any window derates to
    gap 0. Tool A's REGULATORY set spans gaps 0/1/2 (12.0/11.4/10.8 minutes);
    the observable best_runtime_min is 12.0 (100 Wh x 1.0 / 500 W x 60).

    Design: Difficulty/combinatorial_formula/runtime_estimate_generation_gap_floor_and_launch_gate
    """
    pf, ta, tb = _setup_runtime_tools()
    tool_a = get_tool(ta["id"])
    assert tool_a["best_runtime_min"] == 12.0
    launched = transition_tool(ta["id"], "LAUNCHED")
    assert launched["stage"] == "LAUNCHED"


def test_runtime_target_unmet_when_best_runtime_below_target(api, product_engineer_headers):
    """PRD §3.3: "a corded-conversion tool must show `best_runtime_min` of at
    least `runtime_target_min` (`ERR_RUNTIME_TARGET_UNMET`)"
    PRD §3.3: "`best_runtime_min` is the maximum of this estimate across the
    REGULATORY set and is null when the set is empty."

    Note: tool B's window [3,3] admits only the gen-3 pack at gap 0 relative to
    its own min_pack_generation, so its best_runtime_min is 12.0; a target of
    12.1 therefore exceeds the best the packs can deliver and the launch is
    rejected.

    Design: Difficulty/combinatorial_formula/runtime_estimate_generation_gap_floor_and_launch_gate
    """
    pf, ta, tb = _setup_runtime_tools()
    tool_b = get_tool(tb["id"])
    assert tool_b["best_runtime_min"] == 12.0
    version = tool_b["version"]
    resp = api.transition_tool_model(
        tb["id"], {"to_stage": "LAUNCHED", "expected_tool_model_version": version},
        product_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RUNTIME_TARGET_UNMET)
    assert get_tool(tb["id"])["stage"] == "ENGINEERING_VALIDATION"


def test_insight_decide_twice_returns_invalid_state(api, product_engineer_headers):
    """PRD §3.3: "Both outcomes are terminal for the insight."
    PRD §3.3: "On `ADOPTED`, the linked tool's adopted counts are recomputed —
    `adopted_field_research_count` for adopted `FIELD_RESEARCH` insights,
    `adopted_jobsite_observation_count` for adopted `JOBSITE_OBSERVATION` ones"

    Design: Corner/state_machines/insight_decide_twice_returns_invalid_state
    """
    set_clock()
    pf = create_platform(code="MX18")
    tm = create_tool(pf["id"], model_code="T-IDEM")
    i1 = submit_insight(tm["id"], "FIELD_RESEARCH", severity="LOW", summary="fr")
    adopt_insight(i1["id"])
    resp = api.decide_insight(i1["id"], {"decision": "REJECTED"}, product_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    tool = get_tool(tm["id"])
    assert tool["adopted_field_research_count"] == 1


def test_tool_skip_stage_transition_rejected(api, product_engineer_headers):
    """PRD §3.3: "Stage-skipping targets and transitions out of `DISCONTINUED`
    are rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/tool_skip_stage_transition_rejected
    """
    set_clock()
    pf = create_platform(code="MX18")
    tm = create_tool(pf["id"], model_code="T-IDEM")
    resp = api.transition_tool_model(
        tm["id"], {"to_stage": "LAUNCHED", "expected_tool_model_version": tm["version"]},
        product_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    tool = get_tool(tm["id"])
    assert tool["stage"] == "CONCEPT"
    assert tool["version"] == 1, "a rejected transition consumes no version"


def test_tool_revert_loop_preserves_adopted_insight_counts(api):
    """PRD §3.3: "An engineering revert edge `ENGINEERING_VALIDATION` →
    `PROTOTYPE` exists for rework; it does NOT reset the adopted insight counts,
    so looping back and re-entering `ENGINEERING_VALIDATION` requires no new
    insights."

    Design: Corner/state_machines/tool_revert_loop_preserves_adopted_insight_counts
    """
    set_clock()
    pf = create_platform(code="MX18")
    tm = create_tool(pf["id"], model_code="T-IDEM")
    adopt_standard_research(tm["id"])
    stage_tool_to_engineering_validation(tm["id"])
    reverted = transition_tool(tm["id"], "PROTOTYPE")
    assert reverted["stage"] == "PROTOTYPE"
    tool = get_tool(tm["id"])
    assert tool["adopted_field_research_count"] == 2
    assert tool["adopted_jobsite_observation_count"] == 1
    reentered = transition_tool(tm["id"], "ENGINEERING_VALIDATION")
    assert reentered["stage"] == "ENGINEERING_VALIDATION"


def test_tool_discontinue_cascades_to_active_listings(api):
    """PRD §3.3: "Discontinuing a `LAUNCHED` tool additionally ends every
    `ACTIVE` distribution listing referencing it."

    Design: Corner/state_machines/tool_discontinue_cascades_to_active_listings
    """
    set_clock()
    pf = create_platform(code="MX18")
    create_certified_pack(pf["id"], sku="P-LST", pack_generation=1)
    tm = create_launch_ready_tool(pf["id"], model_code="T-IDEM", min_pack_generation=1,
                                  max_pack_generation=1)
    transition_tool(tm["id"], "LAUNCHED")
    partner = create_partner(name="Midwest Industrial Supply")
    listing = create_listing(partner, tool_model_id=tm["id"], wholesale_price_cents=15000,
                             allocation_qty=30)
    activate_listing(listing["id"], partner["id"])
    assert get_listing(listing["id"])["status"] == "ACTIVE"
    discontinued = transition_tool(tm["id"], "DISCONTINUED")
    assert discontinued["stage"] == "DISCONTINUED"
    assert get_listing(listing["id"])["status"] == "ENDED"
