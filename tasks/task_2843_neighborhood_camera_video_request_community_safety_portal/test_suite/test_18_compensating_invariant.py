"""Conserved totals: the solicitation cardinality and the footage-seconds ledger.

Two quantities in this portal are conserved rather than accumulated. A video
request's ``solicitation_count`` is a cardinality that never moves once the
canvass has been dispatched: every answer, revocation and lapse shifts one unit
between the five buckets beneath it. A resident's
``lifetime_shared_footage_seconds`` is a duration ledger that never decreases:
purging footage moves seconds from the retained side to the purged side instead
of destroying them.

Each test below walks a sequence of observation points and checks the conserved
total at every one of them, including at a step that touches no bucket at all,
and then checks that the compensating movement really landed on the counterpart
bucket rather than the total quietly drifting.
"""

from typing import Any, Dict, List

from test_helpers import ApiClient, assertions, constants as k, fixtures

# The two clock instants the walks move to. The first sits past the 72-hour
# response deadline of a request submitted at the scenario clock; the second
# sits past the retention expiry of every clip shared in this file.
AFTER_DEADLINE_CLOCK = "2026-08-15T01:00:00Z"
AFTER_RETENTION_CLOCK = "2026-10-01T00:00:00Z"

# Two non-overlapping footage segments inside the standard six-hour window:
# 30 minutes from 01:00, then 10 minutes from 01:30, touching at one endpoint.
CLIP_A_START = "2026-08-08T01:00:00Z"
CLIP_A_SECONDS = 1800
CLIP_B_START = "2026-08-08T01:30:00Z"
CLIP_B_SECONDS = 600
BOTH_CLIPS_SECONDS = CLIP_A_SECONDS + CLIP_B_SECONDS

# Each clip's retention expiry: the earliest of the agency candidate
# (2026-09-11T00:00:00Z), the device candidate and the portal candidate
# (2026-09-29T00:00:00Z) is in both cases the device candidate.
CLIP_A_EXPIRES = "2026-09-07T01:00:00Z"
CLIP_B_EXPIRES = "2026-09-07T01:30:00Z"


def _solicitations_by_household(
    api: ApiClient, world: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """The solicitation this canvass aimed at each household's camera, in order."""
    return [
        fixtures.solicitation_for_device(api, world["request_id"], household["device_id"])
        for household in world["households"]
    ]


def test_solicitation_total_holds_at_every_step_of_a_revoked_share(
    api: ApiClient,
) -> None:
    """The five buckets move one unit at a time while the total stays at three.

    PRD: "For every video request, `solicitation_count` equals the sum of `pending_count`, `shared_count`, `declined_count`, `expired_count` and `withdrawn_count`."
    PRD: "`solicitation_count` is monotonic — it never decreases — so any operation that moves a solicitation out of one bucket must move it into another, and the compensating path that revokes an already-given consent moves one unit out of `shared_count` and into `withdrawn_count` rather than reducing the total."
    PRD: "A request's `provisional_share_rate_bps` is the live share rate over that request's own solicitations, computed in basis points as described in §2.7: the numerator is the number of the request's solicitations in `SHARED`, the denominator is the number of the request's solicitations in total — every one of them, including those still `SOLICITED`, those `WITHDRAWN`, and those whose notification was suppressed."

    Design: Difficulty/compensating_invariant/solicitation_cardinality_conserved_when_owner_revokes_a_share
    """
    world = fixtures.seed_standard_canvass(api)
    households = world["households"]
    sol_one, sol_two, sol_three = _solicitations_by_household(api, world)

    # Observation point one: the canvass has just been dispatched to three
    # cameras and every one of them is still awaiting an answer.
    at_dispatch = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(at_dispatch, 3, 0, 0, 0, 0)
    assertions.assert_solicitation_ledger(at_dispatch, total=3)
    assertions.assert_bps(at_dispatch["provisional_share_rate_bps"], 0)

    # Observation point two: the nearest owner shares one segment.
    clip = fixtures.share_footage(
        api,
        sol_one["id"],
        households[0]["resident_id"],
        recorded_start_utc=CLIP_A_START,
        duration_seconds=CLIP_A_SECONDS,
    )
    after_share = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(after_share, 2, 1, 0, 0, 0)
    assertions.assert_solicitation_ledger(after_share, total=3)
    assertions.assert_bps(after_share["provisional_share_rate_bps"], 3333)

    # Observation point three: the second owner records a refusal.
    fixtures.decline_solicitation(api, sol_two["id"], households[1]["resident_id"])
    after_decline = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(after_decline, 1, 1, 1, 0, 0)
    assertions.assert_solicitation_ledger(after_decline, total=3)
    assertions.assert_bps(after_decline["provisional_share_rate_bps"], 3333)

    # Observation point four: the first owner revokes the consent they gave by
    # purging the only clip it covered.
    fixtures.purge_clip(
        api,
        clip["id"],
        households[0]["headers"],
        purge_reason=k.PURGE_OWNER_REVOCATION,
    )
    after_revocation = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(after_revocation, 1, 0, 1, 0, 1)
    assertions.assert_solicitation_ledger(after_revocation, total=3)
    assertions.assert_bps(after_revocation["provisional_share_rate_bps"], 0)
    assert after_revocation["lifecycle_state"] == k.LIFECYCLE_SOLICITING, (
        "One solicitation is still awaiting an answer, so the request is still "
        f"soliciting: {after_revocation['lifecycle_state']!r}"
    )

    revoked = fixtures.read_solicitation(api, sol_one["id"])
    assertions.assert_subset(
        revoked,
        {"status": k.SOLICITATION_WITHDRAWN, "clip_count": 1},
    )
    purged = fixtures.read_clip(api, clip["id"])
    assertions.assert_subset(
        purged,
        {"status": k.CLIP_PURGED, "purge_reason": k.PURGE_OWNER_REVOCATION},
    )

    # Observation point five: moving the clock touches no bucket at all.
    fixtures.set_clock(api, AFTER_DEADLINE_CLOCK)
    after_clock = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(after_clock, 1, 0, 1, 0, 1)
    assertions.assert_solicitation_ledger(after_clock, total=3)

    # Observation point six: the sweep lapses the last unanswered solicitation
    # and the request settles with nothing shared.
    sweep = fixtures.run_sweep(api)
    assertions.assert_subset(
        sweep,
        {
            "solicitations_expired_count": 1,
            "clips_purged_count": 0,
            "requests_auto_closed_count": 1,
        },
    )
    at_rest = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(at_rest, 0, 0, 1, 1, 1)
    assertions.assert_solicitation_ledger(at_rest, total=3)
    assertions.assert_bps(at_rest["provisional_share_rate_bps"], 0)
    assert at_rest["lifecycle_state"] == k.LIFECYCLE_EXHAUSTED, (
        "No solicitation is shared, so the request is exhausted rather than "
        f"fulfilled: {at_rest['lifecycle_state']!r}"
    )

    lapsed = fixtures.read_solicitation(api, sol_three["id"])
    assert lapsed["status"] == k.SOLICITATION_EXPIRED, (
        f"A solicitation nobody answered lapses to expired: {lapsed['status']!r}"
    )
    assertions.assert_nulls(lapsed, "decline_reason")


def test_owner_revocation_moves_one_unit_from_shared_into_withdrawn(
    api: ApiClient,
) -> None:
    """The revocation debits `shared_count` and credits `withdrawn_count`, not the total.

    PRD: "When `purge_reason` is `OWNER_REVOCATION` or `ACCOUNT_DEACTIVATED` and no non-purged clip remains for that solicitation, the solicitation cascades `SHARED → WITHDRAWN` as described in §3.5, moving one unit from the request's `shared_count` into its `withdrawn_count` and recomputing `provisional_share_rate_bps`."
    PRD: "`solicitation_count` is monotonic — it never decreases — so any operation that moves a solicitation out of one bucket must move it into another, and the compensating path that revokes an already-given consent moves one unit out of `shared_count` and into `withdrawn_count` rather than reducing the total."

    Design: Difficulty/compensating_invariant/solicitation_cardinality_conserved_when_owner_revokes_a_share
    """
    world = fixtures.seed_standard_canvass(api)
    households = world["households"]
    sol_one = _solicitations_by_household(api, world)[0]

    clip = fixtures.share_footage(
        api,
        sol_one["id"],
        households[0]["resident_id"],
        recorded_start_utc=CLIP_A_START,
        duration_seconds=CLIP_A_SECONDS,
    )
    before = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(before, 2, 1, 0, 0, 0)

    fixtures.purge_clip(
        api,
        clip["id"],
        households[0]["headers"],
        purge_reason=k.PURGE_OWNER_REVOCATION,
    )
    after = fixtures.read_request(api, world["request_id"])

    # The compensating movement is a transfer between two buckets: exactly one
    # unit leaves the share bucket and exactly one unit arrives in the
    # withdrawal bucket.
    assert after["shared_count"] == before["shared_count"] - 1, (
        "The revocation must debit shared_count by exactly one: "
        f"{before['shared_count']} -> {after['shared_count']}"
    )
    assert after["withdrawn_count"] == before["withdrawn_count"] + 1, (
        "The revocation must credit withdrawn_count by exactly one: "
        f"{before['withdrawn_count']} -> {after['withdrawn_count']}"
    )

    # Nothing else moved: the total is untouched and the consent was not
    # re-opened as an unanswered ask, which is what a naive re-derivation of the
    # buckets from the surviving clips would have produced.
    assert after["solicitation_count"] == before["solicitation_count"], (
        "solicitation_count never decreases: "
        f"{before['solicitation_count']} -> {after['solicitation_count']}"
    )
    assert after["pending_count"] == before["pending_count"], (
        "A revoked consent is withdrawn, not returned to the pending bucket: "
        f"{before['pending_count']} -> {after['pending_count']}"
    )
    assertions.assert_solicitation_buckets(after, 2, 0, 0, 0, 1)
    assertions.assert_solicitation_ledger(after, total=3)
    assertions.assert_bps(after["provisional_share_rate_bps"], 0)

    revoked = fixtures.read_solicitation(api, sol_one["id"])
    assert revoked["status"] == k.SOLICITATION_WITHDRAWN, (
        "The compensating path is SHARED -> WITHDRAWN, never a return to "
        f"SOLICITED: {revoked['status']!r}"
    )
    assert revoked["responded_at"] is not None, (
        "The withdrawal stamps responded_at from the logical clock"
    )
    assert revoked["clip_count"] == 1, (
        "The clip the consent once covered still counts on the solicitation: "
        f"{revoked['clip_count']}"
    )
    assert after["version"] > before["version"], (
        "The cascade mutated the request, so its version advanced: "
        f"{before['version']} -> {after['version']}"
    )


def test_request_settles_exhausted_because_its_only_share_was_compensated_away(
    api: ApiClient,
) -> None:
    """A canvass whose single share was revoked resolves to exhausted, not fulfilled.

    PRD: "Whenever any of these five paths leaves a request's `pending_count` at 0, the lifecycle dimension resolves itself immediately."
    PRD: "If none is, it moves `SOLICITING → EXHAUSTED` and `provisional_share_rate_bps` is set to 0."
    PRD: "When the retention sweep of §3.6 finds a solicitation still in `SOLICITED` whose `respond_deadline_utc` is at or before the logical clock, it moves it `SOLICITED → EXPIRED`, stamps `responded_at`, and — diverging from the decline branch — leaves `decline_reason` null, because the owner said nothing and the portal records nothing on their behalf."

    Design: Difficulty/compensating_invariant/solicitation_cardinality_conserved_when_owner_revokes_a_share
    """
    world = fixtures.seed_standard_canvass(api)
    households = world["households"]
    sol_one, sol_two, sol_three = _solicitations_by_household(api, world)

    clip = fixtures.share_footage(
        api,
        sol_one["id"],
        households[0]["resident_id"],
        recorded_start_utc=CLIP_A_START,
        duration_seconds=CLIP_A_SECONDS,
    )
    fixtures.decline_solicitation(api, sol_two["id"], households[1]["resident_id"])
    fixtures.purge_clip(
        api,
        clip["id"],
        households[0]["headers"],
        purge_reason=k.PURGE_OWNER_REVOCATION,
    )

    fixtures.set_clock(api, AFTER_DEADLINE_CLOCK)
    fixtures.run_sweep(api)

    settled = fixtures.read_request(api, world["request_id"])
    assert settled["lifecycle_state"] == k.LIFECYCLE_EXHAUSTED, (
        "The one share this canvass received was compensated away, so no "
        "solicitation is shared and the request is exhausted: "
        f"{settled['lifecycle_state']!r}"
    )
    assertions.assert_solicitation_buckets(settled, 0, 0, 1, 1, 1)
    assertions.assert_solicitation_ledger(settled, total=3)
    assertions.assert_bps(settled["provisional_share_rate_bps"], 0)

    # Every unit of the conserved total is accounted for by exactly one
    # solicitation, and not one of them is left in the share bucket.
    statuses = [
        fixtures.read_solicitation(api, sol["id"])["status"]
        for sol in (sol_one, sol_two, sol_three)
    ]
    assert statuses == [
        k.SOLICITATION_WITHDRAWN,
        k.SOLICITATION_DECLINED,
        k.SOLICITATION_EXPIRED,
    ], f"Expected withdrawn, declined and expired in dispatch order, got {statuses}"
    assert k.SOLICITATION_SHARED not in statuses, (
        "The revoked consent must not still read as shared at resolution time"
    )


def test_footage_seconds_ledger_balances_at_every_step_of_two_purges(
    api: ApiClient,
) -> None:
    """Lifetime seconds stay at 2400 while the retained side empties into the purged side.

    PRD: "For every resident, `lifetime_shared_footage_seconds` equals `retained_footage_seconds` plus `purged_footage_seconds`."
    PRD: "Whichever of the three paths applies — `RETAINED → PURGED`, `LEGAL_HOLD → PURGED` or `PURGE_PENDING → PURGED` — the clip's `status` becomes `PURGED`, `purged_at` is stamped from the logical clock, the supplied `purge_reason` is recorded, `duration_seconds` moves out of the owner's `retained_footage_seconds` and into their `purged_footage_seconds` — leaving `lifetime_shared_footage_seconds` unchanged, exactly as the footage-seconds ledger of §2.11 demands — and the clip's `version` advances by 1."
    PRD: "In every other compliance posture — `JUSTIFICATION_PENDING`, `JUSTIFICATION_LOGGED`, `AUDIT_FLAGGED` or `AUDIT_CLEARED` — the clip is `DEVICE_ANCHORED`: its `retention_expires_at` is the **earliest** of all three candidates, so whichever of the resident's own camera retention, the agency's window and the portal grace period runs out first wins, and the clip's initial `status` is `RETAINED`."
    PRD: "The **device candidate** is the clip's `recorded_start_utc` advanced by the source camera's `retention_window_days` whole days."

    Design: Difficulty/compensating_invariant/footage_seconds_conserved_across_owner_purge_then_retention_purge
    """
    world = fixtures.seed_standard_canvass(api)
    owner = world["households"][0]
    sol_one = _solicitations_by_household(api, world)[0]

    # Observation point one: a freshly registered account owes and holds nothing.
    at_registration = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_footage_ledger(at_registration, lifetime=0, retained=0, purged=0)

    # One consent covers two non-overlapping segments from the same camera.
    clip_a = fixtures.share_footage(
        api,
        sol_one["id"],
        owner["resident_id"],
        recorded_start_utc=CLIP_A_START,
        duration_seconds=CLIP_A_SECONDS,
    )
    assertions.assert_subset(
        clip_a,
        {
            "status": k.CLIP_RETAINED,
            "retention_variant": k.RETENTION_DEVICE_ANCHORED,
            "duration_seconds": CLIP_A_SECONDS,
        },
    )
    assertions.assert_instant(
        clip_a["retention_expires_at"], CLIP_A_EXPIRES, "retention_expires_at"
    )

    clip_b = fixtures.share_footage(
        api,
        sol_one["id"],
        owner["resident_id"],
        recorded_start_utc=CLIP_B_START,
        duration_seconds=CLIP_B_SECONDS,
    )
    assertions.assert_subset(
        clip_b,
        {
            "status": k.CLIP_RETAINED,
            "retention_variant": k.RETENTION_DEVICE_ANCHORED,
            "duration_seconds": CLIP_B_SECONDS,
        },
    )
    assertions.assert_instant(
        clip_b["retention_expires_at"], CLIP_B_EXPIRES, "retention_expires_at"
    )

    # Observation point two: both segments are shared and wholly retained.
    after_shares = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_footage_ledger(
        after_shares, lifetime=BOTH_CLIPS_SECONDS, retained=BOTH_CLIPS_SECONDS, purged=0
    )

    # Observation point three: the owner revokes the first segment only.
    fixtures.purge_clip(
        api, clip_a["id"], owner["headers"], purge_reason=k.PURGE_OWNER_REVOCATION
    )
    after_owner_purge = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_footage_ledger(
        after_owner_purge,
        lifetime=BOTH_CLIPS_SECONDS,
        retained=CLIP_B_SECONDS,
        purged=CLIP_A_SECONDS,
    )
    assertions.assert_subset(
        fixtures.read_clip(api, clip_a["id"]),
        {"status": k.CLIP_PURGED, "purge_reason": k.PURGE_OWNER_REVOCATION},
    )
    still_shared = fixtures.read_solicitation(api, sol_one["id"])
    assertions.assert_subset(
        still_shared, {"status": k.SOLICITATION_SHARED, "clip_count": 2}
    )

    # Observation point four: the sweep purges the surviving segment on retention
    # expiry, emptying the retained bucket without touching the lifetime figure.
    fixtures.set_clock(api, AFTER_RETENTION_CLOCK)
    sweep = fixtures.run_sweep(api)
    assertions.assert_subset(
        sweep,
        {
            "clips_purged_count": 1,
            "solicitations_expired_count": 2,
            "clips_held_count": 0,
            "requests_auto_closed_count": 1,
        },
    )
    at_rest = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_footage_ledger(
        at_rest, lifetime=BOTH_CLIPS_SECONDS, retained=0, purged=BOTH_CLIPS_SECONDS
    )
    assertions.assert_subset(
        fixtures.read_clip(api, clip_b["id"]),
        {"status": k.CLIP_PURGED, "purge_reason": k.PURGE_RETENTION_EXPIRED},
    )

    consent = fixtures.read_solicitation(api, sol_one["id"])
    assertions.assert_subset(consent, {"status": k.SOLICITATION_SHARED, "clip_count": 2})
    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(request, 0, 1, 0, 2, 0)
    assertions.assert_solicitation_ledger(request, total=3)
    assertions.assert_subset(
        request,
        {"shared_clip_count": 2, "lifecycle_state": k.LIFECYCLE_FULFILLED},
    )
    assertions.assert_bps(request["provisional_share_rate_bps"], 3333)


def test_each_purge_moves_exactly_its_own_clip_duration_out_of_retained(
    api: ApiClient,
) -> None:
    """Every purge debits retained and credits purged by that clip's own seconds.

    PRD: "Whichever of the three paths applies — `RETAINED → PURGED`, `LEGAL_HOLD → PURGED` or `PURGE_PENDING → PURGED` — the clip's `status` becomes `PURGED`, `purged_at` is stamped from the logical clock, the supplied `purge_reason` is recorded, `duration_seconds` moves out of the owner's `retained_footage_seconds` and into their `purged_footage_seconds` — leaving `lifetime_shared_footage_seconds` unchanged, exactly as the footage-seconds ledger of §2.11 demands — and the clip's `version` advances by 1."
    PRD: "`lifetime_shared_footage_seconds` is monotonic and is never decremented."
    PRD: "It moves every clip in `RETAINED` whose `retention_expires_at` is at or before the clock to `PURGED` with `purge_reason` `RETENTION_EXPIRED`, moving the seconds across and leaving the solicitation in `SHARED`."

    Design: Difficulty/compensating_invariant/footage_seconds_conserved_across_owner_purge_then_retention_purge
    """
    world = fixtures.seed_standard_canvass(api)
    owner = world["households"][0]
    sol_one = _solicitations_by_household(api, world)[0]

    clip_a = fixtures.share_footage(
        api,
        sol_one["id"],
        owner["resident_id"],
        recorded_start_utc=CLIP_A_START,
        duration_seconds=CLIP_A_SECONDS,
    )
    clip_b = fixtures.share_footage(
        api,
        sol_one["id"],
        owner["resident_id"],
        recorded_start_utc=CLIP_B_START,
        duration_seconds=CLIP_B_SECONDS,
    )
    before = fixtures.read_resident(api, owner["resident_id"])

    # The owner-initiated purge moves that one clip's seconds and no more: the
    # surviving clip's seconds stay on the retained side.
    fixtures.purge_clip(
        api, clip_a["id"], owner["headers"], purge_reason=k.PURGE_OWNER_REVOCATION
    )
    after_first = fixtures.read_resident(api, owner["resident_id"])
    assert after_first["retained_footage_seconds"] == (
        before["retained_footage_seconds"] - clip_a["duration_seconds"]
    ), (
        "The purge debits retained_footage_seconds by exactly this clip's "
        f"duration: {before['retained_footage_seconds']} -> "
        f"{after_first['retained_footage_seconds']}"
    )
    assert after_first["purged_footage_seconds"] == (
        before["purged_footage_seconds"] + clip_a["duration_seconds"]
    ), (
        "The purge credits purged_footage_seconds by exactly this clip's "
        f"duration: {before['purged_footage_seconds']} -> "
        f"{after_first['purged_footage_seconds']}"
    )
    assert (
        after_first["lifetime_shared_footage_seconds"]
        == before["lifetime_shared_footage_seconds"]
    ), (
        "Purging seconds never decrements the lifetime figure: "
        f"{before['lifetime_shared_footage_seconds']} -> "
        f"{after_first['lifetime_shared_footage_seconds']}"
    )
    assertions.assert_footage_ledger(after_first)

    # The sweep's retention purge of the second clip moves its seconds the same
    # way, again leaving the lifetime figure exactly where it was.
    fixtures.set_clock(api, AFTER_RETENTION_CLOCK)
    fixtures.run_sweep(api)
    after_second = fixtures.read_resident(api, owner["resident_id"])
    assert after_second["retained_footage_seconds"] == (
        after_first["retained_footage_seconds"] - clip_b["duration_seconds"]
    ), (
        "The retention purge debits retained_footage_seconds by exactly the "
        f"swept clip's duration: {after_first['retained_footage_seconds']} -> "
        f"{after_second['retained_footage_seconds']}"
    )
    assert after_second["purged_footage_seconds"] == (
        after_first["purged_footage_seconds"] + clip_b["duration_seconds"]
    ), (
        "The retention purge credits purged_footage_seconds by exactly the "
        f"swept clip's duration: {after_first['purged_footage_seconds']} -> "
        f"{after_second['purged_footage_seconds']}"
    )
    assert (
        after_second["lifetime_shared_footage_seconds"]
        == before["lifetime_shared_footage_seconds"]
    ), (
        "All the footage is gone and the lifetime figure still stands: "
        f"{before['lifetime_shared_footage_seconds']} -> "
        f"{after_second['lifetime_shared_footage_seconds']}"
    )
    assertions.assert_footage_ledger(
        after_second, lifetime=BOTH_CLIPS_SECONDS, retained=0, purged=BOTH_CLIPS_SECONDS
    )


def test_neither_purge_withdraws_the_consent_behind_the_two_clips(
    api: ApiClient,
) -> None:
    """One purge spares the consent because a clip survives, the other because it expired.

    PRD: "When `purge_reason` is `OWNER_REVOCATION` or `ACCOUNT_DEACTIVATED` and no non-purged clip remains for that solicitation, the solicitation cascades `SHARED → WITHDRAWN` as described in §3.5, moving one unit from the request's `shared_count` into its `withdrawn_count` and recomputing `provisional_share_rate_bps`."
    PRD: "When `purge_reason` is `RETENTION_EXPIRED`, the solicitation stays `SHARED`, no request counter moves at all, and the historical fact that consent was given survives the deletion of the footage."
    PRD: "For every resident, `lifetime_shared_footage_seconds` equals `retained_footage_seconds` plus `purged_footage_seconds`."

    Design: Difficulty/compensating_invariant/footage_seconds_conserved_across_owner_purge_then_retention_purge
    """
    world = fixtures.seed_standard_canvass(api)
    owner = world["households"][0]
    sol_one = _solicitations_by_household(api, world)[0]

    clip_a = fixtures.share_footage(
        api,
        sol_one["id"],
        owner["resident_id"],
        recorded_start_utc=CLIP_A_START,
        duration_seconds=CLIP_A_SECONDS,
    )
    clip_b = fixtures.share_footage(
        api,
        sol_one["id"],
        owner["resident_id"],
        recorded_start_utc=CLIP_B_START,
        duration_seconds=CLIP_B_SECONDS,
    )

    # The owner revokes one of the two segments. A non-purged clip still remains
    # under this consent, so the compensating SHARED -> WITHDRAWN path does not
    # fire and no request bucket moves.
    fixtures.purge_clip(
        api, clip_a["id"], owner["headers"], purge_reason=k.PURGE_OWNER_REVOCATION
    )
    after_owner_purge = fixtures.read_solicitation(api, sol_one["id"])
    assert after_owner_purge["status"] == k.SOLICITATION_SHARED, (
        "A clip still survives under this consent, so it is not withdrawn: "
        f"{after_owner_purge['status']!r}"
    )
    request_after_owner_purge = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(request_after_owner_purge, 2, 1, 0, 0, 0)
    assertions.assert_solicitation_ledger(request_after_owner_purge, total=3)
    assertions.assert_bps(
        request_after_owner_purge["provisional_share_rate_bps"], 3333
    )

    # The sweep then purges the surviving segment on retention expiry, which is
    # the branch that never revokes consent: the solicitation stays shared even
    # though not one second of its footage is retained any more.
    fixtures.set_clock(api, AFTER_RETENTION_CLOCK)
    fixtures.run_sweep(api)

    assertions.assert_subset(
        fixtures.read_clip(api, clip_b["id"]),
        {"status": k.CLIP_PURGED, "purge_reason": k.PURGE_RETENTION_EXPIRED},
    )
    after_sweep = fixtures.read_solicitation(api, sol_one["id"])
    assert after_sweep["status"] == k.SOLICITATION_SHARED, (
        "A retention-expiry purge leaves the consent as historically given: "
        f"{after_sweep['status']!r}"
    )
    assert after_sweep["clip_count"] == 2, (
        f"Both segments still count on the consent: {after_sweep['clip_count']}"
    )

    settled = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(settled, 0, 1, 0, 2, 0)
    assertions.assert_solicitation_ledger(settled, total=3)
    assertions.assert_bps(settled["provisional_share_rate_bps"], 3333)
    assert settled["lifecycle_state"] == k.LIFECYCLE_FULFILLED, (
        "One solicitation is still shared, so the request is fulfilled rather "
        f"than exhausted: {settled['lifecycle_state']!r}"
    )

    # One bucket is empty and the ledger still balances.
    at_rest = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_footage_ledger(
        at_rest, lifetime=BOTH_CLIPS_SECONDS, retained=0, purged=BOTH_CLIPS_SECONDS
    )
    assert clip_a["duration_seconds"] + clip_b["duration_seconds"] == (
        at_rest["purged_footage_seconds"]
    ), (
        "Both clips' seconds landed on the purged side: "
        f"{at_rest['purged_footage_seconds']}"
    )
