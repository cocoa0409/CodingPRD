"""World builders that drive the API to reach a given business state.

The harness restarts the server before every test, so nothing is shared between
tests: each builder here constructs everything it needs from scratch through the
public API. Every ownership-gated call is made with headers built from the id of
the entity created for that test, never from a shared constant.

The base world is one host store with a connected POS integration and an
attested space obligation, an active license agreement, one certified chef and
one commissioned kiosk with that chef as its lead. Layer builders take that
world and push it further: a released plan, an approved rice batch, a released
fish lot, a pack lot on the shelf, a reconciled POS feed, a draft settlement
statement, or a submitted audit.
"""

from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DISCARD_SHELF_LIFE_EXPIRED,
    SEVERITY_MAJOR,
    VERIFY_OUTCOME_FAIL,
    VERIFY_OUTCOME_PASS,
)
from .factories import (
    CANONICAL_CLOCK,
    acidification_reading_payload,
    audit_payload,
    certification_payload,
    chef_payload,
    clock_payload,
    commission_payload,
    correction_payload,
    discard_payload,
    finding_payload,
    fish_lot_payload,
    food_handler_certification_payload,
    haccp_certification_payload,
    host_store_payload,
    kiosk_payload,
    license_agreement_payload,
    pack_lot_payload,
    placement_payload,
    pos_integration_payload,
    pos_sales_feed_payload,
    production_plan_payload,
    rice_batch_payload,
    settlement_statement_payload,
    space_attestation_payload,
    training_payload,
    verification_payload,
)
from .test_users import (
    AUDITOR_OPENER_ID,
    AUDITOR_VERIFIER_ID,
    OPS_CREATOR_ID,
    OPS_ISSUER_ID,
    make_franchise_chef_headers,
    make_franchisor_ops_headers,
    make_host_store_manager_headers,
    make_quality_auditor_headers,
)


# --- Tier 1: single-step wrappers ------------------------------------------
def set_clock(current_utc: str = CANONICAL_CLOCK) -> dict:
    """Sets the logical clock and returns the resulting clock payload."""
    return get_success_data(api_client.set_clock(clock_payload(current_utc)))


def create_host_store(ops_headers: Optional[dict] = None, **overrides) -> dict:
    """Registers a host store."""
    headers = ops_headers or make_franchisor_ops_headers()
    return get_success_data(
        api_client.create_host_store(host_store_payload(**overrides), headers)
    )


def connect_pos(host_store_id: str, **overrides) -> dict:
    """Sets a host store's POS integration state as its own manager."""
    return get_success_data(
        api_client.set_pos_integration(
            host_store_id,
            pos_integration_payload(**overrides),
            make_host_store_manager_headers(host_store_id),
        )
    )


def attest_space(host_store_id: str, **overrides) -> dict:
    """Records the manager's space attestation for their own host store."""
    return get_success_data(
        api_client.attest_space(
            host_store_id,
            space_attestation_payload(**overrides),
            make_host_store_manager_headers(host_store_id),
        )
    )


def create_license_agreement(host_store_id: str, **overrides) -> dict:
    """Drafts a license agreement for a host store."""
    return get_success_data(
        api_client.create_license_agreement(
            license_agreement_payload(host_store_id, **overrides),
            make_franchisor_ops_headers(),
        )
    )


def activate_agreement(agreement_id: str) -> dict:
    """Activates a drafted license agreement."""
    return get_success_data(
        api_client.activate_license_agreement(agreement_id, make_franchisor_ops_headers())
    )


def create_chef(**overrides) -> dict:
    """Registers a chef candidate."""
    return get_success_data(
        api_client.create_chef(chef_payload(**overrides), make_franchisor_ops_headers())
    )


def log_training(chef_id: str, **overrides) -> dict:
    """Logs training hours against a chef."""
    return get_success_data(
        api_client.log_training(
            chef_id, training_payload(**overrides), make_franchisor_ops_headers()
        )
    )


def issue_certification(chef_id: str, **overrides) -> dict:
    """Issues one certification to a chef."""
    return get_success_data(
        api_client.create_certification(
            chef_id, certification_payload(**overrides), make_quality_auditor_headers()
        )
    )


def issue_mandatory_certifications(chef_id: str) -> dict:
    """Issues both mandatory certifications to a chef."""
    food_handler = get_success_data(
        api_client.create_certification(
            chef_id,
            food_handler_certification_payload(),
            make_quality_auditor_headers(),
        )
    )
    haccp = get_success_data(
        api_client.create_certification(
            chef_id, haccp_certification_payload(), make_quality_auditor_headers()
        )
    )
    return {"food_handler": food_handler, "haccp": haccp}


def create_kiosk(agreement_id: str, **overrides) -> dict:
    """Provisions a kiosk under a license agreement."""
    return get_success_data(
        api_client.create_kiosk(
            kiosk_payload(agreement_id, **overrides), make_franchisor_ops_headers()
        )
    )


def place_chef(chef_id: str, kiosk_id: str, as_lead_chef: bool = True) -> dict:
    """Places a chef at a kiosk, optionally as its lead."""
    return get_success_data(
        api_client.place_chef(
            chef_id,
            placement_payload(kiosk_id, as_lead_chef=as_lead_chef),
            make_franchisor_ops_headers(),
        )
    )


def commission_kiosk(kiosk_id: str, **overrides) -> dict:
    """Commissions a provisioned kiosk."""
    return get_success_data(
        api_client.commission_kiosk(
            kiosk_id, commission_payload(**overrides), make_franchisor_ops_headers()
        )
    )


def read_kiosk(kiosk_id: str) -> dict:
    """Re-reads a kiosk as franchisor operations."""
    return get_success_data(
        api_client.get_kiosk(kiosk_id, make_franchisor_ops_headers())
    )


def read_agreement(agreement_id: str) -> dict:
    """Re-reads a license agreement as franchisor operations."""
    return get_success_data(
        api_client.get_license_agreement(agreement_id, make_franchisor_ops_headers())
    )


def read_host_store(host_store_id: str) -> dict:
    """Re-reads a host store as franchisor operations."""
    return get_success_data(
        api_client.get_host_store(host_store_id, make_franchisor_ops_headers())
    )


def read_chef(chef_id: str) -> dict:
    """Re-reads a chef as franchisor operations."""
    return get_success_data(api_client.get_chef(chef_id, make_franchisor_ops_headers()))


def read_plan(plan_id: str) -> dict:
    """Re-reads a production plan as franchisor operations."""
    return get_success_data(
        api_client.get_production_plan(plan_id, make_franchisor_ops_headers())
    )


def read_rice_batch(batch_id: str) -> dict:
    """Re-reads a rice batch as franchisor operations."""
    return get_success_data(
        api_client.get_rice_batch(batch_id, make_franchisor_ops_headers())
    )


def read_fish_lot(fish_lot_id: str) -> dict:
    """Re-reads a fish lot as franchisor operations."""
    return get_success_data(
        api_client.get_fish_lot(fish_lot_id, make_franchisor_ops_headers())
    )


def read_pack_lot(pack_lot_id: str) -> dict:
    """Re-reads a pack lot as franchisor operations."""
    return get_success_data(
        api_client.get_pack_lot(pack_lot_id, make_franchisor_ops_headers())
    )


def read_statement(statement_id: str) -> dict:
    """Re-reads a settlement statement as franchisor operations."""
    return get_success_data(
        api_client.get_settlement_statement(statement_id, make_franchisor_ops_headers())
    )


def read_audit(audit_id: str) -> dict:
    """Re-reads a food safety audit as its scheduling auditor."""
    return get_success_data(
        api_client.get_audit(audit_id, make_quality_auditor_headers())
    )


def read_risk_summary(kiosk_id: str) -> dict:
    """Reads a kiosk's computed risk decomposition."""
    return get_success_data(
        api_client.get_kiosk_risk_summary(kiosk_id, make_franchisor_ops_headers())
    )


# --- Tier 2: the base world ------------------------------------------------
def base_world(
    *,
    clock: str = CANONICAL_CLOCK,
    suffix: str = "",
    store_overrides: Optional[dict] = None,
    attestation_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
    kiosk_overrides: Optional[dict] = None,
    chef_name: str = "Kenji Arai",
    training_overrides: Optional[dict] = None,
    connect: bool = True,
    attest: bool = True,
    activate: bool = True,
    certify: bool = True,
    place: bool = True,
    commission: bool = True,
) -> dict:
    """Builds a host store, license agreement, certified chef and kiosk.

    ``suffix`` distinguishes a second independent store/agreement/kiosk built in
    the same test. Each stage can be switched off to leave the world short of a
    precondition on purpose.
    """
    set_clock(clock)

    store_kwargs = dict(store_overrides or {})
    if suffix:
        store_kwargs.setdefault("name", f"Northgate Market 418{suffix}")
        store_kwargs.setdefault("store_number", f"418{suffix}")
    host_store = create_host_store(**store_kwargs)
    host_store_id = host_store["id"]

    if connect:
        host_store = connect_pos(host_store_id)
    if attest:
        host_store = attest_space(host_store_id, **(attestation_overrides or {}))

    agreement = create_license_agreement(host_store_id, **(agreement_overrides or {}))
    if activate:
        agreement = activate_agreement(agreement["id"])

    chef = create_chef(full_name=f"{chef_name}{suffix}" if suffix else chef_name)
    chef_id = chef["id"]
    log_training(chef_id, **(training_overrides or {}))
    certifications = issue_mandatory_certifications(chef_id) if certify else {}

    kiosk_kwargs = dict(kiosk_overrides or {})
    if suffix:
        kiosk_kwargs.setdefault("kiosk_code", f"K-418-A{suffix}")
    kiosk = create_kiosk(agreement["id"], **kiosk_kwargs)
    kiosk_id = kiosk["id"]

    if place:
        place_chef(chef_id, kiosk_id, as_lead_chef=True)
    if commission:
        kiosk = commission_kiosk(kiosk_id, commissioned_on=clock[:10])

    return {
        "host_store": read_host_store(host_store_id),
        "host_store_id": host_store_id,
        "agreement": read_agreement(agreement["id"]),
        "agreement_id": agreement["id"],
        "chef": read_chef(chef_id),
        "chef_id": chef_id,
        "certifications": certifications,
        "kiosk": read_kiosk(kiosk_id) if place or commission else kiosk,
        "kiosk_id": kiosk_id,
        "ops_headers": make_franchisor_ops_headers(),
        "ops_issuer_headers": make_franchisor_ops_headers(OPS_ISSUER_ID),
        "manager_headers": make_host_store_manager_headers(host_store_id),
        "chef_headers": make_franchise_chef_headers(chef_id),
        "auditor_headers": make_quality_auditor_headers(),
        "auditor_verifier_headers": make_quality_auditor_headers(AUDITOR_VERIFIER_ID),
    }


def add_chef(world: dict, full_name: str, kiosk_id: Optional[str] = None,
             as_lead_chef: bool = False, certify: bool = True,
             place: bool = True) -> dict:
    """Registers, trains, certifies and places an additional chef."""
    chef = create_chef(full_name=full_name)
    log_training(chef["id"])
    if certify:
        issue_mandatory_certifications(chef["id"])
    if place:
        place_chef(chef["id"], kiosk_id or world["kiosk_id"], as_lead_chef=as_lead_chef)
    return read_chef(chef["id"])


def add_kiosk(world: dict, kiosk_code: str, lead_chef_name: str,
              commission: bool = True, **kiosk_overrides) -> dict:
    """Provisions a second kiosk under the same agreement with its own lead chef."""
    kiosk = create_kiosk(world["agreement_id"], kiosk_code=kiosk_code, **kiosk_overrides)
    chef = create_chef(full_name=lead_chef_name)
    log_training(chef["id"])
    issue_mandatory_certifications(chef["id"])
    place_chef(chef["id"], kiosk["id"], as_lead_chef=True)
    if commission:
        commission_kiosk(kiosk["id"])
    return {
        "kiosk": read_kiosk(kiosk["id"]),
        "kiosk_id": kiosk["id"],
        "chef": read_chef(chef["id"]),
        "chef_id": chef["id"],
        "chef_headers": make_franchise_chef_headers(chef["id"]),
    }


# --- Tier 3: production layers --------------------------------------------
def add_draft_plan(world: dict, **overrides) -> dict:
    """Creates a draft production plan against the current kiosk version."""
    kiosk = read_kiosk(world["kiosk_id"])
    payload = production_plan_payload(world["kiosk_id"], kiosk["version"], **overrides)
    return get_success_data(
        api_client.create_production_plan(payload, world["chef_headers"])
    )


def add_released_plan(world: dict, **overrides) -> dict:
    """Creates a draft plan and releases it to the production floor."""
    plan = add_draft_plan(world, **overrides)
    return get_success_data(
        api_client.release_production_plan(plan["id"], world["chef_headers"])
    )


def add_mixing_rice_batch(world: dict, plan_id: str, **overrides) -> dict:
    """Starts a rice batch against a released plan."""
    payload = rice_batch_payload(plan_id, world["chef_id"], **overrides)
    return get_success_data(api_client.create_rice_batch(payload, world["chef_headers"]))


def add_approved_rice_batch(world: dict, plan_id: str,
                            reading_overrides: Optional[dict] = None,
                            **overrides) -> dict:
    """Starts a rice batch and carries it through to an approved disposition."""
    batch = add_mixing_rice_batch(world, plan_id, **overrides)
    get_success_data(
        api_client.record_acidification_reading(
            batch["id"],
            acidification_reading_payload(**(reading_overrides or {})),
            world["chef_headers"],
        )
    )
    return get_success_data(api_client.verify_ttc(batch["id"], world["chef_headers"]))


def add_received_fish_lot(world: dict, **overrides) -> dict:
    """Receives a fish lot at the kiosk."""
    payload = fish_lot_payload(world["kiosk_id"], **overrides)
    return get_success_data(api_client.create_fish_lot(payload, world["chef_headers"]))


def add_released_fish_lot(world: dict, **overrides) -> dict:
    """Receives a fish lot and releases it for production."""
    lot = add_received_fish_lot(world, **overrides)
    return get_success_data(
        api_client.release_fish_lot(lot["id"], world["auditor_headers"])
    )


def add_pack_lot(world: dict, rice_batch_id: str, fish_lot_id: str, **overrides) -> dict:
    """Builds a pack lot from an approved rice batch and a released fish lot."""
    payload = pack_lot_payload(rice_batch_id, fish_lot_id, **overrides)
    return get_success_data(api_client.create_pack_lot(payload, world["chef_headers"]))


def add_cold_chain_readings(world: dict, fish_lot_id: str, readings) -> list:
    """Appends a series of cold-chain readings, returning each stored reading."""
    from .factories import cold_chain_reading_payload

    stored = []
    for recorded_at, temp_c in readings:
        stored.append(
            get_success_data(
                api_client.create_cold_chain_reading(
                    fish_lot_id,
                    cold_chain_reading_payload(recorded_at, temp_c),
                    world["chef_headers"],
                )
            )
        )
    return stored


# --- Tier 3: settlement layers ---------------------------------------------
def add_submitted_feed(world: dict, **overrides) -> dict:
    """Submits a POS sales feed for the host store as its own manager."""
    payload = pos_sales_feed_payload(world["host_store_id"], **overrides)
    return get_success_data(
        api_client.create_pos_sales_feed(payload, world["manager_headers"])
    )


def add_reconciled_feed(world: dict, **overrides) -> dict:
    """Submits a POS sales feed and reconciles it."""
    feed = add_submitted_feed(world, **overrides)
    return get_success_data(
        api_client.reconcile_pos_sales_feed(feed["id"], world["ops_headers"])
    )


def add_rejected_feed(world: dict, rejection_reason: str = "Terminal export truncated mid-day",
                      **overrides) -> dict:
    """Submits a POS sales feed and rejects it."""
    feed = add_submitted_feed(world, **overrides)
    return get_success_data(
        api_client.reject_pos_sales_feed(
            feed["id"], {"rejection_reason": rejection_reason}, world["ops_headers"]
        )
    )


def add_draft_statement(world: dict, created_by: str = OPS_CREATOR_ID, **overrides) -> dict:
    """Drafts a settlement statement against the current agreement version."""
    agreement = read_agreement(world["agreement_id"])
    payload = settlement_statement_payload(
        world["agreement_id"], agreement["version"], **overrides
    )
    return get_success_data(
        api_client.create_settlement_statement(
            payload, make_franchisor_ops_headers(created_by)
        )
    )


def add_issued_statement(world: dict, created_by: str = OPS_CREATOR_ID,
                         issued_by: str = OPS_ISSUER_ID, **overrides) -> dict:
    """Drafts and issues a settlement statement using two distinct operators."""
    statement = add_draft_statement(world, created_by=created_by, **overrides)
    return get_success_data(
        api_client.issue_settlement_statement(
            statement["id"], make_franchisor_ops_headers(issued_by)
        )
    )


def add_acknowledged_statement(world: dict, **overrides) -> dict:
    """Drafts, issues and acknowledges a settlement statement."""
    statement = add_issued_statement(world, **overrides)
    return get_success_data(
        api_client.acknowledge_settlement_statement(
            statement["id"], world["manager_headers"]
        )
    )


# --- Tier 4: audit layers --------------------------------------------------
def add_scheduled_audit(world: dict, **overrides) -> dict:
    """Schedules an audit of the kiosk."""
    payload = audit_payload(world["kiosk_id"], **overrides)
    return get_success_data(
        api_client.create_audit(payload, make_quality_auditor_headers(AUDITOR_OPENER_ID))
    )


def add_started_audit(world: dict, **overrides) -> dict:
    """Schedules an audit and opens it for finding entry."""
    audit = add_scheduled_audit(world, **overrides)
    return get_success_data(
        api_client.start_audit(
            audit["id"], make_quality_auditor_headers(AUDITOR_OPENER_ID)
        )
    )


def add_findings(world: dict, audit_id: str, severities, codes=None) -> list:
    """Records one finding per severity against an in-progress audit."""
    findings = []
    for index, severity in enumerate(severities):
        overrides = {}
        if codes is not None:
            overrides["finding_code"] = codes[index]
        payload = finding_payload(severity, **overrides)
        findings.append(
            get_success_data(
                api_client.create_finding(
                    audit_id,
                    payload,
                    make_quality_auditor_headers(AUDITOR_OPENER_ID),
                )
            )
        )
    return findings


def add_submitted_audit(world: dict, severities=(), codes=None, **overrides) -> dict:
    """Schedules, starts, populates and submits an audit.

    Returns the submitted audit alongside the findings recorded against it.
    """
    audit = add_started_audit(world, **overrides)
    findings = add_findings(world, audit["id"], severities, codes=codes)
    submitted = get_success_data(
        api_client.submit_audit(
            audit["id"], make_quality_auditor_headers(AUDITOR_OPENER_ID)
        )
    )
    return {"audit": submitted, "audit_id": audit["id"], "findings": findings}


def correct_all_findings(world: dict, audit_id: str, findings) -> None:
    """Records the corrective action taken against every listed finding."""
    for finding in findings:
        get_success_data(
            api_client.correct_finding(
                audit_id, finding["id"], correction_payload(), world["manager_headers"]
            )
        )


def add_reverification_request(world: dict, audit_id: str, findings) -> dict:
    """Corrects every finding and asks for reverification."""
    correct_all_findings(world, audit_id, findings)
    return get_success_data(
        api_client.request_reverification(audit_id, world["manager_headers"])
    )


def verify_audit(world: dict, audit_id: str, outcome: str = VERIFY_OUTCOME_PASS) -> dict:
    """Reverifies an audit as an auditor other than the one who opened it."""
    return get_success_data(
        api_client.verify_audit(
            audit_id,
            verification_payload(outcome),
            make_quality_auditor_headers(AUDITOR_VERIFIER_ID),
        )
    )


def drive_audit_to_second_round(world: dict, severities=(SEVERITY_MAJOR,)) -> dict:
    """Carries an audit through one failed reverification round.

    The audit ends in corrective action with ``round_count`` at 2, which is the
    state from which one more failing verification escalates.
    """
    submitted = add_submitted_audit(world, severities=severities)
    audit_id = submitted["audit_id"]
    findings = submitted["findings"]
    add_reverification_request(world, audit_id, findings)
    verify_audit(world, audit_id, VERIFY_OUTCOME_FAIL)
    reopened = get_success_data(
        api_client.list_findings(audit_id, make_quality_auditor_headers())
    )
    add_reverification_request(world, audit_id, reopened)
    return {"audit_id": audit_id, "findings": reopened}


# --- Tier 5: composed worlds ----------------------------------------------
def shelf_ready_world(*, plan_overrides=None, batch_overrides=None,
                      lot_overrides=None, **base_kwargs) -> dict:
    """Base world plus a released plan, an approved rice batch and a released lot."""
    world = base_world(**base_kwargs)
    plan = add_released_plan(world, **(plan_overrides or {}))
    batch = add_approved_rice_batch(world, plan["id"], **(batch_overrides or {}))
    fish_lot = add_released_fish_lot(world, **(lot_overrides or {}))
    world.update(
        {
            "plan": plan,
            "plan_id": plan["id"],
            "rice_batch": batch,
            "rice_batch_id": batch["id"],
            "fish_lot": fish_lot,
            "fish_lot_id": fish_lot["id"],
        }
    )
    return world


def packed_world(*, pack_overrides=None, **kwargs) -> dict:
    """Shelf-ready world plus one pack lot on the shelf."""
    world = shelf_ready_world(**kwargs)
    pack_lot = add_pack_lot(
        world, world["rice_batch_id"], world["fish_lot_id"], **(pack_overrides or {})
    )
    world.update({"pack_lot": pack_lot, "pack_lot_id": pack_lot["id"]})
    return world


def settled_world(*, feed_overrides=None, statement_overrides=None, **kwargs) -> dict:
    """Packed world plus a reconciled POS feed and a draft settlement statement."""
    world = packed_world(**kwargs)
    feed = add_reconciled_feed(world, **(feed_overrides or {}))
    statement = add_draft_statement(world, **(statement_overrides or {}))
    world.update(
        {
            "feed": feed,
            "feed_id": feed["id"],
            "statement": statement,
            "statement_id": statement["id"],
        }
    )
    return world


def discard_pack_lot_as_auditor(world: dict, pack_lot_id: str,
                                reason: str = DISCARD_SHELF_LIFE_EXPIRED) -> dict:
    """Discards a pack lot's unsold packs as a quality auditor.

    Returns the appended discard event. The discard call itself answers with the
    updated pack lot, because a state transition returns its parent resource
    unless the nested child it creates is "a finding, a cold-chain reading"; the
    event is read back from the lot's nested discard-event list, which is the only
    channel through which discard events surface.
    """
    get_success_data(
        api_client.discard_pack_lot(
            pack_lot_id, discard_payload(reason), world["auditor_headers"]
        )
    )
    events = get_success_data(
        api_client.list_discard_events(pack_lot_id, world["ops_headers"])
    )
    return events[-1]
