// Farmacia Pérez — comportamiento del cliente.
// Nada aquí decide precios ni stock: solo arma el payload que /api/venta
// valida de verdad en el servidor (logic.registrar_venta). El carrito en
// pantalla es una vista optimista, no la fuente de la verdad.
(function () {
  "use strict";

  const money = (n) => "RD$ " + Number(n).toLocaleString("es-DO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // ---------------------------------------------------------- Carrito --
  let cart = {}; // { [id]: { id, nombre, precio, stock, cantidad } }

  window.addProduct = function (id, nombre, precio, stock) {
    if (stock <= 0) return;
    const existing = cart[id];
    if (existing) {
      if (existing.cantidad >= stock) return; // no exceder el stock visible
      existing.cantidad += 1;
    } else {
      cart[id] = { id, nombre, precio, stock, cantidad: 1 };
    }
    renderCart();
  };

  function changeQty(id, delta) {
    const item = cart[id];
    if (!item) return;
    item.cantidad += delta;
    if (item.cantidad <= 0 || item.cantidad > item.stock) {
      if (item.cantidad <= 0) delete cart[id];
      else item.cantidad = item.stock;
    }
    renderCart();
  }

  function removeItem(id) {
    delete cart[id];
    renderCart();
  }

  window.clearCart = function () {
    cart = {};
    renderCart();
  };

  function renderCart() {
    const cartEl = document.getElementById("cart");
    const countEl = document.getElementById("cartCount");
    const totalEl = document.getElementById("total");
    const payButton = document.getElementById("payButton");
    if (!cartEl) return;

    const items = Object.values(cart);
    if (items.length === 0) {
      cartEl.innerHTML = '<div class="empty">Tu carrito está vacío.<small>Agrega productos desde el catálogo.</small></div>';
      if (payButton) payButton.disabled = true;
    } else {
      cartEl.innerHTML = items.map((it) => {
        const lineTotal = it.precio * it.cantidad;
        return `
          <div class="cart-item" data-id="${it.id}">
            <div class="cart-item-info">
              <b>${escapeHtml(it.nombre)}</b>
              <small>${money(it.precio)} c/u</small>
            </div>
            <div class="qty-controls">
              <button type="button" data-action="dec">−</button>
              <span>${it.cantidad}</span>
              <button type="button" data-action="inc">+</button>
            </div>
            <div class="line-total">${money(lineTotal)}</div>
            <button type="button" class="remove-item" data-action="remove" title="Quitar">×</button>
          </div>`;
      }).join("");
      if (payButton) payButton.disabled = false;
    }

    const totalUnidades = items.reduce((sum, it) => sum + it.cantidad, 0);
    if (countEl) countEl.textContent = `${totalUnidades} producto${totalUnidades === 1 ? "" : "s"} agregado${totalUnidades === 1 ? "" : "s"}`;

    const totalPagar = items.reduce((sum, it) => sum + it.precio * it.cantidad, 0);
    if (totalEl) totalEl.textContent = money(totalPagar);
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const itemEl = btn.closest(".cart-item");
    if (!itemEl) return;
    const id = itemEl.getAttribute("data-id");
    if (btn.dataset.action === "inc") changeQty(id, 1);
    else if (btn.dataset.action === "dec") changeQty(id, -1);
    else if (btn.dataset.action === "remove") removeItem(id);
  });

  window.pay = function () {
    const items = Object.values(cart);
    if (items.length === 0) return;
    const payButton = document.getElementById("payButton");
    if (payButton) payButton.disabled = true;

    fetch("/api/venta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: items.map((it) => ({ id: it.id, cantidad: it.cantidad })),
      }),
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (ok && data.ok) {
          showToast(data.mensaje || "Venta registrada correctamente.", "success");
          cart = {};
          renderCart();
          setTimeout(() => window.location.reload(), 900);
        } else {
          showToast(data.mensaje || "No se pudo registrar la venta.", "danger");
          if (payButton) payButton.disabled = false;
        }
      })
      .catch(() => {
        showToast("Error de conexión. Intenta de nuevo.", "danger");
        if (payButton) payButton.disabled = false;
      });
  };

  function showToast(message, category) {
    const main = document.querySelector(".content") || document.body;
    const toast = document.createElement("div");
    toast.className = `toast ${category}`;
    toast.textContent = message;
    main.insertBefore(toast, main.firstChild);
    setTimeout(() => toast.remove(), 4000);
  }

  // -------------------------------------------------- Buscador (ventas) --
  const productSearch = document.getElementById("productSearch");
  if (productSearch) {
    productSearch.addEventListener("input", function () {
      const q = this.value.trim().toLowerCase();
      document.querySelectorAll("#productList .product").forEach((el) => {
        const name = el.getAttribute("data-name") || "";
        el.classList.toggle("hidden-by-search", q.length > 0 && !name.includes(q));
      });
    });
  }

  // --------------------------------------------------- Login: contraseña --
  window.togglePassword = function () {
    const input = document.getElementById("password");
    if (!input) return;
    input.type = input.type === "password" ? "text" : "password";
  };

  // -------------------------------------------------- Modal de producto --
  const productModal = document.getElementById("productModal");
  const productForm = document.getElementById("productForm");
  const productModalTitle = document.getElementById("productModalTitle");
  const productModalAction = document.getElementById("productModalAction");
  const productName = document.getElementById("productName");
  const productStock = document.getElementById("productStock");
  const productPrice = document.getElementById("productPrice");
  const newProductButton = document.getElementById("newProductButton");

  function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove("hidden");
  }

  window.closeModal = function (id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.add("hidden");
  };

  if (newProductButton && productForm) {
    newProductButton.addEventListener("click", function () {
      productForm.reset();
      productForm.action = window.location.pathname; // POST /inventario -> crear
      productModalTitle.textContent = "Nuevo producto";
      productModalAction.textContent = "Guardar";
      openModal("productModal");
    });
  }

  document.querySelectorAll(".edit-product").forEach((btn) => {
    btn.addEventListener("click", function () {
      const { id, name, stock, price } = this.dataset;
      productName.value = name;
      productStock.value = stock;
      productPrice.value = price;
      productForm.action = `${window.location.pathname.replace(/\/$/, "")}/${id}/editar`.replace("//", "/");
      productModalTitle.textContent = "Editar producto";
      productModalAction.textContent = "Actualizar";
      openModal("productModal");
    });
  });

  if (productModal) {
    productModal.addEventListener("click", function (e) {
      if (e.target === productModal) closeModal("productModal");
    });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && productModal && !productModal.classList.contains("hidden")) {
      closeModal("productModal");
    }
  });

  // --------------------------------------------------- Cierre de caja --
  window.copyClose = function () {
    const textarea = document.getElementById("closeText");
    if (!textarea) return;
    const text = textarea.value;
    const done = () => showToast("Resumen copiado. Pégalo en WhatsApp.", "success");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(textarea, done));
    } else {
      fallbackCopy(textarea, done);
    }
  };

  function fallbackCopy(textarea, done) {
    textarea.hidden = false;
    textarea.select();
    try {
      document.execCommand("copy");
      done();
    } catch (e) {
      showToast("No se pudo copiar automáticamente. Selecciona el texto manualmente.", "warning");
    } finally {
      textarea.hidden = true;
    }
  }

  // ----------------------------------------------------- Tema oscuro --
  const themeToggle = document.getElementById("themeToggle");
  const STORAGE_KEY = "farmacia-perez-theme";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    if (themeToggle) themeToggle.checked = theme === "dark";
  }

  const savedTheme = localStorage.getItem(STORAGE_KEY) ||
    (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(savedTheme);

  if (themeToggle) {
    themeToggle.addEventListener("change", function () {
      const theme = this.checked ? "dark" : "light";
      applyTheme(theme);
      localStorage.setItem(STORAGE_KEY, theme);
    });
  }

  // Toasts que ya vienen renderizados por el servidor (flash messages) se
  // quedan un rato y luego se desvanecen solos, igual que los nuevos.
  document.querySelectorAll(".toast").forEach((toast) => {
    setTimeout(() => toast.remove(), 5000);
  });
})();
