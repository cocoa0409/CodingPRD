"""Wire representations. Derived fields are recomputed here, on every read."""

import calc
import derive
import util
from store import db


def _ts(value):
    return util.format_instant(value)


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": _ts(rec["created_at"]),
        "updated_at": _ts(rec["updated_at"]),
        "version": rec["version"],
    }


def operator(rec):
    out = _common(rec)
    out.update({
        "legal_name": rec["legal_name"],
        "operator_type": rec["operator_type"],
        "aoc_number": rec["aoc_number"],
        "home_base_icao": rec["home_base_icao"],
        "policy_count": derive.operator_policy_count(rec["id"]),
    })
    return out


def aircraft(rec):
    out = _common(rec)
    out.update({
        "registration_mark": rec["registration_mark"],
        "aircraft_class": rec["aircraft_class"],
        "manufacture_year": rec["manufacture_year"],
        "hull_new_value_cents": rec["hull_new_value_cents"],
        "seat_count": rec["seat_count"],
        "max_takeoff_weight_kg": rec["max_takeoff_weight_kg"],
        "current_depreciated_value_cents": calc.depreciated_hull_value(rec, db.clock.year),
    })
    return out


def pilot(rec):
    now = db.clock
    logged = calc.pilot_logged_score(rec, now)
    verified = calc.pilot_verified_score(rec, now)
    out = _common(rec)
    out.update({
        "pilot_name": rec["pilot_name"],
        "license_type": rec["license_type"],
        "total_logged_hours": rec["total_logged_hours"],
        "hours_on_type": rec["hours_on_type"],
        "instrument_rated": rec["instrument_rated"],
        "last_training_completed_at": _ts(rec["last_training_completed_at"]),
        "medical_expires_at": _ts(rec["medical_expires_at"]),
        "verified_total_hours": rec["verified_total_hours"],
        "verified_hours_on_type": rec["verified_hours_on_type"],
        "verified_at": _ts(rec["verified_at"]),
        "qualification_score_logged": logged,
        "rating_band_logged": calc.band_from_score(logged),
        "qualification_score_verified": verified,
        "rating_band_verified": calc.band_from_score(verified) if verified is not None else None,
    })
    return out


def policy(rec):
    pid = rec["id"]
    out = _common(rec)
    out.update({
        "operator_id": rec["operator_id"],
        "policy_number": rec["policy_number"],
        "policy_type": rec["policy_type"],
        "status": rec["status"],
        "effective_from": _ts(rec["effective_from"]),
        "effective_to": _ts(rec["effective_to"]),
        "term_days": rec["term_days"],
        "territorial_limit_code": rec["territorial_limit_code"],
        "permitted_use_classes": list(rec["permitted_use_classes"]),
        "base_hull_rate_ppm": rec["base_hull_rate_ppm"],
        "hull_deductible_ppm": rec["hull_deductible_ppm"],
        "liability_limit_cents": rec["liability_limit_cents"],
        "hull_aggregate_limit_cents": rec["hull_aggregate_limit_cents"],
        "premises_liability_extension": rec["premises_liability_extension"],
        "product_liability_extension": rec["product_liability_extension"],
        "automatic_acquisition_enabled": rec["automatic_acquisition_enabled"],
        "acquisition_reporting_days": rec["acquisition_reporting_days"],
        "war_risk_required": rec["war_risk_required"],
        "total_hull_sum_insured_cents": derive.total_hull_sum_insured(pid),
        "written_premium_cents": derive.written_premium(pid),
        "outstanding_reserve_cents": derive.outstanding_reserve(pid),
        "paid_hull_cents": derive.paid_hull(pid),
        "live_schedule_count": derive.live_schedule_count(pid),
    })
    return out


def schedule(rec):
    out = _common(rec)
    out.update({
        "policy_id": rec["policy_id"],
        "aircraft_id": rec["aircraft_id"],
        "named_pilot_id": rec["named_pilot_id"],
        "use_class": rec["use_class"],
        "agreed_value_cents": rec["agreed_value_cents"],
        "effective_from": _ts(rec["effective_from"]),
        "effective_to": _ts(rec["effective_to"]),
        "coverage_status": rec["coverage_status"],
        "warranty_status": rec["warranty_status"],
        "warranty_basis": rec["warranty_basis"],
        "warranted_min_total_hours": rec["warranted_min_total_hours"],
        "warranted_min_hours_on_type": rec["warranted_min_hours_on_type"],
        "rated_pilot_band": rec["rated_pilot_band"],
        "rate_ppm": rec["rate_ppm"],
        "hull_premium_cents": rec["hull_premium_cents"],
        "acquisition_source": rec["acquisition_source"],
        "reported_declaration_id": rec["reported_declaration_id"],
        "warranty_breach_reason": rec["warranty_breach_reason"],
    })
    return out


def endorsement(rec):
    out = _common(rec)
    out.update({
        "policy_id": rec["policy_id"],
        "endorsement_type": rec["endorsement_type"],
        "status": rec["status"],
        "effective_date": _ts(rec["effective_date"]),
        "target_schedule_id": rec["target_schedule_id"],
        "aircraft_id": rec["aircraft_id"],
        "named_pilot_id": rec["named_pilot_id"],
        "new_agreed_value_cents": rec["new_agreed_value_cents"],
        "new_use_class": rec["new_use_class"],
        "territory_code": rec["territory_code"],
        "exposure_member_count": rec["exposure_member_count"],
        "per_seat_limit_cents": rec["per_seat_limit_cents"],
        "quote_round": rec["quote_round"],
        "quoted_premium_delta_cents": rec["quoted_premium_delta_cents"],
        "premium_delta_cents": rec["premium_delta_cents"],
        "quoted_by_user_id": rec["quoted_by_user_id"],
        "referral_reason": rec["referral_reason"],
        "void_reason": rec["void_reason"],
    })
    return out


def market(rec):
    committed = derive.committed_line(rec["id"])
    out = _common(rec)
    out.update({
        "market_name": rec["market_name"],
        "aggregate_line_cents": rec["aggregate_line_cents"],
        "perils_offered": rec["perils_offered"],
        "committed_line_cents": committed,
        "available_line_cents": rec["aggregate_line_cents"] - committed,
    })
    return out


def placement(rec):
    out = _common(rec)
    out.update({
        "policy_id": rec["policy_id"],
        "market_id": rec["market_id"],
        "war_hull_line_cents": rec["war_hull_line_cents"],
        "perils_scope": rec["perils_scope"],
        "coverage_from": _ts(rec["coverage_from"]),
        "coverage_to": _ts(rec["coverage_to"]),
        "status": rec["status"],
        "premium_cents": rec["premium_cents"],
        "cancellation_reason": rec["cancellation_reason"],
    })
    return out


def claim(rec):
    out = _common(rec)
    out.update({
        "policy_id": rec["policy_id"],
        "schedule_id": rec["schedule_id"],
        "loss_date": _ts(rec["loss_date"]),
        "loss_type": rec["loss_type"],
        "loss_description": rec["loss_description"],
        "adjustment_status": rec["adjustment_status"],
        "salvage_status": rec["salvage_status"],
        "cooperation_status": rec["cooperation_status"],
        "investigator_reference": rec["investigator_reference"],
        "reserve_cents": rec["reserve_cents"],
        "ctl_ratio_ppm": rec["ctl_ratio_ppm"],
        "ctl_flag": rec["ctl_flag"],
        "assessment_count": rec["assessment_count"],
        "settlement_basis": rec["settlement_basis"],
        "settlement_amount_cents": rec["settlement_amount_cents"],
        "deductible_applied_cents": rec["deductible_applied_cents"],
        "salvage_proceeds_cents": rec["salvage_proceeds_cents"],
        "coverage_decided_by_user_id": rec["coverage_decided_by_user_id"],
        "denial_reason": rec["denial_reason"],
    })
    return out


def assessment(rec):
    return {
        "id": rec["id"],
        "created_at": _ts(rec["created_at"]),
        "claim_id": rec["claim_id"],
        "repair_cost_estimate_cents": rec["repair_cost_estimate_cents"],
        "assessor_reference": rec["assessor_reference"],
        "assessed_at": _ts(rec["assessed_at"]),
        "ctl_ratio_ppm": rec["ctl_ratio_ppm"],
        "verdict": rec["verdict"],
    }


def transaction(rec):
    return {
        "id": rec["id"],
        "created_at": _ts(rec["created_at"]),
        "policy_id": rec["policy_id"],
        "endorsement_id": rec["endorsement_id"],
        "txn_type": rec["txn_type"],
        "amount_cents": rec["amount_cents"],
        "effective_date": _ts(rec["effective_date"]),
        "basis": rec["basis"],
        "memo": rec["memo"],
    }


def declaration(rec):
    out = _common(rec)
    out.update({
        "policy_id": rec["policy_id"],
        "period_from": _ts(rec["period_from"]),
        "period_to": _ts(rec["period_to"]),
        "status": rec["status"],
        "declared_count": rec["declared_count"],
        "declared_premium_cents": rec["declared_premium_cents"],
        "late_flag": rec["late_flag"],
        "late_loading_cents": rec["late_loading_cents"],
        "reported_schedule_ids": list(rec["reported_schedule_ids"]),
        "rejection_reason": rec["rejection_reason"],
    })
    return out


def many(fn, rows):
    return [fn(r) for r in rows]
