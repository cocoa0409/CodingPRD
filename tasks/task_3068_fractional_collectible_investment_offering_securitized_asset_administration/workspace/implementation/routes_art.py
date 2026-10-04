"""Route registrations: artists, artworks, appraisals."""
from router import ROUTES, read_limit_offset
from envelope import ok, paginated
import views
import svc_artwork as svcArt


def _list(kind, rows, offset_query=True):
    if not offset_query:
        return ok([views.view(kind, r) for r in rows])
    limit, offset = read_limit_offset()
    return paginated([views.view(kind, r) for r in rows], limit, offset)


def _paged(kind, rows):
    limit, offset = read_limit_offset()
    return paginated([views.view(kind, r) for r in rows], limit, offset)


from flask import request


def artists_create():
    data, status = svcArt.create_artist()
    return ok(data, status)


def artists_get(id):
    return ok(svcArt.get_artist(id))


def artists_list():
    return _paged("artists", svcArt.list_artists(request.args))


def artworks_create():
    data, status = svcArt.create_artwork()
    return ok(data, status)


def artworks_get(id):
    return ok(svcArt.get_artwork(id))


def artworks_list():
    return _paged("artworks", svcArt.list_artworks(request.args))


def asset_reports_create(id):
    data, status = svcArt.file_asset_report(id)
    return ok(data, status)


def asset_reports_list(id):
    return _paged("asset_reports", svcArt.list_asset_reports(id, request.args))


def appraisals_create(id):
    data, status = svcArt.file_appraisal(id)
    return ok(data, status)


def appraisals_list(id):
    return _paged("appraisals", svcArt.list_appraisals(id, request.args))


ROUTES.update({
    "/api/artists": {
        "POST": (["IssuerOps", "PlatformAdmin"], artists_create),
        "GET": (["IssuerOps", "ComplianceOfficer", "PlatformAdmin"], artists_list),
    },
    "/api/artists/{id}": {
        "GET": (["IssuerOps", "ComplianceOfficer", "TransferAgent", "PlatformAdmin"],
                artists_get),
    },
    "/api/artworks": {
        "POST": (["IssuerOps", "PlatformAdmin"], artworks_create),
        "GET": (["IssuerOps", "ComplianceOfficer", "PlatformAdmin"], artworks_list),
    },
    "/api/artworks/{id}": {
        "GET": (["IssuerOps", "ComplianceOfficer", "TransferAgent", "PlatformAdmin"],
                artworks_get),
    },
    "/api/artworks/{id}/asset-reports": {
        "POST": (["IssuerOps"], asset_reports_create),
        "GET": (["IssuerOps", "ComplianceOfficer", "PlatformAdmin"], asset_reports_list),
    },
    "/api/artworks/{id}/appraisals": {
        "POST": (["IssuerOps"], appraisals_create),
        "GET": (["IssuerOps", "ComplianceOfficer", "PlatformAdmin"], appraisals_list),
    },
})