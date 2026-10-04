"""Benefits, redemptions, cloud commitments, and RBAC on adjudication."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_benefit_grant,
    create_cloud_commitment,
    get_success_data,
    make_customer_admin_headers,
    set_clock,
    setup_active_agreement_with_anniversary,
    setup_report_in_state,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
LS = TEST_USERS["licensing_specialist_headers"]


def test_benefit_depletion_zero_remaining_boundary(api):
    """PRD §2.10: "a benefit grant moves itself from `ACTIVE` to `DEPLETED` the moment a redemption takes its `quantity_remaining` to exactly zero".
    PRD §3.7: "A grant's terminal states are `DEPLETED`, `EXPIRED`, and `FORFEITED`; a grant in any terminal state rejects further redemptions with `ERR_INVALID_STATE`."

    Design: Difficulty/boundary_precision_check/benefit_depletion_zero_remaining_boundary
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    grant = create_benefit_grant(agr["id"], benefit_type="TRAINING_VOUCHER",
                                 quantity_granted=2, expires_on="2028-01-01")
    resp = api.redeem_benefit(grant["id"], {"quantity": 2}, make_customer_admin_headers(org["id"]))
    assert resp.status_code == 201, get_success_data(resp)
    g = get_success_data(api.get_benefit_grant(grant["id"], LS))
    assert g["status"] == "DEPLETED"
    assert g["quantity_remaining"] == 0
    resp = api.redeem_benefit(grant["id"], {"quantity": 1}, make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_benefit_redemption_conserves_granted_quantity(api):
    """PRD §3.7: "A successful redemption records the `grant_id`, the `quantity`, and the `redeemed_on` date from the logical clock, and decrements the grant's `quantity_remaining` by the redeemed quantity; a redemption that takes `quantity_remaining` to exactly zero moves the grant `ACTIVE → DEPLETED`."

    Design: Difficulty/compensating_invariant/benefit_redemption_conserves_granted_quantity
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    grant = create_benefit_grant(agr["id"], benefit_type="TRAINING_VOUCHER",
                                 quantity_granted=5, expires_on="2028-01-01")
    for q in (2, 3):
        resp = api.redeem_benefit(grant["id"], {"quantity": q}, make_customer_admin_headers(org["id"]))
        assert resp.status_code == 201, get_success_data(resp)
    g = get_success_data(api.get_benefit_grant(grant["id"], LS))
    # conserved: quantity_granted (5) == quantity_remaining (0) + sum(redemptions) (5)
    assert g["quantity_granted"] == g["quantity_remaining"] + 5
    assert g["quantity_remaining"] == 0
    assert g["status"] == "DEPLETED"


def test_redemption_partial_keeps_grant_active(api):
    """PRD §3.7: "A successful redemption records the `grant_id`, the `quantity`, and the `redeemed_on` date from the logical clock, and decrements the grant's `quantity_remaining` by the redeemed quantity; a redemption that takes `quantity_remaining` to exactly zero moves the grant `ACTIVE → DEPLETED`."

    Design: Difficulty/compensating_invariant/benefit_redemption_conserves_granted_quantity
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    grant = create_benefit_grant(agr["id"], benefit_type="SUPPORT_INCIDENT",
                                 quantity_granted=4, expires_on="2028-01-01")
    resp = api.redeem_benefit(grant["id"], {"quantity": 1}, make_customer_admin_headers(org["id"]))
    red = validate_success(resp, 201)
    assert red["quantity"] == 1
    g = get_success_data(api.get_benefit_grant(grant["id"], LS))
    assert g["quantity_remaining"] == 3
    assert g["status"] == "ACTIVE"


def test_state_before_business_temporal_benefit_redemption(api):
    """PRD §2.9: "Requests are validated in a fixed priority order so that the error a caller receives is deterministic when several rules are violated at once. ... then state-machine legality (`ERR_INVALID_STATE`) ... and finally the business temporal, constraint, referential, and fiscal rules detailed in §3".
    PRD §3.7: "A grant's terminal states are `DEPLETED`, `EXPIRED`, and `FORFEITED`; a grant in any terminal state rejects further redemptions with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_business_temporal_benefit_redemption
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    grant = create_benefit_grant(agr["id"], benefit_type="SUPPORT_INCIDENT",
                                 quantity_granted=2, expires_on="2027-01-01")
    resp = api.redeem_benefit(grant["id"], {"quantity": 2}, make_customer_admin_headers(org["id"]))
    assert resp.status_code == 201, get_success_data(resp)
    assert get_success_data(api.get_benefit_grant(grant["id"], LS))["status"] == "DEPLETED"
    set_clock("2027-06-01T00:00:00Z")
    resp = api.redeem_benefit(grant["id"], {"quantity": 1}, make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_redemption_temporal_expiry_error_when_grant_unswept(api):
    """PRD §3.7: "The grant must also still be within its validity window: if the logical clock date has passed the grant's `expires_on`, the redemption is rejected with `ERR_BENEFIT_EXPIRED` (HTTP 422) — this temporal check stands even for a grant that should have expired but has not yet been swept."

    Design: Corner/validations/redemption_temporal_expiry_error_when_grant_unswept
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    grant = create_benefit_grant(agr["id"], benefit_type="SUPPORT_INCIDENT",
                                 quantity_granted=3, expires_on="2026-12-31")
    set_clock("2027-01-15T00:00:00Z")
    assert get_success_data(api.get_benefit_grant(grant["id"], LS))["status"] == "ACTIVE"
    resp = api.redeem_benefit(grant["id"], {"quantity": 1}, make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_BENEFIT_EXPIRED, 422)


def test_grant_creation_rejected_when_agreement_not_active(api):
    """PRD §3.1: "Nearly every commercial mutation in the system — purchasing entitlements, reporting deployments, registering anniversaries, computing snapshots, opening true-up reports, granting benefits, creating commitments, requesting hosting authorizations, initiating step-ups, adjusting entitlement quantities — is gated on the agreement being `ACTIVE`; attempting any of them against an agreement in another status is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/validations/grant_creation_rejected_when_agreement_not_active
    """
    from test_helpers import create_draft_agreement, create_organization
    org = create_organization(legal_name="NA Org", qualified_device_count=100)
    agr = create_draft_agreement(org["id"], enrollment_number="E-NA-1")
    resp = api.create_benefit_grant(agr["id"], {"benefit_type": "TRAINING_VOUCHER",
                                                "quantity_granted": 2,
                                                "expires_on": "2028-01-01"}, LS)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)


def test_cloud_consumption_partial_cap_and_exhaustion(api):
    """PRD §3.8: "the available balance is the committed amount minus the consumed amount so far, and the event's `consumed_cents` is the smaller of the requested amount and that available balance. Partial consumption is permitted — when a request overshoots the remaining balance, the excess above the cap is silently dropped and only `consumed_cents` is applied; no error is raised for the overshoot itself."
    PRD §2.10: "a cloud commitment moves itself from `ACTIVE` to `EXHAUSTED` the moment a consumption event takes its `consumed_amount_cents` to exactly its `committed_amount_cents`."

    Design: Corner/calculations/cloud_consumption_partial_cap_and_exhaustion
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    com = create_cloud_commitment(agr["id"], committed_amount_cents=100000, expires_on="2028-01-01")
    resp = api.consume_commitment(com["id"], {"requested_cents": 60000},
                                  make_customer_admin_headers(org["id"]))
    ev1 = validate_success(resp, 201)
    assert ev1["consumed_cents"] == 60000
    resp = api.consume_commitment(com["id"], {"requested_cents": 70000},
                                  make_customer_admin_headers(org["id"]))
    ev2 = validate_success(resp, 201)
    assert ev2["consumed_cents"] == 40000, "overshoot capped at the remaining balance"
    com_after = get_success_data(api.get_cloud_commitment(com["id"], LS))
    assert com_after["consumed_amount_cents"] == 100000
    assert com_after["status"] == "EXHAUSTED"


def test_commitment_consumption_after_expiry_marks_expired(api):
    """PRD §3.8: "If the logical clock date has passed the commitment's `expires_on` when a consumption event arrives, the commitment transitions `ACTIVE → EXPIRED` and the event is rejected with `ERR_COMMITMENT_EXPIRED` (HTTP 422)."

    Design: Corner/errors/commitment_consumption_after_expiry_marks_expired
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    com = create_cloud_commitment(agr["id"], committed_amount_cents=100000,
                                  expires_on="2026-12-31")
    set_clock("2027-01-15T00:00:00Z")
    resp = api.consume_commitment(com["id"], {"requested_cents": 1000},
                                  make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXPIRED, 422)
    com_after = get_success_data(api.get_cloud_commitment(com["id"], LS))
    assert com_after["status"] == "EXPIRED", "rejected consumption still transitions the commitment"


def test_customer_admin_cannot_accept_own_true_up_report(api):
    """PRD §3.5: "From `SUBMITTED`, a `LicensingSpecialist` either accepts the report (`SUBMITTED → ACCEPTED`) or rejects it (`SUBMITTED → REJECTED`)."
    PRD §2.1: "If the role is recognized but not permitted for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/customer_admin_cannot_accept_own_true_up_report
    """
    ctx = setup_report_in_state("SUBMITTED", deployment_users=2)
    rep, org = ctx["report"], ctx["org"]
    resp = api.accept_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
