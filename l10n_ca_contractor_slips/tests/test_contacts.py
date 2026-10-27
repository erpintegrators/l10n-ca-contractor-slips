# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Contacts: who a recipient is, and what standard contact actions do to their slips."""
from lxml import etree

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from ..models.res_partner import guess_recipient_type
from .common import VALID_SIN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestContacts(L10nCaSlipsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sales_user = cls._user("sales.contacts", ["base.group_user", "base.group_partner_manager"])
        cls.controller = cls._user("controller.contacts", ["base.group_user", "account.group_account_manager"])

    def _merge(self, partners, keep, user=None):
        wizard = self.env["base.partner.merge.automatic.wizard"]
        if user:
            wizard = wizard.with_user(user)
        wizard._merge(partners.ids, keep)

    def _merge_with_wizard(self, partners, keep, user):
        """The Merge action a user runs from the contact list."""
        wizard = self.env["base.partner.merge.automatic.wizard"].with_user(user).with_context(
            active_model="res.partner", active_ids=partners.ids,
        ).create({"dst_partner_id": keep.id})
        wizard.action_merge()

    # Standard contact actions keep working for everyone

    def test_sales_user_can_duplicate_any_contact(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        plain = self.env["res.partner"].create({"name": "Walk-in customer"})
        for partner in (plain, self.contractor_a):
            copy = partner.with_user(self.sales_user).copy()
            self.assertFalse(copy.l10n_ca_recipient_type)
            self.assertFalse(copy.sudo().l10n_ca_sin)
            self.assertFalse(copy.l10n_ca_slip_email_consent)

    def test_sales_user_can_merge_contacts(self):
        first = self.env["res.partner"].create({"name": "Pat Doe", "email": "pat@example.com"})
        second = self.env["res.partner"].create({"name": "Pat Doe", "email": "pat@example.com"})
        self._merge(first | second, first, user=self.sales_user)
        self.assertFalse(second.exists())

    def test_merge_keeps_the_sin_when_only_the_duplicate_has_it(self):
        duplicate = self.env["res.partner"].create({
            "name": "Alex Martin", "email": "alex@example.com", "l10n_ca_sin": "413961806", "l10n_ca_recipient_type": "1",
        })
        keep = self.env["res.partner"].create({"name": "Alex Martin", "email": "alex@example.com"})
        self._merge(duplicate | keep, keep, user=self.controller)
        self.assertEqual(keep.sudo().l10n_ca_sin, "413961806")
        self.assertEqual(keep.l10n_ca_recipient_type, "1")

    # Merging contractors who already have slips

    def _duplicate_contractor(self):
        duplicate = self.env["res.partner"].create({
            "name": "Alex Martin", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1",
            "street": "12 River Road", "city": "Calgary", "zip": "T2P 1J9",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        (duplicate | self.contractor_a).write({"email": "alex@example.com"})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1850.0), "2026-03-10")
        self._pay(self._fee_bill(duplicate, "2026-04-01", 700.0), "2026-04-10")
        return duplicate

    def test_merge_refused_when_both_contacts_are_on_a_filed_return(self):
        duplicate = self._duplicate_contractor()
        slip_return = self._filed(self._return())
        with self.assertRaisesRegex(UserError, "final or filed"):
            self._merge(duplicate | self.contractor_a, self.contractor_a)
        self.assertEqual(len(slip_return.slip_ids), 2)
        self.assertAlmostEqual(slip_return.total_reported, 2550.0)

    def test_merge_on_a_draft_return_asks_for_recalculation(self):
        duplicate = self._duplicate_contractor()
        slip_return = self._return()
        self._merge(duplicate | self.contractor_a, self.contractor_a)
        self.assertEqual(slip_return.slip_ids.partner_id, self.contractor_a)
        self.assertIn("Recalculate", slip_return.message_ids[0].body)
        slip_return.action_compute()
        self.assertAlmostEqual(self._slip(slip_return, self.contractor_a).amount_reported, 2550.0)

    def test_merge_keeps_a_filed_slip_that_has_no_twin(self):
        duplicate = self.env["res.partner"].create({
            "name": "Casey Roy", "email": "casey@example.com", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1",
            "street": "12 River Road", "city": "Calgary", "zip": "T2P 1J9",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        self.contractor_c.email = "casey@example.com"
        self._pay(self._fee_bill(duplicate, "2026-04-01", 700.0), "2026-04-10")
        slip_return = self._filed(self._return())
        self.assertEqual(slip_return.slip_ids.partner_id, duplicate)
        accountant = self._user("controller.merge", [
            "base.group_user", "base.group_partner_manager", "account.group_account_manager",
        ])
        self._merge_with_wizard(duplicate | self.contractor_c, self.contractor_c, accountant)
        self.assertEqual(slip_return.slip_ids.partner_id, self.contractor_c)
        self.assertAlmostEqual(slip_return.slip_ids.amount_reported, 700.0)
        self.assertIn("now belong to Casey Roy", slip_return.message_ids[0].body)

    # Only accounting administrators merge contacts that hold slip details

    def test_contact_manager_cannot_move_a_filed_slip_to_another_portal_login(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1850.0), "2026-03-10")
        slip_return = self._filed(self._return())
        pending = self.env["res.partner"].create({"name": "Jordan Blake", "l10n_ca_recipient_type": "1"})
        portal = self._user("jordan.pending", ["base.group_portal"], partner=pending)
        with self.assertRaisesRegex(UserError, "accounting administrator"):
            self._merge_with_wizard(self.contractor_a | pending, pending, self.sales_user)
        self.assertEqual(slip_return.slip_ids.partner_id, self.contractor_a)
        self.assertFalse(self.env["l10n.ca.slip"].with_user(portal).search([]))

    def test_contact_manager_cannot_move_slips_of_a_contact_no_longer_flagged(self):
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 700.0), "2026-03-10")
        slip_return = self._filed(self._return())
        self.contractor_c.write({"l10n_ca_slip_type": False, "l10n_ca_recipient_type": False})
        stranger = self.env["res.partner"].create({"name": "Jordan Blake"})
        with self.assertRaisesRegex(UserError, "accounting administrator"):
            self._merge(self.contractor_c | stranger, stranger, user=self.sales_user)
        self.assertEqual(slip_return.slip_ids.partner_id, self.contractor_c)

    def test_contact_manager_cannot_drop_recipient_details(self):
        named = self.env["res.partner"].create({"name": "Lee Ann Park", "l10n_ca_slip_surname": "Park"})
        plain = self.env["res.partner"].create({"name": "Lee Ann Park"})
        with self.assertRaisesRegex(UserError, "accounting administrator"):
            self._merge(named | plain, plain, user=self.sales_user)
        self.assertTrue(named.exists())

    def test_contact_manager_cannot_merge_a_portal_login_into_a_contractor(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1850.0), "2026-03-10")
        self._filed(self._return())
        stranger = self.env["res.partner"].create({"name": "Jordan Blake"})
        portal = self._user("jordan.stranger", ["base.group_portal"], partner=stranger)
        with self.assertRaisesRegex(UserError, "accounting administrator"):
            self._merge_with_wizard(self.contractor_a | stranger, self.contractor_a, self.sales_user)
        self.assertEqual(portal.partner_id, stranger)
        self.assertFalse(self.env["l10n.ca.slip"].with_user(portal).search([]))

    # Recipient type

    def test_business_without_a_tax_id_is_not_filed_as_an_individual(self):
        roofer = self.env["res.partner"].create({
            "name": "Prairie Roofing Ltd", "l10n_ca_slip_type": "t5018",
            "street": "4 Ridge Road", "city": "Calgary", "zip": "T2P 1J9",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        self.assertFalse(roofer.is_company)
        self.assertEqual(guess_recipient_type(roofer), "3")
        self._pay(self._bill(roofer, "2026-05-01", [(5000.0, self.construction_account, self.gst)]), "2026-05-15")
        slip_return = self._return("t5018")
        slip = self._slip(slip_return, roofer)
        self.assertEqual((slip.recipient_type, slip.corp_name, slip.surname), ("3", "Prairie Roofing Ltd", False))
        self.assertTrue(slip.recipient_type_guessed)
        with self.assertRaisesRegex(UserError, "choose the slip recipient type"):
            self._finalize(slip_return)
        roofer.l10n_ca_recipient_type = "3"
        slip_return.action_compute()
        self.assertFalse(slip.recipient_type_guessed)

    def test_recipient_type_is_chosen_by_a_person(self):
        self.assertEqual(guess_recipient_type(self.env["res.partner"].new({"name": "Sam Okafor"})), "1")
        self.assertEqual(guess_recipient_type(self.env["res.partner"].new({"name": "Northline Electric Inc."})), "3")
        # Flagging a contact stores no guess: a two-word business name would pass as a person.
        partner = self.env["res.partner"].create({"name": "Northline Electric", "l10n_ca_slip_type": "t5018"})
        self.assertFalse(partner.l10n_ca_recipient_type)

    def test_compound_name_is_flagged_for_review(self):
        person = self.env["res.partner"].create({
            "name": "Maria De la Cruz", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1",
            "street": "4 Ridge Road", "city": "Calgary", "zip": "T2P 1J9",
            "state_id": self.env.ref("base.state_ca_ab").id, "country_id": self.env.ref("base.ca").id,
        })
        self._pay(self._fee_bill(person, "2026-05-01", 900.0), "2026-05-15")
        slip = self._slip(self._return(), person)
        self.assertEqual(slip.surname, "Cruz")
        self.assertIn("split from the contact name", slip.warning_message)
        person.l10n_ca_slip_surname = "De la Cruz"
        slip = self._slip(self._return(year=2026), person)
        self.assertEqual(slip.surname, "De la Cruz")
        self.assertNotIn("split from the contact name", slip.warning_message or "")

    # Settings stay with accounting administrators

    def test_defaults_cannot_set_slip_settings_for_other_users(self):
        Partner = self.env["res.partner"].with_user(self.sales_user)
        flagged = Partner.with_context(default_l10n_ca_slip_type="t4a").create({"name": "Context default"})
        self.assertFalse(flagged.l10n_ca_slip_type)
        self.env["ir.default"].with_user(self.sales_user).set(
            "res.partner", "l10n_ca_recipient_type", "1", user_id=self.sales_user.id
        )
        self.assertFalse(Partner.create({"name": "Personal default"}).l10n_ca_recipient_type)

    def test_invalid_sin_message_does_not_repeat_the_number(self):
        with self.assertRaises(ValidationError) as caught:
            self.env["res.partner"].create({"name": "Typo", "l10n_ca_sin": VALID_SIN[:-1] + "5"})
        self.assertNotIn(VALID_SIN[:-1], str(caught.exception))
        self.assertIn("Typo", str(caught.exception))

    def test_consent_records_its_date(self):
        self.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})
        self.assertEqual(self.contractor_a.l10n_ca_slip_email_consent_date, self._today())
        self.contractor_a.email = "alex.martin@example.com"
        self.assertFalse(self.contractor_a.l10n_ca_slip_email_consent)
        self.assertFalse(self.contractor_a.l10n_ca_slip_email_consent_date)

    def test_renamed_contact_with_a_surname_override_is_pointed_out(self):
        self.contractor_a.l10n_ca_slip_surname = "Martin"
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip = self._slip(self._return(), self.contractor_a)
        self.assertNotIn("is not part of the contact name", slip.warning_message or "")
        self.contractor_a.name = "Alex Lee"
        self.assertIn("The surname on the slip (Martin) is not part of the contact name (Alex Lee)", slip.warning_message)

    def test_accents_and_hyphens_do_not_count_as_a_different_surname(self):
        self.contractor_a.write({"name": "Alex Lévesque-Peña", "l10n_ca_slip_surname": "Levesque Pena"})
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip = self._slip(self._return(), self.contractor_a)
        self.assertNotIn("is not part of the contact name", slip.warning_message or "")

    def test_consent_company_shows_only_with_consent(self):
        # "Consent given to" next to an unticked box reads as consent on file.
        arch = self.env["res.partner"].get_view(view_type="form")["arch"]
        node = etree.fromstring(arch).xpath("//field[@name='l10n_ca_slip_consent_company_id']")[0]
        self.assertIn("not l10n_ca_slip_email_consent", node.get("invisible", ""))
