# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import Command

from . import controllers
from . import models
from . import wizard


# Underscores are wildcards in LIKE patterns, so they are escaped.
PREFIX_PATTERN = "l10n\\_ca\\_contractor\\_slips.%"


def _correct_email_cancel_notice(env):
    """Correct the shipped notice while preserving other edits and inactive-language copies."""
    import re
    from psycopg2.extras import Json

    template = env.ref("l10n_ca_contractor_slips.mail_template_l10n_ca_slip", raise_if_not_found=False)
    if not template:
        return
    template = template.sudo()
    translations = template._fields["body_html"]._get_stored_translations(template) or {}
    corrected = {}
    for language, body in translations.items():
        if isinstance(body, str):
            body = re.sub(
                r"has been cancelled, and the\s+Canada Revenue Agency has been told\.",
                "has been cancelled.", body,
            )
            body = re.sub(
                r"a été annulé, et\s+l['’]Agence du revenu du Canada en a été informée\.",
                "a été annulé.", body,
            )
        corrected[language] = body
    if corrected != translations:
        # A translated HTML field can retain inactive languages. Preserve all stored values;
        # the ordinary translation editor accepts active languages only.
        env.cr.execute("UPDATE mail_template SET body_html = %s WHERE id = %s", (Json(corrected), template.id))
        template.invalidate_recordset(["body_html"])


def post_init_hook(env):
    env["ir.attachment"]._l10n_ca_secure_existing_files()
    _correct_email_cancel_notice(env)


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
