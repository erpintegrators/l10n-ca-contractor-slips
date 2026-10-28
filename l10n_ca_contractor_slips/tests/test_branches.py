# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Branches, and the checks that keep a return in step with the books."""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestBranches(L10nCaSlipsCommon):

    def _branch_with_paid_bill(self, name="Lethbridge branch", vendor=None):
        branch = self._create_company(name=name, parent_id=self.company.id)
        self.env.user.company_ids |= branch
        vendor = vendor or self.contractor_b
        bill = self.env["account.move"].with_company(branch).create({
            "move_type": "in_invoice", "partner_id": vendor.id, "invoice_date": "2026-03-01", "company_id": branch.id,
            "invoice_line_ids": [Command.create({
                "name": "Fees", "account_id": self.fees_account.id, "price_unit": 900.0, "tax_ids": [],
            })],
        })
        bill.action_post()
        self._register_payment(bill.with_company(branch), payment_date="2026-03-10")
        return branch

    # Branches

    def test_archived_branch_still_counts(self):
        branch = self._branch_with_paid_bill()
        self.env.user.company_ids -= branch
        branch.active = False
        slip_return = self._return()
        self.assertAlmostEqual(self._slip(slip_return, self.contractor_b).amount_reported, 900.0)
        self.assertIn("archived branch Lethbridge branch", slip_return.warning_message)

    def test_vendor_flagged_only_in_a_branch_is_pointed_out(self):
        vendor = self.env["res.partner"].create({
            "name": "Erin Park", "l10n_ca_recipient_type": "1",
            "street": "2 Main St", "city": "Lethbridge", "zip": "T1J 0A1",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        branch = self._branch_with_paid_bill(vendor=vendor)
        vendor.with_company(branch).l10n_ca_slip_type = "t4a"
        self.assertTrue(vendor.with_company(branch).l10n_ca_slip_on_branch)
        self.assertFalse(vendor.with_company(self.company).l10n_ca_slip_on_branch)
        slip_return = self._return()
        self.assertIn("Erin Park is flagged for this slip only while working in Lethbridge branch", slip_return.warning_message)

    def test_portal_user_invited_from_a_branch_sees_their_slip(self):
        branch = self._branch_with_paid_bill()
        portal = self._user("bailey.branch", ["base.group_portal"], companies=branch, partner=self.contractor_b)
        slip_return = self._return()
        self._finalize(slip_return)
        self.assertEqual(self.env["l10n.ca.slip"].with_user(portal).search([]), self._slip(slip_return, self.contractor_b))
        other_user = self._user("casey.branch", ["base.group_portal"], companies=branch, partner=self.contractor_c)
        self.assertFalse(self.env["l10n.ca.slip"].with_user(other_user).search([]))

    # Finalize files what the books say now

    def test_cancelled_payment_after_calculation_blocks_finalize(self):
        payment = self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1500.0), "2026-03-10")
        slip_return = self._return()
        payment.action_cancel()
        with self.assertRaisesRegex(UserError, "Recalculate first.*Alex Martin"):
            self._finalize(slip_return)
        slip_return.action_compute()
        self.assertFalse(slip_return.slip_ids)

    def test_corrected_sin_after_calculation_blocks_finalize(self):
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self.contractor_c.l10n_ca_sin = "246454201"
        with self.assertRaisesRegex(UserError, "Recalculate first.*Casey Roy"):
            self._finalize(slip_return)
        slip_return.action_compute()
        root = self._finalize(slip_return)
        self.assertEqual(root.findtext(".//T4ASlip/sin"), "246454201")

    def test_new_contractor_after_calculation_blocks_finalize(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._pay(self._fee_bill(self.contractor_b, "2026-04-01", 900.0), "2026-04-10")
        with self.assertRaisesRegex(UserError, "Recalculate first.*Bailey Chen"):
            self._finalize(slip_return)

    # Amendments and going back to draft

    def test_amendment_warns_when_t5018_settings_changed(self):
        self._pay(self._bill(self.sub_corp, "2026-07-01", [
            (8000.0, self.construction_account, self.gst), (1000.0, self.goods_product, self.gst),
        ]), "2026-07-20")
        original = self._filed(self._return("t5018"))
        self.assertTrue(original.filed_settings)
        self.company.l10n_ca_t5018_include_mixed_goods = not self.company.l10n_ca_t5018_include_mixed_goods
        amendment = self._amend(original)
        amendment.action_compute()
        self.assertIn("settings for mixed bills or the slip threshold changed", amendment.warning_message)

    def test_back_to_draft_clears_report_codes(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        self.assertEqual(slip_return.slip_ids.rpt_tcd, "O")
        slip_return.action_reset_to_draft()
        self.assertFalse(slip_return.slip_ids.rpt_tcd)

    # Email upkeep and warnings

    def test_failed_emails_are_deleted_after_a_month(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        self._send(slip_return)
        slip = slip_return.slip_ids.sudo()
        mail = slip.mail_id
        mail.write({"state": "exception", "failure_reason": "Mailbox full"})
        self.env["l10n.ca.slip"]._purge_failed_emails()
        self.assertTrue(mail.exists())
        slip.sent_date = fields.Datetime.now() - timedelta(days=31)
        self.env["l10n.ca.slip"]._purge_failed_emails()
        self.assertFalse(mail.exists())
        self.assertIn("Mailbox full", slip.message_ids[0].body)

    def test_payment_matched_to_a_bill_reset_to_draft_is_flagged(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
        self._pay(self._fee_bill(self.contractor_a, "2026-02-01", 700.0), "2026-02-10")
        self._pay(bill, "2026-03-10")
        bill.button_draft()
        slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_reported, 700.0)
        self.assertIn("not matched to a posted bill", slip.warning_message)

    def test_slip_recipient_fields_are_read_only_on_the_form(self):
        arch = self.env.ref("l10n_ca_contractor_slips.view_l10n_ca_slip_form").arch_db
        self.assertIn("refresh on each recalculation", arch)
        self.assertNotIn('name="surname" invisible="recipient_type != \'1\'" readonly="state', arch)
