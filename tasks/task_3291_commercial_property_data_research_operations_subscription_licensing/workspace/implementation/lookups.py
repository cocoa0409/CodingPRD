"""Entity lookup with PRD 2.12 left-to-right resolution and counter recomputation."""
import core


def get_organization(org_id):
    org = core.organizations.get(org_id)
    if org is None:
        raise core.ApiError("ERR_ORGANIZATION_NOT_FOUND")
    return org


def get_user(user_id):
    user = core.users.get(user_id)
    if user is None:
        raise core.ApiError("ERR_USER_NOT_FOUND")
    return user


def get_property(property_id):
    prop = core.properties.get(property_id)
    if prop is None:
        raise core.ApiError("ERR_PROPERTY_NOT_FOUND")
    return prop


def scoped_property(property_id, actor):
    """Property resolution with the analyst territory check of PRD 2.5."""
    prop = get_property(property_id)
    if actor is not None and actor.role == "ResearchAnalyst" and actor.user is not None:
        assigned = actor.user.get("assigned_market")
        if assigned is not None and prop["market"] != assigned:
            raise core.ApiError("ERR_PROPERTY_NOT_FOUND")
    return prop


def get_attribute(property_id, attribute_id):
    attr = core.attributes.get(attribute_id)
    if attr is None or attr["property_id"] != property_id:
        raise core.ApiError("ERR_ATTRIBUTE_NOT_FOUND")
    return attr


def get_attribute_any(attribute_id):
    attr = core.attributes.get(attribute_id)
    if attr is None:
        raise core.ApiError("ERR_ATTRIBUTE_NOT_FOUND")
    return attr


def get_source_document(property_id, source_id):
    sd = core.source_documents.get(source_id)
    if sd is None or sd["property_id"] != property_id:
        raise core.ApiError("ERR_SOURCE_DOCUMENT_NOT_FOUND")
    return sd


def get_source_document_any(source_id):
    sd = core.source_documents.get(source_id)
    if sd is None:
        raise core.ApiError("ERR_SOURCE_DOCUMENT_NOT_FOUND")
    return sd


def get_comparable(comparable_id):
    comp = core.lease_comparables.get(comparable_id)
    if comp is None:
        raise core.ApiError("ERR_PROPERTY_NOT_FOUND")
    return comp


def get_transaction(transaction_id):
    txn = core.sale_transactions.get(transaction_id)
    if txn is None:
        raise core.ApiError("ERR_TRANSACTION_NOT_FOUND")
    return txn


def get_contract(contract_id):
    contract = core.contracts.get(contract_id)
    if contract is None:
        raise core.ApiError("ERR_CONTRACT_NOT_FOUND")
    return contract


def get_seat(contract_id, seat_id):
    seat = core.seats.get(seat_id)
    if seat is None or seat["contract_id"] != contract_id:
        raise core.ApiError("ERR_SEAT_NOT_FOUND")
    return seat


def get_seat_any(seat_id):
    seat = core.seats.get(seat_id)
    if seat is None:
        raise core.ApiError("ERR_SEAT_NOT_FOUND")
    return seat


def get_listing(listing_id):
    listing = core.listings.get(listing_id)
    if listing is None:
        raise core.ApiError("ERR_LISTING_NOT_FOUND")
    return listing


def get_case(case_id):
    case = core.enforcement_cases.get(case_id)
    if case is None:
        raise core.ApiError("ERR_ENFORCEMENT_CASE_NOT_FOUND")
    return case


def get_run(run_id):
    run = core.analytics_runs.get(run_id)
    if run is None:
        raise core.ApiError("ERR_INVALID_REQUEST", "No analytics run exists with that id.")
    return run


def get_usage_event(event_id):
    event = core.usage_events.get(event_id)
    if event is None:
        raise core.ApiError("ERR_INVALID_REQUEST", "No usage event exists with that id.")
    return event


# ---------------------------------------------------------------------------
# Reverse-reachability helpers
# ---------------------------------------------------------------------------
def children_of(property_id):
    return [p for p in core.properties.values() if p["parent_property_id"] == property_id]


def sources_of(property_id):
    return [s for s in core.source_documents.values() if s["property_id"] == property_id]


def attributes_of(property_id):
    return [a for a in core.attributes.values() if a["property_id"] == property_id]


def comparables_of(property_id):
    return [c for c in core.lease_comparables.values() if c["property_id"] == property_id]


def transactions_of(property_id):
    return [t for t in core.sale_transactions.values() if t["property_id"] == property_id]


def seats_of(contract_id):
    return [s for s in core.seats.values() if s["contract_id"] == contract_id]


def contracts_of(org_id):
    return [c for c in core.contracts.values()
            if c["subscriber_organization_id"] == org_id]


def events_of(seat_id):
    return [e for e in core.usage_events.values() if e["seat_id"] == seat_id]


# ---------------------------------------------------------------------------
# Derived counters (PRD 2.8, 3.4)
# ---------------------------------------------------------------------------
AUTHORIZED_MARKET_STATUSES = {"PENDING", "ACTIVE", "GRACE", "RENEWED"}
ACTIVE_CONTRACT_STATUSES = {"ACTIVE", "GRACE"}


def recompute_organization_counters(org):
    markets = set()
    active = 0
    for contract in contracts_of(org["id"]):
        if contract["status"] in AUTHORIZED_MARKET_STATUSES:
            for market in contract["licensed_markets"]:
                markets.add(market)
        if contract["status"] in ACTIVE_CONTRACT_STATUSES:
            active += 1
    org["authorized_market_count"] = len(markets)
    org["active_contract_count"] = active
    return org


VERIFIED_COUNTED_STATUSES = {"VERIFIED"}
SCORING_STATUSES = {"NONE", "PENDING", "VERIFIED"}


def recompute_property_attributes(prop):
    """attribute_total_count / attribute_verified_count / stale_source_count.

    PRD 3.4: "`attribute_verified_count` counts only those whose
    `proposed_status` is `VERIFIED` — the state that represents a claim the
    record is willing to stand behind."
    """
    rows = attributes_of(prop["id"])
    prop["attribute_total_count"] = len(rows)
    prop["attribute_verified_count"] = sum(
        1 for a in rows if a["proposed_status"] in VERIFIED_COUNTED_STATUSES
    )
    stale = 0
    for sd in sources_of(prop["id"]):
        age = core.clock.now() - core.parse_dt(sd["obtained_at"])
        if age > core.timedelta(days=core.SOURCE_FRESHNESS_DAYS):
            stale += 1
    prop["stale_source_count"] = stale
    return prop


def recompute_verified_sale_value(prop):
    total = sum(
        t["gross_sale_price_cents"]
        for t in transactions_of(prop["id"])
        if t["subordination_status"] == "SUBORDINATED"
    )
    prop["verified_sale_value_cents"] = total
    return prop