"""Cross-entity state dependencies: a confirmation that turns on the status and
scope rank of a certification grant hanging off another aggregate, and two
byte-identical retail rows that resolve differently because a shared fiscal
aggregate moved between them.
"""

from test_helpers import (
    ApiErrorId,
    assert_folio_contents,
    assert_list_count,
    assert_state_pair,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_QUOTED_PRICE_CENTS, CANON_START_AT
from test_helpers import factories as f
from test_helpers import fixtures as fx

REVOKER = "co-4"


def _requested_appointment_world():
    """The canonical world with one appointment left in REQUESTED x PENDING and the
    therapist's ADVANCED HYDROTHERAPY grant still ACTIVE."""
    world = fx.build_world()
    world.appointments["a"] = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)
    return world


def test_revoking_the_grant_makes_an_untouched_requested_appointment_unconfirmable():
    """Nothing about the appointment changes, yet confirmation now fails.

    PRD §3.3: "Revocation is the one transition the API exposes: it sets `status`
    to `REVOKED`, records the revoking officer as `revoked_by_user_id`, accepts an
    optional `reason_note`, and immediately removes that therapist from the
    eligible pool for every treatment requiring that skill."

    PRD §3.6: "Confirmation deliberately re-runs the clinical and credential gates
    rather than trusting the booking-time verdict, because hours or days may have
    passed and the logical clock may have moved: the authoritative intake form
    must still be `SCREENED_CLEAR` or `OVERRIDDEN` (`ERR_INTAKE_NOT_CLEARED`),
    consent must still match `required_consent_version` (`ERR_CONSENT_MISSING`),
    the contraindication check must still pass (`ERR_CONTRAINDICATION_PRESENT`),
    the licence must still be `VERIFIED` for the practice state
    (`ERR_LICENSE_NOT_VERIFIED`) and unexpired at the clock date
    (`ERR_LICENSE_EXPIRED`), the certification must still satisfy the required
    skill and scope rank (`ERR_SCOPE_OF_PRACTICE_VIOLATION`), the therapist must
    still be `ACTIVE` (`ERR_THERAPIST_NOT_ACTIVE`) and the room must still be
    `ACTIVE` (`ERR_ROOM_UNAVAILABLE`)."

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_certification_grant_status_and_scope
    """
    world = _requested_appointment_world()
    appointment_id = world.appointments["a"]["id"]

    revoked = fx.revoke_certification(world.certification_id, user=REVOKER,
                                      reason_note="board audit finding")
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_by_user_id"] == REVOKER

    appointment = world.fetch_appointment(appointment_id)
    assert_state_pair(appointment, "REQUESTED", "PENDING", None)
    assert appointment["quoted_price_cents"] == CANON_QUOTED_PRICE_CENTS, (
        "the revoke touched a grant on the therapist aggregate, not the "
        "appointment's frozen quote")

    therapist = world.fetch_therapist()
    assert therapist["status"] == "ACTIVE", (
        "the therapist is still ACTIVE, so only the certification dependency can "
        "explain the refusal")

    response = api_client.confirm_appointment(appointment_id, {}, fx.COORDINATOR)
    validate_error(response, ApiErrorId.ERR_SCOPE_OF_PRACTICE_VIOLATION.value, 409)

    assert world.fetch_room()["booked_minutes_total"] == 120, (
        "a refused confirmation commits nothing and releases nothing")


def test_a_basic_regrant_is_still_below_the_required_advanced_scope_rank():
    """Re-granting the skill is not enough; the rank has to reach ADVANCED.

    PRD §3.1: "Scope levels are ranked, with `BASIC` ranked 1 and `ADVANCED`
    ranked 2, and a therapist satisfies the requirement when their granted rank is
    at least the required rank — so an `ADVANCED` grant satisfies a `BASIC`
    requirement but never the reverse."

    PRD §3.6: "Confirmation is also the transition that advances the second
    dimension: `clearance_status` moves `PENDING → CLEARED` and
    `clearance_block_reason` is set to null."

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_certification_grant_status_and_scope
    """
    world = _requested_appointment_world()
    appointment_id = world.appointments["a"]["id"]
    fx.revoke_certification(world.certification_id, user=REVOKER,
                            reason_note="board audit finding")

    basic = fx.grant_certification(world.therapist_id, user=REVOKER,
                                   scope_level="BASIC", granted_on="2026-08-04")
    assert basic["scope_level"] == "BASIC" and basic["status"] == "ACTIVE"
    validate_error(
        api_client.confirm_appointment(appointment_id, {}, fx.COORDINATOR),
        ApiErrorId.ERR_SCOPE_OF_PRACTICE_VIOLATION.value, 409)

    advanced = fx.grant_certification(world.therapist_id, user=REVOKER,
                                      scope_level="ADVANCED",
                                      granted_on="2026-08-05")
    assert advanced["scope_level"] == "ADVANCED"

    confirmed = validate_success(
        api_client.confirm_appointment(appointment_id, {}, fx.COORDINATOR))
    assert_state_pair(confirmed, "CONFIRMED", "CLEARED", None)

    assert world.fetch_room()["booked_minutes_total"] == 120


# ---------------------------------------------------------------------------
# The fiscal aggregate dependency
# ---------------------------------------------------------------------------

def _three_recommendation_world():
    """A checked-in appointment whose guest's folio limit (55100) leaves room for
    exactly one of three identical 4595c recommendations."""
    world = fx.world_with_checked_in_appointment(
        arrival_clock=CANON_START_AT,
        guest_overrides={"folio_limit_cents": 55100})
    appointment_id = world.appointments["a"]["id"]
    attachments = []
    for sku in ("MARINE-SERUM-30", "MARINE-BALM-50", "MARINE-MIST-10"):
        attachments.append(validate_success(api_client.create_retail_attachment(
            appointment_id, f.retail_attachment_payload(product_sku=sku),
            world.therapist_headers), 201))
    return world, attachments


def test_identical_retail_rows_resolve_differently_as_the_shared_folio_moves():
    """The second purchase fails on an aggregate the attachment never references.

    PRD §3.7: "That purchase is subject to the folio capacity rule: when the
    guest's current `folio_balance_cents` plus the attachment's `amount_cents`
    would exceed `folio_limit_cents`, the resolution is rejected with
    `ERR_FOLIO_LIMIT_EXCEEDED` (HTTP 402) and nothing is written."

    PRD §3.7: "A new recommendation lands in `status` `RECOMMENDED` with
    `resolved_by_user_id` and `resolved_at` both null, and it posts nothing to the
    folio; it is a tracked recommendation, not a sale."

    Design: Difficulty/cross_entity_state_dependency/retail_purchase_depends_on_guest_folio_aggregate
    """
    world, attachments = _three_recommendation_world()
    assert world.fetch_guest()["folio_balance_cents"] == 50504, (
        "check-in posted the provisional folio total against a 55100c limit")

    purchased = validate_success(api_client.resolve_retail_attachment(
        attachments[0]["id"], f.resolve_payload("PURCHASED"), world.guest_headers))
    assert purchased["status"] == "PURCHASED"
    assert world.fetch_guest()["folio_balance_cents"] == 55099, (
        "50504 + 4595 lands exactly one cent under the limit")

    refused = api_client.resolve_retail_attachment(
        attachments[1]["id"], f.resolve_payload("PURCHASED"), world.guest_headers)
    validate_error(refused, ApiErrorId.ERR_FOLIO_LIMIT_EXCEEDED.value, 402)

    still_open = validate_success(api_client.list_retail_attachments(
        world.appointments["a"]["id"], world.therapist_headers,
        params={"status": "RECOMMENDED"}))
    blocked = [row for row in still_open if row["id"] == attachments[1]["id"]]
    assert len(blocked) == 1, (
        "the refused attachment is byte-identical to the purchased one in its own "
        "fields and must remain RECOMMENDED")
    assert blocked[0]["resolved_by_user_id"] is None
    assert blocked[0]["resolved_at"] is None
    assert world.fetch_guest()["folio_balance_cents"] == 55099, (
        "nothing is written when the fiscal gate rejects the resolution")


def test_declining_a_recommendation_is_not_subject_to_the_folio_capacity_gate():
    """The limit binds only the PURCHASED branch of the same state machine.

    PRD §3.7: "With `outcome` `DECLINED`, the attachment moves
    `RECOMMENDED → DECLINED`, records `resolved_by_user_id` and `resolved_at` in
    exactly the same way, and posts nothing at all."

    PRD §2.7 rung 30: "**Folio capacity** — the guest's `folio_balance_cents` plus
    the amount about to post does not exceed the guest's `folio_limit_cents`.
    Applies to resolving a retail attachment as purchased and to appointment
    check-in."

    Design: Difficulty/cross_entity_state_dependency/retail_purchase_depends_on_guest_folio_aggregate
    """
    world, attachments = _three_recommendation_world()
    appointment_id = world.appointments["a"]["id"]
    validate_success(api_client.resolve_retail_attachment(
        attachments[0]["id"], f.resolve_payload("PURCHASED"), world.guest_headers))
    validate_error(
        api_client.resolve_retail_attachment(
            attachments[1]["id"], f.resolve_payload("PURCHASED"),
            world.guest_headers),
        ApiErrorId.ERR_FOLIO_LIMIT_EXCEEDED.value, 402)

    declined = validate_success(api_client.resolve_retail_attachment(
        attachments[2]["id"], f.resolve_payload("DECLINED"), world.guest_headers))
    assert declined["status"] == "DECLINED"
    assert declined["resolved_by_user_id"] == world.guest_id
    assert declined["resolved_at"] is not None
    assert world.fetch_guest()["folio_balance_cents"] == 55099, (
        "a decline posts nothing at all, so the balance is unchanged")

    postings = assert_list_count(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR),
        2, "appointment folio postings")
    assert_folio_contents(postings, [("TREATMENT", 50504), ("RETAIL", 4595)],
                          "appointment folio")

    remaining = validate_success(api_client.list_retail_attachments(
        appointment_id, world.therapist_headers,
        params={"status": "RECOMMENDED"}))
    assert len(remaining) == 1, (
        f"only the refused purchase is still RECOMMENDED, got {len(remaining)}")
    assert remaining[0]["id"] == attachments[1]["id"]
