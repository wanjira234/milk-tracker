"""Bridges to the shops' own systems. Maziwa does not replace a shop's POS: a bridge reads the shop's
catalogue (products, prices, what's in stock) from it and hands the farmer's order to it.

Each bridge has fetch_catalogue() -> rows (header first, as a price list) and push_order(payload) -> the
shop system's own reference. Real bridges need the shop's API access; DemoPOS stands in for one in the demo:
its catalogue is a file that plays the shop's stock export, and pushing an order records it in the outbox,
exactly what would be sent to the shop's system.
"""
import csv
import os

from src import catalogue, db

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bridge")


class DemoPOS:
    title = "Fresha store system (demo)"

    def __init__(self, filename):
        self.path = os.path.join(DATA_DIR, filename)

    def fetch_catalogue(self):
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.reader(f))

    def push_order(self, payload):
        return f"POS-{payload['order_id']:05d}"


BRIDGES = {"demo_fresha": DemoPOS("fresha_store.csv")}


def get(kind):
    return BRIDGES.get(kind or "")


def title(kind):
    b = get(kind)
    return b.title if b else None


def sync(user):
    """Pull the shop's catalogue through its bridge. Returns (count, taken off, problems)."""
    if user.get("role") != "agrovet":
        raise ValueError("only an agrovet can sync its catalogue")
    shop = db.shop(user["id"]) or {}
    bridge = get(shop.get("bridge_kind"))
    if bridge is None:
        raise ValueError("this shop isn't connected to a system: upload a price list instead")
    try:
        rows = bridge.fetch_catalogue()
    except OSError:
        raise ValueError("the shop's system didn't answer: try again later") from None
    products, problems = catalogue.parse_rows(rows)
    n, off = catalogue.import_products(user["id"], products, "bridge", replace=True)
    return n, off, problems


def order_payload(order, lines, event):
    """What the shop's system (or a WhatsApp message) is told about an order: no more than it needs."""
    return {
        "event": event, "order_id": order["id"], "farm": order.get("farm_name") or order.get("farmer_name"),
        "phone": order.get("farmer_phone"), "fulfilment": order["fulfilment"], "day": str(order["wanted_on"]),
        "time": order["wanted_time"].strftime("%H:%M") if order.get("wanted_time") else None,
        "payment": order["payment_method"],
        "lines": [{"item": ln["product_name"], "unit": ln["unit"], "qty": float(ln["qty"])} for ln in lines],
        "notes": order.get("notes"),
    }


def whatsapp_text(order, lines):
    """The message the shop would get on WhatsApp once that channel is live (kept short, plain text)."""
    from src import orders

    when = f"{order['wanted_on']:%a %d %b}" + (f" {order['wanted_time']:%H:%M}" if order.get("wanted_time") else "")
    items = ", ".join(f"{float(ln['qty']):g} x {ln['product_name']}" for ln in lines)
    return (f"New Maziwa order #{order['id']} from {order.get('farm_name') or order.get('farmer_name')}: {items}. "
            f"{orders.FULFILMENT_SHOP[order['fulfilment']]} {when}. Pays: {orders.PAYMENT_SHOP[order['payment_method']]}. "
            "Open Maziwa Plus to confirm.")[:600]


def announce(order_id, event):
    """Tell the shop about an order event: through its bridge when it has one, and record the WhatsApp text
    (queued: WhatsApp isn't live yet, the shop sees the order in the app). Never raises: the farmer's order is
    already saved, and a shop system being down must not undo it."""
    try:
        order = db.get_order(order_id)
        if not order or not order["agrovet_user_id"]:
            return
        lines = db.order_lines(order_id)
        shop = db.shop(order["agrovet_user_id"]) or {}
        payload = order_payload(order, lines, event)
        bridge = get(shop.get("bridge_kind"))
        if bridge is not None:
            try:
                ref = bridge.push_order(payload)
                db.add_outbox(order["agrovet_user_id"], order_id, "pos", event, payload, "sent", ref)
            except Exception:
                db.add_outbox(order["agrovet_user_id"], order_id, "pos", event, payload, "failed")
        if event == "placed":
            db.add_outbox(order["agrovet_user_id"], order_id, "whatsapp", event, {"text": whatsapp_text(order, lines)}, "queued")
    except Exception:
        return
