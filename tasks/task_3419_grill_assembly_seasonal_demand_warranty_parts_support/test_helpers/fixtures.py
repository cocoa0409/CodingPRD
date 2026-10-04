"""Composite setup helpers — multi-step PRD workflows packaged as fixtures.

Every helper builds state exclusively through PRD-declared endpoints (the
server boots empty; nothing is seeded). Setup calls use get_success_data so a
failed precondition raises a clear "Setup failed" style error.

Identity threading (PRD 2.1): ChannelRep calls carry make_channel_rep_headers(
channel["id"]) and Assembler calls carry make_assembler_headers(assembler_id) —
never the shared TEST_USERS constants — whenever the call is ownership-gated.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_ISO,  # noqa: F401  (re-exported)
    NO_SHOW_SUSPEND_THRESHOLD,
)
from .factories import (
    create_allocation_payload,
    create_assembler_payload,
    create_assembly_job_payload,
    create_channel_payload,
    create_device_pair_payload,
    create_lot_payload,
    create_model_payload,
    create_part_payload,
    create_parts_order_payload,
    create_sale_payload,
    create_season_payload,
    create_warranty_claim_payload,
    adjudicate_claim_payload,
    advance_season_payload,
    assembler_status_payload,
    job_assign_payload,
    job_action_payload,
    model_lifecycle_payload,
    part_transition_payload,
    parts_order_transition_payload,
    respond_allocation_payload,
    sale_transition_payload,
    set_logical_clock,  # noqa: F401  (re-exported: the PRD clock mechanism)
    unique_suffix,
)
from .test_users import TEST_USERS, make_channel_rep_headers, make_assembler_headers

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]
APP_USER = TEST_USERS["app_user_headers"]

SEASON_LADDER = ["PLANNING", "BUILD", "ALLOCATION", "IN_SEASON", "CLEARANCE", "TRANSITIONED", "CLOSED"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators (via declared endpoints)
# ---------------------------------------------------------------------------
def create_season(**overrides) -> dict:
    """Create a Season in PLANNING. Returns the Season."""
    resp = api_client.create_season(create_season_payload(**overrides), headers=PLANNER)
    return get_success_data(resp)


def create_model(**overrides) -> dict:
    """Create a GrillModel in ACTIVE. Returns the GrillModel."""
    resp = api_client.create_model(create_model_payload(**overrides), headers=PLANNER)
    return get_success_data(resp)


def create_channel(**overrides) -> dict:
    """Create a ChannelAccount. Returns the ChannelAccount."""
    resp = api_client.create_channel(create_channel_payload(**overrides), headers=PLANNER)
    return get_success_data(resp)


def create_lot(season_id: str, model_id: str, units_built: int = 50, **overrides) -> dict:
    """Create an InventoryLot under the season (season must be PLANNING or BUILD)."""
    payload = create_lot_payload(model_id, units_built=units_built, **overrides)
    resp = api_client.create_lot(season_id, payload, headers=PLANNER)
    return get_success_data(resp)


def create_part(**overrides) -> dict:
    """Create a PartSku. Returns the PartSku."""
    resp = api_client.create_part(create_part_payload(**overrides), headers=PLANNER)
    return get_success_data(resp)


def create_assembler(**overrides) -> dict:
    """Register an Assembler in APPLIED. Returns the Assembler."""
    resp = api_client.create_assembler(create_assembler_payload(**overrides), headers=PLANNER)
    return get_success_data(resp)


def create_certified_assembler(**overrides) -> dict:
    """Register an Assembler and CERTIFY it (PlannerAdmin). Returns the Assembler."""
    assembler = create_assembler(**overrides)
    resp = api_client.assembler_status(assembler["id"], assembler_status_payload("CERTIFY"), headers=PLANNER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------
def advance_season(season_id: str, target_status: str) -> dict:
    """Advance the season exactly one rung (target must be the immediate next state)."""
    resp = api_client.advance_season(season_id, advance_season_payload(target_status), headers=PLANNER)
    return get_success_data(resp)


def walk_season_to(season_id: str, target_status: str) -> dict:
    """Advance the season rung by rung until it reaches target_status.

    The caller is responsible for preconditions (a lot must exist before the
    BUILD -> ALLOCATION step; the clock must satisfy the calendar guards of the
    IN_SEASON / CLEARANCE / TRANSITIONED steps).
    """
    season = get_success_data(api_client.get_season(season_id, headers=PLANNER))
    while season["status"] != target_status:
        idx = SEASON_LADDER.index(season["status"])
        target_idx = SEASON_LADDER.index(target_status)
        if target_idx <= idx:
            raise AssertionError(
                f"walk_season_to: cannot reach {target_status} from {season['status']}"
            )
        season = advance_season(season_id, SEASON_LADDER[idx + 1])
    return season


def model_lifecycle(model_id: str, action: str) -> dict:
    """Drive a GrillModel lifecycle action (MARK_CLEARANCE_ELIGIBLE | DISCONTINUE |
    MARK_PARTS_ONLY | RETIRE)."""
    resp = api_client.model_lifecycle(model_id, model_lifecycle_payload(action), headers=PLANNER)
    return get_success_data(resp)


def assembler_status(assembler_id: str, action: str, headers=None) -> dict:
    """Drive an Assembler lifecycle action (CERTIFY | SUSPEND | DECERTIFY)."""
    resp = api_client.assembler_status(assembler_id, assembler_status_payload(action),
                                       headers=headers or PLANNER)
    return get_success_data(resp)


def refetch_season(season_id: str) -> dict:
    return get_success_data(api_client.get_season(season_id, headers=PLANNER))


def refetch_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_allocation(allocation_id, headers=PLANNER))


# ---------------------------------------------------------------------------
# Tier 2: allocation offers with OCC threading
# ---------------------------------------------------------------------------
def create_allocation(season_id: str, channel_account_id: str, model_id: str,
                      allocated_units: int, **overrides) -> dict:
    """Create an Allocation offer. The season version is read immediately before
    the create so the OCC field expected_season_version is always fresh."""
    season = refetch_season(season_id)
    payload = create_allocation_payload(
        season_id, channel_account_id, model_id, allocated_units,
        expected_season_version=season["version"], **overrides,
    )
    resp = api_client.create_allocation(payload, headers=PLANNER)
    return get_success_data(resp)


def respond_to_allocation(allocation, action: str, allocated_units: int = None,
                          version: int = None, headers=None) -> dict:
    """Respond to an offer (ACCEPT | DECLINE | RELEASE | REVISE).

    Version defaults to the allocation's current version (re-read when the
    caller passes a stale snapshot). ChannelRep-scoped actions are issued with
    the owning channel's identity; REVISE goes out as PlannerAdmin.
    """
    alloc_id = allocation["id"] if isinstance(allocation, dict) else allocation
    if version is None:
        version = refetch_allocation(alloc_id)["version"]
    if headers is None:
        if action == "REVISE":
            headers = PLANNER
        else:
            channel_id = allocation["channel_account_id"]
            headers = make_channel_rep_headers(channel_id)
    payload = respond_allocation_payload(action, version, allocated_units=allocated_units)
    resp = api_client.respond_allocation(alloc_id, payload, headers=headers)
    return get_success_data(resp)


def accept_allocation(allocation: dict) -> dict:
    """Owning ChannelRep accepts an OFFERED allocation. Returns ACCEPTED allocation."""
    return respond_to_allocation(allocation, "ACCEPT")


# ---------------------------------------------------------------------------
# Tier 3: posture setups (the recurring season/offer/sale chains)
# ---------------------------------------------------------------------------
def setup_season_in_allocation(units_built: int = 50, clock_at: Optional[str] = "2026-02-01T00:00:00Z",
                               season_over: dict = None, model_over: dict = None) -> dict:
    """Season walked PLANNING -> BUILD -> ALLOCATION with one lot.

    Returns {"season", "model", "lot"}. The season version is whatever the
    advances produced; callers creating allocations should use
    create_allocation(), which re-reads the version.
    """
    if clock_at is not None:
        set_logical_clock(clock_at)
    season = create_season(**(season_over or {}))
    model = create_model(**(model_over or {}))
    lot = create_lot(season["id"], model["id"], units_built=units_built)
    season = advance_season(season["id"], "BUILD")
    season = advance_season(season["id"], "ALLOCATION")
    return {"season": season, "model": model, "lot": lot}


def setup_offered_allocation(allocated_units: int = 10, units_built: int = 50,
                             channel_type: str = "HOME_CENTER",
                             clock_at: Optional[str] = "2026-02-01T00:00:00Z",
                             season_over: dict = None, model_over: dict = None,
                             channel_over: dict = None) -> dict:
    """Season in ALLOCATION + one channel + one OFFERED allocation."""
    bundle = setup_season_in_allocation(units_built=units_built, clock_at=clock_at,
                                        season_over=season_over, model_over=model_over)
    channel_defaults = {"channel_type": channel_type}
    channel_defaults.update(channel_over or {})
    channel = create_channel(**channel_defaults)
    allocation = create_allocation(bundle["season"]["id"], channel["id"],
                                   bundle["model"]["id"], allocated_units)
    bundle.update({"channel": channel, "allocation": allocation})
    return bundle


def setup_accepted_allocation(allocated_units: int = 10, units_built: int = 50,
                              channel_type: str = "HOME_CENTER",
                              clock_at: Optional[str] = "2026-02-01T00:00:00Z",
                              season_over: dict = None, model_over: dict = None,
                              channel_over: dict = None) -> dict:
    """Season in ALLOCATION + one channel + one ACCEPTED allocation."""
    bundle = setup_offered_allocation(
        allocated_units=allocated_units, units_built=units_built, channel_type=channel_type,
        clock_at=clock_at, season_over=season_over, model_over=model_over,
        channel_over=channel_over,
    )
    bundle["allocation"] = accept_allocation(bundle["allocation"])
    return bundle


def setup_in_season(allocated_units: int = 10, units_built: int = 50,
                    channel_type: str = "HOME_CENTER",
                    in_season_clock: str = "2026-04-01T00:00:00Z",
                    season_over: dict = None, model_over: dict = None,
                    channel_over: dict = None) -> dict:
    """Accepted allocation, then clock set to in_season_clock and season advanced
    to IN_SEASON. The default season window (in_season_start 2026-03-01) makes the
    default clock legal."""
    bundle = setup_accepted_allocation(
        allocated_units=allocated_units, units_built=units_built, channel_type=channel_type,
        season_over=season_over, model_over=model_over, channel_over=channel_over,
    )
    set_logical_clock(in_season_clock)
    bundle["season"] = advance_season(bundle["season"]["id"], "IN_SEASON")
    return bundle


def create_sale(season_id: str, model_id: str, channel_account_id: str,
                quantity: int = 1, accessories=None, serials=None,
                proof_of_purchase_token: Optional[str] = None, **overrides) -> dict:
    """Record a sale as the owning ChannelRep (identity threaded)."""
    payload = create_sale_payload(
        season_id, model_id, channel_account_id, quantity=quantity,
        accessories=accessories, serials=serials,
        proof_of_purchase_token=proof_of_purchase_token, **overrides,
    )
    # Drop keys the caller left as None so optionality is exercised faithfully.
    payload = {k: v for k, v in payload.items() if v is not None}
    resp = api_client.create_sale(payload, headers=make_channel_rep_headers(channel_account_id))
    return get_success_data(resp)


def transition_sale(sale, action: str, proof_of_purchase_token: Optional[str] = None,
                    headers=None) -> dict:
    """Sale lifecycle (REGISTER | RETURN) as the owning ChannelRep by default."""
    sale_id = sale["id"] if isinstance(sale, dict) else sale
    if headers is None:
        if isinstance(sale, dict):
            headers = make_channel_rep_headers(sale["channel_account_id"])
        else:
            headers = AGENT
    resp = api_client.transition_sale(
        sale_id, sale_transition_payload(action, proof_of_purchase_token), headers=headers,
    )
    return get_success_data(resp)


def setup_in_season_with_sale(quantity: int = 1, registered: bool = True,
                              accessories=None, serials=None,
                              allocated_units: int = 10, units_built: int = 50,
                              channel_type: str = "HOME_CENTER",
                              in_season_clock: str = "2026-04-01T00:00:00Z",
                              season_over: dict = None, model_over: dict = None,
                              channel_over: dict = None) -> dict:
    """The canonical selling-scene bundle: season IN_SEASON, accepted allocation,
    one sale (REGISTERED when registered=True). Returns the bundle + "sale"."""
    bundle = setup_in_season(
        allocated_units=allocated_units, units_built=units_built, channel_type=channel_type,
        in_season_clock=in_season_clock, season_over=season_over, model_over=model_over,
        channel_over=channel_over,
    )
    token = f"RCPT-{unique_suffix()}" if registered else None
    sale = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                       quantity=quantity, accessories=accessories, serials=serials,
                       proof_of_purchase_token=token)
    bundle["sale"] = sale
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: assembly jobs
# ---------------------------------------------------------------------------
def iso_window(date: str, start_hour: int, duration_hours: int = 1) -> tuple:
    """('2026-04-02T09:00:00Z', '2026-04-02T10:00:00Z')-style window pair."""
    return (f"{date}T{start_hour:02d}:00:00Z", f"{date}T{start_hour + duration_hours:02d}:00:00Z")


def create_job(sale_id: str, job_type: str = "RETAIL_ASSEMBLY",
               distance_mi: Optional[int] = None) -> dict:
    """Request an AssemblyJob (REQUESTED) as ServiceAgent; fee is priced at creation."""
    overrides = {}
    if distance_mi is not None:
        overrides["distance_mi"] = distance_mi
    resp = api_client.create_assembly_job(
        create_assembly_job_payload(sale_id, job_type, **overrides), headers=AGENT,
    )
    return get_success_data(resp)


def assign_job(job_id: str, assembler_id: str, window_start: str, window_end: str) -> dict:
    """ServiceAgent ASSIGN; runs the five booking checks. Returns SCHEDULED job."""
    resp = api_client.transition_assembly_job(
        job_id, job_assign_payload(assembler_id, window_start, window_end), headers=AGENT,
    )
    return get_success_data(resp)


def start_job(job_id: str, assembler_id: str) -> dict:
    """Assembler START on its own job (identity threaded). Returns IN_PROGRESS job."""
    resp = api_client.transition_assembly_job(
        job_id, job_action_payload("START"), headers=make_assembler_headers(assembler_id),
    )
    return get_success_data(resp)


def complete_job(job_id: str, assembler_id: str) -> dict:
    """Assembler COMPLETE on its own job (identity threaded). Returns COMPLETED job."""
    resp = api_client.transition_assembly_job(
        job_id, job_action_payload("COMPLETE"), headers=make_assembler_headers(assembler_id),
    )
    return get_success_data(resp)


def cancel_job(job_id: str) -> dict:
    resp = api_client.transition_assembly_job(job_id, job_action_payload("CANCEL"), headers=AGENT)
    return get_success_data(resp)


def no_show_job(job_id: str) -> dict:
    """ServiceAgent NO_SHOW on a SCHEDULED job. Returns the NO_SHOW job."""
    resp = api_client.transition_assembly_job(job_id, job_action_payload("NO_SHOW"), headers=AGENT)
    return get_success_data(resp)


def setup_job_assigned(window_start: str = "2026-04-02T09:00:00Z",
                       window_end: str = "2026-04-02T10:00:00Z",
                       job_type: str = "RETAIL_ASSEMBLY", distance_mi: Optional[int] = None,
                       assembler_over: dict = None, **sale_kwargs) -> dict:
    """In-season sale bundle + certified assembler + one SCHEDULED job."""
    bundle = setup_in_season_with_sale(**sale_kwargs)
    assembler = create_certified_assembler(**(assembler_over or {}))
    job = create_job(bundle["sale"]["id"], job_type=job_type, distance_mi=distance_mi)
    job = assign_job(job["id"], assembler["id"], window_start, window_end)
    bundle.update({"assembler": assembler, "job": job})
    return bundle


def setup_assembler_with_no_shows(no_show_count: int, window_date: str = "2026-04-02",
                                  assembler_over: dict = None, **sale_kwargs) -> dict:
    """Certified assembler with exactly no_show_count lifetime no-shows.

    Each no-show is its own sale + job: assign then NO_SHOW, hour-disjoint
    windows on window_date. Note: reaching NO_SHOW_SUSPEND_THRESHOLD suspends
    the assembler, so no_show_count values above the threshold cannot be built
    this way (a SUSPENDED assembler rejects further ASSIGNs).
    """
    if no_show_count > NO_SHOW_SUSPEND_THRESHOLD:
        raise AssertionError(
            f"Cannot build {no_show_count} no-shows: the assembler auto-suspends at "
            f"{NO_SHOW_SUSPEND_THRESHOLD} and rejects further ASSIGNs"
        )
    bundle = setup_in_season(channel_type=sale_kwargs.pop("channel_type", "DIRECT"), **sale_kwargs)
    assembler = create_certified_assembler(**(assembler_over or {}))
    jobs = []
    for i in range(no_show_count):
        sale = create_sale(bundle["season"]["id"], bundle["model"]["id"],
                           bundle["channel"]["id"], quantity=1,
                           proof_of_purchase_token=f"RCPT-{unique_suffix()}")
        job = create_job(sale["id"])
        ws, we = iso_window(window_date, 9 + i)
        assign_job(job["id"], assembler["id"], ws, we)
        jobs.append(no_show_job(job["id"]))
    assembler = get_success_data(api_client.get_assembler(assembler["id"], headers=PLANNER))
    bundle.update({"assembler": assembler, "jobs": jobs})
    return bundle


# ---------------------------------------------------------------------------
# Tier 3/5: warranty claims
# ---------------------------------------------------------------------------
def create_claim(sale_id: str, component: str = "BURNER",
                 failure_description: str = "Component failed in normal use",
                 **overrides) -> dict:
    """File a WarrantyClaim (SUBMITTED) as ServiceAgent against a REGISTERED sale."""
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(sale_id, component, failure_description, **overrides),
        headers=AGENT,
    )
    return get_success_data(resp)


def adjudicate_claim(claim_id: str, action: str, goodwill_justification: str = None,
                     actual_labor_cents: int = None) -> dict:
    """One adjudication step as ServiceAgent. Returns the updated claim."""
    resp = api_client.adjudicate_claim(
        claim_id,
        adjudicate_claim_payload(action, goodwill_justification, actual_labor_cents),
        headers=AGENT,
    )
    return get_success_data(resp)


def walk_claim_to_state(claim: dict, target_status: str, via_escalation: bool = False,
                        actual_labor_cents: int = 4000,
                        goodwill_justification: Optional[str] = None) -> dict:
    """Walk a claim (pass the claim dict) to the target adjudication state.

    Paths:
      UNDER_REVIEW:   REVIEW
      INFO_REQUESTED: REVIEW, REQUEST_INFO
      ESCALATED:      REVIEW, ESCALATE
      APPROVED:       REVIEW, [ESCALATE], APPROVE
      DENIED:         REVIEW, DENY
      REOPENED:       REVIEW, DENY, REOPEN
      SETTLED:        REVIEW, [ESCALATE], APPROVE, SETTLE(actual_labor_cents)
    """
    claim_id = claim["id"]
    actions = []
    if target_status == "UNDER_REVIEW":
        actions = ["REVIEW"]
    elif target_status == "INFO_REQUESTED":
        actions = ["REVIEW", "REQUEST_INFO"]
    elif target_status == "ESCALATED":
        actions = ["REVIEW", "ESCALATE"]
    elif target_status == "APPROVED":
        actions = ["REVIEW"] + (["ESCALATE"] if via_escalation else []) + ["APPROVE"]
    elif target_status == "DENIED":
        actions = ["REVIEW", "DENY"]
    elif target_status == "REOPENED":
        actions = ["REVIEW", "DENY", "REOPEN"]
    elif target_status == "SETTLED":
        actions = ["REVIEW"] + (["ESCALATE"] if via_escalation else []) + ["APPROVE", "SETTLE"]
    else:
        raise AssertionError(f"walk_claim_to_state: unsupported target {target_status}")

    current = claim
    for action in actions:
        kwargs = {}
        if action == "APPROVE" and goodwill_justification is not None:
            kwargs["goodwill_justification"] = goodwill_justification
        if action == "SETTLE":
            kwargs["actual_labor_cents"] = actual_labor_cents
        current = adjudicate_claim(claim_id, action, **kwargs)
    return current


def setup_claim_in_state(component: str = "BURNER", target_status: str = "UNDER_REVIEW",
                         via_escalation: bool = False, actual_labor_cents: int = 4000,
                         goodwill_justification: Optional[str] = None,
                         **sale_kwargs) -> dict:
    """In-season registered-sale bundle + one claim walked to target_status."""
    bundle = setup_in_season_with_sale(**sale_kwargs)
    claim = create_claim(bundle["sale"]["id"], component=component)
    claim = walk_claim_to_state(claim, target_status, via_escalation=via_escalation,
                                actual_labor_cents=actual_labor_cents,
                                goodwill_justification=goodwill_justification)
    bundle["claim"] = claim
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: parts catalog and orders
# ---------------------------------------------------------------------------
def create_parts_order(part_id: str, sale_id: str, quantity: int = 1,
                       fulfillment_type: str = "PAID", **overrides) -> dict:
    """Place a PartsOrder as ServiceAgent; supersession resolution runs
    synchronously inside the create (born ALLOCATED or BACKORDERED)."""
    resp = api_client.create_parts_order(
        create_parts_order_payload(part_id, sale_id, quantity, fulfillment_type, **overrides),
        headers=AGENT,
    )
    return get_success_data(resp)


def restock_part(part_id: str, quantity: int, headers=None) -> dict:
    resp = api_client.transition_part(part_id, part_transition_payload("RESTOCK", quantity=quantity),
                                      headers=headers or PLANNER)
    return get_success_data(resp)


def transition_part(part_id: str, action: str, quantity: int = None,
                    successor_part_id: str = None, headers=None) -> dict:
    resp = api_client.transition_part(
        part_id, part_transition_payload(action, quantity, successor_part_id),
        headers=headers or PLANNER,
    )
    return get_success_data(resp)


def transition_parts_order(order_id: str, action: str) -> dict:
    resp = api_client.transition_parts_order(order_id, parts_order_transition_payload(action),
                                             headers=AGENT)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: connected devices
# ---------------------------------------------------------------------------
def pair_device(sale_id: str, app_account_id: Optional[str] = None) -> dict:
    """Pair a ConnectedDevice to a sale as AppUser (registers a SOLD sale)."""
    resp = api_client.pair_device(create_device_pair_payload(sale_id, app_account_id),
                                  headers=APP_USER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4/5: late-season posture setups
# ---------------------------------------------------------------------------
def setup_in_clearance(sold_units: int = 0, allocated_units: int = 10,
                       units_built: int = 50, channel_type: str = "HOME_CENTER",
                       clearance_clock: str = "2026-08-05T00:00:00Z",
                       in_season_clock: str = "2026-04-01T00:00:00Z",
                       season_over: dict = None, model_over: dict = None,
                       channel_over: dict = None) -> dict:
    """Accepted allocation, optional in-season sales, then clock to
    clearance_clock and season advanced into CLEARANCE (running the offer-expiry
    sweep and the allocation waterfall)."""
    bundle = setup_in_season(
        allocated_units=allocated_units, units_built=units_built, channel_type=channel_type,
        in_season_clock=in_season_clock, season_over=season_over, model_over=model_over,
        channel_over=channel_over,
    )
    if sold_units:
        create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                    quantity=sold_units, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
        bundle["allocation"] = refetch_allocation(bundle["allocation"]["id"])
    set_logical_clock(clearance_clock)
    bundle["season"] = advance_season(bundle["season"]["id"], "CLEARANCE")
    return bundle


def setup_transitioned_season(units_built: int = 40, season_over: dict = None,
                              model_over: dict = None,
                              transitioned_clock: str = "2026-10-01T00:00:00Z") -> dict:
    """Full walk to TRANSITIONED: model discontinued, lots CLOSEOUT (PRD 3.2/3.4
    cascades). No allocations needed — the BUILD -> ALLOCATION guard only needs
    the lot."""
    set_logical_clock("2026-02-01T00:00:00Z")
    season = create_season(**(season_over or {}))
    model = create_model(**(model_over or {}))
    lot = create_lot(season["id"], model["id"], units_built=units_built)
    advance_season(season["id"], "BUILD")
    advance_season(season["id"], "ALLOCATION")
    set_logical_clock("2026-04-01T00:00:00Z")
    advance_season(season["id"], "IN_SEASON")
    set_logical_clock("2026-08-05T00:00:00Z")
    advance_season(season["id"], "CLEARANCE")
    set_logical_clock(transitioned_clock)
    season = advance_season(season["id"], "TRANSITIONED")
    model = get_success_data(api_client.get_model(model["id"], headers=PLANNER))
    return {"season": season, "model": model, "lot": lot}


def setup_closed_season(units_built: int = 5) -> dict:
    """Full lifecycle walk to CLOSED (terminal lockdown tests)."""
    bundle = setup_transitioned_season(units_built=units_built)
    bundle["season"] = advance_season(bundle["season"]["id"], "CLOSED")
    return bundle


__all__ = [
    "SEASON_LADDER",
    "DEFAULT_CLOCK_ISO",
    "set_logical_clock",
    "create_season",
    "create_model",
    "create_channel",
    "create_lot",
    "create_part",
    "create_assembler",
    "create_certified_assembler",
    "advance_season",
    "walk_season_to",
    "model_lifecycle",
    "assembler_status",
    "refetch_season",
    "refetch_allocation",
    "create_allocation",
    "respond_to_allocation",
    "accept_allocation",
    "setup_season_in_allocation",
    "setup_offered_allocation",
    "setup_accepted_allocation",
    "setup_in_season",
    "create_sale",
    "transition_sale",
    "setup_in_season_with_sale",
    "iso_window",
    "create_job",
    "assign_job",
    "start_job",
    "complete_job",
    "cancel_job",
    "no_show_job",
    "setup_job_assigned",
    "setup_assembler_with_no_shows",
    "create_claim",
    "adjudicate_claim",
    "walk_claim_to_state",
    "setup_claim_in_state",
    "create_parts_order",
    "restock_part",
    "transition_part",
    "transition_parts_order",
    "pair_device",
    "setup_in_clearance",
    "setup_transitioned_season",
    "setup_closed_season",
]
