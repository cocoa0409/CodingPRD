"""
Composite setup builders and pytest fixtures.

The harness restarts the service before every test, so each test begins
against an empty database and every precondition has to be built from
scratch. The builder below assembles the recurring chains — an active
campaign with a calendar slot, an approved brief with an expert who has the
capacity to hold it, a committed content item, a review fork carried through
to ``READY``, a published piece with distributions, a substantiated claim
with its evidence dossier, and an asset attached on a licensed channel — so
individual tests only have to express the one thing they are probing.

Every builder re-reads the version it is about to pin, because activation
and every sibling commit move the campaign's ``version`` and every
assignment moves the expert's.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    DEFAULT_CLOCK,
    EFFORT_POINTS_MAX,
    EFFORT_POINTS_MIN,
    FUNNEL_UPLIFT_POINTS,
    POINTS_PER_WORD_BLOCK,
    REGULATED_REVIEW_UPLIFT_POINTS,
    SEARCH_INTENT_BASE_POINTS,
    WORD_BLOCK_SIZE,
)
from .test_users import (
    ACCESSIBILITY_REVIEWER,
    BRAND_REVIEWER,
    LEGAL_REVIEWER,
    MANAGING_EDITOR,
    MANAGING_EDITOR_TWO,
    expert_headers,
)


# ─── Effort arithmetic (PRD 3.3) ──────────────────────

def compute_effort_points(
    search_intent: str,
    target_word_count: int,
    funnel_stage: str,
    requires_regulated_review: bool = False,
) -> int:
    """Reproduce the brief effort formula, including the [6, 40] clamp."""
    raw = SEARCH_INTENT_BASE_POINTS[search_intent]
    raw += POINTS_PER_WORD_BLOCK * math.ceil(target_word_count / WORD_BLOCK_SIZE)
    raw += FUNNEL_UPLIFT_POINTS[funnel_stage]
    if requires_regulated_review:
        raw += REGULATED_REVIEW_UPLIFT_POINTS
    return max(EFFORT_POINTS_MIN, min(EFFORT_POINTS_MAX, raw))


def reserved_hours_for(effort_points: int) -> int:
    """``sme_reserved_hours`` is half the effort points, rounded up."""
    return math.ceil(effort_points / 2)


def brief_params_for_effort(
    target_effort_points: int,
    funnel_stage: str = "CONSIDERATION",
    requires_regulated_review: bool = False,
) -> Dict[str, Any]:
    """
    Find brief inputs whose computed ``effort_points`` equal the target.

    Used when a test needs a specific commitment size on a calendar slot; the
    search runs over the declared search intents and 500-word blocks only, so
    the answer is always a legal payload.
    """
    for search_intent in ("NAVIGATIONAL", "INFORMATIONAL", "COMMERCIAL", "TRANSACTIONAL"):
        for blocks in range(1, 19):
            word_count = blocks * WORD_BLOCK_SIZE
            if word_count > 9000:
                continue
            got = compute_effort_points(
                search_intent, word_count, funnel_stage, requires_regulated_review
            )
            if got == target_effort_points:
                return {
                    "search_intent": search_intent,
                    "target_word_count": word_count,
                    "funnel_stage": funnel_stage,
                    "requires_regulated_review": requires_regulated_review,
                }
    raise ValueError(
        f"No brief inputs reach effort_points {target_effort_points} "
        f"at funnel stage {funnel_stage}"
    )


class EditorialWorkflow:
    """Stateful setup helper bound to one API client and one logical clock."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.clock = DEFAULT_CLOCK
        self._code_counter = 0
        self._expert_counter = 0
        self._keyword_counter = 0
        self._slug_counter = 0
        self._window_counter = 0

    # ─── Logical clock (PRD 2.4) ──────────────────────

    def set_clock(self, current_utc: str) -> str:
        data = get_success_data(self.api.set_clock(current_utc, MANAGING_EDITOR))
        self.clock = data["current_utc"]
        return self.clock

    def advance_clock(self, **offset: int) -> str:
        return self.set_clock(f.shift_instant(self.clock, **offset))

    # ─── Naming helpers ───────────────────────────────

    def next_code(self, prefix: str = "CMP") -> str:
        self._code_counter += 1
        return f"{prefix}-{self._code_counter:03d}"

    def next_keyword(self) -> str:
        self._keyword_counter += 1
        return f"editorial topic {self._keyword_counter}"

    def next_slug(self) -> str:
        self._slug_counter += 1
        return f"editorial-piece-{self._slug_counter}"

    def next_expert_name(self) -> str:
        self._expert_counter += 1
        return f"Reviewer Number {self._expert_counter}"

    # ─── Campaigns (PRD 3.1) ──────────────────────────

    def create_campaign(self, **overrides: Any) -> Dict[str, Any]:
        overrides.setdefault("code", self.next_code())
        return get_success_data(
            self.api.create_campaign(f.campaign_payload(**overrides), MANAGING_EDITOR)
        )

    def activate_campaign(self, campaign_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.activate_campaign(campaign_id, MANAGING_EDITOR)
        )

    def active_campaign(self, **overrides: Any) -> Dict[str, Any]:
        campaign = self.create_campaign(**overrides)
        return self.activate_campaign(campaign["id"])

    def read_campaign(self, campaign_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_campaign(campaign_id, MANAGING_EDITOR))

    def campaign_version(self, campaign_id: str) -> int:
        return self.read_campaign(campaign_id)["version"]

    # ─── Calendar slots (PRD 3.1) ─────────────────────

    def create_slot(
        self,
        campaign_id: str,
        week_start_date: str = "2026-08-03",
        funnel_stage: str = "CONSIDERATION",
        capacity_points: int = 40,
        **overrides: Any,
    ) -> Dict[str, Any]:
        payload = f.calendar_slot_payload(
            week_start_date=week_start_date,
            funnel_stage=funnel_stage,
            capacity_points=capacity_points,
            **overrides,
        )
        return get_success_data(
            self.api.create_calendar_slot(campaign_id, payload, MANAGING_EDITOR)
        )

    def read_slot(self, slot_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_calendar_slot(slot_id, MANAGING_EDITOR))

    def lock_slot(self, slot_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.lock_calendar_slot(slot_id, MANAGING_EDITOR)
        )

    # ─── Experts (PRD 3.2) ────────────────────────────

    def create_expert(
        self,
        expertise_tags: Optional[List[str]] = None,
        weekly_capacity_hours: int = 40,
        **overrides: Any,
    ) -> Dict[str, Any]:
        overrides.setdefault("full_name", self.next_expert_name())
        payload = f.expert_payload(
            expertise_tags=expertise_tags or ["cloud-security"],
            weekly_capacity_hours=weekly_capacity_hours,
            **overrides,
        )
        return get_success_data(self.api.create_expert(payload, MANAGING_EDITOR))

    def read_expert(self, expert_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_expert(expert_id, MANAGING_EDITOR))

    def expert_version(self, expert_id: str) -> int:
        return self.read_expert(expert_id)["version"]

    def set_availability(self, expert_id: str, status: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_expert_availability(expert_id, status, MANAGING_EDITOR)
        )

    # ─── Briefs (PRD 3.3) ─────────────────────────────

    def next_window(self, hours: int, week_monday: str = "2026-08-03") -> Dict[str, str]:
        """
        Allocate a fresh whole-hour review window inside one ISO week.

        Successive calls never overlap, so a single expert can hold several
        briefs without tripping the review-window exclusivity rule.
        """
        start_hour = self._window_counter
        self._window_counter += hours
        opening = f.week_start_instant(week_monday)
        start = f.shift_instant(opening, hours=start_hour)
        return {
            "review_window_start": start,
            "review_window_end": f.shift_instant(start, hours=hours),
        }

    def create_brief(
        self,
        campaign_id: str,
        funnel_stage: str = "CONSIDERATION",
        effort_points: Optional[int] = None,
        required_expertise_tag: str = "cloud-security",
        requires_regulated_review: bool = False,
        week_monday: str = "2026-08-03",
        **overrides: Any,
    ) -> Dict[str, Any]:
        """
        Create a brief, optionally targeting an exact ``effort_points`` figure.

        When ``effort_points`` is given, the search intent and word count are
        chosen so the computed figure lands on it; the review window is then
        sized to the reserved hours the formula implies.
        """
        if effort_points is not None:
            params = brief_params_for_effort(
                effort_points, funnel_stage, requires_regulated_review
            )
            overrides.setdefault("search_intent", params["search_intent"])
            overrides.setdefault("target_word_count", params["target_word_count"])
            hours = reserved_hours_for(effort_points)
        else:
            hours = reserved_hours_for(
                compute_effort_points(
                    overrides.get("search_intent", "COMMERCIAL"),
                    overrides.get("target_word_count", 1500),
                    funnel_stage,
                    requires_regulated_review,
                )
            )
        if "review_window_start" not in overrides:
            overrides.update(self.next_window(hours, week_monday))
        overrides.setdefault("primary_keyword", self.next_keyword())
        payload = f.brief_payload(
            campaign_id,
            funnel_stage=funnel_stage,
            required_expertise_tag=required_expertise_tag,
            requires_regulated_review=requires_regulated_review,
            **overrides,
        )
        return get_success_data(self.api.create_brief(payload, MANAGING_EDITOR))

    def read_brief(self, brief_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_brief(brief_id, MANAGING_EDITOR))

    def assign_sme(self, brief_id: str, expert_id: str) -> Dict[str, Any]:
        """Assign an expert, pinning the version read immediately beforehand."""
        payload = f.assign_sme_payload(expert_id, self.expert_version(expert_id))
        return get_success_data(
            self.api.assign_sme(brief_id, payload, MANAGING_EDITOR)
        )

    def approve_brief(self, brief_id: str, expert_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.approve_brief(brief_id, expert_headers(expert_id))
        )

    def approved_brief(
        self,
        campaign_id: str,
        funnel_stage: str = "CONSIDERATION",
        effort_points: Optional[int] = None,
        expert_id: Optional[str] = None,
        expertise_tag: str = "cloud-security",
        requires_regulated_review: bool = False,
        week_monday: str = "2026-08-03",
        **overrides: Any,
    ) -> Tuple[Dict[str, Any], str]:
        """
        Build a brief all the way to ``APPROVED`` and return it with its expert id.

        A dedicated expert with ample weekly capacity is registered unless one
        is supplied, which keeps the weekly ledger out of the way of tests that
        are not about capacity.
        """
        brief = self.create_brief(
            campaign_id,
            funnel_stage=funnel_stage,
            effort_points=effort_points,
            required_expertise_tag=expertise_tag,
            requires_regulated_review=requires_regulated_review,
            week_monday=week_monday,
            **overrides,
        )
        if expert_id is None:
            expert_id = self.create_expert(
                expertise_tags=[expertise_tag], weekly_capacity_hours=60
            )["id"]
        self.assign_sme(brief["id"], expert_id)
        approved = self.approve_brief(brief["id"], expert_id)
        return approved, expert_id

    # ─── Content items (PRD 3.4) ──────────────────────

    def create_item(
        self,
        brief_id: str,
        slot_id: str,
        campaign_id: str,
        headers: Optional[Dict[str, str]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Commit an item, pinning the campaign version read immediately beforehand."""
        payload = f.content_item_payload(
            brief_id, slot_id, self.campaign_version(campaign_id), **overrides
        )
        return get_success_data(
            self.api.create_content_item(payload, headers or MANAGING_EDITOR)
        )

    def read_item(self, item_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_content_item(item_id, MANAGING_EDITOR))

    def submit(self, item_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.submit_for_review(item_id, MANAGING_EDITOR))

    def gates(self, item_id: str) -> List[Dict[str, Any]]:
        response = self.api.list_review_gates(item_id, MANAGING_EDITOR)
        return get_success_data(response)

    def gate_of(self, item_id: str, gate_type: str) -> Dict[str, Any]:
        for gate in self.gates(item_id):
            if gate["gate_type"] == gate_type:
                return gate
        raise AssertionError(
            f"No {gate_type} gate on item {item_id}; "
            f"gates present: {[g['gate_type'] for g in self.gates(item_id)]}"
        )

    def decide_gate(
        self,
        gate_id: str,
        decision: str,
        headers: Dict[str, str],
        decision_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.decide_review_gate(gate_id, decision, headers, decision_notes)
        )

    def approve_all_gates(
        self,
        item_id: str,
        expert_id: str,
        legal_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Approve every open gate with the one reviewer role authorised for it.

        The SME dimension is decided by the expert assigned to the item's brief,
        because that is the identity the ownership check compares.
        """
        role_headers = {
            "SME": expert_headers(expert_id),
            "LEGAL": legal_headers or LEGAL_REVIEWER,
            "BRAND": BRAND_REVIEWER,
            "ACCESSIBILITY": ACCESSIBILITY_REVIEWER,
        }
        for gate in self.gates(item_id):
            if gate["state"] == "PENDING":
                self.decide_gate(
                    gate["id"], "APPROVED", role_headers[gate["gate_type"]]
                )

    # ─── Composite lifecycles ─────────────────────────

    def committed_item(
        self,
        funnel_stage: str = "CONSIDERATION",
        capacity_points: int = 40,
        effort_points: Optional[int] = None,
        week_monday: str = "2026-08-03",
        planned_publish_at: str = "2026-08-05T09:00:00.000Z",
        persona: str = "PRACTITIONER",
        requires_regulated_review: bool = False,
        **item_overrides: Any,
    ) -> Dict[str, Any]:
        """
        Build an active campaign, a slot, an approved brief and a committed item.

        Returns the campaign, slot, brief, expert id and item so a test can
        assert on any level of the chain.
        """
        campaign = self.active_campaign(persona=persona, primary_funnel_stage=funnel_stage)
        slot = self.create_slot(
            campaign["id"],
            week_start_date=week_monday,
            funnel_stage=funnel_stage,
            capacity_points=capacity_points,
        )
        brief, expert_id = self.approved_brief(
            campaign["id"],
            funnel_stage=funnel_stage,
            effort_points=effort_points,
            requires_regulated_review=requires_regulated_review,
            week_monday=week_monday,
        )
        item = self.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            planned_publish_at=planned_publish_at,
            **item_overrides,
        )
        return {
            "campaign": campaign,
            "slot": slot,
            "brief": brief,
            "expert_id": expert_id,
            "item": item,
        }

    def ready_item(self, **kwargs: Any) -> Dict[str, Any]:
        """Carry a committed item through the review fork to ``READY``."""
        chain = self.committed_item(**kwargs)
        self.submit(chain["item"]["id"])
        self.approve_all_gates(chain["item"]["id"], chain["expert_id"])
        chain["item"] = self.read_item(chain["item"]["id"])
        return chain

    def published_item(
        self,
        scheduled_at: str = "2026-08-05T09:00:00.000Z",
        channels: Optional[List[str]] = None,
        publisher: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Carry an item all the way to ``PUBLISHED``.

        The publisher is a different operator from the creator, because the
        editor who created a piece may not be the one who ships it.
        """
        chain = self.ready_item(**kwargs)
        payload = f.publish_payload(
            scheduled_at=scheduled_at,
            channels=channels or ["OWNED", "EMAIL"],
            url_slug=self.next_slug(),
        )
        get_success_data(
            self.api.publish_content_item(
                chain["item"]["id"], payload, publisher or MANAGING_EDITOR_TWO
            )
        )
        chain["item"] = self.read_item(chain["item"]["id"])
        chain["publish_payload"] = payload
        return chain

    def fill_slot(
        self,
        campaign_id: str,
        slot_id: str,
        points: int,
        funnel_stage: str = "CONSIDERATION",
        week_monday: str = "2026-08-03",
        planned_publish_at: str = "2026-08-04T09:00:00.000Z",
    ) -> Dict[str, Any]:
        """
        Commit filler capacity onto a slot so a later commit meets a chosen tier.

        The filler runs through its own brief and its own expert, so it consumes
        calendar points without disturbing the expert ledger under test.
        """
        brief, _expert_id = self.approved_brief(
            campaign_id,
            funnel_stage=funnel_stage,
            effort_points=points,
            week_monday=week_monday,
        )
        return self.create_item(
            brief["id"],
            slot_id,
            campaign_id,
            planned_publish_at=planned_publish_at,
        )

    # ─── Claims and evidence (PRD 3.6) ────────────────

    def create_claim(
        self, item_id: str, claim_type: str = "PERFORMANCE", **overrides: Any
    ) -> Dict[str, Any]:
        payload = f.claim_payload(claim_type=claim_type, **overrides)
        return get_success_data(
            self.api.create_claim(item_id, payload, MANAGING_EDITOR)
        )

    def file_evidence(self, claim_id: str, **overrides: Any) -> Dict[str, Any]:
        payload = f.evidence_payload(**overrides)
        return get_success_data(
            self.api.file_evidence(claim_id, payload, MANAGING_EDITOR)
        )

    def decide_claim(
        self,
        claim_id: str,
        decision: str = "SUBSTANTIATED",
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.decide_claim(claim_id, decision, headers or LEGAL_REVIEWER)
        )

    def read_claim(self, claim_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_claim(claim_id, MANAGING_EDITOR))

    def substantiated_claim(
        self,
        item_id: str,
        claim_type: str = "PERFORMANCE",
        evidence: Optional[List[Dict[str, Any]]] = None,
        legal_headers: Optional[Dict[str, str]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """
        Attach a claim, file enough evidence to clear its required score, and
        have legal substantiate it.
        """
        claim = self.create_claim(item_id, claim_type=claim_type, **overrides)
        rows = evidence if evidence is not None else self._default_evidence(claim_type)
        for row in rows:
            self.file_evidence(claim["id"], **row)
        self.decide_claim(claim["id"], "SUBSTANTIATED", legal_headers)
        return self.read_claim(claim["id"])

    @staticmethod
    def _default_evidence(claim_type: str) -> List[Dict[str, Any]]:
        """Evidence that clears each claim type's required score under its variant."""
        if claim_type == "REGULATED":
            return [
                {"source_type": "REGULATORY_FILING"},
                {"source_type": "THIRD_PARTY_TEST"},
            ]
        if claim_type == "COMPARISON":
            return [
                {"source_type": "THIRD_PARTY_TEST"},
                {"source_type": "INTERNAL_STUDY"},
            ]
        return [{"source_type": "THIRD_PARTY_TEST"}]

    # ─── Assets and usages (PRD 3.7) ──────────────────

    def create_asset(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_asset(f.asset_payload(**overrides), MANAGING_EDITOR)
        )

    def read_asset(self, asset_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_asset(asset_id, MANAGING_EDITOR))

    def attach_usage(
        self, item_id: str, asset_id: str, channel: str = "OWNED"
    ) -> Dict[str, Any]:
        payload = f.asset_usage_payload(asset_id, channel)
        return get_success_data(
            self.api.attach_asset_usage(item_id, payload, MANAGING_EDITOR)
        )

    def renew_asset(self, asset_id: str, new_license_end: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.renew_asset(asset_id, new_license_end, MANAGING_EDITOR)
        )

    def distributions(self, item_id: str) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_distributions(item_id, MANAGING_EDITOR))

    def usages(self, item_id: str) -> List[Dict[str, Any]]:
        return get_success_data(
            self.api.list_item_asset_usages(item_id, MANAGING_EDITOR)
        )

    # ─── Measurement and audit (PRD 3.9) ──────────────

    def snapshot(
        self,
        item_id: str,
        period_start: str,
        period_end: str,
        headers: Optional[Dict[str, str]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        from .test_users import ANALYTICS_SERVICE

        payload = f.performance_snapshot_payload(period_start, period_end, **overrides)
        return get_success_data(
            self.api.create_performance_snapshot(
                item_id, payload, headers or ANALYTICS_SERVICE
            )
        )

    def audit(self, item_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.audit_content_item(
                item_id, f.audit_payload(**overrides), MANAGING_EDITOR
            )
        )

    # ─── Sweep (PRD 3.11) ─────────────────────────────

    def sweep(self) -> Dict[str, Any]:
        return get_success_data(self.api.run_governance_sweep(MANAGING_EDITOR))


# ─── Pytest fixtures ──────────────────────────────────

@pytest.fixture
def api() -> ApiClient:
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def flow(api: ApiClient) -> EditorialWorkflow:
    """Composite setup builder for the editorial governance workflows."""
    return EditorialWorkflow(api)
