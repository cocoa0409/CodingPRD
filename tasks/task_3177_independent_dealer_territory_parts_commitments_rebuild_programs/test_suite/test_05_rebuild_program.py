"""Certified rebuilds: approval gates, specification limits and lockdowns."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    ApiErrorId,
    create_dealer,
    create_rebuild_claim,
    get_rebuild_claim,
    parts_manager_headers,
    rebuild_specialist_headers,
    set_clock,
    setup_active_agreement_order_ready_commitment,
    setup_performance_deficient_commitment,
)


def _claim_payload(dealer, **overrides):
    payload = {
        "dealer_id": dealer["id"],
        "product_family": "EXCAVATION",
        "machine_serial": "SN-7001",
        "machine_operating_weight_lb": 130000,
        "client_meter_hours": 4000,
        "requested_at": "2026-08-20T00:00:00Z",
        "core_purchase_value_cents": 4000000,
        "rebuild_labor_hours": 10.0,
        "rebuild_labor_rate_cents": 14000,
        "certified_rebuild_spec_code": "CAT_CERTIFIED_3",
    }
    payload.update(overrides)
    return payload


def test_approval_reports_the_specification_limit_before_the_population_gate():
    """PRD §2.5: "6. **Business safety.** Certified-rebuild specification limits and warranty-safety limits are checked here: the machine's `machine_operating_weight_lb` against the specification's maximum weight, the specification's technician certification minimum against the agreement's `certified_technician_count`, and the destination of a remanufactured core. Failure gives `ERR_REBUILD_SPEC_EXCEEDED` at HTTP 422."
    PRD §2.5: "9. **Population and representation referential limits.** A machine's serial must be live in the dealer's population before a rebuild claim can be tied to it, and a superseded party registration blocks the decline path. Failure gives `ERR_MACHINE_NOT_IN_POPULATION` at HTTP 409." PRD §2.5: "the first rung that fails determines the error the
    caller sees and later rungs are never reached on that request."

    Design: Difficulty/priority_pair_validation_conflict/rebuild_spec_safety_outranks_machine_not_in_population_referential
    """
    dealer, _agreement, _commitment, _order = setup_performance_deficient_commitment()
    claim = create_rebuild_claim(dealer, **_claim_payload(dealer))
    assert get_rebuild_claim(claim["id"])["status"] == "REQUESTED"

    resp = api_client.approve_rebuild_claim(
        claim["id"], {"expected_rebuildclaim_version": claim["version"]},
        rebuild_specialist_headers())
    validate_error(resp, ApiErrorId.ERR_REBUILD_SPEC_EXCEEDED, expected_status=422)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_MACHINE_NOT_IN_POPULATION


def test_blocked_approval_leaves_the_claim_unpriced():
    """PRD §3.7: "Approval derives `core_purchase_value_cents` from the machine,
    recomputes `rebuild_fee_cents` and recomputes `core_return_credit_cents`, and
    it increments the claim's version by 1."
    PRD §2.5: "a rung that passes never re-raises."

    Design: Difficulty/priority_pair_validation_conflict/rebuild_spec_safety_outranks_machine_not_in_population_referential
    """
    dealer, _agreement, _commitment, _order = setup_performance_deficient_commitment()
    claim = create_rebuild_claim(dealer, **_claim_payload(dealer))
    api_client.approve_rebuild_claim(
        claim["id"], {"expected_rebuildclaim_version": claim["version"]},
        rebuild_specialist_headers())

    after = get_rebuild_claim(claim["id"])
    assert after["status"] == "REQUESTED"
    assert after["rebuild_fee_cents"] is None


def test_deny_locks_the_claim_out_of_approval():
    """PRD §3.7: "Rejection by denial moves `REQUESTED` to `DENIED` and has no
    precondition at all. It creates no commitment, no core credit and no rebuild
    fee for the claim."
    PRD §2.5: "5. **State admissibility.** The target resource must be in a state that admits the operation, and every from-state not listed for a trigger is refused with that operation's invalid-state error, `ERR_INVALID_STATE` at HTTP 409."

    Design: Corner/state_machines/rebuild_claim_deny_locks_the_claim_out_of_approval
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    claim = create_rebuild_claim(dealer, **_claim_payload(
        dealer, machine_serial="SN-7100", machine_operating_weight_lb=90000,
        certified_rebuild_spec_code="CAT_CERTIFIED_2"))
    get_success_data(api_client.deny_rebuild_claim(
        claim["id"], rebuild_specialist_headers()))
    assert get_rebuild_claim(claim["id"])["status"] == "DENIED"

    resp = api_client.approve_rebuild_claim(
        claim["id"], {"expected_rebuildclaim_version": claim["version"]},
        rebuild_specialist_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_rebuild_claim(claim["id"])["status"] == "DENIED"


def test_denied_claim_carries_no_pricing_fields():
    """PRD §3.7: "It creates no commitment, no core credit and no rebuild fee for the claim."

    Design: Corner/state_machines/rebuild_claim_deny_locks_the_claim_out_of_approval
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    claim = create_rebuild_claim(dealer, **_claim_payload(
        dealer, machine_serial="SN-7100", machine_operating_weight_lb=90000,
        certified_rebuild_spec_code="CAT_CERTIFIED_2"))
    get_success_data(api_client.deny_rebuild_claim(
        claim["id"], rebuild_specialist_headers()))
    api_client.approve_rebuild_claim(
        claim["id"], {"expected_rebuildclaim_version": claim["version"]},
        rebuild_specialist_headers())

    after = get_rebuild_claim(claim["id"])
    assert after["rebuild_fee_cents"] is None
    assert after["core_return_credit_cents"] is None


def test_approval_without_repair_priority_reports_the_priority_gate():
    """PRD §3.7: "The dealer must hold at least one commitment in status
    `PERFORMANCE_DEFICIENT`, so that the rebuild carries a repair priority;
    without one the refusal is `ERR_NO_RESTRICTION_PRIORITY` at HTTP 409."

    Design: Corner/errors/rebuild_claim_approve_without_repair_priority_returns_no_restriction_priority
    """
    dealer, _agreement, _commitment = setup_active_agreement_order_ready_commitment()
    claim = create_rebuild_claim(dealer, **_claim_payload(
        dealer, machine_serial="SN-7200", machine_operating_weight_lb=40000,
        certified_rebuild_spec_code="CAT_CERTIFIED_1"))

    resp = api_client.approve_rebuild_claim(
        claim["id"], {"expected_rebuildclaim_version": claim["version"]},
        rebuild_specialist_headers())
    validate_error(resp, ApiErrorId.ERR_NO_RESTRICTION_PRIORITY, expected_status=409)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_REBUILD_SPEC_EXCEEDED


def test_priority_gate_leaves_the_claim_requested():
    """PRD §3.7: "Approval moves `REQUESTED` to `APPROVED` and is gated on three conditions. The dealer's agreement for that product family must be `ACTIVE`; when it is not, the refusal is `ERR_NO_ACTIVE_AGREEMENT` at HTTP 409. The dealer must hold at least one commitment in status `PERFORMANCE_DEFICIENT`, so that the rebuild carries a repair priority; without one the refusal is `ERR_NO_RESTRICTION_PRIORITY` at HTTP 409."

    Design: Corner/errors/rebuild_claim_approve_without_repair_priority_returns_no_restriction_priority
    """
    dealer, _agreement, _commitment = setup_active_agreement_order_ready_commitment()
    claim = create_rebuild_claim(dealer, **_claim_payload(
        dealer, machine_serial="SN-7200", machine_operating_weight_lb=40000,
        certified_rebuild_spec_code="CAT_CERTIFIED_1"))
    api_client.approve_rebuild_claim(
        claim["id"], {"expected_rebuildclaim_version": claim["version"]},
        rebuild_specialist_headers())

    assert get_rebuild_claim(claim["id"])["status"] == "REQUESTED"
    deficient = get_success_data(api_client.list_commitments(
        parts_manager_headers(),
        params={"dealer_id": dealer["id"], "status": "PERFORMANCE_DEFICIENT"}))
    assert deficient == []