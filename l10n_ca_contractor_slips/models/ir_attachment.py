# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, models
from odoo.exceptions import UserError

SLIP_MODEL = "l10n.ca.slip"


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _l10n_ca_refuse_slip_files(self):
        # A file on a slip could be its PDF, which carries the full SIN, and every reader of the slip
        # could open it, including read-only accountants who see only the last three digits. The
        # module never stores files on slips; uploads and composers must not either.
        raise UserError(self.env._(
            "Files cannot be attached to slips because slips hold the recipient's SIN. Send slips from the "
            "return with Email slips."
        ))

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get("res_model") == SLIP_MODEL for vals in vals_list):
            self._l10n_ca_refuse_slip_files()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("res_model") == SLIP_MODEL or ("res_id" in vals and any(a.res_model == SLIP_MODEL for a in self)):
            self._l10n_ca_refuse_slip_files()
        return super().write(vals)
