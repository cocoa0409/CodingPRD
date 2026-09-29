"""Row resolution, uniqueness guards and the three transitive containment cascades."""

import db
from db import ordered, touch
from errors import ApiError
from serializers import held_unit_count

# --------------------------------------------------------------------------
# Path / body reference resolution
# --------------------------------------------------------------------------

TABLES = {
    "supplier": ("suppliers", "ERR_SUPPLIER_NOT_FOUND"),
    "component_lot": ("component_lots", "ERR_COMPONENT_LOT_NOT_FOUND"),
    "furnace": ("furnaces", "ERR_FURNACE_NOT_FOUND"),
    "batch": ("batches", "ERR_GLASS_LINING_BATCH_NOT_FOUND"),
    "tank_lot": ("tank_lots", "ERR_TANK_LOT_NOT_FOUND"),
    "inspection": ("inspections", "ERR_LINING_INSPECTION_NOT_FOUND"),
    "model": ("models", "ERR_PRODUCT_MODEL_NOT_FOUND"),
    "test_cell": ("test_cells", "ERR_TEST_CELL_NOT_FOUND"),
    "test": ("tests", "ERR_EFFICIENCY_TEST_NOT_FOUND"),
    "certification": ("certifications", "ERR_RATING_CERTIFICATION_NOT_FOUND"),
    "unit": ("units", "ERR_HEATER_UNIT_NOT_FOUND"),
    "claim": ("claims", "ERR_WARRANTY_CLAIM_NOT_FOUND"),
    "campaign": ("campaigns", "ERR_RECALL_CAMPAIGN_NOT_FOUND"),
    "notice": ("notices", "ERR_RECALL_NOTICE_NOT_FOUND"),
}


def resolve(kind, row_id):
    attr, error_id = TABLES[kind]
    table = getattr(db.db, attr)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def rows(kind):
    attr, _ = TABLES[kind]
    return list(getattr(db.db, attr).values())


def store(kind):
    attr, _ = TABLES[kind]
    return getattr(db.db, attr)


def require_unique(kind, field, value, scope=None):
    """Code uniqueness -- ladder position 23 (ERR_DUPLICATE_CODE)."""
    for row in rows(kind):
        if row.get(field) != value:
            continue
        if scope is not None:
            scope_field, scope_value = scope
            if row.get(scope_field) != scope_value:
                continue
        raise ApiError(
            "ERR_DUPLICATE_CODE", "The value of '%s' is already in use." % field
        )


# --------------------------------------------------------------------------
# Shared containment helpers
# --------------------------------------------------------------------------

def hold_unit(unit, reason_code, invalidate_label):
    """Move a unit to HELD, recording where it must return to."""
    prior = unit["build_status"]
    unit["build_status"] = "HELD"
    unit["hold_reason_code"] = reason_code
    unit["held_from_status"] = prior if prior in ("ASSEMBLED", "LABELED") else None
    if prior == "LABELED" and invalidate_label:
        unit["label_status"] = "INVALID"
    touch(unit)


def restrict_model_if_released(model):
    """Cascade hop 3: recompute held_unit_count and restrict a RELEASED model."""
    if model["release_status"] == "RELEASED" and held_unit_count(model["id"]) > 0:
        model["release_status"] = "RESTRICTED"


# --------------------------------------------------------------------------
# Cascade 1 -- supplier disqualification (3 hops)
# --------------------------------------------------------------------------

def cascade_supplier_disqualification(supplier):
    # Hop 1: block every QUARANTINED or RELEASED lot of the supplier.
    blocked_ids = set()
    lots = [
        lot
        for lot in rows("component_lot")
        if lot["supplier_id"] == supplier["id"]
        and lot["status"] in ("QUARANTINED", "RELEASED")
    ]
    for lot in ordered(lots):
        lot["status"] = "BLOCKED"
        lot["reject_reason_code"] = "SUPPLIER_DISQUALIFIED"
        touch(lot)
        blocked_ids.add(lot["id"])

    # Hop 2: hold every unit still in the plant that references a blocked lot.
    touched_models = []
    if blocked_ids:
        candidates = [
            unit
            for unit in rows("unit")
            if unit["build_status"] in ("COMPONENTS_STAGED", "ASSEMBLED", "LABELED")
            and (
                unit.get("gas_control_lot_id") in blocked_ids
                or unit.get("safety_valve_lot_id") in blocked_ids
            )
        ]
        for unit in ordered(candidates):
            hold_unit(unit, "COMPONENT_LOT_BLOCKED", invalidate_label=True)
            if unit["product_model_id"] not in touched_models:
                touched_models.append(unit["product_model_id"])

    # Hop 3: every model owning a unit held in hop 2 recomputes held_unit_count.
    models = [store("model")[mid] for mid in touched_models if mid in store("model")]
    for model in ordered(models):
        restrict_model_if_released(model)
        touch(model)


# --------------------------------------------------------------------------
# Cascade 2 -- rating-certification revocation (4 hops)
# --------------------------------------------------------------------------

def cascade_certification_revocation(model):
    # Hop 1: the model is decertified and its published ratings are cleared.
    model["certification_status"] = "DECERTIFIED"
    model["uef_rated"] = None
    model["fhr_rated"] = None
    model["recovery_rate_rated"] = None
    model["label_serial_prefix"] = None

    # Hop 2: hold every ASSEMBLED or LABELED unit of the model.
    candidates = [
        unit
        for unit in rows("unit")
        if unit["product_model_id"] == model["id"]
        and unit["build_status"] in ("ASSEMBLED", "LABELED")
    ]
    for unit in ordered(candidates):
        hold_unit(unit, "MODEL_DECERTIFIED", invalidate_label=True)

    # Hop 3: recompute held_unit_count and restrict a RELEASED model.
    restrict_model_if_released(model)

    # Hop 4: void every SCHEDULED efficiency test of the model.
    tests = [
        t
        for t in rows("test")
        if t["product_model_id"] == model["id"] and t["status"] == "SCHEDULED"
    ]
    for test in ordered(tests):
        test["status"] = "VOIDED"
        touch(test)

    touch(model)


# --------------------------------------------------------------------------
# Cascade 3 -- repeated lining failure on one glass-lining batch (hops 2-4)
# --------------------------------------------------------------------------

def cascade_lining_failure(lot, batch):
    """Hops 2 to 4 of the lining-failure chain; hop 1 is applied by the caller."""
    if batch is None:
        return
    # Hop 2: charge the direct rejection to the batch.
    batch["rejected_lot_count"] = batch.get("rejected_lot_count", 0) + 1
    touch(batch)

    # Hop 3: quarantine the batch once two direct rejections are charged to it.
    if batch["rejected_lot_count"] >= 2 and batch["status"] == "FIRED":
        batch["status"] = "QUARANTINED"
        batch["quarantine_reason_code"] = "REPEAT_LINING_FAILURE"

        # Hop 4: sweep every OTHER lot carrying this batch.
        siblings = [
            other
            for other in rows("tank_lot")
            if other["id"] != lot["id"]
            and other.get("glass_lining_batch_id") == batch["id"]
            and other["status"] in ("LINED", "LINING_VERIFIED", "FOAMED")
        ]
        for other in ordered(siblings):
            other["status"] = "LINING_REJECTED"
            other["cascade_rejected"] = True
            other["rework_count"] = other.get("rework_count", 0) + 1
            other["last_scrap_quantity"] = None
            touch(other)


# --------------------------------------------------------------------------
# Cascade 4 -- recall announcement fan-out
# --------------------------------------------------------------------------

def recall_population(campaign):
    """The scoped population, ordered by serial_number ASC."""
    start = campaign.get("serial_range_start")
    end = campaign.get("serial_range_end")
    if start is None or end is None:
        return []
    affected = [
        unit
        for unit in rows("unit")
        if unit["product_model_id"] == campaign["scope_product_model_id"]
        and unit.get("serial_number") is not None
        and start <= unit["serial_number"] <= end
        and unit["build_status"] in ("LABELED", "SHIPPED", "HELD")
    ]
    return sorted(affected, key=lambda u: u["serial_number"])
