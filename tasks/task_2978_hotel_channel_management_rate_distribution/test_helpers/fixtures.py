"""Scenario builders that stand a world up through the API itself.

The server is restarted before every test, so each test begins with an empty
database and the logical clock at its start value. Everything a test needs must
therefore be created through the endpoints, and these helpers are the composable
steps that do it: one hop each, plus a small number of multi-hop builders that
compose those hops in an order in which no later hop invalidates an earlier one.

Two ordering rules are respected throughout. A mapping is verified only after its
rate plan is active and its connection is sellable, because verification checks
both. And an allotment always re-reads the room type's current ``version``
immediately before it is created, because every accepted allotment spends that
echo by bumping the room type's version.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    APPROVER_USER_ID,
    CHANNEL_OPS_ENGINEER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVENUE_MANAGER_HEADERS,
    SUBMITTER_USER_ID,
    make_revenue_director_headers,
    make_revenue_manager_headers,
)

# ── The fixture clock and the dates hung off it ────────────────────────────

# Every scenario parks the clock here: a date from which the canonical stay
# dates below sit comfortably inside a 365-day booking horizon, and which the
# analytics windows used by these scenarios enclose.
FIXTURE_CLOCK = "2026-08-25T00:00:00.000Z"
FIXTURE_TODAY = "2026-08-25"

# The canonical stay dates. They sit two weeks out, so no test is ever near the
# "strictly after today" edge unless it means to be.
STAY_DATE = "2026-09-10"
STAY_DATE_2 = "2026-09-11"
STAY_DATE_3 = "2026-09-12"
STAY_DATE_4 = "2026-09-13"

# Canonical property policy.
PROPERTY_CODE = "HTL-SFO"
PROPERTY_NAME = "Harborview SFO"
PROPERTY_OVERBOOKING_PCT_BP = 1000
PROPERTY_BOOKING_HORIZON_DAYS = 365
PROPERTY_MIX_WINDOW_DAYS = 30
PROPERTY_TOLERANCE_CENTS = 200
PROPERTY_REQUIRED_IMAGE_COUNT = 5

# Canonical room type: ten physical rooms, a 10% allowance, so a ceiling of 11.
KING_CODE = "KING"
KING_CAPACITY = 10
KING_HASH = "kingv1"
KING_IMAGE_COUNT = 5
KING_CEILING = 11

# A second, deliberately tiny room type: two rooms at a 50% allowance, ceiling 3.
TWIN_CODE = "TWIN"
TWIN_CAPACITY = 2
TWIN_OVERBOOKING_PCT_BP = 5000
TWIN_CEILING = 3

# Canonical channels.
OTA_CODE = "OTA1"
OTA_COMMISSION_BP = 1750
OTA_GEO_MARKET = "US-CA"
BRAND_CODE = "BRAND"
BRAND_COMMISSION_BP = 0
OPAQUE_CODE = "OPQ1"
OPAQUE_COMMISSION_BP = 2500

# Canonical rate plan: a public root plan inside a wide band.
BAR_CODE = "BAR"
BAR_BASE_CENTS = 25000
BAR_FLOOR_CENTS = 18000
BAR_CEILING_CENTS = 40000


def date_offset(base: str, days: int) -> str:
    """The date ``days`` after ``base``, both in ``YYYY-MM-DD`` form."""
    parsed = date.fromisoformat(base)
    return (parsed + timedelta(days=days)).isoformat()


def instant(day: str, clock_time: str = "00:00:00.000") -> str:
    """An ISO 8601 UTC instant on ``day``, with three fractional digits."""
    return f"{day}T{clock_time}Z"


def date_range(start: str, end: str) -> List[str]:
    """Every date of the closed interval from ``start`` through ``end``."""
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]


# ── One-hop builders ───────────────────────────────────────────────────────


def set_clock(api: ApiClient, current_utc: str = FIXTURE_CLOCK) -> Dict[str, Any]:
    """Park the logical clock. Only the platform administrator may do this."""
    response = api.set_clock(factories.clock_payload(current_utc), PLATFORM_ADMIN_HEADERS)
    return get_success_data(response)


def create_property(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.property_payload(**overrides)
    return get_success_data(api.create_property(payload, PLATFORM_ADMIN_HEADERS))


def create_canonical_property(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """The canonical property: a 10% allowance, a 200-cent tolerance, 5 images."""
    payload: Dict[str, Any] = {
        "code": PROPERTY_CODE,
        "name": PROPERTY_NAME,
        "overbooking_pct_bp": PROPERTY_OVERBOOKING_PCT_BP,
        "booking_horizon_days": PROPERTY_BOOKING_HORIZON_DAYS,
        "mix_window_days": PROPERTY_MIX_WINDOW_DAYS,
        "rate_mismatch_tolerance_cents": PROPERTY_TOLERANCE_CENTS,
        "required_image_count": PROPERTY_REQUIRED_IMAGE_COUNT,
    }
    payload.update(overrides)
    return create_property(api, **payload)


def create_room_type(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.room_type_payload(**overrides)
    return get_success_data(api.create_room_type(property_id, payload, REVENUE_MANAGER_HEADERS))


def create_king_room_type(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """Ten rooms whose master content matches the canonical mapping content."""
    payload: Dict[str, Any] = {
        "code": KING_CODE,
        "name": "King Room",
        "physical_capacity_units": KING_CAPACITY,
        "master_description_hash": KING_HASH,
        "master_image_count": KING_IMAGE_COUNT,
    }
    payload.update(overrides)
    return create_room_type(api, property_id, **payload)


def create_twin_room_type(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """Two rooms with their own 50% allowance, so the ceiling is 3."""
    payload: Dict[str, Any] = {
        "code": TWIN_CODE,
        "name": "Twin Room",
        "physical_capacity_units": TWIN_CAPACITY,
        "master_description_hash": KING_HASH,
        "master_image_count": KING_IMAGE_COUNT,
        "overbooking_pct_bp": TWIN_OVERBOOKING_PCT_BP,
    }
    payload.update(overrides)
    return create_room_type(api, property_id, **payload)


def open_inventory_day(api: ApiClient, room_type_id: str, stay_date: str) -> Dict[str, Any]:
    payload = factories.inventory_day_payload(stay_date)
    return get_success_data(api.create_inventory_day(room_type_id, payload, REVENUE_MANAGER_HEADERS))


def open_inventory_days(
    api: ApiClient, room_type_id: str, stay_dates: Sequence[str]
) -> List[Dict[str, Any]]:
    """Open several nights, in the order given."""
    return [open_inventory_day(api, room_type_id, stay_date) for stay_date in stay_dates]


def open_inventory_range(api: ApiClient, room_type_id: str, start: str, end: str) -> List[Dict[str, Any]]:
    """Open every night of the closed interval from ``start`` through ``end``."""
    return open_inventory_days(api, room_type_id, date_range(start, end))


def create_channel(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.channel_payload(**overrides)
    return get_success_data(api.create_channel(property_id, payload, PLATFORM_ADMIN_HEADERS))


def create_connection(api: ApiClient, channel_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.connection_payload(**overrides)
    return get_success_data(api.create_connection(channel_id, payload, CHANNEL_OPS_ENGINEER_HEADERS))


def activate_connection(api: ApiClient, connection_id: str) -> Dict[str, Any]:
    """PENDING to HEALTHY."""
    return get_success_data(api.activate_connection(connection_id, CHANNEL_OPS_ENGINEER_HEADERS))


def record_heartbeat(
    api: ApiClient, connection_id: str, status: str = "OK", failure_code: Any = factories.OMIT
) -> Dict[str, Any]:
    payload = factories.heartbeat_payload(status=status, failure_code=failure_code)
    return get_success_data(api.record_heartbeat(connection_id, payload, CHANNEL_OPS_ENGINEER_HEADERS))


def fail_connection(
    api: ApiClient, connection_id: str, times: int = 1, failure_code: Any = factories.OMIT
) -> Dict[str, Any]:
    """Report ``times`` consecutive failure events and return the last state."""
    state: Dict[str, Any] = {}
    for _ in range(times):
        state = record_heartbeat(api, connection_id, status="ERROR", failure_code=failure_code)
    return state


def revalidate_connection(api: ApiClient, connection_id: str) -> Dict[str, Any]:
    """SUSPENDED to DEGRADED, leaving the streak one below the threshold."""
    return get_success_data(api.revalidate_connection(connection_id, CHANNEL_OPS_ENGINEER_HEADERS))


def create_freeze_window(
    api: ApiClient, connection_id: str, starts_at: str, ends_at: str, reason: Any = factories.OMIT
) -> Dict[str, Any]:
    payload = factories.freeze_window_payload(starts_at, ends_at, reason)
    return get_success_data(
        api.create_freeze_window(connection_id, payload, CHANNEL_OPS_ENGINEER_HEADERS)
    )


def create_rate_plan(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.rate_plan_payload(**overrides)
    return get_success_data(api.create_rate_plan(property_id, payload, REVENUE_MANAGER_HEADERS))


def create_derived_rate_plan(
    api: ApiClient, property_id: str, parent_rate_plan_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.derived_rate_plan_payload(parent_rate_plan_id, **overrides)
    return get_success_data(api.create_rate_plan(property_id, payload, REVENUE_MANAGER_HEADERS))


def activate_rate_plan(api: ApiClient, rate_plan_id: str) -> Dict[str, Any]:
    """DRAFT to ACTIVE. A derived plan needs its parent active first."""
    return get_success_data(api.activate_rate_plan(rate_plan_id, REVENUE_MANAGER_HEADERS))


def create_active_rate_plan(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """Author a plan and activate it; the returned row is the activated one."""
    plan = create_rate_plan(api, property_id, **overrides)
    return activate_rate_plan(api, plan["id"])


def create_canonical_rate_plan(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical public root plan, left in DRAFT."""
    payload: Dict[str, Any] = {
        "code": BAR_CODE,
        "rate_class": "PUBLIC",
        "base_amount_cents": BAR_BASE_CENTS,
        "floor_amount_cents": BAR_FLOOR_CENTS,
        "ceiling_amount_cents": BAR_CEILING_CENTS,
    }
    payload.update(overrides)
    return create_rate_plan(api, property_id, **payload)


def reprice_rate_plan(api: ApiClient, rate_plan_id: str, **fields: Any) -> Dict[str, Any]:
    """Reprice at the plan's current version, re-read immediately beforehand."""
    version = rate_plan_version(api, rate_plan_id)
    payload = factories.reprice_payload(expected_rate_plan_version=version, **fields)
    return get_success_data(api.patch_rate_plan(rate_plan_id, payload, REVENUE_MANAGER_HEADERS))


def close_rate_plan(api: ApiClient, rate_plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_rate_plan(rate_plan_id, REVENUE_MANAGER_HEADERS))


# ── Channels with a live connection ────────────────────────────────────────


def create_sellable_channel(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """A channel whose connection has been activated, so the channel can sell.

    Returns ``{"channel": ..., "connection": ...}``; the connection row is the
    activated one, so its state is HEALTHY and its streak is 0.
    """
    channel = create_channel(api, property_id, **overrides)
    connection = create_connection(api, channel["id"], url=factories.endpoint_url(channel["code"]))
    connection = activate_connection(api, connection["id"])
    return {"channel": channel, "connection": connection}


def create_ota_channel(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical public OTA: a 17.5% commission, member rates, one geo market."""
    payload: Dict[str, Any] = {
        "code": OTA_CODE,
        "channel_kind": "OTA_PUBLIC",
        "commission_bp": OTA_COMMISSION_BP,
        "allows_member_rate": True,
        "geo_market_codes": [OTA_GEO_MARKET],
    }
    payload.update(overrides)
    return create_sellable_channel(api, property_id, **payload)


def create_brand_channel(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical direct brand channel: no commission, every geo market."""
    payload: Dict[str, Any] = {
        "code": BRAND_CODE,
        "channel_kind": "DIRECT_BRAND",
        "commission_bp": BRAND_COMMISSION_BP,
    }
    payload.update(overrides)
    return create_sellable_channel(api, property_id, **payload)


def create_opaque_channel(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical opaque channel, the only one that admits opaque plans."""
    payload: Dict[str, Any] = {
        "code": OPAQUE_CODE,
        "channel_kind": "OTA_OPAQUE",
        "commission_bp": OPAQUE_COMMISSION_BP,
        "allows_opaque_rate": True,
    }
    payload.update(overrides)
    return create_sellable_channel(api, property_id, **payload)


def suspend_connection(api: ApiClient, connection_id: str, failure_code: Any = factories.OMIT) -> Dict[str, Any]:
    """Drive a HEALTHY connection to SUSPENDED with three consecutive failures."""
    return fail_connection(api, connection_id, times=3, failure_code=failure_code)


# ── Mappings ───────────────────────────────────────────────────────────────


def create_mapping(
    api: ApiClient,
    rate_plan_id: str,
    channel_id: str,
    room_type_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.mapping_payload(rate_plan_id, channel_id, room_type_id, **overrides)
    return get_success_data(api.create_mapping(payload, CHANNEL_OPS_ENGINEER_HEADERS))


def create_mapping_in_parity(
    api: ApiClient,
    rate_plan_id: str,
    channel_id: str,
    room_type_id: str,
    content_description_hash: str = KING_HASH,
    content_image_count: int = KING_IMAGE_COUNT,
    **overrides: Any,
) -> Dict[str, Any]:
    """A mapping whose content matches the master hash and clears the image floor."""
    return create_mapping(
        api,
        rate_plan_id,
        channel_id,
        room_type_id,
        content_description_hash=content_description_hash,
        content_image_count=content_image_count,
        **overrides,
    )


def verify_mapping(api: ApiClient, mapping_id: str) -> Dict[str, Any]:
    """To VERIFIED. The plan must already be ACTIVE and the connection sellable."""
    return get_success_data(api.verify_mapping(mapping_id, CHANNEL_OPS_ENGINEER_HEADERS))


def create_verified_mapping(
    api: ApiClient,
    rate_plan_id: str,
    channel_id: str,
    room_type_id: str,
    content_description_hash: str = KING_HASH,
    content_image_count: int = KING_IMAGE_COUNT,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a mapping in parity and verify it; the returned row is verified."""
    mapping = create_mapping_in_parity(
        api,
        rate_plan_id,
        channel_id,
        room_type_id,
        content_description_hash=content_description_hash,
        content_image_count=content_image_count,
        **overrides,
    )
    return verify_mapping(api, mapping["id"])


def patch_mapping_content(api: ApiClient, mapping_id: str, **fields: Any) -> Dict[str, Any]:
    payload = factories.mapping_content_payload(**fields)
    return get_success_data(
        api.patch_mapping_content(mapping_id, payload, CHANNEL_OPS_ENGINEER_HEADERS)
    )


def record_observed_rate(
    api: ApiClient, mapping_id: str, observed_rate_cents: int, observed_stay_date: str
) -> Dict[str, Any]:
    payload = factories.observed_rate_payload(observed_rate_cents, observed_stay_date)
    return get_success_data(
        api.record_observed_rate(mapping_id, payload, CHANNEL_OPS_ENGINEER_HEADERS)
    )


def disable_mapping(api: ApiClient, mapping_id: str) -> Dict[str, Any]:
    return get_success_data(api.disable_mapping(mapping_id, CHANNEL_OPS_ENGINEER_HEADERS))


# ── Promotions ─────────────────────────────────────────────────────────────


def create_promotion(
    api: ApiClient,
    rate_plan_id: str,
    start_date: str = STAY_DATE,
    end_date: str = STAY_DATE_2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.promotion_payload(start_date=start_date, end_date=end_date, **overrides)
    return get_success_data(api.create_promotion(rate_plan_id, payload, REVENUE_MANAGER_HEADERS))


def submit_promotion(api: ApiClient, promotion_id: str, user_id: str = SUBMITTER_USER_ID) -> Dict[str, Any]:
    """Submit for approval, attributing the submission to one named operator."""
    headers = make_revenue_manager_headers(user_id)
    return get_success_data(api.submit_promotion(promotion_id, headers))


def approve_promotion(api: ApiClient, promotion_id: str, user_id: str = APPROVER_USER_ID) -> Dict[str, Any]:
    """Approve as a second, different operator, as segregation of duties demands."""
    headers = make_revenue_director_headers(user_id)
    return get_success_data(api.approve_promotion(promotion_id, headers))


def reject_promotion(
    api: ApiClient,
    promotion_id: str,
    reason: Any = factories.OMIT,
    user_id: str = APPROVER_USER_ID,
) -> Dict[str, Any]:
    headers = make_revenue_director_headers(user_id)
    payload = factories.reject_payload(reason)
    return get_success_data(api.reject_promotion(promotion_id, headers, payload))


def create_approved_promotion(
    api: ApiClient,
    rate_plan_id: str,
    start_date: str = STAY_DATE,
    end_date: str = STAY_DATE_2,
    **overrides: Any,
) -> Dict[str, Any]:
    """Author, submit and approve, using two distinct operator identifiers."""
    promotion = create_promotion(
        api, rate_plan_id, start_date=start_date, end_date=end_date, **overrides
    )
    submit_promotion(api, promotion["id"])
    return approve_promotion(api, promotion["id"])


def load_promotion(api: ApiClient, promotion_id: str) -> Dict[str, Any]:
    return get_success_data(api.load_promotion(promotion_id, CHANNEL_OPS_ENGINEER_HEADERS))


# ── Restrictions ───────────────────────────────────────────────────────────


def create_restriction(
    api: ApiClient,
    room_type_id: str,
    restriction_type: str,
    start_date: str,
    end_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.restriction_payload(
        room_type_id, restriction_type, start_date, end_date, **overrides
    )
    return get_success_data(api.create_restriction(payload, REVENUE_MANAGER_HEADERS))


def lift_restriction(api: ApiClient, restriction_id: str) -> Dict[str, Any]:
    """A manual lift; the system's own guard restrictions refuse this route."""
    return get_success_data(api.lift_restriction(restriction_id, REVENUE_MANAGER_HEADERS))


# ── Allotments ─────────────────────────────────────────────────────────────


def create_allocation(
    api: ApiClient,
    room_type_id: str,
    channel_id: str,
    allocated_units: int,
    start_date: str,
    end_date: str,
    expected_room_type_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Carve an allotment, echoing the room type's version as it stands right now.

    The echo is re-read here rather than remembered by the caller, because every
    accepted allotment spends the previous echo by bumping the room type.
    """
    version = (
        expected_room_type_version
        if expected_room_type_version is not None
        else room_type_version(api, room_type_id)
    )
    payload = factories.allocation_payload(
        channel_id=channel_id,
        allocated_units=allocated_units,
        start_date=start_date,
        end_date=end_date,
        expected_room_type_version=version,
    )
    return get_success_data(api.create_allocation(room_type_id, payload, REVENUE_MANAGER_HEADERS))


def release_allocation(api: ApiClient, allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api.release_allocation(allocation_id, REVENUE_MANAGER_HEADERS))


# ── Reservations ───────────────────────────────────────────────────────────


def create_reservation(
    api: ApiClient,
    channel_id: str,
    rate_plan_id: str,
    room_type_id: str,
    arrival_date: str = STAY_DATE,
    nights: int = 1,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.reservation_payload(
        channel_id=channel_id,
        rate_plan_id=rate_plan_id,
        room_type_id=room_type_id,
        arrival_date=arrival_date,
        nights=nights,
        **overrides,
    )
    return get_success_data(
        api.create_reservation(payload, headers if headers is not None else REVENUE_MANAGER_HEADERS)
    )


def cancel_reservation(
    api: ApiClient, reservation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_reservation(
            reservation_id, headers if headers is not None else REVENUE_MANAGER_HEADERS
        )
    )


# ── Distribution ───────────────────────────────────────────────────────────


def dispatch_batch(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.dispatch_batch(batch_id, CHANNEL_OPS_ENGINEER_HEADERS))


def retry_job(api: ApiClient, job_id: str) -> Dict[str, Any]:
    return get_success_data(api.retry_job(job_id, CHANNEL_OPS_ENGINEER_HEADERS))


# ── Reads ──────────────────────────────────────────────────────────────────

# Every list read here asks for a full page, because the default page size is 10
# and a scenario that queues more rows than that would otherwise be truncated.
_FULL_PAGE = 100


def read_property(api: ApiClient, property_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_property(property_id, REVENUE_MANAGER_HEADERS))


def read_room_type(api: ApiClient, room_type_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_room_type(room_type_id, REVENUE_MANAGER_HEADERS))


def room_type_version(api: ApiClient, room_type_id: str) -> int:
    """The room type's version as it stands right now."""
    return int(read_room_type(api, room_type_id)["version"])


def read_rate_plan(api: ApiClient, rate_plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rate_plan(rate_plan_id, REVENUE_MANAGER_HEADERS))


def rate_plan_version(api: ApiClient, rate_plan_id: str) -> int:
    """The plan's version as it stands right now."""
    return int(read_rate_plan(api, rate_plan_id)["version"])


def read_channel(api: ApiClient, channel_id: str) -> Dict[str, Any]:
    """The single-channel read, which is where the lifetime ledger is inspected."""
    return get_success_data(api.get_channel(channel_id, REVENUE_MANAGER_HEADERS))


def read_connection(api: ApiClient, connection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_connection(connection_id, REVENUE_MANAGER_HEADERS))


def read_mapping(api: ApiClient, mapping_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_mapping(mapping_id, REVENUE_MANAGER_HEADERS))


def read_allocation(api: ApiClient, allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation(allocation_id, REVENUE_MANAGER_HEADERS))


def read_restriction(api: ApiClient, restriction_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_restriction(restriction_id, REVENUE_MANAGER_HEADERS))


def read_promotion(api: ApiClient, promotion_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_promotion(promotion_id, REVENUE_MANAGER_HEADERS))


def read_batch(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_batch(batch_id, REVENUE_MANAGER_HEADERS))


def read_job(api: ApiClient, job_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_job(job_id, REVENUE_MANAGER_HEADERS))


def read_reservation(api: ApiClient, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reservation(reservation_id, REVENUE_MANAGER_HEADERS))


def read_inventory_day(api: ApiClient, inventory_day_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inventory_day(inventory_day_id, REVENUE_MANAGER_HEADERS))


def inventory_day_on(api: ApiClient, room_type_id: str, stay_date: str) -> Dict[str, Any]:
    """The one inventory day of this room type on this stay date."""
    params = factories.page_params(
        limit=_FULL_PAGE,
        room_type_id=room_type_id,
        stay_date_from=stay_date,
        stay_date_to=stay_date,
    )
    days = get_success_data(api.list_inventory_days(REVENUE_MANAGER_HEADERS, params))
    assert len(days) == 1, f"expected one inventory day on {stay_date}, found {len(days)}"
    return dict(days[0])


def list_inventory_days(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_inventory_days(REVENUE_MANAGER_HEADERS, params)))


def list_rate_plans(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_rate_plans(REVENUE_MANAGER_HEADERS, params)))


def list_mappings(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_mappings(REVENUE_MANAGER_HEADERS, params)))


def list_allocations(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_allocations(REVENUE_MANAGER_HEADERS, params)))


def list_restrictions(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_restrictions(REVENUE_MANAGER_HEADERS, params)))


def list_promotions(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_promotions(REVENUE_MANAGER_HEADERS, params)))


def list_batches(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_batches(REVENUE_MANAGER_HEADERS, params)))


def list_jobs(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_jobs(REVENUE_MANAGER_HEADERS, params)))


def list_reservations(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE, **filters)
    return list(get_success_data(api.list_reservations(REVENUE_MANAGER_HEADERS, params)))


def list_freeze_windows(api: ApiClient, connection_id: str) -> List[Dict[str, Any]]:
    params = factories.page_params(limit=_FULL_PAGE)
    return list(
        get_success_data(api.list_freeze_windows(connection_id, REVENUE_MANAGER_HEADERS, params))
    )


def only_batch(api: ApiClient, **filters: Any) -> Dict[str, Any]:
    """The single batch matching the filters; fails when it is not unique."""
    batches = list_batches(api, **filters)
    assert len(batches) == 1, f"expected exactly one batch matching {filters}, found {len(batches)}"
    return batches[0]


def jobs_of(api: ApiClient, batch_id: str) -> List[Dict[str, Any]]:
    """A batch's child jobs, in ascending dispatch order."""
    jobs = list_jobs(api, batch_id=batch_id)
    return sorted(jobs, key=lambda job: job["sequence_index"])


def quoted_rate(api: ApiClient, mapping_id: str, stay_date: str, **params: Any) -> Dict[str, Any]:
    query = factories.quoted_rate_params(stay_date=stay_date, **params)
    return get_success_data(api.get_quoted_rate(mapping_id, REVENUE_MANAGER_HEADERS, query))


def channel_performance(
    api: ApiClient, channel_id: str, window_start_date: str, window_end_date: str, **params: Any
) -> Dict[str, Any]:
    query = factories.performance_params(window_start_date, window_end_date, **params)
    return get_success_data(api.get_channel_performance(channel_id, REVENUE_MANAGER_HEADERS, query))


def booking_pace(api: ApiClient, room_type_id: str, target_stay_date: str, **params: Any) -> Dict[str, Any]:
    query = factories.pace_params(target_stay_date, **params)
    return get_success_data(api.get_pace(room_type_id, REVENUE_MANAGER_HEADERS, query))


def channel_mix(
    api: ApiClient, property_id: str, window_start_date: str, window_end_date: str
) -> Dict[str, Any]:
    query = factories.mix_params(window_start_date, window_end_date)
    return get_success_data(api.get_channel_mix(property_id, REVENUE_MANAGER_HEADERS, query))


# ── The canonical world ────────────────────────────────────────────────────


def seed_reference_data(api: ApiClient) -> Dict[str, Any]:
    """Park the clock and stand up the smallest world that can sell a night.

    One property, one room type of ten rooms at a 10% allowance, one public OTA
    with a live connection, and one active public rate plan. Nothing is mapped
    and no night is open yet, so a scenario adds only what it actually needs.
    """
    set_clock(api, FIXTURE_CLOCK)
    property_row = create_canonical_property(api)
    room_type = create_king_room_type(api, property_row["id"])
    ota = create_ota_channel(api, property_row["id"])
    rate_plan = create_rate_plan(
        api,
        property_row["id"],
        code=BAR_CODE,
        rate_class="PUBLIC",
        base_amount_cents=BAR_BASE_CENTS,
        floor_amount_cents=BAR_FLOOR_CENTS,
        ceiling_amount_cents=BAR_CEILING_CENTS,
    )
    rate_plan = activate_rate_plan(api, rate_plan["id"])
    return {
        "property": property_row,
        "property_id": property_row["id"],
        "room_type": room_type,
        "room_type_id": room_type["id"],
        "channel": ota["channel"],
        "channel_id": ota["channel"]["id"],
        "connection": ota["connection"],
        "connection_id": ota["connection"]["id"],
        "rate_plan": rate_plan,
        "rate_plan_id": rate_plan["id"],
    }
