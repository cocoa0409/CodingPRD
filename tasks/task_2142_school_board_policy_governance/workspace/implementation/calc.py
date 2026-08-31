"""Calculation rules, cascades and the three-phase compliance recompute."""

from decimal import Decimal, ROUND_HALF_UP

import store
from store import db, set_fields, touch

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
NOTICE_LEAD_HOURS = {"REGULAR": 72, "SPECIAL": 48, "EMERGENCY": 24}
PUBLIC_COMMENT_BUDGET_MINUTES = {"REGULAR": 30, "SPECIAL": 5, "EMERGENCY": 0}
MAX_MINUTES_PER_SPEAKER = 3
MIN_MINUTES_PER_SPEAKER = 1
EQUAL_SPLIT_THRESHOLD = 4
MAX_SPEAKERS_PER_ITEM = 5
WAIVER_MAX_DAYS = {
    "REQUIRED_BY_LAW": 90,
    "RECOMMENDED": 180,
    "LOCAL_DISCRETION": 365,
}
REVIEW_CYCLE_DAYS = 1095
EFFECTIVE_DELAY_DAYS = 30
MEETING_SEPARATION_MINUTES = 240
SUPERMAJORITY_NUMERATOR = 2
SUPERMAJORITY_DENOMINATOR = 3
SCORE_MIN = Decimal("1.00")
SCORE_MAX = Decimal("5.00")
DOMAINS = [
    "INSTRUCTIONAL_LEADERSHIP", "FISCAL_STEWARDSHIP",
    "COMMUNITY_RELATIONS", "GOVERNANCE_SUPPORT",
]
DOMAIN_WEIGHT_FIELD = {
    "INSTRUCTIONAL_LEADERSHIP": "weight_instructional",
    "FISCAL_STEWARDSHIP": "weight_fiscal",
    "COMMUNITY_RELATIONS": "weight_community",
    "GOVERNANCE_SUPPORT": "weight_governance",
}


def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp_score(value):
    if value < SCORE_MIN:
        value = SCORE_MIN
    if value > SCORE_MAX:
        value = SCORE_MAX
    return float(value)


# ---------------------------------------------------------------------------
# simple derived counters
# ---------------------------------------------------------------------------

def committee_assignments(committee_id):
    return [a for a in db["assignments"].values()
            if a["committee_id"] == committee_id]


def recompute_committee(committee):
    seats = committee_assignments(committee["id"])
    filled = len([a for a in seats if a["status"] in ("ACTIVE", "RECUSED")])
    voting = len([a for a in seats if a["status"] == "ACTIVE"])
    vacant = committee["seat_capacity"] - filled
    if vacant < 0:
        vacant = 0
    status = "ACTIVE" if voting >= committee["quorum_size"] else "INQUORATE"
    set_fields(committee, filled_seat_count=filled, voting_seat_count=voting,
               vacant_seat_count=vacant, status=status)


def recompute_member_counts(member):
    open_recusals = len([d for d in db["disclosures"].values()
                         if d["board_member_id"] == member["id"]
                         and d["status"] == "RECUSAL_REQUIRED"])
    committees = len([a for a in db["assignments"].values()
                      if a["board_member_id"] == member["id"]
                      and a["status"] in ("ACTIVE", "RECUSED")])
    set_fields(member, open_recusal_count=open_recusals,
               active_committee_count=committees)


def classify_disclosure(nature, policy_category):
    if nature in ("FINANCIAL", "VENDOR"):
        return "RECUSAL_REQUIRED"
    if nature == "EMPLOYMENT" and policy_category == "PERSONNEL":
        return "RECUSAL_REQUIRED"
    if nature == "FAMILIAL" and policy_category == "STUDENTS":
        return "RECUSAL_REQUIRED"
    return "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# three-phase compliance recompute
# ---------------------------------------------------------------------------

def policy_mandates(policy_id):
    return [m for m in db["mandates"].values() if m["policy_id"] == policy_id]


def policy_waivers(policy_id):
    return [w for w in db["waivers"].values() if w["policy_id"] == policy_id]


def published_pinning(policy_id):
    out = []
    for pub in db["publications"].values():
        if pub["status"] != "PUBLISHED":
            continue
        for entry in pub.get("pinned_entries") or []:
            if entry.get("policy_id") == policy_id:
                out.append(pub)
                break
    return out


def _phase1(policy, allow_overdue):
    now = store.now()
    marked = 0
    for m in policy_mandates(policy["id"]):
        if allow_overdue and m["status"] in ("OPEN", "IN_PROGRESS") \
                and now >= m["compliance_deadline"]:
            set_fields(m, status="OVERDUE")
            marked += 1
        if m["status"] == "SATISFIED":
            dpd = 0
        elif now >= m["compliance_deadline"]:
            dpd = store.days_between(m["compliance_deadline"], now)
        else:
            dpd = 0
        set_fields(m, days_past_deadline=dpd)
    return marked


def _phase2(policy):
    now = store.now()
    mandates = policy_mandates(policy["id"])
    open_count = len([m for m in mandates if m["status"] in ("OPEN", "IN_PROGRESS")])
    overdue_count = len([m for m in mandates if m["status"] == "OVERDUE"])
    active_waivers = len([w for w in policy_waivers(policy["id"])
                          if w["status"] == "GRANTED"
                          and w.get("granted_end_date") is not None
                          and w["granted_end_date"] > now])
    if overdue_count > 0:
        state = "NON_COMPLIANT"
    elif open_count > 0:
        state = "ACTION_REQUIRED"
    elif policy["status"] == "UNADOPTED" \
            and policy["legal_requirement_level"] == "REQUIRED_BY_LAW":
        state = "ACTION_REQUIRED"
    elif policy.get("last_review_date") is not None \
            and store.days_between(policy["last_review_date"], now) > REVIEW_CYCLE_DAYS:
        state = "ACTION_REQUIRED"
    else:
        state = "COMPLIANT"
    set_fields(policy, open_mandate_count=open_count,
               overdue_mandate_count=overdue_count,
               active_waiver_count=active_waivers,
               compliance_state=state)


def _phase3(policy):
    for pub in published_pinning(policy["id"]):
        recompute_publication(pub)


def recompute_publication(pub):
    gaps = 0
    for entry in pub.get("pinned_entries") or []:
        target = db["policies"].get(entry.get("policy_id"))
        if target is None or target["compliance_state"] != "COMPLIANT":
            gaps += 1
    set_fields(pub, compliance_gap_count=gaps,
               certification_state="CERTIFIED" if gaps == 0 else "LAPSED")


def policy_scoped_recompute(policy):
    """Phases 1-3 for one policy. Phase 1 never moves a mandate to OVERDUE here."""
    _phase1(policy, allow_overdue=False)
    _phase2(policy)
    _phase3(policy)


def sweep_scoped_recompute():
    """Phases 1-3 over every policy in ascending code order."""
    marked = 0
    policies = sorted(db["policies"].values(), key=lambda p: p["code"])
    for policy in policies:
        marked += _phase1(policy, allow_overdue=True)
        _phase2(policy)
        _phase3(policy)
    return marked, len(policies)


# ---------------------------------------------------------------------------
# public comment allocation
# ---------------------------------------------------------------------------

def item_cards(item_id):
    return [c for c in db["public_comments"].values()
            if c["agenda_item_id"] == item_id]


def meeting_items(meeting_id):
    return [i for i in db["agenda_items"].values() if i["meeting_id"] == meeting_id]


def allocate_public_comment(meeting):
    budget = meeting["public_comment_minutes_budget"]
    cards = []
    for item in meeting_items(meeting["id"]):
        if item["status"] != "POSTED" or not item["requires_public_comment"]:
            continue
        for card in item_cards(item["id"]):
            if card["status"] == "REQUESTED":
                cards.append(card)
    cards.sort(key=lambda c: (c["submitted_at"], c["created_at"], c["speaker_name"]))

    # PASS 0 -- duplicate suppression
    seen = set()
    survivors = []
    for card in cards:
        if card["speaker_name"] in seen:
            set_fields(card, status="DENIED", denial_reason="DUPLICATE_SPEAKER",
                       allotted_minutes=0)
        else:
            seen.add(card["speaker_name"])
            survivors.append(card)

    n = len(survivors)
    if meeting["public_comment_rule"] == "EQUAL_SPLIT" or n >= EQUAL_SPLIT_THRESHOLD:
        variant = "EQUAL_SPLIT"
    else:
        variant = "FIRST_COME_CAPPED"

    remaining = budget
    if variant == "FIRST_COME_CAPPED":
        for card in survivors:
            grant = min(card["requested_minutes"], MAX_MINUTES_PER_SPEAKER, remaining)
            if grant >= MIN_MINUTES_PER_SPEAKER:
                set_fields(card, status="GRANTED", allotted_minutes=grant,
                           denial_reason=None)
                remaining -= grant
            else:
                set_fields(card, status="DENIED",
                           denial_reason="BUDGET_EXHAUSTED", allotted_minutes=0)
    else:
        if n > 0:
            base = budget // n
            capped_base = min(base, MAX_MINUTES_PER_SPEAKER)
            if capped_base == 0:
                for index, card in enumerate(survivors):
                    if index < budget:
                        set_fields(card, status="GRANTED",
                                   allotted_minutes=MIN_MINUTES_PER_SPEAKER,
                                   denial_reason=None)
                        remaining -= MIN_MINUTES_PER_SPEAKER
                    else:
                        set_fields(card, status="DENIED",
                                   denial_reason="BUDGET_EXHAUSTED",
                                   allotted_minutes=0)
            else:
                for card in survivors:
                    set_fields(card, status="GRANTED", allotted_minutes=capped_base,
                               denial_reason=None)
                    remaining -= capped_base
                for card in survivors:
                    if remaining == 0:
                        break
                    if card["allotted_minutes"] < MAX_MINUTES_PER_SPEAKER:
                        set_fields(card,
                                   allotted_minutes=card["allotted_minutes"] + 1)
                        remaining -= 1

    set_fields(meeting, public_comment_allocation_variant=variant,
               public_comment_minutes_remaining=remaining)


def release_cards(item, statuses):
    """Release speaker cards on a dying item and credit minutes back."""
    meeting = db["meetings"].get(item["meeting_id"])
    credited = 0
    for card in item_cards(item["id"]):
        if card["status"] not in statuses:
            continue
        credited += card.get("allotted_minutes") or 0
        set_fields(card, status="RELEASED", denial_reason="ITEM_WITHDRAWN",
                   allotted_minutes=0)
    if credited and meeting is not None:
        set_fields(meeting,
                   public_comment_minutes_remaining=(
                       meeting["public_comment_minutes_remaining"] + credited))
    return credited


def withdraw_items_for_waiver(waiver):
    for item in db["agenda_items"].values():
        if item.get("waiver_request_id") != waiver["id"]:
            continue
        if item["status"] not in ("PROPOSED", "POSTED"):
            continue
        set_fields(item, status="WITHDRAWN")
        release_cards(item, ("REQUESTED", "GRANTED"))


# ---------------------------------------------------------------------------
# vote tally
# ---------------------------------------------------------------------------

def item_policy_id(item):
    if item["item_type"] in ("POLICY_FIRST_READING", "POLICY_SECOND_READING"):
        version = db["policy_versions"].get(item.get("policy_version_id"))
        return version["policy_id"] if version else None
    if item["item_type"] == "WAIVER_DECISION":
        waiver = db["waivers"].get(item.get("waiver_request_id"))
        return waiver["policy_id"] if waiver else None
    return None


def recused_on_policy(member_id, policy_id):
    if policy_id is None:
        return False
    for d in db["disclosures"].values():
        if d["board_member_id"] == member_id and d["policy_id"] == policy_id \
                and d["status"] == "RECUSAL_REQUIRED":
            return True
    return False


def count_recused(meeting, policy_id):
    if policy_id is None:
        return 0
    return len([m for m in (meeting.get("attending_member_ids") or [])
                if recused_on_policy(m, policy_id)])


def required_yes_votes(item, snapshot, votes_cast, policy):
    if item["item_type"] == "POLICY_SECOND_READING":
        if policy is not None \
                and policy["legal_requirement_level"] == "REQUIRED_BY_LAW":
            num = SUPERMAJORITY_NUMERATOR * snapshot
            den = SUPERMAJORITY_DENOMINATOR
            return -((-num) // den)
        return snapshot // 2 + 1
    if item["item_type"] == "WAIVER_DECISION":
        return snapshot // 2 + 1
    return votes_cast // 2 + 1


# ---------------------------------------------------------------------------
# waiver window
# ---------------------------------------------------------------------------

def grant_waiver_window(waiver):
    now = store.now()
    start = waiver["requested_start_date"]
    if now > start:
        start = now
    end = waiver["requested_end_date"]
    days = store.days_between(start, end)
    if days < 0:
        days = 0
    return start, end, days


# ---------------------------------------------------------------------------
# manual publication snapshot
# ---------------------------------------------------------------------------

def publication_snapshot(pub):
    adopted = [p for p in db["policies"].values()
               if p["status"] == "ADOPTED" and p.get("adopted_version_no") is not None]
    adopted.sort(key=lambda p: (p["manual_section"], p["code"]))
    entries = [{
        "policy_id": p["id"],
        "policy_code": p["code"],
        "version_no": p["adopted_version_no"],
        "manual_section": p["manual_section"],
    } for p in adopted]
    gaps = len([e for e in entries
                if db["policies"][e["policy_id"]]["compliance_state"] != "COMPLIANT"])
    set_fields(pub, pinned_entries=entries, entry_count=len(entries),
               compliance_gap_count=gaps,
               certification_state="CERTIFIED" if gaps == 0 else "LAPSED",
               published_at=store.now(), status="PUBLISHED")
    touch(pub)
    for other in db["publications"].values():
        if other["id"] == pub["id"]:
            continue
        if other["status"] == "PUBLISHED":
            set_fields(other, status="SUPERSEDED",
                       superseded_by_label=pub["publication_label"])


# ---------------------------------------------------------------------------
# superintendent evaluation scores
# ---------------------------------------------------------------------------

def evaluation_ratings(evaluation_id):
    return [r for r in db["ratings"].values() if r["evaluation_id"] == evaluation_id]


def recompute_evaluation_counters(evaluation):
    ratings = evaluation_ratings(evaluation["id"])
    eligible = set()
    for r in ratings:
        member = db["board_members"].get(r["board_member_id"])
        if member is None:
            continue
        if member["status"] == "SEATED" \
                and member["term_end_date"] >= evaluation["window_end_date"]:
            eligible.add(member["id"])
    set_fields(evaluation, rating_count=len(ratings),
               eligible_rater_count=len(eligible))


def midyear_formative_score(evaluation):
    rows = []
    for r in evaluation_ratings(evaluation["id"]):
        member = db["board_members"].get(r["board_member_id"])
        if r["phase"] == "FORMATIVE" and member is not None \
                and member["status"] == "SEATED":
            rows.append(r)
    if not rows:
        return None
    total = sum(r["score"] for r in rows)
    mean = Decimal(total) / Decimal(len(rows))
    return clamp_score(round2(mean))


def summative_composite_score(evaluation):
    rows = []
    for r in evaluation_ratings(evaluation["id"]):
        member = db["board_members"].get(r["board_member_id"])
        if member is None:
            continue
        if member["status"] == "SEATED" \
                and member["term_end_date"] >= evaluation["window_end_date"]:
            rows.append(r)
    if not rows:
        return None
    weighted = Decimal("0")
    weight_sum = Decimal("0")
    for domain in DOMAINS:
        scores = [r["score"] for r in rows if r["domain"] == domain]
        if not scores:
            continue
        mean = round2(Decimal(sum(scores)) / Decimal(len(scores)))
        weight = Decimal(str(evaluation[DOMAIN_WEIGHT_FIELD[domain]]))
        weighted += weight * mean
        weight_sum += weight
    if weight_sum == 0:
        return None
    return clamp_score(round2(weighted / weight_sum))
