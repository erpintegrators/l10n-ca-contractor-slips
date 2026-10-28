# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager

PORTAL_DOMAIN = [("state", "in", ("final", "filed")), ("rpt_tcd", "in", ("O", "A", "C")), ("superseded", "=", False)]


class L10nCaSlipPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "l10n_ca_slip_count" in counters:
            Slip = request.env["l10n.ca.slip"]
            values["l10n_ca_slip_count"] = (
                Slip.search_count(self._l10n_ca_slip_domain()) if Slip.check_access_rights("read", raise_exception=False) else 0
            )
        return values

    def _l10n_ca_slip_domain(self):
        partner = request.env.user.partner_id.commercial_partner_id
        return [("partner_id", "=", partner.id)] + PORTAL_DOMAIN

    @http.route(["/my/slips", "/my/slips/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_l10n_ca_slips(self, page=1, **kw):
        Slip = request.env["l10n.ca.slip"]
        values = self._prepare_portal_layout_values()
        domain = self._l10n_ca_slip_domain()
        slips, total = Slip, 0
        if Slip.check_access_rights("read", raise_exception=False):
            total = Slip.search_count(domain)
        pager = portal_pager(url="/my/slips", total=total, page=page, step=self._items_per_page)
        if total:
            slips = Slip.search(domain, order="year desc, id desc", limit=self._items_per_page, offset=pager["offset"])
        values.update({"slips": slips, "pager": pager, "page_name": "l10n_ca_slip", "default_url": "/my/slips"})
        return request.render("l10n_ca_contractor_slips.portal_my_slips", values)

    @http.route(["/my/slips/<int:slip_id>"], type="http", auth="public", website=True)
    def portal_my_l10n_ca_slip(self, slip_id, access_token=None, report_type=None, download=False, **kw):
        try:
            slip_sudo = self._document_check_access("l10n.ca.slip", slip_id, access_token)
        except (AccessError, MissingError):
            return request.redirect("/my")
        if slip_sudo.state not in ("final", "filed") or slip_sudo.rpt_tcd not in ("O", "A", "C") or slip_sudo.superseded:
            return request.redirect("/my")
        if report_type in ("html", "pdf", "text"):
            return self._show_report(
                model=slip_sudo,
                report_type=report_type,
                report_ref="l10n_ca_contractor_slips.action_report_l10n_ca_slip",
                download=download,
            )
        values = self._get_page_view_values(
            slip_sudo, access_token, {"slip": slip_sudo, "page_name": "l10n_ca_slip"}, "my_slips_history", False, **kw
        )
        return request.render("l10n_ca_contractor_slips.portal_slip_page", values)
