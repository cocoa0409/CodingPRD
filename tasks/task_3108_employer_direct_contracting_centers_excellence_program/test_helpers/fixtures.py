"""Composite setup helpers — multi-step scenario builders shared across tests.

Every fixture builds its preconditions from scratch through the public API and
uses get_success_data() internally so setup failures surface as clear
"Setup failed" messages rather than confusing assertion failures.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, QUIET_TAIL_DAYS, RATES
from .factories import (
    create_bundle_template_payload,
    create_care_item_payload,
    create_claim_payload,
    create_contract_payload,
    create_employer_payload,
    create_episode_payload,
    create_patient_payload,
    create_rate_book_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]
REVIEWER = TEST_USERS["physician_reviewer_headers"]
CLAIMS = TEST_USERS["claims_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: program configuration
# ---------------------------------------------------------------------------

def reset_clock(to_iso8601: str = CLOCK_START) -> None:
    """Pin the logical clock (PRD §2.7)."""
    get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def make_rate_book(rates: Optional[dict] = None) -> dict:
    reset_clock()
    payload = create_rate_book_payload()
    if rates is not None:
        payload["rates"] = rates
    return get_success_data(api_client.create_rate_book(payload, ADMIN))


def make_employer(rates: Optional[dict] = None, **employer_overrides) -> dict:
    """Rate book + employer. Returns the Employer."""
    rb = make_rate_book(rates)
    payload = create_employer_payload(rb["id"], **employer_overrides)
    return get_success_data(api_client.create_employer(payload, ADMIN))


def make_template(**overrides) -> dict:
    payload = create_bundle_template_payload(**overrides)
    return get_success_data(api_client.create_bundle_template(payload, ADMIN))


def make_contract(employer: dict, template: dict, **overrides) -> dict:
    """DRAFT contract (not activated)."""
    bundle_price = overrides.pop("bundle_price_cents", 3000000)
    payload = create_contract_payload(
        employer["id"], template["id"], bundle_price_cents=bundle_price, **overrides
    )
    return get_success_data(api_client.create_contract(payload, ADMIN))


def make_active_contract(employer: dict, template: dict, **overrides) -> dict:
    """DRAFT contract + activate. Returns the ACTIVE contract."""
    contract = make_contract(employer, template, **overrides)
    return get_success_data(api_client.activate_contract(contract["id"], ADMIN))


def make_patient(employer: dict, **overrides) -> dict:
    payload = create_patient_payload(employer["id"], **overrides)
    return get_success_data(api_client.create_patient(payload, COORD))


def setup_program(
    rates: Optional[dict] = None,
    template_overrides: Optional[dict] = None,
    contract_overrides: Optional[dict] = None,
    activate: bool = True,
) -> dict:
    """Rate book + employer + template + contract (ACTIVE unless activate=False).

    Returns {"rate_book", "employer", "template", "contract"}.
    """
    employer = make_employer(rates)
    template = make_template(**(template_overrides or {}))
    maker = make_active_contract if activate else make_contract
    contract = maker(employer, template, **(contract_overrides or {}))
    return {
        "rate_book_id": employer["baseline_rate_book"],
        "employer": employer,
        "template": template,
        "contract": contract,
    }


# ---------------------------------------------------------------------------
# Tier 1-3: episode lifecycle progression
# ---------------------------------------------------------------------------

def get_episode(episode_id: str) -> dict:
    """Re-read the episode (default employer view)."""
    return get_success_data(api_client.get_episode(episode_id, ADMIN))


def open_episode(patient: dict, contract: dict, **overrides) -> dict:
    """Intake: returns the INTAKE_PENDING episode."""
    payload = create_episode_payload(patient["id"], contract["id"], **overrides)
    return get_success_data(api_client.create_episode(payload, COORD))


def drive_episode_to_sor_pending(episode: dict) -> dict:
    """One CANDIDATE screening: INTAKE_PENDING -> SCREENING -> SOR_PENDING."""
    get_success_data(
        api_client.submit_screening(
            episode["id"], {"doc_type": "IMAGING", "result": "CANDIDATE"}, COORD
        )
    )
    return get_episode(episode["id"])


def approve_episode(episode: dict) -> dict:
    """Record SURGERY_INDICATED on an SOR_PENDING / SOR_REVIEW episode."""
    current = get_episode(episode["id"])
    get_success_data(
        api_client.record_review(
            current["id"],
            {
                "conclusion": "SURGERY_INDICATED",
                "expected_episode_version": current["version"],
            },
            REVIEWER,
        )
    )
    return get_episode(episode["id"])


def schedule_episode(episode: dict, requested_day_seq: Optional[int] = None) -> dict:
    """Schedule an APPROVED (or reschedule a SCHEDULING) episode."""
    current = get_episode(episode["id"])
    day = (
        requested_day_seq
        if requested_day_seq is not None
        else current["screen_seq"] + 1
    )
    get_success_data(
        api_client.schedule_episode(
            current["id"],
            {
                "requested_day_seq": day,
                "expected_episode_version": current["version"],
            },
            COORD,
        )
    )
    return get_episode(episode["id"])


def add_care_item(episode: dict, **overrides) -> dict:
    """Create a care plan item on the episode; returns the CarePlanItem."""
    payload = create_care_item_payload(**overrides)
    return get_success_data(
        api_client.create_care_item(episode["id"], payload, COORD)
    )


def drive_episode_to_pre_op(
    episode: dict, requested_day_seq: Optional[int] = None,
    first_item_overrides: Optional[dict] = None,
) -> dict:
    """APPROVED -> SCHEDULING -> PRE_OP (first PRE_OP care item)."""
    scheduled = schedule_episode(episode, requested_day_seq)
    add_care_item(scheduled, **(first_item_overrides or {}))
    return get_episode(episode["id"])


def complete_surgery(episode: dict) -> dict:
    current = get_episode(episode["id"])
    get_success_data(
        api_client.complete_surgery(
            current["id"],
            {"expected_episode_version": current["version"]},
            COORD,
        )
    )
    return get_episode(episode["id"])


def discharge_episode(episode: dict) -> dict:
    current = get_episode(episode["id"])
    get_success_data(
        api_client.discharge_episode(
            current["id"],
            {"expected_episode_version": current["version"]},
            COORD,
        )
    )
    return get_episode(episode["id"])


def advance_episode_days(episode_id: str, days: int) -> dict:
    """Advance the day counter `days` times; returns the latest episode read."""
    latest = None
    for _ in range(days):
        latest = get_success_data(api_client.advance_day(episode_id, COORD))
        if latest.get("status") in ("CLOSED", "AVOIDED", "CANCELLED"):
            break
    return get_episode(episode_id)


def drive_episode_to_post_op(episode: dict, requested_day_seq: int = 4) -> dict:
    """APPROVED -> ... -> POST_OP_TRACKING (warranty window open)."""
    pre_op = drive_episode_to_pre_op(episode, requested_day_seq)
    done = complete_surgery(pre_op)
    return discharge_episode(done)


def close_episode(episode: dict, max_days: int = 300) -> dict:
    """Advance days until the episode auto-closes at its closure horizon."""
    for _ in range(max_days):
        latest = get_success_data(api_client.advance_day(episode["id"], COORD))
        if latest.get("status") == "CLOSED":
            return latest
    raise AssertionError(
        f"Setup failed: episode {episode['id']} did not close within {max_days} days"
    )


def _iso(date: str, day: int) -> str:
    return f"{date[:8]}{day:02d}T00:00:00Z"


def setup_program_at(
    clock_iso: str = CLOCK_START,
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    rates: Optional[dict] = None,
    template_overrides: Optional[dict] = None,
    contract_overrides: Optional[dict] = None,
) -> dict:
    """Program stack with the logical clock pinned to an arbitrary instant and
    the contract coverage window containing that instant (defaulting to a
    month-long window). Returns {"employer", "template", "contract"}."""
    employer = make_employer(rates)  # make_rate_book resets the clock first
    template = make_template(**(template_overrides or {}))
    overrides = dict(contract_overrides or {})
    overrides.setdefault("effective_from", effective_from or clock_iso)
    overrides.setdefault("effective_to", effective_to or _iso(clock_iso, 28))
    contract = make_active_contract(employer, template, **overrides)
    get_success_data(api_client.set_clock({"to_iso8601": clock_iso}, ADMIN))
    return {
        "rate_book_id": employer["baseline_rate_book"],
        "employer": employer,
        "template": template,
        "contract": contract,
    }


def make_employer_and_contracts(
    windows, rates: Optional[dict] = None
) -> dict:
    """One employer + one template + one contract per window, all ACTIVE.

    windows: list of (effective_from, effective_to) ISO strings.
    Returns {"employer", "template", "contracts": [...]}.
    """
    employer = make_employer(rates)
    template = make_template()
    contracts = []
    for start, end in windows:
        contract = make_active_contract(
            employer, template, effective_from=start, effective_to=end
        )
        contracts.append(contract)
    return {"employer": employer, "template": template, "contracts": contracts}


def setup_episode_on_contract(
    contract: dict, employer: dict, clock_iso: Optional[str] = None
) -> dict:
    """Open + screen + approve one episode on the given (ACTIVE) contract.
    Returns the APPROVED episode."""
    if clock_iso is not None:
        get_success_data(api_client.set_clock({"to_iso8601": clock_iso}, ADMIN))
    patient = make_patient(employer)
    episode = open_episode(patient, contract)
    episode = drive_episode_to_sor_pending(episode)
    return approve_episode(episode)


def setup_episode_in_sor_pending(**program_overrides) -> dict:
    """Full stack through SOR_PENDING.

    Returns {"employer", "template", "contract", "patient", "episode"}.
    """
    prog = setup_program(**program_overrides)
    patient = make_patient(prog["employer"])
    episode = open_episode(patient, prog["contract"])
    episode = drive_episode_to_sor_pending(episode)
    return {**prog, "patient": patient, "episode": episode}


def setup_approved_episode(**program_overrides) -> dict:
    """Full stack through APPROVED."""
    ctx = setup_episode_in_sor_pending(**program_overrides)
    ctx["episode"] = approve_episode(ctx["episode"])
    return ctx


def setup_episode_in_post_op(
    requested_day_seq: int = 4, **program_overrides
) -> dict:
    """Full stack through POST_OP_TRACKING."""
    ctx = setup_approved_episode(**program_overrides)
    ctx["episode"] = drive_episode_to_post_op(
        ctx["episode"], requested_day_seq=requested_day_seq
    )
    return ctx


def setup_closed_episode(**program_overrides) -> dict:
    """Full stack through CLOSED (use a short warranty via template_overrides)."""
    overrides = dict(program_overrides)
    template_overrides = dict(overrides.pop("template_overrides", {}) or {})
    template_overrides.setdefault("warranty_days", 3)
    ctx = setup_episode_in_post_op(template_overrides=template_overrides, **overrides)
    ctx["episode"] = close_episode(ctx["episode"])
    return ctx


# ---------------------------------------------------------------------------
# Claims and benefits helpers
# ---------------------------------------------------------------------------

def submit_claim(
    episode: dict,
    claim_type: str,
    service_date_seq: int,
    billed_cents: int,
    **overrides,
) -> dict:
    """Submit a claim; returns the PENDING Claim."""
    current = get_episode(episode["id"])
    payload = create_claim_payload(
        claim_type,
        service_date_seq,
        billed_cents,
        expected_episode_version=current["version"],
        **overrides,
    )
    return get_success_data(api_client.submit_claim(current["id"], payload, CLAIMS))


def adjudicate(claim_id: str) -> dict:
    return get_success_data(api_client.adjudicate_claim(claim_id, CLAIMS))


def administer_benefit(episode: dict, kind: str, amount_cents: int, **overrides) -> dict:
    """Administer a travel/lodging benefit; returns the ADMINISTERED benefit."""
    current = get_episode(episode["id"])
    payload = {
        "kind": kind,
        "traveler": "PATIENT",
        "amount_cents": amount_cents,
        "expected_episode_version": current["version"],
    }
    payload.update(overrides)
    return get_success_data(
        api_client.administer_benefit(current["id"], payload, COORD)
    )
