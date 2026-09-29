"""FULL is reachable by two different edges from PROBATION (PRD §3.8).

Restoration from probation and a vacated probation appeal both land the licence
in FULL, but they leave different ladder state behind, and `probation_cycle_count`
is a lifetime tally that neither of them decrements.
"""

from test_helpers import (
    CODE_RATIO,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_capacity_slots,
    assert_cents,
    assert_point_ledger,
    assert_points,
    fixtures as fx,
    make_inspector_headers,
    supervisor_headers,
    validate_error,
    validate_success,
)

ALL_AGE_GROUPS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]
ROOMS = [
    {"age_group": "INFANT", "requested_group_size": 8},
    {"age_group": "TODDLER", "requested_group_size": 12},
    {"age_group": "PRESCHOOL", "requested_group_size": 20},
    {"age_group": "SCHOOL_AGE", "requested_group_size": 20},
]


def _provisionally_licensed_with_thirty_two_open_points(api, catalog):
    """A provisional licence over 60 slots carrying 32 open ratio points.

    The INITIAL visit cites four SERIOUS RA-201 findings and closes
    CONDITIONAL_PASS, so `critical_open_count` is 0 and the issuing decision is
    allowed while the points stay open.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    inspector = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=ALL_AGE_GROUPS,
        max_daily_visits=3,
    )
    ctx = fx.setup_provider_dossier(
        api,
        legal_name="Aspen Grove Center",
        site_address="6 Aspen Grv",
        program_type="CENTER",
        requested_capacity=60,
        rooms=ROOMS,
        catalog=catalog,
        seed_checklist=False,
    )
    fx.advance_to_checks_cleared(ctx)

    visit = fx.run_visit(
        api,
        ctx.id,
        inspector["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="INITIAL",
        target_age_groups=ALL_AGE_GROUPS,
        age_groups_observed=ALL_AGE_GROUPS,
        duration_minutes=120,
        catalog=catalog,
        citations=[
            {"code": CODE_RATIO, "narrative": "Preschool room A over ratio."},
            {"code": CODE_RATIO, "narrative": "Preschool room B over ratio."},
            {"code": CODE_RATIO, "narrative": "Preschool room C over ratio."},
            {"code": CODE_RATIO, "narrative": "Preschool room D over ratio."},
        ],
        outcome="CONDITIONAL_PASS",
    )
    provider = validate_success(
        api.license_decision(ctx.id, "ISSUE", headers=supervisor_headers())
    )
    return {
        "ctx": ctx,
        "provider": provider,
        "inspector": inspector,
        "inspection": visit["inspection"],
        "violations": visit["violations"],
    }


def _place_on_probation(api, ctx_bundle):
    """Propose, issue and effectuate the probation rung."""
    action = fx.propose_action(
        api,
        ctx_bundle["ctx"].id,
        "PROBATION",
        source_inspection_id=ctx_bundle["inspection"]["id"],
        rationale="Thirty-two open ratio points at initial licensure.",
    )
    fx.issue_action(api, action["id"])
    return action, fx.effectuate_action(api, action["id"])


def _correct_every_finding(api, ctx_bundle):
    for violation in ctx_bundle["violations"]:
        validate_success(
            api.disposition_violation(
                violation["id"],
                "VERIFIED_CORRECTED",
                headers=make_inspector_headers(ctx_bundle["inspector"]["id"]),
            )
        )


class TestLicenseStatusTwoEdgesIntoFull:
    """§3.8: "Restoration from probation is the other supervisor-driven licence
    move and its point test is deliberately looser"."""

    def test_issuance_opens_a_provisional_licence_with_the_points_still_open(
        self, api, catalog
    ):
        """The issuing decision licenses 60 slots and leaves the ladder at 0, while
        the four ratio findings keep 32 points open.

        PRD §3.8: "On success it moves `application_status` to `LICENSED` and
        `license_status` from `NONE` to `PROVISIONAL`; ... sets `licensed_capacity`
        to the sum of those approved group sizes and `suspended_capacity` to 0"

        Design: Difficulty/non_linear_state_machine/non_linear_license_status_two_edges_into_full
        """
        bundle = _provisionally_licensed_with_thirty_two_open_points(api, catalog)
        provider = bundle["provider"]

        assert provider["application_status"] == "LICENSED"
        assert provider["license_status"] == "PROVISIONAL"
        assert_capacity_slots(provider, 60, 0)
        assert provider["current_ladder_step"] == 0
        assert provider["probation_cycle_count"] == 0
        assert_point_ledger(provider, 32, 0, 32)
        assert provider["critical_open_count"] == 0

    def test_probation_effectuation_moves_the_licence_but_holds_no_slots(
        self, api, catalog
    ):
        """The probation rung fines 135850 on 32 basis points, and effectuating it
        raises the ladder to 2 and the cycle count to 1 without touching capacity.

        PRD §3.8: "**Probation** sets `license_status` to `PROBATION`, raises
        `current_ladder_step` to the greater of its current value and 2, and
        increments `probation_cycle_count`."

        Design: Difficulty/non_linear_state_machine/non_linear_license_status_two_edges_into_full
        """
        bundle = _provisionally_licensed_with_thirty_two_open_points(api, catalog)
        proposed, effective = _place_on_probation(api, bundle)

        assert proposed["action_type"] == "PROBATION"
        assert proposed["ladder_step"] == 2
        assert_points(proposed["basis_points"], 32, "basis_points")
        assert_cents(proposed["fine_amount_cents"], 135850)
        assert effective["status"] == "EFFECTIVE"
        assert_cents(effective["fine_amount_cents"], 135850)

        provider = bundle["ctx"].reload()
        assert provider["license_status"] == "PROBATION"
        assert provider["current_ladder_step"] == 2
        assert provider["probation_cycle_count"] == 1
        assert_capacity_slots(provider, 60, 0)

    def test_restoration_demands_the_points_fall_below_fifteen_first(
        self, api, catalog
    ):
        """Thirty-two open points refuse the restoration; four verified corrections
        empty the open balance and the second attempt closes the cycle into FULL.

        PRD §3.8: "`open_violation_points` must be **strictly below** 15 rather
        than zero (`ERR_OUTSTANDING_VIOLATION_POINTS`) ... Success sets
        `license_status` to `FULL`, closing the full-to-probation-to-full cycle,
        resets `current_ladder_step` to 0, and increments the provider's
        `version`."

        Design: Difficulty/non_linear_state_machine/non_linear_license_status_two_edges_into_full
        """
        bundle = _provisionally_licensed_with_thirty_two_open_points(api, catalog)
        _place_on_probation(api, bundle)

        validate_error(
            api.restore_full(bundle["ctx"].id, headers=supervisor_headers()),
            "ERR_OUTSTANDING_VIOLATION_POINTS",
            409,
        )
        still_on_probation = bundle["ctx"].reload()
        assert still_on_probation["license_status"] == "PROBATION"
        assert_point_ledger(still_on_probation, 32, 0, 32)

        _correct_every_finding(api, bundle)
        corrected = bundle["ctx"].reload()
        assert_point_ledger(corrected, 0, 32, 32)
        assert corrected["critical_open_count"] == 0

        restored = validate_success(
            api.restore_full(bundle["ctx"].id, headers=supervisor_headers())
        )
        assert restored["license_status"] == "FULL"
        assert restored["current_ladder_step"] == 0
        assert restored["probation_cycle_count"] == 1, (
            "probation_cycle_count is a lifetime counter and restoration never "
            "decrements it"
        )

    def test_a_vacated_probation_appeal_is_the_other_edge_into_full(
        self, api, catalog
    ):
        """Filing the appeal stays nothing, vacating the probation sets FULL with
        the ladder at 1, and the provisional-only promotion edge is then closed.

        PRD §3.8: "Vacating a **probation** sets `license_status` to `FULL` and
        `current_ladder_step` to 1. `probation_cycle_count` is **not**
        decremented: it is a lifetime counter of how many times the provider has
        ever been placed on probation."

        Design: Difficulty/non_linear_state_machine/non_linear_license_status_two_edges_into_full
        """
        bundle = _provisionally_licensed_with_thirty_two_open_points(api, catalog)
        action, _effective = _place_on_probation(api, bundle)
        _correct_every_finding(api, bundle)
        validate_success(api.restore_full(bundle["ctx"].id, headers=supervisor_headers()))

        appealed = validate_success(
            api.appeal_action(
                action["id"],
                "The ratio findings were corrected before the action took effect.",
                headers=bundle["ctx"].headers,
            )
        )
        assert appealed["status"] == "APPEALED"
        during_appeal = bundle["ctx"].reload()
        assert during_appeal["license_status"] == "FULL", (
            "filing an appeal does not stay the action and changes no licence field"
        )

        vacated = validate_success(
            api.decide_appeal(action["id"], "VACATED", headers=admin_headers())
        )
        assert vacated["status"] == "VACATED"
        assert vacated["resolved_at"] is not None

        after = bundle["ctx"].reload()
        assert after["license_status"] == "FULL"
        assert after["current_ladder_step"] == 1
        assert after["probation_cycle_count"] == 1

        validate_error(
            api.promote_to_full(bundle["ctx"].id, headers=supervisor_headers()),
            "ERR_INVALID_LICENSE_STATE",
            409,
        )
