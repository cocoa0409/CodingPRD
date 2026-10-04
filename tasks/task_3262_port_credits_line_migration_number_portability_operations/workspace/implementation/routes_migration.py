"""Routes: prepaid-to-postpaid migration requests."""

from flask import Blueprint

import clock
import errors
import lookups
import middleware
import models
import response
import storage

bp = Blueprint("migration", __name__, url_prefix="/portability")

READERS = ("CustomerService", "PlatformAdmin", "CreditAnalyst", "Customer")
WRITERS = ("CustomerService", "PlatformAdmin")


def evaluate_eligibility(migration, line):
    """Route ELIGIBILITY_CHECK to APPROVED or BLOCKED (mutually exclusive)."""
    protected = models.has_active_protection(line["id"])
    open_ports = models.open_port_requests_on(line["id"])
    account = storage.db.get("accounts", line["account_id"])

    if protected or open_ports:
        migration["migration_state"] = "BLOCKED"
        line["number_status"] = "UNASSIGNED"
        models.touch(line)
        # The account is suspended only when protection is the reason.
        if protected and account is not None and account["account_status"] != "SUSPENDED":
            account["account_status"] = "SUSPENDED"
            models.touch(account)
    else:
        migration["migration_state"] = "APPROVED"
        line["number_status"] = "RESERVED"
        models.touch(line)
    schedule_if_due(migration)
    models.touch(migration)
    return migration


def schedule_if_due(migration):
    """Automatic APPROVED -> CUTOVER_SCHEDULED step (PRD 3.3).

    Scheduling follows approval on its own "once `requested_cutover_at` is set to
    an instant at or after the current logical clock instant". It runs in the same
    operation that produced the approval, because the eligibility call is what
    moved the request into `APPROVED`; the later clock advance is what carries the
    scheduled migration on into `CUTOVER_COMPLETE`.
    """
    if migration["migration_state"] != "APPROVED":
        return migration
    due = clock.parse_instant(migration["requested_cutover_at"])
    if due is not None and due >= clock.now():
        migration["migration_state"] = "CUTOVER_SCHEDULED"
    return migration


@bp.post("/migration-requests")
@middleware.require_roles(*WRITERS)
def create_migration(caller):
    data = middleware.body()
    line_id = middleware.required_str(data, "subscriber_line_id")
    lookups.line(line_id)

    source = middleware.optional_str(data, "source_billing_mode", "PREPAID")
    target = middleware.optional_str(data, "target_billing_mode", "POSTPAID")
    if source != "PREPAID":
        errors.fail("ERR_INVALID_REQUEST", "source_billing_mode is only ever PREPAID.")
    if target != "POSTPAID":
        errors.fail("ERR_INVALID_REQUEST", "target_billing_mode is only ever POSTPAID.")

    cutover = middleware.optional_instant(data, "requested_cutover_at")
    if cutover is None:
        errors.fail("ERR_INVALID_REQUEST", "Field 'requested_cutover_at' is required.")

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "subscriber_line_id": line_id,
        "source_billing_mode": source,
        "target_billing_mode": target,
        "migration_state": "DRAFT",
        "carried_mdn": None,
        "prepaid_balance_cents": middleware.optional_int(data, "prepaid_balance_cents", 0),
        "device_balance_cents": 0,
        "proration_credit_cents": 0,
        "requested_cutover_at": clock.fmt(cutover),
        "cutover_completed_at": None,
    }
    storage.db.add("migration_requests", record)
    return response.ok(models.migration_out(record), 201)


@bp.get("/migration-requests/<migration_id>")
@middleware.require_roles(*READERS)
def get_migration(caller, migration_id):
    record = lookups.migration(migration_id)
    line = lookups.line(record["subscriber_line_id"])
    middleware.enforce_ownership(caller, line["account_id"])
    return response.ok(models.migration_out(record))


@bp.get("/subscriber-lines/<line_id>/migration-requests")
@middleware.require_roles(*READERS)
def list_line_migrations(caller, line_id):
    from flask import request

    line = lookups.line(line_id)
    middleware.enforce_ownership(caller, line["account_id"])
    rows = [
        m for m in storage.db.all("migration_requests")
        if m["subscriber_line_id"] == line_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.migration_out(r) for r in page], limit, offset, total)


@bp.post("/migration-requests/<migration_id>/check-eligibility")
@middleware.require_roles(*WRITERS)
def check_eligibility(caller, migration_id):
    data = middleware.body()
    record = lookups.migration(migration_id)
    line = lookups.line(record["subscriber_line_id"])
    state = record["migration_state"]

    if state == "DRAFT":
        if line["billing_mode"] != "PREPAID":
            errors.fail("ERR_INVALID_STATE",
                        "Only a prepaid line can open a migration.")
        record["migration_state"] = "ELIGIBILITY_CHECK"
        models.touch(record)
        evaluate_eligibility(record, line)
    elif state == "APPROVED":
        if not _protection_cleared_since(record, line):
            errors.fail("ERR_INVALID_STATE",
                        "No protection case has been cleared since the last evaluation.")
        record["migration_state"] = "ELIGIBILITY_CHECK"
        models.touch(record)
        evaluate_eligibility(record, line)
    else:
        errors.fail("ERR_INVALID_STATE",
                    "The migration is not in a state that permits an eligibility check.")

    if "changed_at" in data and data.get("changed_at") is not None:
        changed = clock.to_iso(data.get("changed_at"))
        if changed is None:
            errors.fail("ERR_INVALID_REQUEST", "changed_at must be an ISO 8601 instant.")
        record["requested_cutover_at"] = clock.fmt(changed)
        models.touch(record)

    # The scheduling step is automatic: a request that is APPROVED with a due
    # cutover moves on to CUTOVER_SCHEDULED in the same call.
    schedule_if_due(record)

    return response.ok(models.migration_out(record))


def _protection_cleared_since(migration, line):
    last_evaluated = clock.parse_instant(migration["updated_at"])
    for case in storage.db.all("port_protection_cases"):
        if case["subscriber_line_id"] != line["id"]:
            continue
        if case["case_state"] != "CLEARED" or case["cleared_at"] is None:
            continue
        cleared = clock.parse_instant(case["cleared_at"])
        if last_evaluated is None or (cleared is not None and cleared > last_evaluated):
            return True
    return False