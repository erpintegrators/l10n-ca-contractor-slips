# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
import re

from stdnum.ca import sin as ca_sin

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

# Changing these decides who gets a slip and where it is sent, so only accounting
# administrators may set them, whatever the form shows.
MANAGED_FIELDS = {
    "l10n_ca_slip_type", "l10n_ca_recipient_type", "l10n_ca_sin", "l10n_ca_slip_email_consent",
    "l10n_ca_slip_email_consent_date",
}
# A recipient consents to one payer's slips by email. Each main company keeps its own consent; its
# branches share its business number, so they share its consent.
CONSENT_FIELDS = ("l10n_ca_slip_email_consent", "l10n_ca_slip_email_consent_date")
# Kept for each main company: the payer that collected a SIN or a consent is the only one that holds
# it. Values entered while working in a branch are recorded for its main company.
MAIN_COMPANY_FIELDS = ("l10n_ca_sin", *CONSENT_FIELDS)
# Marks the module's own writes of those values. An object cannot travel in a request's context,
# so no client can set it.
MAIN_COMPANY_WRITE = object()
# Words that end a business name. A contact named like this is offered as a corporation.
BUSINESS_SUFFIX = re.compile(
    r"\b(ltd|lt[ée]e|limited|limit[ée]e|inc|incorporated|incorpor[ée]e|corp|corporation|co|company|"
    r"llp|s\.?e\.?n\.?c\.?r\.?l|s\.?e\.?n\.?c|enr|enterprises?|holdings|group|partnership)\.?$",
    re.IGNORECASE,
)


def guess_recipient_type(partner):
    """Individual unless the contact has a business number or a business name."""
    if partner.is_company or BUSINESS_SUFFIX.search((partner.name or "").strip()):
        return "3"
    return "1"


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ca_slip_type = fields.Selection(
        [("t4a", "T4A: fees for services (box 048)"), ("t5018", "T5018: construction subcontractor")],
        string="Canadian slip",
        company_dependent=True,
        help="Which CRA slip this vendor's payments are reported on. Set it while working in the "
        "main company: returns read it from there for every branch.",
    )
    l10n_ca_recipient_type = fields.Selection(
        [("1", "Individual or sole proprietor"), ("3", "Corporation"), ("4", "Partnership")],
        string="Slip recipient type",
        copy=False,
        help="How CRA identifies this recipient: by name and SIN for individuals, by business name and "
        "business number otherwise.",
    )
    l10n_ca_sin = fields.Char(
        string="SIN",
        company_dependent=True,
        groups="account.group_account_manager",
        copy=False,
        help="Social Insurance Number, needed for individual recipients. Each main company keeps the SIN it "
        "collected, visible to its own accounting administrators only.",
    )
    l10n_ca_slip_surname = fields.Char(
        string="Surname on slips", copy=False, help="Leave empty to use the last word of the contact name."
    )
    l10n_ca_slip_given_name = fields.Char(
        string="Given name on slips", copy=False, help="Leave empty to use the first word of the contact name."
    )
    l10n_ca_slip_initial = fields.Char(string="Second initial on slips", size=1, copy=False)
    l10n_ca_slip_email_consent = fields.Boolean(
        string="Slips by email",
        company_dependent=True,
        copy=False,
        help="The recipient agreed, in writing or electronically, to receive this company's tax slips by "
        "email. CRA requires this consent before slips are emailed, and it covers only the company it was "
        "given to. A T4A slip may be made available on the portal without this consent, unless the "
        "recipient asked for paper or cannot reasonably be expected to use the portal.",
    )
    l10n_ca_slip_email_consent_date = fields.Date(
        string="Consent recorded on",
        company_dependent=True,
        copy=False,
        readonly=True,
        help="Set when the consent box is ticked. Keep the recipient's written or electronic consent with "
        "your records.",
    )
    l10n_ca_slip_paper = fields.Boolean(
        string="Wants paper slips",
        copy=False,
        help="The recipient asked for paper copies. They are listed for printing even when they have a portal "
        "login.",
    )
    l10n_ca_slip_on_branch = fields.Boolean(string="Working in a branch", compute="_compute_l10n_ca_slip_on_branch")
    l10n_ca_slip_consent_company_id = fields.Many2one(
        "res.company", string="Consent given to", compute="_compute_l10n_ca_slip_on_branch",
        help="The company whose slips the consent box covers.",
    )

    @api.depends_context("company")
    def _compute_l10n_ca_slip_on_branch(self):
        company = self.env.company
        for partner in self:
            partner.l10n_ca_slip_on_branch = bool(company.parent_id)
            partner.l10n_ca_slip_consent_company_id = company.root_id

    @api.constrains("l10n_ca_sin")
    def _check_l10n_ca_sin(self):
        for partner in self.sudo().filtered("l10n_ca_sin"):
            if not ca_sin.is_valid(partner.l10n_ca_sin):
                # The number stays out of the message: error messages reach the server log.
                raise ValidationError(self.env._(
                    "The Social Insurance Number on %s is not valid.", partner.display_name or self.env._("this contact")
                ))

    @api.model
    def default_get(self, fields):  # noqa: A002  the field-list argument used by Odoo
        """Context defaults and personal saved defaults cannot set slip settings for users who
        may not change them."""
        values = super().default_get(fields)
        if not self._l10n_ca_may_manage():
            for name in MANAGED_FIELDS:
                values.pop(name, None)
        return values

    def _l10n_ca_may_manage(self):
        return self.env.su or self.env.user.has_group("account.group_account_manager")

    def _l10n_ca_check_managed(self, vals):
        if MANAGED_FIELDS.intersection(vals) and not self._l10n_ca_may_manage():
            raise AccessError(self.env._("Only accounting administrators can change Canadian slip settings."))

    def _l10n_ca_clean_vals(self, vals):
        if vals.get("l10n_ca_sin"):
            vals["l10n_ca_sin"] = re.sub(r"\D", "", vals["l10n_ca_sin"])
        if "l10n_ca_slip_email_consent" in vals:
            vals["l10n_ca_slip_email_consent_date"] = (
                fields.Date.context_today(self) if vals["l10n_ca_slip_email_consent"] else False
            )
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        main_values = []
        for vals in vals_list:
            self._l10n_ca_check_managed({key: value for key, value in vals.items() if value})
            self._l10n_ca_clean_vals(vals)
            main_values.append({name: vals.pop(name) for name in MAIN_COMPANY_FIELDS if name in vals})
        partners = super().create(vals_list)
        for partner, values in zip(partners, main_values, strict=True):
            if any(values.values()):
                partner._l10n_ca_write_main_company(values)
        return partners

    def write(self, vals):
        self._l10n_ca_check_managed(vals)
        if self.env.su and self.env.context.get("l10n_ca_main_company_write") is MAIN_COMPANY_WRITE:
            # A value the module itself writes, already placed on the right company.
            return super().write(vals)
        vals = self._l10n_ca_clean_vals(dict(vals))
        main_values = {name: vals.pop(name) for name in MAIN_COMPANY_FIELDS if name in vals}
        if "email" in vals:
            # Consent ticked in the same save covers the new address for the current company only.
            self._l10n_ca_withdraw_consent(vals["email"])
        result = super().write(vals)
        if main_values:
            self._l10n_ca_write_main_company(main_values)
        return result

    def _l10n_ca_write_main_company(self, values):
        """Record a SIN or a consent for the main company, whichever branch the user is working in."""
        self.check_access("write")
        root = self.env.company.root_id
        self.sudo().with_company(root).with_context(l10n_ca_main_company_write=MAIN_COMPANY_WRITE).write(values)

    def _l10n_ca_withdraw_consent(self, email):
        """Consent was given for an address, so a new address needs consent again, from every payer
        that had it. Slip emails still waiting for the old address are not sent."""
        roots = self.env["res.company"].sudo().with_context(active_test=False).search([("parent_id", "=", False)])
        changed = self.browse()
        for root in roots:
            partners = self.sudo().with_company(root).filtered(
                lambda p: p.l10n_ca_slip_email_consent and p.email != email
            )
            partners.with_context(l10n_ca_main_company_write=MAIN_COMPANY_WRITE).write(
                dict.fromkeys(CONSENT_FIELDS, False)
            )
            changed |= partners
        Slip = self.env["l10n.ca.slip"].sudo()
        queued = Slip.search([
            ("partner_id", "in", changed.commercial_partner_id.ids), "|", ("send_requested_uid", "!=", False),
            ("mail_id.state", "=", "outgoing"),
        ])
        for slip in queued:
            # An email already waiting in the outgoing queue is withdrawn as well; deleting it leaves
            # the slip not emailed.
            slip.mail_id.filtered(lambda mail: mail.state == "outgoing").unlink()
            slip._abandon_email(self.env._(
                "Slip email not sent: the email address changed while it waited. Confirm consent for the new "
                "address, then click Email slips again."
            ))
