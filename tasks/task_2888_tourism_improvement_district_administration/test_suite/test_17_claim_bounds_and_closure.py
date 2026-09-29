"""Room-night claims: the capacity ceiling, the window edge and the closure gate.

All three tests run against the same running program — committed at 62,000 cents
with a booking window of [2026-09-01, 2026-12-01) — and against the perimeter
boutique's sixty rooms, so every ceiling in them is arithmetic on figures the
program and the property already carry.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLAIMS_PENDING_VERIFICATION,
    ERR_CLAIM_EXCEEDS_CAPACITY,
    ERR_CLAIM_OUTSIDE_BOOKING_WINDOW,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_ratio_four_dp,
)
from test_helpers.test_users import ADMIN, DMO_LIAISON, DMO_LIAISON_USER_ID


def _running_program_mid_window(api):
    """The canonical running program with the clock advanced to 2026-09-25, well
    inside the booking window and before every stay these tests claim."""
    ctx = fx.running_program(api)
    fx.set_clock(api, "2026-09-25T00:00:00Z")
    return ctx


# --------------------------------------------------------------------------
# The physical ceiling, at submission and again at verification
# --------------------------------------------------------------------------
def test_a_claim_and_its_verification_are_each_bounded_at_a_hundred_and_twenty_nights(api):
    """Sixty rooms across the two whole nights of [2026-09-10, 2026-09-12) can sell
    120 room nights and no more.  A 121-night claim is refused, the 120-night claim is
    accepted, a verification allowing 121 of those 120 nights is refused, and allowing
    exactly 120 succeeds.  Both ceilings are inclusive and neither is the other's.

    PRD 3.8: "room_nights must not exceed the property's room_count multiplied by the
    number of whole nights in the stay interval, since a property cannot sell more
    room nights than it has rooms. A claim beyond that physical capacity is refused
    with ERR_CLAIM_EXCEEDS_CAPACITY."

    PRD 3.8: "ALLOW moves the claim SUBMITTED to VERIFIED, storing
    verified_room_nights — which defaults to the claim's full room_nights when
    omitted, must be at least 1, and may never exceed room_nights, an excess being
    refused with ERR_CLAIM_EXCEEDS_CAPACITY".

    Design: Corner/errors/room_night_claims_are_bounded_by_room_count_times_nights_at_submission_and_at_verification
    """
    ctx = _running_program_mid_window(api)
    boutique = validate_success(api.get_lodging_business(ctx.b3_id, headers=ADMIN))
    assert_fields(boutique, room_count=60, status="ASSESSABLE")

    validate_error(
        api.create_room_night_claim(
            ctx.mp_id,
            f.room_night_claim_payload(
                ctx.b3_id, "2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z", 121
            ),
            headers=DMO_LIAISON,
        ),
        ERR_CLAIM_EXCEEDS_CAPACITY,
        expected_status=409,
    )
    _, empty = validate_paginated(
        api.list_program_room_night_claims(ctx.mp_id, headers=ADMIN)
    )
    assert empty["total_count"] == 0, (
        "the refused claim must not have been recorded, got %r" % (empty,)
    )

    claim = fx.submit_claim(
        api,
        ctx,
        business_key="b3_id",
        key="rnc_cap",
        stay_start="2026-09-10T00:00:00Z",
        stay_end="2026-09-12T00:00:00Z",
        room_nights=120,
    )
    assert_fields(claim, status="SUBMITTED", room_nights=120, rejection_reason="NONE")
    assert_null_fields(claim, "verified_room_nights", "verified_by_user_id")

    validate_error(
        api.verify_room_night_claim(
            ctx.rnc_cap,
            f.verification_payload("ALLOW", verified_room_nights=121),
            headers=DMO_LIAISON,
        ),
        ERR_CLAIM_EXCEEDS_CAPACITY,
        expected_status=409,
    )
    still_submitted = validate_success(api.get_room_night_claim(ctx.rnc_cap, headers=ADMIN))
    assert_fields(still_submitted, status="SUBMITTED", room_nights=120)
    assert_null_fields(still_submitted, "verified_room_nights", "verified_by_user_id")

    verified = fx.verify_claim(
        api, ctx, claim_key="rnc_cap", verified_room_nights=120
    )
    assert_fields(
        verified,
        status="VERIFIED",
        verified_room_nights=120,
        verified_by_user_id=DMO_LIAISON_USER_ID,
    )

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(program, status="RUNNING", verified_room_nights=120)
    assert_null_fields(program, "closed_at")


# --------------------------------------------------------------------------
# The half-open edge of the booking window
# --------------------------------------------------------------------------
def test_a_stay_beginning_at_the_windows_close_is_out_and_one_ending_there_is_in(api):
    """The window closes at 2026-12-01, exclusively.  A stay that starts on that
    instant sits outside it, and a stay that ends on that instant sits inside it.
    Nothing else separates the two calls: both claim fifty nights, well inside the
    property's capacity, and neither overlaps the other.

    PRD 3.8: "The program must be RUNNING and the claimed stay must fall entirely
    inside the program's half-open booking window; a stay extending one hour past
    booking_window_end, or a claim against a program not yet launched, is refused with
    ERR_CLAIM_OUTSIDE_BOOKING_WINDOW."

    Design: Corner/errors/a_stay_outside_the_half_open_booking_window_is_refused_and_the_closing_edge_is_accepted
    """
    ctx = _running_program_mid_window(api)
    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(program, status="RUNNING")
    assert_instant_equals(
        program["booking_window_end"], "2026-12-01T00:00:00Z", "booking_window_end"
    )

    validate_error(
        api.create_room_night_claim(
            ctx.mp_id,
            f.room_night_claim_payload(
                ctx.b3_id, "2026-12-01T00:00:00Z", "2026-12-03T00:00:00Z", 50
            ),
            headers=DMO_LIAISON,
        ),
        ERR_CLAIM_OUTSIDE_BOOKING_WINDOW,
        expected_status=409,
    )

    on_the_edge = fx.submit_claim(
        api,
        ctx,
        business_key="b3_id",
        key="rnc_edge",
        stay_start="2026-11-29T00:00:00Z",
        stay_end="2026-12-01T00:00:00Z",
        room_nights=50,
    )
    assert_fields(on_the_edge, status="SUBMITTED", room_nights=50, rejection_reason="NONE")
    assert_instant_equals(on_the_edge["stay_end"], "2026-12-01T00:00:00Z", "stay_end")

    claims, meta = validate_paginated(
        api.list_program_room_night_claims(ctx.mp_id, headers=ADMIN)
    )
    assert meta["total_count"] == 1, (
        "only the accepted stay may have been recorded, got %r" % (meta,)
    )
    assert claims[0]["id"] == ctx.rnc_edge, (
        "the single claim must be the one ending on the exclusive bound, got %r"
        % (claims[0],)
    )


# --------------------------------------------------------------------------
# Closure waits for the last submitted claim
# --------------------------------------------------------------------------
def test_closure_waits_for_the_pending_claim_and_then_publishes_its_nights(api):
    """A hundred claimed nights sit unverified, and the closure is refused rather
    than published without them.  Verifying the claim opens the gate, and the figures
    the closure then publishes are computed from exactly those nights: 62,000 cents
    over 100 nights is 620 gross, which is TIER_EFFICIENT, whose 40 percent share
    leaves 37,200 net and an index of 6.7204.

    PRD 3.8: "And no claim of the program may still be SUBMITTED, refused with
    ERR_CLAIMS_PENDING_VERIFICATION, because measurement reads verified nights only
    and an unverified claim would silently drop out of the published index."

    PRD 3.8: "On success the program moves RUNNING to CLOSED, closed_at is stamped
    from the logical clock, and the performance figures are written."

    Design: Corner/errors/a_program_closure_waits_for_every_submitted_claim_to_be_verified
    """
    ctx = _running_program_mid_window(api)
    pending = fx.submit_claim(api, ctx, business_key="b3_id", key="rnc_b3", room_nights=100)
    assert_fields(pending, status="SUBMITTED", room_nights=100)

    validate_error(
        api.close_marketing_program(
            ctx.mp_id, f.program_closure_payload(), headers=DMO_LIAISON
        ),
        ERR_CLAIMS_PENDING_VERIFICATION,
        expected_status=409,
    )
    unpublished = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(
        unpublished,
        status="RUNNING",
        verified_room_nights=0,
        performance_flag="NOT_MEASURED",
        dmo_cost_share_cents=0,
        net_district_cost_cents=0,
    )
    assert_null_fields(
        unpublished,
        "closed_at",
        "gross_cost_per_room_night_cents",
        "efficiency_tier",
        "net_cost_per_room_night_cents",
    )

    verified = fx.verify_claim(api, ctx, claim_key="rnc_b3")
    assert_fields(
        verified,
        status="VERIFIED",
        verified_room_nights=100,
        verified_by_user_id=DMO_LIAISON_USER_ID,
    )

    closed = validate_success(
        api.close_marketing_program(
            ctx.mp_id, f.program_closure_payload(), headers=DMO_LIAISON
        )
    )
    assert_fields(
        closed,
        status="CLOSED",
        verified_room_nights=100,
        gross_cost_per_room_night_cents=620,
        efficiency_tier="TIER_EFFICIENT",
        dmo_cost_share_cents=24800,
        net_district_cost_cents=37200,
        net_cost_per_room_night_cents=372,
        performance_flag="MEETS_BENCHMARK",
    )
    assert_ratio_four_dp(closed["performance_index"], 6.7204, "performance_index")
    assert_instant_equals(closed["closed_at"], "2026-09-25T00:00:00Z", "closed_at")
