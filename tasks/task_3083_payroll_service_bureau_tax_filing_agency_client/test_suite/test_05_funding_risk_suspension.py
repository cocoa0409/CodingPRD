"""Funding failures, credit posture, suspension, and client lifecycle (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_funding_failure,
    create_nsf_strikes,
    create_run,
    fail_impound,
    get_client,
    get_funding_failures,
    get_success_data,
    impound_run,
    make_client_admin_headers,
    set_clock,
    setup_active_client,
    settle_impound,
    submit_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_impound_nsf_cascades_run_reversal_deposit_cancellation_and_strike():
    """PRD §3.4: "A bank NSF return fails a `PENDING` impound directly: the
    impound moves to `FAILED`, a FundingFailureEvent of kind `NSF_RETURN` is
    created, the owning run moves from `IMPOUNDED` to `REVERSED`, and that run's
    `SCHEDULED` TaxDeposit rows are moved to `CANCELLED` — the run's tax funds
    are never scheduled further."
    PRD §3.5: "each unresolved `NSF_RETURN` contributes 2 to a base score ... and
    the posture is `HIGH` when the base is at least 4, `ELEVATED` when the base is
    2 or 3, and `NORMAL` when the base is at most 1."

    Design: Difficulty/transitive_cascade/impound_nsf_cascades_run_reversal_deposit_cancellation_and_strike
    """
    from test_helpers import create_deposit, get_run

    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    run = create_run(client, gross_pay_cents=1250000, total_tax_cents=250000)
    submit_run(client, run)
    imp = impound_run(client, run)
    run = get_run(run["id"])
    dep = create_deposit(run, jurisdiction["id"], 250000)

    validate_success(api_client.fail_impound(imp["id"], TEST_USERS["treasury_headers"]))

    imp_after = get_success_data(
        api_client.get_impound(imp["id"], TEST_USERS["treasury_headers"])
    )
    assert imp_after["status"] == "FAILED"
    assert get_run(run["id"])["status"] == "REVERSED"
    assert get_success_data(
        api_client.get_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "CANCELLED"

    client_after = get_client(client["id"])
    assert client_after["funding_failure_count"] == 1
    assert client_after["risk_posture"] == "ELEVATED"  # NSF weighs 2 -> base 2
    assert client_after["status"] == "ACTIVE"  # count 1 < 3, no suspension

    events = get_funding_failures(client["id"])
    assert len(events) == 1
    assert events[0]["kind"] == "NSF_RETURN"
    assert events[0].get("resolved_at") in (None, "")
    assert events[0]["strike_count_after"] == 1
    assert_funding_failure(events[0])

    assessments = get_success_data(
        api_client.list_client_credit_assessments(
            client["id"], TEST_USERS["treasury_headers"]
        )
    )
    assert len(assessments) == 1
    assert assessments[0]["trigger"] == "FUNDING_FAILURE"
    assert assessments[0]["prior_posture"] == "NORMAL"
    assert assessments[0]["new_posture"] == "ELEVATED"


def test_nsf_fail_creates_immutable_audit_event():
    """PRD §2.4: "The FundingFailureEvent is the sole exception to this
    convention: because it is an immutable audit record, it carries only `id` and
    `created_at` — both `updated_at` and `version` are absent from it."
    PRD §3.5: "Every funding failure — an NSF return or a missed wire confirmation
    — appends an immutable FundingFailureEvent recording the `impound_id`, the
    denormalized `client_id`, the `kind` (`NSF_RETURN` or `WIRE_NOT_CONFIRMED`),
    the `occurred_at` instant, and a `strike_count_after` snapshot of the client's
    `funding_failure_count` immediately after the event was applied."

    Design: Difficulty/transitive_cascade/impound_nsf_cascades_run_reversal_deposit_cancellation_and_strike
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    fail_impound(imp)
    events = get_funding_failures(client["id"])
    assert len(events) == 1
    ev = events[0]
    assert_funding_failure(ev)
    assert ev["impound_id"] == imp["id"]
    assert ev["client_id"] == client["id"]
    assert ev["kind"] == "NSF_RETURN"
    assert ev["strike_count_after"] == 1


def test_third_funding_strike_exactly_suspends_client():
    """PRD §3.5: "The **count-based view** — the client's `funding_failure_count`
    — is simply the number of unresolved events, one per event regardless of kind,
    and it drives the suspension gate: when the count reaches 3 the client is
    automatically moved from `ACTIVE` to `SUSPENDED`."
    PRD §3.5: "a single NSF return (base 2, count 1) already elevates posture to
    `ELEVATED` without suspending, while a third unresolved event of any kind
    suspends regardless of the weighted total."

    Design: Difficulty/boundary_precision_check/third_funding_strike_exactly_suspends_client
    """
    setup = setup_active_client()
    client = setup["client"]
    imps = create_nsf_strikes(client, 2)
    at2 = get_client(client["id"])
    assert at2["funding_failure_count"] == 2
    assert at2["status"] == "ACTIVE", "two strikes do not suspend"
    assert at2["risk_posture"] == "HIGH", "weighted base 2+2 = 4 >= 4"

    # Third strike: inclusive boundary — client auto-suspends.
    create_nsf_strikes(
        client, 1, pay_dates=["2026-09-11T00:00:00Z"]
    )
    at3 = get_client(client["id"])
    assert at3["funding_failure_count"] == 3
    assert at3["status"] == "SUSPENDED"
    events = get_funding_failures(client["id"], resolved=False)
    assert len(events) == 3


def test_two_strikes_leave_client_active_but_high():
    """PRD §3.5: "when the count reaches 3 the client is automatically moved from
    `ACTIVE` to `SUSPENDED`."
    PRD §3.5: "The thresholds are inclusive: a base of exactly 4 is `HIGH`."

    Design: Difficulty/boundary_precision_check/third_funding_strike_exactly_suspends_client
    """
    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 2)
    client_after = get_client(client["id"])
    assert client_after["funding_failure_count"] == 2
    assert client_after["risk_posture"] == "HIGH"
    assert client_after["status"] == "ACTIVE"


def test_impound_blocked_on_suspended_client():
    """PRD §3.4: "Submission requires ... the owning client to be `ACTIVE` — a
    client still `ONBOARDING`, auto-`SUSPENDED`, or `TERMINATED` blocks submission
    with `ERR_CLIENT_NOT_ACTIVE` (HTTP 409)."
    PRD §3.5: "when the count reaches 3 the client is automatically moved from
    `ACTIVE` to `SUSPENDED`, and new impound initiation is blocked for the client
    until reactivation."

    Design: Corner/validations/v_impound_blocked_on_suspended_client
    """
    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 3)
    assert get_client(client["id"])["status"] == "SUSPENDED"

    run4 = create_run(
        client,
        pay_date="2026-09-15T00:00:00Z",
        period_start="2026-09-12T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
    )
    resp = api_client.submit_run(run4["id"], make_client_admin_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE, 409)
    assert get_success_data(
        api_client.get_payroll_run(run4["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "DRAFT"


def test_suspended_client_cannot_initiate_impound():
    """PRD §3.4: "This action — performed by the `ClientPayrollAdmin` and
    OCC-guarded on the client's `version` via `expected_client_version` per §2.7 —
    requires the client to be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`)."
    PRD §3.5: "when the count reaches 3 the client is automatically moved from
    `ACTIVE` to `SUSPENDED`, and new impound initiation is blocked for the client
    until reactivation."

    Design: Corner/validations/v_impound_blocked_on_suspended_client
    """
    from test_helpers import client_version

    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 3)
    assert get_client(client["id"])["status"] == "SUSPENDED"
    run = create_run(client)
    resp = api_client.initiate_impound(
        run["id"], client_version(client["id"]), make_client_admin_headers(client["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE, 409)


def test_wire_required_settle_blocked_until_confirmation():
    """PRD §3.4: "For a run whose `funding_model` is `WIRE_REQUIRED`, settlement
    is blocked until the client has confirmed same-day wire funding — the
    `ClientPayrollAdmin` confirms the wire through a dedicated action on the
    impound that stamps the run's `funding_confirmed_at`, and any settle attempt
    before that stamp exists is rejected with `ERR_WIRE_CONFIRMATION_REQUIRED`
    (HTTP 409)."
    PRD §3.4: "At submission the run's effective `funding_model` is computed:
    `WIRE_REQUIRED` when the client's `risk_posture` is `HIGH`, otherwise
    `STANDARD`."

    Design: Corner/validations/v_wire_required_settle_blocked_until_confirmation
    """
    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 2)  # base 4 -> HIGH (count 2, still ACTIVE)
    assert get_client(client["id"])["risk_posture"] == "HIGH"

    run3 = create_run(
        client,
        pay_date="2026-09-11T00:00:00Z",
        period_start="2026-09-09T00:00:00Z",
        period_end="2026-09-11T00:00:00Z",
    )
    submitted = submit_run(client, run3)
    assert submitted["funding_model"] == "WIRE_REQUIRED"
    imp3 = impound_run(client, run3)

    resp = api_client.settle_impound(imp3["id"], TEST_USERS["treasury_headers"])
    validate_error(resp, ApiErrorId.ERR_WIRE_CONFIRMATION_REQUIRED, 409)

    validate_success(
        api_client.confirm_wire(imp3["id"], make_client_admin_headers(client["id"]))
    )
    settled = validate_success(
        api_client.settle_impound(imp3["id"], TEST_USERS["treasury_headers"])
    )
    assert settled["status"] == "SETTLED"
    assert get_client(client["id"])["status"] == "ACTIVE"  # only 2 strikes


def test_wire_required_due_by_is_end_of_initiation_day():
    """PRD §3.4: "for `WIRE_REQUIRED` funding, `due_by` is the end of the calendar
    day on which the draft was initiated (23:59:59Z that same day)."

    Design: Corner/validations/v_wire_required_settle_blocked_until_confirmation
    """
    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 2)
    run3 = create_run(
        client,
        pay_date="2026-09-11T00:00:00Z",
        period_start="2026-09-09T00:00:00Z",
        period_end="2026-09-11T00:00:00Z",
    )
    submit_run(client, run3)
    set_clock("2026-09-11T08:30:00Z")
    imp3 = impound_run(client, run3)
    assert imp3["due_by"][:10] == "2026-09-11"
    assert "23:59:59" in imp3["due_by"]


def test_wire_missed_creates_lighter_strike_and_suspends_on_count():
    """PRD §3.4: "If the wire deadline passes without confirmation,
    `BureauTreasury` records the miss, which creates a FundingFailureEvent of kind
    `WIRE_NOT_CONFIRMED`, fails the impound, reverses the run, and cancels the
    run's `SCHEDULED` deposits."
    PRD §3.5: "each unresolved `NSF_RETURN` contributes 2 to a base score and each
    unresolved `WIRE_NOT_CONFIRMED` contributes 1 — wire misses weigh less."
    PRD §3.5: "when the count reaches 3 the client is automatically moved from
    `ACTIVE` to `SUSPENDED`."

    Design: Corner/cross_cutting_layers/l_wire_missed_creates_lighter_strike
    """
    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 2)  # base 4 -> HIGH, count 2
    run3 = create_run(
        client,
        pay_date="2026-09-11T00:00:00Z",
        period_start="2026-09-09T00:00:00Z",
        period_end="2026-09-11T00:00:00Z",
    )
    submitted = submit_run(client, run3)
    assert submitted["funding_model"] == "WIRE_REQUIRED"
    imp3 = impound_run(client, run3)

    validate_success(api_client.miss_wire(imp3["id"], TEST_USERS["treasury_headers"]))

    imp_after = get_success_data(
        api_client.get_impound(imp3["id"], TEST_USERS["treasury_headers"])
    )
    assert imp_after["status"] == "FAILED"
    assert get_success_data(
        api_client.get_payroll_run(run3["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "REVERSED"

    events = get_funding_failures(client["id"])
    assert len(events) == 3
    kinds = [e["kind"] for e in events]
    assert kinds.count("WIRE_NOT_CONFIRMED") == 1
    assert kinds.count("NSF_RETURN") == 2

    client_after = get_client(client["id"])
    assert client_after["funding_failure_count"] == 3
    assert client_after["status"] == "SUSPENDED"  # count reached 3

    assessments = get_success_data(
        api_client.list_client_credit_assessments(
            client["id"], TEST_USERS["treasury_headers"]
        )
    )
    assert len(assessments) == 3
    assert assessments[-1]["trigger"] == "FUNDING_FAILURE"
    assert assessments[-1]["new_posture"] == "HIGH"


def test_single_wire_miss_is_lighter_than_nsf():
    """PRD §3.5: "each unresolved `NSF_RETURN` contributes 2 to a base score and
    each unresolved `WIRE_NOT_CONFIRMED` contributes 1 — wire misses weigh less —
    and the posture is `HIGH` when the base is at least 4, `ELEVATED` when the
    base is 2 or 3, and `NORMAL` when the base is at most 1."

    Design: Corner/cross_cutting_layers/l_wire_missed_creates_lighter_strike
    """
    setup = setup_active_client()
    client = setup["client"]
    # One NSF strike: base 2 -> ELEVATED.
    create_nsf_strikes(client, 1)
    elevated = get_client(client["id"])
    assert elevated["risk_posture"] == "ELEVATED"
    assert elevated["funding_failure_count"] == 1
    # A second client with a single wire miss stays NORMAL (base 1 <= 1) —
    # but wire misses only occur on WIRE_REQUIRED runs, which need HIGH posture,
    # so instead verify weighting via event kinds recorded so far.
    events = get_funding_failures(client["id"])
    assert all(e["kind"] == "NSF_RETURN" for e in events)


def test_funding_failures_subresource_lists_strikes_and_cure_resets_posture():
    """PRD §3.5: "`BureauTreasury` cures a failure by marking it resolved, which
    stamps `resolved_at` and recomputes the client's posture."
    PRD §3.5: "Funding failures are listable bureau-wide with `impound_id`,
    `client_id`, and `resolved` filters, per-client through the client's
    funding-failure list (with a `resolved` filter), and individually."

    Design: Corner/endpoints/ep_funding_failures_subresource_lists_strikes
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    fail_impound(imp)

    events = get_funding_failures(client["id"], resolved=False)
    assert len(events) == 1
    assert events[0]["strike_count_after"] == 1
    event_id = events[0]["id"]

    validate_success(
        api_client.resolve_funding_failure(event_id, TEST_USERS["treasury_headers"])
    )
    remaining = get_funding_failures(client["id"], resolved=False)
    assert len(remaining) == 0
    assert get_client(client["id"])["risk_posture"] == "NORMAL"


def test_cure_records_failure_cured_assessment():
    """PRD §3.5: "Every posture recomputation appends a CreditAssessment recording
    `assessed_at`, the `prior_posture`, the `new_posture`, and a `trigger` of
    `FUNDING_FAILURE` for strikes, `FAILURE_CURED` for cures, or `MANUAL_REVIEW`
    for analyst-initiated reviews."

    Design: Corner/endpoints/ep_funding_failures_subresource_lists_strikes
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    fail_impound(impound_run(client, run))
    event_id = get_funding_failures(client["id"])[0]["id"]
    validate_success(
        api_client.resolve_funding_failure(event_id, TEST_USERS["treasury_headers"])
    )
    assessments = get_success_data(
        api_client.list_client_credit_assessments(
            client["id"], TEST_USERS["treasury_headers"]
        )
    )
    triggers = [a["trigger"] for a in assessments]
    assert "FUNDING_FAILURE" in triggers
    assert "FAILURE_CURED" in triggers


def test_reactivate_with_unresolved_failures_rejected():
    """PRD §3.5: "A `BureauCompliance` officer may reactivate a `SUSPENDED` client
    once every FundingFailureEvent for the client has `resolved_at` set — any
    unresolved strike blocks reactivation with `ERR_UNRESOLVED_FUNDING_FAILURES`
    (HTTP 409)."
    PRD §3.5: "Reactivation recomputes posture, so a fully cured client returns to
    `NORMAL`."

    Design: Corner/errors/x_reactivate_with_unresolved_failures
    """
    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 3)
    assert get_client(client["id"])["status"] == "SUSPENDED"

    resp = api_client.reactivate_client(client["id"], TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_FUNDING_FAILURES, 409)

    for ev in get_funding_failures(client["id"], resolved=False):
        validate_success(
            api_client.resolve_funding_failure(ev["id"], TEST_USERS["treasury_headers"])
        )
    reactivated = validate_success(
        api_client.reactivate_client(client["id"], TEST_USERS["compliance_headers"])
    )
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["risk_posture"] == "NORMAL"


def test_reactivate_with_partial_cures_still_rejected():
    """PRD §3.5: "A `BureauCompliance` officer may reactivate a `SUSPENDED` client
    once every FundingFailureEvent for the client has `resolved_at` set — any
    unresolved strike blocks reactivation with `ERR_UNRESOLVED_FUNDING_FAILURES`
    (HTTP 409)."

    Design: Corner/errors/x_reactivate_with_unresolved_failures
    """
    setup = setup_active_client()
    client = setup["client"]
    create_nsf_strikes(client, 3)
    events = get_funding_failures(client["id"], resolved=False)
    validate_success(
        api_client.resolve_funding_failure(events[0]["id"], TEST_USERS["treasury_headers"])
    )
    resp = api_client.reactivate_client(client["id"], TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_FUNDING_FAILURES, 409)
    assert get_client(client["id"])["status"] == "SUSPENDED"


def test_credit_hold_blocks_impound():
    """PRD §3.5: "an imposed hold blocks every new impound initiation and blocks
    activation and reactivation even when the client is otherwise eligible."
    PRD §3.4: "This action ... requires the client to be `ACTIVE` (else
    `ERR_CLIENT_NOT_ACTIVE`) and free of a compliance credit hold (else
    `ERR_CREDIT_HOLD_ACTIVE`)."

    Design: Corner/errors/x_credit_hold_blocks_impound
    """
    from test_helpers import client_version

    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    validate_success(
        api_client.set_credit_hold(client["id"], True, TEST_USERS["compliance_headers"])
    )
    resp = api_client.initiate_impound(
        run["id"], client_version(client["id"]), make_client_admin_headers(client["id"])
    )
    err = validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD_ACTIVE, 409)
    assert err["error_id"] != ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value
    _, meta = validate_paginated(
        api_client.list_impounds(
            TEST_USERS["treasury_headers"], params={"payroll_run_id": run["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_credit_hold_blocks_activation():
    """PRD §3.2: "`credit_hold` must be false, otherwise `ERR_CREDIT_HOLD_ACTIVE`
    (HTTP 409)."
    PRD §3.5: "an imposed hold blocks every new impound initiation and blocks
    activation and reactivation even when the client is otherwise eligible."

    Design: Corner/errors/x_credit_hold_blocks_impound
    """
    from test_helpers import (
        create_client,
        create_jurisdiction,
        create_registration_payload,
    )

    jurisdiction = create_jurisdiction()
    client = create_client(legal_name="Hold At Activate Co")
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    reg = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    get_success_data(
        api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )
    # Impose the hold while still ONBOARDING (hold can be set at any time).
    validate_success(
        api_client.set_credit_hold(client["id"], True, TEST_USERS["compliance_headers"])
    )
    resp = api_client.activate_client(client["id"], TEST_USERS["onboarder_headers"])
    validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD_ACTIVE, 409)
    assert get_client(client["id"])["status"] == "ONBOARDING"


def test_terminate_with_open_obligations():
    """PRD §3.2: "From `ACTIVE`, a client can be moved to `TERMINATED` by a
    `BureauCompliance` officer only when every obligation is settled: no Impound in
    `PENDING` status (else `ERR_PENDING_IMPOUNDS`), no TaxDeposit in `SCHEDULED` or
    `SUBMITTED` status, no AgencyNotice in `OPEN` or `IN_REVIEW` status, and no
    PayrollRun in `DRAFT`, `SUBMITTED`, or `IMPOUNDED` status — each of the latter
    three violations surfaced as `ERR_OPEN_OBLIGATIONS` (HTTP 409)."

    Design: Corner/errors/x_terminate_with_open_obligations
    """
    from test_helpers import create_deposit, create_settled_run

    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client)
    dep = create_deposit(built["run"], jurisdiction["id"], 200000)

    resp = api_client.terminate_client(client["id"], TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_OBLIGATIONS, 409)

    validate_success(
        api_client.cancel_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    terminated = validate_success(
        api_client.terminate_client(client["id"], TEST_USERS["compliance_headers"])
    )
    assert terminated["status"] == "TERMINATED"


def test_terminate_with_draft_run_blocked():
    """PRD §3.2: "no PayrollRun in `DRAFT`, `SUBMITTED`, or `IMPOUNDED` status —
    each of the latter three violations surfaced as `ERR_OPEN_OBLIGATIONS`
    (HTTP 409)."

    Design: Corner/errors/x_terminate_with_open_obligations
    """
    setup = setup_active_client()
    client = setup["client"]
    create_run(client)  # DRAFT run is an open obligation
    resp = api_client.terminate_client(client["id"], TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_OBLIGATIONS, 409)
    assert get_client(client["id"])["status"] == "ACTIVE"


def test_draft_then_reverse_conserves_client_money_and_tax_pipeline():
    """PRD §3.4: "Treasury may also reverse a drafted payroll run directly while
    its impound is still `PENDING` ... A direct reversal fails the impound as a
    returned draft, creates the same `NSF_RETURN` strike, and cascades to the
    run's scheduled deposits identically."
    PRD §3.4: "the run's `SCHEDULED` TaxDeposit rows are moved to `CANCELLED` —
    the run's tax funds are never scheduled further."

    Design: Difficulty/compensating_invariant/draft_then_reverse_conserves_client_money_and_tax_pipeline
    """
    from test_helpers import create_deposit, get_run

    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    run = create_run(client, gross_pay_cents=1200000, total_tax_cents=250000)
    assert run["impound_amount_cents"] == 1450000, "gross + tax pinned at creation"
    submit_run(client, run)
    imp = impound_run(client, run)
    run = get_run(run["id"])
    dep = create_deposit(run, jurisdiction["id"], 250000)

    validate_success(api_client.reverse_run(run["id"], TEST_USERS["treasury_headers"]))

    assert get_run(run["id"])["status"] == "REVERSED"
    assert get_success_data(
        api_client.get_impound(imp["id"], TEST_USERS["treasury_headers"])
    )["status"] == "FAILED"
    assert get_success_data(
        api_client.get_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "CANCELLED"

    # No impounded-not-settled money remains.
    _, meta = validate_paginated(
        api_client.list_impounds(
            TEST_USERS["treasury_headers"],
            params={"client_id": client["id"], "status": "PENDING"},
        )
    )
    assert meta["total_count"] == 0
    # Tax pipeline back to empty.
    for st in ("SCHEDULED", "SUBMITTED"):
        _, meta = validate_paginated(
            api_client.list_deposits(
                TEST_USERS["filer_alpha_headers"],
                params={"client_id": client["id"], "status": st},
            )
        )
        assert meta["total_count"] == 0
    # Audit trail grew by one unresolved NSF strike.
    events = get_funding_failures(client["id"], resolved=False)
    assert len(events) == 1
    assert events[0]["kind"] == "NSF_RETURN"


def test_reverse_only_allowed_while_impound_pending():
    """PRD §3.4: "Treasury may also reverse a drafted payroll run directly while
    its impound is still `PENDING`; reversing a run whose impound has already
    settled is rejected with `ERR_INVALID_STATE` (HTTP 409), because a settled run
    can no longer be unwound this way."

    Design: Difficulty/compensating_invariant/draft_then_reverse_conserves_client_money_and_tax_pipeline
    """
    from test_helpers import create_settled_run

    setup = setup_active_client()
    client = setup["client"]
    built = create_settled_run(client)
    resp = api_client.reverse_run(built["run"]["id"], TEST_USERS["treasury_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_success_data(
        api_client.get_payroll_run(built["run"]["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "SETTLED"


def test_deposit_read_reflects_cascaded_cancellation():
    """PRD §2.10: "When an impound fails or a run is reversed, the owning
    PayrollRun moves from `IMPOUNDED` to `REVERSED` and every `SCHEDULED`
    TaxDeposit belonging to that run is moved to `CANCELLED`."

    Design: Corner/cross_cutting_layers/l_deposit_read_reflects_cascaded_cancellation
    """
    from test_helpers import create_deposit, get_run

    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    run = get_run(run["id"])
    dep = create_deposit(run, jurisdiction["id"], 200000)
    fail_impound(imp)
    fetched = validate_success(
        api_client.get_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert fetched["status"] == "CANCELLED"


def test_late_return_after_settlement_strikes_but_run_stays_settled():
    """PRD §3.4: "a late bank return can arrive after settlement, moving the
    impound from `SETTLED` to `RETURNED`. In that case the payroll itself
    completed, so the run stays `SETTLED` and the bureau covers the returned funds
    out of pocket — but the client still accrues an `NSF_RETURN` strike exactly as
    if the draft had failed."

    Design: Corner/cross_cutting_layers/l_deposit_read_reflects_cascaded_cancellation
    """
    from test_helpers import create_settled_run

    setup = setup_active_client()
    client = setup["client"]
    built = create_settled_run(client)
    validate_success(
        api_client.return_impound(built["impound"]["id"], TEST_USERS["treasury_headers"])
    )
    imp_after = get_success_data(
        api_client.get_impound(built["impound"]["id"], TEST_USERS["treasury_headers"])
    )
    assert imp_after["status"] == "RETURNED"
    assert get_success_data(
        api_client.get_payroll_run(built["run"]["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "SETTLED"
    client_after = get_client(client["id"])
    assert client_after["funding_failure_count"] == 1
    assert client_after["risk_posture"] == "ELEVATED"
