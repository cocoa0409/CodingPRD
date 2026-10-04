"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use the lenient get_success_data validator so a setup
failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_rate_filing_payload,
    create_hospital_payload,
    create_policy_payload,
    create_claim_payload,
    create_medical_record_payload,
    treatment_line,
)
from .test_users import (
    TEST_USERS,
    make_hospital_staff_headers,
    make_pet_owner_headers,
    make_adjuster_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RATE_ADMIN = TEST_USERS["rate_filing_admin_headers"]
ADJ1 = TEST_USERS["adjuster_1_headers"]
ADJ2 = TEST_USERS["adjuster_2_headers"]

# Canonical clock instants reused across fixtures.
CLOCK_START = "2026-09-01T00:00:00Z"
CLOCK_PAST_WAITING = "2026-10-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: clock + filings
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def create_and_file_filing(**overrides):
    """Create a rate filing in DRAFT and file it with the regulator.
    Returns the FILED filing (becomes EFFECTIVE when the logical clock
    reaches filing_effective_date)."""
    resp = api_client.create_rate_filing(create_rate_filing_payload(**overrides), RATE_ADMIN)
    filing = get_success_data(resp)
    resp = api_client.file_rate_filing(filing["id"], RATE_ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: hospitals and policies
# ---------------------------------------------------------------------------

def create_active_hospital(**overrides):
    """Register a hospital, approve it (OCC), and complete training.
    Returns the ACTIVE hospital dict."""
    resp = api_client.create_hospital(create_hospital_payload(**overrides), ADMIN)
    hospital = get_success_data(resp)
    resp = api_client.approve_hospital(
        hospital["id"], {"expected_hospital_version": hospital["version"]}, ADMIN
    )
    hospital = get_success_data(resp)
    resp = api_client.training_complete(hospital["id"], make_hospital_staff_headers(hospital["id"]))
    return get_success_data(resp)


def create_policy(**overrides):
    """Enroll a policy. Assumes an EFFECTIVE filing exists for the
    (territory_code, species) pair at coverage_start."""
    resp = api_client.create_policy(create_policy_payload(**overrides), TEST_USERS["pet_owner_headers"])
    return get_success_data(resp)


def create_policy_past_waiting(**overrides):
    """Enroll a policy, then advance the clock past both waiting windows and
    read the policy back so its lazy enrollment_status evaluation lands on
    FULLY_ACTIVE. Returns the re-read policy."""
    policy = create_policy(**overrides)
    set_clock(CLOCK_PAST_WAITING)
    resp = api_client.get_policy(policy["id"], ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: claims through the adjudication lifecycle
# ---------------------------------------------------------------------------

def submit_claim(policy, hospital, **overrides):
    """Submit a claim at checkout as staff of the treating hospital.
    Returns the SUBMITTED claim."""
    payload = create_claim_payload(policy["id"], hospital["id"], **overrides)
    resp = api_client.create_claim(payload, make_hospital_staff_headers(hospital["id"]))
    return get_success_data(resp)


def adjudicate_claim(claim, adjuster_headers=ADJ1):
    """Adjudicate a claim with the OCC token from the claim snapshot given.
    Returns the ADJUDICATED claim."""
    resp = api_client.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, adjuster_headers
    )
    return get_success_data(resp)


def pay_claim(claim, hospital, idempotency_key, adjuster_headers=ADJ1):
    """Adjudicate (if still SUBMITTED) then checkout-pay.
    Returns (payment, paid_claim)."""
    if claim["status"] in ("SUBMITTED", "PREEXISTING_REVIEW"):
        claim = adjudicate_claim(claim, adjuster_headers)
    resp = api_client.checkout_pay(
        claim["id"], {"idempotency_key": idempotency_key},
        make_hospital_staff_headers(hospital["id"]),
    )
    payment = get_success_data(resp)
    resp = api_client.get_claim(claim["id"], adjuster_headers)
    return payment, get_success_data(resp)


def settle_claim(claim, advance_to="2026-10-04T00:00:00Z", reader_headers=ADJ1):
    """Advance the clock past the settlement delay and read the claim so the
    lazy PAID -> SETTLED evaluation fires. Returns the settled claim."""
    set_clock(advance_to)
    resp = api_client.get_claim(claim["id"], reader_headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: full environment bundles
# ---------------------------------------------------------------------------

def setup_active_environment(**policy_overrides):
    """The canonical environment: clock pinned at start, one filing FILED,
    one ACTIVE hospital, one policy, then clock advanced past both waiting
    windows. Returns (hospital, policy)."""
    set_clock(CLOCK_START)
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy_past_waiting(**policy_overrides)
    return hospital, policy


def setup_adjudicated_claim(lines=None, claim_type="INJURY", visit_date="2026-10-02",
                            **policy_overrides):
    """Environment + one claim adjudicated. Returns (hospital, policy, claim)."""
    hospital, policy = setup_active_environment(**policy_overrides)
    kwargs = {"claim_type": claim_type, "visit_date": visit_date}
    if lines is not None:
        kwargs["lines"] = lines
    claim = submit_claim(policy, hospital, **kwargs)
    claim = adjudicate_claim(claim)
    return hospital, policy, claim


def setup_paid_claim(idempotency_key="KPAY", lines=None, claim_type="INJURY",
                     **policy_overrides):
    """Environment + one claim adjudicated and paid.
    Returns (hospital, policy, claim, payment)."""
    hospital, policy, claim = setup_adjudicated_claim(
        lines=lines, claim_type=claim_type, **policy_overrides
    )
    payment, claim = pay_claim(claim, hospital, idempotency_key)
    return hospital, policy, claim, payment


def setup_settled_claim(idempotency_key="KPAY", settle_clock="2026-10-04T00:00:00Z",
                        **policy_overrides):
    """Environment + one claim paid and settled via clock advance.
    Returns (hospital, policy, claim, payment)."""
    hospital, policy, claim, payment = setup_paid_claim(
        idempotency_key=idempotency_key, **policy_overrides
    )
    claim = settle_claim(claim, advance_to=settle_clock)
    return hospital, policy, claim, payment


# ---------------------------------------------------------------------------
# Tier 5: appeals and denials
# ---------------------------------------------------------------------------

def setup_denied_claim_with_appeal(reason_code="COVERAGE_DENIAL",
                                   denial_reason="not covered",
                                   denying_adjuster=ADJ1,
                                   **policy_overrides):
    """Environment + claim denied by an adjuster + appeal opened by the owner.
    Returns (hospital, policy, claim, appeal)."""
    hospital, policy = setup_active_environment(**policy_overrides)
    claim = submit_claim(policy, hospital)
    resp = api_client.deny_claim(claim["id"], {"denial_reason": denial_reason}, denying_adjuster)
    claim = get_success_data(resp)
    resp = api_client.open_appeal(
        claim["id"], {"reason_code": reason_code}, make_pet_owner_headers(policy["id"])
    )
    appeal = get_success_data(resp)
    return hospital, policy, claim, appeal


def upload_medical_record(policy, hospital, **overrides):
    """Upload a medical record as staff of the producing hospital."""
    resp = api_client.create_medical_record(
        policy["id"], create_medical_record_payload(hospital["id"], **overrides),
        make_hospital_staff_headers(hospital["id"]),
    )
    return get_success_data(resp)


def find_condition(policy, condition_code, reader_headers=ADJ1):
    """Return the PolicyCondition of a policy with the given condition code."""
    resp = api_client.list_policy_conditions_of_policy(policy["id"], reader_headers)
    conditions = get_success_data(resp)
    for condition in conditions:
        if condition["condition_code"] == condition_code:
            return condition
    raise AssertionError(f"Setup failed: no condition {condition_code} on policy {policy['id']}")


def hospital_ledger(hospital_id):
    resp = api_client.get_hospital(hospital_id, ADMIN)
    return get_success_data(resp)["running_ledger_balance_cents"]
