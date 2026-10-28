# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Email delivery, branch access, and the slip type each bill keeps."""
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestDeliveryAndSnapshots(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.auditor = cls.env["res.users"].create({
            "name": "Auditor", "login": "auditor.r3",
            "groups_id": [Command.set([
                cls.env.ref("base.group_user").id, cls.env.ref("account.group_account_readonly").id,
                cls.env.ref("base.group_allow_export").id,
            ])],
            "company_ids": [Command.set(cls.company.ids)], "company_id": cls.company.id,
        })

    def _filed(self, slip_return):
        self._finalize(slip_return)
        slip_return.action_mark_filed()
        return slip_return

    def _branch_setup(self):
        branch = self._create_company(name="Lethbridge branch", parent_id=self.company.id)
        vendor = self.env["res.partner"].create({
            "name": "Erin Park", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1", "company_id": branch.id,
            "street": "2 Main St", "city": "Lethbridge", "zip": "T1J 0A1",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        self.env.user.company_ids |= branch
        bill = self.env["account.move"].with_company(branch).create({
            "move_type": "in_invoice", "partner_id": vendor.id, "invoice_date": "2026-03-01", "company_id": branch.id,
            "invoice_line_ids": [Command.create({"name": "Fees", "account_id": self.fees_account.id, "price_unit": 900.0,
                                                 "tax_ids": []})],
        })
        bill.action_post()
        self._register_payment(bill.with_company(branch), payment_date="2026-03-10")
        return branch, vendor

    def _manager(self, companies):
        return self.env["res.users"].create({
            "name": "Controller", "login": f"controller.{len(companies)}", "email": "controller@example.com",
            "groups_id": [Command.set([self.env.ref("base.group_user").id, self.env.ref("account.group_account_manager").id])],
            "company_ids": [Command.set(companies.ids)], "company_id": self.company.id,
        })

    # Emailed PDF stays out of the chatter

    def test_emailed_pdf_never_reaches_the_slip_chatter(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        self._send(slip_return)
        slip = slip_return.slip_ids
        self.assertFalse(slip.message_ids.attachment_ids)
        self.assertTrue(any("queued for email" in str(m.body) for m in slip.message_ids))
        mail = self._slip_mail(self.contractor_a)
        self.assertEqual(len(mail), 1)
        self.assertFalse(mail.model)
        self.assertEqual(len(mail.attachment_ids), 1)
        with self.assertRaises(AccessError):
            mail.attachment_ids.with_user(self.auditor).check_access("read")

    def _private_files(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        self._send(slip_return)
        xml = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", slip_return._name), ("res_id", "=", slip_return.id), ("res_field", "=", "xml_file"),
        ])
        files = xml | slip_return.slip_ids.sudo().mail_id.attachment_ids
        self.assertEqual(len(files), 2)
        self.assertEqual(files.mapped("l10n_ca_slip_company_id"), self.company)
        return files

    def test_private_xml_and_pdf_refuse_read_search_and_export(self):
        files = self._private_files().with_user(self.auditor)
        self.assertFalse(files.search([("id", "in", files.ids)]))
        with self.assertRaises(AccessError):
            files.read(["datas"])
        with self.assertRaises(AccessError):
            files.export_data(["datas"])

    def test_private_files_refuse_another_company_administrator(self):
        files = self._private_files()
        other = self.setup_other_company(name="Other payer")["company"]
        user = self._user("other.files", ["base.group_user", "account.group_account_manager"], companies=other)
        with self.assertRaises(AccessError):
            files.with_user(user).read(["datas"])

    def test_payer_administrator_reads_private_files(self):
        files = self._private_files()
        self.assertTrue(self.env.user.has_group("account.group_account_manager"))
        self.assertTrue(all(row["datas"] for row in files.with_user(self.env.user).read(["datas"])))

    def test_private_file_restrictions_cannot_be_removed(self):
        files = self._private_files()
        user = self._user("payer.files", ["base.group_user", "account.group_account_manager"])
        for values in ({"l10n_ca_slip_company_id": False}, {"public": True}):
            with self.assertRaises(AccessError):
                files.with_user(user).write(values)
        with self.assertRaises(UserError):
            files.with_user(user).generate_access_token()

    # Branches respect the user's companies

    def test_branch_outside_the_users_companies_blocks_the_return(self):
        branch, _vendor = self._branch_setup()
        controller = self._manager(self.company)
        slip_return = self.env["l10n.ca.slip.return"].with_user(controller).create({"slip_type": "t4a", "year": 2026})
        with self.assertRaisesRegex(UserError, "Lethbridge branch"):
            slip_return.action_compute()

    def test_branch_deselected_still_computes_finalizes_and_prints(self):
        branch, vendor = self._branch_setup()
        controller = self._manager(self.company | branch)
        slip_return = self.env["l10n.ca.slip.return"].with_user(controller).with_context(
            allowed_company_ids=self.company.ids
        ).create({"slip_type": "t4a", "year": 2026})
        slip_return.action_compute()
        self.assertEqual(slip_return.slip_ids.partner_id, vendor)
        self._load_schemas()
        slip_return.action_finalize()
        self.assertEqual(slip_return.state, "final")
        slip_return.action_print_slips()

    def test_returns_belong_to_the_main_company(self):
        branch, _vendor = self._branch_setup()
        self.assertEqual(self.env["l10n.ca.slip.return"].with_company(branch).create(
            {"slip_type": "t4a", "year": 2026}
        ).company_id, self.company)
        with self.assertRaises(ValidationError):
            self.env["l10n.ca.slip.return"].create({"slip_type": "t4a", "year": 2026, "company_id": branch.id})

    # Extra expense on a settling payment counts

    def test_extra_fee_paid_with_a_bill_counts(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        self._register_payment(bill, payment_date="2026-03-10", journal_id=self.bank_journal.id, amount=1500.0,
                               payment_difference_handling="reconcile",
                               writeoff_account_id=self.fees_account.id, writeoff_label="Call-out")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 1500.0)

    # Snapshot follows vendor changes and reversals

    def test_vendor_changed_before_reposting(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 3000.0)
        self.assertEqual(bill.l10n_ca_slip_type, "t4a")
        bill.button_draft()
        bill.partner_id = self.sub_individual
        bill.action_post()
        self.assertEqual(bill.l10n_ca_slip_type, "t5018")

    def test_reversal_keeps_the_bills_slip_type(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 5000.0)
        self._pay(bill, "2026-03-10")
        self.contractor_a.l10n_ca_slip_type = "t5018"
        reversal = bill._reverse_moves([{"invoice_date": "2026-04-01", "date": "2026-04-01"}])
        reversal.action_post()
        self.assertEqual(reversal.l10n_ca_slip_type, "t4a")

    # A credit note keeps its own mix

    def test_credit_note_refunded_in_cash_uses_its_own_mix(self):
        self.company.l10n_ca_t5018_include_mixed_goods = False
        bill_1 = self._bill(self.sub_corp, "2026-03-01", [
            (1000.0, self.construction_account, None), (1000.0, self.goods_product, None),
        ])
        self._pay(bill_1, "2026-03-10")
        bill_2 = self._bill(self.sub_corp, "2026-04-01", [(500.0, self.construction_account, None)])
        credit = self._bill(self.sub_corp, "2026-04-05", [
            (500.0, self.construction_account, None), (500.0, self.goods_product, None),
        ], move_type="in_refund")
        (bill_2 + credit).line_ids.filtered(lambda l_: l_.display_type == "payment_term").reconcile()
        self._pay(credit, "2026-04-20")
        # 1,500 of construction billed, 500 of it credited back.
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 1000.0)

    # Cancelling a slip filed without a province

    def test_slip_without_province_can_be_cancelled(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1000.0), "2026-03-10")
        original = self._return()
        original.slip_ids.state_code = "AB"
        original = self._filed(original)
        self.env.cr.execute("UPDATE l10n_ca_slip SET state_code = NULL WHERE id IN %s", [tuple(original.slip_ids.ids)])
        original.slip_ids.invalidate_recordset(["state_code"])
        amendment = self.env["l10n.ca.slip.return"].browse(original.action_create_amendment()["res_id"])
        self.assertFalse(amendment.slip_ids.state_code)
        amendment.slip_ids.is_cancelled = True
        amendment.amendment_note = "Not a contractor."
        self._finalize(amendment)
        self.assertEqual(amendment.slip_ids.rpt_tcd, "C")


@tagged("post_install", "-at_install")
class TestCreditNotesAndDiscounts(L10nCaSlipsCommon):

    def test_credit_note_with_a_different_mix(self):
        self.company.l10n_ca_t5018_include_mixed_goods = False
        bill = self._bill(self.sub_corp, "2026-03-01", [
            (1000.0, self.construction_account, None), (1000.0, self.goods_product, None),
        ])
        credit = self._bill(self.sub_corp, "2026-03-05", [
            (200.0, self.construction_account, None), (800.0, self.goods_product, None),
        ], move_type="in_refund")
        (bill + credit).line_ids.filtered(lambda l_: l_.display_type == "payment_term").reconcile()
        self._pay(bill, "2026-03-20")
        self.assertAlmostEqual(self._return("t5018").slip_ids.amount_reported, 800.0)

    def test_refund_write_off_is_not_extra_fees(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 2000.0), "2026-03-10")
        credit = self._fee_bill(self.contractor_a, "2026-04-01", 1000.0, move_type="in_refund")
        self._register_payment(credit, payment_date="2026-04-10", journal_id=self.bank_journal.id, amount=950.0,
                               payment_difference_handling="reconcile",
                               writeoff_account_id=self.fees_account.id, writeoff_label="Kept by vendor")
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 1050.0)

    def test_discount_and_extra_work_on_one_bank_entry(self):
        bill = self._fee_bill(self.contractor_a, "2026-03-01", 1000.0)
        payable = bill.line_ids.filtered(lambda l_: l_.display_type == "payment_term")
        entry = self.env["account.move"].create({
            "move_type": "entry", "journal_id": self.bank_journal.id, "date": "2026-03-15",
            "line_ids": [
                Command.create({"account_id": payable.account_id.id, "partner_id": self.contractor_a.id, "debit": 1000.0}),
                Command.create({"account_id": self.supplies_account.id, "partner_id": self.contractor_a.id, "credit": 100.0}),
                Command.create({"account_id": self.fees_account.id, "partner_id": self.contractor_a.id, "debit": 500.0}),
                Command.create({"account_id": self.bank_journal.default_account_id.id, "credit": 1400.0}),
            ],
        })
        entry.action_post()
        (payable | entry.line_ids.filtered(lambda l_: l_.account_id == payable.account_id)).reconcile()
        self.assertAlmostEqual(self._return().slip_ids.amount_reported, 1400.0)

    def test_email_delivery_is_tracked_on_the_slip(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        slip_return.action_send_slips()
        slip = slip_return.slip_ids
        self.assertEqual(slip.email_state, "outgoing")
        self.assertFalse(slip.mail_id)
        slip.sudo()._send_pending()
        self.assertTrue(slip.mail_id)
        self.assertEqual(slip.email_state, "outgoing")
        slip.mail_id.sudo().write({"state": "exception", "failure_reason": "Mailbox unavailable"})
        slip.invalidate_recordset(["email_state"])
        self.assertEqual(slip.email_state, "exception")
        self.assertTrue(slip.mail_id.sudo().auto_delete)
        # Deleting a failed email by hand leaves the slip not emailed, ready to send again.
        slip.mail_id.sudo().unlink()
        slip.invalidate_recordset(["email_state", "mail_id", "sent_date"])
        self.assertFalse(slip.email_state)

    def test_switching_to_another_contact_of_the_vendor_keeps_the_override(self):
        person = self.env["res.partner"].create({"name": "Accounts desk", "parent_id": self.sub_corp.id})
        bill = self._bill(self.sub_corp, "2026-03-01", [(900.0, self.construction_account, None)], post=False)
        bill.l10n_ca_slip_type = "none"
        bill.partner_id = person
        self.assertEqual(bill.l10n_ca_slip_type, "none")
