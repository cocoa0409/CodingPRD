"""Compensating actions that must undo a forward charge to the cent.

Two pairs are pinned by the specification: binding an endorsement against
voiding it, and creating a war-risk placement against cancelling it.  Each test
captures the figure before the forward action, performs the reversal, and
requires the figure back exactly — together with the compensating ledger row and
the undoing of the structural effect.
"""

from test_helpers import (
    AcquisitionSource,
    CoverageStatus,
    EndorsementStatus,
    EndorsementType,
    PerilsScope,
    PlacementStatus,
    TxnBasis,
    TxnType,
    UseClass,
    assert_field_values,
    assert_instants_equal,
    assert_ledger_row,
    assert_ledger_txn_types,
    ledger_signed_sum,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

VOID_REASON = "Aircraft purchase fell through before the endorsement attached"
CANCELLATION_REASON = "Slip re-broked to another syndicate before inception"


def _band_of(pilot, clock_utc):
    """The rating band a pilot's declared figures earn at a given clock."""
    return c.band_for_score(
        c.qualification_score(
            pilot["total_logged_hours"],
            pilot["hours_on_type"],
            pilot["instrument_rated"],
            pilot["license_type"],
            pilot["last_training_completed_at"],
            clock_utc,
        )
    )


def _expected_annual_premium(policy, pilot, use_class, agreed_value_cents, live_count):
    rate_ppm = c.rate_ppm_for(
        policy["base_hull_rate_ppm"],
        use_class,
        policy["territorial_limit_code"],
        _band_of(pilot, f.CLOCK_BEFORE_INCEPTION),
    )
    return c.annual_premium_cents(
        agreed_value_cents, rate_ppm, policy["policy_type"], live_count
    )


# ----------------------------------------------------------------------
# Pair one: binding an endorsement against voiding it
# ----------------------------------------------------------------------
def _bound_add_aircraft_endorsement(api):
    """A bound policy carrying a bound ADD_AIRCRAFT endorsement not yet incepted.

    The clock stays before the endorsement's effective date throughout, which is
    the window in which the endorsement may still be voided.
    """
    book = fx.bound_policy_with_hull(api, compliant_warranty=True)
    book["policy_after_bind"] = book["policy"]
    payload = f.add_aircraft_endorsement_payload(
        book["policy_id"], book["single_id"], book["senior_pilot_id"]
    )
    submitted = fx.make_endorsement(api, payload, headers=users.BROKER)
    quoted = fx.quote_endorsement(api, submitted["id"], headers=users.UNDERWRITER)
    bound = fx.bind_endorsement(api, submitted["id"], headers=users.SECOND_UNDERWRITER)
    book.update(
        {
            "endorsement_payload": payload,
            "endorsement": bound,
            "endorsement_id": bound["id"],
            "quoted": quoted,
        }
    )
    return book


def _expected_delta(book):
    """The pro-rata charge the ADD_AIRCRAFT branch computes, rounded up."""
    policy = book["policy_after_bind"]
    payload = book["endorsement_payload"]
    annual = _expected_annual_premium(
        policy,
        book["senior_pilot"],
        payload["new_use_class"],
        payload["new_agreed_value_cents"],
        live_count=2,
    )
    unexpired_days = c.whole_days_between(
        payload["effective_date"], policy["effective_to"]
    )
    return annual, c.pro_rata_charge_cents(
        annual, unexpired_days, policy["term_days"]
    )


class TestEndorsementVoidRestoresWrittenPremium:
    """Voiding a bound endorsement returns exactly what binding it charged."""

    def test_binding_the_endorsement_charges_the_pro_rata_delta_and_adds_the_hull(
        self, api
    ):
        """PRD §3.6: "Binding freezes `premium_delta_cents` from
        `quoted_premium_delta_cents` — the figure charged is the figure last quoted, not a
        fresh computation — and appends one `ENDORSEMENT_PREMIUM` ledger row with a
        `basis` of `PRO_RATA`, the endorsement's own identifier in `endorsement_id`, an
        `effective_date` equal to the endorsement's `effective_date`, and an
        `amount_cents` equal to `premium_delta_cents`."

        Design: Difficulty/compensating_invariant/endorsement_void_restores_policy_written_premium_exactly
        """
        book = _bound_add_aircraft_endorsement(api)
        policy_before = book["policy_after_bind"]
        annual, expected_delta = _expected_delta(book)
        endorsement = book["endorsement"]

        assert_field_values(
            endorsement,
            endorsement_type=EndorsementType.ADD_AIRCRAFT,
            status=EndorsementStatus.BOUND,
            quote_round=1,
            quoted_premium_delta_cents=expected_delta,
            premium_delta_cents=expected_delta,
            quoted_by_user_id=users.UNDERWRITER_ID,
        )

        rows = fx.ledger_rows(api, book["policy_id"])
        assert_ledger_txn_types(
            rows, [TxnType.INITIAL_PREMIUM, TxnType.ENDORSEMENT_PREMIUM]
        )
        assert_ledger_row(
            rows[1],
            txn_type=TxnType.ENDORSEMENT_PREMIUM,
            amount_cents=expected_delta,
            basis=TxnBasis.PRO_RATA,
            endorsement_id=book["endorsement_id"],
            effective_date=book["endorsement_payload"]["effective_date"],
            policy_id=book["policy_id"],
        )

        new_schedule = fx.fetch_schedule(api, endorsement["target_schedule_id"])
        assert_field_values(
            new_schedule,
            aircraft_id=book["single_id"],
            coverage_status=CoverageStatus.ACTIVE,
            acquisition_source=AcquisitionSource.SCHEDULED,
            use_class=UseClass.PRIVATE,
            hull_premium_cents=annual,
        )
        policy_after = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy_after,
            written_premium_cents=(
                policy_before["written_premium_cents"] + expected_delta
            ),
            live_schedule_count=2,
            total_hull_sum_insured_cents=(
                policy_before["total_hull_sum_insured_cents"]
                + book["endorsement_payload"]["new_agreed_value_cents"]
            ),
        )

    def test_voiding_appends_the_exact_negation_with_no_short_rate_penalty(self, api):
        """PRD §3.6: "It appends one `RETURN_PREMIUM` ledger row with a `basis` of
        `PRO_RATA`, the endorsement's identifier in `endorsement_id`, an `effective_date`
        of the current logical clock, and an `amount_cents` that is the exact negation of
        `premium_delta_cents` — no short-rate penalty applies, precisely because the
        endorsement never attached."

        Design: Difficulty/compensating_invariant/endorsement_void_restores_policy_written_premium_exactly
        """
        book = _bound_add_aircraft_endorsement(api)
        policy = book["policy_after_bind"]
        annual, expected_delta = _expected_delta(book)
        unexpired_days = c.whole_days_between(
            book["endorsement_payload"]["effective_date"], policy["effective_to"]
        )
        short_rated = c.floor_ppm(
            c.pro_rata_return_cents(annual, unexpired_days, policy["term_days"]),
            c.REMOVE_AIRCRAFT_RETURN_PPM,
        )

        voided = validate_unpaginated(
            api.void_endorsement(
                book["endorsement_id"],
                f.void_payload(void_reason=VOID_REASON),
                headers=users.UNDERWRITER,
            )
        )
        assert_field_values(
            voided, status=EndorsementStatus.VOID, void_reason=VOID_REASON
        )

        rows = fx.ledger_rows(api, book["policy_id"])
        assert_ledger_txn_types(
            rows,
            [
                TxnType.INITIAL_PREMIUM,
                TxnType.ENDORSEMENT_PREMIUM,
                TxnType.RETURN_PREMIUM,
            ],
        )
        assert_ledger_row(
            rows[2],
            txn_type=TxnType.RETURN_PREMIUM,
            amount_cents=-expected_delta,
            basis=TxnBasis.PRO_RATA,
            endorsement_id=book["endorsement_id"],
            effective_date=f.CLOCK_BEFORE_INCEPTION,
            policy_id=book["policy_id"],
        )
        assert rows[2]["amount_cents"] == -rows[1]["amount_cents"], (
            "the return must be the exact negation of the charge"
        )
        assert rows[2]["amount_cents"] != -short_rated, (
            "voiding must not apply the short-rate return factor of the "
            f"removal branch, which would return {short_rated}"
        )

    def test_voiding_restores_the_written_premium_and_the_hull_aggregates_exactly(
        self, api
    ):
        """PRD §2.9: "It has a corollary the implementation must honour exactly: for every
        forward action that charges premium there is a compensating action that returns
        it, and after the compensating action the policy's `written_premium_cents` equals
        its value before the forward action, to the cent."

        Design: Difficulty/compensating_invariant/endorsement_void_restores_policy_written_premium_exactly
        """
        book = _bound_add_aircraft_endorsement(api)
        policy_before_bind = book["policy_after_bind"]
        _, expected_delta = _expected_delta(book)
        policy_after_bind = fx.fetch_policy(api, book["policy_id"])
        assert policy_after_bind["written_premium_cents"] != (
            policy_before_bind["written_premium_cents"]
        ), "the endorsement bind must have moved the written premium first"

        fx.void_endorsement(api, book["endorsement_id"], void_reason=VOID_REASON)

        policy_after_void = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy_after_void,
            written_premium_cents=policy_before_bind["written_premium_cents"],
            total_hull_sum_insured_cents=(
                policy_before_bind["total_hull_sum_insured_cents"]
            ),
            live_schedule_count=policy_before_bind["live_schedule_count"],
            version=policy_before_bind["version"] + 2,
        )

        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER,
                params={"policy_id": book["policy_id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 3, (
            "the bind and the void each append one row to the two-row ledger, "
            f"got {meta['total_count']}"
        )
        assert ledger_signed_sum(rows) == policy_after_void["written_premium_cents"], (
            "written_premium_cents is the signed sum of the whole ledger"
        )
        assert expected_delta > 0, "the ADD_AIRCRAFT branch charges premium"

    def test_voiding_retracts_the_schedule_the_bind_created(self, api):
        """PRD §3.6: "Every structural effect is then undone: a schedule created by an
        `ADD_AIRCRAFT` bind moves to `REMOVED`, a schedule removed by a `REMOVE_AIRCRAFT`
        bind returns from `REMOVED` to `ACTIVE`, a revised `agreed_value_cents` or
        `use_class` is restored to its pre-bind value and the schedule is re-rated back to
        its pre-bind `hull_premium_cents`, and a `premises_liability_extension` or
        `product_liability_extension` flag returns to false."

        Design: Difficulty/compensating_invariant/endorsement_void_restores_policy_written_premium_exactly
        """
        book = _bound_add_aircraft_endorsement(api)
        new_schedule_id = book["endorsement"]["target_schedule_id"]
        assert new_schedule_id is not None, (
            "the bind stamps target_schedule_id with the schedule it creates"
        )

        fx.void_endorsement(api, book["endorsement_id"], void_reason=VOID_REASON)

        retracted = validate_unpaginated(
            api.get_schedule(new_schedule_id, headers=users.UNDERWRITER)
        )
        assert_field_values(
            retracted,
            id=new_schedule_id,
            coverage_status=CoverageStatus.REMOVED,
            aircraft_id=book["single_id"],
        )
        original = fx.fetch_schedule(api, book["schedule_id"])
        assert_field_values(original, coverage_status=CoverageStatus.ACTIVE)


# ----------------------------------------------------------------------
# Pair two: creating a war-risk placement against cancelling it
# ----------------------------------------------------------------------
def _placed_war_risk_on_a_bound_policy(api):
    """A bound policy whose war hull line is ceded into one market."""
    book = fx.bound_policy_with_hull(api, compliant_warranty=True)
    book["policy_before_placement"] = book["policy"]
    market_payload = f.war_market_payload()
    market = fx.make_war_market(api, market_payload)
    placement_payload = f.war_placement_payload(
        book["policy_id"], market["id"], book["policy"]["version"]
    )
    placement = validate_unpaginated(
        api.create_war_placement(placement_payload, headers=users.UNDERWRITER),
        expected_status=201,
    )
    book.update(
        {
            "market_id": market["id"],
            "aggregate_line_cents": market_payload["aggregate_line_cents"],
            "placement": placement,
            "placement_id": placement["id"],
            "placement_payload": placement_payload,
            "expected_war_premium": c.war_premium_cents(
                placement_payload["war_hull_line_cents"],
                placement_payload["perils_scope"],
                book["policy"]["territorial_limit_code"],
            ),
        }
    )
    return book


class TestWarPlacementCancellationReleasesTheLine:
    """Cancelling a placement returns exactly what creating it charged."""

    def test_cancelling_releases_the_committed_market_line_exactly(self, api):
        """PRD §3.7: "Cancelling releases the market line exactly —
        `committed_line_cents` falls by this placement's `war_hull_line_cents` and
        `available_line_cents` returns to its precise pre-placement figure — appends one
        `RETURN_PREMIUM` ledger row with a `basis` of `PRO_RATA`, a null `endorsement_id`
        and an `amount_cents` that is the exact negation of `premium_cents`, re-derives the
        policy's `written_premium_cents` and advances the policy's `version`."

        Design: Difficulty/compensating_invariant/war_placement_cancellation_releases_market_line_exactly
        """
        book = _placed_war_risk_on_a_bound_policy(api)
        committed = fx.fetch_war_market(api, book["market_id"])
        assert_field_values(
            committed,
            committed_line_cents=book["placement_payload"]["war_hull_line_cents"],
            available_line_cents=(
                book["aggregate_line_cents"]
                - book["placement_payload"]["war_hull_line_cents"]
            ),
        )

        cancelled = validate_unpaginated(
            api.cancel_war_placement(
                book["placement_id"],
                f.cancellation_payload(cancellation_reason=CANCELLATION_REASON),
                headers=users.UNDERWRITER,
            )
        )
        assert_field_values(
            cancelled,
            status=PlacementStatus.CANCELLED,
            cancellation_reason=CANCELLATION_REASON,
            premium_cents=book["expected_war_premium"],
            war_hull_line_cents=book["placement_payload"]["war_hull_line_cents"],
            perils_scope=PerilsScope.WAR_HIJACK,
        )

        released = fx.fetch_war_market(api, book["market_id"])
        assert_field_values(
            released,
            committed_line_cents=0,
            available_line_cents=book["aggregate_line_cents"],
        )

    def test_cancelling_returns_the_war_premium_to_the_cent(self, api):
        """PRD §2.9: "Two such pairs are pinned by this specification — binding an
        endorsement against voiding that endorsement, and creating a war-risk placement
        against cancelling that placement."

        Design: Difficulty/compensating_invariant/war_placement_cancellation_releases_market_line_exactly
        """
        book = _placed_war_risk_on_a_bound_policy(api)
        policy_before = book["policy_before_placement"]
        policy_after_placement = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy_after_placement,
            written_premium_cents=(
                policy_before["written_premium_cents"] + book["expected_war_premium"]
            ),
            version=policy_before["version"] + 1,
        )

        fx.cancel_war_placement(
            api, book["placement_id"], cancellation_reason=CANCELLATION_REASON
        )

        policy_after_cancel = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy_after_cancel,
            written_premium_cents=policy_before["written_premium_cents"],
            version=policy_before["version"] + 2,
        )

        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER,
                params={"policy_id": book["policy_id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 3, (
            "the placement and its cancellation each append one row to the bind's "
            f"single row, got {meta['total_count']}"
        )
        assert_ledger_txn_types(
            rows,
            [
                TxnType.INITIAL_PREMIUM,
                TxnType.WAR_RISK_PREMIUM,
                TxnType.RETURN_PREMIUM,
            ],
        )
        assert_ledger_row(
            rows[1],
            txn_type=TxnType.WAR_RISK_PREMIUM,
            amount_cents=book["expected_war_premium"],
            policy_id=book["policy_id"],
        )
        assert rows[1]["endorsement_id"] is None, (
            "a WAR_RISK_PREMIUM row carries no endorsement_id"
        )
        assert_ledger_row(
            rows[2],
            txn_type=TxnType.RETURN_PREMIUM,
            amount_cents=-book["expected_war_premium"],
            basis=TxnBasis.PRO_RATA,
            policy_id=book["policy_id"],
        )
        assert rows[2]["endorsement_id"] is None, (
            "a cancellation return arises from no endorsement, so endorsement_id is null"
        )
        assert ledger_signed_sum(rows) == policy_after_cancel["written_premium_cents"], (
            "written_premium_cents is the signed sum of the whole ledger"
        )

    def test_the_released_capacity_admits_the_whole_aggregate_on_the_same_window(
        self, api
    ):
        """PRD §3.7: "A market's `committed_line_cents` starts at 0 and is always the sum
        of `war_hull_line_cents` over the placements on that market whose `status` is
        `BOUND`, with cancelled placements excluded; its `available_line_cents` starts
        equal to `aggregate_line_cents` and is always `aggregate_line_cents` less
        `committed_line_cents`."

        Design: Difficulty/compensating_invariant/war_placement_cancellation_releases_market_line_exactly
        """
        book = _placed_war_risk_on_a_bound_policy(api)
        policy_before = book["policy_before_placement"]
        fx.cancel_war_placement(
            api, book["placement_id"], cancellation_reason=CANCELLATION_REASON
        )
        policy_after_cancel = fx.fetch_policy(api, book["policy_id"])

        replacement_payload = f.war_placement_payload(
            book["policy_id"],
            book["market_id"],
            policy_after_cancel["version"],
            war_hull_line_cents=book["aggregate_line_cents"],
        )
        expected_premium = c.war_premium_cents(
            book["aggregate_line_cents"],
            replacement_payload["perils_scope"],
            policy_before["territorial_limit_code"],
        )

        replacement = validate_unpaginated(
            api.create_war_placement(replacement_payload, headers=users.UNDERWRITER),
            expected_status=201,
        )
        assert_field_values(
            replacement,
            status=PlacementStatus.BOUND,
            war_hull_line_cents=book["aggregate_line_cents"],
            premium_cents=expected_premium,
        )
        assert_instants_equal(
            replacement["coverage_from"],
            book["placement_payload"]["coverage_from"],
            "coverage_from",
        )
        assert_instants_equal(
            replacement["coverage_to"],
            book["placement_payload"]["coverage_to"],
            "coverage_to",
        )

        market = fx.fetch_war_market(api, book["market_id"])
        assert_field_values(
            market,
            committed_line_cents=book["aggregate_line_cents"],
            available_line_cents=0,
        )
        policy_after = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy_after,
            written_premium_cents=(
                policy_before["written_premium_cents"] + expected_premium
            ),
        )
