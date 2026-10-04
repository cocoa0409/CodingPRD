"""Role-based access denials, including the per-outcome role splits and
per-resource ownership checks (PRD §2.1, §2.11, §3.3, §3.5, §3.7, §3.9).
"""
from test_helpers import (
    ADMIN,
    APPEALS,
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    PANEL,
    api_client,
    assert_same_instant,
    create_brief_payload,
    create_party,
    create_petition_payload,
    make_petitioner_headers,
    new_world,
    setup_instituted_proceeding,
    validate_error,
    validate_success,
)

_BOGUS = "00000000-0000-0000-0000-000000000001"


def test_clock_set_forbidden_for_board_panel_role():
    """PRD §2.1: "`PlatformAdmin` is the docketing administrator: it
    registers parties, patents, hearing rooms, and litigation dockets, and it
    alone operates the logical clock." and "An attempt to perform an action
    outside the caller's designated role — or to request an outcome reserved
    for another role — is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/roles/clock_set_forbidden_for_board_panel_role
    """
    resp = api_client.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, PANEL)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    # No mutation occurred: a fresh resource is stamped from the default
    # logical clock, 2026-09-01T00:00:00Z (PRD §2.4).
    party = validate_success(
        api_client.create_party({"name": "Clock Witness LLC",
                                 "party_type": "PETITIONER"}, ADMIN),
        201,
    )
    assert_same_instant(party["created_at"], DEFAULT_CLOCK_ISO, "created_at")


def test_party_registration_forbidden_for_petitioner_role():
    """PRD §2.1: "`PlatformAdmin` is the docketing administrator: it
    registers parties, patents, hearing rooms, and litigation dockets, and it
    alone operates the logical clock."

    Design: Corner/roles/party_registration_forbidden_for_petitioner_role
    """
    resp = api_client.create_party(
        {"name": "Self Registrar Inc", "party_type": "PETITIONER"},
        make_petitioner_headers("00000000-0000-0000-0000-000000000000"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_petition_filing_forbidden_for_patent_owner_role():
    """PRD §3.3: "A `Petitioner` opens a review by filing a petition against
    a registered patent." The endpoint table (PRD §4) restricts
    `POST /ptab/petitions` to the Petitioner role, and PRD §2.11 puts the
    role check at category (2), before existence and fee logic.

    Design: Corner/roles/petition_filing_forbidden_for_patent_owner_role
    """
    world = new_world(owner_name="OW Corp")
    payload = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["owner"]["id"],
        challenged_claims=[1],
        expected_patent_version=world["patent"]["version"],
    )
    resp = api_client.create_petition(payload, world["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_appeal_disposition_forbidden_for_board_panel_role():
    """PRD §3.9: "Disposition belongs to the `AppealsCourt` alone". The role
    check (category (2)) precedes existence (category (3)) per PRD §2.11, so
    even a bogus appeal id draws 403, not 404.

    Design: Corner/roles/appeal_disposition_forbidden_for_board_panel_role
    """
    resp = api_client.decide_appeal(_BOGUS, {"outcome": "AFFIRMED"}, PANEL)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_panel_cannot_waive_hearing_outcome():
    """PRD §3.7: "Marking the hearing held is panel-only; waiver belongs to a
    party to the proceeding — petitioner or patent owner — and a non-party
    waiver is `ERR_NOT_RESOURCE_OWNER`; continuance is panel-only. Any other
    role–outcome pairing is `ERR_FORBIDDEN_ROLE`".

    Design: Corner/roles/panel_cannot_waive_hearing_outcome
    """
    resp = api_client.resolve_oral_hearing(_BOGUS, {"outcome": "WAIVED"}, PANEL)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_patent_owner_cannot_grant_amendment_motion():
    """PRD §3.6: "Only the panel may grant or deny; only the patent owner may
    withdraw. A role reaching for an outcome reserved for another role is
    `ERR_FORBIDDEN_ROLE`".

    Design: Corner/roles/patent_owner_cannot_grant_amendment_motion
    """
    resp = api_client.resolve_amendment_motion(
        _BOGUS, {"outcome": "GRANTED"},
        {"X-User-ID": "00000000-0000-0000-0000-000000000000",
         "X-User-Role": "PatentOwner", "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_reply_by_petitioner_who_is_not_the_proceedings_petitioner_forbidden():
    """PRD §3.5: "the `PETITIONER_REPLY` only by the proceeding's petitioner;
    violations are rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/roles/reply_by_petitioner_who_is_not_the_proceedings_petitioner_forbidden
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-xerxes", petitioner_name="PAV1 Corp",
        owner_name="OAV Corp",
    )
    stranger = create_party("PAV2 Corp", "PETITIONER")
    resp = api_client.create_brief(
        world["proceeding"]["id"],
        create_brief_payload("PETITIONER_REPLY", 30),
        make_petitioner_headers(stranger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


def test_po_response_by_party_that_does_not_own_the_patent_forbidden():
    """PRD §2.1: "When `X-User-Role` is `PatentOwner`, `X-User-ID` is the
    `id` of the owning `Party` referenced by the challenged patent's
    `owner_id`, and ownership checks compare that owner reference to
    `X-User-ID`." PRD §3.5: "the `PO_RESPONSE` and `PO_SUR_REPLY` may be
    filed only by the patent's owner".

    Design: Corner/roles/po_response_by_party_that_does_not_own_the_patent_forbidden
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-yara", petitioner_name="PAW Corp",
        owner_name="OAW Corp",
    )
    other_owner = create_party("OAX Corp", "PATENT_OWNER")
    resp = api_client.create_brief(
        world["proceeding"]["id"],
        create_brief_payload("PO_RESPONSE", 50),
        {"X-User-ID": other_owner["id"], "X-User-Role": "PatentOwner",
         "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


def test_petition_filed_with_petitioner_id_other_than_caller_forbidden():
    """PRD §3.3: "The payload names the `patent_id` of the challenged patent
    and a `petitioner_id` that must reference an existing party whose
    `party_type` is `PETITIONER` and must equal the caller's `X-User-ID` —
    the former kind of mismatch is `ERR_VALIDATION`, the latter
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/roles/petition_filed_with_petitioner_id_other_than_caller_forbidden
    """
    world = new_world(petitioner_name="PAY1 Corp", owner_name="OAY Corp")
    pay2 = create_party("PAY2 Corp", "PETITIONER")
    payload = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        challenged_claims=[1],
        expected_patent_version=world["patent"]["version"],
    )
    # Filed under PAY1's identity by PAY2's credentials.
    resp = api_client.create_petition(payload, make_petitioner_headers(pay2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
