"""Corner coverage: role admission denials (ERR_FORBIDDEN_ROLE)."""

import test_helpers as th

E = th.ApiErrorId


def test_researcher_cannot_accession_or_activate(api):
    """PRD §3.3: "Accession is the legal moment custody passes to the
    Archives, and it belongs to a `ProcessingArchivist`, who supplies a
    `receipt_note` with the accession call."
    PRD §3.7: "A `ResearchRoomStaff` operator activates a `PENDING`
    registration at the desk, moving it to `ACTIVE` and stamping
    `card_expires_at`"
    PRD §2.1: "If the role is declared but not among the roles an endpoint
    admits, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/researcher_cannot_accession_or_activate
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(agency, schedule_number="SCH-DOJ-002")
    transfer = th.create_validated_transfer(agency, schedule)
    ada = th.register_researcher()  # PENDING, never activated
    researcher = th.make_researcher_headers(ada["id"])

    th.validate_error(
        api.accession_transfer(
            transfer["id"], th.accession_payload("researcher attempting accession"),
            headers=researcher,
        ),
        E.ERR_FORBIDDEN_ROLE,
    )
    th.validate_error(
        api.activate_researcher(ada["id"], headers=researcher),
        E.ERR_FORBIDDEN_ROLE,
    )

    transfer_after = th.get_success_data(
        api.get_transfer(
            transfer["id"], headers=th.TEST_USERS["processing_archivist_headers"]
        )
    )
    researcher_after = th.get_success_data(
        api.get_researcher(
            ada["id"], headers=th.TEST_USERS["research_room_staff_headers"]
        )
    )
    assert transfer_after["status"] == "VALIDATED"
    assert researcher_after["status"] == "PENDING"


def test_foia_officer_cannot_decide_appeal(api):
    """PRD §3.9: "Appellate decision belongs to a different authority. A
    `FoiaAppealsOfficer` decides an `APPEALED` request (`ERR_FOIA_NOT_APPEALED`,
    409, otherwise) by supplying an `appeal_decision` of `GRANT`, `UPHOLD`, or
    `REMAND`."
    PRD §2.1: "If the role is declared but not among the roles an endpoint
    admits, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/foia_officer_cannot_decide_appeal
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    ada = th.create_active_researcher()
    foia = th.create_appealed_foia(ada, bundle["collection"],
                                   description_of_records="role probe")

    th.validate_error(
        api.decide_foia_appeal(
            foia["id"], th.decide_appeal_payload("GRANT"),
            headers=th.TEST_USERS["foia_officer_2_headers"],
        ),
        E.ERR_FORBIDDEN_ROLE,
    )

    after = th.get_success_data(
        api.get_foia_request(foia["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    assert after["status"] == "APPEALED"


def test_anonymous_cannot_read_collections(api):
    """PRD §2.1: "`Anonymous` is the unauthenticated public caller and may do
    exactly one thing — self-register as a researcher; every other endpoint
    rejects `Anonymous` with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/anonymous_cannot_read_collections
    """
    th.set_clock()
    bundle = th.create_collection_bundle()
    th.validate_error(
        api.get_collection(
            bundle["collection"]["id"], headers=th.TEST_USERS["anonymous_headers"]
        ),
        E.ERR_FORBIDDEN_ROLE,
    )
