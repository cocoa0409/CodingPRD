"""Brigading cluster routes (§3.5)."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member
from services import community as community_svc
from services import content

bp = Blueprint("brigades", __name__)

CLUSTER_STATUSES = ("DETECTED", "ESCALATED", "DISMISSED")


@bp.post("/api/communities/<community_id>/brigade-clusters")
def create_cluster(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    community_svc.guard_mutable(community)

    R.as_int(data, "internal_link_count", low=0)
    R.as_int(data, "external_link_count", low=0)
    R.as_int(data, "participant_count", low=1)
    R.as_int(data, "legitimate_participant_count", low=0)
    cluster = content.create_cluster(community, data)
    return R.ok(R.to_json(cluster), status=201)


@bp.get("/api/communities/<community_id>/brigade-clusters")
def list_clusters(community_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("BrigadingCluster", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, CLUSTER_STATUSES)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/brigade-clusters/<cluster_id>")
def get_cluster(community_id, cluster_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    cluster = db.find("BrigadingCluster", cluster_id)
    if cluster is None or cluster["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return R.ok(R.to_json(cluster))


@bp.post("/api/communities/<community_id>/brigade-clusters/<cluster_id>/dismiss")
def dismiss_cluster(community_id, cluster_id):
    require_roles("Moderator", "PlatformAdmin")
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    cluster = db.find("BrigadingCluster", cluster_id)
    if cluster is None or cluster["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    cluster = content.dismiss_cluster(community, cluster)
    return R.ok(R.to_json(cluster))