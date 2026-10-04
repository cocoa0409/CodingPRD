"""Corner queue: state-machine claims — divestiture re-signing lockdown,
terminal transfers, DISCONTINUED-item sell-down rejection, and the first-run
PLANNED -> QUALIFYING auto-transition.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_qualification_run_payload,
    create_sell_down_payload,
    create_sign_spa_payload,
    get_item,
    get_tsa_for_divestiture,
    get_transfer,
    make_plant_director_headers,
    record_pass_run,
    setup_divestiture_closed,
    setup_executed_case,
    setup_transfer_executed,
    setup_transfer_planned,
    validate_error,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]


def test_sign_spa_on_closed_divestiture_returns_invalid_state():
    """PRD §3.5: "Signing requires the divestiture to be `PROPOSED`".
    PRD §3.5: "creates exactly one `TransitionServiceAgreement` in `DRAFT`
    bound to the divestiture".

    Design: Corner/state_machines/sign_spa_on_closed_divestiture_returns_invalid_state
    """
    _, divestiture, _ = setup_divestiture_closed(tsa_monthly_fee_cents=75000)
    assert divestiture["divestiture_status"] == "CLOSED", "Setup failed"
    resp = api_client.sign_divestiture_spa(
        divestiture["id"],
        create_sign_spa_payload(tsa_monthly_fee_cents=99000),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    # Still exactly one TSA, with the ORIGINAL fee — no duplicate created.
    tsa = get_tsa_for_divestiture(divestiture["id"])
    assert tsa["monthly_fee_cents"] == 75000


def test_run_on_executed_transfer_returns_invalid_state():
    """PRD §3.4: "Runs are accepted only while the transfer is `PLANNED` or
    `QUALIFYING`; any other transfer state fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/run_on_executed_transfer_returns_invalid_state
    """
    _, _, target_plant, _, transfer = setup_transfer_executed()
    assert transfer["transfer_status"] == "EXECUTED", "Setup failed"
    resp = api_client.record_qualification_run(
        transfer["id"],
        create_qualification_run_payload(run_date="2026-09-04T00:00:00Z"),
        # EXECUTED is terminal: the state guard rejects before ownership.
        # Use the target plant's director so only the state guard can fire.
        make_plant_director_headers(target_plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    runs, _ = validate_paginated(
        api_client.list_qualification_runs(transfer["id"], PM)
    )
    assert len(runs) == 2, "no third run may be recorded on an EXECUTED transfer"


def test_sell_down_on_discontinued_item_returns_invalid_state():
    """PRD §3.3: "Sell-down is permitted only while the item is `LISTED` or
    `SELL_THROUGH`; any other state is rejected with `ERR_INVALID_STATE`."
    PRD §2.8: "23. The optimistic-concurrency check on sell-down
    (`ERR_STALE_VERSION`) is evaluated last."

    Design: Corner/state_machines/sell_down_on_discontinued_item_returns_invalid_state
    """
    _, _, item, _ = setup_executed_case({"units_on_hand": 50})
    assert item["item_status"] == "DISCONTINUED", "Setup failed"
    # Supply the item's CURRENT version: only the state guard can fire.
    resp = api_client.sell_down_item(
        item["id"],
        create_sell_down_payload(1, item["version"]),
        SCP,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_first_run_moves_transfer_planned_to_qualifying():
    """PRD §3.4: "A new transfer starts `PLANNED` with `consecutive_pass_count`
    zero."
    PRD §3.4: "The first accepted run moves the transfer from `PLANNED` to
    `QUALIFYING`; subsequent runs are a self-loop within `QUALIFYING`. Each
    `PASS` increments the transfer's `consecutive_pass_count` by 1".

    Design: Corner/state_machines/first_run_moves_transfer_planned_to_qualifying
    """
    _, _, target_plant, _, transfer = setup_transfer_planned()
    assert transfer["transfer_status"] == "PLANNED"
    assert transfer["consecutive_pass_count"] == 0
    record_pass_run(transfer["id"], target_plant["id"],
                    run_date="2026-09-02T00:00:00Z")
    after = get_transfer(transfer["id"])
    assert after["transfer_status"] == "QUALIFYING"
    assert after["consecutive_pass_count"] == 1
