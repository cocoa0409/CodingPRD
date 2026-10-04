"""Screenings, attendance reporting and encryption-key custody (§3.4, §3.6)."""
from flask import Blueprint

from core import (
    ISSUANCE_STATUS,
    REPORT_OUTCOMES,
    REVOCATION_REASONS,
    SCREENING_STATE,
    ApiError,
    bad_request,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_int,
    f_str,
    new_row,
    now,
    q_bool,
    q_enum,
    q_str,
    respond_object,
    touch,
)
from calcs import key_aligned, validity_state
from services import validate_occupancy
from store import (
    booking_feed_events,
    find,
    get_or_404,
    line_for_screening,
    paginate,
    recompute_booking,
    recompute_encore_window,
    recompute_line,
    screening_keys,
)

bp = Blueprint("screenings", __name__)


def _key_view(key):
    view = dump(key)
    view["validity_state"] = validity_state(key)
    return view


# ---------------------------------------------------------------------------
# Screenings
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/screenings", methods=["POST"])
@endpoint("PlatformOps", "Exhibitor")
def create_screening():
    payload = body()
    booking_id = f_str(payload, "booking_id")
    booking = get_or_404("bookings", booking_id)
    theater_id = f_str(payload, "theater_id")
    get_or_404("theaters", theater_id)
    auditorium = f_str(payload, "auditorium")
    starts_at = f_dt(payload, "starts_at")
    ends_at = f_dt(payload, "ends_at")
    if ends_at <= starts_at:
        bad_request("Field 'ends_at' must be strictly after 'starts_at'.")
    is_encore = payload.get("is_encore", False)
    if not isinstance(is_encore, bool):
        bad_request("Field 'is_encore' must be a boolean.")

    title = find("titles", booking["title_id"])
    if title is not None:
        if starts_at < title["rights_start_utc"] or starts_at >= title["rights_end_utc"]:
            raise ApiError("ERR_RIGHTS_WINDOW_VIOLATION")

    encore_window_id = None
    if is_encore:
        window = _match_window(booking, starts_at, ends_at)
        if window is None:
            raise ApiError("ERR_INVALID_STATE")
        encore_window_id = window["id"]

    validate_occupancy(booking, theater_id, [(auditorium, starts_at, ends_at)])

    screening = new_row(
        "Screening",
        booking_id=booking_id,
        theater_id=theater_id,
        auditorium=auditorium,
        starts_at=starts_at,
        ends_at=ends_at,
        state="SCHEDULED",
        is_encore=is_encore,
        reported_attendance=None,
        encore_window_id=encore_window_id,
    )
    db.screenings[screening["id"]] = screening
    if encore_window_id is not None:
        window = find("encore_windows", encore_window_id)
        recompute_encore_window(window)
        touch(window)
    recompute_booking(booking)
    return respond_object(dump(screening), 201)


def _match_window(booking, starts_at, ends_at):
    for window in db.encore_windows.values():
        if window["booking_id"] != booking["id"]:
            continue
        if window["status"] != "SCHEDULED":
            continue
        if window["window_start_utc"] <= starts_at and window["window_end_utc"] >= ends_at:
            return window
    return None


@bp.route("/event-cinema/screenings/<screening_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "Exhibitor", "Distributor", "Theater")
def read_screening(screening_id):
    row = get_or_404("screenings", screening_id)
    return respond_object(dump(row))


@bp.route("/event-cinema/screenings", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "Theater", "Distributor")
def list_screenings():
    booking_id = q_str("booking_id")
    theater_id = q_str("theater_id")
    state = q_enum("state", SCREENING_STATE)
    is_encore = q_bool("is_encore")
    rows = [
        r
        for r in db.screenings.values()
        if (booking_id is None or r["booking_id"] == booking_id)
        and (theater_id is None or r["theater_id"] == theater_id)
        and (state is None or r["state"] == state)
        and (is_encore is None or bool(r["is_encore"]) == is_encore)
    ]
    rows.sort(key=lambda r: (r["starts_at"], r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/screenings/<screening_id>/report", methods=["POST"])
@endpoint("Theater")
def report_screening(screening_id):
    screening = get_or_404("screenings", screening_id)
    payload = body()
    attendance = f_int(payload, "reported_attendance", minimum=0)
    outcome = f_enum(payload, "reported_outcome", REPORT_OUTCOMES)

    # PRD §3.6: only `SCREENED` and `SKIPPED_INCOMPLETE` are terminal for a report,
    # and a second report against one of those is `ERR_ALREADY_TERMINAL`. A screening
    # set aside by a cascade (`VOID` by a hold, `SKIPPED_CANCELLED` by a withdrawal,
    # expiry, presale failure or venue going dark) never passes through reporting at
    # all, so attempting one is a transition its current state does not admit and is
    # reported as `ERR_INVALID_STATE` per PRD §2.4.
    if screening["state"] in ("SCREENED", "SKIPPED_INCOMPLETE"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if screening["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    booking = get_or_404("bookings", screening["booking_id"])
    if booking["status"] not in ("ON_SALE", "CONFIRMED", "SETTLED"):
        raise ApiError("ERR_BOOKING_NOT_REPORTABLE")
    line = line_for_screening(screening)
    if line is None or line["exhibit_state"] != "COMMITTED":
        raise ApiError("ERR_BOOKING_LINE_NOT_COMMITTED")
    if now() < screening["ends_at"]:
        raise ApiError("ERR_INVALID_STATE")
    if outcome == "SKIPPED_INCOMPLETE":
        if not any(f["state"] == "CONFIRMED" for f in booking_feed_events(booking)):
            raise ApiError("ERR_INVALID_STATE")

    screening["state"] = outcome
    screening["reported_attendance"] = attendance
    touch(screening)
    recompute_line(line)
    touch(line)
    recompute_booking(booking)
    touch(booking)
    return respond_object(dump(screening))


# ---------------------------------------------------------------------------
# Encryption keys
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/encryption-keys", methods=["POST"])
@endpoint("PlatformOps")
def create_key():
    payload = body()
    screening_id = f_str(payload, "screening_id")
    screening = get_or_404("screenings", screening_id)
    title_id = payload.get("title_id")
    booking = find("bookings", screening["booking_id"])
    if title_id is not None:
        if not isinstance(title_id, str):
            bad_request("Field 'title_id' must be a string.")
        title = find("titles", title_id)
        if title is None:
            raise ApiError("ERR_TITLE_NOT_FOUND")
        if booking is None or title_id != booking["title_id"]:
            bad_request("Field 'title_id' must equal the screening's booking title.")
    not_before = f_dt(payload, "not_valid_before_utc")
    not_after = f_dt(payload, "not_valid_after_utc")
    if not_after <= not_before:
        bad_request("Field 'not_valid_after_utc' must be strictly after 'not_valid_before_utc'.")

    for other in screening_keys(screening):
        if other["issuance_status"] == "REVOKED":
            continue
        if other["not_valid_before_utc"] <= not_after and other["not_valid_after_utc"] >= not_before:
            raise ApiError("ERR_KEY_WINDOW_OVERLAP")

    key = new_row(
        "EncryptionKey",
        screening_id=screening_id,
        title_id=(title_id if title_id is not None else (booking["title_id"] if booking else None)),
        key_ref=None,
        not_valid_before_utc=not_before,
        not_valid_after_utc=not_after,
        issuance_status="PENDING",
        validity_state="NOT_YET_VALID",
        revocation_reason=None,
    )
    key["validity_state"] = validity_state(key)
    db.encryption_keys[key["id"]] = key
    return respond_object(_key_view(key), 201)


@bp.route("/event-cinema/encryption-keys/<key_id>", methods=["GET"])
@endpoint("PlatformOps", "ContentOfficer", "Theater")
def read_key(key_id):
    key = get_or_404("encryption_keys", key_id)
    key["validity_state"] = validity_state(key)
    return respond_object(_key_view(key))


@bp.route("/event-cinema/encryption-keys", methods=["GET"])
@endpoint("PlatformOps", "ContentOfficer")
def list_keys():
    screening_id = q_str("screening_id")
    title_id = q_str("title_id")
    issuance_status = q_enum("issuance_status", ISSUANCE_STATUS)
    rows = [
        r
        for r in db.encryption_keys.values()
        if (screening_id is None or r["screening_id"] == screening_id)
        and (title_id is None or r["title_id"] == title_id)
        and (issuance_status is None or r["issuance_status"] == issuance_status)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for row in rows:
        row["validity_state"] = validity_state(row)
    return paginate(rows)


def _booking_of_key(key):
    screening = find("screenings", key["screening_id"])
    if screening is None:
        return None, None
    return screening, find("bookings", screening["booking_id"])


@bp.route("/event-cinema/keys/<key_id>/issue", methods=["POST"])
@endpoint("PlatformOps", "ContentOfficer")
def issue_key(key_id):
    key = get_or_404("encryption_keys", key_id)
    screening, booking = _booking_of_key(key)
    if key["issuance_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    title = find("titles", key["title_id"]) if key["title_id"] else (
        find("titles", booking["title_id"]) if booking else None
    )
    if booking is not None and title is not None and now() >= title["rights_end_utc"]:
        raise ApiError("ERR_RIGHTS_EXPIRED")
    if screening is None or screening["state"] != "SCHEDULED":
        raise ApiError("ERR_KEY_NOT_ISSUABLE")
    if booking is None or booking["status"] not in ("ON_SALE", "CONFIRMED", "SETTLED"):
        raise ApiError("ERR_KEY_NOT_ISSUABLE")
    verified = any(
        d["booking_id"] == booking["id"] and d["status"] == "VERIFIED"
        for d in db.content_deliveries.values()
    )
    if not verified:
        raise ApiError("ERR_DELIVERY_NOT_VERIFIED")
    # PRD §3.4 states exactly three issuance gates: the screening is still
    # SCHEDULED, the booking is ON_SALE/CONFIRMED/SETTLED, and a package has
    # VERIFIED. It says nothing about the key interval covering the whole
    # screening, so `key_window_alignment` is not an issuance precondition --
    # a deliberately narrow key is valid input. Alignment remains an observable
    # calculation and is exercised through the screening read.

    key["issuance_status"] = "ISSUED"
    key["key_ref"] = "KREF-" + key["id"]
    key["validity_state"] = validity_state(key)
    touch(key)
    return respond_object(_key_view(key))


@bp.route("/event-cinema/keys/<key_id>/revoke", methods=["POST"])
@endpoint("PlatformOps", "ContentOfficer")
def revoke_key(key_id):
    key = get_or_404("encryption_keys", key_id)
    payload = body()
    reason = f_enum(payload, "revocation_reason", REVOCATION_REASONS)
    if key["issuance_status"] == "REVOKED":
        raise ApiError("ERR_INVALID_STATE")
    screening, _booking = _booking_of_key(key)
    if key["issuance_status"] == "ISSUED":
        allowed = screening is not None and screening["state"] in ("SKIPPED_CANCELLED", "VOID")
        if not allowed and not (
            reason == "FEED_LOSS" and screening is not None and screening["state"] == "SCHEDULED"
        ):
            raise ApiError("ERR_INVALID_STATE")

    key["issuance_status"] = "REVOKED"
    key["revocation_reason"] = reason
    key["validity_state"] = validity_state(key)
    touch(key)
    theater = find("theaters", screening["theater_id"]) if screening else None
    if theater is not None:
        theater["pending_rekey_count"] = int(theater["pending_rekey_count"]) + 1
        touch(theater)
    return respond_object(_key_view(key))