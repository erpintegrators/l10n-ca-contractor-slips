# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from collections import defaultdict

from odoo import api, fields, models

VENDOR_DOCUMENT_TYPES = ("in_invoice", "in_refund", "in_receipt")
MONEY_JOURNAL_TYPES = ("bank", "cash", "credit")
TAG_XMLIDS = {
    "t4a": "l10n_ca_contractor_slips.account_tag_t4a_fees",
    "t5018": "l10n_ca_contractor_slips.account_tag_t5018_construction",
}


class L10nCaSlipEngine(models.AbstractModel):
    """Turns posted vendor bills and the cash paid against them into slip amounts.

    Amounts follow the cash basis: a payment counts in the period of its own date, whatever
    the bill date. Each payment is split between eligible and ineligible lines in the same
    proportion as the bill, so a bill that is half goods reports half of every payment.
    """

    _name = "l10n.ca.slip.engine"
    _description = "Canadian contractor slip engine"

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------

    @api.model
    def _get_slip_tag(self, slip_type):
        return self.env.ref(TAG_XMLIDS[slip_type])

    @api.model
    def _is_eligible_line(self, line, tag, slip_type="t4a"):
        """A bill line is reportable when it is not goods and its account carries the slip tag.
        For T4A a service product also qualifies. T5018 needs the tag, since a service product
        can be freight or bare equipment rental. A holdback account carrying the T5018 tag makes
        holdbacks count when they are paid."""
        product = line.product_id
        if product and product.type == "consu":
            return False
        if tag in line.account_id.tag_ids:
            return True
        return slip_type == "t4a" and bool(product) and product.type == "service"

    @api.model
    def _document_amounts(self, move, tag, include_mixed_goods, slip_type="t4a"):
        """(eligible before tax, eligible with tax, untaxed total, total) in document currency."""
        product_lines = move.invoice_line_ids.filtered(lambda line: line.display_type == "product")
        eligible = product_lines.filtered(lambda line: self._is_eligible_line(line, tag, slip_type))
        if include_mixed_goods and eligible:
            eligible = product_lines
        return (
            sum(eligible.mapped("price_subtotal")),
            sum(eligible.mapped("price_total")),
            move.amount_untaxed,
            move.amount_total,
        )

    @api.model
    def _bill_ratios(self, move, tag, include_mixed_goods=False, slip_type="t4a"):
        """Share of each settlement of the document that is reportable, before and including tax."""
        base, incl, untaxed, total = self._document_amounts(move, tag, include_mixed_goods, slip_type)
        if (not base and not incl) or move.currency_id.compare_amounts(total, 0.0) <= 0:
            return 0.0, 0.0
        # Never more than the whole settlement, and never more of it than its untaxed part before
        # tax: a holdback or other negative ineligible line lowers the total.
        ratio_base = max(min(base / total, untaxed / total, 1.0), 0.0)
        ratio_incl = max(min(incl / total, 1.0), 0.0)
        return ratio_base, ratio_incl

    # ------------------------------------------------------------------
    # Cash collection
    # ------------------------------------------------------------------

    @api.model
    def _holds_goods(self, move):
        return any(
            line.display_type == "product" and line.product_id.type == "consu" for line in move.invoice_line_ids
        )

    @api.model
    def _effective_slip_type(self, move):
        """Slip settings live on the main company, whose return covers every branch."""
        vendor = move.commercial_partner_id.with_company(move.company_id.root_id)
        return move.l10n_ca_slip_type or vendor.l10n_ca_slip_type

    @api.model
    def _split_settlement(self, move):
        """(liquidity, settled, other) lines of a payment or bank entry. Settled lines are the
        payable and receivable lines it clears; other lines are write-offs and extra charges."""
        cache = self.env.context.get("l10n_ca_split_cache")
        if cache is not None and move.id in cache:
            return cache[move.id]
        result = self._split_settlement_uncached(move)
        if cache is not None:
            cache[move.id] = result
        return result

    @api.model
    def _split_settlement_uncached(self, move):
        if move.origin_payment_id:
            liquidity, _counterpart, _writeoff = move.origin_payment_id._seek_for_lines()
        elif move.statement_line_id:
            liquidity, _suspense, _other = move.statement_line_id._seek_for_lines()
        else:
            journal = move.journal_id
            money_accounts = journal.default_account_id | (
                journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids
            ).payment_account_id
            liquidity = move.line_ids.filtered(
                lambda l_: l_.account_id in money_accounts
                or l_.account_type in ("asset_cash", "liability_credit_card")
            )
        settled = move.line_ids.filtered(lambda l_: l_.account_type in ("liability_payable", "asset_receivable"))
        return liquidity, settled, move.line_ids - liquidity - settled

    @api.model
    def _money_sign(self, move):
        """+1 when money comes in, -1 when it goes out. An entry with no money line (a write-off
        journal entry, say) is read from the side of the documents it clears."""
        liquidity, settled, _other = self._split_settlement(move)
        if liquidity:
            return 1 if sum(liquidity.mapped("balance")) >= 0 else -1
        return -1 if sum(settled.mapped("balance")) >= 0 else 1

    @api.model
    def _discount_lines(self, move):
        """Lines that reduce what the entry pays, such as an early payment discount: written off
        on the same side as the money. Lines on the other side are extra charges paid in the
        same transfer."""
        _liquidity, _settled, other = self._split_settlement(move)
        sign = self._money_sign(move)
        # Exchange differences booked inside the payment are not a discount.
        company = move.company_id
        exchange = company.income_currency_exchange_account_id | company.expense_currency_exchange_account_id
        return other.filtered(lambda l_: l_.balance * sign > 0 and l_.account_id not in exchange)

    @api.model
    def _early_payment_discounts(self, move, paid_side):
        """{bill payment-term line id: discount} for the bills the entry pays inside their early
        payment discount window. Odoo writes one discount line for the whole batch, so each bill's
        own share is read from its payment terms."""
        discounts = {}
        for counterpart in paid_side:
            for partial in counterpart.matched_debit_ids | counterpart.matched_credit_ids:
                bill_line = (partial.debit_move_id | partial.credit_move_id) - counterpart
                if not (
                    bill_line.display_type == "payment_term"
                    and bill_line.discount_date
                    and move.date <= bill_line.discount_date
                    and bill_line.discount_balance
                ):
                    continue
                # The discount is a share of the bill in its own currency, converted at this payment's
                # rate like the rest of the payment.
                in_currency = abs(bill_line.amount_currency) - abs(bill_line.discount_amount_currency)
                if counterpart.currency_id == bill_line.currency_id and counterpart.amount_currency:
                    rate = abs(counterpart.balance) / abs(counterpart.amount_currency)
                    discounts[bill_line.id] = in_currency * rate
                else:
                    discounts[bill_line.id] = abs(bill_line.balance) - abs(bill_line.discount_balance)
        return discounts

    @api.model
    def _net_of_discounts(self, move, counterpart, bill_line, cash):
        """What the entry pays in money for ``cash`` of the document cleared through ``counterpart``.

        Discounts reduce what is paid on the documents being paid (the side opposite the money): each
        bill first takes its own early payment discount, and whatever discount is left, such as a
        manual write-off, is spread over the paid documents. Documents cleared on the money's own
        side, such as a credit note netted in the same transfer, are settled in full."""
        _liquidity, settled, _other = self._split_settlement(move)
        sign = self._money_sign(move)
        paid_side = settled.filtered(lambda l_: l_.balance * sign < 0)
        if counterpart not in paid_side:
            return cash
        currency = move.company_currency_id
        paid_total = abs(sum(paid_side.mapped("balance")))
        discount = abs(sum(self._discount_lines(move).mapped("balance")))
        if currency.is_zero(paid_total) or currency.is_zero(discount):
            return cash
        own = self._early_payment_discounts(move, paid_side)
        leftover = max(discount - sum(own.values()), 0.0)
        # An early payment discount is taken only by the payment that settles the bill, so the bill
        # carries all of it, whatever a credit note settled before.
        own_share = min(own.get(bill_line.id, 0.0), cash)
        return max(cash - own_share - leftover * cash / paid_total, 0.0)

    @api.model
    def _exchange_cash(self, partial, counterpart, bill_line):
        """A payment in company currency against a bill in another currency settles the bill's
        booked amount through ``partial`` and the rest through the exchange difference entry. Both
        parts are money the vendor received."""
        exchange = partial.exchange_move_id
        company_currency = bill_line.company_currency_id
        if not exchange or counterpart.currency_id != company_currency or bill_line.currency_id == company_currency:
            return 0.0
        return sum(
            other.amount
            for other in counterpart.matched_debit_ids | counterpart.matched_credit_ids
            if (other.debit_move_id | other.credit_move_id) & exchange.line_ids
        )

    @api.model
    def _moveless_payments(self, bill):
        return bill.matched_payment_ids.filtered(lambda p: not p.move_id and p.state in ("in_process", "paid"))

    @api.model
    def _cash_from_partials(self, bill, date_from, date_to, slip_type, include_mixed_goods=False):
        """Cash paid or refunded against the bill through reconciliation, in company currency
        at the payment's own rate.

        When the bill also carries payments recorded without a journal entry, the bank lines
        later reconciled with it are the same money; those payments are counted at their own
        date instead, and bank lines up to their total are skipped here."""
        sign = -1 if bill.move_type == "in_refund" else 1
        # Credit notes count on the day they were matched, read in the company's time zone so every
        # user gets the same date.
        tz = bill.company_id.partner_id.tz or "UTC"
        refund_source = self._refund_ratio_source(bill, slip_type, include_mixed_goods)
        moveless_left = sum(abs(p.amount_company_currency_signed) for p in self._moveless_payments(bill))
        rows = []
        for line in bill.line_ids.filtered(lambda l_: l_.display_type == "payment_term"):
            for partial in line.matched_debit_ids | line.matched_credit_ids:
                if partial.debit_move_id == line:
                    counterpart, counterpart_amount_currency = partial.credit_move_id, partial.credit_amount_currency
                else:
                    counterpart, counterpart_amount_currency = partial.debit_move_id, partial.debit_amount_currency
                other_move = counterpart.move_id
                if other_move.exchange_diff_partial_ids:
                    continue
                if counterpart.parent_state != "posted":
                    # Odoo can keep the matching when an entry goes back to draft.
                    continue
                if other_move.is_invoice(include_receipts=True):
                    # A credit note applied to a bill settles both, each at its own mix: the bill
                    # counts as paid, the credit note as refunded. No money moves, so the net is
                    # only the difference in mix, on the date the two were matched. A document
                    # reported on another slip type is left to that slip.
                    if self._effective_slip_type(other_move) != slip_type:
                        continue
                    matched_on = fields.Date.context_today(partial.with_context(tz=tz), partial.create_date)
                    rows.append((matched_on, other_move, partial.amount, "credit_note", False))
                    continue
                if counterpart.currency_id.is_zero(counterpart.amount_currency):
                    cash = partial.amount
                else:
                    cash = abs(counterpart.balance) * abs(counterpart_amount_currency) / abs(counterpart.amount_currency)
                cash += self._exchange_cash(partial, counterpart, line)
                cash = self._net_of_discounts(other_move, counterpart, line, cash)
                rows.append((counterpart.date, other_move, cash, "reconciled", counterpart.payment_id.id))

        result = []
        for row_date, other_move, cash, source, payment_id in sorted(rows, key=lambda r: (r[0], r[1].id)):
            if other_move.statement_line_id and moveless_left > 0:
                covered = min(cash, moveless_left)
                moveless_left -= covered
                cash -= covered
                if bill.company_currency_id.is_zero(cash):
                    continue
            if not (date_from <= row_date <= date_to):
                continue
            result.append({
                "date": row_date,
                "cash": sign * cash,
                "payment_move_id": other_move.id,
                "payment_id": payment_id,
                "source": source,
                # When whole mixed bills are reported, a credit note takes the share of the bill it
                # was matched to: the bill counts the credit as paid, so the credit must cancel it.
                # Refunded in cash, it takes the share of the bill it reverses. Only a bill that holds
                # goods is reported whole; on a services-only bill the credit note keeps its own mix.
                "ratio_from": (
                    other_move if (
                        source == "credit_note" and include_mixed_goods and bill.move_type == "in_refund"
                        and self._holds_goods(other_move)
                    ) else False
                ) if source == "credit_note" else refund_source,
            })
        return result

    @api.model
    def _refund_ratio_source(self, bill, slip_type, include_mixed_goods):
        """Under whole-bill reporting, the bill a cash-refunded credit note reverses, when that bill
        holds goods and is reported on the same slip."""
        original = bill.reversed_entry_id
        if not (include_mixed_goods and bill.move_type == "in_refund" and original):
            return False
        if self._effective_slip_type(original) != slip_type or not self._holds_goods(original):
            return False
        return original

    @api.model
    def _cash_from_moveless_payments(self, bill, date_from, date_to):
        """Payments recorded without a journal entry (bank journals with no outstanding account,
        available with the accountant app). They count at their own date, once."""
        result = []
        for payment in self._moveless_payments(bill).filtered(lambda p: date_from <= p.date <= date_to):
            docs = payment.invoice_ids.filtered(lambda m: m.state == "posted" and m.move_type in VENDOR_DOCUMENT_TYPES)
            doc_total = sum(abs(d.amount_total_signed) for d in docs) or 1.0
            share = abs(bill.amount_total_signed) / doc_total
            sign = 1 if payment.payment_type == "outbound" else -1
            result.append({
                "date": payment.date,
                "cash": sign * abs(payment.amount_company_currency_signed) * share,
                "payment_move_id": False,
                "payment_id": payment.id,
                "source": "payment",
            })
        return result

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    @api.model
    def _compute_partner_amounts(self, company, slip_type, date_from, date_to, partners=None):
        """Return {commercial partner id: {"base", "incl", "svc_base", "svc_incl", "lines",
        "warnings"}} for the period.

        "base" and "incl" are the reported amounts before and including GST/HST and PST: T4A box
        048 is "base", T5018 box 22 is "incl". "svc_base" and "svc_incl" count the services lines
        only and drive the T5018 threshold, whatever the mixed-bill setting. Bills from the company
        and its branches all count; the caller selects those companies (l10n.ca.slip.return._scoped).
        """
        # The return has already checked that the user may see every active branch. The engine reads
        # with elevated rights so archived branches, which no user can select any more, still count.
        self = self.sudo().with_context(l10n_ca_split_cache={})  # noqa: PLW0642
        companies = self.env["res.company"].with_context(active_test=False).search([("id", "child_of", company.id)])
        company = company.sudo()
        tag = self._get_slip_tag(slip_type)
        include_mixed_goods = slip_type == "t5018" and company.l10n_ca_t5018_include_mixed_goods
        if partners is None:
            partners = self.env["res.partner"].with_company(company).with_context(active_test=False).search(
                [("l10n_ca_slip_type", "=", slip_type), ("parent_id", "=", False)]
            )
        result = defaultdict(
            lambda: {"base": 0.0, "incl": 0.0, "svc_base": 0.0, "svc_incl": 0.0, "lines": [], "warnings": []}
        )

        # Bills keep the slip type they were posted with; bills without one follow the vendor.
        # Any bill with money settled against it from the start of the period on counts, whatever
        # its own date or payment status: a prepayment can be matched to a later bill, and a
        # blocked bill can be partly paid. Older settlements cannot reach this period.
        bills = self.env["account.move"].search([
            ("company_id", "in", companies.ids),
            ("state", "=", "posted"),
            ("move_type", "in", VENDOR_DOCUMENT_TYPES),
            "|",
            ("l10n_ca_slip_type", "=", slip_type),
            "&", ("l10n_ca_slip_type", "=", False), ("commercial_partner_id", "in", partners.ids),
            "|", "|", "|", "|",
            ("line_ids.matched_debit_ids.max_date", ">=", date_from),
            ("line_ids.matched_credit_ids.max_date", ">=", date_from),
            ("line_ids.matched_debit_ids.create_date", ">=", date_from),
            ("line_ids.matched_credit_ids.create_date", ">=", date_from),
            ("matched_payment_ids.date", ">=", date_from),
        ])
        ratios = {}

        def ratios_for(move):
            if move.id not in ratios:
                reported = self._bill_ratios(move, tag, include_mixed_goods, slip_type)
                services = self._bill_ratios(move, tag, False, slip_type) if include_mixed_goods else reported
                ratios[move.id] = (reported, services)
            return ratios[move.id]

        for bill in bills:
            (r_base, r_incl), (s_base, s_incl) = ratios_for(bill)
            whole_bill_credit = include_mixed_goods and bill.move_type == "in_refund"
            if not (r_base or r_incl or s_base or s_incl or whole_bill_credit):
                if self._nothing_could_count(bill, tag, slip_type) and self._settled_in(bill, date_from, date_to):
                    result[bill.commercial_partner_id.id]["warnings"].append(self.env._(
                        "%(bill)s was paid in the period, but none of its lines is on an account tagged for %(slip)s"
                        " or holds a product, so it is left out. If it paid for services, tag the account and "
                        "recalculate.",
                        bill=bill.name, slip=slip_type.upper(),
                    ))
                continue
            cash_rows = self._cash_from_partials(bill, date_from, date_to, slip_type, include_mixed_goods)
            cash_rows += self._cash_from_moveless_payments(bill, date_from, date_to)
            data = result[bill.commercial_partner_id.id]
            refunded = [row for row in cash_rows if row["source"] != "credit_note" and not row.get("ratio_from")]
            if whole_bill_credit and refunded and not (r_base or r_incl):
                data["warnings"].append(self.env._(
                    "%(credit)s was refunded in cash and holds only goods, but is not linked to the bill it "
                    "corrects, so box 22 is not reduced. Adjust the slip if that bill was reported in full.",
                    credit=bill.name,
                ))
            for row in cash_rows:
                row_base, row_incl = r_base, r_incl
                if row.get("ratio_from"):
                    # A goods-only bill has no reportable share; the credit note then keeps its own.
                    (bill_base, bill_incl), _services = ratios_for(row["ratio_from"])
                    if bill_base or bill_incl:
                        row_base, row_incl = bill_base, bill_incl
                base, incl = row["cash"] * row_base, row["cash"] * row_incl
                data["base"] += base
                data["incl"] += incl
                data["svc_base"] += row["cash"] * s_base
                data["svc_incl"] += row["cash"] * s_incl
                if not (base or incl):
                    continue
                data["lines"].append({**row, "move_id": bill.id, "amount_base": base, "amount_incl": incl})

        self._add_holdback_warnings(companies, tag, bills, partners, date_from, date_to, result)
        if partners:
            self._add_direct_bank_expenses(companies, tag, partners, date_from, date_to, result)
            self._add_unallocated_payment_warnings(company, companies, partners, date_from, date_to, result)

        currency = company.currency_id
        for data in result.values():
            for key in ("base", "incl", "svc_base", "svc_incl"):
                data[key] = currency.round(data[key])
        return dict(result)

    @api.model
    def _add_direct_bank_expenses(self, companies, tag, partners, date_from, date_to, result):
        """Bank or cash entries booked straight to a tagged expense account with no bill.
        Write-offs on payments and on bank lines that settle a bill are part of that settlement,
        so they stay out."""
        lines = self.env["account.move.line"].search([
            ("company_id", "in", companies.ids),
            ("parent_state", "=", "posted"),
            ("move_id.move_type", "=", "entry"),
            ("journal_id.type", "in", MONEY_JOURNAL_TYPES),
            ("partner_id.commercial_partner_id", "in", partners.ids),
            ("account_id.tag_ids", "in", tag.ids),
            ("tax_line_id", "=", False),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ])
        settling = lines.move_id.filtered(
            lambda m: m.origin_payment_id
            or any(l_.account_type in ("liability_payable", "asset_receivable") for l_ in m.line_ids)
        )
        # On a payment or bank entry that settles documents, a discount or write-off is already
        # reflected in the settlement ratio; only extra charges paid in the same transfer count.
        discounts = self.env["account.move.line"].concat(*(self._discount_lines(move) for move in settling))
        for line in lines - discounts:
            base = line.balance
            incl = base
            if line.tax_ids:
                taxes = line.tax_ids.compute_all(
                    abs(base), currency=line.company_currency_id, partner=line.partner_id, handle_price_include=False
                )
                incl = taxes["total_included"] * (1 if base >= 0 else -1)
            data = result[line.partner_id.commercial_partner_id.id]
            data["base"] += base
            data["incl"] += incl
            data["svc_base"] += base
            data["svc_incl"] += incl
            data["lines"].append({
                "date": line.date,
                "cash": incl,
                "payment_move_id": line.move_id.id,
                "payment_id": False,
                "source": "bank",
                "move_id": False,
                "amount_base": base,
                "amount_incl": incl,
            })

    @api.model
    def _add_holdback_warnings(self, companies, tag, bills, partners, date_from, date_to, result):
        """A negative line on an untagged account, or a payment booked to an untagged liability
        account, is usually a holdback that will never reach the slip. Flag both."""
        label = "T4A" if tag == self.env.ref(TAG_XMLIDS["t4a"]) else "T5018"
        settled = bills.filtered(
            lambda m: m.move_type in ("in_invoice", "in_receipt") and self._settled_in(m, date_from, date_to)
        )
        for bill in settled:
            untagged = bill.invoice_line_ids.filtered(
                lambda l_: l_.display_type == "product" and tag not in l_.account_id.tag_ids
            )
            released = untagged.filtered(
                lambda l_: l_.price_subtotal > 0
                and l_.account_id.account_type in ("liability_current", "liability_non_current")
            )
            for line in released:
                result[bill.commercial_partner_id.id]["warnings"].append(self.env._(
                    "%(bill)s bills %(amount)s to %(account)s, which is not tagged for %(slip)s. If it releases a "
                    "holdback, tag that account so it counts.",
                    bill=bill.name, amount=bill.currency_id.format(line.price_subtotal), account=line.account_id.display_name,
                    slip=label,
                ))
            held = untagged.filtered(
                lambda l_: l_.price_subtotal < 0
                and l_.account_id.account_type in ("liability_current", "liability_non_current")
            )
            for line in held:
                result[bill.commercial_partner_id.id]["warnings"].append(self.env._(
                    "%(bill)s holds back %(amount)s on %(account)s, which is not tagged for %(slip)s. Tag the "
                    "holdback account so the release counts when it is paid.",
                    bill=bill.name, amount=bill.currency_id.format(-line.price_subtotal), account=line.account_id.display_name,
                    slip=label,
                ))
        releases = self.env["account.move.line"].search([
            ("company_id", "in", companies.ids),
            ("parent_state", "=", "posted"),
            ("journal_id.type", "in", MONEY_JOURNAL_TYPES),
            ("partner_id.commercial_partner_id", "in", partners.ids),
            ("account_id.account_type", "in", ("liability_current", "liability_non_current")),
            ("account_id.tag_ids", "not in", tag.ids),
            ("balance", ">", 0),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ])
        for line in releases:
            result[line.partner_id.commercial_partner_id.id]["warnings"].append(self.env._(
                "%(amount)s paid on %(date)s went to %(account)s, which is not tagged for %(slip)s. If it releases "
                "a holdback, tag that account so it counts.",
                amount=line.company_currency_id.format(line.balance), date=line.date, account=line.account_id.display_name,
                slip=label,
            ))

    @api.model
    def _nothing_could_count(self, move, tag, slip_type):
        """A vendor bill whose lines sit on untagged accounts with no product: usually an opening
        bill or an account nobody tagged. Goods, and services products on a T4A, are deliberate."""
        if move.move_type not in ("in_invoice", "in_receipt"):
            return False
        lines = move.invoice_line_ids.filtered(lambda l_: l_.display_type == "product")
        return bool(lines) and not lines.filtered(
            lambda l_: tag in l_.account_id.tag_ids or l_.product_id.type == "consu"
            or (slip_type == "t4a" and l_.product_id.type == "service")
        )

    @api.model
    def _settled_in(self, move, date_from, date_to):
        """Whether money was matched to the document within the period."""
        partials = move.line_ids.matched_debit_ids | move.line_ids.matched_credit_ids
        dates = partials.mapped("max_date") + move.matched_payment_ids.mapped("date")
        return any(date_from <= when <= date_to for when in dates if when)

    @api.model
    def _add_unallocated_payment_warnings(self, company, companies, partners, date_from, date_to, result):
        """Vendor payments in the period that are not matched to any bill cannot be split
        between services and goods, so they are left out and flagged for review. So is money
        matched to a journal entry's payable line, such as an opening balance or a holdback
        released by journal entry: the entry does not say what the money paid for."""
        lines = self.env["account.move.line"].search([
            ("company_id", "in", companies.ids),
            ("parent_state", "=", "posted"),
            ("move_id.move_type", "=", "entry"),
            ("account_id.account_type", "=", "liability_payable"),
            ("partner_id.commercial_partner_id", "in", partners.ids),
            ("balance", ">", 0),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ])
        partials = lines.matched_debit_ids | lines.matched_credit_ids
        exchange_moves = self.env["account.partial.reconcile"].search([
            ("exchange_move_id", "in", (partials.debit_move_id | partials.credit_move_id).move_id.ids),
        ]).exchange_move_id
        unmatched = defaultdict(float)
        to_entries = defaultdict(float)
        entry_names = defaultdict(set)
        for line in lines:
            partner_id = line.partner_id.commercial_partner_id.id
            unmatched[partner_id] += line.amount_residual
            for partial in line.matched_debit_ids | line.matched_credit_ids:
                counterpart = (partial.debit_move_id | partial.credit_move_id) - line
                move = counterpart.move_id
                if counterpart.parent_state != "posted":
                    # Odoo can keep the matching when a bill goes back to draft; money matched only
                    # to documents that are no longer posted is as good as unmatched.
                    unmatched[partner_id] += partial.amount
                elif (
                    move.move_type == "entry" and not move.origin_payment_id and not move.statement_line_id
                    and move not in exchange_moves
                ):
                    to_entries[partner_id] += partial.amount
                    entry_names[partner_id].add(move.name)
        payments = self.env["account.payment"].search([
            ("company_id", "in", companies.ids),
            ("move_id", "=", False),
            ("state", "in", ("in_process", "paid")),
            ("payment_type", "=", "outbound"),
            ("partner_id.commercial_partner_id", "in", partners.ids),
            ("invoice_ids", "=", False),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ])
        for payment in payments:
            unmatched[payment.partner_id.commercial_partner_id.id] += abs(payment.amount_company_currency_signed)
        currency = company.currency_id
        for partner_id, amount in unmatched.items():
            if currency.is_zero(amount):
                continue
            result[partner_id]["warnings"].append(
                self.env._(
                    "%(amount)s paid in the period is not matched to a posted bill and is left out. Match it to "
                    "its bills and recalculate.",
                    amount=currency.format(amount),
                )
            )
        for partner_id, amount in to_entries.items():
            if currency.is_zero(amount):
                continue
            result[partner_id]["warnings"].append(
                self.env._(
                    "%(amount)s paid in the period settles journal entries (%(entries)s) and is left out, because a "
                    "journal entry does not say what the money paid for. If it paid for services, record them as a "
                    "bill on a tagged account, or adjust the slip.",
                    amount=currency.format(amount), entries=", ".join(sorted(entry_names[partner_id])),
                )
            )
