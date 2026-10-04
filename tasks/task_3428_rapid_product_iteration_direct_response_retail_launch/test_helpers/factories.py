"""Payload factories — one per write endpoint, input fields only.

Computed and system-managed fields (posture, exposure_index, margins,
quantity_units, ids, timestamps, versions, ...) are never emitted; per PRD
§2.5/§3 the server mints or derives them and ignores client-supplied values.
"""
from typing import Optional

from .constants import CLOCK_DEFAULT_ISO
from .types import (
    Channel,
    JudgmentOutcome,
    MediaDecision,
    Severity,
)

DEFAULTS = {
    "SEASON_CODE": "FW26",
    "CATEGORY_NAME": "Cordless Vacuums",
    "CROWDING_BASE": 6,
    "CONCEPT_TITLE": "Faster pet-hair pickup",
    "INSIGHT_POINTS": 40,
    "ROUND_SCORE": 80,
    "PARTNER_NAME": "Shenzhen Precision",
    "PARTNER_CAPACITY": 500,
    "MODEL_NUMBER": "CV100-AMZ",
    "CHANNEL": Channel.AMAZON.value,
    "CLAIM_TEXT": "50% more suction than the leading competitor",
    "OUR_METRIC": 115,
    "BASELINE_METRIC": 100,
    "SAMPLE_SIZE": 40,
    "CHALLENGE_REASON": "Competitor dispute letter",
    "MEDIA_TITLE": "Infomercial A",
    "MEDIA_SPEND_CENTS": 1000,
    "PROJECTED_GROSS_CENTS": 1500,
    "RETAILER_NAME": "BigBoxCo",
    "WINDOW_START": "2026-10-01T00:00:00Z",
    "WINDOW_END": "2027-01-01T00:00:00Z",
    "MIN_LAUNCH_UNITS": 100,
    "COMMITTED_UNITS": 300,
    "NEED_BY_DATE": "2026-10-15T00:00:00Z",
    "WEEKLY_VELOCITY": 120,
    "ON_HAND_UNITS": 100,
    "IN_TRANSIT_UNITS": 60,
    "CASE_PACK_UNITS": 24,
    "CASE_NUMBER": "PT-1001",
    "CLAIM_CENTS": 1_000_000,
    "SEVERITY": Severity.MED.value,
    "SETTLEMENT_CENTS": 450_000,
    "AWARD_CENTS": 800_000,
}


# --- Logical clock (PRD §2.4) ----------------------------------------------

def set_clock_payload(to_iso8601: str = CLOCK_DEFAULT_ISO, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# --- Season / category (PRD §3.1) -------------------------------------------

def create_season_payload(season_code: Optional[str] = None, **overrides) -> dict:
    payload = {"season_code": season_code or DEFAULTS["SEASON_CODE"]}
    payload.update(overrides)
    return payload


def create_category_payload(season_id: str, name: Optional[str] = None,
                            crowding_base: Optional[int] = None, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "name": name or DEFAULTS["CATEGORY_NAME"],
        "crowding_base": DEFAULTS["CROWDING_BASE"] if crowding_base is None else crowding_base,
    }
    payload.update(overrides)
    return payload


# --- Concepts / insights / rounds (PRD §3.2) ---------------------------------

def create_concept_payload(category_id: str, title: Optional[str] = None, **overrides) -> dict:
    payload = {
        "category_id": category_id,
        "title": title or DEFAULTS["CONCEPT_TITLE"],
    }
    payload.update(overrides)
    return payload


def create_insight_payload(points: Optional[int] = None,
                           observed_at: str = CLOCK_DEFAULT_ISO, **overrides) -> dict:
    payload = {
        "points": DEFAULTS["INSIGHT_POINTS"] if points is None else points,
        "observed_at": observed_at,
    }
    payload.update(overrides)
    return payload


def complete_round_payload(score: Optional[int] = None,
                           feedback: Optional[str] = None, **overrides) -> dict:
    payload = {"score": DEFAULTS["ROUND_SCORE"] if score is None else score}
    if feedback is not None:
        payload["feedback"] = feedback
    payload.update(overrides)
    return payload


# --- Factory partners / model variants (PRD §3.3) ----------------------------

def create_partner_payload(name: Optional[str] = None,
                           capacity_units_total: Optional[int] = None, **overrides) -> dict:
    payload = {
        "name": name or DEFAULTS["PARTNER_NAME"],
        "capacity_units_total": (DEFAULTS["PARTNER_CAPACITY"]
                                 if capacity_units_total is None else capacity_units_total),
    }
    payload.update(overrides)
    return payload


def create_variant_payload(concept_id: str, model_number: Optional[str] = None,
                           channel: Optional[str] = None, **overrides) -> dict:
    payload = {
        "concept_id": concept_id,
        "model_number": model_number or DEFAULTS["MODEL_NUMBER"],
        "channel": channel or DEFAULTS["CHANNEL"],
    }
    payload.update(overrides)
    return payload


def tool_variant_payload(factory_partner_id: str, **overrides) -> dict:
    payload = {"factory_partner_id": factory_partner_id}
    payload.update(overrides)
    return payload


# --- Claim studies (PRD §3.4) -------------------------------------------------

def create_claim_study_payload(variant_id: str, claim_text: Optional[str] = None,
                               **overrides) -> dict:
    payload = {
        "variant_id": variant_id,
        "claim_text": claim_text or DEFAULTS["CLAIM_TEXT"],
    }
    payload.update(overrides)
    return payload


def complete_claim_study_payload(our_metric: Optional[float] = None,
                                 baseline_metric: Optional[float] = None,
                                 sample_size: Optional[int] = None, **overrides) -> dict:
    payload = {
        "our_metric": DEFAULTS["OUR_METRIC"] if our_metric is None else our_metric,
        "baseline_metric": (DEFAULTS["BASELINE_METRIC"]
                            if baseline_metric is None else baseline_metric),
        "sample_size": DEFAULTS["SAMPLE_SIZE"] if sample_size is None else sample_size,
    }
    payload.update(overrides)
    return payload


def challenge_claim_study_payload(reason: Optional[str] = None, **overrides) -> dict:
    payload = {"reason": reason or DEFAULTS["CHALLENGE_REASON"]}
    payload.update(overrides)
    return payload


# --- Media tests (PRD §3.5) ---------------------------------------------------

def create_media_test_payload(variant_id: str, title: Optional[str] = None,
                              media_spend_cents: Optional[int] = None, **overrides) -> dict:
    payload = {
        "variant_id": variant_id,
        "title": title or DEFAULTS["MEDIA_TITLE"],
        "media_spend_cents": (DEFAULTS["MEDIA_SPEND_CENTS"]
                              if media_spend_cents is None else media_spend_cents),
    }
    payload.update(overrides)
    return payload


def air_media_test_payload(projected_gross_cents: Optional[int] = None, **overrides) -> dict:
    payload = {
        "projected_gross_cents": (DEFAULTS["PROJECTED_GROSS_CENTS"]
                                  if projected_gross_cents is None else projected_gross_cents),
    }
    payload.update(overrides)
    return payload


def order_line(revenue_cents: int, cancels_cents: int = 0, returns_cents: int = 0) -> dict:
    """One per-order entry of a decide payload (PRD §3.5)."""
    return {
        "revenue_cents": revenue_cents,
        "cancels_cents": cancels_cents,
        "returns_cents": returns_cents,
    }


def decide_media_payload(decision: str = MediaDecision.SCALE.value,
                         order_lines: Optional[list] = None, **overrides) -> dict:
    if order_lines is None:
        order_lines = [order_line(5000)]
    payload = {"decision": decision, "order_lines": order_lines}
    payload.update(overrides)
    return payload


# --- Retail agreements / launch commitments (PRD §3.6) ------------------------

def create_retail_agreement_payload(category_id: str,
                                    retailer_name: Optional[str] = None,
                                    exclusive: bool = True,
                                    window_start: Optional[str] = None,
                                    window_end: Optional[str] = None,
                                    min_launch_units: Optional[int] = None,
                                    **overrides) -> dict:
    payload = {
        "category_id": category_id,
        "retailer_name": retailer_name or DEFAULTS["RETAILER_NAME"],
        "exclusive": exclusive,
        "window_start": window_start or DEFAULTS["WINDOW_START"],
        "window_end": window_end or DEFAULTS["WINDOW_END"],
        "min_launch_units": (DEFAULTS["MIN_LAUNCH_UNITS"]
                             if min_launch_units is None else min_launch_units),
    }
    payload.update(overrides)
    return payload


def create_launch_commitment_payload(agreement_id: str, variant_id: str,
                                     expected_agreement_version: int,
                                     committed_units: Optional[int] = None,
                                     need_by_date: Optional[str] = None,
                                     **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "variant_id": variant_id,
        "committed_units": (DEFAULTS["COMMITTED_UNITS"]
                            if committed_units is None else committed_units),
        "need_by_date": need_by_date or DEFAULTS["NEED_BY_DATE"],
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


# --- Replenishment orders (PRD §3.7) ------------------------------------------

def create_replenishment_payload(variant_id: str, expected_variant_version: int,
                                 weekly_velocity: Optional[int] = None,
                                 on_hand_units: Optional[int] = None,
                                 in_transit_units: Optional[int] = None,
                                 case_pack_units: Optional[int] = None,
                                 **overrides) -> dict:
    payload = {
        "variant_id": variant_id,
        "weekly_velocity": (DEFAULTS["WEEKLY_VELOCITY"]
                            if weekly_velocity is None else weekly_velocity),
        "on_hand_units": (DEFAULTS["ON_HAND_UNITS"]
                          if on_hand_units is None else on_hand_units),
        "in_transit_units": (DEFAULTS["IN_TRANSIT_UNITS"]
                             if in_transit_units is None else in_transit_units),
        "case_pack_units": (DEFAULTS["CASE_PACK_UNITS"]
                            if case_pack_units is None else case_pack_units),
        "expected_variant_version": expected_variant_version,
    }
    payload.update(overrides)
    return payload


# --- Patent cases (PRD §3.8) --------------------------------------------------

def create_patent_case_payload(category_id: str, case_number: Optional[str] = None,
                               claim_cents: Optional[int] = None,
                               severity: Optional[str] = None, **overrides) -> dict:
    payload = {
        "category_id": category_id,
        "case_number": case_number or DEFAULTS["CASE_NUMBER"],
        "claim_cents": DEFAULTS["CLAIM_CENTS"] if claim_cents is None else claim_cents,
        "severity": severity or DEFAULTS["SEVERITY"],
    }
    payload.update(overrides)
    return payload


def settle_case_payload(settlement_cents: Optional[int] = None, **overrides) -> dict:
    payload = {
        "settlement_cents": (DEFAULTS["SETTLEMENT_CENTS"]
                             if settlement_cents is None else settlement_cents),
    }
    payload.update(overrides)
    return payload


def record_judgment_payload(outcome: str = JudgmentOutcome.ADVERSE.value,
                            award_cents: Optional[int] = None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if award_cents is not None:
        payload["award_cents"] = award_cents
    payload.update(overrides)
    return payload


__all__ = [
    "DEFAULTS",
    "set_clock_payload",
    "create_season_payload",
    "create_category_payload",
    "create_concept_payload",
    "create_insight_payload",
    "complete_round_payload",
    "create_partner_payload",
    "create_variant_payload",
    "tool_variant_payload",
    "create_claim_study_payload",
    "complete_claim_study_payload",
    "challenge_claim_study_payload",
    "create_media_test_payload",
    "air_media_test_payload",
    "order_line",
    "decide_media_payload",
    "create_retail_agreement_payload",
    "create_launch_commitment_payload",
    "create_replenishment_payload",
    "create_patent_case_payload",
    "settle_case_payload",
    "record_judgment_payload",
]
