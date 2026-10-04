"""Composite setup helpers.

The server starts every test with an empty store and the logical clock at its
startup instant 2026-09-01T00:00:00Z (PRD §2.4), so each precondition here is
built from scratch through the public endpoints. Setup calls go through
``get_success_data`` (any 2xx accepted), so a fixture never bakes in the
200-versus-201 split; tests assert the statuses they care about themselves.

Identity threading (PRD §2.1): every fixture that creates a Forecaster row
builds that caller's headers with ``make_forecaster_headers(forecaster["id"])``
/ ``make_mic_headers(forecaster["id"])`` -- never a shared constant -- because
office scope and MIC level are read off the persisted row.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import DEFAULT_ISSUE_CLOCK_ISO
from .test_users import (
    make_admin_headers,
    make_analyst_headers,
    make_emergency_manager_headers,
    make_forecaster_headers,
    make_mic_headers,
)
from .types import JsonObject, ResourceId


class Bundle(object):
    """A small attribute bag so a test reads ``bundle.product["id"]`` fluently."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return "Bundle(%s)" % ", ".join(sorted(self.__dict__))


# Readings that comfortably meet each hazard's WARNING criterion (PRD §3.5).
DEFAULT_WARNING_READINGS = {
    "SEVERE_THUNDERSTORM": {"max_wind_mph": 60},
    "TORNADO": {"rotation_couplet": True},
    "FLASH_FLOOD": {"rainfall_rate_in_hr": 2.5},
    "HURRICANE": {"max_wind_mph": 80},
    "WINTER_STORM": {"max_wind_mph": 40},
}

# A valid expires_at for a WARNING/ADVISORY issued at the canonical 10:00 clock,
# inside the hazard's inclusive duration range (PRD §3.5).
DEFAULT_WARNING_EXPIRES = {
    "SEVERE_THUNDERSTORM": "2026-09-01T10:45:00Z",  # 45 min in 15..120
    "TORNADO": "2026-09-01T10:45:00Z",  # 45 min in 15..90
    "FLASH_FLOOD": "2026-09-01T11:00:00Z",  # 60 min in 30..180
    "HURRICANE": "2026-09-01T12:00:00Z",  # 120 min in 60..720
    "WINTER_STORM": "2026-09-01T12:00:00Z",  # 120 min in 60..720
}


# ---------------------------------------------------------------------------
# Platform capabilities (unprefixed endpoints, PRD §2.4)
# ---------------------------------------------------------------------------
def set_clock(client, to_iso8601: str) -> JsonObject:
    """Advance the logical clock; returns {"current_utc": ...}. The clock only
    moves forward, and each advance expires products, expires coordination
    requests (reverting their products) and dispatches queued records."""
    return get_success_data(client.set_clock(to_iso8601, make_admin_headers()))


def settle_record(client, record_id: ResourceId, outcome: str) -> JsonObject:
    """Settle a SENT record: CONFIRMED stamps confirmed_at; FAILED requeues below
    three attempts and kills the record at exactly three (PRD §3.6)."""
    return get_success_data(
        client.settle_dissemination_record(record_id, outcome, make_admin_headers())
    )


# ---------------------------------------------------------------------------
# Primitive creators (one POST each, lenient validation)
# ---------------------------------------------------------------------------
def create_office(client, **overrides) -> JsonObject:
    return get_success_data(
        client.create_office(factories.office_payload(**overrides), make_admin_headers())
    )


def create_zone(client, office_id: ResourceId = None, **overrides) -> JsonObject:
    """Create a county zone; when ``office_id`` is omitted a fresh office is
    created first and returned under ``payload_office`` -- prefer
    ``setup_office_with_zone`` when the office is needed."""
    if office_id is None:
        office_id = create_office(client)["id"]
    return get_success_data(
        client.create_zone(factories.zone_payload(office_id, **overrides), make_admin_headers())
    )


def create_forecaster(client, office_id: ResourceId, level: str = "SENIOR", **overrides) -> JsonObject:
    return get_success_data(
        client.create_forecaster(
            factories.forecaster_payload(office_id, level=level, **overrides),
            make_admin_headers(),
        )
    )


def create_neighbor_agreement(
    client,
    office_a_id: ResourceId,
    office_b_id: ResourceId,
    hazard_types=None,
    **overrides,
) -> JsonObject:
    return get_success_data(
        client.create_neighbor_agreement(
            factories.neighbor_agreement_payload(office_a_id, office_b_id, hazard_types, **overrides),
            make_admin_headers(),
        )
    )


def create_alert_channel(client, **overrides) -> JsonObject:
    return get_success_data(
        client.create_alert_channel(factories.alert_channel_payload(**overrides), make_admin_headers())
    )


def create_wea_channel(client, **overrides) -> JsonObject:
    return get_success_data(
        client.create_alert_channel(factories.wea_channel_payload(**overrides), make_admin_headers())
    )


def create_storm(
    client,
    office_id: ResourceId,
    headers,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    **readings,
) -> JsonObject:
    """Open a storm event; the caller must be a forecaster of that office (PRD §3.3)."""
    return get_success_data(
        client.create_storm_event(
            factories.storm_event_payload(office_id, hazard_type, **readings), headers
        )
    )


def update_storm(client, storm_id: ResourceId, headers, expected_version: int = None, **readings) -> JsonObject:
    """OCC-guarded readings update; re-reads the storm when no version is given."""
    if expected_version is None:
        expected_version = get_storm(client, storm_id, headers)["version"]
    return get_success_data(
        client.update_storm_event(
            storm_id, factories.storm_event_update_payload(expected_version, **readings), headers
        )
    )


# ---------------------------------------------------------------------------
# Readers (lenient; tests assert the interesting statuses themselves)
# ---------------------------------------------------------------------------
def get_office(client, office_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(client.get_office(office_id, headers or make_admin_headers()))


def get_storm(client, storm_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(client.get_storm_event(storm_id, headers or make_admin_headers()))


def get_product(client, product_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(client.get_product(product_id, headers or make_admin_headers()))


def get_coordination_request(client, request_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(
        client.get_coordination_request(request_id, headers or make_admin_headers())
    )


def get_record(client, record_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(
        client.get_dissemination_record(record_id, headers or make_admin_headers())
    )


def get_event(client, event_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(
        client.get_verification_event(event_id, headers or make_analyst_headers())
    )


def get_action(client, action_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(
        client.get_emergency_action(action_id, headers or make_emergency_manager_headers())
    )


def list_products(client, headers=None, **filters) -> list:
    return get_success_data(client.list_products(headers or make_admin_headers(), filters or None))


def list_coordination_requests(client, product_id: ResourceId = None, headers=None, **filters) -> list:
    if product_id is not None:
        filters["product_id"] = str(product_id)
    return get_success_data(
        client.list_coordination_requests(headers or make_admin_headers(), filters or None)
    )


def list_records(client, product_id: ResourceId = None, headers=None, **filters) -> list:
    if product_id is not None:
        filters["product_id"] = str(product_id)
    return get_success_data(
        client.list_dissemination_records(headers or make_admin_headers(), filters or None)
    )


def list_verification_events(client, headers=None, **filters) -> list:
    return get_success_data(
        client.list_verification_events(headers or make_analyst_headers(), filters or None)
    )


def list_emergency_actions(client, headers=None, **filters) -> list:
    return get_success_data(
        client.list_emergency_actions(headers or make_emergency_manager_headers(), filters or None)
    )


# ---------------------------------------------------------------------------
# Product drafting and transitions
# ---------------------------------------------------------------------------
def create_warning_draft(
    client,
    office: JsonObject,
    headers,
    storm: JsonObject,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    polygon=None,
    expires_at: str = None,
    **overrides,
) -> JsonObject:
    """A polygon-based WARNING draft (PRD §3.4: warnings require polygon+storm)."""
    return get_success_data(
        client.create_product(
            factories.warning_polygon_payload(
                office["id"],
                storm["id"],
                hazard_type=hazard_type,
                polygon=polygon,
                expires_at=expires_at or DEFAULT_WARNING_EXPIRES[hazard_type],
                **overrides,
            ),
            headers,
        )
    )


def create_watch_draft(
    client,
    office: JsonObject,
    headers,
    zone_ids,
    hazard_type: str = "WINTER_STORM",
    effective_from: str = "2026-09-02T00:00:00Z",
    expires_at: str = "2026-09-02T12:00:00Z",
    product_level: str = "WATCH",
    **overrides,
) -> JsonObject:
    """A zone-based WATCH/OUTLOOK draft with a future onset (PRD §3.4)."""
    return get_success_data(
        client.create_product(
            factories.zone_product_payload(
                product_level,
                office["id"],
                zone_ids,
                hazard_type=hazard_type,
                effective_from=effective_from,
                expires_at=expires_at,
                **overrides,
            ),
            headers,
        )
    )


def submit_coordination(client, product_id: ResourceId, headers) -> JsonObject:
    return get_success_data(client.submit_coordination(product_id, headers))


def respond_to_request(client, request_id: ResourceId, headers, outcome: str) -> JsonObject:
    """Neighbor-office respond; headers must belong to a forecaster of the
    request's target office (PRD §3.5 office scope)."""
    return get_success_data(
        client.respond_coordination_request(
            request_id, factories.coordination_respond_payload(outcome), headers
        )
    )


def issue_product(
    client, product_id: ResourceId, headers, coordination_override: bool = None
) -> JsonObject:
    """Issue a product, re-reading it first so the OCC field always carries the
    current version (PRD §2.6)."""
    current = get_product(client, product_id, headers)
    return get_success_data(
        client.issue_product(
            product_id,
            factories.issue_payload(current["version"], coordination_override),
            headers,
        )
    )


def cancel_product(client, product_id: ResourceId, headers) -> JsonObject:
    return get_success_data(client.cancel_product(product_id, headers))


def dissipate_storm(client, storm_id: ResourceId, headers) -> JsonObject:
    return get_success_data(client.dissipate_storm_event(storm_id, headers))


def get_wea_preview(client, product_id: ResourceId, channel_id: ResourceId, headers=None) -> JsonObject:
    return get_success_data(
        client.get_wea_preview(product_id, channel_id, headers or make_admin_headers())
    )


# ---------------------------------------------------------------------------
# Verification workflow (PRD §3.8)
# ---------------------------------------------------------------------------
def create_event(
    client,
    zone_id: ResourceId,
    hazard_type: str,
    observed_at: str,
    location_lat: float,
    location_lon: float,
    magnitude: str,
    **overrides,
) -> JsonObject:
    return get_success_data(
        client.create_verification_event(
            factories.verification_event_payload(
                zone_id, hazard_type, observed_at, location_lat, location_lon, magnitude, **overrides
            ),
            make_analyst_headers(),
        )
    )


def adjudicate_event(client, event_id: ResourceId, outcome: str) -> JsonObject:
    return get_success_data(
        client.adjudicate_verification_event(
            event_id, factories.adjudicate_payload(outcome), make_analyst_headers()
        )
    )


def create_and_confirm_event(
    client,
    zone_id: ResourceId,
    hazard_type: str,
    observed_at: str,
    location_lat: float,
    location_lon: float,
    magnitude: str,
    **overrides,
) -> JsonObject:
    """Report an event and adjudicate it CONFIRMED (matches products
    polygon-strict and bumps their verified_event_count, PRD §3.8)."""
    event = create_event(
        client, zone_id, hazard_type, observed_at, location_lat, location_lon, magnitude, **overrides
    )
    return adjudicate_event(client, event["id"], "CONFIRMED")


def compute_statistic(
    client,
    office_id: ResourceId,
    hazard_type: str,
    period_start: str = "2026-09-01T00:00:00Z",
    period_end: str = "2026-09-02T00:00:00Z",
    matching_variant: str = "POLYGON_STRICT",
    **overrides,
) -> JsonObject:
    """Compute a verification snapshot; cascades the performance band and bumps
    the office version (PRD §3.8)."""
    return get_success_data(
        client.create_verification_statistic(
            factories.verification_statistic_payload(
                office_id, hazard_type, period_start, period_end, matching_variant, **overrides
            ),
            make_analyst_headers(),
        )
    )


# ---------------------------------------------------------------------------
# Emergency actions (PRD §3.9)
# ---------------------------------------------------------------------------
def create_action(
    client,
    zone_id: ResourceId,
    product_id: ResourceId,
    action_type: str = "EVACUATION",
    effective_from: str = "2026-09-01T10:00:00Z",
    effective_until: str = "2026-09-01T11:00:00Z",
    manager_id: str = None,
    **overrides,
) -> JsonObject:
    headers = make_emergency_manager_headers(manager_id) if manager_id else make_emergency_manager_headers()
    return get_success_data(
        client.create_emergency_action(
            factories.emergency_action_payload(
                zone_id, product_id, action_type, effective_from, effective_until, **overrides
            ),
            headers,
        )
    )


def order_action(client, action_id: ResourceId, manager_id: str = None) -> JsonObject:
    headers = make_emergency_manager_headers(manager_id) if manager_id else make_emergency_manager_headers()
    return get_success_data(client.order_emergency_action(action_id, headers))


def lift_action(client, action_id: ResourceId, manager_id: str = None) -> JsonObject:
    headers = make_emergency_manager_headers(manager_id) if manager_id else make_emergency_manager_headers()
    return get_success_data(client.lift_emergency_action(action_id, headers))


# ---------------------------------------------------------------------------
# Composite tier 1: office setup
# ---------------------------------------------------------------------------
def setup_office_with_forecaster(
    client, level: str = "SENIOR", office_overrides: dict = None
) -> Bundle:
    """An office plus one forecaster whose headers thread the live row id."""
    office = create_office(client, **(office_overrides or {}))
    forecaster = create_forecaster(client, office["id"], level=level)
    headers = (
        make_mic_headers(forecaster["id"])
        if level == "MIC"
        else make_forecaster_headers(forecaster["id"])
    )
    return Bundle(office=office, forecaster=forecaster, headers=headers)


def setup_office_with_zone(
    client,
    zone_overrides: dict = None,
    forecaster_level: str = "SENIOR",
    office_overrides: dict = None,
) -> Bundle:
    """Office + one standard zone (0.1x0.1-degree cell, surveyed 123.21 sq km)
    + one forecaster with threaded headers. The most common test preamble."""
    bundle = setup_office_with_forecaster(client, level=forecaster_level, office_overrides=office_overrides)
    zone = create_zone(client, bundle.office["id"], **(zone_overrides or {}))
    bundle.zone = zone
    return bundle


def setup_office_with_storm(
    client,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    readings: dict = None,
    zone_overrides: dict = None,
    forecaster_level: str = "SENIOR",
    office_overrides: dict = None,
) -> Bundle:
    """Office + zone + forecaster + one storm carrying warning-grade readings."""
    bundle = setup_office_with_zone(
        client,
        zone_overrides=zone_overrides,
        forecaster_level=forecaster_level,
        office_overrides=office_overrides,
    )
    storm = create_storm(
        client,
        bundle.office["id"],
        bundle.headers,
        hazard_type,
        **(readings if readings is not None else DEFAULT_WARNING_READINGS[hazard_type]),
    )
    bundle.storm = storm
    bundle.hazard_type = hazard_type
    return bundle


# ---------------------------------------------------------------------------
# Composite tier 2: issued products
# ---------------------------------------------------------------------------
def setup_issued_warning(
    client,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    readings: dict = None,
    issue_clock: str = DEFAULT_ISSUE_CLOCK_ISO,
    expires_at: str = None,
    polygon=None,
    channels: list = None,
    zone_overrides: dict = None,
    office_overrides: dict = None,
) -> Bundle:
    """Full chain: office + zone + forecaster + storm, clock at ``issue_clock``,
    a polygon WARNING draft, then issue. ``channels`` is an optional list of
    ``alert_channel_payload`` overrides created BEFORE issuance so dissemination
    records spawn for them. Returns the issued product and its records."""
    bundle = setup_office_with_storm(
        client,
        hazard_type=hazard_type,
        readings=readings,
        zone_overrides=zone_overrides,
        office_overrides=office_overrides,
    )
    created_channels = [create_alert_channel(client, **(spec or {})) for spec in (channels or [])]
    set_clock(client, issue_clock)
    draft = create_warning_draft(
        client,
        bundle.office,
        bundle.headers,
        bundle.storm,
        hazard_type=hazard_type,
        polygon=polygon,
        expires_at=expires_at,
    )
    product = issue_product(client, draft["id"], bundle.headers)
    bundle.channels = created_channels
    bundle.product = product
    bundle.records = list_records(client, product["id"], bundle.headers)
    return bundle


def setup_issued_watch(
    client,
    hazard_type: str = "WINTER_STORM",
    issue_clock: str = "2026-09-01T09:00:00Z",
    effective_from: str = "2026-09-01T10:00:00Z",
    expires_at: str = "2026-09-01T12:00:00Z",
    product_level: str = "WATCH",
    channels: list = None,
    zone_overrides: dict = None,
) -> Bundle:
    """Office + zone + forecaster, clock at ``issue_clock``, a zone-based watch
    with a future onset, issued. WATCH/OUTLOOK carry no reading-based criterion."""
    bundle = setup_office_with_zone(client, zone_overrides=zone_overrides)
    created_channels = [create_alert_channel(client, **(spec or {})) for spec in (channels or [])]
    set_clock(client, issue_clock)
    draft = create_watch_draft(
        client,
        bundle.office,
        bundle.headers,
        [bundle.zone["id"]],
        hazard_type=hazard_type,
        effective_from=effective_from,
        expires_at=expires_at,
        product_level=product_level,
    )
    product = issue_product(client, draft["id"], bundle.headers)
    bundle.channels = created_channels
    bundle.product = product
    bundle.records = list_records(client, product["id"], bundle.headers)
    return bundle


# ---------------------------------------------------------------------------
# Composite tier 3: multi-office coordination
# ---------------------------------------------------------------------------
def setup_coordinated_offices(
    client,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    timeout_minutes: int = 15,
    hazard_types=None,
) -> Bundle:
    """Offices A and B joined by a neighbor agreement covering ``hazard_type``,
    a zone in each CWA, and one forecaster per office with threaded headers."""
    office_a = create_office(client)
    office_b = create_office(client)
    agreement = create_neighbor_agreement(
        client,
        office_a["id"],
        office_b["id"],
        hazard_types if hazard_types is not None else [hazard_type],
        coordination_timeout_minutes=timeout_minutes,
    )
    zone_a = create_zone(client, office_a["id"])
    zone_b = create_zone(
        client,
        office_b["id"],
        lon_min=0.2,
        lon_max=0.3,
    )
    forecaster_a = create_forecaster(client, office_a["id"])
    forecaster_b = create_forecaster(client, office_b["id"])
    return Bundle(
        office_a=office_a,
        office_b=office_b,
        agreement=agreement,
        zone_a=zone_a,
        zone_b=zone_b,
        forecaster_a=forecaster_a,
        forecaster_b=forecaster_b,
        headers_a=make_forecaster_headers(forecaster_a["id"]),
        headers_b=make_forecaster_headers(forecaster_b["id"]),
        hazard_type=hazard_type,
    )


def setup_pending_coordination_watch(
    client,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    timeout_minutes: int = 15,
    effective_from: str = "2026-09-01T12:00:00Z",
    expires_at: str = "2026-09-01T20:00:00Z",
) -> Bundle:
    """Two coordinated offices plus a cross-CWA watch moved DRAFT ->
    PENDING_COORDINATION. Returns the product and its REQUESTED requests.
    The default window starts well after the startup clock, so no clock set is
    needed before drafting (PRD §3.4 onset rule)."""
    bundle = setup_coordinated_offices(
        client, hazard_type=hazard_type, timeout_minutes=timeout_minutes
    )
    draft = create_watch_draft(
        client,
        bundle.office_a,
        bundle.headers_a,
        [bundle.zone_a["id"], bundle.zone_b["id"]],
        hazard_type=hazard_type,
        effective_from=effective_from,
        expires_at=expires_at,
    )
    product = submit_coordination(client, draft["id"], bundle.headers_a)
    bundle.product = product
    bundle.requests = list_coordination_requests(client, product["id"], bundle.headers_a)
    return bundle


def setup_issued_coordinated_watch(
    client,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    timeout_minutes: int = 15,
    effective_from: str = "2026-09-01T12:00:00Z",
    expires_at: str = "2026-09-01T20:00:00Z",
) -> Bundle:
    """A pending cross-CWA watch whose neighbor office has ACKNOWLEDGED, then
    issued. Returns the ISSUED product and the acknowledged requests."""
    bundle = setup_pending_coordination_watch(
        client,
        hazard_type=hazard_type,
        timeout_minutes=timeout_minutes,
        effective_from=effective_from,
        expires_at=expires_at,
    )
    for request in bundle.requests:
        respond_to_request(client, request["id"], bundle.headers_b, "ACKNOWLEDGED")
    product = issue_product(client, bundle.product["id"], bundle.headers_a)
    bundle.product = product
    bundle.requests = list_coordination_requests(client, product["id"], bundle.headers_a)
    return bundle


def setup_mic_pair(client, hazard_type: str = "SEVERE_THUNDERSTORM") -> Bundle:
    """Two coordinated offices where office A's forecaster row carries
    level MIC -- the coordination-override path (PRD §2.1, §3.5)."""
    bundle = setup_coordinated_offices(client, hazard_type=hazard_type)
    mic = create_forecaster(client, bundle.office_a["id"], level="MIC")
    bundle.mic = mic
    bundle.mic_headers = make_mic_headers(mic["id"])
    return bundle


__all__ = [
    "Bundle",
    "DEFAULT_WARNING_READINGS",
    "DEFAULT_WARNING_EXPIRES",
    "set_clock",
    "settle_record",
    "create_office",
    "create_zone",
    "create_forecaster",
    "create_neighbor_agreement",
    "create_alert_channel",
    "create_wea_channel",
    "create_storm",
    "update_storm",
    "get_office",
    "get_storm",
    "get_product",
    "get_coordination_request",
    "get_record",
    "get_event",
    "get_action",
    "list_products",
    "list_coordination_requests",
    "list_records",
    "list_verification_events",
    "list_emergency_actions",
    "create_warning_draft",
    "create_watch_draft",
    "submit_coordination",
    "respond_to_request",
    "issue_product",
    "cancel_product",
    "dissipate_storm",
    "get_wea_preview",
    "create_event",
    "adjudicate_event",
    "create_and_confirm_event",
    "compute_statistic",
    "create_action",
    "order_action",
    "lift_action",
    "setup_office_with_forecaster",
    "setup_office_with_zone",
    "setup_office_with_storm",
    "setup_issued_warning",
    "setup_issued_watch",
    "setup_coordinated_offices",
    "setup_pending_coordination_watch",
    "setup_issued_coordinated_watch",
    "setup_mic_pair",
]
