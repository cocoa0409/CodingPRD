"""Disposition gating by site release posture: deviations, inspections, priority pairs."""
from test_helpers import (
    ApiErrorId, USER_IDS,
    validate_success, validate_error,
    setup_batch_downstream, setup_batch_pending_disposition, setup_released_batch,
    create_deviation_entity, create_inspection_entity, inspection_action,
    create_train_entity, create_campaign_entity, advance_campaign, seed_campaign,
    create_batch_entity, record_and_verify_test, advance_batch, submit_batch_for_review,
    disposition_batch, get_batch_entity,
    make_quality_assurance_reviewer_headers,
)

_QA1 = USER_IDS["reviewer"]
_QA3 = USER_IDS["reviewer_3"]
_FINDING = [{"severity": "CRITICAL", "note": "Data integrity gaps in batch records"}]


def _frozen_mid_process_env():
    """Batch in DOWNSTREAM (IN_TESTING) with two OPEN CRITICAL deviations: site FROZEN."""
    env = setup_batch_downstream()
    create_deviation_entity(env["batch"]["id"], kind="PROCESS", severity="CRITICAL",
                            description="Agitation anomaly under investigation")
    create_deviation_entity(env["batch"]["id"], kind="PROCESS", severity="CRITICAL",
                            description="Temperature probe drift under investigation")
    return env


def test_disposition_state_error_precedes_posture_freeze(api, platform_admin_headers):
    """PRD §3.5: "The disposition decision itself carries a `decision` of `RELEASED` or `REJECTED` with a free-text `rationale`, and is admitted only from `PENDING_DISPOSITION` — the state check runs before every business check below (`ERR_INVALID_BATCH_STATE`, HTTP 409)."
    PRD §2.10: "On a disposition request, the batch state check runs first — state errors precede all business checks — and the segregation-of-duties check is the first business rule evaluated."

    Design: Difficulty/priority_pair_validation_conflict/disposition_state_error_precedes_posture_freeze
    """
    env = _frozen_mid_process_env()
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["release_posture"] == "FROZEN", "the posture gate WOULD also fail"
    headers = make_quality_assurance_reviewer_headers(_QA3)
    resp = api.disposition_batch(env["batch"]["id"], {
        "decision": "RELEASED",
        "rationale": "Attempted release while frozen and mid-process"}, headers)
    error_data = validate_error(resp, ApiErrorId.ERR_INVALID_BATCH_STATE)
    assert error_data["error_id"] != "ERR_SITE_RELEASE_FROZEN"


def test_disposition_state_error_leaves_batch_untouched(api, platform_admin_headers):
    """PRD §3.5: "admitted only from `PENDING_DISPOSITION` — the state check runs before every business check below (`ERR_INVALID_BATCH_STATE`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/disposition_state_error_precedes_posture_freeze
    """
    env = _frozen_mid_process_env()
    batch_id = env["batch"]["id"]
    version_before = env["batch"]["version"]
    headers = make_quality_assurance_reviewer_headers(_QA3)
    validate_error(api.disposition_batch(batch_id, {
        "decision": "RELEASED", "rationale": "Attempted release while frozen"}, headers),
        ApiErrorId.ERR_INVALID_BATCH_STATE)
    batch = get_batch_entity(batch_id)
    assert batch["quality_status"] == "IN_TESTING", "no partial mutation"
    assert batch["version"] == version_before
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["release_posture"] == "FROZEN"


def _inspection_gated_env(api):
    """Batch at PENDING_DISPOSITION with an FDA inspection carrying one CRITICAL finding."""
    env = setup_batch_pending_disposition()
    inspection = create_inspection_entity(env["site"]["id"], authority="FDA")
    inspection_action(inspection["id"], "ISSUE_FINDINGS", findings=_FINDING)
    return env, inspection


def test_disposition_blocked_while_critical_finding_open(api, platform_admin_headers):
    """PRD §3.5: "then, for batches whose campaign serves `COMMERCIAL` demand only, the site release posture must not be `FROZEN` (`ERR_SITE_RELEASE_FROZEN`, HTTP 409)"
    PRD §3.7: "the site's posture is recomputed per §2.9 — a single critical finding is enough to freeze the site."

    Design: Difficulty/cross_entity_state_dependency/disposition_gated_by_inspection_driven_posture
    """
    env, _inspection = _inspection_gated_env(api)
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["open_critical_finding_count"] == 1
    assert site["release_posture"] == "FROZEN"
    headers = make_quality_assurance_reviewer_headers(_QA1)
    resp = api.disposition_batch(env["batch"]["id"], {
        "decision": "RELEASED",
        "rationale": "Attempted release during open critical finding"}, headers)
    validate_error(resp, ApiErrorId.ERR_SITE_RELEASE_FROZEN)


def test_disposition_unblocked_after_inspection_close(api, platform_admin_headers):
    """PRD §3.7: "the inspection moves to `CLOSED`, its `open_critical_finding_count` resets to zero, and the site's posture is recomputed once more. A frozen site thaws only when its counters actually fall below the thresholds"

    Design: Difficulty/cross_entity_state_dependency/disposition_gated_by_inspection_driven_posture
    """
    env, inspection = _inspection_gated_env(api)
    inspection_action(inspection["id"], "CLOSE",
                      response_summary="Remediation plan accepted by the agency")
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["open_critical_finding_count"] == 0
    assert site["release_posture"] == "CLEAR"
    released = disposition_batch(env["batch"]["id"], decision="RELEASED",
                                 rationale="All specifications met; posture clear")
    assert released["quality_status"] == "RELEASED"


def _two_batch_threshold_env():
    """Batch A (TR-1) fully RELEASED; batch B (TR-2, same site) at PENDING_DISPOSITION."""
    env = setup_released_batch()
    train2 = create_train_entity(env["site"]["id"], train_code="TR-2", capacity_liters=2000,
                                 supported_molecule_types=["MONOCLONAL_ANTIBODY"])
    camp_b = create_campaign_entity(train2["id"], env["product"]["id"])
    advance_campaign(camp_b["id"], "ALLOCATED")
    seed_campaign(camp_b["id"], stage_durations=(10,),
                  seed_start_utc="2026-10-02T04:00:00Z")
    advance_campaign(camp_b["id"], "PRODUCTION_IN_PROGRESS")
    batch_b = create_batch_entity(camp_b["id"], lot_number="LOT-B2")
    record_and_verify_test(batch_b["id"], batch_version=batch_b["version"],
                           test_type="CELL_VIABILITY", phase="UPSTREAM",
                           measured_value=91.0, unit="PCT", spec_min=80.0, spec_max=100.0)
    advance_batch(batch_b["id"], "DOWNSTREAM")
    record_and_verify_test(batch_b["id"], test_type="TITER", phase="DOWNSTREAM",
                           measured_value=2.2, unit="G/L", spec_min=2.0, spec_max=4.0)
    advance_batch(batch_b["id"], "PROCESS_COMPLETE")
    submit_batch_for_review(batch_b["id"])
    return env, batch_b


def _post_release_critical(env, description):
    headers = make_quality_assurance_reviewer_headers(_QA1)
    return create_deviation_entity(env["batch"]["id"], kind="PROCESS", severity="CRITICAL",
                                   description=description, headers=headers)


def test_one_open_critical_deviation_is_conditional_not_frozen(api, platform_admin_headers):
    """PRD §2.9: "It is `CONDITIONAL` when `open_critical_deviation_count` is exactly 1 (and no critical finding is open). It is `CLEAR` otherwise."

    Design: Difficulty/boundary_precision_check/critical_deviation_count_threshold_boundary
    """
    env, _batch_b = _two_batch_threshold_env()
    _post_release_critical(env, "Post-release audit finding on batch A")
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["open_critical_deviation_count"] == 1
    assert site["release_posture"] == "CONDITIONAL", "one open CRITICAL does not freeze"


def test_second_open_critical_deviation_freezes_and_blocks_release(api,
                                                                   platform_admin_headers):
    """PRD §2.9: "The site is `FROZEN` when `open_critical_finding_count` is at least 1 or `open_critical_deviation_count` is at least 2 — the threshold is inclusive, so exactly two open critical deviations freeze the site."
    PRD §3.5: "the site release posture must not be `FROZEN` (`ERR_SITE_RELEASE_FROZEN`, HTTP 409)"

    Design: Difficulty/boundary_precision_check/critical_deviation_count_threshold_boundary
    """
    env, batch_b = _two_batch_threshold_env()
    _post_release_critical(env, "Post-release audit finding on batch A")
    _post_release_critical(env, "Second post-release audit finding on batch A")
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["open_critical_deviation_count"] == 2
    assert site["release_posture"] == "FROZEN"
    headers = make_quality_assurance_reviewer_headers(_QA1)
    resp = api.disposition_batch(batch_b["id"], {
        "decision": "RELEASED",
        "rationale": "Attempted release under frozen posture"}, headers)
    validate_error(resp, ApiErrorId.ERR_SITE_RELEASE_FROZEN)
    assert get_batch_entity(batch_b["id"])["quality_status"] == "PENDING_DISPOSITION"
