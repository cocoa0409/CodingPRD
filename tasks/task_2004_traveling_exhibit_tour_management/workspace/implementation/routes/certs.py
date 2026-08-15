"""InsuranceCertificate endpoints (PRD §3.5)."""

from flask import Blueprint

import db
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import cert_out
from validate import (json_body, req_str, req_int, req_dt, get_tour, get_cert,
                      paginate, apply_filters, sorted_created)

bp = Blueprint("certs", __name__)


@bp.route("/tours/<tour_id>/certificates", methods=["POST"])
def create_cert(tour_id):
    require_roles("Insurer")
    tour = get_tour(tour_id)
    data = json_body()
    stop_id = data.get("tour_stop_id")
    if not isinstance(stop_id, str) or not stop_id:
        fail("ERR_INVALID_REQUEST",
             "Missing or invalid required field: tour_stop_id")
    stop = db.stops.get(stop_id)
    if stop is None or stop["tour_id"] != tour["id"]:
        fail("ERR_INVALID_REQUEST",
             "tour_stop_id does not reference a stop of this tour")
    insurer_name = req_str(data, "insurer_name")
    coverage = req_int(data, "coverage_cents")
    effective_from = req_dt(data, "effective_from")
    effective_to = req_dt(data, "effective_to")
    if coverage < tour["declared_value_cents"]:
        fail("ERR_INVALID_REQUEST",
             "coverage_cents must be at least the tour's declared value")
    if not (db.parse_dt(effective_from) < db.parse_dt(effective_to)):
        fail("ERR_INVALID_REQUEST",
             "effective_from must precede effective_to")
    cert = db.stamp_new({
        "id": db.new_id(),
        "tour_id": tour["id"],
        "tour_stop_id": stop["id"],
        "insurer_name": insurer_name,
        "coverage_cents": coverage,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ISSUED",
    })
    db.certs[cert["id"]] = cert
    return ok_object(cert_out(cert), status=201)


@bp.route("/tours/<tour_id>/certificates", methods=["GET"])
def list_certs(tour_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    items = [c for c in db.certs.values() if c["tour_id"] == tour["id"]]
    items = apply_filters(items, [("tour_stop_id", "tour_stop_id"),
                                  ("status", "status")])
    return paginate([cert_out(c) for c in sorted_created(items)])


@bp.route("/tours/<tour_id>/certificates/<cert_id>", methods=["GET"])
def get_one_cert(tour_id, cert_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    return ok_object(cert_out(get_cert(tour, cert_id)))
