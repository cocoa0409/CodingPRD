"""PRD §3.2: the hot-market capacity commitment rule and its two variants."""
import pytest

from test_helpers import validate_success
from test_helpers.fixtures import (
    PLANNER,
    create_design,
    create_licensor,
    create_run,
    set_clock,
)


def _approved_run(api, **run_overrides):
    licensor = create_licensor(api, name="NBL Hot Market", royalty_rate_pct=0.1)
    design = create_design(api, licensor, garment_sku="JERSEY")
    return create_run(api, licensor, design, **run_overrides)


def test_first_run_of_a_pair_writes_the_provisional_commitment(api):
    """PRD §3.2: "a `LOCAL` run with 1000 units of projected demand, a quarter
    probability and two hours to the outcome writes 375 units as the provisional
    first run of its pair"
    PRD §3.2: "The first run created for a given `team_code` and `trigger_type`
    pair is the provisional variant, and it multiplies before rounding: its
    commitment is the projected demand times the floored probability times the
    hour factor, rounded up to the next whole unit."

    Design: Difficulty/dual_variant_calc/hot_market_commitment_first_run_vs_later_run
    """
    set_clock(api)
    run = _approved_run(
        api,
        team_code="ATL",
        trigger_type="CHAMPIONSHIP_WIN",
        event_outcome="WIN_FAVORED_TEAM",
        expected_demand_qty=1000,
        unit_cost_cents=900,
        win_probability_pct=0.25,
        outcome_at="2026-09-01T02:00:00Z",
    )
    assert run["capacity_commitment_units"] == 375
    assert run["status"] == "PARALLEL_HOLD"


def test_second_run_of_a_pair_writes_the_superseding_commitment(api):
    """PRD §3.2: "and would write 275 units as a later committed-final run of the
    same pair, because the provisional run is multiplied by the 1.5 hour factor
    while the later run trades that multiplier for a flat 25-unit residual"
    PRD §3.2: "The second and every later run created for that same pair is the
    committed-final variant, and it drops the hour factor entirely — the demand
    is multiplied by the floored probability, rounded down to the whole unit,
    and then the tier residual is added: 25 units for a `LOCAL` run"

    Design: Difficulty/dual_variant_calc/hot_market_commitment_first_run_vs_later_run
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Hot Market 2", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="ATL", garment_sku="JERSEY")

    first = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "CHAMPIONSHIP_WIN",
                "event_outcome": "WIN_FAVORED_TEAM", "expected_demand_qty": 1000,
                "unit_cost_cents": 900, "win_probability_pct": 0.25,
                "outcome_at": "2026-09-01T02:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "CHAMPIONSHIP_WIN",
                "event_outcome": "WIN_UNDERDOG_TEAM", "expected_demand_qty": 1000,
                "unit_cost_cents": 900, "win_probability_pct": 0.25,
                "outcome_at": "2026-09-01T02:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )

    assert first["capacity_commitment_units"] == 375
    assert second["capacity_commitment_units"] == 275
    assert first["status"] == "PARALLEL_HOLD"
    assert second["status"] == "PARALLEL_HOLD"


def test_tier_boundary_is_inclusive_at_regional_demand(api):
    """PRD §3.2: "Tier selection is inclusive at each lower edge, and the tier a
    run lands in is recorded as one of three exact values: `MAJOR_MARKET`,
    `REGIONAL` or `LOCAL`. A projected demand of at least 100000 units places the
    run in `MAJOR_MARKET`. Below that, a projected demand of at least 25000 units
    places it in `REGIONAL`. Anything lower places it in `LOCAL`."
    PRD §3.2: "The second and every later run created for that same pair is the
    committed-final variant, and it drops the hour factor entirely — the demand
    is multiplied by the floored probability, rounded down to the whole unit,
    and then the tier residual is added: 25 units for a `LOCAL` run, 50 units for
    a `REGIONAL` run, and no residual at all for a `MAJOR_MARKET` run"

    Design: Difficulty/combinatorial_formula/hot_market_hour_band_and_tier_residual
    """
    set_clock(api)
    # One unit apart straddles the inclusive regional edge, and the pair also
    # straddles the two variants: the first run of the group is the provisional
    # one, the second the committed-final one that adds its tier residual.
    licensor = create_licensor(api, name="NBL Hot Market 3", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="ATL", garment_sku="JERSEY")

    below_edge = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "MILESTONE",
                "event_outcome": "NO_OUTCOME", "expected_demand_qty": 24999,
                "unit_cost_cents": 900, "win_probability_pct": 0.5,
                "outcome_at": "2026-09-01T02:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    run = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "MILESTONE",
                "event_outcome": "NO_OUTCOME", "expected_demand_qty": 25000,
                "unit_cost_cents": 900, "win_probability_pct": 0.5,
                "outcome_at": "2026-09-01T01:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    # 24999 is LOCAL and provisional: ceil(24999 * 0.5 * 1.5) = 18750.
    assert below_edge["capacity_commitment_units"] == 18750
    # 25000 is REGIONAL and committed-final: floor(25000 * 0.5) + 50 = 12550.
    assert run["capacity_commitment_units"] == 12550


def test_one_unit_below_the_regional_edge_lands_in_local(api):
    """PRD §3.2: "Anything lower places it in `LOCAL`."
    PRD §3.2: "When 6 hours or fewer remain but more than 1 hour remains, the
    factor is 1.5."

    Design: Difficulty/combinatorial_formula/hot_market_hour_band_and_tier_residual
    """
    set_clock(api)
    run = _approved_run(
        api,
        team_code="ATL",
        trigger_type="MILESTONE",
        event_outcome="NO_OUTCOME",
        expected_demand_qty=24999,
        unit_cost_cents=900,
        win_probability_pct=0.5,
        outcome_at="2026-09-01T02:00:00Z",
    )
    assert run["capacity_commitment_units"] == 18750


def test_regional_tier_boundary_on_an_inclusive_25000(api):
    """PRD §3.2: "a projected demand of at least 25000 units places it in
    `REGIONAL`"
    PRD §3.2: "and then the tier residual is added: 25 units for a `LOCAL` run,
    50 units for a `REGIONAL` run, and no residual at all for a `MAJOR_MARKET`
    run"

    Design: Corner/calculations/hot_market_tier_boundary_sits_on_inclusive_25000
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor N", royalty_rate_pct=0.1,
                               minimum_guarantee_cents=500000)
    design = create_design(api, licensor, team_code="ATL", garment_sku="JERSEY")

    # The tier residual is added only on the committed-final variant, so the
    # group is seeded first and both boundary runs are later runs of the pair,
    # which isolates the residual from the variant.
    validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "STANDARD",
                "expected_demand_qty": 1000, "unit_cost_cents": 900,
                "win_probability_pct": 0.5, "outcome_at": "2026-09-01T02:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    at_edge = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "STANDARD",
                "expected_demand_qty": 25000, "unit_cost_cents": 900,
                "win_probability_pct": 0.5, "outcome_at": "2026-09-01T01:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    below_edge = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "STANDARD",
                "expected_demand_qty": 24999, "unit_cost_cents": 900,
                "win_probability_pct": 0.5, "outcome_at": "2026-09-01T01:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )

    # 25000 lands in REGIONAL: floor(25000 * 0.5) + 50 = 12550.
    assert at_edge["capacity_commitment_units"] == 12550
    # One unit lower drops to LOCAL: floor(24999 * 0.5) + 25 = 12524.
    assert below_edge["capacity_commitment_units"] == 12524
    assert at_edge["capacity_commitment_units"] != below_edge["capacity_commitment_units"]


def test_zero_probability_is_lifted_to_the_floor(api):
    """PRD §3.2: "The probability is then floored: the working value is the
    greater of the supplied `win_probability_pct` and 0.05, so a run the planner
    believes will not happen is still capitalised as though it had a one-in-twenty
    chance."

    Design: Corner/cross_cutting_complexity_layers/probability_floor_lifts_a_zero_probability_run
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor AN", royalty_rate_pct=0.1,
                               minimum_guarantee_cents=500000)
    design = create_design(api, licensor, team_code="ATL", garment_sku="JERSEY")

    zero = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "MILESTONE",
                "event_outcome": "NO_OUTCOME", "expected_demand_qty": 1000,
                "unit_cost_cents": 900, "win_probability_pct": 0,
                "outcome_at": "2026-09-01T02:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    above = validate_success(
        api.create_production_order(
            {
                "licensor_id": licensor["id"], "design_id": design["id"],
                "team_code": "ATL", "trigger_type": "MILESTONE",
                "event_outcome": "NO_OUTCOME", "expected_demand_qty": 1000,
                "unit_cost_cents": 900, "win_probability_pct": 0.06,
                "outcome_at": "2026-09-01T02:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )

    assert zero["capacity_commitment_units"] == 75
    assert above["capacity_commitment_units"] == 85


@pytest.mark.parametrize(
    "hours_remaining,outcome_at,expected",
    [
        (8, "2026-09-01T08:00:00Z", 500),    # more than 6 hours -> factor 1.0
        (3, "2026-09-01T03:00:00Z", 750),    # more than 1, at most 6 -> 1.5
        (1, "2026-09-01T01:00:00Z", 1000),   # an hour or less -> 2.0
    ],
)
def test_hour_band_scales_the_provisional_commitment(api, hours_remaining,
                                                     outcome_at, expected):
    """PRD §3.2: "When more than 6 hours remain, the hour factor is 1.0 and the
    run is treated as unhurried. When 6 hours or fewer remain but more than 1
    hour remains, the factor is 1.5. When an hour or less remains — or the
    outcome instant has already passed and the remaining hours are zero or
    negative — the factor is 2.0, the same-hour rush rate."

    Design: Difficulty/combinatorial_formula/hot_market_hour_band_and_tier_residual
    """
    set_clock(api)
    run = _approved_run(
        api,
        team_code="ATL",
        trigger_type="CHAMPIONSHIP_WIN",
        event_outcome="WIN_FAVORED_TEAM",
        expected_demand_qty=1000,
        unit_cost_cents=900,
        win_probability_pct=0.5,
        outcome_at=outcome_at,
    )
    assert run["capacity_commitment_units"] == expected