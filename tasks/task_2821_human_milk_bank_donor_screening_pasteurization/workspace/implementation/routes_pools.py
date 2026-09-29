"""Pooling: pool creation, draws, balance, commit and scrap.

Endpoints (7): POST/GET /pools, GET /pools/{id},
POST/GET /pools/{id}/components, POST /pools/{id}/commit,
POST /pools/{id}/scrap.
"""

from flask import Blueprint

import domain_donor
import domain_pool
import domain_run
import serializers
from auth import (ADMIN, MEDICAL_DIRECTOR, PROCESSING_TECHNICIAN, QA_OFFICER,
                  actor_id, guard)
from envelope import ok, page, pagination
from errors import fail, not_found
from listing import apply_filters, sort_by
from store import db, find, insert, set_field
from util import add_days, dec, parse_date
from validate import field, json_body, validate

bp = Blueprint("pools", __name__)

TARGET_MILK_CLASSES = ("PRETERM", "TERM", "MIXED")
POOL_READERS = (PROCESSING_TECHNICIAN, QA_OFFICER, ADMIN)
POOL_DETAIL_READERS = (PROCESSING_TECHNICIAN, QA_OFFICER, MEDICAL_DIRECTOR, ADMIN)


def pool_or_404(pool_id):
    pool = find("pools", pool_id)
    if pool is None:
        not_found("Pool '%s' does not exist." % pool_id)
    return pool


def class_compatible(target, donation_class):
    if target == "MIXED":
        return True
    return target == donation_class


def in_deferral_window(donation):
    """True when the container was expressed inside any ACTIVE deferral window."""
    expressed = parse_date(donation["expressed_on"])
    if expressed is None:
        return False
    for event in domain_donor.deferrals_of(donation["donor_id"]):
        if event["status"] != "ACTIVE":
            continue
        effective_from = parse_date(event["effective_from"])
        if effective_from is None:
            continue
        window_start = add_days(effective_from, -event["lookback_days"])
        if window_start <= expressed <= effective_from:
            return True
    return False


# --- POST /pools -----------------------------------------------------------
@bp.route("/pools", methods=["POST"])
@guard(PROCESSING_TECHNICIAN)
def create_pool():
    body = json_body()
    values = validate(body, [
        field("pool_code", "string", regex=r"^POOL-[0-9]{4}$"),
        field("target_milk_class", "enum", enum=TARGET_MILK_CLASSES),
    ])
    for existing in db.rows("pools"):
        if existing["pool_code"] == values["pool_code"]:
            fail("ERR_DUPLICATE_CODE",
                 "pool_code '%s' is already in use." % values["pool_code"])
    db.pool_sequence_counter += 1
    pool = insert("pools", {
        "pool_code": values["pool_code"],
        "pool_sequence": db.pool_sequence_counter,
        "target_milk_class": values["target_milk_class"],
        "distinct_donor_count": 0,
        "total_volume_ml": 0,
        "projected_kcal_per_oz": None,
        "bottled_volume_ml": 0,
        "status": "DRAFT",
        "committed_at": None,
        "committed_by_user_id": None,
    })
    return ok(serializers.pool_out(pool), 201)


# --- GET /pools ------------------------------------------------------------
@bp.route("/pools", methods=["GET"])
@guard(*POOL_READERS)
def list_pools():
    limit, offset = pagination()
    rows = apply_filters(db.rows("pools"),
                         [("status", "status", "str"),
                          ("target_milk_class", "target_milk_class", "str")])
    sort_by(rows, [(lambda r: r["created_at"], True),
                   (lambda r: r["pool_code"], False)])
    return page(rows, limit, offset, serializers.pool_out)


# --- GET /pools/{id} -------------------------------------------------------
@bp.route("/pools/<pool_id>", methods=["GET"])
@guard(*POOL_DETAIL_READERS)
def get_pool(pool_id):
    return ok(serializers.pool_out(pool_or_404(pool_id)))


# --- GET /pools/{id}/components -------------------------------------------
@bp.route("/pools/<pool_id>/components", methods=["GET"])
@guard(*POOL_DETAIL_READERS)
def list_pool_components(pool_id):
    pool = pool_or_404(pool_id)
    limit, offset = pagination()
    rows = apply_filters(domain_pool.components_of(pool["id"]),
                         [("status", "status", "str")])
    sort_by(rows, [(lambda r: r["created_at"], False),
                   (lambda r: r["_seq"], False)])
    return page(rows, limit, offset, serializers.component_out)


# --- POST /pools/{id}/components ------------------------------------------
@bp.route("/pools/<pool_id>/components", methods=["POST"])
@guard(PROCESSING_TECHNICIAN)
def create_pool_component(pool_id):
    pool = pool_or_404(pool_id)
    body = json_body()
    raw_donation_id = body.get("donation_id")
    donation = None
    if isinstance(raw_donation_id, str):
        donation = find("donations", raw_donation_id)
        if donation is None:
            not_found("Donation '%s' does not exist." % raw_donation_id)

    values = validate(body, [
        field("donation_id", "string"),
        field("allocated_volume_ml", "integer", min=50, max=1200),
        field("expected_pool_version", "integer"),
    ])

    # PRD 2.10 order for a draw.
    if donation["status"] != "ELIGIBLE":
        fail("ERR_DONATION_STATE_INVALID",
             "A donation in %s may not be drawn from." % donation["status"])
    if pool["status"] not in domain_pool.POOL_OPEN_STATES:
        fail("ERR_POOL_STATE_INVALID",
             "A pool in %s accepts no further components." % pool["status"])
    if values["expected_pool_version"] != pool["version"]:
        fail("ERR_STALE_VERSION", "The pool is at version %d." % pool["version"])
    donor = find("donors", donation["donor_id"])
    if donor is None or donor["status"] != "QUALIFIED":
        fail("ERR_DONOR_NOT_QUALIFIED",
             "The donation's owning donor is not QUALIFIED.")
    if in_deferral_window(donation):
        fail("ERR_DONATION_IN_DEFERRAL_WINDOW",
             "The container falls inside an active deferral lookback window.")
    expressed = parse_date(donation["expressed_on"])
    floor_date = add_days(db.clock_date(), -domain_run.RAW_MILK_MAX_AGE_DAYS)
    if expressed is None or expressed < floor_date:
        fail("ERR_DONOR_MILK_AGE_EXCEEDED",
             "Raw milk expressed before %s may not be pooled." % floor_date.isoformat())
    if not class_compatible(pool["target_milk_class"], donation["milk_class"]):
        fail("ERR_MILK_CLASS_MISMATCH",
             "A %s pool does not accept %s milk."
             % (pool["target_milk_class"], donation["milk_class"]))
    for other in domain_pool.components_of_donation(donation["id"]):
        if other["status"] == "ALLOCATED" and other["pool_id"] != pool["id"]:
            fail("ERR_COMPONENT_ALREADY_ALLOCATED",
                 "The container is already allocated to another pool.")
    if values["allocated_volume_ml"] > donation["remaining_ml"]:
        fail("ERR_ALLOCATION_EXCEEDS_DONATION_REMAINING",
             "Only %d ml remain unallocated on the container."
             % donation["remaining_ml"])
    donors_after = set(
        c["component_donor_id"] for c in domain_pool.components_of(pool["id"])
        if c["status"] == "ALLOCATED"
    )
    donors_after.add(donation["donor_id"])
    if len(donors_after) > domain_pool.MAX_DISTINCT_DONORS:
        fail("ERR_POOL_DONOR_CAP_EXCEEDED",
             "A pool may draw from at most %d donors."
             % domain_pool.MAX_DISTINCT_DONORS)

    component = insert("components", {
        "pool_id": pool["id"],
        "donation_id": donation["id"],
        "allocated_volume_ml": values["allocated_volume_ml"],
        "component_kcal_per_oz": dec(donation["kcal_per_oz"]),
        "component_donor_id": donation["donor_id"],
        "status": "ALLOCATED",
    })
    domain_pool.recompute_donation_remaining(donation)
    if donation["remaining_ml"] == 0:
        set_field(donation, "status", "ALLOCATED")
    domain_pool.recompute_aggregates(pool)
    domain_pool.reevaluate_balance(pool)
    return ok(serializers.component_out(component), 201)


# --- POST /pools/{id}/commit ----------------------------------------------
@bp.route("/pools/<pool_id>/commit", methods=["POST"])
@guard(PROCESSING_TECHNICIAN)
def commit_pool(pool_id):
    pool = pool_or_404(pool_id)
    if pool["status"] not in domain_pool.POOL_OPEN_STATES:
        fail("ERR_POOL_STATE_INVALID",
             "A pool in %s may not be committed." % pool["status"])

    allocated = [c for c in domain_pool.components_of(pool["id"])
                 if c["status"] == "ALLOCATED"]
    if not allocated:
        fail("ERR_POOL_EMPTY", "The pool holds no allocated components.")
    if pool["distinct_donor_count"] < domain_pool.MIN_DISTINCT_DONORS:
        fail("ERR_POOL_DONOR_COUNT_INSUFFICIENT",
             "A pool must draw from at least %d donors."
             % domain_pool.MIN_DISTINCT_DONORS)
    projected = pool["projected_kcal_per_oz"]
    if projected is None or not (domain_pool.KCAL_MIN <= dec(projected)
                                 <= domain_pool.KCAL_MAX):
        fail("ERR_POOL_NUTRITION_OUT_OF_RANGE",
             "The projected caloric density must lie between 19.00 and 21.00.")
    if not (domain_pool.POOL_VOLUME_MIN <= pool["total_volume_ml"]
            <= domain_pool.POOL_VOLUME_MAX):
        fail("ERR_POOL_VOLUME_OUT_OF_RANGE",
             "The pool volume must lie between %d and %d ml."
             % (domain_pool.POOL_VOLUME_MIN, domain_pool.POOL_VOLUME_MAX))

    set_field(pool, "status", "COMMITTED")
    set_field(pool, "committed_at", db.clock_instant())
    set_field(pool, "committed_by_user_id", actor_id())
    return ok(serializers.pool_out(pool))


# --- POST /pools/{id}/scrap -----------------------------------------------
@bp.route("/pools/<pool_id>/scrap", methods=["POST"])
@guard(PROCESSING_TECHNICIAN, QA_OFFICER)
def scrap_pool(pool_id):
    pool = pool_or_404(pool_id)
    if pool["status"] not in domain_pool.POOL_SCRAPPABLE:
        fail("ERR_POOL_STATE_INVALID",
             "A pool in %s may not be scrapped." % pool["status"])
    domain_pool.scrap_pool(pool)
    return ok(serializers.pool_out(pool))
