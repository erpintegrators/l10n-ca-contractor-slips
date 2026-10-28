# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, SUPERUSER_ID
from odoo.addons.l10n_ca_contractor_slips import _correct_email_cancel_notice


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["ir.attachment"]._l10n_ca_secure_existing_files()
    _correct_email_cancel_notice(env)
