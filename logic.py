
import os
import sqlite3
import shutil
from datetime import datetime, timezone

from database import conectar, DB_NAME
from auth import hash_password, verify_password


class VentaError(Exception):
    """Error de negocio al registrar una venta (carrito vacío, stock
    insuficiente, producto inexistente). Se muestra tal cual al usuario,
    así que el mensaje siempre va en español y sin detalles internos."""
    pass


# ---------------------------------------------------------------- Tenants --

def obtener_tenant_por_slug(slug):
    if not slug:
        return None
    conn = conectar()
    row = conn.execute(
        "SELECT * FROM tenants WHERE slug = ? AND activo = 1", (slug,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# --------------------------------------------------------------- Usuarios --

def validar_usuario(empresa_id, usuario, password):

    if not usuario or not password:
        return None
    conn = conectar()
    row = conn.execute(
        "SELECT * FROM usuarios WHERE empresa_id = ? AND user = ? AND activo = 1",
        (empresa_id, usuario),
    ).fetchone()
    conn.close()
    if row and verify_password(password, row["password_hash"]):
        return dict(row)
    return None


def obtener_usuario_por_id(uid, empresa_id):
    conn = conectar()
    row = conn.execute(
        "SELECT * FROM usuarios WHERE id = ? AND empresa_id = ? AND activo = 1",
        (uid, empresa_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def listar_usuarios(empresa_id):
    conn = conectar()
    rows = conn.execute(
        "SELECT id, user, rol FROM usuarios WHERE empresa_id = ? AND activo = 1 ORDER BY user",
        (empresa_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_usuario(empresa_id, user, password, rol):
    user = (user or "").strip()
    rol = rol if rol in ("admin", "cajero") else "cajero"
    conn = conectar()
    try:
        existente = conn.execute(
            "SELECT id FROM usuarios WHERE empresa_id = ? AND user = ?",
            (empresa_id, user),
        ).fetchone()
        if existente:
            # Ya existe (activo o desactivado antes): se reactiva con la
            # nueva contraseña y rol en vez de romper por la restricción
            # UNIQUE(empresa_id, user).
            conn.execute(
                "UPDATE usuarios SET password_hash = ?, rol = ?, activo = 1 WHERE id = ?",
                (hash_password(password), rol, existente["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO usuarios (empresa_id, user, password_hash, rol) VALUES (?,?,?,?)",
                (empresa_id, user, hash_password(password), rol),
            )
        conn.commit()
    finally:
        conn.close()


def actualizar_rol_usuario(empresa_id, uid, nuevo_rol):
    if nuevo_rol not in ("admin", "cajero"):
        return
    conn = conectar()
    conn.execute(
        "UPDATE usuarios SET rol = ? WHERE id = ? AND empresa_id = ?",
        (nuevo_rol, uid, empresa_id),
    )
    conn.commit()
    conn.close()


def borrar_usuario(empresa_id, uid):
    """Desactiva (no borra físicamente, para no romper el historial de
    ventas ni auditoría). Protección: nunca desactiva al último admin
    activo de la empresa, o la cuenta quedaría sin nadie que administre."""
    conn = conectar()
    fila = conn.execute(
        "SELECT rol FROM usuarios WHERE id = ? AND empresa_id = ? AND activo = 1",
        (uid, empresa_id),
    ).fetchone()
    if not fila:
        conn.close()
        return
    if fila["rol"] == "admin":
        admins_activos = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE empresa_id = ? AND rol = 'admin' AND activo = 1",
            (empresa_id,),
        ).fetchone()[0]
        if admins_activos <= 1:
            conn.close()
            return  # no dejar la empresa sin administrador
    conn.execute(
        "UPDATE usuarios SET activo = 0 WHERE id = ? AND empresa_id = ?",
        (uid, empresa_id),
    )
    conn.commit()
    conn.close()


# -------------------------------------------------------------- Productos --

def listar_productos(empresa_id, q=None):
    conn = conectar()
    if q:
        rows = conn.execute(
            "SELECT * FROM productos WHERE empresa_id = ? AND activo = 1 "
            "AND nombre LIKE ? ORDER BY nombre",
            (empresa_id, f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM productos WHERE empresa_id = ? AND activo = 1 ORDER BY nombre",
            (empresa_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_producto(empresa_id, nombre, stock, precio):
    nombre = (nombre or "").strip()
    if not nombre:
        return
    stock = max(0, int(stock))
    precio = max(0.0, float(precio))
    conn = conectar()
    existente = conn.execute(
        "SELECT id, stock FROM productos WHERE empresa_id = ? AND activo = 1 AND lower(nombre) = lower(?)",
        (empresa_id, nombre),
    ).fetchone()
    if existente:
        # "Si el nombre ya existe, el stock se sumará" (ver inventario.html)
        conn.execute(
            "UPDATE productos SET stock = stock + ?, precio = ? WHERE id = ?",
            (stock, precio, existente["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO productos (empresa_id, nombre, stock, precio) VALUES (?,?,?,?)",
            (empresa_id, nombre, stock, precio),
        )
    conn.commit()
    conn.close()


def actualizar_producto(empresa_id, pid, nombre, stock, precio):
    nombre = (nombre or "").strip()
    stock = max(0, int(stock))
    precio = max(0.0, float(precio))
    conn = conectar()
    conn.execute(
        "UPDATE productos SET nombre = ?, stock = ?, precio = ? WHERE id = ? AND empresa_id = ?",
        (nombre, stock, precio, pid, empresa_id),
    )
    conn.commit()
    conn.close()


def borrar_producto(empresa_id, pid):
    """Desactiva en vez de borrar: `ventas.producto_id` referencia esta fila
    (FK), así que un DELETE físico rompería el historial de ventas ya
    registradas para ese producto."""
    conn = conectar()
    conn.execute(
        "UPDATE productos SET activo = 0 WHERE id = ? AND empresa_id = ?",
        (pid, empresa_id),
    )
    conn.commit()
    conn.close()


def low_stock_products(empresa_id, umbral=10):
    conn = conectar()
    rows = conn.execute(
        "SELECT nombre, stock FROM productos WHERE empresa_id = ? AND activo = 1 "
        "AND stock <= ? ORDER BY stock ASC",
        (empresa_id, umbral),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ Venta --

def registrar_venta(empresa_id, items):
    """Registra una venta con uno o más productos, valida stock y calcula
    el total dentro de una sola transacción: o se descuenta todo el stock y
    se insertan todas las líneas, o no se toca nada. `items` es una lista de
    dicts con 'id' y 'cantidad', como los arma el carrito en ventas.html."""
    if not items:
        raise VentaError("El carrito está vacío.")

    # Combina líneas repetidas del mismo producto antes de validar stock,
    # para no rechazar por error un carrito con el mismo producto agregado
    # dos veces por separado.
    cantidades = {}
    for item in items:
        try:
            pid = int(item.get("id"))
            cantidad = int(item.get("cantidad", 0))
        except (TypeError, ValueError):
            raise VentaError("Producto o cantidad inválida en el carrito.")
        if cantidad <= 0:
            raise VentaError("La cantidad debe ser mayor que cero.")
        cantidades[pid] = cantidades.get(pid, 0) + cantidad

    conn = conectar()
    total = 0.0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for pid, cantidad in cantidades.items():
            row = conn.execute(
                "SELECT * FROM productos WHERE id = ? AND empresa_id = ? AND activo = 1",
                (pid, empresa_id),
            ).fetchone()
            if not row:
                raise VentaError("Uno de los productos ya no está disponible.")
            if row["stock"] < cantidad:
                raise VentaError(
                    f"Stock insuficiente para \"{row['nombre']}\". Disponible: {row['stock']}."
                )
            subtotal = round(row["precio"] * cantidad, 2)
            conn.execute(
                "UPDATE productos SET stock = stock - ? WHERE id = ?", (cantidad, pid)
            )
            conn.execute(
                "INSERT INTO ventas (empresa_id, producto_id, cantidad, total) VALUES (?,?,?,?)",
                (empresa_id, pid, cantidad, subtotal),
            )
            total += subtotal
        conn.commit()
    except VentaError:
        conn.rollback()
        raise
    except sqlite3.Error:
        conn.rollback()
        raise VentaError("No se pudo registrar la venta. Intenta de nuevo.")
    finally:
        conn.close()
    return round(total, 2)


def sales_summary(empresa_id):
    conn = conectar()
    row = conn.execute(
        "SELECT COALESCE(SUM(total), 0) AS total, COUNT(*) AS operaciones "
        "FROM ventas WHERE empresa_id = ? AND date(fecha) = date('now')",
        (empresa_id,),
    ).fetchone()
    conn.close()
    return {"total": row["total"] or 0.0, "operaciones": row["operaciones"] or 0}


# --------------------------------------------------------------- Reportes --

_PERIODO_SQL = {
    "diario": "date(v.fecha) = date('now')",
    "semanal": "date(v.fecha) >= date('now', '-6 days')",
    "mensual": "date(v.fecha) >= date('now', 'start of month')",
    "anual": "date(v.fecha) >= date('now', 'start of year')",
}


def obtener_reporte_detallado(empresa_id, periodo):
    condicion = _PERIODO_SQL.get(periodo, _PERIODO_SQL["diario"])
    conn = conectar()
    rows = conn.execute(
        f"""SELECT strftime('%d/%m/%Y %H:%M', v.fecha) AS fecha,
                   p.nombre AS nombre, v.cantidad AS cantidad, v.total AS total
            FROM ventas v
            JOIN productos p ON p.id = v.producto_id
            WHERE v.empresa_id = ? AND {condicion}
            ORDER BY v.fecha DESC""",
        (empresa_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def exportar_reporte_pdf(empresa_id, periodo, datos, total):
    """Genera un PDF simple del reporte con reportlab y devuelve la ruta al
    archivo temporal generado (app.py lo envía con send_file)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm

    out_dir = os.path.join(os.path.dirname(__file__), "reportes_generados")
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    path = os.path.join(out_dir, f"reporte_{periodo}_{empresa_id}_{timestamp}.pdf")

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=letter)
    elementos = [
        Paragraph("Farmacia Pérez — Reporte de ventas", styles["Title"]),
        Paragraph(f"Período: {periodo.title()}", styles["Normal"]),
        Spacer(1, 0.5 * cm),
    ]

    tabla_datos = [["Fecha y hora", "Producto", "Cantidad", "Total"]]
    for d in datos:
        tabla_datos.append([d[0], d[1], str(d[2]), f"RD$ {d[3]:,.2f}"])
    if len(tabla_datos) == 1:
        tabla_datos.append(["—", "Sin ventas en este período", "—", "—"])

    tabla = Table(tabla_datos, colWidths=[4.2 * cm, 6 * cm, 2.5 * cm, 3 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4d3a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f1ea")]),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 0.5 * cm))
    elementos.append(Paragraph(f"<b>Total del período: RD$ {total:,.2f}</b>", styles["Normal"]))

    doc.build(elementos)
    return path


# --------------------------------------------------------------- Respaldo --

def realizar_backup():
    if not os.path.exists(DB_NAME):
        return None
    out_dir = os.path.join(os.path.dirname(__file__), "backups")
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    destino = os.path.join(out_dir, f"sistema_facturacion_{timestamp}.db")
    shutil.copyfile(DB_NAME, destino)
    return destino
