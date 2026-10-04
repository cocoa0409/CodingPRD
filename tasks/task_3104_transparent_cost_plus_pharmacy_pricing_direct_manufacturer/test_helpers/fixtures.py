"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only the public endpoints. Setup calls use
the lenient `get_success_data()` validator so a broken prerequisite surfaces
as a clear "Setup step failed" error rather than a confusing assertion.

Returns are plain dicts of resource payloads keyed by role, so tests can pick
out exactly the handles they need.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, FAR_FUTURE
from .factories import (
    create_drug_payload,
    create_intake_request_payload,
    create_license_payload,
    create_manufacturer_payload,
    create_order_payload,
    create_patient_payload,
    create_pharmacy_payload,
    create_prescription_payload,
    create_prescriber_payload,
    create_price_payload,
    create_substantiation_payload,
)
from .test_users import TEST_USERS

OPS = TEST_USERS["pharmacy_ops_headers"]
PHARMACIST = TEST_USERS["pharmacist_headers"]


# ═══════════════════════════════════════════════════════
# Tier 0 — primitives
# ═══════════════════════════════════════════════════════

def reset_clock(instant=CLOCK_START):
    """Set the logical clock to `instant`, returning the stamped value."""
    return get_success_data(api_client.set_clock(instant, OPS))


def create_manufacturer(name="Bexley Generics"):
    return get_success_data(
        api_client.create_manufacturer(create_manufacturer_payload(manufacturer_name=name), OPS)
    )


def set_manufacturer_state(manufacturer_id, to_status):
    """Suspend or reactivate a manufacturer (PRD §3.1)."""
    return get_success_data(
        api_client.set_manufacturer_state(manufacturer_id, to_status, OPS)
    )


def create_drug(**overrides):
    return get_success_data(api_client.create_drug(create_drug_payload(**overrides), OPS))


def create_price_row(drug_id, manufacturer_id, **overrides):
    """Register a negotiated price row. Born PROPOSED x UNDER_REVIEW, so it is
    outside the sourcing pool until it is activated and moved to SOURCED."""
    return get_success_data(
        api_client.create_price(create_price_payload(drug_id, manufacturer_id, **overrides), OPS)
    )


def activate_and_source_price(price_id):
    """Move a row to ACTIVE on the price dimension and SOURCED on the sourcing
    dimension, making it a member of the sourcing pool."""
    get_success_data(api_client.activate_price(price_id, OPS))
    return get_success_data(api_client.move_price_sourcing(price_id, "SOURCED", OPS))


def create_sourced_price(drug_id, manufacturer_id, **overrides):
    row = create_price_row(drug_id, manufacturer_id, **overrides)
    return activate_and_source_price(row["id"])



def create_pharmacy(**overrides):
    return get_success_data(api_client.create_pharmacy(create_pharmacy_payload(**overrides), OPS))


def create_license_pending(pharmacy_id, **overrides):
    """File a licence, which is born PENDING."""
    return get_success_data(
        api_client.file_license(pharmacy_id, create_license_payload(**overrides), OPS)
    )


def create_license_pending_response(pharmacy_id, **overrides):
    """Same as create_license_pending but returns the raw Response, for tests
    asserting the refused-filing error."""
    return api_client.file_license(pharmacy_id, create_license_payload(**overrides), OPS)


def verify_license(pharmacy_id, license_id):
    return get_success_data(api_client.verify_license(pharmacy_id, license_id, OPS))


def create_active_license(pharmacy_id, state_code="CA", expiry_at=FAR_FUTURE):
    """File a licence and drive it to ACTIVE (verified_at is stamped)."""
    lic = create_license_pending(
        pharmacy_id, state_code=state_code, expiry_at=expiry_at,
        license_number=f"{state_code}-MP-1001",
    )
    return verify_license(pharmacy_id, lic["id"])


def create_patient(**overrides):
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), OPS))


def create_prescriber(**overrides):
    return get_success_data(
        api_client.create_prescriber(create_prescriber_payload(**overrides), OPS)
    )


def create_prescription(patient_id, prescriber_id, drug_id, **overrides):
    return get_success_data(
        api_client.create_prescription(
            create_prescription_payload(patient_id, prescriber_id, drug_id, **overrides), OPS
        )
    )


def submit_intake(prescription_id, packaged_quantity=100):
    """Route the prescription into intake; born SUBMITTED."""
    return get_success_data(
        api_client.create_intake_request(
            prescription_id, packaged_quantity, OPS
        )
    )


def review_intake(request_id):
    return get_success_data(api_client.review_intake_request(request_id, PHARMACIST))


def accept_intake(request_id):
    """Accept an intake request. The prescription becomes ACTIVE and its first
    claim is created; the claim is looked up through the prescription's claim
    list so the handle is the persisted Claim row."""
    get_success_data(api_client.accept_intake_request(request_id, PHARMACIST))
    request = get_success_data(api_client.get_intake_request(request_id, OPS))
    claims = _payload_list(
        api_client.list_claims_of_prescription(request["prescription_id"], OPS)
    )
    claim = claims[-1] if claims else None
    return request, claim


def pay_order(order_id):
    return get_success_data(api_client.pay_order(order_id, OPS))


def fulfill_order(order_id, expected_order_version=None):
    if expected_order_version is None:
        expected_order_version = get_success_data(api_client.get_order(order_id, OPS))["version"]
    return get_success_data(
        api_client.fulfill_order(order_id, expected_order_version, OPS)
    )


def ship_order(order_id):
    return get_success_data(api_client.ship_order(order_id, OPS))


def deliver_order(order_id):
    return get_success_data(api_client.deliver_order(order_id, OPS))


# ─── small response helpers ──────────────────────────

def _payload_list(response):
    """Return the array payload of a list endpoint.

    For an array response the envelope's `data` is the list itself; this
    helper tolerates both a bare list and a wrapped dict so callers never
    have to care which shape the envelope used.
    """
    data = get_success_data(response)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    return data


def list_payload(response):
    """Return the array payload of a list endpoint, tolerating both a bare
    list and a `{"data": [...]}` wrapper in the envelope."""
    return _payload_list(response)


def list_claims_of(prescription_id):
    return _payload_list(api_client.list_claims_of_prescription(prescription_id, OPS))


def list_shipments_of(order_id):
    return _payload_list(api_client.list_shipments_of_order(order_id, OPS))


def list_comparisons_of(order_id):
    return _payload_list(api_client.list_comparisons_of_order(order_id, OPS))


def list_intake_requests_of(prescription_id):
    return _payload_list(api_client.list_intake_requests_of_prescription(prescription_id, OPS))


# ═══════════════════════════════════════════════════════
# Tier 1 — state progression
# ═══════════════════════════════════════════════════════

def setup_drug_with_pool(rows=None, drug_overrides=None, manufacturer_name="Bexley Generics",
                         formulary=False, demand=0, patient=None, prescriber=None):
    """Create a manufacturer, a drug, and one or more ACTIVE+SOURCED price rows.

    `rows` is a list of per-row overrides (unit_cost_cents / available_units /
    reliability_tier / packaging). Returns a dict of handles.

    When `demand` > 0 the demand is driven by accepted intake requests against
    the drug (each of packaged_quantity 50), which also creates the patient and
    prescriber if they were not supplied.
    """
    if rows is None:
        rows = [{}]
    manufacturer = create_manufacturer(manufacturer_name)
    drug = create_drug(**(drug_overrides or {}))
    prices = [create_sourced_price(drug["id"], manufacturer["id"], **row) for row in rows]

    if demand > 0:
        patient = patient or create_patient()
        prescriber = prescriber or create_prescriber()

    ctx = {
        "manufacturer": manufacturer,
        "drug": drug,
        "prices": prices,
        "primary_price": prices[0],
        "patient": patient,
        "prescriber": prescriber,
        "prescriptions": [],
        "requests": [],
    }

    if demand > 0:
        ctx["prescriptions"], ctx["requests"] = add_accepted_demand(
            drug["id"], patient["id"], prescriber["id"], demand
        )

    if formulary:
        ctx["drug"] = get_success_data(api_client.expand_formulary(drug["id"], OPS))

    return ctx


def add_accepted_demand(drug_id, patient_id, prescriber_id, total_units, chunk=50,
                        ship_state_code="CA"):
    """Drive `total_units` of trailing demand for a drug by creating
    prescriptions and driving each intake request all the way to ACCEPTED.

    Returns (prescriptions, requests).
    """
    prescriptions, requests = [], []
    remaining = total_units
    while remaining > 0:
        quantity = min(chunk, remaining)
        rx = create_prescription(patient_id, prescriber_id, drug_id,
                                 ship_state_code=ship_state_code,
                                 total_refills_authorized=1)
        rq = submit_intake(rx["id"], packaged_quantity=quantity)
        review_intake(rq["id"])
        request, _claim = accept_intake(rq["id"])
        prescriptions.append(rx)
        requests.append(request)
        remaining -= quantity
    return prescriptions, requests


def setup_active_prescription(patient_id, prescriber_id, drug_id,
                              packaged_quantity=100, total_refills_authorized=1,
                              ship_state_code="CA", review=True, accept=True):
    """Prescription -> intake request -> (optionally) review -> (optionally) accept.

    Returns (prescription, request, claim). `claim` is None unless accepted.
    """
    rx = create_prescription(patient_id, prescriber_id, drug_id,
                             ship_state_code=ship_state_code,
                             total_refills_authorized=total_refills_authorized)
    rq = submit_intake(rx["id"], packaged_quantity=packaged_quantity)
    claim = None
    if review:
        review_intake(rq["id"])
    if accept:
        rq, claim = accept_intake(rq["id"])
    return get_success_data(api_client.get_prescription(rx["id"], OPS)), rq, claim


# ═══════════════════════════════════════════════════════
# Tier 2 — entity hierarchy
# ═══════════════════════════════════════════════════════

def setup_licensed_pharmacy(state_code="CA", domicile_state_code="TX",
                            shipping_enabled=True, license_expiry=FAR_FUTURE,
                            verify=True):
    """A pharmacy plus a licence for `state_code`.

    Returns (pharmacy, license). The licence is ACTIVE unless verify=False, in
    which case it is returned still PENDING.
    """
    pharmacy = create_pharmacy(domicile_state_code=domicile_state_code,
                               shipping_enabled=shipping_enabled)
    license_row = create_license_pending(
        pharmacy["id"], state_code=state_code, expiry_at=license_expiry,
        license_number=f"{state_code}-MP-1001",
    )
    if verify:
        license_row = verify_license(pharmacy["id"], license_row["id"])
    return pharmacy, license_row


def setup_dispensing_context(drug_id, quantity=30, packaged_quantity=100,
                             total_refills_authorized=1, ship_state_code="CA",
                             licence_state=None):
    """Patient + prescriber + ACTIVE prescription with an ACCEPTED request +
    a licensed pharmacy. Returns a dict of handles including the first claim.

    `licence_state` defaults to `ship_state_code`; pass a different value to
    deliberately leave the destination state uncovered.
    """
    patient = create_patient()
    prescriber = create_prescriber()
    rx, rq, claim = setup_active_prescription(
        patient["id"], prescriber["id"], drug_id,
        packaged_quantity=packaged_quantity,
        total_refills_authorized=total_refills_authorized,
        ship_state_code=ship_state_code,
    )
    pharmacy, license_row = setup_licensed_pharmacy(
        state_code=licence_state or ship_state_code
    )
    return {
        "patient": patient,
        "prescriber": prescriber,
        "prescription": rx,
        "request": rq,
        "claim": claim,
        "pharmacy": pharmacy,
        "license": license_row,
    }


def setup_full_stack(drug_rows=None, drug_overrides=None, formulary=True,
                     demand=0, quantity=30, packaged_quantity=100,
                     total_refills_authorized=1, ship_state_code="CA",
                     licence_state=None, shipping_enabled=True,
                     create_order_now=True, source_index=0, fallback_index=None,
                     manufacturer_name="Bexley Generics"):
    """The workhorse scenario, built in the order the workflows require:

    1. manufacturer + drug + ACTIVE+SOURCED price rows;
    2. patient + prescriber + an ACTIVE prescription whose intake request has
       been accepted (its packaged_quantity is the drug's trailing demand);
    3. formulary admission, which needs that demand to exist;
    4. a pharmacy holding an ACTIVE licence for the destination state;
    5. optionally a CREATED order drawing on one of the sourced rows.

    Returns a dict of handles keyed by role.
    """
    ctx = setup_drug_with_pool(
        rows=drug_rows, drug_overrides=drug_overrides,
        manufacturer_name=manufacturer_name, formulary=False, demand=demand,
    )
    drug = ctx["drug"]

    patient = ctx["patient"] or create_patient()
    prescriber = ctx["prescriber"] or create_prescriber()
    rx, rq, claim = setup_active_prescription(
        patient["id"], prescriber["id"], drug["id"],
        packaged_quantity=packaged_quantity,
        total_refills_authorized=total_refills_authorized,
        ship_state_code=ship_state_code,
    )

    if formulary:
        drug = get_success_data(api_client.expand_formulary(drug["id"], OPS))

    pharmacy = create_pharmacy(shipping_enabled=shipping_enabled)
    license_row = create_license_pending(
        pharmacy["id"], state_code=licence_state or ship_state_code,
        expiry_at=FAR_FUTURE,
        license_number=f"{licence_state or ship_state_code}-MP-1001",
    )
    license_row = verify_license(pharmacy["id"], license_row["id"])

    ctx.update({
        "drug": drug,
        "patient": patient,
        "prescriber": prescriber,
        "prescription": rx,
        "request": rq,
        "claim": claim,
        "pharmacy": pharmacy,
        "license": license_row,
    })
    ctx["order"] = None
    if create_order_now:
        source_price_id = ctx["prices"][source_index]["id"]
        fallback_price_id = (ctx["prices"][fallback_index]["id"]
                             if fallback_index is not None else None)
        order_payload = create_order_payload(
            rx["id"], rq["id"], pharmacy["id"], source_price_id,
            quantity=quantity,
        )
        if fallback_price_id is not None:
            order_payload["sub_source_price_id"] = fallback_price_id
        ctx["order"] = get_success_data(api_client.create_order(order_payload, OPS))
    return ctx


# ═══════════════════════════════════════════════════════
# Tier 3 — full lifecycle shortcuts
# ═══════════════════════════════════════════════════════

def drive_order_to(order_id, status):
    """Walk a freshly-created order forward to `status` and return it.

    `status` must be one of the forward states CREATED..DELIVERED.
    """
    current = get_success_data(api_client.get_order(order_id, OPS))
    if status == "CREATED":
        return current
    current = pay_order(order_id)
    if status == "PAID":
        return current
    current = fulfill_order(order_id)
    if status == "FULFILLING":
        return current
    current = ship_order(order_id)
    if status == "SHIPPED":
        return current
    current = deliver_order(order_id)
    return current


def setup_order_at_status(target_status, drug_rows=None, quantity=30,
                          packaged_quantity=100, total_refills_authorized=1,
                          ship_state_code="CA", licence_state=None,
                          demand=0):
    """Full stack plus an order driven to `target_status`.

    Returns the same dict as setup_full_stack with `order` at the target state.
    """
    ctx = setup_full_stack(
        drug_rows=drug_rows, formulary=True, demand=demand, quantity=quantity,
        packaged_quantity=packaged_quantity,
        total_refills_authorized=total_refills_authorized,
        ship_state_code=ship_state_code, licence_state=licence_state,
    )
    ctx["order"] = drive_order_to(ctx["order"]["id"], target_status)
    return ctx


def setup_multiple_orders(count, drug_rows=None, quantity=2, packaged_quantity=None,
                          total_refills_authorized=1, ship_state_code="CA"):
    """One drug + one licensed pharmacy + `count` independent PAID orders, each
    drawn from its own prescription and request.

    Used by carrier-slot tests that need several concurrent shipments of the
    same drug. Returns a dict with the shared drug/pharmacy plus an `orders`
    list.
    """
    ctx = setup_full_stack(
        drug_rows=drug_rows, formulary=True, demand=0, quantity=quantity,
        packaged_quantity=packaged_quantity or quantity,
        total_refills_authorized=total_refills_authorized,
        ship_state_code=ship_state_code,
    )
    orders = [pay_order(ctx["order"]["id"])]
    for _ in range(count - 1):
        extra = setup_active_prescription(
            ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["drug"]["id"],
            packaged_quantity=packaged_quantity or quantity,
            total_refills_authorized=total_refills_authorized,
            ship_state_code=ship_state_code,
        )
        order = get_success_data(api_client.create_order(create_order_payload(
            extra[0]["id"], extra[1]["id"], ctx["pharmacy"]["id"],
            ctx["primary_price"]["id"], quantity=quantity), OPS))
        orders.append(pay_order(order["id"]))
    ctx["orders"] = orders
    return ctx


# ═══════════════════════════════════════════════════════
# Tier 4 — accumulation / threshold targeting
# ═══════════════════════════════════════════════════════

def setup_expansion_boundary(demand_units, supply_units, drug_overrides=None,
                             reliability_tier="C", unit_cost_cents=12,
                             packaging="500-count bottle"):
    """A drug with exactly `demand_units` of trailing demand and a single
    sourced row of exactly `supply_units` available units.

    Returns (drug, price_row, prescriptions, requests) — demand is driven by
    accepted intake requests of 50 units each.
    """
    manufacturer = create_manufacturer()
    drug = create_drug(**(drug_overrides or {}))
    price_row = create_sourced_price(
        drug["id"], manufacturer["id"],
        unit_cost_cents=unit_cost_cents, available_units=supply_units,
        reliability_tier=reliability_tier, packaging=packaging,
    )
    patient = create_patient()
    prescriber = create_prescriber()
    prescriptions, requests = add_accepted_demand(
        drug["id"], patient["id"], prescriber["id"], demand_units
    )
    return drug, price_row, prescriptions, requests


def setup_drug_in_formulary(price_rows=None, demand=100, drug_overrides=None,
                            quantity=30, packaged_quantity=100, ship_state_code="CA"):
    """A drug already admitted to the formulary, with the full dispensing
    context a payment or fulfilment test needs. Returns the handles dict."""
    ctx = setup_full_stack(
        drug_rows=price_rows or [{"available_units": 600}],
        drug_overrides=drug_overrides, formulary=True, demand=demand,
        quantity=quantity, packaged_quantity=packaged_quantity,
        ship_state_code=ship_state_code,
    )
    return ctx


# ═══════════════════════════════════════════════════════
# Tier 5 — comparison / substantiation lifecycle
# ═══════════════════════════════════════════════════════

def setup_order_with_comparison(total_refills_authorized=1, quantity=60,
                                drug_rows=None, ship_state_code="CA"):
    """A full stack plus a CREATED order and its PriceComparison row.

    Returns (ctx, comparison).
    """
    ctx = setup_full_stack(
        drug_rows=drug_rows, formulary=True, quantity=quantity,
        total_refills_authorized=total_refills_authorized,
        ship_state_code=ship_state_code,
    )
    comparisons = list_comparisons_of(ctx["order"]["id"])
    return ctx, comparisons[0]


def register_substantiation(order_id, **overrides):
    return get_success_data(
        api_client.create_substantiation(create_substantiation_payload(order_id, **overrides), OPS)
    )


def setup_substantiated_comparison(enable=True, total_refills_authorized=1,
                                   quantity=60, drug_rows=None,
                                   ship_state_code="CA", **subst_overrides):
    """A stack with a CREATED order, a comparison, and a substantially
    registered record, optionally enabled.

    Returns (ctx, comparison, substantiation).
    """
    ctx, comparison = setup_order_with_comparison(
        total_refills_authorized=total_refills_authorized, quantity=quantity,
        drug_rows=drug_rows, ship_state_code=ship_state_code,
    )
    sub = register_substantiation(ctx["order"]["id"], **subst_overrides)
    if enable:
        version = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))["version"]
        get_success_data(
            api_client.enable_substantiation(ctx["order"]["id"], sub["id"], version, OPS)
        )
        sub = get_success_data(api_client.get_substantiation(sub["id"], OPS))
        comparison = list_comparisons_of(ctx["order"]["id"])[0]
    return ctx, comparison, sub


def setup_substituted_order(new_drug_overrides=None, total_refills_authorized=1,
                            quantity=60):
    """A stack with a CREATED order on drug D1, a substitution to a second drug
    D2, and the resulting REFRESH_REQUIRED comparison.

    Returns (ctx, new_drug, comparison).
    """
    ctx, comparison = setup_order_with_comparison(
        total_refills_authorized=total_refills_authorized, quantity=quantity
    )
    new_drug = create_drug(**(new_drug_overrides or {
        "drug_name": "Metformin ER", "retail_reference_price_cents": 2000,
        "insured_reference_price_cents": 1600,
    }))
    get_success_data(api_client.substitute_prescription(
        ctx["prescription"]["id"],
        {"new_drug_id": new_drug["id"], "reason_code": "SHORTAGE_SUBSTITUTION"},
        PHARMACIST,
    ))
    comparison = list_comparisons_of(ctx["order"]["id"])[0]
    return ctx, new_drug, comparison