"""Serializers: internal dict -> wire format. Timestamps via iso_from_ts."""
from response import iso_from_ts


def automaker_view(e):
    return {
        "id": e["id"],
        "oem_code": e["oem_code"],
        "name": e["name"],
        "feed_contact_email": e["feed_contact_email"],
        "status": e["status"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def dealer_view(e):
    return {
        "id": e["id"],
        "dealer_code": e["dealer_code"],
        "name": e["name"],
        "used_program_enrolled": e["used_program_enrolled"],
        "used_program_enrolled_at": iso_from_ts(e["used_program_enrolled_at"]),
        "status": e["status"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def customer_view(e):
    return {
        "id": e["id"],
        "email": e["email"],
        "full_name": e["full_name"],
        "status": e["status"],
        "household_size": e["household_size"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def vehicle_view(e):
    return {
        "id": e["id"],
        "vin": e["vin"],
        "automaker_id": e["automaker_id"],
        "model_year": e["model_year"],
        "owner_customer_id": e["owner_customer_id"],
        "condition": e["condition"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def radio_view(e):
    return {
        "id": e["id"],
        "esn": e["esn"],
        "vehicle_id": e["vehicle_id"],
        "hardware_generation": e["hardware_generation"],
        "activation_status": e["activation_status"],
        "last_signal_at": iso_from_ts(e["last_signal_at"]),
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def package_tier_view(e):
    return {
        "id": e["id"],
        "code": e["code"],
        "name": e["name"],
        "channel_entitlements": list(e["channel_entitlements"]),
        "includes_streaming": e["includes_streaming"],
        "min_hardware_generation": e["min_hardware_generation"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def plan_view(e):
    return {
        "id": e["id"],
        "code": e["code"],
        "name": e["name"],
        "package_tier_id": e["package_tier_id"],
        "service_mode": e["service_mode"],
        "is_trial": e["is_trial"],
        "term_kind": e["term_kind"],
        "term_length_days": e["term_length_days"],
        "price_cents": e["price_cents"],
        "auto_renew_default": e["auto_renew_default"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def subscription_view(e):
    return {
        "id": e["id"],
        "customer_id": e["customer_id"],
        "radio_id": e["radio_id"],
        "plan_id": e["plan_id"],
        "kind": e["kind"],
        "status": e["status"],
        "origin": e["origin"],
        "start_at": iso_from_ts(e["start_at"]),
        "end_at": iso_from_ts(e["end_at"]),
        "auto_renew": e["auto_renew"],
        "is_primary_for_discount": e["is_primary_for_discount"],
        "current_term_price_cents": e["current_term_price_cents"],
        "disclosure_state": e["disclosure_state"],
        "save_offers_used_in_term": e["save_offers_used_in_term"],
        "cancel_requested_at": iso_from_ts(e["cancel_requested_at"]),
        "supersession_seq": e["supersession_seq"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def campaign_view(e):
    return {
        "id": e["id"],
        "code": e["code"],
        "name": e["name"],
        "lifecycle_phase": e["lifecycle_phase"],
        "state": e["state"],
        "window_start_at": iso_from_ts(e["window_start_at"]),
        "window_end_at": iso_from_ts(e["window_end_at"]),
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def offer_step_view(e):
    return {
        "id": e["id"],
        "campaign_id": e["campaign_id"],
        "step_index": e["step_index"],
        "plan_id": e["plan_id"],
        "step_up_rank": e["step_up_rank"],
        "discount_pct_bps": e["discount_pct_bps"],
        "flat_discount_cents": e["flat_discount_cents"],
        "eligibility_expr": e["eligibility_expr"],
        "max_redemptions_per_customer": e["max_redemptions_per_customer"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def redemption_view(e):
    return {
        "id": e["id"],
        "campaign_id": e["campaign_id"],
        "offer_step_id": e["offer_step_id"],
        "customer_id": e["customer_id"],
        "subscription_id": e["subscription_id"],
        "redeemed_price_cents": e["redeemed_price_cents"],
        "redeemed_at": iso_from_ts(e["redeemed_at"]),
        "created_at": iso_from_ts(e["created_at"]),
    }


def signal_view(e):
    return {
        "id": e["id"],
        "radio_id": e["radio_id"],
        "subscription_id": e["subscription_id"],
        "command_type": e["command_type"],
        "path": e["path"],
        "status": e["status"],
        "attempt_count": e["attempt_count"],
        "next_retry_at": iso_from_ts(e["next_retry_at"]),
        "idempotency_key": e["idempotency_key"],
        "created_at": iso_from_ts(e["created_at"]),
        "updated_at": iso_from_ts(e["updated_at"]),
        "version": e["version"],
    }


def ledger_view(e):
    return {
        "id": e["id"],
        "subscription_id": e["subscription_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "effective_at": iso_from_ts(e["effective_at"]),
        "idempotency_key": e["idempotency_key"],
        "note": e["note"],
        "created_at": iso_from_ts(e["created_at"]),
    }


def disclosure_view(e):
    return {
        "id": e["id"],
        "subscription_id": e["subscription_id"],
        "disclosure_type": e["disclosure_type"],
        "channel": e["channel"],
        "sent_at": iso_from_ts(e["sent_at"]),
        "due_before": iso_from_ts(e["due_before"]),
        "acknowledged_at": iso_from_ts(e["acknowledged_at"]),
        "created_at": iso_from_ts(e["created_at"]),
    }
