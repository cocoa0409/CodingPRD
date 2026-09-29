"""Representation builders.

Every entity has an explicit field list: internal bookkeeping keys such as
_seq never leak, and OptionPayment carries neither updated_at nor version
(PRD section 2.4).
"""

from util import fmt_dt, num

COMMON_TAIL = ("created_at", "updated_at", "version")


def _dt(value):
    return fmt_dt(value) if value is not None else None


def _n(value):
    return num(value) if value is not None else None


def _i(value):
    return int(value) if value is not None else None


def _common(row, out):
    out["created_at"] = _dt(row["created_at"])
    out["updated_at"] = _dt(row["updated_at"])
    out["version"] = int(row["version"])
    return out


def landowner(row):
    return _common(row, {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "entity_type": row["entity_type"],
        "mailing_state": row["mailing_state"],
        "contact_email": row["contact_email"],
        "w9_on_file": bool(row["w9_on_file"]),
        "payment_hold": bool(row["payment_hold"]),
        "status": row["status"],
        "total_paid_cents": _i(row["total_paid_cents"]),
    })


def parcel(row):
    return _common(row, {
        "id": row["id"],
        "apn": row["apn"],
        "county_fips": row["county_fips"],
        "landowner_id": row["landowner_id"],
        "gross_acres": _n(row["gross_acres"]),
        "interconnection_distance_km": _n(row["interconnection_distance_km"]),
        "resource_capacity_factor": _n(row["resource_capacity_factor"]),
        "slope_pct": _n(row["slope_pct"]),
        "title_condition_grade": row["title_condition_grade"],
        "zoning_code": row["zoning_code"],
        "screen_mode": row["screen_mode"],
        "screening_score": _n(row["screening_score"]),
        "screening_tier": row["screening_tier"],
        "slope_excluded_acres": _n(row["slope_excluded_acres"]),
        "raw_setback_acres": _n(row["raw_setback_acres"]),
        "consent_released_acres": _n(row["consent_released_acres"]),
        "setback_encumbered_acres": _n(row["setback_encumbered_acres"]),
        "buildable_acres": _n(row["buildable_acres"]),
        "blocking_curative_open_count": _i(row["blocking_curative_open_count"]),
        "waived_blocking_count": _i(row["waived_blocking_count"]),
        "curative_cost_cents": _i(row["curative_cost_cents"]),
        "status": row["status"],
    })


def setback_rule(row):
    return _common(row, {
        "id": row["id"],
        "jurisdiction_code": row["jurisdiction_code"],
        "rule_type": row["rule_type"],
        "setback_feet": _i(row["setback_feet"]),
        "encumbrance_rate_per_acre": _n(row["encumbrance_rate_per_acre"]),
        "consent_waivable": bool(row["consent_waivable"]),
    })


def consent(row):
    return _common(row, {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "setback_rule_id": row["setback_rule_id"],
        "neighbor_name": row["neighbor_name"],
        "consent_expiry_days": _i(row["consent_expiry_days"]),
        "requested_at": _dt(row["requested_at"]),
        "consent_expiry_at": _dt(row["consent_expiry_at"]),
        "granted_at": _dt(row["granted_at"]),
        "revoked_at": _dt(row["revoked_at"]),
        "released_acres": _n(row["released_acres"]),
        "status": row["status"],
    })


def curative_item(row):
    return _common(row, {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "blocks_item_id": row["blocks_item_id"],
        "item_type": row["item_type"],
        "severity": row["severity"],
        "curative_cost_cents": _i(row["curative_cost_cents"]),
        "created_by_user_id": row["created_by_user_id"],
        "cleared_by_user_id": row["cleared_by_user_id"],
        "cleared_at": _dt(row["cleared_at"]),
        "waiver_note": row["waiver_note"],
        "status": row["status"],
    })


def option_agreement(row):
    return _common(row, {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "landowner_id": row["landowner_id"],
        "option_term_days": _i(row["option_term_days"]),
        "option_fee_per_acre_cents": _i(row["option_fee_per_acre_cents"]),
        "extension_count_allowed": _i(row["extension_count_allowed"]),
        "extension_fee_per_acre_cents": _i(row["extension_fee_per_acre_cents"]),
        "rent_structure_type": row["rent_structure_type"],
        "base_rent_per_acre_cents": _i(row["base_rent_per_acre_cents"]),
        "royalty_rate_bps": _i(row["royalty_rate_bps"]),
        "escalator_pct_bps": _i(row["escalator_pct_bps"]),
        "escalator_mode": row["escalator_mode"],
        "round_index": _i(row["round_index"]),
        "executed_at": _dt(row["executed_at"]),
        "executed_by_user_id": row["executed_by_user_id"],
        "option_expiry_at": _dt(row["option_expiry_at"]),
        "extensions_used": _i(row["extensions_used"]),
        "total_option_paid_cents": _i(row["total_option_paid_cents"]),
        "exercised_at": _dt(row["exercised_at"]),
        "withdraw_reason": row["withdraw_reason"],
        "status": row["status"],
    })


def option_payment(row):
    """No updated_at and no version: the ledger row is immutable."""
    return {
        "id": row["id"],
        "option_agreement_id": row["option_agreement_id"],
        "sequence_no": _i(row["sequence_no"]),
        "payment_kind": row["payment_kind"],
        "ledger_direction": row["ledger_direction"],
        "amount_cents": _i(row["amount_cents"]),
        "acres_basis": _n(row["acres_basis"]),
        "created_at": _dt(row["created_at"]),
    }


def corridor(row):
    return _common(row, {
        "id": row["id"],
        "route_name": row["route_name"],
        "total_length_m": _i(row["total_length_m"]),
        "voltage_class": row["voltage_class"],
        "buffer_m": _i(row["buffer_m"]),
        "permitted_at": _dt(row["permitted_at"]),
        "granted_crossing_count": _i(row["granted_crossing_count"]),
        "status": row["status"],
    })


def crossing(row):
    return _common(row, {
        "id": row["id"],
        "corridor_id": row["corridor_id"],
        "parcel_id": row["parcel_id"],
        "crossing_kind": row["crossing_kind"],
        "station_start_m": _i(row["station_start_m"]),
        "station_end_m": _i(row["station_end_m"]),
        "occupancy_window_start": _dt(row["occupancy_window_start"]),
        "occupancy_window_end": _dt(row["occupancy_window_end"]),
        "occupied_m": _i(row["occupied_m"]),
        "duration_days": _i(row["duration_days"]),
        "long_occupancy_surcharge_bps": _i(row["long_occupancy_surcharge_bps"]),
        "compensation_cents": _i(row["compensation_cents"]),
        "granted_at": _dt(row["granted_at"]),
        "status": row["status"],
    })


def booking(row):
    return _common(row, {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "purpose": row["purpose"],
        "window_start": _dt(row["window_start"]),
        "window_end": _dt(row["window_end"]),
        "crew_count": _i(row["crew_count"]),
        "cancelled_at": _dt(row["cancelled_at"]),
        "status": row["status"],
    })


def lease(row):
    return _common(row, {
        "id": row["id"],
        "option_agreement_id": row["option_agreement_id"],
        "parcel_id": row["parcel_id"],
        "landowner_id": row["landowner_id"],
        "exercise_notice_reference": row["exercise_notice_reference"],
        "term_start_date": _dt(row["term_start_date"]),
        "term_years": _i(row["term_years"]),
        "acre_basis_at_exercise": _n(row["acre_basis_at_exercise"]),
        "gross_security_cents": _i(row["gross_security_cents"]),
        "admin_rate_bps": _i(row["admin_rate_bps"]),
        "admin_loading_cents": _i(row["admin_loading_cents"]),
        "total_security_required_cents": _i(row["total_security_required_cents"]),
        "security_posted_cents": _i(row["security_posted_cents"]),
        "memo_submitted_at": _dt(row["memo_submitted_at"]),
        "recorded_at": _dt(row["recorded_at"]),
        "recording_instrument_no": row["recording_instrument_no"],
        "last_paid_invoice_year": _i(row["last_paid_invoice_year"]),
        "rent_status": row["rent_status"],
        "recording_status": row["recording_status"],
    })


def invoice(row):
    return _common(row, {
        "id": row["id"],
        "lease_agreement_id": row["lease_agreement_id"],
        "period_year": _i(row["period_year"]),
        "production_mwh": _n(row["production_mwh"]),
        "rent_variant": row["rent_variant"],
        "acre_basis": _n(row["acre_basis"]),
        "per_acre_component_cents": _i(row["per_acre_component_cents"]),
        "royalty_component_cents": _i(row["royalty_component_cents"]),
        "gross_rent_cents": _i(row["gross_rent_cents"]),
        "issued_at": _dt(row["issued_at"]),
        "due_at": _dt(row["due_at"]),
        "paid_at": _dt(row["paid_at"]),
        "paid_amount_cents": _i(row["paid_amount_cents"]),
        "void_reason": row["void_reason"],
        "status": row["status"],
    })


def many(fn, rows):
    return [fn(r) for r in rows]
