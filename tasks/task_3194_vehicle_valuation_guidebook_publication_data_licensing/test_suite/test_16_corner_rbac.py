"""Corner-design section: rbac (role denials)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_region, make_config, make_source, make_series, make_edition,
    make_consumer, setup_published_edition, setup_active_agreement,
    setup_redeemed_offer_with_dispute,
    create_batch_payload, create_batch_item_payload,
    create_market_shift_payload, create_cash_offer_payload,
    make_dealer_headers, make_consumer_headers, make_licensee_headers,
    ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def test_consumer_cannot_publish_edition(api):
    """PRD §3.4: "Publication — PENDING -> PUBLISHED, performed by a
    ValuationAdmin — is the most heavily guarded transition in the system."
    and PRD §2.1: "A request whose declared role is not permitted to call the
    target endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/consumer_cannot_publish_edition
    """
    env = setup_published_edition(segment="SEDAN", price_cents=2000000)
    series = env["series"]
    pending = validate_success(api.create_valuation_edition(
        {"series_id": series["id"], "effective_at": "2026-09-08T00:00:00Z"},
        ADMIN), 201)
    consumer = make_consumer(email="rb1@x.com", full_name="Rb One")

    res = api.publish_valuation_edition(
        pending["id"], make_consumer_headers(consumer["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_dealer_cannot_create_market_shift(api):
    """PRD §3.5: "A MarketShift expresses a signed percentage adjustment to
    be blended into future editions" (a ValuationAdmin workflow per PRD §2.1,
    which states ValuationAdmin "owns publication, licensing, market shifts,
    standards, methodologies, and dispute resolution") and PRD §2.1: "A
    request whose declared role is not permitted to call the target endpoint
    is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/dealer_cannot_create_market_shift
    """
    region = make_region(region_code="EAST")
    dealer = make_source(region["id"], source_type="DEALER",
                         external_key="src-rb2", name="RB2D")

    res = api.create_market_shift(
        create_market_shift_payload(region_id=region["id"], segment=None,
                                    effective_at="2026-09-02T00:00:00Z",
                                    pct_adjustment=0.01),
        make_dealer_headers(dealer["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_dataops_cannot_resolve_dispute(api):
    """PRD §3.7: "Resolution belongs to ValuationAdmin and takes a resolution
    of UPHELD or ADJUSTED." and PRD §2.1: "A request whose declared role is
    not permitted to call the target endpoint is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/dataops_cannot_resolve_dispute
    """
    env = setup_redeemed_offer_with_dispute(segment="SEDAN",
                                            price_cents=2000000)
    dispute = env["dispute"]

    res = api.resolve_dispute(dispute["id"], {"resolution": "UPHELD"}, DATAOPS)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)
    fetched = validate_success(api.get_dispute(dispute["id"], ADMIN), 200)
    assert fetched["status"] == "OPEN"


def test_valuation_admin_cannot_ingest_batches(api):
    """PRD §2.1: "Duties are deliberately segregated between the two operator
    roles. DataOps owns the ingestion pipeline (sources, batches,
    corrections) and never touches publication, licensing, or methodology.
    ValuationAdmin owns publication, licensing, market shifts, standards,
    methodologies, and dispute resolution, and never touches ingestion." and
    "A request whose declared role is not permitted to call the target
    endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/valuation_admin_cannot_ingest_batches
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-rb4")
    dealer = make_source(region["id"], source_type="DEALER",
                         external_key="src-rb4", name="RB4D")

    res = api.create_batch(
        create_batch_payload(
            dealer["id"],
            [create_batch_item_payload(config["id"], region["id"],
                                       sold_price_cents=2000000)],
            submission_ref="b-rb4"),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_licensee_use_not_permitted_denied(api):
    """PRD §3.8: "the requested use must be within the agreement's
    permitted_uses — UNDERWRITING for offer creation, and SETTLEMENT or
    DISPLAY for edition reads per the licensee's declared purpose (otherwise
    ERR_USE_NOT_PERMITTED, HTTP 403)".

    Design: Corner/rbac/licensee_use_not_permitted_denied
    """
    env = setup_published_edition(segment="SEDAN", price_cents=2000000)
    edition = env["edition"]
    source = env["source"]
    consumer = make_consumer(email="rb5@x.com", full_name="Rb Five")
    lic = setup_active_agreement(permitted_uses=("DISPLAY",),
                                 monthly_event_quota=1500,
                                 version_label="v2026.09")
    agreement = lic["agreement"]

    payload = create_cash_offer_payload(
        edition["id"], source["id"], consumer["id"],
        mileage=20000, age_years=2, declared_condition_tier="GOOD",
        option_ids=[])
    payload["purpose"] = "UNDERWRITING"
    res = api.create_cash_offer(payload, make_licensee_headers(agreement["id"]))
    validate_error(res, ApiErrorId.ERR_USE_NOT_PERMITTED.value)

    data, meta = validate_paginated(
        api.list_agreement_events(agreement["id"], ADMIN))
    assert meta["total_count"] == 0, (
        "the rejected request must record no billable event")
