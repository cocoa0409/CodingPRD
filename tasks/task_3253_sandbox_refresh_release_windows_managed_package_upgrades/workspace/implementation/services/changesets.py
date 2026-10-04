"""Deployment candidates and the deployment pipeline (PRD §3.5).

Creation is guarded by segregation of duties (the source and target must
differ) and by the stale target-environment version.  Validation, approval,
reopen and deployment each apply their own fixed rule sequence, and the pinned
component_digests are what make an approved candidate a fixed reference.
"""

import clock
import db
from errors import (
    ERR_APPROVAL_STALE,
    ERR_CYCLE_DETECTED,
    ERR_EMPTY_COMPONENT_LIST,
    ERR_INVALID_STATE,
    ERR_MISSING_COMPONENT_DEPENDENCY,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    fail,
)
from services import common

VALIDATE_FROM = ("DRAFT", "STALE")


def digests_of(change_set):
    return {
        entry["component"]: entry["version_tag"]
        for entry in change_set.get("component_list", [])
    }


def _missing_dependencies(change_set):
    names = {entry["component"] for entry in change_set.get("component_list", [])}
    for dependency in change_set.get("component_dependencies", []):
        for required in dependency.get("requires", []):
            if required not in names:
                return required
    return None


def _has_cycle(change_set):
    """Cycle test over the dependency graph's `requires` edges."""
    graph = {}
    for dependency in change_set.get("component_dependencies", []):
        graph.setdefault(dependency["component"], set()).update(
            dependency.get("requires", [])
        )

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {}

    def visit(node):
        state = colour.get(node, WHITE)
        if state == GREY:
            return True
        if state == BLACK:
            return False
        colour[node] = GREY
        for target in graph.get(node, ()):
            if visit(target):
                return True
        colour[node] = BLACK
        return False

    for node in list(graph):
        if visit(node):
            return True
    return False


# --- authoring --------------------------------------------------------------

def create_change_set(actor, b):
    from validate import (
        optional_list,
        parse_component_dependencies,
        parse_component_list,
        require_int,
        require_string,
    )

    source_id = require_string(b, "source_environment_id")
    common.get_environment(source_id)
    target_id = require_string(b, "target_environment_id")
    target = common.get_environment(target_id)
    expected = require_int(b, "expected_environment_version")

    component_list = parse_component_list(optional_list(b, "component_list"))
    dependencies = parse_component_dependencies(optional_list(b, "component_dependencies"))

    # 1. Segregation of duties is checked before anything else: promoting
    #    metadata onto the same environment is not a deployment.
    if source_id == target_id:
        fail(
            ERR_SEGREGATION_OF_DUTIES,
            "The source and target environments of a deployment must differ.",
        )

    # 2. The stale target-environment version is the sole other reason.
    if expected != target["version"]:
        fail(
            ERR_STALE_VERSION,
            "expected_environment_version does not match the environment's current version.",
        )

    change_set = db.create(
        db.change_sets,
        {
            "source_environment_id": source_id,
            "target_environment_id": target_id,
            "component_dependencies": dependencies,
            "component_list": component_list,
            "status": "DRAFT",
            "component_digests": {},
            "validated_at": None,
            "approved_at": None,
            "approved_by_user_id": None,
        },
    )
    db.touch(target)
    return change_set


def patch_change_set(actor, change_set, b):
    from validate import parse_component_dependencies, parse_component_list

    if b.has("component_list"):
        change_set["component_list"] = parse_component_list(b.value("component_list"))
    if b.has("component_dependencies"):
        change_set["component_dependencies"] = parse_component_dependencies(
            b.value("component_dependencies")
        )

    # Editing an APPROVED change set invalidates its validity and moves it to
    # STALE, but the pinned digests are retained: PRD §3.5 renders the digest
    # clear as the reopen's compensating move ("clears component_digests to an
    # empty map"), and §2.5 makes the pinned map "the pinned reference for the
    # deployment" that is "not rewritten by the deployment itself".
    if change_set["status"] == "APPROVED":
        change_set["status"] = "STALE"

    db.touch(change_set)
    return change_set


# --- lifecycle --------------------------------------------------------------

def validate_change_set(actor, change_set):
    if change_set["status"] not in VALIDATE_FROM:
        fail(ERR_INVALID_STATE, "The change set is not in DRAFT or STALE.")

    # 1. missing component dependency
    missing = _missing_dependencies(change_set)
    if missing is not None:
        fail(
            ERR_MISSING_COMPONENT_DEPENDENCY,
            "Component '%s' is required but absent from the component list." % missing,
        )

    # 2. cycles in the dependency graph
    if _has_cycle(change_set):
        fail(ERR_CYCLE_DETECTED, "The component dependency graph contains a cycle.")

    # 3. the component list must be non-empty
    if not change_set.get("component_list"):
        fail(ERR_EMPTY_COMPONENT_LIST, "The change set's component list is empty.")

    # 4. the target environment must not already be RELEASED
    target = db.environments.get(change_set["target_environment_id"])
    if target is not None and target["release_status"] == "RELEASED":
        fail(
            ERR_INVALID_STATE,
            "The target environment is RELEASED and cannot accept a deployment.",
        )

    change_set["status"] = "VALIDATED"
    change_set["validated_at"] = clock.default_iso()
    db.touch(change_set)
    return change_set


def approve_change_set(actor, change_set):
    # The state precondition runs ahead of the segregation-of-duties rule.
    if change_set["status"] != "VALIDATED":
        fail(ERR_INVALID_STATE, "The change set is not VALIDATED.")

    source_id = change_set["source_environment_id"]
    recent = [
        cs
        for cs in db.change_sets.values()
        if cs["source_environment_id"] == source_id and cs.get("approved_by_user_id")
    ]
    if recent:
        recent.sort(key=lambda cs: (cs.get("created_at") or "", cs.get("_seq", 0)))
        last_approver = recent[-1]["approved_by_user_id"]
        if last_approver == actor["user_id"]:
            fail(
                ERR_SEGREGATION_OF_DUTIES,
                "The approving operator already acted as the source-side approver.",
            )

    change_set["component_digests"] = digests_of(change_set)
    change_set["approved_at"] = clock.default_iso()
    change_set["approved_by_user_id"] = actor["user_id"]
    change_set["status"] = "APPROVED"
    db.touch(change_set)

    target = db.environments.get(change_set["target_environment_id"])
    if target is not None:
        db.touch(target)
    return change_set


def reopen_change_set(actor, change_set):
    if change_set["status"] != "APPROVED":
        fail(ERR_INVALID_STATE, "The change set is not APPROVED.")

    change_set["status"] = "VALIDATED"
    change_set["component_digests"] = {}
    change_set["approved_at"] = None
    change_set["approved_by_user_id"] = None
    change_set["validated_at"] = clock.default_iso()
    db.touch(change_set)
    return change_set


def deploy_change_set(actor, change_set, b):
    from validate import require_string

    key = require_string(b, "idempotency_key")

    # The state precondition still runs ahead of all three domain rules.
    if change_set["status"] != "APPROVED":
        fail(ERR_INVALID_STATE, "The change set is not APPROVED.")

    # 1. no component named in a dependency entry may be missing.
    missing = _missing_dependencies(change_set)
    if missing is not None:
        fail(
            ERR_MISSING_COMPONENT_DEPENDENCY,
            "Component '%s' is required but absent from the component list." % missing,
        )

    # 2. the pinned digests must still match, and source must differ from target.
    if change_set["component_digests"] != digests_of(change_set) or change_set[
        "source_environment_id"
    ] == change_set["target_environment_id"]:
        fail(
            ERR_APPROVAL_STALE,
            "The approved change set's pinned digests no longer match its components.",
        )

    # 3. the component list must be non-empty.
    if not change_set.get("component_list"):
        fail(ERR_EMPTY_COMPONENT_LIST, "The change set's component list is empty.")

    # A repeated request with the same idempotency_key replays the earlier job.
    for job in db.deployment_jobs.values():
        if job["change_set_id"] == change_set["id"] and job["idempotency_key"] == key:
            return job, False

    job = db.create(
        db.deployment_jobs,
        {
            "change_set_id": change_set["id"],
            "idempotency_key": key,
            "target_environment_id": change_set["target_environment_id"],
            "status": "QUEUED",
            "applied_component_count": 0,
            "validated_digest_match": False,
            "component_digests": dict(change_set["component_digests"]),
        },
    )
    return job, True


def complete_deployment(actor, job):
    # Dispatch out of QUEUED into EXECUTING is performed by the system rather
    # than by a client (PRD §3.5), so a queued job is dispatched when the
    # EnvironmentAdmin addresses it and the completion then applies.
    if job["status"] == "QUEUED":
        _dispatch_deployment_job(job)

    if job["status"] not in ("QUEUED", "EXECUTING"):
        fail(ERR_INVALID_STATE, "The deployment job is not EXECUTING.")

    change_set = db.change_sets.get(job["change_set_id"])
    if change_set is None:
        fail(ERR_INVALID_STATE, "The deployment job's change set no longer exists.")

    if change_set["component_digests"] != digests_of(change_set):
        fail(
            ERR_APPROVAL_STALE,
            "The change set's pinned digests no longer match its components.",
        )

    job["status"] = "SUCCEEDED"
    job["applied_component_count"] = len(change_set.get("component_list", []))
    job["validated_digest_match"] = True
    db.touch(job)

    # HOP 1: the referencing change set moves APPROVED -> DEPLOYED.
    if change_set["status"] == "APPROVED":
        change_set["status"] = "DEPLOYED"
        db.touch(change_set)
    return job


def fail_deployment(actor, job):
    # The system dispatches a queued job into EXECUTING before the terminal
    # fail (PRD §3.5).
    if job["status"] == "QUEUED":
        _dispatch_deployment_job(job)

    if job["status"] != "EXECUTING":
        fail(ERR_INVALID_STATE, "The deployment job is not EXECUTING.")

    job["status"] = "FAILED"
    job["applied_component_count"] = 0
    db.touch(job)
    return job


def _dispatch_deployment_job(job):
    """QUEUED -> EXECUTING, performed by the system (PRD §3.5)."""
    job["status"] = "EXECUTING"
    db.touch(job)