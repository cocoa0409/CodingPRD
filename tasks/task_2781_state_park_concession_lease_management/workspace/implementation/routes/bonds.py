"""The performance bond — PRD 3.5 (posting) and 3.9 (reinstatement)."""
from auth import ALL_ROLES, fetch, guard, require_owner
from envelope import listing, ok
from errors import ApiError
from router import route
from shape import body, req_int, req_str
from store import db, touch

REINSTATABLE = ("PARTIALLY_DRAWN", "INSUFFICIENT")


def _lease_of_bond(bond):
    return db.leases.get(bond["lease_id"])


@route("/performance-bonds/<bond_id>/post", methods=["POST"])
def bonds_post(bond_id):
    guard("Concessionaire")
    bond = fetch(db.bonds, bond_id, "ERR_BOND_NOT_FOUND")
    lease = _lease_of_bond(bond)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    penal_sum = req_int(data, "penal_sum_cents")
    surety_name = req_str(data, "surety_name")
    if bond["status"] != "PENDING":
        raise ApiError("ERR_BOND_STATUS_INVALID",
                       "Bond status %s cannot be posted" % bond["status"])
    if penal_sum < bond["required_amount_cents"]:
        raise ApiError("ERR_BOND_INSUFFICIENT",
                       "The penal sum is below the required bond amount")
    offeror = db.offerors.get(lease["offeror_id"]) if lease is not None else None
    if offeror is not None and penal_sum > offeror["bond_capacity_cents"]:
        raise ApiError("ERR_BOND_EXCEEDS_CAPACITY",
                       "The penal sum exceeds the offeror's attested bond capacity")
    bond["penal_sum_cents"] = penal_sum
    bond["surety_name"] = surety_name
    bond["available_balance_cents"] = penal_sum
    bond["drawn_total_cents"] = 0
    bond["status"] = "ACTIVE"
    touch(bond)
    return ok(bond)


@route("/performance-bonds/<bond_id>/reinstate", methods=["POST"])
def bonds_reinstate(bond_id):
    guard("Concessionaire")
    bond = fetch(db.bonds, bond_id, "ERR_BOND_NOT_FOUND")
    lease = _lease_of_bond(bond)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    amount = req_int(data, "reinstatement_amount_cents")
    if bond["status"] not in REINSTATABLE:
        raise ApiError("ERR_BOND_STATUS_INVALID",
                       "Bond status %s cannot be reinstated" % bond["status"])
    if amount <= 0 or amount > bond["drawn_total_cents"]:
        raise ApiError("ERR_REINSTATEMENT_EXCEEDS_DRAWN",
                       "The reinstatement must be positive and no greater than the drawn total")
    full = amount == bond["drawn_total_cents"]
    bond["available_balance_cents"] = bond["available_balance_cents"] + amount
    bond["drawn_total_cents"] = bond["drawn_total_cents"] - amount
    if full:
        # A full reinstatement returns the bond to ACTIVE from either state; a
        # declared lease default is never reversed by it.
        bond["status"] = "ACTIVE"
    touch(bond)
    return ok(bond)


@route("/performance-bonds", methods=["GET"])
def bonds_list():
    guard(*ALL_ROLES)
    return listing(db.bonds, ("lease_id", "status"))


@route("/performance-bonds/<bond_id>", methods=["GET"])
def bonds_read(bond_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.bonds, bond_id, "ERR_BOND_NOT_FOUND"))
