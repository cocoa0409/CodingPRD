"""Applying a content edit: the deepest cascade in the system."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def _market_with_a_proposed_censor_edit(api):
    """A JP market in LQA, one closed FUNCTIONAL pass, one PROPOSED edit."""
    world = fx.build_market_with_edits_required(
        api, title_code="NOVA-15", name="Nova Drift 15", market_code="JP",
        scope_tier="TEXT_ONLY", target_rating="MATURE_15",
        budget_cap_cents=5000000,
        disclosed_content_codes=["VIOLENCE_REALISTIC", "BLOOD"],
        footage_asset_count=2,
    )
    legal_unit = world["units"]["legal.eula"]
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 200)
    bug = fx.log_bug(api, qa_pass["id"], bug_class="TRUNCATION", severity="S3",
                     summary="Licence line clipped at the panel edge.",
                     translation_unit_id=legal_unit["id"])
    fx.resolve_bug(api, bug["id"])
    fx.qa_mark_unit(api, legal_unit["id"], "PASSED")
    world["qa_pass"] = fx.close_qa_pass(api, qa_pass["id"])
    world["bug"] = fx.read_bug(api, bug["id"])
    world["edit"] = fx.propose_content_edit(
        api, world["submission"]["id"], edit_kind="CENSOR_ASSET",
        rationale="Blur the execution close-up and soften the ammo readout warning.",
        affected_string_key_ids=[world["keys"]["legal.eula"]["id"],
                                world["keys"]["hud.ammo"]["id"]],
        removed_content_codes=["VIOLENCE_REALISTIC"],
    )
    return world


def test_applying_an_edit_reverts_the_named_units_and_re_derives_the_cost(api):
    """The first three hops: revert, recount, revert the market and re-derive.

    "Every translation unit belonging to the submission's market plan whose
    `string_key_id` appears in `affected_string_key_ids` and whose
    `translation_status` is `DRAFTED` or `DELIVERED` reverts to
    `translation_status` `PENDING` with `qa_status` reset to `NOT_CHECKED` — a
    deliberate cross-axis reset — clearing `target_text` to null,
    `target_char_count` to 0, `overflow_chars` to 0 and `applied_tm_match_pct`
    to null, and incrementing each unit's `version` by 1."

    "Because `delivered_unit_count` has fallen below `required_unit_count`, the
    market plan reverts `LQA → IN_LOCALIZATION`, its `text_effort_units` is
    recomputed under the `DELIVERED_ACTUAL` variant over the now-shrunken
    delivered set with `text_effort_variant` set accordingly, its
    `localization_cost_cents` and `overage_cents` are recomputed, and its
    `version` increments by 1."

    Only `menu.start` at 0.1 units and `sub.intro` at 2.3 units are still
    delivered, so the effort falls to 2.40 units and 10,080 cents.

    Design: Difficulty/transitive_cascade/content_edit_apply_six_hop_cascade_to_title_and_qa_passes
    """
    world = _market_with_a_proposed_censor_edit(api)

    applied = validate_success(
        api.apply_content_edit(world["edit"]["id"], users.COMPLIANCE)
    )

    assert applied["status"] == "APPLIED"
    assert applied["invalidated_unit_count"] == 2
    A.assert_three_fractional_digits(applied["applied_at_utc"], "applied_at_utc")
    for key_name in ("legal.eula", "hud.ammo"):
        reverted = fx.read_unit(api, world["units"][key_name]["id"])
        assert reverted["translation_status"] == "PENDING"
        assert reverted["qa_status"] == "NOT_CHECKED"
        assert reverted["target_text"] is None
        assert reverted["target_char_count"] == 0
        assert reverted["overflow_chars"] == 0
        assert reverted["applied_tm_match_pct"] is None
    untouched = fx.read_unit(api, world["units"]["menu.start"]["id"])
    assert untouched["translation_status"] == "DELIVERED"
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["delivered_unit_count"] == 2
    assert plan["required_unit_count"] == 4
    assert plan["status"] == "IN_LOCALIZATION"
    A.assert_effort_units(plan["text_effort_units"], 2.40)
    assert plan["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_money_cents(plan["localization_cost_cents"], 10080,
                         "localization_cost_cents")


def test_a_censor_edit_leaves_the_named_string_keys_locked(api):
    """Only a content removal retires source strings.

    "Conditionally, and only when `edit_kind` is `REMOVE_CONTENT`: every string
    key named in `affected_string_key_ids` whose `status` is `LOCKED`
    transitions to `RETIRED`, which lowers the market plan's
    `required_unit_count`."

    Design: Difficulty/transitive_cascade/content_edit_apply_six_hop_cascade_to_title_and_qa_passes
    """
    world = _market_with_a_proposed_censor_edit(api)

    fx.apply_content_edit(api, world["edit"]["id"])

    for key_name in ("legal.eula", "hud.ammo"):
        key = validate_success(
            api.get_string_key(world["keys"][key_name]["id"], users.PRODUCER)
        )
        assert key["status"] == "LOCKED"
    assert fx.read_plan(api, world["plan"]["id"])["required_unit_count"] == 4
    assert fx.read_title(api, world["title"]["id"])["extracted_key_count"] == 4


def test_the_cascade_reopens_the_closed_pass_and_revives_its_verified_defect(api):
    """Hops four and five reach two entity types the trigger never named.

    "Because the market plan left `LQA`, every QA pass of that market plan whose
    `status` is `CLOSED` reopens `CLOSED → OPEN` with `reopen_count` increased
    by 1 and `closed_at_utc` cleared to null."

    "Because those passes reopened, every defect of those passes whose `status`
    is `VERIFIED` and whose `translation_unit_id` was reverted in hop 2 goes
    `VERIFIED → TRIAGED`, which raises the passes' `weighted_defect_points` and
    `defect_density` again."

    The revived `S3` defect is worth 2 points over 200 inspected units, so the
    density climbs off zero to 0.0100.

    Design: Difficulty/transitive_cascade/content_edit_apply_six_hop_cascade_to_title_and_qa_passes
    """
    world = _market_with_a_proposed_censor_edit(api)
    assert world["qa_pass"]["status"] == "CLOSED"
    assert world["qa_pass"]["reopen_count"] == 0
    assert world["bug"]["status"] == "VERIFIED"

    fx.apply_content_edit(api, world["edit"]["id"])

    reopened = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    assert reopened["closed_at_utc"] is None
    assert fx.read_bug(api, world["bug"]["id"])["status"] == "TRIAGED"
    assert reopened["weighted_defect_points"] == 2
    A.assert_defect_density(reopened["defect_density"], 0.0100)


def test_the_cascade_finally_pulls_the_title_out_of_its_certification_window(api):
    """Hop six lands on the title, four entity types from the trigger.

    "Because the market plan left `LQA`, the title reverts `CERT_WINDOW →
    STRINGS_LOCKED` and its `release_gate_state` is recomputed, with its
    `version` incremented by 1."

    "Otherwise the posture is `OPEN`. A title with zero market plans is
    therefore `OPEN`."

    With the clock still at its startup value the sole market is 122 days from
    release, so no earlier clause of the ordered chain matches.

    Design: Difficulty/transitive_cascade/content_edit_apply_six_hop_cascade_to_title_and_qa_passes
    """
    world = _market_with_a_proposed_censor_edit(api)
    before = fx.read_title(api, world["title"]["id"])
    assert before["localization_state"] == "CERT_WINDOW"

    fx.apply_content_edit(api, world["edit"]["id"])

    title = fx.read_title(api, world["title"]["id"])
    assert title["localization_state"] == "STRINGS_LOCKED"
    assert title["release_gate_state"] == "OPEN"
    assert title["string_lock"] is True
    A.assert_version_bumped_by(title, before, 1, "title")


def test_withdrawing_a_proposed_edit_cascades_nowhere(api):
    """The other exit from `PROPOSED` touches nothing downstream.

    "Withdrawing a proposed edit moves it `PROPOSED → WITHDRAWN` under a
    `ComplianceOfficer` or a `LocalizationProducer`; an edit that is not
    `PROPOSED` refuses with `ERR_CONTENT_EDIT_NOT_PROPOSED`."

    "There is no cascade, because nothing was applied: no translation unit, QA
    pass or market plan changes state."

    Design: Difficulty/transitive_cascade/content_edit_apply_six_hop_cascade_to_title_and_qa_passes
    """
    world = _market_with_a_proposed_censor_edit(api)

    withdrawn = validate_success(
        api.withdraw_content_edit(world["edit"]["id"], users.COMPLIANCE)
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["invalidated_unit_count"] == 0
    assert withdrawn["applied_at_utc"] is None
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["status"] == "LQA"
    assert plan["delivered_unit_count"] == 4
    assert fx.read_qa_pass(api, world["qa_pass"]["id"])["status"] == "CLOSED"
    assert fx.read_unit(api, world["units"]["hud.ammo"]["id"])[
        "translation_status"] == "DELIVERED"
    assert fx.read_title(api, world["title"]["id"])["localization_state"] == "CERT_WINDOW"


def test_the_removed_descriptor_leaves_the_effective_disclosure_set(api):
    """Applying an edit rewrites the arithmetic the next round will use.

    "Alongside those hops, the descriptors in `removed_content_codes` leave the
    submission's effective disclosure set, which lowers the next board-adjusted
    risk score by their descriptor weights and additionally credits 5 points
    because the edit is now `APPLIED`."

    Design: Difficulty/transitive_cascade/content_edit_apply_six_hop_cascade_to_title_and_qa_passes
    """
    world = _market_with_a_proposed_censor_edit(api)

    fx.apply_content_edit(api, world["edit"]["id"])

    edits, meta = validate_paginated(
        api.list_content_edits(
            users.COMPLIANCE,
            {"rating_submission_id": world["submission"]["id"], "status": "APPLIED"},
        )
    )
    assert meta["total_count"] == 1
    assert edits[0]["removed_content_codes"] == ["VIOLENCE_REALISTIC"]
    assert edits[0]["status"] == "APPLIED"
    submission = fx.read_submission(api, world["submission"]["id"])
    assert submission["disclosed_content_codes"] == ["VIOLENCE_REALISTIC", "BLOOD"]
    assert submission["status"] == "EDITS_REQUIRED"
