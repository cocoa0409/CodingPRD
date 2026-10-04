"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the API server before each test and
each test therefore begins against an empty database.

Helpers use the lenient `get_success_data` validator so a broken setup reports
"Setup failed: ..." rather than a confusing assertion failure deeper in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_catalog_entry_payload,
    create_engagement_event_payload,
    create_essential_tier_payload,
    create_licensing_deal_payload,
    create_publisher_payload,
    create_region_payload,
    create_subscriber_payload,
    create_subscription_payload,
    create_tier_payload,
    create_title_payload,
)
from .test_users import TEST_USERS, make_subscriber_headers

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class SetupError(AssertionError):
    """Raised when a fixture's precondition chain cannot be built."""


class Scenario:
    """Attribute namespace holding the entities a fixture built."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return f"Scenario({sorted(self.__dict__)})"


def _data(response, what: str) -> dict:
    if response.status_code >= 400:
        raise SetupError(
            f"Setup failed while {what}: HTTP {response.status_code} {response.text[:400]}"
        )
    data = get_success_data(response)
    if not isinstance(data, dict):
        raise SetupError(f"Setup failed while {what}: expected an object, got {data!r}")
    return data


def _rows(response, what: str) -> list:
    if response.status_code >= 400:
        raise SetupError(
            f"Setup failed while {what}: HTTP {response.status_code} {response.text[:400]}"
        )
    body = response.json()
    data = body.get("data")
    if not isinstance(data, list):
        raise SetupError(f"Setup failed while {what}: expected an array, got {type(data)}")
    return data


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(api, current_utc: str = "2026-09-02T00:00:00Z"):
    """Advance the logical clock. The clock never moves backwards."""
    resp = api.set_current_utc(current_utc, ADMIN)
    if resp.status_code >= 400:
        raise SetupError(f"Setup failed setting the clock to {current_utc}: {resp.text[:300]}")
    return resp


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creators
# ---------------------------------------------------------------------------

def create_region(api, **overrides) -> dict:
    return _data(api.create_region(create_region_payload(**overrides), ADMIN),
                 "creating a region")


def create_publisher(api, **overrides) -> dict:
    return _data(api.create_publisher(create_publisher_payload(**overrides), ADMIN),
                 "creating a publisher")


def create_title(api, publisher_id: str, **overrides) -> dict:
    payload = create_title_payload(publisher_id=publisher_id, **overrides)
    return _data(api.create_title(payload, ADMIN), "creating a title")


def create_tier(api, **overrides) -> dict:
    return _data(api.create_tier(create_tier_payload(**overrides), ADMIN),
                 "creating a subscription tier")


def create_essential_tier(api, **overrides) -> dict:
    return _data(api.create_tier(create_essential_tier_payload(**overrides), ADMIN),
                 "creating the ESSENTIAL tier")


def create_subscriber(api, **overrides) -> dict:
    return _data(api.create_subscriber(create_subscriber_payload(**overrides), ANON),
                 "registering a subscriber")


def create_deal(api, publisher_id: str, title_id: str, **overrides) -> dict:
    payload = create_licensing_deal_payload(
        publisher_id=publisher_id, title_id=title_id, **overrides
    )
    return _data(api.create_licensing_deal(payload, ADMIN), "creating a licensing deal")


def sign_deal(api, deal_id: str, expected_title_version: int) -> dict:
    return _data(
        api.sign_licensing_deal(deal_id, {"expected_title_version": expected_title_version},
                                ADMIN),
        "signing a licensing deal",
    )


def create_entry(api, title_id: str, **overrides) -> dict:
    payload = create_catalog_entry_payload(title_id=title_id, **overrides)
    return _data(api.create_catalog_entry(payload, ADMIN), "planning a catalog entry")


def publish_entry(api, entry_id: str) -> dict:
    return _data(api.publish_catalog_entry(entry_id, ADMIN), "publishing a catalog entry")


def open_subscription(api, subscriber_id: str, **overrides) -> dict:
    payload = create_subscription_payload(subscriber_id=subscriber_id, **overrides)
    return _data(api.create_subscription(payload, ADMIN), "opening a subscription")


def pay_subscription(api, subscription_id: str, subscriber_id: str) -> dict:
    return _data(
        api.pay_subscription(subscription_id, make_subscriber_headers(subscriber_id)),
        "settling a subscription month",
    )


def record_event(api, subscription_id: str, subscriber_id: str, title_id: str,
                 **overrides) -> dict:
    payload = create_engagement_event_payload(title_id=title_id, **overrides)
    return _data(
        api.record_engagement_event(subscription_id, payload,
                                    make_subscriber_headers(subscriber_id)),
        "recording an engagement event",
    )


def list_entitlements(api, **params) -> list:
    return _rows(api.list_entitlements(ADMIN, params=params or None), "listing entitlements")


def list_entries(api, **params) -> list:
    return _rows(api.list_catalog_entries(ADMIN, params=params or None),
                 "listing catalog entries")


def first_entitlement(api, subscription_id: str, **params) -> dict:
    params.setdefault("limit", 10)
    params.setdefault("offset", 0)
    params["subscription_id"] = subscription_id
    rows = list_entitlements(api, **params)
    if not rows:
        raise SetupError(f"Setup failed: no entitlement for subscription {subscription_id}")
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy: the standard catalogue scenario
# ---------------------------------------------------------------------------

def build_catalog_scenario(api, *,
                           region_code: str = "NA",
                           currency_code: str = "USD",
                           price_multiplier: float = 1.20,
                           ceiling: int = 4000,
                           tier_floor: str = "ESSENTIAL",
                           publisher_name: str = None,
                           title_name: str = None,
                           platform_set=None,
                           day_one_eligible: bool = True,
                           list_price_cents: int = None,
                           unit_sales_30d: int = None,
                           tier_monthly_price_cents: int = None,
                           deal_overrides: dict = None,
                           seed_clock: str = "2026-09-01T00:00:00Z",
                           advance_to: str = "2026-09-02T00:00:00Z",
                           create_essential: bool = True,
                           sign: bool = True) -> Scenario:
    """Region + PREMIUM tier + publisher + title + one deal, signed and LIVE.

    With `sign=False` the deal is deliberately left in DRAFT, and `advance_to`
    is applied as given.
    """
    set_clock(api, seed_clock)

    region = create_region(
        api,
        region_code=region_code,
        currency_code=currency_code,
        price_multiplier=price_multiplier,
        availability_ceiling_titles=ceiling,
        catalog_tier_floor=tier_floor,
    )
    tier_overrides = {}
    if tier_monthly_price_cents is not None:
        tier_overrides["monthly_price_cents"] = tier_monthly_price_cents
    tier = create_tier(api, **tier_overrides)
    essential = create_essential_tier(api) if create_essential else None

    publisher = create_publisher(
        api,
        name=publisher_name or D["PUBLISHER_NAME"],
        home_region_code=region_code,
    )
    title = create_title(
        api,
        publisher["id"],
        name=title_name or D["TITLE_NAME"],
        platform_set=list(platform_set or D["TITLE_PLATFORM_SET"]),
        day_one_eligible=day_one_eligible,
        list_price_cents=list_price_cents if list_price_cents is not None
        else D["TITLE_LIST_PRICE_CENTS"],
        unit_sales_30d=unit_sales_30d if unit_sales_30d is not None
        else D["TITLE_UNIT_SALES_30D"],
    )
    deal = create_deal(api, publisher["id"], title["id"], **(deal_overrides or {}))
    if sign:
        deal = sign_deal(api, deal["id"], title["version"])
    if advance_to:
        set_clock(api, advance_to)

    return Scenario(
        region=region, tier=tier, essential_tier=essential, publisher=publisher,
        title=title, deal=deal, region_code=region_code,
    )


def scenario_with_published_entry(api, *, entry_overrides: dict = None,
                                  **scenario_kwargs) -> Scenario:
    """The standard scenario plus one published CATALOG_ADD entry."""
    sc = build_catalog_scenario(api, **scenario_kwargs)
    entry = create_entry(api, sc.title["id"], **(entry_overrides or {}))
    entry = publish_entry(api, entry["id"])
    sc.entry = entry
    sc.title = _data(api.get_title(sc.title["id"], ADMIN), "re-reading the title")
    return sc


def scenario_with_subscriber(api, *, subscriber_overrides: dict = None,
                             pay: bool = True, entry_overrides: dict = None,
                             **scenario_kwargs) -> Scenario:
    """The catalogue scenario plus one subscriber on a paid subscription and one
    published entry.

    The subscription is opened and settled BEFORE the entry is published, so the
    publication resolves an ACTIVE entitlement for it.
    """
    sc = build_catalog_scenario(api, **scenario_kwargs)
    subscriber = create_subscriber(api, **(subscriber_overrides or {}))
    # PRD §3.5: the subscription create supplies subscriber_id, tier_code and
    # billing_period only. The subscriber already carries home_region_code, and
    # the server resolves the billing region from it — passing it again would be
    # an undeclared field.
    subscription = open_subscription(
        api, subscriber["id"], tier_code=sc.tier["tier_code"],
    )
    if pay:
        subscription = pay_subscription(api, subscription["id"], subscriber["id"])
    entry = create_entry(api, sc.title["id"], **(entry_overrides or {}))
    entry = publish_entry(api, entry["id"])
    sc.subscriber = subscriber
    sc.subscription = subscription
    sc.entry = entry
    sc.title = _data(api.get_title(sc.title["id"], ADMIN), "re-reading the title")
    return sc

# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# ---------------------------------------------------------------------------

def scenario_with_two_published_entries(api, *,
                                        entry_a_overrides: dict = None,
                                        entry_b_overrides: dict = None,
                                        **scenario_kwargs) -> Scenario:
    """Two published entries for the same title in the same region."""
    sc = build_catalog_scenario(api, **scenario_kwargs)
    entry_a = create_entry(api, sc.title["id"], **(entry_a_overrides or {}))
    entry_b = create_entry(api, sc.title["id"], **(entry_b_overrides or {}))
    entry_a = publish_entry(api, entry_a["id"])
    entry_b = publish_entry(api, entry_b["id"])
    sc.entry_a = entry_a
    sc.entry_b = entry_b
    sc.entry = entry_a
    return sc


def _new_paid_subscription(api, scenario, *, email: str, display_name: str,
                           wallet_credit_cents: int = 0):
    subscriber = create_subscriber(
        api, email=email, display_name=display_name,
        home_region_code=scenario.region_code, wallet_credit_cents=wallet_credit_cents,
    )
    subscription = open_subscription(
        api, subscriber["id"], tier_code=scenario.tier["tier_code"],
    )
    subscription = pay_subscription(api, subscription["id"], subscriber["id"])
    return subscriber, subscription


def scenario_with_two_paid_subscribers(api, *,
                                       entry_a_overrides: dict = None,
                                       entry_b_overrides: dict = None,
                                       email_a: str = "ana@example.com",
                                       email_b: str = "bo@example.com",
                                       **scenario_kwargs) -> Scenario:
    """Two published entries and two subscribers each on a paid subscription.

    Each published entry therefore carries two ACTIVE entitlements.
    """
    sc = build_catalog_scenario(api, **scenario_kwargs)
    subr_a, sub_a = _new_paid_subscription(api, sc, email=email_a, display_name="Ana")
    subr_b, sub_b = _new_paid_subscription(api, sc, email=email_b, display_name="Bo")
    entry_a = create_entry(api, sc.title["id"], **(entry_a_overrides or {}))
    entry_b = create_entry(api, sc.title["id"], **(entry_b_overrides or {}))
    entry_a = publish_entry(api, entry_a["id"])
    entry_b = publish_entry(api, entry_b["id"])
    sc.subscriber_a, sc.subscription_a = subr_a, sub_a
    sc.subscriber_b, sc.subscription_b = subr_b, sub_b
    sc.entry_a, sc.entry_b, sc.entry = entry_a, entry_b, entry_a
    sc.title = _data(api.get_title(sc.title["id"], ADMIN), "re-reading the title")
    return sc


CATALOG_ADD_ENTRY_A = {
    "removal_date": "2026-11-30T00:00:00Z",
    "release_class": "CATALOG_ADD",
    "popularity_index_cents": 6000,
    "popularity_index_cents_30d_avg": 3000,
}

BACK_CATALOG_ENTRY_B = {
    "removal_date": "2026-12-30T00:00:00Z",
    "release_class": "BACK_CATALOG",
    "popularity_index_cents": 4000,
    "popularity_index_cents_30d_avg": 4000,
}


def scenario_with_two_subscribers_and_two_entries(api, **scenario_kwargs) -> Scenario:
    """Shared prefix for the retire cascade and the cancel cascade."""
    scan_kwargs = dict(scenario_kwargs)
    scan_kwargs.setdefault("entry_a_overrides", dict(CATALOG_ADD_ENTRY_A))
    scan_kwargs.setdefault("entry_b_overrides", dict(BACK_CATALOG_ENTRY_B))
    return scenario_with_two_paid_subscribers(api, **scan_kwargs)


def scenario_with_two_expiring_deals(api, *,
                                     entry_a_removal: str = "2027-09-01T00:00:00Z",
                                     entry_b_removal: str = "2027-03-20T00:00:00Z",
                                     advance_to: str = "2027-02-27T00:00:00Z") -> Scenario:
    """One publisher with two titles, one signed HYBRID deal each, both ending
    2027-03-01, each with one published CATALOG_ADD entry; the clock is then
    advanced so both deals are EXPIRING.
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    region = create_region(api)
    tier = create_tier(api)
    create_essential_tier(api)
    publisher = create_publisher(api)

    title_a = create_title(api, publisher["id"], name="Crimson Drift",
                           platform_set=["CONSOLE", "PC", "CLOUD"], day_one_eligible=True,
                           list_price_cents=7000, unit_sales_30d=25000)
    title_b = create_title(api, publisher["id"], name="Second Wind",
                           platform_set=["PC", "CLOUD"], day_one_eligible=False,
                           list_price_cents=4000, unit_sales_30d=9000)

    deal_a = create_deal(api, publisher["id"], title_a["id"])
    deal_b = create_deal(api, publisher["id"], title_b["id"])
    deal_a = sign_deal(api, deal_a["id"], title_a["version"])
    deal_b = sign_deal(api, deal_b["id"], title_b["version"])

    set_clock(api, "2026-09-02T00:00:00Z")
    # PRD §3.3: a tier whose access flags grant cloud streaming requires the
    # title to ship on CLOUD. Both titles therefore carry CLOUD in their
    # platform set, and entry_b names the ESSENTIAL tier so the two entries sit
    # on different tier weights.
    entry_a = create_entry(api, title_a["id"], removal_date=entry_a_removal,
                           tiers=["PREMIUM"],
                           release_class="CATALOG_ADD", popularity_index_cents=6000,
                           popularity_index_cents_30d_avg=3000)
    entry_b = create_entry(api, title_b["id"], removal_date=entry_b_removal,
                           tiers=["ESSENTIAL"],
                           release_class="CATALOG_ADD", popularity_index_cents=4000,
                           popularity_index_cents_30d_avg=4000)
    entry_a = publish_entry(api, entry_a["id"])
    entry_b = publish_entry(api, entry_b["id"])
    set_clock(api, advance_to)

    return Scenario(region=region, tier=tier, publisher=publisher,
                    title_a=title_a, title_b=title_b, deal_a=deal_a, deal_b=deal_b,
                    entry_a=entry_a, entry_b=entry_b, region_code="NA")


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------

def scenario_ready_to_purchase(api, *, wallet_credit_cents: int = 0,
                               email: str = "mira@example.com",
                               price_multiplier: float = 1.20,
                               list_price_cents: int = 7000,
                               entry_overrides: dict = None,
                               tier_overrides: dict = None,
                               **scenario_kwargs) -> Scenario:
    """Standard scenario plus a paid subscriber and one published entry, ready
    to buy the catalogue title outright.
    """
    sc = scenario_with_published_entry(
        api,
        price_multiplier=price_multiplier,
        list_price_cents=list_price_cents,
        entry_overrides=entry_overrides or dict(CATALOG_ADD_ENTRY_A),
        **scenario_kwargs,
    )
    subscriber = create_subscriber(api, email=email, display_name="Buyer",
                                   wallet_credit_cents=wallet_credit_cents)
    subscription = open_subscription(api, subscriber["id"],
                                     tier_code=sc.tier["tier_code"])
    subscription = pay_subscription(api, subscription["id"], subscriber["id"])
    sc.subscriber = subscriber
    sc.subscription = subscription
    return sc


def _buy(api, sc, *, quantity: int = 1, entry_id: str = None) -> dict:
    payload = {
        "subscriber_id": sc.subscriber["id"],
        "title_id": sc.title["id"],
        "entry_id": entry_id or sc.entry["id"],
        "region_code": sc.region_code,
        "quantity": quantity,
    }
    return _data(
        api.create_purchase(payload, make_subscriber_headers(sc.subscriber["id"])),
        "creating a purchase",
    )


def scenario_ready_to_finalize(api, *, purchases: int = 3,
                               entry_overrides: dict = None,
                               **scenario_kwargs) -> Scenario:
    """Standard scenario, one paid subscriber, one published CATALOG_ADD entry,
    an AvailabilityProjection for the day-one release, and `purchases`
    COMPLETED purchases of the same title and region.
    """
    sc = scenario_ready_to_purchase(
        api, entry_overrides=entry_overrides or dict(CATALOG_ADD_ENTRY_A),
        **scenario_kwargs
    )
    projection = _data(
        api.create_availability_projection(
            {
                "title_id": sc.title["id"],
                "region_code": sc.region_code,
                "launch_subscriber_count": 1000,
                "tier_step_count": 2,
                "projected_unit_sales_units": 500,
                "release_class": "DAY_ONE",
            },
            ANALYST,
        ),
        "creating an availability projection",
    )
    sc.projection = projection
    sc.purchases = []
    for _ in range(purchases):
        sc.purchases.append(_buy(api, sc))
    return sc


def scenario_for_projection_boundary(api, **scenario_kwargs) -> Scenario:
    """The published-entry scenario the day-one decision ladder is read against."""
    sc = scenario_with_published_entry(api, entry_overrides=dict(CATALOG_ADD_ENTRY_A),
                                       **scenario_kwargs)
    return sc


def create_projection(api, sc, **overrides) -> dict:
    payload = {
        "title_id": sc.title["id"],
        "region_code": sc.region_code,
        "launch_subscriber_count": 1000,
        "tier_step_count": 2,
        "projected_unit_sales_units": 500,
        "release_class": "DAY_ONE",
    }
    payload.update(overrides)
    return _data(api.create_availability_projection(payload, ANALYST),
                 "creating an availability projection")


# ---------------------------------------------------------------------------
# Tier 5 — terminal states and regional variants
# ---------------------------------------------------------------------------

def scenario_with_maintenance(api, windows: list, *, region_code: str = "NA",
                              ceiling: int = 4000, **region_overrides) -> Scenario:
    """A region created together with planned maintenance windows."""
    set_clock(api, "2026-09-02T00:00:00Z")
    region = _data(
        api.create_region(
            create_region_payload(
                region_code=region_code,
                availability_ceiling_titles=ceiling,
                maintenance_windows=windows,
                **region_overrides,
            ),
            ADMIN,
        ),
        "creating a region with maintenance windows",
    )
    return Scenario(region=region, region_code=region_code)


def list_maintenances(api, **params) -> list:
    return _rows(api.list_catalog_maintenances(ADMIN, params=params or None),
                 "listing maintenance windows")


def capacity_scenario(api, *, region_code: str = "JP", currency_code: str = "JPY",
                      price_multiplier: float = 1.10, ceiling: int = 400,
                      entries: list = None, **scenario_kwargs) -> Scenario:
    """The standard scenario plus a second region carrying planned entries.

    `entries` is a list of payload overrides; every entry is created and
    published in `region_code` unless its override says `published: false`.
    """
    sc = build_catalog_scenario(api, **scenario_kwargs)
    extra_region = create_region(
        api, region_code=region_code, currency_code=currency_code,
        price_multiplier=price_multiplier, availability_ceiling_titles=ceiling,
        catalog_tier_floor="ESSENTIAL",
    )
    created = []
    for overrides in (entries or []):
        overrides = dict(overrides)
        should_publish = overrides.pop("published", True)
        payload_overrides = dict(overrides)
        payload_overrides["region_code"] = region_code
        entry = create_entry(api, sc.title["id"], **payload_overrides)
        if should_publish:
            entry = publish_entry(api, entry["id"])
        created.append(entry)
    sc.extra_region = extra_region
    sc.extra_entries = created
    sc.capacity_region_code = region_code
    return sc
