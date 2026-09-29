"""Authority: role reservations, segregation of duties and operator scoping.

Each refusal here is paired with the identical request made by the role the PRD
does admit, so a test that passes proves the gate discriminates rather than
simply blocking everything.
"""

import pytest

from test_helpers import (
    AdjustmentStatus,
    ApiErrorId,
    CooperationStatus,
    CoverageStatus,
    EndorsementStatus,
    EndorsementType,
    LossType,
    PolicyStatus,
    Role,
    SalvageStatus,
    SettlementBasis,
    TxnBasis,
    TxnType,
    UseClass,
    assert_field_values,
    assert_ledger_row,
    assert_ledger_txn_types,
    assert_no_ledger_row_of_type,
    validate_error,
    validate_list,
    validate_success,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

REVISED_HULL_VALUE_CENTS = 32000000
OTHER_HULL_VALUE_CENTS = 30000000
ENDORSEMENT_EFFECTIVE_DATE = "2026-10-01T00:00:00Z"
LOSS_DATE = "2026-10-15T00:00:00Z"
SECOND_LOSS_DATE = "2026-10-20T00:00:00Z"
SURVEY_INSTANT = "2026-10-25T00:00:00Z"
AUDIT_CLOCK_INSTANT = "2026-11-02T00:00:00Z"
PARTIAL_REPAIR_COST_CENTS = 9000000
RESERVE_CENTS = 10000000

EVERY_ROLE_BUT_THE_UNDERWRITER = [
    Role.BROKER,
    Role.CLAIMS_ADJUSTER,
    Role.OPERATOR_USER,
    Role.AUDITOR,
]


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


def _instructional_rate_ppm(policy: dict) -> int:
    """The rate the standard instructional hull of this suite is priced at."""
    return c.rate_ppm_for(
        policy["base_hull_rate_ppm"],
        UseClass.INSTRUCTIONAL,
        policy["territorial_limit_code"],
        _band_of(f.pilot_payload(), f.CLOCK_BEFORE_INCEPTION),
    )


# ----------------------------------------------------------------------
# Pricing writes are the Underwriter's and nobody else's
# ----------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE_BUT_THE_UNDERWRITER)
def test_binding_a_policy_is_refused_for_every_role_but_the_underwriter(api, role):
    """PRD §2.1: "Binding policies, verifying pilot logbook hours, revising
    agreed values in place, recording pilot-warranty findings, quoting,
    referring, binding and voiding endorsements, opening war-risk markets,
    placing and cancelling war risk, and accepting or rejecting fleet
    declarations are all reserved to this role and to no other."

    Design: Corner/rbac/corner_underwriter_exclusive_writes_rejected_for_every_other_role
    """
    book = fx.draft_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)

    response = api.bind_policy(
        book["policy_id"],
        headers=users.headers_for_role(role, operator_id=book["operator_id"]),
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED)

    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        status=PolicyStatus.DRAFT,
        written_premium_cents=0,
        version=book["policy"]["version"],
    )
    assert_field_values(
        fx.fetch_schedule(api, book["schedule_id"]),
        coverage_status=CoverageStatus.PENDING,
    )


@pytest.mark.parametrize("role", EVERY_ROLE_BUT_THE_UNDERWRITER)
def test_revising_an_agreed_value_is_refused_for_every_role_but_the_underwriter(
    api, role
):
    """PRD §2.1: "Binding policies, verifying pilot logbook hours, revising
    agreed values in place, recording pilot-warranty findings, quoting,
    referring, binding and voiding endorsements, opening war-risk markets,
    placing and cancelling war risk, and accepting or rejecting fleet
    declarations are all reserved to this role and to no other."

    Design: Corner/rbac/corner_underwriter_exclusive_writes_rejected_for_every_other_role
    """
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    schedule = book["schedule"]

    response = api.revise_schedule_value(
        schedule["id"],
        f.value_revision_payload(REVISED_HULL_VALUE_CENTS, schedule["version"]),
        headers=users.headers_for_role(role, operator_id=book["operator_id"]),
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED)

    assert_field_values(
        fx.fetch_schedule(api, schedule["id"]),
        agreed_value_cents=schedule["agreed_value_cents"],
        hull_premium_cents=schedule["hull_premium_cents"],
        version=schedule["version"],
    )


def test_the_underwriter_may_make_the_writes_the_other_roles_were_refused(api):
    """PRD §2.1: "If the role is recognised but is not among the roles the target
    operation admits, the request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_underwriter_exclusive_writes_rejected_for_every_other_role
    """
    book = fx.draft_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    rate_ppm = _instructional_rate_ppm(book["policy"])
    annual = c.annual_premium_cents(
        book["schedule"]["agreed_value_cents"], rate_ppm
    )

    bound = validate_unpaginated(
        api.bind_policy(book["policy_id"], headers=users.UNDERWRITER)
    )
    assert_field_values(
        bound,
        status=PolicyStatus.BOUND,
        live_schedule_count=1,
        written_premium_cents=annual,
    )

    schedule = fx.fetch_schedule(api, book["schedule_id"])
    revised = validate_unpaginated(
        api.revise_schedule_value(
            schedule["id"],
            f.value_revision_payload(REVISED_HULL_VALUE_CENTS, schedule["version"]),
            headers=users.UNDERWRITER,
        )
    )
    revised_annual = c.annual_premium_cents(REVISED_HULL_VALUE_CENTS, rate_ppm)
    assert_field_values(
        revised,
        agreed_value_cents=REVISED_HULL_VALUE_CENTS,
        rate_ppm=rate_ppm,
        hull_premium_cents=revised_annual,
        version=schedule["version"] + 1,
    )

    rows = fx.ledger_rows(api, book["policy_id"])
    assert_ledger_txn_types(
        rows, [TxnType.INITIAL_PREMIUM, TxnType.RERATE_ADJUSTMENT]
    )
    assert_ledger_row(
        rows[1],
        txn_type=TxnType.RERATE_ADJUSTMENT,
        amount_cents=revised_annual - annual,
        basis=TxnBasis.ANNUAL,
        policy_id=book["policy_id"],
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        written_premium_cents=revised_annual,
        total_hull_sum_insured_cents=REVISED_HULL_VALUE_CENTS,
    )


# ----------------------------------------------------------------------
# Broker and ClaimsAdjuster are peers with disjoint write surfaces
# ----------------------------------------------------------------------
def _bound_policy_with_an_endorsement_and_a_notified_claim(api):
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    endorsement = fx.make_endorsement(
        api,
        f.endorsement_payload(
            book["policy_id"],
            EndorsementType.PREMISES_LIABILITY,
            effective_date=ENDORSEMENT_EFFECTIVE_DATE,
        ),
        headers=users.BROKER,
    )
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    claim = fx.make_claim(
        api,
        book["policy_id"],
        book["schedule_id"],
        headers=users.BROKER,
        loss_date=LOSS_DATE,
    )
    book.update(
        {
            "endorsement": endorsement,
            "endorsement_id": endorsement["id"],
            "claim": claim,
            "claim_id": claim["id"],
        }
    )
    return book


def _the_broker_records_an_investigation(api, book):
    return api.record_investigation(
        book["claim_id"], f.investigation_payload(), headers=users.BROKER
    )


def _the_broker_settles_the_claim(api, book):
    return api.settle_claim(
        book["claim_id"],
        f.settlement_payload(SettlementBasis.PARTIAL_REPAIR),
        headers=users.BROKER,
    )


@pytest.mark.parametrize(
    "adjuster_only_write",
    [_the_broker_records_an_investigation, _the_broker_settles_the_claim],
    ids=["investigations", "settlement"],
)
def test_the_broker_cannot_reach_the_adjusters_claim_surfaces(
    api, adjuster_only_write
):
    """PRD §2.1: "A `Broker` places business on behalf of insureds: it may
    register operators, airframes and pilots, open draft policies, attach
    schedules, submit endorsements and fleet declarations, and notify losses —
    but a `Broker` can never price, bind or settle anything."

    Design: Corner/rbac/corner_broker_and_adjuster_surfaces_are_disjoint_peer_roles
    """
    book = _bound_policy_with_an_endorsement_and_a_notified_claim(api)

    response = adjuster_only_write(api, book)
    validate_error(response, ApiErrorId.UNAUTHORIZED)

    assert_field_values(
        fx.fetch_claim(api, book["claim_id"]),
        adjustment_status=AdjustmentStatus.NOTIFIED,
        cooperation_status=CooperationStatus.PENDING,
        settlement_basis=None,
        settlement_amount_cents=None,
        version=book["claim"]["version"],
    )


def test_the_adjuster_cannot_reach_the_underwriters_quotation_surface(api):
    """PRD §2.1: "A `ClaimsAdjuster` owns the claim file end to end: recording
    investigations, appending damage assessments, taking the coverage decision,
    disposing of salvage and executing settlement are reserved to this role."

    Design: Corner/rbac/corner_broker_and_adjuster_surfaces_are_disjoint_peer_roles
    """
    book = _bound_policy_with_an_endorsement_and_a_notified_claim(api)

    response = api.quote_endorsement(
        book["endorsement_id"], headers=users.CLAIMS_ADJUSTER
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED)

    assert_field_values(
        fx.fetch_endorsement(api, book["endorsement_id"]),
        status=EndorsementStatus.SUBMITTED,
        quote_round=0,
        quoted_premium_delta_cents=None,
        quoted_by_user_id=None,
        version=book["endorsement"]["version"],
    )


def test_the_claim_surfaces_the_prd_shares_admit_both_peer_roles(api):
    """PRD §2.1: "A `ClaimsAdjuster` owns the claim file end to end: recording
    investigations, appending damage assessments, taking the coverage decision,
    disposing of salvage and executing settlement are reserved to this role."

    Design: Corner/rbac/corner_broker_and_adjuster_surfaces_are_disjoint_peer_roles
    """
    book = _bound_policy_with_an_endorsement_and_a_notified_claim(api)

    investigating = validate_unpaginated(
        api.record_investigation(
            book["claim_id"], f.investigation_payload(), headers=users.CLAIMS_ADJUSTER
        )
    )
    assert_field_values(
        investigating,
        adjustment_status=AdjustmentStatus.INVESTIGATING,
        cooperation_status=CooperationStatus.COOPERATING,
    )

    notified_by_the_adjuster = validate_unpaginated(
        api.create_claim(
            f.claim_payload(
                book["policy_id"],
                book["schedule_id"],
                loss_date=SECOND_LOSS_DATE,
                loss_type=LossType.LIABILITY_PROPERTY,
            ),
            headers=users.CLAIMS_ADJUSTER,
        ),
        expected_status=201,
    )
    assert_field_values(
        notified_by_the_adjuster,
        adjustment_status=AdjustmentStatus.NOTIFIED,
        loss_type=LossType.LIABILITY_PROPERTY,
    )

    rows, meta = validate_list(
        api.list_claims(
            headers=users.BROKER, params={"policy_id": book["policy_id"]}
        )
    )
    assert len(rows) == 2
    assert_field_values(
        meta,
        total_count=2,
        limit=c.DEFAULT_LIMIT,
        offset=c.DEFAULT_OFFSET,
        has_more=False,
    )


# ----------------------------------------------------------------------
# The Auditor reads everything and writes nothing but the clock
# ----------------------------------------------------------------------
def _bound_policy_with_a_notified_claim(api):
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    claim = fx.make_claim(
        api,
        book["policy_id"],
        book["schedule_id"],
        headers=users.BROKER,
        loss_date=LOSS_DATE,
    )
    book["claim"] = claim
    book["claim_id"] = claim["id"]
    book["annual_premium_cents"] = c.annual_premium_cents(
        book["schedule"]["agreed_value_cents"], _instructional_rate_ppm(book["policy"])
    )
    return book


def _the_auditor_registers_an_operator(api, book):
    return api.create_operator(
        f.private_owner_operator_payload(), headers=users.AUDITOR
    )


def _the_auditor_opens_a_policy(api, book):
    return api.create_policy(
        f.policy_payload(book["operator_id"]), headers=users.AUDITOR
    )


def _the_auditor_notifies_a_claim(api, book):
    return api.create_claim(
        f.claim_payload(
            book["policy_id"], book["schedule_id"], loss_date=SECOND_LOSS_DATE
        ),
        headers=users.AUDITOR,
    )


def _the_auditor_appends_a_damage_assessment(api, book):
    return api.create_damage_assessment(
        f.damage_assessment_payload(book["claim_id"], assessed_at=SURVEY_INSTANT),
        headers=users.AUDITOR,
    )


@pytest.mark.parametrize(
    "auditor_write",
    [
        _the_auditor_registers_an_operator,
        _the_auditor_opens_a_policy,
        _the_auditor_notifies_a_claim,
        _the_auditor_appends_a_damage_assessment,
    ],
    ids=["operators", "policies", "claims", "damage_assessments"],
)
def test_the_auditor_holds_no_write_permission_across_the_book(api, auditor_write):
    """PRD §2.1: "An `Auditor` has read-only oversight of the entire book — the
    premium ledger, reserves, warranty findings and war-risk placements — and
    holds no write permission whatsoever beyond repositioning the logical clock."

    Design: Corner/rbac/corner_auditor_writes_rejected_across_every_collection
    """
    book = _bound_policy_with_a_notified_claim(api)

    response = auditor_write(api, book)
    validate_error(response, ApiErrorId.UNAUTHORIZED)

    _, policy_meta = validate_list(api.list_policies(headers=users.AUDITOR))
    assert_field_values(policy_meta, total_count=1)
    _, claim_meta = validate_list(
        api.list_claims(
            headers=users.AUDITOR, params={"policy_id": book["policy_id"]}
        )
    )
    assert_field_values(claim_meta, total_count=1)
    _, assessment_meta = validate_list(
        api.list_damage_assessments(
            headers=users.AUDITOR, params={"claim_id": book["claim_id"]}
        )
    )
    assert_field_values(assessment_meta, total_count=0)
    assert_field_values(
        fx.fetch_claim(api, book["claim_id"]),
        assessment_count=0,
        ctl_ratio_ppm=None,
        version=book["claim"]["version"],
    )


def test_the_auditor_may_reposition_the_clock_and_read_the_whole_book(api):
    """PRD §2.1: "An `Auditor` has read-only oversight of the entire book — the
    premium ledger, reserves, warranty findings and war-risk placements — and
    holds no write permission whatsoever beyond repositioning the logical clock."

    Design: Corner/rbac/corner_auditor_writes_rejected_across_every_collection
    """
    book = _bound_policy_with_a_notified_claim(api)

    validate_success(
        api.set_clock(f.clock_payload(AUDIT_CLOCK_INSTANT), headers=users.AUDITOR)
    )

    rows, meta = validate_list(
        api.list_premium_transactions(
            headers=users.AUDITOR, params={"policy_id": book["policy_id"]}
        )
    )
    assert_field_values(meta, total_count=1)
    assert_ledger_row(
        rows[0],
        txn_type=TxnType.INITIAL_PREMIUM,
        amount_cents=book["annual_premium_cents"],
        basis=TxnBasis.ANNUAL,
        effective_date=book["policy"]["effective_from"],
        policy_id=book["policy_id"],
    )

    claim = validate_unpaginated(
        api.get_claim(book["claim_id"], headers=users.AUDITOR)
    )
    assert_field_values(
        claim,
        adjustment_status=AdjustmentStatus.NOTIFIED,
        salvage_status=SalvageStatus.NONE,
        reserve_cents=0,
    )

    policy = validate_unpaginated(
        api.get_policy(book["policy_id"], headers=users.AUDITOR)
    )
    assert_field_values(
        policy,
        status=PolicyStatus.BOUND,
        written_premium_cents=book["annual_premium_cents"],
        outstanding_reserve_cents=0,
    )


# ----------------------------------------------------------------------
# Segregation of duties on both header-identity pairs
# ----------------------------------------------------------------------
def _bound_policy_with_an_endorsement_quoted_by_the_first_underwriter(api):
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    endorsement = fx.quoted_endorsement(
        api,
        f.endorsement_payload(
            book["policy_id"],
            EndorsementType.PREMISES_LIABILITY,
            effective_date=ENDORSEMENT_EFFECTIVE_DATE,
        ),
    )
    book["endorsement"] = endorsement
    book["endorsement_id"] = endorsement["id"]
    book["annual_premium_cents"] = c.annual_premium_cents(
        book["schedule"]["agreed_value_cents"], _instructional_rate_ppm(book["policy"])
    )
    book["premium_delta_cents"] = c.pro_rata_charge_cents(
        c.PREMISES_LIABILITY_ANNUAL_CENTS,
        c.whole_days_between(
            ENDORSEMENT_EFFECTIVE_DATE, book["policy"]["effective_to"]
        ),
        c.whole_days_between(
            book["policy"]["effective_from"], book["policy"]["effective_to"]
        ),
    )
    return book


def _reserved_claim_decided_by_the_first_adjuster(api):
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_BEFORE_INCEPTION)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    book = fx.reserved_claim(
        api,
        book,
        repair_cost_estimate_cents=PARTIAL_REPAIR_COST_CENTS,
        reserve_cents=RESERVE_CENTS,
        assessed_at=SURVEY_INSTANT,
        loss_date=LOSS_DATE,
    )
    book["annual_premium_cents"] = c.annual_premium_cents(
        book["schedule"]["agreed_value_cents"], _instructional_rate_ppm(book["policy"])
    )
    return book


def test_the_underwriter_who_quoted_an_endorsement_may_not_bind_it(api):
    """PRD §2.1: "The user id that settles a claim must differ from the
    `coverage_decided_by_user_id` recorded on that claim, and the user id that
    binds an endorsement must differ from the `quoted_by_user_id` recorded on
    that endorsement."

    Design: Corner/rbac/corner_segregation_of_duties_blocks_the_same_user_on_both_pairs
    """
    book = _bound_policy_with_an_endorsement_quoted_by_the_first_underwriter(api)
    quoted = book["endorsement"]
    assert quoted["quoted_by_user_id"] == users.UNDERWRITER_ID

    refused = api.bind_endorsement(book["endorsement_id"], headers=users.UNDERWRITER)
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)

    assert_field_values(
        fx.fetch_endorsement(api, book["endorsement_id"]),
        status=EndorsementStatus.QUOTED,
        premium_delta_cents=None,
        quoted_by_user_id=users.UNDERWRITER_ID,
        version=quoted["version"],
    )
    assert_no_ledger_row_of_type(
        fx.ledger_rows(api, book["policy_id"]), TxnType.ENDORSEMENT_PREMIUM
    )

    bound = validate_unpaginated(
        api.bind_endorsement(
            book["endorsement_id"], headers=users.SECOND_UNDERWRITER
        )
    )
    assert_field_values(
        bound,
        status=EndorsementStatus.BOUND,
        premium_delta_cents=book["premium_delta_cents"],
        quoted_by_user_id=users.UNDERWRITER_ID,
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        premises_liability_extension=True,
        written_premium_cents=(
            book["annual_premium_cents"] + book["premium_delta_cents"]
        ),
    )


def test_the_adjuster_who_confirmed_cover_may_not_release_the_money(api):
    """PRD §3.10: "The acting `X-User-ID` must differ from the claim's
    `coverage_decided_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES` — the adjuster who confirmed cover may not be
    the adjuster who releases the money."

    Design: Corner/rbac/corner_segregation_of_duties_blocks_the_same_user_on_both_pairs
    """
    book = _reserved_claim_decided_by_the_first_adjuster(api)
    reserved = book["claim"]
    assert reserved["coverage_decided_by_user_id"] == users.CLAIMS_ADJUSTER_ID

    refused = api.settle_claim(
        book["claim_id"],
        f.settlement_payload(SettlementBasis.PARTIAL_REPAIR),
        headers=users.CLAIMS_ADJUSTER,
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)

    assert_field_values(
        fx.fetch_claim(api, book["claim_id"]),
        adjustment_status=AdjustmentStatus.RESERVED,
        reserve_cents=RESERVE_CENTS,
        settlement_basis=None,
        settlement_amount_cents=None,
        deductible_applied_cents=None,
        version=reserved["version"],
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        paid_hull_cents=0,
        outstanding_reserve_cents=RESERVE_CENTS,
    )

    settled = validate_unpaginated(
        api.settle_claim(
            book["claim_id"],
            f.settlement_payload(SettlementBasis.PARTIAL_REPAIR),
            headers=users.SECOND_CLAIMS_ADJUSTER,
        )
    )
    deductible = c.deductible_cents(
        PARTIAL_REPAIR_COST_CENTS, book["policy"]["hull_deductible_ppm"]
    )
    assert_field_values(
        settled,
        adjustment_status=AdjustmentStatus.SETTLED,
        settlement_basis=SettlementBasis.PARTIAL_REPAIR,
        deductible_applied_cents=deductible,
        settlement_amount_cents=PARTIAL_REPAIR_COST_CENTS - deductible,
        reserve_cents=0,
    )
    assert_field_values(
        fx.fetch_schedule(api, book["schedule_id"]),
        coverage_status=CoverageStatus.ACTIVE,
    )
    assert_no_ledger_row_of_type(
        fx.ledger_rows(api, book["policy_id"]), TxnType.SETTLEMENT_RETURN
    )
    assert_field_values(
        fx.fetch_policy(api, book["policy_id"]),
        paid_hull_cents=PARTIAL_REPAIR_COST_CENTS - deductible,
        outstanding_reserve_cents=0,
        written_premium_cents=book["annual_premium_cents"],
    )


# ----------------------------------------------------------------------
# An OperatorUser sees its own operator tree and no other
# ----------------------------------------------------------------------
def _two_independent_operator_trees(api):
    """Two insureds, each with its own bound policy and hull."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)

    own_operator = fx.make_operator(api, f.operator_payload())
    own_aircraft = fx.make_aircraft(api, f.aircraft_payload())
    own_pilot = fx.make_pilot(api, f.pilot_payload())
    own_policy = fx.make_policy(api, own_operator["id"])
    own_schedule = fx.make_schedule(
        api, own_policy["id"], own_aircraft["id"], own_pilot["id"]
    )
    fx.bind_policy(api, own_policy["id"])

    other_operator = fx.make_operator(api, f.private_owner_operator_payload())
    other_aircraft = fx.make_aircraft(api, f.single_piston_aircraft_payload())
    other_pilot = fx.make_pilot(api, f.senior_pilot_payload())
    other_policy = fx.make_policy(api, other_operator["id"])
    other_schedule = fx.make_schedule(
        api,
        other_policy["id"],
        other_aircraft["id"],
        other_pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=OTHER_HULL_VALUE_CENTS,
    )
    fx.bind_policy(api, other_policy["id"])

    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    return {
        "own_operator_id": own_operator["id"],
        "own_policy_id": own_policy["id"],
        "own_schedule_id": own_schedule["id"],
        "own_written_premium_cents": c.annual_premium_cents(
            own_schedule["agreed_value_cents"], _instructional_rate_ppm(own_policy)
        ),
        "other_operator_id": other_operator["id"],
        "other_policy_id": other_policy["id"],
        "other_schedule_id": other_schedule["id"],
    }


def _read_the_other_operators_policy(api, book):
    return api.get_policy(
        book["other_policy_id"], headers=users.operator_user(book["own_operator_id"])
    )


def _read_the_other_operators_schedule(api, book):
    return api.get_schedule(
        book["other_schedule_id"], headers=users.operator_user(book["own_operator_id"])
    )


@pytest.mark.parametrize(
    "cross_operator_read",
    [
        _read_the_other_operators_policy,
        _read_the_other_operators_schedule,
    ],
    ids=["policy", "schedule"],
)
def test_an_operator_user_cannot_read_another_operators_tree(
    api, cross_operator_read
):
    """PRD §2.1: "An `OperatorUser` reaching a policy, an aircraft schedule, an
    endorsement, a claim, a war-risk placement, a fleet declaration or a
    premium-ledger row that belongs — directly or transitively through the policy
    — to a different operator is refused with `ERR_OPERATOR_SCOPE_VIOLATION`
    (HTTP 403), on reads as well as on writes."

    Design: Corner/rbac/corner_operator_user_scoped_to_its_own_operator_tree
    """
    book = _two_independent_operator_trees(api)

    response = cross_operator_read(api, book)
    validate_error(response, ApiErrorId.OPERATOR_SCOPE_VIOLATION)


def test_a_cross_operator_loss_notification_is_a_scope_violation_not_a_role_refusal(
    api,
):
    """PRD §2.1: "An `OperatorUser` reaching a policy, an aircraft schedule, an
    endorsement, a claim, a war-risk placement, a fleet declaration or a
    premium-ledger row that belongs — directly or transitively through the policy
    — to a different operator is refused with `ERR_OPERATOR_SCOPE_VIOLATION`
    (HTTP 403), on reads as well as on writes."

    Design: Corner/rbac/corner_operator_user_scoped_to_its_own_operator_tree
    """
    book = _two_independent_operator_trees(api)

    response = api.create_claim(
        f.claim_payload(
            book["other_policy_id"], book["other_schedule_id"], loss_date=LOSS_DATE
        ),
        headers=users.operator_user(book["own_operator_id"]),
    )
    validate_error(response, ApiErrorId.OPERATOR_SCOPE_VIOLATION)

    rows, meta = validate_list(
        api.list_claims(
            headers=users.UNDERWRITER, params={"policy_id": book["other_policy_id"]}
        )
    )
    assert rows == []
    assert_field_values(meta, total_count=0)


def test_an_operator_user_reads_and_notifies_inside_its_own_tree(api):
    """PRD §2.1: "An `OperatorUser` is the insured itself; it may notify a loss
    and read its own policy tree and nothing else."

    Design: Corner/rbac/corner_operator_user_scoped_to_its_own_operator_tree
    """
    book = _two_independent_operator_trees(api)
    headers = users.operator_user(book["own_operator_id"])

    policy = validate_unpaginated(api.get_policy(book["own_policy_id"], headers=headers))
    assert_field_values(
        policy,
        operator_id=book["own_operator_id"],
        status=PolicyStatus.BOUND,
        written_premium_cents=book["own_written_premium_cents"],
    )

    claim = validate_unpaginated(
        api.create_claim(
            f.claim_payload(
                book["own_policy_id"], book["own_schedule_id"], loss_date=LOSS_DATE
            ),
            headers=headers,
        ),
        expected_status=201,
    )
    assert_field_values(
        claim,
        adjustment_status=AdjustmentStatus.NOTIFIED,
        salvage_status=SalvageStatus.NONE,
        cooperation_status=CooperationStatus.PENDING,
        reserve_cents=0,
    )

    rows, meta = validate_list(
        api.list_claims(headers=headers, params={"policy_id": book["own_policy_id"]})
    )
    assert len(rows) == 1
    assert_field_values(meta, total_count=1)
