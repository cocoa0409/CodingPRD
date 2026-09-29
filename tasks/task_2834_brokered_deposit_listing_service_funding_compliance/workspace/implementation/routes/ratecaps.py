from flask import Blueprint

import calc
import db
import middleware as mw
import response
from errors import ApiError

bp = Blueprint("ratecaps", __name__)

READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


@bp.post("/national-rate-caps")
def publish_rate_cap():
    user_id, _role = mw.auth("SystemAdmin")
    data = mw.body()
    bucket = mw.req_enum(data, "tenor_bucket", calc.TENOR_BUCKETS)
    published = mw.req_int(data, "published_national_rate_bps", minimum=0)
    effective_date = mw.req_date(data, "effective_date")
    for existing in db.national_rate_caps.values():
        if (existing["tenor_bucket"] == bucket
                and existing["effective_date"] == effective_date):
            raise ApiError("ERR_DUPLICATE_KEY",
                           "A publication for that tenor bucket and effective date exists.")
    record = {
        "tenor_bucket": bucket,
        "published_national_rate_bps": published,
        "effective_date": effective_date,
        "cap_bps": published + calc.NATIONAL_SPREAD_BPS,
        "non_maturity_cap_bps": published + calc.NON_MATURITY_SPREAD_BPS,
        "published_by_user_id": user_id,
    }
    db.stamp_new(record, versioned=False)
    db.national_rate_caps[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/national-rate-caps")
def list_rate_caps():
    mw.auth(*READ_ROLES)
    limit, offset = mw.page()
    rows = list(db.national_rate_caps.values())
    bucket = mw.q("tenor_bucket")
    if bucket is not None:
        rows = [r for r in rows if r["tenor_bucket"] == bucket]
    as_of = mw.q("as_of_date") or mw.q("as_of") or mw.q("effective_date")
    if as_of is not None:
        rows = [r for r in rows if r["effective_date"] <= as_of]
    rows.sort(key=lambda r: (r["effective_date"], r["created_at"], r["_seq"]), reverse=True)
    return response.listing(db.public_list(rows), limit, offset)
