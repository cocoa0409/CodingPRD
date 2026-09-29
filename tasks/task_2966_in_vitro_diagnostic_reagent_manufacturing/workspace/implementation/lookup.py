"""Rung 40 (path existence, resolved left to right) and rung 45 (body foreign
key existence, in the order the fields are declared on the owning entity)."""

from errors import ApiError
from store import db

_NOT_FOUND = {
    "material_specifications": "ERR_MATERIAL_SPECIFICATION_NOT_FOUND",
    "material_lots": "ERR_MATERIAL_LOT_NOT_FOUND",
    "product_specifications": "ERR_PRODUCT_SPECIFICATION_NOT_FOUND",
    "design_control_records": "ERR_DESIGN_CONTROL_RECORD_NOT_FOUND",
    "reagent_lots": "ERR_REAGENT_LOT_NOT_FOUND",
    "fill_runs": "ERR_FILL_RUN_NOT_FOUND",
    "test_results": "ERR_TEST_RESULT_NOT_FOUND",
    "stability_studies": "ERR_STABILITY_STUDY_NOT_FOUND",
    "bridging_studies": "ERR_BRIDGING_STUDY_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
    "distribution_orders": "ERR_DISTRIBUTION_ORDER_NOT_FOUND",
    "allocations": "ERR_ALLOCATION_NOT_FOUND",
}


def _resolve(collection_name, row_id):
    collection = getattr(db, collection_name)
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection_name])
    return row


def material_specification(row_id):
    return _resolve("material_specifications", row_id)


def material_lot(row_id):
    return _resolve("material_lots", row_id)


def product_specification(row_id):
    return _resolve("product_specifications", row_id)


def design_control_record(row_id):
    return _resolve("design_control_records", row_id)


def reagent_lot(row_id):
    return _resolve("reagent_lots", row_id)


def fill_run(row_id):
    return _resolve("fill_runs", row_id)


def test_result(row_id):
    return _resolve("test_results", row_id)


def stability_study(row_id):
    return _resolve("stability_studies", row_id)


def bridging_study(row_id):
    return _resolve("bridging_studies", row_id)


def complaint(row_id):
    return _resolve("complaints", row_id)


def distribution_order(row_id):
    return _resolve("distribution_orders", row_id)


def allocation(row_id):
    return _resolve("allocations", row_id)
