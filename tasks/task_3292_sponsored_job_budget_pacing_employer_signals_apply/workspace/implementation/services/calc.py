"""Business rules: calculations, state cascades, rollover.

Every rule here traces to PRD section 3 / the scaffold's calculation table.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import DAY_SECONDS, iso, logical_day, parse_iso, store
from models import (
    content_hash,
    create,
    dedupe_key,
    touch,
)

# ============================================================ pacing multipliers

WARMUP_FRACTION = Decimal("0.05")
MIN_MULTIPLIER = Decimal("0.0")
MAX_MULTIPLIER = Decimal("2.0")


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def _round3(value):
    return float(Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _elapsed_fraction(campaign, clock):
    start = parse_iso(campaign["day_open_date"])
    seconds = Decimal((clock - start).total_seconds())
    fraction = seconds / Decimal(DAY_SECONDS)
    return _clamp(fraction, Decimal("0.0"), Decimal("1.0"))


def _campaign_active_in_pacing(campaign):
    return campaign["status"] in ("ACTIVE", "PACING_HOLD")


def campaign_pacing_multiplier(campaign, clock=None):
    """Scheduled (a-priori) pacing multiplier, PRD 3.2."""
    clock = clock or store.clock
    if not _campaign_active_in_pacing(campaign):
        return 1.0
    if parse_iso(campaign["day_open_date"]) != logical_day(clock):
        return 1.0
    if campaign["daily_spent_cents"] >= campaign["daily_budget_cents"]:
        # Realized variant of the scheduled formula: the day is exhausted.
        return 1.0
    elapsed = _elapsed_fraction(campaign, clock)
    if elapsed < WARMUP_FRACTION:
        return 1.0
    target = elapsed
    budget = Decimal(campaign["daily_budget_cents"])
    actual = (Decimal(campaign["daily_spent_cents"]) / budget) if budget else Decimal(0)
    if actual <= target:
        raw = Decimal(1) + (target - actual)
    else:
        raw = Decimal(1) - (actual - target)
    return _round3(_clamp(raw, MIN_MULTIPLIER, MAX_MULTIPLIER))


def realized_pacing_multiplier(campaign, clock=None):
    """Realized (post-hoc) pacing multiplier, PRD 3.2."""
    clock = clock or store.clock
    if campaign["status"] not in ("ACTIVE", "PACING_HOLD", "COMPLETED"):
        return 1.0
    elapsed = _elapsed_fraction(campaign, clock)
    expected = int((Decimal(campaign["daily_budget_cents"]) * elapsed).to_integral_value(
        rounding="ROUND_FLOOR"))
    if expected == 0:
        return 1.0
    raw = Decimal(campaign["daily_spent_cents"]) / Decimal(expected)
    return _round3(_clamp(raw, MIN_MULTIPLIER, MAX_MULTIPLIER))


# ================================================================ auction price

def candidate_pool():
    """Eligible sponsored jobs whose posting is ACTIVE, in ACTIVE campaigns."""
    pool = []
    for job in store.sponsored_jobs.values():
        if job["status"] != "ELIGIBLE":
            continue
        campaign = store.campaigns.get(job["campaign_id"])
        posting = store.job_postings.get(job["job_posting_id"])
        if campaign is None or posting is None:
            continue
        if campaign["status"] != "ACTIVE":
            continue
        if posting["state"] != "ACTIVE":
            continue
        pool.append(job)
    return pool


def effective_bid(job, campaign):
    bid = job["cpc_bid_cents"] if campaign["pricing_model"] == "CPC" else job["cpa_bid_cents"]
    return Decimal(bid) * Decimal(str(job["scheduled_pacing_multiplier"]))


def relevant_bid(job, campaign):
    return job["cpc_bid_cents"] if campaign["pricing_model"] == "CPC" else job["cpa_bid_cents"]


def rank_of(job):
    campaign = store.campaigns.get(job["campaign_id"])
    if campaign is None:
        return Decimal(0)
    employer = store.employers.get(campaign["employer_id"])
    quality = employer["quality_score"] if employer else 100
    return effective_bid(job, campaign) * (Decimal(quality) / Decimal(100))


def rank_key(job):
    """Ordering: rank DESC, cpc_bid_cents DESC, created_at ASC."""
    return (
        -rank_of(job),
        -job["cpc_bid_cents"],
        job["created_at"],
    )


def ordered_candidates():
    return sorted(candidate_pool(), key=rank_key)


def auction_clearing_price(bidding_job):
    """GSP with a quality tilt, PRD 3.4."""
    campaign = store.campaigns[bidding_job["campaign_id"]]
    bidder_bid = relevant_bid(bidding_job, campaign)
    candidates = candidate_pool()
    if len(candidates) < 2:
        return int(bidder_bid)
    ordered = sorted(
        candidates,
        key=lambda job: (
            0 if job["id"] == bidding_job["id"] else 1,
            rank_key(job),
        ),
    )
    if ordered and ordered[0]["id"] == bidding_job["id"]:
        runner_up = ordered[1]
    else:
        runner_up = ordered[0]
    second = rank_of(runner_up)
    employer = store.employers.get(campaign["employer_id"])
    bidder_quality = employer["quality_score"] if employer else 100
    if bidder_quality <= 0:
        return int(bidder_bid)
    raw = (second / Decimal(bidder_quality)) * Decimal(100) + Decimal(1)
    ceiled = int(Decimal(raw).to_integral_value(rounding="ROUND_CEILING"))
    return min(max(ceiled, 1), int(bidder_bid))


# =========================================================== budget commit split

def budget_commit_split(campaign, cleared, sponsor_event_id):
    """Waterfall allocation over ACTIVE holds, oldest-first (PRD 3.5)."""
    remaining = int(cleared)
    holds = [
        hold for hold in store.pacing_holds.values()
        if hold["campaign_id"] == campaign["id"] and hold["status"] == "ACTIVE"
    ]
    holds.sort(key=lambda hold: (hold["created_at"],))
    for hold in holds:
        if remaining <= 0:
            break
        take = min(hold["amount_cents"], remaining)
        if take <= 0:
            continue
        if take == hold["amount_cents"]:
            hold["status"] = "COMMITTED"
        else:
            hold["amount_cents"] = hold["amount_cents"] - take
        hold["sponsor_event_id"] = sponsor_event_id
        touch(hold)
        append_ledger(campaign, "COMMIT", take, sponsor_event_id)
        remaining -= take
    if remaining > 0:
        append_ledger(campaign, "COMMIT", remaining, sponsor_event_id)
    campaign["spent_cents"] += int(cleared)
    return int(cleared)


def append_ledger(campaign, entry_type, amount_cents, sponsor_event_id=None):
    """Append-only ledger row with the declared reference-code scheme."""
    prefix = {"HOLD": "HLD", "COMMIT": "CMT", "RELEASE": "REV", "REFUND": "RFD"}[entry_type]
    store.ledger_seq[prefix] = store.ledger_seq.get(prefix, 0) + 1
    seq = store.ledger_seq[prefix]
    from models import append as append_row
    return append_row(
        "budget_ledger",
        campaign_id=campaign["id"],
        entry_type=entry_type,
        amount_cents=int(amount_cents),
        sponsor_event_id=sponsor_event_id,
        reference_code="%s-%d" % (prefix, seq),
    )


def recompute_held_cents(campaign):
    total = sum(
        hold["amount_cents"] for hold in store.pacing_holds.values()
        if hold["campaign_id"] == campaign["id"] and hold["status"] == "ACTIVE"
    )
    campaign["held_cents"] = total
    return total


def recompute_spent_cents(campaign):
    """spent_cents from the immutable ledger: COMMIT + REFUND (PRD 2.5)."""
    total = 0
    for entry in store.budget_ledger.values():
        if entry["campaign_id"] != campaign["id"]:
            continue
        if entry["entry_type"] in ("COMMIT", "REFUND"):
            total += entry["amount_cents"]
    campaign["spent_cents"] = total
    return total


# ========================================================= employer quality signal

def paused_closed_application(application):
    """True when a CLOSED application counts against the employer as non-response."""
    return application["status"] == "CLOSED" and application["disposition"] == "NONE"


def application_counts_as_dispositioned(application):
    if application["disposition"] not in ("NONE", None):
        return True
    return paused_closed_application(application)


def recompute_employer_quality(employer):
    """response_rate_bps and quality_score, PRD 3.7."""
    applications = [
        app for app in store.applications.values()
        if _application_employer_id(app) == employer["id"]
    ]
    dispositioned = [app for app in applications if application_counts_as_dispositioned(app)]
    responding = [
        app for app in dispositioned
        if app["disposition"] in ("REVIEWED", "INTERVIEW", "REJECTED", "HIRED")
    ]
    count = len(dispositioned)
    if count == 0:
        employer["response_rate_bps"] = 0
        return employer["quality_score"]
    bps = (10000 * len(responding)) // count
    employer["response_rate_bps"] = bps

    if bps >= 6000:
        tier = 100
    elif bps >= 3000:
        tier = 70
    else:
        tier = 40

    hired = sum(1 for app in dispositioned if app["disposition"] == "HIRED")
    interviewed = sum(1 for app in dispositioned if app["disposition"] == "INTERVIEW")
    rejected = sum(1 for app in dispositioned if app["disposition"] == "REJECTED")
    denominator = max(count, 1)
    raw = (Decimal(30 * hired) / denominator
           + Decimal(10 * interviewed) / denominator
           - Decimal(10 * rejected) / denominator)
    delta = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    employer["quality_score"] = _clamp_int(tier + delta, 0, 100)
    return employer["quality_score"]


def _clamp_int(value, low, high):
    return max(low, min(high, int(value)))


def _application_employer_id(application):
    posting = store.job_postings.get(application["job_posting_id"])
    if posting is None:
        return None
    return posting["employer_id"]


def recompute_employer_sponsored_pacing(employer_id):
    """Every SponsoredJob of the employer recomputes both pacing multipliers."""
    for job in store.sponsored_jobs.values():
        campaign = store.campaigns.get(job["campaign_id"])
        if campaign is None or campaign["employer_id"] != employer_id:
            continue
        job["scheduled_pacing_multiplier"] = campaign_pacing_multiplier(campaign)
        job["realized_pacing_multiplier"] = realized_pacing_multiplier(campaign)
        touch(job)


# ==================================================================== relevance

def split_tokens(text):
    if text is None:
        return set()
    return {token for token in str(text).casefold().split() if token}


def keyword_match(filters, title):
    """FULL / PARTIAL / NONE over deduplicated case-insensitive tokens."""
    wanted = split_tokens(filters)
    if not wanted:
        return "NONE"
    have = split_tokens(title)
    if wanted <= have:
        return "FULL"
    if wanted & have:
        return "PARTIAL"
    return "NONE"


def location_match(seeker_location, posting_location):
    """EXACT / SAME_PREFIX / NONE."""
    if seeker_location is None or str(seeker_location).strip() == "":
        return "NONE"
    wanted = " ".join(str(seeker_location).casefold().split())
    have = " ".join(str(posting_location or "").casefold().split())
    if not wanted or not have:
        return "NONE"
    if have == wanted:
        return "EXACT"
    if have.startswith(wanted):
        return "SAME_PREFIX"
    return "NONE"


def relevance_score(posting, keywords, location):
    """Fixed-weight relevance, PRD 3.9.  Maximum 100."""
    match = keyword_match(keywords, posting["title"])
    keyword_score = 40 if match == "FULL" else (20 if match == "PARTIAL" else 0)
    loc = location_match(location, posting["location"])
    location_score = 35 if loc == "EXACT" else (15 if loc == "SAME_PREFIX" else 0)
    freshness = posting["current_freshness"]
    freshness_score = 25 if freshness == "FRESH" else (10 if freshness == "STALE" else 0)
    return keyword_score + location_score + freshness_score


def matchable_postings():
    return [
        posting for posting in store.job_postings.values()
        if posting["state"] in ("ACTIVE", "STALE")
    ]


def ranked_matches(keywords, location):
    scored = [
        (relevance_score(posting, keywords, location), posting)
        for posting in matchable_postings()
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1]["created_at"], pair[1]["id"]))
    return scored


# ============================================================ posting freshness

STALE_AFTER_DAYS = 30
EXPIRED_AFTER_DAYS = 60


def age_days(ingested_at, clock):
    """Whole elapsed days, fractional part truncated toward zero (PRD 3.1)."""
    age_seconds = (clock - parse_iso(ingested_at)).total_seconds()
    return int(age_seconds // DAY_SECONDS)


def freshness_of(ingested_at, clock):
    days = age_days(ingested_at, clock)
    if days < STALE_AFTER_DAYS:
        return "FRESH"
    if days < EXPIRED_AFTER_DAYS:
        return "STALE"
    return "EXPIRED"


def newest_version(posting_id):
    versions = [
        version for version in store.job_posting_versions.values()
        if version["job_posting_id"] == posting_id
    ]
    if not versions:
        return None
    versions.sort(key=lambda version: (version["ingested_at"], version["created_at"]))
    return versions[-1]


def rederive_posting(posting, clock=None):
    """current_freshness + derived state with the pinned precedence (PRD 3.1)."""
    clock = clock or store.clock
    version = newest_version(posting["id"])
    if version is None:
        return posting
    freshness = freshness_of(version["ingested_at"], clock)
    posting["current_freshness"] = freshness
    if posting["state"] == "SUSPENDED":
        return posting
    if freshness == "EXPIRED":
        posting["state"] = "EXPIRED"
    elif freshness == "STALE":
        posting["state"] = "STALE"
    else:
        posting["state"] = "ACTIVE"
    return posting


def rederive_all_postings(clock=None):
    clock = clock or store.clock
    rederived = 0
    for posting in list(store.job_postings.values()):
        before = (posting["current_freshness"], posting["state"])
        rederive_posting(posting, clock)
        after = (posting["current_freshness"], posting["state"])
        if before != after:
            touch(posting)
            rederived += 1
        if posting["state"] in ("EXPIRED", "SUSPENDED"):
            pause_sponsored_jobs_for_posting(posting)
    return rederived


# ================================================================ cascade helpers

def release_active_holds(sponsored_job_id):
    released = 0
    for hold in store.pacing_holds.values():
        if hold["sponsored_job_id"] != sponsored_job_id or hold["status"] != "ACTIVE":
            continue
        campaign = store.campaigns.get(hold["campaign_id"])
        amount = hold["amount_cents"]
        hold["status"] = "RELEASED"
        touch(hold)
        if campaign is not None:
            append_ledger(campaign, "RELEASE", -amount, None)
            recompute_held_cents(campaign)
        released += 1
    return released


def pause_sponsored_job(job):
    if job["status"] == "PAUSED":
        return False
    job["status"] = "PAUSED"
    touch(job)
    release_active_holds(job["id"])
    return True


def pause_sponsored_jobs_for_posting(posting):
    count = 0
    for job in store.sponsored_jobs.values():
        if job["job_posting_id"] == posting["id"] and job["status"] != "PAUSED":
            pause_sponsored_job(job)
            count += 1
    return count


def pause_sponsored_jobs_for_campaign(campaign, only_eligible=True):
    count = 0
    for job in store.sponsored_jobs.values():
        if job["campaign_id"] != campaign["id"]:
            continue
        if only_eligible and job["status"] != "ELIGIBLE":
            continue
        if job["status"] == "PAUSED":
            continue
        pause_sponsored_job(job)
        count += 1
    return count


def recompute_budget_hold_states(campaign):
    """Sponsored job BUDGET_HOLD <-> ELIGIBLE against remaining daily capacity."""
    remaining = (campaign["daily_budget_cents"]
                 - campaign["daily_spent_cents"]
                 - campaign["held_cents"])
    for job in store.sponsored_jobs.values():
        if job["campaign_id"] != campaign["id"]:
            continue
        if job["status"] == "ELIGIBLE" and remaining < 1000:
            job["status"] = "BUDGET_HOLD"
            touch(job)
        elif job["status"] == "BUDGET_HOLD" and remaining >= 1000:
            posting = store.job_postings.get(job["job_posting_id"])
            if campaign["status"] in ("ACTIVE", "PACING_HOLD") and posting is not None \
                    and posting["state"] == "ACTIVE":
                job["status"] = "ELIGIBLE"
                touch(job)
    return remaining


def complete_campaign(campaign):
    """Terminal spend condition: pause every sponsored job, release every hold."""
    campaign["status"] = "COMPLETED"
    for job in store.sponsored_jobs.values():
        if job["campaign_id"] == campaign["id"] and job["status"] != "PAUSED":
            pause_sponsored_job(job)
    for hold in list(store.pacing_holds.values()):
        if hold["campaign_id"] != campaign["id"] or hold["status"] != "ACTIVE":
            continue
        amount = hold["amount_cents"]
        hold["status"] = "RELEASED"
        touch(hold)
        append_ledger(campaign, "RELEASE", -amount, None)
    recompute_held_cents(campaign)


def refresh_campaign_pacing(campaign):
    """Recompute held/remaining posture and derived sponsored-job budget states."""
    recompute_held_cents(campaign)
    if campaign["status"] in ("ACTIVE", "PACING_HOLD"):
        recompute_budget_hold_states(campaign)


# ============================================================== day rollover

def day_rollover(clock):
    """Advance day_open_date / reset daily_spent_cents; returns campaigns_reset."""
    today = logical_day(clock)
    reset = 0
    for campaign in store.campaigns.values():
        if parse_iso(campaign["day_open_date"]) < today:
            campaign["daily_spent_cents"] = 0
            campaign["day_open_date"] = iso(today)
            if campaign["status"] == "PACING_HOLD":
                campaign["status"] = "ACTIVE"
            touch(campaign)
            reset += 1
            recompute_budget_hold_states(campaign)
    for campaign in store.campaigns.values():
        if parse_iso(campaign["day_open_date"]) >= today and campaign["status"] == "ACTIVE":
            recompute_budget_hold_states(campaign)
    return reset


def advance_clock(target):
    """Set the logical clock, firing rollover + freshness re-derivation."""
    store.clock = target
    campaigns_reset = day_rollover(target)
    postings_rederived = rederive_all_postings(target)
    for campaign in store.campaigns.values():
        refresh_campaign_pacing(campaign)
    return campaigns_reset, postings_rederived