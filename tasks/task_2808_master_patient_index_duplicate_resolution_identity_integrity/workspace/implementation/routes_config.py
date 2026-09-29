"""Logical clock, registration sites, match rule sets, downstream systems."""

from decimal import Decimal

from flask import Blueprint

from core import (
    ALL_ROLES, SCORED_ATTRIBUTES, authenticate, bad_request, base_entity, created,
    err, field_bool, field_enum, field_int, field_map, field_string, field_decimal,
    get_body, iso, now, ok, parse_datetime, q2, store, touch,
)
import serializers

bp = Blueprint("config", __name__)

HUNDRED = Decimal("100.00")


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ALL_ROLES)
    body = get_body()
    value = body.get("current_utc")
    if not isinstance(value, str):
        raise bad_request("field 'current_utc' is required")
    parsed = parse_datetime(value)
    if parsed is None:
        raise bad_request("field 'current_utc' must be an ISO 8601 UTC datetime")
    store.clock = parsed
    return ok({"current_utc": iso(store.clock)})


# --------------------------------------------------------------------------
# Registration sites
# --------------------------------------------------------------------------
SITE_CODE_PATTERN = r"^[A-Z0-9-]{1,12}$"


@bp.post("/mpi/registration-sites")
def create_site():
    authenticate(["MpiAdmin"])
    body = get_body()
    site_code = field_string(body, "site_code", required=True, min_len=1, max_len=12,
                             pattern=SITE_CODE_PATTERN)
    name = field_string(body, "name", required=True)
    region_code = field_string(body, "region_code", required=True)
    headcount = field_int(body, "registrar_headcount", required=True, minimum=0)
    if any(s["site_code"] == site_code for s in store.sites.values()):
        raise bad_request("site_code '%s' is already registered" % site_code)
    row = base_entity()
    row.update({
        "site_code": site_code,
        "name": name,
        "region_code": region_code,
        "registrar_headcount": headcount,
        "status": "ACTIVE",
    })
    store.sites[row["id"]] = row
    return created(serializers.site(row))


@bp.patch("/mpi/registration-sites/<site_id>")
def patch_site(site_id):
    authenticate(["MpiAdmin"])
    body = get_body()
    name = field_string(body, "name")
    headcount = field_int(body, "registrar_headcount", minimum=0)
    status = field_enum(body, "status", ["ACTIVE", "SUSPENDED"])
    row = store.sites.get(site_id)
    if row is None:
        raise err("ERR_SITE_NOT_FOUND", "No registration site with id %s" % site_id)
    if name is not None:
        row["name"] = name
    if headcount is not None:
        row["registrar_headcount"] = headcount
    if status is not None:
        row["status"] = status
    touch(row)
    return ok(serializers.site(row))


@bp.get("/mpi/registration-sites/<site_id>")
def get_site(site_id):
    authenticate(ALL_ROLES)
    row = store.sites.get(site_id)
    if row is None:
        raise err("ERR_SITE_NOT_FOUND", "No registration site with id %s" % site_id)
    return ok(serializers.site(row))


# --------------------------------------------------------------------------
# Match rule sets
# --------------------------------------------------------------------------
@bp.post("/mpi/match-rule-sets")
def create_rule_set():
    authenticate(["MpiAdmin"])
    body = get_body()
    name = field_string(body, "name", required=True)
    version_label = field_string(body, "version_label", required=True)
    weights = field_map(body, "attribute_weights", exact_keys=SCORED_ATTRIBUTES, required=True)
    parsed_weights = {}
    for attr in SCORED_ATTRIBUTES:
        parsed_weights[attr] = field_decimal(weights, attr, required=True, minimum=Decimal("0.00"))
    auto = field_decimal(body, "auto_link_threshold", required=True,
                         minimum=Decimal("0.00"), maximum=HUNDRED)
    review = field_decimal(body, "review_threshold", required=True,
                           minimum=Decimal("0.00"), maximum=HUNDRED)
    penalty = field_decimal(body, "conflict_penalty_points", required=True,
                            minimum=Decimal("0.00"), maximum=HUNDRED)
    # rank 16 then rank 17
    if sum(parsed_weights.values()) != HUNDRED:
        raise err("ERR_WEIGHTS_SUM_INVALID",
                  "The seven attribute_weights values must sum to exactly 100.00")
    if review > auto:
        raise err("ERR_THRESHOLD_ORDER_INVALID",
                  "review_threshold must not exceed auto_link_threshold")
    row = base_entity()
    row.update({
        "name": name,
        "version_label": version_label,
        "attribute_weights": {k: q2(v) for k, v in parsed_weights.items()},
        "auto_link_threshold": q2(auto),
        "review_threshold": q2(review),
        "conflict_penalty_points": q2(penalty),
        "status": "DRAFT",
    })
    store.rule_sets[row["id"]] = row
    return created(serializers.rule_set(row))


@bp.post("/mpi/match-rule-sets/<rule_set_id>/activate")
def activate_rule_set(rule_set_id):
    authenticate(["MpiAdmin"])
    get_body()
    row = store.rule_sets.get(rule_set_id)
    if row is None:
        raise err("ERR_RULE_SET_NOT_FOUND", "No match rule set with id %s" % rule_set_id)
    if row["status"] != "DRAFT":
        raise bad_request("only a DRAFT rule set may be promoted to ACTIVE")
    for other in store.rule_sets.values():
        if other["id"] != row["id"] and other["status"] == "ACTIVE":
            other["status"] = "RETIRED"
            touch(other)
    row["status"] = "ACTIVE"
    touch(row)
    return ok(serializers.rule_set(row))


@bp.get("/mpi/match-rule-sets/<rule_set_id>")
def get_rule_set(rule_set_id):
    authenticate(ALL_ROLES)
    row = store.rule_sets.get(rule_set_id)
    if row is None:
        raise err("ERR_RULE_SET_NOT_FOUND", "No match rule set with id %s" % rule_set_id)
    return ok(serializers.rule_set(row))


def active_rule_set():
    for row in sorted(store.rule_sets.values(), key=lambda r: r["_seq"]):
        if row["status"] == "ACTIVE":
            return row
    return None


# --------------------------------------------------------------------------
# Downstream systems
# --------------------------------------------------------------------------
@bp.post("/mpi/downstream-systems")
def create_system():
    authenticate(["MpiAdmin"])
    body = get_body()
    system_code = field_string(body, "system_code", required=True, min_len=1, max_len=16)
    name = field_string(body, "name", required=True)
    mode = field_enum(body, "propagation_mode", ["SYNCHRONOUS", "BATCH"], required=True)
    ack_required = field_bool(body, "ack_required", required=True)
    max_concurrent = field_int(body, "max_concurrent_dispatch", required=True, minimum=1)
    if any(s["system_code"] == system_code for s in store.systems.values()):
        raise bad_request("system_code '%s' is already registered" % system_code)
    row = base_entity()
    row.update({
        "system_code": system_code,
        "name": name,
        "propagation_mode": mode,
        "ack_required": ack_required,
        "max_concurrent_dispatch": max_concurrent,
        "status": "ACTIVE",
    })
    store.systems[row["id"]] = row
    return created(serializers.system(row))


@bp.patch("/mpi/downstream-systems/<system_id>")
def patch_system(system_id):
    authenticate(["MpiAdmin"])
    body = get_body()
    name = field_string(body, "name")
    status = field_enum(body, "status", ["ACTIVE", "PAUSED"])
    max_concurrent = field_int(body, "max_concurrent_dispatch", minimum=1)
    row = store.systems.get(system_id)
    if row is None:
        raise err("ERR_DOWNSTREAM_SYSTEM_NOT_FOUND", "No downstream system with id %s" % system_id)
    if name is not None:
        row["name"] = name
    if status is not None:
        row["status"] = status
    if max_concurrent is not None:
        row["max_concurrent_dispatch"] = max_concurrent
    touch(row)
    return ok(serializers.system(row))


@bp.get("/mpi/downstream-systems/<system_id>")
def get_system(system_id):
    authenticate(ALL_ROLES)
    row = store.systems.get(system_id)
    if row is None:
        raise err("ERR_DOWNSTREAM_SYSTEM_NOT_FOUND", "No downstream system with id %s" % system_id)
    return ok(serializers.system(row))
