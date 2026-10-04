"""Device clusters, their member links and stabilization."""

from flask import Blueprint, request

from db import STORE, add_days, now
from errors import ApiError, ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND
from middleware import (assert_version_matches, body, new_id, require_version, route,
                        stamp, touch)
from response import created, read_pagination, success, success_list
from serializers import cluster as serialize_cluster
from serializers import link as serialize_link
from calculations import recompute_cluster_aggregate, resolve_cluster_for_account
from services import common

bp = Blueprint("clusters", __name__)

_READ_ROLES = ("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead")


def get_cluster(cluster_id):
    cluster = STORE.clusters.get(cluster_id)
    if cluster is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such device cluster: %s" % cluster_id)
    return cluster


@bp.route("/safety/device-clusters", methods=["POST"])
@route("PlatformAdmin")
def create_cluster(ident):
    payload = body()
    cluster = {
        "id": new_id(),
        "cluster_key": payload.get("cluster_key"),
        "region_code": payload.get("region_code"),
        # Any aggregate supplied by the client is ignored; it is always derived.
        "aggregate_cluster_risk": 0,
        "clustered_actor_incident_count": 0,
        "cluster_risk_generation_index": 1,
        "status": "OPEN",
    }
    stamp(cluster)
    STORE.clusters[cluster["id"]] = cluster
    return created(serialize_cluster(cluster))


@bp.route("/safety/device-clusters", methods=["GET"])
@route(*_READ_ROLES)
def list_clusters(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.clusters.values())

    def keep(cluster):
        for field in ("region_code", "status"):
            wanted = request.args.get(field)
            if wanted is not None and cluster.get(field) != wanted:
                return False
        return True

    items = [c for c in items if keep(c)]
    items.sort(key=lambda c: (c.get("created_at"), c.get("id") or ""))
    return success_list([serialize_cluster(c) for c in items], limit, offset)


@bp.route("/safety/device-clusters/<cluster_id>", methods=["GET"])
@route(*_READ_ROLES)
def get_one_cluster(ident, cluster_id):
    return success(serialize_cluster(get_cluster(cluster_id)))


@bp.route("/safety/device-clusters/<cluster_id>/account-device-links", methods=["GET"])
@route(*_READ_ROLES)
def list_cluster_links(ident, cluster_id):
    get_cluster(cluster_id)
    limit, offset = read_pagination(request.args)
    items = STORE.cluster_links(cluster_id)
    wanted = request.args.get("link_status")
    if wanted is not None:
        items = [l for l in items if l.get("link_status") == wanted]
    items.sort(key=lambda l: (l.get("created_at"), l.get("id") or ""))
    return success_list([serialize_link(l) for l in items], limit, offset)


@bp.route("/safety/clusters/<cluster_id>/stabilize", methods=["POST"])
@route("SafetyOperationsLead")
def stabilize(ident, cluster_id):
    cluster = get_cluster(cluster_id)
    payload = body()
    require_version(payload, "expected_cluster_version")
    assert_version_matches(payload, "expected_cluster_version", cluster,
                           "DeviceCluster")

    if cluster.get("status") != "WATCHLIST":
        raise ApiError(*ERR_INVALID_STATE,
                       message="Stabilization is not declared from %s."
                               % cluster.get("status"))

    incident_free_at = _incident_free_instant(cluster)
    if incident_free_at is not None and now() < add_days(incident_free_at, 180):
        raise ApiError(*ERR_INVALID_STATE,
                       message="The cluster has not been incident-free for 180 days.")

    region = cluster.get("region_code")
    policy = common.policy_for_region(region)
    if (cluster.get("aggregate_cluster_risk") or 0) >= float(
            policy.get("cluster_purge_threshold", 2400)):
        raise ApiError(*ERR_INVALID_STATE,
                       message="The cluster's aggregate risk is at or above the purge "
                               "threshold.")

    cluster["status"] = "OPEN"
    for link in STORE.cluster_links(cluster_id):
        if link.get("link_status") == "SEVERED":
            link["link_status"] = "LINKED"
            touch(link)
    recompute_cluster_aggregate(cluster)
    cluster["cluster_risk_generation_index"] = int(policy.get("knob_generation_index", 1))
    touch(cluster)
    return success(serialize_cluster(cluster))


def _incident_free_instant(cluster):
    """The newest clustered S3/S4 incident's created_at, or None."""
    member_ids = set(STORE.cluster_member_accounts(cluster.get("id")))
    newest = None
    for incident in STORE.incidents.values():
        if incident.get("account_id") not in member_ids:
            continue
        if incident.get("severity") not in ("S3", "S4"):
            continue
        created = incident.get("created_at")
        if created is not None and (newest is None or created > newest):
            newest = created
    return newest