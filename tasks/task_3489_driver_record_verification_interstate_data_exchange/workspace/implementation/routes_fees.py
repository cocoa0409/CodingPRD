"""Association dues: assessment, dispute, settlement, and audit (PRD section
3.8)."""
from flask import Blueprint

import calc
import serialize
import store
import validation as v
from errors import err
from response import ok

bp = Blueprint("fees", __name__, url_prefix="/driver-exchange")


@bp.post("/fee-invoices")
def create_fee_invoice():
    """Issue the annual dues invoice. The invoiced jurisdiction must be
    ACTIVE; certified_count_at_issue is pinned at issuance and drives the
    provisional multiplier."""
    _, role = v.auth_context()
    v.require_role(role, {"AssociationAdmin"})
    data = v.body()
    jurisdiction_id = v.req_string(data, "jurisdiction_id")
    fiscal_year = v.req_int(data, "fiscal_year")
    projected_volume = v.req_int(data, "projected_volume", 0)
    jurisdiction = store.db.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        raise err("ERR_JURISDICTION_NOT_FOUND",
                  "no jurisdiction with id %s" % jurisdiction_id)
    if jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "invoicing requires an ACTIVE jurisdiction")
    pinned = jurisdiction["certified_systems_count"]
    invoice = {
        "id": store.new_id(),
        "jurisdiction_id": jurisdiction_id,
        "fiscal_year": fiscal_year,
        "projected_volume": projected_volume,
        "certified_count_at_issue": pinned,
        "provisional_amount_cents": calc.provisional_amount_cents(projected_volume, pinned),
        "status": "ISSUED",
        "dispute_reason": None,
        "settled_amount_cents": None,
        "actual_volume_quarters": None,
        "final_amount_cents": None,
        "adjustment_amount_cents": None,
    }
    store.stamp(invoice)
    store.db.fee_invoices[invoice["id"]] = invoice
    return ok(serialize.fee_invoice(invoice), 201)


def _invoice_or_404(iid):
    invoice = store.db.fee_invoices.get(iid)
    if invoice is None:
        raise err("ERR_INVOICE_NOT_FOUND", "no fee invoice with id %s" % iid)
    return invoice


@bp.post("/fee-invoices/<iid>/dispute")
def dispute_invoice(iid):
    """ISSUED -> DISPUTED by the invoiced jurisdiction's registrar."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    reason = v.req_string(data, "reason")
    invoice = _invoice_or_404(iid)
    if invoice["jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "only the invoiced jurisdiction may dispute")
    if invoice["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "only an ISSUED invoice may be disputed")
    invoice["status"] = "DISPUTED"
    invoice["dispute_reason"] = reason
    store.touch(invoice)
    return ok(serialize.fee_invoice(invoice))


@bp.post("/fee-invoices/<iid>/reissue")
def reissue_invoice(iid):
    """DISPUTED -> ISSUED with a corrected projected volume; the provisional
    amount is recomputed with the ORIGINAL pinned certified_count_at_issue."""
    _, role = v.auth_context()
    v.require_role(role, {"AssociationAdmin"})
    data = v.body()
    projected_volume = v.req_int(data, "projected_volume", 0)
    invoice = _invoice_or_404(iid)
    if invoice["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "only a DISPUTED invoice may be reissued")
    invoice["projected_volume"] = projected_volume
    invoice["provisional_amount_cents"] = calc.provisional_amount_cents(
        projected_volume, invoice["certified_count_at_issue"])
    invoice["dispute_reason"] = None
    invoice["status"] = "ISSUED"
    store.touch(invoice)
    return ok(serialize.fee_invoice(invoice))


@bp.post("/fee-invoices/<iid>/settle")
def settle_invoice(iid):
    """ISSUED -> SETTLED; settlement is exact-change only: amount_cents must
    equal provisional_amount_cents to the cent."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    amount_cents = v.req_int(data, "amount_cents")
    invoice = _invoice_or_404(iid)
    if invoice["jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "only the invoiced jurisdiction may settle")
    if invoice["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "only an ISSUED invoice may be settled")
    if amount_cents != invoice["provisional_amount_cents"]:
        raise err("ERR_FEE_AMOUNT_MISMATCH",
                  "amount_cents must equal provisional_amount_cents exactly")
    invoice["status"] = "SETTLED"
    invoice["settled_amount_cents"] = amount_cents
    store.touch(invoice)
    return ok(serialize.fee_invoice(invoice))


@bp.post("/fee-invoices/<iid>/finalize-audit")
def finalize_audit(iid):
    """SETTLED -> AUDITED: per-quarter rounded charges summed into
    final_amount_cents with the multiplier recomputed from the CURRENT
    certified_systems_count; adjustment = final - settled."""
    _, role = v.auth_context()
    v.require_role(role, {"AuditAuthority"})
    data = v.body()
    quarters = data.get("actual_volume_quarters")
    if (not isinstance(quarters, list) or len(quarters) != 4
            or any(isinstance(q, bool) or not isinstance(q, int) or q < 0
                   for q in quarters)):
        raise err("ERR_INVALID_REQUEST",
                  "actual_volume_quarters must be exactly 4 non-negative integers")
    invoice = _invoice_or_404(iid)
    if invoice["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "only a SETTLED invoice may be audited")
    jurisdiction = store.db.jurisdictions.get(invoice["jurisdiction_id"])
    current_count = jurisdiction["certified_systems_count"] if jurisdiction is not None else 0
    final = calc.audited_final_amount_cents(quarters, current_count)
    invoice["actual_volume_quarters"] = list(quarters)
    invoice["final_amount_cents"] = final
    invoice["adjustment_amount_cents"] = final - invoice["settled_amount_cents"]
    invoice["status"] = "AUDITED"
    store.touch(invoice)
    return ok(serialize.fee_invoice(invoice))
