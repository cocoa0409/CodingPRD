"""Risk-score variants and the frozen submission fee."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def _market_at_lqa_with_one_key(api, title_code, name, target_rating):
    return fx.build_market(api, title_code=title_code, name=name,
                           market_code="JP", scope_tier="TEXT_ONLY",
                           target_rating=target_rating,
                           budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)


def test_self_assessed_score_is_the_descriptor_weights_alone(api):
    """Filing freezes the publisher's own questionnaire arithmetic.

    "The `SELF_ASSESSED` variant is the publisher's own questionnaire
    arithmetic: it is the base points alone, clamped to lie between 0 and 100
    inclusive, and it ignores unresolved legal defects and content edits
    entirely."

    `VIOLENCE_STYLIZED` 12 plus `BLOOD` 15 plus `LANGUAGE_STRONG` 10 is 37
    points even though the market carries a triaged `LEGAL_TEXT` defect, and a
    round-one `CERO` filing 122 days before release is 480,000 less a five per
    cent discount of 24,000, that is 456,000 cents.

    Design: Difficulty/dual_variant_calc/rating_risk_self_assessed_vs_board_adjusted
    """
    world = _market_at_lqa_with_one_key(api, "NOVA-8", "Nova Drift 8", "MATURE_15")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 100)
    bug = fx.log_bug(api, qa_pass["id"], bug_class="LEGAL_TEXT", severity="S2",
                     summary="Mandatory age notice omitted from the JP legal screen.")
    fx.triage_bug(api, bug["id"], "ACCEPT")
    submission = fx.draft_submission(
        api, world["plan"]["id"],
        ["VIOLENCE_STYLIZED", "BLOOD", "LANGUAGE_STRONG"], 1, "MATURE_15",
    )

    filed = validate_success(
        api.submit_rating_submission(submission["id"], users.COMPLIANCE)
    )

    assert filed["status"] == "SUBMITTED"
    assert filed["submission_round"] == 1
    assert filed["self_assessed_risk_score"] == 37
    A.assert_money_cents(filed["fee_cents"], 456000, "fee_cents")
    assert filed["board_adjusted_risk_score"] is None


def test_board_adjusted_score_adds_the_unresolved_legal_defect_penalty(api):
    """Review entry recomputes the score with the board's penalties.

    "The `BOARD_ADJUSTED` variant starts from the same base points, adds 6
    points for each unresolved legal defect, adds 9 points for each proposed
    edit, subtracts 5 points for each applied edit, and clamps the result to lie
    between 0 and 100 inclusive."

    "The unresolved legal-defect count is the number of defects whose
    `bug_class` is `LEGAL_TEXT` and whose `status` is `NEW`, `TRIAGED` or
    `FIX_SUBMITTED`, counted across every QA pass of the submission's market
    plan regardless of that pass's `pass_type` or `status`."

    The one triaged `LEGAL_TEXT` defect lifts 37 to 43, which crosses the
    boundary from `TEEN_12` into `MATURE_15` while the frozen self-assessment
    stays at 37.

    Design: Difficulty/dual_variant_calc/rating_risk_self_assessed_vs_board_adjusted
    """
    world = _market_at_lqa_with_one_key(api, "NOVA-8", "Nova Drift 8", "MATURE_15")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 100)
    bug = fx.log_bug(api, qa_pass["id"], bug_class="LEGAL_TEXT", severity="S2",
                     summary="Mandatory age notice omitted from the JP legal screen.")
    fx.triage_bug(api, bug["id"], "ACCEPT")
    submission = fx.draft_submission(
        api, world["plan"]["id"],
        ["VIOLENCE_STYLIZED", "BLOOD", "LANGUAGE_STRONG"], 1, "MATURE_15",
    )
    fx.submit_submission(api, submission["id"])

    reviewed = validate_success(api.begin_review(submission["id"], users.BOARD))

    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["board_adjusted_risk_score"] == 43
    assert reviewed["projected_rating_band"] == "MATURE_15"
    assert reviewed["self_assessed_risk_score"] == 37
    assert A.band_for_score(37) == "TEEN_12"
    reread_pass = fx.read_qa_pass(api, qa_pass["id"])
    A.assert_defect_density(reread_pass["defect_density"], 0.0400)


def test_round_one_fee_carries_no_expedite_and_a_five_per_cent_tier(api):
    """A filing far from release pays base fee less the volume discount.

    "Step two computes an expedite fee: when the days to release is fewer than
    45, it is thirty per cent of the pre-discount subtotal rounded half up to
    whole cents, and otherwise it is zero."

    With the clock still at its 2026-08-01T00:00:00Z startup value and a
    2026-12-01 release the days to release is 122, so the `CERO` round-one
    subtotal of 480,000 attracts no expedite fee, a five per cent tier and a
    24,000-cent discount.

    Design: Difficulty/combinatorial_formula/submission_fee_discount_tier_keyed_on_pre_discount_subtotal
    """
    world = _market_at_lqa_with_one_key(api, "NOVA-11", "Nova Drift 11", "TEEN_12")
    submission = fx.draft_submission(api, world["plan"]["id"],
                                     ["VIOLENCE_STYLIZED"], 0, "TEEN_12")

    filed = validate_success(
        api.submit_rating_submission(submission["id"], users.COMPLIANCE)
    )

    assert filed["submission_round"] == 1
    A.assert_money_cents(filed["fee_cents"], 456000, "fee_cents")


def test_round_two_discount_tier_is_keyed_on_the_pre_discount_subtotal(api):
    """The expedite fee never moves the volume-discount tier.

    "Step three selects a volume discount percentage **keyed on the
    pre-discount subtotal only**: ten per cent when that subtotal is at least
    600,000 cents, otherwise five per cent when it is at least 400,000 cents,
    otherwise zero."

    A round-two `CERO` filing 26 days out has a pre-discount subtotal of
    555,000 and an expedite fee of 166,500. The tier is read off 555,000, so it
    is five per cent and the discount is 27,750, giving 693,750 — not the
    649,350 that keying the tier on the 721,500 post-expedite total produces.

    Design: Difficulty/combinatorial_formula/submission_fee_discount_tier_keyed_on_pre_discount_subtotal
    """
    world = _market_at_lqa_with_one_key(api, "NOVA-11", "Nova Drift 11", "TEEN_12")
    first = fx.draft_submission(api, world["plan"]["id"], ["VIOLENCE_STYLIZED"], 0,
                               "TEEN_12")
    fx.send_back_for_edits(api, first["id"])
    fx.set_clock(api, "2026-11-05T00:00:00Z")
    second = fx.draft_submission(api, world["plan"]["id"], ["VIOLENCE_STYLIZED"], 0,
                                "TEEN_12")

    filed = validate_success(
        api.submit_rating_submission(second["id"], users.COMPLIANCE)
    )

    assert filed["submission_round"] == 2
    A.assert_money_cents(filed["fee_cents"], 693750, "fee_cents")
    assert filed["fee_cents"] != 649350


def test_a_new_round_supersedes_the_prior_submission_and_the_gate_reacts(api):
    """Filing a fresh round withdraws the one it replaces.

    "Creating a submission also supersedes the market's prior non-terminal
    submission into `WITHDRAWN`."

    "Otherwise, if the total count is at least 1, the ready count is less than
    the total count, and the number of days to release is fewer than 30, the
    posture is `AT_RISK`."

    Moving the clock to 26 days before release leaves one market plan of one
    not yet ready, so the title's posture is `AT_RISK`.

    Design: Difficulty/combinatorial_formula/submission_fee_discount_tier_keyed_on_pre_discount_subtotal
    """
    world = _market_at_lqa_with_one_key(api, "NOVA-11", "Nova Drift 11", "TEEN_12")
    first = fx.draft_submission(api, world["plan"]["id"], ["VIOLENCE_STYLIZED"], 0,
                               "TEEN_12")
    fx.send_back_for_edits(api, first["id"])
    fx.set_clock(api, "2026-11-05T00:00:00Z")

    fx.draft_submission(api, world["plan"]["id"], ["VIOLENCE_STYLIZED"], 0, "TEEN_12")

    superseded = fx.read_submission(api, first["id"])
    assert superseded["status"] == "WITHDRAWN"
    title = fx.read_title(api, world["title"]["id"])
    assert title["release_gate_state"] == "AT_RISK"
    assert title["market_plan_count"] == 1
    assert title["ready_market_count"] == 0
