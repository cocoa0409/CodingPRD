"""Entity serialization.

Field sets are read from the SCAFFOLD.yaml entity table. Rows carrying the
common field set expose id / created_at / updated_at / version; the five
lightweight rows (ClockTick, SupplierAvailabilityReport, CurationReviewItem,
ItemAttribute, ItemCrossReference) expose only id and created_at (PRD 2.4).
"""

from common import out_iso

COMMON = ("id", "created_at", "updated_at", "version")
LIGHT = ("id", "created_at")


def _pick(record, fields, extra=None):
    out = {}
    for field in fields:
        if field in record:
            out[field] = record[field]
    if extra:
        for field in extra:
            if field in record:
                out[field] = record[field]
    return out


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def serialize(record, fields, common=True):
    out = _pick(record, COMMON if common else LIGHT)
    for field in fields:
        if field in record:
            out[field] = _clean(record[field])
    return out


# ------------------------------------------------------------ field lists

DC_FIELDS = ("code", "region", "local_zone", "local_cutoff_time", "local_current_time",
             "utc_offset_minutes", "inbound_capacity_units", "transit_seconds",
             "cutoff_passed", "cutoff_sequence_index", "inbound_reserved_units",
             "operations_posture")

SUPPLIER_FIELDS = ("supplier_name", "home_dc_id", "primary_attribute_name",
                   "primary_attribute_value", "long_tail_authorized",
                   "min_stock_commitment_units", "commitment_breach_count",
                   "performance_rating_units")

AVAILABILITY_REPORT_FIELDS = ("supplier_id", "item_id", "reported_available_units")

CURATION_REVIEW_FIELDS = ("curator_id", "review_status", "bundle_level_revision",
                          "approved_count", "revision_round_baseline")

CURATION_REVIEW_ITEM_FIELDS = ("review_id", "item_id", "item_level_revision",
                               "item_attribute_counter")

ITEM_FIELDS = ("sku", "description", "material_spec", "long_tail", "catalog_status",
               "unit_price_cents", "unit_weight_kg", "curated_dimension_json",
               "curation_bundle_size", "curation_review_state",
               "curation_last_reviewed_by")

ATTRIBUTE_FIELDS = ("item_id", "attribute_name", "attribute_value", "unit_of_measure")

CROSS_REFERENCE_FIELDS = ("item_id", "referenced_manufacturer", "referenced_part_number",
                          "compatibility_note")

STOCK_FIELDS = ("item_id", "dc_id", "account_id", "on_hand_units", "reserved_units",
                "available_units", "daily_demand_units", "inbound_daily_units",
                "positioning_flag")

ACCOUNT_FIELDS = ("account_name", "delivery_zone", "home_region", "open_claim_count")

ORDER_FIELDS = ("account_id", "order_status", "fulfillment_status", "line_count",
                "total_small_line_fee_cents", "order_total_cents", "allocated_dc_id",
                "same_day_committed", "commit_minutes_before_cutoff",
                "damage_claim_count", "freight_charge_cents")

ORDER_LINE_FIELDS = ("order_id", "item_id", "quantity", "allocated_dc_id",
                     "allocated_units", "is_small_line", "line_subtotal_cents",
                     "allocated_small_line_fee_cents", "line_total_cents",
                     "line_status", "returned_units", "restocked_units",
                     "damaged_units", "return_friction_units")

PICK_TASK_FIELDS = ("order_id", "line_id", "dc_id", "requested_units", "picked_units",
                    "shortage_units", "shortage_disposition", "pick_status")

SHIPMENT_FIELDS = ("order_id", "dc_id", "shipment_status", "cutoff_sequence_index",
                   "service_level", "billable_weight_kg", "freight_rate_cents",
                   "freight_surcharge_cents", "freight_charge_cents",
                   "promised_delivery_by")

RETURN_FIELDS = ("order_id", "dc_id", "return_status", "restock_units", "damaged_units")

DAMAGE_CLAIM_FIELDS = ("order_id", "line_id", "claim_units", "damage_value_cents",
                       "claim_status", "disposition")

SQUARE_REQUEST_FIELDS = ("account_id", "request_status", "committed_length_feet",
                         "committed_variant", "prior_committed_length_feet")

SQUARE_LINE_FIELDS = ("request_id", "cut_list_ordinal", "requested_feet",
                      "line_status", "line_committed_feet")


def dc(record):
    data = serialize(record, DC_FIELDS)
    data["local_current_time"] = record.get("local_current_time", "00:00:00")
    return data


def supplier(record):
    return serialize(record, SUPPLIER_FIELDS)


def availability_report(record):
    return serialize(record, AVAILABILITY_REPORT_FIELDS, common=False)


def curation_review(record):
    return serialize(record, CURATION_REVIEW_FIELDS)


def curation_review_item(record):
    return serialize(record, CURATION_REVIEW_ITEM_FIELDS, common=False)


def catalog_item(record, availability=None):
    data = serialize(record, ITEM_FIELDS)
    if availability is not None:
        data["live_availability_at_dc"] = availability
    return data


def item_attribute(record):
    return serialize(record, ATTRIBUTE_FIELDS, common=False)


def item_cross_reference(record):
    return serialize(record, CROSS_REFERENCE_FIELDS, common=False)


def stock(record):
    data = serialize(record, STOCK_FIELDS)
    data["available_units"] = record.get("on_hand_units", 0) - record.get("reserved_units", 0)
    return data


def account(record):
    return serialize(record, ACCOUNT_FIELDS)


def order(record):
    return serialize(record, ORDER_FIELDS)


def order_line(record):
    data = serialize(record, ORDER_LINE_FIELDS)
    data["return_friction_units"] = record.get("return_friction_units", 0)
    return data


def pick_task(record):
    return serialize(record, PICK_TASK_FIELDS)


def shipment(record):
    data = serialize(record, SHIPMENT_FIELDS)
    data["promised_delivery_by"] = out_iso(record.get("promised_delivery_by"))
    return data


def return_authorization(record):
    return serialize(record, RETURN_FIELDS)


def damage_claim(record):
    return serialize(record, DAMAGE_CLAIM_FIELDS)


def square_request(record):
    return serialize(record, SQUARE_REQUEST_FIELDS)


def square_line(record):
    return serialize(record, SQUARE_LINE_FIELDS)