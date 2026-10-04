"""Corner-design section: state_machines."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_region, make_config, make_source, make_series, get_edition,
    submit_batch, submit_accepted_batch, setup_offer_scenario,
    create_batch_payload, create_batch_item_payload,
    ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS
from datetime import datetime, timedelta


class TestBatchValidTransitionReceivedToValidated:
    def test_validate_moves_received_to_validated_and_bumps_version(self, api):
        """PRD §3.2: "New batches start RECEIVED." and "Validation moves it
        RECEIVED -> VALIDATED." and PRD §2.5: "version (integer): a
        system-managed counter that increments by one on every mutation of
        the resource, including state transitions".

        Design: Corner/state_machines/batch_valid_transition_received_to_validated
        """
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN", external_key="cfg-sm")
        source = make_source(region["id"], source_type="DEALER",
                             external_key="src-sm", name="SMD")
        batch = submit_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"],
                                      sold_price_cents=2000000),
        ], submission_ref="b-sm")
        assert batch["status"] == "RECEIVED"
        assert batch["version"] == 1

        validated = validate_success(api.validate_batch(batch["id"], DATAOPS), 200)
        assert validated["status"] == "VALIDATED"
        assert validated["version"] == 2


def test_validate_from_accepted_returns_invalid_state(api):
    """PRD §3.2: "Validation moves it RECEIVED -> VALIDATED." — a batch in
    terminal ACCEPTED state is not RECEIVED, so re-validation fails the
    state-precondition check with ERR_INVALID_STATE (HTTP 409).

    Design: Corner/state_machines/validate_from_accepted_returns_invalid_state
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-sm2")
    source = make_source(region["id"], source_type="DEALER",
                         external_key="src-sm2", name="SM2D")
    batch = submit_accepted_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2000000),
    ], submission_ref="b-sm2")
    assert batch["status"] == "ACCEPTED"

    res = api.validate_batch(batch["id"], DATAOPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_offer_initial_state_is_quoted(api):
    """PRD §3.6: "The offer starts QUOTED, and its expires_at is the pinned
    edition's published_at plus 7 days." and PRD §3.6: final_amount_cents is
    only "Set on inspection" — before inspection it is unset.

    Design: Corner/state_machines/offer_initial_state_is_quoted
    """
    env = setup_offer_scenario(segment="SEDAN", price_cents=3040000)
    offer = env["offer"]
    assert offer["status"] == "QUOTED"
    assert offer.get("final_amount_cents") is None
    published_at = env["edition"]["published_at"]
    pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    exp = datetime.fromisoformat(offer["expires_at"].replace("Z", "+00:00"))
    assert exp - pub == timedelta(days=7)


def test_superseded_series_is_terminal(api):
    """PRD §3.3: "A successful supersession flips the old series to
    SUPERSEDED (bumping its version) and withdraws every one of its
    still-PENDING editions, while the new series starts in DRAFT." and the
    series lifecycle only activates from DRAFT — "Activation moves a series
    DRAFT -> ACTIVE" — so activating a SUPERSEDED series fails the state
    precondition with ERR_INVALID_STATE.

    Design: Corner/state_machines/superseded_series_is_terminal
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-ts")
    first = validate_success(api.create_valuation_series(
        {"configuration_id": config["id"], "region_id": region["id"],
         "effective_from": "2026-09-01T00:00:00Z", "cadence": "WEEKLY",
         "external_key": "ser-ts1"},
        ADMIN), 201)
    first = validate_success(
        api.activate_valuation_series(first["id"], ADMIN), 200)
    current = validate_success(
        api.get_valuation_series(first["id"], ADMIN), 200)

    replacement = validate_success(api.create_valuation_series(
        {"configuration_id": config["id"], "region_id": region["id"],
         "effective_from": "2026-09-08T00:00:00Z", "cadence": "WEEKLY",
         "external_key": "ser-ts2",
         "expected_version": current["version"]},
        ADMIN), 201)
    assert replacement["status"] == "DRAFT"

    old = validate_success(api.get_valuation_series(first["id"], ADMIN), 200)
    assert old["status"] == "SUPERSEDED"

    res = api.activate_valuation_series(first["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_batch_submission_ref_replay_returns_existing_batch(api):
    """PRD §2.9: "submitting a transaction batch is keyed on submission_ref.
    A replay presenting the same key with the same payload returns the
    existing resource instead of creating a duplicate."

    Design: Corner/state_machines/batch_submission_ref_replay_returns_existing_batch
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-idem")
    source = make_source(region["id"], source_type="DEALER",
                         external_key="src-idem", name="IDEMD")
    payload = create_batch_payload(
        source["id"],
        [create_batch_item_payload(config["id"], region["id"],
                                   sold_price_cents=2000000)],
        submission_ref="dup-1")
    first = validate_success(api.create_batch(payload, DATAOPS), 201)
    replay = validate_success(api.create_batch(payload, DATAOPS), 201)
    assert replay["id"] == first["id"]
    assert replay["version"] == first["version"]

    data, meta = validate_paginated(
        api.list_batches(DATAOPS, params={"source_id": source["id"]}))
    assert meta["total_count"] == 1
