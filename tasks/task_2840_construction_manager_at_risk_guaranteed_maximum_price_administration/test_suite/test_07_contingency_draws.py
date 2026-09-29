"""The contingency ledger: postability before affordability, the signature threshold,
and the void that must put every conserved term back exactly where it was.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CM_HEADERS,
    OWNER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_fields,
    assert_gmp_identity,
    assert_instant,
    assert_money,
    assert_money_fields,
    assert_project_axes,
    assert_unchanged,
    factories,
    fixtures,
)
from test_helpers.constants import CLOCK_START
from test_helpers.types import JsonObject

RIVERSIDE_HOSPITAL_TOWER = {
    "cm_fee_pct": Decimal("0.0375"),
    "insurance_rate": Decimal("0.0125"),
    "cost_of_work_total": Decimal("40000000.00"),
    "general_conditions_total": Decimal("2500000.00"),
    "owner_contingency_amount": Decimal("1200000.00"),
    "construction_contingency_amount": Decimal("240000.00"),
    "project_kwargs": {
        "name": "Riverside Regional Hospital Tower",
        "owner_org": "Riverside Health District",
        "precon_fee_amount": Decimal("250000.00"),
    },
}

HARBORVIEW_CIVIC_CENTER = {
    "project_kwargs": {
        "name": "Harborview Civic Center",
        "owner_org": "Harborview County",
        "precon_fee_amount": Decimal("40000.00"),
    }
}

CONSERVED_TERMS = (
    "cost_of_work_budget_total",
    "general_conditions_total",
    "insurance_amount",
    "cm_fee_amount",
    "owner_contingency_remaining",
    "construction_contingency_remaining",
    "contingency_drawn_to_cost_total",
    "gmp_amount",
)


def _civic_centre_draw(api: ApiClient, amount: Decimal) -> Tuple[str, JsonObject]:
    """A construction draw against a 40,000.00 pot that cannot afford 45,000.00."""
    priced = fixtures.executed_project(api, **HARBORVIEW_CIVIC_CENTER)
    draw = fixtures.requested_draw(
        api,
        priced.id,
        amount,
        "CONTINGENCY_USE_CONSTRUCTION",
        origin="FIELD_CONDITION",
        description="unforeseen rock at the north footings",
    )
    return priced.id, draw


def _hospital_tower_draw(api: ApiClient, amount: Decimal) -> Tuple[str, JsonObject]:
    """A construction draw against a fully funded 240,000.00 pot."""
    priced = fixtures.executed_project(api, **RIVERSIDE_HOSPITAL_TOWER)
    draw = fixtures.requested_draw(
        api,
        priced.id,
        amount,
        "CONTINGENCY_USE_CONSTRUCTION",
        origin="DESIGN_DEVELOPMENT",
        description="means and methods, CM risk",
    )
    return priced.id, draw


def _decide(api: ApiClient, draw_id: str, approve: bool, note: str) -> JsonObject:
    """Have the owner's representative decide a requested draw."""
    return validate_success(
        api.approve_draw(
            draw_id,
            factories.draw_approve_payload(approve, approval_note=note),
            OWNER_HEADERS,
        )
    )


def test_the_denied_draw_reports_its_state_before_its_unaffordability(
    api: ApiClient,
) -> None:
    """One post request breaks a state rule and a fiscal rule; the state rule is earlier.

    PRD: "Declining advances it `REQUESTED → DENIED` with no contingency movement whatsoever."

    PRD: "It is permitted from `REQUESTED` only when `requires_owner_approval` is false, and otherwise from `OWNER_APPROVED`; from any other status it draws `ERR_DRAW_STATE_INVALID` (HTTP 409)."

    PRD: "8. State preconditions — the family of `409 Conflict` conditions detailed in §3, in this internal order: the project's `gmp_status` gates, then the per-entity status gates for estimates, proposals, work packages, bids, subcontracts, bond claims, change events, contingency draws, cost reports and the audit engagement, then `ERR_CLOSEOUT_ALREADY_SETTLED`, then `ERR_CONTINGENCY_FROZEN`, then `ERR_POSTURE_NOT_RECOVERED`."

    PRD: "14. Fiscal rules — `ERR_OWNER_APPROVAL_REQUIRED`, then `ERR_CONTINGENCY_INSUFFICIENT`."

    PRD: "Overdrawing a pot would breach the guaranteed maximum price and is rejected with `ERR_CONTINGENCY_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/draw_state_invalid_priority_69_outranks_contingency_insufficient_priority_121
    """
    project_id, draw = _civic_centre_draw(api, Decimal("45000.00"))
    assert_fields(
        draw,
        {
            "status": "REQUESTED",
            "contingency_type": "CONSTRUCTION",
            "requires_owner_approval": False,
        },
    )
    assert_money(draw["amount"], Decimal("45000.00"), "draw amount")

    denied = _decide(
        api,
        draw["id"],
        False,
        "the owner rejects the field-condition characterisation",
    )
    assert_fields(denied, {"status": "DENIED"})

    validate_error(
        api.post_draw(draw["id"], CM_HEADERS),
        ApiErrorId.DRAW_STATE_INVALID,
        409,
    )

    assert_fields(fixtures.read_draw(api, draw["id"]), {"status": "DENIED"})
    project = fixtures.read_project(api, project_id)
    assert_money_fields(
        project,
        {
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
        },
    )


def test_the_affordability_rule_is_live_once_the_draw_is_postable(
    api: ApiClient,
) -> None:
    """With the state rule satisfied, the same 45,000.00 fails against a 40,000.00 pot.

    PRD: "And the draw's `amount` must not exceed the remaining balance of its own pot: `owner_contingency_remaining` for an `OWNER` draw, `construction_contingency_remaining` for a `CONSTRUCTION` draw."

    PRD: "Approving advances the draw `REQUESTED → OWNER_APPROVED` and records `approved_by_user_id` from the acting `X-User-ID`."

    Design: Difficulty/priority_pair_validation_conflict/draw_state_invalid_priority_69_outranks_contingency_insufficient_priority_121
    """
    project_id, draw = _civic_centre_draw(api, Decimal("45000.00"))

    approved = _decide(
        api, draw["id"], True, "the owner accepts the field-condition characterisation"
    )
    assert_fields(approved, {"status": "OWNER_APPROVED"})

    validate_error(
        api.post_draw(draw["id"], CM_HEADERS),
        ApiErrorId.CONTINGENCY_INSUFFICIENT,
        422,
    )

    assert_fields(fixtures.read_draw(api, draw["id"]), {"status": "OWNER_APPROVED"})
    assert_money_fields(
        fixtures.read_project(api, project_id),
        {
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
        },
    )


def test_the_state_rule_is_live_on_a_draw_the_pot_could_have_afforded(
    api: ApiClient,
) -> None:
    """An affordable 30,000.00 draw that was declined is still unpostable.

    PRD: "Either decision is permitted only from `REQUESTED`, and any other starting status is rejected with `ERR_DRAW_STATE_INVALID` (HTTP 409); either increments the draw's `version`."

    PRD: "A successful post advances the draw `REQUESTED → POSTED` or `OWNER_APPROVED → POSTED` with identical ledger effects in both cases: `posted_at` is stamped from the logical clock, the drawn pot's remaining balance decreases by the draw's `amount`, and the project's `contingency_drawn_to_cost_total` increases by the same `amount`, leaving `gmp_amount` unmoved."

    Design: Difficulty/priority_pair_validation_conflict/draw_state_invalid_priority_69_outranks_contingency_insufficient_priority_121
    """
    project_id, draw = _civic_centre_draw(api, Decimal("30000.00"))
    assert_money(draw["amount"], Decimal("30000.00"), "draw amount")

    _decide(api, draw["id"], False, "the owner declines the characterisation")

    validate_error(
        api.post_draw(draw["id"], CM_HEADERS),
        ApiErrorId.DRAW_STATE_INVALID,
        409,
    )
    validate_error(
        api.approve_draw(
            draw["id"], factories.draw_approve_payload(True), OWNER_HEADERS
        ),
        ApiErrorId.DRAW_STATE_INVALID,
        409,
    )
    assert_money_fields(
        fixtures.read_project(api, project_id),
        {
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
        },
    )


def test_a_draw_of_exactly_fifty_thousand_posts_on_the_direct_path(
    api: ApiClient,
) -> None:
    """The threshold comparison is strict, so the draw sitting on it needs no signature.

    PRD: "If it is `CONSTRUCTION`, `requires_owner_approval` is true when any one of three conditions holds: the draw's `amount` is strictly greater than 50,000.00; or the project's `contingency_posture` at mint time is `CONSTRAINED`; or the draw's `origin` is `SUBCONTRACTOR_DEFAULT_PREMIUM`."

    PRD: "The threshold comparison is strict, on 2-decimal money: a construction draw of exactly 50,000.00 on an `OPEN`-posture project arising from a change-event classification does not require approval, while a draw of 50,000.01 does."

    PRD: "A successful post advances the draw `REQUESTED → POSTED` or `OWNER_APPROVED → POSTED` with identical ledger effects in both cases: `posted_at` is stamped from the logical clock, the drawn pot's remaining balance decreases by the draw's `amount`, and the project's `contingency_drawn_to_cost_total` increases by the same `amount`, leaving `gmp_amount` unmoved."

    Design: Difficulty/boundary_precision_check/construction_draw_at_exact_owner_approval_threshold_and_one_cent_above
    """
    project_id, draw = _hospital_tower_draw(api, Decimal("50000.00"))
    assert_fields(draw, {"requires_owner_approval": False, "status": "REQUESTED"})
    assert_money(draw["amount"], Decimal("50000.00"), "draw amount")

    posted = validate_success(api.post_draw(draw["id"], CM_HEADERS))
    assert_fields(posted, {"status": "POSTED"})
    assert_instant(posted["posted_at"], CLOCK_START, "posted_at")

    project = fixtures.read_project(api, project_id)
    assert_money_fields(
        project,
        {
            "construction_contingency_remaining": Decimal("190000.00"),
            "contingency_drawn_to_cost_total": Decimal("50000.00"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )
    assert_project_axes(project, contingency_posture="OPEN")
    assert_gmp_identity(project)


def test_one_cent_above_the_threshold_is_payable_only_through_the_approved_path(
    api: ApiClient,
) -> None:
    """50,000.01 is refused on the direct path and then posts once the owner signs.

    PRD: "A post attempted straight from `REQUESTED` is rejected with `ERR_OWNER_APPROVAL_REQUIRED` (HTTP 422) both when the draw's `requires_owner_approval` is true and, independently, whenever the posture is `CONSTRAINED` — a constrained project forces every draw down the owner-approved path regardless of how the flag was computed at mint time."

    PRD: "The threshold comparison is strict, on 2-decimal money: a construction draw of exactly 50,000.00 on an `OPEN`-posture project arising from a change-event classification does not require approval, while a draw of 50,000.01 does."

    PRD: "Approving advances the draw `REQUESTED → OWNER_APPROVED` and records `approved_by_user_id` from the acting `X-User-ID`."

    Design: Difficulty/boundary_precision_check/construction_draw_at_exact_owner_approval_threshold_and_one_cent_above
    """
    project_id, at_threshold = _hospital_tower_draw(api, Decimal("50000.00"))
    validate_success(api.post_draw(at_threshold["id"], CM_HEADERS))

    over = fixtures.requested_draw(
        api,
        project_id,
        Decimal("50000.01"),
        "CONTINGENCY_USE_CONSTRUCTION",
        origin="DESIGN_DEVELOPMENT",
        description="one cent over the approval threshold",
    )
    assert_fields(over, {"requires_owner_approval": True, "status": "REQUESTED"})
    assert_money(over["amount"], Decimal("50000.01"), "draw amount")

    validate_error(
        api.post_draw(over["id"], CM_HEADERS),
        ApiErrorId.OWNER_APPROVAL_REQUIRED,
        422,
    )
    assert_fields(fixtures.read_draw(api, over["id"]), {"status": "REQUESTED"})
    midway = fixtures.read_project(api, project_id)
    assert_money_fields(
        midway,
        {
            "construction_contingency_remaining": Decimal("190000.00"),
            "contingency_drawn_to_cost_total": Decimal("50000.00"),
        },
    )
    assert_project_axes(midway, contingency_posture="OPEN")

    _decide(api, over["id"], True, "the owner signs for the one-cent overage")
    posted = validate_success(api.post_draw(over["id"], CM_HEADERS))
    assert_fields(posted, {"status": "POSTED"})

    project = fixtures.read_project(api, project_id)
    assert_money_fields(
        project,
        {
            "construction_contingency_remaining": Decimal("139999.99"),
            "contingency_drawn_to_cost_total": Decimal("100000.01"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )
    assert_gmp_identity(project)


def test_voiding_a_posted_draw_restores_every_conserved_term_exactly(
    api: ApiClient,
) -> None:
    """The identity is checked before the post, between, and after the void.

    PRD: "The void advances the draw `POSTED → VOIDED`, stamps `voided_at` from the logical clock, records the supplied `void_reason`, returns the draw's `amount` to its pot's remaining balance and subtracts the same `amount` from `contingency_drawn_to_cost_total` — restoring both fields, and therefore all seven terms of the envelope identity, to exactly their pre-posting values."

    PRD: "A successful post advances the draw `REQUESTED → POSTED` or `OWNER_APPROVED → POSTED` with identical ledger effects in both cases: `posted_at` is stamped from the logical clock, the drawn pot's remaining balance decreases by the draw's `amount`, and the project's `contingency_drawn_to_cost_total` increases by the same `amount`, leaving `gmp_amount` unmoved."

    Design: Difficulty/compensating_invariant/contingency_draw_post_then_void_restores_the_seven_term_gmp_identity
    """
    project_id, draw = _hospital_tower_draw(api, Decimal("50000.00"))
    assert_money(draw["amount"], Decimal("50000.00"), "draw amount")

    before = fixtures.read_project(api, project_id)
    assert_gmp_identity(before)
    assert_money_fields(
        before,
        {
            "cost_of_work_budget_total": Decimal("40000000.00"),
            "general_conditions_total": Decimal("2500000.00"),
            "insurance_amount": Decimal("551171.88"),
            "cm_fee_amount": Decimal("1614418.95"),
            "owner_contingency_remaining": Decimal("1200000.00"),
            "construction_contingency_remaining": Decimal("240000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )

    validate_success(api.post_draw(draw["id"], CM_HEADERS))
    midway = fixtures.read_project(api, project_id)
    assert_gmp_identity(midway)
    assert_money_fields(
        midway,
        {
            "construction_contingency_remaining": Decimal("190000.00"),
            "contingency_drawn_to_cost_total": Decimal("50000.00"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )

    void_reason = "the winter protection was absorbed by the trade contractor"
    voided = validate_success(
        api.void_draw(
            draw["id"], factories.draw_void_payload(void_reason), OWNER_HEADERS
        )
    )
    assert_fields(voided, {"status": "VOIDED", "void_reason": void_reason})
    assert_instant(voided["voided_at"], CLOCK_START, "voided_at")

    after = fixtures.read_project(api, project_id)
    assert_gmp_identity(after)
    assert_unchanged(before, after, *CONSERVED_TERMS)
    assert_project_axes(after, contingency_posture="OPEN", gmp_status="EXECUTED")


def test_the_compensating_void_cannot_be_replayed_to_refill_the_pot_twice(
    api: ApiClient,
) -> None:
    """A second void on the same draw is refused, and the classification survives.

    PRD: "It is permitted only from `POSTED` (otherwise `ERR_DRAW_STATE_INVALID`, HTTP 409), only while the project's `closeout_status` has not reached `SETTLEMENT_EXECUTED`, and only while the posture is not `FROZEN` (otherwise `ERR_CONTINGENCY_FROZEN`, HTTP 409)."

    PRD: "Whichever branch is taken, the event advances `UNDER_REVIEW → CLASSIFIED`, its `classification` is written from the payload, `classified_by_user_id` is recorded from the acting `X-User-ID`, `classified_at` is stamped from the logical clock, and both the event's `version` and the project's `version` increment by 1."

    Design: Difficulty/compensating_invariant/contingency_draw_post_then_void_restores_the_seven_term_gmp_identity
    """
    project_id, draw = _hospital_tower_draw(api, Decimal("50000.00"))
    validate_success(api.post_draw(draw["id"], CM_HEADERS))
    void_reason = "the winter protection was absorbed by the trade contractor"
    validate_success(
        api.void_draw(
            draw["id"], factories.draw_void_payload(void_reason), OWNER_HEADERS
        )
    )

    validate_error(
        api.void_draw(
            draw["id"], factories.draw_void_payload(void_reason), OWNER_HEADERS
        ),
        ApiErrorId.DRAW_STATE_INVALID,
        409,
    )

    project = fixtures.read_project(api, project_id)
    assert_money_fields(
        project,
        {
            "construction_contingency_remaining": Decimal("240000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )
    assert_gmp_identity(project)
    event = fixtures.read_change_event(api, draw["change_event_id"])
    assert_fields(
        event,
        {"status": "CLASSIFIED", "classification": "CONTINGENCY_USE_CONSTRUCTION"},
    )
