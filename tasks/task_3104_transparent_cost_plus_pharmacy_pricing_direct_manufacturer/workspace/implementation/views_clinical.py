"""Route handlers: prescriptions, intake requests and refill authorisations."""

from clock import now, now_iso
from cascades import recompute_drug_quiet
from errors import fail, success_payload
from lifecycle import derive as derive_comparison
from pricing import demand_units_30d
from registry import (
    claims_of_prescription,
    find,
    get,
    of_parent,
    ordered_by_created,
    ordered_by_seq,
    requests_of_prescription,
)
from resources import blank_record, internal_of, touch
from store import store


def _object(record):
    return success_payload(record, "object")


def _array(ctx, records):
    return success_payload(records, "array", ctx.pagination(len(records)))


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------

def create_prescription(ctx):
    record = blank_record()
    record["patient_id"] = ctx.text("patient_id")
    record["prescriber_id"] = ctx.text("prescriber_id")
    record["drug_id"] = ctx.text("drug_id")
    record["ship_state_code"] = ctx.text("ship_state_code")
    refills = ctx.integer("total_refills_authorized")
    if refills < 0:
        fail("ERR_INVALID_AMOUNT", "total_refills_authorized must be at least 0.")
    record["total_refills_authorized"] = refills
    record["refills_consumed"] = 0
    record["status"] = "DRAFT"
    record["rejection_reason_code"] = None
    find("patients", record["patient_id"])
    find("prescribers", record["prescriber_id"])
    find("drugs", record["drug_id"])
    store.prescriptions[record["id"]] = internal_of("prescriptions", record)
    return _object(record), 201


def get_prescription(ctx, prescription_id):
    prescription = find("prescriptions", prescription_id)
    ctx.guard_ownership(prescription.get("patient_id"))
    return _object(prescription), 200


def list_prescriptions(ctx):
    records = list(store.prescriptions.values())
    for field in ("patient_id", "prescriber_id", "drug_id", "status"):
        value = ctx.query(field)
        if value:
            records = [rec for rec in records if rec.get(field) == value]
    return _array(ctx, ordered_by_created(records)), 200


def route_intake(ctx, prescription_id):
    prescription = find("prescriptions", prescription_id)
    if prescription.get("status") != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT prescription may be routed into intake.")
    prescriber = get("prescribers", prescription.get("prescriber_id"))
    drug = get("drugs", prescription.get("drug_id"))
    if prescriber is None or drug is None:
        fail("ERR_PRESCRIBER_ORDER_REQUIRED")
    if prescriber.get("status") != "ACTIVE":
        fail("ERR_PRESCRIBER_ORDER_REQUIRED", "The prescriber is not ACTIVE.")
    if drug.get("is_controlled") is True:
        fail("ERR_CONTROLLED_SUBSTANCE_EXCLUDED")
    packaged_quantity = ctx.integer("packaged_quantity")
    if packaged_quantity < 1:
        fail("ERR_INVALID_AMOUNT", "packaged_quantity must be at least 1.")

    prescription["status"] = "INTAKE_REVIEW"
    touch(prescription)

    request = blank_record()
    request["prescription_id"] = prescription_id
    request["packaged_quantity"] = packaged_quantity
    request["consumed_quantity"] = 0
    request["status"] = "SUBMITTED"
    request["submitted_at"] = now_iso()
    store.requests[request["id"]] = internal_of("requests", request)

    # PRD §3.4: "Requesting intake is also one of the events that recomputes
    # the drug's trailing demand"; the new request counts as inside the window
    # even though it is transitioned to INTAKE_REVIEW by the same operation.
    recompute_drug_quiet(
        drug.get("id"), now(), transitioning_request=request, transition_to="SUBMITTED"
    )
    return _object(request), 201


def terminate_prescription(ctx, prescription_id):
    prescription = find("prescriptions", prescription_id)
    if prescription.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE prescription may be terminated.")
    for claim in claims_of_prescription(prescription_id):
        if claim.get("status") in ("PENDING", "AUTHORIZED", "SHIPPED"):
            fail("ERR_INVALID_STATE", "An outstanding claim blocks termination.")
    prescription["status"] = "TERMINATED"
    touch(prescription)
    return _object(prescription), 200


def substitute_prescription(ctx, prescription_id):
    prescription = find("prescriptions", prescription_id)
    reason_code = ctx.key("reason_code")
    if reason_code is None or (isinstance(reason_code, str) and not reason_code.strip()):
        fail("ERR_SUBSTITUTION_REASON_REQUIRED")
    new_drug_id = ctx.text("new_drug_id")
    new_drug = find("drugs", new_drug_id)

    prescription["drug_id"] = new_drug_id
    for order in of_parent("orders", "prescription_id", prescription_id):
        if order.get("status") not in ("CREATED", "PAID", "FULFILLING", "SHIPPED"):
            continue
        order["retail_reference_price_cents"] = new_drug.get("retail_reference_price_cents")
        order["insured_reference_price_cents"] = new_drug.get("insured_reference_price_cents")
        comparison = _comparison_of(order)
        if comparison is not None:
            comparison["state"] = "REFRESH_REQUIRED"
            comparison["substantiated"] = False
            comparison["substantiation_digest"] = None
            comparison["status"] = "UNSUBSTANTIATED"
            comparison["ever_substantiated"] = False
            touch(comparison)
        touch(order)


    recompute_drug_quiet(new_drug_id, now())
    touch(prescription)
    return _object(prescription), 200


def _comparison_of(order):
    for comparison in store.comparisons.values():
        if comparison.get("order_id") == order.get("id"):
            return comparison
    return None


def list_prescription_requests(ctx, prescription_id):
    find("prescriptions", prescription_id)
    return _array(ctx, ordered_by_created(requests_of_prescription(prescription_id))), 200


def list_prescription_claims(ctx, prescription_id):
    find("prescriptions", prescription_id)
    return _array(ctx, ordered_by_seq(claims_of_prescription(prescription_id), "claim_seq")), 200


def list_prescription_orders(ctx, prescription_id):
    prescription = find("prescriptions", prescription_id)
    ctx.guard_ownership(prescription.get("patient_id"))
    return _array(ctx, ordered_by_created(of_parent("orders", "prescription_id", prescription_id))), 200


# ---------------------------------------------------------------------------
# Prescription requests
# ---------------------------------------------------------------------------

def get_request(ctx, request_id):
    return _object(find("requests", request_id)), 200


def list_requests(ctx):
    records = list(store.requests.values())
    prescription_id = ctx.query("prescription_id")
    if prescription_id:
        records = [rec for rec in records if rec.get("prescription_id") == prescription_id]
    return _array(ctx, ordered_by_created(records)), 200


def review_request(ctx, request_id):
    request = find("requests", request_id)
    if request.get("status") != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED request may be taken up for review.")
    request["status"] = "UNDER_REVIEW"
    touch(request)
    _refresh_request_drug(request)
    return _object(request), 200


def accept_request(ctx, request_id):
    request = find("requests", request_id)
    if request.get("status") != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW request may be accepted.")
    prescription = get("prescriptions", request.get("prescription_id"))
    if prescription is None or prescription.get("status") != "INTAKE_REVIEW":
        fail("ERR_INVALID_STATE", "The prescription is not at INTAKE_REVIEW.")
    drug = get("drugs", prescription.get("drug_id"))
    prescriber = get("prescribers", prescription.get("prescriber_id"))
    if prescriber is None or drug is None:
        fail("ERR_PRESCRIBER_ORDER_REQUIRED")
    if prescriber.get("status") != "ACTIVE":
        fail("ERR_PRESCRIBER_ORDER_REQUIRED", "The prescriber is not ACTIVE.")
    if drug.get("is_controlled") is True:
        fail("ERR_CONTROLLED_SUBSTANCE_EXCLUDED")

    consumed = sum(
        int(rec.get("consumed_quantity") or 0) for rec in requests_of_prescription(prescription.get("id"))
    )
    packaged = _prescription_packaged_quantity(prescription.get("id"))
    if consumed >= packaged:
        fail("ERR_INVALID_STATE", "No fill capacity remains on this prescription.")

    request["status"] = "ACCEPTED"
    touch(request)
    prescription["status"] = "ACTIVE"
    touch(prescription)

    if not claims_of_prescription(prescription.get("id")):
        claim = blank_record()
        claim["prescription_id"] = prescription.get("id")
        claim["claim_seq"] = 1
        claim["status"] = "PENDING"
        claim["reserved_quantity"] = 0
        claim["denied_at"] = None
        claim["denial_reason_code"] = None
        claim["order_id"] = None
        store.claims[claim["id"]] = internal_of("claims", claim)

    recompute_drug_quiet(drug.get("id"), now())
    return _object(request), 200


def reject_request(ctx, request_id):
    request = find("requests", request_id)
    if request.get("status") != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW request may be rejected.")
    prescription = get("prescriptions", request.get("prescription_id"))
    if prescription is None or prescription.get("status") != "INTAKE_REVIEW":
        fail("ERR_INVALID_STATE", "The prescription is not at INTAKE_REVIEW.")

    reason_code = ctx.key("reason_code")
    if reason_code is None or (isinstance(reason_code, str) and not reason_code.strip()):
        fail("ERR_INVALID_AMOUNT", "The reason_code field is required.")

    request["status"] = "REJECTED"
    consumed = int(request.get("consumed_quantity") or 0)
    request["consumed_quantity"] = 0
    touch(request)
    prescription["status"] = "REJECTED"
    prescription["rejection_reason_code"] = str(reason_code)
    touch(prescription)

    drug = get("drugs", prescription.get("drug_id"))
    if drug is not None:
        drug["reserved_total"] = max(0, int(drug.get("reserved_total") or 0) - consumed)
        recompute_drug_quiet(drug.get("id"), now())
        touch(drug)
    return _object(request), 200


def _refresh_request_drug(request):
    """Recompute the drug's demand after an intake request's status moves."""
    prescription = get("prescriptions", request.get("prescription_id"))
    if prescription is None:
        return
    drug = get("drugs", prescription.get("drug_id"))
    if drug is None:
        return
    recompute_drug_quiet(drug.get("id"), now())
    touch(drug)


def _prescription_packaged_quantity(prescription_id):
    """The prescription's packaged quantity, read from its intake requests."""
    requests = requests_of_prescription(prescription_id)
    if not requests:
        return 0
    ordered = ordered_by_created(requests)
    return int(ordered[0].get("packaged_quantity") or 0)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def get_claim(ctx, claim_id):
    claim = find("claims", claim_id)
    prescription = get("prescriptions", claim.get("prescription_id"))
    ctx.guard_ownership((prescription or {}).get("patient_id"))
    return _object(claim), 200


def list_claims(ctx):
    records = list(store.claims.values())
    prescription_id = ctx.query("prescription_id")
    if prescription_id:
        records = [rec for rec in records if rec.get("prescription_id") == prescription_id]
    return _array(ctx, ordered_by_created(records)), 200


def authorize_refill(ctx, claim_id):
    claim = find("claims", claim_id)
    if claim.get("status") != "PENDING":
        fail("ERR_INVALID_STATE", "Only a PENDING claim may be authorised.")
    quantity = ctx.integer("quantity")

    prescription = get("prescriptions", claim.get("prescription_id"))
    drug = get("drugs", prescription.get("drug_id")) if prescription else None

    # Denial paths, evaluated before the numeric lower bound (PRD §2.12: the
    # refill-authorisation refusal set precedes lower-bound numeric validation).
    if prescription is not None and int(prescription.get("refills_consumed") or 0) >= int(
        prescription.get("total_refills_authorized") or 0
    ):
        claim["status"] = "DENIED"
        claim["denied_at"] = now_iso()
        claim["denial_reason_code"] = "REFILLS_EXHAUSTED"
        claim["reserved_quantity"] = 0
        touch(claim)
        if drug is not None:

            recompute_drug_quiet(drug.get("id"), now())
            touch(drug)
        return _object(claim), 200

    # PRD §3.4 enumerates these three as refusals reported with their own error
    # identifiers and HTTP 422 — unlike the exhausted-budget refusal, which has
    # no error identifier and is instead reported as a denial on the claim.
    if drug is not None and drug.get("state") == "DELISTED":
        fail("ERR_DRUG_DELISTED")
    if drug is not None and drug.get("sourcing_status") != "SOURCED":
        demand = int(drug.get("demand_units_30d") or 0)
        supply = int(drug.get("supply_units") or 0)
        if demand > supply:
            drug["expansion_score"] = None
        recompute_drug_quiet(drug.get("id"), now())
        touch(drug)
        fail("ERR_SOURCING_UNAVAILABLE")
    if drug is not None and int(drug.get("supply_units") or 0) < quantity:
        recompute_drug_quiet(drug.get("id"), now())
        touch(drug)
        fail("ERR_SUPPLY_SHORTFALL")
    if quantity < 1:
        fail("ERR_INVALID_AMOUNT", "quantity must be at least 1.")
    if prescription is None or prescription.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "The prescription is not ACTIVE.")

    claim["status"] = "AUTHORIZED"
    claim["reserved_quantity"] = quantity
    touch(claim)
    if drug is not None:
        recompute_drug_quiet(drug.get("id"), now())
        touch(drug)
    return _object(claim), 200


def get_claim_summary(ctx, claim_id):
    claim = find("claims", claim_id)
    prescription = get("prescriptions", claim.get("prescription_id"))
    ctx.guard_ownership((prescription or {}).get("patient_id"))
    return _object(
        {
            "claim_id": claim.get("id"),
            "claim_seq": claim.get("claim_seq"),
            "status": claim.get("status"),
            "reserved_quantity": claim.get("reserved_quantity") or 0,
            "denial_reason_code": claim.get("denial_reason_code"),
            "denied_at": claim.get("denied_at"),
        }
    ), 200