"""Consent requests for transfers, changes of control and refinancings
(PRD 3.9)."""

from flask import Blueprint

import calc
import domain
import envelope
import store
import validation
from auth import ROLE_BSD, ROLE_FDM, ROLE_OWNER, authenticate
from errors import ApiError
from serialize import dump, dump_all
from store import touch

bp = Blueprint("transfers", __name__)

REQUEST_TYPES = ("TRANSFER", "CHANGE_OF_CONTROL", "REFINANCE")
OWNER_BEARING_TYPES = ("TRANSFER", "CHANGE_OF_CONTROL")
CONSENTABLE_AGREEMENT_STATUSES = ("EXECUTED", "OPEN")


@bp.post("/agreements/<agreement_id>/transfer-requests")
def file_request(agreement_id):
    principal = authenticate((ROLE_OWNER,))
    agreement = store.get_agreement(agreement_id)
    domain.require_agreement_owner(principal, agreement)
    payload = validation.body()
    proposed_owner_id = validation.fk_string(payload, "proposed_owner_id")
    proposed_owner = (
        store.get_owner(proposed_owner_id) if proposed_owner_id is not None else None
    )
    fields = validation.take(
        payload,
        [
            {"name": "request_type", "type": "enum", "required": True,
             "values": REQUEST_TYPES},
            {"name": "proposed_owner_id", "type": "string", "required": False,
             "min_len": 1},
            {"name": "lender_name", "type": "string", "required": False, "min_len": 1,
             "max_len": 160},
        ],
    )
    request_type = fields["request_type"]
    if request_type in OWNER_BEARING_TYPES:
        if not fields["_present_proposed_owner_id"]:
            validation.bad("%s requires proposed_owner_id." % request_type)
        if fields["_present_lender_name"]:
            validation.bad("%s must not carry lender_name." % request_type)
    else:
        if not fields["_present_lender_name"]:
            validation.bad("REFINANCE requires lender_name.")
        if fields["_present_proposed_owner_id"]:
            validation.bad("REFINANCE must not carry proposed_owner_id.")

    if agreement["status"] not in CONSENTABLE_AGREEMENT_STATUSES:
        raise ApiError("ERR_AGREEMENT_NOT_OPEN")
    if agreement["transfer_consent_blocked"]:
        raise ApiError("ERR_TRANSFER_BLOCKED_BY_DEFAULT")
    band = None
    if request_type in OWNER_BEARING_TYPES:
        band = proposed_owner["capacity_band_standalone"]
        if band == "INSUFFICIENT":
            raise ApiError("ERR_PROPOSED_OWNER_CAPACITY_INSUFFICIENT")

    transfer_fee, surcharge, total = calc.consent_fees(
        request_type,
        domain.room_count_of_agreement(agreement),
        agreement["compliance_status"],
    )
    row = store.new_row("transfer_request")
    row["agreement_id"] = agreement["id"]
    row["proposed_owner_id"] = (
        proposed_owner["id"] if proposed_owner is not None else None
    )
    row["request_type"] = request_type
    row["lender_name"] = fields["lender_name"]
    row["transfer_fee"] = transfer_fee
    row["non_compliance_surcharge"] = surcharge
    row["total_consent_fee"] = total
    row["proposed_owner_capacity_band"] = band
    row["status"] = "SUBMITTED"
    row["refusal_reason"] = None
    row["decision_user_id"] = None
    row["decided_at"] = None
    row["decision_notes"] = None
    row["submitted_by_user_id"] = principal.user_id
    store.transfer_requests[row["id"]] = row
    return envelope.created(dump(row))


@bp.get("/transfer-requests/<request_id>")
def read_request(request_id):
    principal = authenticate((ROLE_FDM, ROLE_OWNER))
    request_row = store.get_transfer_request(request_id)
    agreement = store.agreements.get(request_row["agreement_id"])
    domain.require_agreement_owner(principal, agreement)
    return envelope.ok(dump(request_row))


@bp.get("/transfer-requests")
def list_requests():
    authenticate((ROLE_FDM, ROLE_BSD))
    limit, offset = envelope.pagination()
    agreement_id = validation.query_filter("agreement_id")
    proposed_owner_id = validation.query_filter("proposed_owner_id")
    status = validation.query_filter("status")

    def keep(row):
        if agreement_id is not None and row["agreement_id"] != agreement_id:
            return False
        if (
            proposed_owner_id is not None
            and row["proposed_owner_id"] != proposed_owner_id
        ):
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = store.ordered(store.transfer_requests, keep)
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.post("/transfer-requests/<request_id>/decide")
def decide_request(request_id):
    principal = authenticate((ROLE_FDM,))
    request_row = store.get_transfer_request(request_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "outcome", "type": "enum", "required": True,
             "values": ("CONSENT", "REFUSE")},
            {"name": "expected_agreement_version", "type": "integer",
             "required": True},
            {"name": "decision_notes", "type": "string", "required": False,
             "nullable": True},
        ],
    )
    if request_row["status"] != "SUBMITTED":
        raise ApiError("ERR_TRANSFER_REQUEST_NOT_SUBMITTED")
    agreement = store.agreements.get(request_row["agreement_id"])
    if agreement["transfer_consent_blocked"]:
        raise ApiError("ERR_TRANSFER_BLOCKED_BY_DEFAULT")
    if (
        fields["outcome"] == "CONSENT"
        and request_row["request_type"] in OWNER_BEARING_TYPES
        and request_row["proposed_owner_capacity_band"] == "INSUFFICIENT"
    ):
        raise ApiError("ERR_PROPOSED_OWNER_CAPACITY_INSUFFICIENT")
    if fields["expected_agreement_version"] != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")

    stamp = domain.now()
    if fields["outcome"] == "CONSENT":
        request_row["status"] = "CONSENTED"
        agreement["transfer_consent_count"] = agreement["transfer_consent_count"] + 1
    else:
        request_row["status"] = "REFUSED"
        request_row["refusal_reason"] = "DISCRETION"
    request_row["decision_user_id"] = principal.user_id
    request_row["decided_at"] = stamp
    request_row["decision_notes"] = fields["decision_notes"]
    touch(request_row)
    touch(agreement)
    return envelope.ok(dump(request_row))
