"""Agency settlement accounts (PRD section 3.1): OCC-guarded create with
optional supersede handoff, treasury verification, agency-scoped listing."""
import re

from flask import Blueprint, request

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import invalid_request, invalid_state, raise_err
from validate import as_enum, as_instant, as_int, as_str, body, opt_field, req_field

bp = Blueprint("accounts", __name__)

_ROUTING_RE = re.compile(r"^\d{9}$")
_LAST4_RE = re.compile(r"^\d{4}$")


@bp.route("/portal/settlement-accounts", methods=["POST"])
def create_account():
    caller({"PlatformAdmin"})
    data = body()
    agency_id = as_str(req_field(data, "agency_id"), "agency_id")
    routing_number = as_str(req_field(data, "routing_number"), "routing_number")
    if not _ROUTING_RE.match(routing_number):
        invalid_request("routing_number must be a 9-digit ACH routing number")
    last4 = as_str(req_field(data, "account_number_last4"), "account_number_last4")
    if not _LAST4_RE.match(last4):
        invalid_request("account_number_last4 must be exactly 4 digits")
    eff_from, eff_raw = as_instant(req_field(data, "effective_from"), "effective_from")
    supersedes = opt_field(data, "supersedes_account_id")
    if supersedes is not None:
        supersedes = as_str(supersedes, "supersedes_account_id")
    expected = as_int(
        req_field(data, "expected_agency_version"), "expected_agency_version"
    )
    # priority 3: body foreign keys in declared input order
    agency = helpers.get_agency(agency_id)
    old = helpers.get_account(supersedes) if supersedes is not None else None
    # priority 4: OCC on the agency aggregate, before all state checks
    if expected != agency["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            412,
            "expected_agency_version does not match the agency's current version",
        )
    if old is not None:
        if old["agency_id"] != agency_id:
            invalid_request("supersedes_account_id does not belong to this agency")
        if old["status"] != "VERIFIED":
            invalid_state("Only a VERIFIED account can be superseded")
        if eff_from <= old["effective_from"]:
            invalid_request(
                "effective_from must be strictly later than the superseded "
                "account's effective_from"
            )
    # priority 8: half-open window [effective_from, effective_to) must not
    # overlap any other live (non-RETIRED) account of the agency
    for acc in store.accounts.values():
        if acc["agency_id"] != agency_id or acc["status"] == "RETIRED":
            continue
        if old is not None and acc["id"] == old["id"]:
            continue
        other_to = acc["effective_to"]
        if other_to is None or eff_from < other_to:
            raise_err(
                "ERR_ACCOUNT_WINDOW_OVERLAP",
                409,
                "New account window overlaps a live account of the agency",
            )
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "agency_id": agency_id,
        "routing_number": routing_number,
        "account_number_last4": last4,
        "effective_from": eff_from,
        "effective_from_raw": eff_raw,
        "effective_to": None,
        "effective_to_raw": None,
        "status": "PENDING_VERIFICATION",
        "verification_attempts": 0,
        "verified_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.accounts[rec["id"]] = rec
    if old is not None:
        # half-open handoff: [old.from, new.from) then [new.from, null)
        old["status"] = "RETIRED"
        old["effective_to"] = eff_from
        old["effective_to_raw"] = eff_raw
        helpers.touch(old)
    # creating an account mutates the agency aggregate
    helpers.touch(agency)
    return envelope.obj(serialize.account(rec), 201)


@bp.route("/portal/agencies/<rid>/settlement-accounts", methods=["GET"])
def list_accounts(rid):
    caller({"PlatformAdmin", "AgencyAdmin", "TreasuryOfficer"})
    helpers.get_agency(rid)
    items = [a for a in store.accounts.values() if a["agency_id"] == rid]
    items.sort(key=lambda a: (a["created_at"], a["created_seq"]))
    return envelope.page([serialize.account(a) for a in items], request.args)


@bp.route("/portal/settlement-accounts/<rid>/verify", methods=["POST"])
def verify_account(rid):
    caller({"TreasuryOfficer"})
    acc = helpers.get_account(rid)
    data = body()
    outcome = as_enum(req_field(data, "outcome"), "outcome", {"SUCCESS", "FAILURE"})
    if acc["status"] != "PENDING_VERIFICATION":
        invalid_state(
            "Account in status %s accepts no further verification calls"
            % acc["status"]
        )
    acc["verification_attempts"] += 1
    if outcome == "SUCCESS":
        acc["status"] = "VERIFIED"
        acc["verified_at"] = clock.now()
    helpers.touch(acc)
    return envelope.obj(serialize.account(acc))
