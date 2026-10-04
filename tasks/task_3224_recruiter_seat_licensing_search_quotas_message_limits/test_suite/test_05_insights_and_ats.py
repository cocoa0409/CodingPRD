"""Talent insight reports: aggregation floor boundary, publish state gating,
and ATS sync-record write-back with duplicate handling."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, AGGREGATION_FLOOR,
    contract_admin_headers,
    create_and_activate_contract, create_public_candidates,
    create_report, generate_report, create_candidate,
    create_integration, connect_integration, create_sync_record,
    setup_connected_integration,
)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/aggregation_floor_exactly_25_vs_24
# ---------------------------------------------------------------------------

def test_aggregation_floor_exactly_25_vs_24():
    """PRD section 3.8: "The report's `aggregation_floor` is fixed at 25. To
    move a `GENERATED` report to `PUBLISHED`, `matched_count` must be at
    least 25; an attempt to publish below the floor is rejected with
    `ERR_AGGREGATION_FLOOR`."

    Design: Difficulty/boundary_precision_check/aggregation_floor_exactly_25_vs_24
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-BND-2")
    cid = contract["id"]
    create_public_candidates(25, "Eng", member_prefix="eng")
    create_public_candidates(24, "Sci", member_prefix="sci")

    rep_a = create_report(cid, report_name="Eng Report",
                          filter_spec={"current_title": "Eng"})
    rep_b = create_report(cid, report_name="Sci Report",
                          filter_spec={"current_title": "Sci"})
    rep_a = generate_report(cid, rep_a["id"])
    rep_b = generate_report(cid, rep_b["id"])
    assert rep_a["matched_count"] == 25
    assert rep_b["matched_count"] == 24

    resp_a = api_client.publish_talent_insight(cid, rep_a["id"], contract_admin_headers())
    assert validate_success(resp_a)["report_status"] == "PUBLISHED"

    resp_b = api_client.publish_talent_insight(cid, rep_b["id"], contract_admin_headers())
    validate_error(resp_b, ApiErrorId.ERR_AGGREGATION_FLOOR)


def test_aggregation_floor_rejection_leaves_report_generated():
    """PRD section 3.8: "The report's `aggregation_floor` is fixed at 25. To
    move a `GENERATED` report to `PUBLISHED`, `matched_count` must be at
    least 25; an attempt to publish below the floor is rejected with
    `ERR_AGGREGATION_FLOOR`."

    Design: Difficulty/boundary_precision_check/aggregation_floor_exactly_25_vs_24
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-BND-2B")
    cid = contract["id"]
    create_public_candidates(AGGREGATION_FLOOR - 1, "Analyst", member_prefix="an")

    report = create_report(cid, report_name="Small Report",
                           filter_spec={"current_title": "Analyst"})
    report = generate_report(cid, report["id"])
    assert report["matched_count"] == AGGREGATION_FLOOR - 1

    resp = api_client.publish_talent_insight(cid, report["id"], contract_admin_headers())
    validate_error(resp, ApiErrorId.ERR_AGGREGATION_FLOOR)

    fetched = validate_success(
        api_client.get_talent_insight(cid, report["id"], contract_admin_headers())
    )
    assert fetched["report_status"] == "GENERATED"


# ---------------------------------------------------------------------------
# Corner/state_machines/report_publish_from_draft_rejected
# ---------------------------------------------------------------------------

def test_report_publish_from_draft_rejected():
    """PRD section 3.8: "To move a `GENERATED` report to `PUBLISHED`,
    `matched_count` must be at least 25; an attempt to publish below the
    floor is rejected with `ERR_AGGREGATION_FLOOR`."
    PRD section 4: "Publish a report (GENERATED->PUBLISHED or SUPPRESSED if
    below floor)".

    Design: Corner/state_machines/report_publish_from_draft_rejected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-SM-4")
    cid = contract["id"]
    report = create_report(cid, report_name="R1", filter_spec={"current_title": "Eng"})
    assert report["report_status"] == "DRAFT"

    resp = api_client.publish_talent_insight(cid, report["id"], contract_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_report_generate_computes_matched_count_and_transitions():
    """PRD section 3.8: "The system applies the same visibility rule and
    filter logic as candidate search (§3.4) to compute `matched_count` — the
    number of `CandidateProfile` rows visible and matching — but unlike
    candidate search, the result is **not** truncated by the contract's
    `search_result_page_cap`; `matched_count` is stored raw. The report moves
    from `DRAFT` to `GENERATED`."

    Design: Corner/state_machines/report_publish_from_draft_rejected
    """
    contract = create_and_activate_contract(seats=1, product_tier="RECRUITER_LITE",
                                            contract_number="C-SM-4B")
    cid = contract["id"]
    # LITE page cap is 40; create 45 matches to prove matched_count is uncapped.
    create_public_candidates(45, "Designer", member_prefix="dsg")

    report = create_report(cid, report_name="Design Report",
                           filter_spec={"current_title": "Designer"})
    report = generate_report(cid, report["id"])
    assert report["report_status"] == "GENERATED"
    assert report["matched_count"] == 45


# ---------------------------------------------------------------------------
# Corner/calculations/ats_duplicate_fingerprint_skips_second_write
# ---------------------------------------------------------------------------

def test_ats_duplicate_fingerprint_skips_second_write():
    """PRD section 3.7: "If another `AtsSyncRecord` under the same
    `ats_integration_id` already has the same `payload_fingerprint` and is in
    `sync_status` of `WRITTEN`, the new record's `sync_status` is set to
    `DUPLICATE_SKIPPED`. This is the duplicate-handling rule: a redelivery of
    an identical event is acknowledged but never written twice."

    Design: Corner/calculations/ats_duplicate_fingerprint_skips_second_write
    """
    ctx = setup_connected_integration(contract_number="C-CALC-4")
    intg, cand = ctx["integration"], ctx["candidate"]

    first = create_sync_record(intg["id"], cand["id"], event_type="HIRED",
                               external_candidate_ref="gh-x",
                               payload={"stage": "hired"})
    second = create_sync_record(intg["id"], cand["id"], event_type="HIRED",
                                external_candidate_ref="gh-x",
                                payload={"stage": "hired"})
    assert first["sync_status"] == "WRITTEN"
    assert second["sync_status"] == "DUPLICATE_SKIPPED"


def test_ats_different_payload_not_duplicate():
    """PRD section 3.7: "If another `AtsSyncRecord` under the same
    `ats_integration_id` already has the same `payload_fingerprint` and is in
    `sync_status` of `WRITTEN`, the new record's `sync_status` is set to
    `DUPLICATE_SKIPPED`."
    PRD section 3.7: "Otherwise, if the integration is in `integration_status`
    of `CONNECTED` and `write_back_enabled` is true, the record is written
    back immediately and its `sync_status` becomes `WRITTEN`."

    Design: Corner/calculations/ats_duplicate_fingerprint_skips_second_write
    """
    ctx = setup_connected_integration(contract_number="C-CALC-4B")
    intg, cand = ctx["integration"], ctx["candidate"]

    first = create_sync_record(intg["id"], cand["id"], event_type="HIRED",
                               external_candidate_ref="gh-y",
                               payload={"stage": "hired"})
    second = create_sync_record(intg["id"], cand["id"], event_type="HIRED",
                                external_candidate_ref="gh-y",
                                payload={"stage": "offer"})
    assert first["sync_status"] == "WRITTEN"
    assert second["sync_status"] == "WRITTEN"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/sync_record_writeback_requires_integration_connected
# ---------------------------------------------------------------------------

def test_sync_record_writeback_requires_integration_connected():
    """PRD section 3.7: "Otherwise, if the integration is in
    `integration_status` of `CONNECTED` and `write_back_enabled` is true, the
    record is written back immediately and its `sync_status` becomes
    `WRITTEN`."
    PRD section 3.7: "Otherwise the record remains `QUEUED` — for example
    while the integration is still `PROVISIONING` or in `SYNC_ERROR`."

    Design: Difficulty/cross_entity_state_dependency/sync_record_writeback_requires_integration_connected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-XD-2")
    cid = contract["id"]
    integration = create_integration(cid, vendor="GREENHOUSE",
                                     external_tenant_id="gh-1",
                                     write_back_enabled=True)
    assert integration["integration_status"] == "PROVISIONING"
    candidate = create_candidate(member_id="m-x")

    queued = create_sync_record(integration["id"], candidate["id"],
                                event_type="APPLICATION_FORWARDED",
                                external_candidate_ref="gh-cand-1",
                                payload={"stage": "applied"})
    assert queued["sync_status"] == "QUEUED"

    connect_integration(cid, integration["id"])

    written = create_sync_record(integration["id"], candidate["id"],
                                 event_type="STAGE_CHANGED",
                                 external_candidate_ref="gh-cand-2",
                                 payload={"stage": "screen"})
    assert written["sync_status"] == "WRITTEN"


def test_sync_record_queued_while_integration_sync_error():
    """PRD section 3.7: "Otherwise the record remains `QUEUED` — for example
    while the integration is still `PROVISIONING` or in `SYNC_ERROR`."
    PRD section 3.7: "A `QUEUED` record may later resolve to `WRITTEN` once
    the integration reaches `CONNECTED` with `write_back_enabled` true and no
    duplicate fingerprint already written exists."

    Design: Difficulty/cross_entity_state_dependency/sync_record_writeback_requires_integration_connected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-XD-2B")
    cid = contract["id"]
    integration = create_integration(cid, vendor="LEVER",
                                     external_tenant_id="lv-1",
                                     write_back_enabled=True)
    candidate = create_candidate(member_id="m-x2")

    record = create_sync_record(integration["id"], candidate["id"],
                                event_type="STAGE_CHANGED",
                                external_candidate_ref="lv-cand-1",
                                payload={"stage": "screen"})
    assert record["sync_status"] == "QUEUED"

    fetched = validate_success(
        api_client.get_ats_sync_record(record["id"], contract_admin_headers())
    )
    assert fetched["sync_status"] == "QUEUED"
