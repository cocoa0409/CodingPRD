"""Composite setup helpers for the concierge pre-sale advance program.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server with an empty database before
each test). Setup calls use the lenient get_success_data() validator so a
broken precondition surfaces as a clear setup error, not an assertion
failure deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_agent_payload,
    create_capacity_window_payload,
    create_case_payload,
    create_change_order_payload,
    create_disbursement_payload,
    create_dispute_payload,
    create_engagement_payload,
    create_listing_event_payload,
    create_project_payload,
    create_vendor_payload,
)
from .test_users import TEST_USERS, make_listing_agent_headers, make_vendor_headers

ADMIN = TEST_USERS["platform_admin_headers"]
HOMEOWNER = TEST_USERS["homeowner_headers"]
UNDERWRITER = TEST_USERS["program_underwriter_headers"]
ANY_HEADERS = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(current_utc: str) -> dict:
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, ADMIN))


def reset_clock() -> dict:
    return set_clock(LOGICAL_CLOCK_START)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def make_agent(**overrides) -> dict:
    resp = api_client.create_agent(create_agent_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_vendor(**overrides) -> dict:
    resp = api_client.create_vendor(create_vendor_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_capacity_window(vendor_id: str, **overrides) -> dict:
    resp = api_client.create_capacity_window(
        vendor_id, create_capacity_window_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def make_vendor_with_window(**window_overrides):
    """A vendor plus one OPEN capacity window covering the Fall 2026 season."""
    vendor = make_vendor()
    window = make_capacity_window(vendor["id"], **window_overrides)
    return vendor, window


# ---------------------------------------------------------------------------
# Case lifecycle
# ---------------------------------------------------------------------------

def create_case(agent: dict, **overrides) -> dict:
    resp = api_client.create_case(
        create_case_payload(**overrides), make_listing_agent_headers(agent["id"])
    )
    return get_success_data(resp)


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, ANY_HEADERS))


def get_case_version(case_id: str) -> int:
    return get_case(case_id)["version"]


def approve_eligibility(case_id: str) -> dict:
    return get_success_data(api_client.approve_eligibility(case_id, UNDERWRITER))


def create_eligible_case(agent: dict, **overrides) -> dict:
    """Case created and eligibility-approved (SCOPE_PLANNING)."""
    case = create_case(agent, **overrides)
    approve_eligibility(case["id"])
    return get_case(case["id"])


def approve_plan(case_id: str) -> dict:
    """Plan approval is an OCC write: always send the fresh case version."""
    version = get_case_version(case_id)
    resp = api_client.approve_plan(case_id, {"expected_case_version": version}, HOMEOWNER)
    return get_success_data(resp)


def cancel_case(case_id: str) -> dict:
    return get_success_data(api_client.cancel_case(case_id, HOMEOWNER))


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def add_project(case_id: str, agent: dict, **overrides) -> dict:
    """Create a project (born DRAFT)."""
    resp = api_client.create_project(
        case_id,
        create_project_payload(**overrides),
        make_listing_agent_headers(agent["id"]),
    )
    return get_success_data(resp)


def propose_project(case_id: str, project_id: str, agent: dict) -> dict:
    resp = api_client.propose_project(
        case_id, project_id, make_listing_agent_headers(agent["id"])
    )
    return get_success_data(resp)


def approve_project(case_id: str, project_id: str) -> dict:
    return get_success_data(api_client.approve_project(case_id, project_id, HOMEOWNER))


def add_approved_project(case_id: str, agent: dict, **overrides) -> dict:
    project = add_project(case_id, agent, **overrides)
    propose_project(case_id, project["id"], agent)
    approve_project(case_id, project["id"])
    return get_success_data(api_client.get_project(case_id, project["id"], ANY_HEADERS))


def get_project(case_id: str, project_id: str) -> dict:
    return get_success_data(api_client.get_project(case_id, project_id, ANY_HEADERS))


# ---------------------------------------------------------------------------
# Engagements
# ---------------------------------------------------------------------------

def create_engagement(project_id: str, vendor_id: str, agent: dict, **overrides) -> dict:
    payload = create_engagement_payload(
        improvement_project_id=project_id, vendor_id=vendor_id, **overrides
    )
    resp = api_client.create_engagement(payload, make_listing_agent_headers(agent["id"]))
    return get_success_data(resp)


def start_engagement(engagement_id: str, vendor: dict) -> dict:
    resp = api_client.start_engagement(engagement_id, make_vendor_headers(vendor["id"]))
    return get_success_data(resp)


def complete_engagement(engagement_id: str, vendor: dict) -> dict:
    resp = api_client.complete_engagement(engagement_id, make_vendor_headers(vendor["id"]))
    return get_success_data(resp)


def get_engagement(engagement_id: str) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id, ANY_HEADERS))


def get_vendor(vendor_id: str) -> dict:
    return get_success_data(api_client.get_vendor(vendor_id, ANY_HEADERS))


def get_capacity_window_reserved(vendor_id: str, window_id: str) -> int:
    resp = api_client.list_capacity_windows(vendor_id, ANY_HEADERS)
    payload = get_success_data(resp)
    for window in payload:
        if window["id"] == window_id:
            return window["reserved_crew_days"]
    raise AssertionError(f"capacity window {window_id} not found for vendor {vendor_id}")


# ---------------------------------------------------------------------------
# Disbursements
# ---------------------------------------------------------------------------

def create_disbursement(case_id: str, project_id: str, engagement_id: str, **overrides) -> dict:
    payload = create_disbursement_payload(
        concierge_case_id=case_id,
        improvement_project_id=project_id,
        vendor_engagement_id=engagement_id,
        **overrides,
    )
    return get_success_data(api_client.create_disbursement(payload, UNDERWRITER))


def approve_disbursement(disbursement_id: str, case_id: str) -> dict:
    """Disbursement approval is an OCC write: send the fresh case version."""
    version = get_case_version(case_id)
    resp = api_client.approve_disbursement(
        disbursement_id, {"expected_case_version": version}, UNDERWRITER
    )
    return get_success_data(resp)


def release_disbursement(disbursement_id: str) -> dict:
    return get_success_data(api_client.release_disbursement(disbursement_id, UNDERWRITER))


def get_disbursement(disbursement_id: str) -> dict:
    return get_success_data(api_client.get_disbursement(disbursement_id, ANY_HEADERS))


# ---------------------------------------------------------------------------
# Change orders
# ---------------------------------------------------------------------------

def create_change_order(project_id: str, engagement_id: str, vendor: dict, **overrides) -> dict:
    payload = create_change_order_payload(
        improvement_project_id=project_id,
        vendor_engagement_id=engagement_id,
        **overrides,
    )
    resp = api_client.create_change_order(payload, make_vendor_headers(vendor["id"]))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

def create_dispute(case_id: str, project_id: str, engagement_id: str, **overrides) -> dict:
    payload = create_dispute_payload(
        concierge_case_id=case_id,
        improvement_project_id=project_id,
        vendor_engagement_id=engagement_id,
        **overrides,
    )
    return get_success_data(api_client.create_dispute(payload, HOMEOWNER))


def create_dispute_in_review(case_id: str, project_id: str, engagement_id: str, **overrides) -> dict:
    dispute = create_dispute(case_id, project_id, engagement_id, **overrides)
    get_success_data(api_client.review_dispute(dispute["id"], UNDERWRITER))
    return get_success_data(api_client.get_dispute(dispute["id"], ANY_HEADERS))


# ---------------------------------------------------------------------------
# Listing events and closing statements
# ---------------------------------------------------------------------------

def create_listing_event(case_id: str, agent: dict, **overrides) -> dict:
    resp = api_client.create_listing_event(
        case_id,
        create_listing_event_payload(**overrides),
        make_listing_agent_headers(agent["id"]),
    )
    return get_success_data(resp)


def get_closing_statement(case_id: str) -> dict:
    return get_success_data(api_client.get_closing_statement(case_id, ANY_HEADERS))


# ---------------------------------------------------------------------------
# Composite contexts (each returns a dict of the entities it built)
# ---------------------------------------------------------------------------

def setup_case_with_approved_project(case_overrides=None, project_overrides=None,
                                     with_vendor=True, window_overrides=None) -> dict:
    """Eligible case (SCOPE_PLANNING) + one APPROVED project."""
    reset_clock()
    agent = make_agent()
    case = create_eligible_case(agent, **(case_overrides or {}))
    project = add_approved_project(case["id"], agent, **(project_overrides or {}))
    ctx = {"agent": agent, "case": get_case(case["id"]), "project": project}
    if with_vendor:
        vendor, window = make_vendor_with_window(**(window_overrides or {}))
        ctx["vendor"] = vendor
        ctx["window"] = window
    return ctx


def setup_engagement_scheduled(case_overrides=None, project_overrides=None,
                               engagement_overrides=None, window_overrides=None,
                               plan_approved=False) -> dict:
    """Approved project + one SCHEDULED engagement on a vendor with capacity.

    PRD §3.4 narrates engagements as created "with the plan approved", and
    creating an engagement advances its project out of APPROVED (which would
    make a later plan approval fail with ERR_NO_APPROVED_PROJECTS). Callers
    that need the case in PLAN_APPROVED must therefore pass
    plan_approved=True so the plan is approved BEFORE the engagement exists.
    The default keeps the case in SCOPE_PLANNING for tests that exercise that
    state (e.g. case cancellation from SCOPE_PLANNING).
    """
    ctx = setup_case_with_approved_project(
        case_overrides=case_overrides,
        project_overrides=project_overrides,
        with_vendor=True,
        window_overrides=window_overrides,
    )
    if plan_approved:
        approve_plan(ctx["case"]["id"])
        ctx["case"] = get_case(ctx["case"]["id"])
        ctx["project"] = get_project(ctx["case"]["id"], ctx["project"]["id"])
    engagement = create_engagement(
        ctx["project"]["id"], ctx["vendor"]["id"], ctx["agent"], **(engagement_overrides or {})
    )
    ctx["engagement"] = engagement
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["project"] = get_project(ctx["case"]["id"], ctx["project"]["id"])
    return ctx


def setup_engagement_in_work(case_overrides=None, project_overrides=None,
                             engagement_overrides=None, window_overrides=None) -> dict:
    """SCHEDULED engagement started -> IN_WORK (reserves crew-days)."""
    ctx = setup_engagement_scheduled(
        case_overrides=case_overrides,
        project_overrides=project_overrides,
        engagement_overrides=engagement_overrides,
        window_overrides=window_overrides,
    )
    start_engagement(ctx["engagement"]["id"], ctx["vendor"])
    ctx["engagement"] = get_engagement(ctx["engagement"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["project"] = get_project(ctx["case"]["id"], ctx["project"]["id"])
    return ctx


def setup_plan_approved_case(case_overrides=None, project_overrides=None) -> dict:
    """Approved project + plan approved (case PLAN_APPROVED)."""
    ctx = setup_case_with_approved_project(
        case_overrides=case_overrides, project_overrides=project_overrides, with_vendor=False
    )
    approve_plan(ctx["case"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_ready_to_list_case(disb_amounts=None, case_overrides=None,
                             project_overrides=None, engagement_overrides=None,
                             release=True) -> dict:
    """Full pipeline to READY_TO_LIST.

    plan approved -> first disbursement APPROVED (case FUNDED) ->
    engagement started (case IN_PROGRESS) -> disbursements RELEASED ->
    engagement completed (project COMPLETE) -> project verified
    (case READY_TO_LIST).
    """
    amounts = disb_amounts if disb_amounts is not None else [TEST_DEFAULTS["DISBURSEMENT_AMOUNT_CENTS"]]
    ctx = setup_engagement_scheduled(
        case_overrides=case_overrides,
        project_overrides=project_overrides,
        engagement_overrides=engagement_overrides,
        plan_approved=True,
    )
    disbursements = []
    for amount in amounts:
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"],
            amount_cents=amount,
        )
        approve_disbursement(disb["id"], ctx["case"]["id"])
        disbursements.append(disb)
    start_engagement(ctx["engagement"]["id"], ctx["vendor"])
    if release:
        for disb in disbursements:
            release_disbursement(disb["id"])
    complete_engagement(ctx["engagement"]["id"], ctx["vendor"])
    verify_resp = api_client.verify_project(
        ctx["case"]["id"], ctx["project"]["id"], make_listing_agent_headers(ctx["agent"]["id"])
    )
    get_success_data(verify_resp)
    ctx["disbursements"] = [
        get_disbursement(d["id"]) for d in disbursements
    ]
    ctx["engagement"] = get_engagement(ctx["engagement"]["id"])
    ctx["project"] = get_project(ctx["case"]["id"], ctx["project"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_listed_case(listed_at="2026-09-10T00:00:00Z", listing_window_days=None,
                      market_risk=False, disb_amounts=None, case_overrides=None) -> dict:
    """READY_TO_LIST case plus the first LISTED event (case LISTED)."""
    overrides = dict(case_overrides or {})
    if listing_window_days is not None:
        overrides["listing_window_days"] = listing_window_days
    ctx = setup_ready_to_list_case(disb_amounts=disb_amounts, case_overrides=overrides)
    event_payload = {"event_kind": "LISTED", "event_at": listed_at,
                     "price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"]}
    if market_risk:
        event_payload["market_risk_flag"] = True
    event = create_listing_event(ctx["case"]["id"], ctx["agent"], **event_payload)
    ctx["listed_event"] = event
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_closed_sold_case(listing_window_days=None, listed_at="2026-09-10T00:00:00Z",
                           offer_at="2026-10-01T00:00:00Z",
                           closed_at="2026-10-15T00:00:00Z",
                           disb_amounts=None, sale_price=None) -> dict:
    """LISTED -> OFFER_ACCEPTED -> CLOSED_SOLD; closing statement exists (DRAFT)."""
    price = sale_price if sale_price is not None else TEST_DEFAULTS["LIST_PRICE_CENTS"]
    ctx = setup_listed_case(
        listed_at=listed_at,
        listing_window_days=listing_window_days,
        disb_amounts=disb_amounts,
    )
    create_listing_event(
        ctx["case"]["id"], ctx["agent"],
        event_kind="OFFER_ACCEPTED", event_at=offer_at, price_cents=price,
    )
    set_clock(closed_at)
    create_listing_event(
        ctx["case"]["id"], ctx["agent"],
        event_kind="CLOSED_SOLD", event_at=closed_at, price_cents=price,
    )
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["statement"] = get_closing_statement(ctx["case"]["id"])
    return ctx


def setup_closed_unsold_case(listing_window_days=30, listed_at="2026-09-01T00:00:00Z",
                             closed_at="2026-10-15T00:00:00Z", market_risk=False,
                             disb_amounts=None) -> dict:
    """LISTED -> CLOSED_UNSOLD after the window; closing statement exists (DRAFT)."""
    ctx = setup_listed_case(
        listed_at=listed_at,
        listing_window_days=listing_window_days,
        market_risk=market_risk,
        disb_amounts=disb_amounts,
    )
    set_clock(closed_at)
    event_payload = {"event_kind": "CLOSED_UNSOLD", "event_at": closed_at}
    if market_risk:
        event_payload["market_risk_flag"] = True
    create_listing_event(ctx["case"]["id"], ctx["agent"], **event_payload)
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["statement"] = get_closing_statement(ctx["case"]["id"])
    return ctx
