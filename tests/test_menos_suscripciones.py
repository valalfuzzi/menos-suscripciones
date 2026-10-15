import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from menos_suscripciones.detect import detect, merchant_key, monthly_totals
from menos_suscripciones.loaders import Charge, load_csv, load_json, load_mercury, parse_amount, parse_date
from menos_suscripciones.report import build_rows, render, summary

ROOT = Path(__file__).resolve().parent.parent


def write(text: str, suffix=".csv") -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return Path(f.name)


def monthly(desc, amount, months, day=5, year=2026):
    return [Charge(date(year, m, day), desc, amount) for m in months]


class ParseTests(unittest.TestCase):
    def test_amount_formats(self):
        self.assertEqual(parse_amount("$1,234.56"), 1234.56)
        self.assertEqual(parse_amount("-12.00"), -12.0)
        self.assertEqual(parse_amount("(12.00)"), -12.0)
        self.assertEqual(parse_amount("1.234,56 €"), 1234.56)
        self.assertEqual(parse_amount("12,50"), 12.5)
        self.assertEqual(parse_amount("1,234"), 1234.0)
        self.assertIsNone(parse_amount(""))

    def test_dates(self):
        self.assertEqual(parse_date("2026-09-02T02:31:28Z"), date(2026, 9, 2))
        self.assertEqual(parse_date("09/02/2026"), date(2026, 9, 2))
        self.assertEqual(parse_date("02/09/2026", dayfirst=True), date(2026, 9, 2))


class LoaderTests(unittest.TestCase):
    def test_csv_with_debit_and_credit_columns_semicolon_dayfirst(self):
        p = write("Fecha;Concepto;Cargo;Abono\n25/08/2026;NETFLIX;15,99;\n26/08/2026;Cliente;;100,00\n")
        charges, warnings = load_csv(p)
        self.assertEqual(charges, [Charge(date(2026, 8, 25), "NETFLIX", -15.99),
                                   Charge(date(2026, 8, 26), "Cliente", 100.0)])
        self.assertEqual(warnings, [])

    def test_csv_positive_charges_are_flipped_with_warning(self):
        p = write("Date,Description,Amount\n2026-08-01,Zoom,22.81\n2026-09-01,Zoom,22.81\n")
        charges, warnings = load_csv(p)
        self.assertTrue(all(c.amount < 0 for c in charges))
        self.assertEqual(len(warnings), 1)

    def test_csv_skips_failed_rows(self):
        p = write("Date,Description,Amount,Status\n2026-08-01,Zoom,-22.81,Failed\n2026-09-01,Zoom,-22.81,Sent\n")
        charges, _ = load_csv(p)
        self.assertEqual(len(charges), 1)

    def test_csv_without_needed_columns_explains(self):
        with self.assertRaises(ValueError) as ctx:
            load_csv(write("foo,bar\n1,2\n"))
        self.assertIn("foo", str(ctx.exception))

    def test_json_mercury_shape_drops_internal_transfers(self):
        p = write(json.dumps({"transactions": [
            {"counterpartyName": "Slack", "amount": -71.7, "postedAt": "2026-09-02T02:31:28Z", "kind": "creditCardTransaction", "status": "sent"},
            {"counterpartyName": "Mercury Savings", "amount": 231.19, "date": "2026-09-03T00:08:20Z", "kind": "internalTransfer", "status": "sent"},
        ]}), suffix=".json")
        self.assertEqual(load_json(p), [Charge(date(2026, 9, 2), "Slack", -71.7)])

    def test_mercury_paginates(self):
        pages = [
            {"transactions": [{"id": str(i), "counterpartyName": "X", "amount": -1, "postedAt": "2026-09-01"} for i in range(1000)]},
            {"transactions": [{"id": "last", "counterpartyName": "X", "amount": -1, "postedAt": "2026-09-02"}]},
        ]
        seen = []

        class Resp:
            def __init__(self, body): self.body = body
            def read(self): return json.dumps(self.body).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout):
            seen.append(req.full_url)
            return Resp(pages[len(seen) - 1])

        out = load_mercury("secret-token:x", date(2026, 9, 1), date(2026, 9, 30), opener=opener)
        self.assertEqual(len(out), 1001)
        self.assertIn("start_after=999", seen[1])


class DetectTests(unittest.TestCase):
    def test_merchant_key(self):
        self.assertEqual(merchant_key("PADDLE.NET* CAPCUT"), "capcut")
        self.assertEqual(merchant_key("GOOGLE *WORKSPACE"), "google workspace")
        self.assertEqual(merchant_key("SLACK T0123ABC"), "slack")
        self.assertEqual(merchant_key("ZOOM.US 888-799-9666"), "zoom")

    def test_monthly_with_refund_and_two_charges_a_month(self):
        charges = monthly("ANTHROPIC* CLAUDE", -100, [6, 7, 8]) + [
            Charge(date(2026, 7, 9), "ANTHROPIC* CLAUDE", -143.39),
            Charge(date(2026, 7, 10), "ANTHROPIC* CLAUDE", 143.39),
            Charge(date(2026, 8, 20), "ANTHROPIC* CLAUDE", -20),
        ]
        r = detect(charges)["recurring"][0]
        self.assertEqual(r["cadence"], "mensual")
        self.assertEqual(r["by_month"], {"2026-06": 100, "2026-07": 100, "2026-08": 120})
        self.assertEqual(r["monthly_cost"], 120)
        self.assertEqual(r["refunds"], 143.39)

    def test_stopped_subscription(self):
        charges = monthly("LOVABLE", -90, [5, 6]) + [Charge(date(2026, 9, 30), "Otra", -1)]
        r = next(x for x in detect(charges)["recurring"] if x["key"] == "lovable")
        self.assertEqual(r["status"], "parada")
        self.assertIsNone(r["next_expected"])

    def test_annual_and_one_off(self):
        charges = [Charge(date(2025, 4, 12), "NAMECHEAP", -24), Charge(date(2026, 4, 12), "NAMECHEAP", -24),
                   Charge(date(2026, 6, 1), "APPSUMO", -226)]
        res = detect(charges)
        self.assertEqual(res["recurring"][0]["cadence"], "anual")
        self.assertEqual(res["recurring"][0]["monthly_cost"], 2.0)
        self.assertEqual(res["one_offs"][0]["key"], "appsumo")

    def test_income_is_not_a_subscription(self):
        charges = monthly("Cliente Acme", 500, [2, 3, 4])
        self.assertEqual(detect(charges)["recurring"], [])

    def test_monthly_totals_only_chosen_keys(self):
        res = detect(monthly("Slack", -70, [7, 8]) + monthly("Super", -50, [7, 8]))
        self.assertEqual(monthly_totals(res["recurring"], {"slack"}), {"2026-07": 70, "2026-08": 70})


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.scan = detect(monthly("Slack", -70, [7, 8, 9]) + monthly("TANGO", -26, [7, 8, 9])
                           + monthly("LOVABLE", -90, [5, 6]))
        self.catalog = json.loads((ROOT / "menos_suscripciones" / "alternatives.json").read_text(encoding="utf-8"))

    def diag(self, **extra):
        d = {"subscriptions": [
            {"keys": ["slack"], "name": "Slack", "verdict": "mantener", "why": "<b>bots</b>"},
            {"keys": ["tango"], "name": "Tango", "verdict": "reemplazar", "why": "x", "alternatives": ["Mimik"]},
            {"keys": ["lovable"], "name": "Lovable", "verdict": "revisar", "why": "y"},
        ]}
        d.update(extra)
        return d

    def test_totals_come_from_scan(self):
        rows = build_rows(self.diag(), self.scan)
        self.assertEqual(summary(rows), {"total": 96, "cut": 26, "year": 312, "cut_names": ["Tango"]})
        self.assertTrue(next(r for r in rows if r["name"] == "Lovable")["stopped"])

    def test_unknown_key_is_an_error(self):
        bad = {"subscriptions": [{"keys": ["netflix"], "name": "Netflix", "verdict": "mantener"}]}
        with self.assertRaises(ValueError):
            build_rows(bad, self.scan)

    def test_unknown_verdict_is_an_error(self):
        bad = {"subscriptions": [{"keys": ["slack"], "name": "Slack", "verdict": "quizás"}]}
        with self.assertRaises(ValueError):
            build_rows(bad, self.scan)

    def test_render_escapes_and_links_catalog(self):
        html = render(self.diag(), self.scan, self.catalog)
        self.assertNotIn("<b>bots</b>", html)
        self.assertIn("&lt;b&gt;bots&lt;/b&gt;", html)
        self.assertIn('href="https://westpoint.io', html)
        self.assertIn('"saving": 26', html)

    def test_example_renders(self):
        scan = detect(load_csv(ROOT / "examples" / "tarjeta-ejemplo.csv")[0])
        diag = json.loads((ROOT / "examples" / "diagnostico-ejemplo.json").read_text(encoding="utf-8"))
        html = render(diag, scan, self.catalog)
        self.assertIn("$56.18", html)
        self.assertIn("$674", html)


if __name__ == "__main__":
    unittest.main()
