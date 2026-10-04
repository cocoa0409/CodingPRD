"""Comparability study workflow: equivalence math, rework loop, filing gate on release."""
from test_helpers import (
    ApiErrorId, TEST_USERS, USER_IDS,
    validate_success, validate_error, validate_paginated,
    setup_batch_downstream, setup_batch_process_complete,
    record_and_verify_test, advance_batch, submit_batch_for_review, disposition_batch,
    get_batch_entity, create_study_entity, study_action,
    make_quality_assurance_reviewer_headers,
)

_OUTLIER_BASELINE = [98.0, 98.2, 97.8, 98.1, 85.0]
_TIGHT_BASELINE = [98.0, 98.2, 97.8]


def _purity_candidate_env(purity=99.5, spec=(95.0, 100.0)):
    """Batch at PROCESS_COMPLETE carrying a VERIFIED DOWNSTREAM PURITY test."""
    env = setup_batch_downstream()
    batch_id = env["batch"]["id"]
    version = env["batch"]["version"]
    for value in (2.4, 2.6):
        _test, version = record_and_verify_test(
            batch_id, batch_version=version, test_type="TITER", phase="DOWNSTREAM",
            measured_value=value, unit="G/L", spec_min=2.0, spec_max=4.0)
    record_and_verify_test(batch_id, batch_version=version, test_type="PURITY",
                           phase="DOWNSTREAM", measured_value=purity, unit="PCT",
                           spec_min=spec[0], spec_max=spec[1])
    env["batch"] = advance_batch(batch_id, "PROCESS_COMPLETE")
    return env


def test_comparability_single_pass_outlier_exclusion(api):
    """PRD §3.7: "First, the mean and the population standard deviation (dividing by the count of values, not the count minus one) are computed over the *full* baseline, including any values that will later be excluded. Second, baseline values lying outside the band from 1.5 standard deviations below that mean to 1.5 standard deviations above it are excluded. Third, the mean of the surviving baseline values is recomputed exactly once, rounded half-up to four decimal places, and stored as `baseline_mean`; the standard deviation is *not* recomputed, and no second exclusion pass occurs."

    Design: Difficulty/combinatorial_formula/comparability_single_pass_outlier_exclusion
    """
    env = _purity_candidate_env()
    study = create_study_entity(env["product"]["id"], [env["batch"]["id"]],
                                change_type="PROCESS_CHANGE",
                                baseline_attribute_values=_OUTLIER_BASELINE)
    study_action(study["id"], "APPROVE_PROTOCOL")
    result = study_action(study["id"], "RECORD_ASSESSMENT")
    assert result["status"] == "COMPARABLE"
    assert result["baseline_mean"] == 98.025, "85.0 excluded by the single pass, mean frozen"
    assert result["equivalence_margin"] == 2.9408, "max(1.5, 0.03 x 98.025), 4-decimal"


def test_comparability_margin_uses_recomputed_mean_not_original(api):
    """PRD §3.7: "Fourth, the `equivalence_margin` is the larger of the absolute margin 1.5 and the relative margin of 3 percent of the baseline mean (0.03 multiplied by `baseline_mean`), rounded half-up to four decimal places, and stored."
    PRD §3.7: "Sixth, the verdict: when every candidate value lies within the inclusive band from `baseline_mean` minus `equivalence_margin` to `baseline_mean` plus `equivalence_margin`, the study moves to `COMPARABLE`; otherwise it moves to `NOT_COMPARABLE`"

    Design: Difficulty/combinatorial_formula/comparability_single_pass_outlier_exclusion
    """
    env = _purity_candidate_env()
    study = create_study_entity(env["product"]["id"], [env["batch"]["id"]],
                                change_type="PROCESS_CHANGE",
                                baseline_attribute_values=_OUTLIER_BASELINE)
    study_action(study["id"], "APPROVE_PROTOCOL")
    result = study_action(study["id"], "RECORD_ASSESSMENT")
    assert result["equivalence_margin"] == 2.9408
    assert result["equivalence_margin"] != 2.8626, "0.03 x mu0 95.42 is NOT conformant"
    # Candidate 99.5 lies inside [95.0842, 100.9658] -> COMPARABLE.
    assert result["status"] == "COMPARABLE"


def test_study_not_comparable_rework_cycle(api):
    """PRD §3.7: "Protocol approval moves the study from `PLANNED` to `PROTOCOL_APPROVED`, and the same action also serves as the rework loop from `NOT_COMPARABLE` back to `PROTOCOL_APPROVED`; from any other status it is rejected with `ERR_INVALID_STUDY_STATE` (HTTP 409)."

    Design: Corner/state_machines/study_not_comparable_rework_cycle
    """
    env = _purity_candidate_env(purity=90.0, spec=(85.0, 95.0))
    study = create_study_entity(env["product"]["id"], [env["batch"]["id"]],
                                change_type="SITE_TRANSFER",
                                baseline_attribute_values=_TIGHT_BASELINE)
    study_action(study["id"], "APPROVE_PROTOCOL")
    result = study_action(study["id"], "RECORD_ASSESSMENT")
    assert result["status"] == "NOT_COMPARABLE", "candidate 90.0 outside [95.06, 100.94]"
    assert result["equivalence_margin"] == 2.94, "max(1.5, 0.03 x 98.0)"
    rework = study_action(study["id"], "APPROVE_PROTOCOL")
    assert rework["status"] == "PROTOCOL_APPROVED"


def test_study_assessment_without_candidate_purity_rejected(api, platform_admin_headers):
    """PRD §3.7: "if any candidate batch lacks such a test, the assessment is rejected with `ERR_STUDY_DATA_MISSING` (HTTP 409) before any verdict."

    Design: Corner/validations/study_assessment_without_candidate_purity_rejected
    """
    env = setup_batch_process_complete()  # VERIFIED DOWNSTREAM TITER only, no PURITY
    study = create_study_entity(env["product"]["id"], [env["batch"]["id"]],
                                change_type="SCALE_UP",
                                baseline_attribute_values=_TIGHT_BASELINE)
    study_action(study["id"], "APPROVE_PROTOCOL")
    resp = api.study_action(study["id"], {"action": "RECORD_ASSESSMENT"},
                            TEST_USERS["regulatory_affairs_specialist_headers"])
    validate_error(resp, ApiErrorId.ERR_STUDY_DATA_MISSING)
    rows, _m = validate_paginated(
        api.list_comparability_studies(env["product"]["id"], platform_admin_headers))
    assert rows[0]["id"] == study["id"] and rows[0]["status"] == "PROTOCOL_APPROVED"


def test_study_submit_filing_before_assessment_rejected(api,
                                                        regulatory_affairs_specialist_headers):
    """PRD §3.7: "submitting the filing moves a `COMPARABLE` study to `FILED` (any other status, `ERR_INVALID_STUDY_STATE`)"

    Design: Corner/validations/study_submit_filing_before_assessment_rejected
    """
    env = setup_batch_downstream()
    study = create_study_entity(env["product"]["id"], [env["batch"]["id"]],
                                change_type="PROCESS_CHANGE",
                                baseline_attribute_values=_TIGHT_BASELINE)
    resp = api.study_action(study["id"], {"action": "SUBMIT_FILING", "authority": "FDA"},
                            regulatory_affairs_specialist_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STUDY_STATE)


def _release_gated_env():
    """Batch at PENDING_DISPOSITION with PURITY 99.5 and a PLANNED study on the product."""
    env = _purity_candidate_env()
    submit_batch_for_review(env["batch"]["id"])
    study = create_study_entity(env["product"]["id"], [env["batch"]["id"]],
                                change_type="PROCESS_CHANGE",
                                baseline_attribute_values=_OUTLIER_BASELINE)
    return env, study


def test_commercial_release_blocked_while_study_not_filed(api):
    """PRD §3.5: "and finally, for `COMMERCIAL` only, if the product has at least one comparability study, the most recently created study must be in `FILED` status (`ERR_COMPARABILITY_NOT_ESTABLISHED`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/commercial_release_gated_by_comparability_filing
    """
    env, _study = _release_gated_env()
    headers = make_quality_assurance_reviewer_headers(USER_IDS["reviewer"])
    resp = api.disposition_batch(env["batch"]["id"], {
        "decision": "RELEASED",
        "rationale": "Attempted release before comparability filing"}, headers)
    validate_error(resp, ApiErrorId.ERR_COMPARABILITY_NOT_ESTABLISHED)
    assert get_batch_entity(env["batch"]["id"])["quality_status"] == "PENDING_DISPOSITION"


def test_commercial_release_unblocked_after_study_filed(api):
    """PRD §3.7: "This status is exactly what the commercial release gate of §3.5 looks for: when a product has any comparability study at all, only a `FILED` most-recent study lets a commercial batch release proceed."

    Design: Difficulty/cross_entity_state_dependency/commercial_release_gated_by_comparability_filing
    """
    env, study = _release_gated_env()
    study_action(study["id"], "APPROVE_PROTOCOL")
    assessed = study_action(study["id"], "RECORD_ASSESSMENT")
    assert assessed["status"] == "COMPARABLE", "candidate 99.5 inside [95.0842, 100.9658]"
    filed = study_action(study["id"], "SUBMIT_FILING", authority="FDA")
    assert filed["status"] == "FILED"
    released = disposition_batch(env["batch"]["id"], decision="RELEASED",
                                 rationale="Comparability filed; all gates pass")
    assert released["quality_status"] == "RELEASED"
