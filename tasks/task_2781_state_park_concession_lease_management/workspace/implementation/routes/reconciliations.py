"""Annual fee reconciliation — PRD 3.8."""
from auth import ALL_ROLES, fetch, guard, require_owner
from envelope import created, listing, ok
from errors import ApiError
from logic import (build_reconciliation, lease_of, recompute_outstanding, supersede_pending)
from money import parse_date
from router import route
from shape import body, ref, req_date, req_int, req_str
from store import clock_date, db, touch


@route("/fee-reconciliations", methods=["POST"])
def reconciliations_create():
    guard("ContractingOfficer")
    data = body()
    lease = None
    lease_ref = ref(data, "lease_id")
    if lease_ref is not None:
        lease = fetch(db.leases, lease_ref, "ERR_LEASE_NOT_FOUND")
    req_str(data, "lease_id")
    expected_version = req_int(data, "expected_lease_version")
    year_start_raw, year_start = req_date(data, "lease_year_start")
    year_end_raw, year_end = req_date(data, "lease_year_end")
    if year_start > year_end:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "lease_year_start must be at or before lease_year_end")
    if expected_version != lease["version"]:
        raise ApiError("ERR_STALE_LEASE_VERSION", "The lease version is stale")
    if lease["contract_status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "The lease is not ACTIVE")
    if not clock_date() > year_end:
        raise ApiError("ERR_RECONCILIATION_PERIOD_NOT_ELAPSED",
                       "The lease year has not elapsed")
    row = build_reconciliation(lease, year_start, year_end)
    supersede_pending(lease["id"], year_start_raw, row["id"])
    recompute_outstanding(lease)
    touch(lease)
    return created(row)


@route("/fee-reconciliations/<reconciliation_id>/settle", methods=["POST"])
def reconciliations_settle(reconciliation_id):
    guard("Concessionaire")
    row = fetch(db.reconciliations, reconciliation_id, "ERR_RECONCILIATION_NOT_FOUND")
    lease = lease_of(row)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    payment = req_int(data, "payment_amount_cents")
    if row["status"] != "PENDING_PAYMENT":
        raise ApiError("ERR_RECONCILIATION_STATUS_INVALID",
                       "Reconciliation status %s cannot be settled" % row["status"])
    if payment != row["additional_fee_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH",
                       "The payment does not equal the amount due")
    row["payment_amount_cents"] = payment
    row["status"] = "SETTLED"
    touch(row)
    if lease is not None:
        recompute_outstanding(lease)
    audit = db.audits.get(row["audit_engagement_id"]) if row["audit_engagement_id"] else None
    if audit is not None and audit["status"] == "FINAL":
        audit["status"] = "CLOSED"
        touch(audit)
    return ok(row)


@route("/fee-reconciliations", methods=["GET"])
def reconciliations_list():
    guard(*ALL_ROLES)
    return listing(db.reconciliations,
                   ("lease_id", "audit_engagement_id", "superseded_by_id", "status"))


@route("/fee-reconciliations/<reconciliation_id>", methods=["GET"])
def reconciliations_read(reconciliation_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.reconciliations, reconciliation_id, "ERR_RECONCILIATION_NOT_FOUND"))
