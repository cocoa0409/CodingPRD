"""Validation, RBAC, temporal-window, and OCC corners (PRD §2.1, §2.5, §2.7, §2.9, §3.4-§3.6, §3.10)."""
from test_helpers import (
    ApiErrorId,
    advance_clock_past_cure,
    create_application,
    create_application_payload,
    create_hearings_review_payload,
    create_issuer,
    get_bid_deficiency,
    get_entry_fee,
    get_success_data,
    make_issuer_officer_headers,
    record_snapshot_days,
    reset_clock,
    run_monitor,
    setup_bid_deficiency,
    setup_filed_appeal,
    setup_listed_issuer,
    setup_staff_determined_deficiency,
    staff_determine,
    submit_application,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["listing_analyst_headers"]
HEARINGS = TEST_USERS["hearings_officer_headers"]
COUNCIL = TEST_USERS["listings_council_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _approve(api, issuer_id, app_id):
    version = get_success_data(api.get_issuer(issuer_id, ANALYST))["version"]
    return api.approve_application(issuer_id, app_id, version, ANALYST)


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request must carry two headers: X-User-ID and X-User-Role. The
    absence or emptiness of either header is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    reset_clock()
    resp = api.list_issuers({})
    err = validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert err["error_id"] == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
    assert err["message"]
    assert resp.json()["response_type"] == "error"


def test_nested_unknown_application_returns_application_not_found(api):
    """PRD §2.9: "URL path parameters are validated left-to-right: the issuer is resolved
    before any nested resource. An unknown nested identifier yields the entity-specific
    404 error—ERR_ISSUER_NOT_FOUND, ERR_APPLICATION_NOT_FOUND, ...—depending on which path
    segment failed to resolve."

    Design: Corner/validations/nested_unknown_application_returns_application_not_found
    """
    reset_clock()
    issuer = create_issuer()
    resp = api.get_listing_application(
        issuer["id"], "00000000-0000-4000-8000-000000000009", ANALYST)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_second_pending_application_returns_multiple_pending(api):
    """PRD §3.2: "The issuer must not already have another SUBMITTED application; if it
    does, the submit is rejected with ERR_MULTIPLE_PENDING_APPLICATIONS (HTTP 409)."

    Design: Corner/validations/second_pending_application_returns_multiple_pending
    """
    reset_clock()
    issuer = create_issuer()
    app_a = create_application(issuer["id"], target_tier="CAPITAL")
    submit_application(issuer["id"], app_a["id"])
    app_b = create_application(issuer["id"], target_tier="GLOBAL")
    resp = api.submit_application(
        issuer["id"], app_b["id"], make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_MULTIPLE_PENDING_APPLICATIONS)
    current = get_success_data(api.get_listing_application(issuer["id"], app_b["id"], ANALYST))
    assert current["status"] == "DRAFT"


def test_readmission_for_non_delisted_issuer_is_barred(api):
    """PRD §3.1: "A readmission application is selected by passing `readmission` as true; the issuer must be
    `DELISTED` and must never have had a prior `READMISSION` application rejected—otherwise the
    create is rejected with `ERR_READMISSION_BARRED` (HTTP 422)."

    Design: Corner/validations/readmission_for_non_delisted_issuer_is_barred
    """
    reset_clock()
    issuer = create_issuer()
    payload = create_application_payload(target_tier="CAPITAL", readmission=True)
    resp = api.create_listing_application(
        issuer["id"], payload, make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_READMISSION_BARRED)
    rows = get_success_data(api.list_listing_applications(issuer["id"], ANALYST))
    assert rows == []


def test_snapshot_with_wrong_trade_date_returns_date_mismatch(api):
    """PRD §3.4: "A ListingAnalyst records end-of-day market observations for an issuer
    by submitting a trade_date (which must equal the logical clock's current date and must
    be unique per issuer—violations are ERR_SNAPSHOT_DATE_MISMATCH, HTTP 422) ..."

    Design: Corner/validations/snapshot_with_wrong_trade_date_returns_date_mismatch
    """
    reset_clock()
    issuer = create_issuer()
    resp = api.create_snapshot(
        issuer["id"],
        {"trade_date": "2026-09-02", "closing_bid_cents": 150,
         "market_value_publicly_held_cents": 500_000_000,
         "market_value_listed_securities_cents": 600_000_000_000,
         "round_lot_holders": 400, "total_shareholders": 400},
        ANALYST)
    validate_error(resp, ApiErrorId.ERR_SNAPSHOT_DATE_MISMATCH)
    rows = get_success_data(api.list_snapshots(issuer["id"], ANALYST))
    assert rows == []


def test_snapshot_trade_date_uniqueness_half_open_day_a(api):
    """PRD §3.4: "A ListingAnalyst records end-of-day market observations for an issuer
    by submitting a trade_date (which must equal the logical clock's current date and must
    be unique per issuer—violations are ERR_SNAPSHOT_DATE_MISMATCH, HTTP 422) ..."

    A second snapshot for an occupied trade_date is rejected even though its payload
    differs.

    Design: Difficulty/resource_temporal_overlap/snapshot_trade_date_uniqueness_half_open_day
    """
    reset_clock()
    issuer = create_issuer()
    first = validate_success(api.create_snapshot(
        issuer["id"],
        {"trade_date": "2026-09-01", "closing_bid_cents": 150,
         "market_value_publicly_held_cents": 500_000_000,
         "market_value_listed_securities_cents": 600_000_000_000,
         "round_lot_holders": 400, "total_shareholders": 400},
        ANALYST), 201)
    resp = api.create_snapshot(
        issuer["id"],
        {"trade_date": "2026-09-01", "closing_bid_cents": 90,
         "market_value_publicly_held_cents": 500_000_000,
         "market_value_listed_securities_cents": 600_000_000_000,
         "round_lot_holders": 400, "total_shareholders": 400},
        ANALYST)
    validate_error(resp, ApiErrorId.ERR_SNAPSHOT_DATE_MISMATCH)
    rows = get_success_data(api.list_snapshots(issuer["id"], ANALYST))
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["closing_bid_cents"] == 150


def test_snapshot_trade_date_uniqueness_half_open_day_b(api):
    """PRD §3.4: "... trade_date (which must equal the logical clock's current date and
    must be unique per issuer—violations are ERR_SNAPSHOT_DATE_MISMATCH, HTTP 422) ..."

    Uniqueness is scoped to the issuer: the same trade_date on a different issuer is a
    free slot and records fine.

    Design: Difficulty/resource_temporal_overlap/snapshot_trade_date_uniqueness_half_open_day
    """
    reset_clock()
    issuer_a = create_issuer()
    issuer_b = create_issuer()
    validate_success(api.create_snapshot(
        issuer_a["id"],
        {"trade_date": "2026-09-01", "closing_bid_cents": 150,
         "market_value_publicly_held_cents": 500_000_000,
         "market_value_listed_securities_cents": 600_000_000_000,
         "round_lot_holders": 400, "total_shareholders": 400},
        ANALYST), 201)
    resp = api.create_snapshot(
        issuer_b["id"],
        {"trade_date": "2026-09-01", "closing_bid_cents": 90,
         "market_value_publicly_held_cents": 500_000_000,
         "market_value_listed_securities_cents": 600_000_000_000,
         "round_lot_holders": 400, "total_shareholders": 400},
        ANALYST)
    snap = validate_success(resp, 201)
    assert snap["issuer_id"] == issuer_b["id"]
    assert snap["closing_bid_cents"] == 90


def test_duplicate_ticker_symbol_returns_invalid_request(api):
    """PRD §3.1: "The ticker must be unique across all issuers regardless of status; a
    duplicate is rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/validations/duplicate_ticker_symbol_returns_invalid_request
    """
    reset_clock()
    create_issuer(legal_name="Corner Creation Corp", ticker_symbol="CCRT")
    resp = api.create_issuer(
        {"legal_name": "Copycat Corp", "ticker_symbol": "CCRT"}, ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows = get_success_data(api.list_issuers(ANALYST))
    assert len(rows) == 1


def test_annual_fee_second_run_same_year_returns_already_assessed(api):
    """PRD §3.10: "The issuer must be LISTED with an ACTIVE listing; no ANNUAL fee
    assessment may already exist for the clock year; and shares_outstanding must be at
    least 1. Violation of any of these is rejected with ERR_FEE_ALREADY_ASSESSED
    (HTTP 409)."

    Design: Corner/validations/annual_fee_second_run_same_year_returns_already_assessed
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    version = get_success_data(api.get_issuer(issuer_id, ANALYST))["version"]
    validate_success(api.run_annual_fees(
        issuer_id, {"shares_outstanding": 3_000_000, "expected_issuer_version": version},
        FINANCE), 201)

    version = get_success_data(api.get_issuer(issuer_id, ANALYST))["version"]
    resp = api.run_annual_fees(
        issuer_id, {"shares_outstanding": 3_000_000, "expected_issuer_version": version},
        FINANCE)
    validate_error(resp, ApiErrorId.ERR_FEE_ALREADY_ASSESSED)
    rows = get_success_data(api.list_fee_assessments(
        issuer_id, FINANCE, params={"fee_kind": "ANNUAL"}))
    assert len(rows) == 1


def test_approve_with_stale_issuer_version_returns_412(api):
    """PRD §2.7: "A request to run annual fee assessment must likewise carry
    expected_issuer_version matching the issuer's current version. If the issuer's version
    has advanced since the client last observed it, the request is rejected with
    ERR_STALE_VERSION (HTTP 412)." and "the issuer's `version` increments by 1"
    (PRD §3.10, annual fee side effect). PRD §3.10 also makes the duplicate-year run
    itself a violation: "no ANNUAL fee assessment may already exist for the clock year ...
    Violation of any of these is rejected with ERR_FEE_ALREADY_ASSESSED (HTTP 409)".

    The first annual run bumps the issuer version; replaying the captured version is
    stale. The replayed request violates both rules at once and PRD does not rank them,
    so either ERR_STALE_VERSION or ERR_FEE_ALREADY_ASSESSED is acceptable — the
    invariant under test is that exactly one ANNUAL row exists afterwards.

    Design: Corner/cross_cutting_complexity_layers/approve_with_stale_issuer_version_returns_412
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    captured_version = get_success_data(api.get_issuer(issuer_id, ANALYST))["version"]
    validate_success(api.run_annual_fees(
        issuer_id,
        {"shares_outstanding": 3_000_000, "expected_issuer_version": captured_version},
        FINANCE), 201)

    resp = api.run_annual_fees(
        issuer_id,
        {"shares_outstanding": 3_000_000, "expected_issuer_version": captured_version},
        FINANCE)
    actual = validate_error_is_one_of(
        resp, ["ERR_STALE_VERSION", "ERR_FEE_ALREADY_ASSESSED"])
    assert actual != "ERR_INVALID_STATE"
    rows = get_success_data(api.list_fee_assessments(
        issuer_id, FINANCE, params={"fee_kind": "ANNUAL"}))
    assert len(rows) == 1


def test_issuer_officer_cannot_approve_application(api):
    """PRD §4 endpoint table: "POST /issuers/{issuerId}/listing-applications/
    {applicationId}/approve — Approve a SUBMITTED application (OCC on issuer version) —
    ListingAnalyst". PRD §2.1: a role not authorized for the endpoint fails with
    `ERR_UNAUTHORIZED_ROLE` (PRD §2.1: "otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)").

    Design: Corner/rbac/issuer_officer_cannot_approve_application
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(issuer["id"], target_tier="CAPITAL")
    submit_application(issuer["id"], app["id"])
    version = get_success_data(api.get_issuer(issuer["id"], ANALYST))["version"]
    resp = api.approve_application(
        issuer["id"], app["id"], version, make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    current = get_success_data(api.get_listing_application(issuer["id"], app["id"], ANALYST))
    assert current["status"] == "SUBMITTED"
    listings = get_success_data(api.list_listings(issuer["id"], ANALYST))
    assert listings == []


def test_finance_officer_cannot_run_deficiency_monitor(api):
    """PRD §4 endpoint table: "POST /issuers/{issuerId}/deficiency-monitor/run — Run
    deficiency detection + regain scan for one issuer — ListingAnalyst". PRD §2.1: a role
    not authorized for the endpoint "otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)".

    Design: Corner/rbac/finance_officer_cannot_run_deficiency_monitor
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    resp = api.run_deficiency_monitor(issuer_id, FINANCE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    rows = get_success_data(api.list_deficiencies(issuer_id, ANALYST))
    assert rows == []


def test_hearings_officer_cannot_render_council_decision(api):
    """PRD §4 endpoint table: "POST | /issuers/{issuerId}/appeals/{appealId}/council-decision |
    Council affirms or reverses (terminal) | ListingsCouncil". PRD §2.1: a role not
    authorized for the endpoint "otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)".

    Design: Corner/rbac/hearings_officer_cannot_render_council_decision
    """
    base = setup_filed_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    appeal = base["appeal"]
    validate_success(api.appeal_panel_review(issuer_id, appeal["id"], HEARINGS), 200)
    validate_success(
        api.appeal_panel_decision(issuer_id, appeal["id"], {"decision": "AFFIRM"}, HEARINGS),
        200)
    validate_success(api.appeal_council_review(issuer_id, appeal["id"], COUNCIL), 200)

    resp = api.appeal_council_decision(
        issuer_id, appeal["id"], {"decision": "AFFIRM"}, HEARINGS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    current = get_success_data(api.get_appeal(issuer_id, appeal["id"], ANALYST))
    assert current["status"] == "COUNCIL_REVIEWING"


def test_auth_unauthorized_trumps_business_plan_not_allowed_a(api):
    """PRD §4 endpoint table: "POST /issuers/{issuerId}/compliance-plans — File a
    compliance plan against an OPEN deficiency — IssuerOfficer". PRD §2.1: a role not
    authorized for the endpoint "otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)".

    A FinanceOfficer filing a plan against a REGAINED (non-OPEN) deficiency hits the role
    gate: 403 ERR_UNAUTHORIZED_ROLE, and no plan row is created.

    Design: Difficulty/priority_pair_validation_conflict/auth_unauthorized_trumps_business_plan_not_allowed
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    record_snapshot_days(issuer_id, "2026-10-02", 10, closing_bid_cents=150)
    run_monitor(issuer_id)
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "REGAINED"

    resp = api.create_compliance_plan(
        issuer_id,
        {"deficiency_id": def1["id"], "plan_text": "late plan", "plan_kind": "CURE_IN_PLACE"},
        FINANCE)
    err = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert err["error_id"] == "ERR_UNAUTHORIZED_ROLE"
    assert err["error_id"] != "ERR_PLAN_NOT_ALLOWED"
    plans = get_success_data(api.list_compliance_plans(issuer_id, ANALYST))
    assert plans == []


def test_auth_unauthorized_trumps_business_plan_not_allowed_b(api):
    """PRD §4 endpoint table: "POST /issuers/{issuerId}/compliance-plans — File a
    compliance plan against an OPEN deficiency — IssuerOfficer". PRD §2.1: a role not
    authorized for the endpoint "otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)".

    A ListingAnalyst (the adjudication role) is likewise not the filing role: the same
    request against a perfectly OPEN deficiency is denied 403 before any business rule.

    Design: Difficulty/priority_pair_validation_conflict/auth_unauthorized_trumps_business_plan_not_allowed
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    resp = api.create_compliance_plan(
        issuer_id,
        {"deficiency_id": def1["id"], "plan_text": "analyst-filed plan",
         "plan_kind": "CURE_IN_PLACE"},
        ANALYST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    plans = get_success_data(api.list_compliance_plans(issuer_id, ANALYST))
    assert plans == []


def test_state_invalid_state_trumps_temporal_cure_period_a(api):
    """PRD §3.6: "A ListingAnalyst may issue a staff delisting determination. For an OPEN
    deficiency, the logical clock must be strictly after compliance_due_at ..." — the
    determination transition exists only from OPEN / PLAN_SUBMITTED; repeating it on a
    STAFF_DELIST_DETERMINED deficiency targets a resource whose state has no such transition (PRD §5
    `ERR_INVALID_STATE`), never `ERR_CURE_PERIOD_ACTIVE`.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_state_trumps_temporal_cure_period
    """
    base = setup_staff_determined_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]

    resp = api.staff_determine_delisting(issuer_id, def1["id"], ANALYST)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"
    assert err["error_id"] != "ERR_CURE_PERIOD_ACTIVE"
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "STAFF_DELIST_DETERMINED"


def test_state_invalid_state_trumps_temporal_cure_period_b(api):
    """PRD §3.6: "For an OPEN deficiency, the logical clock must be strictly after
    compliance_due_at; otherwise the request is rejected with ERR_CURE_PERIOD_ACTIVE
    (HTTP 422)."

    Isolated temporal failure: the deficiency is OPEN (the transition exists) but the
    clock has not crossed the cure deadline.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_state_trumps_temporal_cure_period
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]

    resp = api.staff_determine_delisting(issuer_id, def1["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE)
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "OPEN"


def test_appeal_window_and_cure_period_expire_by_logical_clock(api):
    """PRD §3.6: "For an OPEN deficiency, the logical clock must be strictly after
    compliance_due_at; otherwise the request is rejected with ERR_CURE_PERIOD_ACTIVE
    (HTTP 422)."
    PRD §3.5: "An IssuerOfficer files a compliance plan, naming the target deficiency via
    deficiency_id, against an OPEN deficiency whose compliance_due_at is strictly in the
    future."
    PRD §2.5: "All temporal rules—cure windows, appeal windows, snapshot date validation,
    annual fee billing—read from this logical clock."

    While the cure window is open the determination fails and the plan filing succeeds;
    compliance_due_at derives only from detected_at (logical clock).

    Design: Corner/cross_cutting_complexity_layers/appeal_window_and_cure_period_expire_by_logical_clock
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]

    # clock still inside the cure window (day after detection)
    reset_clock("2026-10-02T00:00:00Z")
    resp = api.staff_determine_delisting(issuer_id, def1["id"], ANALYST)
    err = validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE)
    assert err["error_id"] == "ERR_CURE_PERIOD_ACTIVE"

    resp = api.create_compliance_plan(
        issuer_id,
        {"deficiency_id": def1["id"], "plan_text": "timely plan",
         "plan_kind": "CURE_IN_PLACE"},
        make_issuer_officer_headers(issuer_id))
    plan = validate_success(resp, 201)
    assert plan["status"] == "PENDING_REVIEW"
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "PLAN_SUBMITTED"
    assert deficiency["compliance_due_at"].startswith("2027-03-30")


def test_appeal_window_half_open_vs_cure_interval_gap_a(api):
    """PRD §3.6: "The appeal must be filed while the deficiency is STAFF_DELIST_DETERMINED
    and no later than 7 calendar days after staff_determined_at; filing outside this
    window is rejected with ERR_APPEAL_WINDOW_CLOSED (HTTP 422)."

    An appeal filed 8 days after the staff determination misses the window entirely.

    Design: Difficulty/resource_temporal_overlap/appeal_window_half_open_vs_cure_interval_gap
    """
    base = setup_staff_determined_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    # detection 2026-10-01; due = +180d = 2027-03-30; strictly-past = 2027-03-31
    assert def1["staff_determined_at"].startswith("2027-03-31")

    panel = validate_success(api.create_hearings_review(
        create_hearings_review_payload(issuer_id, panel_name="Panel-17"), HEARINGS), 201)
    reset_clock("2027-04-08T00:00:00Z")
    resp = api.create_appeal(
        issuer_id, {"deficiency_id": def1["id"], "review_id": panel["id"]},
        make_issuer_officer_headers(issuer_id))
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
    appeals = get_success_data(api.list_appeals(issuer_id, ANALYST))
    assert appeals == []


def test_appeal_window_half_open_vs_cure_interval_gap_b(api):
    """PRD §3.6: "The appeal must be filed while the deficiency is STAFF_DELIST_DETERMINED
    and no later than 7 calendar days after staff_determined_at; filing outside this
    window is rejected with ERR_APPEAL_WINDOW_CLOSED (HTTP 422)."

    The boundary day itself is inside the window: an appeal filed exactly 7 calendar days
    after the staff determination succeeds.

    Design: Difficulty/resource_temporal_overlap/appeal_window_half_open_vs_cure_interval_gap
    """
    base = setup_staff_determined_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    # detection 2026-10-01; due = +180d = 2027-03-30; strictly-past = 2027-03-31
    assert def1["staff_determined_at"].startswith("2027-03-31")

    panel = validate_success(api.create_hearings_review(
        create_hearings_review_payload(issuer_id, panel_name="Panel-17"), HEARINGS), 201)
    reset_clock("2027-04-07T00:00:00Z")
    resp = api.create_appeal(
        issuer_id, {"deficiency_id": def1["id"], "review_id": panel["id"]},
        make_issuer_officer_headers(issuer_id))
    appeal = validate_success(resp, 201)
    assert appeal["status"] == "FILED"


def test_mark_paid_from_pending_fee_returns_invalid_state(api):
    """PRD §3.10: "A FinanceOfficer may mark an INVOICED fee as PAID ... Attempting either
    operation on a fee not in INVOICED status is rejected with ERR_INVALID_STATE
    (HTTP 409)."

    The PENDING window is unobservable (creation invoices immediately), so the assertion
    runs against a PAID row: the second mark-paid fails 409.

    Design: Corner/state_machines/mark_paid_from_pending_fee_returns_invalid_state
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    fee = get_entry_fee(issuer_id)
    paid = validate_success(api.mark_fee_paid(issuer_id, fee["id"], FINANCE), 200)
    assert paid["status"] == "PAID"
    resp = api.mark_fee_paid(issuer_id, fee["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_fee_assessment(issuer_id, fee["id"], FINANCE))
    assert current["status"] == "PAID"


def test_waive_paid_fee_returns_invalid_state(api):
    """PRD §3.10: "A FinanceOfficer may waive an INVOICED fee, transitioning it to WAIVED.
    Attempting either operation on a fee not in INVOICED status is rejected with
    ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/waive_paid_fee_returns_invalid_state
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    fee = get_entry_fee(issuer_id)
    validate_success(api.mark_fee_paid(issuer_id, fee["id"], FINANCE), 200)
    resp = api.waive_fee(issuer_id, fee["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_fee_assessment(issuer_id, fee["id"], FINANCE))
    assert current["status"] == "PAID"


def test_error_catalog_triggerability_covered_by_scatter(api):
    """PRD §2.1: "An `IssuerOfficer` acting on a path whose `{issuerId}` segment does not
    equal `X-User-ID` is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §2.9: "An unknown nested identifier yields the entity-specific 404 error ... —
    depending on which path segment failed to resolve."

    A foreign-issuer filing is denied at the ownership gate; unknown listing and
    deficiency ids under a real issuer yield their entity-specific 404s.

    Design: Corner/errors/error_catalog_triggerability_covered_by_scatter
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(issuer["id"], target_tier="CAPITAL")
    submit_application(issuer["id"], app["id"])
    foreign = create_issuer()

    resp = api.create_listing_application(
        foreign["id"], create_application_payload(target_tier="CAPITAL"),
        make_issuer_officer_headers(issuer["id"]))
    err = validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert err["error_id"] == "ERR_OWNERSHIP_MISMATCH"

    resp = api.get_listing(
        issuer["id"], "00000000-0000-4000-8000-000000000007", ANALYST)
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND)

    resp = api.get_deficiency(
        issuer["id"], "00000000-0000-4000-8000-000000000008", ANALYST)
    validate_error(resp, ApiErrorId.ERR_DEFICIENCY_NOT_FOUND)


def test_approval_visibility_is_immediate_in_same_request_chain(api):
    """PRD §3.3: "Upon approval, the issuer's `version` increments by 1, and the application
    becomes `APPROVED`. For `INITIAL`, `TRANSFER`, and `READMISSION` applications, the system
    creates a `Listing` with `tier` set to the application's `target_tier`, `status` `ACTIVE`,
    and `application_id` recording which application's approval created the listing; the issuer's
    status becomes `LISTED`; and an `ENTRY` `FeeAssessment` is created" —
    "The fee is created in `PENDING` status and immediately becomes `INVOICED`" (PRD §3.10).

    The very next GETs in the same request chain observe every cascade hop.

    Design: Corner/consistency_model/approval_visibility_is_immediate_in_same_request_chain
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(issuer["id"], target_tier="CAPITAL")
    submit_application(issuer["id"], app["id"])
    version_before = get_success_data(api.get_issuer(issuer["id"], ANALYST))["version"]
    resp = _approve(api, issuer["id"], app["id"])
    approved = validate_success(resp, 200)
    assert approved["status"] == "APPROVED"

    issuer_now = get_success_data(api.get_issuer(issuer["id"], ANALYST))
    assert issuer_now["status"] == "LISTED"
    assert issuer_now["version"] == version_before + 1

    listings = get_success_data(api.list_listings(issuer["id"], ANALYST))
    assert len(listings) == 1
    assert listings[0]["status"] == "ACTIVE"
    assert listings[0]["tier"] == "CAPITAL"

    fee = get_entry_fee(issuer["id"])
    assert fee["fee_kind"] == "ENTRY"
    assert fee["status"] == "INVOICED"
