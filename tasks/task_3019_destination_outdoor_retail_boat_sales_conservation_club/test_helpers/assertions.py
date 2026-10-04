"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Every persisted resource carries the same four system-managed fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_store(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["dwell_capacity_minutes"], int)
    assert data["attraction_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["remit_ledger_cents"], int)
    assert isinstance(data["permit_remit_epoch"], int)
    assert isinstance(data["load_bays_total"], int)


def assert_member(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert data["club_card_status"] in ("NONE", "PENDING", "ACTIVE", "SUSPENDED")
    assert data["club_tier"] in ("BASE", "SILVER", "GOLD", "PATRON")
    for field in (
        "points_balance",
        "points_lifetime_earned",
        "redeemable_points",
        "conservation_match_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"

    # Invariants the PRD states for every member read.
    assert data["points_balance"] >= 0
    assert data["points_lifetime_earned"] >= 0
    assert data["redeemable_points"] >= 0
    assert data["conservation_match_cents"] >= 0
    assert data["conservation_match_cents"] <= 500, (
        "the conservation match accrues for the calendar year and is capped at five "
        "hundred cents"
    )


def assert_attraction(data: dict):
    assert_common_fields(data)
    assert data["attraction_type"] in (
        "AQUARIUM",
        "MUSEUM",
        "FISHING_POND",
        "ARCHERY_RANGE",
        "SIMULATOR",
        "TAXIDERMY_GALLERY",
    )
    assert isinstance(data["capacity_units"], int)
    assert isinstance(data["dwell_cost_minutes"], int)
    assert isinstance(data["requires_waiver"], bool)
    assert isinstance(data["in_use_units"], int) and data["in_use_units"] >= 0
    assert data["status"] in ("PLANNED", "OPEN", "RESTRICTED", "CLOSED")


def assert_attraction_session(data: dict):
    assert_common_fields(data)
    assert data["session_kind"] in (
        "GENERAL_ADMISSION",
        "ARCHERY_LANE",
        "SIMULATOR",
        "POND_CLINIC",
    )
    assert isinstance(data["party_size"], int)
    assert data["status"] in (
        "REQUESTED",
        "CONFIRMED",
        "IN_PROGRESS",
        "COMPLETED",
        "NO_SHOW",
        "CANCELLED",
    )
    assert isinstance(data["dwell_charge_minutes"], int)
    assert isinstance(data["overrun_minutes"], int) and data["overrun_minutes"] >= 0


def assert_boat_unit(data: dict):
    assert_common_fields(data)
    assert data["unit_condition"] in ("NEW", "USED", "DEMO")
    assert data["status"] in ("AVAILABLE", "DEAL_PENDING", "SOLD")
    assert isinstance(data["unit_price_cents"], int)


def assert_appraisal(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "ACCEPTED", "DECLINED", "SUPERSEDED")
    assert isinstance(data["offer_amount_cents"], int)
    assert isinstance(data["accepted_credit_cents"], int)
    assert is_iso8601_timestamp(data["appraised_at_utc"])


def assert_service_order(data: dict):
    assert_common_fields(data)
    assert data["order_kind"] in (
        "RIGGING",
        "OVERSIZE_LOADING",
        "TAXIDERMY",
        "OUTFITTING",
        "POND_MAINTENANCE",
    )
    assert data["status"] in (
        "INTAKE",
        "SCHEDULED",
        "IN_PROGRESS",
        "COMPLETED",
        "DELIVERED",
        "CANCELLED",
    )
    assert isinstance(data["promised_lead_days"], int)
    assert isinstance(data["actual_lead_days"], int)
    assert isinstance(data["is_late"], bool)


def assert_title_filing(data: dict):
    assert_common_fields(data)
    assert data["filing_kind"] in (
        "BOAT_TITLE",
        "MOTOR_TITLE",
        "TRAILER_REGISTRATION",
        "LIEN_RELEASE",
    )
    assert data["status"] in ("DRAFT", "SUBMITTED", "ISSUED", "REJECTED")


def assert_boat_deal(data: dict):
    assert_common_fields(data)
    assert data["deal_stage"] in ("QUOTED", "CONTRACTED", "DELIVERED", "SETTLED")
    assert data["funding_status"] in ("UNFUNDED", "PENDING", "FUNDED", "REFUNDED")
    assert data["title_status"] in ("NOT_STARTED", "FILED", "ISSUED", "REJECTED")
    assert data["rigging_status"] in ("NOT_STARTED", "SCHEDULED", "COMPLETE")
    for field in (
        "contract_price_cents",
        "total_fee_cents",
        "balance_due_cents",
        "deposit_cents",
        "funded_amount_cents",
        "points_awarded",
        "settlement_variance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["contract_price_cents"] >= 1, "a contract price is never zero and never negative"


def assert_permit_sale(data: dict):
    assert_common_fields(data)
    assert data["permit_type"] in (
        "FISHING",
        "HUNTING",
        "ARCHERY_RANGE",
        "BOAT_REGISTRATION",
    )
    assert data["residency_class"] in ("RESIDENT", "NON_RESIDENT", "SENIOR", "YOUTH")
    assert data["status"] in ("ISSUED", "VOIDED", "REMITTED", "CORRECTED")
    assert isinstance(data["term_days"], int)
    assert isinstance(data["fee_cents"], int)


def assert_remit_batch(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "OPEN",
        "SEALED",
        "TRANSMITTED",
        "ACCEPTED",
        "REJECTED",
        "CORRECTED",
    )
    assert isinstance(data["gross_fee_cents"], int)
    assert isinstance(data["interpretative_gross_cents"], int)
    assert isinstance(data["remit_variance_cents"], int)
    assert (
        data["remit_variance_cents"]
        == data["interpretative_gross_cents"] - data["gross_fee_cents"]
    ), "remit_variance_cents is the live total minus the frozen total"


def assert_club_card_application(data: dict):
    assert_common_fields(data)
    assert data["card_product"] in ("CLASSIC", "REWARDS", "PATRON")
    assert data["status"] in (
        "PENDING",
        "UNDERWRITING",
        "APPROVED",
        "DECLINED",
        "ACTIVATED",
    )
    assert isinstance(data["credit_limit_cents"], int)


def assert_point_event(data: dict):
    assert_common_fields(data)
    assert data["event_kind"] in ("AWARD", "REDEEM", "REVERSAL", "ADJUST")
    assert isinstance(data["points_delta"], int)
    assert isinstance(data["created_seq"], int)


def assert_event_offering(data: dict):
    assert_common_fields(data)
    assert data["offering_kind"] in ("SEMINAR", "KIDS_WORKSHOP", "FREE_DEMO")
    assert data["status"] in ("DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED")
    assert isinstance(data["registration_cap"], int)
    assert isinstance(data["confirmed_count"], int)
    assert isinstance(data["dwell_charge_minutes"], int)


def assert_event_registration(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REGISTERED",
        "CONFIRMED",
        "WAITLISTED",
        "CANCELLED",
        "ATTENDED",
    )
    assert isinstance(data["seats"], int)


def assert_bay_booking(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("RESERVED", "CHECKED_IN", "COMPLETED", "CANCELLED")
    assert isinstance(data["bay_no"], int)


def assert_order_fulfillment(data: dict):
    assert_common_fields(data)
    assert data["order_kind"] in ("OVERSIZE_CARRYOUT", "BOAT_DELIVERY_ORIENTATION")
    assert data["status"] in ("READY_FOR_RELEASE", "RELEASED", "CANCELLED")


def assert_service_intake(data: dict):
    assert_common_fields(data)
    assert data["intake_kind"] in ("TAXIDERMY", "OUTFITTING", "BOAT_SERVICE")
    assert data["status"] in (
        "INTAKE_QUOTED",
        "PERMIT_VERIFIED",
        "MATERIALS_ORDERED",
        "CURING",
        "READY_FOR_PICKUP",
        "RELEASED",
        "ABANDONED",
    )
    assert isinstance(data["project_charge_cents"], int)
    assert isinstance(data["deposit_cents"], int)


def assert_liability_waiver(data: dict):
    assert_common_fields(data)
    assert data["activity_scope"] in (
        "CATCH_AND_RELEASE_POND",
        "ARCHERY_RANGE",
        "SIMULATOR",
        "BOAT_DELIVERY_ORIENTATION",
    )
    assert data["status"] in ("SIGNED", "SUPERSEDED", "EXPIRED")
    assert is_iso8601_timestamp(data["expires_on"])


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_store_invariants(store: dict):
    """The store's dwell arithmetic must be internally consistent."""
    assert_store(store)
    assert (
        store["dwell_free_minutes"]
        == store["dwell_capacity_minutes"] - store["dwell_committed_minutes"]
    ), "dwell_free_minutes == dwell_capacity_minutes - dwell_committed_minutes"
    assert store["dwell_committed_minutes"] >= 0
    assert store["remit_ledger_cents"] >= 0
    assert store["permit_remit_epoch"] >= 0


def assert_member_points_invariants(member: dict):
    """Tier ladder and retention floor as the PRD states them."""
    assert_member(member)
    lifetime = member["points_lifetime_earned"]
    if lifetime >= 60_000:
        expected_tier = "PATRON"
    elif lifetime >= 25_000:
        expected_tier = "GOLD"
    elif lifetime >= 8_000:
        expected_tier = "SILVER"
    else:
        expected_tier = "BASE"
    assert member["club_tier"] == expected_tier, (
        f"lifetime {lifetime} should read {expected_tier}, got {member['club_tier']}"
    )
    floor = {"BASE": 0, "SILVER": 500, "GOLD": 1500, "PATRON": 4000}[expected_tier]
    assert member["redeemable_points"] == max(0, member["points_balance"] - floor)


def assert_deal_price_invariants(deal: dict):
    """A contract price is floored at one cent and never negative."""
    assert_boat_deal(deal)
    assert deal["contract_price_cents"] >= 1