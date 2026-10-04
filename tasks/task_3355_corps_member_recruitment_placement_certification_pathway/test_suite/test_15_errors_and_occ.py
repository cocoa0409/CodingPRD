"""Existence resolution, the OCC guards and the remaining single-trigger errors."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_partner_school_payload,
    create_placement_payload,
    err,
    headers_without_role,
    headers_without_user_id,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers.fixtures import (
    ADMIN,
    CERTIFICATION_OFFICER,
    COMPLETER,
    PLACEMENT_COORDINATOR,
    VERIFIER,
    complete_and_verify_milestone,
    complete_institute,
    create_district,
    create_matched_placement,
    create_region,
    get_district,
    get_member,
    milestones_by_type,
    record_practice_hours,
    setup_exited_member,
    setup_member_scenario,
)


class TestAuthenticationHeaderPresence:
    def test_missing_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the acting capacity."
        PRD §2.10: "The ladder opens with authentication. Every operation except the clock-setting capability requires both headers, and the declared role must be one of the seven recognized names; otherwise the response is `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_when_role_header_absent
        """
        response = api.request_raw(
            "GET", f"/corps/corps-members/{NON_EXISTENT_UUID}", None, headers_without_role()
        )
        validate_error(response, err(ApiErrorId.ERR_UNAUTHENTICATED), 401)

    def test_missing_user_header_is_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or that names a role outside that set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_when_role_header_absent
        """
        response = api.request_raw(
            "GET",
            f"/corps/corps-members/{NON_EXISTENT_UUID}",
            None,
            headers_without_user_id("PlacementCoordinator"),
        )
        validate_error(response, err(ApiErrorId.ERR_UNAUTHENTICATED), 401)


class TestReferenceResolution:
    def test_missing_school_and_missing_member_report_their_own_errors(self, api):
        """PRD §2.11: "a placement payload names both a corps member and a school, and the member is resolved first"
        PRD §2.10: "A PartnerSchool that cannot be resolved is `ERR_SCHOOL_NOT_FOUND` (404), reported on placement creation, on a school read, and on the listing of a school's placements."
        PRD §2.10: "A CorpsMember that cannot be resolved is `ERR_MEMBER_NOT_FOUND` (404), reported on the member read, on leave, return-from-leave and exit, on both institute operations, on placement creation, on milestone creation, on support-record creation, and on all three member sub-collections"

        Design: Corner/errors/error_member_and_school_not_found
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        school_id = scenario["school"]["id"]
        member = get_member(member_id)

        missing_school = api.create_placement(
            create_placement_payload(member_id, NON_EXISTENT_UUID, member["version"]),
            PLACEMENT_COORDINATOR,
        )
        validate_error(missing_school, err(ApiErrorId.ERR_SCHOOL_NOT_FOUND), 404)

        missing_member = api.create_placement(
            create_placement_payload(NON_EXISTENT_UUID, school_id, member["version"]),
            PLACEMENT_COORDINATOR,
        )
        validate_error(missing_member, err(ApiErrorId.ERR_MEMBER_NOT_FOUND), 404)

        rows, meta = validate_paginated(
            api.list_member_placements(member_id, PLACEMENT_COORDINATOR)
        )
        assert rows == [] and meta["total_count"] == 0


class TestFiscalCeiling:
    def test_budget_ceiling_refuses_the_match(self, api):
        """PRD §3.7: "the server projects the district's invoice total as it would stand once this placement is counted among that district's `CONFIRMED` or `ACTIVE` placements, and refuses the match with `ERR_DISTRICT_BUDGET_EXCEEDED` (HTTP 402) when that projected total would exceed the district's `fee_budget_cents`."

        Design: Corner/errors/error_district_budget_exceeded_on_placement_create
        """
        scenario = setup_member_scenario(district_overrides={"fee_budget_cents": 100000})
        member = get_member(scenario["member_id"])
        assert member["service_status"] == "ACTIVE"

        payload = create_placement_payload(
            scenario["member_id"], scenario["school"]["id"], member["version"]
        )
        response = api.create_placement(payload, PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_DISTRICT_BUDGET_EXCEEDED), 402)

        district = get_district(scenario["district"]["id"])
        assert district["committed_placement_count"] == 0


class TestOccGuards:
    def test_stale_member_version_refuses_the_placement(self, api):
        """PRD §2.7: "Creating a Placement through `POST /corps/placements` requires a non-optional `expected_corps_member_version` field carrying the client's last observed `version` of the CorpsMember being placed."
        PRD §2.7: "When that value does not match the CorpsMember's current `version`, the creation is refused with `ERR_STALE_MEMBER_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_member_version_on_placement_create
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        observed = get_member(member_id)["version"]

        record_practice_hours(member_id, 240)
        assert get_member(member_id)["version"] > observed

        payload = create_placement_payload(
            member_id, scenario["school"]["id"], observed
        )
        response = api.create_placement(payload, PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_STALE_MEMBER_VERSION), 412)

        rows, _ = validate_paginated(
            api.list_member_placements(member_id, PLACEMENT_COORDINATOR)
        )
        assert rows == []

    def test_stale_district_version_refuses_the_second_school(self, api):
        """PRD §2.7: "Creating a PartnerSchool through `POST /corps/partner-schools` requires a non-optional `expected_district_version` field carrying the client's last observed `version` of the owning PartnerDistrict; when it does not match the district's current `version`, the creation is refused with `ERR_STALE_DISTRICT_VERSION` (HTTP 412)."
        PRD §3.6: "Because a school is a child of its district, the creation also requires the caller's observed district version in `expected_district_version` and advances the district's `version`"

        Design: Corner/errors/error_stale_district_version_on_school_create
        """
        region = create_region()
        district = create_district(region["id"])
        observed = district["version"]

        first = validate_success(
            api.create_partner_school(
                create_partner_school_payload(district["id"], observed), ADMIN
            ),
            201,
        )
        assert first["district_id"] == district["id"]
        assert get_district(district["id"])["version"] > observed

        stale = api.create_partner_school(
            create_partner_school_payload(
                district["id"], observed, name="Bayou Middle", grade_band="MIDDLE",
                subject_needs=["SCIENCE"],
            ),
            ADMIN,
        )
        validate_error(stale, err(ApiErrorId.ERR_STALE_DISTRICT_VERSION), 412)

        schools, _ = validate_paginated(api.list_district_schools(district["id"], ADMIN))
        assert len(schools) == 1


class TestInstituteIncompleteOnActivate:
    def test_institute_gate_is_triggerable_on_its_own(self, api):
        """PRD §3.7: "two conditions guard it: the member's `institute_status` must be `COMPLETED`, or the request fails with `ERR_INSTITUTE_INCOMPLETE` (HTTP 409), and the member's `readiness_score` must be at least 60.0, or it fails with `ERR_INVALID_STATE` (HTTP 409)."

        The member's readiness is 90.50 here, so the institute is the only
        condition that can fail.

        Design: Corner/errors/error_institute_incomplete_on_activate
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestones = milestones_by_type(member_id)
        complete_and_verify_milestone(milestones["COURSEWORK"]["id"])
        complete_and_verify_milestone(milestones["PRACTICUM"]["id"])

        placement = create_matched_placement(member_id, scenario["school"]["id"])
        confirmed = validate_success(
            api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR)
        )
        assert confirmed["status"] == "CONFIRMED"

        response = api.activate_placement(placement["id"], PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_INSTITUTE_INCOMPLETE), 409)

        complete_institute(member_id)
        activated = validate_success(
            api.activate_placement(placement["id"], PLACEMENT_COORDINATOR)
        )
        assert activated["status"] == "ACTIVE"
        assert activated["employment_eligible"] is True, (
            "180 verified hours meet the pathway floor and no milestone is overdue"
        )


class TestAlreadyTerminalOnExitedMember:
    def test_exited_member_refuses_a_second_exit(self, api):
        """PRD §3.9: "`EXITED` is the service dimension's terminal state, and a member who has exited cannot be put on leave, returned from leave, or exited a second time — those attempts are refused with `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/errors/error_already_terminal_on_exited_member
        """
        scenario = setup_exited_member()
        member_id = scenario["member_id"]
        assert get_member(member_id)["service_status"] == "EXITED"

        response = api.exit_corps_member(member_id, "second exit attempt", PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_ALREADY_TERMINAL), 409)

        # The return-from-leave trigger has no ON_LEAVE from-state either, and
        # the PRD does not commit to which of the two gates answers first.
        back = api.return_member_from_leave(member_id, PLACEMENT_COORDINATOR)
        validate_error_is_one_of(
            back, [err(ApiErrorId.ERR_ALREADY_TERMINAL), err(ApiErrorId.ERR_INVALID_STATE)]
        )

        member = get_member(member_id)
        assert member["service_status"] == "EXITED"
        assert member.get("exit_reason") == "resigned before the term began"
