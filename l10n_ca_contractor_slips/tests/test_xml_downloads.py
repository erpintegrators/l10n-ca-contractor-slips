# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo.tests import HttpCase, tagged

from .common import VALID_SIN, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestXmlDownloads(L10nCaSlipsCommon, HttpCase):
    freeze_time = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._user("xml.manager", ["base.group_user", "account.group_account_manager"]).password = "xml.manager"
        cls._user("xml.readonly", ["base.group_user", "account.group_account_readonly"]).password = "xml.readonly"

    def setUp(self):
        super().setUp()
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self.slip_return = self._return()
        self._finalize(self.slip_return)

    def test_download_preserves_xml_bytes_and_filename(self):
        expected = self._xml_bytes(self.slip_return)
        self.authenticate("xml.manager", "xml.manager")
        response = self.url_open(self.slip_return.action_download_xml()["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, expected)
        self.assertIn(self.slip_return.xml_filename, response.headers.get("Content-Disposition", ""))
        self.assertTrue(response.content.startswith(b"<?xml"))

    def test_readonly_accountant_cannot_download_full_sin_xml(self):
        self.authenticate("xml.readonly", "xml.readonly")
        response = self.url_open(self.slip_return.action_download_xml()["url"], allow_redirects=False)
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn(VALID_SIN, response.text)
        self.assertNotIn("<Submission>", response.text)
