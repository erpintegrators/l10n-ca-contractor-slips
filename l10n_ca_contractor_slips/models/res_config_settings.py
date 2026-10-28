# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ca_slip_rp_account = fields.Char(related="company_id.l10n_ca_slip_rp_account", readonly=False)
    l10n_ca_slip_rz_account = fields.Char(related="company_id.l10n_ca_slip_rz_account", readonly=False)
    l10n_ca_slip_transmitter_account = fields.Char(
        related="company_id.l10n_ca_slip_transmitter_account", readonly=False
    )
    l10n_ca_slip_transmitter_repid = fields.Char(related="company_id.l10n_ca_slip_transmitter_repid", readonly=False)
    l10n_ca_slip_signin = fields.Selection(related="company_id.l10n_ca_slip_signin", readonly=False)
    l10n_ca_slip_transmitter_name = fields.Char(related="company_id.l10n_ca_slip_transmitter_name", readonly=False)
    l10n_ca_slip_contact_id = fields.Many2one(related="company_id.l10n_ca_slip_contact_id", readonly=False)
    l10n_ca_t5018_period = fields.Selection(related="company_id.l10n_ca_t5018_period", readonly=False)
    l10n_ca_t5018_include_mixed_goods = fields.Boolean(
        related="company_id.l10n_ca_t5018_include_mixed_goods", readonly=False
    )
    l10n_ca_t5018_threshold_basis = fields.Selection(
        related="company_id.l10n_ca_t5018_threshold_basis", readonly=False
    )

    def action_l10n_ca_slip_reload_schemas(self):
        loaded = self.env["l10n.ca.slip.return"]._l10n_ca_load_cra_schemas(force=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success" if loaded else "danger",
                "message": _("CRA's schemas are loaded.") if loaded else _(
                    "CRA's schemas could not be downloaded. Check the server's internet access, or set the "
                    "system parameter l10n_ca_contractor_slips.cra_schema_url to a copy of the package."
                ),
            },
        }
