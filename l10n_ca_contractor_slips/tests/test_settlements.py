# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""How payments, refunds, discounts and currencies turn into slip amounts."""
from odoo import Command, fields
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestSettlements(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Units of USD per CAD: the dollar weakens through the year, then recovers in October.
        cls.usd = cls.setup_other_currency("USD", rates=[
            ("2026-01-01", 0.8), ("2026-06-01", 0.625), ("2026-09-01", 0.5), ("2026-10-01", 0.8),
        ])
        cls.term_2_10 = cls.env["account.payment.term"].create({
            "name": "2/10 net 30",
            "early_discount": True,
            "discount_percentage": 2.0,
            "discount_days": 10,
            "line_ids": [Command.create({"value": "percent", "value_amount": 100.0, "nb_days": 30})],
        })
        if not cls.company.account_journal_early_pay_discount_gain_account_id:
            cls.company.account_journal_early_pay_discount_gain_account_id = cls.copy_account(
                cls.company_data["default_account_revenue"], {"name": "Early payment discounts"}
            )

    def _amounts(self, partner, slip_type="t4a"):
        data = self.env["l10n.ca.slip.engine"]._compute_partner_amounts(
            self.company, slip_type, fields.Date.to_date("2026-01-01"), fields.Date.to_date("2026-12-31"), partners=partner
        )
        return data.get(partner.id, {"base": 0.0, "incl": 0.0, "warnings": []})

    # Foreign currency

    def test_usd_bill_paid_in_cad_counts_the_cash_paid(self):
        bill = self._bill(self.contractor_a, "2026-03-01", [(1000.0, self.fees_account, None)], currency=self.usd)
        self.assertAlmostEqual(abs(bill.amount_total_signed), 1250.0)
        self._pay(bill, "2026-07-01", amount=1600.0, currency=self.cad)
        self.assertAlmostEqual(self._amounts(self.contractor_a)["base"], 1600.0)

    def test_usd_bill_paid_in_two_cad_payments(self):
        bill = self._bill(self.contractor_b, "2026-03-01", [(1000.0, self.fees_account, None)], currency=self.usd)
        self._pay(bill, "2026-07-01", amount=800.0, currency=self.cad)
        self._pay(bill, "2026-07-02", amount=800.0, currency=self.cad)
        self.assertAlmostEqual(self._amounts(self.contractor_b)["base"], 1600.0)

    def test_usd_bill_paid_in_cad_when_the_dollar_recovered(self):
        bill = self._bill(self.contractor_c, "2026-09-15", [(1000.0, self.fees_account, None)], currency=self.usd)
        self.assertAlmostEqual(abs(bill.amount_total_signed), 2000.0)
        self._pay(bill, "2026-10-05", amount=1250.0, currency=self.cad)
        self.assertAlmostEqual(self._amounts(self.contractor_c)["base"], 1250.0)

    def test_usd_bill_paid_in_usd_is_not_counted_twice(self):
        bill = self._bill(self.contractor_a, "2026-03-01", [(1000.0, self.fees_account, None)], currency=self.usd)
        self._pay(bill, "2026-07-01", currency=self.usd)
        amounts = self._amounts(self.contractor_a)
        self.assertAlmostEqual(amounts["base"], 1600.0)
        # The exchange difference entry Odoo books on the payment is not a journal entry to flag.
        self.assertFalse([w for w in amounts["warnings"] if "settles journal entries" in w])

    def test_exchange_difference_on_a_partial_payment_is_not_flagged(self):
        bill = self._bill(self.contractor_b, "2026-03-01", [(1000.0, self.fees_account, None)], currency=self.usd)
        self._pay(bill, "2026-07-01", amount=400.0, currency=self.usd)
        self._pay(bill, "2026-09-15", amount=600.0, currency=self.usd)
        payment_lines = self.env["account.move.line"].search([
            ("partner_id", "=", self.contractor_b.id), ("account_id.account_type", "=", "liability_payable"),
            ("move_id.move_type", "=", "entry"), ("balance", ">", 0),
        ])
        exchange_moves = (payment_lines.matched_debit_ids | payment_lines.matched_credit_ids).exchange_move_id
        self.assertTrue(exchange_moves, "the rate moved, so Odoo books an exchange difference")
        amounts = self._amounts(self.contractor_b)
        self.assertFalse([w for w in amounts["warnings"] if "settles journal entries" in w])

    # Entries reset to draft

    def test_payment_reset_to_draft_does_not_count(self):
        payment = self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1200.0), "2026-03-10")
        payment.action_draft()
        self.assertAlmostEqual(self._amounts(self.contractor_a)["base"], 0.0)
        slip_return = self._return()
        self.assertFalse(self._slip(slip_return, self.contractor_a))

    def test_credit_note_reset_to_draft_does_not_count(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        credit = self._fee_bill(self.contractor_a, "2026-03-05", 200.0, move_type="in_refund")
        (bill | credit).line_ids.filtered(lambda line: line.display_type == "payment_term").reconcile()
        self._pay(bill, "2026-03-20")
        self.assertAlmostEqual(self._amounts(self.contractor_a)["base"], 800.0)
        credit.button_draft()
        self.assertAlmostEqual(self._amounts(self.contractor_a)["base"], 800.0)

    # Whole mixed bills and goods credit notes

    def _mixed_bill(self):
        self.company.l10n_ca_t5018_include_mixed_goods = True
        bill = self._bill(self.sub_corp, "2026-09-01", [
            (10000.0, self.construction_account, self.gst), (2000.0, self.goods_product, self.gst),
        ])
        self._pay(bill, "2026-09-25")
        return bill

    def test_goods_credit_note_refunded_in_cash_lowers_box_22(self):
        bill = self._mixed_bill()
        credit = self.env["account.move"].create({
            "move_type": "in_refund", "partner_id": self.sub_corp.id, "invoice_date": "2026-09-26",
            "date": "2026-09-26", "reversed_entry_id": bill.id,
            "invoice_line_ids": [Command.create({
                "product_id": self.goods_product.id, "price_unit": 2000.0, "tax_ids": [Command.set(self.gst.ids)],
            })],
        })
        credit.action_post()
        self._pay(credit, "2026-09-28")
        self.assertAlmostEqual(self._amounts(self.sub_corp, "t5018")["incl"], 10500.0)

    def test_unlinked_goods_credit_note_refunded_in_cash_is_flagged(self):
        self._mixed_bill()
        credit = self._bill(self.sub_corp, "2026-09-26", [(2000.0, self.goods_product, self.gst)], move_type="in_refund")
        self._pay(credit, "2026-09-28")
        data = self._amounts(self.sub_corp, "t5018")
        self.assertAlmostEqual(data["incl"], 12600.0)
        self.assertTrue(any(credit.name in warning for warning in data["warnings"]))

    # Money journals

    def test_payment_booked_from_a_credit_card_counts(self):
        card_account = self.env["account.account"].create({
            "name": "Company Visa", "code": "299001", "account_type": "liability_credit_card",
            "company_id": self.company.id,
        })
        card = self.env["account.journal"].create({
            "name": "Company Visa", "type": "bank", "code": "VISA", "company_id": self.company.id,
            "default_account_id": card_account.id,
        })
        entry = self.env["account.move"].create({
            "move_type": "entry", "journal_id": card.id, "date": "2026-04-02",
            "line_ids": [
                Command.create({"account_id": self.fees_account.id, "partner_id": self.contractor_a.id, "debit": 750.0}),
                Command.create({"account_id": card.default_account_id.id, "partner_id": self.contractor_a.id, "credit": 750.0}),
            ],
        })
        entry.action_post()
        self.assertAlmostEqual(self._amounts(self.contractor_a)["base"], 750.0)

    # Early payment discounts

    def test_early_discount_reduces_only_the_bill_that_earned_it(self):
        services = self._bill(self.contractor_a, "2026-03-01", [(1000.0, self.fees_account, None)], post=False)
        services.invoice_payment_term_id = self.term_2_10
        services.action_post()
        goods = self._bill(self.contractor_a, "2026-03-01", [(1000.0, self.goods_product, None)])
        self._register_payment(services | goods, payment_date="2026-03-05", group_payment=True, journal_id=self.bank_journal.id)
        self.assertAlmostEqual(self._amounts(self.contractor_a)["base"], 980.0)

    def test_early_discount_with_tax_on_a_single_bill(self):
        bill = self._bill(self.contractor_b, "2026-03-01", [(1000.0, self.fees_account, self.gst)], post=False)
        bill.invoice_payment_term_id = self.term_2_10
        bill.action_post()
        self._pay(bill, "2026-03-05")
        data = self._amounts(self.contractor_b)
        self.assertAlmostEqual(data["base"], 980.0)
        self.assertAlmostEqual(data["incl"], 1029.0)

    # Rounding

    def test_payment_lines_add_up_to_the_slip(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0, taxes=self.gst)
        for day in ("2026-03-10", "2026-03-11", "2026-03-12"):
            self._pay(bill, day, amount=350.0)
        slip = self._slip(self._return(), self.contractor_a)
        self.assertAlmostEqual(slip.computed_base, 1000.0)
        self.assertAlmostEqual(sum(slip.line_ids.mapped("amount_base")), slip.computed_base)

    def test_early_discount_on_a_usd_bill_after_the_rate_moved(self):
        bill = self._bill(self.contractor_a, "2026-05-25", [(1000.0, self.fees_account, None)], currency=self.usd, post=False)
        bill.invoice_payment_term_id = self.term_2_10
        bill.action_post()
        payment = self._pay(bill, "2026-06-03", currency=self.usd)
        bank = abs(payment.amount_company_currency_signed)
        self.assertAlmostEqual(self._amounts(self.contractor_a)["base"], bank, places=2)

    def test_early_discount_with_a_credit_note_in_the_same_payment(self):
        bill = self._bill(self.contractor_b, "2026-03-01", [(1000.0, self.fees_account, None)], post=False)
        bill.invoice_payment_term_id = self.term_2_10
        bill.action_post()
        credit = self._fee_bill(self.contractor_b, "2026-03-02", 200.0, move_type="in_refund")
        payment = self._register_payment(bill | credit, payment_date="2026-03-05", group_payment=True, journal_id=self.bank_journal.id)
        self.assertAlmostEqual(abs(payment.amount_company_currency_signed), 780.0)
        self.assertAlmostEqual(self._amounts(self.contractor_b)["base"], 780.0)
