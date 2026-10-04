"""Composite setup helpers for the agent profit-share domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z unless a helper moves it).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_agent_payload,
    create_commission_event_payload,
    create_dispute_payload,
    create_document_payload,
    create_ledger_entry_payload,
    create_market_center_payload,
    create_period_payload,
    create_resolution_payload,
    create_transfer_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_alc_chair_headers,
    make_market_center_admin_headers,
)

PA = TEST_USERS["platform_admin_headers"]
RD = TEST_USERS["regional_director_headers"]
JOIN = TEST_DEFAULTS["JOIN_DATE"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity setup
# ---------------------------------------------------------------------------

def create_center(**overrides):
    return get_success_data(api.create_market_center(create_market_center_payload(**overrides), PA))


def enroll_agent(center_id, sponsor_id=None, join_date=JOIN, docs=True,
                 attested_sponsor_id=None, **overrides):
    """Enroll an agent; by default complete the document set so the agent is ACTIVE.

    Unsponsored agents need ICA_SIGNED + W9; sponsored agents additionally need a
    SPONSOR_ATTESTATION (which names attested_sponsor_id, defaulting to the
    recorded sponsor). Returns the final agent record.
    """
    payload = create_agent_payload(join_date=join_date, **overrides)
    if sponsor_id is not None:
        payload["sponsor_agent_id"] = sponsor_id
    agent = get_success_data(api.create_agent(center_id, payload, PA))
    if docs:
        if sponsor_id is not None:
            attestee = attested_sponsor_id if attested_sponsor_id is not None else sponsor_id
            get_success_data(api.create_onboarding_document(
                agent["id"],
                create_document_payload("SPONSOR_ATTESTATION", attested_sponsor_agent_id=attestee),
                PA,
            ))
        get_success_data(api.create_onboarding_document(
            agent["id"], create_document_payload("ICA_SIGNED"), PA))
        get_success_data(api.create_onboarding_document(
            agent["id"], create_document_payload("W9"), PA))
        agent = get_success_data(api.get_agent(agent["id"], PA))
    return agent


def get_agent(agent_id):
    return get_success_data(api.get_agent(agent_id, PA))


def agent_version(agent_id):
    return get_agent(agent_id)["version"]


def post_commission(agent_id, gross, occurred_on, admin_agent_id, settle=False,
                    external_ref=None):
    """Post a commission event as a MarketCenterAdmin acting through admin_agent_id,
    reading the current agent version first for the OCC guard. Returns the event."""
    headers = make_market_center_admin_headers(admin_agent_id)
    payload = create_commission_event_payload(
        agent_id, agent_version(agent_id),
        gross_commission=gross, occurred_on=occurred_on,
    )
    if external_ref is not None:
        payload["external_ref"] = external_ref
    event = get_success_data(api.create_commission_event(payload, headers))
    if settle:
        event = get_success_data(api.settle_commission_event(event["id"], headers))
    return event


def open_period(center_id, month, admin_agent_id):
    return get_success_data(api.create_period(
        center_id, create_period_payload(period_month=month),
        make_market_center_admin_headers(admin_agent_id),
    ))


def add_ledger_entry(period_id, entry_type, amount, admin_agent_id, **overrides):
    return get_success_data(api.create_ledger_entry(
        period_id, create_ledger_entry_payload(entry_type, amount, **overrides),
        make_market_center_admin_headers(admin_agent_id),
    ))


# ---------------------------------------------------------------------------
# Tier 2: center + sponsor chains
# ---------------------------------------------------------------------------

def setup_center_with_mca(**agent_overrides):
    """One center with a single ACTIVE unsponsored agent who acts as its admin."""
    center = create_center()
    mca = enroll_agent(center["id"], **agent_overrides)
    return {"center": center, "mca": mca}


def setup_chain_mca_s1_d1(include_alc=True):
    """Center with chain mca -> s1 -> d1 (all ACTIVE) and an ALC chair agent."""
    center = create_center()
    mca = enroll_agent(center["id"])
    s1 = enroll_agent(center["id"], sponsor_id=mca["id"])
    d1 = enroll_agent(center["id"], sponsor_id=s1["id"])
    ctx = {"center": center, "mca": mca, "s1": s1, "d1": d1}
    if include_alc:
        ctx["alc"] = enroll_agent(center["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: period close lifecycle shortcuts
# ---------------------------------------------------------------------------

def prelim_close(period_id, admin_agent_id):
    return get_success_data(api.preliminary_close_period(
        period_id, make_market_center_admin_headers(admin_agent_id)))


def draft_resolution(period_id, admin_agent_id):
    return get_success_data(api.create_resolution(
        period_id, create_resolution_payload(),
        make_market_center_admin_headers(admin_agent_id),
    ))


def propose_resolution(resolution_id, admin_agent_id):
    return get_success_data(api.propose_resolution(
        resolution_id, make_market_center_admin_headers(admin_agent_id)))


def ratify_resolution(resolution_id, chair_agent_id):
    return get_success_data(api.ratify_resolution(
        resolution_id, make_alc_chair_headers(chair_agent_id)))


def setup_prelim_closed_divergence_period():
    """The shared dual-variant fixture: chain mca -> s1 -> d1 + ALC chair alc.

    s1 posts a 10000.00 commission that is never settled; d1 posts and settles a
    20000.00 commission (both 2026-09-10). Period 2026-09 carries a 500.00
    EXPENSE, is preliminarily closed by mca, and its resolution is proposed.
    Returns a context dict with all ids and the period.
    """
    ctx = setup_chain_mca_s1_d1()
    center, mca, s1, d1, alc = ctx["center"], ctx["mca"], ctx["s1"], ctx["d1"], ctx["alc"]
    ev_s1 = post_commission(s1["id"], 10000.00, "2026-09-10T00:00:00Z", mca["id"],
                            external_ref="ref-s1-1")
    ev_d1 = post_commission(d1["id"], 20000.00, "2026-09-10T00:00:00Z", mca["id"],
                            settle=True, external_ref="ref-d1-1")
    period = open_period(center["id"], "2026-09", mca["id"])
    add_ledger_entry(period["id"], "EXPENSE", 500.00, mca["id"])
    period = prelim_close(period["id"], mca["id"])
    resolution = draft_resolution(period["id"], mca["id"])
    propose_resolution(resolution["id"], mca["id"])
    ctx.update({"ev_s1": ev_s1, "ev_d1": ev_d1, "period": period, "resolution": resolution})
    return ctx


def setup_final_closed_single_sponsor_period():
    """mca sponsors d1; d1 settles 5000.00 (company dollar 1500.00); period
    2026-09 fully FINAL_CLOSED with mca's distribution PAYABLE 750.00."""
    center = create_center()
    mca = enroll_agent(center["id"])
    d1 = enroll_agent(center["id"], sponsor_id=mca["id"])
    alc = enroll_agent(center["id"])
    ev = post_commission(d1["id"], 5000.00, "2026-09-10T00:00:00Z", mca["id"],
                         settle=True, external_ref="ref-d1")
    period = open_period(center["id"], "2026-09", mca["id"])
    period = prelim_close(period["id"], mca["id"])
    resolution = draft_resolution(period["id"], mca["id"])
    propose_resolution(resolution["id"], mca["id"])
    ratify_resolution(resolution["id"], alc["id"])
    period = get_success_data(api.get_period(period["id"], PA))
    return {"center": center, "mca": mca, "d1": d1, "alc": alc,
            "event": ev, "period": period, "resolution": resolution}


def find_distribution(period_id, agent_id, status=None):
    """Return the single distribution for (period, agent), optionally filtered by status."""
    params = {"period_id": period_id, "agent_id": agent_id}
    if status is not None:
        params["status"] = status
    resp = api.list_distributions(PA, params=params)
    body = resp.json()
    rows = body["data"]
    assert len(rows) == 1, f"expected exactly 1 distribution for agent {agent_id}, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 4: dispute fixtures
# ---------------------------------------------------------------------------

def setup_dispute_fixture(attest_sponsor="r1", include_r2=False):
    """Center with mca sponsoring r1 and s2. s2's SPONSOR_ATTESTATION names
    attested_agent (default r1) while the recorded sponsor is mca. Optionally
    includes a third mca-sponsored agent r2. No dispute is filed."""
    center = create_center()
    mca = enroll_agent(center["id"])
    r1 = enroll_agent(center["id"], sponsor_id=mca["id"])
    ctx = {"center": center, "mca": mca, "r1": r1}
    if include_r2:
        ctx["r2"] = enroll_agent(center["id"], sponsor_id=mca["id"])
    attestee = r1["id"] if attest_sponsor == "r1" else mca["id"]
    s2 = enroll_agent(center["id"], sponsor_id=mca["id"], attested_sponsor_id=attestee)
    docs = get_success_data(api.list_onboarding_documents(s2["id"], PA))
    att = next(d for d in docs if d["document_type"] == "SPONSOR_ATTESTATION")
    ctx.update({"s2": s2, "att": att})
    return ctx


def file_dispute(filer_id, sponsored_id, evidence_id, reason="mine"):
    return get_success_data(api.create_dispute(
        create_dispute_payload(sponsored_id, evidence_id, reason=reason),
        make_agent_headers(filer_id),
    ))


def setup_filed_dispute():
    """Dispute fixture with r1's dispute over s2 already FILED."""
    ctx = setup_dispute_fixture()
    dispute = file_dispute(ctx["r1"]["id"], ctx["s2"]["id"], ctx["att"]["id"])
    ctx["dispute"] = dispute
    return ctx


def setup_under_review_dispute():
    ctx = setup_filed_dispute()
    dispute = get_success_data(api.open_dispute_review(ctx["dispute"]["id"], RD))
    ctx["dispute"] = dispute
    return ctx


def setup_resolved_upheld_dispute():
    ctx = setup_under_review_dispute()
    dispute = get_success_data(api.resolve_dispute(ctx["dispute"]["id"], {"outcome": "UPHELD"}, RD))
    ctx["dispute"] = dispute
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: transfer fixtures
# ---------------------------------------------------------------------------

def request_transfer(agent_id, to_center_id, effective_date="2026-10-01T00:00:00Z"):
    return get_success_data(api.create_transfer_request(
        agent_id,
        create_transfer_request_payload(to_center_id, agent_version(agent_id),
                                        effective_date=effective_date),
        make_agent_headers(agent_id),
    ))


def setup_two_centers_with_agent():
    """Two ACTIVE centers; one ACTIVE unsponsored agent in the first."""
    mc1 = create_center(name="MC One")
    mc2 = create_center(name="MC Two")
    a1 = enroll_agent(mc1["id"])
    return {"mc1": mc1, "mc2": mc2, "a1": a1}
