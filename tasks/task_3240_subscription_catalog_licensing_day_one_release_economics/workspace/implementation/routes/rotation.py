"""CatalogEntry rotation and CatalogMaintenance."""
from datetime import timedelta

from flask import Blueprint, request

from checks import page, query_paging
from db import db
from errors import fail
from request_ctx import (ctx, expect_query, run, want_int, want_instant, want_str,
                         want_tier_list)
from response import ok_array, ok_object
from services import calc
from services.store import (cascade_retire, publish_entitlements,
                            refresh_region_capacities, refresh_subscriber_impact,
                            refresh_title_status)

bp = Blueprint("rotation", __name__)

RELEASE_CLASSES = ("DAY_ONE", "BACK_CATALOG", "CATALOG_ADD")
ENTRY_STATUSES = ("PLANNED", "ADDED", "REMOVING", "DELISTED")
TIER_ORDER = {"ESSENTIAL": 0, "PREMIUM": 1, "ULTIMATE": 2}


def binding_deal(title_id):
    """The deal that binds a title into the catalogue.

    Publication and planning both require the underlying deal to sit in SIGNED
    or LIVE (PRD 3.3); an EXPIRING or COMPLETED deal no longer binds.
    """
    rows = [r for r in db.deals.values()
            if r["title_id"] == title_id and r["status"] in ("SIGNED", "LIVE")]
    if not rows:
        return None
    rows.sort(key=lambda r: (0 if r["status"] == "LIVE" else 1,
                             r["term_start_date"], r["_seq"]))
    return rows[0]


def live_deal(title_id):
    rows = [r for r in db.deals.values()
            if r["title_id"] == title_id and r["status"] == "LIVE"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["term_start_date"], r["_seq"]))
    return rows[0]


def entry_view(entry):
    return db.public(entry)


def _title(tid):
    row = db.titles.get(tid)
    if row is None:
        fail("ERR_TITLE_NOT_FOUND", "No title exists with id %s." % tid)
    return row


def _region(code):
    row = db.regions.get(code)
    if row is None:
        fail("ERR_REGION_NOT_FOUND", "No region exists with code %s." % code)
    return row


def _entry(eid):
    row = db.entries.get(eid)
    if row is None:
        fail("ERR_ENTRY_NOT_FOUND", "No catalog entry exists with id %s." % eid)
    return row


def maintenance_window_active(region_code, now):
    for row in db.maintenances.values():
        if row["region_code"] != region_code:
            continue
        if row["maintenance_start"] <= now < row["maintenance_end"]:
            return row
    return None


# --------------------------------------------------------------------------
# CatalogEntry create / read / list
# --------------------------------------------------------------------------
@bp.route("/catalog/catalog-entries", methods=["POST"])
def create_entry():
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_entry, on_resolve=_entry_refs, on_temporal=_entry_temporal,
        on_eligibility=_entry_eligibility)
    title = c.extra["title"]
    region = c.extra["region"]
    deal = binding_deal(title["id"])
    entry = db.new_row()
    entry.update({
        "title_id": title["id"],
        "deal_id": deal["id"] if deal else None,
        "region_code": region["region_code"],
        "tiers": c.get("tiers"),
        "announced_add_date": c.get("announced_add_date"),
        "actual_add_date": None,
        "removal_date": c.get("removal_date"),
        "release_class": c.get("release_class"),
        "popularity_index_cents": c.get("popularity_index_cents"),
        "popularity_index_cents_30d_avg": c.int_of("popularity_index_cents_30d_avg", 0),
        "removal_notice_days": calc.removal_notice_days(c.get("announced_add_date"),
                                                        c.get("removal_date")),
        "subscriber_impact_count": 0,
        "status": "PLANNED",
    })
    db.entries[entry["id"]] = entry
    # entry_id on the deal names the first catalogue entry planned against it
    if deal is not None and deal.get("entry_id") is None:
        deal["entry_id"] = entry["id"]
        db.touch(deal)
    return ok_object(entry_view(entry), 201)


def _shape_entry(c):
    want_str(c, "title_id", required=True)
    want_str(c, "region_code", required=True)
    want_tier_list(c, "tiers", required=True)
    want_instant(c, "announced_add_date", required=True)
    want_instant(c, "removal_date", required=True)
    want_str(c, "release_class", allowed=RELEASE_CLASSES, required=True)
    want_int(c, "popularity_index_cents", lo=0, hi=10000, required=True)
    want_int(c, "popularity_index_cents_30d_avg", lo=0, hi=10000)


def _entry_refs(c):
    c.extra["title"] = _title(c.get("title_id"))
    c.extra["region"] = _region(c.get("region_code"))


def _entry_temporal(c):
    if c.get("removal_date") <= c.get("announced_add_date"):
        fail("ERR_REMOVAL_DATE_NOT_AFTER_ADD",
             "removal_date must be strictly after announced_add_date.")
    window = maintenance_window_active(c.get("region_code"), db.clock)
    if window is not None:
        fail("ERR_REGION_MAINTENANCE_WINDOW_ACTIVE",
             "Region %s is inside a maintenance window." % c.get("region_code"))


def _tier_floor_ok(tiers, region):
    floor = TIER_ORDER[region["catalog_tier_floor"]]
    for code in tiers:
        if TIER_ORDER[code] < floor:
            return False
    return True


def _cloud_granting_tiers(tiers):
    out = []
    for code in tiers:
        tier = db.tiers.get(code)
        if tier is not None and tier["cloud_access"]:
            out.append(code)
    return out


def _entry_eligibility(c):
    title = c.extra["title"]
    region = c.extra["region"]
    tiers = c.get("tiers")
    if not _tier_floor_ok(tiers, region):
        fail("ERR_TIER_BELOW_REGION_FLOOR",
             "A named tier sits below the region's catalog_tier_floor.")
    if _cloud_granting_tiers(tiers) and "CLOUD" not in title["platform_set"]:
        fail("ERR_PLATFORM_NOT_SUPPORTED",
             "A cloud-granting tier requires the title to ship on CLOUD.")


@bp.route("/catalog/catalog-entries/<entry_id>", methods=["GET"])
def read_entry(entry_id):
    c = ctx(["CatalogAdmin", "CatalogAnalyst", "Subscriber"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"entry": _entry(entry_id)}))
    return ok_object(entry_view(c.extra["entry"]))


@bp.route("/catalog/catalog-entries", methods=["GET"])
def list_entries():
    c = ctx(["CatalogAdmin", "CatalogAnalyst", "Subscriber"])
    expect_query(c, ("region_code", "title_id", "deal_id", "status", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.entries)
    for key in ("region_code", "title_id", "deal_id"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    status = request.args.get("status")
    if status is not None:
        if status not in ENTRY_STATUSES:
            fail("ERR_INVALID_REQUEST", "Unknown entry status %s." % status)
        rows = [r for r in rows if r["status"] == status]
    window, total = page(rows, limit, offset)
    return ok_array([entry_view(r) for r in window], limit, offset, total)


def _nothing(_c):
    return None


# --------------------------------------------------------------------------
# publish
# --------------------------------------------------------------------------
def _publish_state(c):
    entry = c.extra["entry"]
    if entry["status"] != "PLANNED":
        fail("ERR_ENTRY_NOT_PUBLISHABLE",
             "Entry %s is in status %s and cannot be published."
             % (entry["id"], entry["status"]))


def _publish_temporal(c):
    entry = c.extra["entry"]
    window = maintenance_window_active(entry["region_code"], db.clock)
    if window is not None:
        fail("ERR_REGION_MAINTENANCE_WINDOW_ACTIVE",
             "Region %s is inside a maintenance window." % entry["region_code"])


def _publish_eligibility(c):
    entry = c.extra["entry"]
    title = db.titles[entry["title_id"]]
    region = db.regions[entry["region_code"]]
    deal = binding_deal(title["id"])
    if deal is None:
        fail("ERR_NO_BINDING_DEAL",
             "Title %s has no licensing deal in SIGNED or LIVE status." % title["id"])
    publisher = db.publishers.get(deal["publisher_id"])
    if publisher is None or publisher["status"] != "ACTIVE":
        fail("ERR_PUBLISHER_SUSPENDED",
             "Publisher %s is suspended." % deal["publisher_id"])
    if not _tier_floor_ok(entry["tiers"], region):
        fail("ERR_TIER_BELOW_REGION_FLOOR",
             "A named tier sits below the region's catalog_tier_floor.")
    if _cloud_granting_tiers(entry["tiers"]) and "CLOUD" not in title["platform_set"]:
        fail("ERR_PLATFORM_NOT_SUPPORTED",
             "A cloud-granting tier requires the title to ship on CLOUD.")
    if entry["release_class"] == "DAY_ONE" and "CONSOLE" not in title["platform_set"]:
        fail("ERR_PLATFORM_NOT_SUPPORTED",
             "A DAY_ONE entry requires the title to ship on CONSOLE.")
    if entry["release_class"] == "DAY_ONE" and not title["day_one_eligible"]:
        fail("ERR_DAY_ONE_NOT_ELIGIBLE",
             "Title %s is not day-one eligible." % title["id"])


def _publish_fiscal(c):
    entry = c.extra["entry"]
    region = db.regions[entry["region_code"]]
    live = [r for r in db.entries.values()
            if r["region_code"] == entry["region_code"] and r["status"] in ("ADDED", "REMOVING")]
    if len(live) >= region["availability_ceiling_titles"]:
        fail("ERR_REGION_CATALOG_CEILING_REACHED",
             "Region %s already holds %s entries."
             % (entry["region_code"], region["availability_ceiling_titles"]))


@bp.route("/catalog/catalog-entries/<entry_id>/publish", methods=["POST"])
def publish_entry(entry_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"entry": _entry(entry_id)}),
        on_state=_publish_state, on_temporal=_publish_temporal,
        on_eligibility=_publish_eligibility, on_fiscal=_publish_fiscal)
    _do_publish(c.extra["entry"])
    return ok_object(entry_view(c.extra["entry"]))


def _do_publish(entry):
    entry["status"] = "ADDED"
    entry["actual_add_date"] = db.clock
    db.touch(entry)
    entry["removal_notice_days"] = calc.removal_notice_days(entry["announced_add_date"],
                                                           entry["removal_date"])
    # PRD 3.3: the entry's deal_id is "the system resolves the entry's `deal_id`
    # from the title's binding deal". A plan filed before the deal went LIVE
    # carries none; publication re-resolves it against the now-binding deal.
    if entry.get("deal_id") is None:
        bound = live_deal(entry["title_id"])
        if bound is not None:
            entry["deal_id"] = bound["id"]
            db.touch(entry)
    publish_entitlements(entry, db.clock)
    refresh_subscriber_impact(entry)
    title = db.titles.get(entry["title_id"])
    if title is not None:
        if title["status"] == "DRAFT":
            title["status"] = "RELEASED"
            db.touch(title)
        calc.refresh_title_score(title)
    refresh_region_capacities()
    return entry


# --------------------------------------------------------------------------
# announce-removal
# --------------------------------------------------------------------------
def _announce_state(c):
    entry = c.extra["entry"]
    if entry["status"] == "DELISTED":
        fail("ERR_ENTRY_ALREADY_DELISTED", "Entry %s is already delisted." % entry["id"])
    if entry["status"] == "REMOVING":
        fail("ERR_REMOVAL_ALREADY_ANNOUNCED",
             "Entry %s already has a live removal announcement." % entry["id"])
    if entry["status"] != "ADDED":
        fail("ERR_ENTRY_NOT_PUBLISHABLE",
             "Entry %s is in status %s." % (entry["id"], entry["status"]))


def _announce_temporal(c):
    entry = c.extra["entry"]
    if not entry["removal_date"] > entry["actual_add_date"]:
        fail("ERR_REMOVAL_DATE_NOT_AFTER_ADD",
             "removal_date must be strictly after actual_add_date.")
    notice = calc.removal_notice_days(entry["announced_add_date"], entry["removal_date"])
    if notice < calc.minimum_notice_days(entry["release_class"]):
        fail("ERR_INSUFFICIENT_REMOVAL_NOTICE",
             "A %s entry needs at least %s days of notice."
             % (entry["release_class"], calc.minimum_notice_days(entry["release_class"])))


@bp.route("/catalog/catalog-entries/<entry_id>/announce-removal", methods=["POST"])
def announce_removal(entry_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"entry": _entry(entry_id)}),
        on_state=_announce_state, on_temporal=_announce_temporal)
    entry = c.extra["entry"]
    entry["status"] = "REMOVING"
    entry["removal_notice_announced_at"] = db.clock
    db.touch(entry)
    entry["removal_notice_days"] = calc.removal_notice_days(entry["announced_add_date"],
                                                           entry["removal_date"])
    refresh_subscriber_impact(entry)
    refresh_region_capacities()
    return ok_object(entry_view(entry))


# --------------------------------------------------------------------------
# cancel-removal
# --------------------------------------------------------------------------
def _cancel_state(c):
    entry = c.extra["entry"]
    if entry["status"] == "DELISTED":
        fail("ERR_ENTRY_ALREADY_DELISTED", "Entry %s is already delisted." % entry["id"])
    if entry["status"] == "ADDED":
        fail("ERR_REMOVAL_NOT_ANNOUNCED",
             "Entry %s carries no live removal announcement." % entry["id"])
    if entry["status"] != "REMOVING":
        fail("ERR_ENTRY_NOT_PUBLISHABLE",
             "Entry %s is in status %s." % (entry["id"], entry["status"]))


def _cancel_temporal(c):
    entry = c.extra["entry"]
    if db.clock >= entry["removal_date"]:
        fail("ERR_REMOVAL_REVERT_WINDOW_CLOSED",
             "Entry %s has already reached its removal date." % entry["id"])
    if not db.clock < entry["removal_date"] - timedelta(days=calc.REMOVAL_REVERT_CUTOFF_DAYS):
        fail("ERR_REMOVAL_REVERT_CUTOFF",
             "The three-day revert cutoff has passed for entry %s." % entry["id"])


@bp.route("/catalog/catalog-entries/<entry_id>/cancel-removal", methods=["POST"])
def cancel_removal(entry_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"entry": _entry(entry_id)}),
        on_state=_cancel_state, on_temporal=_cancel_temporal)
    entry = c.extra["entry"]
    entry["status"] = "ADDED"
    entry.pop("removal_notice_announced_at", None)
    db.touch(entry)
    refresh_subscriber_impact(entry)
    refresh_region_capacities()
    return ok_object(entry_view(entry))


# --------------------------------------------------------------------------
# retire
# --------------------------------------------------------------------------
def _retire_state(c):
    entry = c.extra["entry"]
    if entry["status"] == "DELISTED":
        fail("ERR_ENTRY_ALREADY_DELISTED", "Entry %s is already delisted." % entry["id"])


@bp.route("/catalog/catalog-entries/<entry_id>/retire", methods=["POST"])
def retire_entry(entry_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"entry": _entry(entry_id)}),
        on_state=_retire_state)
    entry = c.extra["entry"]
    if entry["status"] == "PLANNED":
        entry["status"] = "DELISTED"
        db.touch(entry)
    else:
        cascade_retire(entry, db.clock)
    refresh_region_capacities()
    return ok_object(entry_view(entry))


# --------------------------------------------------------------------------
# CatalogMaintenance (read-only surface)
# --------------------------------------------------------------------------
@bp.route("/catalog/catalog-maintenances/<maintenance_id>", methods=["GET"])
def read_maintenance(maintenance_id):
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ())
    row = db.maintenances.get(maintenance_id)
    if row is None:
        fail("ERR_REGION_NOT_FOUND",
             "No catalog maintenance exists with id %s." % maintenance_id)
    return ok_object(db.public(row))


@bp.route("/catalog/catalog-maintenances", methods=["GET"])
def list_maintenances():
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("region_code", "status", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.maintenances)
    region_code = request.args.get("region_code")
    if region_code is not None:
        rows = [r for r in rows if r["region_code"] == region_code]
    status = request.args.get("status")
    if status is not None:
        if status not in ("SCHEDULED", "ACTIVE", "COMPLETED"):
            fail("ERR_INVALID_REQUEST", "Unknown maintenance status %s." % status)
        rows = [r for r in rows if r["status"] == status]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)
