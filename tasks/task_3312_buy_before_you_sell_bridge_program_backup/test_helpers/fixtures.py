"""Composite setup helpers for multi-step test prerequisites.

Every helper drives the public API surface only. The logical clock is pinned to
the PRD's startup default before each scenario so that date-sensitive rules are
reproducible. Setup failures surface as clear "Setup failed" errors because
setup uses the lenient get_success_data() validator.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_START
from .factories import (
    create_homeowner_payload,
    create_property_payload,
    create_qualification_payload,
    create_bridge_program_payload,
    create_fund_payload,
    create_bridge_advance_payload,
    create_carrying_cost_payload,
    create_repair_advance_payload,
    create_backup_offer_payload,
    create_listing_payload,
    create_agent_payload,
    create_referral_payload,
    create_coordination_task_payload,
    create_disbursement_payload,
    create_repayment_payload,
)
from .test_users import TEST_USERS, make_homeowner_headers, make_agent_headers

COORD = TEST_USERS["coordinator_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]


# ─── The logical clock ────────────────────────────────────────

def reset_clock(to_iso8601: str = LOGICAL_CLOCK_START):
    """Pin the logical clock to the PRD's startup default (or a supplied instant)."""
    data = get_success_data(api_client.set_clock(to_iso8601, COORD))
    assert data.get("current_utc"), "clock endpoint must report current_utc"
    return data


def advance_clock(to_iso8601: str):
    """Advance the logical clock to an explicit instant through the clock endpoint."""
    return reset_clock(to_iso8601)


# ─── Tier 1: single-entity creation ───────────────────────────

def create_homeowner(**overrides):
    payload = create_homeowner_payload(**overrides)
    res = api_client.create_homeowner(payload, COORD)
    assert res.status_code == 201, f"Setup failed: create homeowner -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def create_property(homeowner_id, **overrides):
    payload = create_property_payload(homeowner_id, **overrides)
    res = api_client.create_property(payload, COORD)
    assert res.status_code == 201, f"Setup failed: create property -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def make_property(homeowner_id, kind, default_address=None, **overrides):
    """A property of the stated kind; DEPARTING defaults differ from NEW defaults.

    The third positional argument is the fallback address (as supplied by
    `create_departing_and_new`). An `address` key inside `overrides` names the
    record's address explicitly and wins over the fallback. Because the address
    cannot arrive through both channels, a splatted override dict that includes
    `address` never trips a duplicate-argument TypeError.
    """
    address = overrides.pop("address", default_address) or "1 Test Way"
    if kind == "DEPARTING":
        base = {"kind": "DEPARTING", "address": address,
                "appraised_value_cents": 70_000_000, "mortgage_payoff_cents": 30_000_000,
                "condition_grade": "B"}
    else:
        base = {"kind": "NEW", "address": address,
                "appraised_value_cents": 55_000_000, "purchase_price_cents": 50_000_000,
                "condition_grade": "A"}
    base.update(overrides)
    return create_property(homeowner_id, **base)


def create_agent(**overrides):
    payload = create_agent_payload(**overrides)
    res = api_client.create_agent(payload, COORD)
    assert res.status_code == 201, f"Setup failed: create agent -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def qualify_agent(agent_id):
    data = get_success_data(api_client.qualify_agent(agent_id, COORD))
    assert data["qualification_status"] == "QUALIFIED", "Setup failed: agent not qualified"
    return data


def suspend_agent(agent_id):
    return get_success_data(api_client.suspend_agent(agent_id, COORD))


# ─── Tier 2: hierarchy + qualification ────────────────────────

def create_departing_and_new(homeowner_id, departing=None, new=None):
    dep = make_property(homeowner_id, "DEPARTING", "1 Departing Way", **(departing or {}))
    newp = make_property(homeowner_id, "NEW", "2 New Way", **(new or {}))
    return dep, newp


def create_qualification(homeowner_id, departing_property_id, new_property_id, **overrides):
    payload = create_qualification_payload(
        homeowner_id, departing_property_id, new_property_id, **overrides
    )
    res = api_client.create_qualification(payload, COORD)
    assert res.status_code == 201, f"Setup failed: create qualification -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def approve_qualification(qualification_id):
    return get_success_data(api_client.approve_qualification(qualification_id, COORD))


def get_qualification(qualification_id):
    return get_success_data(api_client.get_qualification(qualification_id, COORD))


def get_backup_offer(offer_id: str):
    return get_success_data(api_client.get_backup_offer(offer_id, COORD))


def get_referral(referral_id: str):
    return get_success_data(api_client.get_referral(referral_id, COORD))


def create_referral(agent_id: str, program_id: str, role_scope: str = "DEPARTING_SIDE",
                    volume_cents: int = 0):
    res = api_client.create_referral(
        create_referral_payload(agent_id, program_id, role_scope=role_scope,
                                qualifying_volume_cents=volume_cents),
        COORD,
    )
    assert res.status_code == 201, f"Setup failed: create referral -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def build_qualified_household(credit_score: int = 700, income_cents: int = 30_000_000,
                              departing: dict = None, new: dict = None):
    """Create homeowner + departing property + new property. Returns a dict."""
    reset_clock()
    h = create_homeowner(credit_score=credit_score, household_income_cents=income_cents)
    dep, newp = create_departing_and_new(h["id"], departing, new)
    return {"homeowner": h, "departing": dep, "new": newp}


def create_approved_qualification(sc, variant: str = "CONSERVATIVE", **overrides):
    """Approve a qualification on the given household scenario. Returns the qualification."""
    q = create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used=variant, **overrides
    )
    approved = approve_qualification(q["id"])
    return approved


def enroll_bridge_program(sc, qualification_id: str, **overrides):
    payload = create_bridge_program_payload(
        sc["homeowner"]["id"], qualification_id, sc["new"]["id"], sc["departing"]["id"],
        **overrides
    )
    res = api_client.create_bridge_program(payload, COORD)
    assert res.status_code == 201, f"Setup failed: enroll program -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def fund_program(program_id: str, interest_rate_bps: int = 800, version: int = None):
    """Fund the program. Returns (program_after_fund, interim_loan)."""
    if version is None:
        version = get_success_data(api_client.get_bridge_program(program_id, COORD))["version"]
    res = api_client.fund_bridge_program(
        program_id, create_fund_payload(version, interest_rate_bps=interest_rate_bps), COORD
    )
    program = get_success_data(res)
    return program, loan_for(program_id)


def loan_for(program_id: str):
    """The interim loan attached to a program (funding originates exactly one)."""
    res = api_client.list_interim_loans(COORD, params={"bridge_program_id": program_id})
    assert res.status_code == 200, f"Setup failed: list interim loans -> {res.status_code} {res.text}"
    body = res.json()
    loans = body.get("data")
    if isinstance(loans, dict):
        loans = loans.get("items") or loans.get("results") or []
    assert isinstance(loans, list) and loans, f"Setup failed: no interim loan for {program_id}"
    return loans[0]


def get_loan(loan_id: str):
    return get_success_data(api_client.get_interim_loan(loan_id, COORD))


def get_program(program_id: str):
    return get_success_data(api_client.get_bridge_program(program_id, COORD))


def setup_funded_program(variant: str = "CONSERVATIVE", interest_rate_bps: int = 800,
                         months: int = 4, credit_score: int = 700, income_cents: int = 30_000_000,
                         departing: dict = None, new: dict = None, fee_bps: int = None):
    """Homeowner + properties + approved qualification + enrolled and funded program.

    Returns a dict: homeowner, departing, new, qualification, program, loan.
    """
    sc = build_qualified_household(credit_score, income_cents, departing, new)
    q = create_approved_qualification(sc, variant)
    sc["qualification"] = q
    prog_over = {"projected_carry_months": months}
    if fee_bps is not None:
        prog_over["program_fee_basis_points"] = fee_bps
    bp = enroll_bridge_program(sc, q["id"], **prog_over)
    program, loan = fund_program(bp["id"], interest_rate_bps)
    sc["program"] = program
    sc["loan"] = loan
    return sc


# ─── Tier 3: lifecycle shortcuts ─────────────────────────────

def occupy_new_home(program_id: str, as_homeowner_id: str = None):
    headers = make_homeowner_headers(as_homeowner_id) if as_homeowner_id else COORD
    return get_success_data(api_client.occupy_new(program_id, headers))


def record_site_visit(property_id: str):
    """Record one coordinator site visit and return the refreshed property."""
    return get_success_data(api_client.record_site_visit(property_id, COORD))


def complete_repairs(departing_property_id: str, visits: int = 3):
    """Record enough site visits for repair_status to reach COMPLETE (default cap 300)."""
    prop = None
    for _ in range(visits):
        prop = get_success_data(api_client.record_site_visit(departing_property_id, COORD))
    return prop


def draft_listing(departing_property_id: str, program_id: str, list_price_cents: int = 44_000_000):
    res = api_client.create_listing(
        create_listing_payload(departing_property_id, program_id, list_price_cents=list_price_cents),
        COORD,
    )
    assert res.status_code == 201, f"Setup failed: create listing -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def go_live_departing(sc):
    """Walk a funded program to the point where the departing home is LIVE.

    occupy-new -> three site visits -> draft listing -> go-live.
    Returns a dict with 'listing' and the refreshed 'program' and 'departing'.
    """
    occupy_new_home(sc["program"]["id"], sc["homeowner"]["id"])
    complete_repairs(sc["departing"]["id"], visits=3)
    listing = draft_listing(sc["departing"]["id"], sc["program"]["id"])
    live = get_success_data(api_client.go_live_listing(listing["id"], COORD))
    return {"listing": live,
            "program": get_program(sc["program"]["id"]),
            "departing": get_success_data(api_client.get_property(sc["departing"]["id"], COORD))}


def create_issued_backup_offer(sc, offer_price_cents: int = 61_000_000, window_days: int = 30,
                               as_user_id: str = None):
    """Departing home LIVE + backup offer drafted and issued. Returns the issued offer."""
    go_live_departing(sc)
    offer = draft_backup_offer(sc, offer_price_cents, window_days, as_user_id)
    issued = issue_backup_offer(offer["id"], as_user_id)
    return issued


def draft_backup_offer(sc, offer_price_cents: int = 61_000_000, window_days: int = 30,
                       as_user_id: str = None, window_start: str = LOGICAL_CLOCK_START):
    payload = create_backup_offer_payload(
        sc["departing"]["id"], sc["program"]["id"],
        offer_price_cents=offer_price_cents, window_days=window_days, window_start=window_start,
    )
    headers = _coord_headers(as_user_id)
    res = api_client.create_backup_offer(payload, headers)
    assert res.status_code == 201, f"Setup failed: draft offer -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def issue_backup_offer(offer_id: str, as_user_id: str = None):
    return get_success_data(api_client.issue_backup_offer(offer_id, _coord_headers(as_user_id)))


def _coord_headers(user_id: str = None):
    from prd_bench_local_runner.testing import build_user_headers
    return build_user_headers(user_id, "Coordinator") if user_id else COORD


# ─── Tier 4: advances, draws and threshold targeting ────────

def create_advance(program_id: str, loan_id: str, purpose: str, amount_cents: int,
                   as_underwriter: bool = False):
    payload = create_bridge_advance_payload(
        program_id, loan_id, purpose=purpose, amount_cents=amount_cents
    )
    res = api_client.create_bridge_advance(payload, COORD)
    assert res.status_code == 201, f"Setup failed: create advance -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def approve_advance(advance_id: str):
    return get_success_data(api_client.approve_bridge_advance(advance_id, UNDERWRITER))


def disburse_advance(advance_id: str):
    return get_success_data(api_client.disburse_bridge_advance(advance_id, COORD))


def approved_advance(program_id: str, loan_id: str, purpose: str, amount_cents: int):
    adv = create_advance(program_id, loan_id, purpose, amount_cents)
    return approve_advance(adv["id"])


def drawn_advance(program_id: str, loan_id: str, purpose: str, amount_cents: int):
    """Create -> approve -> disburse. Returns the disbursed advance."""
    adv = approved_advance(program_id, loan_id, purpose, amount_cents)
    return disburse_advance(adv["id"])


def record_carrying_cost(program_id: str, kind: str, amount_cents: int,
                         due_date: str = "2026-10-01T00:00:00Z"):
    res = api_client.create_carrying_cost(
        create_carrying_cost_payload(program_id, kind=kind, amount_cents=amount_cents,
                                     due_date=due_date),
        COORD,
    )
    assert res.status_code == 201, f"Setup failed: carrying cost -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def program_summary(program_id: str):
    return get_success_data(api_client.get_program_summary(program_id, COORD))


# ─── Tier 5: partner / referral workflows ───────────────────

def setup_referral(program_id: str, qualified: bool = False, role_scope: str = "DEPARTING_SIDE",
                   volume_cents: int = 0, license_number: str = None):
    """Register an agent (optionally qualified) and open a referral on the program."""
    agent = create_agent(license_number=license_number or f"LIC-{program_id[:8]}")
    if qualified:
        qualify_agent(agent["id"])
    res = api_client.create_referral(
        create_referral_payload(agent["id"], program_id, role_scope=role_scope,
                                qualifying_volume_cents=volume_cents),
        COORD,
    )
    assert res.status_code == 201, f"Setup failed: create referral -> {res.status_code} {res.text}"
    return agent, get_success_data(res, 201)


def create_task(program_id: str, referral_id: str, task_kind: str = "PHOTOGRAPHY",
                due_date: str = "2026-09-20T00:00:00Z"):
    res = api_client.create_coordination_task(
        create_coordination_task_payload(program_id, referral_id, task_kind=task_kind,
                                         due_date=due_date),
        COORD,
    )
    assert res.status_code == 201, f"Setup failed: create task -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def complete_task(task_id: str, as_agent_id: str = None):
    headers = make_agent_headers(as_agent_id) if as_agent_id else COORD
    return get_success_data(api_client.complete_coordination_task(task_id, headers))


def setup_completed_tasks(program_id: str, referral_id: str, count: int, first_kind: str = "PHOTOGRAPHY"):
    """Create `count` non-overlapping tasks and complete them all. Returns task list."""
    kinds = ["PHOTOGRAPHY", "INSPECTION", "APPRAISAL", "REPAIR_BID", "CLOSING_PREP", "RESALE_PREP"]
    months = ["2026-09-20", "2026-10-20", "2026-11-20", "2026-12-20", "2027-01-20", "2027-02-20"]
    tasks = []
    for i in range(count):
        t = create_task(program_id, referral_id, kinds[i % len(kinds)],
                        due_date=f"{months[i % len(months)]}T00:00:00Z")
        complete_task(t["id"])
        tasks.append(t)
    return tasks


def setup_repair_advance(program_id: str, property_id: str, approved_amount_cents: int = 3_000_000,
                         scope: str = "Deck repair"):
    res = api_client.create_repair_advance(
        create_repair_advance_payload(property_id, program_id, scope=scope,
                                      approved_amount_cents=approved_amount_cents),
        COORD,
    )
    assert res.status_code == 201, f"Setup failed: repair advance -> {res.status_code} {res.text}"
    return get_success_data(res, 201)


def record_settlement(program_id: str, source_kind: str, amount_cents: int):
    res = api_client.create_disbursement(
        create_disbursement_payload(program_id, source_kind=source_kind,
                                    amount_cents=amount_cents),
        COORD,
    )
    assert res.status_code == 201, f"Setup failed: settlement -> {res.status_code} {res.text}"
    return get_success_data(res, 201)