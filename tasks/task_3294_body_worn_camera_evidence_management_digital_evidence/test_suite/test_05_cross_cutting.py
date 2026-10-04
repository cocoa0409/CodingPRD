"""Cross-cutting tests: full custody chain reconstruction and immediate
consistency of derived counters."""
from test_helpers import (
    TEST_USERS,
    make_prosecutor_headers,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_legal_hold,
    list_custody_events,
    refresh_agency,
    refresh_officer,
    refresh_recording,
    run_retention,
    set_clock,
    setup_agency_with_policy_and_officer,
    setup_closed_case_with_grant,
    upload_recording,
)
from test_helpers.assertions import assert_audit_log_entry, assert_custody_event

RO = TEST_USERS["records_officer_headers"]


# ===========================================================================
# cross_cutting_layers / custody_chain_reconstructed_in_chronological_order
# ===========================================================================

def test_custody_chain_full_lifecycle_in_order(api):
    """PRD §2.5: "Every evidence-affecting event appends a `CustodyEvent` to the
    recording's chain of custody, recording the `event_type` (one of `UPLOADED`,
    `HASH_VERIFIED`, `HASH_MISMATCH`, `CASE_LINKED`, `CASE_UNLINKED`,
    `REDACTION_STARTED`, `REDACTION_RELEASED`, `SHARED`, `ACCESSED`,
    `HOLD_PLACED`, `HOLD_RELEASED`, or `PURGE_EXECUTED`)".
    PRD §4: GET /agencies/{agencyId}/recordings/{recordingId}/custody-events —
    "Chain-of-custody log for a recording (chronological)".

    Design: Corner/cross_cutting_layers/custody_chain_reconstructed_in_chronological_order
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant()
    agency, case, grant = ctx["agency"], ctx["case"], ctx["grant"]
    rec = ctx["recordings"][0]
    # prosecutor accesses the shared case
    resp = api.share_access(agency["id"], {"access_token": grant["access_token"]},
                            make_prosecutor_headers())
    validate_success(resp)
    # record-scoped hold placed and released
    hold = create_legal_hold(agency["id"], scope_type="RECORDING",
                             recording_id=rec["id"], authority_reference="SUBP-1")
    validate_success(api.release_legal_hold(agency["id"], hold["id"], RO))
    # advance the clock past the case-extended INCIDENT retention (link
    # creation 2026-09-01T00:00:00Z + 730 days = 2028-08-31T00:00:00Z, PRD
    # section 3.5) and purge
    set_clock("2028-09-01T00:00:00Z")
    run_retention(agency["id"])
    rec_now = refresh_recording(agency["id"], rec["id"])
    assert rec_now["upload_status"] == "PURGED"
    events = list_custody_events(agency["id"], rec["id"])
    for e in events:
        assert_custody_event(e)
    event_types = [e["event_type"] for e in events]
    assert event_types == [
        "HASH_VERIFIED", "UPLOADED", "CASE_LINKED", "ACCESSED",
        "HOLD_PLACED", "HOLD_RELEASED", "PURGE_EXECUTED",
    ], f"full lifecycle custody chain out of order: {event_types}"


def test_custody_chain_hash_events_carry_hash_at_event(api):
    """PRD §2.5: "on `HASH_VERIFIED`, `HASH_MISMATCH`, and `PURGE_EXECUTED`
    events, the `hash_at_event` observed at that moment".

    Design: Corner/cross_cutting_layers/custody_chain_reconstructed_in_chronological_order
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant()
    agency, grant = ctx["agency"], ctx["grant"]
    rec = ctx["recordings"][0]
    api.share_access(agency["id"], {"access_token": grant["access_token"]},
                     make_prosecutor_headers())
    hold = create_legal_hold(agency["id"], scope_type="RECORDING",
                             recording_id=rec["id"], authority_reference="SUBP-1")
    api.release_legal_hold(agency["id"], hold["id"], RO)
    # advance the clock past the case-extended INCIDENT retention (link
    # creation 2026-09-01T00:00:00Z + 730 days = 2028-08-31T00:00:00Z, PRD
    # section 3.5) so the run purges the recording
    set_clock("2028-09-01T00:00:00Z")
    run_retention(agency["id"])
    events = list_custody_events(agency["id"], rec["id"])
    by_type = {e["event_type"]: e for e in events}
    expected_hash = "a" * 64
    assert by_type["HASH_VERIFIED"]["hash_at_event"] == expected_hash
    assert by_type["PURGE_EXECUTED"]["hash_at_event"] == expected_hash


# ===========================================================================
# consistency_model / derived_counters_visible_in_same_request_response
# ===========================================================================

def test_officer_counters_updated_immediately_after_upload(api):
    """PRD §2.6: "The platform maintains several derived figures synchronously —
    recomputed inside the same request that invalidates them, never by a
    background job".
    PRD §3.4: "The uploading officer's `recordings_uploaded_count` increments by
    one and their `pending_review_count` is recomputed."

    Design: Corner/consistency_model/derived_counters_visible_in_same_request_response
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer(
        policy_overrides={"supervisor_review_rate_pct": 100})
    rec = upload_recording(agency["id"], device, officer, size_bytes=1048576,
                           category="INCIDENT")
    officer_now = refresh_officer(agency["id"], officer["id"])
    assert officer_now["recordings_uploaded_count"] == 1
    assert officer_now["pending_review_count"] == 1
    assert rec["review_status"] == "PENDING_REVIEW"
    assert rec["upload_status"] == "ACTIVE"


def test_agency_storage_updated_immediately_after_upload(api):
    """PRD §2.6: "An agency's `storage_used_bytes` is the sum of `size_bytes`
    over all of its recordings whose `upload_status` is `ACTIVE`,
    `RETENTION_DUE`, or `UNDER_REVIEW` — recordings in `PURGED` are always
    excluded. It is recomputed synchronously on every recording state or size
    change."

    Design: Corner/consistency_model/derived_counters_visible_in_same_request_response
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer(
        policy_overrides={"supervisor_review_rate_pct": 100})
    upload_recording(agency["id"], device, officer, size_bytes=1048576,
                     category="INCIDENT")
    agency_now = refresh_agency(agency["id"])
    assert agency_now["storage_used_bytes"] == 1048576, (
        f"storage accounting must apply synchronously, got "
        f"{agency_now['storage_used_bytes']}"
    )
