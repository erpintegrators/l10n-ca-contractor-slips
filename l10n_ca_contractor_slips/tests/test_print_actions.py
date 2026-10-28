# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Print slips and Print duplicates, requested the way Odoo's web client requests them."""
import json
from urllib.parse import quote

from odoo.tests import HttpCase, tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestPrintActions(L10nCaSlipsCommon, HttpCase):
    freeze_time = None  # the test HTTP server runs on the real clock

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._user("print.manager", ["base.group_user", "account.group_account_manager"]).password = "print.manager"
        cls._user("print.staff", ["base.group_user"]).password = "print.staff"

    def setUp(self):
        super().setUp()
        for partner in (self.contractor_a, self.contractor_b):
            self._pay(self._fee_bill(partner, "2026-03-01", 900.0), "2026-03-10")
        self.slip_return = self._return()
        self._finalize(self.slip_return)

    def _request(self, action, login="print.manager"):
        # An action with options reaches the controller with no ids in the URL: the client sends the
        # options and the action's context instead.
        self.authenticate(login, login)
        return self.url_open("/report/pdf/%s?options=%s&context=%s" % (
            action["report_name"], quote(json.dumps(action["data"])), quote(json.dumps(action["context"])),
        ))

    def _as_the_client_requests(self, action):
        response = self._request(action)
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_print_slips_from_the_button_prints_every_slip_twice(self):
        page = self._as_the_client_requests(self.slip_return.action_print_slips())
        self.assertEqual(page.count('class="o_l10n_ca_slip"'), 4)
        for partner in (self.contractor_a, self.contractor_b):
            self.assertIn(partner.name.split()[-1], page)

    def test_print_duplicates_from_the_button_marks_every_copy(self):
        page = self._as_the_client_requests(self.slip_return.action_print_duplicates())
        self.assertEqual(page.count('class="o_l10n_ca_slip"'), 4)
        self.assertIn("DUPLICATE", page)

    def test_slip_ids_in_the_options_follow_the_access_rules(self):
        # A user who may not read slips gets no slip through ids placed in the options.
        response = self._request(self.slip_return.action_print_slips(), login="print.staff")
        self.assertEqual(response.status_code, 403)

    def test_malformed_ids_in_the_options_print_nothing(self):
        action = self.slip_return.action_print_slips()
        for bad in (["2"], [-1, 0], [True], [[1]], "1,2", None):
            response = self._request({**action, "data": {**action["data"], "ids": bad}})
            self.assertEqual(response.status_code, 200, bad)
            self.assertNotIn('class="o_l10n_ca_slip"', response.text, bad)
