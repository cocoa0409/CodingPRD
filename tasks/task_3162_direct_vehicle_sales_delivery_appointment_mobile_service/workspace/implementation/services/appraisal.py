"""Trade-in appraisal, offer, expiry, acceptance and reappraisal (PRD 3.3)."""

from db import DB, new_id
from errors import fail, fmt
from repository import find, touch
from services import calculation as calc
from services import ledger
from services.order_flow import APPRAISABLE_ORDER_STATES


def create_appraisal(order, trade_vin, mileage, gross_offer_cents,
                     reconditioning_estimate_cents, offer_valid_until):
    appraisal = {
        "id": new_id(),
        "order_id": order["id"],
        "trade_vin": trade_vin,
        "mileage": mileage,
        "gross_offer_cents": gross_offer_cents,
        "reconditioning_estimate_cents": reconditioning_estimate_cents,
        "offer_valid_until": offer_valid_until,
        "net_credit_cents": calc.trade_in_net_credit_cents(
            gross_offer_cents, reconditioning_estimate_cents, mileage),
        "status": "DRAFT",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.appraisals[appraisal["id"]] = appraisal
    return appraisal


def appraise(appraisal, order):
    if appraisal["status"] != "DRAFT":
        fail("ERR_APPRAISAL_NOT_DRAFT")
    if order["status"] not in APPRAISABLE_ORDER_STATES:
        fail("ERR_ORDER_NOT_APPRAISABLE")
    appraisal["net_credit_cents"] = calc.trade_in_net_credit_cents(
        appraisal["gross_offer_cents"], appraisal["reconditioning_estimate_cents"],
        appraisal["mileage"])
    appraisal["status"] = "APPRAISED"
    touch(appraisal)
    return appraisal


def offer(appraisal, order):
    if appraisal["status"] not in ("DRAFT", "APPRAISED"):
        fail("ERR_INVALID_STATE")
    if not appraisal["offer_valid_until"] > DB.now:
        fail("ERR_APPRAISAL_OFFER_EXPIRED")
    current = calc.current_estimate(order["id"])
    if current is None:
        current = calc.latest_estimate(order["id"])
    if (current is not None and current["estimate_state"] in ("PROVISIONAL", "FIRM")
            and appraisal["offer_valid_until"] < current["window_end"]):
        # PRD 3.3: only an offer that lapses before the *projected* window end —
        # that is, one whose window is still a live promise — is refused here.
        # A window already consumed by a booking or a supersession is no longer a
        # live projection, so the gate does not bite on it.
        fail("ERR_APPRAISAL_EXPIRES_BEFORE_DELIVERY")
    appraisal["status"] = "OFFERED"
    ledger.write_entry(order["id"], "TRADE_IN_CREDIT",
                       appraisal["net_credit_cents"], "TRADE_IN_OFFER_PUBLISHED")
    touch(appraisal)
    return appraisal


def accept(appraisal, order):
    if appraisal["status"] != "OFFERED":
        fail("ERR_INVALID_STATE")
    if not appraisal["offer_valid_until"] > DB.now:
        fail("ERR_APPRAISAL_OFFER_EXPIRED")
    appraisal["status"] = "ACCEPTED"
    touch(appraisal)
    for application in DB.applications.values():
        if application["order_id"] != order["id"]:
            continue
        if not application["include_trade_in_credit"]:
            continue
        if application["status"] in ("FUNDED", "DECLINED"):
            continue
        band = application.get("credit_band") or "NEAR_PRIME"
        bps, principal, payment = calc.pricing_for(application, order, band)
        application["amount_financed_cents"] = principal
        application["monthly_payment_cents"] = payment
        if application.get("apr_bps") is not None:
            application["apr_bps"] = bps
        touch(application)
    return appraisal


def reject(appraisal, order):
    if appraisal["status"] != "OFFERED":
        fail("ERR_INVALID_STATE")
    appraisal["status"] = "REJECTED"
    ledger.write_entry(order["id"], "TRADE_IN_CREDIT_REVERSAL",
                       -appraisal["net_credit_cents"], "TRADE_IN_OFFER_REJECTED")
    touch(appraisal)
    return appraisal


def reappraise(appraisal, order, gross_offer_cents, reconditioning_estimate_cents,
               offer_valid_until):
    if appraisal["status"] != "EXPIRED":
        fail("ERR_INVALID_STATE")
    if not offer_valid_until > DB.now:
        fail("ERR_APPRAISAL_OFFER_EXPIRED")
    appraisal["gross_offer_cents"] = gross_offer_cents
    appraisal["reconditioning_estimate_cents"] = reconditioning_estimate_cents
    appraisal["offer_valid_until"] = offer_valid_until
    appraisal["net_credit_cents"] = calc.trade_in_net_credit_cents(
        gross_offer_cents, reconditioning_estimate_cents, appraisal["mileage"])
    appraisal["status"] = "REAPPRAISED"
    ledger.write_entry(order["id"], "TRADE_IN_CREDIT",
                       appraisal["net_credit_cents"], "TRADE_IN_REAPPRAISED")
    touch(appraisal)
    return appraisal