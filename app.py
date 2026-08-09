import os
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from flask_wtf import CSRFProtect

from database import ensure_db
import logic

ensure_db()

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---- Secret key: ya no hay un valor por defecto silencioso en producción ----
SECRET = os.environ.get("FLASK_SECRET")
if not SECRET:
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError(
            "FLASK_SECRET debe estar definido como variable de entorno en producción. "
            "No se permite arrancar con un valor por defecto."
        )
    SECRET = "dev-only-not-for-production"
    print("Usando FLASK_SECRET de desarrollo. Define la variable de entorno en producción.")
app.secret_key = SECRET

# ---- CSRF en todos los formularios y POST (incluye /api/venta) ----
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.login_view = "login"  # type: ignore
login_manager.init_app(app)


class User(UserMixin):
    """Antes había un objeto User de flask_login Y un diccionario `session`
    con usuario/rol duplicados. Ahora solo existe este objeto: current_user
    es la única fuente de verdad de quién está logueado y a qué empresa
    pertenece."""

    def __init__(self, id, username, rol, empresa_id):
        self.id = id
        self.username = username
        self.rol = rol
        self.empresa_id = empresa_id

    def get_id(self):
        # Empaqueta empresa_id en el id de sesión de flask_login para poder
        # recargar el usuario ya filtrado por tenant en cada request.
        return f"{self.empresa_id}:{self.id}"


@login_manager.user_loader
def load_user(session_id):
    try:
        empresa_id_str, uid_str = session_id.split(":")
        empresa_id, uid = int(empresa_id_str), int(uid_str)
    except (ValueError, AttributeError):
        return None
    data = logic.obtener_usuario_por_id(uid, empresa_id)
    if data:
        return User(data["id"], data["user"], data["rol"], data["empresa_id"])
    return None


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user.rol != "admin":
            flash("Acceso denegado", "danger")
            return redirect(url_for("ventas"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("ventas"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        slug = request.form.get("empresa", "").strip().lower()
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")

        tenant = logic.obtener_tenant_por_slug(slug)
        if not tenant:
            flash("Empresa no encontrada.", "danger")
            return render_template("login.html")

        user_data = logic.validar_usuario(tenant["id"], usuario, password)
        if user_data:
            login_user(User(user_data["id"], user_data["user"], user_data["rol"], user_data["empresa_id"]))
            flash("Inicio de sesión exitoso", "success")
            return redirect(url_for("ventas"))

        flash("Usuario o contraseña incorrectos", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Cerraste sesión", "info")
    return redirect(url_for("login"))


@app.route("/ventas")
@login_required
def ventas():
    productos = [p for p in logic.listar_productos(current_user.empresa_id) if p["stock"] > 0]
    resumen = logic.sales_summary(current_user.empresa_id)
    return render_template("ventas.html", productos=productos, resumen=resumen)


@app.route("/api/productos")
@login_required
def api_productos():
    q = request.args.get("q")
    return {"items": logic.listar_productos(current_user.empresa_id, q)}


@app.route("/api/venta", methods=["POST"])
@login_required
def api_venta():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    try:
        total = logic.registrar_venta(current_user.empresa_id, items)
        return jsonify({"ok": True, "mensaje": f"Venta registrada correctamente. Total: RD$ {total:,.2f}"})
    except logic.VentaError as exc:
        return jsonify({"ok": False, "mensaje": str(exc)}), 400


@app.route("/inventario", methods=["GET", "POST"])
@login_required
@admin_required
def inventario():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        stock = int(request.form.get("stock", 0) or 0)
        precio = float(request.form.get("precio", 0) or 0)
        logic.crear_producto(current_user.empresa_id, nombre, stock, precio)
        flash("Producto creado", "success")
        return redirect(url_for("inventario"))

    q = request.args.get("q", "")
    productos = logic.listar_productos(current_user.empresa_id, q)
    return render_template("inventario.html", productos=productos, q=q)


@app.route("/inventario/<int:pid>/editar", methods=["POST"])
@login_required
@admin_required
def editar_producto(pid):
    nombre = request.form.get("nombre", "").strip()
    stock = int(request.form.get("stock", 0) or 0)
    precio = float(request.form.get("precio", 0) or 0)
    logic.actualizar_producto(current_user.empresa_id, pid, nombre, stock, precio)
    flash("Producto actualizado", "success")
    return redirect(url_for("inventario"))


@app.route("/inventario/<int:pid>/eliminar", methods=["POST"])
@login_required
@admin_required
def eliminar_producto(pid):
    logic.borrar_producto(current_user.empresa_id, pid)
    flash("Producto eliminado", "info")
    return redirect(url_for("inventario"))


@app.route("/reportes")
@login_required
@admin_required
def reportes():
    periodo = request.args.get("periodo", "diario")
    rows = logic.obtener_reporte_detallado(current_user.empresa_id, periodo)
    datos = [{"fecha": r["fecha"], "nombre": r["nombre"], "cantidad": r["cantidad"], "total": r["total"]} for r in rows]
    total = sum(d["total"] for d in datos)
    return render_template("reportes.html", periodo=periodo, datos=datos, total=total)


@app.route("/reporte_pdf")
@login_required
@admin_required
def reporte_pdf():
    periodo = request.args.get("periodo", "diario")
    rows = logic.obtener_reporte_detallado(current_user.empresa_id, periodo)
    datos = [(r["fecha"], r["nombre"], r["cantidad"], r["total"]) for r in rows]
    total = sum(d[3] for d in datos)
    path = logic.exportar_reporte_pdf(current_user.empresa_id, periodo, datos, total)
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route("/cierre")
@login_required
def cierre():
    resumen = logic.sales_summary(current_user.empresa_id)
    bajos = logic.low_stock_products(current_user.empresa_id)
    return render_template(
        "cierre.html", resumen=resumen, bajos=bajos,
        now=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"),
    )


@app.route("/backup", methods=["GET", "POST"])
@login_required
@admin_required
def backup_db():
    path = logic.realizar_backup()
    if not path:
        flash("Base de datos no encontrada", "warning")
        return redirect(url_for("inventario"))
    return send_file(path, as_attachment=True)


# ---------- GESTIÓN DE USUARIOS ----------

@app.route("/admin/usuarios")
@login_required
@admin_required
def admin_usuarios():
    usuarios = logic.listar_usuarios(current_user.empresa_id)
    return render_template("admin_usuarios.html", usuarios=usuarios)


@app.route("/admin/usuario/nuevo", methods=["POST"])
@login_required
@admin_required
def admin_usuario_nuevo():
    user = request.form.get("user")
    password = request.form.get("password")
    rol = request.form.get("rol")
    if user and password and rol:
        logic.crear_usuario(current_user.empresa_id, user, password, rol)
        flash("Usuario creado", "success")
    else:
        flash("Datos incompletos para crear usuario", "danger")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuario/<int:uid>/editar", methods=["POST"])
@login_required
@admin_required
def admin_usuario_editar(uid):
    nuevo_rol = request.form.get("rol")
    if nuevo_rol:
        logic.actualizar_rol_usuario(current_user.empresa_id, uid, nuevo_rol)
        flash("Rol actualizado", "success")
    else:
        flash("Rol no especificado", "danger")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuario/<int:uid>/borrar", methods=["POST"])
@login_required
@admin_required
def admin_usuario_borrar(uid):
    logic.borrar_usuario(current_user.empresa_id, uid)
    flash("Usuario desactivado", "info")
    return redirect(url_for("admin_usuarios"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
