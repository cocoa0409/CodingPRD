"""Two figures computed twice over one identical body of facts.

The portal computes two different answers from the same rows in two unrelated
places, and both places are specified so that the two answers diverge rather
than merely rescale one another.

In the agency-reporting domain a transparency report carries both a provisional
and a certified share rate over one set of consent solicitations: the certified
inclusion set drops the unresolved rows *and* the shared row whose notification
was suppressed, so the certified figure is not the provisional figure over a
smaller denominator and lands below it.

In the retention domain the same is true of a shared clip's expiry: two clips
offering byte-identical footage off the same request land on different retention
instants because the parent's compliance posture changed between them, and the
two variants read the same three candidate instants in opposite directions.
"""

from typing import Any, Dict, List

from test_helpers import ApiClient, assertions, canonical_instant, constants as k, fixtures
from test_helpers.test_users import PLATFORM_ADMIN_SECOND_ID

# Five camera owners on one 500 m disc at the origin, at squared distances
# 100, 400, 900, 1600 and 2500 from the centre.
_FIVE_POSITIONS = ((0, 10), (0, 20), (0, 30), (0, 40), (0, 50))

# 2026-08-12T00:00:00Z + 72 hours: the deadline every solicitation of this
# canvass carries, and the request's own expires_at.
_RESPOND_DEADLINE = "2026-08-15T00:00:00Z"

# One hour past that deadline, so the sweep may lapse the silent owners while
# no clip has come anywhere near its retention instant.
_CLOCK_PAST_DEADLINE = "2026-08-15T01:00:00Z"

# The reporting window the report is compiled over, half-open around 12 August.
_PERIOD_START = "2026-08-01T00:00:00Z"
_PERIOD_END = "2026-09-01T00:00:00Z"

# The footage segment both retention clips offer: identical start, identical
# length, inside the justified 2026-08-08T00:00:00Z..06:00:00Z window.
_RECORDED_START = "2026-08-08T01:00:00Z"
_DURATION_SECONDS = 1800

# The three candidate instants that bound both retention clips.
#   agency candidate  shared_at 2026-08-12T00:00:00Z + 30 days
#   device candidate  recorded_start 2026-08-08T01:00:00Z + 30 days
#   portal candidate  expires_at 2026-08-15T00:00:00Z + 45 days
_AGENCY_CANDIDATE = "2026-09-11T00:00:00Z"
_DEVICE_CANDIDATE = "2026-09-07T01:00:00Z"
_PORTAL_CANDIDATE = "2026-09-29T00:00:00Z"

# Well past the later of the two, so one clip is sweepable and one is not.
_CLOCK_PAST_BOTH_EXPIRIES = "2026-10-01T00:00:00Z"


def _seed_five_camera_canvass(
    api: ApiClient,
    *,
    muted_index: int = 0,
    case_number: str = "CASE-9001",
) -> Dict[str, Any]:
    """A submitted canvass over five camera owners, one optionally hard-muted.

    Pins the clock, onboards one agency with a device floor of three and a
    thirty-day agency retention window, enrols one requesting officer, seeds one
    resident owning one camera at each of the five grid points, then draws and
    locks a 500 m area at the origin over the standard six-hour footage window,
    opens a request against it, logs its justification and submits it. The
    resident at ``muted_index`` (1-based, 0 for nobody) registers with a hard
    notification mute, so that owner can still answer while their solicitation
    notification is suppressed.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(
        api,
        min_device_threshold=3,
        max_open_requests=3,
        period_request_quota=20,
        post_share_retention_days=30,
        justification_min_chars=80,
    )
    households: List[Dict[str, Any]] = []
    for index, (x, y) in enumerate(_FIVE_POSITIONS, start=1):
        name = f"R{index}"
        households.append(
            fixtures.seed_resident_with_device(
                api,
                display_name=name,
                email=f"{name.lower()}@example.test",
                x=x,
                y=y,
                alert_radius_m=0,
                notification_budget_per_day=6,
                notification_mute_enabled=True if index == muted_index else None,
                label=f"{name} camera",
                retention_window_days=30,
            )
        )
    world["households"] = households
    world["resident_ids"] = [h["resident_id"] for h in households]
    world.update(
        fixtures.seed_submitted_request(
            api, world["agency_id"], world["officer_id"], case_number=case_number
        )
    )
    world["solicitation_for"] = {
        row["resident_id"]: row for row in world["solicitations"]
    }
    return world


def _answer_three_then_sweep(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """R1 and R2 share, R3 declines, R4 and R5 are lapsed by the sweep."""
    r1, r2, r3 = world["resident_ids"][0], world["resident_ids"][1], world["resident_ids"][2]
    fixtures.share_footage(
        api,
        world["solicitation_for"][r1]["id"],
        r1,
        recorded_start_utc=_RECORDED_START,
        duration_seconds=_DURATION_SECONDS,
    )
    fixtures.share_footage(
        api,
        world["solicitation_for"][r2]["id"],
        r2,
        recorded_start_utc="2026-08-08T02:00:00Z",
        duration_seconds=1200,
    )
    fixtures.decline_solicitation(
        api,
        world["solicitation_for"][r3]["id"],
        r3,
        decline_reason=k.DECLINE_OWNER_DECLINE,
    )
    fixtures.set_clock(api, _CLOCK_PAST_DEADLINE)
    return fixtures.run_sweep(api)


def _compile_report(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a report over the reporting window, quoting the version just read."""
    agency = fixtures.read_agency(api, world["agency_id"])
    return fixtures.compile_report(
        api, agency, period_start_utc=_PERIOD_START, period_end_utc=_PERIOD_END
    )


def test_provisional_rate_counts_the_suppressed_share_in_numerator_and_denominator(
    api: ApiClient,
) -> None:
    """Two shares of five solicitations leave the request's live rate at 4000 bps.

    PRD: "A request's `provisional_share_rate_bps` is the live share rate over that request's own solicitations, computed in basis points as described in §2.7: the numerator is the number of the request's solicitations in `SHARED`, the denominator is the number of the request's solicitations in total — every one of them, including those still `SOLICITED`, those `WITHDRAWN`, and those whose notification was suppressed."
    PRD: "One share out of three solicitations is 3333 basis points; two out of three is 6667; two out of five is 4000; one out of four is 2500."

    Design: Difficulty/dual_variant_calc/share_rate_provisional_vs_certified_diverge_on_suppressed_share
    """
    world = _seed_five_camera_canvass(api, muted_index=2)
    assert world["area"]["eligible_device_count"] == 5
    assert world["area"]["effective_min_devices"] == 3
    assert len(world["solicitations"]) == 5

    _answer_three_then_sweep(api, world)

    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_ledger(request, total=5)
    assertions.assert_solicitation_buckets(
        request, pending=0, shared=2, declined=1, expired=2, withdrawn=0
    )
    assert request["lifecycle_state"] == k.LIFECYCLE_FULFILLED
    assert request["shared_clip_count"] == 2
    assertions.assert_bps(
        request["provisional_share_rate_bps"], 4000, "provisional_share_rate_bps"
    )


def test_compiled_report_diverges_between_its_provisional_and_certified_branches(
    api: ApiClient,
) -> None:
    """One identical set of five solicitations yields 4000 bps and 2500 bps at once.

    PRD: "Then: if the recipient's `notification_mute_enabled` is true, the dispatch is marked `suppressed` true with `suppression_reason` `RESIDENT_MUTED`."
    PRD: "`certified_share_rate_bps` includes only solicitations that both actually reached a resident **and** actually resolved: `status` in `SHARED`, `DECLINED` or `EXPIRED`, **and** `notification_suppressed` false."
    PRD: "It is `provisional_share_rate_bps` while the report's `variant` is `PROVISIONAL` and `certified_share_rate_bps` once the `variant` is `CERTIFIED`; a freshly compiled report is `PROVISIONAL` and publishes the provisional figure."

    Design: Difficulty/dual_variant_calc/share_rate_provisional_vs_certified_diverge_on_suppressed_share
    """
    world = _seed_five_camera_canvass(api, muted_index=2)
    _answer_three_then_sweep(api, world)

    # The muted owner's notification was silenced; the owner still shared.
    sharer = fixtures.read_solicitation(
        api, world["solicitation_for"][world["resident_ids"][0]]["id"]
    )
    muted_sharer = fixtures.read_solicitation(
        api, world["solicitation_for"][world["resident_ids"][1]]["id"]
    )
    assert sharer["status"] == k.SOLICITATION_SHARED
    assert sharer["notification_suppressed"] is False
    assertions.assert_nulls(sharer, "suppression_reason")
    assert muted_sharer["status"] == k.SOLICITATION_SHARED
    assert muted_sharer["notification_suppressed"] is True
    assert muted_sharer["suppression_reason"] == k.SUPPRESSION_RESIDENT_MUTED

    report = _compile_report(api, world)

    assert report["requests_submitted_count"] == 1
    assert report["solicitations_dispatched_count"] == 5
    assert report["suppressed_dispatch_count"] == 1
    assert report["shared_count"] == 2
    assert report["declined_count"] == 1
    assert report["expired_count"] == 2
    assert report["pending_count"] == 0
    assert report["withdrawn_count"] == 0
    assert report["variant"] == k.REPORT_PROVISIONAL

    # Provisional: 2 shared over all 5 solicitations.
    assertions.assert_bps(
        report["provisional_share_rate_bps"], 4000, "provisional_share_rate_bps"
    )
    # Certified: the delivered-and-resolved set is sol1 SHARED, sol3 DECLINED and
    # the two EXPIRED rows, so 1 shared over 4.
    assertions.assert_bps(
        report["certified_share_rate_bps"], 2500, "certified_share_rate_bps"
    )
    assert report["certified_share_rate_bps"] != report["provisional_share_rate_bps"]
    assertions.assert_bps(
        report["published_share_rate_bps"], 4000, "published_share_rate_bps"
    )


def test_certification_repoints_published_at_a_certified_rate_below_the_provisional(
    api: ApiClient,
) -> None:
    """The suppressed share leaves the numerator too, so certifying publishes 2500 bps.

    PRD: "Note carefully that a solicitation in `SHARED` whose notification was suppressed drops out of the **numerator** as well: the certified rate is not merely the provisional rate over a smaller denominator, and it may land on either side of it."
    PRD: "It then sets `variant` to `CERTIFIED`, repoints `published_share_rate_bps` at `certified_share_rate_bps`, records the `certification_note`, stamps `certified_at` from the logical clock and `certified_by_user_id` from the acting caller, and advances the report's `version` by 1."

    Design: Difficulty/dual_variant_calc/share_rate_provisional_vs_certified_diverge_on_suppressed_share
    """
    world = _seed_five_camera_canvass(api, muted_index=2)
    _answer_three_then_sweep(api, world)
    provisional_report = _compile_report(api, world)
    assertions.assert_bps(
        provisional_report["published_share_rate_bps"], 4000, "published_share_rate_bps"
    )

    certified = fixtures.certify_report(api, provisional_report["id"])

    assert certified["variant"] == k.REPORT_CERTIFIED
    assertions.assert_bps(
        certified["certified_share_rate_bps"], 2500, "certified_share_rate_bps"
    )
    # Had only the denominator shrunk, the two shares over four delivered rows
    # would have published 5000 bps; the suppressed share leaves the numerator.
    assert certified["certified_share_rate_bps"] != 5000
    assertions.assert_bps(
        certified["published_share_rate_bps"], 2500, "published_share_rate_bps"
    )
    assert certified["published_share_rate_bps"] == certified["certified_share_rate_bps"]
    # The provisional branch is still on the record beside the certified one.
    assertions.assert_bps(
        certified["provisional_share_rate_bps"], 4000, "provisional_share_rate_bps"
    )
    assert certified["certified_by_user_id"] == PLATFORM_ADMIN_SECOND_ID
    assertions.assert_instant(
        certified["certified_at"], _CLOCK_PAST_DEADLINE, "certified_at"
    )
    assertions.assert_version_advanced(certified, provisional_report["version"])


def _seed_two_retention_variants(api: ApiClient) -> Dict[str, Any]:
    """Two clips off one request, one shared before and one after an escalation.

    Both offer byte-identical footage — the same ``recorded_start_utc`` and the
    same ``duration_seconds`` — from two cameras with the same thirty-day
    on-device retention, at the same logical instant. The only thing that differs
    between them is the parent request's compliance posture: the first is shared
    while the audit is still merely flagged, the second after a separate auditing
    officer has escalated it.
    """
    world = _seed_five_camera_canvass(api, case_number="CASE-9002")
    auditor = fixtures.add_auditor(api, world["agency_id"])
    world["auditor"] = auditor
    r1, r2 = world["resident_ids"][0], world["resident_ids"][1]
    world["clip_a"] = fixtures.share_footage(
        api,
        world["solicitation_for"][r1]["id"],
        r1,
        recorded_start_utc=_RECORDED_START,
        duration_seconds=_DURATION_SECONDS,
    )
    world["escalated"] = fixtures.escalate_audit(
        api,
        world["request_id"],
        auditor["id"],
        audit_note="Radius and device count warrant supervisory hold.",
    )
    world["clip_b"] = fixtures.share_footage(
        api,
        world["solicitation_for"][r2]["id"],
        r2,
        recorded_start_utc=_RECORDED_START,
        duration_seconds=_DURATION_SECONDS,
    )
    return world


def test_case_anchored_clip_takes_the_latest_candidate_where_device_anchored_took_the_earliest(
    api: ApiClient,
) -> None:
    """Identical footage lands on 2026-09-07T01:00:00Z and on 2026-09-29T00:00:00Z.

    PRD: "In every other compliance posture — `JUSTIFICATION_PENDING`, `JUSTIFICATION_LOGGED`, `AUDIT_FLAGGED` or `AUDIT_CLEARED` — the clip is `DEVICE_ANCHORED`: its `retention_expires_at` is the **earliest** of all three candidates, so whichever of the resident's own camera retention, the agency's window and the portal grace period runs out first wins, and the clip's initial `status` is `RETAINED`."
    PRD: "When the owning request's `compliance_state` reads `AUDIT_ESCALATED` at the moment of sharing, the clip is `CASE_ANCHORED`: its `retention_expires_at` is the **later** of the agency candidate and the portal candidate, the device candidate is **ignored entirely**, and the clip's initial `status` is `LEGAL_HOLD`."
    PRD: "`CLEAR` moves the compliance dimension `AUDIT_FLAGGED → AUDIT_CLEARED` and returns the request to ordinary handling; `ESCALATE` moves it `AUDIT_FLAGGED → AUDIT_ESCALATED`."
    PRD: "On identical input data the two variants therefore differ both in `retention_expires_at` and in whether the sweep may act on the clip at all."

    Design: Difficulty/dual_variant_calc/clip_retention_device_anchored_vs_case_anchored_diverge_on_escalation
    """
    world = _seed_two_retention_variants(api)
    clip_a, clip_b = world["clip_a"], world["clip_b"]

    # The two offers are byte-identical, and both requests' expiry — the portal
    # candidate's anchor — is the same 72-hour deadline.
    assertions.assert_instant(clip_a["recorded_start_utc"], _RECORDED_START, "recorded_start_utc")
    assertions.assert_instant(clip_b["recorded_start_utc"], _RECORDED_START, "recorded_start_utc")
    assert clip_a["duration_seconds"] == _DURATION_SECONDS
    assert clip_b["duration_seconds"] == _DURATION_SECONDS
    assertions.assert_instant(clip_a["shared_at"], fixtures.SCENARIO_CLOCK, "shared_at")
    assertions.assert_instant(clip_b["shared_at"], fixtures.SCENARIO_CLOCK, "shared_at")

    # The first share saw a merely flagged audit, so the earliest of the three
    # candidates wins: the device candidate, 30 days after the recorded start.
    assert clip_a["retention_variant"] == k.RETENTION_DEVICE_ANCHORED
    assertions.assert_instant(
        clip_a["retention_expires_at"], _DEVICE_CANDIDATE, "retention_expires_at"
    )
    assert clip_a["status"] == k.CLIP_RETAINED
    assert canonical_instant(clip_a["retention_expires_at"]) != canonical_instant(
        _AGENCY_CANDIDATE
    )
    assert canonical_instant(clip_a["retention_expires_at"]) != canonical_instant(
        _PORTAL_CANDIDATE
    )

    # The escalation flipped the switch for every later share.
    assert world["escalated"]["compliance_state"] == k.COMPLIANCE_AUDIT_ESCALATED

    # The second share reads the same candidate set in the opposite direction and
    # ignores the device candidate outright.
    assert clip_b["retention_variant"] == k.RETENTION_CASE_ANCHORED
    assertions.assert_instant(
        clip_b["retention_expires_at"], _PORTAL_CANDIDATE, "retention_expires_at"
    )
    assert clip_b["status"] == k.CLIP_LEGAL_HOLD
    assert canonical_instant(clip_b["retention_expires_at"]) != canonical_instant(
        _DEVICE_CANDIDATE
    )
    assert canonical_instant(clip_b["retention_expires_at"]) != canonical_instant(
        _AGENCY_CANDIDATE
    )

    assert canonical_instant(clip_a["retention_expires_at"]) != canonical_instant(
        clip_b["retention_expires_at"]
    )
    assertions.assert_nulls(clip_a, "purged_at", "purge_reason")
    assertions.assert_nulls(clip_b, "purged_at", "purge_reason")


def test_sweep_purges_the_device_anchored_clip_and_only_counts_the_case_anchored_one(
    api: ApiClient,
) -> None:
    """One sweep past both expiries destroys one clip and merely counts the other.

    PRD: "It moves every solicitation still in `SOLICITED` whose `respond_deadline_utc` is at or before the clock to `EXPIRED`, processed in ascending `respond_deadline_utc` and then ascending `created_at`, with the counter movements of §3.5."
    PRD: "It moves every clip in `RETAINED` whose `retention_expires_at` is at or before the clock to `PURGED` with `purge_reason` `RETENTION_EXPIRED`, moving the seconds across and leaving the solicitation in `SHARED`."
    PRD: "And it counts every clip in `LEGAL_HOLD` that is past its `retention_expires_at` **without touching it**."
    PRD: "The sweep reports what it did: `run_at_utc` echoing the logical clock instant it ran at, `solicitations_expired_count`, `clips_purged_count`, `clips_held_count` — the legal-hold clips it deliberately skipped — and `requests_auto_closed_count`."

    Design: Difficulty/dual_variant_calc/clip_retention_device_anchored_vs_case_anchored_diverge_on_escalation
    """
    world = _seed_two_retention_variants(api)
    for resident_id in world["resident_ids"][2:]:
        silent = world["solicitation_for"][resident_id]
        assert silent["status"] == k.SOLICITATION_SOLICITED
        assertions.assert_instant(
            silent["respond_deadline_utc"], _RESPOND_DEADLINE, "respond_deadline_utc"
        )

    fixtures.set_clock(api, _CLOCK_PAST_BOTH_EXPIRIES)
    sweep = fixtures.run_sweep(api)

    assertions.assert_instant(sweep["run_at_utc"], _CLOCK_PAST_BOTH_EXPIRIES, "run_at_utc")
    assert sweep["solicitations_expired_count"] == 3
    assert sweep["clips_purged_count"] == 1
    assert sweep["clips_held_count"] == 1
    assert sweep["requests_auto_closed_count"] == 1

    # The device-anchored clip's earliest candidate had already passed.
    purged = fixtures.read_clip(api, world["clip_a"]["id"])
    assert purged["retention_variant"] == k.RETENTION_DEVICE_ANCHORED
    assert purged["status"] == k.CLIP_PURGED
    assert purged["purge_reason"] == k.PURGE_RETENTION_EXPIRED
    assertions.assert_instant(purged["purged_at"], _CLOCK_PAST_BOTH_EXPIRIES, "purged_at")

    # The case-anchored clip is past its own instant too, and is left alone.
    held = fixtures.read_clip(api, world["clip_b"]["id"])
    assert held["retention_variant"] == k.RETENTION_CASE_ANCHORED
    assert held["status"] == k.CLIP_LEGAL_HOLD
    assertions.assert_instant(
        held["retention_expires_at"], _PORTAL_CANDIDATE, "retention_expires_at"
    )
    assertions.assert_nulls(held, "purged_at", "purge_reason")


def test_legal_hold_clip_keeps_its_seconds_retained_while_the_purged_one_moves_them(
    api: ApiClient,
) -> None:
    """After the sweep one owner's seconds have moved to purged and the other's have not.

    PRD: "Purging footage therefore moves seconds from the retained side to the purged side rather than destroying them, and footage awaiting purge still counts as retained exposure."
    PRD: "It moves every clip in `RETAINED` whose `retention_expires_at` is at or before the clock to `PURGED` with `purge_reason` `RETENTION_EXPIRED`, moving the seconds across and leaving the solicitation in `SHARED`."
    PRD: "Evidence under audit escalation is meant to outlive the owner's own camera setting, and a clip under legal hold is never touched by the retention sweep however far past its nominal expiry the clock has travelled; only an explicit release ends the hold."
    PRD: "Finally, every video request whose `pending_count` has reached 0 is auto-resolved out of `SOLICITING` into `FULFILLED` or `EXHAUSTED` under the rule of §3.5, with the agency's `open_request_count` decremented for each."

    Design: Difficulty/dual_variant_calc/clip_retention_device_anchored_vs_case_anchored_diverge_on_escalation
    """
    world = _seed_two_retention_variants(api)
    held_clip_version = world["clip_b"]["version"]
    r1, r2 = world["resident_ids"][0], world["resident_ids"][1]

    fixtures.set_clock(api, _CLOCK_PAST_BOTH_EXPIRIES)
    fixtures.run_sweep(api)

    # The device-anchored owner's exposure has moved across the ledger.
    owner_of_purged = fixtures.read_resident(api, r1)
    assertions.assert_footage_ledger(
        owner_of_purged, lifetime=1800, retained=0, purged=1800
    )

    # The case-anchored owner's clip was never touched, so nothing moved.
    owner_of_held = fixtures.read_resident(api, r2)
    assertions.assert_footage_ledger(owner_of_held, lifetime=1800, retained=1800, purged=0)
    held = fixtures.read_clip(api, world["clip_b"]["id"])
    assert held["status"] == k.CLIP_LEGAL_HOLD
    assertions.assert_version_unchanged(held, held_clip_version)

    # A retention-expiry purge revokes no consent: both answers stand as given.
    for resident_id in (r1, r2):
        answered = fixtures.read_solicitation(
            api, world["solicitation_for"][resident_id]["id"]
        )
        assert answered["status"] == k.SOLICITATION_SHARED

    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_ledger(request, total=5)
    assertions.assert_solicitation_buckets(
        request, pending=0, shared=2, declined=0, expired=3, withdrawn=0
    )
    assert request["lifecycle_state"] == k.LIFECYCLE_FULFILLED
