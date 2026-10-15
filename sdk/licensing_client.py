"""SDK de licencias para apps Python/Flask.

Un solo archivo. Dependencias: pynacl (verificación Ed25519) y requests (HTTP).

Uso mínimo con Flask:

    from licensing_client import LicenseClient, init_flask

    lic = LicenseClient(
        server_url="https://licencias.tudominio.com",
        product="mi-app",
        public_key="<clave pública de `python cli.py init`>",
        storage_path="/var/lib/mi-app/license.json",
    )
    init_flask(app, lic)                 # bloquea la app si no hay licencia válida

    @app.route("/exportar")
    @lic.requires_feature("export")      # además exige una feature concreta
    def exportar(): ...
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
import base64


class LicenseError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class NetworkError(Exception):
    """No se pudo contactar al servidor (distinto de que el servidor rechace la licencia)."""


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class LicenseClient:
    CLOCK_SKEW = 300  # segundos de tolerancia al comparar relojes

    def __init__(self, server_url: str, product: str, public_key: str,
                 license_key: str | None = None, storage_path: str = "license.json",
                 http=None, timeout: float = 8.0, refresh_before_days: float = 2.0,
                 clock: Callable[[], float] = time.time):
        self.server_url = server_url.rstrip("/")
        self.product = product
        self.public_key = public_key
        self.storage = Path(storage_path)
        self.timeout = timeout
        self.refresh_before = refresh_before_days * 86400
        self.clock = clock
        self._license_key = license_key or os.getenv("LICENSE_KEY")
        self._http = http  # cualquier objeto con .post(url, json=, timeout=) (requests, httpx…)
        self._cache: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ huella de máquina
    def fingerprint(self) -> str:
        """Hash estable de la máquina, ligado al producto (no sirve para otro producto)."""
        parts = []
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                parts.append(Path(path).read_text().strip())
                break
            except OSError:
                continue
        if not parts:
            parts.append(str(uuid.getnode()))
        parts += [platform.system(), platform.machine()]
        return hashlib.sha256(("|".join(parts) + "|" + self.product).encode()).hexdigest()

    # ------------------------------------------------------------ almacenamiento local
    def _load(self) -> dict:
        try:
            return json.loads(self.storage.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.storage.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.storage)

    # ------------------------------------------------------------ red
    def _post(self, path: str, body: dict) -> dict:
        http = self._http
        if http is None:
            import requests
            http = requests
        try:
            resp = http.post(f"{self.server_url}{path}", json=body, timeout=self.timeout)
        except Exception as exc:  # errores de conexión, DNS, timeout…
            raise NetworkError(str(exc)) from exc
        if resp.status_code >= 500:
            raise NetworkError(f"servidor respondió {resp.status_code}")
        data = resp.json()
        if resp.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            if err:
                raise LicenseError(err["code"], err["message"])
            raise LicenseError("server_error", f"Respuesta inesperada ({resp.status_code})")
        return data

    # ------------------------------------------------------------ verificación offline
    def _verify(self, token: str, fresh: bool = False) -> dict:
        """`fresh=True`: el token acaba de llegar del servidor; si la firma no cuadra, lo más
        probable es que la clave pública configurada sea otra (no que alguien lo editara)."""
        try:
            verify_key = VerifyKey(_b64d(self.public_key))
        except Exception:  # base64 roto o longitud distinta de 32 bytes
            raise LicenseError("invalid_public_key",
                               "La clave pública configurada no tiene un formato válido")
        try:
            body, sig = token.split(".")
            verify_key.verify(body.encode(), _b64d(sig))
            payload = json.loads(_b64d(body))
        except BadSignatureError:
            if not fresh:
                raise LicenseError("invalid_token", "El token de licencia no es válido")
            raise LicenseError("bad_signature",
                               "La firma del token no coincide con la clave pública configurada "
                               "(¿clave pública equivocada o servidor de licencias distinto?)")
        except ValueError:
            raise LicenseError("invalid_token", "El token de licencia no es válido")
        if payload.get("product") != self.product:
            raise LicenseError("product_mismatch", "La licencia es de otro producto")
        if payload.get("fp") != self.fingerprint():
            raise LicenseError("fingerprint_mismatch",
                               "La licencia está activada en otra máquina")
        return payload

    def _check_clock(self, data: dict) -> None:
        """Detecta que retrocedan el reloj para alargar un token vencido."""
        now = self.clock()
        high = data.get("high_water", 0)
        if now < high - self.CLOCK_SKEW:
            raise LicenseError("clock_tampered", "El reloj del sistema es inconsistente")
        data["high_water"] = max(high, now)

    # ------------------------------------------------------------ API pública
    def activate(self, license_key: str | None = None) -> dict:
        """Activa esta instalación con la clave (requiere internet). Guarda el token."""
        key = license_key or self._license_key
        if not key:
            raise LicenseError("no_key", "Falta la clave de licencia")
        out = self._post("/v1/activate", {
            "license_key": key, "product": self.product,
            "fingerprint": self.fingerprint(), "hostname": socket.gethostname(),
            "two_phase": True})
        try:
            payload = self._verify(out["token"], fresh=True)
        except LicenseError as exc:
            # El servidor dejó la activación PENDIENTE. Como no podemos usar el token (clave
            # pública mal configurada, producto distinto…) avisamos: el servidor la registra
            # como fallida y libera el cupo.
            self._abort_quietly(key, exc.code)
            raise
        # Token verificado: el servidor la registra como exitosa. Si esto falla, el token no
        # se guarda (el servidor cerraría la activación pendiente de todos modos).
        self._post("/v1/activate/confirm", {"license_key": key, "fingerprint": self.fingerprint()})
        data = {"license_key": key, "token": out["token"], "high_water": self.clock()}
        self._save(data)
        self._license_key = key
        self._cache = None
        return payload

    def _abort_quietly(self, key: str, reason: str) -> None:
        try:
            self._post("/v1/activate/abort", {"license_key": key, "reason": reason,
                                              "fingerprint": self.fingerprint()})
        except (LicenseError, NetworkError):
            pass  # mejor esfuerzo: si no llega, el servidor cierra la pendiente a los 5 min

    def refresh(self) -> dict:
        """Pide un token nuevo al servidor. Si el servidor rechaza la licencia, se borra el token."""
        data = self._load()
        key = data.get("license_key") or self._license_key
        if not key:
            raise LicenseError("not_activated", "Esta instalación no está activada")
        try:
            out = self._post("/v1/validate", {
                "license_key": key, "product": self.product,
                "fingerprint": self.fingerprint()})
        except LicenseError:
            data.pop("token", None)  # revocada / expirada / no activada: ya no sirve
            self._save(data)
            self._cache = None
            raise
        payload = self._verify(out["token"], fresh=True)
        data.update(token=out["token"], license_key=key)
        self._check_clock(data)
        self._save(data)
        self._cache = None
        return payload

    def check(self, allow_refresh: bool = True) -> dict:
        """Devuelve el payload verificado o lanza LicenseError.

        Funciona sin internet mientras el token no haya expirado. Si está por expirar
        intenta renovarlo; si no hay red, sigue con el token actual hasta su vencimiento.
        """
        with self._lock:
            data = self._load()
            token = data.get("token")
            if not token:
                raise LicenseError("not_activated", "Esta instalación no está activada")
            payload = self._verify(token)
            self._check_clock(data)
            self._save(data)
            remaining = payload["exp"] - self.clock()

            if allow_refresh and remaining < self.refresh_before:
                try:
                    return self.refresh()
                except NetworkError:
                    pass  # sin red: nos quedamos con el token actual si aún sirve
            if remaining <= -self.CLOCK_SKEW:
                raise LicenseError(
                    "offline_grace_expired",
                    "No se pudo validar la licencia con el servidor. Conéctate a internet.")
            return payload

    def is_valid(self) -> bool:
        try:
            self.check()
            return True
        except (LicenseError, NetworkError):
            return False

    def has_feature(self, name: str) -> bool:
        try:
            return name in self.check(allow_refresh=False).get("features", [])
        except LicenseError:
            return False

    def deactivate(self) -> None:
        """Libera esta instalación en el servidor (para moverla a otra máquina)."""
        data = self._load()
        key = data.get("license_key") or self._license_key
        if key:
            self._post("/v1/deactivate", {"license_key": key, "fingerprint": self.fingerprint()})
        self.storage.unlink(missing_ok=True)
        self._cache = None

    # ------------------------------------------------------------ Flask
    def cached_check(self, ttl: float = 60.0) -> dict:
        """check() con caché corta, para llamarlo en cada petición sin leer disco siempre."""
        now = time.monotonic()
        cached = self._cache
        if cached and now - cached[0] < ttl:
            return cached[1]
        payload = self.check(allow_refresh=False)
        self._cache = (now, payload)
        return payload

    def requires_feature(self, feature: str):
        """Decorador de ruta: exige licencia válida y que incluya `feature`."""
        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                from flask import jsonify
                try:
                    payload = self.cached_check()
                except LicenseError as exc:
                    return jsonify(error=exc.code, message=exc.message), 403
                if feature not in payload.get("features", []):
                    return jsonify(error="feature_not_licensed",
                                   message=f"Tu plan no incluye '{feature}'"), 403
                return fn(*args, **kwargs)
            return wrapper
        return deco

    def start_background_refresh(self, every_hours: float = 6.0) -> threading.Thread:
        """Hilo demonio que renueva el token periódicamente (así las peticiones nunca esperan a la red)."""
        def loop():
            while True:
                try:
                    self.check(allow_refresh=True)
                except (LicenseError, NetworkError):
                    pass
                time.sleep(every_hours * 3600)
        t = threading.Thread(target=loop, name="license-refresh", daemon=True)
        t.start()
        return t


def init_flask(app, client: LicenseClient, exempt: tuple[str, ...] = ("static",),
               exempt_prefixes: tuple[str, ...] = ("/health", "/license"),
               background_refresh: bool = True) -> None:
    """Bloquea toda la app (HTTP 403) si no hay licencia válida.

    Registra también POST /license/activate para activar desde un formulario o curl:
        curl -X POST localhost:5000/license/activate -d '{"license_key":"XXXXX-..."}' \\
             -H 'Content-Type: application/json'
    """
    from flask import jsonify, request

    @app.route("/license/activate", methods=["POST"])
    def _license_activate():
        key = (request.get_json(silent=True) or {}).get("license_key")
        try:
            payload = client.activate(key)
        except LicenseError as exc:
            return jsonify(error=exc.code, message=exc.message), 400
        except NetworkError:
            return jsonify(error="network", message="No se pudo contactar al servidor de licencias"), 503
        return jsonify(ok=True, plan=payload["plan"], features=payload["features"])

    @app.route("/license/status")
    def _license_status():
        try:
            p = client.cached_check()
        except LicenseError as exc:
            return jsonify(valid=False, error=exc.code, message=exc.message), 403
        return jsonify(valid=True, plan=p["plan"], features=p["features"],
                       license_expires=p["lic_exp"], token_expires=p["exp"])

    @app.before_request
    def _enforce_license():
        if request.endpoint in exempt or any(request.path.startswith(p) for p in exempt_prefixes):
            return None
        try:
            client.cached_check()
        except LicenseError as exc:
            return jsonify(error=exc.code, message=exc.message), 403
        return None

    if background_refresh:
        client.start_background_refresh()
