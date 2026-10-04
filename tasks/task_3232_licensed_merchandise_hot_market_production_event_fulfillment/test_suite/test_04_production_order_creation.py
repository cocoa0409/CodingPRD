"""Opening a production run: its initial surface, required fields and listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    PLANNER,
    author_layers,
    create_design,
    create_licensor,
    create_run,
    get_run,
    set_clock,
)


def test_new_run_starts_with_empty_unit_ledgers_and_parallel_hold(api):
    """PRD §3.2: "`layer_ids` starts empty and later lists the ids of the run's
    print layers in submission order; `base_units_printed`,
    `accessory_units_printed`, `committed_inventory_cents`,
    `rush_delivery_points`, `write_down_inventory_cents`, `destroyed_units` and
    `donated_units` all start at 0; and `committed_at`, `retired_at` and
    `retire_reason` all start null."
    PRD §3.2: "Creation writes the run's whole initial surface. `status` is
    `PARALLEL_HOLD`"

    Design: Corner/entities/production_order_computed_unit_ledgers_start_at_zero
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor F", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="PHI", garment_sku="CAP")

    run = create_run(api, licensor, design)

    assert run["base_units_printed"] == 0
    assert run["accessory_units_printed"] == 0
    assert run["layer_ids"] == []
    assert run["committed_inventory_cents"] == 0
    assert run["rush_delivery_points"] == 0
    assert run["write_down_inventory_cents"] == 0
    assert run["destroyed_units"] == 0
    assert run["donated_units"] == 0
    assert run["status"] == "PARALLEL_HOLD"
    assert run["committed_at"] is None
    assert run["retired_at"] is None
    assert run["retire_reason"] is None


def test_new_run_holds_parallel_inventory_and_pins_the_design_version(api):
    """PRD §3.2: "`retired_design_version` is pinned to the design's current
    `approved_version`, which is what will later let the system detect that a run
    is printing artwork the licensor has since changed;
    `observed_current_design_version` is set to the design's current `version`;
    `hold_allocation_cents` holds the parallel-hold inventory value this run
    contributes, and the two outcome runs of one event share the same pool of
    capital between them"

    Design: Corner/entities/production_order_computed_unit_ledgers_start_at_zero
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor F2")
    design = create_design(api, licensor)

    run = create_run(api, licensor, design)

    assert run["retired_design_version"] == design["approved_version"]
    assert run["observed_current_design_version"] == design["version"]
    assert run["hold_allocation_cents"] > 0


def test_omitting_design_id_is_a_request_shape_failure(api):
    """PRD §2.10: "Request shape is checked first, at the highest precedence, and
    a failure is reported as `ERR_INVALID_REQUEST` (HTTP 400). This rung covers a
    missing or mistyped body field"

    Design: Corner/entities/production_order_requires_design_id
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor E")

    resp = api.create_production_order(
        {
            "licensor_id": licensor["id"],
            "team_code": "ATL",
            "trigger_type": "STANDARD",
            "expected_demand_qty": 5000,
            "unit_cost_cents": 900,
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


@pytest.mark.parametrize("field,value", [("expected_demand_qty", 0),
                                         ("unit_cost_cents", 0),
                                         ("expected_demand_qty", -1),
                                         ("unit_cost_cents", -5)])
def test_non_positive_run_quantities_are_request_shape_failures(api, field, value):
    """PRD §3.2: "the quantity and economics of the run in `expected_demand_qty`,
    which must be strictly positive, and `unit_cost_cents`, which must also be
    strictly positive"
    PRD §2.10: "a numeric field that must be strictly positive supplied as zero
    or negative"

    Design: Corner/entities/production_order_requires_design_id
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor E2")
    design = create_design(api, licensor)

    payload = {
        "licensor_id": licensor["id"],
        "design_id": design["id"],
        "team_code": "ATL",
        "trigger_type": "STANDARD",
        "expected_demand_qty": 5000,
        "unit_cost_cents": 900,
    }
    payload[field] = value

    validate_error(
        api.create_production_order(payload, PLANNER),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )


def test_run_list_filters_by_status_and_returns_empty_for_unknown_team(api):
    """PRD §4: "GET | `/production-orders` | List production runs filtered by
    licensor, design, status or team | ProductionPlanner, FulfillmentCoordinator,
    AuditOnly"
    PRD §2.3: "`limit` is the maximum number of resources returned in one page"

    Design: Corner/endpoints/production_orders_list_supports_status_and_team_filters
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor W", royalty_rate_pct=0.1)
    design_atl = create_design(api, licensor, team_code="ATL", garment_sku="CAP")
    design_bos = create_design(api, licensor, team_code="BOS", garment_sku="CAP")

    run_atl = create_run(api, licensor, design_atl, team_code="ATL")
    run_bos = create_run(api, licensor, design_bos, team_code="BOS")
    author_layers(api, run_atl, [{"print_type": "BASE", "quantity": 20}])

    committed = api.list_production_orders(PLANNER, params={"status": "COMMITTED"})
    rows, meta = validate_paginated(committed)
    assert len(rows) == 1
    assert rows[0]["id"] == run_atl["id"]
    assert meta["total_count"] == 1

    empty = api.list_production_orders(PLANNER, params={"team_code": "ZZZ"})
    rows_empty, meta_empty = validate_paginated(empty)
    assert rows_empty == []
    assert meta_empty["total_count"] == 0
    assert meta_empty["has_more"] is False

    assert get_run(api, run_bos["id"])["status"] == "PARALLEL_HOLD"


def test_run_cannot_commit_while_its_artwork_is_uncleared(api):
    """PRD §3.2: "Creating the run also requires that the referenced licensor
    exists and that the referenced design exists with an `APPROVED` clearance."
    PRD §3.3: "layering cannot proceed against artwork that is not cleared at
    all: a design in `PENDING_LICENSOR_APPROVAL` or `APPROVAL_REJECTED` fails the
    request with `ERR_DESIGN_NOT_APPROVED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/fulfillment_pick_requires_approved_design
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Xref", royalty_rate_pct=0.1)
    approved = create_design(api, licensor, team_code="ATL", garment_sku="TRACTOR",
                             design_name="ATL Favored Tractor")
    pending = create_design(api, licensor, team_code="ATL", garment_sku="TRACTOR",
                            design_name="ATL Underdog Tractor", approve=False)

    run_a = create_run(
        api, licensor, approved, team_code="ATL", trigger_type="CHAMPIONSHIP_WIN",
        event_outcome="WIN_FAVORED_TEAM", expected_demand_qty=2000,
        win_probability_pct=0.5, outcome_at="2026-09-02T00:00:00Z",
    )
    # A run may only be opened against artwork the licensor has already cleared,
    # so the event's second outcome carries no run while its design is pending.
    assert run_a["design_id"] == approved["id"]
    assert approved["approval_state"] == "APPROVED"
    assert pending["approval_state"] == "PENDING_LICENSOR_APPROVAL"

    committed = author_layers(api, run_a, [{"print_type": "BASE", "quantity": 2000}])
    assert committed["status"] == "COMMITTED"

    resp = api.create_production_order(
        {
            "licensor_id": licensor["id"], "design_id": pending["id"],
            "team_code": "ATL", "trigger_type": "CHAMPIONSHIP_WIN",
            "event_outcome": "WIN_UNDERDOG_TEAM", "expected_demand_qty": 2000,
            "unit_cost_cents": 900, "win_probability_pct": 0.5,
            "outcome_at": "2026-09-02T00:00:00Z",
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_APPROVED)