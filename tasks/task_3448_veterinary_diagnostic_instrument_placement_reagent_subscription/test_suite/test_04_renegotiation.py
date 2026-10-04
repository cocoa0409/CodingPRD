"""The renegotiation loop: caseload gate, proposals, resolution, OCC (PRD §2.8, §3.6)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    api_client,
    approve_agreement,
    assert_version_incremented,
    create_clinic,
    draft_reagent_commitment_agreement,
    get_agreement,
    list_commitment_periods,
    make_clinic_manager_headers,
    request_renegotiation,
    resolve_renegotiation,
    resolve_renegotiation_payload,
    setup_agreement_in_renegotiation,
    setup_agreement_with_closed_period,
    setup_clinic_with_active_reagent_commitment,
    update_caseload,
    validate_error,
)

_FINANCE = TEST_USERS["finance_reviewer_headers"]


def test_renegotiation_cycle_loops_twice(api):
    """PRD §3.6: "A granted request moves the agreement `ACTIVE` →
    `RENEGOTIATION` and computes the advisory `proposed_minimum_cents`".
    PRD §3.6: "On rejection, no terms change and no bills are waived." PRD
    §3.6: "Either way, `proposed_minimum_cents` is cleared, the agreement
    returns to `ACTIVE`, and its `version` increments by 1." — after a
    rejection the machine is back in ACTIVE, so a second request is legal.

    Design: Difficulty/non_linear_state_machine/placement_agreement_renegotiation_cycle
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])
    approve_agreement(draft["id"])
    activate_agreement(draft["id"])
    update_caseload(clinic["id"], 1400)

    first = request_renegotiation(draft["id"], clinic["id"])
    assert first["status"] == "RENEGOTIATION"
    assert first["proposed_minimum_cents"] == 140000  # 100000 * 1400/1000

    rejected = resolve_renegotiation(draft["id"], False, first["version"])
    assert rejected["status"] == "ACTIVE"
    assert rejected["monthly_minimum_cents"] == 100000
    assert rejected["proposed_minimum_cents"] is None

    # A linear machine could not re-enter RENEGOTIATION here.
    second = request_renegotiation(draft["id"], clinic["id"])
    assert second["status"] == "RENEGOTIATION"

    accepted = resolve_renegotiation(
        draft["id"], True, second["version"], new_minimum_cents=140000
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["monthly_minimum_cents"] == 140000
    assert accepted["proposed_minimum_cents"] is None


def test_renegotiation_cycle_version_marks_each_lap(api):
    """PRD §2.5: "`version` is an integer that increments by 1 on every
    mutation of the resource". PRD §3.6: "every still-`OPEN` commitment
    period's `minimum_cents` is rewritten to match". Each lap of the loop is
    one mutation, so the version counter records both laps.

    Design: Difficulty/non_linear_state_machine/placement_agreement_renegotiation_cycle
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])
    approved = approve_agreement(draft["id"])
    assert_version_incremented(draft["version"], approved["version"])
    activated = activate_agreement(draft["id"])
    assert_version_incremented(approved["version"], activated["version"])
    update_caseload(clinic["id"], 1400)

    first = request_renegotiation(draft["id"], clinic["id"])
    assert_version_incremented(activated["version"], first["version"])
    rejected = resolve_renegotiation(draft["id"], False, first["version"])
    assert_version_incremented(first["version"], rejected["version"])
    second = request_renegotiation(draft["id"], clinic["id"])
    assert_version_incremented(rejected["version"], second["version"])
    accepted = resolve_renegotiation(
        draft["id"], True, second["version"], new_minimum_cents=140000
    )
    assert_version_incremented(second["version"], accepted["version"])
    assert accepted["version"] == draft["version"] + 6

    periods = list_commitment_periods(draft["id"])
    assert all(p["minimum_cents"] == 140000 for p in periods)
    assert periods[0]["period_status"] == "OPEN"


def test_caseload_delta_below_thirty_percent_rejected(api):
    """PRD §3.6: "The gate is a material-drift test: the absolute deviation
    between the clinic's `caseload_current_tests` and the agreement's
    `baseline_caseload_snapshot` must reach at least 0.30 of the snapshot
    (`RENEGOTIATION_CASELOAD_DELTA_PCT`)." PRD §3.6: "a smaller deviation is
    rejected with `ERR_RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT` (HTTP
    422)." — 1299 vs snapshot 1000 is a 0.299 deviation.

    Design: Difficulty/boundary_precision_check/caseload_delta_exactly_thirty_percent
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    update_caseload(clinic["id"], 1299)

    resp = api_client.request_renegotiation(
        agreement["id"], make_clinic_manager_headers(clinic["id"])
    )
    validate_error(resp, ApiErrorId.ERR_RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT)
    assert get_agreement(agreement["id"])["status"] == "ACTIVE"


def test_caseload_delta_exactly_thirty_percent_accepted(api):
    """PRD §3.6: "The boundary is inclusive — a deviation of exactly thirty
    percent qualifies". 1300 vs snapshot 1000 is exactly 0.30; the advisory
    proposal is round_half_up(100000 * 1.30) = 130000 per "the agreement's
    `monthly_minimum_cents` is scaled by the ratio of the clinic's current
    `caseload_current_tests` to the `baseline_caseload_snapshot`".

    Design: Difficulty/boundary_precision_check/caseload_delta_exactly_thirty_percent
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    update_caseload(clinic["id"], 1300)

    granted = request_renegotiation(agreement["id"], clinic["id"])
    assert granted["status"] == "RENEGOTIATION"
    assert granted["proposed_minimum_cents"] == 130000


def test_renegotiation_reject_restores_active_and_terms(api):
    """PRD §3.6: "On rejection, no terms change and no bills are waived."
    PRD §3.6: "Either way, `proposed_minimum_cents` is cleared, the agreement
    returns to `ACTIVE`, and its `version` increments by 1."

    Design: Difficulty/compensating_invariant/renegotiation_reject_conserves_terms_and_billing
    """
    scenario = setup_agreement_with_closed_period()  # 80000c bill ISSUED
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    update_caseload(clinic["id"], 1400)
    requested = request_renegotiation(agreement["id"], clinic["id"])
    assert requested["status"] == "RENEGOTIATION"

    resolved = resolve_renegotiation(agreement["id"], False, requested["version"])
    assert resolved["status"] == "ACTIVE"
    assert resolved["monthly_minimum_cents"] == 100000  # unchanged by rejection
    assert resolved["proposed_minimum_cents"] is None
    assert_version_incremented(requested["version"], resolved["version"])


def test_renegotiation_reject_conserves_billed_revenue(api):
    """PRD §3.6: "On rejection, no terms change and no bills are waived."
    PRD §3.5: an issued bill persists until "payment recording" or waiver —
    a rejected renegotiation is neither, so the ISSUED bill and both
    cumulative ledgers survive the round trip untouched.

    Design: Difficulty/compensating_invariant/renegotiation_reject_conserves_terms_and_billing
    """
    scenario = setup_agreement_with_closed_period()  # 80000c bill ISSUED
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    update_caseload(clinic["id"], 1400)
    requested = request_renegotiation(agreement["id"], clinic["id"])
    resolve_renegotiation(agreement["id"], False, requested["version"])

    after = get_agreement(agreement["id"])
    assert after["cumulative_billed_cents"] == 80000
    assert after["cumulative_unpaid_billed_cents"] == 80000
    period = list_commitment_periods(agreement["id"])[0]
    assert period["billing_status"] == "ISSUED"
    assert period["billed_cents"] == 80000


def test_renegotiation_proposal_hits_minimum_floor(api):
    """PRD §3.6: "the product-ratio is rounded half up to whole cents, and
    the result is then raised to the 50000-cent floor if the scaling fell
    below it." — caseload 400 vs snapshot 1000 scales 100000 to 40000, and
    the floor engages.

    Design: Corner/calculations/renegotiation_proposal_hits_minimum_floor
    """
    scenario = setup_agreement_in_renegotiation(current_caseload=400)
    agreement = scenario["agreement"]
    assert agreement["status"] == "RENEGOTIATION"
    assert agreement["proposed_minimum_cents"] == 50000


def test_occ_resolve_renegotiation_stale_version_rejected(api):
    """PRD §2.8: "If that value does not equal the agreement's current
    `version` — because another writer has advanced the agreement since the
    client read it — the request is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) and nothing is mutated".

    Design: Corner/cross_cutting_layers/occ_resolve_renegotiation_stale_version_rejected
    """
    scenario = setup_agreement_in_renegotiation()
    agreement = scenario["agreement"]
    observed = agreement["version"]

    stale = api_client.resolve_renegotiation(
        agreement["id"],
        resolve_renegotiation_payload(False, observed - 1),
        _FINANCE,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)

    after = get_agreement(agreement["id"])
    assert after["status"] == "RENEGOTIATION"
    assert after["version"] == observed  # nothing mutated

    resolved = resolve_renegotiation(agreement["id"], False, observed)
    assert resolved["status"] == "ACTIVE"
    assert_version_incremented(observed, resolved["version"])
