"""Storage pod endpoints (PRD 2.7, 3.9)."""

from flask import Blueprint, request

import auth
import calc
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_POD_UNRECOVERABLE)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import pagination, req_enum, req_int

bp = Blueprint("pods", __name__, url_prefix="/backup-provider")


@bp.route("/storage-pods", methods=["POST"])
def create_pod():
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    body = request.get_json(silent=True) or {}

    region = req_enum(body, "region", K.REGIONS)
    total_shards = req_int(body, "total_shards")
    data_shards = req_int(body, "data_shards")
    failed_shards = req_int(body, "failed_shards", required=False, default=0)

    if total_shards < 1 or data_shards < 1 or data_shards > total_shards:
        raise APIError(ERR_INVALID_REQUEST,
                       "shard geometry must satisfy 1 <= data_shards <= total_shards")
    if failed_shards < 0:
        raise APIError(ERR_INVALID_REQUEST, "failed_shards must not be negative")

    pod = models.storage_pod(store, region, total_shards, data_shards,
                             failed_shards, store.next_pod_seq())
    store.pods[pod["id"]] = pod
    # registration derives parity_shards, reliability_pct and is_reconstructable
    recompute.recompute_pod(store, pod)
    return object_response(models.public(pod), 201)


@bp.route("/storage-pods", methods=["GET"])
def list_pods():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_POD_READ)
    limit, offset = pagination(request.args)

    region = request.args.get("region")
    status = request.args.get("status")
    rows = list(store.pods.values())
    if region:
        rows = [p for p in rows if p["region"] == region]
    if status:
        rows = [p for p in rows if p["status"] == status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(p) for p in page], limit, offset, total)


@bp.route("/storage-pods/<pod_id>", methods=["GET"])
def get_pod(pod_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_POD_READ)
    pod = lookup.pod(lookup.ensure_id(pod_id, "id"))
    return object_response(models.public(pod))


def _apply_failure(store, pod, delta):
    """PRD 3.9: first-match-wins cascade over the instantaneous shard count."""
    if delta < 0:
        raise APIError(ERR_INVALID_REQUEST, "failed_shards_delta must not be negative")
    new_count = int(pod["failed_shards"]) + delta
    if pod["status"] == "HEALTHY" and new_count < 1:
        raise APIError(ERR_INVALID_REQUEST,
                       "failing shards must move the count to at least one")
    pod["failed_shards"] = max(0, new_count)
    recompute.recompute_pod(store, pod)
    return pod


@bp.route("/storage-pods/<pod_id>/shards/fail", methods=["POST"])
def fail_shards(pod_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    pod = lookup.pod(lookup.ensure_id(pod_id, "id"))
    if pod["status"] == "REPAIRING":
        raise APIError(ERR_INVALID_STATE,
                       "a pod under repair does not accept shard failures")

    body = request.get_json(silent=True) or {}
    delta = req_int(body, "failed_shards_delta")
    _apply_failure(store, pod, delta)
    lookup.bump(pod)
    return object_response(models.public(pod))


@bp.route("/storage-pods/<pod_id>/shards/restore", methods=["POST"])
def restore_shards(pod_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    pod = lookup.pod(lookup.ensure_id(pod_id, "id"))

    body = request.get_json(silent=True) or {}
    delta = req_int(body, "failed_shards_delta")
    if delta < 0:
        raise APIError(ERR_INVALID_REQUEST, "failed_shards_delta must not be negative")
    pod["failed_shards"] = max(0, int(pod["failed_shards"]) - delta)
    recompute.recompute_pod(store, pod)
    lookup.bump(pod)
    return object_response(models.public(pod))


@bp.route("/storage-pods/<pod_id>/begin-repair", methods=["POST"])
def begin_repair(pod_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    pod = lookup.pod(lookup.ensure_id(pod_id, "id"))

    if pod["status"] not in ("DEGRADED", "FAILED"):
        raise APIError(ERR_INVALID_STATE,
                       "only a DEGRADED or FAILED pod may begin repair")
    parity = int(pod["total_shards"]) - int(pod["data_shards"])
    if int(pod["failed_shards"]) > parity:
        raise APIError(ERR_POD_UNRECOVERABLE,
                       "failed_shards still exceeds parity_shards")
    pod["status"] = "REPAIRING"
    recompute.recompute_pod(store, pod)
    lookup.bump(pod)
    return object_response(models.public(pod))


@bp.route("/storage-pods/<pod_id>/complete-repair", methods=["POST"])
def complete_repair(pod_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    pod = lookup.pod(lookup.ensure_id(pod_id, "id"))

    if pod["status"] != "REPAIRING":
        raise APIError(ERR_INVALID_STATE, "pod is not REPAIRING")

    pod["status"] = "HEALTHY"
    pod["failed_shards"] = 0
    pod["last_repair_utc"] = models.fmt_ts(store.now())
    recompute.recompute_pod(store, pod)
    lookup.bump(pod)
    return object_response(models.public(pod))