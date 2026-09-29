"""The alternating network/studio counter cycle, its round ceiling and its exit."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    NEG_AGREED,
    NEG_NETWORK_OFFER,
    NEG_STUDIO_COUNTER,
    OFFER_SIDE_NETWORK,
    OFFER_SIDE_STUDIO,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import business_affairs_headers, studio_partner_headers

WRAP_STAMP = "2026-09-26T00:00:00.000Z"


def _opened(api):
    """A PILOT_DELIVERED project with a CERTIFIED screening and a fresh opening offer."""
    ctx = build_scenario(api, "certified")
    opening = validate_success(
        api.create_negotiation(
            f.negotiation_payload(ctx.project_id), business_affairs_headers()
        ),
        201,
    )
    ctx.negotiation_id = opening["id"]
    return ctx, opening


def _slate(api, ctx):
    return validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))


def test_the_counter_cycle_flips_sides_and_reconciles_the_reservation_by_delta(api):
    """Three counters walk NETWORK_OFFER -> STUDIO_COUNTER -> NETWORK_OFFER -> STUDIO_COUNTER.

    PRD 3.7: "the slate's `reserved_episode_count` is reconciled by the difference
    between the new `episode_count` and the old one - a counter that raises the count
    from 8 to 10 adds 2 to the reservation rather than reserving 10 a second time."

    Design: Difficulty/non_linear_state_machine/negotiation_offer_counter_cycle_flips_sides_and_stops_at_round_four
    """
    ctx, opening = _opened(api)

    assert opening["round_number"] == 1
    assert opening["status"] == NEG_NETWORK_OFFER
    assert opening["last_offer_side"] == OFFER_SIDE_NETWORK
    a.assert_cents(
        opening["total_license_commitment_cents"], 300000000, "total_license_commitment_cents"
    )
    assert opening["agreed_at"] is None
    assert opening["withdrawn_reason"] is None
    a.assert_slate_episode_ledger(
        _slate(api, ctx), committed=0, reserved=10, available=10, posture=POSTURE_OPEN
    )

    studio_counter = validate_success(
        api.table_round(
            ctx.negotiation_id,
            f.round_payload(12, 30000000, 1500, 60, 40),
            studio_partner_headers(),
        )
    )
    assert studio_counter["round_number"] == 2
    assert studio_counter["status"] == NEG_STUDIO_COUNTER
    assert studio_counter["last_offer_side"] == OFFER_SIDE_STUDIO
    a.assert_cents(
        studio_counter["total_license_commitment_cents"],
        360000000,
        "total_license_commitment_cents",
    )
    a.assert_slate_episode_ledger(
        _slate(api, ctx), committed=0, reserved=12, available=8, posture=POSTURE_RESTRICTED
    )

    network_counter = validate_success(
        api.table_round(
            ctx.negotiation_id,
            f.round_payload(11, 29000000, 1500, 70, 30),
            business_affairs_headers(),
        )
    )
    assert network_counter["round_number"] == 3
    assert network_counter["status"] == NEG_NETWORK_OFFER
    assert network_counter["last_offer_side"] == OFFER_SIDE_NETWORK
    a.assert_cents(
        network_counter["total_license_commitment_cents"],
        319000000,
        "total_license_commitment_cents",
    )
    a.assert_slate_episode_ledger(
        _slate(api, ctx), committed=0, reserved=11, available=9, posture=POSTURE_OPEN
    )

    final_counter = validate_success(
        api.table_round(
            ctx.negotiation_id,
            f.round_payload(10, 30000000, 2000, 65, 35),
            studio_partner_headers(),
        )
    )
    assert final_counter["round_number"] == 4
    assert final_counter["status"] == NEG_STUDIO_COUNTER
    assert final_counter["last_offer_side"] == OFFER_SIDE_STUDIO
    a.assert_cents(
        final_counter["total_license_commitment_cents"],
        300000000,
        "total_license_commitment_cents",
    )
    a.assert_slate_episode_ledger(
        _slate(api, ctx), committed=0, reserved=10, available=10, posture=POSTURE_OPEN
    )


def test_a_fifth_term_sheet_is_refused_and_the_non_offering_side_accepts(api):
    """At round_number 4 the counter is exhausted, and BusinessAffairs closes the studio sheet.

    PRD 3.7: "The negotiation's `round_number` must be below 4 for a counter to be
    accepted - four term sheets is the ceiling - else `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/negotiation_offer_counter_cycle_flips_sides_and_stops_at_round_four
    """
    ctx, _ = _opened(api)
    validate_success(
        api.table_round(
            ctx.negotiation_id,
            f.round_payload(12, 30000000, 1500, 60, 40),
            studio_partner_headers(),
        )
    )
    validate_success(
        api.table_round(
            ctx.negotiation_id,
            f.round_payload(11, 29000000, 1500, 70, 30),
            business_affairs_headers(),
        )
    )
    validate_success(
        api.table_round(
            ctx.negotiation_id,
            f.round_payload(10, 30000000, 2000, 65, 35),
            studio_partner_headers(),
        )
    )

    refused = api.table_round(
        ctx.negotiation_id,
        f.round_payload(10, 30000000, 2000, 65, 35),
        business_affairs_headers(),
    )
    validate_error(refused, e.ERR_NEGOTIATION_ROUNDS_EXHAUSTED, 422)

    rows = validate_success(
        api.list_project_negotiations(ctx.project_id, business_affairs_headers())
    )
    standing = next(row for row in rows if row["id"] == ctx.negotiation_id)
    assert standing["round_number"] == 4, "the refused counter moved nothing"
    assert standing["status"] == NEG_STUDIO_COUNTER
    assert standing["last_offer_side"] == OFFER_SIDE_STUDIO

    agreed = validate_success(
        api.accept_negotiation(ctx.negotiation_id, business_affairs_headers())
    )
    assert agreed["status"] == NEG_AGREED
    a.assert_instant(agreed["agreed_at"], WRAP_STAMP, "agreed_at")

    a.assert_slate_episode_ledger(
        _slate(api, ctx), committed=10, reserved=0, available=10, posture=POSTURE_OPEN
    )
