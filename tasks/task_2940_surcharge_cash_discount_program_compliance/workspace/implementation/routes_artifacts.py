"""Disclosure artifacts and program readiness."""

from flask import Blueprint

import auth
import calc
import listing
import serialize
import validation as v
from auth import authorize, check_merchant_ownership
from envelope import created, ok
from errors import ApiError
from store import db, base_row, touch
from validation import as_enum, as_instant, as_string, parse_body

bp = Blueprint("artifacts", __name__)

ARTIFACT_TYPES = ("ENTRY_SIGNAGE", "POS_SIGNAGE", "RECEIPT_TEMPLATE", "PRICE_LIST_POSTING")
ARTIFACT_STATES = ("DRAFT", "ATTESTED", "EXPIRED")


@bp.post("/surcharge-programs/<program_id>/disclosure-artifacts")
def draft_artifact(program_id):
    actor = authorize(["MerchantOperator"])
    program = auth.get_program(program_id)
    check_merchant_ownership(actor, program["merchant_id"])
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["artifact_type", "content_hash"])
    artifact_type = as_enum(body["artifact_type"], "artifact_type", ARTIFACT_TYPES)
    content_hash = as_string(body["content_hash"], "content_hash", 64, 64)
    if not v.HEX64.match(content_hash):
        raise v.bad("content_hash must be exactly 64 lowercase hexadecimal characters.")

    row = base_row()
    row.update({
        "program_id": program["id"],
        "artifact_type": artifact_type,
        "content_hash": content_hash,
        "state": "DRAFT",
        "effective_from": None,
        "expires_at": None,
        "attested_by_user_id": None,
        "attested_at": None,
        "expired_reason": "NONE",
    })
    db.artifacts[row["id"]] = row
    return created(serialize.artifact(row))


@bp.post("/disclosure-artifacts/<artifact_id>/attest")
def attest_artifact(artifact_id):
    actor = authorize(["ComplianceOfficer"])
    art = auth.get_artifact(artifact_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["effective_from", "expires_at"])
    effective_from = as_instant(body["effective_from"], "effective_from")
    expires_at = as_instant(body["expires_at"], "expires_at")
    if expires_at <= effective_from:
        raise v.bad("expires_at must be strictly after effective_from.")

    if art["state"] != "DRAFT":
        raise ApiError("ERR_INVALID_ARTIFACT_STATE",
                       "Only a DRAFT artifact can be attested.")

    # Step 27: half-open windows, so exact adjacency is admitted.
    for peer in calc.program_artifacts(art["program_id"]):
        if peer["id"] == art["id"] or peer["state"] != "ATTESTED":
            continue
        if peer["artifact_type"] != art["artifact_type"]:
            continue
        if effective_from < peer["expires_at"] and peer["effective_from"] < expires_at:
            raise ApiError("ERR_DISCLOSURE_WINDOW_OVERLAP",
                           "The requested window intersects an attested window of the same artifact type.")

    art["state"] = "ATTESTED"
    art["effective_from"] = effective_from
    art["expires_at"] = expires_at
    art["attested_at"] = db.now()
    art["attested_by_user_id"] = actor.user_id
    touch(art)

    program = db.programs.get(art["program_id"])
    if program is not None:
        calc.recompute_disclosure_ready(program)
        touch(program)

    return ok(serialize.artifact(art))


@bp.get("/disclosure-artifacts/<artifact_id>")
def read_artifact(artifact_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.artifact(auth.get_artifact(artifact_id)))


@bp.get("/disclosure-artifacts")
def list_artifacts():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.artifacts.values()), [
        (listing.arg("program_id"), "program_id"),
        (listing.enum_arg("artifact_type", ARTIFACT_TYPES), "artifact_type"),
        (listing.enum_arg("state", ARTIFACT_STATES), "state"),
    ])
    return listing.list_response(rows, serialize.artifact)
