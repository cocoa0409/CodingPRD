"""SlicerAsset and SanitationCycle groups (PRD 3.2)."""
from errors import fail, invalid
from http_support import (
    Endpoint, as_int, as_string, body, envelope_array, opt, query, req,
)
from response import ok_object
from util import parse_dt
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
CLERK_ROLES = ["DeliClerk", "DeliManager"]
MANAGER_ROLES = ["PlatformAdmin", "DeliManager"]

CYCLE_TYPES = ("ROUTINE", "ALLERGEN_CHANGEOVER", "TIMED")
CYCLE_STATUSES = ("OPEN", "COMPLETE", "ABORTED")
SANITATION_STATUSES = ("CLEAN", "IN_USE", "NEEDS_SANITATION", "SANITIZING")

MAX_REOPEN_PER_DAY = 2


def register(app):
    Endpoint(app, "POST", "/deli/slicers", MANAGER_ROLES, create_slicer)
    Endpoint(app, "GET", "/deli/slicers/<id>", READ_ROLES, get_slicer)
    Endpoint(app, "GET", "/deli/slicers", READ_ROLES, list_slicers)
    Endpoint(app, "POST", "/deli/slicers/<id>/assign-operator", MANAGER_ROLES,
             assign_operator)
    Endpoint(app, "PATCH", "/deli/slicers/<id>", MANAGER_ROLES, patch_slicer)

    Endpoint(app, "POST", "/deli/sanitation-cycles", CLERK_ROLES, open_cycle)
    Endpoint(app, "GET", "/deli/sanitation-cycles/<id>", READ_ROLES, get_cycle)
    Endpoint(app, "GET", "/deli/sanitation-cycles", READ_ROLES, list_cycles)
    Endpoint(app, "POST", "/deli/sanitation-cycles/<id>/complete", CLERK_ROLES,
             complete_cycle)
    Endpoint(app, "POST", "/deli/sanitation-cycles/<id>/reopen", MANAGER_ROLES,
             reopen_cycle)
    Endpoint(app, "POST", "/deli/sanitation-cycles/<id>/abort", MANAGER_ROLES,
             abort_cycle)


# --------------------------------------------------------------- slicers ------
def create_slicer(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    asset_tag = as_string(req(payload, "asset_tag"), "asset_tag")
    if any(s["store_id"] == store_id and s["asset_tag"] == asset_tag
           for s in store.slicers.values()):
        invalid("asset_tag must be unique within the store.")
    limit = as_int(opt(payload, "sanitation_cycle_limit", default=25),
                   "sanitation_cycle_limit")
    if limit < 1:
        invalid("sanitation_cycle_limit must be at least 1.")
    operator_id = opt(payload, "assigned_operator_id")
    if operator_id is not None:
        svc.get_associate(store, operator_id)
    row = svc.create(store, "slicers", {
        "store_id": store_id,
        "assigned_deli_item_id": None,
        "last_sliced_deli_item_id": None,
        "assigned_operator_id": operator_id,
        "asset_tag": asset_tag,
        "sanitation_cycle_limit": limit,
        "sanitation_status": "CLEAN",
        "cuts_since_sanitation": 0,
        "in_use_minutes": 0,
        "last_sanitized_at": store.now(),
        "open_sanitation_cycle_id": None,
    })
    _refresh_operator_assignments(store, store_id)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.slicer(row), 201)


def get_slicer(store, actor, view_args):
    row = svc.get_plain(store, "slicers", view_args["id"])
    return ok_object(store, views.slicer(row))


def list_slicers(store, actor, view_args):
    rows = svc.all_rows(store, "slicers")
    for name, key in (("store_id", "store_id"),
                      ("sanitation_status", "sanitation_status"),
                      ("assigned_operator_id", "assigned_operator_id"),
                      ("assigned_deli_item_id", "assigned_deli_item_id")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.slicer)


def assign_operator(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "slicers", view_args["id"])
    operator_id = as_string(req(payload, "assigned_operator_id"),
                            "assigned_operator_id")
    associate = svc.get_associate(store, operator_id)
    if associate["store_id"] != row["store_id"]:
        fail("ERR_NOT_FOUND")
    if not svc.holds_cert(store, operator_id, "SLICER_OPERATION",
                          deli_item_id=None):
        fail("ERR_ASSOCIATE_NOT_CERTIFIED")
    row["assigned_operator_id"] = operator_id
    svc.touch(store, row)
    _refresh_operator_assignments(store, row["store_id"])
    return ok_object(store, views.slicer(row))


def patch_slicer(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "slicers", view_args["id"])
    svc.check_occ(store, row, opt(payload, "expected_slicer_version"),
                  "expected_slicer_version")
    if "sanitation_cycle_limit" in payload:
        limit = as_int(payload["sanitation_cycle_limit"], "sanitation_cycle_limit")
        if limit < 1:
            invalid("sanitation_cycle_limit must be at least 1.")
        row["sanitation_cycle_limit"] = limit
    svc.touch(store, row)
    return ok_object(store, views.slicer(row))


def _refresh_operator_assignments(store, store_id):
    """A slicer's operator names the associate; reflect it back on the staff row."""
    for associate in svc.all_rows(store, "associates"):
        if associate["store_id"] != store_id:
            continue
        assigned = None
        for slicer in svc.all_rows(store, "slicers"):
            if slicer["store_id"] == store_id and slicer["assigned_operator_id"] == associate["id"]:
                assigned = slicer["id"]
                break
        if associate["assigned_slicer_id"] != assigned:
            associate["assigned_slicer_id"] = assigned
            svc.touch(store, associate)


def _latest_cycle_status(store, slicer_id):
    """The status of the most recently started cycle on this slicer, or None."""
    latest = None
    for cycle in svc.all_rows(store, "sanitation_cycles"):
        if cycle["slicer_id"] != slicer_id:
            continue
        if latest is None or cycle["started_at"] >= latest["started_at"]:
            latest = cycle
    return latest["status"] if latest is not None else None


# ------------------------------------------------------ sanitation cycles -----
def open_cycle(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    slicer_id = as_string(req(payload, "slicer_id"), "slicer_id")
    slicer = svc.get_scoped(store, "slicers", slicer_id, store_id)
    cycle_type = req(payload, "cycle_type")
    if cycle_type not in CYCLE_TYPES:
        invalid("cycle_type must be one of %s." % ", ".join(CYCLE_TYPES))
    cycle_minutes = as_int(opt(payload, "cycle_minutes", default=10), "cycle_minutes")
    buffer_minutes = as_int(opt(payload, "buffer_minutes", default=5), "buffer_minutes")
    if cycle_minutes < 1:
        invalid("cycle_minutes must be at least 1.")
    if buffer_minutes < 0:
        invalid("buffer_minutes must not be negative.")
    cleared_item_id = opt(payload, "allergen_cleared_from_item_id")
    batch_id = opt(payload, "production_batch_id")

    # Priority 13: at most one OPEN cycle per slicer.
    if slicer["open_sanitation_cycle_id"] is not None:
        fail("ERR_SLICER_WINDOW_CONFLICT")

    last_sliced = store.items.get(slicer["last_sliced_deli_item_id"]) \
        if slicer["last_sliced_deli_item_id"] else None

    if cycle_type == "ALLERGEN_CHANGEOVER":
        # The cleared item must be named, and its allergen set must be a
        # proper subset of what the slicer last sliced.
        if cleared_item_id is None:
            fail("ERR_ALLERGEN_CHANGEOVER_REQUIRED")
        cleared = store.items.get(cleared_item_id)
        if cleared is None:
            fail("ERR_NOT_FOUND")
        if last_sliced is None:
            fail("ERR_ALLERGEN_CHANGEOVER_REQUIRED")
        cleared_set = set(cleared["allergen_flags"])
        last_set = set(last_sliced["allergen_flags"])
        if not cleared_set < last_set:
            fail("ERR_ALLERGEN_CHANGEOVER_REQUIRED")
    else:
        # Priority 33: dueness is inclusive at the threshold. PRD §3.2 adds one
        # carve-out in prose: because an aborted cycle keeps its status forever,
        # "a second attempt is made by opening a fresh cycle on the same slicer"
        # and that fresh cycle "is permitted only when the previous attempt is
        # ABORTED and no other cycle on that slicer is open" — so a slicer whose
        # latest cycle was aborted admits a reintroduction without re-testing the
        # threshold that the aborted attempt was consuming.
        reintroducing = (
            slicer["sanitation_status"] == "NEEDS_SANITATION"
            and _latest_cycle_status(store, slicer["id"]) == "ABORTED"
        )
        if not reintroducing and not calc.sanitation_cycle_due(slicer, cycle_type):
            fail("ERR_SANITATION_CYCLE_NOT_DUE")

    if slicer["sanitation_status"] not in ("NEEDS_SANITATION", "CLEAN",
                                           "SANITIZING"):
        fail("ERR_SLICER_NOT_SANITIZED")

    if batch_id is not None:
        svc.get_scoped(store, "batches", batch_id, store_id)

    row = svc.create(store, "sanitation_cycles", {
        "store_id": store_id,
        "slicer_id": slicer_id,
        "production_batch_id": batch_id,
        "allergen_cleared_from_item_id": cleared_item_id,
        "verified_by_associate_id": None,
        "cycle_type": cycle_type,
        "cycle_minutes": cycle_minutes,
        "buffer_minutes": buffer_minutes,
        "started_at": store.now(),
        "completed_at": None,
        "status": "OPEN",
    })
    slicer["sanitation_status"] = "SANITIZING"
    slicer["open_sanitation_cycle_id"] = row["id"]
    svc.touch(store, slicer)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.cycle(row), 201)


def get_cycle(store, actor, view_args):
    row = svc.get_plain(store, "sanitation_cycles", view_args["id"])
    return ok_object(store, views.cycle(row))


def list_cycles(store, actor, view_args):
    rows = svc.all_rows(store, "sanitation_cycles")
    for name, key in (("slicer_id", "slicer_id"), ("store_id", "store_id"),
                      ("cycle_type", "cycle_type"), ("status", "status"),
                      ("production_batch_id", "production_batch_id")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.cycle)


def complete_cycle(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "sanitation_cycles", view_args["id"])
    if row["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    verifier_id = as_string(req(payload, "verified_by_associate_id"),
                            "verified_by_associate_id")
    verifier = svc.get_associate(store, verifier_id)
    if verifier["store_id"] != row["store_id"]:
        fail("ERR_NOT_FOUND")
    # Priority 34: the cycle's occupancy must have elapsed.
    clock = parse_dt(store.now())
    started = parse_dt(row["started_at"])
    if (clock - started).total_seconds() < row["cycle_minutes"] * 60:
        fail("ERR_CYCLE_NOT_COMPLETE")
    # Priority 11: an ALLERGEN_CHANGEOVER cycle needs an ACTIVE
    # ALLERGEN_MANAGEMENT certification on the verifying associate.
    if row["cycle_type"] == "ALLERGEN_CHANGEOVER":
        if not svc.holds_cert(store, verifier_id, "ALLERGEN_MANAGEMENT"):
            fail("ERR_ASSOCIATE_NOT_CERTIFIED")

    row["status"] = "COMPLETE"
    row["completed_at"] = store.now()
    row["verified_by_associate_id"] = verifier_id
    svc.touch(store, row)

    slicer = store.slicers[row["slicer_id"]]
    slicer["sanitation_status"] = "CLEAN"
    slicer["cuts_since_sanitation"] = 0
    slicer["in_use_minutes"] = 0
    slicer["last_sanitized_at"] = store.now()
    slicer["assigned_deli_item_id"] = None
    if row["cycle_type"] == "ALLERGEN_CHANGEOVER":
        # The cycle clears the named item's residue, so the changeover is done.
        slicer["last_sliced_deli_item_id"] = None
    if slicer["open_sanitation_cycle_id"] == row["id"]:
        slicer["open_sanitation_cycle_id"] = None
    svc.touch(store, slicer)
    svc.refresh_certification_counters(store, row["store_id"])
    svc.recompute_store(store, row["store_id"])
    return ok_object(store, views.cycle(row))


def reopen_cycle(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "sanitation_cycles", view_args["id"])
    if row["status"] != "COMPLETE":
        fail("ERR_INVALID_STATE")
    reason = req(payload, "reason")
    as_string(reason, "reason")
    slicer = store.slicers[row["slicer_id"]]
    # The slicer must currently be CLEAN for its claim to be reversible.
    if slicer["sanitation_status"] != "CLEAN":
        fail("ERR_INVALID_STATE")
    # Priority 35: at most two reopenings per slicer per production day.
    reopens = sum(
        1 for c in svc.all_rows(store, "sanitation_cycles")
        if c["slicer_id"] == slicer["id"] and c.get("_reopened")
    )
    if reopens >= MAX_REOPEN_PER_DAY:
        fail("ERR_REOPEN_LIMIT_EXCEEDED")
    row["status"] = "ABORTED"
    row["_reopened"] = True
    svc.touch(store, row)
    slicer["sanitation_status"] = "NEEDS_SANITATION"
    # No credit for an invalid cycle: cuts_since_sanitation is NOT reset.
    svc.touch(store, slicer)
    svc.recompute_store(store, row["store_id"])
    return ok_object(store, views.cycle(row))


def abort_cycle(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "sanitation_cycles", view_args["id"])
    if row["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    as_string(req(payload, "reason"), "reason")
    row["status"] = "ABORTED"
    svc.touch(store, row)
    slicer = store.slicers[row["slicer_id"]]
    slicer["sanitation_status"] = "NEEDS_SANITATION"
    if slicer["open_sanitation_cycle_id"] == row["id"]:
        slicer["open_sanitation_cycle_id"] = None
    svc.touch(store, slicer)
    svc.recompute_store(store, row["store_id"])
    return ok_object(store, views.cycle(row))