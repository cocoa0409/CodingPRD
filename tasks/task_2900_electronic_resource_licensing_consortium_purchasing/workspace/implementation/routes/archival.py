"""Section 3.9 - archival deposit checks, attestation and coverage verification."""

from flask import Blueprint, request

import auth
import calc
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("archival", __name__)


@bp.post("/erm/subscriptions/<subscription_id>/archival-checks")
def create_check(subscription_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    subscription = auth.get_subscription(subscription_id)
    data = shape.body()
    agency_code = shape.req_enum(data, "agency_code", shape.ARCHIVAL_AGENCIES)
    deposited_title_count = shape.req_int(data, "deposited_title_count", minimum=0)
    expected = shape.req_int(data, "expected_subscription_version", minimum=0)

    # priority 7 - optimistic concurrency on the subscription aggregate
    if expected != subscription["version"]:
        raise ApiError("ERR_STALE_SUBSCRIPTION_VERSION")

    # priority 15 - the claimed agency must be the one the publisher deposits with
    product = store.products[subscription["product_id"]]
    vendor = store.vendors[product["vendor_id"]]
    if vendor["archival_agency_code"] is None or vendor["archival_agency_code"] != agency_code:
        raise ApiError("ERR_ARCHIVAL_AGENCY_MISMATCH")

    row = store.new_row({
        "subscription_id": subscription["id"],
        "agency_code": agency_code,
        "deposited_title_count": deposited_title_count,
        "attested_title_count": None,
        "coverage_pct": None,
        "status": "PENDING",
    })
    store.archival_checks[row["id"]] = row
    store.touch(subscription)
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/subscriptions/<subscription_id>/archival-checks")
def list_checks(subscription_id):
    auth.require_roles(
        auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_VENDOR_REP
    )
    subscription = auth.get_subscription(subscription_id)
    rows = [
        c for c in store.archival_checks.values()
        if c["subscription_id"] == subscription["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return envelope.paged(rows)


@bp.post("/erm/archival-checks/<archival_check_id>/attest")
def attest_check(archival_check_id):
    auth.require_roles(auth.ROLE_VENDOR_REP)
    check = auth.get_archival_check(archival_check_id)
    subscription = store.subscriptions[check["subscription_id"]]
    product = store.products[subscription["product_id"]]
    auth.require_vendor_scope(product)

    data = shape.body()
    attested_title_count = shape.req_int(data, "attested_title_count", minimum=0)

    if check["status"] not in ("PENDING", "FAILED"):
        raise ApiError("ERR_ARCHIVAL_CHECK_INVALID_STATE")

    changes = {"attested_title_count": attested_title_count, "status": "ATTESTED"}
    # a re-attestation never leaves a stale coverage figure behind
    changes["coverage_pct"] = None
    store.mutate(check, changes)
    return envelope.object_response(store.serialize(check))


@bp.post("/erm/archival-checks/<archival_check_id>/verify")
def verify_check(archival_check_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    check = auth.get_archival_check(archival_check_id)
    if check["status"] != "ATTESTED":
        raise ApiError("ERR_ARCHIVAL_CHECK_INVALID_STATE")

    # priority 29 - the two title counts must agree within tolerance
    if abs(check["attested_title_count"] - check["deposited_title_count"]) \
            > calc.ARCHIVAL_DISCREPANCY_TOLERANCE:
        raise ApiError("ERR_ARCHIVAL_COUNT_DISCREPANCY")

    subscription = store.subscriptions[check["subscription_id"]]
    coverage = calc.archival_coverage_pct(
        check["attested_title_count"], subscription["entitled_title_count"]
    )
    status = "VERIFIED" if coverage >= calc.ARCHIVAL_COVERAGE_THRESHOLD_PCT else "FAILED"
    store.mutate(check, {"coverage_pct": float(coverage), "status": status})
    return envelope.object_response(store.serialize(check))
