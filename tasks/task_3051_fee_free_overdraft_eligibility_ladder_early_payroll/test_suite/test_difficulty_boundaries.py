"""Depth tests for numeric boundaries and overlap-window geometry."""

import test_helpers as th
from test_helpers import fixtures


def _setup_boundary_deposits(api):
    """Member with tenure 365d and three settled PAYROLL deposits of 9999,
    10000 and 10000 cents."""
    member = fixtures.create_member(
        api, external_ref="m11", full_name="M Eleven", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    deposits = []
    for i, (amount, date) in enumerate(
        [
            (9999, "2026-08-07T00:00:00Z"),
            (10000, "2026-08-14T00:00:00Z"),
            (10000, "2026-08-21T00:00:00Z"),
        ],
        start=1,
    ):
        dep = fixtures.register_deposit(
            api,
            account["id"],
            originator_id="EMP11",
            originator_type="PAYROLL",
            amount_cents=amount,
            settlement_date=date,
            trace_id=f"m11-t{i}",
        )
        fixtures.settle_deposit(api, dep["id"])
        deposits.append(dep)
    return {"member": member, "account": account, "deposits": deposits}


def test_qualifying_amount_inclusive_boundary(api):
    """PRD §3.2: "The **regularity component** counts qualifying deposits in the
    window — a deposit qualifies when its `originator_type` is `PAYROLL` and its
    `amount_cents` is at least 10000 (the one-hundred-dollar boundary is
    inclusive; the qualifying flag is recorded on the deposit as `qualifying`)."

    Design: Difficulty/boundary_precision_check/qualifying_amount_inclusive_boundary
    """
    w = _setup_boundary_deposits(api)
    for dep, expected in zip(w["deposits"], [False, True, True]):
        current = th.get_success_data(api.get_deposit(dep["id"], th.TEST_USERS["program_ops"]))
        assert current["qualifying"] is expected, (
            f"amount {current['amount_cents']}: qualifying {current['qualifying']}"
        )


def test_qualifying_boundary_drives_bucket_count(api):
    """PRD §3.2: "Six or more qualifying deposits earn 400 points, four or five
    earn 300, two or three earn 150, and fewer than two earn zero."
    PRD §3.2: "The **tenure component**, stored as `tenure_points`, grants up to
    250 points for a full year of tenure: the member's `tenure_days` capped at
    365, divided by 365, multiplied by 250, and rounded half-up to a whole
    point."

    Design: Difficulty/boundary_precision_check/qualifying_amount_inclusive_boundary
    """
    w = _setup_boundary_deposits(api)
    profile = fixtures.evaluate(api, w["member"]["id"], mode="BATCH")
    assert profile["regularity_points"] == 150, f"profile: {profile}"
    assert profile["tenure_points"] == 250
    assert profile["score"] == 400


def _setup_discrepancy_run_a(api):
    """One settled 15000 deposit in window [08-01, 08-08); run A over that
    window with bank_reported_net -15000 -> DISCREPANCY."""
    member = fixtures.create_member(
        api, external_ref="m20", full_name="M Twenty", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMP20",
        originator_type="PAYROLL",
        amount_cents=15000,
        settlement_date="2026-08-14T00:00:00Z",
        trace_id="m20-t1",
    )
    fixtures.settle_deposit(api, dep["id"])
    run_a = th.get_success_data(
        api.create_reconciliation_run(
            th.factories.reconciliation_run_payload(
                sponsor_bank_code="SB-1",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-08T00:00:00Z",
                bank_reported_net_cents=-15000,
            ),
            th.TEST_USERS["sponsor_bank_ops"],
        )
    )
    return member, account, run_a


def test_recon_window_half_open_adjacency_allowed(api):
    """PRD §3.7: "Two runs for the same sponsor bank may not have overlapping
    windows while either is non-terminal (`OPEN` or `DISCREPANCY`); adjacency —
    one run's `period_end` equal to another's `period_start` — is allowed, and
    an overlapping request is refused with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/recon_window_half_open_adjacency
    """
    _member, _account, run_a = _setup_discrepancy_run_a(api)
    assert run_a["status"] == "DISCREPANCY"

    resp = api.create_reconciliation_run(
        th.factories.reconciliation_run_payload(
            sponsor_bank_code="SB-1",
            period_start="2026-08-08T00:00:00Z",
            period_end="2026-08-15T00:00:00Z",
            bank_reported_net_cents=0,
        ),
        th.TEST_USERS["sponsor_bank_ops"],
    )
    run_b = th.validate_success(resp, expected_status=201)
    th.assert_reconciliation_run(run_b)


def _setup_inflight_deposit(api):
    """Member with an account holding one in-flight deposit settling
    2026-09-10 for originator EMP17."""
    member = fixtures.create_member(
        api, external_ref="m17", full_name="M Seventeen", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMP17",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-10T00:00:00Z",
        trace_id="m17-t1",
    )
    return member, account, dep


def test_deposit_inflight_buffer_conflict(api):
    """PRD §3.4: "Overlap is judged per account and originator: if an in-flight
    deposit — one in `RECEIVED_FILE` or `POSTED_EARLY` — exists for the same
    account and `originator_id` whose `settlement_date` lies within three days
    of the new deposit's settlement date in either direction, the new
    registration conflicts. A gap of exactly three days is a conflict; four
    days or more is allowed."

    Design: Difficulty/resource_temporal_overlap/deposit_inflight_buffer_conflict
    """
    _member, account, _dep = _setup_inflight_deposit(api)

    # Distance 4 days: allowed.
    resp = api.create_deposit(
        account["id"],
        th.factories.deposit_payload(
            originator_id="EMP17",
            amount_cents=10000,
            settlement_date="2026-09-14T00:00:00Z",
            trace_id="m17-t2",
        ),
        th.TEST_USERS["sponsor_bank_ops"],
    )
    th.validate_success(resp, expected_status=201)

    # Distance 3 days: conflict.
    resp = api.create_deposit(
        account["id"],
        th.factories.deposit_payload(
            originator_id="EMP17",
            amount_cents=10000,
            settlement_date="2026-09-13T00:00:00Z",
            trace_id="m17-t3",
        ),
        th.TEST_USERS["sponsor_bank_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_WINDOW_OVERLAP)
    assert resp.status_code == 409

    # One day away but a different originator: allowed.
    resp = api.create_deposit(
        account["id"],
        th.factories.deposit_payload(
            originator_id="EMP-OTHER",
            amount_cents=10000,
            settlement_date="2026-09-11T00:00:00Z",
            trace_id="m17-t4",
        ),
        th.TEST_USERS["sponsor_bank_ops"],
    )
    th.validate_success(resp, expected_status=201)


def test_deposit_inflight_buffer_conflict_leaves_no_row(api):
    """PRD §3.4: "Registration always creates the deposit in `RECEIVED_FILE`
    status; an overlapping registration is refused outright with
    `ERR_WINDOW_OVERLAP` rather than persisted in any rejected state."

    Design: Difficulty/resource_temporal_overlap/deposit_inflight_buffer_conflict
    """
    _member, account, _dep = _setup_inflight_deposit(api)
    resp = api.create_deposit(
        account["id"],
        th.factories.deposit_payload(
            originator_id="EMP17",
            amount_cents=10000,
            settlement_date="2026-09-13T00:00:00Z",
            trace_id="m17-t3",
        ),
        th.TEST_USERS["sponsor_bank_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_WINDOW_OVERLAP)

    data, meta = th.validate_paginated(
        api.list_deposits(account["id"], th.TEST_USERS["program_ops"])
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["settlement_date"].startswith("2026-09-10")
