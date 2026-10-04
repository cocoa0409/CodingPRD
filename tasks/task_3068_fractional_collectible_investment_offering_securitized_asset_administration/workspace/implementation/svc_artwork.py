"""Artist, artwork trust chain, appraisals (§3.1, §3.2)."""
from envelope import (ApiError, invalid_request, invalid_state, not_found, stale,
                      value_rejected)
from catalog import APPRAISAL_CADENCE_DAYS
from store import DB, parse_dt, to_ms, add_days
from models import (make_artist, make_artwork, make_asset_report, make_appraisal,
                    refresh_overview, newest_appraisal, appraisals_of,
                    insert_index)
from svc_common import body, require, as_int, enum_value, check_enum_optional, \
    body_datetime
from calc import day_gap
import views


# ---------------------------------------------------------------------------
# Artist
# ---------------------------------------------------------------------------

def create_artist():
    data = body()
    require(data, ["legal_name", "attribution_status", "nationality_country_code"])
    enum_value(data, "attribution_status", "attribution_status")
    row = make_artist(data)
    return views.artist(row), 201


def get_artist(artist_id):
    row = DB.artists.get(artist_id)
    if row is None:
        raise not_found("Artist %s does not exist." % artist_id)
    return views.artist(row)


def list_artists(query):
    status = query.get("attribution_status")
    rows = DB.ordered("artists")
    if status is not None:
        if status not in ("CONFIRMED", "DISPUTED", "UNKNOWN"):
            raise value_rejected("attribution_status carries an undeclared value.")
        rows = [r for r in rows if r["attribution_status"] == status]
    return rows


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

def create_artwork():
    data = body()
    require(data, ["title", "artist_id", "creation_year", "medium",
                   "acquisition_cost_cents", "reserve_price_cents"])
    enum_value(data, "medium", "medium")
    artist = DB.artists.get(data.get("artist_id"))
    if artist is None:
        raise not_found("Artist %s does not exist." % data.get("artist_id"))
    row = make_artwork(data)
    return views.artwork(row), 201


def get_artwork(artwork_id):
    row = DB.artworks.get(artwork_id)
    if row is None:
        raise not_found("Artwork %s does not exist." % artwork_id)
    return views.artwork(row)


def list_artworks(query):
    rows = DB.ordered("artworks")
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    artist_id = query.get("artist_id")
    if artist_id:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    return rows


# ---------------------------------------------------------------------------
# Asset reports
# ---------------------------------------------------------------------------

def _trust_chain(artwork):
    reports = [r for r in DB.asset_reports.values()
               if r["artwork_id"] == artwork["id"]]
    auth_ok = any(r["report_type"] == "AUTHENTICATION" and r["outcome"] == "VERIFIED"
                  for r in reports)
    prov_ok = any(r["report_type"] == "PROVENANCE" and r["outcome"] == "VERIFIED"
                  for r in reports)
    return auth_ok and prov_ok


def _latest_survey_grade(artwork_id):
    surveys = [r for r in DB.asset_reports.values()
               if r["artwork_id"] == artwork_id
               and r["report_type"] == "CONDITION_SURVEY"]
    if not surveys:
        return None
    surveys.sort(key=lambda r: (r["filed_at"], insert_index(r)))
    return surveys[-1].get("condition_grade")


def file_asset_report(artwork_id):
    artwork = DB.artworks.get(artwork_id)
    if artwork is None:
        raise not_found("Artwork %s does not exist." % artwork_id)
    data = body()
    require(data, ["report_type", "outcome", "firm_name"])
    rtype = enum_value(data, "report_type", "report_type")
    enum_value(data, "outcome", "asset_report_outcome")
    grade = check_enum_optional(data, "condition_grade", "condition_grade")
    if rtype == "CONDITION_SURVEY":
        if grade is None:
            raise invalid_request("condition_grade is required for a CONDITION_SURVEY.")
    elif grade is not None:
        raise invalid_request("condition_grade must be null for report_type %s." % rtype)

    report = make_asset_report(artwork, {**data, "condition_grade": grade})
    if artwork["status"] == "APPRAISED" and _trust_chain(artwork):
        artwork["status"] = "AUTHENTICATED"
        latest = _latest_survey_grade(artwork["id"])
        artwork["condition_grade"] = latest if latest else "PENDING"
    if rtype == "CONDITION_SURVEY":
        artwork["condition_grade"] = grade
    refresh_overview(artwork, bump=True)
    return views.asset_report(report), 201


def list_asset_reports(artwork_id, query):
    if artwork_id not in DB.artworks:
        raise not_found("Artwork %s does not exist." % artwork_id)
    rows = [r for r in DB.ordered("asset_reports") if r["artwork_id"] == artwork_id]
    rtype = query.get("report_type")
    if rtype:
        rows = [r for r in rows if r["report_type"] == rtype]
    return rows


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------

def file_appraisal(artwork_id):
    artwork = DB.artworks.get(artwork_id)
    if artwork is None:
        raise not_found("Artwork %s does not exist." % artwork_id)
    data = body()
    require(data, ["appraised_value_cents", "appraiser_firm", "appraisal_method"])
    value = as_int(data, "appraised_value_cents", minimum=1)
    enum_value(data, "appraisal_method", "appraisal_method")
    expected = as_int(data, "expected_artwork_version")
    if expected is not None and int(expected) != int(artwork["version"]):
        raise stale("expected_artwork_version does not match the artwork's version.")

    previous = newest_appraisal(artwork_id)
    now = to_ms(DB.now())
    if previous is not None:
        gap = day_gap(now, previous["filed_at"])
        if gap is not None and gap < APPRAISAL_CADENCE_DAYS:
            raise ApiError("ERR_APPRAISAL_CADENCE",
                           "A sibling selected appraisal was filed within the "
                           "preceding 90 days.")
    last_at = artwork.get("last_appraisal_at")
    if last_at is not None and now < last_at:
        raise ApiError("ERR_APPRAISAL_CADENCE",
                       "filed_at would precede the artwork's last appraisal.")

    row = make_appraisal(artwork, {**data, "appraised_value_cents": value})
    for sibling in DB.appraisals.values():
        if sibling["artwork_id"] == artwork_id and sibling["id"] != row["id"]:
            sibling["is_selected"] = False
    artwork["last_appraised_value_cents"] = value
    artwork["last_appraisal_at"] = row["filed_at"]
    artwork["next_appraisal_due_at"] = add_days(row["filed_at"], APPRAISAL_CADENCE_DAYS)
    refresh_overview(artwork, bump=True)
    return views.appraisal(row), 201


def list_appraisals(artwork_id, query):
    if artwork_id not in DB.artworks:
        raise not_found("Artwork %s does not exist." % artwork_id)
    rows = appraisals_of(artwork_id)
    flag = query.get("is_selected")
    if flag is not None and flag != "":
        want = str(flag).lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("is_selected")) == want]
    return rows