"""Shape and invariant assertions for every entity the service returns."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ---------------------------------------------------------------------------
# Common-field discipline
# ---------------------------------------------------------------------------
_MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")


def assert_common_fields(record):
    """id, created_at, updated_at and version, as carried by mutable records."""
    for field in _MUTABLE_COMMON_FIELDS:
        assert field in record, f"missing common field {field}"
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int)
    assert record["version"] >= 1


def assert_append_only_common_fields(record):
    """id and created_at only: no updated_at and no version to read back."""
    for field in _APPEND_ONLY_COMMON_FIELDS:
        assert field in record, f"missing common field {field}"
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "append-only record must not carry updated_at"
    assert "version" not in record, "append-only record must not carry version"


def assert_fields_present(record, fields):
    for field in fields:
        assert field in record, f"missing field {field}"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_fair_edition(edition):
    assert_common_fields(edition)
    assert_fields_present(
        edition,
        (
            "year",
            "name",
            "run_start_date",
            "run_end_date",
            "gate_admission_price_cents",
            "talent_budget_cap_cents",
            "refund_reserve_cents",
            "max_shows_per_day",
            "curfew_utc_time",
            "strategy_basis",
            "committed_guarantee_total_cents",
            "refund_liability_committed_cents",
            "open_stage_count",
        ),
    )
    assert edition["strategy_basis"] in ("ATTENDANCE_WEIGHTED", "REVENUE_WEIGHTED")


def assert_stage(stage):
    assert_common_fields(stage)
    assert_fields_present(
        stage,
        (
            "fair_edition_id",
            "name",
            "reserved_seat_capacity",
            "ga_capacity",
            "changeover_buffer_minutes",
            "slot_soft_cap",
            "held_show_count",
            "booking_posture",
        ),
    )
    assert stage["booking_posture"] in ("OPEN", "SATURATED")


def assert_talent_agent(agent):
    assert_common_fields(agent)
    assert_fields_present(
        agent, ("user_id", "agency_name", "contact_email", "roster_artist_count")
    )


def assert_artist(artist):
    assert_common_fields(artist)
    assert_fields_present(
        artist,
        (
            "agent_id",
            "name",
            "genre",
            "audience_segment",
            "base_draw_score",
            "prior_year_paid_attendance",
            "prior_year_net_revenue_cents",
            "draw_score_next_year",
        ),
    )


def assert_offer(offer):
    assert_common_fields(offer)
    assert_fields_present(
        offer,
        (
            "fair_edition_id",
            "artist_id",
            "target_stage_id",
            "deal_type",
            "offered_guarantee_cents",
            "backend_split_pct",
            "backend_breakeven_cents",
            "radius_miles",
            "radius_days_before",
            "radius_days_after",
            "radius_waiver_granted",
            "target_show_date",
            "load_in_start_utc",
            "load_out_end_utc",
            "response_window_hours",
            "status",
            "round_count",
            "countered_guarantee_cents",
            "agreed_guarantee_cents",
            "sent_at_utc",
            "expires_at_utc",
            "created_by_user_id",
        ),
    )
    assert offer["status"] in (
        "DRAFT",
        "SENT",
        "COUNTERED",
        "ACCEPTED",
        "DECLINED",
        "WITHDRAWN",
        "EXPIRED",
    )


def assert_offer_round(round_record):
    assert_append_only_common_fields(round_record)
    assert_fields_present(
        round_record,
        (
            "offer_id",
            "round_number",
            "proposed_by",
            "proposed_guarantee_cents",
            "proposed_backend_split_pct",
            "proposed_breakeven_cents",
            "recorded_at_utc",
        ),
    )
    assert round_record["proposed_by"] in ("BUYER", "AGENT")


def assert_show_booking(booking):
    assert_common_fields(booking)
    assert_fields_present(
        booking,
        (
            "offer_id",
            "stage_id",
            "postponed_from_booking_id",
            "show_date",
            "load_in_start_utc",
            "load_out_end_utc",
            "doors_time_utc",
            "booking_status",
            "ticketing_status",
            "agreed_guarantee_cents",
            "agreed_deal_type",
            "agreed_backend_split_pct",
            "agreed_breakeven_cents",
            "gross_potential_cents",
            "sponsorship_revenue_cents",
            "recoupable_production_cost_cents",
            "paid_attendance",
            "refund_liability_cents",
            "announced_at_utc",
        ),
    )
    assert booking["booking_status"] in (
        "DATE_HELD",
        "ANNOUNCED",
        "PERFORMED",
        "CANCELLED",
        "POSTPONED",
    )
    assert booking["ticketing_status"] in (
        "SCALED_PENDING",
        "SCALED",
        "ON_SALE",
        "SALES_CLOSED",
        "REFUNDING",
        "REFUNDED",
    )


def assert_ticket_scale(scale):
    assert_common_fields(scale)
    assert_fields_present(
        scale,
        (
            "booking_id",
            "seating_type",
            "tier_name",
            "face_price_cents",
            "allotment_seats",
            "bundled_with_gate_admission",
            "facility_fee_cents",
            "sold_seats",
            "available_seats",
            "scale_gross_potential_cents",
            "status",
        ),
    )
    assert scale["seating_type"] in ("RESERVED", "GENERAL_ADMISSION")
    assert scale["status"] in ("ON_SALE_ELIGIBLE", "REFUND_DUE", "CLOSED")


def assert_ticket_sale_batch(batch):
    assert_append_only_common_fields(batch)
    assert_fields_present(
        batch,
        (
            "ticket_scale_id",
            "batch_kind",
            "quantity",
            "channel",
            "recorded_at_utc",
            "counts_toward_paid_attendance",
            "gross_cents",
        ),
    )
    assert batch["batch_kind"] in ("SALE", "REFUND")
    assert batch["channel"] in ("ONLINE", "BOX_OFFICE", "PHONE", "COMP")


def assert_production_advance(advance):
    assert_common_fields(advance)
    assert_fields_present(
        advance,
        (
            "booking_id",
            "status",
            "approved_rider_cost_cents",
            "recoupable_rider_cost_cents",
            "denied_item_count",
            "blocked_reason_code",
        ),
    )
    assert advance["status"] in (
        "ADVANCE_PENDING",
        "ADVANCE_IN_REVIEW",
        "ADVANCE_COMPLETE",
        "ADVANCE_BLOCKED",
        "ADVANCE_CANCELLED",
    )


def assert_rider_item(item):
    assert_common_fields(item)
    assert_fields_present(
        item,
        (
            "production_advance_id",
            "category",
            "description",
            "requested_cost_cents",
            "is_critical",
            "artist_recoupable",
            "status",
            "approved_cost_cents",
        ),
    )
    assert item["category"] in ("STAGING", "SOUND", "LIGHTING", "HOSPITALITY")
    assert item["status"] in (
        "REQUESTED",
        "APPROVED",
        "DENIED",
        "SUBSTITUTED",
        "VOIDED",
    )


def assert_sponsor(sponsor):
    assert_common_fields(sponsor)
    assert_fields_present(sponsor, ("name", "category", "exclusivity_tier"))
    assert sponsor["exclusivity_tier"] in ("PRESENTING", "SUPPORTING")


def assert_sponsorship_activation(activation):
    assert_common_fields(activation)
    assert_fields_present(
        activation,
        (
            "sponsor_id",
            "booking_id",
            "rights",
            "base_fee_cents",
            "exclusivity_category",
            "status",
            "net_fee_cents",
            "make_good_credit_cents",
        ),
    )
    assert activation["rights"] in (
        "STAGE_NAMING",
        "PRESENTING",
        "SAMPLING",
        "SIGNAGE",
    )
    assert activation["status"] in ("PROPOSED", "CONFIRMED", "FULFILLED", "CANCELLED")


def assert_contingency_action(action):
    assert_append_only_common_fields(action)
    assert_fields_present(
        action,
        (
            "booking_id",
            "action_type",
            "reason_code",
            "refund_policy",
            "replacement_show_date",
            "decided_at_utc",
            "pre_doors",
            "refund_liability_cents",
        ),
    )
    assert action["action_type"] in ("CANCEL", "POSTPONE")
    assert action["refund_policy"] in (
        "FULL_REFUND",
        "RAIN_CHECK",
        "NO_REFUND_AFTER_DOORS",
    )


SETTLEMENT_MONEY_FIELDS = (
    "adjusted_gross_cents",
    "sponsorship_offset_cents",
    "base_promoter_expense_cents",
    "provisional_net_pool_cents",
    "artist_payout_cents",
    "production_surcharge_cents",
    "promoter_expense_cents",
    "net_pool_cents",
    "merch_hall_fee_cents",
    "merch_artist_share_cents",
    "total_artist_settlement_cents",
)


def assert_settlement(settlement):
    assert_common_fields(settlement)
    assert_fields_present(
        settlement,
        (
            "booking_id",
            "basis",
            "merch_gross_cents",
            "merch_seller",
            "status",
            "revision_count",
            "submitted_by_user_id",
            "approved_by_user_id",
            "rejection_reason_code",
        )
        + SETTLEMENT_MONEY_FIELDS,
    )
    assert settlement["basis"] in ("PROVISIONAL", "FINAL")
    assert settlement["merch_seller"] in ("ARTIST", "VENUE")
    assert settlement["status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED")


def assert_settlement_preview(preview):
    """The computed read returns the eleven money figures plus its basis."""
    assert_fields_present(preview, SETTLEMENT_MONEY_FIELDS + ("basis",))
    assert preview["basis"] in ("PROVISIONAL", "FINAL")


BUYING_STRATEGY_REPORT_FIELDS = (
    "announced_show_count",
    "distinct_genre_count",
    "distinct_segment_count",
    "genre_diversity_index",
    "total_paid_attendance",
    "total_net_pool_cents",
    "revenue_per_paid_attendee_cents",
    "recommended_guarantee_ceiling_cents",
)


def assert_buying_strategy_report(report):
    assert_fields_present(report, BUYING_STRATEGY_REPORT_FIELDS)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_seat_identity(scale):
    """allotment_seats less sold_seats equals available_seats, exactly."""
    assert scale["available_seats"] == scale["allotment_seats"] - scale["sold_seats"]


def assert_stage_posture(stage):
    """SATURATED whenever held_show_count is at or above slot_soft_cap."""
    expected = (
        "SATURATED" if stage["held_show_count"] >= stage["slot_soft_cap"] else "OPEN"
    )
    assert stage["booking_posture"] == expected


def assert_ledger_values(record, **expected):
    for field, value in expected.items():
        assert record[field] == value, (
            f"{field}: expected {value}, read {record[field]}"
        )


def assert_ordered_by(records, field):
    values = [record[field] for record in records]
    assert values == sorted(values), f"records not ascending by {field}: {values}"


def assert_ordered_desc_by(records, field):
    values = [record[field] for record in records]
    assert values == sorted(values, reverse=True), (
        f"records not descending by {field}: {values}"
    )
