"""Composite setup helpers.

Every test starts against an empty database, so each fixture builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
`get_success_data()` so a broken precondition surfaces as a clear "Setup
failed" message rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, DEFAULT_CUSTODIAN
from .test_users import (
    TEST_USERS, make_investor_headers, make_issuer_ops_headers,
    make_compliance_officer_headers,
)
from .factories import (
    create_artist_payload, create_investor_payload, create_artwork_payload,
    create_asset_report_payload, create_appraisal_payload, create_offering_payload,
    create_subscription_payload, create_custody_record_payload,
    create_insurance_policy_payload, create_cost_lot_payload,
    create_holding_decision_payload, create_transfer_order_payload,
    create_platform_account_payload, create_offering_report_payload,
)

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

PROVENANCE_REPORT = "Halden Provenance Research"
AUTHENTICATION_REPORT = "Vandermeer Catalogue Raisonne Committee"


def _setup(res, what):
    assert res.status_code < 300, (
        f"Setup failed at {what}: HTTP {res.status_code} {res.text[:300]}"
    )
    return get_success_data(res)


# ─── Tier 0: clock ───────────────────────────────────────────────────────────

def set_clock(current_utc: str):
    """Move the logical clock. Every temporal comparison reads this clock."""
    return _setup(api_client.set_clock(current_utc, ADMIN), "set_clock")


# ─── Tier 1: single-entity creation ──────────────────────────────────────────

def create_artist(**overrides) -> dict:
    return _setup(
        api_client.create_artist(create_artist_payload(**overrides), ISSUER),
        "create_artist")


def create_investor(**overrides) -> dict:
    return _setup(
        api_client.create_investor(create_investor_payload(**overrides), ANON),
        "create_investor")


def create_artwork(artist_id: str, **overrides) -> dict:
    return _setup(
        api_client.create_artwork(create_artwork_payload(artist_id, **overrides), ISSUER),
        "create_artwork")


def file_asset_report(artwork_id: str, **overrides) -> dict:
    return _setup(
        api_client.create_asset_report(
            artwork_id, create_asset_report_payload(**overrides), ISSUER),
        "file_asset_report")


def file_verified_provenance(artwork_id: str) -> dict:
    return file_asset_report(
        artwork_id, report_type="PROVENANCE", outcome="VERIFIED",
        firm_name=PROVENANCE_REPORT)


def file_verified_authentication(artwork_id: str) -> dict:
    return file_asset_report(
        artwork_id, report_type="AUTHENTICATION", outcome="VERIFIED",
        firm_name=AUTHENTICATION_REPORT)


def authenticate_artwork(artwork_id: str):
    """File both verified components so the work leaves APPRAISED.

    The trust chain needs a VERIFIED AUTHENTICATION *and* a VERIFIED
    PROVENANCE component together; either alone leaves the work where it is.
    """
    file_verified_provenance(artwork_id)
    file_verified_authentication(artwork_id)
    return get_artwork(artwork_id)


def get_artwork(artwork_id: str) -> dict:
    return _setup(api_client.get_artwork(artwork_id, ISSUER), "get_artwork")


def get_offering(offering_id: str) -> dict:
    return _setup(api_client.get_offering(offering_id, ISSUER), "get_offering")


def offering_version(offering_id: str) -> int:
    """Read the offering's current version, for an expected-version field."""
    return get_offering(offering_id)["version"]


def artwork_version(artwork_id: str) -> int:
    return get_artwork(artwork_id)["version"]


def file_appraisal(artwork_id: str, appraised_value_cents: int, **overrides):
    """File an appraisal, threading the artwork's current version into the body."""
    payload = create_appraisal_payload(
        artwork_version(artwork_id), appraised_value_cents=appraised_value_cents,
        **overrides)
    return api_client.create_appraisal(artwork_id, payload, ISSUER)


def create_appraisal(artwork_id: str, appraised_value_cents: int, **overrides) -> dict:
    return _setup(
        file_appraisal(artwork_id, appraised_value_cents, **overrides),
        "create_appraisal")


def create_offering(artwork_id: str, **overrides) -> dict:
    return _setup(
        api_client.create_offering(
            artwork_id, create_offering_payload(**overrides), ISSUER),
        "create_offering")


def create_custody_record(offering_id: str, **overrides) -> dict:
    return _setup(
        api_client.create_custody_record(
            offering_id, create_custody_record_payload(**overrides), ISSUER),
        "create_custody_record")


def create_insurance_policy(offering_id: str, **overrides) -> dict:
    return _setup(
        api_client.create_insurance_policy(
            offering_id, create_insurance_policy_payload(**overrides), ISSUER),
        "create_insurance_policy")


def create_cost_lot(offering_id: str, **overrides) -> dict:
    return _setup(
        api_client.create_cost_lot(
            offering_id, create_cost_lot_payload(**overrides), ISSUER),
        "create_cost_lot")


def open_platform_account(**overrides) -> dict:
    return _setup(
        api_client.create_platform_account(
            create_platform_account_payload(**overrides), ADMIN),
        "open_platform_account")


def get_platform_account(account_id: str) -> dict:
    return _setup(
        api_client.get_platform_account(account_id, ADMIN), "get_platform_account")


# ─── Tier 2: state progression on the offering ───────────────────────────────

def file_circular(offering_id: str, circular_reference="CIRC-2026-3068-A"):
    """DRAFT -> QUALIFICATION_FILED, stamping the 30-day qualification window."""
    return api_client.file_qualification(
        offering_id,
        {"circular_reference": circular_reference,
         "expected_offering_version": offering_version(offering_id)},
        COMPLIANCE)


def allocate_offering(offering_id: str):
    """QUALIFICATION_FILED -> ALLOCATED, running the allotment clamp."""
    return api_client.allocate(
        offering_id, {"expected_offering_version": offering_version(offering_id)},
        COMPLIANCE)


def receive_custody(custody_id: str, offering_id: str):
    """Receive the work; this is the transition that starts the holding clock."""
    return api_client.receive_custody(
        custody_id, {"expected_offering_version": offering_version(offering_id)},
        ISSUER)


def release_custody(custody_id: str, offering_id: str):
    return api_client.release_custody(
        custody_id, {"expected_offering_version": offering_version(offering_id)},
        ISSUER)


def bind_policy(policy_id: str):
    return api_client.bind_policy(policy_id, {}, ISSUER)


def lapse_policy(policy_id: str):
    return api_client.lapse_policy(policy_id, {}, ISSUER)


def approve_decision(decision_id: str, offering_id: str, as_user_id="ops-desk-12"):
    """Approve a holding decision under a different officer than its proposer."""
    return api_client.approve_decision(
        decision_id,
        {"expected_offering_version": offering_version(offering_id)},
        make_issuer_ops_headers(as_user_id))


def reject_decision(decision_id: str, offering_id: str, as_user_id="officer-reyes"):
    return api_client.reject_decision(
        decision_id,
        {"expected_offering_version": offering_version(offering_id)},
        make_compliance_officer_headers(as_user_id))


def execute_sale(decision_id: str, offering_id: str, executed_gross_cents: int,
                 as_user_id="ops-desk-12"):
    return api_client.execute_sale(
        decision_id,
        {"executed_gross_cents": executed_gross_cents,
         "expected_offering_version": offering_version(offering_id)},
        make_issuer_ops_headers(as_user_id))


def create_screened_subscription(offering_id: str, investor_id: str,
                                 requested_shares=2000):
    """Submit a subscription for an investor and screen it VERIFIED.

    The Investor role is entity-backed, so the subscription is submitted with
    X-User-ID set to that investor's own id.
    """
    sub = _setup(
        api_client.create_subscription(
            create_subscription_payload(offering_id, investor_id,
                                        requested_shares=requested_shares),
            make_investor_headers(investor_id)),
        "create_subscription")
    _setup(api_client.screen_subscription(sub["id"], {"outcome": "VERIFIED"}, COMPLIANCE),
           "screen_subscription")
    return _setup(api_client.get_subscription(sub["id"], COMPLIANCE),
                  "get_subscription")


def collect_funds(subscription_id: str, amount_cents: int):
    return _setup(
        api_client.collect_subscription(subscription_id, {"amount_cents": amount_cents},
                                        ISSUER),
        "collect_funds")


# ─── Tier 3: full-lifecycle shortcuts ────────────────────────────────────────

def setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z", **artwork_overrides):
    """Clock set, artist registered, artwork cleared through both trust components.

    Returns (artist, artwork) with artwork.status == AUTHENTICATED.
    """
    set_clock(start_clock)
    artist = create_artist()
    artwork = create_artwork(artist["id"], **artwork_overrides)
    artwork = authenticate_artwork(artwork["id"])
    return artist, artwork


def setup_draft_offering(start_clock="2026-09-01T00:00:00Z", **offering_overrides):
    """Authenticated artwork with one DRAFT offering. Returns (artwork, offering)."""
    _, artwork = setup_authenticated_artwork(start_clock=start_clock)
    offering = create_offering(artwork["id"], **offering_overrides)
    return get_artwork(artwork["id"]), offering


def setup_filed_offering(start_clock="2026-09-01T00:00:00Z", **offering_overrides):
    """Authenticated artwork + offering driven to QUALIFICATION_FILED."""
    artwork, offering = setup_draft_offering(start_clock=start_clock,
                                             **offering_overrides)
    _setup(file_circular(offering["id"]), "file_circular")
    return artwork, get_offering(offering["id"])


def setup_allocated_offering(subscriptions, start_clock="2026-09-01T00:00:00Z",
                             investor_overrides=None, **offering_overrides):
    """Filed offering + screened subscriptions + one allocation pass.

    `subscriptions` is a list of (email, requested_shares) tuples. Returns
    (artwork, offering, investors, subscriptions).
    """
    artwork, offering = setup_filed_offering(start_clock=start_clock,
                                             **offering_overrides)
    investors, subs = [], []
    for email, requested in subscriptions:
        overrides = dict(investor_overrides or {})
        investor = create_investor(email=email, **overrides)
        investors.append(investor)
        subs.append(create_screened_subscription(
            offering["id"], investor["id"], requested_shares=requested))
    _setup(allocate_offering(offering["id"]), "allocate")
    # Re-read the subscriptions after the allocation pass so their stamped
    # accepted_shares reflect the allotment rather than the pre-pass snapshot.
    subs = [_setup(api_client.get_subscription(s["id"], COMPLIANCE), "get_subscription")
            for s in subs]
    return artwork, get_offering(offering["id"]), investors, subs


def setup_held_offering(subscription_shares=20000, start_clock="2026-08-01T00:00:00Z",
                        custody_clock="2027-01-05T00:00:00Z", **offering_overrides):
    """Allocated offering driven into custody: holding clock started, status HELD.

    Returns (artwork, offering, investor, subscription, custody_record).
    """
    artwork, offering = setup_filed_offering(start_clock=start_clock,
                                             **offering_overrides)
    investor = create_investor()
    sub = create_screened_subscription(offering["id"], investor["id"],
                                       requested_shares=subscription_shares)
    _setup(allocate_offering(offering["id"]), "allocate")
    custody = create_custody_record(offering["id"])
    set_clock(custody_clock)
    _setup(receive_custody(custody["id"], offering["id"]), "receive_custody")
    return (get_artwork(artwork["id"]), get_offering(offering["id"]), investor, sub,
            _setup(api_client.get_custody_record(custody["id"], ISSUER), "get_custody"))


def setup_held_offering_with_policy(subscription_shares=20000,
                                    start_clock="2026-08-01T00:00:00Z",
                                    custody_clock="2027-01-05T00:00:00Z",
                                    appraised_value_cents=90_000_000,
                                    **offering_overrides):
    """Held offering plus a bound (FORCE) insurance policy.

    Returns (artwork, offering, investor, subscription, custody, policy).
    """
    _, artwork = setup_authenticated_artwork(start_clock=start_clock)
    _setup(file_appraisal(artwork["id"], appraised_value_cents), "file_appraisal")
    offering = create_offering(artwork["id"], **offering_overrides)
    investor = create_investor()
    sub = create_screened_subscription(offering["id"], investor["id"],
                                       requested_shares=subscription_shares)
    _setup(file_circular(offering["id"]), "file_circular")
    _setup(allocate_offering(offering["id"]), "allocate")
    custody = create_custody_record(offering["id"])
    set_clock(custody_clock)
    _setup(receive_custody(custody["id"], offering["id"]), "receive_custody")
    policy = create_insurance_policy(offering["id"],
                                     coverage_cents=appraised_value_cents)
    _setup(bind_policy(policy["id"]), "bind_policy")
    return (get_artwork(artwork["id"]), get_offering(offering["id"]), investor, sub,
            custody, policy)


def setup_held_offering_with_cost_lots(lots, appraised_value_cents=90_000_000,
                                       **offering_overrides):
    """Held offering with a FORCE policy and a list of journaled cost lots.

    `lots` is a list of dicts of cost-lot overrides. Returns
    (artwork, offering, custody, policy, lots).
    """
    artwork, offering, _, _, custody, policy = setup_held_offering_with_policy(
        appraised_value_cents=appraised_value_cents, **offering_overrides)
    created = [create_cost_lot(offering["id"], **lot) for lot in lots]
    return artwork, get_offering(offering["id"]), custody, policy, created


def setup_sale_pending_offering(holding_clock="2027-01-05T00:00:00Z",
                                sale_clock="2027-06-30T00:00:00Z",
                                proposed_gross_cents=120_000_000,
                                executor_id="ops-desk-12",
                                lots=None,
                                appraised_value_cents=90_000_000,
                                **offering_overrides):
    """Held, insured offering with an approved SELL decision (offering SALE_PENDING).

    Returns (artwork, offering, decision, custody, lots).
    """
    artwork, offering, _, _, custody, _ = setup_held_offering_with_policy(
        custody_clock=holding_clock, appraised_value_cents=appraised_value_cents,
        **offering_overrides)
    created_lots = [create_cost_lot(offering["id"], **lot) for lot in (lots or [])]
    set_clock(sale_clock)
    decision = _setup(
        api_client.create_holding_decision(
            offering["id"],
            create_holding_decision_payload(decision_type="SELL",
                                            proposed_gross_cents=proposed_gross_cents),
            make_issuer_ops_headers("ops-desk-11")),
        "create_holding_decision")
    _setup(approve_decision(decision["id"], offering["id"], as_user_id=executor_id),
           "approve_decision")
    return (get_artwork(artwork["id"]), get_offering(offering["id"]),
            _setup(api_client.get_holding_decision(decision["id"], ISSUER), "get_decision"),
            custody, created_lots)


def setup_closed_offering_with_distribution(holding_clock="2027-01-05T00:00:00Z",
                                            sale_clock="2027-06-30T00:00:00Z",
                                            executed_gross_cents=120_000_000,
                                            lots=None,
                                            with_account=False,
                                            **offering_overrides):
    """Full lifecycle through a completed sale: CLOSED offering + CALCULATED distribution.

    Returns (artwork, offering, decision, distribution, account).
    """
    account = open_platform_account() if with_account else None
    artwork, offering, decision, _, _ = setup_sale_pending_offering(
        holding_clock=holding_clock, sale_clock=sale_clock, lots=lots,
        **offering_overrides)
    _setup(execute_sale(decision["id"], offering["id"], executed_gross_cents),
           "execute_sale")
    distributions = _setup(
        api_client.list_distributions(offering["id"], ISSUER), "list_distributions")
    assert distributions, "Setup failed: a completed sale must synthesise a distribution"
    return (get_artwork(artwork["id"]), get_offering(offering["id"]),
            _setup(api_client.get_holding_decision(decision["id"], ISSUER), "get_decision"),
            distributions[0], account)


# ─── Tier 4: share-ledger / cap targeting ────────────────────────────────────

def setup_offering_at_cap_boundary(total_shares=40_000, registration_cap_pct=2_000,
                                   subscription_shares=20_000,
                                   start_clock="2026-09-01T00:00:00Z"):
    """A DRAFT offering whose per-investor cap is a known share count."""
    _, artwork = setup_authenticated_artwork(start_clock=start_clock)
    offering = create_offering(artwork["id"], total_shares=total_shares,
                               registration_cap_pct=registration_cap_pct)
    return artwork, offering


def setup_waitlisted_offering(registration_cap_pct=500,
                              start_clock="2026-09-01T00:00:00Z"):
    """An allocated offering with exactly one WAITLISTED subscription.

    One investor asks for more than its cap twice, so the second request is
    clamped all the way to zero and lands on the waitlist; a second investor
    takes an accepted position so the offering is genuinely allocated.

    Returns (artwork, offering, investors, subscriptions).
    """
    artwork, offering = setup_filed_offering(
        start_clock=start_clock, total_shares=10_000, price_per_share_cents=2_000,
        registration_cap_pct=registration_cap_pct, exemption_type="REG_A_TIER2")
    over = create_investor(email="over@x.com")
    other = create_investor(email="other@x.com")
    subs = [
        create_screened_subscription(offering["id"], over["id"], requested_shares=3000),
        create_screened_subscription(offering["id"], over["id"], requested_shares=3000),
        create_screened_subscription(offering["id"], other["id"], requested_shares=3000),
    ]
    _setup(allocate_offering(offering["id"]), "allocate")
    subs = [_setup(api_client.get_subscription(s["id"], COMPLIANCE), "get_subscription")
            for s in subs]
    return get_artwork(artwork["id"]), get_offering(offering["id"]), [over, other], subs


# ─── Tier 5: secondary market shortcuts ──────────────────────────────────────

def setup_allocated_offering_with_holders(count=2, requested_shares=8000,
                                          registration_cap_pct=6_000,
                                          **offering_overrides):
    """Allocated offering (holding clock never started) with `count` holders.

    Returns (artwork, offering, investors, subscriptions).
    """
    investors, subs = [], []
    artwork, offering = setup_filed_offering(
        registration_cap_pct=registration_cap_pct, **offering_overrides)
    for i in range(count):
        investor = create_investor(email=f"holder{i}@x.com",
                                   legal_name=f"Holder {i}")
        investors.append(investor)
        subs.append(create_screened_subscription(
            offering["id"], investor["id"], requested_shares=requested_shares))
    _setup(allocate_offering(offering["id"]), "allocate")
    return (get_artwork(artwork["id"]), get_offering(offering["id"]),
            investors,
            [_setup(api_client.get_subscription(s["id"], COMPLIANCE), "get_subscription")
             for s in subs])


# Legacy aliases kept for readability in the suite.
setup_basic_scenario = setup_draft_offering