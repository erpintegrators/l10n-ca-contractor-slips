# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Slip emails the outgoing mail server refuses, sent through Odoo's real sending code."""
from freezegun import freeze_time

from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.addons.mail.tests.common import MockEmail
from odoo.tests import tagged

from .common import L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestEmailFailures(L10nCaSlipsCommon, MockEmail):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.contractor_a.write({"email": "alex@example.com", "l10n_ca_slip_email_consent": True})

    def _final(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._finalize(slip_return)
        return slip_return

    def _break_address(self):
        # Typed without the @, the way it reaches contacts through imports.
        self.env.cr.execute("UPDATE res_partner SET email = 'alex.example.com' WHERE id = %s", (self.contractor_a.id,))
        self.contractor_a.invalidate_recordset(["email", "email_formatted"])

    def test_email_refused_for_an_invalid_address_reads_as_not_sent(self):
        slip_return = self._final()
        self._break_address()
        slip = slip_return.slip_ids.sudo()
        # Queued as if the address had been valid when Email slips was clicked.
        slip.write({"send_requested_uid": self.env.uid, "send_to_email": self.contractor_a.email_formatted})
        slip._send_pending()
        mail = slip.mail_id
        self.assertTrue(mail)
        with self.mock_mail_gateway(mail_unlink_sent=True):
            mail.send()
        self.assertFalse(mail.exists(), "Odoo deletes an email it could not address")
        self.assertFalse(slip.sent_date)
        self.assertFalse(slip.email_state)
        self.assertIn("failed", slip.message_ids[0].body)
        self.assertIn("Print the slip for this recipient", slip_return.message_ids[0].body)

    def test_invalid_address_is_listed_for_paper(self):
        slip_return = self._final()
        self._break_address()
        slip_return.action_send_slips()
        self.assertFalse(slip_return.slip_ids.sudo().send_requested_uid)
        message = slip_return.message_ids[0].body
        self.assertIn("have an email address that is not valid: Alex Martin", message)
        self.assertIn("Give the other 1 recipient(s) two paper copies", message)

    def test_accepted_email_reads_as_sent(self):
        slip_return = self._final()
        self._send(slip_return)
        slip = slip_return.slip_ids.sudo()
        with self.mock_mail_gateway(mail_unlink_sent=True):
            slip.mail_id.send()
        self.assertTrue(slip.sent_date)
        self.assertEqual(slip.email_state, "sent")

    def test_failed_email_odoo_keeps_is_purged_after_thirty_days(self):
        slip_return = self._final()
        self._send(slip_return)
        slip = slip_return.slip_ids.sudo()
        mail = slip.mail_id
        attachment = mail.attachment_ids
        self.assertTrue(attachment)
        with self.mock_mail_gateway(mail_unlink_sent=True):
            self.send_email_mocked.side_effect = MailDeliveryException("Connection refused")
            mail.send(raise_exception=False)
        self.assertTrue(mail.exists(), "Odoo keeps an email that failed for a server reason")
        self.assertEqual(mail.state, "exception")
        self.assertEqual(slip.email_state, "exception")
        self.assertIn("failed", slip.message_ids[0].body)
        with freeze_time("2026-12-20 12:00:00"):
            self.env["l10n.ca.slip"]._purge_failed_emails()
        self.assertFalse(mail.exists())
        self.assertFalse(attachment.exists())
        self.assertFalse(slip.email_state)
