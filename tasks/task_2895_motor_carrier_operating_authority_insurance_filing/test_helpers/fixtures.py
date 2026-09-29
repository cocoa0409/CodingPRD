"""Composite setup helpers.

The harness restarts the server before every individual test, so each test
starts from an empty database and builds the state it needs through the public
endpoints of PRD S4.  These helpers walk the registry -> application ->
publication -> designation -> insurance -> activation -> contract -> shipment
chain of S3, pinning the logical compliance clock of S2.5 at each step, and
return a namespace carrying every record and every set of headers the test will
need afterwards.

Two roles are entity-backed (S2.1), so ``env.carrier_headers`` and
``env.insurer_headers`` are always built from the created rows' own ids.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as F
from .constants import T_ELIGIBLE, T_ENROLL, T_PUBLISH, MAX_LIMIT
from .test_users import (
    ACTIVATING_OFFICER,
    COMPLIANCE_OFFICER,
    PUBLISHING_ANALYST,
    REGISTRY_ADMIN,
    make_carrier_headers,
    make_insurer_headers,
)


# ---------------------------------------------------------------------------
# Atomic steps
# ---------------------------------------------------------------------------
def set_clock(client, instant: str, headers: Optional[Dict[str, str]] = None) -> str:
    """S2.5: move the logical compliance clock and return the resulting instant."""
    data = get_success_data(client.set_clock(instant, headers or REGISTRY_ADMIN))
    return data.get("current_utc")


def create_carrier(client, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_carrier(F.carrier_payload(**kwargs), REGISTRY_ADMIN), 201
    )


def create_process_agent(client, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_process_agent(F.process_agent_payload(**kwargs), REGISTRY_ADMIN),
        201,
    )


def create_insurer(client, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_insurer(F.insurer_payload(**kwargs), REGISTRY_ADMIN), 201
    )


def create_draft_application(client, carrier_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_application(
            F.application_payload(carrier_id, **kwargs), make_carrier_headers(carrier_id)
        ),
        201,
    )


def submit_application(client, carrier_id: str, application_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.submit_application(application_id, make_carrier_headers(carrier_id))
    )


def review_application(
    client,
    application_id: str,
    disposition: str = "PUBLISH",
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.review_application(
            application_id,
            F.vetting_review_payload(disposition=disposition, **kwargs),
            headers or PUBLISHING_ANALYST,
        )
    )


def authority_for_application(client, application_id: str) -> Dict[str, Any]:
    """S2.9: a published authority is discoverable only through this listing."""
    rows, _ = validate_paginated(
        client.list_authorities(REGISTRY_ADMIN, application_id=application_id)
    )
    assert rows, f"no OperatingAuthority was minted for application {application_id}"
    return rows[0]


def read_authority(client, authority_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(client.get_authority(authority_id, headers or REGISTRY_ADMIN))


def authority_version(client, authority_id: str) -> int:
    """S2.6: re-read the authority immediately before a guarded write."""
    return read_authority(client, authority_id)["version"]


def designate_states(
    client,
    carrier_id: str,
    authority_id: str,
    process_agent_id: str,
    state_codes: Optional[Sequence[str]] = None,
    effective_from: str = T_PUBLISH,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.create_designations(
            authority_id,
            F.designation_payload(
                process_agent_id,
                state_codes=state_codes,
                effective_from=effective_from,
                **kwargs,
            ),
            make_carrier_headers(carrier_id),
        ),
        201,
    )


def file_insurance(
    client,
    insurer_id: str,
    authority_id: str,
    coverage_limit_cents: int,
    filing_type: str = "BIPD",
    effective_at: str = T_PUBLISH,
    policy_number: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Read the authority's current version, then file under the S2.6 guard."""
    version = authority_version(client, authority_id)
    return get_success_data(
        client.create_filing(
            F.filing_payload(
                authority_id,
                insurer_id,
                coverage_limit_cents,
                version,
                filing_type=filing_type,
                policy_number=policy_number or f"{filing_type}-1",
                effective_at=effective_at,
                **kwargs,
            ),
            make_insurer_headers(insurer_id),
        ),
        201,
    )


def file_all_required_insurance(
    client, authority: Dict[str, Any], insurer_id: str, effective_at: str = T_PUBLISH
) -> Dict[str, Dict[str, Any]]:
    """S3.5: satisfy exactly the slots this authority requires, at the minimum."""
    filings: Dict[str, Dict[str, Any]] = {}
    if authority["required_bipd_limit_cents"] > 0:
        filings["BIPD"] = file_insurance(
            client,
            insurer_id,
            authority["id"],
            authority["required_bipd_limit_cents"],
            filing_type="BIPD",
            effective_at=effective_at,
        )
    if authority["required_cargo_limit_cents"] > 0:
        filings["CARGO"] = file_insurance(
            client,
            insurer_id,
            authority["id"],
            authority["required_cargo_limit_cents"],
            filing_type="CARGO",
            effective_at=effective_at,
        )
    if authority["required_bond_limit_cents"] > 0:
        filings["SURETY_BOND"] = file_insurance(
            client,
            insurer_id,
            authority["id"],
            authority["required_bond_limit_cents"],
            filing_type="SURETY_BOND",
            effective_at=effective_at,
        )
    return filings


def pay_fee(client, carrier_id: str, amount_cents: int, memo: str = "docket filing fee"):
    return get_success_data(
        client.record_fee_payment(
            carrier_id,
            F.fee_payment_payload(amount_cents, memo=memo),
            make_carrier_headers(carrier_id),
        ),
        201,
    )


def settle_fee_balance(client, carrier_id: str) -> Dict[str, Any]:
    """Pay exactly the outstanding balance so S2.8 priority 31 is satisfied."""
    carrier = get_success_data(client.get_carrier(carrier_id, REGISTRY_ADMIN))
    outstanding = carrier["fee_balance_cents"]
    if outstanding <= 0:
        return carrier
    return pay_fee(client, carrier_id, outstanding)


def activate_authority(
    client, authority_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.activate_authority(authority_id, headers or ACTIVATING_OFFICER)
    )


def create_contract(
    client, carrier_id: str, authority_id: str, **kwargs: Any
) -> Dict[str, Any]:
    version = kwargs.pop("expected_authority_version", None)
    if version is None:
        version = authority_version(client, authority_id)
    return get_success_data(
        client.create_contract(
            authority_id,
            F.contract_payload(version, **kwargs),
            make_carrier_headers(carrier_id),
        ),
        201,
    )


def tender_shipment(client, carrier_id: str, contract_id: str, **kwargs: Any):
    return get_success_data(
        client.create_shipment(
            contract_id, F.shipment_payload(**kwargs), make_carrier_headers(carrier_id)
        ),
        201,
    )


def depart_shipment(client, carrier_id: str, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.depart_shipment(shipment_id, make_carrier_headers(carrier_id))
    )


def deliver_shipment(client, carrier_id: str, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.deliver_shipment(shipment_id, make_carrier_headers(carrier_id))
    )


def cancel_filing(client, insurer_id: str, filing_id: str, cancellation_effective_at: str):
    return get_success_data(
        client.cancel_filing(
            filing_id,
            F.cancel_filing_payload(cancellation_effective_at),
            make_insurer_headers(insurer_id),
        )
    )


def run_sweep(client, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(client.run_compliance_sweep(headers or COMPLIANCE_OFFICER))


def scheduled_audit(client, carrier_id: str) -> Dict[str, Any]:
    """S2.9: a SafetyAudit is discoverable only through this listing."""
    rows, _ = validate_paginated(
        client.list_carrier_safety_audits(carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    scheduled = [row for row in rows if row.get("status") == "SCHEDULED"]
    assert scheduled, f"no SCHEDULED SafetyAudit exists for carrier {carrier_id}"
    return scheduled[0]


def open_proceeding(client, authority_id: str) -> Dict[str, Any]:
    """S2.9: a RevocationProceeding is discoverable only through this listing."""
    rows, _ = validate_paginated(
        client.list_authority_proceedings(authority_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    open_rows = [row for row in rows if row.get("status") == "NOTICE_ISSUED"]
    assert open_rows, f"no open RevocationProceeding exists on authority {authority_id}"
    return open_rows[-1]


def list_designations(client, authority_id: str, **params: Any) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        client.list_designations(
            REGISTRY_ADMIN, authority_id=authority_id, limit=MAX_LIMIT, **params
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Composite state builders
# ---------------------------------------------------------------------------
def _env(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def setup_registry(
    client,
    *,
    enroll_at: str = T_ENROLL,
    carrier_kwargs: Optional[Dict[str, Any]] = None,
    agent_kwargs: Optional[Dict[str, Any]] = None,
    insurer_kwargs: Optional[Dict[str, Any]] = None,
    coverage_states: Optional[Sequence[str]] = None,
    with_agent: bool = True,
    with_insurer: bool = True,
) -> SimpleNamespace:
    """S3.1: a carrier plus (by default) one process agent and one insurer.

    ``coverage_states`` widens both the agent's coverage_states and the
    insurer's authorized_states in one shot, which is what most chains need.
    """
    set_clock(client, enroll_at)
    carrier = create_carrier(client, **(carrier_kwargs or {}))
    env = _env(
        carrier=carrier,
        carrier_id=carrier["id"],
        carrier_headers=make_carrier_headers(carrier["id"]),
        agent=None,
        agent_id=None,
        insurer=None,
        insurer_id=None,
        insurer_headers=None,
        enroll_at=enroll_at,
    )
    if with_agent:
        kw = dict(agent_kwargs or {})
        if coverage_states is not None and "coverage_states" not in kw:
            kw["coverage_states"] = list(coverage_states)
        env.agent = create_process_agent(client, **kw)
        env.agent_id = env.agent["id"]
    if with_insurer:
        kw = dict(insurer_kwargs or {})
        if coverage_states is not None and "authorized_states" not in kw:
            kw["authorized_states"] = list(coverage_states)
        env.insurer = create_insurer(client, **kw)
        env.insurer_id = env.insurer["id"]
        env.insurer_headers = make_insurer_headers(env.insurer["id"])
    return env


def setup_submitted_application(
    client,
    *,
    application_kwargs: Optional[Dict[str, Any]] = None,
    submit_at: Optional[str] = None,
    **registry_kwargs: Any,
) -> SimpleNamespace:
    """S3.3: a SUBMITTED application whose docket number and fee are settled."""
    app_kwargs = dict(application_kwargs or {})
    states = app_kwargs.get("requested_operating_states")
    if states is not None and "coverage_states" not in registry_kwargs:
        registry_kwargs.setdefault("coverage_states", list(states))
    env = setup_registry(client, **registry_kwargs)
    env.application = create_draft_application(client, env.carrier_id, **app_kwargs)
    if submit_at:
        set_clock(client, submit_at)
    env.application = submit_application(client, env.carrier_id, env.application["id"])
    env.application_id = env.application["id"]
    env.filing_fee_cents = env.application["filing_fee_cents"]
    return env


def setup_published_authority(
    client,
    *,
    publish_at: str = T_PUBLISH,
    analyst: Optional[Dict[str, str]] = None,
    review_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> SimpleNamespace:
    """S3.3 + S2.9: a PUBLISHED application and the authority it minted."""
    env = setup_submitted_application(client, **kwargs)
    set_clock(client, publish_at)
    env.application = review_application(
        client,
        env.application_id,
        disposition="PUBLISH",
        headers=analyst or PUBLISHING_ANALYST,
        **(review_kwargs or {}),
    )
    env.publish_at = publish_at
    env.authority = authority_for_application(client, env.application_id)
    env.authority_id = env.authority["id"]
    return env


def setup_pending_authority_with_coverage(
    client,
    *,
    designation_states: Optional[Sequence[str]] = None,
    designation_from: Optional[str] = None,
    insurance_effective_at: Optional[str] = None,
    pay_fee_in_full: bool = True,
    **kwargs: Any,
) -> SimpleNamespace:
    """Everything the S2.8 activation ladder demands except the waiting period.

    Designations cover exactly the authority's ``required_jurisdictions`` and
    each insurance slot is filed at exactly its required minimum, so the
    authority is one clock tick away from a clean activation.
    """
    env = setup_published_authority(client, **kwargs)
    effective_from = designation_from or env.publish_at
    env.designations = designate_states(
        client,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=list(designation_states or env.authority["required_jurisdictions"]),
        effective_from=effective_from,
    )
    env.designation_from = effective_from
    env.filings = file_all_required_insurance(
        client,
        env.authority,
        env.insurer_id,
        effective_at=insurance_effective_at or env.publish_at,
    )
    env.filing = env.filings.get("BIPD")
    if pay_fee_in_full:
        env.carrier = settle_fee_balance(client, env.carrier_id)
    env.authority = read_authority(client, env.authority_id)
    return env


def setup_active_authority(
    client, *, activate_at: Optional[str] = None, officer=None, **kwargs: Any
) -> SimpleNamespace:
    """S3.6: an ACTIVE authority, its clock parked on the activation instant."""
    env = setup_pending_authority_with_coverage(client, **kwargs)
    env.activate_at = activate_at or env.authority["activation_eligible_at"]
    set_clock(client, env.activate_at)
    env.authority = activate_authority(client, env.authority_id, officer)
    env.carrier = get_success_data(client.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    env.audit = None
    rows, _ = validate_paginated(
        client.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN)
    )
    if rows:
        env.audit = rows[0]
        env.audit_id = rows[0]["id"]
    return env


def setup_active_authority_with_contract(
    client,
    *,
    contract_kwargs: Optional[Dict[str, Any]] = None,
    contract_at: Optional[str] = None,
    **kwargs: Any,
) -> SimpleNamespace:
    """S3.9: one ACTIVE contract hanging off an ACTIVE authority."""
    env = setup_active_authority(client, **kwargs)
    if contract_at:
        set_clock(client, contract_at)
        env.contract_at = contract_at
    env.contract = create_contract(
        client, env.carrier_id, env.authority_id, **(contract_kwargs or {})
    )
    env.contract_id = env.contract["id"]
    env.authority = read_authority(client, env.authority_id)
    return env


def setup_active_authority_with_shipment(
    client,
    *,
    shipment_kwargs: Optional[Dict[str, Any]] = None,
    depart: bool = False,
    tender_at: Optional[str] = None,
    **kwargs: Any,
) -> SimpleNamespace:
    """S3.9: a TENDERED (or IN_TRANSIT) shipment under an ACTIVE contract."""
    env = setup_active_authority_with_contract(client, **kwargs)
    if tender_at:
        set_clock(client, tender_at)
        env.tender_at = tender_at
    env.shipment = tender_shipment(
        client, env.carrier_id, env.contract_id, **(shipment_kwargs or {})
    )
    env.shipment_id = env.shipment["id"]
    if depart:
        env.shipment = depart_shipment(client, env.carrier_id, env.shipment_id)
    return env


def setup_suspended_by_filing_cancel(
    client, *, cancel_at: str = "2026-09-10T00:00:00Z", **kwargs: Any
) -> SimpleNamespace:
    """S3.5 + S3.8: cancellation of the only BIPD filing drives the cascade.

    Leaves the authority SUSPENDED for INSURANCE_LAPSE with an open
    RevocationProceeding, the clock parked on the cancellation instant.
    """
    env = kwargs.pop("env", None) or setup_active_authority_with_contract(client, **kwargs)
    set_clock(client, cancel_at)
    env.cancel_at = cancel_at
    env.filing = cancel_filing(client, env.insurer_id, env.filings["BIPD"]["id"], cancel_at)
    env.authority = read_authority(client, env.authority_id)
    env.proceeding = open_proceeding(client, env.authority_id)
    env.proceeding_id = env.proceeding["id"]
    return env


def setup_suspended_with_shipment(
    client,
    *,
    cancel_at: str = "2026-09-10T00:00:00Z",
    depart: bool = True,
    **kwargs: Any,
) -> SimpleNamespace:
    """A departed shipment that the S3.8 cascade must embargo."""
    env = setup_active_authority_with_shipment(client, depart=depart, **kwargs)
    env = setup_suspended_by_filing_cancel(client, cancel_at=cancel_at, env=env)
    env.shipment = get_success_data(
        client.get_shipment(env.shipment_id, env.carrier_headers)
    )
    return env


def cure_with_replacement_filing(
    client,
    env: SimpleNamespace,
    *,
    cure_at: str = "2026-09-14T00:00:00Z",
    policy_number: str = "BIPD-2",
    coverage_limit_cents: Optional[int] = None,
) -> SimpleNamespace:
    """S3.8: file a replacement at the minimum, then cure the proceeding."""
    set_clock(client, cure_at)
    env.cure_at = cure_at
    env.replacement_filing = file_insurance(
        client,
        env.insurer_id,
        env.authority_id,
        coverage_limit_cents
        if coverage_limit_cents is not None
        else env.authority["required_bipd_limit_cents"],
        filing_type="BIPD",
        effective_at=cure_at,
        policy_number=policy_number,
    )
    env.proceeding = get_success_data(
        client.cure_proceeding(
            env.proceeding_id, F.cure_payload(policy_number), COMPLIANCE_OFFICER
        )
    )
    env.authority = read_authority(client, env.authority_id)
    return env


def setup_scheduled_audit(client, **kwargs: Any) -> SimpleNamespace:
    """S3.7: the SCHEDULED new-entrant audit minted by activation."""
    env = setup_active_authority(client, **kwargs)
    env.audit = scheduled_audit(client, env.carrier_id)
    env.audit_id = env.audit["id"]
    return env


def record_audit(
    client,
    env: SimpleNamespace,
    *,
    at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **audit_kwargs: Any,
) -> SimpleNamespace:
    """S3.7: post one audit result and refresh the records it touches."""
    if at:
        set_clock(client, at)
        env.audit_at = at
    env.audit = get_success_data(
        client.record_audit_result(
            env.audit_id,
            F.audit_result_payload(**audit_kwargs),
            headers or COMPLIANCE_OFFICER,
        )
    )
    env.carrier = get_success_data(client.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    env.authority = read_authority(client, env.authority_id)
    return env


def setup_delinquent_carrier(
    client, *, delinquent_at: str = "2028-03-01T00:00:00Z", **kwargs: Any
) -> SimpleNamespace:
    """S3.10: push the clock past the audit deadline and sweep, so the carrier
    is AUDIT_DELINQUENT with its authority SUSPENDED."""
    env = setup_scheduled_audit(client, **kwargs)
    set_clock(client, delinquent_at)
    env.delinquent_at = delinquent_at
    env.sweep = run_sweep(client)
    env.carrier = get_success_data(client.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    env.authority = read_authority(client, env.authority_id)
    rows, _ = validate_paginated(
        client.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN)
    )
    env.audit = rows[0] if rows else None
    return env
