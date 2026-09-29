"""Row lookups (PRD 2.9) and the wire representation of every entity."""

import errors
from errors import fail
from store import store


# --------------------------------------------------------------------------
# lookups -- each resource kind has its own dedicated 404
# --------------------------------------------------------------------------
def get_team(team_id):
    row = store.teams.get(team_id)
    if row is None:
        fail(errors.ERR_TEAM_NOT_FOUND, "Team '%s' does not exist." % team_id)
    return row


def get_component(component_id):
    row = store.components.get(component_id)
    if row is None:
        fail(errors.ERR_COMPONENT_NOT_FOUND,
             "Component '%s' does not exist." % component_id)
    return row


def get_dependency(dep_id):
    row = store.deps.get(dep_id)
    if row is None:
        fail(errors.ERR_COMPONENT_DEPENDENCY_NOT_FOUND,
             "Component dependency '%s' does not exist." % dep_id)
    return row


def get_impl(impl_id):
    row = store.impls.get(impl_id)
    if row is None:
        fail(errors.ERR_PLATFORM_IMPLEMENTATION_NOT_FOUND,
             "Platform implementation '%s' does not exist." % impl_id)
    return row


def get_token_set(token_set_id):
    row = store.token_sets.get(token_set_id)
    if row is None:
        fail(errors.ERR_TOKEN_SET_NOT_FOUND,
             "Token set '%s' does not exist." % token_set_id)
    return row


def get_token(token_id):
    row = store.tokens.get(token_id)
    if row is None:
        fail(errors.ERR_TOKEN_NOT_FOUND, "Design token '%s' does not exist." % token_id)
    return row


def get_proposal(proposal_id):
    row = store.proposals.get(proposal_id)
    if row is None:
        fail(errors.ERR_PROPOSAL_NOT_FOUND,
             "Contribution proposal '%s' does not exist." % proposal_id)
    return row


def get_release(release_id):
    row = store.releases.get(release_id)
    if row is None:
        fail(errors.ERR_RELEASE_NOT_FOUND, "Release '%s' does not exist." % release_id)
    return row


def get_plan(plan_id):
    row = store.plans.get(plan_id)
    if row is None:
        fail(errors.ERR_DEPRECATION_PLAN_NOT_FOUND,
             "Deprecation plan '%s' does not exist." % plan_id)
    return row


def get_grant(grant_id):
    row = store.grants.get(grant_id)
    if row is None:
        fail(errors.ERR_EXCEPTION_GRANT_NOT_FOUND,
             "Exception grant '%s' does not exist." % grant_id)
    return row


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------
def _audit_triple(row, out):
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def team_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "platform_scope": row["platform_scope"],
        "debt_budget_points": row["debt_budget_points"],
        "outstanding_debt_points": row["outstanding_debt_points"],
        "lifetime_debt_points": row["lifetime_debt_points"],
        "debt_state": row["debt_state"],
        "blocked_implementation_count": row["blocked_implementation_count"],
        "adoption_index_latest": row["adoption_index_latest"],
        "adoption_index_trailing": row["adoption_index_trailing"],
    })


def component_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "owning_team_id": row["owning_team_id"],
        "maturity_level": row["maturity_level"],
        "lifecycle_state": row["lifecycle_state"],
        "current_major_version": row["current_major_version"],
        "docs_state": row["docs_state"],
        "docs_last_reviewed_at": row["docs_last_reviewed_at"],
        "shipped_platform_count": row["shipped_platform_count"],
        "coverage_state": row["coverage_state"],
        "governance_conformance_score": row["governance_conformance_score"],
        "conformance_baseline_at": row["conformance_baseline_at"],
        "blocked_dependency_count": row["blocked_dependency_count"],
        "pending_breaking_change_count": row["pending_breaking_change_count"],
        "maturity_demotion_reason": row["maturity_demotion_reason"],
        "one_off_exception_count": row["one_off_exception_count"],
    })


def impl_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "component_id": row["component_id"],
        "platform": row["platform"],
        "package_name": row["package_name"],
        "package_version": row["package_version"],
        "token_compliance_ratio": row["token_compliance_ratio"],
        "status": row["status"],
        "conformance_score": row["conformance_score"],
        "last_audit_sequence": row["last_audit_sequence"],
        "blocked_reason": row["blocked_reason"],
        "shipped_at": row["shipped_at"],
    })


def dependency_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "consumer_component_id": row["consumer_component_id"],
        "provider_component_id": row["provider_component_id"],
        "pinned_provider_major": row["pinned_provider_major"],
        "compatibility_state": row["compatibility_state"],
    })


def token_set_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "default_brand": row["default_brand"],
        "default_mode": row["default_mode"],
        "token_count": row["token_count"],
        "max_alias_depth": row["max_alias_depth"],
    })


def token_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "token_set_id": row["token_set_id"],
        "name": row["name"],
        "category": row["category"],
        "brand": row["brand"],
        "mode": row["mode"],
        "raw_value": row["raw_value"],
        "alias_of_token_id": row["alias_of_token_id"],
        "alias_depth": row["alias_depth"],
        "resolved_value": row["resolved_value"],
    })


def proposal_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "title": row["title"],
        "author_team_id": row["author_team_id"],
        "target_component_id": row["target_component_id"],
        "pinned_token_set_id": row["pinned_token_set_id"],
        "released_in_release_id": row["released_in_release_id"],
        "proposal_kind": row["proposal_kind"],
        "touches_public_api": row["touches_public_api"],
        "state": row["state"],
        "revision_round": row["revision_round"],
        "pinned_token_set_version": row["pinned_token_set_version"],
        "required_evidence_kinds": list(row["required_evidence_kinds"]),
        "submitted_evidence_kinds": list(row["submitted_evidence_kinds"]),
        "raw_change_class": row["raw_change_class"],
        "effective_change_class": row["effective_change_class"],
        "design_critique_reviewer_user_id": row["design_critique_reviewer_user_id"],
        "engineering_reviewer_user_id": row["engineering_reviewer_user_id"],
        "submitted_at": row["submitted_at"],
        "accepted_at": row["accepted_at"],
    })


def review_json(row):
    return {
        "id": row["id"],
        "proposal_id": row["proposal_id"],
        "stage": row["stage"],
        "verdict": row["verdict"],
        "notes": row["notes"],
        "reviewer_user_id": row["reviewer_user_id"],
        "revision_round": row["revision_round"],
        "resulting_proposal_state": row["resulting_proposal_state"],
        "created_at": row["created_at"],
    }


def release_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "semver_base": row["semver_base"],
        "channel": row["channel"],
        "state": row["state"],
        "semver": row["semver"],
        "policy_tier": row["policy_tier"],
        "breaking_ratio": row["breaking_ratio"],
        "breaking_change_count": row["breaking_change_count"],
        "escalated_proposal_count": row["escalated_proposal_count"],
        "release_notes_state": row["release_notes_state"],
        "published_at": row["published_at"],
    })


def plan_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "component_id": row["component_id"],
        "replacement_component_id": row["replacement_component_id"],
        "announced_at": row["announced_at"],
        "sunset_at": row["sunset_at"],
        "removal_at": row["removal_at"],
        "migration_guide_url": row["migration_guide_url"],
        "migration_guide_state": row["migration_guide_state"],
        "required_notice_days": row["required_notice_days"],
        "actual_notice_days": row["actual_notice_days"],
        "state": row["state"],
        "blocked_dependent_count": row["blocked_dependent_count"],
        "rescinded_at": row["rescinded_at"],
    })


def audit_json(row):
    return {
        "id": row["id"],
        "platform_implementation_id": row["platform_implementation_id"],
        "method": row["method"],
        "wcag_level": row["wcag_level"],
        "violations_critical": row["violations_critical"],
        "violations_serious": row["violations_serious"],
        "violations_moderate": row["violations_moderate"],
        "evidence_url": row["evidence_url"],
        "audit_sequence": row["audit_sequence"],
        "defect_load": row["defect_load"],
        "audited_at": row["audited_at"],
        "created_at": row["created_at"],
    }


def scan_json(row):
    return {
        "id": row["id"],
        "team_id": row["team_id"],
        "scan_kind": row["scan_kind"],
        "window_start_at": row["window_start_at"],
        "window_end_at": row["window_end_at"],
        "system_instance_count": row["system_instance_count"],
        "legacy_instance_count": row["legacy_instance_count"],
        "one_off_instance_count": row["one_off_instance_count"],
        "adoption_ratio": row["adoption_ratio"],
        "scanned_at": row["scanned_at"],
        "created_at": row["created_at"],
    }


def grant_json(row):
    return _audit_triple(row, {
        "id": row["id"],
        "requesting_team_id": row["requesting_team_id"],
        "substitute_for_component_id": row["substitute_for_component_id"],
        "exception_kind": row["exception_kind"],
        "platform_scope": row["platform_scope"],
        "justification": row["justification"],
        "expires_at": row["expires_at"],
        "state": row["state"],
        "debt_points": row["debt_points"],
        "pinned_maturity_level": row["pinned_maturity_level"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": row["decided_at"],
        "repaid_at": row["repaid_at"],
    })
