"""Response projections for every entity.

Field names and ordering come from SCAFFOLD.yaml SS1.1. Numeric/computed
projections (daily dosage, consumption cycle, remaining quantities) are
recomputed at serialisation time so that read endpoints always report the
current derived value.

PRD SS2.4: every entity except `Pet` carries id/created_at/updated_at/version;
`Pet` carries only id and created_at.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from services.constants import (
    CAT_SPECIES_MULTIPLIER,
    DOSE_TIER_LT_MG,
    DOSE_TIER_MG,
    MIN_CYCLE_DAYS,
    MAX_EQUIVALENT_DAYS,
    MIN_WEIGHT_KG,
    OTHER_SPECIES_MULTIPLIER,
    PROTECTION_GUARD_RATE,
    UNITS_PER_DOSE,
)
from services.constants import (
    OVERDUE_URGENT_DAYS,
    OVERDUE_SOON_DAYS,
    PROMPT_ALIGNED_WINDOW_DAYS,
    MAX_PROMPT_DEFERRAL_DAYS,
)


def _round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# --- projection mathematics (PRD SS2.5) -------------------------------------

def dosage_mg_per_day(pet, product):
    """unit_dose_mg_per_kg * weight_kg * species multiplier, rounded once."""
    if pet is None or product is None:
        return None
    multiplier = (
        CAT_SPECIES_MULTIPLIER if pet.get("species") == "CAT" else OTHER_SPECIES_MULTIPLIER
    )
    raw = float(product.get("unit_dose_mg_per_kg", 0)) * float(pet.get("weight_kg", 0)) * multiplier
    return float(_round_half_up(raw, 2))


def dosage_pet_only(pet, product):
    """The scaffold's pet_only_projection variant (species multiplier omitted)."""
    if pet is None or product is None:
        return None
    raw = float(product.get("unit_dose_mg_per_kg", 0)) * float(pet.get("weight_kg", 0))
    return float(_round_half_up(raw, 2))


def run_units_per_day(pet, product):
    if pet is None or product is None:
        return 1, 0.0, 0.0
    sentinel = max(float(pet.get("weight_kg", 0)), MIN_WEIGHT_KG)
    weight_cat = math.ceil(sentinel)
    body_dose = weight_cat * float(product.get("unit_dose_mg_per_kg", 0))
    if body_dose >= DOSE_TIER_MG:
        tier_ge = math.floor(body_dose / DOSE_TIER_MG)
        tier_lt = -1
    else:
        tier_ge = -1
        tier_lt = 2 * math.floor(body_dose / DOSE_TIER_LT_MG)
    return max(1, max(tier_ge, tier_lt)), body_dose, float(weight_cat)


def run_cadence_days(pet, product):
    """Consumption cycle: how many days one pack lasts (clamped 14..84)."""
    if pet is None or product is None:
        return None
    units, _body, _cat = run_units_per_day(pet, product)
    pack_size = int(product.get("pack_size_units", 1) or 1)
    raw = math.floor(pack_size / units)
    return max(MIN_CYCLE_DAYS, min(MAX_EQUIVALENT_DAYS, raw))


def refill_units_consumed(pet, product, item):
    """doses_per_day * cadence_days * UNITS_PER_DOSE (ceil on doses_per_day)."""
    if pet is None or product is None or item is None:
        return 0
    dose = float(product.get("unit_dose_mg_per_kg", 0) or 0)
    if dose <= 0:
        return 0
    doses_per_day = math.ceil(dosage_mg_per_day(pet, product) / dose)
    return int(doses_per_day * int(item.get("cadence_days", 0)) * UNITS_PER_DOSE)


def protection_guard(price_protected_unit_price_cents):
    if price_protected_unit_price_cents is None:
        return None
    return int(_round_half_up(price_protected_unit_price_cents * (1 + PROTECTION_GUARD_RATE), 0))


def protection_state(item):
    """PROTECTED while unit_price_cents <= guard, otherwise REPRICED."""
    guard = protection_guard(item.get("price_protected_unit_price_cents"))
    if guard is None:
        return "PROTECTED"
    return "PROTECTED" if item.get("unit_price_cents", 0) <= guard else "REPRICED"


# --- per-entity projections -------------------------------------------------

def pet(row):
    """Pet carries only id and created_at (PRD SS2.4)."""
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "pet_name": row.get("pet_name"),
        "species": row.get("species"),
        "breed": row.get("breed"),
        "weight_kg": row.get("weight_kg"),
        "owner_state": row.get("owner_state"),
        "pet_status": row.get("pet_status"),
        "passed_at": row.get("passed_at"),
        "pet_lifecycle_state": pet_lifecycle_state(row),
        "compassionate_review_id": row.get("compassionate_review_id"),
    }


def pet_lifecycle_state(row):
    """PRD SS3.6: ALIVE while ACTIVE; PASSED while PASSED and review OPEN;
    ARCHIVED while PASSED and the review is APPROVED or REJECTED."""
    if row.get("pet_status") != "PASSED":
        return "ALIVE"
    review_id = row.get("compassionate_review_id")
    if not review_id:
        return "PASSED"
    review = db.COMPASSIONATE_REVIEWS.get(review_id)
    if review is None:
        return "PASSED"
    if review.get("review_status") == "OPEN":
        return "PASSED"
    return "ARCHIVED"


def veterinarian(row):
    out = _common(row)
    out.update(
        {
            "full_name": row.get("full_name"),
            "clinic_name": row.get("clinic_name"),
            "clinic_phone": row.get("clinic_phone"),
            "vet_email": row.get("vet_email"),
            "license_number": row.get("license_number"),
            "license_state": row.get("license_state"),
            "vet_status": row.get("vet_status"),
        }
    )
    return out


def pharmacy_site(row):
    out = _common(row)
    out.update(
        {
            "site_code": row.get("site_code"),
            "site_state": row.get("site_state"),
            "licensed_states": list(row.get("licensed_states") or []),
            "cold_pack_capacity_units": row.get("cold_pack_capacity_units"),
            "csr_registered": row.get("csr_registered"),
            "cold_pack_committed_units": committed_units(row["id"]),
            "site_status": row.get("site_status"),
        }
    )
    return out


def committed_units(site_id):
    """Invariant (scaffold cold_pack_reserved_units): sum of HELD reservations."""
    return sum(
        int(r.get("units", 0))
        for r in db.COLD_PACK_RESERVATIONS.values()
        if r.get("site_id") == site_id and r.get("reservation_status") == "HELD"
    )


def product(row):
    out = _common(row)
    out.update(
        {
            "sku": row.get("sku"),
            "product_name": row.get("product_name"),
            "medication_scope": row.get("medication_scope"),
            "cold_pack_required": row.get("cold_pack_required"),
            "unit_dose_mg_per_kg": row.get("unit_dose_mg_per_kg"),
            "pack_size_units": row.get("pack_size_units"),
            "unit_price_cents": row.get("unit_price_cents"),
        }
    )
    return out


def autoship_plan(row):
    out = _common(row)
    due = plan_next_due_date(row["id"])
    out.update(
        {
            "pet_id": row.get("pet_id"),
            "plan_status": row.get("plan_status"),
            "autoship_discount_eligibility": row.get("autoship_discount_eligibility"),
            "next_order_due_date": clock.iso(due),
            "autoship_item_count": plan_item_count(row["id"]),
            "cadence_prompt_due_date": clock.iso(row.get("cadence_prompt_due_date")),
            "cadence_prompt_due_days_delta": plan_prompt_delta(row),
            "blackout_start_date": clock.iso(row.get("blackout_start_date")),
            "blackout_end_date": clock.iso(row.get("blackout_end_date")),
            "released_refunds_cents": row.get("released_refunds_cents", 0),
            "transaction_adjustments_cents": row.get("transaction_adjustments_cents", 0),
        }
    )
    return out


def plan_item_count(plan_id):
    return sum(
        1
        for i in db.AUTOSHIP_ITEMS.values()
        if i.get("autoship_plan_id") == plan_id
        and i.get("item_status") in ("ACTIVE", "PAUSED")
    )


def plan_active_items(plan_id):
    return [
        i
        for i in db.AUTOSHIP_ITEMS.values()
        if i.get("autoship_plan_id") == plan_id and i.get("item_status") == "ACTIVE"
    ]


def plan_next_due_date(plan_id):
    """Earliest autoship_item_next_due_date across ACTIVE items, else None."""
    dues = [
        i.get("autoship_item_next_due_date")
        for i in plan_active_items(plan_id)
        if i.get("autoship_item_next_due_date") is not None
    ]
    return min(dues) if dues else None


def plan_prompt_delta(plan):
    """Scaffold/PRD SS3.2 ladder over the whole-day gap."""
    due = plan_next_due_date(plan["id"])
    if due is None:
        return 0
    base = plan.get("cadence_prompt_due_date") or due
    gap = clock.whole_days_between(base, due)
    if gap <= -OVERDUE_URGENT_DAYS:
        return 14
    if gap <= -OVERDUE_SOON_DAYS:
        return 7
    if gap <= 0:
        return 0
    if gap < PROMPT_ALIGNED_WINDOW_DAYS:
        return PROMPT_ALIGNED_WINDOW_DAYS
    return min(gap - PROMPT_ALIGNED_WINDOW_DAYS, MAX_PROMPT_DEFERRAL_DAYS)


def autoship_item(row):
    out = _common(row)
    pet = db.PETS.get(_plan(row).get("pet_id")) if _plan(row) else None
    prod = db.PRODUCTS.get(row.get("product_id"))
    out.update(
        {
            "autoship_plan_id": row.get("autoship_plan_id"),
            "product_id": row.get("product_id"),
            "item_status": row.get("item_status"),
            "verification_state": row.get("verification_state"),
            "cadence_days": row.get("cadence_days"),
            "autoship_item_next_due_date": clock.iso(row.get("autoship_item_next_due_date")),
            "unit_lifecycle_equivalent_days": run_cadence_days(pet, prod),
            "cadence_prompt_state": cadence_prompt_state(row, pet, prod),
            "dosage_mg_per_day": dosage_mg_per_day(pet, prod),
            "dosage_pet_only_mg_per_day": dosage_pet_only(pet, prod),
            "default_quantity": row.get("default_quantity"),
            "unit_price_cents": row.get("unit_price_cents"),
            "price_protected_unit_price_cents": row.get("price_protected_unit_price_cents"),
            "protection_state": protection_state(row),
        }
    )
    return out


def _plan(item):
    return db.AUTOSHIP_PLANS.get(item.get("autoship_plan_id"))


def cadence_prompt_state(item, pet=None, prod=None):
    """UNDER_CONSUMPTION / ALIGNED / OVER_CONSUMPTION (PRD SS3.2)."""
    if pet is None:
        plan = _plan(item)
        pet = db.PETS.get(plan.get("pet_id")) if plan else None
    if prod is None:
        prod = db.PRODUCTS.get(item.get("product_id"))
    equiv = run_cadence_days(pet, prod)
    if equiv is None:
        return "ALIGNED"
    delta = equiv - int(item.get("cadence_days", 0))
    if delta > PROMPT_ALIGNED_WINDOW_DAYS:
        return "UNDER_CONSUMPTION"
    if -delta > PROMPT_ALIGNED_WINDOW_DAYS:
        return "OVER_CONSUMPTION"
    return "ALIGNED"


def prescription(row):
    out = _common(row)
    out.update(
        {
            "autoship_item_id": row.get("autoship_item_id"),
            "prescriber_id": row.get("prescriber_id"),
            "rx_status": row.get("rx_status"),
            "script_source": row.get("script_source"),
            "script_document_id": row.get("script_document_id"),
            "written_prescriber_email_hash": row.get("written_prescriber_email_hash"),
            "drug_schedule": row.get("drug_schedule"),
            "temperature_sensitive": row.get("temperature_sensitive"),
            "authorized_qty_total": row.get("authorized_qty_total"),
            "authorized_qty_remaining": row.get("authorized_qty_remaining"),
            "refills_authorized": row.get("refills_authorized"),
            "refills_used": row.get("refills_used"),
            "verification_expires_at": clock.iso(row.get("verification_expires_at")),
            "callback_attempt_count": row.get("callback_attempt_count", 0),
        }
    )
    return out


def order(row):
    out = _common(row)
    out.update(
        {
            "autoship_plan_id": row.get("autoship_plan_id"),
            "order_kind": row.get("order_kind"),
            "order_status": row.get("order_status"),
            "composed_at": clock.iso(row.get("composed_at")),
            "bundle_line_count": row.get("bundle_line_count", 0),
            "merchandise_subtotal_cents": row.get("merchandise_subtotal_cents", 0),
            "autoship_discount_cents": row.get("autoship_discount_cents", 0),
            "residual_promo_discount_cents": row.get("residual_promo_discount_cents", 0),
            "order_total_cents": row.get("order_total_cents", 0),
            "order_total_components_sum": row.get("order_total_components_sum", 0),
            "cold_pack_fee_cents": row.get("cold_pack_fee_cents", 0),
            "expedited_shipping_fee_cents": row.get("expedited_shipping_fee_cents", 0),
            "promotion_code": row.get("promotion_code"),
            "override_code": row.get("override_code"),
            "cancellation_reason": row.get("cancellation_reason"),
            "refunded_amount_cents": row.get("refunded_amount_cents", 0),
            "settlement_net_cents": row.get("settlement_net_cents", 0),
            "settlement_payment_balance_cents": row.get("settlement_payment_balance_cents", 0),
        }
    )
    return out


def order_line(row):
    out = _common(row)
    out.update(
        {
            "order_id": row.get("order_id"),
            "autoship_item_id": row.get("autoship_item_id"),
            "product_id": row.get("product_id"),
            "quantity": row.get("quantity"),
            "line_unit_price_cents": row.get("line_unit_price_cents"),
            "line_autoship_discount_cents": row.get("line_autoship_discount_cents", 0),
            "line_item_subtotal_cents": row.get("line_item_subtotal_cents", 0),
            "line_requires_clinic_auth": row.get("line_requires_clinic_auth", False),
        }
    )
    return out


def shipment(row):
    out = _common(row)
    out.update(
        {
            "order_id": row.get("order_id"),
            "origin_site_id": row.get("origin_site_id"),
            "destination_state": row.get("destination_state"),
            "shipment_status": row.get("shipment_status"),
            "cold_pack_required": row.get("cold_pack_required", False),
            "cold_pack_units": row.get("cold_pack_units", 0),
            "transit_window_start_date": clock.iso(row.get("transit_window_start_date")),
            "transit_window_end_date": clock.iso(row.get("transit_window_end_date")),
            "tracking_code": row.get("tracking_code"),
        }
    )
    return out


def cold_pack_reservation(row):
    out = _common(row)
    out.update(
        {
            "shipment_id": row.get("shipment_id"),
            "site_id": row.get("site_id"),
            "units": row.get("units", 0),
            "reservation_status": row.get("reservation_status"),
        }
    )
    return out


def compassionate_review(row):
    out = _common(row)
    out.update(
        {
            "pet_id": row.get("pet_id"),
            "affected_shipment_id": row.get("affected_shipment_id"),
            "review_status": row.get("review_status"),
            "refund_destination": row.get("refund_destination"),
            "refunded_amount_cents": row.get("refunded_amount_cents", 0),
        }
    )
    return out


def order_quantities_by_prescription(order_id):
    """Units per prescription over an order's lines (limit-14 check, PRD SS3.5)."""
    totals = {}
    for line in db.ORDER_LINES.values():
        if line.get("order_id") != order_id:
            continue
        item_id = line.get("autoship_item_id")
        rx = next(
            (
                p
                for p in db.PRESCRIPTIONS.values()
                if p.get("autoship_item_id") == item_id
            ),
            None,
        )
        if rx is None:
            continue
        totals[rx["id"]] = totals.get(rx["id"], 0) + int(line.get("quantity", 0))
    return totals
