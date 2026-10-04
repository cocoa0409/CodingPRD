"""Non-audit services: prohibited-service flagging, fee pool and pre-approval."""

from core import constants as C
from core.clock import now as clock_now
from core.db import all_rows, new_row, store, touch
from core.errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NAF_CAP_EXCEEDED,
    ERR_PROHIBITED_SERVICE,
    ApiError,
)
from services import calc
from services.independence import (
    commit_client,
    commit_engagement,
    recompute_client,
    recompute_engagement,
)


def is_prohibited_for(client, service_category):
    if not client or not client.get("is_public_interest_entity"):
        return False
    return service_category in C.PROHIBITED_CATEGORIES


def create_service_row(client_id, engagement_id, service_category, fee_cents,
                       committee_resolution_ref, approval_expires_on):
    client = store.clients.get(client_id)
    return new_row("services", {
        "client_id": client_id,
        "engagement_id": engagement_id,
        "service_category": service_category,
        "fee_cents": int(fee_cents),
        "is_prohibited_for_pie": is_prohibited_for(client, service_category),
        "committee_resolution_ref": committee_resolution_ref,
        "approval_expires_on": approval_expires_on,
        "approved_fee_cents": None,
        "approved_on": None,
        "status": "DRAFT",
    })


def recompute_naf_pool(client):
    client["naf_approved_fee_cents"] = calc.naf_fee_pool(client.get("id"), all_rows("services"))


def _cap_check(service, client):
    candidate = calc.rounded_candidate_fee(service.get("fee_cents"))
    pool = calc.naf_fee_pool(client.get("id"), all_rows("services"))
    cap = int(client.get("naf_annual_cap_cents") or 0)
    if candidate + pool > cap:
        raise ApiError(ERR_NAF_CAP_EXCEEDED,
                       "The rounded fee would push the approved pool above the annual cap.")


def _recompute_client_scope(client_id, engagement_id=None, force_client=False):
    if engagement_id:
        engagement = store.engagements.get(engagement_id)
        if engagement is not None:
            recompute_engagement(engagement)
            commit_engagement(engagement)
    else:
        for engagement in all_rows("engagements"):
            if engagement.get("client_id") == client_id:
                recompute_engagement(engagement)
                commit_engagement(engagement)
    client = store.clients.get(client_id)
    if client is not None:
        recompute_client(client)
        commit_client(client, force=force_client)


def apply_service_action(service, action, payload, now=None):
    now = now or clock_now()
    status = service.get("status")
    client = store.clients.get(service.get("client_id"))
    if action == "SUBMIT_FOR_APPROVAL":
        if status != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "SUBMIT_FOR_APPROVAL requires a DRAFT service.")
        if service.get("is_prohibited_for_pie") is True:
            raise ApiError(ERR_PROHIBITED_SERVICE,
                           "A service prohibited for a public interest entity may not leave DRAFT.")
        if int(service.get("fee_cents") or 0) <= 0:
            raise ApiError(ERR_INVALID_STATE, "SUBMIT_FOR_APPROVAL requires a positive fee.")
        _cap_check(service, client)
        service["status"] = "PENDING_APPROVAL"
    elif action == "APPROVE":
        if status != "PENDING_APPROVAL":
            raise ApiError(ERR_INVALID_STATE, "APPROVE requires a service in PENDING_APPROVAL.")
        reference = payload.get("committee_resolution_ref") or service.get("committee_resolution_ref")
        if not reference:
            raise ApiError(ERR_INVALID_REQUEST,
                           "Field 'committee_resolution_ref' is required to approve a service.")
        _cap_check(service, client)
        service["committee_resolution_ref"] = reference
        service["approved_fee_cents"] = calc.rounded_candidate_fee(service.get("fee_cents"))
        service["approved_on"] = now
        service["status"] = "APPROVED"
        recompute_naf_pool(client)
        _recompute_client_scope(service.get("client_id"), force_client=True)
    elif action == "REJECT":
        if status not in ("DRAFT", "PENDING_APPROVAL"):
            raise ApiError(ERR_INVALID_STATE, "REJECT requires a DRAFT or PENDING_APPROVAL service.")
        was_pending = status == "PENDING_APPROVAL"
        service["status"] = "REJECTED"
        if was_pending and service.get("engagement_id"):
            _recompute_client_scope(service.get("client_id"), service.get("engagement_id"))
        else:
            _recompute_client_scope(service.get("client_id"))
    elif action == "RETURN_TO_DRAFT":
        if status != "REJECTED":
            raise ApiError(ERR_INVALID_STATE, "RETURN_TO_DRAFT requires a REJECTED service.")
        service["status"] = "DRAFT"
    elif action == "REVOKE":
        if status != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "REVOKE requires an APPROVED service.")
        service["status"] = "REVOKED"
        service["approved_fee_cents"] = None
        service["approved_on"] = None
        recompute_naf_pool(client)
        _recompute_client_scope(service.get("client_id"), force_client=True)
    else:
        raise ApiError(ERR_INVALID_STATE, "Unknown action '%s' for a non-audit service." % action)
    touch(service)
    return service
