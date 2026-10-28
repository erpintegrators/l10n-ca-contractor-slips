# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CONTRACTOR_BN, PAYER_BN, VALID_SIN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestIdentifiers(L10nCaSlipsCommon):

    def test_tests_run_on_a_fixed_date(self):
        self.assertEqual(str(fields.Date.today()), "2026-11-15")

    def test_t1_business_number_standard_check(self):
        partner = self.env["res.partner"].create({
            "name": "Valid BN Ltd", "is_company": True, "country_id": self.env.ref("base.ca").id,
        })
        partner.vat = f"{PAYER_BN}RT0001"
        self.assertEqual(partner.vat, f"{PAYER_BN}RT0001")

    def test_t2_business_number_bad_check_digit(self):
        partner = self.env["res.partner"].create({
            "name": "Invalid BN Ltd", "is_company": True, "country_id": self.env.ref("base.ca").id,
        })
        with self.assertRaises(ValidationError):
            partner.vat = "123456789RT0001"

    def test_t3_payer_account_needs_the_right_program(self):
        with self.assertRaises(ValidationError):
            self.company.l10n_ca_slip_rp_account = f"{PAYER_BN}RT0001"
        with self.assertRaises(ValidationError):
            self.company.l10n_ca_slip_rz_account = f"{PAYER_BN}RP0001"
        with self.assertRaises(ValidationError):
            self.company.l10n_ca_slip_rp_account = "123456789RP0001"
        self.company.l10n_ca_slip_rp_account = f"{CONTRACTOR_BN} rp 0002"
        self.assertEqual(self.company.l10n_ca_slip_rp_account, f"{CONTRACTOR_BN}RP0002")

    def test_t3_export_rechecks_the_payer_account(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self.env.cr.execute(
            "UPDATE res_company SET l10n_ca_slip_rp_account = %s WHERE id = %s", (f"{PAYER_BN}RT0001", self.company.id)
        )
        self.company.invalidate_recordset(["l10n_ca_slip_rp_account"])
        with self.assertRaisesRegex(Exception, "RP account"):
            slip_return.action_finalize()

    def test_t4_sin_check_digit(self):
        partner = self.env["res.partner"].create({"name": "Pat Doe", "l10n_ca_sin": "130 692 544"})
        self.assertEqual(partner.l10n_ca_sin, VALID_SIN)
        with self.assertRaises(ValidationError):
            partner.l10n_ca_sin = "130692545"

    def test_transmitter_account_accepts_bn9_and_bn15(self):
        self.company.l10n_ca_slip_transmitter_account = f"{PAYER_BN}RP0001"
        self.company.l10n_ca_slip_transmitter_account = PAYER_BN
        with self.assertRaises(ValidationError):
            self.company.l10n_ca_slip_transmitter_account = "12345"

    def test_slip_names_come_from_the_contact(self):
        Slip = self.env["l10n.ca.slip"]
        values = Slip._recipient_values(self.contractor_a, self.company)
        self.assertEqual((values["surname"], values["given_name"], values["name_guessed"]), ("Martin", "Alex", False))
        self.assertEqual(Slip._recipient_values(self.sub_corp, self.company)["corp_name"], "Prairie Framing Ltd")
        # Corrections typed on the contact survive a rename.
        self.contractor_a.write({"l10n_ca_slip_surname": "Martin-Roy"})
        self.contractor_a.name = "Alex J. Martin"
        self.assertEqual(Slip._recipient_values(self.contractor_a, self.company)["surname"], "Martin-Roy")
