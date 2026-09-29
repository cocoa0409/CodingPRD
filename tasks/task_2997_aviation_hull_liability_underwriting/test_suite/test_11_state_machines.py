"""State machine behaviour: initial states, guarded transitions and terminal locks.

Every resource in this API carries its own lifecycle, and several carry two
independent dimensions at once.  The tests here drive those lifecycles through
the public endpoints and check the state each transition leaves behind, the
preconditions that refuse a transition, and the terminal states that refuse
every further trigger.
"""

import pytest

from test_helpers import (
    AcquisitionSource,
    AdjustmentStatus,
    ApiErrorId,
    CooperationStatus,
    CoverageDecision,
    CoverageStatus,
    DeclarationStatus,
    EndorsementStatus,
    EndorsementType,
    LossType,
    PerilsScope,
    PlacementStatus,
    PolicyStatus,
    SalvageAction,
    SalvageStatus,
    SettlementBasis,
    TerritorialLimit,
    TerritoryCode,
    TxnBasis,
    TxnType,
    UseClass,
    WarrantyStatus,
    assert_field_values,
    assert_ledger_row,
    assert_no_ledger_row_of_type,
    ledger_signed_sum,
    validate_error,
    validate_success,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# The clock instants these tests park the logical clock at, all full instants.
CLOCK_AT_EXPIRY = "2027-09-01T00:00:00Z"
CLOCK_PAST_EXPIRY = "2027-10-01T00:00:00Z"
CLOCK_DECLARATION_MONTH_END = "2026-11-05T00:00:00Z"
LOSS_ASSESSED_AT = "2026-10-20T00:00:00Z"
IN_PERIOD_ACQUISITION_FROM = "2026-10-01T00:00:00Z"
OUT_OF_PERIOD_ACQUISITION_FROM = "2026-12-01T00:00:00Z"
DECLARATION_PERIOD_FROM = "2026-10-01T00:00:00Z"
DECLARATION_PERIOD_TO = "2026-10-31T00:00:00Z"
COVERING_WINDOW_FROM = "2026-10-02T00:00:00Z"
COVERING_WINDOW_TO = "2027-08-01T00:00:00Z"
EARLY_WINDOW_FROM = f.POLICY_EFFECTIVE_FROM
EARLY_WINDOW_TO = "2026-10-01T00:00:00Z"


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


class TestClaimNotificationInitialStates:
    """A freshly notified claim starts at the bottom of every dimension it owns."""

    def test_notification_starts_the_claim_on_its_declared_initial_states(self, api):
        """PRD §3.9: "A new claim starts with `adjustment_status` `NOTIFIED`,
        `salvage_status` `NONE`, `cooperation_status` `PENDING`, `reserve_cents` 0,
        `assessment_count` 0 and `ctl_flag` false."

        Design: Corner/state_machines/corner_initial_states_on_all_three_parallel_dimensions
        """
        book = fx.bound_policy_with_hull(api)
        fx.advance_clock(api, f.CLOCK_LATE_TERM)

        response = api.create_claim(
            f.claim_payload(
                book["policy_id"], book["schedule_id"], loss_date=f.CLOCK_AFTER_LOSS
            ),
            headers=users.BROKER,
        )

        claim = validate_unpaginated(response, expected_status=201)
        assert_field_values(
            claim,
            adjustment_status=AdjustmentStatus.NOTIFIED,
            salvage_status=SalvageStatus.NONE,
            cooperation_status=CooperationStatus.PENDING,
            reserve_cents=0,
            assessment_count=0,
            ctl_flag=False,
            ctl_ratio_ppm=None,
            settlement_basis=None,
            settlement_amount_cents=None,
            deductible_applied_cents=None,
            salvage_proceeds_cents=0,
            coverage_decided_by_user_id=None,
            denial_reason=None,
        )

    def test_notification_moves_neither_schedule_dimension_nor_the_policy_aggregates(
        self, api
    ):
        """PRD §2.9: "`outstanding_reserve_cents` is the sum of `reserve_cents` over
        the claims on the policy whose `adjustment_status` is `RESERVED`, and no
        other claims."

        Design: Corner/state_machines/corner_initial_states_on_all_three_parallel_dimensions
        """
        book = fx.bound_policy_with_hull(api)
        fx.advance_clock(api, f.CLOCK_LATE_TERM)
        fx.make_claim(
            api,
            book["policy_id"],
            book["schedule_id"],
            headers=users.BROKER,
            loss_date=f.CLOCK_AFTER_LOSS,
        )

        schedule = fx.fetch_schedule(api, book["schedule_id"])
        policy = fx.fetch_policy(api, book["policy_id"])

        assert_field_values(
            schedule,
            coverage_status=CoverageStatus.ACTIVE,
            warranty_status=WarrantyStatus.PENDING_EVIDENCE,
        )
        assert_field_values(
            policy,
            status=PolicyStatus.BOUND,
            outstanding_reserve_cents=0,
            paid_hull_cents=0,
        )


class TestPolicyBindTransition:
    """Binding activates the scheduled hulls and writes the opening premium."""

    def test_bind_activates_the_pending_hull_and_re_derives_the_aggregates(self, api):
        """PRD §3.3: "First, every aircraft schedule on the policy whose
        `coverage_status` is `PENDING` **and** whose `acquisition_source` is
        `SCHEDULED` advances `PENDING → ACTIVE`; where such a schedule's
        `warranty_status` is already `BREACHED`, the system transition
        `ACTIVE → SUSPENDED_WARRANTY` follows immediately in the same request."

        Design: Corner/state_machines/corner_policy_bind_transition_activates_hulls_and_writes_ledger
        """
        book = fx.draft_policy_with_hull(api)
        agreed_value_cents = book["schedule"]["agreed_value_cents"]
        band = _logged_band(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        expected_rate_ppm = _rate_ppm(book["policy"], UseClass.INSTRUCTIONAL, band)
        expected_premium_cents = c.annual_premium_cents(
            agreed_value_cents,
            expected_rate_ppm,
            book["policy"]["policy_type"],
            live_schedule_count=1,
        )
        version_before = fx.fetch_policy(api, book["policy_id"])["version"]

        response = api.bind_policy(book["policy_id"], headers=users.UNDERWRITER)

        policy = validate_unpaginated(response)
        assert_field_values(
            policy,
            status=PolicyStatus.BOUND,
            written_premium_cents=expected_premium_cents,
            total_hull_sum_insured_cents=agreed_value_cents,
            live_schedule_count=1,
        )
        assert policy["version"] == version_before + 1, (
            f"binding advances the policy version by one, "
            f"got {version_before} -> {policy['version']}"
        )
        schedule = fx.fetch_schedule(api, book["schedule_id"])
        assert_field_values(
            schedule,
            coverage_status=CoverageStatus.ACTIVE,
            rated_pilot_band=band,
            rate_ppm=expected_rate_ppm,
            hull_premium_cents=expected_premium_cents,
        )

    def test_bind_appends_exactly_one_annual_initial_premium_row(self, api):
        """PRD §3.3: "Second, one `INITIAL_PREMIUM` ledger row is appended with a
        `basis` of `ANNUAL`, a null `endorsement_id`, an `effective_date` equal to
        the policy's `effective_from`, and an `amount_cents` equal to the sum of
        `hull_premium_cents` over the schedules just activated; schedules are
        processed in `created_at` ascending order."

        Design: Corner/state_machines/corner_policy_bind_transition_activates_hulls_and_writes_ledger
        """
        book = fx.draft_policy_with_hull(api)
        band = _logged_band(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        expected_premium_cents = c.annual_premium_cents(
            book["schedule"]["agreed_value_cents"],
            _rate_ppm(book["policy"], UseClass.INSTRUCTIONAL, band),
            book["policy"]["policy_type"],
            live_schedule_count=1,
        )

        fx.bind_policy(api, book["policy_id"])

        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 1, f"binding writes a single ledger row, got {len(rows)}"
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=expected_premium_cents,
            basis=TxnBasis.ANNUAL,
            effective_date=f.POLICY_EFFECTIVE_FROM,
            policy_id=book["policy_id"],
        )
        assert rows[0]["endorsement_id"] is None, (
            "the opening premium row carries no endorsement id"
        )


class TestBindPreconditionOnPendingSchedules:
    """A policy with nothing to insure cannot leave `DRAFT`."""

    def test_bind_against_a_policy_with_no_schedules_is_refused(self, api):
        """PRD §3.3: "At least one aircraft schedule on the policy must be sitting in
        `coverage_status` `PENDING`, because a policy with nothing to insure cannot be
        bound; a bind attempt against an empty policy is refused with
        `ERR_POLICY_HAS_NO_SCHEDULES`."

        Design: Corner/state_machines/corner_bind_precondition_requires_at_least_one_pending_schedule
        """
        book = fx.registered_book(api)
        policy = fx.make_policy(api, book["operator_id"])

        response = api.bind_policy(policy["id"], headers=users.UNDERWRITER)

        validate_error(response, ApiErrorId.POLICY_HAS_NO_SCHEDULES)
        unchanged = fx.fetch_policy(api, policy["id"])
        assert_field_values(
            unchanged,
            status=PolicyStatus.DRAFT,
            written_premium_cents=0,
            total_hull_sum_insured_cents=0,
            live_schedule_count=0,
        )
        assert fx.ledger_rows(api, policy["id"]) == [], (
            "a refused bind must not write to the append-only ledger"
        )

    def test_the_same_bind_succeeds_once_one_pending_hull_is_attached(self, api):
        """PRD §3.3: "At least one aircraft schedule on the policy must be sitting in
        `coverage_status` `PENDING`, because a policy with nothing to insure cannot be
        bound; a bind attempt against an empty policy is refused with
        `ERR_POLICY_HAS_NO_SCHEDULES`."

        Design: Corner/state_machines/corner_bind_precondition_requires_at_least_one_pending_schedule
        """
        book = fx.registered_book(api)
        policy = fx.make_policy(api, book["operator_id"])
        validate_error(
            api.bind_policy(policy["id"], headers=users.UNDERWRITER),
            ApiErrorId.POLICY_HAS_NO_SCHEDULES,
        )

        schedule = fx.make_schedule(
            api, policy["id"], book["aircraft_id"], book["pilot_id"]
        )
        response = api.bind_policy(policy["id"], headers=users.UNDERWRITER)

        bound = validate_unpaginated(response)
        band = _logged_band(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        expected_premium_cents = c.annual_premium_cents(
            schedule["agreed_value_cents"],
            _rate_ppm(policy, UseClass.INSTRUCTIONAL, band),
            policy["policy_type"],
            live_schedule_count=1,
        )
        assert_field_values(
            bound,
            status=PolicyStatus.BOUND,
            written_premium_cents=expected_premium_cents,
            live_schedule_count=1,
        )
        assert fx.fetch_schedule(api, schedule["id"])["coverage_status"] == (
            CoverageStatus.ACTIVE
        ), "the pending hull that satisfied the precondition goes on risk"


def _denied_claim_book(api) -> dict:
    """A bound policy carrying one claim whose coverage decision was a denial."""
    book = fx.bound_policy_with_hull(api)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    book = fx.investigated_claim(
        api,
        book,
        loss_date=f.CLOCK_AFTER_LOSS,
        loss_type=LossType.TOTAL_LOSS,
    )
    book["claim"] = fx.decide_coverage(
        api, book["claim_id"], decision=CoverageDecision.DENIED
    )
    return book


DENIED_CLAIM_TRIGGERS = {
    "investigation": lambda api, book: api.record_investigation(
        book["claim_id"], f.investigation_payload(), headers=users.CLAIMS_ADJUSTER
    ),
    "damage_assessment": lambda api, book: api.create_damage_assessment(
        f.damage_assessment_payload(book["claim_id"], assessed_at=LOSS_ASSESSED_AT),
        headers=users.CLAIMS_ADJUSTER,
    ),
    "coverage_decision": lambda api, book: api.decide_coverage(
        book["claim_id"],
        f.coverage_decision_payload(decision=CoverageDecision.COVERED),
        headers=users.SECOND_CLAIMS_ADJUSTER,
    ),
    "salvage_disposition": lambda api, book: api.dispose_salvage(
        book["claim_id"],
        f.salvage_disposition_payload(SalvageAction.RETAIN),
        headers=users.CLAIMS_ADJUSTER,
    ),
    "settlement": lambda api, book: api.settle_claim(
        book["claim_id"],
        f.settlement_payload(SettlementBasis.AGREED_VALUE),
        headers=users.SECOND_CLAIMS_ADJUSTER,
    ),
}


class TestDeniedClaimIsTerminal:
    """`DENIED` closes the claim file to every further adjustment action."""

    @pytest.mark.parametrize("trigger_name", sorted(DENIED_CLAIM_TRIGGERS))
    def test_a_denied_claim_refuses_every_further_action(self, api, trigger_name):
        """PRD §3.9: "The adjustment dimension is owned entirely by the
        `ClaimsAdjuster` role, and `SETTLED` and `DENIED` are its terminal states: a
        claim that has reached either refuses every further action with
        `ERR_CLAIM_INVALID_STATE`."

        Design: Corner/state_machines/corner_settlement_refused_from_denied_claim_state
        """
        book = _denied_claim_book(api)
        assert book["claim"]["adjustment_status"] == AdjustmentStatus.DENIED

        response = DENIED_CLAIM_TRIGGERS[trigger_name](api, book)

        validate_error(response, ApiErrorId.CLAIM_INVALID_STATE)

    def test_a_refused_settlement_pays_nothing_and_leaves_the_hull_on_risk(self, api):
        """PRD §2.9: "`paid_hull_cents` is the sum of `settlement_amount_cents` over
        the claims on the policy whose `adjustment_status` is `SETTLED` and whose
        `loss_type` is either `HULL_DAMAGE` or `TOTAL_LOSS`."

        Design: Corner/state_machines/corner_settlement_refused_from_denied_claim_state
        """
        book = _denied_claim_book(api)

        validate_error(
            api.settle_claim(
                book["claim_id"],
                f.settlement_payload(SettlementBasis.AGREED_VALUE),
                headers=users.SECOND_CLAIMS_ADJUSTER,
            ),
            ApiErrorId.CLAIM_INVALID_STATE,
        )

        claim = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            claim,
            adjustment_status=AdjustmentStatus.DENIED,
            salvage_status=SalvageStatus.NONE,
            settlement_basis=None,
            settlement_amount_cents=None,
            deductible_applied_cents=None,
        )
        assert fx.fetch_schedule(api, book["schedule_id"])["coverage_status"] == (
            CoverageStatus.ACTIVE
        ), "a refused settlement leaves the hull on risk"
        policy = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(policy, paid_hull_cents=0, outstanding_reserve_cents=0)
        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 1, f"no settlement row may be written, got {len(rows)} rows"
        assert rows[0]["txn_type"] == TxnType.INITIAL_PREMIUM


VOID_REASON = "Broker withdrew the extension request"
SECOND_VOID_REASON = "Duplicate withdrawal filed by the broker"

VOID_ENDORSEMENT_TRIGGERS = {
    "quote": lambda api, endorsement_id: api.quote_endorsement(
        endorsement_id, headers=users.UNDERWRITER
    ),
    "referral": lambda api, endorsement_id: api.refer_endorsement(
        endorsement_id, f.referral_payload(), headers=users.UNDERWRITER
    ),
    "bind": lambda api, endorsement_id: api.bind_endorsement(
        endorsement_id, headers=users.SECOND_UNDERWRITER
    ),
    "second_void": lambda api, endorsement_id: api.void_endorsement(
        endorsement_id,
        f.void_payload(void_reason=SECOND_VOID_REASON),
        headers=users.UNDERWRITER,
    ),
}


class TestVoidEndorsementIsTerminal:
    """`VOID` closes the endorsement to quotation, referral, binding and voiding."""

    @pytest.mark.parametrize("trigger_name", sorted(VOID_ENDORSEMENT_TRIGGERS))
    def test_a_void_endorsement_refuses_every_further_trigger(self, api, trigger_name):
        """PRD §3.6: "Voiding is reserved to an `Underwriter`, requires a
        `void_reason`, and reaches `VOID` — which is terminal — from `SUBMITTED`, from
        `QUOTED` and from `BOUND`."

        Design: Corner/state_machines/corner_void_endorsement_is_locked_against_every_further_trigger
        """
        book = fx.bound_policy_with_hull(api)
        endorsement = fx.make_endorsement(
            api,
            f.territory_extension_endorsement_payload(
                book["policy_id"], territory_code=TerritoryCode.CONTINENTAL
            ),
        )
        voided = fx.void_endorsement(api, endorsement["id"], void_reason=VOID_REASON)
        assert voided["status"] == EndorsementStatus.VOID

        response = VOID_ENDORSEMENT_TRIGGERS[trigger_name](api, endorsement["id"])

        validate_error(response, ApiErrorId.ENDORSEMENT_INVALID_STATE)

    def test_the_refused_triggers_leave_the_endorsement_and_the_policy_untouched(
        self, api
    ):
        """PRD §3.6: "`TERRITORY_EXTENSION` rewrites the policy's
        `territorial_limit_code` to the supplied `territory_code` when that code is
        `CONTINENTAL` or `WORLDWIDE`; a `WAR_ZONE_A` extension leaves
        `territorial_limit_code` untouched, because war zone cover is carried by the
        separate placement rather than by the hull slip's territorial limit."

        Design: Corner/state_machines/corner_void_endorsement_is_locked_against_every_further_trigger
        """
        book = fx.bound_policy_with_hull(api)
        endorsement = fx.make_endorsement(
            api,
            f.territory_extension_endorsement_payload(
                book["policy_id"], territory_code=TerritoryCode.CONTINENTAL
            ),
        )
        fx.void_endorsement(api, endorsement["id"], void_reason=VOID_REASON)
        for trigger in sorted(VOID_ENDORSEMENT_TRIGGERS):
            validate_error(
                VOID_ENDORSEMENT_TRIGGERS[trigger](api, endorsement["id"]),
                ApiErrorId.ENDORSEMENT_INVALID_STATE,
            )

        unchanged = fx.fetch_endorsement(api, endorsement["id"])
        assert_field_values(
            unchanged,
            status=EndorsementStatus.VOID,
            endorsement_type=EndorsementType.TERRITORY_EXTENSION,
            territory_code=TerritoryCode.CONTINENTAL,
            quote_round=0,
            quoted_premium_delta_cents=None,
            premium_delta_cents=None,
            quoted_by_user_id=None,
            void_reason=VOID_REASON,
        )
        policy = fx.fetch_policy(api, book["policy_id"])
        assert policy["territorial_limit_code"] == TerritorialLimit.WORLDWIDE, (
            "a refused bind of a territory extension must not rewrite the limit"
        )
        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 1, (
            f"a void endorsement writes no premium row, got {len(rows)} rows"
        )
        assert rows[0]["txn_type"] == TxnType.INITIAL_PREMIUM


WAR_HULL_LINE_CENTS = 600000000
FIRST_CANCELLATION_REASON = "Slip re-broked to another syndicate"


def _cancelled_placement_book(api) -> dict:
    """A draft policy whose war-risk placement has already been cancelled once."""
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"])
    market = fx.make_war_market(api)
    placement = fx.make_war_placement(
        api,
        policy["id"],
        market["id"],
        fx.fetch_policy(api, policy["id"])["version"],
        war_hull_line_cents=WAR_HULL_LINE_CENTS,
        perils_scope=PerilsScope.WAR_HIJACK,
    )
    book.update(
        {
            "policy": policy,
            "policy_id": policy["id"],
            "market": market,
            "market_id": market["id"],
            "placement": fx.cancel_war_placement(
                api, placement["id"], cancellation_reason=FIRST_CANCELLATION_REASON
            ),
            "placement_id": placement["id"],
        }
    )
    return book


class TestSecondPlacementCancellation:
    """`CANCELLED` is terminal, so the compensating action never replays."""

    def test_a_second_cancellation_is_refused_and_changes_nothing(self, api):
        """PRD §3.7: "It requires a `cancellation_reason`, which is null while the
        placement is `BOUND`, and moves the placement `BOUND → CANCELLED`, which is
        terminal; a second cancellation is refused with `ERR_PLACEMENT_NOT_BOUND`."

        Design: Corner/state_machines/corner_second_placement_cancellation_is_refused_not_replayed
        """
        book = _cancelled_placement_book(api)
        expected_premium_cents = c.war_premium_cents(
            WAR_HULL_LINE_CENTS,
            PerilsScope.WAR_HIJACK,
            book["policy"]["territorial_limit_code"],
        )
        assert book["placement"]["status"] == PlacementStatus.CANCELLED

        response = api.cancel_war_placement(
            book["placement_id"],
            f.cancellation_payload(cancellation_reason="Second cancellation attempt"),
            headers=users.UNDERWRITER,
        )

        validate_error(response, ApiErrorId.PLACEMENT_NOT_BOUND)
        unchanged = fx.fetch_war_placement(api, book["placement_id"])
        assert_field_values(
            unchanged,
            status=PlacementStatus.CANCELLED,
            premium_cents=expected_premium_cents,
            cancellation_reason=FIRST_CANCELLATION_REASON,
            war_hull_line_cents=WAR_HULL_LINE_CENTS,
        )

    def test_the_market_line_and_the_ledger_are_released_exactly_once(self, api):
        """PRD §3.7: "Cancelling releases the market line exactly —
        `committed_line_cents` falls by this placement's `war_hull_line_cents` and
        `available_line_cents` returns to its precise pre-placement figure — appends
        one `RETURN_PREMIUM` ledger row with a `basis` of `PRO_RATA`, a null
        `endorsement_id` and an `amount_cents` that is the exact negation of
        `premium_cents`, re-derives the policy's `written_premium_cents` and advances
        the policy's `version`."

        Design: Corner/state_machines/corner_second_placement_cancellation_is_refused_not_replayed
        """
        book = _cancelled_placement_book(api)
        expected_premium_cents = c.war_premium_cents(
            WAR_HULL_LINE_CENTS,
            PerilsScope.WAR_HIJACK,
            book["policy"]["territorial_limit_code"],
        )
        aggregate_line_cents = book["market"]["aggregate_line_cents"]

        validate_error(
            api.cancel_war_placement(
                book["placement_id"],
                f.cancellation_payload(),
                headers=users.UNDERWRITER,
            ),
            ApiErrorId.PLACEMENT_NOT_BOUND,
        )

        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 2, (
            f"one charge and one release only, got {len(rows)} ledger rows"
        )
        assert_ledger_row(
            rows[0], txn_type=TxnType.WAR_RISK_PREMIUM, amount_cents=expected_premium_cents
        )
        assert_ledger_row(
            rows[1],
            txn_type=TxnType.RETURN_PREMIUM,
            amount_cents=-expected_premium_cents,
            basis=TxnBasis.PRO_RATA,
        )
        assert rows[1]["endorsement_id"] is None
        assert ledger_signed_sum(rows) == 0, "the two rows must cancel exactly"
        market = fx.fetch_war_market(api, book["market_id"])
        assert_field_values(
            market,
            committed_line_cents=0,
            available_line_cents=aggregate_line_cents,
        )
        assert fx.fetch_policy(api, book["policy_id"])["written_premium_cents"] == 0


EARLY_WAR_LINE_CENTS = 400000000
COVERING_WAR_LINE_CENTS = 500000000


def _territory_extension_delta_cents(
    policy: dict, territory_code: str, effective_date: str
) -> int:
    """The flat annual territory charge apportioned over the unexpired days."""
    unexpired_days = c.whole_days_between(effective_date, policy["effective_to"])
    return c.pro_rata_charge_cents(
        c.TERRITORY_EXTENSION_ANNUAL_CENTS[territory_code],
        unexpired_days,
        policy["term_days"],
    )


def _quoted_war_zone_extension(api) -> dict:
    """A bound policy with a war placement that expires before the extension bites."""
    book = fx.bound_policy_with_hull(api)
    market = fx.make_war_market(api)
    fx.make_war_placement(
        api,
        book["policy_id"],
        market["id"],
        fx.fetch_policy(api, book["policy_id"])["version"],
        war_hull_line_cents=EARLY_WAR_LINE_CENTS,
        perils_scope=PerilsScope.WAR_HIJACK,
        coverage_from=EARLY_WINDOW_FROM,
        coverage_to=EARLY_WINDOW_TO,
    )
    endorsement = fx.quoted_endorsement(
        api,
        f.territory_extension_endorsement_payload(
            book["policy_id"],
            territory_code=TerritoryCode.WAR_ZONE_A,
            effective_date=f.CLOCK_LATE_TERM,
        ),
    )
    book.update(
        {
            "market": market,
            "market_id": market["id"],
            "endorsement": endorsement,
            "endorsement_id": endorsement["id"],
            "policy": fx.fetch_policy(api, book["policy_id"]),
        }
    )
    return book


class TestWarZoneExtensionBindGuard:
    """A war zone extension binds only while a placement actually covers the date."""

    def test_the_bind_is_refused_when_no_bound_placement_covers_the_effective_date(
        self, api
    ):
        """PRD §3.6: "Where the type is `TERRITORY_EXTENSION` with `territory_code`
        `WAR_ZONE_A`, a war-risk placement on this policy must exist in `BOUND` status
        whose closed coverage window contains the endorsement's `effective_date`, or
        the bind is refused with `ERR_WAR_RISK_NOT_PLACED`."

        Design: Corner/state_machines/corner_war_zone_extension_bind_guarded_by_bound_placement_window
        """
        book = _quoted_war_zone_extension(api)
        expected_delta_cents = _territory_extension_delta_cents(
            book["policy"], TerritoryCode.WAR_ZONE_A, f.CLOCK_LATE_TERM
        )
        assert book["endorsement"]["quoted_premium_delta_cents"] == expected_delta_cents

        response = api.bind_endorsement(
            book["endorsement_id"], headers=users.SECOND_UNDERWRITER
        )

        validate_error(response, ApiErrorId.WAR_RISK_NOT_PLACED)
        unchanged = fx.fetch_endorsement(api, book["endorsement_id"])
        assert_field_values(
            unchanged,
            status=EndorsementStatus.QUOTED,
            premium_delta_cents=None,
            quoted_premium_delta_cents=expected_delta_cents,
        )
        assert_no_ledger_row_of_type(
            fx.ledger_rows(api, book["policy_id"]), TxnType.ENDORSEMENT_PREMIUM
        )

    def test_the_bind_succeeds_once_a_covering_placement_exists_and_leaves_the_limit(
        self, api
    ):
        """PRD §3.6: "`TERRITORY_EXTENSION` rewrites the policy's
        `territorial_limit_code` to the supplied `territory_code` when that code is
        `CONTINENTAL` or `WORLDWIDE`; a `WAR_ZONE_A` extension leaves
        `territorial_limit_code` untouched, because war zone cover is carried by the
        separate placement rather than by the hull slip's territorial limit."

        Design: Corner/state_machines/corner_war_zone_extension_bind_guarded_by_bound_placement_window
        """
        book = _quoted_war_zone_extension(api)
        expected_delta_cents = _territory_extension_delta_cents(
            book["policy"], TerritoryCode.WAR_ZONE_A, f.CLOCK_LATE_TERM
        )
        validate_error(
            api.bind_endorsement(book["endorsement_id"], headers=users.SECOND_UNDERWRITER),
            ApiErrorId.WAR_RISK_NOT_PLACED,
        )

        fx.make_war_placement(
            api,
            book["policy_id"],
            book["market_id"],
            fx.fetch_policy(api, book["policy_id"])["version"],
            war_hull_line_cents=COVERING_WAR_LINE_CENTS,
            perils_scope=PerilsScope.WAR_HIJACK,
            coverage_from=COVERING_WINDOW_FROM,
            coverage_to=COVERING_WINDOW_TO,
        )
        response = api.bind_endorsement(
            book["endorsement_id"], headers=users.SECOND_UNDERWRITER
        )

        endorsement = validate_unpaginated(response)
        assert_field_values(
            endorsement,
            status=EndorsementStatus.BOUND,
            premium_delta_cents=expected_delta_cents,
        )
        policy = fx.fetch_policy(api, book["policy_id"])
        assert policy["territorial_limit_code"] == TerritorialLimit.WORLDWIDE, (
            "a WAR_ZONE_A extension must leave the hull slip's territorial limit alone"
        )


SCHEDULED_HULL_VALUE_CENTS = 45000000
ACQUIRED_HULL_VALUE_CENTS = 30000000


def _fleet_declaration_book(api) -> dict:
    """A bound fleet account carrying two automatically acquired hulls.

    One acquisition starts inside the reporting period and one starts after it,
    so a declaration for that period reports exactly one of them.
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(
        api,
        book["operator_id"],
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
        automatic_acquisition_enabled=True,
    )
    scheduled = fx.make_schedule(
        api,
        policy["id"],
        book["aircraft_id"],
        book["senior_pilot_id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=SCHEDULED_HULL_VALUE_CENTS,
    )
    fx.bind_policy(api, policy["id"])

    in_period_aircraft = fx.make_aircraft(
        api, f.single_piston_aircraft_payload(f.unique_registration_mark())
    )
    out_of_period_aircraft = fx.make_aircraft(
        api, f.single_piston_aircraft_payload(f.unique_registration_mark())
    )
    in_period = fx.make_schedule(
        api,
        policy["id"],
        in_period_aircraft["id"],
        book["senior_pilot_id"],
        headers=users.BROKER,
        use_class=UseClass.PRIVATE,
        agreed_value_cents=ACQUIRED_HULL_VALUE_CENTS,
        effective_from=IN_PERIOD_ACQUISITION_FROM,
        acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
    )
    out_of_period = fx.make_schedule(
        api,
        policy["id"],
        out_of_period_aircraft["id"],
        book["senior_pilot_id"],
        headers=users.BROKER,
        use_class=UseClass.PRIVATE,
        agreed_value_cents=ACQUIRED_HULL_VALUE_CENTS,
        effective_from=OUT_OF_PERIOD_ACQUISITION_FROM,
        acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
    )
    fx.advance_clock(api, CLOCK_DECLARATION_MONTH_END)
    book.update(
        {
            "policy": fx.fetch_policy(api, policy["id"]),
            "policy_id": policy["id"],
            "scheduled": scheduled,
            "scheduled_id": scheduled["id"],
            "in_period": in_period,
            "in_period_id": in_period["id"],
            "out_of_period": out_of_period,
            "out_of_period_id": out_of_period["id"],
        }
    )
    return book


def _acquired_hull_premium_cents(policy: dict, live_schedule_count: int) -> int:
    """The annual premium of one automatically acquired private hull."""
    band = _logged_band(f.senior_pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
    return c.annual_premium_cents(
        ACQUIRED_HULL_VALUE_CENTS,
        _rate_ppm(policy, UseClass.PRIVATE, band),
        policy["policy_type"],
        live_schedule_count=live_schedule_count,
    )


class TestFleetDeclarationAcceptance:
    """Acceptance activates the hulls the declaration reported, and only those."""

    def test_acceptance_activates_only_the_reported_hull(self, api):
        """PRD §3.8: "It moves every schedule whose identifier appears in
        `reported_schedule_ids` from `PENDING` to `ACTIVE` and stamps each one's
        `reported_declaration_id` with the declaration's identifier; where such a
        schedule's `warranty_status` is already `BREACHED`, the system transition
        `ACTIVE → SUSPENDED_WARRANTY` follows immediately in the same request."

        Design: Corner/state_machines/corner_declaration_acceptance_activates_only_the_reported_hulls
        """
        book = _fleet_declaration_book(api)
        declaration = fx.make_fleet_declaration(
            api,
            book["policy_id"],
            period_from=DECLARATION_PERIOD_FROM,
            period_to=DECLARATION_PERIOD_TO,
        )
        assert declaration["reported_schedule_ids"] == [book["in_period_id"]], (
            "only the acquisition whose cover started inside the period is reportable"
        )
        assert_field_values(declaration, declared_count=1, status=DeclarationStatus.SUBMITTED)

        accepted = fx.accept_declaration(api, declaration["id"])

        assert accepted["status"] == DeclarationStatus.ACCEPTED
        reported = fx.fetch_schedule(api, book["in_period_id"])
        assert_field_values(
            reported,
            coverage_status=CoverageStatus.ACTIVE,
            reported_declaration_id=declaration["id"],
        )
        unreported = fx.fetch_schedule(api, book["out_of_period_id"])
        assert_field_values(
            unreported,
            coverage_status=CoverageStatus.PENDING,
            reported_declaration_id=None,
        )
        assert fx.fetch_schedule(api, book["scheduled_id"])["coverage_status"] == (
            CoverageStatus.ACTIVE
        ), "the originally scheduled hull is untouched by the declaration"

    def test_acceptance_charges_one_pro_rata_row_for_the_reported_hull_only(self, api):
        """PRD §3.8: "It then appends one `DECLARATION_PREMIUM` ledger row with a
        `basis` of `PRO_RATA`, a null `endorsement_id` and an `amount_cents` equal to
        `declared_premium_cents` — an append that is skipped entirely when
        `declared_count` is 0."

        Design: Corner/state_machines/corner_declaration_acceptance_activates_only_the_reported_hulls
        """
        book = _fleet_declaration_book(api)
        policy = book["policy"]
        band = _logged_band(f.senior_pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        scheduled_premium_cents = c.annual_premium_cents(
            SCHEDULED_HULL_VALUE_CENTS,
            _rate_ppm(policy, UseClass.PRIVATE, band),
            policy["policy_type"],
            live_schedule_count=1,
        )
        acquired_premium_cents = _acquired_hull_premium_cents(policy, live_schedule_count=2)
        expected_line_cents = c.pro_rata_charge_cents(
            acquired_premium_cents,
            c.whole_days_between(IN_PERIOD_ACQUISITION_FROM, policy["effective_to"]),
            policy["term_days"],
        )

        declaration = fx.make_fleet_declaration(
            api,
            book["policy_id"],
            period_from=DECLARATION_PERIOD_FROM,
            period_to=DECLARATION_PERIOD_TO,
        )
        assert_field_values(
            declaration,
            late_flag=False,
            late_loading_cents=0,
            declared_premium_cents=expected_line_cents,
        )
        fx.accept_declaration(api, declaration["id"])

        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 2, f"one opening row and one declaration row, got {len(rows)}"
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=scheduled_premium_cents,
        )
        assert_ledger_row(
            rows[1],
            txn_type=TxnType.DECLARATION_PREMIUM,
            amount_cents=expected_line_cents,
            basis=TxnBasis.PRO_RATA,
        )
        assert rows[1]["endorsement_id"] is None
        after = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            after,
            written_premium_cents=scheduled_premium_cents + expected_line_cents,
            live_schedule_count=3,
            total_hull_sum_insured_cents=(
                SCHEDULED_HULL_VALUE_CENTS + 2 * ACQUIRED_HULL_VALUE_CENTS
            ),
        )
        assert ledger_signed_sum(rows) == after["written_premium_cents"]


LOSS_DATE_IN_FINAL_MONTH = "2027-08-15T00:00:00Z"


class TestClockAdvanceRunsTheExpirySweep:
    """Repositioning the clock is what expires a policy — nothing is lazy."""

    def test_repositioning_the_clock_past_the_term_expires_the_policy_and_its_hull(
        self, api
    ):
        """PRD §3.3: "Expiring a policy moves every schedule on it whose
        `coverage_status` is `PENDING`, `ACTIVE` or `SUSPENDED_WARRANTY` to `REMOVED`,
        re-derives `total_hull_sum_insured_cents` and `live_schedule_count` — both of
        which necessarily fall to 0 — and advances the policy's `version` by one."

        Design: Corner/state_machines/corner_clock_advance_runs_the_policy_expiry_sweep
        """
        book = fx.bound_policy_with_hull(api)
        band = _logged_band(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
        earned_premium_cents = c.annual_premium_cents(
            book["schedule"]["agreed_value_cents"],
            _rate_ppm(book["policy"], UseClass.INSTRUCTIONAL, band),
            book["policy"]["policy_type"],
            live_schedule_count=1,
        )
        version_before = fx.fetch_policy(api, book["policy_id"])["version"]

        response = api.set_clock(f.clock_payload(CLOCK_AT_EXPIRY), headers=users.AUDITOR)

        validate_success(response)
        policy = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy,
            status=PolicyStatus.EXPIRED,
            total_hull_sum_insured_cents=0,
            live_schedule_count=0,
            written_premium_cents=earned_premium_cents,
        )
        assert policy["version"] == version_before + 1, (
            f"the sweep advances the policy version once, "
            f"got {version_before} -> {policy['version']}"
        )
        schedule = fx.fetch_schedule(api, book["schedule_id"])
        assert_field_values(
            schedule,
            coverage_status=CoverageStatus.REMOVED,
            warranty_status=WarrantyStatus.PENDING_EVIDENCE,
        )
        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 1, "no premium is returned on expiry: the term is fully earned"
        assert ledger_signed_sum(rows) == earned_premium_cents

    def test_an_expired_policy_refuses_writes_and_is_not_swept_twice(self, api):
        """PRD §3.3: "`EXPIRED` is terminal, and an expired policy refuses every
        write, whatever the operation."

        Design: Corner/state_machines/corner_clock_advance_runs_the_policy_expiry_sweep
        """
        book = fx.bound_policy_with_hull(api)
        fx.advance_clock(api, CLOCK_AT_EXPIRY)
        expired = fx.fetch_policy(api, book["policy_id"])
        assert expired["status"] == PolicyStatus.EXPIRED

        validate_error(
            api.create_claim(
                f.claim_payload(
                    book["policy_id"],
                    book["schedule_id"],
                    loss_date=LOSS_DATE_IN_FINAL_MONTH,
                ),
                headers=users.BROKER,
            ),
            ApiErrorId.POLICY_NOT_BOUND,
        )
        validate_error(
            api.create_endorsement(
                f.territory_extension_endorsement_payload(book["policy_id"]),
                headers=users.UNDERWRITER,
            ),
            ApiErrorId.POLICY_NOT_BOUND,
        )
        validate_success(
            api.set_clock(f.clock_payload(CLOCK_PAST_EXPIRY), headers=users.CLAIMS_ADJUSTER)
        )

        after = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(after, status=PolicyStatus.EXPIRED)
        assert after["version"] == expired["version"], (
            "a policy already out of BOUND is not a sweep candidate a second time"
        )
