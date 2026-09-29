"""Dependencies that cross from one aggregate onto the state of another.

Settlement of a claim depends on the warranty dimension of the aircraft schedule
it names, and notification of a war-peril loss depends on a bound placement in a
separate war market.  Both gates are exercised from the refusing side and from
the accepting side, with the money and the structural effects re-derived from the
PRD's formulas.
"""

from test_helpers import (
    AdjustmentStatus,
    ApiErrorId,
    CooperationStatus,
    CoverageDecision,
    CoverageStatus,
    LossType,
    PerilsScope,
    PlacementStatus,
    SalvageStatus,
    SettlementBasis,
    TxnBasis,
    TxnType,
    WarrantyFinding,
    WarrantyStatus,
    assert_field_values,
    assert_ledger_row,
    assert_ledger_txn_types,
    ledger_signed_sum,
    validate_error,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

ASSESSED_AT = "2026-10-20T00:00:00Z"
BREACH_REASON = "Named pilot flew 40 days past the 365-day recurrency horizon"
WAR_LOSS_DESCRIPTION = "Hull destroyed by mortar fire while parked at a diversion field"


# ----------------------------------------------------------------------
# Derivations shared by the tests in this module
# ----------------------------------------------------------------------
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


def _expected_hull_premium(policy, pilot, use_class, agreed_value_cents, live_count):
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
# Setup for the warranty gate on settlement
# ----------------------------------------------------------------------
def _breached_total_loss_claim(api):
    """A reserved constructive-total-loss claim on a hull whose warranty is breached.

    The reserve is taken while cover is suspended, so the warranty rule rather
    than the claim-state rule is what a settlement attempt meets.
    """
    book = fx.bound_policy_with_hull(api, compliant_warranty=True)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    book = fx.total_loss_ready_claim(
        api,
        book,
        reserve_cents=book["schedule"]["agreed_value_cents"],
        loss_date=f.CLOCK_AFTER_LOSS,
        assessed_at=ASSESSED_AT,
    )
    fx.set_warranty(
        api, book["schedule_id"], WarrantyFinding.BREACH, breach_reason=BREACH_REASON
    )
    book["claim"] = fx.decide_coverage(
        api,
        book["claim_id"],
        decision=CoverageDecision.COVERED,
        reserve_cents=book["schedule"]["agreed_value_cents"],
    )
    return book


class TestSettlementGatedByScheduleWarranty:
    """Settlement crosses from the claim onto the schedule's warranty dimension."""

    def test_settlement_is_refused_while_the_named_hulls_warranty_is_breached(self, api):
        """PRD §3.10: "The schedule's `warranty_status` must not be `BREACHED`: a
        suspended hull is reservable but not payable, and an attempt is refused with
        `ERR_PILOT_WARRANTY_BREACHED` until a waiver or a verification finding lifts
        the breach."

        Design: Difficulty/cross_entity_state_dependency/claim_settlement_gated_by_schedule_warranty_status
        """
        book = _breached_total_loss_claim(api)
        schedule = fx.fetch_schedule(api, book["schedule_id"])
        assert_field_values(
            schedule,
            warranty_status=WarrantyStatus.BREACHED,
            coverage_status=CoverageStatus.SUSPENDED_WARRANTY,
        )
        claim = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            claim,
            adjustment_status=AdjustmentStatus.RESERVED,
            reserve_cents=schedule["agreed_value_cents"],
            salvage_status=SalvageStatus.TENDERED,
        )

        response = api.settle_claim(
            book["claim_id"],
            f.settlement_payload(SettlementBasis.DEPRECIATED_VALUE),
            headers=users.SECOND_CLAIMS_ADJUSTER,
        )
        validate_error(response, ApiErrorId.PILOT_WARRANTY_BREACHED)

        unchanged = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            unchanged,
            adjustment_status=AdjustmentStatus.RESERVED,
            settlement_basis=None,
            settlement_amount_cents=None,
        )

    def test_a_waiver_restores_cover_but_never_the_agreed_value_basis(self, api):
        """PRD §3.5: "A waiver restores cover but it does **not** restore the
        agreed-value basis: a claim on a `WAIVED` schedule can only ever be settled on
        depreciated, market-value terms, as §3.9 sets out."

        Design: Difficulty/cross_entity_state_dependency/claim_settlement_gated_by_schedule_warranty_status
        """
        book = _breached_total_loss_claim(api)

        waived = validate_unpaginated(
            api.record_warranty_finding(
                book["schedule_id"],
                f.warranty_finding_payload(WarrantyFinding.WAIVER),
                headers=users.UNDERWRITER,
            )
        )
        assert_field_values(
            waived,
            warranty_status=WarrantyStatus.WAIVED,
            coverage_status=CoverageStatus.ACTIVE,
            warranty_breach_reason=None,
        )

        refused = api.settle_claim(
            book["claim_id"],
            f.settlement_payload(SettlementBasis.AGREED_VALUE),
            headers=users.SECOND_CLAIMS_ADJUSTER,
        )
        validate_error(refused, ApiErrorId.SETTLEMENT_BASIS_NOT_PERMITTED)
        still_reserved = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            still_reserved, adjustment_status=AdjustmentStatus.RESERVED, settlement_basis=None
        )

    def test_settlement_after_a_waiver_pays_the_loss_year_depreciated_value(self, api):
        """PRD §3.10: "That depreciated value is derived exactly as in §3.1, but the
        reference year is the calendar year of the claim's `loss_date`, **not** the
        calendar year of the current clock and never the airframe's reported
        `current_depreciated_value_cents`."

        Design: Difficulty/cross_entity_state_dependency/claim_settlement_gated_by_schedule_warranty_status
        """
        book = _breached_total_loss_claim(api)
        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.WAIVER)

        schedule = fx.fetch_schedule(api, book["schedule_id"])
        claim_before = fx.fetch_claim(api, book["claim_id"])
        policy = fx.fetch_policy(api, book["policy_id"])
        aircraft = fx.fetch_aircraft(api, book["aircraft_id"])

        depreciated = c.depreciated_value_cents(
            aircraft["hull_new_value_cents"],
            aircraft["manufacture_year"],
            c.calendar_year_of(claim_before["loss_date"]),
        )
        gross = min(schedule["agreed_value_cents"], depreciated)
        expected_deductible = c.deductible_cents(gross, policy["hull_deductible_ppm"])
        expected_net = gross - expected_deductible

        settled = validate_unpaginated(
            api.settle_claim(
                book["claim_id"],
                f.settlement_payload(SettlementBasis.DEPRECIATED_VALUE),
                headers=users.SECOND_CLAIMS_ADJUSTER,
            )
        )
        assert_field_values(
            settled,
            adjustment_status=AdjustmentStatus.SETTLED,
            settlement_basis=SettlementBasis.DEPRECIATED_VALUE,
            settlement_amount_cents=expected_net,
            deductible_applied_cents=expected_deductible,
            reserve_cents=0,
        )

    def test_the_total_loss_takes_the_hull_off_risk_and_returns_unearned_premium(self, api):
        """PRD §2.9: "A policy's `written_premium_cents` is, at every instant, the plain
        signed sum of `amount_cents` over every ledger row whose `policy_id` is that
        policy."

        Design: Difficulty/cross_entity_state_dependency/claim_settlement_gated_by_schedule_warranty_status
        """
        book = _breached_total_loss_claim(api)
        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.WAIVER)

        policy_before = fx.fetch_policy(api, book["policy_id"])
        schedule = fx.fetch_schedule(api, book["schedule_id"])
        claim_before = fx.fetch_claim(api, book["claim_id"])
        aircraft = fx.fetch_aircraft(api, book["aircraft_id"])

        expected_initial = _expected_hull_premium(
            policy_before,
            book["pilot"],
            schedule["use_class"],
            schedule["agreed_value_cents"],
            live_count=1,
        )
        depreciated = c.depreciated_value_cents(
            aircraft["hull_new_value_cents"],
            aircraft["manufacture_year"],
            c.calendar_year_of(claim_before["loss_date"]),
        )
        gross = min(schedule["agreed_value_cents"], depreciated)
        expected_net = gross - c.deductible_cents(gross, policy_before["hull_deductible_ppm"])
        unexpired_days = c.whole_days_between(
            claim_before["loss_date"], policy_before["effective_to"]
        )
        expected_return = c.pro_rata_return_cents(
            expected_initial, unexpired_days, policy_before["term_days"]
        )

        fx.settle_claim(api, book["claim_id"], SettlementBasis.DEPRECIATED_VALUE)

        settled_schedule = fx.fetch_schedule(api, book["schedule_id"])
        assert_field_values(
            settled_schedule, coverage_status=CoverageStatus.TOTAL_LOSS_SETTLED
        )
        policy_after = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy_after,
            live_schedule_count=0,
            total_hull_sum_insured_cents=0,
            outstanding_reserve_cents=0,
            paid_hull_cents=expected_net,
            written_premium_cents=expected_initial - expected_return,
        )

        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER, params={"policy_id": book["policy_id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 2, (
            "the bind and the total-loss return are the only two ledger rows, "
            f"got {meta['total_count']}"
        )
        assert_ledger_txn_types(rows, [TxnType.INITIAL_PREMIUM, TxnType.SETTLEMENT_RETURN])
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=expected_initial,
            basis=TxnBasis.ANNUAL,
            effective_date=policy_before["effective_from"],
            policy_id=book["policy_id"],
        )
        assert rows[0]["endorsement_id"] is None, (
            "an INITIAL_PREMIUM row carries no endorsement_id"
        )
        assert_ledger_row(
            rows[1],
            txn_type=TxnType.SETTLEMENT_RETURN,
            amount_cents=-expected_return,
            basis=TxnBasis.PRO_RATA,
            policy_id=book["policy_id"],
        )
        assert rows[1]["endorsement_id"] is None, (
            "a SETTLEMENT_RETURN row carries no endorsement_id"
        )
        assert ledger_signed_sum(rows) == policy_after["written_premium_cents"], (
            "written_premium_cents is the signed sum of the whole ledger"
        )


# ----------------------------------------------------------------------
# Setup for the war-risk gate on notification
# ----------------------------------------------------------------------
def _bound_policy_and_open_market(api):
    """A bound worldwide policy, an open war market and no placement between them."""
    book = fx.bound_policy_with_hull(api, compliant_warranty=True)
    market_payload = f.war_market_payload()
    book["market"] = fx.make_war_market(api, market_payload)
    book["market_id"] = book["market"]["id"]
    book["market_payload"] = market_payload
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    book["policy"] = fx.fetch_policy(api, book["policy_id"])
    return book


def _war_peril_claim_payload(book):
    """The one war-peril notification both attempts in this group submit."""
    return f.claim_payload(
        book["policy_id"],
        book["schedule_id"],
        loss_date=f.CLOCK_AFTER_LOSS,
        loss_type=LossType.WAR_PERIL,
        loss_description=WAR_LOSS_DESCRIPTION,
    )


class TestWarPerilClaimGatedByBoundPlacement:
    """A war-peril notification crosses from the policy onto the war market."""

    def test_a_war_peril_notification_is_refused_without_a_bound_placement(self, api):
        """PRD §3.7: "A loss notified with `loss_type` `WAR_PERIL` requires a `BOUND`
        placement on the same policy whose closed coverage interval contains the claim's
        `loss_date`; without one, both notification and any later settlement of that
        claim are refused with `ERR_WAR_RISK_NOT_PLACED`."

        Design: Difficulty/cross_entity_state_dependency/war_peril_claim_gated_by_bound_market_placement
        """
        book = _bound_policy_and_open_market(api)

        response = api.create_claim(
            _war_peril_claim_payload(book), headers=users.BROKER
        )
        validate_error(response, ApiErrorId.WAR_RISK_NOT_PLACED)

        rows, meta = validate_list(
            api.list_claims(
                headers=users.UNDERWRITER,
                params={"policy_id": book["policy_id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused notification must leave no claim behind, got {meta['total_count']}"
        )
        assert rows == [], "the refused notification must leave no claim behind"

    def test_placing_the_war_line_commits_the_market_and_charges_the_loaded_premium(
        self, api
    ):
        """PRD §3.7: "Creating a placement appends one `WAR_RISK_PREMIUM` ledger row,
        updates the market's `committed_line_cents` and `available_line_cents`,
        re-derives the policy's `written_premium_cents` and advances the policy's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/war_peril_claim_gated_by_bound_market_placement
        """
        book = _bound_policy_and_open_market(api)
        policy_before = book["policy"]
        placement_payload = f.war_placement_payload(
            book["policy_id"], book["market_id"], policy_before["version"]
        )
        expected_premium = c.war_premium_cents(
            placement_payload["war_hull_line_cents"],
            placement_payload["perils_scope"],
            policy_before["territorial_limit_code"],
        )

        placement = validate_unpaginated(
            api.create_war_placement(placement_payload, headers=users.UNDERWRITER),
            expected_status=201,
        )
        assert_field_values(
            placement,
            status=PlacementStatus.BOUND,
            premium_cents=expected_premium,
            war_hull_line_cents=placement_payload["war_hull_line_cents"],
            perils_scope=PerilsScope.WAR_HIJACK,
            cancellation_reason=None,
        )

        market = fx.fetch_war_market(api, book["market_id"])
        aggregate = book["market_payload"]["aggregate_line_cents"]
        assert_field_values(
            market,
            committed_line_cents=placement_payload["war_hull_line_cents"],
            available_line_cents=aggregate - placement_payload["war_hull_line_cents"],
        )

        policy_after = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy_after,
            written_premium_cents=policy_before["written_premium_cents"] + expected_premium,
            version=policy_before["version"] + 1,
        )

    def test_the_identical_notification_is_accepted_once_the_slip_is_bound(self, api):
        """PRD §3.9: "A new claim starts with `adjustment_status` `NOTIFIED`,
        `salvage_status` `NONE`, `cooperation_status` `PENDING`, `reserve_cents` 0,
        `assessment_count` 0 and `ctl_flag` false."

        Design: Difficulty/cross_entity_state_dependency/war_peril_claim_gated_by_bound_market_placement
        """
        book = _bound_policy_and_open_market(api)
        payload = _war_peril_claim_payload(book)
        validate_error(
            api.create_claim(payload, headers=users.BROKER),
            ApiErrorId.WAR_RISK_NOT_PLACED,
        )

        fx.make_war_placement(
            api, book["policy_id"], book["market_id"], book["policy"]["version"]
        )

        claim = validate_unpaginated(
            api.create_claim(payload, headers=users.BROKER), expected_status=201
        )
        assert_field_values(
            claim,
            adjustment_status=AdjustmentStatus.NOTIFIED,
            salvage_status=SalvageStatus.NONE,
            cooperation_status=CooperationStatus.PENDING,
            reserve_cents=0,
            assessment_count=0,
            ctl_flag=False,
            loss_type=LossType.WAR_PERIL,
        )
