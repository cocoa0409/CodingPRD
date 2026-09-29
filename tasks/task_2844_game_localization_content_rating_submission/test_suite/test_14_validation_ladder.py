"""Individual rungs of the §2.5 rejection ladder, each read in isolation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# Four well-formed UUIDs that resolve to nothing at all, so that a session
# booking reaches the body foreign-key rung with every lookup failing.
_ABSENT_MARKET_PLAN_ID = "11111111-1111-4111-8111-111111111111"
_ABSENT_TALENT_ID = "22222222-2222-4222-8222-222222222222"
_ABSENT_BOOTH_ID = "33333333-3333-4333-8333-333333333333"
_ABSENT_CONTRACT_ID = "44444444-4444-4444-8444-444444444444"


def _assert_error_envelope_meta(response):
    """The two meta fields §2.2 requires on an error envelope."""
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id"
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    A.assert_three_fractional_digits(meta["api_request_timestamp"],
                                     "meta.api_request_timestamp")


def test_a_read_missing_either_identity_header_is_unauthenticated(api):
    """Both header omissions are 401, on a read that would otherwise succeed.

    "Every request — without exception, including every read — must carry two
    headers."

    "If either header is absent, or if `X-User-Role` is not exactly one of the
    seven role names below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/validations/missing_x_user_header_and_unknown_role_both_return_unauthenticated
    """
    title = fx.create_title(api, title_code="NOVA-61", name="Nova Drift 61")

    no_role = api.get_title(title["id"], users.HEADERS_WITHOUT_ROLE)
    no_user = api.get_title(title["id"], users.HEADERS_WITHOUT_USER_ID)

    validate_error(no_role, E.ERR_UNAUTHENTICATED, expected_status=401)
    validate_error(no_user, E.ERR_UNAUTHENTICATED, expected_status=401)
    _assert_error_envelope_meta(no_role)
    _assert_error_envelope_meta(no_user)
    with_both = validate_success(api.get_title(title["id"], users.PRODUCER))
    assert with_both["id"] == title["id"]


def test_an_unrecognised_role_fails_authentication_rather_than_permission(api):
    """A role outside the seven is a 401, not the 403 it superficially resembles.

    "The seven roles are `LocalizationProducer`, `TranslationVendor`,
    `LqaTester`, `ComplianceOfficer`, `RatingBoardLiaison`, `TalentAgent` and
    `PlatformAdmin`."

    "This check runs before anything else the server does."

    "All seven roles may call every read endpoint."

    `LocalisationProducer` is a plausible misspelling of a role that is allowed
    on this read, so nothing but the exact-match rule can decide the answer.

    Design: Corner/validations/missing_x_user_header_and_unknown_role_both_return_unauthenticated
    """
    title = fx.create_title(api, title_code="NOVA-61", name="Nova Drift 61")

    response = api.get_title(title["id"], users.HEADERS_UNKNOWN_ROLE)

    validate_error(response, E.ERR_UNAUTHENTICATED, expected_status=401)
    assert response.status_code != 403
    _assert_error_envelope_meta(response)


def test_the_first_declared_body_foreign_key_decides_the_not_found(api):
    """Four unresolvable body references report the earliest declared field.

    "Foreign keys supplied inside a request body are resolved with the same
    error vocabulary, and they are resolved in the order the fields are declared
    on the target entity."

    "Booking a recording session therefore resolves `market_plan_id` first, then
    `voice_talent_id`, then `recording_booth_id`, then `talent_contract_id` — so
    a request that names two nonexistent rows reports the earlier one."

    Design: Corner/validations/fk_field_order_decides_which_not_found_error_wins
    """
    response = api.create_voice_session(
        f.voice_session_payload(_ABSENT_MARKET_PLAN_ID, _ABSENT_TALENT_ID,
                                _ABSENT_BOOTH_ID, _ABSENT_CONTRACT_ID,
                                start_utc="2026-09-10T09:00:00Z",
                                end_utc="2026-09-10T11:00:00Z",
                                planned_line_count=60),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_MARKET_PLAN_NOT_FOUND, expected_status=404)
    _rows, meta = validate_paginated(api.list_voice_sessions(users.PRODUCER))
    assert meta["total_count"] == 0


def test_the_role_rung_outranks_the_request_shape_rung(api):
    """A forbidden caller learns nothing about the fields the endpoint wants.

    "When one request violates several rules at once, the server returns the
    error of the highest-precedence rule that is violated and does not evaluate
    any later rule."

    "If the acting role is not among the roles listed for the target endpoint in
    §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    "**Request shape** — every required field present, every enum value inside
    its declared set, every integer non-negative where declared, every datetime a
    valid RFC 3339 UTC instant, every array actually an array; else
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/role_check_at_priority_20_beats_the_invalid_payload_at_25
    """
    response = api.create_title({"title_code": "NOVA-62"}, users.LQA_OPENER)

    validate_error(response, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    _rows, meta = validate_paginated(api.list_titles(users.PRODUCER))
    assert meta["total_count"] == 0


def test_the_shape_rung_reports_itself_for_a_permitted_role(api):
    """The same payload really was defective, which the producer's 400 proves.

    "The registration payload carries a `title_code` — a publisher-facing short
    code that must match the pattern of three to sixteen characters drawn only
    from uppercase letters, digits and the hyphen, and must be unique across
    every title — together with a human-readable `name` of one to one hundred and
    twenty characters, the `source_language` the strings are authored in (either
    `EN` or `JA`, defaulting to `EN`), a `target_release_utc` contractual ship
    instant, and a `release_mode` of either `SIMULTANEOUS` or `STAGGERED`,
    defaulting to `SIMULTANEOUS`."

    Design: Corner/validations/role_check_at_priority_20_beats_the_invalid_payload_at_25
    """
    response = api.create_title({"title_code": "NOVA-62"}, users.PRODUCER)

    validate_error(response, E.ERR_INVALID_REQUEST, expected_status=400)
    _rows, meta = validate_paginated(api.list_titles(users.PRODUCER))
    assert meta["total_count"] == 0


def _two_titles_needing_a_japanese_plan(api):
    """Two independent titles, each about to receive a `JP` market plan."""
    return (
        fx.create_title(api, title_code="NOVA-63", name="Nova Drift 63"),
        fx.create_title(api, title_code="NOVA-64", name="Nova Drift 64"),
    )


def test_a_second_japanese_plan_on_one_title_collides(api):
    """The market code is claimed once per title.

    "A market plan's `market_code` is unique within its `title_id`; a collision
    is `ERR_DUPLICATE_MARKET_CODE`."

    "**Uniqueness** — else the matching 409 from §2.7."

    "`market_plan_count` is the number of market plans of the title with no
    status filter at all."

    Design: Corner/validations/duplicate_market_code_on_the_same_title_is_rejected
    """
    title_a, _title_b = _two_titles_needing_a_japanese_plan(api)
    first = fx.create_market_plan(api, title_a["id"], market_code="JP")
    assert first["market_code"] == "JP"
    assert first["rating_board"] == "CERO"

    response = api.create_market_plan(
        f.market_plan_payload(title_a["id"], market_code="JP",
                              scope_tier="SUBTITLED", target_rating="MATURE_15",
                              budget_cap_cents=7000000),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_DUPLICATE_MARKET_CODE, expected_status=409)
    assert fx.read_title(api, title_a["id"])["market_plan_count"] == 1


def test_the_same_market_code_is_free_on_another_title(api):
    """Uniqueness is scoped to the title, not to the platform.

    "A market plan's `market_code` is unique within its `title_id`; a collision
    is `ERR_DUPLICATE_MARKET_CODE`."

    "A new market plan opens in `status` `DRAFT` with `blocked_reason` null,
    `text_effort_units` 0, `text_effort_variant` null, `localization_cost_cents` 0
    and `overage_cents` 0, and it increments the title's `market_plan_count`."

    Design: Corner/validations/duplicate_market_code_on_the_same_title_is_rejected
    """
    title_a, title_b = _two_titles_needing_a_japanese_plan(api)
    fx.create_market_plan(api, title_a["id"], market_code="JP")
    validate_error(
        api.create_market_plan(f.market_plan_payload(title_a["id"], market_code="JP"),
                               users.PRODUCER),
        E.ERR_DUPLICATE_MARKET_CODE,
    )

    twin = validate_success(
        api.create_market_plan(f.market_plan_payload(title_b["id"], market_code="JP"),
                               users.PRODUCER),
        expected_status=201,
    )

    A.assert_new_market_plan(twin)
    assert twin["title_id"] == title_b["id"]
    assert twin["market_code"] == "JP"
    assert fx.read_title(api, title_a["id"])["market_plan_count"] == 1
    assert fx.read_title(api, title_b["id"])["market_plan_count"] == 1


def _market_at_lqa_for_qa_passes(api):
    return fx.build_market(api, title_code="NOVA-65", name="Nova Drift 65",
                           market_code="JP", scope_tier="TEXT_ONLY",
                           target_rating="TEEN_12", budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)


def test_a_second_open_pass_of_the_same_type_is_refused(api):
    """One OPEN pass per type, while the other type stays available.

    "And a market plan may hold at most one `OPEN` QA pass per `pass_type`;
    attempting to open a second is `ERR_OPEN_QA_PASS_EXISTS`."

    "The server assigns `pass_index` as one more than the number of pre-existing
    passes with the same `market_plan_id` and `pass_type`, so the first
    linguistic pass over a market is index 1 and its successor is index 2."

    A second tester is refused just as the opener would be, because the rule is
    scoped to the plan and the type; a `FUNCTIONAL` pass opens regardless.

    Design: Corner/validations/a_second_open_pass_of_the_same_type_is_refused_until_the_first_closes
    """
    world = _market_at_lqa_for_qa_passes(api)
    plan_id = world["plan"]["id"]
    first = fx.open_qa_pass(api, plan_id, "LINGUISTIC", 50)
    A.assert_new_qa_pass(first, users.LQA_OPENER["X-User-ID"])
    assert first["pass_index"] == 1

    response = api.create_qa_pass(f.qa_pass_payload(plan_id, "LINGUISTIC", 60),
                                  users.LQA_LOGGER)

    validate_error(response, E.ERR_OPEN_QA_PASS_EXISTS, expected_status=409)
    other_axis = validate_success(
        api.create_qa_pass(f.qa_pass_payload(plan_id, "FUNCTIONAL", 60),
                           users.LQA_LOGGER),
        expected_status=201,
    )
    assert other_axis["pass_type"] == "FUNCTIONAL"
    assert other_axis["pass_index"] == 1
    _rows, meta = validate_paginated(
        api.list_qa_passes(users.LQA_OPENER, {"market_plan_id": plan_id})
    )
    assert meta["total_count"] == 2


def test_closing_the_first_pass_reopens_the_slot_at_index_two(api):
    """The refused create succeeds verbatim once the first pass is CLOSED.

    "A new pass opens in `status` `OPEN` with `opened_by_user_id` set to the
    acting `X-User-ID`, `reopen_count` 0, `weighted_defect_points` 0,
    `defect_density` 0.0000 and `closed_at_utc` null."

    "The server assigns `pass_index` as one more than the number of pre-existing
    passes with the same `market_plan_id` and `pass_type`, so the first
    linguistic pass over a market is index 1 and its successor is index 2."

    Design: Corner/validations/a_second_open_pass_of_the_same_type_is_refused_until_the_first_closes
    """
    world = _market_at_lqa_for_qa_passes(api)
    plan_id = world["plan"]["id"]
    first = fx.open_qa_pass(api, plan_id, "LINGUISTIC", 50)
    successor = f.qa_pass_payload(plan_id, "LINGUISTIC", 60)
    validate_error(api.create_qa_pass(successor, users.LQA_LOGGER),
                   E.ERR_OPEN_QA_PASS_EXISTS)
    closed = fx.close_qa_pass(api, first["id"])
    assert closed["status"] == "CLOSED"

    second = validate_success(api.create_qa_pass(successor, users.LQA_LOGGER),
                              expected_status=201)

    A.assert_new_qa_pass(second, users.LQA_LOGGER["X-User-ID"])
    assert second["pass_index"] == 2
    assert second["pass_type"] == "LINGUISTIC"
    assert second["inspected_unit_count"] == 60
    assert fx.read_qa_pass(api, first["id"])["status"] == "CLOSED"


# The questionnaire a JP package files: JP mandates no descriptor and restricts
# none, so nothing but the plan's own state can decide these creates.
_JP_DISCLOSURE = ["VIOLENCE_STYLIZED"]


def _delivered_market_not_yet_in_lqa(api):
    """Every unit delivered, but the plan deliberately left in IN_LOCALIZATION."""
    world = fx.build_market(api, title_code="NOVA-66", name="Nova Drift 66",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC],
                            stage=fx.STAGE_DELIVERED)
    world["plan"] = fx.read_plan(api, world["plan"]["id"])
    assert world["plan"]["status"] == "IN_LOCALIZATION"
    assert world["plan"]["delivered_unit_count"] == 1
    return world


def test_a_submission_cannot_be_drafted_before_the_plan_enters_lqa(api):
    """Delivery is not enough; the plan itself must have reached LQA.

    "The market plan must be in `LQA` or `RELEASE_READY`, else
    `ERR_PREREQUISITE_STATE_NOT_MET`."

    "Filing a new rating submission requires the non-optional field
    `expected_market_plan_version`, carrying the client's last observed `version`
    of the target `MarketPlan`."

    The concurrency guard carries the plan's current version, so rung 9 is
    satisfied and the refusal can only come from the cross-entity state rung.

    Design: Corner/validations/rating_submission_requires_the_market_plan_to_have_reached_lqa
    """
    world = _delivered_market_not_yet_in_lqa(api)
    plan = world["plan"]

    response = api.create_rating_submission(
        f.rating_submission_payload(plan["id"], plan["version"], _JP_DISCLOSURE,
                                    footage_asset_count=1, target_rating="TEEN_12"),
        users.COMPLIANCE,
    )

    validate_error(response, E.ERR_PREREQUISITE_STATE_NOT_MET, expected_status=409)
    A.assert_unchanged_row(fx.read_plan(api, plan["id"]), plan, "market_plan")
    _rows, meta = validate_paginated(
        api.list_rating_submissions(users.COMPLIANCE,
                                    {"market_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0


def test_the_identical_package_is_accepted_once_the_plan_is_in_lqa(api):
    """The same body succeeds the moment the state precondition holds.

    "The server assigns `submission_round` as one more than the number of
    pre-existing submissions for that `market_plan_id`, so the first filing is
    round 1."

    "A new submission opens in `status` `DRAFT` with `assigned_rating`,
    `self_assessed_risk_score`, `board_adjusted_risk_score`,
    `projected_rating_band`, `submitted_by_user_id`, `reviewed_by_user_id` and
    `submitted_at_utc` all null, `fee_cents` 0 and `appeal_count` 0, and the
    create increments the market plan's `version`."

    Design: Corner/validations/rating_submission_requires_the_market_plan_to_have_reached_lqa
    """
    world = _delivered_market_not_yet_in_lqa(api)
    stale_plan = world["plan"]
    validate_error(
        api.create_rating_submission(
            f.rating_submission_payload(stale_plan["id"], stale_plan["version"],
                                        _JP_DISCLOSURE, 1, "TEEN_12"),
            users.COMPLIANCE,
        ),
        E.ERR_PREREQUISITE_STATE_NOT_MET,
    )
    at_lqa = fx.enter_lqa(api, stale_plan["id"])
    assert at_lqa["status"] == "LQA"

    submission = validate_success(
        api.create_rating_submission(
            f.rating_submission_payload(at_lqa["id"], at_lqa["version"],
                                        _JP_DISCLOSURE, 1, "TEEN_12"),
            users.COMPLIANCE,
        ),
        expected_status=201,
    )

    A.assert_new_submission(submission)
    assert submission["submission_round"] == 1
    assert submission["market_plan_id"] == at_lqa["id"]
    assert submission["rating_board"] == "CERO"
    A.assert_version_bumped_by(fx.read_plan(api, at_lqa["id"]), at_lqa, 1,
                               "market_plan")


def test_a_stale_version_outranks_the_missing_lqa_state(api):
    """Rung 9 answers first even though the state rung is also violated.

    "If that value does not equal the market plan's current `version`, the create
    is rejected with `ERR_STALE_MARKET_PLAN_VERSION` (HTTP 412)."

    "When one request violates several rules at once, the server returns the
    error of the highest-precedence rule that is violated and does not evaluate
    any later rule."

    Design: Corner/validations/rating_submission_requires_the_market_plan_to_have_reached_lqa
    """
    world = _delivered_market_not_yet_in_lqa(api)
    plan = world["plan"]

    response = api.create_rating_submission(
        f.rating_submission_payload(plan["id"], plan["version"] - 1,
                                    _JP_DISCLOSURE, 1, "TEEN_12"),
        users.COMPLIANCE,
    )

    validate_error(response, E.ERR_STALE_MARKET_PLAN_VERSION, expected_status=412)
    after = fx.read_plan(api, plan["id"])
    assert after["status"] == "IN_LOCALIZATION"
    A.assert_unchanged_row(after, plan, "market_plan")
    _rows, meta = validate_paginated(
        api.list_rating_submissions(users.COMPLIANCE,
                                    {"market_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0


# The contract's rights run out on 2026-09-01, and the booking it is asked to
# authorise sits comfortably inside that window — only the clock decides.
_RIGHTS_END_UTC = "2026-09-01T00:00:00Z"
_AFTER_RIGHTS_END_UTC = "2026-09-02T00:00:00Z"
_IN_WINDOW_SESSION = ("2026-08-15T09:00:00Z", "2026-08-15T11:00:00Z")
_SECOND_IN_WINDOW_SESSION = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")


def _voiced_market_with_a_short_dated_contract(api):
    """A JP FULL_VOICE plan in localization whose only contract lapses 2026-09-01.

    ``build_market`` cannot express the shortened rights window, so the title,
    the studio capacity and the contract are assembled here directly and the plan
    is walked to ``IN_LOCALIZATION`` afterwards.
    """
    title = fx.create_title(api, title_code="NOVA-67", name="Nova Drift 67")
    keys = {"menu.start": fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC)}
    plan = fx.create_market_plan(api, title["id"], market_code="JP",
                                 scope_tier="FULL_VOICE", target_rating="TEEN_12",
                                 budget_cap_cents=9000000,
                                 required_voice_line_count=60)
    booth = fx.create_booth(api, "TOK-G", "Tokyo", 30)
    talent = fx.create_talent(api, "Miki Sato", "JA", False, 240)
    contract = fx.signed_contract(api, talent["id"], title["id"],
                                  territory_scope=["JP"],
                                  media_scope="IN_GAME_AND_TRAILER",
                                  buyout_fee_cents=400000, per_line_rate_cents=200,
                                  rights_end_utc=_RIGHTS_END_UTC)
    assert contract["status"] == "SIGNED"
    A.assert_money_cents(contract["committed_fee_cents"], 400000,
                         "committed_fee_cents")
    fx.lock_strings(api, title["id"])
    fx.scope_plan(api, plan["id"])
    plan = fx.start_localization(api, plan["id"])
    assert plan["status"] == "IN_LOCALIZATION"
    return {"title": title, "keys": keys, "plan": plan, "booth": booth,
            "talent": talent, "contract": contract}


def _booking(world, window):
    return f.voice_session_payload(world["plan"]["id"], world["talent"]["id"],
                                  world["booth"]["id"], world["contract"]["id"],
                                  start_utc=window[0], end_utc=window[1],
                                  planned_line_count=60)


def test_a_lapsed_contract_expires_on_the_booking_that_reads_it(api):
    """The booking that touches the contract is the event that expires it.

    "Contracts expire lazily rather than on a timer."

    "Whenever a session booking or a session start reads a contract that is
    `SIGNED` and the logical clock has reached or passed its `rights_end_utc`, the
    server first moves that contract `SIGNED → EXPIRED` and increments its
    `version`; the referencing request is then evaluated against the new state and
    consequently fails because the contract is no longer `SIGNED`."

    "First the cross-entity state preconditions: the contract must be `SIGNED`
    (after the lazy expiry evaluation) and the market plan must be
    `IN_LOCALIZATION`, else `ERR_PREREQUISITE_STATE_NOT_MET`."

    The requested window lies inside the rights window, so the rights-window rung
    is satisfied and only the lazy transition can explain the refusal.

    Design: Corner/validations/signed_contract_expires_lazily_when_the_clock_passes_its_rights_end
    """
    world = _voiced_market_with_a_short_dated_contract(api)
    signed = world["contract"]
    fx.set_clock(api, _AFTER_RIGHTS_END_UTC)
    assert fx.read_contract(api, signed["id"])["status"] == "SIGNED"

    response = api.create_voice_session(_booking(world, _IN_WINDOW_SESSION),
                                        users.PRODUCER)

    validate_error(response, E.ERR_PREREQUISITE_STATE_NOT_MET, expected_status=409)
    expired = fx.read_contract(api, signed["id"])
    assert expired["status"] == "EXPIRED"
    A.assert_version_bumped_by(expired, signed, 1, "talent_contract")
    A.assert_money_cents(expired["committed_fee_cents"], 400000,
                         "committed_fee_cents")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 0
    _rows, meta = validate_paginated(api.list_voice_sessions(users.PRODUCER))
    assert meta["total_count"] == 0


def test_the_same_booking_succeeds_before_the_clock_passes_the_rights_end(api):
    """Only the clock's position separates the accepted booking from the refused one.

    "The lazy evaluation always runs before the referencing request's own
    preconditions."

    "A successful booking derives `duration_minutes` as the whole minutes between
    `start_utc` and `end_utc`, derives `occupied_end_utc`, opens the session in
    `status` `SCHEDULED` with `recorded_line_count` null and `line_fee_cents` 0,
    and increases the booth's `reserved_minutes_total` by the session's duration
    plus the booth buffer."

    The 2026-08-15 booking is taken while the clock still sits at startup; the
    2026-08-20 booking, identical but for its date, is refused once the clock
    stands beyond the rights end, and the contract expires exactly once.

    Design: Corner/validations/signed_contract_expires_lazily_when_the_clock_passes_its_rights_end
    """
    world = _voiced_market_with_a_short_dated_contract(api)
    booked = validate_success(
        api.create_voice_session(_booking(world, _IN_WINDOW_SESSION), users.PRODUCER),
        expected_status=201,
    )
    assert booked["status"] == "SCHEDULED"
    assert booked["duration_minutes"] == 120
    assert fx.read_contract(api, world["contract"]["id"])["status"] == "SIGNED"
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 150

    fx.set_clock(api, _AFTER_RIGHTS_END_UTC)
    refused = api.create_voice_session(_booking(world, _SECOND_IN_WINDOW_SESSION),
                                       users.PRODUCER)

    validate_error(refused, E.ERR_PREREQUISITE_STATE_NOT_MET, expected_status=409)
    expired = fx.read_contract(api, world["contract"]["id"])
    assert expired["status"] == "EXPIRED"
    A.assert_version_bumped_by(expired, world["contract"], 1, "talent_contract")
    again = api.create_voice_session(_booking(world, _SECOND_IN_WINDOW_SESSION),
                                     users.PRODUCER)
    validate_error(again, E.ERR_PREREQUISITE_STATE_NOT_MET, expected_status=409)
    A.assert_unchanged_row(fx.read_contract(api, world["contract"]["id"]), expired,
                           "talent_contract")
    assert fx.read_session(api, booked["id"])["status"] == "SCHEDULED"
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 150
