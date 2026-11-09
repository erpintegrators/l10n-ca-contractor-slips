# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _postprocess_sent_message(self, success_pids, success_emails, failure_reason=False, failure_type=None):
        """Record slip delivery failures before Odoo deletes failed messages."""
        if failure_type:
            for slip in self.env["l10n.ca.slip"].sudo().search([("mail_id", "in", self.ids)]):
                slip._email_failed(failure_reason or failure_type)
        return super()._postprocess_sent_message(
            success_pids, success_emails, failure_reason=failure_reason, failure_type=failure_type
        )

    def unlink(self):
        """Clear delivery status when an unsent slip email is deleted."""
        unsent = self.filtered(lambda mail: mail.state != "sent")
        if unsent:
            self.env["l10n.ca.slip"].sudo().search([
                ("mail_id", "in", unsent.ids), ("sent_date", "!=", False),
            ]).write({"sent_date": False})
        return super().unlink()
