"""Composite setup helpers.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before each test) using only PRD-declared
endpoints. Setup calls use get_success_data() so failures surface as clear
"Setup failed" errors. Ownership-gated calls are made with per-instance
headers built from the actual entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_advisor_payload,
    create_administrator_payload,
    create_branch_payload,
    create_charge_payload,
    create_financial_period_payload,
    create_goodwill_transfer_payload,
    create_production_payload,
    create_shelf_entry_payload,
    create_solicitation_payload,
    create_territory_payload,
)
from .test_users import TEST_USERS, make_advisor_headers

ADMIN = TEST_USERS["home_office_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_principal_headers"]


def _setup_failed(step, resp):
    raise AssertionError(f"Setup failed at {step}: HTTP {resp.status_code} body={resp.text}")


def _ok(resp, step):
    if resp.status_code >= 400:
        _setup_failed(step, resp)
    return get_success_data(resp)


def _norm_instant(value):
    """Normalize an ISO-8601 instant for equality: drop fractional seconds and
    the trailing Z so '2026-09-01T00:00:00Z' matches '2026-09-01T00:00:00.000Z'."""
    return value.split(".")[0].rstrip("Z")


# ---------------------------------------------------------------------------
# Tier 1/2: advisors, training, territories, branches
# ---------------------------------------------------------------------------

def create_advisor(**overrides):
    resp = api_client.create_advisor(create_advisor_payload(**overrides), ADMIN)
    return _ok(resp, "create_advisor")


def create_validated_advisor(goal_cents=100, seed_gross=200,
                             start_date="2026-01-05T00:00:00Z",
                             seed_posted_at="2026-01-06T00:00:00Z",
                             eval_window_end="2026-04-05T00:00:00Z",
                             **advisor_overrides):
    """Create an advisor, enroll in training, post enough production to pass,
    submit and evaluate the milestone. Returns the VALIDATED advisor record."""
    advisor = create_advisor(hire_date=start_date, **advisor_overrides)
    resp = api_client.enroll_training(
        advisor["id"],
        {"goal_cents": goal_cents, "start_date": start_date},
        ADMIN,
    )
    program = _ok(resp, "enroll_training")
    resp = api_client.create_production_record(
        create_production_payload(advisor["id"], seed_gross, posted_at=seed_posted_at),
        ADMIN,
    )
    _ok(resp, "seed production record")
    resp = api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    _ok(resp, "submit_milestone")
    resp = api_client.evaluate_milestone(
        program["id"], {"window_end": eval_window_end}, ADMIN,
    )
    _ok(resp, "evaluate_milestone")
    return get_success_data(api_client.get_advisor(advisor["id"], ADMIN))


def create_territory(**overrides):
    resp = api_client.create_territory(create_territory_payload(**overrides), ADMIN)
    return _ok(resp, "create_territory")


def create_branch(territory_id=None, **overrides):
    """Create a territory (unless one is supplied) plus a PROPOSED branch.
    Returns (branch, territory)."""
    territory = create_territory() if territory_id is None else None
    tid = territory_id if territory_id is not None else territory["id"]
    resp = api_client.create_branch(create_branch_payload(tid, **overrides), ADMIN)
    return _ok(resp, "create_branch"), territory


def create_site_approved_branch(territory_id=None, site_address=None,
                                term_start="2026-08-01T00:00:00Z",
                                term_end="2027-07-31T00:00:00Z",
                                monthly_rent_cents=150000,
                                **overrides):
    """Create branch and approve its site (signs the lease).
    Returns (branch, territory)."""
    if site_address is not None:
        overrides.setdefault("site_address", site_address)
    branch, territory = create_branch(territory_id=territory_id, **overrides)
    resp = api_client.approve_site(
        branch["id"],
        {
            "monthly_rent_cents": monthly_rent_cents,
            "term_start": term_start,
            "term_end": term_end,
        },
        ADMIN,
    )
    branch = _ok(resp, "approve_site")
    return branch, territory


def create_open_branch(with_advisor=True, **overrides):
    """Fully staffed OPEN branch. Returns
    (branch, territory, advisor_or_none, administrator)."""
    branch, territory = create_site_approved_branch(**overrides)
    advisor = None
    if with_advisor:
        advisor = create_validated_advisor()
        resp = api_client.assign_branch(advisor["id"], {"branch_id": branch["id"]}, ADMIN)
        _ok(resp, "assign_branch")
    boa = create_administrator()
    resp = api_client.assign_administrator(
        branch["id"], {"administrator_id": boa["id"]}, ADMIN,
    )
    boa = _ok(resp, "assign_administrator")
    resp = api_client.open_branch(branch["id"], ADMIN)
    branch = _ok(resp, "open_branch")
    if advisor is not None:
        advisor = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    return branch, territory, advisor, boa


def create_administrator(**overrides):
    resp = api_client.create_administrator(create_administrator_payload(**overrides), ADMIN)
    return _ok(resp, "create_administrator")


# ---------------------------------------------------------------------------
# Tier 3/4: production, periods, charges
# ---------------------------------------------------------------------------

def post_production(advisor_id, gross_commission_cents, posted_at, payout_rate=1.0):
    resp = api_client.create_production_record(
        create_production_payload(
            advisor_id, gross_commission_cents, posted_at=posted_at, payout_rate=payout_rate,
        ),
        ADMIN,
    )
    return _ok(resp, "create_production_record")


def create_period(branch_id, period_start="2026-09-01T00:00:00Z",
                  period_end="2026-10-01T00:00:00Z"):
    resp = api_client.create_financial_period(
        create_financial_period_payload(
            branch_id, period_start=period_start, period_end=period_end,
        ),
        ADMIN,
    )
    return _ok(resp, "create_financial_period")


def post_charge(period_id, branch_id, amount_cents, charge_type="LEASE_RENT"):
    resp = api_client.post_charge(
        period_id, create_charge_payload(branch_id, amount_cents, charge_type), ADMIN,
    )
    return _ok(resp, "post_charge")


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    if resp.status_code >= 400:
        _setup_failed("set_clock", resp)


def get_period(period_id):
    return get_success_data(api_client.get_financial_period(period_id, ADMIN))


def setup_open_branch_with_period(period_start="2026-09-01T00:00:00Z",
                                  period_end="2026-10-01T00:00:00Z",
                                  **branch_overrides):
    """Fully staffed OPEN branch plus an OPEN period.

    Opening a branch auto-creates the branch's first OPEN period covering the
    current calendar month (the clock starts at 2026-09-01, so the auto period
    spans September), and a branch's periods must never overlap. When the
    requested window matches the auto period's, fetch that period through the
    branch's period listing instead of attempting an overlapping creation;
    when the caller requests a non-overlapping later window, an additional
    period is created and returned.
    Returns (branch, territory, advisor, boa, period)."""
    branch, territory, advisor, boa = create_open_branch(**branch_overrides)
    data = get_success_data(api_client.list_branch_financial_periods(branch["id"], ADMIN))
    periods = data["items"] if isinstance(data, dict) and "items" in data else data
    auto = [p for p in periods
            if _norm_instant(p["period_start"]) == _norm_instant(period_start)
            and _norm_instant(p["period_end"]) == _norm_instant(period_end)]
    if auto:
        period = auto[0]
    else:
        resp = api_client.create_financial_period(
            create_financial_period_payload(
                branch["id"], period_start=period_start, period_end=period_end,
            ),
            ADMIN,
        )
        # An overlapping creation must be rejected; only a genuine gap in the
        # branch's calendar permits a new period here.
        if resp.status_code >= 400:
            raise AssertionError(
                f"Setup failed at create_financial_period: requested window "
                f"[{period_start}, {period_end}) collides with the auto-created "
                f"first period(s) {[ (p['period_start'], p['period_end']) for p in periods ]}: "
                f"HTTP {resp.status_code} body={resp.text}"
            )
        period = get_success_data(resp)
    return branch, territory, advisor, boa, period


# ---------------------------------------------------------------------------
# Tier 3: retirement / goodwill
# ---------------------------------------------------------------------------

def setup_retiring_advisor_with_transfer(trailing_gross=2400000,
                                         trailing_posted_at="2026-03-10T00:00:00Z",
                                         valuation_mode="INTERNAL_SUCCESSION",
                                         escrow_deposit_cents=200000,
                                         clock="2026-09-05T00:00:00Z",
                                         legacy=True,
                                         with_boa=False):
    """Branch with a PRACTICING advisor who has declared retirement, trailing
    revenue posted inside the trailing-12-month window, and an OFFERED goodwill
    transfer. Returns (transfer, retiring_advisor, successor, branch)."""
    set_clock(clock)
    if legacy:
        advisor = create_validated_advisor(
            start_date="2020-01-01T00:00:00Z",
            seed_posted_at="2020-01-02T00:00:00Z",
            eval_window_end="2020-04-01T00:00:00Z",
        )
    else:
        advisor = create_validated_advisor()
    branch, territory = create_site_approved_branch(
        term_start="2020-01-01T00:00:00Z", term_end="2030-12-31T00:00:00Z",
    )
    resp = api_client.assign_branch(advisor["id"], {"branch_id": branch["id"]}, ADMIN)
    _ok(resp, "assign_branch")
    if with_boa:
        boa = create_administrator()
        resp = api_client.assign_administrator(
            branch["id"], {"administrator_id": boa["id"]}, ADMIN,
        )
        _ok(resp, "assign_administrator")
        resp = api_client.open_branch(branch["id"], ADMIN)
        branch = _ok(resp, "open_branch")
    if trailing_gross:
        post_production(advisor["id"], trailing_gross, trailing_posted_at)
    resp = api_client.declare_retirement(advisor["id"], make_advisor_headers(advisor["id"]))
    _ok(resp, "declare_retirement")
    successor = create_advisor(
        hire_date="2024-01-01T00:00:00Z" if legacy else "2026-02-01T00:00:00Z",
    )
    resp = api_client.create_goodwill_transfer(
        create_goodwill_transfer_payload(
            branch["id"], advisor["id"], successor["id"],
            valuation_mode=valuation_mode, escrow_deposit_cents=escrow_deposit_cents,
        ),
        ADMIN,
    )
    transfer = _ok(resp, "create_goodwill_transfer")
    advisor = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    return transfer, advisor, successor, branch


# ---------------------------------------------------------------------------
# Tier 3: product shelf & solicitations
# ---------------------------------------------------------------------------

def create_approved_shelf_entry(**overrides):
    resp = api_client.create_shelf_entry(create_shelf_entry_payload(**overrides), COMPLIANCE)
    entry = _ok(resp, "create_shelf_entry")
    resp = api_client.approve_shelf_entry(entry["id"], COMPLIANCE)
    return _ok(resp, "approve_shelf_entry")


def create_submitted_solicitation(advisor_id, product_code, **overrides):
    resp = api_client.create_solicitation_request(
        create_solicitation_payload(advisor_id, product_code, **overrides),
        make_advisor_headers(advisor_id),
    )
    return _ok(resp, "create_solicitation_request")


def setup_practicing_advisor_with_solicitation(product_overrides=None, **branch_overrides):
    """OPEN branch with a PRACTICING advisor, an APPROVED shelf entry and a
    SUBMITTED solicitation. Returns (branch, advisor, entry, request)."""
    branch, territory, advisor, boa = create_open_branch(**branch_overrides)
    entry = create_approved_shelf_entry(**(product_overrides or {}))
    request = create_submitted_solicitation(advisor["id"], entry["product_code"])
    return branch, advisor, entry, request
