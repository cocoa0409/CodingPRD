"""Proceeding/discovery state corners and the authentication gate
(PRD §2.1, §3.5, §3.6, §3.9).
"""
from test_helpers import (
    ApiErrorId,
    PANEL,
    api_client,
    assert_discovery_request,
    create_brief_payload,
    create_discovery_request,
    create_petition_payload,
    decide_appeal,
    file_petitioner_reply,
    file_po_response,
    file_po_sur_reply,
    get_proceeding,
    new_world,
    setup_decided_with_appeal,
    setup_instituted_proceeding,
    outcomes_payload,
    validate_error,
    validate_paginated,
    DEFAULT_CLOCK_ISO,
)


def test_closed_proceeding_after_affirmance_rejects_new_appeal():
    """PRD §3.9: "`AFFIRMED` and `DISMISSED` each close the trial — the
    proceeding moves `DECIDED → CLOSED`, a terminal phase admitting no
    further mutations" and "Appeal creation requires the proceeding to stand
    in `DECIDED` (`ERR_PROCEEDING_NOT_DECIDED`)".

    Design: Corner/state_machines/closed_proceeding_after_affirmance_rejects_new_appeal
    """
    world = setup_decided_with_appeal(
        institute_kw=dict(
            total_claims=2, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 50},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 48}],
            lead_judge="judge-vic",
        ),
        outcomes=outcomes_payload((1, "NOT_UNPATENTABLE"),
                                  (2, "NOT_UNPATENTABLE")),
        hearing_start="2027-01-15T10:00:00Z", hearing_end="2027-01-15T11:00:00Z",
    )
    decide_appeal(world["appeal"]["id"], "AFFIRMED")
    assert get_proceeding(world["proceeding"]["id"])["phase"] == "CLOSED"
    # A fresh appeal against the CLOSED proceeding is rejected.
    resp = api_client.create_appeal(
        world["proceeding"]["id"], world["owner_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_PROCEEDING_NOT_DECIDED, 409)


def test_routine_discovery_request_is_auto_granted_at_creation():
    """PRD §3.6: "A `ROUTINE` request is granted automatically at creation
    and lands directly in `GRANTED`; any `factor_scores` supplied with it are
    simply ignored. An `ADDITIONAL` request requires `factor_scores` of
    exactly five integers, each from 0 to 2 — any other shape is
    `ERR_VALIDATION` — and is created `PENDING` with a computed
    `garmin_score`".

    Design: Corner/state_machines/routine_discovery_request_is_auto_granted_at_creation
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 62}],
        lead_judge="judge-wade",
    )
    req = create_discovery_request(
        world["proceeding"]["id"], world["owner_headers"],
        discovery_type="ROUTINE",
    )
    assert_discovery_request(req)
    assert req["status"] == "GRANTED"
    # Factor-based scoring applies to ADDITIONAL only: no score is computed
    # for a ROUTINE request (field absent or null).
    assert req.get("garmin_score") is None


def test_duplicate_sur_reply_in_same_cycle_rejected():
    """PRD §3.5: "Acceptance of a `PO_SUR_REPLY` requires `SUR_REPLY_WINDOW`
    and leaves the phase unchanged — the sur-reply closes the briefing
    record, but the phase advances only when a hearing is later scheduled."
    and "Only one brief of each type may exist per briefing cycle, so a
    second filing of the same type within the same cycle is
    `ERR_BRIEF_SEQUENCE_VIOLATION`."

    Design: Corner/state_machines/duplicate_sur_reply_in_same_cycle_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-cleo",
    )
    file_po_response(world, 50)
    file_petitioner_reply(world, 25)
    first = file_po_sur_reply(world, 18)
    assert first["brief_type"] == "PO_SUR_REPLY"
    # The phase stayed SUR_REPLY_WINDOW, so the phase gate passes; the
    # one-brief-per-type-per-cycle rule stops the duplicate.
    resp = api_client.create_brief(
        world["proceeding"]["id"],
        create_brief_payload("PO_SUR_REPLY", 12),
        world["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_BRIEF_SEQUENCE_VIOLATION, 422)
    proceeding = get_proceeding(world["proceeding"]["id"])
    assert proceeding["phase"] == "SUR_REPLY_WINDOW"
    assert proceeding["total_overage_fee_cents"] == 0


def test_request_without_auth_headers_rejected_400():
    """PRD §2.1: "All interactions with the API must be authenticated through
    two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, specifying their operational capacity. If either header is
    missing or empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS`."

    Design: Corner/state_machines/request_without_auth_headers_rejected_400
    """
    world = new_world(petitioner_name="PBF Corp", owner_name="OBF Corp")
    payload = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        challenged_claims=[1],
        expected_patent_version=world["patent"]["version"],
    )
    # Neither X-User-ID nor X-User-Role is sent.
    resp = api_client.create_petition(payload, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 400)
    _, meta = validate_paginated(api_client.list_petitions(PANEL, params={}))
    assert meta["total_count"] == 0
