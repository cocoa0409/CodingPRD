"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient `get_success_data` validator so a broken precondition surfaces as a
"Setup step failed" message rather than a confusing assertion.

Monetary values are integers in whole cents and rates are integer basis points
throughout (PRD §2.6).
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_DEFAULT, TEST_DEFAULTS, USER_IDS
from .factories import (
    advance_payload,
    air_payload,
    clock_payload,
    create_activity_signup_payload,
    create_award_tier_payload,
    create_deposit_milestone_payload,
    create_destination_payload,
    create_onsite_activity_payload,
    create_program_payload,
    create_qualifier_payload,
    create_registration_payload,
    create_supplier_contract_payload,
    create_tax_award_report_payload,
    gross_up_policy_payload,
    negotiate_payload,
    respond_payload,
)
from .test_users import (
    TEST_USERS,
    make_contract_approver_headers,
    make_participant_headers,
    make_sourcing_manager_headers,
    make_tax_officer_headers,
)

PD = TEST_USERS["program_director_headers"]
SM = TEST_USERS["sourcing_manager_headers"]
CA = TEST_USERS["contract_approver_headers"]
AN = TEST_USERS["sales_ops_analyst_headers"]
TD = TEST_USERS["travel_desk_headers"]
TAX = TEST_USERS["tax_officer_headers"]
TAX_ALT = TEST_USERS["tax_officer_alt_headers"]


# ─── Date helpers ────────────────────────────────────────────────────────────

def iso_instant(text: str) -> datetime:
    return datetime.strptime(text.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")


def instant_plus_days(text: str, days: int) -> str:
    dt = iso_instant(text) + timedelta(days=days)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def instant_plus_minutes(text: str, minutes: int) -> str:
    dt = iso_instant(text) + timedelta(minutes=minutes)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Tier 0: single-call primitives ──────────────────────────────────────────

def set_logical_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Drive the logical clock (PRD §2.5). Returns the {current_utc} body."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), headers or PD))


def reset_logical_clock() -> Dict[str, Any]:
    return set_logical_clock(LOGICAL_CLOCK_DEFAULT)


def create_program(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_program(create_program_payload(**overrides), PD))


def read_program(program_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_program(program_id, headers or PD))


def program_version(program_id: str) -> int:
    return read_program(program_id)["version"]


def create_award_tier(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_award_tier(create_award_tier_payload(program_id, **overrides), PD)
    )


def create_qualifier(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_qualifier(create_qualifier_payload(program_id, **overrides), AN)
    )


def review_qualifier(qualifier_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.review_qualifier(qualifier_id, AN))


def read_qualifier(qualifier_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_qualifier(qualifier_id, headers or AN))


def create_destination(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_destination(create_destination_payload(program_id, **overrides), SM)
    )


def inspect_destination(
    destination_id: str, inspection_score: int = None, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    score = TEST_DEFAULTS["INSPECTION_SCORE"] if inspection_score is None else inspection_score
    return get_success_data(
        api_client.site_inspect_destination(
            destination_id, {"inspection_score": score}, headers or SM
        )
    )


def shortlist_destination(destination_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.shortlist_destination(destination_id, SM))


def read_destination(destination_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_destination(destination_id, SM))


def create_contract(program_id: str, destination_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(program_id, destination_id, **overrides), SM
        )
    )


def propose_contract(contract_id: str, proposer_user_id: str = None, **terms: Any) -> Dict[str, Any]:
    headers = make_sourcing_manager_headers(proposer_user_id or USER_IDS["SOURCING_MANAGER"])
    return get_success_data(
        api_client.negotiate_contract(contract_id, negotiate_payload("PROPOSE", **terms), headers)
    )


def counter_contract(contract_id: str, counterer_user_id: str = None, **terms: Any) -> Dict[str, Any]:
    headers = make_contract_approver_headers(counterer_user_id or USER_IDS["CONTRACT_APPROVER_ALT"])
    return get_success_data(
        api_client.negotiate_contract(contract_id, negotiate_payload("COUNTER", **terms), headers)
    )


def execute_contract(contract_id: str, executor_user_id: str = None) -> Dict[str, Any]:
    headers = make_contract_approver_headers(executor_user_id or USER_IDS["CONTRACT_APPROVER"])
    return get_success_data(api_client.execute_contract(contract_id, headers))


def read_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_supplier_contract(contract_id, SM))


def read_exposure_projection(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_exposure_projection(contract_id, CA))


def create_milestone(contract_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_deposit_milestone(
            create_deposit_milestone_payload(contract_id, **overrides), SM
        )
    )


def pay_milestone(milestone_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.pay_deposit_milestone(milestone_id, CA))


def read_milestone(milestone_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_deposit_milestone(milestone_id, CA))


def advance_program(program_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.advance_program(program_id, advance_payload(to_status), PD)
    )


def lock_gross_up_policy(program_id: str, policy: str = "NONE") -> Dict[str, Any]:
    return get_success_data(
        api_client.set_gross_up_policy(program_id, gross_up_policy_payload(policy), PD)
    )


def notify_qualifiers(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.notify_qualifiers(program_id, PD))


def cancel_program(program_id: str, reason: str = "Client pulled the program") -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_program(program_id, {"cancellation_reason": reason}, PD)
    )


def create_registration(
    qualifier_id: str,
    program_id: str = None,
    expected_program_version: int = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a seat, reading the program's live `version` for the OCC guard."""
    if expected_program_version is None:
        if program_id is None:
            program_id = read_qualifier(qualifier_id)["program_id"]
        expected_program_version = program_version(program_id)
    payload = create_registration_payload(qualifier_id, expected_program_version, **overrides)
    return get_success_data(api_client.create_registration(payload, headers or TD))


def respond_registration(
    registration_id: str, qualifier_id: str, response: str = "ACCEPT", **fields: Any
) -> Dict[str, Any]:
    """Invitation response — reserved to the owning Participant."""
    return get_success_data(
        api_client.respond_registration(
            registration_id,
            respond_payload(response, **fields),
            make_participant_headers(qualifier_id),
        )
    )


def confirm_registration(registration_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.confirm_registration(registration_id, TD))


def cancel_registration(
    registration_id: str, reason: str = "Winner withdrew", headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_registration(
            registration_id, {"cancellation_reason": reason}, headers or TD
        )
    )


def air_action(registration_id: str, action: str, **fields: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.air_registration(registration_id, air_payload(action, **fields), TD)
    )


def survey_registration(registration_id: str, satisfaction_score: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.survey_registration(
            registration_id, {"satisfaction_score": satisfaction_score}, TD
        )
    )


def read_registration(registration_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_registration(registration_id, headers or TD))


def create_activity(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_onsite_activity(create_onsite_activity_payload(program_id, **overrides), TD)
    )


def read_activity(activity_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_onsite_activity(activity_id, TD))


def activity_version(activity_id: str) -> int:
    return read_activity(activity_id)["version"]


def close_activity(activity_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_onsite_activity(activity_id, TD))


def create_signup(
    activity_id: str,
    registration_id: str,
    expected_activity_version: int = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a signup, reading the activity's live `version` for the OCC guard."""
    if expected_activity_version is None:
        expected_activity_version = activity_version(activity_id)
    payload = create_activity_signup_payload(
        activity_id, registration_id, expected_activity_version
    )
    return get_success_data(api_client.create_activity_signup(payload, headers or TD))


def cancel_signup(signup_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_activity_signup(signup_id, headers or TD))


def read_signup(signup_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_activity_signup(signup_id, headers or TD))


def draft_tax_report(qualifier_id: str, tax_year: int = 2026) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(qualifier_id, tax_year), TAX
        )
    )


def file_tax_report(report_id: str, filer_user_id: str = None) -> Dict[str, Any]:
    headers = make_tax_officer_headers(filer_user_id or USER_IDS["TAX_OFFICER"])
    return get_success_data(api_client.file_tax_award_report(report_id, headers))


def void_tax_report(report_id: str, reason: str = "Filed against the wrong tax year",
                    voider_user_id: str = None) -> Dict[str, Any]:
    headers = make_tax_officer_headers(voider_user_id or USER_IDS["TAX_OFFICER_ALT"])
    return get_success_data(
        api_client.void_tax_award_report(report_id, {"void_reason": reason}, headers)
    )


def read_tax_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_tax_award_report(report_id, TAX))


def read_measurement(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_program_measurement(program_id, PD))


# ─── Tier 1: state progression ───────────────────────────────────────────────

def setup_program_with_tier(
    program_overrides: Optional[Dict[str, Any]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A DESIGN program plus one rung of the award tier ladder."""
    program = create_program(**(program_overrides or {}))
    tier = create_award_tier(program["id"], **(tier_overrides or {}))
    return {"program": program, "tier": tier, "tiers": [tier]}


def setup_program_with_tier_ladder(
    tier_specs: List[Dict[str, Any]],
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A DESIGN program plus one tier per entry of `tier_specs`."""
    program = create_program(**(program_overrides or {}))
    tiers = [create_award_tier(program["id"], **spec) for spec in tier_specs]
    return {"program": program, "tiers": tiers, "tier": tiers[0] if tiers else None}


def setup_inspected_destination(
    program_id: str,
    destination_overrides: Optional[Dict[str, Any]] = None,
    inspection_score: int = None,
) -> Dict[str, Any]:
    """A CANDIDATE destination with its site inspection recorded."""
    destination = create_destination(program_id, **(destination_overrides or {}))
    inspect_destination(destination["id"], inspection_score)
    return read_destination(destination["id"])


def setup_shortlisted_destination(
    program_id: str,
    destination_overrides: Optional[Dict[str, Any]] = None,
    inspection_score: int = None,
) -> Dict[str, Any]:
    """A destination walked CANDIDATE -> INSPECTED -> SHORTLISTED."""
    destination = setup_inspected_destination(
        program_id, destination_overrides, inspection_score
    )
    shortlist_destination(destination["id"])
    return read_destination(destination["id"])


def setup_sourcing_program(
    program_overrides: Optional[Dict[str, Any]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
    destination_overrides: Optional[Dict[str, Any]] = None,
    tier_specs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Program advanced DESIGN -> SOURCING: a tier ladder and a shortlisted
    destination both exist, which are the edge's structural prerequisites."""
    if tier_specs is not None:
        built = setup_program_with_tier_ladder(tier_specs, program_overrides)
    else:
        built = setup_program_with_tier(program_overrides, tier_overrides)
    program = built["program"]
    destination = setup_shortlisted_destination(program["id"], destination_overrides)
    advance_program(program["id"], "SOURCING")
    return {
        "program": read_program(program["id"]),
        "tier": built["tier"],
        "tiers": built["tiers"],
        "destination": destination,
    }


def setup_proposed_contract(
    program_overrides: Optional[Dict[str, Any]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
    destination_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    tier_specs: Optional[List[Dict[str, Any]]] = None,
    proposer_user_id: str = None,
) -> Dict[str, Any]:
    """SOURCING program with one contract walked DRAFT -> PROPOSED."""
    base = setup_sourcing_program(
        program_overrides, tier_overrides, destination_overrides, tier_specs
    )
    contract = create_contract(
        base["program"]["id"], base["destination"]["id"], **(contract_overrides or {})
    )
    propose_contract(contract["id"], proposer_user_id)
    base["contract"] = read_contract(contract["id"])
    return base


def setup_contracted_program(
    program_overrides: Optional[Dict[str, Any]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
    destination_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    tier_specs: Optional[List[Dict[str, Any]]] = None,
    proposer_user_id: str = None,
    executor_user_id: str = None,
) -> Dict[str, Any]:
    """Executed HOTEL contract: the destination is SELECTED, the program has
    moved SOURCING -> CONTRACTED and its per-person cost basis is stamped."""
    base = setup_proposed_contract(
        program_overrides, tier_overrides, destination_overrides,
        contract_overrides, tier_specs, proposer_user_id,
    )
    execute_contract(base["contract"]["id"], executor_user_id)
    base["program"] = read_program(base["program"]["id"])
    base["contract"] = read_contract(base["contract"]["id"])
    base["destination"] = read_destination(base["destination"]["id"])
    return base


# ─── Tier 2: entity hierarchy ────────────────────────────────────────────────

def setup_contract_with_schedule(
    milestone_specs: List[Dict[str, Any]],
    contract_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    destination_overrides: Optional[Dict[str, Any]] = None,
    execute: bool = True,
    pay_sequences: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """A contract plus its deposit schedule, optionally executed and part-paid.

    `milestone_specs` entries are payload overrides for POST /deposit-milestones
    (`sequence`, `due_at`, `amount_cents`, `refundable_bp`). `pay_sequences`
    names the sequences to pay once the contract is EXECUTED.
    """
    base = setup_proposed_contract(
        program_overrides=program_overrides,
        destination_overrides=destination_overrides,
        contract_overrides=contract_overrides,
    )
    contract_id = base["contract"]["id"]
    milestones = [create_milestone(contract_id, **spec) for spec in milestone_specs]
    if execute:
        execute_contract(contract_id)
    for sequence in pay_sequences or []:
        target = next(m for m in milestones if m["sequence"] == sequence)
        pay_milestone(target["id"])
    base["program"] = read_program(base["program"]["id"])
    base["contract"] = read_contract(contract_id)
    base["milestones"] = [read_milestone(m["id"]) for m in milestones]
    return base


def setup_qualified_qualifier(
    contracted: Optional[Dict[str, Any]] = None,
    qualifier_overrides: Optional[Dict[str, Any]] = None,
    **contracted_kwargs: Any,
) -> Dict[str, Any]:
    """A CONTRACTED program with one adjudicated (QUALIFIED) qualifier, so the
    award commitment is computed against a known per-person cost basis."""
    base = contracted or setup_contracted_program(**contracted_kwargs)
    qualifier = create_qualifier(base["program"]["id"], **(qualifier_overrides or {}))
    review_qualifier(qualifier["id"])
    base["qualifier"] = read_qualifier(qualifier["id"])
    base["qualifiers"] = [base["qualifier"]]
    base["program"] = read_program(base["program"]["id"])
    return base


def setup_registration_open_program(
    num_qualifiers: int = 1,
    qualifier_overrides: Optional[Dict[str, Any]] = None,
    qualifier_specs: Optional[List[Dict[str, Any]]] = None,
    gross_up_policy: str = "NONE",
    contracted: Optional[Dict[str, Any]] = None,
    **contracted_kwargs: Any,
) -> Dict[str, Any]:
    """Program walked all the way to REGISTRATION_OPEN with notified winners.

    Reaching REGISTRATION_OPEN needs every qualifier adjudicated and the
    gross-up policy locked, so this fixture reviews each qualifier, records the
    policy decision, runs the bulk notification and then advances.
    """
    base = contracted or setup_contracted_program(**contracted_kwargs)
    specs = qualifier_specs or [dict(qualifier_overrides or {}) for _ in range(num_qualifiers)]
    qualifiers = []
    for spec in specs:
        qualifier = create_qualifier(base["program"]["id"], **spec)
        review_qualifier(qualifier["id"])
        qualifiers.append(qualifier)
    lock_gross_up_policy(base["program"]["id"], gross_up_policy)
    notify_qualifiers(base["program"]["id"])
    advance_program(base["program"]["id"], "REGISTRATION_OPEN")
    base["qualifiers"] = [read_qualifier(q["id"]) for q in qualifiers]
    base["qualifier"] = base["qualifiers"][0] if base["qualifiers"] else None
    base["program"] = read_program(base["program"]["id"])
    return base


# ─── Tier 3: full lifecycle shortcuts ────────────────────────────────────────

def setup_invited_registration(
    registration_overrides: Optional[Dict[str, Any]] = None,
    **open_kwargs: Any,
) -> Dict[str, Any]:
    """REGISTRATION_OPEN program with one WINNER seat sitting at INVITED."""
    base = open_kwargs.pop("base", None) or setup_registration_open_program(**open_kwargs)
    registration = create_registration(
        base["qualifier"]["id"],
        program_id=base["program"]["id"],
        **(registration_overrides or {}),
    )
    base["registration"] = registration
    base["registrations"] = [registration]
    base["program"] = read_program(base["program"]["id"])
    return base


def setup_accepted_registration(
    waiver_signed: Optional[bool] = True,
    registration_overrides: Optional[Dict[str, Any]] = None,
    **open_kwargs: Any,
) -> Dict[str, Any]:
    """Seat walked INVITED -> ACCEPTED by its owning participant."""
    base = setup_invited_registration(
        registration_overrides=registration_overrides, **open_kwargs
    )
    fields = {} if waiver_signed is None else {"waiver_signed": waiver_signed}
    respond_registration(
        base["registration"]["id"], base["qualifier"]["id"], "ACCEPT", **fields
    )
    base["registration"] = read_registration(base["registration"]["id"])
    base["registrations"] = [base["registration"]]
    return base


def setup_confirmed_registration(
    waiver_signed: Optional[bool] = True,
    registration_overrides: Optional[Dict[str, Any]] = None,
    **open_kwargs: Any,
) -> Dict[str, Any]:
    """Seat walked INVITED -> ACCEPTED -> CONFIRMED, so it now consumes
    room-nights on the executed hotel contract and budget on the program."""
    base = setup_accepted_registration(
        waiver_signed=waiver_signed, registration_overrides=registration_overrides, **open_kwargs
    )
    confirm_registration(base["registration"]["id"])
    base["registration"] = read_registration(base["registration"]["id"])
    base["registrations"] = [base["registration"]]
    base["program"] = read_program(base["program"]["id"])
    base["contract"] = read_contract(base["contract"]["id"])
    base["qualifier"] = read_qualifier(base["qualifier"]["id"])
    return base


def enrol_and_confirm(
    base: Dict[str, Any],
    qualifier: Dict[str, Any],
    registration_overrides: Optional[Dict[str, Any]] = None,
    waiver_signed: bool = True,
    confirm: bool = True,
) -> Dict[str, Any]:
    """Enrol an already-NOTIFIED qualifier and walk the seat to CONFIRMED."""
    registration = create_registration(
        qualifier["id"], program_id=base["program"]["id"], **(registration_overrides or {})
    )
    respond_registration(
        registration["id"], qualifier["id"], "ACCEPT", waiver_signed=waiver_signed
    )
    if confirm:
        confirm_registration(registration["id"])
    return read_registration(registration["id"])


# ─── Tier 4: on-site agenda, capacity and waitlist targeting ─────────────────

def setup_onsite_program(
    num_qualifiers: int = 1,
    registration_overrides: Optional[Dict[str, Any]] = None,
    waiver_signed: bool = True,
    qualifier_specs: Optional[List[Dict[str, Any]]] = None,
    **open_kwargs: Any,
) -> Dict[str, Any]:
    """Program advanced REGISTRATION_OPEN -> ONSITE with every winner CONFIRMED.

    The advance needs at least one CONFIRMED registration, so every qualifier is
    enrolled and confirmed first. Seats are staggered across the stay window so
    they never contend for the same room-night unless a test asks them to.
    """
    base = setup_registration_open_program(
        num_qualifiers=num_qualifiers, qualifier_specs=qualifier_specs, **open_kwargs
    )
    registrations = []
    for qualifier in base["qualifiers"]:
        registrations.append(
            enrol_and_confirm(
                base, qualifier,
                registration_overrides=registration_overrides,
                waiver_signed=waiver_signed,
            )
        )
    advance_program(base["program"]["id"], "ONSITE")
    base["registrations"] = [read_registration(r["id"]) for r in registrations]
    base["registration"] = base["registrations"][0] if base["registrations"] else None
    base["program"] = read_program(base["program"]["id"])
    base["contract"] = read_contract(base["contract"]["id"])
    base["qualifiers"] = [read_qualifier(q["id"]) for q in base["qualifiers"]]
    base["qualifier"] = base["qualifiers"][0] if base["qualifiers"] else None
    return base


def setup_onsite_with_activity(
    activity_overrides: Optional[Dict[str, Any]] = None,
    num_qualifiers: int = 1,
    waiver_signed: bool = True,
    **onsite_kwargs: Any,
) -> Dict[str, Any]:
    """ONSITE program with one OPEN activity published and no signups yet."""
    base = onsite_kwargs.pop("base", None) or setup_onsite_program(
        num_qualifiers=num_qualifiers, waiver_signed=waiver_signed, **onsite_kwargs
    )
    activity = create_activity(base["program"]["id"], **(activity_overrides or {}))
    base["activity"] = activity
    base["activities"] = [activity]
    return base


def setup_activity_with_booked_and_waitlist(
    capacity: int = 1,
    num_qualifiers: int = 3,
    activity_overrides: Optional[Dict[str, Any]] = None,
    **onsite_kwargs: Any,
) -> Dict[str, Any]:
    """An activity whose seats are exhausted and whose waitlist is populated.

    Signups are created one at a time, each reading the activity's live version
    for the OCC guard, so admission follows the strict booked_count < capacity
    comparison: the first `capacity` signups land BOOKED and the rest WAITLISTED.
    """
    specs = [
        {"employee_code": f"WL-{index:03d}", "full_name": f"Waitlist Winner {index}"}
        for index in range(1, num_qualifiers + 1)
    ]
    overrides = dict(activity_overrides or {})
    overrides.setdefault("capacity", capacity)
    base = setup_onsite_with_activity(
        activity_overrides=overrides, qualifier_specs=specs, **onsite_kwargs
    )
    signups = []
    for registration in base["registrations"]:
        signups.append(create_signup(base["activity"]["id"], registration["id"]))
    base["signups"] = [read_signup(s["id"]) for s in signups]
    base["activity"] = read_activity(base["activity"]["id"])
    return base


# ─── Tier 5: reconciliation, measurement and taxable reporting ───────────────

def setup_reconciled_program(
    num_qualifiers: int = 1,
    survey_scores: Optional[List[int]] = None,
    gross_up_policy: str = "NONE",
    onsite: Optional[Dict[str, Any]] = None,
    **onsite_kwargs: Any,
) -> Dict[str, Any]:
    """Program advanced ONSITE -> RECONCILED: the travelling cohort is settled,
    every winner is TRAVELLED and each taxable award is stamped.

    Any surveys must be recorded before the advance so the satisfaction index is
    stamped from them.
    """
    base = onsite or setup_onsite_program(
        num_qualifiers=num_qualifiers, gross_up_policy=gross_up_policy, **onsite_kwargs
    )
    for index, score in enumerate(survey_scores or []):
        survey_registration(base["registrations"][index]["id"], score)
    for activity in base.get("activities", []):
        if read_activity(activity["id"])["status"] == "OPEN":
            close_activity(activity["id"])
    advance_program(base["program"]["id"], "RECONCILED")
    base["program"] = read_program(base["program"]["id"])
    base["qualifiers"] = [read_qualifier(q["id"]) for q in base["qualifiers"]]
    base["qualifier"] = base["qualifiers"][0] if base["qualifiers"] else None
    base["registrations"] = [read_registration(r["id"]) for r in base["registrations"]]
    base["registration"] = base["registrations"][0] if base["registrations"] else None
    return base


def setup_drafted_tax_report(
    gross_up_policy: str = "NONE",
    tax_year: int = None,
    reconciled: Optional[Dict[str, Any]] = None,
    **reconciled_kwargs: Any,
) -> Dict[str, Any]:
    """A RECONCILED program whose first travelled winner has a DRAFT report."""
    base = reconciled or setup_reconciled_program(
        gross_up_policy=gross_up_policy, **reconciled_kwargs
    )
    year = base["program"]["fiscal_year"] if tax_year is None else tax_year
    report = draft_tax_report(base["qualifier"]["id"], year)
    base["report"] = report
    base["reports"] = [report]
    return base


def setup_filed_tax_report(
    gross_up_policy: str = "NONE",
    filer_user_id: str = None,
    reconciled: Optional[Dict[str, Any]] = None,
    **reconciled_kwargs: Any,
) -> Dict[str, Any]:
    """A report walked DRAFT -> FILED, with the winner's tax dimension REPORTED
    and the program's reported total grown by the report's reported value."""
    base = setup_drafted_tax_report(
        gross_up_policy=gross_up_policy, reconciled=reconciled, **reconciled_kwargs
    )
    file_tax_report(base["report"]["id"], filer_user_id)
    base["report"] = read_tax_report(base["report"]["id"])
    base["reports"] = [base["report"]]
    base["program"] = read_program(base["program"]["id"])
    base["qualifier"] = read_qualifier(base["qualifier"]["id"])
    return base


def setup_closed_program(
    gross_up_policy: str = "NONE",
    **reconciled_kwargs: Any,
) -> Dict[str, Any]:
    """A program advanced RECONCILED -> CLOSED, which requires every taxable
    award to have been reported."""
    base = setup_filed_tax_report(gross_up_policy=gross_up_policy, **reconciled_kwargs)
    advance_program(base["program"]["id"], "CLOSED")
    base["program"] = read_program(base["program"]["id"])
    return base
