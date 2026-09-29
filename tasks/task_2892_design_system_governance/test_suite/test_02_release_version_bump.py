"""
The release version bump: one forward pass over the carried proposals.

The interesting part of the computation is not the arithmetic of any single step
but the pinning: the ratio and the tier are read from the maturity-adjusted
classes and are never revisited once the tier has escalated individual proposals.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_breaking_ratio, assert_fields
from test_helpers.constants import (
    CLASS_MAJOR,
    CLASS_MINOR,
    EV_MIGRATION_GUIDE,
    KIND_BREAKING_CHANGE,
    KIND_ENHANCEMENT,
    MATURITY_BETA,
    NOTES_PUBLISHED,
    PLATFORM_WEB,
    RELEASE_PUBLISHED,
    STAGE_DESIGN_CRITIQUE,
    STAGE_ENGINEERING_REVIEW,
    TIER_BATCHED,
    TIER_INCREMENTAL,
)
from test_helpers.fixtures import (
    accept,
    file_clean_evidence,
    file_evidence,
    governance_base,
    make_component,
    make_implementation,
    make_proposal,
    make_release,
    promote,
    read_component,
    read_proposal,
    review,
    ship,
    submit,
)
from test_helpers.test_users import make_system_admin_headers


def _beta_component(api, base, name, slug):
    """Register a component and walk it up to BETA through a clean web ship."""
    component = make_component(api, base["team_id"], name=name, slug=slug)
    impl = make_implementation(
        api,
        component["id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name=f"@ds/{slug}-web",
    )
    file_clean_evidence(api, impl["id"], base["team_id"])
    ship(api, impl["id"], base["team_id"])
    promote(api, component["id"], MATURITY_BETA)
    return component


def _carry_proposal(
    api,
    base,
    component_id: str,
    release_id: str,
    proposal_kind: str,
    extra_evidence: Optional[List[str]] = None,
    touches_public_api: Optional[bool] = None,
    title: str = "Carried change",
) -> str:
    """
    Walk one proposal from draft to accepted against the given draft release.

    The proposal is submitted, its computed required evidence is filed together
    with any extra kinds the caller names, both review gates approve it, and a
    lead accepts it echoing the target component's freshly read version.
    """
    overrides = {}
    if touches_public_api is not None:
        overrides["touches_public_api"] = touches_public_api
    proposal = make_proposal(
        api,
        base["team_id"],
        component_id,
        base["token_set_id"],
        title=title,
        proposal_kind=proposal_kind,
        **overrides,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    kinds = list(submitted["required_evidence_kinds"]) + list(extra_evidence or [])
    file_evidence(api, proposal["id"], base["team_id"], kinds)
    review(api, proposal["id"], STAGE_DESIGN_CRITIQUE)
    review(api, proposal["id"], STAGE_ENGINEERING_REVIEW)
    version = read_component(api, component_id)["version"]
    accept(api, proposal["id"], release_id, version)
    return proposal["id"]


def _incremental_release(api):
    """
    A release carrying two breaking changes and one public-API enhancement.

    One breaking change targets a BETA component and keeps its MAJOR class; the
    other targets an EXPERIMENTAL component and is de-escalated to MINOR, which
    is what holds the ratio below the batching threshold.
    """
    base = governance_base(api, component_name="Chart Legend", component_slug="chart-legend")
    release = make_release(api, "4.2.1")
    beta = _beta_component(api, base, "Data Table", "data-table")
    tag_chip = make_component(api, base["team_id"], name="Tag Chip", slug="tag-chip")

    p1 = _carry_proposal(
        api, base, beta["id"], release["id"], KIND_BREAKING_CHANGE, title="Break the table"
    )
    p2 = _carry_proposal(
        api,
        base,
        base["component_id"],
        release["id"],
        KIND_BREAKING_CHANGE,
        title="Break the legend",
    )
    p3 = _carry_proposal(
        api,
        base,
        tag_chip["id"],
        release["id"],
        KIND_ENHANCEMENT,
        touches_public_api=True,
        title="Extend the chip props",
    )
    base.update(
        {
            "release_id": release["id"],
            "beta_component_id": beta["id"],
            "experimental_component_id": base["component_id"],
            "p1": p1,
            "p2": p2,
            "p3": p3,
        }
    )
    return base


def test_breaking_ratio_and_tier_come_from_the_maturity_adjusted_classes(api):
    """The ratio counts step-two MAJOR classes, not the raw ones.

    PRD: "Count the carried proposals whose *step-2* class is `MAJOR`, divide by the number of carried proposals, and round half up to four decimal places."

    One of the three carried proposals is effectively breaking, so the ratio is
    0.3333, the tier stays INCREMENTAL and the version bumps to 5.0.0.

    Design: Difficulty/combinatorial_formula/release_bump_pins_breaking_ratio_to_step_two_classes
    """
    scenario = _incremental_release(api)

    published = validate_success(
        api.publish_release(scenario["release_id"], make_system_admin_headers())
    )
    assert_breaking_ratio(published, 0.3333)
    assert_fields(
        published,
        {
            "policy_tier": TIER_INCREMENTAL,
            "semver": "5.0.0",
            "breaking_change_count": 1,
            "escalated_proposal_count": 1,
            "state": RELEASE_PUBLISHED,
            "release_notes_state": NOTES_PUBLISHED,
        },
        "release",
    )


def test_publication_writes_both_change_classes_onto_every_carried_proposal(api):
    """Every carried proposal keeps its raw class beside its effective one.

    PRD: "A proposal whose step-1 class is `MAJOR` is de-escalated to `MINOR` when the `maturity_level` of the component named by its `target_component_id`, **read at publish time rather than at accept time**, is `EXPERIMENTAL`"

    The experimental target's proposal is stored as raw MAJOR and effective MINOR,
    and publication clears the pending breaking-change counters it created.

    Design: Difficulty/combinatorial_formula/release_bump_pins_breaking_ratio_to_step_two_classes
    """
    scenario = _incremental_release(api)

    validate_success(
        api.publish_release(scenario["release_id"], make_system_admin_headers())
    )

    p1 = read_proposal(api, scenario["p1"])
    p2 = read_proposal(api, scenario["p2"])
    p3 = read_proposal(api, scenario["p3"])
    assert_fields(
        p1, {"raw_change_class": CLASS_MAJOR, "effective_change_class": CLASS_MAJOR}, "p1"
    )
    assert_fields(
        p2, {"raw_change_class": CLASS_MAJOR, "effective_change_class": CLASS_MINOR}, "p2"
    )
    assert_fields(
        p3, {"raw_change_class": CLASS_MINOR, "effective_change_class": CLASS_MINOR}, "p3"
    )

    for component_id in (
        scenario["beta_component_id"],
        scenario["experimental_component_id"],
    ):
        component = read_component(api, component_id)
        assert_fields(
            component,
            {"pending_breaking_change_count": 0, "current_major_version": 2},
            "component",
        )


def _batched_release(api):
    """
    A release carrying one true breaking change and one public-API enhancement.

    With half the carried set effectively breaking, the tier crosses the batching
    threshold and the enhancement is pulled up with it. The enhancement files a
    migration guide it was never required to file, because the escalation makes
    the publish-time guide check apply to it.
    """
    base = governance_base(api, component_name="Tag Chip", component_slug="tag-chip")
    release = make_release(api, "2.7.3")
    beta = _beta_component(api, base, "Data Table", "data-table")

    p1 = _carry_proposal(
        api, base, beta["id"], release["id"], KIND_BREAKING_CHANGE, title="Break the table"
    )
    p2 = _carry_proposal(
        api,
        base,
        base["component_id"],
        release["id"],
        KIND_ENHANCEMENT,
        extra_evidence=[EV_MIGRATION_GUIDE],
        touches_public_api=True,
        title="Extend the chip props",
    )
    base.update({"release_id": release["id"], "p1": p1, "p2": p2})
    return base


def test_batched_tier_escalates_a_public_api_minor_to_major(api):
    """Crossing the batching threshold pulls public-API minors up to major.

    PRD: "Under a `BATCHED` tier, a proposal whose step-2 class is `MINOR` **and** whose `touches_public_api` is true is escalated to `MAJOR`, on the reasoning that a batched breaking window may as well absorb public-API minors; every other proposal keeps its step-2 class."

    Both carried proposals therefore finish effectively breaking, giving a
    breaking-change count of 2 and a semver of 3.0.0.

    Design: Difficulty/combinatorial_formula/release_batched_tier_escalates_public_api_minor_to_major
    """
    scenario = _batched_release(api)

    published = validate_success(
        api.publish_release(scenario["release_id"], make_system_admin_headers())
    )
    assert_fields(
        published,
        {
            "policy_tier": TIER_BATCHED,
            "semver": "3.0.0",
            "breaking_change_count": 2,
            "escalated_proposal_count": 1,
        },
        "release",
    )
    p2 = read_proposal(api, scenario["p2"])
    assert_fields(
        p2, {"raw_change_class": CLASS_MINOR, "effective_change_class": CLASS_MAJOR}, "p2"
    )


def test_the_ratio_is_not_recomputed_after_the_escalation_step(api):
    """The stored ratio still measures the population step three measured.

    PRD: "`breaking_ratio` and `policy_tier` are **not** recomputed from the step-5 classes."

    Both carried proposals end effectively breaking, yet the ratio stays at
    0.5000 rather than being re-derived as 1.0000.

    Design: Difficulty/combinatorial_formula/release_batched_tier_escalates_public_api_minor_to_major
    """
    scenario = _batched_release(api)

    published = validate_success(
        api.publish_release(scenario["release_id"], make_system_admin_headers())
    )
    assert_breaking_ratio(published, 0.5000)
    assert published["policy_tier"] == TIER_BATCHED
    assert published["breaking_change_count"] == 2, (
        "both carried proposals should finish effectively breaking"
    )
    assert round(published["breaking_ratio"], 4) != 1.0000, (
        "the ratio must not be re-derived from the escalated classes"
    )
