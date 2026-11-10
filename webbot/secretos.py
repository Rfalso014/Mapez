"""Contraseñas guardadas en el Administrador de credenciales de Windows (vía keyring).

- Las contraseñas NUNCA se escriben en los flujos (JSON), en los registros ni en pantalla:
  los pasos solo guardan «{secreto:nombre}».
- El almacén es inyectable: `usar_almacen(obj)` con un objeto que tenga
  set_password / get_password / delete_password (como el módulo keyring).
  Las pruebas usan `AlmacenMemoria` y nunca tocan el Administrador de credenciales real.
- keyring no puede listar credenciales, así que se guarda además un índice con los
  NOMBRES (nunca los valores) bajo un usuario especial.
"""

import datetime
import hashlib
import json

SERVICIO = "BotWeb"
_INDICE = "__indice__"
_RECHAZO = "__rechazada__:"     # v3.0: huella de una contraseña que la página rechazó (para no volver a enviarla)


class ErrorSecreto(Exception):
    """No se pudo leer o guardar una contraseña."""


class AlmacenMemoria:
    """Almacén en memoria con la misma interfaz que keyring (para pruebas)."""

    def __init__(self):
        self.datos = {}

    def set_password(self, servicio, usuario, clave):
        self.datos[(servicio, usuario)] = clave

    def get_password(self, servicio, usuario):
        return self.datos.get((servicio, usuario))

    def delete_password(self, servicio, usuario):
        if (servicio, usuario) not in self.datos:
            raise KeyError(usuario)
        del self.datos[(servicio, usuario)]


class _AlmacenKeyring:
    """Carga keyring solo cuando hace falta (así las pruebas no lo necesitan)."""

    def _kr(self):
        try:
            import keyring
        except ImportError as e:  # pragma: no cover
            raise ErrorSecreto("Falta el paquete «keyring». Instálalo con: python -m pip install keyring") from e
        return keyring

    def set_password(self, servicio, usuario, clave):
        self._kr().set_password(servicio, usuario, clave)

    def get_password(self, servicio, usuario):
        return self._kr().get_password(servicio, usuario)

    def delete_password(self, servicio, usuario):
        self._kr().delete_password(servicio, usuario)


_almacen = None


def usar_almacen(almacen):
    """Inyecta el almacén a usar (None = volver al Administrador de credenciales real)."""
    global _almacen
    _almacen = almacen


def almacen_actual():
    global _almacen
    if _almacen is None:
        _almacen = _AlmacenKeyring()
    return _almacen


def _leer_indice():
    try:
        bruto = almacen_actual().get_password(SERVICIO, _INDICE)
    except ErrorSecreto:
        raise
    except Exception as e:
        raise ErrorSecreto("No se pudo leer el almacén de contraseñas: %s" % e) from e
    if not bruto:
        return []
    try:
        datos = json.loads(bruto)
        return [str(x) for x in datos]
    except (ValueError, TypeError):
        return []


def _escribir_indice(nombres):
    almacen_actual().set_password(SERVICIO, _INDICE, json.dumps(sorted(set(nombres)), ensure_ascii=False))


def _validar_nombre(nombre):
    if not nombre or not str(nombre).strip():
        raise ErrorSecreto("El nombre de la contraseña no puede estar vacío")
    if str(nombre).strip() == _INDICE or str(nombre).strip().startswith(_RECHAZO):
        raise ErrorSecreto("Nombre reservado")
    return str(nombre).strip()


def guardar(nombre, valor):
    """Guarda (o reemplaza) una contraseña."""
    nombre = _validar_nombre(nombre)
    if valor is None or valor == "":
        raise ErrorSecreto("La contraseña no puede estar vacía")
    try:
        almacen_actual().set_password(SERVICIO, nombre, valor)
        indice = _leer_indice()
        if nombre not in indice:
            _escribir_indice(indice + [nombre])
    except ErrorSecreto:
        raise
    except Exception as e:
        raise ErrorSecreto("No se pudo guardar la contraseña «%s»: %s" % (nombre, type(e).__name__)) from e


def obtener(nombre):
    """Devuelve la contraseña o None si no existe."""
    nombre = _validar_nombre(nombre)
    try:
        return almacen_actual().get_password(SERVICIO, nombre)
    except ErrorSecreto:
        raise
    except Exception as e:
        raise ErrorSecreto("No se pudo leer la contraseña «%s»: %s" % (nombre, type(e).__name__)) from e


def obtener_requerida(nombre):
    """Como `obtener`, pero con un error claro si no existe."""
    valor = obtener(nombre)
    if valor is None:
        raise ErrorSecreto("No existe la contraseña «%s». Guárdala en el botón «Contraseñas»." % nombre)
    return valor


def existe(nombre):
    return obtener(nombre) is not None


def borrar(nombre):
    """Borra una contraseña (no falla si no existía)."""
    nombre = _validar_nombre(nombre)
    try:
        try:
            almacen_actual().delete_password(SERVICIO, nombre)
        except Exception:
            pass  # ya no estaba (PasswordDeleteError, KeyError…)
        indice = [n for n in _leer_indice() if n != nombre]
        _escribir_indice(indice)
    except ErrorSecreto:
        raise
    except Exception as e:
        raise ErrorSecreto("No se pudo borrar la contraseña «%s»: %s" % (nombre, type(e).__name__)) from e


def listar():
    """Nombres de las contraseñas guardadas (sin valores)."""
    return sorted(_leer_indice())


# --- v3.0: contraseñas rechazadas ---------------------------------------------
# Cuando una página rechaza una contraseña guardada, se guarda (en el MISMO almacén de contraseñas, nunca en la base
# de datos) una huella SHA-256 de ese valor.  Mientras la contraseña guardada siga siendo la misma, no se vuelve a
# enviar automáticamente (para no bloquear la cuenta); en cuanto se cambia (Accesos, el cuadro «La contraseña
# falló», Contraseñas sueltas…), la huella ya no coincide y se puede volver a usar.

def _huella(valor):
    return hashlib.sha256(("botweb-rechazo:" + (valor or "")).encode("utf-8", "replace")).hexdigest()


def marcar_rechazada(nombre, cuando=None):
    """Anota que la contraseña guardada como `nombre` fue rechazada.  False si no hay ninguna guardada."""
    nombre = _validar_nombre(nombre)
    valor = obtener(nombre)
    if valor is None:
        return False
    datos = {"huella": _huella(valor), "cuando": (cuando or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M")}
    try:
        almacen_actual().set_password(SERVICIO, _RECHAZO + nombre, json.dumps(datos))
    except Exception as e:
        raise ErrorSecreto("No se pudo anotar la contraseña rechazada «%s»: %s" % (nombre, type(e).__name__)) from e
    return True


def rechazada(nombre):
    """Fecha («AAAA-MM-DD HH:MM») en que se rechazó la contraseña guardada como `nombre`, si sigue siendo la misma;
    None si no fue rechazada o si ya se cambió."""
    try:
        bruto = almacen_actual().get_password(SERVICIO, _RECHAZO + str(nombre))
    except Exception:
        return None
    if not bruto:
        return None
    try:
        datos = json.loads(bruto)
    except ValueError:
        return None
    valor = obtener(nombre)
    if valor is None or datos.get("huella") != _huella(valor):
        return None
    return datos.get("cuando") or "?"


def limpiar_rechazo(nombre):
    try:
        almacen_actual().delete_password(SERVICIO, _RECHAZO + str(nombre))
    except Exception:
        pass
