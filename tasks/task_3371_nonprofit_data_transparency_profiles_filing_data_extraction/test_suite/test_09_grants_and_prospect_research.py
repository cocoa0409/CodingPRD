"""Grant records, recipient matching and funder prospect research."""
from test_helpers import (
    create_grant,
    get_org,
    get_prospects,
    list_grants,
    make_data_consumer_headers,
    match_recipient,
    prospect_organization_id,
    scenario_funder,
    scenario_willow_creek,
    set_clock,
)


def test_grant_name_normalization_strips_legal_suffixes_before_prefix_comparison(api):
    """PRD §3.9: "Both names are then normalized: uppercased, every character that
    is not a letter A through Z or a digit 0 through 9 replaced by a space, runs of
    spaces collapsed, the result trimmed, a leading token `THE` dropped, and any
    trailing token from the set `INC`, `INCORPORATED`, `CORP`, `CORPORATION`,
    `LLC`, `LTD`, `FOUNDATION`, `FUND`, `TRUST`, `ASSOCIATION`, `SOCIETY` dropped."

    Design: Corner/calculations/grant_name_normalization_strips_legal_suffixes_before_prefix_comparison
    """
    set_clock()
    recipient = scenario_willow_creek()
    funder = scenario_funder()

    exact = create_grant(recipient["id"], funder["id"],
                         recipient_name_raw="The Willow Creek Collective Foundation Inc",
                         amount_cents=750000, fiscal_year=2025)
    prefix = create_grant(recipient["id"], funder["id"],
                          recipient_name_raw="Willow Creek Collective of Illinois",
                          amount_cents=750000, fiscal_year=2025)

    assert exact["match_score"] == 30, (
        "dropping THE, INC and FOUNDATION leaves an exact name match"
    )
    assert exact["recipient_match_status"] == "UNMATCHED", (
        "the exact-name points alone stay below the 40 AMBIGUOUS floor"
    )
    assert prefix["match_score"] == 18, (
        "the 12-character prefix rule is worth less than the exact rule"
    )
    assert prefix["recipient_match_status"] == "UNMATCHED"
    assert exact["match_score"] > prefix["match_score"]


def test_funder_prospects_rank_by_score_then_history_then_created_at(api):
    """PRD §3.9: "The ranking is a deterministic total order: `match_score`
    descending, then `historical_giving_cents` descending, then the candidate's
    `created_at` ascending. No identifier value ever participates in the ranking".
    PRD §3.9: "The response reports the `funder_organization_id`, the
    `mean_grant_amount_cents` that anchored the size band, and a `prospects` array."

    Design: Corner/calculations/funder_prospects_rank_by_score_then_history_then_created_at
    """
    set_clock()
    funder = scenario_funder(ntee_code="B82")
    willow = scenario_willow_creek()
    prairie = scenario_willow_creek(legal_name="Prairie Food Bank", ein="900100201",
                                    state_code="WI", ntee_code="B82")
    lakeshore = scenario_willow_creek(legal_name="Lakeshore Conservancy", ein="900100202",
                                      state_code="WI", ntee_code="B82")
    create_grant(willow["id"], funder["id"], recipient_name_raw="Willow Creek Collective",
                 recipient_ein="900100200", amount_cents=1000000, fiscal_year=2025,
                 subject_code="B82")

    data = get_prospects(funder["id"], subject_code="B82")
    assert isinstance(data, dict), (
        "the response reports the funder id, the mean grant amount and a prospects array"
    )
    prospects = data["prospects"]

    assert data["funder_organization_id"] == funder["id"]
    assert data["mean_grant_amount_cents"] == 1000000
    assert len(prospects) == 3, "the funder itself is excluded from its own prospect list"
    assert [prospect_organization_id(p) for p in prospects] == [
        willow["id"], prairie["id"], lakeshore["id"]]
    assert prospects[0]["match_score"] == 80, "subject 35 + history 20 + geo 25"
    assert prospects[0]["historical_giving_cents"] == 1000000
    assert prospects[1]["match_score"] == 35
    assert prospects[2]["match_score"] == 35, (
        "the two tied candidates are ordered by organization.created_at ascending"
    )


def test_funder_prospects_returns_an_empty_array_when_no_candidate_is_eligible(api):
    """PRD §3.9: "A funder with no eligible candidates receives an empty
    `prospects` array with `total_count` 0 and `has_more` false — an empty result
    is a valid answer, not an error."

    Design: Corner/calculations/funder_prospects_returns_an_empty_array_when_no_candidate_is_eligible
    """
    set_clock()
    funder = scenario_funder(ntee_code="B82")
    scenario_willow_creek(legal_name="Dormant Society", ein="900100260",
                          state_code="IL", activate=False)

    response = api.get_prospects(
        make_data_consumer_headers(funder["id"]),
        {"funder_organization_id": funder["id"], "subject_code": "B82"})
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    body = response.json()
    assert body.get("response_type") != "error", "an empty result is not an error"
    assert "error_id" not in body.get("data", {})

    assert body["data"]["prospects"] == [], (
        "only DRAFT organizations exist, so no candidate is eligible"
    )
    assert body["meta"].get("total_count") == 0
    assert body["meta"].get("has_more") is False


def test_grant_rematch_flips_ambiguous_to_matched_once_the_ein_is_supplied(api):
    """PRD §3.9: "Matching can be re-run when the funder obtains better identifying
    data. ... A supplied `recipient_ein` replaces the grant's stored `recipient_ein`".
    PRD §3.9: "The `match_score` and `recipient_match_status` are recomputed and the
    grant's `version` is incremented by 1."

    Design: Corner/endpoints/grant_rematch_flips_ambiguous_to_matched_once_the_ein_is_supplied
    """
    set_clock()
    recipient = scenario_willow_creek()
    funder = scenario_funder()
    grant = create_grant(recipient["id"], funder["id"],
                         recipient_name_raw="Willow Creek Collective",
                         amount_cents=500000, fiscal_year=2025)
    assert grant["match_score"] == 30
    assert grant["recipient_match_status"] == "UNMATCHED"

    rescore_plain = match_recipient(grant["id"], funder["id"])
    assert rescore_plain["match_score"] == 30, (
        "re-running identical inputs is deterministic and does not invent a match"
    )

    rescore_ein = match_recipient(grant["id"], funder["id"], recipient_ein="900100200")
    # PRD §3.9: the EIN lifts the score to 90 (exact name 30 + EIN 60), which is
    # MATCHED; because no subject_code was supplied and the recipient has a
    # non-null ntee_code, the grant is auto-coded to that ntee_code and the score
    # is recomputed — 90 plus the 10-point subject-code match.
    assert rescore_ein["recipient_match_status"] == "MATCHED"
    assert rescore_ein["recipient_ein"] == "900100200"
    assert rescore_ein["subject_code"] == "B82", (
        "the matched grant is auto-coded from the recipient's ntee_code"
    )
    assert rescore_ein["taxonomy_source"] == "AUTO_CODED"
    assert rescore_ein["match_score"] == 100, "exact name 30 + EIN 60 + subject 10"
    assert rescore_ein["version"] == 3, "created at 1, one bump per re-match"

    rows = list_grants(recipient["id"])
    assert len(rows) == 1, "re-matching updates the grant in place"


# ---------------------------------------------------------------------------
# Recipient-match band boundaries (difficulty instance)
# ---------------------------------------------------------------------------

def _band_setup():
    recipient = scenario_willow_creek(legal_name="Riverbend Arts Council",
                                      ein="135792468", state_code="OR", ntee_code="A26")
    funder = scenario_funder(legal_name="Harborlight Fund", ein="777888999",
                             state_code="OR")
    grants = {
        "ein_and_subject": create_grant(
            recipient["id"], funder["id"], recipient_name_raw="Riverbend Cultural Trust",
            recipient_ein="135792468", amount_cents=1000000, fiscal_year=2025,
            subject_code="A26"),
        "ein_only": create_grant(
            recipient["id"], funder["id"], recipient_name_raw="Riverbend Cultural Trust",
            recipient_ein="135792468", amount_cents=1000000, fiscal_year=2025),
        "name_and_subject": create_grant(
            recipient["id"], funder["id"], recipient_name_raw="the riverbend arts council",
            amount_cents=1000000, fiscal_year=2025, subject_code="A26"),
        "name_only": create_grant(
            recipient["id"], funder["id"], recipient_name_raw="Riverbend Arts Council",
            amount_cents=1000000, fiscal_year=2025),
    }
    return recipient, funder, grants


def test_grant_match_status_band_is_matched_at_exactly_seventy(api):
    """PRD §3.9: "A grant matching only on EIN scores 60; the same grant
    additionally matching on subject code scores 70. The `recipient_match_status`
    follows the score: `MATCHED` at 70 or above, `AMBIGUOUS` from 40 through 69
    inclusive, and `UNMATCHED` below 40."

    Design: Difficulty/boundary_precision_check/grant_match_status_band_boundary_at_scores_70_and_40
    """
    set_clock()
    recipient, funder, grants = _band_setup()

    top = grants["ein_and_subject"]
    assert top["match_score"] == 70
    assert top["recipient_match_status"] == "MATCHED", (
        "the 70 edge is inclusive"
    )

    ein_only = grants["ein_only"]
    assert ein_only["match_score"] == 60
    assert ein_only["recipient_match_status"] == "AMBIGUOUS", (
        "60 sits inside the 40..69 AMBIGUOUS band"
    )


def test_grant_match_status_band_is_ambiguous_at_exactly_forty(api):
    """PRD §3.9: "If the normalized `recipient_name_raw` equals the normalized
    `legal_name`, 30 points are added".
    PRD §3.9: "If `subject_code` is present and equals the recipient organization's
    `ntee_code`, 10 points are added."

    Design: Difficulty/boundary_precision_check/grant_match_status_band_boundary_at_scores_70_and_40
    """
    set_clock()
    recipient, funder, grants = _band_setup()

    name_and_subject = grants["name_and_subject"]
    assert name_and_subject["match_score"] == 40, (
        "the leading THE is dropped before the exact-name comparison"
    )
    assert name_and_subject["recipient_match_status"] == "AMBIGUOUS", (
        "the 40 edge is inclusive"
    )

    name_only = grants["name_only"]
    assert name_only["match_score"] == 30
    assert name_only["recipient_match_status"] == "UNMATCHED"

    assert get_org(recipient["id"])["distinct_funder_count"] == 1, (
        "all four grants come from the same funder"
    )
