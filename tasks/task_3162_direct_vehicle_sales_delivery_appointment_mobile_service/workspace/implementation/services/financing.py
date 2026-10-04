"""Financing applications: submission, decision, contract review, funding (PRD 3.5)."""

from db import DB, new_id, FINANCEABLE_MAX_CENTS
from errors import fail, fmt
from repository import find, touch
from services import calculation as calc
from services import ledger
from services.order_flow import FINANCEABLE_ORDER_STATES


def submit_application(order, term_months, down_payment_cents=0,
                       include_trade_in_credit=False):
    application = {
        "id": new_id(),
        "order_id": order["id"],
        "buyer_id": order["buyer_id"],
        "term_months": term_months,
        "down_payment_cents": down_payment_cents,
        "include_trade_in_credit": include_trade_in_credit,
        "credit_band": None,
        "apr_bps": None,
        "amount_financed_cents": 0,
        "monthly_payment_cents": 0,
        "decision_at": None,
        "status": "SUBMITTED",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    # PRD 3.5 pins the financed principal to three inputs, and the created
    # application carries the resulting figure.
    application["amount_financed_cents"] = calc.amount_financed_cents(application, order)
    DB.applications[application["id"]] = application
    return application


def decide(application, outcome):
    if application["status"] not in ("SUBMITTED", "CONDITIONALLY_APPROVED"):
        fail("ERR_APPLICATION_NOT_SUBMITTED")
    order = find("order", application["order_id"])
    buyer = find("buyer", application["buyer_id"])
    if outcome == "DECLINED":
        if application["status"] == "CONDITIONALLY_APPROVED":
            appointment = find("appointment", order.get("_appointment_id"))
            for row in DB.appointments.values():
                if row["order_id"] == order["id"] and row["status"] not in ("COMPLETED", "CANCELLED"):
                    appointment = row
                    break
            if appointment is not None:
                center = find("center", appointment["delivery_center_id"])
                if center is not None:
                    center["booked_slot_count"] = max(0, center["booked_slot_count"] - 1)
                    touch(center)
        application["status"] = "DECLINED"
        if buyer is not None:
            buyer["credit_band"] = "SUBPRIME"
            touch(buyer)
        touch(application)
        return application

    if application["status"] != "SUBMITTED":
        fail("ERR_APPLICATION_NOT_SUBMITTED")
    if not buyer["identity_verified"]:
        fail("ERR_BUYER_NOT_VERIFIED")
    band = select_band(buyer)
    max_financeable = FINANCEABLE_MAX_CENTS.get(band, FINANCEABLE_MAX_CENTS["NEAR_PRIME"])
    requested = order["order_total_due_cents"] - application["down_payment_cents"]
    if requested > max_financeable:
        fail("ERR_FINANCE_EXCEEDS_VEHICLE_VALUE")
    bps, principal, payment = calc.pricing_for(application, order, band)
    application["apr_bps"] = bps
    application["credit_band"] = band
    application["amount_financed_cents"] = principal
    application["monthly_payment_cents"] = payment
    application["decision_at"] = DB.now
    application["status"] = "CONDITIONALLY_APPROVED"
    buyer["credit_band"] = band
    touch(buyer)
    touch(application)
    return application


def select_band(buyer):
    existing = buyer.get("credit_band")
    if existing in ("PRIME", "SUBPRIME"):
        return existing
    return "NEAR_PRIME"


def contract_review(application):
    if application["status"] not in ("SUBMITTED", "CONDITIONALLY_APPROVED"):
        fail("ERR_APPLICATION_NOT_SUBMITTED")
    order = find("order", application["order_id"])
    if order["status"] not in FINANCEABLE_ORDER_STATES:
        fail("ERR_ORDER_NOT_FINANCEABLE")
    buyer = find("buyer", application["buyer_id"])
    band = application.get("credit_band") or select_band(buyer)
    bps, principal, payment = calc.pricing_for(application, order, band)
    if application.get("apr_bps") is None:
        application["apr_bps"] = bps
        application["monthly_payment_cents"] = payment
        application["credit_band"] = band
        buyer["credit_band"] = band
        touch(buyer)
    application["amount_financed_cents"] = principal
    application["status"] = "CONTRACT_PENDING"
    touch(application)
    return application


def fund(application):
    if application["status"] != "CONTRACT_PENDING":
        fail("ERR_APPLICATION_NOT_SUBMITTED")
    order = find("order", application["order_id"])
    if calc.delivery_readiness_posture(order) != "READY":
        fail("ERR_ORDER_DELIVERY_NOT_READY")
    unresolved = [a for a in calc.visible_appraisals(order["id"])
                  if a["status"] != "ACCEPTED"]
    if unresolved:
        fail("ERR_TRADE_IN_NOT_RESOLVED")
    application["status"] = "FUNDED"
    touch(application)
    calc.recompute_posture(order)
    touch(order)
    return application