"""Core resource routes: employers, layouts, batches, records, workers, verifiers,
products, authorizations, attestations and the logical clock."""
from flask import Blueprint, request as http_request

import calculations
import clock
import middleware
import models
import response
import serialize
import services_consent as consent
import services_feed as feed
import services_verify as verify
import store
from domain import product_rendered_field_set

bp = Blueprint("core", __name__)


def _body():
    return http_request.get_json(silent=True) or {}


def _require(table, row_id):
    row = store.get(table, row_id)
    if row is None:
        from errors import ApiError
        raise ApiError("ERR_NOT_FOUND")
    return row


def _require_ref(table, row_id):
    row = store.get(table, row_id)
    if row is None:
        from errors import ApiError
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return row


# ------------------------------------------------------------------ employers

@bp.route("/work-number/employers", methods=["POST"])
def create_employer():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    for existing in store.all_rows("employers"):
        if existing.get("fein") == body.get("fein"):
            from errors import ApiError
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    row = models.new_employer(body)
    store.insert("employers", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/employers", methods=["GET"])
def list_employers():
    middleware.require_role(["PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("employers")
    fein = http_request.args.get("fein")
    if fein is not None:
        rows = [r for r in rows if r.get("fein") == fein]
    for row in rows:
        calculations.refresh_employer_feed_status(row)
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/employers/<employer_id>", methods=["GET"])
def get_employer(employer_id):
    role, user_id = middleware.require_role(["PlatformAdmin", "Employer", "Verifier"])
    row = _require("employers", employer_id)
    if role == "Employer" and user_id != employer_id:
        from errors import ApiError
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    consent.dispute_escalation_sweep()
    calculations.refresh_employer_feed_status(row)
    consent._cascade_currency(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/employers/<employer_id>/freeze", methods=["POST"])
def freeze(employer_id):
    role, user_id = middleware.require_role(["PlatformAdmin", "Employer"])
    row = _require("employers", employer_id)
    middleware.require_self(role, user_id, employer_id, "Employer", "employers")
    body = _body()
    feed.freeze_employer(row, body.get("reason_code"))
    return response.success(serialize.out(row))


@bp.route("/work-number/employers/<employer_id>/unfreeze", methods=["POST"])
def unfreeze(employer_id):
    role, user_id = middleware.require_role(["PlatformAdmin", "Employer"])
    row = _require("employers", employer_id)
    middleware.require_self(role, user_id, employer_id, "Employer", "employers")
    body = _body()
    feed.unfreeze_employer(row, body.get("outcome"))
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ record layouts

@bp.route("/work-number/record-layouts", methods=["POST"])
def create_layout():
    role, user_id = middleware.require_role(["Employer"])
    body = _body()
    employer = _require_ref("employers", body.get("employer_id"))
    if role == "Employer" and user_id != employer["id"]:
        from errors import ApiError
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    row = models.new_record_layout(body)
    store.insert("record_layouts", row)
    feed.register_layout(row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/record-layouts", methods=["GET"])
def list_layouts():
    middleware.require_role(["Employer", "PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("record_layouts")
    employer_id = http_request.args.get("employer_id")
    if employer_id is not None:
        rows = [r for r in rows if r.get("employer_id") == employer_id]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/record-layouts/<layout_id>", methods=["GET"])
def get_layout(layout_id):
    middleware.require_role(["Employer", "PlatformAdmin"])
    row = _require("record_layouts", layout_id)
    return response.success(serialize.out(row))


@bp.route("/work-number/record-layouts/<layout_id>", methods=["PATCH"])
def patch_layout(layout_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("record_layouts", layout_id)
    middleware.require_owner(role, user_id, "record_layouts", row, "employer_id")
    body = _body()
    feed.revise_layout(row, body.get("column_map") or {}, body.get("fiscal_year_start_month"))
    return response.success(serialize.out(row))


@bp.route("/work-number/record-layouts/<layout_id>/verify", methods=["POST"])
def verify_layout(layout_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("record_layouts", layout_id)
    middleware.require_owner(role, user_id, "record_layouts", row, "employer_id")
    feed.verify_layout(row)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ payroll feed batches

@bp.route("/work-number/payroll-feed-batches", methods=["POST"])
def create_batch():
    role, user_id = middleware.require_role(["Employer"])
    body = _body()
    employer = _require_ref("employers", body.get("employer_id"))
    if role == "Employer" and user_id != employer["id"]:
        from errors import ApiError
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    _require_ref("record_layouts", body.get("record_layout_id"))
    count = body.get("record_count")
    from errors import ApiError
    if count is None or int(count) < 1 or int(count) > 50000:
        raise ApiError("ERR_BATCH_RECORD_COUNT_EXCEEDED")
    for existing in store.all_rows("payroll_feed_batches"):
        if (existing.get("employer_id") == body.get("employer_id")
                and existing.get("batch_sequence") == body.get("batch_sequence")):
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    row = models.new_payroll_feed_batch(body)
    store.insert("payroll_feed_batches", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/payroll-feed-batches", methods=["GET"])
def list_batches():
    middleware.require_role(["Employer", "PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("payroll_feed_batches")
    employer_id = http_request.args.get("employer_id")
    layout_id = http_request.args.get("record_layout_id")
    if employer_id is not None:
        rows = [r for r in rows if r.get("employer_id") == employer_id]
    if layout_id is not None:
        rows = [r for r in rows if r.get("record_layout_id") == layout_id]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/payroll-feed-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    middleware.require_role(["Employer", "PlatformAdmin"])
    row = _require("payroll_feed_batches", batch_id)
    return response.success(serialize.out(row))


@bp.route("/work-number/payroll-feed-batches/<batch_id>/records", methods=["PATCH"])
def patch_batch_records(batch_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("payroll_feed_batches", batch_id)
    middleware.require_owner(role, user_id, "payroll_feed_batches", row, "employer_id")
    body = _body()
    feed.declare_records(row, body.get("rejected_entries", 0))
    return response.success(serialize.out(row))


@bp.route("/work-number/payroll-feed-batches/<batch_id>/reject", methods=["POST"])
def reject_batch(batch_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("payroll_feed_batches", batch_id)
    middleware.require_owner(role, user_id, "payroll_feed_batches", row, "employer_id")
    feed.reject_batch(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/payroll-feed-batches/<batch_id>/validate", methods=["POST"])
def validate_batch(batch_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("payroll_feed_batches", batch_id)
    middleware.require_owner(role, user_id, "payroll_feed_batches", row, "employer_id")
    employer = _require("employers", row.get("employer_id"))
    feed.validate_batch(row, employer)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ employment records

@bp.route("/work-number/employment-records", methods=["POST"])
def create_record():
    role, user_id = middleware.require_role(["Employer"])
    body = _body()
    employer = _require_ref("employers", body.get("employer_id"))
    if role == "Employer" and user_id != employer["id"]:
        from errors import ApiError
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    _require_ref("covered_workers", body.get("covered_worker_id"))
    batch = _require_ref("payroll_feed_batches", body.get("payroll_feed_batch_id"))
    from errors import ApiError
    if batch.get("validation_state") != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    hire = clock.parse_iso(body.get("hire_date"))
    sep = clock.parse_iso(body.get("separation_date"))
    if sep is not None and hire is not None and sep < hire:
        raise ApiError("ERR_BATCH_RECORD_COUNT_EXCEEDED")
    row = models.new_employment_record(body)
    calculations.recompute_record(row, employer)
    store.insert("employment_records", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/employment-records", methods=["GET"])
def list_records():
    middleware.require_role(["PlatformAdmin", "Employer", "CoveredWorker"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("employment_records")
    for key in ("employer_id", "covered_worker_id", "payroll_feed_batch_id"):
        value = http_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/employment-records/<record_id>", methods=["GET"])
def get_record(record_id):
    middleware.require_role(["PlatformAdmin", "Employer", "CoveredWorker", "Verifier"])
    row = _require("employment_records", record_id)
    return response.success(serialize.out(row))


@bp.route("/work-number/employment-records/<record_id>/reconfirm", methods=["POST"])
def reconfirm_record(record_id):
    role, user_id = middleware.require_role(["CoveredWorker"])
    row = _require("employment_records", record_id)
    middleware.require_owner(role, user_id, "employment_records", row, "covered_worker_id")
    if row.get("record_state") != "CORRECTED":
        from errors import ApiError
        raise ApiError("ERR_INVALID_STATE")
    employer = _require("employers", row.get("employer_id"))
    from errors import ApiError
    from services_verify import freeze_is_live
    if freeze_is_live(employer):
        raise ApiError("ERR_EMPLOYER_FROZEN")
    for dispute in store.all_rows("record_disputes"):
        if dispute.get("employment_record_id") == record_id:
            from domain import OPEN_DISPUTE_STATES
            if dispute.get("dispute_state") in OPEN_DISPUTE_STATES:
                raise ApiError("ERR_INVALID_STATE")
    worker = _require("covered_workers", row.get("covered_worker_id"))
    consent.reconfirm_record(row, worker)
    return response.success(serialize.out(row))


@bp.route("/work-number/employment-records/<record_id>/retain", methods=["POST"])
def retain_record(record_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("employment_records", record_id)
    middleware.require_owner(role, user_id, "employment_records", row, "employer_id")
    from domain import OPEN_DISPUTE_STATES
    from errors import ApiError
    if row.get("record_state") != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE")
    for dispute in store.all_rows("record_disputes"):
        if dispute.get("employment_record_id") == record_id and dispute.get("dispute_state") in OPEN_DISPUTE_STATES:
            raise ApiError("ERR_INVALID_STATE")
    if row.get("currency_state") == "FROZEN":
        raise ApiError("ERR_EMPLOYER_FROZEN")
    consent.retain_record(row, None)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ covered workers

@bp.route("/work-number/covered-workers", methods=["POST"])
def create_worker():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    row = models.new_covered_worker(body)
    store.insert("covered_workers", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/covered-workers", methods=["GET"])
def list_workers():
    middleware.require_role(["PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    page, total = middleware.paginate(store.all_rows("covered_workers"), limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/covered-workers/<worker_id>", methods=["GET"])
def get_worker(worker_id):
    middleware.require_role(["PlatformAdmin", "CoveredWorker", "Verifier"])
    row = _require("covered_workers", worker_id)
    return response.success(serialize.out(row))


@bp.route("/work-number/covered-workers/<worker_id>/opt-out", methods=["POST"])
def opt_out(worker_id):
    role, user_id = middleware.require_role(["CoveredWorker"])
    row = _require("covered_workers", worker_id)
    middleware.require_self(role, user_id, worker_id, "CoveredWorker", "covered_workers")
    consent.opt_out(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/covered-workers/<worker_id>/opt-in", methods=["POST"])
def opt_in(worker_id):
    role, user_id = middleware.require_role(["CoveredWorker"])
    row = _require("covered_workers", worker_id)
    middleware.require_self(role, user_id, worker_id, "CoveredWorker", "covered_workers")
    consent.opt_in(row)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ verifiers

@bp.route("/work-number/verifiers", methods=["POST"])
def create_verifier():
    middleware.require_role(["PlatformAdmin"])
    row = models.new_verifier(_body())
    store.insert("verifiers", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/verifiers", methods=["GET"])
def list_verifiers():
    middleware.require_role(["PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("verifiers")
    cls = http_request.args.get("verifier_class")
    if cls is not None:
        rows = [r for r in rows if r.get("verifier_class") == cls]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/verifiers/<verifier_id>", methods=["GET"])
def get_verifier(verifier_id):
    middleware.require_role(["PlatformAdmin", "Verifier"])
    row = _require("verifiers", verifier_id)
    calculations.verifier_negative_score(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/verifiers/<verifier_id>/accredit", methods=["POST"])
def accredit(verifier_id):
    role, user_id = middleware.require_role(["PlatformAdmin", "Verifier"])
    row = _require("verifiers", verifier_id)
    middleware.require_self(role, user_id, verifier_id, "Verifier", "verifiers")
    verify.accredit(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/verifiers/<verifier_id>/authorize", methods=["POST"])
def authorize_verifier(verifier_id):
    role, user_id = middleware.require_role(["PlatformAdmin", "Verifier"])
    row = _require("verifiers", verifier_id)
    middleware.require_self(role, user_id, verifier_id, "Verifier", "verifiers")
    verify.authorize_verifier(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/verifiers/<verifier_id>/escrow-adjustments", methods=["POST"])
def escrow_adjust(verifier_id):
    middleware.require_role(["PlatformAdmin"])
    row = _require("verifiers", verifier_id)
    verify.adjust_escrow(row, _body().get("amount_cents", 0))
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ products

@bp.route("/work-number/verification-products", methods=["POST"])
def create_product():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    for existing in store.all_rows("verification_products"):
        if existing.get("product_code") == body.get("product_code"):
            from errors import ApiError
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    row = models.new_verification_product(body)
    row["rendered_field_set"] = product_rendered_field_set(
        row.get("tier"), row.get("history_months_included"), row.get("includes_employment_status"))
    store.insert("verification_products", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/verification-products", methods=["GET"])
def list_products():
    middleware.require_role(["PlatformAdmin", "Verifier"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("verification_products")
    active = http_request.args.get("active")
    if active is not None:
        wanted = active.lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("active")) == wanted]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/verification-products/<product_id>", methods=["GET"])
def get_product(product_id):
    middleware.require_role(["PlatformAdmin", "Verifier"])
    row = _require("verification_products", product_id)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ authorizations

@bp.route("/work-number/consumer-authorizations", methods=["POST"])
def create_authorization():
    role, user_id = middleware.require_role(["CoveredWorker"])
    body = _body()
    worker = _require_ref("covered_workers", body.get("covered_worker_id"))
    if role == "CoveredWorker" and user_id != worker["id"]:
        from errors import ApiError
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    _require_ref("verifiers", body.get("verifier_id"))
    from errors import ApiError
    expected = body.get("expected_covered_worker_version")
    if expected is None:
        raise ApiError("ERR_STALE_VERSION")
    if int(expected) != worker.get("version"):
        raise ApiError("ERR_STALE_VERSION")
    row = models.new_consumer_authorization(body)
    store.insert("consumer_authorizations", row)
    consent.capture_authorization(row, worker)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/consumer-authorizations", methods=["GET"])
def list_authorizations():
    middleware.require_role(["CoveredWorker", "Verifier", "PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("consumer_authorizations")
    for key in ("covered_worker_id", "verifier_id"):
        value = http_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/consumer-authorizations/<authorization_id>", methods=["GET"])
def get_authorization(authorization_id):
    middleware.require_role(["CoveredWorker", "Verifier", "PlatformAdmin"])
    row = _require("consumer_authorizations", authorization_id)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ attestations

@bp.route("/work-number/verification-attestations", methods=["POST"])
def create_attestation():
    role, user_id = middleware.require_role(["Verifier"])
    body = _body()
    _require_ref("verification_requests", body.get("verification_request_id"))
    verifier = _require_ref("verifiers", body.get("verifier_id"))
    if role == "Verifier" and user_id != verifier["id"]:
        from errors import ApiError
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    verify._supersede_attestations(body.get("verification_request_id"))
    row = models.new_verification_attestation(body)
    row["attestation_state"] = "SIGNED"
    store.insert("verification_attestations", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/verification-attestations", methods=["GET"])
def list_attestations():
    middleware.require_role(["Verifier", "PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("verification_attestations")
    for key in ("verification_request_id", "verifier_id"):
        value = http_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/verification-attestations/<attestation_id>", methods=["GET"])
def get_attestation(attestation_id):
    middleware.require_role(["Verifier", "PlatformAdmin"])
    row = _require("verification_attestations", attestation_id)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    clock.set_now(clock.parse_iso(body.get("to_iso8601")))
    consent.refresh_all_employer_feed_status()
    consent.dispute_escalation_sweep()
    return response.success({})


@bp.route("/work-number/directives/expire-batch", methods=["POST"])
def expire_batch():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    batch = _require("payroll_feed_batches", body.get("payroll_feed_batch_id"))
    employer = store.get("employers", batch.get("employer_id"))
    if employer is not None:
        base = employer.get("last_feed_received_date") or employer.get("created_at")
        interval = __import__("domain").CADENCE_INTERVAL_DAYS.get(employer.get("payroll_frequency"), 30)
        clock.set_now(clock.add_days(base, interval + 1))
        calculations.refresh_employer_feed_status(employer)
        consent._cascade_currency(employer)
    return response.success(serialize.out(batch))