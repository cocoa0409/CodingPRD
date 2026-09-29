"""Scheme rule development: creation defaults, the registry and the status loop.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_audit_fields,
    assert_instant_equals,
    assert_pagination_meta,
    assert_scheme_defaults,
    assert_single_resource_envelope,
    assert_total_count,
    validate_list,
)
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SCHEME_NOT_FOUND,
    ERR_SCHEME_NOT_PUBLISHED,
)
from test_helpers.constants import (
    CYCLE_INITIAL,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    SCHEME_DRAFT,
    SCHEME_PUBLISHED,
    SCHEME_UNDER_REVIEW,
    SCHEME_WITHDRAWN,
    STANDARD_REF_17020,
    STANDARD_REF_17025,
    STANDARD_REF_17065,
    UNKNOWN_UUID,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER, COMPLAINT_OFFICER, SCHEME_MANAGER


def test_scheme_creation_applies_every_declared_default(client):
    """Only the three mandatory inputs are supplied, so every optional
    rule-set field must fall back to its declared default.

    PRD section 3.1: "Everything else about the rule set is optional at
    creation and falls back to a default." and "A freshly created programme
    is in `status` `DRAFT` with `rule_revision` 1, `revision_note` null and
    `published_at` null."

    Design: Corner/entities/create_scheme_applies_all_declared_defaults
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)

    response = client.create_scheme(
        {
            "program_code": "ISO17020-INSP",
            "name": "Inspection bodies",
            "standard_ref": STANDARD_REF_17020,
        },
        SCHEME_MANAGER,
    )

    scheme = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"], "meta.api_request_id must be present"
    assert body["meta"]["api_request_timestamp"], "meta.api_request_timestamp must be present"
    assert_audit_fields(scheme, expected_version=1)
    assert_instant_equals(scheme["created_at"], fx.CLOCK_BUILD_INSTANT)
    assert_scheme_defaults(scheme)


def test_scheme_creation_without_standard_ref_is_rejected(client):
    """``standard_ref`` is one of the three mandatory creation inputs.

    PRD section 3.1: "Creation requires a `program_code` of 3 to 32
    characters that is unique across all accreditation programmes and
    compared case-sensitively — `ISO17025-LAB` and `iso17025-lab` are two
    different programme codes — together with a human-readable `name` of 1 to
    160 characters and a `standard_ref` naming the international standard the
    rules align to, one of `ISO_IEC_17025`, `ISO_IEC_17020`,
    `ISO_IEC_17021_1` or `ISO_IEC_17065`."

    Design: Corner/entities/create_scheme_without_standard_ref_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)

    response = client.create_scheme(
        {"program_code": "ISO17020-INSP", "name": "Inspection bodies"}, SCHEME_MANAGER
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert response.json()["response_type"] == "error"
    assert_total_count(client.list_schemes(SCHEME_MANAGER), 0)


def test_scheme_detail_returns_the_stored_rule_set(client):
    """A single-resource read echoes the explicit non-default parameters.

    PRD section 2.3: "For list responses the `meta` object carries four
    pagination fields — `limit` and `offset` echoing the values actually
    applied, `total_count` giving the number of rows matching the filters
    before the window was applied, and `has_more` indicating whether any
    matching row falls beyond the current window. Single-resource responses
    omit all four."

    Design: Corner/entities/get_scheme_by_id_returns_the_stored_scheme
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    created = fx.create_scheme(
        client,
        "ISO17025-CAL",
        complexity_multiplier=1.0725,
        witness_min_count=2,
        qualification_points_required=72.5,
    )

    response = client.get_scheme(created["id"], ASSESSMENT_MANAGER)

    scheme = assert_single_resource_envelope(response, 200)
    assert scheme["id"] == created["id"]
    assert scheme["program_code"] == "ISO17025-CAL"
    assert scheme["standard_ref"] == STANDARD_REF_17025
    assert float(scheme["complexity_multiplier"]) == 1.0725
    assert scheme["witness_min_count"] == 2
    assert float(scheme["qualification_points_required"]) == 72.5
    assert scheme["status"] == SCHEME_DRAFT


def test_scheme_detail_with_unknown_uuid_is_not_found(client):
    """A well-formed identifier that resolves to no live row is a 404.

    PRD section 2.9: "Each identifier that fails to resolve to a live row
    produces the not-found error of its own resource type, at HTTP 404:
    `ERR_SCHEME_NOT_FOUND`, `ERR_ASSESSOR_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`,
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_TEAM_ASSIGNMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_WITNESS_SESSION_NOT_FOUND`, `ERR_NONCONFORMITY_NOT_FOUND`,
    `ERR_DECISION_NOT_FOUND`, `ERR_SCOPE_NOT_FOUND` and
    `ERR_COMPLAINT_NOT_FOUND`."

    Design: Corner/entities/get_scheme_with_unknown_uuid_not_found
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)

    response = client.get_scheme(UNKNOWN_UUID, SCHEME_MANAGER)

    validate_error(response, ERR_SCHEME_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"


def test_scheme_list_applies_pagination_defaults_and_status_filter(client):
    """An unwindowed read gets the declared defaults; ``status`` narrows it.

    PRD section 2.3: "`limit` defaults to 10 when omitted, must be an
    integer, and must be at least 1 and at most 100."

    Design: Corner/entities/list_schemes_applies_pagination_defaults_and_status_filter
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme_a = fx.create_scheme(client, "ISO17025-CAL")
    scheme_b = fx.create_scheme(
        client, "ISO17020-INSP", name="Inspection bodies", standard_ref=STANDARD_REF_17020
    )
    scheme_c = fx.create_scheme(
        client,
        "ISO17065-PROD",
        name="Product certification bodies",
        standard_ref=STANDARD_REF_17065,
    )
    fx.publish_scheme(client, scheme_a["id"])

    response = client.list_schemes(COMPLAINT_OFFICER)

    rows, meta = validate_list(response)
    assert response.json()["response_type"] == "array"
    assert_pagination_meta(meta, DEFAULT_LIMIT, DEFAULT_OFFSET, 3, False)
    assert {row["id"] for row in rows} == {scheme_a["id"], scheme_b["id"], scheme_c["id"]}

    published = assert_total_count(
        client.list_schemes(COMPLAINT_OFFICER, {"status": SCHEME_PUBLISHED}), 1
    )
    assert [row["id"] for row in published] == [scheme_a["id"]]
    assert_total_count(
        client.list_schemes(COMPLAINT_OFFICER, {"status": SCHEME_DRAFT}), 2
    )


def test_scheme_status_with_undeclared_enum_member_is_rejected(client):
    """``ARCHIVED`` is not a member of the declared status set.

    PRD section 2.9: "Request-shape validity: on every write, the body must
    be a JSON object, every required input must be present, every enum-typed
    value must be a member of its declared set, every count field must be
    non-negative, and every monetary or points field must be numeric —
    otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/scheme_status_with_undeclared_enum_member_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_scheme(client, "ISO17025-CAL")

    response = client.set_scheme_status(
        scheme["id"], {"to_status": "ARCHIVED"}, SCHEME_MANAGER
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    stored = validate_success(client.get_scheme(scheme["id"], SCHEME_MANAGER), 200)
    assert stored["status"] == SCHEME_DRAFT
    assert stored["version"] == 1, "A rejected shape must not bump the version"


def test_newly_created_scheme_starts_in_the_declared_initial_state(client):
    """A ``DRAFT`` programme cannot yet carry a cycle.

    PRD section 3.4: "The programme must be `PUBLISHED`
    (`ERR_SCHEME_NOT_PUBLISHED`), and the organization must not already have
    another cycle for the same programme sitting in a non-terminal status —
    the terminal statuses being `GRANTED` and `WITHDRAWN` — or the request is
    rejected with `ERR_DUPLICATE_ACTIVE_APPLICATION`."

    Design: Corner/state_machines/newly_created_scheme_starts_in_the_declared_initial_state
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    organization = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )

    scheme = validate_success(
        client.create_scheme(f.scheme_payload("ISO17025-CAL"), SCHEME_MANAGER), 201
    )

    assert scheme["status"] == SCHEME_DRAFT
    assert scheme["published_at"] is None
    assert scheme["rule_revision"] == 1
    rejected = client.create_application(
        f.application_payload(
            organization["id"],
            scheme["id"],
            CYCLE_INITIAL,
            ["mass calibration 1 mg - 20 kg"],
            30,
        ),
        ASSESSMENT_MANAGER,
    )
    validate_error(rejected, ERR_SCHEME_NOT_PUBLISHED, 422)


def test_withdrawn_scheme_rejects_every_further_status_change(client):
    """``WITHDRAWN`` is terminal, so no successor status is declared for it.

    PRD section 3.1: "Any `to_status` that is not a declared successor of the
    programme's current status — publishing straight from `DRAFT`, for
    instance, or reviving a `WITHDRAWN` programme — is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/withdrawn_scheme_rejects_every_further_status_change
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_scheme(client, "ISO17025-CAL")
    fx.publish_scheme(client, scheme["id"])
    withdrawn = fx.drive_scheme_status(client, scheme["id"], SCHEME_WITHDRAWN)
    assert withdrawn["status"] == SCHEME_WITHDRAWN
    assert withdrawn["version"] == 4

    response = client.set_scheme_status(
        scheme["id"], f.scheme_status_payload(SCHEME_UNDER_REVIEW), SCHEME_MANAGER
    )

    validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)
    stored = validate_success(client.get_scheme(scheme["id"], SCHEME_MANAGER), 200)
    assert stored["status"] == SCHEME_WITHDRAWN
    assert stored["version"] == 4
    # A ``to_status`` of ``DRAFT`` carries ``revision_note`` so that the
    # rank-3 shape check of section 2.9 is satisfied and the rank-8 status
    # check is the earliest rule this request violates.
    second = client.set_scheme_status(
        scheme["id"],
        f.scheme_status_payload(SCHEME_DRAFT, "Reviving a withdrawn programme."),
        SCHEME_MANAGER,
    )
    validate_error(second, ERR_INVALID_STATE_TRANSITION, 409)
