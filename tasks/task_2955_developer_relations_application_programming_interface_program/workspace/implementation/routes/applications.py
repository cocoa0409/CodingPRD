"""Access applications: drafting, submission, review rounds and decisions."""
from flask import Blueprint

from constants import (
    APPLICATION_STATES,
    DRAFT_JUSTIFICATION_FLOOR,
    MAX_REVISION_ROUNDS,
    ROLE_DEVELOPER,
    ROLE_DEVREL_MANAGER,
    ROLE_PLATFORM_ADMIN,
    TIER_DATA_ACCESS_LIMIT,
    TIER_JUSTIFICATION_FLOOR,
    TIER_RANK,
    TIERS,
)
from db import new_id, store
from errors import ApiError, invalid
from middleware import (
    acting_user,
    endpoint,
    lookup,
    require_not_revoked,
    require_owner,
)
from response import array_response, enum_filter, object_response, pagination, string_filter
from serializers import access_application_out
from services.common import (
    catalog_scopes,
    product_of_version,
    require_good_standing,
    require_scope_sensitivity_permitted,
    require_tos_current,
    require_version_grantable,
    scope_sensitivity,
)
from validation import body

bp = Blueprint("applications", __name__)

LIVE_APPLICATION_STATES = ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED"]


def _application(application_id):
    return lookup(
        store.access_applications, application_id, "ERR_ACCESS_APPLICATION_NOT_FOUND"
    )


@bp.post("/access-applications")
@endpoint([ROLE_DEVELOPER])
def create_application():
    payload = body()
    developer_id = payload.string("developer_id", min_len=1)
    version_id = payload.string("target_api_version_id", min_len=1)
    requested_tier = payload.string("requested_tier", choices=TIERS)
    scopes = payload.string_array(
        "requested_scopes", min_items=1, max_items=20, unique=True
    )
    monthly_calls = payload.integer("requested_monthly_calls", minimum=1)
    justification = payload.string("justification_text", required=False)

    # rung 7 -- body foreign keys resolve in declaration order
    developer = lookup(store.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")
    version = lookup(store.api_versions, version_id, "ERR_API_VERSION_NOT_FOUND")
    product = product_of_version(version)

    # the catalogue is the only set of scopes an application may name
    permitted = catalog_scopes(product)
    for scope in scopes:
        if scope not in permitted:
            invalid("Scope %s is not in the product's scope_catalog." % scope)

    # a mandatory draft justification is a shape rule, not the tier floor
    sensitive = any(
        scope_sensitivity(product, scope) != "PUBLIC" for scope in scopes
    )
    if requested_tier in ("PARTNER", "PRIVILEGED") or sensitive:
        if justification is None or len(justification) < DRAFT_JUSTIFICATION_FLOOR:
            invalid(
                "justification_text is mandatory here and must be at least %d characters."
                % DRAFT_JUSTIFICATION_FLOOR
            )

    require_owner(developer["id"])
    require_not_revoked()

    require_scope_sensitivity_permitted(product, scopes, requested_tier)

    for existing in store.access_applications.values():
        if (
            existing["developer_id"] == developer["id"]
            and existing["target_api_version_id"] == version["id"]
            and existing["state"] in LIVE_APPLICATION_STATES
        ):
            raise ApiError(
                "ERR_DUPLICATE_APPLICATION",
                "This developer already holds a live application for that version.",
            )

    application = {
        "id": new_id(),
        "developer_id": developer["id"],
        "target_api_version_id": version["id"],
        "requested_tier": requested_tier,
        "requested_scopes": list(scopes),
        "requested_monthly_calls": monthly_calls,
        "justification_text": justification,
        "state": "DRAFT",
        "revision_round": 0,
        "reviewer_user_id": None,
        "approver_user_id": None,
        "approved_tier": None,
        "granted_scopes": None,
        "data_access_limit": None,
        "changes_requested_note": None,
        "decision_reason": None,
        "decided_at": None,
    }
    store.stamp_new(application)
    store.access_applications[application["id"]] = application
    return object_response(access_application_out(application), 201)


@bp.get("/access-applications/<application_id>")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def read_application(application_id):
    application = _application(application_id)
    require_owner(application["developer_id"])
    return object_response(access_application_out(application))


@bp.get("/access-applications")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def list_applications():
    limit, offset = pagination()
    developer_id = string_filter("developer_id")
    version_id = string_filter("target_api_version_id")
    state = enum_filter("state", APPLICATION_STATES)

    records = store.ordered(store.access_applications)
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if version_id is not None:
        records = [r for r in records if r["target_api_version_id"] == version_id]
    if state is not None:
        records = [r for r in records if r["state"] == state]

    total = len(records)
    page = records[offset : offset + limit]
    return array_response(
        [access_application_out(r) for r in page], total, limit, offset
    )


@bp.post("/access-applications/<application_id>/submit")
@endpoint([ROLE_DEVELOPER])
def submit_application(application_id):
    payload = body()
    revised = payload.string("justification_text", required=False)

    application = _application(application_id)
    require_owner(application["developer_id"])

    if application["state"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "An application in %s cannot be submitted." % application["state"],
        )

    developer = store.developers[application["developer_id"]]
    version = store.api_versions[application["target_api_version_id"]]
    product = product_of_version(version)

    require_good_standing(developer)
    require_not_revoked()
    require_tos_current(developer, product)

    justification = revised if revised is not None else application["justification_text"]
    floor = TIER_JUSTIFICATION_FLOOR[application["requested_tier"]]
    if len(justification or "") < floor:
        raise ApiError(
            "ERR_JUSTIFICATION_INSUFFICIENT",
            "Tier %s requires a justification of at least %d characters."
            % (application["requested_tier"], floor),
        )

    require_version_grantable(version, application["requested_tier"])

    if application["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED",
            "This application has already used its %d revision rounds."
            % MAX_REVISION_ROUNDS,
        )

    if revised is not None:
        application["justification_text"] = revised
    application["state"] = "SUBMITTED"
    application["revision_round"] += 1
    application["changes_requested_note"] = None
    store.touch(application)
    return object_response(access_application_out(application))


@bp.post("/access-applications/<application_id>/claim-review")
@endpoint([ROLE_DEVREL_MANAGER])
def claim_review(application_id):
    body()
    application = _application(application_id)
    if application["state"] != "SUBMITTED":
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "Only a SUBMITTED application may be claimed; state is %s."
            % application["state"],
        )
    application["state"] = "UNDER_REVIEW"
    application["reviewer_user_id"] = acting_user()
    store.touch(application)
    return object_response(access_application_out(application))


@bp.post("/access-applications/<application_id>/request-changes")
@endpoint([ROLE_DEVREL_MANAGER])
def request_changes(application_id):
    payload = body()
    note = payload.string("changes_requested_note", min_len=1)

    application = _application(application_id)

    if application["state"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "Only an UNDER_REVIEW application may be sent back; state is %s."
            % application["state"],
        )
    if (
        application["reviewer_user_id"] is not None
        and application["reviewer_user_id"] != acting_user()
    ):
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Only the claiming reviewer may request changes.",
        )
    if application["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED",
            "This application has already used its %d revision rounds."
            % MAX_REVISION_ROUNDS,
        )

    application["state"] = "CHANGES_REQUESTED"
    application["changes_requested_note"] = note
    store.touch(application)
    return object_response(access_application_out(application))


@bp.post("/access-applications/<application_id>/decide")
@endpoint([ROLE_PLATFORM_ADMIN])
def decide_application(application_id):
    payload = body()
    decision = payload.string("decision", choices=["APPROVE", "REJECT"])
    approving = decision == "APPROVE"
    approved_tier = payload.string(
        "approved_tier", required=approving, choices=TIERS
    )
    granted_scopes = payload.string_array(
        "granted_scopes",
        required=approving,
        min_items=1 if approving else None,
        max_items=20,
        unique=True,
    )
    reason = payload.string("decision_reason", required=False)

    application = _application(application_id)

    revision_exhausted = (
        application["state"] == "CHANGES_REQUESTED"
        and application["revision_round"] >= MAX_REVISION_ROUNDS
    )
    if approving:
        if application["state"] != "UNDER_REVIEW":
            raise ApiError(
                "ERR_APPLICATION_STATE_INVALID",
                "Only an UNDER_REVIEW application may be approved; state is %s."
                % application["state"],
            )
    elif application["state"] != "UNDER_REVIEW" and not revision_exhausted:
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "An application in %s cannot be rejected." % application["state"],
        )

    version = store.api_versions[application["target_api_version_id"]]
    product = product_of_version(version)

    if approving:
        require_scope_sensitivity_permitted(product, granted_scopes, approved_tier)

    if (
        application["reviewer_user_id"] is not None
        and application["reviewer_user_id"] == acting_user()
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The deciding operator may not be the recorded reviewer.",
        )

    if approving:
        if TIER_RANK[approved_tier] > TIER_RANK[application["requested_tier"]]:
            raise ApiError(
                "ERR_TIER_ESCALATION_NOT_PERMITTED",
                "approved_tier may not outrank the requested tier.",
            )
        permitted = set(catalog_scopes(product))
        requested = set(application["requested_scopes"])
        for scope in granted_scopes:
            if scope not in requested or scope not in permitted:
                raise ApiError(
                    "ERR_TIER_ESCALATION_NOT_PERMITTED",
                    "granted_scopes must be a subset of the requested scopes and "
                    "of the product's scope_catalog.",
                )

        application["state"] = "APPROVED"
        application["approver_user_id"] = acting_user()
        application["approved_tier"] = approved_tier
        application["granted_scopes"] = list(granted_scopes)
        application["data_access_limit"] = TIER_DATA_ACCESS_LIMIT[approved_tier]
        if reason is not None:
            application["decision_reason"] = reason
        application["decided_at"] = store.now()
    else:
        application["state"] = "REJECTED"
        if revision_exhausted:
            application["decision_reason"] = "REVISION_LIMIT_EXHAUSTED"
        else:
            application["decision_reason"] = reason
        application["decided_at"] = store.now()

    store.touch(application)
    return object_response(access_application_out(application))
