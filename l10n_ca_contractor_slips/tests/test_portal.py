# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
import json

from odoo import Command
from odoo.tests import HttpCase, tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestPortal(L10nCaSlipsCommon, HttpCase):
    freeze_time = None  # the test HTTP server runs on the real clock

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = cls.env["res.users"].create({
            "name": "Alex Martin",
            "login": "alex.portal",
            "password": "alex.portal",
            "partner_id": cls.contractor_a.id,
            "groups_id": [Command.set([cls.env.ref("base.group_portal").id])],
        })
        for partner in (cls.contractor_a, cls.contractor_b):
            cls._pay(cls._fee_bill(partner, "2026-03-01", 900.0), "2026-03-10")

    def setUp(self):
        super().setUp()
        self.slip_return = self._return()
        self._finalize(self.slip_return)
        self.own = self._slip(self.slip_return, self.contractor_a)
        self.other = self._slip(self.slip_return, self.contractor_b)

    def test_list_shows_only_own_slips(self):
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open("/my/slips")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/my/slips/{self.own.id}", response.text)
        self.assertNotIn(f"/my/slips/{self.other.id}", response.text)

    def test_list_draws_one_breadcrumb_trail(self):
        # The layout and the search bar each draw the trail unless both are told the search bar has it.
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open("/my/slips")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count("o_portal_submenu"), 1)

    def test_detail_and_pdf_for_own_slip(self):
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open(f"/my/slips/{self.own.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Download PDF", response.text)
        self.assertIn("If you would rather have paper copies", response.text)
        response = self.url_open(f"/my/slips/{self.own.id}?report_type=pdf&download=true")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))

    def test_other_recipients_slip_redirects(self):
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open(f"/my/slips/{self.other.id}?report_type=pdf&download=true", allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers["Location"].endswith("/my"))

    def test_access_token_link_works_without_login(self):
        response = self.url_open(f"/my/slips/{self.own.id}?access_token={self.own.access_token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Download PDF", response.text)
        response = self.url_open(f"/my/slips/{self.own.id}?access_token=wrong", allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))

    def test_draft_slip_not_reachable_by_token(self):
        self.slip_return.action_reset_to_draft()
        response = self.url_open(f"/my/slips/{self.own.id}?access_token={self.own.access_token}", allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))

    def test_portal_home_counter(self):
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open(
            "/my/counters", data=json.dumps({"params": {"counters": ["l10n_ca_slip_count"]}}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["l10n_ca_slip_count"], 1)

    def test_portal_home_contains_the_tax_slips_entry(self):
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open("/my")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/my/slips"', response.text)
        self.assertIn('data-placeholder_count="l10n_ca_slip_count"', response.text)

    def test_portal_counter_excludes_draft_slips(self):
        self.slip_return.action_reset_to_draft()
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open(
            "/my/counters", data=json.dumps({"params": {"counters": ["l10n_ca_slip_count"]}}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["l10n_ca_slip_count"], 0)

    def test_list_page_for_a_contact_without_slips(self):
        self.env["res.users"].create({
            "name": "Casey Roy", "login": "casey.portal", "password": "casey.portal",
            "partner_id": self.contractor_c.id,
            "groups_id": [Command.set([self.env.ref("base.group_portal").id])],
        })
        self.authenticate("casey.portal", "casey.portal")
        response = self.url_open("/my/slips")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No tax slips", response.text)

    def test_replaced_slip_link_redirects(self):
        self.slip_return.action_mark_filed()
        amendment = self._amend(self.slip_return)
        self._slip(amendment, self.contractor_a).write({"adjustment_base": 100.0, "adjustment_reason": "Late invoice"})
        amendment.amendment_note = "Alex Martin: late invoice of 100.00."
        self._finalize(amendment)
        self.assertTrue(self.own.superseded)
        response = self.url_open(f"/my/slips/{self.own.id}?access_token={self.own.access_token}", allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.authenticate("alex.portal", "alex.portal")
        response = self.url_open("/my/slips/page/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/my/slips/{self._slip(amendment, self.contractor_a).id}", response.text)
        self.assertNotIn(f"/my/slips/{self.own.id}?", response.text)
