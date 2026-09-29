"""Section 3.6 - authentication bindings, realm capacity and access incidents."""

from flask import Blueprint, request

import auth
import calc
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("access", __name__)


def _windows_overlap(left, right):
    """Windows run [activation_start_date, term_end] and are closed at both
    ends, so windows that merely touch on a single day do overlap."""
    return left["activation_start_date"] <= right["term_end"] \
        and right["activation_start_date"] <= left["term_end"]


@bp.post("/erm/subscriptions/<subscription_id>/auth-configs")
def create_auth_config(subscription_id):
    auth.require_roles(auth.ROLE_ACCESS_ENGINEER)
    subscription = auth.get_subscription(subscription_id)
    data = shape.body()
    auth_method = shape.req_enum(data, "auth_method", shape.AUTH_METHODS)
    auth_realm_code = shape.req_string(data, "auth_realm_code")
    ip_ranges = shape.req_string_array(data, "ip_ranges")
    if auth_method == "EZPROXY":
        proxy_prefix = shape.req_string(data, "proxy_prefix")
    else:
        proxy_prefix = shape.opt_string(data, "proxy_prefix", None)

    if subscription["contract_status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")

    # priority 17 - the federation realm has finite overlapping capacity
    overlapping = 0
    for config in store.auth_configs.values():
        if config["auth_realm_code"] != auth_realm_code:
            continue
        if config["verification_status"] not in ("PENDING", "VERIFIED"):
            continue
        other = store.subscriptions.get(config["subscription_id"])
        if other is None:
            continue
        if _windows_overlap(other, subscription):
            overlapping += 1
    if overlapping >= calc.MAX_OVERLAPPING_REALM_BINDINGS:
        raise ApiError("ERR_REALM_CAPACITY_EXCEEDED")

    row = store.new_row({
        "subscription_id": subscription["id"],
        "auth_method": auth_method,
        "auth_realm_code": auth_realm_code,
        "ip_ranges": ip_ranges,
        "proxy_prefix": proxy_prefix,
        "verification_status": "PENDING",
        "last_probe_result": None,
    })
    store.auth_configs[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/subscriptions/<subscription_id>/auth-configs")
def list_auth_configs(subscription_id):
    auth.require_roles(
        auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_ACCESS_ENGINEER
    )
    subscription = auth.get_subscription(subscription_id)
    rows = [
        r for r in store.auth_configs.values()
        if r["subscription_id"] == subscription["id"]
    ]
    return envelope.paged(rows)


@bp.post("/erm/auth-configs/<auth_config_id>/verify")
def verify_auth_config(auth_config_id):
    auth.require_roles(auth.ROLE_ACCESS_ENGINEER)
    config = auth.get_auth_config(auth_config_id)
    data = shape.body()
    probe_result = shape.req_enum(data, "probe_result", shape.PROBE_RESULTS)

    if config["verification_status"] not in ("PENDING", "FAILED"):
        raise ApiError("ERR_AUTH_CONFIG_INVALID_STATE")
    subscription = store.subscriptions[config["subscription_id"]]
    if subscription["contract_status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")

    if probe_result == "PASS":
        store.mutate(config, {"verification_status": "VERIFIED", "last_probe_result": "PASS"})
        store.mutate(subscription, {
            "access_status": "CONFIGURED",
            "access_health_score": 100,
        })
    else:
        # a failed probe touches nothing on the subscription
        store.mutate(config, {"verification_status": "FAILED", "last_probe_result": probe_result})
    return envelope.object_response(store.serialize(config))


@bp.post("/erm/subscriptions/<subscription_id>/access-incidents")
def create_incident(subscription_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    subscription = auth.get_subscription(subscription_id)
    data = shape.body()
    if shape.present(data, "member_id"):
        auth.get_member(data["member_id"])
        auth.require_member_scope(data["member_id"])
    member_id = shape.req_string(data, "member_id")
    symptom_code = shape.req_enum(data, "symptom_code", shape.SYMPTOM_CODES)
    off_campus = shape.req_bool(data, "off_campus")

    row = store.new_row({
        "subscription_id": subscription["id"],
        "member_id": member_id,
        "symptom_code": symptom_code,
        "off_campus": off_campus,
        "status": "OPEN",
        "root_cause_code": None,
        "remedy_code": None,
        "reopen_count": 0,
    })
    store.access_incidents[row["id"]] = row
    services.recompute_access_health(subscription, "incident")
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/access-incidents/<incident_id>")
def read_incident(incident_id):
    auth.require_roles(
        auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_ACCESS_ENGINEER
    )
    row = auth.get_incident(incident_id)
    return envelope.object_response(store.serialize(row))


@bp.get("/erm/access-incidents")
def list_incidents():
    auth.require_roles(
        auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_ACCESS_ENGINEER
    )
    rows = list(store.access_incidents.values())
    for field in ("subscription_id", "member_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return envelope.paged(rows)


@bp.post("/erm/access-incidents/<incident_id>/diagnose")
def diagnose_incident(incident_id):
    auth.require_roles(auth.ROLE_ACCESS_ENGINEER)
    incident = auth.get_incident(incident_id)
    data = shape.body()
    root_cause_code = shape.req_enum(data, "root_cause_code", shape.ROOT_CAUSE_CODES)
    if incident["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_INCIDENT_INVALID_STATE")
    store.mutate(incident, {"root_cause_code": root_cause_code, "status": "DIAGNOSED"})
    return envelope.object_response(store.serialize(incident))


@bp.post("/erm/access-incidents/<incident_id>/resolve")
def resolve_incident(incident_id):
    auth.require_roles(auth.ROLE_ACCESS_ENGINEER)
    incident = auth.get_incident(incident_id)
    data = shape.body()
    remedy_code = shape.req_enum(data, "remedy_code", shape.REMEDY_CODES)
    if incident["status"] != "DIAGNOSED":
        raise ApiError("ERR_INCIDENT_INVALID_STATE")
    store.mutate(incident, {"remedy_code": remedy_code, "status": "RESOLVED"})
    subscription = store.subscriptions[incident["subscription_id"]]
    services.recompute_access_health(subscription, "resolve")
    return envelope.object_response(store.serialize(incident))


@bp.post("/erm/access-incidents/<incident_id>/reopen")
def reopen_incident(incident_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    incident = auth.get_incident(incident_id)
    auth.require_member_scope(incident["member_id"])
    if incident["status"] != "RESOLVED":
        raise ApiError("ERR_INCIDENT_INVALID_STATE")
    # hop one - the incident itself
    store.mutate(incident, {
        "reopen_count": incident["reopen_count"] + 1,
        "remedy_code": None,
        "status": "REOPENED",
    })
    # hops two to four follow from that mutation
    subscription = store.subscriptions[incident["subscription_id"]]
    services.recompute_access_health(subscription, "incident")
    return envelope.object_response(store.serialize(incident))
