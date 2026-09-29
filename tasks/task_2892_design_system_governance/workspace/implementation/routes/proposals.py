"""The contribution pipeline (PRD 3.6)."""

from flask import Blueprint

import calc
import errors
from auth import (CONTRIBUTING_TEAM, DESIGN_CRITIQUE_REVIEWER, DESIGN_SYSTEM_LEAD,
                  ENGINEERING_REVIEWER, actor_id, ensure_owner, require_roles)
from entities import (get_component, get_proposal, get_release, get_team,
                      get_token_set, proposal_json, review_json)
from errors import fail
from responses import created, ok
from routes.common import respond_list
from store import sort_created_asc, store
from validation import (body, opt_bool, pagination, query_enum, query_int,
                        query_string, req_enum, req_field, req_int, req_string)

bp = Blueprint("proposals", __name__, url_prefix="/design-system")

PROPOSAL_KINDS = ("NEW_COMPONENT", "ENHANCEMENT", "BREAKING_CHANGE")
PROPOSAL_STATES = ("DRAFT", "DESIGN_CRITIQUE", "ENGINEERING_REVIEW",
                   "CHANGES_REQUESTED", "READY_FOR_ACCEPTANCE", "ACCEPTED",
                   "REJECTED")
STAGES = ("DESIGN_CRITIQUE", "ENGINEERING_REVIEW")
VERDICTS = ("APPROVE", "REQUEST_CHANGES", "BLOCK")
EVIDENCE_KINDS = calc.EVIDENCE_KINDS


@bp.post("/contribution-proposals")
@require_roles(CONTRIBUTING_TEAM)
def create_proposal():
    payload = body()
    title = req_string(payload, "title", 1, 160)
    author_team_id = req_string(payload, "author_team_id", 1, 200)
    target_component_id = req_string(payload, "target_component_id", 1, 200)
    pinned_token_set_id = req_string(payload, "pinned_token_set_id", 1, 200)
    proposal_kind = req_enum(payload, "proposal_kind", PROPOSAL_KINDS)
    touches_public_api = opt_bool(payload, "touches_public_api", False)

    team = get_team(author_team_id)
    get_component(target_component_id)
    get_token_set(pinned_token_set_id)
    ensure_owner(team["id"])

    if team["debt_state"] != "CLEAR":
        fail(errors.ERR_TEAM_DEBT_FROZEN,
             "The authoring team's technical-debt budget is frozen.")

    row = store.new_row()
    row.update({
        "title": title,
        "author_team_id": team["id"],
        "target_component_id": target_component_id,
        "pinned_token_set_id": pinned_token_set_id,
        "released_in_release_id": None,
        "proposal_kind": proposal_kind,
        "touches_public_api": touches_public_api,
        "state": "DRAFT",
        "revision_round": 0,
        "pinned_token_set_version": None,
        "required_evidence_kinds": [],
        "submitted_evidence_kinds": [],
        "raw_change_class": None,
        "effective_change_class": None,
        "design_critique_reviewer_user_id": None,
        "engineering_reviewer_user_id": None,
        "submitted_at": None,
        "accepted_at": None,
    })
    store.proposals[row["id"]] = row
    return created(proposal_json(row))


@bp.get("/contribution-proposals")
@require_roles()
def list_proposals():
    limit, offset = pagination()
    author_team_id = query_string("author_team_id")
    target_component_id = query_string("target_component_id")
    pinned_token_set_id = query_string("pinned_token_set_id")
    released_in_release_id = query_string("released_in_release_id")
    state = query_enum("state", PROPOSAL_STATES)

    rows = list(store.proposals.values())
    if author_team_id is not None:
        rows = [p for p in rows if p["author_team_id"] == author_team_id]
    if target_component_id is not None:
        rows = [p for p in rows if p["target_component_id"] == target_component_id]
    if pinned_token_set_id is not None:
        rows = [p for p in rows if p["pinned_token_set_id"] == pinned_token_set_id]
    if released_in_release_id is not None:
        rows = [p for p in rows
                if p["released_in_release_id"] == released_in_release_id]
    if state is not None:
        rows = [p for p in rows if p["state"] == state]
    return respond_list(sort_created_asc(rows), proposal_json, limit, offset)


@bp.get("/contribution-proposals/<proposal_id>")
@require_roles()
def read_proposal(proposal_id):
    proposal = get_proposal(proposal_id)
    ensure_owner(proposal["author_team_id"])
    return ok(proposal_json(proposal))


@bp.post("/contribution-proposals/<proposal_id>/submit")
@require_roles(CONTRIBUTING_TEAM)
def submit_proposal(proposal_id):
    proposal = get_proposal(proposal_id)
    ensure_owner(proposal["author_team_id"])

    if proposal["state"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail(errors.ERR_INVALID_PROPOSAL_STATE,
             "A proposal in %s cannot be submitted." % proposal["state"])

    component = store.components[proposal["target_component_id"]]
    if component["lifecycle_state"] not in ("ACTIVE", "DEPRECATION_ANNOUNCED"):
        fail(errors.ERR_COMPONENT_DEPRECATION_IN_PROGRESS,
             "The target component's lifecycle blocks new submissions.")

    next_round = 1 if proposal["state"] == "DRAFT" else proposal["revision_round"] + 1
    if next_round > 3:
        fail(errors.ERR_REVISION_LIMIT_EXCEEDED,
             "A proposal may not exceed three revision rounds.")

    team = store.teams[proposal["author_team_id"]]
    if team["debt_state"] != "CLEAR":
        fail(errors.ERR_TEAM_DEBT_FROZEN,
             "The authoring team's technical-debt budget is frozen.")

    token_set = store.token_sets[proposal["pinned_token_set_id"]]

    if proposal["state"] == "DRAFT":
        proposal["revision_round"] = 1
        proposal["submitted_evidence_kinds"] = []
    else:
        proposal["revision_round"] = next_round
        proposal["submitted_evidence_kinds"] = sorted(
            k for k in proposal["submitted_evidence_kinds"]
            if k in calc.ROUND_DURABLE_KINDS)

    proposal["state"] = "DESIGN_CRITIQUE"
    proposal["submitted_at"] = store.now_iso
    proposal["pinned_token_set_version"] = token_set["version"]
    proposal["required_evidence_kinds"] = calc.required_evidence_kinds(
        proposal["proposal_kind"], component["coverage_state"])
    store.touch(proposal)
    return ok(proposal_json(proposal))


@bp.post("/contribution-proposals/<proposal_id>/acceptance-evidence")
@require_roles(CONTRIBUTING_TEAM)
def file_acceptance_evidence(proposal_id):
    payload = body()
    kinds = req_field(payload, "evidence_kinds")
    if not isinstance(kinds, list) or not kinds:
        fail(errors.ERR_INVALID_REQUEST,
             "Field 'evidence_kinds' must be a non-empty array.")
    for kind in kinds:
        if not isinstance(kind, str) or kind not in EVIDENCE_KINDS:
            fail(errors.ERR_INVALID_REQUEST,
                 "Field 'evidence_kinds' contains an unknown evidence kind.")
    req_string(payload, "evidence_url", 1, 500)

    proposal = get_proposal(proposal_id)
    ensure_owner(proposal["author_team_id"])

    merged = set(proposal["submitted_evidence_kinds"]) | set(kinds)
    proposal["submitted_evidence_kinds"] = sorted(merged)
    store.touch(proposal)
    return ok(proposal_json(proposal))


# --------------------------------------------------------------------------
# review gates
# --------------------------------------------------------------------------
STAGE_ROLE = {"DESIGN_CRITIQUE": DESIGN_CRITIQUE_REVIEWER,
              "ENGINEERING_REVIEW": ENGINEERING_REVIEWER}


@bp.post("/contribution-proposals/<proposal_id>/reviews")
@require_roles(DESIGN_CRITIQUE_REVIEWER, ENGINEERING_REVIEWER)
def file_review(proposal_id):
    payload = body()
    stage = req_enum(payload, "stage", STAGES)
    verdict = req_enum(payload, "verdict", VERDICTS)
    notes = req_string(payload, "notes", 1, 2000)

    proposal = get_proposal(proposal_id)

    if proposal["state"] not in STAGES:
        fail(errors.ERR_INVALID_PROPOSAL_STATE,
             "A proposal in %s has no open review gate." % proposal["state"])

    from flask import g
    if stage != proposal["state"] or g.user_role != STAGE_ROLE[stage] or \
            (verdict == "BLOCK" and stage != "ENGINEERING_REVIEW"):
        fail(errors.ERR_REVIEW_STAGE_MISMATCH,
             "The verdict does not match the proposal's open review gate.")

    other_id = (proposal["engineering_reviewer_user_id"]
                if stage == "DESIGN_CRITIQUE"
                else proposal["design_critique_reviewer_user_id"])
    if other_id is not None and other_id == actor_id():
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The two review gates must be filed by different operators.")

    if stage == "DESIGN_CRITIQUE":
        proposal["design_critique_reviewer_user_id"] = actor_id()
        resulting = "ENGINEERING_REVIEW" if verdict == "APPROVE" else "CHANGES_REQUESTED"
    else:
        proposal["engineering_reviewer_user_id"] = actor_id()
        if verdict == "APPROVE":
            resulting = "READY_FOR_ACCEPTANCE"
        elif verdict == "REQUEST_CHANGES":
            resulting = "CHANGES_REQUESTED"
        else:
            resulting = "REJECTED"

    record = store.new_row(mutable=False)
    record.update({
        "proposal_id": proposal["id"],
        "stage": stage,
        "verdict": verdict,
        "notes": notes,
        "reviewer_user_id": actor_id(),
        "revision_round": proposal["revision_round"],
        "resulting_proposal_state": resulting,
    })
    store.reviews[record["id"]] = record

    proposal["state"] = resulting
    if resulting == "REJECTED":
        proposal["required_evidence_kinds"] = []
        proposal["submitted_evidence_kinds"] = []
    store.touch(proposal)
    return created(review_json(record))


@bp.get("/contribution-proposals/<proposal_id>/reviews")
@require_roles()
def list_reviews(proposal_id):
    limit, offset = pagination()
    stage = query_enum("stage", STAGES)
    revision_round = query_int("revision_round", minimum=0)
    proposal = get_proposal(proposal_id)
    ensure_owner(proposal["author_team_id"])

    rows = [r for r in store.reviews.values() if r["proposal_id"] == proposal["id"]]
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    if revision_round is not None:
        rows = [r for r in rows if r["revision_round"] == revision_round]
    return respond_list(sort_created_asc(rows), review_json, limit, offset)


# --------------------------------------------------------------------------
# acceptance and the four-hop breaking-change cascade (PRD 3.6)
# --------------------------------------------------------------------------
@bp.post("/contribution-proposals/<proposal_id>/accept")
@require_roles(DESIGN_SYSTEM_LEAD)
def accept_proposal(proposal_id):
    payload = body()
    release_id = req_string(payload, "release_id", 1, 200)
    expected_component_version = req_int(payload, "expected_component_version",
                                         minimum=0)

    proposal = get_proposal(proposal_id)
    release = get_release(release_id)

    if proposal["state"] != "READY_FOR_ACCEPTANCE":
        fail(errors.ERR_INVALID_PROPOSAL_STATE,
             "A proposal in %s cannot be accepted." % proposal["state"])
    if release["state"] != "DRAFT":
        fail(errors.ERR_INVALID_RELEASE_STATE,
             "Only a DRAFT release can carry an accepted proposal.")

    component = store.components[proposal["target_component_id"]]
    if expected_component_version != component["version"]:
        fail(errors.ERR_STALE_COMPONENT_VERSION,
             "The target component is at version %s." % component["version"])

    reviewer_ids = (proposal["design_critique_reviewer_user_id"],
                    proposal["engineering_reviewer_user_id"])
    if actor_id() in [r for r in reviewer_ids if r is not None]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The accepting lead must be a third party to both review gates.")

    token_set = store.token_sets[proposal["pinned_token_set_id"]]
    if token_set["version"] != proposal["pinned_token_set_version"]:
        fail(errors.ERR_PINNED_TOKEN_SET_STALE,
             "The pinned token set has moved since the proposal was submitted.")

    if not set(proposal["required_evidence_kinds"]).issubset(
            set(proposal["submitted_evidence_kinds"])):
        fail(errors.ERR_ACCEPTANCE_EVIDENCE_INCOMPLETE,
             "The proposal is missing required acceptance evidence.")

    proposal["state"] = "ACCEPTED"
    proposal["accepted_at"] = store.now_iso
    proposal["released_in_release_id"] = release["id"]
    store.touch(proposal)

    component_dirty = False
    if "DOC_PAGE" in proposal["submitted_evidence_kinds"]:
        component["docs_state"] = "PUBLISHED"
        component["docs_last_reviewed_at"] = store.now_iso
        component_dirty = True

    if proposal["proposal_kind"] == "BREAKING_CHANGE":
        _breaking_change_cascade(component)
    elif component_dirty:
        store.touch(component, bump=False)

    return ok(proposal_json(proposal))


def _breaking_change_cascade(component):
    """Hops 1-4 of PRD 3.6; every touched row is versioned exactly once."""
    # Hop 1 -- the accepted breaking change lands on the provider component.
    component["current_major_version"] += 1
    component["pending_breaking_change_count"] += 1
    store.touch(component)

    # Hop 2 -- fires because hop 1 moved current_major_version.
    affected_consumers = []
    for edge in calc.incoming_edges(component["id"]):
        if edge["compatibility_state"] == "COMPATIBLE" and \
                edge["pinned_provider_major"] < component["current_major_version"]:
            edge["compatibility_state"] = "INCOMPATIBLE"
            store.touch(edge)
            consumer = store.components.get(edge["consumer_component_id"])
            if consumer is not None and consumer not in affected_consumers:
                affected_consumers.append(consumer)

    for consumer in affected_consumers:
        calc.recompute_blocked_dependency_count(consumer)

    # Hop 3 -- fires because hop 2 raised those consumers' blocked_dependency_count.
    for consumer in affected_consumers:
        for impl in calc.component_impls(consumer["id"]):
            if impl["status"] == "SHIPPED":
                impl["status"] = "BLOCKED"
                impl["blocked_reason"] = "UPSTREAM_BREAKING_CHANGE"
                store.touch(impl)
        calc.recompute_coverage(consumer)
        store.touch(consumer)

    # Hop 4 -- fires because hop 3 changed those implementations' status.
    seen_teams = []
    for consumer in affected_consumers:
        team = store.teams.get(consumer["owning_team_id"])
        if team is not None and team["id"] not in seen_teams:
            seen_teams.append(team["id"])
            calc.recompute_team_blocked_impls(team)
            store.touch(team)
