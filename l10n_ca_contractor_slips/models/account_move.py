# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

VENDOR_DOCUMENT_TYPES = ("in_invoice", "in_refund", "in_receipt")


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ca_slip_type = fields.Selection(
        [("t4a", "T4A"), ("t5018", "T5018"), ("none", "Not reported")],
        string="Canadian slip",
        copy=False,
        tracking=True,
        index="btree_not_null",
        help="The slip this bill is reported on. Set from the vendor when the bill is posted, so "
        "changing the vendor's slip type later leaves posted bills where they were. Empty means "
        "the bill follows the vendor's current setting.",
    )

    def _l10n_ca_may_manage(self):
        return self.env.su or self.env.user.has_group("account.group_account_manager")

    def _l10n_ca_refuse_slip_type(self):
        raise AccessError(_("Only accounting administrators can change a bill's Canadian slip."))

    @api.model
    def default_get(self, fields):  # noqa: A002  the field-list argument used by Odoo
        """Context defaults and personal saved defaults cannot preset the slip for other users."""
        values = super().default_get(fields)
        if not self._l10n_ca_may_manage():
            values.pop("l10n_ca_slip_type", None)
        return values

    @api.model_create_multi
    def create(self, vals_list):
        if not self._l10n_ca_may_manage() and any(vals.get("l10n_ca_slip_type") for vals in vals_list):
            self._l10n_ca_refuse_slip_type()
        return super().create(vals_list)

    def write(self, vals):
        if "l10n_ca_slip_type" in vals and not self._l10n_ca_may_manage():
            self._l10n_ca_refuse_slip_type()
        # A draft bill moved to another vendor takes that vendor's slip type when posted again.
        if "partner_id" in vals and "l10n_ca_slip_type" not in vals:
            new_vendor = self.env["res.partner"].browse(vals["partner_id"]).commercial_partner_id
            drafts = self.filtered(lambda m: m.state == "draft" and m.l10n_ca_slip_type)
            for move in drafts:
                if move.commercial_partner_id != new_vendor:
                    move.sudo().l10n_ca_slip_type = False
        return super().write(vals)

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        by_type = defaultdict(lambda: self.env["account.move"])
        for move in posted.filtered(lambda m: m.move_type in VENDOR_DOCUMENT_TYPES and not m.l10n_ca_slip_type):
            # Slip settings live on the main company. The poster may work in a branch only, so the
            # vendor's setting is read with elevated rights. A credit note made by reversing a bill
            # is reported where the bill was.
            vendor = move.commercial_partner_id.sudo().with_company(move.company_id.root_id)
            slip_type = move.reversed_entry_id.l10n_ca_slip_type or vendor.l10n_ca_slip_type
            if slip_type:
                by_type[slip_type] |= move
        for slip_type, moves in by_type.items():
            moves.sudo().l10n_ca_slip_type = slip_type
        return posted
