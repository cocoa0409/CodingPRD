"""Composite setup helpers for multi-step preconditions.

Every test starts against a freshly restarted server with an empty database, so
each helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use the lenient ``get_success_data()`` so a broken
precondition surfaces as a clear "Setup failed" error rather than a confusing
assertion failure.
"""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data

from .api_client import api_client
from .constants import (
    REPAIR_ROUND_ALLOWANCE,
)
from .test_users import TEST_USERS, make_engineer_headers

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
SALES_OPS = TEST_USERS["sales_engineer_ops_headers"]
SETUP_TECH = TEST_USERS["setup_technician_headers"]
SUPPORT_AGENT = TEST_USERS["support_agent_headers"]
SERVICE_DEPT = TEST_USERS["service_department_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

GUITAR_CODE = "SW-GTR-100"
AMP_CODE = "SW-AMP-050"
ACC_CODE = "SW-ACC-010"


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the service's logical clock to a supplied instant.

    The service renders every stamped instant with three fractional digits
    (PRD 2.10), so a caller that set the clock to ``...:00Z`` reads it back as
    ``...:00.000Z``.  Normalise the wire form once, here, so tests can compare a
    stamped field against the literal they configured.
    """
    resp = api_client.set_clock({"current_utc": to_iso8601}, PLATFORM_ADMIN)
    return get_success_data(resp)


def norm_instant(value):
    """Normalise an ISO 8601 instant to the service's three-digit wire form."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return "%s.%sZ" % (head, frac)


# ---------------------------------------------------------------------------
# primitive creators
# ---------------------------------------------------------------------------

def default_clock():
    set_clock("2026-09-01T00:00:00.000Z")


def create_engineer(full_name="Dana Riggs", email="dana.riggs@sweetwater.example",
                    region="MIDWEST", **extra) -> dict:
    payload = {"full_name": full_name, "email": email, "region": region}
    payload.update(extra)
    resp = api_client.create_engineer(payload, PLATFORM_ADMIN)
    return get_success_data(resp)


def create_customer(full_name="Riley Chance", email="riley.chance@example.com",
                    home_state="IN", **extra) -> dict:
    payload = {"full_name": full_name, "email": email, "home_state": home_state}
    payload.update(extra)
    resp = api_client.create_customer(payload, ANONYMOUS)
    return get_success_data(resp)


def create_product(product_code=GUITAR_CODE, display_name="Studio Guitar 100",
                   product_family="GUITAR", unit_price_cents=120000, **extra) -> dict:
    payload = {
        "product_code": product_code,
        "display_name": display_name,
        "product_family": product_family,
        "unit_price_cents": unit_price_cents,
    }
    payload.update(extra)
    resp = api_client.create_product(payload, PLATFORM_ADMIN)
    return get_success_data(resp)


def create_guitar_product(unit_price_cents=120000, product_code=GUITAR_CODE) -> dict:
    return create_product(product_code=product_code, display_name="Studio Guitar 100",
                          product_family="GUITAR", unit_price_cents=unit_price_cents)


# ``create_amp_product`` shares ``AMP_CODE`` with the default catalogue, so its
# display name is derived from the code; callers that need a distinct product
# pass a distinct code.
def create_amp_product(unit_price_cents=90000, product_code=AMP_CODE,
                       required_family="GUITAR") -> dict:
    return create_product(product_code=product_code, display_name="Combo Amp 50",
                          product_family="AMPLIFIER", unit_price_cents=unit_price_cents,
                          required_family=required_family)


def create_service_center(name="Indianapolis Bench", region="MIDWEST", capacity_slots=2,
                          accepted_families=None) -> dict:
    payload = {
        "name": name,
        "region": region,
        "capacity_slots": capacity_slots,
        "accepted_families": accepted_families or ["GUITAR", "AMPLIFIER"],
    }
    resp = api_client.create_service_center(payload, PLATFORM_ADMIN)
    return get_success_data(resp)


def customer_version(customer_id: str) -> int:
    data = get_success_data(api_client.get_customer(customer_id, SALES_OPS))
    return data["version"]


def quote_version(quote_id: str, headers=None) -> int:
    data = get_success_data(api_client.get_quote(quote_id, headers or SALES_OPS))
    return data["version"]


# ---------------------------------------------------------------------------
# assignment flow
# ---------------------------------------------------------------------------

def create_assignment(customer, engineer, reason_code="NEW_ACCOUNT",
                      expected_customer_version=None, headers=None, **extra) -> dict:
    version = expected_customer_version
    if version is None:
        version = customer_version(customer["id"])
    payload = {
        "customer_id": customer["id"],
        "engineer_id": engineer["id"],
        "reason_code": reason_code,
        "expected_customer_version": version,
    }
    payload.update(extra)
    resp = api_client.create_assignment(payload, headers or SALES_OPS)
    return get_success_data(resp)


def accept_assignment(assignment, engineer=None) -> dict:
    """Accept a PENDING_ACCEPT assignment as its own engineer (ownership gated)."""
    user_id = assignment["engineer_id"] if engineer is None else engineer["id"]
    resp = api_client.accept_assignment(assignment["id"], make_engineer_headers(user_id))
    return get_success_data(resp)


def decline_assignment(assignment, engineer=None) -> dict:
    user_id = assignment["engineer_id"] if engineer is None else engineer["id"]
    resp = api_client.decline_assignment(assignment["id"], make_engineer_headers(user_id))
    return get_success_data(resp)


def end_assignment(assignment, headers=None) -> dict:
    resp = api_client.end_assignment(assignment["id"], headers or SALES_OPS)
    return get_success_data(resp)


def reopen_assignment(assignment, headers=None) -> dict:
    resp = api_client.reopen_assignment(assignment["id"], headers or SALES_OPS)
    return get_success_data(resp)


def list_assignments_for_engineer(engineer_id: str, headers=None):
    resp = api_client.list_assignments(headers or SALES_OPS, {"engineer_id": engineer_id})
    payload = resp.json()["data"]
    return payload if isinstance(payload, list) else [payload]


def count_active_assignments(engineer_id: str) -> int:
    return len([row for row in list_assignments_for_engineer(engineer_id)
                if row["status"] == "ACTIVE"])


def list_assignments_for(customer_id: str, headers=None):
    resp = api_client.list_assignments(headers or SALES_OPS, {"customer_id": customer_id})
    payload = resp.json()["data"]
    return payload if isinstance(payload, list) else [payload]


# ---------------------------------------------------------------------------
# quoting flow
# ---------------------------------------------------------------------------

def create_quote(customer, engineer, package_type="SYSTEM_PACKAGE") -> dict:
    payload = {
        "customer_id": customer["id"],
        "engineer_id": engineer["id"],
        "package_type": package_type,
    }
    resp = api_client.create_quote(payload, make_engineer_headers(engineer["id"]))
    return get_success_data(resp)


def add_quote_line(quote, engineer, product_code=GUITAR_CODE, **extra) -> dict:
    payload = {"product_code": product_code}
    payload.update(extra)
    resp = api_client.add_quote_line(quote["id"], payload,
                                     make_engineer_headers(engineer["id"]))
    return get_success_data(resp)


def submit_quote(quote, engineer) -> dict:
    resp = api_client.submit_quote(quote["id"], make_engineer_headers(engineer["id"]))
    return get_success_data(resp)


def reserve_quote(quote, engineer, expected_quote_version=None) -> dict:
    version = expected_quote_version
    if version is None:
        version = quote_version(quote["id"])
    resp = api_client.reserve_quote(quote["id"], {"expected_quote_version": version},
                                    make_engineer_headers(engineer["id"]))
    return get_success_data(resp)


def reject_quote(quote, headers=None) -> dict:
    resp = api_client.reject_quote(quote["id"], headers or SALES_OPS)
    return get_success_data(resp)


def amend_quote(quote, engineer, expected_quote_version=None) -> dict:
    payload = {}
    if expected_quote_version is not None:
        payload["expected_quote_version"] = expected_quote_version
    resp = api_client.amend_quote(quote["id"], payload,
                                  make_engineer_headers(engineer["id"]))
    return get_success_data(resp)


def cancel_quote(quote, engineer=None, headers=None) -> dict:
    hdrs = headers or make_engineer_headers(engineer["id"])
    resp = api_client.cancel_quote(quote["id"], hdrs)
    return get_success_data(resp)


def reopen_quote(quote, engineer) -> dict:
    resp = api_client.reopen_quote(quote["id"], make_engineer_headers(engineer["id"]))
    return get_success_data(resp)


def list_quote_lines_for(quote_id: str, headers=None):
    resp = api_client.list_quote_lines_for_quote(quote_id, headers or SALES_OPS)
    payload = resp.json()["data"]
    return payload if isinstance(payload, list) else [payload]


def quote_summary(quote_id: str, headers=None) -> dict:
    resp = api_client.get_quote_summary(quote_id, headers or SALES_OPS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# instrument unit flow
# ---------------------------------------------------------------------------

def create_instrument_unit(quote_line, serial_number="SN-GTR-5521",
                           model_code=GUITAR_CODE) -> dict:
    payload = {
        "quote_line_id": quote_line["id"],
        "serial_number": serial_number,
        "model_code": model_code,
    }
    resp = api_client.create_instrument_unit(payload, SETUP_TECH)
    return get_success_data(resp)


def start_setup(unit) -> dict:
    resp = api_client.start_setup(unit["id"], SETUP_TECH)
    return get_success_data(resp)


def complete_setup(unit, action_height_mm=1.50, relief_mm=0.10,
                   intonation_offset_cents=2) -> dict:
    payload = {
        "action_height_mm": action_height_mm,
        "relief_mm": relief_mm,
        "intonation_offset_cents": intonation_offset_cents,
    }
    resp = api_client.complete_setup(unit["id"], payload, SETUP_TECH)
    return get_success_data(resp)


def record_inspection(unit) -> dict:
    resp = api_client.record_inspection(unit["id"], SETUP_TECH)
    return get_success_data(resp)


def restart_setup(unit) -> dict:
    resp = api_client.restart_setup(unit["id"], SETUP_TECH)
    return get_success_data(resp)


def ship_instrument_unit(unit, headers=None) -> dict:
    resp = api_client.ship_instrument_unit(unit["id"], headers or SETUP_TECH)
    return get_success_data(resp)


def walk_unit_to_setup_complete(unit, **measurements) -> dict:
    start_setup(unit)
    return complete_setup(unit, **measurements)


def walk_unit_to_inspected(unit, **measurements) -> dict:
    walk_unit_to_setup_complete(unit, **measurements)
    return record_inspection(unit)


def walk_unit_to_shipped(unit, **measurements) -> dict:
    walk_unit_to_inspected(unit, **measurements)
    return ship_instrument_unit(unit)


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_instrument_unit(unit_id, SETUP_TECH))


# ---------------------------------------------------------------------------
# warranty flow
# ---------------------------------------------------------------------------

def create_warranty_plan(customer, unit, term_months=None) -> dict:
    payload = {"customer_id": customer["id"], "instrument_unit_id": unit["id"]}
    if term_months is not None:
        payload["term_months"] = term_months
    resp = api_client.create_warranty_plan(payload, SALES_OPS)
    return get_success_data(resp)


def activate_warranty_plan(plan, starts_on) -> dict:
    resp = api_client.activate_warranty_plan(plan["id"], {"starts_on": starts_on}, SALES_OPS)
    return get_success_data(resp)


def void_warranty_plan(plan, headers=None) -> dict:
    resp = api_client.void_warranty_plan(plan["id"], headers or PLATFORM_ADMIN)
    return get_success_data(resp)


def create_warranty_claim(plan, service_center, reported_fault="Fret buzz on the low E") -> dict:
    payload = {
        "warranty_plan_id": plan["id"],
        "reported_fault": reported_fault,
        "service_center_id": service_center["id"],
    }
    resp = api_client.create_warranty_claim(payload, SUPPORT_AGENT)
    return get_success_data(resp)


def route_claim(claim, headers=None) -> dict:
    resp = api_client.route_warranty_claim(claim["id"], headers or SUPPORT_AGENT)
    return get_success_data(resp)


def reopen_claim(claim) -> dict:
    resp = api_client.reopen_warranty_claim(claim["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def close_claim(claim) -> dict:
    resp = api_client.close_warranty_claim(claim["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_warranty_plan(plan_id, SUPPORT_AGENT))


# ---------------------------------------------------------------------------
# support ticket flow
# ---------------------------------------------------------------------------

def create_support_ticket(customer, service_center=None, subject="Amp hum at high gain",
                          channel="PHONE") -> dict:
    payload = {"customer_id": customer["id"], "subject": subject, "channel": channel}
    if service_center is not None:
        payload["service_center_id"] = service_center["id"]
    resp = api_client.create_support_ticket(payload, SUPPORT_AGENT)
    return get_success_data(resp)


def triage_ticket(ticket) -> dict:
    resp = api_client.triage_support_ticket(ticket["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def escalate_ticket(ticket) -> dict:
    resp = api_client.escalate_support_ticket(ticket["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def de_escalate_ticket(ticket) -> dict:
    resp = api_client.de_escalate_support_ticket(ticket["id"], SERVICE_DEPT)
    return get_success_data(resp)


def resolve_ticket(ticket, headers=None) -> dict:
    resp = api_client.resolve_support_ticket(ticket["id"], headers or SUPPORT_AGENT)
    return get_success_data(resp)


def get_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_support_ticket(ticket_id, SUPPORT_AGENT))


def get_support_ticket(ticket_id: str) -> dict:
    """Alias for get_ticket()."""
    return get_ticket(ticket_id)


def ledger_rows_for_ticket(ticket_id: str):
    resp = api_client.list_escalation_ledger(SUPPORT_AGENT, {"support_ticket_id": ticket_id})
    payload = resp.json()["data"]
    return payload if isinstance(payload, list) else [payload]


# ---------------------------------------------------------------------------
# backorder flow
# ---------------------------------------------------------------------------

def create_backorder(quote_line, engineer, units_requested=None,
                     preorder_open_at=None, headers=None, **extra) -> dict:
    payload = {"quote_line_id": quote_line["id"], "engineer_id": engineer["id"]}
    if units_requested is not None:
        payload["units_requested"] = units_requested
    if preorder_open_at is not None:
        payload["preorder_open_at"] = preorder_open_at
    payload.update(extra)
    resp = api_client.create_backorder(payload, headers or SALES_OPS)
    return get_success_data(resp)


def start_sweep(backorder, pool_units=1) -> dict:
    resp = api_client.start_sweep(backorder["id"], {"pool_units": pool_units}, SALES_OPS)
    return get_success_data(resp)


def finalize_allocation(backorder, pool_units=1) -> dict:
    resp = api_client.finalize_allocation(backorder["id"], {"pool_units": pool_units}, SALES_OPS)
    return get_success_data(resp)


def reset_sweep(backorder) -> dict:
    resp = api_client.reset_sweep(backorder["id"], SALES_OPS)
    return get_success_data(resp)


def get_backorder(backorder_id: str) -> dict:
    return get_success_data(api_client.get_backorder(backorder_id, SALES_OPS))


def backorders_for(params: dict, headers=None):
    resp = api_client.list_backorders(headers or SALES_OPS, params)
    payload = resp.json()["data"]
    return payload if isinstance(payload, list) else [payload]


# ---------------------------------------------------------------------------
# gear exchange flow
# ---------------------------------------------------------------------------

def create_gear_exchange(quote_line, customer, reason="TONE_MISMATCH") -> dict:
    payload = {
        "quote_line_id": quote_line["id"],
        "customer_id": customer["id"],
        "reason": reason,
    }
    resp = api_client.create_gear_exchange(payload, SUPPORT_AGENT)
    return get_success_data(resp)


def start_trial(exchange) -> dict:
    resp = api_client.start_trial(exchange["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def request_return(exchange) -> dict:
    resp = api_client.request_return(exchange["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def complete_exchange(exchange) -> dict:
    resp = api_client.complete_exchange(exchange["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def cancel_exchange(exchange) -> dict:
    resp = api_client.cancel_gear_exchange(exchange["id"], SUPPORT_AGENT)
    return get_success_data(resp)


def get_exchange(exchange_id: str) -> dict:
    return get_success_data(api_client.get_gear_exchange(exchange_id, SUPPORT_AGENT))


# ---------------------------------------------------------------------------
# certification flow
# ---------------------------------------------------------------------------

def create_certification_attempt(engineer, product_family="GUITAR", score_pct=85) -> dict:
    payload = {
        "engineer_id": engineer["id"],
        "product_family": product_family,
        "score_pct": score_pct,
    }
    resp = api_client.create_certification_attempt(payload, SALES_OPS)
    return get_success_data(resp)


def grade_certification_attempt(attempt) -> dict:
    resp = api_client.grade_certification_attempt(attempt["id"], SALES_OPS)
    return get_success_data(resp)


def reschedule_certification_attempt(attempt) -> dict:
    resp = api_client.reschedule_certification_attempt(attempt["id"], SALES_OPS)
    return get_success_data(resp)


def get_engineer(engineer_id: str) -> dict:
    return get_success_data(api_client.get_engineer(engineer_id, SALES_OPS))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, SALES_OPS))


# ===========================================================================
# Composite setup helpers
# ===========================================================================

def setup_catalog(guitar_price_cents=120000, amp_price_cents=90000,
                  with_amp=True, amp_required_family="GUITAR",
                  guitar_code=GUITAR_CODE, amp_code=AMP_CODE) -> dict:
    """Register the catalogue products most setups need. Returns {code: product}.

    Catalogue codes are unique across products (PRD 3.10), so re-registering a
    code this world already carries is skipped rather than attempted.
    """
    catalog = {}
    parts = [("guitar", create_guitar_product, guitar_price_cents, guitar_code)]
    if with_amp:
        parts.append(("amp", create_amp_product, amp_price_cents, amp_code))
    for key, maker, price, code in parts:
        existing = core_lookup_product(code)
        if existing is not None:
            catalog[key] = existing
            continue
        if key == "amp":
            catalog[key] = maker(price, code, amp_required_family)
        else:
            catalog[key] = maker(price, code)
    return catalog


def core_lookup_product(product_code):
    """Read a catalogue product by code, or None when it is not registered."""
    resp = api_client.list_products(PLATFORM_ADMIN, {"limit": 100})
    payload = resp.json().get("data")
    rows = payload if isinstance(payload, list) else [payload]
    for row in rows:
        if row and row.get("product_code") == product_code:
            return row
    return None


def setup_book_world(engineer_name="Dana Riggs", engineer_email="dana.riggs@sweetwater.example",
                     region="MIDWEST", engineer_extra=None, customer_name="Riley Chance",
                     customer_email="riley.chance@example.com", home_state="IN",
                     customer_extra=None, clock="2026-09-01T00:00:00.000Z",
                     with_catalog=True, guitar_price_cents=120000,
                     amp_price_cents=90000, with_amp=True, accept=True,
                     reason_code="NEW_ACCOUNT") -> dict:
    """The canonical preamble: clock, one engineer, one customer, an ACTIVE
    assignment, and the catalogue. Most post-sale fixtures extend this."""
    set_clock(clock)
    engineer = create_engineer(engineer_name, engineer_email, region,
                               **(engineer_extra or {}))
    customer = create_customer(customer_name, customer_email, home_state,
                               **(customer_extra or {}))
    assignment = create_assignment(customer, engineer, reason_code=reason_code)
    if accept:
        assignment = accept_assignment(assignment)
    catalog = {}
    if with_catalog:
        catalog = setup_catalog(guitar_price_cents, amp_price_cents, with_amp)
    return {
        "engineer": engineer,
        "customer": customer,
        "assignment": assignment,
        "assignment_id": assignment["id"],
        "engineer_id": engineer["id"],
        "customer_id": customer["id"],
        "catalog": catalog,
        "clock": clock,
    }


def setup_reserved_quote(world, package_type="SYSTEM_PACKAGE", line_specs=None,
                         clock=None) -> dict:
    """Add a fully RESERVED quote to an existing book world.

    ``line_specs`` defaults to a guitar anchor plus a dependent amp line. Each
    spec is a dict of ``add_quote_line`` overrides.
    """
    engineer = world["engineer"]
    customer = world["customer"]
    if line_specs is None:
        line_specs = [
            {"product_code": GUITAR_CODE, "quantity": 1, "is_anchor": True},
            {"product_code": AMP_CODE, "quantity": 1, "requires_line_id": "__anchor__"},
        ]
    quote = create_quote(customer, engineer, package_type)
    lines = []
    for spec in line_specs:
        spec = dict(spec)
        if spec.get("requires_line_id") == "__anchor__":
            spec["requires_line_id"] = lines[0]["id"]
        lines.append(add_quote_line(quote, engineer, **spec))
    submitted = submit_quote(quote, engineer)
    reserved = reserve_quote(submitted, engineer)
    world.update({
        "quote": reserved,
        "quote_id": reserved["id"],
        "lines": lines,
        "guitar_line": lines[0],
        "amp_line": lines[1] if len(lines) > 1 else None,
    })
    return world


def setup_submitted_quote(world, package_type="SYSTEM_PACKAGE", line_specs=None) -> dict:
    """Same as setup_reserved_quote but stops at SUBMITTED."""
    engineer = world["engineer"]
    customer = world["customer"]
    if line_specs is None:
        line_specs = [
            {"product_code": GUITAR_CODE, "quantity": 1, "is_anchor": True},
            {"product_code": AMP_CODE, "quantity": 1, "requires_line_id": "__anchor__"},
        ]
    quote = create_quote(customer, engineer, package_type)
    lines = []
    for spec in line_specs:
        spec = dict(spec)
        if spec.get("requires_line_id") == "__anchor__":
            spec["requires_line_id"] = lines[0]["id"]
        lines.append(add_quote_line(quote, engineer, **spec))
    submitted = submit_quote(quote, engineer)
    world.update({
        "quote": submitted,
        "quote_id": submitted["id"],
        "lines": lines,
        "guitar_line": lines[0],
        "amp_line": lines[1] if len(lines) > 1 else None,
    })
    return world


def setup_draft_quote(world, package_type="SYSTEM_PACKAGE") -> dict:
    """A DRAFT quote carrying a single guitar anchor line."""
    engineer = world["engineer"]
    customer = world["customer"]
    quote = create_quote(customer, engineer, package_type)
    line = add_quote_line(quote, engineer, product_code=GUITAR_CODE, quantity=1,
                          is_anchor=True)
    world.update({"quote": quote, "quote_id": quote["id"], "lines": [line],
                  "guitar_line": line})
    return world


def setup_instrument_unit(world, quote=None, quote_line=None, serial_number="SN-GTR-5521",
                          model_code=GUITAR_CODE) -> dict:
    """Register a serialized unit and return it (still PENDING_SETUP)."""
    line = quote_line or world.get("guitar_line")
    unit = create_instrument_unit(line, serial_number, model_code)
    world["unit"] = unit
    world["unit_id"] = unit["id"]
    return unit


def setup_shipped_instrument(world, quote=None, quote_line=None,
                             serial_number="SN-GTR-5521", model_code=GUITAR_CODE,
                             action_height_mm=1.50, relief_mm=0.10,
                             intonation_offset_cents=2) -> dict:
    """Register a unit and walk it all the way to SHIPPED."""
    unit = setup_instrument_unit(world, quote, quote_line, serial_number, model_code)
    shipped = walk_unit_to_shipped(unit, action_height_mm=action_height_mm,
                                   relief_mm=relief_mm,
                                   intonation_offset_cents=intonation_offset_cents)
    world["unit"] = shipped
    return shipped


def setup_inspected_instrument(world, quote=None, quote_line=None, serial_number="SN-GTR-5521",
                               action_height_mm=1.50, relief_mm=0.10,
                               intonation_offset_cents=2) -> dict:
    """Register a unit and walk it to INSPECTED (not shipped)."""
    unit = setup_instrument_unit(world, quote, quote_line, serial_number)
    inspected = walk_unit_to_inspected(unit, action_height_mm=action_height_mm,
                                       relief_mm=relief_mm,
                                       intonation_offset_cents=intonation_offset_cents)
    world["unit"] = inspected
    return inspected


def setup_active_warranty_plan(world, unit=None, term_months=None, starts_on=None) -> dict:
    """Register and activate a plan covering an already-shipped instrument."""
    unit = unit or world["unit"]
    plan = create_warranty_plan(world["customer"], unit, term_months)
    plan = activate_warranty_plan(plan, starts_on or world.get("clock")
                                  or "2026-09-01T00:00:00.000Z")
    world["plan"] = plan
    world["plan_id"] = plan["id"]
    return plan


def setup_shipped_book_with_active_plan(term_months=None, starts_on="2026-09-01T00:00:00.000Z",
                                        clock="2026-09-01T00:00:00.000Z", **world_kwargs) -> dict:
    """The post-sale preamble: book world + reserved quote + shipped unit +
    ACTIVE warranty plan. Returns the enriched world dict."""
    world = setup_book_world(clock=clock, **world_kwargs)
    setup_reserved_quote(world)
    setup_shipped_instrument(world)
    setup_active_warranty_plan(world, term_months=term_months, starts_on=starts_on)
    return world


def setup_center_and_routed_claim(world, capacity_slots=2,
                                  accepted_families=None,
                                  report="Fret buzz on the low E") -> dict:
    """Register a service center and open a claim against the world's plan."""
    center = create_service_center(capacity_slots=capacity_slots,
                                   accepted_families=accepted_families)
    claim = create_warranty_claim(world["plan"], center, report)
    world["center"] = center
    world["center_id"] = center["id"]
    world["claim"] = claim
    return world


def setup_center_with_consumed_repair_rounds(world, rounds=REPAIR_ROUND_ALLOWANCE,
                                             capacity_slots=2) -> dict:
    """Open, route and close `rounds` claims so the plan's allowance is spent."""
    center = create_service_center(capacity_slots=capacity_slots)
    world["center"] = center
    world["center_id"] = center["id"]
    claims = []
    for index in range(rounds):
        claim = create_warranty_claim(world["plan"], center, f"Round {index + 1} fault")
        route_claim(claim)
        close_claim(claim)
        claims.append(claim)
    world["claims"] = claims
    world["plan"] = get_plan(world["plan"]["id"])
    return world


def setup_escalated_ticket(world, center=None) -> dict:
    """Open, triage and escalate a ticket so it sits in ESCALATED."""
    center = center or world.get("center") or create_service_center()
    world["center"] = center
    ticket = create_support_ticket(world["customer"], center)
    triage_ticket(ticket)
    ticket = escalate_ticket(ticket)
    world["ticket"] = ticket
    world["ticket_id"] = ticket["id"]
    return world