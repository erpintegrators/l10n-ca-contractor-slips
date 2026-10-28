# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Edge cases: prepayments, write-offs, branches, portal visibility and amendment chains."""
from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import MASKED_SIN, PRINTED_SIN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestEdgeCases(L10nCaSlipsCommon):

    def _payable(self, move):
        return move.line_ids.filtered(lambda line: line.account_type == "liability_payable" and not line.reconciled)

    def test_prepayment_counts_in_the_year_it_was_paid(self):
        payment = self.init_payment(-900.0, post=True, date="2026-12-15", partner=self.contractor_a)
        bill = self._fee_bill(self.contractor_a, "2027-01-10", 900.0)
        (self._payable(bill) | self._payable(payment.move_id)).reconcile()
        self.assertAlmostEqual(self._return(year=2026).slip_ids.amount_reported, 900.0)
        self.assertFalse(self._return(year=2027).slip_ids)

    def test_write_off_is_not_cash(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        self._register_payment(bill, payment_date="2026-03-10", journal_id=self.bank_journal.id, amount=980.0,
                               payment_difference_handling="reconcile",
                               writeoff_account_id=self.supplies_account.id, writeoff_label="Discount")
        # With Odoo Enterprise the bill stays "in payment" until the bank statement is reconciled.
        self.assertIn(bill.payment_state, ("paid", "in_payment"))
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 980.0)

    def test_branch_bills_reach_the_parent_return(self):
        branch = self._create_company(name="Edmonton branch", parent_id=self.company.id)
        self.env.user.company_ids |= branch
        bill = self.env["account.move"].with_company(branch).create({
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-03-01",
            "company_id": branch.id,
            "invoice_line_ids": [Command.create({"name": "Fees", "account_id": self.fees_account.id, "price_unit": 900.0,
                                                 "tax_ids": []})],
        })
        bill.action_post()
        self._register_payment(bill.with_company(branch), payment_date="2026-03-10")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 900.0)

    def test_negative_ineligible_line_caps_the_ratio(self):
        bill = self._bill(self.sub_corp, "2026-03-01", [
            (10000.0, self.construction_account, None),
            (-1000.0, self.supplies_account, None),
        ])
        self._pay(bill, "2026-03-20")
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 9000.0)

    def test_registered_payment_cleared_next_year_counts_once(self):
        bill = self._fee_bill(self.contractor_a, "2026-12-01", 900.0)
        payment = self._pay(bill, "2026-12-28", journal=self.fallback_journal)
        self._clear_payment_with_statement(payment, "2027-01-03", -900.0)
        self.assertAlmostEqual(self._return(year=2026).slip_ids.amount_reported, 900.0)
        self.assertFalse(self._return(year=2027).slip_ids)

    def test_period_change_leaves_returns_alone(self):
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(2000.0, self.construction_account, None)]), "2026-03-15")
        slip_return = self._return("t5018")
        self._finalize(slip_return)
        slip_return.action_mark_filed()
        self.company.write({"fiscalyear_last_month": "3", "fiscalyear_last_day": 31, "l10n_ca_t5018_period": "fiscal"})
        self.assertEqual((slip_return.date_from, slip_return.date_to), (date(2026, 1, 1), date(2026, 12, 31)))
        with self.assertRaises(UserError):
            slip_return.date_to = date(2027, 3, 31)

    def test_amendments_chain_from_the_latest_filed_return(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        original = self._return()
        self._finalize(original)
        original.action_mark_filed()
        first = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        self._slip(first, self.contractor_a).write({"adjustment_base": 500.0, "adjustment_reason": "Missed invoice"})
        first.amendment_note = "Box 048 raised to 1,500.00."
        self._finalize(first)
        with self.assertRaises(UserError):
            original.action_create_amendment()
        with self.assertRaises(UserError):
            first.action_create_amendment()
        first.action_mark_filed()
        with self.assertRaises(UserError):
            original.action_create_amendment()
        second = self.env["l10n.ca.slip.return"].browse(first.action_create_amendment()["res_id"])
        slip = self._slip(second, self.contractor_a)
        self.assertAlmostEqual(slip.amount_reported, 1500.0)
        slip.write({"adjustment_base": 0.0, "adjustment_reason": False})
        second.amendment_note = "The extra invoice belonged to another contractor."
        root = self._finalize(second)
        self.assertEqual(slip.rpt_tcd, "A")
        self.assertEqual(root.findtext(".//T4ASlip/T4A_AMT/fee_or_oth_srvc_amt"), "1000.00")

    def test_portal_hides_superseded_and_cancelled_slips(self):
        portal_user = self.env["res.users"].create({
            "name": "Alex portal", "login": "alex.p2", "partner_id": self.contractor_a.id,
            "groups_id": [Command.set([self.env.ref("base.group_portal").id])],
        })
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        original = self._return()
        self._finalize(original)
        original.action_mark_filed()
        Slip = self.env["l10n.ca.slip"].with_user(portal_user)
        self.assertEqual(Slip.search([]), original.slip_ids)
        amendment = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        self._slip(amendment, self.contractor_a).write({"adjustment_base": 100.0, "adjustment_reason": "Late invoice"})
        amendment.amendment_note = "Corrected box 048."
        self._finalize(amendment)
        self.assertEqual(Slip.search([]), amendment.slip_ids)
        amendment.action_mark_filed()
        cancel = self.env["l10n.ca.slip.return"].browse(amendment.action_create_amendment()["res_id"])
        cancel.slip_ids.is_cancelled = True
        cancel.amendment_note = "Not a contractor."
        self._finalize(cancel)
        # The recipient is told about the cancellation: only the cancelled copy shows.
        self.assertEqual(Slip.search([]), cancel.slip_ids)
        self.assertEqual(cancel.slip_ids.rpt_tcd, "C")

    def test_sole_proprietor_with_a_business_name_is_flagged_for_review(self):
        self.sub_corp.write({"l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1"})
        self._pay(self._fee_bill(self.sub_corp, "2026-03-01", 900.0), "2026-03-10")
        slip = self._return().slip_ids
        self.assertEqual((slip.surname, slip.given_name), ("Ltd", "Prairie"))
        self.assertIn("split from the contact name", slip.warning_message)


@tagged("post_install", "-at_install")
class TestSinExposure(L10nCaSlipsCommon):

    def test_read_only_accountant_never_sees_full_sin(self):
        auditor = self.env["res.users"].create({
            "name": "Auditor", "login": "auditor.ro",
            "groups_id": [Command.set([self.env.ref("base.group_user").id, self.env.ref("account.group_account_readonly").id])],
            "company_ids": [Command.set(self.company.ids)], "company_id": self.company.id,
        })
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        html, _type = self.env["ir.actions.report"].with_user(auditor)._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slip_return.slip_ids.ids
        )
        self.assertNotIn(PRINTED_SIN, html.decode())
        self.assertIn(MASKED_SIN, html.decode())
        self.assertIn("544", html.decode())
        manager_html, _type = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slip_return.slip_ids.ids
        )
        self.assertIn(PRINTED_SIN, manager_html.decode())
        returned = slip_return.with_user(auditor)
        returned.invalidate_recordset()
        with self.assertRaises(AccessError):
            returned.read(["xml_file"])
