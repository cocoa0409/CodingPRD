"""Operating days and the five-step daily close."""
from decimal import Decimal

from flask import Blueprint

import db
import response
import shapes
from constants import PREFIX
from errors import ApiError
from middleware import (ALL_ROLES, CONTROLLER, NIGHT_AUDITOR, PROPERTY_ADMIN,
                        authenticate)
from money import ZERO, q2
from services import calc, derive, lookup, serial

bp = Blueprint("business_dates", __name__, url_prefix=PREFIX)


def _find_or_create_period(prop, business_date):
    month = business_date[0:7]
    for row in db.all_of("periods"):
        if row["property_id"] == prop["id"] and row["period_month"] == month:
            return row
    return db.insert("periods", {
        "_kind": "AccountingPeriod",
        "property_id": prop["id"],
        "period_month": month,
        "status": "OPEN",
        "gl_control_total_amount": None,
        "tie_out_attempt_count": 0,
        "tied_out_by_user_id": None,
        "tied_out_at": None,
        "audit_trail_retention_until_date": None,
    })


@bp.route("/business-dates", methods=["POST"])
def create_business_date():
    authenticate([PROPERTY_ADMIN, NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("property_id", "string", required=True),
        shapes.Field("business_date", "date", required=True),
        shapes.Field("out_of_order_room_count", "integer", ge=0, default=0),
        shapes.Field("benchmark_calendar_room_revenue_amount", "number", ge=0,
                     default=Decimal("0.00")),
        shapes.Field("benchmark_weekday_room_revenue_amount", "number", ge=0,
                     default=Decimal("0.00")),
    ])
    prop = lookup.get_property(body["property_id"])
    if body["out_of_order_room_count"] > int(prop["room_count_total"]):
        shapes.bad("out_of_order_room_count may not exceed the property's room_count_total.")
    for row in db.store.business_dates.values():
        if row["property_id"] == prop["id"] and row["business_date"] == body["business_date"]:
            raise ApiError("ERR_DUPLICATE_BUSINESS_DATE",
                           "That operating day already exists for this property.")
    period = _find_or_create_period(prop, body["business_date"])
    row = db.insert("business_dates", {
        "_kind": "BusinessDate",
        "property_id": prop["id"],
        "accounting_period_id": period["id"],
        "business_date": body["business_date"],
        "status": "OPEN",
        "out_of_order_room_count": body["out_of_order_room_count"],
        "benchmark_calendar_room_revenue_amount": body["benchmark_calendar_room_revenue_amount"],
        "benchmark_weekday_room_revenue_amount": body["benchmark_weekday_room_revenue_amount"],
        "reopen_count": 0,
        "city_ledger_swept_folio_count": 0,
        "city_ledger_transferred_balance_total_amount": ZERO,
        "city_ledger_fee_total_amount": ZERO,
    })
    return response.created(serial.business_date_out(row))


@bp.route("/business-dates/<row_id>", methods=["GET"])
def get_business_date(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.business_date_out(lookup.get_date(row_id)))


@bp.route("/business-dates", methods=["GET"])
def list_business_dates():
    authenticate(ALL_ROLES)
    rows = db.all_of("business_dates")
    for key in ("property_id", "accounting_period_id", "business_date", "status"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.business_date_out)
    return response.collection(items, meta)


# --------------------------------------------------------------------------
# step 1: room and tax
# --------------------------------------------------------------------------

@bp.route("/business-dates/<row_id>/post-room-and-tax", methods=["POST"])
def post_room_and_tax(row_id):
    user_id, _role = authenticate([NIGHT_AUDITOR])
    date_row = lookup.get_date(row_id)
    lookup.require_not_archived(date_row)
    if date_row["status"] != "OPEN":
        raise ApiError("ERR_BUSINESS_DATE_NOT_OPEN",
                       "The operating day is not OPEN.")
    prop = db.store.properties[date_row["property_id"]]
    folios = derive.folios_of_property(prop["id"])
    tax_pct = prop["occupancy_tax_rate_pct"]

    def room_line_count(folio):
        return len([p for p in derive.postings_of_folio(folio["id"])
                    if p["charge_type"] == "ROOM"])

    # Evidence check first: the run is all-or-nothing on comp paperwork.
    for folio in folios:
        if not folio["is_comp"] or folio["stay_status"] != "IN_HOUSE":
            continue
        if room_line_count(folio) >= int(folio["nights_count"]):
            continue
        if lookup.has_active_document(folio["id"], "COMP_ROOM",
                                     date_row["business_date"]) is None:
            raise ApiError("ERR_COMP_AUTHORIZATION_MISSING",
                           "A comp account has no active COMP_ROOM authorization.")

    for folio in folios:
        if folio["stay_status"] != "IN_HOUSE":
            continue
        posted = room_line_count(folio)
        if posted >= int(folio["nights_count"]):
            continue
        amount = ZERO if folio["is_comp"] else q2(folio["contracted_rate_amount"])
        night_index = posted + 1
        derive.append_posting("ROOM", amount, date_row, "NIGHT_AUDIT", user_id,
                              folio=folio, night_index=night_index)
        derive.append_posting("OCCUPANCY_TAX",
                              calc.occupancy_tax_provisional(amount, tax_pct),
                              date_row, "NIGHT_AUDIT", user_id, folio=folio,
                              night_index=night_index)

    policy = prop["no_show_charge_policy"]
    for folio in folios:
        if folio["arrival_business_date_id"] != date_row["id"]:
            continue
        if folio["stay_status"] != "RESERVED":
            continue
        folio["stay_status"] = "NO_SHOW"
        derive.touch(folio)
        rate = q2(folio["contracted_rate_amount"])
        if policy == "FIRST_NIGHT_PLUS_TAX":
            derive.append_posting("NO_SHOW", rate, date_row, "NIGHT_AUDIT",
                                  user_id, folio=folio)
            derive.append_posting("OCCUPANCY_TAX",
                                  calc.occupancy_tax_provisional(rate, tax_pct),
                                  date_row, "NIGHT_AUDIT", user_id, folio=folio,
                                  night_index=1)
        elif policy == "FULL_STAY_NO_TAX":
            derive.append_posting("NO_SHOW",
                                  q2(rate * Decimal(int(folio["nights_count"]))),
                                  date_row, "NIGHT_AUDIT", user_id, folio=folio)

    date_row["status"] = "ROOM_POSTING"
    derive.touch(date_row)
    return response.ok(serial.business_date_out(date_row))


# --------------------------------------------------------------------------
# step 2: seal charges
# --------------------------------------------------------------------------

@bp.route("/business-dates/<row_id>/seal-charges", methods=["POST"])
def seal_charges(row_id):
    user_id, _role = authenticate([NIGHT_AUDITOR])
    date_row = lookup.get_date(row_id)
    lookup.require_not_archived(date_row)
    if date_row["status"] != "ROOM_POSTING":
        raise ApiError("ERR_DATE_NOT_READY_TO_SEAL",
                       "The operating day is not in ROOM_POSTING.")
    prop = db.store.properties[date_row["property_id"]]
    tax_pct = prop["occupancy_tax_rate_pct"]
    for folio in derive.folios_of_property(prop["id"]):
        lines = [p for p in derive.postings_of_folio(folio["id"])
                 if p["business_date_id"] == date_row["id"]]
        taxable = [p for p in lines if p["charge_type"] in derive.TAXABLE_TYPES]
        if not taxable:
            continue
        base = ZERO
        for line in taxable:
            base = base + line["amount"]
        final_tax = calc.occupancy_tax_final(base, tax_pct)
        provisional = ZERO
        for line in lines:
            if line["charge_type"] == "OCCUPANCY_TAX":
                provisional = provisional + line["amount"]
        delta = calc.true_up_delta(final_tax, provisional)
        if delta != ZERO:
            derive.append_posting("TAX_TRUE_UP", delta, date_row, "NIGHT_AUDIT",
                                  user_id, folio=folio)
    date_row["status"] = "CHARGES_SEALED"
    derive.touch(date_row)
    return response.ok(serial.business_date_out(date_row))


# --------------------------------------------------------------------------
# step 3: verify settlements
# --------------------------------------------------------------------------

def _matching_system_amount(batch):
    total = ZERO
    for ticket in db.all_of("tickets"):
        if ticket["outlet_id"] != batch["outlet_id"]:
            continue
        if ticket["business_date_id"] != batch["business_date_id"]:
            continue
        if ticket["status"] != "CLOSED":
            continue
        if ticket["settlement_type"] != batch["tender_type"]:
            continue
        transmitted = ticket["transmitted_at"]
        if transmitted is None:
            continue
        if batch["shift_start_at"] <= transmitted < batch["shift_end_at"]:
            total = total + ticket["total_amount"]
    return q2(total)


def reconcile(batch, prop):
    """Stamp the system amount and variance, then judge the batch."""
    system = _matching_system_amount(batch)
    variance = calc.settlement_variance(batch["declared_amount"], system)
    batch["system_amount"] = system
    batch["variance_amount"] = variance
    tolerance = prop["settlement_variance_tolerance_amount"]
    batch["status"] = "MATCHED" if abs(variance) <= tolerance else "VARIANCE_FLAGGED"
    derive.touch(batch)
    return batch


@bp.route("/business-dates/<row_id>/verify-settlements", methods=["POST"])
def verify_settlements(row_id):
    authenticate([NIGHT_AUDITOR])
    date_row = lookup.get_date(row_id)
    lookup.require_not_archived(date_row)
    if date_row["status"] not in ("CHARGES_SEALED", "SETTLEMENT_REVIEW"):
        raise ApiError("ERR_DATE_NOT_READY_TO_VERIFY",
                       "The operating day is not ready for settlement review.")
    prop = db.store.properties[date_row["property_id"]]
    batches = [b for b in db.all_of("batches")
               if b["business_date_id"] == date_row["id"]]
    for outlet in db.all_of("outlets"):
        if outlet["property_id"] != prop["id"]:
            continue
        if outlet["status"] != "ACTIVE" or not outlet["requires_shift_settlement"]:
            continue
        if not any(b["outlet_id"] == outlet["id"] for b in batches):
            raise ApiError("ERR_SETTLEMENTS_UNRESOLVED",
                           "Outlet %s has declared no settlement batch for this day."
                           % outlet["id"])
    for batch in batches:
        if batch["status"] == "DECLARED":
            reconcile(batch, prop)
    date_row["status"] = "SETTLEMENT_REVIEW"
    derive.touch(date_row)
    return response.ok(serial.business_date_out(date_row))


# --------------------------------------------------------------------------
# city ledger sweep
# --------------------------------------------------------------------------

@bp.route("/business-dates/<row_id>/city-ledger-sweep", methods=["POST"])
def city_ledger_sweep(row_id):
    user_id, _role = authenticate([NIGHT_AUDITOR])
    date_row = lookup.get_date(row_id)
    lookup.require_not_archived(date_row)
    if date_row["status"] not in ("ROOM_POSTING", "CHARGES_SEALED",
                                  "SETTLEMENT_REVIEW", "REOPENED"):
        raise ApiError("ERR_DATE_NOT_READY_TO_BALANCE",
                       "The operating day may not be swept in its current state.")
    prop = db.store.properties[date_row["property_id"]]
    city_account = None
    for account in db.all_of("ledger_accounts"):
        if account["property_id"] == prop["id"] and account["ledger_type"] == "CITY_LEDGER":
            city_account = account
            break
    swept = 0
    balance_total = ZERO
    fee_total = ZERO
    for folio in derive.folios_of_property(prop["id"]):
        if folio["stay_status"] != "DEPARTED":
            continue
        if folio["settlement_method"] != "DIRECT_BILL":
            continue
        if folio["settlement_status"] == "TRANSFERRED_TO_CITY_LEDGER":
            continue
        balance = derive.folio_balance(folio)
        if balance <= ZERO:
            continue
        fee = calc.city_ledger_fee(balance, prop["city_ledger_fee_pct"])
        transfer = q2(balance + fee)
        derive.append_posting("CITY_LEDGER_FEE", fee, date_row, "LEDGER_SWEEP",
                              user_id, folio=folio)
        derive.append_posting("LEDGER_TRANSFER", -transfer, date_row,
                              "LEDGER_SWEEP", user_id, folio=folio)
        derive.append_posting(
            "LEDGER_TRANSFER", transfer, date_row, "LEDGER_SWEEP", user_id,
            folio=None,
            ledger_account_id=city_account["id"] if city_account else None,
        )
        folio["settlement_status"] = "TRANSFERRED_TO_CITY_LEDGER"
        derive.touch(folio)
        swept += 1
        balance_total = balance_total + balance
        fee_total = fee_total + fee
    date_row["city_ledger_swept_folio_count"] = swept
    date_row["city_ledger_transferred_balance_total_amount"] = q2(balance_total)
    date_row["city_ledger_fee_total_amount"] = q2(fee_total)
    derive.touch(date_row)
    return response.ok(serial.business_date_out(date_row))


# --------------------------------------------------------------------------
# step 4: balance
# --------------------------------------------------------------------------

@bp.route("/business-dates/<row_id>/balance", methods=["POST"])
def balance_day(row_id):
    authenticate([NIGHT_AUDITOR])
    date_row = lookup.get_date(row_id)
    lookup.require_not_archived(date_row)
    if date_row["status"] not in ("SETTLEMENT_REVIEW", "REOPENED"):
        raise ApiError("ERR_DATE_NOT_READY_TO_BALANCE",
                       "The operating day is not ready to balance.")
    prop = db.store.properties[date_row["property_id"]]
    folio_ids = set(f["id"] for f in derive.folios_of_property(prop["id"]))
    for auth in db.all_of("card_auths"):
        if auth["folio_id"] in folio_ids:
            derive.lapse_authorization(auth, prop)
    aggregates = derive.date_aggregates(date_row)
    if aggregates["declined_authorization_count"] != 0:
        raise ApiError("ERR_DECLINED_AUTH_UNRESOLVED",
                       "A declined card authorization is still unresolved.")
    if aggregates["unresolved_settlement_batch_count"] != 0:
        raise ApiError("ERR_SETTLEMENTS_UNRESOLVED",
                       "Settlement batches remain unresolved.")
    if aggregates["ledger_control_amount"] != ZERO:
        raise ApiError("ERR_LEDGERS_OUT_OF_BALANCE",
                       "The day's ledger control total is not zero.")
    date_row["status"] = "BALANCED"
    derive.touch(date_row)
    return response.ok(serial.business_date_out(date_row))


# --------------------------------------------------------------------------
# step 5: close, and the controller's reopen
# --------------------------------------------------------------------------

@bp.route("/business-dates/<row_id>/close", methods=["POST"])
def close_day(row_id):
    authenticate([NIGHT_AUDITOR])
    date_row = lookup.get_date(row_id)
    lookup.require_not_archived(date_row)
    if date_row["status"] != "BALANCED":
        raise ApiError("ERR_DATE_NOT_BALANCED", "The operating day is not balanced.")
    published = [r for r in derive.reports_of_date(date_row["id"])
                 if r["status"] == "DISTRIBUTED"]
    if not published:
        raise ApiError("ERR_REPORT_NOT_DISTRIBUTED",
                       "The day has no distributed revenue report.")
    date_row["status"] = "CLOSED"
    derive.touch(date_row)
    derive.touch(db.store.periods.get(date_row["accounting_period_id"]))
    return response.ok(serial.business_date_out(date_row))


@bp.route("/business-dates/<row_id>/reopen", methods=["POST"])
def reopen_day(row_id):
    authenticate([CONTROLLER])
    date_row = lookup.get_date(row_id)
    lookup.require_not_archived(date_row)
    if date_row["status"] != "CLOSED":
        raise ApiError("ERR_DATE_NOT_CLOSED", "The operating day is not closed.")
    period = db.store.periods.get(date_row["accounting_period_id"])
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN",
                       "The accounting period is no longer open.")
    date_row["status"] = "REOPENED"
    date_row["reopen_count"] = int(date_row["reopen_count"]) + 1
    derive.supersede_reports(date_row)
    derive.touch(date_row)
    derive.touch(period)
    return response.ok(serial.business_date_out(date_row))
