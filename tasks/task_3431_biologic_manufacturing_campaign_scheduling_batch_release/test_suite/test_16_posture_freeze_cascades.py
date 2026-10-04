"""Depth cascades: OOS verification freezes a site; complaint confirmation quarantines."""
from test_helpers import (
    ApiErrorId, TEST_USERS, USER_IDS,
    validate_success, validate_error, validate_paginated,
    setup_master_data, setup_batch_upstream, setup_batch_downstream, setup_released_batch,
    create_train_entity, create_campaign_entity,
    create_deviation_entity, close_deviation,
    create_inspection_entity, inspection_action,
    record_test, verify_test_entity, get_batch_entity,
    create_shipment_entity, shipment_action,
    make_quality_assurance_reviewer_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_QA1_HEADERS = TEST_USERS["quality_assurance_reviewer_headers"]


def _oos_cascade_env():
    """Batch DOWNSTREAM on TR-1 with one OPEN CRITICAL PROCESS deviation (count 1);
    an unrelated PROPOSED COMMERCIAL victim campaign on TR-2 of the same site."""
    env = setup_batch_downstream()
    train2 = create_train_entity(env["site"]["id"], train_code="TR-2", capacity_liters=2000,
                                 supported_molecule_types=["MONOCLONAL_ANTIBODY"])
    victim = create_campaign_entity(train2["id"], env["product"]["id"])
    create_deviation_entity(env["batch"]["id"], kind="PROCESS", severity="CRITICAL",
                            description="Agitation spike outside validated range")
    return env, victim


def _verify_oos(env):
    """Record + verify an out-of-spec DOWNSTREAM ENDOTOXIN test (10.0 vs spec 0.0-5.0)."""
    test = record_test(env["batch"]["id"], test_type="ENDOTOXIN", phase="DOWNSTREAM",
                       measured_value=10.0, unit="EU/ML", spec_min=0.0, spec_max=5.0)
    return verify_test_entity(test["id"])


def test_oos_verify_flips_test_and_creates_system_deviation(api, platform_admin_headers):
    """PRD §3.4: "An out-of-spec test moves to `OOS_SUSPECT` with `verified_by_user_id` set, and the system immediately opens a deviation on the same batch: `kind` `OOS`, `status` `OPEN`, `linked_test_id` pointing at the test, `severity` `CRITICAL` when the test's phase is `DOWNSTREAM` and `MAJOR` otherwise, and `opened_by_user_id` the literal string `system`."

    Design: Difficulty/transitive_cascade/oos_verify_cascades_to_posture_freeze_and_campaign_preemption
    """
    env, _victim = _oos_cascade_env()
    verified = _verify_oos(env)
    assert verified["status"] == "OOS_SUSPECT"
    rows, meta = validate_paginated(
        api.list_deviations(env["batch"]["id"], platform_admin_headers))
    assert meta["total_count"] == 2, "the manual PROCESS one plus the system OOS one"
    oos = next(row for row in rows if row["kind"] == "OOS")
    assert oos["severity"] == "CRITICAL" and oos["status"] == "OPEN"
    assert oos["linked_test_id"] == verified["id"]
    assert oos["opened_by_user_id"] == "system"


def test_oos_verify_freezes_site_and_preempts_proposed_campaign(api, platform_admin_headers):
    """PRD §3.4: "When that auto-created deviation is `CRITICAL`, the site's posture is recomputed per §2.9 — including the freeze cascade into `PROPOSED` commercial campaigns."
    PRD §2.9: "The site is `FROZEN` when `open_critical_finding_count` is at least 1 or `open_critical_deviation_count` is at least 2"
    PRD §2.9: "When a site's posture transitions *into* `FROZEN`, every `COMMERCIAL` campaign still in `PROPOSED` at that site is immediately moved to `PREEMPTED` by the system."

    Design: Difficulty/transitive_cascade/oos_verify_cascades_to_posture_freeze_and_campaign_preemption
    """
    env, victim = _oos_cascade_env()
    _verify_oos(env)
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["open_critical_deviation_count"] == 2
    assert site["release_posture"] == "FROZEN"
    preempted = validate_success(api.get_campaign(victim["id"], platform_admin_headers))
    assert preempted["status"] == "PREEMPTED"
    assert get_batch_entity(env["batch"]["id"])["quality_status"] == "IN_TESTING", \
        "holds only apply from READY_FOR_REVIEW or PENDING_DISPOSITION"


def _complaint_env():
    """RELEASED batch (625000 units) with s1 PLANNED 100000 and s2 IN_TRANSIT 50000."""
    env = setup_released_batch()
    batch_id = env["batch"]["id"]
    s1 = create_shipment_entity(batch_id, quantity_units=100000,
                                destination_region="US-CHI", market_type="COMMERCIAL")
    s2 = create_shipment_entity(batch_id, quantity_units=50000,
                                destination_region="IE-DUB", market_type="COMMERCIAL")
    shipment_action(s2["id"], "SHIP")
    assert get_batch_entity(batch_id)["available_to_ship_units"] == 475000
    return env, s1, s2


def _confirm_critical_complaint(env):
    complaint = create_deviation_entity(
        env["batch"]["id"], kind="COMPLAINT", severity="CRITICAL",
        description="Pharmacy reports discolored vials from this lot",
        headers=_QA1_HEADERS)
    return close_deviation(complaint["id"], "CONFIRMED",
                           capa_summary="Recall initiated; supplier CAPA opened")


def test_confirmed_complaint_quarantines_batch_and_shipments(api):
    """PRD §3.5: "A `COMPLAINT` deviation of severity `CRITICAL` closed as `CONFIRMED` on a batch whose quality is `RELEASED` moves the batch to `QUARANTINED` and drives every shipment of that batch in `PLANNED`, `IN_TRANSIT`, or `EXCURSION_HOLD` to `QUARANTINED` as well — releasing the cold-storage occupancy of any `PLANNED` shipment caught in the cascade."

    Design: Difficulty/transitive_cascade/complaint_confirm_cascades_batch_and_shipment_quarantine
    """
    env, s1, s2 = _complaint_env()
    _confirm_critical_complaint(env)
    batch = get_batch_entity(env["batch"]["id"])
    assert batch["quality_status"] == "QUARANTINED"
    assert batch["available_to_ship_units"] == 625000, \
        "QUARANTINED shipments no longer consume sellable units"
    for shipment in (s1, s2):
        assert validate_success(api.get_shipment(shipment["id"], _ADMIN))["status"] == "QUARANTINED"


def test_confirmed_complaint_leaves_posture_clear_after_close(api, platform_admin_headers):
    """PRD §3.5: "Closing a `CRITICAL` deviation recomputes the site's posture"
    PRD §2.9: "It is `CLEAR` otherwise."

    Design: Difficulty/transitive_cascade/complaint_confirm_cascades_batch_and_shipment_quarantine
    """
    env, _s1, _s2 = _complaint_env()
    assert get_batch_entity(env["batch"]["id"])["available_to_ship_units"] == 475000
    _confirm_critical_complaint(env)
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["open_critical_deviation_count"] == 0
    assert site["release_posture"] == "CLEAR", "the closed complaint no longer counts as open"
    assert get_batch_entity(env["batch"]["id"])["available_to_ship_units"] == 625000


def test_preempted_campaign_not_resurrected_when_posture_thaws(api, platform_admin_headers):
    """PRD §2.9: "When the posture later transitions *out of* `FROZEN`, nothing is resurrected: campaigns already `PREEMPTED` stay preempted. The freeze cascade is one-way by design"

    Design: Corner/complexity_layers/preempted_campaign_not_resurrected_when_posture_thaws
    """
    env = setup_batch_upstream()
    train2 = create_train_entity(env["site"]["id"], train_code="TR-2", capacity_liters=2000,
                                 supported_molecule_types=["MONOCLONAL_ANTIBODY"])
    victim = create_campaign_entity(train2["id"], env["product"]["id"])
    dev1 = create_deviation_entity(env["batch"]["id"], kind="PROCESS", severity="CRITICAL",
                                   description="Deviation one of two")
    dev2 = create_deviation_entity(env["batch"]["id"], kind="PROCESS", severity="CRITICAL",
                                   description="Deviation two of two")
    frozen = validate_success(api.get_campaign(victim["id"], platform_admin_headers))
    assert frozen["status"] == "PREEMPTED", "posture froze at 2 open criticals and cascaded"
    close_deviation(dev1["id"], "CAPA_COMPLETED", capa_summary="CAPA for deviation one")
    close_deviation(dev2["id"], "CAPA_COMPLETED", capa_summary="CAPA for deviation two")
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["release_posture"] == "CLEAR"
    final = validate_success(api.get_campaign(victim["id"], platform_admin_headers))
    assert final["status"] == "PREEMPTED", "preemption is NOT undone by the thaw"


def test_inspection_close_before_findings_rejected(api, regulatory_affairs_specialist_headers):
    """PRD §3.7: "Closing is admitted from `FINDINGS_ISSUED` (`ERR_INVALID_INSPECTION_STATE` otherwise) and requires a `response_summary` narrative (`ERR_INVALID_REQUEST` when missing)"

    Design: Corner/validations/inspection_close_before_findings_rejected
    """
    env = setup_master_data()
    inspection = create_inspection_entity(env["site"]["id"], authority="FDA")
    resp = api.inspection_action(inspection["id"],
                                 {"action": "CLOSE",
                                  "response_summary": "Premature close attempt"},
                                 regulatory_affairs_specialist_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_INSPECTION_STATE)
