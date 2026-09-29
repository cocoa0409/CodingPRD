"""Developer registration, onboarding, ecosystem, directory and revocation."""
from flask import Blueprint

from constants import (
    CERTIFICATION_LEVELS,
    CURRENT_DOCS_VERSION,
    DIRECTORY_STATES,
    ONBOARDING_STATES,
    REGION_CODES,
    ROLE_DEVELOPER,
    ROLE_DEVREL_MANAGER,
    ROLE_PARTNER_SUPPORT,
    ROLE_PLATFORM_ADMIN,
    ROLE_TRUST_SAFETY,
    STANDINGS,
    ROLE_ANONYMOUS,
)
from db import new_id, store
from errors import ApiError, invalid
from middleware import acting_user, endpoint, lookup, require_not_revoked, require_owner
from response import array_response, enum_filter, object_response, pagination
from serializers import developer_out
from services import enforcement, trust
from services.common import certification_active, require_good_standing
from validation import body

bp = Blueprint("developers", __name__)


def _developer(developer_id):
    return lookup(store.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")


@bp.post("/developers")
@endpoint([ROLE_ANONYMOUS, ROLE_DEVREL_MANAGER])
def create_developer():
    payload = body()
    org_name = payload.string("org_name", min_len=1, max_len=120)
    contact_email = payload.string("contact_email", min_len=5, max_len=160, contains="@")
    region_code = payload.string("region_code", choices=REGION_CODES)

    developer = {
        "id": new_id(),
        "org_name": org_name,
        "contact_email": contact_email,
        "region_code": region_code,
        "onboarding_state": "REGISTERED",
        "standing": "GOOD_STANDING",
        "directory_state": "NOT_LISTED",
        "directory_summary": None,
        "docs_version_acknowledged": None,
        "tos_version_accepted": None,
        "certification_level": "NONE",
        "certification_expires_at": None,
        "hackathon_award_count": 0,
        "clean_window_count": 0,
        "throttled_window_count": 0,
        "violation_points": 0,
        "trust_score": 50,
        "audited_trust_score": 50,
        "revoked_at": None,
    }
    store.stamp_new(developer)
    store.developers[developer["id"]] = developer
    return object_response(developer_out(developer), 201)


@bp.get("/developers/<developer_id>")
@endpoint(
    [
        ROLE_DEVELOPER,
        ROLE_DEVREL_MANAGER,
        ROLE_PLATFORM_ADMIN,
        ROLE_TRUST_SAFETY,
        ROLE_PARTNER_SUPPORT,
    ]
)
def read_developer(developer_id):
    developer = _developer(developer_id)
    require_owner(developer["id"])
    return object_response(developer_out(developer))


@bp.get("/developers")
@endpoint([ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN, ROLE_TRUST_SAFETY])
def list_developers():
    limit, offset = pagination()
    directory_state = enum_filter("directory_state", DIRECTORY_STATES)
    standing = enum_filter("standing", STANDINGS)
    onboarding_state = enum_filter("onboarding_state", ONBOARDING_STATES)

    records = store.ordered(store.developers)
    if directory_state is not None:
        records = [r for r in records if r["directory_state"] == directory_state]
    if standing is not None:
        records = [r for r in records if r["standing"] == standing]
    if onboarding_state is not None:
        records = [r for r in records if r["onboarding_state"] == onboarding_state]

    total = len(records)
    page = records[offset : offset + limit]
    return array_response([developer_out(r) for r in page], total, limit, offset)


@bp.post("/developers/<developer_id>/onboarding-acknowledgement")
@endpoint([ROLE_DEVELOPER])
def acknowledge_onboarding(developer_id):
    payload = body()
    docs_version = payload.integer("docs_version", minimum=1)
    tos_version = payload.integer("tos_version", minimum=1)

    developer = _developer(developer_id)

    recorded = developer["docs_version_acknowledged"]
    if developer["onboarding_state"] == "REGISTERED" or recorded is None:
        if docs_version != CURRENT_DOCS_VERSION:
            invalid(
                "docs_version must equal the current documentation revision %d."
                % CURRENT_DOCS_VERSION
            )
    elif docs_version <= recorded:
        invalid(
            "docs_version must be strictly greater than the acknowledged revision %d."
            % recorded
        )

    if not any(
        product["required_tos_version"] == tos_version
        for product in store.api_products.values()
    ):
        invalid("tos_version must match the required_tos_version of a product.")

    require_owner(developer["id"])
    require_not_revoked()

    developer["docs_version_acknowledged"] = docs_version
    developer["tos_version_accepted"] = tos_version
    if developer["onboarding_state"] == "REGISTERED":
        developer["onboarding_state"] = "DOCS_ACKNOWLEDGED"
    trust.refresh_snapshot(developer)
    store.touch(developer)
    return object_response(developer_out(developer))


@bp.post("/developers/<developer_id>/ecosystem-participations")
@endpoint([ROLE_DEVREL_MANAGER])
def record_ecosystem_participation(developer_id):
    payload = body()
    level = payload.string("certification_level", choices=CERTIFICATION_LEVELS)
    expires_at = payload.instant("certification_expires_at")
    delta = payload.integer("hackathon_awards_delta", required=False, minimum=0)

    developer = _developer(developer_id)

    if expires_at <= store.now():
        raise ApiError(
            "ERR_CERTIFICATION_EXPIRED",
            "certification_expires_at must be strictly after the logical clock.",
        )

    developer["certification_level"] = level
    developer["certification_expires_at"] = expires_at
    if delta is not None:
        developer["hackathon_award_count"] += delta
    trust.refresh_snapshot(developer)
    store.touch(developer)
    return object_response(developer_out(developer))


@bp.post("/developers/<developer_id>/directory-submission")
@endpoint([ROLE_DEVELOPER])
def submit_directory_listing(developer_id):
    payload = body()
    summary = payload.string("directory_summary", min_len=20, max_len=400)

    developer = _developer(developer_id)
    require_owner(developer["id"])
    require_good_standing(developer)
    require_not_revoked()

    if developer["onboarding_state"] != "PRODUCTION_ACTIVE":
        raise ApiError(
            "ERR_DIRECTORY_PREREQUISITES_UNMET",
            "onboarding_state must be PRODUCTION_ACTIVE to list in the directory.",
        )
    if developer["certification_level"] == "NONE" or not certification_active(developer):
        raise ApiError(
            "ERR_DIRECTORY_PREREQUISITES_UNMET",
            "An unexpired certification above NONE is required to list in the directory.",
        )

    developer["directory_summary"] = summary
    developer["directory_state"] = "PENDING_REVIEW"
    store.touch(developer)
    return object_response(developer_out(developer))


@bp.post("/developers/<developer_id>/directory-review")
@endpoint([ROLE_DEVREL_MANAGER])
def review_directory_listing(developer_id):
    payload = body()
    decision = payload.string("decision", choices=["APPROVE", "REJECT"])
    payload.string("review_note", required=False)

    developer = _developer(developer_id)

    if developer["directory_state"] != "PENDING_REVIEW":
        raise ApiError(
            "ERR_DIRECTORY_PREREQUISITES_UNMET",
            "directory_state must be PENDING_REVIEW to review a listing.",
        )
    if decision == "APPROVE":
        require_good_standing(developer)
        developer["directory_state"] = "LISTED"
    else:
        developer["directory_state"] = "NOT_LISTED"
        developer["directory_summary"] = None
    store.touch(developer)
    return object_response(developer_out(developer))


@bp.post("/developers/<developer_id>/revoke-access")
@endpoint([ROLE_PLATFORM_ADMIN])
def revoke_access(developer_id):
    payload = body()
    payload.string("revocation_reason", min_len=1)

    developer = _developer(developer_id)

    if developer["standing"] != "RESTRICTED":
        raise ApiError(
            "ERR_DEVELOPER_STANDING_BLOCKED",
            "Only a RESTRICTED developer may be revoked; standing is %s."
            % developer["standing"],
        )
    if not enforcement.revocation_grounds_met(developer):
        raise ApiError(
            "ERR_DEVELOPER_STANDING_BLOCKED",
            "Revocation requires 100 or more violation points or an UPHELD_FINAL case.",
        )
    if enforcement.is_investigator_of_any_case(developer["id"], acting_user()):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The revoking operator investigated one of this developer's cases.",
        )

    developer["standing"] = "REVOKED"
    developer["revoked_at"] = store.now()
    enforcement.revocation_cascade(developer)
    store.touch(developer)
    return object_response(developer_out(developer))
