"""Corner queue: quantity/size bounds and timing-gate validation claims —
sell-down quantity, project size against the pool, divestiture-close timing,
finalize timing, and transfer referential integrity.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_innovation_project_payload,
    create_plant,
    create_product_transfer_payload,
    create_sell_down_payload,
    get_item,
    get_tsa_for_divestiture,
    set_clock,
    setup_capital_cycle,
    setup_divestiture_spa_signed,
    setup_executing_case,
    setup_listed_item,
    validate_error,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]


def test_sell_down_exceeding_on_hand_returns_insufficient_units():
    """PRD §3.3: "The quantity must be at least 1 and no greater than the
    item's current `units_on_hand`, otherwise the call is rejected with
    `ERR_INSUFFICIENT_UNITS` (HTTP 422)."

    Design: Corner/validations/sell_down_exceeding_on_hand_returns_insufficient_units
    """
    _, _, item = setup_listed_item({"units_on_hand": 50})
    resp = api_client.sell_down_item(
        item["id"], create_sell_down_payload(51, item["version"]), SCP
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNITS)
    assert get_item(item["id"])["units_on_hand"] == 50, (
        "a rejected sell-down must leave the balance unchanged"
    )


def test_project_request_exceeding_cycle_total_returns_capital_request_too_large():
    """PRD §3.7: "the `requested_capital_cents` (greater than zero and no
    greater than the cycle's `total_capital_cents` — an oversized request is
    rejected with `ERR_CAPITAL_REQUEST_TOO_LARGE`, HTTP 422)".

    Design: Corner/validations/project_request_exceeding_cycle_total_returns_capital_request_too_large
    """
    cycle = setup_capital_cycle(total_capital_cents=500000000)
    brand = create_brand(core_flag=True)
    resp = api_client.create_innovation_project(
        create_innovation_project_payload(
            brand["id"], cycle["id"], requested_capital_cents=500000001,
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_CAPITAL_REQUEST_TOO_LARGE)


def test_close_before_tsa_start_returns_tsa_not_started():
    """PRD §3.5: "Closing the divestiture requires it to be `SPA_SIGNED` and
    requires that the logical clock has reached the TSA's `start_date`;
    closing earlier is rejected with `ERR_TSA_NOT_STARTED` (HTTP 409), with the
    boundary inclusive — closing exactly at `start_date` is allowed."

    Design: Corner/validations/close_before_tsa_start_returns_tsa_not_started
    """
    # TSA window starts 2026-10-15; clock stays at the 2026-09-01 default.
    _, divestiture, tsa = setup_divestiture_spa_signed(
        tsa_start_date="2026-10-15T00:00:00Z",
        tsa_end_date="2027-10-15T00:00:00Z",
        divestiture_overrides={"expected_close_date": "2026-11-01T00:00:00Z"},
    )
    resp = api_client.close_divestiture(divestiture["id"], PM)
    validate_error(resp, ApiErrorId.ERR_TSA_NOT_STARTED)
    after = validate_ok(api_client.get_divestiture(divestiture["id"], PM))
    assert after["divestiture_status"] == "SPA_SIGNED"
    assert get_tsa_for_divestiture(divestiture["id"])["tsa_status"] == "DRAFT"


def test_finalize_before_deadline_returns_sell_through_open():
    """PRD §3.2: "the boundary is inclusive, so a finalize at exactly the
    deadline instant is allowed, and an earlier attempt is rejected with
    `ERR_SELL_THROUGH_OPEN` (HTTP 409)."

    Design: Corner/validations/finalize_before_deadline_returns_sell_through_open
    """
    # Approved at the default clock 2026-09-01 -> deadline 2026-11-30;
    # finalize attempted one day early.
    _, _, item, case = setup_executing_case({"units_on_hand": 10})
    set_clock("2026-11-29T00:00:00Z")
    resp = api_client.finalize_rationalization_case(case["id"], PM)
    validate_error(resp, ApiErrorId.ERR_SELL_THROUGH_OPEN)
    assert get_item(item["id"])["item_status"] == "SELL_THROUGH"
    after = validate_ok(api_client.get_rationalization_case(case["id"], PM))
    assert after["case_status"] == "EXECUTING"


def test_transfer_same_plant_and_source_mismatch_referential_errors():
    """PRD §3.4: "The `target_plant_id` must differ from the `source_plant_id`
    (`ERR_SAME_PLANT`, HTTP 422), and the claimed `source_plant_id` must equal
    the item's current `primary_plant_id` (`ERR_SOURCE_PLANT_MISMATCH`, HTTP
    422)."

    Design: Corner/validations/transfer_same_plant_and_source_mismatch_referential_errors
    """
    _, plant_s, item = setup_listed_item()
    plant_t = create_plant(quarterly_capacity_units=1000000)
    plant_t2 = create_plant(quarterly_capacity_units=1000000)
    # target == source
    resp_same = api_client.create_product_transfer(
        create_product_transfer_payload(item["id"], plant_s["id"], plant_s["id"]),
        SCP,
    )
    validate_error(resp_same, ApiErrorId.ERR_SAME_PLANT)
    # claimed source differs from the item's actual primary plant
    resp_mismatch = api_client.create_product_transfer(
        create_product_transfer_payload(item["id"], plant_t["id"], plant_t2["id"]),
        SCP,
    )
    validate_error(resp_mismatch, ApiErrorId.ERR_SOURCE_PLANT_MISMATCH)
    transfers, _ = validate_paginated(
        api_client.list_product_transfers(SCP, params={"item_id": item["id"]})
    )
    assert transfers == [], "no transfer may persist from either rejected call"
