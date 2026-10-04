"""Typed 404 sweep across every resource endpoint (PRD §2.6)."""
from test_helpers import (
    ADMIN,
    APPEALS,
    ApiErrorId,
    PANEL,
    api_client,
    create_hearing_room,
    file_po_response,
    request_hearing,
    schedule_payload,
    setup_instituted_proceeding,
    validate_error,
)

_BOGUS = "00000000-0000-0000-0000-000000000001"


def test_typed_not_found_sweep_across_resource_endpoints():
    """PRD §2.6: "When an endpoint path contains multiple resource
    identifiers — a brief beneath a proceeding, a declaration beneath a
    brief, a matter beneath a patent — the system validates the existence of
    each identifier in sequential, left-to-right order and rejects the
    request immediately with the 404 error corresponding to the *first*
    identifier that does not resolve." and "Body-referenced entities are
    validated after the path chain: a payload naming a missing party
    (`owner_id`, `petitioner_id`, or `defendant_party_id`) is rejected with
    `ERR_PARTY_NOT_FOUND`; a missing patent reference with
    `ERR_PATENT_NOT_FOUND`; and a missing hearing room named in a scheduling
    payload with `ERR_ROOM_NOT_FOUND`."

    Design: Corner/errors/typed_not_found_sweep_across_resource_endpoints
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-will", petitioner_name="PAU Corp",
        owner_name="OAU Corp",
    )
    file_po_response(world, 50)
    hearing = request_hearing(world["proceeding"]["id"],
                              world["petitioner_headers"])

    # 1. PATCH bogus matter.
    resp = api_client.patch_litigation_matter(
        _BOGUS, {"status": "STAYED", "expected_litigation_matter_version": 1},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_MATTER_NOT_FOUND, 404)

    # 2. Expert declaration on a bogus brief.
    resp = api_client.create_expert_declaration(
        _BOGUS, {"declarant_name": "Dr. No", "page_count": 5,
                 "contains_new_evidence": False},
        world["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_BRIEF_NOT_FOUND, 404)

    # 3. Rule on a bogus discovery request.
    resp = api_client.rule_discovery_request(_BOGUS, PANEL)
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_FOUND, 404)

    # 4. Resolve on a bogus amendment motion.
    resp = api_client.resolve_amendment_motion(_BOGUS, {"outcome": "GRANTED"},
                                               PANEL)
    validate_error(resp, ApiErrorId.ERR_MOTION_NOT_FOUND, 404)

    # 5. PATCH on a bogus hearing (path checked before the room body
    #    reference).
    resp = api_client.schedule_oral_hearing(
        _BOGUS,
        schedule_payload(_BOGUS, "2027-02-01T09:00:00Z", "2027-02-01T10:00:00Z"),
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_FOUND, 404)

    # 6. Decide on a bogus appeal.
    resp = api_client.decide_appeal(_BOGUS, {"outcome": "AFFIRMED"}, APPEALS)
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_FOUND, 404)

    # 7. Brief on a bogus proceeding.
    resp = api_client.create_brief(
        _BOGUS, {"brief_type": "PO_RESPONSE", "page_count": 50},
        world["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PROCEEDING_NOT_FOUND, 404)

    # 8. Patent create with a bogus owner_id (body FK existence).
    resp = api_client.create_patent(
        {"patent_number": "US10001055", "title": "Ghost Owner",
         "issue_date": "2020-01-01T00:00:00Z", "owner_id": _BOGUS,
         "total_claims": 2},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PARTY_NOT_FOUND, 404)

    # 9. Scheduling the real hearing into a bogus room.
    resp = api_client.schedule_oral_hearing(
        hearing["id"],
        schedule_payload(_BOGUS, "2027-02-01T09:00:00Z", "2027-02-01T10:00:00Z"),
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND, 404)
