"""Extension requests: caps, window gate, the documentation approval gate, and
the two optimistic-concurrency rules (veteran version on assessment create,
authorization version on extension decide)."""
from test_helpers import (
    TEST_USERS, api_client, validate_error,
    accept_documentation, approve_extension, cancel_referral,
    complete_appointment_with_doc, create_eligibility_assessment_payload,
    create_extension_request, create_extension_request_payload, create_station,
    create_veteran, decide_extension_request_payload, get_authorization,
    list_extension_requests, run_assessment, schedule_appointment,
    setup_episode,
)

COORD = TEST_USERS["care_coordinator_headers"]
CLERK = TEST_USERS["eligibility_clerk_headers"]


def test_extension_approval_blocked_until_documentation_accepted():
    """PRD §3.4: "Approval carries one further regulatory gate: every
    documentation record of the authorization must be accepted — none may sit
    in `AWAITED`, `RECEIVED`, or `OVERDUE` — or the approval is rejected with
    `ERR_DOCS_NOT_ACCEPTED` (HTTP 422)."
    PRD §3.4: "An approval widens the episode in place: the authorization's
    `extended_visits` increases by `requested_visits`, its `end_date_exclusive`
    is recomputed to absorb the `requested_extra_days`, and the
    authorization's `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/extension_approval_blocked_until_documentation_accepted
    """
    env = setup_episode(authorized_visits=2, duration_days=300)
    auth = env["authorization"]
    appt = schedule_appointment(auth)
    appt, doc = complete_appointment_with_doc(appt, env["provider"])
    ext = create_extension_request(auth, requested_visits=5,
                                   requested_extra_days=10)

    # The AWAITED documentation blocks approval.
    current = get_authorization(auth["id"])
    resp = api_client.decide_extension_request(
        auth["id"], ext["id"],
        decide_extension_request_payload("APPROVED", current["version"]),
        COORD,
    )
    validate_error(resp, "ERR_DOCS_NOT_ACCEPTED")
    exts, _m = list_extension_requests(auth["id"])
    assert exts[0]["status"] == "PENDING"

    # Once the documentation is accepted, the same decision succeeds.
    accept_documentation(appt, env["provider"])
    approved = approve_extension(auth["id"], ext["id"])
    assert approved["status"] == "APPROVED"
    after = get_authorization(auth["id"])
    assert after["extended_visits"] == 5
    assert after["end_date_exclusive"] == "2027-07-12"  # 2026-09-05 + 300d + 10d


def test_occ_stale_veteran_version_on_assessment_create_rejected():
    """PRD §2.6: "A `POST
    /community-care/veterans/{id}/eligibility-assessments` request must carry
    `expected_veteran_version` equal to the target veteran's current
    `version`. If another writer has advanced the veteran's version since the
    client last read it — for example because a prior successful assessment
    creation for the same veteran superseded the older current assessment and
    bumped the veteran's version — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412), because the caller's view of which
    assessment is current is out of date."

    Design: Corner/cross_cutting_layers/occ_stale_veteran_version_on_assessment_create_rejected
    """
    station = create_station()
    veteran = create_veteran(station, full_name="V OCC")
    observed = veteran["version"]
    run_assessment(veteran["id"])  # bumps the veteran version

    stale = api_client.create_eligibility_assessment(
        veteran["id"],
        create_eligibility_assessment_payload(
            observed, service_code="CARD", service_category="SPECIALTY_CARE"
        ),
        CLERK,
    )
    validate_error(stale, "ERR_STALE_VERSION")

    fresh = run_assessment(veteran["id"], service_code="CARD",
                           service_category="SPECIALTY_CARE")
    assert fresh["status"] == "CURRENT"


def test_occ_stale_authorization_version_on_extension_decide_rejected():
    """PRD §2.6: "A `POST
    /community-care/referral-authorizations/{id}/extension-requests/{extId}/decide`
    request must carry `expected_referral_authorization_version` equal to the
    parent authorization's current `version`. If the authorization's version
    has advanced since the reviewer last observed it — for example because an
    approved extension mutated the episode scope and bumped the version — the
    decision is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
    reviewer from deciding on an obsolete episode scope."

    Design: Corner/cross_cutting_layers/occ_stale_authorization_version_on_extension_decide_rejected
    """
    env = setup_episode(authorized_visits=2, duration_days=60)
    auth = env["authorization"]
    ext = create_extension_request(auth, requested_visits=2,
                                   requested_extra_days=0)
    observed = get_authorization(auth["id"])["version"]

    # The first appointment flips AUTHORIZED -> ACTIVE, a mutation that bumps
    # the authorization's version (PRD §2.4).
    schedule_appointment(auth)

    stale = api_client.decide_extension_request(
        auth["id"], ext["id"],
        decide_extension_request_payload("APPROVED", observed),
        COORD,
    )
    validate_error(stale, "ERR_STALE_VERSION")

    approved = approve_extension(auth["id"], ext["id"])
    assert approved["status"] == "APPROVED"
    assert get_authorization(auth["id"])["extended_visits"] == 2


def test_extension_create_on_cancelled_auth_returns_window_closed():
    """PRD §3.4: "Extensions can only be requested while the authorization is
    `AUTHORIZED` or `ACTIVE`; once the episode has moved on, the attempt fails
    with `ERR_EXTENSION_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/extension_create_on_cancelled_auth_returns_window_closed
    """
    env = setup_episode()
    auth = env["authorization"]
    cancel_referral(auth)

    resp = api_client.create_extension_request(
        auth["id"],
        create_extension_request_payload(requested_visits=2,
                                         requested_extra_days=0),
        COORD,
    )
    validate_error(resp, "ERR_EXTENSION_WINDOW_CLOSED")


def test_extension_create_cap_violation():
    """PRD §3.4: "The request must stay within the extension caps: at most 12
    additional visits and at most 180 additional days, with the visit ask at
    least 1 and the day ask at least 0; an ask above either cap is rejected
    with `ERR_EXTENSION_CAP` (HTTP 409)."

    Design: Corner/validations/extension_create_cap_violation
    """
    env = setup_episode()
    auth = env["authorization"]

    resp_visits = api_client.create_extension_request(
        auth["id"],
        create_extension_request_payload(requested_visits=13,
                                         requested_extra_days=0),
        COORD,
    )
    validate_error(resp_visits, "ERR_EXTENSION_CAP")

    resp_days = api_client.create_extension_request(
        auth["id"],
        create_extension_request_payload(requested_visits=2,
                                         requested_extra_days=181),
        COORD,
    )
    validate_error(resp_days, "ERR_EXTENSION_CAP")

    exts, meta = list_extension_requests(auth["id"])
    assert meta["total_count"] == 0 and exts == []
