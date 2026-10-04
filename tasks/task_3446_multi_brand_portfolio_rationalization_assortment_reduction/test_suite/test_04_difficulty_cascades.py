"""Difficulty queue: transitive cascades — the depth-3 TSA-termination chain
(items -> cases -> plants) and the depth-2 case-finalization chain.
"""
from test_helpers import (
    DEFAULT_APPROVAL_DEADLINE_ISO,
    TEST_USERS,
    USER_IDS,
    api_client,
    assert_item,
    create_brand,
    create_divestiture_payload,
    create_item,
    create_plant,
    create_sign_spa_payload,
    decide_case,
    finalize_case,
    get_item,
    get_success_data,
    get_tsa_for_divestiture,
    propose_case,
    set_clock,
    setup_listed_item,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


def _setup_divested_brand_with_live_items():
    """Non-core brand with Item1 (STANDARD obsolescence) at Plant A and Item2
    (SALVAGE) at Plant C; Item1 carries an open SCORED case; the divestiture is
    CLOSED so the TSA is ACTIVE (window 2026-09-01..2027-09-01, fee 100000).

    Returns dict of ids."""
    brand = create_brand(core_flag=False, private_label_share_pct=20,
                         annual_net_revenue_cents=800000000)
    plant_a = create_plant(quarterly_capacity_units=1000000)
    plant_c = create_plant(quarterly_capacity_units=1000000)
    item1 = create_item(brand["id"], plant_a["id"], annual_units=4000,
                        unit_net_revenue_cents=2000, unit_cost_cents=500,
                        units_on_hand=100)
    item2 = create_item(brand["id"], plant_c["id"], annual_units=8000,
                        unit_net_revenue_cents=2000, unit_cost_cents=400,
                        units_on_hand=50, salvageable=True)
    case1 = propose_case(item1["id"])
    dv = get_success_data(
        api_client.create_divestiture(create_divestiture_payload(brand["id"]), PM)
    )
    get_success_data(
        api_client.sign_divestiture_spa(dv["id"], create_sign_spa_payload(), PM)
    )
    # TSA start 2026-09-01 equals the default clock; closing at the boundary
    # instant is allowed.
    get_success_data(api_client.close_divestiture(dv["id"], PM))
    tsa = get_tsa_for_divestiture(dv["id"])
    assert tsa["tsa_status"] == "ACTIVE", "Setup failed: TSA must be ACTIVE"
    return {
        "brand": brand, "plant_a": plant_a, "plant_c": plant_c,
        "item1": item1, "item2": item2, "case1": case1, "tsa": tsa,
    }


class TestTsaTerminateDepth3Cascade:
    def test_tsa_terminate_discontinues_items_with_variant_charges(self):
        """PRD §3.5: "Hop 1: every item of the divested brand whose
        `item_status` is `LISTED`, `CUT_PROPOSED`, or `SELL_THROUGH` is moved
        to `DISCONTINUED`, with its obsolescence charge posted per the
        two-variant rule of §3.2, its `units_on_hand` folded into
        `units_written_off_cumulative` and zeroed, and its `version`
        incremented."

        Design: Difficulty/transitive_cascade/tsa_terminate_depth3_cascade
        """
        ctx = _setup_divested_brand_with_live_items()
        validate_ok(api_client.terminate_tsa(ctx["tsa"]["id"], FC))
        item1 = get_item(ctx["item1"]["id"])
        item2 = get_item(ctx["item2"]["id"])
        assert_item(item1)
        assert_item(item2)
        assert item1["item_status"] == "DISCONTINUED"
        assert item2["item_status"] == "DISCONTINUED"
        assert item1["obsolescence_charge_cents"] == 50000, (
            f"Item1 STANDARD charge must be 100 * 500 = 50000, got "
            f"{item1['obsolescence_charge_cents']}"
        )
        assert item2["obsolescence_charge_cents"] == 16000, (
            f"Item2 SALVAGE charge must be round_half_up(50 * 400 * 0.8) = 16000, "
            f"got {item2['obsolescence_charge_cents']}"
        )
        assert item1["units_on_hand"] == 0 and item1["units_written_off_cumulative"] == 100
        assert item2["units_on_hand"] == 0 and item2["units_written_off_cumulative"] == 50

    def test_tsa_terminate_voids_open_cases_and_recomputes_plants(self):
        """PRD §3.5: "Hop 2: every open rationalization case on those items —
        whether `SCORED` or `EXECUTING` — is auto-`VOIDED`, with
        `decider_user_id` set to the literal string `system`, and each such
        case's `version` incremented. Hop 3: every plant that hosted a
        discontinued item recomputes its `committed_units_per_quarter` and
        `utilization_pct`."
        PRD §3.5: "step one: the months remaining are the days remaining
        divided by 30 days per penalty month and rounded **up** to a whole
        number of months."

        Design: Difficulty/transitive_cascade/tsa_terminate_depth3_cascade
        """
        ctx = _setup_divested_brand_with_live_items()
        terminated = validate_ok(api_client.terminate_tsa(ctx["tsa"]["id"], FC))
        # Hop 2: the open SCORED case on item1 is auto-VOIDED.
        cases, _meta = validate_paginated(
            api_client.list_rationalization_cases(PM, params={"item_id": ctx["item1"]["id"]})
        )
        assert len(cases) == 1
        assert cases[0]["id"] == ctx["case1"]["id"]
        assert cases[0]["case_status"] == "VOIDED"
        assert cases[0]["decider_user_id"] == USER_IDS["SYSTEM_MARKER"]
        # Hop 3: both host plants recompute to zero committed load.
        plants, _ = validate_paginated(api_client.list_plants(PM))
        by_id = {p["id"]: p for p in plants}
        for plant in (ctx["plant_a"], ctx["plant_c"]):
            assert by_id[plant["id"]]["committed_units_per_quarter"] == 0, (
                f"plant {plant['name']} must drop to 0 committed units, got "
                f"{by_id[plant['id']]['committed_units_per_quarter']}"
            )
            assert by_id[plant["id"]]["utilization_pct"] == 0.00
        # Termination at the default clock 2026-09-01 is early: 365 days
        # remaining -> ceil(365/30) = 13 months -> 13 * 100000 * 0.25 = 325000.
        assert terminated["early_termination_penalty_cents"] == 325000, (
            f"early penalty must be 13 * 100000 * 0.25 = 325000, got "
            f"{terminated['early_termination_penalty_cents']}"
        )


class TestFinalizeDepth2Cascade:
    def _setup_executing_case_on_heavy_item(self):
        """Plant (capacity 100000) hosting one item (annual 40000 -> committed
        10000; on hand 25, cost 800); case approved at the default clock so the
        deadline is 2026-11-30; clock advanced to the deadline."""
        _, plant, item, case = self._build()
        set_clock(DEFAULT_APPROVAL_DEADLINE_ISO)
        return plant, item, case

    def _build(self):
        brand, plant, item = setup_listed_item(
            {"annual_units": 40000, "unit_net_revenue_cents": 2000,
             "unit_cost_cents": 800, "units_on_hand": 25},
            plant_overrides={"quarterly_capacity_units": 100000},
        )
        case = propose_case(item["id"])
        decide_case(case["id"], "APPROVE")
        return brand, plant, item, case

    def test_finalize_discontinues_item_posts_charge_and_writeoff(self):
        """PRD §3.2: "Finalizing moves the case to `EXECUTED` and the item to
        `DISCONTINUED`, posts the item's obsolescence charge, writes off the
        remaining inventory, and recomputes the host plant's load now that the
        item has left the committed set."

        Design: Difficulty/transitive_cascade/finalize_depth2_cascade
        """
        _, item, case = self._setup_executing_case_on_heavy_item()
        finalized = finalize_case(case["id"])
        assert finalized["case_status"] == "EXECUTED"
        item_after = get_item(item["id"])
        assert item_after["item_status"] == "DISCONTINUED"
        assert item_after["obsolescence_charge_cents"] == 20000, (
            f"STANDARD charge must be 25 * 800 = 20000, got "
            f"{item_after['obsolescence_charge_cents']}"
        )
        assert item_after["units_written_off_cumulative"] == 25
        assert item_after["units_on_hand"] == 0

    def test_finalize_recomputes_host_plant_load(self):
        """PRD §3.4: "The `committed_units_per_quarter` of a plant is the sum,
        over every item whose `primary_plant_id` is this plant and whose
        `item_status` is one of `LISTED`, `CUT_PROPOSED`, or `SELL_THROUGH`, of
        that item's `annual_units` divided by 4 and rounded half-up to a whole
        number of units — the rounding happens per item, before the sum;
        `DISCONTINUED` items are excluded entirely."

        Design: Difficulty/transitive_cascade/finalize_depth2_cascade
        """
        plant, item, case = self._setup_executing_case_on_heavy_item()
        plants_pre, _ = validate_paginated(api_client.list_plants(PM))
        pre = {p["id"]: p for p in plants_pre}[plant["id"]]
        assert pre["committed_units_per_quarter"] == 10000, (
            f"40000/4 = 10000 committed before finalize, got "
            f"{pre['committed_units_per_quarter']}"
        )
        assert pre["utilization_pct"] == 10.00
        finalize_case(case["id"])
        plants_post, _ = validate_paginated(api_client.list_plants(PM))
        post = {p["id"]: p for p in plants_post}[plant["id"]]
        assert post["committed_units_per_quarter"] == 0, (
            f"DISCONTINUED item leaves the committed set: expected 0, got "
            f"{post['committed_units_per_quarter']}"
        )
        assert post["utilization_pct"] == 0.00
