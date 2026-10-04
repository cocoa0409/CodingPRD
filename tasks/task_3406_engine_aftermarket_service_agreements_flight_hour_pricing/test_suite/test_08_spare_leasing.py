"""Spare-engine leasing: half-open window semantics, per-asset exclusion,
window/model validation, lease pricing + deposit, and the pool-conservation
invariant across activate/return."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_enrolled_engine,
    create_visit,
    create_spare_engine,
    create_lease,
    activate_lease,
    return_lease,
    create_spare_engine_lease_payload,
    TEST_USERS,
)


def test_lease_window_adjacency_boundary(api):
    """PRD §3.8: "the new window must not overlap any other `RESERVED` or
    `ACTIVE` lease of the same spare engine under half-open semantics — two
    windows that merely touch, one's `end_date` equal to the other's
    `start_date`, do not overlap — otherwise `ERR_LEASE_WINDOW_OVERLAP`."
    PRD §3.8: "The `lease_cost_usd` is the number of whole calendar days
    inside the half-open window multiplied by the spare's
    `daily_lease_rate_usd`, rounded half-up to 2 decimal places. The
    `deposit_usd` depends on the covered operator's creditworthiness: it is 0
    when the operator's `credit_rating` is `A`, and a flat 50,000 USD
    otherwise."

    Arithmetic: [2026-10-01, 2026-10-10) = 9 days * 4000.00 = 36000.00,
    deposit waived (credit A); the adjacent [2026-10-10, 2026-10-15) = 5 days
    = 20000.00 is legal; [2026-10-09, 2026-10-11) intersects existing windows.

    Design: Difficulty/boundary_precision_check/lease_window_adjacency_boundary
    """
    fx = setup_enrolled_engine(
        credit_rating="A",
        esn="ESN-L201",
        operator_overrides={"name": "Lakeshore Air", "iata_code": "LB"},
        agreement_overrides={"contract_ref": "LTSA-L12"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2026-10-01T00:00:00Z")
    spare = create_spare_engine(spare_serial="SP-L2", daily_lease_rate_usd=4000)

    l1 = create_lease(spare, visit, fx["operator_headers"],
                      "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z")
    assert l1["lease_cost_usd"] == pytest.approx(36000.00, abs=0.01)
    assert l1["deposit_usd"] == pytest.approx(0.00, abs=0.001)

    l2_res = api.create_spare_engine_lease(
        create_spare_engine_lease_payload(
            spare_engine_id=spare["id"], shop_visit_id=visit["id"],
            start_date="2026-10-10T00:00:00Z", end_date="2026-10-15T00:00:00Z"),
        fx["operator_headers"],
    )
    l2 = validate_success(l2_res, 201)
    assert l2["status"] == "RESERVED"
    assert l2["lease_cost_usd"] == pytest.approx(20000.00, abs=0.01)

    res = api.create_spare_engine_lease(
        create_spare_engine_lease_payload(
            spare_engine_id=spare["id"], shop_visit_id=visit["id"],
            start_date="2026-10-09T00:00:00Z", end_date="2026-10-11T00:00:00Z"),
        fx["operator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_LEASE_WINDOW_OVERLAP.value)


def test_spare_engine_half_open_exclusion(api):
    """PRD §3.8: "And one spare cannot be promised twice for the same time:
    the new window must not overlap any other `RESERVED` or `ACTIVE` lease of
    the same spare engine under half-open semantics".

    The same interior window [2026-10-05, 2026-10-12) is rejected on SP-O1
    (overlaps the existing reservation) but accepted on SP-O2 — the resource
    identity, not just the interval, decides. Cost: 7 days * 3000.00 =
    21000.00.

    Design: Difficulty/resource_temporal_overlap/spare_engine_half_open_exclusion
    """
    fx = setup_enrolled_engine(
        esn="ESN-O501",
        operator_overrides={"name": "Orchard Air", "iata_code": "OE"},
        agreement_overrides={"contract_ref": "LTSA-O15"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2026-10-01T00:00:00Z")
    spare1 = create_spare_engine(spare_serial="SP-O1", daily_lease_rate_usd=3000)
    spare2 = create_spare_engine(spare_serial="SP-O2", daily_lease_rate_usd=3000)
    create_lease(spare1, visit, fx["operator_headers"],
                 "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z")

    res = api.create_spare_engine_lease(
        create_spare_engine_lease_payload(
            spare_engine_id=spare1["id"], shop_visit_id=visit["id"],
            start_date="2026-10-05T00:00:00Z", end_date="2026-10-12T00:00:00Z"),
        fx["operator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_LEASE_WINDOW_OVERLAP.value)

    l2_res = api.create_spare_engine_lease(
        create_spare_engine_lease_payload(
            spare_engine_id=spare2["id"], shop_visit_id=visit["id"],
            start_date="2026-10-05T00:00:00Z", end_date="2026-10-12T00:00:00Z"),
        fx["operator_headers"],
    )
    l2 = validate_success(l2_res, 201)
    assert l2["status"] == "RESERVED"
    assert l2["lease_cost_usd"] == pytest.approx(21000.00, abs=0.01)


def test_spare_pool_conserved_across_lease_cycle(api, shop_planner_headers):
    """PRD §3.8: "Activation moves the lease to `ACTIVE`, moves the spare
    engine from `AVAILABLE` to `LEASED`, and increments both resources'
    `version` by 1. Returning an `ACTIVE` lease moves it to `RETURNED`
    (terminal), returns the spare from `LEASED` to `AVAILABLE`, and again
    increments both versions."

    Arithmetic: [2026-09-01, 2026-10-01) = 30 days * 4000.00 = 120000.00;
    activate + return leave the spare exactly AVAILABLE again.

    Design: Difficulty/compensating_invariant/spare_pool_conserved_across_lease_cycle
    """
    fx = setup_enrolled_engine(
        esn="ESN-R701",
        operator_overrides={"name": "River Air", "iata_code": "RG"},
        agreement_overrides={"contract_ref": "LTSA-R17"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2026-09-01T00:00:00Z")
    spare = create_spare_engine(spare_serial="SP-R1", daily_lease_rate_usd=4000)
    assert spare["status"] == "AVAILABLE"

    lease = create_lease(spare, visit, fx["operator_headers"],
                         "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
    assert lease["lease_cost_usd"] == pytest.approx(120000.00, abs=0.01)

    active = activate_lease(lease, fx["operator_headers"])
    assert active["status"] == "ACTIVE"
    mid = validate_success(api.get_spare_engine(spare["id"], shop_planner_headers), 200)
    assert mid["status"] == "LEASED"

    returned = return_lease(lease, fx["operator_headers"])
    assert returned["status"] == "RETURNED"
    post = validate_success(api.get_spare_engine(spare["id"], shop_planner_headers), 200)
    assert post["status"] == "AVAILABLE"


def test_lease_deposit_applied_for_credit_b(api):
    """PRD §3.8: "The `deposit_usd` depends on the covered operator's
    creditworthiness: it is 0 when the operator's `credit_rating` is `A`, and
    a flat 50,000 USD otherwise."
    PRD §3.1: "an operator rated `A` has the spare-engine lease deposit waived
    entirely, while `B` and `C` operators pay it in full".

    Arithmetic: [2026-09-05, 2026-09-07) = 2 days * 3000.00 = 6000.00;
    credit B -> deposit 50000.00.

    Design: Corner/calculations/lease_deposit_applied_for_credit_b
    """
    fx = setup_enrolled_engine(
        credit_rating="B",
        esn="ESN-F201",
        operator_overrides={"name": "Fjord Air", "iata_code": "FB"},
        agreement_overrides={"contract_ref": "LTSA-C901"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2026-09-05T00:00:00Z")
    spare = create_spare_engine(spare_serial="SP-F2", daily_lease_rate_usd=3000)
    lease = create_lease(spare, visit, fx["operator_headers"],
                         "2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z")
    assert lease["lease_cost_usd"] == pytest.approx(6000.00, abs=0.01)
    assert lease["deposit_usd"] == pytest.approx(50000.00, abs=0.01)


def test_lease_window_inverted_rejected(api):
    """PRD §3.8: "The `end_date` must be strictly after the `start_date`, else
    `ERR_INVALID_WINDOW`."

    A zero-length window (end_date equal to start_date) violates the strict
    ordering.

    Design: Corner/validations/lease_window_inverted_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-J101",
        operator_overrides={"name": "Jade Air", "iata_code": "JA"},
        agreement_overrides={"contract_ref": "LTSA-V2001"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2026-10-01T00:00:00Z")
    spare = create_spare_engine(spare_serial="SP-J1", daily_lease_rate_usd=3000)
    res = api.create_spare_engine_lease(
        create_spare_engine_lease_payload(
            spare_engine_id=spare["id"], shop_visit_id=visit["id"],
            start_date="2026-10-01T00:00:00Z", end_date="2026-10-01T00:00:00Z"),
        fx["operator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_spare_model_mismatch_rejected(api):
    """PRD §3.8: "The spare's `engine_model` must match the model of the
    engine under the covered visit, else `ERR_MODEL_MISMATCH`."
    PRD §3.1: "a spare engine may only substitute for an engine of the same
    model."

    A CFM56-8B spare cannot cover a CFM56-7B visit; the window itself is
    valid and non-overlapping.

    Design: Corner/validations/spare_model_mismatch_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-K201",
        engine_model="CFM56-7B",
        operator_overrides={"name": "Kite Air", "iata_code": "KB"},
        agreement_overrides={"contract_ref": "LTSA-V2101"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2026-10-01T00:00:00Z")
    spare = create_spare_engine(spare_serial="SP-K2", engine_model="CFM56-8B",
                                daily_lease_rate_usd=3000)
    res = api.create_spare_engine_lease(
        create_spare_engine_lease_payload(
            spare_engine_id=spare["id"], shop_visit_id=visit["id"],
            start_date="2026-10-01T00:00:00Z", end_date="2026-10-08T00:00:00Z"),
        fx["operator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_MODEL_MISMATCH.value)


def test_lease_activate_before_window_rejected(api):
    """PRD §3.8: "Activating a lease requires it to be `RESERVED` (activation
    from any other status is rejected with `ERR_INVALID_STATE`), requires the
    logical clock to sit inside the window — on or after `start_date` and
    strictly before `end_date`, otherwise `ERR_LEASE_NOT_IN_WINDOW` — requires
    the covered visit to be `SCHEDULED` or `INDUCTED`, and requires the spare
    to be `AVAILABLE`."

    The clock (2026-09-01, PRD §2.4) sits before the December window; visit
    state (SCHEDULED) and pool state (AVAILABLE) are both valid, isolating the
    window check.

    Design: Corner/validations/lease_activate_before_window_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-V401",
        operator_overrides={"name": "Vista Air", "iata_code": "VD"},
        agreement_overrides={"contract_ref": "LTSA-V3401"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2026-12-01T00:00:00Z")
    spare = create_spare_engine(spare_serial="SP-V4", daily_lease_rate_usd=3000)
    lease = create_lease(spare, visit, fx["operator_headers"],
                         "2026-12-01T00:00:00Z", "2026-12-10T00:00:00Z")
    res = api.activate_spare_engine_lease(lease["id"], fx["operator_headers"])
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_IN_WINDOW.value)
