"""Settlement files: per-line fees, sweep conservation, lifecycle (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_transponder,
    create_away_agency,
    generate_settlement_file,
    get_settlement_file,
    get_success_data,
    setup_agency_pair,
    setup_full_account,
    setup_three_trips_101_202_303,
    validate_error,
    validate_paginated,
    validate_success,
)

SO = TEST_USERS["settlement_officer_headers"]
AO = TEST_USERS["agency_ops_headers"]
VO = TEST_USERS["violations_officer_headers"]


def test_settlement_fee_per_line_vs_aggregate_rounding():
    """PRD §3.9: "The reciprocity fee is computed per line: each line
    contributes its `charged_amount_cents` multiplied by the to-agency's
    `reciprocity_fee_bps`, divided by ten thousand, rounded half-up to whole
    cents — and `fee_amount_cents` is the sum of those per-line fees. Computing
    the fee on the aggregate gross instead is an explicitly rejected
    alternative: the two conventions diverge by one or more cents on many
    multi-line files, and the per-line convention is the normative one."

    Design: Difficulty/dual_variant_calc/settlement_fee_per_line_vs_aggregate_rounding
    """
    ctx = setup_three_trips_101_202_303(tag_number="TAG-A")
    sf = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])

    assert sf["line_count"] == 3
    assert sf["gross_amount_cents"] == 606
    # Per-line round_half_up: rhu(101*150/10000)=2, rhu(202*...)=3,
    # rhu(303*...)=5 -> 10. Aggregate would give rhu(606*0.015)=9.
    assert sf["fee_amount_cents"] == 10
    assert sf["net_amount_cents"] == 596


def test_settlement_sweep_conserves_line_total():
    """PRD §3.9: "`net_amount_cents`, the amount the from-agency owes the
    to-agency, is the gross minus the fee."
    PRD §3.9: "The sweep claims every toll transaction that is in `POSTED`
    status with `settlement_file_id` still null, whose `away_agency_id` is the
    to-agency, and whose account's home agency is the from-agency... Each
    claimed line moves from `POSTED` to `SETTLED` and has its
    `settlement_file_id` set."

    Design: Difficulty/compensating_invariant/settlement_sweep_conserves_line_total
    """
    ctx = setup_three_trips_101_202_303(tag_number="TAG-W")
    sf1 = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])
    assert sf1["gross_amount_cents"] == 606
    assert sf1["fee_amount_cents"] + sf1["net_amount_cents"] == sf1["gross_amount_cents"]

    for txn in ctx["txns"]:
        settled = get_success_data(api_client.get_toll_transaction(txn["id"], AO))
        assert settled["status"] == "SETTLED"
        assert settled["settlement_file_id"] == sf1["id"]

    sf2 = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])
    assert sf2["line_count"] == 0
    assert sf2["gross_amount_cents"] == 0
    assert sf2["net_amount_cents"] == 0


def test_settlement_full_lifecycle_and_exception_gate():
    """PRD §3.9: "From `GENERATED` the officer transmits the file, moving it to
    `TRANSMITTED`... If the receiver finds problems, they flag an exception
    with a free-text `reason`, moving the file from `TRANSMITTED` to
    `DISPUTED_SETTLEMENT` and incrementing `exception_count` once per flag.
    Resolving exceptions moves the file from `DISPUTED_SETTLEMENT` to
    `ACKNOWLEDGED` and resets `exception_count` to zero. Reconciliation is the
    terminal step: an `ACKNOWLEDGED` file with zero exceptions moves to
    `RECONCILED`, marking `net_amount_cents` as transferred from the from-agency
    to the to-agency; attempting to reconcile while `exception_count` is
    greater than zero is rejected with `ERR_SETTLEMENT_HAS_EXCEPTIONS`."

    Design: Corner/endpoints/settlement_full_lifecycle_and_exception_gate
    """
    ctx = setup_full_account(tag_number="TAG-SET", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-SET", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-18T09:00:00Z", "is_peak": False,
             "idempotency_key": "s1"}, AO,
        )
    )
    sf = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])
    sf_id = sf["id"]
    # one line charged 800, fee rhu(800*0.015)=12, net 788.
    get_success_data(api_client.transmit_settlement_file(sf_id, SO))

    flagged = get_success_data(api_client.flag_settlement_exception(sf_id, {"reason": "line 1 amount mismatch"}, SO))
    assert flagged["status"] == "DISPUTED_SETTLEMENT"
    assert flagged["exception_count"] == 1

    # Acknowledge is only valid from TRANSMITTED; the file is DISPUTED_SETTLEMENT.
    resp_ack = api_client.acknowledge_settlement_file(sf_id, SO)
    validate_error(resp_ack, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    resolved = get_success_data(api_client.resolve_settlement_exceptions(sf_id, SO))
    assert resolved["status"] == "ACKNOWLEDGED"
    assert resolved["exception_count"] == 0

    reconciled = get_success_data(api_client.reconcile_settlement_file(sf_id, SO))
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["net_amount_cents"] == 788


def test_toll_transaction_filtered_list_by_settlement_file():
    """PRD §3.9: "The sweep claims every toll transaction that is in `POSTED`
    status with `settlement_file_id` still null... Each claimed line moves from
    `POSTED` to `SETTLED` and has its `settlement_file_id` set."

    Design: Corner/endpoints/toll_transaction_filtered_list_by_settlement_file
    """
    ctx = setup_full_account(tag_number="TAG-F", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    for ts, key in (("2026-09-19T08:00:00Z", "f1"), ("2026-09-19T09:00:00Z", "f2")):
        get_success_data(
            api_client.post_toll_transaction(
                {"tag_number": "TAG-F", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
                 "trip_timestamp": ts, "is_peak": False, "idempotency_key": key}, AO,
            )
        )
    sf = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])
    t3 = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-F", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-19T10:00:00Z", "is_peak": False,
             "idempotency_key": "f3"}, AO,
        )
    )

    rows, meta = validate_paginated(
        api_client.list_toll_transactions(AO, params={"settlement_file_id": sf["id"]})
    )
    assert len(rows) == 2

    t3_now = get_success_data(api_client.get_toll_transaction(t3["id"], AO))
    assert t3_now["settlement_file_id"] is None
    assert t3_now["status"] == "POSTED"


def test_void_settled_transaction_rejected():
    """PRD §3.9: "Each claimed line moves from `POSTED` to `SETTLED` and has
    its `settlement_file_id` set."
    PRD §4: "Void a posted transaction and credit the account" — voiding acts
    on a POSTED transaction, so a SETTLED one is refused with
    `ERR_TRANSACTION_ALREADY_SETTLED` (PRD §5).

    Design: Corner/errors/void_settled_transaction_rejected
    """
    ctx = setup_full_account(tag_number="TAG-VS", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    txn = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-VS", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-20T09:00:00Z", "is_peak": False,
             "idempotency_key": "vs1"}, AO,
        )
    )
    generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])

    resp = api_client.void_toll_transaction(txn["id"], AO)
    validate_error(resp, ApiErrorId.ERR_TRANSACTION_ALREADY_SETTLED)
    assert get_success_data(api_client.get_toll_transaction(txn["id"], AO))["status"] == "SETTLED"


def test_agency_suspend_blocked_by_pending_settlement():
    """PRD §3.1: "Suspension is refused with `ERR_AGENCY_HAS_PENDING_SETTLEMENT`
    whenever any settlement file naming this agency on either side — as
    collector or as facility provider — is sitting in `GENERATED` or
    `TRANSMITTED` status."
    PRD §3.1: "A `SettlementOfficer` may suspend an agency, moving it from
    `ACTIVE` to `SUSPENDED`."

    Design: Corner/errors/agency_suspend_blocked_by_pending_settlement
    """
    ctx = setup_full_account(tag_number="TAG-PEND", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-PEND", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-22T09:00:00Z", "is_peak": False,
             "idempotency_key": "pd1"}, AO,
        )
    )
    sf = generate_settlement_file(ctx["home"]["id"], ctx["away"]["id"])

    resp1 = api_client.suspend_agency(ctx["away"]["id"], SO)
    validate_error(resp1, ApiErrorId.ERR_AGENCY_HAS_PENDING_SETTLEMENT)

    get_success_data(api_client.transmit_settlement_file(sf["id"], SO))
    get_success_data(api_client.acknowledge_settlement_file(sf["id"], SO))
    get_success_data(api_client.reconcile_settlement_file(sf["id"], SO))

    resp2 = api_client.suspend_agency(ctx["away"]["id"], SO)
    assert resp2.status_code == 200
    assert get_success_data(api_client.get_agency(ctx["away"]["id"], SO))["status"] == "SUSPENDED"


def test_violations_officer_cannot_generate_settlement_files():
    """PRD §4: settlement file generation is listed under SettlementOfficer
    only.
    PRD §2.1: "If the named role is not permitted to call the endpoint, the
    request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/roles/violations_officer_cannot_generate_settlement_files
    """
    home, away = setup_agency_pair()
    resp = api_client.generate_settlement_file(
        {"from_agency_id": home["id"], "to_agency_id": away["id"]}, VO
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
