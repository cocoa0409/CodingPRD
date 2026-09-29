"""Sign-off re-reads the order a remake moved out from under a scheduled job."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_ORDER_NOT_RECEIVED
from test_helpers.assertions import assert_instant_equals, assert_ledger_entry
from test_helpers.fixtures import (
    ledger_rows,
    read_designer,
    read_install_job,
    read_opening,
    read_order,
    read_quote,
    read_territory,
    receive_order,
    request_remake,
    schedule_install,
    set_clock,
    ship_order,
    single_opening_job,
)
from test_helpers.test_users import designer_headers

REMAKE_CLOCK = "2026-08-17T09:30:00.000Z"
SECOND_RECEIPT_CLOCK = "2026-08-23T09:00:00.000Z"


def _job_whose_order_was_re_placed(api):
    """A scheduled job whose received order has been driven back to `PLACED`.

    The order is a single 4960-cent corded opening on a `SHARED_50_50` manufacturer,
    so there is no ninety-day remake window to respect. The job carries no motorized
    channel, so its commissioning dimension is already `NOT_REQUIRED` and cannot be
    the reason a completion fails.
    """
    world = single_opening_job(api, stop_after="received")
    territory, designer, order = world["territory"], world["designer"], world["order"]
    job = schedule_install(api, territory, order, designer,
                           scheduled_start_at="2026-08-17T09:00:00.000Z",
                           scheduled_end_at="2026-08-17T11:00:00.000Z")
    set_clock(api, REMAKE_CLOCK)
    remade = request_remake(api, territory, order, credit_scope="REPLACEMENT")
    world["job"] = job
    world["remade"] = remade
    return world


def test_the_replacement_remake_re_places_the_order_and_charges_the_territory(api):
    """`RECEIVED → REMAKE_REQUESTED → PLACED` inside one request, with a 1042-cent row.

    "The observable outcome is therefore `RECEIVED → REMAKE_REQUESTED → PLACED` with
    `remake_count` one higher: `placed_at` is re-stamped from the logical clock,
    `shipped_at` and `received_at` are cleared to null, the lead-time calculation is
    re-run and now applies the four-day expedite before the five-day floor, storing a
    fresh `effective_placement_date`, `lead_time_days` and `promised_ship_date`"

    "A `SHARED_50_50` vendor's target is half of `remake_cost_cents` rounded **down** to
    a whole cent, and the territory's target is whatever remains — so on an odd cost of
    7403 cents the vendor takes 3701 and the territory 3702, the extra cent landing on
    the territory rather than on the manufacturer."

    Design: Difficulty/cross_entity_state_dependency/install_completion_rechecks_the_order_state_a_remake_moved_underneath_it
    """
    world = _job_whose_order_was_re_placed(api)
    territory, remade = world["territory"], world["remade"]

    assert remade["status"] == "PLACED"
    assert remade["remake_count"] == 1
    assert remade["credit_scope"] == "REPLACEMENT"
    assert remade["lead_time_days"] == 6
    assert remade["effective_placement_date"] == "2026-08-17"
    assert remade["promised_ship_date"] == "2026-08-23"
    assert remade["received_at"] is None

    assert remade["remake_cost_cents"] == 2083
    assert remade["vendor_absorbed_cents"] == 1041
    assert remade["territory_absorbed_cents"] == 1042
    assert remade["customer_absorbed_cents"] == 0
    assert (remade["vendor_absorbed_cents"] + remade["territory_absorbed_cents"]
            + remade["customer_absorbed_cents"]) == remade["remake_cost_cents"]

    assert read_territory(api, territory)["remake_chargeback_cents"] == 1042
    rows = ledger_rows(api, territory, entry_type="REMAKE_CHARGEBACK")
    assert len(rows) == 1
    assert_ledger_entry(rows[0], "REMAKE_CHARGEBACK", 1042, 2083,
                        "remake_replacement", "VENDOR_ORDER",
                        source_entity_id=remade["id"],
                        territory_id=territory["id"])


def test_completion_consults_the_order_again_and_refuses(api):
    """The job is still `SCHEDULED` and commissioning is satisfied, and it still fails.

    "The re-check at sign-off is not redundant: an order can leave `RECEIVED` after its
    install job has been scheduled, because a remake re-places it, so completion
    re-examines the referenced order rather than trusting the check made at scheduling
    time."

    "Being `RECEIVED` is the precondition for three quite different things — requesting a
    remake on the order, scheduling the install that fits it, and signing that install
    off — and all three report `ERR_ORDER_NOT_RECEIVED` when it does not hold."

    Design: Difficulty/cross_entity_state_dependency/install_completion_rechecks_the_order_state_a_remake_moved_underneath_it
    """
    world = _job_whose_order_was_re_placed(api)
    territory, designer, job = world["territory"], world["designer"], world["job"]

    staged = read_install_job(api, designer, job["id"])
    assert staged["install_status"] == "SCHEDULED"
    assert staged["commissioning_status"] == "NOT_REQUIRED"

    validate_error(
        api.complete_install_job(job["id"], designer_headers(designer["id"])),
        ERR_ORDER_NOT_RECEIVED, 409)

    untouched = read_install_job(api, designer, job["id"])
    assert untouched["install_status"] == "SCHEDULED"
    assert untouched["completed_at"] is None
    assert read_opening(api, designer,
                        world["opening"]["id"])["install_outcome"] == "PENDING"
    assert read_territory(api, territory)["royalty_accrued_cents"] == 273


def test_the_same_call_succeeds_once_the_order_is_received_again(api):
    """Re-shipping and re-receiving restores the precondition, and the true-up is zero.

    "Sign-off stamps `completed_at` from the logical clock and sets `install_outcome` to
    `INSTALLED` on every opening in the order's `opening_ids` whose `install_outcome` is
    still `PENDING`."

    "`remeasure_liability_score` is that raw figure clamped at both ends — never above
    the base of 100 and never below zero."

    Design: Difficulty/cross_entity_state_dependency/install_completion_rechecks_the_order_state_a_remake_moved_underneath_it
    """
    world = _job_whose_order_was_re_placed(api)
    territory, designer, job = world["territory"], world["designer"], world["job"]

    validate_error(
        api.complete_install_job(job["id"], designer_headers(designer["id"])),
        ERR_ORDER_NOT_RECEIVED, 409)

    ship_order(api, world["vendor"], world["remade"])
    set_clock(api, SECOND_RECEIPT_CLOCK)
    receive_order(api, territory, world["remade"])
    assert read_order(api, territory, world["order"]["id"])["status"] == "RECEIVED"

    signed = validate_success(
        api.complete_install_job(job["id"], designer_headers(designer["id"])))
    assert signed["install_status"] == "COMPLETED"
    assert_instant_equals(signed["completed_at"], SECOND_RECEIPT_CLOCK,
                          "completed_at")

    assert read_opening(api, designer,
                        world["opening"]["id"])["install_outcome"] == "INSTALLED"
    assert read_quote(api, territory,
                      world["quote"]["id"])["recognized_net_sales_cents"] == 4960
    assert read_territory(api, territory)["royalty_accrued_cents"] == 273

    scored = read_designer(api, territory, designer["id"])
    assert scored["clean_install_count"] == 1
    assert scored["remeasure_liability_score"] == 100
