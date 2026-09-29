"""Establishment registration, build-out, licence posting and booth rentals."""
from decimal import Decimal

from flask import Blueprint, request

import auth
import derive
import envelope
import store
from errors import fail
from helpers import find, scope_establishment
from validate import (body_of, county_code, fk, opt_instant, opt_str, req_enum, req_instant,
                      req_int, req_str)

facility_bp = Blueprint("facility", __name__)

ACTIVE_LICENCE_ONLY = ("STUDENT", "EXAM_ELIGIBLE", "PROBATION", "SUSPENDED", "LAPSED", "REVOKED")


def _require_operable(est):
    if est["license_status"] not in derive.OPERABLE_STATUSES:
        fail("ERR_ESTABLISHMENT_NOT_OPERABLE",
             "Establishment licence status %s is not operable." % est["license_status"])


def _require_not_frozen(est):
    derive.compute_establishment(est)
    if est["compliance_posture"] == "FROZEN":
        fail("ERR_POSTURE_FROZEN", "The establishment's compliance posture is FROZEN.")


def _require_no_delinquency(est):
    derive.compute_establishment(est)
    if est["delinquent_fine_total_cents"] != 0:
        fail("ERR_OUTSTANDING_FINES_BLOCK_EXPANSION",
             "Delinquent fines block expansion of this establishment.")


def _require_licence_active(prac):
    if prac["license_status"] != "ACTIVE":
        fail("ERR_PRACTITIONER_LICENSE_NOT_ACTIVE",
             "Practitioner licence status %s is not ACTIVE." % prac["license_status"])


# ----------------------------------------------------------- establishments
@facility_bp.post("/establishments")
def create_establishment():
    auth.authenticate(("BoardAdmin", "EstablishmentOwner"))
    body = body_of(request)
    legal_name = req_str(body, "legal_name", max_len=200)
    est_type = req_enum(body, "establishment_type", derive.ESTABLISHMENT_TYPES)
    code = county_code(body)
    capacity = req_int(body, "station_capacity", minimum=1)
    row = store.make_row()
    row.update({
        "legal_name": legal_name,
        "establishment_type": est_type,
        "county_code": code,
        "station_capacity": capacity,
        "station_count": 0,
        "license_status": "PENDING_INSPECTION",
        "compliance_posture": "CLEAR",
        "demerit_balance": Decimal("0.00"),
        "open_critical_citation_count": 0,
        "outstanding_fine_total_cents": 0,
        "delinquent_fine_total_cents": 0,
        "foot_spa_biofilm_current": True,
        "last_finalized_inspection_at": None,
    })
    store.establishments[row["id"]] = row
    return envelope.ok(derive.ser_establishment(row), 201)


# -------------------------------------------------------------- workstations
@facility_bp.post("/establishments/<eid>/workstations")
def create_workstation(eid):
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner"))
    est = find("Establishment", eid)
    scope_establishment(ctx, est["id"])
    body = body_of(request)
    station_number = req_int(body, "station_number", minimum=1)
    station_type = req_enum(body, "station_type", derive.STATION_TYPES)

    _require_operable(est)
    _require_not_frozen(est)

    for existing in derive.workstations_of(est["id"]):
        if existing["station_number"] == station_number:
            fail("ERR_DUPLICATE_STATION_NUMBER",
                 "Station number %d already exists at this establishment." % station_number)
    if len(derive.workstations_of(est["id"])) + 1 > est["station_capacity"]:
        fail("ERR_STATION_CAPACITY_EXCEEDED",
             "The facility permit allows only %d workstations." % est["station_capacity"])
    _require_no_delinquency(est)

    row = store.make_row()
    row.update({
        "establishment_id": est["id"],
        "station_number": station_number,
        "station_type": station_type,
        "posted_practitioner_id": None,
        "posting_status": "MISSING_POSTING",
        "last_biofilm_cycle_at": None,
    })
    store.workstations[row["id"]] = row
    derive.refresh_establishment(est, force=True)
    return envelope.ok(derive.ser_workstation(row), 201)


# ------------------------------------------------------------------ posting
@facility_bp.post("/workstations/<wid>/posting")
def post_licence(wid):
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner"))
    ws = find("Workstation", wid)
    body = body_of(request)
    prac_id = fk(body, "posted_practitioner_id")
    prac = find("Practitioner", prac_id) if prac_id is not None else None
    scope_establishment(ctx, ws["establishment_id"])
    if prac is None:
        fail("ERR_INVALID_REQUEST", "Field 'posted_practitioner_id' is required.")

    est = store.establishments[ws["establishment_id"]]
    _require_operable(est)
    _require_licence_active(prac)
    _require_not_frozen(est)

    if not auth.practitioner_linked_to_establishment(prac["id"], est["id"]):
        fail("ERR_PRACTITIONER_NOT_LINKED_TO_ESTABLISHMENT",
             "The practitioner holds no PROPOSED or ACTIVE rental at this establishment.")

    ws["posted_practitioner_id"] = prac["id"]
    derive.refresh_workstation(ws, force=True)
    return envelope.ok(derive.ser_workstation(ws))


# ----------------------------------------------------------- booth rentals
def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; a null end runs forever.  Touching is allowed."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


@facility_bp.post("/booth-rentals")
def create_booth_rental():
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner"))
    body = body_of(request)

    ws_id = fk(body, "workstation_id")
    ws = find("Workstation", ws_id) if ws_id is not None else None
    prac_id = fk(body, "practitioner_id")
    prac = find("Practitioner", prac_id) if prac_id is not None else None

    if ws is not None:
        scope_establishment(ctx, ws["establishment_id"])

    if ws is None:
        fail("ERR_INVALID_REQUEST", "Field 'workstation_id' is required.")
    if prac is None:
        fail("ERR_INVALID_REQUEST", "Field 'practitioner_id' is required.")
    rental_type = req_enum(body, "rental_type", derive.RENTAL_TYPES)
    term_start_at = req_instant(body, "term_start_at")
    term_end_at = opt_instant(body, "term_end_at")
    monthly_rent_cents = req_int(body, "monthly_rent_cents", minimum=0)
    expected_version = req_int(body, "expected_workstation_version")

    if term_end_at is not None and term_end_at <= term_start_at:
        fail("ERR_INVALID_REQUEST", "Field 'term_end_at' must be strictly after 'term_start_at'.")

    est = store.establishments[ws["establishment_id"]]
    _require_operable(est)

    if expected_version != ws["version"]:
        fail("ERR_STALE_WORKSTATION_VERSION",
             "Workstation version is %d, not %d." % (ws["version"], expected_version))

    _require_not_frozen(est)

    for other in derive.rentals_of_workstation(ws["id"]):
        if other["status"] not in ("PROPOSED", "ACTIVE"):
            continue
        if _overlaps(other["term_start_at"], other["term_end_at"], term_start_at, term_end_at):
            fail("ERR_BOOTH_RENTAL_OVERLAP",
                 "The requested term overlaps an existing rental on this workstation.")

    _require_no_delinquency(est)

    row = store.make_row()
    row.update({
        "workstation_id": ws["id"],
        "practitioner_id": prac["id"],
        "rental_type": rental_type,
        "term_start_at": term_start_at,
        "term_end_at": term_end_at,
        "monthly_rent_cents": monthly_rent_cents,
        "status": "PROPOSED",
        "terminated_at": None,
    })
    store.booth_rentals[row["id"]] = row
    derive.refresh_workstation(ws, force=True)
    return envelope.ok(derive.ser_booth_rental(row), 201)


@facility_bp.post("/booth-rentals/<rid>/activation")
def activate_booth_rental(rid):
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner"))
    rental = find("BoothRental", rid)
    ws = store.workstations[rental["workstation_id"]]
    scope_establishment(ctx, ws["establishment_id"])
    est = store.establishments[ws["establishment_id"]]
    prac = store.practitioners[rental["practitioner_id"]]

    _require_operable(est)
    _require_licence_active(prac)
    if rental["status"] != "PROPOSED":
        fail("ERR_BOOTH_RENTAL_NOT_PROPOSED",
             "Booth rental status is %s, not PROPOSED." % rental["status"])
    _require_not_frozen(est)
    if ws["posted_practitioner_id"] != rental["practitioner_id"]:
        fail("ERR_WORKSTATION_POSTING_NONCOMPLIANT",
             "The workstation's posting does not name this practitioner.")

    rental["status"] = "ACTIVE"
    store.bump(rental)
    derive.refresh_workstation(ws, force=True)
    return envelope.ok(derive.ser_booth_rental(rental))


@facility_bp.post("/booth-rentals/<rid>/termination")
def terminate_booth_rental(rid):
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner", "Practitioner"))
    rental = find("BoothRental", rid)
    ws = store.workstations[rental["workstation_id"]]
    scope_establishment(ctx, ws["establishment_id"])
    if ctx.is_prac and rental["practitioner_id"] != ctx.user_id:
        auth.deny()
    body = body_of(request)
    terminated_at = opt_instant(body, "terminated_at", default=store.now_utc())
    opt_str(body, "reason")

    if rental["status"] != "ACTIVE":
        fail("ERR_BOOTH_RENTAL_NOT_ACTIVE",
             "Booth rental status is %s, not ACTIVE." % rental["status"])

    rental["status"] = "TERMINATED"
    rental["terminated_at"] = terminated_at
    rental["term_end_at"] = terminated_at
    store.bump(rental)
    derive.clear_posting_if(ws, rental["practitioner_id"])
    return envelope.ok(derive.ser_booth_rental(rental))
