"""Queue B — endpoints: full side-effect sets on issuance, the logical-clock
startup default, and the list pagination contract.
"""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ADMIN,
    api_client,
    assert_certification,
    create_approved_exam_application,
    create_candidate,
    create_level,
    create_program,
    create_state_policy,
    create_verified_completion,
    setup_certified_candidate,
    validate_paginated,
)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_issue_endpoint_full_side_effects(api):
    """PRD §3.5: "The new certification is born `ACTIVE`, storing the basis trio
    as `basis_completion_record_id`, `basis_attempt_id`, and
    `basis_psychomotor_id`, with `issued_on` at the issuance instant,
    `expires_on` exactly twenty-four calendar months later, a `lapse_deadline`
    forty-eight calendar months beyond expiry, and `renewed_count` at zero."

    Issue at the 2026-09-04 logical instant: expiry 2028-09-04, lapse deadline
    2032-09-04.

    Design: Corner/endpoints/issue_endpoint_full_side_effects
    """
    ctx = setup_certified_candidate()
    cert = ctx["certification"]
    assert_certification(cert)
    assert cert["status"] == "ACTIVE"
    assert isinstance(cert["version"], int) and cert["version"] >= 1
    assert cert["renewed_count"] == 0
    assert _ts(cert["issued_on"]) == _ts("2026-09-04T00:00:00Z")
    assert _ts(cert["expires_on"]) == _ts("2028-09-04T00:00:00Z"), (
        f"expires_on is twenty-four calendar months after issue, got {cert['expires_on']}"
    )
    assert _ts(cert["lapse_deadline"]) == _ts("2032-09-04T00:00:00Z"), (
        f"lapse_deadline is forty-eight months beyond expiry, got {cert['lapse_deadline']}"
    )
    assert cert["basis_completion_record_id"] == ctx["completion_record"]["id"]
    assert cert["basis_attempt_id"] == ctx["attempt"]["id"]
    assert cert["basis_psychomotor_id"] == ctx["psychomotor"]["id"]


def test_clock_default_is_2026_09_01(api):
    """PRD §2.5: "Before any call, the logical clock stands at exactly
    2026-09-01T00:00:00Z, and it must never fall back to wall-clock time."
    PRD §3.4: "Approval mints an **authorization to test**: `issued_on` at the
    approval instant, `expires_on` ninety calendar days later, status
    `ISSUED`".

    With no clock call anywhere in the chain, the minted authorization's
    issued_on proves the startup default.

    Design: Corner/endpoints/clock_default_is_2026_09_01
    """
    # The entire chain runs without ever calling the clock endpoint.
    level = create_level()
    candidate = create_candidate()
    program = create_program(level["id"])
    record = create_verified_completion(candidate["id"], program)
    application = create_approved_exam_application(
        candidate["id"], level["id"], record["id"],
    )

    resp = api_client.list_authorizations_to_test(
        ADMIN, params={"exam_application_id": application["id"]},
    )
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    att = data[0]
    assert _ts(att["issued_on"]) == _ts("2026-09-01T00:00:00Z"), (
        f"the ATT minted without any clock call proves the startup default, "
        f"got {att['issued_on']}"
    )
    assert _ts(att["expires_on"]) == _ts(att["issued_on"]) + timedelta(days=90)


def test_pagination_limit_offset(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The
    `offset` parameter states how many items to skip and defaults to 0. Unless
    otherwise specified, every list endpoint returns resources sorted by
    creation timestamp in ascending order, and the `meta` object of a list
    response carries the four pagination fields `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_limit_offset
    """
    create_state_policy(state_code="OR", adoption_mode="NREMT_ACCEPTED",
                        accepted_level_codes=["EMT"], base_license_fee_cents=12000)
    create_state_policy()  # WA (the default payload)
    create_state_policy(state_code="TX", adoption_mode="STATE_EXAM",
                        base_license_fee_cents=10000, state_exam_fee_cents=2500)

    page1, meta1 = validate_paginated(
        api_client.list_state_adoption_policies(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0
    assert [p["state_code"] for p in page1] == ["OR", "WA"], "ascending creation order"

    page2, meta2 = validate_paginated(
        api_client.list_state_adoption_policies(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page2[0]["state_code"] == "TX"
