"""Corner coverage: entity creation, retrieval, listing, defaults, and
system-managed fields."""

import test_helpers as th

E = th.ApiErrorId
UNKNOWN_UUID_1 = "00000000-0000-4000-8000-000000000001"
UNKNOWN_UUID_2 = "00000000-0000-4000-8000-000000000002"


def test_agency_create_returns_201_with_system_fields(api):
    """PRD §4: "Operations that create a new resource — registering an agency,
    creating a schedule, initiating a transfer, opening a review, issuing
    referrals, registering a researcher, filing a pull, reproduction, or FOIA
    request, or imposing a presidential restriction — answer `201 Created`."
    PRD §2.5: "- `id` (string): a server-minted UUID, with no type prefix." and
    "- `version` (integer): starts at its initial value on creation and
    increments by one on every mutation — including mutations the resource
    suffers as the target of a cascade or a derived-field recompute triggered
    by another resource's operation."
    PRD §2.4: "Before any such call, the server's startup default is exactly
    `2026-09-01T00:00:00Z`; the clock must never fall back to wall-clock time
    under any circumstance."

    Design: Corner/entities/agency_create_returns_201_with_system_fields
    """
    th.set_clock()
    resp = api.create_agency(
        th.agency_payload("DOJ", "Department of Justice"),
        headers=th.TEST_USERS["admin_headers"],
    )
    assert resp.json()["response_type"] == "object"
    agency = th.validate_success(resp, 201)
    th.assert_agency(agency)
    assert agency["agency_code"] == "DOJ"
    assert agency["name"] == "Department of Justice"
    assert agency["version"] == 1
    assert th.same_instant(agency["created_at"], th.STARTUP_CLOCK_UTC)
    assert th.same_instant(agency["updated_at"], th.STARTUP_CLOCK_UTC)


def test_schedule_get_roundtrip_returns_stored_configuration(api):
    """PRD §3.1: "Creation supplies `agency_id`, `schedule_number`, `title`,
    `records_domain`, `disposition`, `classification_default`, and conditionally
    `transfer_lag_years`." and "A new schedule is born in `DRAFT` status."
    PRD §3.1: "Appraisal records the archivist's `appraisal_recommendation` —
    either `APPROVE` or `RETURN` — supplied with the call, and stamps
    `appraiser_id` with the archivist's `X-User-ID`."

    Design: Corner/entities/schedule_get_roundtrip_returns_stored_configuration
    """
    th.set_clock()
    agency = th.create_agency()
    created = th.create_draft_schedule(
        agency,
        schedule_number="SCH-DOJ-004",
        title="Counterintelligence Files",
        records_domain="FEDERAL",
        disposition="PERMANENT",
        transfer_lag_years=30,
        classification_default="TOP_SECRET",
    )
    resp = api.get_schedule(created["id"], headers=th.TEST_USERS["appraiser_headers"])
    schedule = th.validate_success(resp, 200)
    th.assert_schedule(schedule)
    assert schedule["transfer_lag_years"] == 30
    assert schedule["classification_default"] == "TOP_SECRET"
    assert schedule["records_domain"] == "FEDERAL"
    assert schedule["disposition"] == "PERMANENT"
    assert schedule["status"] == "DRAFT"
    assert schedule["appraiser_id"] is None
    assert schedule["decided_by"] is None


def test_schedules_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
    maximum of 100. The `offset` parameter specifies how many items to skip and
    defaults to 0."
    PRD §2.3: "The `meta` object of a paginated list response carries four
    pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/schedules_list_paginates_with_total_count_and_has_more
    """
    th.set_clock()
    agency = th.create_agency()
    officer = th.make_records_officer_headers(agency["id"])
    for number, disposition in (
        ("SCH-DOJ-101", "TEMPORARY"),
        ("SCH-DOJ-102", "TEMPORARY"),
        ("SCH-DOJ-103", "PERMANENT"),
    ):
        lag = 20 if disposition == "PERMANENT" else None
        th.create_draft_schedule(
            agency, schedule_number=number, title=number,
            disposition=disposition, transfer_lag_years=lag,
        )
    del officer  # listing is open to every declared role; read as archivist

    data, meta = th.validate_paginated(
        api.list_schedules(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"agency_id": agency["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data, meta = th.validate_paginated(
        api.list_schedules(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"agency_id": agency["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    data, meta = th.validate_paginated(
        api.list_schedules(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"agency_id": agency["id"]},
        )
    )
    assert len(data) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0

    data, meta = th.validate_paginated(
        api.list_schedules(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"agency_id": agency["id"], "status": "DRAFT"},
        )
    )
    assert len(data) == 3
    assert meta["total_count"] == 3


def test_transfer_get_with_unknown_id_returns_transfer_not_found(api):
    """PRD §2.6: "Path-segment identifiers must exist, validated left to right.
    Each segment maps to its entity-specific 404: `ERR_AGENCY_NOT_FOUND`,
    `ERR_SCHEDULE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
    `ERR_COLLECTION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND`, `ERR_RESEARCHER_NOT_FOUND`,
    `ERR_PULL_REQUEST_NOT_FOUND`, `ERR_REPRODUCTION_NOT_FOUND`,
    `ERR_FOIA_NOT_FOUND`, or `ERR_RESTRICTION_NOT_FOUND`."

    Design: Corner/entities/transfer_get_with_unknown_id_returns_transfer_not_found
    """
    th.set_clock()
    resp = api.get_transfer(
        th.NON_EXISTENT_UUID, headers=th.TEST_USERS["processing_archivist_headers"]
    )
    th.validate_error(resp, E.ERR_TRANSFER_NOT_FOUND)


def test_schedule_create_missing_title_returns_invalid_request(api):
    """PRD §2.6: "the generic `ERR_INVALID_REQUEST` for a missing required
    field, a wrong type, an out-of-enum value, or an empty string where
    non-empty is required)."
    PRD §3.1: "Creation supplies `agency_id`, `schedule_number`, `title`,
    `records_domain`, `disposition`, `classification_default`, and conditionally
    `transfer_lag_years`."

    Design: Corner/entities/schedule_create_missing_title_returns_invalid_request
    """
    th.set_clock()
    agency = th.create_agency()
    payload = th.schedule_payload(agency["id"], schedule_number="SCH-DOJ-104")
    payload.pop("title")
    resp = api.create_schedule(
        payload, headers=th.make_records_officer_headers(agency["id"])
    )
    th.validate_error(resp, E.ERR_INVALID_REQUEST)
    data, meta = th.validate_paginated(
        api.list_schedules(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"agency_id": agency["id"]},
        )
    )
    assert data == []
    assert meta["total_count"] == 0


def test_reproduction_create_omitting_rush_defaults_false(api):
    """PRD §3.8: "`rush` defaults to false when omitted."
    PRD §3.8: "Pages price in three tiers: the first 20 pages at 80 cents per
    page, the next 80 pages (pages 21 through 100) at 50 cents per page, and
    every page beyond 100 at 25 cents per page."
    PRD §3.8: "A new reproduction request starts in `QUOTED` status."

    Design: Corner/entities/reproduction_create_omitting_rush_defaults_false
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    resp = api.create_reproduction_request(
        th.reproduction_payload(bob["id"], bundle["collection"]["id"], 25, "DIGITAL_SCAN"),
        headers=th.make_researcher_headers(bob["id"]),
    )
    repro = th.validate_success(resp, 201)
    th.assert_reproduction_request(repro)
    assert repro["rush"] is False
    assert repro["fee_cents"] == 1850
    assert repro["fee_cents"] == th.expected_fee_cents(25, "JOURNALIST", False)
    assert repro["status"] == "QUOTED"


def test_collection_backlog_score_computed_at_accession(api):
    """PRD §3.3: "The score awards ten points per whole year of records age
    (computed under §2.9 against the logical clock), counting at most sixty
    years; adds a classification weight of 0 for `NONE`, 5 for `CONFIDENTIAL`,
    15 for `SECRET`, or 30 for `TOP_SECRET`; and adds a further 20 points when
    the collection's domain is `PRESIDENTIAL`."
    PRD §3.3: "Its `processing_status` starts at `UNPROCESSED`, its
    `digitization_status` at `NOT_REQUESTED`, its `digitization_priority` at
    null, and its `declass_outcome` at `NONE`." and "Its three demand counters
    — `pull_count_total`, `repro_pages_fulfilled`, and `foia_release_count` —
    all start at zero."

    Design: Corner/entities/collection_backlog_score_computed_at_accession
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    collection = th.read_collection(bundle["collection"]["id"])
    th.assert_collection(collection)
    assert collection["backlog_score"] == 265
    assert collection["backlog_score"] == th.expected_backlog_score(
        th.STARTUP_CLOCK_UTC, "2001-03-15T00:00:00Z", "SECRET", "FEDERAL"
    )
    assert collection["restriction_posture"] == "CLASSIFIED_REVIEW_REQUIRED"
    assert collection["processing_status"] == "UNPROCESSED"
    assert collection["digitization_status"] == "NOT_REQUESTED"
    assert collection["declass_outcome"] == "NONE"
    assert collection["pull_count_total"] == 0
    assert collection["repro_pages_fulfilled"] == 0
    assert collection["foia_release_count"] == 0


def test_transfer_create_system_fields_input_ignored(api):
    """PRD §3.2: "A successfully created transfer starts in `INITIATED`
    status."
    PRD §2.5: "Every resource in this API — agencies, schedules, transfers,
    collections, declassification reviews, equity referrals, researcher
    registrations, pull requests, reproduction requests, FOIA requests, and
    presidential restrictions — carries a standard set of system-managed
    fields"

    Design: Corner/entities/transfer_create_system_fields_input_ignored
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(agency, schedule_number="SCH-DOJ-002")
    payload = th.transfer_payload(
        schedule["id"], agency["id"],
        unit_count=10, linear_feet=2.0,
        status="ACCESSIONED", version=99, collection_id=UNKNOWN_UUID_1,
    )
    resp = api.create_transfer(
        payload, headers=th.make_records_officer_headers(agency["id"])
    )
    transfer = th.validate_success(resp, 201)
    th.assert_transfer(transfer)
    assert transfer["status"] == "INITIATED"
    assert transfer["version"] == 1
    assert transfer["collection_id"] is None


def test_schedule_create_out_of_enum_domain_returns_invalid_request(api):
    """PRD §3.1: "The `records_domain` is either `FEDERAL` or `PRESIDENTIAL`"
    PRD §2.6: "the generic `ERR_INVALID_REQUEST` for a missing required field,
    a wrong type, an out-of-enum value, or an empty string where non-empty is
    required)."

    Design: Corner/entities/schedule_create_out_of_enum_domain_returns_invalid_request
    """
    th.set_clock()
    agency = th.create_agency()
    payload = th.schedule_payload(
        agency["id"], schedule_number="SCH-DOJ-105", records_domain="ROYAL"
    )
    resp = api.create_schedule(
        payload, headers=th.make_records_officer_headers(agency["id"])
    )
    th.validate_error(resp, E.ERR_INVALID_REQUEST)
    data, meta = th.validate_paginated(
        api.list_schedules(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"agency_id": agency["id"]},
        )
    )
    assert data == []
    assert meta["total_count"] == 0


def test_transfer_create_body_fks_checked_in_input_order(api):
    """PRD §2.6: "Foreign-key identifiers in the request body must exist,
    validated in the endpoint's declared input order — for example,
    `schedule_id` before `agency_id` when initiating a transfer, and
    `researcher_id` before `collection_id` when requesting a pull. A missing
    reference yields the same entity-specific 404 family as rung 3."

    Design: Corner/entities/transfer_create_body_fks_checked_in_input_order
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(agency, schedule_number="SCH-DOJ-002")
    officer = th.make_records_officer_headers(agency["id"])

    both_unknown = th.transfer_payload(
        UNKNOWN_UUID_1, UNKNOWN_UUID_2, unit_count=10, linear_feet=2.0
    )
    th.validate_error(api.create_transfer(both_unknown, headers=officer),
                      E.ERR_SCHEDULE_NOT_FOUND)

    unknown_agency = th.transfer_payload(
        schedule["id"], UNKNOWN_UUID_2, unit_count=10, linear_feet=2.0
    )
    th.validate_error(api.create_transfer(unknown_agency, headers=officer),
                      E.ERR_AGENCY_NOT_FOUND)

    data, meta = th.validate_paginated(
        api.list_transfers(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"schedule_id": schedule["id"]},
        )
    )
    assert data == []
    assert meta["total_count"] == 0
