"""The approval workflow's cycle, and the bundle publication fork-join."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error, validate_success  # noqa: E402

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import ERR_ACCESSIBILITY_AUDIT_REQUIRED  # noqa: E402
from test_helpers.assertions import assert_fields, assert_money  # noqa: E402
from test_helpers.constants import (  # noqa: E402
    ACTION_APPROVE,
    ACTION_PUBLISH,
    ACTION_REQUEST_CHANGES,
    ACTION_SUBMIT,
    AUDIT_STATE_PASSED,
    AUDIT_STATE_PENDING,
    BUNDLE_PUBLISHED,
    BUNDLE_VALIDATED,
    CATEGORY_ENTREE,
    CLOCK_T0,
    PCR_CHANGES_REQUESTED,
    PCR_PENDING_APPROVAL,
    SKU_BURGER,
    STORE_CODE_S001,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    APPROVER,
    COMPLIANCE,
    CONTENT_MANAGER,
)


def _returned_for_changes(api) -> Dict[str, Any]:
    """A request proposing 590 that has been approved once and then returned."""
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    live_version = world.get_item(burger["id"])["version"]
    request = world.price_change_request(burger["id"], zone["id"], 590, CLOCK_T0, live_version,
                                       ANALYST, justification="Beef cost increase")
    world.pcr_action(request["id"], ACTION_SUBMIT, ANALYST)
    world.pcr_action(request["id"], ACTION_APPROVE, APPROVER)
    returned = world.pcr_action(request["id"], ACTION_REQUEST_CHANGES, APPROVER,
                               comment="Justify against competitor pricing")
    return {"world": world, "zone": zone, "store": store, "burger": burger,
            "request": returned}


def test_resubmission_closes_the_cycle_back_to_pending_approval(api):
    """PRD: "The original analyst submits a `CHANGES_REQUESTED` request again, moving it `CHANGES_REQUESTED → PENDING_APPROVAL`, incrementing `revision_round` by 1, clearing `approval_user_ids`, optionally replacing `proposed_price_cents`, and recording `PRICE_REQUEST_RESUBMITTED`."

    Design: Difficulty/non_linear_state_machine/price_request_revision_cycle_reprices_the_approval_tier
    """
    scene = _returned_for_changes(api)
    assert scene["request"]["state"] == PCR_CHANGES_REQUESTED
    assert scene["request"]["approval_user_ids"] == []

    response = api.price_change_request_action(
        scene["request"]["id"],
        f.action_payload(ACTION_SUBMIT, proposed_price_cents=580),
        ANALYST,
    )
    resubmitted = validate_success(response, 200)

    assert_fields(resubmitted, state=PCR_PENDING_APPROVAL, revision_round=1)
    assert resubmitted["approval_user_ids"] == [], (
        f"approval_user_ids must be cleared, got {resubmitted['approval_user_ids']!r}"
    )
    assert_money(resubmitted["proposed_price_cents"], 580, "proposed_price_cents")


def test_the_frozen_baseline_and_tier_survive_the_revision_cycle(api):
    """PRD: "Crucially, `baseline_price_cents`, `uplift_bp` and `required_approvals` are **never** re-derived across it: a request that needed two approvals in its first round still needs two in its fourth, and the baseline stays frozen at the price the analyst saw when the request was opened."

    Design: Difficulty/non_linear_state_machine/price_request_revision_cycle_reprices_the_approval_tier
    """
    scene = _returned_for_changes(api)

    response = api.price_change_request_action(
        scene["request"]["id"],
        f.action_payload(ACTION_SUBMIT, proposed_price_cents=580),
        ANALYST,
    )
    resubmitted = validate_success(response, 200)

    assert_money(resubmitted["baseline_price_cents"], 559, "baseline_price_cents")
    assert_fields(resubmitted, uplift_bp=555, required_approvals=2)


def _validated_but_unaudited_bundle(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = world.bundle(cluster["id"])
    bundle = world.slot(bundle["id"], bundle["version"], category_codes=[CATEGORY_ENTREE])
    validated = world.validate(bundle["id"])
    return {"world": world, "cluster": cluster, "burger": burger, "bundle": validated}


def test_publication_is_refused_while_only_the_technical_branch_is_complete(api):
    """PRD: "The bundle must be in `VALIDATED` — any other state is an invalid transition — and its `accessibility_audit_state` must be `PASSED`, otherwise the publication is refused with `ERR_ACCESSIBILITY_AUDIT_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/bundle_fork_join_requires_both_branches_complete
    """
    scene = _validated_but_unaudited_bundle(api)
    bundle = scene["bundle"]
    assert_fields(bundle, state=BUNDLE_VALIDATED, accessibility_audit_state=AUDIT_STATE_PENDING)
    assert bundle["validation_findings"] == []

    response = api.content_bundle_action(bundle["id"], f.action_payload(ACTION_PUBLISH),
                                         CONTENT_MANAGER)
    validate_error(response, ERR_ACCESSIBILITY_AUDIT_REQUIRED, 422)

    unchanged = validate_success(api.get_content_bundle(bundle["id"], CONTENT_MANAGER), 200)
    assert_fields(unchanged, state=BUNDLE_VALIDATED)
    assert unchanged["validation_findings"] == []


def test_the_join_succeeds_once_the_accessibility_branch_has_also_completed(api):
    """PRD: "It may run while the bundle is `DRAFT` or while it is `VALIDATED`, and in both cases it leaves the bundle's own state exactly where it found it — auditing a `VALIDATED` bundle does **not** send it back to `DRAFT`."

    Design: Difficulty/non_linear_state_machine/bundle_fork_join_requires_both_branches_complete
    """
    scene = _validated_but_unaudited_bundle(api)
    bundle, burger, cluster = scene["bundle"], scene["burger"], scene["cluster"]

    audited = validate_success(
        api.content_bundle_action(bundle["id"], f.audit_action_payload(), COMPLIANCE), 200
    )
    assert_fields(audited, state=BUNDLE_VALIDATED, accessibility_audit_state=AUDIT_STATE_PASSED)

    published = validate_success(
        api.content_bundle_action(bundle["id"], f.action_payload(ACTION_PUBLISH), CONTENT_MANAGER),
        200,
    )
    assert_fields(published, state=BUNDLE_PUBLISHED, stale_flag=False)
    assert published["snapshot_item_ids"] == [burger["id"]]

    cluster_after = validate_success(api.get_store_cluster(cluster["id"], ADMIN), 200)
    assert cluster_after["published_bundle_version"] == published["bundle_version"]
