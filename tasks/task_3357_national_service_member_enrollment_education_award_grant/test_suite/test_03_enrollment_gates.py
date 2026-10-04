"""Enrollment gates: criminal-check posture, age/debarment safety, slot
selection, overlap, and optimistic concurrency on the award (PRD §2.8, §3.4)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    award_version,
    clear_check,
    create_enrollment_payload,
    enroll,
    get_enrollment,
    initiate_check,
    make_grantee_staff_headers,
    record_component,
    register_cleared_member,
    register_flagged_member,
    register_member,
    register_pending_check_member,
    setup_awarded_program,
    setup_org_competition,
    slot_request,
    match_line,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]

FULL_TIME_1_SLOT = {
    "federal_share_requested_cents": 2300000,
    "slot_requests": [slot_request("FULL_TIME", 1)],
    "match_lines": [match_line("CASH", 560000)],
}


class TestEnrollmentActivationGatedOnCheck:
    def _setup_pending_checks_enrollment(self, api):
        program = setup_awarded_program()
        member_id, check_id = register_pending_check_member(program["org_id"])
        enrollment = enroll(program["award_id"], program["org_id"], member_id)
        return program, member_id, check_id, enrollment

    def test_pending_check_enrollment_rejects_hour_entries(self, api):
        """An enrollment created while the latest check is still PENDING waits
        in PENDING_CHECKS and rejects hour recording until adjudication.

        PRD §3.4: "the latest check must not have adjudicated `FLAGGED` (`ERR_CRIMINAL_CHECK_FLAGGED`) — a still-`PENDING` latest check is acceptable, and the enrollment simply waits."
        PRD §3.5: "Against an `ACTIVE` enrollment — recording against an enrollment in any other state is `ERR_ENROLLMENT_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/enrollment_activation_gated_on_check
        """
        program, member_id, check_id, enrollment = self._setup_pending_checks_enrollment(api)
        assert enrollment["status"] == "PENDING_CHECKS"
        staff = make_grantee_staff_headers(program["org_id"])
        resp = api.create_hour_entry(
            enrollment["id"],
            {"service_date": "2026-10-16", "minutes": 480, "activity_code": "DIRECT_SERVICE"},
            staff,
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
        assert get_enrollment(enrollment["id"])["status"] == "PENDING_CHECKS"

    def test_cleared_check_activates_enrollment_and_fills_slot(self, api, officer_headers):
        """The third CLEAR component adjudicates the check CLEARED and the
        waiting enrollment auto-activates; its slot steps RESERVED -> FILLED.

        PRD §3.4: "on `CLEARED`, every enrollment of that member waiting in `PENDING_CHECKS` becomes `ACTIVE` and each such enrollment's reserved slot fills (`RESERVED` → `FILLED`, `fill_count` incremented)"

        Design: Difficulty/cross_entity_state_dependency/enrollment_activation_gated_on_check
        """
        program, member_id, check_id, enrollment = self._setup_pending_checks_enrollment(api)
        slot_id = enrollment["slot_id"]
        record_component(check_id, "NSOPR", "CLEAR")
        record_component(check_id, "STATE_REPOSITORY", "CLEAR")
        record_component(check_id, "FBI_FINGERPRINT", "CLEAR")
        activated = get_enrollment(enrollment["id"])
        assert activated["status"] == "ACTIVE", "system transition on adjudication"
        slot = validate_success(api.get_slot(slot_id, officer_headers))
        assert slot["status"] == "FILLED" and slot["fill_count"] == 1
        staff = make_grantee_staff_headers(program["org_id"])
        resp = api.create_hour_entry(
            enrollment["id"],
            {"service_date": "2026-10-16", "minutes": 480, "activity_code": "DIRECT_SERVICE"},
            staff,
        )
        validate_success(resp, 201)


class TestFlaggedCheckSafetyBeatsSlotConstraint:
    def _setup(self, api):
        program = setup_awarded_program(**FULL_TIME_1_SLOT)
        member_a = register_cleared_member(program["org_id"])
        enroll(program["award_id"], program["org_id"], member_a)
        member_b, check_b = register_flagged_member(
            program["org_id"], full_name="Blair Kim", date_of_birth="1999-05-20",
            citizenship_status="US_NATIONAL",
        )
        return program, member_b, check_b

    def test_flagged_check_rejects_even_with_no_open_slot(self, api):
        """With the only FULL_TIME slot FILLED and the member's latest check
        FLAGGED, enrollment fails with the safety error, not the slot error —
        safety checks run before constraint checks.

        PRD §2.10: "then business rules — safety checks first, then temporal checks, then constraint checks, then fiscal gates."
        PRD §3.4: "the latest check must not have adjudicated `FLAGGED` (`ERR_CRIMINAL_CHECK_FLAGGED`)"

        Design: Difficulty/priority_pair_validation_conflict/flagged_check_safety_beats_slot_constraint
        """
        program, member_b, check_b = self._setup(api)
        version = award_version(program["award_id"])
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member_b,
                service_start_date="2026-11-01",
                service_end_date="2027-09-01",
                expected_award_version=version,
            ),
            make_grantee_staff_headers(program["org_id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_CRIMINAL_CHECK_FLAGGED)
        assert err["error_id"] != ApiErrorId.ERR_NO_OPEN_SLOT
        assert resp.status_code == 422

    def test_flagged_adjudication_recorded_and_no_enrollment_created(self, api, officer_headers):
        """The member's check adjudicates FLAGGED (one FLAGGED component, none
        pending) and the rejected create leaves no enrollment behind.

        PRD §3.4: "becomes `FLAGGED` the moment every component has a result and at least one is `FLAGGED`"
        PRD §3.4: "the latest check must not have adjudicated `FLAGGED` (`ERR_CRIMINAL_CHECK_FLAGGED`)"

        Design: Difficulty/priority_pair_validation_conflict/flagged_check_safety_beats_slot_constraint
        """
        program, member_b, check_b = self._setup(api)
        version = award_version(program["award_id"])
        api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member_b,
                service_start_date="2026-11-01",
                service_end_date="2027-09-01",
                expected_award_version=version,
            ),
            make_grantee_staff_headers(program["org_id"]),
        )
        rows, _ = validate_paginated(api.list_criminal_checks(member_b, officer_headers))
        assert rows[0]["adjudication"] == "FLAGGED"
        enrollments, meta = validate_paginated(
            api.list_enrollments(officer_headers, params={"member_id": member_b})
        )
        assert enrollments == [] and meta["total_count"] == 0


class TestEnrollmentCreationFields:
    def test_enrollment_created_with_term_minutes_and_zero_ledgers(self, api, officer_headers):
        """A FULL_TIME enrollment for an already-cleared member is ACTIVE from
        birth with term_minutes copied from the term table, zeroed accumulators,
        origin NONE, and the award's version bumped by 1.

        PRD §3.4: "the enrollment lands with its `term_minutes` copied from the term table, its hour and payment accumulators (`certified_minutes`, `fundraising_certified_minutes`, `allowance_paid_cents`) at 0, and `suspension_origin` `NONE`"
        PRD §3.4: "If the member's latest check is already `CLEARED` at creation time, the enrollment activates immediately — `ACTIVE` from birth, its slot stepping straight through to `FILLED`"

        Design: Corner/entities/enrollment_create_computes_term_and_zero_ledgers
        """
        program = setup_awarded_program()
        member_id = register_cleared_member(program["org_id"])
        enrollment = enroll(program["award_id"], program["org_id"], member_id)
        assert enrollment["term_category"] == "FULL_TIME"
        assert enrollment["term_minutes"] == 102000
        assert enrollment["certified_minutes"] == 0
        assert enrollment["fundraising_certified_minutes"] == 0
        assert enrollment["allowance_paid_cents"] == 0
        assert enrollment["status"] == "ACTIVE"
        assert enrollment["suspension_origin"] == "NONE"
        assert enrollment["exit_reason"] is None
        assert enrollment["exit_overpayment_cents"] is None
        assert enrollment["slot_id"]
        assert award_version(program["award_id"]) == 2, (
            "enrollment creation increments the award's version by 1"
        )

    def test_unknown_member_id_is_member_not_found(self, api, officer_headers):
        """A syntactically valid but unallocated member_id in the body is a 404
        from the body foreign-key existence check; no slot is reserved.

        PRD §3.4: "the referenced member must exist (`ERR_MEMBER_NOT_FOUND`)"
        PRD §2.10: "(5) path-identifier existence, (6) body foreign-key existence"

        Design: Corner/entities/enrollment_unknown_member_returns_member_not_found
        """
        program = setup_awarded_program()
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                NON_EXISTENT_UUID, expected_award_version=award_version(program["award_id"])
            ),
            make_grantee_staff_headers(program["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND)
        slots, meta = validate_paginated(api.list_slots(program["award_id"], officer_headers))
        assert meta["total_count"] == 2
        assert all(s["status"] == "OPEN" for s in slots), "no reservation happened"


class TestEnrollmentSafetyGates:
    def test_member_younger_than_17_rejected_exactly_17_accepted(self, api):
        """date_of_birth 2010-01-01 makes the member 16 at a 2026-10-15 start
        (rejected); date_of_birth 2009-10-15 turns 17 exactly on the start date
        (accepted — the boundary is inclusive).

        PRD §3.4: "the member must be at least 17 years old on the service start date — the `date_of_birth` plus seventeen years must fall on or before `service_start_date` — else `ERR_MEMBER_TOO_YOUNG`"

        Design: Corner/validations/member_younger_than_17_rejected
        """
        program = setup_awarded_program()
        young = register_cleared_member(
            program["org_id"], full_name="Young Teen", date_of_birth="2010-01-01"
        )
        exact = register_cleared_member(
            program["org_id"], full_name="Exact Seventeen", date_of_birth="2009-10-15"
        )
        staff = make_grantee_staff_headers(program["org_id"])
        resp_young = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(young, expected_award_version=award_version(program["award_id"])),
            staff,
        )
        validate_error(resp_young, ApiErrorId.ERR_MEMBER_TOO_YOUNG)
        resp_ok = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(exact, expected_award_version=award_version(program["award_id"])),
            staff,
        )
        enrolled = validate_success(resp_ok, 201)
        assert enrolled["status"] == "ACTIVE"

    def test_enrollment_without_any_check_is_outstanding(self, api):
        """A member with zero criminal history checks cannot be enrolled.

        PRD §3.4: "the member must have at least one criminal history check on file (`ERR_CRIMINAL_CHECK_OUTSTANDING`)"

        Design: Corner/validations/enrollment_without_any_check_returns_outstanding
        """
        program = setup_awarded_program()
        member = register_member()
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member["id"], expected_award_version=award_version(program["award_id"])
            ),
            make_grantee_staff_headers(program["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CRIMINAL_CHECK_OUTSTANDING)

    def test_no_open_slot_of_requested_category(self, api, officer_headers):
        """The single FULL_TIME slot is FILLED and no HALF_TIME slot exists at
        all — the selector's empty candidate set rejects a HALF_TIME request.

        PRD §3.4: "among the award's slots that are `OPEN` and match the requested `term_category`, it picks the one with the lowest `slot_index`"
        PRD §3.4: "an empty candidate set is `ERR_NO_OPEN_SLOT`"

        Design: Corner/validations/no_open_slot_of_requested_category
        """
        program = setup_awarded_program(**FULL_TIME_1_SLOT)
        member_a = register_cleared_member(program["org_id"])
        enroll(program["award_id"], program["org_id"], member_a)
        member_b = register_cleared_member(
            program["org_id"], full_name="Blair Kim", date_of_birth="1999-05-20",
            citizenship_status="US_NATIONAL",
        )
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member_b,
                term_category="HALF_TIME",
                service_start_date="2026-11-01",
                service_end_date="2027-05-01",
                expected_award_version=award_version(program["award_id"]),
            ),
            make_grantee_staff_headers(program["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_SLOT)
        rows, meta = validate_paginated(
            api.list_enrollments(officer_headers, params={"member_id": member_b})
        )
        assert rows == [] and meta["total_count"] == 0


class TestCriminalHistoryCheckIntegrity:
    def test_second_check_while_pending_is_check_in_progress(self, api, officer_headers):
        """A second initiation while the member's latest check is PENDING is
        rejected; after adjudication a fresh check is allowed with check_seq 2.

        PRD §3.4: "Starting a second check while one is still `PENDING` for the same member is rejected with `ERR_CHECK_IN_PROGRESS`."
        PRD §3.4: "Every check for a member receives a `check_seq`, assigned per member as one more than the highest existing sequence number, starting at 1"

        Design: Corner/validations/second_open_check_returns_check_in_progress
        """
        base = setup_org_competition()
        member = register_member()
        first = initiate_check(member["id"], base["org_id"])
        staff = make_grantee_staff_headers(base["org_id"])
        resp = api.create_criminal_check(member["id"], staff)
        validate_error(resp, ApiErrorId.ERR_CHECK_IN_PROGRESS)
        clear_check(first["id"])
        second = validate_success(api.create_criminal_check(member["id"], staff), 201)
        assert second["check_seq"] == 2
        assert second["adjudication"] == "PENDING"

    def test_component_twice_and_post_adjudication_rejected(self, api):
        """Recording an already-recorded component is rejected while PENDING;
        once the third component adjudicates, any further recording hits the
        check-level guard.

        PRD §3.4: "recording a component that already has a result is `ERR_COMPONENT_ALREADY_RECORDED`, and recording anything on a check whose adjudication has already left `PENDING` is `ERR_CHECK_ALREADY_ADJUDICATED`"

        Design: Corner/validations/component_recorded_twice_and_post_adjudication_rejected
        """
        base = setup_org_competition()
        member = register_member()
        check = initiate_check(member["id"], base["org_id"])
        record_component(check["id"], "NSOPR", "CLEAR")
        dup = api.record_component_result(
            check["id"], {"component": "NSOPR", "result": "FLAGGED"}, OFFICER
        )
        validate_error(dup, ApiErrorId.ERR_COMPONENT_ALREADY_RECORDED)
        record_component(check["id"], "STATE_REPOSITORY", "CLEAR")
        record_component(check["id"], "FBI_FINGERPRINT", "CLEAR")
        late = api.record_component_result(
            check["id"], {"component": "NSOPR", "result": "CLEAR"}, OFFICER
        )
        validate_error(late, ApiErrorId.ERR_CHECK_ALREADY_ADJUDICATED)


class TestFlaggedCheckCascade:
    def test_flagged_check_cancels_enrollment_and_reopens_slot(self, api, officer_headers):
        """A PENDING_CHECKS enrollment whose member's check adjudicates FLAGGED
        is CANCELLED and its slot releases back to OPEN without a fill.

        PRD §3.4: "on `FLAGGED`, those enrollments are `CANCELLED` and their slots release back to `OPEN`."
        PRD §3.4: "becomes `FLAGGED` the moment every component has a result and at least one is `FLAGGED`"

        Design: Corner/state_machines/flagged_check_cancels_enrollment_and_reopens_slot
        """
        program = setup_awarded_program()
        member_id, check_id = register_pending_check_member(program["org_id"])
        enrollment = enroll(program["award_id"], program["org_id"], member_id)
        slot_id = enrollment["slot_id"]
        assert enrollment["status"] == "PENDING_CHECKS"
        record_component(check_id, "NSOPR", "FLAGGED")
        record_component(check_id, "STATE_REPOSITORY", "CLEAR")
        final_check = record_component(check_id, "FBI_FINGERPRINT", "CLEAR")
        assert final_check["adjudication"] == "FLAGGED"
        assert final_check["adjudicated_at"].startswith("2026-10-02")
        cancelled = get_enrollment(enrollment["id"])
        assert cancelled["status"] == "CANCELLED"
        slot = validate_success(api.get_slot(slot_id, officer_headers))
        assert slot["status"] == "OPEN" and slot["fill_count"] == 0


class TestStaleAwardVersion:
    def test_stale_expected_award_version_rejected(self, api, officer_headers):
        """The first enrollment create carries the award's current version 1
        and succeeds (version advances to 2); a second create replaying the
        stale version 1 is rejected 412.

        PRD §2.8: "The enrollment-creation request must therefore carry `expected_award_version` equal to the award's current `version`. If the award's version has advanced since the client last read it — so the client's picture of the slot ledger is out of date — the create is rejected with `ERR_STALE_VERSION` (412)."

        Design: Corner/cross-cutting complexity layers/stale_award_version_on_enrollment_create_returns_412
        """
        program = setup_awarded_program()
        member_a = register_cleared_member(program["org_id"])
        member_b = register_cleared_member(
            program["org_id"], full_name="Blair Kim", date_of_birth="1999-05-20",
            citizenship_status="US_NATIONAL",
        )
        staff = make_grantee_staff_headers(program["org_id"])
        assert award_version(program["award_id"]) == 1
        first = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(member_a, expected_award_version=1),
            staff,
        )
        validate_success(first, 201)
        assert award_version(program["award_id"]) == 2
        stale = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(member_b, expected_award_version=1),
            staff,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412
        rows, meta = validate_paginated(
            api.list_enrollments(officer_headers, params={"member_id": member_b})
        )
        assert rows == [] and meta["total_count"] == 0
        slots, _ = validate_paginated(api.list_slots(program["award_id"], officer_headers))
        assert sum(1 for s in slots if s["status"] == "OPEN") == 1, (
            "the second slot stays OPEN after the stale create is rejected"
        )
