"""Payload factories.

Each factory returns the client-supplied fields of one request body, using the
canonical values from ``constants.TEST_DEFAULTS`` and accepting ``**overrides``.
Server-derived fields (identifiers, timestamps, versions, derived ledgers) are
never included -- clients never supply them.
"""

from .constants import TEST_DEFAULTS


def _merge(payload, overrides):
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Fair editions and stages
# ---------------------------------------------------------------------------
def build_fair_edition_payload(**overrides):
    return _merge(
        {
            "year": TEST_DEFAULTS["EDITION_YEAR"],
            "name": TEST_DEFAULTS["EDITION_NAME"],
            "run_start_date": TEST_DEFAULTS["RUN_START_DATE"],
            "run_end_date": TEST_DEFAULTS["RUN_END_DATE"],
            "gate_admission_price_cents": TEST_DEFAULTS["GATE_ADMISSION_PRICE_CENTS"],
            "talent_budget_cap_cents": TEST_DEFAULTS["TALENT_BUDGET_CAP_CENTS"],
            "refund_reserve_cents": TEST_DEFAULTS["REFUND_RESERVE_CENTS"],
            "max_shows_per_day": TEST_DEFAULTS["MAX_SHOWS_PER_DAY"],
            "curfew_utc_time": TEST_DEFAULTS["CURFEW_UTC_TIME"],
            "strategy_basis": TEST_DEFAULTS["STRATEGY_BASIS"],
        },
        overrides,
    )


def build_stage_payload(fair_edition_id, **overrides):
    return _merge(
        {
            "fair_edition_id": fair_edition_id,
            "name": TEST_DEFAULTS["STAGE_NAME"],
            "reserved_seat_capacity": TEST_DEFAULTS["RESERVED_SEAT_CAPACITY"],
            "ga_capacity": TEST_DEFAULTS["GA_CAPACITY"],
            "changeover_buffer_minutes": TEST_DEFAULTS["CHANGEOVER_BUFFER_MINUTES"],
            "slot_soft_cap": TEST_DEFAULTS["SLOT_SOFT_CAP"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Talent roster
# ---------------------------------------------------------------------------
def build_talent_agent_payload(**overrides):
    return _merge(
        {
            "user_id": TEST_DEFAULTS["AGENT_USER_ID"],
            "agency_name": TEST_DEFAULTS["AGENCY_NAME"],
            "contact_email": TEST_DEFAULTS["CONTACT_EMAIL"],
        },
        overrides,
    )


def build_artist_payload(agent_id, **overrides):
    return _merge(
        {
            "agent_id": agent_id,
            "name": TEST_DEFAULTS["ARTIST_NAME"],
            "genre": TEST_DEFAULTS["ARTIST_GENRE"],
            "audience_segment": TEST_DEFAULTS["ARTIST_AUDIENCE_SEGMENT"],
            "base_draw_score": TEST_DEFAULTS["ARTIST_BASE_DRAW_SCORE"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Offers and negotiation
# ---------------------------------------------------------------------------
def build_offer_payload(fair_edition_id, artist_id, target_stage_id, **overrides):
    return _merge(
        {
            "fair_edition_id": fair_edition_id,
            "artist_id": artist_id,
            "target_stage_id": target_stage_id,
            "deal_type": TEST_DEFAULTS["DEAL_TYPE"],
            "offered_guarantee_cents": TEST_DEFAULTS["OFFERED_GUARANTEE_CENTS"],
            "backend_split_pct": TEST_DEFAULTS["BACKEND_SPLIT_PCT"],
            "backend_breakeven_cents": TEST_DEFAULTS["BACKEND_BREAKEVEN_CENTS"],
            "target_show_date": TEST_DEFAULTS["TARGET_SHOW_DATE"],
            "load_in_start_utc": TEST_DEFAULTS["LOAD_IN_START_UTC"],
            "load_out_end_utc": TEST_DEFAULTS["LOAD_OUT_END_UTC"],
            "response_window_hours": TEST_DEFAULTS["RESPONSE_WINDOW_HOURS"],
        },
        overrides,
    )


def build_counter_payload(proposed_guarantee_cents, **overrides):
    return _merge(
        {
            "proposed_guarantee_cents": proposed_guarantee_cents,
            "proposed_backend_split_pct": TEST_DEFAULTS["BACKEND_SPLIT_PCT"],
        },
        overrides,
    )


def build_revise_payload(expected_offer_version, offered_guarantee_cents, **overrides):
    return _merge(
        {
            "expected_offer_version": expected_offer_version,
            "offered_guarantee_cents": offered_guarantee_cents,
            "backend_split_pct": TEST_DEFAULTS["BACKEND_SPLIT_PCT"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Show calendar
# ---------------------------------------------------------------------------
def build_reschedule_payload(
    new_show_date, new_load_in_start_utc, new_load_out_end_utc, **overrides
):
    return _merge(
        {
            "new_show_date": new_show_date,
            "new_load_in_start_utc": new_load_in_start_utc,
            "new_load_out_end_utc": new_load_out_end_utc,
        },
        overrides,
    )


def build_announce_payload(doors_time_utc=None, **overrides):
    return _merge(
        {"doors_time_utc": doors_time_utc or TEST_DEFAULTS["DOORS_TIME_UTC"]},
        overrides,
    )


# ---------------------------------------------------------------------------
# Price tiers and box-office movement
# ---------------------------------------------------------------------------
def build_ticket_scale_payload(expected_show_booking_version, **overrides):
    return _merge(
        {
            "seating_type": "RESERVED",
            "tier_name": "GOLD",
            "face_price_cents": 6295,
            "allotment_seats": 400,
            "bundled_with_gate_admission": False,
            "facility_fee_cents": 0,
            "expected_show_booking_version": expected_show_booking_version,
        },
        overrides,
    )


def build_sales_batch_payload(batch_kind="SALE", quantity=1, channel="ONLINE", **overrides):
    return _merge(
        {"batch_kind": batch_kind, "quantity": quantity, "channel": channel},
        overrides,
    )


# ---------------------------------------------------------------------------
# Production advance
# ---------------------------------------------------------------------------
def build_rider_item_payload(**overrides):
    return _merge(
        {
            "category": "SOUND",
            "description": "Line array supplement",
            "requested_cost_cents": 0,
        },
        overrides,
    )


def build_rider_ruling_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Sponsorship
# ---------------------------------------------------------------------------
def build_sponsor_payload(**overrides):
    return _merge(
        {
            "name": "Prairie Mutual",
            "category": "FINANCIAL",
            "exclusivity_tier": "SUPPORTING",
        },
        overrides,
    )


def build_activation_payload(
    sponsor_id, booking_id, expected_show_booking_version, **overrides
):
    return _merge(
        {
            "sponsor_id": sponsor_id,
            "booking_id": booking_id,
            "rights": "SIGNAGE",
            "base_fee_cents": 1_000_000,
            "exclusivity_category": "FINANCIAL",
            "expected_show_booking_version": expected_show_booking_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Weather contingency
# ---------------------------------------------------------------------------
def build_contingency_action_payload(
    expected_show_booking_version,
    action_type="CANCEL",
    reason_code="SEVERE_WEATHER",
    refund_policy="FULL_REFUND",
    **overrides,
):
    return _merge(
        {
            "action_type": action_type,
            "reason_code": reason_code,
            "refund_policy": refund_policy,
            "expected_show_booking_version": expected_show_booking_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
def build_settlement_payload(**overrides):
    return _merge({"basis": "FINAL"}, overrides)


def build_settlement_rejection_payload(rejection_reason_code, **overrides):
    return _merge({"rejection_reason_code": rejection_reason_code}, overrides)
