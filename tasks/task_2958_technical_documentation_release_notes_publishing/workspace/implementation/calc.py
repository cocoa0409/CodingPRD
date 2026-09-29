"""Every server-computed quantity: ledgers, scans, quotes, scores.

All figures here are full recomputations over their defining sets, as PRD
section 2.8 requires of the three conserved quantities.
"""
from datetime import timedelta
from decimal import Decimal

from core import (
    D,
    add_days,
    by_seq,
    date_of_instant,
    db,
    dfloor,
    fmt_date,
    parse_instant,
    r2,
    rcents,
    touch,
)

# --- assignment load points (PRD 3.2) --------------------------------------
PAGE_POINTS = 2
COMPLEXITY_CAP = 20
IA_POINTS = {"NEW_TOPIC": 4, "EXISTING_TOPIC_UPDATE": 1, "CONCEPT_HUB": 6}
AUDIENCE_MULTIPLIER = {"CRITICAL": D("1.5"), "STANDARD": D("1.0"), "INTERNAL": D("0.75")}
SENIORITY_DIVISOR = {"PRINCIPAL": D("1.25"), "SENIOR": D("1.0"), "ASSOCIATE": D("0.80")}
MIN_LOAD_POINTS = D("3.0")
REWORK_POINTS = D("1.0")
HANDOFF_BUFFER_DAYS = 2

# --- readiness gate (PRD 3.1) ---------------------------------------------
FREEZE_READY_RATIO = D("0.80")
RESTRICTED_FLOOR = D("0.50")
TRAIN_SPINE = ("PLANNED", "DOC_FREEZE", "GA", "MAINTENANCE", "END_OF_LIFE")

# --- ledgers ---------------------------------------------------------------
COUNTED_ITEM_STATES = ("ASSIGNED", "IN_AUTHORING", "IN_REVIEW", "IN_REVISION", "APPROVED_CONTENT")
OPEN_JOB_STATES = ("QUEUED", "TRANSLATED", "REWORK_REQUESTED", "SCHEDULED_DELAYED")

# --- localization quote (PRD 3.8) ----------------------------------------
TM_DISCOUNT_FACTOR = D("0.70")
RUSH_SURCHARGE_PCT = D("15")
VOLUME_TIERS = ((500000, D("10")), (200000, D("6")), (50000, D("3")))
SLA_GRACE_DAYS = 3

# --- health and deflection (PRD 3.10) ------------------------------------
DEFLECTION_WINDOW_DAYS = 30
CHURN_WEIGHT = D("4")
CHURN_FREE_REVISIONS = 2
BLOCKER_WEIGHT = D("12")
WARNING_WEIGHT = D("3")
LATENCY_WEIGHT = D("2")
LATENCY_GRACE_DAYS = 3
RATING_WEIGHT = D("4")
DEFLECTION_PENALTY_PER_POINT = D("0.06")

# --- customer impact (PRD 3.7) -------------------------------------------
SEVERITY_WEIGHT = {"BREAKING": 40, "SECURITY": 25, "MAJOR": 12, "MINOR": 4, "PATCH": 1}
SEVERITY_ORDER = ("BREAKING", "SECURITY", "MAJOR", "MINOR", "PATCH")

# --- deprecation notice periods (PRD 3.9) --------------------------------
MIN_NOTICE_DAYS = {"BREAKING": 180, "MAJOR": 90, "MINOR": 30}

MAX_IA_DEPTH = 4


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------
def topic_plan_item(topic):
    return db.plan_items.get(topic["plan_item_id"])


def topic_train(topic):
    item = topic_plan_item(topic)
    if item is None:
        return None
    return db.release_trains.get(item["release_train_id"])


def train_topics(train_id):
    out = []
    for topic in db.topics.values():
        item = db.plan_items.get(topic["plan_item_id"])
        if item is not None and item["release_train_id"] == train_id:
            out.append(topic)
    return by_seq(out)


def train_plan_items(train_id):
    return by_seq([i for i in db.plan_items.values() if i["release_train_id"] == train_id])


def topic_revisions(topic_id):
    revs = [r for r in db.source_revisions.values() if r["topic_id"] == topic_id]
    return sorted(revs, key=lambda r: r["revision_number"])


def latest_revision(topic_id):
    revs = topic_revisions(topic_id)
    return revs[-1] if revs else None


def topic_signoffs(topic_id):
    return by_seq([s for s in db.signoffs.values() if s["topic_id"] == topic_id])


def topic_jobs(topic_id):
    return by_seq([j for j in db.localization_jobs.values() if j["topic_id"] == topic_id])


def active_terms():
    terms = [t for t in db.terminology_terms.values() if t["status"] == "ACTIVE"]
    return sorted(terms, key=lambda t: t["term"])


def simultaneous_locales():
    locales = [l for l in db.locale_profiles.values()
               if l["status"] == "ACTIVE" and l["publication_mode"] == "SIMULTANEOUS"]
    return sorted(locales, key=lambda l: l["locale_code"])


# ---------------------------------------------------------------------------
# Terminology violation scan (PRD 3.4)
# ---------------------------------------------------------------------------
def terminology_scan(used_terms):
    """Returns (blocker_count, warning_count, violating_term_ids)."""
    tokens = set()
    for token in used_terms or []:
        tokens.add(token.lower())
    blockers = 0
    warnings = 0
    violated = []
    for term in active_terms():
        forbidden = set(f.lower() for f in term["forbidden_forms"])
        if tokens & forbidden:
            violated.append(term["id"])
            if term["enforcement_severity"] == "BLOCKER":
                blockers += 1
            else:
                warnings += 1
    return blockers, warnings, violated


def refresh_topic_live_counters(topic):
    """Re-derive the topic's live counters from its newest revision's snapshot,
    filtered down to the terms that are still active (PRD 2.9)."""
    revision = latest_revision(topic["id"])
    blockers = 0
    warnings = 0
    if revision is not None:
        for term_id in revision["violating_term_ids"]:
            term = db.terminology_terms.get(term_id)
            if term is not None and term["status"] == "ACTIVE":
                if term["enforcement_severity"] == "BLOCKER":
                    blockers += 1
                else:
                    warnings += 1
    topic["open_blocker_violations"] = blockers
    topic["open_warning_violations"] = warnings


# ---------------------------------------------------------------------------
# Assignment load points (PRD 3.2)
# ---------------------------------------------------------------------------
def compute_load_points(item, writer):
    size_points = D(PAGE_POINTS) * D(item["planned_page_count"])
    depth_points = D(min(item["complexity_points"], COMPLEXITY_CAP))
    ia_points = D(IA_POINTS[item["ia_placement"]])
    raw = ((size_points + depth_points + ia_points)
           * AUDIENCE_MULTIPLIER[item["audience_tier"]]
           / SENIORITY_DIVISOR[writer["seniority_tier"]])
    base = max(MIN_LOAD_POINTS, r2(raw))
    return base, r2(base + REWORK_POINTS * D(item["rework_count"]))


def apply_rework_points(item):
    """Re-derive load_points from the stored base load and the rework count."""
    base = D(item.get("_base_load_points") or 0)
    item["load_points"] = r2(base + REWORK_POINTS * D(item["rework_count"]))


def windows_collide(req_start, req_end, ex_start, ex_end):
    """Half-open windows padded by a two-day handoff buffer on the leading edge."""
    return (req_start < add_days(ex_end, HANDOFF_BUFFER_DAYS)) and (req_end > ex_start)


# ---------------------------------------------------------------------------
# Conserved ledgers (PRD 2.8)
# ---------------------------------------------------------------------------
def writer_counted_items(writer_id):
    return by_seq([i for i in db.plan_items.values()
                   if i["assigned_writer_id"] == writer_id
                   and i["status"] in COUNTED_ITEM_STATES])


def recompute_writer(writer):
    if writer is None:
        return
    items = writer_counted_items(writer["id"])
    total = D(0)
    for item in items:
        total += D(item["load_points"])
    writer["committed_load_points"] = r2(total)
    writer["assignment_count"] = len(items)


def locale_open_jobs(locale_id):
    return by_seq([j for j in db.localization_jobs.values()
                   if j["locale_profile_id"] == locale_id and j["state"] in OPEN_JOB_STATES])


def recompute_locale(locale):
    if locale is None:
        return
    jobs = locale_open_jobs(locale["id"])
    locale["committed_source_words"] = sum(j["reserved_source_words"] for j in jobs)
    locale["open_job_count"] = len(jobs)


def recompute_reviewer(reviewer):
    if reviewer is None:
        return
    reviewer["open_signoff_count"] = len(
        [s for s in db.signoffs.values()
         if s["reviewer_id"] == reviewer["id"] and s["state"] == "PENDING"])


def train_commitment_cents(train_id):
    total = 0
    for job in db.localization_jobs.values():
        if job["state"] not in OPEN_JOB_STATES:
            continue
        topic = db.topics.get(job["topic_id"])
        if topic is None:
            continue
        item = db.plan_items.get(topic["plan_item_id"])
        if item is None or item["release_train_id"] != train_id:
            continue
        if job["cost_variant"] == "FINAL" and job["final_cost_cents"] is not None:
            total += job["final_cost_cents"]
        else:
            total += job["estimated_cost_cents"] or 0
    return total


def recompute_train(train):
    """Readiness figures plus the train's localization commitment (PRD 3.1)."""
    if train is None:
        return
    items = [i for i in db.plan_items.values() if i["release_train_id"] == train["id"]]
    counted = [i for i in items if i["status"] != "CANCELLED"]
    approved = [i for i in counted if i["status"] in ("APPROVED_CONTENT", "PUBLISHED")]
    train["plan_item_count"] = len(counted)
    train["approved_plan_item_count"] = len(approved)
    if not counted:
        ratio = r2(D(1))
    else:
        ratio = r2(D(len(approved)) / D(len(counted)))
    train["approved_topic_ratio"] = ratio
    status = train["status"]
    if status in ("MAINTENANCE", "END_OF_LIFE"):
        posture = "FROZEN"
    elif status == "PLANNED":
        posture = "OPEN"
    elif ratio >= FREEZE_READY_RATIO:
        posture = "OPEN"
    elif ratio >= RESTRICTED_FLOOR:
        posture = "RESTRICTED"
    else:
        posture = "FROZEN"
    train["doc_readiness_posture"] = posture
    train["localization_committed_cents"] = train_commitment_cents(train["id"])


# ---------------------------------------------------------------------------
# Localization job cost quote (PRD 3.8) - nine ordered steps
# ---------------------------------------------------------------------------
def quote_cost(source_words, tm_words, locale, window_start, window_end):
    """Returns (leverage_pct, rush_surcharge_cents, volume_discount_cents, cost_cents)."""
    source_words = int(source_words)
    tm_words = int(tm_words)
    if source_words == 0:
        leverage = r2(D(0))
    else:
        leverage = r2(D(tm_words) * D(100) / D(source_words))
    effective = source_words - dfloor(D(tm_words) * TM_DISCOUNT_FACTOR)
    base_cents = rcents(D(effective) * D(locale["per_word_rate_cents"]))
    window_days = (window_end - window_start).days + 1
    if window_days < locale["sla_days"]:
        rush = rcents(D(base_cents) * RUSH_SURCHARGE_PCT / D(100))
    else:
        rush = 0
    subtotal = base_cents + rush
    percent = D(0)
    for threshold, band in VOLUME_TIERS:
        if subtotal >= threshold:
            percent = band
            break
    discount = rcents(D(subtotal) * percent / D(100))
    return leverage, rush, discount, subtotal - discount


def provisional_tm_words(source_words, locale):
    return dfloor(D(source_words) * D(locale["tm_coverage_pct"]) / D(100))


def apply_provisional_quote(job, locale, window_start, window_end):
    source_words = job["reserved_source_words"]
    tm_words = provisional_tm_words(source_words, locale)
    leverage, rush, discount, cost = quote_cost(
        source_words, tm_words, locale, window_start, window_end)
    job["leverage_pct"] = leverage
    job["rush_surcharge_cents"] = rush
    job["volume_discount_cents"] = discount
    job["estimated_cost_cents"] = cost
    job["cost_variant"] = "PROVISIONAL"


def apply_final_quote(job, locale, window_start, window_end):
    leverage, rush, discount, cost = quote_cost(
        job["translated_word_count"], job["tm_matched_word_count"],
        locale, window_start, window_end)
    job["leverage_pct"] = leverage
    job["rush_surcharge_cents"] = rush
    job["volume_discount_cents"] = discount
    job["final_cost_cents"] = cost
    job["cost_variant"] = "FINAL"


# ---------------------------------------------------------------------------
# Doc set localization budget projection (PRD 3.6) - round per locale, then sum
# ---------------------------------------------------------------------------
def budget_projection(train_id):
    publishable_words = 0
    for topic in train_topics(train_id):
        if topic["review_state"] == "FULLY_APPROVED":
            publishable_words += topic["latest_body_word_count"]
    total = 0
    for locale in simultaneous_locales():
        tm_words = dfloor(D(publishable_words) * D(locale["tm_coverage_pct"]) / D(100))
        effective = publishable_words - dfloor(D(tm_words) * TM_DISCOUNT_FACTOR)
        total += rcents(D(effective) * D(locale["per_word_rate_cents"]))
    return total


# ---------------------------------------------------------------------------
# Deflection metrics (PRD 3.10)
# ---------------------------------------------------------------------------
def deflection_metrics(topic_id):
    window_end_instant = db.now()
    window_start_instant = window_end_instant - timedelta(days=DEFLECTION_WINDOW_DAYS)
    rows = []
    for row in db.page_feedback.values():
        if row["topic_id"] != topic_id:
            continue
        stamp = parse_instant(row["created_at"])
        if stamp is not None and window_start_instant <= stamp <= window_end_instant:
            rows.append(row)
    sample_count = len(rows)
    if sample_count == 0:
        mean_rating = None
    else:
        mean_rating = r2(D(sum(r["rating"] for r in rows)) / D(sample_count))
    decided = [r for r in rows if r["outcome"] in ("RESOLVED_SELF_SERVE", "OPENED_TICKET")]
    if not decided:
        deflection_pct = None
        ticket_rate_pct = None
    else:
        resolved = len([r for r in decided if r["outcome"] == "RESOLVED_SELF_SERVE"])
        tickets = len([r for r in decided if r["outcome"] == "OPENED_TICKET"])
        deflection_pct = r2(D(resolved) * D(100) / D(len(decided)))
        ticket_rate_pct = r2(D(tickets) * D(100) / D(len(decided)))
    return {
        "sample_count": sample_count,
        "mean_rating": mean_rating,
        "deflection_pct": deflection_pct,
        "ticket_rate_pct": ticket_rate_pct,
        "window_start_date": fmt_date(window_start_instant.date()),
        "window_end_date": fmt_date(window_end_instant.date()),
    }


# ---------------------------------------------------------------------------
# Documentation health score (PRD 3.10)
# ---------------------------------------------------------------------------
def health_score(topic, variant):
    churn_excess = topic["current_revision_number"] - CHURN_FREE_REVISIONS
    churn_penalty = CHURN_WEIGHT * D(churn_excess) if churn_excess > 0 else D(0)
    blocker_penalty = BLOCKER_WEIGHT * D(topic["open_blocker_violations"])
    warning_penalty = WARNING_WEIGHT * D(topic["open_warning_violations"])
    latency = topic.get("signoff_latency_days")
    if latency is None or latency <= LATENCY_GRACE_DAYS:
        latency_penalty = D(0)
    else:
        latency_penalty = LATENCY_WEIGHT * D(latency - LATENCY_GRACE_DAYS)
    score = D(100) - churn_penalty - blocker_penalty - warning_penalty - latency_penalty
    if variant == "POST_PUBLICATION":
        metrics = deflection_metrics(topic["id"])
        if metrics["sample_count"] == 0:
            rating_penalty = D(0)
        else:
            rating_penalty = r2(RATING_WEIGHT * (D(5) - D(metrics["mean_rating"])))
        score -= rating_penalty
        if metrics["deflection_pct"] is None:
            deflection_penalty = D(0)
        else:
            deflection_penalty = r2(
                DEFLECTION_PENALTY_PER_POINT * (D(100) - D(metrics["deflection_pct"])))
        score -= deflection_penalty
    if score < D(0):
        score = D(0)
    return r2(score)


def set_health(topic, variant):
    topic["health_score"] = health_score(topic, variant)
    topic["health_score_variant"] = variant


# ---------------------------------------------------------------------------
# Release-note customer impact score (PRD 3.7)
# ---------------------------------------------------------------------------
def approved_change_records(train_id):
    records = [c for c in db.change_records.values()
               if c["release_train_id"] == train_id and c["state"] == "EDITORIALLY_APPROVED"]
    return by_seq(records)


def ordered_included_ids(records):
    ranked = sorted(records, key=lambda c: (SEVERITY_ORDER.index(c["severity"]), c["_seq"]))
    return [c["id"] for c in ranked]


def severity_counts(records):
    counts = dict((severity, 0) for severity in SEVERITY_ORDER)
    for record in records:
        counts[record["severity"]] += 1
    return counts


def headline_severity(records):
    best = None
    for record in records:
        weight = SEVERITY_WEIGHT[record["severity"]]
        if best is None or weight > SEVERITY_WEIGHT[best]:
            best = record["severity"]
    return best


def documented_feature_keys(train_id, counted_statuses):
    keys = set()
    for item in train_plan_items(train_id):
        if item["status"] in counted_statuses:
            keys.add(item["feature_key"])
    return keys


def impact_figures(train_id, records, counted_statuses):
    """Returns (coverage_factor, impact_score) for one variant."""
    raw = 0
    for record in records:
        raw += SEVERITY_WEIGHT[record["severity"]]
    keys = documented_feature_keys(train_id, counted_statuses)
    documented = len([c for c in records if c["affected_component"] in keys])
    if not records:
        coverage = r2(D(0))
    else:
        coverage = r2(D(documented) / D(len(records)))
    score = r2(D(raw) * (D(2) - coverage))
    if score > D(100):
        score = D(100)
    return coverage, r2(score)


PROVISIONAL_COUNTED_STATUSES = ("APPROVED_CONTENT", "PUBLISHED")
FINAL_COUNTED_STATUSES = ("PUBLISHED",)


# ---------------------------------------------------------------------------
# Deprecation timeline compliance (PRD 3.9)
# ---------------------------------------------------------------------------
def timeline_figures(announce_date, removal_date, severity_tier):
    notice_days = (removal_date - announce_date).days
    minimum = MIN_NOTICE_DAYS[severity_tier]
    return notice_days, add_days(announce_date, minimum), minimum
