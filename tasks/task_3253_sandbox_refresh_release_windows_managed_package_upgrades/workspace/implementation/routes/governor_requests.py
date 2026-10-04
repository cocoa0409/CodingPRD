"""Governor-limit request routes (PRD §4)."""

from flask import Blueprint

import middleware
import response
from services import common, governor

bp = Blueprint("governor_requests", __name__)


@bp.post("/platform/governor-limit-requests/<request_id>/submit")
def submit(request_id):
    actor = middleware.require("AppDeveloper")
    row = common.get_governor_request(request_id)
    row = governor.submit_request(actor, row)
    return response.ok(_ser(row))


@bp.post("/platform/governor-limit-requests/<request_id>/approve")
def approve(request_id):
    actor = middleware.require("PlatformAdmin")
    row = common.get_governor_request(request_id)
    row = governor.approve_request(actor, row)
    return response.ok(_ser(row))


@bp.post("/platform/governor-limit-requests/<request_id>/reject")
def reject(request_id):
    actor = middleware.require("PlatformAdmin")
    row = common.get_governor_request(request_id)
    row = governor.reject_request(actor, row)
    return response.ok(_ser(row))


@bp.post("/platform/governor-limit-requests/<request_id>/reopen")
def reopen(request_id):
    actor = middleware.require("AppDeveloper")
    row = common.get_governor_request(request_id)
    row = governor.reopen_request(actor, row)
    return response.ok(_ser(row))


def _ser(row):
    from serializers import governor_request

    return governor_request(row)