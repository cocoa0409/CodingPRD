"""Bonding: statutory requirements, surety capacity conservation and coverage windows."""
from test_helpers import (
    LOGICAL_CLOCK_START,
    ApiErrorId,
    advance_clock,
    create_bond,
    create_commitment,
    create_project,
    complete_project_to_closeout,
    create_surety,
    make_surety_headers,
    setup_active_project,
    setup_open_project,
    setup_project_through_closeout,
    setup_surety_with_commitments,
    validate_error,
    validate_success,
)

#: A performance bond face amount that clears the statutory requirement for a
#: 3,000,000-cent contract under the PRD's tiered selector.
PERFORMANCE_FACE_CENTS = 2_250_000


class TestStatutoryRequirement:
    def test_performance_bond_tier_selection_feeds_the_capacity_gate(
        self, api, platform_admin_headers, contracting_officer_headers, estimator_headers
    ):
        """PRD §3.6: "The size basis is the project's current
        `contract_value_cents`."
        PRD §3.6: "When the size is greater than 1,000,000 cents but at most
        5,000,000 cents the statutory percentage is 0.75."
        PRD §3.6: "For a performance bond the `required_bond_cents` is the size
        multiplied by that statutory percentage, rounded half up to a whole cent."
        PRD §3.6: "For a payment bond the `required_bond_cents` is the size
        multiplied by 1.00, rounded half up."

        Design: Difficulty/combinatorial_formula/performance_bond_tier_selection_feeding_capacity_gate
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5606",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
        )
        issued = validate_success(
            api.issue_bond(ctx["bond"]["id"], ctx["surety_headers"])
        )
        assert issued["required_bond_cents"] == 2_250_000
        assert issued["bond_status"] == "ISSUED"

        payment = validate_success(
            api.create_bond(
                {
                    "project_id": ctx["project"]["id"],
                    "surety_id": ctx["surety"]["id"],
                    "bond_type": "PAYMENT",
                    "bond_amount_cents": 2_999_999,
                    "effective_from": "2026-09-01T00:00:00Z",
                    "effective_to": "2027-09-01T00:00:00Z",
                    "maintain_bond_horizon_days": 30,
                },
                estimator_headers,
            ),
            201,
        )
        assert payment["required_bond_cents"] == 3_000_000

        surety = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert surety["capacity_consumed_cents"] == PERFORMANCE_FACE_CENTS

    def test_payment_bond_below_the_full_contract_value_is_refused(
        self, api, estimator_headers
    ):
        """PRD §3.6: "The bond's statutory `required_bond_cents` must not exceed
        its `bond_amount_cents`, or the attempt is rejected with
        `ERR_BOND_AMOUNT_INSUFFICIENT` (HTTP 422)."
        PRD §3.6: "For a payment bond the `required_bond_cents` is the size
        multiplied by 1.00, rounded half up."

        Design: Difficulty/combinatorial_formula/performance_bond_tier_selection_feeding_capacity_gate
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5606",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
            with_surety=False,
        )
        surety = create_surety()
        payment = validate_success(
            api.create_bond(
                {
                    "project_id": ctx["project"]["id"],
                    "surety_id": surety["id"],
                    "bond_type": "PAYMENT",
                    "bond_amount_cents": 2_999_999,
                    "effective_from": "2026-09-01T00:00:00Z",
                    "effective_to": "2027-09-01T00:00:00Z",
                    "maintain_bond_horizon_days": 30,
                },
                estimator_headers,
            ),
            201,
        )
        response = api.issue_bond(payment["id"], make_surety_headers(surety["id"]))
        validate_error(response, ApiErrorId.ERR_BOND_AMOUNT_INSUFFICIENT)
        assert response.status_code == 422

    def test_performance_bond_statutory_requirement_derived_at_creation(
        self, api, estimator_headers
    ):
        """PRD §3.6: "Recording a bond starts it in `PENDING` status and computes
        its statutory `required_bond_cents` under the tiered requirement described
        below."
        PRD §3.6: "When the size is greater than 1,000,000 cents but at most
        5,000,000 cents the statutory percentage is 0.75."
        PRD §3.6: "For a performance bond the `required_bond_cents` is the size
        multiplied by that statutory percentage, rounded half up to a whole cent."

        Design: Corner/endpoints/performance_bond_statutory_requirement_derived_at_creation
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5718",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            with_surety=False,
        )
        surety = create_surety()
        bond = validate_success(
            api.create_bond(
                {
                    "project_id": ctx["project"]["id"],
                    "surety_id": surety["id"],
                    "bond_type": "PERFORMANCE",
                    "bond_amount_cents": 1_500_000,
                    "effective_from": "2026-09-01T00:00:00Z",
                    "effective_to": "2027-09-01T00:00:00Z",
                    "maintain_bond_horizon_days": 30,
                },
                estimator_headers,
            ),
            201,
        )
        assert bond["required_bond_cents"] == 2_250_000
        assert bond["bond_status"] == "PENDING"

    def test_payment_bond_requires_full_contract_value(self, api, estimator_headers):
        """PRD §3.6: "For a payment bond the `required_bond_cents` is the size
        multiplied by 1.00, rounded half up."
        PRD §3.6: "The bond's statutory `required_bond_cents` must not exceed its
        `bond_amount_cents`, or the attempt is rejected with
        `ERR_BOND_AMOUNT_INSUFFICIENT` (HTTP 422)."

        Design: Corner/errors/payment_bond_requires_full_contract_value
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5719",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            with_surety=False,
        )
        surety = create_surety()
        payment = validate_success(
            api.create_bond(
                {
                    "project_id": ctx["project"]["id"],
                    "surety_id": surety["id"],
                    "bond_type": "PAYMENT",
                    "bond_amount_cents": 2_999_999,
                    "effective_from": "2026-09-01T00:00:00Z",
                    "effective_to": "2027-09-01T00:00:00Z",
                    "maintain_bond_horizon_days": 30,
                },
                estimator_headers,
            ),
            201,
        )
        assert payment["required_bond_cents"] == 3_000_000

        response = api.issue_bond(payment["id"], make_surety_headers(surety["id"]))
        validate_error(response, ApiErrorId.ERR_BOND_AMOUNT_INSUFFICIENT)
        assert response.status_code == 422
        after = validate_success(api.get_bond(payment["id"], estimator_headers))
        assert after["bond_status"] == "PENDING"


class TestBondCoverageWindows:
    def test_same_bond_type_adjacent_coverage_periods_do_not_overlap(
        self, api, estimator_headers
    ):
        """PRD §3.6: "And no other bond on the same project with the same
        `bond_type` that is in `ISSUED` or `EXECUTED` status may have a coverage
        interval intersecting the interval that runs from this bond's
        `effective_from` up to but excluding its `effective_to`"
        PRD §3.6: "The overlap rule reads on the half-open interval deliberately:
        one bond whose `effective_to` equals another's `effective_from` does not
        overlap, because the earlier interval is exclusive at its end and the
        later is inclusive at its start."

        Design: Difficulty/resource_temporal_overlap/same_bond_type_adjacent_coverage_periods_do_not_overlap
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5618")
        surety = create_surety()
        first = create_bond(
            project["id"],
            surety["id"],
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-12-01T00:00:00Z",
        )
        validate_success(api.issue_bond(first["id"], make_surety_headers(surety["id"])))
        second = create_bond(
            project["id"],
            surety["id"],
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
            effective_from="2026-12-01T00:00:00Z",
            effective_to="2027-03-01T00:00:00Z",
        )
        issued = validate_success(
            api.issue_bond(second["id"], make_surety_headers(surety["id"]))
        )
        assert issued["bond_status"] == "ISSUED"

        incumbent = validate_success(api.get_bond(first["id"], estimator_headers))
        assert incumbent["bond_status"] == "ISSUED"
        refreshed = validate_success(api.get_surety(surety["id"], estimator_headers))
        assert refreshed["capacity_consumed_cents"] == 2 * PERFORMANCE_FACE_CENTS

    def test_same_bond_type_overlapping_coverage_periods_are_refused(
        self, api, estimator_headers
    ):
        """PRD §3.6: "And no other bond on the same project with the same
        `bond_type` that is in `ISSUED` or `EXECUTED` status may have a coverage
        interval intersecting the interval that runs from this bond's
        `effective_from` up to but excluding its `effective_to`; an intersection
        is rejected with `ERR_RESERVATION_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/same_bond_type_adjacent_coverage_periods_do_not_overlap
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5618")
        surety = create_surety()
        first = create_bond(
            project["id"],
            surety["id"],
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-12-01T00:00:00Z",
        )
        validate_success(api.issue_bond(first["id"], make_surety_headers(surety["id"])))
        overlapping = create_bond(
            project["id"],
            surety["id"],
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
            effective_from="2026-11-30T23:59:59Z",
            effective_to="2027-03-01T00:00:00Z",
        )
        response = api.issue_bond(overlapping["id"], make_surety_headers(surety["id"]))
        validate_error(response, ApiErrorId.ERR_RESERVATION_OVERLAP)
        assert response.status_code == 409


class TestSuretyCapacityConservation:
    def test_temporally_intersecting_surety_commitments_exhaust_aggregate_capacity(
        self, api, platform_admin_headers, contracting_officer_headers
    ):
        """PRD §3.6: "Reservations are refused when the sum of the committed
        amounts of every commitment on that surety whose coverage interval
        intersects the new commitment's interval, plus the requested amount, would
        exceed the surety's aggregate capacity; that refusal is reported as
        `ERR_AGGREGATE_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD §2.11: "The consumed amount is the sum of the capacity consumed by
        that surety's bonds plus the sum of the committed amounts of that surety's
        commitments that are either reserved or active"

        Design: Difficulty/resource_temporal_overlap/temporally_intersecting_surety_commitments_exhaust_aggregate_capacity
        """
        ctx = setup_surety_with_commitments()
        response = api.create_surety_commitment(
            {
                "surety_id": ctx["surety"]["id"],
                "project_id": ctx["project_b"]["id"],
                "committed_amount_cents": 120_000_000,
            },
            contracting_officer_headers,
        )
        validate_error(response, ApiErrorId.ERR_AGGREGATE_CAPACITY_EXCEEDED)
        assert response.status_code == 422

        surety = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert surety["capacity_consumed_cents"] == 120_000_000
        assert surety["available_capacity_cents"] == 80_000_000
        commitment = validate_success(
            api.get_surety_commitment(ctx["commitment"]["id"], contracting_officer_headers)
        )
        assert commitment["commitment_status"] == "RESERVED"

    def test_non_overlapping_commitments_do_not_compete_for_the_same_capacity(
        self, api, platform_admin_headers, contracting_officer_headers
    ):
        """PRD §3.6: "The intersection test is what makes the check meaningful:
        two reservations that will not overlap in time do not compete for the same
        capacity, while two that do overlap must both fit inside it."
        PRD §3.6: "Once released, the reservation no longer consumes capacity at
        all."

        Design: Difficulty/resource_temporal_overlap/temporally_intersecting_surety_commitments_exhaust_aggregate_capacity
        """
        ctx = setup_surety_with_commitments()
        released = validate_success(
            api.release_surety_commitment(
                ctx["commitment"]["id"], contracting_officer_headers
            )
        )
        assert released["commitment_status"] == "RELEASED"

        again = validate_success(
            api.create_surety_commitment(
                {
                    "surety_id": ctx["surety"]["id"],
                    "project_id": ctx["project_b"]["id"],
                    "committed_amount_cents": 120_000_000,
                },
                contracting_officer_headers,
            ),
            201,
        )
        assert again["commitment_status"] == "RESERVED"
        surety = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert surety["capacity_consumed_cents"] == 120_000_000
        assert surety["available_capacity_cents"] == 80_000_000

    def test_exact_capacity_boundary_then_one_cent_over_is_rejected(
        self, api, platform_admin_headers, contracting_officer_headers
    ):
        """PRD §2.11: "The available amount is the aggregate capacity minus the
        consumed amount, and it is floored at zero so that it can never be
        reported as a negative number."
        PRD §3.6: "Reservations are refused when the sum of the committed amounts
        of every commitment on that surety whose coverage interval intersects the
        new commitment's interval, plus the requested amount, would exceed the
        surety's aggregate capacity"

        Design: Corner/cross_cutting_layers/exact_capacity_boundary_then_one_cent_over_is_rejected
        """
        advance_clock(LOGICAL_CLOCK_START)
        surety = create_surety(
            surety_name="Cascade Indemnity",
            aggregate_capacity_cents=15_000_000,
            single_job_limit_cents=15_000_000,
        )
        project_a = create_project(project_code="CALTRANS-04-1J5728")
        project_b = create_project(project_code="CALTRANS-04-1J5729")

        # Exactly the full aggregate capacity is reserved successfully.
        full = create_commitment(surety["id"], project_a["id"], 15_000_000)
        assert full["commitment_status"] == "RESERVED"
        drawn = validate_success(api.get_surety(surety["id"], platform_admin_headers))
        assert drawn["capacity_consumed_cents"] == 15_000_000
        assert drawn["available_capacity_cents"] == 0

        # One cent beyond the exhausted pool is refused.
        response = api.create_surety_commitment(
            {
                "surety_id": surety["id"],
                "project_id": project_b["id"],
                "committed_amount_cents": 1,
            },
            contracting_officer_headers,
        )
        validate_error(response, ApiErrorId.ERR_AGGREGATE_CAPACITY_EXCEEDED)
        assert response.status_code == 422
        unchanged = validate_success(api.get_surety(surety["id"], platform_admin_headers))
        assert unchanged["capacity_consumed_cents"] == 15_000_000
        assert unchanged["available_capacity_cents"] == 0

    def test_capacity_issue_then_cascade_release_returns_same_available_cents(
        self, api, platform_admin_headers
    ):
        """PRD §2.11: "Issuing or executing a bond adds its face amount to the
        consumed total and therefore removes that amount from the available
        total; releasing the bond sets its consumed amount to zero and therefore
        returns exactly that amount to the available total."
        PRD §3.12: "it is the reason a project that closes out cleanly ends with
        its items closed, its project complete, its commitments released, its
        bonds released and its sureties' available capacity restored to what it
        was before the project began."

        Design: Difficulty/compensating_invariant/capacity_issue_then_release_returns_same_available_cents
        """
        ctx = setup_active_project(
            project_code="CALTRANS-04-1J5620",
            bid_unit_price_cents=2000,
            bond_amount_cents=12_000_000,
        )
        after_issue = validate_success(
            api.get_surety(ctx["surety"]["id"], platform_admin_headers)
        )
        assert after_issue["capacity_consumed_cents"] == 12_000_000
        assert after_issue["available_capacity_cents"] == 188_000_000

        ctx = complete_project_to_closeout(ctx, measured_quantity=1000)
        restored = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert restored["aggregate_capacity_cents"] == 200_000_000
        assert restored["capacity_consumed_cents"] == 0
        assert restored["available_capacity_cents"] == 200_000_000

    def test_explicit_bond_release_returns_capacity_to_the_surety(
        self, api, platform_admin_headers, contracting_officer_headers
    ):
        """PRD §3.6: "An `ISSUED` bond may be released only once the project's
        delivery dimension has reached `COMPLETE` and the project's non-closed
        reconciliation has reached `CLOSED`, so that a live bond cannot be shed
        while the work it backs is still open."
        PRD §3.6: "Every release sets the bond to `RELEASED`, stamps its
        released-at instant from the logical clock, sets its consumed capacity to
        zero, recomputes the surety's exposure, and advances the surety's
        `version`."

        Design: Difficulty/compensating_invariant/capacity_issue_then_release_returns_same_available_cents
        """
        ctx = setup_project_through_closeout(
            project_code="CALTRANS-04-1J5620", bid_unit_price_cents=2000
        )
        assert ctx["project"]["project_status"] == "COMPLETE"

        replacement = create_bond(
            ctx["project"]["id"],
            ctx["surety"]["id"],
            bond_amount_cents=12_000_000,
            effective_from="2027-09-01T00:00:00Z",
            effective_to="2028-09-01T00:00:00Z",
        )
        issued = validate_success(
            api.issue_bond(replacement["id"], ctx["surety_headers"])
        )
        assert issued["bond_status"] == "ISSUED"
        drawn = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert drawn["available_capacity_cents"] == 188_000_000

        released = validate_success(
            api.release_bond(replacement["id"], contracting_officer_headers)
        )
        assert released["capacity_consumed_cents"] == 0
        final = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert final["capacity_consumed_cents"] == 0
        assert final["available_capacity_cents"] == 200_000_000
        assert final["aggregate_capacity_cents"] == 200_000_000


class TestBondLifecycleGuards:
    def test_releasing_an_already_released_bond_returns_invalid_state(
        self, api, contracting_officer_headers
    ):
        """PRD §3.6: "A `PENDING` bond may be released at any time by a
        `ContractingOfficer`, which is the route for a bond that was recorded and
        then abandoned before issue."
        PRD §3.6: "Every release sets the bond to `RELEASED`"
        PRD §2.5: "The fifth band is state: if the target resource is not in the
        state that the requested transition requires, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/releasing_an_already_released_bond_returns_invalid_state
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5708")
        surety = create_surety()
        bond = create_bond(
            project["id"],
            surety["id"],
            bond_type="BID",
            bond_amount_cents=300_000,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-12-01T00:00:00Z",
        )
        released = validate_success(api.release_bond(bond["id"], contracting_officer_headers))
        assert released["bond_status"] == "RELEASED"

        response = api.release_bond(bond["id"], contracting_officer_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert response.status_code == 409

        after = validate_success(api.get_bond(bond["id"], contracting_officer_headers))
        assert after["bond_status"] == "RELEASED"
        assert after["capacity_consumed_cents"] == 0

    def test_performance_bond_call_requires_outstanding_lien_claim(
        self, api, platform_admin_headers
    ):
        """PRD §3.6: "A `PlatformAdmin` executes a performance bond that is in
        `ISSUED` status, and the move requires the project's payment bond to show
        an outstanding lien claim — a `lien_claim_amount_cents` strictly greater
        than zero — or the attempt is rejected with `ERR_NO_LIEN_CLAIM`
        (HTTP 422)."

        Design: Corner/errors/performance_bond_call_requires_outstanding_lien_claim
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5720",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
            issue_bond_now=True,
        )
        assert ctx["bond"]["bond_status"] == "ISSUED"

        response = api.execute_bond(ctx["bond"]["id"], platform_admin_headers)
        validate_error(response, ApiErrorId.ERR_NO_LIEN_CLAIM)
        assert response.status_code == 422
        after = validate_success(api.get_bond(ctx["bond"]["id"], platform_admin_headers))
        assert after["bond_status"] == "ISSUED"


class TestBondExecutionPermissions:
    def test_platform_admin_exclusive_performance_bond_execution(
        self, api, contracting_officer_headers
    ):
        """PRD §2.1: "`PlatformAdmin` is the back-office operator, responsible for
        the surety registry, surety suspension and reinstatement, the calling of
        an executed performance bond, the finalization of engineer determinations,
        and the logical clock."
        PRD §2.1: "A request whose declared role is not permitted on the
        operation being attempted is rejected with `ERR_FORBIDDEN` and an HTTP 403
        status."

        Design: Corner/rbac/platform_admin_exclusive_performance_bond_execution
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5722",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            bond_amount_cents=PERFORMANCE_FACE_CENTS,
            issue_bond_now=True,
        )
        response = api.execute_bond(ctx["bond"]["id"], contracting_officer_headers)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert response.status_code == 403
        after = validate_success(api.get_bond(ctx["bond"]["id"], contracting_officer_headers))
        assert after["bond_status"] == "ISSUED"


class TestSuspendedSurety:
    def test_suspended_surety_beats_insufficient_bond_amount(
        self, api, platform_admin_headers
    ):
        """PRD §2.5: "The sixth band is business safety, where a suspended surety
        is rejected first with `ERR_SURETY_SUSPENDED` (HTTP 422) before any
        capacity arithmetic is attempted"
        PRD §3.6: "The backing surety must be `ACTIVE`, or the attempt is
        rejected with `ERR_SURETY_SUSPENDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_surety_beats_insufficient_bond_amount
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5612",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            bond_amount_cents=1_000_000,
        )
        # `required_bond_cents` is a computed field sized off the project's
        # current `contract_value_cents`, so it is read back after the award.
        bond = validate_success(api.get_bond(ctx["bond"]["id"], platform_admin_headers))
        assert bond["required_bond_cents"] > bond["bond_amount_cents"], (
            "the dual failure requires a face amount below the statutory requirement"
        )
        validate_success(api.suspend_surety(ctx["surety"]["id"], platform_admin_headers))

        response = api.issue_bond(ctx["bond"]["id"], ctx["surety_headers"])
        validate_error(response, ApiErrorId.ERR_SURETY_SUSPENDED)
        assert response.status_code == 422

        after = validate_success(api.get_bond(ctx["bond"]["id"], platform_admin_headers))
        assert after["bond_status"] == "PENDING"

    def test_insufficient_bond_amount_surfaces_once_the_surety_is_active(
        self, api, platform_admin_headers
    ):
        """PRD §3.6: "The bond's statutory `required_bond_cents` must not exceed
        its `bond_amount_cents`, or the attempt is rejected with
        `ERR_BOND_AMOUNT_INSUFFICIENT` (HTTP 422)."
        PRD §3.6: "The backing surety must be `ACTIVE`, or the attempt is
        rejected with `ERR_SURETY_SUSPENDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_surety_beats_insufficient_bond_amount
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5612",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            bond_amount_cents=1_000_000,
        )
        response = api.issue_bond(ctx["bond"]["id"], ctx["surety_headers"])
        validate_error(response, ApiErrorId.ERR_BOND_AMOUNT_INSUFFICIENT)
        assert response.status_code == 422
        after = validate_success(api.get_bond(ctx["bond"]["id"], platform_admin_headers))
        assert after["bond_status"] == "PENDING"
