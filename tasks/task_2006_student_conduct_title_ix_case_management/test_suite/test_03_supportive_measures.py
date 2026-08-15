"""Supportive measures: confidentiality, immediate consistency, count invariant."""
from test_helpers import (
    ApiErrorId,
    assert_supportive_measure,
    begin_jurisdiction_review,
    create_case,
    create_measure,
    get_case,
    make_cast,
    make_coordinator_headers,
    make_party_headers,
    set_clock,
    terminate_measure,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client


def _case_with_two_measures(cast):
    """Case in JURISDICTION_REVIEW with M1 (open-ended) and M2 (expiring)."""
    case = create_case(cast, categories=["STALKING"])
    begin_jurisdiction_review(case["id"], cast["coord"]["id"])
    m1 = create_measure(
        case["id"], cast["coord"]["id"],
        measure_type="COUNSELING", party_side="COMPLAINANT",
        description="Weekly counseling",
    )
    m2 = create_measure(
        case["id"], cast["coord"]["id"],
        measure_type="HOUSING_CHANGE", party_side="COMPLAINANT",
        description="Temporary housing", effective_to="2026-08-05T00:00:00Z",
    )
    return case, m1, m2


class TestMeasureConfidentiality:
    def test_cross_party_supportive_measure_read_rejected(self, api):
        """PRD 2.6: "A `Party` single-read of a measure is limited to measures
        whose `party_side` covers the reader — a complainant reads `COMPLAINANT`
        measures, a respondent reads `RESPONDENT` measures, and a `BOTH` measure
        is visible to both parties. Reading a measure scoped only to the other
        party is rejected with `ERR_SUPPORTIVE_MEASURE_CONFIDENTIAL` (403)."
        PRD 3.2: "party readers see only the measures covering their own side
        plus `BOTH`".

        Design: Corner/validations/cross_party_supportive_measure_read_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        measure = create_measure(
            case["id"], cast["coord"]["id"],
            measure_type="COUNSELING", party_side="COMPLAINANT",
            description="Counseling referral",
        )

        resp = api.get_supportive_measure(
            measure["id"], make_party_headers(cast["resp"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SUPPORTIVE_MEASURE_CONFIDENTIAL)

        resp_list, _ = validate_paginated(
            api.list_supportive_measures(case["id"], make_party_headers(cast["resp"]["id"]))
        )
        assert resp_list == [], "respondent list must exclude COMPLAINANT-scoped measures"
        staff_list, meta = validate_paginated(
            api.list_supportive_measures(
                case["id"], make_coordinator_headers(cast["coord"]["id"])
            )
        )
        assert len(staff_list) == 1 and meta["total_count"] == 1


class TestImmediateConsistency:
    def test_immediate_consistency_mutation_visible_in_response_and_reads(self, api):
        """PRD 2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD 3.2: "Terminating an `ACTIVE` measure early moves it to `TERMINATED`,
        lowers `active_supportive_measure_count` by one, appends
        `MEASURE_TERMINATED`, and increments the case `version`."
        PRD 2.4: "`version` is an integer that starts low and increments by one
        on every mutation of the resource".

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response_and_reads
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        measure = create_measure(
            case["id"], cast["coord"]["id"],
            measure_type="COUNSELING", party_side="COMPLAINANT",
            description="Counseling",
        )
        created_version = measure["version"]

        resp = api.terminate_supportive_measure(measure["id"], coord_h)
        data = validate_success(resp, 200)
        # The mutation is visible in the terminating response itself.
        assert data["status"] == "TERMINATED"
        assert data["version"] == created_version + 1, (
            "version must increment by exactly one on the mutation"
        )

        # The very next reads agree: no lag, no reconciliation delay.
        reread = validate_success(api.get_supportive_measure(measure["id"], coord_h))
        assert reread["status"] == "TERMINATED"
        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["active_supportive_measure_count"] == 0


class TestActiveMeasureCountInvariant:
    def test_supportive_measure_count_balanced_across_mutations(self, api):
        """PRD 3.2: "The count is maintained on every measure mutation, so it
        always equals the number of `ACTIVE` measures on the case."
        PRD 3.2: "Reconciliation (§3.8) expires any `ACTIVE` measure whose
        `effective_to` is set and reached by the clock, moving it to `EXPIRED`
        with the same count decrement and a `MEASURE_EXPIRED` event."

        Design: Difficulty/compensating_invariant/supportive_measure_active_count_conserved
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case, m1, m2 = _case_with_two_measures(cast)

        # create(+1) paired with terminate(-1): net zero.
        m3 = create_measure(
            case["id"], cast["coord"]["id"],
            measure_type="ESCORT", party_side="BOTH",
            description="Campus escort", effective_from="2026-08-02T00:00:00Z",
        )
        terminate_measure(m3["id"], cast["coord"]["id"])

        # Clock reaches M2's effective_to exactly; reconcile expires it (-1).
        set_clock("2026-08-05T00:00:00Z")
        api.reconcile_case(case["id"], TEST_USERS["case_admin_headers"])

        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["active_supportive_measure_count"] == 1, (
            "3 creates balanced by terminate + expiry must leave exactly 1"
        )
        active, _ = validate_paginated(
            api.list_supportive_measures(case["id"], coord_h, params={"status": "ACTIVE"})
        )
        assert len(active) == 1 and active[0]["id"] == m1["id"], (
            "invariant: the counter equals the number of ACTIVE rows"
        )
        # Invariant check against the unfiltered list as well.
        all_rows, _ = validate_paginated(api.list_supportive_measures(case["id"], coord_h))
        assert sum(1 for row in all_rows if row["status"] == "ACTIVE") == 1

    def test_supportive_measure_double_terminate_rejected_and_expiry_boundary(self, api):
        """PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409)".
        PRD 2.8: "When `effective_to` is set, expiry fires as soon as the logical
        clock reaches that instant."

        Design: Difficulty/compensating_invariant/supportive_measure_active_count_conserved
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case, m1, m2 = _case_with_two_measures(cast)

        m3 = create_measure(
            case["id"], cast["coord"]["id"],
            measure_type="ESCORT", party_side="BOTH",
            description="Campus escort", effective_from="2026-08-02T00:00:00Z",
        )
        terminate_measure(m3["id"], cast["coord"]["id"])

        set_clock("2026-08-05T00:00:00Z")
        api.reconcile_case(case["id"], TEST_USERS["case_admin_headers"])

        # M2 expired at exactly its effective_to boundary (inclusive expiry).
        m2_after = validate_success(api.get_supportive_measure(m2["id"], coord_h))
        assert m2_after["status"] == "EXPIRED"
        m3_after = validate_success(api.get_supportive_measure(m3["id"], coord_h))
        assert m3_after["status"] == "TERMINATED"

        # TERMINATED is terminal: a second terminate cannot double-decrement.
        resp = api.terminate_supportive_measure(m3["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["active_supportive_measure_count"] == 1
