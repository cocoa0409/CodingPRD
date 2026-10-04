"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: entity-backed roles (DealerPartner, Consumer, Licensee)
always use make_*_headers(<entity id>) for ownership-gated calls — never the
shared TEST_USERS fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_region_payload, create_source_payload, create_configuration_payload,
    create_batch_item_payload, create_batch_payload, create_series_payload,
    create_edition_payload, create_market_shift_payload,
    create_cash_offer_payload, create_license_agreement_payload,
    create_dispute_payload, create_methodology_payload,
    create_option_package_payload, create_consumer_profile_payload,
    create_correction_payload,
)
from .test_users import (
    TEST_USERS, make_dealer_headers, make_consumer_headers, make_licensee_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DATAOPS = TEST_USERS["dataops_headers"]

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"


# --- Tier 1: single-entity creation + state progression ---

def make_region(region_code="EAST", name="East Region") -> dict:
    res = api_client.create_region(
        create_region_payload(region_code=region_code, name=name), ADMIN)
    return get_success_data(res)


def make_config(segment="SEDAN", annual_expected_miles=10000, **overrides) -> dict:
    res = api_client.create_configuration(
        create_configuration_payload(
            segment=segment, annual_expected_miles=annual_expected_miles,
            **overrides),
        ADMIN)
    return get_success_data(res)


def make_source(region_id, source_type="DEALER", activate=True, **overrides) -> dict:
    res = api_client.create_source(
        create_source_payload(region_id, source_type=source_type, **overrides),
        DATAOPS)
    source = get_success_data(res)
    if activate:
        source = get_success_data(api_client.activate_source(source["id"], DATAOPS))
    return source


def make_option(configuration_id, option_code, credit_cents) -> dict:
    res = api_client.create_configuration_option_package(
        configuration_id,
        {"option_code": option_code, "credit_cents": credit_cents},
        ADMIN)
    return get_success_data(res)


def make_consumer(**overrides) -> dict:
    res = api_client.create_consumer_profile(
        create_consumer_profile_payload(**overrides),
        # Consumer role; X-User-ID is a fresh opaque id for profile creation.
        make_consumer_headers(f"self-register-{id(overrides)}"),
    )
    return get_success_data(res)


def make_methodology(publish=True, version_label="v2026.09",
                     formula_hash="hash-1") -> dict:
    res = api_client.create_methodology(
        create_methodology_payload(
            version_label=version_label, formula_hash=formula_hash),
        ADMIN)
    methodology = get_success_data(res)
    if publish:
        methodology = get_success_data(
            api_client.publish_methodology(methodology["id"], ADMIN))
    return methodology


def make_agreement(permitted_uses=("DISPLAY",), monthly_event_quota=1500,
                   activate=False, **overrides) -> dict:
    res = api_client.create_license_agreement(
        create_license_agreement_payload(
            permitted_uses=list(permitted_uses),
            monthly_event_quota=monthly_event_quota,
            **overrides),
        ADMIN)
    agreement = get_success_data(res)
    if activate:
        agreement = get_success_data(
            api_client.activate_license_agreement(agreement["id"], ADMIN))
    return agreement


# --- Tier 2: batch pipeline ---

def submit_batch(source_id, items, submission_ref=None) -> dict:
    """Create a batch only (status RECEIVED)."""
    payload = create_batch_payload(source_id, items)
    if submission_ref is not None:
        payload["submission_ref"] = submission_ref
    return get_success_data(api_client.create_batch(payload, DATAOPS))


def submit_accepted_batch(source_id, items, submission_ref=None) -> dict:
    """Create -> validate -> accept. Returns ACCEPTED batch."""
    batch = submit_batch(source_id, items, submission_ref=submission_ref)
    get_success_data(api_client.validate_batch(batch["id"], DATAOPS))
    return get_success_data(api_client.accept_batch(batch["id"], DATAOPS))


def submit_rejected_batch(source_id, items, submission_ref=None) -> dict:
    """Create -> reject. Returns REJECTED batch."""
    batch = submit_batch(source_id, items, submission_ref=submission_ref)
    return get_success_data(api_client.reject_batch(batch["id"], DATAOPS))


def reject_n_batches(source_id, configuration_id, region_id, n, ref_prefix) -> dict:
    """Submit and reject n batches against the same source. Returns the source."""
    for i in range(1, n + 1):
        submit_rejected_batch(
            source_id,
            [create_batch_item_payload(configuration_id, region_id)],
            submission_ref=f"{ref_prefix}-{i}",
        )
    return get_success_data(api_client.get_source(source_id, DATAOPS))


# --- Tier 3: series + edition lifecycle ---

def make_series(configuration_id, region_id,
                effective_from=CLOCK_DEFAULT, activate=True,
                expected_version=None, **overrides) -> dict:
    payload = create_series_payload(
        configuration_id, region_id, effective_from=effective_from, **overrides)
    if expected_version is not None:
        payload["expected_version"] = expected_version
    series = get_success_data(api_client.create_valuation_series(payload, ADMIN))
    if activate:
        series = get_success_data(
            api_client.activate_valuation_series(series["id"], ADMIN))
    return series


def make_edition(series_id, effective_at=CLOCK_DEFAULT, publish=False) -> dict:
    edition = get_success_data(api_client.create_valuation_edition(
        create_edition_payload(series_id, effective_at=effective_at), ADMIN))
    if publish:
        edition = get_success_data(
            api_client.publish_valuation_edition(edition["id"], ADMIN))
    return edition


def get_series(series_id) -> dict:
    return get_success_data(api_client.get_valuation_series(series_id, ADMIN))


def get_edition(edition_id) -> dict:
    return get_success_data(api_client.get_valuation_edition(edition_id, ADMIN))


def get_offer(offer_id) -> dict:
    return get_success_data(api_client.get_cash_offer(offer_id, ADMIN))


def get_source(source_id) -> dict:
    return get_success_data(api_client.get_source(source_id, DATAOPS))


# --- Tier 4: full bootstrap composites ---

def setup_published_edition(segment="SEDAN", price_cents=3040000,
                            sale_date="2026-08-20", region_code="EAST",
                            effective_from=CLOCK_DEFAULT,
                            annual_expected_miles=10000,
                            num_items=1, **config_overrides) -> dict:
    """Region + config + ACTIVE DEALER source + one ACCEPTED batch
    (num_items identical items) + ACTIVE series + PUBLISHED edition.

    With recent sale dates the single-source confidence is
    0.5*(n/30) + 0.3*(1/3) + 0.2*1 which is >= 0.25 for n >= 1, so
    publication succeeds.
    """
    region = make_region(region_code=region_code)
    config = make_config(segment=segment,
                         annual_expected_miles=annual_expected_miles,
                         **config_overrides)
    source = make_source(region["id"], source_type="DEALER", activate=True)
    items = [
        create_batch_item_payload(
            config["id"], region["id"],
            sold_price_cents=price_cents, sale_date=sale_date,
            mileage=10000 + i)
        for i in range(num_items)
    ]
    batch = submit_accepted_batch(source["id"], items)
    series = make_series(config["id"], region["id"], effective_from=effective_from)
    edition = make_edition(series["id"], effective_at=effective_from, publish=True)
    return {
        "region": region, "configuration": config, "source": source,
        "batch": batch, "series": series, "edition": edition,
    }


def setup_offer(edition, source, consumer, **offer_overrides) -> dict:
    """Create a QUOTED offer as the DealerPartner funding it."""
    payload = create_cash_offer_payload(
        edition["id"], source["id"], consumer["id"], **offer_overrides)
    return get_success_data(
        api_client.create_cash_offer(payload, make_dealer_headers(source["id"])))


def setup_offer_scenario(segment="SEDAN", price_cents=3040000,
                         sale_date="2026-08-20", region_code="EAST",
                         effective_from=CLOCK_DEFAULT,
                         annual_expected_miles=10000,
                         offer_overrides=None, **config_overrides) -> dict:
    """Bootstrap through PUBLISHED edition plus a consumer plus one QUOTED offer."""
    env = setup_published_edition(
        segment=segment, price_cents=price_cents, sale_date=sale_date,
        region_code=region_code, effective_from=effective_from,
        annual_expected_miles=annual_expected_miles, **config_overrides)
    consumer = make_consumer()
    offer = setup_offer(env["edition"], env["source"], consumer,
                        **(offer_overrides or {}))
    env["consumer"] = consumer
    env["offer"] = offer
    return env


def inspect_offer(offer_id, source_id, inspected_condition_tier="GOOD") -> dict:
    return get_success_data(api_client.inspect_cash_offer(
        offer_id, {"inspected_condition_tier": inspected_condition_tier},
        make_dealer_headers(source_id)))


def redeem_offer(offer_id, source_id) -> dict:
    return get_success_data(
        api_client.redeem_cash_offer(offer_id, make_dealer_headers(source_id)))


def setup_redeemed_offer(**kwargs) -> dict:
    """Full path: bootstrap + QUOTED -> INSPECTED(GOOD) -> REDEEMED."""
    env = setup_offer_scenario(**kwargs)
    offer = env["offer"]
    src_id = env["source"]["id"]
    offer = inspect_offer(offer["id"], src_id, "GOOD")
    offer = redeem_offer(offer["id"], src_id)
    env["offer"] = offer
    return env


def setup_redeemed_offer_with_dispute(**kwargs) -> dict:
    """REDEEMED offer plus one OPEN dispute filed by the owning consumer."""
    env = setup_redeemed_offer(**kwargs)
    dispute = get_success_data(api_client.create_dispute(
        create_dispute_payload(env["offer"]["id"]),
        make_consumer_headers(env["consumer"]["id"])))
    env["dispute"] = dispute
    return env


def setup_active_agreement(permitted_uses=("DISPLAY",), monthly_event_quota=1500,
                           version_label="v2026.09", **overrides) -> dict:
    """Publish a methodology, then create + activate an agreement."""
    methodology = make_methodology(publish=True, version_label=version_label)
    agreement = make_agreement(permitted_uses=permitted_uses,
                               monthly_event_quota=monthly_event_quota,
                               activate=True, **overrides)
    return {"methodology": methodology, "agreement": agreement}
