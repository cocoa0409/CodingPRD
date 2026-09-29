"""Queue A - rule ``cross_entity_state_dependency``.

Three instances in which the blocking state lives on an entity the request does
not talk about, and in which disarming only that entity turns the same request
from a rejection into a success.
"""

import re

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPEAL_NOT_EXHAUSTED,
    ERR_DISPUTE_INVALID_STATE,
    ERR_FACILITY_NOT_OPEN,
    ERR_TARIFF_NOT_PUBLISHED,
    ERR_TARIFF_WITHDRAWN,
)
from test_helpers.assertions import (
    assert_end_of_day,
    assert_error_meta_is_minimal,
    assert_instant_eq,
    assert_server_minted_id,
    assert_subset_equal,
    error_id_of,
)
from test_helpers.constants import (
    ACCESS_MODE_GATE_CONTROLLED,
    ACCESS_MODE_OPEN,
    BILLING_POSTURE_CURRENT,
    BILLING_UNBILLED,
    CHARGE_FINAL,
    CLOCK_AT_COMPLAINT,
    COLD_START_CLOCK,
    CLOCK_BASIS_ACTUAL,
    CLOCK_BASIS_CONSTRUCTIVE,
    CLOCK_BASIS_NONE,
    COMPLAINT_FILED,
    COMPLAINT_RESPONSE_DUE_AT,
    COMPLAINT_TYPE_BILLING_PRACTICE,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_ACTUAL_EXPIRY,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_RELEASE_AT,
    DECISION_DENIED,
    DISPUTE_DECIDED,
    DISPUTE_ESCALATED,
    DISPUTE_POSTURE_ESCALATED,
    DISPUTE_UNDER_REVIEW,
    DOCKET_NUMBER_PATTERN,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_CONSTRUCTIVELY_PLACED,
    MOVEMENT_ORDERED,
    MOVEMENT_RELEASED,
    SCOPE_WHOLE_INVOICE,
    TARIFF_STATUS_DRAFT,
    TARIFF_STATUS_PUBLISHED,
)
from test_helpers.test_users import AGENT, OFFICER, make_customer_headers

# --- instance 18 literals --------------------------------------------------
CLOCK_AT_SPOT_ATTEMPT = "2026-08-05T10:00:00.000Z"

# --- instance 19 literals --------------------------------------------------
ADJUDICATOR_R7I2_A = "adj-r7i2-a"
ADJUDICATOR_R7I2_B = "adj-r7i2-b"
FIRST_DOCKET_NUMBER = "D-00001"


def _noticed_cycle_at_a_gate_controlled_track(api):
    """A CONSTRUCTIVELY_PLACED, notified cycle whose facility is GATE_CONTROLLED.

    ``GATE_CONTROLLED`` is deliberately neither ``OPEN`` nor ``EMBARGOED``: PRD
    3.1 makes it the one posture on which the placement check and the release
    check disagree.
    """
    world = fx.reference_world(api)
    cycle = fx.noticed_cycle(api, world)
    assert cycle["movement_status"] == MOVEMENT_CONSTRUCTIVELY_PLACED

    gated = fx.set_access_mode(api, world["facility_id"], ACCESS_MODE_GATE_CONTROLLED)
    assert gated["access_mode"] == ACCESS_MODE_GATE_CONTROLLED
    assert gated["occupied_spot_count"] == 0

    fx.set_clock(api, CLOCK_AT_SPOT_ATTEMPT)
    return world, fx.get_cycle(api, cycle["id"])


# ===========================================================================
# instance: actual_placement_blocked_by_facility_access_mode_not_by_cycle_state
# ===========================================================================
def test_a_gate_controlled_facility_refuses_a_spot_the_cycle_state_permits(api):
    """The cycle is in a legal source state; the other entity does the refusing.

    PRD 3.4: "The facility's `access_mode` must be exactly `OPEN`; a
    `GATE_CONTROLLED` or `EMBARGOED` facility yields `ERR_FACILITY_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/actual_placement_blocked_by_facility_access_mode_not_by_cycle_state
    """
    world, before = _noticed_cycle_at_a_gate_controlled_track(api)
    payload = f.actual_placement_payload(CYCLE_A_ACTUAL_AT)

    refused = api.actual_placement(before["id"], payload, AGENT)
    validate_error(refused, ERR_FACILITY_NOT_OPEN)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    # Not one field on the cycle moved, including its OCC version.
    after = fx.get_cycle(api, before["id"])
    assert after == before
    assert_subset_equal(
        after,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "actual_placement_at": None,
            "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
        },
    )
    gated = fx.set_access_mode(api, world["facility_id"], ACCESS_MODE_GATE_CONTROLLED)
    assert gated["occupied_spot_count"] == 0

    # Open only the facility and the byte-identical request now succeeds.
    opened = fx.set_access_mode(api, world["facility_id"], ACCESS_MODE_OPEN)
    assert opened["access_mode"] == ACCESS_MODE_OPEN
    fx.place_actually(api, before["id"], CYCLE_A_ACTUAL_AT)

    spotted = fx.get_cycle(api, before["id"])
    assert_subset_equal(
        spotted,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "clock_basis": CLOCK_BASIS_ACTUAL,
        },
    )
    assert_instant_eq(
        spotted["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )
    assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 1


def test_the_same_gate_controlled_posture_still_lets_the_car_out(api):
    """The dependency is asymmetric: the posture that blocks the spot allows the release.

    PRD 3.5: "The facility's `access_mode` must be `OPEN` or `GATE_CONTROLLED` - a
    gate-controlled facility blocks new spots but never blocks a release - and an
    `EMBARGOED` facility yields `ERR_FACILITY_EMBARGOED`."

    Design: Difficulty/cross_entity_state_dependency/actual_placement_blocked_by_facility_access_mode_not_by_cycle_state
    """
    world = fx.reference_world(api)
    cycle = fx.actually_placed_cycle(api, world)
    assert cycle["movement_status"] == MOVEMENT_ACTUALLY_PLACED

    gated = fx.set_access_mode(api, world["facility_id"], ACCESS_MODE_GATE_CONTROLLED)
    assert gated["access_mode"] == ACCESS_MODE_GATE_CONTROLLED
    assert gated["occupied_spot_count"] == 1

    fx.set_clock(api, CYCLE_A_RELEASE_AT)
    fx.release_cycle(api, cycle["id"], CYCLE_A_RELEASE_AT, world["customer_id"])

    released = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        released,
        {
            "movement_status": MOVEMENT_RELEASED,
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
        },
    )
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert charge["status"] == CHARGE_FINAL
    assert charge["gross_amount_cents"] == CYCLE_A_GROSS_CENTS

    # The facility was never reopened; the release simply did not care.
    still_gated = fx.set_access_mode(
        api, world["facility_id"], ACCESS_MODE_GATE_CONTROLLED
    )
    assert still_gated["access_mode"] == ACCESS_MODE_GATE_CONTROLLED
    assert still_gated["occupied_spot_count"] == 0


def _invoice_with_an_under_review_dispute(api):
    """One 47550-cent ISSUED invoice with a WHOLE_INVOICE dispute at UNDER_REVIEW."""
    world = fx.reference_world(api)
    fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    dispute = fx.under_review_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        ADJUDICATOR_R7I2_A,
        scope=SCOPE_WHOLE_INVOICE,
    )
    assert dispute["status"] == DISPUTE_UNDER_REVIEW
    return world, invoice, dispute


def _attempt_complaint(api, dispute_id, customer_id):
    return api.create_regulatory_complaint(
        f.complaint_payload(dispute_id, COMPLAINT_TYPE_BILLING_PRACTICE),
        make_customer_headers(customer_id),
    )


# ===========================================================================
# instance: regulatory_complaint_requires_a_twice_decided_dispute
# ===========================================================================
def test_the_state_gate_and_the_exhaustion_gate_are_independent(api):
    """Two different codes at two different statuses, from the same other entity.

    PRD 3.9: "The two failure modes must not be confused: a dispute that is not
    `DECIDED` at all fails the state band first and reports
    `ERR_DISPUTE_INVALID_STATE`, and `ERR_APPEAL_NOT_EXHAUSTED` is reserved for
    the narrower case of a `DECIDED` dispute that never went to appeal."

    Design: Difficulty/cross_entity_state_dependency/regulatory_complaint_requires_a_twice_decided_dispute
    """
    world, _invoice, dispute = _invoice_with_an_under_review_dispute(api)
    customer_id = world["customer_id"]

    first = _attempt_complaint(api, dispute["id"], customer_id)
    validate_error(first, ERR_DISPUTE_INVALID_STATE)
    assert first.status_code == 409
    assert_error_meta_is_minimal(first)
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_UNDER_REVIEW

    decided = fx.decide(api, dispute["id"], ADJUDICATOR_R7I2_A, DECISION_DENIED, 0)
    assert decided["status"] == DISPUTE_DECIDED
    assert decided["round_number"] == 1

    second = _attempt_complaint(api, dispute["id"], customer_id)
    validate_error(second, ERR_APPEAL_NOT_EXHAUSTED)
    assert second.status_code == 422
    # The state gate is satisfied and the round gate is not: two live conditions.
    assert error_id_of(second) != ERR_DISPUTE_INVALID_STATE
    assert second.status_code != 409
    assert_error_meta_is_minimal(second)

    unchanged = fx.get_dispute(api, dispute["id"])
    assert_subset_equal(
        unchanged, {"status": DISPUTE_DECIDED, "round_number": 1}
    )
    assert unchanged["version"] == decided["version"]


def test_filing_after_the_second_round_cascades_back_into_the_dispute(api):
    """The third attempt is accepted, and its docket proves the first two filed nothing.

    PRD 3.9: "The escalated dispute moves `DECIDED -> ESCALATED` and the
    consignee's `dispute_posture` re-derives to `ESCALATED`, which outranks
    `UNDER_REVIEW` in that field's own precedence."

    Design: Difficulty/cross_entity_state_dependency/regulatory_complaint_requires_a_twice_decided_dispute
    """
    world, _invoice, dispute = _invoice_with_an_under_review_dispute(api)
    customer_id = world["customer_id"]

    validate_error(
        _attempt_complaint(api, dispute["id"], customer_id), ERR_DISPUTE_INVALID_STATE
    )
    fx.decide(api, dispute["id"], ADJUDICATOR_R7I2_A, DECISION_DENIED, 0)
    validate_error(
        _attempt_complaint(api, dispute["id"], customer_id), ERR_APPEAL_NOT_EXHAUSTED
    )

    fx.appealed_dispute(api, dispute["id"], customer_id)
    fx.begin_review(api, dispute["id"], ADJUDICATOR_R7I2_B)
    round_two = fx.decide(api, dispute["id"], ADJUDICATOR_R7I2_B, DECISION_DENIED, 0)
    assert_subset_equal(
        round_two,
        {
            "status": DISPUTE_DECIDED,
            "round_number": 2,
            "allowed_credit_cents": 0,
        },
    )

    complaint = fx.filed_complaint(api, dispute["id"], customer_id)
    assert_server_minted_id(complaint["id"])
    assert_subset_equal(
        complaint,
        {
            "status": COMPLAINT_FILED,
            "complaint_type": COMPLAINT_TYPE_BILLING_PRACTICE,
            "demurrage_dispute_id": dispute["id"],
            "tariff_rule_set_id": None,
            "answer_narrative": None,
            "ordered_credit_cents": 0,
        },
    )
    assert_instant_eq(complaint["filed_at"], CLOCK_AT_COMPLAINT, "filed_at")
    assert_end_of_day(complaint["response_due_at"], "response_due_at")
    assert_instant_eq(
        complaint["response_due_at"], COMPLAINT_RESPONSE_DUE_AT, "response_due_at"
    )
    assert re.match(DOCKET_NUMBER_PATTERN, complaint["docket_number"])
    # D-00001 means this is the first complaint row ever: the two 4xx filed nothing.
    assert complaint["docket_number"] == FIRST_DOCKET_NUMBER

    escalated = fx.get_dispute(api, dispute["id"])
    assert escalated["status"] == DISPUTE_ESCALATED
    assert (
        fx.get_customer(api, customer_id)["dispute_posture"]
        == DISPUTE_POSTURE_ESCALATED
    )
    # A BILLING_PRACTICE complaint never touches the tariff.
    tariff = fx.get_tariff(api, world["tariff_id"])
    assert tariff["status"] == TARIFF_STATUS_PUBLISHED
    assert tariff["challenge_count"] == 0


def _everything_ready_except_the_tariff(api):
    """A free car, an OPEN track, a CURRENT consignee - and a tariff still DRAFT.

    Nothing the create request talks about is in a blocking state; the only
    obstacle is two entities away on the pinned rate table.
    """
    fx.set_clock(api, COLD_START_CLOCK)
    customer = fx.make_customer(api)
    facility = fx.make_industry_track(api)
    car = fx.make_rail_car(api)
    tariff = fx.make_draft_tariff(api)

    assert customer["billing_posture"] == BILLING_POSTURE_CURRENT
    assert facility["access_mode"] == ACCESS_MODE_OPEN
    assert car["active_cycle_count"] == 0
    assert car["version"] == 1
    assert tariff["status"] == TARIFF_STATUS_DRAFT

    payload = f.placement_cycle_payload(
        customer["id"], car["id"], facility["id"], tariff["id"], car["version"]
    )
    return customer, facility, car, tariff, payload


# ===========================================================================
# instance: placement_cycle_create_gated_by_tariff_rule_set_publication
# ===========================================================================
def test_a_draft_tariff_blocks_the_create_from_two_entities_away(api):
    """DRAFT is not WITHDRAWN and it is not absent: it is simply not in force.

    PRD 3.2: "And a rule set that is `DRAFT` or `SUPERSEDED` is simply not in
    force, yielding `ERR_TARIFF_NOT_PUBLISHED`. Only `PUBLISHED` and `CHALLENGED`
    rule sets pass; as §3.1 noted, a challenge does not suspend a tariff."

    Design: Difficulty/cross_entity_state_dependency/placement_cycle_create_gated_by_tariff_rule_set_publication
    """
    _customer, _facility, car, tariff, payload = _everything_ready_except_the_tariff(api)

    refused = api.create_placement_cycle(payload, AGENT)
    validate_error(refused, ERR_TARIFF_NOT_PUBLISHED)
    assert refused.status_code == 422
    assert error_id_of(refused) != ERR_TARIFF_WITHDRAWN
    assert refused.status_code != 404
    assert_error_meta_is_minimal(refused)

    published = get_success_data(api.publish_tariff_rule_set(tariff["id"], OFFICER))
    assert published["status"] == TARIFF_STATUS_PUBLISHED
    assert published["version"] == tariff["version"] + 1

    # The byte-identical retry, same OCC token and all, is now accepted.
    created = get_success_data(api.create_placement_cycle(payload, AGENT), 201)
    assert_subset_equal(
        created,
        {
            "movement_status": MOVEMENT_ORDERED,
            "billing_status": BILLING_UNBILLED,
            "clock_basis": CLOCK_BASIS_NONE,
            "tariff_rule_set_id": tariff["id"],
            "customer_id": _customer["id"],
            "rail_car_id": car["id"],
        },
    )
    assert created["actual_placement_at"] is None
    assert created["constructive_placement_at"] is None


def test_the_refused_create_consumes_no_occ_token_and_mints_no_charge(api):
    """Three rejections in a row all reuse version 1, because none of them wrote.

    PRD 2.7: "A successful create increments the car's `version` by 1 and
    re-derives its `active_cycle_count`, so a second create replaying the first
    request's `expected_rail_car_version` necessarily fails - which is exactly how
    two agents ordering the same car serialise into one cycle rather than two."

    Design: Difficulty/cross_entity_state_dependency/placement_cycle_create_gated_by_tariff_rule_set_publication
    """
    _customer, _facility, car, tariff, payload = _everything_ready_except_the_tariff(api)

    for _attempt in range(3):
        refused = api.create_placement_cycle(payload, AGENT)
        validate_error(refused, ERR_TARIFF_NOT_PUBLISHED)
        untouched = fx.get_car(api, car["id"])
        assert untouched["version"] == car["version"]
        assert untouched["active_cycle_count"] == 0

    get_success_data(api.publish_tariff_rule_set(tariff["id"], OFFICER))
    created = get_success_data(api.create_placement_cycle(payload, AGENT), 201)

    # Only the successful create moved the car.
    moved = fx.get_car(api, car["id"])
    assert moved["version"] == car["version"] + 1
    assert moved["active_cycle_count"] == 1

    # The charge line is born at constructive placement, not at ordering.
    assert fx.charges_of_cycle(api, created["id"]) == []
