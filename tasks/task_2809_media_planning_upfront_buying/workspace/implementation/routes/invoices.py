"""Client billing and seller settlement (PRD 3.9)."""

from flask import Blueprint

from auth import (
    current_user_id,
    require_advertiser_owner,
    require_roles,
)
from errors import ApiError
from lookup import get
from response import created, ok
from routes.common import listing, read_one
from serializers import serialize
from services import cascades, derive
from store import store
from timeutil import add_days
from validation import body, require_window

bp = Blueprint("invoices", __name__)


@bp.post("/invoices")
@require_roles("AgencyController")
def create_invoice():
    data = body()
    buy_id = data.string("buy_id")
    period_start = data.timestamp("billing_period_start")
    period_end = data.timestamp("billing_period_end")
    require_window(period_start, period_end, "billing_period")

    buy = get("buys", buy_id)
    lines = derive.billable_lines(buy, period_start, period_end)
    if not lines:
        raise ApiError("ERR_NO_BILLABLE_LINES")

    rollups = derive.invoice_rollups(buy, lines)
    credit = derive.make_good_credit_cents(buy)
    fields = dict(
        rollups,
        buy_id=buy["id"],
        billing_period_start=period_start,
        billing_period_end=period_end,
        make_good_credit_cents=credit,
        net_payable_cents=derive.net_payable_cents(
            rollups["gross_billable_cents"], credit
        ),
        client_paid_cents=0,
        seller_remitted_cents=0,
        issued_at=None,
        due_date=None,
        late_payment_flag=False,
        approver_user_id=None,
        client_status="DRAFT",
        seller_status="UNREMITTED",
    )
    fields["max_remittable_cents"] = derive.max_remittable_cents(
        fields, derive.advertiser_of_buy(buy)
    )
    invoice = store.new("invoices", fields)
    return created(serialize("invoices", invoice))


@bp.post("/invoices/<invoice_id>/issue")
@require_roles("AgencyController")
def issue_invoice(invoice_id):
    invoice = get("invoices", invoice_id)
    if invoice["client_status"] == "PAID":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if invoice["client_status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_NOT_IN_EXPECTED_STATE")

    buy = store.buys.get(invoice["buy_id"])
    campaign = store.campaigns.get(buy["campaign_id"]) if buy is not None else None
    if campaign is not None:
        outstanding = _issued_net_payable(campaign, exclude_id=invoice["id"])
        if campaign["funded_cents"] < invoice["net_payable_cents"] + outstanding:
            raise ApiError("ERR_CAMPAIGN_FUNDING_INSUFFICIENT")

    now = store.now()
    advertiser = derive.advertiser_of_buy(buy) if buy is not None else None
    terms = advertiser["payment_terms_days"] if advertiser is not None else 30
    invoice["issued_at"] = now
    invoice["due_date"] = add_days(now, terms)
    invoice["client_status"] = "ISSUED"
    store.touch(invoice)

    if buy is not None and buy["settlement_status"] == "UNBILLED":
        cascades.advance_settlement(buy, "INVOICED")
    if advertiser is not None:
        # The receivable is derived, but the figure the client sees just moved.
        store.touch(advertiser)
    return ok(serialize("invoices", invoice))


def _issued_net_payable(campaign, exclude_id):
    """Net payable already outstanding on the campaign's other live invoices."""
    total = 0
    for buy in derive.buys_of_campaign(campaign["id"]):
        for other in derive.invoices_of_buy(buy["id"]):
            if other["id"] == exclude_id:
                continue
            if other["client_status"] in ("ISSUED", "PARTIALLY_PAID", "PAID"):
                total += other["net_payable_cents"]
    return total


@bp.post("/invoices/<invoice_id>/record-client-payment")
@require_roles("AdvertiserClient")
def record_client_payment(invoice_id):
    data = body()
    amount_cents = data.integer("amount_cents", minimum=1)

    invoice = get("invoices", invoice_id)
    buy = store.buys.get(invoice["buy_id"])
    advertiser = derive.advertiser_of_buy(buy) if buy is not None else None
    if advertiser is not None:
        require_advertiser_owner(advertiser["id"])

    if invoice["client_status"] == "PAID":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if invoice["client_status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVOICE_NOT_IN_EXPECTED_STATE")
    if invoice["client_paid_cents"] + amount_cents > invoice["net_payable_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_INVOICE")

    invoice["client_paid_cents"] += amount_cents
    if invoice["client_paid_cents"] >= invoice["net_payable_cents"]:
        invoice["client_status"] = "PAID"
        # Full client cash releases the whole payable for remittance.
        invoice["max_remittable_cents"] = invoice["seller_payable_cents"]
    else:
        invoice["client_status"] = "PARTIALLY_PAID"
        invoice["max_remittable_cents"] = derive.max_remittable_cents(
            invoice, advertiser
        )

    now = store.now()
    late = invoice["due_date"] is not None and now > invoice["due_date"]
    if late:
        invoice["late_payment_flag"] = True
    store.touch(invoice)

    if late and advertiser is not None:
        advertiser["late_payment_count"] += 1
        # Punctuality is the only thing that drives the credit machine.
        if advertiser["credit_status"] == "ACTIVE":
            advertiser["credit_status"] = "WATCH"
        elif advertiser["credit_status"] == "WATCH":
            advertiser["credit_status"] = "HOLD"
    if advertiser is not None:
        store.touch(advertiser)
    if invoice["client_status"] == "PAID":
        if buy is not None and buy["settlement_status"] == "INVOICED":
            cascades.advance_settlement(buy, "CLIENT_PAID")
    return ok(serialize("invoices", invoice))


@bp.post("/invoices/<invoice_id>/remit-seller")
@require_roles("AgencyController")
def remit_seller(invoice_id):
    data = body()
    amount_cents = data.integer("amount_cents", minimum=1)

    invoice = get("invoices", invoice_id)
    if invoice["seller_status"] == "REMITTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if invoice["client_status"] not in ("ISSUED", "PARTIALLY_PAID", "PAID"):
        raise ApiError("ERR_INVOICE_NOT_IN_EXPECTED_STATE")

    buy = store.buys.get(invoice["buy_id"])
    if buy is not None and current_user_id() == buy["placed_by_user_id"]:
        # The buyer who committed the money may not release it.
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    proposed = invoice["seller_remitted_cents"] + amount_cents
    if (
        proposed > invoice["max_remittable_cents"]
        or proposed > invoice["seller_payable_cents"]
    ):
        raise ApiError("ERR_SEQUENTIAL_LIABILITY_EXCEEDED")

    invoice["seller_remitted_cents"] = proposed
    invoice["approver_user_id"] = current_user_id()
    if proposed >= invoice["seller_payable_cents"]:
        invoice["seller_status"] = "REMITTED"
    else:
        invoice["seller_status"] = "PARTIALLY_REMITTED"
    store.touch(invoice)

    if invoice["seller_status"] == "REMITTED":
        if buy is not None and buy["settlement_status"] == "CLIENT_PAID":
            cascades.advance_settlement(buy, "REMITTED")
    return ok(serialize("invoices", invoice))


@bp.get("/invoices/<invoice_id>")
def get_invoice(invoice_id):
    return read_one("invoices", invoice_id)


@bp.get("/invoices")
def list_invoices():
    return listing(
        "invoices",
        {
            "buy_id": "buy_id",
            "client_status": "client_status",
            "seller_status": "seller_status",
        },
    )
