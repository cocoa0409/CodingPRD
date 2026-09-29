"""Show classes: offering, judge attachment, closing entries, completion."""
from flask import Blueprint

import agg
from auth import authenticate, must_get, owner_check
import calc
from common import (
    ALL_ROLES, CLASS_LEVELS, DISCIPLINES, GROUP_CODES, POINTS_SCALES,
)
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("classes", __name__)

ROLE_FOR_LEVEL = {
    "BREED": "BREED_JUDGE",
    "GROUP": "GROUP_JUDGE",
    "BEST_IN_SHOW": "BIS_JUDGE",
    "PERFORMANCE": "PERFORMANCE_JUDGE",
}
PARENT_RUNG = {"BREED": "GROUP", "GROUP": "BEST_IN_SHOW"}


@bp.post("/classes")
def create_class():
    authenticate(["ShowSecretary"])
    body = shape.json_body()
    show_id = shape.string_field(body, "show_id")
    class_code = shape.string_field(body, "class_code")
    class_level = shape.string_field(body, "class_level", enum=CLASS_LEVELS)
    entry_limit = shape.int_field(body, "entry_limit", minimum=1)
    breed_code = shape.string_field(body, "breed_code", required=False, default=None)
    group_code = shape.string_field(
        body, "group_code", required=False, default=None, enum=GROUP_CODES
    )
    discipline = shape.string_field(
        body, "discipline", required=False, default=None, enum=DISCIPLINES
    )
    jump_height_cm = shape.int_field(
        body, "jump_height_cm", required=False, default=None,
        allowed=calc.JUMP_HEIGHTS,
    )
    points_scale_override = shape.string_field(
        body, "points_scale_override", required=False, default=None,
        enum=POINTS_SCALES,
    )
    parent_class_id = shape.string_field(
        body, "parent_class_id", required=False, default=None
    )

    if class_level == "BREED":
        shape.require_present(body, "breed_code")
        shape.require_present(body, "group_code")
        shape.forbid(body, "discipline")
        shape.forbid(body, "jump_height_cm")
    elif class_level == "GROUP":
        shape.require_present(body, "group_code")
        shape.forbid(body, "breed_code")
        shape.forbid(body, "discipline")
        shape.forbid(body, "jump_height_cm")
    elif class_level == "BEST_IN_SHOW":
        shape.forbid(body, "breed_code")
        shape.forbid(body, "group_code")
        shape.forbid(body, "discipline")
        shape.forbid(body, "jump_height_cm")
    else:
        shape.require_present(body, "discipline")
        shape.forbid(body, "breed_code")
        shape.forbid(body, "group_code")
        if discipline == "AGILITY":
            shape.require_present(body, "jump_height_cm")
        else:
            shape.forbid(body, "jump_height_cm")

    for existing in store.rows("classes"):
        if existing["show_id"] == show_id and existing["class_code"] == class_code:
            fail("ERR_INVALID_REQUEST",
                 "class_code '%s' is already offered at this show." % class_code)

    show = must_get("shows", show_id)
    parent = None
    if parent_class_id is not None:
        parent = must_get("classes", parent_class_id)

    if show["status"] not in ("SUBMITTED", "APPROVED"):
        fail("ERR_SHOW_NOT_ACCEPTING_ENTRIES",
             "Classes may not be offered while the show is %s." % show["status"])

    if class_level == "PERFORMANCE":
        if show["show_type"] not in ("PERFORMANCE", "COMBINED"):
            fail("ERR_INVALID_REQUEST",
                 "A PERFORMANCE class requires a PERFORMANCE or COMBINED show.")
    else:
        if show["show_type"] not in ("CONFORMATION", "COMBINED"):
            fail("ERR_INVALID_REQUEST",
                 "A conformation class requires a CONFORMATION or COMBINED show.")

    if parent is not None:
        if class_level == "PERFORMANCE" or parent["class_level"] == "PERFORMANCE":
            fail("ERR_PARENT_CLASS_LEVEL_INVALID",
                 "A PERFORMANCE class may neither have a parent nor be one.")
        if parent["show_id"] != show_id:
            fail("ERR_PARENT_CLASS_LEVEL_INVALID",
                 "The parent class belongs to another show.")
        if PARENT_RUNG.get(class_level) != parent["class_level"]:
            fail("ERR_PARENT_CLASS_LEVEL_INVALID",
                 "A %s class may not advance into a %s class."
                 % (class_level, parent["class_level"]))

    rec = store.insert("classes", {
        "show_id": show_id,
        "class_code": class_code,
        "class_level": class_level,
        "breed_code": breed_code,
        "group_code": group_code,
        "discipline": discipline,
        "jump_height_cm": jump_height_cm,
        "entry_limit": entry_limit,
        "points_scale_override": points_scale_override,
        "parent_class_id": parent_class_id,
        "assigned_slot_id": None,
        "status": "OPEN",
        "entry_count": 0,
        "present_count": 0,
        "counted_dog_count": 0,
        "base_points": 0,
        "completed_at": None,
        "final_assessment_done": False,
    })
    return object_response(store.serialize(rec), 201)


@bp.get("/classes/<class_id>")
def read_class(class_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("classes", class_id)))


@bp.get("/classes")
def list_classes():
    authenticate(ALL_ROLES)
    limit, offset = shape.pagination()
    rows = shape.apply_filters(store.rows("classes"), {
        "show_id": "show_id",
        "parent_class_id": "parent_class_id",
        "assigned_slot_id": "assigned_slot_id",
        "class_level": "class_level",
        "status": "status",
    })
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/classes/<class_id>/assign-judge")
def assign_judge(class_id):
    authenticate(["ShowSecretary"])
    cls = must_get("classes", class_id)
    body = shape.json_body()
    slot_id = shape.string_field(body, "slot_id")
    slot = must_get("slots", slot_id)

    for other in store.rows("classes"):
        if other["parent_class_id"] != cls["id"]:
            continue
        if other["assigned_slot_id"] is None:
            continue
        feeder_slot = store.get("slots", other["assigned_slot_id"])
        if feeder_slot is not None and feeder_slot["judge_id"] == slot["judge_id"]:
            fail("ERR_SEGREGATION_CONFLICT",
                 "The judge already officiates a feeder of this class.")

    if slot["slot_status"] != "CONFIRMED":
        fail("ERR_SLOT_NOT_CONFIRMED", "The named panel slot is not CONFIRMED.")
    judge = store.get("judges", slot["judge_id"])
    if judge["status"] != "ACTIVE":
        fail("ERR_JUDGE_NOT_ACTIVE", "The judge's licence is not ACTIVE.")
    if cls["class_level"] in ("BREED", "GROUP", "BEST_IN_SHOW"):
        if cls["group_code"] is not None and cls["group_code"] not in judge["approved_breed_group_codes"]:
            fail("ERR_JUDGE_NOT_APPROVED_FOR_GROUP",
                 "The judge is not approved for group %s." % cls["group_code"])
    if cls["class_level"] == "PERFORMANCE":
        if cls["discipline"] not in judge["approved_performance_disciplines"]:
            fail("ERR_JUDGE_NOT_APPROVED_FOR_DISCIPLINE",
                 "The judge is not approved for %s." % cls["discipline"])
    if ROLE_FOR_LEVEL[cls["class_level"]] != slot["panel_role"]:
        fail("ERR_PANEL_ROLE_MISMATCH",
             "A %s slot may not judge a %s class."
             % (slot["panel_role"], cls["class_level"]))
    if slot["show_id"] != cls["show_id"]:
        fail("ERR_PANEL_ROLE_MISMATCH",
             "The panel slot belongs to another show.")

    set_fields(cls, assigned_slot_id=slot_id)
    store.touch(cls)
    agg.recompute_slot(slot)
    return object_response(store.serialize(cls))


@bp.post("/classes/<class_id>/close-entries")
def close_entries(class_id):
    authenticate(["ShowSecretary"])
    cls = must_get("classes", class_id)
    shape.json_body()
    if cls["status"] != "OPEN":
        fail("ERR_CLASS_NOT_OPEN",
             "A class in %s may not close its entries." % cls["status"])
    show = store.get("shows", cls["show_id"])
    if show["status"] not in ("APPROVED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE",
             "Entries may not be closed while the show is %s." % show["status"])

    previous_charged = show["fee_charged_cents"]
    show_entries = agg.entries_of_show(show["id"])
    counted_statuses = ("CONFIRMED", "CHECKED_IN")
    targets = [
        e for e in agg.entries_of_class(cls["id"])
        if e["entry_status"] in counted_statuses
    ]
    targets.sort(key=calc.entry_rank_key)
    for entry in targets:
        fee_cents, levy_cents = calc.assess_entry_fee(
            entry, cls["class_level"], show_entries, counted_statuses
        )
        set_fields(
            entry,
            entry_fee_cents=fee_cents,
            levy_cents=levy_cents,
            net_fee_cents=fee_cents - entry["fee_refunded_cents"],
            fee_basis="FINAL",
        )
    set_fields(cls, status="CLOSED", final_assessment_done=True)
    store.touch(cls)
    agg.recompute_show_money(show)
    delta = 0 if not targets else show["fee_charged_cents"] - previous_charged
    set_fields(show, fee_assessment_delta_cents=delta)
    return object_response(store.serialize(cls))


@bp.post("/classes/<class_id>/complete")
def complete_class(class_id):
    user_id, _role = authenticate(["Judge"])
    cls = must_get("classes", class_id)
    body = shape.json_body()
    placement_ids = shape.str_list_field(body, "placements")
    placed = [must_get("entries", entry_id) for entry_id in placement_ids]

    slot = None
    if cls["assigned_slot_id"] is not None:
        slot = store.get("slots", cls["assigned_slot_id"])
    if slot is None or slot["judge_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the judge attached to this class may judge it.")
    if cls["status"] not in ("CLOSED", "SCHEDULED"):
        fail("ERR_CLASS_NOT_READY",
             "A class in %s may not be judged." % cls["status"])
    show = store.get("shows", cls["show_id"])
    if show["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE",
             "The show must be IN_PROGRESS to judge a class.")
    if agg.heat_blocked(show, cls):
        fail("ERR_HEAT_RESTRICTION_ACTIVE",
             "A RED advisory blocks performance judging at an outdoor show.")

    expected = min(calc.MAX_PLACEMENTS, cls["present_count"])
    if len(placement_ids) != expected:
        fail("ERR_PLACEMENT_SET_INVALID",
             "placements must hold exactly %d distinct entries." % expected)
    if len(set(placement_ids)) != len(placement_ids):
        fail("ERR_PLACEMENT_SET_INVALID", "placements repeats an entry.")
    for entry in placed:
        if entry["class_id"] != cls["id"] or entry["entry_status"] != "CHECKED_IN":
            fail("ERR_PLACEMENT_SET_INVALID",
                 "Every placement must be a CHECKED_IN entry of this class.")

    if not placement_ids:
        set_fields(
            cls,
            status="ABANDONED",
            counted_dog_count=0,
            base_points=0,
            completed_at=store.now(),
        )
        store.touch(cls)
        agg.complete_published_blocks(cls)
        return object_response(store.serialize(cls))

    counted_dog_count, winner_points = agg.compute_award(cls)
    class_entries = agg.entries_of_class(cls["id"])
    placed_ids = set(placement_ids)
    for position, entry in enumerate(placed, start=1):
        set_fields(
            entry,
            placement=position,
            points_awarded=winner_points if position == 1 else 0,
        )
    for entry in class_entries:
        if entry["id"] not in placed_ids:
            set_fields(entry, points_awarded=0)
        if entry["entry_status"] == "CHECKED_IN":
            set_fields(entry, entry_status="JUDGED")
    set_fields(
        cls,
        status="COMPLETED",
        counted_dog_count=counted_dog_count,
        base_points=winner_points,
        completed_at=store.now(),
    )
    store.touch(cls)
    agg.recompute_class_counts(cls)

    for dog_id in sorted(set(e["dog_id"] for e in class_entries)):
        agg.recompute_dog(store.get("dogs", dog_id))
    agg.recompute_show_points(show)

    winner = placed[0]
    if cls["parent_class_id"] is not None:
        parent = store.get("classes", cls["parent_class_id"])
        promotion = store.insert("entries", agg.entry_fields(
            show_id=cls["show_id"],
            class_id=parent["id"],
            dog_id=winner["dog_id"],
            handler_id=winner["handler_id"],
            source="PROMOTION",
            entry_status="CHECKED_IN",
            armband_number=winner["armband_number"],
            promoted_from_entry_id=winner["id"],
        ))
        agg.recompute_dog(store.get("dogs", promotion["dog_id"]))
        agg.recompute_class_counts(parent)
        if parent["assigned_slot_id"] is not None:
            parent_slot = store.get("slots", parent["assigned_slot_id"])
            if parent_slot is not None:
                agg.recompute_slot(parent_slot)
        agg.recompute_blocks_of_class(parent["id"])
        agg.recompute_show_points(show)

    agg.complete_published_blocks(cls)
    return object_response(store.serialize(cls))
