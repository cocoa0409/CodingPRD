"""Refund checks: issuance gate, stale sweep, void compensation, reissue
window, ledger conservation, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    FRAUD_WARNING_TEXT,
    TEST_USERS,
    add_days_iso,
    advance_clock,
    api_client,
    approve_claim,
    assert_fund_ledger_invariants,
    assert_refund_check,
    build_user_headers,
    cash_check,
    close_claims_window,
    file_claim,
    get_claim,
    get_fund,
    get_success_data,
    issue_check,
    make_claimant_specs,
    parse_iso,
    setup_check_issued_fund,
    setup_disbursing_fund,
    setup_fund_with_approved_claims,
    setup_open_fund,
    start_disbursing,
    validate_error,
    validate_success,
    void_check,
)

_ADMIN = TEST_USERS["fund_administrator_headers"]  # fa-1
_OFFICER = TEST_USERS["disbursement_officer_headers"]  # do-1


def _setup_two_claim_disbursing():
    """DISBURSING fund: claim A (loss 3,000,000, filed on 2026-10-01) final
    1,892,858; claim B (loss 1,000,000, filed on 2026-10-02) final 757,142.
    allocated 2,650,000, available 0, reserve 350,000, total 3,000,000.
    Filings separated by one logical day to pin the remainder cent to A."""
    bundle = setup_open_fund(
        judgment_amount_cents=3_000_000,
        monetary_relief_cents=3_000_000,
        claimant_specs=make_claimant_specs(2),
    )
    claim_a = file_claim(bundle["claimants"][0], 3_000_000)
    approve_claim(claim_a["id"])
    advance_clock("2026-10-02T00:00:00Z")
    claim_b = file_claim(bundle["claimants"][1], 1_000_000)
    approve_claim(claim_b["id"])
    fund_id = bundle["fund"]["id"]
    close_claims_window(fund_id)
    start_disbursing(fund_id)
    bundle["claim_a"] = get_claim(claim_a["id"])
    bundle["claim_b"] = get_claim(claim_b["id"])
    bundle["fund"] = get_fund(fund_id)
    return bundle


def test_check_issue_requires_fund_disbursing():
    """PRD section 3.7: "Issuance requires the fund to be `DISBURSING` —
    against any other fund state the request fails with
    `ERR_FUND_NOT_DISBURSING`".
    PRD section 3.7: "Every check is stamped with the standing
    `fraud_warning_text`: "WARNING: The FTC never requires payment or personal
    information to cash a refund check. Anyone who demands money or
    information in exchange for your refund is a scammer.""
    PRD section 3.7: "Issuance moves the claim from `APPROVED` to
    `PAYMENT_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/check_issue_requires_fund_disbursing
    """
    bundle = setup_fund_with_approved_claims(
        [500_000], judgment_amount_cents=1_500_000, monetary_relief_cents=1_500_000
    )
    fund_id = bundle["fund"]["id"]
    claim_id = bundle["claims"][0]["id"]
    close_claims_window(fund_id)

    blocked = api_client.issue_refund_check(claim_id, {}, _OFFICER)
    validate_error(blocked, ApiErrorId.ERR_FUND_NOT_DISBURSING)

    start_disbursing(fund_id)
    check = validate_success(api_client.issue_refund_check(claim_id, {}, _OFFICER), 201)
    assert_refund_check(check)
    # eligible 500,000 fully covered: reserve 50,000, pool 1,450,000 >= 500,000.
    assert check["amount_cents"] == 500_000
    assert check["fraud_warning_text"] == FRAUD_WARNING_TEXT
    assert get_claim(claim_id)["status"] == "PAYMENT_PENDING"


def test_check_void_compensation_reverts_claim_and_releases_allocation():
    """PRD section 3.7: "because only uncashed checks can be voided, the claim
    always cascades back from `PAYMENT_PENDING` to `APPROVED`, reopening it
    for a replacement; the void simultaneously releases the allocation, so the
    fund's `allocated_cents` falls by the check's amount, `available_cents`
    rises by the same amount, and the fund's `version` increments."

    Design: Difficulty/transitive_cascade/check_void_compensation_reverts_claim_and_releases_allocation
    """
    bundle = _setup_two_claim_disbursing()
    fund_id = bundle["fund"]["id"]
    assert bundle["fund"]["allocated_cents"] == 2_650_000
    assert bundle["fund"]["available_cents"] == 0

    check_b = issue_check(bundle["claim_b"]["id"])
    fund_pre = get_fund(fund_id)

    voided = void_check(check_b["id"], voided_reason="uncashed and undeliverable")
    assert voided["status"] == "VOIDED"
    assert voided["voided_reason"] == "uncashed and undeliverable"

    assert get_claim(bundle["claim_b"]["id"])["status"] == "APPROVED", (
        "compensation loop: PAYMENT_PENDING -> APPROVED"
    )
    fund_post = get_fund(fund_id)
    assert fund_post["allocated_cents"] == 1_892_858, "757,142 released on reversion"
    assert fund_post["available_cents"] == 757_142
    assert fund_post["version"] > fund_pre["version"], "the void cascade must bump the fund version"


def test_fund_ledger_conservation_across_issue_cash_and_void():
    """PRD section 3.7: "`cashed_at` is stamped, the claim cascades from
    `PAYMENT_PENDING` to `PAID`, and the fund's ledger syncs —
    `allocated_cents` falls by the check's amount while `disbursed_cents`
    rises by the same amount".
    PRD section 3.7: "the void simultaneously releases the allocation, so the
    fund's `allocated_cents` falls by the check's amount, `available_cents`
    rises by the same amount".
    PRD section 3.6: "`available_cents`, the pool minus allocations and
    disbursements (the figure residual disposition later sweeps)".

    Design: Difficulty/compensating_invariant/fund_ledger_conservation_across_issue_cash_and_void
    """
    bundle = _setup_two_claim_disbursing()
    fund_id = bundle["fund"]["id"]

    fund0 = get_fund(fund_id)
    assert (fund0["available_cents"], fund0["allocated_cents"], fund0["disbursed_cents"],
            fund0["admin_reserve_cents"], fund0["residual_cents"]) == (0, 2_650_000, 0, 350_000, 0)
    assert_fund_ledger_invariants(fund0)

    check_a = issue_check(bundle["claim_a"]["id"])
    cash_check(check_a["id"])
    fund1 = get_fund(fund_id)
    assert fund1["allocated_cents"] == 757_142
    assert fund1["disbursed_cents"] == 1_892_858
    assert fund1["available_cents"] == 0
    assert_fund_ledger_invariants(fund1)

    check_b = issue_check(bundle["claim_b"]["id"])
    void_check(check_b["id"], voided_reason="uncashed and undeliverable")
    fund2 = get_fund(fund_id)
    assert fund2["allocated_cents"] == 0, "the ISSUE+VOID compensating pair fully released B"
    assert fund2["available_cents"] == 757_142
    assert fund2["disbursed_cents"] == 1_892_858
    assert_fund_ledger_invariants(fund2)

    assert get_claim(bundle["claim_a"]["id"])["status"] == "PAID"
    assert get_claim(bundle["claim_b"]["id"])["status"] == "APPROVED"


def test_check_auto_stale_at_exactly_90_day_boundary():
    """PRD section 3.7: "computes `stale_after` as 90 days after issuance".
    PRD section 2.5: "Any refund check still `ISSUED` whose `stale_after`
    instant has been reached or passed transitions to `STALE`. At exactly
    `stale_after` the check is stale."

    Design: Corner/state_machines/check_auto_stale_at_exactly_90_day_boundary
    """
    bundle = setup_check_issued_fund(
        losses=(500_000,), judgment_amount_cents=1_500_000, monetary_relief_cents=1_500_000
    )
    check = bundle["checks"][0]
    claim_id = bundle["claims"][0]["id"]
    assert parse_iso(check["issued_at"]) == parse_iso("2026-10-01T00:00:00Z")
    assert parse_iso(check["stale_after"]) == parse_iso(add_days_iso(check["issued_at"], 90))
    assert parse_iso(check["stale_after"]) == parse_iso("2026-12-30T00:00:00Z")

    advance_clock("2026-12-29T00:00:00Z")
    checks = get_success_data(api_client.list_claim_checks(claim_id, _OFFICER))
    assert checks[0]["status"] == "ISSUED", "89 days in: not yet stale"

    advance_clock("2026-12-30T00:00:00Z")
    checks = get_success_data(api_client.list_claim_checks(claim_id, _OFFICER))
    assert checks[0]["status"] == "STALE", "at exactly stale_after the check is already stale"


def test_check_reissue_within_window_then_expired_at_deadline():
    """PRD section 3.7: "The attempt succeeds strictly before the
    `reissue_deadline` of the original check in the chain; at or after that
    instant it fails with `ERR_REISSUE_WINDOW_EXPIRED`. The replacement
    check's `original_check_id` points at the `VOIDED` check it reissues,
    forming the audit chain."
    PRD section 3.7: "computes `stale_after` as 90 days after issuance and
    `reissue_deadline` as 180 days after issuance".

    Design: Corner/validations/check_reissue_within_window_then_expired_at_deadline
    """
    bundle = setup_check_issued_fund(
        losses=(500_000,), judgment_amount_cents=1_500_000, monetary_relief_cents=1_500_000
    )
    claim_id = bundle["claims"][0]["id"]
    check_1 = bundle["checks"][0]
    assert parse_iso(check_1["reissue_deadline"]) == parse_iso(
        add_days_iso(check_1["issued_at"], 180)
    )
    assert parse_iso(check_1["reissue_deadline"]) == parse_iso("2027-03-30T00:00:00Z")

    # Sweep the first check STALE at 2026-12-30, then void it; the claim
    # returns to APPROVED and can be reissued within the original's window.
    advance_clock("2026-12-30T00:00:00Z")
    void_check(check_1["id"], voided_reason="stale and uncashed")

    check_2 = validate_success(api_client.issue_refund_check(claim_id, {}, _OFFICER), 201)
    assert check_2["original_check_id"] == check_1["id"]
    assert check_2["amount_cents"] == 500_000
    assert parse_iso(check_2["issued_at"]) == parse_iso("2026-12-30T00:00:00Z")

    void_check(check_2["id"], voided_reason="returned by mail")
    advance_clock("2027-03-30T00:00:00Z")  # exactly the original's deadline
    expired = api_client.issue_refund_check(claim_id, {}, _OFFICER)
    validate_error(expired, ApiErrorId.ERR_REISSUE_WINDOW_EXPIRED)

    checks = get_success_data(api_client.list_claim_checks(claim_id, _OFFICER))
    assert len(checks) == 2
    assert [c["status"] for c in checks] == ["VOIDED", "VOIDED"]
    assert parse_iso(checks[0]["created_at"]) < parse_iso(checks[1]["created_at"]), (
        "the check listing is ordered by created_at ascending"
    )


def test_sod_check_issue_by_approving_user_rejected():
    """PRD section 3.7: "the issuing officer's identity must differ from the
    `approved_by_user_id` recorded on the claim, else `ERR_SOD_CHECK_ISSUE`."

    Design: Corner/cross_cutting_layers/sod_check_issue_by_approving_user_rejected
    """
    bundle = setup_disbursing_fund(
        [500_000], judgment_amount_cents=1_500_000, monetary_relief_cents=1_500_000
    )
    claim = bundle["claims"][0]
    assert claim["approved_by_user_id"] == "fa-1", "the SoD comparison key"

    same_user = api_client.issue_refund_check(
        claim["id"], {}, build_user_headers("fa-1", "DisbursementOfficer")
    )
    validate_error(same_user, ApiErrorId.ERR_SOD_CHECK_ISSUE)

    check = validate_success(api_client.issue_refund_check(claim["id"], {}, _OFFICER), 201)
    assert check["amount_cents"] == 500_000
