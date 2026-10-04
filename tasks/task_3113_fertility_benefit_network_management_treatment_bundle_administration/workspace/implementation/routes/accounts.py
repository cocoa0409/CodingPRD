"""Employer accounts and bundle entitlements (PRD 3.1)."""

from body import body, opt, require, require_enum, require_int, require_dt
from bp import api
from clock import parse_dt
from db import db
from errors import APIError
from helpers import employer_of_bundle, recompute_bundle, recompute_employer
from listing import apply_filters, apply_int_filters, ordered, paginate
from lookups import employer_account, bundle_entitlement
from middleware import resolve_actor
from response import ok, created
from serializers import serialize

DEFAULT_COPAY_MAX = False


@api.route("/employer-accounts", methods=["POST"])
def create_employer_account():
    resolve_actor()
    data = body()
    employer_name = require(data, "employer_name")
    plan_year = require_int(data, "plan_year")
    funding_type = require_enum(data, "funding_type")
    allocation_method = require_enum(data, "allocation_method")
    enrollment_limit = require_int(data, "enrollment_limit")

    row = db.common()
    row.update({
        "_collection": "employer_accounts",
        "employer_name": employer_name,
        "plan_year": plan_year,
        "funding_type": funding_type,
        "allocation_method": allocation_method,
        "enrollment_limit": enrollment_limit,
        "account_status": "ACTIVE",
        "active_member_count": 0,
        "entitlement_count": 0,
    })
    db.add(row)
    return created(serialize("employer_accounts", row))


@api.route("/employer-accounts/<account_id>", methods=["GET"])
def get_employer_account(account_id):
    resolve_actor()
    row = employer_account(account_id)
    return ok(serialize("employer_accounts", row))


@api.route("/employer-accounts", methods=["GET"])
def list_employer_accounts():
    resolve_actor()
    rows = ordered(db.all("employer_accounts"))
    rows = apply_filters(rows, {
        "account_status": "account_status",
        "allocation_method": "allocation_method",
    })
    rows = apply_int_filters(rows, {"plan_year": "plan_year"})
    return paginate(rows, "employer_accounts")


@api.route("/employer-accounts/<account_id>/suspend", methods=["POST"])
def suspend_employer_account(account_id):
    resolve_actor()
    account = employer_account(account_id)
    if account["account_status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", "The account is not ACTIVE.")

    account["account_status"] = "SUSPENDED"

    for bundle in db.all("bundle_entitlements"):
        if bundle["employer_account_id"] != account["id"]:
            continue
        recompute_bundle(db, bundle)

    member_ids = {m["id"] for m in db.all("members") if m["employer_account_id"] == account["id"]}
    plan_ids = {p["id"] for p in db.all("treatment_plans") if p["member_id"] in member_ids}
    for pa in db.all("preauthorizations"):
        if pa["treatment_plan_id"] in plan_ids and pa["review_status"] == "SUBMITTED":
            pa["review_status"] = "EXPIRED"
            pa["denial_reason_code"] = "ACCOUNT_SUSPENDED"
            db.touch(pa)

    recompute_employer(db, account)
    db.touch(account)
    return ok(serialize("employer_accounts", account))


@api.route("/employer-accounts/<account_id>/reactivate", methods=["POST"])
def reactivate_employer_account(account_id):
    resolve_actor()
    account = employer_account(account_id)
    if account["account_status"] != "SUSPENDED":
        raise APIError("ERR_INVALID_STATE", "The account is not SUSPENDED.")

    account["account_status"] = "ACTIVE"

    for bundle in db.all("bundle_entitlements"):
        if bundle["employer_account_id"] != account["id"]:
            continue
        recompute_bundle(db, bundle)

    recompute_employer(db, account)
    db.touch(account)
    return ok(serialize("employer_accounts", account))


@api.route("/bundle-entitlements", methods=["POST"])
def create_bundle_entitlement():
    resolve_actor()
    data = body()
    account_id = require(data, "employer_account_id")
    bundle_type = require_enum(data, "bundle_type")
    lifetime_max_cycles = require_int(data, "lifetime_max_cycles")
    max_cycles_per_year = require_int(data, "max_cycles_per_year")
    max_transfers_per_cycle = require_int(data, "max_transfers_per_cycle")
    pharmacy_pool_cents = require_int(data, "pharmacy_pool_cents")
    copay_max = bool(opt(data, "copay_max", DEFAULT_COPAY_MAX))
    effective_from = require_dt(data, "effective_from")
    effective_to = require_dt(data, "effective_to")

    if effective_to <= effective_from:
        raise APIError("ERR_INVALID_REQUEST", "The effective interval end precedes its start.")

    account = db.find("employer_accounts", account_id)
    if account is None:
        raise APIError("ERR_NOT_FOUND", "The employer_account_id does not resolve.")

    row = db.common()
    row.update({
        "_collection": "bundle_entitlements",
        "_activated": False,
        "employer_account_id": account_id,
        "bundle_type": bundle_type,
        "lifetime_max_cycles": lifetime_max_cycles,
        "max_cycles_per_year": max_cycles_per_year,
        "max_transfers_per_cycle": max_transfers_per_cycle,
        "pharmacy_pool_cents": pharmacy_pool_cents,
        "copay_max": copay_max,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "cycles_consumed": 0,
        "cycles_committed": 0,
        "cycles_remaining": 0,
        "pharmacy_consumed_cents": 0,
        "pharmacy_remaining_cents": 0,
        "bundle_status": "DRAFT",
    })
    db.add(row)

    recompute_employer(db, account)
    db.touch(account)
    return created(serialize("bundle_entitlements", row))


@api.route("/bundle-entitlements/<bundle_id>", methods=["GET"])
def get_bundle_entitlement(bundle_id):
    resolve_actor()
    row = bundle_entitlement(bundle_id)
    return ok(serialize("bundle_entitlements", row))


@api.route("/bundle-entitlements", methods=["GET"])
def list_bundle_entitlements():
    resolve_actor()
    rows = ordered(db.all("bundle_entitlements"))
    rows = apply_filters(rows, {
        "employer_account_id": "employer_account_id",
        "bundle_type": "bundle_type",
        "bundle_status": "bundle_status",
    })
    return paginate(rows, "bundle_entitlements")


@api.route("/bundle-entitlements/<bundle_id>/activate", methods=["POST"])
def activate_bundle_entitlement(bundle_id):
    resolve_actor()
    bundle = bundle_entitlement(bundle_id)
    if bundle["bundle_status"] != "DRAFT":
        raise APIError("ERR_INVALID_STATE", "The entitlement is not DRAFT.")

    account = employer_of_bundle(db, bundle)
    if account is None or account["account_status"] != "ACTIVE":
        raise APIError("ERR_BENEFIT_INACTIVE", "The sponsoring account is not ACTIVE.")

    if parse_dt(bundle["effective_from"]) > db.now():
        raise APIError("ERR_INVALID_STATE", "The entitlement's effective_from has not been reached.")

    bundle["_activated"] = True
    recompute_bundle(db, bundle, force=True)

    recompute_employer(db, account)
    db.touch(account)
    return ok(serialize("bundle_entitlements", bundle))


@api.route("/bundle-entitlements/<bundle_id>/reinstate", methods=["POST"])
def reinstate_bundle_entitlement(bundle_id):
    resolve_actor()
    bundle = bundle_entitlement(bundle_id)
    if bundle["bundle_status"] != "EXHAUSTED":
        raise APIError("ERR_INVALID_STATE", "The entitlement is not EXHAUSTED.")

    account = employer_of_bundle(db, bundle)
    if account is None or account["account_status"] != "ACTIVE":
        raise APIError("ERR_BENEFIT_INACTIVE", "The sponsoring account is not ACTIVE.")

    bundle["_activated"] = True
    recompute_bundle(db, bundle, force=True)

    recompute_employer(db, account)
    db.touch(account)
    return ok(serialize("bundle_entitlements", bundle))