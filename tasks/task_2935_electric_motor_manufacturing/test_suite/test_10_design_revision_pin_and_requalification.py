"""Reopening a released design: the stale pin, requalification and the create gate."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_DESIGN_NOT_RELEASED,
    ERR_REQUALIFICATION_REQUIRED,
    ERR_STALE_DESIGN_VERSION,
)
from test_helpers.fixtures import build_plant


def _scheduled_test_inside_its_window(api):
    """An ASSEMBLED work order with a live 09:00-11:00Z test and the clock at 09:30Z."""
    plant = build_plant(api, "test_scheduled", test={"dyno_draw_kw": 12.0})
    plant.set_clock(F.RECORD_CLOCK)
    scheduled = plant.get_test()
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["requires_requalification"] is False
    work_order = plant.get_work_order()
    assert work_order["build_status"] == "ASSEMBLED"
    assert work_order["design_pin_stale"] is False
    assert work_order["pinned_design_revision_index"] == 0
    return plant, scheduled


def test_opening_a_revision_stales_the_pin_and_flags_the_scheduled_test(api):
    """Two hops downstream of the design: the work order, then its live test.

    PRD 3.3: "In the second hop, caused by the first, every performance test still
    in `SCHEDULED` status on each of those newly stale work orders has
    `requires_requalification` set to true and its own `version` incremented, again
    in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/design_revision_cascades_to_workorder_pin_and_scheduled_test_requalification
    """
    plant, scheduled = _scheduled_test_inside_its_window(api)
    design_before = plant.get_design()
    assert design_before["status"] == "RELEASED"
    assert design_before["revision_index"] == 0

    reopened = plant.open_revision()

    assert reopened["status"] == "REVISION_OPEN"
    assert reopened["revision_index"] == 1
    assert reopened["version"] > design_before["version"]
    work_order = plant.get_work_order()
    assert work_order["design_pin_stale"] is True
    assert work_order["pinned_design_revision_index"] == 0
    assert work_order["build_status"] == "ASSEMBLED"
    flagged = plant.get_test(scheduled)
    assert flagged["requires_requalification"] is True
    assert flagged["status"] == "SCHEDULED"
    assert flagged["version"] > scheduled["version"]


def test_the_flagged_test_can_no_longer_be_recorded(api):
    """The clock is inside the window, so only the requalification flag can refuse it.

    PRD 3.8: "must not carry `requires_requalification`
    (`ERR_REQUALIFICATION_REQUIRED`, HTTP 409 — a test flagged by a design revision
    must be superseded by a freshly scheduled test rather than recorded)"

    Design: Difficulty/transitive_cascade/design_revision_cascades_to_workorder_pin_and_scheduled_test_requalification
    """
    plant, scheduled = _scheduled_test_inside_its_window(api)
    plant.open_revision()
    assert plant.get_test(scheduled)["requires_requalification"] is True

    refused = api.record_performance_test(
        scheduled["id"], F.record_results_payload(), U.TEST_ENGINEER
    )

    validate_error(refused, ERR_REQUALIFICATION_REQUIRED, 409)
    stored = plant.get_test(scheduled)
    assert stored["status"] == "SCHEDULED"
    assert stored["measured_efficiency_pct"] is None
    assert stored["recorded_at"] is None
    assert stored["total_loss_w"] is None
    assert plant.get_work_order()["build_status"] == "ASSEMBLED"
    assert plant.get_work_order()["design_pin_stale"] is True


def _order_confirmed_then_design_back_in_review(api):
    """The order was confirmed against a RELEASED design that is now IN_REVIEW."""
    plant = build_plant(api, "confirmed_order")
    assert plant.get_order()["status"] == "CONFIRMED"
    plant.open_revision()
    in_review = plant.submit_design()
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["revision_index"] == 1
    return plant, in_review


def test_a_work_order_is_refused_while_the_pinned_design_sits_in_review(api):
    """The create gate reads the design's status now, not at order confirmation.

    PRD 3.5: "the `design_id` — which must be the very design the customer order
    named, and which must be in `RELEASED` status at that moment or the request is
    refused with `ERR_DESIGN_NOT_RELEASED`"

    Design: Difficulty/cross_entity_state_dependency/work_order_creation_blocked_while_pinned_design_sits_in_review
    """
    plant, in_review = _order_confirmed_then_design_back_in_review(api)

    refused = api.create_work_order(
        F.work_order_payload(
            plant.order["id"], plant.design["id"], in_review["version"]
        ),
        U.PRODUCTION_PLANNER,
    )

    validate_error(refused, ERR_DESIGN_NOT_RELEASED, 409)
    assert plant.get_order()["status"] == "CONFIRMED"
    assert plant.get_design()["status"] == "IN_REVIEW"
    assert plant.get_design()["revision_index"] == 1


def test_re_approval_unblocks_the_work_order_but_only_on_a_re_read_version(api):
    """The approval bumped the design's version, so the pre-approval view is stale.

    PRD 3.5: "Because creating a work order pins the design's revision and advances
    the design's own `version`, a request whose `expected_design_version` does not
    equal the design's current `version` is rejected with
    `ERR_STALE_DESIGN_VERSION` (HTTP 412)."

    Design: Difficulty/cross_entity_state_dependency/work_order_creation_blocked_while_pinned_design_sits_in_review
    """
    plant, in_review = _order_confirmed_then_design_back_in_review(api)
    stale_version = in_review["version"]
    validate_error(
        api.create_work_order(
            F.work_order_payload(
                plant.order["id"], plant.design["id"], stale_version
            ),
            U.PRODUCTION_PLANNER,
        ),
        ERR_DESIGN_NOT_RELEASED,
        409,
    )
    re_released = plant.decide_design("APPROVE")
    assert re_released["status"] == "RELEASED"
    assert re_released["version"] > stale_version

    validate_error(
        api.create_work_order(
            F.work_order_payload(
                plant.order["id"], plant.design["id"], stale_version
            ),
            U.PRODUCTION_PLANNER,
        ),
        ERR_STALE_DESIGN_VERSION,
        412,
    )
    opened = validate_success(
        api.create_work_order(
            F.work_order_payload(
                plant.order["id"], plant.design["id"], re_released["version"]
            ),
            U.PRODUCTION_PLANNER,
        ),
        201,
    )

    assert opened["pinned_design_revision_index"] == 1
    assert opened["design_pin_stale"] is False
    assert opened["build_status"] == "RELEASED"
    assert opened["certification_status"] == "PENDING"
    assert opened["rework_reject_count"] == 0
    assert plant.get_order()["status"] == "IN_PRODUCTION"
    final_design = plant.get_design()
    assert final_design["status"] == "RELEASED"
    assert final_design["revision_index"] == 1
