"""Customers, insurance certificates and rate cards."""

from flask import Blueprint

import calc
import envelope
import serializers
import services
import store
import validate
from auth import ALL_ROLES, authenticate, require_owner
from errors import fail

bp = Blueprint("parties", __name__)

TIERS = ("A", "B", "C")
CERT_STATUSES = ("ACTIVE", "EXPIRED", "REVOKED")
PRODUCTS = ("SHORT_TERM_RENTAL", "FULL_SERVICE_LEASE")
CARD_STATUSES = ("ACTIVE", "SUPERSEDED")


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------
@bp.post("/fleet/customers")
def create_customer():
    authenticate(["FleetAdmin"])
    payload = validate.body()
    legal_name = validate.req_string(payload, "legal_name")
    dot_number = validate.req_string(payload, "dot_number")
    tier = validate.req_enum(payload, "credit_tier", TIERS)
    limit_cents = validate.req_int(payload, "credit_limit_cents", minimum=0)

    rec = store.new_record()
    rec.update({
        "legal_name": legal_name,
        "dot_number": dot_number,
        "credit_tier": tier,
        "credit_limit_cents": limit_cents,
    })
    store.customers[rec["id"]] = rec
    return envelope.created(serializers.customer(rec))


@bp.get("/fleet/customers/<customer_id>")
def read_customer(customer_id):
    authenticate(["FleetAdmin", "BranchManager", "ChargebackApprover", "Customer"])
    return envelope.ok(serializers.customer(services.get_customer(customer_id)))


@bp.get("/fleet/customers/<customer_id>/risk-review")
def risk_review(customer_id):
    authenticate(["FleetAdmin", "ChargebackApprover"])
    customer = services.get_customer(customer_id)
    result = calc.customer_risk_score(customer, "renewal_review")
    return envelope.ok({
        "customer_id": customer_id,
        "variant": "renewal_review",
        "risk_score": result["risk_score"],
        "base_points": result["base_points"],
        "chargeback_weight_points": result["chargeback_weight_points"],
        "assessment_points": result["assessment_points"],
        "weighted_chargeback_cents": result["weighted_chargeback_cents"],
        "outstanding_chargeback_cents": calc.outstanding_chargeback_cents(customer_id),
    })


# ---------------------------------------------------------------------------
# insurance certificates
# ---------------------------------------------------------------------------
@bp.post("/fleet/insurance-certificates")
def create_certificate():
    caller = authenticate(["FleetAdmin", "Customer"])
    payload = validate.body()
    if validate.present(payload, "customer_id") and isinstance(payload["customer_id"], str):
        services.get_customer(payload["customer_id"])

    customer_id = validate.req_string(payload, "customer_id")
    carrier_name = validate.req_string(payload, "carrier_name")
    policy_number = validate.req_string(payload, "policy_number")
    physical_limit = validate.req_int(payload, "physical_damage_limit_cents", minimum=0)
    liability_limit = validate.req_int(payload, "liability_limit_cents", minimum=0)
    effective = validate.req_date(payload, "effective_date")
    expiry = validate.req_date(payload, "expiry_date")

    if expiry < effective:
        fail("ERR_INVALID_DATE_RANGE", "expiry_date must be on or after effective_date")
    if caller.is_customer:
        require_owner(caller, customer_id)

    rec = store.new_record()
    rec.update({
        "customer_id": customer_id,
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "physical_damage_limit_cents": physical_limit,
        "liability_limit_cents": liability_limit,
        "effective_date": effective.isoformat(),
        "expiry_date": expiry.isoformat(),
        "status": "ACTIVE",
        "revoked_reason": None,
    })
    store.certificates[rec["id"]] = rec
    return envelope.created(serializers.certificate(rec))


@bp.get("/fleet/insurance-certificates/<certificate_id>")
def read_certificate(certificate_id):
    authenticate(["FleetAdmin", "BranchManager", "ChargebackApprover", "Customer"])
    return envelope.ok(serializers.certificate(services.get_certificate(certificate_id)))


@bp.get("/fleet/insurance-certificates")
def list_certificates():
    authenticate(["FleetAdmin", "BranchManager", "ChargebackApprover", "Customer"])
    limit, offset = validate.pagination()
    customer_id = validate.query("customer_id")
    status = validate.query_enum("status", CERT_STATUSES)
    rows = []
    for c in store.certificates.values():
        if customer_id is not None and c["customer_id"] != customer_id:
            continue
        if status is not None and serializers.certificate_status(c) != status:
            continue
        rows.append(c)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.certificate(r) for r in page], limit, offset, len(rows))


@bp.post("/fleet/insurance-certificates/<certificate_id>/revoke")
def revoke_certificate(certificate_id):
    authenticate(["FleetAdmin"])
    cert = services.get_certificate(certificate_id)
    payload = validate.body()
    reason = validate.req_string(payload, "reason")

    if serializers.certificate_status(cert) != "ACTIVE":
        fail("ERR_CERTIFICATE_NOT_ACTIVE", "Certificate is not ACTIVE")

    cert["status"] = "REVOKED"
    cert["revoked_reason"] = reason
    store.touch(cert)
    return envelope.ok(serializers.certificate(cert))


# ---------------------------------------------------------------------------
# rate cards
# ---------------------------------------------------------------------------
@bp.post("/fleet/rate-cards")
def create_rate_card():
    authenticate(["FleetAdmin"])
    payload = validate.body()
    branch = None
    if validate.present(payload, "branch_id") and isinstance(payload["branch_id"], str):
        branch = services.get_branch(payload["branch_id"])
    if validate.present(payload, "trailer_type_id") and isinstance(payload["trailer_type_id"], str):
        services.get_trailer_type(payload["trailer_type_id"])

    branch_id = validate.req_string(payload, "branch_id")
    type_id = validate.req_string(payload, "trailer_type_id")
    product = validate.req_enum(payload, "product", PRODUCTS)
    daily = validate.req_int(payload, "daily_rate_cents", minimum=0)
    monthly = validate.req_int(payload, "monthly_rate_cents", minimum=0)
    uplift = validate.req_number(payload, "peak_uplift_pct", 0.00, 2.00)
    mileage_included = validate.req_int(payload, "mileage_included_per_month", minimum=0)
    excess_rate = validate.req_int(payload, "excess_mileage_rate_cents_per_mile", minimum=0)
    effective = validate.req_date(payload, "effective_date")
    expected_version = validate.req_int(payload, "expected_branch_version")

    if expected_version != branch["version"]:
        fail("ERR_STALE_VERSION", "expected_branch_version does not match the branch version")

    prior = services.active_rate_card(branch_id, type_id, product)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        store.touch(prior)

    rec = store.new_record()
    rec.update({
        "branch_id": branch_id,
        "trailer_type_id": type_id,
        "product": product,
        "daily_rate_cents": daily,
        "monthly_rate_cents": monthly,
        "peak_uplift_pct": uplift,
        "mileage_included_per_month": mileage_included,
        "excess_mileage_rate_cents_per_mile": excess_rate,
        "effective_date": effective.isoformat(),
        "status": "ACTIVE",
    })
    store.rate_cards[rec["id"]] = rec
    store.touch(branch)
    return envelope.created(serializers.rate_card(rec))


@bp.get("/fleet/rate-cards/<rate_card_id>")
def read_rate_card(rate_card_id):
    authenticate(["FleetAdmin", "BranchManager", "Customer"])
    return envelope.ok(serializers.rate_card(services.get_rate_card(rate_card_id)))


@bp.get("/fleet/rate-cards")
def list_rate_cards():
    authenticate(["FleetAdmin", "BranchManager", "Customer"])
    limit, offset = validate.pagination()
    branch_id = validate.query("branch_id")
    type_id = validate.query("trailer_type_id")
    product = validate.query_enum("product", PRODUCTS)
    status = validate.query_enum("status", CARD_STATUSES)
    rows = []
    for c in store.rate_cards.values():
        if branch_id is not None and c["branch_id"] != branch_id:
            continue
        if type_id is not None and c["trailer_type_id"] != type_id:
            continue
        if product is not None and c["product"] != product:
            continue
        if status is not None and c["status"] != status:
            continue
        rows.append(c)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.rate_card(r) for r in page], limit, offset, len(rows))
