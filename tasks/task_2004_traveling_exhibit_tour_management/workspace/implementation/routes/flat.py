"""Flat read aliases (FK reverse-reachability) — PRD §4. All roles may read;
each collection sorts by created_at ascending and paginates."""

from flask import Blueprint

import db
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import (stop_out, contract_out, crate_out, shipment_out,
                         report_out, claim_out, kit_out, cert_out)
from validate import paginate, apply_filters, sorted_created

bp = Blueprint("flat", __name__)


def _flat_get(store, rid, label, out):
    require_roles(*ALL_ROLES)
    resource = store.get(rid)
    if resource is None:
        fail("ERR_NOT_FOUND", "%s not found: %s" % (label, rid))
    return ok_object(out(resource))


def _flat_list(store, filters, out):
    require_roles(*ALL_ROLES)
    items = apply_filters(list(store.values()), filters)
    return paginate([out(r) for r in sorted_created(items)])


@bp.route("/tours/stops/<stop_id>", methods=["GET"])
def flat_get_stop(stop_id):
    return _flat_get(db.stops, stop_id, "TourStop", stop_out)


@bp.route("/tours/stops", methods=["GET"])
def flat_list_stops():
    return _flat_list(db.stops, [("tour_id", "tour_id"),
                                 ("venue_id", "venue_id"),
                                 ("status", "status")], stop_out)


@bp.route("/tours/contracts/<contract_id>", methods=["GET"])
def flat_get_contract(contract_id):
    return _flat_get(db.contracts, contract_id, "ParticipationContract",
                     contract_out)


@bp.route("/tours/contracts", methods=["GET"])
def flat_list_contracts():
    return _flat_list(db.contracts, [("tour_stop_id", "tour_stop_id"),
                                     ("status", "status")], contract_out)


@bp.route("/tours/crates/<crate_id>", methods=["GET"])
def flat_get_crate(crate_id):
    return _flat_get(db.crates, crate_id, "Crate", crate_out)


@bp.route("/tours/crates", methods=["GET"])
def flat_list_crates():
    return _flat_list(db.crates, [("tour_id", "tour_id"),
                                  ("current_stop_id", "current_stop_id"),
                                  ("location_status", "location_status")],
                      crate_out)


@bp.route("/tours/shipments/<shipment_id>", methods=["GET"])
def flat_get_shipment(shipment_id):
    return _flat_get(db.shipments, shipment_id, "Shipment", shipment_out)


@bp.route("/tours/shipments", methods=["GET"])
def flat_list_shipments():
    return _flat_list(db.shipments, [("tour_id", "tour_id"),
                                     ("origin_stop_id", "origin_stop_id"),
                                     ("destination_stop_id", "destination_stop_id"),
                                     ("status", "status")], shipment_out)


@bp.route("/tours/reports/<report_id>", methods=["GET"])
def flat_get_report(report_id):
    return _flat_get(db.reports, report_id, "ConditionReport", report_out)


@bp.route("/tours/reports", methods=["GET"])
def flat_list_reports():
    return _flat_list(db.reports, [("shipment_id", "shipment_id"),
                                   ("crate_id", "crate_id"),
                                   ("phase", "phase"),
                                   ("status", "status")], report_out)


@bp.route("/tours/claims/<claim_id>", methods=["GET"])
def flat_get_claim(claim_id):
    return _flat_get(db.claims, claim_id, "DamageClaim", claim_out)


@bp.route("/tours/claims", methods=["GET"])
def flat_list_claims():
    return _flat_list(db.claims, [("shipment_id", "shipment_id"),
                                  ("condition_report_id", "condition_report_id"),
                                  ("status", "status")], claim_out)


@bp.route("/tours/marketing-kits/<kit_id>", methods=["GET"])
def flat_get_kit(kit_id):
    return _flat_get(db.kits, kit_id, "MarketingKit", kit_out)


@bp.route("/tours/marketing-kits", methods=["GET"])
def flat_list_kits():
    return _flat_list(db.kits, [("tour_stop_id", "tour_stop_id"),
                                ("status", "status")], kit_out)


@bp.route("/tours/certificates/<cert_id>", methods=["GET"])
def flat_get_cert(cert_id):
    return _flat_get(db.certs, cert_id, "InsuranceCertificate", cert_out)


@bp.route("/tours/certificates", methods=["GET"])
def flat_list_certs():
    return _flat_list(db.certs, [("tour_id", "tour_id"),
                                 ("tour_stop_id", "tour_stop_id"),
                                 ("status", "status")], cert_out)
