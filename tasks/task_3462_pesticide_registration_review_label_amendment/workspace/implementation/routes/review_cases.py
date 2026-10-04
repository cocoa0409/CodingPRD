"""Registration review cases (PRD 3.7): scheduling, completion, cycles."""
from datetime import timedelta

from flask import Blueprint

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from validate import as_datetime, as_str, paginate, parse_body, reject_unknown

bp = Blueprint("review_cases", __name__)

NON_TERMINAL_CASE_STATUSES = ("SCHEDULED", "OPEN", "DCI_PENDING", "UNDER_REVIEW")


def get_case_or_404(case_id):
    case = store["review_cases"].get(case_id)
    if case is None:
        err("ERR_NOT_FOUND", "Registration review case %s does not exist." % case_id)
    return case


@bp.post("/registration-review-cases")
def create_case():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["product_id", "opened_at", "due_at"])
    product_id = as_str(data, "product_id", required=True)
    opened_at = as_datetime(data, "opened_at", required=True)
    due_at = as_datetime(data, "due_at", required=False)

    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    # Stage 7: manual scheduling requires a REGISTERED product.
    if product["status"] != "REGISTERED":
        err(
            "ERR_PRODUCT_NOT_REGISTERED",
            "Manual review-case scheduling requires a REGISTERED product.",
        )

    if due_at is None:
        due_at = opened_at + timedelta(days=constants.REVIEW_COMPLETION_DAYS)
    # Stage 11: case window ordering.
    if opened_at > due_at:
        err("ERR_INVALID_REQUEST", "opened_at must be at or before due_at.")

    # Stage 9: half-open [opened_at, due_at) must not intersect another
    # non-terminal case of the product (touching endpoints are permitted).
    for case in store["review_cases"].values():
        if (
            case["product_id"] == product_id
            and case["status"] in NON_TERMINAL_CASE_STATUSES
            and opened_at < case["due_at"]
            and case["opened_at"] < due_at
        ):
            err(
                "ERR_REVIEW_CASE_WINDOW_OVERLAP",
                "The proposed window intersects another non-terminal case of the product.",
            )

    existing = [c for c in store["review_cases"].values() if c["product_id"] == product_id]
    row = new_row()
    row.update(
        {
            "product_id": product_id,
            "cycle_number": len(existing) + 1,
            "opened_at": opened_at,
            "due_at": due_at,
            "status": "SCHEDULED",
            "completed_at": None,
        }
    )
    store["review_cases"][row["id"]] = row
    return ok(row, status=201)


@bp.get("/registration-review-cases/<case_id>")
def get_case(case_id):
    require_auth()
    return ok(get_case_or_404(case_id))


@bp.post("/registration-review-cases/<case_id>/complete")
def complete_case(case_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["completion_summary"])
    if "completion_summary" in data and data["completion_summary"] is not None:
        as_str(data, "completion_summary")

    case = get_case_or_404(case_id)
    if case["status"] not in ("OPEN", "DCI_PENDING", "UNDER_REVIEW"):
        err("ERR_CASE_NOT_COMPLETABLE", "The case is not OPEN, DCI_PENDING, or UNDER_REVIEW.")
    for dci in store["dcis"].values():
        if dci["review_case_id"] == case_id and dci["status"] in (
            "ISSUED",
            "RESPONDED",
            "DEFICIENT",
            "DELINQUENT",
        ):
            err("ERR_DCI_OUTSTANDING", "A data call-in of this case is still outstanding.")

    now = clock.now()
    case["status"] = "COMPLETED"
    case["completed_at"] = now
    if data.get("completion_summary") is not None:
        case["completion_summary"] = data["completion_summary"]
    touch(case)

    product = store["products"][case["product_id"]]
    if product["status"] == "UNDER_REVIEW":
        still_open = any(
            c["product_id"] == product["id"]
            and c["id"] != case["id"]
            and c["status"] in ("OPEN", "DCI_PENDING", "UNDER_REVIEW")
            for c in store["review_cases"].values()
        )
        if not still_open:
            product["status"] = "REGISTERED"
            touch(product)

    # Auto-schedule the next cycle: opened 5475 days after completion.
    from services.cascade import schedule_next_case

    schedule_next_case(product, now + timedelta(days=constants.REVIEW_CYCLE_DAYS))
    return ok(case)


@bp.get("/registration-review-cases/<case_id>/data-call-ins")
def list_case_dcis(case_id):
    require_auth()
    get_case_or_404(case_id)
    rows = [d for d in store["dcis"].values() if d["review_case_id"] == case_id]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)
