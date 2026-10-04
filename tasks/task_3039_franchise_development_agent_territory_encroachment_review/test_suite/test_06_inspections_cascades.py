"""Compliance inspections: scoring, rounding order, outcome thresholds, and
store cascades (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_franchisee,
    create_store,
    create_territory,
    create_transfer,
    finalize_inspection,
    get_inspection,
    get_store,
    get_transfer_request,
    make_inspector_headers,
    record_findings,
    schedule_inspection,
    setup_territory_with_stores,
    validate_error,
    validate_success,
)


def test_inspection_score_per_line_rounding_order(api, franchisor_ops_headers):
    """PRD §3.6: "each category score is first multiplied by its weight — 0.40
    for food safety, 0.30 for cleanliness, 0.30 for operations — and each
    weighted category is rounded half up to 2 decimal places; the three
    rounded figures are summed ... This per-category-rounding-before-summation
    order is pinned."

    Design: Difficulty/combinatorial_formula/inspection_score_per_line_rounding_order
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store = ctx["stores"][0]
    insp = schedule_inspection(store["id"], inspector_ref="insp-1")
    conducted = record_findings(insp["id"], "insp-1", food=87.55, cleanliness=76.65,
                                operations=81.15, critical_violations=0)
    assert conducted["status"] == "CONDUCTED"
    # Per-line rounding: 35.02 + 23.00 + 24.35 = 82.37 (sum-then-round = 82.36).
    assert conducted["final_score"] == pytest.approx(82.37, abs=0.001)
    assert conducted["final_score"] != pytest.approx(82.36, abs=0.0001)


def test_inspection_score_rounding_half_up_per_category(api, franchisor_ops_headers):
    """PRD §3.6: "each weighted category is rounded half up to 2 decimal
    places; the three rounded figures are summed; two and a half points per
    critical violation are subtracted; the result is rounded half up to 2
    decimal places and floored at zero."
    PRD §2.9: "Inspection scores ... are computed to 2 decimal places, round
    half up."

    Design: Difficulty/combinatorial_formula/inspection_score_per_line_rounding_order
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store = ctx["stores"][0]
    insp = schedule_inspection(store["id"], inspector_ref="insp-1")
    # Clean values: 90.00 x 0.40 = 36.00, 80.00 x 0.30 = 24.00, 70.00 x 0.30
    # = 21.00; sum 81.00, minus 1 x 2.50 penalty = 78.50.
    conducted = record_findings(insp["id"], "insp-1", food=90.0, cleanliness=80.0,
                                operations=70.0, critical_violations=1)
    assert conducted["final_score"] == pytest.approx(78.50, abs=0.001)


def test_inspection_boundary_60_passes_and_59_97_fails(api, franchisor_ops_headers):
    """PRD §3.6: "Finalizing derives the `outcome`: `FAIL_CRITICAL` when
    `critical_violations` is three or more; otherwise `PASS` when
    `final_score` is at least 60.00; otherwise `FAIL`." and "A non-critical
    `FAIL` against an `OPEN` store moves it to `PROBATION` and increments its
    `consecutive_failed_inspections`"

    Design: Corner/calculations/inspection_boundary_60_passes_and_59_97_fails
    """
    ctx = setup_territory_with_stores(store_count=2, agent_assigned=False)
    s1, s2 = ctx["stores"]
    i1 = schedule_inspection(s1["id"], inspector_ref="insp-1")
    record_findings(i1["id"], "insp-1", food=60.0, cleanliness=60.0,
                    operations=60.0, critical_violations=0)
    i2 = schedule_inspection(s2["id"], inspector_ref="insp-1")
    record_findings(i2["id"], "insp-1", food=59.98, cleanliness=59.98,
                    operations=59.98, critical_violations=0)
    f1 = finalize_inspection(i1["id"])
    f2 = finalize_inspection(i2["id"])
    assert f1["final_score"] == pytest.approx(60.00, abs=0.001)
    assert f1["outcome"] == "PASS"
    assert get_store(s1["id"])["status"] == "OPEN"
    # 59.98 x (0.40+0.30+0.30) per-line rounded = 59.97 < 60.00 -> FAIL.
    assert f2["final_score"] == pytest.approx(59.97, abs=0.001)
    assert f2["outcome"] == "FAIL"
    store2 = get_store(s2["id"])
    assert store2["status"] == "PROBATION"
    assert store2["consecutive_failed_inspections"] == 1


def test_pass_reinspection_restores_probation_store_to_open(api, franchisor_ops_headers):
    """PRD §3.6: "A `PASS` finalized against a store on `PROBATION` returns it
    to `OPEN` and resets `consecutive_failed_inspections` to zero."

    Design: Corner/state_machines/pass_reinspection_restores_probation_store_to_open
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store = ctx["stores"][0]
    i1 = schedule_inspection(store["id"], inspector_ref="insp-1")
    record_findings(i1["id"], "insp-1", food=59.98, cleanliness=59.98,
                    operations=59.98, critical_violations=0)
    f1 = finalize_inspection(i1["id"])
    assert f1["outcome"] == "FAIL"
    assert get_store(store["id"])["status"] == "PROBATION"
    i2 = schedule_inspection(store["id"], inspector_ref="insp-2",
                             scheduled_on="2026-09-09T00:00:00Z")
    record_findings(i2["id"], "insp-2", food=90.0, cleanliness=90.0,
                    operations=90.0, critical_violations=0)
    f2 = finalize_inspection(i2["id"])
    assert f2["outcome"] == "PASS"
    assert f2["final_score"] == pytest.approx(90.00, abs=0.001)
    restored = get_store(store["id"])
    assert restored["status"] == "OPEN"
    assert restored["consecutive_failed_inspections"] == 0


def test_fail_critical_inspection_cascade_cancels_transfer_and_voids_inspection(
        api, franchisor_ops_headers):
    """PRD §3.6: "A `FAIL_CRITICAL`, or a `FAIL` against a store whose
    `consecutive_failed_inspections` already stood at one or more — the second
    consecutive failure — moves the store from `OPEN` or `PROBATION` to
    `TERMINATION_PENDING`: the failure count increments, in-flight transfers
    cancel, and every still-`SCHEDULED` inspection of the store is voided."

    Design: Difficulty/transitive_cascade/fail_critical_inspection_cascade_depth2
    """
    territory = create_territory()
    seller = create_franchisee()
    buyer = create_franchisee()
    store = create_store(territory["id"], seller["id"])
    transfer = create_transfer(store, seller["id"], buyer["id"])
    i1 = schedule_inspection(store["id"], inspector_ref="insp-1")
    record_findings(i1["id"], "insp-1", food=70.0, cleanliness=70.0,
                    operations=70.0, critical_violations=3)
    i2 = schedule_inspection(store["id"], inspector_ref="insp-2",
                             scheduled_on="2026-09-09T00:00:00Z")
    finalized = finalize_inspection(i1["id"])
    assert finalized["outcome"] == "FAIL_CRITICAL"
    store_after = get_store(store["id"])
    assert store_after["status"] == "TERMINATION_PENDING"
    transfer_after = get_transfer_request(transfer["id"])
    assert transfer_after["status"] == "CANCELLED"
    i2_after = get_inspection(i2["id"])
    assert i2_after["status"] == "VOID"


def test_second_consecutive_fail_moves_store_to_termination_pending(api, franchisor_ops_headers):
    """PRD §3.6: "a `FAIL` against a store whose
    `consecutive_failed_inspections` already stood at one or more — the second
    consecutive failure — moves the store from `OPEN` or `PROBATION` to
    `TERMINATION_PENDING`"

    Design: Difficulty/transitive_cascade/fail_critical_inspection_cascade_depth2
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store = ctx["stores"][0]
    i1 = schedule_inspection(store["id"], inspector_ref="insp-1")
    record_findings(i1["id"], "insp-1", food=50.0, cleanliness=50.0,
                    operations=50.0, critical_violations=0)
    finalize_inspection(i1["id"])
    assert get_store(store["id"])["status"] == "PROBATION"
    i2 = schedule_inspection(store["id"], inspector_ref="insp-1",
                             scheduled_on="2026-09-09T00:00:00Z")
    record_findings(i2["id"], "insp-1", food=50.0, cleanliness=50.0,
                    operations=50.0, critical_violations=0)
    f2 = finalize_inspection(i2["id"])
    assert f2["outcome"] == "FAIL"
    assert get_store(store["id"])["status"] == "TERMINATION_PENDING"


def test_inspector_cannot_finalize_own_inspection(api):
    """PRD §2.7: "the `Inspector` who records findings must be the operator
    whose `X-User-ID` equals the inspection's `inspector_ref`, and that same
    operator is barred from finalizing the inspection — finalization is
    performed by `FranchisorOps`"
    PRD §2.1: "Attempting an operation outside the caller's role ... is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/inspector_cannot_finalize_own_inspection
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store = ctx["stores"][0]
    insp = schedule_inspection(store["id"], inspector_ref="insp-1")
    record_findings(insp["id"], "insp-1")
    resp = api.finalize_inspection(insp["id"], make_inspector_headers("insp-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
    still = get_inspection(insp["id"])
    assert still["status"] == "CONDUCTED"
    assert still["outcome"] is None
