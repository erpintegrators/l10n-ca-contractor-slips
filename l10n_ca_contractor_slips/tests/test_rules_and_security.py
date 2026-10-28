# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""T5018 rules, amended returns, SIN security and schema refresh."""

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import PRINTED_SIN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestRulesAndSecurity(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sales_user = cls.env["res.users"].create({
            "name": "Sales rep", "login": "sales.rules",
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("base.group_partner_manager").id])],
            "company_ids": [Command.set(cls.company.ids)], "company_id": cls.company.id,
        })
        cls.holdback_account = cls.env["account.account"].create({
            "name": "Holdbacks payable", "code": "2190HB", "account_type": "liability_current",
            "tag_ids": [Command.set(cls.tag_t5018.ids)],
        })

    def _payable(self, move):
        return move.line_ids.filtered(lambda l_: l_.display_type == "payment_term")

    def _filed(self, slip_return):
        self._finalize(slip_return)
        slip_return.action_mark_filed()
        return slip_return

    # Amounts

    def test_mixed_bill_reported_whole_by_default(self):
        self._pay(self._bill(self.sub_individual, "2026-05-01", [
            (4000.0, self.construction_account, self.gst), (3000.0, self.goods_product, self.gst),
        ]), "2026-05-20")
        slip = self._return("t5018").slip_ids
        self.assertAlmostEqual(slip.amount_base, 7000.0)
        self.assertAlmostEqual(slip.amount_reported, 7350.0)

    def test_t5018_threshold_default_is_services_with_tax(self):
        self._pay(self._bill(self.sub_individual, "2026-08-01", [(480.0, self.construction_account, self.gst)]), "2026-08-10")
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 504.0)
        self.company.l10n_ca_t5018_threshold_basis = "base_over_500"
        self.assertFalse(self._return("t5018").slip_ids)

    def test_t5018_threshold_counts_services_only_on_a_whole_mixed_bill(self):
        self._pay(self._bill(self.sub_individual, "2026-08-01", [
            (400.0, self.construction_account, None), (5000.0, self.goods_product, None),
        ]), "2026-08-10")
        self.assertFalse(self._return("t5018").slip_ids)

    def test_goods_credit_note_on_a_whole_mixed_bill(self):
        for whole in (True, False):
            with self.subTest(whole_bill=whole):
                self.company.l10n_ca_t5018_include_mixed_goods = whole
                partner = self.env["res.partner"].create({
                    "name": f"Northline {whole}", "l10n_ca_recipient_type": "3", "l10n_ca_slip_type": "t5018",
                    "street": "1 Main St", "city": "Calgary", "zip": "T2P 1J9",
                    "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
                })
                bill = self._bill(partner, "2026-09-01", [
                    (10000.0, self.construction_account, self.gst), (2000.0, self.goods_product, self.gst),
                ])
                credit = self._bill(partner, "2026-09-10", [(2000.0, self.goods_product, self.gst)], move_type="in_refund")
                (self._payable(bill) | self._payable(credit)).reconcile()
                self._pay(bill, "2026-09-25")
                slip = self._slip(self._return("t5018"), partner)
                self.assertAlmostEqual(slip.amount_reported, 10500.0)

    def test_goods_credit_note_on_a_services_only_bill(self):
        goods_bill = self._bill(self.sub_corp, "2026-08-01", [(2000.0, self.goods_product, self.gst)])
        credit = self._bill(self.sub_corp, "2026-08-05", [(2000.0, self.goods_product, self.gst)], move_type="in_refund")
        services_bill = self._bill(self.sub_corp, "2026-08-10", [(10000.0, self.construction_account, self.gst)])
        (self._payable(services_bill) | self._payable(credit)).reconcile()
        self._pay(services_bill, "2026-08-20")
        self._pay(goods_bill, "2026-08-20")
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 10500.0)

    def test_untagged_holdback_is_flagged(self):
        untagged = self.env["account.account"].create({
            "name": "Holdbacks (untagged)", "code": "2191HB", "account_type": "liability_current",
        })
        untagged.tag_ids = [Command.clear()]  # Odoo copies tags from the closest existing code
        bill = self._bill(self.sub_corp, "2026-06-01", [
            (10000.0, self.construction_account, None), (-1000.0, untagged, None),
        ])
        self._pay(bill, "2026-06-20")
        self.assertIn("not tagged for T5018", self._return("t5018").slip_ids.warning_message or "")

    def test_services_credit_note_on_a_goods_only_bill(self):
        goods_bill = self._bill(self.sub_corp, "2026-08-01", [(3000.0, self.goods_product, None)])
        services_bill = self._bill(self.sub_corp, "2026-08-02", [(5000.0, self.construction_account, None)])
        credit = self._bill(self.sub_corp, "2026-08-05", [(1000.0, self.construction_account, None)], move_type="in_refund")
        (self._payable(goods_bill) | self._payable(credit)).reconcile()
        self._pay(goods_bill, "2026-08-20")
        self._pay(services_bill, "2026-08-20")
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 4000.0)

    def test_untagged_holdback_release_is_flagged(self):
        untagged = self.env["account.account"].create({
            "name": "Holdbacks (untagged)", "code": "2192HB", "account_type": "liability_current",
        })
        untagged.tag_ids = [Command.clear()]
        self._pay(self._bill(self.sub_corp, "2026-06-01", [(10000.0, self.construction_account, None)]), "2026-06-20")
        self._pay(self._bill(self.sub_corp, "2026-07-01", [(1000.0, untagged, None)]), "2026-07-20")
        self.assertIn("releases a holdback", self._return("t5018").slip_ids.warning_message or "")

    def test_holdback_counts_when_released(self):
        bill = self._bill(self.sub_corp, "2026-06-01", [
            (10000.0, self.construction_account, self.gst), (-1000.0, self.holdback_account, None),
        ])
        self.assertAlmostEqual(bill.amount_total, 9500.0)
        self._pay(bill, "2026-06-20")
        release = self._bill(self.sub_corp, "2027-02-01", [(1000.0, self.holdback_account, self.gst)])
        self._pay(release, "2027-02-10")
        self.assertAlmostEqual(self._return("t5018", year=2026).slip_ids.amount_reported, 9500.0)
        self.assertAlmostEqual(self._return("t5018", year=2027).slip_ids.amount_reported, 1050.0)

    def test_t5018_needs_the_tag(self):
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(2000.0, self.service_product, None)]), "2026-03-10")
        self.assertFalse(self._return("t5018").slip_ids)

    def test_t4a_fees_and_goods_on_one_bill(self):
        self._pay(self._bill(self.contractor_a, "2026-05-04", [
            (300.0, self.fees_account, None), (500.0, self.goods_product, None), (400.0, self.fees_account, self.gst),
        ]), "2026-05-15")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 700.0)

    # Amended returns

    def test_amended_and_cancelled_slips_file_separately(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        self._pay(self._fee_bill(self.contractor_b, "2026-03-01", 900.0), "2026-03-10")
        original = self._filed(self._return())
        amendment = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        self._slip(amendment, self.contractor_a).write({"adjustment_base": 100.0, "adjustment_reason": "Late invoice"})
        self._slip(amendment, self.contractor_b).is_cancelled = True
        amendment.amendment_note = "Corrections."
        with self.assertRaisesRegex(UserError, "separate submissions"):
            amendment.action_finalize()
        self._slip(amendment, self.contractor_b).is_cancelled = False
        self._filed(amendment)
        cancel = self.env["l10n.ca.slip.return"].browse(amendment.action_create_amendment()["res_id"])
        self._slip(cancel, self.contractor_b).is_cancelled = True
        cancel.amendment_note = "Bailey Chen was an employee."
        root = self._finalize(cancel)
        self.assertEqual(root.findtext(".//T4ASummary/slp_cnt"), "1")
        self.assertEqual(root.findtext(".//T4ASummary/T4A_TAMT/rpt_tot_fee_srvc_amt"), "900.00")

    def test_amendment_note_limit(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        original = self._filed(self._return())
        amendment = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        self._slip(amendment, self.contractor_a).write({"adjustment_base": 100.0, "adjustment_reason": "Late invoice"})
        amendment.amendment_note = "x" * 1310
        with self.assertRaisesRegex(UserError, "1309"):
            amendment.action_finalize()

    # Security

    def test_full_sin_only_for_the_recipient_or_an_administrator_with_access(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        child = self.env["res.partner"].create({"name": "Alex assistant", "parent_id": self.contractor_a.id})
        child_user = self.env["res.users"].create({
            "name": "Alex assistant", "login": "alex.assistant", "partner_id": child.id,
            "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
        })
        other = self.setup_other_company()["company"]
        outsider = self.env["res.users"].create({
            "name": "Other controller", "login": "other.controller",
            "group_ids": [Command.set([self.env.ref("base.group_user").id, self.env.ref("account.group_account_manager").id])],
            "company_ids": [Command.set(other.ids)], "company_id": other.id,
        })
        for user in (child_user, outsider):
            html, _type = self.env["ir.actions.report"].with_user(user).sudo()._render_qweb_html(
                "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slip_return.slip_ids.ids
            )
            self.assertNotIn(PRINTED_SIN, html.decode(), user.name)

    def test_payer_account_not_on_recipient_copies(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        html, _type = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slip_return.slip_ids.ids
        )
        self.assertNotIn("123026635RP0001", html.decode())
        report = self.env.ref("l10n_ca_contractor_slips.action_report_l10n_ca_slip")
        self.assertEqual(report.paperformat_id.format, "Letter")
        # Odoo's letterhead prints the company's GST number; the slip has no letterhead.
        self.company.vat = "123026635RT0001"
        html, _type = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ca_contractor_slips.action_report_l10n_ca_slip", slip_return.slip_ids.ids
        )
        self.assertNotIn("123026635", html.decode())

    def test_only_accounting_administrators_change_slip_settings(self):
        partner = self.contractor_a.with_user(self.sales_user)
        for vals in ({"l10n_ca_slip_type": False}, {"l10n_ca_slip_email_consent": True}, {"l10n_ca_recipient_type": "3"}):
            with self.assertRaises(AccessError):
                partner.write(vals)
        partner.write({"phone": "403-555-0100"})
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 900.0)
        clerk = self.env["res.users"].create({
            "name": "Clerk", "login": "clerk.rules",
            "group_ids": [Command.set([self.env.ref("base.group_user").id, self.env.ref("account.group_account_invoice").id])],
            "company_ids": [Command.set(self.company.ids)], "company_id": self.company.id,
        })
        with self.assertRaises(AccessError):
            bill.with_user(clerk).write({"l10n_ca_slip_type": "none"})
        with self.assertRaises(AccessError):
            bill.with_user(clerk).write({"l10n_ca_slip_type": "none"})

    def test_new_email_needs_new_consent(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self.contractor_a.with_user(self.sales_user).write({"email": "sales@example.com"})
        self.assertFalse(self.contractor_a.l10n_ca_slip_email_consent)

    def test_email_goes_only_to_the_recipient(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        template = self.env.ref("l10n_ca_contractor_slips.mail_template_l10n_ca_slip")
        template.write({"email_cc": "spy@example.com", "partner_to": f"{self.contractor_a.id},{self.contractor_b.id}"})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        self._send(slip_return)
        mail = slip_return.slip_ids.sudo().mail_id
        self.assertEqual(mail.email_to, self.contractor_a.email_formatted)
        self.assertFalse(mail.recipient_ids)
        self.assertEqual(mail.partner_ids, self.contractor_a)
        self.assertFalse(mail.email_cc)

    def test_portal_cannot_read_internal_slip_fields(self):
        portal_user = self.env["res.users"].create({
            "name": "Alex portal", "login": "alex.rules", "partner_id": self.contractor_a.id,
            "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
        })
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        slip_return.slip_ids.write({"adjustment_base": 1.0, "adjustment_reason": "Internal note"})
        self._finalize(slip_return)
        slip = slip_return.slip_ids.with_user(portal_user)
        slip.read(["amount_reported"])
        for name in ("adjustment_reason", "engine_warnings", "warning_message", "email_failure"):
            with self.assertRaises(AccessError):
                slip.read([name])

    # Schemas and slip types per company

    def test_schemas_reload_when_the_package_changes(self):
        self._load_schemas()
        Return = self.env["l10n.ca.slip.return"]
        self.assertTrue(Return._l10n_ca_schemas_current())
        self.env["ir.config_parameter"].sudo().set_param(
            "l10n_ca_contractor_slips.cra_schema_url", "https://www.canada.ca/next-package.zip"
        )
        self.assertFalse(Return._l10n_ca_schemas_current())

    def test_branch_bill_takes_the_main_company_slip_type(self):
        branch = self._create_company(name="Airdrie branch", parent_id=self.company.id)
        self.env.user.company_ids |= branch
        bill = self.env["account.move"].with_company(branch).create({
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-03-01",
            "company_id": branch.id,
            "invoice_line_ids": [Command.create({"name": "Fees", "account_id": self.fees_account.id, "price_unit": 900.0,
                                                 "tax_ids": []})],
        })
        bill.action_post()
        self.assertEqual(bill.l10n_ca_slip_type, "t4a")

    def test_slip_type_is_per_company(self):
        other = self.setup_other_company()["company"]
        self.assertEqual(self.contractor_a.l10n_ca_slip_type, "t4a")
        self.assertFalse(self.contractor_a.with_company(other).l10n_ca_slip_type)
