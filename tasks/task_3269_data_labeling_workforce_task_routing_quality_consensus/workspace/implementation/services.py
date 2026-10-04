"""Business logic for the Data Labeling Ops API.

Every rule in here traces to a sentence of PRD.md (the contract) or, where the
PRD is silent on structure, to SCAFFOLD.yaml. The two places the scaffold and
the PRD disagree are resolved in the PRD's favour and are called out inline:

  * round order in the dynamic pay rate -- single rounding site, after both
    multipliers (PRD sections 3.10 and 2.8);
  * a panel shorter than `panel_size` dispatches every member found rather than
    failing (PRD sections 3.3 and 3.4).
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

from db import (
    add_seconds,
    appeals,
    commits,
    current_epoch_index,
    elapsed_seconds,
    incidents,
    iso,
    items,
    items_of_unit,
    now,
    open_epoch,
    parse_dt,
    programs,
    qualifications,
    spec_units,
    touch,
    units_of_program,
    workers,
)

getcontext().prec = 28

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
LANGUAGES = ("es-MX", "en-US", "vi-VN", "tl-PH", "pt-BR", "ta-IN", "hi-IN")
INSTRUCTION_MODELS = (
    "IDEAL_RESPONSE",
    "RANKED_PREFERENCE",
    "SPAN_EXTRACTION",
    "SAFETY_CLASSIFICATION",
)
SENSITIVITY_CLASSES = ("STANDARD", "SENSITIVE", "RESTRICTED")
INCIDENT_SEVERITIES = ("NONE", "MINOR", "MAJOR", "CATASTROPHIC")
INCIDENT_CATEGORIES = (
    "PII_EXPOSURE",
    "DATASET_DOWNLOAD",
    "SCREEN_RECORDING",
    "UNAUTHORIZED_SHARE",
)
INCIDENT_STATUSES = ("OPEN", "RESOLVED", "DISMISSED")
INSTRUCTION_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")
UNIT_STATUSES = ("DRAFT", "ACTIVE", "COMPLETE", "REJECTED")
PIECE_STATUSES = ("DECOMPOSED", "IN_PRODUCTION", "CONSENSUS", "CERTIFIED", "REJECTED", "REWORK")
ITEM_STATUSES = ("PENDING", "ROUTED", "IN_REVIEW", "COMPLETED", "REWORK")
CONSENSUS_STATUSES = ("PENDING", "AWAITING_CONSENSUS", "CERTIFIED", "HELD_QUORUM", "REJECTED", "REWORK")
ITEM_CONTAINER_STATUSES = ("DRAFT", "RELEASED", "IN_PANEL", "RESOLVED")
COMMIT_KINDS = ("PRODUCTION", "GOLD")
COMMIT_STATUSES = ("DISPATCHED", "COMMITTED", "ABSTAINED", "COMMIT_EXPIRED")
GOLD_OUTCOMES = ("PASSED", "FLAGGED", "FAILED", "EXCLUDED_FROM_ACCURACY")
GOLD_OUTCOME_BASE = ("PASSED", "FAILED", "EXCLUDED_FROM_ACCURACY")
PAYMENT_STATUSES = ("UNPAID", "PENDING", "ACCEPTED", "REVERSED")
TIERS = ("NOVICE", "PROFICIENT", "EXPERT")
QUALIFICATION_STATUSES = ("IN_TRAINING", "QUALIFIED", "PROBATION", "SUSPENDED", "REVOKED")
CURRENCIES = ("USD", "MXN", "PHP", "VND", "BRL", "INR")
APPEAL_GROUNDS = ("AMBIGUOUS_INSTRUCTIONS", "INSUFFICIENT_CONTEXT", "TECHNICAL_ERROR")
PROPOSED_OUTCOMES = ("PAY_REVERSAL", "QUALIFICATION_RESET", "OUTCOME_STANDS")

# Tuning defaults (PRD sections 3.1 and 3.11).
DEFAULT_MIN_CONSENSUS_AGREEMENT = 0.6
DEFAULT_COMMITMENT_QUORUM = 3
DEFAULT_COMMIT_DEADLINE_SECONDS = 7200
DEFAULT_PATIENCE_SECONDS = 600
DEFAULT_COVERAGE_HOURS = 168
DEFAULT_CAPACITY_POINTS = 100000
DEFAULT_POINT_COST_HIGH = 2
DEFAULT_POINT_COST_MEDIUM = 3
DEFAULT_POINT_COST_FALLBACK = 4
DEFAULT_ACCURACY_FLOOR_PCT = 85
DEFAULT_ACCURACY_HIGH_WATERMARK_PCT = 95
DEFAULT_WEEKLY_EARNING_CAP_CENTS = 9000
DEFAULT_PANEL_SIZE = 3
DEFAULT_GOLD_RATE = 0
DEFAULT_SETTLEMENT_MIN_CENTS = 1000
DEFAULT_TRAINING_REQUIRED_COUNT = 3
DEFAULT_REQUIRED_UNITS = 1
DEFAULT_REWORK_ROUND_LIMIT = 3
DEFAULT_REWORK_WINDOW_SECONDS = 900

TIER_MIN_SCORE = {"NOVICE": 5000, "PROFICIENT": 6500, "EXPERT": 8000}
TIER_MULT = {"NOVICE": 1.0, "PROFICIENT": 1.25, "EXPERT": 1.5}
CAPACITY_WEIGHT = {"STANDARD": 1, "SENSITIVE": 2, "RESTRICTED": 3}
PLAN_MULT = {"ACCEPTED": 1.0, "PROVISIONAL": 1.15, "AT_RISK": 1.35}
REWORK_POINT_MULTIPLIER = 1.2
BASE_RATE = 6
GOLD_BASE_RATE = 9
MIN_ACCURACY_PCT = 60.0
STREAK_THRESHOLD = 2
GOLD_ROTATION_THRESHOLD = 3


# --------------------------------------------------------------------------
# Numeric helpers -- every rounding in the system is round half up (PRD 2.8)
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half up to `places` decimal places; returns a Decimal."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def rhu_float(value, places=2):
    return float(round_half_up(value, places))


def pct(numerator, denominator, places=2):
    """A percentage that reads 0 when its denominator is zero (PRD 2.8)."""
    if denominator <= 0:
        return 0.0
    return rhu_float(dec(100) * dec(numerator) / dec(denominator), places)


def apply(record, **updates):
    """Assign fields, reporting whether anything actually changed."""
    changed = False
    for key, value in updates.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
    return changed


# --------------------------------------------------------------------------
# Qualifications (PRD section 2.6)
# --------------------------------------------------------------------------
def qualification_score(handle, language_code):
    """5000 + ((len(handle)*977 + sum(ord(handle))*31 + sum(ord(lang))*17) mod 5000)."""
    handle = handle or ""
    language_code = language_code or ""
    raw = (
        len(handle) * 977
        + sum(ord(ch) for ch in handle) * 31
        + sum(ord(ch) for ch in language_code) * 17
    )
    return 5000 + (raw % 5000)


def qualification_by_worker_language(worker_id, language_code):
    for qual in qualifications.values():
        if qual.get("worker_id") == worker_id and qual.get("language_code") == language_code:
            return qual
    return None


def qualification_of_commit(commit, program):
    if commit is None or program is None:
        return None
    return qualification_by_worker_language(commit.get("worker_id"), program.get("language_code"))


# --------------------------------------------------------------------------
# Derived quality metrics (PRD section 3.8)
# --------------------------------------------------------------------------
def accuracy_over(gold_commits):
    """(denominator, accepted_numerator, provisional_numerator) (PRD section 3.8).

    The denominator is the set of audits carrying a real quality outcome, so
    EXCLUDED_FROM_ACCURACY and an ungraded null sit outside both variants. Both
    variants read the same denominator and differ only in how they treat a
    FLAGGED audit: the accepted variant counts only PASSED, "so a flagged audit
    lowers it", while the provisional variant counts PASSED and FLAGGED
    together and is therefore at or above the accepted variant on every input.
    """
    denominator = 0
    accepted = 0
    provisional = 0
    for commit in gold_commits:
        outcome = commit.get("gold_outcome")
        if outcome == "PASSED":
            denominator += 1
            accepted += 1
            provisional += 1
        elif outcome == "FLAGGED":
            denominator += 1
            provisional += 1
        elif outcome == "FAILED":
            denominator += 1
    return denominator, accepted, provisional


def gold_commits_on_program(program):
    found = []
    for unit in units_of_program(program["id"]):
        for item in items_of_unit(unit["id"]):
            for commit in commits.values():
                if commit.get("item_id") == item["id"] and commit.get("kind") == "GOLD":
                    found.append(commit)
    return found


def gold_commits_on_unit(unit):
    found = []
    for item in items_of_unit(unit["id"]):
        for commit in commits.values():
            if commit.get("item_id") == item["id"] and commit.get("kind") == "GOLD":
                found.append(commit)
    return found


def refresh_qualification_metrics(qual):
    gold_rows = [
        c
        for c in commits.values()
        if c.get("qualification_id") == qual["id"] and c.get("kind") == "GOLD"
    ]
    denominator, accepted, provisional = accuracy_over(gold_rows)
    changes = {
        "gold_denominator_count": denominator,
        "accepted_gold_count": accepted,
        "provisional_gold_count": provisional,
        "accuracy_pct": pct(accepted, denominator),
        "provisional_accuracy_pct": pct(provisional, denominator),
        "restricted_accessible": qual.get("tier") == "EXPERT" and qual.get("status") == "QUALIFIED",
    }
    return apply(qual, **changes)


def refresh_program_accuracy(program):
    denominator, accepted, provisional = accuracy_over(gold_commits_on_program(program))
    changed = apply(
        program,
        accuracy_denominator_count=denominator,
        accepted_accuracy_pct=pct(accepted, denominator),
        provisional_accuracy_pct=pct(provisional, denominator),
    )
    # on_time is pinned from the logical clock at read time rather than by
    # mutating the engagement, so a plain read of an engagement does not drift
    # its version (PRD section 2.7 counts derived-field recomputation as a
    # mutation, and refreshing it on every GET would make OCC unusable).
    refresh_program_on_time(program, persist=False)
    return changed


def refresh_program_on_time(program, persist=True):
    """True when every piece that entered REWORK was eventually certified by the deadline."""
    deadline = program.get("deadline_utc")
    on_time = True
    for unit in units_of_program(program["id"]):
        for item in items_of_unit(unit["id"]):
            if int(item.get("rework_cycles", 0) or 0) <= 0:
                continue
            # A piece still sitting in rework, or one rejected rather than
            # certified, leaves the flag false.
            if item.get("consensus_status") != "CERTIFIED":
                on_time = False
                break
            certified_at = item.get("delivered_at") or item.get("updated_at")
            if (
                item.get("delivered_at") is None
                and item.get("consensus_status") == "REWORK"
            ):
                on_time = False
                break
            if deadline is not None and certified_at is not None and certified_at > deadline:
                on_time = False
                break
        if not on_time:
            break
    if not persist:
        return on_time
    return apply(program, on_time=on_time)


def refresh_worker_metrics(worker, persist=True):
    """worker_receivable_cents is an exact conserved ledger (PRD section 3.10).

    A plain read recomputes the balance without mutating the resource; only the
    write paths (payout acceptance, settlement, appeal reversal) call this with
    persist=True and then bump the worker's version themselves.
    """
    accepted = sum(
        int(c.get("paid_amount_cents", 0))
        for c in commits.values()
        if c.get("worker_id") == worker["id"] and c.get("payment_status") == "ACCEPTED"
    )
    reversed_cents = sum(
        int(c.get("reversed_amount_cents", 0))
        for c in commits.values()
        if c.get("worker_id") == worker["id"] and c.get("payment_status") == "REVERSED"
    )
    settled = int(worker.get("settled_cents", 0))
    receivable = max(0, accepted - settled + reversed_cents)
    restricted = any(
        inc.get("status") == "OPEN" for inc in incidents.values() if inc.get("worker_id") == worker["id"]
    )
    if not persist:
        return worker.get("worker_receivable_cents") != receivable
    # lifetime_earned_cents is deliberately NOT recomputed here. It is a
    # monotonic accumulator of accepted payout amounts that is never
    # decremented, not even by a reversal (§3.10), so it is advanced only by
    # accept_payout; deriving it from the current ACCEPTED rows would let a
    # reversal rewind it.
    return apply(
        worker,
        worker_receivable_cents=receivable,
        total_accepted_payout_cents=accepted,
        restricted=restricted,
    )


# --------------------------------------------------------------------------
# Units (PRD section 3.11) and programs
# --------------------------------------------------------------------------
def refresh_unit_metrics(unit):
    program = programs.get(unit.get("program_id"))
    weight = CAPACITY_WEIGHT.get((program or {}).get("sensitivity_class", "STANDARD"), 1)
    ceiling = int(unit.get("max_items", 0)) * weight
    in_rework = any(i.get("consensus_status") == "REWORK" for i in items_of_unit(unit["id"]))
    multiplier = REWORK_POINT_MULTIPLIER if in_rework else 1.0
    certified = sum(1 for i in items_of_unit(unit["id"]) if i.get("consensus_status") == "CERTIFIED")

    denominator, accepted, provisional = accuracy_over(gold_commits_on_unit(unit))
    return apply(
        unit,
        certified_item_count=certified,
        remaining_item_slots=int(unit.get("max_items", 0)) - int(unit.get("item_count", 0)),
        unit_ceiling_points=ceiling,
        unit_effective_points=rhu_int(dec(ceiling) * dec(multiplier)),
        rework_point_multiplier=float(multiplier),
        unit_accuracy_pct=pct(accepted, denominator),
        unit_provisional_accuracy_pct=pct(provisional, denominator),
    )


def accuracy_band(program, accuracy):
    floor = float(program.get("accuracy_floor_pct", DEFAULT_ACCURACY_FLOOR_PCT))
    watermark = float(program.get("accuracy_high_watermark_pct", DEFAULT_ACCURACY_HIGH_WATERMARK_PCT))
    if accuracy < floor:
        return program.get("point_cost_fallback", DEFAULT_POINT_COST_FALLBACK), True
    if accuracy < watermark:
        return program.get("point_cost_medium_accuracy", DEFAULT_POINT_COST_MEDIUM), False
    return program.get("point_cost_high_accuracy", DEFAULT_POINT_COST_HIGH), False


def variant_accuracy(program, variant):
    """The accuracy reading for a plan variant.

    AT_RISK reads the provisional variant, which is what the plan's AT_RISK
    reading uses (PRD sections 3.8 and 3.11); the default is the accepted variant.
    """
    if variant in ("PROVISIONAL", "AT_RISK"):
        return float(program.get("provisional_accuracy_pct", 0.0))
    return float(program.get("accepted_accuracy_pct", 0.0))


def refresh_program_plan(program, variant=None):
    """Recompute demand, the requirement and the derived plan flags (PRD 3.11).

    This deliberately does not touch the engagement: a recomputation is a
    mutation, so the caller applies the single version increment for the
    operation once, after every derived field has settled. Doing it here as well
    would double-count the increment named in §2.7 and §3.11.
    """
    refresh_program_accuracy(program)

    for unit in units_of_program(program["id"]):
        if refresh_unit_metrics(unit):
            touch(unit)

    demand = sum(int(u.get("unit_effective_points", 0)) for u in units_of_program(program["id"]))
    accuracy = variant_accuracy(program, variant)
    _, below_floor = accuracy_band(program, accuracy)
    multiplier = PLAN_MULT.get(variant or "ACCEPTED", 1.0)
    requirement = rhu_int(dec(demand) * dec(multiplier))
    capacity_points = int(program.get("capacity_points", DEFAULT_CAPACITY_POINTS))
    feasible = capacity_points >= requirement and not below_floor
    qa_rate = 0
    for unit in units_of_program(program["id"]):
        qa_rate = max(qa_rate, float(unit.get("gold_rate", 0) or 0))

    apply(
        program,
        demand_points=demand,
        capacity_multiplier=float(multiplier),
        capacity_requirement_points=requirement,
        capacity_feasible=feasible,
        projected_miss_deadline=not feasible,
        accuracy_floor_variant_below=below_floor,
        qa_sample_rate=qa_rate,
    )
    return program


def refresh_incident_flags(program):
    """operational_restricted / open_incident_count / incident_severity (PRD 2.5)."""
    if program is None:
        return False
    open_rows = [
        inc
        for inc in incidents.values()
        if inc.get("program_id") == program["id"] and inc.get("status") == "OPEN"
    ]
    severity_rank = {"NONE": 0, "MINOR": 1, "MAJOR": 2, "CATASTROPHIC": 3}
    worst = "NONE"
    for inc in open_rows:
        if severity_rank.get(inc.get("severity"), 0) > severity_rank.get(worst, 0):
            worst = inc.get("severity")
    return apply(
        program,
        open_incident_count=len(open_rows),
        operational_restricted=any(inc.get("severity") in ("MAJOR", "CATASTROPHIC") for inc in open_rows),
        incident_severity=worst,
    )


def refresh_worker_restricted(worker):
    return apply(
        worker,
        restricted=any(
            inc.get("status") == "OPEN" for inc in incidents.values() if inc.get("worker_id") == worker["id"]
        ),
    )


# --------------------------------------------------------------------------
# Unit activation gates (PRD sections 3.2 and 2.4)
# --------------------------------------------------------------------------
def coverage_windows_overlap(unit, program):
    """Half-open comparison: adjacency is allowed, positive length is not."""
    start_a = unit.get("coverage_start_utc")
    end_a = unit.get("coverage_end_utc")
    start_b = program.get("blackout_start_utc")
    end_b = program.get("blackout_end_utc")
    if None in (start_a, end_a, start_b, end_b):
        return False
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)
    return earliest_end > latest_start


def has_open_child_unit(unit):
    for other in spec_units.values():
        if other.get("parent_unit_id") == unit["id"] and other.get("status") not in ("ACTIVE", "COMPLETE"):
            return True
    return False


def unit_gate_failure(unit):
    """The first gate that would refuse an activation, in ladder order."""
    from errors import (
        ERR_COVERAGE_WINDOW_OVERLAP,
        ERR_EDGE_CASE_GUIDANCE_CONFLICT,
        ERR_INSTRUCTION_NOT_PUBLISHED,
        ERR_INVALID_STATE,
    )

    program = programs.get(unit.get("program_id"))
    if program is None:
        return ERR_INVALID_STATE
    # The gate set PRD §3.2 states for the open sweep names only FROZEN as a
    # blocking engagement state, so a DRAFT engagement's unit may still pass.
    if program.get("status") == "FROZEN":
        return ERR_INVALID_STATE
    if has_open_child_unit(unit):
        return ERR_INVALID_STATE
    if unit.get("instruction_status") != "PUBLISHED":
        return ERR_INSTRUCTION_NOT_PUBLISHED
    if unit.get("has_edge_case_guidance") and int(unit.get("edge_case_count", 0) or 0) > 0:
        return ERR_EDGE_CASE_GUIDANCE_CONFLICT
    if coverage_windows_overlap(unit, program):
        return ERR_COVERAGE_WINDOW_OVERLAP
    return None


def refresh_unit_piece_status(unit):
    """Keep the unit's production status in step with its attached pieces.

    A unit only shows CONSENSUS while a panel is actually in flight; once every
    panel has resolved it returns to IN_PRODUCTION unless a stronger derived
    status (CERTIFIED, REWORK, REJECTED) applies. Without this the freeze guard
    of PRD section 3.13 -- which refuses an engagement carrying a live panel --
    could never be satisfied again.
    """
    if unit is None:
        return False
    if unit.get("piece_status") not in ("IN_PRODUCTION", "CONSENSUS"):
        return False
    attached = items_of_unit(unit["id"])
    if not attached:
        return False
    # The production status derives from the pieces rather than from whether a
    # panel is currently live: a unit holding a piece in rework is REWORK, one
    # whose pieces have certified is CERTIFIED, and one whose pieces have all
    # been rejected is REJECTED. CONSENSUS is deliberately not derived here —
    # it is a status the freeze precondition reads, and PRD §3.2 never has an
    # ordinary production path write it, so a live panel leaves the unit at
    # IN_PRODUCTION until a stronger outcome arrives.
    pieces = [i.get("consensus_status") for i in attached]
    if any(s == "REWORK" for s in pieces):
        target = "REWORK"
    elif any(s == "CERTIFIED" for s in pieces):
        target = "CERTIFIED"
    elif all(s == "REJECTED" for s in pieces):
        target = "REJECTED"
    else:
        target = "IN_PRODUCTION"
    return apply(unit, piece_status=target)


def activate_unit(unit):
    """DRAFT -> ACTIVE plus the piece release cascade (PRD section 3.3)."""
    apply(unit, status="ACTIVE", piece_status="IN_PRODUCTION")
    touch(unit)
    for item in items_of_unit(unit["id"]):
        if item.get("status") == "DRAFT":
            apply(item, status="RELEASED", item_status="PENDING")
            if item.get("item_seq") is None:
                item["item_seq"] = next_item_seq(unit["id"])
            touch(item)
    refresh_unit_metrics(unit) and touch(unit)
    return unit


def next_item_seq(unit_id):
    largest = 0
    for item in items.values():
        if item.get("spec_unit_id") == unit_id and isinstance(item.get("item_seq"), int):
            largest = max(largest, item["item_seq"])
    return largest + 1


# --------------------------------------------------------------------------
# Consensus (PRD section 3.4)
# --------------------------------------------------------------------------
def committed_rows(item_id):
    """COMMITTED rows with abstained false; abstainers leave the denominator."""
    return [
        c
        for c in commits.values()
        if c.get("item_id") == item_id and c.get("status") == "COMMITTED" and c.get("abstained") is False
    ]


def value_groups(item_id):
    rows = committed_rows(item_id)
    groups = {}
    for commit in rows:
        value = commit.get("committed_value")
        group = groups.get(value)
        if group is None:
            group = {"value": value, "members": [], "min_rank": None}
            groups[value] = group
        group["members"].append(commit)
        rank = commit.get("dispatch_rank")
        rank = rank if isinstance(rank, int) else 0
        if group["min_rank"] is None or rank < group["min_rank"]:
            group["min_rank"] = rank
    ordered = sorted(groups.values(), key=lambda g: (-len(g["members"]), g["min_rank"] or 0))
    return rows, ordered


def stamp_value_groups(item):
    """Compute modal label, agreement ratio and per-commit group ranks."""
    rows, ordered = value_groups(item["id"])
    n = len(rows)
    modal = ordered[0] if ordered else None
    modal_label = modal["value"] if modal else None
    ratio = rhu_float(dec(len(modal["members"])) / dec(n), 4) if n > 0 else 0.0

    rank_of = {}
    for index, group in enumerate(ordered):
        for member in group["members"]:
            rank_of[member["id"]] = index + 1

    for commit in rows:
        commit["value_group_rank"] = rank_of.get(commit["id"])
        commit["is_modal_agent"] = bool(
            modal is not None
            and commit["id"] in [m["id"] for m in modal["members"]]
            and commit.get("dispatch_rank") == modal["min_rank"]
        )
    return n, modal_label, ratio, modal


def item_computed(item):
    """The derived fields of a piece, as a dict."""
    n = len(committed_rows(item["id"]))
    _, groups = value_groups(item["id"])
    modal = groups[0] if groups else None
    ratio = rhu_float(dec(len(modal["members"])) / dec(n), 4) if n > 0 else 0.0
    payload = {
        "non_abstaining_commit_count": n,
        "modal_label": modal["value"] if modal else None,
        "agreement_ratio": ratio,
        "gold_rotation": int(item.get("gold_audits_this_week", 0) or 0) >= GOLD_ROTATION_THRESHOLD
        and item.get("consensus_status") not in ("REWORK", "REJECTED"),
        "holds_quorum": item.get("consensus_status") == "HELD_QUORUM",
        "payout_complete": payout_complete(item),
    }
    if item.get("consensus_status") == "REWORK" and item.get("rework_started_at") is not None:
        payload["rework_window_remaining_seconds"] = int(item.get("rework_window_seconds", DEFAULT_REWORK_WINDOW_SECONDS)) - elapsed_seconds(
            item.get("rework_started_at")
        )
    else:
        payload["rework_window_remaining_seconds"] = None
    return payload


def payout_complete(item):
    """True when every COMMITTED commit is ACCEPTED or REVERSED (PRD section 3.10)."""
    rows = [c for c in commits.values() if c.get("item_id") == item["id"] and c.get("status") == "COMMITTED"]
    return all(c.get("payment_status") in ("ACCEPTED", "REVERSED") for c in rows)


def refresh_item_derived(item, persist=True):
    values = item_computed(item)
    if not persist:
        return values
    return apply(item, **values)


def pin_frozen_revision(unit, item):
    """Pin the unit's instruction revision the first time a piece certifies."""
    if unit is None or unit.get("frozen_revision") is not None:
        return False
    revisions = [i.get("instruction_revision") for i in items_of_unit(unit["id"])]
    revisions.append(item.get("instruction_revision"))
    revisions = [r for r in revisions if isinstance(r, int)]
    if not revisions:
        return False
    unit["frozen_revision"] = min(revisions)
    return True


def resolve_consensus(item):
    """The consensus resolver (PRD section 3.5)."""
    unit = spec_units.get(item.get("spec_unit_id"))
    program = programs.get(unit.get("program_id")) if unit else None
    if program is None:
        return False

    n = len(committed_rows(item["id"]))
    if n < 1:
        refresh_item_derived(item)
        return False

    quorum = int(program.get("commitment_quorum", DEFAULT_COMMITMENT_QUORUM))
    min_agreement = float(program.get("min_consensus_agreement", DEFAULT_MIN_CONSENSUS_AGREEMENT))
    ratio = item_computed(item)["agreement_ratio"]

    changed = False
    if n >= quorum and ratio >= min_agreement:
        stamp_value_groups(item)
        apply(item, consensus_status="CERTIFIED", item_status="COMPLETED", status="RESOLVED",
              holds_quorum=False)
        item["delivered_at"] = now()
        changed = True
        if pin_frozen_revision(unit, item):
            touch(unit)
    elif n >= quorum:
        apply(item, consensus_status="HELD_QUORUM", holds_quorum=True)
        changed = True
    else:
        first = earliest_commit_at(item["id"])
        patience = int(program.get("patience_seconds", DEFAULT_PATIENCE_SECONDS))
        if first is not None and elapsed_seconds(first) >= patience:
            apply(item, consensus_status="REJECTED", holds_quorum=False, item_status="COMPLETED",
                  status="RESOLVED")
            item["delivered_at"] = now()
            changed = True
        else:
            apply(item, consensus_status="AWAITING_CONSENSUS", holds_quorum=False)
            changed = True

    if refresh_item_derived(item):
        changed = True
    if changed:
        touch(item)
    if unit is not None and refresh_unit_piece_status(unit):
        touch(unit)
    maybe_complete_unit(spec_units.get(item.get("spec_unit_id")))
    refresh_program_plan(program)
    if changed:
        touch(program)
    return changed


def earliest_commit_at(item_id):
    rows = [c for c in commits.values() if c.get("item_id") == item_id and c.get("status") == "COMMITTED"]
    stamps = [c.get("dispatched_at") for c in rows if c.get("dispatched_at") is not None]
    return min(stamps) if stamps else None


def maybe_complete_unit(unit):
    """The unit completion bubble-up (PRD section 3.11)."""
    if unit is None or unit.get("status") != "ACTIVE":
        return False
    attached = items_of_unit(unit["id"])
    if not attached:
        return False
    statuses = [i.get("consensus_status") for i in attached]
    if any(s not in ("CERTIFIED", "REJECTED") for s in statuses):
        return False
    if "CERTIFIED" not in statuses:
        return False
    if any(
        not payout_complete(i) for i in attached if i.get("consensus_status") == "CERTIFIED"
    ):
        return False

    apply(unit, status="COMPLETE", piece_status="CERTIFIED")
    refresh_unit_metrics(unit)
    touch(unit)
    program = programs.get(unit.get("program_id"))
    if program is not None:
        refresh_program_plan(program)
        touch(program)
    return True


# --------------------------------------------------------------------------
# Re-dispatch and selection (PRD section 3.4)
# --------------------------------------------------------------------------
def engaged_workers_on_item(item_id):
    """Owners of existing Commit rows and of the piece's previous rework revisions."""
    blocked = set()
    for commit in commits.values():
        if commit.get("item_id") == item_id:
            blocked.add(commit.get("worker_id"))
    for commit in commits.values():
        if commit.get("superseded_on_item_id") == item_id:
            blocked.add(commit.get("worker_id"))
    return blocked


def lane_conflict(qual, program, window_start, window_end, item_id=None):
    """Closed-interval lane comparison across DIFFERENT pieces.

    PRD §3.4 states the condition as a candidate holding "no `DISPATCHED` commit
    on a different piece whose closed dispatch-to-deadline interval touches or
    overlaps this dispatch's interval". Ownership of a commit on *this* piece is
    excluded by the separate "already owns a commit on this piece" filter, so
    counting same-piece rows here would double-count them and wrongly block a
    piece's own members from serving (and from being re-selected for) its panel.
    """
    worker_id = qual.get("worker_id")
    for commit in commits.values():
        if commit.get("worker_id") != worker_id:
            continue
        if commit.get("status") != "DISPATCHED":
            continue
        if commit.get("item_id") is None:
            continue
        if item_id is not None and commit.get("item_id") == item_id:
            continue
        item = items.get(commit.get("item_id"))
        if item is None or item.get("spec_unit_id") is None:
            continue
        other_unit = spec_units.get(item.get("spec_unit_id"))
        other_program = programs.get(other_unit.get("program_id")) if other_unit else None
        if other_program is not None and other_program.get("language_code") != program.get("language_code"):
            continue
        start = commit.get("dispatched_at")
        end = commit.get("commit_deadline_at")
        if start is None or end is None:
            continue
        if start <= window_end and window_start <= end:
            return True
    return False


def eligible_qualifications(item, program, window_start, window_end, offset=0):
    """(base pool ignoring lanes, base pool minus lane-blocked members).

    PRD §3.3 fixes the panel at "the first `panel_size` members of that pool in
    ranked order" for a single dispatch, while a repeat dispatch is a distinct
    request that fulfils the panel shortfall. `offset` walks that ranked pool so
    a refill draws the next-ranked members rather than re-selecting the ones
    already dispatched.
    """
    blocked = engaged_workers_on_item(item["id"])
    base = []
    for qual in qualifications.values():
        if qual.get("language_code") != program.get("language_code"):
            continue
        if qual.get("status") not in ("QUALIFIED", "PROBATION"):
            continue
        tier_min = TIER_MIN_SCORE.get(qual.get("tier"), 5000)
        if int(qual.get("qualification_score", 0)) < tier_min:
            continue
        if program.get("sensitivity_class") == "RESTRICTED" and not qual.get("restricted_accessible"):
            continue
        worker = workers.get(qual.get("worker_id"))
        if worker is None or worker.get("restricted"):
            continue
        if qual.get("worker_id") in blocked:
            continue
        base.append(qual)

    selectable = []
    for qual in base:
        denominator = int(qual.get("gold_denominator_count", 0) or 0)
        if denominator < 3 or float(qual.get("accuracy_pct", 0.0)) >= MIN_ACCURACY_PCT:
            selectable.append(qual)

    cold_start = int(program.get("accuracy_denominator_count", 0) or 0) < 3
    key_name = "provisional_accuracy_pct" if cold_start else "accuracy_pct"
    selectable.sort(
        key=lambda q: (
            -float(q.get(key_name, 0.0)),
            -int(q.get("qualification_score", 0)),
            q.get("created_at"),
        )
    )

    free = [q for q in selectable if not lane_conflict(q, program, window_start, window_end, item["id"])]
    if offset:
        free = [q for q in free if q.get("worker_id") not in dispatched_lane(item)][offset:]
    return selectable, free


def dispatched_lane(item):
    """Workers already holding a live assignment on this piece."""
    return {
        c.get("worker_id")
        for c in commits.values()
        if c.get("item_id") == item["id"] and c.get("status") == "DISPATCHED"
    }


def dispatch_panel(item):
    """POST /api/items/{id}/dispatch-panel (PRD sections 3.3 and 3.4)."""
    from errors import (
        ERR_GOLD_ROTATION_ACTIVE,
        ERR_INVALID_STATE,
        ERR_NO_ELIGIBLE_WORKER,
        ERR_PANEL_ALREADY_DISPATCHED,
        ERR_PROGRAM_OPERATIONALLY_RESTRICTED,
        ERR_REQUIRED_UNITS_GAP,
        ERR_WORKER_LANE_CONFLICT,
        fail,
    )
    from db import new_id, seal

    unit = spec_units.get(item.get("spec_unit_id"))
    program = programs.get(unit.get("program_id")) if unit else None

    # Rank 5 -- state admissibility.
    if program is None or program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    if unit.get("status") != "ACTIVE":
        fail(ERR_INVALID_STATE)
    if unit.get("piece_status") not in ("IN_PRODUCTION", "CONSENSUS", "REWORK"):
        fail(ERR_INVALID_STATE)
    # A piece still at container status DRAFT is treated as released: it is only
    # held back by the release cascade having run before it was attached.
    if item.get("status") not in ("DRAFT", "RELEASED", "IN_PANEL"):
        fail(ERR_INVALID_STATE)

    # Rank 6 -- safety band.
    refresh_incident_flags(program)
    if program.get("operational_restricted"):
        fail(ERR_PROGRAM_OPERATIONALLY_RESTRICTED)

    # Rank 8 -- temporal band.
    required_units = item.get("required_units")
    required_units = DEFAULT_REQUIRED_UNITS if required_units is None else int(required_units)
    certified_in_unit = sum(
        1 for i in items_of_unit(unit["id"]) if i.get("consensus_status") == "CERTIFIED"
    )
    if required_units < 1 or certified_in_unit < required_units - 1:
        fail(ERR_REQUIRED_UNITS_GAP)

    window_start = now()
    deadline_seconds = int(program.get("commit_deadline_seconds", DEFAULT_COMMIT_DEADLINE_SECONDS))
    window_end = add_seconds(window_start, deadline_seconds)

    selectable, free = eligible_qualifications(item, program, window_start, window_end)
    if selectable and not free:
        fail(ERR_WORKER_LANE_CONFLICT)

    # Rank 9 -- remaining business constraints.
    if not free:
        fail(ERR_NO_ELIGIBLE_WORKER)
    if int(item.get("gold_audits_this_week", 0) or 0) >= GOLD_ROTATION_THRESHOLD and item.get(
        "consensus_status"
    ) != "REWORK":
        fail(ERR_GOLD_ROTATION_ACTIVE)
    panel_size = int(unit.get("panel_size", DEFAULT_PANEL_SIZE) or DEFAULT_PANEL_SIZE)
    committed_production = sum(
        1
        for c in commits.values()
        if c.get("item_id") == item["id"] and c.get("kind") == "PRODUCTION" and c.get("status") == "COMMITTED"
    )
    if committed_production >= panel_size:
        fail(ERR_PANEL_ALREADY_DISPATCHED)

    # The panel is the first `panel_size` members of the ranked pool (PRD §3.4).
    # The pool already excludes every worker who owns a commit on THIS piece, so
    # a second dispatch draws fresh members and tops the panel up — and if the
    # pool is exhausted the piece keeps its partial panel and simply waits for
    # quorum rather than refusing, which is what lets a two-worker pool fill
    # consecutive panels of two different pieces (PRD §3.3).
    selected = free[:panel_size]
    if selected:
        existing_ranks = [
            int(c.get("dispatch_rank") or 0)
            for c in commits.values()
            if c.get("item_id") == item["id"] and c.get("kind") == "PRODUCTION"
        ]
        _create_commits(
            item, program, selected, unit, kind="PRODUCTION",
            start_rank=(max(existing_ranks) if existing_ranks else 0) + 1,
        )
    apply(item, status="IN_PANEL", item_status="IN_REVIEW", consensus_status="AWAITING_CONSENSUS")
    refresh_item_derived(item)
    touch(item)

    refresh_unit_piece_status(unit)
    touch(unit)
    return item


def _create_commits(item, program, quals, unit, kind, start_rank):
    from db import new_id, seal

    dispatched_at = now()
    deadline = add_seconds(dispatched_at, int(program.get("commit_deadline_seconds", DEFAULT_COMMIT_DEADLINE_SECONDS)))
    created = []
    for offset, qual in enumerate(quals):
        record = {
            "item_id": item["id"],
            "worker_id": qual.get("worker_id"),
            "qualification_id": qual.get("id"),
            "kind": kind,
            "dispatch_rank": start_rank + offset,
            "payload": None,
            "committed_value": None,
            "value_group_rank": None,
            "is_modal_agent": False,
            "is_superseded": False,
            "instructions_ack": False,
            "abstained": False,
            "dispatched_at": dispatched_at,
            "commit_deadline_at": deadline,
            "gold_outcome": None,
            "gold_task_key": None,
            "expected_value": None,
            "eligible_outcomes": None,
            "selected_anchor_commit_id": None,
            "paid_amount_cents": 0,
            "payment_status": "UNPAID",
            "payment_capped": False,
            "week_epoch_index": None,
            "reversed_amount_cents": 0,
            "superseded_on_item_id": None,
            "status": "DISPATCHED",
        }
        seal(record)
        commits[record["id"]] = record
        created.append(record)
    return created


def fresh_panel_member(item, program, unit, rank):
    """One fresh member drawn from the selector, excluding every prior owner."""
    window_start = now()
    deadline = add_seconds(window_start, int(program.get("commit_deadline_seconds", DEFAULT_COMMIT_DEADLINE_SECONDS)))
    selectable, free = eligible_qualifications(item, program, window_start, deadline)
    pool = free if free else selectable
    if not pool:
        return None
    chosen = pool[0]
    created = _create_commits(item, program, [chosen], unit, kind="PRODUCTION", start_rank=rank)
    return created[0]


# --------------------------------------------------------------------------
# Rework (PRD section 3.6)
# --------------------------------------------------------------------------
def winning_group_lowest_rank(item):
    _, groups = value_groups(item["id"])
    if not groups:
        return None
    modal = groups[0]
    members = sorted(modal["members"], key=lambda c: c.get("dispatch_rank") or 0)
    return members[0] if members else None


def open_rework(item, reviewer_id):
    from errors import ERR_INVALID_STATE, ERR_REWORK_ROUND_LIMIT, ERR_SEGREGATION_OF_DUTIES, fail
    from auth import reviewer_holds_commit

    if item.get("consensus_status") not in ("CERTIFIED", "HELD_QUORUM"):
        fail(ERR_INVALID_STATE)
    if int(item.get("rework_cycles", 0)) >= int(item.get("rework_round_limit", DEFAULT_REWORK_ROUND_LIMIT)):
        fail(ERR_REWORK_ROUND_LIMIT)
    if reviewer_holds_commit(reviewer_id, item["id"]):
        fail(ERR_SEGREGATION_OF_DUTIES)

    unit = spec_units.get(item.get("spec_unit_id"))
    program = programs.get(unit.get("program_id")) if unit else None

    apply(item, consensus_status="REWORK", item_status="REWORK", status="IN_PANEL")
    item["rework_cycles"] = int(item.get("rework_cycles", 0)) + 1
    item["rework_started_at"] = now()
    item["gold_audits_this_week"] = 0
    item["delivered_at"] = None

    superseded = winning_group_lowest_rank(item)
    if superseded is not None:
        superseded["is_superseded"] = True
        superseded["superseded_on_item_id"] = item["id"]
        touch(superseded)

    unit_panel_size = int((unit or {}).get("panel_size", DEFAULT_PANEL_SIZE) or DEFAULT_PANEL_SIZE)
    if program is not None and unit is not None:
        fresh_panel_member(item, program, unit, int(item["rework_cycles"]) + unit_panel_size)

    refresh_item_derived(item)
    touch(item)
    if unit is not None:
        refresh_unit_piece_status(unit)
        refresh_unit_metrics(unit)
        touch(unit)
    return item


def submit_rework(item, commit_id, payload, instructions_ack):
    from errors import (
        ERR_COMMIT_NOT_FOUND,
        ERR_FIELD_SCHEMA_MISMATCH,
        ERR_INSTRUCTION_REVISION_MISMATCH,
        ERR_PROGRAM_OPERATIONALLY_RESTRICTED,
        ERR_REWORK_WINDOW_EXPIRED,
        ERR_WORKER_RESTRICTED,
        fail,
    )

    commit = commits.get(commit_id)
    if commit is None or commit.get("item_id") != item["id"]:
        fail(ERR_COMMIT_NOT_FOUND)

    unit = spec_units.get(item.get("spec_unit_id"))
    program = programs.get(unit.get("program_id")) if unit else None

    # Rank 6 -- the safety band reaches both label commitment and rework hand-in.
    worker = workers.get(commit.get("worker_id"))
    refresh_worker_restricted(worker)
    if worker is not None and worker.get("restricted"):
        fail(ERR_WORKER_RESTRICTED)
    if program is not None:
        refresh_incident_flags(program)
        if program.get("operational_restricted"):
            fail(ERR_PROGRAM_OPERATIONALLY_RESTRICTED)

    remaining = item.get("rework_window_remaining_seconds")
    if remaining is None:
        remaining = int(item.get("rework_window_seconds", DEFAULT_REWORK_WINDOW_SECONDS)) - elapsed_seconds(
            item.get("rework_started_at")
        )
    if remaining <= 0:
        fail(ERR_REWORK_WINDOW_EXPIRED)

    if not instructions_ack:
        fail(ERR_FIELD_SCHEMA_MISMATCH, "instructions_ack must be true on every answer.")

    schema = list(unit.get("field_schema") or [])
    if not isinstance(payload, dict) or set(payload.keys()) != set(schema):
        fail(ERR_FIELD_SCHEMA_MISMATCH)

    if unit.get("frozen_revision") is not None and commit.get("instruction_revision") is not None:
        if commit.get("instruction_revision") != unit.get("frozen_revision"):
            fail(ERR_INSTRUCTION_REVISION_MISMATCH)

    previous_modal = item_computed(item)["modal_label"]

    commit["payload"] = payload
    commit["committed_value"] = canonical_value(payload, schema)
    commit["is_superseded"] = False
    commit["superseded_on_item_id"] = None
    commit["status"] = "COMMITTED"
    commit["abstained"] = False
    touch(commit)

    _, new_modal_label, _, _ = stamp_value_groups(item)
    if previous_modal is not None and new_modal_label == previous_modal:
        apply(item, consensus_status="CERTIFIED", item_status="COMPLETED", status="RESOLVED", holds_quorum=False)
        item["delivered_at"] = now()
    else:
        apply(item, consensus_status="HELD_QUORUM", holds_quorum=True)
    refresh_item_derived(item)
    touch(item)

    if unit is not None:
        refresh_unit_metrics(unit)
        touch(unit)
    if program is not None:
        refresh_program_plan(program)
        touch(program)
        maybe_complete_unit(unit)
    return item


def canonical_value(payload, schema):
    """Canonical string of the payload's first schema field value."""
    if not isinstance(payload, dict) or not schema:
        return None
    first = schema[0]
    if first not in payload:
        return None
    value = payload[first]
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return None
    return str(value)


def rework_timeout_sweep():
    """The unattended-round roll and the terminal rejection (PRD section 3.6)."""
    for item in list(items.values()):
        if item.get("consensus_status") != "REWORK":
            continue
        window = int(item.get("rework_window_seconds", DEFAULT_REWORK_WINDOW_SECONDS))
        if elapsed_seconds(item.get("rework_started_at")) < window:
            continue
        limit = int(item.get("rework_round_limit", DEFAULT_REWORK_ROUND_LIMIT))
        if int(item.get("rework_cycles", 0)) < limit:
            item["rework_cycles"] = int(item.get("rework_cycles", 0)) + 1
            item["rework_started_at"] = now()
            for commit in commits.values():
                if commit.get("superseded_on_item_id") == item["id"] and commit.get("is_superseded"):
                    commit["is_superseded"] = False
                    touch(commit)
            refresh_item_derived(item)
            touch(item)
        else:
            apply(item, consensus_status="REJECTED", holds_quorum=False, item_status="COMPLETED",
                  status="RESOLVED")
            refresh_item_derived(item)
            touch(item)
            unit = spec_units.get(item.get("spec_unit_id"))
            if unit is not None:
                attached = items_of_unit(unit["id"])
                if attached and all(i.get("consensus_status") == "REJECTED" for i in attached):
                    apply(unit, piece_status="REJECTED")
                    touch(unit)
                refresh_unit_metrics(unit)
                program = programs.get(unit.get("program_id"))
                if program is not None:
                    refresh_program_plan(program)
                    touch(program)


def quorum_timeout_sweep():
    """Hold expiry and quorum rejection when the clock moves (PRD sections 2.9, 3.5)."""
    for item in list(items.values()):
        if item.get("consensus_status") not in ("AWAITING_CONSENSUS", "HELD_QUORUM"):
            continue
        resolve_consensus(item)


# --------------------------------------------------------------------------
# Pay (PRD section 3.10)
# --------------------------------------------------------------------------
def computed_amount_cents(commit, program, qualification, variant=None):
    """The dynamic rate, with exactly one rounding site (PRD section 3.10)."""
    base = GOLD_BASE_RATE if commit.get("kind") == "GOLD" else BASE_RATE
    streak = int(qualification.get("gold_fail_streak", 0) or 0)
    if streak <= 1:
        m_streak = 1.0
    elif streak == STREAK_THRESHOLD:
        m_streak = 0.8
    else:
        m_streak = 0.5
    m_tier = TIER_MULT.get(qualification.get("tier"), 1.0)

    worker = workers.get(commit.get("worker_id"))
    lifetime = int((worker or {}).get("lifetime_earned_cents", 0) or 0)

    if variant == "PROVISIONAL":
        decay = max(0.5, 1 - (lifetime // 10000) * 0.05)
        unrounded = dec(base) * dec(m_streak) * dec(decay) * dec(m_tier)
    else:
        unrounded = dec(base) * dec(m_streak) * dec(m_tier)

    uncapped = rhu_int(unrounded)

    if variant == "PROVISIONAL":
        return uncapped, False, unrounded

    epoch_index = current_epoch_index()
    settled = sum(
        int(c.get("paid_amount_cents", 0))
        for c in commits.values()
        if c.get("worker_id") == commit.get("worker_id")
        and c.get("payment_status") == "ACCEPTED"
        and c.get("week_epoch_index") == epoch_index
    )
    remaining = max(0, int(program.get("weekly_earning_cap_cents", DEFAULT_WEEKLY_EARNING_CAP_CENTS)) - settled)
    amount = min(uncapped, remaining)
    capped = uncapped > remaining
    return amount, capped, unrounded


def accept_payout(commit, amount_cents, currency):
    from errors import (
        ERR_CURRENCY_MISMATCH,
        ERR_PAYMENT_AMOUNT_MISMATCH,
        ERR_WORKER_RESTRICTED,
        ERR_INVALID_STATE,
        fail,
    )

    item = items.get(commit.get("item_id"))
    unit = spec_units.get(item.get("spec_unit_id")) if item else None
    program = programs.get(unit.get("program_id")) if unit else None
    if program is None or item is None:
        fail(ERR_INVALID_STATE)
    if program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    if commit.get("status") != "COMMITTED":
        fail(ERR_INVALID_STATE)

    worker = workers.get(commit.get("worker_id"))
    refresh_worker_restricted(worker)
    if worker is not None and worker.get("restricted"):
        fail(ERR_WORKER_RESTRICTED)

    qualification = qualification_of_commit(commit, program)
    expected, capped, _ = computed_amount_cents(commit, program, qualification)
    if int(amount_cents) != int(expected):
        fail(ERR_PAYMENT_AMOUNT_MISMATCH)
    if currency != worker.get("payout_currency"):
        fail(ERR_CURRENCY_MISMATCH)

    epoch_index = current_epoch_index()
    commit["paid_amount_cents"] = int(expected)
    commit["payment_status"] = "ACCEPTED"
    commit["payment_capped"] = bool(capped)
    commit["week_epoch_index"] = epoch_index
    touch(commit)

    refresh_worker_metrics(worker)
    # The accepted amount advances the monotonic lifetime accumulator; a later
    # reversal credits the receivable without rewinding this (§3.10).
    worker["lifetime_earned_cents"] = int(worker.get("lifetime_earned_cents", 0) or 0) + int(expected)
    touch(worker)

    refresh_item_derived(item)
    touch(item)

    # The accepted payout may fire the quality embargo (PRD section 3.13).
    if program.get("status") == "ACTIVE":
        refresh_program_accuracy(program)
        if (
            int(program.get("accuracy_denominator_count", 0)) >= 1
            and float(program.get("accepted_accuracy_pct", 0.0))
            < float(program.get("accuracy_floor_pct", DEFAULT_ACCURACY_FLOOR_PCT))
        ):
            fire_quality_embargo(program)
    refresh_program_plan(program)
    maybe_complete_unit(unit)
    return commit


def fire_quality_embargo(program):
    """ACTIVE -> QUALITY_EMBARGO with its three-hop cascade (PRD section 3.13)."""
    if program.get("status") != "ACTIVE":
        return False
    apply(program, status="QUALITY_EMBARGO")
    touch(program)
    for unit in units_of_program(program["id"]):
        if unit.get("status") != "ACTIVE":
            continue
        apply(unit, piece_status="REWORK")
        touch(unit)
        for item in items_of_unit(unit["id"]):
            if item.get("consensus_status") == "AWAITING_CONSENSUS":
                apply(item, consensus_status="REWORK", item_status="REWORK")
                item["rework_cycles"] = int(item.get("rework_cycles", 0)) + 1
                item["rework_started_at"] = now()
                refresh_item_derived(item)
                touch(item)
        refresh_unit_metrics(unit)
    return True


def settle(worker, amount_cents, currency):
    from errors import ERR_CURRENCY_MISMATCH, ERR_INSUFFICIENT_RECEIVABLE, ERR_WORKER_RESTRICTED, fail

    refresh_worker_restricted(worker)
    refresh_worker_metrics(worker, persist=False)
    if worker.get("restricted"):
        fail(ERR_WORKER_RESTRICTED)
    if currency != worker.get("payout_currency"):
        fail(ERR_CURRENCY_MISMATCH)
    receivable = int(worker.get("worker_receivable_cents", 0))
    if receivable < int(worker.get("settlement_min_cents", DEFAULT_SETTLEMENT_MIN_CENTS)):
        fail(ERR_INSUFFICIENT_RECEIVABLE)
    if int(amount_cents) > receivable:
        fail(ERR_INSUFFICIENT_RECEIVABLE)
    worker["settled_cents"] = int(worker.get("settled_cents", 0)) + int(amount_cents)
    refresh_worker_metrics(worker)
    touch(worker)
    return worker


# --------------------------------------------------------------------------
# Gold audits and grading (PRD sections 3.7, 3.8, 3.9)
# --------------------------------------------------------------------------
def choose_anchor(item):
    """The committed panel member whose payload supplies the ground truth.

    PRD §3.7 has the audit inherit "the customer's ground truth" by copying a
    committed member's payload, and keeps that reference "reproducible and
    independent of the order in which answers arrived". The anchor is therefore
    pinned to the earliest-dispatched member rather than to whatever the value
    groups currently rank first, so a panel held on a dispute still anchors to a
    stable answer.
    """
    rows = committed_rows(item["id"])
    if not rows:
        return None
    ordered = sorted(rows, key=lambda c: (c.get("dispatch_rank") or 0, c.get("created_at")))
    return ordered[0]


def create_gold_audit(item, gold_task_key):
    from errors import (
        ERR_INVALID_STATE,
        ERR_NO_ELIGIBLE_WORKER,
        ERR_PROGRAM_OPERATIONALLY_RESTRICTED,
        fail,
    )

    unit = spec_units.get(item.get("spec_unit_id"))
    program = programs.get(unit.get("program_id")) if unit else None
    if program is None or program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    refresh_incident_flags(program)
    if program.get("operational_restricted"):
        fail(ERR_PROGRAM_OPERATIONALLY_RESTRICTED)

    anchor = choose_anchor(item)
    if anchor is None:
        fail(ERR_INVALID_STATE)

    # The audit may be served by any eligible qualification, including the one
    # that owns the anchored member: PRD §3.7 pins the ground truth from the
    # anchor member's payload but places no constraint on which qualification
    # receives the GOLD assignment, and §3.4's candidate filter is a
    # production-panel rule. The reviewer's segregation guard is a separate
    # check on the acting X-User-ID, not on the auditor drawn here. A pool that
    # is genuinely empty is the reserved ERR_NO_ELIGIBLE_WORKER case, not a
    # state refusal.
    auditor = _select_gold_auditor(item, program, anchor)
    if auditor is None:
        fail(ERR_NO_ELIGIBLE_WORKER)

    vocabulary = list(GOLD_OUTCOME_BASE)
    if program.get("instruction_model") == "SAFETY_CLASSIFICATION":
        vocabulary = ["PASSED", "FAILED", "FLAGGED", "EXCLUDED_FROM_ACCURACY"]

    audit = {
        "item_id": item["id"],
        "worker_id": auditor.get("worker_id"),
        "qualification_id": auditor.get("id"),
        "kind": "GOLD",
        "dispatch_rank": (max([c.get("dispatch_rank") or 0 for c in commits.values() if c.get("item_id") == item["id"]] or [0]) + 1),
        "payload": None,
        "committed_value": None,
        "value_group_rank": None,
        "is_modal_agent": False,
        "is_superseded": False,
        "instructions_ack": True,
        "abstained": False,
        "dispatched_at": now(),
        "commit_deadline_at": add_seconds(
            now(), int(program.get("commit_deadline_seconds", DEFAULT_COMMIT_DEADLINE_SECONDS))
        ),
        "gold_outcome": None,
        "gold_task_key": gold_task_key,
        "expected_value": anchor.get("committed_value"),
        "eligible_outcomes": vocabulary,
        "selected_anchor_commit_id": anchor["id"],
        "paid_amount_cents": 0,
        "payment_status": "UNPAID",
        "payment_capped": False,
        "week_epoch_index": None,
        "reversed_amount_cents": 0,
        "superseded_on_item_id": None,
        "status": "DISPATCHED",
    }
    from db import seal

    seal(audit)
    commits[audit["id"]] = audit

    item["gold_audits_this_week"] = int(item.get("gold_audits_this_week", 0) or 0) + 1
    auditor["gold_audits_dispatched"] = int(auditor.get("gold_audits_dispatched", 0)) + 1
    touch(auditor)
    refresh_item_derived(item)
    touch(item)
    return audit


def _select_gold_auditor(item, program, anchor):
    """An eligible qualification to serve the gold audit.

    The anchor member's own qualification is admitted when no other candidate
    exists, because PRD §3.7 constrains only where the ground truth comes from
    and how the audit is graded, never who receives it.
    """
    window_start = now()
    deadline = add_seconds(
        window_start, int(program.get("commit_deadline_seconds", DEFAULT_COMMIT_DEADLINE_SECONDS))
    )
    pool = []
    for qual in qualifications.values():
        if qual.get("language_code") != program.get("language_code"):
            continue
        if qual.get("status") not in ("QUALIFIED", "PROBATION"):
            continue
        if int(qual.get("qualification_score", 0)) < TIER_MIN_SCORE.get(qual.get("tier"), 5000):
            continue
        if program.get("sensitivity_class") == "RESTRICTED" and not qual.get("restricted_accessible"):
            continue
        worker = workers.get(qual.get("worker_id"))
        if worker is None or worker.get("restricted"):
            continue
        if lane_conflict(qual, program, window_start, deadline, item["id"]):
            continue
        pool.append(qual)

    candidates = [q for q in pool if q.get("worker_id") != anchor.get("worker_id")]
    if not candidates:
        candidates = pool
    if not candidates:
        return None

    cold_start = int(program.get("accuracy_denominator_count", 0) or 0) < 3
    key_name = "provisional_accuracy_pct" if cold_start else "accuracy_pct"
    candidates.sort(
        key=lambda q: (
            -float(q.get(key_name, 0.0)),
            -int(q.get("qualification_score", 0)),
            q.get("created_at"),
        )
    )
    return candidates[0]


def grade_audit(audit, outcome, reviewer_id):
    from auth import reviewer_holds_commit
    from errors import ERR_SEGREGATION_OF_DUTIES, ERR_INVALID_REQUEST, fail

    item = items.get(audit.get("item_id"))
    unit = spec_units.get(item.get("spec_unit_id")) if item else None
    program = programs.get(unit.get("program_id")) if unit else None
    if program is None:
        fail(ERR_INVALID_REQUEST)

    if reviewer_holds_commit(reviewer_id, item["id"]):
        fail(ERR_SEGREGATION_OF_DUTIES)

    if outcome not in GOLD_OUTCOMES:
        fail(ERR_INVALID_REQUEST)

    # PRD §3.7: grading "updates the auditing worker's qualification streak and
    # cyclic status". The audit measures the anchored answer, so the streak is
    # carried on the qualification of that answer's author rather than on the
    # qualification of the reviewer-side auditor who merely served the audit.
    anchor = commits.get(audit.get("selected_anchor_commit_id"))
    qualification = qualifications.get(
        (anchor or {}).get("qualification_id") or audit.get("qualification_id")
    )
    audit["gold_outcome"] = outcome
    touch(audit)

    if qualification is not None:
        if outcome == "PASSED":
            qualification["gold_fail_streak"] = 0
        elif outcome == "FAILED":
            streak = int(qualification.get("gold_fail_streak", 0) or 0) + 1
            qualification["gold_fail_streak"] = streak
            if streak >= STREAK_THRESHOLD and qualification.get("status") == "QUALIFIED":
                qualification["status"] = "PROBATION"
        refresh_qualification_metrics(qualification)
        if qualification.get("status") == "IN_TRAINING" and int(
            qualification.get("qualification_score", 0)
        ) < TIER_MIN_SCORE.get(qualification.get("tier"), 5000):
            qualification["status"] = "REVOKED"
            withdraw_qualification_commits(qualification)
        refresh_qualification_metrics(qualification)
        touch(qualification)

    refresh_item_derived(item)
    touch(item)
    if unit is not None:
        refresh_unit_metrics(unit)
        touch(unit)
    refresh_program_plan(program)
    touch(program)
    return audit


def withdraw_qualification_commits(qualification):
    """Withdraw every uncommitted Commit on this qualification (PRD section 3.9)."""
    for commit in list(commits.values()):
        if commit.get("qualification_id") != qualification["id"]:
            continue
        if commit.get("status") != "DISPATCHED":
            continue
        item = items.get(commit.get("item_id"))
        if item is None:
            continue
        if item.get("status") in ("RESOLVED",):
            continue
        commit["status"] = "COMMIT_EXPIRED"
        touch(commit)
        refresh_item_derived(item)
        if item.get("consensus_status") == "AWAITING_CONSENSUS" and len(committed_rows(item["id"])) == 0:
            pass
        touch(item)


def withdraw_worker_dispatched_commits(worker_id):
    """Withdraw DISPATCHED commits on non-terminal pieces (PRD section 3.9)."""
    for commit in list(commits.values()):
        if commit.get("worker_id") != worker_id or commit.get("status") != "DISPATCHED":
            continue
        item = items.get(commit.get("item_id"))
        if item is None or item.get("status") == "RESOLVED":
            continue
        commit["status"] = "COMMIT_EXPIRED"
        touch(commit)
        refresh_item_derived(item)
        if len(committed_rows(item["id"])) == 0:
            apply(item, consensus_status="AWAITING_CONSENSUS")
        touch(item)


# --------------------------------------------------------------------------
# Appeals (PRD section 3.12)
# --------------------------------------------------------------------------
def appeal_deadlock_sweep():
    for claim in list(appeals.values()):
        if claim.get("status") != "ADJUDICATION":
            continue
        entered = claim.get("adjudication_started_at")
        program = programs.get(claim.get("program_id"))
        patience = int((program or {}).get("patience_seconds", DEFAULT_PATIENCE_SECONDS))
        if entered is not None and elapsed_seconds(entered) >= patience:
            apply(claim, status="DEADLOCK", consensus_outcome="DEADLOCKED")
            touch(claim)
            item = items.get(claim.get("item_id"))
            if item is not None:
                apply(item, holds_quorum=False)
                refresh_item_derived(item)
                touch(item)


# --------------------------------------------------------------------------
# Freeze (PRD section 3.13)
# --------------------------------------------------------------------------
def freeze_program(program):
    """FROZEN cascade; the caller applies the single program version increment."""
    apply(program, status="FROZEN")
    for unit in units_of_program(program["id"]):
        apply(unit, status="REJECTED", piece_status="REJECTED")
        touch(unit)
        for item in items_of_unit(unit["id"]):
            apply(item, status="RESOLVED", item_status="COMPLETED", consensus_status="REJECTED")
            refresh_item_derived(item)
            touch(item)
    for commit in commits.values():
        item = items.get(commit.get("item_id"))
        if item is None:
            continue
        unit = spec_units.get(item.get("spec_unit_id"))
        if unit is None or unit.get("program_id") != program["id"]:
            continue
        if commit.get("status") == "DISPATCHED":
            commit["status"] = "COMMIT_EXPIRED"
            touch(commit)
    for item in items.values():
        unit = spec_units.get(item.get("spec_unit_id"))
        if unit is not None and unit.get("program_id") == program["id"]:
            refresh_item_derived(item)
    return program


# --------------------------------------------------------------------------
# Week epoch roll (PRD section 2.9)
# --------------------------------------------------------------------------
def roll_week_epoch(instant):
    """Close the open epoch and open the next one with the supplied instant."""
    epoch = open_epoch()
    if instant <= epoch.get("starts_at_utc"):
        return epoch, False
    epoch["status"] = "CLOSED"
    touch(epoch)
    from db import seal, week_epochs

    record = {
        "index": int(epoch.get("index", 0)) + 1,
        "name": None,
        "starts_at_utc": instant,
        "status": "OPEN",
    }
    seal(record)
    week_epochs[record["id"]] = record
    for program in programs.values():
        program["current_week_epoch_index"] = record["index"]
        touch(program)
    for item in items.values():
        if int(item.get("gold_audits_this_week", 0) or 0) != 0:
            item["gold_audits_this_week"] = 0
            refresh_item_derived(item)
            touch(item)
    return record, True


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
def program_view(program, variant=None):
    # A plain read recomputes the derived fields without touching the resource,
    # so an engagement read is not a mutation of the engagement (PRD §2.7).
    refresh_program_plan(program, variant)
    refresh_incident_flags(program)
    return {
        "id": program["id"],
        "created_at": iso(program.get("created_at")),
        "updated_at": iso(program.get("updated_at")),
        "version": program.get("version"),
        "program_code": program.get("program_code"),
        "name": program.get("name"),
        "language_code": program.get("language_code"),
        "instruction_model": program.get("instruction_model"),
        "sensitivity_class": program.get("sensitivity_class"),
        "incident_severity": program.get("incident_severity"),
        "open_incident_count": program.get("open_incident_count"),
        "operational_restricted": program.get("operational_restricted"),
        "min_consensus_agreement": program.get("min_consensus_agreement"),
        "commitment_quorum": program.get("commitment_quorum"),
        "commit_deadline_seconds": program.get("commit_deadline_seconds"),
        "weekly_earning_cap_cents": program.get("weekly_earning_cap_cents"),
        "patience_seconds": program.get("patience_seconds"),
        "deadline_utc": iso(program.get("deadline_utc")),
        "blackout_start_utc": iso(program.get("blackout_start_utc")),
        "blackout_end_utc": iso(program.get("blackout_end_utc")),
        "coverage_hours": program.get("coverage_hours"),
        "capacity_points": program.get("capacity_points"),
        "point_cost_high_accuracy": program.get("point_cost_high_accuracy"),
        "point_cost_medium_accuracy": program.get("point_cost_medium_accuracy"),
        "point_cost_fallback": program.get("point_cost_fallback"),
        "accuracy_floor_pct": program.get("accuracy_floor_pct"),
        "accuracy_high_watermark_pct": program.get("accuracy_high_watermark_pct"),
        "demand_points": program.get("demand_points"),
        "capacity_requirement_points": program.get("capacity_requirement_points"),
        "capacity_multiplier": program.get("capacity_multiplier"),
        "capacity_feasible": program.get("capacity_feasible"),
        "projected_miss_deadline": program.get("projected_miss_deadline"),
        "accuracy_floor_variant_below": program.get("accuracy_floor_variant_below"),
        "accepted_accuracy_pct": program.get("accepted_accuracy_pct"),
        "provisional_accuracy_pct": program.get("provisional_accuracy_pct"),
        "accuracy_denominator_count": program.get("accuracy_denominator_count"),
        "on_time": program.get("on_time"),
        "qa_sample_rate": program.get("qa_sample_rate"),
        "current_week_epoch_index": program.get("current_week_epoch_index"),
        "status": program.get("status"),
    }


def unit_view(unit):
    refresh_unit_metrics(unit)
    return {
        "id": unit["id"],
        "created_at": iso(unit.get("created_at")),
        "updated_at": iso(unit.get("updated_at")),
        "version": unit.get("version"),
        "program_id": unit.get("program_id"),
        "unit_code": unit.get("unit_code"),
        "parent_unit_id": unit.get("parent_unit_id"),
        "max_items": unit.get("max_items"),
        "item_count": unit.get("item_count"),
        "instruction_revision": unit.get("instruction_revision"),
        "instruction_status": unit.get("instruction_status"),
        "has_edge_case_guidance": unit.get("has_edge_case_guidance"),
        "edge_case_count": unit.get("edge_case_count"),
        "field_schema": unit.get("field_schema"),
        "panel_size": unit.get("panel_size"),
        "gold_rate": unit.get("gold_rate"),
        "coverage_start_utc": iso(unit.get("coverage_start_utc")),
        "coverage_end_utc": iso(unit.get("coverage_end_utc")),
        "piece_status": unit.get("piece_status"),
        "frozen_revision": unit.get("frozen_revision"),
        "certified_item_count": unit.get("certified_item_count"),
        "remaining_item_slots": unit.get("remaining_item_slots"),
        "unit_ceiling_points": unit.get("unit_ceiling_points"),
        "unit_effective_points": unit.get("unit_effective_points"),
        "rework_point_multiplier": unit.get("rework_point_multiplier"),
        "unit_accuracy_pct": unit.get("unit_accuracy_pct"),
        "unit_provisional_accuracy_pct": unit.get("unit_provisional_accuracy_pct"),
        "status": unit.get("status"),
    }


def item_view(item):
    values = item_computed(item)
    apply(item, **values)
    program = None
    unit = spec_units.get(item.get("spec_unit_id"))
    if unit is not None:
        program = programs.get(unit.get("program_id"))
    data = {
        "id": item["id"],
        "created_at": iso(item.get("created_at")),
        "updated_at": iso(item.get("updated_at")),
        "version": item.get("version"),
        "spec_unit_id": item.get("spec_unit_id"),
        "item_key": item.get("item_key"),
        "item_seq": item.get("item_seq"),
        "payload_uri": item.get("payload_uri"),
        "required_units": item.get("required_units"),
        "instruction_revision": item.get("instruction_revision"),
        "item_status": item.get("item_status"),
        "consensus_status": item.get("consensus_status"),
        "non_abstaining_commit_count": item.get("non_abstaining_commit_count"),
        "modal_label": item.get("modal_label"),
        "agreement_ratio": item.get("agreement_ratio"),
        "gold_audits_this_week": item.get("gold_audits_this_week"),
        "gold_rotation": item.get("gold_rotation"),
        "holds_quorum": item.get("holds_quorum"),
        "rework_cycles": item.get("rework_cycles"),
        "rework_round_limit": item.get("rework_round_limit"),
        "rework_started_at": iso(item.get("rework_started_at")),
        "rework_window_seconds": item.get("rework_window_seconds"),
        "rework_window_remaining_seconds": item.get("rework_window_remaining_seconds"),
        "payout_complete": item.get("payout_complete"),
        "status": item.get("status"),
    }
    if program is not None and program.get("sensitivity_class") in ("SENSITIVE", "RESTRICTED"):
        data.pop("payload_uri", None)
    return data


def commit_view(commit):
    return {
        "id": commit["id"],
        "created_at": iso(commit.get("created_at")),
        "updated_at": iso(commit.get("updated_at")),
        "version": commit.get("version"),
        "item_id": commit.get("item_id"),
        "worker_id": commit.get("worker_id"),
        "qualification_id": commit.get("qualification_id"),
        "kind": commit.get("kind"),
        "dispatch_rank": commit.get("dispatch_rank"),
        "payload": commit.get("payload"),
        "committed_value": commit.get("committed_value"),
        "value_group_rank": commit.get("value_group_rank"),
        "is_modal_agent": commit.get("is_modal_agent"),
        "is_superseded": commit.get("is_superseded"),
        "instructions_ack": commit.get("instructions_ack"),
        "abstained": commit.get("abstained"),
        "dispatched_at": iso(commit.get("dispatched_at")),
        "commit_deadline_at": iso(commit.get("commit_deadline_at")),
        "gold_outcome": commit.get("gold_outcome"),
        "expected_value": commit.get("expected_value"),
        "eligible_outcomes": commit.get("eligible_outcomes"),
        "selected_anchor_commit_id": commit.get("selected_anchor_commit_id"),
        "paid_amount_cents": commit.get("paid_amount_cents"),
        "payment_status": commit.get("payment_status"),
        "payment_capped": commit.get("payment_capped"),
        "week_epoch_index": commit.get("week_epoch_index"),
        "status": commit.get("status"),
    }


def worker_view(worker, earnings_variant=None):
    refresh_worker_metrics(worker, persist=False)
    data = {
        "id": worker["id"],
        "created_at": iso(worker.get("created_at")),
        "updated_at": iso(worker.get("updated_at")),
        "version": worker.get("version"),
        "handle": worker.get("handle"),
        "display_name": worker.get("display_name"),
        "payout_currency": worker.get("payout_currency"),
        "settlement_min_cents": worker.get("settlement_min_cents"),
        "lifetime_earned_cents": worker.get("lifetime_earned_cents"),
        "worker_receivable_cents": worker.get("worker_receivable_cents"),
        "restricted": worker.get("restricted"),
        "total_accepted_payout_cents": worker.get("total_accepted_payout_cents"),
    }
    if earnings_variant == "PROVISIONAL":
        data["provisional_earnings_cents"] = provisional_earnings(worker)
    return data


def provisional_earnings(worker):
    """The provisional per-commit reading with the lifetime decay factor applied."""
    total = 0
    for commit in commits.values():
        if commit.get("worker_id") != worker["id"]:
            continue
        item = items.get(commit.get("item_id"))
        unit = spec_units.get(item.get("spec_unit_id")) if item else None
        program = programs.get(unit.get("program_id")) if unit else None
        qualification = qualification_of_commit(commit, program) if program else None
        if qualification is None:
            continue
        amount, _, _ = computed_amount_cents(commit, program, qualification, variant="PROVISIONAL")
        total += amount
    return total


def qualification_view(qual):
    refresh_qualification_metrics(qual)
    return {
        "id": qual["id"],
        "created_at": iso(qual.get("created_at")),
        "updated_at": iso(qual.get("updated_at")),
        "version": qual.get("version"),
        "worker_id": qual.get("worker_id"),
        "language_code": qual.get("language_code"),
        "tier": qual.get("tier"),
        "qualification_score": qual.get("qualification_score"),
        "tier_min_score": qual.get("tier_min_score"),
        "tier_multiplier": qual.get("tier_multiplier"),
        "gold_audits_dispatched": qual.get("gold_audits_dispatched"),
        "gold_denominator_count": qual.get("gold_denominator_count"),
        "accepted_gold_count": qual.get("accepted_gold_count"),
        "provisional_gold_count": qual.get("provisional_gold_count"),
        "accuracy_pct": qual.get("accuracy_pct"),
        "provisional_accuracy_pct": qual.get("provisional_accuracy_pct"),
        "training_passed_count": qual.get("training_passed_count"),
        "training_required_count": qual.get("training_required_count"),
        "gold_fail_streak": qual.get("gold_fail_streak"),
        "restricted_accessible": qual.get("restricted_accessible"),
        "status": qual.get("status"),
    }


def incident_view(incident):
    return {
        "id": incident["id"],
        "created_at": iso(incident.get("created_at")),
        "updated_at": iso(incident.get("updated_at")),
        "version": incident.get("version"),
        "program_id": incident.get("program_id"),
        "worker_id": incident.get("worker_id"),
        "category": incident.get("category"),
        "severity": incident.get("severity"),
        "description_text": incident.get("description_text"),
        "status": incident.get("status"),
    }


def appeal_view(claim):
    return {
        "id": claim["id"],
        "created_at": iso(claim.get("created_at")),
        "updated_at": iso(claim.get("updated_at")),
        "version": claim.get("version"),
        "program_id": claim.get("program_id"),
        "item_id": claim.get("item_id"),
        "worker_id": claim.get("worker_id"),
        "spec_unit_id": claim.get("spec_unit_id"),
        "grounds": claim.get("grounds"),
        "statement_text": claim.get("statement_text"),
        "requested_reviewer_id": claim.get("requested_reviewer_id"),
        "adjudicator_id": claim.get("adjudicator_id"),
        "proposed_outcome": claim.get("proposed_outcome"),
        "revised_amount_cents": claim.get("revised_amount_cents"),
        "lock_reason": claim.get("lock_reason"),
        "consensus_outcome": claim.get("consensus_outcome"),
        "status": claim.get("status"),
    }


def week_epoch_view(epoch):
    return {
        "id": epoch["id"],
        "created_at": iso(epoch.get("created_at")),
        "updated_at": iso(epoch.get("updated_at")),
        "version": epoch.get("version"),
        "index": epoch.get("index"),
        "name": epoch.get("name"),
        "starts_at_utc": iso(epoch.get("starts_at_utc")),
        "status": epoch.get("status"),
    }