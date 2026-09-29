"""Serialized shapes: exactly the fields each PRD section declares."""

import calc

PROPERTY = ("id", "created_at", "updated_at", "version", "code", "name",
            "currency_code", "overbooking_pct_bp", "booking_horizon_days",
            "mix_window_days", "rate_mismatch_tolerance_cents",
            "required_image_count")

ROOM_TYPE = ("id", "created_at", "updated_at", "version", "property_id", "code",
             "name", "physical_capacity_units", "overbooking_pct_bp",
             "master_description_hash", "master_image_count")

INVENTORY_DAY = ("id", "created_at", "updated_at", "version", "room_type_id",
                 "stay_date", "physical_capacity_units",
                 "overbooking_ceiling_units", "allocated_units",
                 "shared_pool_units", "committed_units", "pooled_state")

CHANNEL = ("id", "created_at", "updated_at", "version", "property_id", "code",
           "channel_kind", "commission_bp", "sell_adjustment_bp",
           "allows_member_rate", "allows_opaque_rate", "geo_market_codes",
           "requires_content_parity", "gross_revenue_cents",
           "commission_accrued_cents", "net_revenue_cents", "room_nights_sold",
           "bookings_count", "cancellations_count", "mismatch_alert_count")

CONNECTION = ("id", "created_at", "updated_at", "version", "channel_id",
              "protocol", "endpoint_url", "heartbeat_interval_minutes",
              "connection_state", "consecutive_failures", "last_heartbeat_at",
              "last_failure_code", "suspended_at")

FREEZE_WINDOW = ("id", "created_at", "connection_id", "starts_at", "ends_at",
                 "reason", "effective_starts_at")

RATE_PLAN = ("id", "created_at", "updated_at", "version", "property_id", "code",
             "rate_class", "parent_rate_plan_id", "base_amount_cents",
             "offset_kind", "offset_bp", "offset_amount_cents",
             "floor_amount_cents", "ceiling_amount_cents",
             "package_inclusion_cents", "member_only", "negotiated_account_code",
             "plan_state", "derivation_depth", "resolved_base_amount_cents")

MAPPING = ("id", "created_at", "updated_at", "version", "rate_plan_id",
           "channel_id", "room_type_id", "external_rate_code", "mapping_state",
           "content_description_hash", "content_image_count", "parity_state",
           "last_push_at", "last_pushed_rate_cents", "observed_rate_cents",
           "observed_stay_date", "mismatch_state", "mismatch_delta_cents")

ALLOCATION = ("id", "created_at", "updated_at", "version", "room_type_id",
              "channel_id", "allocated_units", "start_date", "end_date",
              "consumed_units", "allocation_state", "superseded_at",
              "recalled_at")

RESTRICTION = ("id", "created_at", "updated_at", "version", "room_type_id",
               "rate_plan_id", "restriction_type", "start_date", "end_date",
               "value_nights", "origin", "restriction_state", "lifted_at",
               "lift_reason")

PROMOTION = ("id", "created_at", "updated_at", "version", "rate_plan_id", "code",
             "promo_kind", "discount_kind", "discount_bp",
             "discount_amount_cents", "start_date", "end_date",
             "geo_market_codes", "approval_status", "distribution_status",
             "submitted_by_user_id", "approved_by_user_id", "reject_reason",
             "revision_count")

BATCH = ("id", "created_at", "updated_at", "version", "property_id",
         "payload_kind", "source_ref_kind", "source_ref_id", "batch_state",
         "total_jobs", "applied_jobs", "rejected_jobs", "abandoned_jobs",
         "dispatched_at")

JOB = ("id", "created_at", "updated_at", "version", "batch_id",
       "channel_mapping_id", "sequence_index", "payload_kind",
       "payload_rate_cents", "job_state", "attempt_count", "failure_reason",
       "applied_at")

RESERVATION = ("id", "created_at", "updated_at", "version", "property_id",
               "channel_id", "rate_plan_id", "room_type_id", "arrival_date",
               "nights", "departure_date", "member_flag", "geo_market_code",
               "negotiated_account_code", "override_overbooking",
               "reservation_state", "nightly_breakdown", "gross_amount_cents",
               "commission_amount_cents", "net_amount_cents",
               "loyalty_credit_cents", "overbooking_overridden", "cancelled_at")


def pick(rec, fields):
    return {name: rec.get(name) for name in fields}


def property_out(rec):
    return pick(rec, PROPERTY)


def room_type_out(rec):
    out = pick(rec, ROOM_TYPE)
    out["effective_overbooking_pct_bp"] = calc.effective_overbooking_bp(rec)
    return out


def inventory_day_out(rec):
    return pick(rec, INVENTORY_DAY)


def channel_out(rec):
    return pick(rec, CHANNEL)


def connection_out(rec):
    return pick(rec, CONNECTION)


def freeze_window_out(rec):
    return pick(rec, FREEZE_WINDOW)


def rate_plan_out(rec):
    return pick(rec, RATE_PLAN)


def mapping_out(rec):
    return pick(rec, MAPPING)


def allocation_out(rec):
    return pick(rec, ALLOCATION)


def restriction_out(rec):
    return pick(rec, RESTRICTION)


def promotion_out(rec):
    return pick(rec, PROMOTION)


def batch_out(rec):
    return pick(rec, BATCH)


def job_out(rec):
    return pick(rec, JOB)


def reservation_out(rec):
    out = pick(rec, RESERVATION)
    out["nightly_breakdown"] = [dict(night) for night in rec["nightly_breakdown"]]
    return out


def many(fn, records):
    return [fn(rec) for rec in records]
