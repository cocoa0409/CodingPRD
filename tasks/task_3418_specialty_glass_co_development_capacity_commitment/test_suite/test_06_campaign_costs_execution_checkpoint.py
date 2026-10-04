"""Campaign cost model, execution timing gates, abort cascade, and the
operations checkpoint sweeps.

Covers the yield learning curve and energy surcharge tiers with the pinned
per-component ceiling (PRD section 3.5), the provisional-vs-final cost
divergence (PRD section 3.6), the start/complete clock gates, and the
checkpoint sweeps for commitment exhaustion and breach (PRD section 3.9).
"""

from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    complete_campaign,
    create_allocation,
    create_campaign,
    create_commissioned_tank,
    create_composition,
    create_program_with_nda,
    create_qual_cycle,
    create_secured_commitment,
    create_qualified_composition,
    factories,
    fulfill_allocation,
    record_production,
    record_qual_result,
    begin_testing,
    run_checkpoint,
    set_clock,
    setup_running_chain_with_allocation,
    setup_running_supply_chain,
    setup_supply_chain,
    setup_supply_chain_with_allocation,
    shift_iso,
    start_campaign,
    release_allocation,
    validate_created,
    validate_error,
    validate_success,
    get_success_data,
)

MANAGER = TEST_USERS["program_manager_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _setup_to_commissioned_tank():
    """The shared bootstrap minus the campaign: maker, program past NDA,
    QUALIFIED composition, SECURED commitment, COMMISSIONED tank."""
    chain = create_program_with_nda()
    qual = create_qualified_composition(chain.program, chain.maker)
    commitment = create_secured_commitment(chain.program, chain.maker)
    tank = create_commissioned_tank(commitment, 1000)
    return chain, qual, tank


def test_yield_step_boundaries_20000_and_80000():
    """PRD section 3.5: "When `planned_units` is below 20000 units
    (CONST.YIELD_STEP1_MAX_UNITS) the provisional yield rate is 0.62
    (CONST.YIELD_STEP1_RATE); at 20000 units or more but below 80000 units
    (CONST.YIELD_STEP2_MAX_UNITS) it is 0.78 (CONST.YIELD_STEP2_RATE); and at
    80000 units or more it is 0.90 (CONST.YIELD_STEP3_RATE)." Step thresholds
    are inclusive at the lower bound of the next step: 20000 takes 0.78 and
    80000 takes 0.90.

    Design: Corner/calculations/yield_step_boundaries_20000_and_80000
    """
    _, qual, tank = _setup_to_commissioned_tank()
    campaign_a = validate_created(
        api_client.create_campaign(
            factories.create_campaign_payload(
                tank["id"],
                qual.composition["id"],
                start_date="2028-03-01T00:00:00Z",
                end_date="2029-03-01T00:00:00Z",
                planned_units=20000,
            ),
            PLANNER,
        )
    )
    # 0.78 step; energy 120 (20000 < 50000); ceil(970 / 0.78) = 1244.
    assert campaign_a["expected_good_units"] == 15600  # floor(20000 * 0.78)
    assert campaign_a["provisional_unit_cost_cents"] == 1244

    campaign_b = validate_created(
        api_client.create_campaign(
            factories.create_campaign_payload(
                tank["id"],
                qual.composition["id"],
                start_date="2029-03-01T00:00:00Z",
                end_date="2030-03-01T00:00:00Z",
                planned_units=80000,
            ),
            PLANNER,
        )
    )
    # 0.90 step; energy 60 (80000 >= 50000); same-composition adjacency pays
    # no changeover; ceil(910 / 0.90) = 1012.
    assert campaign_b["expected_good_units"] == 72000  # floor(80000 * 0.90)
    assert campaign_b["provisional_unit_cost_cents"] == 1012


def test_energy_surcharge_tier_boundary_50000():
    """PRD section 3.5: "The energy surcharge per unit is re-selected on the
    basis units: 60 cents (CONST.ENERGY_SURCHARGE_T2_CENTS) when the basis
    units are at least 50000 (CONST.ENERGY_SURCHARGE_T1_MAX_UNITS), and 120
    cents (CONST.ENERGY_SURCHARGE_T1_CENTS) below that." At 49999 planned
    units the surcharge is 120; at exactly 50000 it drops to 60.

    Design: Corner/calculations/energy_surcharge_tier_boundary_50000
    """
    _, qual, tank = _setup_to_commissioned_tank()
    campaign_a = validate_created(
        api_client.create_campaign(
            factories.create_campaign_payload(
                tank["id"],
                qual.composition["id"],
                start_date="2028-03-01T00:00:00Z",
                end_date="2029-03-01T00:00:00Z",
                planned_units=49999,
            ),
            PLANNER,
        )
    )
    # 0.78 step; energy 120; ceil(970 / 0.78) = 1244.
    assert campaign_a["expected_good_units"] == 38999  # floor(49999 * 0.78)
    assert campaign_a["provisional_unit_cost_cents"] == 1244

    campaign_b = validate_created(
        api_client.create_campaign(
            factories.create_campaign_payload(
                tank["id"],
                qual.composition["id"],
                start_date="2029-03-01T00:00:00Z",
                end_date="2030-03-01T00:00:00Z",
                planned_units=50000,
            ),
            PLANNER,
        )
    )
    # 0.78 step; energy 60; ceil(910 / 0.78) = 1167.
    assert campaign_b["expected_good_units"] == 39000  # floor(50000 * 0.78)
    assert campaign_b["provisional_unit_cost_cents"] == 1167


def test_campaign_cost_provisional_vs_final_diverge():
    """PRD section 3.5: "The unit cost in integer cents is then the sum of two
    separately ceilinged components". PRD section 3.6: "computes
    `final_unit_cost_cents` per the final variant of the cost model in section
    3.5 — cumulative good units as the basis, realized yield as the yield
    basis, and the energy tier re-selected on the actual good units." For the
    identical campaign the provisional variant yields 1244 cents per unit
    (planned 40000 at step yield 0.78) while the final variant yields 1358 on a
    realized yield of 30000/42000 = 0.714286.

    Design: Difficulty/dual_variant_calc/campaign_cost_provisional_vs_final_diverge
    """
    chain = setup_supply_chain(planned_units=40000)
    # Provisional: energy 120 (40000 < 50000); ceil(970 / 0.78) = 1244.
    assert chain.campaign["expected_good_units"] == 31200  # floor(40000 * 0.78)
    assert chain.campaign["provisional_unit_cost_cents"] == 1244

    chain.campaign = start_campaign(chain.campaign)
    record_production(chain.campaign, good_units=30000, scrap_units=12000)
    done = complete_campaign(chain.campaign)
    assert done["status"] == "COMPLETED"
    assert done["realized_yield"] == pytest.approx(0.714286)  # 30000/42000, 6dp
    # Final: energy tier re-selected on 30000 good units stays at 120;
    # ceil(970 / 0.714286) = 1358; no changeover (no prior campaign).
    assert done["final_unit_cost_cents"] == 1358
    assert done["provisional_unit_cost_cents"] != done["final_unit_cost_cents"]


def test_campaign_cost_multifactor_changeover_interaction():
    """PRD section 3.5: "if there is no such prior campaign, or the prior
    campaign melts the same `composition_id`, the changeover total is zero;
    otherwise it is 4000 cents per campaign day
    (CONST.CHANGEOVER_AMORTIZATION_CENTS_PER_DAY) multiplied by the
    campaign-day count." A 60000-unit successor melting a different
    composition pays the energy tier-2 surcharge and the changeover
    amortization: ceil((850 * 1.0 + 60) / 0.78) + ceil(4000 * 365 / 60000) =
    1167 + 25 = 1192.

    Design: Difficulty/combinatorial_formula/campaign_cost_multifactor_changeover_interaction
    """
    chain = setup_supply_chain()  # campaign A on GX-100: [2028-03-01, 2029-03-01)
    cx2 = create_composition(chain.program, composition_code="GX-300")
    cycle2 = create_qual_cycle(cx2, test_plan_ref="TP-2")
    cycle2 = begin_testing(cycle2, chain.maker["id"])
    record_qual_result(cycle2, chain.maker["id"], "PASSED")

    campaign_b = validate_created(
        api_client.create_campaign(
            factories.create_campaign_payload(
                chain.tank["id"],
                cx2["id"],
                start_date="2029-04-15T00:00:00Z",
                end_date="2030-04-15T00:00:00Z",
                planned_units=60000,
            ),
            PLANNER,
        )
    )
    # 0.78 step (20000 <= 60000 < 80000); energy 60 (60000 >= 50000).
    assert campaign_b["expected_good_units"] == 46800  # floor(60000 * 0.78)
    assert campaign_b["provisional_unit_cost_cents"] == 1192


def test_campaign_complete_before_end_returns_campaign_not_ended():
    """PRD section 3.6: "Once the logical clock has reached the campaign's
    `end_date` — earlier attempts fail with `ERR_CAMPAIGN_NOT_ENDED`" — at
    2028-06-01 the window [2028-03-01, 2029-03-01) has not closed.

    Design: Corner/state_machines/campaign_complete_before_end_returns_campaign_not_ended
    """
    chain = setup_running_supply_chain()
    set_clock("2028-06-01T00:00:00Z")
    resp = api_client.complete_campaign(chain.campaign["id"], headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ENDED)
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["status"] == "RUNNING"


def test_campaign_start_requires_composition_qualified():
    """PRD section 3.6: "The composition must by then be `QUALIFIED` or
    `LOCKED` — scheduling accepted `TUNED`, but the melt itself does not —
    failing otherwise with `ERR_COMPOSITION_NOT_QUALIFIED`". The identical
    start call fails while the composition is TUNED and succeeds once the
    recorded PASSED result qualifies it.

    Design: Difficulty/cross_entity_state_dependency/campaign_start_requires_composition_qualified
    """
    chain = setup_supply_chain(composition_maturity="TUNED")
    set_clock("2028-03-01T00:00:00Z")
    resp = api_client.start_campaign(chain.campaign["id"], headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_COMPOSITION_NOT_QUALIFIED)

    record_qual_result(chain.cycle, chain.maker["id"], "PASSED")
    started = validate_success(api_client.start_campaign(chain.campaign["id"], headers=PLANNER))
    assert started["status"] == "RUNNING"


def test_campaign_abort_releases_allocations_and_marks_breach():
    """PRD section 3.6: "every `RESERVED` allocation of the campaign is
    `RELEASED` with the campaign's `unallocated_units` increased by the
    released units; each still-`SECURED` commitment referenced by a released
    allocation has its `supply_coverage` recomputed and drops into
    `BREACH_WATCH` — deadline set to the clock plus 90 days
    (CONST.BREACH_GRACE_DAYS) — when coverage falls below 1.0
    (CONST.SUPPLY_COVERAGE_MIN); and each maker behind a newly watched
    commitment is demoted one standing step."

    Design: Corner/state_machines/campaign_abort_releases_allocations_and_marks_breach
    """
    chain = setup_running_chain_with_allocation(
        alloc_units=5000, standing_tier="STRATEGIC"
    )
    aborted = validate_success(api_client.abort_campaign(chain.campaign["id"], headers=PLANNER))
    assert aborted["status"] == "ABORTED"

    allocation = get_success_data(api_client.get_allocation(chain.allocation["id"], PLANNER))
    assert allocation["status"] == "RELEASED"
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 6200  # 1200 + 5000 restored
    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], PLANNER))
    assert commitment["status"] == "BREACH_WATCH"  # supply_coverage fell to 0
    maker = get_success_data(api_client.get_device_maker(chain.maker["id"], PLANNER))
    assert maker["standing_tier"] == "STANDARD"  # demoted one step from STRATEGIC


def test_commitment_exhausted_at_checkpoint():
    """PRD section 3.9: "It marks every commitment in `SECURED` or
    `BREACH_WATCH` whose `fulfilled_units` have reached its `committed_units`
    as `EXHAUSTED`." and "The response reports the sweep's work as counts:
    `campaigns_completed`, `campaigns_cancelled`, `licenses_expired`,
    `commitments_exhausted`, and `commitments_breached`."

    Design: Corner/state_machines/commitment_exhausted_at_checkpoint
    """
    chain = setup_running_supply_chain(
        committed_units=1000, required_units=1000, prepayment_cents=1000000
    )
    allocation = create_allocation(chain.commitment, chain.campaign, 1000)
    fulfill_allocation(allocation)
    result = run_checkpoint()
    assert result["commitments_exhausted"] == 1
    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], MANAGER))
    assert commitment["fulfilled_units"] == 1000
    assert commitment["status"] == "EXHAUSTED"


def test_breach_watch_flips_to_breached_after_grace():
    """PRD section 3.4: "the commitment moves from `SECURED` to
    `BREACH_WATCH`, its `breach_deadline` is set to the current logical clock
    plus 90 days (CONST.BREACH_GRACE_DAYS)". PRD section 3.9: "And it flips
    every commitment still in `BREACH_WATCH` whose `breach_deadline` the clock
    has passed to `BREACHED`." Releasing the only allocation at 2028-03-01 sets
    the deadline to 2028-05-30; a checkpoint at 2028-05-31 breaches it.

    Design: Corner/state_machines/breach_watch_flips_to_breached_after_grace
    """
    chain = setup_supply_chain_with_allocation(alloc_units=5000)
    set_clock("2028-03-01T00:00:00Z")
    release_allocation(chain.allocation)
    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], MANAGER))
    assert commitment["status"] == "BREACH_WATCH"
    expected_deadline = shift_iso("2028-03-01T00:00:00Z", days=90)
    assert expected_deadline == "2028-05-30T00:00:00Z"
    assert _parse(commitment["breach_deadline"]) == _parse(expected_deadline)

    set_clock("2028-05-31T00:00:00Z")
    result = run_checkpoint()
    assert result["commitments_breached"] == 1
    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], MANAGER))
    assert commitment["status"] == "BREACHED"
