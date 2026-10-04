"""Composite setup helpers.

The interesting rules in this PRD all require the system to be in a
specific state that takes several API calls to reach (a LISTED app with
an ACTIVE installation, an issued invoice, an installation past its
data-deletion deadline, ...). These fixtures encapsulate those chains so
tests can focus on assertions. All helpers build their preconditions
from scratch using only PRD-declared endpoints and use the lenient
get_success_data() so a setup failure surfaces as a clear error.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_app_payload,
    create_app_version_payload,
    create_billing_charge_payload,
    create_developer_payload,
    create_installation_payload,
    create_invoice_payload,
    create_merchant_payload,
)
from .test_users import (
    make_admin_headers,
    make_developer_headers,
    make_merchant_headers,
    make_reviewer_headers,
)

_counter = itertools.count(1)


def _uniq(tag: str) -> str:
    return f"{tag}-{next(_counter)}"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def create_developer(company_name=None, contact_email=None, payout_currency="USD"):
    """Create a DeveloperAccount. Returns the developer dict."""
    payload = create_developer_payload(
        company_name=company_name or _uniq("Dev"),
        contact_email=contact_email or f"{_uniq('dev')}@example.com",
        payout_currency=payout_currency,
    )
    return get_success_data(api_client.create_developer(payload, make_admin_headers()))


def create_merchant(shop_domain=None, plan_tier="BASIC"):
    """Create a MerchantAccount. Returns the merchant dict."""
    payload = create_merchant_payload(
        shop_domain=shop_domain or f"{_uniq('shop')}.myshop.com",
        plan_tier=plan_tier,
    )
    return get_success_data(api_client.create_merchant(payload, make_admin_headers()))


def create_app(developer_id, name=None, category="PRODUCTIVITY"):
    """Create an app in DRAFT under the developer. Returns the app dict."""
    payload = create_app_payload(developer_id, name=name or _uniq("App"), category=category)
    return get_success_data(
        api_client.create_app(payload, make_developer_headers(developer_id))
    )


def create_app_version(app_id, developer_id, semver="1.0.0"):
    """Create an AppVersion (SUBMITTED) for the app. Returns the version dict."""
    payload = create_app_version_payload(semver=semver)
    return get_success_data(
        api_client.create_app_version(app_id, payload, make_developer_headers(developer_id))
    )


def submit_app(app_id, developer_id):
    """Submit (or resubmit) the app. Returns the app dict."""
    return get_success_data(
        api_client.submit_app(app_id, {}, make_developer_headers(developer_id))
    )


def register_permission_scope(code, risk_level="LOW"):
    """Register a scope in the permission catalog. Returns the scope dict."""
    return get_success_data(
        api_client.create_permission_scope(
            {"code": code, "risk_level": risk_level}, make_admin_headers()
        )
    )


def create_scope_request(version_id, developer_id, scope_code, justification=None):
    """Create a scope request on a version. Returns the scope-request dict."""
    payload = {"scope_code": scope_code}
    if justification is not None:
        payload["justification"] = justification
    return get_success_data(
        api_client.create_scope_request(
            version_id, payload, make_developer_headers(developer_id)
        )
    )


def decide_scope_request(scope_request_id, decision, denied_reason=None,
                         reviewer_id=TEST_DEFAULTS["REVIEWER_ID"]):
    """Reviewer decides a scope request. Returns the scope-request dict."""
    payload = {"decision": decision}
    if denied_reason is not None:
        payload["denied_reason"] = denied_reason
    return get_success_data(
        api_client.decide_scope_request(
            scope_request_id, payload, make_reviewer_headers(reviewer_id)
        )
    )


def approve_version(version_id, reviewer_id=TEST_DEFAULTS["REVIEWER_ID"]):
    """Reviewer approves an IN_REVIEW version. Returns the version dict."""
    return get_success_data(
        api_client.approve_version(
            version_id, {"reviewer_id": reviewer_id}, make_reviewer_headers(reviewer_id)
        )
    )


def publish_app(app_id, developer_id):
    """Developer publishes an APPROVED app. Returns the app dict."""
    return get_success_data(
        api_client.publish_app(app_id, {}, make_developer_headers(developer_id))
    )


def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin test-driving capability)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_admin_headers())
    )


# ---------------------------------------------------------------------------
# Tier 2: app lifecycle composites
# ---------------------------------------------------------------------------

def setup_listed_app(company=None, category="PRODUCTIVITY", scope_specs=None,
                     scope_decisions=None, developer=None):
    """Developer + app + version + submit + (optional scopes decided) + approve
    + publish. Returns (developer, app, version).

    scope_specs: optional list of {"code": ..., "risk_level": ...,
                 "justification": ...} to register and request before submit.
    scope_decisions: optional list of (index, decision, denied_reason) applied
                 after submit, before approve.
    developer: optional existing developer dict to own the app (per PRD §3.1
                 a developer may act only on their own apps, so multi-app
                 scenarios must share one developer account).
    """
    if developer is None:
        developer = create_developer(company_name=company)
    app = create_app(developer["id"], name=_uniq("App"), category=category)
    version = create_app_version(app["id"], developer["id"])
    requests = []
    if scope_specs:
        for spec in scope_specs:
            register_permission_scope(spec["code"], spec.get("risk_level", "LOW"))
            requests.append(
                create_scope_request(
                    version["id"], developer["id"], spec["code"],
                    justification=spec.get("justification"),
                )
            )
    submit_app(app["id"], developer["id"])
    if scope_decisions:
        for idx, decision, denied_reason in scope_decisions:
            requests[idx] = decide_scope_request(
                requests[idx]["id"], decision, denied_reason=denied_reason
            )
    approve_version(version["id"])
    app = publish_app(app["id"], developer["id"])
    return developer, app, version


def setup_active_installation(company=None, category="PRODUCTIVITY",
                              plan_tier="BASIC", scope_specs=None,
                              developer=None):
    """Listed app + merchant + installation + consent. The version requests no
    scopes by default, so the all-approved precondition holds vacuously.

    Returns (developer, app, version, merchant, installation).
    """
    developer, app, version = setup_listed_app(
        company=company, category=category, scope_specs=scope_specs,
        scope_decisions=(
            [(i, "APPROVED", None) for i in range(len(scope_specs))]
            if scope_specs else None
        ),
        developer=developer,
    )
    merchant = create_merchant(plan_tier=plan_tier)
    installation = get_success_data(
        api_client.create_installation(
            create_installation_payload(app["id"], merchant["id"]),
            make_merchant_headers(merchant["id"]),
        )
    )
    installation = get_success_data(
        api_client.consent_installation(
            installation["id"], {}, make_merchant_headers(merchant["id"])
        )
    )
    return developer, app, version, merchant, installation


# ---------------------------------------------------------------------------
# Tier 3: billing composites
# ---------------------------------------------------------------------------

def create_approved_charge(installation, developer, merchant, base_amount_cents,
                           charge_type="ONE_TIME", description=None,
                           discount_code=None):
    """Create a charge and have the merchant approve it. Returns the charge."""
    payload = create_billing_charge_payload(
        base_amount_cents=base_amount_cents,
        charge_type=charge_type,
        description=description or _uniq("charge"),
    )
    if discount_code is not None:
        payload["discount_code"] = discount_code
    charge = get_success_data(
        api_client.create_billing_charge(
            installation["id"], payload, make_developer_headers(developer["id"])
        )
    )
    charge = get_success_data(
        api_client.approve_charge(charge["id"], {}, make_merchant_headers(merchant["id"]))
    )
    return charge


def open_invoice(merchant, cycle=TEST_DEFAULTS["DEFAULT_CYCLE"]):
    """Open a MonthlyInvoice for the merchant. Returns the invoice dict."""
    return get_success_data(
        api_client.create_invoice(
            merchant["id"], create_invoice_payload(cycle=cycle), make_admin_headers()
        )
    )


def issue_invoice(invoice):
    """Issue an OPEN invoice with the correct OCC version. Returns issued dict."""
    return get_success_data(
        api_client.issue_invoice(
            invoice["id"],
            {"expected_invoice_version": invoice["version"]},
            make_admin_headers(),
        )
    )


def mark_invoice_paid(invoice):
    """Mark an ISSUED invoice paid. Returns the invoice dict."""
    return get_success_data(
        api_client.mark_invoice_paid(invoice["id"], {}, make_admin_headers())
    )


def setup_issued_invoice(company=None, category="PRODUCTIVITY",
                         charge_amounts=(2500,), charge_type="ONE_TIME",
                         cycle=TEST_DEFAULTS["DEFAULT_CYCLE"]):
    """Active installation + approved charges + issued invoice.

    Returns (developer, app, version, merchant, installation, charges, invoice).
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company=company, category=category
    )
    charges = [
        create_approved_charge(
            installation, developer, merchant, amount, charge_type=charge_type
        )
        for amount in charge_amounts
    ]
    invoice = open_invoice(merchant, cycle=cycle)
    invoice = issue_invoice(invoice)
    return developer, app, version, merchant, installation, charges, invoice


def setup_paid_invoice(company=None, category="PRODUCTIVITY",
                       charge_amounts=(2500,), cycle=TEST_DEFAULTS["DEFAULT_CYCLE"]):
    """Issued invoice then marked PAID.

    Returns (developer, app, version, merchant, installation, charges, invoice).
    """
    developer, app, version, merchant, installation, charges, invoice = (
        setup_issued_invoice(
            company=company, category=category, charge_amounts=charge_amounts,
            cycle=cycle,
        )
    )
    invoice = mark_invoice_paid(invoice)
    return developer, app, version, merchant, installation, charges, invoice


# ---------------------------------------------------------------------------
# Tier 4: uninstall composites
# ---------------------------------------------------------------------------

def setup_uninstalling_installation(company=None, category="PRODUCTIVITY",
                                    pending_charge_amount=None):
    """Active installation (optionally with one PENDING charge), then the
    merchant uninstalls. Returns (developer, app, merchant, installation, charge)
    where charge may be None.
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company=company, category=category
    )
    charge = None
    if pending_charge_amount is not None:
        charge = get_success_data(
            api_client.create_billing_charge(
                installation["id"],
                create_billing_charge_payload(base_amount_cents=pending_charge_amount),
                make_developer_headers(developer["id"]),
            )
        )
    installation = get_success_data(
        api_client.uninstall_installation(
            installation["id"], {}, make_merchant_headers(merchant["id"])
        )
    )
    return developer, app, merchant, installation, charge


def setup_uninstalled_installation(company=None, category="PRODUCTIVITY"):
    """Uninstalled + developer confirmed data deletion within the deadline.

    Returns (developer, app, merchant, installation).
    """
    developer, app, merchant, installation, _ = setup_uninstalling_installation(
        company=company, category=category
    )
    installation = get_success_data(
        api_client.confirm_data_deletion(
            installation["id"], {}, make_developer_headers(developer["id"])
        )
    )
    return developer, app, merchant, installation


# ---------------------------------------------------------------------------
# Tier 5: governance / strikes / performance composites
# ---------------------------------------------------------------------------

def add_performance_strikes(installation, developer, count, load_ms=300,
                            start_day=1, month="2026-09"):
    """Submit `count` breaching performance samples on distinct days. Each 300ms
    sample yields impact 600 > 200 budget, opening a PERFORMANCE_BREACH strike
    per breach. Returns the list of created samples.

    NOTE: per PRD §3.7, three consecutive breaching windows drive the app into
    `DELISTED` via the system-initiated performance transition — after the
    third sample the app leaves `SUSPENDED`, which disqualifies it from the
    admin delist action (§3.11 requires `SUSPENDED`). Use at most two samples
    when the goal is only to accumulate strikes; for larger strike counts
    interleave compliant samples (they reset the consecutive-breach tracker
    while the already-opened strikes stay `ACTIVE`).
    """
    samples = []
    for i in range(count):
        day = start_day + i
        sampled_at = f"{month}-{day:02d}T00:00:00Z"
        sample = get_success_data(
            api_client.create_performance_sample(
                installation["id"],
                {"storefront_load_ms": load_ms, "sampled_at": sampled_at},
                make_developer_headers(developer["id"]),
            )
        )
        samples.append(sample)
    return samples


def add_performance_strikes_without_perf_delist(installation, developer, count,
                                                start_day=1, month="2026-09"):
    """Open `count` ACTIVE PERFORMANCE_BREACH strikes without ever letting
    three consecutive windows breach (which would trigger the §3.7
    system-initiated `LISTED → DELISTED` transition). Pattern per strike:
    one breaching sample, then a compliant sample eight days later — far
    enough that its 7-day window excludes the breach, so the compliant
    reading resets the consecutive-breach tracker and returns the app to
    COMPLIANT per §3.7 "remains or returns to `COMPLIANT`". The compliant
    samples open no strikes; the breaching samples each open one, and
    already-opened strikes remain `ACTIVE`. Returns the created samples.

    NOTE: the pattern spans 10 days per strike (breach day + 8-day gap),
    rolling over month boundaries; the logical clock stays at its initial
    instant throughout (samples carry their own sampled_at), so strike
    windows (strike_start + 30 days per §2.13) are all still unexpired at
    delist time.
    """
    samples = []
    day = start_day
    month_i = int(month.split("-")[1])
    year = month.split("-")[0]

    def _stamp(d):
        # Roll day-of-month over month boundaries (Sep/Oct 2026 both fit the
        # scenarios this helper serves).
        import datetime as _dt
        base = _dt.date(int(year), month_i, 1)
        dt = base + _dt.timedelta(days=d - 1)
        return f"{dt.isoformat()}T00:00:00Z"

    for _ in range(count):
        for load, offset in ((300, 0), (100, 8)):
            samples.append(
                get_success_data(
                    api_client.create_performance_sample(
                        installation["id"],
                        {"storefront_load_ms": load, "sampled_at": _stamp(day + offset)},
                        make_developer_headers(developer["id"]),
                    )
                )
            )
        day += 10
    return samples


def setup_suspended_app(company=None, category="PRODUCTIVITY"):
    """Listed app suspended by the platform. Returns (developer, app, version)."""
    developer, app, version = setup_listed_app(company=company, category=category)
    app = get_success_data(api_client.suspend_app(app["id"], {}, make_admin_headers()))
    return developer, app, version


def setup_suspended_app_with_strikes(strike_count=5, company=None,
                                     category="PRODUCTIVITY",
                                     with_pending_charge=None):
    """Listed app with an ACTIVE installation (optionally holding one PENDING
    charge), suspended, then `strike_count` ACTIVE PERFORMANCE_BREACH strikes
    opened via breaching performance samples on distinct days. Compliant
    samples are interleaved so no run of three consecutive breaching windows
    ever forms — per PRD §3.7 that would drive the app `LISTED → DELISTED`
    through the system-initiated transition, leaving it ineligible for the
    admin delist action (§3.11 requires `SUSPENDED`).

    Returns (developer, app, version, merchant, installation, charge).
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company=company, category=category
    )
    charge = None
    if with_pending_charge is not None:
        charge = get_success_data(
            api_client.create_billing_charge(
                installation["id"],
                create_billing_charge_payload(base_amount_cents=with_pending_charge),
                make_developer_headers(developer["id"]),
            )
        )
    app = get_success_data(api_client.suspend_app(app["id"], {}, make_admin_headers()))
    add_performance_strikes_without_perf_delist(installation, developer,
                                                strike_count)
    return developer, app, version, merchant, installation, charge


# ---------------------------------------------------------------------------
# Support ticket composites
# ---------------------------------------------------------------------------

def setup_support_ticket(severity="LOW", company=None, category="PRODUCTIVITY"):
    """Developer + app + merchant + one OPEN support ticket.

    Returns (developer, app, merchant, ticket).
    """
    developer = create_developer(company_name=company)
    app = create_app(developer["id"], name=_uniq("App"), category=category)
    merchant = create_merchant()
    ticket = get_success_data(
        api_client.create_support_ticket(
            app["id"],
            {"merchant_id": merchant["id"], "severity": severity},
            make_merchant_headers(merchant["id"]),
        )
    )
    return developer, app, merchant, ticket
