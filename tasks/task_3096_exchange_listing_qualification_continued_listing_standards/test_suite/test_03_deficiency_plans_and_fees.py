"""Deficiency detection, regain, compliance plans, and fee brackets (PRD §3.4-§3.6, §3.10)."""
from test_helpers import (
    ApiErrorId,
    create_application,
    create_compliance_plan_payload,
    create_issuer,
    create_snapshot_payload,
    get_bid_deficiency,
    get_deficiency_for,
    get_entry_fee,
    get_success_data,
    make_issuer_officer_headers,
    record_snapshot_days,
    reset_clock,
    run_monitor,
    setup_bid_deficiency,
    setup_listed_issuer,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["listing_analyst_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _approve(api, issuer_id, app_id):
    version = get_success_data(api.get_issuer(issuer_id, ANALYST))["version"]
    return api.approve_application(issuer_id, app_id, version, ANALYST)


def test_bid_streak_day_29_vs_day_30_trigger_a(api):
    """PRD §3.4: "If the consecutive failure count reaches the trigger—30 days for
    BID_PRICE, 10 days for all others—and no deficiency for that issuer and standard
    already exists in a non-terminal status, the system creates a Deficiency with ...
    status OPEN."

    29 consecutive failing days create zero deficiencies; the 30th creates exactly one.

    Design: Difficulty/boundary_precision_check/bid_streak_day_29_vs_day_30_trigger
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    record_snapshot_days(issuer_id, "2026-09-02", 29, closing_bid_cents=90)
    result = run_monitor(issuer_id)
    assert result["deficiencies_created"] == []

    record_snapshot_days(issuer_id, "2026-10-01", 1, closing_bid_cents=90)
    result = run_monitor(issuer_id)
    assert len(result["deficiencies_created"]) == 1

    deficiency = get_bid_deficiency(issuer_id)
    assert deficiency["status"] == "OPEN"
    assert deficiency["consecutive_days_failed"] == 30
    assert deficiency["tier_at_detection"] == "CAPITAL"
    assert deficiency["detected_at"].startswith("2026-10-01")
    assert deficiency["compliance_due_at"].startswith("2027-03-30")

    result = run_monitor(issuer_id)
    assert result["deficiencies_created"] == []


def test_bid_streak_day_29_vs_day_30_trigger_b(api):
    """PRD §3.4: "If the consecutive failure count reaches the trigger—30 days for
    BID_PRICE ... —and no deficiency for that issuer and standard already exists in a
    non-terminal status, the system creates a Deficiency ..."

    A fresh issuer: a monitor run after only 29 failing days yields an empty
    deficiencies list — one day short of the trigger.

    Design: Difficulty/boundary_precision_check/bid_streak_day_29_vs_day_30_trigger
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    record_snapshot_days(issuer_id, "2026-09-02", 29, closing_bid_cents=90)
    result = run_monitor(issuer_id)
    assert result["deficiencies_created"] == []
    rows = get_deficiency_for(issuer_id, "BID_PRICE")
    assert rows == []


def test_bid_price_strict_inequality_100_passes_99_fails(api):
    """PRD §3.4: "it walks backward from the latest snapshot counting consecutive days
    that strictly fail the tier threshold. The bid-price threshold is 100 cents at every
    tier."

    Thirty consecutive days at exactly 100 cents never fail — the monitor creates no
    deficiency.

    Design: Corner/calculations/bid_price_strict_inequality_100_passes_99_fails
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    record_snapshot_days(issuer_id, "2026-09-02", 30, closing_bid_cents=100)
    result = run_monitor(issuer_id)
    assert result["deficiencies_created"] == []
    rows = get_deficiency_for(issuer_id, "BID_PRICE")
    assert rows == []


def test_holders_deficiency_trigger_at_ten_consecutive_days(api):
    """PRD §3.4: "If the consecutive failure count reaches the trigger—30 days for
    BID_PRICE, 10 days for all others ..." and "The `ROUND_LOT_HOLDERS` and
    `TOTAL_SHAREHOLDERS` thresholds are 400 at `GLOBAL_SELECT` and `GLOBAL`, and 300 at
    `CAPITAL`."

    Ten consecutive days at 299 round-lot holders on a CAPITAL listing create exactly one
    ROUND_LOT_HOLDERS deficiency with consecutive_days_failed 10; the compliant bid price
    yields no BID_PRICE row.

    Design: Corner/calculations/holders_deficiency_trigger_at_ten_consecutive_days
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    record_snapshot_days(
        issuer_id, "2026-09-02", 10, closing_bid_cents=150,
        round_lot_holders=299, total_shareholders=299)
    run_monitor(issuer_id)
    rows = get_deficiency_for(issuer_id, "ROUND_LOT_HOLDERS")
    assert len(rows) == 1
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["consecutive_days_failed"] == 10
    rows = get_deficiency_for(issuer_id, "BID_PRICE")
    assert rows == []


def test_deficiency_regain_redeficiency_cycle_a(api):
    """PRD §3.4: "For every non-terminal deficiency of the issuer, the monitor recomputes
    still_open and checks for regain: if the trailing window shows at least 10 consecutive
    compliant days for the deficiency's standard, the deficiency transitions OPEN →
    REGAINED ..., a ComplianceRecord is created with method NATURAL, qualifying_days set
    to the run length, and regained_at set to the logical clock; the deficiency's
    closed_at is set."

    Design: Difficulty/non_linear_state_machine/deficiency_regain_redeficiency_cycle
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    record_snapshot_days(issuer_id, "2026-10-02", 10, closing_bid_cents=150)
    run_monitor(issuer_id)

    rows = get_deficiency_for(issuer_id, "BID_PRICE", status="REGAINED")
    assert len(rows) == 1
    assert rows[0]["id"] == def1["id"]
    assert rows[0]["still_open"] is False
    assert rows[0]["closed_at"] is not None

    records = get_success_data(api.list_compliance_records(
        issuer_id, ANALYST, params={"deficiency_id": def1["id"]}))
    assert len(records) == 1
    assert records[0]["method"] == "NATURAL"
    assert records[0]["qualifying_days"] == 10

    # Second slide: a fresh 30-day failure streak mints a NEW OPEN row (cycle re-entry)
    record_snapshot_days(issuer_id, "2026-10-12", 30, closing_bid_cents=90)
    run_monitor(issuer_id)
    rows = get_deficiency_for(issuer_id, "BID_PRICE", status="OPEN")
    assert len(rows) == 1
    assert rows[0]["id"] != def1["id"]


def test_deficiency_regain_redeficiency_cycle_b(api):
    """PRD §3.4: "For every non-terminal deficiency of the issuer, the monitor recomputes
    still_open and checks for regain: if the trailing window shows at least 10 consecutive
    compliant days for the deficiency's standard, the deficiency transitions OPEN →
    REGAINED ..., a ComplianceRecord is created with method NATURAL ..."

    Nine compliant days leave the deficiency OPEN with still_open true; the tenth flips it
    to REGAINED in the next run.

    Design: Difficulty/non_linear_state_machine/deficiency_regain_redeficiency_cycle
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    record_snapshot_days(issuer_id, "2026-10-02", 9, closing_bid_cents=150)
    run_monitor(issuer_id)
    current = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert current["status"] == "OPEN"
    assert current["still_open"] is True

    record_snapshot_days(issuer_id, "2026-10-11", 1, closing_bid_cents=150)
    run_monitor(issuer_id)
    current = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert current["status"] == "REGAINED"
    assert current["still_open"] is False
    assert current["closed_at"] is not None


def test_monitor_run_reconciles_still_open_on_every_execution(api):
    """PRD §3.4: "For every non-terminal deficiency of the issuer, the monitor recomputes
    still_open and checks for regain: if the trailing window shows at least 10 consecutive
    compliant days for the deficiency's standard, the deficiency transitions OPEN →
    REGAINED ..."
    PRD §2.4: version is "an integer starting at 1, incremented on every mutation".

    Design: Corner/cross_cutting_complexity_layers/monitor_run_reconciles_still_open_on_every_execution
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    record_snapshot_days(issuer_id, "2026-10-02", 9, closing_bid_cents=150)
    run_monitor(issuer_id)
    current = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert current["still_open"] is True
    assert current["status"] == "OPEN"

    record_snapshot_days(issuer_id, "2026-10-11", 1, closing_bid_cents=150)
    run_monitor(issuer_id)
    current = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert current["still_open"] is False
    assert current["status"] == "REGAINED"
    assert current["version"] > def1["version"]


def test_deficiency_get_returns_full_row(api):
    """PRD §3.4: "the system creates a Deficiency with tier_at_detection set to the
    listing's current tier, consecutive_days_failed set to the run length, detected_at set
    to the logical clock, compliance_due_at set to 180 calendar days after detection, and
    status OPEN."

    Design: Corner/endpoints/deficiency_get_returns_full_row
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    resp = api.get_deficiency(issuer_id, def1["id"], ANALYST)
    data = validate_success(resp, 200)
    assert data["standard_code"] == "BID_PRICE"
    assert data["status"] == "OPEN"
    assert data["consecutive_days_failed"] == 30
    assert data["tier_at_detection"] == "CAPITAL"
    assert data["detected_at"].startswith("2026-10-01")
    assert data["compliance_due_at"].startswith("2027-03-30")
    assert data["still_open"] is True
    assert data.get("staff_determined_at") is None


def test_plan_filing_moves_deficiency_open_to_plan_submitted(api):
    """PRD §3.5: "Filing the plan transitions the deficiency `OPEN` → `PLAN_SUBMITTED`."

    Design: Corner/state_machines/plan_filing_moves_deficiency_open_to_plan_submitted
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    resp = api.create_compliance_plan(
        issuer_id, create_compliance_plan_payload(def1["id"]),
        make_issuer_officer_headers(issuer_id))
    plan = validate_success(resp, 201)
    assert plan["status"] == "PENDING_REVIEW"
    assert plan["deficiency_id"] == def1["id"]
    assert plan["plan_kind"] == "CURE_IN_PLACE"
    current = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert current["status"] == "PLAN_SUBMITTED"


def test_plan_second_review_returns_plan_under_review(api):
    """PRD §3.5: "The plan must be PENDING_REVIEW; a second review attempt on an
    already-decided plan is rejected with ERR_PLAN_UNDER_REVIEW (HTTP 409)."
    "Rejecting a plan leaves the deficiency in PLAN_SUBMITTED, allowing staff to proceed
    to a delisting determination."

    Design: Corner/state_machines/plan_second_review_returns_plan_under_review
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    resp = api.create_compliance_plan(
        issuer_id, create_compliance_plan_payload(def1["id"]),
        make_issuer_officer_headers(issuer_id))
    plan = validate_success(resp, 201)
    resp = api.review_compliance_plan(
        issuer_id, plan["id"],
        {"decision": "REJECT", "review_decision_reason": "not credible"}, ANALYST)
    rejected = validate_success(resp, 200)
    assert rejected["status"] == "REJECTED"

    resp = api.review_compliance_plan(
        issuer_id, plan["id"],
        {"decision": "APPROVE", "review_decision_reason": "second thoughts"}, ANALYST)
    validate_error(resp, ApiErrorId.ERR_PLAN_UNDER_REVIEW)
    current = get_success_data(api.get_compliance_plan(issuer_id, plan["id"], ANALYST))
    assert current["status"] == "REJECTED"
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "PLAN_SUBMITTED"


def test_plan_approve_reject_preserves_plan_singleton_a(api):
    """PRD §3.5: "At most one plan ever exists per deficiency; filing against a non-OPEN
    deficiency, a lapsed cure period, or a deficiency that already has a plan is rejected
    with ERR_PLAN_NOT_ALLOWED (HTTP 422)."

    After the single plan is REJECTED, a second filing for the same deficiency fails and
    the rejected row remains the only plan.

    Design: Difficulty/compensating_invariant/plan_approve_reject_preserves_plan_singleton
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    resp = api.create_compliance_plan(
        issuer_id, create_compliance_plan_payload(def1["id"]),
        make_issuer_officer_headers(issuer_id))
    plan = validate_success(resp, 201)
    api.review_compliance_plan(
        issuer_id, plan["id"],
        {"decision": "REJECT", "review_decision_reason": "not credible"}, ANALYST)

    resp = api.create_compliance_plan(
        issuer_id,
        create_compliance_plan_payload(def1["id"], plan_text="a second plan attempt"),
        make_issuer_officer_headers(issuer_id))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ALLOWED)

    plans = get_success_data(api.list_compliance_plans(
        issuer_id, ANALYST, params={"deficiency_id": def1["id"]}))
    assert len(plans) == 1
    assert plans[0]["id"] == plan["id"]
    assert plans[0]["status"] == "REJECTED"
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "PLAN_SUBMITTED"


def test_plan_approve_reject_preserves_plan_singleton_b(api):
    """PRD §3.5: "At most one plan ever exists per deficiency ... a deficiency that
    already has a plan is rejected with ERR_PLAN_NOT_ALLOWED (HTTP 422)."

    The singleton holds even before any review: a second filing against a deficiency whose
    first plan is still PENDING_REVIEW fails with ERR_PLAN_NOT_ALLOWED.

    Design: Difficulty/compensating_invariant/plan_approve_reject_preserves_plan_singleton
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    api.create_compliance_plan(
        issuer_id, create_compliance_plan_payload(def1["id"]),
        make_issuer_officer_headers(issuer_id))
    resp = api.create_compliance_plan(
        issuer_id,
        create_compliance_plan_payload(def1["id"], plan_text="duplicate plan"),
        make_issuer_officer_headers(issuer_id))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ALLOWED)
    plans = get_success_data(api.list_compliance_plans(
        issuer_id, ANALYST, params={"deficiency_id": def1["id"]}))
    assert len(plans) == 1


def test_plan_approval_tier_transfer_cascade_a(api):
    """PRD §3.5: "Approving a `TIER_TRANSFER` plan transitions the deficiency
    `PLAN_SUBMITTED` → `REGAINED`, creates a `ComplianceRecord` with `method` `TIER_TRANSFER` and
    `qualifying_days` 0, and updates the listing's `tier` to the `proposed_target_tier`."

    Design: Difficulty/transitive_cascade/plan_approval_tier_transfer_cascade
    """
    # GLOBAL issuer passing entry S2 (MVLS 8,000,000,000,000 >= 7,500,000,000,000,
    # MVUPH 3,000,000,000 >= 2,000,000,000, holders 500 >= 400, market makers 4 >= 3)
    base = setup_bid_deficiency(
        bid_cents=90, fail_days=30, tier="GLOBAL",
        market_value_listed_securities_cents=8_000_000_000_000,
        market_value_unrestricted_publicly_held_cents=3_000_000_000,
        round_lot_holders=500, total_shareholders=500, market_makers=4)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    listing_id = base["listing"]["id"]
    resp = api.create_compliance_plan(
        issuer_id,
        create_compliance_plan_payload(
            def1["id"], plan_kind="TIER_TRANSFER", proposed_target_tier="CAPITAL",
            plan_text="Transfer to the Capital tier where our metrics comply"),
        make_issuer_officer_headers(issuer_id))
    plan = validate_success(resp, 201)

    resp = api.review_compliance_plan(
        issuer_id, plan["id"],
        {"decision": "APPROVE",
         "review_decision_reason": "Continued standards of CAPITAL are met per the latest snapshot"},
        ANALYST)
    reviewed = validate_success(resp, 200)
    assert reviewed["status"] == "APPROVED"

    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "REGAINED"

    records = get_success_data(api.list_compliance_records(
        issuer_id, ANALYST, params={"deficiency_id": def1["id"]}))
    assert len(records) == 1
    assert records[0]["method"] == "TIER_TRANSFER"
    assert records[0]["qualifying_days"] == 0

    listing = get_success_data(api.get_listing(issuer_id, listing_id, ANALYST))
    assert listing["tier"] == "CAPITAL"
    assert listing["status"] == "ACTIVE"


def test_plan_approval_tier_transfer_cascade_b(api):
    """PRD §3.5: "Approving a `CURE_IN_PLACE` plan transitions the deficiency
    `PLAN_SUBMITTED` → `REGAINED` and creates a `ComplianceRecord` with `method` `PLAN_APPROVED` and
    `qualifying_days` 0."

    Design: Difficulty/transitive_cascade/plan_approval_tier_transfer_cascade
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30, tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    listing_id = base["listing"]["id"]
    resp = api.create_compliance_plan(
        issuer_id, create_compliance_plan_payload(def1["id"]),
        make_issuer_officer_headers(issuer_id))
    plan = validate_success(resp, 201)
    resp = api.review_compliance_plan(
        issuer_id, plan["id"],
        {"decision": "APPROVE", "review_decision_reason": "credible cure"}, ANALYST)
    reviewed = validate_success(resp, 200)
    assert reviewed["status"] == "APPROVED"

    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "REGAINED"
    records = get_success_data(api.list_compliance_records(
        issuer_id, ANALYST, params={"deficiency_id": def1["id"]}))
    assert len(records) == 1
    assert records[0]["method"] == "PLAN_APPROVED"
    assert records[0]["qualifying_days"] == 0
    listing = get_success_data(api.get_listing(issuer_id, listing_id, ANALYST))
    assert listing["tier"] == "CAPITAL"
    assert listing["status"] == "ACTIVE"


def test_entry_fee_tier_and_year_recorded_from_clock(api):
    """PRD §3.3: "an `ENTRY` `FeeAssessment` is created with `tier` equal to the application's
    `target_tier`, `assessment_year` equal to the logical-clock year, `shares_outstanding` equal
    to the application's `unrestricted_publicly_held_shares`, and status `PENDING`."
    PRD §3.10: "For CAPITAL: 1 to 5,000,000 shares yields 5,000,000 to 7,500,000 cents;
    5,000,001 to 15,000,000 shares yields 7,500,000 to 10,000,000 cents. Bracket
    membership is inclusive on both ends"; "The fee is created in `PENDING` status and
    immediately becomes `INVOICED`".

    Design: Corner/calculations/entry_fee_tier_and_year_recorded_from_clock
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(
        issuer["id"], target_tier="CAPITAL",
        unrestricted_publicly_held_shares=2_000_000)
    submit_application(issuer["id"], app["id"])
    validate_success(_approve(api, issuer["id"], app["id"]), 200)

    fee = get_entry_fee(issuer["id"])
    assert fee["fee_kind"] == "ENTRY"
    assert fee["tier"] == "CAPITAL"
    assert fee["assessment_year"] == 2026
    assert fee["shares_outstanding"] == 2_000_000
    # PRD §3.10 CAPITAL entry row "1 to 5,000,000 shares yields 5,000,000 to
    # 7,500,000 cents" bounds the charge; PRD does not state the in-bracket rule.
    assert 5_000_000 <= fee["amount_cents"] <= 7_500_000
    assert fee["status"] == "INVOICED"
    assert fee["delisted_mid_year"] is False


def test_fee_bracket_upper_boundary_membership_a(api):
    """PRD §3.10: "For CAPITAL: 1 to 5,000,000 shares yields 3,000,000 to 5,000,000
    cents; 5,000,001 to 15,000,000 shares yields 4,000,000 to 6,500,000 cents; above
    15,000,000 shares yields 5,000,000 to 8,000,000 cents. Bracket membership is inclusive
    on both ends; every share count of at least 1 belongs to exactly one row; counts above
    the top row's upper bound clamp to the top row's maximum."

    15,000,000 shares sits on the inclusive upper edge of bracket 2; 15,000,001 shares
    falls into bracket 3. Both amounts must land inside their PRD-stated bracket ranges
    ("5,000,001 to 15,000,000 shares yields 4,000,000 to 6,500,000 cents; above
    15,000,000 shares yields 5,000,000 to 8,000,000 cents") — PRD does not state the
    in-bracket rule, so the amounts need not differ.

    Design: Difficulty/boundary_precision_check/fee_bracket_upper_boundary_membership
    """
    reset_clock()
    issuer_a = create_issuer()
    app_a = create_application(issuer_a["id"], target_tier="CAPITAL")
    submit_application(issuer_a["id"], app_a["id"])
    validate_success(_approve(api, issuer_a["id"], app_a["id"]), 200)

    issuer_b = create_issuer()
    app_b = create_application(issuer_b["id"], target_tier="CAPITAL")
    submit_application(issuer_b["id"], app_b["id"])
    validate_success(_approve(api, issuer_b["id"], app_b["id"]), 200)

    fee_a = validate_success(
        api.run_annual_fees(
            issuer_a["id"],
            {"shares_outstanding": 15_000_000,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer_a["id"], ANALYST))["version"]},
            FINANCE), 201)
    assert 4_000_000 <= fee_a["amount_cents"] <= 6_500_000

    fee_b = validate_success(
        api.run_annual_fees(
            issuer_b["id"],
            {"shares_outstanding": 15_000_001,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer_b["id"], ANALYST))["version"]},
            FINANCE), 201)
    assert 5_000_000 <= fee_b["amount_cents"] <= 8_000_000


def test_fee_bracket_upper_boundary_membership_b(api):
    """PRD §3.10: "For CAPITAL: 1 to 5,000,000 shares yields 3,000,000 to 5,000,000
    cents; 5,000,001 to 15,000,000 shares yields 4,000,000 to 6,500,000 cents ... Bracket
    membership is inclusive on both ends."

    5,000,000 shares sits on the inclusive upper edge of bracket 1 ("1 to 5,000,000
    shares yields 3,000,000 to 5,000,000 cents"); 5,000,001 shares falls into bracket 2
    ("5,000,001 to 15,000,000 shares yields 4,000,000 to 6,500,000 cents"). Both amounts
    must land inside their PRD-stated bracket ranges — PRD does not state the in-bracket
    rule, so the amounts need not differ.

    Design: Difficulty/boundary_precision_check/fee_bracket_upper_boundary_membership
    """
    reset_clock()
    issuer_a = create_issuer()
    app_a = create_application(issuer_a["id"], target_tier="CAPITAL")
    submit_application(issuer_a["id"], app_a["id"])
    validate_success(_approve(api, issuer_a["id"], app_a["id"]), 200)

    issuer_b = create_issuer()
    app_b = create_application(issuer_b["id"], target_tier="CAPITAL")
    submit_application(issuer_b["id"], app_b["id"])
    validate_success(_approve(api, issuer_b["id"], app_b["id"]), 200)

    fee_a = validate_success(
        api.run_annual_fees(
            issuer_a["id"],
            {"shares_outstanding": 5_000_000,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer_a["id"], ANALYST))["version"]},
            FINANCE), 201)
    assert 3_000_000 <= fee_a["amount_cents"] <= 5_000_000

    fee_b = validate_success(
        api.run_annual_fees(
            issuer_b["id"],
            {"shares_outstanding": 5_000_001,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer_b["id"], ANALYST))["version"]},
            FINANCE), 201)
    assert 4_000_000 <= fee_b["amount_cents"] <= 6_500_000
