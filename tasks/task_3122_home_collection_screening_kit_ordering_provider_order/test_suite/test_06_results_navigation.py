"""Result delivery and positive-result navigation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_order,
    get_result,
    set_clock,
    setup_resulted,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
NAV = TEST_USERS["navigator_headers"]


def test_navigation_schedule_on_negative_result_rejected(api):
    """PRD §3.6: "scheduling is only meaningful for `POSITIVE` results, and
    an attempt against a `NEGATIVE` result fails with
    `ERR_NAVIGATION_NOT_REQUIRED` (HTTP 422)".

    Design: Corner/validations/navigation_schedule_on_negative_result_rejected
    """
    ctx = setup_resulted("NEGATIVE")
    resp = api.schedule_navigation(ctx["result"]["id"], NAV)
    validate_error(resp, ApiErrorId.ERR_NAVIGATION_NOT_REQUIRED)


def test_navigation_invalid_state_on_double_schedule(api):
    """PRD §3.6: "an attempt from any `navigation_status` other than
    `PENDING` fails with `ERR_NAVIGATION_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/navigation_invalid_state_on_double_schedule
    """
    ctx = setup_resulted("POSITIVE")
    validate_success(api.schedule_navigation(ctx["result"]["id"], NAV))
    resp = api.schedule_navigation(ctx["result"]["id"], NAV)
    validate_error(resp, ApiErrorId.ERR_NAVIGATION_INVALID_STATE)


def test_navigation_fork_negative_not_required_positive_pending(api):
    """PRD §3.6: "A `NEGATIVE` result needs no follow-up and starts at
    `NOT_REQUIRED`. A `POSITIVE` result starts at `PENDING`, and its
    `navigation_due_at` is computed as the date 90 days after the delivery
    date — the colonoscopy navigation window."

    Design: Difficulty/non_linear_state_machine/navigation_branching_fork_join
    """
    set_clock()
    neg = setup_resulted("NEGATIVE", patient_overrides={"external_ref": "p-br-1"})
    pos = setup_resulted("POSITIVE", patient_overrides={"external_ref": "p-br-2"})

    r_neg = get_result(neg["result"]["id"])
    r_pos = get_result(pos["result"]["id"])
    assert r_neg["navigation_status"] == "NOT_REQUIRED"
    assert r_pos["navigation_status"] == "PENDING"
    # Delivery 2026-09-01 + 90 days == 2026-11-30.
    assert str(r_pos["navigation_due_at"])[:10] == "2026-11-30"


def test_navigation_lapse_flips_positive_result_quality_outcome(api):
    """PRD §3.6: "When the logical clock advances past `navigation_due_at`
    while a result's `navigation_status` is still `PENDING` or `SCHEDULED`,
    the result's navigation moves to `LAPSED`, the owning order's
    `quality_outcome` becomes `POSITIVE_NAVIGATION_LAPSED`, and the order's
    `version` increments by one."
    PRD §3.8: "An order that resulted with `outcome` `NEGATIVE` is
    `ADHERENT_NEGATIVE`."

    Design: Difficulty/non_linear_state_machine/navigation_branching_fork_join
    """
    set_clock()
    neg = setup_resulted("NEGATIVE", patient_overrides={"external_ref": "p-br-1b"})
    pos = setup_resulted("POSITIVE", patient_overrides={"external_ref": "p-br-2b"})
    set_clock("2026-12-01T00:00:00Z")  # past the 2026-11-30 due date

    r_pos = get_result(pos["result"]["id"])
    assert r_pos["navigation_status"] == "LAPSED"
    assert get_order(neg["order"]["id"])["quality_outcome"] == "ADHERENT_NEGATIVE"
    assert get_order(pos["order"]["id"])["quality_outcome"] == "POSITIVE_NAVIGATION_LAPSED"


def test_navigation_completion_on_due_date_is_adherent(api):
    """PRD §3.6: "A completion is on-time when the completion date falls on
    or before `navigation_due_at` — the boundary day itself counts as
    on-time."
    PRD §3.8: "An order that resulted `POSITIVE` and whose navigation
    completed on or before its `navigation_due_at` is
    `ADHERENT_POSITIVE_NAVIGATED`."

    Design: Difficulty/combinatorial_formula/navigation_window_circular_dependency_pinned_order
    """
    set_clock()
    ctx = setup_resulted("POSITIVE")
    result_id = ctx["result"]["id"]
    set_clock("2026-09-10T00:00:00Z")
    validate_success(api.schedule_navigation(result_id, NAV))
    set_clock("2026-11-30T00:00:00Z")  # exactly the due date

    completed = validate_success(api.complete_navigation(result_id, NAV))
    assert completed["navigation_status"] == "COMPLETED"
    assert str(completed["navigation_due_at"])[:10] == "2026-11-30"
    assert get_order(ctx["order"]["id"])["quality_outcome"] == "ADHERENT_POSITIVE_NAVIGATED"


def test_navigation_due_date_derived_from_delivery(api):
    """PRD §3.6: "A `POSITIVE` result starts at `PENDING`, and its
    `navigation_due_at` is computed as the date 90 days after the delivery
    date — the colonoscopy navigation window."
    PRD §3.6: "a `resulted_at` timestamp, and a `delivered_to_provider_at`
    timestamp — both stamped from the logical clock, since finalization and
    delivery to the ordering provider happen in the same instant".

    Design: Difficulty/combinatorial_formula/navigation_window_circular_dependency_pinned_order
    """
    set_clock()
    ctx = setup_resulted("POSITIVE")
    result = get_result(ctx["result"]["id"])
    assert result["navigation_status"] == "PENDING"
    assert str(result["delivered_to_provider_at"])[:10] == "2026-09-01"
    assert str(result["navigation_due_at"])[:10] == "2026-11-30"
