"""Route handlers: manufacturers, drugs, formularies, prices, pharmacies,
licences, patients and prescribers.

Every handler receives the per-request context and the path parameters and
returns (payload, http_status).
"""

from clock import now, now_iso, parse_iso, to_iso
from cascades import (
    delist_cascade,
    recompute_drug,
    recompute_drug_quiet,
    suppress_all_price_rows,
)
from errors import fail, success_payload
from pricing import (
    effective_unit_cost_cents,
    eligible_pool,
    expansion_score as compute_expansion_score,
    per_row_interval,
    primary_row,
    shipment_interval_days,
    sourcing_status as compute_sourcing_status,
)
from registry import (
    active_license_for,
    all_of,
    find,
    get,
    license_pair,
    of_parent,
    ordered_by_created,
    price_rows_for_drug,
)
from resources import blank_record, internal_of, touch
from store import store

TRANSACTION_KINDS = (
    "manufacturers",
    "drugs",
    "pharmacies",
    "licenses",
    "prices",
    "patients",
    "prescribers",
    "prescriptions",
    "requests",
    "orders",
    "shipments",
    "claims",
    "comparisons",
    "substantiations",
)


def _array(ctx, records):
    return success_payload(records, "array", ctx.pagination(len(records)))


def _object(record):
    return success_payload(record, "object")


def _price_view(price):
    """A manufacturer price row plus its own computed `interval_days` (PRD §3.1:
    "The row also exposes a computed interval_days, the shipment interval this
    particular row contributes")."""
    if price is None:
        return None
    view = dict(price)
    view["interval_days"] = per_row_interval(price)
    return view


def _price_views(prices):
    return [_price_view(price) for price in prices]


# ---------------------------------------------------------------------------
# Manufacturers
# ---------------------------------------------------------------------------

def create_manufacturer(ctx):
    record = blank_record()
    record["manufacturer_name"] = ctx.text("manufacturer_name")
    record["status"] = "ACTIVE"
    store.manufacturers[record["id"]] = internal_of("manufacturers", record)
    return _object(record), 201


def get_manufacturer(ctx, manufacturer_id):
    return _object(find("manufacturers", manufacturer_id)), 200


def list_manufacturers(ctx):
    return _array(ctx, ordered_by_created(all_of("manufacturers"))), 200


def set_manufacturer_state(ctx, manufacturer_id):
    manufacturer = find("manufacturers", manufacturer_id)
    target = ctx.text("to_status")
    if target not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "to_status must be ACTIVE or SUSPENDED.")
    manufacturer["status"] = target
    if target == "SUSPENDED":
        for price in list(store.prices.values()):
            if price.get("manufacturer_id") != manufacturer_id:
                continue
            if price.get("sourcing_status") != "SOURCED":
                continue
            price["sourcing_status"] = "SUPPRESSED"
            touch(price)
            drug = get("drugs", price.get("drug_id"))
            if drug is None:
                continue
            # PRD §3.1: suspension forces every SOURCED row to SUPPRESSED and
            # "each such move runs the full sourcing-loss cascade" — it does
            # not by itself delist every drug the manufacturer offers.
            recompute_drug_quiet(drug.get("id"), now())
            if drug.get("state") == "FORMULARY" and drug.get("sourcing_status") != "SOURCED":
                delist_cascade(
                    drug, now(),
                    order_states=("CREATED", "PAID", "FULFILLING"),
                    deny_reason="SOURCING_LOST",
                )
            else:
                touch(drug)
    touch(manufacturer)
    return _object(manufacturer), 200


def list_manufacturer_drug_prices(ctx, manufacturer_id):
    find("manufacturers", manufacturer_id)
    records = ordered_by_created(of_parent("prices", "manufacturer_id", manufacturer_id))
    return _array(ctx, _price_views(records)), 200


# ---------------------------------------------------------------------------
# Drugs
# ---------------------------------------------------------------------------

def create_drug(ctx):
    record = blank_record()
    record["drug_name"] = ctx.text("drug_name")
    record["strength"] = ctx.text("strength")
    record["dosage_form"] = ctx.text("dosage_form")
    record["is_controlled"] = ctx.boolean("is_controlled")
    record["retail_reference_price_cents"] = ctx.integer("retail_reference_price_cents")
    record["insured_reference_price_cents"] = ctx.integer("insured_reference_price_cents")
    record["state"] = "NON_FORMULARY"
    record["packaging"] = None
    record["packaging_str"] = None
    record["reserved_total"] = 0
    record["demand_units_30d"] = 0
    record["supply_units"] = 0
    record["sourcing_status"] = "UNSOURCED"
    record["expansion_score"] = None
    record["effective_unit_cost_cents"] = None
    record["ship_interval_days"] = None
    store.drugs[record["id"]] = internal_of("drugs", record)
    return _object(record), 201


def get_drug(ctx, drug_id):
    find("drugs", drug_id)
    record = store.drugs[drug_id]
    if record.get("state") != "FORMULARY":
        recompute_drug_quiet(drug_id)
    return _object(record), 200


def list_drugs(ctx):
    records = list(store.drugs.values())
    state = ctx.query("state")
    if state:
        records = [rec for rec in records if rec.get("state") == state]
    records = ordered_by_created(records)
    return _array(ctx, records), 200


def stock_check(ctx, drug_id):
    find("drugs", drug_id)
    drug = store.drugs[drug_id]
    pool = eligible_pool(drug_id)
    drug["effective_unit_cost_cents"] = effective_unit_cost_cents(pool)
    drug["sourcing_status"] = compute_sourcing_status(drug_id)
    selected = primary_row(pool)
    if selected is not None:
        drug["packaging"] = selected.get("packaging")
        drug["packaging_str"] = selected.get("packaging")
    return _object(
        {
            "drug_id": drug_id,
            "effective_unit_cost_cents": drug["effective_unit_cost_cents"],
            "packaging": drug.get("packaging"),
            "sourcing_status": drug["sourcing_status"],
            "eligible_price_ids": [row.get("id") for row in ordered_by_created(pool)],
        }
    ), 200


def supply_summary(ctx, drug_id):
    find("drugs", drug_id)
    drug = store.drugs[drug_id]
    clock = now()
    recompute_drug_quiet(drug_id, clock)
    rows = []
    for price in ordered_by_created(price_rows_for_drug(drug_id)):
        rows.append(
            {
                "price_id": price.get("id"),
                "manufacturer_id": price.get("manufacturer_id"),
                "unit_cost_cents": price.get("unit_cost_cents"),
                "available_units": price.get("available_units"),
                "reliability_tier": price.get("reliability_tier"),
                "price_status": price.get("price_status"),
                "sourcing_status": price.get("sourcing_status"),
                "drug_sourcing_status": drug.get("sourcing_status"),
            }
        )
    return _object(
        {
            "drug_id": drug_id,
            "supply_units": drug.get("supply_units"),
            "demand_units_30d": drug.get("demand_units_30d"),
            "sourcing_status": drug.get("sourcing_status"),
            "rows": rows,
        }
    ), 200


def expansion_score_view(ctx, drug_id):
    find("drugs", drug_id)
    drug = store.drugs[drug_id]
    clock = now()
    recompute_drug_quiet(drug_id, clock)
    return _object(
        {
            "drug_id": drug_id,
            "expansion_score": drug.get("expansion_score"),
            "demand_units_30d": drug.get("demand_units_30d"),
            "supply_units": drug.get("supply_units"),
        }
    ), 200


def expand_formulary(ctx, drug_id):
    find("drugs", drug_id)
    drug = store.drugs[drug_id]
    clock = now()
    recompute_drug_quiet(drug_id, clock)
    demand = drug.get("demand_units_30d") or 0
    supply = drug.get("supply_units") or 0

    if drug.get("sourcing_status") != "SOURCED":
        fail("ERR_FORMULARY_GATE_FAILED", "The drug's sourcing_status is not SOURCED.")
    if drug.get("state") != "NON_FORMULARY":
        fail("ERR_FORMULARY_GATE_FAILED", "The drug's state is not NON_FORMULARY.")
    if drug.get("is_controlled") is True:
        fail("ERR_FORMULARY_GATE_FAILED", "A controlled substance may not enter the formulary.")
    if demand < 1:
        fail("ERR_FORMULARY_GATE_FAILED", "Trailing demand must be at least 1 unit.")
    if (drug.get("expansion_score") or 0) < 2:
        fail("ERR_FORMULARY_GATE_FAILED", "The expansion score must be at least 2.")
    if supply < demand:
        fail("ERR_FORMULARY_GATE_FAILED", "Supply must cover trailing demand.")

    drug["state"] = "FORMULARY"
    pool = eligible_pool(drug_id)
    selected = primary_row(pool)
    if selected is not None:
        drug["packaging"] = selected.get("packaging")
        drug["packaging_str"] = selected.get("packaging")
    drug["effective_unit_cost_cents"] = effective_unit_cost_cents(pool)
    drug["ship_interval_days"] = shipment_interval_days(pool)
    drug["expansion_score"] = compute_expansion_score(drug, demand, supply)
    touch(drug)
    return _object(drug), 200


def delist_formulary(ctx, drug_id):
    find("drugs", drug_id)
    drug = store.drugs[drug_id]
    clock = now()
    recompute_drug_quiet(drug_id, clock)
    if drug.get("state") != "FORMULARY":
        fail("ERR_INVALID_STATE", "Only a FORMULARY drug may be delisted.")
    # The Drug delist transition cancels every order on the drug still at
    # CREATED, PAID, FULFILLING or SHIPPED (PRD §3.3, §3.2).
    delist_cascade(
        drug,
        clock,
        order_states=("CREATED", "PAID", "FULFILLING", "SHIPPED"),
        deny_reason="SOURCING_LOST",
    )
    return _object(drug), 200


# ---------------------------------------------------------------------------
# Manufacturer drug prices
# ---------------------------------------------------------------------------

def create_price(ctx):
    record = blank_record()
    record["drug_id"] = ctx.text("drug_id")
    record["manufacturer_id"] = ctx.text("manufacturer_id")
    unit_cost = ctx.integer("unit_cost_cents")
    available = ctx.integer("available_units")
    if unit_cost < 1:
        fail("ERR_INVALID_AMOUNT", "unit_cost_cents must be at least 1.")
    if available < 0:
        fail("ERR_INVALID_AMOUNT", "available_units must be at least 0.")
    record["unit_cost_cents"] = unit_cost
    record["available_units"] = available
    tier = ctx.text("reliability_tier")
    if tier not in ("A", "B", "C"):
        fail("ERR_INVALID_STATE", "reliability_tier must be A, B or C.")
    record["reliability_tier"] = tier
    record["packaging"] = ctx.text("packaging")
    record["price_status"] = "PROPOSED"
    record["sourcing_status"] = "UNDER_REVIEW"
    find("drugs", record["drug_id"])
    find("manufacturers", record["manufacturer_id"])
    store.prices[record["id"]] = internal_of("prices", record)
    return _object(_price_view(record)), 201


def get_price(ctx, price_id):
    return _object(_price_view(find("prices", price_id))), 200


def list_prices(ctx):
    records = list(store.prices.values())
    drug_id = ctx.query("drug_id")
    manufacturer_id = ctx.query("manufacturer_id")
    if drug_id:
        records = [rec for rec in records if rec.get("drug_id") == drug_id]
    if manufacturer_id:
        records = [rec for rec in records if rec.get("manufacturer_id") == manufacturer_id]
    return _array(ctx, _price_views(ordered_by_created(records))), 200


def list_drug_prices(ctx, drug_id):
    find("drugs", drug_id)
    return _array(ctx, _price_views(ordered_by_created(price_rows_for_drug(drug_id)))), 200


def list_drug_prescriptions(ctx, drug_id):
    find("drugs", drug_id)
    records = ordered_by_created(of_parent("prescriptions", "drug_id", drug_id))
    return _array(ctx, records), 200


def activate_price(ctx, price_id):
    price = find("prices", price_id)
    if price.get("price_status") != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED price row may be activated.")
    manufacturer = find("manufacturers", price.get("manufacturer_id"))
    if manufacturer.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "The offering manufacturer is not ACTIVE.")
    price["price_status"] = "ACTIVE"
    drug_id = price.get("drug_id")
    recompute_drug_quiet(drug_id, now())
    touch(price)
    touch(store.drugs[drug_id])
    return _object(price), 200


def move_sourcing(ctx, price_id):
    price = find("prices", price_id)
    target = ctx.text("to_sourcing_status")
    if target not in ("SOURCED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE", "to_sourcing_status must be SOURCED or UNDER_REVIEW.")
    drug_id = price.get("drug_id")
    drug = store.drugs[drug_id]

    if target == "SOURCED":
        if price.get("sourcing_status") != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW row may be sourced.")
        if price.get("price_status") != "ACTIVE":
            fail("ERR_INVALID_STATE", "A row whose price dimension is not ACTIVE may not be sourced.")
        if int(price.get("available_units") or 0) <= 0:
            fail("ERR_INVALID_STATE", "A row with no available units may not be sourced.")
        manufacturer = find("manufacturers", price.get("manufacturer_id"))
        if manufacturer.get("status") != "ACTIVE":
            fail("ERR_INVALID_STATE", "The offering manufacturer is not ACTIVE.")
        price["sourcing_status"] = "SOURCED"
        recompute_drug_quiet(drug_id, now(), refresh_packaging=True)
        touch(price)
        touch(drug)
        return _object(price), 200

    if price.get("sourcing_status") != "SOURCED":
        fail("ERR_INVALID_STATE", "Only a SOURCED row may return to UNDER_REVIEW.")
    price["sourcing_status"] = "UNDER_REVIEW"
    recompute_drug_quiet(drug_id, now())
    if drug.get("state") == "FORMULARY" and drug.get("sourcing_status") != "SOURCED":
        # The conditional cascade fires before the order-price recomputation
        # (PRD §3.2 states the drug recomputation, then the cascade).
        delist_cascade(drug, now(),
                       order_states=("CREATED", "PAID", "FULFILLING"),
                       deny_reason="SOURCING_LOST")
    else:
        from cascades import recompute_open_orders_for_price

        recompute_open_orders_for_price(price_id)
    touch(price)
    touch(drug)
    return _object(price), 200


def revoke_price(ctx, price_id):
    price = find("prices", price_id)
    if price.get("price_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE price row may be revoked.")
    price["price_status"] = "REVOKED"
    price["sourcing_status"] = "SUPPRESSED"
    drug_id = price.get("drug_id")
    recompute_drug_quiet(drug_id, now())
    touch(price)
    touch(store.drugs[drug_id])
    return _object(price), 200


def list_price_orders(ctx, price_id):
    find("prices", price_id)
    records = [
        order
        for order in store.orders.values()
        if order.get("source_price_id") == price_id or order.get("sub_source_price_id") == price_id
    ]
    return _array(ctx, ordered_by_created(records)), 200


# ---------------------------------------------------------------------------
# Pharmacies and licences
# ---------------------------------------------------------------------------

def create_pharmacy(ctx):
    record = blank_record()
    record["pharmacy_name"] = ctx.text("pharmacy_name")
    record["domicile_state_code"] = ctx.text("domicile_state_code")
    record["shipping_enabled"] = ctx.boolean("shipping_enabled")
    record["status"] = "ACTIVE"
    store.pharmacies[record["id"]] = internal_of("pharmacies", record)
    return _object(record), 201


def get_pharmacy(ctx, pharmacy_id):
    return _object(find("pharmacies", pharmacy_id)), 200


def list_pharmacies(ctx):
    return _array(ctx, ordered_by_created(all_of("pharmacies"))), 200


def create_license(ctx, pharmacy_id):
    find("pharmacies", pharmacy_id)
    state_code = ctx.text("state_code")
    license_number = ctx.text("license_number")
    expiry_at = parse_iso(ctx.text("expiry_at"))
    if expiry_at is None:
        fail("ERR_INVALID_AMOUNT", "expiry_at must be an ISO 8601 instant.")
    incumbent = active_license_for(pharmacy_id, state_code)
    if incumbent is not None:
        incumbent_expiry = parse_iso(incumbent.get("expiry_at"))
        if incumbent_expiry is None or expiry_at <= incumbent_expiry:
            fail(
                "ERR_LICENSE_CONFLICT",
                "The incoming expiry must be strictly after the incumbent's.",
            )
    record = blank_record()
    record["pharmacy_id"] = pharmacy_id
    record["state_code"] = state_code
    record["license_number"] = license_number
    record["status"] = "PENDING"
    record["verified_at"] = None
    record["expiry_at"] = to_iso(expiry_at)
    store.licenses[record["id"]] = internal_of("licenses", record)
    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        touch(incumbent)
    return _object(record), 201


def list_licenses(ctx, pharmacy_id):
    find("pharmacies", pharmacy_id)
    records = of_parent("licenses", "pharmacy_id", pharmacy_id)
    status = ctx.query("status")
    if status:
        records = [rec for rec in records if rec.get("status") == status]
    return _array(ctx, ordered_by_created(records)), 200


def get_license(ctx, pharmacy_id, license_id):
    find("pharmacies", pharmacy_id)
    record = find("licenses", license_id)
    if record.get("pharmacy_id") != pharmacy_id:
        fail("ERR_RESOURCE_NOT_FOUND", "License %s does not belong to pharmacy %s." % (license_id, pharmacy_id))
    return _object(record), 200


def set_license_state(ctx, pharmacy_id, license_id):
    find("pharmacies", pharmacy_id)
    record = find("licenses", license_id)
    if record.get("pharmacy_id") != pharmacy_id:
        fail("ERR_RESOURCE_NOT_FOUND", "License %s does not belong to pharmacy %s." % (license_id, pharmacy_id))
    target = ctx.text("to_status")
    clock = now()
    if target == "REVOKED":
        if record.get("status") != "ACTIVE":
            fail("ERR_INVALID_STATE", "Only an ACTIVE licence may be revoked.")
        record["status"] = "REVOKED"
    elif target == "EXPIRED":
        if record.get("status") != "ACTIVE":
            fail("ERR_INVALID_STATE", "Only an ACTIVE licence may be expired.")
        record["status"] = "EXPIRED"
    else:
        fail("ERR_INVALID_STATE", "to_status must be REVOKED or EXPIRED.")
    touch(record)
    return _object(record), 200


def verify_license(ctx, pharmacy_id, license_id):
    find("pharmacies", pharmacy_id)
    record = find("licenses", license_id)
    if record.get("pharmacy_id") != pharmacy_id:
        fail("ERR_RESOURCE_NOT_FOUND", "License %s does not belong to pharmacy %s." % (license_id, pharmacy_id))
    clock = now()
    expiry_at = parse_iso(record.get("expiry_at"))
    status = record.get("status")
    unexpired = expiry_at is not None and expiry_at > clock
    if status in ("PENDING", "EXPIRED", "REVOKED"):
        if not unexpired:
            fail("ERR_INVALID_STATE", "The licence's expiry_at is not strictly after the logical clock.")
        record["status"] = "ACTIVE"
        record["verified_at"] = now_iso()
        touch(record)
        return _object(record), 200
    if status == "ACTIVE":
        if not unexpired:
            record["status"] = "EXPIRED"
            touch(record)
            return _object(record), 200
        # No ACTIVE -> ACTIVE transition is declared, so an unexpired ACTIVE
        # licence admits no further verification (PRD §3.5, §2.12).
        fail("ERR_INVALID_STATE", "An unexpired ACTIVE licence admits no verification transition.")
    fail("ERR_INVALID_STATE", "A licence at %s admits no verification transition." % status)


def list_pharmacy_orders(ctx, pharmacy_id):
    find("pharmacies", pharmacy_id)
    return _array(ctx, ordered_by_created(of_parent("orders", "pharmacy_id", pharmacy_id))), 200


# ---------------------------------------------------------------------------
# Patients and prescribers
# ---------------------------------------------------------------------------

def create_patient(ctx):
    record = blank_record()
    record["full_name"] = ctx.text("full_name")
    record["email"] = ctx.text("email")
    record["home_state_code"] = ctx.text("home_state_code")
    record["status"] = "ACTIVE"
    store.patients[record["id"]] = internal_of("patients", record)
    return _object(record), 201


def get_patient(ctx, patient_id):
    find("patients", patient_id)
    ctx.guard_ownership(patient_id)
    return _object(store.patients[patient_id]), 200


def list_patients(ctx):
    return _array(ctx, ordered_by_created(all_of("patients"))), 200


def create_prescriber(ctx):
    record = blank_record()
    record["prescriber_name"] = ctx.text("prescriber_name")
    record["npi"] = ctx.text("npi")
    record["license_state_code"] = ctx.text("license_state_code")
    record["status"] = "ACTIVE"
    store.prescribers[record["id"]] = internal_of("prescribers", record)
    return _object(record), 201


def get_prescriber(ctx, prescriber_id):
    return _object(find("prescribers", prescriber_id)), 200


def set_prescriber_state(ctx, prescriber_id):
    record = find("prescribers", prescriber_id)
    target = ctx.text("to_status")
    if target not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "to_status must be ACTIVE or SUSPENDED.")
    record["status"] = target
    touch(record)
    return _object(record), 200


def list_prescriber_prescriptions(ctx, prescriber_id):
    find("prescribers", prescriber_id)
    return _array(ctx, ordered_by_created(of_parent("prescriptions", "prescriber_id", prescriber_id))), 200


def list_patient_prescriptions(ctx, patient_id):
    find("patients", patient_id)
    ctx.guard_ownership(patient_id)
    return _array(ctx, ordered_by_created(of_parent("prescriptions", "patient_id", patient_id))), 200