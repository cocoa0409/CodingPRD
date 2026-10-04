"""Composite setup helpers for the Vehicle History Network API.

Every test starts against an empty database, so each helper builds the world it
needs through the public API. All setup calls use the lenient
``get_success_data`` so setup failures surface as clear "Setup failed" errors.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_START
from .factories import (
    DEFAULTS,
    create_claim_payload,
    create_consumer_payload,
    create_dealer_payload,
    create_listing_payload,
    create_network_payload,
    create_record_payload,
    create_service_record_payload,
    create_shop_payload,
    create_source_payload,
)
from .test_users import (
    make_dealer_agent_headers,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_shop_operator_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
)

# A stable VIN pool so fixtures can create distinct vehicles.
VIN_A = "1HGCM82633A004352"
VIN_B = "2HGCM82633A004353"
VIN_C = "5YJSA1E26HF122334"
VIN_D = "9YJSA1E26HF122339"

# Default brand lexicon terms (per PRD section on brand normalization).
CA_TERMS = {
    "salvage certificate": "SALVAGE",
    "revived salvage": "REBUILT",
    "flood": "FLOOD",
    "lemon law buyback": "LEMON",
    "clean": "CLEAN",
}
TX_TERMS = {
    "salvage title": "SALVAGE",
    "rebuilt": "REBUILT",
    "water damage": "FLOOD",
    "manufacturer buyback": "LEMON",
    "clear": "CLEAN",
}


def set_clock(api: ApiClient, to_iso8601: str = CLOCK_START):
    resp = api.set_clock({"to_iso8601": to_iso8601}, make_network_admin_headers())
    get_success_data(resp)


def create_network(api: ApiClient, cap_cents: int = DEFAULTS["GUARANTEE_PAYOUT_CAP_CENTS"], name: str = "N1") -> Dict[str, Any]:
    resp = api.create_network(create_network_payload(name=name, guarantee_payout_cap_cents=cap_cents), make_network_admin_headers())
    return get_success_data(resp)


def setup_network(api: ApiClient, cap_cents: int = DEFAULTS["GUARANTEE_PAYOUT_CAP_CENTS"]) -> Dict[str, Any]:
    """Clock pinned to the startup instant + a fresh network."""
    set_clock(api)
    return create_network(api, cap_cents=cap_cents)


def register_source(api: ApiClient, source_type: str = "MVA", jurisdiction: str = "CA", activate: bool = True) -> Dict[str, Any]:
    resp = api.create_source(create_source_payload(source_type=source_type, jurisdiction=jurisdiction), make_network_admin_headers())
    source = get_success_data(resp)
    if activate:
        resp = api.activate_source(source["id"], make_network_admin_headers())
        source = get_success_data(resp)
    return source


def setup_network_with_source(api: ApiClient, source_type: str = "MVA", jurisdiction: str = "CA",
                              cap_cents: int = DEFAULTS["GUARANTEE_PAYOUT_CAP_CENTS"]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    network = setup_network(api, cap_cents=cap_cents)
    source = register_source(api, source_type=source_type, jurisdiction=jurisdiction)
    return network, source


def submit_record(api: ApiClient, source_id: str, **overrides) -> Dict[str, Any]:
    """Submit an external history record as the owning SourceOperator. Raises on failure."""
    payload = create_record_payload(source_id=source_id, **overrides)
    resp = api.create_record(payload, make_source_operator_headers(source_id))
    return get_success_data(resp)


def submit_title(api: ApiClient, source_id: str, vin: str, jurisdiction: str, raw_brand_text: str,
                 event_date: str = DEFAULTS["EVENT_DATE"], idempotency_key: str = "k-t1", payload_ref: str = "t1") -> Dict[str, Any]:
    return submit_record(
        api, source_id,
        vin=vin, record_type="TITLE_BRAND", jurisdiction=jurisdiction, raw_brand_text=raw_brand_text,
        event_date=event_date, idempotency_key=idempotency_key, payload_ref=payload_ref,
    )


def submit_inspection(api: ApiClient, source_id: str, vin: str, odometer_reading: int,
                      event_date: str = DEFAULTS["EVENT_DATE"], idempotency_key: str = "k-i1", payload_ref: str = "i1") -> Dict[str, Any]:
    return submit_record(
        api, source_id,
        vin=vin, record_type="INSPECTION", odometer_reading=odometer_reading,
        event_date=event_date, idempotency_key=idempotency_key, payload_ref=payload_ref,
    )


def advance_epoch(api: ApiClient, times: int = 1) -> Dict[str, Any]:
    """Advance the network epoch `times` times. Returns the last network payload."""
    network = None
    for _ in range(times):
        resp = api.advance_epoch(make_network_admin_headers())
        network = get_success_data(resp)
    return network


def get_vehicle(api: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vehicle(vehicle_id, make_network_admin_headers()))


def get_source(api: ApiClient, source_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_source(source_id, make_network_admin_headers()))


def get_record(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_record(record_id, make_network_admin_headers()))


def get_network(api: ApiClient, network_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_network(network_id, make_network_admin_headers()))


# ── Shops ─────────────────────────────────────────────────────────────────────

def create_active_shop(api: ApiClient, legal_name: str = "S1") -> Dict[str, Any]:
    """APPLIED shop approved to ACTIVE (with its provisioned SERVICE_SHOP source)."""
    shop = get_success_data(api.create_shop(create_shop_payload(legal_name=legal_name), make_network_admin_headers()))
    return get_success_data(api.approve_shop(shop["id"], make_network_admin_headers()))


def get_shop(api: ApiClient, shop_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shop(shop_id, make_network_admin_headers()))


def submit_service_record(api: ApiClient, shop_id: str, vin: str = VIN_A, odometer_reading: int = 10_000,
                          event_date: str = DEFAULTS["EVENT_DATE"], idempotency_key: str = "k-s1",
                          payload_ref: str = "s1", reported_cost_cents: Optional[int] = None) -> Dict[str, Any]:
    payload = create_service_record_payload(
        vin=vin, odometer_reading=odometer_reading, event_date=event_date,
        idempotency_key=idempotency_key, payload_ref=payload_ref,
    )
    if reported_cost_cents is not None:
        payload["reported_cost_cents"] = reported_cost_cents
    resp = api.create_service_record(shop_id, payload, make_shop_operator_headers(shop_id))
    return get_success_data(resp)


def submit_n_service_records(api: ApiClient, shop_id: str, count: int, vin: str = VIN_A,
                             base_odometer: int = 10_000, event_date: str = "2026-08-01"):
    """Submit `count` service records from the same shop on the same date with a
    monotonically non-decreasing odometer (SERVICE records never dedupe)."""
    records = []
    for i in range(count):
        records.append(submit_service_record(
            api, shop_id, vin=vin, odometer_reading=base_odometer,
            event_date=event_date, idempotency_key=f"k-s{i}", payload_ref=f"s{i}",
        ))
    return records


# ── Consumers ─────────────────────────────────────────────────────────────────

def create_consumer(api: ApiClient, email: str = "owner@x.com", credit_cents: int = 0) -> Dict[str, Any]:
    consumer = get_success_data(api.create_consumer(create_consumer_payload(email=email), make_vehicle_owner_headers("pending-owner")))
    if credit_cents:
        consumer = get_success_data(api.top_up_consumer_credit(
            consumer["id"], {"amount_cents": credit_cents}, make_network_admin_headers()))
    return consumer


def get_consumer(api: ApiClient, consumer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_consumer(consumer_id, make_network_admin_headers()))


# ── Dealers ───────────────────────────────────────────────────────────────────

def create_dealer(api: ApiClient, legal_name: str = "D1") -> Dict[str, Any]:
    return get_success_data(api.create_dealer(create_dealer_payload(legal_name=legal_name), make_network_admin_headers()))


def get_dealer(api: ApiClient, dealer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dealer(dealer_id, make_network_admin_headers()))


def subscribe_dealer(api: ApiClient, dealer_id: str, tier: str = "STANDARD") -> Dict[str, Any]:
    return get_success_data(api.subscribe_dealer(dealer_id, {"tier": tier}, make_dealer_agent_headers(dealer_id)))


# ── Listings ──────────────────────────────────────────────────────────────────

def create_listing(api: ApiClient, dealer_id: str, vehicle_id: str, asking_price_cents: int = DEFAULTS["ASKING_PRICE_CENTS"]) -> Dict[str, Any]:
    return get_success_data(api.create_listing(
        dealer_id, create_listing_payload(vehicle_id=vehicle_id, asking_price_cents=asking_price_cents),
        make_dealer_agent_headers(dealer_id)))


def publish_listing(api: ApiClient, dealer_id: str, listing_id: str, window_end_epoch: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if window_end_epoch is not None:
        payload["window_end_epoch"] = window_end_epoch
    return get_success_data(api.publish_listing(dealer_id, listing_id, payload, make_dealer_agent_headers(dealer_id)))


def enroll_listing(api: ApiClient, dealer_id: str, listing_id: str, expected_listing_version: int) -> Dict[str, Any]:
    return get_success_data(api.enroll_guarantee(
        dealer_id, listing_id, {"expected_listing_version": expected_listing_version},
        make_dealer_agent_headers(dealer_id)))


def setup_published_listing(api: ApiClient, dealer_id: str, vehicle_id: str,
                            asking_price_cents: int = DEFAULTS["ASKING_PRICE_CENTS"],
                            window_end_epoch: Optional[int] = None) -> Dict[str, Any]:
    listing = create_listing(api, dealer_id, vehicle_id, asking_price_cents=asking_price_cents)
    return publish_listing(api, dealer_id, listing["id"], window_end_epoch=window_end_epoch)


def setup_enrolled_listing(api: ApiClient, dealer_id: str, vehicle_id: str,
                           asking_price_cents: int = DEFAULTS["ASKING_PRICE_CENTS"],
                           window_end_epoch: Optional[int] = None) -> Dict[str, Any]:
    """DRAFT -> PUBLISHED -> ENROLLED. Returns the enrolled listing."""
    listing = setup_published_listing(api, dealer_id, vehicle_id, asking_price_cents=asking_price_cents,
                                      window_end_epoch=window_end_epoch)
    return enroll_listing(api, dealer_id, listing["id"], listing["version"])


def get_listing(api: ApiClient, listing_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_listing(listing_id, make_network_admin_headers()))


# ── Corrections ───────────────────────────────────────────────────────────────

def open_correction(api: ApiClient, vehicle_id: str, target_record_id: str, expected_vehicle_version: int,
                    requester_headers: Dict[str, str], reason: str = "record is wrong",
                    corrected_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_record_id": target_record_id,
        "reason": reason,
        "expected_vehicle_version": expected_vehicle_version,
    }
    if corrected_record is not None:
        payload["corrected_record"] = corrected_record
    return get_success_data(api.open_correction(vehicle_id, payload, requester_headers))


def setup_routed_correction(api: ApiClient, vehicle_id: str, target_record_id: str,
                            expected_vehicle_version: int, requester_headers: Dict[str, str],
                            corrected_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """OPEN -> AWAITING_SOURCE. Returns the routed correction."""
    correction = open_correction(api, vehicle_id, target_record_id, expected_vehicle_version,
                                 requester_headers, corrected_record=corrected_record)
    return get_success_data(api.route_correction(correction["id"], make_network_admin_headers()))


def setup_verified_correction(api: ApiClient, vehicle_id: str, target_record_id: str,
                              expected_vehicle_version: int, requester_headers: Dict[str, str],
                              record_source_id: str,
                              corrected_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """OPEN -> AWAITING_SOURCE -> VERIFIED. Returns the verified correction."""
    correction = setup_routed_correction(api, vehicle_id, target_record_id, expected_vehicle_version,
                                         requester_headers, corrected_record=corrected_record)
    return get_success_data(api.confirm_correction(correction["id"], make_source_operator_headers(record_source_id)))


def get_correction(api: ApiClient, correction_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_correction(correction_id, make_network_admin_headers()))


# ── Claims ────────────────────────────────────────────────────────────────────

def file_claim(api: ApiClient, listing_id: str, claimant_name: str = "Buyer One", claim_reason: str = "brand issue") -> Dict[str, Any]:
    return get_success_data(api.create_claim(
        create_claim_payload(listing_id=listing_id, claimant_name=claimant_name, claim_reason=claim_reason),
        make_guarantee_admin_headers()))


def get_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_claim(claim_id, make_network_admin_headers()))


def setup_enrolled_listing_with_escalation(api: ApiClient, source_id: str, dealer_id: str,
                                           vin: str = VIN_A,
                                           asking_price_cents: int = DEFAULTS["ASKING_PRICE_CENTS"],
                                           window_end_epoch: Optional[int] = None) -> Tuple[Dict[str, Any], str]:
    """Full flow: CLEAN title -> dealer listing published + enrolled -> SALVAGE title
    escalates the vehicle. Returns (listing, vehicle_id)."""
    clean = submit_title(api, source_id, vin, "CA", "clean", idempotency_key=f"k-{vin}-clean", payload_ref=f"{vin}-clean")
    vehicle_id = clean["vehicle_id"]
    listing = setup_enrolled_listing(api, dealer_id, vehicle_id, asking_price_cents=asking_price_cents,
                                     window_end_epoch=window_end_epoch)
    submit_title(api, source_id, vin, "TX", "salvage title", idempotency_key=f"k-{vin}-salvage", payload_ref=f"{vin}-salvage")
    return listing, vehicle_id


def setup_approved_claim(api: ApiClient, source_id: str, dealer_id: str, vin: str = VIN_A,
                         asking_price_cents: int = DEFAULTS["ASKING_PRICE_CENTS"]) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Enrolled listing, SALVAGE escalation, claim filed and approved.
    Returns (listing, approved_claim, vehicle_id)."""
    listing, vehicle_id = setup_enrolled_listing_with_escalation(api, source_id, dealer_id, vin=vin,
                                                                 asking_price_cents=asking_price_cents)
    claim = file_claim(api, listing["id"])
    approved = get_success_data(api.approve_claim(claim["id"], make_guarantee_admin_headers()))
    return listing, approved, vehicle_id


# ── Reports ───────────────────────────────────────────────────────────────────

def purchase_consumer_report(api: ApiClient, consumer_id: str, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(api.purchase_report(
        {"vehicle_id": vehicle_id, "product": "CONSUMER_SINGLE", "buyer_consumer_id": consumer_id},
        make_vehicle_owner_headers(consumer_id)))


def purchase_dealer_report(api: ApiClient, dealer_id: str, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(api.purchase_report(
        {"vehicle_id": vehicle_id, "product": "DEALER_SUBSCRIPTION", "buyer_dealer_id": dealer_id},
        make_dealer_agent_headers(dealer_id)))


def purchase_n_dealer_reports(api: ApiClient, dealer_id: str, vehicle_id: str, count: int) -> List[Dict[str, Any]]:
    return [purchase_dealer_report(api, dealer_id, vehicle_id) for _ in range(count)]


def get_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_report(report_id, make_network_admin_headers()))


# ── Whole-world composite fixtures ────────────────────────────────────────────

def setup_dealer_with_vehicle(api: ApiClient, vin: str = VIN_A) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Network + ACTIVE MVA source + a CLEAN-titled vehicle + a dealer.
    Returns (network, dealer, vehicle_id)."""
    network, source = setup_network_with_source(api)
    clean = submit_title(api, source["id"], vin, "CA", "clean", idempotency_key=f"k-{vin}-c", payload_ref=f"{vin}-c")
    dealer = create_dealer(api)
    return network, dealer, clean["vehicle_id"]
