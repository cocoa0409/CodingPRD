"""Ring blocks: planning, publication, rescheduling and the ring timetable."""
from flask import Blueprint

import agg
from auth import authenticate, must_get
import calc
from common import ALL_ROLES, PLANNABLE_BLOCKS
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("blocks", __name__)

PLANNABLE_CLASS_STATUSES = ("OPEN", "CLOSED", "SCHEDULED")
ROLE_FOR_LEVEL = {
    "BREED": "BREED_JUDGE",
    "GROUP": "GROUP_JUDGE",
    "BEST_IN_SHOW": "BIS_JUDGE",
    "PERFORMANCE": "PERFORMANCE_JUDGE",
}


def _on_show_date(instant_text, show_date):
    return instant_text[:10] == show_date


def _blocks_to_supersede(class_id):
    return [
        b for b in agg.blocks_of_class(class_id)
        if b["block_status"] in PLANNABLE_BLOCKS
    ]


@bp.post("/ring-blocks")
def plan_block():
    authenticate(["ShowSecretary"])
    body = shape.json_body()
    show_id = shape.string_field(body, "show_id")
    class_id = shape.string_field(body, "class_id")
    slot_id = shape.string_field(body, "slot_id")
    ring_number = shape.int_field(body, "ring_number", minimum=1, maximum=12)
    block_start_at = shape.instant_field(body, "block_start_at")
    expected_show_version = shape.int_field(body, "expected_show_version", minimum=0)

    show = must_get("shows", show_id)
    cls = must_get("classes", class_id)
    slot = must_get("slots", slot_id)

    if show["status"] not in ("APPROVED", "IN_PROGRESS"):
        fail("ERR_SHOW_NOT_ACCEPTING_ENTRIES",
             "A block may not be planned while the show is %s." % show["status"])
    if cls["show_id"] != show_id:
        fail("ERR_INVALID_STATE", "The class belongs to another show.")
    if cls["status"] not in PLANNABLE_CLASS_STATUSES:
        fail("ERR_INVALID_STATE",
             "A class in %s may not be timetabled." % cls["status"])
    if slot["slot_status"] not in ("PROPOSED", "CONFIRMED"):
        fail("ERR_INVALID_STATE",
             "A slot in %s may not officiate a block." % slot["slot_status"])

    if expected_show_version != show["version"]:
        fail("ERR_STALE_SHOW_VERSION",
             "expected_show_version %d does not match the show's version %d."
             % (expected_show_version, show["version"]))

    if slot["show_id"] != show_id:
        fail("ERR_PANEL_ROLE_MISMATCH", "The panel slot belongs to another show.")
    if ROLE_FOR_LEVEL[cls["class_level"]] != slot["panel_role"]:
        fail("ERR_PANEL_ROLE_MISMATCH",
             "A %s slot may not judge a %s class."
             % (slot["panel_role"], cls["class_level"]))

    if not _on_show_date(block_start_at, show["show_date"]):
        fail("ERR_INVALID_REQUEST",
             "block_start_at must fall on the show's show_date.")

    superseded = _blocks_to_supersede(class_id)
    exclude_ids = set(b["id"] for b in superseded)
    geometry = agg.block_geometry(
        cls,
        block_start_at,
        agg.class_scheduled_dog_count(class_id),
        agg.class_deferred_dog_count(class_id),
    )
    if agg.occupancy_conflict(show_id, ring_number, block_start_at,
                              geometry["block_end_at"], exclude_ids):
        fail("ERR_RING_BLOCK_OVERLAP",
             "Ring %d is already occupied over that interval." % ring_number)
    if agg.rest_conflict(slot["judge_id"], block_start_at,
                         geometry["block_end_at"], exclude_ids):
        fail("ERR_JUDGE_REST_BUFFER_VIOLATION",
             "The judge needs %d minutes between blocks."
             % calc.JUDGE_REST_BUFFER_MINUTES)
    judge = store.get("judges", slot["judge_id"])
    if agg.planning_dog_load(judge["id"], show, cls) > judge["max_daily_dog_count"]:
        fail("ERR_JUDGE_DOG_LIMIT_EXCEEDED",
             "The judge's daily dog limit of %d is exceeded."
             % judge["max_daily_dog_count"])

    superseded_block_id = superseded[-1]["id"] if superseded else None
    had_published = False
    for old in superseded:
        if old["block_status"] == "PUBLISHED":
            had_published = True
        set_fields(old, block_status="SUPERSEDED")

    fields = {
        "show_id": show_id,
        "class_id": class_id,
        "slot_id": slot_id,
        "ring_number": ring_number,
        "block_start_at": block_start_at,
        "block_end_at": geometry["block_end_at"],
        "superseded_block_id": superseded_block_id,
        "scheduled_dog_count": geometry["scheduled_dog_count"],
        "conflict_free_minutes": geometry["conflict_free_minutes"],
        "judging_minutes_estimate": geometry["judging_minutes_estimate"],
        "deferred_dog_count": geometry["deferred_dog_count"],
        "block_status": "PLANNED",
        "published_at": None,
    }
    rec = store.insert("blocks", fields)

    if had_published:
        remaining = [
            b for b in agg.blocks_of_class(class_id)
            if b["block_status"] == "PUBLISHED"
        ]
        if not remaining and cls["status"] == "SCHEDULED":
            set_fields(cls, status="CLOSED")
    if superseded:
        agg.conflict_resolution(show)
    store.touch(show)
    return object_response(store.serialize(rec), 201)


@bp.get("/ring-blocks/<block_id>")
def read_block(block_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("blocks", block_id)))


@bp.get("/ring-blocks")
def list_blocks():
    authenticate(ALL_ROLES)
    limit, offset = shape.pagination()
    rows = shape.apply_filters(store.rows("blocks"), {
        "show_id": "show_id",
        "class_id": "class_id",
        "slot_id": "slot_id",
        "ring_number": "ring_number",
        "block_status": "block_status",
        "superseded_block_id": "superseded_block_id",
    })
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/ring-blocks/<block_id>/publish")
def publish_block(block_id):
    authenticate(["ShowSecretary"])
    block = must_get("blocks", block_id)
    shape.json_body()
    show = store.get("shows", block["show_id"])
    cls = store.get("classes", block["class_id"])
    slot = store.get("slots", block["slot_id"])

    if block["block_status"] != "PLANNED":
        fail("ERR_INVALID_STATE",
             "A block in %s may not be published." % block["block_status"])
    if slot["slot_status"] != "CONFIRMED":
        fail("ERR_SLOT_NOT_CONFIRMED", "The panel slot is not CONFIRMED.")
    if cls["status"] != "CLOSED":
        fail("ERR_INVALID_STATE",
             "The class must be CLOSED to publish its block.")
    if agg.heat_blocked(show, cls):
        fail("ERR_HEAT_RESTRICTION_ACTIVE",
             "A RED advisory blocks performance publication at an outdoor show.")

    exclude_ids = {block["id"]}
    if block["superseded_block_id"] is not None:
        exclude_ids.add(block["superseded_block_id"])
    if agg.occupancy_conflict(block["show_id"], block["ring_number"],
                              block["block_start_at"], block["block_end_at"],
                              exclude_ids):
        fail("ERR_RING_BLOCK_OVERLAP",
             "Ring %d is already occupied over that interval."
             % block["ring_number"])
    if agg.rest_conflict(slot["judge_id"], block["block_start_at"],
                         block["block_end_at"], exclude_ids):
        fail("ERR_JUDGE_REST_BUFFER_VIOLATION",
             "The judge needs %d minutes between blocks."
             % calc.JUDGE_REST_BUFFER_MINUTES)

    set_fields(block, block_status="PUBLISHED", published_at=store.now())
    store.touch(block)
    if cls["status"] == "CLOSED":
        set_fields(cls, status="SCHEDULED")
    agg.conflict_resolution(show)
    return object_response(store.serialize(block))


@bp.post("/ring-blocks/<block_id>/reschedule")
def reschedule_block(block_id):
    authenticate(["ShowSecretary"])
    block = must_get("blocks", block_id)
    body = shape.json_body()
    block_start_at = shape.instant_field(body, "block_start_at")
    expected_show_version = shape.int_field(body, "expected_show_version", minimum=0)
    show = store.get("shows", block["show_id"])
    cls = store.get("classes", block["class_id"])
    slot = store.get("slots", block["slot_id"])

    if block["block_status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE",
             "A block in %s may not be rescheduled." % block["block_status"])
    if expected_show_version != show["version"]:
        fail("ERR_STALE_SHOW_VERSION",
             "expected_show_version %d does not match the show's version %d."
             % (expected_show_version, show["version"]))
    if agg.heat_blocked(show, cls):
        fail("ERR_HEAT_RESTRICTION_ACTIVE",
             "A RED advisory blocks performance rescheduling at an outdoor show.")
    if not _on_show_date(block_start_at, show["show_date"]):
        fail("ERR_INVALID_REQUEST",
             "block_start_at must fall on the show's show_date.")

    geometry = agg.block_geometry(
        cls,
        block_start_at,
        agg.class_scheduled_dog_count(cls["id"]),
        agg.class_deferred_dog_count(cls["id"]),
    )
    exclude_ids = {block["id"]}
    if block["superseded_block_id"] is not None:
        exclude_ids.add(block["superseded_block_id"])
    if agg.occupancy_conflict(block["show_id"], block["ring_number"],
                              block_start_at, geometry["block_end_at"],
                              exclude_ids):
        fail("ERR_RING_BLOCK_OVERLAP",
             "Ring %d is already occupied over that interval."
             % block["ring_number"])
    if agg.rest_conflict(slot["judge_id"], block_start_at,
                         geometry["block_end_at"], exclude_ids):
        fail("ERR_JUDGE_REST_BUFFER_VIOLATION",
             "The judge needs %d minutes between blocks."
             % calc.JUDGE_REST_BUFFER_MINUTES)

    set_fields(block, block_start_at=block_start_at, **geometry)
    store.touch(block)
    agg.conflict_resolution(show)
    store.touch(show)
    return object_response(store.serialize(block))
