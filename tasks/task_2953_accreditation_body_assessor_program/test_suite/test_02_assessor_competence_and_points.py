"""Assessor recruitment, the four-factor points model and the grant boundary.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    add_days,
    assert_audit_fields,
    assert_capacity_ledger,
    assert_points_equal,
    assert_total_count,
)
from test_helpers.api_errors import ERR_ASSESSOR_NOT_FOUND
from test_helpers.constants import (
    EMPLOYMENT_CONTRACT,
    EMPLOYMENT_INTERNAL,
    IMPARTIALITY_UNDECLARED,
    QUALIFICATION_STATUS_APPLICANT,
    QUALIFICATION_STATUS_SCREENING,
    QUALIFICATION_VALIDITY_DAYS,
    QUAL_GRANTED,
    QUAL_PENDING,
    ROLE_TYPE_LEAD_ASSESSOR,
    ROLE_TYPE_TECHNICAL_EXPERT,
    STANDARD_REF_17020,
    UNKNOWN_UUID,
    WITNESS_DAY_FLOOR_LEAD_ASSESSOR,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER, SCHEME_MANAGER

GRANT_DATE = "2026-08-10"
EXPIRY_DATE = "2030-08-09"


def test_new_assessor_lifecycle_fields_are_system_initialized(client):
    """Registration seeds both state dimensions and the witness-day ledger.

    PRD section 3.2: "An `annual_witness_capacity_days` may be supplied,
    defaulting to 20 and constrained to between 0 and 250 days; this is the
    conserved total of the assessor's witness-day ledger, so a new assessor
    starts with `committed_witness_days` at 0 and `available_witness_days`
    equal to the capacity just set."

    Design: Corner/entities/new_assessor_lifecycle_fields_are_system_initialized
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)

    response = client.create_assessor(
        f.assessor_payload(
            "Lena Ahlgren", "lena.ahlgren@ab.test", EMPLOYMENT_INTERNAL, 12
        ),
        ASSESSMENT_MANAGER,
    )

    assessor = validate_success(response, 201)
    assert assessor["qualification_status"] == QUALIFICATION_STATUS_APPLICANT
    assert assessor["impartiality_status"] == IMPARTIALITY_UNDECLARED
    assert assessor["annual_witness_capacity_days"] == 12
    assert_capacity_ledger(assessor, committed=0, available=12)
    assert assessor["granted_qualification_count"] == 0
    assert assessor["last_screened_on"] is None
    assert assessor["suspension_reason"] is None
    assert_audit_fields(assessor, expected_version=1)


def test_declared_and_verified_competence_points_diverge(client):
    """The provisional and final variants read different counts, so the two
    points figures on one qualification differ.

    PRD section 3.2: "The **provisional** variant runs at qualification
    registration and writes `declared_points`. It reads only the
    self-declared numbers — the declared years of experience supplied as
    `years_experience`, plus `declared_witness_days` and
    `declared_training_modules` — and pins the recency factor to 1.00
    regardless of what `last_witness_on` says."

    Design: Difficulty/dual_variant_calc/competence_points_declared_provisional_vs_verified_final_diverge
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(client, "ISO17025-CAL")
    assessor = fx.register_assessor(
        client, "Lena Ahlgren", "lena.ahlgren@ab.test", EMPLOYMENT_INTERNAL, 20
    )
    qualification = fx.register_qualification(
        client,
        assessor["id"],
        scheme["id"],
        ROLE_TYPE_LEAD_ASSESSOR,
        8,
        6,
        3,
        "2026-05-10",
    )
    assert_points_equal(qualification["declared_points"], "92.00")

    response = client.verify_evidence(
        qualification["id"], f.verify_evidence_payload(8, 5, 2), SCHEME_MANAGER
    )

    verified = validate_success(response, 200)
    assert_points_equal(verified["declared_points"], "92.00")
    assert_points_equal(verified["verified_points"], "87.00")
    assert float(verified["declared_points"]) != float(verified["verified_points"]), (
        "The two variants must not collapse onto one figure"
    )
    assert verified["status"] == QUAL_GRANTED
    assert verified["granted_on"] == GRANT_DATE
    assert verified["expires_on"] == EXPIRY_DATE
    assert verified["expires_on"] == add_days(GRANT_DATE, QUALIFICATION_VALIDITY_DAYS)
    owner = fx.read_assessor(client, assessor["id"])
    assert owner["granted_qualification_count"] == 1


def test_qualification_granted_at_exact_points_and_exact_witness_day_floor(client):
    """Both grant conditions are inclusive comparisons, tested one unit
    either side of each boundary.

    PRD section 3.2: "The qualification is then granted only when two
    conditions both hold: `verified_points` is at least the programme's
    `qualification_points_required`, and `verified_witness_days` is at least
    the witness-day floor for the `role_type` being claimed — 4 days for
    `LEAD_ASSESSOR`, 2 days for `TECHNICAL_ASSESSOR`, and 0 days for
    `TECHNICAL_EXPERT`."

    Design: Difficulty/boundary_precision_check/qualification_granted_at_exact_points_and_exact_witness_day_floor
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(client, "ISO17025-BND")

    def candidate(full_name, email, years, declared_days):
        assessor = fx.register_assessor(client, full_name, email, EMPLOYMENT_CONTRACT, 20)
        qualification = fx.register_qualification(
            client,
            assessor["id"],
            scheme["id"],
            ROLE_TYPE_LEAD_ASSESSOR,
            years,
            declared_days,
            1,
            "2026-06-01",
        )
        return assessor, qualification

    assessor_a, qual_a = candidate("Aina Boundary", "aina.boundary@ab.test", 6, 4)
    assessor_b, qual_b = candidate("Bo Underpoints", "bo.underpoints@ab.test", 6, 4)
    assessor_c, qual_c = candidate("Cai Underdays", "cai.underdays@ab.test", 9, 4)
    verified_b = fx.verify_qualification(client, qual_b["id"], 6, 3, 1)
    verified_c = fx.verify_qualification(client, qual_c["id"], 9, 3, 1)

    response = client.verify_evidence(
        qual_a["id"], f.verify_evidence_payload(6, 4, 1), SCHEME_MANAGER
    )

    verified_a = validate_success(response, 200)
    assert_points_equal(verified_a["verified_points"], "60.00")
    assert verified_a["status"] == QUAL_GRANTED, "The points comparison is >= and not >"
    assert verified_a["granted_on"] == GRANT_DATE
    assert verified_a["expires_on"] == EXPIRY_DATE
    assert verified_a["verified_witness_days"] == WITNESS_DAY_FLOOR_LEAD_ASSESSOR
    assert fx.read_assessor(client, assessor_a["id"])["granted_qualification_count"] == 1

    assert_points_equal(verified_b["verified_points"], "55.00")
    assert verified_b["status"] == QUAL_PENDING
    assert verified_b["granted_on"] is None
    assert_points_equal(verified_c["verified_points"], "67.00")
    assert verified_c["status"] == QUAL_PENDING, (
        "Above the points bar but one day below the LEAD_ASSESSOR witness floor"
    )
    assert verified_c["granted_on"] is None
    assert fx.read_assessor(client, assessor_b["id"])["granted_qualification_count"] == 0
    assert fx.read_assessor(client, assessor_c["id"])["granted_qualification_count"] == 0


def test_verified_recency_bands_at_their_exact_day_boundaries(client):
    """The three recency factors, read at 365, 366, 730 and 731 whole days.

    PRD section 3.2: "It reads only the verifier-confirmed numbers
    `verified_years_experience`, `verified_witness_days` and
    `verified_training_modules`, and derives the recency factor from the
    number of whole days between `last_witness_on` and the current
    logical-clock date: the factor is 1.00 when that gap is at most 365 days,
    0.90 when the gap is from 366 to 730 days inclusive, and 0.75 when the
    gap exceeds 730 days or when `last_witness_on` is null altogether."

    Design: Corner/calculations/verified_competence_recency_bands_at_their_exact_day_boundaries
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(
        client, "ISO17025-CAL", qualification_points_required=60.0, witness_min_count=2
    )

    def candidate(full_name, email, last_witness_on):
        assessor = fx.register_assessor(client, full_name, email, EMPLOYMENT_INTERNAL, 20)
        return fx.register_qualification(
            client,
            assessor["id"],
            scheme["id"],
            ROLE_TYPE_LEAD_ASSESSOR,
            8,
            6,
            3,
            last_witness_on,
        )

    qual_a = candidate("Aina Berg", "aina.berg@ab.test", "2025-08-10")
    qual_b = candidate("Bo Carlsen", "bo.carlsen@ab.test", "2025-08-09")
    qual_c = candidate("Cato Dahl", "cato.dahl@ab.test", "2024-08-10")
    qual_d = candidate("Dina Eide", "dina.eide@ab.test", "2024-08-09")
    verified_a = fx.verify_qualification(client, qual_a["id"], 8, 5, 2)
    verified_b = fx.verify_qualification(client, qual_b["id"], 8, 5, 2)
    verified_c = fx.verify_qualification(client, qual_c["id"], 8, 5, 2)

    response = client.verify_evidence(
        qual_d["id"], f.verify_evidence_payload(8, 5, 2), SCHEME_MANAGER
    )

    verified_d = validate_success(response, 200)
    assert_points_equal(verified_a["verified_points"], "87.00")
    assert_points_equal(verified_b["verified_points"], "78.30")
    assert_points_equal(verified_c["verified_points"], "78.30")
    assert_points_equal(verified_d["verified_points"], "65.25")
    assert_points_equal(qual_a["declared_points"], "92.00")
    assert_points_equal(qual_d["declared_points"], "92.00")
    for verified in (verified_a, verified_b, verified_c, verified_d):
        assert verified["status"] == QUAL_GRANTED, (
            "Five verified witness days clears the LEAD_ASSESSOR floor of four"
        )
    assert verified_a["expires_on"] == EXPIRY_DATE


def test_qualification_under_unknown_assessor_is_not_found(client):
    """The path identifier is resolved before the body's foreign key.

    PRD section 2.9: "Foreign keys supplied **in the request body** are
    resolved only after every path identifier has resolved, and among
    themselves they are resolved in the order the fields are declared for
    that endpoint."

    Design: Corner/entities/create_qualification_under_unknown_assessor_not_found
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(client, "ISO17025-CAL")

    response = client.create_qualification(
        UNKNOWN_UUID,
        f.qualification_payload(
            scheme["id"], ROLE_TYPE_LEAD_ASSESSOR, 8, 6, 3, "2026-05-10"
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_ASSESSOR_NOT_FOUND, 404)
    assert_total_count(
        client.list_qualifications(ASSESSMENT_MANAGER, {"scheme_id": scheme["id"]}), 0
    )


def test_qualification_lists_resolve_both_reverse_foreign_keys(client):
    """One assessor's two qualifications are reachable from either side.

    PRD section 3.2: "Qualification lists may be filtered by `assessor_id`,
    `scheme_id`, `role_type` and `status`, and the qualification detail view
    exposes `declared_points` and `verified_points` side by side."

    Design: Corner/endpoints/qualification_lists_resolve_both_reverse_foreign_keys
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme_a = fx.create_published_scheme(
        client, "ISO17025-CAL", witness_min_count=2, qualification_points_required=60.0
    )
    scheme_b = fx.create_published_scheme(
        client,
        "ISO17020-INSP",
        name="Inspection bodies",
        standard_ref=STANDARD_REF_17020,
        witness_min_count=1,
        qualification_points_required=60.0,
    )
    assessor = fx.register_assessor(
        client, "Bruno Katz", "bruno.katz@ab.test", EMPLOYMENT_CONTRACT, 20
    )
    qual_a = fx.register_qualification(
        client,
        assessor["id"],
        scheme_a["id"],
        ROLE_TYPE_LEAD_ASSESSOR,
        6,
        4,
        1,
        "2026-05-10",
    )

    response = client.create_qualification(
        assessor["id"],
        f.qualification_payload(
            scheme_b["id"], ROLE_TYPE_TECHNICAL_EXPERT, 12, 2, 2, "2026-05-10"
        ),
        ASSESSMENT_MANAGER,
    )

    qual_b = validate_success(response, 201)
    assert qual_b["assessor_id"] == assessor["id"]
    assert qual_b["scheme_id"] == scheme_b["id"]
    by_assessor = assert_total_count(
        client.list_qualifications(ASSESSMENT_MANAGER, {"assessor_id": assessor["id"]}), 2
    )
    assert {row["id"] for row in by_assessor} == {qual_a["id"], qual_b["id"]}
    rows = assert_total_count(
        client.list_qualifications(ASSESSMENT_MANAGER, {"scheme_id": scheme_a["id"]}), 1
    )
    assert rows[0]["id"] == qual_a["id"]
    rows = assert_total_count(
        client.list_qualifications(ASSESSMENT_MANAGER, {"scheme_id": scheme_b["id"]}), 1
    )
    assert rows[0]["id"] == qual_b["id"]
    rows = assert_total_count(
        client.list_qualifications(
            ASSESSMENT_MANAGER,
            {"assessor_id": assessor["id"], "role_type": ROLE_TYPE_LEAD_ASSESSOR},
        ),
        1,
    )
    assert rows[0]["id"] == qual_a["id"]
    assert qual_a["status"] == QUAL_PENDING
    assert qual_b["status"] == QUAL_PENDING
    owner = fx.read_assessor(client, assessor["id"])
    assert owner["qualification_status"] == QUALIFICATION_STATUS_SCREENING
    assert owner["granted_qualification_count"] == 0
