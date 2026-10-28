# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Goods and services mixes, flag changes and the amendment workflow."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import PRINTED_SIN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestMixesAndWorkflow(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.auditor = cls.env["res.users"].create({
            "name": "Auditor", "login": "auditor.r2",
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("account.group_account_readonly").id])],
            "company_ids": [Command.set(cls.company.ids)], "company_id": cls.company.id,
        })

    def _filed(self, slip_return):
        self._finalize(slip_return)
        slip_return.action_mark_filed()
        return slip_return

    def _amend(self, slip_return):
        return self.env["l10n.ca.slip.return"].browse(slip_return.action_create_amendment()["res_id"])

    def _render(self, slips, user=None):
        Report = self.env["ir.actions.report"]
        if user:
            Report = Report.with_user(user).sudo()
        html, _type = Report._render_qweb_html("l10n_ca_contractor_slips.action_report_l10n_ca_slip", slips.ids)
        return html.decode()

    # SIN exposure

    def test_token_link_masks_sin_and_recipient_sees_it(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        public = self.env.ref("base.public_user")
        self.assertNotIn(PRINTED_SIN, self._render(slip_return.slip_ids, public))
        portal = self.env["res.users"].create({
            "name": "Alex", "login": "alex.r2", "partner_id": self.contractor_a.id,
            "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
        })
        self.assertIn(PRINTED_SIN, self._render(slip_return.slip_ids, portal))
        other = self.env["res.users"].create({
            "name": "Bailey", "login": "bailey.r2", "partner_id": self.contractor_b.id,
            "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
        })
        self.assertNotIn(PRINTED_SIN, self._render(slip_return.slip_ids, other))

    # Engine

    def test_blocked_bill_keeps_its_payments(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 2000.0)
        self._pay(bill, "2026-03-10", amount=1000.0)
        bill.action_toggle_block_payment()
        self.assertEqual(bill.payment_state, "blocked")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 1000.0)

    def test_write_off_to_a_tagged_account_counts_once(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        self._register_payment(bill, payment_date="2026-03-10", journal_id=self.bank_journal.id, amount=980.0,
                               payment_difference_handling="reconcile",
                               writeoff_account_id=self.fees_account.id, writeoff_label="Discount")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 980.0)

    def test_credit_note_on_goods_shifts_the_mix(self):
        self.company.l10n_ca_t5018_include_mixed_goods = False
        bill = self._bill(self.sub_corp, "2026-03-01", [
            (1000.0, self.construction_account, self.gst),
            (1000.0, self.goods_product, self.gst),
        ])
        refund = self._bill(self.sub_corp, "2026-03-05", [(1000.0, self.goods_product, self.gst)], move_type="in_refund")
        (bill + refund).line_ids.filtered(lambda line: line.display_type == "payment_term").reconcile()
        self._pay(bill, "2026-03-20")
        slip = self._return("t5018").slip_ids
        self.assertAlmostEqual(slip.amount_base, 1000.0)
        self.assertAlmostEqual(slip.amount_reported, 1050.0)

    def test_credit_note_on_services_shifts_the_mix(self):
        self.company.l10n_ca_t5018_include_mixed_goods = False
        bill = self._bill(self.sub_corp, "2026-03-01", [
            (1000.0, self.construction_account, self.gst),
            (1000.0, self.goods_product, self.gst),
        ])
        refund = self._bill(self.sub_corp, "2026-03-05", [(400.0, self.construction_account, self.gst)], move_type="in_refund")
        (bill + refund).line_ids.filtered(lambda line: line.display_type == "payment_term").reconcile()
        self._pay(bill, "2026-03-20")
        slip = self._return("t5018").slip_ids
        self.assertAlmostEqual(slip.amount_base, 600.0)
        self.assertAlmostEqual(slip.amount_reported, 630.0)

    def test_holdback_keeps_gst_out_of_box_048(self):
        bill = self._bill(self.contractor_a, "2026-03-01", [
            (1000.0, self.fees_account, self.gst),
            (-200.0, self.supplies_account, None),
        ])
        self.assertAlmostEqual(bill.amount_total, 850.0)
        self._pay(bill, "2026-03-20")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 800.0)

    # Branches

    def test_branch_contact_and_deselected_branch(self):
        branch = self._create_company(name="Red Deer branch", parent_id=self.company.id)
        self.env.user.company_ids |= branch
        vendor = self.env["res.partner"].create({
            "name": "Dana Lee", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1", "company_id": branch.id,
            "street": "1 Main St", "city": "Red Deer", "zip": "T4N 1A1",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        bill = self.env["account.move"].with_company(branch).create({
            "move_type": "in_invoice", "partner_id": vendor.id, "invoice_date": "2026-03-01", "company_id": branch.id,
            "invoice_line_ids": [Command.create({"name": "Fees", "account_id": self.fees_account.id, "price_unit": 900.0,
                                                 "tax_ids": []})],
        })
        bill.action_post()
        self._register_payment(bill.with_company(branch), payment_date="2026-03-10")
        slip_return = self.env["l10n.ca.slip.return"].with_context(allowed_company_ids=self.company.ids).create(
            {"slip_type": "t4a", "year": 2026}
        )
        slip_return.action_compute()
        self.assertEqual(slip_return.slip_ids.partner_id, vendor)

    # Flag changes

    def test_bills_keep_the_slip_type_they_were_posted_with(self):
        self._pay(self._bill(self.contractor_a, "2026-02-01", [(3000.0, self.service_product, None)]), "2026-02-10")
        self.contractor_a.l10n_ca_slip_type = "t5018"
        self._pay(self._bill(self.contractor_a, "2026-08-01", [(2000.0, self.construction_account, None)]), "2026-08-10")
        self.assertAlmostEqual(self._return("t4a").slip_ids.amount_reported, 3000.0)
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_base, 2000.0)

    def test_bills_posted_before_flagging_follow_the_contact(self):
        self.contractor_b.l10n_ca_slip_type = False
        self._pay(self._fee_bill(self.contractor_b, "2026-02-01", 900.0), "2026-02-10")
        self.contractor_b.l10n_ca_slip_type = "t4a"
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 900.0)

    def test_bill_marked_not_reported(self):
        bill = self._fee_bill(self.contractor_a, "2026-02-01", 900.0)
        bill.l10n_ca_slip_type = "none"
        self._pay(bill, "2026-02-10")
        self.assertFalse(self._return().slip_ids)

    # Workflow

    def test_cancelled_slip_repeats_the_filed_values(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        original = self._filed(self._return())
        self.contractor_a.street = "99 New Street"
        amendment = self._amend(original)
        amendment.action_compute()
        slip = amendment.slip_ids
        slip.is_cancelled = True
        amendment.amendment_note = "Paid in error to the wrong contact."
        root = self._finalize(amendment)
        self.assertEqual(root.findtext(".//T4ASlip/rpt_tcd"), "C")
        self.assertEqual(root.findtext(".//T4ASlip/T4A_AMT/fee_or_oth_srvc_amt"), "1000.00")
        self.assertEqual(root.findtext(".//T4ASlip/RCPNT_ADDR/addr_l1_txt"), "12 River Road")

    def test_cancelled_recipient_can_be_reported_again(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        original = self._filed(self._return())
        amendment = self._amend(original)
        amendment.slip_ids.is_cancelled = True
        amendment.amendment_note = "Wrong year."
        self._filed(amendment)
        again = self._return()
        self.assertEqual(again.slip_ids.partner_id, self.contractor_a)

    def test_two_original_returns_cannot_both_be_finalized(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        first, second = self._return(), self._return()
        self._finalize(first)
        with self.assertRaisesRegex(UserError, "already"):
            second.action_finalize()

    def test_older_return_does_not_send_superseded_slips(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        original = self._filed(self._return())
        amendment = self._amend(original)
        amendment.slip_ids.write({"adjustment_base": 500.0, "adjustment_reason": "Missed invoice"})
        amendment.amendment_note = "Raised to 1,500.00."
        self._finalize(amendment)
        self._send(original)
        self.assertFalse(self._slip_mail(self.contractor_a))
        with self.assertRaises(UserError):
            original.action_print_slips()

    # Province

    def test_canadian_recipient_needs_a_province(self):
        self.contractor_a.state_id = False
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        with self.assertRaisesRegex(UserError, "province"):
            slip_return.action_finalize()
