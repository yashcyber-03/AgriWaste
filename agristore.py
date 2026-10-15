"""AgriStore: product catalog, cart, checkout with an AgriPoints discount, and order management.

Money is stored in PAISE (whole numbers): Rs 10.50 = 1050 paise. This avoids decimal rounding errors.
The backend always recalculates prices, stock and discounts itself. It never trusts the browser.
It reuses the existing login (auth), the users table and the AgriPoints ledger (points_ledger).
"""
import os
import re
import sqlite3
from decimal import Decimal

from flask import jsonify, request, g, send_from_directory

import agripoints  # we reuse its database connection helper and its balance calculation

FRONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agristore_frontend")

# ---------------------------------------------------------------- settings (easy to change)
POINTS_PER_BLOCK = 100              # every 100 AgriPoints ...
PAISE_PER_BLOCK = 1000              # ... give Rs 10 discount
MIN_REDEEM_POINTS = 100             # smallest number of points that can be used in one order
MAX_DISCOUNT_PERCENT = 50           # discount can be at most 50% of the eligible product total
DELIVERY_CHARGE_PAISE = 4000        # Rs 40 delivery ...
FREE_DELIVERY_ABOVE_PAISE = 100000  # ... free when the product total is Rs 1000 or more

# An order moves forward through these statuses. Only an admin can change it.
NEXT_STATUS = {"placed": ("confirmed", "cancelled"), "confirmed": ("processing", "cancelled"),
               "processing": ("shipped", "cancelled"), "shipped": ("delivered",),
               "delivered": (), "cancelled": ()}

# Safe to run on every start: it only creates tables that do not exist yet.
SCHEMA = """
CREATE TABLE IF NOT EXISTS product_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES product_categories(id),
  name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  price_paise INTEGER NOT NULL CHECK (price_paise > 0),
  stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  image_url TEXT, points_eligible INTEGER NOT NULL DEFAULT 1,
  is_active INTEGER NOT NULL DEFAULT 1, is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS cart_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 99),
  UNIQUE (user_id, product_id));
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_number TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  idempotency_key TEXT NOT NULL,          -- stops a repeated click from creating a second order
  status TEXT NOT NULL DEFAULT 'placed'
    CHECK (status IN ('placed','confirmed','processing','shipped','delivered','cancelled')),
  payment_method TEXT NOT NULL DEFAULT 'Cash on Delivery (demo)',
  customer_name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL,
  city TEXT NOT NULL, state TEXT NOT NULL, pin_code TEXT NOT NULL,
  subtotal_paise INTEGER NOT NULL, points_redeemed INTEGER NOT NULL DEFAULT 0,
  discount_paise INTEGER NOT NULL DEFAULT 0, delivery_paise INTEGER NOT NULL DEFAULT 0,
  total_paise INTEGER NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, idempotency_key));
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id),
  product_name TEXT NOT NULL,             -- name and price are copied, so old orders never change
  unit_price_paise INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK (quantity > 0),
  line_total_paise INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
"""

CATEGORIES = ('Irrigation Equipment', 'Sprayers and Pumps', 'Gardening and Hand Tools', 'Crop Protection Equipment', 'Harvesting Tools', 'Soil Testing Equipment', 'Farm Safety Equipment', 'Small Farming Machinery')
IMAGE_NAMES = ('irrigation', 'sprayers', 'tools', 'protection', 'harvesting', 'soil', 'safety', 'machinery')

# Clearly marked DEMO products (example names, prices and stock for the college demonstration).
# (category number, name, description, price in rupees, stock)
DEMO_PRODUCTS = [
    (1, 'Drip Irrigation Kit (1 acre)', 'Pipes, drippers and connectors for a small plot.', 4500, 12),
    (1, 'Garden Hose Pipe 30 m', 'Flexible reinforced hose pipe.', 650, 40),
    (2, 'Knapsack Sprayer 16 L', 'Manual backpack sprayer with adjustable nozzle.', 1800, 25),
    (2, 'Water Pump 1 HP', 'Small electric pump for field irrigation.', 5200, 8),
    (3, 'Hand Trowel Set (3 pcs)', 'Steel trowel, fork and cultivator.', 350, 60),
    (3, 'Pruning Shears', 'Sharp bypass shears for plants and fruit trees.', 420, 35),
    (4, 'Bird Protection Net 10x10 m', 'Light net that keeps birds off the crop.', 700, 30),
    (4, 'Crop Cover Sheet', 'Protects young plants from frost and pests.', 950, 20),
    (5, 'Sickle (Steel Blade)', 'Traditional harvesting sickle with wooden handle.', 280, 50),
    (5, 'Harvesting Basket Set', 'Set of 3 strong baskets.', 540, 28),
    (6, 'Soil pH Meter', 'Quick pH reading of your soil.', 1200, 15),
    (6, 'Soil Moisture Tester', 'Shows how much water is in the soil.', 850, 18),
    (7, 'Safety Gloves (Pair)', 'Cut-resistant work gloves.', 180, 80),
    (7, 'Spray Mask and Goggles Set', 'Protects face while spraying.', 380, 45),
    (8, 'Manual Seed Sower', 'Push-type seed sower for small fields.', 3200, 10),
    (8, 'Mini Weeder Cultivator', 'Hand-pushed weeder for between crop rows.', 6800, 5),
]


# ---------------------------------------------------------------- price and discount calculation
def calculate_totals(lines, points):
    """lines: list of dicts with price_paise, quantity, points_eligible. points: AgriPoints the farmer wants to use.
    Only the 'eligible' products count towards the discount cap."""
    subtotal = sum(line["price_paise"] * line["quantity"] for line in lines)
    eligible = sum(line["price_paise"] * line["quantity"] for line in lines if line["points_eligible"])
    delivery = 0 if subtotal == 0 or subtotal >= FREE_DELIVERY_ABOVE_PAISE else DELIVERY_CHARGE_PAISE
    discount = points // POINTS_PER_BLOCK * PAISE_PER_BLOCK
    return {"subtotal_paise": subtotal, "eligible_paise": eligible, "points": points,
            "discount_paise": discount, "delivery_paise": delivery,
            "total_paise": subtotal - discount + delivery}


def max_points_allowed(eligible_paise, balance):
    """The most points that can be used: the smaller of the 50% rule and the points owned, in blocks of 100."""
    cap_paise = eligible_paise * MAX_DISCOUNT_PERCENT // 100
    by_cap = cap_paise // PAISE_PER_BLOCK * POINTS_PER_BLOCK
    by_balance = balance // POINTS_PER_BLOCK * POINTS_PER_BLOCK
    highest = min(by_cap, by_balance)
    return highest if highest >= MIN_REDEEM_POINTS else 0


def points_error(points, eligible_paise, balance):
    """Returns None if the farmer may use this many points, otherwise a message explaining why not."""
    if points == 0:
        return None
    if points % POINTS_PER_BLOCK != 0 or points < MIN_REDEEM_POINTS:
        return f"Use AgriPoints in multiples of {POINTS_PER_BLOCK} (minimum {MIN_REDEEM_POINTS})."
    if points > balance:
        return "You do not have that many AgriPoints."
    if points > max_points_allowed(eligible_paise, balance):
        return f"You can use at most {max_points_allowed(eligible_paise, balance)} AgriPoints on this order."
    return None


def read_points(value):
    """Points typed by the user -> a whole number (0 if empty or invalid)."""
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def rupees_to_paise(value):
    """Rs 249.50 typed by the admin -> 24950 paise."""
    return int((Decimal(str(value)) * 100).to_integral_value())


def read_cart(conn, user_id):
    """The farmer's cart with the CURRENT price and stock from the products table."""
    rows = conn.execute("""SELECT c.quantity, p.id AS product_id, p.name, p.price_paise, p.stock, p.image_url,
                                  p.points_eligible, p.is_active, p.price_paise * c.quantity AS line_total_paise
                           FROM cart_items c JOIN products p ON p.id = c.product_id
                           WHERE c.user_id=? ORDER BY c.id""", (user_id,)).fetchall()
    return [dict(row) for row in rows]


def read_delivery_form(data):
    """Returns (clean delivery details, error message)."""
    details = {"customer_name": data.get("name"), "phone": data.get("phone"), "address": data.get("address"),
               "city": data.get("city"), "state": data.get("state"), "pin_code": data.get("pin")}
    details = {key: str(value or "").strip() for key, value in details.items()}
    if not all(details.values()):
        return None, "Please fill in all delivery details."
    if not re.fullmatch(r"[6-9]\d{9}", details["phone"]):
        return None, "Enter a valid 10-digit mobile number."
    if not re.fullmatch(r"\d{6}", details["pin_code"]):
        return None, "Enter a valid 6-digit PIN code."
    return details, None


def stop(conn, message):
    """Cancel the current database transaction and report an error."""
    conn.execute("ROLLBACK")
    return None, message, False


# ---------------------------------------------------------------- placing and changing orders
def place_order(user_id, form, points):
    """Create the order, reduce stock and deduct points in ONE all-or-nothing transaction.
    Returns (order_id, error message, created). error is None when it worked."""
    key = str(form.get("key") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
        return None, "Invalid checkout request. Please reload the page.", False
    details, error = read_delivery_form(form)
    if error:
        return None, error, False

    conn = agripoints._con()
    try:
        conn.execute("BEGIN IMMEDIATE")  # one checkout at a time, so the same points can never be spent twice

        # The same checkout sent again (double click / retry)? Return the order we already made.
        old = conn.execute("SELECT id FROM orders WHERE user_id=? AND idempotency_key=?", (user_id, key)).fetchone()
        if old:
            conn.execute("ROLLBACK")
            return old["id"], None, False

        cart = read_cart(conn, user_id)
        if not cart:
            return stop(conn, "Your cart is empty.")
        for item in cart:
            if not item["is_active"]:
                return stop(conn, f"{item['name']} is no longer available. Please remove it from your cart.")
            if item["quantity"] > item["stock"]:
                return stop(conn, f"Only {item['stock']} left of {item['name']}. Please update your cart.")

        balance = agripoints._balance(conn, user_id)
        totals = calculate_totals(cart, points)
        error = points_error(points, totals["eligible_paise"], balance)
        if error:
            return stop(conn, error)

        cursor = conn.execute(
            """INSERT INTO orders(order_number, user_id, idempotency_key, customer_name, phone, address, city, state,
               pin_code, subtotal_paise, points_redeemed, discount_paise, delivery_paise, total_paise)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("pending-" + key, user_id, key, details["customer_name"], details["phone"], details["address"],
             details["city"], details["state"], details["pin_code"], totals["subtotal_paise"], points,
             totals["discount_paise"], totals["delivery_paise"], totals["total_paise"]))
        order_id = cursor.lastrowid
        order_number = f"AS-{order_id:06d}"
        conn.execute("UPDATE orders SET order_number=? WHERE id=?", (order_number, order_id))

        for item in cart:
            conn.execute("INSERT INTO order_items(order_id, product_id, product_name, unit_price_paise, quantity,"
                         " line_total_paise) VALUES(?,?,?,?,?,?)",
                         (order_id, item["product_id"], item["name"], item["price_paise"], item["quantity"],
                          item["line_total_paise"]))
            # "stock >= ?" means stock can never go below zero, even when two orders arrive together.
            reduced = conn.execute("UPDATE products SET stock = stock - ? WHERE id=? AND stock >= ?",
                                   (item["quantity"], item["product_id"], item["quantity"]))
            if reduced.rowcount != 1:
                return stop(conn, f"{item['name']} just went out of stock.")

        if points:
            conn.execute("INSERT INTO points_ledger(user_id, entry_type, activity_type, points, reference, description,"
                         " balance_after) VALUES(?,?,?,?,?,?,?)",
                         (user_id, "debit", "order_redemption", points, f"redeem:{order_number}",
                          f"Redeemed on AgriStore order {order_number}", balance - points))

        conn.execute("DELETE FROM cart_items WHERE user_id=?", (user_id,))
        conn.execute("INSERT INTO notifications(user_id, message) VALUES(?,?)",
                     (user_id, f"Your AgriStore order {order_number} has been placed."))
        conn.execute("COMMIT")
        return order_id, None, True
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        return None, "Could not place the order. Please try again.", False
    finally:
        conn.close()


def change_order_status(order_id, new_status):
    """Admin action. Cancelling returns the stock and refunds the points. Returns (ok, error message, http status)."""
    conn = agripoints._con()
    try:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if order is None:
            conn.execute("ROLLBACK")
            return False, "Order not found.", 404
        if new_status not in NEXT_STATUS[order["status"]]:
            conn.execute("ROLLBACK")
            return False, f"An order that is {order['status']} cannot become {new_status}.", 400

        conn.execute("UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, order_id))
        if new_status == "cancelled":
            for item in conn.execute("SELECT product_id, quantity FROM order_items WHERE order_id=?", (order_id,)).fetchall():
                conn.execute("UPDATE products SET stock = stock + ? WHERE id=?", (item["quantity"], item["product_id"]))
            if order["points_redeemed"]:  # the refund is a NEW credit in the ledger; old rows are never edited
                balance = agripoints._balance(conn, order["user_id"])
                conn.execute("INSERT INTO points_ledger(user_id, entry_type, activity_type, points, reference,"
                             " description, balance_after) VALUES(?,?,?,?,?,?,?)",
                             (order["user_id"], "credit", "order_refund", order["points_redeemed"],
                              f"refund:{order['order_number']}", f"Refund for cancelled order {order['order_number']}",
                              balance + order["points_redeemed"]))
        conn.execute("INSERT INTO notifications(user_id, message) VALUES(?,?)",
                     (order["user_id"], f"Your AgriStore order {order['order_number']} is now {new_status}."))
        conn.execute("COMMIT")
        return True, None, 200
    finally:
        conn.close()


def read_product_form(data, db):
    """Check the admin's product form. Returns (clean values, error message)."""
    try:
        name = str(data.get("name") or "").strip()
        price = rupees_to_paise(data.get("price"))
        stock = int(data.get("stock"))
        category_id = int(data.get("category_id"))
    except (ArithmeticError, TypeError, ValueError):
        return None, "Enter a name, a price, a stock number and a category."
    if not name or price <= 0 or stock < 0:
        return None, "Name is required, price must be above 0 and stock cannot be negative."
    if db().execute("SELECT 1 FROM product_categories WHERE id=?", (category_id,)).fetchone() is None:
        return None, "Unknown category."
    image_url = str(data.get("image_url") or "").strip()
    if not image_url and 1 <= category_id <= len(IMAGE_NAMES):
        image_url = f"/agristore_frontend/images/{IMAGE_NAMES[category_id - 1]}.svg"
    return {"category_id": category_id, "name": name, "description": str(data.get("description") or "").strip(),
            "price_paise": price, "stock": stock, "image_url": image_url or None,
            "points_eligible": 0 if data.get("points_eligible") in (0, False, "0") else 1,
            "is_active": 0 if data.get("is_active") in (0, False, "0") else 1}, None


# ---------------------------------------------------------------- register all routes
def register(app, db_path, auth, db):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    if not conn.execute("SELECT 1 FROM product_categories").fetchone():
        conn.executemany("INSERT INTO product_categories(name) VALUES(?)", [(name,) for name in CATEGORIES])
    if not conn.execute("SELECT 1 FROM products").fetchone():
        for category_id, name, description, price, stock in DEMO_PRODUCTS:
            conn.execute("INSERT INTO products(category_id, name, description, price_paise, stock, image_url, is_demo)"
                         " VALUES(?,?,?,?,?,?,1)",
                         (category_id, name, description, price * 100, stock,
                          f"/agristore_frontend/images/{IMAGE_NAMES[category_id - 1]}.svg"))
    conn.commit()
    conn.close()

    def rows(sql, values=()):
        return [dict(row) for row in db().execute(sql, values).fetchall()]

    PRODUCT_SELECT = ("SELECT p.*, c.name AS category FROM products p "
                      "JOIN product_categories c ON c.id = p.category_id")

    # ----- public: anyone can browse -----
    @app.get("/api/store/config")
    def store_config():
        return jsonify(points_per_block=POINTS_PER_BLOCK, rupees_per_block=PAISE_PER_BLOCK // 100,
                       min_points=MIN_REDEEM_POINTS, max_percent=MAX_DISCOUNT_PERCENT,
                       delivery_paise=DELIVERY_CHARGE_PAISE, free_delivery_above_paise=FREE_DELIVERY_ABOVE_PAISE)

    @app.get("/api/store/categories")
    def store_categories():
        return jsonify(rows("SELECT * FROM product_categories ORDER BY id"))

    @app.get("/api/store/products")
    def store_products():
        sql = PRODUCT_SELECT + " WHERE p.is_active = 1"
        values = []
        search = (request.args.get("q") or "").strip()
        if search:
            sql += " AND (p.name LIKE ? OR p.description LIKE ?)"
            values += [f"%{search}%", f"%{search}%"]
        if request.args.get("category", "").isdigit():
            sql += " AND p.category_id = ?"
            values.append(int(request.args["category"]))
        if request.args.get("in_stock") == "1":
            sql += " AND p.stock > 0"
        # only these exact sort choices are allowed (user text is never put into SQL)
        sort_sql = {"price_asc": "p.price_paise ASC", "price_desc": "p.price_paise DESC"}.get(request.args.get("sort"), "p.id ASC")
        return jsonify(rows(sql + " ORDER BY " + sort_sql, values))

    @app.get("/api/store/products/<int:product_id>")
    def store_product(product_id):
        found = rows(PRODUCT_SELECT + " WHERE p.id = ? AND p.is_active = 1", (product_id,))
        return jsonify(found[0]) if found else (jsonify(error="Product not found."), 404)

    # ----- farmer: cart -----
    def cart_response(user_id):
        items = read_cart(db(), user_id)
        return {"items": items, "subtotal_paise": sum(item["line_total_paise"] for item in items)}

    @app.get("/api/store/cart")
    @auth("farmer")
    def get_cart():
        return jsonify(cart_response(g.user["id"]))

    @app.put("/api/store/cart")
    @auth("farmer")
    def change_cart():
        """add=true adds to the quantity already in the cart; otherwise the quantity is set. Quantity 0 removes."""
        data = request.get_json(silent=True) or {}
        try:
            product_id, quantity = int(data.get("product_id")), int(data.get("quantity"))
        except (TypeError, ValueError):
            return jsonify(error="Choose a product and a quantity."), 400
        product = db().execute("SELECT * FROM products WHERE id=? AND is_active=1", (product_id,)).fetchone()
        if product is None:
            return jsonify(error="Product not found."), 404
        old = db().execute("SELECT quantity FROM cart_items WHERE user_id=? AND product_id=?",
                           (g.user["id"], product_id)).fetchone()
        new_quantity = quantity + (old["quantity"] if old and data.get("add") else 0)
        if new_quantity <= 0:
            db().execute("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (g.user["id"], product_id))
        elif new_quantity > min(product["stock"], 99):
            return jsonify(error=f"Only {min(product['stock'], 99)} available in stock."), 400
        else:
            db().execute("INSERT INTO cart_items(user_id, product_id, quantity) VALUES(?,?,?) "
                         "ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = excluded.quantity",
                         (g.user["id"], product_id, new_quantity))
        db().commit()
        return jsonify(cart_response(g.user["id"]))

    # ----- farmer: checkout and orders -----
    @app.get("/api/store/checkout-preview")
    @auth("farmer")
    def checkout_preview():
        items = read_cart(db(), g.user["id"])
        points = read_points(request.args.get("points"))
        balance = agripoints._balance(db(), g.user["id"])
        totals = calculate_totals(items, points)
        totals.update(items=items, balance=balance, max_points=max_points_allowed(totals["eligible_paise"], balance),
                      points_error=points_error(points, totals["eligible_paise"], balance))
        return jsonify(totals)

    @app.post("/api/store/orders")
    @auth("farmer")
    def create_order():
        form = request.get_json(silent=True) or {}
        order_id, error, created = place_order(g.user["id"], form, read_points(form.get("points_to_use")))
        if error:
            return jsonify(error=error), 400
        return jsonify(my_order_data(order_id)), (201 if created else 200)

    def orders_with_items(where, values=()):
        orders = rows("SELECT o.*, u.name AS farmer FROM orders o JOIN users u ON u.id = o.user_id "
                      + where + " ORDER BY o.id DESC", values)
        for order in orders:
            order["items"] = rows("SELECT * FROM order_items WHERE order_id=?", (order["id"],))
        return orders

    def my_order_data(order_id):
        return orders_with_items("WHERE o.id=?", (order_id,))[0]

    @app.get("/api/store/orders")
    @auth("farmer")
    def my_orders():
        return jsonify(orders_with_items("WHERE o.user_id=?", (g.user["id"],)))  # only the signed-in farmer's orders

    @app.get("/api/store/orders/<int:order_id>")
    @auth("farmer")
    def my_order(order_id):
        found = orders_with_items("WHERE o.id=? AND o.user_id=?", (order_id, g.user["id"]))
        return jsonify(found[0]) if found else (jsonify(error="Order not found."), 404)

    # ----- admin: products and orders -----
    @app.get("/api/store/admin/products")
    @auth("admin")
    def admin_products():
        return jsonify(rows(PRODUCT_SELECT + " ORDER BY p.id"))

    @app.post("/api/store/admin/products")
    @auth("admin")
    def admin_add_product():
        form, error = read_product_form(request.get_json(silent=True) or {}, db)
        if error:
            return jsonify(error=error), 400
        cursor = db().execute("INSERT INTO products(category_id, name, description, price_paise, stock, image_url,"
                              " points_eligible, is_active) VALUES(?,?,?,?,?,?,?,?)",
                              (form["category_id"], form["name"], form["description"], form["price_paise"],
                               form["stock"], form["image_url"], form["points_eligible"], form["is_active"]))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201

    @app.put("/api/store/admin/products/<int:product_id>")
    @auth("admin")
    def admin_edit_product(product_id):
        form, error = read_product_form(request.get_json(silent=True) or {}, db)
        if error:
            return jsonify(error=error), 400
        cursor = db().execute("UPDATE products SET category_id=?, name=?, description=?, price_paise=?, stock=?,"
                              " image_url=?, points_eligible=?, is_active=? WHERE id=?",
                              (form["category_id"], form["name"], form["description"], form["price_paise"],
                               form["stock"], form["image_url"], form["points_eligible"], form["is_active"], product_id))
        db().commit()
        return jsonify(ok=True) if cursor.rowcount else (jsonify(error="Product not found."), 404)

    @app.delete("/api/store/admin/products/<int:product_id>")
    @auth("admin")
    def admin_delete_product(product_id):
        # A product that is already in an order is never deleted (old orders keep their history). Disable it instead.
        if db().execute("SELECT 1 FROM order_items WHERE product_id=?", (product_id,)).fetchone():
            return jsonify(error="This product is in past orders. Disable it instead of deleting it."), 409
        db().execute("DELETE FROM products WHERE id=?", (product_id,))
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/store/admin/orders")
    @auth("admin")
    def admin_orders():
        return jsonify(orders_with_items(""))

    @app.put("/api/store/admin/orders/<int:order_id>/status")
    @auth("admin")
    def admin_order_status(order_id):
        status = str((request.get_json(silent=True) or {}).get("status") or "").lower()
        done, error, code = change_order_status(order_id, status)
        return jsonify(ok=True) if done else (jsonify(error=error), code)

    # ----- pages and static files -----
    @app.get("/agristore")
    def store_home():
        return send_from_directory(FRONT, "index.html")

    @app.get("/agristore/<page>")
    def store_page(page):
        if page not in ("product", "cart", "checkout", "orders", "admin"):
            return "Not found", 404
        return send_from_directory(FRONT, page + ".html")

    @app.get("/agristore_frontend/<path:filename>")
    def store_static(filename):
        return send_from_directory(FRONT, filename)
