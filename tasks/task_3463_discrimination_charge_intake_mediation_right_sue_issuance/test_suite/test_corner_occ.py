"""Corner queue: cross-cutting optimistic-concurrency claims (412s)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    amend_charge_payload,
    make_charging_party_headers,
    make_respondent_rep_headers,
    read_charge,
    setup_conciliation,
    setup_docketed_charge,
    table_offer,
    table_offer_payload,
    validate_error,
    validate_ok,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]


def test_amend_stale_version_returns_412(api):
    """PRD section 2.7: "Amending a charge (`POST /eeoc/charges/{id}/amend`) requires the non-optional field `expected_charge_version`, carrying the client's last observed `version` of the target `Charge`. If another writer has advanced the charge's version since the client last read it, the amendment is rejected with `ERR_STALE_VERSION`, because a later amendment legitimately supersedes earlier factual allegations and a stale client would otherwise silently overwrite edits it never observed."

    Design: Corner/cross_cutting_layers/amend_stale_version_returns_412
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    party = make_charging_party_headers(charge["complainant_id"])
    stale_version = charge["version"]

    # First amend succeeds and advances the version.
    first = validate_ok(
        api_client.amend_charge(
            charge["id"],
            amend_charge_payload(expected_charge_version=stale_version,
                                 harm_description="first amendment"),
            party,
        )
    )
    assert first["version"] == stale_version + 1

    # Second amend carrying the stale version: rejected 412, strictly
    # sequential — no concurrency required.
    stale = api_client.amend_charge(
        charge["id"],
        amend_charge_payload(expected_charge_version=stale_version,
                             harm_description="stale amendment"),
        party,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert read_charge(charge["id"])["harm_description"] == "first amendment"


def test_offer_stale_version_returns_412(api):
    """PRD section 2.7: "Tabling a conciliation offer (`POST /eeoc/conciliation-processes/{id}/offers`) requires the non-optional field `expected_conciliation_version`, carrying the client's last observed `version` of the `ConciliationProcess`. A mismatch with the process's current version is rejected with `ERR_STALE_VERSION`, because a newer offer changes `current_offer_cents` and `last_offer_by` without changing the negotiation's status, so a stale view is otherwise undetectable and would silently displace the newest offer."

    Design: Corner/cross_cutting_layers/offer_stale_version_returns_412
    """
    base = setup_conciliation(
        cause_components={
            "back_pay_cents": 100_000, "front_pay_cents": 0,
            "compensatory_damages_cents": 0, "punitive_damages_cents": 0,
            "harm_start_date": "2026-06-01",
        },
        investigator_user_id="inv-037",
        director_user_id="dir-011",
    )
    charge = base["charge"]
    conciliation = base["conciliation"]
    stale_version = conciliation["version"]

    # The first offer (COMMISSION) succeeds and advances the version.
    offer = table_offer(conciliation, 200_000, "COMMISSION", charge,
                        director_user_id="dir-011")
    assert offer["version"] == stale_version + 1

    # The respondent's counter-offer carries the pre-offer version: even
    # though the turn alternation would allow RESPONDENT next, the stale
    # version loses first.
    stale = api_client.table_offer(
        conciliation["id"],
        table_offer_payload(amount_cents=150_000,
                            expected_conciliation_version=stale_version),
        make_respondent_rep_headers(charge["employer_id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    unchanged = validate_ok(
        api_client.get_conciliation_process(conciliation["id"], _DIRECTOR)
    )
    assert unchanged["current_offer_cents"] == 200_000
    assert unchanged["last_offer_by"] == "COMMISSION"
