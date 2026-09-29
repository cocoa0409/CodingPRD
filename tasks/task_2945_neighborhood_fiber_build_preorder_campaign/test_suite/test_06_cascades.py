"""The four-hop qualification failure cascade and the four-hop pole-denial cascade."""

from test_helpers import (
    PM,
    UTILITY,
    api_client,
    assert_cents,
    assert_crew_load,
    assert_deposit_stream_balances,
    CLOCK_AFTER_DEADLINE,
    list_ledger_for_account,
    list_ledger_for_preorder,
    make_pole_request,
    pole_decision_payload,
    read_account,
    read_appointment,
    read_crew,
    read_preorder,
    read_zone,
    set_clock,
    setup_scheduled_bury_appointment,
    setup_zone_with_preorders,
    validate_success,
)

ACCEPTED_MAKE_READY_CENTS = 12000
DENIED_QUOTE_CENTS = 90000


def _zone_that_misses_its_bar():
    """A 20-household zone holding a single preorder, so its final rate is only 5.00."""
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=20, threshold_pct=10.0
    )
    set_clock(CLOCK_AFTER_DEADLINE)
    validate_success(api_client.qualification_run(base["campaign"]["id"], PM))
    return base


def test_failed_zone_appends_exactly_one_refund_entry_for_the_single_preorder():
    """The preorder's stream holds one hold and one refund, and nothing else.

    PRD 3.4: "The third hop is caused by the second: each of those preorders moves
    `deposit_status` `HELD → REFUNDED`, and each such move appends exactly one ledger entry
    of `entry_type` `DEPOSIT_REFUNDED` whose `amount_cents` is the negative of that
    preorder's `deposit_amount_cents` - one entry per preorder, never one aggregate entry per
    account."

    Design: Difficulty/transitive_cascade/not_qualified_run_cascades_zone_preorder_deposit_ledger_account
    """
    base = _zone_that_misses_its_bar()
    preorder = base["preorders"][0]

    entries, _ = list_ledger_for_preorder(preorder["id"])

    assert len(entries) == 2, entries
    kinds = sorted(entry["entry_type"] for entry in entries)
    assert kinds == ["DEPOSIT_HELD", "DEPOSIT_REFUNDED"], kinds
    by_kind = {entry["entry_type"]: entry for entry in entries}
    assert_cents(by_kind["DEPOSIT_HELD"]["amount_cents"], 1000, "DEPOSIT_HELD amount_cents")
    assert_cents(
        by_kind["DEPOSIT_REFUNDED"]["amount_cents"], -1000, "DEPOSIT_REFUNDED amount_cents"
    )


def test_the_fourth_hop_returns_the_account_balance_to_its_pre_preorder_value():
    """Replaying the whole stream leaves deposit_held_cents back at zero.

    PRD 3.4: "The fourth hop is caused by the third: every account touched by those refunds
    has its `deposit_held_cents` recomputed from its ledger stream, which returns it to the
    value it held before these preorders existed."

    Design: Difficulty/transitive_cascade/not_qualified_run_cascades_zone_preorder_deposit_ledger_account
    """
    base = _zone_that_misses_its_bar()
    account = base["accounts"][0]

    entries, _ = list_ledger_for_account(account["id"])

    assert_deposit_stream_balances(entries, 0)
    assert_cents(read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents")


def test_the_verdict_and_the_lapse_hops_run_before_the_money_hops():
    """The zone records the failed verdict and the preorder lapses with the zone's reason.

    PRD 3.4: "The first hop is the zone's own verdict, with `final_qualifying_count`,
    `final_rate_pct` and `campaign_status` written. The second hop lapses every preorder of
    the zone whose `preorder_status` is `PENDING`, each with `lapse_reason`
    `ZONE_NOT_QUALIFIED`."

    Design: Difficulty/transitive_cascade/not_qualified_run_cascades_zone_preorder_deposit_ledger_account
    """
    base = _zone_that_misses_its_bar()

    zone = read_zone(base["zone"]["id"])
    assert zone["campaign_status"] == "NOT_QUALIFIED", zone["campaign_status"]
    assert zone["final_qualifying_count"] == 1, zone["final_qualifying_count"]

    preorder = read_preorder(base["preorders"][0]["id"])
    assert preorder["preorder_status"] == "LAPSED", preorder["preorder_status"]
    assert preorder["lapse_reason"] == "ZONE_NOT_QUALIFIED", preorder["lapse_reason"]
    assert preorder["deposit_status"] == "REFUNDED", preorder["deposit_status"]


def _denied_pole_on_a_zone_mid_build():
    """A zone mid-build with one scheduled bury visit, then a second pole request denied."""
    base = setup_scheduled_bury_appointment(
        pole_quote_cents=ACCEPTED_MAKE_READY_CENTS,
        household_count=10,
        preorder_count=1,
    )
    second = make_pole_request(
        base["zone"]["id"],
        target_status="SURVEYED",
        make_ready_cost_cents=DENIED_QUOTE_CENTS,
        utility_owner="Aurora Power North",
    )
    base["crew_version_before"] = read_crew(base["crew"]["id"])["version"]
    base["denied_request"] = validate_success(
        api_client.decide_pole_attachment_request(
            second["id"],
            pole_decision_payload("DENY", denial_reason="CAPACITY_FULL"),
            UTILITY,
        )
    )
    return base


def test_pole_denial_suspends_the_zone_that_was_already_in_construction():
    """The denial's second hop drives IN_CONSTRUCTION to SUSPENDED with reason POLE_DENIED.

    PRD 3.5: "Where the zone's `construction_status` is `IN_CONSTRUCTION`, the second hop
    suspends it with `suspension_reason` `POLE_DENIED`"

    Design: Difficulty/transitive_cascade/pole_denial_cascades_zone_suspend_appointment_cancel_crew_release
    """
    base = _denied_pole_on_a_zone_mid_build()

    assert base["denied_request"]["status"] == "DENIED", base["denied_request"]["status"]
    zone = read_zone(base["zone"]["id"])
    assert zone["construction_status"] == "SUSPENDED", zone["construction_status"]
    assert zone["suspension_reason"] == "POLE_DENIED", zone["suspension_reason"]
    assert zone["readiness_posture"] == "SUSPENDED", zone["readiness_posture"]


def test_the_suspension_hop_cancels_the_scheduled_visit_with_zone_suspended():
    """The third hop cancels the booked appointment and names the suspension as the cause.

    PRD 3.5: "the third hop, caused by that suspension, cancels every appointment whose
    preorder belongs to that zone and whose status is `SCHEDULED`, each with
    `cancellation_reason` `ZONE_SUSPENDED`"

    Design: Difficulty/transitive_cascade/pole_denial_cascades_zone_suspend_appointment_cancel_crew_release
    """
    base = _denied_pole_on_a_zone_mid_build()

    appointment = read_appointment(base["appointment"]["id"])
    assert appointment["status"] == "CANCELLED", appointment["status"]
    assert appointment["cancellation_reason"] == "ZONE_SUSPENDED", (
        appointment["cancellation_reason"]
    )


def test_the_cancellation_hop_releases_crew_minutes_and_bumps_the_crew_version():
    """The fourth hop drops the crew from 150 booked minutes and one appointment to zero.

    PRD 3.5: "and the fourth hop, caused by those cancellations, recomputes each affected
    crew's `booked_minutes_total` and `scheduled_appointment_count` downward by the released
    `occupied_minutes` and increments each such crew's `version` by 1."

    Design: Difficulty/transitive_cascade/pole_denial_cascades_zone_suspend_appointment_cancel_crew_release
    """
    base = _denied_pole_on_a_zone_mid_build()

    crew = read_crew(base["crew"]["id"])
    assert_crew_load(crew, 0, 0)
    assert crew["version"] > base["crew_version_before"], (
        base["crew_version_before"],
        crew["version"],
    )


def test_denial_leaves_the_accepted_quote_and_the_converted_preorder_untouched():
    """Only the denied request drops out of the cost; the settled preorder is not rewound.

    PRD 3.5: "it moves `SURVEYED → DENIED`, and the zone's `make_ready_cost_cents` now
    *excludes* this request."

    Design: Difficulty/transitive_cascade/pole_denial_cascades_zone_suspend_appointment_cancel_crew_release
    """
    base = _denied_pole_on_a_zone_mid_build()

    zone = read_zone(base["zone"]["id"])
    assert_cents(
        zone["make_ready_cost_cents"], ACCEPTED_MAKE_READY_CENTS, "make_ready_cost_cents"
    )

    preorder = read_preorder(base["converted"]["id"])
    assert preorder["preorder_status"] == "CONVERTED", preorder["preorder_status"]
    assert preorder["deposit_status"] == "APPLIED", preorder["deposit_status"]
