"""Servidor local del sitio de prueba (http.server en un puerto libre).

Uso desde las pruebas:   with ServidorPrueba() as srv: srv.url_base
Uso manual:              python tests/servidor_prueba.py [segundos_de_vida]
                         (imprime la URL y se apaga solo pasado ese tiempo)
"""

import datetime
import functools
import io
import json
import http.server
import os
import re
import sys
import threading
import time
import unicodedata
import zipfile

SITIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sitio_prueba")
CORTE_NUEVO = "45 - 2026 (16/10/2026 - 22/10/2026)"


def cortes_portal(reporte, nuevo=False):
    """Cortes semanales de la página tipo Portal (del más antiguo al más reciente): «33 - 2026 (…)» … «44 - 2026 (…)»,
    y «45 - 2026 (…)» si llegó el corte nuevo.  Otro reporte tiene cortes mensuales."""
    if reporte == "Resumen de Ventas":
        return ["Agosto 2026", "Septiembre 2026"] + (["Octubre 2026"] if nuevo else [])
    if not reporte:
        return []
    fin = datetime.date(2026, 10, 9)          # inicio del corte 44
    res = []
    for n in range(33, 46 if nuevo else 45):
        ini = fin + datetime.timedelta(days=7 * (n - 44))
        res.append("%d - 2026 (%s - %s)" % (n, ini.strftime("%d/%m/%Y"), (ini + datetime.timedelta(days=6)).strftime("%d/%m/%Y")))
    return res


# ---------------------------------------------------------------- v3.4: buzón de prueba (Outlook / Gmail)
DIAS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DIAS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"]


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t or ""))
    return re.sub(r"[^0-9a-z]+", "", "".join(c for c in t if not unicodedata.combining(c)).lower())


def fecha_outlook(d):
    """Como la escribe Outlook en inglés en el title de la fila: «Thu 10/29/2026 9:07 AM»."""
    h12 = d.hour % 12 or 12
    return "%s %d/%d/%d %d:%02d %s" % (DIAS_EN[d.weekday()], d.month, d.day, d.year, h12, d.minute,
                                       "AM" if d.hour < 12 else "PM")


def fecha_gmail(d):
    """Como la escribe Gmail en español en el title: «jue, 29 oct 2026, 9:07»."""
    return "%s, %d %s %d, %d:%02d" % (DIAS_ES[d.weekday()], d.day, MESES_ES[d.month - 1], d.year, d.hour, d.minute)


def _zip(archivos):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, datos in archivos:
            z.writestr(n, datos)
    return b.getvalue()


def correos_prueba(hoy=None):
    """Los correos del buzón de prueba (fechas relativas a hoy, para que «los últimos 7 días» funcione cualquier día).
    Nombres y direcciones INVENTADOS."""
    hoy = hoy or datetime.date.today()
    dia = lambda n, h, m: datetime.datetime.combine(hoy - datetime.timedelta(days=n), datetime.time(h, m))  # noqa: E731
    adjunto = "SUPERVISION VENTAS EJEMPLO V1.4.xlsx"
    tabla = ("<table><tr><td><table><tr><th>Producto</th><th>Cantidad</th><th>Importe</th></tr>"
             "<tr><td>Plan Básico</td><td>12</td><td>1,200.50</td></tr><tr><td>Plan Plus</td><td>3</td><td>34</td></tr>"
             "</table></td></tr></table>")
    return [
        {"id": "m1", "de_nombre": "Reportes Ventas", "de_correo": "reportes@ejemplo.com",
         "asunto": "RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S. AL %s" % dia(0, 9, 7).strftime("%d/%m/%Y"),
         "fecha": dia(0, 9, 7), "html": "<p>Buenos días,</p><p>Total ventas: 1.234</p><p>Clientes nuevos:&nbsp;15</p>" + tabla,
         "adjuntos": [(adjunto, b"xlsx-de-hoy"), ("Otro reporte.csv", b"a;b\n1;2\n")]},
        {"id": "m2", "de_nombre": "Reportes Ventas", "de_correo": "reportes@ejemplo.com",
         "asunto": "RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S. AL %s" % dia(1, 15, 30).strftime("%d/%m/%Y"),
         "fecha": dia(1, 15, 30), "html": "<div>Total ventas: 987</div><div>Clientes nuevos: 4</div>",
         "adjuntos": [(adjunto, b"xlsx-de-ayer")]},
        {"id": "m3", "de_nombre": "Boletín", "de_correo": "noticias@ejemplo.org", "asunto": "Novedades de la semana",
         "fecha": dia(0, 8, 0), "html": "<p>Nada de ventas por aquí.</p>", "adjuntos": []},
        {"id": "m4", "de_nombre": "Reportes Ventas", "de_correo": "reportes@ejemplo.com",
         "asunto": "RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S. AL %s" % dia(10, 9, 0).strftime("%d/%m/%Y"),
         "fecha": dia(10, 9, 0), "html": "<p>Total ventas: 555</p>",
         "adjuntos": [("paquete.zip", _zip([(adjunto, b"xlsx-del-zip"), ("leeme.txt", b"hola")]))]},
        {"id": "m5", "de_nombre": "Cobros", "de_correo": "cobros@ejemplo.com", "asunto": "Estado de cuenta",
         "fecha": dia(2, 11, 15), "html": "<p>Saldo pendiente: 3.400,00 DOP</p><p>Fecha límite: 05/11/2026</p>",
         "adjuntos": [("estado.pdf", b"%PDF-1.4 prueba")]},
    ]


def _texto_html(h):
    return re.sub(r"<[^>]+>", " ", (h or "").replace("&nbsp;", " "))


def _coincide_outlook(m, q):
    todo = _norm(" ".join([m["de_nombre"], m["de_correo"], m["asunto"], _texto_html(m["html"])]))
    return all(_norm(p) in todo for p in q.split() if _norm(p))


def _coincide_gmail(m, q):
    """Operadores de Gmail (los que usa el bot): subject:(…) from:(…) after: before: has:attachment filename: "…" y
    {a b} (cualquiera de)."""
    def uno(clave, valor):
        v = _norm(valor)
        if clave == "subject":
            return v in _norm(m["asunto"])
        if clave == "from":
            return v in _norm(m["de_nombre"] + " " + m["de_correo"])
        if clave in ("after", "before"):
            d = datetime.datetime.strptime(valor, "%Y/%m/%d").date()
            return m["fecha"].date() >= d if clave == "after" else m["fecha"].date() < d
        if clave == "has":
            return bool(m["adjuntos"]) if valor == "attachment" else True
        if clave == "filename":
            return any(v in _norm(n) for n, _d in m["adjuntos"])
        if clave == "in":
            return True
        return v in _norm(" ".join([m["asunto"], m["de_nombre"], m["de_correo"], _texto_html(m["html"])]))
    for grupo in re.findall(r"\{([^}]*)\}", q):
        if not any(uno(*t.split(":", 1)) for t in grupo.split() if ":" in t):
            return False
    q = re.sub(r"\{[^}]*\}", " ", q)
    for clave, par, simple, frase, palabra in re.findall(r'(\w+):(?:\(([^)]*)\)|("[^"]*"|\S+))|"([^"]*)"|(\S+)', q):
        if clave:
            if not uno(clave, par if par else simple.strip('"')):
                return False
        elif not uno("", frase or palabra):
            return False
    return True


def _resumen_correo(m):
    return {"id": m["id"], "de_nombre": m["de_nombre"], "de_correo": m["de_correo"], "asunto": m["asunto"],
            "fecha_outlook": fecha_outlook(m["fecha"]), "fecha_gmail": fecha_gmail(m["fecha"]),
            "corta": m["fecha"].strftime("%H:%M"), "vista": _texto_html(m["html"])[:80].strip(),
            "adjuntos": [n for n, _d in m["adjuntos"]]}


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def _json(self, datos, cabeceras=None, cuerpo=None, tipo="application/json"):
        cuerpo = cuerpo if cuerpo is not None else json.dumps(datos, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (cabeceras or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(cuerpo)
        except ConnectionError:
            pass

    def _portal(self, ruta, q):
        """Página tipo Portal: cortes por reporte (con un corte nuevo si `estado["nuevo_corte"]`) y descarga."""
        estado = self.server.estado
        if ruta == "/api/portal/cortes":
            return self._json({"cortes": cortes_portal(q.get("reporte", [""])[0], estado.get("nuevo_corte"))})
        if ruta == "/api/portal/estado":
            if "nuevo" in q:
                estado["nuevo_corte"] = q["nuevo"][0] == "1"
            return self._json({"nuevo_corte": bool(estado.get("nuevo_corte")), "descargas": estado["descargas"]})
        if ruta == "/api/portal/descarga":
            corte = q.get("corte", [""])[0]
            formato = q.get("formato", ["xlsx"])[0]
            estado["descargas"].append(corte)
            numero = corte.split(" ")[0] if corte else "x"
            cuerpo = ("reporte;corte\n%s;%s\n" % (q.get("reporte", [""])[0], corte)).encode("utf-8")
            return self._json(None, {"Content-Disposition": 'attachment; filename="Portal_%s.%s"' % (numero, formato)},
                              cuerpo=cuerpo, tipo="application/octet-stream")
        return self._json({"error": "no existe"})

    def _correo(self, ruta, q):
        """v3.4: buzón de prueba.  `estado["correo_login"]` = la sesión caducó (las páginas enseñan el inicio de
        sesión); `estado["correos_extra"]` = correos que «llegan» durante la prueba."""
        from urllib.parse import quote
        estado = self.server.estado
        lista = sorted(correos_prueba() + list(estado.get("correos_extra") or []), key=lambda m: m["fecha"], reverse=True)
        por_id = {m["id"]: m for m in lista}
        v = lambda k: q.get(k, [""])[0]  # noqa: E731
        if ruta == "/api/correo/entrar":
            estado["correo_login"] = False
            return self._json({"ok": True})
        if ruta == "/api/correo/salir":
            estado["correo_login"] = True
            return self._json({"ok": True})
        if estado.get("correo_login"):
            return self._json({"login": True})
        if ruta == "/api/correo/lista":
            estado.setdefault("correo_busquedas", []).append(v("q"))
            filtro = _coincide_gmail if v("modo") == "gmail" else _coincide_outlook
            return self._json({"mensajes": [_resumen_correo(m) for m in lista if filtro(m, v("q"))]})
        m = por_id.get(v("id"))
        if m is None:
            return self._json({"error": "no existe"})
        if ruta == "/api/correo/mensaje":
            d = _resumen_correo(m)
            d.update(html=m["html"], adjuntos=[{"nombre": n, "tamano": "%d KB" % max(1, len(datos) // 1024),
                                                "url": "/api/correo/adjunto?id=%s&n=%d" % (m["id"], i)}
                                               for i, (n, datos) in enumerate(m["adjuntos"])])
            return self._json(d)
        if ruta == "/api/correo/adjunto":
            n, datos = m["adjuntos"][int(v("n") or 0)]
            estado.setdefault("correo_descargas", []).append(n)
            return self._json(None, {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(n)}, cuerpo=datos,
                              tipo="application/octet-stream")
        if ruta == "/api/correo/todo":
            estado.setdefault("correo_descargas", []).append("(todo) " + m["id"])
            return self._json(None, {"Content-Disposition": 'attachment; filename="Adjuntos.zip"'},
                              cuerpo=_zip(m["adjuntos"]), tipo="application/zip")
        return self._json({"error": "no existe"})

    def do_GET(self):
        # /api/lento?ms=N  responde tras N ms (petición lenta);  /api/ping  responde enseguida (sondeos)
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        if u.path.startswith("/api/portal/"):
            return self._portal(u.path, parse_qs(u.query))
        if u.path.startswith("/api/correo/"):
            return self._correo(u.path, parse_qs(u.query))
        if u.path == "/api/erp/descarga":               # v3.2: página tipo ERP (menú «Vista Exportar» → «Exportar»)
            q = parse_qs(u.query)
            almacen, fecha = q.get("almacen", [""])[0], q.get("fecha", [""])[0]
            self.server.estado["descargas"].append("ERP %s %s" % (almacen, fecha))
            cuerpo = ("almacen;fecha\n%s;%s\n" % (almacen, fecha)).encode("utf-8")
            return self._json(None, {"Content-Disposition": 'attachment; filename="existencias.csv"'}, cuerpo=cuerpo,
                              tipo="application/octet-stream")
        if u.path.startswith("/api/"):
            ms = 0
            if u.path == "/api/lento":
                try:
                    ms = int(parse_qs(u.query).get("ms", ["2000"])[0])
                except ValueError:
                    ms = 2000
            time.sleep(min(ms, 20000) / 1000.0)
            cuerpo = b'{"ok": true}'
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(cuerpo)
            except ConnectionError:
                pass
            return
        super().do_GET()

    def handle(self):
        try:
            super().handle()
        except ConnectionError:      # el navegador cortó la conexión (p. ej. al pedir favicon.ico): no es un error
            pass


class ServidorPrueba:
    def __init__(self, carpeta=SITIO):
        manejador = functools.partial(_Silencioso, directory=carpeta)
        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manejador)   # puerto 0 = uno libre
        self._srv.estado = {"nuevo_corte": False, "descargas": []}
        self.estado = self._srv.estado
        self.puerto = self._srv.server_address[1]
        self.url_base = "http://127.0.0.1:%d/" % self.puerto
        self._hilo = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def iniciar(self):
        self._hilo.start()
        return self

    def parar(self):
        self._srv.shutdown()
        self._srv.server_close()

    def __enter__(self):
        return self.iniciar()

    def __exit__(self, *exc):
        self.parar()


if __name__ == "__main__":
    vida = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    with ServidorPrueba() as s:
        print(s.url_base, flush=True)
        time.sleep(vida)
