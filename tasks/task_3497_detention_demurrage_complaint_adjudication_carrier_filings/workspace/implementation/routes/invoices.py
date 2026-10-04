"""DemurrageDetentionInvoice: issuance with computed charge, list, get,
mark-paid (PRD §3.5-§3.6)."""
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
    ERR_TARIFF_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_ACCESS,
    ERR_INVOICE_MISSING_REQUIRED_ELEMENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_INVOICE_DATES,
    ERR_CARRIER_NOT_ACTIVE,
    ERR_TARIFF_NOT_PUBLISHED,
    ERR_CONTRACT_NOT_EFFECTIVE,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_LATE_INVOICE_ISSUANCE,
    ERR_TARIFF_CARRIER_MISMATCH,
    ERR_BILLED_PARTY_NOT_CONTRACT_PARTY,
    ERR_INVOICE_NOT_PAYABLE,
)
from serialization import ser_invoice
from services import calc
from services.cascades import has_active_license
from store import touch
from util import body, req_str, req_int, req_enum, req_dt, opt_int
from constants import INVOICE_ISSUANCE_WINDOW_DAYS

bp = Blueprint("invoices", __name__)

CHARGE_BASES = ("TARIFF", "SERVICE_CONTRACT")
LICENSABLE_ORG_TYPES = ("NVOCC", "OFF")


@bp.post("/fmc/carriers/<carrierId>/invoices")
def issue_invoice(carrierId):
    uid, _role = require_roles("CarrierRep")
    carrier = store.carriers.get(carrierId)
    if carrier is None:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    if uid != carrierId:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "a CarrierRep may issue invoices only for its own organization")
    b = body()
    # Rung 5: existence of body-referenced entities that are present.
    billed_party = b.get("billed_party_shipper_id")
    if isinstance(billed_party, str) and billed_party not in store.shippers:
        fail(ERR_SHIPPER_NOT_FOUND, "shipper account not found: %s" % billed_party)
    tariff_id = b.get("tariff_id")
    if isinstance(tariff_id, str) and tariff_id not in store.tariffs:
        fail(ERR_TARIFF_NOT_FOUND, "tariff publication not found: %s" % tariff_id)
    contract_id = b.get("service_contract_id")
    if isinstance(contract_id, str) and contract_id not in store.contracts:
        fail(ERR_CONTRACT_NOT_FOUND, "service contract not found: %s" % contract_id)

    # Rung 6: required billing elements and scalar sanity.
    MISSING = ERR_INVOICE_MISSING_REQUIRED_ELEMENT
    invoice_number = req_str(b, "invoice_number", MISSING)
    charge_basis = req_enum(b, "charge_basis", CHARGE_BASES, MISSING)
    billed_party_shipper_id = req_str(b, "billed_party_shipper_id", MISSING)
    container_number = req_str(b, "container_number", MISSING)
    port_code = req_str(b, "port_code", MISSING)
    availability_date = req_dt(b, "availability_date", missing_err=MISSING)
    return_date = req_dt(b, "return_date", missing_err=MISSING)
    last_accrual_date = req_dt(b, "last_accrual_date", missing_err=MISSING)
    if charge_basis == "TARIFF":
        if tariff_id is None:
            fail(MISSING, "tariff_id is required when charge_basis is TARIFF")
        if not isinstance(tariff_id, str):
            fail(ERR_INVALID_REQUEST, "tariff_id must be a string")
    else:
        if contract_id is None:
            fail(MISSING,
                 "service_contract_id is required when charge_basis is SERVICE_CONTRACT")
        if not isinstance(contract_id, str):
            fail(ERR_INVALID_REQUEST, "service_contract_id must be a string")
    government_hold_days = opt_int(b, "government_hold_days", 0, lo=0)
    appointment_unavailable_days = opt_int(b, "appointment_unavailable_days", 0, lo=0)

    now = CLOCK.now()
    if not (availability_date <= return_date <= last_accrual_date <= now):
        fail(ERR_INVALID_INVOICE_DATES,
             "availability_date <= return_date <= last_accrual_date <= issuance "
             "must hold")

    # Rung 7: carrier standing.
    if carrier["status"] != "ACTIVE":
        fail(ERR_CARRIER_NOT_ACTIVE, "carrier is not ACTIVE")
    # Rung 8: tariff state, then contract state, then license state.
    governing = None
    if charge_basis == "TARIFF":
        governing = store.tariffs[tariff_id]
        if governing["publication_status"] != "PUBLISHED":
            fail(ERR_TARIFF_NOT_PUBLISHED,
                 "TARIFF-basis invoicing requires the tariff to be PUBLISHED")
    else:
        governing = store.contracts[contract_id]
        if governing["contract_status"] != "EFFECTIVE":
            fail(ERR_CONTRACT_NOT_EFFECTIVE,
                 "SERVICE_CONTRACT-basis invoicing requires the contract to be "
                 "EFFECTIVE")
    if carrier["org_type"] in LICENSABLE_ORG_TYPES and not has_active_license(carrierId):
        fail(ERR_LICENSE_NOT_ACTIVE,
             "an NVOCC/OFF carrier must hold an ACTIVE OTI license to issue invoices")
    # Rung 9: issuance window.
    if now > last_accrual_date + timedelta(days=INVOICE_ISSUANCE_WINDOW_DAYS):
        fail(ERR_LATE_INVOICE_ISSUANCE,
             "invoice issued more than 30 days after last_accrual_date")
    # Rung 10: cross-reference consistency.
    if charge_basis == "TARIFF":
        if governing["carrier_id"] != carrierId:
            fail(ERR_TARIFF_CARRIER_MISMATCH,
                 "the named tariff belongs to a different carrier")
        free_time_days = governing["free_time_days"]
        per_diem_rate_cents = governing["per_diem_rate_cents"]
        accrual_method = governing["accrual_method"]
    else:
        if (
            governing["carrier_id"] != carrierId
            or governing["shipper_id"] != billed_party_shipper_id
        ):
            fail(ERR_BILLED_PARTY_NOT_CONTRACT_PARTY,
                 "the contract must belong to the invoicing carrier with the "
                 "billed party as its contracting shipper")
        free_time_days = governing["negotiated_free_time_days"]
        per_diem_rate_cents = governing["negotiated_per_diem_rate_cents"]
        accrual_method = governing["negotiated_accrual_method"]

    billable_days = calc.invoice_billable_days(
        free_time_days, accrual_method, availability_date, return_date
    )
    amount_cents = calc.invoice_amount_cents(billable_days, per_diem_rate_cents)

    rec = store.base_record()
    rec.update(
        carrier_id=carrierId,
        invoice_number=invoice_number,
        charge_basis=charge_basis,
        tariff_id=tariff_id if charge_basis == "TARIFF" else None,
        service_contract_id=contract_id if charge_basis == "SERVICE_CONTRACT" else None,
        billed_party_shipper_id=billed_party_shipper_id,
        container_number=container_number,
        port_code=port_code,
        availability_date=availability_date,
        return_date=return_date,
        last_accrual_date=last_accrual_date,
        government_hold_days=government_hold_days,
        appointment_unavailable_days=appointment_unavailable_days,
        free_time_days=free_time_days,
        per_diem_rate_cents=per_diem_rate_cents,
        accrual_method=accrual_method,
        billable_days=billable_days,
        amount_cents=amount_cents,
        issued_at=now,
        invoice_status="ISSUED",
    )
    store.invoices[rec["id"]] = rec
    return ok_object(ser_invoice(rec), 201)


@bp.get("/fmc/invoices")
def list_invoices():
    any_role()
    carrier_id = request.args.get("carrier_id")
    billed_party = request.args.get("billed_party_shipper_id")
    tariff_id = request.args.get("tariff_id")
    contract_id = request.args.get("service_contract_id")
    recs = list(store.invoices.values())
    if carrier_id is not None:
        recs = [i for i in recs if i["carrier_id"] == carrier_id]
    if billed_party is not None:
        recs = [i for i in recs if i["billed_party_shipper_id"] == billed_party]
    if tariff_id is not None:
        recs = [i for i in recs if i["tariff_id"] == tariff_id]
    if contract_id is not None:
        recs = [i for i in recs if i["service_contract_id"] == contract_id]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_invoice(i) for i in page], limit, offset, total)


@bp.get("/fmc/invoices/<invoiceId>")
def get_invoice(invoiceId):
    any_role()
    inv = store.invoices.get(invoiceId)
    if inv is None:
        fail(ERR_INVOICE_NOT_FOUND, "invoice not found: %s" % invoiceId)
    return ok_object(ser_invoice(inv))


@bp.post("/fmc/invoices/<invoiceId>/mark-paid")
def mark_paid(invoiceId):
    uid, _role = require_roles("ShipperRep")
    inv = store.invoices.get(invoiceId)
    if inv is None:
        fail(ERR_INVOICE_NOT_FOUND, "invoice not found: %s" % invoiceId)
    if uid != inv["billed_party_shipper_id"]:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "only the billed party may mark the invoice paid")
    if inv["invoice_status"] != "ISSUED":
        fail(ERR_INVOICE_NOT_PAYABLE, "mark-paid requires the invoice to be ISSUED")
    inv["invoice_status"] = "PAID"
    touch(inv)
    return ok_object(ser_invoice(inv))
