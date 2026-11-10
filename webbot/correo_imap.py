"""v3.4 «Correo»: cualquier buzón por IMAP (Gmail, Outlook/Microsoft 365 si la empresa lo permite, otros).

Adaptado del cliente IMAP de Octopus (`email/imap_client.py`): conexión SSL (puerto 993) o normal, `UID SEARCH` con lo
que el servidor sabe filtrar (SINCE/BEFORE, FROM, SUBJECT) y el resto se comprueba aquí; los correos se leen con
`BODY.PEEK[…]`, que NO los marca como leídos, y la carpeta se abre en solo lectura.

La contraseña está en el Administrador de credenciales de Windows (`secretos`, nombre «correo_imap:<id de la cuenta>»),
nunca en la base de datos ni en los registros.  Gmail no admite la contraseña normal por IMAP: hace falta una
«contraseña de aplicación» (Cuenta de Google → Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones).
"""

import email
import email.policy
import imaplib
import os
import re
import ssl

from . import correo, secretos
from .correo import ErrorProveedor, ErrorSesion

TIMEOUT_S = 30


def _texto_cabecera(valor):
    return re.sub(r"\s+", " ", str(valor or "")).strip()


class AdaptadorImap:
    def __init__(self, cuenta, log=None, clave=None):
        self.cuenta = cuenta
        self._log_fn = log
        self._clave = clave
        self.con = None
        self._mensajes = {}           # uid -> email.message (el último abierto, para descargar sus adjuntos)
        self.uidvalidity = ""

    def log(self, linea):
        if self._log_fn:
            try:
                self._log_fn(linea)
            except Exception:          # noqa: BLE001
                pass

    # ----------------------------------------------------------------- conectar
    def __enter__(self):
        c = self.cuenta
        clave = self._clave
        if clave is None:
            try:
                clave = secretos.obtener(correo.secreto_de_cuenta(c["id"]))
            except secretos.ErrorSecreto as e:
                raise ErrorProveedor(str(e))
        if not clave:
            raise ErrorSesion("Falta la contraseña IMAP de «%s»: escríbela en Correo → la cuenta → «Cambiar…» (en Gmail, "
                              "una contraseña de aplicación)." % c.get("nombre", ""))
        host, puerto = c.get("host"), int(c.get("puerto") or (993 if c.get("ssl", True) else 143))
        self.log("Conectando a %s:%d (IMAP%s)…" % (host, puerto, " con SSL" if c.get("ssl", True) else ""))
        try:
            if c.get("ssl", True):
                self.con = imaplib.IMAP4_SSL(host, puerto, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_S)
            else:
                self.con = imaplib.IMAP4(host, puerto, timeout=TIMEOUT_S)
        except (OSError, imaplib.IMAP4.error) as e:
            raise ErrorProveedor("No se pudo conectar a %s:%d: %s" % (host, puerto, e))
        try:
            self.con.login(c.get("usuario") or c.get("direccion"), clave)
        except imaplib.IMAP4.error as e:
            self._cerrar()
            raise ErrorSesion("El servidor IMAP rechazó el usuario o la contraseña de «%s» (%s). En Gmail hace falta una "
                              "«contraseña de aplicación»; cámbiala en Correo → la cuenta." % (c.get("nombre", ""),
                                                                                             _texto_cabecera(e)[:120]))
        carpeta = c.get("carpeta") or "INBOX"
        try:
            ok, datos = self.con.select(self._carpeta_imap(carpeta), readonly=True)
        except imaplib.IMAP4.error as e:
            ok, datos = "NO", [str(e).encode()]
        if ok != "OK":
            self._cerrar()
            raise ErrorProveedor("No existe la carpeta «%s» en el buzón" % carpeta)
        try:
            r = self.con.response("UIDVALIDITY")
            self.uidvalidity = (r[1][0].decode() if r and r[1] and r[1][0] else "")
        except Exception:              # noqa: BLE001
            self.uidvalidity = ""
        return self

    @staticmethod
    def _carpeta_imap(nombre):
        return nombre if re.fullmatch(r"[\w.\-/]+", nombre) else '"%s"' % nombre.replace('"', "")

    def _cerrar(self):
        if self.con is None:
            return
        try:
            try:
                self.con.close()
            except imaplib.IMAP4.error:
                pass
            self.con.logout()
        except Exception:              # noqa: BLE001
            pass
        self.con = None

    def __exit__(self, *exc):
        self._cerrar()
        return False

    # ----------------------------------------------------------------- buscar
    def buscar(self, criterios, hoy=None, limite=30):
        crit = correo.criterios_imap(criterios, hoy)
        try:
            ok, datos = self.con.uid("SEARCH", None, *crit)
        except imaplib.IMAP4.error as e:
            raise ErrorProveedor("El servidor IMAP no aceptó la búsqueda (%s): %s" % (" ".join(crit), e))
        if ok != "OK":
            raise ErrorProveedor("El servidor IMAP no aceptó la búsqueda: %s" % datos)
        uids = (datos[0].decode("ascii", "replace").split() if datos and datos[0] else [])
        uids = uids[-max(limite, 1):][::-1]           # los más recientes primero
        self.log("IMAP: %d correo(s) con %s (se miran los %d más recientes)" % (len(uids) if datos else 0,
                                                                                " ".join(crit), len(uids)))
        res = []
        for uid in uids:
            try:
                ok, d = self.con.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID CONTENT-TYPE)])")
            except imaplib.IMAP4.error as e:
                self.log("  no se pudo leer el correo %s: %s" % (uid, e))
                continue
            cab = b""
            for parte in d or []:
                if isinstance(parte, tuple) and len(parte) > 1 and isinstance(parte[1], bytes):
                    cab = parte[1]
            msg = email.message_from_bytes(cab, policy=email.policy.default)
            mid = _texto_cabecera(msg.get("Message-ID"))
            tipo = (msg.get_content_type() or "").lower()
            res.append({"id": ("imap:" + mid) if mid else "imap:uid:%s:%s" % (self.uidvalidity, uid), "_uid": uid,
                        "asunto": _texto_cabecera(msg.get("Subject")), "remitente": _texto_cabecera(msg.get("From")),
                        "remitente_correo": correo.correo_de(msg.get("From")),
                        "fecha": correo.leer_fecha(msg.get("Date")), "adjuntos": None,
                        "tiene_adjuntos": False if tipo.startswith("text/") else None, "texto": ""})
        return res

    # ----------------------------------------------------------------- abrir y descargar
    def abrir(self, m):
        uid = m["_uid"]
        try:
            ok, d = self.con.uid("FETCH", uid, "(BODY.PEEK[])")
        except imaplib.IMAP4.error as e:
            raise ErrorProveedor("No se pudo leer el correo: %s" % e)
        crudo = b""
        for parte in d or []:
            if isinstance(parte, tuple) and len(parte) > 1 and isinstance(parte[1], bytes):
                crudo = parte[1]
        if not crudo:
            raise ErrorProveedor("El servidor IMAP no devolvió el correo")
        msg = email.message_from_bytes(crudo, policy=email.policy.default)
        self._mensajes = {uid: msg}
        html, texto = "", ""
        cuerpo = msg.get_body(preferencelist=("html",))
        if cuerpo is not None:
            html = cuerpo.get_content()
        cuerpo = msg.get_body(preferencelist=("plain",))
        if cuerpo is not None:
            texto = cuerpo.get_content()
        if not texto and html:
            texto = correo.html_a_texto(html)
        adjuntos = []
        for parte in self._partes_adjuntas(msg):
            datos = parte.get_payload(decode=True) or b""
            adjuntos.append({"nombre": parte.get_filename(), "tamano": "%d B" % len(datos)})
        return {"asunto": _texto_cabecera(msg.get("Subject")), "remitente": _texto_cabecera(msg.get("From")),
                "remitente_correo": correo.correo_de(msg.get("From")), "fecha": correo.leer_fecha(msg.get("Date")),
                "html": html, "texto": texto, "adjuntos": adjuntos}

    @staticmethod
    def _partes_adjuntas(msg):
        return [p for p in msg.walk() if not p.is_multipart() and p.get_filename()
                and (p.get_content_disposition() in ("attachment", "inline", None))]

    def descargar(self, m, det, nombres, carpeta):
        msg = self._mensajes.get(m["_uid"])
        if msg is None:
            self.abrir(m)
            msg = self._mensajes.get(m["_uid"])
        res = {}
        for parte in self._partes_adjuntas(msg):
            n = parte.get_filename()
            if n in nombres and n not in res:
                destino = correo._ruta_libre(os.path.join(carpeta, correo._limpio(n) or "adjunto"))
                with open(destino, "wb") as f:
                    f.write(parte.get_payload(decode=True) or b"")
                res[n] = destino
        return res


def probar_conexion(cuenta, clave=None):
    """«Probar conexión»: entra, abre la carpeta y sale.  Devuelve un texto o lanza ErrorSesion/ErrorProveedor."""
    with AdaptadorImap(cuenta, clave=clave) as a:
        ok, datos = a.con.uid("SEARCH", None, "ALL")
        n = len(datos[0].split()) if ok == "OK" and datos and datos[0] else 0
        return "Conexión correcta: la carpeta «%s» tiene %d correo(s)" % (cuenta.get("carpeta") or "INBOX", n)
