"""Depth tests: priority pairs in the fixed validation pipeline.

When one request violates two pipeline tiers, the earlier tier's error is the
one reported: state (tier 5) before inspector qualification (tier 6) on
assignment creation, and temporal (tier 7) before cross-entity referential
consistency (tier 9) on noncompliance-record issuance.
"""

from test_helpers import (
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    factories as f,
    fixtures as fx,
    make_inspector_headers,
    validate_error,
    validate_paginated,
)


class TestStateBeatsSafetyOnAssignmentCreate:
    def test_inactive_inspector_reports_state_error_not_qualification(self, api):
        """PRD §3.2: "Assignment creation is the most heavily gated write in the
        system, and the §2.7 pipeline orders the gates: optimistic concurrency
        first, then state, then qualification, then temporal rules."
        PRD §2.7 tier 5: "This tier also carries ... the inspector gate
        `ERR_INSPECTOR_INACTIVE` (HTTP 409) when an inspector-gated operation
        names an inspector whose `employment_status` is not `ACTIVE`."
        PRD §2.7 tier 6: "A deactivated inspector surfaces earlier, at tier 5,
        as `ERR_INSPECTOR_INACTIVE`."
        PRD §3.2: "The named inspector must be `ACTIVE` (a deactivated inspector
        is rejected with `ERR_INSPECTOR_INACTIVE`, HTTP 409) ... a single
        uncovered species class yields `ERR_INSPECTOR_NOT_QUALIFIED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assignment_create
        """
        base = fx.setup_granted_with_window(api, species_classes=["CATTLE"], name="D10 Beef Plant")
        window = base["window"]
        poultry_only = fx.create_inspector(api, full_name="Pat Poultry", species_qualifications=["POULTRY"])
        deactivated = api.deactivate_inspector(poultry_only["id"], PROGRAM_ADMINISTRATOR_HEADERS)
        assert deactivated.status_code == 200, "setup deactivated the inspector"

        # The request violates tier 5 (inspector INACTIVE) AND tier 6 (the
        # POULTRY-only inspector does not cover the CATTLE establishment).
        resp = api.create_assignment(
            window["id"],
            f.assignment_payload(
                poultry_only["id"], 1,
                "2026-09-02T06:00:00Z", "2026-09-02T10:00:00Z",
                window["version"],
            ),
            PROGRAM_ADMINISTRATOR_HEADERS,
        )

        validate_error(resp, ApiErrorId.ERR_INSPECTOR_INACTIVE)
        assert resp.json()["data"]["error_id"] != "ERR_INSPECTOR_NOT_QUALIFIED", (
            "the tier-6 qualification failure is shadowed by the earlier state tier"
        )
        rows, _meta = validate_paginated(api.list_shift_assignments(DISTRICT_MANAGER_HEADERS))
        assert len(rows) == 0, f"no assignment may be created, got {len(rows)}"

    def test_unqualified_inspector_rejected_when_state_tier_passes(self, api):
        """PRD §3.2: "The inspector's `species_qualifications` must cover every
        member of the shift establishment's `species_classes`; a single
        uncovered species class yields `ERR_INSPECTOR_NOT_QUALIFIED` (HTTP
        422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assignment_create
        """
        base = fx.setup_granted_with_window(
            api, species_classes=["CATTLE"], planned_line_count=2
        )
        window = base["window"]
        cattle_inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
        fx.add_assignment(api, window["id"], cattle_inspector["id"], line_index=1)
        poultry_only = fx.create_inspector(api, full_name="Pat Poultry", species_qualifications=["POULTRY"])

        # Window is PLANNED (state tier passes), line 2 is free (no overlap);
        # only the qualification gate can fail.
        resp = api.create_assignment(
            window["id"],
            f.assignment_payload(
                poultry_only["id"], 2,
                "2026-09-02T06:00:00Z", "2026-09-02T10:00:00Z",
                fx.get_shift_window(api, window["id"])["version"],
            ),
            PROGRAM_ADMINISTRATOR_HEADERS,
        )

        validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_QUALIFIED)
        rows, _meta = validate_paginated(api.list_shift_assignments(DISTRICT_MANAGER_HEADERS))
        assert len(rows) == 1


class TestTemporalBeatsReferentialOnNrCreate:
    def _two_granted_establishments_with_window(self, api):
        est_a = fx.create_establishment(api, name="D11 Plant A", species_classes=["CATTLE"])
        base_b = fx.create_granted_establishment(api, species_classes=["SWINE"], name="D11 Plant B")
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE", "SWINE"])
        window_b = fx.create_shift_window(api, base_b["establishment"]["id"])
        return est_a, base_b["establishment"], inspector, window_b

    def test_future_observation_shadows_shift_window_mismatch(self, api):
        """PRD §2.7: "Every request is evaluated against a fixed, ordered
        validation pipeline. When several checks could fail, the earliest
        tier's error is the one reported."
        PRD §2.7: "Observation timestamps at or before the logical clock,
        well-formed half-open intervals inside their shift window, no same-line
        overlapping coverage, and the cross-establishment travel buffer —
        violations surface as `ERR_FUTURE_OBSERVATION` (HTTP 422),
        `ERR_INVALID_REQUEST` (HTTP 400) for malformed intervals,
        `ERR_ASSIGNMENT_OVERLAP` (HTTP 409), or `ERR_TRAVEL_BUFFER_VIOLATION`
        (HTTP 409)."
        PRD §2.7: "A noncompliance record's optional shift link must belong to
        the same establishment, a humane event's species must be one the
        establishment handles, and a pathogen sample's establishment must hold
        a grant — violations surface as `ERR_SHIFT_WINDOW_MISMATCH` (HTTP 422),
        `ERR_SPECIES_NOT_SUPPORTED` (HTTP 422), or
        `ERR_ESTABLISHMENT_NOT_GRANTED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_nr_create
        """
        est_a, _est_b, inspector, window_b = self._two_granted_establishments_with_window(api)

        # observed_at lies after the logical clock (tier 7) AND the linked
        # window belongs to a different establishment (tier 9).
        resp = api.create_noncompliance_record(
            f.nr_payload(
                est_a["id"], inspector["id"],
                regulation_family="SANITATION",
                description="temporal and referential both violated",
                observed_at="2026-09-02T00:00:00Z",
                shift_window_id=window_b["id"],
            ),
            make_inspector_headers(inspector["id"]),
        )

        validate_error(resp, ApiErrorId.ERR_FUTURE_OBSERVATION)
        assert resp.json()["data"]["error_id"] != "ERR_SHIFT_WINDOW_MISMATCH", (
            "the tier-9 referential failure is shadowed by the earlier temporal tier"
        )
        assert fx.list_nrs(api) == [], "no record may be created"

    def test_cross_establishment_window_link_rejected_on_its_own(self, api):
        """PRD §3.3: "When `shift_window_id` is supplied, the referenced window
        must belong to the same establishment as the record; a
        cross-establishment link is rejected with `ERR_SHIFT_WINDOW_MISMATCH`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_nr_create
        """
        est_a, _est_b, inspector, window_b = self._two_granted_establishments_with_window(api)

        # observed_at precedes the boot clock, so only the referential rule fails.
        resp = api.create_noncompliance_record(
            f.nr_payload(
                est_a["id"], inspector["id"],
                regulation_family="SANITATION",
                description="referential violation only",
                observed_at="2026-08-31T06:00:00Z",
                shift_window_id=window_b["id"],
            ),
            make_inspector_headers(inspector["id"]),
        )

        validate_error(resp, ApiErrorId.ERR_SHIFT_WINDOW_MISMATCH)
        assert fx.list_nrs(api) == []
