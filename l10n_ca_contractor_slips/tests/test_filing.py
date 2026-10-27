# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Filing rules: periods, currency, amendments and the transmitter record."""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import PAYER_BN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestFiling(L10nCaSlipsCommon):

    def _paid(self, partner=None, amount=900.0):
        self._pay(self._fee_bill(partner or self.contractor_a, "2026-03-01", amount), "2026-03-10")

    # Periods

    def test_t4a_covers_the_calendar_year(self):
        slip_return = self._return(compute=False)
        self.assertEqual((slip_return.date_from, slip_return.date_to), (date(2026, 1, 1), date(2026, 12, 31)))
        with self.assertRaises(ValidationError):
            slip_return.date_from = date(2026, 7, 1)

    def test_t5018_period_ends_in_its_year(self):
        slip_return = self._return("t5018", compute=False)
        with self.assertRaises(ValidationError):
            slip_return.date_to = date(2027, 3, 31)
        with self.assertRaises(ValidationError):
            slip_return.write({"date_from": date(2026, 12, 31), "date_to": date(2026, 6, 30)})

    def test_t5018_short_period_is_flagged(self):
        slip_return = self._return("t5018", compute=False)
        slip_return.date_from = date(2026, 7, 1)
        slip_return.action_compute()
        self.assertIn("not twelve months", slip_return.warning_message)

    def test_overlapping_periods_are_refused(self):
        self.company.l10n_ca_t5018_period = "fiscal"
        self.company.write({"fiscalyear_last_month": "3", "fiscalyear_last_day": 31})
        self._pay(self._bill(self.sub_corp, "2026-02-01", [(5000.0, self.construction_account, self.gst)]), "2026-02-10")
        fiscal = self._return("t5018")
        self._finalize(fiscal)
        self.company.l10n_ca_t5018_period = "calendar"
        calendar = self._return("t5018")
        with self.assertRaisesRegex(UserError, "already covers part of this period"):
            self._finalize(calendar)

    def test_due_dates(self):
        self.assertEqual(self._return(compute=False).due_date, date(2027, 2, 28))
        self.assertEqual(self._return("t5018", compute=False).due_date, date(2027, 6, 30))

    # Currency

    def test_amounts_must_be_in_canadian_dollars(self):
        self._paid()
        slip_return = self._return()
        usd = self.setup_other_currency("USD")
        self.env.cr.execute("UPDATE res_company SET currency_id = %s WHERE id = %s", (usd.id, self.company.id))
        self.company.invalidate_recordset(["currency_id"])
        slip_return.invalidate_recordset(["currency_id"])
        with self.assertRaisesRegex(UserError, "Canadian dollars"):
            self._finalize(slip_return)

    # Amendments

    def test_address_change_alone_does_not_amend_a_slip(self):
        self._paid()
        self._paid(self.contractor_b)
        original = self._filed(self._return())
        self.contractor_a.street = "99 New Street"
        self.contractor_b.street = "77 Other Street"
        amendment = self._amend(original)
        self._slip(amendment, self.contractor_b).write({"adjustment_base": 100.0, "adjustment_reason": "Late invoice"})
        amendment.action_compute()
        amendment.amendment_note = "Bailey Chen: late invoice of 100.00."
        root = self._finalize(amendment)
        self.assertFalse(self._slip(amendment, self.contractor_a).rpt_tcd)
        self.assertEqual(self._slip(amendment, self.contractor_b).rpt_tcd, "A")
        self.assertEqual(root.findtext(".//T4ASlip/RCPNT_ADDR/addr_l1_txt"), "77 Other Street")

    # Transmitter record

    def test_web_access_code_files_the_program_account(self):
        self.company.l10n_ca_slip_signin = "wac"
        self._paid()
        root = self._finalize(self._return())
        self.assertEqual(root.findtext("T619/TransmitterAccountNumber/bn15"), f"{PAYER_BN}RP0001")
        self.assertIsNone(root.find("T619/TransmitterAccountNumber/bn9"))

    def test_representative_needs_a_repid(self):
        self.company.write({
            "l10n_ca_slip_signin": "rac", "l10n_ca_slip_transmitter_account": False,
            "l10n_ca_slip_transmitter_name": "Prairie Tax Services",
        })
        self._paid()
        slip_return = self._return()
        with self.assertRaisesRegex(UserError, "RepID"):
            self._finalize(slip_return)
        self.company.l10n_ca_slip_transmitter_repid = "RP12345"
        root = self._finalize(slip_return)
        self.assertEqual(root.findtext("T619/TransmitterRepID/RepID"), "RP12345")
        self.assertEqual(len(root.find("T619/TransmitterAccountNumber")), 0)
        self.assertEqual(root.findtext("T619/TransmitterName/l1_nm"), "Prairie Tax Services")

    def test_my_business_account_keeps_the_nine_digit_number(self):
        self._paid()
        root = self._finalize(self._return())
        self.assertEqual(root.findtext("T619/TransmitterAccountNumber/bn9"), PAYER_BN)

    # Input checks

    def test_long_contact_email_is_refused(self):
        self.filing_contact.email = "a" * 55 + "@example.com"
        self._paid()
        with self.assertRaisesRegex(UserError, "longer than CRA's limit"):
            self._finalize(self._return())

    def test_second_initial_must_be_a_letter(self):
        self.contractor_a.l10n_ca_slip_initial = "7"
        self._paid()
        with self.assertRaisesRegex(UserError, "second initial must be a letter"):
            self._finalize(self._return())

    def test_sin_typed_on_a_slip_is_checked(self):
        self._paid()
        slip = self._return().slip_ids
        with self.assertRaises(ValidationError):
            slip.sin = "130692545"

    def test_postal_code_and_business_number_are_checked(self):
        self.contractor_a.zip = "12345"
        self._paid()
        slip = self._return().slip_ids
        self.assertIn("not a Canadian postal code", slip.warning_message)
        # Odoo refuses a bad Tax ID on the contact; a number typed on the slip is checked too.
        slip.recipient_bn = "123456789RT0001"
        self.assertIn("invalid check digit", slip.warning_message)

    def test_phone_extension_up_to_five_digits(self):
        from ..models import cra_format as fmt
        self.assertEqual(fmt.phone_parts("403-555-0142 x 12345"), ("403", "555-0142", "12345"))
        self.assertIsNone(fmt.phone_parts("403-555-0142 ext 123456"))

    # Thresholds and file contents

    def test_t5018_threshold_at_exactly_500(self):
        self._pay(self._bill(self.sub_corp, "2026-05-01", [(500.0, self.construction_account, None)]), "2026-05-10")
        self.assertTrue(self._slip(self._return("t5018"), self.sub_corp))
        self.company.l10n_ca_t5018_threshold_basis = "base_over_500"
        self.assertFalse(self._slip(self._return("t5018"), self.sub_corp))

    def test_changed_sin_after_filing_amends_the_slip(self):
        self._paid(self.contractor_c)
        original = self._filed(self._return())
        self.contractor_c.l10n_ca_sin = "246454201"
        amendment = self._amend(original)
        amendment.action_compute()
        amendment.amendment_note = "Casey Roy: SIN received after filing."
        root = self._finalize(amendment)
        self.assertEqual(amendment.slip_ids.rpt_tcd, "A")
        self.assertEqual(root.findtext(".//T4ASlip/sin"), "246454201")

    def test_t5018_amendment_carries_its_note(self):
        self._pay(self._bill(self.sub_corp, "2026-05-01", [(5000.0, self.construction_account, self.gst)]), "2026-05-10")
        original = self._filed(self._return("t5018"))
        amendment = self._amend(original)
        amendment.slip_ids.write({"adjustment_incl": 100.0, "adjustment_reason": "Late invoice"})
        amendment.amendment_note = "Prairie Framing Ltd: late invoice of 100.00."
        root = self._finalize(amendment)
        self.assertEqual(root.findtext(".//T5018Summary/rpt_tcd"), "A")
        self.assertIn("late invoice", root.findtext(".//T5018Summary/fileramendmentnote"))

    def test_french_company_files_in_french(self):
        self.env["res.lang"]._activate_lang("fr_CA")
        self.company.partner_id.lang = "fr_CA"
        self._paid()
        root = self._finalize(self._return())
        self.assertEqual(root.findtext("T619/lang_cd"), "F")

    # Round-two filing rules

    def test_future_year_is_refused_and_an_open_period_is_flagged(self):
        future = self._return(year=2027, compute=False)
        future.action_compute()
        with self.assertRaisesRegex(UserError, "has not started"):
            self._finalize(future)
        self._paid()
        current = self._return()
        self.assertIn("This period has not ended", current.warning_message)

    def test_t5018_gap_and_long_period(self):
        self._pay(self._bill(self.sub_corp, "2025-05-01", [(5000.0, self.construction_account, self.gst)]), "2025-05-10")
        first = self._return("t5018", year=2025)
        self._finalize(first)
        second = self._return("t5018", compute=False)
        second.date_from = date(2026, 3, 1)
        second.action_compute()
        self.assertIn("are on no return", second.warning_message)
        with self.assertRaises(ValidationError):
            second.write({"date_from": date(2025, 1, 1)})

    def test_t5018_due_date_for_a_mid_month_period_end(self):
        slip_return = self._return("t5018", compute=False)
        slip_return.write({"date_from": date(2025, 6, 16), "date_to": date(2026, 6, 15)})
        self.assertEqual(slip_return.due_date, date(2026, 12, 15))

    def test_repid_only_for_representatives(self):
        self.company.l10n_ca_slip_transmitter_repid = "RP12345"
        self._paid()
        root = self._finalize(self._return())
        self.assertIsNone(root.find("T619/TransmitterRepID"))

    def test_amendment_keeps_its_period(self):
        self._paid()
        amendment = self._amend(self._filed(self._return()))
        with self.assertRaisesRegex(UserError, "keeps the slip type and period"):
            amendment.write({"year": 2025})

    def test_zero_amendment_points_to_cancel(self):
        self._paid()
        amendment = self._amend(self._filed(self._return()))
        amendment.slip_ids.write({"adjustment_base": -900.0, "adjustment_reason": "Payment reversed"})
        amendment.amendment_note = "Alex Martin: payment reversed."
        with self.assertRaisesRegex(UserError, "Cancel this slip"):
            self._finalize(amendment)

    def test_changed_identifier_on_an_amendment_is_flagged(self):
        self._paid(self.contractor_c)
        amendment = self._amend(self._filed(self._return()))
        self.contractor_c.l10n_ca_sin = "246454201"
        amendment.action_compute()
        self.assertIn("differs from the slip filed earlier", amendment.slip_ids.warning_message)

    def test_character_tables_for_notes_and_contacts(self):
        from ..models import cra_format as fmt
        self.assertEqual(fmt.clean_text("a=b_c", "amendment_note"), "a b c")
        self.assertEqual(fmt.clean_text("Smith & Co.", "contact_name"), "Smith Co")

    def test_threshold_change_after_calculation_blocks_finalize(self):
        self._pay(self._bill(self.sub_corp, "2026-05-01", [(500.0, self.construction_account, None)]), "2026-05-10")
        slip_return = self._return("t5018")
        self.company.l10n_ca_t5018_threshold_basis = "base_over_500"
        with self.assertRaisesRegex(UserError, "Recalculate first"):
            self._finalize(slip_return)

    def test_contractor_left_out_of_an_amendment_can_be_cancelled(self):
        self._paid()
        amendment = self._amend(self._filed(self._return()))
        self.contractor_a.country_id = self.env.ref("base.us")
        amendment.action_compute()
        self.assertFalse(amendment._stale_slips())
