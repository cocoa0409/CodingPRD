"""Error corners: one envelope for every refusal, and the ladder's own ordering.

Two instances of the CORNER design index's ``errors`` section are translated
here:

* refusals raised at three different tiers of PRD section 2.5's ladder — role
  authorisation, path existence and request shape — must all come back in PRD
  section 2.2's single error envelope, with the documented HTTP status and a
  non-empty ``data.message``, and never with the code hoisted to the top level;
* a request that is wrong in both the path and the body must report the tier-4
  404 rather than the tier-5 422, with the same body proved schema-invalid on a
  resolvable path.

PRD section 2.2 gives error responses no ``success`` field: the envelope carries
``meta``, ``response_type`` set to ``"error"``, and ``data``. The design index's
"success false" is therefore asserted as ``response_type == "error"``, which the
shared ``validate_error`` validator enforces on every call below.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DEAL_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ISSUER_NOT_FOUND,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import assert_pagination
from test_helpers.constants import SEQUENCE_NUMBER_MIN
from test_helpers.test_users import make_advisor_headers
from test_helpers.types import FirmType

# PRD section 2.2: an error body carries exactly these three top-level members,
# and its ``meta`` carries only these two.
ERROR_ENVELOPE_KEYS = {"meta", "response_type", "data"}
ERROR_META_KEYS = {"api_request_id", "api_request_timestamp"}

# The design index's "uid=any_firm": a well-formed identifier that the role check
# at tier 2 refuses before tier 3 would ever resolve it.
ANY_FIRM_ID = NON_EXISTENT_UUID

# A sequence number below PRD section 3.2's floor of one, sent alone so the body
# also omits every other required field of a maturity tranche.
MALFORMED_SEQUENCE_NUMBER = SEQUENCE_NUMBER_MIN - 1


def _assert_uniform_error_envelope(response, expected_error_id):
    """Assert PRD section 2.2's error envelope, then return ``data``.

    ``validate_error`` already pins ``response_type``, the ``error_id`` and the
    non-empty ``message``, and cross-checks the documented HTTP status. What is
    added here is the shape of the body around them: no top-level ``error_id``,
    nothing outside the envelope's three members, and no traceback leaking
    through the human-readable message.
    """
    error = validate_error(response, expected_error_id)
    body = response.json()
    assert set(body) == ERROR_ENVELOPE_KEYS, f"error envelope members: {sorted(body)}"
    assert "error_id" not in body, "error_id must live under data, not at the top level"
    assert set(body["meta"]) == ERROR_META_KEYS, f"error meta: {sorted(body['meta'])}"
    assert body["response_type"] == "error"
    assert error["message"].strip()
    assert "Traceback (most recent call last)" not in error["message"]
    return error


def _issuer_body_missing_entity_type():
    """A registration body that omits the required ``entity_type``."""
    payload = f.issuer_payload()
    payload.pop("entity_type")
    return payload


def _tranche_body_below_the_sequence_floor():
    """The design index's garbage body: one out-of-range field and nothing else."""
    return {"sequence_number": MALFORMED_SEQUENCE_NUMBER}


def test_role_refusal_carries_the_uniform_error_envelope(client):
    """PRD section 2.1: "If both headers are present but the declared role is not among the roles authorised for the target endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/every_error_response_carries_a_uniform_envelope
    """
    # Firm registration is the ComplianceOfficer's alone, so a MunicipalAdvisor
    # is refused at tier 2 against an otherwise perfectly valid body.
    response = client.create_firm(
        f.firm_payload(FirmType.UNDERWRITER), make_advisor_headers(ANY_FIRM_ID)
    )
    error = _assert_uniform_error_envelope(response, ERR_UNAUTHORIZED)
    assert error["error_id"] == ERR_UNAUTHORIZED
    assert response.status_code == 403


def test_path_miss_carries_the_uniform_error_envelope(client, compliance):
    """PRD section 2.5: "On every endpoint with a path parameter, the identifier in the path names an existing row of the expected entity."

    Design: Corner/errors/every_error_response_carries_a_uniform_envelope
    """
    # An empty database, so no identifier resolves: the refusal is the entity's
    # own not-found error and not a bare 500.
    response = client.get_issuer(NON_EXISTENT_UUID, compliance)
    error = _assert_uniform_error_envelope(response, ERR_ISSUER_NOT_FOUND)
    assert error["error_id"] == ERR_ISSUER_NOT_FOUND
    assert response.status_code == 404


def test_schema_refusal_carries_the_uniform_error_envelope(client, compliance):
    """PRD section 3.1: "Registering a governmental issuer is open to an `IssuerOfficial`, a `MunicipalAdvisor`, or a `ComplianceOfficer`, and takes the issuer's legal `name` (one to one hundred sixty characters, not blank), its two-letter `state_code` (exactly two uppercase letters), and its `entity_type`, which is one of `CITY`, `COUNTY`, `SCHOOL_DISTRICT`, `AUTHORITY`, or `STATE`."

    Design: Corner/errors/every_error_response_carries_a_uniform_envelope
    """
    body = _issuer_body_missing_entity_type()
    assert "entity_type" not in body

    # The acting role is authorised and there is no path to resolve, so the
    # missing required field at tier 5 is the first violated tier.
    response = client.create_issuer(body, compliance)
    error = _assert_uniform_error_envelope(response, ERR_INVALID_REQUEST)
    assert error["error_id"] == ERR_INVALID_REQUEST
    assert response.status_code == 422


def test_unknown_deal_in_the_path_beats_the_invalid_tranche_body(client):
    """PRD section 2.10: "The same precedence governs creation: when a child is created under a parent, the parent's existence is established before any field of the child is examined, and before any business rule of the child is evaluated."

    Design: Corner/errors/path_existence_error_precedes_the_body_schema_error
    """
    ctx = fx.draft_deal(client, tranches=False)

    # Wrong in both dimensions: an unknown parent in the path and a body that is
    # missing every required field but one, which is itself out of range.
    response = client.create_maturity_tranche(
        NON_EXISTENT_UUID, _tranche_body_below_the_sequence_floor(), ctx.advisor_headers
    )
    error = validate_error(response, ERR_DEAL_NOT_FOUND)
    assert error["error_id"] != ERR_INVALID_REQUEST
    assert response.status_code == 404
    assert ctx.deal_id != NON_EXISTENT_UUID


def test_the_same_tranche_body_on_a_real_deal_reports_the_schema_error(client, compliance):
    """PRD section 2.5: "On every endpoint that accepts a body: every required field is present and non-null, every field matches its declared type, every enum field carries a listed member, every string satisfies its length bounds, every number satisfies its range bounds, every datetime is a valid ISO 8601 UTC instant, and no unknown top-level field is present."

    Design: Corner/errors/path_existence_error_precedes_the_body_schema_error
    """
    ctx = fx.draft_deal(client, tranches=False)
    assert MALFORMED_SEQUENCE_NUMBER < SEQUENCE_NUMBER_MIN

    # With tier 4 satisfied the very same body is shown to be schema-invalid.
    response = client.create_maturity_tranche(
        ctx.deal_id, _tranche_body_below_the_sequence_floor(), ctx.advisor_headers
    )
    error = validate_error(response, ERR_INVALID_REQUEST)
    assert error["error_id"] != ERR_DEAL_NOT_FOUND
    assert response.status_code == 422

    # Neither refusal wrote a maturity onto the deal.
    tranches, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, compliance)
    )
    assert tranches == []
    assert_pagination(meta, total_count=0, has_more=False)
