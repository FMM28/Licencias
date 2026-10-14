import os
import sys
from pathlib import Path

from app.core import crypto
from app.core.config import get_settings


def cmd_init(args):
    path = Path(get_settings().private_key_file)
    if path.exists() and not args.force:
        sys.exit(f"Ya existe {path}. Usa --force para sobrescribirla "
                 "(¡invalida todos los tokens emitidos!).")
    path.parent.mkdir(parents=True, exist_ok=True)
    private, public = crypto.generate_keypair()
    path.write_text(private + "\n")
    os.chmod(path, 0o600)
    print(f"Clave privada guardada en {path} (permisos 600). NO la subas a git.")
    print("\nClave pública (incrústala en tu SDK / app):\n")
    print(f"  {public}\n")


def register(sub):
    s = sub.add_parser("init", help="genera el par de llaves Ed25519")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)
