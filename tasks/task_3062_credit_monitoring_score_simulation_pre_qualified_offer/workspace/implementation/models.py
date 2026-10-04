"""Public serialisation of every entity, honouring the common-field exceptions."""

from datetime import datetime

import store
from envelope import plain_timestamp

# Dated resource fields reported without fractional digits; created_at and
# updated_at keep the three-digit form required by PRD 2.10.
PLAIN_INSTANT_FIELDS = {
    "monitoring_consent_at", "pulled_at", "evaluated_at", "decided_at",
    "fresh_until", "consented_at", "sealed_at", "intent_recorded_at",
    "render_intent_recorded_at", "funded_at", "reversed_at", "recognized_at",
    "go_live_at", "expiry_at", "requested_at",
}

CONSUMER_FIELDS = [
    "id", "full_name", "email", "state_code", "dti_pct", "bureau_pin",
    "monitoring_consent_at", "monitoring_posture", "status", "archive_status",
    "score_version", "current_score", "previous_score", "utilization_pct",
    "open_dispute_count", "created_at", "updated_at", "version",
]

SNAPSHOT_FIELDS = [
    "id", "consumer_id", "snapshot_ordinal", "pulled_at", "score",
    "added_account_count", "total_revolving_balance_cents",
    "credit_limit_total_cents", "overall_credit_utilization_pct",
    "factor_codes", "status", "created_at", "updated_at", "version",
]

FACTOR_FIELDS = ["id", "snapshot_id", "factor_code", "direction",
                 "impact_points", "rank_index", "created_at"]

ALERT_FIELDS = ["id", "consumer_id", "alert_kind", "threshold_used",
                "from_score", "to_score", "channel", "status", "evaluated_at",
                "created_at", "updated_at", "version"]

ALERT_THRESHOLD_FIELDS = ["id", "consumer_id", "threshold_override_points",
                          "created_at", "updated_at", "version"]

SIMULATION_FIELDS = ["id", "consumer_id", "baseline_ordinal", "baseline_score",
                     "base_utilization_pct", "actions", "projected_score",
                     "delta_points", "tier_code", "status",
                     "created_at", "updated_at", "version"]

CATALOG_FIELDS = ["id", "product_kind", "product_name", "min_score", "max_score",
                  "max_dti_pct", "status", "created_at", "updated_at", "version"]

LENDER_FIELDS = ["id", "lender_name", "compliance_status", "states_served",
                 "status", "created_at", "updated_at", "version"]

PROGRAM_FIELDS = ["id", "lender_id", "product_catalog_item_id", "program_name",
                  "program_code", "min_modeled_score", "max_dti_pct",
                  "max_eligible_utilization_pct", "annual_fee_cents",
                  "intro_apr_bps", "go_live_at", "expiry_at",
                  "revenue_share_bps", "clawback_rate_bps", "clawback_days",
                  "status", "created_at", "updated_at", "version"]

CRITERION_FIELDS = ["id", "lender_program_id", "criterion_field", "operator",
                    "criterion_value", "is_hard_requirement",
                    "created_at", "updated_at", "version"]

DECISION_FIELDS = ["id", "consumer_id", "lender_program_id", "snapshot_id",
                   "snapshot_ordinal_used", "modeled_odds_pct",
                   "modeled_odds_settled", "decision_status",
                   "disqualifying_criteria", "reason", "decided_at",
                   "fresh_until", "created_at", "updated_at", "version"]

CONSENT_FIELDS = ["id", "consumer_id", "decision_id", "consent_method",
                  "consent_scope", "consumer_pii_ciphertext",
                  "lender_routing_netloc", "status", "consented_at",
                  "sealed_at", "archive_status", "created_at"]

REFERRAL_FIELDS = ["id", "consumer_id", "decision_id", "external_referral_ref",
                   "channel", "revenue_share_bps", "clawback_days", "status",
                   "funded_amount_cents", "funded_at", "reversed_at",
                   "created_at", "updated_at", "version"]

DISPUTE_FIELDS = ["id", "consumer_id", "snapshot_id", "referral_id",
                  "referral_count", "inaccuracy_type", "narrative",
                  "bureau_case_ref", "education_code", "status",
                  "created_at", "updated_at", "version"]

REVENUE_FIELDS = ["id", "consumer_id", "referral_id", "entry_kind",
                  "realized_amount_cents", "recognized_at", "created_at"]

TIER_FIELDS = ["id", "tier_code", "min_score", "max_score", "factor_catalog",
               "status", "created_at", "updated_at", "version"]

OFFER_FIELDS = ["id", "decision_id", "consumer_id", "lender_program_id",
                "product_kind", "channel", "intent_recorded_at",
                "render_intent_recorded_at", "status",
                "created_at", "updated_at", "version"]

POLICY_FIELDS = ["id", "consumer_id", "blanket_presentation_override",
                 "content_quality_override", "render_posture",
                 "created_at", "updated_at", "version"]

FACET_FIELDS = ["id", "consumer_id", "topic", "score_bps", "status",
                "created_at", "updated_at", "version"]

CAP_FIELDS = ["id", "consumer_id", "product_kind", "presented_count",
              "presentation_cap_bps", "exceeds_cap",
              "created_at", "updated_at", "version"]

OPS_RUN_FIELDS = ["id", "run_key", "status", "stages_passed", "requested_at",
                  "created_at", "updated_at", "version"]


def _project(row, fields):
    out = {}
    for f in fields:
        value = row.get(f)
        if f in PLAIN_INSTANT_FIELDS and isinstance(value, datetime):
            value = plain_timestamp(value)
        out[f] = value
    return out


def consumer(row):
    return _project(row, CONSUMER_FIELDS)


def snapshot(row):
    return _project(row, SNAPSHOT_FIELDS)


def factor(row):
    return _project(row, FACTOR_FIELDS)


def alert(row):
    return _project(row, ALERT_FIELDS)


def alert_threshold(row):
    return _project(row, ALERT_THRESHOLD_FIELDS)


def simulation(row):
    return _project(row, SIMULATION_FIELDS)


def catalog_item(row):
    return _project(row, CATALOG_FIELDS)


def lender(row):
    return _project(row, LENDER_FIELDS)


def program(row):
    return _project(row, PROGRAM_FIELDS)


def criterion(row):
    return _project(row, CRITERION_FIELDS)


def decision(row, settled_odds=True):
    """A settled decision reports the realized integer odds (0 or 100).

    The calibration calculation consumes the provisional two-decimal value, so
    callers inside the analytics layer pass settled_odds=False (PRD 3.5 / 3.8).
    """
    out = _project(row, DECISION_FIELDS)
    if settled_odds and row.get("modeled_odds_settled") and out.get("modeled_odds_pct") is not None:
        out["modeled_odds_pct"] = 0 if float(row["modeled_odds_pct"]) < 0.5 else 100
    return out


def consent(row):
    """The sealed PII blob is withheld from every read until status is SEALED."""
    out = _project(row, CONSENT_FIELDS)
    if row.get("status") != "SEALED":
        out["consumer_pii_ciphertext"] = None
    return out


def referral(row):
    return _project(row, REFERRAL_FIELDS)


def dispute(row):
    """education_code is derived on read from inaccuracy_type."""
    out = _project(row, DISPUTE_FIELDS)
    out["education_code"] = str(row.get("inaccuracy_type", "")).lower()
    return out


def revenue(row):
    return _project(row, REVENUE_FIELDS)


def tier(row):
    return _project(row, TIER_FIELDS)


def offer(row):
    return _project(row, OFFER_FIELDS)


def policy(row):
    return _project(row, POLICY_FIELDS)


def facet(row):
    return _project(row, FACET_FIELDS)


def cap(row):
    out = _project(row, CAP_FIELDS)
    out["exceeds_cap"] = bool(row.get("exceeds_cap"))
    return out


def ops_run(row):
    return _project(row, OPS_RUN_FIELDS)


def touch(row):
    row["updated_at"] = store.now()
    row["version"] = int(row.get("version", 0)) + 1
    return row