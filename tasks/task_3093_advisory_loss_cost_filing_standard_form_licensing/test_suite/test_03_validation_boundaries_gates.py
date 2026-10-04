"""Validation priority conflicts, boundary precision, and cross-entity state
gates (PRD §2.7, §3.3, §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_adoption_payload,
    make_activated_plan,
    make_agreement,
    make_class_plan,
    make_department,
    make_effective_filing,
    make_filed_filing,
    make_insurer,
    make_reviewed_filing,
    make_staged_revision,
    make_adoption,
    set_clock,
    setup_adoption_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    make_insurer_headers,
    make_regulator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


class TestValidationPriorityConflicts:
    """Dual-failure scenarios: the highest-priority check determines the error."""

    def test_objection_on_reviewed_filing_reports_invalid_state_not_window(self, api):
        """PRD §2.7: "Every request passes through an ordered validation
        pipeline, and the order is part of the contract — when several checks
        could fail, the one with the highest priority determines the error
        returned."
        PRD §2.7: "**From-state validity.** The target resource must be in a
        valid from-state for the requested transition; otherwise
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/objection_in_wrong_state_and_out_of_window_reports_state_first
        """
        dept = make_department()
        filing = make_reviewed_filing()  # REVIEWED, never FILED
        set_clock("2027-06-01T00:00:00Z")  # far past any window
        resp = api.raise_objection(
            filing["id"],
            {"department_id": dept["id"], "objection_code": "R-02",
             "objection_text": "Premature objection"},
            make_regulator_headers(dept["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] == ApiErrorId.ERR_INVALID_STATE
        assert err["error_id"] != ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED

    def test_objection_on_reviewed_filing_mutates_nothing(self, api):
        """PRD §3.3: "The first in-window objection moves the filing from
        `FILED` to `OBJECTED` and increments the filing's `version` by 1."
        PRD §2.7: "**From-state validity.** The target resource must be in a
        valid from-state for the requested transition; otherwise
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/objection_in_wrong_state_and_out_of_window_reports_state_first
        """
        dept = make_department()
        filing = make_reviewed_filing()
        set_clock("2027-06-01T00:00:00Z")
        resp = api.raise_objection(
            filing["id"],
            {"department_id": dept["id"], "objection_code": "R-02",
             "objection_text": "Premature objection"},
            make_regulator_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_filing(filing["id"], ADMIN))
        assert after["filing_status"] == "REVIEWED"
        rows, _meta = validate_paginated(api.list_filing_objections(filing["id"], ADMIN))
        assert rows == []

    def test_authorize_with_suspended_insurer_reports_invalid_state_not_license(self, api):
        """PRD §2.7: "**Cross-entity state gates.** A filing is adoptable only
        when `EFFECTIVE`; a class plan revision activates only while its plan
        is `OPEN`; adoption authorization proceeds only while the insurer is
        `ACTIVE`."
        PRD §2.7: "Every request passes through an ordered validation
        pipeline, and the order is part of the contract — when several checks
        could fail, the one with the highest priority determines the error
        returned."

        Design: Difficulty/priority_pair_validation_conflict/adoption_authorize_state_gate_fires_before_license_temporal_check
        """
        scenario = setup_adoption_scenario(
            filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
            agreement_overrides={
                "coverage_start": "2026-01-01T00:00:00Z",
                "coverage_end": "2026-12-31T00:00:00Z",
            },
        )
        ins_id = scenario["insurer"]["id"]
        validate_success(api.suspend_insurer(ins_id, ADMIN))
        set_clock("2028-06-01T00:00:00Z")  # agreement window also lapsed
        resp = api.authorize_adoption(scenario["adoption"]["id"], ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] != ApiErrorId.ERR_LICENSE_NOT_COVERING

    def test_authorize_with_suspended_insurer_leaves_adoption_pending(self, api):
        """PRD §3.4: "A new adoption starts in `PENDING` status."
        PRD §2.7: "**Cross-entity state gates.** A filing is adoptable only
        when `EFFECTIVE`; a class plan revision activates only while its plan
        is `OPEN`; adoption authorization proceeds only while the insurer is
        `ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/adoption_authorize_state_gate_fires_before_license_temporal_check
        """
        scenario = setup_adoption_scenario(
            filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
            agreement_overrides={
                "coverage_start": "2026-01-01T00:00:00Z",
                "coverage_end": "2026-12-31T00:00:00Z",
            },
        )
        validate_success(api.suspend_insurer(scenario["insurer"]["id"], ADMIN))
        set_clock("2028-06-01T00:00:00Z")
        resp = api.authorize_adoption(scenario["adoption"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        adoption = validate_success(api.get_adoption(scenario["adoption"]["id"], ADMIN))
        assert adoption["adoption_status"] == "PENDING"


class TestLcmBandBoundary:
    """Deviation exactly at the ceiling authorizes; one point over band-rejects."""

    def _setup_two_adoptions(self, api):
        insurer = make_insurer()
        make_agreement(insurer["id"], royalty_rate_bps=100)
        filing, _dept = make_effective_filing(
            filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
            department_overrides={"max_lcm_deviation_pct": 25},
        )
        ad_ok = make_adoption(insurer["id"], filing, multiplier_pct=125)
        ad_over = make_adoption(insurer["id"], filing, multiplier_pct=126)
        return insurer, filing, ad_ok, ad_over

    def test_deviation_exactly_at_max_is_authorized(self, api):
        """PRD §3.4: "if the multiplier's excess over 100 (that is,
        `multiplier_pct` minus 100) is no greater than the department's
        `max_lcm_deviation_pct` for the filing's state, the adoption is
        `AUTHORIZED`; if the excess exceeds that ceiling, the adoption is
        `REJECTED_BAND`. At exactly the boundary — deviation equal to the
        ceiling — authorization is granted."

        Design: Difficulty/boundary_precision_check/lcm_deviation_exactly_at_max_is_authorized_not_rejected
        """
        _ins, _filing, ad_ok, _ad_over = self._setup_two_adoptions(api)
        adoption = validate_success(api.authorize_adoption(ad_ok["id"], ADMIN))
        assert adoption["adoption_status"] == "AUTHORIZED"
        assert adoption["authorized_premium_cents"] == 150000

    def test_deviation_one_above_max_lands_rejected_band(self, api):
        """PRD §3.4: "if the excess exceeds that ceiling, the adoption is
        `REJECTED_BAND`."
        PRD §3.4: "Two outcomes are possible, and both are states, not
        errors."

        Design: Difficulty/boundary_precision_check/lcm_deviation_exactly_at_max_is_authorized_not_rejected
        """
        _ins, _filing, ad_ok, ad_over = self._setup_two_adoptions(api)
        validate_success(api.authorize_adoption(ad_ok["id"], ADMIN))
        adoption = validate_success(api.authorize_adoption(ad_over["id"], ADMIN))
        assert adoption["adoption_status"] == "REJECTED_BAND"
        assert adoption.get("authorized_premium_cents") is None


class TestFinalizeZeroObjectionsBoundary:
    """The objection window is inclusive on its last day; once OBJECTED, the
    filing has left FILED and finalize is a from-state failure."""

    def test_objection_on_exact_last_window_day_lands_objected(self, api):
        """PRD §3.3: "the logical clock must be no later than `filed_at` plus
        the department's `objection_window_days`, else
        `ERR_OBJECTION_WINDOW_CLOSED`."
        PRD §3.3: "The first in-window objection moves the filing from `FILED`
        to `OBJECTED` and increments the filing's `version` by 1."

        Design: Difficulty/boundary_precision_check/finalize_requires_exactly_zero_objections_at_window_boundary
        """
        filing, dept = make_filed_filing(
            filing_overrides={"effective_date": "2026-11-01T00:00:00Z"},
        )  # filed_at = 2026-09-01, window 30 days
        set_clock("2026-10-01T00:00:00Z")  # exactly filed_at + 30 days
        resp = api.raise_objection(
            filing["id"],
            {"department_id": dept["id"], "objection_code": "R-30",
             "objection_text": "Last-day objection"},
            make_regulator_headers(dept["id"]),
        )
        validate_success(resp, expected_status=201)
        after = validate_success(api.get_filing(filing["id"], ADMIN))
        assert after["filing_status"] == "OBJECTED"

    def test_finalize_after_objection_is_invalid_state(self, api):
        """PRD §3.3: "finalization requires the filing still `FILED`, the
        logical clock strictly later than `filed_at` plus
        `objection_window_days`, and zero objection rows against the filing."
        PRD §2.7: "**From-state validity.** The target resource must be in a
        valid from-state for the requested transition; otherwise
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/finalize_requires_exactly_zero_objections_at_window_boundary
        """
        filing, dept = make_filed_filing(
            filing_overrides={"effective_date": "2026-11-01T00:00:00Z"},
        )
        set_clock("2026-10-01T00:00:00Z")
        validate_success(
            api.raise_objection(
                filing["id"],
                {"department_id": dept["id"], "objection_code": "R-30",
                 "objection_text": "Last-day objection"},
                make_regulator_headers(dept["id"]),
            ),
            expected_status=201,
        )
        set_clock("2026-10-02T00:00:00Z")
        resp = api.finalize_filing(filing["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, _meta = validate_paginated(api.list_filing_objections(filing["id"], ADMIN))
        assert len(rows) == 1


class TestCrossEntityStateDependency:
    """Cross-entity state gates: adoption creation gated on filing EFFECTIVE;
    revision activation gated on the parent plan OPEN."""

    def test_adoption_against_filed_not_effective_filing_fails_state_gate(self, api):
        """PRD §3.4: "the `filing_id` of an `EFFECTIVE` filing (adoption
        against a filing in any other status fails the cross-entity state gate
        with `ERR_INVALID_STATE`)".
        PRD §2.7: "**Cross-entity state gates.** A filing is adoptable only
        when `EFFECTIVE`; a class plan revision activates only while its plan
        is `OPEN`; adoption authorization proceeds only while the insurer is
        `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/adoption_creation_gated_on_filing_effective
        """
        insurer = make_insurer()
        make_department()
        filing, _dept = make_filed_filing(
            filing_overrides={"effective_date": "2026-11-01T00:00:00Z"},
        )
        resp = api.create_adoption(
            create_adoption_payload(insurer["id"], filing["id"], filing["version"],
                                    multiplier_pct=110),
            make_insurer_headers(insurer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_filing(filing["id"], ADMIN))
        assert after["filing_status"] == "FILED"

    def test_rejected_adoption_create_persists_no_rows(self, api):
        """PRD §3.4: "A new adoption starts in `PENDING` status."
        PRD §3.4: "adoption against a filing in any other status fails the
        cross-entity state gate with `ERR_INVALID_STATE`".

        Design: Difficulty/cross_entity_state_dependency/adoption_creation_gated_on_filing_effective
        """
        insurer = make_insurer()
        make_department()
        filing, _dept = make_filed_filing(
            filing_overrides={"effective_date": "2026-11-01T00:00:00Z"},
        )
        resp = api.create_adoption(
            create_adoption_payload(insurer["id"], filing["id"], filing["version"],
                                    multiplier_pct=110),
            make_insurer_headers(insurer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, meta = validate_paginated(
            api.list_adoptions(ADMIN, params={"insurer_id": insurer["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_revision_activation_on_locked_plan_fails_state_gate(self, api):
        """PRD §3.6: "Activation is permitted once the logical clock has
        reached `activates_at` and only while the parent plan is `OPEN`;
        activating moves the revision's `revision_status` from `STAGED` to
        `ACTIVATED`".
        PRD §3.6: "Activation while the plan is `LOCKED`, or before
        `activates_at`, fails with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/revision_activation_gated_on_class_plan_open
        """
        plan, rev1 = make_activated_plan()
        validate_success(api.lock_class_plan(plan["id"], ADMIN))
        rev2 = make_staged_revision(plan["id"], class_count=14,
                                    activates_at="2026-08-15T00:00:00Z")
        resp = api.activate_revision(rev2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rev2_after = validate_success(api.get_revision(rev2["id"], ADMIN))
        assert rev2_after["revision_status"] == "STAGED"

    def test_locked_plan_keeps_current_revision_unchanged_after_rejected_activation(self, api):
        """PRD §3.6: "activating moves the revision's `revision_status` from
        `STAGED` to `ACTIVATED` and fires three cascades at once: the plan's
        previously `ACTIVATED` revision, if any, moves to `SUPERSEDED`; the
        plan's `current_revision_id` is set to the newly activated revision;
        and the plan's `version` increments by 1 (with `updated_at`
        refreshed)."
        PRD §3.6: "Locking a class plan is terminal and requires the plan
        `OPEN`, a `current_revision_id` that is set, and zero revisions still
        in `STAGED` status; it moves `plan_status` from `OPEN` to `LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/revision_activation_gated_on_class_plan_open
        """
        plan, rev1 = make_activated_plan()
        validate_success(api.lock_class_plan(plan["id"], ADMIN))
        rev2 = make_staged_revision(plan["id"], class_count=14,
                                    activates_at="2026-08-15T00:00:00Z")
        resp = api.activate_revision(rev2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        plan_after = validate_success(api.get_class_plan(plan["id"], ADMIN))
        assert plan_after["plan_status"] == "LOCKED"
        assert plan_after["current_revision_id"] == rev1["id"]
        rev1_after = validate_success(api.get_revision(rev1["id"], ADMIN))
        assert rev1_after["revision_status"] == "ACTIVATED"
