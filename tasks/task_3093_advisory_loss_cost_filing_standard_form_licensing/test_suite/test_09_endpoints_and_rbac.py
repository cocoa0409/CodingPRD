"""Endpoint corners: conditional insurer withdrawal, adoption ownership
withdraw, list filtering, and RBAC denials on action endpoints (PRD §2.1,
§3.1, §3.3, §3.4, §4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_cell_payload,
    create_filing_payload,
    get_success_data,
    make_agreement,
    make_insurer,
    make_adoption,
    setup_adoption_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    make_insurer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


def test_insurer_withdraw_membership_blocked_by_active_agreement(api):
    """PRD §3.1: "Membership withdrawal is terminal — `insurer_status` becomes
    `WITHDRAWN` — and is permitted from either `ACTIVE` or `SUSPENDED`, but
    only when the insurer holds zero license agreements in `ACTIVE` status and
    zero adoptions in `PENDING` or `AUTHORIZED` status; withdrawal from a
    non-eligible state fails with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/insurer_withdraw_membership_blocked_by_active_agreement
    """
    insurer = make_insurer()
    make_agreement(insurer["id"])
    resp = api.withdraw_membership(insurer["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_insurer(insurer["id"], ADMIN))
    assert after["insurer_status"] == "ACTIVE"


def test_adoption_withdraw_by_insurer_user_ownership(api):
    """PRD §3.4: "An insurer may walk away from its own adoption: withdrawal
    by an `InsurerUser` requires `X-User-ID` to equal the adoption's
    `insurer_id`, and is permitted from `PENDING` or from `AUTHORIZED`,
    landing the adoption in `WITHDRAWN`."
    PRD §2.1: "When `X-User-Role` is `InsurerUser`, `X-User-ID` is the `id` of
    the acting `MemberInsurer`. Ownership checks on any resource that
    references a member insurer — for example, withdrawing an adoption —
    compare the resource's `insurer_id` to `X-User-ID`."

    Design: Corner/endpoints/adoption_withdraw_by_insurer_user_ownership
    """
    scenario = setup_adoption_scenario(
        multiplier_pct=110,
        filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
    )
    resp = api.withdraw_adoption(
        scenario["adoption"]["id"], make_insurer_headers(scenario["insurer"]["id"])
    )
    adoption = validate_success(resp)
    assert adoption["adoption_status"] == "WITHDRAWN"


def test_filings_list_filter_by_state_and_status(api):
    """PRD §3.3: "Filings can be listed filtered by `state_code`,
    `line_of_business`, `filing_status`, or `supersedes_filing_id`."
    PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0."

    Design: Corner/endpoints/filings_list_filter_by_state_and_status
    """
    f_tx = get_success_data(api.create_filing(
        create_filing_payload(filing_code="LC-TX-CP-130", state_code="TX",
                              effective_date="2027-01-01T00:00:00Z"), ADMIN
    ))
    f_ca = get_success_data(api.create_filing(
        create_filing_payload(filing_code="LC-CA-CP-131", state_code="CA",
                              effective_date="2027-01-01T00:00:00Z"), ADMIN
    ))
    rows, meta = validate_paginated(
        api.list_filings(ACTUARY, params={"state_code": "TX", "filing_status": "DRAFT"})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == f_tx["id"]
    rows2, meta2 = validate_paginated(
        api.list_filings(ACTUARY, params={"state_code": "CA"})
    )
    assert len(rows2) == 1
    assert rows2[0]["id"] == f_ca["id"]


def test_insurer_user_cannot_authorize_own_adoption(api):
    """PRD §2.1: "A caller whose role is recognized but not permitted for the
    requested endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST `/bureau/adoptions/{id}/authorize` | Authorize or
    band-reject an adoption | BureauAdmin".

    Design: Corner/roles/insurer_user_cannot_authorize_own_adoption
    """
    scenario = setup_adoption_scenario(
        multiplier_pct=110,
        filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
    )
    resp = api.authorize_adoption(
        scenario["adoption"]["id"], make_insurer_headers(scenario["insurer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    adoption = validate_success(api.get_adoption(scenario["adoption"]["id"], ADMIN))
    assert adoption["adoption_status"] == "PENDING"


def test_bureau_actuary_cannot_create_cells(api):
    """PRD §2.1: "A caller whose role is recognized but not permitted for the
    requested endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST `/bureau/filings/{id}/cells` | Add a loss cost cell to a
    draft filing | BureauAdmin".

    Design: Corner/roles/bureau_actuary_cannot_create_cells
    """
    filing = get_success_data(api.create_filing(
        create_filing_payload(effective_date="2027-01-01T00:00:00Z"), ADMIN
    ))
    resp = api.create_cell(filing["id"], create_cell_payload(), ACTUARY)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    rows, meta = validate_paginated(api.list_cells(filing["id"], ADMIN))
    assert rows == []
