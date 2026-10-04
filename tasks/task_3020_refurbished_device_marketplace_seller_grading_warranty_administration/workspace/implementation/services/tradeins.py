"""Trade-in intake pricing, inspection and post-inspection revision (PRD §3.8).

Pinned evaluation order for the final quote:
  base -> deduct -> step penalty -> clamp at 0 -> subtract fee -> round -> clamp at 0
"""

from db import store, touch, iso, stamp_new, add_days
from errors import fail
from numeric import rhu, rhu_int
from vocab import (
    ACCEPTANCE_WINDOW_DAYS,
    BASE_CENTS,
    battery_deduct,
    COSMETIC_DEDUCT_TABLE,
    FUNCTIONAL_DEDUCT_TABLE,
    GRADE_ORDER_COSMETIC,
    GRADE_ORDER_FUNCTIONAL,
    GRADE_STEP_PENALTY_CENTS,
    INSPECTION_FEE_CENTS,
    INSPECTION_FEE_PCT,
    INSPECTED_BATTERY_REJECT_PCT,
    LOCK_DEDUCT_TABLE,
)


def provisional_quote(data):
    """Base minus the four declared deductions, clamped at zero.

    No step penalty and no inspection fee participate in this variant.
    """
    value = (
        BASE_CENTS
        - COSMETIC_DEDUCT_TABLE[data["self_declared_cosmetic_grade"]]
        - FUNCTIONAL_DEDUCT_TABLE[data["self_declared_functional_grade"]]
        - battery_deduct(data["self_declared_battery_health_pct"])
        - LOCK_DEDUCT_TABLE[data["self_declared_carrier_lock_status"]]
    )
    return max(0, value)


def grade_steps(declared_cosmetic, declared_functional, inspected_cosmetic, inspected_functional):
    """Sum of two clamped differences over the pinned ordinal maps."""
    cosmetic = max(0, GRADE_ORDER_COSMETIC[inspected_cosmetic]
                   - GRADE_ORDER_COSMETIC[declared_cosmetic])
    functional = max(0, GRADE_ORDER_FUNCTIONAL[inspected_functional]
                     - GRADE_ORDER_FUNCTIONAL[declared_functional])
    return cosmetic + functional


def final_quote(submission, inspected):
    """The FINAL variant, from the inspector's measurements only."""
    steps = grade_steps(
        submission["self_declared_cosmetic_grade"],
        submission["self_declared_functional_grade"],
        inspected["inspected_cosmetic_grade"],
        inspected["inspected_functional_grade"],
    )
    inspected_value = (
        BASE_CENTS
        - COSMETIC_DEDUCT_TABLE[inspected["inspected_cosmetic_grade"]]
        - FUNCTIONAL_DEDUCT_TABLE[inspected["inspected_functional_grade"]]
        - battery_deduct(inspected["inspected_battery_health_pct"])
        - LOCK_DEDUCT_TABLE[inspected["inspected_carrier_lock_status"]]
    )
    revised = inspected_value - GRADE_STEP_PENALTY_CENTS * steps
    revised = max(0, revised)
    fee = rhu_int(revised * INSPECTION_FEE_PCT, 0)
    return max(0, rhu_int(revised - fee, 0))


# --------------------------------------------------------------- lifecycle
def create_submission(data, clock):
    payload = {
        "customer_ref": data["customer_ref"],
        "submitted_model_code": data["submitted_model_code"],
        "submission_state": "SUBMITTED",
        "self_declared_cosmetic_grade": data["self_declared_cosmetic_grade"],
        "self_declared_functional_grade": data["self_declared_functional_grade"],
        "self_declared_battery_health_pct": data["self_declared_battery_health_pct"],
        "self_declared_carrier_lock_status": data["self_declared_carrier_lock_status"],
        "provisional_quote_cents": 0,
        "inspected_cosmetic_grade": None,
        "inspected_functional_grade": None,
        "inspected_battery_health_pct": None,
        "inspected_carrier_lock_status": None,
        "inspection_fee_cents": 0,
        "final_quote_cents": 0,
        "acceptance_deadline": None,
        "revision_count": 0,
        "_deadline_dt": None,
    }
    payload["provisional_quote_cents"] = provisional_quote(data)
    stamp_new("trade_ins", payload, clock)
    store.trade_ins[payload["id"]] = payload
    return payload


def record_inspection(submission, measured, clock):
    if submission["submission_state"] != "SUBMITTED":
        raise fail("ERR_INVALID_STATE")
    if measured["inspected_battery_health_pct"] < INSPECTED_BATTERY_REJECT_PCT:
        submission["submission_state"] = "REJECTED"
        touch(submission, clock)
        raise fail("ERR_INSPECTION_BATTERY_UNINSURABLE")
    submission.update({
        "inspected_cosmetic_grade": measured["inspected_cosmetic_grade"],
        "inspected_functional_grade": measured["inspected_functional_grade"],
        "inspected_battery_health_pct": measured["inspected_battery_health_pct"],
        "inspected_carrier_lock_status": measured["inspected_carrier_lock_status"],
    })
    submission["submission_state"] = "INSPECTED"
    submission["final_quote_cents"] = 0
    touch(submission, clock)
    return submission


def revise(submission, measured, clock):
    state = submission["submission_state"]
    if state == "PRICE_REVISED":
        # The one free revision round runs in both directions.
        if submission["revision_count"] == 1 and clock <= submission["_deadline_dt"]:
            submission["submission_state"] = "INSPECTED"
            touch(submission, clock)
            return submission
        raise fail("ERR_REVISION_LIMIT_REACHED")
    if state != "INSPECTED":
        raise fail("ERR_INVALID_STATE")
    if submission["revision_count"] != 0:
        raise fail("ERR_REVISION_LIMIT_REACHED")

    for key, value in measured.items():
        if value is not None:
            submission[key] = value
    submission["submission_state"] = "PRICE_REVISED"
    submission["final_quote_cents"] = final_quote(submission, submission)
    submission["inspection_fee_cents"] = INSPECTION_FEE_CENTS
    deadline = add_days(clock, ACCEPTANCE_WINDOW_DAYS)
    submission["acceptance_deadline"] = iso(deadline)
    submission["_deadline_dt"] = deadline
    submission["revision_count"] = submission["revision_count"] + 1
    touch(submission, clock)
    return submission


def accept(submission, clock):
    if submission["submission_state"] != "PRICE_REVISED":
        raise fail("ERR_INVALID_STATE")
    if clock > submission["_deadline_dt"]:
        raise fail("ERR_ACCEPTANCE_WINDOW_CLOSED")
    if submission["final_quote_cents"] <= 0:
        raise fail("ERR_INVALID_STATE", "The revised quote carries no positive value to accept.")
    submission["submission_state"] = "ACCEPTED"
    touch(submission, clock)
    return submission


def sweep_deadlines(clock):
    """System transition: PRICE_REVISED past its deadline becomes REJECTED."""
    changed = []
    for submission in store.trade_ins.values():
        if submission["submission_state"] != "PRICE_REVISED":
            continue
        deadline = submission.get("_deadline_dt")
        if deadline is not None and clock > deadline:
            submission["submission_state"] = "REJECTED"
            touch(submission, clock)
            changed.append(submission)
    return changed