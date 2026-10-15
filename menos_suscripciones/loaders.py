"""Leer transacciones desde un CSV de cualquier banco, un JSON, o la API de Mercury.

Todo termina en la misma forma: una lista de Charge(date, description, amount),
donde amount es NEGATIVO para un cargo y POSITIVO para un reembolso.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DATE_HEADERS = ("posted date", "transaction date", "date", "fecha", "posted", "created", "fecha operación", "fecha de operación")
DESC_HEADERS = ("counterparty name", "merchant", "description", "descripción", "descripcion", "payee",
                "name", "nombre", "concepto", "comercio", "details", "memo")
AMOUNT_HEADERS = ("amount", "monto", "importe", "valor", "total")
DEBIT_HEADERS = ("debit", "débito", "debito", "cargo", "cargos", "withdrawal", "withdrawals")
CREDIT_HEADERS = ("credit", "crédito", "credito", "abono", "abonos", "deposit", "deposits")
STATUS_HEADERS = ("status", "estado")

# Estados que no movieron plata y tipos que son plata moviéndose entre tus propias cuentas.
SKIP_STATUSES = {"failed", "cancelled", "canceled", "reversed", "blocked", "declined", "fallida", "cancelada"}
SKIP_KINDS = {"internaltransfer"}


@dataclass(frozen=True)
class Charge:
    date: date
    description: str
    amount: float


def parse_amount(raw: str) -> float | None:
    """'$1,234.56' · '-12.00' · '(12.00)' · '1.234,56' · '12,50 €' → float."""
    s = (raw or "").strip()
    if not s:
        return None
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")")) or s.endswith("-")
    s = re.sub(r"[^\d,.]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        # El separador que aparece de último es el decimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # '12,50' es decimal; '1,234' son miles.
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else s.replace(",", "")
    value = float(s)
    return -value if negative else value


_DATE_FORMATS_MDY = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y")
_DATE_FORMATS_DMY = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y")


def parse_date(raw: str, dayfirst: bool = False) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    s = s.split(" ")[0].split("T")[0]
    formats = _DATE_FORMATS_DMY + _DATE_FORMATS_MDY if dayfirst else _DATE_FORMATS_MDY + _DATE_FORMATS_DMY
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    norm = [h.strip().lower() for h in headers]
    for cand in candidates:
        if cand in norm:
            return norm.index(cand)
    for cand in candidates:
        for i, h in enumerate(norm):
            if cand in h:
                return i
    return None


def _guess_dayfirst(values: list[str]) -> bool:
    """Si algún primer número pasa de 12, las fechas vienen día/mes."""
    for v in values:
        m = re.match(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}", v or "")
        if m and int(m.group(1)) > 12:
            return True
    return False


def load_csv(path: str | Path, charges_positive: bool | None = None) -> tuple[list[Charge], list[str]]:
    """Devuelve (cargos, avisos). Detecta columnas, separador y formato de fecha solo."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], ["El CSV está vacío."]
    header, body = rows[0], rows[1:]
    warnings: list[str] = []

    i_date = _find(header, DATE_HEADERS)
    i_desc = _find(header, DESC_HEADERS)
    i_amt = _find(header, AMOUNT_HEADERS)
    i_deb = _find(header, DEBIT_HEADERS)
    i_cred = _find(header, CREDIT_HEADERS)
    i_status = _find(header, STATUS_HEADERS)
    if i_date is None or i_desc is None or (i_amt is None and i_deb is None):
        raise ValueError(
            "No encontré las columnas de fecha, descripción y monto. Encabezados del archivo: "
            + ", ".join(header)
        )

    dayfirst = _guess_dayfirst([r[i_date] for r in body if len(r) > i_date])
    parsed: list[Charge] = []
    for r in body:
        if len(r) <= max(i for i in (i_date, i_desc, i_amt, i_deb) if i is not None):
            continue
        if i_status is not None and len(r) > i_status and r[i_status].strip().lower() in SKIP_STATUSES:
            continue
        d = parse_date(r[i_date], dayfirst)
        if d is None:
            continue
        if i_amt is not None and r[i_amt].strip():
            amt = parse_amount(r[i_amt])
        else:
            deb = parse_amount(r[i_deb]) if i_deb is not None and len(r) > i_deb else None
            cred = parse_amount(r[i_cred]) if i_cred is not None and len(r) > i_cred else None
            amt = -abs(deb) if deb else (abs(cred) if cred else None)
        if amt is None:
            continue
        parsed.append(Charge(d, r[i_desc].strip(), amt))

    # Algunas tarjetas exportan los cargos en positivo. Si casi todo es positivo, se invierte.
    if i_amt is not None and parsed:
        if charges_positive is None:
            share_pos = sum(1 for c in parsed if c.amount > 0) / len(parsed)
            charges_positive = share_pos > 0.8
            if charges_positive:
                warnings.append("Casi todos los montos vienen en positivo: los traté como cargos. "
                                "Si es al revés, corre con --charges-negative.")
        if charges_positive:
            parsed = [Charge(c.date, c.description, -c.amount) for c in parsed]
    return parsed, warnings


def load_json(path: str | Path) -> list[Charge]:
    """Una lista de objetos con fecha, descripción y monto (o el JSON crudo de Mercury)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("transactions", data) if isinstance(data, dict) else data
    return [c for c in (_from_record(t) for t in items) if c]


def _from_record(t: dict) -> Charge | None:
    if str(t.get("status", "")).lower() in SKIP_STATUSES:
        return None
    if str(t.get("kind", "")).lower() in SKIP_KINDS:
        return None
    raw_date = t.get("postedAt") or t.get("date") or t.get("createdAt") or t.get("fecha")
    desc = (t.get("counterpartyName") or t.get("description") or t.get("merchant")
            or t.get("bankDescription") or t.get("descripcion") or "")
    amt = t.get("amount", t.get("monto"))
    if isinstance(amt, str):
        amt = parse_amount(amt)
    d = parse_date(str(raw_date or ""))
    if d is None or amt is None or not desc:
        return None
    return Charge(d, str(desc).strip(), float(amt))


MERCURY_URL = "https://api.mercury.com/api/v1/transactions"


def load_mercury(api_key: str, start: date, end: date, opener=urllib.request.urlopen) -> list[Charge]:
    """Todas las transacciones de todas las cuentas (incluida la tarjeta), por fecha de posteo."""
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    out: list[Charge] = []
    after = None
    while True:
        params = {"postedStart": start.isoformat(), "postedEnd": end.isoformat(), "limit": 1000}
        if after:
            params["start_after"] = after
        req = urllib.request.Request(f"{MERCURY_URL}?{urllib.parse.urlencode(params)}",
                                     headers={"Authorization": f"Basic {token}", "Accept": "application/json"})
        with opener(req, timeout=60) as resp:
            page = json.loads(resp.read().decode())
        items = page.get("transactions", [])
        out.extend(c for c in (_from_record(t) for t in items) if c)
        if len(items) < 1000:
            return out
        after = items[-1]["id"]
