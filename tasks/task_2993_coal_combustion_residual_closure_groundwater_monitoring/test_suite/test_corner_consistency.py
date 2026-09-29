"""A breadth probe over the declared consistency model.

The platform is immediate: a cascade must be finished before the request that
caused it returns, and visible to the very next read with no retry.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.constants import (
    CLOSURE_STATE_CLOSURE_PLANNED,
    METHOD_CLOSURE_IN_PLACE,
    PLAN_STATUS_APPROVED,
    POSTURE_WATCH,
)
from test_helpers.test_users import PUBLIC_VIEWER_HEADERS, REGULATOR_HEADERS, UTILITY_ADMIN_HEADERS


def test_the_approval_cascade_is_complete_before_the_approval_returns(api):
    """The plan body already says APPROVED and the next unaided read already says CLOSURE_PLANNED.

    PRD: On success the plan moves `FULLY_CERTIFIED → APPROVED` with `approved_on` and `permit_reference` stored, and a second effect follows from it: the unit's `closure_state` advances `ACTIVE → CLOSURE_PLANNED`, the unit's `closure_plan_posting_due_date` is set to `approved_on` plus 60 days, creating a public-posting obligation, and the unit's `compliance_posture` is recomputed.
    Design: Corner/consistency_model/approval_cascade_is_visible_to_the_very_next_read
    """
    world = fixtures.seed_unit(api, "IMP-0154")
    fixtures.file_stability(api, world, "2026-07-15")
    plan = fixtures.draft_plan(api, world, "CP-0154")
    fixtures.certify_plan_both_halves(api, world, plan["id"], "2026-08-01")

    approved = validate_success(
        api.approve_closure_plan(
            plan["id"],
            factories.approve_plan_payload("2026-08-01", "PERMIT-2026-G"),
            REGULATOR_HEADERS,
        )
    )

    assert approved["status"] == PLAN_STATUS_APPROVED
    a.assert_date(approved["approved_on"], "2026-08-01", "approved_on")
    assert approved["permit_reference"] == "PERMIT-2026-G"

    unit = validate_success(api.get_unit(world["unit_id"], UTILITY_ADMIN_HEADERS))

    assert unit["closure_state"] == CLOSURE_STATE_CLOSURE_PLANNED
    a.assert_date(
        unit["closure_plan_posting_due_date"], "2026-09-30", "closure_plan_posting_due_date"
    )
    assert unit["compliance_posture"] == POSTURE_WATCH

    summary = validate_success(
        api.get_compliance_summary(world["unit_id"], PUBLIC_VIEWER_HEADERS)
    )

    assert summary["compliance_posture"] == POSTURE_WATCH
    assert summary["recommended_method"] == METHOD_CLOSURE_IN_PLACE
    a.assert_cents(summary["in_place_pv_usd_cents"], 119600444, "in_place_pv_usd_cents")
