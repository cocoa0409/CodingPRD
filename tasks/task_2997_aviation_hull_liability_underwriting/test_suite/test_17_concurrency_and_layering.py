"""Optimistic concurrency, non-retroactive pricing and same-request consistency.

Two operations in this API carry a version token, and the token is compared
before any business rule is evaluated.  The tests here drive those tokens through
their real staling paths, check that a pricing credit decided at one premium
event is never revisited at another, and check that a mutating call's own
response body already carries every figure it caused.
"""

from test_helpers import (
    ApiErrorId,
    CoverageStatus,
    EndorsementStatus,
    PerilsScope,
    PlacementStatus,
    PolicyStatus,
    TxnBasis,
    TxnType,
    UseClass,
    WarrantyFinding,
    WarrantyStatus,
    assert_field_values,
    assert_ledger_row,
    assert_no_ledger_row_of_type,
    ledger_signed_sum,
    rows_of_type,
    validate_error,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# Agreed values used by the revision tests.  The first two sit under the
# over-insurance ceiling of §3.4 for the airframe they are attached to; the
# third deliberately breaches it, so that a request carrying both a stale token
# and a fiscal fault can be observed.
REVISED_VALUE_CENTS = 40000000
SECOND_REVISED_VALUE_CENTS = 46000000
OVER_CEILING_VALUE_CENTS = 60000000

# The private fleet used by the war-placement and fleet-credit tests.
PRIVATE_HULL_VALUE_CENTS = 30000000
CONSISTENCY_REVISED_VALUE_CENTS = 36000000

FIRST_WAR_LINE_CENTS = 200000000
SECOND_WAR_LINE_CENTS = 300000000
FIRST_WAR_WINDOW_FROM = f.POLICY_EFFECTIVE_FROM
FIRST_WAR_WINDOW_TO = "2026-10-01T00:00:00Z"
SECOND_WAR_WINDOW_FROM = "2026-10-02T00:00:00Z"
SECOND_WAR_WINDOW_TO = "2027-08-01T00:00:00Z"

REMOVAL_EFFECTIVE_DATE = f.CLOCK_LATE_TERM
ADDITION_EFFECTIVE_DATE = "2026-12-01T00:00:00Z"


def _logged_band(pilot_payload: dict, clock_utc: str) -> str:
    """The rating band the pilot's logged figures earn at the given instant."""
    score = c.qualification_score(
        pilot_payload["total_logged_hours"],
        pilot_payload["hours_on_type"],
        pilot_payload["instrument_rated"],
        pilot_payload["license_type"],
        pilot_payload["last_training_completed_at"],
        clock_utc,
    )
    return c.band_for_score(score)


def _rate_ppm(policy: dict, use_class: str, band: str) -> int:
    """The hull rate for a use class and band, from the policy's own inputs."""
    return c.rate_ppm_for(
        policy["base_hull_rate_ppm"], use_class, policy["territorial_limit_code"], band
    )


def _private_hull_premium_cents(policy: dict, live_schedule_count: int) -> int:
    """The annual premium of one private hull, credit applied only if it qualifies."""
    band = _logged_band(f.senior_pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
    return c.annual_premium_cents(
        PRIVATE_HULL_VALUE_CENTS,
        _rate_ppm(policy, UseClass.PRIVATE, band),
        policy["policy_type"],
        live_schedule_count=live_schedule_count,
    )


def _private_fleet_register(api, hull_count: int) -> dict:
    """A private owner, one first-band pilot and `hull_count` distinct airframes."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api, f.private_owner_operator_payload())
    pilot = fx.make_pilot(api, f.senior_pilot_payload())
    aircraft = [
        fx.make_aircraft(
            api, f.single_piston_aircraft_payload(f.unique_registration_mark())
        )
        for _ in range(hull_count)
    ]
    return {
        "operator_id": operator["id"],
        "pilot_id": pilot["id"],
        "aircraft": aircraft,
    }


def _private_fleet_policy(api, register: dict) -> dict:
    """A draft worldwide fleet policy that permits the private use class."""
    return fx.make_policy(
        api,
        register["operator_id"],
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
    )


def _attach_private_hull(api, policy_id: str, register: dict, index: int) -> dict:
    return fx.make_schedule(
        api,
        policy_id,
        register["aircraft"][index]["id"],
        register["pilot_id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
    )


class TestScheduleValueRevisionVersionToken:
    """The value-revision token is compared against the schedule's live version."""

    def test_a_warranty_finding_stales_a_revision_priced_against_the_earlier_version(
        self, api
    ):
        """PRD §2.10: "If `expected_schedule_version` does not equal the schedule's
        current `version`, the request is rejected with `ERR_STALE_SCHEDULE_VERSION`
        (HTTP 412) before any business rule runs, and nothing is mutated."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_schedule_value_revision_stale_version_rejected
        """
        book = fx.bound_policy_with_hull(api)
        schedule_id = book["schedule_id"]
        policy_id = book["policy_id"]
        observed = fx.fetch_schedule(api, schedule_id)
        observed_version = observed["version"]
        rated_band = _logged_band(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        original_rate_ppm = _rate_ppm(book["policy"], UseClass.INSTRUCTIONAL, rated_band)
        original_premium_cents = c.annual_premium_cents(
            observed["agreed_value_cents"],
            original_rate_ppm,
            book["policy"]["policy_type"],
            live_schedule_count=1,
        )

        # An unrelated write on the same row consumes the version the pricing
        # client is holding.
        finding = fx.set_warranty(api, schedule_id, WarrantyFinding.EVIDENCE_VERIFIED)
        assert_field_values(
            finding,
            warranty_status=WarrantyStatus.COMPLIANT,
            coverage_status=CoverageStatus.ACTIVE,
            version=observed_version + 1,
        )

        refused = api.revise_schedule_value(
            schedule_id,
            f.value_revision_payload(REVISED_VALUE_CENTS, observed_version),
            headers=users.UNDERWRITER,
        )
        validate_error(refused, ApiErrorId.STALE_SCHEDULE_VERSION)

        unchanged = fx.fetch_schedule(api, schedule_id)
        assert_field_values(
            unchanged,
            agreed_value_cents=observed["agreed_value_cents"],
            rate_ppm=original_rate_ppm,
            hull_premium_cents=original_premium_cents,
            version=observed_version + 1,
        )
        rows = fx.ledger_rows(api, policy_id)
        assert_no_ledger_row_of_type(rows, TxnType.RERATE_ADJUSTMENT)
        assert_field_values(
            fx.fetch_policy(api, policy_id),
            written_premium_cents=original_premium_cents,
        )

    def test_b_a_consumed_token_is_refused_even_when_the_new_value_also_breaches_the_ceiling(
        self, api
    ):
        """PRD §2.11: "Because rank 19 sits above every business-safety rule, a stale
        concurrency token is reported even when the request would also have failed a
        fiscal check — the token is checked and the request abandoned before anything
        else is evaluated."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_schedule_value_revision_stale_version_rejected
        """
        book = fx.bound_policy_with_hull(api)
        schedule_id = book["schedule_id"]
        policy_id = book["policy_id"]
        policy = book["policy"]
        rated_band = _logged_band(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        rate_ppm = _rate_ppm(policy, UseClass.INSTRUCTIONAL, rated_band)
        original_premium_cents = c.annual_premium_cents(
            book["schedule"]["agreed_value_cents"],
            rate_ppm,
            policy["policy_type"],
            live_schedule_count=1,
        )
        first_premium_cents = c.annual_premium_cents(
            REVISED_VALUE_CENTS, rate_ppm, policy["policy_type"], live_schedule_count=1
        )
        second_premium_cents = c.annual_premium_cents(
            SECOND_REVISED_VALUE_CENTS,
            rate_ppm,
            policy["policy_type"],
            live_schedule_count=1,
        )

        first_token = fx.fetch_schedule(api, schedule_id)["version"]
        revised = validate_unpaginated(
            api.revise_schedule_value(
                schedule_id,
                f.value_revision_payload(REVISED_VALUE_CENTS, first_token),
                headers=users.UNDERWRITER,
            )
        )
        assert_field_values(
            revised,
            agreed_value_cents=REVISED_VALUE_CENTS,
            rate_ppm=rate_ppm,
            hull_premium_cents=first_premium_cents,
            version=first_token + 1,
        )

        # The accepted revision consumed its own token, so replaying it is stale —
        # and it stays stale even though the value it carries also breaches the
        # over-insurance ceiling of the airframe.
        assert OVER_CEILING_VALUE_CENTS > c.over_insurance_ceiling_cents(
            c.depreciated_value_cents(
                f.aircraft_payload()["hull_new_value_cents"],
                f.aircraft_payload()["manufacture_year"],
                c.calendar_year_of(f.CLOCK_BEFORE_INCEPTION),
            )
        )
        replayed = api.revise_schedule_value(
            schedule_id,
            f.value_revision_payload(OVER_CEILING_VALUE_CENTS, first_token),
            headers=users.UNDERWRITER,
        )
        validate_error(replayed, ApiErrorId.STALE_SCHEDULE_VERSION)
        assert_field_values(
            fx.fetch_schedule(api, schedule_id),
            agreed_value_cents=REVISED_VALUE_CENTS,
            hull_premium_cents=first_premium_cents,
            version=first_token + 1,
        )

        second_token = fx.fetch_schedule(api, schedule_id)["version"]
        assert second_token == first_token + 1
        revised_again = validate_unpaginated(
            api.revise_schedule_value(
                schedule_id,
                f.value_revision_payload(SECOND_REVISED_VALUE_CENTS, second_token),
                headers=users.UNDERWRITER,
            )
        )
        assert_field_values(
            revised_again,
            agreed_value_cents=SECOND_REVISED_VALUE_CENTS,
            hull_premium_cents=second_premium_cents,
            version=second_token + 1,
        )

        rerate_rows = rows_of_type(
            fx.ledger_rows(api, policy_id), TxnType.RERATE_ADJUSTMENT
        )
        assert len(rerate_rows) == 2, (
            "one RERATE_ADJUSTMENT row per accepted revision and none per refusal, "
            f"got {len(rerate_rows)}"
        )
        assert_ledger_row(
            rerate_rows[0],
            txn_type=TxnType.RERATE_ADJUSTMENT,
            amount_cents=first_premium_cents - original_premium_cents,
            basis=TxnBasis.ANNUAL,
            effective_date=f.CLOCK_BEFORE_INCEPTION,
            policy_id=policy_id,
        )
        assert_field_values(rerate_rows[0], endorsement_id=None)
        assert_ledger_row(
            rerate_rows[1],
            txn_type=TxnType.RERATE_ADJUSTMENT,
            amount_cents=second_premium_cents - first_premium_cents,
            basis=TxnBasis.ANNUAL,
            effective_date=f.CLOCK_BEFORE_INCEPTION,
            policy_id=policy_id,
        )
        assert_field_values(rerate_rows[1], endorsement_id=None)
        assert_field_values(
            fx.fetch_policy(api, policy_id),
            written_premium_cents=second_premium_cents,
        )


class TestWarPlacementPolicyVersionToken:
    """The placement token is the parent policy's version, on a creating write."""

    def test_b_each_accepted_placement_consumes_the_token_it_was_written_against(
        self, api
    ):
        """PRD §3.7: "Creating a placement appends one `WAR_RISK_PREMIUM` ledger row,
        updates the market's `committed_line_cents` and `available_line_cents`,
        re-derives the policy's `written_premium_cents` and advances the policy's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_war_placement_stale_policy_version_rejected
        """
        register = _private_fleet_register(api, 1)
        policy = _private_fleet_policy(api, register)
        policy_id = policy["id"]
        _attach_private_hull(api, policy_id, register, 0)
        market = fx.make_war_market(
            api, f.war_market_payload(perils_offered=PerilsScope.WAR_ONLY)
        )
        market_id = market["id"]
        aggregate_line_cents = market["aggregate_line_cents"]
        first_premium_cents = c.war_premium_cents(
            FIRST_WAR_LINE_CENTS, PerilsScope.WAR_ONLY, policy["territorial_limit_code"]
        )
        second_premium_cents = c.war_premium_cents(
            SECOND_WAR_LINE_CENTS, PerilsScope.WAR_ONLY, policy["territorial_limit_code"]
        )

        first_token = fx.fetch_policy(api, policy_id)["version"]
        first_placement = validate_unpaginated(
            api.create_war_placement(
                f.war_placement_payload(
                    policy_id,
                    market_id,
                    first_token,
                    war_hull_line_cents=FIRST_WAR_LINE_CENTS,
                    perils_scope=PerilsScope.WAR_ONLY,
                    coverage_from=FIRST_WAR_WINDOW_FROM,
                    coverage_to=FIRST_WAR_WINDOW_TO,
                ),
                headers=users.UNDERWRITER,
            ),
            expected_status=201,
        )
        assert_field_values(
            first_placement,
            status=PlacementStatus.BOUND,
            premium_cents=first_premium_cents,
        )
        assert_field_values(
            fx.fetch_war_market(api, market_id),
            committed_line_cents=FIRST_WAR_LINE_CENTS,
            available_line_cents=aggregate_line_cents - FIRST_WAR_LINE_CENTS,
        )
        assert_field_values(
            fx.fetch_policy(api, policy_id),
            status=PolicyStatus.DRAFT,
            written_premium_cents=first_premium_cents,
            version=first_token + 1,
        )

        # A second line on a window that neither touches nor overlaps the first is a
        # sound placement; only the token it carries has been consumed.
        second_body = f.war_placement_payload(
            policy_id,
            market_id,
            first_token,
            war_hull_line_cents=SECOND_WAR_LINE_CENTS,
            perils_scope=PerilsScope.WAR_ONLY,
            coverage_from=SECOND_WAR_WINDOW_FROM,
            coverage_to=SECOND_WAR_WINDOW_TO,
        )
        validate_error(
            api.create_war_placement(second_body, headers=users.UNDERWRITER),
            ApiErrorId.STALE_POLICY_VERSION,
        )

        second_token = fx.fetch_policy(api, policy_id)["version"]
        assert second_token == first_token + 1
        second_body["expected_policy_version"] = second_token
        second_placement = validate_unpaginated(
            api.create_war_placement(second_body, headers=users.UNDERWRITER),
            expected_status=201,
        )
        assert_field_values(
            second_placement,
            status=PlacementStatus.BOUND,
            premium_cents=second_premium_cents,
        )

        placed_line_cents = FIRST_WAR_LINE_CENTS + SECOND_WAR_LINE_CENTS
        assert_field_values(
            fx.fetch_war_market(api, market_id),
            committed_line_cents=placed_line_cents,
            available_line_cents=aggregate_line_cents - placed_line_cents,
        )
        rows = fx.ledger_rows(api, policy_id)
        war_rows = rows_of_type(rows, TxnType.WAR_RISK_PREMIUM)
        assert [row["amount_cents"] for row in war_rows] == [
            first_premium_cents,
            second_premium_cents,
        ], "one WAR_RISK_PREMIUM row per accepted placement, in created_at order"
        assert_no_ledger_row_of_type(rows, TxnType.INITIAL_PREMIUM)
        assert_field_values(
            fx.fetch_policy(api, policy_id),
            status=PolicyStatus.DRAFT,
            written_premium_cents=first_premium_cents + second_premium_cents,
        )
        assert ledger_signed_sum(rows) == first_premium_cents + second_premium_cents


class TestFleetCreditIsNotRevisitedWhenTheFleetShrinks:
    """A credit decided at one premium event survives later changes in fleet size."""

    @staticmethod
    def _five_hull_fleet(api):
        """A bound fleet policy carrying five identical private hulls."""
        register = _private_fleet_register(api, 6)
        policy = _private_fleet_policy(api, register)
        schedule_ids = [
            _attach_private_hull(api, policy["id"], register, index)["id"]
            for index in range(5)
        ]
        bound = fx.bind_policy(api, policy["id"])
        return {
            "register": register,
            "policy": bound,
            "policy_id": bound["id"],
            "schedule_ids": schedule_ids,
        }

    @staticmethod
    def _removal_delta_cents(policy: dict, hull_premium_cents: int) -> int:
        """The negated, twice-rounded short-rate return of a removed hull."""
        unexpired_days = c.whole_days_between(
            REMOVAL_EFFECTIVE_DATE, policy["effective_to"]
        )
        unearned_cents = c.pro_rata_return_cents(
            hull_premium_cents, unexpired_days, policy["term_days"]
        )
        return -c.floor_ppm(unearned_cents, c.REMOVE_AIRCRAFT_RETURN_PPM)

    def test_a_removing_hulls_does_not_claw_the_credit_back_off_the_survivor(self, api):
        """PRD §3.4: "The credit is evaluated afresh at each premium-computation event
        and is never applied retroactively."

        Design: Corner/cross_cutting_complexity_layers/corner_fleet_credit_threshold_does_not_reverse_when_the_fleet_shrinks
        """
        book = self._five_hull_fleet(api)
        policy = book["policy"]
        policy_id = book["policy_id"]
        schedule_ids = book["schedule_ids"]
        full_premium_cents = _private_hull_premium_cents(policy, 4)
        credited_premium_cents = _private_hull_premium_cents(policy, 5)
        assert credited_premium_cents < full_premium_cents, (
            "the fifth hull must be the one that earns the credit"
        )
        initial_premium_cents = 4 * full_premium_cents + credited_premium_cents
        assert_field_values(
            fx.fetch_schedule(api, schedule_ids[3]),
            hull_premium_cents=full_premium_cents,
        )
        assert_field_values(
            fx.fetch_schedule(api, schedule_ids[4]),
            hull_premium_cents=credited_premium_cents,
        )
        assert_field_values(
            fx.fetch_policy(api, policy_id),
            live_schedule_count=5,
            total_hull_sum_insured_cents=5 * PRIVATE_HULL_VALUE_CENTS,
            written_premium_cents=initial_premium_cents,
        )

        expected_delta_cents = self._removal_delta_cents(policy, full_premium_cents)
        written_premium_cents = initial_premium_cents
        for removed_index, live_count_after in ((0, 4), (1, 3)):
            endorsement = fx.make_endorsement(
                api,
                f.remove_aircraft_endorsement_payload(
                    policy_id,
                    schedule_ids[removed_index],
                    effective_date=REMOVAL_EFFECTIVE_DATE,
                ),
                headers=users.BROKER,
            )
            quoted = fx.quote_endorsement(
                api, endorsement["id"], headers=users.UNDERWRITER
            )
            assert_field_values(
                quoted,
                status=EndorsementStatus.QUOTED,
                quoted_premium_delta_cents=expected_delta_cents,
            )
            bound = fx.bind_endorsement(
                api, endorsement["id"], headers=users.SECOND_UNDERWRITER
            )
            assert_field_values(
                bound,
                status=EndorsementStatus.BOUND,
                premium_delta_cents=expected_delta_cents,
            )
            written_premium_cents += expected_delta_cents
            assert_field_values(
                fx.fetch_schedule(api, schedule_ids[removed_index]),
                coverage_status=CoverageStatus.REMOVED,
            )
            assert_field_values(
                fx.fetch_policy(api, policy_id),
                live_schedule_count=live_count_after,
                written_premium_cents=written_premium_cents,
            )

        # The fleet now stands two hulls below the threshold, and the hull that was
        # priced with the credit still carries the credited figure.
        assert_field_values(
            fx.fetch_schedule(api, schedule_ids[4]),
            agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
            hull_premium_cents=credited_premium_cents,
        )
        assert_field_values(
            fx.fetch_schedule(api, schedule_ids[2]),
            hull_premium_cents=full_premium_cents,
        )
        rows = fx.ledger_rows(api, policy_id)
        assert ledger_signed_sum(rows) == written_premium_cents
        assert [row["amount_cents"] for row in rows_of_type(
            rows, TxnType.ENDORSEMENT_PREMIUM
        )] == [expected_delta_cents, expected_delta_cents]

    def test_b_a_hull_added_below_the_threshold_is_priced_without_the_credit(self, api):
        """PRD §3.4: "The credit applies only when the policy's `policy_type` is
        `FLEET` **and** the number of live schedules on that policy — those whose
        `coverage_status` is `PENDING`, `ACTIVE` or `SUSPENDED_WARRANTY`, counting the
        schedule currently being computed — has reached at least five."

        Design: Corner/cross_cutting_complexity_layers/corner_fleet_credit_threshold_does_not_reverse_when_the_fleet_shrinks
        """
        book = self._five_hull_fleet(api)
        policy = book["policy"]
        policy_id = book["policy_id"]
        schedule_ids = book["schedule_ids"]
        register = book["register"]
        full_premium_cents = _private_hull_premium_cents(policy, 4)
        credited_premium_cents = _private_hull_premium_cents(policy, 5)
        written_premium_cents = 4 * full_premium_cents + credited_premium_cents
        removal_delta_cents = self._removal_delta_cents(policy, full_premium_cents)

        for removed_index in (0, 1):
            removal = fx.make_endorsement(
                api,
                f.remove_aircraft_endorsement_payload(
                    policy_id,
                    schedule_ids[removed_index],
                    effective_date=REMOVAL_EFFECTIVE_DATE,
                ),
                headers=users.BROKER,
            )
            fx.quote_endorsement(api, removal["id"], headers=users.UNDERWRITER)
            fx.bind_endorsement(api, removal["id"], headers=users.SECOND_UNDERWRITER)
            written_premium_cents += removal_delta_cents
        assert_field_values(fx.fetch_policy(api, policy_id), live_schedule_count=3)

        # Three live hulls plus the hypothetical one is four, one short of the
        # threshold, so the new hull is priced gross.
        unexpired_days = c.whole_days_between(
            ADDITION_EFFECTIVE_DATE, policy["effective_to"]
        )
        expected_add_delta_cents = c.pro_rata_charge_cents(
            full_premium_cents, unexpired_days, policy["term_days"]
        )
        addition = fx.make_endorsement(
            api,
            f.add_aircraft_endorsement_payload(
                policy_id,
                register["aircraft"][5]["id"],
                register["pilot_id"],
                effective_date=ADDITION_EFFECTIVE_DATE,
                new_agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
                new_use_class=UseClass.PRIVATE,
            ),
            headers=users.BROKER,
        )
        quoted = fx.quote_endorsement(api, addition["id"], headers=users.UNDERWRITER)
        assert_field_values(
            quoted, quoted_premium_delta_cents=expected_add_delta_cents
        )
        bound = fx.bind_endorsement(
            api, addition["id"], headers=users.SECOND_UNDERWRITER
        )
        assert_field_values(
            bound,
            status=EndorsementStatus.BOUND,
            premium_delta_cents=expected_add_delta_cents,
        )
        written_premium_cents += expected_add_delta_cents

        added_schedule = fx.fetch_schedule(api, bound["target_schedule_id"])
        assert_field_values(
            added_schedule,
            coverage_status=CoverageStatus.ACTIVE,
            agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
            hull_premium_cents=full_premium_cents,
        )
        # An identical hull to the credited one, priced higher purely because of when
        # its premium was computed.
        assert_field_values(
            fx.fetch_schedule(api, schedule_ids[4]),
            agreed_value_cents=added_schedule["agreed_value_cents"],
            hull_premium_cents=credited_premium_cents,
        )
        live_schedules, _meta = validate_list(
            api.list_schedules(
                headers=users.AUDITOR,
                params={
                    "policy_id": policy_id,
                    "coverage_status": CoverageStatus.ACTIVE,
                    "limit": 100,
                },
            )
        )
        assert sorted(row["hull_premium_cents"] for row in live_schedules) == sorted(
            [
                full_premium_cents,
                full_premium_cents,
                credited_premium_cents,
                full_premium_cents,
            ]
        )
        assert_field_values(
            fx.fetch_policy(api, policy_id),
            live_schedule_count=4,
            total_hull_sum_insured_cents=4 * PRIVATE_HULL_VALUE_CENTS,
            written_premium_cents=written_premium_cents,
        )
        assert ledger_signed_sum(fx.ledger_rows(api, policy_id)) == written_premium_cents


class TestDerivedFiguresAppearInTheMutatingResponse:
    """Derived figures are recomputed before the causing response is serialised."""

    @staticmethod
    def _two_hull_draft(api):
        """A draft fleet policy with two pending private hulls, ready to bind."""
        register = _private_fleet_register(api, 2)
        policy = _private_fleet_policy(api, register)
        schedule_ids = [
            _attach_private_hull(api, policy["id"], register, index)["id"]
            for index in range(2)
        ]
        return {
            "policy": policy,
            "policy_id": policy["id"],
            "schedule_ids": schedule_ids,
        }

    def test_the_bind_response_already_carries_the_re_derived_policy_aggregates(
        self, api
    ):
        """PRD §2.8: "There is no deferred or eventual settling of derived figures:
        when a request returns 200 or 201, every aggregate this document defines
        already reflects it."

        Design: Corner/consistency_model/corner_immediate_consistency_derived_fields_in_the_same_response
        """
        book = self._two_hull_draft(api)
        policy_id = book["policy_id"]
        hull_premium_cents = _private_hull_premium_cents(book["policy"], 2)
        expected_written_cents = 2 * hull_premium_cents

        bound = validate_unpaginated(
            api.bind_policy(policy_id, headers=users.UNDERWRITER)
        )
        assert_field_values(
            bound,
            status=PolicyStatus.BOUND,
            written_premium_cents=expected_written_cents,
            total_hull_sum_insured_cents=2 * PRIVATE_HULL_VALUE_CENTS,
            live_schedule_count=2,
            outstanding_reserve_cents=0,
            paid_hull_cents=0,
        )

        # A read afterwards recomputes nothing the write left undone.
        read_back = fx.fetch_policy(api, policy_id)
        assert_field_values(
            read_back,
            status=bound["status"],
            written_premium_cents=bound["written_premium_cents"],
            total_hull_sum_insured_cents=bound["total_hull_sum_insured_cents"],
            live_schedule_count=bound["live_schedule_count"],
            version=bound["version"],
        )
        assert_field_values(
            fx.fetch_schedule(api, book["schedule_ids"][0]),
            coverage_status=CoverageStatus.ACTIVE,
            hull_premium_cents=hull_premium_cents,
        )
        rows = fx.ledger_rows(api, policy_id)
        assert_ledger_row(
            rows_of_type(rows, TxnType.INITIAL_PREMIUM)[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=expected_written_cents,
            basis=TxnBasis.ANNUAL,
            effective_date=book["policy"]["effective_from"],
            policy_id=policy_id,
        )
        assert ledger_signed_sum(rows) == bound["written_premium_cents"]

    def test_the_value_revision_response_already_carries_the_re_derived_hull_figures(
        self, api
    ):
        """PRD §2.8: "Every cascade in this specification is applied immediately,
        inside the same request, before the response is produced."

        Design: Corner/consistency_model/corner_immediate_consistency_derived_fields_in_the_same_response
        """
        book = self._two_hull_draft(api)
        policy_id = book["policy_id"]
        schedule_id = book["schedule_ids"][0]
        policy = book["policy"]
        hull_premium_cents = _private_hull_premium_cents(policy, 2)
        rated_band = _logged_band(f.senior_pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        expected_rate_ppm = _rate_ppm(policy, UseClass.PRIVATE, rated_band)
        revised_premium_cents = c.annual_premium_cents(
            CONSISTENCY_REVISED_VALUE_CENTS,
            expected_rate_ppm,
            policy["policy_type"],
            live_schedule_count=2,
        )
        fx.bind_policy(api, policy_id)

        token = fx.fetch_schedule(api, schedule_id)["version"]
        revised = validate_unpaginated(
            api.revise_schedule_value(
                schedule_id,
                f.value_revision_payload(CONSISTENCY_REVISED_VALUE_CENTS, token),
                headers=users.UNDERWRITER,
            )
        )
        assert_field_values(
            revised,
            agreed_value_cents=CONSISTENCY_REVISED_VALUE_CENTS,
            rate_ppm=expected_rate_ppm,
            hull_premium_cents=revised_premium_cents,
        )

        expected_written_cents = (
            2 * hull_premium_cents + revised_premium_cents - hull_premium_cents
        )
        after = fx.fetch_policy(api, policy_id)
        assert_field_values(
            after,
            written_premium_cents=expected_written_cents,
            total_hull_sum_insured_cents=(
                PRIVATE_HULL_VALUE_CENTS + CONSISTENCY_REVISED_VALUE_CENTS
            ),
            live_schedule_count=2,
        )
        rows = fx.ledger_rows(api, policy_id)
        assert_ledger_row(
            rows_of_type(rows, TxnType.RERATE_ADJUSTMENT)[0],
            txn_type=TxnType.RERATE_ADJUSTMENT,
            amount_cents=revised_premium_cents - hull_premium_cents,
            basis=TxnBasis.ANNUAL,
            effective_date=f.CLOCK_BEFORE_INCEPTION,
            policy_id=policy_id,
        )
        assert ledger_signed_sum(rows) == after["written_premium_cents"]
