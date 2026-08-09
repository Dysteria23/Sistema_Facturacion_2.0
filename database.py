import sqlite3
import os

DB_NAME = os.path.join(os.path.dirname(__file__), "sistema_facturacion.db")


def conectar():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db():
    conn = conectar()
    cur = conn.cursor()

    # Una fila por cliente
    cur.execute("""CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT UNIQUE NOT NULL,
                    nombre TEXT NOT NULL,
                    rnc TEXT,
                    plan TEXT NOT NULL DEFAULT 'basico',
                    activo INTEGER NOT NULL DEFAULT 1,
                    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    # Todas las tablas de negocio id 
    cur.execute("""CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    empresa_id INTEGER NOT NULL REFERENCES tenants(id),
                    user TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    rol TEXT NOT NULL,
                    activo INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(empresa_id, user))""")

    cur.execute("""CREATE TABLE IF NOT EXISTS productos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    empresa_id INTEGER NOT NULL REFERENCES tenants(id),
                    nombre TEXT NOT NULL,
                    stock INTEGER NOT NULL DEFAULT 0,
                    precio REAL NOT NULL DEFAULT 0,
                    activo INTEGER NOT NULL DEFAULT 1)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_productos_empresa_nombre ON productos(empresa_id, nombre)")

    cur.execute("""CREATE TABLE IF NOT EXISTS ventas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    empresa_id INTEGER NOT NULL REFERENCES tenants(id),
                    producto_id INTEGER NOT NULL REFERENCES productos(id),
                    cantidad INTEGER NOT NULL,
                    total REAL NOT NULL,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ventas_empresa_fecha ON ventas(empresa_id, fecha)")

    conn.commit()
    conn.close()


def seed_demo_data():
    """Crea un tenant y un admin de demo, SOLO si la base está completamente
    vacía (instalación nueva de desarrollo). Si ya tienes datos de un cliente
    real, usa migrate_to_multitenant.py en vez de esto."""
    from auth import hash_password

    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tenants")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO tenants (slug, nombre, plan) VALUES (?,?,?)", ("demo", "Empresa Demo", "pro"))
        empresa_id = cur.lastrowid
        cur.execute(
            "INSERT INTO usuarios (empresa_id, user, password_hash, rol) VALUES (?,?,?,?)",
            (empresa_id, "admin", hash_password("cambiar123"), "admin"),
        )
        conn.commit()
        print("Tenant demo creado -> slug: demo | usuario: admin | contraseña: cambiar123 (cámbiala)")
    conn.close()


def ensure_db():
    """Idempotente: si la base no existe, la crea desde cero con datos demo.
    Si ya existe (tu base actual con datos reales), solo crea las tablas que
    falten y NO toca nada existente — para migrar datos reales usa
    migrate_to_multitenant.py."""
    existe = os.path.exists(DB_NAME)
    inicializar_db()
    if not existe:
        seed_demo_data()
