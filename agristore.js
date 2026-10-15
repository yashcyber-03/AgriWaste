// AgriStore shop pages. Every HTML page has <body data-page="..."> and the matching function at the bottom runs.
var token = localStorage.getItem('tok');          // same login token as the main AgriWaste site
var me = null;
try { me = JSON.parse(localStorage.getItem('me')); } catch (error) { me = null; }
var isFarmer = !!(token && me && me.role === 'farmer');
var rules = null;                                  // points rules from the server (shown to the farmer)

function esc(text) {                               // makes text safe to put inside HTML
  return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; });
}
function rupees(paise) { return '\u20B9' + (paise / 100).toLocaleString('en-IN'); }
function show(id, html) { document.getElementById(id).innerHTML = html; }
function toast(message) {
  var box = document.getElementById('toast');
  box.textContent = message; box.className = 'show';
  setTimeout(function () { box.className = ''; }, 2400);
}
function call(url, method, body) {                 // one place that talks to the server
  var options = { method: method || 'GET', headers: { 'Content-Type': 'application/json' } };
  if (token) options.headers.Authorization = 'Bearer ' + token;
  if (body) options.body = JSON.stringify(body);
  return fetch(url, options).then(function (response) {
    return response.json().catch(function () { return {}; }).then(function (data) {
      if (!response.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
      return data;
    });
  });
}
function store(path, method, body) { return call('/api/store' + path, method, body); }
function signOut() { localStorage.removeItem('tok'); localStorage.removeItem('me'); location.href = '/'; }
function needLogin() { alert('Please sign in as a farmer to continue.'); location.href = '/'; }

// ---------------------------------------------------------------- header (same on every page)
function drawHeader() {
  var account = me && token
    ? '<span>' + esc(me.name) + ' (' + esc(me.role) + ')</span><a href="/">AgriWaste dashboard</a>' +
      (me.role === 'admin' ? '<a href="/agristore/admin">Manage store</a>' : '') +
      '<a href="#" onclick="signOut(); return false;">Sign out</a>'
    : '<a href="/">Sign in</a>';
  show('header',
    '<a class="brand" href="/agristore">Agri<span>Store</span></a>' +
    '<nav><a href="/agristore">Home</a><a href="/agristore#all-products">All Products</a><a href="/agristore#categories">Categories</a>' +
    '<a href="/agristore/orders">My Orders</a><a href="/agripoints">My AgriPoints</a>' +
    '<a href="/agristore/cart">Cart<span class="badge" id="cart-count">0</span></a></nav>' +
    (isFarmer ? '<span class="points-chip" id="points-chip">\uD83C\uDF43 ...</span>' : '') +
    '<details class="menu"><summary>My Account \u25BE</summary><div>' + account + '</div></details>');
  if (!isFarmer) return;
  call('/api/agripoints/summary').then(function (wallet) {       // the real balance comes from the AgriPoints system
    var discount = Math.floor(wallet.balance / 100) * 10;
    show('points-chip', '\uD83C\uDF43 ' + wallet.balance + ' pts \u00B7 \u20B9' + discount + ' discount available');
  }).catch(function () {});
  refreshCartCount();
}
function refreshCartCount() {
  if (!isFarmer) return;
  store('/cart').then(function (cart) {
    var total = 0;
    cart.items.forEach(function (item) { total += item.quantity; });
    document.getElementById('cart-count').textContent = total;
  }).catch(function () {});
}
function addToCart(productId, quantity) {
  if (!isFarmer) { needLogin(); return; }
  store('/cart', 'PUT', { product_id: productId, quantity: quantity, add: true })
    .then(function () { toast('Added to cart'); refreshCartCount(); })
    .catch(function (error) { alert(error.message); });
}

// ---------------------------------------------------------------- home page
function productCard(p) {
  var inStock = p.stock > 0;
  return '<article class="card"><a href="/agristore/product?id=' + p.id + '"><img src="' + esc(p.image_url) + '" alt="' + esc(p.name) + '"></a>' +
    '<div class="card-body"><div><span class="tag">' + esc(p.category) + '</span>' + (p.is_demo ? '<span class="tag demo">Demo product</span>' : '') + '</div>' +
    '<h3>' + esc(p.name) + '</h3><p class="muted small">' + esc(p.description) + '</p>' +
    '<div class="price">' + rupees(p.price_paise) + '</div>' +
    '<div class="' + (inStock ? 'in-stock' : 'out-stock') + '">' + (inStock ? 'In stock (' + p.stock + ')' : 'Out of stock') + '</div>' +
    (p.points_eligible && rules ? '<div class="small muted">Use AgriPoints: up to ' + rules.max_percent + '% off</div>' : '') +
    '<div class="row"><a class="btn alt" href="/agristore/product?id=' + p.id + '">View details</a>' +
    '<button class="btn" onclick="addToCart(' + p.id + ', 1)"' + (inStock ? '' : ' disabled') + '>Add to cart</button></div></div></article>';
}
function loadProducts() {
  var params = new URLSearchParams();
  params.set('q', document.getElementById('search').value);
  params.set('category', document.getElementById('category').value);
  params.set('sort', document.getElementById('sort').value);
  if (document.getElementById('instock').checked) params.set('in_stock', '1');
  store('/products?' + params.toString()).then(function (products) {
    show('products', products.length ? products.map(productCard).join('') : '<p class="empty">No products match your search.</p>');
  });
}
function homePage() {
  store('/config').then(function (data) { rules = data; loadProducts(); });
  store('/categories').then(function (categories) {
    var options = '<option value="">All categories</option>';
    var chips = '<button class="chip on" data-id="">All</button>';
    categories.forEach(function (c) {
      options += '<option value="' + c.id + '">' + esc(c.name) + '</option>';
      chips += '<button class="chip" data-id="' + c.id + '">' + esc(c.name) + '</button>';
    });
    show('category', options); show('chips', chips);
    document.querySelectorAll('.chip').forEach(function (chip) {
      chip.onclick = function () { document.getElementById('category').value = chip.dataset.id; markChip(); loadProducts(); };
    });
  });
  function markChip() {
    document.querySelectorAll('.chip').forEach(function (chip) { chip.className = 'chip' + (chip.dataset.id === document.getElementById('category').value ? ' on' : ''); });
  }
  ['search', 'category', 'sort', 'instock'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', function () { markChip(); loadProducts(); });
  });
}

// ---------------------------------------------------------------- product page
function productPage() {
  var id = new URLSearchParams(location.search).get('id');
  store('/products/' + encodeURIComponent(id)).then(function (p) {
    show('product',
      '<img src="' + esc(p.image_url) + '" alt="' + esc(p.name) + '"><div><span class="tag">' + esc(p.category) + '</span>' +
      (p.is_demo ? '<span class="tag demo">Demo product</span>' : '') + '<h1>' + esc(p.name) + '</h1>' +
      '<p class="muted">' + esc(p.description) + '</p><div class="price" style="font-size:1.8rem">' + rupees(p.price_paise) + '</div>' +
      '<p class="' + (p.stock > 0 ? 'in-stock' : 'out-stock') + '">' + (p.stock > 0 ? 'In stock (' + p.stock + ' available)' : 'Out of stock') + '</p>' +
      (p.points_eligible ? '<p class="small muted">You can use AgriPoints at checkout for a discount on this product.</p>' : '') +
      '<div class="row"><input type="number" id="qty" value="1" min="1" max="' + Math.max(1, p.stock) + '" style="width:90px">' +
      '<button class="btn" onclick="addToCart(' + p.id + ', parseInt(document.getElementById(\'qty\').value) || 1)"' + (p.stock > 0 ? '' : ' disabled') + '>Add to cart</button></div></div>');
  }).catch(function (error) { show('product', '<p class="empty">' + esc(error.message) + '</p>'); });
}

// ---------------------------------------------------------------- cart page
function setQuantity(productId, quantity) {
  store('/cart', 'PUT', { product_id: productId, quantity: quantity })
    .then(function () { cartPage(); refreshCartCount(); })
    .catch(function (error) { alert(error.message); });
}
function cartPage() {
  if (!isFarmer) { show('cart', '<p class="empty">Please <a href="/">sign in as a farmer</a> to use the cart.</p>'); return; }
  store('/cart').then(function (cart) {
    if (!cart.items.length) { show('cart', '<p class="empty">Your cart is empty. <a href="/agristore">Browse products</a></p>'); return; }
    var html = cart.items.map(function (item) {
      return '<div class="cart-line"><img src="' + esc(item.image_url) + '" alt=""><div><b>' + esc(item.name) + '</b><div class="muted small">' + rupees(item.price_paise) + ' each</div></div>' +
        '<div class="qty"><button onclick="setQuantity(' + item.product_id + ',' + (item.quantity - 1) + ')">\u2212</button><b>' + item.quantity +
        '</b><button onclick="setQuantity(' + item.product_id + ',' + (item.quantity + 1) + ')">+</button></div>' +
        '<div><b>' + rupees(item.line_total_paise) + '</b><br><button class="btn danger" style="padding:.2rem .6rem" onclick="setQuantity(' + item.product_id + ',0)">Remove</button></div></div>';
    }).join('');
    show('cart', '<div class="panel">' + html + '<div class="sum-row total"><span>Subtotal</span><span>' + rupees(cart.subtotal_paise) + '</span></div>' +
      '<p class="muted small">Delivery and your AgriPoints discount are calculated at checkout.</p><a class="btn" href="/agristore/checkout">Proceed to checkout</a></div>');
  });
}

// ---------------------------------------------------------------- checkout page
var checkoutKey = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random();
function refreshSummary() {
  var points = parseInt(document.getElementById('points').value) || 0;
  store('/checkout-preview?points=' + points).then(function (p) {
    document.getElementById('max-points').textContent = p.max_points;
    document.getElementById('use-max').onclick = function () { document.getElementById('points').value = p.max_points; refreshSummary(); };
    show('points-error', esc(p.points_error || ''));
    show('summary',
      '<div class="sum-row"><span>Product subtotal</span><span>' + rupees(p.subtotal_paise) + '</span></div>' +
      '<div class="sum-row discount"><span>AgriPoints applied (' + (p.points_error ? 0 : p.points) + ')</span><span>\u2212 ' + rupees(p.points_error ? 0 : p.discount_paise) + '</span></div>' +
      '<div class="sum-row"><span>Delivery charge</span><span>' + (p.delivery_paise ? rupees(p.delivery_paise) : 'FREE') + '</span></div>' +
      '<div class="sum-row total"><span>Amount payable</span><span>' + rupees(p.points_error ? p.subtotal_paise + p.delivery_paise : p.total_paise) + '</span></div>');
    document.getElementById('balance').textContent = p.balance;
    document.getElementById('place').disabled = !p.items.length || !!p.points_error;
  });
}
function checkoutPage() {
  if (!isFarmer) { show('checkout', '<p class="empty">Please <a href="/">sign in as a farmer</a> to check out.</p>'); return; }
  show('checkout',
    '<div class="checkout-layout"><div class="panel"><h2>Delivery details</h2><br>' +
    '<div class="grid2"><div class="field"><label for="name">Full name</label><input id="name" value="' + esc(me.name) + '"></div>' +
    '<div class="field"><label for="phone">Mobile number</label><input id="phone" inputmode="numeric" maxlength="10"></div></div>' +
    '<div class="field"><label for="address">Delivery address</label><input id="address"></div>' +
    '<div class="grid2"><div class="field"><label for="city">Village / City</label><input id="city"></div><div class="field"><label for="state">State</label><input id="state" value="Maharashtra"></div></div>' +
    '<div class="field" style="max-width:200px"><label for="pin">PIN code</label><input id="pin" inputmode="numeric" maxlength="6"></div>' +
    '<p class="small muted">Payment: Cash on Delivery (demo order, no online payment).</p></div>' +
    '<div class="panel"><h2>Order summary</h2><br><div class="field"><label for="points">Use AgriPoints (you have <span id="balance">0</span>; usable now: <span id="max-points">0</span>)</label>' +
    '<div class="row"><input id="points" type="number" min="0" step="100" value="0" style="width:130px"><button type="button" class="btn alt" id="use-max">Use max</button></div>' +
    '<div class="error" id="points-error"></div><div class="small muted">100 points = \u20B910 off. Minimum 100 points. Up to 50% of the product price.</div></div>' +
    '<div id="summary"></div><div class="error" id="order-error"></div><button class="btn" id="place" style="width:100%" disabled>Place order</button></div></div>');
  document.getElementById('points').addEventListener('input', refreshSummary);
  document.getElementById('place').onclick = placeOrder;
  refreshSummary();
}
function placeOrder() {
  var button = document.getElementById('place');
  button.disabled = true;                              // stops double clicks; the server also guards with the key
  function value(id) { return document.getElementById(id).value; }
  store('/orders', 'POST', { key: checkoutKey, name: value('name'), phone: value('phone'), address: value('address'),
                             city: value('city'), state: value('state'), pin: value('pin'), points_to_use: parseInt(value('points')) || 0 })
    .then(function (order) { location.href = '/agristore/orders?placed=' + encodeURIComponent(order.order_number); })
    .catch(function (error) { show('order-error', esc(error.message)); button.disabled = false; });
}

// ---------------------------------------------------------------- orders page
function ordersPage() {
  if (!isFarmer) { show('orders', '<p class="empty">Please <a href="/">sign in as a farmer</a> to see your orders.</p>'); return; }
  var placed = new URLSearchParams(location.search).get('placed');
  if (placed) show('flash', '<div class="notice">\u2705 Order <b>' + esc(placed) + '</b> placed. Pay cash on delivery (demo order).</div>');
  store('/orders').then(function (orders) {
    if (!orders.length) { show('orders', '<p class="empty">You have no orders yet. <a href="/agristore">Start shopping</a></p>'); return; }
    show('orders', orders.map(function (o) {
      var items = o.items.map(function (i) { return '<tr><td>' + esc(i.product_name) + '</td><td>' + i.quantity + '</td><td>' + rupees(i.unit_price_paise) + '</td><td>' + rupees(i.line_total_paise) + '</td></tr>'; }).join('');
      return '<details class="order"' + (o.order_number === placed ? ' open' : '') + '><summary><span>' + esc(o.order_number) + ' \u00B7 ' + esc(o.created_at.slice(0, 10)) + '</span>' +
        '<span><span class="status ' + o.status + '">' + o.status + '</span> ' + rupees(o.total_paise) + '</span></summary><br>' +
        '<div class="table-scroll"><table><tr><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr>' + items + '</table></div><br>' +
        '<div class="sum-row"><span>Subtotal</span><span>' + rupees(o.subtotal_paise) + '</span></div>' +
        '<div class="sum-row discount"><span>AgriPoints redeemed (' + o.points_redeemed + ')</span><span>\u2212 ' + rupees(o.discount_paise) + '</span></div>' +
        '<div class="sum-row"><span>Delivery</span><span>' + (o.delivery_paise ? rupees(o.delivery_paise) : 'FREE') + '</span></div>' +
        '<div class="sum-row total"><span>Final amount</span><span>' + rupees(o.total_paise) + '</span></div>' +
        '<p class="muted small">Deliver to: ' + esc(o.customer_name) + ', ' + esc(o.address) + ', ' + esc(o.city) + ', ' + esc(o.state) + ' ' + esc(o.pin_code) + ' \u00B7 ' + esc(o.phone) + ' \u00B7 ' + esc(o.payment_method) + '</p></details>';
    }).join(''));
  });
}

// ---------------------------------------------------------------- start the right page
var pages = { home: homePage, product: productPage, cart: cartPage, checkout: checkoutPage, orders: ordersPage };
if (typeof adminPage === 'function') pages.admin = adminPage;   // defined in agristore_admin.js
drawHeader();
if (pages[document.body.dataset.page]) pages[document.body.dataset.page]();
