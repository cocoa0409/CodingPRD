"""ServiceContract: filing (timely within 30 days of execution), list, get
(PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import store
from auth import require_roles, any_role
from clock import CLOCK
from envelope import ok_object, ok_list, paginate
from errors import (
    fail,
    ERR_CARRIER_NOT_FOUND,
    ERR_SHIPPER_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_ACCESS,
    ERR_CARRIER_NOT_ACTIVE,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_LATE_SERVICE_CONTRACT_FILING,
)
from serialization import ser_contract
from services.cascades import has_active_license
from util import body, req_str, req_int, req_enum, req_dt
from constants import SERVICE_CONTRACT_FILING_WINDOW_DAYS

bp = Blueprint("contracts", __name__)

ACCRUAL_METHODS = ("CALENDAR", "WORKING_DAY")
LICENSABLE_ORG_TYPES = ("NVOCC", "OFF")


@bp.post("/fmc/carriers/<carrierId>/service-contracts")
def file_contract(carrierId):
    uid, _role = require_roles("CarrierRep")
    carrier = store.carriers.get(carrierId)
    if carrier is None:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    if uid != carrierId:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "a CarrierRep may file contracts only for its own organization")
    b = body()
    # Rung 5 (body-reference existence) precedes rung 6 (scalar sanity).
    sid = b.get("shipper_id")
    if isinstance(sid, str) and sid not in store.shippers:
        fail(ERR_SHIPPER_NOT_FOUND, "shipper account not found: %s" % sid)
    contract_reference = req_str(b, "contract_reference")
    shipper_id = req_str(b, "shipper_id")
    agreed_at = req_dt(b, "agreed_at")
    duration_months = req_int(b, "duration_months", lo=1)
    minimum_quantity_commitment = req_int(b, "minimum_quantity_commitment", lo=1)
    negotiated_free_time_days = req_int(b, "negotiated_free_time_days", lo=0)
    negotiated_per_diem_rate_cents = req_int(b, "negotiated_per_diem_rate_cents", lo=1)
    negotiated_accrual_method = req_enum(b, "negotiated_accrual_method", ACCRUAL_METHODS)

    if carrier["status"] != "ACTIVE":
        fail(ERR_CARRIER_NOT_ACTIVE, "carrier is not ACTIVE")
    if carrier["org_type"] in LICENSABLE_ORG_TYPES and not has_active_license(carrierId):
        fail(ERR_LICENSE_NOT_ACTIVE,
             "an NVOCC/OFF carrier must hold an ACTIVE OTI license to file "
             "service contracts")
    now = CLOCK.now()
    if now > agreed_at + timedelta(days=SERVICE_CONTRACT_FILING_WINDOW_DAYS):
        fail(ERR_LATE_SERVICE_CONTRACT_FILING,
             "service contract filed more than 30 days after agreed_at")

    rec = store.base_record()
    rec.update(
        carrier_id=carrierId,
        contract_reference=contract_reference,
        shipper_id=shipper_id,
        agreed_at=agreed_at,
        duration_months=duration_months,
        minimum_quantity_commitment=minimum_quantity_commitment,
        negotiated_free_time_days=negotiated_free_time_days,
        negotiated_per_diem_rate_cents=negotiated_per_diem_rate_cents,
        negotiated_accrual_method=negotiated_accrual_method,
        filed_at=now,
        contract_status="EFFECTIVE",
    )
    store.contracts[rec["id"]] = rec
    return ok_object(ser_contract(rec), 201)


@bp.get("/fmc/service-contracts")
def list_contracts():
    any_role()
    carrier_id = request.args.get("carrier_id")
    shipper_id = request.args.get("shipper_id")
    recs = list(store.contracts.values())
    if carrier_id is not None:
        recs = [c for c in recs if c["carrier_id"] == carrier_id]
    if shipper_id is not None:
        recs = [c for c in recs if c["shipper_id"] == shipper_id]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_contract(c) for c in page], limit, offset, total)


@bp.get("/fmc/service-contracts/<contractId>")
def get_contract(contractId):
    any_role()
    c = store.contracts.get(contractId)
    if c is None:
        fail(ERR_CONTRACT_NOT_FOUND, "service contract not found: %s" % contractId)
    return ok_object(ser_contract(c))
