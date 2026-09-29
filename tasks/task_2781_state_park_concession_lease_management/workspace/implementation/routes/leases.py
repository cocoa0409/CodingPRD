"""Lease execution, insurance, holdover, expiry and close-out — PRD 3.5 / 3.9."""
import calc
from auth import ALL_ROLES, acting_user, fetch, guard
from envelope import listing, ok
from errors import ApiError
from logic import (OPEN_AUDIT_STATES, bond_of, compensable_total, expire_cascade)
from money import parse_date
from router import route
from shape import body, opt_enum, opt_str, ref, req_date, req_str
from store import clock_date, db, touch

MAINTENANCE_SCOPES = ("NONE", "STRUCTURAL_ONLY", "STRUCTURAL_AND_UTILITIES")
INSURANCE_FILING_STATES = ("PENDING_EXECUTION", "ACTIVE", "HOLDOVER")


@route("/leases/<lease_id>/execute", methods=["POST"])
def leases_execute(lease_id):
    guard("ContractingOfficer")
    lease = fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    data = body()
    expires_raw, expires_on = req_date(data, "insurance_expires_on")
    carrier_name = req_str(data, "carrier_name")
    scope = opt_enum(data, "agency_maintenance_scope", MAINTENANCE_SCOPES, "STRUCTURAL_ONLY")
    if lease["contract_status"] != "PENDING_EXECUTION":
        raise ApiError("ERR_LEASE_STATUS_INVALID",
                       "Lease contract_status %s cannot be executed" % lease["contract_status"])
    bond = bond_of(lease)
    if bond is None or bond["status"] != "ACTIVE":
        raise ApiError("ERR_BOND_NOT_ACTIVE", "The performance bond is not ACTIVE")
    if not expires_on > clock_date():
        raise ApiError("ERR_INSURANCE_LAPSED",
                       "The certificate of insurance is not in force beyond today")
    if acting_user() == lease["awarded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The awarding officer may not execute the lease")
    lease["insurance_expires_on"] = expires_raw
    lease["carrier_name"] = carrier_name
    lease["agency_maintenance_scope"] = scope
    lease["executed_by_user_id"] = acting_user()
    lease["contract_status"] = "ACTIVE"
    touch(lease)
    return ok(lease)


@route("/leases/<lease_id>/insurance-certificate", methods=["POST"])
def leases_insurance_certificate(lease_id):
    guard("ContractingOfficer")
    lease = fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    data = body()
    expires_raw, expires_on = req_date(data, "insurance_expires_on")
    carrier_name = opt_str(data, "carrier_name")
    if lease["contract_status"] not in INSURANCE_FILING_STATES:
        raise ApiError("ERR_LEASE_STATUS_INVALID",
                       "Lease contract_status %s cannot file a certificate"
                       % lease["contract_status"])
    # The agency records what the carrier files, lapsed expiry included.
    lease["insurance_expires_on"] = expires_raw
    if carrier_name is not None:
        lease["carrier_name"] = carrier_name
    touch(lease)
    return ok(lease)


@route("/leases/<lease_id>/enter-holdover", methods=["POST"])
def leases_enter_holdover(lease_id):
    guard("ContractingOfficer")
    lease = fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    if lease["contract_status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_STATUS_INVALID",
                       "Lease contract_status %s cannot enter holdover"
                       % lease["contract_status"])
    for other in db.leases.values():
        if other["predecessor_lease_id"] == lease_id and other["contract_status"] == "ACTIVE":
            raise ApiError("ERR_SUCCESSOR_ALREADY_ACTIVE",
                           "A successor lease is already ACTIVE")
    if clock_date() < parse_date(lease["term_end"]):
        raise ApiError("ERR_TERM_NOT_ELAPSED", "The lease term has not elapsed")
    lease["contract_status"] = "HOLDOVER"
    touch(lease)
    return ok(lease)


@route("/leases/<lease_id>/expire", methods=["POST"])
def leases_expire(lease_id):
    guard("ContractingOfficer")
    lease = fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    if lease["contract_status"] not in ("ACTIVE", "HOLDOVER"):
        raise ApiError("ERR_LEASE_STATUS_INVALID",
                       "Lease contract_status %s cannot expire" % lease["contract_status"])
    if not clock_date() > parse_date(lease["term_end"]):
        raise ApiError("ERR_TERM_NOT_ELAPSED", "The lease term has not elapsed")
    expire_cascade(lease)
    lease["contract_status"] = "EXPIRED"
    touch(lease)
    return ok(lease)


@route("/leases/<lease_id>/close-out", methods=["POST"])
def leases_close_out(lease_id):
    guard("ContractingOfficer")
    lease = fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    data = body()
    successor = None
    successor_ref = ref(data, "successor_lease_id")
    if successor_ref is not None:
        if successor_ref == lease_id:
            raise ApiError("ERR_LEASE_NOT_FOUND",
                           "The successor lease must differ from this lease")
        successor = fetch(db.leases, successor_ref, "ERR_LEASE_NOT_FOUND")
    opt_str(data, "successor_lease_id")
    if lease["contract_status"] != "EXPIRED":
        raise ApiError("ERR_LEASE_STATUS_INVALID",
                       "Lease contract_status %s cannot be closed out"
                       % lease["contract_status"])
    for audit in db.audits.values():
        if audit["lease_id"] == lease_id and audit["status"] in OPEN_AUDIT_STATES:
            raise ApiError("ERR_AUDIT_IN_PROGRESS", "An audit engagement is still open")
    gross = compensable_total(lease_id)
    net, deficiency = calc.transfer_settlement(gross, lease["outstanding_fee_balance_cents"])
    lease["transfer_settlement_net_cents"] = net
    lease["transfer_settlement_deficiency_cents"] = deficiency
    if successor is not None:
        successor["predecessor_lease_id"] = lease_id
        touch(successor)
    bond = bond_of(lease)
    if bond is not None and bond["status"] == "ACTIVE" \
            and lease["outstanding_fee_balance_cents"] == 0:
        bond["status"] = "RELEASED"
        touch(bond)
    lease["contract_status"] = "CLOSED_OUT"
    touch(lease)
    return ok(lease)


@route("/leases", methods=["GET"])
def leases_list():
    guard(*ALL_ROLES)
    return listing(db.leases, ("park_id", "prospectus_id", "offeror_id", "selected_proposal_id",
                               "predecessor_lease_id", "performance_bond_id",
                               "contract_status", "compliance_status"))


@route("/leases/<lease_id>", methods=["GET"])
def leases_read(lease_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND"))
