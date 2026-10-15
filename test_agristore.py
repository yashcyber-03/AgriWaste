"""AgriStore tests. Run from the project folder:  python tests/test_agristore.py
It deletes agri.db first and builds a fresh demo database, so do not run it on data you want to keep."""
import os, sys, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if os.path.exists("agri.db"):
    os.remove("agri.db")
import app, agristore, agripoints

client = app.app.test_client()
results = []
def check(name, condition):
    results.append(bool(condition)); print(("PASS  " if condition else "FAIL  ") + name)
def login(email):
    return {"Authorization": "Bearer " + client.post("/api/login", json={"email": email, "password": "demo123"}).json["token"]}
def balance(headers):
    return client.get("/api/agripoints/summary", headers=headers).json["balance"]

farmer, worker, admin = login("farmer@demo.com"), login("worker@demo.com"), login("admin@demo.com")
client.post("/api/register", json={"name": "Second", "email": "f2@demo.com", "password": "demo123"})
farmer2 = login("f2@demo.com")

def earn_points(headers, how_many_requests):
    """Give a farmer 60 points per request, using the real worker workflow."""
    for _ in range(how_many_requests):
        rid = client.post("/api/requests", json={"category_id": 1, "quantity_kg": 10, "address": "x"}, headers=headers).json["id"]
        for status in ("accepted", "scheduled", "collected"):
            client.put(f"/api/requests/{rid}/status", json={"status": status}, headers=worker)

def shop(headers, product_id, quantity):
    return client.put("/api/store/cart", json={"product_id": product_id, "quantity": quantity, "add": True}, headers=headers)
FORM = {"name": "Ravi", "phone": "9876543210", "address": "Plot 1", "city": "Daund", "state": "Maharashtra", "pin": "413801"}
def checkout(headers, points=0, key="k1", **extra):
    return client.post("/api/store/orders", json=dict(FORM, key=key, points_to_use=points, **extra), headers=headers)

# --- catalog
products = client.get("/api/store/products").json
check("catalog: 16 demo products, public (no login needed)", len(products) == 16 and all(p["is_demo"] for p in products))
check("catalog: 8 categories", len(client.get("/api/store/categories").json) == 8)
check("search 'sprayer'", [p["name"] for p in client.get("/api/store/products?q=sprayer").json] == ["Knapsack Sprayer 16 L"])
check("filter by category 5", len(client.get("/api/store/products?category=5").json) == 2)
prices = [p["price_paise"] for p in client.get("/api/store/products?sort=price_asc").json]
check("sort by price ascending", prices == sorted(prices))
check("in-stock filter works", len(client.get("/api/store/products?in_stock=1").json) == 16)
# --- cart
check("cart needs login (401)", client.get("/api/store/cart").status_code == 401)
check("admin/worker cannot use farmer cart (403)", client.get("/api/store/cart", headers=admin).status_code == 403)
shop(farmer, 5, 2); shop(farmer, 5, 1); shop(farmer, 2, 1)       # trowel set 350 x3, hose 650 x1
cart = client.get("/api/store/cart", headers=farmer).json
check("cart adds quantities and totals correctly (350*3 + 650 = Rs 1700)", cart["subtotal_paise"] == 170000 and len(cart["items"]) == 2)
check("cannot add more than stock", shop(farmer, 16, 6).status_code == 400)
check("cart is per farmer (farmer2 has an empty cart)", client.get("/api/store/cart", headers=farmer2).json["items"] == [])
# --- checkout validation
check("empty cart cannot check out", checkout(farmer2, key="e1").status_code == 400)
check("bad phone rejected", client.post("/api/store/orders", json=dict(FORM, phone="123", key="x"), headers=farmer).status_code == 400)
check("cannot use points you do not own", checkout(farmer, 100, key="p0").status_code == 400 and balance(farmer) == 0)
earn_points(farmer, 5)                                              # 5 x (10+50) = 300 points
check("farmer earned 300 AgriPoints through the real workflow", balance(farmer) == 300)
preview = client.get("/api/store/checkout-preview?points=200", headers=farmer).json
check("preview: Rs 1700 subtotal, 200 pts = Rs 20 off, free delivery, total Rs 1680",
      (preview["subtotal_paise"], preview["discount_paise"], preview["delivery_paise"], preview["total_paise"]) == (170000, 2000, 0, 168000))
check("max points = min(owned 300, 50% cap) = 300", preview["max_points"] == 300)
check("below minimum (50) rejected", checkout(farmer, 50, key="m1").status_code == 400)
check("not a multiple of 100 (150) rejected", checkout(farmer, 150, key="m2").status_code == 400)
# the 50% cap and the discount conversion, tested directly on the calculation functions
check("100 points = Rs 10 (1000 paise); 250 points = 2 blocks", agristore.calculate_totals([], 100)["discount_paise"] == 1000 and agristore.calculate_totals([], 250)["discount_paise"] == 2000)
check("50% cap: on a Rs 40 item with 300 pts owned, max usable = 200 pts (Rs 20)", agristore.max_points_allowed(4000, 300) == 200)
check("50% cap: asking for 300 pts on a Rs 40 item is refused, 200 is fine", agristore.points_error(300, 4000, 300) is not None and agristore.points_error(200, 4000, 300) is None)
check("cannot redeem more than owned even if the cap allows it", agristore.points_error(500, 1000000, 300) is not None)
check("only 'points eligible' products count towards the cap", agristore.calculate_totals([{"price_paise": 5000, "quantity": 1, "points_eligible": 0}], 0)["eligible_paise"] == 0)
check("delivery: Rs 40 below Rs 1000, free from Rs 1000", agristore.calculate_totals([{"price_paise": 90000, "quantity": 1, "points_eligible": 1}], 0)["delivery_paise"] == 4000 and agristore.calculate_totals([{"price_paise": 100000, "quantity": 1, "points_eligible": 1}], 0)["delivery_paise"] == 0)
# --- real order with tampering attempt
before_stock = client.get("/api/store/products/5").json["stock"]
r = checkout(farmer, 200, key="order-1", total_paise=1, discount_paise=999999, price_paise=1)
order = r.json
check("order created (201) and browser-sent prices/totals ignored", r.status_code == 201 and order["order_number"] == "AS-000001")
mine = client.get("/api/store/orders", headers=farmer).json[0]
check("order saved with correct amounts (1700 - 20 = 1680) and 200 points", (mine["subtotal_paise"], mine["discount_paise"], mine["total_paise"], mine["points_redeemed"]) == (170000, 2000, 168000, 200))
check("order items keep name and price at purchase time", {i["product_name"] for i in mine["items"]} == {"Hand Trowel Set (3 pcs)", "Garden Hose Pipe 30 m"})
check("points deducted exactly once (300 -> 100)", balance(farmer) == 100)
check("stock decreased by the quantity bought", client.get("/api/store/products/5").json["stock"] == before_stock - 3)
check("cart emptied after order", client.get("/api/store/cart", headers=farmer).json["items"] == [])
again = checkout(farmer, 200, key="order-1")
check("repeating the same checkout returns the SAME order, no second deduction", again.json["id"] == order["id"] and balance(farmer) == 100 and len(client.get("/api/store/orders", headers=farmer).json) == 1)
ledger = client.get("/api/agripoints/transactions", headers=farmer).json[0]
check("ledger has the redemption debit with order reference", ledger["points"] == -200 and "AS-000001" in ledger["description"])
# --- access control
oid = order["id"]
check("another farmer cannot open my order (404)", client.get(f"/api/store/orders/{oid}", headers=farmer2).status_code == 404)
check("another farmer's order list does not include mine", client.get("/api/store/orders", headers=farmer2).json == [])
check("farmer cannot use admin product/order endpoints (403)", all(client.open(u, method=m, json={"status": "shipped"}, headers=farmer).status_code == 403 for u, m in
      [("/api/store/admin/products", "GET"), (f"/api/store/admin/orders/{oid}/status", "PUT"), ("/api/store/admin/orders", "GET")]))
check("guest cannot place order (401)", client.post("/api/store/orders", json=dict(FORM, key="g")).status_code == 401)
# --- concurrency: 2 checkouts racing for the same 100 points
earn_points(farmer2, 2)                                             # 120 points
shop(farmer2, 5, 2)
outcomes = []
farmer2_id = [u["id"] for u in client.get("/api/admin/users", headers=admin).json if u["email"] == "f2@demo.com"][0]
def race(key):
    outcomes.append(agristore.place_order(farmer2_id, dict(FORM, key=key), 100)[1])  # (order_id, error); error None = success
threads = [threading.Thread(target=race, args=(f"race-{i}",)) for i in range(6)]
[t.start() for t in threads]; [t.join() for t in threads]
check("6 simultaneous checkouts: exactly ONE order succeeds (others see empty cart)", outcomes.count(None) == 1)
check("points never negative and deducted once (120 -> 20)", balance(farmer2) == 20)
# --- stock safety
shop(farmer, 16, 5)                                                 # all 5 mini weeders
check("last units can be bought", checkout(farmer, 0, key="w1").status_code == 201)
check("stock is now 0, cannot add more", shop(farmer2, 16, 1).status_code == 400 and client.get("/api/store/products/16").json["stock"] == 0)
# --- admin
check("admin lists all orders incl. points redeemed", any(o["points_redeemed"] == 200 for o in client.get("/api/store/admin/orders", headers=admin).json))
check("admin cannot skip steps (placed -> delivered)", client.put(f"/api/store/admin/orders/{oid}/status", json={"status": "delivered"}, headers=admin).status_code == 400)
check("admin confirms order", client.put(f"/api/store/admin/orders/{oid}/status", json={"status": "confirmed"}, headers=admin).status_code == 200)
check("farmer notified of status change", any("confirmed" in n["message"] for n in client.get("/api/notifications", headers=farmer).json))
stock_before_cancel = client.get("/api/store/products/5").json["stock"]
check("admin cancels order", client.put(f"/api/store/admin/orders/{oid}/status", json={"status": "cancelled"}, headers=admin).status_code == 200)
check("cancel returned stock (+3) and refunded 200 points (100 -> 300)", client.get("/api/store/products/5").json["stock"] == stock_before_cancel + 3 and balance(farmer) == 300)
check("cancelling again is refused, no double refund", client.put(f"/api/store/admin/orders/{oid}/status", json={"status": "cancelled"}, headers=admin).status_code == 400 and balance(farmer) == 300)
summary = client.get("/api/agripoints/summary", headers=farmer).json
check("refund is not counted as points 'earned' (total earned stays 300)", summary["total_earned"] == 300)
new_p = client.post("/api/store/admin/products", json={"name": "Test Tool", "category_id": 3, "price": "99.50", "stock": 4, "description": "t"}, headers=admin)
check("admin adds product; price Rs 99.50 stored as 9950 paise", new_p.status_code == 201 and client.get(f"/api/store/products/{new_p.json['id']}").json["price_paise"] == 9950)
check("admin disables product -> hidden from shop", client.put(f"/api/store/admin/products/{new_p.json['id']}", json={"name": "Test Tool", "category_id": 3, "price": 99.5, "stock": 4, "is_active": False}, headers=admin).status_code == 200 and client.get(f"/api/store/products/{new_p.json['id']}").status_code == 404)
check("admin deletes unused product", client.delete(f"/api/store/admin/products/{new_p.json['id']}", headers=admin).status_code == 200)
check("product that is in past orders cannot be deleted (409)", client.delete("/api/store/admin/products/5", headers=admin).status_code == 409)
check("farmer cannot add products (403)", client.post("/api/store/admin/products", json={}, headers=farmer).status_code == 403)
# --- pages
for url in ["/", "/agripoints", "/agristore", "/agristore/product", "/agristore/cart", "/agristore/checkout", "/agristore/orders", "/agristore/admin"]:
    check(f"page {url} loads", client.get(url).status_code == 200)
print(f"\nRESULT: {sum(results)} / {len(results)} passed")
sys.exit(0 if all(results) else 1)
