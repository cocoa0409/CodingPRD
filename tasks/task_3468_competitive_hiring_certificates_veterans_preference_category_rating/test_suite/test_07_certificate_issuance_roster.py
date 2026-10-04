"""Certificate issuance: roster size boundary, announcement-state gate,
referral cascade, whole-category merging, preference-aware ranking, raw-score
categories, expiry date arithmetic, and the one-ACTIVE / window-overlap rules.
"""
from test_helpers import (
    HR, HM, SO, ApiErrorId,
    api_client, classify_position, create_announcement, create_draft_position,
    create_series, get_success_data, list_entries, open_announcement,
    rate_application, register_applicant, register_verified_preference_applicant,
    return_certificate_payload, screen_application, set_clock,
    setup_competitive_certificate, setup_open_announcement,
    setup_qualified_application, setup_rated_application, submit_application,
    validate_error, validate_paginated, validate_success,
)

ISSUE_CLOCK = "2026-09-15T00:00:00Z"


def test_certificate_roster_minimum_count_boundary(api):
    """PRD §3.6: "the roster opens with every candidate in the highest category
    present, and while it still holds fewer than three names and a lower
    non-empty category exists, the entire next lower category is merged in —
    never a partial category. If the final roster still falls short of three
    candidates, issuance fails with `ERR_INSUFFICIENT_ELIGIBLES` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/certificate_roster_minimum_count_boundary
    """
    ctx = setup_open_announcement()
    announcement = ctx["announcement"]
    rated = []
    for _ in range(3):
        rated.append(setup_qualified_application(announcement)[1])

    rate_application(rated[0]["id"], 5, 5, 5)  # 100
    rate_application(rated[1]["id"], 5, 3, 5)  # 98
    # Exactly two RATED candidates when the announcement closes.
    get_success_data(api_client.close_announcement(announcement["id"], HM))
    set_clock(ISSUE_CLOCK)
    resp = api_client.issue_certificate(announcement["id"], HR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ELIGIBLES)

    # Rating the third candidate reaches the boundary: 3 succeeds where 2 failed.
    rate_application(rated[2]["id"], 3, 5, 5)  # 96
    resp = api_client.issue_certificate(announcement["id"], HR)
    certificate = validate_success(resp, 201)
    assert certificate["status"] == "ACTIVE"

    entries = list_entries(certificate["id"])
    assert len(entries) == 3
    assert [e["rank_position"] for e in entries] == [1, 2, 3]

    announcement = get_success_data(api_client.get_announcement(announcement["id"], HR))
    assert announcement["status"] == "CERT_ISSUED"


def test_certificate_issuance_requires_closed_announcement(api):
    """PRD §3.6: "Issuance requires the announcement in `CLOSED` or
    `CERT_ISSUED` — anything else is `ERR_ANNOUNCEMENT_NOT_CLOSED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/certificate_issuance_requires_closed_announcement
    """
    ctx = setup_open_announcement()
    announcement = ctx["announcement"]
    # A complete rated roster while the announcement is still OPEN.
    for ratings in ((5, 5, 5), (5, 3, 5), (3, 5, 5)):
        setup_rated_application(announcement, *ratings)

    resp = api_client.issue_certificate(announcement["id"], HR)
    validate_error(resp, ApiErrorId.ERR_ANNOUNCEMENT_NOT_CLOSED)

    get_success_data(api_client.close_announcement(announcement["id"], HM))
    set_clock(ISSUE_CLOCK)
    certificate = validate_success(api_client.issue_certificate(announcement["id"], HR), 201)
    assert certificate["status"] == "ACTIVE"
    announcement = get_success_data(api_client.get_announcement(announcement["id"], HR))
    assert announcement["status"] == "CERT_ISSUED"


def test_issuance_flips_applications_to_referred(api):
    """PRD §3.6: "Every rostered application transitions to `REFERRED` and gains
    a certificate entry." and "takes `expires_at` as `issued_at` plus the
    announcement's `certificate_validity_days` days" and "the first issuance
    flips the announcement `CLOSED` → `CERT_ISSUED`."

    Design: Corner/state_machines/issuance_flips_applications_to_referred
    """
    ctx = setup_competitive_certificate()  # scores 100/98/96, validity 60 days
    certificate = ctx["certificate"]
    assert certificate["status"] == "ACTIVE"
    assert certificate["issued_at"] == ISSUE_CLOCK
    assert certificate["expires_at"] == "2026-11-14T00:00:00Z"

    entries = ctx["entries"]
    assert len(entries) == 3
    top = entries[0]
    assert top["rank_position"] == 1
    assert top["augmented_score"] == 100  # no preference: raw 100 + 0
    assert top["status"] == "REFERRED"

    referred = get_success_data(api_client.get_application(top["application_id"], HR))
    assert referred["status"] == "REFERRED"
    assert ctx["announcement"]["status"] == "CERT_ISSUED"


def test_roster_merges_whole_categories_only(api):
    """PRD §3.6: "the roster opens with every candidate in the highest category
    present, and while it still holds fewer than three names and a lower
    non-empty category exists, the entire next lower category is merged in —
    never a partial category."

    Design: Corner/calculations/roster_merges_whole_categories_only
    """
    applicants = [register_applicant() for _ in range(5)]
    ctx = setup_competitive_certificate(
        ratings_list=((5, 5, 5), (5, 3, 5), (4, 4, 4), (1, 1, 5), (5, 1, 1)),
        vacancies_count=2,
        applicants=applicants)
    # Scores: 100 BQ, 98 BQ, 94 WQ, 88 WQ, 83 QUALIFIED. BQ holds 2 (< 3), so
    # the whole WQ category merges; the QUALIFIED applicant is never referred.
    entries = ctx["entries"]
    assert len(entries) == 4
    assert [e["quality_category"] for e in entries] == [
        "BEST_QUALIFIED", "BEST_QUALIFIED", "WELL_QUALIFIED", "WELL_QUALIFIED"]
    assert entries[3]["quality_category"] == "WELL_QUALIFIED"

    gary_application = ctx["applications"][4]
    reread = get_success_data(api_client.get_application(gary_application["id"], HR))
    assert reread["status"] == "RATED", "the unmerged QUALIFIED-category applicant stays in the pool"
    resp = api_client.list_application_certificate_entries(gary_application["id"], HR)
    gary_entries, meta = validate_paginated(resp)
    assert gary_entries == [], "no certificate entry may exist for the unmerged applicant"
    assert meta["total_count"] == 0


def test_certificate_ranking_preference_precedence(api):
    """PRD §3.6: "Ranking under `CATEGORY_RATING` is lexicographic, each key
    descending unless noted: category first; then, within a category, a verified
    `TEN_POINT_CPS` entry floats to the top of that category; then
    preference-eligible entries ahead of non-eligible ones; then
    `augmented_score`; and any remaining tie falls to the earlier
    `submitted_at`, never to a record `id`."

    Design: Corner/calculations/certificate_ranking_preference_precedence
    """
    carol = register_verified_preference_applicant("TEN_POINT_CPS")
    dave = register_verified_preference_applicant("FIVE_POINT")
    frank = register_applicant()
    ctx = setup_competitive_certificate(
        ratings_list=((3, 5, 5), (5, 3, 5), (5, 5, 5)),
        vacancies_count=1,
        applicants=[carol, dave, frank])
    # Raw scores 96 / 98 / 100, all BEST_QUALIFIED. CPS float lifts carol above
    # the category; the preference group then outranks frank's higher raw score.
    entries = ctx["entries"]
    carol_app, dave_app, frank_app = ctx["applications"]

    assert [e["application_id"] for e in entries] == [
        carol_app["id"], dave_app["id"], frank_app["id"]]
    assert [e["rank_position"] for e in entries] == [1, 2, 3]

    assert entries[0]["preference_eligible"] is True
    assert entries[0]["preference_points"] == 10
    assert entries[0]["augmented_score"] == 106  # 96 + 10
    assert entries[1]["preference_eligible"] is True
    assert entries[1]["preference_points"] == 5
    assert entries[1]["augmented_score"] == 103  # 98 + 5
    assert entries[2]["preference_eligible"] is False
    assert entries[2]["preference_points"] == 0
    assert entries[2]["augmented_score"] == 100  # highest raw score, still rank 3


def test_category_uses_raw_score_never_augmented(api):
    """PRD §3.5: "One rule outranks preference throughout the rating machinery:
    categories are computed from the raw score alone, and veterans preference
    points never move an applicant between categories."

    Design: Corner/calculations/category_uses_raw_score_never_augmented
    """
    dave = register_applicant()
    frank = register_applicant()
    carol = register_verified_preference_applicant("TEN_POINT_CPS")
    ctx = setup_competitive_certificate(
        ratings_list=((5, 5, 5), (5, 3, 5), (4, 4, 4)),
        vacancies_count=2,
        applicants=[dave, frank, carol])
    # dave 100 BQ, frank 98 BQ; BQ holds 2 (< 3) so carol 94 WQ merges in.
    entries = ctx["entries"]
    dave_app, frank_app, carol_app = ctx["applications"]

    assert [e["application_id"] for e in entries] == [
        dave_app["id"], frank_app["id"], carol_app["id"]]
    carol_entry = entries[2]
    assert carol_entry["quality_category"] == "WELL_QUALIFIED", (
        "94 < bq_cut 95 keeps carol WELL_QUALIFIED even though augmented_score is 104")
    assert carol_entry["augmented_score"] == 104  # 94 raw + 10 preference
    assert carol_entry["preference_points"] == 10
    assert carol_entry["preference_eligible"] is True
    # CPS float applies within carol's own category only: she stays below both BQ.
    assert carol_entry["rank_position"] == 3


def test_certificate_expiry_date_arithmetic(api):
    """PRD §3.6: "takes `expires_at` as `issued_at` plus the announcement's
    `certificate_validity_days` days — a closed interval per §2.9 — starts its
    `extension_count` at 0, and is born `ACTIVE`".

    Design: Corner/calculations/certificate_expiry_date_arithmetic
    """
    # Two announcements on two positions of one series (identical periods on
    # the SAME position would collide under the sibling-overlap rule; the
    # asserted date arithmetic and the per-announcement window scope are
    # unchanged). Clock moves monotonically across both pipelines.
    series = create_series()

    def build_announcement(validity_days):
        position = classify_position(create_draft_position(series["id"])["id"])
        announcement = create_announcement(
            position["id"], certificate_validity_days=validity_days)
        open_announcement(announcement["id"])
        return announcement

    ann60 = build_announcement(60)
    ann45 = build_announcement(45)

    set_clock("2026-09-10T00:00:00Z")
    apps60 = [submit_application(ann60, register_applicant()) for _ in range(3)]
    apps45 = [submit_application(ann45, register_applicant()) for _ in range(3)]

    set_clock("2026-09-14T00:00:00Z")
    for application in apps60 + apps45:
        screen_application(application["id"])
        rate_application(application["id"], 5, 5, 5)

    get_success_data(api_client.close_announcement(ann60["id"], HM))
    get_success_data(api_client.close_announcement(ann45["id"], HM))

    set_clock(ISSUE_CLOCK)
    cert60 = validate_success(api_client.issue_certificate(ann60["id"], HR), 201)
    cert45 = validate_success(api_client.issue_certificate(ann45["id"], HR), 201)

    assert cert60["issued_at"] == ISSUE_CLOCK
    assert cert60["expires_at"] == "2026-11-14T00:00:00Z"  # 2026-09-15 + 60 days
    assert cert60["status"] == "ACTIVE"
    assert cert45["issued_at"] == ISSUE_CLOCK
    assert cert45["expires_at"] == "2026-10-30T00:00:00Z"  # 2026-09-15 + 45 days
    assert cert45["status"] == "ACTIVE"


def test_second_certificate_while_active_rejected(api):
    """PRD §3.6: "it is barred while another certificate of the same
    announcement is still `ACTIVE`, a block reported as
    `ERR_ACTIVE_CERTIFICATE_EXISTS` (HTTP 409)".
    PRD §2.7: "an `ACTIVE` certificate always overlaps its own window — the
    rejection is `ERR_ACTIVE_CERTIFICATE_EXISTS`, never
    `ERR_CERTIFICATE_WINDOW_OVERLAP`."

    Design: Corner/validations/second_certificate_while_active_rejected
    """
    ctx = setup_competitive_certificate()
    announcement = ctx["announcement"]

    set_clock("2026-09-16T00:00:00Z")
    resp = api_client.issue_certificate(announcement["id"], HR)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_CERTIFICATE_EXISTS)

    resp = api_client.list_announcement_certificates(announcement["id"], HR)
    certificates, meta = validate_paginated(resp)
    assert len(certificates) == 1
    assert meta["total_count"] == 1


def test_certificate_window_closed_interval_adjacency(api):
    """PRD §2.9: "The interval from `issued_at` to `expires_at` is closed,
    inclusive of both ends: a new issuance whose `issued_at` falls on or before
    any prior certificate's `expires_at` on the same announcement conflicts —
    adjacency is a conflict here, unlike announcement periods — and is rejected
    with `ERR_CERTIFICATE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/certificate_window_closed_interval_adjacency
    """
    ctx = setup_competitive_certificate()  # window [2026-09-15, 2026-11-14]
    announcement, certificate = ctx["announcement"], ctx["certificate"]
    assert certificate["expires_at"] == "2026-11-14T00:00:00Z"

    set_clock("2026-09-20T00:00:00Z")
    returned = validate_success(
        api_client.return_certificate(
            certificate["id"],
            return_certificate_payload(reason="no suitable candidate"),
            SO),
        200)
    assert returned["status"] == "RETURNED"

    # Reissuing at exactly the prior expires_at conflicts (closed interval).
    set_clock("2026-11-14T00:00:00Z")
    resp = api_client.issue_certificate(announcement["id"], HR)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP)

    # One day later the window is clear; issuance succeeds.
    set_clock("2026-11-15T00:00:00Z")
    cert2 = validate_success(api_client.issue_certificate(announcement["id"], HR), 201)
    assert cert2["status"] == "ACTIVE"
    assert cert2["issued_at"] == "2026-11-15T00:00:00Z"
    assert cert2["expires_at"] == "2027-01-14T00:00:00Z"  # + 60 days
