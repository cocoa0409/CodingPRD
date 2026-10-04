"""Cash rewards: pending accrual at pay, settlement, void clawback."""
from test_helpers import (
    ADMIN,
    ASSOCIATE,
    LPO,
    ApiErrorId,
    create_item,
    create_member,
    create_session,
    get_member,
    member_headers,
    scan_unit_line,
    setup_club_member,
    setup_paid_session,
    validate_success,
)


class TestPendingVsPostedVariants:
    def test_rewards_pending_vs_posted_after_void_excludes_voided(self, api):
        """PRD §3.8: "Sessions in `VOIDED` contribute nothing at settle time —
        their pending contribution was already clawed back by the void (§3.4)
        — which is exactly how the pending and posted figures diverge for
        identical payment data when a session is voided between pay and
        settle."

        Design: Difficulty/dual_variant_calc/rewards_pending_vs_posted_after_void
        """
        club, member_a, member_b, session_a, session_b = _two_paid_plus_members(api)

        resp = api.void_payment(session_a["id"], LPO)
        voided = validate_success(resp)
        assert voided["status"] == "VOIDED"
        assert voided["refunded_cents"] == 5000

        resp = api.settle_rewards(member_a["id"], ADMIN)
        validate_success(resp)
        resp = api.settle_rewards(member_b["id"], ADMIN)
        validate_success(resp)

        a = get_member(member_a["id"])
        b = get_member(member_b["id"])
        assert a["cash_rewards_pending_cents"] == 0
        assert a["cash_rewards_posted_cents"] == 0
        assert b["cash_rewards_posted_cents"] == 100

    def test_rewards_pending_accrues_at_pay_and_posts_at_settle(self, api):
        """PRD §3.8: "At pay time, a `PLUS` member's session contributes the
        integer floor of `qualifying_cents` multiplied by 2 and divided by
        100; this contribution is added to the member's
        `cash_rewards_pending_cents` and recorded on the session as
        `rewards_contribution_cents`."

        Design: Difficulty/dual_variant_calc/rewards_pending_vs_posted_after_void
        """
        club, member_a, member_b, session_a, session_b = _two_paid_plus_members(api)
        # Both members paid 5000c -> 100c pending each before any void.
        a = get_member(member_a["id"])
        b = get_member(member_b["id"])
        assert a["cash_rewards_pending_cents"] == 100
        assert b["cash_rewards_pending_cents"] == 100

        resp = api.settle_rewards(member_b["id"], ADMIN)
        validate_success(resp)
        b_after = get_member(member_b["id"])
        assert b_after["cash_rewards_posted_cents"] == 100
        # A never settles: pending stays, posted stays zero.
        a_after = get_member(member_a["id"])
        assert a_after["cash_rewards_posted_cents"] == 0


def _two_paid_plus_members(api):
    """Club with a 2500c UNIT item; PLUS members A and B each pay 2 units."""
    club, _unused = setup_club_member()
    item = create_item(club["id"], sku="TV-55", unit_price_cents=2500)
    member_a = create_member(club["id"], tier="PLUS", birth_year=1985)
    member_b = create_member(club["id"], tier="PLUS", birth_year=1988)

    sessions = []
    for member in (member_a, member_b):
        session = create_session(club, member)
        scan_unit_line(session, member, item, quantity=2)
        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["status"] == "PAID", f"Setup failed: {resp.text}"
        assert paid["final_total_cents"] == 5000
        sessions.append(session)
    return club, member_a, member_b, sessions[0], sessions[1]


class TestRewardEligibility:
    def test_club_tier_earns_no_cash_rewards(self, api):
        """PRD §3.8: "`CLUB`-tier members accrue nothing — both stages are
        always zero for them."

        Design: Corner/calculations/club_tier_earns_no_cash_rewards
        """
        club, item, member, session, pay_data = setup_paid_session(
            price_cents=2500, quantity=2,
            member_overrides={"tier": "CLUB", "birth_year": 1990},
        )
        assert pay_data["final_total_cents"] == 5000

        resp = api.settle_rewards(member["id"], ADMIN)
        settled = validate_success(resp)
        assert settled["cash_rewards_pending_cents"] == 0
        assert settled["cash_rewards_posted_cents"] == 0

    def test_rewards_exclude_restricted_lines_from_qualifying(self, api):
        """PRD §3.4: "The session also records `qualifying_cents` at pay time:
        the portion of `final_total_cents` attributable to unrestricted
        merchandise, computed as the final total minus the `line_total_cents`
        of every non-`REMOVED` line whose `restricted_class_snapshot` is not
        `NONE`."; PRD §3.8: "a `PLUS` member's session contributes the integer
        floor of `qualifying_cents` multiplied by 2 and divided by 100".

        Design: Corner/calculations/rewards_exclude_restricted_lines_from_qualifying
        """
        club, member = setup_club_member(
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        good_item = create_item(club["id"], sku="TV", unit_price_cents=3000)
        alc_item = create_item(
            club["id"], sku="WINE", unit_price_cents=2000,
            restricted_class="ALCOHOL",
        )
        session = create_session(club, member)
        scan_unit_line(session, member, good_item, quantity=1)
        scan_unit_line(session, member, alc_item, quantity=1)

        resp = api.list_session_intercepts(session["id"], ASSOCIATE)
        intercept = resp.json()["data"][0]
        resp = api.resolve_intercept(
            intercept["id"], {"decision": "APPROVE", "birth_year_verified": True},
            ASSOCIATE,
        )
        assert resp.status_code == 200, f"Setup failed: {resp.text}"

        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["final_total_cents"] == 5000
        assert paid["qualifying_cents"] == 3000
        # floor(3000 * 2 / 100) = 60.
        assert paid["rewards_contribution_cents"] == 60
