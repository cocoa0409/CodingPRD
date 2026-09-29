"""Shared rungs of the ladder: existence, uniqueness, state and the posture gate."""
from errors import ApiError
from store import db, by_seq

FAMILY_404 = {
    "plants": "ERR_PLANT_NOT_FOUND",
    "trains": "ERR_TRAIN_NOT_FOUND",
    "charges": "ERR_CATALYST_CHARGE_NOT_FOUND",
    "lots": "ERR_HEDGE_LOT_NOT_FOUND",
    "lines": "ERR_PRODUCT_LINE_NOT_FOUND",
    "runs": "ERR_RUN_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "assets": "ERR_STORAGE_ASSET_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "quotes": "ERR_QUOTE_NOT_FOUND",
    "turnarounds": "ERR_TURNAROUND_NOT_FOUND",
    "tasks": "ERR_TASK_NOT_FOUND",
    "readings": "ERR_EMISSIONS_READING_NOT_FOUND",
}


def load(family, row_id):
    """Resolve an identifier to a row, or raise the family's own 404."""
    row = getattr(db, family).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(FAMILY_404[family])
    return row


def duplicate(family, field, value, scope=None, extra=None):
    """Rung 8: a business code colliding inside its declared uniqueness scope.

    `scope` is an (attribute, value) pair for the parent the code is scoped to;
    `extra` is an optional predicate for scopes that are not a single column.
    """
    for row in getattr(db, family).values():
        if row.get(field) != value:
            continue
        if scope is not None and row.get(scope[0]) != scope[1]:
            continue
        if extra is not None and not extra(row):
            continue
        raise ApiError("ERR_DUPLICATE_CODE")


def state(condition, error_id="ERR_INVALID_STATE", message=None):
    if not condition:
        raise ApiError(error_id, message)


def not_frozen(plant):
    """Rung 10. The governing plant's posture is re-derived before the test."""
    import calc
    if calc.operating_posture(plant) == "FROZEN":
        raise ApiError("ERR_PLANT_FROZEN")


def filtered(family, filters):
    """Rows of a family matching every (field, value) filter, created_at ASC."""
    rows = getattr(db, family).values()
    for field, value in filters:
        if value is None:
            continue
        rows = [r for r in rows if r.get(field) == value]
    return by_seq(list(rows))
