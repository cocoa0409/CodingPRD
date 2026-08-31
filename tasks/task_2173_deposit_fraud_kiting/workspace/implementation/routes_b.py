"""Deposit items, settlement, check holds and early-release override reviews."""
from flask import Blueprint, g, request

import calc
import serial
from core import (
    API_PREFIX,
    bad,
    base_row,
    body,
    db,
    endpoint,
    fail,
    get_account,
    get_check_hold,
    get_deposit_item,
    get_review,
    now,
    ok,
    ok_list,
    opt_id,
    opt_str,
    pagination,
    paginate,
    query_enum,
    req_dt,
    req_enum,
    req_int,
    req_str,
    sort_rows,
    touch,
)

bp = Blueprint("b", __name__)

ITEM_TYPES = {"CHECK", "ACH", "CASH"}
ITEM_STATUSES = {"PENDING", "CLEARED", "RETURNED"}
RETURN_REASONS = {"NSF", "ACCOUNT_CLOSED", "UNCOLLECTED_FUNDS", "STOP_PAYMENT"}
HOLD_STATUSES = {"ACTIVE", "RELEASED", "OVERRIDDEN", "CHARGED_BACK"}
REVIEW_STATUSES = {
    "DRAFT",
    "SUBMITTED",
    "RETURNED_FOR_INFO",
    "APPROVED",
    "DENIED",
    "EXECUTED",
    "SUPERSEDED",
}
ACCOUNT_ROLE_DEPOSITING = {
    "DEPOSITING",
    "DEPOSITOR",
    "DEPOSIT",
    "ACCOUNT",
    "DEPOSITING_ACCOUNT",
    "DEPOSITED_INTO",
}
ACCOUNT_ROLE_DRAWEE = {"DRAWEE", "DRAWN_ON", "DRAWEE_ACCOUNT", "DRAWN"}


# --------------------------------------------------------------------------
# Deposit items
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/accounts/<aid>/deposit-items")
@endpoint(["OperationsAdmin"])
def create_deposit_item(aid):
    acct = get_account(aid)
    data = body()
    item_type = req_enum(data, "item_type", ITEM_TYPES)
    amount = req_int(data, "amount_cents", 1, None)
    drawee_id = opt_id(data, "drawee_account_id")

    if drawee_id is not None:
        get_account(drawee_id)

    if acct["lifecycle_status"] != "ACTIVE":
        fail("ERR_ACCOUNT_NOT_ACTIVE", "Deposits require an ACTIVE account.")
    if acct["access_posture"] == "LOCKED":
        fail("ERR_ACCOUNT_ACCESS_LOCKED", "The account's access posture is LOCKED.")

    clock = now()
    item = base_row()
    item.update(
        {
            "account_id": aid,
            "drawee_account_id": drawee_id,
            "item_type": item_type,
            "amount_cents": amount,
            "deposit_at": clock,
            "status": "PENDING",
            "settled_at": None,
            "return_reason": None,
            "immediate_credit_cents": 0,
            "held_cents": 0,
        }
    )
    db.deposit_items[item["id"]] = item

    # check_hold_schedule
    if item_type == "CASH":
        immediate = amount
        held = 0
    else:
        immediate = min(amount, calc.IMMEDIATE_AVAIL_CENTS)
        held = amount - immediate
    item["immediate_credit_cents"] = immediate
    item["held_cents"] = held

    if held > 0:
        hold_type = calc.choose_hold_type(item, acct, clock)
        hold = base_row()
        hold.update(
            {
                "deposit_item_id": item["id"],
                "hold_type": hold_type,
                "held_amount_cents": held,
                "hold_start_at": item["deposit_at"],
                "hold_release_at": item["deposit_at"] + calc.days(calc.HOLD_DAYS[hold_type]),
                "status": "ACTIVE",
                "released_at": None,
            }
        )
        db.check_holds[hold["id"]] = hold

    snap = calc.snapshot_account(acct)
    acct["ledger_balance_cents"] += amount
    acct["available_balance_cents"] += immediate
    calc.bump_if_dirty(acct, snap)
    calc.recompute_cases_for_account(aid)

    return ok(serial.deposit_item(item), 201)


@bp.get(API_PREFIX + "/accounts/<aid>/deposit-items")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor", "BsaOfficer"])
def list_account_deposit_items(aid):
    get_account(aid)
    limit, offset = pagination()
    status = query_enum("status", ITEM_STATUSES)
    role_raw = None
    if "account_role" in request.args:
        role_raw = request.args.get("account_role")
        upper = (role_raw or "").upper()
        if upper in ACCOUNT_ROLE_DEPOSITING:
            role_raw = "DEPOSITING"
        elif upper in ACCOUNT_ROLE_DRAWEE:
            role_raw = "DRAWEE"
        else:
            bad("account_role is not a declared value.")

    rows = []
    for i in db.deposit_items.values():
        is_dep = i["account_id"] == aid
        is_dra = i.get("drawee_account_id") == aid
        if not (is_dep or is_dra):
            continue
        if role_raw == "DEPOSITING" and not is_dep:
            continue
        if role_raw == "DRAWEE" and not is_dra:
            continue
        rows.append(i)
    if status:
        rows = [i for i in rows if i["status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.deposit_item)
    return ok_list(items, limit, offset, total)


@bp.get(API_PREFIX + "/deposit-items/<iid>")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor", "BsaOfficer"])
def read_deposit_item(iid):
    return ok(serial.deposit_item(get_deposit_item(iid)))


@bp.post(API_PREFIX + "/deposit-items/<iid>/settle")
@endpoint(["OperationsAdmin"])
def settle_deposit_item(iid):
    item = get_deposit_item(iid)
    data = body()
    outcome = req_enum(data, "outcome", {"CLEARED", "RETURNED"})
    return_reason = None
    if "return_reason" in data and data["return_reason"] is not None:
        return_reason = req_enum(data, "return_reason", RETURN_REASONS)
    if outcome == "RETURNED" and return_reason is None:
        bad("return_reason is required when outcome is RETURNED.")

    if item["status"] != "PENDING":
        fail("ERR_ITEM_ALREADY_SETTLED", "The item has already been settled.")

    clock = now()
    acct = db.accounts.get(item["account_id"])
    active_holds = [h for h in calc.holds_of_item(item["id"]) if h["status"] == "ACTIVE"]
    released_total = sum(h["held_amount_cents"] for h in active_holds)

    affected = set()
    if outcome == "CLEARED":
        item["status"] = "CLEARED"
        item["settled_at"] = clock
        touch(item)
        for h in active_holds:
            h["status"] = "RELEASED"
            h["released_at"] = clock
            touch(h)
        if acct is not None:
            snap = calc.snapshot_account(acct)
            acct["available_balance_cents"] += released_total
            calc.bump_if_dirty(acct, snap)
            affected.add(acct["id"])
        drawee = db.accounts.get(item.get("drawee_account_id")) if item.get("drawee_account_id") else None
        if drawee is not None:
            dsnap = calc.snapshot_account(drawee)
            drawee["ledger_balance_cents"] -= item["amount_cents"]
            drawee["available_balance_cents"] -= item["amount_cents"]
            calc.bump_if_dirty(drawee, dsnap)
            affected.add(drawee["id"])
    else:
        item["status"] = "RETURNED"
        item["return_reason"] = return_reason
        item["settled_at"] = clock
        touch(item)
        for h in active_holds:
            h["status"] = "CHARGED_BACK"
            h["released_at"] = clock
            touch(h)
        if acct is not None:
            snap = calc.snapshot_account(acct)
            acct["ledger_balance_cents"] -= item["amount_cents"]
            acct["available_balance_cents"] -= item["amount_cents"] - released_total
            calc.bump_if_dirty(acct, snap)
            affected.add(acct["id"])

    if acct is not None:
        affected.add(acct["id"])
    for aid in affected:
        calc.recompute_cases_for_account(aid)

    return ok(serial.deposit_item(item))


@bp.get(API_PREFIX + "/deposit-items/<iid>/holds")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def list_item_holds(iid):
    get_deposit_item(iid)
    limit, offset = pagination()
    status = query_enum("status", HOLD_STATUSES)
    rows = calc.holds_of_item(iid)
    if status:
        rows = [h for h in rows if h["status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.check_hold)
    return ok_list(items, limit, offset, total)


@bp.get(API_PREFIX + "/check-holds/<hid>")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def read_check_hold(hid):
    return ok(serial.check_hold(get_check_hold(hid)))


# --------------------------------------------------------------------------
# Override reviews
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/check-holds/<hid>/override-reviews")
@endpoint(["FraudAnalyst", "FraudSupervisor"])
def create_override_review(hid):
    hold = get_check_hold(hid)
    data = body()
    requested = req_int(data, "requested_release_cents", 1, None)
    eff = req_dt(data, "release_effective_at")
    end = req_dt(data, "release_window_end_at")
    justification = req_str(data, "justification", 1, 500)
    expected_version = req_int(data, "expected_check_hold_version", None, None)
    if not (end > eff):
        bad("release_window_end_at must be strictly after release_effective_at.")

    # rank 7 — optimistic concurrency on the parent hold
    if expected_version != hold["version"]:
        fail("ERR_STALE_CHECK_HOLD_VERSION", "The check hold has been modified since it was read.")

    # rank 9 — state gate
    if hold["status"] != "ACTIVE":
        fail("ERR_HOLD_NOT_ACTIVE", "The check hold is not ACTIVE.")

    # rank 15 — maturity
    clock = now()
    if not (clock < hold["hold_release_at"]):
        fail("ERR_HOLD_ALREADY_MATURED", "The hold has already matured.")

    # rank 16 — release window overlap on the same account
    account_id = calc.account_of_hold(hold)
    live = ("DRAFT", "SUBMITTED", "RETURNED_FOR_INFO", "APPROVED", "EXECUTED")
    for other in db.override_reviews.values():
        if other["status"] not in live:
            continue
        other_hold = db.check_holds.get(other["check_hold_id"])
        if other_hold is None or calc.account_of_hold(other_hold) != account_id:
            continue
        if eff < other["release_window_end_at"] and other["release_effective_at"] < end:
            fail(
                "ERR_RELEASE_WINDOW_OVERLAP",
                "The requested release window overlaps an existing window on this account.",
            )

    # rank 19 — fiscal
    if requested > hold["held_amount_cents"]:
        fail("ERR_RELEASE_EXCEEDS_HOLD", "requested_release_cents exceeds the hold balance.")

    row = base_row()
    row.update(
        {
            "check_hold_id": hid,
            "requested_release_cents": requested,
            "release_effective_at": eff,
            "release_window_end_at": end,
            "justification": justification,
            "prepared_by_user_id": g.user_id,
            "decided_by_user_id": None,
            "status": "DRAFT",
            "loss_exposure_cents": 0,
            "adjusted_exposure_cents": 0,
            "decision_note": None,
            "revision_count": 0,
            "submitted_at": None,
            "decided_at": None,
            "executed_at": None,
        }
    )
    db.override_reviews[row["id"]] = row

    calc.supersede_reviews_for_hold(hid, exclude_id=row["id"])
    touch(hold)
    calc.price_exposure(row)
    return ok(serial.override_review(row), 201)


@bp.get(API_PREFIX + "/check-holds/<hid>/override-reviews")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def list_hold_override_reviews(hid):
    get_check_hold(hid)
    limit, offset = pagination()
    status = query_enum("status", REVIEW_STATUSES)
    rows = [r for r in db.override_reviews.values() if r["check_hold_id"] == hid]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.override_review)
    return ok_list(items, limit, offset, total)


@bp.get(API_PREFIX + "/hold-override-reviews/<rid>")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def read_override_review(rid):
    return ok(serial.override_review(get_review(rid)))


@bp.post(API_PREFIX + "/hold-override-reviews/<rid>/submit")
@endpoint(["FraudAnalyst", "FraudSupervisor"])
def submit_override_review(rid):
    review = get_review(rid)
    hold = db.check_holds.get(review["check_hold_id"])
    if hold is None or hold["status"] != "ACTIVE":
        fail("ERR_HOLD_NOT_ACTIVE", "The underlying check hold is not ACTIVE.")
    if review["status"] not in ("DRAFT", "RETURNED_FOR_INFO"):
        fail("ERR_REVIEW_NOT_SUBMITTED", "Submit requires DRAFT or RETURNED_FOR_INFO.")

    was_returned = review["status"] == "RETURNED_FOR_INFO"
    review["status"] = "SUBMITTED"
    review["submitted_at"] = now()
    if was_returned:
        review["revision_count"] += 1
    calc.price_exposure(review)
    touch(review)
    return ok(serial.override_review(review))


@bp.post(API_PREFIX + "/hold-override-reviews/<rid>/decide")
@endpoint(["FraudSupervisor"])
def decide_override_review(rid):
    review = get_review(rid)
    data = body()
    decision = req_enum(data, "decision", {"APPROVE", "DENY", "RETURN_FOR_INFO"})
    note = opt_str(data, "decision_note")

    hold = db.check_holds.get(review["check_hold_id"])
    if hold is None or hold["status"] != "ACTIVE":
        fail("ERR_HOLD_NOT_ACTIVE", "The underlying check hold is not ACTIVE.")
    if review["status"] != "SUBMITTED":
        fail("ERR_REVIEW_NOT_SUBMITTED", "A decision requires status SUBMITTED.")
    if g.user_id == review["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The preparer may not decide their own review.")
    if decision == "APPROVE" and review["adjusted_exposure_cents"] > calc.SUPERVISOR_APPROVAL_LIMIT_CENTS:
        fail(
            "ERR_EXPOSURE_EXCEEDS_AUTHORITY",
            "Adjusted exposure exceeds the supervisor approval limit.",
        )

    review["status"] = {
        "APPROVE": "APPROVED",
        "DENY": "DENIED",
        "RETURN_FOR_INFO": "RETURNED_FOR_INFO",
    }[decision]
    review["decided_by_user_id"] = g.user_id
    review["decided_at"] = now()
    review["decision_note"] = note
    touch(review)
    return ok(serial.override_review(review))


@bp.post(API_PREFIX + "/hold-override-reviews/<rid>/execute")
@endpoint(["FraudSupervisor"])
def execute_override_review(rid):
    review = get_review(rid)
    hold = db.check_holds.get(review["check_hold_id"])
    if hold is None or hold["status"] != "ACTIVE":
        fail("ERR_HOLD_NOT_ACTIVE", "The underlying check hold is not ACTIVE.")
    if review["status"] != "APPROVED":
        fail("ERR_REVIEW_NOT_APPROVED", "Execution requires status APPROVED.")
    requested = review["requested_release_cents"]
    if requested > hold["held_amount_cents"]:
        fail("ERR_RELEASE_EXCEEDS_HOLD", "requested_release_cents exceeds the hold balance.")
    if review["adjusted_exposure_cents"] > calc.SUPERVISOR_APPROVAL_LIMIT_CENTS:
        fail(
            "ERR_EXPOSURE_EXCEEDS_AUTHORITY",
            "Adjusted exposure exceeds the supervisor approval limit.",
        )

    clock = now()
    # hop 1
    review["status"] = "EXECUTED"
    review["executed_at"] = clock
    touch(review)
    # hop 2
    hold["held_amount_cents"] -= requested
    if hold["held_amount_cents"] == 0:
        hold["status"] = "OVERRIDDEN"
        hold["released_at"] = clock
    touch(hold)
    # hop 3
    account_id = calc.account_of_hold(hold)
    acct = db.accounts.get(account_id)
    if acct is not None:
        acct["available_balance_cents"] += requested
        touch(acct)
    # hop 4
    if account_id:
        calc.recompute_cases_for_account(account_id)

    return ok(serial.override_review(review))
