# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import Command

from . import controllers
from . import models
from . import wizard


# Underscores are wildcards in LIKE patterns, so they are escaped.
PREFIX_PATTERN = "l10n\\_ca\\_contractor\\_slips.%"


def uninstall_hook(env):
    """Remove what the module created outside its own tables: the CRA schemas it downloaded, its
    settings, its tags on accounts, and slip emails still waiting or failed, which hold a PDF with
    the recipient's SIN."""
    env["l10n.ca.slip"].sudo().search([]).mail_id.unlink()
    # Accounts keep their tags on uninstall, which would keep the module's two tags alive.
    tags = env["account.account.tag"].search([("id", "in", [
        env.ref(xmlid).id for xmlid in (
            "l10n_ca_contractor_slips.account_tag_t4a_fees", "l10n_ca_contractor_slips.account_tag_t5018_construction",
        ) if env.ref(xmlid, raise_if_not_found=False)
    ])])
    accounts = env["account.account"].sudo().with_context(active_test=False).search([("tag_ids", "in", tags.ids)])
    accounts.write({"tag_ids": [Command.unlink(tag.id) for tag in tags]})
    env["ir.attachment"].search([("name", "=like", PREFIX_PATTERN)]).unlink()
    env["ir.config_parameter"].search([("key", "=like", PREFIX_PATTERN)]).unlink()
