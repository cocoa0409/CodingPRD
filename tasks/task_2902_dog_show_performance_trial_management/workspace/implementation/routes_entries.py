"""Entries: submission, armbands, fee assessment, attendance and season."""
from flask import Blueprint

import agg
from auth import authenticate, must_get, owner_check
import calc
from common import ALL_ROLES, ATTENDANCE
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("entries", __name__)

CONFIRM_COUNTED = ("CONFIRMED", "CHECKED_IN", "JUDGED")


def _dog_holds_season(show_id, dog_id):
    for other in store.rows("entries"):
        if other["show_id"] != show_id or other["dog_id"] != dog_id:
            continue
        if other["welfare_status"] == "SEASON_DECLARED":
            return True
    return False


def _mint_armband(show, entry):
    lowest = None
    for other in agg.entries_of_show(show["id"]):
        if other["dog_id"] != entry["dog_id"]:
            continue
        if other["id"] == entry["id"]:
            continue
        number = other["armband_number"]
        if number is not None and (lowest is None or number < lowest):
            lowest = number
    if lowest is not None:
        set_fields(entry, armband_number=lowest)
        return
    number = show["armband_high_water"] + 1
    set_fields(entry, armband_number=number)
    set_fields(show, armband_high_water=number)


@bp.post("/entries")
def create_entry():
    user_id, _role = authenticate(["Handler"])
    body = shape.json_body()
    show_id = shape.string_field(body, "show_id")
    class_id = shape.string_field(body, "class_id")
    dog_id = shape.string_field(body, "dog_id")
    handler_id = shape.string_field(body, "handler_id")

    show = must_get("shows", show_id)
    cls = must_get("classes", class_id)
    dog = must_get("dogs", dog_id)
    handler = must_get("handlers", handler_id)

    owner_check(user_id, handler_id)

    if show["status"] != "APPROVED":
        fail("ERR_SHOW_NOT_ACCEPTING_ENTRIES",
             "Entries are accepted only while the show is APPROVED.")
    if cls["show_id"] != show_id:
        fail("ERR_CLASS_NOT_OPEN", "The class belongs to another show.")
    if cls["status"] != "OPEN":
        fail("ERR_CLASS_NOT_OPEN", "The class is %s." % cls["status"])
    if cls["class_level"] in ("GROUP", "BEST_IN_SHOW"):
        fail("ERR_INVALID_STATE",
             "A %s class is reachable only by promotion." % cls["class_level"])

    if _dog_holds_season(show_id, dog_id):
        fail("ERR_BITCH_IN_SEASON",
             "The dog already holds a season-declared entry at this show.")
    if handler["status"] != "ACTIVE":
        fail("ERR_HANDLER_SUSPENDED", "The handler is not ACTIVE.")
    months = calc.dog_age_months(dog, show["show_date"])
    if months < calc.MIN_ENTRY_AGE_MONTHS:
        fail("ERR_DOG_UNDER_MINIMUM_AGE",
             "The dog is %d whole months old on the show date." % months)

    if cls["class_level"] == "BREED":
        if dog["breed_code"] != cls["breed_code"]:
            fail("ERR_BREED_MISMATCH", "The dog's breed does not match the class.")
    if cls["class_level"] == "PERFORMANCE" and cls["discipline"] == "AGILITY":
        if dog["measurement_status"] == "UNMEASURED":
            fail("ERR_MEASUREMENT_REQUIRED",
                 "An agility entry requires a measuring card.")
        if calc.eligible_jump_height(dog["measured_height_cm"]) != cls["jump_height_cm"]:
            fail("ERR_JUMP_HEIGHT_MISMATCH",
                 "The dog does not map to a jump height of %s cm."
                 % cls["jump_height_cm"])

    clock = store.now()
    if clock < show["entry_open_at"] or clock > show["entry_close_at"]:
        fail("ERR_ENTRY_WINDOW_CLOSED", "The show's entry window is not open.")

    for other in agg.entries_of_class(class_id):
        if other["dog_id"] != dog_id:
            continue
        if other["entry_status"] not in ("WITHDRAWN", "DISQUALIFIED"):
            fail("ERR_DUPLICATE_ENTRY",
                 "The dog already holds a %s entry in this class."
                 % other["entry_status"])

    in_class = len([
        e for e in agg.entries_of_class(class_id)
        if e["entry_status"] in calc.ENTRY_LIMIT_STATUSES
    ])
    if in_class + 1 > cls["entry_limit"]:
        fail("ERR_CLASS_ENTRY_LIMIT_REACHED",
             "The class entry limit of %d is reached." % cls["entry_limit"])
    in_show = len([
        e for e in agg.entries_of_show(show_id)
        if e["entry_status"] in calc.ENTRY_LIMIT_STATUSES
    ])
    if in_show + 1 > show["max_total_entries"]:
        fail("ERR_SHOW_ENTRY_CAP_REACHED",
             "The show entry cap of %d is reached." % show["max_total_entries"])

    rec = store.insert("entries", agg.entry_fields(
        show_id=show_id, class_id=class_id, dog_id=dog_id, handler_id=handler_id
    ))
    agg.recompute_class_counts(cls)
    return object_response(store.serialize(rec), 201)


@bp.get("/entries/<entry_id>")
def read_entry(entry_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("entries", entry_id)))


@bp.get("/entries")
def list_entries():
    authenticate(ALL_ROLES)
    limit, offset = shape.pagination()
    rows = shape.apply_filters(store.rows("entries"), {
        "show_id": "show_id",
        "class_id": "class_id",
        "dog_id": "dog_id",
        "handler_id": "handler_id",
        "promoted_from_entry_id": "promoted_from_entry_id",
        "entry_status": "entry_status",
        "welfare_status": "welfare_status",
        "conflict_deferred": "conflict_deferred",
    })
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/entries/<entry_id>/confirm")
def confirm_entry(entry_id):
    authenticate(["ShowSecretary"])
    entry = must_get("entries", entry_id)
    shape.json_body()
    show = store.get("shows", entry["show_id"])
    cls = store.get("classes", entry["class_id"])
    handler = store.get("handlers", entry["handler_id"])

    if entry["entry_status"] != "RECEIVED":
        fail("ERR_INVALID_STATE",
             "An entry in %s may not be confirmed." % entry["entry_status"])
    if show["status"] not in ("APPROVED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE",
             "The show is %s." % show["status"])
    if cls["status"] != "OPEN":
        fail("ERR_CLASS_NOT_OPEN", "The class is %s." % cls["status"])
    if entry["welfare_status"] == "SEASON_DECLARED":
        fail("ERR_BITCH_IN_SEASON",
             "A season-declared entry may not be confirmed.")
    if entry["welfare_status"] != "CLEAR":
        fail("ERR_INVALID_STATE",
             "Confirmation requires a welfare_status of CLEAR.")
    if handler["status"] != "ACTIVE":
        fail("ERR_HANDLER_SUSPENDED", "The handler is not ACTIVE.")
    if cls["entry_count"] >= cls["entry_limit"]:
        fail("ERR_CLASS_ENTRY_LIMIT_REACHED",
             "The class entry limit of %d is reached." % cls["entry_limit"])

    slot = None
    if cls["assigned_slot_id"] is not None:
        slot = store.get("slots", cls["assigned_slot_id"])
    if slot is not None:
        # The entry is still RECEIVED and therefore uncounted, so the load of
        # this confirmation is the standing load plus this one dog.
        load = agg.judge_daily_load(slot["judge_id"], show["show_date"]) + 1
        if load > slot["assigned_dog_capacity"]:
            fail("ERR_JUDGE_DOG_LIMIT_EXCEEDED",
                 "The judge's daily dog capacity of %d is exceeded."
                 % slot["assigned_dog_capacity"])

    set_fields(entry, entry_status="CONFIRMED")
    _mint_armband(show, entry)
    fee_cents, levy_cents = calc.assess_entry_fee(
        entry, cls["class_level"], agg.entries_of_show(show["id"]), CONFIRM_COUNTED
    )
    set_fields(
        entry,
        entry_fee_cents=fee_cents,
        levy_cents=levy_cents,
        net_fee_cents=fee_cents - entry["fee_refunded_cents"],
        fee_basis="PROVISIONAL",
    )
    store.touch(entry)

    agg.recompute_show_money(show)
    agg.recompute_class_counts(cls)
    if slot is not None:
        agg.recompute_slot(slot)
    agg.recompute_blocks_of_class(cls["id"])
    agg.conflict_resolution(show)
    return object_response(store.serialize(entry))


@bp.post("/entries/<entry_id>/check-in")
def check_in_entry(entry_id):
    authenticate(["ShowSecretary"])
    entry = must_get("entries", entry_id)
    body = shape.json_body()
    attendance = shape.string_field(body, "attendance", enum=ATTENDANCE)
    show = store.get("shows", entry["show_id"])
    cls = store.get("classes", entry["class_id"])

    if entry["entry_status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE",
             "An entry in %s may not be checked in." % entry["entry_status"])
    if show["status"] != "IN_PROGRESS":
        fail("ERR_CLASS_NOT_READY", "The show is %s." % show["status"])
    if cls["status"] not in ("CLOSED", "SCHEDULED"):
        fail("ERR_CLASS_NOT_READY", "The class is %s." % cls["status"])
    if attendance == "PRESENT" and entry["welfare_status"] == "SEASON_DECLARED":
        fail("ERR_BITCH_IN_SEASON",
             "A season-declared entry may not be checked in present.")

    if attendance == "PRESENT":
        set_fields(entry, entry_status="CHECKED_IN")
        store.touch(entry)
        agg.recompute_class_counts(cls)
    else:
        set_fields(entry, entry_status="ABSENT")
        store.touch(entry)
        agg.recompute_class_counts(cls)
        if cls["assigned_slot_id"] is not None:
            slot = store.get("slots", cls["assigned_slot_id"])
            if slot is not None:
                agg.recompute_slot(slot)
        agg.recompute_blocks_of_class(cls["id"])
    return object_response(store.serialize(entry))


@bp.post("/entries/<entry_id>/declare-season")
def declare_season(entry_id):
    user_id, _role = authenticate(["Handler"])
    entry = must_get("entries", entry_id)
    shape.json_body()
    owner_check(user_id, entry["handler_id"])
    show = store.get("shows", entry["show_id"])
    cls = store.get("classes", entry["class_id"])
    dog = store.get("dogs", entry["dog_id"])

    if entry["entry_status"] not in ("CONFIRMED", "CHECKED_IN"):
        fail("ERR_INVALID_STATE",
             "An entry in %s may not declare a season." % entry["entry_status"])
    if entry["welfare_status"] != "CLEAR":
        fail("ERR_INVALID_STATE",
             "The welfare axis is already %s." % entry["welfare_status"])
    was_checked_in = entry["entry_status"] == "CHECKED_IN"
    if was_checked_in:
        if show["status"] != "IN_PROGRESS":
            fail("ERR_INVALID_STATE",
                 "A checked-in entry may declare a season only while the show "
                 "is IN_PROGRESS.")
    elif show["status"] not in ("APPROVED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "The show is %s." % show["status"])
    if dog["sex"] != "BITCH":
        fail("ERR_BITCH_IN_SEASON",
             "Only a bitch may be declared in season.")

    tier_basis_cents = show["fee_collected_cents"]
    retention, net_refund = calc.refund_split(
        entry["entry_fee_cents"], tier_basis_cents
    )
    set_fields(
        entry,
        welfare_status="SEASON_DECLARED",
        entry_status="WITHDRAWN",
        fee_refunded_cents=net_refund,
        net_fee_cents=entry["entry_fee_cents"] - net_refund,
    )
    store.touch(entry)
    set_fields(show, fee_retained_cents=show["fee_retained_cents"] + retention)
    agg.recompute_show_money(show)

    agg.recompute_class_counts(cls)
    if cls["assigned_slot_id"] is not None:
        slot = store.get("slots", cls["assigned_slot_id"])
        if slot is not None:
            agg.recompute_slot(slot)
    agg.recompute_blocks_of_class(cls["id"])
    agg.conflict_resolution(show)
    return object_response(store.serialize(entry))
