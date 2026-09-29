"""Stored field sets, server-minted values and declared defaults.

Every write in this domain is a compliance artefact, so what a create call puts
on the row — the echoed inputs, the server-minted identity and audit columns, the
values computed from a fixed table, and the defaults that materialise when an
optional input is omitted — is part of the contract rather than an
implementation detail.
"""

from test_helpers import (
    assert_cents,
    assert_credit_hours,
    assert_credit_totals,
    assert_fields_absent,
    assert_fields_present,
    assert_instant_format,
    assert_rate,
    assert_version,
    errors,
    f,
    is_valid_uuid,
    k,
    users,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)

PROGRAM_FIELDS = (
    "id",
    "cip_code",
    "title",
    "cluster",
    "labor_market_data_asof",
    "approval_status",
    "clna_phase",
    "approval_round",
    "authored_by_user_id",
    "alignment_index",
    "alignment_index_variant",
    "secondary_credit_total",
    "postsecondary_credit_total",
    "articulated_credit_total",
    "federal_reporting_eligible",
    "open_finding_codes",
    "narrative_url",
    "clna_certified_on",
    "clna_expires_on",
    "clna_certified_by_user_id",
    "created_at",
    "updated_at",
    "version",
)

GRANT_LEDGER_FIELDS = (
    "allocation_cents",
    "direct_obligated_cents",
    "indirect_pool_cents",
    "indirect_rate",
    "obligated_cents",
    "remaining_cents",
    "admin_cap_cents",
    "admin_obligated_cents",
)


class TestProgramOfStudyCreationRow:
    """What a 201 on the program-of-study collection puts on the wire."""

    def test_the_four_authored_values_are_echoed_onto_the_created_row(
        self, api, director_headers
    ):
        """PRD §3.1: "The creation payload carries four values: a `cip_code`, which is the federal classification code and must be exactly two digits, a period, and four further digits; a `title` of between 1 and 120 characters, which is the local program name printed on the state approval packet; a `cluster` naming the career area, which must be one of `HEALTH_SCIENCE`, `ADVANCED_MANUFACTURING`, `INFORMATION_TECHNOLOGY`, `CONSTRUCTION` or `AGRICULTURE`; and a `labor_market_data_asof` calendar date recording which labor-market dataset the needs assessment will lean on."

        PRD §4: "an endpoint that brings a new resource into existence answers **201 Created**"

        Design: Corner/entities/program_of_study_creation_returns_the_declared_field_set
        """
        response = api.create_program(
            f.program_payload(
                "51.0801",
                title="Medical Assisting",
                cluster=k.CLUSTER_HEALTH_SCIENCE,
                labor_market_data_asof="2026-03-01",
            ),
            director_headers,
        )
        program = validate_unpaginated(response, 201)

        assert_fields_present(program, PROGRAM_FIELDS)
        assert program["cip_code"] == "51.0801"
        assert program["title"] == "Medical Assisting"
        assert program["cluster"] == k.CLUSTER_HEALTH_SCIENCE
        assert program["labor_market_data_asof"] == "2026-03-01"
        assert is_valid_uuid(program["id"]), (
            f"id must be a server-minted UUID, got {program['id']!r}"
        )

    def test_the_system_and_computed_columns_open_at_their_declared_values(
        self, api, director_headers
    ):
        """PRD §3.1: "On creation the new program lands in `approval_status` `DRAFT` and `clna_phase` `NOT_STARTED`, its `version` is 1, its `authored_by_user_id` is set to the acting `X-User-ID`, its `alignment_index` and `alignment_index_variant` are both null, its `narrative_url` is null, its `open_finding_codes` list is empty, its `federal_reporting_eligible` flag is false, its `approval_round` is 0, its `clna_certified_by_user_id`, `clna_certified_on` and `clna_expires_on` are all null, and `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total` are all 0."

        Design: Corner/entities/program_of_study_creation_returns_the_declared_field_set
        """
        response = api.create_program(
            f.program_payload("51.0801", title="Medical Assisting"), director_headers
        )
        program = validate_unpaginated(response, 201)

        assert program["approval_status"] == k.APPROVAL_DRAFT
        assert program["clna_phase"] == k.CLNA_NOT_STARTED
        assert_version(program, 1)
        assert program["authored_by_user_id"] == users.DIRECTOR.user_id
        assert program["alignment_index"] is None
        assert program["alignment_index_variant"] is None
        assert program["narrative_url"] is None
        assert program["open_finding_codes"] == []
        assert program["federal_reporting_eligible"] is False
        assert program["approval_round"] == 0
        assert program["clna_certified_by_user_id"] is None
        assert program["clna_certified_on"] is None
        assert program["clna_expires_on"] is None
        assert_credit_totals(program, 0, 0, 0)


class TestSequenceCourseDetailRead:
    """The detail read of a course, including the depth its chain determines."""

    def test_the_course_that_opens_the_sequence_reads_depth_zero(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The server computes `depth_from_root`, the number of prerequisite hops from the course back to a course whose `prerequisite_course_id` is null, by walking the chain; a course that opens the sequence has `depth_from_root` 0."

        Design: Corner/entities/get_sequence_course_returns_the_stored_row_including_depth_from_root
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        root = build.add_course(
            program["id"],
            f.secondary_course(
                "MED-1", 1, 4.0, title="Medical Assisting I", status=k.COURSE_ACTIVE
            ),
        )
        build.add_course(
            program["id"],
            f.postsecondary_course(
                "MED-9",
                2,
                3.0,
                2.5,
                True,
                title="Dual-Credit Phlebotomy",
                status=k.COURSE_ACTIVE,
                prerequisite_course_id=root["id"],
            ),
        )

        course = validate_unpaginated(api.get_course(root["id"], director_headers))

        assert course["depth_from_root"] == 0, (
            "a course whose prerequisite_course_id is null sits at depth 0"
        )
        assert course["prerequisite_course_id"] is None

    def test_the_course_naming_the_root_reads_depth_one_with_its_stored_articulation(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The server computes `depth_from_root`, the number of prerequisite hops from the course back to a course whose `prerequisite_course_id` is null, by walking the chain; a course that opens the sequence has `depth_from_root` 0."

        PRD §3.1: "Each `SequenceCourse` carries a `code` of 1 to 24 characters that must be unique among the courses of the same program (a repeat is `ERR_COURSE_CODE_DUPLICATE`), a `title`, a `segment` of either `SECONDARY` or `POSTSECONDARY`, a `position` from 1 through 8 fixing its ordinal place in the sequence, and `credit_hours` greater than zero at two decimal places."

        Design: Corner/entities/get_sequence_course_returns_the_stored_row_including_depth_from_root
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        root = build.add_course(
            program["id"],
            f.secondary_course(
                "MED-1", 1, 4.0, title="Medical Assisting I", status=k.COURSE_ACTIVE
            ),
        )
        leaf = build.add_course(
            program["id"],
            f.postsecondary_course(
                "MED-9",
                2,
                3.0,
                2.5,
                True,
                title="Dual-Credit Phlebotomy",
                status=k.COURSE_ACTIVE,
                prerequisite_course_id=root["id"],
            ),
        )

        course = validate_unpaginated(api.get_course(leaf["id"], director_headers))

        assert course["depth_from_root"] == 1, (
            "one prerequisite hop separates this course from the root"
        )
        assert course["prerequisite_course_id"] == root["id"]
        assert course["segment"] == k.SEGMENT_POSTSECONDARY
        assert course["position"] == 2
        assert_credit_hours(course["credit_hours"], 3.00, "credit_hours")
        assert_credit_hours(
            course["articulated_credit_hours"], 2.50, "articulated_credit_hours"
        )
        assert course["articulation_verified"] is True
        assert course["status"] == k.COURSE_ACTIVE


class TestDeclaredDefaultsOnOmittedOptionalInputs:
    """Optional inputs left out of the payload materialise as declared values."""

    def test_a_course_written_without_its_optional_inputs_opens_in_draft(
        self, api, build, director_headers
    ):
        """PRD §3.1: "Optionally the payload sets `articulated_credit_hours` — the portion of the course's credit that articulates to the postsecondary partner, which defaults to 0 and may be neither negative nor greater than `credit_hours` — an `articulation_verified` flag that defaults to false and turns true only once the postsecondary partner has countersigned the articulation agreement, a `prerequisite_course_id` naming an earlier course, and a `status` that defaults to `DRAFT` and may be set to `ACTIVE` or `RETIRED`."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        program = build.create_program("51.0801", title="Medical Assisting")

        response = api.create_course(
            program["id"],
            f.course_payload(
                "MED-1", "Medical Assisting I", k.SEGMENT_SECONDARY, 1, 4.0
            ),
            director_headers,
        )
        course = validate_unpaginated(response, 201)

        assert course["status"] == k.COURSE_DRAFT
        assert_credit_hours(
            course["articulated_credit_hours"], 0.00, "articulated_credit_hours"
        )
        assert course["articulation_verified"] is False

    def test_a_credential_written_without_exam_required_demands_an_exam(
        self, api, build, director_headers
    ):
        """PRD §3.1: "A `Credential` carries a `code` of 1 to 32 characters unique within the program (a repeat is `ERR_CREDENTIAL_CODE_DUPLICATE`), a `title`, a `tier` of `STATE_RECOGNIZED`, `NATIONAL` or `LOCAL`, and an `exam_required` flag that defaults to true. The server sets `counts_toward_indicator` to true when the `tier` is `STATE_RECOGNIZED` or `NATIONAL`, and to false when the `tier` is `LOCAL` — locally recognised credentials are legitimate to award but never enter a federal performance numerator. A credential's `verified_attainment_count` starts at 0 and thereafter always equals the number of attainment records against it whose `verification_status` is `VERIFIED`."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        program = build.create_program("51.0801", title="Medical Assisting")

        response = api.create_credential(
            program["id"],
            f.credential_payload(
                "CCMA",
                title="Certified Clinical Medical Assistant",
                tier=k.TIER_NATIONAL,
            ),
            director_headers,
        )
        credential = validate_unpaginated(response, 201)

        assert credential["exam_required"] is True
        assert credential["counts_toward_indicator"] is True
        assert credential["verified_attainment_count"] == 0

    def test_a_member_seated_without_is_chair_leaves_the_chair_pointer_null(
        self, api, build, director_headers
    ):
        """PRD §3.3: "A `CommitteeMember` payload carries a `full_name`, a `sector` of `EMPLOYER`, `POSTSECONDARY`, `LABOR`, `PARENT` or `STUDENT`, a `seat_code` written as three uppercase letters followed by a hyphen and one or two digits, a `term_start_on` date, a `term_end_on` date strictly after it, and an optional `is_chair` flag that defaults to false. A member's `status` begins as `ACTIVE` and becomes `EXPIRED` once the logical clock's date reaches `term_end_on`; the term is inclusive of `term_start_on` and exclusive of `term_end_on`."

        PRD §3.3: "`chair_member_id` becomes the `id` of the single `ACTIVE` member whose `is_chair` is true (staying null while no such member exists)."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        committee = build.charter_committee(program["id"])

        response = api.seat_member(
            committee["id"],
            f.member_payload(
                "Rosa Vega",
                k.SECTOR_EMPLOYER,
                "EMP-1",
                term_start_on="2026-01-01",
                term_end_on="2027-12-31",
            ),
            director_headers,
        )
        member = validate_unpaginated(response, 201)

        assert member["is_chair"] is False
        assert member["status"] == k.MEMBER_ACTIVE

        seated = validate_unpaginated(api.get_committee(committee["id"], director_headers))
        assert seated["chair_member_id"] is None

    def test_a_student_enrolled_without_special_populations_opens_as_a_participant(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "A `SchoolRegistrar` enrolls a student into a program with a `state_student_id` of exactly nine digits — unique among that program's students, a repeat being `ERR_STUDENT_ID_DUPLICATE` — a `cohort_year` between 2020 and 2035 naming the accountability cohort the student is reported under, and an optional `special_population_codes` list whose elements are drawn from `ECON_DISADV`, `IEP`, `EL`, `SINGLE_PARENT` and `NONTRADITIONAL` with no duplicates, defaulting to an empty list. The new student begins with `cte_credits_earned` 0, `verified_qualifying_attainment_count` 0, `concentrator_status` `PARTICIPANT`, and `exited_on` and `exit_reason` both null."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        program = build.create_program("51.0801", title="Medical Assisting")

        response = api.enroll_student(
            program["id"], f.student_payload("100000001", 2026), registrar_headers
        )
        student = validate_unpaginated(response, 201)

        assert student["special_population_codes"] == []
        assert student["concentrator_status"] == k.CONCENTRATOR_PARTICIPANT
        assert_credit_hours(student["cte_credits_earned"], 0.00, "cte_credits_earned")
        assert student["verified_qualifying_attainment_count"] == 0
        assert student["exited_on"] is None
        assert student["exit_reason"] is None


class TestExpenditureComputedAmounts:
    """The two amounts a purchase request computes rather than accepts."""

    def test_gross_cents_and_the_category_share_are_computed_on_the_request(
        self, api, build, director_headers
    ):
        """PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`."

        PRD §3.7: "`PROFESSIONAL_DEVELOPMENT` is reimbursed in full at a share of 1.0000."

        Design: Corner/entities/expenditure_gross_and_federal_share_are_computed_from_the_category_table
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)

        response = api.request_expenditure(
            grant.grant_id,
            f.expenditure_payload(
                program["id"],
                k.CATEGORY_PROFESSIONAL_DEVELOPMENT,
                12345,
                7,
                grant.version,
                description="Instructor externship stipends",
            ),
            director_headers,
        )
        expenditure = validate_unpaginated(response, 201)

        assert_cents(expenditure["gross_cents"], 86415, "gross_cents")
        assert_rate(expenditure["federal_share_pct"], 1.0, "federal_share_pct")
        assert expenditure["approved_cents"] is None
        assert expenditure["status"] == k.EXP_REQUESTED
        assert expenditure["requested_by_user_id"] == users.DIRECTOR.user_id
        assert expenditure["certified_by_user_id"] is None
        assert expenditure["finding_code"] is None
        assert expenditure["grant_award_id"] == grant.grant_id

    def test_a_merely_requested_line_stays_out_of_the_obligation_ledger(
        self, api, build, director_headers, fiscal_headers
    ):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation."

        Design: Corner/entities/expenditure_gross_and_federal_share_are_computed_from_the_category_table
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)
        build.expenditure(
            grant.grant_id,
            program["id"],
            k.CATEGORY_PROFESSIONAL_DEVELOPMENT,
            12345,
            quantity=7,
            expected_version=grant.version,
        )

        award = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))

        assert_cents(award["direct_obligated_cents"], 0, "direct_obligated_cents")
        assert_cents(award["remaining_cents"], 5000000, "remaining_cents")


class TestGrantAwardCreationRow:
    """The ledger a recorded federal award is born holding."""

    def test_the_whole_ledger_is_initialised_in_one_step(self, api, fiscal_headers):
        """PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        PRD §3.7: "a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812"

        Design: Corner/entities/grant_award_system_and_computed_fields_are_server_minted_at_creation
        """
        response = api.create_grant(
            f.grant_payload(2027, 5000000, "2026-07-01", "2027-06-30"), fiscal_headers
        )
        award = validate_unpaginated(response, 201)

        assert_fields_present(award, GRANT_LEDGER_FIELDS)
        assert award["status"] == k.GRANT_OPEN
        assert_cents(award["direct_obligated_cents"], 0, "direct_obligated_cents")
        assert_cents(award["indirect_pool_cents"], 0, "indirect_pool_cents")
        assert_cents(award["obligated_cents"], 0, "obligated_cents")
        assert_cents(award["admin_obligated_cents"], 0, "admin_obligated_cents")
        assert_cents(award["remaining_cents"], 5000000, "remaining_cents")
        assert_cents(award["admin_cap_cents"], 250000, "admin_cap_cents")
        assert_rate(award["indirect_rate"], 0.0812, "indirect_rate")

    def test_identity_and_audit_columns_are_server_minted_at_creation(
        self, api, fiscal_headers
    ):
        """PRD §2.4: "Every resource this API stores is addressed by an `id`, which is a server-minted UUID carrying no type prefix."

        PRD §2.4: "`created_at` is the ISO 8601 UTC instant at which the record was first stored, rendered with three fractional digits. `updated_at` is the same format and is refreshed on every mutation of the record. `version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that record"

        Design: Corner/entities/grant_award_system_and_computed_fields_are_server_minted_at_creation
        """
        response = api.create_grant(
            f.grant_payload(2027, 5000000, "2026-07-01", "2027-06-30"), fiscal_headers
        )
        award = validate_unpaginated(response, 201)

        assert is_valid_uuid(award["id"]), (
            f"id must be a server-minted UUID, got {award['id']!r}"
        )
        assert_version(award, 1)
        assert_instant_format(award["created_at"], "created_at")
        assert_instant_format(award["updated_at"], "updated_at")


#: A career-area name deliberately outside the five the specification recognises.
CLUSTER_NOT_IN_CATALOGUE = "AVIATION"

#: A seat code carrying a two-letter prefix instead of the required three.
SEAT_CODE_SHORT_PREFIX = "EM-1"


class TestRequestShapeRulesOnPatternsEnumsAndRanges:
    """Every pattern, enum and numeric bound answers at request-shape priority."""

    def test_a_cip_code_missing_the_two_dot_four_pattern_is_rejected(
        self, api, director_headers, reviewer_headers
    ):
        """PRD §3.1: "The creation payload carries four values: a `cip_code`, which is the federal classification code and must be exactly two digits, a period, and four further digits"

        PRD §2.7: "Request-body and query-string shape: required fields present, enum members valid, string patterns matched, numeric bounds respected"

        Design: Corner/entities/pattern_enum_and_range_constraints_are_all_enforced_as_invalid_request
        """
        response = api.create_program(
            f.program_payload("5.0801", title="Bad CIP"), director_headers
        )
        validate_error(response, errors.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(api.list_programs(reviewer_headers))
        assert meta["total_count"] == 0, "a rejected create must persist nothing"

    def test_a_cluster_outside_the_declared_enum_is_rejected(
        self, api, director_headers, reviewer_headers
    ):
        """PRD §3.1: "a `cluster` naming the career area, which must be one of `HEALTH_SCIENCE`, `ADVANCED_MANUFACTURING`, `INFORMATION_TECHNOLOGY`, `CONSTRUCTION` or `AGRICULTURE`"

        PRD §2.7: "Request-body and query-string shape: required fields present, enum members valid, string patterns matched, numeric bounds respected"

        Design: Corner/entities/pattern_enum_and_range_constraints_are_all_enforced_as_invalid_request
        """
        response = api.create_program(
            f.program_payload(
                "49.0202", title="Bad Cluster", cluster=CLUSTER_NOT_IN_CATALOGUE
            ),
            director_headers,
        )
        validate_error(response, errors.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(api.list_programs(reviewer_headers))
        assert meta["total_count"] == 0, "a rejected create must persist nothing"

    def test_a_seat_code_without_its_three_letter_prefix_is_rejected(
        self, api, build, director_headers
    ):
        """PRD §3.3: "A `CommitteeMember` payload carries a `full_name`, a `sector` of `EMPLOYER`, `POSTSECONDARY`, `LABOR`, `PARENT` or `STUDENT`, a `seat_code` written as three uppercase letters followed by a hyphen and one or two digits, a `term_start_on` date, a `term_end_on` date strictly after it, and an optional `is_chair` flag that defaults to false."

        Design: Corner/entities/pattern_enum_and_range_constraints_are_all_enforced_as_invalid_request
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        committee = build.charter_committee(program["id"])

        response = api.seat_member(
            committee["id"],
            f.member_payload("Bad Seat", k.SECTOR_EMPLOYER, SEAT_CODE_SHORT_PREFIX),
            director_headers,
        )
        validate_error(response, errors.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_committee_members(committee["id"], director_headers)
        )
        assert meta["total_count"] == 0, "a rejected seating must persist nothing"

    def test_a_position_above_the_eight_slot_sequence_is_rejected(
        self, api, build, director_headers
    ):
        """PRD §2.7: "Request-body and query-string shape: required fields present, enum members valid, string patterns matched, numeric bounds respected (`unit_cost_cents` greater than zero, `quantity` at least 1, `credit_hours` greater than zero, `position` from 1 through 8, `articulated_credit_hours` no greater than `credit_hours`, `vote_yes` and `vote_no` at least zero, `cohort_year` and `reporting_year` from 2020 through 2035, `baseline_pct` and `offered_level_pct` from 0.00 through 100.00, `limit` from 1 through 100, `offset` at least zero)"

        Design: Corner/entities/pattern_enum_and_range_constraints_are_all_enforced_as_invalid_request
        """
        program = build.create_program("51.0801", title="Medical Assisting")

        response = api.create_course(
            program["id"],
            f.course_payload("MED-9", "Bad Position", k.SEGMENT_SECONDARY, 9, 1.0),
            director_headers,
        )
        validate_error(response, errors.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_program_courses(program["id"], director_headers)
        )
        assert meta["total_count"] == 0, "a rejected course must persist nothing"

    def test_a_cohort_year_below_the_twenty_twenty_bound_is_rejected(
        self, api, build, registrar_headers
    ):
        """PRD §2.7: "Request-body and query-string shape: required fields present, enum members valid, string patterns matched, numeric bounds respected (`unit_cost_cents` greater than zero, `quantity` at least 1, `credit_hours` greater than zero, `position` from 1 through 8, `articulated_credit_hours` no greater than `credit_hours`, `vote_yes` and `vote_no` at least zero, `cohort_year` and `reporting_year` from 2020 through 2035, `baseline_pct` and `offered_level_pct` from 0.00 through 100.00, `limit` from 1 through 100, `offset` at least zero)"

        Design: Corner/entities/pattern_enum_and_range_constraints_are_all_enforced_as_invalid_request
        """
        program = build.create_program("51.0801", title="Medical Assisting")

        response = api.enroll_student(
            program["id"], f.student_payload("100000002", 2019), registrar_headers
        )
        validate_error(response, errors.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_program_students(program["id"], registrar_headers)
        )
        assert meta["total_count"] == 0, "a rejected enrollment must persist nothing"

    def test_articulated_credit_beyond_the_courses_own_credit_hours_is_rejected(
        self, api, build, director_headers
    ):
        """PRD §3.1: "Optionally the payload sets `articulated_credit_hours` — the portion of the course's credit that articulates to the postsecondary partner, which defaults to 0 and may be neither negative nor greater than `credit_hours`"

        PRD §2.7: "Request-body and query-string shape: required fields present, enum members valid, string patterns matched, numeric bounds respected (`unit_cost_cents` greater than zero, `quantity` at least 1, `credit_hours` greater than zero, `position` from 1 through 8, `articulated_credit_hours` no greater than `credit_hours`, `vote_yes` and `vote_no` at least zero, `cohort_year` and `reporting_year` from 2020 through 2035, `baseline_pct` and `offered_level_pct` from 0.00 through 100.00, `limit` from 1 through 100, `offset` at least zero)"

        Design: Corner/entities/pattern_enum_and_range_constraints_are_all_enforced_as_invalid_request
        """
        program = build.create_program("51.0801", title="Medical Assisting")

        response = api.create_course(
            program["id"],
            f.course_payload(
                "MED-8",
                "Over-articulated",
                k.SEGMENT_POSTSECONDARY,
                2,
                3.0,
                articulated_credit_hours=3.5,
            ),
            director_headers,
        )
        validate_error(response, errors.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_program_courses(program["id"], director_headers)
        )
        assert meta["total_count"] == 0, "a rejected course must persist nothing"

    def test_a_quantity_below_one_is_rejected_and_leaves_the_award_untouched(
        self, api, build, director_headers, fiscal_headers
    ):
        """PRD §3.7: "A request names the `pos_id` of the program the purchase is charged to, a `category`, a `description` for the grant file, a `unit_cost_cents` greater than zero, a `quantity` of at least 1, a `service_period_start` and a `service_period_end` on or after it, optionally an `asset_tag` of 3 to 24 characters drawn from uppercase letters, digits and hyphens, and the `expected_grant_award_version` of §2.9."

        Design: Corner/entities/pattern_enum_and_range_constraints_are_all_enforced_as_invalid_request
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)

        response = api.request_expenditure(
            grant.grant_id,
            f.expenditure_payload(
                program["id"],
                k.CATEGORY_CONSUMABLE,
                100000,
                0,
                grant.version,
                description="Zero quantity",
            ),
            director_headers,
        )
        validate_error(response, errors.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_grant_expenditures(grant.grant_id, fiscal_headers)
        )
        assert meta["total_count"] == 0, "a rejected request must persist nothing"

        award = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_version(award, grant.version)


class TestCredentialAttainmentImmutability:
    """The one record in the system that carries neither version nor updated_at."""

    def _filed_attainment(self, api, build, registrar_headers):
        program = build.create_program("51.0801", title="Medical Assisting")
        credential = build.add_credential(
            program["id"],
            "CCMA",
            tier=k.TIER_NATIONAL,
            title="Certified Clinical Medical Assistant",
            exam_required=False,
        )
        student = build.enroll(program["id"], "100000001", cohort_year=2026)
        response = api.create_attainment(
            student["id"],
            f.attainment_payload(
                credential["id"], "2026-07-20", k.VERIFICATION_VERIFIED
            ),
            registrar_headers,
        )
        return credential, student, validate_unpaginated(response, 201)

    def test_the_stored_attainment_exposes_neither_version_nor_updated_at(
        self, api, build, registrar_headers
    ):
        """PRD §2.4: "`CredentialAttainment` is the single exception. An attainment record is immutable once filed: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from its representation entirely."

        Design: Corner/entities/credential_attainment_is_immutable_and_carries_no_version
        """
        _, _, filed = self._filed_attainment(api, build, registrar_headers)

        row = validate_unpaginated(api.get_attainment(filed["id"], registrar_headers))

        assert_fields_present(row, ("id", "created_at"))
        assert_fields_absent(row, ("version", "updated_at"))

    def test_a_verified_attainment_on_a_counting_credential_counts_for_the_indicator(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Whether an attainment counts for federal purposes is a conjunction of two facts, and the server records the answer on the row as `counted_for_indicator`: it is true only when the attainment's `verification_status` is `VERIFIED` **and** the referenced credential's `counts_toward_indicator` is true."

        PRD §3.6: "An attainment record is immutable once filed, and it carries `student_id` taken from the addressed student together with the `credential_id` from the payload."

        Design: Corner/entities/credential_attainment_is_immutable_and_carries_no_version
        """
        credential, student, filed = self._filed_attainment(
            api, build, registrar_headers
        )

        row = validate_unpaginated(api.get_attainment(filed["id"], registrar_headers))

        assert row["verification_status"] == k.VERIFICATION_VERIFIED
        assert row["counted_for_indicator"] is True
        assert row["attained_on"] == "2026-07-20"
        assert row["student_id"] == student["id"]
        assert row["credential_id"] == credential["id"]

    def test_refiling_the_same_pairing_is_refused_rather_than_overwriting(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "no attainment may already exist for that same student-and-credential pairing, a repeat being `ERR_DUPLICATE_ATTAINMENT`"

        PRD §3.6: "An attainment record is immutable once filed"

        Design: Corner/entities/credential_attainment_is_immutable_and_carries_no_version
        """
        credential, student, filed = self._filed_attainment(
            api, build, registrar_headers
        )

        response = api.create_attainment(
            student["id"],
            f.attainment_payload(
                credential["id"], "2026-08-01", k.VERIFICATION_SELF_REPORTED
            ),
            registrar_headers,
        )
        validate_error(response, errors.ERR_DUPLICATE_ATTAINMENT)

        rows, meta = validate_paginated(
            api.list_attainments(registrar_headers, f.page(student_id=student["id"]))
        )
        assert meta["total_count"] == 1, "the rejected repeat must not have been stored"
        assert rows[0]["id"] == filed["id"]
        assert rows[0]["verification_status"] == k.VERIFICATION_VERIFIED
        assert rows[0]["attained_on"] == "2026-07-20"
