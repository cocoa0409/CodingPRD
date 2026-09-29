"""Releases, semantic versioning and the breaking-change policy (PRD 3.7)."""

from flask import Blueprint

import calc
import errors
from auth import SYSTEM_ADMIN, require_roles
from entities import get_release, release_json
from errors import fail
from responses import created, ok
from store import sort_created_asc, store
from validation import body, opt_enum, req_semver

bp = Blueprint("releases", __name__, url_prefix="/design-system")

CHANNELS = ("STABLE", "NEXT")


@bp.post("/releases")
@require_roles(SYSTEM_ADMIN)
def cut_release():
    payload = body()
    semver_base = req_semver(payload, "semver_base")
    channel = opt_enum(payload, "channel", CHANNELS, "STABLE")

    row = store.new_row()
    row.update({
        "semver_base": semver_base,
        "channel": channel,
        "state": "DRAFT",
        "semver": None,
        "policy_tier": None,
        "breaking_ratio": None,
        "breaking_change_count": 0,
        "escalated_proposal_count": 0,
        "release_notes_state": "PENDING",
        "published_at": None,
    })
    store.releases[row["id"]] = row
    return created(release_json(row))


@bp.post("/releases/<release_id>/publish")
@require_roles(SYSTEM_ADMIN)
def publish_release(release_id):
    release = get_release(release_id)

    if release["state"] != "DRAFT":
        fail(errors.ERR_INVALID_RELEASE_STATE,
             "Only a DRAFT release can be published.")

    carried = sort_created_asc([p for p in store.proposals.values()
                                if p["released_in_release_id"] == release["id"]
                                and p["state"] == "ACCEPTED"])
    if not carried:
        fail(errors.ERR_INVALID_RELEASE_STATE,
             "An empty release has nothing to version.")

    raw, effective, ratio, tier, breaking_count, escalated, semver = \
        calc.release_version_bump(release, carried)

    for prop in carried:
        if effective[prop["id"]] == "MAJOR" and \
                "MIGRATION_GUIDE" not in prop["submitted_evidence_kinds"]:
            fail(errors.ERR_MIGRATION_GUIDE_REQUIRED,
                 "A proposal effectively MAJOR at publish time needs a migration guide.")

    for prop in carried:
        prop["raw_change_class"] = raw[prop["id"]]
        prop["effective_change_class"] = effective[prop["id"]]
        store.touch(prop)

    release["semver"] = semver
    release["policy_tier"] = tier
    release["breaking_ratio"] = ratio
    release["breaking_change_count"] = breaking_count
    release["escalated_proposal_count"] = escalated
    release["state"] = "PUBLISHED"
    release["release_notes_state"] = "PUBLISHED"
    release["published_at"] = store.now_iso
    store.touch(release)

    reset_ids = []
    for prop in carried:
        if prop["proposal_kind"] != "BREAKING_CHANGE":
            continue
        component = store.components.get(prop["target_component_id"])
        if component is None or component["id"] in reset_ids:
            continue
        reset_ids.append(component["id"])
        component["pending_breaking_change_count"] = 0
        store.touch(component, bump=False)

    return ok(release_json(release))
