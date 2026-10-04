"""Event applications: submission, sanctioning, reporting and code redemption.

  POST /op/event-applications                        submit an application
  GET  /op/event-applications                        list applications
  GET  /op/event-applications/{id}                   retrieve one
  PATCH /op/event-applications/{id}                  edit mutable fields
  POST /op/event-applications/{id}/transition        all lifecycle actions
  GET  /op/event-applications/{id}/prizing-summary   computed read
  POST /op/event-applications/{id}/prize-reports     file results
  POST /op/event-applications/{id}/code-redemption   redeem a printed code
  GET  /op/event-applications/{id}/prize-distributions  reverse-reachability read
"""

from datetime import timedelta

from flask import Blueprint, request

import db as store
import computed as calcs
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE,
    STRING, INTEGER, DATETIME,
    require_role, check_body, check_query_enums, require_action,
    is_ops_or_owner, body_of,
)
from services import application as app_service
from utils import parse_dt, clock
from computed import EVENT_COMPLETION_DAYS_AFTER_STREET

bp = Blueprint("event_applications", __name__)

TIERS = ("LOCAL", "QUALIFIER", "CHAMPIONSHIP")
APP_STATUSES = ("SUBMITTED", "APPROVED", "DENIED", "WITHDRAWN", "COMPLETED", "REPORTED")
PRIZING_STATUSES = ("NOT_DUE", "DUE", "SUBMITTED")
APP_ACTIONS = ("APPROVE", "DENY", "WITHDRAW", "COMPLETE", "OPTION_IN", "OPTION_OUT")
POOL_MODES = ("BUNDLED", "UNBUNDLED")
CODE_KINDS = ("DIGITAL", "PHYSICAL")
REDEMPTION_ACTIONS = ("REDEEM", "DECLINE")


# --------------------------------------------------------------------------
# POST /op/event-applications
# --------------------------------------------------------------------------

@bp.route("/op/event-applications", methods=["POST"])
def create_application():
    require_role(request, (ROLE_STORE_ORGANIZER,))
    body = check_body(
        request,
        required=("store_id", "set_release_id", "format_id", "format_code",
                  "tier", "scheduled_date", "expected_headcount"),
        types={
            "store_id": STRING,
            "set_release_id": STRING,
            "format_id": STRING,
            "format_code": STRING,
            "tier": STRING,
            "scheduled_date": DATETIME,
            "expected_headcount": INTEGER,
        },
        enums={"tier": TIERS},
    )

    store_row = store.db.stores.get(body["store_id"])
    if store_row is None:
        fail("ERR_NOT_FOUND", "Store %s does not exist." % body["store_id"])
    release = store.db.set_releases.get(body["set_release_id"])
    if release is None:
        fail("ERR_NOT_FOUND", "SetRelease %s does not exist." % body["set_release_id"])
    format_row = store.db.formats.get(body["format_id"])
    if format_row is None:
        fail("ERR_NOT_FOUND", "Format %s does not exist." % body["format_id"])

    scheduled = parse_dt(body["scheduled_date"])
    if scheduled is None:
        fail("ERR_INVALID_REQUEST", "scheduled_date must be an ISO 8601 datetime.")

    # The format-legality rule also guards submission (§3.3), and it is checked
    # before the row is written so a rejected submission leaves no trace.
    probe = {
        "format_code": body["format_code"],
        "format_id": body["format_id"],
        "set_release_id": body["set_release_id"],
    }
    _check_format_legality(probe, format_row)

    row = store.insert_event_application(
        body["store_id"], body["set_release_id"], body["format_id"],
        body["format_code"], body["tier"], scheduled, body["expected_headcount"],
    )
    return envelope.object_response(models.event_application_view(row), status=201)


def _check_format_legality(probe, format_row):
    """format_code equality plus the rotation-epoch legality rule."""
    if probe["format_code"] != format_row["format_code"]:
        fail("ERR_FORMAT_CODE_NOT_LEGAL",
             "format_code does not match the format named by format_id.")
    recorded = store.db.format_legal_sets.get(format_row["id"], {})
    if probe["set_release_id"] in recorded:
        if format_row["current_epoch"] > recorded[probe["set_release_id"]]:
            fail("ERR_FORMAT_CODE_NOT_LEGAL",
                 "The cited format has rotated past the epoch in which this set "
                 "release was legalized.")


# --------------------------------------------------------------------------
# GET /op/event-applications
# --------------------------------------------------------------------------

@bp.route("/op/event-applications", methods=["GET"])
def list_applications():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    check_query_enums(request, {
        "tier": TIERS,
        "status": APP_STATUSES,
    })
    rows = list(store.db.event_applications.values())
    for name in ("store_id", "set_release_id", "format_id", "tier", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response(
        [models.event_application_view(r) for r in rows], limit, offset)


# --------------------------------------------------------------------------
# GET /op/event-applications/{id}
# --------------------------------------------------------------------------

@bp.route("/op/event-applications/<application_id>", methods=["GET"])
def get_application(application_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    row = store.db.event_applications.get(application_id)
    if row is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)
    return envelope.object_response(models.event_application_view(row))


# --------------------------------------------------------------------------
# PATCH /op/event-applications/{id}
# --------------------------------------------------------------------------

@bp.route("/op/event-applications/<application_id>", methods=["PATCH"])
def patch_application(application_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER))
    body = check_body(
        request,
        optional=("expected_headcount", "scheduled_date"),
        types={"expected_headcount": INTEGER, "scheduled_date": DATETIME},
    )
    if body.get("expected_headcount") is None and body.get("scheduled_date") is None:
        fail("ERR_INVALID_REQUEST",
             "At least one of expected_headcount or scheduled_date must be supplied.")

    row = store.db.event_applications.get(application_id)
    if row is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)
    if not is_ops_or_owner(request, row["store_id"]):
        fail("ERR_UNAUTHORIZED", "This application belongs to another store.")

    if row["status"] not in ("SUBMITTED", "APPROVED"):
        fail("ERR_INVALID_STATE",
             "Only a SUBMITTED or APPROVED application may be edited.")

    changes = {}
    if body.get("expected_headcount") is not None:
        changes["expected_headcount"] = body["expected_headcount"]
    if body.get("scheduled_date") is not None:
        scheduled = parse_dt(body["scheduled_date"])
        if scheduled is None:
            fail("ERR_INVALID_REQUEST", "scheduled_date must be an ISO 8601 datetime.")
        changes["scheduled_date"] = scheduled

    # A corrected competitive event does not keep a deadline computed from its
    # original date, so an APPROVED application's deadline is re-derived.
    if row["status"] == "APPROVED" and row["tier"] != "LOCAL":
        release = store.db.set_releases.get(row["set_release_id"])
        if release is not None:
            changes["reporting_due_by"] = calcs.reporting_due_by(
                row["tier"], release["street_date"])

    store.touch(row, **changes)
    return envelope.object_response(models.event_application_view(row))


# --------------------------------------------------------------------------
# POST /op/event-applications/{id}/transition
# --------------------------------------------------------------------------

@bp.route("/op/event-applications/<application_id>/transition", methods=["POST"])
def transition_application(application_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER))
    body = check_body(
        request,
        required=("action",),
        optional=("expected_store_version", "pool_mode", "pool_variant"),
        types={
            "action": STRING,
            "expected_store_version": INTEGER,
            "pool_mode": STRING,
            "pool_variant": STRING,
        },
        enums={"pool_mode": POOL_MODES},
    )
    action = require_action(body, APP_ACTIONS)

    row = store.db.event_applications.get(application_id)
    if row is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)
    if not is_ops_or_owner(request, row["store_id"]):
        fail("ERR_UNAUTHORIZED", "This application belongs to another store.")

    store_row = store.db.stores.get(row["store_id"])
    if store_row is None:
        fail("ERR_NOT_FOUND", "The application's store no longer exists.")
    format_row = store.db.formats.get(row["format_id"])

    if action == "APPROVE":
        if format_row is None:
            fail("ERR_NOT_FOUND", "The application's format no longer exists.")
        app_service.check_approval(row, store_row, format_row, body)
        app_service.apply_approval(row, store_row, body)
    elif action == "DENY":
        _deny(row)
    elif action == "WITHDRAW":
        _withdraw(row)
    elif action == "COMPLETE":
        _complete(row)
    elif action == "OPTION_IN":
        _option(row, to_due=True)
    else:  # OPTION_OUT
        _option(row, to_due=False)

    return envelope.object_response(models.event_application_view(row))


def _deny(row):
    """A StoreOrganizer may give up on a submitted application."""
    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED application may be denied.")
    # No PrizeAllocation is created.
    store.touch(row, status="DENIED")


def _withdraw(row):
    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED application may be withdrawn.")
    store.touch(row, status="WITHDRAWN")


def _complete(row):
    """Completion only unlocks reporting; it mutates nothing else."""
    if row["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED application may be completed.")
    release = store.db.set_releases.get(row["set_release_id"])
    if release is None:
        fail("ERR_NOT_FOUND", "The application's set release no longer exists.")
    earliest = release["street_date"] + timedelta(days=EVENT_COMPLETION_DAYS_AFTER_STREET)
    if clock.now() < earliest:
        fail("ERR_INVALID_STATE",
             "An application may not be completed until seven days past the street date.")
    store.touch(row, status="COMPLETED")


def _option(row, to_due):
    """OPTION_IN / OPTION_OUT: neither touches any allocation."""
    if row["status"] not in ("SUBMITTED", "APPROVED", "COMPLETED"):
        fail("ERR_INVALID_STATE",
             "The reporting window may only be opted into or out of while the "
             "application is SUBMITTED, APPROVED or COMPLETED.")
    if to_due:
        if row["prizing_report_status"] != "NOT_DUE":
            fail("ERR_INVALID_STATE", "The reporting window is already open.")
        store.touch(row, prizing_report_status="DUE")
    else:
        if row["prizing_report_status"] != "DUE":
            fail("ERR_INVALID_STATE", "The reporting window is not open.")
        store.touch(row, prizing_report_status="NOT_DUE")


# --------------------------------------------------------------------------
# GET /op/event-applications/{id}/prizing-summary
# --------------------------------------------------------------------------

@bp.route("/op/event-applications/<application_id>/prizing-summary", methods=["GET"])
def prizing_summary(application_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    row = store.db.event_applications.get(application_id)
    if row is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)

    deadline = row["reporting_due_by"]
    if deadline is None:
        due_status = "NOT_SCHEDULED"
    elif clock.now() <= deadline:
        due_status = "OPEN"
    else:
        due_status = "PAST_DUE"

    report_status, qualified, gate_error = calcs.headcount_gate(row)

    allocation = store.db.prize_allocations.get(row.get("prize_allocation_id"))
    remaining = calcs.prize_pool_remaining(allocation) if allocation else 0

    from utils import to_iso
    return envelope.object_response({
        "reporting_due_by": to_iso(deadline),
        "reporting_due_status": due_status,
        "qualified_headcount": qualified,
        "prize_pool_remaining_tp": remaining,
        "report_status": report_status,
        "headcount_gate_error": gate_error,
    })


# --------------------------------------------------------------------------
# POST /op/event-applications/{id}/prize-reports
# --------------------------------------------------------------------------

@bp.route("/op/event-applications/<application_id>/prize-reports", methods=["POST"])
def file_prize_report(application_id):
    require_role(request, (ROLE_STORE_ORGANIZER,))
    body = check_body(
        request,
        required=("prize_allocation_id", "unclaimed_tp", "reported_headcount"),
        types={
            "prize_allocation_id": STRING,
            "unclaimed_tp": INTEGER,
            "reported_headcount": INTEGER,
        },
    )

    row = store.db.event_applications.get(application_id)
    if row is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)
    allocation = store.db.prize_allocations.get(body["prize_allocation_id"])
    if allocation is None:
        fail("ERR_NOT_FOUND",
             "PrizeAllocation %s does not exist." % body["prize_allocation_id"])
    if not is_ops_or_owner(request, row["store_id"]):
        fail("ERR_UNAUTHORIZED", "This application belongs to another store.")

    # State rungs fire before the business rungs (§2.12).
    if row["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "Only a COMPLETED application may be reported.")
    if row["prizing_report_status"] != "DUE":
        fail("ERR_INVALID_STATE",
             "The application's reporting window is not open.")

    # The pool named in the body must be the pool the application recorded.
    if body["prize_allocation_id"] != row.get("prize_allocation_id"):
        fail("ERR_INVALID_REQUEST",
             "prize_allocation_id is not the allocation recorded on this application.")

    if row["reporting_due_by"] is not None and clock.now() > row["reporting_due_by"]:
        fail("ERR_REPORT_WINDOW_CLOSED",
             "The reporting deadline for this event has passed.")

    for existing in store.reports_for_application(application_id):
        fail("ERR_PRIZE_REPORT_ALREADY_FILED",
             "A prize report has already been filed for this application.")

    report = store.insert_prize_report(
        application_id, body["prize_allocation_id"],
        body["unclaimed_tp"], body["reported_headcount"], status="FILED")

    store.touch(row,
                status="REPORTED",
                prizing_report_status="SUBMITTED",
                prize_report_id=report["id"])
    _sync_allocation(allocation, body["unclaimed_tp"])
    _derive_store_tier(row["store_id"])

    return envelope.object_response(models.prize_report_view(report), status=201)


def _sync_allocation(allocation, unclaimed_tp):
    """Restore the report's unclaimed_tp to the pool, then re-derive the balance."""
    allocation["total_restored_tp"] = allocation["total_restored_tp"] + unclaimed_tp
    allocation["remaining_tp"] = calcs.prize_pool_remaining(allocation)
    store.touch(allocation)


def _derive_store_tier(store_id):
    store_row = store.db.stores.get(store_id)
    if store_row is None:
        return
    tier = calcs.store_reporting_tier(store_id)
    if store_row["reporting_tier"] != tier:
        store.touch(store_row, reporting_tier=tier)


# --------------------------------------------------------------------------
# POST /op/event-applications/{id}/code-redemption
# --------------------------------------------------------------------------

@bp.route("/op/event-applications/<application_id>/code-redemption", methods=["POST"])
def redeem_code(application_id):
    require_role(request, (ROLE_STORE_ORGANIZER,))
    body = check_body(
        request,
        required=("redemption_code", "code_kind"),
        optional=("action",),
        types={"redemption_code": STRING, "code_kind": STRING, "action": STRING},
        enums={"code_kind": CODE_KINDS, "action": REDEMPTION_ACTIONS},
    )
    action = body.get("action") or "REDEEM"

    row = store.db.event_applications.get(application_id)
    if row is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)

    # The presented code must match exactly one existing card (§2.11).
    matches = [c for c in store.db.code_redemptions.values()
               if c["redemption_code"] == body["redemption_code"]]
    if len(matches) != 1:
        fail("ERR_INVALID_REDEMPTION_CODE",
             "The redemption code matches no card, or matches more than one.")
    card = matches[0]

    if not is_ops_or_owner(request, row["store_id"]):
        fail("ERR_UNAUTHORIZED", "This application belongs to another store.")

    if card["status"] != "AVAILABLE":
        fail("ERR_INVALID_STATE", "Only an AVAILABLE card may be redeemed or declined.")

    if action == "DECLINE":
        # Declining is available only to a card of kind PHYSICAL.
        if card["code_kind"] != "PHYSICAL":
            fail("ERR_INVALID_STATE", "Only a PHYSICAL card may be declined.")
        card["physical_grant_status"] = "NOT_APPLICABLE"
        store.touch(card, status="DECLINED")
        return envelope.object_response(models.code_redemption_view(card), status=201)

    if row["status"] not in ("SUBMITTED", "APPROVED"):
        fail("ERR_INVALID_STATE",
             "A code may only be redeemed against a SUBMITTED or APPROVED application.")

    card["redemption_seq"] = store.next_redemption_seq()
    changes = {"status": "REDEEMED"}
    if card["code_kind"] == "PHYSICAL":
        # Physical fulfilment is a separate parallel dimension.
        changes["physical_grant_status"] = "RESERVED"
    store.touch(card, **changes)
    return envelope.object_response(models.code_redemption_view(card), status=201)


# --------------------------------------------------------------------------
# GET /op/event-applications/{id}/prize-distributions
# --------------------------------------------------------------------------

@bp.route("/op/event-applications/<application_id>/prize-distributions", methods=["GET"])
def application_distributions(application_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    row = store.db.event_applications.get(application_id)
    if row is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)

    allocation_id = row.get("prize_allocation_id")
    if not allocation_id:
        return envelope.array_response([])
    rows = store.distributions_of(allocation_id)
    rows.sort(key=lambda r: r["created_at"])
    return envelope.array_response([models.prize_distribution_view(r) for r in rows])