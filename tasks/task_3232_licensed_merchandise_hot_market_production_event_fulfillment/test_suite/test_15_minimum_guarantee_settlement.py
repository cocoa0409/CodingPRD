"""Minimum-guarantee settlement and its compensating reversal."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    committed_run,
    create_licensor,
    create_order,
    deliver_flow,
    get_licensor,
    make_licensing_ops_headers,
    set_clock,
)


def _licensor_with_accrual(api, guarantee_cents, target_accrued=843.75,
                           royalty_rate_pct=0.1, **licensor_overrides):
    """Build a licensor whose ledger holds exactly `target_accrued` cents.

    One delivered ECOM order of 2500 units on a CAP design has a gross of 12500
    cents, so its row accrues 750.00 of royalty (12500 * 0.06) plus 93.75 of
    designer premium (750 * 0.125), a row total of 843.75 cents — the reference
    figure the PRD's settlement examples carry.
    """
    setup = committed_run(
        api, base_qty=6000,
        licensor_overrides={
            "name": f"NBL Guarantee {guarantee_cents}",
            "royalty_rate_pct": royalty_rate_pct,
            "minimum_guarantee_cents": guarantee_cents,
            **licensor_overrides,
        },
        design_overrides={"team_code": "BOS", "garment_sku": "CAP",
                          "design_name": "BOS Guarantee Cap"},
    )
    licensor = setup["licensor"]
    order = create_order(
        api, setup["run"], channel="ECOM",
        destination_code="ECOM-BOS-G0", quantity=2500,
    )
    deliver_flow(api, setup["run"]["id"], order, 2500, "pick-g0")

    headers = make_licensing_ops_headers(licensor["id"])
    read = get_licensor(api, licensor["id"], headers)
    return setup, licensor, headers, read


def test_applying_then_reversing_restores_the_ledger_triple(api):
    """PRD §3.9: "the licensor's accrued royalty is set back to the settlement's
    `snapped_accrued_cents`, the recovery block is reduced by the settlement's
    recorded `guarantee_shortfall_cents`, and the unsettled amount is recomputed
    from the invariant."
    PRD §3.9: "applying a settlement and then reversing it returns the three
    ledger quantities to precisely the values observed before the application,
    with no drift"

    Design: Difficulty/compensating_invariant/minimum_guarantee_reversal_restores_ledger_triple
    """
    set_clock(api)
    setup, licensor, headers, before = _licensor_with_accrual(api, 2000)

    assert before["accrued_royalty_cents"] == 843.75
    assert before["guarantee_recovery_block_cents"] == 0
    assert before["accrued_unsettled_cents"] == 843.75

    applied = validate_success(
        api.apply_settlement(
            licensor["id"],
            {
                "expected_licensor_version": before["version"],
                "reserved_cents": 100,
                "accept_guarantee_breach": True,
            },
            headers,
        ),
        expected_status=201,
    )
    assert applied["status"] == "APPROVED"
    assert applied["snapped_accrued_cents"] == 843.75
    assert applied["reserved_cents"] == 100

    validate_success(
        api.reverse_settlement(
            licensor["id"],
            {"expected_licensor_version": applied["licensor_version"]},
            headers,
        ),
        expected_status=200,
    )

    after = get_licensor(api, licensor["id"], headers)
    assert after["accrued_royalty_cents"] == 843.75
    assert after["guarantee_recovery_block_cents"] == 0
    assert after["accrued_unsettled_cents"] == 843.75
    assert (
        after["accrued_royalty_cents"]
        + after["guarantee_recovery_block_cents"]
        + after["accrued_unsettled_cents"]
    ) == (
        before["accrued_royalty_cents"]
        + before["guarantee_recovery_block_cents"]
        + before["accrued_unsettled_cents"]
    )


def test_the_recorded_shortfall_and_the_post_settlement_ledger(api):
    """PRD §3.9: "With an accrued royalty of 843.75 cents, a guarantee of 2000
    cents, a reserve of 100 cents and the breach accepted, the post-settlement
    accrued figure is 743.75, the shortfall is 1256.25, the snapped figure is
    843.75 and the recoverable figure is 843.75, so the licensor's accrued royalty
    becomes 743.75, its recovery block becomes 1256.25 and its unsettled amount
    recomputes to 0."

    Design: Difficulty/compensating_invariant/minimum_guarantee_reversal_restores_ledger_triple
    """
    set_clock(api)
    setup, licensor, headers, before = _licensor_with_accrual(api, 2000)
    assert before["accrued_royalty_cents"] == 843.75

    applied = validate_success(
        api.apply_settlement(
            licensor["id"],
            {
                "expected_licensor_version": before["version"],
                "reserved_cents": 100,
                "accept_guarantee_breach": True,
            },
            headers,
        ),
        expected_status=201,
    )

    assert applied["guarantee_shortfall_cents"] == 1256.25
    assert applied["max_recoverable_early_cents"] == 843.75

    ledger = get_licensor(api, licensor["id"], headers)
    assert ledger["accrued_royalty_cents"] == 743.75
    assert ledger["guarantee_recovery_block_cents"] == 1256.25
    assert ledger["accrued_unsettled_cents"] == 0


def test_a_breach_without_the_flag_is_refused_and_reports_the_shortfall(api):
    """PRD §3.9: "If that post-settlement figure is below the contract's
    `minimum_guarantee_cents` while `accept_guarantee_breach` is false, the request
    is rejected with `ERR_GUARANTEE_FLOOR_BREACH` (HTTP 422) and the message
    carries the exact shortfall"

    Design: Corner/validations/settlement_below_floor_requires_the_breach_flag
    """
    set_clock(api)
    setup, licensor, headers, before = _licensor_with_accrual(api, 2000)
    assert before["accrued_royalty_cents"] == 843.75

    resp = api.apply_settlement(
        licensor["id"],
        {
            "expected_licensor_version": before["version"],
            "reserved_cents": 100,
            "accept_guarantee_breach": False,
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_FLOOR_BREACH,
                   expected_status=422)
    assert "1256.25" in resp.json()["data"]["message"]

    # The rejected call leaves the version where it was, so the same anchor is
    # still current for a retry.
    unchanged = get_licensor(api, licensor["id"], headers)
    assert unchanged["version"] == before["version"]
    assert unchanged["accrued_royalty_cents"] == 843.75


def test_the_same_numbers_are_accepted_once_the_breach_is_elected(api):
    """PRD §3.9: "With the breach accepted, the recorded figures are written in
    this order: `snapped_accrued_cents` takes the licensor's accrued royalty as it
    stood before the settlement, `guarantee_shortfall_cents` takes the shortfall
    just computed"

    Design: Corner/validations/settlement_below_floor_requires_the_breach_flag
    """
    set_clock(api)
    setup, licensor, headers, before = _licensor_with_accrual(api, 2000)

    refused = api.apply_settlement(
        licensor["id"],
        {
            "expected_licensor_version": before["version"],
            "reserved_cents": 100,
            "accept_guarantee_breach": False,
        },
        headers,
    )
    validate_error(refused, ApiErrorId.ERR_GUARANTEE_FLOOR_BREACH)

    accepted = validate_success(
        api.apply_settlement(
            licensor["id"],
            {
                "expected_licensor_version": before["version"],
                "reserved_cents": 100,
                "accept_guarantee_breach": True,
            },
            headers,
        ),
        expected_status=201,
    )

    assert accepted["guarantee_shortfall_cents"] == 1256.25
    ledger = get_licensor(api, licensor["id"], headers)
    assert ledger["accrued_royalty_cents"] == 743.75
    assert ledger["guarantee_recovery_block_cents"] == 1256.25


def test_a_settlement_with_no_unsettled_accrual_is_refused(api):
    """PRD §3.9: "The licensor must have a strictly positive unsettled amount, and
    the reserved amount must not exceed it; a settlement attempted with no
    unsettled accrual at all ... is rejected with `ERR_NO_ACCRUED_ROYALTY`
    (HTTP 422)."

    Design: Corner/validations/settlement_requires_a_positive_unsettled_accrual
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor T",
                               minimum_guarantee_cents=100000)
    headers = make_licensing_ops_headers(licensor["id"])

    resp = api.apply_settlement(
        licensor["id"],
        {
            "expected_licensor_version": licensor["version"],
            "reserved_cents": 100,
            "accept_guarantee_breach": True,
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACCRUED_ROYALTY, expected_status=422)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_GUARANTEE_FLOOR_BREACH


def test_a_settlement_that_moves_nothing_is_refused(api):
    """PRD §3.9: "a settlement that would reserve nothing while leaving the accrued
    royalty, the recovery block and the unsettled amount all unchanged moves no
    royalty at all and is rejected with `ERR_SETTLEMENT_NOOP` (HTTP 422) rather
    than being recorded as an empty event."

    Design: Corner/validations/settlement_noop_is_rejected
    """
    set_clock(api)
    setup = committed_run(
        api, base_qty=2000,
        licensor_overrides={"name": "Licensor S2", "minimum_guarantee_cents": 0},
        design_overrides={"team_code": "BOS", "garment_sku": "CAP",
                          "design_name": "S2 Cap"},
    )
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-5", quantity=250)
    deliver_flow(api, setup["run"]["id"], order, 250, "pick-s")

    headers = make_licensing_ops_headers(setup["licensor"]["id"])
    ledger = get_licensor(api, setup["licensor"]["id"], headers)
    assert ledger["accrued_royalty_cents"] == 84.38

    resp = api.apply_settlement(
        setup["licensor"]["id"],
        {
            "expected_licensor_version": ledger["version"],
            "reserved_cents": 0,
            "accept_guarantee_breach": True,
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOOP, expected_status=422)

    after = get_licensor(api, setup["licensor"]["id"], headers)
    assert after["accrued_royalty_cents"] == 84.38
    assert after["guarantee_recovery_block_cents"] == 0
    assert after["accrued_unsettled_cents"] == 84.38


def test_a_stale_licensor_version_blocks_the_settlement(api):
    """PRD §2.8: "A minimum-guarantee settlement must carry
    `expected_licensor_version`, the client's last-observed `version` of the
    `Licensor`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/settlement_with_stale_licensor_version_is_rejected
    """
    set_clock(api)
    setup = committed_run(
        api, base_qty=2000,
        licensor_overrides={"name": "Licensor AK", "royalty_rate_pct": 0.1},
    )
    run_id = setup["run"]["id"]
    headers = make_licensing_ops_headers(setup["licensor"]["id"])

    first = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-13", quantity=250)
    deliver_flow(api, run_id, first, 250, "pick-ak1")
    stale = get_licensor(api, setup["licensor"]["id"], headers)

    second = create_order(api, setup["run"], channel="ECOM",
                          destination_code="ECOM-ATL-14", quantity=250)
    deliver_flow(api, run_id, second, 250, "pick-ak2")

    resp = api.apply_settlement(
        setup["licensor"]["id"],
        {
            "expected_licensor_version": stale["version"],
            "reserved_cents": 100,
            "accept_guarantee_breach": True,
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    after = get_licensor(api, setup["licensor"]["id"], headers)
    assert after["guarantee_recovery_block_cents"] == 0


def test_reversing_without_an_approved_settlement_is_refused(api):
    """PRD §3.9: "Reversal is permitted only where an approved settlement exists to
    reverse — an attempt with none is rejected with `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/errors/settlement_reversal_requires_an_approved_settlement
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor AC")
    headers = make_licensing_ops_headers(licensor["id"])

    resp = api.reverse_settlement(
        licensor["id"],
        {"expected_licensor_version": licensor["version"]},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    read = get_licensor(api, licensor["id"], headers)
    assert read["accrued_royalty_cents"] == 0
    assert read["guarantee_recovery_block_cents"] == 0


def test_a_foreign_operator_cannot_settle_another_licensors_ledger(api):
    """PRD §2.1: "a `LicensingOps` caller may record a licensor decision only on a
    design whose `licensor_id` equals its own identifier and may settle only the
    licensor it identifies; acting on any other rights holder is rejected with
    `ERR_LICENSOR_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/licensor_bound_operator_cannot_settle_a_foreign_licensor
    """
    set_clock(api)
    setup = committed_run(
        api, base_qty=2000,
        licensor_overrides={"name": "Licensor AF", "royalty_rate_pct": 0.1},
    )
    foreign = create_licensor(api, name="Licensor AG", league_code="NBLM",
                              royalty_rate_pct=0.1, minimum_guarantee_cents=100)

    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-6", quantity=250)
    deliver_flow(api, setup["run"]["id"], order, 250, "pick-af")

    owner_headers = make_licensing_ops_headers(setup["licensor"]["id"])
    ledger = get_licensor(api, setup["licensor"]["id"], owner_headers)

    resp = api.apply_settlement(
        setup["licensor"]["id"],
        {
            "expected_licensor_version": ledger["version"],
            "reserved_cents": 100,
            "accept_guarantee_breach": True,
        },
        make_licensing_ops_headers(foreign["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LICENSOR_MISMATCH, expected_status=403)

    untouched = get_licensor(api, setup["licensor"]["id"], owner_headers)
    assert untouched["accrued_unsettled_cents"] == ledger["accrued_unsettled_cents"]