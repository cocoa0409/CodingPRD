import db
import clock
from util import fmt_iso
from services import nameserver_view, link_view, MIN_NAMESERVER_QPS
from middleware import require_roles, body_json, require_fields, pagination_params
from response import success_object, success_list
from errors import err_invalid_request, err_not_found, ApiError
from flask import Blueprint, request

bp = Blueprint("nameservers", __name__)


@bp.post("/nameservers")
def create_nameserver():
    require_roles("RegistryAdmin")
    data = body_json()
    require_fields(data, ["hostname", "ip_addresses", "capacity_qps"])
    hostname = data["hostname"]
    if not isinstance(hostname, str) or not hostname:
        raise err_invalid_request("hostname must be a non-empty string")
    ips = data["ip_addresses"]
    if not isinstance(ips, list) or len(ips) < 1 or not all(isinstance(x, str) for x in ips):
        raise err_invalid_request("ip_addresses must be a list of at least one string")
    qps = data["capacity_qps"]
    if isinstance(qps, bool) or not isinstance(qps, int) or qps <= 0:
        raise err_invalid_request("capacity_qps must be a positive integer")
    if qps < MIN_NAMESERVER_QPS:
        raise ApiError("ERR_CAPACITY_BELOW_MINIMUM", "capacity_qps below 2000 minimum", 409)
    rec = db.new_common(clock.now())
    rec.update({
        "hostname": hostname,
        "ip_addresses": ips,
        "capacity_qps": qps,
    })
    db.nameservers[rec["id"]] = rec
    return success_object(nameserver_view(rec), 201)


@bp.get("/nameservers")
def list_nameservers():
    require_roles("RegistryAdmin", "RegistrarOperator")
    limit, offset = pagination_params()
    rows = sorted(db.nameservers.values(), key=lambda n: n["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([nameserver_view(n) for n in page], limit, offset, total)


@bp.get("/nameservers/<nid>")
def get_nameserver(nid):
    require_roles("RegistryAdmin", "RegistrarOperator")
    n = db.nameservers.get(nid)
    if n is None:
        raise err_not_found()
    return success_object(nameserver_view(n))


@bp.delete("/nameservers/<nid>")
def delete_nameserver(nid):
    require_roles("RegistryAdmin")
    n = db.nameservers.get(nid)
    if n is None:
        raise err_not_found()
    for l in db.links.values():
        if l["nameserver_id"] == nid:
            d = db.domains.get(l["domain_id"])
            if d is not None and d["status"] != "DELETED":
                raise ApiError("ERR_NAMESERVER_IN_USE",
                               "Nameserver still linked from a non-DELETED domain", 409)
    del db.nameservers[nid]
    return "", 204


@bp.get("/domain-nameserver-links")
def list_links():
    require_roles("RegistryAdmin", "RegistrarOperator", "AbuseAnalyst")
    limit, offset = pagination_params()
    rows = sorted(db.links.values(), key=lambda l: l["created_at"])
    did = request.args.get("domain_id")
    nid = request.args.get("nameserver_id")
    if did:
        rows = [l for l in rows if l["domain_id"] == did]
    if nid:
        rows = [l for l in rows if l["nameserver_id"] == nid]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([link_view(l) for l in page], limit, offset, total)


@bp.get("/domain-nameserver-links/<lid>")
def get_link(lid):
    require_roles("RegistryAdmin", "RegistrarOperator", "AbuseAnalyst")
    l = db.links.get(lid)
    if l is None:
        raise err_not_found()
    return success_object(link_view(l))


@bp.get("/capacity/summary")
def capacity_summary():
    require_roles("RegistryAdmin")
    provisioned = sum(n["capacity_qps"] for n in db.nameservers.values())
    commitment = 8000
    ratio = provisioned / commitment
    return success_object({
        "provisioned_qps": provisioned,
        "commitment_qps": commitment,
        "utilization_ratio": ratio,
        "status": "OK" if ratio >= 1.0 else "BELOW_COMMITMENT",
    })
