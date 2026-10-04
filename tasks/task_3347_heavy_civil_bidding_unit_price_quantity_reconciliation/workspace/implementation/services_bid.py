"""Bid-preparation services: projects, pay items and subcontractor quotes."""

import calc
import db
from errors import ApiError
from services import get_project
from util import dec, parse_iso

CONTRACT_TYPES = ("UNIT_PRICE", "LUMP_SUM")
UNITS_OF_MEASURE = ("LF", "CY", "TON", "EA", "SY")
GOOD_FAITH_BASES = ("NONE", "SOLICITED_DBE", "DOCUMENTED_UNAVAILABLE", "OUTREACH_EVENT")
RECALL_REASONS = ("ERROR_IN_BID", "OWNER_ADDENDUM", "PROTESTS_RECEIVED")


def _number(payload, key, default):
    value = payload.get(key)
    if value is None:
        return default
    return dec(value)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

def create_project(payload):
    project_code = payload.get("project_code")
    owner_agency_name = payload.get("owner_agency_name")
    if not isinstance(project_code, str) or not project_code.strip():
        raise ApiError("ERR_INVALID_REQUEST", "project_code is required.", 400)
    if not isinstance(owner_agency_name, str) or not owner_agency_name.strip():
        raise ApiError("ERR_INVALID_REQUEST", "owner_agency_name is required.", 400)

    contract_type = payload.get("contract_type") or "UNIT_PRICE"
    if contract_type not in CONTRACT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "contract_type must be one of %s." % ", ".join(CONTRACT_TYPES), 400)

    bid_deadline_at = parse_iso(payload.get("bid_deadline_at"))

    retention_rate = _number(payload, "retention_rate_pct", dec("5.0"))
    if retention_rate < 0 or retention_rate > 10:
        raise ApiError("ERR_INVALID_REQUEST",
                       "retention_rate_pct must be between 0.0 and 10.0 inclusive.", 400)
    advertised_goal = _number(payload, "advertised_dbe_goal_pct", dec("0.0"))
    if advertised_goal < 0 or advertised_goal > 100:
        raise ApiError("ERR_INVALID_REQUEST",
                       "advertised_dbe_goal_pct must be between 0.0 and 100.0 inclusive.", 400)

    for existing in db.PROJECTS.values():
        if existing["project_code"] == project_code and existing["project_status"] != "COMPLETE":
            raise ApiError("ERR_DUPLICATE_PROJECT_CODE",
                           "project_code %r is already held by an in-flight project."
                           % project_code, 409)

    return db.create("project", {
        "project_code": project_code,
        "owner_agency_name": owner_agency_name,
        "contract_type": contract_type,
        "bid_deadline_at": bid_deadline_at,
        "retention_rate_pct": float(retention_rate),
        "advertised_dbe_goal_pct": float(advertised_goal),
        "bid_window_open_at": db.clock(),
        "bid_status": "DRAFT",
        "project_status": "PRE_BID",
        "bid_open_at": None,
        "total_bid_cents": 0,
        "contract_value_cents": 0,
        "unbalanced_bid_score": 0.0,
        "dbe_participation_pct": 0.0,
        "retention_balance_cents": 0,
        "claim_window_open": False,
    })


def seal_bid(project):
    if project["bid_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "The bid is not in DRAFT.", 409)
    if db.clock() >= project["bid_deadline_at"]:
        raise ApiError("ERR_BID_WINDOW_CLOSED",
                       "The bid window has closed; the bid may no longer be sealed.", 422)

    items = calc.project_items(project)
    if not any(i["item_status"] in ("PRICED", "SUBMITTED") for i in items):
        raise ApiError("ERR_INVALID_STATE",
                       "An empty bid cannot be sealed; at least one priced item is required.", 409)
    if any(i["item_status"] == "DRAFT" for i in items):
        raise ApiError("ERR_INVALID_STATE",
                       "A pay item that was never priced has no place in a sealed bid.", 409)
    for item in items:
        if item["bid_unit_price_cents"] < item["balanced_unit_price_cents"]:
            raise ApiError("ERR_RATE_BELOW_COST",
                           "Pay item %s is priced below its crew-productivity cost floor."
                           % item["item_code"], 422)
    for quote in calc.project_quotes(project):
        if quote["shopping_flagged"]:
            raise ApiError("ERR_BID_SHOPPING_RESTRICTED",
                           "A quote on this project was received after the bid was opened.", 422)

    project["bid_status"] = "SEALED"
    calc.refresh_project_bid(project)
    db.touch(project)
    return project


def open_bid(project):
    if project["bid_status"] != "SEALED":
        raise ApiError("ERR_INVALID_STATE", "The bid is not SEALED.", 409)
    if db.clock() < project["bid_deadline_at"]:
        raise ApiError("ERR_BID_NOT_YET_CLOSED",
                       "The bid deadline has not yet passed.", 422)

    project["bid_status"] = "OPEN"
    project["project_status"] = "AWARDED"
    project["bid_open_at"] = db.clock()
    calc.refresh_project_bid(project)
    project["_awarded_value_cents"] = project["total_bid_cents"]
    project["contract_value_cents"] = project["total_bid_cents"]

    for item in calc.project_items(project):
        if item["item_status"] == "SUBMITTED":
            item["item_status"] = "AWARDED"
            calc.recalc_item(item)
    for reconciliation in db.RECONCILIATIONS.values():
        if reconciliation["project_id"] == project["id"] and reconciliation["reconciliation_status"] != "CLOSED":
            calc.refresh_reconciliation(project)
    reconciliation = calc.non_closed_reconciliation(project)
    if reconciliation is not None:
        project["contract_value_cents"] = reconciliation["final_contract_value_cents"]
        project["retention_balance_cents"] = (
            reconciliation["retention_held_cents"] - reconciliation["retention_released_cents"]
        )

    project["dbe_participation_pct"] = calc.dbe_participation_pct(project)
    for quote in calc.project_quotes(project):
        if project["bid_open_at"] is not None and quote["quote_received_at"] > project["bid_open_at"]:
            quote["shopping_flagged"] = True
    db.touch(project)
    return project


def recall_bid(project, reason_code):
    if project["bid_status"] != "SEALED":
        raise ApiError("ERR_INVALID_STATE", "The bid is not SEALED.", 409)
    if db.clock() >= project["bid_deadline_at"]:
        raise ApiError("ERR_BID_WINDOW_CLOSED",
                       "The bid window has closed; the bid may no longer be recalled.", 422)

    project["bid_status"] = "RECALLED"
    for item in calc.project_items(project):
        if item["item_status"] == "SUBMITTED":
            item["item_status"] = "DRAFT"
            db.touch(item)
    for quote in calc.project_quotes(project):
        if quote["quote_status"] == "CARRIED":
            quote["quote_status"] = "RECEIVED"
            quote["carried_in_bid"] = False
            quote["version_round"] = quote["version_round"] + 1
            db.touch(quote)
    project["total_bid_cents"] = 0
    db.touch(project)
    return project


def reset_bid(project):
    if project["bid_status"] != "RECALLED":
        raise ApiError("ERR_INVALID_STATE", "The bid is not RECALLED.", 409)
    project["bid_status"] = "DRAFT"
    project["project_status"] = "PRE_BID"
    db.touch(project)
    return project


def dbe_gate_satisfied(project):
    if project["dbe_participation_pct"] >= project["advertised_dbe_goal_pct"]:
        return True
    for quote in calc.project_quotes(project):
        if quote["good_faith_effort_basis"] in ("SOLICITED_DBE", "DOCUMENTED_UNAVAILABLE",
                                                "OUTREACH_EVENT"):
            return True
    return False


def start_work(project):
    if project["project_status"] != "AWARDED":
        raise ApiError("ERR_INVALID_STATE", "The project is not AWARDED.", 409)

    performance_bond = None
    for bond in db.BONDS.values():
        if (bond["project_id"] == project["id"] and bond["bond_type"] == "PERFORMANCE"
                and bond["bond_status"] == "ISSUED"):
            performance_bond = bond
            break
    if performance_bond is None:
        raise ApiError("ERR_INVALID_STATE",
                       "The project carries no issued performance bond.", 409)
    surety = db.find("surety", performance_bond["surety_id"])
    if surety is None or surety["surety_status"] != "ACTIVE":
        raise ApiError("ERR_SURETY_SUSPENDED",
                       "The surety backing the performance bond is not ACTIVE.", 422)

    project["dbe_participation_pct"] = calc.dbe_participation_pct(project)
    if not dbe_gate_satisfied(project):
        raise ApiError("ERR_DBE_GOOD_FAITH_MISSING",
                       "The project misses its advertised DBE goal with no documented good-faith effort.",
                       422)

    project["project_status"] = "ACTIVE"
    project["claim_window_open"] = True
    for item in calc.project_items(project):
        if item["item_status"] == "AWARDED":
            item["item_status"] = "ACTIVE"
            item["measured_quantity"] = 0
            db.touch(item)
    touched_sureties = set()
    for commitment in db.COMMITMENTS.values():
        if commitment["project_id"] == project["id"] and commitment["commitment_status"] == "RESERVED":
            commitment["commitment_status"] = "ACTIVE"
            db.touch(commitment)
            touched_sureties.add(commitment["surety_id"])
    for surety_id in touched_sureties:
        surety = db.find("surety", surety_id)
        if surety is not None:
            calc.recalc_surety(surety)
    db.touch(project)
    return project


# ---------------------------------------------------------------------------
# BidItem
# ---------------------------------------------------------------------------

def create_item(project, payload):
    item_code = payload.get("item_code")
    item_description = payload.get("item_description")
    unit_of_measure = payload.get("unit_of_measure")
    if not isinstance(item_code, str) or not item_code.strip():
        raise ApiError("ERR_INVALID_REQUEST", "item_code is required.", 400)
    if not isinstance(item_description, str) or not item_description.strip():
        raise ApiError("ERR_INVALID_REQUEST", "item_description is required.", 400)
    if unit_of_measure not in UNITS_OF_MEASURE:
        raise ApiError("ERR_INVALID_REQUEST",
                       "unit_of_measure must be one of %s." % ", ".join(UNITS_OF_MEASURE), 400)
    if payload.get("estimated_quantity") is None:
        raise ApiError("ERR_INVALID_REQUEST", "estimated_quantity is required.", 400)
    estimated_quantity = dec(payload["estimated_quantity"])
    if estimated_quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "estimated_quantity must be strictly greater than zero.", 400)

    overrun = _number(payload, "overrun_threshold_pct", dec("15.0"))
    underrun = _number(payload, "underrun_threshold_pct", dec("15.0"))
    for label, value in (("overrun_threshold_pct", overrun), ("underrun_threshold_pct", underrun)):
        if value < 0 or value > 100:
            raise ApiError("ERR_INVALID_REQUEST",
                           "%s must be between 0.0 and 100.0 inclusive." % label, 400)

    for existing in calc.project_items(project):
        if existing["item_code"] == item_code:
            raise ApiError("ERR_DUPLICATE_ITEM_CODE",
                           "item_code %r already exists within this project." % item_code, 409)

    return db.create("bid_item", {
        "project_id": project["id"],
        "item_code": item_code,
        "item_description": item_description,
        "unit_of_measure": unit_of_measure,
        "estimated_quantity": float(estimated_quantity),
        "bid_unit_price_cents": 0,
        "balanced_unit_price_cents": 0,
        "crew_day_labor_cents": 0,
        "crew_day_equipment_cents": 0,
        "daily_productivity_units": 0,
        "overrun_threshold_pct": float(overrun),
        "underrun_threshold_pct": float(underrun),
        "measured_quantity": 0,
        "variance_pct": 0.0,
        "item_status": "DRAFT",
        "renegotiation_required": False,
    })


def price_item(project, item, payload):
    if item["item_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT pay item may be priced.", 409)

    if payload.get("bid_unit_price_cents") is None:
        raise ApiError("ERR_INVALID_REQUEST", "bid_unit_price_cents is required.", 400)
    price = payload["bid_unit_price_cents"]
    if not isinstance(price, int) or isinstance(price, bool) or price < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "bid_unit_price_cents must be an integer of zero or more.", 400)

    for key in ("crew_day_labor_cents", "crew_day_equipment_cents", "daily_productivity_units"):
        if payload.get(key) is None:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % key, 400)
    labor = payload["crew_day_labor_cents"]
    equipment = payload["crew_day_equipment_cents"]
    productivity = dec(payload["daily_productivity_units"])
    if not isinstance(labor, int) or isinstance(labor, bool) or labor <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "crew_day_labor_cents must be strictly greater than zero.", 400)
    if not isinstance(equipment, int) or isinstance(equipment, bool) or equipment < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "crew_day_equipment_cents must be zero or greater.", 400)
    if productivity <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "daily_productivity_units must be strictly greater than zero.", 400)

    if price <= 0:
        raise ApiError("ERR_UNIT_PRICE_REQUIRED",
                       "A price of zero cannot be committed; a positive unit price is required.", 422)

    balanced = calc.crew_rate_cents(labor, equipment, payload["daily_productivity_units"])
    if price < balanced:
        raise ApiError("ERR_RATE_BELOW_COST",
                       "The bid price falls below the crew-productivity cost floor.", 422)

    item["bid_unit_price_cents"] = price
    item["crew_day_labor_cents"] = labor
    item["crew_day_equipment_cents"] = equipment
    item["daily_productivity_units"] = float(productivity)
    item["balanced_unit_price_cents"] = balanced
    item["item_status"] = "PRICED"
    db.touch(item)
    project["unbalanced_bid_score"] = float(calc.unbalanced_bid_score(project))
    project["total_bid_cents"] = calc.total_bid_cents(project)
    db.touch(project)
    return item


def submit_item(project, item):
    if item["item_status"] != "PRICED":
        raise ApiError("ERR_INVALID_STATE", "Only a PRICED pay item may be submitted.", 409)
    if project["bid_status"] not in ("DRAFT", "SEALED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The composition of the bid is frozen once it has been opened.", 409)
    item["item_status"] = "SUBMITTED"
    db.touch(item)
    project["total_bid_cents"] = calc.total_bid_cents(project)
    db.touch(project)
    return item


def unsubmit_item(project, item):
    if item["item_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED pay item may be unsubmitted.", 409)
    if project["bid_status"] == "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       "The composition of the bid is frozen once it has been opened.", 409)
    item["item_status"] = "PRICED"
    db.touch(item)
    project["total_bid_cents"] = calc.total_bid_cents(project)
    db.touch(project)
    return item


def close_item(project, item):
    if item["item_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE pay item may be closed.", 409)
    reconciliation = calc.non_closed_reconciliation(project)
    if reconciliation is None or reconciliation["reconciliation_status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE",
                       "The project's reconciliation has not reached FINALIZED.", 409)
    for measurement in calc.item_measurements(item):
        if measurement["measurement_status"] not in ("APPROVED", "PAYABLE", "VOIDED"):
            raise ApiError("ERR_MEASUREMENTS_PENDING",
                           "A progress measurement on this pay item is still DRAFT.", 422)

    item["item_status"] = "CLOSED"
    measured, variance, renegotiation = calc.item_ledger(item)
    item["measured_quantity"] = float(measured)
    item["variance_pct"] = calc.f2(variance)
    item["renegotiation_required"] = bool(renegotiation)
    db.touch(item)
    calc.refresh_reconciliation(project)
    if calc.project_items(project) and all(i["item_status"] == "CLOSED"
                                           for i in calc.project_items(project)):
        project["project_status"] = "COMPLETE"
        project["claim_window_open"] = False
    db.touch(project)
    return item


# ---------------------------------------------------------------------------
# SubcontractorQuote
# ---------------------------------------------------------------------------

def create_quote(payload):
    project = get_project(payload.get("project_id"))
    trade_code = payload.get("trade_code")
    contact_name = payload.get("contact_name")
    if not isinstance(trade_code, str) or not trade_code.strip():
        raise ApiError("ERR_INVALID_REQUEST", "trade_code is required.", 400)
    if not isinstance(contact_name, str) or not contact_name.strip():
        raise ApiError("ERR_INVALID_REQUEST", "contact_name is required.", 400)
    if payload.get("quoted_amount_cents") is None:
        raise ApiError("ERR_INVALID_REQUEST", "quoted_amount_cents is required.", 400)
    amount = payload["quoted_amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "quoted_amount_cents must be strictly greater than zero.", 400)
    window_start = parse_iso(payload.get("quote_window_start"))
    window_end = parse_iso(payload.get("quote_window_end"))
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "quote_window_end must fall strictly after quote_window_start.", 400)

    unicap = payload.get("unicap_registered")
    unicap = bool(unicap) if unicap is not None else False
    basis = payload.get("good_faith_effort_basis") or "NONE"
    if basis not in GOOD_FAITH_BASES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "good_faith_effort_basis must be one of %s." % ", ".join(GOOD_FAITH_BASES),
                       400)

    if db.clock() >= project["bid_deadline_at"]:
        raise ApiError("ERR_QUOTE_AFTER_DEADLINE",
                       "A quote may not be recorded at or after the project's bid deadline.", 422)

    now = db.clock()
    record = db.create("quote", {
        "project_id": project["id"],
        "trade_code": trade_code,
        "contact_name": contact_name,
        "quoted_amount_cents": amount,
        "quote_window_start": window_start,
        "quote_window_end": window_end,
        "quote_received_at": now,
        "quote_status": "RECEIVED",
        "version_round": 1,
        "unicap_registered": unicap,
        "good_faith_effort_basis": basis,
        "dbe_credit_cents": 0,
        "carried_in_bid": False,
        "shopping_flagged": bool(project["bid_open_at"] is not None
                                 and now > project["bid_open_at"]),
    })
    return record


def carry_quote(quote):
    project = get_project(quote["project_id"])
    if quote["quote_status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED quote may be carried.", 409)
    for other in calc.project_quotes(project):
        if other["id"] == quote["id"]:
            continue
        if other["trade_code"] == quote["trade_code"] and other["quote_status"] in ("CARRIED", "SELECTED"):
            raise ApiError("ERR_BID_SHOPPING_RESTRICTED",
                           "Another quote on this trade is already carried or selected.", 422)
    if db.clock() >= project["bid_deadline_at"]:
        raise ApiError("ERR_QUOTE_AFTER_DEADLINE",
                       "A quote may not be carried at or after the project's bid deadline.", 422)

    quote["quote_status"] = "CARRIED"
    quote["carried_in_bid"] = True
    quote["dbe_credit_cents"] = calc.quote_dbe_credit_cents(quote)
    db.touch(quote)
    project["dbe_participation_pct"] = calc.dbe_participation_pct(project)
    project["total_bid_cents"] = calc.total_bid_cents(project)
    db.touch(project)
    return quote


def withdraw_quote(quote):
    project = get_project(quote["project_id"])
    if quote["quote_status"] != "CARRIED":
        raise ApiError("ERR_INVALID_STATE", "Only a CARRIED quote may be withdrawn.", 409)
    if project["bid_status"] == "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       "A quote may not be withdrawn once the bid has been opened.", 409)

    quote["quote_status"] = "RECEIVED"
    quote["carried_in_bid"] = False
    quote["version_round"] = quote["version_round"] + 1
    quote["dbe_credit_cents"] = calc.quote_dbe_credit_cents(quote)
    db.touch(quote)
    project["dbe_participation_pct"] = calc.dbe_participation_pct(project)
    project["total_bid_cents"] = calc.total_bid_cents(project)
    db.touch(project)
    return quote


def select_quote(quote):
    project = get_project(quote["project_id"])
    if quote["quote_status"] != "CARRIED":
        raise ApiError("ERR_INVALID_STATE", "Only a CARRIED quote may be selected.", 409)
    if project["bid_status"] != "OPEN" or db.clock() < project["bid_deadline_at"]:
        raise ApiError("ERR_BID_NOT_YET_CLOSED",
                       "A quote may only be selected after the bid has been opened.", 422)

    quote["quote_status"] = "SELECTED"
    quote["carried_in_bid"] = True
    quote["dbe_credit_cents"] = calc.quote_dbe_credit_cents(quote)
    db.touch(quote)
    project["dbe_participation_pct"] = calc.dbe_participation_pct(project)
    project["total_bid_cents"] = calc.total_bid_cents(project)
    db.touch(project)
    return quote


def reject_quote(quote):
    project = get_project(quote["project_id"])
    if quote["quote_status"] not in ("CARRIED", "SELECTED"):
        raise ApiError("ERR_INVALID_STATE", "Only a carried or selected quote may be rejected.", 409)

    quote["quote_status"] = "REJECTED"
    quote["carried_in_bid"] = False
    quote["dbe_credit_cents"] = calc.quote_dbe_credit_cents(quote)
    db.touch(quote)
    project["dbe_participation_pct"] = calc.dbe_participation_pct(project)
    project["total_bid_cents"] = calc.total_bid_cents(project)
    db.touch(project)
    return quote
