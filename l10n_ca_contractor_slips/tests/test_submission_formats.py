# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree

from odoo.tests import tagged

from odoo.addons.l10n_ca_contractor_slips.models.l10n_ca_slip_return import XSD_URLS

from .common import FakeResponse, L10nCaSlipsCommon, PAYER_BN, cra_schema_zip_path


@tagged("post_install", "-at_install")
class TestSubmissionFormats(L10nCaSlipsCommon):

    def _validate_edition(self, record, data, year):
        day = "2026-10-28 12:00:00" if year == "2026" else "2027-01-11 12:00:00"
        with open(cra_schema_zip_path(year), "rb") as handle:
            package = handle.read()
        with freeze_time(day), patch("requests.get", return_value=FakeResponse(package)):
            self.assertEqual(record._l10n_ca_schema_url(), XSD_URLS[year])
            self.assertTrue(record._l10n_ca_load_cra_schemas(force=True))
            record._validate_xml(data)

    def _assert_both_editions(self, record):
        data = self._xml_bytes(record)
        original = (record.state, record.xml_filename, record.total_reported)
        for year in ("2026", "2027"):
            self._validate_edition(record, data, year)
        self.assertEqual(self._xml_bytes(record), data)
        self.assertEqual((record.state, record.xml_filename, record.total_reported), original)
        return etree.fromstring(data)

    def test_current_edition_is_independent_of_tax_year(self):
        for tax_year in (2022, 2025, 2026):
            record = self._return(year=tax_year, compute=False)
            with freeze_time("2026-10-28 12:00:00"):
                self.assertEqual(record._l10n_ca_schema_year(), "2026")
                self.assertEqual(record._l10n_ca_schema_url(), XSD_URLS["2026"])
            with freeze_time("2027-01-11 12:00:00"):
                self.assertEqual(record._l10n_ca_schema_year(), "2027")
                self.assertEqual(record._l10n_ca_schema_url(), XSD_URLS["2027"])

    def test_rollover_uses_eastern_time_and_ignores_caller_timezone(self):
        record = self._return(compute=False).with_context(tz="Pacific/Kiritimati")
        with freeze_time("2027-01-11 04:59:59"):
            self.assertEqual(record._l10n_ca_schema_year(), "2026")
        with freeze_time("2027-01-11 05:00:00"):
            self.assertEqual(record._l10n_ca_schema_year(), "2027")

    def test_maintenance_notice_has_exact_boundaries(self):
        for instant, closed in (
            ("2026-12-22 04:59:59", False), ("2026-12-22 05:00:00", True),
            ("2027-01-11 04:59:59", True), ("2027-01-11 05:00:00", False),
        ):
            with freeze_time(instant):
                record = self._return(compute=False)
                self.assertEqual(bool(record.cra_filing_notice), closed)
                if closed:
                    self.assertIn("11 January 2027", record.cra_filing_notice)

    def test_original_t4a_and_t5018_validate_in_both_official_packages(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(1000.0, self.construction_account, self.gst)]),
                  "2026-03-10")
        for kind, amount in (("t4a", 900.0), ("t5018", 1050.0)):
            record = self._return(kind)
            self._finalize(record)
            root = self._assert_both_editions(record)
            self.assertEqual(record.total_reported, amount)
            self.assertEqual(root.findtext("T619/TransmitterAccountNumber/bn9"), PAYER_BN)

    def test_amended_and_cancelled_files_validate_in_both_packages(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(1000.0, self.construction_account, self.gst)]),
                  "2026-03-10")
        for kind, partner, adjustment in (("t4a", self.contractor_a, "adjustment_base"),
                                           ("t5018", self.sub_corp, "adjustment_incl")):
            original = self._filed(self._return(kind))
            frozen = self._xml_bytes(original)
            amended = self._amend(original)
            amended.amendment_note = "Correct the documented service amount."
            self._slip(amended, partner).write({adjustment: 100, "adjustment_reason": "Reviewed service adjustment"})
            self._filed(amended)
            root = self._assert_both_editions(amended)
            self.assertEqual(root.findtext(".//rpt_tcd"), "A")
            cancelled = self._amend(amended)
            cancelled.amendment_note = "Cancel this recipient's slip."
            self._slip(cancelled, partner).is_cancelled = True
            self._finalize(cancelled)
            root = self._assert_both_editions(cancelled)
            self.assertEqual(root.findtext(".//rpt_tcd"), "C")
            self.assertEqual(self._xml_bytes(original), frozen)

    def test_all_supported_signin_paths_validate_in_both_packages(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        record = self._return()
        self._finalize(record)
        frozen = self._xml_bytes(record)
        for signin, account in (("myba", PAYER_BN), ("wac", f"{PAYER_BN}RP0001"), ("rac", "")):
            self.company.write({"l10n_ca_slip_signin": signin, "l10n_ca_slip_transmitter_account": account,
                                "l10n_ca_slip_transmitter_repid": "R123456" if signin == "rac" else False})
            data = record._build_xml()
            for year in ("2026", "2027"):
                self._validate_edition(record, data, year)
            root = etree.fromstring(data)
            if signin == "rac":
                self.assertEqual(root.findtext("T619/TransmitterRepID/RepID"), "R123456")
                self.assertIsNone(root.find("T619/TransmitterAccountNumber/bn9"))
            else:
                tag = "bn9" if signin == "myba" else "bn15"
                self.assertEqual(root.findtext(f"T619/TransmitterAccountNumber/{tag}"), account)
        self.assertEqual(self._xml_bytes(record), frozen)

    def test_schema_rollover_refreshes_cache_and_preserves_filed_xml(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        record = self._filed(self._return())
        frozen = self._xml_bytes(record)
        for year, instant in (("2027", "2027-01-11 12:00:00"), ("2026", "2026-10-28 12:00:00")):
            with open(cra_schema_zip_path(year), "rb") as handle:
                package = handle.read()
            with freeze_time(instant), patch("requests.get", return_value=FakeResponse(package)) as request:
                self.assertFalse(record._l10n_ca_schemas_current())
                record._validate_xml(frozen)
                self.assertTrue(request.called)
                self.assertTrue(record._l10n_ca_schemas_current())
            self.assertEqual(record.state, "filed")
            self.assertEqual(self._xml_bytes(record), frozen)

    def test_internal_schema_mirror_override_is_preserved(self):
        parameter = self.env["ir.config_parameter"].sudo()
        parameter.set_str("l10n_ca_contractor_slips.cra_schema_url", "https://schemas.example.com/current.zip")
        record = self._return(compute=False)
        for instant in ("2026-10-28 12:00:00", "2027-01-11 12:00:00"):
            with freeze_time(instant):
                self.assertEqual(record._l10n_ca_schema_url(), "https://schemas.example.com/current.zip")
