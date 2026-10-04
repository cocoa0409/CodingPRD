"""Cascading side effects that hop across entities."""
from test_helpers import (
    add_seat_ok, api_client, expire_subscription_by_renewal_failure,
    get_success_data, issue_offer, list_standings, make_learner_headers,
    read_node, scene_league_demotion_mutates_crowned_node, set_clock,
    settle_league, subscribe, validate_error,
)


def _register(display_name):
    return get_success_data(api_client.create_learner(
        {"display_name": display_name, "timezone_id": "Etc/UTC",
         "local_date_offset_days": 0, "program_tier": "FREE"}, None))




def test_league_demotion_adds_a_decay_point_to_every_crowned_node(api):
    """PRD §3.7: "Demotion records `settled_outcome` `DEMOTED`, recomputes the
    learner's `leaf_count`, and — the sting of relegation — adds one decay point to
    every crowned node of that learner sitting in a unit that is `COMPLETED`"

    Design: Difficulty/transitive_cascade/decay_cascade_learner_league_engagement
    """
    scene = scene_league_demotion_mutates_crowned_node()

    updated = read_node(scene["gold_node"]["id"], scene["learner"]["id"])
    assert updated["decay_meter"] == scene["gold_node"]["decay_meter"] + 1, (
        "the crowned node gained exactly one decay point from the demotion sweep, "
        f"got {updated['decay_meter']} from {scene['gold_node']['decay_meter']}"
    )
    assert updated["state"] == "GOLD", (
        f"one decay point does not demote the node, got {updated['state']}"
    )


def test_league_demotion_leaves_a_node_whose_unit_left_completed_alone(api):
    """PRD §3.7: "adds one decay point to every crowned node of that learner sitting
    in a unit that is `COMPLETED`"
    PRD §2.6: "A unit's own progression posture is likewise derived: it advances
    when its children advance and it is pulled backwards when one of its children
    is demoted by decay, so a completed unit can legitimately return to
    in-progress and later complete again."

    Design: Difficulty/transitive_cascade/decay_cascade_learner_league_engagement
    """
    scene = scene_league_demotion_mutates_crowned_node()

    refreshed = read_node(scene["decayed_node"]["id"], scene["learner"]["id"])
    assert refreshed["decay_meter"] == scene["decayed_node"]["decay_meter"], (
        "the unit was pulled back to IN_PROGRESS by the earlier decay, so the "
        "demotion sweep does not touch this node's meter, got "
        f"{refreshed['decay_meter']} from {scene['decayed_node']['decay_meter']}"
    )
    assert refreshed["state"] == "DECAYED", (
        f"the node is untouched by the settlement sweep, got {refreshed['state']}"
    )


def test_league_demotion_settles_the_sole_standing_and_closes_the_league(api, admin_headers):
    """PRD §3.7: "Because the demotion sweep runs last, a standing that satisfies
    both cutoffs settles as `DEMOTED`."
    PRD §3.7: "moves each to `DEMOTED` when its rank is at or above the demotion
    cutoff, and lands the league in `CLOSED`"

    Design: Difficulty/transitive_cascade/decay_cascade_learner_league_engagement
    """
    scene = scene_league_demotion_mutates_crowned_node()

    assert scene["standing"]["settled_outcome"] == "DEMOTED", (
        "with one member the demotion cutoff resolves to rank 1, so the sole "
        f"standing settles as DEMOTED, got {scene['standing']['settled_outcome']}"
    )
    league = get_success_data(api_client.get_league(
        scene["league"]["id"], scene["headers"]
    ))
    assert league["status"] == "CLOSED"
    assert league["member_count"] == 1, (
        f"a DEMOTED standing still counts as a member, got {league['member_count']}"
    )
    # PRD §2.10 / §3.7: a settlement sweep aimed at a league that is no longer
    # ACTIVE at the week close is refused with ERR_LEAGUE_NOT_SETTLING, so the
    # CLOSED round is left exactly as the first settlement left it.
    set_clock("2026-09-29T00:00:00Z")
    validate_error(
        api_client.update_league(scene["league"]["id"], {"action": "SETTLE"},
                                 admin_headers),
        "ERR_LEAGUE_NOT_SETTLING",
    )
    landed = list_standings(scene["learner"]["id"], scene["league"]["id"])[0]
    assert landed["rank"] == 1


def test_subscription_expiry_moves_an_active_seat_to_removed(api):
    """PRD §3.5: "Grace is finite: once the clock has passed `current_period_end`
    by `GRACE_DAYS`, the renewal sweep moves the record `IN_GRACE → EXPIRED`."
    PRD §3.5: "every `ACTIVE` seat under it is moved to `REMOVED`"

    Design: Difficulty/transitive_cascade/subscription_lapse_cascade_seat_heart_cadence
    """
    owner = _register("Ada")
    member = _register("Bea")
    subscription = subscribe(owner["id"], "PLUS_FAMILY", seats_total=4,
                             auto_renew=True)
    add_seat_ok(subscription["id"], owner["id"], member["id"],
                subscription["version"])

    final = expire_subscription_by_renewal_failure(subscription["id"], owner["id"])

    assert final["status"] == "EXPIRED", (
        "an auto-renewing subscription past its grace window is expired, got "
        f"{final['status']}"
    )
    assert final["limits_removed"] is False

    seats = get_success_data(api_client.list_subscription_memberships(
        subscription["id"], make_learner_headers(owner["id"])
    ))
    assert seats and all(seat["status"] == "REMOVED" for seat in seats), (
        f"every ACTIVE seat is moved to REMOVED, got {seats}"
    )


def test_subscription_expiry_sweeps_the_learners_issued_offers(api):
    """PRD §3.5: "every engagement offer belonging to a learner under that
    subscription that is still `ISSUED` is moved to `EXPIRED`"
    PRD §3.5: "`limits_removed` becomes false"

    Design: Difficulty/transitive_cascade/subscription_lapse_cascade_seat_heart_cadence
    """
    owner = _register("Ada")
    subscription = subscribe(owner["id"], "PLUS_FAMILY", seats_total=4,
                             auto_renew=True)
    offer = issue_offer(owner["id"], "STREAK_7")

    final = expire_subscription_by_renewal_failure(subscription["id"], owner["id"])

    assert final["status"] == "EXPIRED"
    assert final["limits_removed"] is False
    offers = get_success_data(api_client.list_engagement_offers(
        make_learner_headers(owner["id"]), {"learner_id": owner["id"]}
    ))
    target = [o for o in offers if o["id"] == offer["id"]][0]
    assert target["status"] == "EXPIRED", (
        "an offer belonging to a learner under the expired subscription leaves "
        f"the ISSUED posture for the terminal one, got {target['status']}"
    )