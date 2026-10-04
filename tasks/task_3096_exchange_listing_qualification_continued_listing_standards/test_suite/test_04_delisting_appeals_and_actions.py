"""Delisting cascade, appeals workflow, and corporate actions (PRD §3.6-§3.9)."""
from test_helpers import (
    ApiErrorId,
    create_application,
    create_compliance_plan_payload,
    create_corporate_action_payload,
    create_hearings_review_payload,
    create_issuer,
    get_bid_deficiency,
    get_deficiency_for,
    get_entry_fee,
    get_success_data,
    make_issuer_officer_headers,
    record_snapshot_days,
    reset_clock,
    run_annual_fee,
    setup_bid_deficiency,
    setup_filed_appeal,
    setup_listed_issuer,
    setup_panel_reviewing_appeal,
    run_monitor,
    setup_staff_determined_deficiency,
    submit_application,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["listing_analyst_headers"]
HEARINGS = TEST_USERS["hearings_officer_headers"]
COUNCIL = TEST_USERS["listings_council_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_appeal_filing_moves_deficiency_to_panel_review(api):
    """PRD §3.6: "Filing the appeal transitions the deficiency `STAFF_DELIST_DETERMINED` → `PANEL_REVIEW`." and "The appeal records `filed_at` as the logical-clock timestamp of
    filing."

    Design: Corner/state_machines/appeal_filing_moves_deficiency_to_panel_review
    """
    base = setup_staff_determined_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    # detection 2026-10-01; due = +180d = 2027-03-30; strictly-past = 2027-03-31
    assert def1["staff_determined_at"].startswith("2027-03-31")

    panel = validate_success(api.create_hearings_review(
        create_hearings_review_payload(issuer_id, panel_name="Panel-C"), HEARINGS), 201)
    resp = api.create_appeal(
        issuer_id, {"deficiency_id": def1["id"], "review_id": panel["id"]},
        make_issuer_officer_headers(issuer_id))
    appeal = validate_success(resp, 201)
    assert appeal["status"] == "FILED"
    assert appeal["filed_at"].startswith("2027-03-31")

    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "PANEL_REVIEW"
    assert deficiency["staff_determined_at"].startswith("2027-03-31")


def test_council_review_from_filed_appeal_returns_not_available(api):
    """PRD §3.7: "Council review is available only from PANEL_AFFIRMED or PANEL_REVERSED;
    from any other state the request is rejected with ERR_COUNCIL_REVIEW_NOT_AVAILABLE
    (HTTP 422)."

    Design: Corner/state_machines/council_review_from_filed_appeal_returns_not_available
    """
    base = setup_filed_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    appeal = base["appeal"]
    resp = api.appeal_council_review(issuer_id, appeal["id"], COUNCIL)
    validate_error(resp, ApiErrorId.ERR_COUNCIL_REVIEW_NOT_AVAILABLE)
    current = get_success_data(api.get_appeal(issuer_id, appeal["id"], ANALYST))
    assert current["status"] == "FILED"


def test_panel_decision_gated_on_hearings_review_open_a(api):
    """PRD §3.7: "A panel may be closed by a `HearingsOfficer`; an appeal that references a
    `CLOSED` panel is rejected with `ERR_HEARING_NOT_OPEN` (HTTP 422)."

    Panel-review of a FILED appeal fails once the referenced panel has been closed, even
    though the appeal itself is in the correct state.

    Design: Difficulty/cross_entity_state_dependency/panel_decision_gated_on_hearings_review_open
    """
    base = setup_filed_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    appeal = base["appeal"]
    panel = base["panel"]

    validate_success(api.close_hearings_review(panel["id"], HEARINGS), 200)
    resp = api.appeal_panel_review(issuer_id, appeal["id"], HEARINGS)
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_OPEN)

    current = get_success_data(api.get_appeal(issuer_id, appeal["id"], ANALYST))
    assert current["status"] == "FILED"
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "PANEL_REVIEW"


def test_panel_decision_gated_on_hearings_review_open_b(api):
    """PRD §3.7: "A HearingsOfficer takes a filed appeal under review; the appeal
    transitions FILED → PANEL_REVIEWING." — the same transition succeeds while the
    referenced panel is OPEN (the positive branch of the gate).

    Design: Difficulty/cross_entity_state_dependency/panel_decision_gated_on_hearings_review_open
    """
    base = setup_filed_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    appeal = base["appeal"]
    panel = base["panel"]

    panel_now = get_success_data(api.get_hearings_review(panel["id"], HEARINGS))
    assert panel_now["status"] == "OPEN"
    resp = api.appeal_panel_review(issuer_id, appeal["id"], HEARINGS)
    data = validate_success(resp, 200)
    assert data["status"] == "PANEL_REVIEWING"


def test_appeal_panel_council_fork_join_a(api):
    """PRD §3.7: "An `AFFIRM` decision transitions the appeal `PANEL_REVIEWING` →
    `PANEL_AFFIRMED`, sets `decided_by` to `PANEL`, and transitions the deficiency `PANEL_REVIEW`
    → `DELIST_UPHELD` with `closed_at` set. ... A REVERSE decision transitions the appeal
    COUNCIL_REVIEWING → COUNCIL_REVERSED, sets decided_by to COUNCIL, and transitions the
    deficiency to DELIST_REVERSED with the same new-OPEN-deficiency side effect as a panel
    reversal."

    Fork: panel AFFIRM; join: council review; terminal: council REVERSE mints a fresh OPEN
    deficiency row while the original closes DELIST_REVERSED.

    Design: Difficulty/non_linear_state_machine/appeal_panel_council_fork_join
    """
    base = setup_panel_reviewing_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    appeal = base["appeal"]
    listing_id = base["listing"]["id"]

    resp = api.appeal_panel_decision(issuer_id, appeal["id"], {"decision": "AFFIRM"}, HEARINGS)
    decided = validate_success(resp, 200)
    assert decided["status"] == "PANEL_AFFIRMED"
    assert decided["decided_by"] == "PANEL"

    validate_success(api.appeal_council_review(issuer_id, appeal["id"], COUNCIL), 200)
    resp = api.appeal_council_decision(
        issuer_id, appeal["id"], {"decision": "REVERSE"}, COUNCIL)
    decided = validate_success(resp, 200)
    assert decided["status"] == "COUNCIL_REVERSED"
    assert decided["decided_by"] == "COUNCIL"

    original = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert original["status"] == "DELIST_REVERSED"
    assert original["closed_at"] is not None

    rows = get_deficiency_for(issuer_id, "BID_PRICE")
    assert len(rows) == 2
    new_rows = [r for r in rows if r["id"] != def1["id"]]
    assert len(new_rows) == 1
    new_row = new_rows[0]
    assert new_row["status"] == "OPEN"
    assert new_row["standard_code"] == "BID_PRICE"

    listing = get_success_data(api.get_listing(issuer_id, listing_id, ANALYST))
    assert listing["status"] == "ACTIVE"

    panel_now = get_success_data(api.get_hearings_review(base["panel"]["id"], HEARINGS))
    assert panel_now["status"] == "OPEN"


def test_appeal_panel_council_fork_join_b(api):
    """PRD §3.7: "An `AFFIRM` decision transitions the appeal `COUNCIL_REVIEWING` →
    `COUNCIL_AFFIRMED`, sets `decided_by` to `COUNCIL`, and—if the deficiency is still in
    `PANEL_REVIEW`—transitions it to `DELIST_UPHELD`."

    The other branch of the fork: panel REVERSE closes the deficiency DELIST_REVERSED
    (minting a new OPEN row); the council then AFFIRMs the already-decided appeal, leaving
    the reversal intact.

    Design: Difficulty/non_linear_state_machine/appeal_panel_council_fork_join
    """
    base = setup_panel_reviewing_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    appeal = base["appeal"]

    resp = api.appeal_panel_decision(issuer_id, appeal["id"], {"decision": "REVERSE"}, HEARINGS)
    decided = validate_success(resp, 200)
    assert decided["status"] == "PANEL_REVERSED"
    assert decided["decided_by"] == "PANEL"
    original = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert original["status"] == "DELIST_REVERSED"

    validate_success(api.appeal_council_review(issuer_id, appeal["id"], COUNCIL), 200)
    resp = api.appeal_council_decision(
        issuer_id, appeal["id"], {"decision": "AFFIRM"}, COUNCIL)
    decided = validate_success(resp, 200)
    assert decided["status"] == "COUNCIL_AFFIRMED"
    assert decided["decided_by"] == "COUNCIL"
    # the deficiency was no longer PANEL_REVIEW, so the affirm leaves the reversal intact
    original = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert original["status"] == "DELIST_REVERSED"


def test_panel_reversal_conserves_open_deficiency_count_a(api):
    """PRD §3.7: "A `REVERSE` decision transitions the appeal `PANEL_REVIEWING` →
    `PANEL_REVERSED`, sets `decided_by` to `PANEL`, and transitions the deficiency `PANEL_REVIEW`
    → `DELIST_REVERSED` with `closed_at` set; a new `OPEN` deficiency row is created with the
    same `standard_code` and `tier_at_detection`, `detected_at` set to the logical clock, and
    `compliance_due_at` set to 180 days after the clock."

    The reversal closes one track and mints a fresh OPEN row: zero OPEN rows before the
    decision (the sole deficiency sits in PANEL_REVIEW), exactly one after.

    Design: Difficulty/compensating_invariant/panel_reversal_conserves_open_deficiency_count
    """
    base = setup_panel_reviewing_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    appeal = base["appeal"]

    open_before = get_deficiency_for(issuer_id, "BID_PRICE", status="OPEN")
    reversed_before = get_deficiency_for(issuer_id, "BID_PRICE", status="DELIST_REVERSED")
    assert open_before == []
    assert reversed_before == []

    validate_success(
        api.appeal_panel_decision(issuer_id, appeal["id"], {"decision": "REVERSE"}, HEARINGS),
        200)

    open_after = get_deficiency_for(issuer_id, "BID_PRICE", status="OPEN")
    reversed_after = get_deficiency_for(issuer_id, "BID_PRICE", status="DELIST_REVERSED")
    assert len(reversed_after) == 1
    assert reversed_after[0]["id"] == def1["id"]
    assert len(open_after) == 1
    assert open_after[0]["id"] != def1["id"]
    # the new row's detected_at is the reversal clock (staff determination day 2027-03-31)
    assert open_after[0]["detected_at"].startswith("2027-03-31")
    assert open_after[0]["compliance_due_at"].startswith("2027-09-27")


def test_panel_reversal_conserves_open_deficiency_count_b(api):
    """PRD §3.7: "a new OPEN deficiency row is created with the same standard_code and
    tier_at_detection, detected_at set to the logical clock, and compliance_due_at set to
    180 days after the clock. The hearings panel remains OPEN and may serve other
    appeals."

    The minted OPEN row inherits standard and tier from the reversed deficiency, and the
    panel stays OPEN for other appeals.

    Design: Difficulty/compensating_invariant/panel_reversal_conserves_open_deficiency_count
    """
    base = setup_panel_reviewing_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    appeal = base["appeal"]

    validate_success(
        api.appeal_panel_decision(issuer_id, appeal["id"], {"decision": "REVERSE"}, HEARINGS),
        200)

    open_after = get_deficiency_for(issuer_id, "BID_PRICE", status="OPEN")
    assert len(open_after) == 1
    new_row = open_after[0]
    assert new_row["standard_code"] == def1["standard_code"]
    assert new_row["tier_at_detection"] == def1["tier_at_detection"]

    panel_now = get_success_data(api.get_hearings_review(base["panel"]["id"], HEARINGS))
    assert panel_now["status"] == "OPEN"


def test_execute_delisting_transitive_cascade_a(api):
    """PRD §3.8: "Execution performs the full cascade in one request: the listing
    transitions ACTIVE → SUSPENDED with suspended_at set to the logical clock, then
    SUSPENDED → DELISTED with delisted_at set; the issuer's status becomes DELISTED; every
    PENDING fee assessment of the issuer becomes INVOICED; if no ANNUAL fee assessment ...
    exists for the logical-clock year, one is created with delisted_mid_year set to true
    ... every deficiency in OPEN, PLAN_SUBMITTED, STAFF_DELIST_DETERMINED, or
    PANEL_REVIEW becomes DELIST_UPHELD with closed_at set; every appeal in FILED or
    PANEL_REVIEWING becomes PANEL_AFFIRMED with decided_by PANEL; and every SUBMITTED
    corporate action becomes CANCELLED."

    Driven via a staff determination whose 7-day appeal window lapsed unexercised.

    Design: Difficulty/transitive_cascade/execute_delisting_transitive_cascade
    """
    base = setup_staff_determined_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    listing_id = base["listing"]["id"]

    # clock strictly past staff_determined_at + 7 days, no appeal filed
    reset_clock("2027-04-08T00:00:00Z")
    resp = api.execute_delisting(issuer_id, listing_id, ANALYST)
    listing = validate_success(resp, 200)
    assert listing["status"] == "DELISTED"
    assert listing["suspended_at"] is not None
    assert listing["delisted_at"] is not None
    assert listing["suspended_at"].startswith("2027-04-08")
    assert listing["delisted_at"].startswith("2027-04-08")

    issuer = get_success_data(api.get_issuer(issuer_id, ANALYST))
    assert issuer["status"] == "DELISTED"

    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "DELIST_UPHELD"
    assert deficiency["closed_at"] is not None

    # the fill minted the clock-year ANNUAL row (none existed) with the mid-year flag
    annual_rows = get_success_data(api.list_fee_assessments(
        issuer_id, FINANCE, params={"fee_kind": "ANNUAL", "assessment_year": 2027}))
    assert len(annual_rows) == 1
    fill = annual_rows[0]
    assert fill["delisted_mid_year"] is True
    assert fill["status"] == "INVOICED"


def test_execute_delisting_transitive_cascade_b(api):
    """PRD §3.8: "every appeal in `FILED` or
    `PANEL_REVIEWING` becomes `PANEL_AFFIRMED` with `decided_by` `PANEL`; and every `SUBMITTED`
    corporate action becomes `CANCELLED`." And on the
    fee fill: "shares_outstanding taken from the latest ANNUAL assessment if any otherwise
    from the approving application's unrestricted_publicly_held_shares".

    Driven via a decided (panel-affirmed) appeal, with a pre-existing clock-year ANNUAL
    row (fill suppressed), a waived ENTRY fee, and a live SUBMITTED corporate action.

    Design: Difficulty/transitive_cascade/execute_delisting_transitive_cascade
    """
    base = setup_panel_reviewing_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    appeal = base["appeal"]
    listing_id = base["listing"]["id"]

    # SUBMITTED corporate action and a clock-year ANNUAL row; the ENTRY fee is waived
    action = validate_success(api.create_corporate_action(
        issuer_id, create_corporate_action_payload(split_ratio_denominator=5),
        make_issuer_officer_headers(issuer_id)), 201)
    annual = run_annual_fee(issuer_id, 3_000_000)
    entry_fee = get_entry_fee(issuer_id)
    validate_success(api.waive_fee(issuer_id, entry_fee["id"], FINANCE), 200)

    # panel AFFIRM -> deficiency DELIST_UPHELD -> delisting is final
    validate_success(
        api.appeal_panel_decision(issuer_id, appeal["id"], {"decision": "AFFIRM"}, HEARINGS),
        200)
    resp = api.execute_delisting(issuer_id, listing_id, ANALYST)
    listing = validate_success(resp, 200)
    assert listing["status"] == "DELISTED"

    issuer = get_success_data(api.get_issuer(issuer_id, ANALYST))
    assert issuer["status"] == "DELISTED"

    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "DELIST_UPHELD"

    action_now = get_success_data(api.get_corporate_action(issuer_id, action["id"], ANALYST))
    assert action_now["status"] == "CANCELLED"

    annual_now = get_success_data(api.get_fee_assessment(issuer_id, annual["id"], FINANCE))
    assert annual_now["status"] == "INVOICED"
    entry_now = get_success_data(api.get_fee_assessment(issuer_id, entry_fee["id"], FINANCE))
    assert entry_now["status"] == "WAIVED"

    annual_rows = get_success_data(api.list_fee_assessments(
        issuer_id, FINANCE, params={"fee_kind": "ANNUAL", "assessment_year": 2027}))
    assert len(annual_rows) == 1


def test_fee_bracket_clamp_order_with_mid_year_surcharge_a(api):
    """PRD §3.10: "A fee row whose delisted_mid_year flag is true adds a flat surcharge of
    1,000,000 cents after the bracket clamp; the surcharge is never bracket-adjusted." and
    "counts above the top row's upper bound clamp to the top row's maximum" ("above
    15,000,000 shares yields 5,000,000 to 8,000,000 cents" for the CAPITAL annual table).
    PRD §3.8: the fill uses "the listing's tier at execution" and takes
    "`shares_outstanding` taken from the latest `ANNUAL` assessment if any otherwise
    from the approving application's `unrestricted_publicly_held_shares`".

    CAPITAL delisting fill at 20,000,000 shares (above the top bracket's upper bound, so
    the clamp applies): the mid-year surcharge must land after the clamp — the fill's
    amount strictly exceeds the surcharge alone, and a same-share non-mid-year annual
    assessment (no surcharge) is billed strictly less, by exactly 1,000,000 cents.

    Design: Difficulty/combinatorial_formula/fee_bracket_clamp_order_with_mid_year_surcharge
    """
    base = setup_staff_determined_deficiency(
        bid_cents=90, fail_days=30, entry_shares=20_000_000)
    issuer_id = base["issuer"]["id"]
    listing_id = base["listing"]["id"]

    reset_clock("2027-04-08T00:00:00Z")
    validate_success(api.execute_delisting(issuer_id, listing_id, ANALYST), 200)

    annual_rows = get_success_data(api.list_fee_assessments(
        issuer_id, FINANCE, params={"fee_kind": "ANNUAL"}))
    assert len(annual_rows) == 1
    fill = annual_rows[0]
    assert fill["assessment_year"] == 2027
    assert fill["delisted_mid_year"] is True
    assert fill["shares_outstanding"] == 20_000_000
    assert fill["status"] == "INVOICED"
    # surcharge lands after the clamp: amount = clamped bracket charge + 1,000,000
    assert fill["amount_cents"] > 1_000_000

    # control: same tier, same share count, no mid-year flag -> exactly 1,000,000 less
    reset_clock("2026-09-01T00:00:00Z")
    issuer_b = create_issuer()
    app_b = create_application(
        issuer_b["id"], target_tier="CAPITAL",
        unrestricted_publicly_held_shares=20_000_000)
    submit_application(issuer_b["id"], app_b["id"])
    version_b = get_success_data(api.get_issuer(issuer_b["id"], ANALYST))["version"]
    validate_success(
        api.approve_application(issuer_b["id"], app_b["id"], version_b, ANALYST), 200)
    control = validate_success(
        api.run_annual_fees(
            issuer_b["id"],
            {"shares_outstanding": 20_000_000,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer_b["id"], ANALYST))["version"]},
            FINANCE), 201)
    assert control["delisted_mid_year"] is False
    assert fill["amount_cents"] == control["amount_cents"] + 1_000_000


def test_fee_bracket_clamp_order_with_mid_year_surcharge_b(api):
    """PRD §3.10: "For CAPITAL: 1 to 5,000,000 shares yields 3,000,000 to 5,000,000
    cents" (annual table) and "A fee row whose delisted_mid_year flag is true adds a flat
    surcharge of 1,000,000 cents after the bracket clamp; the surcharge is never
    bracket-adjusted."

    CAPITAL delisting fill at 2,000,000 shares: the bracket min (3,000,000) governs the
    clamp, then the surcharge — 4,000,000 total.

    Design: Difficulty/combinatorial_formula/fee_bracket_clamp_order_with_mid_year_surcharge
    """
    base = setup_staff_determined_deficiency(
        bid_cents=90, fail_days=30, entry_shares=2_000_000)
    issuer_id = base["issuer"]["id"]
    listing_id = base["listing"]["id"]

    reset_clock("2027-04-08T00:00:00Z")
    validate_success(api.execute_delisting(issuer_id, listing_id, ANALYST), 200)

    annual_rows = get_success_data(api.list_fee_assessments(
        issuer_id, FINANCE, params={"fee_kind": "ANNUAL"}))
    assert len(annual_rows) == 1
    fill = annual_rows[0]
    assert fill["delisted_mid_year"] is True
    assert fill["shares_outstanding"] == 2_000_000
    assert fill["status"] == "INVOICED"

    # control: same tier, same share count, no mid-year flag -> exactly 1,000,000 less
    reset_clock("2026-09-01T00:00:00Z")
    issuer_b = create_issuer()
    app_b = create_application(
        issuer_b["id"], target_tier="CAPITAL",
        unrestricted_publicly_held_shares=2_000_000)
    submit_application(issuer_b["id"], app_b["id"])
    version_b = get_success_data(api.get_issuer(issuer_b["id"], ANALYST))["version"]
    validate_success(
        api.approve_application(issuer_b["id"], app_b["id"], version_b, ANALYST), 200)
    control = validate_success(
        api.run_annual_fees(
            issuer_b["id"],
            {"shares_outstanding": 2_000_000,
             "expected_issuer_version": get_success_data(
                 api.get_issuer(issuer_b["id"], ANALYST))["version"]},
            FINANCE), 201)
    assert control["delisted_mid_year"] is False
    assert fill["amount_cents"] == control["amount_cents"] + 1_000_000


def test_execute_delisting_blocked_while_appeal_under_review(api):
    """PRD §3.8: "An appeal in `PANEL_REVIEWING` or `COUNCIL_REVIEWING` blocks execution; the
    request is rejected with `ERR_DELISTING_BLOCKED` (HTTP 422)."

    Design: Corner/validations/execute_delisting_blocked_while_appeal_under_review
    """
    base = setup_panel_reviewing_appeal(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    listing_id = base["listing"]["id"]

    resp = api.execute_delisting(issuer_id, listing_id, ANALYST)
    validate_error(resp, ApiErrorId.ERR_DELISTING_BLOCKED)
    listing = get_success_data(api.get_listing(issuer_id, listing_id, ANALYST))
    assert listing["status"] == "ACTIVE"
    issuer = get_success_data(api.get_issuer(issuer_id, ANALYST))
    assert issuer["status"] == "LISTED"


def test_hearings_review_close_round_trips_open_then_closed(api):
    """PRD §3.7: "the panel begins `OPEN`. A panel may be closed by a `HearingsOfficer`" —
    and a second close targets a resource not in a state from which the transition exists
    (ERR_INVALID_STATE, PRD §5).

    Design: Corner/endpoints/hearings_review_close_round_trips_open_then_closed
    """
    reset_clock()
    issuer = create_issuer()
    panel = validate_success(api.create_hearings_review(
        create_hearings_review_payload(issuer["id"], panel_name="Panel-C"), HEARINGS), 201)
    assert panel["status"] == "OPEN"

    closed = validate_success(api.close_hearings_review(panel["id"], HEARINGS), 200)
    assert closed["status"] == "CLOSED"

    resp = api.close_hearings_review(panel["id"], HEARINGS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = __import__("test_helpers").validate_paginated(
        api.list_hearings_reviews(HEARINGS, params={"status": "CLOSED"}))
    assert len(rows) == 1
    assert rows[0]["id"] == panel["id"]


def test_corporate_action_reject_then_cancel_returns_invalid_state(api):
    """PRD §3.9: "A `ListingAnalyst` may reject a `SUBMITTED` action; an `IssuerOfficer` may
    cancel a `SUBMITTED` action." — REJECTED is terminal; the cancel targets a resource not
    in a state from which the transition exists (ERR_INVALID_STATE, PRD §5).

    Design: Corner/state_machines/corporate_action_reject_then_cancel_returns_invalid_state
    """
    reset_clock()
    issuer = create_issuer()
    action = validate_success(api.create_corporate_action(
        issuer["id"], create_corporate_action_payload(split_ratio_denominator=4),
        make_issuer_officer_headers(issuer["id"])), 201)
    assert action["status"] == "SUBMITTED"
    validate_success(api.reject_corporate_action(issuer["id"], action["id"], ANALYST), 200)

    resp = api.cancel_corporate_action(
        issuer["id"], action["id"], make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_corporate_action(issuer["id"], action["id"], ANALYST))
    assert current["status"] == "REJECTED"


def test_reverse_split_projection_regains_bid_deficiency(api):
    """PRD §3.9: "The system runs a split-adjusted projection over the trailing
    10-snapshot window: each day's closing_bid_cents is multiplied by the
    split_ratio_denominator ... If the projection finds at least 10 consecutive days with
    an adjusted bid of at least 100, the qualifying BID_PRICE deficiency transitions to
    REGAINED with a ComplianceRecord of method REVERSE_SPLIT and qualifying_days equal to
    the run length."

    Ten trailing days at 90 cents adjust to 450 under a 1-for-5 split.

    Design: Corner/calculations/reverse_split_projection_regains_bid_deficiency
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    action = validate_success(api.create_corporate_action(
        issuer_id, create_corporate_action_payload(split_ratio_denominator=5),
        make_issuer_officer_headers(issuer_id)), 201)

    resp = api.effect_corporate_action(issuer_id, action["id"], ANALYST)
    effected = validate_success(resp, 200)
    assert effected["status"] == "EFFECTIVE"

    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "REGAINED"
    assert deficiency["still_open"] is False
    assert deficiency["closed_at"] is not None

    records = get_success_data(api.list_compliance_records(
        issuer_id, ANALYST, params={"deficiency_id": def1["id"]}))
    assert len(records) == 1
    assert records[0]["method"] == "REVERSE_SPLIT"
    assert records[0]["qualifying_days"] == 10


def test_reverse_split_projection_fails_when_window_short(api):
    """PRD §3.9: "If the projection finds at least 10 consecutive days with an adjusted
    bid of at least 100, the qualifying BID_PRICE deficiency transitions to REGAINED ..."
    — with only 9 trailing split-adjusted compliant days the projection does not qualify;
    the action still becomes EFFECTIVE (the qualifying-deficiency gate only requires an
    OPEN or PLAN_SUBMITTED BID_PRICE deficiency) but the deficiency stays OPEN.

    Design: Corner/calculations/reverse_split_projection_fails_when_window_short
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    # day 10 back at 10 cents adjusts to 50 < 100; the latest 9 days adjust to 450
    record_snapshot_days(issuer_id, "2026-09-02", 21, closing_bid_cents=90)
    record_snapshot_days(issuer_id, "2026-09-23", 1, closing_bid_cents=10)
    record_snapshot_days(issuer_id, "2026-09-24", 8, closing_bid_cents=90)
    run_monitor(issuer_id)
    def1 = get_bid_deficiency(issuer_id)
    action = validate_success(api.create_corporate_action(
        issuer_id, create_corporate_action_payload(split_ratio_denominator=5),
        make_issuer_officer_headers(issuer_id)), 201)

    resp = api.effect_corporate_action(issuer_id, action["id"], ANALYST)
    effected = validate_success(resp, 200)
    assert effected["status"] == "EFFECTIVE"

    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "OPEN"
    assert deficiency["still_open"] is True
    records = get_success_data(api.list_compliance_records(
        issuer_id, ANALYST, params={"deficiency_id": def1["id"]}))
    assert records == []


def test_corporate_action_effect_gated_on_bid_deficiency_open_a(api):
    """PRD §3.9: "The issuer must have a `BID_PRICE` deficiency in `OPEN` or `PLAN_SUBMITTED`
    status; otherwise the request is rejected with `ERR_NO_QUALIFYING_DEFICIENCY`
    (HTTP 422)."

    Once the deficiency regains naturally, the still-SUBMITTED split can no longer be
    effected.

    Design: Difficulty/cross_entity_state_dependency/corporate_action_effect_gated_on_bid_deficiency_open
    """
    base = setup_bid_deficiency(bid_cents=90, fail_days=30)
    issuer_id = base["issuer"]["id"]
    def1 = base["deficiency"]
    action = validate_success(api.create_corporate_action(
        issuer_id, create_corporate_action_payload(split_ratio_denominator=5),
        make_issuer_officer_headers(issuer_id)), 201)

    record_snapshot_days(issuer_id, "2026-10-02", 10, closing_bid_cents=150)
    run_monitor(issuer_id)
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "REGAINED"

    resp = api.effect_corporate_action(issuer_id, action["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_NO_QUALIFYING_DEFICIENCY)
    current = get_success_data(api.get_corporate_action(issuer_id, action["id"], ANALYST))
    assert current["status"] == "SUBMITTED"
    deficiency = get_success_data(api.get_deficiency(issuer_id, def1["id"], ANALYST))
    assert deficiency["status"] == "REGAINED"


def test_corporate_action_effect_gated_on_bid_deficiency_open_b(api):
    """PRD §3.9: "The issuer must have a `BID_PRICE` deficiency in `OPEN` or `PLAN_SUBMITTED`
    status; otherwise the request is rejected with `ERR_NO_QUALIFYING_DEFICIENCY`
    (HTTP 422)."

    An issuer with no BID_PRICE deficiency at all cannot effect a reverse split.

    Design: Difficulty/cross_entity_state_dependency/corporate_action_effect_gated_on_bid_deficiency_open
    """
    base = setup_listed_issuer(tier="CAPITAL")
    issuer_id = base["issuer"]["id"]
    action = validate_success(api.create_corporate_action(
        issuer_id, create_corporate_action_payload(split_ratio_denominator=5),
        make_issuer_officer_headers(issuer_id)), 201)
    resp = api.effect_corporate_action(issuer_id, action["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_NO_QUALIFYING_DEFICIENCY)
    current = get_success_data(api.get_corporate_action(issuer_id, action["id"], ANALYST))
    assert current["status"] == "SUBMITTED"
