# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""What each step of a return allows, and who may take it."""
from unittest.mock import patch

from psycopg2.errors import CheckViolation, UniqueViolation

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import FakeResponse, L10nCaSlipsCommon, cra_schema_zip_path


@tagged("post_install", "-at_install")
class TestWorkflowGuards(L10nCaSlipsCommon):

    def _paid(self, partner=None, amount=900.0):
        self._pay(self._fee_bill(partner or self.contractor_a, "2026-03-01", amount), "2026-03-10")

    # Steps out of order

    def test_each_step_refuses_the_wrong_state(self):
        self._paid()
        draft = self._return()
        with self.assertRaisesRegex(UserError, "Finalize the return before marking it filed"):
            draft.action_mark_filed()
        with self.assertRaisesRegex(UserError, "Only filed returns can be amended"):
            draft.action_create_amendment()
        with self.assertRaisesRegex(UserError, "Only final returns can go back to draft"):
            draft.action_reset_to_draft()
        with self.assertRaisesRegex(UserError, "Finalize the return before printing"):
            draft.action_print_slips()
        self._finalize(draft)
        with self.assertRaisesRegex(UserError, "Only draft returns can be finalized"):
            draft.action_finalize()
        with self.assertRaisesRegex(UserError, "Only draft returns can be recalculated"):
            draft.action_compute()
        with self.assertRaisesRegex(UserError, "Only draft returns can be deleted"):
            draft.unlink()
        draft.action_mark_filed()
        with self.assertRaisesRegex(UserError, "Only final returns can go back to draft"):
            draft.action_reset_to_draft()
        with self.assertRaisesRegex(UserError, "cannot be deleted"):
            draft.slip_ids.unlink()

    def test_empty_return_cannot_be_finalized(self):
        with self.assertRaisesRegex(UserError, "There are no slips to file"):
            self._finalize(self._return())

    def test_filed_return_keeps_its_year_and_note(self):
        self._paid()
        original = self._filed(self._return())
        amendment = self._amend(original)
        amendment.slip_ids.write({"adjustment_base": 50.0, "adjustment_reason": "Late invoice"})
        amendment.amendment_note = "Alex Martin: late invoice of 50.00."
        self._filed(amendment)
        for vals in ({"year": 2025}, {"amendment_note": "Changed"}, {"slip_type": "t5018"}):
            with self.subTest(vals=vals), self.assertRaises(UserError):
                amendment.write(vals)

    def test_back_to_draft_restores_the_replaced_slip(self):
        self._paid()
        original = self._filed(self._return())
        amendment = self._amend(original)
        amendment.slip_ids.write({"adjustment_base": 50.0, "adjustment_reason": "Late invoice"})
        amendment.amendment_note = "Alex Martin: late invoice of 50.00."
        self._finalize(amendment)
        self.assertTrue(original.slip_ids.superseded)
        amendment.action_reset_to_draft()
        self.assertFalse(original.slip_ids.superseded)

    def test_amendment_totals_count_only_changed_slips(self):
        self._paid()
        self._paid(self.contractor_b, 700.0)
        original = self._filed(self._return())
        self.assertEqual((original.slip_count, original.exported_slip_count), (2, 2))
        self.assertAlmostEqual(original.total_reported, 1600.0)
        amendment = self._amend(original)
        self._slip(amendment, self.contractor_b).write({"adjustment_base": 100.0, "adjustment_reason": "Late invoice"})
        self.assertEqual((amendment.slip_count, amendment.exported_slip_count), (2, 1))
        self.assertAlmostEqual(amendment.total_reported, 800.0)
        amendment.amendment_note = "Bailey Chen: late invoice of 100.00."
        self._finalize(amendment)
        self.assertEqual(amendment.exported_slip_count, 1)
        self.assertAlmostEqual(amendment.total_reported, 800.0)

    # Settings a return needs

    def test_missing_settings_are_listed(self):
        self._paid()
        slip_return = self._return()
        self.company.l10n_ca_slip_rp_account = False
        self.company.l10n_ca_slip_transmitter_account = False
        self.filing_contact.write({"phone": "555-0142", "email": False})
        with self.assertRaises(UserError) as caught:
            self._finalize(slip_return)
        message = str(caught.exception)
        for text in ("payer's RP account", "transmitter CRA account number", "10-digit phone", "needs an email address"):
            self.assertIn(text, message)

    def test_year_must_be_realistic(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(CheckViolation):
            self.env["l10n.ca.slip.return"].create({"slip_type": "t4a", "year": 1999})
            self.env.flush_all()

    def test_one_slip_per_recipient_per_return(self):
        self._paid()
        slip_return = self._return()
        with mute_logger("odoo.sql_db"), self.assertRaises(UniqueViolation):
            slip_return.slip_ids.copy({"return_id": slip_return.id})
            self.env.flush_all()

    # Actions

    def test_download_and_open_actions(self):
        self._paid()
        slip_return = self._return()
        with self.assertRaisesRegex(UserError, "Finalize the return to create the CRA file"):
            slip_return.action_download_xml()
        self._finalize(slip_return)
        action = slip_return.action_download_xml()
        self.assertIn(f"/web/content/l10n.ca.slip.return/{slip_return.id}/xml_file/", action["url"])
        slip = slip_return.slip_ids
        self.assertEqual(slip.action_open_slip()["res_id"], slip.id)

    def test_schema_button_reports_the_outcome(self):
        settings = self.env["res.config.settings"].create({})
        Return = self.env["l10n.ca.slip.return"]
        maintenance = FakeResponse(b"<html>Maintenance</html>")
        with patch("requests.get", return_value=maintenance):
            self.assertEqual(settings.action_l10n_ca_slip_reload_schemas()["params"]["type"], "danger")
        self.assertFalse(Return._l10n_ca_schemas_current())
        self.assertFalse(self.env["ir.attachment"].search([("name", "like", "contractor_slips.xmlschm")]))
        with open(cra_schema_zip_path(), "rb") as handle, patch("requests.get", return_value=FakeResponse(handle.read())):
            self.assertEqual(settings.action_l10n_ca_slip_reload_schemas()["params"]["type"], "success")
        self.assertTrue(Return._l10n_ca_schemas_current())
        # A failed refresh keeps the schemas already loaded.
        with patch("requests.get", return_value=maintenance):
            self.assertEqual(settings.action_l10n_ca_slip_reload_schemas()["params"]["type"], "danger")
        self.assertTrue(Return._l10n_ca_schemas_current())

    # Who may do what

    def test_read_only_accountant_cannot_create_or_change_returns(self):
        auditor = self._user("auditor.guards", ["base.group_user", "account.group_account_readonly"])
        Return = self.env["l10n.ca.slip.return"].with_user(auditor)
        with self.assertRaises(AccessError):
            Return.create({"slip_type": "t4a", "year": 2026})
        slip_return = self._return(compute=False)
        self.assertTrue(slip_return.with_user(auditor).read(["name"]))
        with self.assertRaises(AccessError):
            slip_return.with_user(auditor).write({"cra_confirmation": "X"})

    def test_other_companies_cannot_see_the_return(self):
        slip_return = self._return(compute=False)
        other = self.setup_other_company()["company"]
        outsider = self._user("outsider.guards", ["base.group_user", "account.group_account_manager"], companies=other)
        self.assertFalse(self.env["l10n.ca.slip.return"].with_user(outsider).search([("id", "=", slip_return.id)]))

    def test_calculation_keeps_to_the_returns_companies(self):
        other = self.setup_other_company()["company"]
        self.contractor_a.with_company(other).l10n_ca_slip_type = "t4a"
        bill = self.env["account.move"].with_company(other).create({
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-03-01",
            "company_id": other.id,
            "invoice_line_ids": [(0, 0, {"name": "Fees", "price_unit": 5000.0, "tax_ids": []})],
        })
        bill.action_post()
        self._register_payment(bill.with_company(other), payment_date="2026-03-10")
        self._paid()
        self.assertAlmostEqual(self._slip(self._return(), self.contractor_a).amount_reported, 900.0)

    def test_sales_user_cannot_flag_a_new_contact(self):
        sales = self._user("sales.guards", ["base.group_user", "base.group_partner_manager"])
        with self.assertRaises(AccessError):
            self.env["res.partner"].with_user(sales).create({"name": "New vendor", "l10n_ca_slip_type": "t4a"})
