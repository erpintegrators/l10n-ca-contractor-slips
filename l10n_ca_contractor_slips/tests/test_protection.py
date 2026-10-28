# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""What keeps SINs private and filed returns intact."""
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .. import uninstall_hook
from .common import OTHER_SIN, VALID_SIN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestProtection(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        cls.sales_user = cls._user("sales.protect", ["base.group_user", "base.group_partner_manager"])
        cls.clerk = cls._user("clerk.protect", ["base.group_user", "account.group_account_invoice"])

    def _final(self, amount=900.0):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", amount), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        return slip_return

    # The slip PDF stays out of the chatter

    def test_slip_template_is_not_offered_in_the_chatter(self):
        template = self.env.ref("l10n_ca_contractor_slips.mail_template_l10n_ca_slip")
        self.assertEqual(template.user_id, self.env.ref("base.user_root"))
        self.assertFalse(template.report_template_ids)

    def test_files_cannot_be_attached_to_slip_messages(self):
        slip = self._final().slip_ids
        with self.assertRaisesRegex(UserError, "Files cannot be attached"):
            slip.message_post(body="Copy", attachments=[("slip.pdf", b"%PDF-1.4")])
        composer = self.env["mail.compose.message"].with_context(
            default_model="l10n.ca.slip", default_res_ids=slip.ids, default_composition_mode="comment",
        ).create({"body": "Resend", "attachment_ids": [Command.create({"name": "slip.pdf", "raw": b"%PDF-1.4"})]})
        with self.assertRaises(UserError):
            composer.action_send_mail()

    # Email goes where consent was given

    def test_changed_address_stops_a_queued_email(self):
        slip_return = self._final()
        slip_return.action_send_slips()
        slip = slip_return.slip_ids
        self.contractor_a.with_user(self.sales_user).email = "someone.else@example.com"
        self.assertFalse(slip.sudo().send_requested_uid)
        self.assertIn("email address changed while it waited", slip.message_ids[0].body)
        self.assertIn("email address changed while it waited", slip_return.message_ids[0].body)
        slip.sudo()._send_pending()
        self.assertFalse(self.env["mail.mail"].sudo().search([("email_to", "ilike", "someone.else")]))
        self.assertFalse(slip.sudo().mail_id)

    def test_consent_given_again_for_a_new_address_does_not_send_to_the_old_one(self):
        slip_return = self._final()
        slip_return.action_send_slips()
        slip = slip_return.slip_ids.sudo()
        # Address and consent change together without going through the contact form.
        self.env.cr.execute(
            "UPDATE res_partner SET email = 'alex.new@example.com' WHERE id = %s", (self.contractor_a.id,)
        )
        self.contractor_a.invalidate_recordset(["email", "email_formatted"])
        slip._send_pending()
        self.assertFalse(self.env["mail.mail"].sudo().search([("email_to", "ilike", "alex@example.com")]))
        self.assertIn("no longer covers the address", slip.message_ids[0].body)

    def test_email_is_sent_by_the_user_who_asked(self):
        slip_return = self._final()
        self._send(slip_return)
        mail = slip_return.slip_ids.sudo().mail_id
        self.assertEqual(mail.author_id, self.env.user.partner_id)
        self.assertEqual(mail.email_to, '"Alex Martin" <alex@example.com>')

    def test_slips_already_emailed_are_not_sent_twice(self):
        slip_return = self._final()
        self._send(slip_return)
        self._send(slip_return)
        self.assertEqual(len(self._slip_mail(self.contractor_a)), 1)
        self.assertIn("already emailed", slip_return.message_ids[0].body)

    def test_back_to_draft_withdraws_queued_emails(self):
        slip_return = self._final()
        self._send(slip_return)
        mail = slip_return.slip_ids.sudo().mail_id
        slip_return.action_reset_to_draft()
        self.assertFalse(mail.exists())
        self.assertFalse(slip_return.slip_ids.sent_date)
        self.assertFalse(slip_return.slip_ids.email_state)

    def test_queue_runs_in_batches(self):
        slip_return = self._final()
        slip_return.action_send_slips()
        cron = self.env.ref("l10n_ca_contractor_slips.ir_cron_send_slips")
        self.assertEqual(cron.code, "model._cron_send_pending()")
        slip = slip_return.slip_ids
        self.assertEqual(slip.sudo().send_requested_uid, self.env.user)
        self.assertEqual(slip.sudo().send_to_email, self.contractor_a.email_formatted)

    # Bills keep the slip their vendor sets

    def test_billing_user_cannot_create_an_unreported_bill(self):
        Move = self.env["account.move"].with_user(self.clerk)
        values = {
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-03-01",
            "invoice_line_ids": [Command.create({"name": "Fees", "account_id": self.fees_account.id, "price_unit": 900.0})],
        }
        with self.assertRaises(AccessError):
            Move.create({**values, "l10n_ca_slip_type": "none"})
        bill = Move.with_context(default_l10n_ca_slip_type="none").create(values)
        bill.action_post()
        self.assertEqual(bill.l10n_ca_slip_type, "t4a")

    def test_branch_only_user_can_post_bills(self):
        branch = self._create_company(name="Okotoks branch", parent_id=self.company.id)
        branch_clerk = self._user("branch.clerk", ["base.group_user", "account.group_account_invoice"], companies=branch)
        bill = self.env["account.move"].with_user(branch_clerk).with_company(branch).create({
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-03-01",
            "invoice_line_ids": [Command.create({
                "name": "Fees", "account_id": self.fees_account.with_company(branch).id, "price_unit": 900.0,
            })],
        })
        bill.action_post()
        self.assertEqual(bill.state, "posted")
        self.assertEqual(bill.l10n_ca_slip_type, "t4a")

    # Filed returns stay as filed

    def test_filed_return_cannot_be_rewritten(self):
        slip_return = self._final()
        slip_return.action_mark_filed()
        slip = slip_return.slip_ids
        for vals in ({"state": "draft"}, {"xml_file": False}, {"sbmt_ref_id": "X"}, {"filed_date": False}):
            with self.subTest(vals=vals), self.assertRaises(UserError):
                slip_return.write(vals)
        for vals in ({"rpt_tcd": "A"}, {"superseded": True}, {"origin_slip_id": slip.id}):
            with self.subTest(vals=vals), self.assertRaises(UserError):
                slip.write(vals)
        with self.assertRaises(UserError):
            slip.line_ids[:1].write({"amount_base": 1.0})
        with self.assertRaises(UserError):
            slip.line_ids.unlink()
        with self.assertRaises(UserError):
            self.env["l10n.ca.slip.line"].create({
                "slip_id": slip.id, "date": "2026-03-01", "source": "bank", "amount_base": 5.0,
            })
        self.assertEqual(slip_return.state, "filed")

    def test_return_state_is_set_only_by_its_buttons(self):
        with self.assertRaises(UserError):
            self.env["l10n.ca.slip.return"].create({"slip_type": "t4a", "year": 2026, "state": "filed"})
        draft = self._return(compute=False)
        with self.assertRaises(UserError):
            draft.write({"state": "final"})

    def test_read_only_accountant_cannot_run_the_steps(self):
        auditor = self._user("auditor.protect", ["base.group_user", "account.group_account_readonly"])
        slip_return = self._final()
        for action in ("action_mark_filed", "action_reset_to_draft", "action_send_slips"):
            with self.subTest(action=action), self.assertRaises(AccessError):
                getattr(slip_return.with_user(auditor), action)()

    # Uninstall

    def test_uninstall_removes_waiting_slip_emails(self):
        slip_return = self._final()
        self._send(slip_return)
        mail = slip_return.slip_ids.sudo().mail_id
        mail.write({"state": "exception", "failure_reason": "Mailbox full"})
        attachment = mail.attachment_ids
        unrelated = self.env["ir.attachment"].create({"name": "l10nXcaXcontractorXslips.xsd", "raw": b"x"})
        uninstall_hook(self.env)
        self.assertFalse(mail.exists())
        self.assertFalse(attachment.exists())
        self.assertTrue(unrelated.exists())
        # The tags come off the accounts, so they can be removed with the module.
        self.assertFalse(self.fees_account.tag_ids & self.env.ref("l10n_ca_contractor_slips.account_tag_t4a_fees"))

    # Full SIN

    def test_other_company_administrator_gets_the_masked_copy(self):
        slip = self._final().slip_ids
        other = self.setup_other_company()["company"]
        outsider = self._user("outsider.protect", ["base.group_user", "account.group_account_manager"], companies=other)
        self.assertFalse(slip.with_user(outsider).sudo()._l10n_ca_full_sin_allowed())
        assistant = self.env["res.partner"].create({"name": "Alex assistant", "parent_id": self.contractor_a.id})
        portal = self._user("assistant.protect", ["base.group_portal"], partner=assistant)
        self.assertFalse(slip.with_user(portal).sudo()._l10n_ca_full_sin_allowed())
        recipient = self._user("alex.protect", ["base.group_portal"], partner=self.contractor_a)
        self.assertTrue(slip.with_user(recipient).sudo()._l10n_ca_full_sin_allowed())
        self.assertTrue(slip._l10n_ca_full_sin_allowed())
        self.assertEqual(slip.sudo().sin, VALID_SIN)

    # Found by the third security review

    def test_files_cannot_be_uploaded_onto_a_slip(self):
        slip = self._final().slip_ids
        with self.assertRaisesRegex(UserError, "Files cannot be attached to slips"):
            self.env["ir.attachment"].create({
                "name": "slip.pdf", "raw": b"%PDF-1.4", "res_model": "l10n.ca.slip", "res_id": slip.id,
            })
        loose = self.env["ir.attachment"].create({"name": "slip.pdf", "raw": b"%PDF-1.4"})
        with self.assertRaisesRegex(UserError, "Files cannot be attached to slips"):
            loose.write({"res_model": "l10n.ca.slip", "res_id": slip.id})

    def test_contacts_with_filed_slips_for_different_people_cannot_be_merged(self):
        self._pay(self._fee_bill(self.contractor_b, "2026-04-01", 900.0), "2026-04-10")
        self.assertEqual(len(self._final().slip_ids), 2)
        with self.assertRaisesRegex(UserError, "look like different people"):
            self.env["base.partner.merge.automatic.wizard"]._merge(
                (self.contractor_a | self.contractor_b).ids, self.contractor_a
            )

    def test_changed_address_withdraws_an_email_already_in_the_outgoing_queue(self):
        slip_return = self._final()
        self._send(slip_return)
        slip = slip_return.slip_ids.sudo()
        mail = slip.mail_id
        self.assertEqual(mail.state, "outgoing")
        self.contractor_a.email = "alex.moved@example.com"
        self.assertFalse(mail.exists())
        self.assertFalse(slip.sent_date)
        self.assertIn("email address changed while it waited", slip.message_ids[0].body)

    # Found by the architecture review

    def test_default_get_takes_odoos_parameter_name(self):
        # Odoo passes the field list by the name "fields".
        for model in ("res.partner", "account.move", "l10n.ca.slip.return"):
            with self.subTest(model=model):
                self.assertIsInstance(self.env[model].default_get(fields=["display_name"]), dict)

    def test_posting_a_contractor_bill_is_not_a_manual_change(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
        self.assertEqual(bill.l10n_ca_slip_type, "t4a")
        self.assertFalse(bill.is_manually_modified)

    def test_internal_consent_flag_from_a_client_does_not_skip_the_rules(self):
        self.contractor_a.sudo().with_context(l10n_ca_main_company_write=True).write({"email": "alex.other@example.com"})
        self.assertFalse(self.contractor_a.l10n_ca_slip_email_consent)
        with self.assertRaises(AccessError):
            self.contractor_a.with_user(self.sales_user).with_context(l10n_ca_main_company_write=True).write(
                {"l10n_ca_slip_email_consent": True}
            )

    def test_filed_slip_cannot_be_merged_into_a_contact_with_another_sin(self):
        self._final()
        other_person = self.env["res.partner"].create({"name": "Robin Hale", "l10n_ca_sin": OTHER_SIN})
        with self.assertRaisesRegex(UserError, "look like different people"):
            self.env["base.partner.merge.automatic.wizard"]._merge(
                (self.contractor_a | other_person).ids, other_person
            )
