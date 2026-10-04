"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from .constants import SEPT_PERIOD_END, SEPT_PERIOD_START

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def document_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "source_type": "COURT",
        "jurisdiction_code": "US",
        "document_type": "CASE",
        "title": f"Test v. Document {n}",
        "raw_citation_string": f"{1000 + n} F.3d {n}",
        "decision_date": "2026-01-15",
    }
    defaults.update(overrides)
    return defaults


def reference_entry(cited_document_id: str, treatment: str = "FOLLOWED", depth: str = "CITED") -> dict:
    return {"cited_document_id": cited_document_id, "treatment": treatment, "depth": depth}


def headnote_payload(**overrides) -> dict:
    defaults = {
        "topic_code": "LITIGATION",
        "headnote_text": "Holding text",
        "synopsis_text": "Synopsis text",
    }
    defaults.update(overrides)
    return defaults


def flat_plan_payload(**overrides) -> dict:
    """The PRD §3.6 worked-example flat plan: 5000 base, 2 included searches /
    1 included view, overage fees 250/105, 15% volume discount at >= 4
    combined overage units."""
    n = _seq()
    defaults = {
        "name": f"Flat Plan {n}",
        "practice_area": "LITIGATION",
        "jurisdiction_scope": "NATIONAL",
        "firm_size_tier": "SMALL",
        "billing_model": "FLAT_RATE",
        "scope_enforcement": "SOFT",
        "government_only": False,
        "cost_recovery_allowed": False,
        "monthly_fee_cents": 5000,
        "included_searches": 2,
        "included_doc_views": 1,
        "overage_search_fee_cents": 250,
        "overage_doc_view_fee_cents": 105,
        "volume_discount_pct": 0.15,
        "discount_threshold_overage_units": 4,
    }
    defaults.update(overrides)
    return defaults


def transactional_plan_payload(**overrides) -> dict:
    """The PRD §3.6 transactional counterpart: 300 per search, 120 per view."""
    n = _seq()
    defaults = {
        "name": f"Txn Plan {n}",
        "practice_area": "ALL",
        "jurisdiction_scope": "FEDERAL",
        "firm_size_tier": "SOLO",
        "billing_model": "TRANSACTIONAL",
        "scope_enforcement": "SOFT",
        "government_only": False,
        "cost_recovery_allowed": False,
        "per_search_fee_cents": 300,
        "per_doc_view_fee_cents": 120,
    }
    defaults.update(overrides)
    return defaults


def account_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "org_name": f"Test Org {n}",
        "account_type": "LAW_FIRM",
        "cost_recovery_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def subscription_payload(account_id: str, plan_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "plan_id": plan_id,
        "period_start": SEPT_PERIOD_START,
        "period_end": SEPT_PERIOD_END,
        "seats_total": 1,
    }
    defaults.update(overrides)
    return defaults


def usage_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "SEARCH",
        "practice_area_tag": "LITIGATION",
    }
    defaults.update(overrides)
    return defaults


def invoice_window_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "period_start": SEPT_PERIOD_START,
        "period_end": SEPT_PERIOD_END,
    }
    defaults.update(overrides)
    return defaults


def license_agreement_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "work_title": f"Treatise {n}",
        "author_name": f"Author {n}",
        "practice_area": "LITIGATION",
        "royalty_basis": "PER_VIEW",
        "per_view_fee_cents": 45,
        "exclusive": False,
        "window_start": "2026-01-01",
        "window_end": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def royalty_statement_payload(license_agreement_id: str, **overrides) -> dict:
    defaults = {
        "license_agreement_id": license_agreement_id,
        "period_start": SEPT_PERIOD_START,
        "period_end": SEPT_PERIOD_END,
    }
    defaults.update(overrides)
    return defaults


def removal_order_payload(document_id: str, **overrides) -> dict:
    defaults = {
        "document_id": document_id,
        "scope": "SEAL",
        "effective_from": "2026-09-01",
        "effective_until": "2026-09-30",
        "reason": "Court order",
    }
    defaults.update(overrides)
    return defaults
