"""Role-based access control: exclusive operations, cross-role refusals, the
three segregation-of-duties pairs and the entity-backed TalentAgent ownership."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def _jp_market_with_a_draft_contract(api):
    """A JP TEXT_ONLY market handed to the vendor, plus one unsigned contract.

    The plan carries the single MENU key, so its scope estimate is 0.10 effort
    units, and the talent contract is left in `DRAFT` for the agent to execute.
    """
    world = fx.build_market(api, title_code="NOVA-82", name="Nova Drift 82",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="ALL_AGES", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC],
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["talent"] = fx.create_talent(api, "Miki Sato", "JA", False, 240)
    world["contract"] = fx.draft_contract(
        api, world["talent"]["id"], world["title"]["id"], territory_scope=["JP"],
        media_scope="IN_GAME_AND_TRAILER", buyout_fee_cents=400000,
        per_line_rate_cents=200,
    )
    return world


def test_every_role_executes_an_operation_it_exclusively_owns(api):
    """One pass in which each of the six domain roles drives its own step.

    "A `TranslationVendor` is the external language service provider."

    "It writes target text into translation units, delivers them, and submits bug
    fixes."

    "An `LqaTester` runs linguistic and functional quality assurance."

    "A `RatingBoardLiaison` acts for the rating board itself."

    "Its only two write capabilities are picking a filed submission up for review
    and recording the board's decision."

    "To make it concrete: a `CERO` round-one filing made 122 days before release
    has a pre-discount subtotal of 480,000, no expedite fee, a five per cent tier,
    a discount of 24,000, and a fee of 456,000."

    Nothing in this test may return 401 or 403: every call is made by the one role
    the endpoint table names for it, and `VIOLENCE_STYLIZED` alone is 12 points,
    which lands in `ALL_AGES` under both variants.

    Design: Corner/rbac/each_of_the_seven_roles_can_perform_its_own_exclusive_operations
    """
    world = _jp_market_with_a_draft_contract(api)
    plan_id = world["plan"]["id"]
    unit = world["units"]["menu.start"]
    agent = users.make_talent_agent_headers(world["talent"]["id"])

    drafted = validate_success(api.write_translation_unit(
        unit["id"], f.translation_text_payload("ゲームを始める", 7, 96), users.VENDOR
    ))
    assert drafted["translation_status"] == "DRAFTED"
    delivered = validate_success(
        api.deliver_translation_unit(unit["id"], users.VENDOR)
    )
    assert delivered["translation_status"] == "DELIVERED"

    marked = validate_success(api.qa_mark_translation_unit(
        unit["id"], f.qa_mark_payload("PASSED"), users.LQA_VERIFIER
    ))
    assert marked["qa_status"] == "PASSED"

    in_lqa = validate_success(api.enter_lqa(plan_id, users.PRODUCER))
    assert in_lqa["status"] == "LQA"

    qa_pass = validate_success(
        api.create_qa_pass(f.qa_pass_payload(plan_id, "LINGUISTIC", 40),
                           users.LQA_OPENER),
        expected_status=201,
    )
    assert qa_pass["status"] == "OPEN"
    assert qa_pass["opened_by_user_id"] == users.LQA_OPENER_USER_ID

    signed = validate_success(
        api.sign_talent_contract(world["contract"]["id"], agent)
    )
    assert signed["status"] == "SIGNED"

    plan_seen_by_agent = validate_success(api.get_market_plan(plan_id, agent))
    submission = validate_success(
        api.create_rating_submission(
            f.rating_submission_payload(plan_id, plan_seen_by_agent["version"],
                                        ["VIOLENCE_STYLIZED"], 0, "ALL_AGES"),
            users.COMPLIANCE,
        ),
        expected_status=201,
    )
    filed = validate_success(
        api.submit_rating_submission(submission["id"], users.COMPLIANCE)
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["submitted_by_user_id"] == users.COMPLIANCE_USER_ID
    assert filed["self_assessed_risk_score"] == 12
    A.assert_money_cents(filed["fee_cents"], 456000, "fee_cents")

    reviewed = validate_success(api.begin_review(submission["id"], users.BOARD))
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["board_adjusted_risk_score"] == 12
    assert reviewed["projected_rating_band"] == "ALL_AGES"

    rated = validate_success(api.record_outcome(
        submission["id"], f.record_outcome_payload("RATE", "ALL_AGES"), users.BOARD
    ))
    assert rated["status"] == "RATED"
    assert rated["assigned_rating"] == "ALL_AGES"


def test_platform_admin_holds_another_roles_endpoint_and_the_clock_alone(api):
    """The admin registers a title and moves the clock; a producer may not.

    "A `PlatformAdmin` operates the publishing platform."

    "It is permitted on every endpoint in this specification, and it is the only
    role that may move the server's logical clock."

    "A `PlatformAdmin` moves it by supplying a `current_utc` instant; the response
    body for that operation is the inline object `{ current_utc: <datetime> }`
    rather than a domain resource."

    "Signature stamps `signed_at_utc` with the logical clock and opens the
    commitment ledger by setting `committed_fee_cents` to `buyout_fee_cents`,
    incrementing the contract's `version` by 1."

    The signature instant is the proof that the admin's clock write landed and the
    producer's refused one did not.

    Design: Corner/rbac/each_of_the_seven_roles_can_perform_its_own_exclusive_operations
    """
    title = validate_success(
        api.create_title(f.title_payload(title_code="NOVA-82B",
                                         name="Nova Drift 82 B"), users.ADMIN),
        expected_status=201,
    )
    talent = validate_success(
        api.create_voice_talent(
            f.voice_talent_payload("Miki Sato", "JA", False, 240), users.ADMIN
        ),
        expected_status=201,
    )
    contract = validate_success(
        api.create_talent_contract(
            f.talent_contract_payload(talent["id"], title["id"], talent["version"],
                                      territory_scope=["JP"]),
            users.ADMIN,
        ),
        expected_status=201,
    )
    assert contract["status"] == "DRAFT"

    moved = validate_success(api.set_clock("2026-08-02T00:00:00Z", users.ADMIN))
    A.assert_instant_equals(moved["current_utc"], "2026-08-02T00:00:00Z",
                            "current_utc")

    validate_error(api.set_clock("2027-01-01T00:00:00Z", users.PRODUCER),
                   E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    signed = validate_success(api.sign_talent_contract(
        contract["id"], users.make_talent_agent_headers(talent["id"])
    ))
    assert signed["status"] == "SIGNED"
    A.assert_instant_equals(signed["signed_at_utc"], "2026-08-02T00:00:00Z",
                            "signed_at_utc")
    A.assert_money_cents(signed["committed_fee_cents"], 500000,
                         "committed_fee_cents")


def test_every_one_of_the_seven_roles_may_call_the_read_endpoints(api):
    """Reads are shared: six opaque operators and the entity-backed agent all pass.

    "All seven roles may call every read endpoint."

    "The seven roles are `LocalizationProducer`, `TranslationVendor`, `LqaTester`,
    `ComplianceOfficer`, `RatingBoardLiaison`, `TalentAgent` and `PlatformAdmin`."

    "`TalentAgent` is the single exception and is entity-backed."

    Design: Corner/rbac/each_of_the_seven_roles_can_perform_its_own_exclusive_operations
    """
    title = fx.create_title(api, title_code="NOVA-82C", name="Nova Drift 82 C")
    talent = fx.create_talent(api, "Miki Sato", "JA", False, 240)

    assert len(C.ALL_ROLES) == 7
    for role, headers in users.HEADERS_BY_ROLE.items():
        seen = validate_success(api.get_title(title["id"], headers))
        assert seen["title_code"] == "NOVA-82C", role
        rows, meta = validate_paginated(api.list_titles(headers))
        assert meta["total_count"] == 1, role
        assert [row["id"] for row in rows] == [title["id"]], role

    agent = users.make_talent_agent_headers(talent["id"])
    seen_by_agent = validate_success(api.get_title(title["id"], agent))
    assert seen_by_agent["title_code"] == "NOVA-82C"
    talent_seen_by_agent = validate_success(
        api.get_voice_talent(talent["id"], agent)
    )
    assert talent_seen_by_agent["talent_name"] == "Miki Sato"
    _rows, meta = validate_paginated(api.list_voice_talents(agent))
    assert meta["total_count"] == 1


# Deliberately unresolvable identifiers: the role rung must answer before the
# path-existence rung ever runs.
_GHOST_UNIT = "00000000-0000-4000-8000-00000000ee01"
_GHOST_SUBMISSION = "00000000-0000-4000-8000-00000000ee03"
_GHOST_BUG = "00000000-0000-4000-8000-00000000ee04"


def _title_and_draft_plan(api):
    """One title and one `DRAFT` JP plan, so the refusals have a real neighbour."""
    title = fx.create_title(api, title_code="NOVA-83", name="Nova Drift 83")
    plan = fx.create_market_plan(api, title["id"], market_code="JP",
                                 scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                                 budget_cap_cents=5000000)
    return {"title": title, "plan": plan}


def test_eleven_cross_role_writes_are_all_refused_at_the_role_rung(api):
    """A forbidden role is refused even with a ghost path id and a thin body.

    "If the acting role is not among the roles listed for the target endpoint in
    §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    "When one request violates several rules at once, the server returns the error
    of the highest-precedence rule that is violated and does not evaluate any later
    rule."

    "The ladder is fixed and total; implementers must treat it as an ordered
    sequence, not as a set of independent checks."

    Role permission is the second rung, above request shape, path existence and
    body foreign keys, so neither the fabricated identifiers nor the invalid
    `blocked_reason` may surface instead of the 403.

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    world = _title_and_draft_plan(api)
    plan_id = world["plan"]["id"]

    validate_error(
        api.create_title(f.title_payload(title_code="NOVA-83X",
                                         name="Vendor attempt"), users.VENDOR),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.write_translation_unit(
            _GHOST_UNIT, f.translation_text_payload("x", 1, 50), users.LQA_OPENER
        ),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.deliver_translation_unit(_GHOST_UNIT, users.LQA_OPENER),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.create_qa_pass(f.qa_pass_payload(plan_id, "LINGUISTIC", 10),
                           users.COMPLIANCE),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.create_rating_submission(
            f.rating_submission_payload(plan_id, world["plan"]["version"],
                                        ["BLOOD"], 1, "TEEN_12"),
            users.PRODUCER,
        ),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.begin_review(_GHOST_SUBMISSION, users.COMPLIANCE),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.record_outcome(_GHOST_SUBMISSION,
                           f.record_outcome_payload("RATE", "TEEN_12"),
                           users.COMPLIANCE),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.mark_release_ready(plan_id, users.PRODUCER),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.block_market_plan(plan_id,
                              {"blocked_reason": "attempt by the wrong role"},
                              users.LQA_OPENER),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.create_content_edit(
            {"rating_submission_id": _GHOST_SUBMISSION, "edit_kind": "AGE_GATE",
             "rationale": "attempt by the wrong role"},
            users.LQA_OPENER,
        ),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.triage_lqa_bug(_GHOST_BUG, f.triage_payload("ACCEPT"), users.VENDOR),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )

    after = fx.read_plan(api, plan_id)
    assert after["status"] == "DRAFT"
    assert after["blocked_reason"] is None
    A.assert_unchanged_row(after, world["plan"], "market_plan")
    rows, meta = validate_paginated(api.list_titles(users.PRODUCER))
    assert meta["total_count"] == 1
    assert [row["title_code"] for row in rows] == ["NOVA-83"]
    _submissions, sub_meta = validate_paginated(
        api.list_rating_submissions(users.COMPLIANCE, {"market_plan_id": plan_id})
    )
    assert sub_meta["total_count"] == 0

    readable = validate_success(api.get_title(world["title"]["id"], users.VENDOR))
    assert readable["title_code"] == "NOVA-83"


def test_a_shared_operation_is_shared_only_with_the_roles_the_table_names(api):
    """Two roles hold content-edit creation and bug triage; the other five do not.

    "When a board comes back demanding changes, a `ComplianceOfficer` or a
    `LocalizationProducer` proposes a **Content Edit**."

    "Triage is a three-way fork out of `NEW`, driven by a `triage_action` supplied
    by an `LqaTester` or a `LocalizationProducer`."

    "If the acting role is not among the roles listed for the target endpoint in
    §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    world = fx.build_market_with_edits_required(
        api, title_code="NOVA-83B", name="Nova Drift 83 B", market_code="JP",
        key_specs=[f.MENU_KEY_SPEC], target_rating="MATURE_15",
        disclosed_content_codes=["VIOLENCE_REALISTIC", "BLOOD"],
        footage_asset_count=2,
    )
    submission_id = world["submission"]["id"]
    assert world["submission"]["status"] == "EDITS_REQUIRED"

    validate_error(
        api.create_content_edit(
            f.content_edit_payload(submission_id, edit_kind="AGE_GATE",
                                   rationale="Gate the opening act behind an age "
                                             "check."),
            users.LQA_OPENER,
        ),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.create_content_edit(
            f.content_edit_payload(submission_id, edit_kind="AGE_GATE",
                                   rationale="Gate the opening act behind an age "
                                             "check."),
            users.VENDOR,
        ),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    edit = validate_success(
        api.create_content_edit(
            f.content_edit_payload(submission_id, edit_kind="AGE_GATE",
                                   rationale="Gate the opening act behind an age "
                                             "check."),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    assert edit["status"] == "PROPOSED"

    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 100)
    bug = fx.log_bug(api, qa_pass["id"], bug_class="MISTRANSLATION", severity="S4",
                     summary="Imperative reads as a question")
    validate_error(
        api.triage_lqa_bug(bug["id"], f.triage_payload("ACCEPT"), users.VENDOR),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    unchanged = fx.read_bug(api, bug["id"])
    assert unchanged["status"] == "NEW"
    A.assert_unchanged_row(unchanged, bug, "lqa_bug")

    triaged = validate_success(
        api.triage_lqa_bug(bug["id"], f.triage_payload("ACCEPT"), users.PRODUCER)
    )
    assert triaged["status"] == "TRIAGED"


def test_an_unrecognised_or_missing_role_header_is_refused_before_the_role_rung(api):
    """Authentication answers first; only a recognised-but-wrong role gets 403.

    "Every request — without exception, including every read — must carry two
    headers."

    "If either header is absent, or if `X-User-Role` is not exactly one of the
    seven role names below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    "This check runs before anything else the server does."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    payload = f.title_payload(title_code="NOVA-83C", name="Nova Drift 83 C")

    validate_error(api.create_title(payload, users.HEADERS_UNKNOWN_ROLE),
                   E.ERR_UNAUTHENTICATED, expected_status=401)
    validate_error(api.create_title(payload, users.HEADERS_WITHOUT_ROLE),
                   E.ERR_UNAUTHENTICATED, expected_status=401)
    validate_error(api.create_title(payload, users.HEADERS_WITHOUT_USER_ID),
                   E.ERR_UNAUTHENTICATED, expected_status=401)
    validate_error(api.list_titles(users.HEADERS_UNKNOWN_ROLE),
                   E.ERR_UNAUTHENTICATED, expected_status=401)

    validate_error(api.create_title(payload, users.VENDOR),
                   E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    _rows, meta = validate_paginated(api.list_titles(users.PRODUCER))
    assert meta["total_count"] == 0
    created = validate_success(api.create_title(payload, users.PRODUCER),
                               expected_status=201)
    assert created["title_code"] == "NOVA-83C"


def test_a_role_refusal_leaves_the_logical_clock_where_it_was(api):
    """The refused clock write is inert: the next signature still reads startup.

    "It is permitted on every endpoint in this specification, and it is the only
    role that may move the server's logical clock."

    "The logical clock.** This system has no dependency on wall-clock time."

    "Signature stamps `signed_at_utc` with the logical clock and opens the
    commitment ledger by setting `committed_fee_cents` to `buyout_fee_cents`,
    incrementing the contract's `version` by 1."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    title = fx.create_title(api, title_code="NOVA-83D", name="Nova Drift 83 D")
    talent = fx.create_talent(api, "Miki Sato", "JA", False, 240)
    contract = fx.draft_contract(api, talent["id"], title["id"],
                                 territory_scope=["JP"], buyout_fee_cents=400000,
                                 per_line_rate_cents=200)

    validate_error(api.set_clock("2027-01-01T00:00:00Z", users.COMPLIANCE),
                   E.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    validate_error(api.set_clock("2027-01-01T00:00:00Z", users.LQA_OPENER),
                   E.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    validate_error(
        api.set_clock("2027-01-01T00:00:00Z",
                      users.make_talent_agent_headers(talent["id"])),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )

    signed = validate_success(api.sign_talent_contract(
        contract["id"], users.make_talent_agent_headers(talent["id"])
    ))
    A.assert_instant_equals(signed["signed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "signed_at_utc")


def _jp_market_in_lqa(api, title_code, name):
    """A JP TEXT_ONLY market whose single unit is delivered and the plan in `LQA`."""
    return fx.build_market(api, title_code=title_code, name=name, market_code="JP",
                           scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                           budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)


def test_the_user_who_opened_a_pass_may_not_close_it(api):
    """First declared pair: `opened_by_user_id` against the closer.

    "The user recorded in a QA pass's `opened_by_user_id` may not close that
    pass."

    "Any of these three collisions is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    "The user recorded in `opened_by_user_id` may not be the one closing, per
    §2.1."

    "On success `status` becomes `CLOSED`, `closed_at_utc` is stamped with the
    logical clock, `weighted_defect_points` and `defect_density` are frozen at the
    values that passed the gate, and the pass's `version` increments by 1."

    The pass carries no defects at all, so the density gate is satisfied both
    times and the identity of the caller is the only difference between the two
    requests.

    Design: Corner/rbac/segregation_of_duties_separates_all_three_declared_pairs
    """
    world = _jp_market_in_lqa(api, "NOVA-84", "Nova Drift 84")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 100,
                              users.LQA_OPENER)
    assert qa_pass["opened_by_user_id"] == users.LQA_OPENER_USER_ID
    A.assert_defect_density(qa_pass["defect_density"], 0.0000)

    validate_error(api.close_qa_pass(qa_pass["id"], users.LQA_OPENER),
                   E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    still_open = fx.read_qa_pass(api, qa_pass["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["closed_at_utc"] is None
    A.assert_unchanged_row(still_open, qa_pass, "qa_pass")

    closed = validate_success(api.close_qa_pass(qa_pass["id"], users.LQA_CLOSER))
    assert closed["status"] == "CLOSED"
    assert closed["weighted_defect_points"] == 0
    A.assert_defect_density(closed["defect_density"], 0.0000)
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")
    A.assert_version_bumped_by(closed, qa_pass, 1, "qa_pass")


def test_the_user_who_logged_a_defect_may_not_verify_its_fix(api):
    """Second declared pair: `logged_by_user_id` against the verifier.

    "The user recorded in a defect's `logged_by_user_id` may not verify that
    defect's fix."

    "An `LqaTester` verifies the fix, moving the defect `FIX_SUBMITTED →
    VERIFIED`."

    "The defect must be `FIX_SUBMITTED`, the owning pass must be `OPEN`, and the
    acting `X-User-ID` must differ from the defect's `logged_by_user_id`."

    "On success `verified_by_user_id` is set to the acting `X-User-ID`, the pass's
    `weighted_defect_points` and `defect_density` are recomputed and drop because
    the defect leaves the open set, the linked unit's `open_bug_count` is
    recomputed, and the defect's `version` increments by 1."

    Design: Corner/rbac/segregation_of_duties_separates_all_three_declared_pairs
    """
    world = _jp_market_in_lqa(api, "NOVA-84B", "Nova Drift 84 B")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 100,
                              users.LQA_OPENER)
    bug = fx.log_bug(api, qa_pass["id"], users.LQA_LOGGER,
                     bug_class="MISTRANSLATION", severity="S2",
                     summary="Honorific register wrong in the opening line.")
    assert bug["logged_by_user_id"] == users.LQA_LOGGER_USER_ID
    assert bug["severity_weight"] == 4
    fx.triage_bug(api, bug["id"], "ACCEPT")
    claimed = fx.submit_fix(api, bug["id"])
    assert claimed["status"] == "FIX_SUBMITTED"
    A.assert_defect_density(fx.read_qa_pass(api, qa_pass["id"])["defect_density"],
                            0.0400)

    validate_error(api.verify_lqa_bug(bug["id"], users.LQA_LOGGER),
                   E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    still_claimed = fx.read_bug(api, bug["id"])
    assert still_claimed["status"] == "FIX_SUBMITTED"
    assert still_claimed["verified_by_user_id"] is None
    A.assert_unchanged_row(still_claimed, claimed, "lqa_bug")

    verified = validate_success(api.verify_lqa_bug(bug["id"], users.LQA_VERIFIER))
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == users.LQA_VERIFIER_USER_ID
    A.assert_version_bumped_by(verified, claimed, 1, "lqa_bug")
    after = fx.read_qa_pass(api, qa_pass["id"])
    assert after["weighted_defect_points"] == 0
    A.assert_defect_density(after["defect_density"], 0.0000)


def test_the_user_who_filed_a_submission_may_neither_review_it_nor_rate_it(api):
    """Third declared pair, plus the review-entry separation from the other side.

    "The user recorded in a rating submission's `submitted_by_user_id` may not
    record that submission's outcome."

    "Note that the review-entry step imposes the same separation from a different
    direction: a submission may only be picked up for review by a user whose
    `X-User-ID` differs from the submission's `submitted_by_user_id`."

    "The user recorded in `submitted_by_user_id` may not record the outcome."

    The filer here borrows the `RatingBoardLiaison` role, so the role rung is
    satisfied and the identity collision is the only rule left to break.

    Design: Corner/rbac/segregation_of_duties_separates_all_three_declared_pairs
    """
    world = _jp_market_in_lqa(api, "NOVA-84C", "Nova Drift 84 C")
    draft = fx.draft_submission(api, world["plan"]["id"], ["VIOLENCE_STYLIZED"], 1,
                                "TEEN_12", headers=users.COMPLIANCE)
    filed = fx.submit_submission(api, draft["id"], users.COMPLIANCE)
    assert filed["submitted_by_user_id"] == users.COMPLIANCE_USER_ID
    filer_wearing_the_board_hat = users.make_headers(users.COMPLIANCE_USER_ID,
                                                     C.ROLE_RATING_BOARD_LIAISON)

    validate_error(api.begin_review(draft["id"], filer_wearing_the_board_hat),
                   E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    still_filed = fx.read_submission(api, draft["id"])
    assert still_filed["status"] == "SUBMITTED"
    assert still_filed["reviewed_by_user_id"] is None
    A.assert_unchanged_row(still_filed, filed, "rating_submission")

    reviewed = validate_success(api.begin_review(draft["id"], users.BOARD))
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == users.BOARD_USER_ID
    assert reviewed["projected_rating_band"] == "ALL_AGES"

    validate_error(
        api.record_outcome(draft["id"], f.record_outcome_payload("RATE", "ALL_AGES"),
                           filer_wearing_the_board_hat),
        E.ERR_SEGREGATION_OF_DUTIES, expected_status=403,
    )
    still_under_review = fx.read_submission(api, draft["id"])
    assert still_under_review["status"] == "UNDER_REVIEW"
    assert still_under_review["assigned_rating"] is None
    A.assert_unchanged_row(still_under_review, reviewed, "rating_submission")

    rated = validate_success(api.record_outcome(
        draft["id"], f.record_outcome_payload("RATE", "ALL_AGES"), users.BOARD
    ))
    assert rated["status"] == "RATED"
    assert rated["assigned_rating"] == "ALL_AGES"


def test_only_the_three_declared_pairs_are_split(api):
    """Logging then triaging, and logging then closing, are one identity's work.

    "Three duties are split and are enforced on `X-User-ID` regardless of role."

    "Triage is a three-way fork out of `NEW`, driven by a `triage_action` supplied
    by an `LqaTester` or a `LocalizationProducer`."

    "`ACCEPT` moves the defect `NEW → TRIAGED`."

    "The pass's `weighted_defect_points` and `defect_density` are recomputed, and
    the figures do not fall, because a triaged defect stays in the open set."

    The tester who logged and triaged the defect is not the pass opener, so the
    close is legitimate: one `S4` finding over 100 inspected units is one weighted
    point and a density of 0.0100, below the 0.0500 ceiling.

    Design: Corner/rbac/segregation_of_duties_separates_all_three_declared_pairs
    """
    world = _jp_market_in_lqa(api, "NOVA-84D", "Nova Drift 84 D")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 100,
                              users.LQA_OPENER)
    bug = fx.log_bug(api, qa_pass["id"], users.LQA_LOGGER,
                     bug_class="MISTRANSLATION", severity="S4",
                     summary="Imperative reads as a question")
    assert bug["logged_by_user_id"] == users.LQA_LOGGER_USER_ID

    triaged = validate_success(
        api.triage_lqa_bug(bug["id"], f.triage_payload("ACCEPT"), users.LQA_LOGGER)
    )
    assert triaged["status"] == "TRIAGED"
    A.assert_version_bumped_by(triaged, bug, 1, "lqa_bug")

    with_one_open_defect = fx.read_qa_pass(api, qa_pass["id"])
    assert with_one_open_defect["weighted_defect_points"] == 1
    A.assert_defect_density(with_one_open_defect["defect_density"], 0.0100)

    closed = validate_success(api.close_qa_pass(qa_pass["id"], users.LQA_LOGGER))
    assert closed["status"] == "CLOSED"
    assert closed["weighted_defect_points"] == 1
    A.assert_defect_density(closed["defect_density"], 0.0100)


def _two_talents_and_one_booking(api):
    """A JP FULL_VOICE market with Miki's session booked and Ji-hoon idle.

    Ji-hoon is a registered talent with no interest in this booking, so his agent
    is a legitimate caller whose `X-User-ID` simply does not match the session's
    `voice_talent_id`.
    """
    world = fx.build_market(api, title_code="NOVA-85", name="Nova Drift 85",
                            market_code="JP", scope_tier="FULL_VOICE",
                            target_rating="TEEN_12", budget_cap_cents=9000000,
                            required_voice_line_count=40,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="TOK-K",
                            turnaround_buffer_minutes=0, talent_name="Miki Sato",
                            talent_language_code="JA",
                            max_daily_recording_minutes=240,
                            buyout_fee_cents=400000, per_line_rate_cents=200,
                            media_scope="IN_GAME_AND_TRAILER",
                            territory_scope=["JP"],
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["other_talent"] = fx.create_talent(api, "Ji-hoon Park", "KO", True, 180)
    world["session"] = fx.book_session(
        api, world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc="2026-08-01T09:00:00Z",
        end_utc="2026-08-01T11:00:00Z", planned_line_count=60,
    )
    world["owner"] = users.make_talent_agent_headers(world["talent"]["id"])
    world["stranger"] = users.make_talent_agent_headers(world["other_talent"]["id"])
    return world


def test_a_foreign_agent_may_not_open_the_booth_door_of_another_talents_session(api):
    """The ownership rung compares the session's `voice_talent_id` to `X-User-ID`.

    "When `X-User-Role` is `TalentAgent`, `X-User-ID` is the `id` of the acting
    `VoiceTalent` row; ownership checks on any resource that references a
    `VoiceTalent` compare the resource's `voice_talent_id` field to `X-User-ID`."

    "Concretely, a `TalentAgent` may only sign a talent contract whose
    `voice_talent_id` equals its own `X-User-ID`, and may only start or complete a
    recording session whose `voice_talent_id` equals its own `X-User-ID`."

    "A mismatch on any of those three operations is rejected with
    `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    "Either the owning `TalentAgent` or a `LocalizationProducer` may do it."

    Every other precondition is already met when the stranger calls — the clock is
    on the booking, the contract is signed and the plan is in localization — so
    ownership is the only rule that can answer.

    Design: Corner/rbac/talent_agent_may_only_touch_its_own_sessions
    """
    world = _two_talents_and_one_booking(api)
    session = world["session"]
    assert session["status"] == "SCHEDULED"
    assert session["voice_talent_id"] == world["talent"]["id"]
    fx.set_clock(api, session["start_utc"])

    validate_error(api.start_voice_session(session["id"], world["stranger"]),
                   E.ERR_OWNERSHIP_VIOLATION, expected_status=403)

    untouched = fx.read_session(api, session["id"])
    assert untouched["status"] == "SCHEDULED"
    A.assert_unchanged_row(untouched, session, "voice_session")

    opened = validate_success(api.start_voice_session(session["id"], world["owner"]))
    assert opened["status"] == "IN_PROGRESS"
    A.assert_version_bumped_by(opened, session, 1, "voice_session")


def test_a_foreign_agent_may_not_record_the_line_count_of_another_talents_session(api):
    """The same comparison guards completion, and the owner's money lands.

    "The session must be `IN_PROGRESS`, else `ERR_SESSION_STATE_INVALID`."

    "Completion stores `recorded_line_count`, sets `line_fee_cents` to
    `recorded_line_count` multiplied by the contract's `per_line_rate_cents`,
    recomputes the contract's `committed_fee_cents`, recomputes the market plan's
    `voice_recorded_line_count` together with its `localization_cost_cents` and
    `overage_cents`, and increments the `version` of the session, the contract and
    the market plan by 1 each."

    "The buyout term is present from the moment the contract is `SIGNED` and is
    never reversed."

    Forty-five lines at 200 cents is a 9,000-cent line fee, so the ledger reads
    409,000; the text component is 0.10 effort units at 4,200 cents under the
    `FULL_VOICE` multiplier of 1.80, which is 756 cents, and the subtotal of 9,756
    is far below the 9,000,000-cent cap.

    Design: Corner/rbac/talent_agent_may_only_touch_its_own_sessions
    """
    world = _two_talents_and_one_booking(api)
    session = world["session"]
    fx.set_clock(api, session["start_utc"])
    opened = validate_success(api.start_voice_session(session["id"], world["owner"]))

    validate_error(
        api.complete_voice_session(session["id"], f.complete_session_payload(45),
                                   world["stranger"]),
        E.ERR_OWNERSHIP_VIOLATION, expected_status=403,
    )
    still_open = fx.read_session(api, session["id"])
    assert still_open["status"] == "IN_PROGRESS"
    assert still_open["recorded_line_count"] is None
    A.assert_unchanged_row(still_open, opened, "voice_session")

    recorded = validate_success(api.complete_voice_session(
        session["id"], f.complete_session_payload(45), world["owner"]
    ))
    assert recorded["status"] == "RECORDED"
    assert recorded["recorded_line_count"] == 45
    A.assert_money_cents(recorded["line_fee_cents"], 9000, "line_fee_cents")

    contract = fx.read_contract(api, world["contract"]["id"])
    A.assert_money_cents(contract["committed_fee_cents"], 409000,
                         "committed_fee_cents")
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["voice_recorded_line_count"] == 45
    A.assert_money_cents(plan["localization_cost_cents"], 9756,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")


def test_even_the_owning_agent_is_refused_the_cancel_endpoint_at_the_role_rung(api):
    """Cancellation is not on the agent's table at all, so rung 2 answers first.

    "A `LocalizationProducer` may cancel a session in `SCHEDULED`, `IN_PROGRESS`
    or `RECORDED`; an already-`CANCELLED` session refuses with
    `ERR_SESSION_STATE_INVALID`, and cancellation is forbidden once the owning
    market plan has reached `RELEASE_READY`."

    "If the acting role is not among the roles listed for the target endpoint in
    §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    "Cancelling a session that was only `SCHEDULED` — whether by direct request or
    as a cascade from a market block or a contract termination — sets `status` to
    `CANCELLED`, recomputes the booth's `reserved_minutes_total` and the talent's
    reserved minutes for the clock date, leaves `committed_fee_cents` unchanged
    because a scheduled session contributed no line fee, and increments the
    session's `version` by 1."

    The caller owns the session, so ownership at rung 7 would have passed; the
    refusal proves the role rung is evaluated first. The booth's 120 reserved
    minutes are the two booked hours with a zero-minute buffer.

    Design: Corner/rbac/talent_agent_may_only_touch_its_own_sessions
    """
    world = _two_talents_and_one_booking(api)
    session = world["session"]
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 120

    validate_error(api.cancel_voice_session(session["id"], world["owner"]),
                   E.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    validate_error(api.cancel_voice_session(session["id"], world["stranger"]),
                   E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    unchanged = fx.read_session(api, session["id"])
    assert unchanged["status"] == "SCHEDULED"
    A.assert_unchanged_row(unchanged, session, "voice_session")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 120

    cancelled = validate_success(
        api.cancel_voice_session(session["id"], users.PRODUCER)
    )
    assert cancelled["status"] == "CANCELLED"
    A.assert_money_cents(cancelled["line_fee_cents"], 0, "line_fee_cents")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 0
    A.assert_money_cents(
        fx.read_contract(api, world["contract"]["id"])["committed_fee_cents"],
        400000, "committed_fee_cents",
    )


def test_a_foreign_agent_may_not_sign_another_talents_contract(api):
    """The third ownership-guarded operation, on the junction row itself.

    "Concretely, a `TalentAgent` may only sign a talent contract whose
    `voice_talent_id` equals its own `X-User-ID`, and may only start or complete a
    recording session whose `voice_talent_id` equals its own `X-User-ID`."

    "A `TalentAgent` may sign only its own contract, per the ownership rule of
    §2.1; a `LocalizationProducer` may also sign."

    "A new contract opens in `status` `DRAFT` with `signed_at_utc` null and
    `committed_fee_cents` 0, and it increments the talent's `version`."

    Design: Corner/rbac/talent_agent_may_only_touch_its_own_sessions
    """
    world = _two_talents_and_one_booking(api)
    other = world["other_talent"]
    draft = fx.draft_contract(api, other["id"], world["title"]["id"],
                              territory_scope=["JP"],
                              media_scope="IN_GAME_ONLY",
                              buyout_fee_cents=300000, per_line_rate_cents=150)
    assert draft["status"] == "DRAFT"
    assert draft["signed_at_utc"] is None
    A.assert_money_cents(draft["committed_fee_cents"], 0, "committed_fee_cents")

    validate_error(api.sign_talent_contract(draft["id"], world["owner"]),
                   E.ERR_OWNERSHIP_VIOLATION, expected_status=403)

    still_draft = fx.read_contract(api, draft["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["signed_at_utc"] is None
    A.assert_unchanged_row(still_draft, draft, "talent_contract")

    signed = validate_success(
        api.sign_talent_contract(draft["id"], world["stranger"])
    )
    assert signed["status"] == "SIGNED"
    A.assert_money_cents(signed["committed_fee_cents"], 300000,
                         "committed_fee_cents")
    A.assert_instant_equals(signed["signed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "signed_at_utc")
