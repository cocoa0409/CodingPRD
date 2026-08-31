"""Payload factories — one per write endpoint, client-supplied fields only."""

DEFAULTS = {
    "ATHLETE_NAME": "Rae Nakamura",
    "ATHLETE_SPORT": "BASKETBALL",
    "MARKET_TIER": "GLOBAL",
    "BASE_APPEARANCE_RATE_CENTS": 400_000,
    "COMMISSION_PCT": 0.15,
    "BRAND_NAME": "Volt Hydration",
    "BRAND_CATEGORY": "BEVERAGE",
    "BRAND_LEGAL_ENTITY_NAME": "Volt Hydration Inc",
    "COMPLIANCE_RATING": 45,
    "REQUESTED_START_DATE": "2026-09-01",
    "REQUESTED_END_DATE": "2027-02-28",
    "PROPOSED_FEE_CENTS": 100_000,
    "HEADLINE_FEE_CENTS": 1_400_000,
    "USAGE_TERM_MONTHS": 12,
    "EXCLUSIVITY_MONTHS": 12,
    "APPEARANCE_DAYS": 1,
    "SLOT_NAME": "Studio A",
    "SLOT_CAPACITY": 1,
    "SLOT_WINDOW_START_AT": "2026-09-01T00:00:00Z",
    "SLOT_WINDOW_END_AT": "2026-12-31T23:00:00Z",
    "BOOKING_CITY": "Chicago",
    "BOOKING_START_AT": "2026-09-10T14:00:00Z",
    "BOOKING_END_AT": "2026-09-10T22:00:00Z",
    "TRAVEL_BUFFER_HOURS": 12,
    "TRAVEL_COST_CENTS": 180_500,
    "ASSET_URL": "https://cdn.example/asset.jpg",
    "DUE_DATE": "2026-09-20",
    "POSTED_AT": "2026-09-19T12:00:00Z",
    "DISCLOSURE_TAG": "#ad",
    "SIGNED_BY_REFERENCE": "CS-2026-0001",
}


def create_athlete_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["ATHLETE_NAME"],
        "sport": DEFAULTS["ATHLETE_SPORT"],
        "market_tier": DEFAULTS["MARKET_TIER"],
        "base_appearance_rate_cents": DEFAULTS["BASE_APPEARANCE_RATE_CENTS"],
        "commission_pct": DEFAULTS["COMMISSION_PCT"],
    }
    payload.update(overrides)
    return payload


def set_athlete_status_payload(status, reason=None) -> dict:
    payload = {"status": status}
    if reason is not None:
        payload["reason"] = reason
    return payload


def create_brand_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["BRAND_NAME"],
        "category": DEFAULTS["BRAND_CATEGORY"],
        "legal_entity_name": DEFAULTS["BRAND_LEGAL_ENTITY_NAME"],
        "compliance_rating": DEFAULTS["COMPLIANCE_RATING"],
    }
    payload.update(overrides)
    return payload


def sanction_brand_payload(sanctioned, reason=None) -> dict:
    payload = {"sanctioned": sanctioned}
    if reason is not None:
        payload["reason"] = reason
    return payload


def create_opportunity_payload(athlete_id, brand_id, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "brand_id": brand_id,
        "requested_start_date": DEFAULTS["REQUESTED_START_DATE"],
        "requested_end_date": DEFAULTS["REQUESTED_END_DATE"],
        "proposed_fee_cents": DEFAULTS["PROPOSED_FEE_CENTS"],
        "planned_posts": 1,
        "planned_appearances": 0,
        "planned_shoots": 0,
        "exclusivity_category": DEFAULTS["BRAND_CATEGORY"],
        "exclusivity_months": DEFAULTS["EXCLUSIVITY_MONTHS"],
        "territory": "NORTH_AMERICA",
        "usage_rights_tier": "BROADCAST",
    }
    payload.update(overrides)
    return payload


def create_term_sheet_payload(opportunity_id, **overrides) -> dict:
    payload = {
        "opportunity_id": opportunity_id,
        "fee_cents": DEFAULTS["HEADLINE_FEE_CENTS"],
        "usage_rights_tier": "BROADCAST",
        "usage_term_months": DEFAULTS["USAGE_TERM_MONTHS"],
        "territory": "NORTH_AMERICA",
        "morals_clause_tier": "TIER_B",
        "exclusivity_months": DEFAULTS["EXCLUSIVITY_MONTHS"],
        "appearance_days": DEFAULTS["APPEARANCE_DAYS"],
    }
    payload.update(overrides)
    return payload


def counter_term_sheet_payload(**overrides) -> dict:
    payload = {
        "counter_fee_cents": 1_300_000,
        "counter_usage_rights_tier": "BROADCAST",
        "counter_morals_clause_tier": "TIER_A",
        "counter_exclusivity_months": DEFAULTS["EXCLUSIVITY_MONTHS"],
    }
    payload.update(overrides)
    return payload


def revise_term_sheet_payload(**overrides) -> dict:
    payload = {
        "fee_cents": 1_350_000,
        "usage_rights_tier": "BROADCAST",
        "usage_term_months": DEFAULTS["USAGE_TERM_MONTHS"],
        "morals_clause_tier": "TIER_A",
        "exclusivity_months": DEFAULTS["EXCLUSIVITY_MONTHS"],
        "appearance_days": DEFAULTS["APPEARANCE_DAYS"],
    }
    payload.update(overrides)
    return payload


def countersign_payload(signed_by_reference=None) -> dict:
    return {"signed_by_reference": signed_by_reference or DEFAULTS["SIGNED_BY_REFERENCE"]}


def terminate_payload(reason_code="MORALS_BREACH") -> dict:
    return {"reason_code": reason_code}


def create_appearance_booking_payload(engagement_id, expected_engagement_version, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "city": DEFAULTS["BOOKING_CITY"],
        "start_at": DEFAULTS["BOOKING_START_AT"],
        "end_at": DEFAULTS["BOOKING_END_AT"],
        "travel_buffer_hours": DEFAULTS["TRAVEL_BUFFER_HOURS"],
        "expected_engagement_version": expected_engagement_version,
    }
    payload.update(overrides)
    return payload


def confirm_booking_payload(travel_cost_cents=None) -> dict:
    return {
        "travel_cost_cents": DEFAULTS["TRAVEL_COST_CENTS"]
        if travel_cost_cents is None
        else travel_cost_cents
    }


def close_booking_payload(outcome) -> dict:
    return {"outcome": outcome}


def cancel_booking_payload(reason_code="VENUE_CLOSED") -> dict:
    return {"reason_code": reason_code}


def create_production_slot_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SLOT_NAME"],
        "capacity": DEFAULTS["SLOT_CAPACITY"],
        "window_start_at": DEFAULTS["SLOT_WINDOW_START_AT"],
        "window_end_at": DEFAULTS["SLOT_WINDOW_END_AT"],
    }
    payload.update(overrides)
    return payload


def create_deliverable_payload(engagement_id, type_, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "type": type_,
        "due_date": DEFAULTS["DUE_DATE"],
    }
    payload.update(overrides)
    return payload


def submit_deliverable_payload(asset_url=None) -> dict:
    return {"asset_url": asset_url or DEFAULTS["ASSET_URL"]}


def review_deliverable_payload(decision, revision_note=None) -> dict:
    payload = {"decision": decision}
    if revision_note is not None:
        payload["revision_note"] = revision_note
    return payload


def create_disclosure_record_payload(deliverable_id, **overrides) -> dict:
    payload = {
        "deliverable_id": deliverable_id,
        "platform": "INSTAGRAM",
        "disclosure_tag": DEFAULTS["DISCLOSURE_TAG"],
        "posted_at": DEFAULTS["POSTED_AT"],
    }
    payload.update(overrides)
    return payload


def rule_disclosure_payload(ruling, finding_note=None) -> dict:
    payload = {"ruling": ruling}
    if finding_note is not None:
        payload["finding_note"] = finding_note
    return payload


def remediate_disclosure_payload(disclosure_tag, posted_at) -> dict:
    return {"disclosure_tag": disclosure_tag, "posted_at": posted_at}


def create_payout_statement_payload(engagement_id, expected_engagement_version) -> dict:
    return {
        "engagement_id": engagement_id,
        "expected_engagement_version": expected_engagement_version,
    }


def create_renewal_option_payload(engagement_id, option_deadline_date, proposed_base_fee_cents) -> dict:
    return {
        "engagement_id": engagement_id,
        "option_deadline_date": option_deadline_date,
        "proposed_base_fee_cents": proposed_base_fee_cents,
    }


def decide_renewal_payload(decision) -> dict:
    return {"decision": decision}
