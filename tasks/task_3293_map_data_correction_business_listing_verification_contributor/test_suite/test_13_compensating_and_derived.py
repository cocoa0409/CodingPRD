"""Compensating invariants and derived-field reconciliation."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    blur_complete_imagery_task,
    capture_imagery_task,
    get_contributor,
    get_listing,
    get_region,
    claim_listing,
    make_contributor,
    make_imagery_task,
    make_listing,
    make_map_edit,
    make_operator_headers,
    make_region,
    publish_imagery_task,
    schedule_imagery_task,
    set_clock,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PA1 = TEST_USERS["policy_analyst_headers"]


def test_grant_post_then_revoke_restores_total_points(api):
    """PRD §3.4: "A policy analyst may revert a published edit, moving it to
    `REVERTED`: the payload's effect on the listing is undone and the prior
    field values restored, the listing's `accepted_edit_count` decrements, the
    grant created at publish is revoked — so `total_points` returns to exactly
    its pre-publish value while `lifetime_points` keeps the history — and
    trust and health recompute on both sides."
    PRD §3.4: "creates a point grant for the author with `source_type` `EDIT`,
    `base_points` of 5, and a multiplier equal to the edit's
    `quality_weight`."
    PRD §3.1: "Level, in turn, sets the quality weight an edit earns its
    author on publication: `NEWCOMER` earns 0.5, `REGULAR` 1.0, `TRUSTED` 1.5,
    `EXPERT` 2.0, and `MASTER` 2.5."

    Design: Difficulty/compensating_invariant/grant_post_then_revoke_restores_total_points
    """
    region = make_region(name="R17")
    contributor = make_contributor(region["id"], display_name="C16",
                                   email="c16@x.com")
    listing = make_listing(region["id"], name="Spa Seventeen")

    # Fresh NEWCOMER (weight 0.5) with 3 evidence URLs: score 85 -> PUBLISHED.
    edit = make_map_edit(
        listing, contributor["id"],
        payload={"attribute": "wifi", "value": True,
                 "evidence_urls": ["u1", "u2", "u3"]},
    )
    assert edit["status"] == "PUBLISHED"

    after_publish = get_contributor(contributor["id"])
    # round_half_up(5 * 0.5) = 3 points posted.
    assert after_publish["total_points"] == 3
    assert after_publish["lifetime_points"] == 3

    resp = api.revert_map_edit(edit["id"], PA1)
    reverted = validate_success(resp)
    assert reverted["status"] == "REVERTED"

    after_revert = get_contributor(contributor["id"])
    assert after_revert["total_points"] == 0, (
        f"conserved quantity restored, got {after_revert['total_points']}"
    )
    assert after_revert["lifetime_points"] == 3, (
        f"revocation preserves history, got {after_revert['lifetime_points']}"
    )


def test_revert_restores_listing_accepted_edit_count(api):
    """PRD §3.4: "Publication, whether immediate or through review, applies
    the edit's payload to the listing's fields according to its type,
    increments the listing's `accepted_edit_count`, creates a point grant for
    the author with `source_type` `EDIT`, `base_points` of 5, and a multiplier
    equal to the edit's `quality_weight`, then recomputes the author's points,
    level, and both trust variants, and finally recomputes both listing health
    variants."
    PRD §3.4: "A policy analyst may revert a published edit, moving it to
    `REVERTED`: the payload's effect on the listing is undone and the prior
    field values restored, the listing's `accepted_edit_count` decrements, the
    grant created at publish is revoked — so `total_points` returns to exactly
    its pre-publish value while `lifetime_points` keeps the history — and
    trust and health recompute on both sides."

    Design: Difficulty/compensating_invariant/grant_post_then_revoke_restores_total_points
    """
    region = make_region(name="R17b")
    contributor = make_contributor(region["id"], display_name="C16b",
                                   email="c16b@x.com")
    listing = make_listing(region["id"], name="Spa Seventeen B")

    edit = make_map_edit(
        listing, contributor["id"],
        payload={"attribute": "wifi", "value": True,
                 "evidence_urls": ["u1", "u2", "u3"]},
    )
    assert edit["status"] == "PUBLISHED"
    mid = get_listing(listing["id"])
    assert mid["accepted_edit_count"] == 1

    validate_success(api.revert_map_edit(edit["id"], PA1))
    final = get_listing(listing["id"])
    assert final["accepted_edit_count"] == 0, (
        f"revert decrements the accepted-edit ledger, got "
        f"{final['accepted_edit_count']}"
    )


def test_listing_version_increments_on_every_mutation(api):
    """PRD §2.4: "Most resources additionally carry `created_at` (an ISO 8601
    UTC timestamp with three fractional digits, stamped from the logical
    clock), `updated_at` (same format, refreshed on every mutation), and
    `version` (an integer that increments by one on every mutation of that
    resource)."
    PRD §2.5: "Successful mutations of the guarded parent bump its `version`
    by one: a map-edit create increments the target listing's `version`, a
    claim increments the claimed listing's `version`, and a routing-update
    create increments the region's `version`."

    Design: Corner/cross_cutting_layers/listing_version_increments_on_every_mutation
    """
    region = make_region(name="RVer")
    contributor = make_contributor(region["id"], display_name="CV",
                                   email="ver@x.com")
    listing = make_listing(region["id"], name="Version Biz")
    v0 = listing["version"]
    assert v0 == 1, f"fresh listing starts at version 1, got {v0}"

    listing = claim_listing(listing, contributor["id"])
    assert listing["version"] == v0 + 1, (
        f"claim bumps the version, got {listing['version']}"
    )

    make_map_edit(listing, contributor["id"])
    listing = get_listing(listing["id"])
    assert listing["version"] == v0 + 2, (
        f"edit create bumps the version again, got {listing['version']}"
    )


def test_region_posture_drains_to_clear_on_publish(api):
    """PRD §2.8: "The posture `posture` then follows a strict priority: a
    region whose frozen flag is set reports `FROZEN`; otherwise, a region with
    a `privacy_pending_count` greater than zero reports `CLEARANCE_PENDING`;
    otherwise, a region in which at least one imagery task has captured media
    reports `CLEAR`; otherwise the region reports `ACTIVE`."
    PRD §3.8: "Publishing a blurred task — refused outright in a `FROZEN`
    region — moves it to `PUBLISHED`, decrements the region's
    `privacy_pending_count` by one, and when that drain brings the count to
    zero in a `CLEARANCE_PENDING` region, the posture settles back to
    `CLEAR`."

    Design: Corner/cross_cutting_layers/region_posture_drains_to_clear_on_publish
    """
    region = make_region(name="RClear")
    task = make_imagery_task(region["id"], collection_zone="zc",
                             operator_id="op-1",
                             window_start="2026-09-02T00:00:00Z",
                             window_end="2026-09-05T00:00:00Z",
                             blur_obligation="FULL_PRIVACY")
    schedule_imagery_task(task["id"], "op-1")
    set_clock("2026-09-03T00:00:00Z")
    capture_imagery_task(task["id"], 3, "op-1")
    blur_complete_imagery_task(task["id"], 3, "op-1")

    resp = api.publish_imagery_task(task["id"], make_operator_headers("op-1"))
    published = validate_success(resp)
    assert published["status"] == "PUBLISHED"

    region = get_region(region["id"])
    assert region["privacy_pending_count"] == 0
    assert region["posture"] == "CLEAR", (
        f"a region that has captured media and drained reports CLEAR, "
        f"got {region['posture']}"
    )


def test_immediate_consistency_edit_publish_visible_in_same_chain(api):
    """PRD §3.4: "Publication, whether immediate or through review, applies
    the edit's payload to the listing's fields according to its type,
    increments the listing's `accepted_edit_count`, creates a point grant for
    the author with `source_type` `EDIT`, `base_points` of 5, and a multiplier
    equal to the edit's `quality_weight`, then recomputes the author's points,
    level, and both trust variants, and finally recomputes both listing health
    variants."
    PRD §3.6: "Health recomputes whenever a review on the listing changes
    status, when an edit is published or reverted, when the listing is
    suspended or reinstated, and on every listing read."
    PRD §3.1: "Level, in turn, sets the quality weight an edit earns its
    author on publication: `NEWCOMER` earns 0.5, `REGULAR` 1.0, `TRUSTED` 1.5,
    `EXPERT` 2.0, and `MASTER` 2.5."

    Design: Corner/consistency_model/immediate_consistency_edit_publish_visible_in_same_chain
    """
    region = make_region(name="RImm")
    contributor = make_contributor(region["id"], display_name="CImm",
                                   email="imm2@x.com")
    listing = make_listing(region["id"], name="Immediate Biz")

    edit = make_map_edit(
        listing, contributor["id"],
        payload={"attribute": "wifi", "value": True,
                 "evidence_urls": ["u1", "u2", "u3"]},
    )
    assert edit["status"] == "PUBLISHED", (
        "edit publishes within the creation response"
    )

    listing = get_listing(listing["id"])
    assert listing["accepted_edit_count"] == 1
    # 50 + 4*0.0 rating + 2*min(1,10) - 0 - 0 = 52.
    assert listing["health_score"] == pytest.approx(52, abs=0.005), (
        f"health 50 + 2*1 = 52 immediately, got {listing['health_score']}"
    )

    contributor = get_contributor(contributor["id"])
    # round_half_up(5 * 0.5) = 3 points.
    assert contributor["total_points"] == 3
