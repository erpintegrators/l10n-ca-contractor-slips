# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestDelivery(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for partner, email in ((cls.contractor_a, "alex@example.com"), (cls.contractor_b, "bailey@example.com"),
                               (cls.contractor_c, "casey@example.com")):
            partner.write({"email": email, "l10n_ca_slip_email_consent": True})
        for partner in (cls.contractor_a, cls.contractor_b, cls.contractor_c):
            cls._pay(cls._fee_bill(partner, "2026-03-01", 900.0), "2026-03-10")

    def _final_return(self):
        slip_return = self._return()
        self._finalize(slip_return)
        return slip_return

    def test_t17_each_recipient_gets_only_their_slip(self):
        slip_return = self._final_return()
        self._send(slip_return)
        for slip in slip_return.slip_ids:
            mail = self._slip_mail(slip.partner_id)
            self.assertEqual(len(mail), 1)
            self.assertEqual(mail.email_to, slip.partner_id.email_formatted)
            self.assertFalse(mail.recipient_ids)
            self.assertEqual(len(mail.attachment_ids), 1)
            self.assertIn(slip.partner_id.name, mail.attachment_ids.name)
            self.assertTrue(slip.sent_date)

    def test_no_email_without_consent(self):
        self.contractor_b.l10n_ca_slip_email_consent = False
        slip_return = self._final_return()
        self._send(slip_return)
        slip = self._slip(slip_return, self.contractor_b)
        self.assertFalse(self._slip_mail(self.contractor_b))
        self.assertFalse(slip.sent_date)
        self.assertIn("two paper copies", slip_return.message_ids[0].body)
        self.assertIn("Bailey Chen", slip_return.message_ids[0].body)

    def test_cannot_send_a_draft(self):
        with self.assertRaisesRegex(UserError, "Finalize the return"):
            self._return().action_send_slips()

    def test_pdf_renders(self):
        slip_return = self._final_return()
        content, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slip_return.slip_ids.ids
        )
        html = content.decode()
        start = html.find('class="page"')
        self.assertIn("Statement of Pension, Retirement, Annuity, and Other Income", html)
        self.assertIn("Fees for services", html, html[start:start + 3000])
        self.assertIn("900.00", html, html[start:start + 3000])

    def test_portal_user_sees_only_own_final_slips(self):
        portal_user = self.env["res.users"].create({
            "name": "Alex Martin portal",
            "login": "alex.portal",
            "partner_id": self.contractor_a.id,
            "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
        })
        slip_return = self._return()
        own = self._slip(slip_return, self.contractor_a)
        other = self._slip(slip_return, self.contractor_b)
        Slip = self.env["l10n.ca.slip"].with_user(portal_user)
        self.assertFalse(Slip.search([]))
        self._finalize(slip_return)
        self.assertEqual(Slip.search([]), own)
        with self.assertRaises(AccessError):
            other.with_user(portal_user).check_access("read")
        with self.assertRaises(AccessError):
            own.with_user(portal_user).check_access("write")
        self.assertEqual(own.access_url, f"/my/slips/{own.id}")
        self.assertTrue(own.access_token)

    def test_slip_renders_in_the_recipients_language(self):
        self.env["res.lang"]._activate_lang("fr_CA")
        self.env["ir.module.module"]._load_module_terms(["l10n_ca_contractor_slips"], ["fr_CA"], overwrite=True)
        self.contractor_a.lang = "fr_CA"
        slip_return = self._final_return()
        content, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", self._slip(slip_return, self.contractor_a).ids
        )
        html = content.decode()
        self.assertIn("État du revenu de pension", html)
        self.assertIn("Honoraires ou autres sommes", html)
