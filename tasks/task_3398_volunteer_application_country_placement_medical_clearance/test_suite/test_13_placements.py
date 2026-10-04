"""Site placements: the PROPOSED/REJECTED/CONFIRMED review loop and the two
independent CONFIRM gates (signed agreement, housing standards)."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    api_client,
    assert_inspection_conjunction,
    create_site_placement,
    create_sworn_in_scenario,
    review_site_placement,
    set_clock,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["country_director_headers"]


class TestPlacementReviewLoop:
    def test_placement_review_reject_then_confirm_loop(self):
        """PRD §3.8: "Review is a loop, not a gate: from `PROPOSED` or from
        `REJECTED`, the director records the four flags and a `decision`,
        while reviewing a placement that has reached `CONFIRMED` or `ENDED`
        fails with `ERR_INVALID_STATE`. The service must still be `ACTIVE`
        (`ERR_SERVICE_NOT_ACTIVE`)."
        PRD §3.8: "It is born `PROPOSED`, with `counterpart_agreement_signed`,
        `has_running_water`, `structurally_sound`, and `secure_locks` all
        false and `inspection_passed` — the conjunction of the three housing
        flags — likewise false."

        Design: Corner/state_machines/placement_review_reject_then_confirm_loop
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        placement = create_site_placement(service["id"])
        assert placement["status"] == "PROPOSED"
        assert placement["counterpart_agreement_signed"] is False
        assert placement["has_running_water"] is False
        assert placement["structurally_sound"] is False
        assert placement["secure_locks"] is False
        assert placement["inspection_passed"] is False

        rejected = review_site_placement(
            placement["id"],
            counterpart_agreement_signed=False, has_running_water=False,
            structurally_sound=False, secure_locks=False, decision="REJECT")
        assert rejected["status"] == "REJECTED"
        assert_inspection_conjunction(rejected)

        # The loop: a REJECTED placement can still be confirmed once the
        # agreement is signed and all housing standards pass.
        confirmed = review_site_placement(
            placement["id"],
            counterpart_agreement_signed=True, has_running_water=True,
            structurally_sound=True, secure_locks=True, decision="CONFIRM")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["counterpart_agreement_signed"] is True
        assert confirmed["inspection_passed"] is True
        assert_inspection_conjunction(confirmed)

    def test_placement_confirm_requires_agreement_then_standards(self):
        """PRD §3.8: "A `CONFIRM` decision additionally requires
        `counterpart_agreement_signed` to be true (`ERR_AGREEMENT_NOT_SIGNED`,
        HTTP 422) and all three housing standards — running water, structural
        soundness, and secure locks — to be true
        (`ERR_HOUSING_STANDARDS_NOT_MET`, HTTP 422), and lands the placement
        in `CONFIRMED`; a `REJECT` decision lands it in `REJECTED`, from
        which a later review may still confirm it."

        Design: Corner/state_machines/placement_confirm_requires_agreement_then_standards
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]
        placement = create_site_placement(service["id"])

        # CONFIRM without the signed agreement (housing flags all true).
        validate_error(
            api_client.review_site_placement(
                placement["id"],
                {"counterpart_agreement_signed": False, "has_running_water": True,
                 "structurally_sound": True, "secure_locks": True,
                 "decision": "CONFIRM"},
                DIRECTOR),
            ApiErrorId.ERR_AGREEMENT_NOT_SIGNED, 422)
        # CONFIRM with the agreement signed but one housing standard false.
        validate_error(
            api_client.review_site_placement(
                placement["id"],
                {"counterpart_agreement_signed": True, "has_running_water": False,
                 "structurally_sound": True, "secure_locks": True,
                 "decision": "CONFIRM"},
                DIRECTOR),
            ApiErrorId.ERR_HOUSING_STANDARDS_NOT_MET, 422)

        placements = validate_success(
            api_client.list_site_placements(service["id"], DIRECTOR), 200)
        assert len(placements) == 1
        assert placements[0]["status"] == "PROPOSED", \
            "rejected reviews must not move the placement"
