"""Resource serialisation: only fields the PRD and scaffold declare."""

SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "price_zone": ("zone_code", "currency_code", "price_multiplier_bp",
                   "psychological_rounding", "tax_rate_bp", "max_uplift_bp"),
    "cluster": ("cluster_code", "tier", "parent_cluster_id", "chain_depth",
                "published_bundle_version"),
    "store": ("store_code", "cluster_id", "price_zone_id", "timezone_offset_minutes",
              "accessibility_certified_until_utc", "daily_order_seq_counter",
              "seq_counter_date", "open_order_count", "content_posture"),
    "menu_item": ("sku", "display_name", "category", "base_price_cents", "allergen_tags",
                  "screen_reader_text", "contrast_ratio", "accessibility_state",
                  "zone_price_overrides", "zone_override_total_cents",
                  "pending_price_request_count", "pricing_lock_state",
                  "chainwide_availability_state"),
    "price_request": ("menu_item_id", "price_zone_id", "proposed_price_cents", "justification",
                      "effective_from_utc", "state", "requested_by_user_id",
                      "approval_user_ids", "baseline_price_cents", "uplift_bp",
                      "required_approvals", "revision_round", "pinned_menu_item_version",
                      "applied_price_cents", "last_decision_comment"),
    "availability": ("store_id", "menu_item_id", "on_hand_units", "reserved_units",
                     "par_units", "available_units", "supply_state", "listing_state",
                     "eighty_six_state", "eighty_six_until_utc", "eighty_six_reason",
                     "availability_state", "last_sync_utc"),
    "campaign": ("campaign_code", "version_no", "cluster_id", "discount_kind",
                 "discount_value", "window_start_utc", "window_end_utc", "stacking_group",
                 "priority_rank", "state", "pinned_bundle_version"),
    "upsell_rule": ("cluster_id", "trigger_item_id", "suggested_item_id", "rule_kind",
                    "min_cart_subtotal_cents", "suggestion_slot", "max_prompt_seconds",
                    "state", "suspended_reason"),
    "bundle": ("cluster_id", "bundle_version", "state", "accessibility_audit_state",
               "daypart_slots", "snapshot_item_ids", "price_snapshot",
               "price_snapshot_checksum", "live_price_checksum", "stale_flag",
               "validation_findings", "accessibility_findings", "published_at_utc",
               "effective_from_utc"),
    "device": ("store_id", "cached_bundle_id", "device_kind", "device_code",
               "offline_cache_capacity", "health_state", "payment_compliance_state",
               "cache_state", "printer_ok", "touch_ok", "screen_reader_ok", "network_ok",
               "last_heartbeat_utc", "consecutive_missed_heartbeats", "rolling_health_score",
               "worst_case_health_score", "cached_bundle_version", "pin_pad_firmware_version",
               "attestation_expiry_utc", "p2pe_certified", "offline_order_count"),
    "order": ("device_id", "applied_campaign_version_id", "order_number", "line_items",
              "priced_lines", "subtotal_cents", "discount_cents", "tax_cents", "total_cents",
              "tender_kind", "payment_state", "handoff_state", "created_offline",
              "accepted_upsell_rule_ids", "daypart_code", "pinned_bundle_version",
              "receipt_hash"),
}

AUDIT_FIELDS = ("subject_kind", "subject_id", "action", "actor_role", "actor_user_id",
                "at_utc", "before_value_cents", "after_value_cents", "sequence_no", "detail")


def clean(value):
    """Internal bookkeeping keys never leave the server."""
    if isinstance(value, dict):
        return dict((k, clean(v)) for k, v in value.items() if not k.startswith("_"))
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def dump(kind, row):
    out = {}
    for field in SYSTEM_FIELDS:
        out[field] = clean(row.get(field))
    for field in FIELDS[kind]:
        out[field] = clean(row.get(field))
    return out


def dump_many(kind, rows):
    return [dump(kind, row) for row in rows]


def dump_audit(row):
    out = {"id": row.get("id"), "created_at": row.get("created_at")}
    for field in AUDIT_FIELDS:
        out[field] = row.get(field)
    return out


def dump_audits(rows):
    return [dump_audit(row) for row in rows]
