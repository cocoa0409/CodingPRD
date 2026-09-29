"""The consistency model: every cascade has landed by the time the response is written.

One test walks the two largest cascades in the system — baseline approval and issuance — and
reads every denormalised figure they touch exactly once, immediately afterwards.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import assert_acres
from test_helpers.constants import (
    BASELINE_APPROVED,
    BASELINE_HISTORICAL_DATA,
    CROP_YEAR_2026,
    ENROLLMENT_ACTIVE,
    EVIDENCE_FARM_RECORD,
    FIELD_ENROLLED,
    METHOD_MODEL,
    OPINION_POSITIVE,
    PAYMENT_ACCRUED,
    PAYMENT_MODEL_PER_CREDIT,
    PERMANENCE_IN_COMPLIANCE,
    RUN_VERIFIED,
)
from test_helpers.test_users import (
    ADMIN_BASELINE_HEADERS,
    ADMIN_BASELINE_ID,
    ADMIN_HEADERS,
)


def test_both_cascades_are_fully_landed_in_the_very_next_read(scenario):
    """Baseline approval activates the enrollment, enrolls the field and moves the grower's
    acreage in one write, and issuance mints the batch, the payment, the pool movement and both
    credit aggregates in another — each visible on the first read that follows.

    PRD §2.9: "There is no queue and no eventual consistency: by the time the response is
    written, every hop has landed and every touched row has a refreshed `updated_at` and an
    incremented `version`."

    PRD §3.4: "First, the enrollment moves `ACCEPTED → ACTIVE`, its `permanence_status` moves
    `NOT_STARTED → IN_COMPLIANCE`, and the acting identifier is also recorded on the enrollment
    as `baseline_approval_admin_id`. Second, *because* the enrollment became `ACTIVE`, its field
    moves `MAPPED → ENROLLED`. Third, *because* the field became `ENROLLED`, the grower's
    `total_enrolled_acres` increases by that field's `mapped_acres`."

    Design: Corner/consistency_model/approval_and_issuance_cascades_are_visible_immediately_in_the_next_read
    """
    scenario.accepted_enrollment(standard_overrides={"telemetry_required": False})
    scenario.accredit_body()
    assert_acres(scenario.reload_grower()["total_enrolled_acres"], 0.00)
    proposed = scenario.propose_baseline(BASELINE_HISTORICAL_DATA)

    approved = validate_success(
        scenario.api.approve_baseline(proposed["id"], None, ADMIN_BASELINE_HEADERS), 200
    )
    assert approved["status"] == BASELINE_APPROVED
    assert approved["approved_by_admin_id"] == ADMIN_BASELINE_ID

    # First read after the approval: all three hops already landed.
    enrollment = scenario.reload_enrollment()
    assert enrollment["status"] == ENROLLMENT_ACTIVE
    assert enrollment["permanence_status"] == PERMANENCE_IN_COMPLIANCE
    assert enrollment["baseline_approval_admin_id"] == ADMIN_BASELINE_ID
    field = scenario.reload_field()
    assert field["status"] == FIELD_ENROLLED
    assert_acres(scenario.reload_grower()["total_enrolled_acres"], 1000.00)

    observed = enrollment["version"]
    scenario.passed_packet(source=EVIDENCE_FARM_RECORD)
    scenario.create_run(METHOD_MODEL, CROP_YEAR_2026, expected_enrollment_version=observed)
    scenario.submit_run()
    scenario.commission_verification(
        site_visit_start="2026-07-01", site_visit_end="2026-07-03"
    )
    scenario.opine(OPINION_POSITIVE)
    assert scenario.reload_run()["status"] == RUN_VERIFIED

    batch = scenario.issue()
    assert batch["gross_credits"] == 283
    assert batch["buffer_credits"] == 51
    assert batch["issued_credits"] == 232
    assert batch["serial_start"] == 1
    assert batch["serial_end"] == 232

    # The cascade-minted payment is discoverable on the first list read after issuance.
    payments, meta = validate_paginated(
        scenario.api.list_grower_payments(
            {"enrollment_id": scenario.enrollment_id}, ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert payments[0]["status"] == PAYMENT_ACCRUED
    assert payments[0]["payment_model"] == PAYMENT_MODEL_PER_CREDIT
    assert payments[0]["net_amount_cents"] == 306240
    assert payments[0]["credit_batch_id"] == batch["id"]

    pool = scenario.buffer_pool()
    assert pool["balance_credits"] == 51
    assert pool["contributed_total"] == 51
    assert pool["outstanding_issued_credits"] == 232
    assert pool["required_reserve_credits"] == 12
    assert pool["next_serial_number"] == 233

    assert scenario.reload_grower()["lifetime_credits_issued"] == 232
    settled = scenario.reload_enrollment()
    assert settled["credits_issued_total"] == 232
    assert settled["accrued_payment_cents"] == 306240
