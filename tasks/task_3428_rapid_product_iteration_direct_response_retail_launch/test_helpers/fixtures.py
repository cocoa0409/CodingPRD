"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints only (each test runs against a fresh database). All time-dependent
state is reached through the logical clock: fixtures start from the startup
default 2026-09-01T00:00:00Z (PRD §2.4) and move time forward exclusively via
POST /_clock/set_current_utc. Setup calls use the framework's lenient
get_success_data so a broken precondition surfaces as a clear setup failure
rather than an assertion error.

Segregation-of-duties identity model (PRD §3.4, §3.8): studies are conducted
by sci-anna and substantiated by sci-bob; cases are filed by lc-jane and
settled by lc-john. All roles are opaque (PRD §2.1), so the shared header
constants are safe to use everywhere.
"""
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    air_media_test_payload,
    challenge_claim_study_payload,
    complete_claim_study_payload,
    complete_round_payload,
    create_category_payload,
    create_claim_study_payload,
    create_concept_payload,
    create_insight_payload,
    create_launch_commitment_payload,
    create_media_test_payload,
    create_partner_payload,
    create_patent_case_payload,
    create_replenishment_payload,
    create_retail_agreement_payload,
    create_season_payload,
    create_variant_payload,
    decide_media_payload,
    order_line,
    record_judgment_payload,
    set_clock_payload,
    settle_case_payload,
    tool_variant_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["product_lead_headers"]
SOURCING = TEST_USERS["sourcing_manager_headers"]
SCI_ANNA = TEST_USERS["claims_scientist_headers"]
SCI_BOB = TEST_USERS["claims_scientist_alt_headers"]
MEDIA = TEST_USERS["media_buyer_headers"]
RETAIL = TEST_USERS["retail_exec_headers"]
LC_JANE = TEST_USERS["legal_counsel_headers"]
LC_JOHN = TEST_USERS["legal_counsel_alt_headers"]

# Canonical clock positions used by the launch pipeline fixtures. All are
# reached from the startup default via set_clock calls (PRD §2.4).
LOCK_CLOCK_ISO = "2026-09-10T00:00:00Z"      # momentum 50.0 read; lock advance
GO_LIVE_CLOCK_ISO = "2026-10-16T00:00:00Z"   # review fulfilling need_by 10-15
CANDIDACY_CLOCK_ISO = "2027-06-14T00:00:00Z"  # 241 days after retail-live
RETIRE_CLOCK_ISO = "2027-07-15T00:00:00Z"    # 31 days after candidacy


def iso_plus_days(base_iso: str, days: int) -> str:
    """Add whole days to an ISO 8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)."""
    dt = datetime.fromisoformat(base_iso.replace("Z", "+00:00")) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 1: primitive wrappers and state progression
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    """Set the server's logical clock (PRD §2.4). PlatformAdmin only."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    get_success_data(resp)


def reset_clock() -> None:
    """Re-assert the startup default clock (idempotent; PRD §2.4)."""
    set_clock(CLOCK_DEFAULT_ISO)


def create_season(season_code: Optional[str] = None) -> dict:
    resp = api_client.create_season(create_season_payload(season_code), ADMIN)
    return get_success_data(resp)


def get_season(season_id: str) -> dict:
    return get_success_data(api_client.get_season(season_id, ADMIN))


def freeze_season(season_id: str) -> dict:
    return get_success_data(api_client.freeze_season(season_id, ADMIN))


def unfreeze_season(season_id: str) -> dict:
    return get_success_data(api_client.unfreeze_season(season_id, ADMIN))


def run_review(season_id: str) -> dict:
    """Run the ops-review checkpoint; returns the updated season (PRD §3.9)."""
    return get_success_data(api_client.run_review(season_id, ADMIN))


def create_category(season_id: str, name: Optional[str] = None,
                    crowding_base: Optional[int] = None) -> dict:
    resp = api_client.create_category(
        create_category_payload(season_id, name, crowding_base), ADMIN
    )
    return get_success_data(resp)


def get_category(category_id: str) -> dict:
    return get_success_data(api_client.get_category(category_id, ADMIN))


def create_concept(category_id: str, title: Optional[str] = None) -> dict:
    resp = api_client.create_concept(create_concept_payload(category_id, title), LEAD)
    return get_success_data(resp)


def get_concept(concept_id: str) -> dict:
    return get_success_data(api_client.get_concept(concept_id, LEAD))


def add_insight(concept_id: str, points: Optional[int] = None,
                observed_at: str = CLOCK_DEFAULT_ISO) -> dict:
    resp = api_client.add_insight(
        concept_id, create_insight_payload(points, observed_at), LEAD
    )
    return get_success_data(resp)


def advance_concept(concept_id: str) -> dict:
    return get_success_data(api_client.advance_concept(concept_id, LEAD))


def create_open_round(concept_id: str) -> dict:
    return get_success_data(api_client.create_round(concept_id, LEAD))


def complete_round(round_id: str, score: Optional[int] = None,
                   feedback: Optional[str] = None) -> dict:
    resp = api_client.complete_round(
        round_id, complete_round_payload(score, feedback), LEAD
    )
    return get_success_data(resp)


def create_partner(name: Optional[str] = None,
                   capacity_units_total: Optional[int] = None) -> dict:
    resp = api_client.create_partner(
        create_partner_payload(name, capacity_units_total), SOURCING
    )
    return get_success_data(resp)


def get_partner(partner_id: str) -> dict:
    return get_success_data(api_client.get_partner(partner_id, SOURCING))


def create_variant(concept_id: str, model_number: Optional[str] = None,
                   channel: Optional[str] = None) -> dict:
    resp = api_client.create_variant(
        create_variant_payload(concept_id, model_number, channel), LEAD
    )
    return get_success_data(resp)


def get_variant(variant_id: str) -> dict:
    return get_success_data(api_client.get_variant(variant_id, LEAD))


def tool_variant(variant_id: str, partner_id: str) -> dict:
    resp = api_client.tool_variant(variant_id, tool_variant_payload(partner_id), SOURCING)
    return get_success_data(resp)


def create_claim_study(variant_id: str, claim_text: Optional[str] = None,
                       conductor_headers: Optional[dict] = None) -> dict:
    resp = api_client.create_claim_study(
        create_claim_study_payload(variant_id, claim_text),
        conductor_headers or SCI_ANNA,
    )
    return get_success_data(resp)


def complete_claim_study(study_id: str, our_metric: Optional[float] = None,
                         baseline_metric: Optional[float] = None,
                         sample_size: Optional[int] = None,
                         conductor_headers: Optional[dict] = None) -> dict:
    resp = api_client.complete_claim_study(
        study_id,
        complete_claim_study_payload(our_metric, baseline_metric, sample_size),
        conductor_headers or SCI_ANNA,
    )
    return get_success_data(resp)


def substantiate_claim_study(study_id: str,
                             substantiator_headers: Optional[dict] = None) -> dict:
    """Substantiate with a DIFFERENT scientist than the conductor (PRD §3.4)."""
    resp = api_client.substantiate_claim_study(study_id, substantiator_headers or SCI_BOB)
    return get_success_data(resp)


def challenge_claim_study(study_id: str, reason: Optional[str] = None) -> dict:
    resp = api_client.challenge_claim_study(
        study_id, challenge_claim_study_payload(reason), LC_JANE
    )
    return get_success_data(resp)


def retest_claim_study(study_id: str,
                       scientist_headers: Optional[dict] = None) -> dict:
    resp = api_client.retest_claim_study(study_id, scientist_headers or SCI_ANNA)
    return get_success_data(resp)


def create_media_test(variant_id: str, title: Optional[str] = None,
                      media_spend_cents: Optional[int] = None) -> dict:
    resp = api_client.create_media_test(
        create_media_test_payload(variant_id, title, media_spend_cents), MEDIA
    )
    return get_success_data(resp)


def air_media_test(media_id: str, projected_gross_cents: Optional[int] = None) -> dict:
    resp = api_client.air_media_test(
        media_id, air_media_test_payload(projected_gross_cents), MEDIA
    )
    return get_success_data(resp)


def decide_media_test(media_id: str, decision: str,
                      order_lines: Optional[list] = None) -> dict:
    resp = api_client.decide_media_test(
        media_id, decide_media_payload(decision, order_lines), MEDIA
    )
    return get_success_data(resp)


def create_retail_agreement(category_id: str, retailer_name: Optional[str] = None,
                            exclusive: bool = True,
                            window_start: Optional[str] = None,
                            window_end: Optional[str] = None,
                            min_launch_units: Optional[int] = None) -> dict:
    resp = api_client.create_retail_agreement(
        create_retail_agreement_payload(
            category_id, retailer_name, exclusive, window_start, window_end,
            min_launch_units,
        ),
        RETAIL,
    )
    return get_success_data(resp)


def get_retail_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_retail_agreement(agreement_id, RETAIL))


def sign_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.sign_retail_agreement(agreement_id, RETAIL))


def create_commitment(agreement_id: str, agreement_version: int, variant_id: str,
                      committed_units: Optional[int] = None,
                      need_by_date: Optional[str] = None) -> dict:
    """Create a launch commitment carrying the OCC field
    expected_agreement_version (PRD §2.8)."""
    resp = api_client.create_launch_commitment(
        create_launch_commitment_payload(
            agreement_id, variant_id, agreement_version, committed_units, need_by_date
        ),
        SOURCING,
    )
    return get_success_data(resp)


def get_commitment(commitment_id: str) -> dict:
    return get_success_data(api_client.get_launch_commitment(commitment_id, SOURCING))


def cancel_commitment(commitment_id: str) -> dict:
    return get_success_data(api_client.cancel_launch_commitment(commitment_id, SOURCING))


def create_replenishment(variant_id: str, variant_version: int,
                         weekly_velocity: Optional[int] = None,
                         on_hand_units: Optional[int] = None,
                         in_transit_units: Optional[int] = None,
                         case_pack_units: Optional[int] = None) -> dict:
    """Place a replenishment order carrying the OCC field
    expected_variant_version (PRD §2.8)."""
    resp = api_client.create_replenishment_order(
        create_replenishment_payload(
            variant_id, variant_version, weekly_velocity, on_hand_units,
            in_transit_units, case_pack_units,
        ),
        RETAIL,
    )
    return get_success_data(resp)


def file_case(category_id: str, case_number: Optional[str] = None,
              claim_cents: Optional[int] = None, severity: Optional[str] = None,
              filer_headers: Optional[dict] = None) -> dict:
    resp = api_client.create_patent_case(
        create_patent_case_payload(category_id, case_number, claim_cents, severity),
        filer_headers or LC_JANE,
    )
    return get_success_data(resp)


def settle_case(case_id: str, settlement_cents: Optional[int] = None,
                settler_headers: Optional[dict] = None) -> dict:
    """Settle with a DIFFERENT counsel than the filer (PRD §3.8)."""
    resp = api_client.settle_patent_case(
        case_id, settle_case_payload(settlement_cents), settler_headers or LC_JOHN
    )
    return get_success_data(resp)


def record_judgment(case_id: str, outcome: str,
                    award_cents: Optional[int] = None) -> dict:
    resp = api_client.record_judgment(
        case_id, record_judgment_payload(outcome, award_cents), LC_JANE
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_season_with_category(season_code: Optional[str] = None,
                               category_name: Optional[str] = None,
                               crowding_base: Optional[int] = None,
                               set_default_clock: bool = True) -> dict:
    """Season + category workspace. Returns {"season", "category"}."""
    if set_default_clock:
        reset_clock()
    season = create_season(season_code)
    category = create_category(season["id"], category_name, crowding_base)
    return {"season": season, "category": category}


def setup_engineering_locked_concept(category_id: str,
                                     title: Optional[str] = None,
                                     lock_clock: str = LOCK_CLOCK_ISO,
                                     round_score: int = 80) -> dict:
    """Walk a concept IDENTIFIED -> RESEARCHING -> CONCEPT_LOCKED ->
    PROTOTYPE_CYCLING -> ENGINEERING_LOCKED (PRD §3.2).

    Insights: 40 points observed at the startup default clock plus 16 points
    observed 2026-09-08; at the 2026-09-10 lock clock the first insight is one
    full week old (decayed to 34.0) and the second is zero weeks old, so
    momentum is exactly 50.0 — above the inclusive 40.0 lock gate.
    """
    concept = create_concept(category_id, title)
    add_insight(concept["id"], 40, "2026-09-01T00:00:00Z")
    add_insight(concept["id"], 16, "2026-09-08T00:00:00Z")
    set_clock(lock_clock)
    advance_concept(concept["id"])  # IDENTIFIED -> RESEARCHING (insight gate)
    advance_concept(concept["id"])  # RESEARCHING -> CONCEPT_LOCKED (momentum 50.0)
    advance_concept(concept["id"])  # CONCEPT_LOCKED -> PROTOTYPE_CYCLING
    round_ = create_open_round(concept["id"])
    complete_round(round_["id"], round_score)
    advance_concept(concept["id"])  # PROTOTYPE_CYCLING -> ENGINEERING_LOCKED
    return get_concept(concept["id"])


def setup_tooled_variant(category_id: str,
                         model_number: Optional[str] = None,
                         channel: Optional[str] = None,
                         partner_name: Optional[str] = None,
                         partner_capacity: Optional[int] = None) -> dict:
    """ENGINEERING_LOCKED concept + ACTIVE partner + variant tooled at it.
    Returns {"concept", "partner", "variant"} (variant lifecycle TOOLED)."""
    concept = setup_engineering_locked_concept(category_id)
    partner = create_partner(partner_name, partner_capacity)
    variant = create_variant(concept["id"], model_number, channel)
    variant = tool_variant(variant["id"], partner["id"])
    return {"concept": concept, "partner": partner, "variant": variant}


def setup_draft_variants(concept_id: str,
                         specs: Optional[List[Tuple[str, str]]] = None) -> List[dict]:
    """Create N DRAFT variants on one concept. specs: (model_number, channel)."""
    if specs is None:
        specs = [("CV100-AMZ", "AMAZON"), ("CV200-BBX", "BIG_BOX"), ("CV300-CLB", "CLUB")]
    return [create_variant(concept_id, model, channel) for model, channel in specs]


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts (claims, media, agreements, commitments)
# ---------------------------------------------------------------------------

def setup_substantiated_study(variant_id: str,
                              claim_text: Optional[str] = None,
                              our_metric: Optional[float] = None,
                              baseline_metric: Optional[float] = None,
                              sample_size: Optional[int] = None) -> dict:
    """Study RUNNING -> RESULTS_RECORDED -> SUBSTANTIATED with the conductor /
    substantiator split (PRD §3.4); flips the variant's claim_clearance to
    SUBSTANTIATED. Default metrics 115/100 give margin exactly 0.15."""
    study = create_claim_study(variant_id, claim_text, conductor_headers=SCI_ANNA)
    study = complete_claim_study(
        study["id"], our_metric, baseline_metric, sample_size,
        conductor_headers=SCI_ANNA,
    )
    study = substantiate_claim_study(study["id"], substantiator_headers=SCI_BOB)
    return study


def setup_airing_media(variant_id: str, title: Optional[str] = None,
                       media_spend_cents: Optional[int] = None,
                       projected_gross_cents: Optional[int] = None) -> dict:
    """Media test EDITING -> AIRING (PRD §3.5). Requires the variant's
    claim_clearance SUBSTANTIATED and the owning season not GUARDED; a TOOLED
    variant advances to DR_TESTING on airing."""
    media = create_media_test(variant_id, title, media_spend_cents)
    return air_media_test(media["id"], projected_gross_cents)


def setup_decided_scale_media(variant_id: str,
                              media_spend_cents: Optional[int] = None,
                              projected_gross_cents: Optional[int] = None) -> dict:
    """Media test aired then decided SCALE with a single 5000-cent order line
    (settled ratio 4.25, inside the >= 2.0 scale band). Returns the
    DECIDED_SCALE media test."""
    media = setup_airing_media(
        variant_id, media_spend_cents=media_spend_cents,
        projected_gross_cents=projected_gross_cents,
    )
    return decide_media_test(media["id"], "SCALE", [order_line(5000)])


def setup_signed_agreement(category_id: str, retailer_name: Optional[str] = None,
                           exclusive: bool = True,
                           window_start: Optional[str] = None,
                           window_end: Optional[str] = None,
                           min_launch_units: Optional[int] = None) -> dict:
    """Agreement DRAFT -> SIGNED (PRD §3.6). Returns the signed agreement whose
    version is the value to pass as expected_agreement_version on the next
    commitment create."""
    agreement = create_retail_agreement(
        category_id, retailer_name, exclusive, window_start, window_end,
        min_launch_units,
    )
    return sign_agreement(agreement["id"])


def setup_launch_ready(category_id: str,
                       model_number: Optional[str] = None,
                       partner_capacity: Optional[int] = None) -> dict:
    """Variant DR_TESTING with clearance SUBSTANTIATED and a DECIDED_SCALE
    media test — the retail-readiness gate state of PRD §3.6.
    Returns {"concept", "partner", "variant", "study", "media"}."""
    bundle = setup_tooled_variant(
        category_id, model_number=model_number, partner_capacity=partner_capacity
    )
    study = setup_substantiated_study(bundle["variant"]["id"])
    media = setup_decided_scale_media(bundle["variant"]["id"])
    bundle["study"] = study
    bundle["media"] = media
    bundle["variant"] = get_variant(bundle["variant"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 4/5: review-driven pipelines and terminal states
# ---------------------------------------------------------------------------

def setup_retail_live_fulfilled(season_code: Optional[str] = None,
                                committed_units: Optional[int] = None,
                                partner_capacity: Optional[int] = None) -> dict:
    """Full launch pipeline ending in a RETAIL_LIVE variant whose commitment
    was FULFILLED by the go-live review (PRD §3.9 steps 5 and 8).

    Backbone: season/category -> ENGINEERING_LOCKED concept -> partner ->
    TOOLED variant -> SUBSTANTIATED study -> media AIRING -> DECIDED_SCALE ->
    agreement SIGNED [2026-10-01, 2027-01-01) -> commitment (need_by
    2026-10-15) -> clock 2026-10-16 -> run-review.

    Postconditions: commitment FULFILLED (need_by before the review clock),
    variant RETAIL_LIVE, partner allocated_units back to 0, review_index 1.
    Returns the full entity bundle with post-review re-reads.
    """
    base = setup_season_with_category(season_code)
    bundle = setup_launch_ready(base["category"]["id"],
                                partner_capacity=partner_capacity)
    agreement = setup_signed_agreement(base["category"]["id"])
    commitment = create_commitment(
        agreement["id"], agreement["version"], bundle["variant"]["id"],
        committed_units=committed_units, need_by_date="2026-10-15T00:00:00Z",
    )
    set_clock(GO_LIVE_CLOCK_ISO)
    season = run_review(base["season"]["id"])
    bundle.update({
        "season": season,
        "category": get_category(base["category"]["id"]),
        "agreement": get_retail_agreement(agreement["id"]),
        "commitment": get_commitment(commitment["id"]),
        "variant": get_variant(bundle["variant"]["id"]),
        "partner": get_partner(bundle["partner"]["id"]),
    })
    return bundle


def setup_retail_live_open_commitment(season_code: Optional[str] = None,
                                      committed_units: Optional[int] = None,
                                      need_by_date: str = "2027-08-01T00:00:00Z",
                                      window_end: str = "2028-01-01T00:00:00Z",
                                      partner_capacity: Optional[int] = None) -> dict:
    """Full launch pipeline ending RETAIL_LIVE with the commitment still OPEN
    (long agreement window [2026-10-01, 2028-01-01) and a future need_by), so
    the partner holds the committed units in allocated_units.

    Postconditions: variant RETAIL_LIVE (step 8 admits an OPEN commitment),
    commitment OPEN, partner allocated_units == committed_units.
    """
    base = setup_season_with_category(season_code)
    bundle = setup_launch_ready(base["category"]["id"],
                                partner_capacity=partner_capacity)
    agreement = setup_signed_agreement(base["category"]["id"], window_end=window_end)
    commitment = create_commitment(
        agreement["id"], agreement["version"], bundle["variant"]["id"],
        committed_units=committed_units, need_by_date=need_by_date,
    )
    set_clock(GO_LIVE_CLOCK_ISO)
    season = run_review(base["season"]["id"])
    bundle.update({
        "season": season,
        "category": get_category(base["category"]["id"]),
        "agreement": get_retail_agreement(agreement["id"]),
        "commitment": get_commitment(commitment["id"]),
        "variant": get_variant(bundle["variant"]["id"]),
        "partner": get_partner(bundle["partner"]["id"]),
    })
    return bundle


def advance_variant_to_refresh_candidate(bundle: dict) -> dict:
    """From a retail-live bundle: move the clock to 241 days after
    retail_live_at and run the review (PRD §3.9 step 9). Returns the bundle
    with the variant re-read at REFRESH_CANDIDATE."""
    set_clock(CANDIDACY_CLOCK_ISO)
    bundle["season"] = run_review(bundle["season"]["id"])
    bundle["variant"] = get_variant(bundle["variant"]["id"])
    bundle["partner"] = get_partner(bundle["partner"]["id"])
    return bundle


def advance_variant_to_retired(bundle: dict) -> dict:
    """From a refresh-candidate bundle: move the clock 31 days past candidacy
    and run the review (PRD §3.9 step 10). Retirement cascades: OPEN
    commitments and replenishments on the variant are CANCELLED and the
    partner's allocated_units recompute."""
    set_clock(RETIRE_CLOCK_ISO)
    bundle["season"] = run_review(bundle["season"]["id"])
    bundle["variant"] = get_variant(bundle["variant"]["id"])
    bundle["partner"] = get_partner(bundle["partner"]["id"])
    if "commitment" in bundle:
        bundle["commitment"] = get_commitment(bundle["commitment"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Litigation / posture scenario fixtures (PRD §3.8, §3.9)
# ---------------------------------------------------------------------------

def setup_severe_guarded_season(season_code: Optional[str] = None) -> dict:
    """Category (crowding_base 6) with two FILED cases — HIGH claim 2_000_000
    filed by lc-jane plus MED claim 500_000 — pushing the exposure index to
    6 + 9 + 5 = 20, banding SEVERE and flipping the season OPEN -> GUARDED at
    review_index 0 (PRD §3.8 contagion).

    Returns {"season", "category", "case_high", "case_med"}.
    """
    base = setup_season_with_category(season_code)
    case_high = file_case(base["category"]["id"], "PT-5001", 2_000_000, "HIGH",
                          filer_headers=LC_JANE)
    case_med = file_case(base["category"]["id"], "PT-5002", 500_000, "MED",
                         filer_headers=LC_JANE)
    return {
        "season": get_season(base["season"]["id"]),
        "category": get_category(base["category"]["id"]),
        "case_high": case_high,
        "case_med": case_med,
    }


def setup_active_high_case(season_code: Optional[str] = None) -> dict:
    """Category (crowding_base 6) with one HIGH case (claim 2_000_000) filed by
    lc-jane and activated by a run-review (PRD §3.9 step 1): exposure index 15,
    level ELEVATED, season still OPEN, review_index 1. The case is ACTIVE and
    therefore judgment-ready (PRD §3.8).

    Returns {"season", "category", "case"} with post-review re-reads.
    """
    base = setup_season_with_category(season_code)
    case = file_case(base["category"]["id"], "PT-2001", 2_000_000, "HIGH",
                     filer_headers=LC_JANE)
    season = run_review(base["season"]["id"])
    return {
        "season": season,
        "category": get_category(base["category"]["id"]),
        "case": case,
    }


__all__ = [
    "ADMIN",
    "LEAD",
    "SOURCING",
    "SCI_ANNA",
    "SCI_BOB",
    "MEDIA",
    "RETAIL",
    "LC_JANE",
    "LC_JOHN",
    "LOCK_CLOCK_ISO",
    "GO_LIVE_CLOCK_ISO",
    "CANDIDACY_CLOCK_ISO",
    "RETIRE_CLOCK_ISO",
    "iso_plus_days",
    "set_clock",
    "reset_clock",
    "create_season",
    "get_season",
    "freeze_season",
    "unfreeze_season",
    "run_review",
    "create_category",
    "get_category",
    "create_concept",
    "get_concept",
    "add_insight",
    "advance_concept",
    "create_open_round",
    "complete_round",
    "create_partner",
    "get_partner",
    "create_variant",
    "get_variant",
    "tool_variant",
    "create_claim_study",
    "complete_claim_study",
    "substantiate_claim_study",
    "challenge_claim_study",
    "retest_claim_study",
    "create_media_test",
    "air_media_test",
    "decide_media_test",
    "create_retail_agreement",
    "get_retail_agreement",
    "sign_agreement",
    "create_commitment",
    "get_commitment",
    "cancel_commitment",
    "create_replenishment",
    "file_case",
    "settle_case",
    "record_judgment",
    "setup_season_with_category",
    "setup_engineering_locked_concept",
    "setup_tooled_variant",
    "setup_draft_variants",
    "setup_substantiated_study",
    "setup_airing_media",
    "setup_decided_scale_media",
    "setup_signed_agreement",
    "setup_launch_ready",
    "setup_retail_live_fulfilled",
    "setup_retail_live_open_commitment",
    "advance_variant_to_refresh_candidate",
    "advance_variant_to_retired",
    "setup_severe_guarded_season",
    "setup_active_high_case",
]
