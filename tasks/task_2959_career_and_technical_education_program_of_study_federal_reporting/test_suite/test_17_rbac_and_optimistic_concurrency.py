"""Role authorization, the chair identity binding, and the two version guards.

Every test drives the public API only, against an empty database whose logical
clock starts at its startup default, and asserts an outcome the PRD derives
uniquely.
"""

from test_helpers import (
    Builder,
    CteApiClient,
    STOP_COMMITTEE_REVIEW,
    STOP_DRAFT,
    STOP_STATE_APPROVED,
    assert_cohort_figures,
    assert_pct,
    assert_quorum_figures,
    assert_version,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)

MEETING_INSTANT = "2026-08-18T15:00:00.000Z"


def _committee_with_scheduled_meeting(build: Builder, cip_code: str):
    """A chartered committee with a seated chair and one SCHEDULED meeting."""
    scenario = build.program(cip_code, stop_at=STOP_DRAFT)
    row = build.charter_committee(scenario.program_id)
    committee = build.seat_roster(row["id"])
    meeting = build.schedule_meeting(
        committee.committee_id,
        committee.chair_member_id,
        k.AGENDA_POS_ENDORSEMENT,
        MEETING_INSTANT,
    )
    return committee, meeting["id"]


def _passing_minutes(committee):
    """A minutes payload that clears quorum for the default three-seat roster."""
    return f.minutes_payload(
        MEETING_INSTANT, committee.member_ids, vote_yes=3, vote_no=0
    )


class TestExclusiveOperations:
    """An operation reserved to one role refuses every other role."""

    def test_a_director_cannot_grant_state_approval(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "When the headers are well-formed but the named role is not permitted to invoke the endpoint being called, the response is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4: "| POST | `/cte/programs-of-study/{id}/state-approve` | Grant state approval to a program under committee review, unlocking federal expenditure certification. | StateComplianceReviewer |"

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        scenario = build.program("51.3801", stop_at=STOP_COMMITTEE_REVIEW)

        res = api.state_approve(
            scenario.program_id,
            f.state_approve_payload(approval_note="District self-approval attempt"),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_a_state_reviewer_cannot_author_a_program_of_study(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "When the headers are well-formed but the named role is not permitted to invoke the endpoint being called, the response is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4: "| POST | `/cte/programs-of-study` | Create a program of study in DRAFT with its CLNA not yet started. | CteDirector |"

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        res = api.create_program(
            f.program_payload("51.3801"), users.headers(users.REVIEWER)
        )
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_a_fiscal_officer_cannot_enroll_a_student(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "When the headers are well-formed but the named role is not permitted to invoke the endpoint being called, the response is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4: "| POST | `/cte/programs-of-study/{id}/students` | Enroll a student in a program of study as a participant. | SchoolRegistrar |"

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        scenario = build.program("51.3801", stop_at=STOP_DRAFT)

        res = api.enroll_student(
            scenario.program_id,
            f.student_payload("100000001", 2026),
            users.headers(users.FISCAL_OFFICER),
        )
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_a_registrar_cannot_record_a_federal_award(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "When the headers are well-formed but the named role is not permitted to invoke the endpoint being called, the response is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4: "| POST | `/cte/grant-awards` | Record a federal grant award with its obligation window. | GrantFiscalOfficer |"

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        res = api.create_grant(
            f.grant_payload(2027, 5000000), users.headers(users.REGISTRAR)
        )
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_a_director_cannot_schedule_a_committee_meeting(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "A `CommitteeChair` is the seated chair of exactly one advisory committee and may schedule that committee's meetings and file or amend its minutes."

        PRD §4: "| POST | `/cte/advisory-committees/{id}/meetings` | Schedule a committee meeting with a declared agenda kind. | CommitteeChair |"

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        scenario = build.program("51.3801", stop_at=STOP_DRAFT)
        row = build.charter_committee(scenario.program_id)
        build.seat_roster(row["id"])

        res = api.schedule_meeting(
            row["id"],
            f.meeting_payload(k.AGENDA_EQUIPMENT_REVIEW, MEETING_INSTANT),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_a_registrar_cannot_read_a_federal_award(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "When the headers are well-formed but the named role is not permitted to invoke the endpoint being called, the response is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4: "| GET | `/cte/grant-awards/{id}` | Retrieve one grant award, including its obligated, remaining and administrative-cap figures. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |"

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)

        res = api.get_grant(grant.grant_id, users.headers(users.REGISTRAR))
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_an_active_member_who_is_not_the_chair_cannot_file_minutes(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "Both chair-only operations resolve the target committee — directly for meeting scheduling, or through the target meeting's `committee_id` when minutes are filed — and then require that a `CommitteeMember` exists whose `id` equals `X-User-ID`, whose `committee_id` is that committee, whose `status` is `ACTIVE`, and whose `is_chair` is true. A caller who fails this identity binding receives `ERR_UNAUTHORIZED` (HTTP 403), the same code used for a plain role mismatch; the binding is evaluated after the endpoint's role list has already admitted `CommitteeChair`, and after path resources have been resolved."

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        committee, meeting_id = _committee_with_scheduled_meeting(build, "51.3801")
        rank_and_file = [
            member_id
            for member_id in committee.member_ids
            if member_id != committee.chair_member_id
        ][0]

        res = api.file_minutes(
            meeting_id,
            _passing_minutes(committee),
            users.chair_headers(rank_and_file),
        )
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_the_chair_of_another_committee_cannot_file_these_minutes(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "`CommitteeChair` is the one **entity-backed** role. When `X-User-Role` is `CommitteeChair`, `X-User-ID` is the `id` of the acting `CommitteeMember`. Both chair-only operations resolve the target committee — directly for meeting scheduling, or through the target meeting's `committee_id` when minutes are filed — and then require that a `CommitteeMember` exists whose `id` equals `X-User-ID`, whose `committee_id` is that committee, whose `status` is `ACTIVE`, and whose `is_chair` is true."

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        committee, meeting_id = _committee_with_scheduled_meeting(build, "51.3801")
        other = build.program("51.3802", stop_at=STOP_DRAFT)
        other_row = build.charter_committee(other.program_id)
        other_committee = build.seat_roster(other_row["id"])

        res = api.file_minutes(
            meeting_id,
            _passing_minutes(committee),
            users.chair_headers(other_committee.chair_member_id),
        )
        validate_error(res, errors.ERR_UNAUTHORIZED)

    def test_an_empty_operator_identifier_is_rejected_before_the_role_list(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "Both must be present and non-empty, and `X-User-Role` must name one of the five roles the system recognises; a request that fails any part of that check is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about it is examined."

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        scenario = build.program("51.3801", stop_at=STOP_DRAFT)

        res = api.get_program(
            scenario.program_id,
            users.blank_user_id_headers(k.ROLE_CTE_DIRECTOR),
        )
        validate_error(res, errors.ERR_UNAUTHENTICATED)

    def test_a_role_outside_the_catalogue_is_rejected_before_the_role_list(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "Both must be present and non-empty, and `X-User-Role` must name one of the five roles the system recognises; a request that fails any part of that check is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about it is examined."

        PRD §2.1: "The five roles are `CteDirector`, `StateComplianceReviewer`, `GrantFiscalOfficer`, `CommitteeChair`, and `SchoolRegistrar`."

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        scenario = build.program("51.3801", stop_at=STOP_DRAFT)

        res = api.get_program(
            scenario.program_id,
            users.unknown_role_headers(users.DIRECTOR.user_id, k.ROLE_NOT_IN_CATALOGUE),
        )
        validate_error(res, errors.ERR_UNAUTHENTICATED)

    def test_the_seated_chair_files_the_minutes_the_others_were_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.1: "Both chair-only operations resolve the target committee — directly for meeting scheduling, or through the target meeting's `committee_id` when minutes are filed — and then require that a `CommitteeMember` exists whose `id` equals `X-User-ID`, whose `committee_id` is that committee, whose `status` is `ACTIVE`, and whose `is_chair` is true."

        PRD §4: "| POST | `/cte/committee-meetings/{id}/minutes` | File or amend the minutes of a meeting, recording attendance and the endorsement vote. | CommitteeChair |"

        Design: Corner/rbac/other_roles_cannot_perform_a_roles_exclusive_operations
        """
        committee, meeting_id = _committee_with_scheduled_meeting(build, "51.3801")

        res = api.file_minutes(
            meeting_id,
            _passing_minutes(committee),
            users.chair_headers(committee.chair_member_id),
        )
        filed = validate_unpaginated(res, 200)
        assert filed["minutes_status"] == k.MINUTES_FINALIZED
        assert_quorum_figures(
            filed, eligible=3, employer=2, quorum_met=True, endorsement_passed=True
        )


def _program_visible_to_every_role(build: Builder):
    """A DRAFT program whose committee gives a chair identity to read it with."""
    scenario = build.program("41.0101", stop_at=STOP_DRAFT)
    row = build.charter_committee(scenario.program_id)
    committee = build.seat_roster(row["id"])
    return scenario, committee


class TestSharedOperations:
    """An operation that lists several roles admits each of them."""

    def test_the_director_reads_the_program_of_study(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §4: "| GET | `/cte/programs-of-study/{id}` | Retrieve one program of study, including its computed alignment index and CLNA phase. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |"

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)

        row = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )
        assert row["id"] == scenario.program_id
        assert row["cip_code"] == scenario.cip_code

    def test_the_state_reviewer_reads_the_program_of_study(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §4: "| GET | `/cte/programs-of-study/{id}` | Retrieve one program of study, including its computed alignment index and CLNA phase. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |"

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)

        row = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.REVIEWER))
        )
        assert row["id"] == scenario.program_id
        assert row["approval_status"] == k.APPROVAL_DRAFT

    def test_the_fiscal_officer_reads_the_program_of_study(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §4: "| GET | `/cte/programs-of-study/{id}` | Retrieve one program of study, including its computed alignment index and CLNA phase. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |"

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)

        row = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.FISCAL_OFFICER))
        )
        assert row["id"] == scenario.program_id
        assert row["clna_phase"] == k.CLNA_NOT_STARTED

    def test_the_seated_chair_reads_the_program_of_study(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §4: "| GET | `/cte/programs-of-study/{id}` | Retrieve one program of study, including its computed alignment index and CLNA phase. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |"

        PRD §2.1: "When `X-User-Role` is `CommitteeChair`, `X-User-ID` is the `id` of the acting `CommitteeMember`."

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, committee = _program_visible_to_every_role(build)

        row = validate_unpaginated(
            api.get_program(
                scenario.program_id, users.chair_headers(committee.chair_member_id)
            )
        )
        assert row["id"] == scenario.program_id

    def test_the_registrar_reads_the_program_of_study(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §4: "| GET | `/cte/programs-of-study/{id}` | Retrieve one program of study, including its computed alignment index and CLNA phase. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |"

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)

        row = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.REGISTRAR))
        )
        assert row["id"] == scenario.program_id

    def test_the_director_opens_the_needs_assessment(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.2: "Both a `CteDirector` and a `StateComplianceReviewer` may drive it, one phase at a time, by naming the target phase in a `to_phase` field and optionally attaching an `evidence_url` documenting the step."

        PRD §3.2: "Opening the assessment moves `NOT_STARTED → DATA_COLLECTION` and requires only that the program already carry a non-null `labor_market_data_asof`."

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)

        res = api.advance_clna(
            scenario.program_id,
            f.clna_advance_payload(k.CLNA_DATA_COLLECTION),
            users.headers(users.DIRECTOR),
        )
        opened = validate_unpaginated(res, 200)
        assert opened["clna_phase"] == k.CLNA_DATA_COLLECTION

    def test_the_state_reviewer_advances_the_needs_assessment(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.2: "Both a `CteDirector` and a `StateComplianceReviewer` may drive it, one phase at a time, by naming the target phase in a `to_phase` field and optionally attaching an `evidence_url` documenting the step."

        PRD §3.2: "Leaving data collection for `DATA_COLLECTION → STAKEHOLDER_CONSULTATION` imposes the freshness rule: the labor-market dataset behind the assessment may be at most two years old, meaning the difference between the logical clock's date and `labor_market_data_asof` must be no more than 730 days."

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)
        build.advance_clna(scenario.program_id, k.CLNA_DATA_COLLECTION)

        res = api.advance_clna(
            scenario.program_id,
            f.clna_advance_payload(
                k.CLNA_STAKEHOLDER_CONSULTATION,
                evidence_url="https://state.example/consultation.pdf",
            ),
            users.headers(users.REVIEWER),
        )
        advanced = validate_unpaginated(res, 200)
        assert advanced["clna_phase"] == k.CLNA_STAKEHOLDER_CONSULTATION

    def test_the_registrar_drives_the_logical_clock(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.5: "An administrative test-driving capability accepts a `to_iso8601` instant and moves the clock to it; the call mutates no stored entity, but every request that follows evaluates its temporal rules against the new reading. All five roles may drive the clock."

        PRD §4: "| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock, which every date and window rule reads. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |"

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)
        before = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )

        validate_unpaginated(
            api.set_clock("2026-09-15T09:30:00Z", users.headers(users.REGISTRAR)), 200
        )

        after = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )
        assert_version(after, before["version"])

    def test_two_accepted_advances_move_the_program_version_twice(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.2: "A `to_phase` that is not the declared successor of the program's current `clna_phase` is refused with `ERR_INVALID_CLNA_PHASE_TRANSITION`; each accepted advance increments the program's `version`."

        Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
        """
        scenario, _ = _program_visible_to_every_role(build)
        before = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )

        build.advance_clna(
            scenario.program_id, k.CLNA_DATA_COLLECTION, actor=users.DIRECTOR
        )
        build.advance_clna(
            scenario.program_id, k.CLNA_STAKEHOLDER_CONSULTATION, actor=users.REVIEWER
        )

        after = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )
        assert_version(after, before["version"] + 2)


OCC_ALLOCATION_CENTS = 5000000
OCC_UNIT_COST_CENTS = 120000


def _program_whose_version_moved_on(build: Builder, api: CteApiClient):
    """A program the client last read at ``stale``, since advanced by a writer."""
    scenario = build.program("47.0604", stop_at=STOP_DRAFT)
    stale = validate_unpaginated(
        api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
    )["version"]
    validate_unpaginated(
        api.patch_program(
            scenario.program_id,
            f.program_patch(title="Diesel Technology Pathway"),
            users.headers(users.DIRECTOR),
        )
    )
    return scenario, stale


class TestOptimisticConcurrencyGuards:
    """Both guarded creates refuse a stale parent version and accept the current one."""

    def test_chartering_on_a_stale_program_version_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "Chartering an advisory committee under a program of study requires `expected_program_of_study_version` in the body, carrying the client's last observed `version` of that `ProgramOfStudy`. If the program's current `version` differs from the supplied value — because any writer has advanced it since the client read the program — the create is refused with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario, stale = _program_whose_version_moved_on(build, api)

        res = api.charter_committee(
            scenario.program_id,
            f.committee_payload(stale),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_STALE_PROGRAM_VERSION)

    def test_chartering_on_the_current_program_version_is_accepted(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "Chartering an advisory committee under a program of study requires `expected_program_of_study_version` in the body, carrying the client's last observed `version` of that `ProgramOfStudy`."

        PRD §3.3: "A newly chartered committee starts in `status` `FORMING` with `active_member_count` 0, `employer_member_count` 0 and `chair_member_id` null, and its creation increments the parent program's `version`."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario, stale = _program_whose_version_moved_on(build, api)
        current = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )["version"]
        assert current != stale

        res = api.charter_committee(
            scenario.program_id,
            f.committee_payload(current),
            users.headers(users.DIRECTOR),
        )
        chartered = validate_unpaginated(res, 201)
        assert chartered["status"] == k.COMMITTEE_FORMING
        assert chartered["active_member_count"] == 0
        assert chartered["employer_member_count"] == 0
        assert chartered["chair_member_id"] is None

    def test_a_stale_charter_leaves_the_program_without_a_committee(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "If the program's current `version` differs from the supplied value — because any writer has advanced it since the client read the program — the create is refused with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

        PRD §2.9: "This guard matters precisely because nothing else blocks the call: a newly chartered committee legitimately supersedes the prior committee on the same program, moving that predecessor to `DISSOLVED`, so no state precondition would reject a second charter."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario, stale = _program_whose_version_moved_on(build, api)
        validate_error(
            api.charter_committee(
                scenario.program_id,
                f.committee_payload(stale),
                users.headers(users.DIRECTOR),
            ),
            errors.ERR_STALE_PROGRAM_VERSION,
        )

        committees, meta = validate_paginated(
            api.list_program_committees(
                scenario.program_id, users.headers(users.DIRECTOR)
            )
        )
        assert meta["total_count"] == 0
        assert committees == []

    def test_chartering_without_the_program_version_is_a_request_shape_failure(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "Two create operations are guarded by optimistic concurrency against their parent record's `version`, and only those two. Both take the version field as a **required** input, not an optional one; omitting it is a request-shape failure."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario = build.program("47.0604", stop_at=STOP_DRAFT)
        current = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )["version"]
        payload = f.committee_payload(current)
        del payload["expected_program_of_study_version"]

        res = api.charter_committee(
            scenario.program_id, payload, users.headers(users.DIRECTOR)
        )
        validate_error(res, errors.ERR_INVALID_REQUEST)

    def test_requesting_a_charge_on_a_stale_award_version_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "Requesting an expenditure against a grant award requires `expected_grant_award_version` in the body, carrying the client's last observed `version` of that `GrantAward`. A mismatch with the award's current `version` is refused with `ERR_STALE_GRANT_VERSION` (HTTP 412)."

        PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario = build.program("47.0604", stop_at=STOP_DRAFT)
        grant = build.grant(fiscal_year=2027, allocation_cents=OCC_ALLOCATION_CENTS)
        build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            OCC_UNIT_COST_CENTS,
            expected_version=grant.version,
        )

        res = api.request_expenditure(
            grant.grant_id,
            f.expenditure_payload(
                scenario.program_id,
                k.CATEGORY_CONSUMABLE,
                OCC_UNIT_COST_CENTS,
                1,
                grant.version,
            ),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_STALE_GRANT_VERSION)

    def test_requesting_a_charge_on_the_refreshed_award_version_is_accepted(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "Requesting an expenditure against a grant award requires `expected_grant_award_version` in the body, carrying the client's last observed `version` of that `GrantAward`. A mismatch with the award's current `version` is refused with `ERR_STALE_GRANT_VERSION` (HTTP 412). Again, two distinct purchase requests against one award are both legitimate under the product semantics and no state check rejects the second; the stale version is what signals that the client sized its request against a superseded `remaining_cents` figure."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario = build.program("47.0604", stop_at=STOP_DRAFT)
        grant = build.grant(fiscal_year=2027, allocation_cents=OCC_ALLOCATION_CENTS)
        first = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            OCC_UNIT_COST_CENTS,
            expected_version=grant.version,
        )
        refreshed = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )["version"]

        res = api.request_expenditure(
            grant.grant_id,
            f.expenditure_payload(
                scenario.program_id,
                k.CATEGORY_CONSUMABLE,
                OCC_UNIT_COST_CENTS,
                1,
                refreshed,
            ),
            users.headers(users.DIRECTOR),
        )
        second = validate_unpaginated(res, 201)
        assert second["id"] != first["id"]
        assert second["status"] == k.EXP_REQUESTED

        lines, meta = validate_paginated(
            api.list_grant_expenditures(
                grant.grant_id, users.headers(users.FISCAL_OFFICER)
            )
        )
        assert meta["total_count"] == 2

    def test_a_stale_charge_request_writes_no_expenditure_row(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "A mismatch with the award's current `version` is refused with `ERR_STALE_GRANT_VERSION` (HTTP 412)."

        PRD §2.9: "Again, two distinct purchase requests against one award are both legitimate under the product semantics and no state check rejects the second; the stale version is what signals that the client sized its request against a superseded `remaining_cents` figure."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario = build.program("47.0604", stop_at=STOP_DRAFT)
        grant = build.grant(fiscal_year=2027, allocation_cents=OCC_ALLOCATION_CENTS)
        build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            OCC_UNIT_COST_CENTS,
            expected_version=grant.version,
        )
        before = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )

        validate_error(
            api.request_expenditure(
                grant.grant_id,
                f.expenditure_payload(
                    scenario.program_id,
                    k.CATEGORY_CONSUMABLE,
                    OCC_UNIT_COST_CENTS,
                    1,
                    grant.version,
                ),
                users.headers(users.DIRECTOR),
            ),
            errors.ERR_STALE_GRANT_VERSION,
        )

        lines, meta = validate_paginated(
            api.list_grant_expenditures(
                grant.grant_id, users.headers(users.FISCAL_OFFICER)
            )
        )
        assert meta["total_count"] == 1

        after = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )
        assert_version(after, before["version"])

    def test_requesting_a_charge_without_the_award_version_is_a_request_shape_failure(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.9: "Two create operations are guarded by optimistic concurrency against their parent record's `version`, and only those two. Both take the version field as a **required** input, not an optional one; omitting it is a request-shape failure."

        PRD §3.7: "A request names the `pos_id` of the program the purchase is charged to, a `category`, a `description` for the grant file, a `unit_cost_cents` greater than zero, a `quantity` of at least 1, a `service_period_start` and a `service_period_end` on or after it, optionally an `asset_tag` of 3 to 24 characters drawn from uppercase letters, digits and hyphens, and the `expected_grant_award_version` of §2.9."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_refuse_a_stale_parent_version_and_accept_the_current_one
        """
        scenario = build.program("47.0604", stop_at=STOP_DRAFT)
        grant = build.grant(fiscal_year=2027, allocation_cents=OCC_ALLOCATION_CENTS)
        payload = f.expenditure_payload(
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            OCC_UNIT_COST_CENTS,
            1,
            grant.version,
        )
        del payload["expected_grant_award_version"]

        res = api.request_expenditure(
            grant.grant_id, payload, users.headers(users.DIRECTOR)
        )
        validate_error(res, errors.ERR_INVALID_REQUEST)


MISS_ALLOCATION_CENTS = 5000000
MISS_UNIT_COST_CENTS = 100000
FIRST_CLOSE_DATE = "2027-06-30"
SECOND_CLOSE_DATE = "2027-07-01"
AGREED_LEVEL_PCT = 90.00
MET_THRESHOLD_PCT = 81.00


def _approved_program_with_an_agreed_indicator(build: Builder):
    """A state-approved program, an open charge, a five-strong cohort and a target."""
    scenario = build.program("15.0613", stop_at=STOP_STATE_APPROVED)
    grant = build.grant(fiscal_year=2027, allocation_cents=MISS_ALLOCATION_CENTS)
    line = build.expenditure(
        grant.grant_id,
        scenario.program_id,
        k.CATEGORY_CONSUMABLE,
        MISS_UNIT_COST_CENTS,
    )
    students = build.cohort(
        scenario, 5, verified_count=2, credit_delta=2.0, cohort_year=2026
    )
    indicator = build.agreed_indicator(
        scenario.program_id,
        k.INDICATOR_4S1_CREDENTIAL,
        AGREED_LEVEL_PCT,
        reporting_year=2027,
        baseline_pct=AGREED_LEVEL_PCT,
        cohort_year=2026,
    )
    return scenario, line, indicator["id"], students


class TestConsecutiveMissCountBelowTolerance:
    """One miss counts, does not escalate, and a met year clears it."""

    def test_the_first_close_scores_the_year_short_of_its_target(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "When `denominator_count` is at least 5 and `actual_pct` is strictly below `met_threshold_pct`, the indicator is scored `NOT_MET` and `consecutive_miss_count` increases by 1; from `NOT_MET` this is a self-loop that re-enters `NOT_MET` for a second consecutive miss."

        PRD §3.8: "`numerator_count` is the number of those same students whose `verified_qualifying_attainment_count` is at least 1. `small_cohort_flag` is true exactly when `denominator_count` is below the federal minimum cohort size of 5. The raw percentage is null when `denominator_count` is zero; otherwise it is 100 multiplied by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal places."

        Design: Corner/cross_cutting_complexity_layers/consecutive_miss_count_stays_below_the_tolerance_after_one_miss_and_resets_on_a_met_year
        """
        _, _, indicator_id, _ = _approved_program_with_an_agreed_indicator(build)

        res = api.close_reporting_year(
            indicator_id,
            f.close_year_payload(FIRST_CLOSE_DATE),
            users.headers(users.REVIEWER),
        )
        closed = validate_unpaginated(res, 200)
        assert closed["status"] == k.PI_NOT_MET
        assert_cohort_figures(closed, denominator=5, numerator=2, small_cohort=False)
        assert_pct(closed["actual_pct"], 40.00, "actual_pct")
        assert_pct(closed["met_threshold_pct"], MET_THRESHOLD_PCT, "met_threshold_pct")
        assert closed["closed_on"] == FIRST_CLOSE_DATE

    def test_one_miss_leaves_the_counter_below_the_tolerance(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The increment of `consecutive_miss_count` is cascade link 1, and it is that increment reaching the miss tolerance of 2 — not the close itself — that fires link 2: the indicator escalates `NOT_MET → IMPROVEMENT_REQUIRED`."

        Design: Corner/cross_cutting_complexity_layers/consecutive_miss_count_stays_below_the_tolerance_after_one_miss_and_resets_on_a_met_year
        """
        _, _, indicator_id, _ = _approved_program_with_an_agreed_indicator(build)
        build.close_year(indicator_id, FIRST_CLOSE_DATE)

        standing = validate_unpaginated(
            api.get_indicator(indicator_id, users.headers(users.REVIEWER))
        )
        assert standing["consecutive_miss_count"] == 1
        assert standing["status"] == k.PI_NOT_MET

    def test_one_miss_does_not_suspend_the_program_of_study(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "Link 2 in turn fires link 3, which suspends the program: a program of study in `approval_status` `STATE_APPROVED` moves `STATE_APPROVED → SUSPENDED`, has `federal_reporting_eligible` set to false, appends the finding code `PERF_SUSPENSION` to `open_finding_codes`, and has its `version` incremented."

        Design: Corner/cross_cutting_complexity_layers/consecutive_miss_count_stays_below_the_tolerance_after_one_miss_and_resets_on_a_met_year
        """
        scenario, _, indicator_id, _ = _approved_program_with_an_agreed_indicator(build)
        build.close_year(indicator_id, FIRST_CLOSE_DATE)

        program = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )
        assert program["approval_status"] == k.APPROVAL_STATE_APPROVED
        assert k.FINDING_PERF_SUSPENSION not in program["open_finding_codes"]

    def test_one_miss_does_not_block_the_requested_charge(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "And that suspension fires link 4: every expenditure charged to that program whose `status` is `REQUESTED` moves `REQUESTED → BLOCKED`, each with its own `version` increment."

        Design: Corner/cross_cutting_complexity_layers/consecutive_miss_count_stays_below_the_tolerance_after_one_miss_and_resets_on_a_met_year
        """
        _, line, indicator_id, _ = _approved_program_with_an_agreed_indicator(build)
        build.close_year(indicator_id, FIRST_CLOSE_DATE)

        charge = validate_unpaginated(
            api.get_expenditure(line["id"], users.headers(users.FISCAL_OFFICER))
        )
        assert charge["status"] == k.EXP_REQUESTED

    def test_later_verifications_lift_the_preliminary_reading_above_the_target(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The `PRELIMINARY_UNADJUSTED` variant ignores `small_cohort_flag` completely: it publishes the raw percentage as `preliminary_actual_pct` and sets `preliminary_status_projection` to `MET` when the raw percentage is at least `met_threshold_pct`, to `NOT_MET` when it is strictly below, and to `UNDEFINED` whenever either the raw percentage or `met_threshold_pct` is null. This variant is recomputed on every read of the indicator and on every cascade that changes any cohort member's `concentrator_status`, and it never suppresses anything."

        Design: Corner/cross_cutting_complexity_layers/consecutive_miss_count_stays_below_the_tolerance_after_one_miss_and_resets_on_a_met_year
        """
        scenario, _, indicator_id, students = _approved_program_with_an_agreed_indicator(
            build
        )
        build.close_year(indicator_id, FIRST_CLOSE_DATE)
        for student in students[2:]:
            build.attain(student["id"], scenario.credential_id)

        refreshed = validate_unpaginated(
            api.get_indicator(indicator_id, users.headers(users.REVIEWER))
        )
        assert_cohort_figures(refreshed, denominator=5, numerator=5, small_cohort=False)
        assert_pct(refreshed["preliminary_actual_pct"], 100.00, "preliminary_actual_pct")
        assert refreshed["preliminary_status_projection"] == k.PROJECTION_MET
        assert_pct(refreshed["actual_pct"], 40.00, "actual_pct")

    def test_a_met_year_resets_the_consecutive_miss_counter(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "When `denominator_count` is at least 5 and `actual_pct` is at least `met_threshold_pct` (the comparison is inclusive), the indicator is scored `MET` and `consecutive_miss_count` is reset to 0."

        PRD §3.8: "The call is admissible from `AGREED`, from `ARBITRATED`, from `NOT_MET` and from `MONITORING`; from `NOT_MET` or `MONITORING` it additionally requires the supplied `closed_on` to be strictly later than the `closed_on` already stored, because each close advances the reporting year."

        Design: Corner/cross_cutting_complexity_layers/consecutive_miss_count_stays_below_the_tolerance_after_one_miss_and_resets_on_a_met_year
        """
        scenario, _, indicator_id, students = _approved_program_with_an_agreed_indicator(
            build
        )
        build.close_year(indicator_id, FIRST_CLOSE_DATE)
        for student in students[2:]:
            build.attain(student["id"], scenario.credential_id)

        res = api.close_reporting_year(
            indicator_id,
            f.close_year_payload(SECOND_CLOSE_DATE),
            users.headers(users.REVIEWER),
        )
        recovered = validate_unpaginated(res, 200)
        assert recovered["status"] == k.PI_MET
        assert recovered["consecutive_miss_count"] == 0
        assert_pct(recovered["actual_pct"], 100.00, "actual_pct")
        assert recovered["closed_on"] == SECOND_CLOSE_DATE

        program = validate_unpaginated(
            api.get_program(scenario.program_id, users.headers(users.DIRECTOR))
        )
        assert program["approval_status"] == k.APPROVAL_STATE_APPROVED
