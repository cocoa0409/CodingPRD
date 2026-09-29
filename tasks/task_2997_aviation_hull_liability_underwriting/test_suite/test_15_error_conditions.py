"""Refusal behaviour: not-found codes, uniqueness, state gates and windows.

Every expectation here is derived from the PRD rather than read back out of the
response: money and rates come from the pure helpers in `test_helpers.constants`
applied to the request payloads the setup sent.
"""

import pytest

from test_helpers import (
    AcquisitionSource,
    AdjustmentStatus,
    AircraftClass,
    ApiErrorId,
    CooperationStatus,
    CoverageDecision,
    CoverageStatus,
    DeclarationDecision,
    DeclarationStatus,
    EndorsementStatus,
    EndorsementType,
    NON_EXISTENT_UUID,
    PerilsScope,
    PlacementStatus,
    PolicyStatus,
    SalvageAction,
    SalvageStatus,
    TxnBasis,
    TxnType,
    UseClass,
    assert_field_values,
    assert_ledger_row,
    rows_of_type,
    validate_error,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# ----------------------------------------------------------------------
# Instants and amounts these tests drive the book with
# ----------------------------------------------------------------------
PRIVATE_HULL_VALUE_CENTS = 30000000
REVISED_HULL_VALUE_CENTS = 32000000
BOUNDARY_HULL_VALUE_CENTS = 40000000
HULL_REMOVAL_DATE = "2026-10-01T00:00:00Z"
LOSS_DATE = "2026-10-15T00:00:00Z"
SECOND_LOSS_DATE = "2026-10-20T00:00:00Z"
SURVEY_INSTANT = "2026-10-25T00:00:00Z"
CTL_REPAIR_COST_CENTS = 36000000
CTL_RESERVE_CENTS = 40000000
COOPERATION_RESERVE_CENTS = 10000000
SALVAGE_PROCEEDS_CENTS = 5000000
WINDOW_STARTING_BEFORE_INCEPTION = "2026-08-25T00:00:00Z"
WINDOW_ENDING_AFTER_EXPIRY = "2027-09-02T00:00:00Z"


def _band_of(pilot_request: dict, clock_utc: str) -> str:
    """The rating band a pilot registration scores into at a given clock."""
    return c.band_for_score(
        c.qualification_score(
            pilot_request["total_logged_hours"],
            pilot_request["hours_on_type"],
            pilot_request["instrument_rated"],
            pilot_request["license_type"],
            pilot_request["last_training_completed_at"],
            clock_utc,
        )
    )


def _term_days(policy_request: dict) -> int:
    return c.whole_days_between(
        policy_request["effective_from"], policy_request["effective_to"]
    )


# ----------------------------------------------------------------------
# Every path `{id}` collection answers with its own not-found code
# ----------------------------------------------------------------------
PATH_ID_COLLECTIONS = [
    ("get_operator", ApiErrorId.OPERATOR_NOT_FOUND),
    ("get_endorsement", ApiErrorId.ENDORSEMENT_NOT_FOUND),
    ("get_war_placement", ApiErrorId.PLACEMENT_NOT_FOUND),
    ("get_damage_assessment", ApiErrorId.ASSESSMENT_NOT_FOUND),
    ("get_premium_transaction", ApiErrorId.TRANSACTION_NOT_FOUND),
    ("get_fleet_declaration", ApiErrorId.DECLARATION_NOT_FOUND),
]


@pytest.mark.parametrize(
    "reader,expected_error_id",
    PATH_ID_COLLECTIONS,
    ids=[reader for reader, _ in PATH_ID_COLLECTIONS],
)
def test_an_unresolvable_path_id_reports_the_addressed_collections_own_code(
    api, reader, expected_error_id
):
    """PRD §2.7: "An `{id}` appearing in the path is resolved first, against the
    collection the endpoint belongs to; if it matches no row, the request fails
    with that collection's own not-found code — `ERR_OPERATOR_NOT_FOUND`,
    `ERR_AIRCRAFT_NOT_FOUND`, `ERR_PILOT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_SCHEDULE_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`,
    `ERR_MARKET_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND` or
    `ERR_DECLARATION_NOT_FOUND` — each carrying HTTP 404."

    Design: Corner/errors/corner_every_path_id_lookup_returns_its_own_not_found_code
    """
    response = getattr(api, reader)(NON_EXISTENT_UUID, headers=users.AUDITOR)
    validate_error(response, expected_error_id)


def test_the_collections_do_not_share_one_generic_not_found_code(api):
    """PRD §2.7: "An `{id}` appearing in the path is resolved first, against the
    collection the endpoint belongs to; if it matches no row, the request fails
    with that collection's own not-found code — `ERR_OPERATOR_NOT_FOUND`,
    `ERR_AIRCRAFT_NOT_FOUND`, `ERR_PILOT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_SCHEDULE_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`,
    `ERR_MARKET_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND` or
    `ERR_DECLARATION_NOT_FOUND` — each carrying HTTP 404."

    Design: Corner/errors/corner_every_path_id_lookup_returns_its_own_not_found_code
    """
    operator = fx.make_operator(api)

    reported = []
    for reader, expected_error_id in PATH_ID_COLLECTIONS:
        response = getattr(api, reader)(NON_EXISTENT_UUID, headers=users.AUDITOR)
        reported.append(validate_error(response, expected_error_id)["error_id"])

    assert len(set(reported)) == len(PATH_ID_COLLECTIONS), reported

    resolved = validate_unpaginated(
        api.get_operator(operator["id"], headers=users.AUDITOR)
    )
    assert resolved["id"] == operator["id"]


# ----------------------------------------------------------------------
# A registration mark is unique across the whole book
# ----------------------------------------------------------------------
def test_a_mark_already_on_the_register_cannot_be_registered_again(api):
    """PRD §3.1: "Marks are between 3 and 8 characters of uppercase letters,
    digits and hyphens, and are globally unique across the whole book: a second
    registration of a mark that already exists is refused with
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/errors/corner_duplicate_registration_mark_rejected
    """
    incumbent_request = f.single_piston_aircraft_payload(registration_mark="N512NW")
    incumbent = fx.make_aircraft(api, incumbent_request)

    response = api.create_aircraft(
        f.turboprop_aircraft_payload(
            registration_mark=incumbent_request["registration_mark"],
            manufacture_year=2013,
            hull_new_value_cents=120000000,
            seat_count=12,
            max_takeoff_weight_kg=7600,
        ),
        headers=users.UNDERWRITER,
    )
    validate_error(response, ApiErrorId.DUPLICATE_REGISTRATION)

    unchanged = validate_unpaginated(
        api.get_aircraft(incumbent["id"], headers=users.UNDERWRITER)
    )
    assert_field_values(
        unchanged,
        registration_mark=incumbent_request["registration_mark"],
        aircraft_class=AircraftClass.SINGLE_PISTON,
        manufacture_year=incumbent_request["manufacture_year"],
        hull_new_value_cents=incumbent_request["hull_new_value_cents"],
        seat_count=incumbent_request["seat_count"],
    )


def test_the_same_airframe_specification_is_admitted_under_a_free_mark(api):
    """PRD §3.1: "Marks are between 3 and 8 characters of uppercase letters,
    digits and hyphens, and are globally unique across the whole book: a second
    registration of a mark that already exists is refused with
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/errors/corner_duplicate_registration_mark_rejected
    """
    first = fx.make_aircraft(
        api, f.single_piston_aircraft_payload(registration_mark="N512NW")
    )

    second_request = f.single_piston_aircraft_payload(registration_mark="N513NW")
    second = validate_unpaginated(
        api.create_aircraft(second_request, headers=users.UNDERWRITER),
        expected_status=201,
    )

    assert second["id"] != first["id"]
    assert_field_values(
        second,
        registration_mark=second_request["registration_mark"],
        aircraft_class=AircraftClass.SINGLE_PISTON,
        hull_new_value_cents=second_request["hull_new_value_cents"],
    )


# ----------------------------------------------------------------------
# A hull taken off risk by a REMOVE_AIRCRAFT endorsement is no longer live
# ----------------------------------------------------------------------
def _policy_with_one_removed_and_one_active_hull(api):
    """Two private hulls on one bound fleet policy, one of them since removed."""
    book = fx.registered_book(api, clock=f.CLOCK_BEFORE_INCEPTION)
    policy_request = f.policy_payload(book["operator_id"])
    policy = validate_unpaginated(
        api.create_policy(policy_request, headers=users.UNDERWRITER),
        expected_status=201,
    )
    kept = fx.make_schedule(
        api,
        policy["id"],
        book["aircraft_id"],
        book["senior_pilot_id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
    )
    removed = fx.make_schedule(
        api,
        policy["id"],
        book["single_id"],
        book["senior_pilot_id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
    )
    fx.bind_policy(api, policy["id"])
    fx.bound_endorsement(
        api,
        f.remove_aircraft_endorsement_payload(
            policy["id"], removed["id"], effective_date=HULL_REMOVAL_DATE
        ),
    )
    fx.advance_clock(api, f.CLOCK_LATE_TERM)

    band = _band_of(f.senior_pilot_payload(), f.CLOCK_BEFORE_INCEPTION)
    rate_ppm = c.rate_ppm_for(
        policy_request["base_hull_rate_ppm"],
        UseClass.PRIVATE,
        policy_request["territorial_limit_code"],
        band,
    )
    annual_each = c.annual_premium_cents(PRIVATE_HULL_VALUE_CENTS, rate_ppm)
    unexpired_days = c.whole_days_between(
        HULL_REMOVAL_DATE, policy_request["effective_to"]
    )
    short_rate_return = c.floor_ppm(
        c.pro_rata_return_cents(annual_each, unexpired_days, _term_days(policy_request)),
        c.REMOVE_AIRCRAFT_RETURN_PPM,
    )
    return {
        "policy_id": policy["id"],
        "policy_request": policy_request,
        "kept_schedule_id": kept["id"],
        "removed_schedule_id": removed["id"],
        "rate_ppm": rate_ppm,
        "annual_each_cents": annual_each,
        "written_premium_cents": 2 * annual_each - short_rate_return,
    }


def _revise_the_removed_hulls_value(api, book):
    schedule = fx.fetch_schedule(api, book["removed_schedule_id"])
    return api.revise_schedule_value(
        schedule["id"],
        f.value_revision_payload(REVISED_HULL_VALUE_CENTS, schedule["version"]),
        headers=users.UNDERWRITER,
    )


def _notify_a_loss_on_the_removed_hull(api, book):
    return api.create_claim(
        f.claim_payload(
            book["policy_id"], book["removed_schedule_id"], loss_date=LOSS_DATE
        ),
        headers=users.BROKER,
    )


@pytest.mark.parametrize(
    "write_on_the_removed_hull",
    [_revise_the_removed_hulls_value, _notify_a_loss_on_the_removed_hull],
    ids=["value_revision", "claim_notification"],
)
def test_a_removed_hull_is_not_live_and_refuses_further_writes(
    api, write_on_the_removed_hull
):
    """PRD §2.11: "The target aircraft schedule is live, meaning its
    `coverage_status` is `PENDING`, `ACTIVE` or `SUSPENDED_WARRANTY` —
    `ERR_SCHEDULE_NOT_LIVE`, 409. Applies to value revision, warranty findings,
    endorsement binding, claim notification and the coverage decision."

    Design: Corner/errors/corner_removed_hull_is_not_live_and_rejects_writes
    """
    book = _policy_with_one_removed_and_one_active_hull(api)
    before = fx.fetch_schedule(api, book["removed_schedule_id"])
    assert before["coverage_status"] == CoverageStatus.REMOVED

    response = write_on_the_removed_hull(api, book)
    validate_error(response, ApiErrorId.SCHEDULE_NOT_LIVE)

    after = fx.fetch_schedule(api, book["removed_schedule_id"])
    assert_field_values(
        after,
        coverage_status=CoverageStatus.REMOVED,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
        version=before["version"],
    )
    policy = fx.fetch_policy(api, book["policy_id"])
    assert_field_values(
        policy,
        live_schedule_count=1,
        total_hull_sum_insured_cents=PRIVATE_HULL_VALUE_CENTS,
        written_premium_cents=book["written_premium_cents"],
    )


def test_the_surviving_hull_accepts_the_revision_the_removed_hull_refused(api):
    """PRD §3.4: "The schedule must be live — `PENDING`, `ACTIVE` or
    `SUSPENDED_WARRANTY` — and a `TOTAL_LOSS_SETTLED` or `REMOVED` schedule is
    refused with `ERR_SCHEDULE_NOT_LIVE`."

    Design: Corner/errors/corner_removed_hull_is_not_live_and_rejects_writes
    """
    book = _policy_with_one_removed_and_one_active_hull(api)
    kept = fx.fetch_schedule(api, book["kept_schedule_id"])
    assert kept["coverage_status"] == CoverageStatus.ACTIVE

    revised = validate_unpaginated(
        api.revise_schedule_value(
            kept["id"],
            f.value_revision_payload(REVISED_HULL_VALUE_CENTS, kept["version"]),
            headers=users.UNDERWRITER,
        )
    )
    revised_annual = c.annual_premium_cents(REVISED_HULL_VALUE_CENTS, book["rate_ppm"])
    assert_field_values(
        revised,
        coverage_status=CoverageStatus.ACTIVE,
        agreed_value_cents=REVISED_HULL_VALUE_CENTS,
        rate_ppm=book["rate_ppm"],
        hull_premium_cents=revised_annual,
        version=kept["version"] + 1,
    )

    rows = fx.ledger_rows(api, book["policy_id"])
    rerates = rows_of_type(rows, TxnType.RERATE_ADJUSTMENT)
    assert len(rerates) == 1
    assert_ledger_row(
        rerates[0],
        txn_type=TxnType.RERATE_ADJUSTMENT,
        amount_cents=revised_annual - book["annual_each_cents"],
        basis=TxnBasis.ANNUAL,
        policy_id=book["policy_id"],
    )

    policy = fx.fetch_policy(api, book["policy_id"])
    assert_field_values(
        policy,
        live_schedule_count=1,
        total_hull_sum_insured_cents=REVISED_HULL_VALUE_CENTS,
        written_premium_cents=(
            book["written_premium_cents"] + revised_annual - book["annual_each_cents"]
        ),
    )


# ----------------------------------------------------------------------
# The salvage dimension walks its own ordered path
# ----------------------------------------------------------------------
def _reserved_constructive_total_loss(api):
    """A reserved claim whose survey carries it over the total-loss threshold."""
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    book = fx.reserved_claim(
        api,
        book,
        repair_cost_estimate_cents=CTL_REPAIR_COST_CENTS,
        reserve_cents=CTL_RESERVE_CENTS,
        assessed_at=SURVEY_INSTANT,
        loss_date=LOSS_DATE,
    )
    agreed_value_cents = book["schedule"]["agreed_value_cents"]
    assert (
        c.ctl_ratio_ppm(CTL_REPAIR_COST_CENTS, agreed_value_cents)
        >= c.CTL_THRESHOLD_PPM
    )
    return book


@pytest.mark.parametrize(
    "unreachable_action", [SalvageAction.SELL, SalvageAction.ABANDON]
)
def test_a_salvage_action_unreachable_from_no_disposition_is_refused(
    api, unreachable_action
):
    """PRD §3.9: "`salvage_status` starts at `NONE` and a disposition that is not
    reachable from the current value is refused with
    `ERR_SALVAGE_INVALID_STATE`."

    Design: Corner/errors/corner_salvage_actions_out_of_order_rejected
    """
    book = _reserved_constructive_total_loss(api)
    before = fx.fetch_claim(api, book["claim_id"])
    assert_field_values(
        before, salvage_status=SalvageStatus.NONE, ctl_flag=True,
        adjustment_status=AdjustmentStatus.RESERVED,
    )

    response = api.dispose_salvage(
        book["claim_id"],
        f.salvage_disposition_payload(unreachable_action),
        headers=users.CLAIMS_ADJUSTER,
    )
    validate_error(response, ApiErrorId.SALVAGE_INVALID_STATE)

    after = fx.fetch_claim(api, book["claim_id"])
    assert_field_values(
        after,
        salvage_status=SalvageStatus.NONE,
        salvage_proceeds_cents=0,
        adjustment_status=AdjustmentStatus.RESERVED,
        version=before["version"],
    )


def test_a_tendered_wreck_may_only_be_sold_or_abandoned_and_a_sale_is_terminal(api):
    """PRD §3.9: "`RETAINED_BY_INSURED`, `SOLD` and `ABANDONED` are all terminal,
    so a second disposition on the same claim is refused."

    Design: Corner/errors/corner_salvage_actions_out_of_order_rejected
    """
    book = _reserved_constructive_total_loss(api)
    claim_id = book["claim_id"]
    reserved = fx.fetch_claim(api, claim_id)

    tendered = validate_unpaginated(
        api.dispose_salvage(
            claim_id,
            f.salvage_disposition_payload(SalvageAction.TENDER),
            headers=users.CLAIMS_ADJUSTER,
        )
    )
    assert_field_values(
        tendered,
        salvage_status=SalvageStatus.TENDERED,
        adjustment_status=AdjustmentStatus.RESERVED,
        version=reserved["version"] + 1,
    )

    retained_back_edge = api.dispose_salvage(
        claim_id,
        f.salvage_disposition_payload(SalvageAction.RETAIN),
        headers=users.CLAIMS_ADJUSTER,
    )
    validate_error(retained_back_edge, ApiErrorId.SALVAGE_INVALID_STATE)
    assert_field_values(
        fx.fetch_claim(api, claim_id),
        salvage_status=SalvageStatus.TENDERED,
        version=tendered["version"],
    )

    sold = validate_unpaginated(
        api.dispose_salvage(
            claim_id,
            f.salvage_disposition_payload(
                SalvageAction.SELL, salvage_proceeds_cents=SALVAGE_PROCEEDS_CENTS
            ),
            headers=users.CLAIMS_ADJUSTER,
        )
    )
    assert_field_values(
        sold,
        salvage_status=SalvageStatus.SOLD,
        salvage_proceeds_cents=SALVAGE_PROCEEDS_CENTS,
        version=tendered["version"] + 1,
    )

    second_disposition = api.dispose_salvage(
        claim_id,
        f.salvage_disposition_payload(SalvageAction.ABANDON),
        headers=users.CLAIMS_ADJUSTER,
    )
    validate_error(second_disposition, ApiErrorId.SALVAGE_INVALID_STATE)
    assert_field_values(
        fx.fetch_claim(api, claim_id),
        salvage_status=SalvageStatus.SOLD,
        salvage_proceeds_cents=SALVAGE_PROCEEDS_CENTS,
        adjustment_status=AdjustmentStatus.RESERVED,
        version=sold["version"],
    )


# ----------------------------------------------------------------------
# Non-cooperation blocks cover and cannot be repaired after a denial
# ----------------------------------------------------------------------
def _two_claims_one_of_them_non_cooperating(api):
    """Two losses on one active hull; the insured cooperates on only one."""
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)

    withholding = fx.make_claim(
        api, book["policy_id"], book["schedule_id"], headers=users.BROKER,
        loss_date=LOSS_DATE,
    )
    cooperating = fx.make_claim(
        api, book["policy_id"], book["schedule_id"], headers=users.BROKER,
        loss_date=SECOND_LOSS_DATE,
    )
    withholding = fx.investigate_claim(
        api,
        withholding["id"],
        cooperation_status=CooperationStatus.NON_COOPERATION,
        investigator_reference="AAIB-2026-0411",
    )
    cooperating = fx.investigate_claim(
        api,
        cooperating["id"],
        cooperation_status=CooperationStatus.COOPERATING,
        investigator_reference="AAIB-2026-0412",
    )
    book.update(
        {
            "withholding_claim": withholding,
            "withholding_claim_id": withholding["id"],
            "cooperating_claim": cooperating,
            "cooperating_claim_id": cooperating["id"],
        }
    )
    return book


def test_cover_cannot_be_confirmed_while_the_insured_withholds_cooperation(api):
    """PRD §3.9: "The claim's `cooperation_status` must not be
    `NON_COOPERATION`: cover cannot be confirmed while the insured withholds
    cooperation with the accident investigation, and only a recorded
    investigation submitted as `COOPERATING` can produce the value the rule
    demands, so an attempt is refused with
    `ERR_INVESTIGATION_COOPERATION_MISSING`."

    Design: Corner/errors/corner_non_cooperation_blocks_cover_and_cannot_be_repaired
    """
    book = _two_claims_one_of_them_non_cooperating(api)
    decision = f.coverage_decision_payload(
        decision=CoverageDecision.COVERED, reserve_cents=COOPERATION_RESERVE_CENTS
    )

    refused = api.decide_coverage(
        book["withholding_claim_id"], decision, headers=users.CLAIMS_ADJUSTER
    )
    validate_error(refused, ApiErrorId.INVESTIGATION_COOPERATION_MISSING)
    assert_field_values(
        fx.fetch_claim(api, book["withholding_claim_id"]),
        adjustment_status=AdjustmentStatus.COVERAGE_REFERRED,
        cooperation_status=CooperationStatus.NON_COOPERATION,
        reserve_cents=0,
        version=book["withholding_claim"]["version"],
    )

    accepted = validate_unpaginated(
        api.decide_coverage(
            book["cooperating_claim_id"], decision, headers=users.CLAIMS_ADJUSTER
        )
    )
    assert_field_values(
        accepted,
        adjustment_status=AdjustmentStatus.RESERVED,
        cooperation_status=CooperationStatus.COOPERATING,
        reserve_cents=COOPERATION_RESERVE_CENTS,
    )

    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        outstanding_reserve_cents=COOPERATION_RESERVE_CENTS,
    )


def test_a_denied_claim_is_terminal_and_refuses_a_repairing_investigation(api):
    """PRD §3.9: "The adjustment dimension is owned entirely by the
    `ClaimsAdjuster` role, and `SETTLED` and `DENIED` are its terminal states: a
    claim that has reached either refuses every further action with
    `ERR_CLAIM_INVALID_STATE`."

    Design: Corner/errors/corner_non_cooperation_blocks_cover_and_cannot_be_repaired
    """
    book = _two_claims_one_of_them_non_cooperating(api)

    denied = validate_unpaginated(
        api.decide_coverage(
            book["withholding_claim_id"],
            f.coverage_decision_payload(decision=CoverageDecision.DENIED),
            headers=users.CLAIMS_ADJUSTER,
        )
    )
    assert_field_values(
        denied, adjustment_status=AdjustmentStatus.DENIED, reserve_cents=0
    )

    repair_attempt = api.record_investigation(
        book["withholding_claim_id"],
        f.investigation_payload(
            cooperation_status=CooperationStatus.COOPERATING,
            investigator_reference="AAIB-2026-0413",
        ),
        headers=users.CLAIMS_ADJUSTER,
    )
    validate_error(repair_attempt, ApiErrorId.CLAIM_INVALID_STATE)

    assert_field_values(
        fx.fetch_claim(api, book["withholding_claim_id"]),
        adjustment_status=AdjustmentStatus.DENIED,
        cooperation_status=CooperationStatus.NON_COOPERATION,
        reserve_cents=0,
        version=denied["version"],
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]), outstanding_reserve_cents=0
    )


# ----------------------------------------------------------------------
# Coverage windows and endorsement effective dates must sit inside the term
# ----------------------------------------------------------------------
def _draft_policy_without_hulls(api):
    book = fx.registered_book(api, clock=f.CLOCK_BEFORE_INCEPTION)
    policy_request = f.policy_payload(book["operator_id"])
    policy = validate_unpaginated(
        api.create_policy(policy_request, headers=users.UNDERWRITER),
        expected_status=201,
    )
    book.update(
        {
            "policy": policy,
            "policy_id": policy["id"],
            "policy_request": policy_request,
            "rate_ppm": c.rate_ppm_for(
                policy_request["base_hull_rate_ppm"],
                UseClass.INSTRUCTIONAL,
                policy_request["territorial_limit_code"],
                _band_of(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION),
            ),
        }
    )
    book["annual_premium_cents"] = c.annual_premium_cents(
        BOUNDARY_HULL_VALUE_CENTS, book["rate_ppm"]
    )
    return book


def _bound_policy_on_exact_term_boundaries(api):
    book = _draft_policy_without_hulls(api)
    book["schedule"] = fx.make_schedule(
        api,
        book["policy_id"],
        book["aircraft_id"],
        book["pilot_id"],
        agreed_value_cents=BOUNDARY_HULL_VALUE_CENTS,
    )
    book["schedule_id"] = book["schedule"]["id"]
    book["policy"] = fx.bind_policy(api, book["policy_id"])
    return book


ESCAPING_WINDOWS = [
    ("starts_before_inception", {"effective_from": WINDOW_STARTING_BEFORE_INCEPTION}),
    ("ends_after_expiry", {"effective_to": WINDOW_ENDING_AFTER_EXPIRY}),
]


@pytest.mark.parametrize(
    "escaping_window",
    [window for _, window in ESCAPING_WINDOWS],
    ids=[name for name, _ in ESCAPING_WINDOWS],
)
def test_a_hull_window_escaping_the_policy_term_is_refused(api, escaping_window):
    """PRD §3.4: "The hull's window must sit inside the policy's term, meaning
    the policy's `effective_from` must be at or before the schedule's
    `effective_from`, the schedule's `effective_from` must be strictly earlier
    than its `effective_to`, and the schedule's `effective_to` must be at or
    before the policy's `effective_to`; a window that escapes the term is
    refused with `ERR_SCHEDULE_WINDOW_OUTSIDE_POLICY`."

    Design: Corner/errors/corner_coverage_and_endorsement_windows_outside_the_term_rejected
    """
    book = _draft_policy_without_hulls(api)

    response = api.create_schedule(
        f.schedule_payload(
            book["policy_id"],
            book["aircraft_id"],
            book["pilot_id"],
            agreed_value_cents=BOUNDARY_HULL_VALUE_CENTS,
            **escaping_window,
        ),
        headers=users.UNDERWRITER,
    )
    validate_error(response, ApiErrorId.SCHEDULE_WINDOW_OUTSIDE_POLICY)

    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        status=PolicyStatus.DRAFT,
        live_schedule_count=0,
        total_hull_sum_insured_cents=0,
        written_premium_cents=0,
    )
    rows, meta = validate_list(
        api.list_schedules(
            headers=users.UNDERWRITER, params={"policy_id": book["policy_id"]}
        )
    )
    assert rows == []
    assert_field_values(meta, total_count=0)


def test_a_hull_window_on_the_exact_policy_boundaries_is_admitted_and_rated(api):
    """PRD §3.4: "The hull's window must sit inside the policy's term, meaning
    the policy's `effective_from` must be at or before the schedule's
    `effective_from`, the schedule's `effective_from` must be strictly earlier
    than its `effective_to`, and the schedule's `effective_to` must be at or
    before the policy's `effective_to`; a window that escapes the term is
    refused with `ERR_SCHEDULE_WINDOW_OUTSIDE_POLICY`."

    Design: Corner/errors/corner_coverage_and_endorsement_windows_outside_the_term_rejected
    """
    book = _draft_policy_without_hulls(api)
    request = f.schedule_payload(
        book["policy_id"],
        book["aircraft_id"],
        book["pilot_id"],
        agreed_value_cents=BOUNDARY_HULL_VALUE_CENTS,
    )
    assert request["effective_from"] == book["policy_request"]["effective_from"]
    assert request["effective_to"] == book["policy_request"]["effective_to"]

    schedule = validate_unpaginated(
        api.create_schedule(request, headers=users.UNDERWRITER), expected_status=201
    )
    assert_field_values(
        schedule,
        coverage_status=CoverageStatus.PENDING,
        rate_ppm=book["rate_ppm"],
        hull_premium_cents=book["annual_premium_cents"],
    )

    bound = validate_unpaginated(
        api.bind_policy(book["policy_id"], headers=users.UNDERWRITER)
    )
    assert_field_values(
        bound,
        status=PolicyStatus.BOUND,
        live_schedule_count=1,
        written_premium_cents=book["annual_premium_cents"],
    )


def test_an_endorsement_effective_exactly_at_expiry_is_refused(api):
    """PRD §3.6: "The `effective_date` is the instant the endorsement attaches
    and the start of the pro-rata numerator; it must fall inside the policy term
    treated as a half-open interval that includes `effective_from` and excludes
    `effective_to`, so an endorsement effective exactly at expiry is refused
    with `ERR_EFFECTIVE_DATE_OUT_OF_TERM`."

    Design: Corner/errors/corner_coverage_and_endorsement_windows_outside_the_term_rejected
    """
    book = _bound_policy_on_exact_term_boundaries(api)

    at_expiry = api.create_endorsement(
        f.endorsement_payload(
            book["policy_id"],
            EndorsementType.PREMISES_LIABILITY,
            effective_date=book["policy_request"]["effective_to"],
        ),
        headers=users.UNDERWRITER,
    )
    validate_error(at_expiry, ApiErrorId.EFFECTIVE_DATE_OUT_OF_TERM)

    at_inception = validate_unpaginated(
        api.create_endorsement(
            f.endorsement_payload(
                book["policy_id"],
                EndorsementType.PREMISES_LIABILITY,
                effective_date=book["policy_request"]["effective_from"],
            ),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    assert_field_values(
        at_inception,
        status=EndorsementStatus.SUBMITTED,
        quote_round=0,
        quoted_premium_delta_cents=None,
        premium_delta_cents=None,
    )

    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        status=PolicyStatus.BOUND,
        premises_liability_extension=False,
        written_premium_cents=book["annual_premium_cents"],
    )


# ----------------------------------------------------------------------
# Fleet declarations: one decision only, and non-overlapping valid periods
# ----------------------------------------------------------------------
AUTO_HULL_ATTACHED_AT = "2026-09-20T00:00:00Z"
DECLARATION_FILED_AT = "2026-10-05T00:00:00Z"
FIRST_PERIOD_FROM = "2026-09-01T00:00:00Z"
FIRST_PERIOD_TO = "2026-09-30T00:00:00Z"
OVERLAPPING_PERIOD_FROM = "2026-09-15T00:00:00Z"
OVERLAPPING_PERIOD_TO = "2026-10-15T00:00:00Z"
CLEAN_PERIOD_FROM = "2026-10-01T00:00:00Z"
CLEAN_PERIOD_TO = "2026-10-31T00:00:00Z"
PERIOD_ESCAPING_THE_TERM_TO = "2027-09-05T00:00:00Z"


def _fleet_account_with_one_submitted_declaration(api):
    """A bound fleet account carrying one auto-acquired hull and its report."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    scheduled_hull = fx.make_aircraft(
        api, f.single_piston_aircraft_payload(registration_mark="N512NW")
    )
    acquired_hull = fx.make_aircraft(
        api, f.single_piston_aircraft_payload(registration_mark="N721CC")
    )
    pilot_request = f.senior_pilot_payload()
    pilot = fx.make_pilot(api, pilot_request)

    policy_request = f.policy_payload(
        operator["id"], automatic_acquisition_enabled=True
    )
    policy = validate_unpaginated(
        api.create_policy(policy_request, headers=users.UNDERWRITER),
        expected_status=201,
    )
    fx.make_schedule(
        api,
        policy["id"],
        scheduled_hull["id"],
        pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
    )
    fx.bind_policy(api, policy["id"])

    fx.advance_clock(api, AUTO_HULL_ATTACHED_AT)
    reported = fx.make_schedule(
        api,
        policy["id"],
        acquired_hull["id"],
        pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
        acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
        effective_from=AUTO_HULL_ATTACHED_AT,
    )

    fx.advance_clock(api, DECLARATION_FILED_AT)
    declaration = fx.make_fleet_declaration(
        api, policy["id"], period_from=FIRST_PERIOD_FROM, period_to=FIRST_PERIOD_TO
    )

    rate_ppm = c.rate_ppm_for(
        policy_request["base_hull_rate_ppm"],
        UseClass.PRIVATE,
        policy_request["territorial_limit_code"],
        _band_of(pilot_request, f.CLOCK_BEFORE_INCEPTION),
    )
    annual = c.annual_premium_cents(PRIVATE_HULL_VALUE_CENTS, rate_ppm)
    line_total = c.pro_rata_charge_cents(
        annual,
        c.whole_days_between(AUTO_HULL_ATTACHED_AT, policy_request["effective_to"]),
        _term_days(policy_request),
    )
    return {
        "policy_id": policy["id"],
        "policy_request": policy_request,
        "reported_schedule_id": reported["id"],
        "declaration": declaration,
        "declaration_id": declaration["id"],
        "initial_premium_cents": annual,
        "declared_premium_cents": line_total,
        "written_after_acceptance_cents": annual + line_total,
    }


def test_a_declaration_period_overlapping_a_live_declaration_is_refused(api):
    """PRD §3.8: "Creation supplies only the `policy_id` and the reporting period
    as `period_from` and `period_to`, both of which are **inclusive** bounds:
    `period_from` must be at or after the policy's `effective_from`, `period_to`
    must be strictly later than `period_from` and at or before the policy's
    `effective_to`, and the period must not overlap the period of any other
    declaration on the same policy that is `SUBMITTED` or `ACCEPTED`."

    Design: Corner/errors/corner_declaration_lifecycle_and_period_overlap_rejected
    """
    book = _fleet_account_with_one_submitted_declaration(api)
    overlapping = f.fleet_declaration_payload(
        book["policy_id"],
        period_from=OVERLAPPING_PERIOD_FROM,
        period_to=OVERLAPPING_PERIOD_TO,
    )

    while_submitted = api.create_fleet_declaration(
        overlapping, headers=users.UNDERWRITER
    )
    validate_error(while_submitted, ApiErrorId.DECLARATION_PERIOD_INVALID)

    accepted = validate_unpaginated(
        api.accept_fleet_declaration(
            book["declaration_id"],
            f.declaration_acceptance_payload(decision=DeclarationDecision.ACCEPT),
            headers=users.UNDERWRITER,
        )
    )
    assert_field_values(
        accepted,
        status=DeclarationStatus.ACCEPTED,
        declared_count=1,
        declared_premium_cents=book["declared_premium_cents"],
        late_flag=False,
        late_loading_cents=0,
        reported_schedule_ids=[book["reported_schedule_id"]],
    )

    while_accepted = api.create_fleet_declaration(
        overlapping, headers=users.UNDERWRITER
    )
    validate_error(while_accepted, ApiErrorId.DECLARATION_PERIOD_INVALID)

    assert_field_values(
        fx.fetch_schedule(api, book["reported_schedule_id"]),
        coverage_status=CoverageStatus.ACTIVE,
        reported_declaration_id=book["declaration_id"],
    )


@pytest.mark.parametrize(
    "second_decision", [DeclarationDecision.ACCEPT, DeclarationDecision.REJECT]
)
def test_an_accepted_declaration_refuses_a_second_decision(api, second_decision):
    """PRD §3.8: "The declaration must be in `SUBMITTED`; `ACCEPTED` and
    `REJECTED` are both terminal and a second decision is refused with
    `ERR_DECLARATION_NOT_SUBMITTED`."

    Design: Corner/errors/corner_declaration_lifecycle_and_period_overlap_rejected
    """
    book = _fleet_account_with_one_submitted_declaration(api)
    accepted = fx.accept_declaration(api, book["declaration_id"])

    response = api.accept_fleet_declaration(
        book["declaration_id"],
        f.declaration_acceptance_payload(decision=second_decision),
        headers=users.UNDERWRITER,
    )
    validate_error(response, ApiErrorId.DECLARATION_NOT_SUBMITTED)

    assert_field_values(
        fx.fetch_fleet_declaration(api, book["declaration_id"]),
        status=DeclarationStatus.ACCEPTED,
        rejection_reason=None,
        declared_premium_cents=book["declared_premium_cents"],
        version=accepted["version"],
    )

    rows = fx.ledger_rows(api, book["policy_id"])
    declaration_rows = rows_of_type(rows, TxnType.DECLARATION_PREMIUM)
    assert len(declaration_rows) == 1
    assert_ledger_row(
        declaration_rows[0],
        txn_type=TxnType.DECLARATION_PREMIUM,
        amount_cents=book["declared_premium_cents"],
        basis=TxnBasis.PRO_RATA,
        policy_id=book["policy_id"],
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        written_premium_cents=book["written_after_acceptance_cents"],
        live_schedule_count=2,
    )


def test_a_declaration_period_escaping_the_term_is_refused_while_a_clean_one_is_taken(
    api,
):
    """PRD §3.8: "Any of those failures is refused with
    `ERR_DECLARATION_PERIOD_INVALID`."

    Design: Corner/errors/corner_declaration_lifecycle_and_period_overlap_rejected
    """
    book = _fleet_account_with_one_submitted_declaration(api)
    fx.accept_declaration(api, book["declaration_id"])

    escaping = api.create_fleet_declaration(
        f.fleet_declaration_payload(
            book["policy_id"],
            period_from=CLEAN_PERIOD_FROM,
            period_to=PERIOD_ESCAPING_THE_TERM_TO,
        ),
        headers=users.UNDERWRITER,
    )
    validate_error(escaping, ApiErrorId.DECLARATION_PERIOD_INVALID)

    admitted = validate_unpaginated(
        api.create_fleet_declaration(
            f.fleet_declaration_payload(
                book["policy_id"],
                period_from=CLEAN_PERIOD_FROM,
                period_to=CLEAN_PERIOD_TO,
            ),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    assert_field_values(
        admitted,
        status=DeclarationStatus.SUBMITTED,
        declared_count=0,
        declared_premium_cents=0,
        late_loading_cents=0,
        reported_schedule_ids=[],
    )

    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        written_premium_cents=book["written_after_acceptance_cents"],
    )


# ----------------------------------------------------------------------
# A market writes no scope wider than the one it offers
# ----------------------------------------------------------------------
NARROW_LINE_CENTS = 200000000
WIDER_LINE_CENTS = 500000000
NARROW_WINDOW_FROM = "2026-09-01T00:00:00Z"
NARROW_WINDOW_TO = "2026-10-01T00:00:00Z"
WIDER_WINDOW_FROM = "2026-10-02T00:00:00Z"


def _two_markets_of_different_appetite_and_a_draft_policy(api):
    """One market writing war only, one writing hijack, and a policy to cede."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)

    narrow_request = f.war_market_payload(perils_offered=PerilsScope.WAR_ONLY)
    narrow = validate_unpaginated(
        api.create_war_market(narrow_request, headers=users.UNDERWRITER),
        expected_status=201,
    )
    wider_request = f.war_market_payload(
        market_name="Zurich Political Violence Pool",
        perils_offered=PerilsScope.WAR_HIJACK,
    )
    wider = validate_unpaginated(
        api.create_war_market(wider_request, headers=users.UNDERWRITER),
        expected_status=201,
    )

    policy_request = f.policy_payload(operator["id"])
    policy = validate_unpaginated(
        api.create_policy(policy_request, headers=users.UNDERWRITER),
        expected_status=201,
    )
    return {
        "policy": policy,
        "policy_id": policy["id"],
        "policy_request": policy_request,
        "narrow_market_id": narrow["id"],
        "narrow_aggregate_cents": narrow_request["aggregate_line_cents"],
        "wider_market_id": wider["id"],
        "wider_aggregate_cents": wider_request["aggregate_line_cents"],
    }


@pytest.mark.parametrize(
    "wider_scope", [PerilsScope.WAR_HIJACK, PerilsScope.WAR_HIJACK_TERRORISM]
)
def test_a_scope_wider_than_the_market_offers_is_refused(api, wider_scope):
    """PRD §3.7: "The requested `perils_scope` must be no wider than the market's
    `perils_offered`, and a request for a wider scope is refused with
    `ERR_PERILS_NOT_OFFERED`."

    Design: Corner/errors/corner_perils_scope_not_offered_by_the_market_rejected
    """
    book = _two_markets_of_different_appetite_and_a_draft_policy(api)

    response = api.create_war_placement(
        f.war_placement_payload(
            book["policy_id"],
            book["narrow_market_id"],
            book["policy"]["version"],
            war_hull_line_cents=NARROW_LINE_CENTS,
            perils_scope=wider_scope,
            coverage_from=NARROW_WINDOW_FROM,
            coverage_to=NARROW_WINDOW_TO,
        ),
        headers=users.UNDERWRITER,
    )
    validate_error(response, ApiErrorId.PERILS_NOT_OFFERED)

    assert_field_values(
        fx.fetch_war_market(api, book["narrow_market_id"]),
        committed_line_cents=0,
        available_line_cents=book["narrow_aggregate_cents"],
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        status=PolicyStatus.DRAFT,
        written_premium_cents=0,
        version=book["policy"]["version"],
    )


def test_each_market_admits_the_scope_it_offers_and_holds_only_its_own_line(api):
    """PRD §3.7: "The requested `perils_scope` must be no wider than the market's
    `perils_offered`, and a request for a wider scope is refused with
    `ERR_PERILS_NOT_OFFERED`."

    Design: Corner/errors/corner_perils_scope_not_offered_by_the_market_rejected
    """
    book = _two_markets_of_different_appetite_and_a_draft_policy(api)
    territory = book["policy_request"]["territorial_limit_code"]

    on_narrow = validate_unpaginated(
        api.create_war_placement(
            f.war_placement_payload(
                book["policy_id"],
                book["narrow_market_id"],
                book["policy"]["version"],
                war_hull_line_cents=NARROW_LINE_CENTS,
                perils_scope=PerilsScope.WAR_ONLY,
                coverage_from=NARROW_WINDOW_FROM,
                coverage_to=NARROW_WINDOW_TO,
            ),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    narrow_premium = c.war_premium_cents(
        NARROW_LINE_CENTS, PerilsScope.WAR_ONLY, territory
    )
    assert_field_values(
        on_narrow,
        status=PlacementStatus.BOUND,
        perils_scope=PerilsScope.WAR_ONLY,
        premium_cents=narrow_premium,
    )

    after_first = fx.fetch_policy(api, book["policy_id"])
    assert_field_values(
        after_first, status=PolicyStatus.DRAFT, written_premium_cents=narrow_premium
    )

    on_wider = validate_unpaginated(
        api.create_war_placement(
            f.war_placement_payload(
                book["policy_id"],
                book["wider_market_id"],
                after_first["version"],
                war_hull_line_cents=WIDER_LINE_CENTS,
                perils_scope=PerilsScope.WAR_HIJACK,
                coverage_from=WIDER_WINDOW_FROM,
                coverage_to=book["policy_request"]["effective_to"],
            ),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    wider_premium = c.war_premium_cents(
        WIDER_LINE_CENTS, PerilsScope.WAR_HIJACK, territory
    )
    assert_field_values(
        on_wider,
        status=PlacementStatus.BOUND,
        perils_scope=PerilsScope.WAR_HIJACK,
        premium_cents=wider_premium,
    )

    assert_field_values(
        fx.fetch_war_market(api, book["narrow_market_id"]),
        committed_line_cents=NARROW_LINE_CENTS,
        available_line_cents=book["narrow_aggregate_cents"] - NARROW_LINE_CENTS,
    )
    assert_field_values(
        fx.fetch_war_market(api, book["wider_market_id"]),
        committed_line_cents=WIDER_LINE_CENTS,
        available_line_cents=book["wider_aggregate_cents"] - WIDER_LINE_CENTS,
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        status=PolicyStatus.DRAFT,
        written_premium_cents=narrow_premium + wider_premium,
    )
