"""Fee invoices and care transitions."""

from db import STORE
from errors import ApiError, invalid_reference, invalid_state
from services import billing, common, intake


# ---------------------------------------------------------------------------
# M11 -- FeeInvoice
# ---------------------------------------------------------------------------
def invoice(ident):
    return STORE.need("FeeInvoice", ident, "FeeInvoice")


def create_invoice(payload):
    client_id = payload.get("client_account_id")
    client_row = billing.client_of(client_id)
    period = payload.get("billing_period")
    billing.billing_period_bounds(period)
    if client_row["account_status"] != "ACTIVE":
        raise ApiError(
            "ERR_CLIENT_NOT_ACTIVE",
            "Billable work may not be created against a non-ACTIVE client.",
        )

    for other in billing.invoices_of_client(client_id):
        if other["billing_period"] != period:
            continue
        if other["invoice_status"] == "VOID":
            continue
        raise ApiError(
            "ERR_DUPLICATE_SAVINGS_ATTRIBUTION",
            "That enrollment and claim window would enter a second invoice.",
        )

    from db import create

    row = create("FeeInvoice", {
        "client_account_id": client_id,
        "billing_period": period,
        "billing_model_snapshot": None,
        "milestone_member_count": 0,
        "milestone_engagement_component_cents": 0,
        "savings_share_component_cents": 0,
        "additional_fee_component_cents": 0,
        "recalculated_component_cents": 0,
        "provisional_amount_cents": 0,
        "final_amount_cents": 0,
        "net_delta_cents": 0,
        "finalized_total_cents": None,
        "invoice_status": "DRAFT",
    })
    row["_milestone_group"] = [
        e["id"] for e in billing.adhered_group(client_id)
    ]
    billing.build_invoice_components(row)
    STORE.touch("ClientAccount", client_row)
    return row


def finalize_invoice(invoice_id):
    row = invoice(invoice_id)
    if row["invoice_status"] != "DRAFT":
        raise invalid_state("Only a DRAFT invoice can be finalized.")
    client_row = billing.client_of(row["client_account_id"])
    if client_row["account_status"] != "ACTIVE":
        raise invalid_state("The client must be ACTIVE to finalize an invoice.")
    billing.build_invoice_components(row)
    if row["additional_fee_component_cents"] != 0:
        raise ApiError(
            "ERR_INVOICE_UNRECONCILED",
            "Every reconciliation delta must be reconciled before finalization.",
        )
    row["billing_model_snapshot"] = client_row["billing_model"]
    row["invoice_status"] = "FINALIZED"
    billing.build_invoice_components(row)
    row["finalized_total_cents"] = row["final_amount_cents"]
    STORE.touch("FeeInvoice", row)
    return row


def void_invoice(invoice_id):
    row = invoice(invoice_id)
    if row["invoice_status"] != "DRAFT":
        raise invalid_state("Only a DRAFT invoice can be voided.")
    row["invoice_status"] = "VOID"
    STORE.touch("FeeInvoice", row)
    return row


def reopen_invoice(invoice_id):
    row = invoice(invoice_id)
    if row["invoice_status"] == "VOID":
        raise ApiError(
            "ERR_INVOICE_ALREADY_VOID", "A voided invoice can never be reopened."
        )
    if row["invoice_status"] != "FINALIZED":
        raise invalid_state("Only a FINALIZED invoice can be reopened.")
    client_row = billing.client_of(row["client_account_id"])
    if client_row["account_status"] != "ACTIVE":
        raise invalid_state("The client must be ACTIVE to reopen an invoice.")
    row["invoice_status"] = "DRAFT"
    row["finalized_total_cents"] = None
    STORE.touch("FeeInvoice", row)
    return row