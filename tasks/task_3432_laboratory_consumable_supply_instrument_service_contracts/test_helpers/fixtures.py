"""Composite setup builders - the state machine's preconditions, prebuilt.

Every builder drives the public API only; there is no direct database access
anywhere.  Builders use ``get_success_data`` so a create that the PRD answers
201 and a transition it answers 200 both pass without pinning the code at
every call site, and a failed setup step surfaces as a clear "Setup failed"
error rather than a confusing assertion deep inside a test.

Identity threading is mandatory throughout: every LabProcurement call is
signed with the owning account's own id via ``make_lab_procurement_headers``
and every FieldEngineer resolve with the assigned engineer's id via
``make_field_engineer_headers`` - never the shared placeholder constants.

The builders are phased: each one leaves the system in the state its name
promises and nothing a builder does at its last step invalidates a
precondition an earlier step of the same builder established.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    CLOCK_START_UTC,
    CREDIT_LIMIT_CENTS,
    TRANSIT_DAYS,
)
from .test_users import (
    ACCOUNT_MANAGER,
    ADMIN,
    DISPATCHER,
    SUPPLY_OPS,
    make_field_engineer_headers,
    make_lab_procurement_headers,
)


def _id_of(entity):
    """Accept an entity dict or a bare id string and return the id."""
    return entity["id"] if isinstance(entity, dict) else entity


# --- Instant arithmetic --------------------------------------------------------
# The PRD pins the logical clock's startup default and derives every window
# (365-day trailing spend, 60/30-day renewal windows, transit days) from it;
# fixtures therefore compute instants rather than hardcoding calendar dates.

def parse_instant(value):
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment):
    """Render a UTC datetime the way fixture payloads spell instants."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_seconds(instant, seconds):
    return format_instant(parse_instant(instant) + timedelta(seconds=seconds))


def plus_days(instant, days):
    return format_instant(parse_instant(instant) + timedelta(days=days))


def plus_months(instant, months):
    """Calendar-month addition used by the 12-month renewal recipes."""
    moment = parse_instant(instant)
    month_index = (moment.year * 12 + (moment.month - 1)) + months
    year, month = divmod(month_index, 12)
    day = min(moment.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                           31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return format_instant(moment.replace(year=year, month=month + 1, day=day))


# --- Logical clock (PRD section 2.4) ----------------------------------------------

def set_clock(to_iso8601, headers=ADMIN):
    """Move the logical clock; runs the delivery sweep.  Returns the echo."""
    response = api_client.set_clock(to_iso8601, headers=headers)
    return get_success_data(response)


# --- Accounts (PRD section 3.1) ------------------------------------------------------

def create_account(headers=ACCOUNT_MANAGER, **overrides):
    response = api_client.create_account(f.account_payload(**overrides), headers=headers)
    return get_success_data(response)


def get_account(account, headers=ACCOUNT_MANAGER):
    response = api_client.get_account(_id_of(account), headers=headers)
    return get_success_data(response)


def patch_account(account, headers=ACCOUNT_MANAGER, **fields):
    response = api_client.update_account(_id_of(account), fields, headers=headers)
    return get_success_data(response)


def suspend_account(account, headers=ACCOUNT_MANAGER):
    return patch_account(account, headers=headers, status="SUSPENDED")


def reactivate_account(account, headers=ACCOUNT_MANAGER):
    return patch_account(account, headers=headers, status="ACTIVE")


def close_account(account, headers=ACCOUNT_MANAGER):
    return patch_account(account, headers=headers, status="CLOSED")


# --- Catalog (PRD section 3.6) ---------------------------------------------------------

def create_catalog_item(headers=SUPPLY_OPS, **overrides):
    response = api_client.create_catalog_item(
        f.catalog_item_payload(**overrides), headers=headers
    )
    return get_success_data(response)


def get_catalog_item_by_sku(sku, headers=SUPPLY_OPS):
    """The catalog has no get-by-id endpoint; the list accepts a sku filter."""
    response = api_client.list_catalog_items(headers=headers, params={"sku": sku})
    items = get_success_data(response)
    assert items, "Setup failed: no catalog item with sku {0}".format(sku)
    return items[0]


# --- Engineers and loaner units (PRD section 3.5) ------------------------------------------

def create_engineer(headers=DISPATCHER, **overrides):
    response = api_client.create_engineer(f.engineer_payload(**overrides), headers=headers)
    return get_success_data(response)


def ensure_engineer(account, skills, headers=DISPATCHER, **overrides):
    """An ACTIVE engineer covering the account's territory with the given skills."""
    overrides.setdefault("territory_code", account["territory_code"])
    overrides.setdefault("skills", list(skills))
    overrides.setdefault("status", "ACTIVE")
    return create_engineer(headers=headers, **overrides)


def ensure_install_engineer(account, headers=DISPATCHER, **overrides):
    """The INSTALL-skilled territory engineer an install transition requires."""
    return ensure_engineer(account, ["INSTALL"], headers=headers, **overrides)


def create_engineers_staggered(count, base_instant=CLOCK_START_UTC, step_seconds=1,
                               per_engineer=None, headers=DISPATCHER, **overrides):
    """Create ``count`` engineers, stepping the clock ``step_seconds`` between
    creates so their created_at values are strictly ordered - the dispatch
    selector's created_at tie-break then reliably ranks them in creation
    order.  ``base_instant`` must be at or after the current logical time;
    with the clock still at its startup default the first create needs no
    step at all.  ``per_engineer`` is an optional list of per-index override
    dicts (for engineers that differ in skills or territory)."""
    engineers = []
    for index in range(count):
        if index > 0:
            set_clock(plus_seconds(base_instant, step_seconds * index))
        own = dict(overrides)
        if per_engineer is not None:
            own.update(per_engineer[index])
        engineers.append(create_engineer(headers=headers, **own))
    return engineers


def create_loaner_unit(headers=DISPATCHER, **overrides):
    response = api_client.create_loaner_unit(
        f.loaner_unit_payload(**overrides), headers=headers
    )
    return get_success_data(response)


def list_loaner_units(headers=DISPATCHER, **params):
    response = api_client.list_loaner_units(headers=headers, params=params or None)
    return get_success_data(response)


# --- Instruments (PRD section 3.3) ----------------------------------------------------------

def create_instrument(account, headers=ACCOUNT_MANAGER, **overrides):
    response = api_client.create_instrument(
        f.instrument_payload(_id_of(account), **overrides), headers=headers
    )
    return get_success_data(response)


def install_instrument(instrument, headers=DISPATCHER):
    response = api_client.install_instrument(_id_of(instrument), headers=headers)
    return get_success_data(response)


def decommission_instrument(instrument, headers=ACCOUNT_MANAGER):
    response = api_client.decommission_instrument(_id_of(instrument), headers=headers)
    return get_success_data(response)


def get_instrument(instrument, headers=ACCOUNT_MANAGER):
    response = api_client.get_instrument(_id_of(instrument), headers=headers)
    return get_success_data(response)


def create_installed_instrument(account, install_engineer=True, headers=DISPATCHER,
                                **overrides):
    """ORDERED -> INSTALLED: ensures an INSTALL-skilled ACTIVE engineer exists
    in the account's territory (unless install_engineer=False) then installs.
    Returns the installed instrument."""
    if install_engineer:
        ensure_install_engineer(account)
    instrument = create_instrument(account, **overrides)
    return install_instrument(instrument, headers=headers)


# --- Service contracts (PRD section 3.4) ------------------------------------------------------

def create_service_contract(instrument, headers=ACCOUNT_MANAGER, **overrides):
    response = api_client.create_service_contract(
        f.service_contract_payload(_id_of(instrument), **overrides), headers=headers
    )
    return get_success_data(response)


def get_service_contract(contract, headers=ACCOUNT_MANAGER):
    response = api_client.get_service_contract(_id_of(contract), headers=headers)
    return get_success_data(response)


def renew_service_contract(contract, expected_contract_version, headers=ACCOUNT_MANAGER):
    response = api_client.renew_service_contract(
        _id_of(contract),
        f.contract_renew_payload(expected_contract_version),
        headers=headers,
    )
    return get_success_data(response)


def cancel_service_contract(contract, headers=ACCOUNT_MANAGER):
    response = api_client.cancel_service_contract(_id_of(contract), headers=headers)
    return get_success_data(response)


def setup_instrument_with_contract(tier="GOLD", account_overrides=None,
                                   contract_overrides=None, instrument_overrides=None):
    """Account + INSTALL engineer + INSTALLED instrument + live contract of the
    given tier.  Returns (account, instrument, contract)."""
    account = create_account(**(account_overrides or {}))
    instrument = create_installed_instrument(account, **(instrument_overrides or {}))
    contract_overrides = dict(contract_overrides or {})
    contract_overrides["tier"] = tier
    contract = create_service_contract(instrument, **contract_overrides)
    return account, instrument, contract


# --- Enterprise agreements (PRD section 3.2) ------------------------------------------------------

def create_enterprise_agreement(account, headers=ACCOUNT_MANAGER, **overrides):
    response = api_client.create_enterprise_agreement(
        f.enterprise_agreement_payload(_id_of(account), **overrides), headers=headers
    )
    return get_success_data(response)


def get_enterprise_agreement(agreement, headers=ACCOUNT_MANAGER):
    response = api_client.get_enterprise_agreement(_id_of(agreement), headers=headers)
    return get_success_data(response)


def renew_enterprise_agreement(agreement, expected_agreement_version,
                               headers=ACCOUNT_MANAGER):
    response = api_client.renew_enterprise_agreement(
        _id_of(agreement),
        f.agreement_renew_payload(expected_agreement_version),
        headers=headers,
    )
    return get_success_data(response)


def terminate_enterprise_agreement(agreement, headers=ACCOUNT_MANAGER):
    response = api_client.terminate_enterprise_agreement(
        _id_of(agreement), headers=headers
    )
    return get_success_data(response)


# --- Orders (PRD section 3.6) -----------------------------------------------------------------

def procurement_headers(account):
    """The LabProcurement caller for this account - X-User-ID is its own id."""
    return make_lab_procurement_headers(_id_of(account))


def create_order(account, lines, headers=None):
    """Create a DRAFT order as the account's own LabProcurement buyer."""
    if headers is None:
        headers = procurement_headers(account)
    response = api_client.create_order(
        f.order_payload(_id_of(account), lines=lines), headers=headers
    )
    return get_success_data(response)


def submit_order(order, account, headers=None):
    """Submit a DRAFT order as the owning buyer; returns the submitted view
    (ALLOCATED or BACKORDERED) without asserting which."""
    if headers is None:
        headers = procurement_headers(account)
    response = api_client.submit_order(_id_of(order), headers=headers)
    return get_success_data(response)


def ship_order(order, headers=SUPPLY_OPS):
    response = api_client.ship_order(_id_of(order), headers=headers)
    return get_success_data(response)


def cancel_order(order, account, headers=None):
    if headers is None:
        headers = procurement_headers(account)
    response = api_client.cancel_order(_id_of(order), headers=headers)
    return get_success_data(response)


def get_order(order, headers=SUPPLY_OPS):
    response = api_client.get_order(_id_of(order), headers=headers)
    return get_success_data(response)


def create_allocated_order(account, lines):
    """DRAFT -> ALLOCATED.  The caller guarantees the gates pass: account
    ACTIVE and credit GOOD, licenses held, no surge on the lines' groups, and
    stock sufficient."""
    order = create_order(account, lines)
    submitted = submit_order(order, account)
    assert submitted["status"] == "ALLOCATED", (
        "Setup failed: expected ALLOCATED, got {0}".format(submitted["status"])
    )
    return submitted


def create_shipped_order(account, lines):
    """ALLOCATED -> SHIPPED; stamps shipped_at from the logical clock."""
    return ship_order(create_allocated_order(account, lines))


def deliver_order(order, headers=SUPPLY_OPS):
    """Drive a SHIPPED order to DELIVERED through the clock sweep: reads the
    order's shipped_at and shipping_class, sets the clock to exactly
    shipped_at + the class's transit days (the sweep threshold is inclusive),
    and returns the delivered view."""
    current = get_order(order, headers=headers)
    assert current["status"] == "SHIPPED", (
        "Setup failed: deliver_order needs SHIPPED, got {0}".format(current["status"])
    )
    deliver_at = plus_days(
        current["shipped_at"], TRANSIT_DAYS[current["shipping_class"]]
    )
    set_clock(deliver_at)
    delivered = get_order(order, headers=headers)
    assert delivered["status"] == "DELIVERED", (
        "Setup failed: sweep did not deliver the order (status {0})".format(
            delivered["status"]
        )
    )
    return delivered


def create_delivered_order(account, lines):
    """Full pipeline DRAFT -> ALLOCATED -> SHIPPED -> DELIVERED."""
    return deliver_order(create_shipped_order(account, lines))


# --- Trailing spend and credit standing (PRD sections 2.8, 3.1, 3.2) ----------------------------

def ship_order_total(account, total_cents, sku=None):
    """Ship a one-line STANDARD order whose frozen total is exactly
    ``total_cents`` (unit price == total, quantity 1, no handling fee, and -
    while the account holds no agreement - no discount).  Posts the invoice to
    the account's outstanding balance.  Returns (shipped_order, account)."""
    item_overrides = {"base_price_cents": total_cents, "stock_on_hand": 5}
    if sku is not None:
        item_overrides["sku"] = sku
    item = create_catalog_item(**item_overrides)
    order = create_shipped_order(account, [f.order_line(item["sku"], 1)])
    assert order["total_cents"] == total_cents, (
        "Setup failed: shipped total {0} != target {1} (an ACTIVE/EXPIRING "
        "agreement would have discounted it)".format(order["total_cents"], total_cents)
    )
    return order, get_account(account)


def seed_delivered_spend(account, amount_cents, sku=None):
    """Deliver a one-line order whose total is exactly ``amount_cents`` so the
    account's trailing_spend_cents reads exactly that figure afterwards.
    Advances the clock to the delivery instant (shipped_at + 3 days for the
    STANDARD class).  Returns the delivered order."""
    item_overrides = {"base_price_cents": amount_cents, "stock_on_hand": 5}
    if sku is not None:
        item_overrides["sku"] = sku
    item = create_catalog_item(**item_overrides)
    return create_delivered_order(account, [f.order_line(item["sku"], 1)])


def setup_account_with_trailing_spend(amount_cents, **account_overrides):
    """An account whose trailing_spend_cents is exactly ``amount_cents``:
    one STANDARD item priced at the amount, ordered, shipped and swept to
    DELIVERED.  Returns (account, delivered_order)."""
    account = create_account(**account_overrides)
    order = seed_delivered_spend(account, amount_cents)
    return account, order


def setup_account_with_agreement(trailing_spend_cents, committed_annual_spend_cents=100000,
                                 agreement_overrides=None, **account_overrides):
    """An account seeded with exactly ``trailing_spend_cents`` of delivered
    spend plus an ACTIVE enterprise agreement over the standard window.
    Pass 0 to skip the seed order.  Returns (account, agreement)."""
    account = create_account(**account_overrides)
    if trailing_spend_cents:
        seed_delivered_spend(account, trailing_spend_cents)
    overrides = dict(agreement_overrides or {})
    overrides["committed_annual_spend_cents"] = committed_annual_spend_cents
    agreement = create_enterprise_agreement(account, **overrides)
    return account, agreement


def push_account_to_credit_hold(account):
    """Ship a single order of CREDIT_LIMIT_CENTS + 1 so the balance crosses
    the line strictly and credit_status flips to HOLD (cancelling the
    account's DRAFT orders).  Returns the re-read account."""
    _, fresh = ship_order_total(account, CREDIT_LIMIT_CENTS + 1)
    assert fresh["credit_status"] == "HOLD", (
        "Setup failed: account did not flip to HOLD at {0}".format(
            fresh["outstanding_balance_cents"]
        )
    )
    return fresh


# --- Surge events (PRD section 3.7) --------------------------------------------------------------

def create_surge_event(headers=SUPPLY_OPS, **overrides):
    response = api_client.create_surge_event(
        f.surge_event_payload(**overrides), headers=headers
    )
    return get_success_data(response)


def resolve_surge_event(surge, headers=SUPPLY_OPS):
    response = api_client.resolve_surge_event(_id_of(surge), headers=headers)
    return get_success_data(response)


def create_backordered_order(account, lines):
    """Create + submit an order whose lines are surge-covered or
    stock-short; returns the submitted view with its frozen
    allocation_score.  Asserts the order did land in BACKORDERED."""
    submitted = submit_order(create_order(account, lines), account)
    assert submitted["status"] == "BACKORDERED", (
        "Setup failed: expected BACKORDERED, got {0}".format(submitted["status"])
    )
    return submitted


# --- Service requests (PRD section 3.5) ---------------------------------------------------------

def create_service_request(instrument, account=None, headers=None, **overrides):
    """OPEN a service request on an INSTALLED instrument.  Defaults to the
    owning account's LabProcurement buyer when ``account`` is given, else the
    AccountManager; pass ``headers`` to act as another allowed role.  For
    PREVENTIVE_MAINTENANCE pass ``scheduled_for``."""
    if headers is None:
        headers = procurement_headers(account) if account is not None else ACCOUNT_MANAGER
    response = api_client.create_service_request(
        f.service_request_payload(_id_of(instrument), **overrides), headers=headers
    )
    return get_success_data(response)


def get_service_request(request, headers=DISPATCHER):
    response = api_client.get_service_request(_id_of(request), headers=headers)
    return get_success_data(response)


def dispatch_request(request, headers=DISPATCHER):
    """OPEN -> DISPATCHED; the selector assigns the best eligible engineer."""
    response = api_client.dispatch_service_request(_id_of(request), headers=headers)
    return get_success_data(response)


def resolve_request(request, hours_on_site=1, parts_cost_cents=0, as_engineer=None,
                    headers=None):
    """DISPATCHED -> RESOLVED.  Pass ``as_engineer`` (an Engineer dict) to act
    as the assigned FieldEngineer; default is the ServiceDispatcher."""
    if headers is None:
        if as_engineer is not None:
            headers = make_field_engineer_headers(_id_of(as_engineer))
        else:
            headers = DISPATCHER
    response = api_client.resolve_service_request(
        _id_of(request),
        f.resolve_payload(hours_on_site, parts_cost_cents=parts_cost_cents),
        headers=headers,
    )
    return get_success_data(response)


def create_and_dispatch_request(instrument, account=None, engineer_skills=None,
                                headers=DISPATCHER, **overrides):
    """OPEN request + dispatch.  When ``engineer_skills`` is given, first
    ensures an ACTIVE engineer holding them exists in the account territory
    (required for the eligible set to be non-empty)."""
    if engineer_skills is not None:
        if account is None:
            raise ValueError("engineer territory needs the owning account")
        ensure_engineer(account, engineer_skills)
    request = create_service_request(instrument, account, **overrides)
    return dispatch_request(request, headers=headers)


def create_and_resolve_request(instrument, account=None, hours_on_site=1,
                               parts_cost_cents=0, engineer_skills=None, **overrides):
    """Full OPEN -> DISPATCHED -> RESOLVED walk; returns the resolved view."""
    dispatched = create_and_dispatch_request(
        instrument, account, engineer_skills=engineer_skills, **overrides
    )
    return resolve_request(
        dispatched, hours_on_site=hours_on_site, parts_cost_cents=parts_cost_cents
    )


def create_pm_request(instrument, account, scheduled_for, headers=None, **overrides):
    """A PREVENTIVE_MAINTENANCE request with the required scheduled_for."""
    overrides["request_type"] = "PREVENTIVE_MAINTENANCE"
    overrides["scheduled_for"] = scheduled_for
    overrides.setdefault("severity", "LOW")
    return create_service_request(instrument, account, headers=headers, **overrides)


def resolve_pm_visit(instrument, account, scheduled_for, hours_on_site=2,
                     parts_cost_cents=0):
    """Create + dispatch + resolve one preventive visit; returns the resolved
    view whose billable/covered split shows whether the visit was within the
    contract's PM quota."""
    request = create_pm_request(instrument, account, scheduled_for)
    dispatched = dispatch_request(request)
    return resolve_request(
        dispatched, hours_on_site=hours_on_site, parts_cost_cents=parts_cost_cents
    )


def setup_pm_quota_scenario(tier="GOLD", resolved_visits=4,
                            first_pm_date="2026-10-01T09:00:00Z", day_step=31,
                            hours_on_site=2):
    """Account + INSTALLED instrument + live contract of ``tier``, then
    ``resolved_visits`` preventive visits resolved in sequence, each scheduled
    ``day_step`` days after the previous (comfortably over the 30-day PM
    spacing floor, and earlier visits are RESOLVED so they never enter the
    OPEN/DISPATCHED gap check).  Returns a dict with account, instrument,
    contract, and the resolved request views in order."""
    account, instrument, contract = setup_instrument_with_contract(tier=tier)
    ensure_engineer(account, ["PM"])
    resolved = []
    for index in range(resolved_visits):
        scheduled = plus_days(first_pm_date, day_step * index)
        resolved.append(
            resolve_pm_visit(instrument, account, scheduled,
                             hours_on_site=hours_on_site)
        )
    return {
        "account": account,
        "instrument": instrument,
        "contract": contract,
        "resolved_requests": resolved,
    }


# --- Loaners (PRD section 3.5) ------------------------------------------------------------------

def reserve_loaner(request, headers=DISPATCHER):
    response = api_client.reserve_loaner(_id_of(request), headers=headers)
    return get_success_data(response)


def setup_loaner_scenario(tier="GOLD", severity="HIGH", unit_serials=("LN-1",),
                          unit_model="SEQ-5000", instrument_model="SEQ-5000"):
    """A loaner-eligible scene: account + INSTALLED instrument + live contract
    of ``tier``, a BREAK_FIX request of the given severity, and one AVAILABLE
    loaner unit per serial in ``unit_serials`` (all of ``unit_model``).
    Returns a dict with account, instrument, contract, request, units."""
    account, instrument, contract = setup_instrument_with_contract(
        tier=tier, instrument_overrides={"model": instrument_model}
    )
    units = [
        create_loaner_unit(model=unit_model, serial_number=serial)
        for serial in unit_serials
    ]
    request = create_service_request(
        instrument, account, request_type="BREAK_FIX", severity=severity
    )
    return {
        "account": account,
        "instrument": instrument,
        "contract": contract,
        "request": request,
        "units": units,
    }
