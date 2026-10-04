"""Composite setup helpers.

Every helper builds its preconditions from scratch through the API — nothing is
seeded by the server, and every test starts against an empty database. Helpers
use the lenient ``get_success_data`` validator so a setup failure reports as a
clear "Setup failed" assertion rather than a confusing mismatch.

Two rules from the PRD shape the identity model here:

* Attribute verification is a two-person control — the analyst who created a
  claim may never verify it — so a provider organization is provisioned with a
  distinct creator and verifier.
* Scoped research operations resolve the acting analyst's ``assigned_market``,
  so entity-backed roles are always represented by a real ``User`` row's id,
  never by a shared header constant.
"""

import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH
from .factories import (
    create_attribute_payload,
    create_contract_payload,
    create_enforcement_case_payload,
    create_lease_comparable_payload,
    create_listing_payload,
    create_organization_payload,
    create_property_payload,
    create_sale_transaction_payload,
    create_seat_payload,
    create_source_document_payload,
    create_usage_event_payload,
    create_user_payload,
)
from .test_users import (
    TEST_USERS,
    make_broker_publisher_headers,
    make_enforcement_officer_headers,
    make_licensing_admin_headers,
    make_research_analyst_headers,
    make_seat_user_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Tier 0: clock and version primitives ─────────────────────

def set_logical_clock(current_utc: str = CLOCK_EPOCH) -> dict:
    """Advance or rewind the logical clock through its own endpoint."""
    return get_success_data(api_client.set_clock(current_utc, PLATFORM_ADMIN))


def current_property_version(property_id: str, headers: dict) -> int:
    return int(get_success_data(api_client.get_property(property_id, headers))["version"])


def current_contract_version(contract_id: str, headers: dict) -> int:
    return int(get_success_data(api_client.get_contract(contract_id, headers))["version"])


def current_transaction_version(transaction_id: str, headers: dict) -> int:
    return int(get_success_data(
        api_client.get_sale_transaction(transaction_id, headers)
    )["version"])


def get_property(property_id: str, headers: dict) -> dict:
    return get_success_data(api_client.get_property(property_id, headers))


def get_contract(contract_id: str, headers: dict) -> dict:
    return get_success_data(api_client.get_contract(contract_id, headers))


def get_organization(organization_id: str) -> dict:
    return get_success_data(api_client.get_organization(organization_id, PLATFORM_ADMIN))


# ─── Tier 1: organizations and identities ─────────────────────

def create_organization(**overrides) -> dict:
    return get_success_data(
        api_client.create_organization(create_organization_payload(**overrides), PLATFORM_ADMIN)
    )


def create_user(organization_id: str, *, role: str, email: str,
                full_name: str = "User", assigned_market=None) -> dict:
    payload = create_user_payload(email=email, full_name=full_name, role=role)
    if assigned_market is None:
        payload.pop("assigned_market", None)
    else:
        payload["assigned_market"] = assigned_market
    return get_success_data(api_client.create_user(organization_id, payload, PLATFORM_ADMIN))


def headers_for(user: dict) -> dict:
    """Build per-instance headers from a real entity-backed ``User`` row."""
    builder = {
        "RESEARCH_ANALYST": make_research_analyst_headers,
        "SEAT_USER": make_seat_user_headers,
        "LICENSING_ADMIN": make_licensing_admin_headers,
        "ENFORCEMENT_OFFICER": make_enforcement_officer_headers,
        "BROKER_PUBLISHER": make_broker_publisher_headers,
    }[user["role"]]
    return builder(user["id"])


def setup_provider_org(market: str = "TX-DALLAS", org_name: str = "Tarrant Field Research LLC",
                       service_tier: str = "ENTERPRISE", with_officer: bool = False) -> dict:
    """A DATA_PROVIDER organization with two assigned research analysts.

    Two analysts are provisioned because verification may not be performed by
    the analyst who created the claim. ``creator_headers`` and
    ``verifier_headers`` name them.
    """
    org = create_organization(
        legal_name=org_name, org_type="DATA_PROVIDER", home_market=market,
        service_tier=service_tier,
    )
    creator = create_user(
        org["id"], role="RESEARCH_ANALYST",
        email="dana.reyes@tarrantresearch.example", full_name="Dana Reyes",
        assigned_market=market,
    )
    verifier = create_user(
        org["id"], role="RESEARCH_ANALYST",
        email="yusuf.adeyemi@tarrantresearch.example", full_name="Yusuf Adeyemi",
        assigned_market=market,
    )
    out = {
        "org": org,
        "analysts": [creator, verifier],
        "creator": creator,
        "verifier": verifier,
        "creator_headers": headers_for(creator),
        "verifier_headers": headers_for(verifier),
    }
    if with_officer:
        officer = create_user(
            org["id"], role="ENFORCEMENT_OFFICER",
            email="hugo.lindqvist@tarrantresearch.example", full_name="Hugo Lindqvist",
        )
        out["officer"] = officer
        out["officer_headers"] = headers_for(officer)
    return out


def setup_subscriber_org(market: str = "TX-DALLAS", org_name: str = "Meridian Advisory Partners",
                         service_tier: str = "MID_MARKET", seat_user_count: int = 1) -> dict:
    """A SUBSCRIBER organization with a licensing admin and N seat users."""
    org = create_organization(
        legal_name=org_name, org_type="SUBSCRIBER", home_market=market,
        service_tier=service_tier,
    )
    admin = create_user(
        org["id"], role="LICENSING_ADMIN",
        email="priya.nair@meridianadvisory.example", full_name="Priya Nair",
    )
    seat_users = [
        create_user(
            org["id"], role="SEAT_USER",
            email=f"seat-user-{i + 1}@meridianadvisory.example",
            full_name=f"Seat User {i + 1}",
        )
        for i in range(seat_user_count)
    ]
    return {
        "org": org,
        "admin": admin,
        "admin_headers": headers_for(admin),
        "seat_users": seat_users,
        "seat_user_headers": [headers_for(u) for u in seat_users],
    }


def setup_brokerage_org(market: str = "TX-DALLAS", org_name: str = "Bison Commercial Realty",
                        service_tier: str = "MID_MARKET", with_admin: bool = False) -> dict:
    org = create_organization(
        legal_name=org_name, org_type="BROKERAGE", home_market=market,
        service_tier=service_tier,
    )
    publisher = create_user(
        org["id"], role="BROKER_PUBLISHER",
        email="carla.mendes@bisoncommercial.example", full_name="Carla Mendes",
    )
    out = {"org": org, "publisher": publisher, "publisher_headers": headers_for(publisher)}
    if with_admin:
        admin = create_user(
            org["id"], role="LICENSING_ADMIN",
            email="gregory.osei@bisoncommercial.example", full_name="Gregory Osei",
        )
        out["admin"] = admin
        out["admin_headers"] = headers_for(admin)
    return out


def add_user(org_id: str, *, role: str, email: str, full_name: str,
             assigned_market=None) -> tuple:
    user = create_user(
        org_id, role=role, email=email, full_name=full_name, assigned_market=assigned_market,
    )
    return user, headers_for(user)


def add_distinct_user(org_id: str, *, role: str, full_name: str,
                      assigned_market=None) -> tuple:
    """Add a user whose `email` is minted fresh.

    `User.email` is unique within its organization (PRD 2.8), so a test that
    wants a second analyst in an organization that already holds one must not
    reuse the first analyst's address — that would be an organization-state
    contradiction rather than a scenario a PRD-faithful server can serve.
    """
    email = f"{role.lower()}-{uuid.uuid4().hex[:12]}@example.test"
    user = create_user(
        org_id, role=role, email=email, full_name=full_name, assigned_market=assigned_market,
    )
    return user, headers_for(user)


def setup_listing_licensed_brokerage(markets=None, org_name: str = "Bison Commercial Realty",
                                     service_tier: str = "MID_MARKET",
                                     with_admin: bool = False) -> dict:
    """A brokerage holding an ACTIVE listing-service contract over `markets`.

    Listing publication checks the origin market against the publishing
    organization's licensed markets, so a brokerage without an activated
    contract cannot publish at all. Contracts, seats and activation are
    `LicensingAdmin` operations by PRD §4, so a real licensing administrator is
    provisioned even when the caller does not ask for one; a `BrokerPublisher`
    can never create or activate a contract.
    """
    markets = markets or ["TX-DALLAS"]
    out = setup_brokerage_org(
        market=markets[0], org_name=org_name, service_tier=service_tier,
        with_admin=True,
    )
    admin_headers = out["admin_headers"]
    contract = create_contract(
        out["org"]["id"], admin_headers, product="LISTING_SERVICE",
        licensed_markets=markets, seat_count=3, annual_fee_cents=50_000,
    )
    create_seat(contract["id"], admin_headers, market=markets[0],
                last_usage_cycle=CLOCK_EPOCH)
    activate_contract(contract["id"], admin_headers)
    out["contract"] = get_contract(contract["id"], admin_headers)
    out["license_admin_headers"] = admin_headers
    return out


# ─── Tier 2: research records ─────────────────────────────────

def create_property(analyst_headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_property(create_property_payload(**overrides), analyst_headers)
    )


def attach_source_document(property_id: str, analyst_headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_source_document(
            property_id, create_source_document_payload(**overrides), analyst_headers
        )
    )


def create_attribute_claim(property_id: str, source_document_id: str, analyst_headers: dict,
                           **overrides) -> dict:
    return get_success_data(
        api_client.create_attribute(
            property_id,
            create_attribute_payload(source_document_id, **overrides),
            analyst_headers,
        )
    )


def propose_value(property_id: str, attribute_id: str, value: str, analyst_headers: dict):
    """Submit a candidate value, carrying the property version the client just read."""
    payload = {
        "value": value,
        "expected_property_version": current_property_version(property_id, analyst_headers),
    }
    return api_client.propose_attribute(property_id, attribute_id, payload, analyst_headers)


def verify(attribute_id: str, verifier_headers: dict, payload=None):
    return api_client.verify_attribute(attribute_id, verifier_headers, payload)


def reject(attribute_id: str, verifier_headers: dict, payload=None):
    return api_client.reject_attribute(attribute_id, verifier_headers, payload)


def propose_and_verify(property_id: str, attribute_id: str, value: str,
                       creator_headers: dict, verifier_headers: dict) -> dict:
    """Drive one attribute from NONE to VERIFIED.

    The creator proposes; a different analyst verifies — the two-person control
    the PRD requires.
    """
    get_success_data(propose_value(property_id, attribute_id, value, creator_headers))
    return get_success_data(verify(attribute_id, verifier_headers))


def build_verified_attribute(provider: dict, property_id: str, *, field_name: str,
                             value: str, source_overrides=None,
                             attribute_overrides=None) -> dict:
    """Attach a source document and drive one attribute to VERIFIED.

    Returns ``{"source": sd, "attribute": att}``.
    """
    sd = attach_source_document(property_id, provider["creator_headers"],
                                **(source_overrides or {}))
    att = create_attribute_claim(
        property_id, sd["id"], provider["creator_headers"],
        field_name=field_name, **(attribute_overrides or {}),
    )
    att = propose_and_verify(
        property_id, att["id"], value,
        provider["creator_headers"], provider["verifier_headers"],
    )
    return {"source": sd, "attribute": att}


def ensure_researching(property_id: str, headers: dict) -> dict:
    """Move a DRAFT property to RESEARCHING, tolerating an automatic advance.

    The first attribute on a DRAFT property advances it without an explicit call,
    so an unconditional research/start would be refused with ERR_INVALID_STATE.
    """
    snapshot = get_property(property_id, headers)
    if snapshot["research_status"] == "DRAFT":
        get_success_data(api_client.start_research(property_id, headers))
        snapshot = get_property(property_id, headers)
    return snapshot


def create_sale_transaction(property_id: str, analyst_headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_sale_transaction(
            property_id, create_sale_transaction_payload(**overrides), analyst_headers
        )
    )


def create_lease_comparable(property_id: str, analyst_headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_lease_comparable(
            property_id, create_lease_comparable_payload(**overrides), analyst_headers
        )
    )


def create_listing(property_id: str, organization_id: str, publisher_headers: dict,
                   **overrides) -> dict:
    return get_success_data(
        api_client.create_listing(
            property_id, create_listing_payload(organization_id, **overrides), publisher_headers
        )
    )


# ─── Tier 3: contracts, seats and enforcement ─────────────────

def create_contract(subscriber_org_id: str, admin_headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(subscriber_org_id, **overrides), admin_headers
        )
    )


def create_seat(contract_id: str, admin_headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_seat(contract_id, create_seat_payload(**overrides), admin_headers)
    )


def assign_seat(contract_id: str, seat_id: str, occupant_user_id: str, admin_headers: dict):
    payload = {
        "occupant_user_id": occupant_user_id,
        "expected_contract_version": current_contract_version(contract_id, admin_headers),
    }
    return api_client.assign_seat(contract_id, seat_id, payload, admin_headers)


def unassign_seat(contract_id: str, seat_id: str, admin_headers: dict):
    payload = {"expected_contract_version": current_contract_version(contract_id, admin_headers)}
    return api_client.unassign_seat(contract_id, seat_id, payload, admin_headers)


def activate_contract(contract_id: str, admin_headers: dict):
    payload = {"expected_contract_version": current_contract_version(contract_id, admin_headers)}
    return api_client.activate_contract(contract_id, payload, admin_headers)


def add_market(contract_id: str, market: str, admin_headers: dict):
    payload = {
        "market": market,
        "expected_contract_version": current_contract_version(contract_id, admin_headers),
    }
    return api_client.add_contract_market(contract_id, payload, admin_headers)


def record_usage(seat_id: str, seat_user_headers: dict, **overrides):
    return api_client.create_usage_event(
        seat_id, create_usage_event_payload(**overrides), seat_user_headers
    )


def setup_active_contract(subscriber: dict, market: str = "TX-DALLAS", *,
                          product: str = "CORE_MARKET_DATA", annual_fee_cents: int = 100_000,
                          seat_count: int = 5, index_tier: str = "TIER_2",
                          licensed_markets=None, term_start: str = "2026-09-01T00:00:00Z",
                          term_end: str = "2027-09-01T00:00:00Z",
                          renewal_notice_days: int = 30, auto_renew: bool = True,
                          audit_intensity: str = "STANDARD",
                          assign_occupant: bool = True,
                          last_usage_cycle: str = "2026-09-01T00:00:00Z") -> dict:
    """Create an ACTIVE contract carrying exactly one seat.

    Returns ``contract``, ``seat``, ``admin_headers``, ``admin`` and — when a seat
    user exists and ``assign_occupant`` is set — ``occupant`` / ``occupant_headers``.
    """
    admin_headers = subscriber["admin_headers"]
    contract = create_contract(
        subscriber["org"]["id"], admin_headers,
        product=product,
        licensed_markets=[market] if licensed_markets is None else licensed_markets,
        seat_count=seat_count,
        annual_fee_cents=annual_fee_cents,
        auto_renew=auto_renew,
        renewal_notice_days=renewal_notice_days,
        term_start=term_start,
        term_end=term_end,
        audit_intensity=audit_intensity,
    )
    seat = create_seat(
        contract["id"], admin_headers, market=market, index_tier=index_tier,
        last_usage_cycle=last_usage_cycle,
    )
    out = {
        "contract": contract,
        "seat": seat,
        "admin_headers": admin_headers,
        "admin": subscriber["admin"],
    }
    # Activation must precede occupant assignment: PRD 3.6 gates assignment on the
    # contract's status being ACTIVE or GRACE, and on success assignment *sets*
    # access_revoked to false, so doing it beforehand would be overwritten too.
    get_success_data(activate_contract(contract["id"], admin_headers))
    if assign_occupant and subscriber.get("seat_users"):
        occupant = subscriber["seat_users"][0]
        assign_seat(contract["id"], seat["id"], occupant["id"], admin_headers)
        out["occupant"] = occupant
        out["occupant_headers"] = headers_for(occupant)
    out["contract"] = get_contract(contract["id"], admin_headers)
    out["seat"] = get_success_data(api_client.get_seat(seat["id"], admin_headers))
    return out


def open_enforcement_case(organization_id: str, contract_id: str, officer_headers: dict,
                          **overrides) -> dict:
    return get_success_data(
        api_client.create_enforcement_case(
            create_enforcement_case_payload(organization_id, contract_id, **overrides),
            officer_headers,
        )
    )


# ─── Tier 4: full research-record lifecycles ──────────────────

def setup_researching_property(provider: dict, *, field_name: str = "tenant_name",
                               value: str = "Harborline Logistics Inc",
                               property_overrides=None, source_overrides=None) -> dict:
    """A property holding one VERIFIED attribute.

    The first attribute on a DRAFT property advances it automatically, so the
    record comes back RESEARCHING rather than DRAFT.
    """
    prop = create_property(provider["creator_headers"], **(property_overrides or {}))
    built = build_verified_attribute(
        provider, prop["id"], field_name=field_name, value=value,
        source_overrides=source_overrides,
    )
    return {
        "property": get_property(prop["id"], provider["creator_headers"]),
        "source": built["source"],
        "attribute": built["attribute"],
    }


def setup_verified_property(provider: dict, *, field_name: str = "tenant_name",
                            value: str = "Harborline Logistics Inc",
                            property_overrides=None, source_overrides=None) -> dict:
    """A property driven all the way to VERIFIED through one published attribute."""
    out = setup_researching_property(
        provider, field_name=field_name, value=value,
        property_overrides=property_overrides, source_overrides=source_overrides,
    )
    get_success_data(
        api_client.finalize_property(out["property"]["id"], provider["creator_headers"])
    )
    out["property"] = get_property(out["property"]["id"], provider["creator_headers"])
    return out


def setup_completeness_divergence_property(provider: dict) -> dict:
    """The three-attribute fixture whose provisional and final scores diverge.

    Two of the three verified attributes rest on sources strictly older than the
    freshness window, so the provisional variant scores them at the unsourced
    weight and the final variant at zero. Returns the property snapshot taken
    immediately before finalize, plus the source and attribute rows.
    """
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    pid = prop["id"]
    ch, vh = provider["creator_headers"], provider["verifier_headers"]

    fresh = attach_source_document(
        pid, ch, source_type="DEED", source_name="Dallas County Clerk",
        contact_method="RECORDS_REQUEST", obtained_at="2026-02-20T00:00:00Z",
    )
    stale_one = attach_source_document(
        pid, ch, source_type="DIRECT_CONTACT",
        source_name="Building engineer walk-through", contact_method="SITE_VISIT",
        obtained_at="2025-07-01T00:00:00Z",
    )
    tenant = create_attribute_claim(pid, fresh["id"], ch, field_name="tenant_name")
    propose_and_verify(pid, tenant["id"], "Harborline Logistics Inc", ch, vh)

    occ = create_attribute_claim(pid, stale_one["id"], ch, field_name="occupancy_pct")
    propose_and_verify(pid, occ["id"], "92", ch, vh)

    stale_two = attach_source_document(
        pid, ch, source_type="BROKER_LISTING", source_name="Dallas County Registry digest",
        contact_method="RECORDS_REQUEST", obtained_at="2025-07-15T00:00:00Z",
    )
    enum_att = create_attribute_claim(pid, stale_two["id"], ch, field_name="enumeration_pct")
    propose_and_verify(pid, enum_att["id"], "2024", ch, vh)

    snapshot = get_property(pid, ch)
    return {
        "property_id": pid,
        "provisional_snapshot": snapshot,
        "sources": [fresh, stale_one, stale_two],
        "attributes": [tenant, occ, enum_att],
    }


def setup_two_attribute_completeness_property(provider: dict) -> dict:
    """The canonical two-attribute fixture described by the scoring rule.

    One verified attribute rests on a fresh deed, the other on a source 243 days
    old, with no other sources on the property. Returns the property snapshot
    taken before finalize.
    """
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    pid = prop["id"]
    ch, vh = provider["creator_headers"], provider["verifier_headers"]
    fresh = attach_source_document(
        pid, ch, source_type="DEED", source_name="Dallas County Clerk",
        contact_method="RECORDS_REQUEST", obtained_at="2026-02-20T00:00:00Z",
    )
    stale = attach_source_document(
        pid, ch, source_type="DIRECT_CONTACT", source_name="Expired listing sheet",
        contact_method="PHONE", obtained_at="2025-07-01T00:00:00Z",
    )
    att1 = create_attribute_claim(pid, fresh["id"], ch, field_name="tenant_name")
    propose_and_verify(pid, att1["id"], "Harborline Logistics Inc", ch, vh)
    att2 = create_attribute_claim(pid, stale["id"], ch, field_name="occupancy_pct")
    propose_and_verify(pid, att2["id"], "92", ch, vh)
    return {"property_id": pid, "snapshot": get_property(pid, ch),
            "fresh_source": fresh, "stale_source": stale,
            "attributes": [att1, att2]}


def post_usage_events(seat_id: str, occupant_headers: dict, events) -> list:
    """Record a sequence of usage events for one seat.

    Each entry is a dict with at least ``occurred_at``; missing fields take their
    factory defaults.
    """
    out = []
    for ev in events:
        out.append(get_success_data(record_usage(seat_id, occupant_headers, **ev)))
    return out


def setup_attribution_seat(subscriber: dict) -> dict:
    """An ACTIVE contract with one seat whose cycle starts 2026-04-01.

    The subscriber is expected to carry at least four seat users.
    """
    return setup_active_contract(
        subscriber, annual_fee_cents=100_000, seat_count=10,
        term_start="2026-04-01T00:00:00Z", term_end="2027-04-01T00:00:00Z",
        last_usage_cycle="2026-04-01T00:00:00Z",
    )