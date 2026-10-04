"""Agreement lifecycle: initial state, activation window, renewal, expiry, OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    create_active_agreement,
    create_agreement_payload,
    create_benefit_grant,
    create_draft_agreement,
    create_organization,
    get_success_data,
    make_customer_admin_headers,
    register_anniversary,
    set_clock,
    setup_agreement_in_renewal_pending,
    setup_expired_agreement,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
LS = TEST_USERS["licensing_specialist_headers"]


def test_agreement_initial_state_is_draft(api):
    """PRD §3.1: "A new agreement is born in `DRAFT` status with `renewal_count` at 0."

    Design: Corner/state_machines/agreement_initial_state_is_draft
    """
    org = create_organization(legal_name="Init Org", qualified_device_count=100)
    agr = create_draft_agreement(org["id"], enrollment_number="E-INI-1")
    assert agr["status"] == "DRAFT"
    assert agr["renewal_count"] == 0


def test_agreement_terminal_states_lockdown(api):
    """PRD §3.6: "`RENEWED`, `EXPIRED`, and `NON_RENEWED` are the agreement's terminal states."
    PRD §3.5: "Any transition attempted from the wrong status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/agreement_terminal_states_lockdown
    """
    ctx = setup_expired_agreement()
    agr = ctx["agreement"]
    assert agr["status"] == "EXPIRED"
    resp1 = api.open_renewal_review(agr["id"], LS)
    validate_error(resp1, ApiErrorId.ERR_INVALID_STATE, 409)
    resp2 = api.activate_agreement(agr["id"], PA)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE, 409)


def test_decline_renewal_continue_returns_to_active(api):
    """PRD §3.6: "The customer may decide to simply continue the current term: a `CustomerAdmin` declines renewal with `decision` set to `CONTINUE`, returning the agreement `RENEWAL_PENDING → ACTIVE` with no other effect beyond the version increment."

    Design: Corner/state_machines/decline_renewal_continue_returns_to_active
    """
    ctx = setup_agreement_in_renewal_pending(
        grants=[{"benefit_type": "TRAINING_VOUCHER",
                 "quantity_granted": 3, "expires_on": "2029-12-31"}])
    org, agr = ctx["org"], ctx["agreement"]
    assert agr["status"] == "RENEWAL_PENDING"
    grant = ctx["grants"][0]
    resp = api.decline_renewal(agr["id"], {"decision": "CONTINUE"}, ctx["customer_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
    grant_after = get_success_data(api.get_benefit_grant(grant["id"], LS))
    assert grant_after["status"] == "ACTIVE", "CONTINUE must not forfeit grants"


def test_renew_closes_all_anniversaries_and_bumps_renewal_count(api):
    """PRD §3.6: "A successful renewal increments `renewal_count` by 1, moves `end_date` to `new_end_date`, marks every anniversary of the agreement `true_up_closed`, and increments the agreement's `version`."

    Design: Corner/state_machines/renew_closes_all_anniversaries_and_bumps_renewal_count
    """
    ctx = setup_agreement_in_renewal_pending(with_anniversaries=2)
    org, agr, anns = ctx["org"], ctx["agreement"], ctx["anniversaries"]
    cur = get_success_data(api.get_agreement(agr["id"], LS))
    resp = api.renew_agreement(agr["id"], {"new_end_date": "2032-08-31",
                                           "expected_agreement_version": cur["version"]}, PA)
    data = validate_success(resp, 200)
    assert data["status"] == "RENEWED"
    assert data["renewal_count"] == 1
    assert data["end_date"] == "2032-08-31"
    for ann in anns:
        ann_after = get_success_data(api.get_anniversary(ann["id"], LS))
        assert ann_after["true_up_closed"] is True, "renewal must close every anniversary"


def test_renew_stale_version_occ_conflict(api):
    """PRD §2.8: "Renewing an agreement requires the request to carry `expected_agreement_version` holding the agreement `version` the client last observed; if the agreement's current `version` has advanced beyond that value, the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/renew_stale_version_occ_conflict
    """
    ctx = setup_agreement_in_renewal_pending()
    agr = ctx["agreement"]
    cur = get_success_data(api.get_agreement(agr["id"], LS))
    resp1 = api.renew_agreement(agr["id"], {"new_end_date": "2032-08-31",
                                            "expected_agreement_version": cur["version"]}, PA)
    ok = validate_success(resp1, 200)
    assert ok["status"] == "RENEWED"
    resp2 = api.renew_agreement(agr["id"], {"new_end_date": "2032-08-31",
                                            "expected_agreement_version": cur["version"]}, PA)
    actual = validate_error_is_one_of(resp2, [ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_INVALID_STATE])
    assert actual in ("ERR_STALE_VERSION", "ERR_INVALID_STATE")


def test_activation_window_missed_after_start_date(api):
    """PRD §3.1: "Activation moves the agreement `DRAFT → ACTIVE` and is only possible on or before the term's start date: if the logical clock has already passed `start_date`, the attempt is rejected with `ERR_ACTIVATION_WINDOW_MISSED` (HTTP 422)".

    Design: Corner/endpoints/activation_window_missed_after_start_date
    """
    org = create_organization(legal_name="Win Org", qualified_device_count=100)
    agr = create_draft_agreement(org["id"], enrollment_number="E-WIN-1",
                                 start_date="2026-09-01", end_date="2029-08-31")
    set_clock("2026-09-02T00:00:00Z")
    resp = api.activate_agreement(agr["id"], PA)
    validate_error(resp, ApiErrorId.ERR_ACTIVATION_WINDOW_MISSED, 422)


def test_renewal_review_outside_window(api):
    """PRD §3.6: "The review may only be opened inside the ninety-day window before the term ends — the current logical clock date must fall on or after ninety days before `end_date` and on or before `end_date` itself; outside that window the attempt is rejected with `ERR_RENEWAL_WINDOW` (HTTP 422)."

    Design: Corner/endpoints/renewal_review_outside_window
    """
    org, agr = create_active_agreement(enrollment_number="E-RW-1",
                                       start_date="2026-09-01", end_date="2029-08-31")
    resp = api.open_renewal_review(agr["id"], LS)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW, 422)


def test_non_renewal_cascade_grants_forfeited_commitments_expired(api):
    """PRD §2.10: "When an agreement leaves the active commercial world — by non-renewal or by expiry — its dependents are swept in the same write. Every software-assurance benefit grant of that agreement still in `ACTIVE` status becomes `FORFEITED`, and every cloud commitment still `ACTIVE` becomes `EXPIRED`, with the unconsumed remainder forfeited and no refund record created."

    Design: Difficulty/transitive_cascade/non_renewal_cascade_grants_forfeited_commitments_expired
    """
    ctx = setup_agreement_in_renewal_pending(
        grants=[{"benefit_type": "TRAINING_VOUCHER",
                 "quantity_granted": 4, "expires_on": "2029-12-31"}],
        commitments=[{"committed_amount_cents": 100000, "expires_on": "2029-12-31"}])
    org, agr = ctx["org"], ctx["agreement"]
    grant = ctx["grants"][0]
    com = ctx["commitments"][0]
    resp = api.decline_renewal(agr["id"], {"decision": "NON_RENEW"}, ctx["customer_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "NON_RENEWED"
    grant_after = get_success_data(api.get_benefit_grant(grant["id"], LS))
    assert grant_after["status"] == "FORFEITED"
    com_after = get_success_data(api.get_cloud_commitment(com["id"], LS))
    assert com_after["status"] == "EXPIRED"
    assert com_after["consumed_amount_cents"] == 0


def test_expiry_cascade_forfeits_grants_and_expires_commitments(api):
    """PRD §3.6: "Expiry triggers the same terminal sweep as non-renewal: `ACTIVE` grants forfeit and `ACTIVE` commitments expire."
    PRD §2.10: "Every software-assurance benefit grant of that agreement still in `ACTIVE` status becomes `FORFEITED`, and every cloud commitment still `ACTIVE` becomes `EXPIRED`, with the unconsumed remainder forfeited and no refund record created."

    Design: Difficulty/transitive_cascade/non_renewal_cascade_grants_forfeited_commitments_expired
    """
    org, agr = create_active_agreement(end_date="2026-09-30")
    grant = create_benefit_grant(agr["id"], benefit_type="SUPPORT_INCIDENT",
                                 quantity_granted=2, expires_on="2027-06-01")
    resp = api.create_cloud_commitment(agr["id"], {"committed_amount_cents": 50000,
                                                   "expires_on": "2027-06-01"}, LS)
    com = get_success_data(resp)
    assert resp.status_code == 201
    set_clock("2026-10-01T00:00:00Z")
    resp = api.expire_agreement(agr["id"], PA)
    data = validate_success(resp, 200)
    assert data["status"] == "EXPIRED"
    assert get_success_data(api.get_benefit_grant(grant["id"], LS))["status"] == "FORFEITED"
    assert get_success_data(api.get_cloud_commitment(com["id"], LS))["status"] == "EXPIRED"


def test_anniversary_period_strictly_increasing_sequence(api):
    """PRD §3.3: "the `period_start` must not precede the agreement's `start_date` and must fall strictly after the previous anniversary's `period_start`; and the `period_end` must fall after its own `period_start`. ... any violation is rejected with `ERR_INVALID_ANNIVERSARY_SEQUENCE` (HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/anniversary_period_strictly_increasing_sequence
    """
    org, agr = create_active_agreement(enrollment_number="E-OV1-1")
    ann1 = register_anniversary(agr["id"], year_index=1,
                                period_start="2026-09-01", period_end="2027-08-31")
    resp = api.register_anniversary(agr["id"], {"year_index": 2,
                                                "period_start": "2026-09-01",
                                                "period_end": "2028-08-31"}, PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_ANNIVERSARY_SEQUENCE, 422)
    resp2 = api.register_anniversary(agr["id"], {"year_index": 2,
                                                 "period_start": "2027-09-01",
                                                 "period_end": "2028-08-31"}, PA)
    ann2 = validate_success(resp2, 201)
    assert ann2["year_index"] == 2


def test_anniversary_year_index_must_exceed_existing(api):
    """PRD §3.3: "the `year_index` must lie within 1 through 3 and must be strictly greater than every `year_index` already registered for that agreement".

    Design: Difficulty/resource_temporal_overlap/anniversary_period_strictly_increasing_sequence
    """
    org, agr = create_active_agreement(enrollment_number="E-OV1B-1")
    register_anniversary(agr["id"], year_index=1, period_start="2026-09-01", period_end="2027-08-31")
    resp = api.register_anniversary(agr["id"], {"year_index": 1,
                                                "period_start": "2027-09-01",
                                                "period_end": "2028-08-31"}, PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_ANNIVERSARY_SEQUENCE, 422)
