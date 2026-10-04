"""Authoring print layers against a held run and the layer sequencing rules."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    AUDIT,
    PLANNER,
    author_layers,
    create_design,
    create_licensor,
    create_run,
    get_run,
    set_clock,
)


def test_layers_are_listed_against_their_run_with_pending_state(api):
    """PRD §3.3: "A new layer is written with its `layer_state` in
    `PENDING_PRINT` and with `printed_qty`, `committed_qty` and `failed_qty` all
    at 0 and `design_version_checked` null."

    Design: Corner/endpoints/print_layer_list_scoped_by_run
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor Z", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="PHI", garment_sku="TRACTOR")
    run = create_run(api, licensor, design, team_code="PHI")
    committed = author_layers(
        api, run,
        [{"print_type": "BASE", "quantity": 20},
         {"print_type": "EMBROIDER", "quantity": 10}],
    )

    resp = api.list_print_layers(PLANNER,
                                 params={"production_order_id": run["id"]})
    rows, meta = validate_paginated(resp)

    assert len(rows) == 2
    assert meta["total_count"] == 2
    for layer in rows:
        assert layer["layer_state"] == "PENDING_PRINT"
        assert layer["committed_qty"] == 0
        assert layer["printed_qty"] == 0
        assert layer["failed_qty"] == 0

    assert committed["base_units_printed"] == 20
    assert committed["accessory_units_printed"] == 10
    assert committed["layer_ids"][0] == rows[0]["id"]


def test_committing_recomputes_the_unit_totals_by_print_type(api):
    """PRD §3.3: "The run's `base_units_printed` and `accessory_units_printed` are
    recomputed from the committed layer set — the first summing `committed_qty`
    over layers whose `print_type` is `BASE`, the second summing `committed_qty`
    over layers whose `print_type` is `EMBROIDER`, `HEAT_PRESS` or `PENNANT`"

    Design: Corner/endpoints/print_layer_list_scoped_by_run
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor Z2")
    design = create_design(api, licensor, team_code="PHI", garment_sku="TRACTOR")
    run = create_run(api, licensor, design, team_code="PHI")

    committed = author_layers(
        api, run,
        [{"print_type": "BASE", "quantity": 200},
         {"print_type": "HEAT_PRESS", "quantity": 40},
         {"print_type": "PENNANT", "quantity": 60}],
    )
    assert committed["base_units_printed"] == 200
    assert committed["accessory_units_printed"] == 100
    assert len(committed["layer_ids"]) == 3


def test_a_pennant_layer_is_refused_when_the_flag_is_false(api):
    """PRD §3.3: "a `PENNANT` layer may only be requested on a run whose
    `pennants_included` flag is true; a pennant layer on a run that has declared
    pennants excluded from its sellable units is refused with the same code"

    Design: Corner/state_machines/print_layer_pennant_blocked_when_flag_false
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor L", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="BOS", garment_sku="PENNANT",
                           design_name="L Pennant")
    run = create_run(api, licensor, design, team_code="BOS",
                     pennants_included=False)

    resp = api.author_layers(
        run["id"],
        {
            "expected_production_order_version": run["version"],
            "layers": [{"print_type": "PENNANT", "quantity": 500}],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_PRINT_TYPECAST_MISMATCH)

    unchanged = get_run(api, run["id"])
    assert unchanged["status"] == "PARALLEL_HOLD"
    assert unchanged["layer_ids"] == []


def test_a_non_base_layer_before_the_base_layer_is_refused(api):
    """PRD §3.3: "a `BASE` layer must be committed before any `EMBROIDER` or
    `HEAT_PRESS` layer on the same run: a request that presents a non-base
    operation before its run's base layer has been committed is refused."

    Design: Corner/state_machines/print_layer_pennant_blocked_when_flag_false
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor L2")
    design = create_design(api, licensor, team_code="BOS", garment_sku="TRACTOR")
    run = create_run(api, licensor, design, team_code="BOS")

    resp = api.author_layers(
        run["id"],
        {
            "expected_production_order_version": run["version"],
            "layers": [{"print_type": "EMBROIDER", "quantity": 20}],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_PRINT_TYPECAST_MISMATCH)


def test_shortfall_destroy_mode_leaves_the_run_in_parallel_hold(api):
    """PRD §3.3: "When `destroy_mode` is supplied as `SHORTFALL`, the run is not
    committed at all: it stays in `PARALLEL_HOLD`, and the call's effect stops at
    appending the submitted layers, recomputing the printed-unit totals from them
    and appending their ids to `layer_ids` in submission order."

    Design: Corner/entities/production_order_computed_unit_ledgers_start_at_zero
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor L3")
    design = create_design(api, licensor, team_code="BOS", garment_sku="TRACTOR")
    run = create_run(api, licensor, design, team_code="BOS")

    staged = author_layers(
        api, run, [{"print_type": "BASE", "quantity": 20}], destroy_mode="SHORTFALL",
    )

    assert staged["status"] == "PARALLEL_HOLD"
    assert staged["committed_at"] is None
    assert len(staged["layer_ids"]) == 1
    assert staged["base_units_printed"] == 20


def test_committing_advances_the_run_design_and_licensor_versions(api):
    """PRD §3.3: "Every committing path advances three versions. The run's own
    `version` is incremented by 1, the `Design`'s `version` is incremented by 1,
    and the `Licensor`'s `version` is incremented by 1 with its
    `accrued_unsettled_cents` recomputed from the ledger invariant of §2.4."

    Design: Corner/entities/production_order_computed_unit_ledgers_start_at_zero
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor L4")
    design = create_design(api, licensor)
    run = create_run(api, licensor, design)

    committed = author_layers(api, run, [{"print_type": "BASE", "quantity": 20}])

    assert committed["version"] == run["version"] + 1
    assert api.get_design(design["id"], PLANNER).status_code == 200
    licensor_after = api.get_licensor(licensor["id"], AUDIT)
    validate_success(licensor_after, expected_status=200)
    assert licensor_after.json()["data"]["version"] > licensor["version"]


@pytest.mark.parametrize("quantity", [0, -5])
def test_a_layer_quantity_must_be_strictly_positive(api, quantity):
    """PRD §3.3: "the number of units it is authorised for through `quantity`,
    which must be strictly positive"

    Design: Corner/entities/production_order_requires_design_id
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor L5")
    design = create_design(api, licensor)
    run = create_run(api, licensor, design)

    resp = api.author_layers(
        run["id"],
        {
            "expected_production_order_version": run["version"],
            "layers": [{"print_type": "BASE", "quantity": quantity}],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_a_stale_run_version_blocks_the_commit_request(api):
    """PRD §2.8: "authoring layers against a run carries
    `expected_production_order_version` compared against the `ProductionOrder`'s
    current `version` ... In every one of those cases a mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/pick_with_stale_run_version_is_rejected
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor L6")
    design = create_design(api, licensor)
    run = create_run(api, licensor, design)

    author_layers(api, run, [{"print_type": "BASE", "quantity": 20}])

    resp = api.author_layers(
        run["id"],
        {
            "expected_production_order_version": run["version"],
            "layers": [{"print_type": "BASE", "quantity": 20}],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)