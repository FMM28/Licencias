from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Nombres explícitos y estables para índices y claves: sin esto cada servidor inventa los suyos
# y las migraciones futuras (DROP CONSTRAINT) se vuelven un dolor.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Opciones de tabla de MariaDB. Hay que declararlas con los dos
# prefijos: con una URL `mariadb+pymysql` SQLAlchemy usa el dialecto "mariadb", que solo lee
# `mariadb_*`; con `mysql+pymysql` usa "mysql" y solo lee `mysql_*`. Si falta el prefijo, la
# opción se ignora EN SILENCIO y la tabla hereda el motor/charset por defecto del servidor
# (MyISAM no tiene bloqueo de filas ni claves foráneas: el límite de instalaciones dejaría
# de estar protegido contra peticiones simultáneas).
_TABLE_OPTIONS = {"engine": "InnoDB", "charset": "utf8mb4", "collate": "utf8mb4_unicode_ci"}
MYSQL_TABLE_ARGS = {f"{dialect}_{name}": value
                    for dialect in ("mysql", "mariadb") for name, value in _TABLE_OPTIONS.items()}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
