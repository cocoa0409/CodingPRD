"""Purchase feed ingestion, normalization, accrual and markup audit (PRD §3.3, §3.4, §3.7)."""

from flask import Blueprint

from authz import endpoint, find, require_distributor_scope, resolve
from envelope import created, ok
from errors import ApiError
from pageutil import paged
from routes_reference import _filtered
from serializers import dump
from shapes import (Date, Enum, Int, Str, UPPER_CODE_RE, parse_body, raw_body,
                    supplied)
from store import db, new_record, parse_instant, touch
from svc_accrue import accrue_batch, accruable_lines, reverse_batch_accruals
from svc_audit import allocate_recovery, audit_batch_markup
from svc_common import accruals_of_batch, lines_of_batch, recompute_batch_cases
from svc_norm import eligible_candidates, normalize_batch, renormalize_batch

bp = Blueprint("feed", __name__)

BATCH_ROLES = ("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "DistributorFeed")
LINE_ROLES = ("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "DistributorFeed",
              "MemberOperator")


# --------------------------------------------------------------------------
# purchase batches
# --------------------------------------------------------------------------

@bp.post("/purchase-batches")
@endpoint("DistributorFeed", "RebateAnalyst")
def create_batch(caller):
    # priority 6 - a DistributorFeed account may only open its own feed
    require_distributor_scope(caller, raw_body().get("distributor_id"))

    body = parse_body([
        Str("distributor_id"),
        Date("period_start"),
        Date("period_end"),
        Str("source_reference", 3, 40),
    ])
    distributor = resolve("distributor", body["distributor_id"])   # priority 9
    if distributor["status"] != "ACTIVE":                          # priority 13
        raise ApiError("ERR_DISTRIBUTOR_SUSPENDED")
    if body["period_end"] < body["period_start"]:                  # priority 22
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")
    # priority 33 - source_reference unused within the same distributor
    for batch in db.batches.values():
        if (batch["distributor_id"] == distributor["id"]
                and batch["source_reference"] == body["source_reference"]):
            raise ApiError("ERR_DUPLICATE_BATCH_REFERENCE")

    rec = new_record("PurchaseBatch", {
        "distributor_id": distributor["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "source_reference": body["source_reference"],
        "normalization_status": "RECEIVED",
        "audit_status": "NOT_AUDITED",
        "line_count": 0,
        "total_cases_ingested": 0,
        "matched_cases": 0,
        "unmatched_cases": 0,
        "overbilled_cents": 0,
        "recovered_cents": 0,
        "accrued_by_user_id": None,
        "payout_hold": False,
    })
    db.batches[rec["id"]] = rec
    return created(dump(rec))


@bp.get("/purchase-batches/<batch_id>")
@endpoint(*BATCH_ROLES)
def get_batch(caller, batch_id):
    return ok(dump(resolve("batch", batch_id)))


@bp.get("/purchase-batches")
@endpoint(*BATCH_ROLES)
def list_batches(caller):
    records = _filtered(db.batches.values(),
                        [("distributor_id", "distributor_id"),
                         ("normalization_status", "normalization_status"),
                         ("audit_status", "audit_status")])
    return paged(records)


@bp.post("/purchase-batches/<batch_id>/normalize")
@endpoint("RebateAnalyst")
def normalize(caller, batch_id):
    batch = resolve("batch", batch_id)
    # priority 11 - RECEIVED and holding at least one line
    if batch["normalization_status"] != "RECEIVED" or batch["line_count"] < 1:
        raise ApiError("ERR_INVALID_STATE")
    normalize_batch(batch)
    return ok(dump(batch))


@bp.post("/purchase-batches/<batch_id>/renormalize")
@endpoint("RebateAnalyst")
def renormalize(caller, batch_id):
    batch = resolve("batch", batch_id)
    # priority 11 - only from NORMALIZED or ACCRUED
    if batch["normalization_status"] not in ("NORMALIZED", "ACCRUED"):
        raise ApiError("ERR_INVALID_STATE")
    # Money has been demanded from or settled with the distributor on these figures.
    if batch["audit_status"] in ("RECOVERY_REQUESTED", "RECOVERED", "WRITTEN_OFF"):
        raise ApiError("ERR_INVALID_STATE")
    if batch["normalization_status"] == "ACCRUED":
        for accrual in accruals_of_batch(batch):
            if accrual["status"] in ("VALIDATED", "DISPUTED", "PAID"):
                raise ApiError("ERR_INVALID_STATE")
        reverse_batch_accruals(batch, "RENORMALIZED")

    renormalize_batch(batch)
    return ok(dump(batch))


@bp.post("/purchase-batches/<batch_id>/accrue")
@endpoint("RebateAnalyst")
def accrue(caller, batch_id):
    batch = resolve("batch", batch_id)
    if batch["normalization_status"] != "NORMALIZED":     # priority 11
        raise ApiError("ERR_INVALID_STATE")
    if not accruable_lines(batch):                        # priority 36
        raise ApiError("ERR_NO_ACCRUABLE_LINES")
    accrue_batch(batch, caller)
    return ok(dump(batch))


@bp.post("/purchase-batches/<batch_id>/audit-markup")
@endpoint("RebateAnalyst")
def audit_markup(caller, batch_id):
    batch = resolve("batch", batch_id)
    # priority 11 - the audit dimension must be untouched and the feed normalized
    if batch["audit_status"] != "NOT_AUDITED":
        raise ApiError("ERR_INVALID_STATE")
    if batch["normalization_status"] not in ("NORMALIZED", "ACCRUED"):
        raise ApiError("ERR_INVALID_STATE")
    audit_batch_markup(batch)
    return ok(dump(batch))


@bp.post("/purchase-batches/<batch_id>/request-recovery")
@endpoint("RebateAnalyst")
def request_recovery(caller, batch_id):
    batch = resolve("batch", batch_id)
    if batch["audit_status"] != "AUDIT_OVERBILLED":       # priority 11
        raise ApiError("ERR_INVALID_STATE")
    distributor = db.distributors.get(batch["distributor_id"])
    if distributor is None or distributor["status"] != "ACTIVE":  # priority 13
        raise ApiError("ERR_DISTRIBUTOR_SUSPENDED")
    batch["audit_status"] = "RECOVERY_REQUESTED"
    touch(batch)
    return ok(dump(batch))


@bp.post("/purchase-batches/<batch_id>/settle-recovery")
@endpoint("GpoAdmin")
def settle_recovery(caller, batch_id):
    batch = resolve("batch", batch_id)
    body = parse_body([
        Enum("outcome", ("RECOVERED", "WRITTEN_OFF")),
        Int("recovered_cents", 0, None, required=False),
    ])
    # recovered_cents is required for RECOVERED and must be omitted for WRITTEN_OFF;
    # supplying it in the write-off case is an unknown-field violation.
    if body["outcome"] == "RECOVERED":
        if body["recovered_cents"] is None:
            raise ApiError("ERR_INVALID_REQUEST")
    elif supplied("recovered_cents"):
        raise ApiError("ERR_INVALID_REQUEST")

    if batch["audit_status"] != "RECOVERY_REQUESTED":     # priority 11
        raise ApiError("ERR_INVALID_STATE")

    if body["outcome"] == "RECOVERED":
        if body["recovered_cents"] > batch["overbilled_cents"]:   # priority 39
            raise ApiError("ERR_RECOVERY_EXCEEDS_OVERBILLING")
        batch["recovered_cents"] = body["recovered_cents"]
        batch["audit_status"] = "RECOVERED"
        touch(batch)
        allocate_recovery(batch, body["recovered_cents"])
        distributor = db.distributors.get(batch["distributor_id"])
        if distributor is not None:
            distributor["overbilled_recovered_cents"] += body["recovered_cents"]
            touch(distributor)
    else:
        batch["recovered_cents"] = 0
        batch["audit_status"] = "WRITTEN_OFF"
        touch(batch)
        # The write-off cascades into the distributor relationship; no operation
        # ever returns a SUSPENDED distributor to ACTIVE.
        distributor = db.distributors.get(batch["distributor_id"])
        if distributor is not None:
            distributor["status"] = "SUSPENDED"
            touch(distributor)
    return ok(dump(batch))


# --------------------------------------------------------------------------
# purchase lines
# --------------------------------------------------------------------------

def _loa_in_force(member_id, distributor_id):
    """An ACTIVE letter for the pairing whose half-open window holds the clock."""
    now = db.now()
    for letter in db.letters.values():
        if letter["status"] != "ACTIVE":
            continue
        if letter["member_id"] != member_id:
            continue
        if letter["distributor_id"] != distributor_id:
            continue
        start = parse_instant(letter["effective_from"])
        end = parse_instant(letter["effective_to"])
        if start <= now < end:   # effective_from included, effective_to excluded
            return True
    return False


@bp.post("/purchase-lines")
@endpoint("DistributorFeed")
def create_line(caller):
    # priority 6 - scope against the owning batch's distributor.  When the batch id
    # does not resolve there is no owner to compare, so the request falls through
    # to body-shape and foreign-key resolution.
    pre_batch = find("batch", raw_body().get("purchase_batch_id"))
    if pre_batch is not None:
        require_distributor_scope(caller, pre_batch["distributor_id"])

    body = parse_body([
        Str("purchase_batch_id"),
        Str("member_id"),
        Str("distributor_sku", 1, 40),
        Str("vendor_item_description", 1, 200),
        Str("normalized_item_key_reported", 1, 60, UPPER_CODE_RE),
        Int("cases_shipped"),
        Int("invoice_unit_cost_cents"),
        Int("distributor_base_cost_cents"),
        Date("invoice_date"),
    ])
    batch = resolve("batch", body["purchase_batch_id"])   # priority 9
    member = resolve("member", body["member_id"])

    if batch["normalization_status"] != "RECEIVED":       # priority 11
        raise ApiError("ERR_INVALID_STATE")
    if member["enrollment_status"] != "ACTIVE":           # priority 12
        raise ApiError("ERR_MEMBER_NOT_ENROLLED")
    if not _loa_in_force(member["id"], batch["distributor_id"]):  # priority 15
        raise ApiError("ERR_LOA_NOT_ACTIVE")
    if not (batch["period_start"] <= body["invoice_date"]
            <= batch["period_end"]):                     # priority 23
        raise ApiError("ERR_INVOICE_DATE_OUT_OF_PERIOD")
    # priority 29 - quantity and cost figures each at least 1
    if (body["cases_shipped"] < 1 or body["invoice_unit_cost_cents"] < 1
            or body["distributor_base_cost_cents"] < 1):
        raise ApiError("ERR_INVALID_CASE_QUANTITY")

    extended = body["cases_shipped"] * body["invoice_unit_cost_cents"]
    rec = new_record("PurchaseLine", {
        "purchase_batch_id": batch["id"],
        "member_id": member["id"],
        "contracted_item_id": None,
        "distributor_sku": body["distributor_sku"],
        "vendor_item_description": body["vendor_item_description"],
        "normalized_item_key_reported": body["normalized_item_key_reported"],
        "cases_shipped": body["cases_shipped"],
        "invoice_unit_cost_cents": body["invoice_unit_cost_cents"],
        "distributor_base_cost_cents": body["distributor_base_cost_cents"],
        "invoice_date": body["invoice_date"],
        "invoice_extended_cents": extended,
        "match_status": "UNMATCHED",
        "accrual_block_reason": "NONE",
        "overbilled_cents": 0,
    })
    db.lines[rec["id"]] = rec

    batch["line_count"] += 1
    batch["total_cases_ingested"] += rec["cases_shipped"]
    batch["unmatched_cases"] += rec["cases_shipped"]
    touch(batch)
    return created(dump(rec))


@bp.get("/purchase-lines/<line_id>")
@endpoint(*LINE_ROLES)
def get_line(caller, line_id):
    return ok(dump(resolve("line", line_id)))


@bp.get("/purchase-lines")
@endpoint(*LINE_ROLES)
def list_lines(caller):
    records = _filtered(db.lines.values(),
                        [("purchase_batch_id", "purchase_batch_id"),
                         ("member_id", "member_id"),
                         ("contracted_item_id", "contracted_item_id"),
                         ("match_status", "match_status"),
                         ("accrual_block_reason", "accrual_block_reason")])
    return paged(records)


@bp.post("/purchase-lines/<line_id>/map")
@endpoint("RebateAnalyst")
def map_line(caller, line_id):
    line = resolve("line", line_id)                        # priority 4
    body = parse_body([Str("contracted_item_id")])
    item = resolve("item", body["contracted_item_id"])      # priority 9

    batch = db.batches.get(line["purchase_batch_id"])
    if line["match_status"] != "AMBIGUOUS":                 # priority 11
        raise ApiError("ERR_INVALID_STATE")
    if batch is None or batch["normalization_status"] != "NORMALIZED":
        raise ApiError("ERR_INVALID_STATE")
    # priority 17 - the offered item must be one of the line's eligible candidates
    if item["id"] not in [c["id"] for c in eligible_candidates(line)]:
        raise ApiError("ERR_ITEM_NOT_A_CANDIDATE")

    line["contracted_item_id"] = item["id"]
    line["match_status"] = "MATCHED"
    touch(line)
    recompute_batch_cases(batch)
    return ok(dump(line))
