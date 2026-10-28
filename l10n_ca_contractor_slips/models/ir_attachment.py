# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

SLIP_MODEL = "l10n.ca.slip"


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    l10n_ca_slip_company_id = fields.Many2one(
        "res.company", string="Contractor slip payer", readonly=True, copy=False, index=True,
        help="Restricts stored CRA XML and queued slip PDFs to the paying company's accounting administrators.",
    )

    def _l10n_ca_private_files(self):
        return self.sudo().filtered(lambda attachment:
            attachment.l10n_ca_slip_company_id
            or (attachment.res_model == "l10n.ca.slip.return" and attachment.res_field == "xml_file")
        )

    def _l10n_ca_check_private_read(self):
        if self.env.su:
            return
        files = self._l10n_ca_private_files()
        if not files:
            return
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError(self.env._("Only the paying company's accounting administrators may read stored slip files."))
        for attachment in files:
            company = attachment.l10n_ca_slip_company_id
            if not company and attachment.res_model == "l10n.ca.slip.return":
                company = self.env["l10n.ca.slip.return"].sudo().browse(attachment.res_id).exists().company_id
            if not company or company not in self.env.user.company_ids:
                raise AccessError(self.env._("Only the paying company's accounting administrators may read stored slip files."))

    @api.model
    def _l10n_ca_secure_existing_files(self):
        """Revoke legacy public links without changing the retained XML or queued PDF bytes."""
        attachments = self.sudo()
        xml_files = attachments.search([
            ("res_model", "=", "l10n.ca.slip.return"), ("res_field", "=", "xml_file"),
        ])
        for attachment in xml_files:
            slip_return = self.env["l10n.ca.slip.return"].sudo().browse(attachment.res_id).exists()
            attachment.write({
                "l10n_ca_slip_company_id": slip_return.company_id.id,
                "public": False, "access_token": False,
            })
        for slip in self.env["l10n.ca.slip"].sudo().search([("mail_id", "!=", False)]):
            slip.mail_id.attachment_ids.write({
                "l10n_ca_slip_company_id": slip.company_id.id,
                "public": False, "access_token": False,
            })

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
        for vals in vals_list:
            if vals.get("l10n_ca_slip_company_id") and not self.env.su:
                raise AccessError(self.env._("The slip payer is assigned by the return or email workflow."))
            if vals.get("res_model") == "l10n.ca.slip.return" and vals.get("res_field") == "xml_file":
                record = self.env["l10n.ca.slip.return"].sudo().browse(vals.get("res_id")).exists()
                if record:
                    vals["l10n_ca_slip_company_id"] = record.company_id.id
                vals["public"] = False
                vals["access_token"] = False
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and (
            "l10n_ca_slip_company_id" in vals
            or ((vals.get("public") or vals.get("access_token")) and self._l10n_ca_private_files())
        ):
            raise AccessError(self.env._("The privacy restriction on a contractor slip file cannot be changed."))
        if vals.get("res_model") == SLIP_MODEL or ("res_id" in vals and any(a.res_model == SLIP_MODEL for a in self)):
            self._l10n_ca_refuse_slip_files()
        return super().write(vals)

    def generate_access_token(self):
        if self._l10n_ca_private_files():
            raise UserError(self.env._("Stored contractor slip files cannot have public download tokens."))
        return super().generate_access_token()

    def validate_access(self, access_token):
        self.ensure_one()
        if self._l10n_ca_private_files():
            self._l10n_ca_check_private_read()
            self.check_access("read")
            return self
        return super().validate_access(access_token)
