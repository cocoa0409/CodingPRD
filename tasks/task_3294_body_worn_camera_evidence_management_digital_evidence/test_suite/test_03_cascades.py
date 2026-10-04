"""Cascade tests: purge cascade to agency posture and case rollup; share-access
cascade to grant counter and custody fan-in."""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    make_officer_headers,
    make_supervisor_headers,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_budget_plan,
    create_case,
    link_evidence,
    list_custody_events,
    refresh_agency,
    refresh_recording,
    run_retention,
    set_clock,
    setup_agency_with_policy,
    setup_agency_with_policy_and_officer,
    setup_closed_case_with_grant,
    setup_officer_with_device,
    submit_case,
    close_case,
    get_case,
    upload_recording,
)
from test_helpers.test_users import make_prosecutor_headers

ADMIN = TEST_USERS["agency_admin_headers"]
RO = TEST_USERS["records_officer_headers"]


# ===========================================================================
# transitive_cascade / purge_cascade_recording_to_agency_posture_to_case_rollup
# ===========================================================================

def test_retention_run_marks_and_purges_all_due_recordings(api):
    """PRD §3.5: "First, every `ACTIVE` recording whose `retention_due_at` is at
    or before the logical now moves `ACTIVE → RETENTION_DUE`... Then, in the same
    run, each `RETENTION_DUE` recording whose `legal_hold_count` is zero moves to
    `PURGED`... The run reports how many recordings were marked retention-due
    (`marked_retention_due`), how many were purged (`purged`), how many were
    skipped because of holds (`held_skipped`)".

    Design: Difficulty/transitive_cascade/purge_cascade_recording_to_agency_posture_to_case_rollup
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    create_budget_plan(agency["id"], monthly_budget_cents=3000,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    # Pin the clock past the latest recorded_at used below so no upload is
    # future-dated relative to the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:03:00Z")
    recs = []
    for i in range(4):
        recs.append(upload_recording(
            agency["id"], device, officer,
            recorded_at=f"2026-09-01T00:0{i}:00Z",
            size_bytes=1073741824, category="INCIDENT"))
    case = create_case(agency["id"], officer)
    link_evidence(agency["id"], case["id"], recs[3]["id"], officer)
    # The linked recording's retention is extended per PRD section 3.5:
    # link creation (2026-09-01T00:03:00Z) + 730 days = 2028-08-31T00:03:00Z,
    # so the run must execute past that instant to purge all four.
    set_clock("2028-09-05T00:00:00Z")
    result = run_retention(agency["id"])
    assert result["marked_retention_due"] == 4
    assert result["purged"] == 4
    assert result["held_skipped"] == 0


def test_purge_cascade_zeroes_storage_and_nulls_case_rollup(api):
    """PRD §3.5: "Each purge removes the recording's `size_bytes` from the
    agency's `storage_used_bytes`, recomputes `storage_posture`, decrements the
    officer's `recordings_uploaded_count` by one, recomputes each linked case's
    `total_evidence_bytes` and `retention_due_at`".
    PRD §3.7: "When the projection exceeds `monthly_budget_cents` — strictly
    greater — posture is `OVER_BUDGET`."

    Design: Difficulty/transitive_cascade/purge_cascade_recording_to_agency_posture_to_case_rollup
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    create_budget_plan(agency["id"], monthly_budget_cents=3000,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    # Pin the clock past the latest recorded_at used below so no upload is
    # future-dated relative to the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:03:00Z")
    recs = []
    for i in range(4):
        recs.append(upload_recording(
            agency["id"], device, officer,
            recorded_at=f"2026-09-01T00:0{i}:00Z",
            size_bytes=1073741824, category="INCIDENT"))
    case = create_case(agency["id"], officer)
    link_evidence(agency["id"], case["id"], recs[3]["id"], officer)
    # 4 GiB live -> projection 4000 > 3000 budget -> OVER_BUDGET
    agency_now = refresh_agency(agency["id"])
    assert agency_now["storage_posture"] == "OVER_BUDGET"
    # The linked recording's retention is extended per PRD section 3.5:
    # link creation (2026-09-01T00:03:00Z) + 730 days = 2028-08-31T00:03:00Z,
    # so the run must execute past that instant to purge all four.
    set_clock("2028-09-05T00:00:00Z")
    run_retention(agency["id"])
    agency_now = refresh_agency(agency["id"])
    assert agency_now["storage_used_bytes"] == 0
    assert agency_now["storage_posture"] == "OK", (
        f"the purge-driven recompute flips posture back to OK, "
        f"got {agency_now['storage_posture']}"
    )
    case_now = get_case(agency["id"], case["id"])
    assert case_now["total_evidence_bytes"] == 0
    assert case_now["retention_due_at"] is None


# ===========================================================================
# transitive_cascade / share_access_cascade_grant_counter_to_custody_fanin
# ===========================================================================

def test_share_access_returns_linked_recordings_and_active_status(api):
    """PRD §3.9: "A successful access increments the grant's `access_count` by
    one, records an `ACCESSED` custody event on every recording currently
    `LINKED` to the grant's case, and returns the `case_id`, the `recording_ids`
    of the linked recordings, and the `grant_status`."

    Design: Difficulty/transitive_cascade/share_access_cascade_grant_counter_to_custody_fanin
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant(num_recordings=2)
    agency, case, grant = ctx["agency"], ctx["case"], ctx["grant"]
    ra, rb = ctx["recordings"][0], ctx["recordings"][1]
    resp = api.share_access(agency["id"], {"access_token": grant["access_token"]},
                            make_prosecutor_headers())
    data = validate_success(resp)
    assert data["case_id"] == case["id"]
    assert set(data["recording_ids"]) == {ra["id"], rb["id"]}
    assert data["grant_status"] == "ACTIVE"


def test_share_access_increments_counter_and_writes_accessed_per_recording(api):
    """PRD §3.9: "A successful access increments the grant's `access_count` by
    one, records an `ACCESSED` custody event on every recording currently
    `LINKED` to the grant's case".

    Design: Difficulty/transitive_cascade/share_access_cascade_grant_counter_to_custody_fanin
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant(num_recordings=2)
    agency, case, grant = ctx["agency"], ctx["case"], ctx["grant"]
    ra, rb = ctx["recordings"][0], ctx["recordings"][1]
    api.share_access(agency["id"], {"access_token": grant["access_token"]},
                     make_prosecutor_headers())
    data, meta = validate_paginated(api.list_case_share_grants(agency["id"], case["id"], RO))
    grant_now = [g for g in data if g["id"] == grant["id"]][0]
    assert grant_now["access_count"] == 1
    for rec in (ra, rb):
        events = list_custody_events(agency["id"], rec["id"])
        accessed = [e for e in events if e["event_type"] == "ACCESSED"]
        assert len(accessed) == 1, (
            f"exactly one ACCESSED event expected on recording {rec['id']}, "
            f"got {[e['event_type'] for e in events]}"
        )
        assert accessed[0]["actor_role"] == "Prosecutor"
