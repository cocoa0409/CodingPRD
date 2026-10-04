"""The Flask application: envelope handling, error translation, RBAC and every
route of the declared endpoint table."""

import os

from flask import Flask, g, jsonify, request

from core import (
    ApiError,
    ROLES,
    TIERS,
    USER_ID_HEADER,
    USER_ROLE_HEADER,
    fail,
    fmt,
    now,
    parse_dt,
    set_clock,
)
from envelope import array_response, error_body, object_response, read_pagination
from serialize import serialize
import routes_common as rc

import bookings as bookings_mod
import lifecycle
import marketplace
import memberships
import networks
import packs
import payroll
import portability
import subscriptions
import waitlist
from commons import (
    assert_studio_owned,
    derive_studio_status,
    feature_gates,
    mint,
    refresh_client,
    refresh_session_counters,
    refresh_staff_accrued,
    refresh_studio,
    refresh_subscription,
    require_gate,
    touch,
)
from store import (
    BENEFIT_NETWORKS,
    BOOKINGS,
    CLASS_PACKS,
    CLASS_SESSIONS,
    CLASS_TEMPLATES,
    CLIENTS,
    COMMISSION_ENTRIES,
    MEMBERSHIPS,
    PAYROLL_PERIODS,
    PORTABILITY_REQUESTS,
    STAFF_MEMBERS,
    STUDIOS,
    SUBSCRIPTIONS,
    TIERS as TIER_ROWS,
    WAITLIST_ENTRIES,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, status = error_body(exc.error_id, exc.message), exc.status
    return jsonify(body), status


@app.errorhandler(404)
def handle_not_found(_exc):
    body = error_body("ERR_CLASS_SESSION_NOT_FOUND", "The route does not exist.")
    return jsonify(body), 404


@app.errorhandler(405)
def handle_method(_exc):
    body = error_body("ERR_INVALID_STATE", "Method not allowed.")
    return jsonify(body), 405


@app.errorhandler(500)
def handle_server_error(exc):
    body = error_body("ERR_INVALID_STATE", str(exc))
    return jsonify(body), 500


def respond(pair):
    payload, status = pair
    return jsonify(payload), status


def guard(*roles):
    return rc.require_roles(*roles)


def guard_anon(*roles):
    return rc.require_roles_or_anonymous(*roles)


STUDIO_KEY = "studio_id"


@app.before_request
def enforce_studio_ownership():
    """A StudioOwner's X-User-ID is the id of the acting Studio; acting on any
    resource that references a different studio is ERR_STUDIO_NOT_OWNED
    (PRD §2.1).  PlatformAdmin is explicitly exempt."""
    role = request.headers.get(USER_ROLE_HEADER)
    actor_id = request.headers.get(USER_ID_HEADER)
    if role != "StudioOwner" or not actor_id:
        return None
    referenced = request.view_args.get(STUDIO_KEY) if request.view_args else None
    if referenced and referenced != actor_id:
        fail("ERR_STUDIO_NOT_OWNED")
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        for key in ("studio_id", "home_studio_id", "source_studio_id"):
            value = payload.get(key)
            if value and value != actor_id:
                fail("ERR_STUDIO_NOT_OWNED")
    # resource-id paths: resolve the owning studio when the row exists
    args = request.view_args or {}
    for name, collection in (
        ("sub_id", SUBSCRIPTIONS),
        ("session_id", CLASS_SESSIONS),
        ("booking_id", BOOKINGS),
        ("template_id", CLASS_TEMPLATES),
        ("staff_id", STAFF_MEMBERS),
        ("pack_id", CLASS_PACKS),
        ("membership_id", MEMBERSHIPS),
        ("period_id", PAYROLL_PERIODS),
        ("entry_id", WAITLIST_ENTRIES),
        ("client_id", CLIENTS),
        ("request_id", PORTABILITY_REQUESTS),
    ):
        row_id = args.get(name)
        if not row_id:
            continue
        row = collection.get(row_id)
        if row is None:
            continue
        owner = row.get("studio_id")
        if name == "client_id":
            owner = row.get("home_studio_id")
        if owner and owner != actor_id:
            fail("ERR_STUDIO_NOT_OWNED")
    return None


# ---------------------------------------------------------------------------
# Subscription tiers
# ---------------------------------------------------------------------------


@app.get("/wellness/subscription-tiers")
def list_tiers():
    limit, offset = read_pagination(request.args)
    rows = sorted(TIER_ROWS.values(), key=lambda r: (r.get("tier_rank", 0), r.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


@app.post("/wellness/subscription-tiers")
def post_tier():
    guard("PlatformAdmin")
    row = subscriptions.define_tier(rc.body())
    return respond(rc.ok_object(row, status=201))


# ---------------------------------------------------------------------------
# Studios and subscriptions
# ---------------------------------------------------------------------------


@app.post("/wellness/studios")
def post_studio():
    guard("Anonymous", "PlatformAdmin")
    studio = subscriptions.signup_studio(rc.body())
    refresh_studio(studio)
    return respond(rc.ok_object(studio, status=201))


@app.get("/wellness/studios")
def list_studios():
    _actor, role = guard("PlatformAdmin", "StudioOwner")
    limit, offset = read_pagination(request.args)
    rows = list(STUDIOS.values())
    subscription_id = rc.str_arg("subscription_id")
    if subscription_id:
        rows = [s for s in rows if s.get("subscription_id") == subscription_id]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    if role == "StudioOwner":
        rows = [s for s in rows if s["id"] == _actor]
    rows.sort(key=lambda s: s.get("created_at"))
    for studio in rows:
        refresh_studio(studio)
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>")
def get_studio(studio_id):
    actor, role = guard("PlatformAdmin", "StudioOwner", "Client")
    studio = lifecycle.studio_or_404(studio_id)
    refresh_studio(studio)
    return respond(rc.ok_object(studio))


@app.post("/wellness/studios/<studio_id>/cancel")
def cancel_studio(studio_id):
    actor, role = guard("PlatformAdmin", "StudioOwner")
    studio = lifecycle.studio_or_404(studio_id)
    assert_studio_owned(role, actor, studio_id)
    lifecycle.close_studio(studio)
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None:
        subscription["status"] = "CANCELLED"
        subscription["dunning_stage"] = "CANCELLED"
        touch(subscription)
        refresh_subscription(subscription)
    refresh_studio(studio)
    return respond(rc.ok_object(studio))


@app.get("/wellness/studios/<studio_id>/business-subscriptions")
def studio_subscriptions(studio_id):
    guard("PlatformAdmin", "StudioOwner")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [s for s in SUBSCRIPTIONS.values() if s.get("studio_id") == studio_id]
    rows.sort(key=lambda s: s.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/subscriptions/<sub_id>")
def get_subscription(sub_id):
    guard("PlatformAdmin", "StudioOwner")
    subscription = SUBSCRIPTIONS.get(sub_id)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    refresh_subscription(subscription)
    return respond(rc.ok_object(subscription))


@app.post("/wellness/subscriptions/<sub_id>/advance-renewal")
def post_advance_renewal(sub_id):
    guard("PlatformAdmin", "StudioOwner")
    subscription = SUBSCRIPTIONS.get(sub_id)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    rc.occ(subscription, "expected_subscription_version")
    subscriptions.advance_renewal(subscription, rc.body())
    return respond(rc.ok_object(subscription))


@app.post("/wellness/subscriptions/<sub_id>/change-tier")
def post_change_tier(sub_id):
    guard("PlatformAdmin")
    subscription = SUBSCRIPTIONS.get(sub_id)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    rc.occ(subscription, "expected_subscription_version")
    subscriptions.change_tier(subscription, rc.body())
    return respond(rc.ok_object(subscription))


@app.post("/wellness/subscriptions/<sub_id>/suspend")
def post_suspend(sub_id):
    guard("PlatformAdmin", "StudioOwner")
    subscription = SUBSCRIPTIONS.get(sub_id)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    rc.occ(subscription, "expected_subscription_version")
    subscriptions.suspend_subscription(subscription, rc.body())
    return respond(rc.ok_object(subscription))


@app.post("/wellness/subscriptions/<sub_id>/resume")
def post_resume(sub_id):
    guard("PlatformAdmin", "StudioOwner")
    subscription = SUBSCRIPTIONS.get(sub_id)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    rc.occ(subscription, "expected_subscription_version")
    subscriptions.resume_subscription(subscription, rc.body())
    return respond(rc.ok_object(subscription))


@app.post("/wellness/subscriptions/<sub_id>/cancel")
def post_cancel_subscription(sub_id):
    guard("PlatformAdmin", "StudioOwner")
    subscription = SUBSCRIPTIONS.get(sub_id)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    rc.occ(subscription, "expected_subscription_version")
    subscriptions.cancel_subscription(subscription, rc.body())
    return respond(rc.ok_object(subscription))


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


@app.post("/wellness/staff-members")
def post_staff():
    guard("PlatformAdmin", "StudioOwner")
    staff = subscriptions.create_staff(rc.body())
    return respond(rc.ok_object(staff, status=201))


@app.get("/wellness/staff-members")
def list_staff():
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    limit, offset = read_pagination(request.args)
    rows = list(STAFF_MEMBERS.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [s for s in rows if s.get("studio_id") == studio_id]
    template_id = rc.str_arg("primary_class_template_id")
    if template_id:
        rows = [s for s in rows if s.get("primary_class_template_id") == template_id]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    rows.sort(key=lambda s: s.get("created_at"))
    for staff in rows:
        refresh_staff_accrued(staff)
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/staff-members/<staff_id>")
def get_staff(staff_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    staff = subscriptions.staff_or_404(staff_id)
    refresh_staff_accrued(staff)
    return respond(rc.ok_object(staff))


@app.post("/wellness/staff-members/<staff_id>/restrict-to-substitute")
def post_restrict(staff_id):
    guard("StudioOwner")
    staff = subscriptions.staff_or_404(staff_id)
    subscriptions.restrict_to_substitute(staff)
    return respond(rc.ok_object(staff))


@app.post("/wellness/staff-members/<staff_id>/reinstate")
def post_reinstate(staff_id):
    guard("StudioOwner")
    staff = subscriptions.staff_or_404(staff_id)
    subscriptions.reinstate(staff)
    return respond(rc.ok_object(staff))


@app.post("/wellness/staff-members/<staff_id>/deactivate")
def post_deactivate(staff_id):
    guard("StudioOwner")
    staff = subscriptions.staff_or_404(staff_id)
    subscriptions.deactivate(staff, rc.body())
    return respond(rc.ok_object(staff))


@app.get("/wellness/studios/<studio_id>/staff-members")
def studio_staff(studio_id):
    guard("PlatformAdmin", "StudioOwner")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [s for s in STAFF_MEMBERS.values() if s.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    rows.sort(key=lambda s: s.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


@app.post("/wellness/clients")
def post_client():
    guard("PlatformAdmin", "StudioOwner", "Client")
    body = rc.body()
    studio = lifecycle.studio_or_404(body.get("home_studio_id"))
    home_state = body.get("home_state_code")
    if home_state not in ("CA", "NY", "TX", "WA", "CO"):
        fail("ERR_INVALID_STATE", "home_state_code is outside the state vocabulary.", 409)
    for other in CLIENTS.values():
        if (
            other.get("home_studio_id") == studio["id"]
            and other.get("email")
            and other.get("email") == body.get("email")
        ):
            fail("ERR_CLIENT_EMAIL_CONFLICT")
    client = mint(
        CLIENTS,
        {
            "home_studio_id": studio["id"],
            "display_name": body.get("display_name"),
            "email": body.get("email"),
            "home_state_code": home_state,
            "status": "ACTIVE",
            "no_show_strike_count": 0,
            "late_cancel_count": 0,
            "outstanding_fee_cents": 0,
        },
    )
    refresh_studio(studio)
    return respond(rc.ok_object(client, status=201))


@app.get("/wellness/clients")
def list_clients():
    guard("PlatformAdmin", "StudioOwner", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(CLIENTS.values())
    studio_id = rc.str_arg("home_studio_id")
    if studio_id:
        rows = [c for c in rows if c.get("home_studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [c for c in rows if c.get("status") == status]
    rows.sort(key=lambda c: c.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/clients/<client_id>")
def get_client(client_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    client = CLIENTS.get(client_id)
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    refresh_client(client)
    return respond(rc.ok_object(client))


# ---------------------------------------------------------------------------
# Class templates
# ---------------------------------------------------------------------------


@app.post("/wellness/class-templates")
def post_template():
    guard("StudioOwner")
    body = rc.body()
    studio = lifecycle.studio_or_404(body.get("studio_id"))
    duration = int(body.get("duration_minutes", 0))
    if duration < 15:
        fail("ERR_INVALID_STATE", "duration_minutes must be at least 15.", 409)
    capacity = int(body.get("default_capacity", 0))
    if capacity < 1:
        fail("ERR_INVALID_STATE", "default_capacity must be at least 1.", 409)
    credit_cost = int(body.get("credit_cost", 0))
    if credit_cost < 1:
        fail("ERR_INVALID_STATE", "credit_cost must be at least 1.", 409)
    buffer_minutes = int(body.get("buffer_minutes", 0))
    if buffer_minutes < 0:
        fail("ERR_INVALID_STATE", "buffer_minutes must be at least 0.", 409)
    base_price = int(body.get("base_price_cents", 0))
    if base_price < 0:
        fail("ERR_INVALID_STATE", "base_price_cents must be at least 0.", 409)
    template = mint(
        CLASS_TEMPLATES,
        {
            "studio_id": studio["id"],
            "name": body.get("name"),
            "duration_minutes": duration,
            "base_price_cents": base_price,
            "default_capacity": capacity,
            "credit_cost": credit_cost,
            "is_off_peak": bool(body.get("is_off_peak", False)),
            "buffer_minutes": buffer_minutes,
        },
    )
    return respond(rc.ok_object(template, status=201))


@app.get("/wellness/class-templates")
def list_templates():
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(CLASS_TEMPLATES.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [t for t in rows if t.get("studio_id") == studio_id]
    off_peak = rc.bool_arg("is_off_peak")
    if off_peak is not None:
        rows = [t for t in rows if bool(t.get("is_off_peak")) == off_peak]
    rows.sort(key=lambda t: t.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-templates/<template_id>")
def get_template(template_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    template = CLASS_TEMPLATES.get(template_id)
    if template is None:
        fail("ERR_INVALID_STATE", "The class template does not exist.", 404)
    return respond(rc.ok_object(template))


@app.get("/wellness/studios/<studio_id>/class-templates")
def studio_templates(studio_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [t for t in CLASS_TEMPLATES.values() if t.get("studio_id") == studio_id]
    off_peak = rc.bool_arg("is_off_peak")
    if off_peak is not None:
        rows = [t for t in rows if bool(t.get("is_off_peak")) == off_peak]
    rows.sort(key=lambda t: t.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-templates/<template_id>/class-sessions")
def template_sessions(template_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    if template_id not in CLASS_TEMPLATES:
        fail("ERR_INVALID_STATE", "The class template does not exist.", 404)
    limit, offset = read_pagination(request.args)
    rows = [s for s in CLASS_SESSIONS.values() if s.get("class_template_id") == template_id]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    rows.sort(key=lambda s: (s.get("start_at"), s.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-templates/<template_id>/staff-members")
def template_staff(template_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    if template_id not in CLASS_TEMPLATES:
        fail("ERR_INVALID_STATE", "The class template does not exist.", 404)
    limit, offset = read_pagination(request.args)
    rows = [
        s
        for s in STAFF_MEMBERS.values()
        if s.get("primary_class_template_id") == template_id
    ]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    rows.sort(key=lambda s: s.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Class sessions
# ---------------------------------------------------------------------------


@app.post("/wellness/class-sessions")
def post_session():
    guard("StudioOwner")
    body = rc.body()
    studio = lifecycle.studio_or_404(body.get("studio_id"))
    subscription = lifecycle.subscription_for_studio(studio)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    rc.occ(subscription, "expected_subscription_version")
    for field in ("class_template_id", "instructor_staff_id", "room_code", "start_at"):
        if not body.get(field):
            fail("ERR_INVALID_STATE", "%s is required." % field, 409)
    session = lifecycle.create_session(body)
    return respond(rc.ok_object(session, status=201))


@app.get("/wellness/class-sessions")
def list_sessions():
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(CLASS_SESSIONS.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [s for s in rows if s.get("studio_id") == studio_id]
    template_id = rc.str_arg("class_template_id")
    if template_id:
        rows = [s for s in rows if s.get("class_template_id") == template_id]
    room_code = rc.str_arg("room_code")
    if room_code:
        rows = [s for s in rows if s.get("room_code") == room_code]
    period_id = rc.str_arg("payroll_period_id")
    if period_id:
        rows = [s for s in rows if s.get("payroll_period_id") == period_id]
    instructor_id = rc.str_arg("instructor_staff_id")
    if instructor_id:
        rows = [s for s in rows if s.get("instructor_staff_id") == instructor_id]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    start_after = rc.dt_arg("start_after")
    if start_after is not None:
        rows = [s for s in rows if s.get("start_at") and s["start_at"] > start_after]
    start_before = rc.dt_arg("start_before")
    if start_before is not None:
        rows = [s for s in rows if s.get("start_at") and s["start_at"] < start_before]
    rows.sort(key=lambda s: (s.get("start_at"), s.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-sessions/<session_id>")
def get_session(session_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    session = lifecycle.session_or_404(session_id)
    waitlist.materialise_lapsed_offers(session)
    refresh_session_counters(session)
    return respond(rc.ok_object(session))


@app.put("/wellness/class-sessions/<session_id>")
def put_session(session_id):
    guard("StudioOwner")
    session = lifecycle.session_or_404(session_id)
    rc.occ(session, "expected_class_session_version")
    lifecycle.update_session(session, rc.body())
    return respond(rc.ok_object(session))


@app.post("/wellness/class-sessions/<session_id>/cancel")
def post_cancel_session(session_id):
    guard("StudioOwner")
    session = lifecycle.session_or_404(session_id)
    if session.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "The session may not be cancelled from this state.", 409)
    lifecycle.cancel_session(session)
    return respond(rc.ok_object(session))


@app.post("/wellness/class-sessions/<session_id>/complete")
def post_complete_session(session_id):
    guard("PlatformAdmin", "StudioOwner")
    session = lifecycle.session_or_404(session_id)
    if session.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "The session may not be completed from this state.", 409)
    lifecycle.complete_session(session)
    return respond(rc.ok_object(session))


@app.get("/wellness/class-sessions/<session_id>/bookings")
def session_bookings(session_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    lifecycle.session_or_404(session_id)
    limit, offset = read_pagination(request.args)
    rows = [b for b in BOOKINGS.values() if b.get("class_session_id") == session_id]
    status = rc.str_arg("status")
    if status:
        rows = [b for b in rows if b.get("status") == status]
    channel = rc.str_arg("channel")
    if channel:
        rows = [b for b in rows if b.get("channel") == channel]
    rows.sort(key=lambda b: (b.get("creation_seq", 0), b.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-sessions/<session_id>/waitlist-entries")
def session_waitlist(session_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    session = lifecycle.session_or_404(session_id)
    waitlist.materialise_lapsed_offers(session)
    refresh_session_counters(session)
    limit, offset = read_pagination(request.args)
    rows = [w for w in WAITLIST_ENTRIES.values() if w.get("class_session_id") == session_id]
    status = rc.str_arg("status")
    if status:
        rows = [w for w in rows if w.get("status") == status]
    rows.sort(key=waitlist.rank_key)
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-sessions/<session_id>/class-sessions")
def session_cascade(session_id):
    guard("PlatformAdmin", "StudioOwner")
    lifecycle.session_or_404(session_id)
    limit, offset = read_pagination(request.args)
    rows = [
        s
        for s in CLASS_SESSIONS.values()
        if s.get("promo_cascade_class_session_id") == session_id
    ]
    rows.sort(key=lambda s: (s.get("start_at"), s.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-sessions/<session_id>/eligible-instructors")
def eligible_instructors(session_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    session = lifecycle.session_or_404(session_id)
    exclude = rc.str_arg("exclude_staff_id")
    rows = payroll.eligible_instructors(session, exclude)
    limit = rc.int_arg("limit", 10)
    total = len(rows)
    page = rows[:limit]
    return respond(
        rc.ok_raw(
            {
                "eligible": page,
                "total_count": total,
                "has_more": limit < total,
            }
        )
    )


@app.post("/wellness/class-sessions/<session_id>/reassign-instructor")
def reassign_instructor(session_id):
    guard("StudioOwner")
    session = lifecycle.session_or_404(session_id)
    rc.occ(session, "expected_class_session_version")
    payroll.reassign_instructor(session, rc.body())
    return respond(rc.ok_object(session))


@app.get("/wellness/studios/<studio_id>/class-sessions")
def studio_sessions(studio_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [s for s in CLASS_SESSIONS.values() if s.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    start_after = rc.dt_arg("start_after")
    if start_after is not None:
        rows = [s for s in rows if s.get("start_at") and s["start_at"] > start_after]
    rows.sort(key=lambda s: (s.get("start_at"), s.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------


@app.post("/wellness/bookings")
def post_booking():
    actor, role = guard("StudioOwner", "Client")
    booking = bookings_mod.create_booking(rc.body())
    return respond(rc.ok_object(booking, status=201))


@app.get("/wellness/bookings")
def list_bookings():
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(BOOKINGS.values())
    client_id = rc.str_arg("client_id")
    if client_id:
        rows = [b for b in rows if b.get("client_id") == client_id]
    session_id = rc.str_arg("class_session_id")
    if session_id:
        rows = [b for b in rows if b.get("class_session_id") == session_id]
    status = rc.str_arg("status")
    if status:
        rows = [b for b in rows if b.get("status") == status]
    channel = rc.str_arg("channel")
    if channel:
        rows = [b for b in rows if b.get("channel") == channel]
    rows.sort(key=lambda b: (b.get("created_at"), b.get("creation_seq", 0)))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/bookings/<booking_id>")
def get_booking(booking_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    booking = bookings_mod.booking_or_404(booking_id)
    return respond(rc.ok_object(booking))


@app.post("/wellness/bookings/<booking_id>/check-in")
def post_check_in(booking_id):
    guard("StudioOwner", "Client")
    booking = bookings_mod.booking_or_404(booking_id)
    bookings_mod.check_in(booking)
    return respond(rc.ok_object(booking))


@app.post("/wellness/bookings/<booking_id>/cancel")
def post_cancel_booking(booking_id):
    guard("StudioOwner", "Client")
    booking = bookings_mod.booking_or_404(booking_id)
    bookings_mod.cancel_booking(booking)
    return respond(rc.ok_object(booking))


@app.post("/wellness/bookings/<booking_id>/restore-no-show")
def post_restore_no_show(booking_id):
    guard("StudioOwner")
    booking = bookings_mod.booking_or_404(booking_id)
    bookings_mod.restore_no_show(booking, rc.body().get("reason"))
    return respond(rc.ok_object(booking))


@app.post("/wellness/bookings/<booking_id>/reverse-claim")
def post_reverse_claim(booking_id):
    guard("StudioOwner")
    booking = bookings_mod.booking_or_404(booking_id)
    bookings_mod.reverse_claim(booking, rc.body().get("reason"))
    return respond(rc.ok_object(booking))


@app.get("/wellness/bookings/<booking_id>/waitlist-entries")
def booking_waitlist(booking_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    bookings_mod.booking_or_404(booking_id)
    limit, offset = read_pagination(request.args)
    rows = bookings_mod.waiting_holds_for_booking(booking_id)
    status = rc.str_arg("status")
    if status:
        rows = [w for w in rows if w.get("status") == status]
    rows.sort(key=lambda w: (w.get("created_at"), w.get("joined_at")))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/bookings/<booking_id>/commission-entries")
def booking_commissions(booking_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    bookings_mod.booking_or_404(booking_id)
    limit, offset = read_pagination(request.args)
    rows = bookings_mod.commission_entries_for_booking(booking_id)
    status = rc.str_arg("status")
    if status:
        rows = [e for e in rows if e.get("status") == status]
    rows.sort(key=lambda e: e.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/clients/<client_id>/bookings")
def client_bookings(client_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    if client_id not in CLIENTS:
        fail("ERR_CLIENT_NOT_FOUND")
    limit, offset = read_pagination(request.args)
    rows = [b for b in BOOKINGS.values() if b.get("client_id") == client_id]
    status = rc.str_arg("status")
    if status:
        rows = [b for b in rows if b.get("status") == status]
    channel = rc.str_arg("channel")
    if channel:
        rows = [b for b in rows if b.get("channel") == channel]
    rows.sort(key=lambda b: (b.get("created_at"), b.get("creation_seq", 0)))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>/bookings")
def studio_bookings(studio_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [b for b in BOOKINGS.values() if b.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [b for b in rows if b.get("status") == status]
    channel = rc.str_arg("channel")
    if channel:
        rows = [b for b in rows if b.get("channel") == channel]
    rows.sort(key=lambda b: (b.get("created_at"), b.get("creation_seq", 0)))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Waitlist
# ---------------------------------------------------------------------------


@app.post("/wellness/waitlist-entries")
def post_waitlist_entry():
    guard("StudioOwner", "Client")
    body = rc.body()
    session = lifecycle.session_or_404(body.get("class_session_id"))
    client = CLIENTS.get(body.get("client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    entry = waitlist.create_entry(session, client, body.get("position_mode"))
    return respond(rc.ok_object(entry, status=201))


@app.get("/wellness/waitlist-entries")
def list_waitlist_entries():
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(WAITLIST_ENTRIES.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [w for w in rows if w.get("studio_id") == studio_id]
    session_id = rc.str_arg("class_session_id")
    if session_id:
        rows = [w for w in rows if w.get("class_session_id") == session_id]
    client_id = rc.str_arg("client_id")
    if client_id:
        rows = [w for w in rows if w.get("client_id") == client_id]
    booking_id = rc.str_arg("promoted_booking_id")
    if booking_id:
        rows = [w for w in rows if w.get("promoted_booking_id") == booking_id]
    status = rc.str_arg("status")
    if status:
        rows = [w for w in rows if w.get("status") == status]
    rows.sort(key=waitlist.rank_key)
    return respond(rc.ok_array(rows, limit, offset))


@app.post("/wellness/waitlist-entries/<entry_id>/claim")
def post_claim(entry_id):
    guard("StudioOwner", "Client")
    entry = waitlist.entry_or_404(entry_id)
    booking = waitlist.claim(entry, rc.body())
    return respond(rc.ok_object(booking))


@app.post("/wellness/waitlist-entries/<entry_id>/cancel")
def post_cancel_entry(entry_id):
    guard("StudioOwner", "Client")
    entry = waitlist.entry_or_404(entry_id)
    waitlist.cancel_entry(entry)
    return respond(rc.ok_object(entry))


@app.post("/wellness/waitlist-entries/<entry_id>/confirm-position")
def post_confirm_position(entry_id):
    guard("StudioOwner", "Client")
    entry = waitlist.entry_or_404(entry_id)
    waitlist.confirm_position(entry)
    return respond(rc.ok_object(entry))


@app.post("/wellness/waitlist-entries/sweep-offers")
def post_sweep_offers():
    guard("PlatformAdmin", "StudioOwner")
    body = rc.body()
    studio_id = body.get("studio_id")
    lifecycle.studio_or_404(studio_id)
    expected = body.get("expected_class_session_version")
    if expected is not None:
        for session in CLASS_SESSIONS.values():
            if session.get("studio_id") != studio_id:
                continue
            if int(expected) != session.get("version"):
                fail("ERR_STALE_VERSION")
    expired, offered = waitlist.sweep_lapsed_offers(studio_id)
    return respond(
        rc.ok_raw(
            {
                "swept_count": len(offered),
                "offered_entry_ids": [e["id"] for e in offered],
                "expired_entry_ids": [e["id"] for e in expired],
            }
        )
    )


@app.get("/wellness/clients/<client_id>/waitlist-entries")
def client_waitlist(client_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember", "Client")
    if client_id not in CLIENTS:
        fail("ERR_CLIENT_NOT_FOUND")
    limit, offset = read_pagination(request.args)
    rows = [w for w in WAITLIST_ENTRIES.values() if w.get("client_id") == client_id]
    status = rc.str_arg("status")
    if status:
        rows = [w for w in rows if w.get("status") == status]
    rows.sort(key=waitlist.rank_key)
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>/waitlist-entries")
def studio_waitlist(studio_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [w for w in WAITLIST_ENTRIES.values() if w.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [w for w in rows if w.get("status") == status]
    rows.sort(key=waitlist.rank_key)
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/staff-members/<staff_id>/class-sessions")
def staff_sessions(staff_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    subscriptions.staff_or_404(staff_id)
    limit, offset = read_pagination(request.args)
    rows = [s for s in CLASS_SESSIONS.values() if s.get("instructor_staff_id") == staff_id]
    status = rc.str_arg("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    rows.sort(key=lambda s: (s.get("start_at"), s.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Class packs
# ---------------------------------------------------------------------------


@app.post("/wellness/class-packs")
def post_pack():
    guard("StudioOwner", "Client")
    body = rc.body()
    client = CLIENTS.get(body.get("client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    rc.occ(client, "expected_client_version")
    pack = packs.create_pack(body)
    return respond(rc.ok_object(pack, status=201))


@app.get("/wellness/class-packs")
def list_packs():
    guard("PlatformAdmin", "StudioOwner", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(CLASS_PACKS.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [p for p in rows if p.get("studio_id") == studio_id]
    client_id = rc.str_arg("client_id")
    if client_id:
        rows = [p for p in rows if p.get("client_id") == client_id]
    status = rc.str_arg("status")
    if status:
        rows = [p for p in rows if p.get("status") == status]
    rows.sort(key=lambda p: p.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/class-packs/<pack_id>")
def get_pack(pack_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    pack = packs.pack_or_404(pack_id)
    return respond(rc.ok_object(pack))


@app.post("/wellness/class-packs/<pack_id>/extend")
def post_extend_pack(pack_id):
    guard("StudioOwner")
    pack = packs.pack_or_404(pack_id)
    packs.extend_pack(pack, rc.body())
    return respond(rc.ok_object(pack))


@app.post("/wellness/class-packs/<pack_id>/sweep-expiry")
def post_sweep_expiry(pack_id):
    guard("PlatformAdmin", "StudioOwner")
    pack = packs.pack_or_404(pack_id)
    result = packs.sweep_expiry(rc.body(), pack)
    return respond(rc.ok_raw(result))


@app.get("/wellness/class-packs/<pack_id>/bookings")
def pack_bookings(pack_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    packs.pack_or_404(pack_id)
    limit, offset = read_pagination(request.args)
    rows = [b for b in BOOKINGS.values() if b.get("class_pack_id") == pack_id]
    status = rc.str_arg("status")
    if status:
        rows = [b for b in rows if b.get("status") == status]
    rows.sort(key=lambda b: (b.get("created_at"), b.get("creation_seq", 0)))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/clients/<client_id>/class-packs")
def client_packs(client_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    if client_id not in CLIENTS:
        fail("ERR_CLIENT_NOT_FOUND")
    limit, offset = read_pagination(request.args)
    rows = [p for p in CLASS_PACKS.values() if p.get("client_id") == client_id]
    status = rc.str_arg("status")
    if status:
        rows = [p for p in rows if p.get("status") == status]
    rows.sort(key=lambda p: p.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>/class-packs")
def studio_packs(studio_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [p for p in CLASS_PACKS.values() if p.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [p for p in rows if p.get("status") == status]
    rows.sort(key=lambda p: p.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Memberships
# ---------------------------------------------------------------------------


@app.post("/wellness/memberships")
def post_membership():
    guard("StudioOwner", "Client")
    membership = memberships.create_membership(rc.body())
    return respond(rc.ok_object(membership, status=201))


@app.get("/wellness/memberships")
def list_memberships():
    guard("PlatformAdmin", "StudioOwner", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(MEMBERSHIPS.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [m for m in rows if m.get("studio_id") == studio_id]
    client_id = rc.str_arg("client_id")
    if client_id:
        rows = [m for m in rows if m.get("client_id") == client_id]
    status = rc.str_arg("status")
    if status:
        rows = [m for m in rows if m.get("status") == status]
    rows.sort(key=lambda m: m.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/memberships/<membership_id>")
def get_membership(membership_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    membership = memberships.membership_or_404(membership_id)
    return respond(rc.ok_object(membership))


@app.post("/wellness/memberships/<membership_id>/advance-cycle")
def post_advance_cycle(membership_id):
    guard("PlatformAdmin", "StudioOwner")
    membership = memberships.membership_or_404(membership_id)
    rc.occ(membership, "expected_membership_version")
    memberships.advance_cycle(membership, rc.body())
    return respond(rc.ok_object(membership))


@app.post("/wellness/memberships/<membership_id>/freeze")
def post_freeze(membership_id):
    guard("StudioOwner", "Client")
    membership = memberships.membership_or_404(membership_id)
    rc.occ(membership, "expected_membership_version")
    memberships.freeze(membership, rc.body())
    return respond(rc.ok_object(membership))


@app.post("/wellness/memberships/<membership_id>/unfreeze")
def post_unfreeze(membership_id):
    guard("StudioOwner", "Client")
    membership = memberships.membership_or_404(membership_id)
    rc.occ(membership, "expected_membership_version")
    memberships.unfreeze(membership, rc.body())
    return respond(rc.ok_object(membership))


@app.post("/wellness/memberships/<membership_id>/cancel")
def post_cancel_membership(membership_id):
    guard("StudioOwner", "Client")
    membership = memberships.membership_or_404(membership_id)
    rc.occ(membership, "expected_membership_version")
    memberships.cancel_membership(membership, rc.body())
    return respond(rc.ok_object(membership))


@app.get("/wellness/memberships/<membership_id>/bookings")
def membership_bookings(membership_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    memberships.membership_or_404(membership_id)
    limit, offset = read_pagination(request.args)
    rows = [b for b in BOOKINGS.values() if b.get("membership_id") == membership_id]
    status = rc.str_arg("status")
    if status:
        rows = [b for b in rows if b.get("status") == status]
    rows.sort(key=lambda b: (b.get("created_at"), b.get("creation_seq", 0)))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/clients/<client_id>/memberships")
def client_memberships(client_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    if client_id not in CLIENTS:
        fail("ERR_CLIENT_NOT_FOUND")
    limit, offset = read_pagination(request.args)
    rows = [m for m in MEMBERSHIPS.values() if m.get("client_id") == client_id]
    status = rc.str_arg("status")
    if status:
        rows = [m for m in rows if m.get("status") == status]
    rows.sort(key=lambda m: m.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>/memberships")
def studio_memberships(studio_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [m for m in MEMBERSHIPS.values() if m.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [m for m in rows if m.get("status") == status]
    rows.sort(key=lambda m: m.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------


@app.post("/wellness/payroll-periods")
def post_payroll_period():
    guard("StudioOwner")
    period = payroll.create_period(rc.body())
    return respond(rc.ok_object(period, status=201))


@app.get("/wellness/payroll-periods")
def list_payroll_periods():
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    limit, offset = read_pagination(request.args)
    rows = list(PAYROLL_PERIODS.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [p for p in rows if p.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [p for p in rows if p.get("status") == status]
    rows.sort(key=lambda p: (p.get("start_date"), p.get("created_at")))
    for period in rows:
        from commons import refresh_payroll_period

        refresh_payroll_period(period)
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/payroll-periods/<period_id>")
def get_payroll_period(period_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    period = payroll.period_or_404(period_id)
    from commons import refresh_payroll_period

    refresh_payroll_period(period)
    return respond(rc.ok_object(period))


@app.post("/wellness/payroll-periods/<period_id>/close")
def post_close_period(period_id):
    guard("StudioOwner")
    period = payroll.period_or_404(period_id)
    rc.occ(period, "expected_payroll_period_version")
    payroll.close_period(period)
    return respond(rc.ok_object(period))


@app.post("/wellness/payroll-periods/<period_id>/reopen")
def post_reopen_period(period_id):
    guard("StudioOwner")
    period = payroll.period_or_404(period_id)
    rc.occ(period, "expected_payroll_period_version")
    payroll.reopen_period(period)
    return respond(rc.ok_object(period))


@app.get("/wellness/payroll-periods/<period_id>/commission-entries")
def period_commissions(period_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    payroll.period_or_404(period_id)
    limit, offset = read_pagination(request.args)
    rows = [e for e in COMMISSION_ENTRIES.values() if e.get("payroll_period_id") == period_id]
    status = rc.str_arg("status")
    if status:
        rows = [e for e in rows if e.get("status") == status]
    rows.sort(key=lambda e: e.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/commission-entries")
def list_commissions():
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    limit, offset = read_pagination(request.args)
    rows = list(COMMISSION_ENTRIES.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [e for e in rows if e.get("studio_id") == studio_id]
    staff_id = rc.str_arg("staff_member_id")
    if staff_id:
        rows = [e for e in rows if e.get("staff_member_id") == staff_id]
    period_id = rc.str_arg("payroll_period_id")
    if period_id:
        rows = [e for e in rows if e.get("payroll_period_id") == period_id]
    booking_id = rc.str_arg("booking_id")
    if booking_id:
        rows = [e for e in rows if e.get("booking_id") == booking_id]
    status = rc.str_arg("status")
    if status:
        rows = [e for e in rows if e.get("status") == status]
    rows.sort(key=lambda e: e.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/commission-entries/<entry_id>")
def get_commission(entry_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    entry = payroll.entry_or_404(entry_id)
    return respond(rc.ok_object(entry))


@app.get("/wellness/staff-members/<staff_id>/commission-entries")
def staff_commissions(staff_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    subscriptions.staff_or_404(staff_id)
    limit, offset = read_pagination(request.args)
    rows = [e for e in COMMISSION_ENTRIES.values() if e.get("staff_member_id") == staff_id]
    status = rc.str_arg("status")
    if status:
        rows = [e for e in rows if e.get("status") == status]
    rows.sort(key=lambda e: e.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>/commission-entries")
def studio_commissions(studio_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [e for e in COMMISSION_ENTRIES.values() if e.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [e for e in rows if e.get("status") == status]
    rows.sort(key=lambda e: e.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>/payroll-periods")
def studio_payroll(studio_id):
    guard("PlatformAdmin", "StudioOwner", "StaffMember")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [p for p in PAYROLL_PERIODS.values() if p.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [p for p in rows if p.get("status") == status]
    rows.sort(key=lambda p: (p.get("start_date"), p.get("created_at")))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------


@app.get("/wellness/marketplace/classes")
def marketplace_classes():
    guard_anon("Anonymous", "Client", "StudioOwner", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = [s for s in CLASS_SESSIONS.values() if marketplace.listing_visible(s)]
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [s for s in rows if s.get("studio_id") == studio_id]
    home_state = rc.str_arg("home_state_code")
    if home_state:
        rows = [
            s
            for s in rows
            if (STUDIOS.get(s.get("studio_id")) or {}).get("home_state_code") == home_state
        ]
    off_peak = rc.bool_arg("is_off_peak")
    if off_peak is not None:
        rows = [
            s
            for s in rows
            if bool(
                (CLASS_TEMPLATES.get(s.get("class_template_id")) or {}).get("is_off_peak")
            )
            == off_peak
        ]
    start_after = rc.dt_arg("start_after")
    if start_after is not None:
        rows = [s for s in rows if s.get("start_at") and s["start_at"] > start_after]
    start_before = rc.dt_arg("start_before")
    if start_before is not None:
        rows = [s for s in rows if s.get("start_at") and s["start_at"] < start_before]
    rows.sort(key=lambda s: (s.get("start_at"), s.get("created_at")))
    views = [marketplace.marketplace_view(s) for s in rows]
    return respond(rc.ok_array(views, limit, offset))


@app.get("/wellness/marketplace/classes/<session_id>")
def marketplace_class(session_id):
    guard_anon("Anonymous", "Client", "StudioOwner", "PlatformAdmin")
    view = marketplace.single_class(session_id)
    return respond(rc.ok_raw(view))


@app.post("/wellness/marketplace/bookings")
def post_marketplace_booking():
    guard("Client")
    booking = marketplace.create_marketplace_booking(rc.body())
    return respond(rc.ok_object(booking, status=201))


@app.get("/wellness/marketplace/settlement")
def marketplace_settlement():
    guard("PlatformAdmin", "StudioOwner")
    studio_id = rc.str_arg("studio_id")
    lifecycle.studio_or_404(studio_id)
    return respond(rc.ok_raw(marketplace.settlement(studio_id)))


# ---------------------------------------------------------------------------
# Benefit networks
# ---------------------------------------------------------------------------


@app.post("/wellness/benefit-networks")
def post_network():
    guard("PlatformAdmin")
    network = networks.create_network(rc.body())
    return respond(rc.ok_object(network, status=201))


@app.get("/wellness/benefit-networks")
def list_networks():
    guard("PlatformAdmin", "StudioOwner")
    limit, offset = read_pagination(request.args)
    rows = list(BENEFIT_NETWORKS.values())
    code = rc.str_arg("network_code")
    if code:
        rows = [n for n in rows if n.get("network_code") == code]
    rows.sort(key=lambda n: n.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/benefit-network-claims")
def list_claims():
    guard("PlatformAdmin", "StudioOwner")
    studio_id = rc.str_arg("studio_id")
    lifecycle.studio_or_404(studio_id)
    claims, receivable = networks.claims_walk(studio_id)
    status = rc.str_arg("status")
    if status:
        claims = [c for c in claims if c.get("benefit_claim_status") == status]
    limit, offset = read_pagination(request.args)
    total = len(claims)
    page = claims[offset: offset + limit]
    return respond(
        rc.ok_raw(
            {
                "claims": page,
                "receivable_total_cents": receivable,
                "total_count": total,
                "has_more": offset + len(page) < total,
            }
        )
    )


@app.post("/wellness/benefit-network-claims/<claim_id>/resubmit")
def post_resubmit_claim(claim_id):
    guard("PlatformAdmin", "StudioOwner")
    booking = BOOKINGS.get(claim_id)
    if booking is None:
        fail("ERR_BOOKING_NOT_FOUND")
    networks.resubmit_claim(booking, rc.body())
    return respond(rc.ok_object(booking))


# ---------------------------------------------------------------------------
# Portability
# ---------------------------------------------------------------------------


@app.post("/wellness/portability-requests")
def post_portability():
    guard("Client")
    request_row = portability.create_request(rc.body())
    return respond(rc.ok_object(request_row, status=201))


@app.get("/wellness/portability-requests")
def list_portability():
    guard("PlatformAdmin", "StudioOwner", "Client")
    limit, offset = read_pagination(request.args)
    rows = list(PORTABILITY_REQUESTS.values())
    studio_id = rc.str_arg("studio_id")
    if studio_id:
        rows = [r for r in rows if r.get("studio_id") == studio_id]
    client_id = rc.str_arg("requesting_client_id")
    if client_id:
        rows = [r for r in rows if r.get("requesting_client_id") == client_id]
    status = rc.str_arg("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/portability-requests/<request_id>")
def get_portability(request_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    row = portability.request_or_404(request_id)
    return respond(rc.ok_object(row))


@app.post("/wellness/portability-requests/<request_id>/object")
def post_object(request_id):
    guard("StudioOwner")
    row = portability.request_or_404(request_id)
    portability.object_request(row, rc.body())
    return respond(rc.ok_object(row))


@app.post("/wellness/portability-requests/<request_id>/resolve-release")
def post_resolve_release(request_id):
    guard("StudioOwner")
    row = portability.request_or_404(request_id)
    portability.resolve_release(row, rc.body())
    return respond(rc.ok_object(row))


@app.post("/wellness/portability-requests/<request_id>/resolve-deny")
def post_resolve_deny(request_id):
    guard("StudioOwner")
    row = portability.request_or_404(request_id)
    portability.resolve_deny(row, rc.body())
    return respond(rc.ok_object(row))


@app.post("/wellness/portability-requests/<request_id>/adjudicate")
def post_adjudicate(request_id):
    guard("PlatformAdmin")
    row = portability.request_or_404(request_id)
    portability.adjudicate(row, rc.body())
    return respond(rc.ok_object(row))


@app.post("/wellness/portability-requests/<request_id>/issue-export")
def post_issue_export(request_id):
    guard("PlatformAdmin")
    row = portability.request_or_404(request_id)
    rc.occ(row, "expected_portability_request_version")
    portability.issue_export(row)
    return respond(rc.ok_object(row))


@app.post("/wellness/portability-requests/<request_id>/withdraw")
def post_withdraw(request_id):
    actor, _role = guard("Client")
    row = portability.request_or_404(request_id)
    portability.withdraw(row, actor)
    return respond(rc.ok_object(row))


@app.get("/wellness/portability-requests/<request_id>/export")
def get_export(request_id):
    actor, role = guard("PlatformAdmin", "Client")
    row = portability.request_or_404(request_id)
    portability.download_export(row)
    return respond(rc.ok_object(row))


@app.get("/wellness/clients/<client_id>/portability-requests")
def client_portability(client_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    if client_id not in CLIENTS:
        fail("ERR_CLIENT_NOT_FOUND")
    limit, offset = read_pagination(request.args)
    rows = [
        r for r in PORTABILITY_REQUESTS.values() if r.get("requesting_client_id") == client_id
    ]
    status = rc.str_arg("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


@app.get("/wellness/studios/<studio_id>/portability-requests")
def studio_portability(studio_id):
    guard("PlatformAdmin", "StudioOwner", "Client")
    lifecycle.studio_or_404(studio_id)
    limit, offset = read_pagination(request.args)
    rows = [r for r in PORTABILITY_REQUESTS.values() if r.get("studio_id") == studio_id]
    status = rc.str_arg("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at"))
    return respond(rc.ok_array(rows, limit, offset))


# ---------------------------------------------------------------------------
# Operator: logical clock and injectors
# ---------------------------------------------------------------------------


@app.post("/_clock/set_current_utc")
def post_set_clock():
    rc.require_operator()
    incoming = parse_dt(rc.body().get("current_utc"))
    if incoming is None:
        fail("ERR_INVALID_STATE", "current_utc is required.", 409)
    previous = set_clock(incoming)
    lifecycle.run_due_transitions()
    return respond(
        rc.ok_raw(
            {
                "current_utc": now(),
                "advanced_from": previous,
            }
        )
    )


@app.post("/_inject/client-history")
def post_inject_history():
    rc.require_operator()
    body = rc.body()
    client = CLIENTS.get(body.get("client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    client["no_show_strike_count"] = int(body.get("no_show_strike_count", 0))
    client["late_cancel_count"] = int(body.get("late_cancel_count", 0))
    touch(client)
    refresh_client(client)
    return respond(rc.ok_object(client))


@app.post("/_inject/client-entitlement")
def post_inject_entitlement():
    rc.require_operator()
    body = rc.body()
    client = CLIENTS.get(body.get("client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    studio = lifecycle.studio_or_404(body.get("studio_id"))
    kind = body.get("kind")
    if isinstance(kind, str):
        # PRD §3.12: the kind "selects a membership or a pack".  The entity
        # vocabulary is used interchangeably with the endpoint vocabulary, so
        # accept either spelling.
        kind = kind.strip().lower()
        if kind in ("membership", "memberships"):
            kind = "membership"
        elif kind in ("class_pack", "class-packs", "pack", "packs"):
            kind = "class_pack"
    credits = int(body.get("credits", 0))
    if kind == "membership":
        row = mint(
            MEMBERSHIPS,
            {
                "studio_id": studio["id"],
                "client_id": client["id"],
                "plan_name": "INJECTED",
                "monthly_fee_cents": 0,
                "included_credits_per_cycle": credits,
                "minimum_term_months": 0,
                "freeze_allowed": False,
                "freeze_max_days_per_cycle": 0,
                "billing_anchor_day": 1,
                "current_period_index": 1,
                "next_billing_at": now(),
                "auto_renew": True,
                "freeze_start_at": None,
                "freeze_resume_at": None,
                "freeze_days_used": 0,
                "prorated_fee_cents": 0,
                "open_balance_cents": 0,
                "status": "ACTIVE",
                "_credits_remaining": credits,
                "_planned_freeze_days": 0,
            },
        )
        entity_id = row["id"]
    elif kind == "class_pack":
        expires_at = parse_dt(body.get("expires_at"))
        if expires_at is None:
            from core import add_days

            expires_at = add_days(now(), 180)
        row = mint(
            CLASS_PACKS,
            {
                "studio_id": studio["id"],
                "client_id": client["id"],
                "pack_size": credits,
                "credits_remaining": credits,
                "purchased_at": now(),
                "expires_at": expires_at,
                "extension_days_used": 0,
                "status": "ACTIVE",
                "pending_expiry_grace_until": None,
                "expiry_scheme": "NONE",
                "_overage_cents": 0,
                "_pre_expiry_credits": credits,
                "_voided": 0,
                "_grace_used": 0,
            },
        )
        entity_id = row["id"]
    else:
        fail("ERR_INVALID_STATE", "kind must be membership or class_pack.", 409)
    return respond(
        rc.ok_raw({"kind": kind, "entity_id": entity_id, "credits": credits})
    )


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )