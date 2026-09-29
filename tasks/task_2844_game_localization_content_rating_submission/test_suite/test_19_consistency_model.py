"""Immediate consistency: every recomputed field is in the response that caused it.

There is no settling period anywhere in this specification, so each write below is
checked twice — once in its own response body, and once in the very next read of
the row or of the parent the write reached.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# A HUD string whose Japanese rendering runs 15 characters past the 4:3 readout.
_NARROW_HUD_SPEC = {
    "key_name": "hud.ammo",
    "source_text": "Ammo",
    "source_char_count": 60,
    "ui_surface": "HUD",
    "display_char_limit": 80,
    "tm_match_pct": 80,
}
_OVERLONG_HUD_TEXT = "残" * 95
_MENU_TEXT = "ゲームを始める"


def _locked_two_key_title(api, title_code, name):
    """A frozen two-key string set and a JP plan still in `DRAFT`.

    The MENU key contributes 0.1 effort units (125 chars, exact match, no uplift)
    and the HUD key 0.3 (60 chars, high-fuzzy 0.45, HUD uplift 1.10), so the
    estimate is 0.40 units and the TEXT_ONLY cost is 1,680 cents.
    """
    title = fx.create_title(api, title_code=title_code, name=name)
    keys = {
        "menu.start": fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC),
        "hud.ammo": fx.create_string_key(api, title["id"], **_NARROW_HUD_SPEC),
    }
    plan = fx.create_market_plan(api, title["id"], market_code="JP",
                                 scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                                 budget_cap_cents=5000000)
    title = fx.lock_strings(api, title["id"])
    return {"title": title, "keys": keys, "plan": plan}


def _handed_to_the_vendor(api, title_code, name):
    """The same two-key market driven through scope into `IN_LOCALIZATION`."""
    world = _locked_two_key_title(api, title_code, name)
    world["plan"] = fx.scope_plan(api, world["plan"]["id"])
    world["plan"] = fx.start_localization(api, world["plan"]["id"])
    world["units"] = fx.units_by_key_name(api, world["plan"]["id"], world["keys"])
    return world


def test_scopes_own_response_already_carries_the_effort_the_cost_and_the_count(api):
    """No second call is needed to see what scoping computed.

    "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    "Scoping computes the **translation effort estimate** under its first variant
    and sets `required_unit_count` to the count of the title's non-retired string
    keys."

    "The plan must be in `SCOPED`, else `ERR_MARKET_PLAN_STATE_INVALID`."

    "The consistency model is immediate; there is no deferred reconciliation."

    The hand-off attempted before scoping is refused, which proves the numbers
    below were produced by the scope call itself and by nothing that ran earlier.

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
    """
    world = _locked_two_key_title(api, "NOVA-89", "Nova Drift 89")
    plan_id = world["plan"]["id"]
    assert world["plan"]["text_effort_variant"] is None

    validate_error(api.start_localization(plan_id, users.PRODUCER),
                   E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409)

    scoped = validate_success(api.scope_market_plan(plan_id, users.PRODUCER))

    assert scoped["status"] == "SCOPED"
    A.assert_effort_units(scoped["text_effort_units"], 0.40)
    assert scoped["text_effort_variant"] == "SCOPE_ESTIMATE"
    A.assert_money_cents(scoped["localization_cost_cents"], 1680,
                         "localization_cost_cents")
    A.assert_money_cents(scoped["overage_cents"], 0, "overage_cents")
    assert scoped["required_unit_count"] == 2

    immediately = fx.read_plan(api, plan_id)
    A.assert_effort_units(immediately["text_effort_units"], 0.40)
    A.assert_money_cents(immediately["localization_cost_cents"], 1680,
                         "localization_cost_cents")
    assert immediately["required_unit_count"] == 2
    A.assert_unchanged_row(immediately, scoped, "market_plan")


def test_the_text_write_response_already_reports_the_overflow_it_created(api):
    """The recomputed character count and overflow ride back on the PUT itself.

    "On success the server stores the text and recomputes `target_char_count` as
    the character length of `target_text` — zero when `target_text` is null — and
    recomputes `overflow_chars` as the amount by which `target_char_count` exceeds
    the linked string key's `display_char_limit`, floored at zero."

    "The `qa_status` axis is untouched. The unit's `version` increments by 1."

    "Delivery is deliberately permitted while `overflow_chars` is greater than
    zero: overflow is a QA finding, not a delivery gate."

    Ninety-five target characters against a `display_char_limit` of 80 is an
    overflow of 15; the MENU unit's seven characters against 140 is zero.

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
    """
    world = _handed_to_the_vendor(api, "NOVA-89B", "Nova Drift 89 B")
    hud = world["units"]["hud.ammo"]
    menu = world["units"]["menu.start"]
    assert hud["target_char_count"] == 0
    assert hud["overflow_chars"] == 0

    written = validate_success(api.write_translation_unit(
        hud["id"], f.translation_text_payload(_OVERLONG_HUD_TEXT, 95, 80),
        users.VENDOR,
    ))

    assert written["translation_status"] == "DRAFTED"
    assert written["target_char_count"] == 95
    assert written["overflow_chars"] == 15
    assert written["qa_status"] == "NOT_CHECKED"
    A.assert_version_bumped_by(written, hud, 1, "translation_unit")

    immediately = fx.read_unit(api, hud["id"])
    assert immediately["target_char_count"] == 95
    assert immediately["overflow_chars"] == 15
    A.assert_unchanged_row(immediately, written, "translation_unit")

    menu_written = validate_success(api.write_translation_unit(
        menu["id"], f.translation_text_payload(_MENU_TEXT, 7, 96), users.VENDOR
    ))
    assert menu_written["target_char_count"] == 7
    assert menu_written["overflow_chars"] == 0


def test_each_delivery_and_the_qa_hand_off_publish_their_totals_at_once(api):
    """A cascade's effect on the parent is readable on the very next call.

    "Delivery records `applied_tm_match_pct` and recomputes the market plan's
    `delivered_unit_count`, incrementing both the unit's and the market plan's
    `version` by 1."

    "On success the plan's `text_effort_units` is recomputed under the
    `DELIVERED_ACTUAL` variant with `text_effort_variant` set accordingly,
    `localization_cost_cents` and `overage_cents` are recomputed from the new
    effort figure, and the plan's `version` increments by 1."

    "The same request then bubbles the title up: if every market plan of the title
    now sits in `LQA` or `RELEASE_READY` and the title has at least one market
    plan, the title moves `STRINGS_LOCKED → CERT_WINDOW`, its `release_gate_state`
    is recomputed, and its `version` increments by 1."

    The vendor reused exactly the matches extraction predicted — 96 on the MENU key
    and 80 on the HUD key — so `DELIVERED_ACTUAL` reproduces the estimate's 0.40
    units and 1,680 cents, and the change that must be visible immediately is the
    variant label rather than the number.

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
    """
    world = _handed_to_the_vendor(api, "NOVA-89C", "Nova Drift 89 C")
    plan_id = world["plan"]["id"]
    menu = world["units"]["menu.start"]
    hud = world["units"]["hud.ammo"]
    assert fx.read_plan(api, plan_id)["delivered_unit_count"] == 0
    fx.write_unit_text(api, menu["id"], _MENU_TEXT, 96, 7)

    delivered = validate_success(
        api.deliver_translation_unit(menu["id"], users.VENDOR)
    )

    assert delivered["translation_status"] == "DELIVERED"
    assert delivered["applied_tm_match_pct"] == 96
    after_one = fx.read_plan(api, plan_id)
    assert after_one["delivered_unit_count"] == 1
    assert after_one["required_unit_count"] == 2
    assert after_one["text_effort_variant"] == "SCOPE_ESTIMATE"
    A.assert_version_bumped_by(after_one, world["plan"], 1, "market_plan")

    fx.draft_and_deliver_unit(api, hud["id"], _OVERLONG_HUD_TEXT, 80, 95)
    before_lqa = fx.read_plan(api, plan_id)
    assert before_lqa["delivered_unit_count"] == 2

    in_lqa = validate_success(api.enter_lqa(plan_id, users.PRODUCER))

    assert in_lqa["status"] == "LQA"
    assert in_lqa["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_effort_units(in_lqa["text_effort_units"], 0.40)
    A.assert_money_cents(in_lqa["localization_cost_cents"], 1680,
                         "localization_cost_cents")
    A.assert_money_cents(in_lqa["overage_cents"], 0, "overage_cents")
    A.assert_version_bumped_by(in_lqa, before_lqa, 1, "market_plan")

    title = fx.read_title(api, world["title"]["id"])
    assert title["localization_state"] == "CERT_WINDOW"
    assert fx.read_plan(api, plan_id)["text_effort_variant"] == "DELIVERED_ACTUAL"


def test_the_defect_filing_returns_its_own_weight_and_the_pass_and_unit_agree(api):
    """One filing recomputes three rows, and all three are already current.

    "A new pass opens in `status` `OPEN` with `opened_by_user_id` set to the acting
    `X-User-ID`, `reopen_count` 0, `weighted_defect_points` 0, `defect_density`
    0.0000 and `closed_at_utc` null."

    "Two fields are derived and never supplied: `severity_weight` is the weight of
    the declared `severity`, and `axis` is `LINGUISTIC` when `bug_class` is
    `MISTRANSLATION`, `CULTURAL` or `LEGAL_TEXT`, and `FUNCTIONAL` when it is
    `TEXT_OVERFLOW`, `TRUNCATION` or `FUNCTIONAL_CRASH`."

    "A new defect opens in `status` `NEW` with `logged_by_user_id` set to the
    acting `X-User-ID`, `verified_by_user_id` null and `duplicate_of_bug_id` null;
    the linked unit's `open_bug_count` is incremented, the pass's density figures
    are recomputed, and when the class is `LEGAL_TEXT` the board-adjusted risk
    arithmetic of §3.7 changes as a consequence."

    "Logging a defect whose derived axis is functional drives the unit to
    `FUNC_FLAGGED`, but only from `NOT_CHECKED` or from `PASSED`; a unit already
    sitting at `LING_FLAGGED` is **not** overwritten by a functional finding."

    One open `S2` over twenty inspected units is four weighted points and a density
    of 0.2000, and the pass that opened one call earlier reported 0 and 0.0000.

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
    """
    world = _handed_to_the_vendor(api, "NOVA-89D", "Nova Drift 89 D")
    hud = world["units"]["hud.ammo"]
    fx.write_unit_text(api, hud["id"], _OVERLONG_HUD_TEXT, 80, 95)

    opened = validate_success(
        api.create_qa_pass(f.qa_pass_payload(world["plan"]["id"], "FUNCTIONAL", 20),
                           users.LQA_OPENER),
        expected_status=201,
    )
    assert opened["status"] == "OPEN"
    assert opened["reopen_count"] == 0
    assert opened["weighted_defect_points"] == 0
    A.assert_defect_density(opened["defect_density"], 0.0000)
    assert opened["closed_at_utc"] is None

    logged = validate_success(
        api.create_lqa_bug(
            f.lqa_bug_payload(opened["id"], bug_class="TEXT_OVERFLOW", severity="S2",
                              summary="Ammo readout runs 15 characters past the HUD.",
                              translation_unit_id=hud["id"]),
            users.LQA_LOGGER,
        ),
        expected_status=201,
    )

    assert logged["status"] == "NEW"
    assert logged["severity_weight"] == 4
    assert logged["axis"] == "FUNCTIONAL"
    assert logged["verified_by_user_id"] is None
    assert logged["duplicate_of_bug_id"] is None

    pass_now = fx.read_qa_pass(api, opened["id"])
    assert pass_now["weighted_defect_points"] == 4
    A.assert_defect_density(pass_now["defect_density"], 0.2000)
    A.assert_version_bumped_by(pass_now, opened, 1, "qa_pass")

    unit_now = fx.read_unit(api, hud["id"])
    assert unit_now["qa_status"] == "FUNC_FLAGGED"
    assert unit_now["open_bug_count"] == 1
    assert unit_now["translation_status"] == "DRAFTED"
    assert unit_now["overflow_chars"] == 15
