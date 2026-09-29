"""Collection reads, detail misses and the foreign keys that bind the records.

The records of this service are addressed three ways: through a paginated
collection read, through a detail read that must answer with the collection's own
not-found identifier when the id does not resolve, and through the foreign keys
that let a parent be walked back to from its children. Each of those is a
contract in its own right.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_error_envelope,
    assert_cents,
    assert_credit_hours,
    assert_version,
    errors,
    f,
    ids_of,
    k,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)


def _three_programs(build):
    """One program per career area, created oldest first."""
    first = build.create_program(
        "51.0801", title="Medical Assisting", cluster=k.CLUSTER_HEALTH_SCIENCE
    )
    second = build.create_program(
        "11.0201",
        title="Computer Programming",
        cluster=k.CLUSTER_INFORMATION_TECHNOLOGY,
    )
    third = build.create_program(
        "46.0302", title="Electrical Trades", cluster=k.CLUSTER_CONSTRUCTION
    )
    return first, second, third


class TestProgramCollectionPagination:
    """The four pagination figures the program-of-study collection publishes."""

    def test_the_first_page_of_two_reports_the_full_match_count_and_more_to_come(
        self, api, build, reviewer_headers
    ):
        """PRD §2.3: "List responses populate all four pagination fields in `meta`: `limit` and `offset` echo the values in force for the page, `total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        PRD §2.3: "Three endpoints override that default: the program-of-study collection returns the most recently created programs first, the grant-award collection returns the highest `fiscal_year` first, and a committee's meeting list returns the latest `scheduled_for` first."

        Design: Corner/entities/list_programs_of_study_paginates_with_total_count_and_has_more
        """
        first, second, third = _three_programs(build)

        rows, meta = validate_paginated(
            api.list_programs(reviewer_headers, f.page(limit=2, offset=0))
        )

        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert ids_of(rows) == [third["id"], second["id"]], (
            "the newest two programs form the first page"
        )

    def test_the_window_past_the_last_full_page_reports_no_more_records(
        self, api, build, reviewer_headers
    ):
        """PRD §2.3: "List responses populate all four pagination fields in `meta`: `limit` and `offset` echo the values in force for the page, `total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        PRD §2.3: "`offset` controls how many records are skipped before the page begins: its default is 0 and its minimum accepted value is 0."

        Design: Corner/entities/list_programs_of_study_paginates_with_total_count_and_has_more
        """
        first, _, _ = _three_programs(build)

        rows, meta = validate_paginated(
            api.list_programs(reviewer_headers, f.page(limit=2, offset=2))
        )

        assert meta["limit"] == 2
        assert meta["offset"] == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert ids_of(rows) == [first["id"]], (
            "the oldest program is the only one left beyond the first page"
        )

    def test_a_cluster_filter_narrows_the_total_count_to_the_matching_subset(
        self, api, build, reviewer_headers
    ):
        """PRD §2.3: "`total_count` is the number of records matching the filter before the page window is applied"

        PRD §4: "programs may be filtered by `approval_status`, `cluster` or `clna_phase`"

        Design: Corner/entities/list_programs_of_study_paginates_with_total_count_and_has_more
        """
        _, _, third = _three_programs(build)

        rows, meta = validate_paginated(
            api.list_programs(
                reviewer_headers, f.page(cluster=k.CLUSTER_CONSTRUCTION)
            )
        )

        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert ids_of(rows) == [third["id"]]

    def test_a_filter_matching_nothing_reports_a_zero_total_and_an_empty_page(
        self, api, build, reviewer_headers
    ):
        """PRD §2.3: "`total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        PRD §4: "programs may be filtered by `approval_status`, `cluster` or `clna_phase`"

        Design: Corner/entities/list_programs_of_study_paginates_with_total_count_and_has_more
        """
        _three_programs(build)

        rows, meta = validate_paginated(
            api.list_programs(
                reviewer_headers, f.page(approval_status=k.APPROVAL_STATE_APPROVED)
            )
        )

        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert rows == []


class TestStudentDetailMiss:
    """A detail read of an id that never existed answers on the student's own code."""

    def test_an_unpersisted_student_id_answers_with_the_student_not_found_code(
        self, api, build, registrar_headers
    ):
        """PRD §2.6: "Each collection prefix has its own not-found code: `/cte/programs-of-study/{id}` yields `ERR_PROGRAM_NOT_FOUND`, `/cte/sequence-courses/{id}` yields `ERR_COURSE_NOT_FOUND`, `/cte/students/{id}` yields `ERR_STUDENT_NOT_FOUND`, `/cte/credential-attainments/{id}` yields `ERR_ATTAINMENT_NOT_FOUND`, `/cte/advisory-committees/{id}` yields `ERR_COMMITTEE_NOT_FOUND`, `/cte/committee-members/{id}` yields `ERR_MEMBER_NOT_FOUND`, `/cte/committee-meetings/{id}` yields `ERR_MEETING_NOT_FOUND`, `/cte/grant-awards/{id}` yields `ERR_GRANT_NOT_FOUND`, `/cte/expenditures/{id}` yields `ERR_EXPENDITURE_NOT_FOUND`, `/cte/performance-indicators/{id}` yields `ERR_INDICATOR_NOT_FOUND`, `/cte/improvement-plans/{id}` yields `ERR_PLAN_NOT_FOUND`, and `/cte/educators/{id}` yields `ERR_EDUCATOR_NOT_FOUND`. Every one of these is HTTP 404."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error." and "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/get_student_with_an_unknown_id_returns_student_not_found
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        build.enroll(program["id"], "100000001", cohort_year=2026)

        response = api.get_student(NON_EXISTENT_UUID, registrar_headers)

        validate_error(response, errors.ERR_STUDENT_NOT_FOUND)
        assert_error_envelope(response)

    def test_the_enrolled_student_is_left_untouched_by_the_failed_read(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "The new student begins with `cte_credits_earned` 0, `verified_qualifying_attainment_count` 0, `concentrator_status` `PARTICIPANT`, and `exited_on` and `exit_reason` both null."

        PRD §2.6: "`/cte/students/{id}` yields `ERR_STUDENT_NOT_FOUND`"

        Design: Corner/entities/get_student_with_an_unknown_id_returns_student_not_found
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        student = build.enroll(program["id"], "100000001", cohort_year=2026)

        validate_error(
            api.get_student(NON_EXISTENT_UUID, registrar_headers),
            errors.ERR_STUDENT_NOT_FOUND,
        )

        row = validate_unpaginated(api.get_student(student["id"], registrar_headers))
        assert row["concentrator_status"] == k.CONCENTRATOR_PARTICIPANT
        assert_credit_hours(row["cte_credits_earned"], 0.00, "cte_credits_earned")
        assert row["verified_qualifying_attainment_count"] == 0


class TestExpenditureRequiredFields:
    """A field the request declares without a default is required, not optional."""

    def _payload_without_service_period_end(self, program_id, grant_version):
        payload = f.expenditure_payload(
            program_id,
            k.CATEGORY_CONSUMABLE,
            100000,
            1,
            grant_version,
            description="Missing end date",
        )
        payload.pop("service_period_end")
        return payload

    def test_omitting_service_period_end_fails_request_shape_validation(
        self, api, build, director_headers
    ):
        """PRD §3.7: "A request names the `pos_id` of the program the purchase is charged to, a `category`, a `description` for the grant file, a `unit_cost_cents` greater than zero, a `quantity` of at least 1, a `service_period_start` and a `service_period_end` on or after it, optionally an `asset_tag` of 3 to 24 characters drawn from uppercase letters, digits and hyphens, and the `expected_grant_award_version` of §2.9."

        PRD §2.7: "Request-body and query-string shape: required fields present, enum members valid, string patterns matched, numeric bounds respected"

        Design: Corner/entities/create_expenditure_without_service_period_end_returns_invalid_request
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)

        response = api.request_expenditure(
            grant.grant_id,
            self._payload_without_service_period_end(program["id"], grant.version),
            director_headers,
        )

        validate_error(response, errors.ERR_INVALID_REQUEST)

    def test_the_rejected_request_leaves_the_award_ledger_and_version_alone(
        self, api, build, director_headers, fiscal_headers
    ):
        """PRD §2.7: "Checks are evaluated in strictly ascending priority and the **first** failure is the response; no later check can mask an earlier one."

        PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`"

        Design: Corner/entities/create_expenditure_without_service_period_end_returns_invalid_request
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)

        validate_error(
            api.request_expenditure(
                grant.grant_id,
                self._payload_without_service_period_end(program["id"], grant.version),
                director_headers,
            ),
            errors.ERR_INVALID_REQUEST,
        )

        award = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_version(award, grant.version)
        assert_cents(award["remaining_cents"], 5000000, "remaining_cents")

        _, meta = validate_paginated(
            api.list_grant_expenditures(grant.grant_id, fiscal_headers)
        )
        assert meta["total_count"] == 0, "nothing may have been stored"


class TestChildCreationUnderAnUnknownParent:
    """A child POST resolves its path segment before it looks at the body."""

    def test_a_course_written_under_an_unknown_program_answers_on_the_programs_code(
        self, api, build, director_headers
    ):
        """PRD §2.6: "Path parameters are resolved strictly left to right, and the first segment that fails to resolve determines the error. Each collection prefix has its own not-found code: `/cte/programs-of-study/{id}` yields `ERR_PROGRAM_NOT_FOUND`"

        PRD §2.7: "Path-parameter existence, left to right — the per-collection not-found codes of §2.6."

        Design: Corner/entities/child_creation_under_an_unknown_parent_returns_that_parents_not_found_error
        """
        program = build.create_program("51.0801", title="Medical Assisting")

        response = api.create_course(
            NON_EXISTENT_UUID,
            f.course_payload("ORP-1", "Orphan", k.SEGMENT_SECONDARY, 1, 1.0),
            director_headers,
        )
        validate_error(response, errors.ERR_PROGRAM_NOT_FOUND)

        _, meta = validate_paginated(
            api.list_program_courses(program["id"], director_headers)
        )
        assert meta["total_count"] == 0, "the orphan course must not have landed anywhere"

    def test_a_member_seated_into_an_unknown_committee_answers_on_the_committees_code(
        self, api, build, director_headers
    ):
        """PRD §2.6: "Each collection prefix has its own not-found code:" and "`/cte/advisory-committees/{id}` yields `ERR_COMMITTEE_NOT_FOUND`"

        PRD §2.7: "Path-parameter existence, left to right — the per-collection not-found codes of §2.6."

        Design: Corner/entities/child_creation_under_an_unknown_parent_returns_that_parents_not_found_error
        """
        build.create_program("51.0801", title="Medical Assisting")

        response = api.seat_member(
            NON_EXISTENT_UUID,
            f.member_payload("Orphan Member", k.SECTOR_EMPLOYER, "EMP-1"),
            director_headers,
        )
        validate_error(response, errors.ERR_COMMITTEE_NOT_FOUND)

    def test_a_charge_against_an_unknown_award_answers_on_the_awards_code(
        self, api, build, director_headers, fiscal_headers
    ):
        """PRD §2.6: "Each collection prefix has its own not-found code:" and "`/cte/grant-awards/{id}` yields `ERR_GRANT_NOT_FOUND`"

        PRD §2.7: "4. Path-parameter existence, left to right — the per-collection not-found codes of §2.6."

        PRD §2.7: "8. Optimistic concurrency on the parent's `version` — `ERR_STALE_PROGRAM_VERSION` or `ERR_STALE_GRANT_VERSION`."

        Design: Corner/entities/child_creation_under_an_unknown_parent_returns_that_parents_not_found_error
        """
        program = build.create_program("51.0801", title="Medical Assisting")
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)

        response = api.request_expenditure(
            NON_EXISTENT_UUID,
            f.expenditure_payload(
                program["id"],
                k.CATEGORY_CONSUMABLE,
                100000,
                1,
                grant.version,
                description="Orphan charge",
            ),
            director_headers,
        )
        validate_error(response, errors.ERR_GRANT_NOT_FOUND)

        _, meta = validate_paginated(
            api.list_grant_expenditures(grant.grant_id, fiscal_headers)
        )
        assert meta["total_count"] == 0, (
            "the charge must not have landed on the award that does exist"
        )

    def test_a_plan_drafted_under_an_unknown_indicator_answers_on_the_indicators_code(
        self, api, build, director_headers
    ):
        """PRD §2.6: "Each collection prefix has its own not-found code:" and "`/cte/performance-indicators/{id}` yields `ERR_INDICATOR_NOT_FOUND`"

        PRD §2.7: "Path-parameter existence, left to right — the per-collection not-found codes of §2.6."

        Design: Corner/entities/child_creation_under_an_unknown_parent_returns_that_parents_not_found_error
        """
        build.create_program("51.0801", title="Medical Assisting")

        response = api.draft_plan(
            NON_EXISTENT_UUID,
            f.plan_payload(
                f.three_milestones(
                    due_dates=["2027-01-31", "2027-03-31", "2027-05-31"]
                )
            ),
            director_headers,
        )
        validate_error(response, errors.ERR_INDICATOR_NOT_FOUND)


class TestCrossEntityForeignKeys:
    """Body-level references are resolved against the row they name."""

    def _two_programs_with_credentials(self, build):
        """Two unrelated programs, each carrying its own exam-bearing credential."""
        first = build.create_program("51.0801", title="Medical Assisting")
        second = build.create_program(
            "11.0201",
            title="Computer Programming",
            cluster=k.CLUSTER_INFORMATION_TECHNOLOGY,
        )
        first_credential = build.add_credential(
            first["id"], "CCMA-1", tier=k.TIER_NATIONAL, exam_required=True
        )
        second_credential = build.add_credential(
            second["id"], "COMPTIA-1", tier=k.TIER_NATIONAL, exam_required=True
        )
        student = build.enroll(first["id"], "100000001")
        return student, first_credential, second_credential

    def test_a_charge_naming_an_unpersisted_program_answers_program_not_found(
        self, api, build, director_headers, fiscal_headers
    ):
        """PRD §2.6: "Foreign keys supplied in a request body are resolved immediately after the path, and they map to the same code family: an unresolvable `pos_id` gives `ERR_PROGRAM_NOT_FOUND`"

        PRD §2.6: "This body-level resolution applies to expenditure requests, sequence-course creation and revision, credential-attainment filing, credit postings, and improvement-plan drafting."

        Design: Corner/entities/cross_entity_foreign_keys_are_validated_against_the_referenced_row
        """
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)

        response = api.request_expenditure(
            grant.grant_id,
            f.expenditure_payload(
                NON_EXISTENT_UUID,
                k.CATEGORY_CONSUMABLE,
                100000,
                1,
                grant.version,
                description="Charge to nobody",
            ),
            director_headers,
        )
        validate_error(response, errors.ERR_PROGRAM_NOT_FOUND)

        award = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_version(award, grant.version)
        assert_cents(award["obligated_cents"], 0)

    def test_a_filing_naming_an_unpersisted_credential_answers_credential_not_found(
        self, api, build, registrar_headers
    ):
        """PRD §2.6: "an unresolvable `credential_id` gives `ERR_CREDENTIAL_NOT_FOUND`"

        PRD §2.6: "This body-level resolution applies to expenditure requests, sequence-course creation and revision, credential-attainment filing, credit postings, and improvement-plan drafting."

        Design: Corner/entities/cross_entity_foreign_keys_are_validated_against_the_referenced_row
        """
        student, _, _ = self._two_programs_with_credentials(build)

        response = api.create_attainment(
            student["id"],
            f.attainment_payload(
                NON_EXISTENT_UUID, "2026-07-20", k.VERIFICATION_VERIFIED, exam_score=88.50
            ),
            registrar_headers,
        )
        validate_error(response, errors.ERR_CREDENTIAL_NOT_FOUND)

    def test_a_credential_belonging_to_another_program_is_refused_as_a_mismatch(
        self, api, build, registrar_headers
    ):
        """PRD §3.5: "Three integrity rules apply in a fixed internal order: the referenced credential must belong to the same program as the student, or the filing fails with `ERR_CREDENTIAL_PROGRAM_MISMATCH`"

        Design: Corner/entities/cross_entity_foreign_keys_are_validated_against_the_referenced_row
        """
        student, _, other_credential = self._two_programs_with_credentials(build)

        response = api.create_attainment(
            student["id"],
            f.attainment_payload(
                other_credential["id"],
                "2026-07-20",
                k.VERIFICATION_VERIFIED,
                exam_score=88.50,
            ),
            registrar_headers,
        )
        validate_error(response, errors.ERR_CREDENTIAL_PROGRAM_MISMATCH)

        _, meta = validate_paginated(api.list_attainments(registrar_headers))
        assert meta["total_count"] == 0, "the mismatched filing must not persist"

    def test_an_exam_bearing_credential_filed_without_a_score_is_refused(
        self, api, build, registrar_headers
    ):
        """PRD §3.5: "an `exam_score` must be supplied whenever the referenced credential has `exam_required` true, or the filing fails with `ERR_EXAM_SCORE_REQUIRED`"

        Design: Corner/entities/cross_entity_foreign_keys_are_validated_against_the_referenced_row
        """
        student, own_credential, _ = self._two_programs_with_credentials(build)

        response = api.create_attainment(
            student["id"],
            f.attainment_payload(
                own_credential["id"], "2026-07-20", k.VERIFICATION_VERIFIED
            ),
            registrar_headers,
        )
        validate_error(response, errors.ERR_EXAM_SCORE_REQUIRED)


class TestReverseReachabilityReads:
    """Each stored reference can be walked backwards from the row it points at."""

    def _wired_program(self, build):
        """A program whose courses, roster, award and charge are all cross-linked."""
        program = build.create_program("51.0801", title="Medical Assisting")
        root = build.add_course(
            program["id"], f.secondary_course("MA-101", 1, 1.0, title="Health Careers")
        )
        leaf = build.add_course(
            program["id"],
            f.postsecondary_course(
                "MA-201",
                2,
                3.0,
                2.0,
                True,
                title="Clinical Procedures",
                prerequisite_course_id=root["id"],
            ),
        )
        student = build.enroll(program["id"], "100000001", cohort_year=2026)
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)
        charge = build.expenditure(
            grant.grant_id, program["id"], k.CATEGORY_CONSUMABLE, 100000, 1
        )
        return program, root, leaf, student, grant, charge

    def test_the_root_course_is_reachable_from_the_course_that_names_it(
        self, api, build, director_headers
    ):
        """PRD §4: "GET | `/cte/sequence-courses/{id}/dependents` | List the sequence courses that name this course as their prerequisite."

        Design: Corner/entities/reverse_reachability_reads_expose_every_declared_foreign_key
        """
        _, root, leaf, _, _, _ = self._wired_program(build)

        rows, meta = validate_paginated(
            api.list_course_dependents(root["id"], director_headers)
        )
        assert meta["total_count"] == 1, "exactly one course names the root as prerequisite"
        assert ids_of(rows) == [leaf["id"]]

    def test_the_last_course_in_the_chain_has_nothing_depending_on_it(
        self, api, build, director_headers
    ):
        """PRD §4: "GET | `/cte/sequence-courses/{id}/dependents` | List the sequence courses that name this course as their prerequisite."

        PRD §2.3: "`total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        Design: Corner/entities/reverse_reachability_reads_expose_every_declared_foreign_key
        """
        _, _, leaf, _, _, _ = self._wired_program(build)

        rows, meta = validate_paginated(
            api.list_course_dependents(leaf["id"], director_headers)
        )
        assert meta["total_count"] == 0, "no course names the terminal course as prerequisite"
        assert rows == []
        assert meta["has_more"] is False

    def test_the_roster_is_reachable_from_the_program_filtered_by_cohort(
        self, api, build, registrar_headers
    ):
        """PRD §4: "GET | `/cte/programs-of-study/{id}/students` | List students enrolled in a program."

        PRD §4: "Collection reads accept the `limit` and `offset` parameters of §2.3 plus the filters named in their descriptions:" and "students by `cohort_year` or `concentrator_status`"

        Design: Corner/entities/reverse_reachability_reads_expose_every_declared_foreign_key
        """
        program, _, _, student, _, _ = self._wired_program(build)

        rows, meta = validate_paginated(
            api.list_program_students(
                program["id"], registrar_headers, f.page(cohort_year=2026)
            )
        )
        assert meta["total_count"] == 1, "the enrolled student answers on her own cohort year"
        assert ids_of(rows) == [student["id"]]

        _, other_meta = validate_paginated(
            api.list_program_students(
                program["id"], registrar_headers, f.page(cohort_year=2027)
            )
        )
        assert other_meta["total_count"] == 0, "no student is reported under the next cohort"

    def test_the_charge_is_reachable_from_the_award_filtered_by_status(
        self, api, build, fiscal_headers
    ):
        """PRD §4: "GET | `/cte/grant-awards/{id}/expenditures` | List expenditures drawn against a grant award."

        PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`"

        Design: Corner/entities/reverse_reachability_reads_expose_every_declared_foreign_key
        """
        _, _, _, _, grant, charge = self._wired_program(build)

        rows, meta = validate_paginated(
            api.list_grant_expenditures(
                grant.grant_id, fiscal_headers, f.page(status=k.EXP_REQUESTED)
            )
        )
        assert meta["total_count"] == 1, "the award reaches back to the charge drawn on it"
        assert ids_of(rows) == [charge["id"]]

    def test_the_charge_is_reachable_from_the_program_filtered_by_category(
        self, api, build, fiscal_headers
    ):
        """PRD §4: "GET | `/cte/programs-of-study/{id}/expenditures` | List expenditures charged to a program."

        PRD §4: "Collection reads accept the `limit` and `offset` parameters of §2.3 plus the filters named in their descriptions:" and "expenditures by `category` or `asset_tag`"

        Design: Corner/entities/reverse_reachability_reads_expose_every_declared_foreign_key
        """
        program, _, _, _, _, charge = self._wired_program(build)

        rows, meta = validate_paginated(
            api.list_program_expenditures(
                program["id"], fiscal_headers, f.page(category=k.CATEGORY_CONSUMABLE)
            )
        )
        assert meta["total_count"] == 1, "the program reaches back to the charge booked to it"
        assert ids_of(rows) == [charge["id"]]

        _, other_meta = validate_paginated(
            api.list_program_expenditures(
                program["id"], fiscal_headers, f.page(category=k.CATEGORY_EQUIPMENT)
            )
        )
        assert other_meta["total_count"] == 0, "no equipment was charged to this program"

    def test_no_improvement_plan_is_reachable_before_one_is_drafted(
        self, api, build, director_headers
    ):
        """PRD §4: "GET | `/cte/improvement-plans` | List improvement plans."

        PRD §2.3: "`total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        Design: Corner/entities/reverse_reachability_reads_expose_every_declared_foreign_key
        """
        self._wired_program(build)

        rows, meta = validate_paginated(
            api.list_plans(director_headers, f.page(status=k.PLAN_DRAFT))
        )
        assert meta["total_count"] == 0, "a wired program alone owes no improvement plan"
        assert rows == []
        assert meta["has_more"] is False
