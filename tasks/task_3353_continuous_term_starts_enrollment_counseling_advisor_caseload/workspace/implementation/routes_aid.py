"""Routes: financial aid packages (create, certify, list)."""

from flask import Blueprint

from auth import require_roles
from domain import (
    award_packaging,
    build_disbursement_schedule,
    lazy_release_package,
    packages_for_enrollment,
    ser_package,
)
from errors import raise_err
from response import ok_list, ok_object
from store import STORE, bump, new_entity
from validate import get_body, paginate, req_int

bp = Blueprint("financial_aid", __name__)


@bp.post("/api/enrollments/<eid>/financial-aid-packages")
def create_package(eid):
    uid, _role = require_roles("FinancialAidOfficer")
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    body = get_body()
    efc = req_int(body, "efc_cents")
    # One active package per enrollment.
    for pkg in packages_for_enrollment(eid):
        if pkg["status"] in ("PACKAGED", "CERTIFIED", "DISBURSING"):
            raise_err(
                "ERR_PACKAGE_ALREADY_EXISTS",
                "an active financial aid package already exists for this enrollment",
            )
    package = new_entity(
        {
            "enrollment_id": eid,
            "efc_cents": efc,
            "status": "PACKAGED",
            # ESTIMATED variant always assumes FULL_TIME.
            "estimated_award_cents": award_packaging(efc, "FULL_TIME"),
            "certified_award_cents": 0,
            "disbursement_schedule": [],
            "disbursed_cents": 0,
            "returned_cents": 0,
            "retained_cents": 0,
            "cancelled_cents": 0,
            "created_by_officer_id": uid,
        }
    )
    STORE.packages[package["id"]] = package
    return ok_object(ser_package(package), 201)


@bp.post("/api/financial-aid-packages/<pid>/certify")
def certify_package(pid):
    uid, _role = require_roles("FinancialAidOfficer")
    body = get_body()
    expected_version = req_int(body, "expected_enrollment_version")
    package = STORE.packages.get(pid)
    if package is None:
        raise_err("ERR_NOT_FOUND", "financial aid package not found")
    if package["status"] != "PACKAGED":
        raise_err("ERR_INVALID_STATE", "only PACKAGED packages may be certified")
    # Segregation of duties: certifier must differ from the creating officer.
    if uid == package["created_by_officer_id"]:
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES",
            "certifying officer must differ from the package creator",
        )
    enrollment = STORE.enrollments.get(package["enrollment_id"])
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    # Optimistic concurrency on the parent enrollment version (PRD §2.8).
    if expected_version != enrollment["version"]:
        raise_err("ERR_STALE_VERSION", "enrollment version has advanced since it was observed")

    term = STORE.terms.get(enrollment["term_id"])
    # CERTIFIED variant keys the cost of attendance to the actual intensity.
    package["certified_award_cents"] = award_packaging(
        package["efc_cents"], enrollment["enrollment_intensity"]
    )
    package["disbursement_schedule"] = build_disbursement_schedule(
        package["certified_award_cents"], term
    )
    package["status"] = "CERTIFIED"
    bump(package)
    bump(enrollment)
    # Certification mutates the package; lazy release applies immediately if
    # the term is already in session and an entry is due.
    lazy_release_package(package)
    return ok_object(ser_package(package))


@bp.get("/api/enrollments/<eid>/financial-aid-packages")
def list_packages(eid):
    require_roles("SystemAdmin", "RegistrarAdmin", "FinancialAidOfficer")
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    items = sorted(packages_for_enrollment(eid), key=lambda p: p["_seq"])
    for pkg in items:
        lazy_release_package(pkg)
    page, limit, offset, total = paginate([ser_package(p) for p in items])
    return ok_list(page, limit, offset, total)
