"""Version guards on the two protected writes, and effects visible at once.

The two stale-version rules are the only optimistic-concurrency checks in the
contract, and each guards a child write against the parent's version: a
specification revision against its product, a consumption or a void against its
run. A refused guard writes nothing. The last test takes the opposite view of
the same request boundary: the heaviest transition in the system already carries
every figure its own side effects produced, and the read that follows adds no
correction.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
)

# The product version ladder: registration, then one revision per channel.
FIRST_VERSION = 1
SECOND_VERSION = 2
THIRD_VERSION = 3
NO_SPECS = 0
ONE_SPEC = 1
TWO_SPECS = 2
FIRST_REVISION = 1

# Two draws from the same load, the second one a repeat of the first attempt.
FIRST_DRAW_LB = 10000.00
SECOND_DRAW_LB = 5000.00
NO_POUNDS_LB = 0.00
AFTER_SECOND_DRAW_LB = FIRST_DRAW_LB + SECOND_DRAW_LB
REMAINING_AFTER_VOID_LB = c.RECEIPT_ACCEPTED_LB - FIRST_DRAW_LB
ONE_CONSUMPTION = 1
TWO_CONSUMPTIONS = 2
ONE_STEP = 1

# The close response and the read that follows must agree on all of these.
MIRRORED_RUN_FIELDS = (
    "run_status",
    "disposition_status",
    "cases_produced",
    "output_lb",
    "yield_pct",
    "provisional_shelf_life_days",
    "provisional_code_date",
    "total_run_cost_cents",
    "per_case_cost_cents",
    "cost_remainder_cents",
    "cases_available",
    "cases_on_hold",
    "cases_shipped",
    "cases_destroyed",
    "min_ppm_observed",
    "version",
)
ONE_HOLD = 1
NO_CASES = 0


def _read_product(api, product_id):
    """Read a product back as its registrar sees it."""
    return get_success_data(api.get_product(product_id, PLANT_ADMIN_HEADERS))


def test_the_second_revision_replaying_the_first_seen_product_version_is_refused(api):
    """The child write bumps the parent, so the version the client first saw is dead.

    PRD: Publishing a customer specification revision for a product requires the request to carry `expected_product_version` holding the `version` of that `Product` as the client last read it.
    PRD: If the product's current `version` differs — because another writer has published a revision, or because any other mutation has advanced the product row — the request is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412).
    PRD: It then recomputes the product's `active_spec_count` and increments the product's `version` by 1.

    Design: Corner/cross_cutting_complexity_layers/corner_spec_create_rejects_a_stale_product_version
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    product = fx.create_product(api)

    untouched = _read_product(api, product["id"])
    version_seen = untouched["version"]
    assert version_seen == FIRST_VERSION
    assert untouched["active_spec_count"] == NO_SPECS

    foodservice = fx.create_customer_spec(api, product["id"], version_seen)
    assert foodservice["spec_revision"] == FIRST_REVISION
    assert foodservice["status"] == c.SPEC_ACTIVE
    assert foodservice["superseded_at"] is None
    assert foodservice["channel"] == c.CHANNEL_FOODSERVICE

    advanced = _read_product(api, product["id"])
    assert advanced["version"] == SECOND_VERSION, (
        "the specification write incremented its parent product's version"
    )
    assert advanced["active_spec_count"] == ONE_SPEC

    refused = api.create_customer_spec(
        product["id"], f.retail_spec_payload(version_seen), PLANT_ADMIN_HEADERS
    )
    validate_error(refused, ApiErrorId.STALE_PRODUCT_VERSION)
    a.assert_error_body_shape(refused, ApiErrorId.STALE_PRODUCT_VERSION.value)

    unchanged = _read_product(api, product["id"])
    assert unchanged["version"] == SECOND_VERSION, "the refusal wrote nothing at all"
    assert unchanged["active_spec_count"] == ONE_SPEC

    retail = get_success_data(
        api.create_customer_spec(
            product["id"],
            f.retail_spec_payload(unchanged["version"]),
            PLANT_ADMIN_HEADERS,
        )
    )
    assert retail["spec_revision"] == FIRST_REVISION, (
        "the revision counter is per channel, so RETAIL starts again at one"
    )
    assert retail["channel"] == c.CHANNEL_RETAIL
    assert retail["status"] == c.SPEC_ACTIVE

    settled = _read_product(api, product["id"])
    assert settled["version"] == THIRD_VERSION
    assert settled["active_spec_count"] == TWO_SPECS

    live = a.assert_page(
        api.list_customer_specs(
            product["id"], QA_MANAGER_HEADERS, {"status": c.SPEC_ACTIVE}
        ),
        expected_total=TWO_SPECS,
    )
    a.assert_row_ids(live, [foodservice["id"], retail["id"]])


def test_a_replayed_run_version_is_refused_on_the_consumption_and_on_the_void(api):
    """Both protected writes on the run demand the version the client saw last.

    PRD: Recording a lot consumption against a processing run, and voiding a consumption already recorded, both require the request to carry `expected_process_run_version` holding the `version` of that `ProcessRun` as the client last read it.
    PRD: If the run's current `version` differs, the write is rejected with `ERR_STALE_PROCESS_RUN_VERSION` (HTTP 412).
    PRD: Recording a consumption therefore lowers the load's remaining pounds and raises the run's input pounds by the same figure, recomputes the wash system's chemistry per §3.4 — which can push the system to `DUMP_REQUIRED` in the middle of production — and increments the run's `version` by 1.

    Design: Corner/cross_cutting_complexity_layers/corner_consumption_and_void_reject_a_stale_run_version
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_RUNNING)

    empty = fx.read_run(api, world.run_id)
    version_seen = empty["version"]
    assert empty["run_status"] == c.RUN_RUNNING
    assert empty["input_lb"] == NO_POUNDS_LB
    assert fx.read_receipt(api, world.receipt_id)["remaining_lb"] == (
        c.RECEIPT_ACCEPTED_LB
    )

    first = fx.consume(
        api, world.run_id, world.receipt_id, version_seen, consumed_lb=FIRST_DRAW_LB
    )
    assert first["status"] == c.CONSUMPTION_ACTIVE
    assert first["consumed_lb"] == FIRST_DRAW_LB

    replayed = api.create_lot_consumption(
        world.run_id,
        f.lot_consumption_payload(world.receipt_id, version_seen, SECOND_DRAW_LB),
        LINE_OPERATOR_HEADERS,
    )
    validate_error(replayed, ApiErrorId.STALE_PROCESS_RUN_VERSION)
    a.assert_error_body_shape(replayed, ApiErrorId.STALE_PROCESS_RUN_VERSION.value)

    drawn_once = fx.read_run(api, world.run_id)
    a.assert_version_is(drawn_once, version_seen + ONE_STEP, "process run")
    assert drawn_once["input_lb"] == FIRST_DRAW_LB
    only_row = a.assert_page(
        api.list_run_lot_consumptions(world.run_id, LINE_OPERATOR_HEADERS),
        expected_total=ONE_CONSUMPTION,
    )
    a.assert_row_ids(only_row, [first["id"]])

    second = fx.consume(
        api,
        world.run_id,
        world.receipt_id,
        drawn_once["version"],
        consumed_lb=SECOND_DRAW_LB,
    )
    assert second["status"] == c.CONSUMPTION_ACTIVE

    # The void presents the version it read before its own create advanced it.
    stale_void = api.void_lot_consumption(
        second["id"], f.void_payload(drawn_once["version"]), LINE_OPERATOR_HEADERS
    )
    validate_error(stale_void, ApiErrorId.STALE_PROCESS_RUN_VERSION)
    a.assert_error_body_shape(stale_void, ApiErrorId.STALE_PROCESS_RUN_VERSION.value)

    drawn_twice = fx.read_run(api, world.run_id)
    a.assert_version_is(drawn_twice, drawn_once["version"] + ONE_STEP, "process run")
    assert drawn_twice["input_lb"] == AFTER_SECOND_DRAW_LB
    still_active = a.assert_page(
        api.list_run_lot_consumptions(
            world.run_id, LINE_OPERATOR_HEADERS, {"status": c.CONSUMPTION_ACTIVE}
        ),
        expected_total=TWO_CONSUMPTIONS,
    )
    a.assert_row_ids(still_active, [first["id"], second["id"]])

    voided = fx.void_consumption(api, second["id"], drawn_twice["version"])
    assert voided["status"] == c.CONSUMPTION_VOIDED
    a.assert_instant_equals(voided["voided_at"], c.CLOCK_START, "voided_at")

    reverted = fx.read_run(api, world.run_id)
    assert reverted["input_lb"] == FIRST_DRAW_LB
    assert fx.read_receipt(api, world.receipt_id)["remaining_lb"] == (
        REMAINING_AFTER_VOID_LB
    ), "the voided pounds went back to the load and the first draw stayed drawn"


def test_the_close_response_already_carries_the_effects_it_caused(api):
    """Yield, shelf life, cost and case counters arrive in the closing body itself.

    PRD: Endpoints that modify an existing resource — every state transition, every disposition, every result and every void — respond with HTTP 200 and return the updated resource in `data`, so that the caller can read back the recomputed derived fields and the incremented `version` without a second request.
    PRD: Where a transition has effects on other resources, those effects are applied before the response is serialised, so the returned representation and every sibling collection are consistent the instant the call returns.
    PRD: When the product's `hold_and_release_required` is true, the close opens a hold record with `reason` of `HOLD_AND_RELEASE_TESTING`, moves the run's disposition `UNRESTRICTED → HELD`, and moves every newly created case `IN_INVENTORY → ON_HOLD`.

    Design: Corner/consistency_model/corner_every_effect_is_visible_in_the_response_that_caused_it
    """
    world = fx.build_world(api, stop_after=fx.STOP_CLOCK_AT_CLOSE)
    assert world.product["hold_and_release_required"] is True

    response = api.close_process_run(
        world.run_id, f.close_payload(), LINE_OPERATOR_HEADERS
    )
    closed = get_success_data(response, expected_status=200)
    a.assert_object_envelope(response)

    # The transition itself, and the hold it opened, in one body.
    assert closed["run_status"] == c.RUN_CLOSED
    assert closed["disposition_status"] == c.DISPOSITION_HELD
    a.assert_instant_equals(closed["closed_at"], c.CLOCK_CLOSE, "closed_at")

    # The mass balance and the two derived windows, computed inside the request.
    assert closed["cases_produced"] == c.CLOSE_CASES_PRODUCED
    assert closed["output_lb"] == c.BASE_OUTPUT_LB
    assert closed["yield_pct"] == c.BASE_YIELD_PCT
    assert closed["min_ppm_observed"] == c.BASE_MIN_PPM_OBSERVED
    a.assert_shelf_life(
        closed,
        provisional_days=c.BASE_PROVISIONAL_SHELF_LIFE_DAYS,
        provisional_code_date=c.BASE_PROVISIONAL_CODE_DATE,
    )

    # The cost allocation, likewise, rather than on some later read.
    a.assert_cost_totals(
        closed,
        total_run_cost_cents=c.BASE_TOTAL_RUN_COST_CENTS,
        per_case_cost_cents=c.BASE_PER_CASE_COST_CENTS,
        cost_remainder_cents=c.BASE_COST_REMAINDER_CENTS,
    )

    # The nine hundred cases were created and held by the same call.
    a.assert_case_counters(
        closed,
        available=NO_CASES,
        on_hold=c.CLOSE_CASES_PRODUCED,
        shipped=NO_CASES,
        destroyed=NO_CASES,
    )
    a.assert_case_counters_conserved(closed)

    # The read that follows corrects nothing at all.
    reread = fx.read_run(api, world.run_id, QA_MANAGER_HEADERS)
    for field in MIRRORED_RUN_FIELDS:
        assert reread[field] == closed[field], (
            f"{field} read back as {reread[field]!r} but the close response "
            f"already reported {closed[field]!r}"
        )

    # And the sibling collection is listable in the very next request.
    holds = a.assert_page(
        api.list_hold_records(world.run_id, QA_TECHNICIAN_HEADERS),
        expected_total=ONE_HOLD,
    )
    opened = holds[0]
    assert opened["reason"] == c.REASON_HOLD_AND_RELEASE_TESTING
    assert opened["status"] == c.HOLD_HELD
    assert opened["cases_held_count"] == c.CLOSE_CASES_PRODUCED
    assert opened["shipped_case_count"] == NO_CASES
    a.assert_instant_equals(opened["opened_at"], c.CLOCK_CLOSE, "opened_at")
