"""Corner-design section: validations."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_region, make_config, make_source, make_series, make_edition,
    make_consumer, submit_accepted_batch, create_batch_item_payload,
    create_source_payload, create_market_shift_payload,
    create_cash_offer_payload, make_dealer_headers,
    setup_offer_scenario, get_offer, NON_EXISTENT_UUID, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request whose X-User-Role header is missing or does not
    name one of these roles — or whose X-User-ID is missing for an
    entity-backed role — is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    res = api.list_regions(headers={"X-User-ID": "nobody"})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_priority_auth_beats_not_found(api):
    """PRD §2.10: "When several checks could reject the same request, they
    are evaluated in a fixed priority order so that the surfaced error is
    deterministic. Authentication (missing or unknown role header) comes
    first, then authorization (role not permitted), then existence (path or
    body references failing to resolve), then idempotency-key conflicts, then
    state-precondition failures (ERR_INVALID_STATE), then license gates
    (ERR_LICENSE_INACTIVE), then business rules in their documented order
    (funding source eligibility, confidence gate, cadence, offer expiry,
    quota, permitted use, archived region), then input shape
    (ERR_INVALID_INPUT), then OCC staleness (ERR_STALE_VERSION), then
    duplicate-dispute uniqueness, then shift-in-past, then the
    edition-withdrawal open-offer guard."

    A request that is both unauthenticated AND references a non-existent
    resource surfaces ERR_UNAUTHENTICATED.

    Design: Corner/validations/priority_auth_beats_not_found
    """
    res = api.get_region(NON_EXISTENT_UUID, headers={"X-User-ID": "nobody"})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_region_archived_blocks_new_source(api):
    """PRD §3.1: "Regions still in ACTIVE are a precondition on several
    creation paths: registering a source into a region, creating a valuation
    series for a region, creating a market shift scoped to a region, or
    submitting a batch whose items target a region all fail with
    ERR_REGION_ARCHIVED (HTTP 422) when the named region has been archived."

    Design: Corner/validations/region_archived_blocks_new_source
    """
    region = make_region(region_code="NORTH", name="North Region")
    validate_success(api.patch_region(
        region["id"], {"status": "ARCHIVED"}, ADMIN), 200)

    res = api.create_source(
        create_source_payload(region["id"], source_type="DEALER", name="Late",
                              external_key="src-late"),
        DATAOPS)
    validate_error(res, ApiErrorId.ERR_REGION_ARCHIVED.value)


def test_shift_activation_in_past_rejected(api):
    """PRD §3.5: "The effective_at must not be earlier than the server clock
    at activation — a shift activated into the past is rejected with
    ERR_SHIFT_IN_PAST (HTTP 422)."

    Design: Corner/validations/shift_activation_in_past_rejected
    """
    validate_success(api.set_clock("2026-09-10T00:00:00Z", ADMIN), 200)
    region = make_region(region_code="EAST")
    shift = validate_success(api.create_market_shift(
        create_market_shift_payload(region_id=region["id"], segment=None,
                                    effective_at="2026-09-01T00:00:00Z",
                                    pct_adjustment=0.02),
        ADMIN), 201)
    res = api.activate_market_shift(shift["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_SHIFT_IN_PAST.value)


def test_funding_source_must_be_dealer(api):
    """PRD §3.6: "The funding dealer must resolve to a source whose
    source_type is DEALER; anything else is rejected with
    ERR_INVALID_FUNDING_SOURCE (HTTP 422)."

    Design: Corner/validations/funding_source_must_be_dealer
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-fund")
    dealer = make_source(region["id"], source_type="DEALER",
                         external_key="src-fund-d", name="FUNDD")
    lender = make_source(region["id"], source_type="LENDER",
                         external_key="src-fund-l", name="FUNDL")
    submit_accepted_batch(dealer["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2000000,
                                  sale_date="2026-08-20", mileage=10000),
    ], submission_ref="b-fund")
    series = make_series(config["id"], region["id"], external_key="ser-fund")
    edition = make_edition(series["id"], publish=True)
    consumer = make_consumer(email="fund@x.com", full_name="Fund")

    res = api.create_cash_offer(
        create_cash_offer_payload(
            edition["id"], lender["id"], consumer["id"],
            mileage=20000, age_years=2, declared_condition_tier="GOOD",
            option_ids=[]),
        make_dealer_headers(dealer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_FUNDING_SOURCE.value)


def test_offer_expiry_blocks_inspect(api):
    """PRD §2.4: "Every cash offer still in QUOTED or INSPECTED status whose
    expires_at is earlier than the new clock value transitions to EXPIRED at
    the moment of the advance." and PRD §3.6: "A DealerPartner inspects a
    QUOTED offer" — an EXPIRED offer is not QUOTED, so inspection fails the
    state precondition with ERR_INVALID_STATE.

    Design: Corner/validations/offer_expiry_blocks_inspect
    """
    env = setup_offer_scenario(segment="SEDAN", price_cents=2000000)
    offer = env["offer"]
    source = env["source"]
    validate_success(api.set_clock("2026-09-20T00:00:00Z", ADMIN), 200)

    assert get_offer(offer["id"])["status"] == "EXPIRED"
    res = api.inspect_cash_offer(
        offer["id"], {"inspected_condition_tier": "GOOD"},
        make_dealer_headers(source["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
