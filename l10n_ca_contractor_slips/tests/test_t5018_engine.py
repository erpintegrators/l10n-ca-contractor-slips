# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from datetime import date

from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestT5018Engine(L10nCaSlipsCommon):

    def test_t18_mixed_bill_reports_services_with_tax(self):
        self.company.l10n_ca_t5018_include_mixed_goods = False
        bill = self._bill(self.sub_corp, "2026-03-01", [
            (1000.0, self.goods_product, self.gst),
            (1000.0, self.construction_account, self.gst),
        ])
        self._pay(bill, "2026-03-20")
        slip = self._return("t5018").slip_ids
        self.assertAlmostEqual(slip.amount_base, 1000.0)
        self.assertAlmostEqual(slip.amount_reported, 1050.0)

    def test_t18_mixed_bill_option_reports_the_whole_bill(self):
        self.company.l10n_ca_t5018_include_mixed_goods = True
        bill = self._bill(self.sub_corp, "2026-03-01", [
            (1000.0, self.goods_product, self.gst),
            (1000.0, self.construction_account, self.gst),
        ])
        self._pay(bill, "2026-03-20")
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 2100.0)

    def test_goods_only_bill_never_reported(self):
        self.company.l10n_ca_t5018_include_mixed_goods = True
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(5000.0, self.goods_product, self.gst)]), "2026-03-20")
        self.assertFalse(self._return("t5018").slip_ids)

    def test_t19_threshold_is_before_tax(self):
        self.company.l10n_ca_t5018_threshold_basis = "base_over_500"
        self._pay(self._bill(self.sub_individual, "2026-03-01", [(480.0, self.construction_account, self.gst)]), "2026-03-20")
        self.assertFalse(self._return("t5018").slip_ids)
        self._pay(self._bill(self.sub_individual, "2026-04-01", [(30.0, self.construction_account, self.gst)]), "2026-04-20")
        slip = self._return("t5018", compute=True).slip_ids
        self.assertAlmostEqual(slip.amount_base, 510.0)
        self.assertAlmostEqual(slip.amount_reported, 535.5)

    def test_t20_fiscal_period(self):
        self.company.write({
            "fiscalyear_last_month": "3",
            "fiscalyear_last_day": 31,
            "l10n_ca_t5018_period": "fiscal",
        })
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(2000.0, self.construction_account, None)]), "2026-03-15")
        self._pay(self._bill(self.sub_corp, "2026-05-01", [(3000.0, self.construction_account, None)]), "2026-05-15")
        slip_return = self._return("t5018", year=2027)
        self.assertEqual((slip_return.date_from, slip_return.date_to), (date(2026, 4, 1), date(2027, 3, 31)))
        self.assertAlmostEqual(slip_return.slip_ids.amount_reported, 3000.0)

    def test_t4a_ignores_fiscal_period(self):
        self.company.write({"fiscalyear_last_month": "3", "fiscalyear_last_day": 31, "l10n_ca_t5018_period": "fiscal"})
        slip_return = self._return("t4a", year=2026, compute=False)
        self.assertEqual((slip_return.date_from, slip_return.date_to), (date(2026, 1, 1), date(2026, 12, 31)))

    def test_t4a_and_t5018_vendors_stay_apart(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(900.0, self.construction_account, None)]), "2026-03-10")
        self.assertEqual(self._return("t4a").slip_ids.partner_id, self.contractor_a)
        self.assertEqual(self._return("t5018").slip_ids.partner_id, self.sub_corp)
