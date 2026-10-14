#!/bin/sh
set -e

KEY_FILE="${LICENSE_PRIVATE_KEY_FILE:-/data/private.key}"


# La llave privada se crea SOLO si no existe (regenerarla invalidaría todos los tokens).
if [ ! -f "$KEY_FILE" ]; then
    echo ">>> Generando llave privada en $KEY_FILE"
    python -m app.cli init
    echo ">>> Copia la clave PÚBLICA de arriba; también está en GET /v1/public-key"
fi

exec "$@"