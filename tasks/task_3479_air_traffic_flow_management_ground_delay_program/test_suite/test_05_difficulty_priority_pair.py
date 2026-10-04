"""Difficulty queue: priority-ordered validation conflicts.

When one request violates two rules, the PRD's numbered evaluation order pins
which single error the server reports.
"""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    at,
    cancel_tmi,
    fill_reroute_bucket,
    get_tmi,
    list_reroute_assignments,
    propose_tmi,
    publish_tmi,
    reroute_assignment_payload,
    setup_active_gdp,
    setup_reroute_scenario,
    tmi_revision_payload,
    validate_error,
)


class TestRerouteStateBeatsSectorSafety:
    def test_cancelled_tmi_reports_terminal_not_sector_capacity(self, api):
        """PRD §2.6: "Otherwise, when several validations could fail on the
        same request, the server evaluates them in the following priority order
        and reports the first failure only:"
        PRD §2.6 item 5: "The target sits in a legal from-state for the
        requested transition: publishing needs a `PROPOSED` TMI, activation
        needs `PUBLISHED` or `REVISING`, substitutions, compression runs, GA
        adjudication and reroute assignment need an `ACTIVE` TMI (otherwise
        `ERR_TMI_NOT_ACTIVE`, HTTP 409), any action on a `CANCELLED` or
        `COMPLETED` TMI yields `ERR_TMI_TERMINAL` (HTTP 409)"
        PRD §2.6 item 7: "The count of existing
        reroute assignments for the same `via_sector_id` and hourly bucket must
        remain below the sector's `base_acceptance_rate`; failure yields
        `ERR_SECTOR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/reroute_state_beats_sector_safety
        """
        world = setup_reroute_scenario(api, sector_base_rate=2)
        sector = world["sector"]
        x3 = world["flights"][2]
        # the 13:00h bucket on the sector is now full (load == rate == 2)
        fill_reroute_bucket(
            api, world["tmi"]["id"], sector["id"], world["flights"], 2
        )

        # a second REROUTE initiative that is published, then cancelled
        r2 = propose_tmi(
            api, world["airport"]["id"], tmi_type="REROUTE",
            program_start=at("13:00"), program_end=at("15:00"),
        )
        publish_tmi(api, r2["id"])
        cancel_tmi(api, r2["id"])

        # one request violating both rules: state (item 5) beats capacity (7)
        resp = api.create_reroute_assignment(
            r2["id"],
            reroute_assignment_payload(
                flight_id=x3["id"], via_sector_id=sector["id"], assigned_route="J64"
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TMI_TERMINAL)

        rows, meta = list_reroute_assignments(api, {"flight_id": x3["id"]})
        assert meta["total_count"] == 0, "no assignment may be created for x3"


class TestRevisionTemporalBeatsFiscal:
    def test_invalid_window_reported_before_capacity_gate(self, api):
        """PRD §2.6: "Otherwise, when several validations could fail on the
        same request, the server evaluates them in the following priority order
        and reports the first failure only:"
        PRD §2.6 item 8: "Every windowed create or
        extend requires start strictly before end; failure yields
        `ERR_INVALID_WINDOW` (HTTP 422)."
        PRD §2.6 item 20: "The `controlled_rate` must not exceed the maximum
        feasible rate for the facility and window, recomputed at gate time, for
        `GROUND_DELAY_PROGRAM` and `AIRSPACE_FLOW_PROGRAM` initiatives;
        `GROUND_STOP` and `REROUTE` are exempt. Failure yields
        `ERR_RATE_EXCEEDS_CAPACITY` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/revision_temporal_beats_fiscal
        """
        world = setup_active_gdp(api, flight_specs=())
        tmi_id = world["tmi"]["id"]
        observed_version = get_tmi(api, tmi_id)["version"]

        # new_program_end 13:00 == program_start violates item 8; rate 60 over
        # max_feasible 30 violates item 20 — the earlier item must be reported
        resp = api.create_tmi_revision(
            tmi_id,
            tmi_revision_payload(
                expected_tmi_version=observed_version,
                new_controlled_rate=60, new_program_end=at("13:00"),
                reason="dual violation",
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

        tmi_after = get_tmi(api, tmi_id)
        assert tmi_after["status"] == "ACTIVE"
        assert tmi_after["revision_count"] == 0, "the rejected revision left no record"
