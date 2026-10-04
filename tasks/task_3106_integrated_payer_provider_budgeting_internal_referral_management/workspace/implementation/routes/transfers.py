"""MemberTransfer endpoints (PRD 3.9)."""

from flask import Blueprint

from calculations import capitation_rate_cents
from clock import CLOCK, parse_iso8601
from constants import ROLE_REGIONAL_FINANCE_OFFICER
from db import STORE
from domain import (
    check_member_version,
    get_member,
    get_region,
    get_transfer,
    new_record,
    recompute_member_capitation,
    recompute_region_aggregates,
    recompute_region_providers,
    require_body_reference,
    run_posture_ladder,
    store_row,
    touch,
)
from errors import (
    ERR_INVALID_STATE,
    ERR_REGION_POSTURE_FROZEN,
    ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED,
    ERR_TRANSFER_NOT_COMPLETABLE,
    raise_error,
)
from projections import region_view
from routes._common import (
    TRANSFER_READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
)

bp = Blueprint("transfers", __name__)


def _network_profile(region_id):
    profile = {}
    for service in STORE.network_services.values():
        if service.get("region_id") != region_id:
            continue
        profile[service.get("service_code")] = service.get("availability_status")
    return profile


def _network_difference_for(member, to_region_id):
    origin = member.get("region_id")
    return _network_profile(origin) != _network_profile(to_region_id)


@bp.post("/member-transfers")
def request_transfer():
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    body = payload()
    member_id = require_field(body, "member_id")
    from_region_id = require_field(body, "from_region_id")
    to_region_id = require_field(body, "to_region_id")
    effective_utc = require_field(body, "effective_utc")
    expected = optional_field(body, "expected_member_version")

    member = require_body_reference("members", member_id)
    get_region(from_region_id)
    get_region(to_region_id)
    check_member_version(member, expected)

    origin_region = get_region(from_region_id)
    destination_region = get_region(to_region_id)
    origin_rate = capitation_rate_cents(
        member["plan_product"], member.get("risk_score", 1),
        origin_region.get("capitation_index", 1))
    destination_rate = capitation_rate_cents(
        member["plan_product"], member.get("risk_score", 1),
        destination_region.get("capitation_index", 1))

    row = new_record(
        member_id=member_id,
        from_region_id=from_region_id,
        to_region_id=to_region_id,
        effective_utc=effective_utc,
        benefit_difference_cents=destination_rate - origin_rate,
        network_difference_flag=_network_difference_for(member, to_region_id),
        status="REQUESTED",
    )
    store_row("transfers", row)
    touch(member)
    return single_response("transfers", row, 201)


@bp.get("/member-transfers")
def list_transfers():
    principal(TRANSFER_READERS)
    rows = list(STORE.transfers.values())
    rows = filter_rows(
        rows,
        member_id=arg("member_id"),
        from_region_id=arg("from_region_id"),
        to_region_id=arg("to_region_id"),
        status=arg("status"),
    )
    return list_response("transfers", rows)


@bp.get("/member-transfers/<transfer_id>")
def get_one_transfer(transfer_id):
    principal(TRANSFER_READERS)
    return single_response("transfers", get_transfer(transfer_id))


@bp.post("/member-transfers/<transfer_id>/accept")
def accept_transfer(transfer_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    transfer = get_transfer(transfer_id)
    if transfer.get("status") != "REQUESTED":
        raise_error(ERR_INVALID_STATE)
    destination = get_region(transfer["to_region_id"])
    if region_view(destination)["posture"] == "FROZEN":
        raise_error(ERR_REGION_POSTURE_FROZEN)

    transfer["status"] = "PENDING_EFFECTIVE"
    touch(transfer)

    member = get_member(transfer["member_id"])
    member["status"] = "TRANSFER_PENDING"
    touch(member)
    return single_response("transfers", transfer)


@bp.post("/member-transfers/<transfer_id>/reject")
def reject_transfer(transfer_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    transfer = get_transfer(transfer_id)
    if transfer.get("status") != "REQUESTED":
        raise_error(ERR_INVALID_STATE)
    transfer["status"] = "REJECTED"
    touch(transfer)
    return single_response("transfers", transfer)


@bp.post("/member-transfers/<transfer_id>/complete")
def complete_transfer(transfer_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    transfer = get_transfer(transfer_id)
    if transfer.get("status") != "PENDING_EFFECTIVE":
        raise_error(ERR_TRANSFER_NOT_COMPLETABLE)
    effective = parse_iso8601(transfer["effective_utc"])
    if CLOCK.now() < effective:
        raise_error(ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED)

    transfer["status"] = "COMPLETED"
    touch(transfer)

    member = get_member(transfer["member_id"])
    origin_region_id = member["region_id"]
    destination_region_id = transfer["to_region_id"]

    member["region_id"] = destination_region_id
    recompute_member_capitation(member)
    member["status"] = "ACTIVE"
    touch(member)

    recompute_region_providers(destination_region_id, bump_versions=True)
    recompute_region_aggregates(destination_region_id, bump_version=True)
    recompute_region_aggregates(origin_region_id, bump_version=True)
    run_posture_ladder(destination_region_id)
    run_posture_ladder(origin_region_id)
    return single_response("transfers", transfer)


@bp.post("/member-transfers/<transfer_id>/cancel")
def cancel_transfer(transfer_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    transfer = get_transfer(transfer_id)
    status = transfer.get("status")
    member = get_member(transfer["member_id"])

    if status == "REQUESTED":
        transfer["status"] = "CANCELLED"
        touch(transfer)
        return single_response("transfers", transfer)

    if status == "PENDING_EFFECTIVE":
        effective = parse_iso8601(transfer["effective_utc"])
        if CLOCK.now() >= effective:
            raise_error(ERR_TRANSFER_NOT_COMPLETABLE)
        transfer["status"] = "CANCELLED"
        touch(transfer)
        member["status"] = "ACTIVE"
        touch(member)
        return single_response("transfers", transfer)

    raise_error(ERR_INVALID_STATE)