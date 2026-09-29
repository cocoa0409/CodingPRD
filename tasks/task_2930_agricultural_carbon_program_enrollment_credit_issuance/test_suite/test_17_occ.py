"""Optimistic concurrency on the three operations that declare a version field.

A second baseline proposal and a repeat draft run are both legitimate product operations, so
only the version gate can distinguish a fresh client from a stale one; and a batch cancellation
must not be built on a snapshot taken before the registry moved the row.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_DUPLICATE_QUANTIFICATION_RUN,
    ERR_STALE_BATCH_VERSION,
    ERR_STALE_ENROLLMENT_VERSION,
)
from test_helpers.constants import (
    BASELINE_HISTORICAL_DATA,
    BASELINE_MODELED,
    BASELINE_PROPOSED,
    BASELINE_SUPERSEDED,
    CROP_YEAR_2026,
    EVIDENCE_FARM_RECORD,
    ISSUANCE_CANCELLED,
    ISSUANCE_ISSUED,
    METHOD_MODEL,
    REGISTRY_LISTED,
    RUN_DRAFT,
)
from test_helpers.factories import (
    baseline_payload,
    cancellation_payload,
    quantification_run_payload,
)
from test_helpers.test_users import (
    ADMIN_BASELINE_HEADERS,
    ADMIN_HEADERS,
    REGISTRY_HEADERS,
)

CANCEL_REASON = "issued against the wrong vintage"


def test_a_legitimate_second_proposal_still_needs_the_current_version(scenario):
    """Superseding the incumbent proposal is a legal operation, so the screening-era version is
    the only thing that can refuse it; the refusal leaves the incumbent proposed and the
    version untouched, and the identical retry supersedes it.

    PRD §2.8: "The state machine alone cannot protect this operation, because a second proposal
    is entirely legitimate on its own terms — it supersedes the incumbent proposal."

    PRD §3.4: "A proposal starts with `status` of `PROPOSED`, a null `approved_by_admin_id` and
    a null `rejection_note`, and proposing one increments the parent enrollment's `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_enrollment_version_refuses_a_baseline_proposal_that_is_otherwise_legitimate
    """
    scenario.accepted_enrollment()
    screening_era = scenario.enrollment_version
    incumbent = scenario.propose_baseline(
        BASELINE_HISTORICAL_DATA, expected_enrollment_version=screening_era
    )
    assert incumbent["status"] == BASELINE_PROPOSED

    validate_error(
        scenario.api.propose_baseline(
            scenario.enrollment_id,
            baseline_payload(screening_era, BASELINE_MODELED),
            ADMIN_BASELINE_HEADERS,
        ),
        ERR_STALE_ENROLLMENT_VERSION,
        412,
    )

    rows, meta = validate_paginated(
        scenario.api.list_baselines({"enrollment_id": scenario.enrollment_id}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == incumbent["id"]
    assert rows[0]["status"] == BASELINE_PROPOSED
    assert rows[0]["method"] == BASELINE_HISTORICAL_DATA

    current = scenario.reload_enrollment()["version"]
    # The first proposal's own bump, and nothing from the rejected call.
    assert current == screening_era + 1

    successor = validate_success(
        scenario.api.propose_baseline(
            scenario.enrollment_id,
            baseline_payload(current, BASELINE_MODELED),
            ADMIN_BASELINE_HEADERS,
        ),
        201,
    )
    assert successor["method"] == BASELINE_MODELED
    assert successor["status"] == BASELINE_PROPOSED
    assert get_success_data(
        scenario.api.get_baseline(incumbent["id"], ADMIN_HEADERS)
    )["status"] == BASELINE_SUPERSEDED
    assert scenario.reload_enrollment()["version"] == current + 1


def test_the_version_gate_answers_before_the_duplicate_run_key(scenario):
    """One request breaks the version gate and the uniqueness key at once; the version gate
    answers, and only the refreshed retry is allowed to reach the duplicate-run refusal.

    PRD §2.10: "Where the endpoint declares a version field (§2.8), the supplied value equals
    the parent's current `version` → otherwise `ERR_STALE_ENROLLMENT_VERSION` or
    `ERR_STALE_BATCH_VERSION` (412)."

    PRD §3.6: "At most one non-rejected run may exist per enrollment and `crop_year`; a second
    reports `ERR_DUPLICATE_QUANTIFICATION_RUN`."

    Design: Corner/cross_cutting_complexity_layers/stale_enrollment_version_is_reported_before_duplicate_run_detection
    """
    scenario.active_enrollment(standard_overrides={"telemetry_required": False})
    scenario.passed_packet(source=EVIDENCE_FARM_RECORD)
    observed = scenario.enrollment_version
    incumbent = scenario.create_run(
        METHOD_MODEL, CROP_YEAR_2026, expected_enrollment_version=observed
    )
    assert incumbent["status"] == RUN_DRAFT

    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, scenario.baseline_id, observed, CROP_YEAR_2026,
                METHOD_MODEL,
            ),
            ADMIN_HEADERS,
        ),
        ERR_STALE_ENROLLMENT_VERSION,
        412,
    )

    refreshed = scenario.reload_enrollment()["version"]
    assert refreshed == observed + 1

    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, scenario.baseline_id, refreshed, CROP_YEAR_2026,
                METHOD_MODEL,
            ),
            ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_QUANTIFICATION_RUN,
        409,
    )

    runs, meta = validate_paginated(
        scenario.api.list_quantification_runs(
            {"enrollment_id": scenario.enrollment_id}, ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert runs[0]["id"] == incumbent["id"]
    assert runs[0]["status"] == RUN_DRAFT
    assert scenario.reload_enrollment()["version"] == refreshed


def test_listing_bumps_the_batch_and_strands_an_issuance_era_cancellation(scenario):
    """The registry listing advances the batch's version without moving its issuance axis, so a
    cancellation built on the issuance-era snapshot is refused; the re-read version lets the
    identical payload through, releasing the credits but not the serial numbers.

    PRD §2.8: "Listing, retirement and reversal cascades all advance a batch's `version`
    without moving its `issuance_status`, so a cancellation built on an older snapshot would
    otherwise release buffer credits from a batch whose registry position has since changed."

    PRD §3.8: "The pool's `next_serial_number` is **not** rolled back: serial numbers are never
    reused."

    Design: Corner/cross_cutting_complexity_layers/stale_batch_version_refuses_cancellation_after_listing_bumps_the_batch
    """
    scenario.issued_batch(
        standard_overrides={"telemetry_required": False},
        packet_overrides={"source": EVIDENCE_FARM_RECORD},
    )
    batch_id = scenario.batch["id"]
    issuance_era = scenario.batch["version"]

    scenario.list_batch(batch_id, registry_account_ref="REG-ACCT-OCC")

    validate_error(
        scenario.api.cancel_batch(
            batch_id,
            cancellation_payload(issuance_era, cancellation_reason=CANCEL_REASON),
            REGISTRY_HEADERS,
        ),
        ERR_STALE_BATCH_VERSION,
        412,
    )

    reread = scenario.reload_batch(batch_id)
    assert reread["issuance_status"] == ISSUANCE_ISSUED
    assert reread["registry_status"] == REGISTRY_LISTED
    assert reread["registry_account_ref"] == "REG-ACCT-OCC"
    assert reread["version"] == issuance_era + 1

    cancelled = validate_success(
        scenario.api.cancel_batch(
            batch_id,
            cancellation_payload(reread["version"], cancellation_reason=CANCEL_REASON),
            REGISTRY_HEADERS,
        ),
        200,
    )
    assert cancelled["issuance_status"] == ISSUANCE_CANCELLED
    assert cancelled["cancellation_reason"] == CANCEL_REASON
    # The registry axis is left exactly where the listing put it.
    assert cancelled["registry_status"] == REGISTRY_LISTED

    pool = scenario.buffer_pool()
    assert pool["balance_credits"] == 0
    assert pool["outstanding_issued_credits"] == 0
    assert pool["next_serial_number"] == 233
