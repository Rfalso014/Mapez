"""Ejecutor: reproduce un flujo en el navegador (visible u oculto).

- Antes de cada acción espera a que el elemento exista, sea visible y esté habilitado.
- Los pasos de descarga esperan (hasta `timeout_descarga`) a que el botón esté disponible y a que llegue el archivo.
- Mientras espera mucho rato avisa cada ~15 s en el registro y en la barra de estado de la ventana.
- Resuelve plantillas y contraseñas justo al ejecutar el paso.
- Paso opcional que falla: se anota y se continúa.  Paso obligatorio que falla:
  captura de pantalla + registro y se detiene.
- Escribe un registro por ejecución con cada paso y su duración.  Las contraseñas
  nunca llegan al registro, a la consola ni a los mensajes de error.
- «Pasar el ratón» (pasar_raton): pone el ratón encima de un elemento para abrir su menú.
- Recuperación automática (opción `recuperacion_automatica`): si el elemento de un clic no se ve tras
  ~2 s, intenta una vez abrir el menú o la lista que lo contiene (ver `_recuperar`).
- «Escribir»: si el campo ya tiene el valor, no hace nada; en listas con autocompletar elige la opción.
- Esperas de carga (v2.3, opción `esperar_carga`): tras cada acción y antes de buscar el elemento siguiente
  espera a que no haya peticiones pendientes ni indicadores de carga (ruedas, «Cargando…», ASP.NET…); ver
  `_esperar_carga`.  Las esperas «hasta que aparezca» no se dan por buenas con lo que ya estaba antes.
- Inicio de sesión (v2.3): paso «iniciar_sesion» (se omite si ya hay sesión) y guardia en todos los pasos (si la
  página pide iniciar sesión, se entra y se repite el paso).  Si faltan datos o los rechazan se piden con
  `pedir_acceso(solicitud, esperar)`; sin él (sin ventana) el paso falla con un mensaje claro.

Hilos: debe ejecutarse entero en un solo hilo (el que llama a `ejecutar()`).  `pedir_acceso` también se llama
desde ese hilo; la ventana contesta por su cola (ver bot.App._pedir_acceso).
"""

import csv
import datetime
import html
import os
import re
import time

from . import accesos as mod_accesos
from . import flujo as mod_flujo
from . import navegador as mod_navegador
from . import plantillas, secretos

TIMEOUT_OPCIONAL = mod_flujo.TIMEOUT_OPCIONAL   # segundos que se espera un paso opcional sin timeout propio
SONDEO = 0.15
AVISO_CADA = 15.0       # segundos entre avisos «esperando…»
MAX_CANDIDATOS = 50
ESPERA_RECUPERACION = 2.0     # segundos sin ver el elemento antes de intentar abrir su menú
ESPERA_BLOQUEADO = 3.0        # escribir: segundos con el campo visible pero «no disponible» antes de forzar
TIPOS_CON_RECUPERACION = ("clic", "descargar", "marcar", "pasar_raton")

# Esperas de carga (ver Ejecutor._esperar_carga)
ESPERA_RED_MAX = 30.0         # tope de las esperas «cortas» (peticiones pendientes, página abriéndose)
RED_MAX_EDAD = 15.0           # una petición pendiente más antigua no cuenta (conexiones largas, sondeos)
QUIETUD_RED = 0.5             # segundos sin peticiones para dar la red por tranquila
ESPERA_ESTANCADA = 30.0       # indicador visible sin peticiones ni cambios en la página: se da por atascado
ESPERA_ESTANCADA_DEBIL = 3.0  # lo mismo para lo que no es claramente una rueda de carga (capas, «busy»…)
TIPOS_RED_IGNORADOS = ("websocket", "eventsource", "media", "manifest", "texttrack", "ping")
RX_RED_IGNORAR = re.compile(
    r"google-analytics|googletagmanager|doubleclick|hotjar|clarity\.ms|facebook\.(com|net)|connect\.facebook|"
    r"segment\.(io|com)|mixpanel|newrelic|nr-data|sentry|datadoghq|fullstory|intercom|zendesk|/collect\b|"
    r"longpoll|long-poll|/poll(ing)?\b|signalr|socket\.io|sockjs|heartbeat|keep-?alive|comet|__webpack_hmr|"
    r"livereload|browser-sync", re.IGNORECASE)
SONDEO_REPETIDO = 3           # la misma dirección pedida 3 veces en 10 s = la página consulta periódicamente

# Inicio de sesión
ESPERA_LOGIN = 3.0            # segundos sin ver el elemento de un paso antes de mirar si la página pide iniciar sesión
ESPERA_LOGIN_TRAS_ABRIR = 1.5  # lo mismo, en el paso justo después de «Abrir la página»
MAX_INTENTOS_LOGIN = mod_accesos.MAX_INTENTOS_POR_SITIO
TIPOS_ESPERA = ("esperar_elemento", "esperar_texto", "esperar_segundos")

# Elemento bloqueado: deshabilitado, aria-disabled, clase «disabled» o sin eventos de ratón.
JS_BLOQUEADO = r"""el => {
  const cercano = el.closest('button, a, input, select, textarea, [role=button], [role=menuitem], [role=option], [role=tab]') || el;
  const clase = (n) => (typeof n.className === 'string' ? n.className : (n.getAttribute && n.getAttribute('class')) || '');
  for (const n of [el, cercano, cercano.parentElement]) {
    if (!n || n.nodeType !== 1) continue;
    if (n.matches && n.matches(':disabled')) return true;
    if (n.getAttribute('aria-disabled') === 'true') return true;
    if (/(^|\s)([\w-]*[-_])?disabled(\s|$)/i.test(clase(n))) return true;
  }
  return getComputedStyle(cercano).pointerEvents === 'none';
}"""

# Elemento dentro de una ventanita emergente (calendario, menú, diálogo…)
JS_EN_POPUP = r"""el => {
  const rx = /popup|popover|dropdown|datepicker|daterangepicker|calendar|picker|modal|overlay|menu|tooltip|listbox/i;
  for (let n = el; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    const rol = n.getAttribute('role');
    if (rol && /dialog|menu|listbox|tooltip/.test(rol)) return true;
    const pos = getComputedStyle(n).position;
    if (pos === 'fixed' || pos === 'absolute') {
      if (n.parentElement === document.body) return true;
      const c = typeof n.className === 'string' ? n.className : '';
      if (rx.test(c)) return true;
    }
  }
  return false;
}"""

JS_SOLO_LECTURA = "e => !!(e.readOnly || (e.hasAttribute && e.hasAttribute('readonly')))"

JS_PONER_VALOR = r"""(el, v) => {
  if (el.isContentEditable && !('value' in el)) { el.innerText = v; }
  else {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const d = Object.getOwnPropertyDescriptor(proto, 'value');
    if (d && d.set) d.set.call(el, v); else el.value = v;
  }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  if (document.activeElement === el && el.blur) el.blur(); else el.dispatchEvent(new Event('blur'));
}"""

JS_LEER_VALOR = "e => ('value' in e && e.value !== undefined && !e.isContentEditable) ? e.value : (e.innerText || '')"
# v3.8: estado de una casilla dibujada (DevExpress ASPxCheckBox: un <span> con clase …Checked/…Unchecked y un <input>
# oculto «…_S» con C/U; o role=checkbox con aria-checked).  null si no se sabe.
JS_CASILLA_MARCADA = r"""e => {
  const c = (typeof e.className === 'string' ? e.className : (e.getAttribute('class') || ''));
  if (e.hasAttribute('aria-checked')) return e.getAttribute('aria-checked') === 'true';
  if ('checked' in e && (e.type === 'checkbox' || e.type === 'radio')) return !!e.checked;
  if (/Unchecked/i.test(c)) return false;
  if (/Checked/i.test(c)) return true;
  const i = e.querySelector && e.querySelector('input');
  if (i && /^[CU]$/i.test(i.value || '')) return /^c$/i.test(i.value);
  return null;
}"""
# v3.8: calendario de DevExpress (ASPxDateEdit, p. ej. «Fecha Desde» del ERP): la fecha de verdad la guarda el control
# (…_State, rawValue) y su máscara devuelve al campo esa fecha al salir de él, así que escribir el texto no basta: se
# pone con su API (SetDate), como al elegir un día en su calendario.  null si el campo no es uno de estos calendarios.
JS_DX_PONER_FECHA = r"""(el, f) => {
  const w = el.ownerDocument.defaultView;
  const id = String(el.id || '').replace(/_I$/, '');
  if (!id || id === el.id) return null;
  let c = null;
  try {
    const col = w.ASPxClientControl && w.ASPxClientControl.GetControlCollection && w.ASPxClientControl.GetControlCollection();
    c = col && (typeof col.GetByName === 'function' ? col.GetByName(id) : (typeof col.Get === 'function' ? col.Get(id) : null));
  } catch (e) { c = null; }
  if (!c) { try { c = w[id] || null; } catch (e) { c = null; } }
  if (!c) {      // con otro ClientInstanceName: el control cuyo campo es este
    try {
      const col = w.ASPxClientControl.GetControlCollection();
      if (typeof col.ForEachControl === 'function') col.ForEachControl((x) => { if (!c && x && typeof x.GetInputElement === 'function' && x.GetInputElement() === el) c = x; });
    } catch (e) { c = c || null; }
  }
  if (!c || typeof c.SetDate !== 'function' || typeof c.GetDate !== 'function') return null;
  c.SetDate(new w.Date(f[0], f[1] - 1, f[2]));
  const d = c.GetDate();
  return { ok: !!d && d.getFullYear() === f[0] && d.getMonth() === f[1] - 1 && d.getDate() === f[2], texto: el.value || '' };
}"""
# v3.6.1: lo que dice el formato de fecha de una casilla antes de escribir (su valor y su placeholder)
JS_PISTAS_FECHA = "e => ({valor: ('value' in e && !e.isContentEditable) ? (e.value || '') : '', " \
                  "placeholder: e.getAttribute('placeholder') || ''})"
# Forma de una fecha (cifras o «dd/mm/aaaa» → 9) → su formato (dd/mm antes que mm/dd, como en el calendario)
FORMAS_FECHA = {"9999-99-99": "%Y-%m-%d", "9999/99/99": "%Y/%m/%d", "99/99/9999": "%d/%m/%Y",
                "99-99-9999": "%d-%m-%Y", "99.99.9999": "%d.%m.%Y"}


def formato_de_forma(texto):
    """«2026-10-30», «3010-20-26» o «aaaa-mm-dd» → «%Y-%m-%d»; None si no tiene forma de fecha."""
    return FORMAS_FECHA.get(re.sub(r"[0-9dmya]", "9", str(texto or "").strip().lower()))


def leer_fecha(texto):
    """«30/10/2026» → (date(2026, 10, 30), «%d/%m/%Y»); (None, None) si no es una fecha."""
    t = str(texto or "").strip()
    formato = formato_de_forma(t) if re.fullmatch(r"[\d/.\-]+", t) else None
    if not formato:
        return None, None
    try:
        return datetime.datetime.strptime(t, formato).date(), formato
    except ValueError:
        return None, None

# ¿Es un campo con lista de opciones (autocompletar, combobox, v-select…)?
JS_ES_COMBO = r"""e => {
  const rx = /autocomplete|combobox|v-select|v-combobox|select2|chosen|choices|multiselect|typeahead|ng-select|mat-select/i;
  const rol = e.getAttribute('role');
  if (rol === 'combobox' || e.getAttribute('aria-autocomplete') || /^(listbox|true)$/.test(e.getAttribute('aria-haspopup') || '')) return true;
  if (e.closest('[role=combobox]')) return true;
  for (let n = e.parentElement, k = 0; n && k < 4; n = n.parentElement, k++) {
    const c = typeof n.className === 'string' ? n.className : '';
    if (rx.test(c)) return true;
  }
  return false;
}"""

# Marca (data-bot-opcion) la opción visible de una lista cuyo texto es exactamente `v` (devuelve 2; 1 si hay
# una lista abierta sin esa opción; 0 si no hay lista).  El primer argumento es el campo: no cuentan los
# elementos del propio campo (p. ej. el texto ya elegido).
JS_MARCAR_OPCION = r"""(campo, v) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const obj = norm(v);
  document.querySelectorAll('[data-bot-opcion]').forEach((e) => e.removeAttribute('data-bot-opcion'));
  if (!obj) return false;
  const vis = (e) => { if (!e.getClientRects().length) return false; const cs = getComputedStyle(e); return cs.visibility !== 'hidden'; };
  let propio = campo;
  for (let k = 0; k < 4 && propio.parentElement && propio.parentElement !== document.body; k++) propio = propio.parentElement;
  const sel = '[role=option], [role=menuitem], [role=treeitem], .v-list-item, li, [class*=option], [class*=item]';
  let mejor = null, nivel = -1, hay = false;
  for (const e of document.querySelectorAll(sel)) {
    if (propio.contains(e) || !vis(e)) continue;
    if (e.matches('[role=option], [role=menuitem], [role=treeitem], .v-list-item')) hay = true;
    if (norm(e.innerText || e.textContent) !== obj) continue;
    const n = e.getAttribute('role') === 'option' ? 2 : (e.matches('[role=menuitem], [role=treeitem], .v-list-item') ? 1 : 0);
    if (n > nivel || (n === nivel && mejor && mejor.contains(e))) { mejor = e; nivel = n; }
  }
  if (!mejor) return hay ? 1 : 0;      // 1 = hay una lista abierta pero sin esa opción; 0 = no hay lista
  mejor.setAttribute('data-bot-opcion', '1');
  return 2;
}"""

# Recuperación (a): el elemento sobre el que hay que pasar el ratón para que aparezca `el` (oculto).
# 1) ARIA: quien lo controla (aria-controls / aria-owns);  2) menús DevExpress (…_DXI1i0_ → …_DXI1_);
# 3) el ancestro visible más cercano del primer contenedor oculto (menús CSS con :hover).
JS_PADRE_MENU = r"""el => {
  const vis = (n) => { if (!n.getClientRects().length) return false; const cs = getComputedStyle(n); return cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const grande = (x) => { const r = x.getBoundingClientRect(); return r.width * r.height > 0.4 * innerWidth * innerHeight; };
  const ok = (x) => !!x && x.nodeType === 1 && x !== document.body && x !== document.documentElement && x.tagName !== 'FORM' && vis(x) && !grande(x);
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  for (let m = el; m && m.nodeType === 1 && m !== document.body; m = m.parentElement) {
    if (!m.id) continue;
    let c = null;
    try { c = document.querySelector('[aria-controls~="' + esc(m.id) + '"], [aria-owns~="' + esc(m.id) + '"]'); } catch (e) { c = null; }
    if (ok(c)) return c;
  }
  for (let m = el; m && m.nodeType === 1 && m !== document.body; m = m.parentElement) {
    const r = /^(.*_DXI)(\d+(?:i\d+)+)_/.exec(m.id || '');
    if (!r) continue;
    const item = document.getElementById(r[1] + r[2].replace(/i\d+$/, '') + '_');
    if (item) {
      const t = item.querySelector('.dxm-content') || item;
      if (ok(t)) return t;
      if (ok(item)) return item;
    }
  }
  let n = el, oculto = null;
  while (n && n.nodeType === 1 && n !== document.body && !vis(n)) { oculto = n; n = n.parentElement; }
  if (oculto && ok(n)) return n;
  return null;
}"""

# Recuperación (c): ¿el elemento abre una lista o menú?  '' = no; 'abierto' / 'cerrado'.
JS_ABRIDOR = r"""el => {
  const rx = /menu|dropdown|select|combo|autocomplete|picker|v-field|toggle|listbox/i;
  const nodos = [];
  for (let n = el, k = 0; n && n.nodeType === 1 && n !== document.body && k < 3; n = n.parentElement, k++) nodos.push(n);
  if (el.querySelectorAll) el.querySelectorAll('[aria-haspopup], [aria-expanded], [role=combobox]').forEach((x, i) => { if (i < 10) nodos.push(x); });
  let es = false, abierto = false;
  for (const n of nodos) {
    const hp = n.getAttribute('aria-haspopup'), ex = n.getAttribute('aria-expanded'), rol = n.getAttribute('role');
    if ((hp && hp !== 'false') || ex !== null || rol === 'combobox' || rol === 'listbox' || n.tagName === 'SELECT') es = true;
    if (ex === 'true') abierto = true;
  }
  if (!es) {
    const c = (n) => (typeof n.className === 'string' ? n.className : '');
    es = nodos.slice(0, 3).some((n) => rx.test(c(n)));
  }
  return !es ? '' : (abierto ? 'abierto' : 'cerrado');
}"""

# Recuperación (d): marca (data-bot-explorar=k) las opciones visibles de los menús de la página.
JS_MARCAR_MENUS = r"""body => {
  document.querySelectorAll('[data-bot-explorar]').forEach((e) => e.removeAttribute('data-bot-explorar'));
  const vis = (e) => { if (!e.getClientRects().length) return false; const cs = getComputedStyle(e); return cs.visibility !== 'hidden'; };
  const sel = '[role=menubar] > *, [role=menubar] [role=menuitem], .dxm-item, nav li, [class*=menu] > li, [class*=menu] > ul > li, [class*=nav] > li, [class*=nav] > ul > li';
  const vistos = [];
  for (const e of document.querySelectorAll(sel)) {
    if (vistos.length >= 20) break;
    if (!vis(e) || vistos.some((v) => v.contains(e) || e.contains(v))) continue;
    const r = e.getBoundingClientRect();
    if (r.width * r.height > 0.25 * innerWidth * innerHeight) continue;
    vistos.push(e);
  }
  vistos.forEach((e, i) => e.setAttribute('data-bot-explorar', String(i)));
  return vistos.map((e) => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40));
}"""

# ---------------------------------------------------------------- elegir opción (v3.0)
# Opciones de la lista abierta que corresponde al campo `c` (listas nativas aparte): la que el campo controla
# (aria-controls / aria-owns), o la lista visible más cercana al campo (Vuetify la «teletransporta» al final del
# <body>).  Marca la opción que buscar (data-bot-op-elegida) si se pide.  Devuelve {n, textos, abierta, puede_bajar}.
JS_OPCIONES = r"""(c, a) => {
  a = a || {};
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const vis = (e) => { if (!e || !e.getClientRects().length) return false; const cs = getComputedStyle(e);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0.05; };
  const clase = (e) => (typeof e.className === 'string' ? e.className : (e.getAttribute && e.getAttribute('class')) || '');
  document.querySelectorAll('[data-bot-op-elegida]').forEach((e) => e.removeAttribute('data-bot-op-elegida'));
  const SEL_LISTA = '[role=listbox],[role=menu],.v-list,.v-overlay__content,.dropdown-menu,.select2-results,.mat-select-panel,' +
    '.mat-mdc-select-panel,.ui-menu,.el-select-dropdown,.ant-select-dropdown,.choices__list--dropdown,.vs__dropdown-menu,' +
    '.multiselect__content-wrapper,.p-dropdown-panel,.k-list-container,.dx-list,.dxeListBox,[class*=dropdown-menu]';
  const SEL_OPCION = '[role=option],[role=menuitem],[role=menuitemradio],.v-list-item,.dropdown-item,.select2-results__option,' +
    'mat-option,.mat-option,.el-select-dropdown__item,.ant-select-item-option,.choices__item--choice,.vs__dropdown-option,' +
    '.multiselect__option,.p-dropdown-item,.k-list-item,.dx-list-item,.dxeListBoxItem,li';
  let lista = null;
  const ids = [];
  for (const e of [c].concat(Array.from(c.querySelectorAll('[aria-controls],[aria-owns]')))) {
    for (const at of ['aria-controls', 'aria-owns']) (e.getAttribute(at) || '').split(/\s+/).forEach((i) => { if (i) ids.push(i); });
  }
  for (const i of ids) { const l = document.getElementById(i); if (l && vis(l) && l.querySelector(SEL_OPCION)) { lista = l; break; } }
  if (!lista) {
    const r = c.getBoundingClientRect();
    let mejor = null, dist = 1e9;
    for (const l of document.querySelectorAll(SEL_LISTA)) {
      if (!vis(l) || l.contains(c)) continue;          // una lista que contiene al propio campo no es su menú
      const ops = Array.from(l.querySelectorAll(SEL_OPCION)).filter(vis);
      if (!ops.length) continue;
      if (lista && lista.contains(l)) continue;
      const b = l.getBoundingClientRect();
      const d = Math.abs(b.top - r.bottom) + Math.abs(b.left - r.left) * 0.5 + (b.top < r.top ? Math.abs(b.bottom - r.top) : 0);
      if (d < dist || (mejor && l.contains(mejor) && d <= dist + 1)) { dist = d; mejor = l; }
    }
    lista = mejor;
  }
  const res = { n: 0, textos: [], abierta: !!lista, puede_bajar: false, elegida: false };
  if (!lista) return res;
  let ops = Array.from(lista.querySelectorAll(SEL_OPCION)).filter((o) => vis(o) && !o.contains(c));
  ops = ops.filter((o) => !ops.some((x) => x !== o && x.contains(o)));        // la opción de fuera, no sus piezas
  for (const o of ops) {
    if (o.getAttribute('aria-disabled') === 'true' || /subheader|divider|disabled|header/i.test(clase(o))) continue;
    const t = norm(o.innerText || o.textContent);
    if (!t) continue;
    res.textos.push(t);
    if (a.buscar !== undefined && a.buscar !== null && !res.elegida && t.toLowerCase() === norm(a.buscar).toLowerCase()) {
      o.setAttribute('data-bot-op-elegida', '1'); res.elegida = true;
    }
  }
  res.n = res.textos.length;
  // contenedor que se desplaza (listas virtuales: solo se dibujan las opciones que se ven)
  let desp = null;
  for (let n = ops.length ? ops[0].parentElement : lista; n && n !== document.body; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (/(auto|scroll)/.test(cs.overflowY) && n.scrollHeight > n.clientHeight + 2) { desp = n; break; }
    if (n === lista.parentElement) break;
  }
  window.__botListaDesp = desp;
  if (desp) {
    if (a.arriba) { desp.scrollTop = 0; desp.dispatchEvent(new Event('scroll')); }
    else if (a.bajar) { desp.scrollTop = desp.scrollTop + Math.max(30, desp.clientHeight * 0.8); desp.dispatchEvent(new Event('scroll')); }
    res.puede_bajar = desp.scrollTop + desp.clientHeight < desp.scrollHeight - 2;
  }
  return res;
}"""

# ¿La lista del campo está abierta?  (aria-expanded del campo o de sus piezas)
JS_EXPANDIDO = r"""c => { for (const e of [c].concat(Array.from(c.querySelectorAll('[aria-expanded]'))))
  { if (e.getAttribute('aria-expanded') === 'true') return true; } return false; }"""

# Lista nativa (<select>) del campo: el propio elemento o la única dentro de él.
JS_SELECT_NATIVO = r"""c => { const s = c.tagName === 'SELECT' ? c : (c.querySelectorAll('select').length === 1 ? c.querySelector('select') : null);
  if (!s) return null; s.setAttribute('data-bot-select', '1');
  return Array.from(s.options).map((o) => ({ texto: (o.text || '').replace(/\s+/g, ' ').trim(), valor: o.value, desactivada: o.disabled })); }"""

JS_NOMBRE_CORTO = r"""e => ((e.innerText || e.textContent || e.getAttribute('aria-label') || e.id || e.tagName) + '').replace(/\s+/g, ' ').trim().slice(0, 50)"""

# ---------------------------------------------------------------- esperas de carga
# Script que se pone en cada documento: cuenta los cambios del DOM (para saber si una página «hace algo»).
JS_INIT_CARGA = r"""(() => {
  if (window.__botCarga) return;
  window.__botCarga = { mut: 0 };
  const iniciar = () => {
    try {
      new MutationObserver((ms) => {
        let n = 0;
        for (const m of ms) if (!(m.type === 'attributes' && /^data-bot-/.test(m.attributeName || ''))) n++;
        window.__botCarga.mut += n;
      }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    } catch (e) { /* documento especial */ }
  };
  iniciar();
})();"""

# Estado de carga de un documento: readyState, jQuery.active, postback asíncrono de ASP.NET y los indicadores de
# carga visibles (ruedas, barras, «Cargando…», paneles de DevExpress, aria-busy).  Con `marcar` = true, marca los
# indicadores visibles con data-bot-ind (los que ya estaban antes de una acción no se esperan con el tope largo).
JS_ESTADO_CARGA = r"""(_, marcar) => {
  const r = { listo: document.readyState, jq: 0, asp: false, ind: [], mut: (window.__botCarga && window.__botCarga.mut) || 0 };
  try { if (window.jQuery && typeof window.jQuery.active === 'number') r.jq = window.jQuery.active; } catch (e) {}
  try {
    const P = window.Sys && Sys.WebForms && Sys.WebForms.PageRequestManager;
    if (P && P.getInstance) { const m = P.getInstance(); r.asp = !!(m && m.get_isInAsyncPostBack && m.get_isInAsyncPostBack()); }
  } catch (e) {}
  const host = document.getElementById('__bot_host__');
  const vw = innerWidth * innerHeight;
  const visible = (e) => {
    if (!e || !e.getClientRects().length) return false;
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    for (let n = e, k = 0; n && n.nodeType === 1 && k < 4; n = n.parentElement, k++) {
      if (parseFloat(getComputedStyle(n).opacity || '1') < 0.05) return false;
    }
    return true;
  };
  const clase = (e) => (typeof e.className === 'string' ? e.className : (e.getAttribute && e.getAttribute('class')) || '');
  const RX = /spinner|loading|loader|cargando|progress|blockui|v-progress|v-overlay--active|mat-progress|busy|(^|[\s_-])wait([\s_-]|$)|preloader|throbber|dxlp|loadingpanel|lds-/i;
  const NO = /load-?more|download|upload|loaded|no-?loading|progress-?(label|text|value)/i;
  // v3.0: «fuerte» = de verdad es una rueda/barra de carga; «débil» = solo una capa (overlay) o algo «busy/wait»:
  // si la página no hace nada durante ~3 s se deja de esperar.  Los menús, listas desplegables, popovers, diálogos y
  // tooltips NO son indicadores de carga (en Vuetify el menú abierto de una lista es un «v-overlay--active»).
  const RX_FUERTE = /spinner|loading|loader|cargando|progress|blockui|preloader|throbber|dxlp|loadingpanel|lds-/i;
  const RX_MENU = /v-menu|v-select|v-autocomplete|v-combobox|v-tooltip|dropdown|popover|tooltip|menu|listbox|select2|chosen-|mat-select|picker/i;
  const ROL_MENU = /^(menu|menubar|listbox|dialog|alertdialog|tooltip|combobox|tree|grid)$/;
  const RXT = /^(cargando|loading|procesando|espere|por favor,? espere|please wait|generando|actualizando|un momento)\b/i;
  const SEL_PROGRESO = '[class*=v-progress],[class*=mat-progress],[role=progressbar],progress,[class*=spinner i],' +
    '[class*=loader i],[class*=loading i],[class*=throbber i],[class*=lds- i],[aria-busy=true],[class*=cargando i]';
  const conProgreso = (e) => {
    try {
      for (const p of e.querySelectorAll(SEL_PROGRESO)) {
        if (/v-progress-linear/.test(clase(p)) && !/v-progress-linear--active|indeterminate/.test(clase(p))) continue;
        if (visible(p)) return true;
      }
      const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
      let t, k = 0;
      while ((t = w.nextNode()) && k++ < 300) { const s = (t.nodeValue || '').trim(); if (s.length >= 4 && s.length <= 70 && RXT.test(s)) return true; }
    } catch (x) {}
    return false;
  };
  const conOpciones = (e) => {
    try { return !!e.querySelector('[role=option],[role=menuitem],[role=listbox],[role=menu],.v-list-item,.v-list,li,input,select,textarea,button,a[href]'); }
    catch (x) { return false; }
  };
  const esMenu = (e) => ROL_MENU.test(e.getAttribute('role') || '') || RX_MENU.test(clase(e) + ' ' + (e.id || ''));
  const vistos = [];
  const anotar = (e, d, fuerte) => {
    if (vistos.some((v) => v === e || v.contains(e) || e.contains(v))) return;
    vistos.push(e);
    r.ind.push({ d: d.slice(0, 60), pre: e.hasAttribute('data-bot-ind'), fuerte: fuerte !== false });
    if (marcar) { try { e.setAttribute('data-bot-ind', '1'); } catch (x) {} }
  };
  const sel = '[class*=spin i],[class*=load i],[class*=progress i],[class*=busy i],[class*=wait i],[class*=cargando i],' +
    '[class*=blockui i],[class*=overlay--active i],[class*=preloader i],[class*=throbber i],[class*=dxlp i],[class*=lds- i],' +
    '[id*=load i],[id*=spin i],[id*=progress i],[role=progressbar],[aria-busy=true],progress';
  let n = 0;
  let lista = [];
  try { lista = document.querySelectorAll(sel); } catch (e) { lista = []; }
  for (const e of lista) {
    if (n++ > 500 || r.ind.length >= 6) break;
    if (e === document.body || e === document.documentElement) continue;
    if (host && (e === host || host.contains(e))) continue;
    const c = clase(e), id = e.id || '', rol = e.getAttribute('role') || '';
    const ocupado = e.getAttribute('aria-busy') === 'true';
    const barra = rol === 'progressbar' || e.tagName === 'PROGRESS';
    if (!ocupado && !barra && (!RX.test(c + ' ' + id) || NO.test(c + ' ' + id))) continue;
    if (barra) {
      const v = e.getAttribute('aria-valuenow') || (e.tagName === 'PROGRESS' && e.hasAttribute('value') ? e.value : null);
      const mx = e.getAttribute('aria-valuemax') || (e.tagName === 'PROGRESS' ? e.max : null) || 100;
      if (v !== null && v !== '' && parseFloat(v) >= parseFloat(mx)) continue;      // barra completa
    }
    if (/v-progress-linear/.test(c) && !/v-progress-linear--active|indeterminate/.test(c)) continue;
    if (!visible(e)) continue;
    const b = e.getBoundingClientRect();
    if (b.width < 6 || b.height < 3) continue;
    const pos = getComputedStyle(e).position;
    if (b.width * b.height > 0.9 * vw && pos !== 'fixed' && pos !== 'absolute' && !/overlay|blockui|dxlp/i.test(c)) continue;
    let fuerte = true;
    if (!ocupado && !barra) {
      if (esMenu(e)) continue;               // lista desplegable / menú / diálogo abierto: no es una carga (su rueda, si la tiene, se ve aparte)
      if (!RX_FUERTE.test(c + ' ' + id)) {
        // capa (v-overlay--active) o «busy/wait»: solo es una carga si dentro hay una rueda/barra o un «Cargando…»
        if (conProgreso(e)) fuerte = true;
        else if (/overlay/i.test(c) && conOpciones(e)) continue;      // capa con opciones, campos o botones: un menú
        else fuerte = false;
      }
    }
    anotar(e, (id ? '#' + id : '') + (c ? '.' + c.trim().split(/\s+/).slice(0, 2).join('.') : '') || e.tagName.toLowerCase(), fuerte);
  }
  if (r.ind.length < 6 && document.body) {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let k = 0, t;
    while ((t = w.nextNode()) && k++ < 4000) {
      const s = (t.nodeValue || '').trim();
      if (s.length < 4 || s.length > 70 || !RXT.test(s)) continue;
      const e = t.parentElement;
      if (!e || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|OPTION|TITLE)$/.test(e.tagName) || (host && host.contains(e))) continue;
      if (visible(e)) anotar(e, '«' + s.slice(0, 40) + '»');
      if (r.ind.length >= 6) break;
    }
  }
  return r;
}"""

# Esperas «hasta que aparezca»: marca (data-bot-pre-N = huella del texto) lo que ya coincidía antes de la acción
# anterior, para que la espera no se dé por buena con un elemento que ya estaba.
JS_MARCAR_PREVIO = r"""(e, n) => { const t = (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim(); let h = 0;
  for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0; e.setAttribute('data-bot-pre-' + n, t.length + ':' + h); }"""
JS_ES_NUEVO = r"""(e, n) => { const a = e.getAttribute('data-bot-pre-' + n); if (a === null) return true;
  const t = (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim(); let h = 0;
  for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0; return a !== t.length + ':' + h; }"""

JS_TEXTO_EN_PAGINA = r"""(frs) => { if (!document.body) return false;
  const t = (document.body.innerText || '').replace(/\s+/g, ' ');
  let pos = 0; for (const f of frs) { const k = t.indexOf(f, pos); if (k < 0) return false; pos = k + f.length; } return true; }"""

# ---------------------------------------------------------------- inicio de sesión
# Analiza la página: ¿hay un formulario de inicio de sesión visible (un campo de contraseña visible, o el «clon»
# visible de DevExpress de uno oculto)?  Marca sus campos (data-bot-login=k) y el botón de entrar
# (data-bot-login-enviar) y devuelve {hay, campos: [{k, clave, nombre, etiqueta, tipo, requerido, tiene_valor}],
# enviar, error, firma}.
JS_ANALIZAR_LOGIN = r"""(_) => {
  document.querySelectorAll('[data-bot-login]').forEach((e) => e.removeAttribute('data-bot-login'));
  document.querySelectorAll('[data-bot-login-enviar]').forEach((e) => e.removeAttribute('data-bot-login-enviar'));
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const vis = (e) => { if (!e || !e.getClientRects().length) return false; const cs = getComputedStyle(e);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0.05; };
  const host = document.getElementById('__bot_host__');
  const pws = [];
  for (const e of document.querySelectorAll('input[type=password]')) {
    if (host && host.contains(e)) continue;
    if (vis(e)) { pws.push({ real: e, vista: e }); continue; }
    const clon = e.id ? document.getElementById(e.id + '_CLND') : null;
    if (clon && vis(clon)) pws.push({ real: e, vista: clon });
  }
  const res = { hay: false, campos: [], enviar: false, error: '', firma: '' };
  const RXERR = /error|alert|invalid|danger|warning|validation|mensaje|msg|snackbar|toast|v-messages__message|dxeErrorCell|failure|incorrect/i;
  const buscarError = () => {
    const sel = '[role=alert],[aria-live=assertive],[class*=error i],[class*=alert i],[class*=invalid i],[class*=danger i],' +
      '[class*=warning i],[class*=validation i],[class*=msg i],[class*=mensaje i],[class*=snackbar i],[class*=toast i],' +
      '[id*=error i],[id*=msg i],[id*=mensaje i],.v-messages__message';
    let k = 0;
    for (const e of document.querySelectorAll(sel)) {
      if (k++ > 200) break;
      if (host && host.contains(e)) continue;
      const t = norm(e.innerText || e.textContent);
      if (t.length < 3 || t.length > 220 || !vis(e)) continue;
      const c = (typeof e.className === 'string' ? e.className : '') + ' ' + (e.id || '') + ' ' + (e.getAttribute('role') || '');
      if (!RXERR.test(c) && e.getAttribute('role') !== 'alert') continue;
      return t;
    }
    return '';
  };
  if (!pws.length) return res;
  res.hay = true;
  res.firma = pws.map((p) => p.real.id || p.real.name || 'pw').join('|');
  const pw = pws[0].real;
  const cuenta = (n) => n.querySelectorAll('input:not([type=hidden]), select, textarea').length;
  let region = pw.closest('form');
  if (!region || cuenta(region) > 15) {
    region = null;
    for (let n = pw.parentElement, k = 0; n && n !== document.body && k < 8; n = n.parentElement, k++) {
      if (cuenta(n) > 15) break;
      region = n;
      if (cuenta(n) >= 2 && n.querySelector('button, input[type=submit], input[type=button], input[type=image], [role=button], a[href], .dxb')) break;
    }
    region = region || document.body;
  }
  const clones = new Set(pws.filter((p) => p.vista !== p.real).map((p) => p.vista));
  const reales = new Set(pws.map((p) => p.real));
  const TIPOS = ['text', 'email', 'tel', 'number', 'password', 'search', 'url', ''];
  const etiquetaDe = (e) => {
    let t = '';
    try { if (e.labels && e.labels.length) t = norm(e.labels[0].innerText || e.labels[0].textContent); } catch (x) {}
    if (!t) t = norm(e.getAttribute('aria-label'));
    if (!t && e.getAttribute('aria-labelledby')) {
      t = norm(e.getAttribute('aria-labelledby').split(/\s+/).map((i) => { const l = document.getElementById(i); return l ? l.textContent : ''; }).join(' '));
    }
    if (!t) t = norm(e.getAttribute('placeholder'));
    if (!t && e.id) { const c = document.getElementById(e.id + '_CLND'); if (c) t = norm(c.value || c.getAttribute('placeholder')); }
    if (!t) t = norm(e.getAttribute('title'));
    if (!t) {
      const td = e.closest('td');
      if (td) {
        let p = td.previousElementSibling;
        if (!p) { const tr = td.parentElement && td.parentElement.closest('tr'); if (tr && tr.previousElementSibling) p = tr.previousElementSibling; }
        if (p) t = norm(p.innerText || p.textContent);
      }
    }
    return (t || '').replace(/[:*]+$/, '').trim().slice(0, 60);
  };
  let k = 0;
  for (const e of region.querySelectorAll('input, textarea')) {
    if (clones.has(e) || (host && host.contains(e))) continue;
    const tipo = (e.getAttribute('type') || '').toLowerCase();
    if (!TIPOS.includes(tipo) && e.tagName !== 'TEXTAREA') continue;
    if (!reales.has(e) && !vis(e)) continue;
    if (e.disabled) continue;
    e.setAttribute('data-bot-login', String(k));
    res.campos.push({ k: String(k), clave: e.id || e.name || ('campo' + k), nombre: e.name || e.id || ('campo' + k),
      etiqueta: etiquetaDe(e), tipo: (tipo === 'password' || reales.has(e)) ? 'clave' : 'texto',
      requerido: !!(e.required || e.getAttribute('aria-required') === 'true'), tiene_valor: !!e.value });
    k++;
  }
  const RXENT = /iniciar|entrar|ingresar|acceder|login|log in|sign in|aceptar|continuar|enviar|submit|conectar/i;
  const botones = Array.from(region.querySelectorAll('button, input[type=submit], input[type=button], input[type=image], [role=button], a[href], .dxb'))
    .filter((b) => vis(b) && !(host && host.contains(b)));
  const textoB = (b) => norm(b.innerText || b.value || b.getAttribute('aria-label') || b.getAttribute('title') || '');
  const ojo = (b) => /appended|prepended|mostrar|ocultar|show|hide|toggle|eye|ojo|visibility/i.test(textoB(b) + ' ' + (typeof b.className === 'string' ? b.className : ''));
  let boton = botones.find((b) => RXENT.test(textoB(b)) && !ojo(b)) || botones.find((b) => (b.type || '').toLowerCase() === 'submit' && !ojo(b));
  if (boton) { boton.setAttribute('data-bot-login-enviar', '1'); res.enviar = true; }
  res.error = buscarError();
  return res;
}"""

# v3.3.1: ventanita de mensaje de la página tras enviar el inicio de sesión («Mensaje — El campo LICENCIA esta vacio…
# [Aceptar]», p. ej. un popup de DevExpress): marca su botón para cerrarla.  No toca el formulario de inicio de sesión
# (una capa que contiene un campo de contraseña es el propio formulario).
JS_MARCAR_CIERRE_MENSAJE = r"""(_, msg) => {
  document.querySelectorAll('[data-bot-cerrar]').forEach((e) => e.removeAttribute('data-bot-cerrar'));
  // solo la capa que muestra el mensaje que se leyó (no un aviso de cookies u otra ventanita que no tiene que ver)
  const palabras = ((msg || '') + '').toLowerCase().split(/[^a-záéíóúñü0-9]+/).filter((p) => p.length >= 4).slice(0, 6);
  const esDelMensaje = (t) => { if (!palabras.length) return false; t = t.toLowerCase();
    return palabras.filter((p) => t.includes(p)).length * 2 >= palabras.length; };
  const vis = (e) => { if (!e || !e.getClientRects().length) return false; const cs = getComputedStyle(e);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0.05; };
  const host = document.getElementById('__bot_host__');
  const RXCAPA = /dxpc|popup|modal|dialog|swal|alert|toast|snackbar|mensaje|message|msgbox|notif|bootbox|overlay/i;
  const RXBOTON = /^(aceptar|ok|okay|cerrar|entendido|continuar|close|de acuerdo|×|x)$/i;
  const capas = Array.from(document.querySelectorAll('[role=dialog],[role=alertdialog],[role=alert],div,section,table'))
    .filter((c) => {
      if (host && host.contains(c)) return false;
      const k = (typeof c.className === 'string' ? c.className : '') + ' ' + (c.id || '') + ' ' + (c.getAttribute('role') || '');
      return RXCAPA.test(k) && vis(c) && !c.querySelector('input[type=password]') && esDelMensaje(c.innerText || '');
    });
  for (const c of capas) {
    const botones = Array.from(c.querySelectorAll('button, input[type=button], input[type=submit], a, [role=button], .dxb, span'))
      .filter((b) => vis(b) && !b.closest('[data-bot-login-enviar]') && !b.hasAttribute('data-bot-login-enviar'));
    const b = botones.find((x) => RXBOTON.test(((x.innerText || x.value || x.getAttribute('aria-label') || '') + '').replace(/\s+/g, ' ').trim()));
    if (b) { b.setAttribute('data-bot-cerrar', '1'); return ((c.innerText || '') + '').replace(/\s+/g, ' ').trim().slice(0, 120); }
  }
  return null;
}"""

# v3.3.1: ¿el elemento es una pestaña que ya está elegida?  (Vuetify v-tab--selected / v-tab-item--selected, ARIA,
# Bootstrap .active)
JS_PESTANA_ELEGIDA = r"""e => {
  const t = e.closest('[role=tab], .v-tab, .nav-link, .tab, [class*="tab-item"]');
  if (!t) return false;
  const c = typeof t.className === 'string' ? t.className : '';
  return t.getAttribute('aria-selected') === 'true' || /(^|\s)(v-tab--selected|v-tab-item--selected|active|selected)(\s|$)|--selected(\s|$)/.test(c);
}"""

# v3.3.1: ¿la dirección parece la del inicio de sesión?  (entonces no se «vuelve» a ella después de entrar)
RX_URL_LOGIN = re.compile(r"login|log-in|logon|signin|sign-in|inicio-?sesion|iniciar-?sesion|auth|acceso|ingres",
                          re.IGNORECASE)


def _partes_url(url):
    """(host+ruta sin la barra final, ruta hash sin barras) de una dirección; la consulta (?…) no cuenta."""
    from urllib.parse import urlparse
    try:
        u = urlparse(url or "")
    except ValueError:
        return ("", "")
    ruta = (u.path or "/").rstrip("/") or "/"
    return ((u.hostname or "").lower() + ruta, (u.fragment or "").strip("/").split("?")[0].rstrip("/"))


def misma_direccion(a, b):
    """True si dos direcciones son la misma página (sin mirar la consulta, pero SÍ la ruta tras «#» de las webs de
    una sola página como Portal: «…/portal/#/inicio» no es «…/portal/#/reportes/corte»)."""
    return _partes_url(a) == _partes_url(b)


def hay_que_volver(actual, destino):
    """Tras iniciar sesión: ¿hay que volver a abrir `destino` (la página a la que iba el reporte) porque la web llevó
    a otra (`actual`)?  No si es la misma, si el destino es la propia página de inicio de sesión o la raíz del sitio, ni
    si solo cambia la ruta tras «#» y el destino no lleva ninguna."""
    if not destino or misma_direccion(actual, destino):
        return False
    base_d, hash_d = _partes_url(destino)
    base_a, _hash_a = _partes_url(actual)
    if RX_URL_LOGIN.search(base_d.split("/", 1)[-1] if "/" in base_d else "") or RX_URL_LOGIN.search(hash_d):
        return False
    if not hash_d and (base_d == base_a or base_d.endswith("/") and base_d.count("/") <= 1):
        return False
    if not hash_d and "/" not in base_d.rstrip("/"):
        return False
    return True


JS_TABLA = r"""() => {
  let mejor = null, n = 0;
  for (const t of document.querySelectorAll('table')) {
    const c = t.querySelectorAll('td, th').length;
    if (c > n) { n = c; mejor = t; }
  }
  if (!mejor) return null;
  const celdas = (r) => Array.from(r.cells).map((c) => (c.innerText || c.textContent || '').replace(/\s+/g, ' ').trim());
  return { celdas: n, filas: Array.from(mejor.rows).map(celdas) };
}"""


class ErrorPaso(RuntimeError):
    """Un paso no se pudo completar."""


class Detenido(Exception):
    """El usuario pidió detener la ejecución."""


class ResultadoEjecucion:
    def __init__(self):
        self.ok = False
        self.detenido = False
        self.total = 0
        self.completados = 0
        self.omitidos = 0
        self.desactivados = 0
        self.sin_valor = 0        # v3.8: pasos saltados porque se dejaron vacíos
        self.error = ""
        self.paso_fallido = None
        self.ruta_log = ""
        self.ruta_captura = ""
        self.archivos = []
        self.dias = []            # v3.0: días de «Repetir por días» (vacío = una sola vez)
        self.extra = None         # v3.0: lo que devolvió `al_final` (opciones leídas, mapa de la página…)
        self.opciones_leidas = {}  # v3.1: {paso: {opciones, padres, firma}} listas leídas (opciones de los filtros)
        self.filtros = []          # v3.1: filtros cambiados solo para esta ejecución (texto para el registro)

    def resumen(self):
        if self.ok:
            if self.dias:
                txt = "Terminado: %d días (%s a %s), %d pasos" % (
                    len(self.dias), self.dias[0].strftime("%d/%m/%Y"), self.dias[-1].strftime("%d/%m/%Y"), self.completados)
            else:
                txt = "Terminado: %d de %d pasos" % (self.completados, self.total - self.desactivados - self.sin_valor)
            extra = []
            if self.omitidos:
                extra.append("%d opcionales omitidos" % self.omitidos)
            if self.desactivados:
                extra.append("%d desactivados" % self.desactivados)
            if self.sin_valor:
                extra.append("%d sin valor, saltados" % self.sin_valor)
            if extra:
                txt += " (%s)" % ", ".join(extra)
            if self.archivos:
                txt += "; archivos: " + ", ".join(self.archivos)
            return txt
        if self.detenido:
            return "Detenido por el usuario en el paso %s" % (self.paso_fallido or "?")
        return "Error en el paso %s: %s" % (self.paso_fallido, self.error)


def _primeras_lineas(e, n=2):
    lineas = [l.strip() for l in str(e).splitlines() if l.strip()]
    return " ".join(lineas[:n]) if lineas else type(e).__name__


def nombre_archivo_seguro(nombre):
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", nombre).strip(" .")
    return limpio or "descarga"


RX_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def separar_extension(ruta, ext=None):
    """(v3.5) (base, extensión) sin romper los nombres con puntos: «Ventas S.A.S. 2026-10-29.xlsx» → («…2026-10-29»,
    «.xlsx»); «Ventas S.A.S. 2026-10-29» (sin extensión) → (todo, «»), y no («Ventas S.A.S», «. 2026-10-29») como
    `os.path.splitext`.  Con `ext` (la extensión conocida, p. ej. la del archivo descargado) se usa esa."""
    if ext is not None:
        if ext and ruta.lower().endswith(ext.lower()):
            return ruta[:-len(ext)], ruta[-len(ext):]
        if not ext:
            return ruta, ""
    base, e = os.path.splitext(ruta)
    if e and RX_EXTENSION.match(e) and not base.endswith(" "):
        return base, e
    return ruta, ""


def ruta_libre(ruta, ext=None):
    """Si la ruta existe, añade « (2)», « (3)»… antes de la extensión."""
    if not os.path.exists(ruta):
        return ruta
    base, ext = separar_extension(ruta, ext)
    n = 2
    while os.path.exists("%s (%d)%s" % (base, n, ext)):
        n += 1
    return "%s (%d)%s" % (base, n, ext)


def inyectar_base(contenido, url):
    """Añade <base href="url"> al HTML (si no la tiene) para que una copia guardada encuentre sus recursos."""
    if not url or not url.lower().startswith(("http://", "https://")) or re.search(r"<base\b", contenido, re.I):
        return contenido
    etiqueta = '<base href="%s">' % html.escape(url, quote=True)
    m = re.search(r"<head[^>]*>", contenido, re.I)
    if m:
        return contenido[:m.end()] + etiqueta + contenido[m.end():]
    m = re.search(r"<html[^>]*>", contenido, re.I)
    if m:
        return contenido[:m.end()] + "<head>" + etiqueta + "</head>" + contenido[m.end():]
    return etiqueta + contenido


class Ejecutor:
    def __init__(self, flujo, carpeta_perfil, carpeta_registros, carpeta_descargas=None,
                 oculto=True, lento=False, navegador=None, hoy=None, variables=None,
                 progreso=None, log=None, detener=None, resolver_secreto=None, ver_resaltado=True,
                 aviso_cada=AVISO_CADA, pausa_entre_pasos=None, forzar_pdf_auxiliar=False, recuperacion=None,
                 pedir_acceso=None, accesos=None, esperar_carga=None, espera_red_max=ESPERA_RED_MAX,
                 espera_estancada=ESPERA_ESTANCADA, espera_estancada_debil=ESPERA_ESTANCADA_DEBIL,
                 hasta=None, al_final=None, dias=None, notificar=None, reporte_id=None, filtros=None, solo_leer=False):
        # v3.1: `filtros` = {paso: {estrategia, valor}} solo para esta ejecución (no cambia el reporte guardado);
        # `solo_leer` («Actualizar opciones»): si la opción elegida no está en una lista, se elige la primera para seguir
        # leyendo las listas siguientes.
        self.filtros_aplicados = []
        if filtros:
            from . import filtros as mod_filtros
            flujo, self.filtros_aplicados = mod_filtros.aplicar(flujo, filtros)
        self.solo_leer = bool(solo_leer)
        self.lineas_inicio = []         # v3.2: líneas que se escriben en el registro al empezar (Páginas: lo elegido)
        self._elegidas = {}             # paso -> texto elegido en una lista (para las listas que dependen de otras)
        self.flujo = flujo
        self.carpeta_perfil = carpeta_perfil
        self.carpeta_registros = carpeta_registros
        self.oculto = oculto
        self.lento = lento
        self.navegador = navegador or flujo.opcion("navegador") or "chrome"
        self.hoy = hoy
        self.variables = dict(flujo.variables)
        self.variables.update(variables or {})
        self.progreso = progreso or (lambda indice, estado, texto="": None)
        self._log_cb = log
        self._detener = detener
        self._resolver = resolver_secreto or secretos.obtener_requerida
        self._valores_secretos = set()
        self._ruta_log = ""
        self._archivo_log = None
        self.paginas = []
        self._descargas = []
        self._pagina_activa = -1
        self._indice_actual = 0
        self._pw = None
        self._ctx = None
        self.aviso_cada = aviso_cada
        self.pausa_entre_pasos = pausa_entre_pasos      # None = la opción del flujo
        self.forzar_pdf_auxiliar = forzar_pdf_auxiliar  # solo pruebas: usa siempre el PDF por página auxiliar
        if recuperacion is None:
            recuperacion = flujo.opcion("recuperacion_automatica")
        self.recuperacion = recuperacion is not False      # recuperación automática de menús (ver _recuperar)
        self._indice_previo = None      # índice del último paso ejecutado (para la recuperación)
        self._recuperado_en = None      # índice del paso en el que ya se intentó la recuperación
        self._scope_escribir = None     # página o marco del paso «escribir» en curso
        # Inicio de sesión: `pedir_acceso(solicitud, esperar)` pregunta al usuario (ventana) y devuelve
        # {"valores": {clave: valor}, "recordar": bool} o None (Cancelar).  Sin él (sin ventana) no se puede preguntar.
        self._pedir_acceso = pedir_acceso
        self.accesos = accesos if accesos is not None else mod_accesos.AccesosMemoria()
        self._intentos_login = {}       # host -> envíos del formulario en esta ejecución
        self._enviados_login = {}       # host -> huellas de los datos ya enviados (nunca se reenvían los mismos)
        self._guardia_en = None         # índice del paso en el que ya se miró si la página pedía iniciar sesión
        self._tras_abrir = False        # el paso anterior fue «Abrir la página»
        self._pista_login = ""          # aviso para el error del paso si la página pedía iniciar sesión
        # v3.3.1: página -> dirección a la que iba el reporte (último «Abrir la página»): si tras iniciar sesión la web
        # lleva a otra (Portal: siempre a «Inicio»), se vuelve a ella; host -> reintentos por un dato obligatorio vacío
        self._destinos = {}
        self._reintentos_obligatorio = {}
        # Esperas de carga
        self.esperar_carga = esperar_carga      # None = opción del flujo / del paso
        self.espera_red_max = float(espera_red_max)
        self.espera_estancada = float(espera_estancada)
        self.espera_estancada_debil = float(espera_estancada_debil)
        self._red = {}                  # página -> {"vuelo": {petición: (t0, clave)}, "ultima": t, "historial": {}}
        self._previos = set()           # índices de esperas con lo que ya coincidía antes de la acción anterior marcado
        self.opcion_elegida = None      # texto de la última opción elegida por un paso «Elegir opción»
        # v3.0: ejecutar solo los pasos anteriores a `hasta` y llamar a `al_final(ejecutor, pagina)` con el navegador
        # todavía abierto (vigilancia, mapear la página); `dias` = días de «Repetir por días» (None = los del flujo);
        # `notificar(tipo, datos)` avisa a la aplicación (accesos guardados, contraseña rechazada…).
        self.hasta = hasta
        self.al_final = al_final
        self.dias = dias
        self.fecha = None
        self._notificar = notificar
        self.reporte_id = reporte_id
        self._rechazo_previo = None
        self.resultado = ResultadoEjecucion()
        carpeta = carpeta_descargas or flujo.opcion("carpeta_descargas")
        if not carpeta:
            from . import RAIZ
            carpeta = os.path.join(RAIZ, "descargas")
        self.carpeta_descargas = os.path.abspath(carpeta)

    # ------------------------------------------------------------- registro
    def _limpiar(self, texto):
        for v in sorted(self._valores_secretos, key=len, reverse=True):
            if v:
                texto = texto.replace(v, "********")
        return texto

    def _log(self, texto):
        linea = "[%s] %s" % (time.strftime("%H:%M:%S"), self._limpiar(texto))
        if self._archivo_log:
            self._archivo_log.write(linea + "\n")
            self._archivo_log.flush()
        if self._log_cb:
            self._log_cb(linea)

    def _abrir_log(self):
        os.makedirs(self.carpeta_registros, exist_ok=True)
        base = os.path.join(self.carpeta_registros, datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        ruta = base + ".log"
        n = 2
        while os.path.exists(ruta):
            ruta = "%s_%d.log" % (base, n)
            n += 1
        self._ruta_log = ruta
        self._archivo_log = open(ruta, "w", encoding="utf-8")
        self.resultado.ruta_log = ruta

    # ----------------------------------------------------------- plantillas
    def _secreto(self, nombre):
        valor = self._resolver(nombre)
        self._valores_secretos.add(valor)
        return valor

    def _r(self, texto, ext=None, nombre=None):
        return plantillas.renderizar(texto, variables=self.variables, hoy=self.hoy, ext=ext, nombre=nombre,
                                     resolver_secreto=self._secreto, fecha=self.fecha, reporte=self.flujo.nombre or "")

    def _r_log(self, texto, ext=None, nombre=None):
        return plantillas.renderizar(texto, variables=self.variables, hoy=self.hoy, ext=ext, nombre=nombre,
                                     enmascarar_secretos=True, fecha=self.fecha, reporte=self.flujo.nombre or "")

    # ------------------------------------------------------------- utilidades
    def _comprobar_detener(self):
        if self._detener is not None and self._detener.is_set():
            raise Detenido()

    def _dormir(self, segundos):
        """Espera sin bloquear los eventos de Playwright y atenta a «Detener»."""
        fin = time.monotonic() + segundos
        while True:
            self._comprobar_detener()
            resto = fin - time.monotonic()
            if resto <= 0:
                return
            self._pausa(min(resto, 0.25))

    def _pausa(self, segundos):
        for pg in self.paginas:
            try:
                if not pg.is_closed():
                    pg.wait_for_timeout(int(segundos * 1000))
                    return
            except Exception:
                continue
        time.sleep(segundos)

    def _timeout_paso(self, paso):
        """Tiempo máximo de espera del paso (ver Paso.timeout_efectivo)."""
        if paso.tipo in ("descargar", "guardar_pagina"):
            return paso.timeout_descarga_efectivo(self.flujo.opciones)
        return paso.timeout_efectivo(self.flujo.opciones)

    def _pausa_entre_pasos(self):
        if self.pausa_entre_pasos is not None:
            return max(0.0, float(self.pausa_entre_pasos))
        v = self.flujo.opcion("pausa_entre_pasos")
        return max(0.0, float(v if v is not None else 0.3))

    def _pagina(self, indice, timeout):
        fin = time.monotonic() + timeout
        while len(self.paginas) <= indice:
            self._comprobar_detener()
            if time.monotonic() >= fin:
                raise ErrorPaso("La pestaña %d todavía no se ha abierto" % (indice + 1))
            self._pausa(SONDEO)
        pg = self.paginas[indice]
        if pg.is_closed():
            raise ErrorPaso("La pestaña %d ya está cerrada" % (indice + 1))
        if indice != self._pagina_activa:
            self._pagina_activa = indice
            if not self.oculto:
                try:
                    pg.bring_to_front()
                except Exception:
                    pass
        return pg

    def _alcance(self, paso, timeout):
        pg = self._pagina(paso.pagina, timeout)
        scope = pg
        for marco in paso.marco:
            scope = scope.frame_locator(marco)
        return pg, scope

    # ------------------------------------------------------- localizar elementos
    def _candidatos(self, scope, sel, visible, habilitado):
        """Candidatos de un selector que cumplen las condiciones.  Devuelve (lista, hay_deshabilitados)."""
        loc = scope.locator(sel)
        n = loc.count()
        res = []
        bloqueados = False
        for i in range(min(n, MAX_CANDIDATOS)):
            cand = loc.nth(i)
            if visible and not cand.is_visible():
                continue
            if habilitado and cand.evaluate(JS_BLOQUEADO):
                bloqueados = True
                continue
            res.append(cand)
        return res, bloqueados

    @staticmethod
    def _elegir(cands):
        """Entre varios candidatos visibles, prefiere el de la ventanita emergente más reciente
        (el último en el DOM dentro de un popup); si ninguno está en un popup, el primero."""
        if len(cands) == 1:
            return cands[0]
        elegido = None
        for c in cands:
            try:
                if c.evaluate(JS_EN_POPUP):
                    elegido = c
            except Exception:
                continue
        return elegido or cands[0]

    def _avisar_espera(self, que, segundos, habilitado=True):
        texto = ("esperando a que %s esté disponible… %d s" if habilitado else "esperando a que aparezca %s… %d s") % (
            que, int(segundos))
        self._log("    " + texto)
        self.progreso(self._indice_actual, "espera", texto)

    def _localizar(self, pg, scope, selectores, timeout, visible=True, habilitado=False, que=None, al_atascar=None,
                   guardia=False):
        """Espera hasta que algún selector encuentre un elemento visible (y habilitado si se pide) y lo devuelve.

        `al_atascar()`: se llama una vez si tras ESPERA_RECUPERACION segundos no hay ningún candidato visible
        (ni siquiera deshabilitado): sirve para intentar abrir el menú que lo contiene.
        `guardia`: si tras ~3 s no aparece y la página muestra un formulario de inicio de sesión, se inicia sesión
        (ver `_guardia_login`) y se sigue buscando."""
        from playwright.sync_api import Error as ErrorPW
        inicio = time.monotonic()
        fin = inicio + timeout
        proximo_aviso = inicio + self.aviso_cada
        que = que or "el elemento"
        hubo_bloqueados = False
        while True:
            if guardia and self._toca_guardia(inicio, fin):
                t0 = time.monotonic()
                if self._guardia_login(pg):
                    fin += time.monotonic() - t0          # el tiempo del inicio de sesión no cuenta para el paso
                    continue
            self._comprobar_detener()
            for k, sel in enumerate(selectores):
                try:
                    cands, bloqueados = self._candidatos(scope, sel, visible, habilitado)
                    hubo_bloqueados = hubo_bloqueados or bloqueados
                    if cands:
                        if k > 0:
                            self._log("    (usó el selector alternativo %d: %s)" % (k + 1, sel))
                        return self._elegir(cands)
                except ErrorPW:
                    pass   # la página está navegando o se está redibujando; se reintenta
            ahora = time.monotonic()
            if al_atascar is not None and not hubo_bloqueados and ahora - inicio >= ESPERA_RECUPERACION and ahora < fin:
                funcion, al_atascar = al_atascar, None
                funcion()
                continue
            if ahora >= fin:
                nombres = " | ".join(mod_flujo.describir_selector(s) for s in selectores)
                if hubo_bloqueados:
                    raise ErrorPaso("El elemento (%s) apareció pero sigue deshabilitado tras %g s" % (nombres, timeout))
                raise ErrorPaso("No apareció ningún elemento (%s) en %g s%s" % (nombres, timeout, self._pista()))
            if ahora >= proximo_aviso:
                self._avisar_espera(que, ahora - inicio, habilitado=habilitado or hubo_bloqueados)
                proximo_aviso += self.aviso_cada
            self._pausa(SONDEO)

    def _restante_ms(self, fin):
        return max(1000, int((fin - time.monotonic()) * 1000))

    def _accionar(self, pg, scope, paso, fin, accion, habilitado=True):
        """Localiza el elemento (visible y, si se pide, habilitado) y ejecuta `accion(loc, ms)`.

        Si la acción falla porque la página se redibujó (animaciones, calendarios…), vuelve a
        localizar y reintenta mientras quede tiempo.  En los clics, si el elemento no se ve, intenta
        una vez abrir el menú o la lista que lo contiene (ver `_recuperar`)."""
        from playwright.sync_api import Error as ErrorPW
        que = paso.nombre_objetivo() or "el elemento"
        intento = 0
        tapado = 0
        recuperar = None
        if paso.tipo in TIPOS_CON_RECUPERACION and self.recuperacion and self._recuperado_en != self._indice_actual:
            recuperar = lambda: self._recuperar(pg, scope, paso)    # noqa: E731
        while True:
            restante = fin - time.monotonic()
            loc = self._localizar(pg, scope, paso.selectores, max(restante, 0.5), habilitado=habilitado, que=que,
                                  al_atascar=recuperar if self._recuperado_en != self._indice_actual else None,
                                  guardia=True)
            ms = max(1000, min(self._restante_ms(fin), 15000))
            try:
                return accion(loc, ms)
            except ErrorPW as e:
                intento += 1
                if time.monotonic() >= fin - 0.5 or "has been closed" in str(e):
                    raise
                if "intercepts pointer events" in str(e):
                    # algo tapa el elemento (capa de «cargando…», ventanita): se espera a que termine y se reintenta
                    tapado += 1
                    if tapado >= 3 and paso.tipo in ("clic", "pasar_raton") and paso.boton == "izquierdo" \
                            and not paso.doble and self._accion_directa(loc, paso, que):
                        return None
                    if intento <= 3:
                        self._log("    (algo tapa %s: se espera a que la página termine de cargar y se reintenta)" % que)
                    self._esperar_carga(pg, minimo=0.3, forzar=True)
                elif intento <= 3:
                    self._log("    (reintento %d: %s)" % (intento, _primeras_lineas(e, 1)[:100]))
                self._pausa(0.3)

    def _accion_directa(self, loc, paso, que):
        """Algo (otro menú abierto, una capa) sigue tapando el elemento tras varios intentos: se le envía el evento
        directamente (clic → evento «click»; pasar el ratón → eventos de ratón encima).  True si funcionó."""
        from playwright.sync_api import Error as ErrorPW
        try:
            if paso.tipo == "pasar_raton":
                loc.hover(force=True, timeout=3000)
                for ev in ("mouseover", "mouseenter", "mousemove"):
                    loc.dispatch_event(ev)
            else:
                loc.dispatch_event("click")
        except ErrorPW:
            return False
        self._log("    (%s seguía tapado: se le envió el %s directamente)" % (
            que, "ratón" if paso.tipo == "pasar_raton" else "clic"))
        return True

    # ------------------------------------------------------------------ pasos
    def _ejecutar_paso(self, paso):
        from playwright.sync_api import Error as ErrorPW
        t = paso.tipo
        timeout = self._timeout_paso(paso)
        fin = time.monotonic() + timeout

        if t == "abrir_url":
            pg = self._pagina(paso.pagina, timeout)
            url = self._r(paso.url)
            self._log("    → %s" % self._r_log(paso.url))
            self._destinos[paso.pagina] = url
            pg.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            return

        if t == "esperar_segundos":
            self._dormir(max(0.0, float(paso.segundos)))
            return

        pg, scope = self._alcance(paso, timeout)

        if t == "iniciar_sesion":
            self._paso_iniciar_sesion(paso, pg, scope, fin)
            return

        if t == "esperar_texto":
            texto = self._r(paso.texto)
            # Un texto escrito tal cual con fechas u horas («… 24/10/2026 11:32 …») no se repetirá otro día:
            # basta con que aparezcan sus partes estables.  Con plantillas ({hoy}…) se busca el texto exacto.
            if plantillas.es_plantilla(paso.texto):
                trozos = [re.sub(r"\s+", " ", texto).strip()]
            else:
                trozos = mod_flujo.fragmentos_estables(texto) or [texto]
                if len(trozos) > 1 or trozos[0] != re.sub(r"\s+", " ", texto).strip():
                    self._log("    (el texto lleva fechas u horas que cambian: se buscan sus partes fijas: %s)"
                              % " … ".join("«%s»" % self._limpiar(f[:40]) for f in trozos))
            inicio = time.monotonic()
            proximo_aviso = inicio + self.aviso_cada
            while True:
                self._comprobar_detener()
                if self._toca_guardia(inicio, fin):
                    t0 = time.monotonic()
                    if self._guardia_login(pg):
                        fin += time.monotonic() - t0
                        continue
                try:
                    if pg.evaluate(JS_TEXTO_EN_PAGINA, trozos):
                        return
                except ErrorPW:
                    pass
                ahora = time.monotonic()
                if ahora >= fin:
                    raise ErrorPaso("No apareció el texto «%s» en %g s%s" % (self._r_log(paso.texto), timeout, self._pista()))
                if ahora >= proximo_aviso:
                    self._avisar_espera("«%s»" % self._r_log(paso.texto), ahora - inicio, habilitado=False)
                    proximo_aviso += self.aviso_cada
                self._pausa(SONDEO * 2)

        if t == "esperar_elemento":
            if paso.estado == "oculto":
                inicio = time.monotonic()
                proximo_aviso = inicio + self.aviso_cada
                while True:
                    self._comprobar_detener()
                    visible = False
                    for sel in paso.selectores:
                        try:
                            loc = scope.locator(sel)
                            if any(loc.nth(i).is_visible() for i in range(min(loc.count(), MAX_CANDIDATOS))):
                                visible = True
                        except ErrorPW:
                            visible = True
                    if not visible:
                        return
                    ahora = time.monotonic()
                    if ahora >= fin:
                        raise ErrorPaso("El elemento sigue visible tras %g s" % timeout)
                    if ahora >= proximo_aviso:
                        texto = "esperando a que desaparezca %s… %d s" % (paso.nombre_objetivo() or "el elemento",
                                                                         int(ahora - inicio))
                        self._log("    " + texto)
                        self.progreso(self._indice_actual, "espera", texto)
                        proximo_aviso += self.aviso_cada
                    self._pausa(SONDEO)
            self._esperar_aparezca(pg, scope, paso, fin)
            return

        if t == "tecla" and not paso.selectores:
            pg.keyboard.press(paso.tecla)
            return

        if t == "descargar":
            self._descargar(paso, pg, scope, timeout)
            return

        if t == "guardar_pagina":
            self._guardar_pagina(paso, pg, timeout)
            return

        if t == "elegir_opcion":
            self._paso_elegir_opcion(pg, scope, paso, fin)
            return

        if t == "clic":
            boton = {"izquierdo": "left", "derecho": "right", "medio": "middle"}[paso.boton]

            def hacer_clic(loc, ms):
                if paso.doble:
                    loc.dblclick(button=boton, timeout=ms)
                    return
                if boton == "left" and self._pestana_ya_elegida(loc):
                    self._log("    (la pestaña «%s» ya está elegida)" % (paso.nombre_objetivo() or "")[:60])
                    return
                loc.click(button=boton, timeout=ms)
            self._accionar(pg, scope, paso, fin, hacer_clic)
        elif t == "pasar_raton":
            self._accionar(pg, scope, paso, fin, lambda loc, ms: loc.hover(timeout=ms), habilitado=False)
            self._pausa(0.3)            # deja que el menú termine de abrirse
        elif t == "escribir":
            valor = self._r(paso.valor)
            self._log("    → %s" % self._valor_para_log(paso))
            self._paso_escribir(pg, scope, paso, fin, valor)
            if paso.filtro and not paso.es_secreto() and not paso.parece_contrasena():
                self._anotar_filtro(paso, valor)
        elif t == "tecla":
            self._accionar(pg, scope, paso, fin, lambda loc, ms: loc.press(paso.tecla, timeout=ms))
        elif t == "seleccionar":
            valor = self._r(paso.valor)
            self._log("    → %s" % self._r_log(paso.valor))
            self._elegidas[self._indice_actual] = paso.etiqueta or valor

            def elegir(loc, ms):
                try:
                    loc.select_option(value=valor, timeout=min(ms, 5000))
                except ErrorPW:
                    if not paso.etiqueta:
                        raise
                    loc.select_option(label=paso.etiqueta, timeout=ms)
            self._accionar(pg, scope, paso, fin, elegir)
        elif t == "marcar":
            self._accionar(pg, scope, paso, fin, lambda loc, ms: self._marcar_casilla(loc, bool(paso.marcado), ms))
        else:
            raise ErrorPaso("Tipo de paso desconocido: %s" % t)

    @staticmethod
    def _marcar_casilla(loc, marcado, ms):
        """v3.8: marca o desmarca.  Una casilla de verdad con `set_checked`; una dibujada (DevExpress: un <span>) con un
        clic solo si su estado es otro, comprobando después que cambió."""
        from playwright.sync_api import Error as ErrorPW
        try:
            estado = loc.evaluate(JS_CASILLA_MARCADA)
        except ErrorPW:
            estado = None
        es_input = False
        try:
            es_input = bool(loc.evaluate("e => e.tagName === 'INPUT' || e.getAttribute('role') === 'checkbox' || "
                                         "e.getAttribute('role') === 'switch'"))
        except ErrorPW:
            pass
        if es_input or estado is None:
            return loc.set_checked(marcado, timeout=ms)
        if estado == marcado:
            return None
        loc.click(timeout=ms)
        fin = time.monotonic() + min(ms, 5000) / 1000.0
        while time.monotonic() < fin:
            try:
                if loc.evaluate(JS_CASILLA_MARCADA) == marcado:
                    return None
            except ErrorPW:
                pass
            time.sleep(0.1)
        raise ErrorPaso("La casilla no cambió al hacer clic (sigue %s)" % ("marcada" if not marcado else "sin marcar"))

    @staticmethod
    def _pestana_ya_elegida(loc):
        from playwright.sync_api import Error as ErrorPW
        try:
            return bool(loc.evaluate(JS_PESTANA_ELEGIDA))
        except ErrorPW:
            return False

    def _valor_para_log(self, paso):
        """Texto de un paso «escribir» para el registro: nunca una contraseña, ni siquiera literal."""
        if paso.valor_literal_en_campo_contrasena():
            return "********"
        return self._r_log(paso.valor)

    @staticmethod
    def _tiene_valor(loc, valor):
        """True si el campo ya contiene exactamente `valor` (sin contar espacios de los extremos)."""
        from playwright.sync_api import Error as ErrorPW
        try:
            actual = loc.evaluate(JS_LEER_VALOR)
        except ErrorPW:
            return False
        return (actual or "").strip() == (valor or "").strip()

    def _paso_escribir(self, pg, scope, paso, fin, valor):
        """Paso «escribir»: espera al campo y escribe.

        - Si el campo ya tiene el valor (p. ej. lo puso la web al elegir una opción de una lista), no hace nada.
        - Si el campo se ve pero no parece disponible (solo lectura, sin eventos de ratón…) durante más de
          ESPERA_BLOQUEADO s, se escribe igualmente (JavaScript o, en listas con autocompletar, eligiendo la opción)."""
        from playwright.sync_api import Error as ErrorPW
        que = paso.nombre_objetivo() or "el campo"
        self._scope_escribir = scope
        inicio = time.monotonic()
        proximo_aviso = inicio + self.aviso_cada
        bloqueado_desde = None
        intento = 0
        while True:
            self._comprobar_detener()
            if self._toca_guardia(inicio, fin):
                t0 = time.monotonic()
                if self._guardia_login(pg):
                    fin += time.monotonic() - t0
                    continue
            visible = None
            habil = None
            try:
                for k, sel in enumerate(paso.selectores):
                    vis, _ = self._candidatos(scope, sel, visible=True, habilitado=False)
                    if not vis:
                        continue
                    visible = visible or self._elegir(vis)
                    hab = [c for c in vis if not c.evaluate(JS_BLOQUEADO)]
                    if hab:
                        habil = self._elegir(hab)
                        if k > 0:
                            self._log("    (usó el selector alternativo %d: %s)" % (k + 1, sel))
                        break
                if visible is None and time.monotonic() - inicio >= 1.0:
                    # oculto pero ya con el valor puesto: no hace falta escribir
                    for sel in paso.selectores:
                        loc = scope.locator(sel)
                        if loc.count() and self._tiene_valor(loc.first, valor):
                            self._log("    (el campo ya tenía el valor: no hace falta escribir)")
                            return
            except ErrorPW:
                visible = habil = None          # la página se está redibujando
            objetivo = habil or visible
            if objetivo is not None and valor and self._tiene_valor(objetivo, valor):
                self._log("    (el campo ya tenía el valor: no hace falta escribir)")
                return
            forzar = False
            if habil is None and visible is not None:
                bloqueado_desde = bloqueado_desde or time.monotonic()
                forzar = time.monotonic() - bloqueado_desde >= ESPERA_BLOQUEADO
            else:
                bloqueado_desde = None
            if habil is not None or forzar:
                if forzar:
                    self._log("    (el campo se ve pero no parece disponible: se escribe igualmente)")
                ms = max(1000, min(self._restante_ms(fin), 15000))
                try:
                    return self._escribir(pg, objetivo, valor, ms)
                except ErrorPW as e:
                    intento += 1
                    if time.monotonic() >= fin - 0.5 or "has been closed" in str(e):
                        raise
                    if intento <= 3:
                        self._log("    (reintento %d: %s)" % (intento, _primeras_lineas(e, 1)[:100]))
                    self._pausa(0.3)
                    continue
            ahora = time.monotonic()
            if ahora >= fin:
                nombres = " | ".join(mod_flujo.describir_selector(s) for s in paso.selectores)
                raise ErrorPaso("No apareció ningún campo (%s) en %g s%s" % (nombres, fin - inicio, self._pista()))
            if ahora >= proximo_aviso:
                self._avisar_espera(que, ahora - inicio, habilitado=True)
                proximo_aviso += self.aviso_cada
            self._pausa(SONDEO)

    def _escribir(self, pg, loc, valor, ms):
        """Escribe en un campo.  En campos de solo lectura (selectores de fecha) o si `fill` falla,
        pone el valor con JavaScript (eventos input + change + blur) y pulsa Escape para cerrar el calendario.
        En listas con autocompletar (combobox) escribe y elige la opción con ese texto."""
        from playwright.sync_api import Error as ErrorPW
        try:
            solo_lectura = bool(loc.evaluate(JS_SOLO_LECTURA))
        except ErrorPW:
            solo_lectura = False
        try:
            combo = bool(loc.evaluate(JS_ES_COMBO))
        except ErrorPW:
            combo = False
        if combo and self._escribir_combo(pg, loc, valor, ms, solo_lectura):
            return
        if self._fecha_devexpress(loc, valor):
            return
        if not solo_lectura:
            try:
                pistas = loc.evaluate(JS_PISTAS_FECHA)
            except ErrorPW:
                pistas = None
            try:
                loc.fill(valor, timeout=min(ms, 8000))
                if (self._valor_quedo(loc, valor) or self._fecha_al_formato_del_campo(loc, valor, pistas, ms)
                        or self._escribir_con_mascara(pg, loc, valor)):
                    return
                self._log("    (la página cambió lo escrito: se pone el valor directamente)")
            except ErrorPW as e:
                self._log("    (fill falló: %s; se pone el valor directamente)" % _primeras_lineas(e, 1)[:80])
        else:
            self._log("    (campo de solo lectura o selector de fecha: se escribe el valor directamente)")
        loc.evaluate(JS_PONER_VALOR, valor)
        try:
            pg.keyboard.press("Escape")      # cierra el calendario si quedó abierto
        except ErrorPW:
            pass
        actual = loc.evaluate(JS_LEER_VALOR)
        if (actual or "").strip() != valor.strip():
            raise ErrorPaso("No se pudo escribir el valor en el campo (la página lo rechazó o lo borró)")

    def _fecha_devexpress(self, loc, valor):
        """v3.8: si el campo es un calendario de DevExpress (ERP) y lo que se escribe es una fecha, la pone con la API del
        calendario (SetDate).  Devuelve True si quedó puesta; False para seguir escribiendo como siempre."""
        from playwright.sync_api import Error as ErrorPW
        fecha, _formato = leer_fecha(valor)
        if fecha is None:
            return False
        try:
            r = loc.evaluate(JS_DX_PONER_FECHA, [fecha.year, fecha.month, fecha.day])
        except ErrorPW:
            return False
        if not r:
            return False
        if not r.get("ok"):
            raise ErrorPaso("El calendario no aceptó la fecha «%s» (¿está fuera de las fechas que permite?)" % valor)
        self._log("    (calendario de DevExpress: fecha puesta en el calendario; se ve «%s»)" % self._limpiar(str(r.get("texto") or ""))[:30])
        return True

    @staticmethod
    def _valor_quedo(loc, valor):
        """v3.6.1: ¿el campo quedó con lo escrito?  (Si no se puede leer, se da por bueno, como antes.)"""
        from playwright.sync_api import Error as ErrorPW
        try:
            actual = loc.evaluate(JS_LEER_VALOR)
        except ErrorPW:
            return True
        if actual is None:
            return True
        return str(actual).strip() == str(valor).strip()

    def _fecha_al_formato_del_campo(self, loc, valor, pistas, ms):
        """v3.6.1: la casilla reordenó una FECHA (Informes: el reporte escribe «30/10/2026» y su máscara AAAA-MM-DD lo deja
        en «3010-20-26»).  Se mira qué formato usa la casilla (por su valor de antes, su placeholder o la forma en que
        dejó lo escrito) y se escribe la misma fecha en ese formato.  Devuelve True si el campo quedó bien."""
        from playwright.sync_api import Error as ErrorPW
        fecha, formato_valor = leer_fecha(valor)
        if fecha is None:
            return False
        try:
            escrito = str(loc.evaluate(JS_LEER_VALOR) or "")
        except ErrorPW:
            return False
        pistas = dict(pistas or {})
        for pista in (pistas.get("valor"), pistas.get("placeholder"), escrito):
            formato = formato_de_forma(pista)
            if not formato or formato == formato_valor:
                continue
            nuevo = fecha.strftime(formato)
            self._log("    (la casilla usa fechas como «%s» y dejó «%s»: se escribe «%s»)"
                      % (self._limpiar(str(pista))[:30], self._limpiar(escrito)[:30], nuevo))
            try:
                loc.fill(nuevo, timeout=min(ms, 8000))
            except ErrorPW:
                return False
            return self._valor_quedo(loc, nuevo)
        return False

    def _escribir_con_mascara(self, pg, loc, valor):
        """v3.6.1: campos con máscara (fechas «__/__/____»): `fill` pone todo de golpe y la máscara lo desordena
        («30/10/2026» → «3020/2/026»).  Se vacía y se teclea despacio como una persona: primero tal cual y, si la
        máscara pone ella las barras, solo los números.  Devuelve True si el campo quedó bien."""
        from playwright.sync_api import Error as ErrorPW
        self._log("    (la página cambió lo escrito a «%s»: se teclea despacio)"
                  % self._limpiar(str(loc.evaluate(JS_LEER_VALOR) or ""))[:60])
        intentos = [valor]
        solo_numeros = re.sub(r"\D", "", valor)
        if solo_numeros and solo_numeros != valor:
            intentos.append(solo_numeros)
        for texto in intentos:
            try:
                loc.click(timeout=3000)
                pg.keyboard.press("Control+A")
                pg.keyboard.press("Delete")
                pg.keyboard.press("Home")
                loc.press_sequentially(texto, delay=80, timeout=10000)
                pg.wait_for_timeout(200)
                if self._valor_quedo(loc, valor):
                    return True
            except ErrorPW:
                continue
        return False

    def _elegir_opcion(self, loc, valor, espera):
        """Busca (hasta `espera` s) una opción visible de una lista con el texto `valor` y hace clic en ella."""
        from playwright.sync_api import Error as ErrorPW
        inicio = time.monotonic()
        fin = inicio + espera
        while True:
            self._comprobar_detener()
            estado = None
            try:
                estado = loc.evaluate(JS_MARCAR_OPCION, valor)
                if estado == 2:
                    opcion = (self._scope_escribir or loc.page).locator('[data-bot-opcion="1"]').first
                    opcion.click(timeout=5000)
                    self._log("    (elegida la opción «%s» de la lista)" % self._limpiar(valor[:60]))
                    return True
            except ErrorPW:
                pass
            ahora = time.monotonic()
            if ahora >= fin or (estado == 0 and ahora - inicio >= 1.0):     # sin lista de opciones: no se espera más
                return False
            self._pausa(SONDEO)

    def _escribir_combo(self, pg, loc, valor, ms, solo_lectura):
        """Lista con autocompletar: escribe el texto (o abre la lista si no se puede escribir) y elige la
        opción con ese texto.  Devuelve False si no encontró la opción (se sigue con la escritura normal)."""
        from playwright.sync_api import Error as ErrorPW
        if not valor:
            return False
        escrito = False
        if not solo_lectura:
            try:
                loc.fill(valor, timeout=min(ms, 8000))
                escrito = True
            except ErrorPW:
                escrito = False
        if not escrito:
            try:
                loc.click(timeout=3000, force=True)        # abre la lista
            except ErrorPW:
                pass
        if self._elegir_opcion(loc, valor, 2.5):
            return True
        if escrito:
            self._log("    (no apareció ninguna opción «%s» en la lista: se deja el texto escrito)" % self._limpiar(valor[:60]))
            return True
        return False

    # ------------------------------------------------------ elegir opción (v3.0)
    def _paso_elegir_opcion(self, pg, scope, paso, fin):
        """Paso «Elegir opción»: abre la lista (nativa o propia), lee sus opciones y elige según la estrategia."""
        que = paso.nombre_objetivo() or "la lista"
        loc = self._localizar(pg, scope, paso.selectores, max(fin - time.monotonic(), 0.5), habilitado=False, que=que,
                              guardia=True)
        valor = self._r(paso.valor) if paso.valor else ""
        est = paso.estrategia or "fija"
        nativo = loc.evaluate(JS_SELECT_NATIVO)
        if nativo is not None:
            textos = [o["texto"] for o in nativo if not o.get("desactivada")]
            self.anotar_opciones_leidas(self._indice_actual, paso, textos)
            k = self._elegir_o_seguir(textos, est, valor, que)
            if k is None:
                raise ErrorPaso(self._sin_opcion(que, est, valor, textos))
            elegido = next(i for i, o in enumerate(nativo) if not o.get("desactivada") and o["texto"] == textos[k])
            scope.locator('[data-bot-select="1"]').first.select_option(index=elegido, timeout=self._restante_ms(fin))
            self._log("    → «%s» (%s; %d opciones)" % (self._limpiar(textos[k][:80]), est, len(textos)))
            self.opcion_elegida = textos[k]
            self.variables["opcion"] = textos[k]
            self._anotar_filtro(paso, textos[k])
            self._elegidas[self._indice_actual] = textos[k]
            return textos[k]
        textos = self.leer_opciones(pg, scope, loc, fin, cerrar=False)
        self.anotar_opciones_leidas(self._indice_actual, paso, textos)
        k = self._elegir_o_seguir(textos, est, valor, que)
        if k is None:
            self._cerrar_lista(pg, loc)
            raise ErrorPaso(self._sin_opcion(que, est, valor, textos))
        self._log("    → «%s» (%s; %d opciones)" % (self._limpiar(textos[k][:80]), est, len(textos)))
        self._pulsar_opcion(pg, scope, loc, textos[k], fin)
        self.opcion_elegida = textos[k]
        self.variables["opcion"] = textos[k]
        self._anotar_filtro(paso, textos[k])
        self._elegidas[self._indice_actual] = textos[k]
        return textos[k]

    def _anotar_filtro(self, paso, texto):
        """v3.2: lo elegido en un filtro con nombre queda como variable {Nombre del filtro} (nombre de los archivos de
        las Páginas: «{Elegir corte}» = el corte que se eligió de verdad, también con «la más reciente»)."""
        nombre = (paso.filtro or "").strip()
        if nombre and nombre not in plantillas.RESERVADAS:
            self.variables[nombre] = texto

    def _elegir_o_seguir(self, textos, est, valor, que):
        k = mod_flujo.elegir_indice(textos, est, valor)
        if k is None and self.solo_leer and textos:
            k = mod_flujo.elegir_indice(textos, "primera")
            self._log("    (%s no tiene «%s»: para seguir leyendo las listas se elige «%s»)" % (
                que, self._limpiar(valor[:60]), self._limpiar(textos[k][:60])))
        return k

    def padres_de(self, indice):
        """Lo elegido en las listas anteriores al paso `indice` en esta ejecución ({paso: texto})."""
        return {k: v for k, v in self._elegidas.items() if k < int(indice)}

    def anotar_opciones_leidas(self, indice, paso, textos):
        """v3.1: guarda en el resultado la lista leída de un filtro (con lo elegido antes) para las opciones del filtro."""
        if textos is None:
            return
        from . import filtros as mod_filtros
        self.resultado.opciones_leidas[int(indice)] = {"opciones": list(textos), "padres": self.padres_de(indice),
                                                       "firma": mod_filtros.firma_paso(paso)}

    def _sin_opcion(self, que, est, valor, textos):
        lista = ", ".join("«%s»" % t[:40] for t in textos[:8]) + (" …" if len(textos) > 8 else "")
        if est == "por_fecha":              # v3.8: nunca se baja otro: se dice claro qué pasó
            fecha = mod_flujo.fecha_de_valor(valor)
            if fecha is None:
                return "La fecha «%s» de %s no se entiende: elígela otra vez en el calendario" % (self._limpiar(valor[:40]), que)
            return "El reporte del %s todavía no ha salido (%s: %s). No se baja otro." % (
                fecha.strftime("%d/%m/%Y"), que, lista or "sin opciones")
        if est in ("fija", "contiene"):
            return "No hay ninguna opción «%s» en %s (opciones: %s)" % (self._limpiar(valor[:60]), que, lista or "ninguna")
        return "La lista %s no tiene opciones%s" % (que, (" (%s)" % lista) if lista else "")

    def _leer_lista(self, loc, **arg):
        from playwright.sync_api import Error as ErrorPW
        try:
            r = loc.evaluate(JS_OPCIONES, arg)
        except ErrorPW:
            r = None
        return r if isinstance(r, dict) else {"n": 0, "textos": [], "abierta": False, "puede_bajar": False,
                                              "elegida": False}

    def _abrir_lista(self, pg, scope, loc, fin):
        """Abre la lista del campo (si no estaba abierta) y devuelve la primera lectura de sus opciones."""
        from playwright.sync_api import Error as ErrorPW
        r = self._leer_lista(loc)
        try:
            expandido = bool(loc.evaluate(JS_EXPANDIDO))
        except ErrorPW:
            expandido = False
        if r["n"] and expandido:
            return r

        def clic(objetivo):
            try:
                objetivo.click(timeout=min(5000, self._restante_ms(fin)))
            except ErrorPW as e:
                if "intercepts pointer events" not in str(e):
                    raise
                objetivo.dispatch_event("mousedown")
                objetivo.dispatch_event("click")

        def clic_si_hay(objetivo):
            if not objetivo.count():
                raise ErrorPW("no hay botón de lista")
            clic(objetivo)

        intentos = [lambda: clic(loc),
                    lambda: clic(loc.locator("[role=combobox], input, .v-field__append-inner, [class*=arrow], [class*=caret]").first),
                    # v3.3: el botón de la lista de DevExpress (ASPxComboBox: «…_B-1»)
                    lambda: clic_si_hay(loc.locator("[id$='_B-1'], .dxeButtonEditButton, td[class*=dxeButton]").first),
                    lambda: loc.press("ArrowDown", timeout=2000)]
        for k, intento in enumerate(intentos):
            try:
                intento()
            except ErrorPW:
                continue
            limite = time.monotonic() + (2.5 if k == 0 else 1.5)
            while time.monotonic() < limite:
                self._comprobar_detener()
                self._pausa(0.12)
                r = self._leer_lista(loc)
                if r["n"]:
                    self._pausa(0.15)              # deja terminar la animación (y que se dibujen las opciones)
                    return self._leer_lista(loc)
            if time.monotonic() >= fin:
                break
        raise ErrorPaso("No se abrió la lista de opciones de %s" % "el campo")

    def leer_opciones(self, pg, scope, loc, fin=None, cerrar=True):
        """Abre la lista del campo `loc` y devuelve los textos de TODAS sus opciones, en orden (en las listas
        virtuales, que solo dibujan lo que se ve, la va desplazando).  Las listas nativas se leen directamente."""
        fin = fin or (time.monotonic() + 20)
        nativo = loc.evaluate(JS_SELECT_NATIVO)
        if nativo is not None:
            return [o["texto"] for o in nativo if not o.get("desactivada") and o["texto"]]
        r = self._abrir_lista(pg, scope, loc, fin)
        textos = []

        def anadir(lectura):
            for t in lectura.get("textos") or []:
                if t not in textos:
                    textos.append(t)
        if r.get("puede_bajar") or self._leer_lista(loc, arriba=True).get("puede_bajar"):
            self._pausa(0.12)
            r = self._leer_lista(loc)
            for _ in range(80):
                anadir(r)
                if not r.get("puede_bajar") or time.monotonic() >= fin:
                    break
                self._leer_lista(loc, bajar=True)
                self._pausa(0.12)
                r = self._leer_lista(loc)
            anadir(r)
        else:
            anadir(r)
        if cerrar:
            self._cerrar_lista(pg, loc)
        return textos

    def _pulsar_opcion(self, pg, scope, loc, texto, fin):
        from playwright.sync_api import Error as ErrorPW
        r = self._leer_lista(loc, buscar=texto)
        if not r.get("abierta") or not r.get("n"):
            self._abrir_lista(pg, scope, loc, fin)
            r = self._leer_lista(loc, buscar=texto)
        if not r.get("elegida"):
            self._leer_lista(loc, arriba=True)
            self._pausa(0.12)
            for _ in range(80):
                r = self._leer_lista(loc, buscar=texto)
                if r.get("elegida") or not r.get("puede_bajar") or time.monotonic() >= fin:
                    break
                self._leer_lista(loc, bajar=True)
                self._pausa(0.12)
                r = self._leer_lista(loc, buscar=texto)
                if r.get("elegida"):
                    break
        if not r.get("elegida"):
            raise ErrorPaso("No se pudo pulsar la opción «%s»" % self._limpiar(texto[:60]))
        op = scope.locator('[data-bot-op-elegida="1"]').first
        try:
            op.scroll_into_view_if_needed(timeout=3000)
            op.click(timeout=min(8000, self._restante_ms(fin)))
        except ErrorPW as e:
            if "intercepts pointer events" not in str(e) and "not visible" not in str(e):
                raise
            op.dispatch_event("click")
        self._pausa(0.25)
        r = self._leer_lista(loc)
        if r.get("abierta") and r.get("n") and texto in (r.get("textos") or []):
            self._cerrar_lista(pg, loc)          # listas que no se cierran solas (selección múltiple…)

    def _cerrar_lista(self, pg, loc):
        from playwright.sync_api import Error as ErrorPW
        try:
            pg.keyboard.press("Escape")
            self._pausa(0.2)
            r = self._leer_lista(loc)
            if r.get("abierta") and r.get("n") and bool(loc.evaluate(JS_EXPANDIDO)):
                loc.click(timeout=3000)
                self._pausa(0.2)
        except ErrorPW:
            pass

    # ----------------------------------------------------- esperas de carga
    def _carga_activa(self, paso=None):
        """¿Se espera a que la página termine de cargar?  Paso (sí/no) > parámetro del ejecutor > opción del flujo."""
        if paso is not None and paso.esperar_carga is not None:
            return bool(paso.esperar_carga)
        if self.esperar_carga is not None:
            return bool(self.esperar_carga)
        return self.flujo.opcion("esperar_carga") is not False

    def _seguir_red(self, pg):
        """Apunta las peticiones de la página (para saber si sigue cargando).  Se ignoran websockets, sondeos
        periódicos y analítica."""
        red = {"vuelo": {}, "ultima": time.monotonic(), "historial": {}}
        self._red[pg] = red

        def inicio(req):
            try:
                tipo, url, metodo = req.resource_type, req.url, req.method
            except Exception:          # noqa: BLE001 (la página se cerró)
                return
            if tipo in TIPOS_RED_IGNORADOS or url.startswith(("data:", "blob:", "chrome-extension:")) \
                    or RX_RED_IGNORAR.search(url):
                return
            ahora = time.monotonic()
            clave = "%s %s" % (metodo, url.split("#")[0].split("?")[0])
            hist = [t for t in red["historial"].get(clave, []) if ahora - t < 10.0]
            hist.append(ahora)
            red["historial"][clave] = hist
            if len(red["historial"]) > 400:
                red["historial"] = {k: v for k, v in red["historial"].items() if v and ahora - v[-1] < 10.0}
            if len(hist) >= SONDEO_REPETIDO and tipo in ("xhr", "fetch", "other"):
                # la página consulta periódicamente esa dirección: no cuenta (tampoco las que ya se apuntaron;
                # a veces nunca «terminan» porque la página no lee la respuesta)
                for r, (_t, k) in list(red["vuelo"].items()):
                    if k == clave:
                        red["vuelo"].pop(r, None)
                return
            red["vuelo"][req] = (ahora, clave)
            red["ultima"] = ahora

        def fin(req):
            if red["vuelo"].pop(req, None) is not None:
                red["ultima"] = time.monotonic()

        def respuesta(resp):
            # una petición de datos (xhr/fetch) ya contestó: basta (si la página no lee el cuerpo, «requestfinished»
            # puede no llegar nunca)
            try:
                req = resp.request
                if req.resource_type in ("xhr", "fetch"):
                    fin(req)
            except Exception:          # noqa: BLE001
                pass

        try:
            pg.on("request", inicio)
            pg.on("response", respuesta)
            pg.on("requestfinished", fin)
            pg.on("requestfailed", fin)
        except Exception:              # noqa: BLE001
            pass

    def _estado_red(self, pg):
        """(pendientes_recientes, pendientes_todas, segundos_sin_peticiones)."""
        red = self._red.get(pg)
        if red is None:
            return 0, 0, 999.0
        ahora = time.monotonic()
        tiempos = [t for t, _k in list(red["vuelo"].values())]
        recientes = sum(1 for t in tiempos if ahora - t < RED_MAX_EDAD)
        return recientes, len(tiempos), ahora - red["ultima"]

    def _marcos_de(self, pg):
        """Documento principal y (hasta 4) marcos de la misma web, donde se miran los indicadores de carga."""
        try:
            principal = pg.main_frame
            marcos = [principal]
            host = mod_flujo.host_de(pg.url)
            for fr in pg.frames:
                if fr is principal or len(marcos) >= 5:
                    continue
                try:
                    if fr.is_detached() or not fr.url or fr.url == "about:blank":
                        continue
                except Exception:      # noqa: BLE001
                    continue
                if mod_flujo.host_de(fr.url) in (host, ""):
                    marcos.append(fr)
            return marcos
        except Exception:              # noqa: BLE001
            return []

    def _estado_documentos(self, pg, marcar=False):
        """Junta el estado de carga de los documentos de la página (None si la página está cambiando)."""
        from playwright.sync_api import Error as ErrorPW
        total = {"listo": "complete", "jq": 0, "asp": False, "ind": [], "mut": 0}
        marcos = self._marcos_de(pg)
        if not marcos:
            return None
        for k, fr in enumerate(marcos):
            try:
                r = fr.evaluate(JS_ESTADO_CARGA, bool(marcar))
            except ErrorPW:
                if k == 0:
                    return None        # el documento principal está navegando
                continue
            if not isinstance(r, dict):
                continue
            if r.get("listo") != "complete" and (k == 0 or r.get("listo") == "loading"):
                total["listo"] = r.get("listo")
            total["jq"] += int(r.get("jq") or 0)
            total["asp"] = total["asp"] or bool(r.get("asp"))
            total["ind"] += list(r.get("ind") or [])
            total["mut"] += int(r.get("mut") or 0)
        return total

    def _esperar_carga(self, pg, minimo=0.3, forzar=False, paso=None):
        """Espera a que la página termine de cargar:

        - la página terminó de abrirse (readyState «complete») y no hay peticiones pendientes durante 0,5 s
          (sin contar websockets, sondeos periódicos ni analítica) y jQuery no tiene peticiones activas: espera
          «corta», como mucho `espera_red_max` (30 s) y luego se sigue igualmente;
        - mientras se vea un indicador de carga nuevo (rueda, barra, «Cargando…», panel de DevExpress, aria-busy,
          capa que tapa la página) o ASP.NET esté actualizando la página: espera «larga», hasta `timeout_descarga`
          (600 s), avisando cada ~15 s.  Un indicador que no desaparece aunque la página no haga nada durante
          30 s se da por atascado.
        `minimo`: segundos que se observa como poco (tras una acción, por si la petición tarda en empezar)."""
        from playwright.sync_api import Error as ErrorPW
        if pg is None or (not forzar and not self._carga_activa(paso)):
            return
        try:
            if pg.is_closed():
                return
        except Exception:              # noqa: BLE001
            return
        inicio = time.monotonic()
        largo = float(self.flujo.opcion("timeout_descarga") or mod_flujo.OPCIONES_DEFECTO["timeout_descarga"])
        corto = min(self.espera_red_max, largo)
        proximo_aviso = inicio + self.aviso_cada
        ultimo_mut, t_mut = None, inicio
        motivo = ""
        debiles_vistos_desde = None
        ignorar_debiles = False
        while True:
            self._comprobar_detener()
            ahora = time.monotonic()
            dur = ahora - inicio
            try:
                if pg.is_closed():
                    return
                est = self._estado_documentos(pg)
            except ErrorPW:
                est = None
            recientes, todas, quieta = self._estado_red(pg)
            cortos, largos, debiles = [], [], []
            if est is None:
                cortos.append("la página está cambiando")
            else:
                if est["listo"] != "complete":
                    cortos.append("la página se está abriendo")
                if est["jq"]:
                    cortos.append("peticiones de jQuery")
                if est["asp"]:
                    largos.append("la página se está actualizando (ASP.NET)")
                for ind in est["ind"]:
                    if not ind.get("pre") or todas or est["asp"] or est["jq"]:
                        if ind.get("fuerte", True):
                            largos.append("indicador %s" % ind.get("d"))
                        elif not ignorar_debiles:
                            debiles.append("indicador %s" % ind.get("d"))
                if est["mut"] != ultimo_mut:
                    ultimo_mut, t_mut = est["mut"], ahora
            if recientes:
                cortos.append("%d petición%s pendiente%s" % (recientes, "" if recientes == 1 else "es",
                                                             "" if recientes == 1 else "s"))
            red_ok = not recientes and quieta >= QUIETUD_RED
            if debiles:
                # capa o «busy» sin rueda de carga dentro: solo se espera mientras la página hace algo (≈3 s sin
                # actividad y se sigue; como mucho 10 s si solo cambia el dibujo, p. ej. animaciones)
                debiles_vistos_desde = debiles_vistos_desde or ahora
                tranquila = not recientes and quieta >= self.espera_estancada_debil
                if tranquila and (ahora - t_mut >= self.espera_estancada_debil
                                  or ahora - debiles_vistos_desde >= 10.0):
                    self._log("    (%s no parece una rueda de carga y la página no hace nada desde hace %d s: se continúa)"
                              % (debiles[0], int(min(ahora - t_mut, ahora - debiles_vistos_desde))))
                    ignorar_debiles = True
                    debiles = []
            cortos += debiles
            if largos and est is not None and not todas and not est["asp"] and not est["jq"] \
                    and ahora - t_mut >= self.espera_estancada:
                self._log("    (un indicador de carga sigue visible pero la página no hace nada desde hace %d s: se continúa)"
                          % int(ahora - t_mut))
                try:
                    self._estado_documentos(pg, marcar=True)     # ya no se espera por él
                except ErrorPW:
                    pass
                largos = []
                if not cortos:
                    break
            if not cortos and not largos and red_ok and dur >= minimo:
                break
            motivo = (largos or cortos or ["peticiones recientes"])[0]
            if largos:
                if dur >= largo:
                    self._log("    (la página sigue cargando tras %d s (%s): se continúa)" % (int(dur), motivo))
                    break
            elif dur >= corto:
                self._log("    (la página sigue ocupada tras %d s (%s): se continúa)" % (int(dur), motivo))
                break
            if ahora >= proximo_aviso:
                texto = "esperando a que termine de cargar… %d s (%s)" % (int(dur), motivo)
                self._log("    " + texto)
                self.progreso(self._indice_actual, "espera", texto)
                proximo_aviso += self.aviso_cada
            self._pausa(SONDEO)
        dur = time.monotonic() - inicio
        if dur >= 2.0:
            self._log("    (la página tardó %.1f s en terminar de cargar%s)" % (dur, (": " + motivo) if motivo else ""))

    def _pagina_tranquila(self, pg):
        """True si ahora mismo la página no está cargando nada (sin esperar)."""
        from playwright.sync_api import Error as ErrorPW
        try:
            est = self._estado_documentos(pg)
        except ErrorPW:
            return False
        recientes, _, quieta = self._estado_red(pg)
        if est is None or est["listo"] != "complete" or est["jq"] or est["asp"] or recientes or quieta < QUIETUD_RED:
            return False
        return not any(not i.get("pre") and i.get("fuerte", True) for i in est["ind"])

    def _pagina_si_existe(self, indice):
        if 0 <= indice < len(self.paginas):
            pg = self.paginas[indice]
            try:
                return None if pg.is_closed() else pg
            except Exception:          # noqa: BLE001
                return None
        return None

    def _preparar_accion(self, indice):
        """Antes de una acción: (1) marca los indicadores de carga que ya se ven (no se esperarán con el tope
        largo); (2) marca, en las esperas «hasta que aparezca» que siguen, lo que ya coincide con sus selectores
        alternativos, para que no se den por buenas con un elemento que ya estaba antes de la acción."""
        from playwright.sync_api import Error as ErrorPW
        paso = self.flujo.pasos[indice]
        pg = self._pagina_si_existe(paso.pagina)
        if pg is not None:
            try:
                self._estado_documentos(pg, marcar=True)
            except ErrorPW:
                pass
        for j in range(indice + 1, len(self.flujo.pasos)):
            sig = self.flujo.pasos[j]
            if sig.desactivado or sig.tipo == "esperar_segundos":
                continue
            if sig.tipo not in ("esperar_elemento", "esperar_texto"):
                break
            if sig.tipo != "esperar_elemento" or sig.estado == "oculto" or len(sig.selectores) < 2:
                continue
            pg2 = self._pagina_si_existe(sig.pagina)
            if pg2 is None:
                continue
            scope = pg2
            for marco in sig.marco:
                scope = scope.frame_locator(marco)
            try:
                for sel in sig.selectores[1:]:
                    loc = scope.locator(sel)
                    for k in range(min(loc.count(), 10)):
                        cand = loc.nth(k)
                        if cand.is_visible():
                            cand.evaluate(JS_MARCAR_PREVIO, j)
                self._previos.add(j)
            except ErrorPW:
                continue

    def _esperar_aparezca(self, pg, scope, paso, fin):
        """Paso «Esperar hasta que aparezca»: el primer selector vale siempre; los alternativos solo si encuentran
        algo nuevo o que cambió desde antes de la acción anterior.  Si solo coincide lo que ya estaba, se acepta
        cuando la página lleva un rato sin cargar nada (como en las versiones anteriores, pero sin adelantarse)."""
        from playwright.sync_api import Error as ErrorPW
        j = self._indice_actual
        marcado = j in self._previos
        inicio = time.monotonic()
        proximo_aviso = inicio + self.aviso_cada
        gracia = min(30.0, max(5.0, float(paso.espera_grabada or 0)))
        solo_previos_desde = None
        que = paso.nombre_objetivo() or "el elemento"
        while True:
            self._comprobar_detener()
            if self._toca_guardia(inicio, fin):
                t0 = time.monotonic()
                if self._guardia_login(pg):
                    fin += time.monotonic() - t0
                    continue
            hay_previo = False
            for k, sel in enumerate(paso.selectores):
                try:
                    cands, _ = self._candidatos(scope, sel, visible=True, habilitado=False)
                    if cands and k > 0 and marcado:
                        nuevos = [c for c in cands if c.evaluate(JS_ES_NUEVO, j)]
                        if not nuevos:
                            hay_previo = True
                            continue
                        cands = nuevos
                except ErrorPW:
                    continue
                if cands:
                    if k > 0:
                        self._log("    (usó el selector alternativo %d: %s)" % (k + 1, sel))
                    return self._elegir(cands)
            ahora = time.monotonic()
            if hay_previo:
                solo_previos_desde = solo_previos_desde or ahora
                if ahora - solo_previos_desde >= gracia and self._pagina_tranquila(pg):
                    self._log("    (solo coincide un elemento que ya estaba antes del paso anterior y la página ya "
                              "terminó de cargar: se da por bueno)")
                    return None
            else:
                solo_previos_desde = None
            if ahora >= fin:
                nombres = " | ".join(mod_flujo.describir_selector(s) for s in paso.selectores)
                extra = " (solo estaba el que ya había antes del paso anterior)" if hay_previo else ""
                raise ErrorPaso("No apareció ningún elemento (%s) en %g s%s%s" % (nombres, fin - inicio, extra,
                                                                                  self._pista()))
            if ahora >= proximo_aviso:
                self._avisar_espera(que, ahora - inicio, habilitado=False)
                proximo_aviso += self.aviso_cada
            self._pausa(SONDEO)

    # ------------------------------------------------------ inicio de sesión
    def _pista(self):
        return (" — " + self._pista_login) if self._pista_login else ""

    def _toca_guardia(self, inicio, fin):
        """¿Toca mirar (una vez por paso) si la página pide iniciar sesión?  A los ~3 s sin ver el elemento
        (1,5 s si el paso anterior fue «Abrir la página»), si queda tiempo en el paso."""
        if self._guardia_en == self._indice_actual:
            return False
        ahora = time.monotonic()
        umbral = ESPERA_LOGIN_TRAS_ABRIR if self._tras_abrir else ESPERA_LOGIN
        if ahora - inicio < umbral or fin - ahora <= 1.0:
            return False
        paso = self.flujo.pasos[self._indice_actual] if 0 <= self._indice_actual < len(self.flujo.pasos) else None
        if paso is not None and paso.tipo == "iniciar_sesion":
            return False
        self._guardia_en = self._indice_actual
        return True

    def _analizar_login(self, scope):
        """Formulario de inicio de sesión de la página (ver JS_ANALIZAR_LOGIN)."""
        r = scope.locator("html").first.evaluate(JS_ANALIZAR_LOGIN, None)
        if not isinstance(r, dict):
            return {"hay": False, "campos": [], "enviar": False, "error": "", "firma": ""}
        return r

    def _paso_login_de(self, host):
        for p in self.flujo.pasos:
            if p.tipo == "iniciar_sesion" and not p.desactivado and (p.sitio or host) == host:
                return p
        return None

    def _accesos_de(self, host):
        try:
            return list(self.accesos.accesos_de(host) or [])
        except Exception as e:         # noqa: BLE001 (la base de datos no debe tumbar la ejecución)
            self._log("    (no se pudieron leer los accesos guardados: %s)" % type(e).__name__)
            return []

    def _guardia_login(self, pg):
        """El elemento de un paso no aparece: si la página muestra un formulario de inicio de sesión (la sesión
        caducó, o el reporte se grabó con la sesión ya abierta), se inicia sesión con los datos del paso «Iniciar
        sesión» del reporte o con los accesos guardados del sitio (o se piden al usuario) y se sigue con el paso.
        v3.3.1: si después la web lleva a otra página (Portal: siempre a «Inicio»), se vuelve a la que iba el reporte.
        Devuelve True si inició sesión."""
        from playwright.sync_api import Error as ErrorPW
        try:
            analisis = self._analizar_login(pg)
        except ErrorPW:
            return False
        if not analisis.get("hay"):
            return False
        host = mod_flujo.host_de(pg.url)
        paso_login = self._paso_login_de(host)
        if paso_login is None and not self._accesos_de(host) and self._pedir_acceso is None:
            self._pista_login = ("la página «%s» pide iniciar sesión. %s" % (host, mod_accesos.MENSAJE_SIN_VENTANA % host))
            self._log("    (la página «%s» pide iniciar sesión, pero no hay datos guardados para hacerlo)" % host)
            return False
        self._log("    (la página «%s» pide iniciar sesión: se inicia sesión y después se sigue con el paso)" % host)
        url_formulario = pg.url
        self._hacer_login(pg, pg, host, paso_login, analisis, time.monotonic() + 90)
        self._esperar_carga(pg, minimo=0.3, forzar=True)
        self._volver_tras_login(pg, url_formulario)
        return True

    def _volver_tras_login(self, pg, url_formulario=None):
        """v3.3.1: tras iniciar sesión, si la web llevó a otra página (p. ej. Portal va siempre a «Inicio» aunque se
        abriera «…/#/reportes/corte»), se vuelve a abrir la dirección a la que iba el reporte (su último «Abrir la
        página») y se espera a que cargue.  `url_formulario`: dónde estaba el formulario; si estaba en esa misma
        dirección y después de entrar la web pasó a OTRA página (no solo a otra ruta «#/…»), esa dirección era la propia
        página de inicio de sesión (p. ej. «index.html» → «reportes.html») y no se vuelve a ella."""
        from playwright.sync_api import Error as ErrorPW
        try:
            indice = self.paginas.index(pg)
        except ValueError:
            return False
        destino = self._destinos.get(indice)
        try:
            actual = pg.url
        except ErrorPW:
            return False
        if not hay_que_volver(actual, destino):
            return False
        if url_formulario and misma_direccion(url_formulario, destino) and _partes_url(destino)[0] != _partes_url(actual)[0]:
            return False
        self._log("    tras iniciar sesión la web fue a «%s»: se vuelve a «%s»" % (self._limpiar(actual)[:150],
                                                                              self._limpiar(destino)[:150]))
        try:
            pg.goto(destino, wait_until="domcontentloaded", timeout=60000)
        except ErrorPW as e:
            self._log("    (no se pudo volver a «%s»: %s)" % (self._limpiar(destino)[:150], _primeras_lineas(e, 1)[:100]))
            return False
        self._esperar_carga(pg, minimo=0.5, forzar=True)
        return True

    def _paso_iniciar_sesion(self, paso, pg, scope, fin):
        """Paso «Iniciar sesión (si hace falta)»: si no se ve el formulario (ya había una sesión abierta) se omite;
        si se ve, se rellena, se envía y se comprueba que la página lo aceptó."""
        from playwright.sync_api import Error as ErrorPW
        host = paso.sitio or mod_flujo.host_de(pg.url)
        self._esperar_carga(pg, minimo=0, paso=paso)
        limite = time.monotonic() + min(4.0, max(0.5, fin - time.monotonic() - 1))
        analisis = {"hay": False}
        while True:
            self._comprobar_detener()
            try:
                analisis = self._analizar_login(scope)
            except ErrorPW:
                analisis = {"hay": False}
            if analisis.get("hay") or self._algun_campo_visible(scope, paso):
                break
            if time.monotonic() >= limite:
                self._log("    ya había una sesión abierta: se omite")
                return
            self._pausa(0.25)
        if not analisis.get("hay"):
            self._log("    (se ve un campo del inicio de sesión pero no el de la contraseña; se rellena igualmente)")
        url_formulario = pg.url
        self._hacer_login(pg, scope, host, paso, analisis, max(fin, time.monotonic() + 30))
        if not paso.marco:
            self._esperar_carga(pg, minimo=0.3, forzar=True)
            self._volver_tras_login(pg, url_formulario)

    def _algun_campo_visible(self, scope, paso):
        from playwright.sync_api import Error as ErrorPW
        for c in paso.campos:
            for sel in c.get("selectores") or []:
                try:
                    loc = scope.locator(sel)
                    if any(loc.nth(i).is_visible() for i in range(min(loc.count(), 5))):
                        return True
                except ErrorPW:
                    continue
        return False

    def _secreto_o_nada(self, nombre):
        if not nombre:
            return None
        try:
            return self._secreto(nombre)
        except secretos.ErrorSecreto:
            return None

    def _marca_login(self, scope, selectores):
        """Número (data-bot-login) del campo analizado al que apuntan los selectores, o None."""
        from playwright.sync_api import Error as ErrorPW
        for sel in selectores or []:
            try:
                loc = scope.locator(sel)
                if loc.count():
                    k = loc.first.get_attribute("data-bot-login", timeout=2000)
                    if k is not None:
                        return k
            except ErrorPW:
                continue
        return None

    @staticmethod
    def _identidades(host, *textos, selectores=None):
        ids = []
        for t in textos:
            i = mod_accesos.identidad_campo(t, host)
            if i and i not in ids:
                ids.append(i)
        for i in mod_accesos.identidades_de_selectores(selectores):
            if i not in ids:
                ids.append(i)
        return ids

    def _visible_por_selectores(self, scope, selectores):
        from playwright.sync_api import Error as ErrorPW
        for sel in selectores or []:
            try:
                loc = scope.locator(sel)
                for i in range(min(loc.count(), 5)):
                    if loc.nth(i).is_visible():
                        return True
                    clon = loc.nth(i).evaluate("e => { const c = e.id ? document.getElementById(e.id + '_CLND') : null; "
                                               "return !!(c && c.getClientRects().length); }")
                    if clon:
                        return True
            except ErrorPW:
                continue
        return False

    def _plan_login(self, scope, host, paso, analisis, incluir=()):
        """Qué campos rellenar y con qué: [{clave, nombre, etiqueta, tipo, selectores, valor, secreto, necesario,
        del_usuario, ids}].  Orden de preferencia de los valores: accesos guardados del sitio (los confirmó el usuario)
        > lo grabado en el paso > contraseña guardada con el nombre del grabador («host:campo»).

        v3.3.1: el mismo campo escrito de varias formas (`X`, `X_I`, `X_I_CLND`, `ctl00$a$b` / `ctl00_a_b`, la
        contraseña «host:ctl00$a$b») es UNO solo; los campos que Accesos conoce para el sitio y el paso grabado no lleva
        (p. ej. «Licencia») se rellenan también; `incluir` = identidades de campos que hay que pedir aunque no se sepa su
        valor (la página dijo que son obligatorios)."""
        guardados = list(self._accesos_de(host))
        ids_guardado = []
        for a in guardados:
            ids_guardado.append(self._identidades(host, a.get("clave"), a.get("secreto"),
                                                  selectores=a.get("selectores")))
        usados_g = set()

        def guardado_de(ids):
            for n, g_ids in enumerate(ids_guardado):
                if set(ids) & set(g_ids):
                    usados_g.add(n)
                    return guardados[n]
            return {}

        vivos = list(analisis.get("campos") or [])
        usados = set()
        plan = []
        campos_paso = list(paso.campos) if paso is not None else []

        def en_plan(ids):
            return next((e for e in plan if set(ids) & set(e["ids"])), None)

        for c in campos_paso:
            sels = list(c.get("selectores") or [])
            k = self._marca_login(scope, sels) if analisis.get("hay") else None
            vivo = next((v for v in vivos if v.get("k") == k), None) if k is not None else None
            clave = c.get("clave") or mod_flujo.clave_de_campo(sels, c.get("etiqueta"))
            ids = self._identidades(host, clave, c.get("secreto"), selectores=sels)
            if vivo is None:
                # el campo marcado puede ser el «real» de DevExpress aunque el paso apunte al clon (o al revés)
                vivo = next((v for v in vivos if v.get("k") not in usados and
                             set(self._identidades(host, v.get("clave"), v.get("nombre"))) & set(ids)), None)
            if vivo is not None:
                usados.add(vivo.get("k"))
                for i in self._identidades(host, vivo.get("clave"), vivo.get("nombre")):
                    if i not in ids:
                        ids.append(i)
            previo = en_plan(ids)
            if previo is not None:                 # el mismo campo dos veces en el paso: se queda el primero
                continue
            e = {"clave": clave, "nombre": (vivo or {}).get("nombre") or clave,
                 "etiqueta": c.get("etiqueta") or (vivo or {}).get("etiqueta") or clave,
                 "tipo": c.get("tipo") or "texto",
                 "selectores": ([('[data-bot-login="%s"]' % vivo.get("k"))] if vivo else []) + sels,
                 "estables": sels, "valor": None, "secreto": None, "necesario": True, "del_usuario": False, "ids": ids}
            g = guardado_de(ids)
            if e["tipo"] == "clave":
                e["secreto"] = c.get("secreto") or g.get("secreto") or mod_accesos.nombre_secreto(host, e["nombre"])
                if c.get("valor"):
                    e["valor"] = self._r(c["valor"])            # contraseña en claro (flujo antiguo)
                    self._valores_secretos.add(e["valor"])
                else:
                    e["valor"] = self._secreto_o_nada(e["secreto"])
                    if e["valor"] is None and g.get("secreto") and g.get("secreto") != e["secreto"]:
                        e["valor"] = self._secreto_o_nada(g["secreto"])
                        if e["valor"] is not None:
                            e["secreto"] = g["secreto"]
            else:
                if g.get("valor") is not None:
                    e["valor"] = g["valor"]
                elif c.get("valor"):
                    e["valor"] = self._r(c["valor"])
                elif vivo is None and not (set(ids) & set(incluir)):
                    e["necesario"] = False            # sin valor y el campo no está en la página: se omite
            plan.append(e)
        for v in vivos:
            if v.get("k") in usados:
                continue
            ids = self._identidades(host, v.get("clave"), v.get("nombre"))
            previo = en_plan(ids)
            if previo is not None:                 # ya está (con otro nombre): se le añade la marca del análisis
                marca = '[data-bot-login="%s"]' % v.get("k")
                if marca not in previo["selectores"]:
                    previo["selectores"].insert(0, marca)
                continue
            g = guardado_de(ids)
            e = {"clave": v.get("clave"), "nombre": v.get("nombre") or v.get("clave"),
                 "etiqueta": v.get("etiqueta") or mod_flujo.etiqueta_bonita("", [v.get("nombre") or ""]) or v.get("clave"),
                 "tipo": v.get("tipo") or "texto",
                 "selectores": ['[data-bot-login="%s"]' % v.get("k")] + list(g.get("selectores") or []),
                 "estables": list(g.get("selectores") or []), "valor": None, "secreto": None, "necesario": True,
                 "del_usuario": False, "ids": ids}
            if g.get("clave"):
                e["clave"] = g["clave"]               # la respuesta y lo que se recuerde van con la clave de Accesos
                e["etiqueta"] = g.get("etiqueta") or e["etiqueta"]
            if e["tipo"] == "clave":
                e["secreto"] = g.get("secreto") or mod_accesos.nombre_secreto(host, e["nombre"])
                e["valor"] = self._secreto_o_nada(e["secreto"])
            elif g.get("valor") is not None:
                e["valor"] = g["valor"]
            if campos_paso:
                # con un paso grabado, un campo nuevo solo se rellena si se sabe su valor o si es obligatorio
                if e["valor"] is None and not v.get("requerido") and not (set(ids) & set(incluir)):
                    continue
            elif e["valor"] is None and v.get("tiene_valor") and e["tipo"] == "texto" and not (set(ids) & set(incluir)):
                e["necesario"] = False        # ya trae algo escrito (p. ej. lo recordó el navegador)
            plan.append(e)
        # campos de Accesos que no están en el paso ni salieron en el análisis, pero se ven en la página
        for n, g in enumerate(guardados):
            if n in usados_g or g.get("tipo") != "texto" or g.get("valor") is None or not g.get("selectores"):
                continue
            if en_plan(ids_guardado[n]) is not None or not self._visible_por_selectores(scope, g["selectores"]):
                continue
            plan.append({"clave": g["clave"], "nombre": g["clave"], "etiqueta": g.get("etiqueta") or g["clave"],
                         "tipo": "texto", "selectores": list(g["selectores"]), "estables": list(g["selectores"]),
                         "valor": g["valor"], "secreto": None, "necesario": True, "del_usuario": False,
                         "ids": ids_guardado[n]})
        return plan

    def _preguntar_acceso(self, host, url, plan, rechazada, error_pagina, solo=None):
        """Pide al usuario los datos del formulario.  Devuelve la respuesta, o None si canceló.
        `solo`: entradas del plan que hay que pedir (v3.3.1: la página dijo que falta ese dato obligatorio); el resto
        se rellena con lo que ya se sabe."""
        campos = []
        vistas = set()
        for e in plan:
            if solo is not None and e not in solo:
                continue
            if not e["necesario"] and e["valor"] is None:
                continue
            if e["clave"] in vistas:              # (nunca dos cajas con la misma clave: la respuesta sería ambigua)
                continue
            vistas.add(e["clave"])
            valor = e["valor"] or ""
            if e["tipo"] == "clave" and (rechazada or solo is not None):
                valor = ""                    # la contraseña rechazada (o guardada) no se vuelve a proponer
            campos.append({"clave": e["clave"], "etiqueta": e["etiqueta"], "tipo": e["tipo"], "valor": valor,
                           "requerido": bool(e["necesario"])})
        if rechazada:
            mensaje = mod_accesos.MENSAJE_RECHAZADA
            if self._rechazo_previo:
                mensaje = ("La página ya rechazó la contraseña guardada el %s (seguramente se cambió en la web). Escribe "
                           "la nueva: se guardará y se reintentará." % self._rechazo_previo)
        elif solo is not None:
            mensaje = ("La página «%s» pide %s (es un dato obligatorio que no estaba guardado). Escríbelo: se guardará en "
                       "Accesos y se reintentará. La contraseña no tiene nada que ver." % (
                           host, ", ".join("«%s»" % e["etiqueta"] for e in solo)))
        else:
            mensaje = "La página «%s» pide iniciar sesión. Escribe los datos que faltan." % host
        usuario = self._usuario_de(plan)
        solicitud = {"host": host, "url": url, "rechazada": bool(rechazada), "mensaje": mensaje,
                     "error_pagina": error_pagina or "", "campos": campos,
                     "tipo": "clave_fallida" if rechazada else "inicio_sesion", "usuario": usuario,
                     "reporte": self.flujo.nombre, "reporte_id": self.reporte_id}
        if solo is not None:
            solicitud["obligatorio"] = True
        self._log("    se piden al usuario los datos de acceso de «%s»%s" % (
            host, " (la contraseña fue rechazada)" if rechazada else
            ((": %s" % ", ".join(e["etiqueta"] for e in solo)) if solo is not None else "")))
        self.progreso(self._indice_actual, "espera", "La página «%s» pide iniciar sesión: escribe los datos en la ventana"
                      % host)
        respuesta = self._pedir_acceso(solicitud, self._esperar_evento)
        if not respuesta or not isinstance(respuesta, dict):
            return None
        return respuesta

    def _esperar_evento(self, evento):
        """Espera (sin bloquear el navegador y atento a «Detener») a que la ventana conteste."""
        while not evento.is_set():
            self._dormir(0.2)

    @staticmethod
    def _huella_login(plan):
        import hashlib
        h = hashlib.sha256()
        for e in plan:
            h.update(("%s=%s\x00" % (e["clave"], e["valor"] or "")).encode("utf-8", "replace"))
        return h.hexdigest()

    def _sesion_ya_iniciada(self, scope):
        """True si el formulario de inicio de sesión ya no está (p. ej. el usuario entró a mano mientras se le
        preguntaba)."""
        from playwright.sync_api import Error as ErrorPW
        try:
            return not self._analizar_login(scope).get("hay")
        except ErrorPW:
            return False

    def _aplicar_respuesta(self, plan, resp):
        valores = resp.get("valores") or {}
        for e in plan:
            if e["clave"] in valores and valores[e["clave"]] is not None:
                nuevo = str(valores[e["clave"]])
                if e["tipo"] == "clave":
                    if not nuevo:
                        continue
                    self._valores_secretos.add(nuevo)
                if nuevo != (e["valor"] or "") or e["tipo"] == "clave":
                    e["del_usuario"] = True
                    e["forzar"] = True
                e["valor"] = nuevo

    @staticmethod
    def _faltan(plan):
        return [e for e in plan if (e["valor"] is None or (e["tipo"] == "clave" and e["valor"] == "")) and e["necesario"]]

    def _campos_obligatorios_vacios(self, host, plan, analisis, mensaje):
        """v3.3.1: la página dijo que falta un dato obligatorio: ¿cuál?  El que nombra el mensaje («El campo LICENCIA
        esta vacio» → «Licencia», por su etiqueta o por su id/name «txtLicencia»), o los obligatorios que siguen
        vacíos.  Devuelve las identidades de esos campos."""
        res = []
        candidatos = [(e["ids"], e["etiqueta"], e["clave"], e["nombre"]) for e in plan]
        for v in analisis.get("campos") or []:
            candidatos.append((self._identidades(host, v.get("clave"), v.get("nombre")), v.get("etiqueta"),
                               v.get("clave"), v.get("nombre")))
        for g in self._accesos_de(host):
            candidatos.append((self._identidades(host, g.get("clave"), selectores=g.get("selectores")),
                               g.get("etiqueta"), g.get("clave"), ""))
        for ids, *nombres in candidatos:
            if mensaje and mod_accesos.nombra_campo(mensaje, *nombres):
                res += [i for i in ids if i not in res]
        if not res:
            # sin mensaje que nombre el campo: los obligatorios que siguen vacíos y de los que no se envió nada (las
            # contraseñas no cuentan: muchas webs las vacían tras un intento fallido)
            enviados = [i for e in plan if e["valor"] is not None for i in e["ids"]]
            for v in analisis.get("campos") or []:
                ids = self._identidades(host, v.get("clave"), v.get("nombre"))
                if v.get("requerido") and not v.get("tiene_valor") and v.get("tipo") != "clave"                         and not set(ids) & set(enviados):
                    res += [i for i in ids if i not in res]
        return res

    def _cerrar_mensaje(self, pg, scope, mensaje=""):
        """Cierra la ventanita con el mensaje que dejó la página («Aceptar»), si la hay; si no, pulsa Escape."""
        from playwright.sync_api import Error as ErrorPW
        try:
            texto = scope.locator("html").first.evaluate(JS_MARCAR_CIERRE_MENSAJE, mensaje or "")
        except ErrorPW:
            texto = None
        try:
            if texto is not None:
                scope.locator('[data-bot-cerrar="1"]').first.click(timeout=3000)
                self._log("    (se cierra el mensaje de la página)")
            else:
                pg.keyboard.press("Escape")
        except ErrorPW:
            try:
                scope.locator('[data-bot-cerrar="1"]').first.dispatch_event("click")
            except ErrorPW:
                pass
        self._pausa(0.4)

    def _hacer_login(self, pg, scope, host, paso, analisis, fin):
        """Rellena y envía el formulario de inicio de sesión, y comprueba el resultado.

        - Si falta algún dato (contraseña no guardada…), se pide al usuario (`pedir_acceso`); sin ventana, falla
          con un mensaje claro.
        - Si la página rechaza los datos, se pregunta UNA vez («La contraseña fue rechazada…»); nunca se reenvían
          los mismos datos y como mucho se intenta 2 veces por sitio y ejecución (para no bloquear la cuenta).
        - v3.3.1: si la página dice que falta un dato obligatorio («El campo LICENCIA esta vacio…»), NO es una
          contraseña rechazada: se cierra el mensaje, se rellena ese campo (con Accesos, o se pide SOLO ese dato) y se
          reintenta."""
        from playwright.sync_api import Error as ErrorPW
        plan = self._plan_login(scope, host, paso, analisis)
        rechazada, error_pagina, recordar = False, "", False
        pedir_solo = None                      # entradas del plan que faltan (dato obligatorio)
        preguntas = 0
        enviar = dict(paso.enviar) if paso is not None else {}
        self._rechazo_previo = None
        previa = self._clave_ya_rechazada(plan, host)
        if previa is not None:
            # v3.0: la página ya rechazó esta misma contraseña guardada (en otra ejecución): no se vuelve a enviar
            entrada, fecha = previa
            self._log("    la contraseña guardada de «%s» ya fue rechazada el %s y no se ha cambiado: no se vuelve a "
                      "enviar" % (host, fecha))
            if self._pedir_acceso is None:
                self._avisar_rechazo(host, plan)
                raise ErrorPaso(mod_accesos.MENSAJE_YA_RECHAZADA % (host, fecha))
            self._rechazo_previo = fecha
            rechazada = True
            for e in plan:
                if e["tipo"] == "clave":
                    e["valor"] = None
                    e["necesario"] = True
        while True:
            faltan = self._faltan(plan)
            if faltan or rechazada or pedir_solo:
                if self._pedir_acceso is None:
                    if pedir_solo:
                        raise ErrorPaso("La página «%s» pide %s (dato obligatorio) y no está guardado. Abre el bot y "
                                        "ejecútalo una vez con la ventana para escribirlo (se guardará en Accesos)." % (
                                            host, ", ".join("«%s»" % e["etiqueta"] for e in pedir_solo)))
                    raise ErrorPaso(mod_accesos.MENSAJE_SIN_VENTANA % host +
                                    ((" (La página dijo: «%s».)" % self._limpiar(error_pagina[:150])) if error_pagina else ""))
                solo = None
                if pedir_solo and not rechazada:
                    solo = list(pedir_solo) + [e for e in faltan if e not in pedir_solo]
                resp = self._preguntar_acceso(host, pg.url, plan, rechazada, error_pagina, solo=solo)
                preguntas += 1
                if analisis.get("hay") and self._sesion_ya_iniciada(scope):
                    self._log("    la sesión de «%s» ya está iniciada (se inició a mano mientras se preguntaba): se "
                              "sigue" % host)
                    self._pista_login = ""
                    if resp is not None:
                        self._aplicar_respuesta(plan, resp)
                    return True
                if resp is None:
                    raise ErrorPaso("Inicio de sesión en «%s» cancelado por el usuario" % host)
                recordar = bool(resp.get("recordar", True))
                self._aplicar_respuesta(plan, resp)
                faltan = self._faltan(plan)
                if faltan:
                    if preguntas < 3:
                        self._log("    (faltan datos en la respuesta: %s; se vuelven a pedir)" % ", ".join(
                            e["etiqueta"] for e in faltan))
                        error_pagina = "Falta: " + ", ".join(e["etiqueta"] for e in faltan)
                        pedir_solo = faltan if pedir_solo else None
                        continue
                    raise ErrorPaso("Faltan datos para iniciar sesión en «%s»: %s" % (
                        host, ", ".join(e["etiqueta"] for e in faltan)))
                pedir_solo = None
            huella = self._huella_login(plan)
            enviados = self._enviados_login.setdefault(host, set())
            if huella in enviados:
                raise ErrorPaso("Son los mismos datos que «%s» ya rechazó: no se vuelven a enviar (para no bloquear la "
                                "cuenta). Corrige la contraseña en «Accesos»." % host)
            if self._intentos_login.get(host, 0) >= MAX_INTENTOS_LOGIN:
                raise ErrorPaso("Ya se intentó iniciar sesión %d veces en «%s» en esta ejecución; no se vuelve a "
                                "intentar (para no bloquear la cuenta)." % (MAX_INTENTOS_LOGIN, host))
            self._intentos_login[host] = self._intentos_login.get(host, 0) + 1
            enviados.add(huella)
            self._log("    iniciando sesión en «%s» (intento %d)…" % (host, self._intentos_login[host]))
            url_antes = pg.url
            firma_antes = analisis.get("firma", "")
            ultimo = self._rellenar_login(pg, scope, plan, fin)
            self._enviar_login(pg, scope, enviar, ultimo, fin)
            ok, error_pagina = self._verificar_login(pg, scope, url_antes, firma_antes, fin)
            if ok:
                self._log("    sesión iniciada en «%s»" % host)
                self._pista_login = ""
                enviados.discard(huella)          # solo se recuerdan (para no reenviarlos) los datos rechazados
                if recordar:
                    self._recordar_acceso(host, plan)
                self._clave_funciono(host, plan)
                return True
            self._log("    la página no aceptó el inicio de sesión%s" % (
                (": «%s»" % self._limpiar(error_pagina[:150])) if error_pagina else ""))
            try:
                analisis = self._analizar_login(scope)
            except ErrorPW:
                analisis = {"hay": False, "campos": []}
            # v3.3.1: ¿falta un dato obligatorio (no es la contraseña)?
            tipo = mod_accesos.tipo_de_fallo(error_pagina)
            vacios = []
            if tipo != "credencial":
                vacios = self._campos_obligatorios_vacios(host, plan, analisis, error_pagina if tipo else "")
            reintentos = self._reintentos_obligatorio.get(host, 0)
            if tipo == "obligatorio" or (not tipo and vacios):
                if reintentos >= 2:
                    raise ErrorPaso(self._error_obligatorio(host, error_pagina))
                self._cerrar_mensaje(pg, scope, error_pagina)
                try:
                    analisis = self._analizar_login(scope)
                except ErrorPW:
                    analisis = {"hay": False, "campos": []}
                nuevo = self._plan_login(scope, host, paso, analisis, incluir=vacios)
                for e in nuevo:                   # se conserva todo lo que ya se sabía (también la contraseña)
                    a = next((x for x in plan if set(x["ids"]) & set(e["ids"])), None)
                    if a is not None and a["valor"] is not None and (e["valor"] is None or a["del_usuario"]):
                        e["valor"], e["del_usuario"] = a["valor"], a["del_usuario"]
                    if a is not None and a.get("secreto") and e["tipo"] == "clave":
                        e["secreto"] = e.get("secreto") or a["secreto"]
                    if set(e["ids"]) & set(vacios):
                        e["necesario"] = True
                        e["forzar"] = True        # la página no recibió su valor: se vuelve a escribir
                nombres = [e["etiqueta"] for e in nuevo if set(e["ids"]) & set(vacios)]
                desconocidos = [e for e in nuevo if set(e["ids"]) & set(vacios) and e["valor"] is None]
                if reintentos < 1 or desconocidos:
                    self._reintentos_obligatorio[host] = reintentos + 1
                    enviados.discard(huella)      # no fue un rechazo: se pueden volver a enviar
                    self._intentos_login[host] -= 1   # (ni cuenta como intento con la contraseña)
                    plan = nuevo
                    self._log("    (no es la contraseña: la página dice que falta %s; %s)" % (
                        ", ".join("«%s»" % n for n in nombres) or "un dato obligatorio",
                        "se pide ese dato" if desconocidos else "se vuelve a escribir y se reintenta"))
                    pedir_solo = desconocidos or None
                    rechazada = False         # (la contraseña no tuvo la culpa)
                    continue
                # ya se reintentó con todo relleno y la página sigue pidiendo un dato: no se marca la contraseña
                raise ErrorPaso(self._error_obligatorio(host, error_pagina))
            marcadas = self._anotar_rechazo(host, plan, error_pagina)
            if self._pedir_acceso is None:
                if marcadas:
                    self._avisar_rechazo(host, plan)
                    raise ErrorPaso(mod_accesos.MENSAJE_RECHAZADA_SIN_VENTANA % (host, host) +
                                    ((" (La página dijo: «%s».)" % self._limpiar(error_pagina[:150])) if error_pagina else ""))
                raise ErrorPaso(mod_accesos.MENSAJE_SIN_VENTANA % host +
                                ((" (La página dijo: «%s».)" % self._limpiar(error_pagina[:150])) if error_pagina else ""))
            if self._intentos_login[host] >= MAX_INTENTOS_LOGIN:
                raise ErrorPaso("La página «%s» volvió a rechazar el inicio de sesión%s. No se vuelve a intentar (para no "
                                "bloquear la cuenta): revisa los datos en «Accesos»." % (
                                    host, (" («%s»)" % self._limpiar(error_pagina[:120])) if error_pagina else ""))
            rechazada = True
            self._cerrar_mensaje(pg, scope, error_pagina)
            try:
                analisis = self._analizar_login(scope)
            except ErrorPW:
                analisis = {"hay": False, "campos": []}
            anteriores = plan
            plan = self._plan_login(scope, host, paso, analisis)
            for e in plan:                     # se proponen los mismos datos de texto; la contraseña, vacía
                a = next((x for x in anteriores if set(x["ids"]) & set(e["ids"])), None)
                if a is not None and e["tipo"] == "texto":
                    e["valor"], e["del_usuario"] = a["valor"], a["del_usuario"]
                if e["tipo"] == "clave":
                    if a is not None and a.get("secreto"):
                        e["secreto"] = a["secreto"]
                    e["valor"] = None
                    e["necesario"] = True

    def _error_obligatorio(self, host, error_pagina):
        return ("La página «%s» sigue pidiendo un dato obligatorio%s que el bot no consigue rellenar. Revisa los datos de "
                "«%s» en Accesos (la contraseña NO se marca como rechazada: no es el problema)." % (
                    host, (" («%s»)" % self._limpiar(error_pagina[:150])) if error_pagina else "", host))

    def _rellenar_login(self, pg, scope, plan, fin):
        """Escribe cada dato en su campo (como «Escribir»: campos de solo lectura, ya rellenos, clones de DevExpress).
        Devuelve el último campo rellenado (para pulsar Enter si no hay botón).
        v3.3.1: `forzar` (la página no recibió el valor) borra y vuelve a teclear aunque el campo ya lo muestre; al
        terminar se comprueba que ningún dato se haya borrado solo (la página terminaba de cargar)."""
        from playwright.sync_api import Error as ErrorPW
        ultimo = None
        escritos = []
        for e in plan:
            if e["valor"] is None:
                continue
            valor = e["valor"]
            loc = None
            limite = time.monotonic() + min(5.0, max(1.0, fin - time.monotonic()))
            clon_probado = False
            while True:
                self._comprobar_detener()
                for sel in e["selectores"]:
                    try:
                        cands, _ = self._candidatos(scope, sel, visible=True, habilitado=False)
                    except ErrorPW:
                        continue
                    if cands:
                        loc = self._elegir(cands)
                        break
                if loc is not None or time.monotonic() >= limite:
                    break
                if not clon_probado:
                    clon_probado = True
                    if self._activar_clon(scope, e["selectores"]):
                        continue
                self._pausa(SONDEO)
            if loc is None:
                oculto = None
                for sel in e["selectores"]:
                    try:
                        l2 = scope.locator(sel)
                        if l2.count():
                            oculto = l2.first
                            break
                    except ErrorPW:
                        continue
                if oculto is not None:
                    self._log("    (el campo «%s» no se ve: se pone el valor directamente)" % e["etiqueta"])
                    oculto.evaluate(JS_PONER_VALOR, valor)
                    ultimo = oculto
                    continue
                if e["tipo"] == "clave":
                    raise ErrorPaso("No se encontró el campo «%s» de la página de inicio de sesión" % e["etiqueta"])
                self._log("    (no se encontró el campo «%s»: se omite)" % e["etiqueta"])
                continue
            ultimo = loc
            escritos.append((e, loc))
            if e.get("forzar"):
                e["forzar"] = False
                self._teclear(pg, loc, valor)
                continue
            if self._tiene_valor(loc, valor):
                continue
            ms = max(1000, min(self._restante_ms(fin), 10000))
            try:
                self._escribir(pg, loc, valor, ms)
            except (ErrorPW, ErrorPaso):
                loc.evaluate(JS_PONER_VALOR, valor)
        # ¿se borró algo solo mientras se rellenaba el resto? (la web terminaba de cargar): se vuelve a escribir
        self._pausa(0.2)
        for e, loc in escritos:
            try:
                if e["tipo"] == "texto" and not (loc.evaluate(JS_LEER_VALOR) or "").strip() and (e["valor"] or "").strip():
                    self._log("    (el campo «%s» quedó vacío: se vuelve a escribir)" % e["etiqueta"])
                    self._teclear(pg, loc, e["valor"])
            except ErrorPW:
                continue
        return ultimo

    def _teclear(self, pg, loc, valor):
        """Borra el campo y teclea el valor (como una persona: lo ven también las webs que solo atienden al teclado);
        si no se puede, lo pone con JavaScript."""
        from playwright.sync_api import Error as ErrorPW
        try:
            loc.click(timeout=3000)
        except ErrorPW:
            pass
        try:
            loc.fill("", timeout=3000)
            loc.press_sequentially(valor, delay=15, timeout=10000)
            loc.evaluate("e => e.dispatchEvent(new Event('change', { bubbles: true }))")
            if self._tiene_valor(loc, valor):
                return
        except ErrorPW:
            pass
        try:
            loc.evaluate(JS_PONER_VALOR, valor)
        except ErrorPW:
            pass

    def _activar_clon(self, scope, selectores):
        """DevExpress: el campo real (…_I) está oculto y se ve un «clon» (…_I_CLND); al pulsarlo aparece el real.
        v3.3.1: también si el campo se busca por otra cosa que su id (la marca del análisis, su name…)."""
        from playwright.sync_api import Error as ErrorPW
        ids = []
        for sel in selectores:
            if re.match(r"^#[\w\-]+$", sel) and not sel.endswith("_CLND"):
                ids.append(sel[1:])
                continue
            try:
                loc = scope.locator(sel)
                if loc.count():
                    i = loc.first.get_attribute("id", timeout=1000)
                    if i and not i.endswith("_CLND"):
                        ids.append(i)
            except ErrorPW:
                continue
        for i in ids:
            try:
                clon = scope.locator('[id="%s_CLND"]' % i)
                if clon.count() and clon.first.is_visible():
                    try:
                        clon.first.click(timeout=3000)
                    except ErrorPW:
                        clon.first.focus()
                    self._pausa(0.3)
                    return True
            except ErrorPW:
                continue
        return False

    def _enviar_login(self, pg, scope, enviar, ultimo, fin):
        """Pulsa el botón de entrar (el grabado, o el que se reconoció en la página) o Enter en el último campo."""
        from playwright.sync_api import Error as ErrorPW
        if enviar.get("selectores"):
            try:
                loc = self._localizar(pg, scope, enviar["selectores"], min(10.0, max(2.0, fin - time.monotonic())),
                                      habilitado=True, que="el botón para entrar")
                loc.click(timeout=10000)
                return
            except (ErrorPaso, ErrorPW) as e:
                self._log("    (no se pudo pulsar «%s» (%s): se pulsa Enter)" % (
                    enviar.get("objetivo") or "Entrar", _primeras_lineas(e, 1)[:80]))
        elif not enviar.get("tecla"):
            try:
                boton = scope.locator('[data-bot-login-enviar="1"]')
                if boton.count() and boton.first.is_visible():
                    boton.first.click(timeout=10000)
                    return
            except ErrorPW:
                pass
        try:
            if ultimo is not None:
                ultimo.press("Enter", timeout=5000)
            else:
                pg.keyboard.press("Enter")
        except ErrorPW:
            pg.keyboard.press("Enter")

    def _verificar_login(self, pg, scope, url_antes, firma_antes, fin):
        """¿La página aceptó el inicio de sesión?  Sí: el campo de contraseña ya no se ve (o se pasó a otra página
        con otros campos).  No: sigue el formulario (con un mensaje de error, se decide antes).  (ok, error)."""
        from playwright.sync_api import Error as ErrorPW
        self._esperar_carga(pg, minimo=0.5, forzar=True)
        inicio = time.monotonic()
        limite = inicio + min(25.0, max(8.0, fin - inicio))
        error = ""
        while True:
            self._comprobar_detener()
            try:
                a = self._analizar_login(scope)
            except ErrorPW:
                a = None                       # la página está cambiando
            if a is not None:
                if not a.get("hay"):
                    return True, ""
                error = a.get("error") or ""
                if pg.url != url_antes and a.get("firma") != firma_antes:
                    return True, ""
                if error and time.monotonic() - inicio >= 1.5 and self._pagina_tranquila(pg):
                    return False, error
            if time.monotonic() >= limite:
                return False, error
            self._pausa(0.25)

    # --- v3.0: contraseñas rechazadas (se recuerdan entre ejecuciones; nunca se reenvía la misma)
    def _secreto_guardado_de(self, e):
        """Nombre de la contraseña guardada que se está usando en la entrada del plan (o None si es otra)."""
        if e["tipo"] != "clave" or not e.get("secreto") or e.get("del_usuario") or e["valor"] is None:
            return None
        try:
            guardada = secretos.obtener(e["secreto"])
        except secretos.ErrorSecreto:
            return None
        return e["secreto"] if guardada is not None and guardada == e["valor"] else None

    def _clave_ya_rechazada(self, plan, host=""):
        for e in plan:
            nombre = self._secreto_guardado_de(e)
            if nombre:
                fecha = secretos.rechazada(nombre)
                if fecha and self._rechazo_por_dato_obligatorio(nombre, host):
                    continue
                if fecha:
                    return e, fecha
        return None

    def _rechazo_por_dato_obligatorio(self, nombre, host):
        """v3.3.1: la marca de «rechazada» se puso porque la página dijo que faltaba un dato obligatorio (p. ej. «El
        campo LICENCIA esta vacio»), no porque la contraseña fuera mala: se quita.  True si se quitó."""
        estado = getattr(self.accesos, "estado_clave", None)
        try:
            est = estado(nombre) if estado is not None else None
        except Exception:              # noqa: BLE001
            est = None
        motivo = (est or {}).get("motivo") or ""
        if not mod_accesos.es_mensaje_obligatorio(motivo):
            return False
        try:
            secretos.limpiar_rechazo(nombre)
        except secretos.ErrorSecreto:
            pass
        limpiar = getattr(self.accesos, "limpiar_rechazo_clave", None)
        if limpiar is not None:
            try:
                limpiar(nombre)
            except Exception:          # noqa: BLE001
                pass
        self._log("    (la contraseña de «%s» estaba marcada como rechazada porque la página dijo «%s»: eso es un dato "
                  "obligatorio vacío, no la contraseña; se quita la marca)" % (host, self._limpiar(motivo[:120])))
        return True

    def _usuario_de(self, plan):
        textos = [e for e in plan if e["tipo"] == "texto" and e["valor"]]
        rx = re.compile(r"usuario|user|login|correo|mail|rnc|cuenta", re.IGNORECASE)
        e = next((x for x in textos if rx.search("%s %s" % (x.get("etiqueta") or "", x.get("clave") or ""))), None)
        return (e or (textos[0] if textos else {})).get("valor") or ""

    def _anotar_rechazo(self, host, plan, motivo=""):
        """La página rechazó el inicio de sesión: se marcan como rechazadas las contraseñas GUARDADAS que se usaron
        (huella en el almacén de contraseñas; fecha y, desde la 3.3.1, lo que dijo la página en la base de datos).
        Devuelve sus nombres."""
        marcadas = []
        for e in plan:
            nombre = self._secreto_guardado_de(e)
            if not nombre:
                continue
            try:
                secretos.marcar_rechazada(nombre)
                marcadas.append(nombre)
            except secretos.ErrorSecreto:
                continue
            marcar = getattr(self.accesos, "marcar_clave_rechazada", None)
            if marcar is not None:
                try:
                    marcar(nombre, host, self._usuario_de(plan), motivo=self._limpiar(motivo or "")[:300])
                except TypeError:
                    marcar(nombre, host, self._usuario_de(plan))
                except Exception:          # noqa: BLE001
                    pass
        if marcadas:
            self._log("    (la contraseña guardada de «%s» queda marcada como rechazada: no se volverá a enviar hasta "
                      "que se cambie)" % host)
            if self._notificar:
                self._notificar("clave_rechazada", {"host": host, "usuario": self._usuario_de(plan)})
        return marcadas

    def _avisar_rechazo(self, host, plan):
        """Sin nadie delante: aviso en la aplicación y notificación de Windows."""
        from . import avisos
        titulo = mod_accesos.TITULO_CLAVE_CAMBIO % host
        texto = ("La página rechazó la contraseña guardada%s. Abre el aviso o Accesos para escribir la nueva."
                 % ((" del usuario «%s»" % self._usuario_de(plan)) if self._usuario_de(plan) else ""))
        avisos.avisar(self.accesos, "clave_rechazada", titulo, texto,
                      {"host": host, "usuario": self._usuario_de(plan), "reporte_id": self.reporte_id,
                       "reporte": self.flujo.nombre})
        self._log("    aviso: %s" % titulo)

    def _clave_funciono(self, host, plan):
        for e in plan:
            if e["tipo"] != "clave" or not e.get("secreto"):
                continue
            try:
                if secretos.obtener(e["secreto"]) is None:
                    continue
            except secretos.ErrorSecreto:
                continue
            secretos.limpiar_rechazo(e["secreto"])
            ok = getattr(self.accesos, "marcar_clave_ok", None)
            if ok is not None:
                try:
                    ok(e["secreto"], host, self._usuario_de(plan))
                    marcar = getattr(self.accesos, "marcar_notificaciones_de", None)
                    if marcar is not None:
                        marcar("clave_rechazada", "host", host)
                except Exception:          # noqa: BLE001
                    pass

    def _recordar_acceso(self, host, plan):
        """Guarda lo que escribió el usuario: contraseñas en el Administrador de credenciales; el resto en Accesos."""
        guardado = False
        for e in plan:
            if not e.get("del_usuario") or e["valor"] is None:
                continue
            sels = [s for s in (e.get("estables") or []) if "data-bot-login" not in s]
            try:
                if e["tipo"] == "clave":
                    nombre = e["secreto"] or mod_accesos.nombre_secreto(host, e["nombre"])
                    secretos.guardar(nombre, e["valor"])
                    self.accesos.guardar_acceso(host, e["clave"], e["etiqueta"], "clave", secreto=nombre, selectores=sels)
                    self._log("    (contraseña de «%s» guardada como «%s»)" % (host, nombre))
                else:
                    self.accesos.guardar_acceso(host, e["clave"], e["etiqueta"], "texto", valor=e["valor"], selectores=sels)
                    self._log("    («%s» de «%s» guardado en Accesos)" % (e["etiqueta"], host))
                guardado = True
            except Exception as ex:            # noqa: BLE001 (no poder guardar no debe tumbar la ejecución)
                self._log("    (no se pudo guardar «%s»: %s)" % (e["etiqueta"], type(ex).__name__))
        if guardado:
            self._log("    " + mod_accesos.MENSAJE_GUARDADOS % host)
            if self._notificar:
                self._notificar("accesos_guardados", {"host": host, "texto": mod_accesos.MENSAJE_GUARDADOS % host})

    # ------------------------------------------------- recuperación de menús
    def _visible_ya(self, scope, paso, espera):
        """True si algún selector del paso encuentra un elemento visible antes de `espera` s."""
        from playwright.sync_api import Error as ErrorPW
        fin = time.monotonic() + espera
        while True:
            self._comprobar_detener()
            for sel in paso.selectores:
                try:
                    loc = scope.locator(sel)
                    if any(loc.nth(i).is_visible() for i in range(min(loc.count(), MAX_CANDIDATOS))):
                        return True
                except ErrorPW:
                    pass
            if time.monotonic() >= fin:
                return False
            self._pausa(SONDEO)

    def _objetivo_oculto(self, scope, paso):
        """El primer elemento del paso que existe en la página pero no se ve (o None)."""
        from playwright.sync_api import Error as ErrorPW
        for sel in paso.selectores:
            try:
                loc = scope.locator(sel)
                for i in range(min(loc.count(), 5)):
                    if not loc.nth(i).is_visible():
                        return loc.nth(i)
            except ErrorPW:
                continue
        return None

    def _recuperar(self, pg, scope, paso):
        """El elemento de un clic no se ve tras ~2 s: se intenta (una vez por paso) abrir el menú o la lista
        que lo contiene.  (a) pasar el ratón por el elemento que lo despliega (menús CSS, ARIA, DevExpress);
        (b) volver a pasar el ratón por los pasos «Pasar el ratón» anteriores; (c) si el paso anterior fue un
        clic que abre una lista o menú (y está cerrada), repetir ese clic; (d) pasar el ratón por las opciones
        de los menús de la página, una a una.  Nunca hace fallar el paso: si no lo consigue, se sigue esperando."""
        from playwright.sync_api import Error as ErrorPW
        if not self.recuperacion or self._recuperado_en == self._indice_actual:
            return
        self._recuperado_en = self._indice_actual
        que = paso.nombre_objetivo() or "el elemento"
        self._log("    (%s no se ve: se intenta abrir el menú o la lista que lo contiene)" % que)
        try:
            for metodo in (self._recuperar_ancestros, self._recuperar_raton_previo, self._recuperar_reabrir,
                           self._recuperar_explorar):
                if metodo(pg, scope, paso):
                    self._log("    (recuperado: %s ya se ve)" % que)
                    return
            self._log("    (no se consiguió abrir el menú; se sigue esperando)")
        except Detenido:
            raise
        except (ErrorPW, ErrorPaso) as e:
            self._log("    (la recuperación automática no funcionó: %s)" % _primeras_lineas(e, 1)[:100])

    def _pasar_raton(self, elemento, nombre):
        self._log("    intentando abrir el menú pasando el ratón por «%s»" % self._limpiar(nombre or "…"))
        elemento.hover(timeout=3000)
        self._pausa(0.35)

    def _apartar_raton(self, pg):
        """Lleva el ratón a una esquina: si ya estaba encima del elemento, volver a «pasar» no avisaría a la web."""
        try:
            pg.mouse.move(0, 0)
            self._pausa(0.1)
        except Exception:          # noqa: BLE001 (la página se está cerrando)
            pass

    def _recuperar_ancestros(self, pg, scope, paso):
        """(a) Menús que se abren al pasar el ratón por un elemento conocido (padre en el DOM, ARIA, DevExpress)."""
        for vuelta in range(4):
            oculto = self._objetivo_oculto(scope, paso)
            if oculto is None:
                return False
            el = oculto.evaluate_handle(JS_PADRE_MENU).as_element()
            if el is None:
                return False
            if vuelta == 0:
                self._apartar_raton(pg)
            self._pasar_raton(el, el.evaluate(JS_NOMBRE_CORTO))
            if self._visible_ya(scope, paso, 0.6):
                return True
        return False

    def _pasos_raton_previos(self):
        """Pasos «Pasar el ratón» justo antes del paso actual (saltando esperas y pasos desactivados)."""
        res = []
        for p in reversed(self.flujo.pasos[:self._indice_actual]):
            if p.desactivado or p.tipo in ("esperar_segundos", "esperar_elemento", "esperar_texto"):
                continue
            if p.tipo != "pasar_raton":
                break
            res.insert(0, p)
        return res

    def _recuperar_raton_previo(self, pg, scope, paso):
        """(b) Repetir los pasos «Pasar el ratón» anteriores."""
        previos = self._pasos_raton_previos()
        if not previos:
            return False
        self._apartar_raton(pg)
        for p in previos:
            pg2, scope2 = self._alcance(p, 5)
            try:
                loc = self._localizar(pg2, scope2, p.selectores, 1.5, que=p.nombre_objetivo())
            except ErrorPaso:
                continue
            self._pasar_raton(loc, (p.nombre_objetivo() or "").strip("«»"))
        return self._visible_ya(scope, paso, 1.0)

    def _recuperar_reabrir(self, pg, scope, paso):
        """(c) Si el paso anterior fue un clic que abre una lista o menú y ahora está cerrada, repetirlo."""
        k = self._indice_previo
        if k is None or not (0 <= k < len(self.flujo.pasos)):
            return False
        prev = self.flujo.pasos[k]
        if prev.tipo != "clic" or prev.boton != "izquierdo" or prev.doble or not prev.selectores:
            return False
        pg2, scope2 = self._alcance(prev, 5)
        try:
            loc = self._localizar(pg2, scope2, prev.selectores, 1.5, que=prev.nombre_objetivo())
        except ErrorPaso:
            return False
        if loc.evaluate(JS_ABRIDOR) != "cerrado":
            return False
        self._log("    intentando abrir la lista otra vez: clic de nuevo en %s" % (prev.nombre_objetivo() or "el paso anterior"))
        loc.click(timeout=5000)
        self._pausa(0.4)
        return self._visible_ya(scope, paso, 1.5)

    def _recuperar_explorar(self, pg, scope, paso):
        """(d) Solo si el elemento existe pero está oculto: pasar el ratón por cada opción de los menús visibles."""
        if self._objetivo_oculto(scope, paso) is None:
            return False
        nombres = scope.locator("body").first.evaluate(JS_MARCAR_MENUS)
        if not nombres:
            return False
        self._log("    (se prueban los menús de la página uno a uno: %d)" % len(nombres))
        self._apartar_raton(pg)
        try:
            for i, nombre in enumerate(nombres):
                item = scope.locator('[data-bot-explorar="%d"]' % i).first
                try:
                    self._pasar_raton(item, nombre)
                except ErrorPW:            # una opción que no admite el ratón: la siguiente
                    continue
                if self._visible_ya(scope, paso, 0.3):
                    return True
        finally:
            try:
                scope.locator("body").first.evaluate(
                    "() => document.querySelectorAll('[data-bot-explorar]').forEach((e) => e.removeAttribute('data-bot-explorar'))")
            except Exception:              # noqa: BLE001
                pass
        return False

    # ------------------------------------------------------------ archivos
    def _destino(self, nombre, carpeta_plantilla, ext=None):
        carpeta = self._r(carpeta_plantilla) if carpeta_plantilla else self.carpeta_descargas
        if not os.path.isabs(carpeta):
            carpeta = os.path.join(self.carpeta_descargas, carpeta)
        os.makedirs(carpeta, exist_ok=True)
        destino = os.path.join(carpeta, nombre)
        if self.flujo.opcion("si_existe") != "sobrescribir":
            destino = ruta_libre(destino, ext)
        return destino

    def _descargar(self, paso, pg, scope, espera):
        """`espera` (timeout_descarga) vale para esperar al botón (visible y habilitado) y luego al archivo."""
        antes = len(self._descargas)
        if paso.selectores:
            boton = {"izquierdo": "left", "derecho": "right", "medio": "middle"}[paso.boton]

            def hacer_clic(loc, ms):
                if paso.doble:
                    loc.dblclick(button=boton, timeout=ms)
                else:
                    loc.click(button=boton, timeout=ms)
            self._accionar(pg, scope, paso, time.monotonic() + espera, hacer_clic)
        inicio = time.monotonic()
        fin = inicio + espera
        proximo_aviso = inicio + self.aviso_cada
        while len(self._descargas) <= antes:
            self._comprobar_detener()
            ahora = time.monotonic()
            if ahora >= fin:
                raise ErrorPaso("No llegó ninguna descarga en %g s" % espera)
            if ahora >= proximo_aviso:
                texto = "esperando a que se genere el archivo… %d s" % int(ahora - inicio)
                self._log("    " + texto)
                self.progreso(self._indice_actual, "espera", texto)
                proximo_aviso += self.aviso_cada
            self._pausa(0.25)
        descarga = self._descargas[antes]
        sugerido = descarga.suggested_filename or "descarga"
        base, ext = separar_extension(sugerido)
        plantilla = paso.nombre or "{nombre}{ext}"
        nombre = nombre_archivo_seguro(self._r(plantilla, ext=ext, nombre=base))
        destino = self._destino(nombre, paso.carpeta, ext if nombre.lower().endswith(ext.lower()) else None)
        descarga.save_as(destino)
        fallo = descarga.failure()
        if fallo:
            raise ErrorPaso("La descarga falló: %s" % fallo)
        self.resultado.archivos.append(destino)
        self._log("    archivo guardado: %s" % destino)

    def _guardar_pagina(self, paso, pg, timeout):
        """Guarda la página actual como PDF, HTML o CSV (la tabla más grande)."""
        from playwright.sync_api import Error as ErrorPW
        formato = (paso.formato or "html").lower()
        ext = "." + formato
        fin = time.monotonic() + timeout
        try:
            pg.wait_for_load_state("domcontentloaded", timeout=int(timeout * 1000))
        except ErrorPW:
            pass
        try:
            titulo = pg.title() or ""
        except ErrorPW:
            titulo = ""
        base = re.sub(r"[^\w\-. ]+", "_", titulo, flags=re.UNICODE).strip(" .") or "pagina"
        plantilla = paso.nombre or "Pagina_{hoy:%Y-%m-%d}"
        nombre = nombre_archivo_seguro(self._r(plantilla, ext=ext, nombre=base))
        if not nombre.lower().endswith(ext):
            nombre += ext
        destino = self._destino(nombre, paso.carpeta)

        if formato == "csv":
            filas = self._esperar_tabla(pg, fin)
            with open(destino, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(filas)
        elif formato == "pdf":
            destino = self._guardar_pdf(pg, destino)
        else:
            contenido = inyectar_base(pg.content(), pg.url)
            with open(destino, "w", encoding="utf-8") as f:
                f.write(contenido)
        self.resultado.archivos.append(destino)
        self._log("    página guardada: %s" % destino)

    def _esperar_tabla(self, pg, fin):
        from playwright.sync_api import Error as ErrorPW
        while True:
            self._comprobar_detener()
            mejor = None
            for fr in list(pg.frames):
                try:
                    r = fr.evaluate(JS_TABLA)
                except ErrorPW:
                    continue
                if r and (mejor is None or r["celdas"] > mejor["celdas"]):
                    mejor = r
            if mejor:
                return mejor["filas"]
            if time.monotonic() >= fin:
                raise ErrorPaso("No hay ninguna tabla en la página para guardar como CSV")
            self._pausa(0.3)

    def _guardar_pdf(self, pg, destino):
        """PDF directo si el navegador es oculto; si es visible, imprime una copia en un navegador oculto
        auxiliar (con la misma sesión).  Si no se puede, explica el motivo y guarda HTML."""
        from playwright.sync_api import Error as ErrorPW
        if self.oculto and not self.forzar_pdf_auxiliar:
            try:
                pg.pdf(path=destino, print_background=True)
                return destino
            except ErrorPW as e:
                motivo = _primeras_lineas(e, 1)
        else:
            try:
                self._pdf_auxiliar(pg, destino)
                return destino
            except Exception as e:
                motivo = "%s: %s" % (type(e).__name__, _primeras_lineas(e, 1))
        alternativo = ruta_libre(os.path.splitext(destino)[0] + ".html")
        self._log("    No se pudo crear el PDF (%s). Se guarda como HTML: %s" % (motivo[:150], os.path.basename(alternativo)))
        with open(alternativo, "w", encoding="utf-8") as f:
            f.write(inyectar_base(pg.content(), pg.url))
        return alternativo

    def _pdf_auxiliar(self, pg, destino):
        if self._pw is None or self._ctx is None:
            raise ErrorPaso("el navegador ya no está disponible")
        self._log("    (PDF en modo visible: se imprime en un navegador oculto auxiliar)")
        estado = self._ctx.storage_state()
        contenido = inyectar_base(pg.content(), pg.url)
        nav = mod_navegador.lanzar(self._pw, self.navegador, log=self._log, headless=True)
        try:
            ctx2 = nav.new_context(storage_state=estado, locale="es-ES")
            p2 = ctx2.new_page()
            p2.set_content(contenido, wait_until="load", timeout=45000)
            p2.pdf(path=destino, print_background=True)
        finally:
            nav.close()

    # ------------------------------------------------------------ ejecución
    def _capturar_error(self, indice):
        try:
            candidatas = list(self.paginas)
            if 0 <= self._pagina_activa < len(self.paginas):
                candidatas.insert(0, self.paginas[self._pagina_activa])
            for pg in candidatas:
                if not pg.is_closed():
                    ruta = os.path.splitext(self._ruta_log)[0] + "_error_paso%d.png" % indice
                    pg.screenshot(path=ruta, timeout=10000)
                    self.resultado.ruta_captura = ruta
                    self._log("Captura de pantalla: %s" % ruta)
                    return
        except Exception as e:
            self._log("No se pudo hacer la captura de pantalla (%s)" % type(e).__name__)

    def ejecutar(self):
        res = self.resultado
        res.total = len(self.flujo.pasos)
        self._abrir_log()
        try:
            self._log("Flujo «%s» — %d pasos — %s — %s" % (
                self.flujo.nombre, res.total, "oculto" if self.oculto else "visible",
                mod_navegador.NAVEGADORES.get(self.navegador, self.navegador)))
            for linea in self.lineas_inicio:
                self._log(linea)
            if self.filtros_aplicados:
                res.filtros = list(self.filtros_aplicados)
                self._log("Filtros elegidos para esta ejecución (el reporte guardado no cambia): %s"
                          % "; ".join(self._limpiar(x) for x in self.filtros_aplicados))
            problemas = self.flujo.problemas()
            if problemas:
                raise ErrorPaso("El flujo tiene errores: " + "; ".join(problemas[:3]))
            faltan = [v for v in self.flujo.variables_necesarias() if v not in self.variables]
            if faltan:
                raise ErrorPaso("Faltan variables: %s (usa --var nombre=valor)" % ", ".join(faltan))
            # las contraseñas de los pasos «Iniciar sesión» no se exigen aquí: si faltan, se piden al usuario
            sin_clave = [s for s in self.flujo.secretos_necesarios(incluir_inicio_sesion=False)
                         if not self._existe_secreto(s)]
            if sin_clave:
                raise ErrorPaso("Faltan contraseñas guardadas: %s (botón «Contraseñas»)" % ", ".join(sin_clave))
            self._con_navegador()
        except Detenido:
            res.detenido = True
            self._log("Detenido por el usuario.")
        except (ErrorPaso, mod_navegador.ErrorNavegador, plantillas.ErrorPlantilla, secretos.ErrorSecreto) as e:
            res.ok = False
            res.error = self._limpiar(_primeras_lineas(e))
            self._log("ERROR: %s" % res.error)
        except Exception as e:
            res.ok = False
            res.error = self._limpiar("%s: %s" % (type(e).__name__, _primeras_lineas(e)))
            self._log("ERROR inesperado: %s" % res.error)
        finally:
            self._log("Resultado: %s" % res.resumen())
            self._archivo_log.close()
            self._archivo_log = None
        return res

    def _existe_secreto(self, nombre):
        try:
            self._resolver(nombre)
            return True
        except secretos.ErrorSecreto:
            return False

    def _con_navegador(self):
        from playwright.sync_api import Error as ErrorPW
        from playwright.sync_api import sync_playwright
        res = self.resultado
        with sync_playwright() as p:
            ctx = mod_navegador.abrir_contexto(p, self.carpeta_perfil, self.navegador, self.oculto,
                                               lento_ms=700 if self.lento else 0, log=self._log)
            try:
                self._pw, self._ctx = p, ctx
                try:
                    ctx.add_init_script(JS_INIT_CARGA)     # cuenta los cambios del DOM (indicadores atascados)
                except ErrorPW:
                    pass
                ctx.on("page", self._registrar_pagina)
                for pg in ctx.pages:
                    self._registrar_pagina(pg)
                if not self.paginas:
                    ctx.new_page()
                ctx.set_default_timeout(int(float(self.flujo.opcion("timeout_paso") or 60) * 1000))
                pausa = self._pausa_entre_pasos()
                dias = [] if self.hasta is not None else self.dias_a_repetir()
                res.dias = list(dias)
                for n, dia in enumerate(dias or [None], 1):
                    self.fecha = dia
                    if dia is not None:
                        texto = "Día %s (%d de %d)" % (dia.strftime("%d/%m/%Y"), n, len(dias))
                        self._log("=== %s ===" % texto)
                        self.progreso(-1, "dia", texto)
                        self._indice_previo = self._recuperado_en = self._guardia_en = None
                        self._tras_abrir = False
                    if not self._recorrer_pasos(res, pausa):
                        return
                if self.al_final is not None:
                    pg = self._pagina_si_existe(self._pagina_activa if self._pagina_activa >= 0 else 0) or \
                        self._pagina_si_existe(0)
                    res.extra = self.al_final(self, pg)
                res.ok = True
            finally:
                self._pw = self._ctx = None
                try:
                    ctx.close()
                except Exception:
                    pass

    def dias_a_repetir(self):
        """Días de «Repetir por días» (opción del flujo; `dias` del ejecutor manda) o [] si no se repite."""
        if self.dias is not None:
            return list(self.dias)
        return mod_flujo.dias_a_repetir(self.flujo.opciones.get("repetir_dias"), self.hoy)

    def _recorrer_pasos(self, res, pausa):
        """Ejecuta los pasos (hasta `self.hasta` si se indicó).  False si un paso obligatorio falló."""
        from playwright.sync_api import Error as ErrorPW
        ejecutados = 0
        for i, paso in enumerate(self.flujo.pasos, 1):
            if self.hasta is not None and i - 1 >= self.hasta:
                break
            self._comprobar_detener()
            self._indice_actual = i - 1
            descripcion = paso.descripcion()
            if paso.desactivado:
                res.desactivados += 1
                self._log("Paso %d/%d: %s" % (i, res.total, descripcion))
                self._log("    desactivado: se omite")
                self.progreso(i - 1, "desactivado", "desactivado")
                continue
            if paso.sin_valor():            # v3.8: se dejó vacío: no se toca la página (ni se falla)
                res.sin_valor += 1
                self._log("Paso %d/%d: %s" % (i, res.total, descripcion))
                self._log("    sin valor: se salta este paso")
                self.progreso(i - 1, "omitido", "sin valor: se salta")
                continue
            if ejecutados and pausa > 0:
                self._dormir(pausa)
            ejecutados += 1
            self.progreso(i - 1, "inicio", descripcion)
            self._log("Paso %d/%d: %s%s" % (i, res.total, descripcion, " [opcional]" if paso.opcional else ""))
            inicio = time.monotonic()
            self._pista_login = ""
            try:
                self._proteger_literal(paso)
                carga = self._carga_activa(paso)
                pg_paso = self._pagina_si_existe(paso.pagina)
                if carga and pg_paso is not None and paso.tipo not in ("abrir_url", "esperar_segundos"):
                    self._esperar_carga(pg_paso, minimo=0, paso=paso)     # antes de buscar el elemento
                if carga and paso.tipo not in TIPOS_ESPERA:
                    self._preparar_accion(i - 1)
                self._ejecutar_paso(paso)
                if carga and paso.tipo in mod_flujo.TIPOS_CON_CARGA:
                    # tras un clic, tecla, lista… se observa un momento por si la petición tarda en
                    # empezar; tras escribir o esperar basta con mirar cómo está la página
                    minimo = 0 if paso.tipo in ("escribir", "esperar_elemento", "esperar_texto") else 0.25
                    self._esperar_carga(self._pagina_si_existe(paso.pagina), minimo=minimo, paso=paso)
            except Detenido:
                res.paso_fallido = i
                raise
            except (ErrorPaso, plantillas.ErrorPlantilla, secretos.ErrorSecreto, ErrorPW) as e:
                dur = time.monotonic() - inicio
                motivo = self._limpiar(_primeras_lineas(e))
                if paso.opcional:
                    res.omitidos += 1
                    self._log("    OMITIDO (opcional, %.1f s): %s" % (dur, motivo))
                    self.progreso(i - 1, "omitido", motivo)
                    continue
                res.paso_fallido = i
                res.error = motivo
                self._log("    ERROR (%.1f s): %s" % (dur, motivo))
                self.progreso(i - 1, "error", motivo)
                self._capturar_error(i)
                return False
            res.completados += 1
            self._indice_previo = i - 1
            self._tras_abrir = paso.tipo == "abrir_url"
            self._log("    OK (%.1f s)" % (time.monotonic() - inicio))
            self.progreso(i - 1, "ok", "")
        return True

    def _proteger_literal(self, paso):
        """Si un campo de contraseña lleva el texto en claro, ese texto no debe salir en ningún registro."""
        if paso.valor_literal_en_campo_contrasena():
            try:
                literal = self._r(paso.valor)
            except plantillas.ErrorPlantilla:
                return
            if len(literal) >= 3:
                self._valores_secretos.add(literal)

    def _registrar_pagina(self, pg):
        self.paginas.append(pg)
        pg.on("download", lambda d: self._descargas.append(d))
        pg.on("dialog", lambda dlg: self._aceptar_dialogo(dlg))
        self._seguir_red(pg)

    def _aceptar_dialogo(self, dlg):
        try:
            self._log("    (aviso del navegador aceptado: %s)" % _primeras_lineas(dlg.message, 1)[:80])
            dlg.accept()
        except Exception:
            pass
