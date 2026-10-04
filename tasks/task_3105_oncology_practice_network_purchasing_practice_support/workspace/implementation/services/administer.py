"""Treatment administration: vial rounding, FIFO draws, wastage, stock counting.

The two dose plans (WASTE_BILLED / WASTE_ABSORBED) draw exactly the same units
from the same lots in the same FIFO order; they disagree only about who pays for
the remainder, which is why the divergence shows up on the treatment, on the lot
and on the claim alike.
"""

import math
from decimal import Decimal

import db
from services import helpers
from services import pricing
from utils import parse_iso, utc_now_dt

WASTE_BILLED = "WASTE_BILLED"
WASTE_ABSORBED = "WASTE_ABSORBED"

CANDIDATE_STATUS = "AVAILABLE"


def _dt(value):
    return parse_iso(value)


def usable_lots(practice_id, product_id, instant):
    """AVAILABLE lots of the practice and product whose expires_at is strictly
    after the evaluated instant — a lot expiring exactly at t is not usable."""
    rows = db.where("inventory_lots", practice_id=practice_id, drug_product_id=product_id)
    out = []
    for lot in rows:
        if lot["status"] != CANDIDATE_STATUS:
            continue
        expires = _dt(lot.get("expires_at"))
        if expires is None or not (expires > instant):
            continue
        out.append(lot)
    return out


def fifo_order(lots):
    """expires_at ASC, then created_at ASC — an identifier is never a key."""
    return sorted(
        lots,
        key=lambda l: (l.get("expires_at") or "", l.get("created_at") or "", l.get("_seq", 0)),
    )


def usable_units(practice_id, product_id, instant):
    return sum(
        int(l.get("quantity_remaining") or 0) for l in usable_lots(practice_id, product_id, instant)
    )


def expiring_units(practice_id, product_id):
    """Physically on the shelf: no expiry filter at all."""
    rows = db.where("inventory_lots", practice_id=practice_id, drug_product_id=product_id)
    return sum(
        int(l.get("quantity_remaining") or 0) for l in rows if l["status"] == CANDIDATE_STATUS
    )


def expire_lots_at(practice_id, instant, product_id=None):
    """Expiry fires inside administer for every lot whose expires_at has been
    reached by the administration instant, quarantined lots included."""
    rows = db.where("inventory_lots", practice_id=practice_id)
    expired = []
    for lot in rows:
        if lot["status"] not in ("AVAILABLE", "QUARANTINED"):
            continue
        if product_id is not None and lot.get("drug_product_id") != product_id:
            continue
        expires = _dt(lot.get("expires_at"))
        if expires is not None and expires <= instant:
            lot["status"] = "EXPIRED"
            db.touch(lot)
            expired.append(lot)
    return expired


def draw_plan(administered_units, vial_yield_units, dose_count):
    """Vial count is identical under both dose plans, because a vial cannot be
    half-opened. The remainder is part of the total draw, never additional."""
    yield_units = int(vial_yield_units or 1)
    administered = int(administered_units or 0)
    doses = int(dose_count or 1)
    if yield_units <= 0:
        vial_count = 0
        dose_units_per_dose = administered
    else:
        vial_count = int(math.ceil(Decimal(administered) / Decimal(yield_units)))
        dose_units_per_dose = vial_count * yield_units
    waste_per_dose = dose_units_per_dose - administered
    allocations = [
        {
            "vial_count": vial_count,
            "dose_units": dose_units_per_dose,
            "waste_per_dose_units": waste_per_dose,
        }
        for _ in range(max(doses, 0))
    ]
    return {
        "vial_count": vial_count,
        "dose_units_per_dose": dose_units_per_dose,
        "waste_per_dose_units": waste_per_dose,
        "total_draw_units": doses * dose_units_per_dose,
        "remainder_units": waste_per_dose * doses,
        "dose_allocations": allocations,
    }


def remainder_units(product, plan_detail):
    """Only VIAL products carry a remainder at all."""
    if product.get("unit_type") != "VIAL":
        return 0
    return int(plan_detail["remainder_units"])


def ensure_dose_plan(data):
    from errors import ApiError

    plan = data.get("dose_plan")
    if plan is None:
        return WASTE_BILLED
    if plan not in (WASTE_BILLED, WASTE_ABSORBED):
        raise ApiError("ERR_INVALID_REQUEST", "dose_plan must be WASTE_BILLED or WASTE_ABSORBED")
    return plan


def administer(treatment, practice, plan):
    """Consume inventory FIFO, record the consumption rows, and settle the
    treatment's cost basis. Both plans draw identical units from identical lots."""
    product = db.get("drug_products", treatment["drug_product_id"])
    instant = _dt(treatment.get("administered_at")) or utc_now_dt()

    expire_lots_at(practice["id"], instant, treatment["drug_product_id"])

    plan_detail = draw_plan(
        treatment.get("administered_units"),
        treatment.get("vial_yield_units"),
        treatment.get("dose_count"),
    )
    remainder = remainder_units(product, plan_detail)
    wastage = remainder if plan == WASTE_BILLED else 0
    total_draw = plan_detail["total_draw_units"]

    candidates = fifo_order(usable_lots(practice["id"], treatment["drug_product_id"], instant))
    draws = []
    need = total_draw
    for lot in candidates:
        if need <= 0:
            break
        available = int(lot.get("quantity_remaining") or 0)
        if available <= 0:
            continue
        take = min(need, available)
        draws.append({"lot": lot, "qty": take, "waste": 0})
        need -= take

    # Under the billed plan the wastage draw is emitted as the last row, from
    # the terminal lot, at that lot's same per-unit cost basis.
    if wastage > 0:
        outstanding = wastage
        for entry in reversed(draws):
            if outstanding == 0:
                break
            take = min(entry["qty"], outstanding)
            entry["qty"] -= take
            entry["waste"] += take
            outstanding -= take

    rows = []
    for entry in draws:
        if entry["qty"] > 0:
            rows.append({"lot": entry["lot"], "qty": entry["qty"], "is_wastage": False})
        if entry["waste"] > 0:
            rows.append({"lot": entry["lot"], "qty": entry["waste"], "is_wastage": True})

    acquisition_basis = 0
    wastage_basis = 0
    for sequence, row in enumerate(rows, start=1):
        lot = row["lot"]
        cost_per_unit = int(lot.get("acquisition_cost_cents_per_unit") or 0)
        cost_basis = row["qty"] * cost_per_unit
        acquisition_basis += cost_basis
        if row["is_wastage"]:
            wastage_basis += cost_basis
        db.touch(
            db.create(
                "lot_consumptions",
                {
                    "treatment_id": treatment["id"],
                    "inventory_lot_id": lot["id"],
                    "practice_id": practice["id"],
                    "drug_product_id": treatment["drug_product_id"],
                    "quantity_consumed": row["qty"],
                    "cost_basis_cents": cost_basis,
                    "consumption_sequence": sequence,
                    "is_wastage": row["is_wastage"],
                },
            )
        )
        lot["quantity_remaining"] = int(lot.get("quantity_remaining") or 0) - row["qty"]
        if row["is_wastage"]:
            lot["wastage_units"] = int(lot.get("wastage_units") or 0) + row["qty"]
            lot["waste_cost_basis_cents"] = int(lot.get("waste_cost_basis_cents") or 0) + cost_basis
        if int(lot.get("quantity_remaining") or 0) <= 0:
            lot["quantity_remaining"] = 0
            lot["status"] = "DEPLETED"
        db.touch(lot)

    if plan == WASTE_ABSORBED and remainder > 0 and draws:
        # The remainder dollars land on the lot as absorbed cost and never
        # appear on a claim, so the practice's recovery is lower by exactly it.
        terminal = draws[-1]["lot"]
        per_unit = int(terminal.get("acquisition_cost_cents_per_unit") or 0)
        terminal["absorbed_cost_basis_cents"] = int(
            terminal.get("absorbed_cost_basis_cents") or 0
        ) + remainder * per_unit
        db.touch(terminal)

    treatment["dose_allocations"] = plan_detail["dose_allocations"]
    treatment["unmet_dose_units"] = 0
    treatment["wastage_units"] = wastage
    treatment["acquisition_cost_basis_cents"] = acquisition_basis
    treatment["wastage_cost_basis_cents"] = wastage_basis
    treatment["is_pathway_concordant"] = concordant(treatment, product, instant)
    treatment["status"] = "ADMINISTERED"
    treatment["received_at"] = treatment.get("received_at")
    return treatment


# ---------------------------------------------------------------------------
# Pathways


def regime_protocol(treatment):
    return db.get("pathway_protocols", treatment.get("pathway_protocol_id"))


def concordant(treatment, product, instant):
    """is_pathway_concordant is true when the regimen code belongs to the
    on-pathway subset of the protocol in force at administered_at."""
    protocol = regime_protocol(treatment)
    if protocol is None or protocol.get("status") != "PUBLISHED":
        return False
    return treatment.get("regimen_code") in (protocol.get("on_pathway_regimen_codes") or [])


def recompute_adherence(practice):
    helpers.recompute_adherence(practice)


# ---------------------------------------------------------------------------
# Draw unit cost rate used by the claim assembly


def treatment_draw_unit_cost(treatment):
    return pricing.draw_unit_cost_cents(treatment["practice_id"], treatment["drug_product_id"])