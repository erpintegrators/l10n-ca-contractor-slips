# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""The recipient copy: CRA's customized-slip rules, and who gets which copy."""
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestSlipCopies(L10nCaSlipsCommon):

    def _html(self, slips, data=None):
        content, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slips.ids, data=data
        )
        return content.decode()

    def _final(self, slip_type="t4a"):
        if slip_type == "t4a":
            self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 2150.0), "2026-03-10")
        else:
            self._pay(self._bill(self.sub_corp, "2026-07-01", [(24000.0, self.construction_account, self.gst)]), "2026-07-20")
        slip_return = self._return(slip_type)
        self._finalize(slip_return)
        return slip_return

    def test_t4a_copy_follows_the_customized_slip_rules(self):
        html = self._html(self._final().slip_ids)
        for text in (
            "Protected B when completed", "Canada Revenue Agency", "Agence du revenu du Canada", "fip_flag.svg",
            "Payer's name", "Payer's program account number", "Social insurance number",
            "Recipient's program account number", "Fees for services", "Recipient's name and address",
            "Box 048, Fees for services: Report this amount as business or professional income.",
            "See the privacy notice on your return.", "T4A (25)", "2,150.00",
        ):
            self.assertIn(text, html)
        self.assertNotIn("web.external_layout", html)
        self.assertNotIn("o_company_", html)

    def test_t5018_copy_shows_box_20_as_year_month_day(self):
        html = self._html(self._final("t5018").slip_ids)
        for text in (
            "For the period ending", "2026 12 31", "Construction subcontractor payments", "25,200.00",
            "Recipient's business name and address", "This total may include goods and services tax",
            "The payer has sent a copy of this slip to the Canada Revenue Agency.", "T5018 (26)",
        ):
            self.assertIn(text, html)

    def test_paper_delivery_prints_two_copies(self):
        slip_return = self._final()
        action = slip_return.action_print_slips()
        self.assertEqual(action["data"], {"l10n_ca_copies": 2, "ids": slip_return.slip_ids.ids})
        self.assertEqual(self._html(slip_return.slip_ids, action["data"]).count('class="o_l10n_ca_slip"'), 2)
        self.assertEqual(self._html(slip_return.slip_ids).count('class="o_l10n_ca_slip"'), 1)

    def test_reprints_are_marked_duplicate(self):
        slip_return = self._final()
        action = slip_return.action_print_duplicates()
        self.assertIn("DUPLICATE", self._html(slip_return.slip_ids, action["data"]))
        self.assertNotIn("DUPLICATE", self._html(slip_return.slip_ids))

    def test_cancelled_slip_reaches_the_recipient(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        portal = self._user("alex.copies", ["base.group_portal"], partner=self.contractor_a)
        original = self._final()
        original.action_mark_filed()
        cancel = self._amend(original)
        cancel.slip_ids.is_cancelled = True
        cancel.amendment_note = "Alex Martin was paid through payroll."
        self._finalize(cancel)
        slip = cancel.slip_ids
        self.assertEqual(cancel._slips_to_deliver(), slip)
        self.assertIn("CANCELLED", self._html(slip))
        self.assertEqual(self.env["l10n.ca.slip"].with_user(portal).search([]), slip)
        self._send(cancel)
        mail = self._slip_mail(self.contractor_a)
        self.assertIn("has been cancelled", mail.body_html)
        self.assertIn("CANCELLED", self._html(slip))

    def test_send_message_counts_who_needs_paper(self):
        self.contractor_b.write({"email": "bailey@example.com"})
        self._pay(self._fee_bill(self.contractor_b, "2026-03-01", 900.0), "2026-03-10")
        bailey = self._user("bailey.copies", ["base.group_portal"], partner=self.contractor_b)
        self.env["res.users.log"].with_user(bailey).sudo().create({})  # Bailey has signed in before
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        action = self._send(slip_return)
        message = action["params"]["message"]
        self.assertIn("1 recipient(s) without email consent have a portal account", message)
        self.assertIn("two paper copies (Print slips): Casey Roy", message)
        self.assertTrue(action["params"]["sticky"])

    def test_portal_login_never_used_is_listed_for_paper(self):
        self._pay(self._fee_bill(self.contractor_b, "2026-03-01", 900.0), "2026-03-10")
        self._user("bailey.unused", ["base.group_portal"], partner=self.contractor_b)
        slip_return = self._return()
        self._finalize(slip_return)
        message = self._send(slip_return)["params"]["message"]
        self.assertIn("1 recipient(s) have a portal login they have never used", message)
        self.assertIn("two paper copies (Print slips): Bailey Chen", message)

    def test_email_mentions_paper_copies(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self._send(self._final())
        self.assertIn("paper copies", self._slip_mail(self.contractor_a).body_html)

    def test_names_are_sent_in_cras_characters(self):
        person = self.env["res.partner"].create({
            "name": "José Peña", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1",
            "street": "4 Ridge Road", "city": "Calgary", "zip": "T2P 1J9",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        self._pay(self._fee_bill(person, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        slip = self._slip(slip_return, person)
        self.assertIn('CRA receives "Pena" for the surname "Peña".', slip.warning_message)
        root = self._finalize(slip_return)
        names = [node.text for node in root.iter("snm")]
        self.assertIn("Pena", names)

    def test_portal_page_offers_paper_and_marks_cancellations(self):
        arch = self.env.ref("l10n_ca_contractor_slips.portal_slip_page").arch_db
        self.assertIn("If you would rather have paper copies", arch)
        self.assertIn("This slip was cancelled", arch)
        self.assertNotIn("payer has told", arch)

    def test_sole_proprietor_with_a_business_number_needs_no_sin_warning(self):
        self.contractor_c.vat = "897012340RT0001"
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 900.0), "2026-03-10")
        slip = self._slip(self._return(), self.contractor_c)
        self.assertNotIn("No SIN", slip.warning_message or "")
        self.assertTrue(slip.recipient_bn)

    def test_french_users_outside_canada_get_the_french_slip(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"]._load_module_terms(["l10n_ca_contractor_slips"], ["fr_FR"], overwrite=True)
        self.contractor_a.lang = "fr_FR"
        html = self._html(self._final().slip_ids)
        self.assertIn("Protégé B une fois rempli", html)
        self.assertIn("Honoraires ou autres sommes pour services rendus", html)

    def test_duplicates_keep_the_amended_and_cancelled_marks(self):
        original = self._final()
        original.action_mark_filed()
        amendment = self._amend(original)
        amendment.slip_ids.write({"adjustment_base": 100.0, "adjustment_reason": "Late invoice"})
        amendment.amendment_note = "Alex Martin: late invoice of 100.00."
        self._finalize(amendment)
        html = self._html(amendment.slip_ids, amendment.action_print_duplicates()["data"])
        self.assertIn("AMENDED", html)
        self.assertIn("DUPLICATE", html)
        amendment.action_mark_filed()
        cancel = self._amend(amendment)
        cancel.slip_ids.is_cancelled = True
        cancel.amendment_note = "Alex Martin was paid through payroll."
        self._finalize(cancel)
        html = self._html(cancel.slip_ids, cancel.action_print_duplicates()["data"])
        for text in ("CANCELLED", "DUPLICATE", "Do not report the amount on this slip", "This slip cancels"):
            self.assertIn(text, html)
        self.assertNotIn("Report these amounts on your tax return.", html)

    def test_slip_shows_every_cra_identification_box(self):
        t4a = self._html(self._final().slip_ids)
        for text in ("022", "Income tax deducted", "Line 43700", "Last name (print)"):
            self.assertIn(text, t4a)
        self._pay(self._bill(self.sub_corp, "2025-07-01", [(24000.0, self.construction_account, self.gst)]), "2025-07-20")
        t5018 = self._return("t5018", year=2025)
        self._finalize(t5018)
        html = self._html(t5018.slip_ids)
        for text in ("Year Month Day", "Account number", "Do not enter your business number on the copies", "T5018 (26)"):
            self.assertIn(text, html)

    def test_recipient_outside_french_and_english_gets_english(self):
        self.env["res.lang"]._activate_lang("es_ES")
        self.contractor_a.lang = "es_ES"
        slip = self._final().slip_ids
        self.assertEqual(slip._l10n_ca_slip_lang(), "en_US")
        self.assertIn("Protected B when completed", self._html(slip))

    def test_revoked_portal_user_and_paper_requests_are_listed_for_paper(self):
        self._pay(self._fee_bill(self.contractor_b, "2026-03-01", 900.0), "2026-03-10")
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 900.0), "2026-03-10")
        revoked = self._user("bailey.revoked", ["base.group_portal"], partner=self.contractor_b)
        revoked.active = False
        self._user("casey.portal", ["base.group_portal"], partner=self.contractor_c)
        self.contractor_c.l10n_ca_slip_paper = True
        slip_return = self._return()
        self._finalize(slip_return)
        message = slip_return.action_send_slips()["params"]["message"]
        self.assertIn("Bailey Chen", message)
        self.assertIn("Casey Roy", message)
        self.assertNotIn("portal account", message)

    def test_t5018_delivery_is_optional(self):
        self._pay(self._bill(self.sub_corp, "2026-07-01", [(24000.0, self.construction_account, self.gst)]), "2026-07-20")
        slip_return = self._return("t5018")
        self._finalize(slip_return)
        self.assertIn("optional", slip_return.action_send_slips()["params"]["message"])
