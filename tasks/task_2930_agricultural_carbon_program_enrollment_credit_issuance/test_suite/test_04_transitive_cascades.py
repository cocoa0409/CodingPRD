"""Cascades that walk entities the caller never names.

Baseline approval reaches three entities deep and feeds a grower aggregate from
the field rather than the enrollment; reversal assessment reaches seven hops deep
and ends by suspending the grower, which re-cascades on its own.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import assert_acres, assert_cents, assert_credits, assert_tonnes
from test_helpers.constants import (
    BASELINE_APPROVED,
    BASELINE_PROPOSED,
    ENROLLMENT_ACCEPTED,
    ENROLLMENT_ACTIVE,
    ENROLLMENT_SUSPENDED,
    FIELD_ENROLLED,
    FIELD_MAPPED,
    FIELD_SUSPENDED,
    GROWER_ACTIVE,
    GROWER_SUSPENDED,
    ISSUANCE_ISSUED,
    PAYMENT_CLAWED_BACK,
    PERMANENCE_BREACHED,
    PERMANENCE_IN_COMPLIANCE,
    PERMANENCE_NOT_STARTED,
    POOL_DEFICIT,
    POOL_HEALTHY,
    REGISTRY_SUSPENDED,
    REVERSAL_ASSESSED,
    REVERSAL_UNINTENTIONAL,
)
from test_helpers.factories import reversal_payload
from test_helpers.test_users import (
    ADMIN_BASELINE_ID,
    ADMIN_HEADERS,
    ADMIN_REVERSAL_ASSESSOR_HEADERS,
    ADMIN_REVERSAL_REPORTER_HEADERS,
)

BIG_FIELD = {
    "field_name": "Big Section",
    "boundary_max_x": 10000,
    "gross_acres": 5010.00,
    "county_code": "SD-103",
}


def _reversal_ready(scenario):
    """A listed 1217-credit batch, an accrued per-acre payment and a reported reversal."""
    scenario.issued_batch(
        field_overrides=BIG_FIELD,
        enrollment_overrides={"enrolled_acres": 5000.00, "per_acre_rate_cents": 1000.00},
        per_acre=True,
        history_adopted_acres=(1000.00, 2500.00),
        packet_overrides={"reported_acres": 5000.00},
        verification_overrides={"sample_pct": 20.00},
    )
    scenario.list_batch()
    payment = scenario.accrue_payment(2026)
    reversal = get_success_data(
        scenario.api.create_reversal_event(
            reversal_payload(scenario.batch_id, 2000.00, 2026, REVERSAL_UNINTENTIONAL),
            ADMIN_REVERSAL_REPORTER_HEADERS,
        )
    )
    return payment, reversal


def test_baseline_approval_walks_three_hops_to_the_grower_aggregate(scenario):
    """Approval activates the enrollment, enrolls the field and grows the grower aggregate
    by the field's 1000.00 mapped acres, not by the 900.00 acres enrolled.

    PRD §3.4: "Third, *because* the field became `ENROLLED`, the grower's
    `total_enrolled_acres` increases by that field's `mapped_acres`."

    Design: Difficulty/transitive_cascade/baseline_approval_three_hop_cascade
    """
    scenario.accepted_enrollment(enrollment_overrides={"enrolled_acres": 900.00})
    scenario.propose_baseline()

    approved = scenario.approve_baseline()

    assert approved["status"] == BASELINE_APPROVED
    assert approved["approved_by_admin_id"] == ADMIN_BASELINE_ID
    assert_tonnes(approved["baseline_emissions_t"], 145.000)
    enrollment = scenario.reload_enrollment()
    assert enrollment["status"] == ENROLLMENT_ACTIVE
    assert enrollment["permanence_status"] == PERMANENCE_IN_COMPLIANCE
    assert enrollment["baseline_approval_admin_id"] == ADMIN_BASELINE_ID
    assert scenario.reload_field()["status"] == FIELD_ENROLLED
    assert_acres(scenario.reload_grower()["total_enrolled_acres"], 1000.00)
    # 900.00 would mean the aggregate was fed by enrolled_acres; 0.00 that hop 3 never ran.
    assert scenario.grower["total_enrolled_acres"] not in (900.00, 0.00)


def test_nothing_downstream_of_the_field_moves_before_or_after_approval(scenario):
    """Before approval the field is still mapped and the aggregate still zero, and after
    approval the cascade stops at the aggregate without touching the credit ledger.

    PRD §3.4: "Second, *because* the enrollment became `ACTIVE`, its field moves
    `MAPPED → ENROLLED`."

    Design: Difficulty/transitive_cascade/baseline_approval_three_hop_cascade
    """
    scenario.accepted_enrollment(enrollment_overrides={"enrolled_acres": 900.00})
    proposed = scenario.propose_baseline()

    assert proposed["status"] == BASELINE_PROPOSED
    assert scenario.reload_enrollment()["status"] == ENROLLMENT_ACCEPTED
    assert scenario.enrollment["permanence_status"] == PERMANENCE_NOT_STARTED
    assert scenario.reload_field()["status"] == FIELD_MAPPED
    assert_acres(scenario.reload_grower()["total_enrolled_acres"], 0.00)

    scenario.approve_baseline()

    ledger = get_success_data(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, ADMIN_HEADERS)
    )
    assert_credits(ledger["lifetime_credits_issued"], 0)
    assert_cents(ledger["accrued_total_cents"], 0)
    assert_cents(ledger["paid_total_cents"], 0)
    assert_credits(ledger["buffer_contributed_credits"], 0)


def test_reversal_assessment_prices_the_damage_and_drains_the_pool(scenario):
    """The unintentional draw is capped by the pool balance at 199 credits, the 288 unbacked
    credits are clawed back at the full share, and the pool falls into deficit.

    PRD §3.8: "For an `UNINTENTIONAL` reversal — fire, drought, flood —
    `buffer_draw_credits` is the smaller of the buffer pool's current `balance_credits`
    and `affected_credits`."

    Design: Difficulty/transitive_cascade/reversal_assessment_seven_hop_cascade
    """
    _payment, reversal = _reversal_ready(scenario)
    pool_before = scenario.buffer_pool()
    assert_credits(pool_before["balance_credits"], 199)
    assert_credits(pool_before["required_reserve_credits"], 61)
    assert pool_before["pool_status"] == POOL_HEALTHY

    assessed = get_success_data(
        scenario.api.assess_reversal(reversal["id"], None, ADMIN_REVERSAL_ASSESSOR_HEADERS)
    )

    assert assessed["status"] == REVERSAL_ASSESSED
    assert_credits(assessed["affected_credits"], 487)
    assert_credits(assessed["buffer_draw_credits"], 199)
    assert_credits(assessed["unbacked_credits"], 288)
    assert_cents(assessed["grower_clawback_cents"], 792000)
    # 487 would ignore the pool cap; 475200 would apply the per-credit share to per-acre.
    assert assessed["buffer_draw_credits"] != 487
    assert assessed["grower_clawback_cents"] != 475200
    pool = scenario.buffer_pool()
    assert_credits(pool["balance_credits"], 0)
    assert_credits(pool["drawn_total"], 199)
    assert_credits(pool["contributed_total"], 199)
    assert_credits(pool["unbacked_reversal_credits"], 288)
    assert_credits(pool["required_reserve_credits"], 61)
    assert pool["pool_status"] == POOL_DEFICIT


def test_pool_deficit_cascades_through_permanence_and_clawback_to_suspension(scenario):
    """The deficit suspends the listed batch, breaches the enrollment, claws the accrued
    payment back once, and the 792000-cent liability suspends the grower and its field.

    PRD §3.8: "Seventh, when a grower's `outstanding_clawback_cents` has thereby reached
    250000 cents or more, that grower moves `ACTIVE → SUSPENDED`, which itself cascades to
    that grower's active enrollments and their enrolled fields exactly as §3.1 describes."

    Design: Difficulty/transitive_cascade/reversal_assessment_seven_hop_cascade
    """
    payment, reversal = _reversal_ready(scenario)
    assert scenario.reload_grower()["status"] == GROWER_ACTIVE

    get_success_data(
        scenario.api.assess_reversal(reversal["id"], None, ADMIN_REVERSAL_ASSESSOR_HEADERS)
    )

    batch = scenario.reload_batch()
    assert batch["registry_status"] == REGISTRY_SUSPENDED
    assert batch["issuance_status"] == ISSUANCE_ISSUED
    enrollment = scenario.reload_enrollment()
    assert enrollment["permanence_status"] == PERMANENCE_BREACHED
    assert enrollment["status"] == ENROLLMENT_SUSPENDED
    assert_cents(enrollment["accrued_payment_cents"], 0)
    settled = get_success_data(scenario.api.get_grower_payment(payment["id"], ADMIN_HEADERS))
    assert settled["status"] == PAYMENT_CLAWED_BACK
    grower = scenario.reload_grower()
    assert grower["status"] == GROWER_SUSPENDED
    assert grower["reversal_count"] == 1
    assert_cents(grower["outstanding_clawback_cents"], 792000)
    # 1584000 would book the liability once per clawed-back payment instead of once per event.
    assert grower["outstanding_clawback_cents"] != 1584000
    assert_acres(grower["total_enrolled_acres"], 5000.00)
    assert scenario.reload_field()["status"] == FIELD_SUSPENDED
    ledger = get_success_data(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, ADMIN_HEADERS)
    )
    assert_cents(ledger["paid_total_cents"], 0)
    assert_cents(ledger["clawed_back_total_cents"], 3550000)
    assert_cents(ledger["outstanding_clawback_cents"], 792000)
    assert_credits(ledger["buffer_contributed_credits"], 199)
    assert_credits(ledger["lifetime_credits_issued"], 1217)
