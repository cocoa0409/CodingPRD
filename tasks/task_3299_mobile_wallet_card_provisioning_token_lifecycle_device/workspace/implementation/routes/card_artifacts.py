# =============================================================================
# Card artifacts: create, get, list (global + per-account),
# suspend / resume / deactivate
# =============================================================================
from flask import Blueprint, request

import db
from domain import deactivate_token, suspend_token
from errors import ApiError
from helpers import (
    list_response, new_common_row, resolve_artifact, resolve_card_account,
)
from middleware import get_body, req_str, require_roles
from response import success_object

bp = Blueprint("card_artifacts", __name__)


@bp.post("/card-artifacts")
def create_artifact():
    body = get_body()
    card_account_id = req_str(body, "card_account_id")
    pan_last4 = req_str(body, "pan_last4")
    expiry = req_str(body, "expiry")
    embossing_name = req_str(body, "embossing_name")
    require_roles(["IssuerOperator"])
    resolve_card_account(card_account_id)
    row = new_common_row({
        "card_account_id": card_account_id,
        "pan_last4": pan_last4,
        "expiry": expiry,
        "embossing_name": embossing_name,
        "status": "ACTIVE",
    })
    db.card_artifacts[row["id"]] = row
    return success_object(row, 201)


@bp.get("/card-artifacts/<cardArtifactId>")
def get_artifact(cardArtifactId):
    return success_object(resolve_artifact(cardArtifactId), 200)


@bp.get("/card-artifacts")
def list_artifacts():
    return list_response(db.card_artifacts.values(), filters={
        "card_account_id": request.args.get("card_account_id"),
        "status": request.args.get("status"),
    })


@bp.get("/card-accounts/<cardAccountId>/artifacts")
def list_account_artifacts(cardAccountId):
    resolve_card_account(cardAccountId)
    rows = [a for a in db.card_artifacts.values() if a["card_account_id"] == cardAccountId]
    return list_response(rows)


def _tokens_of_artifact(artifact_id, statuses):
    return [
        t for t in db.payment_tokens.values()
        if t["card_artifact_id"] == artifact_id and t["status"] in statuses
    ]


@bp.post("/card-artifacts/<cardArtifactId>/suspend")
def suspend_artifact(cardArtifactId):
    require_roles(["IssuerOperator"])
    artifact = resolve_artifact(cardArtifactId)
    if artifact["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Artifact cannot be suspended from {artifact['status']}")
    account = db.card_accounts.get(artifact["card_account_id"])
    if account is None or account["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Parent CardAccount must be OPEN")
    artifact["status"] = "SUSPENDED"
    db.touch(artifact)
    for token in _tokens_of_artifact(artifact["id"], {"ACTIVE"}):
        suspend_token(token, "artifact")
    return success_object(artifact, 200)


@bp.post("/card-artifacts/<cardArtifactId>/resume")
def resume_artifact(cardArtifactId):
    require_roles(["IssuerOperator"])
    artifact = resolve_artifact(cardArtifactId)
    if artifact["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Artifact cannot be resumed from {artifact['status']}")
    account = db.card_accounts.get(artifact["card_account_id"])
    if account is None or account["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Parent CardAccount must be OPEN")
    # Does not resume tokens; tokens resume only via their own /resume
    artifact["status"] = "ACTIVE"
    db.touch(artifact)
    return success_object(artifact, 200)


@bp.post("/card-artifacts/<cardArtifactId>/deactivate")
def deactivate_artifact(cardArtifactId):
    require_roles(["IssuerOperator"])
    artifact = resolve_artifact(cardArtifactId)
    if artifact["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE",
                       f"Artifact cannot be deactivated from {artifact['status']}")
    artifact["status"] = "DEACTIVATED"
    db.touch(artifact)
    # Direct deactivation: tokens -> DEACTIVATED with ISSUER_REVOKE
    # (CARD_REISSUE is used only when the cascade arrives via account reissue)
    for token in _tokens_of_artifact(artifact["id"], {"ACTIVE", "SUSPENDED"}):
        deactivate_token(token, "ISSUER_REVOKE")
    return success_object(artifact, 200)
