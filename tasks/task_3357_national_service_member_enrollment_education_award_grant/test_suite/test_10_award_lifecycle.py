"""Award lifecycle: suspension ledger, close gates, match report accumulation,
and org debarment (PRD §2.1, §3.1, §3.3)."""
from test_helpers import (
    ApiErrorId,
    award_version,
    certify_minutes,
    create_enrollment_payload,
    enroll,
    exit_member,
    make_grantee_staff_headers,
    match_line,
    register_cleared_member,
    setup_active_enrollment,
    setup_awarded_program,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAwardCloseGates:
    def test_close_blocked_by_open_enrollments(self, api, officer_headers):
        """Closing with a still-ACTIVE enrollment is rejected and the award
        stays ACTIVE.

        PRD §3.3: "Closing an `ACTIVE` award is the final act, and it is gated twice: no enrollment of the award may remain in `PENDING_CHECKS`, `ACTIVE`, or `SUSPENDED` (else `ERR_ENROLLMENTS_OPEN`)"

        Design: Corner/validations/award_close_blocked_by_open_enrollments
        """
        scenario = setup_active_enrollment()
        resp = api.close_award(scenario["award_id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENTS_OPEN)
        award = validate_success(api.get_award(scenario["award_id"], officer_headers))
        assert award["status"] == "ACTIVE"

    def test_close_blocked_by_match_shortfall(self, api, officer_headers):
        """All enrollments terminal but the accumulated match (900000) is below
        24% of the 4000000 federal share (needs 960000): the aggregate gate
        rejects the close.

        PRD §3.3: "the accumulated match must clear the same 24% floor as at submit time — `allowable_match_cents` multiplied by 25 must be at least `federal_share_awarded_cents` multiplied by 6, equality allowed, else `ERR_MATCH_BELOW_MINIMUM`"

        Design: Corner/validations/award_close_blocked_by_match_shortfall
        """
        scenario = setup_active_enrollment(minutes_chunks=[15300])
        exit_member(scenario["enrollment_id"], scenario["org_id"], "COMPELLING_CIRCUMSTANCE")
        staff = make_grantee_staff_headers(scenario["org_id"])
        validate_success(
            api.create_match_report(
                scenario["award_id"],
                {"reporting_period_label": "P1", "lines": [match_line("CASH", 900000)]},
                staff,
            ),
            201,
        )
        resp = api.close_award(scenario["award_id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_MATCH_BELOW_MINIMUM)
        award = validate_success(api.get_award(scenario["award_id"], officer_headers))
        assert award["status"] == "ACTIVE"
        assert award["allowable_match_cents"] == 900000


class TestMatchReports:
    def test_match_report_on_closed_award_rejected(self, api, officer_headers):
        """A clean close (all enrollments terminal, match floor met) retires
        the OPEN slots; a match report against the now-CLOSED award is
        rejected with the award-posture error and accumulates nothing.
        (Re-derived: PRD §3.3 rejects reports against any non-ACTIVE award
        with ERR_AWARD_SUSPENDED — the design index's ERR_INVALID_STATE is
        corrected to the PRD-stated error id.)

        PRD §3.3: "Reporting against a non-`ACTIVE` award is rejected with `ERR_AWARD_SUSPENDED`."
        PRD §3.3: "Closing retires every still-`OPEN` slot of the award (`OPEN` → `RETIRED`)."

        Design: Corner/state_machines/match_report_on_closed_award_returns_invalid_state
        """
        scenario = setup_active_enrollment(minutes_chunks=[15300])
        exit_member(scenario["enrollment_id"], scenario["org_id"], "COMPELLING_CIRCUMSTANCE")
        staff = make_grantee_staff_headers(scenario["org_id"])
        validate_success(
            api.create_match_report(
                scenario["award_id"],
                {"reporting_period_label": "P1", "lines": [match_line("CASH", 960000)]},
                staff,
            ),
            201,
        )
        closed = validate_success(api.close_award(scenario["award_id"], officer_headers))
        assert closed["status"] == "CLOSED", (
            "960000 x 25 == 24000000 >= 4000000 x 6 == 24000000 (equality allowed)"
        )
        slots, _ = validate_paginated(api.list_slots(scenario["award_id"], officer_headers))
        assert all(s["status"] == "RETIRED" for s in slots), "close retires OPEN slots"
        resp = api.create_match_report(
            scenario["award_id"],
            {"reporting_period_label": "P2", "lines": [match_line("CASH", 1000)]},
            staff,
        )
        validate_error(resp, ApiErrorId.ERR_AWARD_SUSPENDED)
        award = validate_success(api.get_award(scenario["award_id"], officer_headers))
        assert award["allowable_match_cents"] == 960000

    def test_match_reports_accumulate_per_line_rounded_amounts(self, api, officer_headers):
        """CASH 500001 accumulates at full value (500001), then IN_KIND 100001
        rounds per line to 80001 and accumulates to 580002; each accepted
        report bumps the award version by exactly 1.

        PRD §3.3: "each report adds its per-line-rounded sum to the award's `allowable_match_cents`. Reporting against a non-`ACTIVE` award is rejected with `ERR_AWARD_SUSPENDED`. Every accepted report also increments the award's `version`"
        PRD §2.6: "For match commitments and match reports, each line is rounded half up to integer cents first, and the line values are summed afterward"

        Design: Corner/endpoints/match_reports_accumulate_per_line_rounded_amounts
        """
        program = setup_awarded_program()
        staff = make_grantee_staff_headers(program["org_id"])
        validate_success(
            api.create_match_report(
                program["award_id"],
                {"reporting_period_label": "P1", "lines": [match_line("CASH", 500001)]},
                staff,
            ),
            201,
        )
        award = validate_success(api.get_award(program["award_id"], officer_headers))
        assert award["allowable_match_cents"] == 500001
        assert award["version"] == 2
        validate_success(
            api.create_match_report(
                program["award_id"],
                {"reporting_period_label": "P2", "lines": [match_line("IN_KIND", 100001)]},
                staff,
            ),
            201,
        )
        award = validate_success(api.get_award(program["award_id"], officer_headers))
        assert award["allowable_match_cents"] == 580002, (
            "500001 + round_half_up(100001 x 0.8) == 500001 + 80001"
        )
        assert award["version"] == 3


class TestOrgDebarment:
    def test_debarred_org_staff_lose_write_access_but_keep_reads(self, api, officer_headers):
        """After debarment the org's enrollment create is rejected at the
        debarment tier, while its read of the same award still succeeds.

        PRD §2.1: "Debarment cuts access off at the organization level. Once a GranteeOrganization is `DEBARRED`, every org-scoped write attempted by its `GranteeStaff` is rejected with `ERR_ORG_DEBARRED`."
        PRD §3.1: "the transition is terminal, and from that moment its staff lose write access"

        Design: Corner/validations/debarred_org_staff_lose_write_access
        """
        program = setup_awarded_program()
        member_id = register_cleared_member(program["org_id"])
        validate_success(api.debar_organization(program["org_id"], officer_headers))
        staff = make_grantee_staff_headers(program["org_id"])
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member_id, expected_award_version=award_version(program["award_id"])
            ),
            staff,
        )
        validate_error(resp, ApiErrorId.ERR_ORG_DEBARRED)
        assert resp.status_code == 403
        read = api.get_award(program["award_id"], staff)
        validate_success(read, 200)
