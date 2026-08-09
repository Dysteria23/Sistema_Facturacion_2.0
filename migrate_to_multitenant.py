"""
Migra tu base de datos actual (single-tenant, contraseñas en texto plano)
al nuevo esquema multi-tenant con contraseñas hasheadas.

Uso:
    python migrate_to_multitenant.py

Qué hace, en orden:
1. Renombra tus tablas actuales (usuarios, productos, ventas) a *_legacy.
2. Crea el nuevo esquema (tenants + empresa_id en cada tabla).
3. Crea UN tenant para tu cliente actual (te pregunta nombre y slug).
4. Copia usuarios re-hasheando sus contraseñas de texto plano a hash seguro.
5. Copia productos y el historial completo de ventas, respetando los ids
   nuevos de producto.
6. NO borra las tablas *_legacy — quedan como respaldo. Bórralas a mano
   cuando confirmes que la app funciona correctamente con el nuevo esquema.

Es seguro correrlo una sola vez: si detecta que el esquema multi-tenant
ya existe, no hace nada.
"""
import sys

from database import conectar, inicializar_db
from auth import hash_password


def main():
    conn = conectar()
    cur = conn.cursor()

    tablas = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    if "tenants" in tablas:
        print("El esquema multi-tenant ya existe. No hay nada que migrar.")
        conn.close()
        return

    if "usuarios" not in tablas:
        print("No se encontró una tabla 'usuarios' con el esquema anterior. Nada que migrar.")
        conn.close()
        return

    nombre_empresa = input("Nombre de la empresa/cliente actual: ").strip()
    slug = input("Slug corto para el login (ej. 'acme', sin espacios ni mayúsculas): ").strip().lower()
    if not nombre_empresa or not slug:
        print("El nombre y el slug son obligatorios. Abortando sin tocar nada.")
        sys.exit(1)

    print("Renombrando tablas actuales a *_legacy (no se borra nada)...")
    cur.execute("ALTER TABLE usuarios RENAME TO usuarios_legacy")
    cur.execute("ALTER TABLE productos RENAME TO productos_legacy")
    cur.execute("ALTER TABLE ventas RENAME TO ventas_legacy")
    conn.commit()
    conn.close()

    print("Creando el nuevo esquema multi-tenant...")
    inicializar_db()

    conn = conectar()
    cur = conn.cursor()

    cur.execute("INSERT INTO tenants (slug, nombre, plan) VALUES (?,?,?)", (slug, nombre_empresa, "pro"))
    empresa_id = cur.lastrowid

    print("Migrando usuarios (las contraseñas se re-hashean, no se guardan en texto plano)...")
    usuarios_legacy = cur.execute("SELECT user, password, rol FROM usuarios_legacy").fetchall()
    for user, password_plano, rol in usuarios_legacy:
        cur.execute(
            "INSERT INTO usuarios (empresa_id, user, password_hash, rol) VALUES (?,?,?,?)",
            (empresa_id, user, hash_password(password_plano), rol),
        )

    print("Migrando productos...")
    id_map = {}
    productos_legacy = cur.execute("SELECT id, nombre, stock, precio FROM productos_legacy").fetchall()
    for old_id, nombre, stock, precio in productos_legacy:
        cur.execute(
            "INSERT INTO productos (empresa_id, nombre, stock, precio) VALUES (?,?,?,?)",
            (empresa_id, nombre, stock, precio),
        )
        id_map[old_id] = cur.lastrowid

    print("Migrando historial de ventas...")
    omitidas = 0
    ventas_legacy = cur.execute("SELECT producto_id, cantidad, total, fecha FROM ventas_legacy").fetchall()
    for old_pid, cantidad, total, fecha in ventas_legacy:
        nuevo_pid = id_map.get(old_pid)
        if nuevo_pid is None:
            omitidas += 1
            continue
        cur.execute(
            "INSERT INTO ventas (empresa_id, producto_id, cantidad, total, fecha) VALUES (?,?,?,?,?)",
            (empresa_id, nuevo_pid, cantidad, total, fecha),
        )

    conn.commit()
    conn.close()

    print(f"\nMigración completa. Empresa '{nombre_empresa}' creada con slug '{slug}'.")
    print(f"  Usuarios migrados: {len(usuarios_legacy)}")
    print(f"  Productos migrados: {len(productos_legacy)}")
    print(f"  Ventas migradas: {len(ventas_legacy) - omitidas} (omitidas por producto huérfano: {omitidas})")
    print("\nInicia sesión con el slug de empresa + tus usuarios y contraseñas de siempre.")
    print("Las tablas *_legacy quedaron como respaldo — bórralas manualmente cuando confirmes que todo funciona.")


if __name__ == "__main__":
    main()
