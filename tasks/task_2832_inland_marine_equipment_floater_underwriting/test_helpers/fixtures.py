"""Composite setup for the inland marine underwriting record.

The service is relaunched before every individual test, so every test starts
from an empty database and a logical clock sitting at its 2026-08-01T00:00:00Z
default. Every precondition here is therefore built by calling the same public
endpoints a client would call, in five tiers:

1. the client itself;
2. single-resource builders (a published rate cell, a policy, a part, a jobsite,
   a conveyance) that return the created resource;
3. lifecycle drivers (quote, bind, activate, survey, approve) that move one
   resource along its state machine;
4. chain builders that assemble a whole priced or on-risk file and hand back
   every identifier and version token the test will need;
5. the pytest fixtures that wrap the chains the suite reaches for most often.

Setup calls use the lenient success reader, so a broken precondition surfaces as
a setup failure naming the HTTP status and the error identifier rather than as a
confusing assertion deep inside a test.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as fac
from .api_client import ApiClient
from .constants import CLOCK_DEFAULT_UTC
from .test_users import (
    ACTUARY,
    ADJUSTER,
    MANAGER,
    UNDERWRITER,
    make_policyholder_headers,
)
from .types import (
    AdjustmentBasis,
    Ledger,
    TerritoryCode,
)


class Ctx(dict):
    """A dict whose keys are reachable as attributes, for readable chains."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        self[name] = value


# ─── Tier 1: the client ───────────────────────────────────────────────────────

@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the service under test."""
    return ApiClient()


# ─── Tier 2: single-resource builders ─────────────────────────────────────────

def publish_rate_rule(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Draft a rate cell and publish it, so rating can select it."""
    rule = get_success_data(api.create_rate_rule(fac.rate_rule(**kwargs), ACTUARY))
    return get_success_data(api.publish_rate_rule(rule["id"], ACTUARY))


def draft_rate_rule(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Draft a rate cell and leave it unpublished, invisible to rating."""
    return get_success_data(api.create_rate_rule(fac.rate_rule(**kwargs), ACTUARY))


def create_policy(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_policy(fac.policy(**kwargs), UNDERWRITER))


def create_part(api: ApiClient, policy_id: str,
                payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_coverage_part(policy_id, payload, UNDERWRITER))


def policy_version(api: ApiClient, policy_id: str) -> int:
    """Read the owning policy's current version, the OCC token for a schedule add."""
    return get_success_data(api.get_policy(policy_id, UNDERWRITER))["version"]


def part_version(api: ApiClient, part_id: str) -> int:
    """Read the part's current version, the OCC token for a value report."""
    return get_success_data(api.get_coverage_part(part_id, UNDERWRITER))["version"]


def schedule_item(api: ApiClient, part_id: str, policy_id: str,
                  **kwargs: Any) -> Dict[str, Any]:
    """Schedule a unit, reading the policy version token immediately beforehand."""
    version = policy_version(api, policy_id)
    payload = fac.equipment_item(expected_policy_version=version, **kwargs)
    return get_success_data(api.create_equipment_item(part_id, payload, UNDERWRITER))


def create_jobsite(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_jobsite(fac.jobsite(**kwargs), UNDERWRITER))


def survey_jobsite(api: ApiClient, jobsite_id: str,
                   controls: Optional[Dict[str, bool]] = None,
                   **kwargs: Any) -> Dict[str, Any]:
    """Record the four theft controls, scoring and tiering the site."""
    payload = fac.security_survey(**(controls or {}), **kwargs)
    return get_success_data(
        api.record_security_survey(jobsite_id, payload, UNDERWRITER))


def create_vehicle(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_vehicle(fac.vehicle(**kwargs), UNDERWRITER))


def approve_vehicle(api: ApiClient, vehicle_id: str,
                    approval_expires_on: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(api.approve_vehicle(
        vehicle_id, UNDERWRITER, fac.vehicle_approval(approval_expires_on)))


def plan_shipment(api: ApiClient, part_id: str, vehicle_id: str,
                  **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_transit_shipment(
        part_id, fac.transit_shipment(vehicle_id, **kwargs), UNDERWRITER))


def open_floater(api: ApiClient, part_id: str, jobsite_id: str,
                 **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_installation_floater(
        part_id, fac.installation_floater(jobsite_id, **kwargs), UNDERWRITER))


def file_value_report(api: ApiClient, part_id: str, period_start_date: str,
                      period_end_date: str, reported_value_cents: int,
                      headers=None, expected_version: Optional[int] = None
                      ) -> Dict[str, Any]:
    """File a periodic declared value, reading the part version token first."""
    version = expected_version if expected_version is not None else part_version(
        api, part_id)
    payload = fac.value_report(period_start_date, period_end_date,
                               reported_value_cents, version)
    return get_success_data(api.create_value_report(
        part_id, payload, headers or UNDERWRITER))


# ─── Tier 3: lifecycle drivers ────────────────────────────────────────────────

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; the response reports what the move expired."""
    return get_success_data(api.set_clock(current_utc, MANAGER))


def quote(api: ApiClient, policy_id: str) -> Dict[str, Any]:
    return get_success_data(api.quote_policy(policy_id, UNDERWRITER))


def bind(api: ApiClient, policy_id: str) -> Dict[str, Any]:
    return get_success_data(api.bind_policy(policy_id, UNDERWRITER))


def activate(api: ApiClient, policy_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_policy(policy_id, UNDERWRITER))


def activate_item(api: ApiClient, item_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_equipment_item(item_id, UNDERWRITER))


def activate_floater(api: ApiClient, floater_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.activate_installation_floater(floater_id, UNDERWRITER))


def refer_and_approve(api: ApiClient, policy_id: str) -> Dict[str, Any]:
    """Raise a referral as the underwriter and approve it as a different manager."""
    get_success_data(api.refer_policy(policy_id, UNDERWRITER))
    return get_success_data(api.decide_referral(
        policy_id, fac.referral_decision("APPROVE"), MANAGER))


def premium_ledger(api: ApiClient, policy_id: str) -> List[Dict[str, Any]]:
    body = api.list_ledger_entries(policy_id, UNDERWRITER, limit=100, offset=0,
                                   ledger=Ledger.PREMIUM)
    return get_success_data(body)


def loss_ledger(api: ApiClient, policy_id: str) -> List[Dict[str, Any]]:
    body = api.list_ledger_entries(policy_id, UNDERWRITER, limit=100, offset=0,
                                   ledger=Ledger.LOSS)
    return get_success_data(body)


# ─── Tier 4: chain builders ───────────────────────────────────────────────────
#
# The canonical file used across the suite is one T2_URBAN policy running
# 2026-08-01 to 2027-08-01 with a minimum premium of 100000, carrying one
# SCHEDULED_EQUIPMENT part on the actual-cash-value basis and one 2022 excavator
# of 12000000 original cost. That unit is four years old at the clock's default
# date, so it depreciates to an insured value of 8160000 and rates to 173318,
# which loads to a written premium of 180251.

def build_scheduled_file(api: ApiClient,
                         rate_rule_kwargs: Optional[Dict[str, Any]] = None,
                         policy_kwargs: Optional[Dict[str, Any]] = None,
                         part_kwargs: Optional[Dict[str, Any]] = None,
                         item_kwargs: Optional[Dict[str, Any]] = None,
                         with_item: bool = True,
                         quote_it: bool = False) -> Ctx:
    """Publish a rate cell, open a policy, add a scheduled part and one unit."""
    rule = publish_rate_rule(api, **(rate_rule_kwargs or {}))
    pol = create_policy(api, **(policy_kwargs or {}))
    part = create_part(api, pol["id"],
                       fac.scheduled_equipment_part(**(part_kwargs or {})))
    ctx = Ctx(rule=rule, policy=pol, part=part, item=None,
              policy_id=pol["id"], part_id=part["id"], rule_id=rule["id"])
    if with_item:
        ctx["item"] = schedule_item(api, part["id"], pol["id"],
                                    **(item_kwargs or {}))
        ctx["item_id"] = ctx["item"]["id"]
    if quote_it:
        ctx["quoted"] = quote(api, pol["id"])
    return ctx


def build_bound_file(api: ApiClient, **kwargs: Any) -> Ctx:
    """The canonical file taken through quoting to BOUND, writing the initial premium."""
    ctx = build_scheduled_file(api, quote_it=True, **kwargs)
    ctx["bound"] = bind(api, ctx.policy_id)
    return ctx


def build_in_force_file(api: ApiClient, activate_the_item: bool = True,
                        **kwargs: Any) -> Ctx:
    """The canonical file on risk: bound, activated, and its unit put on risk."""
    ctx = build_bound_file(api, **kwargs)
    ctx["in_force"] = activate(api, ctx.policy_id)
    if activate_the_item and ctx.get("item_id"):
        ctx["active_item"] = activate_item(api, ctx["item_id"])
    return ctx


def build_transit_file(api: ApiClient,
                       policy_kwargs: Optional[Dict[str, Any]] = None,
                       part_kwargs: Optional[Dict[str, Any]] = None,
                       quote_it: bool = False) -> Ctx:
    """A policy carrying a single TRANSIT part priced from its own three limits."""
    pol = create_policy(api, **(policy_kwargs or {}))
    part = create_part(api, pol["id"], fac.transit_part(**(part_kwargs or {})))
    ctx = Ctx(policy=pol, part=part, policy_id=pol["id"], part_id=part["id"])
    if quote_it:
        ctx["quoted"] = quote(api, pol["id"])
    return ctx


def build_in_force_transit_file(api: ApiClient, **kwargs: Any) -> Ctx:
    """A TRANSIT file on risk, ready for a conveyance to be dispatched."""
    ctx = build_transit_file(api, quote_it=True, **kwargs)
    ctx["bound"] = bind(api, ctx.policy_id)
    ctx["in_force"] = activate(api, ctx.policy_id)
    return ctx


def build_installation_file(api: ApiClient,
                            jobsite_controls: Optional[Dict[str, bool]] = None,
                            policy_kwargs: Optional[Dict[str, Any]] = None,
                            part_kwargs: Optional[Dict[str, Any]] = None,
                            floater_kwargs: Optional[Dict[str, Any]] = None,
                            with_floater: bool = True,
                            quote_it: bool = False) -> Ctx:
    """A policy with an INSTALLATION_FLOATER part, a jobsite and one floater."""
    pol = create_policy(api, **(policy_kwargs or {}))
    part = create_part(api, pol["id"],
                       fac.installation_floater_part(**(part_kwargs or {})))
    site = create_jobsite(api)
    if jobsite_controls is not None:
        site = survey_jobsite(api, site["id"], jobsite_controls)
    ctx = Ctx(policy=pol, part=part, jobsite=site, policy_id=pol["id"],
              part_id=part["id"], jobsite_id=site["id"], floater=None)
    if with_floater:
        ctx["floater"] = open_floater(api, part["id"], site["id"],
                                     **(floater_kwargs or {}))
        ctx["floater_id"] = ctx["floater"]["id"]
    if quote_it:
        ctx["quoted"] = quote(api, pol["id"])
    return ctx


def build_in_force_installation_file(api: ApiClient,
                                     activate_the_floater: bool = True,
                                     **kwargs: Any) -> Ctx:
    """An installation file on risk with its floater activated."""
    ctx = build_installation_file(api, quote_it=True, **kwargs)
    ctx["bound"] = bind(api, ctx.policy_id)
    ctx["in_force"] = activate(api, ctx.policy_id)
    if activate_the_floater and ctx.get("floater_id"):
        ctx["active_floater"] = activate_floater(api, ctx["floater_id"])
    return ctx


def build_reporting_file(api: ApiClient,
                         policy_kwargs: Optional[Dict[str, Any]] = None,
                         part_kwargs: Optional[Dict[str, Any]] = None,
                         to_in_force: bool = True) -> Ctx:
    """A policy carrying one REPORTING_FORM part, quoted, bound and on risk."""
    pol = create_policy(api, **(policy_kwargs or {}))
    part = create_part(api, pol["id"], fac.reporting_form_part(**(part_kwargs or {})))
    ctx = Ctx(policy=pol, part=part, policy_id=pol["id"], part_id=part["id"])
    ctx["quoted"] = quote(api, pol["id"])
    if to_in_force:
        ctx["bound"] = bind(api, ctx.policy_id)
        ctx["in_force"] = activate(api, ctx.policy_id)
    ctx["policyholder"] = make_policyholder_headers(pol["id"])
    return ctx


def build_claim_on_item(api: ApiClient, ctx: Ctx, loss_date: str = "2026-08-01",
                        **claim_kwargs: Any) -> Dict[str, Any]:
    """Open a claim on the file's scheduled unit."""
    payload = fac.claim(ctx.part_id, loss_date=loss_date,
                        equipment_item_id=ctx["item_id"], **claim_kwargs)
    return get_success_data(api.create_claim(ctx.policy_id, payload, UNDERWRITER))


def build_inspected_claim(api: ApiClient, ctx: Ctx, repair_estimate_cents: int,
                          actual_value_at_loss_cents: int,
                          **claim_kwargs: Any) -> Dict[str, Any]:
    """Open a claim and record the inspection that pre-computes both bases."""
    claim = build_claim_on_item(api, ctx, **claim_kwargs)
    return get_success_data(api.inspect_claim(
        claim["id"],
        fac.inspection(repair_estimate_cents, actual_value_at_loss_cents),
        ADJUSTER))


def build_repair_claim(api: ApiClient, ctx: Ctx,
                       repair_estimate_cents: int = 3000000,
                       actual_value_at_loss_cents: int = 8160000,
                       loss_of_use_days_claimed: Optional[int] = None,
                       **claim_kwargs: Any) -> Dict[str, Any]:
    """Take a claim to REPAIR_APPROVED, leaving the salvage axis dormant."""
    claim = build_inspected_claim(api, ctx, repair_estimate_cents,
                                  actual_value_at_loss_cents, **claim_kwargs)
    return get_success_data(api.adjust_claim(
        claim["id"],
        fac.adjustment(AdjustmentBasis.REPAIR, loss_of_use_days_claimed),
        ADJUSTER))


def build_total_loss_claim(api: ApiClient, ctx: Ctx,
                           repair_estimate_cents: int = 7000000,
                           actual_value_at_loss_cents: int = 8160000,
                           **claim_kwargs: Any) -> Dict[str, Any]:
    """Take a claim to TOTAL_LOSS_DECLARED, arming the salvage axis."""
    claim = build_inspected_claim(api, ctx, repair_estimate_cents,
                                  actual_value_at_loss_cents, **claim_kwargs)
    return get_success_data(api.adjust_claim(
        claim["id"], fac.adjustment(AdjustmentBasis.TOTAL_LOSS), ADJUSTER))


def settle(api: ApiClient, claim_id: str, headers=None) -> Dict[str, Any]:
    """Authorise payment as a manager who is not the declaring adjuster."""
    return get_success_data(api.settle_claim(claim_id, headers or MANAGER))


# ─── Tier 5: the pytest fixtures the suite reaches for most often ─────────────

@pytest.fixture
def excavator_rate_cell(api: ApiClient) -> Dict[str, Any]:
    """A published grade-A excavator cell for T2_URBAN ages 0 to 5 at 180 bp."""
    return publish_rate_rule(api)


@pytest.fixture
def draft_policy(api: ApiClient) -> Dict[str, Any]:
    """One DRAFT T2_URBAN policy running a full year from the clock's default date."""
    return create_policy(api)


@pytest.fixture
def scheduled_file(api: ApiClient) -> Ctx:
    """The canonical DRAFT file: one scheduled part carrying one 2022 excavator."""
    return build_scheduled_file(api)


@pytest.fixture
def quoted_file(api: ApiClient) -> Ctx:
    """The canonical file quoted: part 173318, written premium 180251."""
    return build_scheduled_file(api, quote_it=True)


@pytest.fixture
def bound_file(api: ApiClient) -> Ctx:
    """The canonical file bound, with its 180251 initial premium on the ledger."""
    return build_bound_file(api)


@pytest.fixture
def in_force_file(api: ApiClient) -> Ctx:
    """The canonical file on risk with its unit activated."""
    return build_in_force_file(api)


@pytest.fixture
def rented_leased_file(api: ApiClient) -> Ctx:
    """A rented-and-leased file on risk: the only part loss-of-use pays on."""
    return _build_rented_leased(api)


def _build_rented_leased(api: ApiClient) -> Ctx:
    rule = publish_rate_rule(api)
    pol = create_policy(api)
    part = create_part(api, pol["id"], fac.rented_leased_part())
    ctx = Ctx(rule=rule, policy=pol, part=part, policy_id=pol["id"],
              part_id=part["id"], rule_id=rule["id"])
    ctx["item"] = schedule_item(api, part["id"], pol["id"], ownership="RENTED",
                               description="Rented Excavator")
    ctx["item_id"] = ctx["item"]["id"]
    quote(api, pol["id"])
    bind(api, pol["id"])
    activate(api, pol["id"])
    ctx["active_item"] = activate_item(api, ctx["item_id"])
    return ctx


@pytest.fixture
def transit_file(api: ApiClient) -> Ctx:
    """A DRAFT policy carrying one TRANSIT part with owned, hired and cat limits."""
    return build_transit_file(api)


@pytest.fixture
def installation_file(api: ApiClient) -> Ctx:
    """An installation file on a three-control TIER_2 jobsite."""
    return build_installation_file(api, jobsite_controls=fac.SURVEY_TIER_2)


@pytest.fixture
def reporting_file(api: ApiClient) -> Ctx:
    """A monthly reporting-form file on risk at 250 bp with a 20000000 limit."""
    return build_reporting_file(api)


@pytest.fixture
def owned_vehicle(api: ApiClient) -> Dict[str, Any]:
    """An approved owned conveyance, never subject to the carrier approval test."""
    veh = create_vehicle(api)
    return approve_vehicle(api, veh["id"])


@pytest.fixture
def clock_default() -> str:
    """The instant the logical clock starts at before anything moves it."""
    return CLOCK_DEFAULT_UTC
