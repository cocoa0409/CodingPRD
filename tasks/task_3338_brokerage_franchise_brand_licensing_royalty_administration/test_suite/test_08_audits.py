"""Brand-standards audit lifecycle and its cascade into the default machinery."""
from test_helpers import (
    validate_error, validate_paginated, get_success_data,
    setup_active_agreement, open_default,
    create_audit_payload,
    ApiErrorId, TEST_USERS,
)

OPS = TEST_USERS["franchisor_ops_headers"]
AUDITOR = TEST_USERS["brand_auditor_headers"]


def test_audit_start_rejected_while_agreement_suspended(api):
    """PRD §3.7: "Starting an audit is the `BrandAuditor`'s exclusive act and
    requires two conditions: the audit must be `SCHEDULED`, and the parent
    agreement must be `ACTIVE` — an audit cannot be opened against a suspended,
    expired, or winding-down agreement."

    Design: Difficulty/cross_entity_state_dependency/audit_start_gated_by_agreement_state
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    audit = get_success_data(
        api.create_compliance_audit(ag_id, create_audit_payload(audit_type="SIGNAGE"), AUDITOR)
    )
    open_default(ag_id, "PAYMENT")
    get_success_data(api.suspend_agreement(ag_id, OPS))

    resp = api.start_compliance_audit(audit["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    audits, _meta = validate_paginated(api.list_compliance_audits(ag_id, OPS))
    assert audits[0]["status"] == "SCHEDULED", "rejected start must not move the audit"


def test_audit_start_succeeds_while_agreement_active(api):
    """PRD §3.7: "On start, the audit moves to `IN_PROGRESS` and stamps
    `started_at`."

    Design: Difficulty/cross_entity_state_dependency/audit_start_gated_by_agreement_state
    """
    ctx = setup_active_agreement()
    audit = get_success_data(
        api.create_compliance_audit(
            ctx["agreement"]["id"], create_audit_payload(audit_type="MARKETING"), AUDITOR
        )
    )
    started = get_success_data(api.start_compliance_audit(audit["id"], AUDITOR))
    assert started["status"] == "IN_PROGRESS"
    assert started["started_at"], "started_at must be stamped on start"


def test_failed_audit_opens_brand_standards_default_case(api):
    """PRD §3.7: "A `FAIL` does not: the system opens a `DefaultCase` on the
    agreement with `reason_code` `BRAND_STANDARDS` in `OPEN` status, and the
    agreement's `open_cure_count` is recomputed to include it."

    Design: Corner/cross_cutting_layers/cascading_side_effects_audit_fail_creates_default_case
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    audit = get_success_data(
        api.create_compliance_audit(ag_id, create_audit_payload(audit_type="SIGNAGE"), AUDITOR)
    )
    get_success_data(api.start_compliance_audit(audit["id"], AUDITOR))
    completed = get_success_data(
        api.complete_compliance_audit(audit["id"], {"finding": "FAIL"}, AUDITOR)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["finding"] == "FAIL"

    cases, _meta = validate_paginated(api.list_default_cases(ag_id, OPS))
    assert len(cases) == 1
    assert cases[0]["reason_code"] == "BRAND_STANDARDS"
    assert cases[0]["status"] == "OPEN"

    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 1


def test_passed_audit_opens_no_default_case(api):
    """PRD §3.7: "A `PASS` closes the matter. A `FAIL` does not: the system opens
    a `DefaultCase` on the agreement with `reason_code` `BRAND_STANDARDS` in
    `OPEN` status, and the agreement's `open_cure_count` is recomputed to include
    it."

    Design: Corner/cross_cutting_layers/cascading_side_effects_audit_fail_creates_default_case
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    audit = get_success_data(
        api.create_compliance_audit(ag_id, create_audit_payload(audit_type="TECH_ADOPTION"), AUDITOR)
    )
    get_success_data(api.start_compliance_audit(audit["id"], AUDITOR))
    completed = get_success_data(
        api.complete_compliance_audit(audit["id"], {"finding": "PASS"}, AUDITOR)
    )
    assert completed["status"] == "COMPLETED"

    cases, _meta = validate_paginated(api.list_default_cases(ag_id, OPS))
    assert cases == []
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 0
