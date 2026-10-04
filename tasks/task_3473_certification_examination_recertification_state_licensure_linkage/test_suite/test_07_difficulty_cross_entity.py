"""Queue A — cross_entity_state_dependency: a gate on one endpoint reads the
state of a different entity (license creation reads the certification; attempt
scheduling reads the authorization).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    create_license_application_payload,
    create_state_policy,
    make_candidate_headers,
    refresh_certification,
    schedule_attempt_payload,
    setup_approved_application,
    setup_certified_candidate,
    validate_error,
)


def test_license_nremt_path_requires_active_certification(api):
    """PRD §3.8: "On the national (`NREMT`) path, the cited certification must
    stand `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`), its level's code must
    appear in the policy's `accepted_level_codes`
    (`ERR_LEVEL_NOT_ACCEPTED_IN_STATE`), and the concurrency field
    `expected_certification_version` must match the certification's current
    `version` (`ERR_STALE_VERSION`)."
    PRD §2.5: "Certifications `ACTIVE` whose `expires_on` is earlier than now
    become `LAPSED`."

    After the lapse sweep, a license application carrying the freshly re-read
    (current) certification version still fails — the rejection is the state
    gate, not staleness.

    Design: Difficulty/cross_entity_state_dependency/license_nremt_path_requires_active_certification
    """
    create_state_policy()
    ctx = setup_certified_candidate()
    advance_clock("2028-09-05T00:00:00Z")
    cert = refresh_certification(ctx["certification"]["id"])
    assert cert["status"] == "LAPSED"

    resp = api_client.create_license_application(
        create_license_application_payload(
            "WA", ctx["level"]["id"],
            certification_id=cert["id"],
            expected_certification_version=cert["version"],
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)


def test_attempt_scheduling_requires_att_issued(api):
    """PRD §3.4: "Scheduling is allowed only while the authorization is `ISSUED`
    and the scheduling instant is on or before its `expires_on`, and only while
    no prior attempt already references it — one attempt per authorization —
    with violations rejected as `ERR_ATT_NOT_ISSUABLE`."
    PRD §2.5: "Authorizations to test still `ISSUED` whose `expires_on` is
    earlier than now become `EXPIRED`."

    The authorization minted at the 2026-09-01 approval expires ninety calendar
    days later (2026-11-30); the 2026-12-01 sweep expires it, and scheduling
    against it is then rejected.

    Design: Difficulty/cross_entity_state_dependency/attempt_scheduling_requires_att_issued
    """
    ctx = setup_approved_application()
    sweep = advance_clock("2026-12-01T00:00:00Z")
    assert sweep["att_expired_count"] == 1

    resp = api_client.schedule_cognitive_exam_attempt(
        schedule_attempt_payload(
            ctx["att_id"], "2026-12-02T00:00:00Z", "2026-12-04T00:00:00Z",
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ATT_NOT_ISSUABLE)
