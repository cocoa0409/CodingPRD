"""Read-your-writes across the whole activation fan-out.

Activation is the single densest write in this API: PRD 3.6 has it move the
authority, the originating application and the owning carrier, mint a first
risk score and schedule a safety audit, all in one request.  This test compares
the activate response against independent reads taken at the very same logical
instant and requires every one of those effects to be already settled — no
denormalised field lags behind, and repeated reads do not drift.
"""

from test_helpers import (
    COMPLIANCE_OFFICER,
    MAX_LIMIT,
    REGISTRY_ADMIN,
    assert_created_at_ascending,
    assert_risk_score,
    get_success_data,
    read_authority,
    set_clock,
    setup_pending_authority_with_coverage,
    validate_paginated,
    validate_success,
)


def test_activation_side_effects_are_visible_in_the_same_response(api):
    """Every field activation writes is already settled when the call returns.

    PRD 3.6: "When all eight conditions hold, activation writes a great deal at
    once. The authority's `authority_status` becomes `ACTIVE`, its `activated_at` is
    stamped with the current logical time, and its `insurance_status` is set to
    `FILED`. The originating application moves `PUBLISHED → GRANTED`. On the owning
    carrier, `unified_registration_status` becomes `REGISTERED` and
    `active_authority_count` increases by one. The carrier is also scored for the
    first time: `compliance_risk_score` is written from the self-reported variant
    below and `compliance_risk_variant` becomes `SELF_REPORTED`. The authority's
    `version` increases by one."

    PRD 3.6: "If the carrier's `entrant_status` is `NEW_ENTRANT` at the moment of
    activation, the authority's `new_entrant_audit_status` becomes `PENDING`, its
    `new_entrant_audit_deadline_at` is set to the audit window described below, and a
    `SafetyAudit` is created for that carrier with `status` `SCHEDULED`,
    `audit_window_opens_at` equal to the current logical time (that is, the
    authority's `activated_at`) and `audit_deadline_at` equal to the same window
    figure."

    PRD 3.6: "The audit is **not** returned by the activation response; it is
    discoverable only by listing that carrier's safety audits."

    PRD 3.6: "The audit window runs 18 calendar months from `activated_at`,
    preserving the day of month and the time of day"

    Design: Corner/consistency_model/activation_side_effects_are_visible_in_the_same_response
    """
    env = setup_pending_authority_with_coverage(api)

    # The opening posture of every field activation is about to move.
    assert env.authority["authority_status"] == "PENDING"
    assert env.authority["activated_at"] is None
    assert env.authority["new_entrant_audit_status"] == "NOT_REQUIRED"
    assert env.authority["new_entrant_audit_deadline_at"] is None
    version_before = env.authority["version"]

    before = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert before["entrant_status"] == "NEW_ENTRANT"
    assert before["unified_registration_status"] == "NOT_REGISTERED"
    assert before["active_authority_count"] == 0
    assert before["compliance_risk_variant"] == "NONE"
    assert before["compliance_risk_score"] is None
    assert before["fee_balance_cents"] == 0
    assert before["biennial_delinquent"] is False
    assert before["self_reported_vehicle_count"] == 25
    assert before["self_reported_driver_count"] == 30
    assert before["self_reported_oos_rate_pct"] == 8.0

    application_before = get_success_data(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application_before["status"] == "PUBLISHED"

    audits_before, meta_before = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert audits_before == []
    assert meta_before["total_count"] == 0

    eligible_at = env.authority["activation_eligible_at"]
    assert eligible_at == "2026-08-26T00:00:00.000Z"
    set_clock(api, eligible_at)

    activated = validate_success(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    )

    # Everything §3.6 lists for the authority is already in the activate response.
    assert activated["id"] == env.authority_id
    assert activated["authority_status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-26T00:00:00.000Z"
    assert activated["insurance_status"] == "FILED"
    assert activated["new_entrant_audit_status"] == "PENDING"
    assert activated["new_entrant_audit_deadline_at"] == "2028-02-26T00:00:00.000Z"
    assert activated["version"] == version_before + 1
    # The audit itself is deliberately absent from this payload.
    assert "safety_audit" not in activated
    assert "safety_audit_id" not in activated

    # The carrier read taken immediately afterwards agrees with it.
    carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["unified_registration_status"] == "REGISTERED"
    assert carrier["active_authority_count"] == 1
    assert carrier["compliance_risk_variant"] == "SELF_REPORTED"
    assert_risk_score(carrier["compliance_risk_score"], 20.65)
    # The audited figures are untouched by a self-reported scoring.
    assert carrier["audited_oos_rate_pct"] is None
    assert carrier["entrant_status"] == "NEW_ENTRANT"

    # The scheduled audit exists on the very next read of the carrier's audits.
    audits, meta = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert meta["total_count"] == 1
    assert_created_at_ascending(audits)
    audit = audits[0]
    assert audit["carrier_id"] == env.carrier_id
    assert audit["status"] == "SCHEDULED"
    assert audit["audit_window_opens_at"] == activated["activated_at"]
    assert audit["audit_deadline_at"] == activated["new_entrant_audit_deadline_at"]
    assert audit["result_recorded_at"] is None
    assert audit["audited_oos_rate_pct"] is None
    assert audit["audited_driver_violation_count"] is None
    assert audit["audited_vehicle_defect_count"] is None
    assert audit["acute_violation_count"] is None
    assert audit["audit_score"] is None

    # The originating application moved inside the same request.
    application = get_success_data(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application["status"] == "GRANTED"
    assert application["id"] == env.application_id

    # No read disagrees with the activate response, and repeated reads at the same
    # logical instant are stable field for field.
    first_reread = read_authority(api, env.authority_id)
    assert first_reread == activated
    second_reread = read_authority(api, env.authority_id, headers=COMPLIANCE_OFFICER)
    assert second_reread == activated

    carrier_again = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier_again == carrier
    audits_again, _ = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert audits_again == audits
