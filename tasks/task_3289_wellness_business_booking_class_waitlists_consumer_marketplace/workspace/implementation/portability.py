"""Client-list portability and the export lifecycle."""

import hashlib

from datetime import timedelta

from core import (
    EXPORT_MAX_DOWNLOADS,
    PORTABILITY_ADJUDICATION_WINDOW_HOURS,
    PORTABILITY_COOLDOWN_DAYS,
    PORTABILITY_RESPONSE_WINDOW_HOURS,
    add_days,
    fail,
    fmt,
    new_id,
    now,
)
from commons import mint, refresh_client, refresh_studio, require_gate, touch
from store import (
    BOOKINGS,
    CLIENTS,
    PORTABILITY_REQUESTS,
    STUDIOS,
)


def request_or_404(request_id):
    request = PORTABILITY_REQUESTS.get(request_id)
    if request is None:
        fail("ERR_PORTABILITY_REQUEST_NOT_FOUND")
    return request


def _cooldown_active(studio_id, client_id):
    for other in PORTABILITY_REQUESTS.values():
        if other.get("studio_id") != studio_id:
            continue
        if other.get("requesting_client_id") != client_id:
            continue
        if other.get("status") in ("PENDING", "OBJECTED", "RESOLVED_RELEASE", "EXPORT_ISSUED"):
            continue
        if other.get("status") not in (
            "RESOLVED_DENIED",
            "EXPIRED",
            "WITHDRAWN",
        ):
            continue
        decided = other.get("decided_at") or other.get("updated_at")
        if decided is not None and now() <= decided + timedelta(
            days=PORTABILITY_COOLDOWN_DAYS
        ):
            return True
    return False


def create_request(body):
    studio = STUDIOS.get(body.get("studio_id"))
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    client = CLIENTS.get(body.get("requesting_client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    require_gate(studio, "client_portability_export")
    if _cooldown_active(studio["id"], client["id"]):
        fail("ERR_PORTABILITY_COOLDOWN_ACTIVE")

    request = mint(
        PORTABILITY_REQUESTS,
        {
            "studio_id": studio["id"],
            "requesting_client_id": client["id"],
            "dispute_reason": body.get("dispute_reason"),
            "requested_at": now(),
            "decided_at": None,
            "export_grant_id": None,
            "export_manifest": None,
            "export_download_count": 0,
            "status": "PENDING",
            "objection_basis": None,
        },
    )
    studio["data_ownership_state"] = "PORTABILITY_PENDING"
    touch(studio)
    return request


def _assert_undecided(request):
    if request.get("status") in (
        "RESOLVED_RELEASE",
        "RESOLVED_DENIED",
        "EXPORT_ISSUED",
        "EXPIRED",
        "WITHDRAWN",
    ):
        fail("ERR_PORTABILITY_ALREADY_DECIDED")


def _within_response_window(request):
    requested_at = request.get("requested_at")
    return now() < requested_at + timedelta(hours=PORTABILITY_RESPONSE_WINDOW_HOURS)


def _within_adjudication_window(request):
    requested_at = request.get("requested_at")
    return now() <= requested_at + timedelta(hours=PORTABILITY_ADJUDICATION_WINDOW_HOURS)


def object_request(request, body):
    _assert_undecided(request)
    if request.get("status") != "PENDING":
        fail("ERR_INVALID_STATE", "Only a pending request may be objected.")
    if not _within_response_window(request):
        fail("ERR_PORTABILITY_WINDOW_CLOSED")
    request["status"] = "OBJECTED"
    request["objection_basis"] = body.get("objection_basis")
    touch(request)
    return request


def _grant_effects(request, include_booking_history, include_financial_history):
    studio = STUDIOS.get(request.get("studio_id"))
    client = CLIENTS.get(request.get("requesting_client_id"))
    request["status"] = "RESOLVED_RELEASE"
    request["decided_at"] = now()
    request["export_grant_id"] = "grant_" + new_id().replace("-", "")
    manifest = build_manifest(
        studio, client, include_booking_history, include_financial_history
    )
    request["export_manifest"] = manifest
    if studio is not None:
        studio["data_ownership_state"] = "PORTABILITY_GRANTED"
        touch(studio)
    if client is not None:
        client["status"] = "PORTABILITY_HOLD"
        touch(client)
        refresh_client(client)


def build_manifest(studio, client, include_booking_history, include_financial_history):
    source_ids = [studio["id"]] if studio else []
    records = []
    for other in CLIENTS.values():
        if studio is not None and other.get("home_studio_id") == studio["id"]:
            records.append(other["id"])
    digest_src = "|".join(sorted(records)) + "|" + (client["id"] if client else "")
    digest = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()
    return {
        "record_count": len(records),
        "record_digest": digest,
        "source_studio_ids": source_ids,
        "generated_at_utc": fmt(now()),
        "booking_history_included": bool(include_booking_history),
        "financial_history_included": bool(include_financial_history),
        "requesting_client_id": client["id"] if client else None,
    }


def resolve_release(request, body):
    _assert_undecided(request)
    if request.get("status") != "PENDING":
        fail("ERR_INVALID_STATE", "Only a pending request may be released.")
    client = CLIENTS.get(request.get("requesting_client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    if client.get("outstanding_fee_cents", 0) != 0:
        fail("ERR_CLIENT_BALANCE_OUTSTANDING")
    studio = STUDIOS.get(request.get("studio_id"))
    if studio is not None and studio.get("data_ownership_state") not in (
        "OWNED",
        "PORTABILITY_PENDING",
    ):
        fail("ERR_INVALID_STATE", "The studio ownership state blocks a release.", 409)
    _grant_effects(
        request,
        body.get("include_booking_history"),
        body.get("include_financial_history"),
    )
    touch(request)
    return request


def resolve_deny(request, body):
    _assert_undecided(request)
    if request.get("status") != "PENDING":
        fail("ERR_INVALID_STATE", "Only a pending request may be denied.")
    dispute_reason = request.get("dispute_reason")
    reason = body.get("dispute_reason") or dispute_reason
    if not reason:
        fail("ERR_INVALID_STATE", "A denial requires a recorded basis.", 409)
    request["status"] = "RESOLVED_DENIED"
    request["decided_at"] = now()
    if reason:
        request["dispute_reason"] = reason
    studio = STUDIOS.get(request.get("studio_id"))
    if studio is not None:
        studio["data_ownership_state"] = "OWNED"
        touch(studio)
    touch(request)
    return request


def adjudicate(request, body):
    _assert_undecided(request)
    if request.get("status") != "OBJECTED":
        fail("ERR_INVALID_STATE", "Only an objected request may be adjudicated.")
    if not _within_adjudication_window(request):
        fail("ERR_PORTABILITY_WINDOW_CLOSED")
    decision = body.get("decision")
    if decision == "RELEASE":
        _grant_effects(
            request,
            body.get("include_booking_history"),
            body.get("include_financial_history"),
        )
        request["objection_founded"] = False
    elif decision == "DENY":
        request["status"] = "RESOLVED_DENIED"
        request["decided_at"] = now()
        studio = STUDIOS.get(request.get("studio_id"))
        if studio is not None:
            studio["data_ownership_state"] = "OWNED"
            touch(studio)
    else:
        fail("ERR_INVALID_STATE", "decision must be RELEASE or DENY.", 409)
    touch(request)
    return request


def issue_export(request):
    if request.get("export_download_count", 0) >= EXPORT_MAX_DOWNLOADS:
        fail("ERR_EXPORT_DOWNLOAD_CAP")
    if request.get("status") != "RESOLVED_RELEASE":
        fail("ERR_EXPORT_NOT_GRANTED")
    # PRD §3.10: a lapsed EXPORT_ISSUED row is walked back to RESOLVED_RELEASE
    # precisely so the export "can be generated again"; the 72-hour window is a
    # download window, so issuance itself is not refused on elapsed time.
    if request.get("export_grant_id") is None:
        request["export_grant_id"] = "grant_" + new_id().replace("-", "")
    request["status"] = "EXPORT_ISSUED"
    manifest = request.get("export_manifest") or {}
    manifest["generated_at_utc"] = fmt(now())
    request["export_manifest"] = manifest
    touch(request)
    studio = STUDIOS.get(request.get("studio_id"))
    if studio is not None:
        refresh_studio(studio)
    return request


def download_export(request):
    if request.get("status") != "EXPORT_ISSUED":
        fail("ERR_EXPORT_NOT_GRANTED")
    if request.get("export_download_count", 0) >= EXPORT_MAX_DOWNLOADS:
        fail("ERR_EXPORT_DOWNLOAD_CAP")
    request["export_download_count"] = request.get("export_download_count", 0) + 1
    touch(request)
    if request["export_download_count"] >= EXPORT_MAX_DOWNLOADS:
        client = CLIENTS.get(request.get("requesting_client_id"))
        if client is not None:
            client["status"] = "PORTED"
            touch(client)
        studio = STUDIOS.get(request.get("studio_id"))
        if studio is not None:
            studio["data_ownership_state"] = "EXPORT_CLOSED"
            touch(studio)
    else:
        studio = STUDIOS.get(request.get("studio_id"))
        if studio is not None:
            refresh_studio(studio)
    return request


def withdraw(request, actor_client_id):
    if request.get("status") not in ("PENDING", "OBJECTED"):
        fail("ERR_PORTABILITY_ALREADY_DECIDED")
    if request.get("requesting_client_id") != actor_client_id:
        fail("ERR_UNAUTHORIZED_ROLE", "Only the requesting client may withdraw.")
    request["status"] = "WITHDRAWN"
    request["decided_at"] = now()
    studio = STUDIOS.get(request.get("studio_id"))
    if studio is not None:
        studio["data_ownership_state"] = "OWNED"
        touch(studio)
    touch(request)
    return request


def portability_clock_transitions():
    for request in list(PORTABILITY_REQUESTS.values()):
        status = request.get("status")
        if status == "PENDING" and not _within_response_window(request):
            _grant_effects(request, None, None)
            request["decided_at"] = now()
            studio = STUDIOS.get(request.get("studio_id"))
            if studio is not None:
                studio["suspension_reason"] = "PORTABILITY_NONRESPONSE"
                touch(studio)
            touch(request)
        elif status == "OBJECTED" and not _within_adjudication_window(request):
            request["status"] = "RESOLVED_DENIED"
            request["decided_at"] = now()
            studio = STUDIOS.get(request.get("studio_id"))
            if studio is not None:
                studio["data_ownership_state"] = "OWNED"
                touch(studio)
            touch(request)
        elif status == "EXPORT_ISSUED":
            decided_at = request.get("decided_at")
            if decided_at is not None and now() > decided_at + timedelta(hours=72):
                if request.get("export_download_count", 0) == 0:
                    request["status"] = "RESOLVED_RELEASE"
                    request["export_grant_id"] = None
                    request["export_manifest"] = None
                    touch(request)
        elif status == "RESOLVED_RELEASE":
            decided_at = request.get("decided_at")
            if (
                decided_at is not None
                and now() > decided_at + timedelta(hours=72)
                and request.get("export_manifest") is None
            ):
                request["status"] = "EXPIRED"
                request["decided_at"] = now()
                studio = STUDIOS.get(request.get("studio_id"))
                if studio is not None:
                    studio["data_ownership_state"] = "OWNED"
                    touch(studio)
                touch(request)