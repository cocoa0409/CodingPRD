"""Logical clock endpoint.

Setting the clock recomputes every time-derived status in the system:
CertificationRecord.status, SupportAgreement coverage and ServiceOrder SLA
outcomes.  The startup default is exactly 2026-09-01T00:00:00Z and the clock
never silently reverts to real wall-clock time.
"""

from __future__ import annotations

import db
import registry as reg
import response as resp
from request import Request
from services import core as svc

BASE = "/dealer-network"

STAFF_ROLES = [
    "DealerNetworkManager",
    "DealerPerformanceReviewer",
    "PartsManager",
    "RebuildProgramSpecialist",
    "ServiceTechnicianSupervisor",
    "DealerSalesManager",
    "FinancePartner",
]


def set_current_utc(request: Request):
    to_iso8601 = request.datetime("to_iso8601")
    db.set_clock(to_iso8601)

    # Recompute every time-derived status across the system.
    svc.recompute_all_recurrences()
    for record in db.rows("certification_records"):
        svc.touch(record)
    for agreement in db.rows("dealer_agreements"):
        svc.refresh_agreement_derived(agreement)
    for dealer in db.rows("dealers"):
        svc.recompute_certified_family_count(dealer)
    for support in db.rows("support_agreements"):
        svc.refresh_serial_coverage(support["machine_serial"])
    for commitment in db.rows("parts_commitments"):
        svc.compute_stocking_mandate(commitment)
    svc.recompute_sla_outcomes()

    return resp.ok({"current_utc": db.clock_iso(db.STATE["current_utc"])}), 200


def register_routes():
    reg.register(
        "POST",
        BASE + "/_clock/set_current_utc",
        set_current_utc,
        STAFF_ROLES,
        200,
        ["to_iso8601"],
        "set_current_utc",
    )