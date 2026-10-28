# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestT4AEngine(L10nCaSlipsCommon):

    @contextmanager
    def _payments_without_entries(self):
        """Odoo records payments without a journal entry only when the accountant app is
        installed; this reproduces that mode on Community."""
        with patch.object(type(self.env["account.move"]), "_get_invoice_in_payment_state", lambda self: "in_payment"):
            yield

    def test_t5_threshold_is_more_than_500(self):
        for partner, amount in ((self.contractor_a, 600.0), (self.contractor_b, 500.0), (self.contractor_c, 499.0)):
            self._pay(self._fee_bill(partner, "2026-02-01", amount, taxes=self.gst), "2026-02-15")
        slip_return = self._return()
        self.assertEqual(slip_return.slip_ids.partner_id, self.contractor_a)
        self.assertAlmostEqual(self._slip(slip_return, self.contractor_a).amount_reported, 600.0)

    def test_t6_cash_basis_across_years(self):
        bill = self._fee_bill(self.contractor_a, "2026-12-15", 1000.0)
        self._pay(bill, "2027-01-10")
        self.assertFalse(self._return(year=2026).slip_ids)
        slip = self._return(year=2027).slip_ids
        self.assertEqual(slip.partner_id, self.contractor_a)
        self.assertAlmostEqual(slip.amount_reported, 1000.0)

    def test_t7_partial_payments(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0, taxes=self.gst)
        self._pay(bill, "2026-03-15", amount=525.0)
        self._pay(bill, "2026-04-15", amount=525.0)
        slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_reported, 1000.0)
        self.assertEqual(len(slip.line_ids), 2)

    def test_t7_partial_payment_split_across_years(self):
        bill = self._fee_bill(self.contractor_a, "2026-11-01", 1400.0)
        self._pay(bill, "2026-12-20", amount=700.0)
        self._pay(bill, "2027-01-05", amount=700.0)
        self.assertAlmostEqual(self._return(year=2026).slip_ids.amount_reported, 700.0)
        self.assertAlmostEqual(self._return(year=2027).slip_ids.amount_reported, 700.0)

    def test_t8_refund_received(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        self._pay(bill, "2026-03-15")
        refund = self._fee_bill(self.contractor_a, "2026-05-01", 200.0, move_type="in_refund")
        self._pay(refund, "2026-05-10")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 800.0)

    def test_t8_credit_note_applied_to_bill_is_not_cash(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        refund = self._fee_bill(self.contractor_a, "2026-03-05", 200.0, move_type="in_refund")
        (bill + refund).line_ids.filtered(lambda line: line.display_type == "payment_term").reconcile()
        self._pay(bill, "2026-03-20")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 800.0)

    def test_t9_cancelled_payment(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 700.0)
        payment = self._pay(bill, "2026-03-15")
        payment.action_draft()
        payment.action_cancel()
        self.assertFalse(self._return().slip_ids)

    def test_t10_foreign_currency_uses_payment_date_rate(self):
        usd = self.setup_other_currency("USD", rates=[("2026-01-01", 0.8), ("2026-06-01", 0.625)])
        bill = self._bill(self.contractor_a, "2026-03-01", [(1000.0, self.fees_account, None)], currency=usd)
        self.assertAlmostEqual(bill.amount_total_signed, -1250.0)
        self._pay(bill, "2026-06-15", currency=usd)
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 1600.0)

    def test_t11_goods_excluded(self):
        self._pay(self._bill(self.contractor_a, "2026-03-01", [(800.0, self.fees_account, None)]), "2026-03-10")
        self._pay(self._bill(self.contractor_a, "2026-04-01", [(900.0, self.goods_product, None)]), "2026-04-10")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 800.0)

    def test_service_product_counts_without_a_tagged_account(self):
        self._pay(self._bill(self.contractor_a, "2026-03-01", [(650.0, self.service_product, None)]), "2026-03-10")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 650.0)

    def test_untagged_account_without_product_is_left_out(self):
        self._pay(self._bill(self.contractor_a, "2026-03-01", [(650.0, self.supplies_account, None)]), "2026-03-10")
        self.assertFalse(self._return().slip_ids)

    def test_box_048_excludes_gst(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0, taxes=self.gst), "2026-03-10")
        slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_base, 1000.0)
        self.assertAlmostEqual(slip.amount_incl, 1050.0)
        self.assertAlmostEqual(slip.amount_reported, 1000.0)

    def test_unflagged_vendor_ignored(self):
        self.contractor_a.l10n_ca_slip_type = False
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        self.assertFalse(self._return().slip_ids)

    def test_payments_to_a_contact_roll_up_to_the_company(self):
        person = self.env["res.partner"].create({"name": "Site lead", "parent_id": self.sub_corp.id})
        self.sub_corp.l10n_ca_slip_type = "t4a"
        self._pay(self._fee_bill(person, "2026-03-01", 900.0), "2026-03-10")
        self.assertEqual(self._return().slip_ids.partner_id, self.sub_corp)

    def test_payment_without_journal_entry_counts_once(self):
        with self._payments_without_entries():
            bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
            payment = self._pay(bill, "2026-03-10", journal=self.moveless_journal)
            self.assertFalse(payment.move_id)
            self.assertEqual(payment.state, "in_process")
            slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_reported, 900.0)
        self.assertEqual(slip.line_ids.source, "payment")

    def test_payment_without_entry_then_bank_reconciled_is_not_doubled(self):
        with self._payments_without_entries():
            bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
            payment = self._pay(bill, "2026-03-10", journal=self.moveless_journal)
            self.pay_with_statement_line(bill, self.moveless_journal.id, "2026-03-12", -900.0)
            self.assertEqual(payment.state, "paid")
            slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_reported, 900.0)
        self.assertEqual(slip.line_ids.source, "payment")

    def test_bill_paid_from_bank_statement(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
        self.pay_with_statement_line(bill, self.bank_journal.id, "2026-03-12", -900.0)
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 900.0)

    def test_direct_bank_expense_counts(self):
        entry = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self.bank_journal.id,
            "date": "2026-04-01",
            "line_ids": [
                Command.create({"account_id": self.fees_account.id, "partner_id": self.contractor_a.id, "debit": 750.0}),
                Command.create({"account_id": self.bank_journal.default_account_id.id, "credit": 750.0}),
            ],
        })
        entry.action_post()
        slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_reported, 750.0)
        self.assertEqual(slip.line_ids.source, "bank")

    def test_misc_journal_entry_is_not_cash(self):
        entry = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self.company_data["default_journal_misc"].id,
            "date": "2026-04-01",
            "line_ids": [
                Command.create({"account_id": self.fees_account.id, "partner_id": self.contractor_a.id, "debit": 750.0}),
                Command.create({"account_id": self.supplies_account.id, "credit": 750.0}),
            ],
        })
        entry.action_post()
        self.assertFalse(self._return().slip_ids)

    def test_unmatched_payment_is_flagged(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self.init_payment(-300.0, post=True, date="2026-05-01", partner=self.contractor_a)
        slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_reported, 900.0)
        self.assertIn("not matched to a posted bill", slip.warning_message)

    def test_non_resident_left_out_with_a_note(self):
        self.contractor_b.country_id = self.env.ref("base.us")
        self._pay(self._fee_bill(self.contractor_b, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self.assertFalse(slip_return.slip_ids)
        self.assertIn("outside Canada", slip_return.warning_message)

    def test_other_company_bills_ignored(self):
        other = self.setup_other_company()["company"]
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
        self._pay(bill, "2026-03-10")
        other_return = self.env["l10n.ca.slip.return"].with_company(other).create({"slip_type": "t4a", "year": 2026})
        other_return.action_compute()
        self.assertFalse(other_return.slip_ids)
