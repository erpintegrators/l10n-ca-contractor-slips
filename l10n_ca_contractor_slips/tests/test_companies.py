# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Two businesses in one database, and the branches of one business."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

from .common import OTHER_SIN, PAYER_BN, VALID_SIN, L10nCaSlipsCommon

OTHER_BN = "100000009"


@tagged("post_install", "-at_install")
class TestCompanies(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other = cls.setup_other_company(name="Foothills Holdings")["company"]
        cls.other.partner_id.write({
            "street": "8 Centre Street", "city": "Calgary", "zip": "T2G 0B4",
            "state_id": cls.env.ref("base.state_ca_ab").id, "country_id": cls.env.ref("base.ca").id,
        })
        cls.other.write({
            "l10n_ca_slip_rp_account": f"{OTHER_BN}RP0001",
            "l10n_ca_slip_rz_account": f"{OTHER_BN}RZ0001",
            "l10n_ca_slip_transmitter_account": OTHER_BN,
            "l10n_ca_slip_contact_id": cls.env["res.partner"].create({
                "name": "Robin Ledger", "phone": "+1 403-555-0199", "email": "robin@example.com",
                "parent_id": cls.other.partner_id.id,
            }).id,
        })
        cls.env.user.company_ids |= cls.other
        cls.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        cls.contractor_a.with_company(cls.other).l10n_ca_slip_type = "t4a"

    def _other_paid_bill(self, amount=2000.0):
        Move = self.env["account.move"].with_company(self.other)
        expense = self.env["account.account"].with_company(self.other).search([
            ("company_ids", "in", self.other.id), ("account_type", "=", "expense"),
        ], limit=1)
        expense.tag_ids |= self.tag_t4a
        bill = Move.create({
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-04-01",
            "company_id": self.other.id,
            "invoice_line_ids": [Command.create({"name": "Fees", "account_id": expense.id, "price_unit": amount})],
        })
        bill.action_post()
        self._register_payment(bill.with_company(self.other), payment_date="2026-04-10")

    def _other_return(self):
        slip_return = self.env["l10n.ca.slip.return"].with_company(self.other).create({"slip_type": "t4a", "year": 2026})
        slip_return.action_compute()
        return slip_return

    # Each business files its own return

    def test_each_business_files_its_own_return_for_the_same_contractor(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._other_paid_bill()
        ours, theirs = self._return(), self._other_return()
        self.assertEqual(theirs.company_id, self.other)
        self.assertAlmostEqual(self._slip(ours, self.contractor_a).amount_reported, 900.0)
        self.assertAlmostEqual(self._slip(theirs, self.contractor_a).amount_reported, 2000.0)
        our_xml, their_xml = self._finalize(ours), self._finalize(theirs)
        self.assertEqual(our_xml.findtext(".//T4ASummary/bn"), f"{PAYER_BN}RP0001")
        self.assertEqual(their_xml.findtext(".//T4ASummary/bn"), f"{OTHER_BN}RP0001")
        self.assertNotEqual(ours.sbmt_ref_id, theirs.sbmt_ref_id)
        outsider = self._user("foothills.only", ["base.group_user", "account.group_account_manager"], companies=self.other)
        Slip = self.env["l10n.ca.slip"].with_user(outsider)
        self.assertEqual(Slip.search([("partner_id", "=", self.contractor_a.id)]), theirs.slip_ids)

    def test_recipient_of_two_businesses_sees_both_slips_with_their_payer(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._other_paid_bill()
        ours, theirs = self._return(), self._other_return()
        self._finalize(ours)
        self._finalize(theirs)
        portal = self._user("alex.two", ["base.group_portal"], partner=self.contractor_a)
        slips = self.env["l10n.ca.slip"].with_user(portal).search([])
        self.assertEqual(slips, ours.slip_ids | theirs.slip_ids)
        self.assertEqual(set(slips.mapped("company_id.name")), {"Northern Build Co", "Foothills Holdings"})

    # Email consent belongs to the business it was given to

    def _both_final(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._other_paid_bill()
        ours, theirs = self._return(), self._other_return()
        self._finalize(ours)
        self._finalize(theirs)
        # Opened while working in Northern Build Co, as a user with both companies would.
        Return = self.env["l10n.ca.slip.return"]
        # Consent given to Foothills Holdings only.
        self.contractor_a.with_company(self.company).l10n_ca_slip_email_consent = False
        self.contractor_a.with_company(self.other).l10n_ca_slip_email_consent = True
        return Return.browse(ours.id), Return.browse(theirs.id)

    def test_consent_given_to_one_business_does_not_cover_another(self):
        ours, theirs = self._both_final()
        self._send(ours)
        self._send(theirs)
        self.assertFalse(ours.slip_ids.sudo().mail_id)
        self.assertIn("Give the other 1 recipient(s) two paper copies", ours.message_ids[0].body)
        self.assertTrue(theirs.slip_ids.sudo().mail_id)
        self.assertEqual(len(self._slip_mail(self.contractor_a)), 1)

    def test_queued_email_needs_the_paying_business_own_consent(self):
        ours, theirs = self._both_final()
        slips = (ours.slip_ids | theirs.slip_ids).sudo()
        # Queued by hand, as if consent had been read from the wrong business. Whichever company
        # the sender works in first, one of the two would go out on the other's consent.
        slips.write({"send_requested_uid": self.env.uid, "send_to_email": self.contractor_a.email_formatted})
        slips._send_pending()
        self.assertFalse(ours.slip_ids.sudo().mail_id)
        self.assertIn("no longer covers the address", ours.slip_ids.message_ids[0].body)
        self.assertTrue(theirs.slip_ids.sudo().mail_id)

    def test_consent_ticked_in_a_branch_is_kept_for_the_main_company(self):
        branch = self._create_company(name="Red Deer branch", parent_id=self.company.id)
        self.env.user.company_ids |= branch
        self.contractor_b.with_company(branch).write({"email": "bailey@example.com", "l10n_ca_slip_email_consent": True})
        self.assertTrue(self.contractor_b.with_company(self.company).l10n_ca_slip_email_consent)
        self.assertTrue(self.contractor_b.with_company(self.company).l10n_ca_slip_email_consent_date)
        self.assertFalse(self.contractor_b.with_company(self.other).l10n_ca_slip_email_consent)

    def test_new_address_withdraws_consent_from_every_business(self):
        self.contractor_a.with_company(self.other).l10n_ca_slip_email_consent = True
        self.contractor_a.email = "alex.new@example.com"
        for company in (self.company, self.other):
            with self.subTest(company=company.name):
                self.assertFalse(self.contractor_a.with_company(company).l10n_ca_slip_email_consent)
                self.assertFalse(self.contractor_a.with_company(company).l10n_ca_slip_email_consent_date)

    def test_requester_who_lost_the_payer_company_does_not_send(self):
        controller = self._user(
            "controller.both", ["base.group_user", "account.group_account_manager"], companies=self.company | self.other
        )
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        slip_return.with_user(controller).action_send_slips()
        controller.write({"company_id": self.other.id, "company_ids": [Command.set(self.other.ids)]})
        slip = slip_return.slip_ids.sudo()
        slip._send_pending()
        self.assertFalse(slip.mail_id)
        self.assertIn("can no longer send slips", slip.message_ids[0].body)

    # The SIN stays with the business that collected it

    def _outsider(self):
        return self._user("foothills.sin", [
            "base.group_user", "base.group_partner_manager", "base.group_allow_export", "account.group_account_manager",
        ], companies=self.other)

    def test_another_business_cannot_read_a_shared_contacts_sin(self):
        outsider = self._outsider()
        self.env.flush_all()
        self.env.invalidate_all()
        as_outsider = self.contractor_a.with_user(outsider).with_context(allowed_company_ids=self.other.ids)
        self.assertFalse(as_outsider.l10n_ca_sin)
        self.assertFalse(as_outsider.read(["l10n_ca_sin"])[0]["l10n_ca_sin"])
        Partner = self.env["res.partner"].with_user(outsider).with_context(allowed_company_ids=self.other.ids)
        self.assertFalse(Partner.search([("l10n_ca_sin", "=", VALID_SIN)]))
        exported = as_outsider.export_data(["l10n_ca_sin"])["datas"]
        self.assertNotIn(VALID_SIN, str(exported))
        self.assertEqual(self.contractor_a.sudo().with_company(self.company).l10n_ca_sin, VALID_SIN)

    def test_each_business_keeps_the_sin_it_collected(self):
        outsider = self._outsider()
        self.contractor_a.with_user(outsider).with_context(allowed_company_ids=self.other.ids).l10n_ca_sin = OTHER_SIN
        self.assertEqual(self.contractor_a.sudo().with_company(self.other).l10n_ca_sin, OTHER_SIN)
        self.assertEqual(self.contractor_a.sudo().with_company(self.company).l10n_ca_sin, VALID_SIN)

    def test_sin_typed_in_a_branch_is_kept_for_the_main_company(self):
        branch = self._create_company(name="Banff branch", parent_id=self.company.id)
        self.env.user.company_ids |= branch
        self.contractor_c.with_company(branch).l10n_ca_sin = OTHER_SIN
        self.assertEqual(self.contractor_c.sudo().with_company(self.company).l10n_ca_sin, OTHER_SIN)
        self.assertFalse(self.contractor_c.sudo().with_company(self.other).l10n_ca_sin)

    def test_each_return_reports_its_own_businesss_sin(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._other_paid_bill()
        ours, theirs = self._return(), self._other_return()
        self.assertEqual(self._slip(ours, self.contractor_a).sudo().sin, VALID_SIN)
        self.assertFalse(self._slip(theirs, self.contractor_a).sudo().sin)
        self.assertIn("No SIN on the contact", self._slip(theirs, self.contractor_a).warning_message)
        # Whatever company the user works in, the snapshot takes the paying company's SIN.
        Slip = self.env["l10n.ca.slip"].with_company(self.company)
        self.assertFalse(Slip._recipient_values(self.contractor_a, self.other)["sin"])
        self.assertEqual(Slip.with_company(self.other)._recipient_values(self.contractor_a, self.company)["sin"], VALID_SIN)

    def test_only_an_administrator_of_every_paying_business_merges_their_contractor(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._filed(self._return())
        duplicate = self.env["res.partner"].with_company(self.other).create({"name": "A. Martin", "email": "alex@example.com"})
        duplicate.with_company(self.other).l10n_ca_sin = VALID_SIN
        Wizard = self.env["base.partner.merge.automatic.wizard"]
        with self.assertRaisesRegex(UserError, "accounting administrator"):
            Wizard.with_user(self._outsider())._merge((self.contractor_a | duplicate).ids, duplicate)
        self.assertEqual(slip_return.slip_ids.partner_id, self.contractor_a)
        self.assertTrue(duplicate.exists())
        both = self._user("group.controller", [
            "base.group_user", "base.group_partner_manager", "account.group_account_manager",
        ], companies=self.company | self.other)
        Wizard.with_user(both)._merge((self.contractor_a | duplicate).ids, self.contractor_a)
        self.assertFalse(duplicate.exists())
        self.assertEqual(slip_return.slip_ids.partner_id, self.contractor_a)
        self.assertEqual(self.contractor_a.sudo().with_company(self.company).l10n_ca_sin, VALID_SIN)
        self.assertEqual(self.contractor_a.sudo().with_company(self.other).l10n_ca_sin, VALID_SIN)

    def test_administrator_of_another_business_cannot_carry_off_a_sin(self):
        holder = self.env["res.partner"].create({"name": "Sam Ortiz", "email": "sam@example.com", "l10n_ca_sin": OTHER_SIN})
        duplicate = self.env["res.partner"].create({"name": "Sam Ortiz", "email": "sam@example.com"})
        with self.assertRaisesRegex(UserError, "accounting administrator"):
            self.env["base.partner.merge.automatic.wizard"].with_user(self._outsider())._merge(
                (holder | duplicate).ids, duplicate
            )
        self.assertEqual(holder.sudo().with_company(self.company).l10n_ca_sin, OTHER_SIN)

    # Found by the multi-company approver

    def test_new_address_with_consent_in_one_save_keeps_other_businesses_out(self):
        self.contractor_a.with_company(self.other).l10n_ca_slip_email_consent = True
        self.contractor_a.write({"email": "alex.new@example.com", "l10n_ca_slip_email_consent": True})
        self.assertTrue(self.contractor_a.with_company(self.company).l10n_ca_slip_email_consent)
        self.assertFalse(self.contractor_a.with_company(self.other).l10n_ca_slip_email_consent)

    def test_consent_box_names_the_company_it_covers(self):
        self.assertEqual(self.contractor_a.with_company(self.other).l10n_ca_slip_consent_company_id, self.other)
        branch = self._create_company(name="Cochrane branch", parent_id=self.company.id)
        self.env.user.company_ids |= branch
        self.assertEqual(self.contractor_a.with_company(branch).l10n_ca_slip_consent_company_id, self.company)

    def test_head_office_delivers_slips_of_a_contact_kept_to_a_branch(self):
        branch = self._create_company(name="Canmore branch", parent_id=self.company.id)
        self.env.user.company_ids |= branch
        self.contractor_a.company_id = branch
        bill = self.env["account.move"].with_company(branch).create({
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-03-01",
            "company_id": branch.id,
            "invoice_line_ids": [Command.create({
                "name": "Fees", "account_id": self.fees_account.id, "price_unit": 900.0, "tax_ids": [],
            })],
        })
        bill.action_post()
        self._register_payment(bill.with_company(branch), payment_date="2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        controller = self._user("hq.delivers", ["base.group_user", "account.group_account_manager"])
        as_controller = slip_return.with_user(controller)
        self.env.invalidate_all()
        self.assertTrue(as_controller.slip_ids.display_name)
        as_controller.action_print_slips()
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        as_controller.action_send_slips()
        slip = slip_return.slip_ids.sudo()
        self.assertTrue(slip.send_requested_uid)
        # The scheduled job runs later, in its own transaction, with nothing cached.
        self.env.invalidate_all()
        slip._send_pending()
        self.assertTrue(slip.mail_id, slip.message_ids[:1].body)

    def test_merge_keeps_consent_only_with_its_address(self):
        duplicate = self.env["res.partner"].with_company(self.other).create({
            "name": "A. Martin", "email": "a.martin@example.com", "l10n_ca_slip_email_consent": True,
        })
        self.assertTrue(duplicate.with_company(self.other).l10n_ca_slip_email_consent)
        self.env["base.partner.merge.automatic.wizard"]._merge((self.contractor_a | duplicate).ids, self.contractor_a)
        self.assertFalse(self.contractor_a.with_company(self.other).l10n_ca_slip_email_consent)
        self.assertTrue(self.contractor_a.with_company(self.company).l10n_ca_slip_email_consent)


@tagged("post_install", "-at_install")
class TestCompaniesPortal(L10nCaSlipsCommon, HttpCase):
    freeze_time = None  # the test HTTP server runs on the real clock

    def test_portal_list_for_a_recipient_paid_by_two_businesses_and_invited_from_a_branch(self):
        other = self.setup_other_company(name="Foothills Holdings")["company"]
        other.write({"l10n_ca_slip_rp_account": "100000009RP0001", "l10n_ca_slip_transmitter_account": "100000009",
                     "l10n_ca_slip_contact_id": self.filing_contact.copy({"parent_id": other.partner_id.id}).id})
        other.partner_id.write({"street": "8 Centre Street", "city": "Calgary", "zip": "T2G 0B4",
                                "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id})
        branch = self._create_company(name="Okotoks branch", parent_id=self.company.id)
        self.env.user.company_ids |= other | branch
        self.contractor_a.with_company(other).l10n_ca_slip_type = "t4a"
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        expense = self.env["account.account"].with_company(other).search([
            ("company_ids", "in", other.id), ("account_type", "=", "expense"),
        ], limit=1)
        expense.tag_ids |= self.tag_t4a
        bill = self.env["account.move"].with_company(other).create({
            "move_type": "in_invoice", "partner_id": self.contractor_a.id, "invoice_date": "2026-04-01",
            "company_id": other.id,
            "invoice_line_ids": [Command.create({"name": "Fees", "account_id": expense.id, "price_unit": 2000.0})],
        })
        bill.action_post()
        self._register_payment(bill.with_company(other), payment_date="2026-04-10")
        ours = self._return()
        theirs = self.env["l10n.ca.slip.return"].with_company(other).create({"slip_type": "t4a", "year": 2026})
        theirs.action_compute()
        self._finalize(ours)
        self._finalize(theirs)
        # A portal login made while working in a branch belongs to the branch only.
        self.env["res.users"].create({
            "name": "Alex Martin", "login": "alex.branch", "password": "alex.branch",
            "partner_id": self.contractor_a.id, "groups_id": [Command.set([self.env.ref("base.group_portal").id])],
            "company_ids": [Command.set(branch.ids)], "company_id": branch.id,
        })
        self.authenticate("alex.branch", "alex.branch")
        response = self.url_open("/my/slips")
        self.assertEqual(response.status_code, 200)
        for slip in ours.slip_ids | theirs.slip_ids:
            self.assertIn(f"/my/slips/{slip.id}", response.text)
        self.assertIn("Northern Build Co", response.text)
        self.assertIn("Foothills Holdings", response.text)
