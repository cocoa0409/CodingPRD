"""Agency notices and return amendments (PRD §3.8, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_accepted_return,
    create_confirmed_deposit,
    create_jurisdiction,
    create_notice_payload,
    create_return_for,
    create_settled_run,
    get_success_data,
    set_clock,
    setup_active_client,
    validate_error,
    validate_paginated,
    validate_success,
)


def _accepted_q3_return(client, jurisdiction):
    """Client with one SETTLED Q3 run + CONFIRMED deposit; ACCEPTED 2026-Q3 return."""
    r1 = create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    create_confirmed_deposit(r1["run"], jurisdiction["id"], 300000)
    set_clock("2026-10-20T00:00:00Z")
    return create_accepted_return(client, jurisdiction["id"], "2026-Q3")


def _reconciled_q3_return(client, jurisdiction):
    ret = _accepted_q3_return(client, jurisdiction)
    return validate_success(
        api_client.reconcile_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )


def test_notice_escalation_loop_returns_to_in_review():
    """PRD §3.9: "Taking ownership of the discrepancy moves the notice from `OPEN`
    to `IN_REVIEW`. From there, a `BureauTaxFiler` may escalate it — `IN_REVIEW`
    to `ESCALATED` — and later pull it back into review; the escalation loop
    between `IN_REVIEW` and `ESCALATED` is unbounded."
    PRD §3.9: "resolving with no change moves the notice to `RESOLVED_NO_CHANGE`,
    records the `resolution_note`, and sets `adjustment_amount_cents` to zero."
    PRD §3.9: "Either resolved state can then be closed, moving the notice to
    terminal `CLOSED`."

    Design: Corner/state_machines/sm_notice_escalation_loop_returns_to_in_review
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    notice = get_success_data(
        api_client.create_notice(
            create_notice_payload(
                client_id=client["id"],
                jurisdiction_id=jurisdiction["id"],
                return_id=ret["id"],
                notice_type="BALANCE_DUE",
                claimed_amount_cents=50000,
            ),
            TEST_USERS["filer_alpha_headers"],
        )
    )
    assert notice["status"] == "OPEN"

    in_review = validate_success(
        api_client.start_notice_review(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert in_review["status"] == "IN_REVIEW"
    escalated = validate_success(
        api_client.escalate_notice(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert escalated["status"] == "ESCALATED"
    back = validate_success(
        api_client.start_notice_review(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert back["status"] == "IN_REVIEW"
    resolved = validate_success(
        api_client.resolve_notice(
            notice["id"],
            {
                "resolution": "NO_CHANGE",
                "resolution_note": "Agency figure matched bureau books",
            },
            TEST_USERS["filer_alpha_headers"],
        )
    )
    assert resolved["status"] == "RESOLVED_NO_CHANGE"
    assert resolved["adjustment_amount_cents"] == 0
    closed = validate_success(
        api_client.close_notice(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert closed["status"] == "CLOSED"


def test_notice_adjustment_resolution_requires_positive_amount():
    """PRD §3.9: "resolving with an adjustment moves it to `RESOLVED_ADJUSTMENT`
    and requires `adjustment_amount_cents` to be supplied and greater than zero —
    a missing or non-positive amount is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/sm_notice_escalation_loop_returns_to_in_review
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    notice = get_success_data(
        api_client.create_notice(
            create_notice_payload(
                client_id=client["id"],
                jurisdiction_id=jurisdiction["id"],
                return_id=ret["id"],
            ),
            TEST_USERS["filer_alpha_headers"],
        )
    )
    validate_success(
        api_client.start_notice_review(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    resp = api_client.resolve_notice(
        notice["id"],
        {"resolution": "ADJUSTMENT", "resolution_note": "Agreed adjustment"},
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    resp = api_client.resolve_notice(
        notice["id"],
        {
            "resolution": "ADJUSTMENT",
            "resolution_note": "Agreed adjustment",
            "adjustment_amount_cents": 0,
        },
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_amendment_acceptance_cascades_return_supersession():
    """PRD §3.8: "Acceptance is the consequential transition: it moves the
    amendment to `ACCEPTED`, moves the amended TaxReturn to `AMENDED` (from either
    `ACCEPTED` or `RECONCILED`), and creates a brand-new TaxReturn already in
    `FILED` status for the same client, jurisdiction, and period, whose
    `supersedes_return_id` points at the amended return and whose
    `expected_liability_cents` is the amendment's `adjusted_liability_cents`."

    Design: Difficulty/transitive_cascade/amendment_acceptance_cascades_return_supersession_and_replacement_filing
    """
    jurisdiction = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    ret = _accepted_q3_return(client, jurisdiction)

    amd = get_success_data(
        api_client.create_amendment(
            {
                "return_id": ret["id"],
                "reason": "Wage reclass discovered in agency audit",
                "adjusted_liability_cents": 320000,
            },
            TEST_USERS["filer_alpha_headers"],
        )
    )
    validate_success(
        api_client.file_amendment(amd["id"], TEST_USERS["filer_alpha_headers"])
    )
    accepted = validate_success(
        api_client.accept_amendment(amd["id"], TEST_USERS["filer_beta_headers"])
    )
    assert accepted["status"] == "ACCEPTED"

    amended = validate_success(
        api_client.get_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert amended["status"] == "AMENDED"

    replacements, meta = validate_paginated(
        api_client.list_returns(
            TEST_USERS["filer_alpha_headers"],
            params={"client_id": client["id"], "status": "FILED"},
        )
    )
    assert meta["total_count"] == 1
    replacement = replacements[0]
    assert replacement["supersedes_return_id"] == ret["id"]
    assert replacement["expected_liability_cents"] == 320000
    assert replacement["period"] == "2026-Q3"
    assert replacement["jurisdiction_id"] == jurisdiction["id"]


def test_amendment_acceptance_from_reconciled_also_supersedes():
    """PRD §3.8: "it moves the amendment to `ACCEPTED`, moves the amended
    TaxReturn to `AMENDED` (from either `ACCEPTED` or `RECONCILED`), and creates
    a brand-new TaxReturn already in `FILED` status for the same client,
    jurisdiction, and period, whose `supersedes_return_id` points at the amended
    return."

    Design: Difficulty/transitive_cascade/amendment_acceptance_cascades_return_supersession_and_replacement_filing
    """
    jurisdiction = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    ret = _reconciled_q3_return(client, jurisdiction)
    assert ret["status"] == "RECONCILED"

    amd = get_success_data(
        api_client.create_amendment(
            {
                "return_id": ret["id"],
                "reason": "Post-reconciliation adjustment",
                "adjusted_liability_cents": 350000,
            },
            TEST_USERS["filer_alpha_headers"],
        )
    )
    validate_success(
        api_client.file_amendment(amd["id"], TEST_USERS["filer_alpha_headers"])
    )
    validate_success(
        api_client.accept_amendment(amd["id"], TEST_USERS["filer_beta_headers"])
    )
    amended = validate_success(
        api_client.get_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert amended["status"] == "AMENDED"
    replacements, meta = validate_paginated(
        api_client.list_returns(
            TEST_USERS["filer_alpha_headers"],
            params={"client_id": client["id"], "supersedes_return_id": ret["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert replacements[0]["status"] == "FILED"
    assert replacements[0]["expected_liability_cents"] == 350000


def test_amend_draft_return_returns_not_amendable():
    """PRD §3.8: "Amendments may only be created against, and filed against,
    returns in `ACCEPTED` or `RECONCILED` status; any other target is rejected
    with `ERR_RETURN_NOT_AMENDABLE` (HTTP 409), both at creation and again when
    the amendment itself moves from `DRAFT` to `FILED`."

    Design: Corner/errors/x_amend_draft_return_returns_not_amendable
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")  # DRAFT
    resp = api_client.create_amendment(
        {"return_id": ret["id"], "reason": "Too early", "adjusted_liability_cents": 100},
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_AMENDABLE, 409)
    _, meta = validate_paginated(
        api_client.list_return_amendments(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert meta["total_count"] == 0


def test_amend_filed_return_returns_not_amendable():
    """PRD §3.8: "Amendments may only be created against, and filed against,
    returns in `ACCEPTED` or `RECONCILED` status; any other target is rejected
    with `ERR_RETURN_NOT_AMENDABLE` (HTTP 409), both at creation and again when
    the amendment itself moves from `DRAFT` to `FILED`."

    Design: Corner/errors/x_amend_draft_return_returns_not_amendable
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    set_clock("2026-10-05T00:00:00Z")
    validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )  # FILED, not yet ACCEPTED
    resp = api_client.create_amendment(
        {"return_id": ret["id"], "reason": "Too early", "adjusted_liability_cents": 100},
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_AMENDABLE, 409)


def test_amendment_reject_redraft_loop():
    """PRD §3.8: "Rejection moves the amendment from `FILED` to `REJECTED`, and a
    redraft returns it to `DRAFT` — the loop is unbounded."
    PRD §3.8: "it moves the amendment to `ACCEPTED`, moves the amended TaxReturn
    to `AMENDED` (from either `ACCEPTED` or `RECONCILED`)."

    Design: Corner/state_machines/sm_amendment_reject_redraft_loop
    """
    jurisdiction = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    ret = _reconciled_q3_return(client, jurisdiction)

    amd = get_success_data(
        api_client.create_amendment(
            {"return_id": ret["id"], "reason": "Reclass", "adjusted_liability_cents": 310000},
            TEST_USERS["filer_alpha_headers"],
        )
    )
    validate_success(api_client.file_amendment(amd["id"], TEST_USERS["filer_alpha_headers"]))
    rejected = validate_success(
        api_client.reject_amendment(amd["id"], TEST_USERS["filer_beta_headers"])
    )
    assert rejected["status"] == "REJECTED"
    redrafted = validate_success(
        api_client.redraft_amendment(amd["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert redrafted["status"] == "DRAFT"
    validate_success(api_client.file_amendment(amd["id"], TEST_USERS["filer_alpha_headers"]))
    accepted = validate_success(
        api_client.accept_amendment(amd["id"], TEST_USERS["filer_beta_headers"])
    )
    assert accepted["status"] == "ACCEPTED"

    amended = validate_success(
        api_client.get_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert amended["status"] == "AMENDED"  # RECONCILED -> AMENDED edge fired
    rows, meta = validate_paginated(
        api_client.list_return_amendments(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == amd["id"]


def test_amendment_redraft_clears_back_to_draft():
    """PRD §3.8: "Rejection moves the amendment from `FILED` to `REJECTED`, and a
    redraft returns it to `DRAFT` — the loop is unbounded."

    Design: Corner/state_machines/sm_amendment_reject_redraft_loop
    """
    jurisdiction = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    ret = _accepted_q3_return(client, jurisdiction)
    amd = get_success_data(
        api_client.create_amendment(
            {"return_id": ret["id"], "reason": "Reclass", "adjusted_liability_cents": 310000},
            TEST_USERS["filer_alpha_headers"],
        )
    )
    validate_success(api_client.file_amendment(amd["id"], TEST_USERS["filer_alpha_headers"]))
    validate_success(
        api_client.reject_amendment(amd["id"], TEST_USERS["filer_beta_headers"])
    )
    redrafted = validate_success(
        api_client.redraft_amendment(amd["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert redrafted["status"] == "DRAFT"
    # The loop is unbounded: file it again.
    refiled = validate_success(
        api_client.file_amendment(amd["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert refiled["status"] == "FILED"
