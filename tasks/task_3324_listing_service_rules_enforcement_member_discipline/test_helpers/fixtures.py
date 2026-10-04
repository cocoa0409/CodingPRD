"""Composite setup helpers. Each builds preconditions from scratch using only
PRD-declared endpoints; all setup calls use get_success_data so failures surface
as clear 'Setup failed' errors."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_association_payload,
    create_member_payload,
    create_office_payload,
    create_dues_period_payload,
    create_listing_payload,
    create_citation_payload,
    create_fine_schedule_payload,
    create_data_license_payload,
    create_policy_revision_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_grievance_headers,
    make_panelist_headers,
)

STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base entity creation
# ---------------------------------------------------------------------------

def create_association(**overrides):
    resp = api_client.create_association(create_association_payload(**overrides), STAFF)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, STAFF)
    return get_success_data(resp)


def advance_day(days=None):
    resp = api_client.advance_day(STAFF, days=days)
    return get_success_data(resp)


def create_member(association_id, **overrides):
    resp = api_client.create_member(association_id, create_member_payload(**overrides), STAFF)
    return get_success_data(resp)


def create_members(association_id, n, prefix="P"):
    """Create n members; returns list of member dicts in creation order."""
    return [create_member(association_id, member_nr=f"{prefix}{i+1}", full_name=f"{prefix}{i+1}")
            for i in range(n)]


def create_office(association_id, broker_member_id, **overrides):
    resp = api_client.create_office(
        association_id, create_office_payload(broker_member_id, **overrides), STAFF)
    return get_success_data(resp)


def create_fine_schedule(association_id, rule_code="INACCURACY", fine_amount_cents=30000,
                         effective_from="2026-01-01T00:00:00Z", **overrides):
    resp = api_client.create_fine_schedule(
        association_id,
        create_fine_schedule_payload(
            rule_code=rule_code, fine_amount_cents=fine_amount_cents,
            effective_from=effective_from, **overrides),
        STAFF)
    return get_success_data(resp)


def create_dues_period(association_id, **overrides):
    resp = api_client.create_dues_period(
        association_id, create_dues_period_payload(**overrides), STAFF)
    return get_success_data(resp)


def bill_dues_period(association_id, period):
    resp = api_client.bill_dues_period(association_id, period["id"], period["version"], STAFF)
    return get_success_data(resp)


def reconcile_dues_period(association_id, period_id):
    resp = api_client.reconcile_dues_period(association_id, period_id, STAFF)
    return get_success_data(resp)


def get_member_invoice(association_id, period_id, member_id):
    resp = api_client.list_dues_invoices_flat(
        STAFF, params={"dues_period_id": period_id, "member_id": member_id})
    data = get_success_data(resp)
    assert len(data) == 1, f"expected exactly one invoice for member {member_id}, got {len(data)}"
    return data[0]


def pay_invoice(association_id, invoice):
    resp = api_client.pay_dues_invoice(
        association_id, invoice["id"], invoice["amount_due_cents"],
        make_member_headers(invoice["member_id"]))
    return get_success_data(resp)


def seed_credit(association_id, member_id, amount_cents, note="seed"):
    resp = api_client.create_credit_adjustment(
        association_id, member_id, {"amount_cents": amount_cents, "note": note}, STAFF)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: policy revision scheduling / activation
# ---------------------------------------------------------------------------

def create_policy_revision(association_id, expected_association_version, **overrides):
    resp = api_client.create_policy_revision(
        association_id,
        create_policy_revision_payload(expected_association_version, **overrides),
        STAFF)
    return get_success_data(resp)


def activate_policy_revision(association_id, expected_association_version, *,
                             revision_code=None, effective_at="2026-09-01T00:00:00Z",
                             comp_display_mode="COMP_DISPLAY_ON", activate_now=None):
    """Create a revision and advance the clock so it activates. Returns the
    revision (re-read to observe ACTIVE status). activate_now defaults to the
    effective_at instant."""
    overrides = {"effective_at": effective_at, "comp_display_mode": comp_display_mode}
    if revision_code is not None:
        overrides["revision_code"] = revision_code
    rev = create_policy_revision(association_id, expected_association_version, **overrides)
    set_clock(activate_now or effective_at)
    resp = api_client.get_policy_revision(association_id, rev["id"], STAFF)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: listings
# ---------------------------------------------------------------------------

def create_listing(association_id, office_id, listing_member_id, **overrides):
    resp = api_client.create_listing(
        association_id, office_id,
        create_listing_payload(listing_member_id, **overrides),
        make_member_headers(listing_member_id))
    return get_success_data(resp)


def activate_listing(association_id, office_id, listing):
    resp = api_client.activate_listing(
        association_id, office_id, listing["id"],
        make_member_headers(listing["listing_member_id"]))
    return get_success_data(resp)


def change_status(association_id, office_id, listing, to_status, business_effective_at):
    resp = api_client.change_listing_status(
        association_id, office_id, listing["id"],
        {"to_status": to_status, "business_effective_at": business_effective_at},
        make_member_headers(listing["listing_member_id"]))
    return get_success_data(resp)


def setup_office_with_listing(**overrides):
    """Association + broker member + office + DRAFT listing owned by the broker.
    Returns dict with keys: assoc, broker, office, listing."""
    assoc = create_association(**overrides.pop("assoc_overrides", {}))
    broker = create_member(assoc["id"], **overrides.pop("broker_overrides", {}))
    office = create_office(assoc["id"], broker["id"], **overrides.pop("office_overrides", {}))
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             **overrides.pop("listing_overrides", {}))
    return {"assoc": assoc, "broker": broker, "office": office, "listing": listing}


def setup_active_listing(revision_effective_at="2026-09-01T00:00:00Z",
                         activation_instant=None, **overrides):
    """Association + broker + office + ACTIVE policy revision + ACTIVE listing.
    Returns dict: assoc, broker, office, revision, listing (ACTIVE)."""
    ctx = setup_office_with_listing(**overrides)
    assoc = ctx["assoc"]
    revision = activate_policy_revision(
        assoc["id"], assoc["version"], revision_code="R1",
        effective_at=revision_effective_at)
    if activation_instant:
        set_clock(activation_instant)
    listing = activate_listing(assoc["id"], ctx["office"]["id"], ctx["listing"])
    ctx["revision"] = revision
    ctx["listing"] = listing
    return ctx


def setup_sold_listing(**overrides):
    """Active listing driven ACTIVE -> PENDING -> SOLD with timely business
    events. Returns ctx from setup_active_listing with listing in SOLD state
    plus 'sold_at' (the business effective instant of the SOLD change)."""
    ctx = setup_active_listing(**overrides)
    assoc, office, listing = ctx["assoc"], ctx["office"], ctx["listing"]
    # Record timely status changes with business_effective_at == current clock.
    cur = current_clock_iso()
    change_status(assoc["id"], office["id"], listing, "PENDING", cur)
    listing = change_status(assoc["id"], office["id"], listing, "SOLD", cur)
    ctx["listing"] = listing
    ctx["sold_at"] = cur
    return ctx


def current_clock_iso():
    """Read the current logical instant (advance by 0 days)."""
    return get_success_data(api_client.advance_day(STAFF, days=0))["now_iso8601"]


# ---------------------------------------------------------------------------
# Tier 4: citations / panels / cases
# ---------------------------------------------------------------------------

def create_citation(association_id, member_id, rule_code="INACCURACY", **overrides):
    resp = api_client.create_citation(
        association_id,
        create_citation_payload(member_id, rule_code=rule_code, **overrides),
        STAFF)
    return get_success_data(resp)


def pay_citation(association_id, citation):
    """Pay a citation with the exact required tender (fine minus credits)."""
    member = get_success_data(
        api_client.get_member(association_id, citation["member_id"], STAFF))
    tender = citation["fine_amount_cents"] - min(
        citation["fine_amount_cents"], member["sanction_credit_balance_cents"])
    resp = api_client.pay_citation(
        association_id, citation["id"], tender,
        make_member_headers(citation["member_id"]))
    return get_success_data(resp)


def issue_and_pay_citation(association_id, member_id, rule_code="INACCURACY",
                           **overrides):
    cit = create_citation(association_id, member_id, rule_code=rule_code, **overrides)
    return pay_citation(association_id, cit)


def setup_citation_hearing_held(assoc_id, cited_member_id, panel_pool_member_ids,
                                rule_code="INACCURACY", listing_id=None):
    """Issue citation -> request hearing -> convene panel -> hold hearing.
    panel_pool_member_ids must give at least 3 eligible non-subject members.
    Returns dict: citation, panel, holder_id (panelist[0]), ruler_id (panelist[1])."""
    payload_overrides = {}
    if listing_id is not None:
        payload_overrides["listing_id"] = listing_id
    citation = create_citation(assoc_id, cited_member_id, rule_code=rule_code,
                               **payload_overrides)
    resp = api_client.request_hearing(
        assoc_id, citation["id"], make_member_headers(cited_member_id))
    citation = get_success_data(resp)
    panel = get_success_data(
        api_client.convene_hearing_panel(assoc_id, "CITATION", citation["id"], STAFF))
    holder_id = panel["selected_member_ids"][0]
    ruler_id = panel["selected_member_ids"][1]
    get_success_data(api_client.hold_hearing(
        assoc_id, panel["id"], make_panelist_headers(holder_id)))
    return {"citation": citation, "panel": panel,
            "holder_id": holder_id, "ruler_id": ruler_id}


def rule_on_panel(association_id, panel_id, ruler_id, decision):
    resp = api_client.rule_panel(
        association_id, panel_id, decision, make_panelist_headers(ruler_id))
    return get_success_data(resp)


def setup_arbitration_case_scheduled(**overrides):
    """Full chain: association, broker, complainant ML, respondent MR, 3 pool
    members, office, ACTIVE revision, SOLD listing, arbitration case routed to
    ARBITRATION_SCHEDULED, panel convened and ready for hold-hearing.
    Returns dict with all context."""
    claim_amount_cents = overrides.pop("claim_amount_cents", 1000000)
    assoc = create_association()
    mb = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    ml = create_member(assoc["id"], member_nr="ML", full_name="Lister")
    mr = create_member(assoc["id"], member_nr="MR", full_name="Responder")
    pool = create_members(assoc["id"], 3, prefix="P")
    office = create_office(assoc["id"], mb["id"])
    revision = activate_policy_revision(
        assoc["id"], get_success_data(api_client.get_association(assoc["id"], STAFF))["version"],
        revision_code=f"R-{assoc['association_code']}",
        effective_at="2026-09-01T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], ml["id"])
    listing = activate_listing(assoc["id"], office["id"], listing)
    cur = current_clock_iso()
    listing = change_status(assoc["id"], office["id"], listing, "PENDING", cur)
    listing = change_status(assoc["id"], office["id"], listing, "SOLD", cur)
    resp = api_client.create_arbitration_case(
        assoc["id"],
        {"respondent_member_id": mr["id"], "listing_id": listing["id"],
         "claim_amount_cents": claim_amount_cents},
        make_member_headers(ml["id"]))
    case = get_success_data(resp)
    get_success_data(api_client.record_mediation_outcome(
        assoc["id"], case["id"], "DECLINED", STAFF))
    panel = get_success_data(
        api_client.convene_hearing_panel(assoc["id"], "ARBITRATION", case["id"], STAFF))
    return {
        "assoc": assoc, "broker": mb, "complainant": ml, "respondent": mr,
        "pool": pool, "office": office, "revision": revision, "listing": listing,
        "case": case, "panel": panel,
        "holder_id": panel["selected_member_ids"][0],
        "ruler_id": panel["selected_member_ids"][1],
    }


def setup_ethics_case_decided(respondent_strikes=0, **overrides):
    """Association with complainant MC, respondent MR (carrying
    respondent_strikes paid INACCURACY citations), grievance member MG, pool of
    5; ethics case screened FORWARDED, panel convened, hearing held.
    Returns dict with context incl. ruler/holder ids."""
    assoc = create_association(sanction_credit_cap_cents=200000)
    mc = create_member(assoc["id"], member_nr="MC", full_name="Complainant")
    mr = create_member(assoc["id"], member_nr="MR", full_name="Respondent")
    # Pool is created BEFORE the grievance member: panel selection ranks
    # zero-strike candidates by earliest created_at, so MG stays off the
    # convened panel and remains eligible to rule a later appeal (PRD §3.6
    # excludes only complainant, respondent, and original panelists).
    pool = create_members(assoc["id"], 5, prefix="P")
    mg = create_member(assoc["id"], member_nr="MG", full_name="Grievance")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    for _ in range(respondent_strikes):
        issue_and_pay_citation(assoc["id"], mr["id"], rule_code="INACCURACY")
    case = get_success_data(api_client.create_ethics_case(
        assoc["id"], {"respondent_member_id": mr["id"], "article_code": "A16"},
        make_member_headers(mc["id"])))
    get_success_data(api_client.screen_ethics_case(
        assoc["id"], case["id"], "FORWARDED", make_grievance_headers(mg["id"])))
    panel = get_success_data(
        api_client.convene_hearing_panel(assoc["id"], "ETHICS", case["id"], STAFF))
    holder_id = panel["selected_member_ids"][0]
    ruler_id = panel["selected_member_ids"][1]
    get_success_data(api_client.hold_hearing(
        assoc["id"], panel["id"], make_panelist_headers(holder_id)))
    return {"assoc": assoc, "complainant": mc, "respondent": mr, "grievance": mg,
            "pool": pool, "case": case, "panel": panel,
            "holder_id": holder_id, "ruler_id": ruler_id}


# ---------------------------------------------------------------------------
# Tier 5: dues suspension / termination chains
# ---------------------------------------------------------------------------

def setup_billed_period_with_unpaid_member(**overrides):
    """Association + member with a billed, still-PENDING invoice. Clock left at
    bill instant. Returns dict: assoc, member, period, invoice."""
    assoc = create_association(**overrides.pop("assoc_overrides", {}))
    member = create_member(assoc["id"], **overrides.pop("member_overrides", {}))
    period_overrides = overrides.pop("period_overrides", {})
    period = create_dues_period(assoc["id"], **period_overrides)
    bill_dues_period(assoc["id"], period)
    invoice = get_member_invoice(assoc["id"], period["id"], member["id"])
    return {"assoc": assoc, "member": member, "period": period, "invoice": invoice}


def suspend_member_via_reconcile(association_id, period_id, grace_end_next_day):
    """Advance clock past grace end and reconcile: suspends members with
    PENDING invoices for the period."""
    set_clock(grace_end_next_day)
    return reconcile_dues_period(association_id, period_id)
