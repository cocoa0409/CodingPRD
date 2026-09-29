"""Transition-legality corners of the surplus-disposal state machines.

Every test here drives one declared transition and then reads the row back:
an accepted transition must leave the stated status behind, and a refused one
must leave the row exactly as it stood — same status, same version, same
stamped instants. The PRD sentence each test asserts is quoted in full in the
test's own docstring.
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    TEST_DEFAULTS,
    TEST_USERS,
    add_asset,
    create_asset_payload,
    create_bid_payload,
    create_bidder_payload,
    create_condition_assessment_payload,
    create_turn_in_payload,
    create_draft_turn_in,
    file_screening_request,
    get_success_data,
    list_lot_bids,
    make_agency_officer_headers,
    make_bidder_headers,
    open_screening_cycle,
    read_agency,
    read_asset,
    read_bidder,
    read_cycle,
    read_invoice,
    read_lot,
    read_request,
    read_turn_in,
    read_venue,
    register_agency,
    register_state_agency,
    register_venue,
    set_clock,
    setup_assessed_asset,
    setup_assessed_assets,
    setup_closed_met_lot,
    setup_lot_with_active_bid,
    setup_listed_lot,
    setup_open_lot,
    setup_settled_lot,
    submit_turn_in,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["program_admin_headers"]
OFFICER_HEADERS = TEST_USERS["disposal_officer_headers"]
ASSESSOR_HEADERS = TEST_USERS["surplus_assessor_headers"]
FINANCE_HEADERS = TEST_USERS["finance_controller_headers"]

OFFICER_ID = "officer-01"

# A FURNITURE item bought new for 1000000 cents on 2026-01-10 sits inside its
# first year at the epoch clock, so its age factor is 1.00; a C1 / functional
# assessment with no repair estimate leaves fair_market_value_cents at 1000000,
# comfortably above the screening threshold.
SCREENABLE_ASSET = {
    "description": "Modular workstation cluster",
    "acquisition_cost_cents": 1_000_000,
    "acquisition_date": "2026-01-10",
}
SCREENABLE_ASSESSMENT = {
    "condition_code": "C1",
    "functional": True,
    "repair_cost_estimate_cents": 0,
    "assessed_on": "2026-07-31",
}
SCREENABLE_FMV_CENTS = 1_000_000

# The canonical de-minimis pallet: 104500 cents acquired 2024-05-20, assessed C6
# and functional, which values it at 12540 cents.
DE_MINIMIS_FMV_CENTS = TEST_DEFAULTS["FURNITURE_FMV_CENTS"]
DE_MINIMIS_RESERVE_CENTS = TEST_DEFAULTS["FURNITURE_RESERVE_CENTS"]

LOT_OPENS_AT = "2026-08-02T00:00:00Z"
LOT_CLOSES_AT = "2026-08-03T00:00:00Z"


def _instant(value):
    """Parse one of the PRD's ISO 8601 UTC instants for comparison."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


class TestTurnInSubmissionTransitions:
    """DRAFT -> SUBMITTED, the guards on entry and the frozen asset set."""

    def test_submit_moves_draft_to_submitted_and_opens_the_assessment_gate(self, api):
        """PRD: "The turn-in must be in `DRAFT` and must hold at least one asset;
        an empty turn-in is refused with `ERR_TURN_IN_NOT_ASSESSED`. Submission
        moves `status` from `DRAFT` to `SUBMITTED`, stamps `submitted_at` from the
        logical clock and increments the turn-in's `version` by 1. It changes no
        field on any asset, but it is the gate that opens condition assessment:
        assessors work on submitted turn-ins."

        PRD: "Assessment is only admissible while the asset's
        `disposition_status` is `INTAKE` or `ASSESSED`; an asset anywhere else on
        the disposition axis is refused with `ERR_ASSET_NOT_ASSESSABLE`. The
        parent turn-in's state matters too, and it differs between the first
        assessment and later ones: the first assessment on an asset requires the
        turn-in to be in `SUBMITTED`, whereas a re-assessment is admissible while
        the turn-in is in either `SUBMITTED` or `ACCEPTED`, so that a valuation
        can still be corrected after the turn-in has been accepted. An attempt
        outside those turn-in states is refused with `ERR_INVALID_STATE`."

        PRD: "The first assessment on an asset drives `disposition_status` from
        `INTAKE` to `ASSESSED`."

        Design: Corner/state_machines/sm_turn_in_submit_transition_and_side_effects
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        agency_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])
        asset = add_asset(agency["id"], turn_in["id"], **SCREENABLE_ASSET)
        # Adding the asset recomputed the parent's asset_count, which PRD §2.5
        # counts as a mutation of the turn-in row, so read the live version
        # rather than assuming it is still 1.
        version_before_refusal = read_turn_in(turn_in["id"])["version"]

        # The asset sits at INTAKE, so it is assessable on its own axis; the
        # DRAFT parent is the single unmet precondition.
        premature = api.create_condition_assessment(
            asset["id"],
            create_condition_assessment_payload(1, **SCREENABLE_ASSESSMENT),
            ASSESSOR_HEADERS,
        )
        validate_error(premature, ApiErrorId.ERR_INVALID_STATE)

        unchanged = read_turn_in(turn_in["id"])
        assert unchanged["status"] == "DRAFT", (
            "a refused assessment must leave the turn-in in DRAFT, got "
            f"{unchanged['status']}"
        )
        assert unchanged["version"] == version_before_refusal, (
            f"a refused assessment must not bump the turn-in version, got "
            f"{unchanged['version']}"
        )

        submitted = validate_success(api.submit_turn_in(turn_in["id"], agency_headers))
        assert submitted["status"] == "SUBMITTED", (
            f"submission must move the turn-in to SUBMITTED, got {submitted['status']}"
        )
        _assert_instant(submitted["submitted_at"], CLOCK_EPOCH, "submitted_at")
        assert submitted["reviewed_at"] is None, (
            "submission does not review the turn-in, so reviewed_at stays null, got "
            f"{submitted['reviewed_at']}"
        )
        assert submitted["version"] == version_before_refusal + 1, (
            "submission increments the turn-in version by exactly 1, from "
            f"{version_before_refusal}, got {submitted['version']}"
        )

        untouched_asset = read_asset(asset["id"])
        assert untouched_asset["disposition_status"] == "INTAKE", (
            "submission changes no field on any asset, so the child stays at INTAKE, "
            f"got {untouched_asset['disposition_status']}"
        )
        assert untouched_asset["version"] == 1, (
            "submission changes no field on any asset, so the child version stays 1, "
            f"got {untouched_asset['version']}"
        )

        accepted_assessment = api.create_condition_assessment(
            asset["id"],
            create_condition_assessment_payload(1, **SCREENABLE_ASSESSMENT),
            ASSESSOR_HEADERS,
        )
        validate_success(accepted_assessment, 201)

        assessed = read_asset(asset["id"])
        assert assessed["disposition_status"] == "ASSESSED", (
            "the first assessment drives the asset from INTAKE to ASSESSED, got "
            f"{assessed['disposition_status']}"
        )
        assert assessed["fair_market_value_cents"] == SCREENABLE_FMV_CENTS, (
            f"fair_market_value_cents must be {SCREENABLE_FMV_CENTS}, got "
            f"{assessed['fair_market_value_cents']}"
        )

        rolled_up = read_turn_in(turn_in["id"])
        assert rolled_up["appraised_total_cents"] == SCREENABLE_FMV_CENTS, (
            f"appraised_total_cents must roll up to {SCREENABLE_FMV_CENTS}, got "
            f"{rolled_up['appraised_total_cents']}"
        )
        assert rolled_up["status"] == "SUBMITTED", (
            "an assessment does not review the turn-in, got "
            f"{rolled_up['status']}"
        )

    def test_submit_of_an_empty_turn_in_is_refused_and_changes_nothing(self, api):
        """PRD: "The turn-in must be in `DRAFT` and must hold at least one asset;
        an empty turn-in is refused with `ERR_TURN_IN_NOT_ASSESSED`."

        PRD: "Those secondary effects are part of the operation's contract, not
        best-effort housekeeping: an operation either applies all of its hops or,
        if a validation fails, applies none of them."

        Design: Corner/state_machines/sm_turn_in_submit_without_assets_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        agency_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])
        assert turn_in["asset_count"] == 0, (
            f"the turn-in must start empty, got asset_count {turn_in['asset_count']}"
        )

        validate_error(
            api.submit_turn_in(turn_in["id"], agency_headers),
            ApiErrorId.ERR_TURN_IN_NOT_ASSESSED,
        )

        after = read_turn_in(turn_in["id"])
        assert after["status"] == "DRAFT", (
            f"the refused submission must leave the turn-in in DRAFT, got {after['status']}"
        )
        assert after["version"] == 1, (
            f"the refused submission must not bump the version, got {after['version']}"
        )
        assert after["submitted_at"] is None, (
            f"the refused submission must not stamp submitted_at, got {after['submitted_at']}"
        )

        # The very same call succeeds once the turn-in holds one asset.
        add_asset(agency["id"], turn_in["id"], **SCREENABLE_ASSET)
        submitted = validate_success(api.submit_turn_in(turn_in["id"], agency_headers))
        assert submitted["status"] == "SUBMITTED", (
            "a turn-in holding one asset submits successfully, got "
            f"{submitted['status']}"
        )

    def test_accept_of_a_turn_in_with_an_unvalued_asset_is_refused(self, api):
        """PRD: "Acceptance requires that the turn-in be in `SUBMITTED` and that
        **every** child asset has left `INTAKE` — equivalently, that every child
        asset has at least one condition assessment on file and therefore a
        non-null `fair_market_value_cents`. A turn-in with even one unvalued
        asset cannot be accepted and is refused with `ERR_TURN_IN_NOT_ASSESSED`;
        this is a compound guard, in which the parent's transition is conditioned
        on the state of all of its children."

        Design: Corner/state_machines/sm_turn_in_submit_without_assets_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        turn_in = create_draft_turn_in(agency["id"])
        asset = add_asset(agency["id"], turn_in["id"], **SCREENABLE_ASSET)
        version_after_submit = submit_turn_in(agency["id"], turn_in["id"])["version"]

        unvalued = read_asset(asset["id"])
        assert unvalued["fair_market_value_cents"] is None, (
            "the asset must still be unvalued, got "
            f"{unvalued['fair_market_value_cents']}"
        )

        validate_error(
            api.review_turn_in(
                turn_in["id"],
                {"decision": "ACCEPT"},
                OFFICER_HEADERS,
            ),
            ApiErrorId.ERR_TURN_IN_NOT_ASSESSED,
        )

        after = read_turn_in(turn_in["id"])
        assert after["status"] == "SUBMITTED", (
            "the refused acceptance must leave the turn-in in SUBMITTED, got "
            f"{after['status']}"
        )
        assert after["version"] == version_after_submit, (
            "the refused acceptance must not bump the version past the submission's "
            f"{version_after_submit}, got {after['version']}"
        )
        assert after["reviewed_at"] is None, (
            f"the refused acceptance must not stamp reviewed_at, got {after['reviewed_at']}"
        )

    def test_second_submit_is_refused_and_does_not_restamp_submitted_at(self, api):
        """PRD: "The turn-in must be in `DRAFT` and must hold at least one asset;
        an empty turn-in is refused with `ERR_TURN_IN_NOT_ASSESSED`. Submission
        moves `status` from `DRAFT` to `SUBMITTED`, stamps `submitted_at` from the
        logical clock and increments the turn-in's `version` by 1."

        PRD: "It also freezes the asset set — from this point forward adding
        property to the turn-in is refused with `ERR_TURN_IN_NOT_DRAFT`."

        PRD: "Generic state preconditions, including every attempt from a
        terminal state and every repeat of an already-applied trigger:
        `ERR_INVALID_STATE` (409), followed by the specialised state codes
        `ERR_TURN_IN_NOT_DRAFT`, `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`,
        `ERR_BIDDER_NOT_REGISTERED`, `ERR_AGENCY_SUSPENDED`,
        `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."

        Design: Corner/state_machines/sm_turn_in_double_submit_second_attempt_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        agency_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])
        add_asset(agency["id"], turn_in["id"], **SCREENABLE_ASSET)
        submitted = submit_turn_in(agency["id"], turn_in["id"])
        version_after_submit = submitted["version"]

        # Move the clock on so a re-stamped submitted_at would be visible.
        set_clock("2026-08-04T09:30:00Z")

        validate_error(
            api.submit_turn_in(turn_in["id"], agency_headers),
            ApiErrorId.ERR_INVALID_STATE,
        )

        after = read_turn_in(turn_in["id"])
        assert after["status"] == "SUBMITTED", (
            f"the replayed submission must leave SUBMITTED intact, got {after['status']}"
        )
        _assert_instant(after["submitted_at"], CLOCK_EPOCH, "submitted_at")
        assert after["version"] == version_after_submit, (
            f"the replayed submission must not bump the version, got {after['version']}"
        )

        # The frozen asset set answers with the specialised code, not ERR_INVALID_STATE.
        validate_error(
            api.create_asset(
                create_asset_payload(turn_in["id"], description="Late addition"),
                agency_headers,
            ),
            ApiErrorId.ERR_TURN_IN_NOT_DRAFT,
        )

        final = read_turn_in(turn_in["id"])
        assert final["asset_count"] == 1, (
            f"the frozen asset set must still hold exactly 1 asset, got {final['asset_count']}"
        )
        assert final["version"] == version_after_submit, (
            f"the refused asset insert must not bump the turn-in version, got {final['version']}"
        )


class TestTurnInRejectionAndTerminalState:
    """SUBMITTED -> REJECTED, the downward cascade, and the terminal lock."""

    def test_reject_cascades_intake_and_assessed_children_to_retained(self, api):
        """PRD: "Rejection requires the turn-in to be in `SUBMITTED` and a
        `rejection_reason` in the request body. It moves `status` from
        `SUBMITTED` to `REJECTED`, stamps `reviewed_at`, stores the
        `rejection_reason`, and cascades downward: every child asset whose
        `disposition_status` is `INTAKE` or `ASSESSED` moves to `RETAINED`,
        meaning custody returns to the relinquishing agency, and the affected
        assets are processed in `created_at` ascending order. The turn-in's
        `version` increments by 1 and so does the `version` of each asset the
        cascade touched. `REJECTED` is terminal for the turn-in."

        Design: Corner/state_machines/sm_turn_in_reject_cascades_children_to_retained
        """
        scenario = setup_assessed_assets(
            [
                {
                    "kind": "furniture",
                    "overrides": dict(SCREENABLE_ASSET, description="Workstation run A"),
                    "assessment": SCREENABLE_ASSESSMENT,
                },
                {
                    "kind": "furniture",
                    "overrides": dict(SCREENABLE_ASSET, description="Workstation run B"),
                    "assessment": SCREENABLE_ASSESSMENT,
                },
                {
                    "kind": "furniture",
                    "overrides": dict(SCREENABLE_ASSET, description="Workstation run C"),
                    "assessment": None,
                },
            ],
            accept=False,
        )
        turn_in_id = scenario["turn_in"]["id"]
        first, second, third = (a["id"] for a in scenario["assets"])

        before_turn_in = read_turn_in(turn_in_id)
        before_versions = {aid: read_asset(aid)["version"] for aid in (first, second, third)}
        assert read_asset(third)["disposition_status"] == "INTAKE", (
            "the unappraised child must still sit at INTAKE before the rejection"
        )

        rejected = validate_success(
            api.review_turn_in(
                turn_in_id,
                {"decision": "REJECT", "rejection_reason": "Depot has no storage bay free"},
                OFFICER_HEADERS,
            )
        )
        assert rejected["status"] == "REJECTED", (
            f"the rejection must move the turn-in to REJECTED, got {rejected['status']}"
        )
        assert rejected["rejection_reason"] == "Depot has no storage bay free", (
            f"the rejection_reason must be stored verbatim, got {rejected['rejection_reason']}"
        )
        _assert_instant(rejected["reviewed_at"], CLOCK_EPOCH, "reviewed_at")
        assert rejected["version"] == before_turn_in["version"] + 1, (
            "the rejection increments the turn-in version by exactly 1, from "
            f"{before_turn_in['version']} to {rejected['version']}"
        )

        for asset_id, label in ((first, "first"), (second, "second"), (third, "third")):
            child = read_asset(asset_id)
            assert child["disposition_status"] == "RETAINED", (
                f"the {label} child must be swept to RETAINED, got "
                f"{child['disposition_status']}"
            )
            assert child["version"] == before_versions[asset_id] + 1, (
                f"the cascade bumps the {label} child's version by exactly 1, from "
                f"{before_versions[asset_id]} to {child['version']}"
            )

        # The cascade rewrites only the disposition axis: the valuation the
        # assessments produced survives, and the clearance axis is untouched.
        survivor = read_asset(first)
        assert survivor["fair_market_value_cents"] == SCREENABLE_FMV_CENTS, (
            f"fair_market_value_cents must survive the cascade at {SCREENABLE_FMV_CENTS}, "
            f"got {survivor['fair_market_value_cents']}"
        )
        assert survivor["condition_code"] == "C1", (
            f"condition_code must survive the cascade at C1, got {survivor['condition_code']}"
        )
        assert survivor["clearance_status"] == "NOT_REQUIRED", (
            "the clearance axis is untouched by a disposition cascade, got "
            f"{survivor['clearance_status']}"
        )

    def test_rejected_turn_in_refuses_every_further_trigger(self, api):
        """PRD: "The turn-in's `version` increments by 1 and so does the
        `version` of each asset the cascade touched. `REJECTED` is terminal for
        the turn-in."

        PRD: "Generic state preconditions, including every attempt from a
        terminal state and every repeat of an already-applied trigger:
        `ERR_INVALID_STATE` (409), followed by the specialised state codes
        `ERR_TURN_IN_NOT_DRAFT`, `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`,
        `ERR_BIDDER_NOT_REGISTERED`, `ERR_AGENCY_SUSPENDED`,
        `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."

        PRD: "It also freezes the asset set — from this point forward adding
        property to the turn-in is refused with `ERR_TURN_IN_NOT_DRAFT`."

        Design: Corner/state_machines/sm_turn_in_rejected_state_is_terminal_locked
        """
        scenario = setup_assessed_asset(
            asset_overrides=dict(SCREENABLE_ASSET),
            assessment_overrides=SCREENABLE_ASSESSMENT,
            accept=False,
        )
        agency_id = scenario["agency"]["id"]
        agency_headers = make_agency_officer_headers(agency_id)
        turn_in_id = scenario["turn_in"]["id"]
        asset_id = scenario["asset"]["id"]

        validate_success(
            api.review_turn_in(
                turn_in_id,
                {"decision": "REJECT", "rejection_reason": "Not surplus after all"},
                OFFICER_HEADERS,
            )
        )
        locked = read_turn_in(turn_in_id)
        assert locked["status"] == "REJECTED", (
            f"the turn-in must be REJECTED before the terminal probes, got {locked['status']}"
        )
        assert read_asset(asset_id)["disposition_status"] == "RETAINED", (
            "the child must be RETAINED before the terminal probes"
        )
        locked_version = locked["version"]

        validate_error(
            api.submit_turn_in(turn_in_id, agency_headers),
            ApiErrorId.ERR_INVALID_STATE,
        )
        validate_error(
            api.review_turn_in(turn_in_id, {"decision": "ACCEPT"}, OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        validate_error(
            api.create_asset(
                create_asset_payload(turn_in_id, description="Afterthought pallet"),
                agency_headers,
            ),
            ApiErrorId.ERR_TURN_IN_NOT_DRAFT,
        )
        # Both the asset's own axis and the parent's state now bar assessment,
        # so either of the two state codes the PRD names for this call is a
        # faithful answer. The rejection cascade mutated the asset, so the
        # optimistic-concurrency field carries its live version — PRD §2.12 puts
        # ERR_STALE_ASSET_VERSION ahead of the state codes this probe is after.
        validate_error_is_one_of(
            api.create_condition_assessment(
                asset_id,
                create_condition_assessment_payload(
                    read_asset(asset_id)["version"], **SCREENABLE_ASSESSMENT
                ),
                ASSESSOR_HEADERS,
            ),
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ASSET_NOT_ASSESSABLE],
        )

        after = read_turn_in(turn_in_id)
        assert after["status"] == "REJECTED", (
            f"a terminal turn-in must stay REJECTED, got {after['status']}"
        )
        assert after["version"] == locked_version, (
            "none of the four refused triggers may bump the turn-in version, expected "
            f"{locked_version}, got {after['version']}"
        )
        assert after["asset_count"] == 1, (
            f"the refused asset insert must leave asset_count at 1, got {after['asset_count']}"
        )


class TestVenueAndAgencyStatusMachines:
    """The two organisation-level status axes: venue closure and suspension."""

    def test_closed_venue_refuses_a_repeat_close_and_an_unknown_status(self, api):
        """PRD: "A new venue opens with `status` `ACTIVE` and an
        `active_lot_count` of 0. Closing a venue moves its `status` from `ACTIVE`
        to `CLOSED`; lots already in `DRAFT` or `OPEN` there keep their own status
        and continue to run, but no new lot may be created at a closed venue and
        no draft lot at a closed venue may be opened for bidding — both attempts
        are refused with `ERR_VENUE_CLOSED`."

        PRD: "Every enum-typed input carries a value from that enum's declared
        set — otherwise `ERR_INVALID_ENUM_VALUE` (422)."

        PRD: "Generic state preconditions, including every attempt from a
        terminal state and every repeat of an already-applied trigger:
        `ERR_INVALID_STATE` (409), followed by the specialised state codes
        `ERR_TURN_IN_NOT_DRAFT`, `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`,
        `ERR_BIDDER_NOT_REGISTERED`, `ERR_AGENCY_SUSPENDED`,
        `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."

        Design: Corner/state_machines/sm_venue_closed_state_is_terminal_locked
        """
        set_clock(CLOCK_EPOCH)
        venue = register_venue()
        assert venue["status"] == "ACTIVE", (
            f"a new venue must open ACTIVE, got {venue['status']}"
        )
        assert venue["active_lot_count"] == 0, (
            f"a new venue must open with active_lot_count 0, got {venue['active_lot_count']}"
        )
        assert venue["version"] == 1, (
            f"a new venue row starts at version 1, got {venue['version']}"
        )

        closed = validate_success(api.set_venue_status(venue["id"], "CLOSED", ADMIN_HEADERS))
        assert closed["status"] == "CLOSED", (
            f"closing must move the venue to CLOSED, got {closed['status']}"
        )
        assert closed["version"] == 2, (
            f"closing increments the venue version to 2, got {closed['version']}"
        )

        validate_error(
            api.set_venue_status(venue["id"], "CLOSED", ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        # An out-of-enum value is caught ahead of the state check, which the
        # precedence order places later.
        validate_error(
            api.set_venue_status(venue["id"], "MOTHBALLED", ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_ENUM_VALUE,
        )

        after = read_venue(venue["id"])
        assert after["status"] == "CLOSED", (
            f"the two refused calls must leave the venue CLOSED, got {after['status']}"
        )
        assert after["version"] == 2, (
            f"the two refused calls must not bump the venue version, got {after['version']}"
        )

    def test_suspension_is_forward_looking_and_reinstatement_reopens_intake(self, api):
        """PRD: "Participation can be suspended and reinstated, moving `status`
        between `ACTIVE` and `SUSPENDED` and incrementing the organisation's
        `version` each time. Suspension is forward-looking only: turn-ins,
        screening requests and transfer orders already on file are untouched, but
        any attempt to open a new turn-in for a `SUSPENDED` organisation, to file
        a screening request naming it, or to issue a transfer order to it, is
        refused with `ERR_AGENCY_SUSPENDED`. Suspending an already-suspended
        organisation, or reinstating an already-active one, is refused with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sm_agency_suspend_then_reactivate_cycle
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        agency_headers = make_agency_officer_headers(agency["id"])
        assert agency["status"] == "ACTIVE", (
            f"a new organisation must open ACTIVE, got {agency['status']}"
        )
        existing = create_draft_turn_in(agency["id"])

        suspended = validate_success(
            api.set_agency_status(agency["id"], "SUSPENDED", ADMIN_HEADERS)
        )
        assert suspended["status"] == "SUSPENDED", (
            f"suspension must move the organisation to SUSPENDED, got {suspended['status']}"
        )
        assert suspended["version"] == 2, (
            f"suspension increments the organisation version to 2, got {suspended['version']}"
        )

        validate_error(
            api.create_turn_in(
                create_turn_in_payload(agency["id"], custody_location="Austin Yard 5"),
                agency_headers,
            ),
            ApiErrorId.ERR_AGENCY_SUSPENDED,
        )

        # Forward-looking only: the turn-in already on file is untouched.
        untouched = read_turn_in(existing["id"], agency["id"])
        assert untouched["status"] == "DRAFT", (
            f"the pre-existing turn-in must stay DRAFT, got {untouched['status']}"
        )
        assert untouched["version"] == 1, (
            f"the pre-existing turn-in must stay at version 1, got {untouched['version']}"
        )

        validate_error(
            api.set_agency_status(agency["id"], "SUSPENDED", ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        still_suspended = read_agency(agency["id"])
        assert still_suspended["version"] == 2, (
            "the refused repeat suspension must not bump the version, got "
            f"{still_suspended['version']}"
        )

        reinstated = validate_success(
            api.set_agency_status(agency["id"], "ACTIVE", ADMIN_HEADERS)
        )
        assert reinstated["status"] == "ACTIVE", (
            f"reinstatement must move the organisation back to ACTIVE, got "
            f"{reinstated['status']}"
        )
        assert reinstated["version"] == 3, (
            f"reinstatement increments the organisation version to 3, got "
            f"{reinstated['version']}"
        )

        retried = validate_success(
            api.create_turn_in(
                create_turn_in_payload(agency["id"], custody_location="Austin Yard 5"),
                agency_headers,
            ),
            201,
        )
        assert retried["status"] == "DRAFT", (
            f"the retried turn-in must be created in DRAFT, got {retried['status']}"
        )

        _, meta = validate_paginated(
            api.list_turn_ins(ADMIN_HEADERS, params={"turning_in_agency_id": agency["id"]})
        )
        assert meta["total_count"] == 2, (
            "the organisation must own exactly the pre-existing and the retried "
            f"turn-in, got total_count {meta['total_count']}"
        )


class TestAuctionLotLifecycle:
    """Lot, bidder and bid initial states, the window guards on open, and the
    two close outcomes."""

    def test_initial_states_of_a_new_lot_bidder_and_bid(self, api):
        """PRD: "A new lot sits in `status` `DRAFT` with `high_bid_cents` and
        `bid_count` at 0 and `closed_by_user_id` and `closed_at` null."

        PRD: "Every lot gets a human-readable `lot_number` assembled as the
        venue's `venue_code`, a hyphen, and the lot's one-based position among all
        lots at that venue ordered by `created_at` ascending, with the position
        zero-padded to four digits — the third lot ever created at a venue coded
        `NORTHYARD` is therefore `NORTHYARD-0003`."

        PRD: "By default the reserve is derived from the asset's stored
        valuation: take sixty hundredths of `fair_market_value_cents`, round that
        product half up to whole cents, and use the larger of that figure and
        twenty-five dollars."

        PRD: "A reserve below five thousand dollars requires no deposit at all
        and `required_deposit_cents` is 0."

        PRD: "An asset still in `ASSESSED` is listable only under the de-minimis
        exemption: its `fair_market_value_cents` must be strictly below two
        hundred fifty dollars, and its turn-in must have been `ACCEPTED`, in which
        case it moves `ASSESSED` → `LISTED` without ever entering a screening
        cycle."

        PRD: "Registration lands in `status` `PENDING` with
        `end_use_certificate_expires_on` null, a `winning_lot_count` of 0 and all
        four deposit counters — `deposit_paid_cents`, `deposit_held_cents`,
        `deposit_applied_cents` and `deposit_forfeited_cents` — at 0."

        PRD: "An accepted bid is created in `status` `ACTIVE` with `placed_at`
        stamped from the logical clock, and it recomputes two roll-ups on the lot:
        `high_bid_cents` becomes the largest `amount_cents` among the lot's bids
        whose `status` is `ACTIVE` or `WINNING`, and 0 when that set is empty;
        `bid_count` becomes the number of the lot's bids whose `status` is
        `ACTIVE`, `WINNING` or `OUTBID`, which deliberately excludes retracted
        ones."

        Design: Corner/state_machines/sm_initial_states_of_lot_bidder_and_bid
        """
        scenario = setup_listed_lot(
            kind="furniture", opens_at=LOT_OPENS_AT, closes_at=LOT_CLOSES_AT
        )
        lot = scenario["lot"]
        assert lot["status"] == "DRAFT", (
            f"a new lot must sit in DRAFT, got {lot['status']}"
        )
        assert lot["lot_number"] == "AUS-01-0001", (
            f"the first lot at venue AUS-01 must be numbered AUS-01-0001, got "
            f"{lot['lot_number']}"
        )
        assert lot["reserve_price_cents"] == DE_MINIMIS_RESERVE_CENTS, (
            f"the computed reserve must be {DE_MINIMIS_RESERVE_CENTS}, got "
            f"{lot['reserve_price_cents']}"
        )
        assert lot["reserve_source"] == "COMPUTED", (
            f"an officer who supplies no reserve gets reserve_source COMPUTED, got "
            f"{lot['reserve_source']}"
        )
        assert lot["required_deposit_cents"] == 0, (
            "a reserve below five thousand dollars requires no deposit, got "
            f"{lot['required_deposit_cents']}"
        )
        assert lot["high_bid_cents"] == 0, (
            f"a new lot starts with high_bid_cents 0, got {lot['high_bid_cents']}"
        )
        assert lot["bid_count"] == 0, (
            f"a new lot starts with bid_count 0, got {lot['bid_count']}"
        )
        assert lot["closed_at"] is None, (
            f"a new lot has closed_at null, got {lot['closed_at']}"
        )
        assert lot["closed_by_user_id"] is None, (
            f"a new lot has closed_by_user_id null, got {lot['closed_by_user_id']}"
        )
        assert scenario["asset"]["disposition_status"] == "LISTED", (
            "the de-minimis asset moves ASSESSED -> LISTED at lot creation, got "
            f"{scenario['asset']['disposition_status']}"
        )

        bidder = validate_success(
            api.create_bidder(create_bidder_payload(), ADMIN_HEADERS), 201
        )
        assert bidder["status"] == "PENDING", (
            f"registration lands in PENDING, got {bidder['status']}"
        )
        assert bidder["end_use_certificate_expires_on"] is None, (
            "registration leaves end_use_certificate_expires_on null, got "
            f"{bidder['end_use_certificate_expires_on']}"
        )
        assert bidder["winning_lot_count"] == 0, (
            f"registration starts winning_lot_count at 0, got {bidder['winning_lot_count']}"
        )
        for counter in (
            "deposit_paid_cents", "deposit_held_cents",
            "deposit_applied_cents", "deposit_forfeited_cents",
        ):
            assert bidder[counter] == 0, (
                f"registration starts {counter} at 0, got {bidder[counter]}"
            )

        validate_success(api.set_bidder_status(bidder["id"], "REGISTERED", ADMIN_HEADERS))

        set_clock(LOT_OPENS_AT)
        opened = validate_success(api.open_auction_lot(lot["id"], OFFICER_HEADERS))
        assert opened["status"] == "OPEN", (
            f"opening inside the window moves the lot to OPEN, got {opened['status']}"
        )

        bid = validate_success(
            api.place_bid(
                lot["id"],
                create_bid_payload(bidder["id"], 10000),
                make_bidder_headers(bidder["id"]),
            ),
            201,
        )
        assert bid["status"] == "ACTIVE", (
            f"an accepted bid is created ACTIVE, got {bid['status']}"
        )
        _assert_instant(bid["placed_at"], LOT_OPENS_AT, "placed_at")

        after = read_lot(lot["id"])
        assert after["status"] == "OPEN", (
            f"the lot must still be OPEN after the bid, got {after['status']}"
        )
        assert after["high_bid_cents"] == 10000, (
            f"high_bid_cents must roll up to 10000, got {after['high_bid_cents']}"
        )
        assert after["bid_count"] == 1, (
            f"bid_count must roll up to 1, got {after['bid_count']}"
        )

    def test_open_is_refused_before_the_window_and_cannot_be_replayed(self, api):
        """PRD: "Opening a draft lot for bidding moves it `DRAFT` → `OPEN`; it
        requires the venue to still be `ACTIVE`, refusing with `ERR_VENUE_CLOSED`
        otherwise, and it requires the logical clock to lie inside the sale
        window, at or after `opens_at` and strictly before `closes_at`, refusing
        with `ERR_INVALID_STATE` otherwise."

        PRD: "Generic state preconditions, including every attempt from a
        terminal state and every repeat of an already-applied trigger:
        `ERR_INVALID_STATE` (409), followed by the specialised state codes
        `ERR_TURN_IN_NOT_DRAFT`, `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`,
        `ERR_BIDDER_NOT_REGISTERED`, `ERR_AGENCY_SUSPENDED`,
        `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."

        Design: Corner/state_machines/sm_lot_open_outside_window_rejected
        """
        scenario = setup_listed_lot(
            kind="furniture", clock=CLOCK_EPOCH,
            opens_at=LOT_OPENS_AT, closes_at=LOT_CLOSES_AT,
        )
        lot_id = scenario["lot"]["id"]

        # The clock still stands a day before opens_at.
        validate_error(
            api.open_auction_lot(lot_id, OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        before = read_lot(lot_id)
        assert before["status"] == "DRAFT", (
            f"a refused open must leave the lot in DRAFT, got {before['status']}"
        )
        assert before["version"] == 1, (
            f"a refused open must not bump the lot version, got {before['version']}"
        )

        # The lower bound is inclusive, so the exact opens_at instant is admitted.
        set_clock(LOT_OPENS_AT)
        opened = validate_success(api.open_auction_lot(lot_id, OFFICER_HEADERS))
        assert opened["status"] == "OPEN", (
            f"opening at exactly opens_at must succeed, got {opened['status']}"
        )
        assert opened["version"] == 2, (
            f"the open increments the lot version to 2, got {opened['version']}"
        )

        validate_error(
            api.open_auction_lot(lot_id, OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = read_lot(lot_id)
        assert after["status"] == "OPEN", (
            f"the replayed open must leave the lot OPEN, got {after['status']}"
        )
        assert after["version"] == 2, (
            f"the replayed open must not bump the lot version, got {after['version']}"
        )

    def test_close_is_refused_early_and_admitted_at_exactly_closes_at(self, api):
        """PRD: "A `DisposalOfficer` closes an open lot once its window has run.
        Closing requires the lot's `status` to be `OPEN` and the logical clock to
        be at or after `closes_at`; an early close is refused with
        `ERR_INVALID_STATE`."

        PRD: "Hop one stamps `closed_by_user_id` from the officer's `X-User-ID`
        and `closed_at` from the logical clock."

        PRD: "The selected bid moves `ACTIVE` → `WINNING`, every other `ACTIVE`
        bid on the lot moves `ACTIVE` → `OUTBID` processed in `created_at`
        ascending order, and the winning `Bidder`'s `winning_lot_count` is
        incremented by 1."

        PRD: "Hop three, caused by hop two, follows from a bid having become
        `WINNING`: a `SaleInvoice` is created for that bidder in `status`
        `ISSUED`, carrying `auction_lot_id` and `bidder_id`, with
        `hammer_price_cents` equal to the winning bid's `amount_cents`, its money
        lines computed as described below, `amount_paid_cents` and
        `deposit_applied_cents` at 0, `default_reason` and `void_reason` null, and
        `due_at` set to `closed_at` plus a payment term of seven whole days."

        PRD: "Hop four, caused by hop three, follows from an invoice now existing
        for the lot: the lot's asset moves `disposition_status` `LISTED` →
        `SOLD`."

        PRD: "The `buyer_premium_cents` is the `hammer_price_cents` multiplied by
        the venue's `buyer_premium_pct`, rounded half up to whole cents on its
        own."

        PRD: "The `sales_tax_cents` is the sum of `hammer_price_cents` and
        `buyer_premium_cents` multiplied by the venue's `sales_tax_pct`, again
        rounded half up on its own — the tax is charged on the premium-inclusive
        amount, not on the hammer price alone."

        PRD: "Finally, `balance_due_cents` is `total_due_cents` less
        `amount_paid_cents`, so a freshly issued invoice has a balance equal to
        its total."

        Design: Corner/state_machines/sm_lot_close_at_exact_closes_at_boundary
        """
        scenario = setup_lot_with_active_bid(
            bid_amount_cents=10000, kind="furniture",
            opens_at=LOT_OPENS_AT, closes_at=LOT_CLOSES_AT,
        )
        lot_id = scenario["lot"]["id"]
        bidder_id = scenario["bidder"]["id"]

        # The clock stands at opens_at, a day short of closes_at.
        validate_error(
            api.close_auction_lot(lot_id, OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        early = read_lot(lot_id)
        assert early["status"] == "OPEN", (
            f"a refused early close must leave the lot OPEN, got {early['status']}"
        )
        assert early["closed_at"] is None, (
            f"a refused early close must not stamp closed_at, got {early['closed_at']}"
        )
        early_version = early["version"]

        set_clock(LOT_CLOSES_AT)
        closed = validate_success(api.close_auction_lot(lot_id, OFFICER_HEADERS))
        assert closed["status"] == "CLOSED_MET", (
            "a close with the reserve met lands at CLOSED_MET, got "
            f"{closed['status']}"
        )
        _assert_instant(closed["closed_at"], LOT_CLOSES_AT, "closed_at")
        assert closed["closed_by_user_id"] == OFFICER_ID, (
            f"closed_by_user_id must be stamped from the officer's X-User-ID "
            f"{OFFICER_ID}, got {closed['closed_by_user_id']}"
        )
        assert closed["version"] == early_version + 1, (
            "the close increments the lot version by exactly 1, from "
            f"{early_version} to {closed['version']}"
        )

        bids = list_lot_bids(lot_id)
        assert len(bids) == 1, f"the lot must carry exactly one bid, got {len(bids)}"
        assert bids[0]["status"] == "WINNING", (
            f"the selected bid must move ACTIVE -> WINNING, got {bids[0]['status']}"
        )
        assert read_bidder(bidder_id)["winning_lot_count"] == 1, (
            "the winning bidder's winning_lot_count must be incremented to 1"
        )

        invoices, meta = validate_paginated(
            api.list_sale_invoices(FINANCE_HEADERS, params={"auction_lot_id": lot_id})
        )
        assert meta["total_count"] == 1, (
            f"the close must create exactly one invoice, got total_count {meta['total_count']}"
        )
        invoice = invoices[0]
        assert invoice["status"] == "ISSUED", (
            f"the new invoice must be ISSUED, got {invoice['status']}"
        )
        assert invoice["hammer_price_cents"] == 10000, (
            f"hammer_price_cents must equal the winning bid, got "
            f"{invoice['hammer_price_cents']}"
        )
        assert invoice["buyer_premium_cents"] == 1050, (
            f"buyer_premium_cents must be 1050, got {invoice['buyer_premium_cents']}"
        )
        assert invoice["sales_tax_cents"] == 702, (
            f"sales_tax_cents must be 702, got {invoice['sales_tax_cents']}"
        )
        assert invoice["total_due_cents"] == 11752, (
            f"total_due_cents must be 11752, got {invoice['total_due_cents']}"
        )
        assert invoice["amount_paid_cents"] == 0, (
            f"a freshly issued invoice has amount_paid_cents 0, got "
            f"{invoice['amount_paid_cents']}"
        )
        assert invoice["balance_due_cents"] == 11752, (
            f"a freshly issued invoice has a balance equal to its total, got "
            f"{invoice['balance_due_cents']}"
        )
        _assert_instant(invoice["due_at"], "2026-08-10T00:00:00Z", "due_at")

        sold = read_asset(scenario["asset"]["id"])
        assert sold["disposition_status"] == "SOLD", (
            f"the lot's asset must move LISTED -> SOLD, got {sold['disposition_status']}"
        )
        parent = read_turn_in(scenario["turn_in"]["id"])
        assert parent["status"] == "ACCEPTED", (
            "SOLD is not a terminal disposition, so the parent turn-in stays ACCEPTED, "
            f"got {parent['status']}"
        )

    def test_close_with_no_qualifying_bid_returns_the_asset_to_auction_eligible(self, api):
        """PRD: "**When the candidate set is empty** — no bids at all, or every
        bid below reserve — the lot closes at `CLOSED_NO_SALE`.
        `closed_by_user_id` and `closed_at` are still stamped, no invoice is
        created, and the asset moves `disposition_status` `LISTED` →
        `AUCTION_ELIGIBLE` so it can be listed again once the relist cooldown has
        elapsed."

        PRD: "The close also re-derives `high_bid_cents` and `bid_count` on the
        lot and recomputes the venue's `active_lot_count`, and increments both the
        lot's and the asset's `version` by 1."

        Design: Corner/state_machines/sm_lot_close_with_no_bids_returns_asset_to_auction_eligible
        """
        scenario = setup_open_lot(
            kind="furniture", opens_at=LOT_OPENS_AT, closes_at=LOT_CLOSES_AT
        )
        lot_id = scenario["lot"]["id"]

        set_clock(LOT_CLOSES_AT)
        closed = validate_success(api.close_auction_lot(lot_id, OFFICER_HEADERS))
        assert closed["status"] == "CLOSED_NO_SALE", (
            f"an empty candidate set closes the lot at CLOSED_NO_SALE, got "
            f"{closed['status']}"
        )
        _assert_instant(closed["closed_at"], LOT_CLOSES_AT, "closed_at")
        assert closed["closed_by_user_id"] == OFFICER_ID, (
            f"closed_by_user_id is still stamped on a no-sale close, got "
            f"{closed['closed_by_user_id']}"
        )
        assert closed["high_bid_cents"] == 0, (
            f"high_bid_cents must re-derive to 0, got {closed['high_bid_cents']}"
        )
        assert closed["bid_count"] == 0, (
            f"bid_count must re-derive to 0, got {closed['bid_count']}"
        )

        _, meta = validate_paginated(
            api.list_sale_invoices(FINANCE_HEADERS, params={"auction_lot_id": lot_id})
        )
        assert meta["total_count"] == 0, (
            f"a no-sale close creates no invoice, got total_count {meta['total_count']}"
        )

        returned = read_asset(scenario["asset"]["id"])
        assert returned["disposition_status"] == "AUCTION_ELIGIBLE", (
            "the unsold asset must move LISTED -> AUCTION_ELIGIBLE, got "
            f"{returned['disposition_status']}"
        )

        venue = read_venue(scenario["venue"]["id"])
        assert venue["active_lot_count"] == 0, (
            "a closed lot no longer counts toward the venue's active_lot_count, got "
            f"{venue['active_lot_count']}"
        )
        parent = read_turn_in(scenario["turn_in"]["id"])
        assert parent["status"] == "ACCEPTED", (
            "AUCTION_ELIGIBLE is not a terminal disposition, so the parent turn-in "
            f"stays ACCEPTED, got {parent['status']}"
        )


class TestInvoiceSettlementAndDefault:
    """ISSUED -> PARTIALLY_PAID -> PAID, the upward hop to SETTLED, and the
    strict temporal guard on default."""

    def test_partial_payment_then_full_settlement_bubbles_the_lot_to_settled(self, api):
        """PRD: "A payment that leaves a balance moves the invoice `ISSUED` →
        `PARTIALLY_PAID`, or holds it at `PARTIALLY_PAID` on later instalments; a
        payment that brings `amount_paid_cents` exactly up to `total_due_cents`
        moves it to `PAID`, and that settlement in turn moves the lot
        `CLOSED_MET` → `SETTLED`."

        PRD: "The invoice's `amount_paid_cents` therefore always equals the sum of
        every cash `amount_cents` received plus the invoice's own
        `deposit_applied_cents`, and `balance_due_cents` is re-derived as
        `total_due_cents` less `amount_paid_cents`."

        PRD: "`PAID`, `DEFAULTED` and `VOIDED` are all terminal for an invoice."

        Design: Corner/state_machines/sm_invoice_partial_payment_then_settle_bubbles_lot_to_settled
        """
        scenario = setup_closed_met_lot(
            bid_amount_cents=10000, kind="furniture",
            opens_at=LOT_OPENS_AT, closes_at=LOT_CLOSES_AT,
        )
        invoice_id = scenario["invoice"]["id"]
        lot_id = scenario["lot"]["id"]
        assert scenario["invoice"]["total_due_cents"] == 11752, (
            f"the invoice total must be 11752, got {scenario['invoice']['total_due_cents']}"
        )

        first = get_success_data(
            api.pay_sale_invoice(invoice_id, {"amount_cents": 5000}, FINANCE_HEADERS)
        )
        assert first["status"] == "PARTIALLY_PAID", (
            f"a payment leaving a balance moves the invoice to PARTIALLY_PAID, got "
            f"{first['status']}"
        )
        assert first["amount_paid_cents"] == 5000, (
            f"amount_paid_cents must be 5000, got {first['amount_paid_cents']}"
        )
        assert first["balance_due_cents"] == 6752, (
            f"balance_due_cents must be 6752, got {first['balance_due_cents']}"
        )
        mid_lot = read_lot(lot_id)
        assert mid_lot["status"] == "CLOSED_MET", (
            "only full settlement moves the lot, so it stays CLOSED_MET, got "
            f"{mid_lot['status']}"
        )

        second = get_success_data(
            api.pay_sale_invoice(invoice_id, {"amount_cents": 6752}, FINANCE_HEADERS)
        )
        assert second["status"] == "PAID", (
            "a payment bringing amount_paid_cents exactly up to total_due_cents moves "
            f"the invoice to PAID, got {second['status']}"
        )
        assert second["amount_paid_cents"] == 11752, (
            f"amount_paid_cents must be 11752, got {second['amount_paid_cents']}"
        )
        assert second["balance_due_cents"] == 0, (
            f"balance_due_cents must be 0, got {second['balance_due_cents']}"
        )
        settled = read_lot(lot_id)
        assert settled["status"] == "SETTLED", (
            f"settlement moves the lot CLOSED_MET -> SETTLED, got {settled['status']}"
        )

        # PAID is terminal, and the terminal-state check outranks the balance check.
        validate_error(
            api.pay_sale_invoice(invoice_id, {"amount_cents": 1}, FINANCE_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = read_invoice(invoice_id)
        assert after["status"] == "PAID", (
            f"the refused third payment must leave the invoice PAID, got {after['status']}"
        )
        assert after["amount_paid_cents"] == 11752, (
            "the refused third payment must not move amount_paid_cents, got "
            f"{after['amount_paid_cents']}"
        )
        assert after["deposit_applied_cents"] == 0, (
            "no deposit was ever lodged, so deposit_applied_cents stays 0, got "
            f"{after['deposit_applied_cents']}"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "SOLD", (
            "settlement does not release the asset, so it stays SOLD"
        )

    def test_default_is_refused_on_the_due_instant_and_admitted_one_second_later(self, api):
        """PRD: "The invoice must be `ISSUED` or `PARTIALLY_PAID` and the logical
        clock must be strictly after `due_at`; a default declared on the due
        instant itself is premature and refused with `ERR_INVALID_STATE`. The
        invoice moves to `DEFAULTED` with `default_reason` stored and
        `amount_paid_cents` frozen at whatever it had reached. The deposit
        consequence is a forfeiture, not a refund: the invoice's
        `deposit_applied_cents` moves out of the bidder's `deposit_applied_cents`
        and into `deposit_forfeited_cents`, while `deposit_paid_cents` is left
        untouched. The lot deliberately stays at `CLOSED_MET` rather than
        reverting, so that a cash-basis distribution of whatever money was
        actually collected can still be computed."

        Design: Corner/state_machines/sm_invoice_default_requires_clock_strictly_past_due_at
        """
        scenario = setup_closed_met_lot(
            bid_amount_cents=10000, kind="furniture",
            opens_at=LOT_OPENS_AT, closes_at=LOT_CLOSES_AT,
        )
        invoice_id = scenario["invoice"]["id"]
        _assert_instant(scenario["invoice"]["due_at"], "2026-08-10T00:00:00Z", "due_at")

        # A week before the due instant.
        validate_error(
            api.default_sale_invoice(invoice_id, "Buyer unreachable", FINANCE_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        assert read_invoice(invoice_id)["status"] == "ISSUED", (
            "the premature default must leave the invoice ISSUED"
        )

        # On the due instant itself the guard is still unmet.
        set_clock("2026-08-10T00:00:00Z")
        validate_error(
            api.default_sale_invoice(invoice_id, "Buyer unreachable", FINANCE_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        on_instant = read_invoice(invoice_id)
        assert on_instant["status"] == "ISSUED", (
            "a default declared on the due instant is premature, so the invoice stays "
            f"ISSUED, got {on_instant['status']}"
        )
        assert on_instant["default_reason"] is None, (
            f"the premature default must not store a reason, got {on_instant['default_reason']}"
        )
        version_before = on_instant["version"]

        set_clock("2026-08-10T00:00:01Z")
        defaulted = validate_success(
            api.default_sale_invoice(invoice_id, "Buyer unreachable", FINANCE_HEADERS)
        )
        assert defaulted["status"] == "DEFAULTED", (
            f"one second past due_at the default is admitted, got {defaulted['status']}"
        )
        assert defaulted["default_reason"] == "Buyer unreachable", (
            f"default_reason must be stored verbatim, got {defaulted['default_reason']}"
        )
        assert defaulted["amount_paid_cents"] == 0, (
            "amount_paid_cents freezes at whatever it had reached, which is 0, got "
            f"{defaulted['amount_paid_cents']}"
        )
        assert defaulted["balance_due_cents"] == 11752, (
            f"balance_due_cents stays at the full 11752, got {defaulted['balance_due_cents']}"
        )
        assert defaulted["version"] == version_before + 1, (
            "the accepted default increments the invoice version by exactly 1, from "
            f"{version_before} to {defaulted['version']}"
        )

        bidder = read_bidder(scenario["bidder"]["id"])
        assert bidder["deposit_forfeited_cents"] == 0, (
            "no deposit had been applied, so nothing is forfeited, got "
            f"{bidder['deposit_forfeited_cents']}"
        )
        lot = read_lot(scenario["lot"]["id"])
        assert lot["status"] == "CLOSED_MET", (
            f"the lot deliberately stays at CLOSED_MET rather than reverting, got "
            f"{lot['status']}"
        )
        bids = list_lot_bids(scenario["lot"]["id"])
        assert bids[0]["status"] == "WINNING", (
            f"the winning bid is not retracted by a default, got {bids[0]['status']}"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "SOLD", (
            "a default does not un-sell the asset, so it stays SOLD"
        )


class TestScreeningCycleTerminals:
    """OPEN -> AWARDED with its sibling denials, and OPEN -> EXHAUSTED."""

    def test_award_approves_the_named_request_and_denies_every_sibling(self, api):
        """PRD: "Awarding ends the ladder the other way. A `DisposalOfficer` names
        one `screening_request_id` to win. The cycle must be `OPEN`; the named
        request must belong to this very cycle and must be in `status`
        `SUBMITTED`, and a request from another cycle or in any other status is
        refused with `ERR_REQUEST_CYCLE_MISMATCH`; and the requesting organisation
        must still be `ACTIVE`, an award naming a request from a suspended
        organisation being refused with `ERR_AGENCY_SUSPENDED`. The award stamps
        `awarded_by_user_id` from the officer's `X-User-ID` and `awarded_at` from
        the logical clock, and moves the cycle from `OPEN` to `AWARDED`. It also
        resolves every competitor: the named request moves `SUBMITTED` →
        `APPROVED`, and every *other* request on the cycle whose `status` is
        `SUBMITTED` or `INFO_REQUESTED` moves to `DENIED` with `denial_reason` set
        to `LOST_AWARD`, processed in `created_at` ascending order. Crossing into
        the asset, `disposition_status` moves from `SCREENING` to
        `AWARDED_TRANSFER`. The cycle's `version`, each denied request's
        `version`, the approved request's `version` and the asset's `version` all
        increment by 1."

        Design: Corner/state_machines/sm_screening_cycle_award_denies_sibling_requests
        """
        scenario = setup_assessed_asset(
            asset_overrides=dict(SCREENABLE_ASSET),
            assessment_overrides=SCREENABLE_ASSESSMENT,
        )
        asset_id = scenario["asset"]["id"]
        parks = register_agency(
            name="State Parks Commission", agency_code="PARKS-02",
            agency_type="STATE_AGENCY",
        )
        health = register_agency(
            name="State Department of Health", agency_code="HEALTH-03",
            agency_type="STATE_AGENCY",
        )
        library = register_agency(
            name="State Library Archives", agency_code="LIB-04",
            agency_type="STATE_AGENCY",
        )

        cycle = open_screening_cycle(asset_id, opens_at=CLOCK_EPOCH, tier_window_days=5)
        assert cycle["status"] == "OPEN", (
            f"a new screening cycle must open OPEN, got {cycle['status']}"
        )
        first = file_screening_request(cycle["id"], parks["id"])
        second = file_screening_request(cycle["id"], health["id"])
        third = file_screening_request(cycle["id"], library["id"])
        validate_success(
            api.request_screening_info(
                second["id"], "Confirm the storage site is ready", OFFICER_HEADERS
            )
        )
        assert read_request(second["id"])["status"] == "INFO_REQUESTED", (
            "the second request must sit at INFO_REQUESTED before the award"
        )

        awarded = validate_success(
            api.award_screening_cycle(cycle["id"], third["id"], OFFICER_HEADERS)
        )
        assert awarded["status"] == "AWARDED", (
            f"the award moves the cycle OPEN -> AWARDED, got {awarded['status']}"
        )
        assert awarded["awarded_by_user_id"] == OFFICER_ID, (
            f"awarded_by_user_id must be stamped from the officer's X-User-ID "
            f"{OFFICER_ID}, got {awarded['awarded_by_user_id']}"
        )
        _assert_instant(awarded["awarded_at"], CLOCK_EPOCH, "awarded_at")
        assert awarded["open_request_count"] == 0, (
            "every request has been resolved, so open_request_count falls to 0, got "
            f"{awarded['open_request_count']}"
        )
        assert awarded["current_tier"] == "STATE_AGENCY", (
            f"the award does not advance the ladder, got {awarded['current_tier']}"
        )

        winner = read_request(third["id"])
        assert winner["status"] == "APPROVED", (
            f"the named request must move SUBMITTED -> APPROVED, got {winner['status']}"
        )
        assert winner["denial_reason"] is None, (
            f"the approved request carries no denial_reason, got {winner['denial_reason']}"
        )

        loser_one = read_request(first["id"])
        assert loser_one["status"] == "DENIED", (
            f"the SUBMITTED sibling must be DENIED, got {loser_one['status']}"
        )
        assert loser_one["denial_reason"] == "LOST_AWARD", (
            f"the denial_reason must be LOST_AWARD, got {loser_one['denial_reason']}"
        )
        assert loser_one["version"] == 2, (
            "the SUBMITTED sibling is mutated exactly once, by the denial, got version "
            f"{loser_one['version']}"
        )

        loser_two = read_request(second["id"])
        assert loser_two["status"] == "DENIED", (
            f"the INFO_REQUESTED sibling must also be DENIED, got {loser_two['status']}"
        )
        assert loser_two["denial_reason"] == "LOST_AWARD", (
            f"the denial_reason must be LOST_AWARD, got {loser_two['denial_reason']}"
        )
        assert loser_two["version"] == 3, (
            "the INFO_REQUESTED sibling was mutated by the information request and then "
            f"by the denial, got version {loser_two['version']}"
        )

        asset = read_asset(asset_id)
        assert asset["disposition_status"] == "AWARDED_TRANSFER", (
            "the award moves the asset SCREENING -> AWARDED_TRANSFER, got "
            f"{asset['disposition_status']}"
        )

        # AWARDED is not OPEN, so a second award is refused on the cycle's state.
        validate_error(
            api.award_screening_cycle(cycle["id"], first["id"], OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        final = read_cycle(cycle["id"])
        assert final["status"] == "AWARDED", (
            f"the refused second award must leave the cycle AWARDED, got {final['status']}"
        )
        assert final["version"] == awarded["version"], (
            "the refused second award must not bump the cycle version, expected "
            f"{awarded['version']}, got {final['version']}"
        )

    def test_exhausted_cycle_refuses_a_further_advance_and_any_award(self, api):
        """PRD: "Advancing out of `PUBLIC_SALE` is the ladder's exhaustion. The
        cycle moves from `OPEN` to `EXHAUSTED`, `tier_advance_count` increases by
        1, and — crossing into the other entity — the cycle's asset moves
        `disposition_status` from `SCREENING` to `AUCTION_ELIGIBLE`. Both the
        cycle's `version` and the asset's `version` increment by 1. `EXHAUSTED` is
        terminal for the cycle."

        PRD: "An advance is permitted only when the cycle's `open_request_count`
        is zero — nobody in this tier wants the property — or when the logical
        clock has reached or passed `tier_deadline_at`, meaning the window has
        closed regardless of interest."

        PRD: "Generic state preconditions, including every attempt from a
        terminal state and every repeat of an already-applied trigger:
        `ERR_INVALID_STATE` (409), followed by the specialised state codes
        `ERR_TURN_IN_NOT_DRAFT`, `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`,
        `ERR_BIDDER_NOT_REGISTERED`, `ERR_AGENCY_SUSPENDED`,
        `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."

        Design: Corner/state_machines/sm_exhausted_cycle_refuses_award_and_further_advance
        """
        scenario = setup_assessed_asset(
            asset_overrides=dict(SCREENABLE_ASSET),
            assessment_overrides=SCREENABLE_ASSESSMENT,
        )
        asset_id = scenario["asset"]["id"]
        parks = register_agency(
            name="State Parks Commission", agency_code="PARKS-02",
            agency_type="STATE_AGENCY",
        )
        cycle = open_screening_cycle(asset_id, opens_at=CLOCK_EPOCH, tier_window_days=1)
        request = file_screening_request(cycle["id"], parks["id"])

        # One request stays open throughout, so every advance has to wait out the
        # one-day tier window instead of relying on an empty tier.
        for instant in (
            "2026-08-02T00:00:00Z",
            "2026-08-03T00:00:00Z",
            "2026-08-04T00:00:00Z",
            "2026-08-05T00:00:00Z",
        ):
            set_clock(instant)
            validate_success(api.advance_screening_tier(cycle["id"], OFFICER_HEADERS))

        exhausted = read_cycle(cycle["id"])
        assert exhausted["status"] == "EXHAUSTED", (
            f"advancing out of PUBLIC_SALE exhausts the cycle, got {exhausted['status']}"
        )
        assert exhausted["current_tier"] == "PUBLIC_SALE", (
            f"the exhausted cycle rests at PUBLIC_SALE, got {exhausted['current_tier']}"
        )
        assert exhausted["tier_advance_count"] == 4, (
            f"four advances must be counted, got {exhausted['tier_advance_count']}"
        )
        assert read_asset(asset_id)["disposition_status"] == "AUCTION_ELIGIBLE", (
            "exhaustion moves the asset SCREENING -> AUCTION_ELIGIBLE"
        )
        exhausted_version = exhausted["version"]

        validate_error(
            api.advance_screening_tier(cycle["id"], OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        # The named request does belong to this cycle and is still SUBMITTED, so
        # the cycle's own terminal state is the only unmet precondition.
        validate_error(
            api.award_screening_cycle(cycle["id"], request["id"], OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )

        after = read_cycle(cycle["id"])
        assert after["status"] == "EXHAUSTED", (
            f"a terminal cycle must stay EXHAUSTED, got {after['status']}"
        )
        assert after["tier_advance_count"] == 4, (
            f"the refused advance must not increase tier_advance_count, got "
            f"{after['tier_advance_count']}"
        )
        assert after["version"] == exhausted_version, (
            "neither refusal may bump the cycle version, expected "
            f"{exhausted_version}, got {after['version']}"
        )
        surviving = read_request(request["id"])
        assert surviving["status"] == "SUBMITTED", (
            f"the refused award must leave the request SUBMITTED, got {surviving['status']}"
        )
        assert surviving["denial_reason"] is None, (
            f"the refused award must not deny the request, got {surviving['denial_reason']}"
        )


class TestReleaseUpwardClosure:
    """SOLD -> RELEASED and the turn-in's server-initiated ACCEPTED -> CLOSED."""

    def test_release_of_the_last_asset_closes_the_parent_turn_in(self, api):
        """PRD: "Two source states admit release, each with its own downstream
        precondition: an asset at `SOLD` requires the `SaleInvoice` of its lot to
        be `PAID`, and an asset at `AWARDED_TRANSFER` requires its `TransferOrder`
        to be `ACKNOWLEDGED`."

        PRD: "A successful release stores `released_at` from the logical clock
        along with the supplied `odometer_disclosure_reading`,
        `lien_release_reference` and `title_recipient_name`, and moves the asset to
        `RELEASED`."

        PRD: "A final hop bubbles upward exactly as destruction does: when every
        asset of the parent turn-in has reached a terminal disposition, the
        turn-in moves `ACCEPTED` → `CLOSED`."

        PRD: "Whenever an operation leaves every one of an `ACCEPTED` turn-in's
        assets in a terminal `disposition_status` — that is, every asset is
        `RELEASED`, `RETAINED` or `DESTROYED` — the turn-in moves from `ACCEPTED`
        to `CLOSED` on the server's own initiative, its `appraised_total_cents`
        freezes at its then-current value, and its `version` increments by 1."

        PRD: "Any other disposition state, an unpaid invoice or an unacknowledged
        order is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sm_asset_release_bubbles_turn_in_to_closed
        """
        scenario = setup_settled_lot(
            bid_amount_cents=10000, kind="furniture",
            opens_at=LOT_OPENS_AT, closes_at=LOT_CLOSES_AT,
        )
        asset_id = scenario["asset"]["id"]
        turn_in_id = scenario["turn_in"]["id"]
        assert scenario["invoice"]["status"] == "PAID", (
            f"the invoice must be PAID before release, got {scenario['invoice']['status']}"
        )
        assert scenario["asset"]["disposition_status"] == "SOLD", (
            f"the asset must be SOLD before release, got "
            f"{scenario['asset']['disposition_status']}"
        )
        assert read_turn_in(turn_in_id)["status"] == "ACCEPTED", (
            "the parent turn-in must still be ACCEPTED before release"
        )

        released = validate_success(api.release_asset(asset_id, {}, OFFICER_HEADERS))
        assert released["disposition_status"] == "RELEASED", (
            f"a successful release moves the asset to RELEASED, got "
            f"{released['disposition_status']}"
        )
        _assert_instant(released["released_at"], LOT_CLOSES_AT, "released_at")
        for field in (
            "odometer_disclosure_reading", "lien_release_reference",
            "title_recipient_name",
        ):
            assert released[field] is None, (
                f"nothing was supplied for {field}, so it stays null, got {released[field]}"
            )
        assert released["clearance_status"] == "NOT_REQUIRED", (
            "the release gate stood open from birth, so the clearance axis is still "
            f"NOT_REQUIRED, got {released['clearance_status']}"
        )

        closed = read_turn_in(turn_in_id)
        assert closed["status"] == "CLOSED", (
            "the turn-in's only asset has reached a terminal disposition, so the "
            f"turn-in moves ACCEPTED -> CLOSED, got {closed['status']}"
        )
        assert closed["appraised_total_cents"] == DE_MINIMIS_FMV_CENTS, (
            f"appraised_total_cents freezes at {DE_MINIMIS_FMV_CENTS}, got "
            f"{closed['appraised_total_cents']}"
        )

        # Neither the lot nor the invoice is disturbed by the release.
        assert read_lot(scenario["lot"]["id"])["status"] == "SETTLED", (
            "the lot stays SETTLED after the release"
        )
        assert read_invoice(scenario["invoice"]["id"])["status"] == "PAID", (
            "the invoice stays PAID after the release"
        )

        validate_error(
            api.release_asset(asset_id, {}, OFFICER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )
        final = read_asset(asset_id)
        assert final["disposition_status"] == "RELEASED", (
            f"the refused second release must leave the asset RELEASED, got "
            f"{final['disposition_status']}"
        )
        assert final["version"] == released["version"], (
            "the refused second release must not bump the asset version, expected "
            f"{released['version']}, got {final['version']}"
        )
