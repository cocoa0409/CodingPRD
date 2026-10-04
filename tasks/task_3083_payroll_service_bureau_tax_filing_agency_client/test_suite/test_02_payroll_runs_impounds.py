"""Payroll run and impound lifecycle tests (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_deposit,
    create_run,
    create_settled_run,
    fail_impound,
    get_client,
    get_deposit,
    get_run,
    get_success_data,
    impound_run,
    make_client_admin_headers,
    setup_active_client,
    submit_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_payroll_run_get_round_trips_and_computes_impound_amount():
    """PRD §3.4: "the system computes `impound_amount_cents` as the sum of
    `gross_pay_cents` and `total_tax_cents` — integer cents, no rounding."

    Design: Corner/entities/e_payroll_run_get_round_trips_and_computes_impound_amount
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
        gross_pay_cents=1000000,
        total_tax_cents=200000,
    )
    fetched = validate_success(
        api_client.get_payroll_run(run["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert fetched["gross_pay_cents"] == 1000000
    assert fetched["total_tax_cents"] == 200000
    assert fetched["impound_amount_cents"] == 1200000
    assert fetched["status"] == "DRAFT"
    assert fetched["version"] == 1


def test_run_initial_state_is_draft_without_funding_model():
    """PRD §3.4: "The run starts in `DRAFT` status."
    PRD §3.4: "At submission the run's effective `funding_model` is computed:
    `WIRE_REQUIRED` when the client's `risk_posture` is `HIGH`, otherwise
    `STANDARD`."

    Design: Corner/state_machines/sm_run_initial_state_is_draft
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    assert run["status"] == "DRAFT"
    assert run["version"] == 1
    assert run.get("funding_model") in (None, ""), (
        "funding_model is computed at submit, not at create"
    )


def test_submit_computes_standard_funding_model_for_normal_client():
    """PRD §3.4: "At submission the run's effective `funding_model` is computed:
    `WIRE_REQUIRED` when the client's `risk_posture` is `HIGH`, otherwise
    `STANDARD`."

    Design: Corner/state_machines/sm_run_initial_state_is_draft
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submitted = submit_run(client, run)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["funding_model"] == "STANDARD"


def test_run_create_missing_total_tax_returns_invalid_request():
    """PRD §2.8: "required fields present, enum values within their declared
    domain, integer cents fields non-negative, and `period_end` not earlier than
    `period_start` — with failures rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/e_run_create_missing_total_tax_returns_invalid_request
    """
    setup = setup_active_client()
    client = setup["client"]
    payload = {
        "client_id": client["id"],
        "pay_date": "2026-09-04T00:00:00Z",
        "period_start": "2026-08-22T00:00:00Z",
        "period_end": "2026-09-04T00:00:00Z",
        "gross_pay_cents": 1000000,
    }
    resp = api_client.create_payroll_run(payload, make_client_admin_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(
        api_client.list_payroll_runs(
            TEST_USERS["filer_alpha_headers"], params={"client_id": client["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_run_create_missing_gross_pay_returns_invalid_request():
    """PRD §2.8: "required fields present, enum values within their declared
    domain, integer cents fields non-negative, and `period_end` not earlier than
    `period_start` — with failures rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/e_run_create_missing_total_tax_returns_invalid_request
    """
    setup = setup_active_client()
    client = setup["client"]
    payload = {
        "client_id": client["id"],
        "pay_date": "2026-09-04T00:00:00Z",
        "period_start": "2026-08-22T00:00:00Z",
        "period_end": "2026-09-04T00:00:00Z",
        "total_tax_cents": 200000,
    }
    resp = api_client.create_payroll_run(payload, make_client_admin_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_run_create_impound_amount_input_ignored():
    """PRD §3.4: "the system computes `impound_amount_cents` as the sum of
    `gross_pay_cents` and `total_tax_cents` — integer cents, no rounding."

    Design: Corner/entities/e_run_create_impound_amount_input_ignored
    """
    setup = setup_active_client()
    client = setup["client"]
    payload = {
        "client_id": client["id"],
        "pay_date": "2026-09-04T00:00:00Z",
        "period_start": "2026-08-22T00:00:00Z",
        "period_end": "2026-09-04T00:00:00Z",
        "gross_pay_cents": 1000000,
        "total_tax_cents": 200000,
        "impound_amount_cents": 999,
    }
    resp = api_client.create_payroll_run(payload, make_client_admin_headers(client["id"]))
    run = validate_success(resp, expected_status=201)
    assert run["impound_amount_cents"] == 1200000, (
        "impound_amount_cents is computed server-side; the supplied 999 must be ignored"
    )


def test_run_create_inverted_period_returns_invalid_request():
    """PRD §3.4: "the run's `period_end` must not precede its `period_start`."
    PRD §2.8: "...and `period_end` not earlier than `period_start` — with failures
    rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/e_run_create_inverted_period_returns_invalid_request
    """
    setup = setup_active_client()
    client = setup["client"]
    payload = {
        "client_id": client["id"],
        "pay_date": "2026-09-04T00:00:00Z",
        "period_start": "2026-09-04T00:00:00Z",
        "period_end": "2026-08-22T00:00:00Z",
        "gross_pay_cents": 1000000,
        "total_tax_cents": 200000,
    }
    resp = api_client.create_payroll_run(payload, make_client_admin_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(
        api_client.list_payroll_runs(
            TEST_USERS["filer_alpha_headers"], params={"client_id": client["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_initiate_impound_action_creates_child():
    """PRD §3.4: "It creates an Impound in `PENDING` status whose `amount_cents`
    equals the run's `impound_amount_cents`, whose `initiated_at` is the logical
    clock's current instant, and whose `due_by` deadline depends on the run's
    funding model: for `STANDARD` funding, `due_by` is `initiated_at` plus 2
    business days (rolling forward over Saturdays and Sundays only — a Friday
    initiation lands the deadline on the following Tuesday)."

    Design: Corner/endpoints/ep_initiate_impound_action_creates_child
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client, gross_pay_cents=1000000, total_tax_cents=200000)
    submit_run(client, run)
    # Default logical clock is Tuesday 2026-09-01; +2 business days = 2026-09-03.
    resp = api_client.initiate_impound(
        run["id"],
        get_client(client["id"])["version"],
        make_client_admin_headers(client["id"]),
    )
    imp = validate_success(resp, expected_status=201)
    assert imp["amount_cents"] == 1200000
    assert imp["status"] == "PENDING"
    assert imp["due_by"][:10] == "2026-09-03"
    assert get_run(run["id"])["status"] == "IMPOUNDED"


def test_initiate_impound_amount_equals_impound_amount_cents():
    """PRD §3.4: "It creates an Impound in `PENDING` status whose `amount_cents`
    equals the run's `impound_amount_cents`."

    Design: Corner/endpoints/ep_initiate_impound_action_creates_child
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client, gross_pay_cents=750000, total_tax_cents=150000)
    submit_run(client, run)
    imp = impound_run(client, run)
    assert imp["amount_cents"] == 900000
    assert imp["status"] == "PENDING"
    assert imp["payroll_run_id"] == run["id"]
    assert imp["client_id"] == client["id"]


def test_cancel_settled_run_returns_invalid_state():
    """PRD §3.4: "A `SUBMITTED` run may still be cancelled outright, moving it to
    `CANCELLED`."
    PRD §2.8: "any state-transition endpoint verifies the target resource is in a
    state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sm_cancel_settled_run_returns_invalid_state
    """
    setup = setup_active_client()
    client = setup["client"]
    built = create_settled_run(client)
    run = built["run"]
    resp = api_client.cancel_run(run["id"], make_client_admin_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_run(run["id"])["status"] == "SETTLED"


def test_cancel_draft_run_returns_invalid_state():
    """PRD §3.4: "A `SUBMITTED` run may still be cancelled outright, moving it to
    `CANCELLED`."
    PRD §2.8: "any state-transition endpoint verifies the target resource is in a
    state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sm_cancel_settled_run_returns_invalid_state
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    resp = api_client.cancel_run(run["id"], make_client_admin_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_run(run["id"])["status"] == "DRAFT"


def test_failed_impound_rejects_settle_terminal_lockdown():
    """PRD §3.4: "A bank NSF return fails a `PENDING` impound directly: the
    impound moves to `FAILED`."
    PRD §2.8: "any state-transition endpoint verifies the target resource is in a
    state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sm_failed_impound_rejects_settle_terminal_lockdown
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    fail_impound(imp)
    resp = api_client.settle_impound(imp["id"], TEST_USERS["treasury_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    fetched = get_success_data(
        api_client.get_impound(imp["id"], TEST_USERS["treasury_headers"])
    )
    assert fetched["status"] == "FAILED"
    assert get_client(client["id"])["funding_failure_count"] == 1


def test_failed_impound_also_rejects_second_fail():
    """PRD §3.4: "A bank NSF return fails a `PENDING` impound directly: the
    impound moves to `FAILED`."
    PRD §2.8: "any state-transition endpoint verifies the target resource is in a
    state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sm_failed_impound_rejects_settle_terminal_lockdown
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    fail_impound(imp)
    resp = api_client.fail_impound(imp["id"], TEST_USERS["treasury_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    # Strike count unchanged by the rejected second fail.
    assert get_client(client["id"])["funding_failure_count"] == 1


def test_second_settle_rejected_and_settled_at_unchanged():
    """PRD §3.4: "Settling an impound moves it from `PENDING` to `SETTLED`, stamps
    `settled_at`, moves the owning run from `IMPOUNDED` to `SETTLED`."
    PRD §2.8: "any state-transition endpoint verifies the target resource is in a
    state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sm_settle_is_idempotent_unsafe_second_settle_rejected
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    settled = validate_success(
        api_client.settle_impound(imp["id"], TEST_USERS["treasury_headers"])
    )
    first_settled_at = settled["settled_at"]
    resp = api_client.settle_impound(imp["id"], TEST_USERS["treasury_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    fetched = get_success_data(
        api_client.get_impound(imp["id"], TEST_USERS["treasury_headers"])
    )
    assert fetched["settled_at"] == first_settled_at
    assert fetched["status"] == "SETTLED"


def test_settle_side_effects_visible_immediately():
    """PRD §3.4: "Settling an impound moves it from `PENDING` to `SETTLED`, stamps
    `settled_at`, moves the owning run from `IMPOUNDED` to `SETTLED`, and closes
    the bureau's float window for that run."
    PRD §2.10: "State changes propagate across aggregate boundaries, and the
    server performs these reconciliations automatically without an explicit client
    request on the affected resource."

    Design: Corner/consistency_model/k_impound_side_effects_visible_in_same_response
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    settled = validate_success(
        api_client.settle_impound(imp["id"], TEST_USERS["treasury_headers"])
    )
    assert settled["status"] == "SETTLED"
    assert settled.get("settled_at"), "settled_at must be stamped in the response"
    assert get_run(run["id"])["status"] == "SETTLED"


def test_settle_updates_run_and_refreshes_versions():
    """PRD §2.10: "Each of these cascades increments the `version` and refreshes
    the `updated_at` of every resource it touches."
    PRD §3.4: "Settling an impound moves it from `PENDING` to `SETTLED`, stamps
    `settled_at`, moves the owning run from `IMPOUNDED` to `SETTLED`."

    Design: Corner/consistency_model/k_impound_side_effects_visible_in_same_response
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    run_before = get_run(run["id"])
    settled = validate_success(
        api_client.settle_impound(imp["id"], TEST_USERS["treasury_headers"])
    )
    run_after = get_run(run["id"])
    assert settled["status"] == "SETTLED"
    assert run_after["status"] == "SETTLED"
    assert run_after["version"] == run_before["version"] + 1


def test_reverse_run_rejected_when_impound_settled():
    """PRD §3.4: "reversing a run whose impound has already settled is rejected
    with `ERR_INVALID_STATE` (HTTP 409), because a settled run can no longer be
    unwound this way."

    Design: Corner/state_machines/sm_cancel_settled_run_returns_invalid_state
    """
    setup = setup_active_client()
    client = setup["client"]
    built = create_settled_run(client)
    resp = api_client.reverse_run(built["run"]["id"], TEST_USERS["treasury_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_run(built["run"]["id"])["status"] == "SETTLED"


def test_cross_client_submit_forbidden():
    """PRD §2.1: "When `X-User-Role` is `ClientPayrollAdmin`, `X-User-ID` is the
    `id` of the acting `Client`; the header value must equal the `client_id` of the
    client aggregate being touched, and a mismatch on any client-scoped endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/endpoints/ep_cross_client_submit_forbidden
    """
    from test_helpers import create_client as _create_client

    setup = setup_active_client()
    client_a = setup["client"]
    run = create_run(client_a)
    other = _create_client(legal_name="Other Client")
    resp = api_client.submit_run(run["id"], make_client_admin_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert get_run(run["id"])["status"] == "DRAFT"


def test_cross_client_initiate_impound_forbidden():
    """PRD §2.1: "When `X-User-Role` is `ClientPayrollAdmin`, `X-User-ID` is the
    `id` of the acting `Client`; the header value must equal the `client_id` of the
    client aggregate being touched, and a mismatch on any client-scoped endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/endpoints/ep_cross_client_submit_forbidden
    """
    from test_helpers import client_version
    from test_helpers import create_client as _create_client

    setup = setup_active_client()
    client_a = setup["client"]
    run = create_run(client_a)
    submit_run(client_a, run)
    other = _create_client(legal_name="Other Client Two")
    resp = api_client.initiate_impound(
        run["id"], client_version(client_a["id"]), make_client_admin_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert get_run(run["id"])["status"] == "SUBMITTED"


def test_deposit_create_bogus_jurisdiction_returns_not_found():
    """PRD §2.8: "path and body resource identifiers must correspond to existing
    resources, validated left-to-right with path identifiers checked before body
    identifiers and body identifiers checked in their declared input order, and the
    first missing identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/e_deposit_create_bogus_jurisdiction_returns_not_found
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client)
    run = built["run"]
    resp = api_client.create_deposit(
        run["id"],
        {
            "jurisdiction_id": NON_EXISTENT_UUID,
            "amount_cents": 100000,
            "expected_payroll_run_version": run["version"],
        },
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    _, meta = validate_paginated(
        api_client.list_deposits(
            TEST_USERS["filer_alpha_headers"], params={"payroll_run_id": run["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_deposit_get_unknown_id_returns_not_found():
    """PRD §2.8: "path and body resource identifiers must correspond to existing
    resources, validated left-to-right with path identifiers checked before body
    identifiers and body identifiers checked in their declared input order, and the
    first missing identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/e_deposit_get_unknown_id_returns_not_found
    """
    resp = api_client.get_deposit(NON_EXISTENT_UUID, TEST_USERS["filer_alpha_headers"])
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    assert "error_id" in err and "message" in err
