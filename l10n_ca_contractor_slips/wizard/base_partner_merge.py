# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import models
from odoo.exceptions import UserError
from odoo.tools import email_normalize

from ..models.res_partner import CONSENT_FIELDS, MAIN_COMPANY_FIELDS

# Recipient details a merge carries over to the kept contact when it has none of its own.
CARRIED_FIELDS = (
    "l10n_ca_recipient_type", "l10n_ca_slip_surname", "l10n_ca_slip_given_name", "l10n_ca_slip_initial",
)
# Kept for each company, including companies other than the one selected during the merge.
COMPANY_FIELDS = ("l10n_ca_slip_type", *MAIN_COMPANY_FIELDS)


class BasePartnerMergeAutomaticWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    def _merge(self, partner_ids, dst_partner=None, extra_checks=True):
        if dst_partner:
            # A caller can pass a record from another environment. Native field selection and
            # reads must both use the merge operator's rights.
            dst_partner = dst_partner.with_env(self.env)
        partners = self.env["res.partner"].browse(partner_ids).exists()
        if len(partners) < 2:
            return super()._merge(partner_ids, dst_partner=dst_partner, extra_checks=extra_checks)
        if dst_partner and dst_partner in partners:
            src_partners = partners - dst_partner
        else:
            ordered = self._get_ordered_partner(partners.ids)
            dst_partner, src_partners = ordered[-1], ordered[:-1]
        self._l10n_ca_check_rights(src_partners, dst_partner)
        self._l10n_ca_check_same_person(src_partners, dst_partner)
        self._l10n_ca_resolve_slips(src_partners, dst_partner)
        carried = self._l10n_ca_carried_values(src_partners, dst_partner)
        company_values = self._l10n_ca_company_values(src_partners, dst_partner)
        consents = self._l10n_ca_consents(src_partners, dst_partner)
        moved = self.env["l10n.ca.slip"].sudo().search([
            ("partner_id", "in", src_partners.ids), ("return_id.state", "!=", "draft"),
        ])
        names = ", ".join(src_partners.sudo().mapped("display_name"))
        result = super()._merge(partner_ids, dst_partner=dst_partner, extra_checks=extra_checks)
        if carried:
            dst_partner.sudo().write(carried)
        for company, values in company_values.items():
            dst_partner.sudo().with_company(company).write(values)
        self._l10n_ca_keep_consent_with_its_address(dst_partner, consents)
        for slip_return in moved.return_id:
            slip_return.message_post(body=self.env._(
                "%(names)s merged into %(kept)s. Their slips on this return now belong to %(kept)s.",
                names=names, kept=dst_partner.sudo().display_name,
            ), subtype_xmlid="mail.mt_note")
        return result

    def _l10n_ca_company_values(self, src_partners, dst_partner):
        """Odoo 19 merges ordinary company-dependent fields in the selected company only.
        Preserve the contractor fields for every main company after checking the operator's
        rights. As in the native merge, the kept contact's nonempty values take precedence."""
        companies = self.env["res.company"].sudo().with_context(active_test=False).search([
            ("parent_id", "=", False),
        ])
        result = {}
        for company in companies:
            values = {}
            for partner in (src_partners + dst_partner).sudo().with_company(company):
                for name in COMPANY_FIELDS:
                    if partner[name]:
                        values[name] = partner[name]
            if values:
                result[company] = values
        return result

    def _l10n_ca_consents(self, src_partners, dst_partner):
        """For each main company: whether the kept contact already had email consent, and the
        addresses the merged-away contacts had consented with."""
        roots = self.env["res.company"].sudo().with_context(active_test=False).search([("parent_id", "=", False)])
        consents = {}
        for root in roots:
            kept = dst_partner.sudo().with_company(root).l10n_ca_slip_email_consent
            sources = src_partners.sudo().with_company(root).filtered("l10n_ca_slip_email_consent")
            consents[root] = (kept, {email_normalize(source.email) for source in sources} - {False})
        return consents

    def _l10n_ca_keep_consent_with_its_address(self, dst_partner, consents):
        """Odoo's merge copies each company's consent from a merged-away contact. Consent covers
        the address it was given for, so it stays only when the kept contact has that address."""
        kept_contact = dst_partner.sudo()
        address = email_normalize(kept_contact.email)
        for root, (had_consent, addresses) in consents.items():
            if had_consent or not kept_contact.with_company(root).l10n_ca_slip_email_consent:
                continue
            if address not in addresses:
                kept_contact.with_company(root).write(dict.fromkeys(CONSENT_FIELDS, False))

    def _l10n_ca_check_rights(self, src_partners, dst_partner):
        """Odoo's merge moves each company's SIN, consent and slip type to the kept contact, along
        with the slips, filed ones included, and the portal login, which then opens those slips with
        the full SIN. Contacts holding any slip detail are merged only by an accounting administrator
        who works in every main company that holds one."""
        if self.env.su:
            return
        partners = (src_partners | dst_partner).sudo()
        companies = self._l10n_ca_slip_companies(partners)
        if not companies and not any(partner[name] for partner in partners for name in CARRIED_FIELDS):
            return
        user = self.env.user
        if user.has_group("account.group_account_manager") and companies <= user.company_ids:
            return
        raise UserError(self.env._(
            "These contacts hold Canadian slip details (a SIN, email consent, slip type, recipient details or "
            "slips), and the merge moves them to the kept contact. Ask an accounting administrator who works in "
            "every company that pays them to merge the contacts."
        ))

    def _l10n_ca_slip_companies(self, partners):
        """The main companies holding slip details for these contacts: values kept for each company,
        and slips."""
        companies = self.env["res.company"].sudo().with_context(active_test=False).search([])
        holders = companies.filtered(lambda company: any(
            value for name in COMPANY_FIELDS for value in partners.with_company(company).mapped(name)
        ))
        slips = self.env["l10n.ca.slip"].sudo().search([("partner_id", "in", partners.ids)])
        return (holders | slips.company_id).root_id

    def _l10n_ca_check_same_person(self, src_partners, dst_partner):
        """Final or filed slips keep the SIN or business number they reported. Merging contacts whose
        slips name different people would show one person's slip, with their full SIN, on the other's
        portal."""
        slips = self.env["l10n.ca.slip"].sudo().search([
            ("partner_id", "in", (src_partners | dst_partner).ids), ("return_id.state", "!=", "draft"),
        ])
        if not slips:
            return
        sins = {slip.sin for slip in slips} - {False, ""}
        numbers = {(slip.recipient_bn or "")[:9] for slip in slips} - {""}
        # The kept contact's own SIN or business number names a person too.
        kept = dst_partner.sudo()
        roots = self.env["res.company"].sudo().with_context(active_test=False).search([("parent_id", "=", False)])
        sins |= {kept.with_company(root).l10n_ca_sin for root in roots} - {False, ""}
        numbers |= {(kept.vat or "")[:9]} - {""} if (kept.vat or "")[:9].isdigit() else set()
        if len(sins) > 1 or len(numbers) > 1:
            raise UserError(self.env._(
                "%(names)s have final or filed slips with different SINs or business numbers, so they look like "
                "different people. Keep both contacts.",
                names=", ".join((src_partners | dst_partner).mapped("display_name")),
            ))

    def _l10n_ca_resolve_slips(self, src_partners, dst_partner):
        """Odoo's merge deletes rows that would break a unique constraint. Two contacts with a slip
        on the same return would lose one slip that way, so a final or filed return blocks the
        merge, and on a draft return the merged contact's slip is removed for recalculation."""
        slips = self.env["l10n.ca.slip"].sudo().search([("partner_id", "in", (src_partners | dst_partner).ids)])
        for slip_return in slips.return_id:
            on_return = slips.filtered(lambda s, r=slip_return: s.return_id == r)
            if len(on_return.partner_id) < 2:
                continue
            if slip_return.state != "draft":
                raise UserError(self.env._(
                    "%(names)s each have a slip on %(slip_return)s, which is final or filed. Merging would delete "
                    "one of them. Cancel the duplicate slip in an amendment first, or keep both contacts.",
                    names=", ".join(on_return.partner_id.mapped("display_name")),
                    slip_return=slip_return.display_name,
                ))
            duplicates = on_return.filtered(lambda s: s.partner_id != dst_partner)
            if any(slip._has_adjustment() for slip in duplicates):
                raise UserError(self.env._(
                    "The slip for %(names)s on %(slip_return)s has an adjustment. Move it to %(kept)s's slip "
                    "before merging.",
                    names=", ".join(duplicates.partner_id.mapped("display_name")),
                    slip_return=slip_return.display_name,
                    kept=dst_partner.display_name,
                ))
            duplicates.unlink()
            slip_return.message_post(body=self.env._(
                "Contacts merged into %s. Recalculate this return to combine their payments.", dst_partner.display_name
            ), subtype_xmlid="mail.mt_note")

    def _l10n_ca_carried_values(self, src_partners, dst_partner):
        values = {}
        if not (self.env.su or self.env.user.has_group("account.group_account_manager")):
            return values
        for name in CARRIED_FIELDS:
            if dst_partner.sudo()[name]:
                continue
            donor = src_partners.sudo().filtered(name)[:1]
            if donor:
                values[name] = donor[name]
        return values
