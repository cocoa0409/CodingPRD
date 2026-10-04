"""Component substitution requests: decision, implementation guards, OCC.

Covers the state guard on implementation (certification must be ACTIVE), the
re-pinning side effects of a successful implementation, the terminal REJECTED
state of a request, and the ordering of the optimistic-concurrency check ahead
of the state check.
"""

from test_helpers import (
    ApiErrorId,
    create_substitution_request,
    decide_substitution,
    implement_substitution,
    make_manufacturer_rep_headers,
    refresh_certification,
    reinstate_certification,
    setup_approved_substitution,
    setup_certified,
    substitution_implement_payload,
    suspend_certification,
    validate_error,
    validate_paginated,
)


def test_substitution_implement_blocked_while_certification_suspended(api, officer_headers):
    """PRD §3.5: "Implementation is the manufacturer's act, moving an `APPROVED`
    request to `IMPLEMENTED`, and it is guarded twice: the certification must
    still be `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`), and the request must
    carry `expected_certification_version` matching the certification's current
    `version` per §2.7, with a mismatch rejected as `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Difficulty/cross_entity_state_dependency/substitution_implement_blocked_while_certification_suspended
    """
    ctx = setup_approved_substitution(api)
    cert_id = ctx["certification"]["id"]
    sub_id = ctx["substitution_request"]["id"]
    mfr_id = ctx["manufacturer"]["id"]

    suspend_certification(api, cert_id, reason="Surveillance hold")
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "SUSPENDED"

    response = api.implement_substitution_request(
        sub_id,
        substitution_implement_payload(certification["version"]),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)

    requests, _meta = validate_paginated(
        api.list_substitution_requests(cert_id, officer_headers)
    )
    request = next(r for r in requests if r["id"] == sub_id)
    assert request["status"] == "APPROVED", (
        "a rejected implementation leaves the request APPROVED"
    )


def test_substitution_implement_after_reinstate_repins_construction(api, officer_headers):
    """PRD §3.5: "On success, the system freezes a new construction-record
    revision on the certification's project — the pinned `components` with the
    substituted slot replaced by the `proposed_component` — superseding the
    previously `FROZEN` revision; the certification re-pins
    `construction_record_id` and `construction_record_revision` to the new
    revision; the certification's `permitted_variations` gains an entry for the
    slot listing the `proposed_component`'s `part_number` as an allowed
    alternate; and the certification's `version` increments by 1, the standard
    mutation bump of this write."
    PRD §3.9: "On reinstatement the certification returns to `ACTIVE`, its
    `suspension_causes` are cleared"

    Design: Difficulty/cross_entity_state_dependency/substitution_implement_blocked_while_certification_suspended
    """
    ctx = setup_approved_substitution(api)
    cert_id = ctx["certification"]["id"]
    sub_id = ctx["substitution_request"]["id"]
    mfr_id = ctx["manufacturer"]["id"]

    suspend_certification(api, cert_id, reason="Surveillance hold")
    certification = refresh_certification(api, cert_id)
    blocked = api.implement_substitution_request(
        sub_id,
        substitution_implement_payload(certification["version"]),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(blocked, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)

    reinstate_certification(api, cert_id)
    certification = refresh_certification(api, cert_id)
    implemented = implement_substitution(
        api, sub_id, mfr_id, certification["version"]
    )
    assert implemented["status"] == "IMPLEMENTED"

    certification = refresh_certification(api, cert_id)
    assert certification["construction_record_revision"] == 2
    assert {
        "slot": "power_supply",
        "allowed_alternates": ["MW-RS-25-PRO"],
    } in certification["permitted_variations"]

    records, _meta = validate_paginated(
        api.list_construction_records(ctx["project"]["id"], officer_headers)
    )
    by_revision = {record["revision_no"]: record for record in records}
    assert by_revision[1]["status"] == "SUPERSEDED"
    assert by_revision[2]["status"] == "FROZEN"
    replacement = next(
        c for c in by_revision[2]["components"] if c["slot"] == "power_supply"
    )
    assert replacement["part_number"] == "MW-RS-25-PRO"


def test_substitution_decide_reject_is_terminal_for_implement(api, officer_headers):
    """PRD §3.5: "Either way, `decided_by` and `decided_on` are recorded, and
    the request moves to `APPROVED` or `REJECTED` — the latter terminal."
    PRD §2.8: "an entity already in a terminal state — `REJECTED`, `WITHDRAWN`,
    `EXPIRED`, `VOIDED`, `IMPLEMENTED`, or `EVALUATED_FAIL` — rejects all
    further transitions with `ERR_ALREADY_TERMINAL`"

    Design: Corner/endpoints/substitution_decide_reject_is_terminal_for_implement
    """
    ctx = setup_certified(api)
    cert_id = ctx["certification"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    request = create_substitution_request(
        api,
        cert_id,
        mfr_id,
        slot="power_supply",
        proposed_component={
            "component_name": "Generic PSU",
            "material": "n/a",
            "part_number": "GEN-25",
            "rating": "100-240VAC",
        },
        rationale="Cost reduction",
    )
    request = decide_substitution(
        api, request["id"], "REJECT", note="Unlisted component family"
    )
    assert request["status"] == "REJECTED"

    response = api.implement_substitution_request(
        request["id"],
        substitution_implement_payload(ctx["certification"]["version"]),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)

    records, _meta = validate_paginated(
        api.list_construction_records(ctx["project"]["id"], officer_headers)
    )
    assert len(records) == 1
    assert records[0]["revision_no"] == 1
    assert records[0]["status"] == "FROZEN", (
        "a rejected request never freezes a new revision"
    )


def test_occ_stale_certification_version_checked_before_state_returns_412(
    api, officer_headers
):
    """PRD §2.8: "Every request is validated against an ordered pipeline, and a
    failure at an earlier stage produces that stage's error rather than a later
    stage's."
    PRD §2.7: "Implementing an approved substitution request (`POST
    /certification/substitution-requests/{id}/implement`) requires the request
    to carry `expected_certification_version`, the `version` of the
    certification as the client last observed it."
    PRD §2.7: "If the supplied value does not match the parent entity's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    no mutation occurs."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_certification_version_checked_before_state_returns_412
    """
    ctx = setup_approved_substitution(api)
    cert_id = ctx["certification"]["id"]
    sub_id = ctx["substitution_request"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    stale_version = ctx["certification"]["version"]

    # The suspend both makes the version stale and the state inadmissible; the
    # OCC stage runs first, so the 412 must win over ERR_CERTIFICATION_NOT_ACTIVE.
    suspend_certification(api, cert_id, reason="Surveillance hold")
    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "SUSPENDED"
    assert certification["version"] == stale_version + 1

    response = api.implement_substitution_request(
        sub_id,
        substitution_implement_payload(stale_version),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    requests, _meta = validate_paginated(
        api.list_substitution_requests(cert_id, officer_headers)
    )
    request = next(r for r in requests if r["id"] == sub_id)
    assert request["status"] == "APPROVED", "no mutation may occur on a 412"
