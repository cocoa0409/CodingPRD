"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdBookingStatus,
    ComplianceStatus,
    ContractStatus,
    DemandBand,
    DonorLevel,
    EngagementStatus,
    PackageStatus,
    PackageType,
    PerformanceStatus,
    ProgrammingStatus,
    ReadinessPosture,
    SaleStatus,
    SeasonStatus,
    ServiceStatus,
    TicketOrderStatus,
)


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an int"
    assert data["version"] >= 1, f"{entity_name}.version starts at 1"


def assert_season(data: dict):
    assert_common_fields(data, "Season")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fiscal_year"], int)
    assert is_iso8601_timestamp(data["renewal_deadline_utc"])
    assert isinstance(data["base_ticket_price_cents"], int)
    assert data["base_ticket_price_cents"] >= 1
    assert isinstance(data["loyalty_discount_bp"], int)
    assert 0 <= data["loyalty_discount_bp"] <= 2000
    assert data["status"] in _values(SeasonStatus), f"bad Season.status {data['status']}"
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    assert isinstance(data["concerts_programmed_count"], int)
    assert isinstance(data["concerts_cancelled_count"], int)
    assert isinstance(data["program_book_revenue_cents"], int)


def assert_venue(data: dict):
    assert_common_fields(data, "Venue")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["changeover_buffer_minutes"], int)
    assert data["changeover_buffer_minutes"] >= 0
    assert isinstance(data["total_capacity"], int) and data["total_capacity"] >= 0


def assert_seat_section(data: dict):
    assert_common_fields(data, "SeatSection")
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["price_multiplier_bp"], int) and data["price_multiplier_bp"] >= 1
    assert isinstance(data["donor_priority_rank"], int)
    assert 1 <= data["donor_priority_rank"] <= 5
    assert isinstance(data["min_renewal_priority_score"], int)
    assert data["min_renewal_priority_score"] >= 0


def assert_section_inventory_element(element: dict):
    assert is_valid_uuid(element["seat_section_id"])
    for key in ("capacity", "held_count", "sold_count", "available_count", "fill_bp"):
        assert isinstance(element[key], int), f"section_inventory.{key} must be an int"
        assert element[key] >= 0, f"section_inventory.{key} must not be negative"
    assert element["demand_band"] in _values(DemandBand)
    assert (
        element["capacity"]
        == element["available_count"] + element["held_count"] + element["sold_count"]
    ), (
        "seat conservation broken: capacity must equal available_count + held_count "
        f"+ sold_count, got {element}"
    )


def assert_concert(data: dict):
    assert_common_fields(data, "Concert")
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["performance_start_utc"])
    assert is_iso8601_timestamp(data["performance_end_utc"])
    assert isinstance(data["program_minutes"], int) and data["program_minutes"] >= 1
    assert data["programming_status"] in _values(ProgrammingStatus)
    assert data["sale_status"] in _values(SaleStatus)
    assert data["performance_status"] in _values(PerformanceStatus)
    assert data["readiness_posture"] in _values(ReadinessPosture)
    assert isinstance(data["section_inventory"], list)
    for element in data["section_inventory"]:
        assert_section_inventory_element(element)
    assert isinstance(data["substitution_count"], int)
    assert isinstance(data["gross_ticket_revenue_cents"], int)
    assert_concert_rollups(data)


def assert_concert_rollups(concert: dict):
    """seats_held_count / seats_sold_count are the sums over section_inventory."""
    inventory = concert["section_inventory"]
    assert concert["seats_held_count"] == sum(e["held_count"] for e in inventory), (
        "seats_held_count must equal the sum of held_count over the inventory elements"
    )
    assert concert["seats_sold_count"] == sum(e["sold_count"] for e in inventory), (
        "seats_sold_count must equal the sum of sold_count over the inventory elements"
    )


def inventory_for(concert: dict, seat_section_id: str) -> dict:
    """Return the concert's section_inventory element for one seat section."""
    for element in concert["section_inventory"]:
        if element["seat_section_id"] == seat_section_id:
            return element
    raise AssertionError(
        f"concert {concert['id']} has no section_inventory element for {seat_section_id}"
    )


def assert_inventory_counts(
    concert: dict,
    seat_section_id: str,
    *,
    held_count=None,
    sold_count=None,
    available_count=None,
    fill_bp=None,
    demand_band=None,
    capacity=None,
):
    element = inventory_for(concert, seat_section_id)
    assert_section_inventory_element(element)
    if capacity is not None:
        assert element["capacity"] == capacity, f"capacity: {element}"
    if held_count is not None:
        assert element["held_count"] == held_count, f"held_count: {element}"
    if sold_count is not None:
        assert element["sold_count"] == sold_count, f"sold_count: {element}"
    if available_count is not None:
        assert element["available_count"] == available_count, f"available_count: {element}"
    if fill_bp is not None:
        assert element["fill_bp"] == fill_bp, f"fill_bp: {element}"
    if demand_band is not None:
        assert element["demand_band"] == demand_band, f"demand_band: {element}"
    return element


def assert_guest_artist_contract(data: dict):
    assert_common_fields(data, "GuestArtistContract")
    assert is_valid_uuid(data["concert_id"])
    assert isinstance(data["artist_name"], str) and data["artist_name"]
    assert data["role_type"] in ("SOLOIST", "CONDUCTOR")
    assert isinstance(data["offered_fee_cents"], int) and data["offered_fee_cents"] >= 0
    assert data["countered_fee_cents"] is None or isinstance(
        data["countered_fee_cents"], int
    )
    assert data["agreed_fee_cents"] is None or isinstance(data["agreed_fee_cents"], int)
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 1
    assert data["status"] in _values(ContractStatus)


def assert_musician(data: dict):
    assert_common_fields(data, "Musician")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["instrument"], str)
    assert isinstance(data["is_principal"], bool)
    assert isinstance(data["overscale_bp"], int) and 0 <= data["overscale_bp"] <= 10000
    assert isinstance(data["services_charged_ytd"], int)
    assert data["services_charged_ytd"] >= 0, "services_charged_ytd must never go negative"
    assert isinstance(data["ytd_earnings_cents"], int)


def assert_union_agreement(data: dict):
    assert_common_fields(data, "UnionAgreement")
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["scale_service_fee_cents"], int)
    assert data["scale_service_fee_cents"] >= 1
    assert isinstance(data["max_service_minutes"], int) and data["max_service_minutes"] >= 1
    assert data["overtime_rate_cents_per_minute"] >= 0
    assert data["min_rest_minutes_between_services"] >= 0
    assert data["max_services_per_day"] >= 1
    assert data["doubling_premium_bp"] >= 0
    assert data["mandatory_break_minutes"] >= 0
    assert data["principal_premium_bp"] >= 0


def assert_rehearsal_service(data: dict):
    assert_common_fields(data, "RehearsalService")
    assert is_valid_uuid(data["concert_id"])
    assert is_valid_uuid(data["venue_id"])
    assert data["service_type"] in ("REHEARSAL", "DRESS_REHEARSAL", "PERFORMANCE")
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])
    assert data["scheduled_end_utc"] > data["scheduled_start_utc"]
    assert isinstance(data["break_minutes"], int) and data["break_minutes"] >= 0
    assert isinstance(data["minimum_complement"], int) and data["minimum_complement"] >= 0
    assert data["status"] in _values(ServiceStatus)
    assert isinstance(data["confirmed_engagement_count"], int)
    assert data["confirmed_engagement_count"] >= 0
    assert data["compliance_status"] in _values(ComplianceStatus)


def assert_musician_engagement(data: dict):
    assert_common_fields(data, "MusicianEngagement")
    assert is_valid_uuid(data["service_id"])
    assert is_valid_uuid(data["musician_id"])
    assert isinstance(data["doubling_count"], int) and data["doubling_count"] >= 0
    assert data["status"] in _values(EngagementStatus)
    assert data["provisional_pay_cents"] is None or isinstance(
        data["provisional_pay_cents"], int
    )
    assert data["final_pay_cents"] is None or isinstance(data["final_pay_cents"], int)
    assert isinstance(data["overtime_minutes"], int) and data["overtime_minutes"] >= 0


def assert_patron(data: dict):
    assert_common_fields(data, "Patron")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["donor_level"] in _values(DonorLevel)
    assert isinstance(data["lifetime_donation_cents"], int)
    assert isinstance(data["consecutive_renewal_years"], int)
    assert isinstance(data["renewal_priority_score"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0, "credit_balance_cents must never go negative"
    assert isinstance(data["lifetime_cash_in_cents"], int)
    assert data["lifetime_cash_in_cents"] >= 0


def assert_subscription_package(data: dict):
    assert_common_fields(data, "SubscriptionPackage")
    assert is_valid_uuid(data["patron_id"])
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["seat_section_id"])
    assert data["prior_package_id"] is None or is_valid_uuid(data["prior_package_id"])
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert isinstance(data["concert_ids"], list) and data["concert_ids"]
    assert data["package_type"] in _values(PackageType)
    assert data["status"] in _values(PackageStatus)
    assert isinstance(data["locked_unit_price_cents"], int)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["fulfilled_concert_count"], int)


def assert_ticket_order(data: dict):
    assert_common_fields(data, "TicketOrder")
    assert is_valid_uuid(data["concert_id"])
    assert is_valid_uuid(data["patron_id"])
    assert is_valid_uuid(data["seat_section_id"])
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert data["status"] in _values(TicketOrderStatus)
    assert isinstance(data["quoted_unit_price_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] == data["quoted_unit_price_cents"] * data["seat_count"]
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert data["demand_band_at_hold"] in _values(DemandBand)
    assert isinstance(data["hold_expires_at_ops_run"], int)


def assert_ad_booking(data: dict):
    assert_common_fields(data, "AdBooking")
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["advertiser_name"], str) and data["advertiser_name"]
    assert data["ad_size"] in ("FULL_PAGE", "HALF_PAGE", "QUARTER_PAGE")
    assert data["placement"] in ("BACK_COVER", "INSIDE_FRONT_COVER", "RUN_OF_BOOK")
    assert isinstance(data["insertion_count"], int) and data["insertion_count"] >= 1
    assert data["status"] in _values(AdBookingStatus)


def assert_price_quote(data: dict):
    for key in (
        "unit_price_cents",
        "fill_bp",
        "donor_discount_bp",
        "seat_count",
        "amount_due_cents",
    ):
        assert isinstance(data[key], int), f"price quote {key} must be an int"
    assert data["demand_band"] in _values(DemandBand)
    assert data["amount_due_cents"] == data["unit_price_cents"] * data["seat_count"]


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_seat_conservation(concert: dict):
    """capacity == available_count + held_count + sold_count on every element."""
    for element in concert["section_inventory"]:
        assert_section_inventory_element(element)
    assert_concert_rollups(concert)


def assert_patron_cash_identity(patron: dict, paid_orders, active_packages):
    """lifetime_cash_in_cents == credit_balance_cents + PAID orders + ACTIVE/EXPIRED packages."""
    expected = (
        patron["credit_balance_cents"]
        + sum(o["amount_paid_cents"] for o in paid_orders)
        + sum(p["price_cents"] for p in active_packages)
    )
    assert patron["lifetime_cash_in_cents"] == expected, (
        "patron cash identity broken: lifetime_cash_in_cents "
        f"{patron['lifetime_cash_in_cents']} != credit {patron['credit_balance_cents']} "
        f"+ paid orders + active packages ({expected})"
    )


def assert_service_credit_identity(musician: dict, engagements):
    """services_charged_ytd == count of CONFIRMED/SETTLED engagements already priced."""
    expected = sum(
        1
        for e in engagements
        if e["status"] in ("CONFIRMED", "SETTLED") and e["provisional_pay_cents"] is not None
    )
    assert musician["services_charged_ytd"] == expected, (
        "musician service-credit ledger broken: services_charged_ytd "
        f"{musician['services_charged_ytd']} != {expected}"
    )
