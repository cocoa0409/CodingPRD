"""Account-device links and the dormancy sweep."""

from flask import Blueprint, request

from db import STORE, add_days, now
from errors import ApiError, ERR_CLUSTER_BANNED, ERR_CROSS_REGION_REFERENCE, ERR_RESOURCE_NOT_FOUND
from middleware import body, new_id, route, stamp, touch
from response import created, read_pagination, success, success_list
from serializers import link as serialize_link
from calculations import recompute_cluster_aggregate
from services import common

bp = Blueprint("links", __name__)

_READ_ROLES = ("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead")


@bp.route("/safety/account-device-links", methods=["POST"])
@route("SafetyInvestigator")
def create_link(ident):
    payload = body()
    account = STORE.accounts.get(payload.get("account_id"))
    if account is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such account: %s" % payload.get("account_id"))
    cluster = STORE.clusters.get(payload.get("device_cluster_id"))
    if cluster is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such device cluster: %s" % payload.get("device_cluster_id"))

    # A link may only be recorded against a cluster that is OPEN or WATCHLIST;
    # a BANNED cluster rejects the write before any row is stored.
    if cluster.get("status") == "BANNED":
        raise ApiError(*ERR_CLUSTER_BANNED,
                       message="The target device cluster is banned.")

    if cluster.get("region_code") != account.get("home_region_code"):
        raise ApiError(*ERR_CROSS_REGION_REFERENCE,
                       message="The device cluster belongs to a different operating region.")

    instant = now()
    link = {
        "id": new_id(),
        "account_id": account.get("id"),
        "device_cluster_id": cluster.get("id"),
        "fingerprint_hash": payload.get("fingerprint_hash"),
        "first_seen_at": instant,
        "last_seen_at": instant,
        "link_status": "LINKED",
    }
    stamp(link)
    STORE.links[link["id"]] = link

    recompute_cluster_aggregate(cluster)
    common.refresh_account(account)
    return created(serialize_link(link))


@bp.route("/safety/account-device-links", methods=["GET"])
@route(*_READ_ROLES)
def list_links(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.links.values())

    def keep(link):
        for field in ("account_id", "device_cluster_id"):
            wanted = request.args.get(field)
            if wanted is not None and link.get(field) != wanted:
                return False
        return True

    items = [l for l in items if keep(l)]
    items.sort(key=lambda l: (l.get("created_at"), l.get("id") or ""))
    return success_list([serialize_link(l) for l in items], limit, offset)


@bp.route("/safety/account-device-links/<link_id>", methods=["GET"])
@route(*_READ_ROLES)
def get_one_link(ident, link_id):
    link = STORE.links.get(link_id)
    if link is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such account-device link: %s" % link_id)
    return success(serialize_link(link))


@bp.route("/safety/account-device-links/dormancy-sweep", methods=["POST"])
@route("PlatformAdmin")
def dormancy_sweep(ident):
    instant = now()
    affected = set()
    for link in STORE.links.values():
        last_seen = link.get("last_seen_at")
        if last_seen is None:
            continue
        status = link.get("link_status")
        if status == "LINKED" and instant >= add_days(last_seen, 180):
            link["link_status"] = "DORMANT"
            touch(link)
            affected.add(link.get("device_cluster_id"))
        elif status == "DORMANT" and instant >= add_days(last_seen, 365):
            link["link_status"] = "SEVERED"
            touch(link)
            affected.add(link.get("device_cluster_id"))
    for cluster_id in affected:
        cluster = STORE.clusters.get(cluster_id)
        if cluster is not None:
            recompute_cluster_aggregate(cluster)
    return success({})