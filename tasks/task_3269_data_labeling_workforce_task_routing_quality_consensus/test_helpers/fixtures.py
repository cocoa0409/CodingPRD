"""Composite setup helpers.

Every helper builds its preconditions through the public API only, because the
server holds all state in memory and is restarted before every test. No helper
assumes any pre-existing row.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    commit_label_payload,
    create_item_payload,
    create_program_payload,
    create_spec_unit_payload,
    create_worker_payload,
    grade_payload,
    payout_payload,
)
from .test_users import (
    TEST_USERS,
    make_worker_headers,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
REVIEWER_TWO = TEST_USERS["reviewer_two_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Engagement-level input fields of PRD §3.1/§3.2, used to route a scenario's
# keyword overrides to the right registration call.
PROGRAM_INPUT_FIELDS = {
    "program_code", "name", "instruction_model", "sensitivity_class",
    "deadline_utc", "blackout_start_utc", "blackout_end_utc", "coverage_hours",
    "min_consensus_agreement", "commitment_quorum", "commit_deadline_seconds",
    "patience_seconds", "weekly_earning_cap_cents", "capacity_points",
    "accuracy_floor_pct", "accuracy_high_watermark_pct",
    "point_cost_high_accuracy", "point_cost_medium_accuracy", "point_cost_fallback",
}

# Handles whose deterministic es-MX score clears the PROFICIENT gate (6500),
# ordered so that pool[0] is the top-ranked member of the pool (PRD §3.4 ranks
# by qualification_score descending, and a hand-picked handle order alone does
# not guarantee the registration order matches the dispatch order).
PROFICIENT_HANDLES = [
    "kevin-lum",     # 9555, the top-ranked member of the pool
    "june-osei",     # 9276
    "linh-tran",     # 9214
    "priya-nair",    # 8632
    "mira-vega",     # 8594
    "aiko-tanaka",   # 6748
    "tomas-ibarra",  # 6724
]
# Handles whose es-MX score clears the EXPERT gate (8000), top-ranked first.
EXPERT_HANDLES = ["kevin-lum", "june-osei", "linh-tran", "priya-nair", "mira-vega"]


# ---------------------------------------------------------------------------
# Low-level builders
# ---------------------------------------------------------------------------

def set_clock(current_utc: str = DEFAULT_CLOCK_UTC):
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def register_worker(handle: str, **overrides) -> dict:
    payload = create_worker_payload(handle=handle, **overrides)
    return get_success_data(api_client.register_worker(payload, ANON), 201)


def get_worker(worker_id: str, params=None) -> dict:
    return get_success_data(api_client.get_worker(worker_id, ADMIN, params), 200)


def create_program(**overrides) -> dict:
    payload = create_program_payload(**overrides)
    return get_success_data(api_client.create_program(payload, ADMIN), 201)


def get_program(program_id: str, plan_variant=None) -> dict:
    params = {"plan_variant": plan_variant} if plan_variant else None
    return get_success_data(api_client.get_program(program_id, ADMIN, params), 200)


def open_program(program: dict, action: str = "OPEN") -> dict:
    resp = api_client.program_state(program["id"], {"program_action": action}, ADMIN)
    return get_success_data(resp, 200)


def freeze_program(program: dict) -> dict:
    return get_success_data(
        api_client.program_state(program["id"], {"program_action": "FREEZE"}, ADMIN), 200
    )


def create_unit(program: dict, **overrides) -> dict:
    current = get_program(program["id"])
    payload = create_spec_unit_payload(
        program_id=program["id"], expected_program_version=current["version"], **overrides
    )
    return get_success_data(api_client.create_spec_unit(payload, ADMIN), 201)


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_spec_unit(unit_id, ADMIN), 200)


def advance_unit(unit: dict, action: str = "ACTIVATE") -> dict:
    return get_success_data(
        api_client.advance_unit(unit["id"], {"unit_action": action}, ADMIN), 200
    )


def attach_item(unit: dict, **overrides) -> dict:
    payload = create_item_payload(**overrides)
    return get_success_data(api_client.create_item(unit["id"], payload, ADMIN), 201)


def enroll_qualification(
    worker: dict, language_code: str = "es-MX", tier: str = "PROFICIENT",
    training_required_count: int = 0,
) -> dict:
    payload = {
        "language_code": language_code,
        "tier": tier,
        "qualification_action": "ENROLL",
        "training_required_count": training_required_count,
    }
    return get_success_data(api_client.worker_qualification_action(worker["id"], payload, ADMIN), 200)


def verify_qualification(worker: dict, language_code: str = "es-MX", tier: str = "PROFICIENT") -> dict:
    payload = {"language_code": language_code, "tier": tier, "qualification_action": "VERIFY"}
    return get_success_data(api_client.worker_qualification_action(worker["id"], payload, ADMIN), 200)


def register_qualified_worker(
    handle: str, language_code: str = "es-MX", tier: str = "PROFICIENT",
    worker_overrides: dict = None,
) -> tuple:
    """Register a worker and drive its qualification to QUALIFIED. Returns (worker, qualification)."""
    worker = register_worker(handle, **(worker_overrides or {}))
    enroll_qualification(worker, language_code, tier, training_required_count=0)
    qualification = verify_qualification(worker, language_code, tier)
    return worker, qualification


def make_pool(count: int, language_code: str = "es-MX", tier: str = "PROFICIENT",
              handles=None, worker_overrides: dict = None) -> list:
    """Register `count` verified workers with distinct identities.

    The pool is returned in the selector's own ranking order (PRD §3.4 keys the
    ranking on `accuracy_pct` descending and then `qualification_score`
    descending), so `pool[0]` is the member a full panel takes first. Every
    freshly verified qualification carries an accuracy of 0, so the
    deterministic `qualification_score` is what orders them, and hand-picked
    handles alone do not guarantee registration order matches dispatch order.
    """
    handles = handles or (PROFICIENT_HANDLES if tier != "EXPERT" else EXPERT_HANDLES)
    pool = []
    for i in range(count):
        worker, qualification = register_qualified_worker(
            handles[i], language_code, tier, worker_overrides
        )
        pool.append((worker, qualification))
    pool.sort(key=lambda entry: (-entry[1].get("qualification_score", 0), entry[1]["created_at"]))
    return pool


# ---------------------------------------------------------------------------
# Panel plumbing
# ---------------------------------------------------------------------------

def dispatch_panel(item: dict) -> dict:
    return get_success_data(api_client.dispatch_panel(item["id"], ADMIN), 200)


def panel_commits(item: dict, limit: int = 100) -> list:
    """Every assignment on the piece.

    The commit list of PRD §2.3 defaults `limit` to 10, and a unit at
    panel_size 2 with several gold audits on one piece exceeds that, so the
    fixture asks for the declared maximum; otherwise a rework's fresh member
    can be paged out and the test would see a truncated panel.
    """
    data = get_success_data(api_client.list_commits(item["id"], ADMIN, {"limit": limit}), 200)
    return data


def production_commits(item: dict) -> list:
    return [c for c in panel_commits(item) if c.get("kind") == "PRODUCTION"]


def commit_label(commit: dict, worker: dict, label: str = "A", **overrides) -> dict:
    payload = commit_label_payload(label=label, **overrides)
    return get_success_data(
        api_client.commit_label(commit["id"], payload, make_worker_headers(worker["id"])), 200
    )


def commit_abstain(commit: dict, worker: dict) -> dict:
    return get_success_data(
        api_client.commit_label(
            commit["id"], {"abstained": True, "instructions_ack": True},
            make_worker_headers(worker["id"]),
        ),
        200,
    )


def pay_commit(commit_id: str, amount_cents: int, currency: str = "USD") -> dict:
    return get_success_data(
        api_client.create_payout_record(commit_id, payout_payload(amount_cents, currency), ADMIN), 200
    )


def create_gold_audit(commit: dict, task_key: str) -> dict:
    return get_success_data(
        api_client.create_gold_audit(commit["id"], {"gold_task_key": task_key}, REVIEWER), 201
    )


def grade_gold_audit(gold_audit_id: str, outcome: str, item_id: str) -> dict:
    """Read the piece's live version immediately before grading, as the OCC guard demands."""
    live = get_success_data(api_client.get_item(item_id, REVIEWER), 200)
    return get_success_data(
        api_client.grade_gold_audit(
            gold_audit_id, grade_payload(outcome, live["version"]), REVIEWER
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenarios
# ---------------------------------------------------------------------------

def setup_program_with_unit(
    pool_size: int = 1,
    language_code: str = "es-MX",
    tier: str = "PROFICIENT",
    item_count: int = 0,
    open_program_flag: bool = True,
    item_overrides: dict = None,
    extra_items: list = None,
    worker_overrides: dict = None,
    program_overrides: dict = None,
    **unit_overrides,
) -> tuple:
    """Engagement + one published unit + a verified worker pool.

    `program_overrides` reaches the engagement registration; a keyword naming an
    engagement-level field is routed there too, and everything else reaches the
    unit decomposition.
    Returns (program, unit, pool, items) where pool is a list of (worker, qualification).
    """
    merged_program = dict(program_overrides or {})
    unit_overrides = dict(unit_overrides)
    for key in list(unit_overrides):
        if key in PROGRAM_INPUT_FIELDS:
            merged_program.setdefault(key, unit_overrides.pop(key))
    program = create_program(language_code=language_code, **merged_program)
    unit = create_unit(program, **unit_overrides)
    if open_program_flag:
        program = open_program(program)
        unit = get_unit(unit["id"])
    pool = make_pool(
        pool_size, language_code, tier, worker_overrides=worker_overrides
    ) if pool_size > 0 else []
    items = []
    for i in range(item_count):
        overrides = dict(item_overrides or {}) if i == 0 else {}
        overrides.setdefault("item_key", f"i-{i + 1:04d}")
        overrides.setdefault("payload_uri", f"s3://ax/{i + 1:04d}")
        items.append(attach_item(unit, **overrides))
    for spec in (extra_items or []):
        items.append(attach_item(unit, **spec))
    return program, unit, pool, items


def setup_program_for_capacity(units: list, **program_overrides) -> tuple:
    """Engagement in DRAFT with N units declared by (unit_code, max_items) pairs."""
    program = create_program(**program_overrides)
    created = []
    for unit_code, max_items in units:
        created.append(create_unit(program, unit_code=unit_code, max_items=max_items))
    program = get_program(program["id"])
    return program, created


def setup_dispatched_item(
    panel_size: int = 1,
    pool_size: int = None,
    language_code: str = "es-MX",
    tier: str = "PROFICIENT",
    item_overrides: dict = None,
    worker_overrides: dict = None,
    program_overrides: dict = None,
    **unit_overrides,
) -> tuple:
    """Engagement + unit + one released piece with a panel already dispatched.

    The pool is deliberately deeper than the first panel: the selector of PRD
    §3.4 excludes every worker who already owns a commit on the piece, and a
    second dispatch tops the panel up to `panel_size` rather than refusing
    (§3.3), so a pool of exactly `panel_size + 1` would leave the rework of a
    panel_size 1 piece with no fresh member. Two spare members guarantee one is
    still available after the panel is filled, whatever the deterministic
    qualification scores of the pooled handles.

    Returns (program, unit, pool, item, commits).
    """
    pool_size = pool_size if pool_size is not None else max(panel_size, 1) + 2
    program, unit, pool, items = setup_program_with_unit(
        pool_size=pool_size,
        language_code=language_code,
        tier=tier,
        item_count=1,
        item_overrides=item_overrides,
        worker_overrides=worker_overrides,
        program_overrides=program_overrides,
        panel_size=panel_size,
        **unit_overrides,
    )
    item = items[0]
    item = dispatch_panel(item)
    # The fixture's contract is "a panel already dispatched", so the returned
    # commits are the panel the dispatch actually selected. The deeper pool
    # exists only so a rework re-dispatch has a fresh member.
    commits = production_commits(item)[:panel_size]
    return program, unit, pool, item, commits


def worker_for_commit(commit: dict, pool: list) -> dict:
    """Resolve the pool entry that owns a dispatched assignment."""
    for worker, _qualification in pool:
        if worker["id"] == commit["worker_id"]:
            return worker
    raise AssertionError(f"No pooled worker owns commit {commit['id']}")


def setup_certified_item(
    panel_size: int = 1,
    label: str = "A",
    pay: bool = True,
    amount_cents: int = None,
    language_code: str = "es-MX",
    tier: str = "PROFICIENT",
    item_overrides: dict = None,
    program_overrides: dict = None,
    **unit_overrides,
) -> tuple:
    """Engagement + unit + one piece driven all the way to CERTIFIED.

    The quorum is pinned to at most the panel that is actually dispatched, so a
    panel_size 1 piece can certify: PRD §3.1 defaults `commitment_quorum` to 3
    and a one-member panel can never reach it. A caller's explicit quorum wins.

    Returns (program, unit, pool, item, commits).
    """
    program_overrides = dict(program_overrides or {})
    program_overrides.setdefault("commitment_quorum", min(max(panel_size, 1), 3))
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=panel_size,
        language_code=language_code,
        tier=tier,
        item_overrides=item_overrides,
        program_overrides=program_overrides,
        **unit_overrides,
    )
    amount = amount_cents if amount_cents is not None else _unit_amount(tier, 0, "PRODUCTION")
    for commit in commits:
        worker = worker_for_commit(commit, pool)
        commit_label(commit, worker, label)
    if pay:
        for commit in commits:
            pay_commit(commit["id"], amount)
    item = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    return program, unit, pool, item, commits


def setup_split_panel(
    label_majority: int,
    label_minority: int,
    minority_label: str = "B",
    **kwargs,
) -> tuple:
    """Dispatch a panel and split its members across two labels.

    Returns (program, unit, pool, item, commits).
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=label_majority + label_minority, **kwargs
    )
    for commit in commits[:label_majority]:
        commit_label(commit, worker_for_commit(commit, pool), "A")
    for commit in commits[label_majority:]:
        commit_label(commit, worker_for_commit(commit, pool), minority_label)
    item = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    return program, unit, pool, item, commits


def setup_graded_gold_audits(item: dict, anchor_commit: dict, outcomes: list,
                             start_index: int = 1) -> list:
    """Create and grade `len(outcomes)` gold audits, one per outcome.

    Returns the list of graded gold-audit commit payloads.
    """
    graded = []
    for offset, outcome in enumerate(outcomes):
        gold = create_gold_audit(anchor_commit, f"gold-{start_index + offset:06d}")
        graded.append(grade_gold_audit(gold["id"], outcome, item["id"]))
    return graded


def setup_rotated_item(anchor_commit: dict, item: dict, count: int = 3) -> list:
    """Create `count` gold audits on a piece without grading them."""
    audits = []
    for i in range(count):
        audits.append(create_gold_audit(anchor_commit, f"gold-{i + 1:06d}"))
    return audits


def _unit_amount(tier: str, gold_fail_streak: int, kind: str = "PRODUCTION") -> int:
    """The PRD rounding of section 3.10, computed for fixture defaults."""
    from .constants import BASE_RATE, GOLD_BASE_RATE, STREAK_MULT, TIER_MULT

    base = GOLD_BASE_RATE if kind == "GOLD" else BASE_RATE
    product = base * STREAK_MULT.get(gold_fail_streak, 0.5) * TIER_MULT[tier]
    # round half up on a single non-negative value
    return int(product + 0.5)


def qualified_headers(worker: dict) -> dict:
    return make_worker_headers(worker["id"])


def report_incident(worker: dict, severity: str = "MAJOR", program_code: str = None,
                    category: str = "PII_EXPOSURE", action: str = "REPORT",
                    description_text: str = "Observed breach.") -> dict:
    payload = {
        "program_code": program_code or TEST_DEFAULTS["PROGRAM_CODE"],
        "category": category,
        "severity": severity,
        "description_text": description_text,
        "incident_action": action,
    }
    return get_success_data(api_client.create_incident(worker["id"], payload, ADMIN), 201)


def file_appeal(item: dict, worker: dict, grounds: str = "AMBIGUOUS_INSTRUCTIONS",
                statement_text: str = "The instruction document does not cover the null case.") -> dict:
    payload = {"item_id": item["id"], "grounds": grounds, "statement_text": statement_text}
    return get_success_data(
        api_client.file_appeal(payload, make_worker_headers(worker["id"])), 201
    )


def propose_appeal(case_id: str, outcome: str, headers=None) -> dict:
    return get_success_data(
        api_client.advance_appeal(
            case_id, {"appeal_action": "PROPOSE", "proposed_outcome": outcome},
            headers or REVIEWER,
        ),
        200,
    )


def escalate_appeal(case_id: str, headers=None, proposed_outcome: str = None) -> dict:
    payload = {"appeal_action": "ESCALATE"}
    if proposed_outcome is not None:
        payload["proposed_outcome"] = proposed_outcome
    return get_success_data(
        api_client.advance_appeal(case_id, payload, headers or REVIEWER_TWO),
        200,
    )


def concur_appeal(case_id: str, expected_claim_version: int, headers=None) -> dict:
    return get_success_data(
        api_client.concur_appeal(
            case_id, {"expected_claim_version": expected_claim_version}, headers or REVIEWER
        ),
        200,
    )


def get_appeal_case(case_id: str, item: dict) -> dict:
    """Recover an AppealClaim from its owning piece's dispute list."""
    claims = get_success_data(api_client.list_appeal_cases(item["id"], ADMIN), 200)
    for claim in claims:
        if claim["id"] == case_id:
            return claim
    raise AssertionError(f"Appeal claim {case_id} not found on piece {item['id']}")


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_split_gold_audits(outcomes, item_count=2, panel_size=1, gold_rate=1.0,
                            language_code="es-MX", tier="PROFICIENT", pay=False,
                            **program_overrides):
    """Engagement + one unit holding `item_count` pieces, each with its first
    panel member committed, and `len(outcomes)` gold audits graded in order.

    Audits are spread across the pieces so that no single piece ever exceeds the
    weekly rotation counter of three; when the caller asks for more audits than
    the requested piece count could absorb, the harness adds the pieces it needs
    rather than exceeding the rotation limit, which PRD §3.7 refuses outright.

    Returns (program, unit, pool, items, commits, graded).
    """
    item_count = max(item_count, (len(outcomes) + 2) // 3)
    program = create_program(language_code=language_code, **program_overrides)
    unit = create_unit(program, unit_code="U-1", panel_size=panel_size, gold_rate=gold_rate)
    open_program(program)
    # The pool carries at least two eligible qualifications: the dispatch
    # selector of PRD §3.4 excludes a piece's existing owners, and a second
    # dispatch tops a partial panel up rather than refusing, so a panel_size 1
    # unit needs a second member available for a gold audit to be served by
    # someone other than the anchor.
    pool = make_pool(max(panel_size, 2) + item_count, language_code, tier)

    items, commits = [], []
    for index in range(item_count):
        item = attach_item(unit, item_key=f"i-{index + 1:04d}", payload_uri=f"s3://ax/{index + 1:04d}")
        dispatched = dispatch_panel(item)
        member = production_commits(dispatched)[0]
        commit_label(member, worker_for_commit(member, pool), "A")
        if pay:
            pay_commit(member["id"], _unit_amount(tier, 0, "PRODUCTION"))
        items.append(get_success_data(api_client.get_item(item["id"], ADMIN), 200))
        commits.append(member)

    graded = []
    per_piece = [[] for _ in items]
    for offset, outcome in enumerate(outcomes):
        per_piece[offset % item_count].append((offset, outcome))
    for piece_index, entries in enumerate(per_piece):
        for offset, outcome in entries:
            gold = create_gold_audit(commits[piece_index], f"gold-{offset + 1:06d}")
            graded.append(grade_gold_audit(gold["id"], outcome, items[piece_index]["id"]))

    program = get_program(program["id"])
    return program, unit, pool, items, commits, graded


def setup_pending_embargo(accuracy_floor_pct=85, quorum=3, panel_size=2,
                          language_code="es-MX", tier="PROFICIENT"):
    """Engagement on which four PASSED and one FAILED audit put accepted accuracy
    at exactly 80.00, with two dispatched pieces still short of quorum.

    Returns (program, unit, pool, items, commits).
    """
    program = create_program(
        language_code=language_code, accuracy_floor_pct=accuracy_floor_pct,
        commitment_quorum=quorum,
    )
    unit = create_unit(program, unit_code="U-1", panel_size=panel_size, gold_rate=1.0)
    open_program(program)
    # One extra eligible qualification so a gold audit always has an auditor
    # distinct from the anchor member (§3.7 constrains where the ground truth
    # comes from, not who serves the audit).
    pool = make_pool(max(panel_size, 1) + 1, language_code, tier)

    # Three pieces so the accepted variant can later be lifted back over the
    # floor: the weekly gold rotation caps each piece at three audits, so a
    # recall path needs room to grade further PASSED audits.
    items, commits = [], []
    for index in range(3):
        item = attach_item(unit, item_key=f"i-{index + 1:04d}", payload_uri=f"s3://ax/{index + 1:04d}")
        dispatched = dispatch_panel(item)
        member = production_commits(dispatched)[0]
        commit_label(member, worker_for_commit(member, pool), "A" if index == 0 else "B")
        items.append(item)
        commits.append(member)

    outcomes = ["PASSED", "PASSED", "PASSED", "PASSED", "FAILED"]
    prices = [(0, "PASSED"), (0, "PASSED"), (0, "PASSED"), (1, "PASSED"), (1, "FAILED")]
    for offset, (piece_index, outcome) in enumerate(prices):
        gold = create_gold_audit(commits[piece_index], f"gold-{offset + 1:06d}")
        grade_gold_audit(gold["id"], outcome, items[piece_index]["id"])

    return program, unit, pool, items, commits


def setup_certified_standard_unit(max_items=10, panel_size=1, language_code="es-MX",
                                  tier="PROFICIENT", **overrides):
    """Engagement + one unit whose single piece is certified and paid.

    The quorum is pinned to 1 unless the caller overrides it: PRD §3.1 defaults
    `commitment_quorum` to 3, and a single-member panel can never reach it, so
    without the pin the fixture's piece would stall in AWAITING_CONSENSUS and
    every "certified piece" scenario would be unbuildable. Engagement-level
    keywords are routed to the engagement registration and the rest to the unit.

    Returns (program, unit, pool, item, commit).
    """
    program_overrides = {"commitment_quorum": 1}
    unit_overrides = {}
    for key, value in overrides.items():
        if key in PROGRAM_INPUT_FIELDS:
            program_overrides[key] = value
        else:
            unit_overrides[key] = value
    program, unit, pool, item, commits = setup_certified_item(
        panel_size=panel_size, language_code=language_code, tier=tier,
        max_items=max_items, program_overrides=program_overrides, **unit_overrides,
    )
    return program, unit, pool, item, commits[0]