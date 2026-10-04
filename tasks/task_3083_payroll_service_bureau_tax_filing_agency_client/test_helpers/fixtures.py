"""Composite setup helpers.

Every fixture builds preconditions from an empty database using only
PRD-declared endpoints. Setup calls use get_success_data so failures surface
as clear "Setup failed" messages. ClientPayrollAdmin calls always carry the
owning client's id in X-User-ID (PRD §2.1).
"""
import uuid as _uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_client_payload,
    create_jurisdiction_payload,
    create_payroll_run_payload,
    create_registration_payload,
)
from .test_users import TEST_USERS, make_client_admin_headers

EIN_COUNTER = {"n": 1000}


def _ein() -> str:
    EIN_COUNTER["n"] += 1
    return f"99-{EIN_COUNTER['n']:07d}"


def create_jurisdiction(**overrides):
    """Create a jurisdiction. Returns the Jurisdiction dict."""
    payload = create_jurisdiction_payload(**overrides)
    resp = api_client.create_jurisdiction(payload, TEST_USERS["compliance_headers"])
    return get_success_data(resp)


def create_client(**overrides):
    """Create a client (starts PROSPECT). Returns the Client dict."""
    overrides.setdefault("ein", _ein())
    resp = api_client.create_client(
        create_client_payload(**overrides), TEST_USERS["onboarder_headers"]
    )
    return get_success_data(resp)


def setup_active_client(jurisdiction=None, legal_name="Test Client Co", **jur_overrides):
    """Client fully onboarded and ACTIVE with one VERIFIED registration.

    Returns dict(client=..., jurisdiction=..., registration=...).
    """
    jurisdiction = jurisdiction or create_jurisdiction(**jur_overrides)
    client = create_client(legal_name=legal_name)
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    reg = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    client = get_success_data(
        api_client.activate_client(client["id"], TEST_USERS["onboarder_headers"])
    )
    return {"client": client, "jurisdiction": jurisdiction, "registration": reg}


def client_version(client_id):
    return get_success_data(
        api_client.get_client(client_id, TEST_USERS["compliance_headers"])
    )["version"]


def run_version(run_id):
    return get_success_data(
        api_client.get_payroll_run(run_id, TEST_USERS["filer_alpha_headers"])
    )["version"]


def create_run(client, **overrides):
    """Create a DRAFT payroll run for the client. Returns the run dict."""
    payload = create_payroll_run_payload(client_id=client["id"], **overrides)
    resp = api_client.create_payroll_run(payload, make_client_admin_headers(client["id"]))
    return get_success_data(resp)


def submit_run(client, run):
    """DRAFT -> SUBMITTED. Returns the updated run."""
    return get_success_data(
        api_client.submit_run(run["id"], make_client_admin_headers(client["id"]))
    )


def impound_run(client, run):
    """SUBMITTED -> IMPOUNDED; creates the Impound. Returns the impound dict."""
    resp = api_client.initiate_impound(
        run["id"], client_version(client["id"]), make_client_admin_headers(client["id"])
    )
    return get_success_data(resp)


def settle_impound(impound):
    """Impound PENDING -> SETTLED (also moves run IMPOUNDED -> SETTLED)."""
    return get_success_data(
        api_client.settle_impound(impound["id"], TEST_USERS["treasury_headers"])
    )


def fail_impound(impound):
    """Impound PENDING -> FAILED via bank NSF return (cascades per PRD §3.4)."""
    return get_success_data(
        api_client.fail_impound(impound["id"], TEST_USERS["treasury_headers"])
    )


def create_settled_run(client, **overrides):
    """Full happy path: DRAFT run -> SUBMITTED -> IMPOUNDED -> SETTLED.

    Returns dict(run=..., impound=...) with the run in SETTLED.
    """
    run = create_run(client, **overrides)
    submit_run(client, run)
    impound = impound_run(client, run)
    settle_impound(impound)
    run = get_success_data(
        api_client.get_payroll_run(run["id"], TEST_USERS["filer_alpha_headers"])
    )
    return {"run": run, "impound": impound}


def create_deposit(run, jurisdiction_id, amount_cents):
    """Schedule a deposit against a run (OCC on the run's version)."""
    resp = api_client.create_deposit(
        run["id"],
        {
            "jurisdiction_id": jurisdiction_id,
            "amount_cents": amount_cents,
            "expected_payroll_run_version": run_version(run["id"]),
        },
        TEST_USERS["filer_alpha_headers"],
    )
    return get_success_data(resp)


def create_confirmed_deposit(run, jurisdiction_id, amount_cents):
    """Schedule + submit + confirm a deposit. Returns the CONFIRMED deposit."""
    dep = create_deposit(run, jurisdiction_id, amount_cents)
    api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    return get_success_data(
        api_client.confirm_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )


def create_return_for(client, jurisdiction_id, period):
    """Create a DRAFT return (OCC on the client's version)."""
    resp = api_client.create_return(
        {
            "client_id": client["id"],
            "jurisdiction_id": jurisdiction_id,
            "period": period,
            "expected_client_version": client_version(client["id"]),
        },
        TEST_USERS["filer_alpha_headers"],
    )
    return get_success_data(resp)


def file_return(ret):
    """DRAFT -> FILED, filed by filer-alpha (SoD attribution)."""
    return get_success_data(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )


def accept_return(ret):
    """FILED -> ACCEPTED, accepted by filer-beta (satisfies SoD)."""
    return get_success_data(
        api_client.accept_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )


def create_accepted_return(client, jurisdiction_id, period):
    """Create + file + accept a return. Returns the ACCEPTED return."""
    ret = create_return_for(client, jurisdiction_id, period)
    file_return(ret)
    return accept_return(ret)


def create_nsf_strikes(client, n, pay_dates=None):
    """Apply n NSF strikes to the client (each fails a fresh impounded run).

    Returns list of created FundingFailureEvent-capable impounds (FAILED).
    """
    pay_dates = pay_dates or [
        "2026-09-04T00:00:00Z",
        "2026-09-08T00:00:00Z",
        "2026-09-11T00:00:00Z",
        "2026-09-15T00:00:00Z",
    ]
    impounds = []
    for i in range(n):
        run = create_run(
            client,
            pay_date=pay_dates[i],
            period_start="2026-08-22T00:00:00Z",
            period_end=pay_dates[i],
            gross_pay_cents=500000,
            total_tax_cents=100000,
        )
        submit_run(client, run)
        imp = impound_run(client, run)
        fail_impound(imp)
        impounds.append(imp)
    return impounds


def get_funding_failures(client_id, resolved=None):
    params = {} if resolved is None else {"resolved": str(resolved).lower()}
    return get_success_data(
        api_client.list_client_funding_failures(
            client_id, TEST_USERS["treasury_headers"], params=params
        )
    )


def get_client(client_id):
    return get_success_data(
        api_client.get_client(client_id, TEST_USERS["compliance_headers"])
    )


def get_run(run_id):
    return get_success_data(
        api_client.get_payroll_run(run_id, TEST_USERS["filer_alpha_headers"])
    )


def get_deposit(deposit_id):
    return get_success_data(
        api_client.get_deposit(deposit_id, TEST_USERS["filer_alpha_headers"])
    )


def set_clock(current_utc):
    """Advance the logical clock (PRD §2.6)."""
    return get_success_data(
        api_client.set_clock(current_utc, TEST_USERS["compliance_headers"])
    )


def new_ein():
    return _ein()


def random_uuid():
    return str(_uuid.uuid4())
