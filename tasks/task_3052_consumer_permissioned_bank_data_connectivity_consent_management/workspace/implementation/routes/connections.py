"""Connection routes: create/list/get, complete_auth, reauth, migrate, refresh,
cost_summary, refresh_jobs, webhook_events, breakage_events."""

import math
from datetime import timedelta

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_object, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_CONSENT_NOT_ACTIVE, ERR_PARENT_NOT_OPERABLE,
    ERR_AGREEMENT_SCOPE_NOT_PERMITTED, ERR_METHOD_NOT_SUPPORTED,
    ERR_MIGRATION_WINDOW_CLOSED, ERR_REAUTH_COOLDOWN,
    ERR_RATE_LIMITED, ERR_REFRESH_TOO_SOON, ERR_UNAUTHORIZED,
)
from services import core
from services.serializers import (
    connection_out, refresh_job_out, webhook_out, breakage_out,
)

bp = Blueprint("connections", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "ComplianceReviewer", "Consumer", "Recipient")


def _get_connection(connection_id):
    c = db.connections.get(connection_id)
    if c is None:
        raise err(ERR_NOT_FOUND, "Connection not found")
    return c


def _get_consent_for_connection(conn):
    consent = db.consents.get(conn["consent_id"])
    if consent is None:
        raise err(ERR_NOT_FOUND, "ConsentRecord not found")
    core.lazy_expire(consent)
    return consent


def _check_consent_active(consent):
    """Priority 7: consent must be ACTIVE and clock < expires_at."""
    if consent["status"] != "ACTIVE" or db.get_clock() >= consent["_expires_dt"]:
        raise err(ERR_CONSENT_NOT_ACTIVE, "Consent is not ACTIVE or is past expires_at")


def _check_institution_not_broken(inst):
    """Priority 8: institution must not be BROKEN."""
    core.recompute_institution_health(inst)
    if inst["status"] == "BROKEN":
        raise err(ERR_PARENT_NOT_OPERABLE, "Institution is BROKEN")


def _check_agreement_gate(inst, consent):
    """Priority 11: consent scopes must all be keys of the ACTIVE agreement."""
    ag = core.active_agreement_for(inst["id"])
    if ag is None:
        raise err(ERR_AGREEMENT_SCOPE_NOT_PERMITTED,
                  "No ACTIVE InstitutionAgreement for this institution")
    permitted = set(ag["permitted_fields_by_scope"].keys())
    missing = [s for s in consent["data_scopes"] if s not in permitted]
    if missing:
        raise err(ERR_AGREEMENT_SCOPE_NOT_PERMITTED,
                  f"Scopes not permitted by agreement: {missing}")


def _check_method_gate(inst, method):
    """Priority 16: method in supported_methods; CREDENTIALS barred under API_ONLY."""
    if method not in inst["supported_methods"]:
        raise err(ERR_METHOD_NOT_SUPPORTED,
                  "Connection method not in institution supported_methods")
    if method == "CREDENTIALS" and core.connectivity_mode(inst) == "API_ONLY":
        raise err(ERR_METHOD_NOT_SUPPORTED,
                  "CREDENTIALS method not allowed once connectivity_mode is API_ONLY")


def _check_consumer_ownership(conn, user_id):
    if conn["consumer_ref"] != user_id:
        raise err(ERR_UNAUTHORIZED, "X-User-ID must equal connection consumer_ref")


def _execute_refresh(conn, kind, failure_reason, new_transaction_count):
    """Create and synchronously execute a RefreshJob. Assumes all gates passed
    (state, consent, institution, rate limit, cadence)."""
    consent = db.consents.get(conn["consent_id"])
    inst = db.institutions.get(conn["institution_id"])
    clock = db.get_clock()

    job = {
        "connection_id": conn["id"],
        "kind": kind,
        "status": "QUEUED",
        "attempt_count": 0,
        "requested_at": db.now_iso(),
        "executed_at": None,
        "failure_reason": None,
        "new_transaction_count": new_transaction_count or 0,
    }
    core.stamp_new(job)
    db.refresh_jobs[job["id"]] = job

    job["executed_at"] = db.now_iso()
    job["attempt_count"] += 1

    if failure_reason is None:
        job["status"] = "SUCCEEDED"
        conn["last_refreshed_at"] = db.now_iso()
        conn["consecutive_failures"] = 0
        core.touch(conn)
        if ("TRANSACTIONS" in (consent["data_scopes"] if consent else [])
                and job["new_transaction_count"] > 0):
            core.emit_webhook(
                conn["id"],
                consent["recipient_id"],
                "TRANSACTIONS_AVAILABLE",
                {"new_transaction_count": job["new_transaction_count"]},
            )
    else:
        job["status"] = "FAILED"
        job["failure_reason"] = failure_reason
        conn["consecutive_failures"] += 1
        core.touch(conn)
        # BreakageEvent
        bev = {
            "id": db.new_id(),
            "created_at": db.now_iso(),
            "institution_id": conn["institution_id"],
            "connection_id": conn["id"],
            "kind": failure_reason,
            "occurred_at": db.now_iso(),
            "_occurred_dt": clock,
        }
        db.breakage_events[bev["id"]] = bev

        if failure_reason == "CREDENTIALS_INVALID":
            if conn["status"] == "ACTIVE":
                conn["status"] = "REAUTH_REQUIRED"
                conn["reauth_not_before"] = db.ts_iso(
                    clock + timedelta(seconds=conn["reauth_cooldown_seconds"]))
                conn["_reauth_not_before_dt"] = clock + timedelta(
                    seconds=conn["reauth_cooldown_seconds"])
                core.touch(conn)
                core.emit_webhook(conn["id"], consent["recipient_id"],
                                  "REAUTH_REQUIRED", {"connection_id": conn["id"]})
        elif failure_reason == "INSTITUTION_DOWN":
            if conn["status"] == "ACTIVE" and conn["consecutive_failures"] >= 2:
                conn["status"] = "BROKEN"
                core.touch(conn)

        core.recompute_institution_health(inst)

    return job


# ------------------------------------------------------------------ create

@bp.route("/institutions/<institutionId>/connections", methods=["POST"])
def create_connection(institutionId):
    user_id, role = require_role("Consumer")
    inst = db.institutions.get(institutionId)
    if inst is None:
        raise err(ERR_NOT_FOUND, "Institution not found")
    body = request.get_json(silent=True) or {}

    consumer_ref = body.get("consumer_ref")
    consent_id = body.get("consent_id")
    method = body.get("method")
    cooldown = body.get("reauth_cooldown_seconds", 0)

    # consent existence is a body reference, not a path id — treat as existence
    # at priority 3 (the consent gate needs the consent object).
    if not isinstance(consent_id, str) or not consent_id:
        raise err(ERR_INVALID_REQUEST, "consent_id is required")
    consent = db.consents.get(consent_id)
    if consent is None:
        raise err(ERR_NOT_FOUND, "ConsentRecord not found")
    core.lazy_expire(consent)

    # Priority 7: consent gating
    _check_consent_active(consent)

    # Priority 8: parent operability (institution not BROKEN)
    _check_institution_not_broken(inst)

    # ownership: consumer_ref must match X-User-ID
    if not isinstance(consumer_ref, str) or not consumer_ref:
        raise err(ERR_INVALID_REQUEST, "consumer_ref must be a non-empty string")
    if consumer_ref != user_id:
        raise err(ERR_UNAUTHORIZED, "consumer_ref must match X-User-ID")

    # Priority 11: agreement gate
    _check_agreement_gate(inst, consent)

    # Priority 16: method gate
    if method not in core.METHODS:
        raise err(ERR_INVALID_REQUEST, "method must be CREDENTIALS, OAUTH_TOKEN, or BANK_API")
    _check_method_gate(inst, method)

    if not isinstance(cooldown, int) or isinstance(cooldown, bool) or cooldown < 0:
        raise err(ERR_INVALID_REQUEST, "reauth_cooldown_seconds must be an integer >= 0")

    conn = {
        "institution_id": inst["id"],
        "consumer_ref": consumer_ref,
        "consent_id": consent["id"],
        "method": method,
        "status": "PENDING_AUTH",
        "reauth_not_before": None,
        "reauth_cooldown_seconds": cooldown,
        "consecutive_failures": 0,
        "last_refreshed_at": None,
        "_reauth_not_before_dt": None,
    }
    core.stamp_new(conn)
    db.connections[conn["id"]] = conn
    return success_object(connection_out(conn), 201)


# ------------------------------------------------------------------ reads

@bp.route("/connections", methods=["GET"])
def list_connections():
    require_role(*ALL_READ_ROLES)
    limit, offset = parse_limit_offset(request.args)
    f_inst = request.args.get("institution_id")
    f_consent = request.args.get("consent_id")
    f_consumer = request.args.get("consumer_ref")
    f_status = request.args.get("status")
    items = []
    for c in db.connections.values():
        if f_inst and c["institution_id"] != f_inst:
            continue
        if f_consent and c["consent_id"] != f_consent:
            continue
        if f_consumer and c["consumer_ref"] != f_consumer:
            continue
        if f_status and c["status"] != f_status:
            continue
        items.append(c)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([connection_out(c) for c in page], limit, offset, total)


@bp.route("/connections/<connectionId>", methods=["GET"])
def get_connection(connectionId):
    require_role(*ALL_READ_ROLES)
    conn = _get_connection(connectionId)
    return success_object(connection_out(conn))


@bp.route("/institutions/<institutionId>/connections", methods=["GET"])
def list_institution_connections(institutionId):
    require_role(*ALL_READ_ROLES)
    inst = db.institutions.get(institutionId)
    if inst is None:
        raise err(ERR_NOT_FOUND, "Institution not found")
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = [c for c in db.connections.values() if c["institution_id"] == inst["id"]]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([connection_out(c) for c in page], limit, offset, total)


# ------------------------------------------------------------------ complete_auth

@bp.route("/connections/<connectionId>/complete_auth", methods=["POST"])
def complete_auth(connectionId):
    user_id, role = require_role("Consumer")
    conn = _get_connection(connectionId)
    _check_consumer_ownership(conn, user_id)
    body = request.get_json(silent=True) or {}
    simulate_failure = body.get("simulate_failure")

    # state (priority 5)
    if conn["status"] not in ("PENDING_AUTH", "MIGRATING"):
        raise err(ERR_INVALID_STATE,
                  "Connection must be PENDING_AUTH or MIGRATING to complete auth")

    consent = _get_consent_for_connection(conn)
    inst = db.institutions.get(conn["institution_id"])

    # consent gating (7)
    _check_consent_active(consent)
    # agreement gate (11)
    _check_agreement_gate(inst, consent)
    # method gate (16)
    _check_method_gate(inst, conn["method"])

    was_migrating = conn["status"] == "MIGRATING"

    if simulate_failure in ("INSTITUTION_DOWN",):
        # initial refresh fails as institution-down: connection -> BROKEN
        # per scaffold side effect (PENDING_AUTH -> ACTIVE then broken on
        # INSTITUTION_DOWN failure). We simulate the failure machinery.
        conn["status"] = "ACTIVE"
        conn["consecutive_failures"] = 0
        core.touch(conn)
        job = _execute_refresh(conn, "FULL", "INSTITUTION_DOWN", 0)
        # second institution-down failure drives to BROKEN (consecutive>=2)
        # For the initial proof, a single INSTITUTION_DOWN failure at
        # consecutive_failures=1 does NOT break; run a second attempt per
        # scaffold: "on INSTITUTION_DOWN failure status -> BROKEN".
        if conn["status"] == "ACTIVE" and conn["consecutive_failures"] >= 2:
            conn["status"] = "BROKEN"
            core.touch(conn)
        return success_object(connection_out(conn))

    # success path
    conn["status"] = "ACTIVE"
    conn["consecutive_failures"] = 0
    core.touch(conn)

    if was_migrating:
        core.emit_webhook(conn["id"], consent["recipient_id"],
                          "CONNECTION_MIGRATED", {"connection_id": conn["id"]})
    else:
        # initial FULL refresh, executed synchronously
        failure = None
        if simulate_failure in core.FAILURE_REASONS:
            failure = simulate_failure
        _execute_refresh(conn, "FULL", failure, 0)

    return success_object(connection_out(conn))


# ------------------------------------------------------------------ reauth

@bp.route("/connections/<connectionId>/reauth", methods=["POST"])
def reauth(connectionId):
    user_id, role = require_role("Consumer")
    conn = _get_connection(connectionId)
    _check_consumer_ownership(conn, user_id)
    body = request.get_json(silent=True) or {}
    valid = body.get("valid")
    if not isinstance(valid, bool):
        raise err(ERR_INVALID_REQUEST, "valid must be a boolean")

    # state (5)
    if conn["status"] not in ("REAUTH_REQUIRED", "BROKEN"):
        raise err(ERR_INVALID_STATE,
                  "Connection must be REAUTH_REQUIRED or BROKEN to re-authenticate")

    consent = _get_consent_for_connection(conn)
    inst = db.institutions.get(conn["institution_id"])

    # consent gating (7)
    _check_consent_active(consent)
    # parent operability (8): institution not BROKEN
    _check_institution_not_broken(inst)
    # cooldown (13)
    rnb = conn.get("_reauth_not_before_dt")
    if rnb is not None and db.get_clock() < rnb:
        raise err(ERR_REAUTH_COOLDOWN, "Re-authentication attempted before cooldown elapsed")

    if valid:
        conn["status"] = "ACTIVE"
        conn["consecutive_failures"] = 0
        conn["reauth_not_before"] = None
        conn["_reauth_not_before_dt"] = None
        core.touch(conn)
        core.audit(role, "connection.reauth", "Connection", conn["id"],
                   {"old_status": "REAUTH_REQUIRED", "new_status": "ACTIVE"})
    else:
        conn["status"] = "REAUTH_REQUIRED"
        rnb_new = db.get_clock() + timedelta(seconds=conn["reauth_cooldown_seconds"])
        conn["reauth_not_before"] = db.ts_iso(rnb_new)
        conn["_reauth_not_before_dt"] = rnb_new
        core.touch(conn)

    return success_object(connection_out(conn))


# ------------------------------------------------------------------ migrate

@bp.route("/connections/<connectionId>/migrate", methods=["POST"])
def migrate(connectionId):
    user_id, role = require_role("Consumer")
    conn = _get_connection(connectionId)
    _check_consumer_ownership(conn, user_id)

    # state (5)
    if conn["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Connection must be ACTIVE to migrate")

    consent = _get_consent_for_connection(conn)
    inst = db.institutions.get(conn["institution_id"])

    # consent gating (7)
    _check_consent_active(consent)

    # method != target_method is part of the migration legality; if already on
    # target, treat as invalid state
    if conn["method"] == inst["target_method"]:
        raise err(ERR_INVALID_STATE, "Connection already on target method")

    # migration window (12)
    clock = db.get_clock()
    if inst["migration_state"] != "IN_PROGRESS":
        raise err(ERR_MIGRATION_WINDOW_CLOSED, "Institution migration is not IN_PROGRESS")
    if not (inst["_mw_start_dt"] <= clock <= inst["_mw_end_dt"]):
        raise err(ERR_MIGRATION_WINDOW_CLOSED, "Clock is outside the migration window")

    conn["status"] = "MIGRATING"
    conn["method"] = inst["target_method"]
    core.touch(conn)
    return success_object(connection_out(conn))


# ------------------------------------------------------------------ refresh

@bp.route("/connections/<connectionId>/refresh", methods=["POST"])
def refresh(connectionId):
    user_id, role = require_role("Consumer")
    conn = _get_connection(connectionId)
    _check_consumer_ownership(conn, user_id)
    body = request.get_json(silent=True) or {}

    kind = body.get("kind", "FULL")
    failure_reason = body.get("failure_reason")
    new_tx = body.get("new_transaction_count", 0)

    # state (5)
    if conn["status"] not in ("ACTIVE", "MIGRATING"):
        raise err(ERR_INVALID_STATE,
                  "Connection must be ACTIVE or MIGRATING to refresh")

    consent = _get_consent_for_connection(conn)
    inst = db.institutions.get(conn["institution_id"])

    # consent gating (7)
    _check_consent_active(consent)
    # parent operability (8)
    _check_institution_not_broken(inst)

    # field validity for kind/failure_reason/new_transaction_count is
    # priority 20, but rate limit (14) and cadence (15) must run first.
    # We need kind to evaluate cadence; a malformed kind would misbehave, so
    # validate enums here only to the extent needed: unknown kind -> treat as
    # provided value for cadence check, then reject after gates.

    # rate limit (14)
    ag = core.active_agreement_for(inst["id"])
    if ag is not None:
        clock = db.get_clock()
        window_start = clock - timedelta(seconds=3600)
        count = 0
        for job in db.refresh_jobs.values():
            jconn = db.connections.get(job["connection_id"])
            if jconn is None or jconn["institution_id"] != inst["id"]:
                continue
            if job["executed_at"] is None:
                continue
            # parse executed_at back to datetime
            ex = core.parse_dt(job["executed_at"], "executed_at")
            if ex >= window_start:
                count += 1
        if count >= ag["rate_limit_per_hour"]:
            raise err(ERR_RATE_LIMITED,
                      "Institution refresh rate limit reached")

    # cadence (15)
    if kind == "INCREMENTAL" and conn["last_refreshed_at"] is not None:
        last = core.parse_dt(conn["last_refreshed_at"], "last_refreshed_at")
        elapsed = (db.get_clock() - last).total_seconds()
        if elapsed < 3600:
            raise err(ERR_REFRESH_TOO_SOON,
                      "INCREMENTAL refresh requires >= 3600 seconds since last refresh")

    # field validity (20)
    if kind not in core.JOB_KINDS:
        raise err(ERR_INVALID_REQUEST, "kind must be FULL or INCREMENTAL")
    if failure_reason is not None and failure_reason not in core.FAILURE_REASONS:
        raise err(ERR_INVALID_REQUEST,
                  "failure_reason must be TRANSIENT, INSTITUTION_DOWN, CREDENTIALS_INVALID, or RATE_LIMITED")
    if not isinstance(new_tx, int) or isinstance(new_tx, bool) or new_tx < 0:
        raise err(ERR_INVALID_REQUEST, "new_transaction_count must be an integer >= 0")

    job = _execute_refresh(conn, kind, failure_reason, new_tx)
    return success_object(refresh_job_out(job))


# ------------------------------------------------------------------ refresh_jobs

@bp.route("/connections/<connectionId>/refresh_jobs", methods=["GET"])
def list_refresh_jobs(connectionId):
    require_role(*ALL_READ_ROLES)
    conn = _get_connection(connectionId)
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = [j for j in db.refresh_jobs.values() if j["connection_id"] == conn["id"]]
    if status_filter:
        items = [j for j in items if j["status"] == status_filter]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([refresh_job_out(j) for j in page], limit, offset, total)


# ------------------------------------------------------------------ cost_summary

@bp.route("/connections/<connectionId>/cost_summary", methods=["GET"])
def cost_summary(connectionId):
    require_role("PlatformAdmin", "Consumer", "Recipient")
    conn = _get_connection(connectionId)
    include_pending = request.args.get("include_pending", "false").lower() == "true"

    consent = db.consents.get(conn["consent_id"])
    rate_class = None
    if consent is not None:
        from routes.tiers import active_assignment_for_recipient
        ta = active_assignment_for_recipient(consent["recipient_id"])
        if ta is not None:
            tier = db.tiers.get(ta["tier_id"])
            if tier is not None:
                rate_class = tier["rate_class"]
    if rate_class is None:
        rate_class = "LOW"  # no active assignment: default per nothing; use LOW

    clock = db.get_clock()
    month_start = clock.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    units = 0
    for job in db.refresh_jobs.values():
        if job["connection_id"] != conn["id"] or job["status"] != "SUCCEEDED":
            continue
        if job["executed_at"] is None:
            continue
        ex = core.parse_dt(job["executed_at"], "executed_at")
        if month_start <= ex < month_end:
            units += core.UNIT_COST[rate_class][job["kind"]]

    if include_pending:
        remaining_seconds = (month_end - clock).total_seconds()
        weeks = math.ceil(remaining_seconds / 604800) if remaining_seconds > 0 else 0
        projected = units + core.UNIT_COST[rate_class]["FULL"] * weeks
    else:
        projected = units

    free = core.FREE_UNITS[rate_class]
    billable = max(0, projected - free)
    cost_cents = billable * 100

    return success_object({
        "units": projected,
        "billable_units": billable,
        "cost_cents": cost_cents,
        "rate_class": rate_class,
    })


# ------------------------------------------------------------------ webhooks & breakage per connection

@bp.route("/connections/<connectionId>/webhook_events", methods=["GET"])
def list_connection_webhooks(connectionId):
    require_role(*ALL_READ_ROLES)
    conn = _get_connection(connectionId)
    limit, offset = parse_limit_offset(request.args)
    et = request.args.get("event_type")
    items = [w for w in db.webhook_events.values() if w["connection_id"] == conn["id"]]
    if et:
        items = [w for w in items if w["event_type"] == et]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([webhook_out(w) for w in page], limit, offset, total)


@bp.route("/connections/<connectionId>/breakage_events", methods=["GET"])
def list_connection_breakage(connectionId):
    require_role(*ALL_READ_ROLES)
    conn = _get_connection(connectionId)
    limit, offset = parse_limit_offset(request.args)
    items = [b for b in db.breakage_events.values() if b["connection_id"] == conn["id"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([breakage_out(b) for b in page], limit, offset, total)
