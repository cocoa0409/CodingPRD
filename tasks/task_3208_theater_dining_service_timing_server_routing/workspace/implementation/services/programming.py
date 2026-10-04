"""Programming events, the pre-show review cycle, and themed menu attachments."""

import db
import errors
from errors import ApiError
from services import core


def create(data):
    aud = core.auditorium(data.get("auditorium_id"))
    requires = data.get("requires_themed_menu", True)
    if requires is None:
        requires = True
    row = {
        "auditorium_id": aud["id"],
        "theme_name": data.get("theme_name") or "",
        "requires_themed_menu": bool(requires),
        "pre_show_content_status": "PRE_SHOW_DRAFT",
        "status": "DRAFT",
        "pre_show_content_version": 1,
        "themed_menu_count": 0,
        "version": 1,
        "updated_at": db.db.now,
    }
    return db.db.register("programming_events", row)


def attach_themed_item(event, data):
    item = core.menu_item(data.get("menu_item_id"))
    price = data.get("theme_price_cents", 0)
    try:
        price = int(price)
    except (TypeError, ValueError):
        price = 0
    if price < 0:
        price = 0
    row = {
        "programming_event_id": event["id"],
        "menu_item_id": item["id"],
        "theme_price_cents": price,
        "is_signature": bool(data.get("is_signature", False)),
    }
    db.db.register("themed_menu_items", row)
    event["themed_menu_count"] = count_items(event["id"])
    core.touch(event)
    return row


def count_items(event_id):
    return len([a for a in db.db.sorted_rows("themed_menu_items")
                if a["programming_event_id"] == event_id])


def signature_count(event_id):
    return len([a for a in db.db.sorted_rows("themed_menu_items")
                if a["programming_event_id"] == event_id and a["is_signature"]])


def submit(event):
    status = event["pre_show_content_status"]
    if status == "PRE_SHOW_DRAFT":
        if event["status"] != "DRAFT":
            raise ApiError(errors.ERR_PROGRAMMING_EVENT_NOT_DRAFT)
        first_submission = True
    elif status in ("PRE_SHOW_REJECTED", "PRE_SHOW_APPROVED"):
        if event["status"] != "DRAFT":
            raise ApiError(errors.ERR_PROGRAMMING_EVENT_NOT_DRAFT)
        first_submission = False
    else:
        raise ApiError(errors.ERR_PRE_SHOW_NOT_RESUBMITTABLE)

    if count_items(event["id"]) < 1:
        raise ApiError(errors.ERR_THEMED_MENU_REQUIRED)

    event["pre_show_content_status"] = "PRE_SHOW_IN_REVIEW"
    if not first_submission:
        event["pre_show_content_version"] = event["pre_show_content_version"] + 1
    core.bump_version(event)
    core.touch(event)
    return event


def approve(event):
    if event["pre_show_content_status"] != "PRE_SHOW_IN_REVIEW":
        raise ApiError(errors.ERR_PRE_SHOW_NOT_IN_REVIEW)
    if signature_count(event["id"]) < 1:
        raise ApiError(errors.ERR_SIGNATURE_ITEM_REQUIRED)
    event["pre_show_content_status"] = "PRE_SHOW_APPROVED"
    core.bump_version(event)
    core.touch(event)
    return event


def reject(event, data=None):
    if event["pre_show_content_status"] != "PRE_SHOW_IN_REVIEW":
        raise ApiError(errors.ERR_PRE_SHOW_NOT_IN_REVIEW)
    event["pre_show_content_status"] = "PRE_SHOW_REJECTED"
    core.bump_version(event)
    core.touch(event)
    return event


def linked_special_showtimes(event):
    return [s for s in db.db.sorted_rows("showtimes")
            if s["auditorium_id"] == event["auditorium_id"]
            and s["content_type"] == "SPECIAL_EVENT"]


def activate(event, data):
    if event["status"] != "DRAFT":
        raise ApiError(errors.ERR_PROGRAMMING_EVENT_NOT_DRAFT)

    expected = data.get("expected_programming_event_version")
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            expected = -1
        if expected != event["version"]:
            raise ApiError(errors.ERR_STALE_PROGRAMMING_EVENT_VERSION)

    if event["pre_show_content_status"] != "PRE_SHOW_APPROVED":
        raise ApiError(errors.ERR_PRE_SHOW_NOT_APPROVED)

    linked = linked_special_showtimes(event)
    if not linked:
        raise ApiError(errors.ERR_NO_LINKED_SHOWTIME)

    event["status"] = "ACTIVATED"
    for st in linked:
        if st["status"] == "SCHEDULED":
            st["content_type"] = "SPECIAL_EVENT"
            core.touch(st)
    core.bump_version(event)
    core.touch(event)
    return event


def cancel(event):
    if event["status"] not in ("DRAFT", "ACTIVATED"):
        raise ApiError(errors.ERR_PROGRAMMING_EVENT_NOT_CANCELLABLE)
    if event["status"] == "ACTIVATED":
        linked = linked_special_showtimes(event)
        if any(s["status"] == "RUNNING" for s in linked):
            raise ApiError(errors.ERR_SHOWTIME_IN_PROGRESS)

    event["status"] = "CANCELLED"
    for st in linked_special_showtimes(event):
        if st["status"] == "SCHEDULED":
            st["status"] = "CANCELLED"
            st["mode"] = "DINING_CLOSED"
            core.bump_version(st)
            core.touch(st)
            core.reconcile_auditorium(core.auditorium(st["auditorium_id"]))
    core.bump_version(event)
    core.touch(event)
    return event