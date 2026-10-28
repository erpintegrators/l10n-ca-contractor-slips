# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _postprocess_sent_message(self, success_pids, failure_reason=False, failure_type=None):
        """Odoo deletes an email sent to an invalid or missing address straight away, and keeps
        other failures. The slip and its return say why it failed before that happens; deleting
        the email (see unlink) is what makes the slip read as not emailed."""
        if failure_type:
            for slip in self.env["l10n.ca.slip"].sudo().search([("mail_id", "in", self.ids)]):
                slip._email_failed(failure_reason or failure_type)
        return super()._postprocess_sent_message(
            success_pids, failure_reason=failure_reason, failure_type=failure_type
        )

    def unlink(self):
        """A slip whose email is deleted before it was sent reads as not emailed. Odoo deletes a
        sent email right after sending it, and the slip stays sent."""
        unsent = self.filtered(lambda mail: mail.state != "sent")
        if unsent:
            self.env["l10n.ca.slip"].sudo().search([
                ("mail_id", "in", unsent.ids), ("sent_date", "!=", False),
            ]).write({"sent_date": False})
        return super().unlink()
