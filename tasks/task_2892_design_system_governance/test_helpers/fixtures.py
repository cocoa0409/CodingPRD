"""
Composite setup builders.

Each test starts against an empty database, so every precondition has to be built
through the API itself. The helpers here are the shared vocabulary for doing that:
small single-call wrappers that raise a readable error when a setup step fails,
and larger scenario builders that assemble the recurring governance situations —
a shipped web implementation, a proposal parked at the acceptance gate, a
provider/consumer pair joined by a dependency edge.

Every builder returns plain dictionaries of rows and ids so that a test can read
whatever it needs without a second round trip.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    AUDIT_METHOD_AUTOMATED,
    AUDIT_METHOD_MANUAL,
    DEFAULT_CLOCK,
    KIND_ENHANCEMENT,
    MATURITY_BETA,
    MATURITY_STABLE,
    PLATFORM_IOS,
    PLATFORM_WEB,
    STAGE_DESIGN_CRITIQUE,
    STAGE_ENGINEERING_REVIEW,
    VERDICT_APPROVE,
)
from . import factories as f
from .test_users import (
    CRITIC_USER_ID,
    ENGINEER_USER_ID,
    make_contributing_team_headers,
    make_design_critique_reviewer_headers,
    make_design_system_lead_headers,
    make_engineering_reviewer_headers,
    make_system_admin_headers,
)
from .types import Payload, Row


# ─── Single-call setup wrappers ───────────────────────

def pin_clock(api: ApiClient, instant: str = DEFAULT_CLOCK) -> Row:
    """Move the logical clock to a known instant so every stamp is predictable."""
    return get_success_data(
        api.set_clock(instant, make_system_admin_headers())
    )


def make_team(api: ApiClient, **overrides: Any) -> Row:
    """Register a team and return its row."""
    return get_success_data(
        api.create_team(f.team_payload(**overrides), make_system_admin_headers())
    )


def make_token_set(api: ApiClient, **overrides: Any) -> Row:
    """Provision a token set and return its row."""
    return get_success_data(
        api.create_token_set(
            f.token_set_payload(**overrides), make_design_system_lead_headers()
        )
    )


def make_component(api: ApiClient, owning_team_id: str, **overrides: Any) -> Row:
    """Register a component owned by the given team and return its row."""
    return get_success_data(
        api.create_component(
            f.component_payload(owning_team_id, **overrides),
            make_design_system_lead_headers(),
        )
    )


def make_implementation(
    api: ApiClient, component_id: str, team_id: str, **overrides: Any
) -> Row:
    """Declare a platform implementation as the owning team."""
    return get_success_data(
        api.create_implementation(
            component_id,
            f.implementation_payload(**overrides),
            make_contributing_team_headers(team_id),
        )
    )


def file_audit(
    api: ApiClient,
    implementation_id: str,
    team_id: str,
    critical: int = 0,
    serious: int = 0,
    moderate: int = 0,
    method: str = AUDIT_METHOD_AUTOMATED,
    **overrides: Any,
) -> Row:
    """File one accessibility audit against the implementation."""
    return get_success_data(
        api.create_accessibility_audit(
            implementation_id,
            f.audit_payload(critical, serious, moderate, method=method, **overrides),
            make_contributing_team_headers(team_id),
        )
    )


def file_clean_evidence(
    api: ApiClient, implementation_id: str, team_id: str
) -> List[Row]:
    """
    File one clean automated pass and one clean manual pass.

    Two methods with no findings is the evidence set that scores 100.00, which is
    what a test needs whenever accessibility must not be the thing under test.
    """
    return [
        file_audit(api, implementation_id, team_id, method=AUDIT_METHOD_AUTOMATED),
        file_audit(api, implementation_id, team_id, method=AUDIT_METHOD_MANUAL),
    ]


def ship(
    api: ApiClient,
    implementation_id: str,
    team_id: str,
    package_version: str = "1.0.0",
    token_compliance_ratio: float = 0.95,
    **overrides: Any,
) -> Row:
    """Ship the implementation as its owning team."""
    return get_success_data(
        api.ship_implementation(
            implementation_id,
            f.ship_payload(package_version, token_compliance_ratio, **overrides),
            make_contributing_team_headers(team_id),
        )
    )


def declare_dependency(
    api: ApiClient,
    consumer_component_id: str,
    provider_component_id: str,
    pinned_provider_major: int = 1,
) -> Row:
    """Declare a dependency edge from consumer to provider."""
    return get_success_data(
        api.create_dependency(
            consumer_component_id,
            f.dependency_payload(provider_component_id, pinned_provider_major),
            make_design_system_lead_headers(),
        )
    )


def promote(api: ApiClient, component_id: str, target: str) -> Row:
    """Promote the component's maturity one step."""
    return get_success_data(
        api.promote_maturity(
            component_id, f.promote_payload(target), make_design_system_lead_headers()
        )
    )


def make_proposal(
    api: ApiClient,
    team_id: str,
    target_component_id: str,
    pinned_token_set_id: str,
    **overrides: Any,
) -> Row:
    """Open a contribution proposal in draft as its authoring team."""
    return get_success_data(
        api.create_proposal(
            f.proposal_payload(
                team_id, target_component_id, pinned_token_set_id, **overrides
            ),
            make_contributing_team_headers(team_id),
        )
    )


def submit(api: ApiClient, proposal_id: str, team_id: str) -> Row:
    """Submit or resubmit the proposal into design critique."""
    return get_success_data(
        api.submit_proposal(proposal_id, make_contributing_team_headers(team_id))
    )


def file_evidence(
    api: ApiClient, proposal_id: str, team_id: str, kinds: List[str], **overrides: Any
) -> Row:
    """Attach acceptance evidence kinds to the proposal."""
    return get_success_data(
        api.file_acceptance_evidence(
            proposal_id,
            f.evidence_payload(kinds, **overrides),
            make_contributing_team_headers(team_id),
        )
    )


def review(
    api: ApiClient,
    proposal_id: str,
    stage: str,
    verdict: str = VERDICT_APPROVE,
    user_id: Optional[str] = None,
) -> Row:
    """File one review verdict at the named gate with the role that owns it."""
    if stage == STAGE_DESIGN_CRITIQUE:
        headers = make_design_critique_reviewer_headers(user_id or CRITIC_USER_ID)
    else:
        headers = make_engineering_reviewer_headers(user_id or ENGINEER_USER_ID)
    return get_success_data(
        api.create_review(proposal_id, f.review_payload(stage, verdict), headers)
    )


def make_release(api: ApiClient, semver_base: str = "1.0.0", **overrides: Any) -> Row:
    """Cut a draft release."""
    return get_success_data(
        api.create_release(
            f.release_payload(semver_base, **overrides), make_system_admin_headers()
        )
    )


def accept(
    api: ApiClient, proposal_id: str, release_id: str, expected_component_version: int
) -> Row:
    """Accept a ready proposal into a draft release."""
    return get_success_data(
        api.accept_proposal(
            proposal_id,
            f.accept_payload(release_id, expected_component_version),
            make_design_system_lead_headers(),
        )
    )


def make_plan(
    api: ApiClient,
    component_id: str,
    announced_at: str,
    sunset_at: str,
    removal_at: str,
    **overrides: Any,
) -> Row:
    """Draft a deprecation plan for the component."""
    return get_success_data(
        api.create_deprecation_plan(
            component_id,
            f.deprecation_plan_payload(
                announced_at, sunset_at, removal_at, **overrides
            ),
            make_design_system_lead_headers(),
        )
    )


def announce_plan(api: ApiClient, plan_id: str, **overrides: Any) -> Row:
    """Publish the plan's migration guide, which announces the deprecation."""
    return get_success_data(
        api.attach_migration_guide(
            plan_id,
            f.migration_guide_payload(publish=True, **overrides),
            make_design_system_lead_headers(),
        )
    )


def advance_plan(api: ApiClient, plan_id: str) -> Row:
    """Advance the plan one step once the clock has reached its due instant."""
    return get_success_data(
        api.advance_deprecation_plan(plan_id, make_design_system_lead_headers())
    )


def request_grant(
    api: ApiClient,
    team_id: str,
    substitute_for_component_id: str,
    expires_at: str = "2026-12-31T00:00:00.000Z",
    **overrides: Any,
) -> Row:
    """Request an exception grant as the requesting team."""
    return get_success_data(
        api.create_exception_grant(
            f.exception_grant_payload(
                team_id, substitute_for_component_id, expires_at, **overrides
            ),
            make_contributing_team_headers(team_id),
        )
    )


def approve_grant(api: ApiClient, grant_id: str, **overrides: Any) -> Row:
    """Approve a requested grant, charging its debt to the requesting team."""
    return get_success_data(
        api.decide_exception_grant(
            grant_id, f.decision_payload(**overrides), make_design_system_lead_headers()
        )
    )


# ─── Read-through helpers ─────────────────────────────

def read_component(api: ApiClient, component_id: str) -> Row:
    """Read one component with every governance roll-up."""
    return get_success_data(
        api.get_component(component_id, make_design_system_lead_headers())
    )


def read_team(api: ApiClient, team_id: str) -> Row:
    """Read one team with its debt and adoption roll-ups."""
    return get_success_data(api.get_team(team_id, make_design_system_lead_headers()))


def read_implementation(api: ApiClient, implementation_id: str) -> Row:
    """Read one platform implementation."""
    return get_success_data(
        api.get_implementation(implementation_id, make_design_system_lead_headers())
    )


def read_proposal(api: ApiClient, proposal_id: str) -> Row:
    """Read one contribution proposal."""
    return get_success_data(
        api.get_proposal(proposal_id, make_design_system_lead_headers())
    )


def read_token_set(api: ApiClient, token_set_id: str) -> Row:
    """Read one token set, which is where the OCC version comes from."""
    return get_success_data(
        api.get_token_set(token_set_id, make_design_system_lead_headers())
    )


def read_grant(api: ApiClient, grant_id: str) -> Row:
    """Read one exception grant."""
    return get_success_data(
        api.get_exception_grant(grant_id, make_design_system_lead_headers())
    )


# ─── Scenario builders ────────────────────────────────

def governance_base(
    api: ApiClient,
    team_name: str = "Design Guild",
    team_slug: Optional[str] = None,
    component_name: str = "Badge",
    component_slug: Optional[str] = None,
    team_overrides: Optional[Payload] = None,
    component_overrides: Optional[Payload] = None,
) -> Dict[str, Any]:
    """
    The starting position almost every test needs.

    Pins the clock, registers one team, provisions one token set and registers one
    component owned by that team. Returns the three rows plus their ids and the
    contributing-team headers built from the real team id.
    """
    pin_clock(api)
    team = make_team(
        api, name=team_name, slug=team_slug, **(team_overrides or {})
    )
    token_set = make_token_set(api)
    component = make_component(
        api,
        team["id"],
        name=component_name,
        slug=component_slug,
        **(component_overrides or {}),
    )
    return {
        "team": team,
        "team_id": team["id"],
        "team_headers": make_contributing_team_headers(team["id"]),
        "token_set": token_set,
        "token_set_id": token_set["id"],
        "component": component,
        "component_id": component["id"],
    }


def shipped_web_implementation(
    api: ApiClient,
    package_version: str = "1.0.0",
    token_compliance_ratio: float = 0.95,
    **base_overrides: Any,
) -> Dict[str, Any]:
    """
    A component with one shipped web implementation carrying clean evidence.

    Clean automated and manual passes are filed first, so the shipped
    implementation scores 100.00 and coverage reads WEB_ONLY.
    """
    base = governance_base(api, **base_overrides)
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_version=package_version,
    )
    file_clean_evidence(api, impl["id"], base["team_id"])
    shipped = ship(
        api,
        impl["id"],
        base["team_id"],
        package_version=package_version,
        token_compliance_ratio=token_compliance_ratio,
    )
    base.update({"implementation": shipped, "implementation_id": impl["id"]})
    return base


def stable_component_with_two_platforms(
    api: ApiClient, **base_overrides: Any
) -> Dict[str, Any]:
    """
    A component promoted all the way to stable.

    Web and iOS implementations are shipped with clean evidence, which gives
    partial coverage and a 100.00 conformance score; the component's docs page is
    published so that the stable gate on documentation is satisfied.
    """
    overrides = dict(base_overrides)
    component_overrides = dict(overrides.pop("component_overrides", None) or {})
    component_overrides.setdefault("docs_state", "PUBLISHED")
    base = governance_base(api, component_overrides=component_overrides, **overrides)

    web = make_implementation(
        api, base["component_id"], base["team_id"], platform=PLATFORM_WEB
    )
    file_clean_evidence(api, web["id"], base["team_id"])
    ship(api, web["id"], base["team_id"])

    ios = make_implementation(
        api, base["component_id"], base["team_id"], platform=PLATFORM_IOS
    )
    file_clean_evidence(api, ios["id"], base["team_id"])
    ship(api, ios["id"], base["team_id"])

    promote(api, base["component_id"], MATURITY_BETA)
    stable = promote(api, base["component_id"], MATURITY_STABLE)

    base.update(
        {
            "web_implementation_id": web["id"],
            "ios_implementation_id": ios["id"],
            "component": stable,
        }
    )
    return base


def provider_and_consumer(
    api: ApiClient,
    pinned_provider_major: int = 1,
    provider_name: str = "Icon Set",
    consumer_name: str = "Menu Button",
) -> Dict[str, Any]:
    """
    Two components joined by one dependency edge.

    The consumer is registered second and the edge points from consumer to
    provider, which is the direction the API records.
    """
    base = governance_base(api, component_name=provider_name)
    provider_id = base["component_id"]
    consumer = make_component(api, base["team_id"], name=consumer_name)
    edge = declare_dependency(
        api, consumer["id"], provider_id, pinned_provider_major
    )
    base.update(
        {
            "provider": base["component"],
            "provider_id": provider_id,
            "consumer": consumer,
            "consumer_id": consumer["id"],
            "dependency": edge,
            "dependency_id": edge["id"],
        }
    )
    return base


def proposal_at_acceptance_gate(
    api: ApiClient,
    proposal_kind: str = KIND_ENHANCEMENT,
    evidence_kinds: Optional[List[str]] = None,
    semver_base: str = "1.0.0",
    critique_user_id: str = CRITIC_USER_ID,
    engineering_user_id: str = ENGINEER_USER_ID,
    **base_overrides: Any,
) -> Dict[str, Any]:
    """
    A proposal walked from draft to the acceptance gate, with a draft release ready.

    The proposal is submitted, its required evidence is filed, and both review
    gates approve it, which leaves it ready for acceptance. The two reviewers are
    distinct users so that the segregation-of-duties rule is satisfied.
    """
    base = governance_base(api, **base_overrides)
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        proposal_kind=proposal_kind,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    kinds = evidence_kinds
    if kinds is None:
        kinds = list(submitted["required_evidence_kinds"])
    file_evidence(api, proposal["id"], base["team_id"], kinds)
    review(
        api,
        proposal["id"],
        STAGE_DESIGN_CRITIQUE,
        VERDICT_APPROVE,
        user_id=critique_user_id,
    )
    engineering_review = review(
        api,
        proposal["id"],
        STAGE_ENGINEERING_REVIEW,
        VERDICT_APPROVE,
        user_id=engineering_user_id,
    )
    release = make_release(api, semver_base)
    base.update(
        {
            # `review` returns the immutable review record the gate wrote, not the
            # proposal it advanced, so the proposal row is read back explicitly.
            "proposal": read_proposal(api, proposal["id"]),
            "engineering_review": engineering_review,
            "proposal_id": proposal["id"],
            "submitted": submitted,
            "release": release,
            "release_id": release["id"],
            "required_evidence_kinds": list(submitted["required_evidence_kinds"]),
        }
    )
    return base


def leaf_token(
    api: ApiClient,
    token_set_id: str,
    name: str,
    raw_value: str,
    expected_token_set_version: int,
    **overrides: Any,
) -> Row:
    """Write one raw-valued token into the set."""
    return get_success_data(
        api.create_token(
            f.leaf_token_payload(
                token_set_id, name, raw_value, expected_token_set_version, **overrides
            ),
            make_design_system_lead_headers(),
        )
    )


def alias_token(
    api: ApiClient,
    token_set_id: str,
    name: str,
    alias_of_token_id: str,
    expected_token_set_version: int,
    **overrides: Any,
) -> Row:
    """Write one alias token pointing at another token in the same set."""
    return get_success_data(
        api.create_token(
            f.alias_token_payload(
                token_set_id,
                name,
                alias_of_token_id,
                expected_token_set_version,
                **overrides,
            ),
            make_design_system_lead_headers(),
        )
    )


def alias_chain(
    api: ApiClient, token_set_id: str, depth: int, raw_value: str = "#000000"
) -> Dict[str, Any]:
    """
    Build a leaf plus `depth` alias hops on top of it.

    Returns the rows in walk order, leaf first, together with the token set's
    version after the last write so that a caller can keep writing.
    """
    version = read_token_set(api, token_set_id)["version"]
    rows = [
        leaf_token(api, token_set_id, "color.chain.0", raw_value, version)
    ]
    version += 1
    for hop in range(1, depth + 1):
        rows.append(
            alias_token(
                api,
                token_set_id,
                f"color.chain.{hop}",
                rows[-1]["id"],
                version,
            )
        )
        version += 1
    return {"tokens": rows, "token_set_version": version}
