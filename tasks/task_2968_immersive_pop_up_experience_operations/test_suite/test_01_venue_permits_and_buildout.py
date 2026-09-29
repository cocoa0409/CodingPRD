"""Registering a venue, walking the permit conversation and drawing buildout money."""

import pytest

from test_helpers import (
    ApiErrorId,
    THRESHOLDS,
    UNKNOWN_UUID,
    api_client,
    assert_buildout_conserved,
    assert_total_count,
    assert_venue,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_object,
    validate_paginated,
    validate_success,
)

VOM = fx.VOM
OFFICER = fx.OFFICER


class TestPermitConversation:
    """The permit loop, its three-way decision and its round cap."""

    def test_conditions_arm_loops_back_to_review_and_stops_at_the_third_round(self):
        """A conditioned package may be refiled twice more and refused the fourth time.

        PRD: "A venue in `PERMIT_CONDITIONS` may be filed again, returning it to
        `PERMIT_UNDER_REVIEW` with the round counter incremented and the
        conditions note cleared".
        PRD: "refused with `ERR_PERMIT_ROUND_CAP` once `permit_submission_round`
        has already reached three".

        Design: Difficulty/non_linear_state_machine/venue_permit_conditions_cycle_and_three_way_decision_branch
        """
        venue = fx.create_venue()
        for expected_round in (1, 2, 3):
            filed = validate_success(
                api_client.submit_permit_package(
                    venue["id"], f.permit_submission_payload(), VOM
                )
            )
            assert filed["status"] == "PERMIT_UNDER_REVIEW"
            assert filed["permit_submission_round"] == expected_round
            assert filed["permit_conditions_note"] is None
            conditioned = validate_success(
                api_client.decide_permit(
                    venue["id"],
                    f.permit_decision_payload(
                        "CONDITIONS", "queue barrier detail incomplete"
                    ),
                    OFFICER,
                )
            )
            assert conditioned["status"] == "PERMIT_CONDITIONS"
            assert conditioned["permit_conditions_note"] == (
                "queue barrier detail incomplete"
            )
            assert conditioned["permitted_occupancy_load"] == 0

        before = fx.read_venue(venue["id"])
        assert before["permit_submission_round"] == THRESHOLDS["PERMIT_ROUND_CAP"]
        validate_error(
            api_client.submit_permit_package(
                venue["id"], f.permit_submission_payload(), VOM
            ),
            ApiErrorId.ERR_PERMIT_ROUND_CAP.value,
        )
        after = fx.read_venue(venue["id"])
        assert after["permit_submission_round"] == 3
        assert after["status"] == "PERMIT_CONDITIONS"
        assert after["version"] == before["version"]
        assert after["permitted_occupancy_load"] == 0

    def test_issued_and_denied_arms_write_different_fields(self):
        """Only the issued arm grants occupancy; only the denied arm records a reason.

        PRD: "On `ISSUED` the venue moves to `PERMIT_ISSUED`, `permit_issued_at`
        is stamped from the logical clock, any conditions note is cleared, and
        `permitted_occupancy_load` becomes the smaller of
        `requested_occupancy_load` and `egress_capacity`".
        PRD: "On `DENIED` the venue moves to the terminal `PERMIT_DENIED`, the
        mandatory 1-to-500-character `note` is stored as `permit_denial_reason`,
        and `permitted_occupancy_load` is set to 0."

        Design: Difficulty/non_linear_state_machine/venue_permit_conditions_cycle_and_three_way_decision_branch
        """
        issued_venue = fx.create_venue()
        validate_success(
            api_client.submit_permit_package(
                issued_venue["id"], f.permit_submission_payload(), VOM
            )
        )
        issued = validate_success(
            api_client.decide_permit(
                issued_venue["id"], f.permit_decision_payload("ISSUED"), OFFICER
            )
        )
        assert issued["status"] == "PERMIT_ISSUED"
        assert issued["egress_capacity"] == 197
        assert issued["permitted_occupancy_load"] == 180
        assert issued["permit_issued_at"] is not None
        assert issued["permit_conditions_note"] is None
        assert issued["permit_submission_round"] == 1

        denied_venue = fx.create_venue(site_name="Basin Street Warehouse")
        validate_success(
            api_client.submit_permit_package(
                denied_venue["id"], f.permit_submission_payload(), VOM
            )
        )
        denied = validate_success(
            api_client.decide_permit(
                denied_venue["id"],
                f.permit_decision_payload(
                    "DENIED", "no sprinklers in an assembly occupancy"
                ),
                OFFICER,
            )
        )
        assert denied["status"] == "PERMIT_DENIED"
        assert denied["permit_denial_reason"] == (
            "no sprinklers in an assembly occupancy"
        )
        assert denied["permitted_occupancy_load"] == 0
        validate_error(
            api_client.activate_lease(denied_venue["id"], VOM),
            ApiErrorId.ERR_VENUE_INVALID_STATE.value,
        )

    def test_a_package_asking_for_more_people_than_the_doors_discharge_is_refused(self):
        """The filing itself is refused when the request exceeds the code ceiling.

        PRD: "Filing is refused with `ERR_OCCUPANCY_ABOVE_EGRESS` when the
        `requested_occupancy_load` on the venue exceeds its own
        `egress_capacity`".

        Design: Corner/validations/capacity_ceilings_require_the_checks_they_depend_on_to_run_first
        """
        venue = fx.create_venue(egress_width_cm=300, requested_occupancy_load=200)
        assert venue["egress_capacity"] == 147
        validate_error(
            api_client.submit_permit_package(
                venue["id"], f.permit_submission_payload(), VOM
            ),
            ApiErrorId.ERR_OCCUPANCY_ABOVE_EGRESS.value,
        )
        unchanged = fx.read_venue(venue["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["permit_submission_round"] == 0

        fitting = fx.create_venue(
            egress_width_cm=300, requested_occupancy_load=147,
            site_name="Basin Street Warehouse",
        )
        filed = validate_success(
            api_client.submit_permit_package(
                fitting["id"], f.permit_submission_payload(), VOM
            )
        )
        assert filed["status"] == "PERMIT_UNDER_REVIEW"

    def test_the_conditions_loop_clears_the_note_it_left_behind(self):
        """Refiling a conditioned package clears the conditions note.

        PRD: "A `VenueOpsManager` files the assembly-occupancy package,
        optionally attaching a `package_note`, which moves the venue from
        `DRAFT` to `PERMIT_UNDER_REVIEW`, increments `permit_submission_round`
        by 1 and clears any `permit_conditions_note` left over from an earlier
        round."

        Design: Corner/state_machines/permit_conditions_loop_returns_the_venue_to_review_and_bumps_the_round
        """
        venue = fx.create_venue()
        validate_success(
            api_client.submit_permit_package(
                venue["id"], f.permit_submission_payload(), VOM
            )
        )
        validate_success(
            api_client.decide_permit(
                venue["id"],
                f.permit_decision_payload("CONDITIONS", "add a second exit sign"),
                OFFICER,
            )
        )
        conditioned = fx.read_venue(venue["id"])
        assert conditioned["permit_conditions_note"] == "add a second exit sign"
        assert conditioned["permit_submission_round"] == 1

        refiled = validate_success(
            api_client.submit_permit_package(
                venue["id"], f.permit_submission_payload(), VOM
            )
        )
        assert refiled["status"] == "PERMIT_UNDER_REVIEW"
        assert refiled["permit_submission_round"] == 2
        assert refiled["permit_conditions_note"] is None


class TestLeaseLifecycle:
    """Switching a lease on, and switching it off again once the site is empty."""

    def test_activation_needs_an_issued_permit_and_a_reached_start_date(self):
        """A lease is switched on only from PERMIT_ISSUED and only on or after its start.

        PRD: "activation is admissible only when the logical clock's calendar
        date is on or after `lease_start_date`, and an early attempt is refused
        with `ERR_LEASE_START_NOT_REACHED`."

        Design: Corner/state_machines/lease_activation_requires_an_issued_permit_and_a_reached_start_date
        """
        draft = fx.create_venue()
        validate_error(
            api_client.activate_lease(draft["id"], VOM),
            ApiErrorId.ERR_VENUE_INVALID_STATE.value,
        )

        early = fx.venue_permitted(
            lease_start_date="2026-09-01", lease_end_date="2027-01-31",
            site_name="Harbor Loft",
        )
        validate_error(
            api_client.activate_lease(early["id"], VOM),
            ApiErrorId.ERR_LEASE_START_NOT_REACHED.value,
        )
        assert fx.read_venue(early["id"])["status"] == "PERMIT_ISSUED"

        fx.set_clock("2026-09-01T00:00:00Z")
        activated = validate_success(api_client.activate_lease(early["id"], VOM))
        assert activated["status"] == "LEASE_ACTIVE"
        assert activated["lease_activated_at"] is not None

    def test_a_lease_ends_only_once_no_run_at_the_venue_is_still_live(self):
        """An occupied site refuses the end-lease, and its own state is checked first.

        PRD: "if any run at that venue still has an operational status of
        `PLANNED`, `OPEN`, `EXTENDED` or `CLOSING`, the request is refused with
        `ERR_VENUE_HAS_ACTIVE_RUN`."

        Design: Corner/endpoints/end_lease_is_conditional_on_every_run_at_the_venue_being_finished
        """
        bundle = fx.open_run()
        venue_id = bundle["venue"]["id"]
        before = fx.read_venue(venue_id)
        validate_error(
            api_client.end_lease(venue_id, VOM),
            ApiErrorId.ERR_VENUE_HAS_ACTIVE_RUN.value,
        )
        inert = fx.read_venue(venue_id)
        assert inert["status"] == "LEASE_ACTIVE"
        assert inert["version"] == before["version"]

        # A venue that never reached LEASE_ACTIVE fails on its own state first,
        # which is the rung above the cross-entity gate.
        draft = fx.create_venue(site_name="Harbor Loft")
        validate_error(
            api_client.end_lease(draft["id"], VOM),
            ApiErrorId.ERR_VENUE_INVALID_STATE.value,
        )

        fx.closed_run(bundle)
        ended = validate_success(api_client.end_lease(venue_id, VOM))
        assert ended["status"] == "LEASE_ENDED"
        assert ended["version"] == inert["version"] + 1
        validate_error(
            api_client.end_lease(venue_id, VOM),
            ApiErrorId.ERR_VENUE_INVALID_STATE.value,
        )


class TestBuildoutWaterfall:
    """Three funding buckets filled in a fixed order, and a cap checked first."""

    def test_the_three_buckets_fill_in_the_declared_order(self):
        """Draws straddle the bucket boundaries and always sum to the spend.

        PRD: "Bucket one is the landlord allowance: the service takes the
        smaller of the amount still to be allocated and the allowance headroom,
        which is `buildout_allowance_cents` less `allowance_drawn_cents`".
        PRD: "Bucket three is the operator's own capital, which is uncapped and
        absorbs whatever remains".

        Design: Difficulty/compensating_invariant/buildout_waterfall_buckets_always_sum_to_the_spend
        """
        venue = fx.create_venue(
            buildout_allowance_cents=1500000,
            kit_reuse_credit_cents=500000,
            buildout_cap_cents=3000000,
        )
        expectations = [
            (1200000, 1200000, 0, 0, 1200000),
            (600000, 1500000, 300000, 0, 1800000),
            (900000, 1500000, 500000, 700000, 2700000),
        ]
        for amount, allowance, credit, capex, spend in expectations:
            drawn = validate_success(
                api_client.draw_buildout(
                    venue["id"], f.buildout_draw_payload(amount), VOM
                )
            )
            assert drawn["allowance_drawn_cents"] == allowance
            assert drawn["kit_credit_drawn_cents"] == credit
            assert drawn["operator_capex_cents"] == capex
            assert drawn["buildout_spend_cents"] == spend
            assert_buildout_conserved(drawn)

    def test_the_cap_is_checked_before_any_bucket_is_touched(self):
        """A refused draw leaves all four counters and the version exactly as they were.

        PRD: "Before any bucket is touched, the service checks the ceiling: if
        the venue's existing `buildout_spend_cents` plus the requested
        `draw_amount_cents` would exceed `buildout_cap_cents`, the draw is
        refused with `ERR_BUILDOUT_CAP_EXCEEDED` and all four counters are left
        exactly as they were."

        Design: Difficulty/compensating_invariant/buildout_waterfall_buckets_always_sum_to_the_spend
        """
        venue = fx.create_venue(
            buildout_allowance_cents=1500000,
            kit_reuse_credit_cents=500000,
            buildout_cap_cents=3000000,
        )
        for amount in (1200000, 600000, 900000):
            validate_success(
                api_client.draw_buildout(
                    venue["id"], f.buildout_draw_payload(amount), VOM
                )
            )
        before = fx.read_venue(venue["id"])
        assert before["buildout_spend_cents"] == 2700000

        validate_error(
            api_client.draw_buildout(
                venue["id"], f.buildout_draw_payload(400000), VOM
            ),
            ApiErrorId.ERR_BUILDOUT_CAP_EXCEEDED.value,
        )
        after = fx.read_venue(venue["id"])
        assert after["allowance_drawn_cents"] == 1500000
        assert after["kit_credit_drawn_cents"] == 500000
        assert after["operator_capex_cents"] == 700000
        assert after["buildout_spend_cents"] == 2700000
        assert after["version"] == before["version"]

        # Landing exactly on the cap is admissible, because the comparison is
        # strictly greater-than.
        exact = validate_success(
            api_client.draw_buildout(
                venue["id"], f.buildout_draw_payload(300000), VOM
            )
        )
        assert exact["operator_capex_cents"] == 1000000
        assert exact["buildout_spend_cents"] == 3000000
        assert_buildout_conserved(exact)


class TestVenueReadsAndListing:
    """The shape of a venue row, the purity of a read and the reverse filters."""

    def test_creation_returns_every_declared_field_with_the_derived_egress_capacity(self):
        """The create response carries the derived ceiling and the zeroed counters.

        PRD: "the venue's `egress_capacity` is the clear width divided by that
        figure, floored to a whole occupant."
        PRD: "A new venue starts in `DRAFT` with `permitted_occupancy_load` at
        0, `permit_submission_round` at 0, `permit_conditions_note`,
        `permit_denial_reason`, `permit_issued_at` and `lease_activated_at` all
        null".

        Design: Corner/entities/venue_creation_returns_every_declared_field_with_the_derived_egress_capacity
        """
        response = api_client.create_venue(
            f.venue_payload(
                lease_extension_option_days=30, kit_reuse_credit_cents=500000
            ),
            VOM,
        )
        data = validate_object(response, 201)
        assert_venue(data)
        assert data["egress_capacity"] == 197
        assert data["egress_width_cm"] == 400
        assert data["status"] == "DRAFT"
        assert data["permit_submission_round"] == 0
        assert data["permitted_occupancy_load"] == 0
        assert data["allowance_drawn_cents"] == 0
        assert data["kit_credit_drawn_cents"] == 0
        assert data["operator_capex_cents"] == 0
        assert data["buildout_spend_cents"] == 0
        assert data["lease_extension_days_consumed"] == 0
        assert data["lease_extension_option_days"] == 30
        assert data["permit_issued_at"] is None
        assert data["lease_activated_at"] is None
        assert data["permit_conditions_note"] is None
        assert data["permit_denial_reason"] is None
        assert data["version"] == 1
        assert data["created_at"] == data["updated_at"]

    def test_a_read_returns_the_stored_row_and_advances_nothing(self):
        """Reading a venue twice yields the same row with the same version.

        PRD: "`version` is an integer that is 1 at creation and increases by
        exactly 1 on every mutation of that row, again including cascaded
        mutations."

        Design: Corner/entities/venue_retrieval_returns_the_stored_row_unchanged
        """
        created = fx.create_venue()
        first = validate_object(api_client.get_venue(created["id"], VOM))
        second = validate_object(api_client.get_venue(created["id"], VOM))
        assert first == created
        assert second == first
        assert second["version"] == 1
        assert second["updated_at"] == created["updated_at"]

    def test_listing_filters_by_city_and_status_and_paginates(self):
        """The venue collection is filterable, ordered and paginated.

        PRD: "Venues filter on `city_code` and `status`."
        PRD: "Results are ordered by `created_at` ascending".

        Design: Corner/entities/venue_listing_filters_by_city_and_status_and_paginates
        """
        nyc_draft = fx.create_venue(site_name="Pier 9 Shed")
        nyc_permitted = fx.venue_permitted(site_name="Harbor Loft")
        chi = fx.create_venue(
            city_code="CHI", site_name="Loop Annex",
        )

        rows, meta = validate_paginated(api_client.list_venues(VOM))
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [
            nyc_draft["id"], nyc_permitted["id"], chi["id"]
        ]

        by_city, city_meta = validate_paginated(
            api_client.list_venues(VOM, {"city_code": "CHI"})
        )
        assert city_meta["total_count"] == 1
        assert by_city[0]["id"] == chi["id"]

        by_status, status_meta = validate_paginated(
            api_client.list_venues(VOM, {"status": "PERMIT_ISSUED"})
        )
        assert status_meta["total_count"] == 1
        assert by_status[0]["id"] == nyc_permitted["id"]

        page, page_meta = validate_paginated(
            api_client.list_venues(VOM, {"limit": 2, "offset": 0})
        )
        assert len(page) == 2
        assert page_meta["total_count"] == 3
        assert page_meta["has_more"] is True

        tail, tail_meta = validate_paginated(
            api_client.list_venues(VOM, {"limit": 2, "offset": 2})
        )
        assert [row["id"] for row in tail] == [chi["id"]]
        assert tail_meta["has_more"] is False

    def test_an_unknown_venue_identifier_is_a_venue_not_found(self):
        """A path identifier that resolves to nothing selects the venue code.

        PRD: "Every identifier in the request path resolves to a stored row,
        validated left to right. The unresolved identifier selects the code".

        Design: Corner/entities/every_path_identifier_returns_its_own_not_found_error
        """
        validate_error(
            api_client.get_venue(UNKNOWN_UUID, VOM),
            ApiErrorId.ERR_VENUE_NOT_FOUND.value,
        )
        validate_error(
            api_client.draw_buildout(
                UNKNOWN_UUID, f.buildout_draw_payload(1000), VOM
            ),
            ApiErrorId.ERR_VENUE_NOT_FOUND.value,
        )
        assert_total_count(api_client.list_venues(VOM), 0)
