"""A shop's product list, brought in from its own system: an uploaded price list (CSV or Excel, as most
POS and stock systems export) or a bridge to the system itself (src/bridges.py). Farmers only ever see
it; they cannot change it.

A price list needs a product name and a price; the unit, whether it's in stock and the shop's own item code
are optional. Column names are matched loosely ("Item", "Product", "Selling price", "Qty on hand"...).
"""
import csv
import io
from decimal import Decimal, InvalidOperation

from src import db

MAX_ROWS = 500
MAX_BYTES = 1_000_000

COLUMNS = {
    "name": ("product", "name", "item", "item name", "product name", "description"),
    "unit": ("unit", "sold per", "uom", "pack", "pack size", "size"),
    "price": ("price", "price kes", "price (kes)", "selling price", "retail price", "kes", "unit price"),
    "stock": ("in stock", "stock", "qty", "quantity", "qty on hand", "on hand", "available"),
    "ref": ("code", "sku", "item code", "barcode", "ref"),
}
_YES = {"yes", "y", "true", "1", "in stock", "available"}
_NO = {"no", "n", "false", "0", "out", "out of stock", "none"}


def _key(text):
    return " ".join(str(text or "").strip().lower().replace("_", " ").split())


def _columns(header):
    found = {}
    for i, h in enumerate(header):
        k = _key(h)
        for field, names in COLUMNS.items():
            if field not in found and k in names:
                found[field] = i
    if "name" not in found or "price" not in found:
        raise ValueError("the price list needs a product name column and a price column")
    return found


def _stock(value):
    v = _key(value)
    if v == "":
        return True
    if v in _YES:
        return True
    if v in _NO:
        return False
    try:
        return Decimal(v.replace(",", "")) > 0
    except InvalidOperation:
        return True


def parse_rows(rows):
    """rows = [header, row, ...] (lists of cells). Returns (products, problems): products are dicts with
    name, unit, price, in_stock, ref; problems are plain sentences about rows that were skipped."""
    rows = [r for r in rows if any(str(c or "").strip() for c in r)]
    if not rows:
        raise ValueError("the price list is empty")
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f"at most {MAX_ROWS} products in one price list")
    cols = _columns(rows[0])
    out, problems, seen = [], [], set()

    def cell(r, field):
        i = cols.get(field)
        return r[i] if i is not None and i < len(r) else None

    for n, r in enumerate(rows[1:], start=2):
        name = " ".join(str(cell(r, "name") or "").split())[:80]
        if not name:
            continue
        try:
            price = Decimal(str(cell(r, "price") or "").replace(",", "").replace("KES", "").replace("Ksh", "").strip())
        except InvalidOperation:
            problems.append(f"row {n} ({name}): the price isn't a number")
            continue
        if not (0 < price <= 1_000_000):
            problems.append(f"row {n} ({name}): the price must be between 1 and 1,000,000")
            continue
        if name.lower() in seen:
            problems.append(f"row {n} ({name}): listed twice, the first one is kept")
            continue
        seen.add(name.lower())
        unit = " ".join(str(cell(r, "unit") or "").split())[:30] or "each"
        ref = " ".join(str(cell(r, "ref") or "").split())[:60] or None
        out.append({"name": name, "unit": unit, "price": price.quantize(Decimal("0.01")), "in_stock": _stock(cell(r, "stock")),
                    "ref": ref})
    if not out:
        raise ValueError("no products with a name and a price were found")
    return out, problems


def read_file(name, data):
    """Rows from an uploaded .csv or .xlsx file (bytes)."""
    if len(data) > MAX_BYTES:
        raise ValueError("the file is too big (1 MB at most)")
    lower = (name or "").lower()
    if lower.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return list(csv.reader(io.StringIO(text)))
    if lower.endswith((".xlsx", ".xlsm")):
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise ValueError("that Excel file couldn't be read") from None
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True, max_row=MAX_ROWS + 50)]
    raise ValueError("upload a .csv or .xlsx file")


def import_products(agrovet_user_id, products, source, replace=True):
    """Write a parsed list onto the shop's catalogue in one transaction. With replace, anything not in the
    list is taken off (it stays on past orders). Returns (added or updated, taken off)."""
    before = {p["id"] for p in db.list_products(agrovet_user_id)}
    with db.batch():
        ids = [db.upsert_product(agrovet_user_id, p["name"], p["unit"], p["price"], p["in_stock"], source, p["ref"]) for p in products]
        if replace:
            db.retire_products_except(agrovet_user_id, ids)
        db.mark_catalogue_synced(agrovet_user_id)
    return len(ids), len(before - set(ids)) if replace else 0


def upload(user, name, data, replace=True):
    """The agrovet uploads its price list. Returns (count, taken off, problems)."""
    if user.get("role") != "agrovet":
        raise ValueError("only an agrovet can upload a price list")
    products, problems = parse_rows(read_file(name, data))
    n, off = import_products(user["id"], products, "upload", replace)
    return n, off, problems
