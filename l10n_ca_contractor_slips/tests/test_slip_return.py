# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestSlipReturn(L10nCaSlipsCommon):

    def _paid_contractors(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1200.0), "2026-03-10")
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 800.0), "2026-03-10")

    def test_t12_missing_sin_warns(self):
        self._paid_contractors()
        slip = self._slip(self._return(), self.contractor_c)
        self.assertIn("No SIN", slip.warning_message)
        self.assertFalse(self._slip(slip.return_id, self.contractor_a).warning_message)

    def test_t13_filed_slips_locked(self):
        self._paid_contractors()
        slip_return = self._return()
        self._finalize(slip_return)
        slip_return.action_mark_filed()
        self._pay(self._fee_bill(self.contractor_a, "2026-06-01", 500.0), "2026-06-10")
        with self.assertRaises(UserError):
            slip_return.action_compute()
        slip = self._slip(slip_return, self.contractor_a)
        with self.assertRaises(UserError):
            slip.adjustment_base = 10.0
        with self.assertRaises(UserError):
            slip_return.unlink()
        self.assertAlmostEqual(slip.amount_reported, 1200.0)

    def test_t13_recalculating_a_draft_keeps_adjustments(self):
        self._paid_contractors()
        slip_return = self._return()
        slip = self._slip(slip_return, self.contractor_a)
        slip.write({"adjustment_base": 100.0, "adjustment_reason": "Invoice paid in cash, not recorded"})
        self._pay(self._fee_bill(self.contractor_a, "2026-06-01", 300.0), "2026-06-10")
        slip_return.action_compute()
        self.assertEqual(self._slip(slip_return, self.contractor_a), slip)
        self.assertAlmostEqual(slip.amount_reported, 1600.0)

    def test_t14_adjustment_needs_a_reason_and_is_logged(self):
        self._paid_contractors()
        slip = self._slip(self._return(), self.contractor_a)
        with self.assertRaises(ValidationError):
            slip.adjustment_base = -50.0
        slip.write({"adjustment_base": -50.0, "adjustment_reason": "Reimbursed expenses included in the bill"})
        self.assertAlmostEqual(slip.amount_reported, 1150.0)
        messages = slip.message_ids.mapped("body")
        self.assertTrue(any("Reimbursed expenses" in str(body) for body in messages))
        self.assertTrue(any(self.env.user.name in str(body) for body in messages))

    def test_below_threshold_slip_removed_on_recalculation(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
        payment = self._pay(bill, "2026-03-10")
        slip_return = self._return()
        self.assertTrue(slip_return.slip_ids)
        payment.action_draft()
        payment.action_cancel()
        slip_return.action_compute()
        self.assertFalse(slip_return.slip_ids)

    def test_finalize_blocks_on_missing_settings(self):
        self._paid_contractors()
        slip_return = self._return()
        self.company.l10n_ca_slip_contact_id = False
        with self.assertRaisesRegex(UserError, "filing contact"):
            slip_return.action_finalize()
        self.assertEqual(slip_return.state, "draft")

    def test_back_to_draft_then_finalize_again(self):
        self._paid_contractors()
        slip_return = self._return()
        self._finalize(slip_return)
        reference = slip_return.sbmt_ref_id
        slip_return.action_reset_to_draft()
        self.assertFalse(slip_return.xml_filename)
        slip_return.action_finalize()
        self.assertNotEqual(slip_return.sbmt_ref_id, reference)
        self.assertEqual(len(slip_return.sbmt_ref_id), 8)

    def test_t22_amended_return(self):
        self._paid_contractors()
        original = self._return()
        self._finalize(original)
        original.action_mark_filed()
        amendment = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        self.assertEqual(amendment.report_type, "A")
        self.assertEqual(len(amendment.slip_ids), 2)
        slip = self._slip(amendment, self.contractor_a)
        slip.write({"adjustment_base": 250.0, "adjustment_reason": "Missed December invoice"})
        with self.assertRaisesRegex(UserError, "amendment note"):
            amendment.action_finalize()
        amendment.amendment_note = "Box 048 for Alex Martin was understated by 250.00."
        root = self._finalize(amendment)
        self.assertEqual(slip.rpt_tcd, "A")
        self.assertFalse(self._slip(amendment, self.contractor_c).rpt_tcd)
        self.assertEqual(len(root.findall(".//T4ASlip")), 1)
        self.assertEqual(root.findtext(".//T4ASlip/rpt_tcd"), "A")
        self.assertEqual(root.findtext(".//T4ASummary/rpt_tcd"), "A")
        self.assertIn("understated", root.findtext(".//T4ASummary/fileramendmentnote"))

    def test_t23_cancelled_slip(self):
        self._paid_contractors()
        original = self._return()
        self._finalize(original)
        original.action_mark_filed()
        amendment = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        self._slip(amendment, self.contractor_c).is_cancelled = True
        amendment.amendment_note = "Casey Roy was an employee; the T4A slip is cancelled."
        root = self._finalize(amendment)
        slips = root.findall(".//T4ASlip")
        self.assertEqual(len(slips), 1)
        self.assertEqual(slips[0].findtext("rpt_tcd"), "C")
        self.assertEqual(slips[0].findtext("RCPNT_NM/snm"), "Roy")

    def test_only_one_draft_amendment(self):
        self._paid_contractors()
        original = self._return()
        self._finalize(original)
        original.action_mark_filed()
        original.action_create_amendment()
        with self.assertRaises(UserError):
            original.action_create_amendment()

    def test_amendment_lists_missed_contractors(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1200.0), "2026-03-10")
        original = self._return()
        self._finalize(original)
        original.action_mark_filed()
        self._pay(self._fee_bill(self.contractor_b, "2026-04-01", 900.0), "2026-04-10")
        amendment = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        amendment.action_compute()
        self.assertNotIn(self.contractor_b, amendment.slip_ids.partner_id)
        self.assertIn("new original return", amendment.warning_message)

    def test_supplementary_original_return_only_adds_missed_contractors(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1200.0), "2026-03-10")
        first = self._return()
        self._finalize(first)
        first.action_mark_filed()
        self._pay(self._fee_bill(self.contractor_b, "2026-04-01", 900.0), "2026-04-10")
        second = self._return()
        self.assertEqual(second.slip_ids.partner_id, self.contractor_b)
