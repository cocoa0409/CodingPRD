"""Workflow routes: verification requests and responses, disclosures, disputes,
compensation and currency reviews."""
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
from domain import REVIEW_WINDOW_BUFFER_DAYS, SETTLEMENT_VOID_GRACE_DAYS
from errors import ApiError

bp = Blueprint("flow", __name__)


def _body():
    return http_request.get_json(silent=True) or {}


def _require(table, row_id):
    row = store.get(table, row_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND")
    return row


def _require_ref(table, row_id):
    row = store.get(table, row_id)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return row


# ------------------------------------------------------------------ verification requests

@bp.route("/work-number/verification-requests", methods=["POST"])
def create_request():
    middleware.require_role(["Verifier"])
    body = _body()
    _require_ref("verifiers", body.get("verifier_id"))
    _require_ref("covered_workers", body.get("covered_worker_id"))
    _require_ref("verification_products", body.get("product_id"))
    row = models.new_verification_request(body)
    store.insert("verification_requests", row)
    verify.create_request(row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/verification-requests", methods=["GET"])
def list_requests():
    middleware.require_role(["Verifier", "CoveredWorker", "PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("verification_requests")
    for key in ("verifier_id", "covered_worker_id", "product_id",
                "consumer_authorization_id", "current_employer_id"):
        value = http_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/verification-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    middleware.require_role(["Verifier", "CoveredWorker", "PlatformAdmin"])
    row = _require("verification_requests", request_id)
    if row.get("request_state") == "PERMITTED":
        resolution = verify.resolution_for(row)
        row["resolved_product_tier"] = resolution["tier"]
    return response.success(serialize.out(row))


@bp.route("/work-number/verification-requests/<request_id>/permit", methods=["POST"])
def permit_request(request_id):
    role, user_id = middleware.require_role(["CoveredWorker", "PlatformAdmin"])
    row = _require("verification_requests", request_id)
    if role == "CoveredWorker" and user_id != row.get("covered_worker_id"):
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    state = row.get("request_state")
    if state in ("DECLINED", "RESPONDED", "REVERSED_RECONSENT_REQUIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if state not in ("SUBMITTED", "PENDING_AUTH"):
        raise ApiError("ERR_INVALID_STATE")
    body = _body()
    authorization_id = body.get("consumer_authorization_id")
    if authorization_id is None:
        raise ApiError("ERR_INVALID_STATE")
    authorization = store.get("consumer_authorizations", authorization_id)
    if authorization is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    verify.permit_request(row, authorization)
    return response.success(serialize.out(row))


@bp.route("/work-number/verification-requests/<request_id>/validate-currency", methods=["POST"])
def validate_currency(request_id):
    role, user_id = middleware.require_role(["Verifier"])
    consent.dispute_escalation_sweep()
    row = _require("verification_requests", request_id)
    if user_id != row.get("verifier_id"):
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    state = row.get("request_state")
    if state in ("DECLINED", "RESPONDED", "REVERSED_RECONSENT_REQUIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    verify.validate_currency(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/verification-requests/<request_id>/reconsent", methods=["POST"])
def reconsent(request_id):
    role, user_id = middleware.require_role(["CoveredWorker"])
    row = _require("verification_requests", request_id)
    if user_id != row.get("covered_worker_id"):
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    verify.reconsent(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/verification-requests/<request_id>/decline", methods=["POST"])
def decline_request(request_id):
    middleware.require_role(["Verifier", "PlatformAdmin"])
    row = _require("verification_requests", request_id)
    state = row.get("request_state")
    if state in ("DECLINED", "RESPONDED", "REVERSED_RECONSENT_REQUIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    body = _body()
    verify.decline_by_actor(row, body.get("decline_reason"))
    return response.success(serialize.out(row))


@bp.route("/work-number/verification-requests/<request_id>/reverse", methods=["POST"])
def reverse_request(request_id):
    middleware.require_role(["PlatformAdmin"])
    row = _require("verification_requests", request_id)
    if row.get("request_state") != "RESPONDED":
        raise ApiError("ERR_INVALID_STATE")
    verify.reverse_request(row)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ verification responses

@bp.route("/work-number/verification-responses", methods=["POST"])
def build_response():
    middleware.require_role(["Verifier"])
    consent.dispute_escalation_sweep()
    body = _body()
    row = _require_ref("verification_requests", body.get("verification_request_id"))
    for existing in store.all_rows("verification_responses"):
        if existing.get("verification_request_id") == row["id"]:
            raise ApiError("ERR_RESPONSE_ALREADY_MATERIALIZED")
    state = row.get("request_state")
    if state in ("RESPONDED", "DECLINED", "REVERSED_RECONSENT_REQUIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if state not in ("SUBMITTED", "VALIDATED"):
        raise ApiError("ERR_INVALID_STATE")
    created = verify.build_response(row, actor_id=_actor_id())
    return response.success(serialize.out(created)), 201


def _actor_id():
    """The acting X-User-ID, read after the role check has already passed."""
    return http_request.headers.get("X-User-ID")


@bp.route("/work-number/verification-responses", methods=["GET"])
def list_responses():
    middleware.require_role(["Verifier", "CoveredWorker", "PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("verification_responses")
    request_id = http_request.args.get("verification_request_id")
    if request_id is not None:
        rows = [r for r in rows if r.get("verification_request_id") == request_id]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/verification-responses/<response_id>", methods=["GET"])
def get_response(response_id):
    middleware.require_role(["Verifier", "CoveredWorker", "PlatformAdmin"])
    row = _require("verification_responses", response_id)
    consent.dispute_escalation_sweep()
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ disclosures

@bp.route("/work-number/consumer-disclosures", methods=["POST"])
def create_disclosure():
    role, user_id = middleware.require_role(["CoveredWorker"])
    body = _body()
    worker = _require_ref("covered_workers", body.get("covered_worker_id"))
    if user_id != worker["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    row = models.new_consumer_disclosure(body)
    store.insert("consumer_disclosures", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/consumer-disclosures", methods=["GET"])
def list_disclosures():
    middleware.require_role(["CoveredWorker", "PlatformAdmin"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("consumer_disclosures")
    worker_id = http_request.args.get("covered_worker_id")
    if worker_id is not None:
        rows = [r for r in rows if r.get("covered_worker_id") == worker_id]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/consumer-disclosures/<disclosure_id>", methods=["GET"])
def get_disclosure(disclosure_id):
    middleware.require_role(["CoveredWorker", "PlatformAdmin"])
    row = _require("consumer_disclosures", disclosure_id)
    return response.success(serialize.out(row))


@bp.route("/work-number/consumer-disclosures/<disclosure_id>/generate", methods=["POST"])
def generate_disclosure(disclosure_id):
    role, user_id = middleware.require_role(["CoveredWorker"])
    row = _require("consumer_disclosures", disclosure_id)
    worker = _require("covered_workers", row.get("covered_worker_id"))
    if user_id != worker["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    consent.generate_disclosure(row, worker)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ disputes

@bp.route("/work-number/record-disputes", methods=["POST"])
def create_dispute():
    role, user_id = middleware.require_role(["CoveredWorker"])
    body = _body()
    worker = _require_ref("covered_workers", body.get("covered_worker_id"))
    if user_id != worker["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    record = _require_ref("employment_records", body.get("employment_record_id"))
    if record.get("covered_worker_id") != worker["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    expected = body.get("expected_employment_record_version")
    if expected is None or int(expected) != record.get("version"):
        raise ApiError("ERR_STALE_VERSION")
    if record.get("record_state") != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE")
    employer = _require("employers", record.get("employer_id"))
    if verify.freeze_is_live(employer) or record.get("currency_state") == "FROZEN":
        raise ApiError("ERR_EMPLOYER_FROZEN")
    row = models.new_record_dispute(body)
    store.insert("record_disputes", row)
    consent.file_dispute(row, record, worker, employer)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/record-disputes", methods=["GET"])
def list_disputes():
    middleware.require_role(["CoveredWorker", "Employer", "PlatformAdmin"])
    consent.dispute_escalation_sweep()
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("record_disputes")
    for key in ("covered_worker_id", "employment_record_id"):
        value = http_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/record-disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    middleware.require_role(["CoveredWorker", "Employer", "PlatformAdmin"])
    row = _require("record_disputes", dispute_id)
    consent.dispute_escalation_sweep()
    return response.success(serialize.out(row))


@bp.route("/work-number/record-disputes/<dispute_id>/notice", methods=["POST"])
def notice_dispute(dispute_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("record_disputes", dispute_id)
    record = _require("employment_records", row.get("employment_record_id"))
    if user_id != record.get("employer_id"):
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    consent.notice_dispute(row)
    return response.success(serialize.out(row))


@bp.route("/work-number/record-disputes/<dispute_id>/respond", methods=["POST"])
def respond_dispute(dispute_id):
    role, user_id = middleware.require_role(["Employer"])
    row = _require("record_disputes", dispute_id)
    record = _require("employment_records", row.get("employment_record_id"))
    if user_id != record.get("employer_id"):
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    employer = _require("employers", record.get("employer_id"))
    worker = _require("covered_workers", row.get("covered_worker_id"))
    consent.respond_dispute(row, _body().get("resolution"), record, worker, employer)
    return response.success(serialize.out(row))


@bp.route("/work-number/record-disputes/<dispute_id>/reopen", methods=["POST"])
def reopen_dispute(dispute_id):
    role, user_id = middleware.require_role(["CoveredWorker"])
    row = _require("record_disputes", dispute_id)
    if user_id != row.get("covered_worker_id"):
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    record = _require("employment_records", row.get("employment_record_id"))
    employer = _require("employers", record.get("employer_id"))
    worker = _require("covered_workers", row.get("covered_worker_id"))
    body = _body()
    if body.get("resolution") != "REOPEN":
        raise ApiError("ERR_INVALID_STATE")
    consent.reopen_dispute(row, worker, employer)
    return response.success(serialize.out(row))


# ------------------------------------------------------------------ compensation

@bp.route("/work-number/contributor-compensations", methods=["POST"])
def create_accrual():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    _require_ref("employers", body.get("employer_id"))
    for existing in store.all_rows("compensation_accruals"):
        if (existing.get("employer_id") == body.get("employer_id")
                and existing.get("transaction_ref") == body.get("transaction_ref")):
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    count = int(body.get("records_count") or 0)
    if count < 1:
        raise ApiError("ERR_SETTLEMENT_OUTCOME_INVALID")
    row = models.new_compensation_accrual(body)
    unit, gross = calculations.contributor_rate(count)
    row["unit_rate_cents"] = unit
    row["gross_accrued_cents"] = gross
    store.insert("compensation_accruals", row)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/contributor-compensations", methods=["GET"])
def list_accruals():
    middleware.require_role(["PlatformAdmin", "Employer"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("compensation_accruals")
    employer_id = http_request.args.get("employer_id")
    if employer_id is not None:
        rows = [r for r in rows if r.get("employer_id") == employer_id]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/contributor-compensations/<accrual_id>", methods=["GET"])
def get_accrual(accrual_id):
    middleware.require_role(["PlatformAdmin", "Employer"])
    row = _require("compensation_accruals", accrual_id)
    return response.success(serialize.out(row))


def _settlement_order(accrual):
    return (accrual.get("pay_period_end_date"), accrual.get("created_at"),
            accrual.get("transaction_ref") or "")


@bp.route("/work-number/compensation-settlements", methods=["POST"])
def post_settlement():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    employer = _require_ref("employers", body.get("employer_id"))
    period_end = clock.parse_iso(body.get("settlement_period_end"))
    paid_budget = int(body.get("settlement_budget_cents") or 0)
    waiver_budget = int(body.get("waiver_budget_cents") or 0)
    apply_blended = bool(body.get("apply_blended_rate"))

    eligible = [
        accrual for accrual in store.all_rows("compensation_accruals")
        if accrual.get("employer_id") == employer["id"]
        and accrual.get("cycle_state") == "ACCRUED"
        and (period_end is None or accrual.get("pay_period_end_date") <= period_end)
    ]
    if not eligible:
        raise ApiError("ERR_SETTLEMENT_OUTCOME_INVALID")
    eligible.sort(key=_settlement_order)

    remaining_paid = paid_budget
    remaining_waiver = waiver_budget
    touched = []
    gross_total = 0
    net_total = 0
    for accrual in eligible:
        gross = accrual.get("gross_accrued_cents") or 0
        if apply_blended and accrual.get("records_count"):
            unit = calculations.blended_rate(accrual["records_count"])
            gross = accrual["records_count"] * unit
            accrual["unit_rate_cents"] = unit
            accrual["gross_accrued_cents"] = gross
        if gross <= remaining_paid:
            accrual["cycle_state"] = "PAID"
            accrual["paid_cents"] = gross
            accrual["waived_cents"] = 0
            remaining_paid -= gross
            gross_total += gross
            net_total += gross
        elif gross <= remaining_waiver:
            accrual["cycle_state"] = "WAIVED"
            accrual["paid_cents"] = 0
            accrual["waived_cents"] = gross
            remaining_waiver -= gross
            gross_total += gross
        else:
            continue
        employer["compensation_earned_cents"] = (
            (employer.get("compensation_earned_cents") or 0)
            + accrual.get("paid_cents", 0) + accrual.get("waived_cents", 0)
        )
        store.touch(accrual)
        touched.append(accrual)

    settlement = models.entity()
    settlement.update({
        "employer_id": employer["id"],
        "settlement_period_end": period_end,
        "accrual_ids": [accrual["id"] for accrual in touched],
        "settlement_budget_cents": paid_budget,
        "waiver_budget_cents": waiver_budget,
        "apply_blended_rate": apply_blended,
    })
    store.insert("compensation_settlements", settlement)
    store.touch(employer)
    payload = {
        "settlement_id": settlement["id"],
        "accrual_count": len(touched),
        "settled_gross_cents": gross_total,
        "settled_net_cents": net_total,
    }
    return response.success(payload), 201


@bp.route("/work-number/compensation-settlements/<settlement_id>/void", methods=["POST"])
def void_settlement(settlement_id):
    middleware.require_role(["PlatformAdmin"])
    settlement = _require("compensation_settlements", settlement_id)
    employer = _require("employers", settlement.get("employer_id"))
    accrual_count = 0
    reverted = 0
    for accrual_id in settlement.get("accrual_ids", []):
        accrual = store.get("compensation_accruals", accrual_id)
        if accrual is None:
            continue
        state = accrual.get("cycle_state")
        if state == "WAIVED":
            reverted += accrual.get("waived_cents") or 0
            accrual["cycle_state"] = "ACCRUED"
            accrual["waived_cents"] = 0
            accrual["paid_cents"] = 0
            store.touch(accrual)
            accrual_count += 1
        elif state == "PAID":
            if clock.days_elapsed(accrual.get("updated_at")) <= SETTLEMENT_VOID_GRACE_DAYS:
                reverted += accrual.get("paid_cents") or 0
                accrual["cycle_state"] = "ACCRUED"
                accrual["waived_cents"] = 0
                accrual["paid_cents"] = 0
                store.touch(accrual)
                accrual_count += 1
    employer["compensation_earned_cents"] = calculations.employer_compensation_balance(employer)
    store.touch(employer)
    settlement["voided"] = True
    store.touch(settlement)
    payload = {
        "settlement_id": settlement_id,
        "accrual_count": accrual_count,
        "reverted_cents": reverted,
    }
    return response.success(payload)


# ------------------------------------------------------------------ currency reviews

@bp.route("/work-number/data-currency-reviews", methods=["POST"])
def create_review():
    middleware.require_role(["PlatformAdmin"])
    body = _body()
    employer = _require_ref("employers", body.get("employer_id"))
    window_days = int(body.get("window_days") or 0)
    expected = int(body.get("expected_periods") or 0)
    period_end = clock.parse_iso(body.get("review_period_end"))
    if window_days < 1 or expected < 1:
        raise ApiError("ERR_INVALID_STATE")
    for existing in store.all_rows("data_currency_reviews"):
        if existing.get("employer_id") != employer["id"]:
            continue
        if existing.get("review_state") not in ("PENDING", "SCORED", "ESCALATED"):
            continue
        old_end = existing.get("review_period_end")
        old_start = clock.add_days(old_end, -(existing.get("window_days") or 0))
        new_start = clock.add_days(period_end, -window_days)
        gap = None
        if new_start > old_end:
            gap = (new_start - old_end).total_seconds() / 86400.0
        elif old_start > period_end:
            gap = (old_start - period_end).total_seconds() / 86400.0
        else:
            gap = 0.0
        if gap < REVIEW_WINDOW_BUFFER_DAYS:
            raise ApiError("ERR_REVIEW_WINDOW_OVERLAP")
    row = models.new_data_currency_review(body)
    store.insert("data_currency_reviews", row)
    verify.score_review(row, employer)
    return response.success(serialize.out(row)), 201


@bp.route("/work-number/data-currency-reviews", methods=["GET"])
def list_reviews():
    middleware.require_role(["PlatformAdmin", "Employer"])
    limit, offset = middleware.pagination_args()
    rows = store.all_rows("data_currency_reviews")
    employer_id = http_request.args.get("employer_id")
    if employer_id is not None:
        rows = [r for r in rows if r.get("employer_id") == employer_id]
    page, total = middleware.paginate(rows, limit, offset)
    return response.list_response(serialize.out(page), total, limit, offset)


@bp.route("/work-number/data-currency-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    middleware.require_role(["PlatformAdmin", "Employer", "Verifier"])
    row = _require("data_currency_reviews", review_id)
    return response.success(serialize.out(row))


@bp.route("/work-number/data-currency-reviews/<review_id>/escalate", methods=["POST"])
def escalate_review(review_id):
    middleware.require_role(["PlatformAdmin"])
    row = _require("data_currency_reviews", review_id)
    if row.get("review_state") == "CLEARED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row.get("review_state") != "SCORED":
        raise ApiError("ERR_INVALID_STATE")
    if (row.get("currency_score") or 0) < 300:
        raise ApiError("ERR_INVALID_STATE")
    if clock.now() < row.get("review_period_end"):
        raise ApiError("ERR_INVALID_STATE")
    employer = _require("employers", row.get("employer_id"))
    verify.escalate_review(row, employer)
    return response.success(serialize.out(row))


@bp.route("/work-number/data-currency-reviews/<review_id>/rescore", methods=["POST"])
def rescore_review(review_id):
    middleware.require_role(["PlatformAdmin", "Employer"])
    row = _require("data_currency_reviews", review_id)
    employer = _require("employers", row.get("employer_id"))
    calculations.refresh_employer_feed_status(employer)
    verify.rescore_review(row, employer)
    return response.success(serialize.out(row))