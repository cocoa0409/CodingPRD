"""Farm program and premium payment lifecycle (PRD §3.3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_enrollment_payload, create_premium_payment_payload,
    make_enrollment, make_assessed_enrollment, assess_enrollment,
    make_payment, make_final_payment, make_approved_payment,
)

DPM = TEST_USERS["dairy_program_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]
FA = TEST_USERS["franchise_admin_headers"]


def test_payment_create_requires_assessed_enrollment(api):
    """PRD §3.3: "Against an `ASSESSED` enrollment (any other state is rejected with `ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/payment_create_requires_assessed_enrollment
    """
    enrollment = make_enrollment(baseline_volume_liters=5000,
                                 farm_name="Unassessed Acres")
    resp = api.create_premium_payment(
        enrollment["id"],
        create_premium_payment_payload(declared_volume_liters=5000), DPM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_payment_approve_provisional_rejected(api):
    """PRD §3.3: "Approval moves a payment from `CALCULATED` to `APPROVED`, but
    only once its `calc_variant` is `FINAL`; approving a still-`PROVISIONAL`
    payment fails with `ERR_PAYMENT_NOT_FINAL` (HTTP 409)."

    Design: Corner/state_machines/payment_approve_provisional_rejected
    """
    enrollment = make_assessed_enrollment(farm_name="Provisional Farm")
    payment = make_payment(enrollment["id"])
    assert payment["calc_variant"] == "PROVISIONAL"
    resp = api.approve_payment(payment["id"], DPM)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_FINAL)


def test_payment_pay_before_approve_rejected(api):
    """PRD §3.3: "a `ParentOpsController` pays an `APPROVED` payment, moving it
    to the terminal `PAID`."
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/payment_pay_before_approve_rejected
    """
    enrollment = make_assessed_enrollment(farm_name="Skip Farm")
    payment = make_final_payment(enrollment["id"], metered_volume_liters=10000)
    assert payment["status"] == "CALCULATED"
    resp = api.pay_payment(payment["id"], POC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_payment_double_finalize_rejected(api):
    """PRD §3.3: "Finalize is defined only for a `PROVISIONAL` payment."
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/payment_double_finalize_rejected
    """
    enrollment = make_assessed_enrollment(farm_name="Twice Farm")
    payment = make_final_payment(enrollment["id"], metered_volume_liters=10000)
    assert payment["calc_variant"] == "FINAL"
    resp = api.finalize_payment(
        payment["id"],
        {"metered_volume_liters": 9000, "non_conformance_count": 0}, DPM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_enrollment_payments_reverse_reach_list(api):
    """PRD §4: "GET | `/creamery/enrollments/{id}/premium-payments` | List an
    enrollment's premium payments". Children are reachable from the parent.

    Design: Corner/endpoints/enrollment_payments_reverse_reach_list
    """
    enrollment = make_assessed_enrollment(farm_name="List Farm",
                                          baseline_volume_liters=5000)
    payment = make_payment(enrollment["id"], declared_volume_liters=5000,
                           commodity_price_cents_per_liter=40)
    data, meta = validate_paginated(api.list_premium_payments(enrollment["id"], DPM))
    assert meta["total_count"] == 1
    assert data[0]["id"] == payment["id"]


def test_enrollment_reassessment_updates_blended(api):
    """PRD §3.3: "re-assessment from `ASSESSED` is allowed, re-sets both
    practice scores and the blended score, and deliberately does not recompute
    payments that already exist."

    Design: Corner/calculations/enrollment_reassessment_updates_blended
    """
    enrollment = make_assessed_enrollment(env_score=60, welfare_score=60,
                                          baseline_volume_liters=5000,
                                          farm_name="Reassess Ranch")
    payment = make_payment(enrollment["id"], declared_volume_liters=5000,
                           commodity_price_cents_per_liter=40)
    assert payment["gross_amount_cents"] == 10000  # 5000*40*0.05 at blended 60

    reassessed = assess_enrollment(enrollment["id"], 90, 90)
    assert reassessed["blended_score"] == 90
    after = get_success_data(api.get_premium_payment(payment["id"], DPM))
    assert after["gross_amount_cents"] == 10000, "existing payments are not recomputed"


def test_payment_void_restores_enrollment_total(api):
    """PRD §3.3: "Approval adds the payment's `gross_amount_cents` to the enrollment's `total_approved_cents` — the running sum of gross amounts over payments in `APPROVED` or `PAID`" and "voiding an `APPROVED` one subtracts its `gross_amount_cents` back out of `total_approved_cents` as a compensating reversal."

    Design: Corner/consistency_model/payment_void_restores_enrollment_total
    """
    enrollment = make_assessed_enrollment(env_score=80, welfare_score=70,
                                          baseline_volume_liters=5000,
                                          farm_name="Void Farm")
    payment = make_final_payment(enrollment["id"], declared_volume_liters=5000,
                                 commodity_price_cents_per_liter=40,
                                 metered_volume_liters=5000)
    assert payment["gross_amount_cents"] == 16000  # 5000*40*0.08, blended 75 -> tier 8

    validate_success(api.approve_payment(payment["id"], DPM))
    mid = get_success_data(api.get_enrollment(enrollment["id"], DPM))
    assert mid["total_approved_cents"] == 16000

    validate_success(api.void_payment(payment["id"], DPM))
    end = get_success_data(api.get_enrollment(enrollment["id"], DPM))
    assert end["total_approved_cents"] == 0, "compensation must be exact"


def test_franchise_admin_cannot_pay_premium(api):
    """PRD §2.9: "Neither role can perform the other's exclusive operations, and
    a role not listed for an operation is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.3: "Disbursement is parent-company business: a `ParentOpsController`
    pays an `APPROVED` payment".

    Design: Corner/rbac/franchise_admin_cannot_pay_premium
    """
    enrollment = make_assessed_enrollment(farm_name="RBAC Farm",
                                          baseline_volume_liters=5000)
    payment = make_approved_payment(enrollment["id"], declared_volume_liters=5000,
                                    commodity_price_cents_per_liter=40,
                                    metered_volume_liters=5000)
    assert payment["status"] == "APPROVED"
    resp = api.pay_payment(payment["id"], FA)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
