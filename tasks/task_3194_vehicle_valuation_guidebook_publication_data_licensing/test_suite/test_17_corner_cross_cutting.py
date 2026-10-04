"""Corner-design section: cross_cutting_layers."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_region, make_config, make_source, make_series,
    create_source_payload, get_series, submit_accepted_batch,
    create_batch_item_payload, setup_offer_scenario,
    get_edition, get_offer, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def test_occ_stale_version_on_series_supersede(api):
    """PRD §2.7: "Creating a replacement valuation series for a
    (configuration_id, region_id) pair that already has an ACTIVE series
    requires the caller to present expected_version carrying the version of
    that active series as the caller last observed it. If the presented value
    is older than the series' current version — because another writer has
    advanced it since the caller's last read — the create is rejected with
    ERR_STALE_VERSION (HTTP 412), reducing what would have been a racing
    supersede mutation to a sequential stale-version check."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_series_supersede
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-occ2")
    first = validate_success(api.create_valuation_series(
        {"configuration_id": config["id"], "region_id": region["id"],
         "effective_from": "2026-09-01T00:00:00Z", "cadence": "WEEKLY",
         "external_key": "ser-occ2a"},
        ADMIN), 201)
    first = validate_success(
        api.activate_valuation_series(first["id"], ADMIN), 200)
    current = validate_success(
        api.get_valuation_series(first["id"], ADMIN), 200)
    assert current["version"] == 2

    res = api.create_valuation_series(
        {"configuration_id": config["id"], "region_id": region["id"],
         "effective_from": "2026-09-08T00:00:00Z", "cadence": "WEEKLY",
         "external_key": "ser-occ2b",
         "expected_version": current["version"] - 1},
        ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(
        api.get_valuation_series(first["id"], ADMIN), 200)
    assert after["status"] == "ACTIVE"


def test_derived_confidence_reconciles_on_new_batch(api):
    """PRD §3.3: "The score is recomputed after each batch acceptance, after
    each data correction, and on series activation" and "The three weighted
    terms sum, and the result is rounded half-up to 4 decimal places."

    From 1 stale item, one source type (0.5*(1/30) + 0.3*(1/3) + 0.2*0 =
    0.1167) to 9 stale items, one source type (0.5*(9/30) + 0.3*(1/3) + 0 =
    0.2500) after an 8-item batch accept; the series stays ACTIVE.

    Design: Corner/cross_cutting_layers/derived_confidence_reconciles_on_new_batch
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-der")
    source = make_source(region["id"], source_type="DEALER",
                         external_key="src-der", name="DERD")
    submit_accepted_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2000000,
                                  sale_date="2026-07-31", mileage=10000),
    ], submission_ref="b-der1")
    series = make_series(config["id"], region["id"], external_key="ser-der")
    assert get_series(series["id"])["confidence_score"] == pytest.approx(
        0.1167, abs=1e-4)

    items = [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2000000,
                                  sale_date="2026-07-31",
                                  mileage=11000 + i)
        for i in range(8)
    ]
    submit_accepted_batch(source["id"], items, submission_ref="b-der2")

    fetched = get_series(series["id"])
    assert fetched["confidence_score"] == pytest.approx(0.25, abs=1e-9)
    assert fetched["status"] == "ACTIVE"


def test_idempotent_source_creation_replays_existing(api):
    """PRD §2.9: "Registering a source, creating a configuration, and
    creating a valuation series are each keyed on a caller-supplied
    external_key (unique per source for sources; globally unique for
    configurations and series); submitting a transaction batch is keyed on
    submission_ref. A replay presenting the same key with the same payload
    returns the existing resource instead of creating a duplicate. A replay
    that presents an already-used key with a different payload — or a
    submission_ref reused for a different batch body — is rejected with
    ERR_DUPLICATE_KEY (HTTP 409)."

    Design: Corner/cross_cutting_layers/idempotent_source_creation_replays_existing
    """
    region = make_region(region_code="EAST")
    payload = create_source_payload(region["id"], source_type="DEALER",
                                    name="Dup", external_key="ext-dup")
    first = validate_success(api.create_source(payload, DATAOPS), 201)
    replay = validate_success(api.create_source(payload, DATAOPS), 201)
    assert replay["id"] == first["id"]
    assert replay["version"] == first["version"]

    changed = dict(payload)
    changed["source_type"] = "AUCTION"
    changed["name"] = "DupChanged"
    res = api.create_source(changed, DATAOPS)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_cascade_visible_in_same_response(api):
    """PRD §2.11: "State changes propagate across aggregate boundaries
    without an explicit client request on the affected resource. When a
    published edition is withdrawn, every cash offer built on it that is
    still QUOTED transitions to VOID in the same operation."

    Design: Corner/consistency_model/cascade_visible_in_same_response
    """
    env = setup_offer_scenario(segment="SEDAN", price_cents=2000000)
    edition = env["edition"]
    offer = env["offer"]
    assert offer["status"] == "QUOTED"

    withdrawn = validate_success(
        api.withdraw_valuation_edition(edition["id"], ADMIN), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_edition(edition["id"])["status"] == "WITHDRAWN"
    assert get_offer(offer["id"])["status"] == "VOID"
