"""Path-parameter and foreign-key resolution (PRD 2.9 rules 3 and 4)."""
from errors import ApiError
from store import db

_TABLES = {
    "Agency": ("agencies", "ERR_AGENCY_NOT_FOUND"),
    "Officer": ("officers", "ERR_OFFICER_NOT_FOUND"),
    "Resident": ("residents", "ERR_RESIDENT_NOT_FOUND"),
    "Device": ("devices", "ERR_DEVICE_NOT_FOUND"),
    "RequestArea": ("request_areas", "ERR_REQUEST_AREA_NOT_FOUND"),
    "VideoRequest": ("video_requests", "ERR_VIDEO_REQUEST_NOT_FOUND"),
    "ConsentSolicitation": ("solicitations", "ERR_SOLICITATION_NOT_FOUND"),
    "SharedClip": ("clips", "ERR_SHARED_CLIP_NOT_FOUND"),
    "ResidentPost": ("posts", "ERR_POST_NOT_FOUND"),
    "ModerationCase": ("cases", "ERR_MODERATION_CASE_NOT_FOUND"),
    "TransparencyReport": ("reports", "ERR_TRANSPARENCY_REPORT_NOT_FOUND"),
}


def table(kind):
    return getattr(db, _TABLES[kind][0])


def find(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return table(kind).get(row_id)


def must(kind, row_id):
    row = find(kind, row_id)
    if row is None:
        raise ApiError(_TABLES[kind][1], "%s %s does not exist" % (kind, row_id))
    return row
