"""Derived values whose formulae compose several independent terms.

Three of the portal's numbers are not single lookups but compositions, and each
composition can be got wrong in a way a single-term reading would never reveal:

  * a canvass area's ``effective_min_devices``, which sums an agency base with a
    radius step and a capped window step and only then applies a global floor;
  * a community post's ``discrimination_score``, whose four weighted terms are
    each rounded before their sum is rounded again;
  * a dispatch batch's fatigue arithmetic, whose tier is read once at batch
    start rather than re-derived after every delivery.

Every scenario pins the logical clock first, so every stamped instant and every
daily counter in the file is measured against a known "now".
"""

from decimal import Decimal
from typing import Any, Dict, List

from test_helpers import ApiClient, assertions, constants as k, fixtures


# ═══ effective_min_devices: base + radius step + capped window step ════════

def test_lock_freezes_effective_min_devices_at_the_agency_base_with_neither_bump(
    api: ApiClient, clock: str
) -> None:
    """A 500 m disc over a six-hour window engages no bump, so the base stands.

    PRD: "The base is the owning agency's own `min_device_threshold`."
    PRD: "A six-hour window therefore contributes nothing, while a thirty-hour window contributes 2."
    PRD: "Locking writes `locked_at` from the logical clock, moves the area `DRAFT → LOCKED`, and advances `version` by 1."

    Design: Difficulty/combinatorial_formula/effective_min_devices_nested_bumps_cap_and_global_floor
    """
    world = fixtures.seed_agency_with_officer(
        api,
        name="Alpha County Sheriff",
        jurisdiction_code="AL-001",
        min_device_threshold=3,
        badge_number="A-100",
        full_name="Officer Alpha",
    )
    drafted = fixtures.create_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=0,
        center_y_m=0,
        radius_m=500,
        window_start_utc=fixtures.FOOTAGE_WINDOW_START,
        window_end_utc=fixtures.FOOTAGE_WINDOW_END,
        area_label="P no bumps",
    )
    assert drafted["status"] == k.AREA_STATUS_DRAFT
    assert drafted["effective_min_devices"] is None

    locked = fixtures.lock_area(api, drafted["id"], world["officer_id"])

    # base 3, radius bump 0 (500 m or less), window bump 0 (six hours), floor 3.
    assert locked["effective_min_devices"] == 3
    assert locked["eligible_device_count"] == 0
    assertions.assert_instant(locked["locked_at"], clock, "locked_at")
    assertions.assert_version_advanced(locked, drafted["version"])

    stored = fixtures.read_area(api, drafted["id"])
    assertions.assert_subset(
        stored,
        {
            "status": k.AREA_STATUS_LOCKED,
            "effective_min_devices": 3,
            "eligible_device_count": 0,
            "derived_request_count": 0,
            "radius_m": 500,
            "invalidated_reason": None,
            "version": 2,
        },
    )
    assertions.assert_instant(stored["locked_at"], clock, "locked_at")


def test_lock_adds_the_radius_and_window_bumps_independently_to_the_agency_base(
    api: ApiClient, clock: str
) -> None:
    """One agency, two discs: neither step engaged reads 3, both engaged reads 7.

    PRD: "To that is added a radius bump, a step function over the disc: a `radius_m` of 500 metres or less adds nothing, a `radius_m` above 500 metres and up to and including 1000 metres adds 2, and a `radius_m` above 1000 metres adds 5."
    PRD: "To that is added a window bump: take the elapsed time between `window_start_utc` and `window_end_utc`, round it **up** to a whole number of hours, divide that by 12, round the quotient **up** to a whole number, subtract 1, and take the smaller of the result and 3."
    PRD: "A six-hour window therefore contributes nothing, while a thirty-hour window contributes 2."

    Design: Difficulty/combinatorial_formula/effective_min_devices_nested_bumps_cap_and_global_floor
    """
    world = fixtures.seed_agency_with_officer(
        api,
        name="Alpha County Sheriff",
        jurisdiction_code="AL-001",
        min_device_threshold=3,
        badge_number="A-100",
        full_name="Officer Alpha",
    )

    plain = fixtures.seed_locked_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=0,
        center_y_m=0,
        radius_m=500,
        window_start_utc=fixtures.FOOTAGE_WINDOW_START,
        window_end_utc=fixtures.FOOTAGE_WINDOW_END,
        area_label="P no bumps",
    )
    # Far enough away that the repeat-canvass proximity disc is not engaged.
    bumped = fixtures.seed_locked_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=5000,
        center_y_m=5000,
        radius_m=600,
        window_start_utc="2026-08-08T00:00:00Z",
        window_end_utc="2026-08-09T06:00:00Z",
        area_label="Q both bumps",
    )

    # Same base of 3 either side: 3 + 0 + 0 against 3 + 2 (600 m) + 2 (30 h).
    assert plain["effective_min_devices"] == 3
    assert bumped["effective_min_devices"] == 7

    stored_plain = fixtures.read_area(api, plain["id"])
    stored_bumped = fixtures.read_area(api, bumped["id"])
    assertions.assert_subset(
        stored_plain,
        {
            "status": k.AREA_STATUS_LOCKED,
            "effective_min_devices": 3,
            "radius_m": 500,
            "eligible_device_count": 0,
            "invalidated_reason": None,
            "version": 2,
        },
    )
    assertions.assert_subset(
        stored_bumped,
        {
            "status": k.AREA_STATUS_LOCKED,
            "effective_min_devices": 7,
            "radius_m": 600,
            "eligible_device_count": 0,
            "invalidated_reason": None,
            "version": 2,
        },
    )
    assertions.assert_instant(stored_bumped["locked_at"], clock, "locked_at")


def test_window_bump_saturates_at_its_cap_while_the_radius_bump_is_maximal(
    api: ApiClient, clock: str
) -> None:
    """A 1200 m disc over a 168-hour window reads 11, not the uncapped 21.

    PRD: "To that is added a window bump: take the elapsed time between `window_start_utc` and `window_end_utc`, round it **up** to a whole number of hours, divide that by 12, round the quotient **up** to a whole number, subtract 1, and take the smaller of the result and 3."
    PRD: "To that is added a radius bump, a step function over the disc: a `radius_m` of 500 metres or less adds nothing, a `radius_m` above 500 metres and up to and including 1000 metres adds 2, and a `radius_m` above 1000 metres adds 5."

    Design: Difficulty/combinatorial_formula/effective_min_devices_nested_bumps_cap_and_global_floor
    """
    world = fixtures.seed_agency_with_officer(
        api,
        name="Alpha County Sheriff",
        jurisdiction_code="AL-001",
        min_device_threshold=3,
        badge_number="A-100",
        full_name="Officer Alpha",
    )
    drafted = fixtures.create_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=9000,
        center_y_m=9000,
        radius_m=1200,
        window_start_utc="2026-08-04T00:00:00Z",
        window_end_utc="2026-08-11T00:00:00Z",
        area_label="R capped window bump",
    )

    locked = fixtures.lock_area(api, drafted["id"], world["officer_id"])

    # 3 + 5 (above 1000 m) + min(3, ceil(168/12) - 1 = 13) = 11.
    assert locked["effective_min_devices"] == 11
    assert locked["eligible_device_count"] == 0

    stored = fixtures.read_area(api, drafted["id"])
    assertions.assert_subset(
        stored,
        {
            "status": k.AREA_STATUS_LOCKED,
            "effective_min_devices": 11,
            "radius_m": 1200,
            "eligible_device_count": 0,
            "derived_request_count": 0,
            "invalidated_reason": None,
            "version": 2,
        },
    )
    assertions.assert_instant(stored["locked_at"], clock, "locked_at")


def test_global_floor_lifts_a_sub_floor_agency_base_to_the_portal_minimum(
    api: ApiClient, clock: str
) -> None:
    """An agency base of 1 with no bump still locks at the floor of 3.

    PRD: "Finally, and only after the three terms have been summed, the larger of that sum and the global floor of 3 is taken."
    PRD: "The floor applies to the sum, never to the individual terms — flooring each term separately would produce a different answer."

    Design: Difficulty/combinatorial_formula/effective_min_devices_nested_bumps_cap_and_global_floor
    """
    alpha = fixtures.seed_agency_with_officer(
        api,
        name="Alpha County Sheriff",
        jurisdiction_code="AL-001",
        min_device_threshold=3,
        badge_number="A-100",
        full_name="Officer Alpha",
    )
    beta = fixtures.seed_agency_with_officer(
        api,
        name="Beta Township Police",
        jurisdiction_code="BE-001",
        min_device_threshold=1,
        badge_number="B-100",
        full_name="Officer Beta",
    )
    assert alpha["agency"]["min_device_threshold"] == 3
    assert beta["agency"]["min_device_threshold"] == 1

    at_base = fixtures.seed_locked_area(
        api,
        alpha["agency_id"],
        alpha["officer_id"],
        center_x_m=0,
        center_y_m=0,
        radius_m=500,
        window_start_utc=fixtures.FOOTAGE_WINDOW_START,
        window_end_utc=fixtures.FOOTAGE_WINDOW_END,
        area_label="P no bumps",
    )
    # A different agency, so no repeat-canvass rule reaches across from ALPHA.
    below_floor = fixtures.seed_locked_area(
        api,
        beta["agency_id"],
        beta["officer_id"],
        center_x_m=0,
        center_y_m=0,
        radius_m=500,
        window_start_utc=fixtures.FOOTAGE_WINDOW_START,
        window_end_utc=fixtures.FOOTAGE_WINDOW_END,
        area_label="S floor bites",
    )

    # A summed 1 is lifted to the floor, landing on the same 3 as a base of 3.
    assert at_base["effective_min_devices"] == 3
    assert below_floor["effective_min_devices"] == 3

    stored = fixtures.read_area(api, below_floor["id"])
    assertions.assert_subset(
        stored,
        {
            "status": k.AREA_STATUS_LOCKED,
            "effective_min_devices": 3,
            "radius_m": 500,
            "eligible_device_count": 0,
            "derived_request_count": 0,
            "invalidated_reason": None,
            "version": 2,
        },
    )
    assertions.assert_instant(stored["locked_at"], clock, "locked_at")


# ═══ discrimination_score: four weighted terms, rounded twice ══════════════

def _lone_author(api: ApiClient) -> Dict[str, Any]:
    """One resident who hears about nothing, so no fan-out perturbs a score."""
    return fixtures.register_resident(
        api,
        display_name="RA",
        email="ra@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )


def test_discrimination_score_rounds_each_weighted_term_before_summing_them(
    api: ApiClient, clock: str
) -> None:
    """Three profiling and three tone signals score 0.61, not the round-once 0.60.

    PRD: "Only then are the four rounded terms added together, and the sum is rounded to two decimals again."
    PRD: "Adding the raw products and rounding once at the end is a different calculation and gives a different answer for some inputs: with a `location_profiling_count` of 3 and a `hostile_tone_count` of 3, per-term rounding turns 0.345 into 0.35 and 0.255 into 0.26 for a total of 0.61, while rounding only the raw sum gives 0.60."
    PRD: "It is created in `FLAGGED` with `auto_flag_reason` set to `DISCRIMINATION_SCORE`, it alerts nobody, and its three alert counters stay at 0."

    Design: Difficulty/combinatorial_formula/discrimination_score_per_term_rounding_beats_sum_rounding
    """
    author = _lone_author(api)

    post = fixtures.create_post(
        api,
        author["id"],
        body="Post one: profiling and tone signals.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
        location_profiling_count=3,
        hostile_tone_count=3,
    )

    # 0.115 * 3 -> 0.35 and 0.085 * 3 -> 0.26, summing to 0.61.
    assertions.assert_score(post["discrimination_score"], "0.61")
    assert assertions.assert_two_dp(post["discrimination_score"]) != Decimal("0.60")
    assertions.assert_subset(
        post,
        {
            "author_resident_id": author["id"],
            "state": k.POST_FLAGGED,
            "auto_flag_reason": k.AUTO_FLAG_DISCRIMINATION_SCORE,
            "protected_class_term_count": 0,
            "unverified_assertion_count": 0,
            "location_profiling_count": 3,
            "hostile_tone_count": 3,
            "alert_candidate_count": 0,
            "alert_fanout_count": 0,
            "alert_suppressed_count": 0,
            "flag_count": 0,
            "revision_count": 0,
        },
    )
    assertions.assert_created_equals_updated(post)

    stored = fixtures.read_post(api, post["id"])
    assertions.assert_score(stored["discrimination_score"], "0.61")
    assertions.assert_subset(
        stored,
        {
            "state": k.POST_FLAGGED,
            "auto_flag_reason": k.AUTO_FLAG_DISCRIMINATION_SCORE,
            "version": 1,
        },
    )


def test_one_signal_in_three_classes_scores_by_term_not_by_the_raw_sum(
    api: ApiClient, clock: str
) -> None:
    """One of each of three signals scores 0.55, where rounding once gives 0.54.

    PRD: "Only then are the four rounded terms added together, and the sum is rounded to two decimals again."
    PRD: "The operands must be exact decimals, not binary floats, for the same reason set out in §2.7 — in IEEE-754, 0.115 multiplied by 3 is 0.34499999999999997, which rounds down to 0.34 and produces the wrong score."

    Design: Difficulty/combinatorial_formula/discrimination_score_per_term_rounding_beats_sum_rounding
    """
    author = _lone_author(api)

    post = fixtures.create_post(
        api,
        author["id"],
        body="Post four: one signal in three different classes.",
        category=k.CATEGORY_GENERAL,
        post_x_m=0,
        post_y_m=0,
        protected_class_term_count=1,
        location_profiling_count=1,
        hostile_tone_count=1,
    )

    # 0.34 + (0.115 -> 0.12) + (0.085 -> 0.09) = 0.55; the raw sum is 0.54.
    assertions.assert_score(post["discrimination_score"], "0.55")
    assert assertions.assert_two_dp(post["discrimination_score"]) != Decimal("0.54")
    assertions.assert_subset(
        post,
        {
            "state": k.POST_FLAGGED,
            "auto_flag_reason": k.AUTO_FLAG_DISCRIMINATION_SCORE,
            "protected_class_term_count": 1,
            "unverified_assertion_count": 0,
            "location_profiling_count": 1,
            "hostile_tone_count": 1,
            "alert_candidate_count": 0,
            "alert_fanout_count": 0,
            "alert_suppressed_count": 0,
        },
    )

    stored = fixtures.read_post(api, post["id"])
    assertions.assert_score(stored["discrimination_score"], "0.55")
    assert stored["state"] == k.POST_FLAGGED


def test_a_score_below_the_threshold_publishes_with_no_auto_flag_reason(
    api: ApiClient, clock: str
) -> None:
    """Four profiling signals score 0.46 and publish, as does a post with none.

    PRD: "A score below 0.49 means the post is created in `PUBLISHED` with a null `auto_flag_reason` and the alert fan-out runs immediately."
    PRD: "An empty candidate pool is entirely legal, never an error: all three counters read 0, no dispatches are created, and the post is still returned with HTTP 201."

    Design: Difficulty/combinatorial_formula/discrimination_score_per_term_rounding_beats_sum_rounding
    """
    author = _lone_author(api)

    profiling_only = fixtures.create_post(
        api,
        author["id"],
        body="Post two: profiling only.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
        location_profiling_count=4,
    )
    unsignalled = fixtures.create_post(
        api,
        author["id"],
        body="Post five: no signals at all.",
        category=k.CATEGORY_LOST_PET,
        post_x_m=0,
        post_y_m=0,
    )

    # 0.115 * 4 = 0.46 exactly, one term short of the 0.49 flag threshold.
    assertions.assert_score(profiling_only["discrimination_score"], "0.46")
    assertions.assert_subset(
        profiling_only,
        {
            "state": k.POST_PUBLISHED,
            "auto_flag_reason": None,
            "location_profiling_count": 4,
            "hostile_tone_count": 0,
            "alert_candidate_count": 0,
            "alert_fanout_count": 0,
            "alert_suppressed_count": 0,
        },
    )

    assertions.assert_score(unsignalled["discrimination_score"], "0.00")
    assertions.assert_subset(
        unsignalled,
        {
            "state": k.POST_PUBLISHED,
            "auto_flag_reason": None,
            "protected_class_term_count": 0,
            "unverified_assertion_count": 0,
            "location_profiling_count": 0,
            "hostile_tone_count": 0,
            "alert_candidate_count": 0,
            "alert_fanout_count": 0,
            "alert_suppressed_count": 0,
        },
    )

    stored = fixtures.read_post(api, profiling_only["id"])
    assertions.assert_score(stored["discrimination_score"], "0.46")
    assertions.assert_subset(
        stored, {"state": k.POST_PUBLISHED, "auto_flag_reason": None, "version": 1}
    )


def test_a_score_landing_exactly_on_the_flag_threshold_is_flagged(
    api: ApiClient, clock: str
) -> None:
    """Two profiling and three tone signals land on 0.49 and are flagged.

    PRD: "A `discrimination_score` of 0.49 or higher — the comparison is inclusive — means the post never reaches the feed."
    PRD: "Only then are the four rounded terms added together, and the sum is rounded to two decimals again."

    Design: Difficulty/combinatorial_formula/discrimination_score_per_term_rounding_beats_sum_rounding
    """
    author = _lone_author(api)

    post = fixtures.create_post(
        api,
        author["id"],
        body="Post three: sits exactly on the flag threshold.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
        location_profiling_count=2,
        hostile_tone_count=3,
    )

    # (0.115 * 2 -> 0.23) + (0.085 * 3 -> 0.26) = 0.49, inclusive of the threshold.
    assertions.assert_score(post["discrimination_score"], "0.49")
    assertions.assert_subset(
        post,
        {
            "state": k.POST_FLAGGED,
            "auto_flag_reason": k.AUTO_FLAG_DISCRIMINATION_SCORE,
            "location_profiling_count": 2,
            "hostile_tone_count": 3,
            "alert_candidate_count": 0,
            "alert_fanout_count": 0,
            "alert_suppressed_count": 0,
        },
    )

    stored = fixtures.read_post(api, post["id"])
    assertions.assert_score(stored["discrimination_score"], "0.49")
    assertions.assert_subset(
        stored,
        {
            "state": k.POST_FLAGGED,
            "auto_flag_reason": k.AUTO_FLAG_DISCRIMINATION_SCORE,
            "version": 1,
        },
    )


# ═══ Fatigue arithmetic: the tier is read once, at batch start ═════════════

def _consent_dispatches(api: ApiClient, resident_id: str) -> List[Dict[str, Any]]:
    """The consent-solicitation dispatches aimed at one resident, in batch order."""
    return fixtures.list_dispatches(api, resident_id, kind=k.DISPATCH_KIND_CONSENT)


def _seed_primed_household_and_request(api: ApiClient) -> Dict[str, Any]:
    """One five-camera household already carrying four delivered alerts today.

    The household's owner has a daily budget of 8 and sits inside the alert
    radius of four earlier posts by a distant neighbour, so the counter reads 4
    before the canvass batch starts. The canvass itself is drawn, locked and
    justified over those five cameras but is deliberately left unsubmitted.
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    target = fixtures.register_resident(
        api,
        display_name="RT",
        email="rt@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=800,
        notification_budget_per_day=8,
    )
    world["devices"] = [
        fixtures.register_device(
            api,
            target["id"],
            label=f"RT D{index}",
            grid_x_m=0,
            grid_y_m=10 * index,
            retention_window_days=30,
        )
        for index in range(1, 6)
    ]
    poster = fixtures.register_resident(
        api,
        display_name="RP",
        email="rp@example.test",
        home_x_m=9000,
        home_y_m=9000,
        alert_radius_m=0,
        notification_budget_per_day=8,
    )
    for ordinal in ("one", "two", "three", "four"):
        fixtures.create_post(
            api,
            poster["id"],
            body=f"Fan-out primer post {ordinal}.",
            category=k.CATEGORY_GENERAL,
            post_x_m=0,
            post_y_m=50,
        )
    world.update(
        fixtures.seed_justified_request(
            api, world["agency_id"], world["officer_id"], case_number="CASE-9003"
        )
    )
    world["target"] = target
    world["target_id"] = target["id"]
    world["poster_id"] = poster["id"]
    return world


def test_submit_batch_spends_the_allowance_read_at_batch_start_and_suppresses_the_rest(
    api: ApiClient, clock: str
) -> None:
    """A snapshot of 4 against a budget of 8 delivers four of five and suppresses one.

    PRD: "For each recipient in a batch, let the snapshot be that recipient's `notifications_sent_today` at batch start and let the budget be their `notification_budget_per_day`."
    PRD: "The batch allowance is then the effective budget minus the snapshot, again clamped at a floor of zero."
    PRD: "Otherwise, if the count already delivered in this batch has reached the batch allowance, the dispatch is marked `suppressed` true with `suppression_reason` `FATIGUE_BUDGET_EXHAUSTED`."
    PRD: "When a dispatch is suppressed, the solicitation it belongs to has `notification_suppressed` set to true and `suppression_reason` set to the matching cause — either `FATIGUE_BUDGET_EXHAUSTED` or `RESIDENT_MUTED`."

    Design: Difficulty/combinatorial_formula/fatigue_tier_snapshot_read_once_not_retiered_mid_batch
    """
    world = _seed_primed_household_and_request(api)
    assertions.assert_subset(
        world["area"], {"eligible_device_count": 5, "effective_min_devices": 3}
    )
    before = fixtures.read_resident(api, world["target_id"])
    assertions.assert_subset(
        before, {"notifications_sent_today": 4, "fatigue_state": k.FATIGUE_NORMAL}
    )

    submitted = fixtures.submit_request(api, world["request_id"], world["officer_id"])

    # Allowance = effective budget 8 - snapshot 4 = 4, so rank 5 goes unheard.
    assert submitted["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assertions.assert_solicitation_buckets(submitted, 5, 0, 0, 0, 0)
    assertions.assert_solicitation_ledger(submitted, 5)
    assertions.assert_bps(submitted["provisional_share_rate_bps"], 0)

    dispatches = _consent_dispatches(api, world["target_id"])
    assert len(dispatches) == 5
    assertions.assert_field_sequence(dispatches, "batch_sequence_no", [1, 2, 3, 4, 5])
    assertions.assert_field_sequence(
        dispatches, "suppressed", [False, False, False, False, True]
    )
    assertions.assert_field_sequence(
        dispatches,
        "suppression_reason",
        [None, None, None, None, k.SUPPRESSION_BUDGET_EXHAUSTED],
    )

    solicitations = fixtures.list_solicitations(
        api, video_request_id=world["request_id"]
    )
    assert len(solicitations) == 5
    assertions.assert_field_sequence(solicitations, "dispatch_rank", [1, 2, 3, 4, 5])
    assertions.assert_field_sequence(
        solicitations,
        "notification_suppressed",
        [False, False, False, False, True],
    )
    assertions.assert_subset(
        solicitations[3],
        {
            "dispatch_rank": 4,
            "status": k.SOLICITATION_SOLICITED,
            "notification_suppressed": False,
            "suppression_reason": None,
        },
    )
    assertions.assert_subset(
        solicitations[4],
        {
            "dispatch_rank": 5,
            "status": k.SOLICITATION_SOLICITED,
            "notification_suppressed": True,
            "suppression_reason": k.SUPPRESSION_BUDGET_EXHAUSTED,
        },
    )

    after = fixtures.read_resident(api, world["target_id"])
    assertions.assert_subset(
        after,
        {"notifications_sent_today": 8, "fatigue_state": k.FATIGUE_THROTTLED},
    )

    stored = fixtures.read_request(api, world["request_id"])
    assertions.assert_subset(
        stored,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "solicitation_count": 5,
            "pending_count": 5,
        },
    )
    assertions.assert_solicitation_ledger(stored, 5)


def test_every_dispatch_in_one_batch_carries_the_same_frozen_snapshot_and_budget(
    api: ApiClient, clock: str
) -> None:
    """The tier is read once: all five rows quote snapshot 4 and budget 8.

    PRD: "Dispatches emitted inside the batch draw down the remaining allowance but they do not re-tier the recipient part-way through."
    PRD: "Re-deriving the tier per dispatch would yield a strictly smaller allowance and is wrong."
    PRD: "A tier penalty is chosen from the snapshot in four bands: a snapshot below 5 incurs no penalty; a snapshot of 5 or more but below 10 incurs a penalty of 1; a snapshot of 10 or more but below 20 incurs a penalty of 3; and a snapshot of 20 or more incurs a penalty equal to the recipient's entire budget."
    PRD: "Both are identical across every dispatch of one batch aimed at the same recipient, which is the whole point."

    Design: Difficulty/combinatorial_formula/fatigue_tier_snapshot_read_once_not_retiered_mid_batch
    """
    world = _seed_primed_household_and_request(api)
    before = fixtures.read_resident(api, world["target_id"])
    assert before["notifications_sent_today"] == 4
    assert before["fatigue_state"] == k.FATIGUE_NORMAL
    assert before["notification_budget_per_day"] == 8

    fixtures.submit_request(api, world["request_id"], world["officer_id"])

    dispatches = _consent_dispatches(api, world["target_id"])
    assert len(dispatches) == 5
    # A snapshot of 4 sits in the no-penalty band, so the effective budget is the
    # whole 8 on every row — including the row the same batch went on to suppress.
    assertions.assert_field_sequence(
        dispatches, "recipient_budget_snapshot", [4, 4, 4, 4, 4]
    )
    assertions.assert_field_sequence(
        dispatches, "recipient_effective_budget", [8, 8, 8, 8, 8]
    )
    assertions.assert_field_sequence(
        dispatches, "kind", [k.DISPATCH_KIND_CONSENT] * 5
    )

    # Four delivered, not the three a mid-batch re-tiering would have allowed.
    delivered = [row for row in dispatches if row["suppressed"] is False]
    suppressed = [row for row in dispatches if row["suppressed"] is True]
    assert len(delivered) == 4
    assert len(suppressed) == 1
    assertions.assert_subset(
        suppressed[0],
        {
            "batch_sequence_no": 5,
            "recipient_budget_snapshot": 4,
            "recipient_effective_budget": 8,
            "suppression_reason": k.SUPPRESSION_BUDGET_EXHAUSTED,
        },
    )

    after = fixtures.read_resident(api, world["target_id"])
    assert after["notifications_sent_today"] == 8
    assert after["fatigue_state"] == k.FATIGUE_THROTTLED
