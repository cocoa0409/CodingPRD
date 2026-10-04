"""Docket registration and retrieval corners: party creation fields, patent
field round-trip, petition listing pagination, typed 404s, schema rejection,
hearing defaults, and event-record immutability (PRD §2.2–§2.5, §3.1, §3.7).
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    NON_EXISTENT_UUID,
    PANEL,
    accord,
    api_client,
    assert_institution_decision,
    assert_party,
    assert_patent,
    assert_same_instant,
    create_party,
    create_patent,
    decide_institution,
    file_petition,
    new_world,
    per_ground_scores,
    set_clock,
    setup_instituted_proceeding,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_party_creation_returns_declared_fields_and_version_1():
    """PRD §3.1: "Parties are registered with a legal `name`, a `party_type`
    of `PETITIONER` or `PATENT_OWNER` that fixes which side of a trial the
    party may act on, and an optional `counsel_firm` lead-counsel label that
    remains null when omitted."
    PRD §2.5: "An ISO 8601 timestamp in UTC with three fractional digits,
    indicating when the resource was created." — and PRD §2.4: "All system
    timestamps — `created_at`, `filing_date`, `accorded_date`,
    `institution_date`, `cycle_anchor_date`, `decided_at`, `issued_at` — are
    stamped from this clock".

    Design: Corner/entities/party_creation_returns_declared_fields_and_version_1
    """
    set_clock()
    resp = api_client.create_party(
        {"name": "Acme IP Holdings", "party_type": "PATENT_OWNER"}, ADMIN
    )
    data = validate_success(resp, 201)
    assert_party(data)
    assert data["name"] == "Acme IP Holdings"
    assert data["party_type"] == "PATENT_OWNER"
    assert data["counsel_firm"] is None
    assert_same_instant(data["created_at"], DEFAULT_CLOCK_ISO, "created_at")
    assert_same_instant(data["updated_at"], data["created_at"], "updated_at")


def test_patent_retrieval_round_trips_all_declared_fields():
    """PRD §3.1: "A newly registered patent stands in `ISSUED` status with
    `claims_alive` equal to `total_claims` and both `claims_cancelled_count`
    and `claims_amended_count` at zero".

    Design: Corner/entities/patent_retrieval_round_trips_all_declared_fields
    """
    set_clock()
    owner = create_party("Roundtrip Owner LLC", "PATENT_OWNER")
    patent = create_patent(
        owner["id"], total_claims=7, patent_number="US10000999",
        title="Roundtrip Gear", issue_date="2016-04-15T00:00:00Z",
    )
    data = validate_success(api_client.get_patent(patent["id"], PANEL), 200)
    assert_patent(data)
    assert data["patent_number"] == "US10000999"
    assert data["title"] == "Roundtrip Gear"
    assert_same_instant(data["issue_date"], "2016-04-15T00:00:00Z", "issue_date")
    assert data["status"] == "ISSUED"
    assert data["claims_alive"] == 7
    assert data["claims_cancelled_count"] == 0
    assert data["claims_amended_count"] == 0
    assert data["total_claims"] == 7


def test_petitions_list_paginates_and_reports_total_count_and_has_more():
    """PRD §2.3: "Paginated list responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`." and "The `limit` parameter specifies the
    maximum number of items to return; if not provided it defaults to 10,
    with a minimum of 1 and a maximum of 100. The `offset` parameter
    specifies the number of items to skip and defaults to 0."

    Design: Corner/entities/petitions_list_paginates_and_reports_total_count_and_has_more
    """
    world = new_world(petitioner_name="PC Corp", owner_name="OC Corp")
    for i in range(1, 4):
        pat = create_patent(world["owner"]["id"], total_claims=2,
                            patent_number=f"US1000100{i}",
                            title=f"Petal {chr(64 + i)}")
        file_petition(world["petitioner"]["id"], pat["id"],
                      challenged_claims=[1])
    page1, meta1 = validate_paginated(
        api_client.list_petitions(
            PANEL,
            params={"petitioner_id": world["petitioner"]["id"],
                    "limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api_client.list_petitions(
            PANEL,
            params={"petitioner_id": world["petitioner"]["id"],
                    "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    page_all, meta_all = validate_paginated(
        api_client.list_petitions(
            PANEL, params={"petitioner_id": world["petitioner"]["id"]}
        )
    )
    assert len(page_all) == 3
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0
    assert meta_all["has_more"] is False


def test_petition_get_with_unknown_id_returns_404():
    """PRD §2.6: "The full 404 family, one code per resource kind, is:
    `ERR_PARTY_NOT_FOUND`, `ERR_PATENT_NOT_FOUND`, `ERR_MATTER_NOT_FOUND`,
    `ERR_PETITION_NOT_FOUND`, `ERR_PROCEEDING_NOT_FOUND`,
    `ERR_BRIEF_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_MOTION_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, and
    `ERR_APPEAL_NOT_FOUND`."

    Design: Corner/entities/petition_get_with_unknown_id_returns_404
    """
    set_clock()
    resp = api_client.get_petition(NON_EXISTENT_UUID, PANEL)
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_FOUND, 404)


def test_patent_create_missing_total_claims_rejected():
    """PRD §3.1: "Patents enter the docket with a `patent_number` unique
    across the system, a `title`, an `issue_date` recording when the patent
    issued, an `owner_id` referencing the owning party, and a `total_claims`
    count of issued claims, which must be at least one."

    Design: Corner/entities/patent_create_missing_total_claims_rejected
    """
    set_clock()
    owner = create_party("Schema Owner LLC", "PATENT_OWNER")
    payload = {
        "patent_number": "US10001010",
        "title": "No Claims",
        "issue_date": "2020-01-01T00:00:00Z",
        "owner_id": owner["id"],
    }
    resp = api_client.create_patent(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_oral_hearing_argument_minutes_defaults_to_60():
    """PRD §3.7: "Either party to the proceeding — and only a party, on pain
    of `ERR_NOT_RESOURCE_OWNER` — may request oral argument, optionally
    sizing the session with `argument_minutes`, which defaults to 60 when
    omitted." and "A fresh hearing is created in `REQUESTED` status with
    `hearing_room_id`, `start_at`, and `end_at` all null."

    Design: Corner/entities/oral_hearing_argument_minutes_defaults_to_60
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 65}],
        lead_judge="judge-rick",
    )
    resp = api_client.create_oral_hearing(
        world["proceeding"]["id"], {}, world["petitioner_headers"]
    )
    hearing = validate_success(resp, 201)
    assert hearing["argument_minutes"] == 60
    assert hearing["status"] == "REQUESTED"
    assert hearing["hearing_room_id"] is None
    assert hearing["start_at"] is None
    assert hearing["end_at"] is None


def test_institution_decision_is_immutable_and_carries_no_version():
    """PRD §2.5: "Two resources are immutable event records rather than
    mutable entities: the `InstitutionDecision` and the
    `FinalWrittenDecision`. Each is written once and never modified, and each
    therefore carries only `id` and `created_at` — both `updated_at` and
    `version` are absent from these records."
    PRD §3.4: "The decision record is retrievable as an array holding zero or
    one entries."

    Design: Corner/entities/institution_decision_is_immutable_and_carries_no_version
    """
    world = new_world(petitioner_name="PE Corp", owner_name="OE Corp")
    petition = file_petition(
        world["petitioner"]["id"], world["patent"]["id"],
        challenged_claims=[1],
        grounds=[{"claim_number": 1, "basis": "OBVIOUSNESS_103"}],
        prior_art=[{"reference_type": "PRINTED_PUBLICATION",
                    "citation": "Nature 2017"}],
    )
    accord(petition["id"])
    decision = decide_institution(
        petition["id"],
        per_ground_scores((1, 55, "OBVIOUSNESS_103")),
        "judge-sara",
    )
    resp = api_client.get_institution_decision(petition["id"], PANEL)
    records = validate_success(resp, 200)
    assert isinstance(records, list) and len(records) == 1
    record = records[0]
    assert record["id"] == decision["decision_id"]
    assert_institution_decision(record)  # asserts no version / updated_at
    assert_same_instant(record["decided_at"], DEFAULT_CLOCK_ISO, "decided_at")
    assert record["outcome"] == "INSTITUTED"
    assert record["threshold_used"] == 40
