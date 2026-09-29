"""Requests that violate two rules at once, where §2.8 fixes which one answers."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CREDIT_INSUFFICIENT,
    ERR_PRACTICE_PERIOD_OVERLAP,
    ERR_TRADING_SUSPENDED,
    ERR_ZONE_NOT_ELIGIBLE,
)
from test_helpers.assertions import assert_batch_buckets, assert_pagination_meta
from test_helpers.test_users import ADMIN, PERMITTEE_1, REGISTRY, make_producer_headers


def test_suspension_answers_before_the_batch_balance_is_even_consulted(api):
    """A wildly over-large purchase into a held watershed reports the suspension.

    "because the program-suspension check sits at position 12, ahead of every
    fiscal and geographic check, a proposal into a suspended watershed reports
    `ERR_TRADING_SUSPENDED` rather than being masked by an insufficient-balance or
    ineligible-geography finding."

    Design: Difficulty/priority_pair_validation_conflict/trading_suspended_outranks_credit_insufficient_on_transaction_proposal
    """
    world = fx.scr_trading_ready(api)
    batch_version = fx.read_batch_version(api, world["batch_id"])
    fx.set_program_status(api, world["watershed_id"], "ADAPTIVE_HOLD", "Interim target missed")

    refused = api.propose_credit_transaction(
        f.credit_transaction_payload(
            world["batch_id"], world["permit_id"], 10000.00, 2026, batch_version
        ),
        PERMITTEE_1,
    )

    validate_error(refused, ERR_TRADING_SUSPENDED, 409)

    rows, meta = validate_paginated(
        api.list_credit_transactions(REGISTRY, {"credit_batch_id": world["batch_id"]})
    )
    assert_pagination_meta(meta, 10, 0, 0, False)
    assert rows == [], rows

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(batch, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)


def test_resuming_the_program_uncovers_the_masked_insufficient_balance(api):
    """The identical payload reports the fiscal fault once trading is open again.

    "The requested quantity does not exceed the batch's unencumbered balance —
    `ERR_CREDIT_INSUFFICIENT`. Applies to credit-transaction proposal, where
    `requested_gross_lbs` may not exceed the batch's `available_lbs`"

    Design: Difficulty/priority_pair_validation_conflict/trading_suspended_outranks_credit_insufficient_on_transaction_proposal
    """
    world = fx.scr_trading_ready(api)
    batch_version = fx.read_batch_version(api, world["batch_id"])
    payload = f.credit_transaction_payload(
        world["batch_id"], world["permit_id"], 10000.00, 2026, batch_version
    )

    fx.set_program_status(api, world["watershed_id"], "ADAPTIVE_HOLD", "Interim target missed")
    validate_error(
        api.propose_credit_transaction(payload, PERMITTEE_1), ERR_TRADING_SUSPENDED, 409
    )

    resumed = fx.set_program_status(api, world["watershed_id"], "ACTIVE", "Target back on track")
    assert resumed["program_status"] == "ACTIVE", resumed
    assert resumed["trading_enabled"] is True, resumed

    refused = api.propose_credit_transaction(payload, PERMITTEE_1)
    validate_error(refused, ERR_CREDIT_INSUFFICIENT, 409)

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(batch, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)


def _tract_occupied_world(api):
    """SCR hydrology, a producer, and one live COVER_CROP project on tract T-101."""
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    reaches = fx.scr_reaches(api, watershed["id"], with_background=True)
    producer = fx.make_producer(api)
    pp_a = fx.make_practice_project(
        api,
        producer["id"],
        reaches["r_up"]["id"],
        "T-101",
        practice_type="COVER_CROP",
        effective_start_date="2026-01-01",
        effective_end_date="2027-01-01",
    )
    return {
        "watershed": watershed,
        "reaches": reaches,
        "producer": producer,
        "pp_a": pp_a,
    }


def test_tract_occupancy_answers_before_geographic_eligibility(api):
    """A registration that is both overlapping and out of zone reports the overlap.

    "No live practice project on the same tract and practice type occupies an
    overlapping effective interval — `ERR_PRACTICE_PERIOD_OVERLAP`, 409. Applies
    to practice-project registration."

    Design: Difficulty/priority_pair_validation_conflict/practice_period_overlap_outranks_zone_not_eligible_on_project_registration
    """
    world = _tract_occupied_world(api)
    producer_id = world["producer"]["id"]

    refused = api.create_practice_project(
        f.practice_project_payload(
            producer_id,
            world["reaches"]["r_bg"]["id"],
            "T-101",
            practice_type="COVER_CROP",
            effective_start_date="2026-06-01",
            effective_end_date="2026-09-01",
        ),
        make_producer_headers(producer_id),
    )

    validate_error(refused, ERR_PRACTICE_PERIOD_OVERLAP, 409)

    incumbent = get_success_data(api.get_practice_project(world["pp_a"]["id"], ADMIN))
    assert incumbent["status"] == "REGISTERED", incumbent

    rows, meta = validate_paginated(
        api.list_practice_projects(ADMIN, {"producer_id": producer_id})
    )
    assert_pagination_meta(meta, 10, 0, 1, False)
    assert len(rows) == 1, rows


def test_freeing_the_tract_uncovers_the_masked_zone_ineligibility(api):
    """The same out-of-zone reach is refused on its own merits once the tract differs.

    "Registration is gated on geography: the reach's `trading_zone_code` must
    appear in the watershed's `eligible_zone_codes`, and a practice outside the
    eligible zones is rejected with `ERR_ZONE_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/practice_period_overlap_outranks_zone_not_eligible_on_project_registration
    """
    world = _tract_occupied_world(api)
    producer_id = world["producer"]["id"]

    refused = api.create_practice_project(
        f.practice_project_payload(
            producer_id,
            world["reaches"]["r_bg"]["id"],
            "T-999",
            practice_type="COVER_CROP",
            effective_start_date="2026-06-01",
            effective_end_date="2026-09-01",
        ),
        make_producer_headers(producer_id),
    )

    validate_error(refused, ERR_ZONE_NOT_ELIGIBLE, 422)

    rows, meta = validate_paginated(
        api.list_practice_projects(ADMIN, {"producer_id": producer_id})
    )
    assert_pagination_meta(meta, 10, 0, 1, False)
    assert rows[0]["tract_code"] == "T-101", rows
