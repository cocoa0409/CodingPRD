"""The registry surface and the appointment record itself.

Creation defaults, the seeded system fields, the derived compensation figures a
draft already carries, body-shape refusals, the entity-specific 404, and the
flat topology's reverse-navigable filters.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_award_ledger,
    assert_money,
    create_appointment_payload,
    create_faculty_mentor_payload,
    create_laboratory_payload,
    create_postdoc_payload,
    draft_appointment,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_officer_headers,
    read_appointment,
    read_funding_source,
    register_faculty_mentor,
    register_funding_source,
    register_postdoc,
    validate_error,
    validate_paginated,
    validate_success,
)

_SHARED_AWARD = {
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
}

_ASSOCIATE_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 62000.00,
}


def test_registering_a_scholar_seeds_its_status_and_its_realized_rank_ledger():
    """The scholar record comes back complete on the creating response.

    PRD 3.1: "On registration the scholar's `status` is set to `PROSPECTIVE` and
    the realized rank ledger `total_months_in_rank` is seeded to whatever
    `prior_external_months_in_rank` was supplied."

    Design: Corner/entities/postdoc_creation_returns_declared_defaults_and_a_zero_rank_ledger
    """
    officer = make_officer_headers("officer-pa-20")

    response = api_client.create_postdoc(
        create_postdoc_payload(
            full_name="Anya Krylova", citizenship_country="RU",
            requires_sponsorship=True, phd_award_date="2026-03-20",
            prior_external_months_in_rank=6, o1_endorsement_on_file=False,
            j1_two_year_bar_flag=False, restricted_party_flag=False,
        ),
        officer,
    )
    scholar = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object", (
        f"A single resource carries response_type object, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert is_valid_uuid(scholar["id"]), (
        f"The id must be a server-minted UUID, got {scholar['id']!r}"
    )
    assert scholar["status"] == "PROSPECTIVE", (
        f"Expected PROSPECTIVE on registration, got {scholar['status']}"
    )
    assert scholar["total_months_in_rank"] == 6, (
        "The realized ledger is seeded from prior_external_months_in_rank, got "
        f"{scholar['total_months_in_rank']}"
    )
    assert scholar["citizenship_country"] == "RU"
    assert scholar["requires_sponsorship"] is True
    assert scholar["prior_external_months_in_rank"] == 6
    assert scholar["version"] == 1, (
        f"version starts at 1, got {scholar['version']}"
    )


def test_a_freshly_registered_award_reads_back_with_an_untouched_ledger():
    """The derived balance is present from registration, not from first use.

    PRD 3.1: "At registration the award's `verification_status` is `UNVERIFIED`,
    its `encumbered_usd` is 0.00, and its `available_balance_usd` equals
    `annual_budget_usd`."

    Design: Corner/entities/funding_source_retrieval_exposes_the_untouched_award_ledger
    """
    officer = make_officer_headers("officer-pa-20")
    award = register_funding_source(
        verify=False, headers=officer,
        sponsor_name="Wellcome Trust W-2000", funding_type="FOUNDATION_GRANT",
        salary_floor_policy="INSTITUTIONAL_MIN", award_start_date="2026-09-01",
        award_end_date="2027-12-31", annual_budget_usd=250000.00,
    )

    reread = validate_success(
        api_client.get_funding_source(award["id"], TEST_USERS["hr_approver_headers"])
    )

    assert reread["verification_status"] == "UNVERIFIED", (
        f"Expected UNVERIFIED, got {reread['verification_status']}"
    )
    assert_award_ledger(reread, 0.00, 250000.00)
    assert reread["verified_at"] is None, (
        f"verified_at is null until the first verification, got {reread['verified_at']!r}"
    )
    assert reread["verified_by_user_id"] is None
    assert reread["requires_mentoring_plan"] is False, (
        "requires_mentoring_plan defaults to false"
    )
    assert reread["requires_idp"] is False, "requires_idp defaults to false"


def _three_drafts_under_one_mentor():
    """One mentor, one VERIFIED award and three scholars, each holding exactly one
    DRAFT appointment on the same term."""
    officer = make_officer_headers("officer-pa-21")
    mentor = register_faculty_mentor(
        officer, full_name="N. Abebe", department="Public Health",
        mentor_training_valid_through="2029-09-30", max_concurrent_postdocs=3,
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-2100",
        annual_budget_usd=600000.00, **_SHARED_AWARD,
    )
    appointments = []
    for name, phd_date in (("Page One", "2026-01-05"), ("Page Two", "2026-01-06"),
                           ("Page Three", "2026-01-07")):
        scholar = register_postdoc(
            officer, full_name=name, citizenship_country="US",
            requires_sponsorship=False, phd_award_date=phd_date,
        )
        appointments.append(
            draft_appointment(
                scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM,
            )
        )
    return officer, [a["id"] for a in appointments]


def test_appointment_listing_pages_with_limit_offset_total_count_and_has_more():
    """total_count is the unpaged count and the offset does not move it.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of records matching the filters before pagination is applied and
    `has_more` is true when records remain beyond the current page."

    Design: Corner/entities/appointment_listing_pages_with_limit_offset_total_count_and_has_more
    """
    officer, appointment_ids = _three_drafts_under_one_mentor()

    first_response = api_client.list_appointments(officer, {"limit": 2, "offset": 0})
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", (
        "A collection carries response_type array"
    )
    assert len(first_page) == 2, (
        f"limit 2 caps the page at two rows, got {len(first_page)}"
    )
    assert first_meta["total_count"] == 3, (
        f"Expected the unpaged count 3, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "One row remains beyond the first page"
    )

    second_page, second_meta = validate_paginated(
        api_client.list_appointments(officer, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, (
        f"Expected the remaining single row, got {len(second_page)}"
    )
    assert second_meta["total_count"] == 3, (
        f"The offset must not move total_count, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "Nothing remains beyond the second page"
    )
    assert first_page[0]["id"] != second_page[0]["id"], (
        "The two pages must not repeat a row"
    )
    assert {row["id"] for row in first_page + second_page} == set(appointment_ids), (
        "The union of the two pages is exactly the three drafted appointments"
    )


def test_an_unknown_appointment_id_returns_appointment_not_found():
    """A well-formed but unused identifier is a 404, not an empty 200.

    PRD 2.11 rule 3: "Existence of every referenced identifier, path identifiers
    first in path order and then body foreign keys in declaration order — the
    entity-specific 404 codes listed in section 2.7, on every operation that
    carries a path identifier or a foreign-key body field."

    Design: Corner/entities/appointment_get_with_an_unknown_id_returns_appointment_not_found
    """
    officer = make_officer_headers("officer-pa-22")

    response = api_client.get_appointment(NON_EXISTENT_UUID, officer)
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error", (
        f"Expected response_type error, got {body['response_type']!r}"
    )
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
        "The error envelope carries a human-readable message"
    )


def test_a_missing_annual_salary_is_rejected_as_an_invalid_request():
    """A body-shape failure answers before the unverified award is ever consulted.

    PRD 2.11 rule 5: "Request shape — `ERR_INVALID_REQUEST` (400), on every write
    operation. This covers a missing required field, an enum field whose value is
    not a declared member, a date that is not ISO 8601, a negative numeric field,
    a `term_end_date` that is not strictly after `term_start_date`, an
    `access_end_date` that is not strictly after `access_start_date`, and a
    `bench_seats` value below 1."

    Design: Corner/entities/appointment_create_missing_annual_salary_is_rejected_as_invalid_request
    """
    officer = make_officer_headers("officer-pa-22")
    mentor = register_faculty_mentor(
        officer, full_name="O. Bergstrom", department="Linguistics",
        mentor_training_valid_through="2029-09-30",
    )
    award = register_funding_source(
        verify=False, headers=officer, sponsor_name="NEH-2200",
        annual_budget_usd=300000.00, **_SHARED_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Rhys Calloway", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-02-14",
    )

    payload = create_appointment_payload(
        scholar["id"], mentor["id"], award["id"], **_ASSOCIATE_TERM
    )
    payload.pop("annual_salary_usd")

    validate_error(
        api_client.create_appointment(payload, officer),
        ApiErrorId.ERR_INVALID_REQUEST.value, 400,
    )

    _, meta = validate_paginated(
        api_client.list_appointments(officer, {"postdoc_id": scholar["id"]})
    )
    assert meta["total_count"] == 0, (
        f"A refused draft must persist nothing, got {meta['total_count']}"
    )


def test_omitted_optional_inputs_fall_back_to_declared_defaults():
    """Three registries created with every optional input left out.

    PRD 3.1: "Four further inputs are optional and each defaults to a value that
    assumes the least complicated case." PRD 3.1: "`max_concurrent_postdocs` is
    the institutional ceiling on simultaneously active appointments this mentor
    may hold; it defaults to 3 and must be at least 1 and no more than 12." PRD
    3.1: "an optional `decontamination_buffer_days` between 0 and 30 that defaults
    to 0 and is applied to the leading edge of every access interval in the space,
    and an optional `status` of `OPEN` or `CLOSED` that defaults to `OPEN`"

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    officer = make_officer_headers("officer-pa-23")

    scholar = validate_success(
        api_client.create_postdoc(
            create_postdoc_payload(
                full_name="Minimal Scholar", citizenship_country="US",
                requires_sponsorship=False, phd_award_date="2026-07-01",
            ),
            officer,
        ),
        expected_status=201,
    )
    assert scholar["prior_external_months_in_rank"] == 0, (
        f"Expected the declared default 0, "
        f"got {scholar['prior_external_months_in_rank']}"
    )
    assert scholar["o1_endorsement_on_file"] is False
    assert scholar["j1_two_year_bar_flag"] is False
    assert scholar["restricted_party_flag"] is False
    assert scholar["requires_sponsorship"] is False, (
        "requires_sponsorship is required, not defaulted, and was supplied false"
    )

    mentor = validate_success(
        api_client.create_faculty_mentor(
            create_faculty_mentor_payload(
                full_name="Minimal Mentor", department="Philosophy",
                mentor_training_valid_through="2029-12-31",
            ),
            officer,
        ),
        expected_status=201,
    )
    assert mentor["max_concurrent_postdocs"] == 3, (
        f"Expected the declared default 3, got {mentor['max_concurrent_postdocs']}"
    )
    assert mentor["active_postdoc_count"] == 0, (
        f"The derived count begins at 0, got {mentor['active_postdoc_count']}"
    )

    laboratory = validate_success(
        api_client.create_laboratory(
            create_laboratory_payload(
                name="Minimal Bay", biosafety_level="BSL2", bench_capacity=4,
            ),
            officer,
        ),
        expected_status=201,
    )
    assert laboratory["decontamination_buffer_days"] == 0, (
        f"Expected the declared default 0, "
        f"got {laboratory['decontamination_buffer_days']}"
    )
    assert laboratory["status"] == "OPEN", (
        f"Expected the declared default OPEN, got {laboratory['status']}"
    )
    assert laboratory["bench_capacity"] == 4


def test_drafting_derives_every_computed_field_from_the_supplied_inputs():
    """One create call publishes the rank ledger, the floor and the benefits.

    PRD 3.2: "Drafting is the first point at which the compensation figures are
    computed. The rank quantities above are produced first because the salary
    floor depends on them; the policy floor and the benefits determination
    described in the next section are then computed and stored on the draft,
    before any offer exists." PRD 3.3: "Under `NIH_SCALE` the five bands read
    61008, 61428, 62124, 64536 and 67284 US dollars in band order."

    Design: Corner/entities/appointment_create_derives_every_computed_field_from_the_supplied_inputs
    """
    officer = make_officer_headers("officer-pa-24")
    mentor = register_faculty_mentor(
        officer, full_name="Q. Ivanova", department="Mathematics",
        mentor_training_valid_through="2029-10-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF DMS-2400",
        annual_budget_usd=300000.00, **_SHARED_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Sable Ortiz", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-30",
    )

    appointment = validate_success(
        api_client.create_appointment(
            create_appointment_payload(
                scholar["id"], mentor["id"], award["id"],
                **dict(_ASSOCIATE_TERM, annual_salary_usd=68000.00),
            ),
            officer,
        ),
        expected_status=201,
    )

    assert appointment["term_months"] == 12, (
        f"Expected term_months 12, got {appointment['term_months']}"
    )
    assert appointment["months_in_rank_at_start"] == 0, (
        f"No predecessor and no prior external service, "
        f"got {appointment['months_in_rank_at_start']}"
    )
    assert appointment["cumulative_months_in_rank_at_end"] == 12, (
        f"Expected cumulative_months_in_rank_at_end 12, "
        f"got {appointment['cumulative_months_in_rank_at_end']}"
    )
    assert_money(appointment["salary_floor_usd"], 61008.00, "salary_floor_usd")
    assert appointment["benefits_package"] == "EMPLOYEE_FULL", (
        f"Expected EMPLOYEE_FULL, got {appointment['benefits_package']}"
    )
    assert_money(appointment["encumbrance_usd"], 0.00, "encumbrance_usd")

    assert_award_ledger(read_funding_source(award["id"]), 0.00, 300000.00)


def test_drafting_seeds_the_system_fields_the_client_never_supplies():
    """Neither state dimension nor the audit anchor is client-settable.

    PRD 3.2: "The draft is created with `appointment_status` `DRAFT`,
    `compliance_status` `PENDING_REVIEW`, and `prepared_by_user_id` set to the
    drafting officer's `X-User-ID` — the value that anchors every
    segregation-of-duties check later in the appointment's life."

    Design: Corner/entities/appointment_create_seeds_system_fields_the_client_never_supplies
    """
    officer = make_officer_headers("officer-pa-25")
    mentor = register_faculty_mentor(
        officer, full_name="R. Kirchner", department="History",
        mentor_training_valid_through="2029-11-30",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="Mellon-2500", funding_type="FOUNDATION_GRANT",
        salary_floor_policy="NIH_SCALE", award_start_date="2026-09-01",
        award_end_date="2027-12-31", annual_budget_usd=300000.00,
    )
    scholar = register_postdoc(
        officer, full_name="Talia Boone", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-01",
    )

    appointment = validate_success(
        api_client.create_appointment(
            create_appointment_payload(
                scholar["id"], mentor["id"], award["id"], **_ASSOCIATE_TERM
            ),
            officer,
        ),
        expected_status=201,
    )

    assert appointment["appointment_status"] == "DRAFT", (
        f"Expected DRAFT, got {appointment['appointment_status']}"
    )
    assert appointment["compliance_status"] == "PENDING_REVIEW", (
        f"Expected PENDING_REVIEW, got {appointment['compliance_status']}"
    )
    assert appointment["prepared_by_user_id"] == officer["X-User-ID"], (
        "prepared_by_user_id is taken from the header, not from the body, got "
        f"{appointment['prepared_by_user_id']!r}"
    )
    assert appointment["version"] == 1, (
        f"version starts at 1, got {appointment['version']}"
    )
    assert appointment["salary_exception_floor_usd"] is None, (
        "Both exception fields are null until an exception has been approved"
    )
    assert appointment["salary_exception_approved_by_user_id"] is None
    assert appointment["withdraw_reason"] is None, (
        "withdraw_reason is null on any appointment that is not WITHDRAWN"
    )
    assert appointment["reinstated_count"] == 0, (
        f"reinstated_count starts at 0, got {appointment['reinstated_count']}"
    )
    assert is_iso8601_timestamp(appointment["created_at"]), (
        f"created_at must be an ISO 8601 instant, got {appointment['created_at']!r}"
    )
    assert is_iso8601_timestamp(appointment["updated_at"]), (
        f"updated_at must be an ISO 8601 instant, got {appointment['updated_at']!r}"
    )


def test_an_undeclared_enum_and_an_inverted_term_are_both_invalid_requests():
    """Neither body-shape failure may be dressed up as a semantic refusal.

    PRD 3.2: "a `title_classification` of `POSTDOC_FELLOW`,
    `POSTDOC_SCHOLAR_EMPLOYEE` or `POSTDOC_ASSOCIATE`, an `employment_class` of
    either `EMPLOYEE` or `FELLOWSHIP`, the `term_start_date` and `term_end_date`
    bounding the term as ISO 8601 dates". PRD 2.11 rule 5: "This covers a missing
    required field, an enum field whose value is not a declared member, a date
    that is not ISO 8601, a negative numeric field, a `term_end_date` that is not
    strictly after `term_start_date`".

    Design: Corner/entities/appointment_create_rejects_an_undeclared_enum_and_an_inverted_term
    """
    officer = make_officer_headers("officer-pa-26")
    mentor = register_faculty_mentor(
        officer, full_name="S. Duarte", department="Sociology",
        mentor_training_valid_through="2029-11-30",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF SES-2600",
        annual_budget_usd=300000.00, **_SHARED_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Umar Sesay", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-05",
    )

    undeclared_enum = api_client.create_appointment(
        create_appointment_payload(
            scholar["id"], mentor["id"], award["id"],
            **dict(_ASSOCIATE_TERM, title_classification="POSTDOC_SUPERVISOR"),
        ),
        officer,
    )
    validate_error(undeclared_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    inverted_term = api_client.create_appointment(
        create_appointment_payload(
            scholar["id"], mentor["id"], award["id"],
            **dict(_ASSOCIATE_TERM, term_start_date="2027-09-30",
                   term_end_date="2026-10-01"),
        ),
        officer,
    )
    validate_error(inverted_term, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api_client.list_appointments(officer, {"postdoc_id": scholar["id"]})
    )
    assert meta["total_count"] == 0, (
        f"Neither refused draft may persist, got {meta['total_count']}"
    )


def test_an_unknown_mentor_is_reported_as_mentor_not_found():
    """The dangling body foreign key names the missing parent specifically.

    PRD 2.7: "Body-borne foreign keys are validated after all path identifiers, in
    the order in which the fields are declared for the entity being written. The
    404 codes are entity-specific: `ERR_POSTDOC_NOT_FOUND`,
    `ERR_MENTOR_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`,
    `ERR_LABORATORY_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND` (which also covers an
    unresolvable `predecessor_appointment_id`)"

    Design: Corner/entities/appointment_create_with_an_unknown_mentor_reports_mentor_not_found
    """
    officer = make_officer_headers("officer-pa-27")
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R03-2700",
        annual_budget_usd=300000.00, **_SHARED_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Vera Lindgren", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-18",
    )

    response = api_client.create_appointment(
        create_appointment_payload(
            scholar["id"], NON_EXISTENT_UUID, award["id"], **_ASSOCIATE_TERM
        ),
        officer,
    )
    validate_error(response, ApiErrorId.ERR_MENTOR_NOT_FOUND.value, 404)

    _, meta = validate_paginated(
        api_client.list_appointments(officer, {"postdoc_id": scholar["id"]})
    )
    assert meta["total_count"] == 0, (
        f"A refused draft must persist nothing, got {meta['total_count']}"
    )


def test_the_foreign_key_filters_partition_the_appointment_collection():
    """Every foreign key on the appointment is reverse-navigable, the
    self-referential one included.

    PRD 3.1: "Because the topology is flat, the registries are also the discovery
    surface. Appointments may be listed filtered by `postdoc_id`, `mentor_id`,
    `funding_source_id`, `predecessor_appointment_id`, `appointment_status` and
    `compliance_status` in any combination"

    Design: Corner/entities/flat_topology_fk_filters_partition_the_appointment_collection
    """
    officer = make_officer_headers("officer-pa-28")
    mentor_alpha = register_faculty_mentor(
        officer, full_name="Mentor Alpha", department="Physics",
        mentor_training_valid_through="2030-06-30",
    )
    mentor_beta = register_faculty_mentor(
        officer, full_name="Mentor Beta", department="Physics",
        mentor_training_valid_through="2030-06-30",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="DOE-2800", funding_type="FEDERAL_GRANT",
        salary_floor_policy="NIH_SCALE", award_start_date="2026-09-01",
        award_end_date="2028-12-31", annual_budget_usd=900000.00,
    )
    scholar_a = register_postdoc(
        officer, full_name="Scholar A28", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-03-01",
    )
    scholar_b = register_postdoc(
        officer, full_name="Scholar B28", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-03-02",
    )

    first_term = draft_appointment(
        scholar_a["id"], mentor_alpha["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    successor = draft_appointment(
        scholar_a["id"], mentor_alpha["id"], award["id"], officer,
        **dict(_ASSOCIATE_TERM, term_start_date="2027-10-01",
               term_end_date="2028-09-30", annual_salary_usd=64000.00,
               predecessor_appointment_id=first_term["id"]),
    )
    beta_term = draft_appointment(
        scholar_b["id"], mentor_beta["id"], award["id"], officer, **_ASSOCIATE_TERM
    )

    by_mentor, by_mentor_meta = validate_paginated(
        api_client.list_appointments(officer, {"mentor_id": mentor_beta["id"]})
    )
    assert by_mentor_meta["total_count"] == 1, (
        f"Mentor Beta supervises exactly one appointment, "
        f"got {by_mentor_meta['total_count']}"
    )
    assert by_mentor[0]["id"] == beta_term["id"]

    by_predecessor, by_predecessor_meta = validate_paginated(
        api_client.list_appointments(
            officer, {"predecessor_appointment_id": first_term["id"]}
        )
    )
    assert by_predecessor_meta["total_count"] == 1, (
        f"Exactly one successor names the first term, "
        f"got {by_predecessor_meta['total_count']}"
    )
    assert by_predecessor[0]["id"] == successor["id"]

    _, by_award_meta = validate_paginated(
        api_client.list_appointments(officer, {"funding_source_id": award["id"]})
    )
    assert by_award_meta["total_count"] == 3, (
        f"All three appointments are charged to the one award, "
        f"got {by_award_meta['total_count']}"
    )

    assert successor["months_in_rank_at_start"] == 0, (
        "A predecessor still in DRAFT contributes zero, got "
        f"{successor['months_in_rank_at_start']}"
    )
    assert successor["predecessor_appointment_id"] == first_term["id"]
    assert read_appointment(first_term["id"], officer)[
        "predecessor_appointment_id"] is None, (
        "The first term of a chain names no predecessor"
    )
