"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LETTERS = ["A", "B", "C", "D", "F"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_hospital(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"], "name must be a non-empty string"
    assert isinstance(data.get("ccn"), str) and len(data["ccn"]) == 6, (
        f"ccn must be a six-character string, got {data.get('ccn')!r}"
    )
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2, (
        f"state_code must be a two-letter uppercase code, got {data.get('state_code')!r}"
    )
    assert isinstance(data.get("bed_count"), int) and data["bed_count"] >= 1
    assert isinstance(data.get("annual_discharges"), int) and data["annual_discharges"] >= 1
    assert data.get("teaching_status") in ["TEACHING", "NON_TEACHING"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED"]
    assert data.get("disclosure_status") in ["NEVER_SUBMITTED", "SUBMITTED", "UNVERIFIED"]
    assert data.get("worst_grade_ever") in LETTERS + [None]
    assert "submitted_source_document_count" in data
    assert isinstance(data["submitted_source_document_count"], int)
    assert data["submitted_source_document_count"] >= 0


def assert_methodology_version(data: dict):
    _assert_common(data)
    assert isinstance(data.get("label"), str) and data["label"]
    assert isinstance(data.get("measure_definitions"), list)
    assert data.get("status") in ["DRAFT", "PUBLISHED"]
    for md in data["measure_definitions"]:
        assert md["domain"] in [
            "PATIENT_SAFETY", "INFECTION_PREVENTION", "CPOE", "STAFFING", "SURGICAL_VOLUME",
        ]
        assert md["derivation_rule"] in [
            "NONE", "RATE_TO_COUNT_FLOOR", "INVERSE_BOUNDED", "PER_100_BEDS_FLOOR",
        ]


def assert_survey(data: dict):
    _assert_common(data)
    assert data.get("af_status") in [
        "AWAITING_SUBMISSION", "SUBMITTED", "VERIFIED", "DISCREPANCY_OPEN", "DISCREPANCY_RESOLVED",
    ]
    assert data.get("af_certification_level") in [
        "UNCERTIFIED", "CERTIFIED", "CERTIFICATION_WITHDRAWN",
    ]
    assert data.get("verification_response") in ["ACCEPT", "DISCREPANCY_REQUEST", None]
    assert isinstance(data.get("verification_cycle"), int)
    assert data["verification_cycle"] >= 0
    assert isinstance(data.get("started_survey_count"), int)
    assert isinstance(data.get("completed_survey_count"), int)
    assert isinstance(data.get("entity_annual_discharges"), int)
    assert data.get("validation_method") in ["ATTESTATION", "SOURCE_DOCUMENT", None]


def assert_survey_measure(data: dict):
    _assert_common(data)
    assert isinstance(data.get("measure_code"), str) and data["measure_code"]
    assert isinstance(data.get("raw_value"), (int, float))
    assert data.get("measure_status") in [
        "REPORTED", "UNREPORTED_EXCLUDED", "PUBLIC_SOURCE_SUBSTITUTED",
    ]
    assert isinstance(data.get("flag_hold"), bool)


def assert_measure_set(data: dict):
    _assert_common(data)
    assert data.get("readiness_state") in ["INCOMPLETE", "OMITTED_FROM_CYCLE", "READY"]
    assert isinstance(data.get("measures"), list)
    assert isinstance(data.get("substituted_measure_count"), int)
    assert data["substituted_measure_count"] >= 0
    for m in data["measures"]:
        assert "measure_code" in m and "domain" in m
        assert m["measure_status"] in [
            "REPORTED", "UNREPORTED_EXCLUDED", "PUBLIC_SOURCE_SUBSTITUTED",
        ]
        if m["measure_status"] == "UNREPORTED_EXCLUDED":
            assert m.get("derived_value") is None, (
                "an excluded measure carries a null derived value"
            )


def assert_score_run(data: dict):
    _assert_common(data)
    assert data.get("score_state") in [
        "RUNNING", "SCORED", "CHAR_EXEMPT", "REANALYSIS_PENDING",
    ]
    assert isinstance(data.get("domain_scores"), list)
    assert data.get("base_grade_letter") in LETTERS + [None]
    assert data.get("letter_grade") in LETTERS + [None]


def assert_release_cycle(data: dict):
    _assert_common(data)
    assert data.get("state") in [
        "DRAFT", "OPEN_REVIEW", "CORRECTION_CLOSED", "EMBARGOED", "PUBLISHED",
    ]
    assert isinstance(data.get("embargo_lifted"), bool)
    assert isinstance(data.get("grade_count"), int)
    assert isinstance(data.get("correction_request_count"), int)


def assert_grade(data: dict):
    _assert_common(data)
    assert data.get("status") in ["SCORED", "CHAR_EXEMPT", "CORRECTED", "WITHHELD"]
    assert data.get("letter_grade") in LETTERS + [None]
    assert isinstance(data.get("grade_cap_applied"), bool)


def assert_hospital_review(data: dict):
    _assert_common(data)
    assert data.get("status") in ["PENDING", "ACCEPTED", "CORRECTION_REQUESTED"]
    assert isinstance(data.get("challenged_measure_codes"), list)
    assert data.get("accepted_at") is None or is_iso8601_timestamp(data["accepted_at"])


def assert_correction_request(data: dict):
    _assert_common(data)
    assert data.get("correction_type") in [
        "MEASURE_VALUE_ERROR", "MEASURE_OMISSION", "SOURCE_PROGRAM_MISMATCH",
    ]
    assert data.get("status") in ["PENDING", "ACCEPTED", "REJECTED", "EXPIRED"]
    assert isinstance(data.get("corrected_measure_codes"), list)
    assert isinstance(data.get("delta_points"), (int, float))


def assert_reanalysis_request(data: dict):
    _assert_common(data)
    assert data.get("status") in ["PENDING", "UNDER_REVIEW", "GRANTED", "REFUTED", "WITHDRAWN"]
    assert isinstance(data.get("subset_selector"), list)
    assert isinstance(data.get("documents_sufficient"), bool)
    assert isinstance(data.get("reference_stale"), bool)
    assert isinstance(data.get("non_regression_confirmed"), bool)


def assert_employer(data: dict):
    _assert_common(data)
    assert data.get("purchaser_type") in [
        "SELF_INSURED_EMPLOYER", "COALITION", "HEALTH_PLAN",
    ]
    assert data.get("minimum_acceptable_letter") in ["A", "B", "C", "D"]
    assert isinstance(data.get("network_hospital_count"), int)
    assert isinstance(data.get("eligible_hospital_count"), int)


def assert_score_run_invariants(data: dict):
    """Invariants that hold for any completed run."""
    assert data["score_state"] in ["SCORED", "CHAR_EXEMPT", "REANALYSIS_PENDING", "RUNNING"]
    if data["score_state"] == "CHAR_EXEMPT":
        assert data.get("letter_grade") is None, "an exempt run carries no letter"
    if data.get("composite_score") is not None:
        assert round(data["composite_score"], 2) == data["composite_score"], (
            "composite_score is rounded once to two decimal places"
        )


def assert_employer_invariants(data: dict):
    assert data["eligible_hospital_count"] <= data["network_hospital_count"]
    if data.get("utilization_index") is not None:
        assert round(data["utilization_index"], 4) == data["utilization_index"], (
            "utilization_index is reported to four decimal places"
        )
        assert 0.0 <= data["utilization_index"] <= 1.0


def domain_score_of(domain_scores, domain):
    """Extract one domain's score from a run's or preview's domain array."""
    for entry in domain_scores:
        if entry.get("domain") == domain:
            return entry.get("domain_score")
    return None


def domain_names(domain_scores):
    return [entry.get("domain") for entry in domain_scores]

def and_instant_equal(actual, expected):
    """Compare two instants at second granularity.

    PRD §2.2 renders server-generated instants with three fractional digits,
    while a request may carry the same instant in bare-seconds form. Comparing
    the parsed values keeps an assertion about the *instant* honest instead of
    over-constraining the fractional-digit rendering.
    """
    from datetime import datetime, timezone

    def _parse(value):
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).replace(microsecond=0)

    return _parse(actual) == _parse(expected)
