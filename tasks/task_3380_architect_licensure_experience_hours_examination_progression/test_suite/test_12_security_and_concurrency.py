"""Authentication, role gates, and optimistic concurrency (PRD §2.1, §2.4,
§2.5, §2.6, §3.1, §3.4)."""
from test_helpers import (
    ApiErrorId, LOGICAL_CLOCK_START_DATE, NON_EXISTENT_UUID, TEST_USERS,
    authorize_exams, create_active_supervisor, create_candidate,
    create_jurisdiction, make_candidate_headers, schedule_division,
    validate_error, validate_paginated, validate_success,
)

J1 = "J1"
NCARB = TEST_USERS["ncarb_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string outside the declared role set, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.6: "1. **Authentication.** `X-User-Role` and `X-User-ID` are
        present and the role is one of the five declared roles; otherwise
        `ERR_UNAUTHENTICATED` (HTTP 401)." (authentication precedes the
        existence tier, so even a nonexistent id answers 401)

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        validate_error(
            api.get_candidate(NON_EXISTENT_UUID, {}),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.get_candidate(NON_EXISTENT_UUID, {"X-User-Role": "NcarbAdministrator"}),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.get_candidate(NON_EXISTENT_UUID, {"X-User-ID": "ncarb-1"}),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )


class TestRoleGates:
    def test_candidate_cannot_review_own_evaluation_unauthorized(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in
        the endpoint's authorized-role list and the ownership rules of §2.6
        must hold; either failure is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."
        PRD §3.2: "An `NcarbAdministrator` adjudicates each open evaluation
        through the review action, which takes a `decision` of `SATISFIED` or
        `DEFICIENT`."

        Design: Corner/rbac/candidate_cannot_review_own_evaluation_unauthorized
        """
        create_jurisdiction(code=J1)
        candidate = create_candidate(home_jurisdiction_code=J1)
        ch = make_candidate_headers(candidate["id"])
        evaluation = validate_success(api.create_education_evaluation(
            candidate["id"],
            {"path_type": "ACCREDITED_DEGREE", "institution_name": "State U",
             "semester_credit_hours": 150},
            ch,
        ), expected_status=201)
        # Even the owning candidate is outside the endpoint's role list.
        validate_error(
            api.review_education_evaluation(
                evaluation["id"], {"decision": "SATISFIED"}, ch,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        rows, _m = validate_paginated(
            api.list_education_evaluations(candidate["id"], ch)
        )
        assert len(rows) == 1 and rows[0]["status"] == "SUBMITTED", (
            "rejected review leaves the evaluation untouched"
        )

    def test_candidate_cannot_set_clock_unauthorized(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in
        the endpoint's authorized-role list and the ownership rules of §2.6
        must hold; either failure is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."
        PRD §2.4: "At server startup, before any administrative clock action,
        the logical clock reads exactly 2026-09-01T00:00:00Z."
        PRD §3.4: "From `ELIGIBLE`, the requested date must fall on or after
        the current date (earlier dates are rejected with
        `ERR_SCHEDULE_DATE_PAST`)".

        Design: Corner/rbac/candidate_cannot_set_clock_unauthorized
        """
        create_jurisdiction(code=J1)
        candidate = create_candidate(home_jurisdiction_code=J1)
        ch = make_candidate_headers(candidate["id"])
        validate_error(
            api.set_clock("2030-01-01T00:00:00Z", ch),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # The rejected call must not have moved the clock: a sitting dated
        # exactly at the startup date 2026-09-01 is still schedulable (had
        # the clock jumped to 2030, that date would lie in the past).
        auth = authorize_exams(candidate, jurisdiction_code=J1)
        data = schedule_division(
            candidate, auth["divisions"]["CE"]["id"], LOGICAL_CLOCK_START_DATE,
        )
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_date"] == LOGICAL_CLOCK_START_DATE


class TestOptimisticConcurrency:
    def test_occ_jurisdiction_stale_version(self, api):
        """PRD §2.5: "Updating a jurisdiction's requirement flags requires the
        request to carry `expected_jurisdiction_version` holding the caller's
        last-observed `version` of that jurisdiction; when the value does not
        match the jurisdiction's currently stored `version` — because another
        writer has modified the jurisdiction since the caller last read it —
        the update is rejected with `ERR_STALE_VERSION` (HTTP 412), so the
        stale caller cannot silently discard the intervening change."
        PRD §2.5: "a successful guarded update increments the stored
        `version` by one."

        Design: Corner/cross_cutting_layers/occ_jurisdiction_stale_version
        """
        j1 = create_jurisdiction(code=J1)
        v1 = j1["version"]
        first = validate_success(api.update_jurisdiction(
            j1["id"],
            {"expected_jurisdiction_version": v1,
             "min_total_experience_hours": 3800},
            NCARB,
        ))
        assert first["version"] == v1 + 1, "guarded update increments by one"
        assert first["min_total_experience_hours"] == 3800
        # Replaying the caller's last-observed version is stale now.
        validate_error(
            api.update_jurisdiction(
                j1["id"],
                {"expected_jurisdiction_version": v1,
                 "min_total_experience_hours": 3900},
                NCARB,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        # The current version succeeds; its response proves the stale write
        # never landed (min_total_experience_hours is still 3800).
        third = validate_success(api.update_jurisdiction(
            j1["id"],
            {"expected_jurisdiction_version": first["version"],
             "name": "Renamed Board"},
            NCARB,
        ))
        assert third["version"] == first["version"] + 1
        assert third["name"] == "Renamed Board"
        assert third["min_total_experience_hours"] == 3800

    def test_occ_supervisor_stale_version(self, api):
        """PRD §2.5: "Updating a supervisor's license data works identically
        with `expected_supervisor_version` against the supervisor's stored
        `version`, and a mismatch is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.5: "Both fields are non-optional on their respective endpoints,
        and a successful guarded update increments the stored `version` by
        one."

        Design: Corner/cross_cutting_layers/occ_supervisor_stale_version
        """
        create_jurisdiction(code=J1)
        supervisor = create_active_supervisor(jurisdiction_code=J1)
        v1 = supervisor["version"]
        first = validate_success(api.update_supervisor(
            supervisor["id"],
            {"expected_supervisor_version": v1, "full_name": "Sup One Sr"},
            NCARB,
        ))
        assert first["version"] == v1 + 1
        assert first["full_name"] == "Sup One Sr"
        # Two sequential updates carrying the creation version: the first
        # wins, the second is stale.
        validate_error(
            api.update_supervisor(
                supervisor["id"],
                {"expected_supervisor_version": v1,
                 "license_status": "INACTIVE"},
                NCARB,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        # A no-field guarded read-modify-write at the current version proves
        # the stale update applied nothing.
        current = validate_success(api.update_supervisor(
            supervisor["id"],
            {"expected_supervisor_version": first["version"]},
            NCARB,
        ))
        assert current["full_name"] == "Sup One Sr"
        assert current["license_status"] == "ACTIVE", (
            "stale replay did not flip the license status"
        )
