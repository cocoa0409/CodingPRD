"""Payload factories — one per resource, input fields only.

Numeric fields are always emitted as JSON numbers, never as strings. Datetime
fields are always full ISO 8601 UTC instants, never date-only strings.
"""

# The shared "SOS-FULL" vocabulary: gubernatorial_vote_total 100 with
# signature_pct_bps 200 gives required_valid_signatures 2; sufficiency_upper_bps
# 15000 gives upper_gate 3 and sufficiency_lower_bps 5000 gives lower_gate 1;
# sample_pct_bps 10000 with sample_min_count 1 makes every draw a census.
STANDARD_BASE = {
    "jurisdiction_code": "SOS-FULL",
    "gubernatorial_vote_total": 100,
    "signature_pct_bps": 200,
    "sample_pct_bps": 10000,
    "sample_min_count": 1,
    "sufficiency_upper_bps": 15000,
    "sufficiency_lower_bps": 5000,
    "stratification_mode": "POOLED",
    "county_distribution_pct_bps": 500,
    "required_qualifying_counties": 1,
    "verification_rate_millicents_per_signature": 4750,
    "county_surcharge_bps": 250,
    "cure_allowed": True,
    "cure_window_days": 30,
    "cure_eligibility_floor_bps": 5000,
    "circulation_window_days": 180,
}

# The twelve mandatory parameters only. Sending this leaves the four optional
# inputs absent so their declared defaults apply.
MANDATORY_STANDARD_FIELDS = [
    "jurisdiction_code",
    "gubernatorial_vote_total",
    "signature_pct_bps",
    "sample_pct_bps",
    "sample_min_count",
    "sufficiency_upper_bps",
    "sufficiency_lower_bps",
    "stratification_mode",
    "county_distribution_pct_bps",
    "required_qualifying_counties",
    "verification_rate_millicents_per_signature",
    "county_surcharge_bps",
]


def create_verification_standard_payload(**overrides):
    """The full sixteen-parameter payload, with every optional input stated
    explicitly so a test's arithmetic never depends on a default."""
    payload = dict(STANDARD_BASE)
    payload.update(overrides)
    return payload


def minimal_verification_standard_payload(**overrides):
    """Only the mandatory parameters; the four optional inputs are omitted so
    the server must supply their declared defaults."""
    payload = {key: STANDARD_BASE[key] for key in MANDATORY_STANDARD_FIELDS}
    payload.update(overrides)
    return payload


def create_county_payload(**overrides):
    payload = {
        "county_code": "ALPHA",
        "name": "Alpha County",
        "registered_voter_count": 20,
    }
    payload.update(overrides)
    return payload


def create_voter_record_payload(county_id, **overrides):
    payload = {
        "county_id": county_id,
        "voter_id_number": "VA1",
        "full_name": "Ada Adams",
        "signature_on_file_hash": "H-VA1",
        "registration_date": "2020-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_petition_payload(standard_id, **overrides):
    payload = {
        "standard_id": standard_id,
        "proponent_name": "Test Committee",
        "submitted_title": "Test Measure",
        "measure_subject_codes": ["TAX"],
    }
    payload.update(overrides)
    return payload


def format_decision_payload(decision="APPROVE", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def title_summary_payload(expected_petition_version, **overrides):
    payload = {
        "official_title": "The Official Act",
        "official_summary": "An official summary of the measure.",
        "expected_petition_version": expected_petition_version,
    }
    payload.update(overrides)
    return payload


def create_circulator_payload(**overrides):
    payload = {
        "full_name": "Cora Carter",
        "residency_state_code": "CA",
    }
    payload.update(overrides)
    return payload


def training_payload(training_course_code="SOS-CIRC-101", **overrides):
    payload = {"training_course_code": training_course_code}
    payload.update(overrides)
    return payload


def paid_disclosure_payload(disclosure_document_id="DISC-1", **overrides):
    payload = {"disclosure_document_id": disclosure_document_id}
    payload.update(overrides)
    return payload


def affidavit_payload(sworn=True, **overrides):
    payload = {"sworn": sworn}
    payload.update(overrides)
    return payload


def create_assignment_payload(
    petition_id,
    circulator_id,
    expected_circulator_version,
    assigned_county_codes=None,
    effective_from="2026-08-01T00:00:00Z",
    effective_to="2026-08-31T00:00:00Z",
    **overrides,
):
    payload = {
        "petition_id": petition_id,
        "circulator_id": circulator_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "assigned_county_codes": list(assigned_county_codes or ["ALPHA"]),
        "expected_circulator_version": expected_circulator_version,
    }
    payload.update(overrides)
    return payload


def create_batch_payload(petition_id, circulator_id, county_id, **overrides):
    payload = {
        "petition_id": petition_id,
        "circulator_id": circulator_id,
        "county_id": county_id,
        "affidavit_signed": True,
    }
    payload.update(overrides)
    return payload


def add_signature_payload(
    line_number=1,
    signer_name="Ada Adams",
    claimed_voter_id_number="VA1",
    signed_on="2026-08-05T00:00:00Z",
    signature_hash="H-VA1",
    **overrides,
):
    payload = {
        "line_number": line_number,
        "signer_name": signer_name,
        "claimed_voter_id_number": claimed_voter_id_number,
        "signed_on": signed_on,
        "signature_hash": signature_hash,
    }
    payload.update(overrides)
    return payload


def verify_affidavit_payload(affidavit_notary_id="NOT-1", **overrides):
    payload = {"affidavit_notary_id": affidavit_notary_id}
    payload.update(overrides)
    return payload


def invalidate_batch_payload(invalidation_reason="Struck on review", **overrides):
    payload = {"invalidation_reason": invalidation_reason}
    payload.update(overrides)
    return payload


def create_round_payload(round_type="RANDOM_SAMPLE", **overrides):
    payload = {"round_type": round_type}
    payload.update(overrides)
    return payload


def void_round_payload(voided_reason="Examination error", **overrides):
    payload = {"voided_reason": voided_reason}
    payload.update(overrides)
    return payload


def create_challenge_payload(**overrides):
    payload = {
        "challenger_name": "Concerned Elector",
        "grounds": "COUNT_ERROR",
        "statement": "The count is disputed.",
    }
    payload.update(overrides)
    return payload


def escalate_challenge_payload(court_docket_number="DOCKET-1", **overrides):
    payload = {"court_docket_number": court_docket_number}
    payload.update(overrides)
    return payload


def rule_payload(ruling="AFFIRM", **overrides):
    payload = {"ruling": ruling}
    payload.update(overrides)
    return payload


def determination_payload(determination="CERTIFY", **overrides):
    payload = {"determination": determination}
    payload.update(overrides)
    return payload


def create_fraud_referral_payload(petition_id, circulator_id, **overrides):
    payload = {
        "petition_id": petition_id,
        "circulator_id": circulator_id,
        "referral_type": "FORGED_SIGNATURES",
        "narrative": "Signatures appear to be in one hand.",
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(finding="SUBSTANTIATED", **overrides):
    payload = {"finding": finding}
    payload.update(overrides)
    return payload


def clock_payload(current_utc):
    return {"current_utc": current_utc}


def registration_status_payload(registration_status):
    return {"registration_status": registration_status}
