// AgriStore admin page: manage products and orders. The server checks the admin role on every call.
var NEXT = { placed: ['confirmed', 'cancelled'], confirmed: ['processing', 'cancelled'], processing: ['shipped', 'cancelled'], shipped: ['delivered'], delivered: [], cancelled: [] };
var adminCategories = [];
var adminProducts = [];   // the list currently shown, so Edit can find a product by its id

function adminPage() {
  if (!me || me.role !== 'admin') { show('admin', '<p class="empty">This page is for administrators only. <a href="/">Sign in</a></p>'); return; }
  store('/categories').then(function (categories) { adminCategories = categories; loadAdminProducts(); loadAdminOrders(); });
}

function loadAdminProducts() {
  store('/admin/products').then(function (products) {
    adminProducts = products;
    var options = adminCategories.map(function (c) { return '<option value="' + c.id + '">' + esc(c.name) + '</option>'; }).join('');
    var rows = products.map(function (p) {
      return '<tr><td>' + esc(p.name) + '</td><td>' + esc(p.category) + '</td><td>' + rupees(p.price_paise) + '</td><td>' + p.stock + '</td><td>' + (p.is_active ? 'Active' : 'Disabled') +
        '</td><td><button class="btn alt" onclick="editProduct(' + p.id + ')">Edit</button> <button class="btn danger" onclick="deleteProduct(' + p.id + ')">Delete</button></td></tr>';
    }).join('');
    show('admin-products',
      '<div class="panel"><h2 id="form-title">Add a product</h2><br><input type="hidden" id="p-id">' +
      '<div class="grid2"><div class="field"><label for="p-name">Name</label><input id="p-name"></div><div class="field"><label for="p-category">Category</label><select id="p-category">' + options + '</select></div></div>' +
      '<div class="field"><label for="p-desc">Description</label><input id="p-desc"></div>' +
      '<div class="grid2"><div class="field"><label for="p-price">Price (\u20B9)</label><input id="p-price" type="number" step="0.01" min="0"></div><div class="field"><label for="p-stock">Stock</label><input id="p-stock" type="number" min="0"></div></div>' +
      '<div class="field"><label for="p-image">Image URL (e.g. /agristore_frontend/images/tools.svg)</label><input id="p-image"></div>' +
      '<div class="row"><label><input type="checkbox" id="p-points" checked style="width:auto"> AgriPoints discount allowed</label><label><input type="checkbox" id="p-active" checked style="width:auto"> Active (visible in shop)</label></div>' +
      '<div class="error" id="p-error"></div><button class="btn" onclick="saveProduct()">Save product</button> <button class="btn alt" onclick="loadAdminProducts()">Clear form</button></div>' +
      '<div class="panel table-scroll"><table><tr><th>Name</th><th>Category</th><th>Price</th><th>Stock</th><th>Status</th><th></th></tr>' + rows + '</table></div>');
  });
}
function editProduct(id) {
  var p = adminProducts.filter(function (item) { return item.id === id; })[0];
  document.getElementById('form-title').textContent = 'Edit product #' + p.id;
  document.getElementById('p-id').value = p.id; document.getElementById('p-name').value = p.name;
  document.getElementById('p-category').value = p.category_id; document.getElementById('p-desc').value = p.description;
  document.getElementById('p-price').value = p.price_paise / 100; document.getElementById('p-stock').value = p.stock;
  document.getElementById('p-image').value = p.image_url || '';
  document.getElementById('p-points').checked = !!p.points_eligible; document.getElementById('p-active').checked = !!p.is_active;
  window.scrollTo(0, 0);
}
function saveProduct() {
  var id = document.getElementById('p-id').value;
  var data = { name: document.getElementById('p-name').value, category_id: document.getElementById('p-category').value, description: document.getElementById('p-desc').value,
               price: document.getElementById('p-price').value, stock: document.getElementById('p-stock').value, image_url: document.getElementById('p-image').value,
               points_eligible: document.getElementById('p-points').checked, is_active: document.getElementById('p-active').checked };
  store(id ? '/admin/products/' + id : '/admin/products', id ? 'PUT' : 'POST', data)
    .then(function () { toast('Product saved'); loadAdminProducts(); })
    .catch(function (error) { show('p-error', esc(error.message)); });
}
function deleteProduct(id) {
  if (!confirm('Delete this product?')) return;
  store('/admin/products/' + id, 'DELETE').then(function () { toast('Deleted'); loadAdminProducts(); }).catch(function (error) { alert(error.message); });
}

function loadAdminOrders() {
  store('/admin/orders').then(function (orders) {
    if (!orders.length) { show('admin-orders', '<p class="empty">No orders yet.</p>'); return; }
    show('admin-orders', '<div class="panel table-scroll"><table><tr><th>Order</th><th>Customer</th><th>Items</th><th>Points used</th><th>Total</th><th>Status</th></tr>' + orders.map(function (o) {
      var choices = NEXT[o.status].map(function (s) { return '<option value="' + s + '">' + s + '</option>'; }).join('');
      var items = o.items.map(function (i) { return esc(i.product_name) + ' \u00D7 ' + i.quantity; }).join('<br>');
      return '<tr><td>' + esc(o.order_number) + '<br><span class="muted small">' + esc(o.created_at.slice(0, 10)) + '</span></td><td>' + esc(o.customer_name) + '<br><span class="muted small">' + esc(o.phone) + '<br>' + esc(o.address) + ', ' + esc(o.city) + ' ' + esc(o.pin_code) + '</span></td><td>' + items + '</td>' +
        '<td>' + o.points_redeemed + ' (' + rupees(o.discount_paise) + ')</td><td>' + rupees(o.total_paise) + '</td><td><span class="status ' + o.status + '">' + o.status + '</span>' +
        (choices ? '<br><select id="s-' + o.id + '" style="width:auto;margin:.3rem 0">' + choices + '</select><button class="btn alt" onclick="setOrderStatus(' + o.id + ')">Update</button>' : '') + '</td></tr>';
    }).join('') + '</table></div>');
  });
}
function setOrderStatus(id) {
  store('/admin/orders/' + id + '/status', 'PUT', { status: document.getElementById('s-' + id).value })
    .then(function () { toast('Order updated'); loadAdminOrders(); }).catch(function (error) { alert(error.message); });
}
