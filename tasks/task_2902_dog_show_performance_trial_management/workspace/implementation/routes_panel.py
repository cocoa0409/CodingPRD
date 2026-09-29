"""Judge panel slots."""
from flask import Blueprint

import agg
from auth import authenticate, must_get, owner_check
import calc
from common import ALL_ROLES, PANEL_ROLES
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("panel", __name__)

GROUP_ROLES = ("BREED_JUDGE", "GROUP_JUDGE", "BIS_JUDGE")


def _slots_at_show(judge_id, show_id):
    return [
        s for s in agg.slots_of_judge(judge_id)
        if s["show_id"] == show_id and s["slot_status"] in ("PROPOSED", "CONFIRMED")
    ]


def _confirmed_elsewhere(judge_id, show):
    for slot in agg.slots_of_judge(judge_id):
        if slot["slot_status"] != "CONFIRMED":
            continue
        if slot["show_id"] == show["id"]:
            continue
        other = store.get("shows", slot["show_id"])
        if other is not None and other["show_date"] == show["show_date"]:
            return True
    return False


@bp.post("/panel-slots")
def propose_slot():
    authenticate(["ShowSecretary"])
    body = shape.json_body()
    show_id = shape.string_field(body, "show_id")
    judge_id = shape.string_field(body, "judge_id")
    panel_role = shape.string_field(body, "panel_role", enum=PANEL_ROLES)
    expected_judge_version = shape.int_field(
        body, "expected_judge_version", minimum=0
    )
    show = must_get("shows", show_id)
    judge = must_get("judges", judge_id)
    if show["status"] not in ("SUBMITTED", "APPROVED"):
        fail("ERR_SHOW_NOT_ACCEPTING_ENTRIES",
             "A panel may not be assembled while the show is %s." % show["status"])
    if expected_judge_version != judge["version"]:
        fail("ERR_STALE_JUDGE_VERSION",
             "expected_judge_version does not match the judge's version.")
    if judge["status"] != "ACTIVE":
        fail("ERR_JUDGE_NOT_ACTIVE", "The judge's licence is not ACTIVE.")
    if panel_role in GROUP_ROLES and not judge["approved_breed_group_codes"]:
        fail("ERR_JUDGE_NOT_APPROVED_FOR_GROUP",
             "The judge holds no approved breed groups.")
    if panel_role == "PERFORMANCE_JUDGE" and not judge["approved_performance_disciplines"]:
        fail("ERR_JUDGE_NOT_APPROVED_FOR_DISCIPLINE",
             "The judge holds no approved performance disciplines.")
    if len(_slots_at_show(judge_id, show_id)) >= calc.MAX_SLOTS_PER_JUDGE_PER_SHOW:
        fail("ERR_JUDGE_ASSIGNMENT_LIMIT",
             "The judge already holds the maximum number of slots at this show.")
    if _confirmed_elsewhere(judge_id, show):
        fail("ERR_JUDGE_ASSIGNMENT_LIMIT",
             "The judge already works another show on that date.")
    capacity = min(judge["max_daily_dog_count"], calc.MAX_DOGS_PER_JUDGE_PER_DAY)
    rec = store.insert("slots", {
        "show_id": show_id,
        "judge_id": judge_id,
        "panel_role": panel_role,
        "slot_status": "PROPOSED",
        "responded_at": None,
        "decline_reason": None,
        "assigned_class_count": 0,
        "assigned_dog_capacity": capacity,
    })
    store.touch(judge)
    return object_response(store.serialize(rec), 201)


@bp.get("/panel-slots/<slot_id>")
def read_slot(slot_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("slots", slot_id)))


@bp.get("/panel-slots")
def list_slots():
    authenticate(ALL_ROLES)
    limit, offset = shape.pagination()
    rows = shape.apply_filters(store.rows("slots"), {
        "show_id": "show_id",
        "judge_id": "judge_id",
        "slot_status": "slot_status",
        "panel_role": "panel_role",
    })
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/panel-slots/<slot_id>/respond")
def respond_slot(slot_id):
    user_id, _role = authenticate(["Judge"])
    slot = must_get("slots", slot_id)
    body = shape.json_body()
    decision = shape.string_field(body, "decision", enum=["ACCEPT", "DECLINE"])
    decline_reason = shape.string_field(
        body, "decline_reason", required=False, default=None, allow_blank=True
    )
    owner_check(user_id, slot["judge_id"])
    if slot["slot_status"] != "PROPOSED":
        fail("ERR_INVALID_STATE",
             "A slot in %s may not be answered." % slot["slot_status"])
    judge = store.get("judges", slot["judge_id"])
    show = store.get("shows", slot["show_id"])
    if decision == "ACCEPT":
        if _confirmed_elsewhere(slot["judge_id"], show):
            fail("ERR_JUDGE_ASSIGNMENT_LIMIT",
                 "The judge already works another show on that date.")
        set_fields(slot, slot_status="CONFIRMED", responded_at=store.now())
        store.touch(slot)
        agg.recompute_judge_slot_count(judge)
        store.touch(judge)
    else:
        set_fields(
            slot,
            slot_status="DECLINED",
            responded_at=store.now(),
            decline_reason=decline_reason,
        )
        store.touch(slot)
        store.touch(judge)
        for block in store.rows("blocks"):
            if block["slot_id"] == slot["id"] and block["block_status"] == "PLANNED":
                set_fields(block, block_status="SUPERSEDED")
    return object_response(store.serialize(slot))
