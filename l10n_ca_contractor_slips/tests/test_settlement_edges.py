# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Settlement entries that are not plain payments."""
from freezegun import freeze_time

from odoo import Command
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestSettlementEdges(L10nCaSlipsCommon):

    def _payable(self, move):
        return move.line_ids.filtered(lambda l_: l_.display_type == "payment_term")

    def _entry(self, journal, date, lines):
        entry = self.env["account.move"].create({
            "move_type": "entry", "journal_id": journal.id, "date": date,
            "line_ids": [Command.create(vals) for vals in lines],
        })
        entry.action_post()
        return entry

    def test_credit_note_on_another_slip_type_stays_out(self):
        bill = self._bill(self.sub_corp, "2026-03-01", [(10000.0, self.construction_account, None)])
        self._pay(bill, "2026-03-10", amount=7000.0)
        self.sub_corp.l10n_ca_slip_type = "t4a"
        credit = self._bill(self.sub_corp, "2026-04-01", [(3000.0, self.fees_account, None)], move_type="in_refund")
        self.assertEqual(credit.l10n_ca_slip_type, "t4a")
        (self._payable(bill) | self._payable(credit)).reconcile()
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 7000.0)
        self.assertFalse(self._return("t4a").slip_ids)

    def test_discount_applies_to_the_bill_side_only(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 10000.0)
        credit = self._bill(self.contractor_a, "2026-03-05", [(9000.0, self.goods_product, None)], move_type="in_refund")
        account = self._payable(bill).account_id
        entry = self._entry(self.bank_journal, "2026-03-20", [
            {"account_id": account.id, "partner_id": self.contractor_a.id, "debit": 10000.0},
            {"account_id": account.id, "partner_id": self.contractor_a.id, "credit": 9000.0},
            {"account_id": self.supplies_account.id, "partner_id": self.contractor_a.id, "credit": 200.0},
            {"account_id": self.bank_journal.default_account_id.id, "credit": 800.0},
        ])
        lines = entry.line_ids.filtered(lambda l_: l_.account_id == account)
        (self._payable(bill) | lines.filtered(lambda l_: l_.debit)).reconcile()
        (self._payable(credit) | lines.filtered(lambda l_: l_.credit)).reconcile()
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 9800.0)

    def test_write_off_entry_with_no_money_is_not_cash(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        account = self._payable(bill).account_id
        entry = self._entry(self.company_data["default_journal_misc"], "2026-03-20", [
            {"account_id": account.id, "partner_id": self.contractor_a.id, "debit": 1000.0},
            {"account_id": self.fees_account.id, "partner_id": self.contractor_a.id, "credit": 1000.0},
        ])
        (self._payable(bill) | entry.line_ids.filtered(lambda l_: l_.account_id == account)).reconcile()
        self.assertFalse(self._return().slip_ids)

    def test_outstanding_account_is_money(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        account = self._payable(bill).account_id
        outstanding = self.outbound_payment_method_line.payment_account_id
        self.assertEqual(outstanding.account_type, "asset_current")
        entry = self._entry(self.bank_journal, "2026-03-15", [
            {"account_id": account.id, "partner_id": self.contractor_a.id, "debit": 1000.0},
            {"account_id": self.supplies_account.id, "partner_id": self.contractor_a.id, "credit": 100.0},
            {"account_id": self.fees_account.id, "partner_id": self.contractor_a.id, "debit": 500.0},
            {"account_id": outstanding.id, "credit": 1400.0},
        ])
        (self._payable(bill) | entry.line_ids.filtered(lambda l_: l_.account_id == account)).reconcile()
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 1400.0)

    def test_credit_note_counts_when_it_is_matched(self):
        self.company.l10n_ca_t5018_include_mixed_goods = False
        bill = self._bill(self.sub_corp, "2025-11-01", [
            (2000.0, self.construction_account, None), (2000.0, self.goods_product, None),
        ])
        self._pay(bill, "2025-11-20", amount=2000.0)
        credit = self._bill(self.sub_corp, "2025-12-15", [(2000.0, self.goods_product, None)], move_type="in_refund")
        with freeze_time("2026-02-10"):
            (self._payable(bill) | self._payable(credit)).reconcile()
        self.assertAlmostEqual(self._return("t5018", year=2025).slip_ids.amount_reported, 1000.0)
        self.assertAlmostEqual(self._return("t5018", year=2026).slip_ids.amount_reported, 1000.0)
