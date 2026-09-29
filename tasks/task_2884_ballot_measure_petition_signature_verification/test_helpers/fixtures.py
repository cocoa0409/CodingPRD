"""Composite setup helpers.

Every helper builds its preconditions from scratch through published
endpoints, because each test starts against an empty database. Setup calls use
the lenient success validator so a broken precondition surfaces as a clear
setup failure rather than as a confusing assertion.

Identity threading: after a helper creates a County or a Circulator, any call
whose authorisation depends on owning that resource uses
``make_county_clerk_headers(county["id"])`` or
``make_circulator_agent_headers(circulator["id"])`` — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_instant, plus_days
from .constants import CLOCK_EPOCH
from .factories import (
    add_signature_payload,
    adjudicate_payload,
    affidavit_payload,
    clock_payload,
    create_assignment_payload,
    create_batch_payload,
    create_challenge_payload,
    create_circulator_payload,
    create_county_payload,
    create_fraud_referral_payload,
    create_petition_payload,
    create_round_payload,
    create_verification_standard_payload,
    create_voter_record_payload,
    determination_payload,
    escalate_challenge_payload,
    format_decision_payload,
    invalidate_batch_payload,
    paid_disclosure_payload,
    registration_status_payload,
    rule_payload,
    title_summary_payload,
    training_payload,
    verify_affidavit_payload,
    void_round_payload,
)
from .test_users import (
    ADMIN_USER_ID,
    CHALLENGER_USER_ID,
    EXAMINER_USER_ID,
    PROPONENT_USER_ID,
    TITLE_USER_ID,
    make_challenger_headers,
    make_circulator_agent_headers,
    make_county_clerk_headers,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    make_title_examiner_headers,
)

DEFAULT_SIGNED_ON = "2026-08-05T00:00:00Z"


# =========================================================================
# Primitives
# =========================================================================

def set_clock(current_utc, admin_user_id=ADMIN_USER_ID):
    """Move the server logical clock. Before the first call it reads exactly
    2026-08-01T00:00:00Z."""
    return get_success_data(
        api_client.set_clock(
            clock_payload(current_utc), make_sos_admin_headers(admin_user_id)
        )
    )


def register_standard(**overrides):
    return get_success_data(
        api_client.create_verification_standard(
            create_verification_standard_payload(**overrides), make_sos_admin_headers()
        )
    )


def register_county(county_code="ALPHA", registered_voter_count=20, name=None):
    return get_success_data(
        api_client.create_county(
            create_county_payload(
                county_code=county_code,
                registered_voter_count=registered_voter_count,
                name=name or f"{county_code.title()} County",
            ),
            make_sos_admin_headers(),
        )
    )


def add_voter(
    county_id,
    voter_id_number="VA1",
    signature_on_file_hash=None,
    registration_status=None,
    full_name=None,
    registration_date="2020-01-01T00:00:00Z",
):
    extra = {}
    if registration_status is not None:
        extra["registration_status"] = registration_status
    return get_success_data(
        api_client.create_voter_record(
            create_voter_record_payload(
                county_id,
                voter_id_number=voter_id_number,
                signature_on_file_hash=signature_on_file_hash or f"H-{voter_id_number}",
                full_name=full_name or f"Voter {voter_id_number}",
                registration_date=registration_date,
                **extra,
            ),
            make_sos_admin_headers(),
        )
    )


def move_voter_registration(voter_record_id, registration_status):
    return get_success_data(
        api_client.set_voter_registration_status(
            voter_record_id,
            registration_status_payload(registration_status),
            make_sos_admin_headers(),
        )
    )


def file_petition(
    standard_id,
    proponent_user_id=PROPONENT_USER_ID,
    measure_subject_codes=("TAX",),
    **overrides,
):
    return get_success_data(
        api_client.create_petition(
            create_petition_payload(
                standard_id,
                measure_subject_codes=list(measure_subject_codes),
                **overrides,
            ),
            make_proponent_headers(proponent_user_id),
        )
    )


def read_petition(petition_id, headers=None):
    return get_success_data(
        api_client.get_petition(petition_id, headers or make_examiner_headers())
    )


def read_batch(batch_id, headers=None):
    return get_success_data(
        api_client.get_signature_batch(batch_id, headers or make_examiner_headers())
    )


def read_line(record_id, headers=None):
    return get_success_data(
        api_client.get_signature_record(record_id, headers or make_examiner_headers())
    )


def read_circulator(circulator_id, headers=None):
    return get_success_data(
        api_client.get_circulator(circulator_id, headers or make_examiner_headers())
    )


def read_round(round_id, headers=None):
    return get_success_data(
        api_client.get_verification_round(round_id, headers or make_examiner_headers())
    )


def read_cure_period(cure_period_id, headers=None):
    return get_success_data(
        api_client.get_cure_period(cure_period_id, headers or make_examiner_headers())
    )


def read_challenge(challenge_id, headers=None):
    return get_success_data(
        api_client.get_challenge(challenge_id, headers or make_examiner_headers())
    )


def read_referral(referral_id, headers=None):
    return get_success_data(
        api_client.get_fraud_referral(referral_id, headers or make_examiner_headers())
    )


def read_assignment(assignment_id, headers=None):
    return get_success_data(
        api_client.get_circulation_assignment(
            assignment_id, headers or make_examiner_headers()
        )
    )


def submit_petition(petition_id, proponent_user_id=PROPONENT_USER_ID):
    return get_success_data(
        api_client.submit_petition(petition_id, make_proponent_headers(proponent_user_id))
    )


def decide_format(petition_id, decision="APPROVE", examiner_id=EXAMINER_USER_ID):
    return get_success_data(
        api_client.format_decision(
            petition_id,
            format_decision_payload(decision),
            make_examiner_headers(examiner_id),
        )
    )


def prepare_title_summary(
    petition_id,
    official_title="The Official Act",
    official_summary="An official summary of the measure.",
    title_user_id=TITLE_USER_ID,
):
    """Reads the petition first so the version echo the write requires is
    current."""
    current = read_petition(petition_id)
    return get_success_data(
        api_client.put_title_summary(
            petition_id,
            title_summary_payload(
                current["version"],
                official_title=official_title,
                official_summary=official_summary,
            ),
            make_title_examiner_headers(title_user_id),
        )
    )


def clear_for_circulation(petition_id):
    return get_success_data(
        api_client.clear_for_circulation(petition_id, make_sos_admin_headers())
    )


def create_cleared_petition(
    standard_id,
    proponent_user_id=PROPONENT_USER_ID,
    measure_subject_codes=("TAX",),
    prepare_title=True,
    **overrides,
):
    """File a petition and walk it DRAFT -> FORMAT_REVIEW -> TITLE_PENDING ->
    CLEARED. Returns the cleared petition."""
    petition = file_petition(
        standard_id,
        proponent_user_id=proponent_user_id,
        measure_subject_codes=measure_subject_codes,
        **overrides,
    )
    submit_petition(petition["id"], proponent_user_id)
    decide_format(petition["id"], "APPROVE")
    if prepare_title:
        prepare_title_summary(petition["id"])
    return clear_for_circulation(petition["id"])


def register_circulator(full_name="Cora Carter", **overrides):
    return get_success_data(
        api_client.create_circulator(
            create_circulator_payload(full_name=full_name, **overrides),
            make_sos_admin_headers(),
        )
    )


def record_training(circulator_id, training_course_code="SOS-CIRC-101"):
    return get_success_data(
        api_client.record_training(
            circulator_id,
            training_payload(training_course_code),
            make_sos_admin_headers(),
        )
    )


def file_paid_disclosure(circulator_id, disclosure_document_id="DISC-1", employer_name=None):
    extra = {}
    if employer_name is not None:
        extra["employer_name"] = employer_name
    return get_success_data(
        api_client.file_paid_disclosure(
            circulator_id,
            paid_disclosure_payload(disclosure_document_id, **extra),
            make_sos_admin_headers(),
        )
    )


def file_circulator_affidavit(circulator_id, sworn=True):
    return get_success_data(
        api_client.file_affidavit(
            circulator_id, affidavit_payload(sworn), make_sos_admin_headers()
        )
    )


def create_registered_circulator(full_name="Cora Carter", is_paid=False, **overrides):
    """Register a circulator and walk it PENDING_TRAINING -> TRAINED ->
    REGISTERED, filing a paid disclosure first when it is compensated."""
    payload_overrides = dict(overrides)
    if is_paid:
        payload_overrides["is_paid"] = True
        payload_overrides.setdefault("employer_name", "Signatures Inc")
    circulator = register_circulator(full_name=full_name, **payload_overrides)
    record_training(circulator["id"])
    if is_paid:
        file_paid_disclosure(circulator["id"])
    return file_circulator_affidavit(circulator["id"])


def create_assignment(
    petition_id,
    circulator_id,
    assigned_county_codes=("ALPHA",),
    effective_from="2026-08-01T00:00:00Z",
    effective_to="2026-08-31T00:00:00Z",
    actor_headers=None,
    **overrides,
):
    """Re-reads the circulator so the version echo the create requires is
    current — a successful create increments that version by one."""
    circulator = read_circulator(circulator_id)
    return get_success_data(
        api_client.create_circulation_assignment(
            create_assignment_payload(
                petition_id,
                circulator_id,
                circulator["version"],
                assigned_county_codes=list(assigned_county_codes),
                effective_from=effective_from,
                effective_to=effective_to,
                **overrides,
            ),
            actor_headers or make_sos_admin_headers(),
        )
    )


def terminate_assignment(assignment_id, reason="No longer needed"):
    return get_success_data(
        api_client.terminate_assignment(
            assignment_id, make_sos_admin_headers(), {"reason": reason}
        )
    )


def file_batch(
    petition_id,
    circulator_id,
    county_id,
    is_supplemental=None,
    cure_period_id=None,
    actor="proponent",
    proponent_user_id=PROPONENT_USER_ID,
    **overrides,
):
    extra = dict(overrides)
    if is_supplemental is not None:
        extra["is_supplemental"] = is_supplemental
    if cure_period_id is not None:
        extra["cure_period_id"] = cure_period_id
    headers = (
        make_proponent_headers(proponent_user_id)
        if actor == "proponent"
        else make_circulator_agent_headers(circulator_id)
    )
    return get_success_data(
        api_client.create_signature_batch(
            create_batch_payload(petition_id, circulator_id, county_id, **extra),
            headers,
        )
    )


def add_line(
    batch_id,
    line_number=1,
    claimed_voter_id_number="VA1",
    signed_on=DEFAULT_SIGNED_ON,
    signature_hash=None,
    signer_name=None,
    proponent_user_id=PROPONENT_USER_ID,
):
    return get_success_data(
        api_client.add_signature(
            batch_id,
            add_signature_payload(
                line_number=line_number,
                claimed_voter_id_number=claimed_voter_id_number,
                signed_on=signed_on,
                signature_hash=(
                    signature_hash
                    if signature_hash is not None
                    else f"H-{claimed_voter_id_number}"
                ),
                signer_name=signer_name or f"Signer {claimed_voter_id_number}",
            ),
            make_proponent_headers(proponent_user_id),
        )
    )


def verify_batch_affidavit(
    batch_id,
    county_id,
    format_defect_line_numbers=None,
    affidavit_notary_id="NOT-1",
):
    extra = {}
    if format_defect_line_numbers is not None:
        extra["format_defect_line_numbers"] = list(format_defect_line_numbers)
    return get_success_data(
        api_client.verify_affidavit(
            batch_id,
            verify_affidavit_payload(affidavit_notary_id, **extra),
            make_county_clerk_headers(county_id),
        )
    )


def close_circulation(petition_id, proponent_user_id=PROPONENT_USER_ID):
    return get_success_data(
        api_client.file_signatures(petition_id, make_proponent_headers(proponent_user_id))
    )


def open_round(
    petition_id,
    round_type="RANDOM_SAMPLE",
    cure_period_id=None,
    examiner_id=EXAMINER_USER_ID,
):
    extra = {}
    if cure_period_id is not None:
        extra["cure_period_id"] = cure_period_id
    return get_success_data(
        api_client.create_verification_round(
            petition_id,
            create_round_payload(round_type, **extra),
            make_examiner_headers(examiner_id),
        )
    )


def validate_line(record_id, county_id, manual_match_override=None):
    payload = {}
    if manual_match_override is not None:
        payload["manual_match_override"] = manual_match_override
    return get_success_data(
        api_client.validate_signature_record(
            record_id, make_county_clerk_headers(county_id), payload
        )
    )


def tally_round(round_id, examiner_id=EXAMINER_USER_ID):
    return get_success_data(
        api_client.tally_round(round_id, make_examiner_headers(examiner_id))
    )


def void_round(round_id, voided_reason="Examination error"):
    return get_success_data(
        api_client.void_round(
            round_id, void_round_payload(voided_reason), make_sos_admin_headers()
        )
    )


def open_cure_period(petition_id):
    return get_success_data(
        api_client.create_cure_period(petition_id, make_sos_admin_headers())
    )


def expire_cure_period(cure_period_id):
    return get_success_data(
        api_client.expire_cure_period(cure_period_id, make_sos_admin_headers())
    )


def invalidate_batch(batch_id, invalidation_reason="Struck on review"):
    return get_success_data(
        api_client.invalidate_batch(
            batch_id, invalidate_batch_payload(invalidation_reason), make_sos_admin_headers()
        )
    )


def reinstate_batch(batch_id, invalidation_reason=None):
    payload = {}
    if invalidation_reason is not None:
        payload["invalidation_reason"] = invalidation_reason
    return get_success_data(
        api_client.reinstate_batch(batch_id, make_sos_admin_headers(), payload)
    )


def suspend_circulator(circulator_id, reason="Discretionary suspension"):
    return get_success_data(
        api_client.suspend_circulator(
            circulator_id, make_sos_admin_headers(), {"reason": reason}
        )
    )


def reinstate_circulator(circulator_id):
    return get_success_data(
        api_client.reinstate_circulator(circulator_id, make_sos_admin_headers())
    )


def revoke_circulator(circulator_id, reason="Revoked for cause"):
    return get_success_data(
        api_client.revoke_circulator(
            circulator_id, make_sos_admin_headers(), {"reason": reason}
        )
    )


def file_challenge(petition_id, challenger_user_id=CHALLENGER_USER_ID, **overrides):
    return get_success_data(
        api_client.create_challenge(
            petition_id,
            create_challenge_payload(**overrides),
            make_challenger_headers(challenger_user_id),
        )
    )


def escalate_challenge(
    challenge_id, challenger_user_id=CHALLENGER_USER_ID, court_docket_number="DOCKET-1"
):
    return get_success_data(
        api_client.escalate_challenge(
            challenge_id,
            escalate_challenge_payload(court_docket_number),
            make_challenger_headers(challenger_user_id),
        )
    )


def rule_on_challenge(challenge_id, ruling="AFFIRM"):
    return get_success_data(
        api_client.rule_on_challenge(
            challenge_id, rule_payload(ruling), make_sos_admin_headers()
        )
    )


def dismiss_challenge(challenge_id, reason="Administratively dismissed"):
    return get_success_data(
        api_client.dismiss_challenge(
            challenge_id, make_sos_admin_headers(), {"reason": reason}
        )
    )


def open_referral(
    petition_id,
    circulator_id,
    batch_id=None,
    referral_type="FORGED_SIGNATURES",
    opener_headers=None,
    opened_by=EXAMINER_USER_ID,
):
    extra = {"referral_type": referral_type}
    if batch_id is not None:
        extra["batch_id"] = batch_id
    return get_success_data(
        api_client.create_fraud_referral(
            create_fraud_referral_payload(petition_id, circulator_id, **extra),
            opener_headers or make_examiner_headers(opened_by),
        )
    )


def refer_referral_to_ag(referral_id, examiner_id=EXAMINER_USER_ID):
    return get_success_data(
        api_client.refer_to_ag(referral_id, make_examiner_headers(examiner_id))
    )


def adjudicate_referral(referral_id, finding="SUBSTANTIATED", adjudicator_headers=None):
    return get_success_data(
        api_client.adjudicate_referral(
            referral_id,
            adjudicate_payload(finding),
            adjudicator_headers or make_sos_admin_headers(),
        )
    )


def issue_determination(petition_id, determination="CERTIFY", actor_headers=None):
    return get_success_data(
        api_client.issue_determination(
            petition_id,
            determination_payload(determination),
            actor_headers or make_sos_admin_headers(),
        )
    )


# =========================================================================
# Composite builders
# =========================================================================
#
# The composites return a mutable "world" dict so a test can keep drilling
# deeper from wherever the helper stopped:
#
#   world["standard"]                 the VerificationStandard
#   world["counties"][county_code]    County keyed by its code
#   world["voters"][voter_id_number]  VoterRecord keyed by its voter id number
#   world["petition"]                 the Petition
#   world["circulators"][key]         Circulator keyed by a caller label
#   world["assignments"][key]         CirculationAssignment for that circulator
#   world["batches"][key]             {"batch", "lines", "county"} per batch
#   world["round"]                    the most recent VerificationRound

def setup_program(standard_overrides=None, counties=None, voters=None):
    """Register a standard, its counties and their voter rolls.

    ``counties`` accepts codes, ``(code, registered_voter_count)`` pairs, or
    dicts. ``voters`` accepts dicts keyed on ``voter_id_number`` with an
    optional ``county_code``, ``signature_on_file_hash`` and
    ``registration_status``.
    """
    standard = register_standard(**(standard_overrides or {}))
    specs = counties if counties is not None else [{"county_code": "ALPHA"}]
    built_counties = {}
    for spec in specs:
        if isinstance(spec, str):
            spec = {"county_code": spec}
        elif isinstance(spec, (tuple, list)):
            spec = {"county_code": spec[0], "registered_voter_count": spec[1]}
        code = spec["county_code"]
        built_counties[code] = register_county(
            county_code=code,
            registered_voter_count=spec.get("registered_voter_count", 20),
            name=spec.get("name"),
        )
    world = {
        "standard": standard,
        "counties": built_counties,
        "voters": {},
        "circulators": {},
        "assignments": {},
        "batches": {},
        "proponent_user_id": PROPONENT_USER_ID,
    }
    add_voters(world, voters or [])
    return world


def add_voters(world, voters):
    """Add voter rolls to an existing world."""
    default_code = next(iter(world["counties"]))
    for spec in voters:
        if isinstance(spec, str):
            spec = {"voter_id_number": spec}
        code = spec.get("county_code", default_code)
        record = add_voter(
            world["counties"][code]["id"],
            voter_id_number=spec["voter_id_number"],
            signature_on_file_hash=spec.get("signature_on_file_hash"),
            registration_status=spec.get("registration_status"),
            full_name=spec.get("full_name"),
        )
        world["voters"][spec["voter_id_number"]] = record
    return world["voters"]


def add_circulator(
    world,
    key="c2",
    full_name=None,
    is_paid=False,
    assign=True,
    assigned_county_codes=None,
    effective_from=CLOCK_EPOCH,
    effective_to="2026-08-31T00:00:00Z",
    **overrides,
):
    """Register one more circulator into an existing world, optionally
    assigning it to the world's petition."""
    circulator = create_registered_circulator(
        full_name=full_name or f"Circulator {key.upper()}",
        is_paid=is_paid,
        **overrides,
    )
    world["circulators"][key] = circulator
    if assign:
        codes = list(assigned_county_codes or world["counties"].keys())
        world["assignments"][key] = create_assignment(
            world["petition"]["id"],
            circulator["id"],
            assigned_county_codes=codes,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        world["circulators"][key] = read_circulator(circulator["id"])
    return world["circulators"][key]


def setup_circulation_ready(
    standard_overrides=None,
    counties=None,
    voters=None,
    measure_subject_codes=("TAX",),
    proponent_user_id=PROPONENT_USER_ID,
    assigned_county_codes=None,
    effective_from=CLOCK_EPOCH,
    effective_to="2026-08-31T00:00:00Z",
    circulator_overrides=None,
    circulator_key="c1",
    circulator_is_paid=False,
):
    """Everything needed before signatures can be gathered: a standard, its
    counties and voters, a petition walked all the way to CLEARED, and one
    REGISTERED circulator holding an ACTIVE assignment."""
    world = setup_program(standard_overrides, counties, voters)
    world["proponent_user_id"] = proponent_user_id
    world["petition"] = create_cleared_petition(
        world["standard"]["id"],
        proponent_user_id=proponent_user_id,
        measure_subject_codes=measure_subject_codes,
    )
    circulator = create_registered_circulator(
        is_paid=circulator_is_paid, **(circulator_overrides or {})
    )
    world["circulators"][circulator_key] = circulator
    codes = list(assigned_county_codes or world["counties"].keys())
    world["assignments"][circulator_key] = create_assignment(
        world["petition"]["id"],
        circulator["id"],
        assigned_county_codes=codes,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    world["circulators"][circulator_key] = read_circulator(circulator["id"])
    world["circulator"] = world["circulators"][circulator_key]
    world["assignment"] = world["assignments"][circulator_key]
    return world


def file_batch_with_lines(
    world,
    lines,
    county_code=None,
    circulator_key="c1",
    verify=True,
    format_defect_line_numbers=None,
    is_supplemental=None,
    cure_period_id=None,
    batch_key=None,
):
    """File one batch, add its lines, and (by default) verify the affidavit so
    the batch reaches AFFIDAVIT_VERIFIED.

    ``lines`` accepts bare voter id numbers or dicts with ``line_number``,
    ``claimed_voter_id_number``, ``signed_on``, ``signature_hash`` and
    ``signer_name``.
    """
    county = world["counties"][county_code or next(iter(world["counties"]))]
    circulator = world["circulators"][circulator_key]
    proponent = world.get("proponent_user_id", PROPONENT_USER_ID)
    batch = file_batch(
        world["petition"]["id"],
        circulator["id"],
        county["id"],
        is_supplemental=is_supplemental,
        cure_period_id=cure_period_id,
        proponent_user_id=proponent,
    )
    built = []
    for index, spec in enumerate(lines, start=1):
        if isinstance(spec, str):
            spec = {"claimed_voter_id_number": spec}
        built.append(
            add_line(
                batch["id"],
                line_number=spec.get("line_number", index),
                claimed_voter_id_number=spec["claimed_voter_id_number"],
                signed_on=spec.get("signed_on", DEFAULT_SIGNED_ON),
                signature_hash=spec.get("signature_hash"),
                signer_name=spec.get("signer_name"),
                proponent_user_id=proponent,
            )
        )
    if verify:
        batch = verify_batch_affidavit(
            batch["id"], county["id"], format_defect_line_numbers=format_defect_line_numbers
        )
    else:
        batch = read_batch(batch["id"])
    record = {"batch": batch, "lines": built, "county": county}
    key = batch_key or "b%d" % (len(world["batches"]) + 1)
    world["batches"][key] = record
    record["key"] = key
    return record


def validate_batch_lines(batch_record, only_in_sample=True, overrides=None):
    """Adjudicate every still-PENDING line of one batch, as the clerk of the
    county that batch belongs to.

    ``overrides`` maps a line_number to the manual_match_override to send.
    """
    county_id = batch_record["county"]["id"]
    results = []
    for line in batch_record["lines"]:
        current = read_line(line["id"])
        if only_in_sample and not current["in_sample"]:
            continue
        if current["validation_status"] != "PENDING":
            continue
        results.append(
            validate_line(
                current["id"],
                county_id,
                manual_match_override=(overrides or {}).get(current["line_number"]),
            )
        )
    return results


def validate_open_sample(world, only_in_sample=True, overrides=None):
    """Adjudicate every pending line across every batch of the world.

    ``overrides`` is either a flat ``{line_number: override}`` applied to every
    batch, or a nested ``{batch_key: {line_number: override}}``.
    """
    nested = bool(overrides) and set(overrides) <= set(world["batches"])
    results = []
    for key, record in world["batches"].items():
        per_batch = (overrides or {}).get(key) if nested else overrides
        results.extend(
            validate_batch_lines(
                record, only_in_sample=only_in_sample, overrides=per_batch
            )
        )
    return results


def close_circulation_and_open_round(
    world, round_type="RANDOM_SAMPLE", examiner_id=EXAMINER_USER_ID
):
    """Close circulation on the world's petition and open a verification
    round over it."""
    close_circulation(
        world["petition"]["id"], world.get("proponent_user_id", PROPONENT_USER_ID)
    )
    world["round"] = open_round(
        world["petition"]["id"], round_type=round_type, examiner_id=examiner_id
    )
    world["petition"] = read_petition(world["petition"]["id"])
    return world["round"]


def run_verification_round(
    world,
    round_type="RANDOM_SAMPLE",
    overrides=None,
    examiner_id=EXAMINER_USER_ID,
    only_in_sample=True,
):
    """Close circulation, open a round, adjudicate its whole sample, and tally
    it. Returns the closed round."""
    opened = close_circulation_and_open_round(
        world, round_type=round_type, examiner_id=examiner_id
    )
    validate_open_sample(world, only_in_sample=only_in_sample, overrides=overrides)
    world["round"] = tally_round(opened["id"], examiner_id=examiner_id)
    world["petition"] = read_petition(world["petition"]["id"])
    return world["round"]


def open_followup_round(
    world, round_type="FULL_CHECK", cure_period_id=None, examiner_id=EXAMINER_USER_ID
):
    """Open a second or later round on a petition whose circulation is already
    closed."""
    world["round"] = open_round(
        world["petition"]["id"],
        round_type=round_type,
        cure_period_id=cure_period_id,
        examiner_id=examiner_id,
    )
    world["petition"] = read_petition(world["petition"]["id"])
    return world["round"]


def run_followup_round(
    world,
    round_type="FULL_CHECK",
    cure_period_id=None,
    overrides=None,
    examiner_id=EXAMINER_USER_ID,
    only_in_sample=True,
):
    opened = open_followup_round(
        world, round_type=round_type, cure_period_id=cure_period_id, examiner_id=examiner_id
    )
    validate_open_sample(world, only_in_sample=only_in_sample, overrides=overrides)
    world["round"] = tally_round(opened["id"], examiner_id=examiner_id)
    world["petition"] = read_petition(world["petition"]["id"])
    return world["round"]


def setup_tallied_petition(
    standard_overrides=None,
    counties=None,
    voters=None,
    batches=None,
    overrides=None,
    examiner_id=EXAMINER_USER_ID,
    **ready_kwargs,
):
    """One-shot: standard + counties + voters + cleared petition + registered
    circulator + assignment + the given batches + one tallied RANDOM_SAMPLE
    round.

    ``batches`` is a list of dicts forwarded to ``file_batch_with_lines`` —
    each needs at least ``lines``.
    """
    world = setup_circulation_ready(
        standard_overrides=standard_overrides,
        counties=counties,
        voters=voters,
        **ready_kwargs,
    )
    for spec in batches or []:
        file_batch_with_lines(world, **spec)
    run_verification_round(world, overrides=overrides, examiner_id=examiner_id)
    return world


def refresh(world):
    """Re-read every mutable entity the world tracks."""
    if "petition" in world:
        world["petition"] = read_petition(world["petition"]["id"])
    for key, circulator in list(world["circulators"].items()):
        world["circulators"][key] = read_circulator(circulator["id"])
    for key, assignment in list(world["assignments"].items()):
        world["assignments"][key] = read_assignment(assignment["id"])
    for record in world["batches"].values():
        record["batch"] = read_batch(record["batch"]["id"])
        record["lines"] = [read_line(line["id"]) for line in record["lines"]]
    if world.get("round"):
        world["round"] = read_round(world["round"]["id"])
    if world.get("circulator"):
        world["circulator"] = read_circulator(world["circulator"]["id"])
    if world.get("assignment"):
        world["assignment"] = read_assignment(world["assignment"]["id"])
    return world
