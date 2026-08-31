"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its own
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient validator so a broken precondition surfaces as "Setup step failed"
rather than as a confusing assertion inside the test body.

Identity threading matters: `PlanSponsorAdmin`, `VendorRepresentative` and
`Participant` are entity-backed roles, so every ownership-gated call below
passes the acting entity's own id through `make_*_headers`.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import OFFICER_ONE, OFFICER_TWO, TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_balance_report_payload,
    create_election_payload,
    create_employer_payload,
    create_movement_request_payload,
    create_notice_payload,
    create_participant_payload,
    create_participant_request_payload,
    create_plan_payload,
    create_remittance_batch_payload,
    create_vendor_account_payload,
    create_vendor_payload,
    make_line_item,
)
from .test_users import (
    make_officer_headers,
    make_operator_headers,
    make_participant_headers,
    make_sponsor_headers,
    make_vendor_headers,
)

CLOCK_DEFAULT = TEST_DEFAULTS["CLOCK_DEFAULT"]
FRESH_FEED = TEST_DEFAULTS["FRESH_FEED_DATE"]


# ---------------------------------------------------------------------------
# Tier 0 — primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_DEFAULT) -> dict:
    """Move the logical clock. Returns {current_utc, previous_utc}."""
    return get_success_data(
        api.set_clock({"to_iso8601": to_iso8601}, make_operator_headers())
    )


def register_employer(**overrides) -> dict:
    return get_success_data(
        api.create_employer(create_employer_payload(**overrides), make_operator_headers())
    )


def register_public_school_employer(**overrides) -> dict:
    return register_employer(**overrides)


def register_nonqualified_employer(**overrides) -> dict:
    """A TAX_EXEMPT_501C3 / OTHER sponsor: neither governmental nor qualified."""
    payload = {
        "legal_name": "Lakeside Community Trust",
        "ein": "33-3333333",
        "entity_type": "TAX_EXEMPT_501C3",
        "organization_subtype": "OTHER",
        "total_employee_count": 300,
    }
    payload.update(overrides)
    return register_employer(**payload)


def register_church_employer(**overrides) -> dict:
    payload = {
        "legal_name": "Grace Assembly",
        "ein": "55-5555555",
        "entity_type": "CHURCH",
        "organization_subtype": "CHURCH_ORG",
        "total_employee_count": 40,
    }
    payload.update(overrides)
    return register_employer(**payload)


def register_vendor(**overrides) -> dict:
    return get_success_data(
        api.create_vendor(create_vendor_payload(**overrides), make_operator_headers())
    )


def register_second_vendor(**overrides) -> dict:
    payload = {
        "legal_name": "Cedar Custodial",
        "vendor_code": "CDR",
        "contact_email": "ops@cedar.example",
    }
    payload.update(overrides)
    return register_vendor(**payload)


def create_plan(employer_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_plan(
            create_plan_payload(employer_id, **overrides), make_sponsor_headers(employer_id)
        )
    )


def move_plan(plan_id: str, employer_id: str, to_status: str) -> dict:
    return get_success_data(
        api.set_plan_status(plan_id, {"to_status": to_status}, make_sponsor_headers(employer_id))
    )


def create_active_plan(employer_id: str, **overrides) -> dict:
    plan = create_plan(employer_id, **overrides)
    return move_plan(plan["id"], employer_id, "ACTIVE")


def create_agreement(plan_id: str, vendor_id: str, employer_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_agreement(
            create_agreement_payload(plan_id, vendor_id, **overrides),
            make_sponsor_headers(employer_id),
        )
    )


def move_agreement(agreement_id: str, employer_id: str, to_status: str) -> dict:
    return get_success_data(
        api.set_agreement_status(
            agreement_id, {"to_status": to_status}, make_sponsor_headers(employer_id)
        )
    )


def post_data_feed(agreement_id: str, vendor_id: str, data_current_through_date: str = FRESH_FEED) -> dict:
    return get_success_data(
        api.post_data_feed(
            agreement_id,
            {"data_current_through_date": data_current_through_date},
            make_vendor_headers(vendor_id),
        )
    )


def setup_active_agreement(
    plan_id: str,
    vendor_id: str,
    employer_id: str,
    feed_date: Optional[str] = FRESH_FEED,
    **overrides,
) -> dict:
    """Create an agreement, activate it and (optionally) post a data feed."""
    agreement = create_agreement(plan_id, vendor_id, employer_id, **overrides)
    agreement = move_agreement(agreement["id"], employer_id, "ACTIVE")
    if feed_date is not None:
        agreement = post_data_feed(agreement["id"], vendor_id, feed_date)
    return agreement


def register_participant(employer_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_participant(
            create_participant_payload(employer_id, **overrides),
            make_sponsor_headers(employer_id),
        )
    )


def read_participant(participant_id: str, employer_id: str) -> dict:
    return get_success_data(
        api.get_participant(participant_id, make_sponsor_headers(employer_id))
    )


def participant_version(participant_id: str, employer_id: str) -> int:
    return read_participant(participant_id, employer_id)["version"]


def update_participant(participant_id: str, employer_id: str, **fields) -> dict:
    return get_success_data(
        api.update_participant(participant_id, fields, make_sponsor_headers(employer_id))
    )


def open_contract(
    participant_id: str, plan_id: str, vendor_id: str, employer_id: str, **overrides
) -> dict:
    return get_success_data(
        api.create_vendor_account(
            create_vendor_account_payload(participant_id, plan_id, vendor_id, **overrides),
            make_sponsor_headers(employer_id),
        )
    )


def read_contract(account_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_vendor_account(account_id, headers or make_officer_headers())
    )


def contract_version(account_id: str, vendor_id: str) -> int:
    return get_success_data(
        api.get_vendor_account(account_id, make_vendor_headers(vendor_id))
    )["version"]


def report_balance(account_id: str, vendor_id: str, **figures) -> dict:
    """Read the contract's current version, then post a balance report."""
    version = contract_version(account_id, vendor_id)
    payload = create_balance_report_payload(version, **figures)
    return get_success_data(
        api.report_balance(account_id, payload, make_vendor_headers(vendor_id))
    )


def file_notice(plan_id: str, employer_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_notice(
            plan_id, create_notice_payload(**overrides), make_sponsor_headers(employer_id)
        )
    )


def determine_eligibility(
    plan_id: str, participant_id: str, officer: str = OFFICER_ONE, **overrides
) -> dict:
    payload = {"plan_id": plan_id, "participant_id": participant_id}
    payload.update(overrides)
    return get_success_data(
        api.create_eligibility_determination(payload, make_officer_headers(officer))
    )


def submit_election(
    participant_id: str, plan_id: str, vendor_account_id: str, employer_id: str, **overrides
) -> dict:
    """Submit an election, reading the participant's current version first."""
    version = overrides.pop(
        "expected_participant_version", participant_version(participant_id, employer_id)
    )
    payload = create_election_payload(
        participant_id, plan_id, vendor_account_id, version, **overrides
    )
    return get_success_data(
        api.create_election(payload, make_sponsor_headers(employer_id))
    )


def decide_election(election_id: str, decision: str, officer: str = OFFICER_TWO, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api.decide_election(election_id, payload, make_officer_headers(officer))
    )


def approve_election(election_id: str, officer: str = OFFICER_TWO) -> dict:
    return decide_election(election_id, "APPROVE", officer)


def revoke_election(election_id: str, employer_id: str, reason: str = "withdrawn") -> dict:
    return get_success_data(
        api.revoke_election(election_id, {"reason": reason}, make_sponsor_headers(employer_id))
    )


def create_batch(plan_id: str, employer_id: str, line_items: List[dict], **overrides) -> dict:
    return get_success_data(
        api.create_remittance_batch(
            create_remittance_batch_payload(plan_id, line_items, **overrides),
            make_sponsor_headers(employer_id),
        )
    )


def deposit_batch(batch_id: str, employer_id: str, deposit_date: str) -> dict:
    return get_success_data(
        api.deposit_remittance_batch(
            batch_id, {"deposit_date": deposit_date}, make_sponsor_headers(employer_id)
        )
    )


def reverse_batch(batch_id: str, employer_id: str, reason: str = "payroll file superseded") -> dict:
    return get_success_data(
        api.reverse_remittance_batch(
            batch_id, {"reason": reason}, make_sponsor_headers(employer_id)
        )
    )


def list_corrections(batch_id: str, params: Optional[Dict] = None) -> list:
    body = get_success_data(api.list_corrections(batch_id, make_officer_headers(), params))
    return body


def first_correction(batch_id: str) -> dict:
    rows = list_corrections(batch_id)
    assert rows, f"Setup step failed: batch {batch_id} produced no correction"
    return rows[0]


def settle_correction(
    batch_id: str, correction_id: str, reference: str = "VFCP-2026-0001", officer: str = OFFICER_TWO
) -> dict:
    return get_success_data(
        api.settle_correction(
            batch_id,
            correction_id,
            {"settlement_reference": reference},
            make_officer_headers(officer),
        )
    )


def submit_request(
    participant_id: str, plan_id: str, vendor_account_id: str, request_type: str, **overrides
) -> dict:
    payload = create_participant_request_payload(
        participant_id, plan_id, vendor_account_id, request_type, **overrides
    )
    return get_success_data(
        api.create_participant_request(payload, make_participant_headers(participant_id))
    )


def decide_request(request_id: str, decision: str, officer: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api.decide_participant_request(request_id, payload, make_officer_headers(officer))
    )


def begin_review(request_id: str, officer: str = OFFICER_ONE) -> dict:
    return decide_request(request_id, "BEGIN_REVIEW", officer)


def approve_request(request_id: str, officer: str = OFFICER_TWO) -> dict:
    return decide_request(request_id, "APPROVE", officer)


def fulfill_request(request_id: str, employer_id: str, fulfillment_date: str) -> dict:
    return get_success_data(
        api.fulfill_participant_request(
            request_id, {"fulfillment_date": fulfillment_date}, make_sponsor_headers(employer_id)
        )
    )


def submit_movement(
    participant_id: str,
    request_kind: str,
    source_plan_id: str,
    destination_plan_id: str,
    source_vendor_account_id: str,
    destination_vendor_account_id: str,
    amount_cents: int,
    employer_id: str,
) -> dict:
    payload = create_movement_request_payload(
        participant_id,
        request_kind,
        source_plan_id,
        destination_plan_id,
        source_vendor_account_id,
        destination_vendor_account_id,
        amount_cents,
    )
    return get_success_data(
        api.create_movement_request(payload, make_sponsor_headers(employer_id))
    )


def vendor_respond(request_id: str, vendor_id: str, accepted: bool, rejection_reason: str = None) -> dict:
    payload = {"accepted": accepted}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api.respond_to_movement_request(request_id, payload, make_vendor_headers(vendor_id))
    )


def decide_movement(request_id: str, decision: str, officer: str = OFFICER_ONE, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api.decide_movement_request(request_id, payload, make_officer_headers(officer))
    )


def execute_movement(request_id: str, employer_id: str, execution_date: str) -> dict:
    return get_success_data(
        api.execute_movement_request(
            request_id, {"execution_date": execution_date}, make_sponsor_headers(employer_id)
        )
    )


def reverse_movement(request_id: str, reason: str, officer: str = OFFICER_ONE) -> dict:
    return get_success_data(
        api.reverse_movement_request(request_id, {"reason": reason}, make_officer_headers(officer))
    )


# ---------------------------------------------------------------------------
# Tier 1 / 2 — sponsor, plan and contract hierarchies
# ---------------------------------------------------------------------------

def setup_plan_env(
    plan_type: str = "PLAN_403B",
    activate: bool = True,
    num_vendors: int = 1,
    clock: str = CLOCK_DEFAULT,
    employer_overrides: Optional[Dict] = None,
    plan_overrides: Optional[Dict] = None,
) -> dict:
    """Logical clock + one sponsor + N providers + one plan.

    Returns {"employer", "employer_id", "plan", "plan_id", "vendors",
    "vendor_ids", "vendor", "vendor_id"}.
    """
    set_clock(clock)
    employer = register_employer(**(employer_overrides or {}))
    vendors = []
    if num_vendors >= 1:
        vendors.append(register_vendor())
    if num_vendors >= 2:
        vendors.append(register_second_vendor())
    for extra in range(2, num_vendors):
        vendors.append(
            register_vendor(
                legal_name=f"Provider {extra + 1}",
                vendor_code=f"PRV{extra + 1}",
                contact_email=f"ops{extra + 1}@provider.example",
            )
        )
    overrides = {"plan_type": plan_type}
    overrides.update(plan_overrides or {})
    plan = create_plan(employer["id"], **overrides)
    if activate:
        plan = move_plan(plan["id"], employer["id"], "ACTIVE")
    env = {
        "employer": employer,
        "employer_id": employer["id"],
        "plan": plan,
        "plan_id": plan["id"],
        "vendors": vendors,
        "vendor_ids": [v["id"] for v in vendors],
    }
    if vendors:
        env["vendor"] = vendors[0]
        env["vendor_id"] = vendors[0]["id"]
    if len(vendors) >= 2:
        env["vendor_two"] = vendors[1]
        env["vendor_two_id"] = vendors[1]["id"]
    return env


def setup_participant_with_contract(
    env: dict,
    participant_overrides: Optional[Dict] = None,
    contract_overrides: Optional[Dict] = None,
    vendor_index: int = 0,
) -> dict:
    """Register one employee under the env's sponsor and open one contract.

    Adds "participant", "participant_id", "account", "account_id" to env and
    returns env.
    """
    participant = register_participant(env["employer_id"], **(participant_overrides or {}))
    account = open_contract(
        participant["id"],
        env["plan_id"],
        env["vendor_ids"][vendor_index],
        env["employer_id"],
        **(contract_overrides or {}),
    )
    env["participant"] = participant
    env["participant_id"] = participant["id"]
    env["account"] = account
    env["account_id"] = account["id"]
    return env


def setup_basic_403b(
    participant_overrides: Optional[Dict] = None,
    contract_overrides: Optional[Dict] = None,
    plan_overrides: Optional[Dict] = None,
    clock: str = CLOCK_DEFAULT,
) -> dict:
    """Sponsor + provider + ACTIVE 403(b) plan + employee + one contract."""
    env = setup_plan_env(
        plan_type="PLAN_403B", num_vendors=1, clock=clock, plan_overrides=plan_overrides
    )
    return setup_participant_with_contract(env, participant_overrides, contract_overrides)


def setup_403b_with_agreement(
    feed_date: Optional[str] = FRESH_FEED,
    agreement_overrides: Optional[Dict] = None,
    participant_overrides: Optional[Dict] = None,
    contract_overrides: Optional[Dict] = None,
    plan_overrides: Optional[Dict] = None,
) -> dict:
    """Basic 403(b) scenario whose single provider holds an ACTIVE agreement."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1, plan_overrides=plan_overrides)
    agreement = setup_active_agreement(
        env["plan_id"], env["vendor_id"], env["employer_id"], feed_date,
        **(agreement_overrides or {}),
    )
    env["agreement"] = agreement
    env["agreement_id"] = agreement["id"]
    return setup_participant_with_contract(env, participant_overrides, contract_overrides)


def setup_two_vendor_403b(
    feed_dates=(FRESH_FEED, FRESH_FEED),
    contract_one_overrides: Optional[Dict] = None,
    contract_two_overrides: Optional[Dict] = None,
    participant_overrides: Optional[Dict] = None,
    plan_overrides: Optional[Dict] = None,
) -> dict:
    """One ACTIVE 403(b) plan, two providers each with an ACTIVE agreement, one
    employee holding one contract at each provider."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2, plan_overrides=plan_overrides)
    env["agreement_one"] = setup_active_agreement(
        env["plan_id"], env["vendor_ids"][0], env["employer_id"], feed_dates[0]
    )
    env["agreement_two"] = setup_active_agreement(
        env["plan_id"], env["vendor_ids"][1], env["employer_id"], feed_dates[1]
    )
    env["agreement_one_id"] = env["agreement_one"]["id"]
    env["agreement_two_id"] = env["agreement_two"]["id"]
    participant = register_participant(env["employer_id"], **(participant_overrides or {}))
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        **(contract_one_overrides or {"contract_number": "NLA-0001",
                                      "accumulated_benefit_cents": 5_000_000}),
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        **(contract_two_overrides or {"contract_number": "CDR-0001",
                                      "accumulated_benefit_cents": 1_000_000}),
    )
    env["participant"] = participant
    env["participant_id"] = participant["id"]
    env["account_one"] = account_one
    env["account_one_id"] = account_one["id"]
    env["account_two"] = account_two
    env["account_two_id"] = account_two["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_election_ready(
    participant_overrides: Optional[Dict] = None,
    contract_overrides: Optional[Dict] = None,
    plan_overrides: Optional[Dict] = None,
    notice_overrides: Optional[Dict] = None,
    file_valid_notice: bool = True,
    determining_officer: str = OFFICER_ONE,
    run_determination: bool = True,
) -> dict:
    """ACTIVE 403(b) plan with a valid notice, one employee with one contract,
    and a live eligibility determination — everything an election approval
    needs except the election itself."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1, plan_overrides=plan_overrides)
    if file_valid_notice:
        env["notice"] = file_notice(
            env["plan_id"], env["employer_id"], **(notice_overrides or {})
        )
    env = setup_participant_with_contract(env, participant_overrides, contract_overrides)
    if run_determination:
        env["determination"] = determine_eligibility(
            env["plan_id"], env["participant_id"], determining_officer
        )
        env["determination_id"] = env["determination"]["id"]
    return env


def setup_effective_election(
    annual_deferral_amount_cents: int = 500_000,
    effective_from: str = "2026-01-01",
    effective_through: str = "2026-06-30",
    catchup_election: Optional[str] = None,
    participant_overrides: Optional[Dict] = None,
    contract_overrides: Optional[Dict] = None,
) -> dict:
    """setup_election_ready plus one election walked through to EFFECTIVE."""
    env = setup_election_ready(
        participant_overrides=participant_overrides, contract_overrides=contract_overrides
    )
    extras = {}
    if catchup_election is not None:
        extras["catchup_election"] = catchup_election
    election = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=annual_deferral_amount_cents,
        effective_from=effective_from,
        effective_through=effective_through,
        **extras,
    )
    env["election"] = approve_election(election["id"], OFFICER_TWO)
    env["election_id"] = election["id"]
    return env


def setup_request_under_review(
    request_type: str,
    plan_type: str = "PLAN_403B",
    request_overrides: Optional[Dict] = None,
    contract_overrides: Optional[Dict] = None,
    participant_overrides: Optional[Dict] = None,
    reviewing_officer: str = OFFICER_ONE,
    feed_date: Optional[str] = FRESH_FEED,
) -> dict:
    """ACTIVE plan with an ACTIVE, current agreement, one fully vested contract,
    and one participant request already moved to UNDER_REVIEW."""
    env = setup_plan_env(plan_type=plan_type, num_vendors=1)
    env["agreement"] = setup_active_agreement(
        env["plan_id"], env["vendor_id"], env["employer_id"], feed_date
    )
    env["agreement_id"] = env["agreement"]["id"]
    env = setup_participant_with_contract(
        env, participant_overrides, contract_overrides or {"accumulated_benefit_cents": 5_000_000}
    )
    request = submit_request(
        env["participant_id"], env["plan_id"], env["account_id"], request_type,
        **(request_overrides or {}),
    )
    env["request"] = begin_review(request["id"], reviewing_officer)
    env["request_id"] = request["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and deadline targeting
# ---------------------------------------------------------------------------

def setup_late_deposit(
    line_items: Optional[List[dict]] = None,
    deposit_clock: str = "2026-09-30T00:00:00Z",
    deposit_date: str = "2026-09-30",
    plan_overrides: Optional[Dict] = None,
    batch_overrides: Optional[Dict] = None,
    contract_overrides: Optional[Dict] = None,
) -> dict:
    """Large-plan batch withheld on 2026-07-15 and deposited late, so the plan
    carries one OPEN correction and reads UNDER_CORRECTION."""
    env = setup_basic_403b(
        contract_overrides=contract_overrides, plan_overrides=plan_overrides
    )
    items = line_items or [make_line_item(env["account_id"], 100_000)]
    env["batch"] = create_batch(
        env["plan_id"], env["employer_id"], items, **(batch_overrides or {})
    )
    env["batch_id"] = env["batch"]["id"]
    set_clock(deposit_clock)
    env["deposited_batch"] = deposit_batch(env["batch_id"], env["employer_id"], deposit_date)
    env["correction"] = first_correction(env["batch_id"])
    env["correction_id"] = env["correction"]["id"]
    return env


def setup_withheld_batch(
    line_items: Optional[List[dict]] = None,
    plan_overrides: Optional[Dict] = None,
    batch_overrides: Optional[Dict] = None,
) -> dict:
    """Large-plan batch in WITHHELD, ready for a deposit under test."""
    env = setup_basic_403b(plan_overrides=plan_overrides)
    items = line_items or [make_line_item(env["account_id"], 100_000)]
    env["batch"] = create_batch(
        env["plan_id"], env["employer_id"], items, **(batch_overrides or {})
    )
    env["batch_id"] = env["batch"]["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 5 — movement pipelines
# ---------------------------------------------------------------------------

def setup_accepted_exchange(
    amount_cents: int = 1_000_000,
    contract_one_overrides: Optional[Dict] = None,
    contract_two_overrides: Optional[Dict] = None,
    plan_overrides: Optional[Dict] = None,
) -> dict:
    """Two-provider 403(b) plan with a CONTRACT_EXCHANGE already accepted by the
    receiving provider."""
    env = setup_two_vendor_403b(
        contract_one_overrides=contract_one_overrides,
        contract_two_overrides=contract_two_overrides,
        plan_overrides=plan_overrides,
    )
    movement = submit_movement(
        env["participant_id"], "CONTRACT_EXCHANGE", env["plan_id"], env["plan_id"],
        env["account_one_id"], env["account_two_id"], amount_cents, env["employer_id"],
    )
    env["movement"] = vendor_respond(movement["id"], env["vendor_ids"][1], True)
    env["movement_id"] = movement["id"]
    return env


def setup_approved_exchange(
    amount_cents: int = 1_500_000,
    contract_one_overrides: Optional[Dict] = None,
    contract_two_overrides: Optional[Dict] = None,
) -> dict:
    """An accepted CONTRACT_EXCHANGE taken through compliance approval."""
    env = setup_accepted_exchange(
        amount_cents=amount_cents,
        contract_one_overrides=contract_one_overrides,
        contract_two_overrides=contract_two_overrides,
    )
    env["movement"] = decide_movement(env["movement_id"], "APPROVE", OFFICER_ONE)
    return env
