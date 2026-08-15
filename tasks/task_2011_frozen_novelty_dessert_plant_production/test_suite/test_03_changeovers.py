"""Changeover matrix branches and the cleaning redo loop (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    complete_run_ok,
    create_booking,
    create_changeover,
    create_product,
    create_released_batch,
    create_run,
    create_verified_changeover,
    get_success_data,
    setup_completed_run,
    setup_mix_assigned_run,
    setup_plant,
    start_run,
    validate_error,
)
from test_helpers.fixtures import PM, PLANNER


def _complete_nutbar_run(api, line, zone, tunnel):
    """Run NUTBAR (allergens [MILK,PEANUT,SOY], NUT_BAKERY) to completion on
    the given line so line.last_product_id becomes NUTBAR."""
    nut = create_product(sku_code="NUTBAR", product_name="Nut Bar",
                         flavor_family="NUT_BAKERY",
                         allergens=["MILK", "PEANUT", "SOY"])
    batch = create_released_batch(nut["id"], batch_code="MB-N", litres=200)
    run = create_run(nut["id"], line["id"], run_code="R-NUT",
                     planned_units=1000)
    create_verified_changeover(line["id"], nut["id"])
    create_booking(tunnel["id"], run["id"])
    get_success_data(api.assign_mix(run["id"], {"mix_batch_id": batch["id"]},
                                    PLANNER))
    start_run(run["id"])
    complete_run_ok(run["id"], 1000, 40.0, zone["id"])
    return nut


class TestChangeoverMatrix:
    def test_allergen_branch_dominates_flavor_branch(self, api):
        """PRD §3.4: "when the from-product's allergen set is not a subset of
        the to-product's allergen set — that is, some residue allergen is not
        declared by the target product — the level is ALLERGEN_CIP."
        "Duration is fixed by level: ... 240 minutes for ALLERGEN_CIP."

        NUTBAR [MILK,PEANUT,SOY] -> VANBAR [MILK]: PEANUT and SOY are not
        declared by the target, so the allergen branch fires even though the
        flavor family also differs.

        Design: Difficulty/combinatorial_formula/changeover_matrix_set_containment_branches
        """
        _, line, tunnel, zone = setup_plant()
        nut = _complete_nutbar_run(api, line, zone, tunnel)
        van = create_product(sku_code="VANBAR", product_name="Vanilla Bar",
                             flavor_family="VANILLA", allergens=["MILK"])
        ch = create_changeover(line["id"], van["id"])
        assert ch["required_clean_level"] == "ALLERGEN_CIP"
        assert ch["duration_minutes"] == 240
        assert ch["from_product_id"] == nut["id"]

    def test_superset_allergens_fall_through_to_wash(self, api):
        """PRD §3.4: "Otherwise, when the from-product's flavor_family
        differs from the to-product's flavor_family, the level is WASH."
        "Duration is fixed by level: ... 90 minutes for WASH."

        NUTBAR [MILK,PEANUT,SOY] -> CHOCSUP [MILK,PEANUT,SOY,WHEAT]: the
        allergen set IS a subset, so the allergen branch does not fire; the
        families differ (NUT_BAKERY vs CHOCOLATE) -> WASH.

        Design: Difficulty/combinatorial_formula/changeover_matrix_set_containment_branches
        """
        _, line, tunnel, zone = setup_plant()
        _complete_nutbar_run(api, line, zone, tunnel)
        choc = create_product(sku_code="CHOCSUP", product_name="Choc Supreme",
                              flavor_family="CHOCOLATE",
                              allergens=["MILK", "PEANUT", "SOY", "WHEAT"])
        # Complete+verify the first changeover so the line returns to IDLE.
        create_verified_changeover(line["id"], choc["id"])
        ch = create_changeover(line["id"], choc["id"])
        # from is still NUTBAR (no run completed between changeovers)
        # but to avoid ambiguity about which branch fires, assert the level
        # computed from NUTBAR -> CHOCSUP: WASH.
        assert ch["required_clean_level"] == "WASH"
        assert ch["duration_minutes"] == 90

    def test_superset_same_family_is_rinse(self, api):
        """PRD §3.4: "Otherwise the level is RINSE." "Duration is fixed by
        level: 30 minutes for RINSE".

        NUTBAR [MILK,PEANUT,SOY] -> NUTBAR-2 [MILK,PEANUT,SOY,WHEAT] in the
        same NUT_BAKERY family: allergen subset holds and family matches, so
        only a rinse is required.

        Design: Difficulty/combinatorial_formula/changeover_matrix_set_containment_branches
        """
        _, line, tunnel, zone = setup_plant()
        _complete_nutbar_run(api, line, zone, tunnel)
        nut2 = create_product(sku_code="NUTBAR-2", product_name="Nut Bar Light",
                              flavor_family="NUT_BAKERY",
                              allergens=["MILK", "PEANUT", "SOY", "WHEAT"])
        ch = create_changeover(line["id"], nut2["id"])
        assert ch["required_clean_level"] == "RINSE"
        assert ch["duration_minutes"] == 30

    def test_changeover_first_use_rinse(self, api):
        """PRD §3.4: "When from_product_id is null (the line has never run),
        the level is RINSE." "Creation snapshots from_product_id from the
        line's last_product_id"."

        Design: Corner/calculations/changeover_first_use_rinse
        """
        product, line, _, _ = setup_plant()
        ch = create_changeover(line["id"], product["id"])
        assert ch["required_clean_level"] == "RINSE"
        assert ch["duration_minutes"] == 30
        assert ch["from_product_id"] is None


class TestChangeoverSequence:
    def test_changeover_while_line_running_rejected(self, api):
        """PRD §3.4: "Creation requires the line to be IDLE — a line with a
        run in flight or another open changeover rejects with
        ERR_CHANGEOVER_SEQUENCE (HTTP 422)"."

        Design: Corner/validations/changeover_while_line_running_rejected
        """
        ctx = setup_mix_assigned_run(run_code="R-SE")
        choc = create_product(sku_code="BAR-CHOC-70", product_name="Choc Bar",
                              flavor_family="CHOCOLATE",
                              allergens=["MILK", "SOY"])
        start_run(ctx["run"]["id"])
        resp = api.create_changeover(
            {"line_id": ctx["line"]["id"], "to_product_id": choc["id"]},
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_SEQUENCE)


class TestLineCompletionSnapshot:
    def test_run_complete_sets_line_last_product(self, api):
        """PRD §3.5: completion "returns the line RUNNING -> IDLE with
        last_product_id set to the run's product and last_allergens
        snapshotted from that product"."

        Design: Corner/state_machines/run_complete_sets_line_last_product
        """
        ctx = setup_completed_run(
            product_overrides={
                "sku_code": "NUTBAR", "product_name": "Nut Bar",
                "flavor_family": "NUT_BAKERY",
                "allergens": ["MILK", "PEANUT", "SOY"]},
            line_overrides={"line_code": "L-2"},
            run_code="R-LP", planned_units=1000, actual_units=1000,
            mix_metered_litres=40.0)
        line = get_success_data(api.get_line(ctx["line"]["id"], PM))
        assert line["status"] == "IDLE"
        assert line["last_product_id"] == ctx["product"]["id"]
        assert sorted(line["last_allergens"]) == ["MILK", "PEANUT", "SOY"]
