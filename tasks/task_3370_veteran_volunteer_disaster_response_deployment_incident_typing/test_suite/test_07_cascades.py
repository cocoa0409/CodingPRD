"""The two deep cascades: incident stand-down (operation -> deployment -> FOB
ledger + wellness screen) and certification revocation (deployment hold ->
capability gap -> blocked field work)."""
from test_helpers import (
    assert_deployment,
    assert_wellness_check,
    get_deployment,
    get_fob_site,
    get_operation,
    get_volunteer,
    get_work_order,
    list_deployment_wellness_checks,
    schedule_and_complete_shifts,
    set_clock,
    setup_in_progress_work_order,
    setup_two_volunteer_operation,
    transition_incident,
    validate_paginated,
    validate_success,
)

THREE_TEN_HOUR_SHIFTS = [
    ("2026-09-10T08:00:00Z", "2026-09-10T18:00:00Z"),
    ("2026-09-11T08:00:00Z", "2026-09-11T18:00:00Z"),
    ("2026-09-12T08:00:00Z", "2026-09-12T18:00:00Z"),
]


def _setup_stand_down_scenario():
    """ACTIVE operation (hazard TREE_REMOVAL, team 2, duration 4, start
    2026-09-10) under a TYPED incident, with FOB Alpha (2 bunks, 1235/night).
    d1 (v1, CHAINSAW, needs_lodging) ON_SITE since 2026-09-10T08:00:00Z holding
    a bunk; d2 (v2, MEDICAL) ACCEPTED and never checked in. Three 10h shifts
    for d1 (Sep 10/11/12) are completed by the ops run at 2026-09-12T19:00:00Z
    (fatigue 30); the same epoch sweeps d2 to NO_SHOW."""
    bundle = setup_two_volunteer_operation(
        v1_cert_kinds=("CHAINSAW",),
        v2_cert_kinds=("MEDICAL",),
        required_capabilities=("CHAINSAW", "MEDICAL"),
        d1_offer_overrides={"needs_lodging": True},
        with_fob={"name": "FOB Alpha", "bunks_total": 2, "nightly_rate_cents": 1235},
    )
    schedule_and_complete_shifts(
        bundle["operation"]["id"], bundle["d1"]["id"],
        THREE_TEN_HOUR_SHIFTS, ops_clock="2026-09-12T19:00:00Z",
    )
    return bundle


def test_stand_down_demobilizes_active_operation_and_deployments(api):
    """PRD §3.8: "When an `IncidentCommander` moves a `TYPED` incident to `STANDING_DOWN`, the cascade runs hop by hop. Every operation of the incident in `MUSTERED` or `ACTIVE` moves to `DEMOBILIZING`."
    PRD §3.4: "A volunteer who never shows is caught by the ops run: a deployment still `ACCEPTED` once `current_utc` has passed the operation's `start_date` by more than the 24-hour grace flips to the terminal `NO_SHOW` state, with the operation's counters recomputed."

    Design: Difficulty/transitive_cascade/incident_stand_down_three_hop_cascade
    """
    bundle = _setup_stand_down_scenario()
    set_clock("2026-09-13T09:00:00Z")
    transition_incident(bundle["incident"]["id"], status="STANDING_DOWN")
    operation = get_operation(bundle["operation"]["id"])
    assert operation["status"] == "DEMOBILIZING"
    d1 = get_deployment(bundle["d1"]["id"])
    assert_deployment(d1)
    assert d1["status"] == "DEMOBED"
    d2 = get_deployment(bundle["d2"]["id"])
    assert d2["status"] == "NO_SHOW"


def test_stand_down_finalizes_lodging_and_raises_wellness_check(api):
    """PRD §3.8: "every deployment in `ON_SITE` or `SAFETY_HOLD` is demobilized with the full demobe bundle of §3.4 — `demobed_at` stamped, `duty_status` returned to `RESTING`, bunk released and lodging finalized where a `fob_site_id` was set, `stipend_final_cents` computed, remaining `SCHEDULED` shifts cancelled, the wellness screen run, and the operation's counters recomputed"
    PRD §3.4: "if the volunteer's `fatigue_hours` has reached 30 (`WELLNESS_FATIGUE_THRESHOLD_HOURS`) or the actual on-site stay spans at least 10 days (`WELLNESS_LONG_DEPLOYMENT_DAYS`), an `OPEN` `WellnessCheck` is created for the deployment with `reason` `FATIGUE_THRESHOLD` or `LONG_DEPLOYMENT` respectively."

    Design: Difficulty/transitive_cascade/incident_stand_down_three_hop_cascade
    """
    bundle = _setup_stand_down_scenario()
    set_clock("2026-09-13T09:00:00Z")
    transition_incident(bundle["incident"]["id"], status="STANDING_DOWN")
    # On site 2026-09-10T08:00Z -> demobed by the cascade at 2026-09-13T09:00Z:
    # 73 hours -> ceil = 4 days -> 4 x 6500 + 15000 = 41000.
    d1 = get_deployment(bundle["d1"]["id"])
    assert d1["status"] == "DEMOBED"
    assert d1["stipend_final_cents"] == 41000
    # 3 nights x round_half_up(1235 x 1.07) = 3 x 1321 = 3963; bunk released.
    fob = get_fob_site(bundle["operation"]["id"], bundle["fob"]["id"])
    assert fob["bunks_occupied"] == 0
    assert fob["lodging_cost_cents"] == 3963
    # Fatigue 30 >= 30 -> exactly one OPEN wellness check (FATIGUE_THRESHOLD).
    checks = list_deployment_wellness_checks(bundle["d1"]["id"])
    assert len(checks) == 1
    assert_wellness_check(checks[0])
    assert checks[0]["status"] == "OPEN"
    assert checks[0]["reason"] == "FATIGUE_THRESHOLD"
    volunteer = get_volunteer(bundle["v1"]["id"])
    assert volunteer["fatigue_hours"] == 30


def _revoke_v1_chainsaw_cert(api, safety_officer_headers, bundle):
    """Revoke v1's only (CHAINSAW) certification; returns the response."""
    certs, _meta = validate_paginated(
        api.list_certifications(
            safety_officer_headers, params={"volunteer_id": bundle["v1"]["id"]},
        )
    )
    assert len(certs) == 1
    return api.patch_certification(
        certs[0]["id"], {"status": "REVOKED"}, safety_officer_headers
    )


def test_cert_revocation_holds_on_site_deployment(api, safety_officer_headers):
    """PRD §3.1: "When a `SafetyOfficer` moves a `VERIFIED` certification to the terminal `REVOKED` state, the cascade runs in hops. First, every deployment of the credential's owner that is currently `ON_SITE`, serving an operation whose `required_capabilities` contains the revoked kind, and for which the owner holds no other `VERIFIED` certification of that kind, is moved to `SAFETY_HOLD`."

    Design: Difficulty/transitive_cascade/cert_revocation_two_hop_cascade
    """
    bundle = setup_in_progress_work_order()
    resp = _revoke_v1_chainsaw_cert(api, safety_officer_headers, bundle)
    cert = validate_success(resp, 200)
    assert cert["status"] == "REVOKED"
    d1 = get_deployment(bundle["d1"]["id"])
    assert d1["status"] == "SAFETY_HOLD"
    # d2 belongs to a different volunteer whose certs are untouched.
    d2 = get_deployment(bundle["d2"]["id"])
    assert d2["status"] == "ACCEPTED"


def test_cert_revocation_opens_gap_and_blocks_field_work(api, safety_officer_headers):
    """PRD §3.1: "Second, for each operation touched by the first hop, the `capability_gap` is recomputed, and if the gap for the affected kind is now positive, every work order of that operation that is `IN_PROGRESS` and whose `hazard_kind` maps to that capability is moved to `BLOCKED` with `blocked_reason` set to `CAPABILITY_LOST`."
    PRD §2.10: "for each required capability, the shortfall is 1 minus the number of rostered volunteers holding a `VERIFIED` certification of that kind, clamped so it never goes below zero, with zero-shortfall entries omitted from the map entirely."

    Design: Difficulty/transitive_cascade/cert_revocation_two_hop_cascade
    """
    bundle = setup_in_progress_work_order()
    resp = _revoke_v1_chainsaw_cert(api, safety_officer_headers, bundle)
    validate_success(resp, 200)
    operation = get_operation(bundle["operation"]["id"])
    # SAFETY_HOLD drops d1 out of the rostered set; CHAINSAW coverage lost.
    assert operation["capability_gap"] == {"CHAINSAW": 1}
    work_order = get_work_order(bundle["wo1"]["id"])
    assert work_order["status"] == "BLOCKED"
    assert work_order["blocked_reason"] == "CAPABILITY_LOST"
