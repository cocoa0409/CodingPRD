"""OrderInvoice endpoints: pricing, invoicing and ship-and-debit credits."""
import calc
import serialize
import store
import validate as v
from auth import endpoint
from constants import TIER_MARGIN_CEILING_PCT
from errors import ApiError
from guards import (check_not_suspended, find, find_partner, find_registration,
                    invalid_state)
from response import created, filtered, listing, object_response


def _recompute_partner_revenue(partner):
    if partner is None:
        return
    before = partner["trailing_revenue_cents"]
    calc.recompute_revenue(partner)
    if before != partner["trailing_revenue_cents"]:
        store.touch(partner)


def register(app):
    @app.route("/order-invoices", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def create_order():
        body = v.body()
        # existence (3), body foreign keys in declaration order
        partner_ref = v.fk_candidate(body, "partner_id")
        partner = find_partner(partner_ref) if partner_ref is not None else None
        registration_ref = v.fk_candidate(body, "registration_id")
        registration = (find_registration(registration_ref)
                        if registration_ref is not None else None)
        # request shape (5)
        partner_id = v.req_string(body, "partner_id")
        order_type = v.req_enum(body, "order_type", ("STOCKING", "DROP_SHIP"))
        list_amount_cents = v.req_int(body, "list_amount_cents", minimum=1)
        registration_id = v.opt_string(body, "registration_id")
        # partner-type eligibility (6)
        if order_type == "STOCKING" and partner["partner_type"] != "DISTRIBUTOR":
            raise ApiError("ERR_PARTNER_TYPE_NOT_ELIGIBLE",
                           "Only a DISTRIBUTOR may place a STOCKING order.")
        # program standing (13)
        check_not_suspended(partner)
        instant = store.now()
        margin_pct, band, invoice_amount, margin_value = calc.resolve_margin(
            partner, order_type, list_amount_cents, registration, instant)
        row = {
            "partner_id": partner_id,
            "registration_id": registration_id,
            "order_type": order_type,
            "list_amount_cents": list_amount_cents,
            "margin_pct": margin_pct,
            "volume_band": band,
            "invoice_amount_cents": invoice_amount,
            "margin_value_cents": margin_value,
            "credit_memo_cents": 0,
            "status": "PENDING",
            "invoiced_at": None,
            "credit_reason": None,
        }
        store.insert("orders", row)
        return created(serialize.order(row))

    @app.route("/order-invoices", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_orders():
        rows = store.ordered(store.all_rows("orders"))
        rows = filtered(rows, [("partner_id", "partner_id"),
                               ("registration_id", "registration_id"),
                               ("status", "status"),
                               ("order_type", "order_type")])
        return listing(rows, serialize.order)

    @app.route("/order-invoices/<order_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_order(order_id):
        row = find("orders", order_id)
        return object_response(serialize.order(row))

    @app.route("/order-invoices/<order_id>/invoice", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def invoice_order(order_id):
        order = find("orders", order_id)
        v.body()
        # state precondition (9)
        if order["status"] != "PENDING":
            raise invalid_state("Only a PENDING order can be invoiced.")
        partner = store.get("partners", order["partner_id"])
        # program standing (13)
        check_not_suspended(partner)
        order["status"] = "INVOICED"
        order["invoiced_at"] = store.now()
        store.touch(order)
        _recompute_partner_revenue(partner)
        return object_response(serialize.order(order))

    @app.route("/order-invoices/<order_id>/credit-memo", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def credit_order(order_id):
        order = find("orders", order_id)
        body = v.body()
        credit_memo_cents = v.req_int(body, "credit_memo_cents", minimum=0)
        credit_reason = v.req_string(body, "credit_reason", non_empty=False)
        # state precondition (9)
        if order["status"] not in ("INVOICED", "CREDITED"):
            raise invalid_state("A credit memo needs an INVOICED order.")
        partner = store.get("partners", order["partner_id"])
        list_amount = order["list_amount_cents"]
        reduced = order["invoice_amount_cents"] - credit_memo_cents
        # margin ceiling (20) - PRD 2.8 puts the ceiling above the credit size
        effective = calc.effective_margin_pct(list_amount, reduced)
        if effective > TIER_MARGIN_CEILING_PCT[partner["tier"]]:
            raise ApiError("ERR_MARGIN_CEILING_EXCEEDED",
                           "The credit would breach the tier's margin ceiling.")
        # credit size (21)
        if not (0 < credit_memo_cents < order["invoice_amount_cents"]):
            raise ApiError("ERR_CREDIT_EXCEEDS_INVOICE",
                           "The credit must be above 0 and below the invoiced amount.")
        order["status"] = "CREDITED"
        order["credit_memo_cents"] = order["credit_memo_cents"] + credit_memo_cents
        order["invoice_amount_cents"] = reduced
        order["margin_value_cents"] = list_amount - reduced
        order["margin_pct"] = effective
        order["credit_reason"] = credit_reason
        store.touch(order)
        _recompute_partner_revenue(partner)
        return object_response(serialize.order(order))
