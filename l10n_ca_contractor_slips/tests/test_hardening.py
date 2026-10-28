# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Access between companies, locks on stored fields, and the email queue's edge cases."""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestHardening(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})

    def _final(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        return slip_return

    def _html(self, slips, data=None):
        content, _type = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slips.ids, data=data
        )
        return content.decode()

    # Between companies

    def test_another_companys_accountant_cannot_reach_slips_issued_to_their_company(self):
        slip = self._final().slip_ids
        other = self.setup_other_company()["company"]
        accountant = self._user("beta.accountant", ["base.group_user", "account.group_account_manager"],
                                companies=other, partner=self.env["res.partner"].create({
                                    "name": "Beta Accountant", "parent_id": self.contractor_a.id,
                                }))
        self.assertEqual(accountant.partner_id.commercial_partner_id, self.contractor_a)
        Slip = self.env["l10n.ca.slip"].with_user(accountant)
        self.assertFalse(Slip.search([("id", "=", slip.id)]))
        with self.assertRaises(AccessError):
            slip.with_user(accountant).write({"adjustment_reason": "x"})

    # Stored copies cannot reopen a filed slip

    def test_stored_copies_and_totals_cannot_be_written(self):
        slip_return = self._final()
        slip_return.action_mark_filed()
        slip = slip_return.slip_ids
        for vals in (
            {"state": "draft"}, {"year": 1999}, {"slip_type": "t5018"}, {"company_id": self.company.id},
            {"amount_reported": 5000.0}, {"amount_base": 1.0},
            {"mail_id": False}, {"send_requested_uid": self.env.uid}, {"send_to_email": "evil@example.net"},
            {"sent_date": fields.Datetime.now()},
        ):
            with self.subTest(vals=vals), self.assertRaises(UserError):
                slip.write(vals)
        with self.assertRaises(UserError):
            slip.write({"adjustment_base": 5000.0, "adjustment_reason": "x"})

    def test_lock_follows_the_returns_own_state(self):
        slip_return = self._final()
        slip_return.action_mark_filed()
        slip = slip_return.slip_ids
        # Even if the slip's stored copy were out of step, the return's state decides.
        slip.sudo().write({"state": "draft"})
        with self.assertRaises(UserError):
            slip.write({"adjustment_base": 5000.0, "adjustment_reason": "x"})
        with self.assertRaises(UserError):
            slip.unlink()

    def test_slips_cannot_be_added_to_a_filed_return(self):
        slip_return = self._final()
        slip_return.action_mark_filed()
        with self.assertRaisesRegex(UserError, "draft return"):
            self.env["l10n.ca.slip"].create({
                "return_id": slip_return.id, "partner_id": self.contractor_b.id, "recipient_type": "1",
            })
        with self.assertRaisesRegex(UserError, "draft return"):
            slip_return.write({"slip_ids": [Command.create({"partner_id": self.contractor_b.id, "recipient_type": "1"})]})

    def test_report_options_cannot_multiply_copies(self):
        slip = self._final().slip_ids
        html = self._html(slip, {"l10n_ca_copies": 40, "l10n_ca_duplicate": "yes"})
        self.assertEqual(html.count('class="o_l10n_ca_slip"'), 1)
        self.assertNotIn("DUPLICATE", html)

    # Contacts

    def test_consent_date_is_set_only_by_the_consent_box(self):
        sales = self._user("sales.hardening", ["base.group_user", "base.group_partner_manager"])
        with self.assertRaises(AccessError):
            self.contractor_a.with_user(sales).write({"l10n_ca_slip_email_consent_date": "2019-01-01"})

    def test_merge_by_a_salesperson_cannot_drop_a_sin(self):
        sales = self._user("sales.merge", ["base.group_user", "base.group_partner_manager"])
        duplicate = self.env["res.partner"].create({"name": "Alex Martin", "email": "alex@example.com"})
        with self.assertRaisesRegex(UserError, "accounting administrator"):
            self.env["base.partner.merge.automatic.wizard"].with_user(sales)._merge(
                (self.contractor_a | duplicate).ids, duplicate
            )

    # Email queue

    def test_requester_who_lost_rights_does_not_send(self):
        controller = self._user("controller.queue", ["base.group_user", "account.group_account_manager"])
        slip_return = self._final()
        slip_return.with_user(controller).action_send_slips()
        controller.active = False
        slip = slip_return.slip_ids.sudo()
        slip._send_pending()
        self.assertFalse(slip.mail_id)
        self.assertFalse(slip.send_requested_uid)
        self.assertIn("can no longer send slips", slip_return.message_ids[0].body)

    def test_template_is_archived_and_still_sends(self):
        template = self.env.ref("l10n_ca_contractor_slips.mail_template_l10n_ca_slip")
        self.assertFalse(template.active)
        slip_return = self._final()
        self._send(slip_return)
        self.assertTrue(slip_return.slip_ids.sudo().mail_id)

    def test_purged_or_cancelled_email_reads_as_not_sent(self):
        slip_return = self._final()
        self._send(slip_return)
        slip = slip_return.slip_ids.sudo()
        slip.mail_id.write({"state": "cancel"})
        slip.write({"sent_date": fields.Datetime.now() - timedelta(days=31)})
        self.env["l10n.ca.slip"]._purge_failed_emails()
        self.assertFalse(slip.mail_id)
        self.assertFalse(slip.email_state)
        self._send(slip_return)
        self.assertTrue(slip.mail_id)

    def test_back_to_draft_removes_a_cancelled_email(self):
        slip_return = self._final()
        self._send(slip_return)
        mail = slip_return.slip_ids.sudo().mail_id
        mail.write({"state": "cancel"})
        slip_return.action_reset_to_draft()
        self.assertFalse(mail.exists())

    def test_head_office_accountant_can_deliver_without_branch_access(self):
        branch = self._create_company(name="Airdrie branch", parent_id=self.company.id)
        slip_return = self._final()
        self.env.user.company_ids |= branch
        controller = self._user("hq.only", ["base.group_user", "account.group_account_manager"])
        slip_return.with_user(controller).action_print_slips()
        slip_return.with_user(controller).action_send_slips()
        self.assertTrue(slip_return.slip_ids.sudo().send_requested_uid)
