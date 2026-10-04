"""Application lifecycle and tier-standards evaluation (PRD §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_application,
    create_issuer,
    get_entry_fee,
    get_success_data,
    make_issuer_officer_headers,
    reset_clock,
    submit_application,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["listing_analyst_headers"]


def _approve(api, issuer_id, app_id):
    version = get_success_data(api.get_issuer(issuer_id, ANALYST))["version"]
    return api.approve_application(issuer_id, app_id, version, ANALYST)


def test_application_initial_state_is_draft(api):
    """PRD §3.1: "The application begins in `DRAFT` status."
    PRD §3.2: "The evaluation fills `evaluated_standards` with the per-standard results and
    margins." — evaluation runs at submit, not at creation.

    Design: Corner/state_machines/application_initial_state_is_draft
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(issuer["id"], target_tier="CAPITAL")
    assert app["status"] == "DRAFT"
    assert app["evaluated_standards"] == []


def test_second_submit_on_submitted_application_returns_invalid_state(api):
    """PRD §3.2: "When the IssuerOfficer submits the application, the system first
    validates governance composition ..." — submit transitions only from DRAFT; PRD §5:
    ERR_INVALID_STATE (409) covers a target resource not in a state from which the
    requested transition exists.

    Design: Corner/state_machines/second_submit_on_submitted_application_returns_invalid_state
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(issuer["id"], target_tier="CAPITAL")
    submitted = submit_application(issuer["id"], app["id"])
    assert submitted["status"] == "SUBMITTED"
    resp = api.submit_application(
        issuer["id"], app["id"], make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_listing_application(issuer["id"], app["id"], ANALYST))
    assert current["status"] == "SUBMITTED"


def test_approve_already_approved_application_returns_invalid_state(api):
    """PRD §3.3: "A `ListingAnalyst` may approve a `SUBMITTED` application." — APPROVED is
    terminal; a second approve is rejected with ERR_INVALID_STATE (PRD §5) even though the
    OCC version supplied is the current one.

    Design: Corner/state_machines/approve_already_approved_application_returns_invalid_state
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(issuer["id"], target_tier="CAPITAL")
    submit_application(issuer["id"], app["id"])
    approved = validate_success(_approve(api, issuer["id"], app["id"]), 200)
    assert approved["status"] == "APPROVED"
    resp = _approve(api, issuer["id"], app["id"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_listing_application(issuer["id"], app["id"], ANALYST))
    assert current["status"] == "APPROVED"
    listings = get_success_data(api.list_listings(issuer["id"], ANALYST))
    assert len(listings) == 1


def test_governance_majority_committee_membership_composition_a(api):
    """PRD §3.2: "When the IssuerOfficer submits the application, the system first
    validates governance composition: the board must have a strictly majority of
    independent directors (more than half of board_directors must have is_independent
    true) ... Failure is rejected with ERR_GOVERNANCE_COMPOSITION (HTTP 422)."

    A 4-director board with exactly 2 independent fails the strict-majority leg even
    though the audit and compensation committees pass their own composition legs.

    Design: Difficulty/combinatorial_formula/governance_majority_committee_membership_composition
    """
    reset_clock()
    issuer = create_issuer()
    board = [
        {"director_name": "D1", "is_independent": True},
        {"director_name": "D2", "is_independent": True},
        {"director_name": "D3", "is_independent": False},
        {"director_name": "D4", "is_independent": False},
    ]
    audit = [
        {"director_name": "D1", "is_independent": True, "is_financial_expert": True},
        {"director_name": "D2", "is_independent": True, "is_financial_expert": False},
        {"director_name": "D1", "is_independent": True, "is_financial_expert": False},
    ]
    comp = [
        {"director_name": "D1", "is_independent": True},
        {"director_name": "D2", "is_independent": True},
    ]
    app = create_application(
        issuer["id"], target_tier="CAPITAL",
        board_directors=board, audit_committee=audit, compensation_committee=comp)
    resp = api.submit_application(
        issuer["id"], app["id"], make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_GOVERNANCE_COMPOSITION)
    current = get_success_data(api.get_listing_application(issuer["id"], app["id"], ANALYST))
    assert current["status"] == "DRAFT"
    assert current["evaluated_standards"] == []
    issuer_now = get_success_data(api.get_issuer(issuer["id"], ANALYST))
    assert issuer_now["status"] == "PRE_LISTING"


def test_governance_majority_committee_membership_composition_b(api):
    """PRD §3.2: "the audit committee must have at least three members, all independent,
    with at least one financial expert ... and every committee member must appear in
    board_directors by director_name. Failure is rejected with ERR_GOVERNANCE_COMPOSITION
    (HTTP 422)."

    A board-majority-independent application whose audit committee names a director not on
    the board still fails the composition gate at submit.

    Design: Difficulty/combinatorial_formula/governance_majority_committee_membership_composition
    """
    reset_clock()
    issuer = create_issuer()
    audit = [
        {"director_name": "D1", "is_independent": True, "is_financial_expert": True},
        {"director_name": "D2", "is_independent": True, "is_financial_expert": False},
        {"director_name": "D9", "is_independent": True, "is_financial_expert": False},
    ]
    app = create_application(issuer["id"], target_tier="CAPITAL", audit_committee=audit)
    resp = api.submit_application(
        issuer["id"], app["id"], make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_GOVERNANCE_COMPOSITION)
    current = get_success_data(api.get_listing_application(issuer["id"], app["id"], ANALYST))
    assert current["status"] == "DRAFT"


def test_tier_standards_entry_rejects_vs_continued_accepts_same_metrics_a(api):
    """PRD §3.2: "The GLOBAL tier passes if any one of three standards is met: standard 1
    requires stockholders_equity_cents of at least 1,500,000,000 cents ... standard 2
    requires market_value_listed_securities_cents of at least 7,500,000,000,000 cents,
    market_value_unrestricted_publicly_held_cents of at least 2,000,000,000 cents ...
    standard 3 requires total_revenue_cents of at least 7,500,000,000,000 cents ..."
    "If no standard passes, the application auto-transitions from DRAFT to REJECTED in the
    same request; the submit returns 200 with the REJECTED application."

    Metrics equity 1,000,000,000 / MVLS 800,000,000,000 / MVUPH 1,500,000,000 /
    revenue 5,000,000,000 fail every GLOBAL entry standard.

    Design: Difficulty/dual_variant_calc/tier_standards_entry_rejects_vs_continued_accepts_same_metrics
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(
        issuer["id"], target_tier="GLOBAL",
        stockholders_equity_cents=1_000_000_000,
        market_value_listed_securities_cents=800_000_000_000,
        market_value_unrestricted_publicly_held_cents=1_500_000_000,
        total_revenue_cents=5_000_000_000,
        income_from_continuing_operations_cents=900_000_000,
        round_lot_holders=500, total_shareholders=500, market_makers=4)
    resp = api.submit_application(
        issuer["id"], app["id"], make_issuer_officer_headers(issuer["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"
    assert len(data["evaluated_standards"]) > 0
    for entry in data["evaluated_standards"]:
        assert entry["passed"] is False
    issuer_now = get_success_data(api.get_issuer(issuer["id"], ANALYST))
    assert issuer_now["status"] == "PRE_LISTING"
    listings = get_success_data(api.list_listings(issuer["id"], ANALYST))
    assert listings == []


def test_tier_standards_entry_rejects_vs_continued_accepts_same_metrics_b(api):
    """PRD §3.5: "The continued standards are: for `GLOBAL_SELECT`,
    `market_value_listed_securities_cents` of at least 30,000,000,000,000 cents; for `GLOBAL`,
    `market_value_publicly_held_cents` of at least 5,000,000,000 cents and `round_lot_holders`
    of at least 400; for `CAPITAL`, `market_value_publicly_held_cents` of at least 1,000,000,000
    cents and `round_lot_holders` of at least 300." — and PRD §3.3: "The issuer must also meet the continued (not entry)
    standards of the target tier, evaluated from the application's metric fields" for
    TIER_TRANSFER approval; PRD §3.2: "If no standard passes, the application
    auto-transitions from DRAFT to REJECTED in the same request".

    The same metric set (MVUPH exactly 5,000,000,000; holders 500) that fails every
    GLOBAL entry standard satisfies the GLOBAL continued gate. PRD §3.2 evaluates
    *entry* standards at submit for every application, so the dual variant is observed
    by filing two TIER_TRANSFER applications: one whose metrics pass both gates
    (approval rewrites the listing tier), then one carrying the borderline set, which
    auto-rejects at submit under the entry gate.

    Design: Difficulty/dual_variant_calc/tier_standards_entry_rejects_vs_continued_accepts_same_metrics
    """
    reset_clock()
    # GLOBAL_SELECT issuer that passes entry S1 (income >= 1,100,000,000)
    issuer = create_issuer()
    app = create_application(
        issuer["id"], target_tier="GLOBAL_SELECT",
        income_from_continuing_operations_cents=1_100_000_000,
        market_value_publicly_held_cents=600_000_000_000)
    submit_application(issuer["id"], app["id"])
    approved = validate_success(_approve(api, issuer["id"], app["id"]), 200)
    assert approved["status"] == "APPROVED"
    listing = get_success_data(api.list_listings(issuer["id"], ANALYST))[0]
    assert listing["tier"] == "GLOBAL_SELECT"

    # First TIER_TRANSFER: metrics that pass a GLOBAL entry standard (S1: equity
    # 1,500,000,000; holders 400; market makers 3) AND the GLOBAL continued gate
    # (MVUPH 5,000,000,000 >= 5,000,000,000; holders 400 >= 400) — approval
    # re-evaluates the *continued* standards from the application's metric fields
    # (PRD §3.3) and rewrites the listing tier.
    tt_ok = create_application(
        issuer["id"], target_tier="GLOBAL", application_kind="TIER_TRANSFER",
        stockholders_equity_cents=1_500_000_000,
        market_value_unrestricted_publicly_held_cents=5_000_000_000,
        round_lot_holders=400, market_makers=3)
    submitted = submit_application(issuer["id"], tt_ok["id"])
    assert submitted["status"] == "SUBMITTED"
    approved = validate_success(_approve(api, issuer["id"], tt_ok["id"]), 200)
    assert approved["status"] == "APPROVED"
    listing = get_success_data(api.list_listings(issuer["id"], ANALYST))[0]
    assert listing["tier"] == "GLOBAL"

    # Second TIER_TRANSFER: the borderline metric set. Its MVUPH 5,000,000,000 and 500
    # holders satisfy the GLOBAL *continued* standards (PRD §3.5), yet it passes no
    # GLOBAL *entry* standard (equity 1,000,000,000 < 1,500,000,000; MVLS
    # 800,000,000,000 < 7,500,000,000,000; revenue 5,000,000,000 < 7,500,000,000,000)
    # — so submit auto-rejects per PRD §3.2 ("If no standard passes, the application
    # auto-transitions from DRAFT to REJECTED in the same request"), leaving the
    # listing untouched.
    tt_borderline = create_application(
        issuer["id"], target_tier="GLOBAL", application_kind="TIER_TRANSFER",
        stockholders_equity_cents=1_000_000_000,
        market_value_listed_securities_cents=800_000_000_000,
        market_value_unrestricted_publicly_held_cents=5_000_000_000,
        total_revenue_cents=5_000_000_000,
        income_from_continuing_operations_cents=900_000_000,
        round_lot_holders=500, total_shareholders=500, market_makers=4)
    resp = api.submit_application(
        issuer["id"], tt_borderline["id"], make_issuer_officer_headers(issuer["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"
    assert len(data["evaluated_standards"]) > 0
    for entry in data["evaluated_standards"]:
        assert entry["passed"] is False
    listing = get_success_data(api.list_listings(issuer["id"], ANALYST))[0]
    assert listing["tier"] == "GLOBAL"


def test_fee_convention_entry_inclusive_vs_annual_exclusive_same_shares_a(api):
    """PRD §3.10: "The annual fee uses the exclusive-of-entry-fee bracket table, which is
    strictly lower than the entry table for the same tier and share count." and "For
    GLOBAL_SELECT and GLOBAL: 1 to 50,000,000 shares yields 4,500,000 to 10,500,000
    cents" versus the entry table's "1 to 50,000,000 shares yields 15,000,000 to
    25,000,000 cents"; "The fee is created in `PENDING` status and
    immediately becomes `INVOICED`".

    One share on GLOBAL_SELECT: the ENTRY fee lands inside its PRD-stated bracket range
    ("1 to 50,000,000 shares yields 15,000,000 to 25,000,000 cents") and the ANNUAL fee
    inside its own ("1 to 50,000,000 shares yields 4,500,000 to 10,500,000 cents") —
    "strictly lower than the entry table for the same tier and share count".

    Design: Difficulty/dual_variant_calc/fee_convention_entry_inclusive_vs_annual_exclusive_same_shares
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(
        issuer["id"], target_tier="GLOBAL_SELECT",
        unrestricted_publicly_held_shares=1,
        income_from_continuing_operations_cents=1_100_000_000)
    submit_application(issuer["id"], app["id"])
    validate_success(_approve(api, issuer["id"], app["id"]), 200)

    entry_fee = get_entry_fee(issuer["id"])
    assert 15_000_000 <= entry_fee["amount_cents"] <= 25_000_000

    annual = validate_success(
        api.run_annual_fees(
            issuer["id"],
            {"shares_outstanding": 1,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer["id"], ANALYST))["version"]},
            TEST_USERS["finance_officer_headers"]),
        201)
    assert annual["fee_kind"] == "ANNUAL"
    assert annual["assessment_year"] == 2026
    assert 4_500_000 <= annual["amount_cents"] <= 10_500_000
    assert annual["amount_cents"] < entry_fee["amount_cents"]
    assert annual["status"] == "INVOICED"


def test_fee_convention_entry_inclusive_vs_annual_exclusive_same_shares_b(api):
    """PRD §3.10: "For CAPITAL: 1 to 5,000,000 shares yields 5,000,000 to 7,500,000
    cents" (entry table) versus "For CAPITAL: 1 to 5,000,000 shares yields 3,000,000 to
    5,000,000 cents" (annual table, "strictly lower than the entry table for the same tier
    and share count").

    5,000,000 shares on CAPITAL: the ENTRY fee lands inside its PRD-stated bracket range
    ("1 to 5,000,000 shares yields 5,000,000 to 7,500,000 cents") and the ANNUAL fee
    inside its own ("1 to 5,000,000 shares yields 3,000,000 to 5,000,000 cents") — the
    annual table is "strictly lower than the entry table for the same tier and share
    count" (the two ranges touch at 5,000,000, so only range membership, not strict
    amount ordering, is pinned at this boundary share count).

    Design: Difficulty/dual_variant_calc/fee_convention_entry_inclusive_vs_annual_exclusive_same_shares
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(
        issuer["id"], target_tier="CAPITAL",
        unrestricted_publicly_held_shares=5_000_000)
    submit_application(issuer["id"], app["id"])
    validate_success(_approve(api, issuer["id"], app["id"]), 200)

    entry_fee = get_entry_fee(issuer["id"])
    assert 5_000_000 <= entry_fee["amount_cents"] <= 7_500_000

    annual = validate_success(
        api.run_annual_fees(
            issuer["id"],
            {"shares_outstanding": 5_000_000,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer["id"], ANALYST))["version"]},
            TEST_USERS["finance_officer_headers"]),
        201)
    assert annual["fee_kind"] == "ANNUAL"
    assert 3_000_000 <= annual["amount_cents"] <= 5_000_000
    assert annual["status"] == "INVOICED"
