"""Composite setup helpers. Every fixture builds its preconditions from scratch
via PRD-declared endpoints; the runner restarts the server before each test, so
nothing carries over between tests.

Naming: setup_<outcome>() returns a dict of the ids/entities the test needs.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, CLOCK_EPOCH_DATE
from .factories import (
    create_application_payload,
    create_compliance_plan_payload,
    create_hearings_review_payload,
    create_issuer_payload,
    create_snapshot_payload,
)
from .test_users import TEST_USERS, make_issuer_officer_headers

ANALYST = TEST_USERS["listing_analyst_headers"]
HEARINGS = TEST_USERS["hearings_officer_headers"]
COUNCIL = TEST_USERS["listings_council_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + issuer primitives
# ---------------------------------------------------------------------------

def reset_clock(current_utc=CLOCK_EPOCH):
    resp = api_client.set_clock(current_utc, ANALYST)
    return get_success_data(resp)


def create_issuer(**overrides):
    resp = api_client.create_issuer(create_issuer_payload(**overrides), ANALYST)
    return get_success_data(resp)


def _current_issuer_version(issuer_id):
    return get_success_data(api_client.get_issuer(issuer_id, ANALYST))["version"]


# ---------------------------------------------------------------------------
# Tier 1: application lifecycle
# ---------------------------------------------------------------------------

def create_application(issuer_id, **overrides):
    resp = api_client.create_listing_application(
        issuer_id, create_application_payload(**overrides),
        make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def submit_application(issuer_id, app_id):
    resp = api_client.submit_application(
        issuer_id, app_id, make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def approve_application(issuer_id, app_id):
    version = _current_issuer_version(issuer_id)
    resp = api_client.approve_application(issuer_id, app_id, version, ANALYST)
    return get_success_data(resp)


def create_submitted_application(issuer_id, **overrides):
    app = create_application(issuer_id, **overrides)
    submitted = submit_application(issuer_id, app["id"])
    return app, submitted


# ---------------------------------------------------------------------------
# Tier 2: listing setup
# ---------------------------------------------------------------------------

def get_listing(issuer_id):
    data = get_success_data(api_client.list_listings(issuer_id, ANALYST))
    assert isinstance(data, list) and len(data) >= 1, "expected at least one listing"
    return data[0]


def setup_listed_issuer(tier="CAPITAL", entry_shares=2_000_000, **app_overrides):
    """Issuer created, application filed + submitted + approved.
    Returns dict with issuer, app, listing."""
    issuer = create_issuer()
    app = create_application(
        issuer["id"], target_tier=tier,
        unrestricted_publicly_held_shares=entry_shares, **app_overrides)
    submitted = submit_application(issuer["id"], app["id"])
    assert submitted["status"] == "SUBMITTED", (
        f"Setup failed: submit did not yield SUBMITTED (got {submitted['status']})")
    approve_application(issuer["id"], app["id"])
    listing = get_listing(issuer["id"])
    issuer = get_success_data(api_client.get_issuer(issuer["id"], ANALYST))
    return {"issuer": issuer, "app": app, "listing": listing}


# ---------------------------------------------------------------------------
# Tier 3: snapshot streaks (each trading day admits exactly one snapshot whose
# trade_date must equal the logical clock's date)
# ---------------------------------------------------------------------------

def _dates_from(start_date: str, count: int):
    y, m, d = (int(x) for x in start_date.split("-"))
    start = date(y, m, d)
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]


def record_snapshot_days(issuer_id, start_date: str, days: int, **snapshot_overrides):
    """Advance the clock day-by-day and record one snapshot per day."""
    for trade_date in _dates_from(start_date, days):
        reset_clock(f"{trade_date}T00:00:00Z")
        resp = api_client.create_snapshot(
            issuer_id,
            create_snapshot_payload(trade_date, **snapshot_overrides),
            ANALYST)
        get_success_data(resp)


def run_monitor(issuer_id):
    resp = api_client.run_deficiency_monitor(issuer_id, ANALYST)
    return get_success_data(resp)


def get_deficiency_for(issuer_id, standard_code, status=None):
    params = {"standard_code": standard_code}
    if status:
        params["status"] = status
    data = get_success_data(api_client.list_deficiencies(issuer_id, ANALYST, params=params))
    return data


def get_bid_deficiency(issuer_id):
    rows = get_deficiency_for(issuer_id, "BID_PRICE")
    assert len(rows) >= 1, "Setup failed: no BID_PRICE deficiency found"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 4: deficiency / plan / staff-determination composites
# ---------------------------------------------------------------------------

def setup_bid_deficiency(bid_cents=90, fail_days=30, snapshot_start="2026-09-02",
                         tier="CAPITAL", **app_overrides):
    """LISTED issuer + a BID_PRICE deficiency detected OPEN.
    Detection happens on the day after the last snapshot."""
    base = setup_listed_issuer(tier=tier, **app_overrides)
    record_snapshot_days(base["issuer"]["id"], snapshot_start, fail_days,
                         closing_bid_cents=bid_cents)
    run_monitor(base["issuer"]["id"])
    deficiency = get_bid_deficiency(base["issuer"]["id"])
    base["deficiency"] = deficiency
    return base


def setup_plan_submitted_deficiency(plan_kind="CURE_IN_PLACE", **kwargs):
    """BID_PRICE deficiency OPEN -> plan filed -> PLAN_SUBMITTED."""
    base = setup_bid_deficiency(**kwargs)
    payload = create_compliance_plan_payload(base["deficiency"]["id"])
    if plan_kind == "TIER_TRANSFER":
        payload["plan_kind"] = "TIER_TRANSFER"
        payload["proposed_target_tier"] = kwargs.get("proposed_target_tier", "CAPITAL")
    resp = api_client.create_compliance_plan(
        base["issuer"]["id"], payload, make_issuer_officer_headers(base["issuer"]["id"]))
    plan = get_success_data(resp)
    base["plan"] = plan
    return base


def advance_clock_past_cure(deficiency):
    """Move the clock strictly past compliance_due_at (180-day cure window).

    PRD §3.6 requires the clock to be *strictly after* compliance_due_at, so
    the earliest valid instant is the day after the due date."""
    due = deficiency["compliance_due_at"][:10]
    past = (date.fromisoformat(due) + timedelta(days=1)).isoformat()
    reset_clock(f"{past}T00:00:00Z")
    return past


def staff_determine(issuer_id, deficiency_id):
    resp = api_client.staff_determine_delisting(issuer_id, deficiency_id, ANALYST)
    return get_success_data(resp)


def setup_staff_determined_deficiency(**kwargs):
    """OPEN deficiency -> clock past cure -> STAFF_DELIST_DETERMINED."""
    base = setup_bid_deficiency(**kwargs)
    advance_clock_past_cure(base["deficiency"])
    staff_determine(base["issuer"]["id"], base["deficiency"]["id"])
    deficiency = get_success_data(api_client.get_deficiency(
        base["issuer"]["id"], base["deficiency"]["id"], ANALYST))
    assert deficiency["status"] == "STAFF_DELIST_DETERMINED"
    base["deficiency"] = deficiency
    return base


# ---------------------------------------------------------------------------
# Tier 5: appeal / panel composites
# ---------------------------------------------------------------------------

def create_panel(issuer_id, panel_name="Panel-1"):
    resp = api_client.create_hearings_review(
        create_hearings_review_payload(issuer_id, panel_name=panel_name), HEARINGS)
    return get_success_data(resp)


def file_appeal(issuer_id, deficiency_id, review_id):
    resp = api_client.create_appeal(
        issuer_id, {"deficiency_id": deficiency_id, "review_id": review_id},
        make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def setup_filed_appeal(**kwargs):
    """STAFF_DELIST_DETERMINED deficiency + OPEN panel + FILED appeal
    (the filing moves the deficiency to PANEL_REVIEW)."""
    base = setup_staff_determined_deficiency(**kwargs)
    panel = create_panel(base["issuer"]["id"])
    appeal = file_appeal(base["issuer"]["id"], base["deficiency"]["id"], panel["id"])
    base["panel"] = panel
    base["appeal"] = appeal
    return base


def setup_panel_reviewing_appeal(**kwargs):
    """FILED appeal taken under panel review (appeal PANEL_REVIEWING)."""
    base = setup_filed_appeal(**kwargs)
    resp = api_client.appeal_panel_review(
        base["issuer"]["id"], base["appeal"]["id"], HEARINGS)
    base["appeal"] = get_success_data(resp)
    return base


# ---------------------------------------------------------------------------
# Fee helpers
# ---------------------------------------------------------------------------

def get_entry_fee(issuer_id):
    data = get_success_data(api_client.list_fee_assessments(
        issuer_id, FINANCE, params={"fee_kind": "ENTRY"}))
    assert len(data) == 1, f"Setup failed: expected 1 ENTRY fee, got {len(data)}"
    return data[0]


def run_annual_fee(issuer_id, shares_outstanding):
    version = _current_issuer_version(issuer_id)
    resp = api_client.run_annual_fees(
        issuer_id,
        {"shares_outstanding": shares_outstanding,
         "expected_issuer_version": version},
        FINANCE)
    return get_success_data(resp)
