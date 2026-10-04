"""Factory tooling slots, partner-activity gating, and the refresh/retirement
cadence cascade into commitments and capacity (PRD §3.3, §3.9).
"""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    SOURCING,
    ApiErrorId,
    api_client,
    advance_variant_to_refresh_candidate,
    advance_variant_to_retired,
    assert_capacity_conservation,
    create_partner,
    get_commitment,
    get_partner,
    get_variant,
    set_clock,
    setup_draft_variants,
    setup_engineering_locked_concept,
    setup_retail_live_open_commitment,
    setup_season_with_category,
    tool_variant,
    tool_variant_payload,
    validate_error,
    validate_ok,
)


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_tooling_slots_reject_third_parallel_engagement(api):
    """PRD §3.3: "Tooling occupies a 14-day window, running from the instant
    of tooling up to but not including the instant 14 days later, and a
    partner runs at most 2 tooling engagements in parallel: the request is
    rejected with `ERR_TOOLING_SLOTS_FULL` when 2 or more other variants at
    that partner hold tooling windows intersecting the requested one."

    Design: Difficulty/resource_temporal_overlap/tooling_slots_aggregate_capacity_not_interval_exclusion
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    partner = create_partner()
    v1, v2, v3 = setup_draft_variants(concept["id"])
    assert tool_variant(v1["id"], partner["id"])["lifecycle"] == "TOOLED"
    assert tool_variant(v2["id"], partner["id"])["lifecycle"] == "TOOLED"
    resp = api_client.tool_variant(
        v3["id"], tool_variant_payload(partner["id"]), SOURCING
    )
    validate_error(resp, ApiErrorId.ERR_TOOLING_SLOTS_FULL)


def test_tooling_slot_frees_after_window_elapses(api):
    """PRD §3.3: "Tooling occupies a 14-day window, running from the instant
    of tooling up to but not including the instant 14 days later" — the
    [2026-09-10, 2026-09-24) windows no longer intersect a tooling requested
    at 2026-09-25, so the third engagement fits without any explicit release.

    Design: Difficulty/resource_temporal_overlap/tooling_slots_aggregate_capacity_not_interval_exclusion
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    partner = create_partner()
    v1, v2, v3 = setup_draft_variants(concept["id"])
    tool_variant(v1["id"], partner["id"])
    tool_variant(v2["id"], partner["id"])
    validate_error(
        api_client.tool_variant(v3["id"], tool_variant_payload(partner["id"]),
                                SOURCING),
        ApiErrorId.ERR_TOOLING_SLOTS_FULL,
    )
    set_clock("2026-09-25T00:00:00Z")
    data = validate_ok(
        api_client.tool_variant(v3["id"], tool_variant_payload(partner["id"]),
                                SOURCING)
    )
    assert data["lifecycle"] == "TOOLED"
    assert data["factory_partner_id"] == partner["id"]
    assert _iso(data["tooled_at"]) == datetime(2026, 9, 25, tzinfo=timezone.utc)


def test_variant_tooling_rejected_at_suspended_partner(api):
    """PRD §3.3: "The partner must be `ACTIVE`, else
    `ERR_PARTNER_NOT_ACTIVE`." and "`SUSPENDED` is terminal: no transition
    leads out of it."

    Design: Difficulty/cross_entity_state_dependency/variant_tooling_gated_on_partner_active
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    partner = create_partner()
    variant = setup_draft_variants(concept["id"], specs=[("CV100-AMZ", "AMAZON")])[0]
    validate_ok(api_client.suspend_partner(partner["id"], SOURCING))
    resp = api_client.tool_variant(
        variant["id"], tool_variant_payload(partner["id"]), SOURCING
    )
    validate_error(resp, ApiErrorId.ERR_PARTNER_NOT_ACTIVE)
    assert get_variant(variant["id"])["lifecycle"] == "DRAFT"


def test_variant_tooling_succeeds_at_active_partner_after_rejection(api):
    """PRD §3.3: "A `SourcingManager` tools a `DRAFT` variant ... by naming a
    `factory_partner_id`. The partner must be `ACTIVE`, else
    `ERR_PARTNER_NOT_ACTIVE`." and "A successful tooling sets
    `factory_partner_id`, stamps `tooled_at` from the logical clock, and moves
    the variant `DRAFT` → `TOOLED`."

    Design: Difficulty/cross_entity_state_dependency/variant_tooling_gated_on_partner_active
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    suspended = create_partner("Shenzhen Precision", 500)
    active = create_partner("Vietnam Assembly Co", 800)
    variant = setup_draft_variants(concept["id"], specs=[("CV100-AMZ", "AMAZON")])[0]
    validate_ok(api_client.suspend_partner(suspended["id"], SOURCING))
    validate_error(
        api_client.tool_variant(variant["id"], tool_variant_payload(suspended["id"]),
                                SOURCING),
        ApiErrorId.ERR_PARTNER_NOT_ACTIVE,
    )
    data = tool_variant(variant["id"], active["id"])
    assert data["lifecycle"] == "TOOLED"
    assert data["factory_partner_id"] == active["id"]


def test_review_retirement_cascades_variant_to_commitment_to_capacity(api):
    """PRD §3.9: "Step 10 retires stale candidates: every variant
    `REFRESH_CANDIDATE` whose `refresh_candidate_at` is more than 30 days in
    the past becomes `RETIRED`, stamping `retired_at`; retirement cascades,
    moving every `OPEN` LaunchCommitment on the variant to `CANCELLED` and
    every `OPEN` ReplenishmentOrder on the variant to `CANCELLED`, and the
    partner's `allocated_units` recomputes."

    Design: Difficulty/transitive_cascade/review_retirement_cascades_variant_to_commitment_to_capacity
    """
    bundle = setup_retail_live_open_commitment()  # 300 units OPEN, alloc 300
    assert bundle["partner"]["allocated_units"] == 300
    bundle = advance_variant_to_refresh_candidate(bundle)  # review at +241d
    assert bundle["variant"]["lifecycle"] == "REFRESH_CANDIDATE"
    bundle = advance_variant_to_retired(bundle)  # review at +31d candidacy
    assert bundle["variant"]["lifecycle"] == "RETIRED"
    assert bundle["commitment"]["status"] == "CANCELLED"
    assert bundle["partner"]["allocated_units"] == 0


def test_retirement_cadence_stamps_and_conserves_capacity(api):
    """PRD §3.9: "Step 9 ages the line: every variant `RETAIL_LIVE` whose
    `retail_live_at` is more than 240 days in the past becomes
    `REFRESH_CANDIDATE`, stamping `refresh_candidate_at`." and "Step 8 sends
    proven variants to retail: every variant in `DR_TESTING` with at least one
    LaunchCommitment in `OPEN` or `FULFILLED` status becomes `RETAIL_LIVE`,
    stamping `retail_live_at` from the clock."

    Design: Difficulty/transitive_cascade/review_retirement_cascades_variant_to_commitment_to_capacity
    """
    bundle = setup_retail_live_open_commitment()
    variant = bundle["variant"]
    assert variant["lifecycle"] == "RETAIL_LIVE"
    assert _iso(variant["retail_live_at"]) == datetime(2026, 10, 16,
                                                      tzinfo=timezone.utc)
    bundle = advance_variant_to_refresh_candidate(bundle)
    variant = bundle["variant"]
    assert variant["lifecycle"] == "REFRESH_CANDIDATE"
    assert _iso(variant["refresh_candidate_at"]) == datetime(2027, 6, 14,
                                                            tzinfo=timezone.utc)
    # Candidacy alone does not cascade: the OPEN commitment still holds.
    assert get_commitment(bundle["commitment"]["id"])["status"] == "OPEN"
    assert get_partner(bundle["partner"]["id"])["allocated_units"] == 300
    bundle = advance_variant_to_retired(bundle)
    variant = bundle["variant"]
    assert variant["lifecycle"] == "RETIRED"
    assert _iso(variant["retired_at"]) == datetime(2027, 7, 15,
                                                  tzinfo=timezone.utc)
    assert_capacity_conservation(get_partner(bundle["partner"]["id"]), [], [])
