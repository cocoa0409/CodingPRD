"""Certification compliance: suspension, reinstatement, expiry, and the
compensating inspection void.

Covers the ACTIVE -> SUSPENDED -> ACTIVE cycle with its mark-license mirror,
clock-sweep expiry (and its exclusion of SUSPENDED certifications), immediate
consistency of mutation responses, role exclusivity of suspension, the
open-critical-findings reinstatement gate, and the end-to-end unwind an
inspection void performs.
"""

from test_helpers import (
    ApiErrorId,
    BASE_CLOCK_ISO,
    canonical_instant,
    complete_inspection,
    finding_entry,
    make_manufacturer_rep_headers,
    refresh_certification,
    refresh_factory,
    refresh_mark_license,
    reinstate_certification,
    schedule_inspection,
    set_clock,
    setup_certified,
    setup_certified_with_license,
    suspend_certification,
    suspend_certification_payload,
    validate_error,
    validate_success,
    void_inspection,
)


def test_suspend_reinstate_cycle_restores_certification(api):
    """PRD §3.9: "A `ComplianceOfficer` suspends an `ACTIVE` certification,
    supplying a `reason`; the certification becomes `SUSPENDED` with 'MANUAL'
    added to its `suspension_causes`, and every one of its mark licenses in
    `ACTIVE` or `EXHAUSTED` cascades to `SUSPENDED`."
    PRD §3.9: "On reinstatement the certification returns to `ACTIVE`, its
    `suspension_causes` are cleared, and each `SUSPENDED` mark license returns
    to `ACTIVE` when its `used_quantity` is below its `authorized_quantity`, or
    to `EXHAUSTED` when the two are equal."

    Design: Difficulty/non_linear_state_machine/certification_suspend_reinstate_cycle_restores_licenses
    """
    ctx = setup_certified_with_license(api, label_type="HOLOGRAM")
    cert_id = ctx["certification"]["id"]

    suspend_certification(api, cert_id, reason="Routine surveillance hold")
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "SUSPENDED"
    assert certification["suspension_causes"] == ["MANUAL"]

    reinstate_certification(api, cert_id)
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "ACTIVE"
    assert certification["suspension_causes"] == [], (
        "causes must be cleared on reinstatement"
    )


def test_suspend_reinstate_cycle_restores_mark_license(api):
    """PRD §2.10: "Suspending a certification suspends every one of its mark
    licenses that is `ACTIVE` or `EXHAUSTED`. Reinstating a certification
    returns each `SUSPENDED` license to `ACTIVE` or `EXHAUSTED` according to
    its quota consumption."

    Design: Difficulty/non_linear_state_machine/certification_suspend_reinstate_cycle_restores_licenses
    """
    ctx = setup_certified_with_license(api, label_type="HOLOGRAM")
    cert_id = ctx["certification"]["id"]
    lic_id = ctx["mark_license"]["id"]

    suspend_certification(api, cert_id, reason="Routine surveillance hold")
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["status"] == "SUSPENDED", (
        "the suspension must mirror down to the license"
    )

    reinstate_certification(api, cert_id)
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["status"] == "ACTIVE"
    # The cycle does not disturb quota fields.
    assert license_view["authorized_quantity"] == 11000
    assert license_view["used_quantity"] == 0


def test_certification_expires_via_clock_sweep_at_expiry_instant(api, officer_headers):
    """PRD §2.5: "Second, certification expiry: every `ACTIVE` certification
    whose `expires_on` is set and is at or before the current time becomes
    `EXPIRED`; `SUSPENDED` certifications do not expire."
    PRD §2.8: "an entity already in a terminal state — `REJECTED`, `WITHDRAWN`,
    `EXPIRED`, `VOIDED`, `IMPLEMENTED`, or `EVALUATED_FAIL` — rejects all
    further transitions with `ERR_ALREADY_TERMINAL`"

    Design: Corner/state_machines/certification_expires_via_clock_sweep_at_expiry_instant
    """
    ctx = setup_certified(api, validity_months=1)
    cert_id = ctx["certification"]["id"]
    assert canonical_instant(ctx["certification"]["expires_on"]) == canonical_instant(
        "2026-10-01T00:00:00Z"
    )

    set_clock(api, "2026-10-01T00:00:00Z")
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "EXPIRED", (
        "expiry is at-or-before: reaching expires_on exactly expires the certification"
    )
    response = api.suspend_certification(
        cert_id, suspend_certification_payload("Late hold"), officer_headers
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_suspended_certification_does_not_expire(api):
    """PRD §2.5: "every `ACTIVE` certification whose `expires_on` is set and is
    at or before the current time becomes `EXPIRED`; `SUSPENDED` certifications
    do not expire."

    Design: Corner/state_machines/suspended_certification_does_not_expire
    """
    ctx = setup_certified(api, validity_months=1)
    suspend_certification(api, ctx["certification"]["id"], reason="Surveillance hold")
    set_clock(api, "2026-11-01T00:00:00Z")
    certification = refresh_certification(api, ctx["certification"]["id"])
    assert certification["status"] == "SUSPENDED", (
        "a SUSPENDED certification must not expire even past expires_on"
    )


def test_immediate_consistency_suspend_response_shows_final_state(api, officer_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp, likewise with three
    fractional digits, refreshed on every mutation. `version` is an integer that
    increments by 1 on every mutation of the resource."

    Design: Corner/consistency_model/immediate_consistency_suspend_response_shows_final_state
    """
    ctx = setup_certified(api)
    response = api.suspend_certification(
        ctx["certification"]["id"],
        suspend_certification_payload("Routine surveillance hold"),
        officer_headers,
    )
    data = validate_success(response, 200)
    assert data["status"] == "SUSPENDED"
    assert data["suspension_causes"] == ["MANUAL"]
    assert data["version"] == 2
    assert data["updated_at"] is not None


def test_manufacturer_rep_cannot_suspend_certification_returns_unauthorized(api):
    """PRD §3.9: "A `ComplianceOfficer` suspends an `ACTIVE` certification,
    supplying a `reason`"
    PRD §2.1: "A request whose role is not permitted on the targeted endpoint is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/roles/manufacturer_rep_cannot_suspend_certification_returns_unauthorized
    """
    ctx = setup_certified(api)
    response = api.suspend_certification(
        ctx["certification"]["id"],
        suspend_certification_payload("Self-suspension attempt"),
        make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    certification = refresh_certification(api, ctx["certification"]["id"])
    assert certification["status"] == "ACTIVE"


def test_reinstate_blocked_while_critical_finding_open(api, officer_headers):
    """PRD §3.9: "It is blocked while any open `CRITICAL` finding naming the
    certification remains — that is, while the factory's count of `CRITICAL`
    findings naming this certification on non-`VOIDED` `COMPLETED` inspections
    is nonzero — and the attempt is rejected with
    `ERR_OPEN_CRITICAL_FINDINGS`."
    PRD §3.6: "And each certification whose `suspension_causes` contained only
    causes contributed by this inspection's findings — and no 'MANUAL' cause —
    is automatically reinstated to `ACTIVE`, cascading to its `SUSPENDED` mark
    licenses."

    Design: Corner/state_machines/reinstate_blocked_while_critical_finding_open
    """
    ctx = setup_certified(api)
    cert_id = ctx["certification"]["id"]
    inspection = schedule_inspection(api, ctx["factory"]["id"], BASE_CLOCK_ISO)
    complete_inspection(
        api,
        inspection["id"],
        findings=[
            finding_entry(
                "FD-7",
                "CRITICAL",
                "Line-built units omit listed fuse",
                certification_id=cert_id,
            )
        ],
    )
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "SUSPENDED"

    response = api.reinstate_certification(cert_id, officer_headers)
    validate_error(response, ApiErrorId.ERR_OPEN_CRITICAL_FINDINGS)
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "SUSPENDED"

    void_inspection(api, inspection["id"], reason="Finding recorded against wrong line")
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "ACTIVE", (
        "the void removes the last finding-derived cause and reinstates automatically"
    )


def test_inspection_void_restores_factory_conformity(api):
    """PRD §3.6: "Its findings cease to count: the factory's `conformity_score`,
    `conformity_regime`, `open_critical_findings`,
    `last_inspection_completed_on`, and `next_inspection_due_on` are all
    recomputed without them."
    PRD §3.6: "Voiding is the compensating action, performed by a
    `ComplianceOfficer` supplying a `reason`, and is available only on a
    `COMPLETED` inspection. The inspection becomes `VOIDED`, which is terminal."

    Design: Difficulty/compensating_invariant/inspection_void_restores_conformity_and_reinstates_certification
    """
    ctx = setup_certified_with_license(api)
    factory_id = ctx["factory"]["id"]
    inspection = schedule_inspection(api, factory_id, BASE_CLOCK_ISO)
    complete_inspection(
        api,
        inspection["id"],
        findings=[
            finding_entry(
                "FD-7",
                "CRITICAL",
                "Line-built units omit listed fuse",
                certification_id=ctx["certification"]["id"],
            )
        ],
    )
    factory = refresh_factory(api, factory_id)
    assert factory["conformity_score"] == 60
    assert factory["conformity_regime"] == "PROBATION"
    assert factory["open_critical_findings"] == 1

    voided = void_inspection(
        api,
        inspection["id"],
        reason="Inspection record created against the wrong production line",
    )
    assert voided["status"] == "VOIDED"

    factory = refresh_factory(api, factory_id)
    assert factory["conformity_score"] == 100
    assert factory["conformity_regime"] == "STANDARD"
    assert factory["open_critical_findings"] == 0


def test_inspection_void_reinstates_certification_and_license(api):
    """PRD §3.6: "And each certification whose `suspension_causes` contained
    only causes contributed by this inspection's findings — and no 'MANUAL'
    cause — is automatically reinstated to `ACTIVE`, cascading to its
    `SUSPENDED` mark licenses."
    PRD §3.6: "Every `CRITICAL` finding that names a certification also suspends
    that certification, if it is `ACTIVE`, adding a cause string of
    'CRITICAL_FINDING:' followed by the `finding_ref` to its
    `suspension_causes` and cascading the suspension to its mark licenses as
    §3.9 describes."

    Design: Difficulty/compensating_invariant/inspection_void_restores_conformity_and_reinstates_certification
    """
    ctx = setup_certified_with_license(api)
    cert_id = ctx["certification"]["id"]
    lic_id = ctx["mark_license"]["id"]
    inspection = schedule_inspection(api, ctx["factory"]["id"], BASE_CLOCK_ISO)
    complete_inspection(
        api,
        inspection["id"],
        findings=[
            finding_entry(
                "FD-7",
                "CRITICAL",
                "Line-built units omit listed fuse",
                certification_id=cert_id,
            )
        ],
    )
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "SUSPENDED"
    assert "CRITICAL_FINDING:FD-7" in certification["suspension_causes"]
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["status"] == "SUSPENDED"

    void_inspection(
        api,
        inspection["id"],
        reason="Inspection record created against the wrong production line",
    )
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "ACTIVE"
    assert certification["suspension_causes"] == []
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["status"] == "ACTIVE", "cascade restoration reaches the license"
