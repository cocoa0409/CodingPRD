"""The first matching enabled rule decides, not the strictest one.

The same MAIL contact is refused and then accepted with no event deleted in
between: adding a lower-priority-number MAIL rule with a generous ceiling displaces
the ALL-scope rule that had just blocked an EMAIL, so the two channels start behaving
differently under one identical event history. The disabled rule at the start proves
is_enabled gates the check entirely, and every contact is aged 61-90 days so the
fatigue score stays far below the suppression threshold and cannot mask the outcome.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    CLOCK_START,
    create_contact_event_payload,
    fetch_segment,
    iso_utc,
    new_contact_event,
    new_season,
    new_segment,
    new_suppression_rule,
    set_clock,
    validate_error,
    validate_paginated,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}


def _a_segment_governed_only_by_a_disabled_rule() -> dict:
    """CAP_MAIL_OFF would cap MAIL at two contacts, but it is registered with
    is_enabled false, so three MAIL touches go in unopposed."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)
    rule_off = new_suppression_rule(
        season["id"],
        rule_code="CAP_MAIL_OFF",
        channel_scope="MAIL",
        window_days=90,
        max_contacts_per_window=2,
        priority=10,
        is_enabled=False,
    )
    mails = [
        new_contact_event(segment["id"], iso_utc(date), "MAIL")
        for date in ("2026-06-01", "2026-05-20", "2026-05-10")
    ]
    return {"season": season, "segment": segment, "rule_off": rule_off,
            "mails": mails}


def _the_all_scope_rule_taking_the_count_to_its_ceiling(api) -> dict:
    """CAP_ALL counts every channel together with a ceiling of five, so the fourth
    and fifth contacts are admitted and the sixth is refused."""
    world = _a_segment_governed_only_by_a_disabled_rule()
    segment_id = world["segment"]["id"]
    world["rule_all"] = new_suppression_rule(
        world["season"]["id"],
        rule_code="CAP_ALL",
        channel_scope="ALL",
        window_days=90,
        max_contacts_per_window=5,
        priority=20,
        is_enabled=True,
    )
    world["fourth"] = new_contact_event(segment_id, iso_utc("2026-05-15"), "EMAIL")
    world["fifth"] = new_contact_event(segment_id, iso_utc("2026-05-16"), "DIGITAL")
    world["sixth"] = api.create_contact_event(
        create_contact_event_payload(segment_id, iso_utc("2026-05-17"), "EMAIL"),
        ANALYST,
    )
    return world


def _a_loose_mail_rule_ahead_of_the_all_scope_rule(api) -> dict:
    """CAP_MAIL_LOOSE sits at priority 5, ahead of CAP_ALL, and caps MAIL at ten."""
    world = _the_all_scope_rule_taking_the_count_to_its_ceiling(api)
    segment_id = world["segment"]["id"]
    world["rule_loose"] = new_suppression_rule(
        world["season"]["id"],
        rule_code="CAP_MAIL_LOOSE",
        channel_scope="MAIL",
        window_days=90,
        max_contacts_per_window=10,
        priority=5,
        is_enabled=True,
    )
    world["fourth_mail"] = new_contact_event(
        segment_id, iso_utc("2026-05-18"), "MAIL"
    )
    world["late_email"] = api.create_contact_event(
        create_contact_event_payload(segment_id, iso_utc("2026-05-19"), "EMAIL"),
        ANALYST,
    )
    return world


class TestADisabledRuleDoesNotParticipate:
    def test_three_mail_touches_pass_a_disabled_cap_of_two(self, api):
        """PRD §3.8: "Each rule carries a `rule_code` such as `CAP_EMAIL_30D`, unique
        within the season with a repeat rejected as
        `ERR_DUPLICATE_SUPPRESSION_RULE_CODE`; a `channel_scope` of `MAIL`, `EMAIL`,
        `DIGITAL` or `ALL`, where `ALL` counts every channel together; a `window_days`
        trailing window between 1 and 365 whole days inclusive; a
        `max_contacts_per_window` ceiling that may not be negative; a `priority` of at
        least 1 that fixes evaluation order among a season's rules, with lower numbers
        evaluated first and `created_at` ascending breaking ties; and an `is_enabled`
        flag that defaults to true and determines whether the rule participates at
        all."

        Design: Corner/validations/the_contact_cap_binds_only_when_an_enabled_rule_matches_first_by_priority
        """
        world = _a_segment_governed_only_by_a_disabled_rule()

        assert world["rule_off"]["is_enabled"] is False
        assert world["rule_off"]["max_contacts_per_window"] == 2
        assert len(world["mails"]) == 3

        rows, meta = validate_paginated(
            api.list_segment_contact_events(world["segment"]["id"], ANALYST)
        )
        assert meta["total_count"] == 3
        assert all(row["channel"] == "MAIL" for row in rows)


class TestTheFirstMatchingEnabledRuleDecides:
    def test_a_count_reaching_the_ceiling_is_admitted_and_the_next_is_not(self, api):
        """PRD §3.8: "Before the row is written, the season's enabled suppression
        rules are consulted in ascending `priority`: the **first** enabled rule whose
        `channel_scope` covers the contact's channel — either matching it exactly or
        being `ALL` — is the one that decides, and no later rule is consulted. That
        rule counts the segment's existing in-scope contact events within its
        `window_days` trailing window, and if admitting the new contact would push the
        count past `max_contacts_per_window` the request is rejected with
        `ERR_CONTACT_CAP_EXCEEDED`."

        Design: Corner/validations/the_contact_cap_binds_only_when_an_enabled_rule_matches_first_by_priority
        """
        world = _the_all_scope_rule_taking_the_count_to_its_ceiling(api)

        assert world["fourth"]["channel"] == "EMAIL"
        assert world["fifth"]["channel"] == "DIGITAL"
        validate_error(world["sixth"], "ERR_CONTACT_CAP_EXCEEDED", 422)

        _, meta = validate_paginated(
            api.list_segment_contact_events(world["segment"]["id"], ANALYST)
        )
        assert meta["total_count"] == 5

    def test_a_looser_rule_at_a_lower_priority_displaces_the_all_scope_rule(
        self, api
    ):
        """PRD §3.8: "Before the row is written, the season's enabled suppression
        rules are consulted in ascending `priority`: the **first** enabled rule whose
        `channel_scope` covers the contact's channel — either matching it exactly or
        being `ALL` — is the one that decides, and no later rule is consulted. That
        rule counts the segment's existing in-scope contact events within its
        `window_days` trailing window, and if admitting the new contact would push the
        count past `max_contacts_per_window` the request is rejected with
        `ERR_CONTACT_CAP_EXCEEDED`."

        Design: Corner/validations/the_contact_cap_binds_only_when_an_enabled_rule_matches_first_by_priority
        """
        world = _a_loose_mail_rule_ahead_of_the_all_scope_rule(api)

        assert world["fourth_mail"]["channel"] == "MAIL"
        validate_error(world["late_email"], "ERR_CONTACT_CAP_EXCEEDED", 422)

        rows, meta = validate_paginated(
            api.list_segment_contact_events(world["segment"]["id"], ANALYST)
        )
        assert meta["total_count"] == 6
        stored = {row["id"] for row in rows}
        assert world["mails"][2]["id"] in stored
        assert world["fourth_mail"]["id"] in stored

    def test_the_enabled_filter_never_returns_the_disabled_rule(self, api):
        """PRD §3.8: "The collection read for a season's rules accepts
        `channel_scope` and `is_enabled` as filters."

        Design: Corner/validations/the_contact_cap_binds_only_when_an_enabled_rule_matches_first_by_priority
        """
        world = _a_loose_mail_rule_ahead_of_the_all_scope_rule(api)

        rows, meta = validate_paginated(
            api.list_suppression_rules(
                world["season"]["id"], ADMIN, params={"is_enabled": "true"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            world["rule_all"]["id"],
            world["rule_loose"]["id"],
        }
        assert world["rule_off"]["id"] not in {row["id"] for row in rows}


class TestTheSoftScoreNeverInterferes:
    def test_every_touch_sits_in_the_same_decay_band_well_under_the_threshold(
        self, api
    ):
        """PRD §3.8: "Each surviving contact's contribution is its channel weight
        multiplied by its decay factor, divided by ten thousand, rounded half up to
        whole points, and `fatigue_score` is the exact sum of those individually
        rounded contributions."

        Design: Corner/validations/the_contact_cap_binds_only_when_an_enabled_rule_matches_first_by_priority
        """
        world = _a_loose_mail_rule_ahead_of_the_all_scope_rule(api)
        segment = fetch_segment(world["segment"]["id"], ANALYST)

        assert segment["fatigue_score"] == 45
        assert segment["fatigue_score"] == (4 * 10) + 3 + 2
        assert segment["contact_strategy"] == "PREMIUM_FULL"
        assert segment["suppressed_at"] is None
