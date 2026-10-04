"""Composite setup helpers for the guaranteed-savings performance contract API.

Every fixture builds its preconditions from scratch through public endpoints
(the server is restarted before every test). Setup calls use get_success_data
so a broken precondition surfaces as a clear 'Setup failed' message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_adjustment_payload,
    create_baseline_payload,
    create_bundle_payload,
    create_contract_payload,
    create_dispute_payload,
    create_disruption_payload,
    create_draw_payload,
    create_esco_engineer_payload,
    create_facility_payload,
    create_measure_payload,
    create_owner_rep_payload,
    create_phase_payload,
    create_report_payload,
)
from .test_users import (
    make_esco_engineer_headers,
    make_lender_officer_headers,
    make_owner_rep_headers,
    make_platform_admin_headers,
)


def _ok(response, step: str):
    data = get_success_data(response)
    assert isinstance(data, dict), f"Setup failed at {step}: {response.text}"
    return data


def set_clock(current_utc: str):
    return _ok(
        api_client.set_clock(
            {"current_utc": current_utc}, make_platform_admin_headers()
        ),
        f"set_clock({current_utc})",
    )


def reset_clock():
    """Restore the logical clock to its documented default instant."""
    return set_clock(TEST_DEFAULTS.get("CLOCK_DEFAULT", "2026-09-01T00:00:00Z"))


def make_actor_ids():
    """Register one ESCO engineer and one owner rep; return (eng_id, owner_id)."""
    eng = _ok(
        api_client.create_esco_engineer(
            create_esco_engineer_payload(), make_platform_admin_headers()
        ),
        "create_esco_engineer",
    )
    owner = _ok(
        api_client.create_owner_rep(
            create_owner_rep_payload(), make_platform_admin_headers()
        ),
        "create_owner_rep",
    )
    return eng["id"], owner["id"]


def eng_headers(eng_id):
    return make_esco_engineer_headers(eng_id)


def own_headers(owner_id):
    return make_owner_rep_headers(owner_id)


def lender_headers():
    return make_lender_officer_headers()


def create_contract(eng_id, **overrides):
    return _ok(
        api_client.create_contract(
            create_contract_payload(**overrides), eng_headers(eng_id)
        ),
        "create_contract",
    )


def add_approved_baseline(contract_id, eng_id, owner_id, **overrides):
    """Create + submit + approve a baseline. Returns the baseline dict."""
    baseline = _ok(
        api_client.create_baseline(
            contract_id, create_baseline_payload(**overrides), eng_headers(eng_id)
        ),
        "create_baseline",
    )
    _ok(
        api_client.submit_baseline(contract_id, baseline["id"], eng_headers(eng_id)),
        "submit_baseline",
    )
    return _ok(
        api_client.approve_baseline(
            contract_id, baseline["id"], own_headers(owner_id)
        ),
        "approve_baseline",
    )


def add_bundle_with_measures(contract_id, eng_id, owner_id, measures, approve=True,
                             bundle_name="Scope"):
    """Create a bundle with the given measure payloads, propose it, and
    optionally approve it. Returns (bundle, measures list)."""
    bundle = _ok(
        api_client.create_bundle(
            contract_id, create_bundle_payload(name=bundle_name),
            eng_headers(eng_id),
        ),
        "create_bundle",
    )
    created = []
    for m in measures:
        created.append(
            _ok(
                api_client.create_measure(
                    contract_id, bundle["id"], m, eng_headers(eng_id)
                ),
                "create_measure",
            )
        )
    _ok(
        api_client.propose_bundle(contract_id, bundle["id"], eng_headers(eng_id)),
        "propose_bundle",
    )
    if approve:
        bundle = _ok(
            api_client.approve_bundle(
                contract_id, bundle["id"], own_headers(owner_id)
            ),
            "approve_bundle",
        )
    return bundle, created


def add_facility(contract_id, eng_id, lender_approve=False, **overrides):
    """Create (and optionally submit+approve) a facility. Returns the dict."""
    facility = _ok(
        api_client.create_facility(
            contract_id, create_facility_payload(**overrides), eng_headers(eng_id)
        ),
        "create_facility",
    )
    if lender_approve:
        _ok(
            api_client.submit_facility(
                contract_id, facility["id"], eng_headers(eng_id)
            ),
            "submit_facility",
        )
        facility = _ok(
            api_client.approve_facility(
                contract_id, facility["id"], lender_headers()
            ),
            "approve_facility",
        )
    return facility


def scoped_contract(eng_id, owner_id, *, measures=None, approve_bundle=False,
                    with_approved_facility=False, **kwargs):
    """Contract walked AUDIT -> SCOPED: approved baseline, at least one
    measure, complete-audit done. Returns (contract, baseline, bundle,
    measures, facility_or_None).

    Keyword overrides prefixed ``baseline_`` route to the baseline factory;
    everything else routes to the contract factory."""
    baseline_overrides = {
        k[len("baseline_"):]: v for k, v in kwargs.items()
        if k.startswith("baseline_")
    }
    contract_overrides = {
        k: v for k, v in kwargs.items() if not k.startswith("baseline_")
    }
    contract = create_contract(eng_id, **contract_overrides)
    cid = contract["id"]
    baseline = add_approved_baseline(cid, eng_id, owner_id, **baseline_overrides)
    measures = measures if measures is not None else [create_measure_payload()]
    bundle, created = add_bundle_with_measures(
        cid, eng_id, owner_id, measures, approve=approve_bundle
    )
    facility = None
    if with_approved_facility:
        facility = _ok(
            api_client.create_facility(
                cid, create_facility_payload(), eng_headers(eng_id)
            ),
            "create_facility",
        )
    _ok(api_client.complete_audit(cid, eng_headers(eng_id)), "complete_audit")
    if with_approved_facility:
        _ok(
            api_client.submit_facility(cid, facility["id"], eng_headers(eng_id)),
            "submit_facility",
        )
        facility = _ok(
            api_client.approve_facility(cid, facility["id"], lender_headers()),
            "approve_facility",
        )
    contract = _ok(
        api_client.get_contract(cid, eng_headers(eng_id)), "get_contract"
    )
    return contract, baseline, bundle, created, facility


def executed_contract(eng_id, owner_id, **contract_overrides):
    """Contract walked to EXECUTED: scoped + bundle APPROVED + facility
    APPROVED + execute. Returns (contract, baseline, bundle, measures,
    facility)."""
    contract, baseline, bundle, measures, facility = scoped_contract(
        eng_id, owner_id, approve_bundle=True, with_approved_facility=True,
        **contract_overrides,
    )
    cid = contract["id"]
    _ok(api_client.execute_contract(cid, own_headers(owner_id)), "execute")
    contract = _ok(api_client.get_contract(cid, eng_headers(eng_id)), "get")
    return contract, baseline, bundle, measures, facility


def construction_contract(eng_id, owner_id, *, phase_overrides=None,
                          start_phase=False, **contract_overrides):
    """Contract walked to CONSTRUCTION with one phase (MOBILIZED; optionally
    started -> IN_PROGRESS). Returns (contract, baseline, bundle, measures,
    facility, phase)."""
    contract, baseline, bundle, measures, facility = executed_contract(
        eng_id, owner_id, **contract_overrides
    )
    cid = contract["id"]
    phase = _ok(
        api_client.create_phase(
            cid, create_phase_payload(**(phase_overrides or {})),
            eng_headers(eng_id),
        ),
        "create_phase",
    )
    _ok(api_client.mobilize_phase(cid, phase["id"], eng_headers(eng_id)),
        "mobilize_phase")
    _ok(api_client.mobilize_contract(cid, eng_headers(eng_id)), "mobilize_contract")
    if start_phase:
        _ok(api_client.start_phase(cid, phase["id"], eng_headers(eng_id)),
            "start_phase")
    # Re-fetch entities mutated by the mobilize cascade (facility APPROVED ->
    # FUNDING) so callers observe current server state, not stale snapshots.
    facility = _ok(
        api_client.get_facility(cid, facility["id"], eng_headers(eng_id)),
        "get_facility",
    )
    phase = _ok(
        api_client.get_phase(cid, phase["id"], eng_headers(eng_id)),
        "get_phase",
    )
    contract = _ok(api_client.get_contract(cid, eng_headers(eng_id)), "get")
    return contract, baseline, bundle, measures, facility, phase


def performance_contract(eng_id, owner_id, *, end_year_1=True,
                         **contract_overrides):
    """Full lifecycle to PERFORMANCE: construction, measures installed and
    verified, phase completed, commence-performance. Optionally advances the
    clock past guarantee year 1. Returns (contract, baseline, bundle, measures,
    facility, phase)."""
    contract, baseline, bundle, measures, facility, phase = construction_contract(
        eng_id, owner_id, start_phase=True, **contract_overrides
    )
    cid = contract["id"]
    for m in measures:
        _ok(
            api_client.install_measure(cid, bundle["id"], m["id"],
                                       eng_headers(eng_id)),
            "install_measure",
        )
        _ok(
            api_client.verify_measure(cid, bundle["id"], m["id"],
                                      own_headers(owner_id)),
            "verify_measure",
        )
    _ok(api_client.complete_phase(cid, phase["id"], own_headers(owner_id)),
        "complete_phase")
    set_clock(TEST_DEFAULTS["GUARANTEE_START_DATE"])
    _ok(api_client.commence_performance(cid, own_headers(owner_id)),
        "commence_performance")
    if end_year_1:
        set_clock(TEST_DEFAULTS["YEAR1_ENDED_CLOCK"])
    contract = _ok(api_client.get_contract(cid, eng_headers(eng_id)), "get")
    return contract, baseline, bundle, measures, facility, phase


def create_and_submit_report(contract_id, eng_id, **report_overrides):
    """Create + submit a report on a PERFORMANCE contract (clock must be past
    the period end). Returns the submitted report dict."""
    report = _ok(
        api_client.create_report(
            contract_id, create_report_payload(**report_overrides),
            eng_headers(eng_id),
        ),
        "create_report",
    )
    return _ok(
        api_client.submit_report(contract_id, report["id"], eng_headers(eng_id)),
        "submit_report",
    )


def attested_report(contract_id, eng_id, owner_id, **report_overrides):
    """Create + submit + attest a report. Returns the attested report dict."""
    report = create_and_submit_report(contract_id, eng_id, **report_overrides)
    return _ok(
        api_client.attest_report(contract_id, report["id"], own_headers(owner_id)),
        "attest_report",
    )
