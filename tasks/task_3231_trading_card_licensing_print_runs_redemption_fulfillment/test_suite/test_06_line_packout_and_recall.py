"""Line packout, the redemption close it drives, and the recall unwind.

Packing a line out is the last line-level move and it closes every fulfilled
redemption under the line's sets. Recall is the platform's most destructive
operation: the allocation goes terminal and the line is unwound.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_fulfilled_redemption,
    build_packed_out_line,
    build_ready_to_ship_allocation,
    get_success_data,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]
DIST = TEST_USERS["distribution_manager_headers"]
PM = TEST_USERS["product_manager_headers"]


def test_packing_the_line_out_closes_its_fulfilled_redemption(api):
    """PRD §3.2: "Packing out sets the line to `PACKED_OUT`, closes every
    redemption under the line's sets that is in `FULFILLED` status".

    Design: Difficulty/transitive_cascade/product_line_pack_out_closes_fulfilled_redemptions_on_its_sets
    """
    scenario = build_fulfilled_redemption(
        api, redemption_code="RDM-9001",
        pack_out_line=False, pack_out_set=False,
    )
    line = scenario["line"]
    card_set = scenario["card_set"]
    redemption = validate_success(
        api.get_redemption(
            scenario["redemption"]["id"],
            TEST_USERS["redemption_analyst_headers"],
        )
    )
    assert scenario["session"]["status"] == "COMPLETED"
    assert redemption["status"] == "FULFILLED", (
        "the signer's session completion fulfilled it before the line packed out"
    )
    assert line["status"] == "IN_PRODUCTION", (
        "the line pack-out has not happened yet; that is the hop under test"
    )
    line = get_success_data(
        api.pack_out_product_line(line["id"], TEST_USERS["production_planner_headers"])
    )
    assert line["status"] == "PACKED_OUT"

    after = validate_success(
        api.get_redemption(redemption["id"], TEST_USERS["redemption_analyst_headers"])
    )
    assert after["status"] == "CLOSED"
    read = validate_success(api.get_card_set(card_set["id"], PLANNER))
    assert read["autograph_redemptions_outstanding"] == 0


def test_the_line_packout_is_the_hop_that_closes_the_redemption(api):
    """PRD §3.4: "each redemption whose status is `ISSUED`, whose `signer_name`
    matches the session's signer, and whose `card_set_id` is named by one of
    the session's allocation lines is moved to `FULFILLED`".

    PRD §3.2: "Packing out sets the line to `PACKED_OUT`, closes every
    redemption under the line's sets that is in `FULFILLED` status".

    Design: Difficulty/transitive_cascade/product_line_pack_out_closes_fulfilled_redemptions_on_its_sets
    """
    scenario = build_packed_out_line(api)
    card_set = scenario["card_set"]
    redemption = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-9002",
                "signer_name": scenario["session"]["signer_name"],
                "estimated_value_cents": 400000,
                "opened_on": "2026-10-12T00:00:00Z",
            },
            TEST_USERS["redemption_analyst_headers"],
        )
    )
    assert redemption["status"] == "ISSUED", (
        "the session had already completed, so nothing fulfilled this one"
    )
    after = validate_success(
        api.get_redemption(redemption["id"], TEST_USERS["redemption_analyst_headers"])
    )
    assert after["status"] == "ISSUED", (
        "only a FULFILLED redemption is closed, so this one is left untouched"
    )


def test_packing_the_line_out_clears_the_sets_outstanding_redemptions(api):
    """PRD §3.2: "recomputes `autograph_redemptions_outstanding` on those sets."

    Design: Difficulty/transitive_cascade/product_line_pack_out_closes_fulfilled_redemptions_on_its_sets
    """
    scenario = build_fulfilled_redemption(
        api, redemption_code="RDM-9003", pack_out_line=False, pack_out_set=False
    )
    get_success_data(
        api.pack_out_product_line(
            scenario["line"]["id"], TEST_USERS["production_planner_headers"]
        )
    )
    card_set = validate_success(
        api.get_card_set(scenario["card_set"]["id"], PLANNER)
    )
    assert card_set["autograph_redemptions_outstanding"] == 0, (
        "the fulfilled redemption was closed, so the outstanding count drops to zero"
    )


def test_packing_a_line_out_requires_its_autograph_plan_to_be_secured(api):
    """PRD §3.2: "every card set under the line whose `autograph_planned_count`
    exceeds zero must by then have `autograph_secured_count` at least equal to
    that plan, and a shortfall is refused with `ERR_AUTOGRAPH_QUANTITY_SHORT`."

    Design: Difficulty/transitive_cascade/product_line_pack_out_closes_fulfilled_redemptions_on_its_sets
    """
    scenario = build_packed_out_line(
        api, quantity_delivered=50, autograph_planned_count=200,
        pack_out_line=False,
    )
    card_set = validate_success(api.get_card_set(scenario["card_set"]["id"], PLANNER))
    assert card_set["autograph_secured_count"] == 50
    assert card_set["autograph_planned_count"] == 200, (
        "only half the planned autographs were ever secured"
    )


def test_recall_returns_the_whole_product_line(api):
    """PRD §3.8: "The line's `version` advances by one, and the call returns
    the line rather than the allocation, because the line is what has
    materially changed."

    Design: Difficulty/transitive_cascade/product_line_pack_out_closes_fulfilled_redemptions_on_its_sets
    """
    scenario = build_ready_to_ship_allocation(api, ship=True)
    line = scenario["line"]
    allocation = scenario["allocation"]
    assert allocation["status"] == "SHIPPED"

    recalled_line = validate_success(api.recall_allocation(allocation["id"], DIST))
    assert "line_name" in recalled_line, "the recall returns the ProductLine"
    assert recalled_line["id"] == line["id"]
    assert recalled_line["status"] == "PLANNING"
    assert recalled_line["version"] > line["version"]


def test_recall_unwinds_the_frozen_print_run_under_the_line(api):
    """PRD §3.8: "Each recursion of the loop also supersedes every print-run
    decision belonging to the line's card sets and returns those card sets'
    print-run status to the `UNDECIDED` value".

    Design: Difficulty/transitive_cascade/product_line_pack_out_closes_fulfilled_redemptions_on_its_sets
    """
    scenario = build_ready_to_ship_allocation(api, ship=True)
    card_set = scenario["card_set"]
    assert card_set["print_run_status"] in ("LOCKED", "DISCLOSED", "UNDISCLOSED")

    get_success_data(api.recall_allocation(scenario["allocation"]["id"], DIST))

    read = validate_success(api.get_card_set(card_set["id"], PLANNER))
    assert read["print_run_status"] == "UNDECIDED"


def test_recall_drives_the_line_back_while_approved_defect_exposure_remains(api):
    """PRD §3.8: "the platform repeatedly returns the parent product line to
    `PLANNING`, once per recursion, and continues recursing while the total
    `affected_quantity` summed over the quality claims for that line's card
    sets that are in `APPROVED` status exceeds the platform's
    `QUALITY_RECALL_THRESHOLD`."

    Design: Difficulty/transitive_cascade/product_line_pack_out_closes_fulfilled_redemptions_on_its_sets
    """
    scenario = build_ready_to_ship_allocation(
        api, ship=True, quality_claim_affected=40
    )
    assert scenario["claim"]["status"] == "APPROVED"
    assert scenario["claim"]["affected_quantity"] == 40

    recalled_line = validate_success(api.recall_allocation(scenario["allocation"]["id"], DIST))
    assert recalled_line["status"] == "PLANNING"
    assert recalled_line["sets_per_case"] == (
        recalled_line["boxes_per_case"]
        * recalled_line["packs_per_box"]
        * recalled_line["cards_per_pack"]
    )
    read = validate_success(api.get_card_set(scenario["card_set"]["id"], PLANNER))
    assert read["print_run_status"] == "UNDECIDED"