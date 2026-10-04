"""Corner queue — RBAC claims (1 of 2): role-exclusivity violations and
entity-backed Participant ownership."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_participant,
    create_irb_protocol_payload,
    create_study_payload,
    irb_decision_payload,
    make_participant_headers,
    setup_active_site_study,
    setup_contract,
    setup_contract_with_study,
    setup_study_with_sites,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]
PEER = TEST_USERS["peer_reviewer_headers"]


def test_agency_officer_cannot_create_study(api):
    """PRD §2.1: "Once a request is authenticated, each operation is restricted
    to the roles named for it in §4; an authenticated caller attempting an
    operation outside their role is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." (§4 names only `PrincipalInvestigator` for study creation.)

    Design: Corner/rbac/agency_officer_cannot_create_study
    """
    contract = setup_contract()
    resp = api.create_study(
        contract["id"], create_study_payload(title="S", research_question="Q"), AO
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    studies, _ = validate_paginated(api.list_studies(contract["id"], PI))
    assert len(studies) == 0, "no study created"


def test_study_director_cannot_decide_irb(api):
    """PRD §2.1: "Once a request is authenticated, each operation is restricted
    to the roles named for it in §4; an authenticated caller attempting an
    operation outside their role is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." (§4 names only `IRBReviewer` for the IRB decision.)

    Design: Corner/rbac/study_director_cannot_decide_irb
    """
    ctx = setup_contract_with_study()
    irb = validate_success(
        api.create_irb_protocol(ctx["study"]["id"], create_irb_protocol_payload(), PI),
        201,
    )
    validate_success(api.submit_irb_protocol(irb["id"], PI), 200)

    resp = api.irb_decision(
        irb["id"],
        irb_decision_payload(
            "APPROVED",
            approval_start="2026-09-01T00:00:00Z",
            approval_end="2027-09-01T00:00:00Z",
        ),
        SD,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    protocols, _ = validate_paginated(api.list_irb_protocols(ctx["study"]["id"], PI))
    assert next(p for p in protocols if p["id"] == irb["id"])["status"] == "SUBMITTED"


def test_peer_reviewer_cannot_publish_even_when_report_missing(api):
    """PRD §2.8: "Every mutating request passes through a fixed pipeline of
    validation stages, and the pipeline is ordered: the first failing stage
    determines the error returned, so a caller can never observe a later-stage
    error while an earlier-stage failure is present." (Authorization is stage
    2; path existence is stage 3 — so an unauthorized role sees
    `ERR_UNAUTHORIZED_ROLE`, never the `ERR_NOT_FOUND` a later stage would
    produce.)
    PRD §2.1: "an authenticated caller attempting an operation outside their
    role is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." (§4 names only
    `AgencyOfficer` for publish.)

    Design: Corner/rbac/peer_reviewer_cannot_publish_even_when_report_missing
    """
    resp = api.publish_report(NON_EXISTENT_UUID, PEER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.json()["data"]["error_id"] != "ERR_NOT_FOUND"


def test_participant_cannot_randomize(api):
    """PRD §2.1: "Once a request is authenticated, each operation is restricted
    to the roles named for it in §4; an authenticated caller attempting an
    operation outside their role is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." (§4 names only `PrincipalInvestigator` for randomization —
    the Participant role is denied even on its own record.)

    Design: Corner/rbac/participant_cannot_randomize
    """
    ctx = setup_active_site_study()
    p1 = add_participant(ctx["site"]["id"], external_ref="P001", consent=True)

    resp = api.randomize_participant(p1["id"], make_participant_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    participants, _ = validate_paginated(api.list_participants(PI))
    assert next(p for p in participants if p["id"] == p1["id"])["status"] == "CONSENTED"


def test_participant_read_other_participant_forbidden(api):
    """PRD §2.1: "A caller in the `Participant` role may therefore consent only
    on their own record, withdraw only their own record, and read only their
    own detail view — any attempt to act on a participant whose `id` differs
    from `X-User-ID` is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/participant_read_other_participant_forbidden
    """
    ctx = setup_study_with_sites()  # site A RECRUITED accepts participants
    p1 = add_participant(ctx["site"]["id"], external_ref="P001")
    p2 = add_participant(ctx["site"]["id"], external_ref="P002")

    own = validate_success(
        api.get_participant(p1["id"], make_participant_headers(p1["id"])), 200
    )
    assert own["id"] == p1["id"]

    resp = api.get_participant(p2["id"], make_participant_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
