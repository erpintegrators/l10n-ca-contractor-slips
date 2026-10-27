# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
import logging
import re
import unicodedata
from datetime import timedelta

from stdnum.ca import bn as ca_bn
from stdnum.ca import sin as ca_sin

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from . import cra_format as fmt
from .res_partner import guess_recipient_type

_logger = logging.getLogger(__name__)

SEND_BATCH = 20
FAILED_EMAIL_DAYS = 30

RECIPIENT_FIELDS = (
    "recipient_type", "surname", "given_name", "initial", "corp_name", "street", "street2",
    "city", "state_code", "country_code", "zip", "sin", "recipient_bn",
)
# CRA does not want a slip amended when only the address changed; a slip amended for another
# reason carries the new address.
IDENTITY_FIELDS = ("recipient_type", "surname", "given_name", "initial", "corp_name", "sin", "recipient_bn")
LOCKED_FIELDS = set(RECIPIENT_FIELDS) | {
    "partner_id", "return_id", "computed_base", "computed_incl", "adjustment_base", "adjustment_incl",
    "adjustment_reason", "line_ids", "is_cancelled", "recipient_type_guessed", "name_guessed", "engine_warnings",
}
# Set by the return's own steps and the email job only. The stored copies of the return's state,
# year, type and company, and the stored totals, are kept by Odoo itself.
WORKFLOW_FIELDS = {
    "rpt_tcd", "superseded", "origin_slip_id", "sent_date", "mail_id", "send_requested_uid", "send_to_email",
    "state", "year", "slip_type", "company_id", "amount_base", "amount_incl", "amount_reported",
}


class L10nCaSlip(models.Model):
    _name = "l10n.ca.slip"
    _inherit = ["portal.mixin", "mail.thread"]
    _description = "Canadian contractor slip"
    _order = "year desc, partner_id"

    return_id = fields.Many2one("l10n.ca.slip.return", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="return_id.company_id", store=True)
    currency_id = fields.Many2one(related="return_id.currency_id")
    slip_type = fields.Selection(related="return_id.slip_type", store=True)
    year = fields.Integer(related="return_id.year", store=True)
    state = fields.Selection(related="return_id.state", store=True)
    report_type = fields.Selection(related="return_id.report_type")
    # No company check: a vendor contact can belong to a branch whose bills roll up here.
    partner_id = fields.Many2one("res.partner", string="Recipient", required=True, index=True)
    origin_slip_id = fields.Many2one("l10n.ca.slip", string="Amends slip", readonly=True, copy=False)
    is_cancelled = fields.Boolean(
        string="Cancel this slip",
        tracking=True,
        help="On an amended return, sends this slip to CRA with report type C to cancel it.",
    )
    rpt_tcd = fields.Selection(
        [("O", "Original"), ("A", "Amended"), ("C", "Cancelled")],
        string="Report type",
        readonly=True,
        copy=False,
        help="Set when the return is finalized. Empty on an amended return when the slip did not change, "
        "so it is not sent again.",
    )

    # Recipient details as they appear on the slip, refreshed from the contact on each recalculation.
    recipient_type = fields.Selection(
        [("1", "Individual or sole proprietor"), ("3", "Corporation"), ("4", "Partnership")], required=True
    )
    recipient_type_guessed = fields.Boolean(
        string="Recipient type assumed", readonly=True,
        help="The contact has no recipient type, so the slip assumed one.",
    )
    name_guessed = fields.Boolean(
        string="Name split from the contact", readonly=True,
        help="The surname and given name were split from the contact name.",
    )
    surname = fields.Char()
    given_name = fields.Char()
    initial = fields.Char(size=1)
    corp_name = fields.Char(string="Business name")
    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    state_code = fields.Char(string="Province")
    country_code = fields.Char(string="Country")
    zip = fields.Char(string="Postal code")
    sin = fields.Char(string="SIN", groups="account.group_account_manager")
    recipient_bn = fields.Char(string="Recipient business number")

    computed_base = fields.Monetary(string="Calculated before tax", readonly=True)
    computed_incl = fields.Monetary(string="Calculated with tax", readonly=True)
    adjustment_base = fields.Monetary(string="Adjustment before tax", tracking=True)
    adjustment_incl = fields.Monetary(string="Adjustment with tax", tracking=True)
    adjustment_reason = fields.Text(tracking=True, groups="account.group_account_readonly,account.group_account_manager")
    amount_base = fields.Monetary(string="Total before tax", compute="_compute_amounts", store=True)
    amount_incl = fields.Monetary(string="Total with tax", compute="_compute_amounts", store=True)
    amount_reported = fields.Monetary(
        compute="_compute_amounts",
        store=True,
        help="T4A box 048 (fees for services, before GST/HST and PST) or T5018 box 22 "
        "(contract payments, GST/HST and PST included where charged).",
    )
    line_ids = fields.One2many("l10n.ca.slip.line", "slip_id", string="Payments")
    engine_warnings = fields.Text(readonly=True, groups="account.group_account_readonly,account.group_account_manager")
    warning_message = fields.Text(
        compute="_compute_warning_message", groups="account.group_account_readonly,account.group_account_manager"
    )
    sent_date = fields.Datetime(string="Emailed on", readonly=True, copy=False)
    mail_id = fields.Many2one("mail.mail", readonly=True, copy=False, groups="account.group_account_manager")
    send_requested_uid = fields.Many2one(
        "res.users", string="Email requested by", readonly=True, copy=False, groups="account.group_account_manager",
        help="Set while the slip waits for the scheduled job that emails it.",
    )
    send_to_email = fields.Char(
        string="Queued for", readonly=True, copy=False, groups="account.group_account_manager",
        help="The address the recipient consented to when the email was queued.",
    )
    email_state = fields.Selection(
        [("outgoing", "Queued"), ("sent", "Sent"), ("received", "Received"), ("exception", "Failed"), ("cancel", "Cancelled")],
        compute="_compute_email_state",
        help="Delivery state of the slip email.",
    )
    email_failure = fields.Text(
        compute="_compute_email_state", groups="account.group_account_readonly,account.group_account_manager"
    )
    superseded = fields.Boolean(
        readonly=True, copy=False, help="Replaced or cancelled by a slip on a later amended return."
    )

    _partner_return_uniq = models.Constraint(
        "UNIQUE(return_id, partner_id)", "A recipient can only have one slip per return."
    )

    @api.depends("computed_base", "computed_incl", "adjustment_base", "adjustment_incl", "slip_type")
    def _compute_amounts(self):
        for slip in self:
            slip.amount_base = slip.computed_base + slip.adjustment_base
            slip.amount_incl = slip.computed_incl + slip.adjustment_incl
            slip.amount_reported = slip.amount_base if slip.slip_type == "t4a" else slip.amount_incl

    @api.depends(
        "engine_warnings", "recipient_type", "surname", "given_name", "corp_name", "recipient_bn", "street",
        "street2", "city", "zip", "country_code", "name_guessed", "partner_id.name", "return_id.state", "sin",
        "is_cancelled", "origin_slip_id",
    )
    def _compute_warning_message(self):
        for slip in self:
            warnings = [w for w in (slip.engine_warnings or "").split("\n") if w]
            sin = slip.sudo().sin
            # A sole proprietor may be identified by a business number instead (RC4157).
            if slip.recipient_type == "1" and not sin and not slip.recipient_bn:
                warnings.append(self.env._(
                    "No SIN on the contact. The file reports 000000000, which CRA accepts after a "
                    "reasonable effort to get the number."
                ))
            if slip.recipient_type == "1" and slip.name_guessed:
                warnings.append(self.env._(
                    "The surname and given name were split from the contact name (%(surname)s, %(given)s). "
                    "Enter them on the contact if that split is wrong.",
                    surname=slip.surname or "", given=slip.given_name or "",
                ))
            if slip.recipient_type == "1" and slip.return_id.state == "draft" and slip._surname_not_in_contact_name():
                warnings.append(self.env._(
                    "The surname on the slip (%(surname)s) is not part of the contact name (%(name)s). If the contact "
                    "was renamed, check Surname on slips on the contact.",
                    surname=slip.surname, name=slip.partner_id.sudo().commercial_partner_id.name or "",
                ))
            if slip.recipient_type in ("3", "4") and not slip.recipient_bn:
                warnings.append(self.env._(
                    "No 15-character business number on the contact (Tax ID), so the file reports %s.",
                    fmt.BN_PLACEHOLDER,
                ))
            if not (slip.street and slip.city and slip.zip):
                warnings.append(self.env._("The recipient's address is incomplete."))
            elif slip.country_code in (False, "CA") and not re.fullmatch(r"[A-Z]\d[A-Z]\d[A-Z]\d", fmt.postal_code(slip.zip)):
                warnings.append(self.env._("%s is not a Canadian postal code (A1A 1A1).", slip.zip))
            if slip.recipient_bn and not ca_bn.is_valid(slip.recipient_bn[:9]):
                warnings.append(self.env._(
                    "The business number %s has an invalid check digit; check the contact's Tax ID.", slip.recipient_bn
                ))
            warnings.extend(slip._cleaning_warnings())
            origin = slip.origin_slip_id.sudo()
            if origin and not slip.is_cancelled and (
                (origin.sin or False) != (slip.sudo().sin or False) or (origin.recipient_bn or False) != (slip.recipient_bn or False)
            ):
                warnings.append(self.env._(
                    "The SIN or business number differs from the slip filed earlier. CRA's guidance does not say how "
                    "an amended slip with a new identifier is matched; consider cancelling this slip and filing it in "
                    "a new original return."
                ))
            slip.warning_message = "\n".join(warnings) or False

    def _surname_not_in_contact_name(self):
        """A surname entered on the contact stays when the contact is renamed. Compare letters only,
        so accents, hyphens and spacing do not count as a difference."""
        self.ensure_one()

        def letters(text):
            text = unicodedata.normalize("NFKD", fmt.transliterate(text or ""))
            return re.sub(r"[^a-z]", "", text.lower())

        surname = letters(self.surname)
        return bool(surname) and surname not in letters(self.partner_id.sudo().commercial_partner_id.name)

    def _cleaning_warnings(self):
        """CRA discards characters it does not accept and cuts fields to length: say so where the
        file will differ from what is on the contact."""
        self.ensure_one()
        warnings = []
        fields_to_check = [
            (self.env._("surname"), self.surname, "surname"),
            (self.env._("given name"), self.given_name, "given_name"),
            (self.env._("street"), self.street, "address_line"),
            (self.env._("street, second line"), self.street2, "address_line"),
            (self.env._("city"), self.city, "city"),
        ] if self.recipient_type == "1" else [
            (self.env._("street"), self.street, "address_line"),
            (self.env._("street, second line"), self.street2, "address_line"),
            (self.env._("city"), self.city, "city"),
        ]
        for label, value, key in fields_to_check:
            if fmt.changed_by_cleaning(value, key):
                warnings.append(self.env._(
                    'CRA receives "%(sent)s" for the %(label)s "%(typed)s".',
                    sent=fmt.clean_text(value, key), label=label, typed=value,
                ))
        if self.recipient_type != "1" and self.corp_name:
            sent = " ".join(fmt.split_lines(self.corp_name, "name_line", 2))
            if sent != " ".join(self.corp_name.split()):
                warnings.append(self.env._(
                    'CRA receives "%(sent)s" for the business name "%(typed)s".', sent=sent, typed=self.corp_name
                ))
        return warnings

    @api.constrains("sin")
    def _check_sin(self):
        for slip in self.sudo().filtered("sin"):
            if not ca_sin.is_valid(slip.sin):
                raise ValidationError(self.env._(
                    "The Social Insurance Number on the slip for %s is not valid.", slip.partner_id.display_name
                ))

    @api.depends("send_requested_uid", "sent_date", "mail_id.state", "mail_id.failure_reason")
    def _compute_email_state(self):
        """A sent email is deleted with its PDF, so a slip that was sent and has no mail left is sent."""
        mails = self.sudo().mail_id.exists()
        for slip in self:
            mail = slip.sudo().mail_id & mails
            if slip.sudo().send_requested_uid:
                slip.email_state = "outgoing"
            else:
                slip.email_state = mail.state if mail else ("sent" if slip.sent_date else False)
            slip.email_failure = mail.failure_reason if mail and mail.state == "exception" else False

    @api.constrains("adjustment_base", "adjustment_incl", "adjustment_reason")
    def _check_adjustment_reason(self):
        for slip in self:
            if slip._has_adjustment() and not (slip.adjustment_reason or "").strip():
                raise ValidationError(self.env._("Give a reason for the adjustment on %s.", slip.partner_id.display_name))

    def _compute_access_url(self):
        for slip in self:
            slip.access_url = f"/my/slips/{slip.id}"

    @api.depends("slip_type", "year", "partner_id")
    def _compute_display_name(self):
        labels = dict(self.env["l10n.ca.slip.return"]._fields["slip_type"].selection)
        for slip in self:
            label = (labels.get(slip.slip_type) or "").split(":")[0]
            # A contact kept to one branch stays readable on the main company's slips.
            slip.display_name = f"{label} {slip.year} - {slip.partner_id.sudo().display_name}"

    def _get_report_base_filename(self):
        self.ensure_one()
        return f"{(self.slip_type or '').upper()} {self.year} {self.partner_id.sudo().name or ''}".strip()

    def action_open_slip(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form"}

    def _l10n_ca_full_sin_allowed(self):
        """The full SIN prints only for the signed-in recipient and for accounting administrators
        who can read this slip. Everyone else, including share-link viewers, sees three digits."""
        self.ensure_one()
        user = self.env.user
        if user._is_public():
            return False
        if user.partner_id == self.partner_id:
            return True
        if not user.has_group("account.group_account_manager"):
            return False
        try:
            return self.sudo(False).has_access("read")
        except AccessError:
            return False

    def _l10n_ca_slip_lang(self):
        """CRA accepts slips in the recipient's official language: French for French speakers,
        English for everyone else."""
        self.ensure_one()
        lang = self.partner_id.sudo().lang or ""
        return lang if lang.startswith("fr") else "en_US"

    def message_post(self, **kwargs):
        # The slip PDF carries the full SIN; anything attached here could be opened by every reader
        # of the slip and by holders of its share link.
        if kwargs.get("attachments") or kwargs.get("attachment_ids"):
            raise UserError(self.env._(
                "Files cannot be attached to slip messages because slips hold the recipient's SIN. "
                "Send slips from the return with Email slips."
            ))
        return super().message_post(**kwargs)

    # ------------------------------------------------------------------
    # Email delivery
    # ------------------------------------------------------------------

    @api.model
    def _cron_send_pending(self):
        """Render and email queued slips in batches, committing after each batch. Failed emails are
        deleted, with their PDF, after a month: the slip keeps the failure in its messages."""
        self._purge_failed_emails()
        while True:
            slips = self.sudo().search([("send_requested_uid", "!=", False)], limit=SEND_BATCH)
            if not slips:
                return
            slips._send_pending()
            remaining = self.sudo().search_count([("send_requested_uid", "!=", False)])
            if self.env["ir.cron"]._commit_progress(len(slips), remaining=remaining) <= 0:
                return

    @api.model
    def _purge_failed_emails(self):
        cutoff = fields.Datetime.now() - timedelta(days=FAILED_EMAIL_DAYS)
        for slip in self.sudo().search([("mail_id.state", "in", ("exception", "cancel")), ("sent_date", "<", cutoff)]):
            reason = slip.mail_id.failure_reason or ""
            slip.mail_id.unlink()
            # Nothing reached the recipient, so the slip reads as not emailed and can be sent again.
            slip.write({"sent_date": False})
            slip.message_post(
                body=self.env._("The failed slip email and its PDF were deleted after %(days)s days. Reason: %(reason)s",
                                days=FAILED_EMAIL_DAYS, reason=reason),
                subtype_xmlid="mail.mt_note",
            )

    def _send_pending(self):
        for slip in self.sudo():
            requester = slip.send_requested_uid
            if not (
                requester.active and requester.has_group("account.group_account_manager")
                and slip.company_id in requester.company_ids
            ):
                # The email goes out in the requester's name; someone who has left or lost the
                # right to send slips cannot send it.
                slip._abandon_email(self.env._(
                    "%s can no longer send slips. Ask an accounting administrator to click Email slips again.",
                    requester.name,
                ))
                continue
            try:
                with self.env.cr.savepoint():
                    slip.with_user(requester).with_context(
                        allowed_company_ids=requester.company_ids.ids
                    )._send_email()
            except Exception as error:  # noqa: BLE001  one bad slip must not stop the batch
                _logger.warning("Slip %s could not be emailed: %s", slip.id, error)
                slip._abandon_email(self.env._("The slip email could not be prepared: %s", str(error)[:300]))

    def _email_failed(self, reason):
        """The email could not be sent. When Odoo deletes it, the slip reads as not emailed and
        can be emailed again. When Odoo keeps it, the slip shows the failure, and the failed email
        and its PDF are deleted after FAILED_EMAIL_DAYS like any other."""
        self.ensure_one()
        slip = self.sudo()
        address = slip.mail_id.email_to or slip.partner_id.email_formatted or ""
        reason = self.env._(
            "Slip email to %(address)s failed: %(reason)s. Print the slip for this recipient, or correct the address "
            "and email it again.",
            address=address, reason=reason,
        )
        slip.message_post(body=reason, subtype_xmlid="mail.mt_note")
        slip.return_id.message_post(
            body=self.env._("%(recipient)s: %(reason)s", recipient=slip.partner_id.display_name, reason=reason),
            subtype_xmlid="mail.mt_note",
        )

    def _abandon_email(self, reason):
        """Take the slip out of the email queue and say why, on the slip and on its return, so the
        preparer sees it where they clicked Email slips."""
        self.ensure_one()
        slip = self.sudo()
        slip.write({"send_requested_uid": False, "send_to_email": False})
        slip.message_post(body=reason, subtype_xmlid="mail.mt_note")
        slip.return_id.message_post(
            body=self.env._("%(recipient)s: %(reason)s", recipient=slip.partner_id.display_name, reason=reason),
            subtype_xmlid="mail.mt_note",
        )

    def _send_email(self):
        """Email this slip as the user who asked for it. The PDF carries the recipient's full SIN, so
        the email stands on its own, unlinked from the slip: it never reaches the chatter, where
        anyone who can read the slip or holds its link could open it. The address is fixed now, so
        a later change to the contact cannot redirect it. The PDF is deleted with the email once it
        is sent; a failed email stays, with its reason, on the slip."""
        self.ensure_one()
        # A contact kept to a branch the requester cannot select is still the slip's recipient.
        partner = self.partner_id.sudo()
        address = self.sudo().send_to_email
        consent = partner.with_company(self.company_id).l10n_ca_slip_email_consent
        if not (consent and address and address == partner.email_formatted):
            # Consent was withdrawn, or given again for another address, while the email waited.
            self._abandon_email(self.env._(
                "Slip email not sent: the email consent of %s no longer covers the address it was queued for.",
                partner.display_name,
            ))
            return
        pdf, _report_type = self.env["ir.actions.report"]._render_qweb_pdf(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", self.ids
        )
        template = self.env.ref("l10n_ca_contractor_slips.mail_template_l10n_ca_slip")
        mail_id = template.sudo().send_mail(self.id, email_values={
            "model": False,
            "res_id": False,
            "author_id": self.env.user.partner_id.id,
            "email_to": address,
            "email_cc": "",
            "recipient_ids": [fields.Command.clear()],
            "recipient_cc_ids": [fields.Command.clear()],
            "partner_ids": [fields.Command.set(partner.ids)],
            "partner_cc_ids": [fields.Command.clear()],
            "attachments": [(f"{self._get_report_base_filename()}.pdf", pdf)],
        })
        previous = self.sudo().mail_id
        self.sudo().write({
            "sent_date": fields.Datetime.now(), "mail_id": mail_id, "send_requested_uid": False, "send_to_email": False,
        })
        previous.exists().unlink()
        self.message_post(body=self.env._("Slip queued for email to %s.", address), subtype_xmlid="mail.mt_note")

    # ------------------------------------------------------------------
    # Helpers used by the return
    # ------------------------------------------------------------------

    def _has_adjustment(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        return not (currency.is_zero(self.adjustment_base) and currency.is_zero(self.adjustment_incl))

    def _clear_computed(self):
        self.write({
            "computed_base": 0.0,
            "computed_incl": 0.0,
            "line_ids": [fields.Command.clear()],
            "engine_warnings": False,
        })

    @api.model
    def _recipient_values(self, partner, company):
        # The SIN is the one the paying main company collected.
        partner = partner.sudo().commercial_partner_id.with_company(company)
        recipient_type = partner.l10n_ca_recipient_type or guess_recipient_type(partner)
        vals = {
            "recipient_type": recipient_type,
            "recipient_type_guessed": not partner.l10n_ca_recipient_type,
            "street": partner.street,
            "street2": partner.street2,
            "city": partner.city,
            "state_code": partner.state_id.code,
            "country_code": partner.country_id.code or "CA",
            "zip": partner.zip,
            "sin": partner.l10n_ca_sin,
            "recipient_bn": fmt.program_account(partner.vat),
        }
        if recipient_type == "1":
            name = (partner.name or "").strip()
            parts = name.replace(",", " ").split()
            surname = partner.l10n_ca_slip_surname or (parts[-1] if parts else False)
            given_name = partner.l10n_ca_slip_given_name or (parts[0] if len(parts) > 1 else False)
            vals.update(
                surname=surname,
                given_name=given_name,
                initial=partner.l10n_ca_slip_initial,
                corp_name=False,
                # Two words split cleanly; more words, or a comma, may hide a compound surname.
                name_guessed=not partner.l10n_ca_slip_surname and (len(parts) > 2 or "," in name),
            )
        else:
            vals.update(surname=False, given_name=False, initial=False, corp_name=partner.name, name_guessed=False)
        return vals

    def _copy_filed_values(self):
        """A cancelled slip repeats what was filed, as CRA asks."""
        self.ensure_one()
        origin = self.origin_slip_id.sudo()
        if not origin:
            return
        names = list(RECIPIENT_FIELDS) + [
            "computed_base", "computed_incl", "adjustment_base", "adjustment_incl", "adjustment_reason",
        ]
        values = {name: origin[name] for name in names} | {"line_ids": [fields.Command.clear()]}
        self.sudo().with_context(l10n_ca_slip_copy=True).write(values)

    def _differs_from_origin(self):
        self.ensure_one()
        origin = self.origin_slip_id
        if not origin:
            return True
        if self.currency_id.compare_amounts(self.amount_reported, origin.amount_reported):
            return True
        return any(self.sudo()[name] != origin.sudo()[name] for name in IDENTITY_FIELDS)

    def _get_blocking_errors(self):
        self.ensure_one()
        errors = []
        if self.recipient_type_guessed and not self.is_cancelled:
            label = dict(self._fields["recipient_type"].selection).get(self.recipient_type)
            errors.append(self.env._(
                "choose the slip recipient type on the contact (the slip assumed %s), then recalculate.", label
            ))
        if self.recipient_type == "1" and not fmt.clean_text(self.surname, "surname"):
            errors.append(self.env._("an individual recipient needs a surname."))
        if self.recipient_type == "1" and self.initial and not self.initial.isalpha():
            errors.append(self.env._("the second initial must be a letter."))
        if self.recipient_type in ("3", "4") and not fmt.clean_text(self.corp_name, "name_line"):
            errors.append(self.env._("a business recipient needs a name."))
        if self.country_code in ("CA", "US") and not self.state_code and not self.is_cancelled:
            errors.append(self.env._("the recipient's address needs a province or state."))
        if not self.is_cancelled and self.currency_id.compare_amounts(self.amount_reported, 0.0) <= 0:
            if self.origin_slip_id:
                errors.append(self.env._("the amount is now zero; tick Cancel this slip to cancel it with CRA."))
            else:
                errors.append(self.env._("the slip amount must be above zero."))
        if self.slip_type == "t4a" and self.amount_reported >= 10**9:
            errors.append(self.env._("the amount is too large for the CRA file."))
        return errors

    @api.model
    def _append_address(self, parent, tag, record, node, optional):
        """Append a CanadaAddressType element from a partner or a slip snapshot."""
        if record._name == "res.partner":
            values = {
                "street": record.street, "street2": record.street2, "city": record.city,
                "state_code": record.state_id.code, "country_code": record.country_id.code or "CA",
                "zip": record.zip,
            }
        else:
            values = {name: record[name] for name in ("street", "street2", "city", "state_code", "country_code", "zip")}
        country = fmt.COUNTRY_CODES.get(values["country_code"] or "CA")
        address = node(parent, tag)
        optional(address, "addr_l1_txt", fmt.clean_text(values["street"], "address_line"))
        optional(address, "addr_l2_txt", fmt.clean_text(values["street2"], "address_line"))
        optional(address, "cty_nm", fmt.clean_text(values["city"], "city"))
        if country:
            optional(address, "prov_cd", (values["state_code"] or "").upper()[:2])
        else:
            optional(address, "prov_cd", "ZZ")
        optional(address, "cntry_cd", country)
        optional(address, "pstl_cd", fmt.postal_code(values["zip"], values["country_code"] or "CA"))
        if not len(address):
            parent.remove(address)

    def _append_xml(self, body, payer_account, node, optional):
        self.ensure_one()
        is_t4a = self.slip_type == "t4a"
        slip = node(body, "T4ASlip" if is_t4a else "T5018Slip")
        sin = fmt.sin_digits(self.sudo().sin)
        if self.recipient_type == "1":
            name = node(slip, "RCPNT_NM")
            node(name, "snm", fmt.clean_text(self.surname, "surname"))
            optional(name, "gvn_nm", fmt.clean_text(self.given_name, "given_name"))
            optional(name, "init", fmt.clean_text(self.initial, "initial"))
            node(slip, "sin", sin or fmt.SIN_PLACEHOLDER)
            node(slip, "rcpnt_bn", self.recipient_bn or fmt.BN_PLACEHOLDER)
        else:
            node(slip, "sin", fmt.SIN_PLACEHOLDER)
            node(slip, "rcpnt_bn", self.recipient_bn or fmt.BN_PLACEHOLDER)
            name = node(slip, "RCPNT_CORP_NM" if is_t4a else "CORP_PTNRP_NM")
            for index, line in enumerate(fmt.split_lines(self.corp_name, "name_line", 2), start=1):
                node(name, f"l{index}_nm", line)
        if not is_t4a:
            node(slip, "rcpnt_tcd", self.recipient_type)
        self._append_address(slip, "RCPNT_ADDR", self, node, optional)
        node(slip, "bn", payer_account)
        if is_t4a:
            node(slip, "rpt_tcd", self.rpt_tcd)
            node(node(slip, "T4A_AMT"), "fee_or_oth_srvc_amt", fmt.amount(self.amount_reported))
        else:
            node(slip, "sbctrcr_amt", fmt.amount(self.amount_reported))
            node(slip, "rpt_tcd", self.rpt_tcd)

    # ------------------------------------------------------------------
    # Protection
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            if any(vals.get(name) for vals in vals_list for name in WORKFLOW_FIELDS):
                raise UserError(self.env._("Report codes and amendment links are set by the return."))
            returns = self.env["l10n.ca.slip.return"].browse([vals.get("return_id") for vals in vals_list if vals.get("return_id")])
            if any(slip_return.state != "draft" for slip_return in returns):
                raise UserError(self.env._("Slips can only be added to a draft return."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if WORKFLOW_FIELDS.intersection(vals):
                raise UserError(self.env._("Report codes and amendment links are set by the return."))
            # The return's own state decides; the slip's stored copy could be out of step.
            if LOCKED_FIELDS.intersection(vals) and any(slip.return_id.state != "draft" for slip in self):
                raise UserError(self.env._(
                    "Slips on a final or filed return cannot be changed. Amend the return instead."
                ))
        result = super().write(vals)
        if {"adjustment_base", "adjustment_incl"}.intersection(vals) and not self.env.context.get("l10n_ca_slip_copy"):
            for slip in self:
                slip.message_post(body=self.env._(
                    "Adjustment changed by %(user)s. Reason: %(reason)s",
                    user=self.env.user.name,
                    reason=slip.adjustment_reason or "",
                ))
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(slip.return_id.state != "draft" for slip in self):
            raise UserError(self.env._("Slips on a final or filed return cannot be deleted."))


class L10nCaSlipLine(models.Model):
    _name = "l10n.ca.slip.line"
    _description = "Payment counted on a Canadian contractor slip"
    _order = "date, id"

    slip_id = fields.Many2one("l10n.ca.slip", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="slip_id.company_id", store=True)
    currency_id = fields.Many2one(related="slip_id.currency_id")
    date = fields.Date(string="Paid on", required=True)
    move_id = fields.Many2one("account.move", string="Bill")
    move_ref = fields.Char(string="Bill number", help="Kept on the slip if the bill is later deleted.")
    payment_move_id = fields.Many2one("account.move", string="Payment entry")
    payment_ref = fields.Char(string="Payment number", help="Kept on the slip if the entry is later deleted.")
    payment_id = fields.Many2one("account.payment")
    source = fields.Selection(
        [
            ("reconciled", "Matched payment"),
            ("credit_note", "Credit note applied"),
            ("payment", "Payment without entry"),
            ("bank", "Direct bank entry"),
        ],
        required=True,
    )
    cash = fields.Monetary(help="Amount paid in company currency at the payment date.")
    amount_base = fields.Monetary(string="Counted before tax")
    amount_incl = fields.Monetary(string="Counted with tax")

    def _check_slip_draft(self, slips):
        if not self.env.su and any(slip.return_id.state != "draft" for slip in slips):
            raise UserError(self.env._("Slips on a final or filed return cannot be changed. Amend the return instead."))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_slip_draft(self.env["l10n.ca.slip"].browse([vals.get("slip_id") for vals in vals_list if vals.get("slip_id")]))
        return super().create(vals_list)

    def write(self, vals):
        if "company_id" in vals and not self.env.su:
            raise UserError(self.env._("A payment line belongs to its slip's company."))
        self._check_slip_draft(self.slip_id | self.env["l10n.ca.slip"].browse(vals.get("slip_id") or []))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        self._check_slip_draft(self.slip_id)
