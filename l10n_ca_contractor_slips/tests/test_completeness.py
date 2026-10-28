# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""What the return points out so nothing is missed or filed twice."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestCompleteness(L10nCaSlipsCommon):

    def _new_vendor(self, name, **values):
        return self.env["res.partner"].create({
            "name": name, "street": "1 Main St", "city": "Calgary", "zip": "T2P 1J9",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id, **values,
        })

    # Vendors nobody flagged

    def test_unflagged_vendor_paid_from_a_tagged_account_is_named(self):
        vendor = self._new_vendor("Drew Hollis")
        self._pay(self._fee_bill(vendor, "2026-06-01", 5000.0), "2026-06-10")
        slip_return = self._return()
        self.assertFalse(slip_return.slip_ids)
        self.assertIn("Drew Hollis was paid", slip_return.warning_message)
        self.assertIn("5,000.00", slip_return.warning_message)
        self.assertIn("not set to T4A", slip_return.warning_message)

    def test_unflagged_subcontractor_is_named_on_the_t5018_return(self):
        vendor = self._new_vendor("Ridge Concrete Ltd", is_company=True)
        self._pay(self._bill(vendor, "2026-06-01", [(5000.0, self.construction_account, self.gst)]), "2026-06-10")
        slip_return = self._return("t5018")
        self.assertFalse(slip_return.slip_ids)
        self.assertIn("Ridge Concrete Ltd was paid", slip_return.warning_message)
        self.assertIn("5,250.00", slip_return.warning_message)

    def test_bills_set_to_not_reported_are_not_named(self):
        vendor = self._new_vendor("Drew Hollis")
        bill = self._bill(vendor, "2026-06-01", [(5000.0, self.fees_account, None)], post=False)
        bill.l10n_ca_slip_type = "none"
        bill.action_post()
        self._pay(bill, "2026-06-10")
        self.assertNotIn("Drew Hollis", self._return().warning_message or "")

    def test_bill_on_the_other_slip_using_this_slips_account_is_named(self):
        bill = self._bill(self.contractor_a, "2026-06-01", [(2000.0, self.construction_account, None)])
        self._pay(bill, "2026-06-10")
        slip_return = self._return("t5018")
        self.assertIn("Alex Martin is reported on T4A", slip_return.warning_message)
        self.assertIn(bill.name, slip_return.warning_message)

    def test_notes_are_kept_on_the_return_when_it_is_finalized(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._pay(self._fee_bill(self._new_vendor("Drew Hollis"), "2026-06-01", 5000.0), "2026-06-10")
        slip_return = self._return()
        self._finalize(slip_return)
        self.assertIn("Finalized with these notes", slip_return.message_ids[0].body)
        self.assertIn("Drew Hollis was paid", slip_return.message_ids[0].body)

    # Slips cancelled with CRA

    def test_contractor_whose_slip_was_cancelled_is_pointed_out_on_a_new_original(self):
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 900.0), "2026-03-10")
        original = self._filed(self._return())
        cancellation = self._amend(original)
        cancellation.slip_ids.is_cancelled = True
        cancellation.amendment_note = "Casey Roy slip cancelled: paid through payroll as an employee."
        self._filed(cancellation)
        again = self._return()
        self.assertIn("Casey Roy: the slip for this period was cancelled", again.warning_message)
        self.assertIn("paid through payroll as an employee", again.warning_message)
        self.assertIn("Not reported", again.warning_message)

    # Found by the amounts and multi-company reviews

    def test_untagged_holdback_on_a_t4a_bill_is_flagged(self):
        holdback = self.env["account.account"].create({
            "name": "Holdbacks (untagged)", "code": "2193HB", "account_type": "liability_current",
        })
        holdback.tag_ids = [Command.clear()]  # Odoo copies tags from the closest existing code
        self._pay(self._bill(self.contractor_a, "2026-06-01", [
            (10000.0, self.fees_account, None), (-1000.0, holdback, None),
        ]), "2026-06-20")
        self.assertIn("not tagged for T4A", self._return().slip_ids.warning_message or "")

    def test_user_without_the_main_company_is_told_which_company_returns_belong_to(self):
        branch = self._create_company(name="Airdrie branch", parent_id=self.company.id)
        clerk = self._user("branch.returns", ["base.group_user", "account.group_account_manager"], companies=branch)
        Return = self.env["l10n.ca.slip.return"].with_user(clerk).with_company(branch)
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, "Returns belong to Northern Build Co"):
            Return.create({"slip_type": "t4a", "year": 2026})

    # Found by the amounts re-check

    def test_goods_on_this_slips_account_do_not_raise_the_other_slip_note(self):
        bill = self._bill(self.contractor_a, "2026-05-01", [
            (1000.0, self.fees_account, None), (500.0, self.goods_product, None),
        ])
        self._pay(bill, "2026-05-10")
        self.assertNotIn("is reported on T4A", self._return("t5018").warning_message or "")

    def test_holdback_warnings_stay_in_the_year_the_bill_was_settled(self):
        holdback = self.env["account.account"].create({
            "name": "Holdbacks (untagged)", "code": "2194HB", "account_type": "liability_current",
        })
        holdback.tag_ids = [Command.clear()]
        self._pay(self._bill(self.contractor_a, "2026-06-01", [
            (10000.0, self.fees_account, None), (-1000.0, holdback, None),
        ]), "2026-06-20")
        self.assertNotIn("holds back", self._return(year=2025).warning_message or "")
        self.assertIn("holds back", self._return(year=2026).slip_ids.warning_message or "")

    def test_flagged_contractor_bill_with_nothing_that_counts_is_pointed_out(self):
        opening = self._bill(self.contractor_b, "2026-01-05", [(3000.0, self.supplies_account, None)])
        self._pay(opening, "2026-02-01")
        slip_return = self._return()
        self.assertFalse(slip_return.slip_ids)
        self.assertIn(f"Bailey Chen: {opening.name} was paid in the period", slip_return.warning_message or "")

    def test_goods_only_bill_is_not_pointed_out(self):
        self._pay(self._bill(self.contractor_b, "2026-01-05", [(3000.0, self.goods_product, None)]), "2026-02-01")
        self.assertNotIn("was paid in the period, but none", self._return().warning_message or "")

    def test_bill_on_the_other_slip_paid_through_a_bank_line_is_named(self):
        bill = self._bill(self.contractor_a, "2026-06-01", [(2000.0, self.construction_account, None)])
        payable = bill.line_ids.filtered(lambda l_: l_.display_type == "payment_term")
        statement_line = self.env["account.bank.statement.line"].create({
            "journal_id": self.bank_journal.id, "date": "2026-06-10", "payment_ref": "Paid bill",
            "partner_id": self.contractor_a.id, "amount": -2000.0, "counterpart_account_id": payable.account_id.id,
        })
        counterpart = statement_line.move_id.line_ids.filtered(lambda l_: l_.account_id == payable.account_id)
        (counterpart | payable).reconcile()
        self.assertFalse(bill.matched_payment_ids)
        self.assertIn("Alex Martin is reported on T4A", self._return("t5018").warning_message or "")
