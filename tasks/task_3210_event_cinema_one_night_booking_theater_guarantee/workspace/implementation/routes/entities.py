"""Catalogue CRUD: Distributors, Circuits, Theaters and Titles.

These are the four records the whole workflow is built on (PRD §3.1).
"""
from flask import Blueprint

from core import (
    CIRCUIT_CODES,
    CIRCUIT_STATUS,
    CONTENT_TYPES,
    CREDIT_RATINGS,
    DISTRIBUTOR_STATUS,
    BOOKING_STATUS,
    THEATER_STATUS,
    TITLE_STATUS,
    ApiError,
    bad_request,
    body,
    db,
    dump,
    endpoint,
    f_bool,
    f_dt,
    f_enum,
    f_int,
    f_str,
    f_str_list,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    touch,
)
from calcs import bookable_window_days
from services import (
    accredit_circuit,
    archive_title,
    clear_title,
    evaluate_title_expiry,
    go_dark,
    publish_title,
    reactivate_distributor,
    reopen_title_bookings,
    suspend_circuit,
    suspend_distributor,
    unpublish_title,
    withdraw_title,
)
from store import (
    get_or_404,
    recompute_circuit,
    recompute_distributor,
    recompute_title,
)

bp = Blueprint("entities", __name__)


# ---------------------------------------------------------------------------
# Distributors
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/distributors", methods=["POST"])
@endpoint("PlatformOps")
def create_distributor():
    payload = body()
    row = new_row(
        "Distributor",
        distributor_name=f_str(payload, "distributor_name"),
        contact_email=f_str(payload, "contact_email"),
        settlement_currency=f_str(payload, "settlement_currency", required=False) or "USD",
        guarantee_floor_cents=f_int(payload, "guarantee_floor_cents", minimum=0),
        ticket_price_default_cents=f_int(payload, "ticket_price_default_cents", minimum=0),
        status="ACTIVE",
        bookable_title_count=0,
    )
    db.distributors[row["id"]] = row
    return respond_object(dump(row), 201)


@bp.route("/event-cinema/distributors/<dist_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor")
def read_distributor(dist_id):
    row = get_or_404("distributors", dist_id)
    recompute_distributor(row)
    return respond_object(dump(row))


@bp.route("/event-cinema/distributors", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps")
def list_distributors():
    status = q_enum("status", DISTRIBUTOR_STATUS)
    rows = [r for r in db.distributors.values() if status is None or r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    return paginate(rows)


@bp.route("/event-cinema/distributors/<dist_id>/suspend", methods=["POST"])
@endpoint("PlatformOps")
def suspend_distributor_route(dist_id):
    row = get_or_404("distributors", dist_id)
    return respond_object(dump(suspend_distributor(row)))


@bp.route("/event-cinema/distributors/<dist_id>/reactivate", methods=["POST"])
@endpoint("PlatformOps")
def reactivate_distributor_route(dist_id):
    row = get_or_404("distributors", dist_id)
    return respond_object(dump(reactivate_distributor(row)))


@bp.route("/event-cinema/distributors/<dist_id>/bookings", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "Distributor")
def distributor_bookings(dist_id):
    get_or_404("distributors", dist_id)
    status = q_enum("status", BOOKING_STATUS)
    title_ids = {
        t["id"] for t in db.titles.values() if t["distributor_id"] == dist_id
    }
    rows = [
        b
        for b in db.bookings.values()
        if b["title_id"] in title_ids and (status is None or b["status"] == status)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows)


# ---------------------------------------------------------------------------
# Circuits
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/circuits", methods=["POST"])
@endpoint("PlatformOps")
def create_circuit():
    payload = body()
    code = f_str(payload, "circuit_code")
    if any(c["circuit_code"] == code for c in db.circuits.values()):
        raise ApiError("ERR_DUPLICATE_CIRCUIT_CODE")
    row = new_row(
        "Circuit",
        circuit_name=f_str(payload, "circuit_name"),
        circuit_code=code,
        credit_rating=f_enum(payload, "credit_rating", CREDIT_RATINGS),
        settlement_terms=f_enum(payload, "settlement_terms", CIRCUIT_CODES),
        screen_pool_total=f_int(payload, "screen_pool_total", minimum=1),
        on_sale_lead_days_min=f_int(
            payload, "on_sale_lead_days_min", required=False, default=21, minimum=0
        ),
        committed_screens_balance=0,
        status="PENDING",
    )
    db.circuits[row["id"]] = row
    return respond_object(dump(row), 201)


@bp.route("/event-cinema/circuits/<circuit_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor", "Theater")
def read_circuit(circuit_id):
    row = get_or_404("circuits", circuit_id)
    recompute_circuit(row)
    return respond_object(dump(row))


@bp.route("/event-cinema/circuits", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps")
def list_circuits():
    status = q_enum("status", CIRCUIT_STATUS)
    rows = [r for r in db.circuits.values() if status is None or r["status"] == status]
    rows.sort(key=lambda r: (r["circuit_code"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/circuits/<circuit_id>/accredit", methods=["POST"])
@endpoint("PlatformOps")
def accredit_circuit_route(circuit_id):
    row = get_or_404("circuits", circuit_id)
    if row["status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(accredit_circuit(row)))


@bp.route("/event-cinema/circuits/<circuit_id>/suspend", methods=["POST"])
@endpoint("PlatformOps")
def suspend_circuit_route(circuit_id):
    row = get_or_404("circuits", circuit_id)
    if row["status"] != "ACCREDITED":
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(suspend_circuit(row)))


# ---------------------------------------------------------------------------
# Theaters
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/theaters", methods=["POST"])
@endpoint("Exhibitor", "PlatformOps")
def create_theater():
    payload = body()
    circuit_id = f_str(payload, "circuit_id")
    get_or_404("circuits", circuit_id)
    row = new_row(
        "Theater",
        circuit_id=circuit_id,
        theater_name=f_str(payload, "theater_name"),
        city=f_str(payload, "city"),
        state_code=f_str(payload, "state_code"),
        timezone=f_str(payload, "timezone"),
        seats_total=f_int(payload, "seats_total", minimum=1),
        screen_count=f_int(payload, "screen_count", minimum=1),
        showtime_buffer_minutes=f_int(
            payload, "showtime_buffer_minutes", required=False, default=20, minimum=0
        ),
        status="ACTIVE",
        pending_rekey_count=0,
    )
    db.theaters[row["id"]] = row
    return respond_object(dump(row), 201)


@bp.route("/event-cinema/theaters/<theater_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Theater", "Distributor")
def read_theater(theater_id):
    row = get_or_404("theaters", theater_id)
    return respond_object(dump(row))


@bp.route("/event-cinema/theaters", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "Exhibitor", "Theater")
def list_theaters():
    circuit_id = q_str("circuit_id")
    status = q_enum("status", THEATER_STATUS)
    rows = [
        r
        for r in db.theaters.values()
        if (circuit_id is None or r["circuit_id"] == circuit_id)
        and (status is None or r["status"] == status)
    ]
    rows.sort(key=lambda r: (r["state_code"], r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/theaters/<theater_id>/go-dark", methods=["POST"])
@endpoint("Exhibitor", "PlatformOps")
def go_dark_route(theater_id):
    row = get_or_404("theaters", theater_id)
    return respond_object(dump(go_dark(row)))


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------
def _load_title(title_id):
    title = get_or_404("titles", title_id)
    evaluate_title_expiry(title)
    return title


@bp.route("/event-cinema/titles", methods=["POST"])
@endpoint("ProgrammingManager")
def create_title():
    payload = body()
    distributor_id = f_str(payload, "distributor_id")
    get_or_404("distributors", distributor_id)
    rights_start = f_dt(payload, "rights_start_utc")
    rights_end = f_dt(payload, "rights_end_utc")
    if rights_end <= rights_start:
        bad_request("Field 'rights_end_utc' must be strictly after 'rights_start_utc'.")
    row = new_row(
        "Title",
        distributor_id=distributor_id,
        title_name=f_str(payload, "title_name"),
        content_type=f_enum(payload, "content_type", CONTENT_TYPES),
        is_live=f_bool(payload, "is_live"),
        duration_minutes=f_int(payload, "duration_minutes", minimum=1),
        rights_start_utc=rights_start,
        rights_end_utc=rights_end,
        territory_state_codes=f_str_list(payload, "territory_state_codes"),
        max_screen_commitment=f_int(payload, "max_screen_commitment", minimum=1),
        ticket_price_cents=f_int(payload, "ticket_price_cents", required=False, default=None),
        status="DRAFT",
        bookable_window_days=0,
        booking_count=0,
    )
    row["bookable_window_days"] = bookable_window_days(row)
    db.titles[row["id"]] = row
    return respond_object(dump(row), 201)


@bp.route("/event-cinema/titles/<title_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor")
def read_title(title_id):
    title = _load_title(title_id)
    recompute_title(title)
    return respond_object(dump(title))


@bp.route("/event-cinema/titles", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor")
def list_titles():
    distributor_id = q_str("distributor_id")
    status = q_enum("status", TITLE_STATUS)
    rows = [
        r
        for r in db.titles.values()
        if (distributor_id is None or r["distributor_id"] == distributor_id)
        and (status is None or r["status"] == status)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/titles/<title_id>", methods=["PUT"])
@endpoint("ProgrammingManager")
def update_title(title_id):
    title = _load_title(title_id)
    if title["status"] in ("ARCHIVED",):
        raise ApiError("ERR_ALREADY_TERMINAL")
    payload = body()
    if "title_name" in payload:
        title["title_name"] = f_str(payload, "title_name")
    if "ticket_price_cents" in payload and payload["ticket_price_cents"] is not None:
        title["ticket_price_cents"] = f_int(payload, "ticket_price_cents", minimum=0)
    if "max_screen_commitment" in payload and payload["max_screen_commitment"] is not None:
        title["max_screen_commitment"] = f_int(
            payload, "max_screen_commitment", minimum=1
        )
    if "rights_end_utc" in payload and payload["rights_end_utc"] is not None:
        rights_end = f_dt(payload, "rights_end_utc")
        if rights_end <= title["rights_start_utc"]:
            bad_request("Field 'rights_end_utc' must be strictly after 'rights_start_utc'.")
        title["rights_end_utc"] = rights_end
    if "territory_state_codes" in payload and payload["territory_state_codes"] is not None:
        title["territory_state_codes"] = f_str_list(
            payload, "territory_state_codes")
    title["bookable_window_days"] = bookable_window_days(title)
    touch(title)
    return respond_object(dump(title))


@bp.route("/event-cinema/titles/<title_id>/publish", methods=["POST"])
@endpoint("ProgrammingManager")
def publish_title_route(title_id):
    title = _load_title(title_id)
    if title["status"] == "ARCHIVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if title["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(publish_title(title)))


@bp.route("/event-cinema/titles/<title_id>/unpublish", methods=["POST"])
@endpoint("ProgrammingManager")
def unpublish_title_route(title_id):
    title = _load_title(title_id)
    if title["status"] == "ARCHIVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if title["status"] != "BOOKABLE":
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(unpublish_title(title)))


@bp.route("/event-cinema/titles/<title_id>/clear", methods=["POST"])
@endpoint("ProgrammingManager")
def clear_title_route(title_id):
    title = _load_title(title_id)
    if title["status"] == "ARCHIVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if title["status"] != "BOOKABLE":
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(clear_title(title)))


@bp.route("/event-cinema/titles/<title_id>/reopen-bookings", methods=["POST"])
@endpoint("ProgrammingManager")
def reopen_title_route(title_id):
    title = _load_title(title_id)
    if title["status"] == "ARCHIVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if title["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(reopen_title_bookings(title)))


@bp.route("/event-cinema/titles/<title_id>/withdraw", methods=["POST"])
@endpoint("ProgrammingManager")
def withdraw_title_route(title_id):
    title = _load_title(title_id)
    if title["status"] == "ARCHIVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if title["status"] not in ("BOOKABLE", "CLEARED"):
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(withdraw_title(title)))


@bp.route("/event-cinema/titles/<title_id>/archive", methods=["POST"])
@endpoint("ProgrammingManager")
def archive_title_route(title_id):
    title = _load_title(title_id)
    if title["status"] == "ARCHIVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if title["status"] not in ("RIGHTS_EXPIRED", "WITHDRAWN"):
        raise ApiError("ERR_INVALID_STATE")
    return respond_object(dump(archive_title(title)))