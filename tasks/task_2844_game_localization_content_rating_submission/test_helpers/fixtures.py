"""Composite state builders and pytest fixtures.

The harness restarts the server before every individual test, so every test
starts against an empty database. Nothing here assumes pre-existing rows: each
builder drives the public workflow endpoints from scratch, in the order the
specification requires, and returns the rows it created.

Builders are plain functions taking the client first, so a test can vary one
knob (a scope tier, a buffer, a disclosure set) without restating a chain of
twenty calls. The pytest fixtures at the bottom are the common shapes.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .api_client import ApiClient
from .constants import CLOCK_STARTUP_UTC, MARKET_BOARD

# ─── Single-step helpers ───────────────────────────────────────────────


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the server's logical clock; only a PlatformAdmin may do it."""
    return get_success_data(api.set_clock(current_utc, users.ADMIN))


def create_title(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_title(f.title_payload(**overrides), users.PRODUCER)
    )


def create_string_key(api: ApiClient, title_id: str, **spec) -> Dict[str, Any]:
    return get_success_data(
        api.create_string_key(f.string_key_payload(title_id, **spec), users.PRODUCER)
    )


def create_canonical_keys(api: ApiClient, title_id: str) -> Dict[str, Dict[str, Any]]:
    """Extract the canonical four source strings, in order."""
    keys: Dict[str, Dict[str, Any]] = {}
    for spec in f.CANONICAL_KEY_SPECS:
        key = create_string_key(api, title_id, **spec)
        keys[key["key_name"]] = key
    return keys


def lock_strings(api: ApiClient, title_id: str) -> Dict[str, Any]:
    return get_success_data(api.lock_strings(title_id, users.PRODUCER))


def create_market_plan(api: ApiClient, title_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_market_plan(f.market_plan_payload(title_id, **kwargs), users.PRODUCER)
    )


def scope_plan(api: ApiClient, market_plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.scope_market_plan(market_plan_id, users.PRODUCER))


def start_localization(api: ApiClient, market_plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.start_localization(market_plan_id, users.PRODUCER))


def enter_lqa(api: ApiClient, market_plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.enter_lqa(market_plan_id, users.PRODUCER))


def read_plan(api: ApiClient, market_plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_market_plan(market_plan_id, users.PRODUCER))


def read_title(api: ApiClient, title_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_title(title_id, users.PRODUCER))


def read_unit(api: ApiClient, translation_unit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_translation_unit(translation_unit_id, users.VENDOR))


def read_booth(api: ApiClient, recording_booth_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_booth(recording_booth_id, users.PRODUCER))


def read_talent(api: ApiClient, voice_talent_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_voice_talent(voice_talent_id, users.PRODUCER))


def read_contract(api: ApiClient, talent_contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_talent_contract(talent_contract_id, users.PRODUCER)
    )


def read_session(api: ApiClient, voice_session_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_voice_session(voice_session_id, users.PRODUCER))


def read_qa_pass(api: ApiClient, qa_pass_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_qa_pass(qa_pass_id, users.LQA_OPENER))


def read_bug(api: ApiClient, lqa_bug_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lqa_bug(lqa_bug_id, users.LQA_OPENER))


def read_submission(api: ApiClient, rating_submission_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_rating_submission(rating_submission_id, users.COMPLIANCE)
    )


def read_content_edit(api: ApiClient, content_edit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_content_edit(content_edit_id, users.COMPLIANCE))


def list_units(api: ApiClient, market_plan_id: str) -> List[Dict[str, Any]]:
    """Listing is the only discovery channel for cascade-created units."""
    body = api.list_translation_units(
        users.VENDOR, {"market_plan_id": market_plan_id, "limit": 100}
    )
    return get_success_data(body)


def units_by_key_name(api: ApiClient, market_plan_id: str,
                      keys: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index a plan's units by the ``key_name`` of the string key they point at."""
    by_key_id = {key["id"]: name for name, key in keys.items()}
    units: Dict[str, Dict[str, Any]] = {}
    for unit in list_units(api, market_plan_id):
        name = by_key_id.get(unit["string_key_id"])
        if name is not None:
            units[name] = unit
    return units


# ─── Translation production ────────────────────────────────────────────

# The applied match the vendor actually reuses on each canonical key. The
# subtitle line drops from the extraction-time 80 to 60, which is what makes
# the delivered figure diverge from the estimate.
CANONICAL_APPLIED_TM = {
    "menu.start": 96,
    "sub.intro": 60,
    "legal.eula": 40,
    "hud.ammo": 60,
}

CANONICAL_TARGET_TEXT = {
    "menu.start": "ゲーム開始",
    "sub.intro": "コロニーは夜明け前に陥落した。",
    "legal.eula": "続行すると使用許諾に同意したものとみなされます。",
    "hud.ammo": "残弾",
}


def write_unit_text(api: ApiClient, translation_unit_id: str, target_text: str,
                    applied_tm_match_pct: int,
                    target_char_count: Optional[int] = None) -> Dict[str, Any]:
    payload = f.translation_text_payload(
        target_text,
        len(target_text) if target_char_count is None else target_char_count,
        applied_tm_match_pct,
    )
    return get_success_data(
        api.write_translation_unit(translation_unit_id, payload, users.VENDOR)
    )


def deliver_unit(api: ApiClient, translation_unit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.deliver_translation_unit(translation_unit_id, users.VENDOR)
    )


def draft_and_deliver_unit(api: ApiClient, translation_unit_id: str, target_text: str,
                           applied_tm_match_pct: int,
                           target_char_count: Optional[int] = None) -> Dict[str, Any]:
    write_unit_text(api, translation_unit_id, target_text, applied_tm_match_pct,
                    target_char_count)
    return deliver_unit(api, translation_unit_id)


def deliver_all_units(api: ApiClient, market_plan_id: str,
                      keys: Dict[str, Dict[str, Any]],
                      applied_tm: Optional[Dict[str, int]] = None
                      ) -> Dict[str, Dict[str, Any]]:
    """Draft and deliver every unit of a plan, keyed by string-key name."""
    applied_tm = applied_tm or CANONICAL_APPLIED_TM
    delivered: Dict[str, Dict[str, Any]] = {}
    for name, unit in units_by_key_name(api, market_plan_id, keys).items():
        text = CANONICAL_TARGET_TEXT.get(name, f"Zieltext fuer {name}")
        pct = applied_tm.get(name, keys[name]["tm_match_pct"])
        delivered[name] = draft_and_deliver_unit(api, unit["id"], text, pct)
    return delivered


def qa_mark_unit(api: ApiClient, translation_unit_id: str, qa_status: str = "PASSED",
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.qa_mark_translation_unit(
            translation_unit_id, f.qa_mark_payload(qa_status),
            headers or users.LQA_VERIFIER,
        )
    )


# ─── Voice production ──────────────────────────────────────────────────


def create_booth(api: ApiClient, booth_code: str = "BER-A",
                 studio_city: str = "Berlin",
                 turnaround_buffer_minutes: Optional[int] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_booth(
            f.booth_payload(booth_code, studio_city, turnaround_buffer_minutes),
            users.PRODUCER,
        )
    )


def create_talent(api: ApiClient, talent_name: str = "Anke Roth",
                  language_code: str = "DE", union_flag: bool = True,
                  max_daily_recording_minutes: Optional[int] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_voice_talent(
            f.voice_talent_payload(talent_name, language_code, union_flag,
                                   max_daily_recording_minutes),
            users.PRODUCER,
        )
    )


def draft_contract(api: ApiClient, voice_talent_id: str, title_id: str,
                   expected_voice_talent_version: Optional[int] = None,
                   **kwargs) -> Dict[str, Any]:
    """Draft a usage-rights contract, reading the talent's current version first."""
    if expected_voice_talent_version is None:
        expected_voice_talent_version = read_talent(api, voice_talent_id)["version"]
    return get_success_data(
        api.create_talent_contract(
            f.talent_contract_payload(voice_talent_id, title_id,
                                      expected_voice_talent_version, **kwargs),
            users.PRODUCER,
        )
    )


def sign_contract(api: ApiClient, talent_contract_id: str,
                  voice_talent_id: str) -> Dict[str, Any]:
    """The talent's own agent executes the contract."""
    return get_success_data(
        api.sign_talent_contract(
            talent_contract_id, users.make_talent_agent_headers(voice_talent_id)
        )
    )


def signed_contract(api: ApiClient, voice_talent_id: str, title_id: str,
                    **kwargs) -> Dict[str, Any]:
    contract = draft_contract(api, voice_talent_id, title_id, **kwargs)
    return sign_contract(api, contract["id"], voice_talent_id)


def book_session(api: ApiClient, market_plan_id: str, voice_talent_id: str,
                 recording_booth_id: str, talent_contract_id: str,
                 **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_voice_session(
            f.voice_session_payload(market_plan_id, voice_talent_id,
                                    recording_booth_id, talent_contract_id, **kwargs),
            users.PRODUCER,
        )
    )


def record_session(api: ApiClient, voice_session_id: str, voice_talent_id: str,
                   recorded_line_count: int) -> Dict[str, Any]:
    """Drive a scheduled session all the way to RECORDED as the owning agent."""
    agent = users.make_talent_agent_headers(voice_talent_id)
    get_success_data(api.start_voice_session(voice_session_id, agent))
    return get_success_data(
        api.complete_voice_session(
            voice_session_id, f.complete_session_payload(recorded_line_count), agent
        )
    )


def cancel_session(api: ApiClient, voice_session_id: str) -> Dict[str, Any]:
    return get_success_data(api.cancel_voice_session(voice_session_id, users.PRODUCER))


def record_session_at_its_start(api: ApiClient, session: Dict[str, Any],
                                voice_talent_id: str,
                                recorded_line_count: int) -> Dict[str, Any]:
    """Move the clock onto the booking and drive the session to RECORDED.

    Opening the booth door requires the logical clock to be at or after the
    session's ``start_utc``, so the clock is moved there first.
    """
    set_clock(api, session["start_utc"])
    return record_session(api, session["id"], voice_talent_id, recorded_line_count)


# ─── Quality assurance ─────────────────────────────────────────────────


def open_qa_pass(api: ApiClient, market_plan_id: str, pass_type: str = "LINGUISTIC",
                 inspected_unit_count: int = 100,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_qa_pass(
            f.qa_pass_payload(market_plan_id, pass_type, inspected_unit_count),
            headers or users.LQA_OPENER,
        )
    )


def log_bug(api: ApiClient, qa_pass_id: str, headers: Optional[Dict[str, str]] = None,
            **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_lqa_bug(
            f.lqa_bug_payload(qa_pass_id, **kwargs), headers or users.LQA_LOGGER
        )
    )


def triage_bug(api: ApiClient, lqa_bug_id: str, triage_action: str = "ACCEPT",
               duplicate_of_bug_id: Optional[str] = None,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.triage_lqa_bug(
            lqa_bug_id, f.triage_payload(triage_action, duplicate_of_bug_id),
            headers or users.LQA_LOGGER,
        )
    )


def submit_fix(api: ApiClient, lqa_bug_id: str,
               target_text: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.submit_fix_lqa_bug(lqa_bug_id, users.VENDOR, f.submit_fix_payload(target_text))
    )


def verify_bug(api: ApiClient, lqa_bug_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Verification is barred to the logger, so a different tester signs off."""
    return get_success_data(
        api.verify_lqa_bug(lqa_bug_id, headers or users.LQA_VERIFIER)
    )


def resolve_bug(api: ApiClient, lqa_bug_id: str) -> Dict[str, Any]:
    """Accept, fix and verify one defect, taking it out of the open set."""
    triage_bug(api, lqa_bug_id, "ACCEPT")
    submit_fix(api, lqa_bug_id)
    return verify_bug(api, lqa_bug_id)


def close_qa_pass(api: ApiClient, qa_pass_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Closing is barred to the opener, so a different tester closes."""
    return get_success_data(api.close_qa_pass(qa_pass_id, headers or users.LQA_CLOSER))


def open_and_close_linguistic_pass(api: ApiClient, market_plan_id: str,
                                   inspected_unit_count: int = 100) -> Dict[str, Any]:
    """The one LINGUISTIC pass every release-ready market must be able to show."""
    qa_pass = open_qa_pass(api, market_plan_id, "LINGUISTIC", inspected_unit_count)
    return close_qa_pass(api, qa_pass["id"])


# ─── Rating submissions ────────────────────────────────────────────────


def draft_submission(api: ApiClient, market_plan_id: str,
                     disclosed_content_codes: Optional[List[str]] = None,
                     footage_asset_count: int = 1,
                     target_rating: str = "TEEN_12",
                     expected_market_plan_version: Optional[int] = None,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """File a draft package, reading the plan's current version for the guard."""
    if expected_market_plan_version is None:
        expected_market_plan_version = read_plan(api, market_plan_id)["version"]
    payload = f.rating_submission_payload(
        market_plan_id, expected_market_plan_version, disclosed_content_codes,
        footage_asset_count, target_rating,
    )
    return get_success_data(
        api.create_rating_submission(payload, headers or users.COMPLIANCE)
    )


def submit_submission(api: ApiClient, rating_submission_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.submit_rating_submission(rating_submission_id, headers or users.COMPLIANCE)
    )


def begin_review(api: ApiClient, rating_submission_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The board picks the package up; it may not be the filer who does it."""
    return get_success_data(
        api.begin_review(rating_submission_id, headers or users.BOARD)
    )


def record_outcome(api: ApiClient, rating_submission_id: str,
                   board_decision: str = "RATE",
                   assigned_rating: Optional[str] = None,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.record_outcome(
            rating_submission_id,
            f.record_outcome_payload(board_decision, assigned_rating),
            headers or users.BOARD,
        )
    )


def rate_submission(api: ApiClient, rating_submission_id: str,
                    assigned_rating: Optional[str] = None) -> Dict[str, Any]:
    """Submit, review and rate one package. The assigned rating must equal the
    projected band, so it is read from the review response when not supplied."""
    submit_submission(api, rating_submission_id)
    reviewed = begin_review(api, rating_submission_id)
    band = assigned_rating or reviewed["projected_rating_band"]
    return record_outcome(api, rating_submission_id, "RATE", band)


def send_back_for_edits(api: ApiClient, rating_submission_id: str) -> Dict[str, Any]:
    """Submit, review and return the package EDITS_REQUIRED."""
    submit_submission(api, rating_submission_id)
    begin_review(api, rating_submission_id)
    return record_outcome(api, rating_submission_id, "REQUIRE_EDITS")


def propose_content_edit(api: ApiClient, rating_submission_id: str,
                         **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_content_edit(
            f.content_edit_payload(rating_submission_id, **kwargs), users.COMPLIANCE
        )
    )


def apply_content_edit(api: ApiClient, content_edit_id: str) -> Dict[str, Any]:
    return get_success_data(api.apply_content_edit(content_edit_id, users.COMPLIANCE))


# ─── Composite scenario builders ───────────────────────────────────────

VOICED_TIERS = ("FULL_VOICE", "FULL_CULTURAL")

STAGE_PLANNING = "PLANNING"
STAGE_STRINGS_LOCKED = "STRINGS_LOCKED"
STAGE_SCOPED = "SCOPED"
STAGE_IN_LOCALIZATION = "IN_LOCALIZATION"
STAGE_DELIVERED = "DELIVERED"
STAGE_LQA = "LQA"

_STAGE_ORDER = [
    STAGE_PLANNING,
    STAGE_STRINGS_LOCKED,
    STAGE_SCOPED,
    STAGE_IN_LOCALIZATION,
    STAGE_DELIVERED,
    STAGE_LQA,
]


def build_market(api: ApiClient, *, title_code: str = "NOVA-01",
                 name: str = "Nova Drift",
                 release_mode: str = "STAGGERED",
                 target_release_utc: Optional[str] = None,
                 market_code: str = "JP",
                 scope_tier: str = "TEXT_ONLY",
                 target_rating: str = "TEEN_12",
                 budget_cap_cents: int = 5000000,
                 required_voice_line_count: int = 0,
                 key_specs: Optional[List[Dict[str, Any]]] = None,
                 stage: str = STAGE_IN_LOCALIZATION,
                 applied_tm: Optional[Dict[str, int]] = None,
                 with_voice_capacity: bool = False,
                 booth_code: str = "BER-A",
                 turnaround_buffer_minutes: Optional[int] = None,
                 talent_name: str = "Anke Roth",
                 talent_language_code: str = "DE",
                 max_daily_recording_minutes: Optional[int] = None,
                 buyout_fee_cents: int = 500000,
                 per_line_rate_cents: int = 250,
                 media_scope: str = "IN_GAME_AND_TRAILER",
                 territory_scope: Optional[List[str]] = None,
                 ) -> Dict[str, Any]:
    """Drive one title and one market plan up to the requested stage.

    ``stage`` walks the workflow: a title in ``PLANNING``, a frozen string set,
    a ``SCOPED`` plan, a plan handed to the vendor, every unit ``DELIVERED``, or
    the plan in ``LQA``. A voiced tier needs studio capacity and a signed
    contract covering the market before the hand-off is permitted, so those rows
    are built automatically for ``FULL_VOICE`` and ``FULL_CULTURAL``.
    """
    assert stage in _STAGE_ORDER, f"Unknown stage {stage!r}"
    reached = _STAGE_ORDER.index(stage)

    world: Dict[str, Any] = {}
    title_kwargs: Dict[str, Any] = {
        "title_code": title_code,
        "name": name,
        "release_mode": release_mode,
    }
    if target_release_utc is not None:
        title_kwargs["target_release_utc"] = target_release_utc
    world["title"] = create_title(api, **title_kwargs)
    title_id = world["title"]["id"]

    specs = key_specs if key_specs is not None else f.CANONICAL_KEY_SPECS
    keys: Dict[str, Dict[str, Any]] = {}
    for spec in specs:
        key = create_string_key(api, title_id, **spec)
        keys[key["key_name"]] = key
    world["keys"] = keys

    world["plan"] = create_market_plan(
        api, title_id, market_code=market_code, scope_tier=scope_tier,
        target_rating=target_rating, budget_cap_cents=budget_cap_cents,
        required_voice_line_count=required_voice_line_count,
    )
    plan_id = world["plan"]["id"]

    needs_voice = with_voice_capacity or scope_tier in VOICED_TIERS
    if needs_voice:
        world["booth"] = create_booth(api, booth_code, "Berlin",
                                      turnaround_buffer_minutes)
        world["talent"] = create_talent(api, talent_name, talent_language_code, True,
                                        max_daily_recording_minutes)
        world["contract"] = signed_contract(
            api, world["talent"]["id"], title_id,
            territory_scope=territory_scope or [market_code],
            media_scope=media_scope, buyout_fee_cents=buyout_fee_cents,
            per_line_rate_cents=per_line_rate_cents,
        )

    if reached >= _STAGE_ORDER.index(STAGE_STRINGS_LOCKED):
        world["title"] = lock_strings(api, title_id)
    if reached >= _STAGE_ORDER.index(STAGE_SCOPED):
        world["plan"] = scope_plan(api, plan_id)
    if reached >= _STAGE_ORDER.index(STAGE_IN_LOCALIZATION):
        world["plan"] = start_localization(api, plan_id)
        world["units"] = units_by_key_name(api, plan_id, keys)
    if reached >= _STAGE_ORDER.index(STAGE_DELIVERED):
        world["units"] = deliver_all_units(api, plan_id, keys, applied_tm)
    if reached >= _STAGE_ORDER.index(STAGE_LQA):
        world["plan"] = enter_lqa(api, plan_id)
        world["title"] = read_title(api, title_id)

    return world


def build_market_with_rated_submission(api: ApiClient, *,
                                       disclosed_content_codes: Optional[List[str]] = None,
                                       footage_asset_count: int = 2,
                                       assigned_rating: Optional[str] = None,
                                       **market_kwargs) -> Dict[str, Any]:
    """A market in LQA whose governing submission has been rated by the board."""
    market_kwargs.setdefault("stage", STAGE_LQA)
    world = build_market(api, **market_kwargs)
    submission = draft_submission(
        api, world["plan"]["id"], disclosed_content_codes, footage_asset_count,
        world["plan"]["target_rating"],
    )
    world["submission"] = rate_submission(api, submission["id"], assigned_rating)
    world["plan"] = read_plan(api, world["plan"]["id"])
    return world


def build_market_with_edits_required(api: ApiClient, *,
                                     disclosed_content_codes: Optional[List[str]] = None,
                                     footage_asset_count: int = 2,
                                     **market_kwargs) -> Dict[str, Any]:
    """A market in LQA whose governing submission came back EDITS_REQUIRED.

    That is the one state from which a content edit may be proposed.
    """
    market_kwargs.setdefault("stage", STAGE_LQA)
    world = build_market(api, **market_kwargs)
    submission = draft_submission(
        api, world["plan"]["id"], disclosed_content_codes, footage_asset_count,
        world["plan"]["target_rating"],
    )
    world["submission"] = send_back_for_edits(api, submission["id"])
    world["plan"] = read_plan(api, world["plan"]["id"])
    return world


def build_release_ready_market(api: ApiClient, *,
                               disclosed_content_codes: Optional[List[str]] = None,
                               footage_asset_count: int = 1,
                               inspected_unit_count: int = 100,
                               **market_kwargs) -> Dict[str, Any]:
    """A market driven all the way to RELEASE_READY.

    The ladder needs one closed LINGUISTIC pass, a rated governing submission
    whose assigned rating is no stricter than the target, and zero overage.
    """
    market_kwargs.setdefault("market_code", "JP")
    market_kwargs.setdefault("target_rating", "MATURE_17")
    world = build_market_with_rated_submission(
        api,
        disclosed_content_codes=disclosed_content_codes or ["VIOLENCE_STYLIZED"],
        footage_asset_count=footage_asset_count,
        **market_kwargs,
    )
    world["qa_pass"] = open_and_close_linguistic_pass(
        api, world["plan"]["id"], inspected_unit_count
    )
    world["plan"] = get_success_data(
        api.mark_release_ready(world["plan"]["id"], users.COMPLIANCE)
    )
    world["title"] = read_title(api, world["title"]["id"])
    return world


def build_voiced_market_ready_to_book(api: ApiClient, **market_kwargs) -> Dict[str, Any]:
    """A FULL_VOICE market in IN_LOCALIZATION with a booth, talent and signed contract."""
    market_kwargs.setdefault("market_code", "DE")
    market_kwargs.setdefault("scope_tier", "FULL_VOICE")
    market_kwargs.setdefault("target_rating", "MATURE_15")
    market_kwargs.setdefault("budget_cap_cents", 9000000)
    market_kwargs.setdefault("stage", STAGE_IN_LOCALIZATION)
    return build_market(api, **market_kwargs)


def add_talent_with_contract(api: ApiClient, world: Dict[str, Any], *,
                             talent_name: str, territory_scope: List[str],
                             media_scope: str = "IN_GAME_AND_TRAILER",
                             buyout_fee_cents: int = 400000,
                             per_line_rate_cents: int = 200,
                             union_flag: bool = False,
                             max_daily_recording_minutes: Optional[int] = None,
                             language_code: str = "DE") -> Dict[str, Any]:
    """Register a second talent for the same title with its own signed contract."""
    talent = create_talent(api, talent_name, language_code, union_flag,
                           max_daily_recording_minutes)
    contract = signed_contract(
        api, talent["id"], world["title"]["id"], territory_scope=territory_scope,
        media_scope=media_scope, buyout_fee_cents=buyout_fee_cents,
        per_line_rate_cents=per_line_rate_cents,
    )
    return {"talent": talent, "contract": contract}


# ─── Pytest fixtures ───────────────────────────────────────────────────


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def clock_at_startup(api: ApiClient) -> str:
    """Pin the logical clock at its startup value, 2026-08-01T00:00:00Z."""
    set_clock(api, CLOCK_STARTUP_UTC)
    return CLOCK_STARTUP_UTC


@pytest.fixture
def title_with_keys(api: ApiClient) -> Dict[str, Any]:
    """A title in PLANNING carrying the canonical four source strings."""
    title = create_title(api, title_code="NOVA-01", name="Nova Drift")
    keys = create_canonical_keys(api, title["id"])
    return {"title": title, "keys": keys}


@pytest.fixture
def text_market_in_localization(api: ApiClient) -> Dict[str, Any]:
    """A TEXT_ONLY JP market handed to the vendor, its four units PENDING."""
    return build_market(api, title_code="NOVA-01", market_code="JP",
                        scope_tier="TEXT_ONLY", stage=STAGE_IN_LOCALIZATION)


@pytest.fixture
def text_market_in_lqa(api: ApiClient) -> Dict[str, Any]:
    """A TEXT_ONLY JP market in LQA with all four units DELIVERED."""
    return build_market(api, title_code="NOVA-01", market_code="JP",
                        scope_tier="TEXT_ONLY", stage=STAGE_LQA)


@pytest.fixture
def voiced_market_ready_to_book(api: ApiClient) -> Dict[str, Any]:
    """A FULL_VOICE DE market with a booth, a talent and a signed contract."""
    return build_voiced_market_ready_to_book(api, title_code="NOVA-02",
                                             name="Nova Drift Voice")


@pytest.fixture
def market_with_edits_required(api: ApiClient) -> Dict[str, Any]:
    """A JP market whose governing submission came back EDITS_REQUIRED."""
    return build_market_with_edits_required(
        api, title_code="NOVA-03", name="Nova Drift Edits", market_code="JP",
        disclosed_content_codes=["VIOLENCE_REALISTIC", "BLOOD"],
        footage_asset_count=2, target_rating="MATURE_15",
    )


BOARD_FOR_MARKET = MARKET_BOARD
