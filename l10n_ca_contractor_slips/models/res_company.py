# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
import re

from stdnum.ca import bn as ca_bn

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PROGRAM_ACCOUNT = re.compile(r"^\d{9}(?P<program>[A-Z]{2})\d{4}$")


def compact_bn(value):
    return re.sub(r"[\s-]", "", value or "").upper()


def check_program_account(env, value, program):
    """Return an error message when value is not a valid 15-character CRA account for program."""
    value = compact_bn(value)
    match = PROGRAM_ACCOUNT.match(value)
    if not match:
        return _(
            "%(value)s is not a 15-character CRA account such as 123456789%(program)s0001.",
            value=value or _("(empty)"), program=program,
        )
    if match["program"] != program:
        return _(
            "%(value)s uses program %(used)s; this filing needs a %(program)s account.",
            value=value, used=match["program"], program=program,
        )
    if not ca_bn.is_valid(value[:9]):
        return _("%s has an invalid business number check digit.", value)
    return ""


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ca_slip_rp_account = fields.Char(
        string="T4A payer account (RP)",
        help="Your CRA RP program account, for example 123456789RP0001. Used on T4A slips and summary.",
    )
    l10n_ca_slip_rz_account = fields.Char(
        string="T5018 payer account (RZ)",
        help="Your CRA RZ program account, for example 123456789RZ0001. Used on T5018 slips and summary.",
    )
    l10n_ca_slip_transmitter_account = fields.Char(
        string="Transmitter CRA account number",
        help="The business number (9 digits) or program account (15 characters) used to sign in to CRA "
        "when you upload the file. It must match that login.",
    )
    l10n_ca_slip_transmitter_repid = fields.Char(
        string="Transmitter RepID",
        help="Only for representatives filing through Represent a Client.",
    )
    l10n_ca_slip_signin = fields.Selection(
        [
            ("myba", "My Business Account"),
            ("wac", "Web access code"),
            ("rac", "Represent a Client"),
        ],
        string="CRA sign-in",
        default="myba",
        required=True,
        help="How you sign in to CRA's Internet File Transfer to upload the file. CRA checks the file "
        "against that sign-in: with a web access code the file carries the 15-character account you "
        "signed in with, and a representative's file carries their RepID.",
    )
    l10n_ca_slip_transmitter_name = fields.Char(
        string="Transmitter name",
        help="The person or firm who uploads the file, when it is not the company itself, such as an "
        "accounting firm filing through Represent a Client.",
    )
    l10n_ca_slip_contact_id = fields.Many2one(
        "res.partner",
        string="Filing contact",
        help="Person CRA contacts about the return. Needs a 10-digit phone number and an email.",
    )
    l10n_ca_t5018_period = fields.Selection(
        [("calendar", "Calendar year"), ("fiscal", "Fiscal year")],
        string="T5018 reporting period",
        default="calendar",
        required=True,
        help="Once you file for a reporting period, CRA expects every later T5018 return for the same "
        "period unless it authorizes a change in writing.",
    )
    l10n_ca_t5018_include_mixed_goods = fields.Boolean(
        string="T5018: report the whole mixed bill",
        default=True,
        help="When a subcontractor bill mixes construction services and goods, report the whole bill, "
        "as Form T5018SUM describes. Untick to report the services lines only. Goods-only bills are "
        "never reported.",
    )
    l10n_ca_t5018_threshold_basis = fields.Selection(
        [
            ("incl_500", "Service part with tax, $500 or more (Form T5018SUM)"),
            ("base_over_500", "Before tax, more than $500 (CRA T5018 slip page)"),
        ],
        string="T5018 slip threshold",
        default="incl_500",
        required=True,
        help="CRA's two publications word the T5018 threshold differently. The default issues a slip "
        "in every case either wording requires.",
    )

    @api.constrains("l10n_ca_slip_rp_account")
    def _check_l10n_ca_slip_rp_account(self):
        for company in self.filtered("l10n_ca_slip_rp_account"):
            if error := check_program_account(self.env, company.l10n_ca_slip_rp_account, "RP"):
                raise ValidationError(error)

    @api.constrains("l10n_ca_slip_rz_account")
    def _check_l10n_ca_slip_rz_account(self):
        for company in self.filtered("l10n_ca_slip_rz_account"):
            if error := check_program_account(self.env, company.l10n_ca_slip_rz_account, "RZ"):
                raise ValidationError(error)

    @api.constrains("l10n_ca_slip_transmitter_account")
    def _check_l10n_ca_slip_transmitter_account(self):
        for company in self.filtered("l10n_ca_slip_transmitter_account"):
            value = compact_bn(company.l10n_ca_slip_transmitter_account)
            if not (re.fullmatch(r"\d{9}", value) or PROGRAM_ACCOUNT.match(value)) or not ca_bn.is_valid(value[:9]):
                raise ValidationError(
                    _("%s is not a valid business number or 15-character CRA account.", value)
                )

    def write(self, vals):
        for key in ("l10n_ca_slip_rp_account", "l10n_ca_slip_rz_account", "l10n_ca_slip_transmitter_account"):
            if vals.get(key):
                vals[key] = compact_bn(vals[key])
        return super().write(vals)
