# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, models


class ReportL10nCaSlip(models.AbstractModel):
    """The printed slip. A report action that carries options (two copies, DUPLICATE) reaches the
    report controller with no record ids in its URL, because Odoo's web client sends the options in
    their place. The print actions put the slip ids in the options, and the slips are read from
    there when the URL has none."""

    _name = "report.l10n_ca_contractor_slips.report_l10n_ca_slip"
    _description = "Canadian contractor slip"

    @api.model
    def _get_report_values(self, docids, data=None):
        ids = docids or self._ids_from_options((data or {}).get("ids"))
        return {
            "doc_ids": ids,
            "doc_model": "l10n.ca.slip",
            "docs": self.env["l10n.ca.slip"].browse(ids),
        }

    @api.model
    def _ids_from_options(self, value):
        # Options come from the client, so only positive whole numbers are kept, as Odoo keeps only
        # digits from the ids in a report URL.
        if not isinstance(value, list):
            return []
        return [i for i in value if isinstance(i, int) and not isinstance(i, bool) and i > 0]
