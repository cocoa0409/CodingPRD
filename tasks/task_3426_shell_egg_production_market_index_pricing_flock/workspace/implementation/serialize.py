"""Serializers: whitelist exactly the declared public fields per entity
(internal "_" keys never leak). Datetime fields are echoed as stored strings
(raw input strings for input fields, canonical for system-stamped ones).

CustomerCommitment's transition-progress fields are computed fresh on every
read (calculations.commitment_transition_progress).
"""

from calc import commitment_progress


def _pick(ent, fields):
    return {name: ent.get(name) for name in fields}


_COMPLEX_FIELDS = [
    "id", "name", "region_code", "mill_receiving_tons_per_day",
    "biosecurity_posture",
    "corn_inventory_tons", "corn_organic_inventory_tons",
    "soy_inventory_tons", "soy_organic_inventory_tons",
    "ungraded_conventional_dozen", "ungraded_cage_free_dozen",
    "ungraded_organic_dozen",
    "ops_run_index", "last_ops_run_at",
    "created_at", "updated_at", "version",
]

_HOUSE_FIELDS = [
    "id", "complex_id", "house_code", "housing_style", "capacity_hens",
    "hen_inventory", "downtime_until", "created_at", "updated_at", "version",
]

_CERT_FIELDS = [
    "id", "house_id", "program", "auditor_name", "scheduled_date", "status",
    "result", "valid_from", "valid_until", "created_at", "updated_at",
    "version",
]

_FLOCK_FIELDS = [
    "id", "house_id", "flock_code", "program", "ownership", "grower_name",
    "placement_date", "placed_hen_count", "current_hen_count", "age_weeks",
    "molt_count", "molt_start_age_weeks", "status",
    "created_at", "updated_at", "version",
]

_DISEASE_EVENT_FIELDS = [
    "id", "complex_id", "pathogen", "detection_date", "scope_house_ids",
    "status", "confirmed_at", "cleared_at", "created_at", "updated_at",
    "version",
]

_DEPOP_ORDER_FIELDS = [
    "id", "disease_event_id", "house_id", "disposal_method", "downtime_days",
    "status", "completed_at", "created_at", "updated_at", "version",
]

_QUOTATION_FIELDS = [
    "id", "region_code", "size_class", "price_cents_per_dozen",
    "effective_date", "source", "created_at",
]

_CUSTOMER_FIELDS = [
    "id", "name", "segment", "credit_limit_cents", "outstanding_cents",
    "status", "created_at", "updated_at", "version",
]

_COMMITMENT_FIELDS = [
    "id", "customer_id", "program", "region_code", "weekly_dozen_committed",
    "price_adjustment_cents_per_dozen", "effective_from", "effective_to",
    "cage_free_transition_deadline", "required_cage_free_pct",
    "blocked_order_count", "status", "created_at", "updated_at", "version",
]

_ORDER_FIELDS = [
    "id", "commitment_id", "ship_week_start", "dozen_ordered", "size_class",
    "status", "allocated_complex_id", "allocated_dozen",
    "created_at", "updated_at", "version",
]

_SETTLEMENT_FIELDS = [
    "id", "sales_order_id", "ship_week_start", "dozen_shipped", "status",
    "provisional_index_cents", "provisional_unit_price_cents",
    "provisional_total_cents",
    "final_index_average_cents", "final_volume_discount_cents",
    "final_unit_price_cents", "final_total_cents",
    "quotation_ids_used", "disputed_reason",
    "created_at", "updated_at", "version",
]

_FEED_CONTRACT_FIELDS = [
    "id", "complex_id", "commodity", "is_organic_certified", "total_tons",
    "received_tons", "basis_cents_per_ton", "spot_reference_cents_per_ton",
    "hedged_tons", "hedge_futures_cents_per_ton", "hedged_applied_tons",
    "total_cost_cents", "average_received_cost_cents_per_ton",
    "delivery_start", "delivery_end", "status",
    "created_at", "updated_at", "version",
]

_FEED_BATCH_FIELDS = [
    "id", "complex_id", "program", "corn_tons", "soybean_tons",
    "tons_produced", "blended_cost_cents_per_ton",
    "actual_cost_per_dozen_cents", "standard_cost_per_dozen_cents",
    "created_at", "updated_at", "version",
]

_PACKING_RUN_FIELDS = [
    "id", "complex_id", "program", "dozen_input", "run_date",
    "cases_by_size", "total_cases", "status",
    "created_at", "updated_at", "version",
]

_CAPITAL_PROJECT_FIELDS = [
    "id", "commitment_id", "house_id", "investment_cents", "target_style",
    "construction_weeks", "construction_started_at", "commissioned_at",
    "status", "created_at", "updated_at", "version",
]


def serialize_complex(ent):
    return _pick(ent, _COMPLEX_FIELDS)


def serialize_house(ent):
    return _pick(ent, _HOUSE_FIELDS)


def serialize_certification(ent):
    return _pick(ent, _CERT_FIELDS)


def serialize_flock(ent):
    return _pick(ent, _FLOCK_FIELDS)


def serialize_disease_event(ent):
    return _pick(ent, _DISEASE_EVENT_FIELDS)


def serialize_depop_order(ent):
    return _pick(ent, _DEPOP_ORDER_FIELDS)


def serialize_quotation(ent):
    return _pick(ent, _QUOTATION_FIELDS)


def serialize_customer(ent):
    return _pick(ent, _CUSTOMER_FIELDS)


def serialize_commitment(ent):
    out = _pick(ent, _COMMITMENT_FIELDS)
    required, achieved, on_track = commitment_progress(ent)
    out["required_conversion_hens"] = required
    out["achieved_conversion_hens"] = achieved
    out["transition_on_track"] = on_track
    return out


def serialize_order(ent):
    return _pick(ent, _ORDER_FIELDS)


def serialize_settlement(ent):
    return _pick(ent, _SETTLEMENT_FIELDS)


def serialize_feed_contract(ent):
    return _pick(ent, _FEED_CONTRACT_FIELDS)


def serialize_feed_batch(ent):
    return _pick(ent, _FEED_BATCH_FIELDS)


def serialize_packing_run(ent):
    return _pick(ent, _PACKING_RUN_FIELDS)


def serialize_capital_project(ent):
    return _pick(ent, _CAPITAL_PROJECT_FIELDS)
