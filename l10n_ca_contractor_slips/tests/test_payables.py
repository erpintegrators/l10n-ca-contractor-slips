# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Payments that settle a journal entry's payable line instead of a bill."""
from odoo import Command
from odoo.tests import tagged

from .common import L10nCaSlipsCommon

WARNING = "settles journal entries"


@tagged("post_install", "-at_install")
class TestPayables(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payable = cls.company_data["default_account_payable"]
        cls.equity = cls.env["account.account"].search([
            ("company_ids", "in", cls.company.id), ("account_type", "=", "equity"),
        ], limit=1)
        cls.holdback_account = cls.env["account.account"].create({
            "name": "Holdbacks payable", "code": "2190HP", "account_type": "liability_current",
            "tag_ids": [Command.set(cls.tag_t5018.ids)],
        })

    def _payable_entry(self, partner, date, amount, account):
        entry = self.env["account.move"].create({
            "move_type": "entry", "date": date,
            "line_ids": [
                Command.create({"account_id": account.id, "partner_id": partner.id, "debit": amount}),
                Command.create({"account_id": self.payable.id, "partner_id": partner.id, "credit": amount}),
            ],
        })
        entry.action_post()
        return entry

    def _pay_entry(self, entry, date):
        payment = self.env["account.payment"].create({
            "payment_type": "outbound", "partner_type": "supplier", "partner_id": entry.line_ids.partner_id.id,
            "amount": abs(sum(entry.line_ids.filtered(lambda l_: l_.account_id == self.payable).mapped("balance"))),
            "date": date, "journal_id": self.bank_journal.id,
        })
        payment.action_post()
        (payment.move_id.line_ids | entry.line_ids).filtered(
            lambda l_: l_.account_id == self.payable and not l_.reconciled
        ).reconcile()
        return payment

    def test_payment_of_an_opening_balance_is_flagged_beside_billed_work(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-02-01", 800.0), "2026-02-10")
        opening = self._payable_entry(self.contractor_a, "2026-01-01", 2500.0, self.equity)
        self._pay_entry(opening, "2026-01-20")
        slip = self._return().slip_ids
        self.assertAlmostEqual(slip.amount_reported, 800.0)
        self.assertIn(WARNING, slip.warning_message)
        self.assertIn(opening.name, slip.warning_message)

    def test_payment_of_an_opening_balance_alone_is_noted_on_the_return(self):
        opening = self._payable_entry(self.contractor_b, "2026-01-01", 3000.0, self.equity)
        self._pay_entry(opening, "2026-01-20")
        slip_return = self._return()
        self.assertFalse(slip_return.slip_ids)
        notes = slip_return.warning_message or ""
        self.assertIn("Bailey Chen:", notes)
        self.assertIn("3,000.00", notes)
        self.assertIn("paid in the period " + WARNING, notes)

    def test_holdback_released_by_journal_entry_is_noted(self):
        bill = self._bill(self.sub_corp, "2026-06-01", [
            (10000.0, self.construction_account, self.gst), (-1000.0, self.holdback_account, None),
        ])
        self._pay(bill, "2026-06-20")
        release = self._payable_entry(self.sub_corp, "2027-02-01", 1000.0, self.holdback_account)
        self._pay_entry(release, "2027-02-15")
        self.assertAlmostEqual(self._return("t5018", year=2026).slip_ids.amount_reported, 9500.0)
        later = self._return("t5018", year=2027)
        self.assertFalse(later.slip_ids)
        self.assertIn("Prairie Framing Ltd:", later.warning_message or "")
        self.assertIn(WARNING, later.warning_message or "")

    def test_payment_matched_to_a_bill_is_not_flagged(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-02-01", 800.0), "2026-02-10")
        self.assertNotIn(WARNING, self._return().slip_ids.warning_message or "")
