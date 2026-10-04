"""TransferRequest routes: propose, list, get, relinquish, decide."""
from flask import Blueprint, request

from constants import (
    NON_TERMINAL_TRANSFER_STATUSES,
    ROLE_APPLICANT,
    ROLE_GRANTS_OFFICER,
    TERM_STANDARD,
    TERM_TRANSFERRED_AWARD,
    TRANSFER_DECISIONS,
)
from db import STORE, clock_now, new_entity, touch
from errors import fail
from serializers import transfer_json
from services import dec, get, rhu
from util import (
    auth_context,
    get_body,
    ok_list,
    ok_object,
    opt_str,
    parse_pagination,
    req_dt,
    req_enum,
    req_str,
    require_owner,
    require_role,
    sort_and_page,
)

bp = Blueprint("transfers", __name__)


def _get_transfer_or_404(transfer_id):
    transfer = get("transfer_requests", transfer_id)
    if transfer is None:
        fail("ERR_TRANSFER_REQUEST_NOT_FOUND", "transfer request not found")
    return transfer


@bp.route("/grants/awards/<award_id>/transfer-requests", methods=["POST"])
def create_transfer(award_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_APPLICANT,))
    award = get("awards", award_id)
    if award is None:
        fail("ERR_AWARD_NOT_FOUND", "award not found")
    body = get_body()
    to_institution_id = req_str(body, "to_institution_id")
    effective_date = req_dt(body, "effective_date")
    if effective_date < clock_now():
        fail("ERR_VALIDATION", "effective_date must not be earlier than the logical clock")
    to_institution = get("institutions", to_institution_id)
    if to_institution is None:
        fail("ERR_INSTITUTION_NOT_FOUND", "receiving institution not found")
    app = get("applications", award["application_id"])
    require_owner(app["applicant_id"] if app else None, user_id)
    if award["status"] != "ACTIVE":
        fail("ERR_AWARD_NOT_ACTIVE", "transfers require an ACTIVE award")
    for other in STORE["transfer_requests"].values():
        if (
            other["award_id"] == award["id"]
            and other["status"] in NON_TERMINAL_TRANSFER_STATUSES
        ):
            fail(
                "ERR_TRANSFER_ALREADY_PENDING",
                "a non-terminal transfer request already exists for this award",
            )
    # certification re-check against the application's flags at effective_date
    if app is not None:
        if app["human_subjects_involved"]:
            expiry = to_institution["human_subjects_certification_expiry"]
            if expiry is None:
                fail(
                    "ERR_CERTIFICATION_MISSING",
                    "receiving institution lacks human-subjects certification",
                )
            if expiry < effective_date:
                fail(
                    "ERR_CERTIFICATION_EXPIRED",
                    "human-subjects certification expires before the effective_date",
                )
        if app["vertebrate_animals_involved"]:
            expiry = to_institution["animal_welfare_assurance_expiry"]
            if expiry is None:
                fail(
                    "ERR_CERTIFICATION_MISSING",
                    "receiving institution lacks animal-welfare assurance",
                )
            if expiry < effective_date:
                fail(
                    "ERR_CERTIFICATION_EXPIRED",
                    "animal-welfare assurance expires before the effective_date",
                )
    transfer = new_entity()
    transfer.update(
        {
            "award_id": award["id"],
            "to_institution_id": to_institution_id,
            "effective_date": effective_date,
            "proration_variant": None,
            "relinquished_amount_cents": None,
            "status": "PROPOSED",
        }
    )
    STORE["transfer_requests"][transfer["id"]] = transfer
    return ok_object(transfer_json(transfer), 201)


@bp.route("/grants/transfer-requests", methods=["GET"])
def list_transfers():
    auth_context()
    limit, offset = parse_pagination(request.args)
    items = list(STORE["transfer_requests"].values())
    for field in ("award_id", "to_institution_id", "status"):
        if request.args.get(field) is not None:
            items = [t for t in items if t.get(field) == request.args[field]]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([transfer_json(t) for t in page], total, limit, offset)


@bp.route("/grants/transfer-requests/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    auth_context()
    return ok_object(transfer_json(_get_transfer_or_404(transfer_id)))


@bp.route("/grants/transfer-requests/<transfer_id>/relinquish", methods=["POST"])
def relinquish_transfer(transfer_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_GRANTS_OFFICER,))
    transfer = _get_transfer_or_404(transfer_id)
    if transfer["status"] != "PROPOSED":
        fail("ERR_TRANSFER_INVALID_STATE", "relinquish requires PROPOSED status")
    award = get("awards", transfer["award_id"])
    if award["disbursed_cents"] > 0:
        variant = "LEDGER_ACTUALS"
        relinquished = award["total_awarded_cents"] - award["disbursed_cents"]
    else:
        variant = "TIME_PRORATED"
        total_days = (award["end_date"] - award["start_date"]).days
        days_remaining = max((award["end_date"] - transfer["effective_date"]).days, 0)
        if total_days <= 0:
            relinquished = 0
        else:
            relinquished = int(
                rhu(
                    dec(award["total_awarded_cents"]) * days_remaining / total_days,
                    0,
                )
            )
    transfer["proration_variant"] = variant
    transfer["relinquished_amount_cents"] = relinquished
    transfer["status"] = "RELINQUISHED"
    touch(transfer)
    return ok_object(transfer_json(transfer))


@bp.route("/grants/transfer-requests/<transfer_id>/decide", methods=["POST"])
def decide_transfer(transfer_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_GRANTS_OFFICER,))
    transfer = _get_transfer_or_404(transfer_id)
    body = get_body()
    decision = req_enum(body, "decision", TRANSFER_DECISIONS)
    opt_str(body, "decline_reason")
    if transfer["status"] != "RELINQUISHED":
        fail("ERR_TRANSFER_INVALID_STATE", "decide requires RELINQUISHED status")
    if decision == "DECLINE":
        transfer["status"] = "DECLINED"
        touch(transfer)
        return ok_object(transfer_json(transfer))
    # ACCEPT: three-level cascade
    award = get("awards", transfer["award_id"])
    institute = get("institutes", award["institute_id"])
    relinquished = transfer["relinquished_amount_cents"]
    retained = award["total_awarded_cents"] - award["disbursed_cents"] - relinquished
    institute["committed_cents"] -= relinquished + retained
    award["status"] = "TRANSFERRED"
    touch(award)
    successor = new_entity()
    successor.update(
        {
            "application_id": award["application_id"],
            "institute_id": award["institute_id"],
            "institution_id": transfer["to_institution_id"],
            "start_date": transfer["effective_date"],
            "end_date": award["end_date"],
            "period_total_cents": [relinquished],
            "total_awarded_cents": relinquished,
            "disbursed_cents": 0,
            "disbursed_per_period_cents": [0],
            "carried_out_per_period_cents": [0],
            "current_period": 1,
            "terms_and_conditions": [TERM_STANDARD, TERM_TRANSFERRED_AWARD],
            "originating_transfer_id": transfer["id"],
            "status": "ACTIVE",
        }
    )
    STORE["awards"][successor["id"]] = successor
    institute["committed_cents"] += relinquished
    touch(institute)
    transfer["status"] = "ACCEPTED"
    touch(transfer)
    return ok_object(transfer_json(transfer))
