"""Allocation: manual reservation, the batch selector, confirmation and cancellation."""

from flask import Blueprint, request

import auth
import calc
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("allocations", __name__)

ALLOCATION_STATUSES = ("RESERVED", "CONFIRMED", "CONSUMED", "RELEASED", "CANCELLED")
TRANSPLANT_CLASSIFICATIONS = ("TRANSPLANT_OPTICAL", "TRANSPLANT_THERAPEUTIC")
# Procedure compatibility is asymmetric (PRD 3.6): optical tissue serves every
# procedure, therapeutic tissue only THERAPEUTIC and PK.
ALLOWED_PROCEDURES = {
    "TRANSPLANT_OPTICAL": ("PK", "DSAEK", "DMEK", "THERAPEUTIC"),
    "TRANSPLANT_THERAPEUTIC": ("THERAPEUTIC", "PK"),
}
LIVE_CAPACITY_STATUSES = ("RESERVED", "CONFIRMED", "CONSUMED")
AVAILABLE_CUSTODY = ("IN_HOUSE", "RETURNED_TO_BANK")
CONSENT_ALLOWS_TRANSPLANT = ("TRANSPLANT_ONLY", "TRANSPLANT_AND_RESEARCH")
DAY_CAPACITY_OTHERS = 1


def specular_ecd(tissue_id):
    row = calc.recorded_evaluation(tissue_id, "SPECULAR")
    if row is None:
        return None
    return row["endothelial_cell_count"]


def surgery_day_load(surgeon_id, surgery_date, ignore_allocation_id=None):
    """Live allocations of this surgeon whose surgery falls on the same UTC date."""
    day = surgery_date.date()
    count = 0
    for allocation in store.DB["allocations"].values():
        if allocation["status"] not in LIVE_CAPACITY_STATUSES:
            continue
        if ignore_allocation_id is not None and allocation["id"] == ignore_allocation_id:
            continue
        req = store.DB["requests"].get(allocation["request_id"])
        if req is None or req["surgeon_id"] != surgeon_id:
            continue
        if req["surgery_date"].date() == day:
            count += 1
    return count


def build_allocation(tissue, req, source):
    classification = tissue["classification"]
    row = store.base_row()
    row.update(
        {
            "tissue_id": tissue["id"],
            "request_id": req["id"],
            "allocated_at": store.now(),
            "status": "RESERVED",
            "source": source,
            "reserved_ecd_snapshot": specular_ecd(tissue["id"]),
            "reserved_classification_snapshot": classification,
            "processing_fee_cents": calc.allocation_processing_fee(classification, req),
            "expiry_margin_hours": store.floor_hours(
                req["surgery_date"], tissue["expires_at"]
            ),
            "cancel_reason": None,
        }
    )
    store.DB["allocations"][row["id"]] = row
    return row


@bp.post("/eye-bank/allocations")
def create_allocation():
    """Manual reservation. The gates run in the exact order of PRD 2.10's ladder."""
    auth.authenticate(("EyeBankCoordinator",))
    body = auth.body_dict()

    # rung 5: body foreign keys, left to right
    tissue = validate.resolve_fk(body, "tissue_id", "tissues")
    req = validate.resolve_fk(body, "request_id", "requests")

    # rung 6: input schema
    validate.req_str(body, "tissue_id")
    validate.req_str(body, "request_id")
    if tissue is None:
        raise ApiError("ERR_INVALID_REQUEST", "tissue_id must reference a tissue.")
    if req is None:
        raise ApiError("ERR_INVALID_REQUEST", "request_id must reference a surgeon request.")

    # rung 14 / 15: the two tissue state dimensions, disposition before custody
    if tissue["disposition_status"] != "ELIGIBLE":
        raise ApiError("ERR_TISSUE_NOT_ELIGIBLE", "Only an ELIGIBLE tissue may be reserved.")
    if tissue["custody_status"] not in AVAILABLE_CUSTODY:
        raise ApiError(
            "ERR_TISSUE_CUSTODY_INVALID", "The tissue is not in the bank's physical custody."
        )

    # rung 16: request state
    if req["status"] != "OPEN":
        raise ApiError("ERR_REQUEST_STATE_INVALID", "Only an OPEN request may be allocated.")

    donor = store.DB["donors"].get(tissue["donor_id"])
    surgeon = store.DB["surgeons"].get(req["surgeon_id"])

    # rungs 21, 22, 24: donor gates
    if donor is None or donor["consent_scope"] not in CONSENT_ALLOWS_TRANSPLANT:
        raise ApiError(
            "ERR_CONSENT_SCOPE_VIOLATION", "The donor's consent does not permit transplantation."
        )
    if donor["serology_status"] == "REACTIVE":
        raise ApiError("ERR_SEROLOGY_REACTIVE", "The donor is serologically reactive.")
    if donor["lookback_flag"]:
        raise ApiError("ERR_DONOR_UNDER_LOOKBACK", "The donor is under lookback investigation.")

    # rung 25: the receiving surgeon
    if surgeon is None or surgeon["credential_status"] != "ACTIVE":
        raise ApiError("ERR_SURGEON_NOT_CREDENTIALED", "The receiving surgeon is not ACTIVE.")

    # rungs 34, 35: viability against the clock and against the surgery date
    if tissue["expires_at"] <= store.now():
        raise ApiError("ERR_TISSUE_EXPIRED", "The tissue has expired.")
    if tissue["expires_at"] < req["surgery_date"]:
        raise ApiError(
            "ERR_EXPIRY_BEFORE_SURGERY_DATE",
            "The tissue expires before the requested surgery date.",
        )

    # rungs 40, 41, 42: the compatibility set (laterality_preference is NOT enforced here)
    classification = tissue["classification"]
    if (
        classification not in TRANSPLANT_CLASSIFICATIONS
        or req["procedure_type"] not in ALLOWED_PROCEDURES[classification]
    ):
        raise ApiError(
            "ERR_PROCEDURE_CLASSIFICATION_MISMATCH",
            "The tissue's classification does not permit this procedure.",
        )
    ecd = specular_ecd(tissue["id"])
    if ecd is None or ecd < req["min_ecd"]:
        raise ApiError(
            "ERR_ECD_BELOW_REQUEST_MINIMUM",
            "The specular endothelial cell count is below the request's minimum.",
        )
    if donor["age_years"] > req["max_donor_age_years"]:
        raise ApiError(
            "ERR_DONOR_AGE_ABOVE_REQUEST_MAX",
            "The donor is older than the request permits.",
        )

    # rung 43: re-issue ceiling
    if tissue["reissue_generation"] > 1:
        raise ApiError("ERR_REISSUE_LIMIT_REACHED", "This tissue has been returned twice.")

    # rung 46: two grafts per surgeon per calendar day
    if surgery_day_load(surgeon["id"], req["surgery_date"]) > DAY_CAPACITY_OTHERS:
        raise ApiError(
            "ERR_SURGEON_DAY_CAPACITY_EXCEEDED",
            "The surgeon already holds two grafts for that surgery date.",
        )

    allocation = build_allocation(tissue, req, "MANUAL")

    tissue["disposition_status"] = "RESERVED"
    store.touch(tissue)
    req["status"] = "ALLOCATED"
    store.touch(req)

    return envelope.ok(serialize.allocation(allocation), 201)


@bp.get("/eye-bank/allocations/<allocation_id>")
def get_allocation(allocation_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    row = validate.lookup("allocations", allocation_id)
    return envelope.ok(serialize.allocation(row))


@bp.get("/eye-bank/allocations")
def list_allocations():
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    rows = list(store.DB["allocations"].values())
    tissue_id = request.args.get("tissue_id")
    if tissue_id is not None:
        rows = [r for r in rows if r["tissue_id"] == tissue_id]
    request_id = request.args.get("request_id")
    if request_id is not None:
        rows = [r for r in rows if r["request_id"] == request_id]
    status = request.args.get("status")
    if status is not None:
        validate.filter_enum("status", status, ALLOCATION_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_desc(rows, lambda r: r["allocated_at"])
    return envelope.paginated(rows, serialize.allocation)


def _run_pool(reserved_this_run, now):
    """Step three: the tissue candidate pool, recomputed before each request."""
    pool = []
    for tissue in store.DB["tissues"].values():
        if tissue["id"] in reserved_this_run:
            continue
        if tissue["disposition_status"] != "ELIGIBLE":
            continue
        if tissue["custody_status"] not in AVAILABLE_CUSTODY:
            continue
        if tissue["classification"] not in TRANSPLANT_CLASSIFICATIONS:
            continue
        if tissue["reissue_generation"] > 1:
            continue
        if tissue["expires_at"] <= now:
            continue
        donor = store.DB["donors"].get(tissue["donor_id"])
        if donor is None or donor["lookback_flag"]:
            continue
        pool.append(tissue)
    return pool


def _matches_request(tissue, req, ecd):
    """Step four: the per-pair match filter."""
    if ecd is None or ecd < req["min_ecd"]:
        return False
    donor = store.DB["donors"].get(tissue["donor_id"])
    if donor is None or donor["age_years"] > req["max_donor_age_years"]:
        return False
    preference = req["laterality_preference"]
    if preference != "ANY" and preference != tissue["laterality"]:
        return False
    if req["procedure_type"] not in ALLOWED_PROCEDURES[tissue["classification"]]:
        return False
    if tissue["expires_at"] < req["surgery_date"]:
        return False
    return True


@bp.post("/eye-bank/allocation-runs")
def allocation_run():
    """The batch matcher. Planned in full before anything is persisted, because a run
    that matches nothing must leave no trace at all -- not even the expiry sweep."""
    auth.authenticate(("EyeBankCoordinator",))
    now = store.now()

    open_requests = store.by_created(
        [r for r in store.DB["requests"].values() if r["status"] == "OPEN"]
    )
    # The three priority figures are recomputed from scratch, clock read afresh,
    # at the start of every allocation run (PRD 3.5).
    scores = {
        r["id"]: calc.request_priority(r["urgency"], r["surgery_date"]) for r in open_requests
    }

    expired = [r for r in open_requests if r["surgery_date"] <= now]
    expired_ids = set(r["id"] for r in expired)

    candidates = []
    for req in open_requests:
        if req["id"] in expired_ids:
            continue
        surgeon = store.DB["surgeons"].get(req["surgeon_id"])
        if surgeon is None or surgeon["credential_status"] != "ACTIVE":
            continue
        if req["surgery_date"] <= now:
            continue
        candidates.append(req)
    candidates.sort(
        key=lambda r: (-scores[r["id"]][2], r["surgery_date"], r["created_at"], r["_seq"])
    )

    ecd_cache = {}

    def ecd_of(tissue):
        if tissue["id"] not in ecd_cache:
            ecd_cache[tissue["id"]] = specular_ecd(tissue["id"])
        return ecd_cache[tissue["id"]]

    reserved_this_run = set()
    matches = []
    unmatched_ids = []
    for req in candidates:
        pool = _run_pool(reserved_this_run, now)
        eligible = [t for t in pool if _matches_request(t, req, ecd_of(t))]
        if not eligible:
            unmatched_ids.append(req["id"])
            continue
        eligible.sort(
            key=lambda t: (t["expires_at"], ecd_of(t) or 0, t["created_at"], t["_seq"])
        )
        chosen = eligible[0]
        reserved_this_run.add(chosen["id"])
        matches.append((req, chosen))

    if not matches:
        raise ApiError(
            "ERR_NO_ELIGIBLE_TISSUE", "The allocation run produced no match at all."
        )

    matched_ids = set(req["id"] for req, _ in matches)

    # ---- apply -------------------------------------------------------------
    def publish(req, new_status=None):
        base, tier, score = scores[req["id"]]
        changed = (
            req["base_score"] != base
            or req["priority_tier"] != tier
            or req["priority_score"] != score
        )
        req["base_score"] = base
        req["priority_tier"] = tier
        req["priority_score"] = score
        if new_status is not None and new_status != req["status"]:
            req["status"] = new_status
            changed = True
        if changed:
            store.touch(req)

    for req in expired:
        publish(req, "EXPIRED")

    allocation_ids = []
    for req, tissue in matches:
        allocation = build_allocation(tissue, req, "RUN")
        allocation_ids.append(allocation["id"])
        tissue["disposition_status"] = "RESERVED"
        store.touch(tissue)
        publish(req, "ALLOCATED")

    for req in open_requests:
        if req["id"] in expired_ids or req["id"] in matched_ids:
            continue
        publish(req)

    return envelope.ok(
        {
            "run_at": store.iso(now),
            "allocations_created": len(allocation_ids),
            "allocation_ids": allocation_ids,
            "unmatched_request_ids": unmatched_ids,
            "expired_request_ids": [r["id"] for r in expired],
        }
    )


@bp.post("/eye-bank/allocations/<allocation_id>/confirm")
def confirm_allocation(allocation_id):
    auth.authenticate(("EyeBankCoordinator",))
    allocation = validate.lookup("allocations", allocation_id)

    if allocation["status"] != "RESERVED":
        raise ApiError(
            "ERR_ALLOCATION_STATE_INVALID", "Only a RESERVED allocation may be confirmed."
        )

    req = store.DB["requests"].get(allocation["request_id"])
    tissue = store.DB["tissues"].get(allocation["tissue_id"])
    surgeon = store.DB["surgeons"].get(req["surgeon_id"]) if req is not None else None

    # The three re-checks confirmation performs (PRD 3.7).
    if surgeon is None or surgeon["credential_status"] != "ACTIVE":
        raise ApiError("ERR_SURGEON_NOT_CREDENTIALED", "The receiving surgeon is not ACTIVE.")
    if tissue is not None and tissue["expires_at"] < req["surgery_date"]:
        raise ApiError(
            "ERR_EXPIRY_BEFORE_SURGERY_DATE",
            "The tissue now expires before the requested surgery date.",
        )
    if (
        surgery_day_load(surgeon["id"], req["surgery_date"], ignore_allocation_id=allocation["id"])
        > DAY_CAPACITY_OTHERS
    ):
        raise ApiError(
            "ERR_SURGEON_DAY_CAPACITY_EXCEEDED",
            "The surgeon already holds two grafts for that surgery date.",
        )

    allocation["status"] = "CONFIRMED"
    store.touch(allocation)

    calc.recompute_fee_ledger(surgeon)
    store.touch(surgeon)

    return envelope.ok(serialize.allocation(allocation))


@bp.post("/eye-bank/allocations/<allocation_id>/cancel")
def cancel_allocation(allocation_id):
    auth.authenticate(("EyeBankCoordinator",))
    allocation = validate.lookup("allocations", allocation_id)
    body = auth.body_dict()
    cancel_reason = validate.req_str(body, "cancel_reason", 1, 500)

    if allocation["status"] != "RESERVED":
        raise ApiError(
            "ERR_ALLOCATION_STATE_INVALID", "Only a RESERVED allocation may be cancelled."
        )

    cascade.cancel_reserved_allocation(allocation, cancel_reason, reopen=True)

    tissue = store.DB["tissues"].get(allocation["tissue_id"])
    if tissue is not None and tissue["disposition_status"] == "RESERVED":
        # custody_status is deliberately left where it is.
        tissue["disposition_status"] = "ELIGIBLE"
        store.touch(tissue)

    return envelope.ok(serialize.allocation(allocation))
