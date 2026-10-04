"""Wellness benefit networks and the forward-looking claim receivable walk."""

from datetime import timedelta

from core import (
    CLAIM_RESUBMIT_MAX,
    DEFAULT_REMIT_DAYS,
    add_days,
    fail,
    now,
)
from commons import mint_config, touch
from store import BENEFIT_NETWORKS, BOOKINGS, CLASS_SESSIONS, STUDIOS

import calc
import lifecycle


def network_or_404(network_code):
    network = BENEFIT_NETWORKS.get(network_code)
    if network is None:
        fail("ERR_BENEFIT_NETWORK_NOT_FOUND")
    return network


def create_network(body):
    code = body.get("network_code")
    if not code:
        fail("ERR_INVALID_STATE", "network_code is required.", 409)
    allowance = int(body.get("per_visit_allowance_cents", 0))
    if allowance < 0:
        fail("ERR_INVALID_STATE", "per_visit_allowance_cents must be >= 0.", 409)
    fields = {
        "network_code": code,
        "name": body.get("name"),
        "per_visit_allowance_cents": allowance,
        "reimburse_full_list_price": bool(body.get("reimburse_full_list_price", False)),
        "remit_days_after_visit": int(
            body.get("remit_days_after_visit", DEFAULT_REMIT_DAYS)
        ),
        "claim_denial_window_hours": int(body.get("claim_denial_window_hours", 0)),
        "status": True,
    }
    existing = BENEFIT_NETWORKS.get(code)
    if existing is not None:
        existing.update(fields)
        return existing
    return mint_config(BENEFIT_NETWORKS, code, fields)


def claim_rows(studio_id):
    rows = []
    for booking in BOOKINGS.values():
        if booking.get("studio_id") != studio_id:
            continue
        if booking.get("benefit_claim_status") in (None, "NOT_APPLICABLE"):
            continue
        if booking.get("payment_source") != "BENEFIT_NETWORK":
            continue
        rows.append(booking)
    rows.sort(key=lambda b: (b.get("created_at"), b.get("creation_seq", 0)))
    return rows


def _network_for(booking):
    return BENEFIT_NETWORKS.get(booking.get("benefit_network_code"))


def claim_amount_at_read(booking):
    session = CLASS_SESSIONS.get(booking.get("class_session_id"))
    network = _network_for(booking)
    if session is None or network is None:
        return booking.get("benefit_claim_amount_cents", 0)
    return calc.benefit_claim_amount(network, session.get("list_price_cents", 0))


def _resubmission_open(booking):
    if booking.get("benefit_claim_status") != "DENIED":
        return False
    if booking.get("_claim_resubmissions", 0) >= CLAIM_RESUBMIT_MAX:
        return False
    submitted = booking.get("_claim_submitted_at") or booking.get("created_at")
    network = _network_for(booking)
    if network is None or submitted is None:
        return False
    window = network.get("claim_denial_window_hours", 0)
    return now() <= submitted + timedelta(hours=window)


def claims_walk(studio_id):
    if STUDIOS.get(studio_id) is None:
        fail("ERR_STUDIO_NOT_FOUND")
    rows = claim_rows(studio_id)
    claims = []
    receivable = 0
    for booking in rows:
        session = CLASS_SESSIONS.get(booking.get("class_session_id"))
        network = _network_for(booking)
        amount = claim_amount_at_read(booking)
        remit_at = None
        if session is not None and network is not None:
            remit_at = add_days(
                session.get("end_at"), network.get("remit_days_after_visit", 0)
            )
        claim = {
            "id": booking["id"],
            "booking_id": booking["id"],
            "studio_id": booking.get("studio_id"),
            "client_id": booking.get("client_id"),
            "class_session_id": booking.get("class_session_id"),
            "benefit_network_code": booking.get("benefit_network_code"),
            "benefit_claim_status": booking.get("benefit_claim_status"),
            "claim_amount_cents": amount,
            "remit_at": remit_at,
        }
        claims.append(claim)
        status = booking.get("benefit_claim_status")
        if status in ("SUBMITTED", "PAID"):
            receivable += amount
        elif status == "DENIED" and _resubmission_open(booking):
            receivable += amount
    return claims, receivable


def resubmit_claim(booking, body=None):
    if booking.get("benefit_claim_status") != "DENIED":
        fail("ERR_CLAIM_WINDOW_CLOSED", "Only a denied claim may be resubmitted.")
    if booking.get("_claim_resubmissions", 0) >= CLAIM_RESUBMIT_MAX:
        fail("ERR_CLAIM_WINDOW_CLOSED")
    submitted = booking.get("_claim_submitted_at") or booking.get("created_at")
    network = _network_for(booking)
    if network is None:
        fail("ERR_BENEFIT_NETWORK_NOT_FOUND")
    window = network.get("claim_denial_window_hours", 0)
    if submitted is not None and now() > submitted + timedelta(hours=window):
        fail("ERR_CLAIM_WINDOW_CLOSED")

    session = CLASS_SESSIONS.get(booking.get("class_session_id"))
    if session is None:
        fail("ERR_CLASS_SESSION_NOT_FOUND")
    booking["benefit_claim_amount_cents"] = claim_amount_at_read(booking)
    booking["benefit_claim_status"] = "SUBMITTED"
    booking["_claim_resubmissions"] = booking.get("_claim_resubmissions", 0) + 1
    booking["_claim_submitted_at"] = now()
    touch(booking)
    return booking


def note_claim_submission(booking):
    booking["_claim_submitted_at"] = now()
    booking["_claim_resubmissions"] = booking.get("_claim_resubmissions", 0)