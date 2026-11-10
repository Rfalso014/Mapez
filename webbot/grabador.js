/* Grabador del Bot Web: script inyectado en todas las páginas y marcos.
 *
 * - Captura clics, clic derecho, valores finales de campos (al salir del campo),
 *   listas, casillas y teclas Enter/Escape; y los envía a Python con window.__botEvento().
 * - Ignora todo lo que ocurra en su propia barra flotante (Shadow DOM) y los eventos
 *   no reales (isTrusted = false), como los clics lanzados por los scripts de la página.
 * - La barra flotante (solo en el documento principal) tiene: "Esperar a un elemento",
 *   "Esperar texto…", "Guardar esta página" y "Terminar".
 * - Contraseñas: un campo cuenta como contraseña si ALGUNA VEZ fue type=password (aunque luego
 *   el ojito lo convierta en texto), si su autocomplete es current/new-password o si su
 *   id/name/etiqueta/placeholder lo sugiere.  Su valor nunca se envía como texto normal.
 * - Calendarios: si el valor de un campo cambia tras clics dentro de un selector de fecha
 *   (sin teclear), se envía un único «escribir» con la fecha final (fecha_directa) y la lista
 *   de clics del calendario para que Python los marque como desactivados.
 * - Menús que se abren al pasar el ratón: se guarda el rastro de los elementos de menú por los que
 *   pasó el ratón (≥ 150 ms) desde el último paso; al hacer clic se envían antes pasos «pasar_raton»
 *   (auto) por los que abrieron algo que contiene (en cadena) lo que se pulsó.  Modo «Pasar el ratón»
 *   en la barra: el siguiente clic graba un «pasar_raton» sobre ese elemento (sin hacer clic).
 * - Listas con autocompletar: el valor que la web pone en el campo al elegir una opción no se graba
 *   como «escribir» (ya lo hace el clic en la opción).  Dos clics seguidos (< 1 s) en la etiqueta y en
 *   el cuadro del mismo campo se quedan en uno (el último), para no abrir y cerrar la lista.
 */
(() => {
  'use strict';
  if (window.__botGrabador) return;

  const esTop = window === window.top;
  let modo = null;            // null | 'elemento' | 'raton'
  let host = null, sombra = null, caja = null;
  const reportado = new WeakMap();   // último valor enviado de cada campo
  let contador = 0;
  const nuevoId = () => 'e' + Date.now().toString(36) + (contador++).toString(36) + Math.random().toString(36).slice(2, 5);

  // ---------------------------------------------------------------- utilidades
  // <<selectores-1  (mapeador.py reutiliza este bloque y el siguiente para calcular los selectores de los filtros)
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^\w-]/g, '\\$&');
  const unico = (sel, el) => {
    try { const l = document.querySelectorAll(sel); return l.length === 1 && l[0] === el; }
    catch (e) { return false; }
  };
  const idEstable = (id) => !!id && id.length < 60 &&
    !/\d{4,}|^:|[0-9a-f]{8}-[0-9a-f]{4}|^(ember|react|ext-gen|mui-|radix-|headlessui|__bot)/i.test(id);
  const claseDe = (n) => (n && typeof n.className === 'string') ? n.className : ((n && n.getAttribute && n.getAttribute('class')) || '');

  // Clases: «estables» (no autogeneradas ni de estado) y «con significado» (no genéricas de maquetación).
  const RX_CLASE_AUTO = /^(css|jss|sc|emotion|styled|svelte)[-_]\w|^_|\d{3,}|^[0-9a-f]{7,}$|^[a-z]{1,2}\d|[A-Z][a-z]+\d+[A-Za-z]*$/;
  const RX_CLASE_ESTADO = /^(active|focus|focused|selected|hover|hovered|disabled|today|current|open|opened|show|shown|hide|hidden|visible|checked|highlight|highlighted|old|new|in|out|fade|collapse|collapsed|expanded|ng-.*|is-.*|has-.*|js-.*|ui-state-.*|ui-corner-.*|mat-mdc-.*|ng-star-inserted)$/i;
  const RX_CLASE_GENERICA = /^(row|col(-[a-z]+)?(-\d+)?|container(-fluid)?|wrapper|clearfix|pull-(left|right)|float-.*|text-.*|[mp][trblxy]?-\d+|d-.*|flex.*|justify-.*|align-.*|w-\d+|h-\d+|content|inner|outer|box|item|items|list|table(-.*)?|tr|td|th|div|span|group|form-group|form-control|input-group|input-group-.*|panel|panel-.*|body|header|footer|btn(-.*)?|fa|fas|far|fab|glyphicon|icon|icons|label|link|nav|navbar|card(-.*)?|dropdown-menu|menu|clase|left|right|center|top|bottom|small|large|big|medium|lg|sm|md|xs)$/i;
  const claseEstable = (c) => /^[A-Za-z][\w-]*$/.test(c) && c.length >= 2 && c.length <= 40 &&
    !RX_CLASE_AUTO.test(c) && !RX_CLASE_ESTADO.test(c);
  const clasesEstables = (el) => Array.from(el.classList || []).filter(claseEstable);
  const claveSignificativa = (el) => clasesEstables(el).find((c) => !RX_CLASE_GENERICA.test(c));
  // selectores-1>>

  // Rastro del ratón (menús que se abren al pasar por encima) y último clic grabado (ver más abajo).
  const rastro = [];            // [{el, t0, t1, dur, abiertos: [raíces de lo que se abrió]}]
  let ultimoClicRec = null;     // {id, el, t}: para juntar «clic en la etiqueta» + «clic en el campo»
  const PASOS_QUE_REINICIAN = ['clic', 'pasar_raton', 'esperar_elemento', 'esperar_texto', 'tecla', 'guardar_pagina'];

  function enviar(ev) {
    ev.url = location.href;
    if (PASOS_QUE_REINICIAN.includes(ev.tipo)) rastro.length = 0;   // el rastro cuenta desde el último paso
    if (ev.tipo && ev.tipo !== 'clic') ultimoClicRec = null;
    try {
      if (typeof window.__botEvento === 'function') {
        Promise.resolve(window.__botEvento(ev)).catch(() => {});
      }
    } catch (e) { /* sin enlace con Python todavía */ }
  }

  // ------------------------------------------------------- tipos de elemento
  const TIPOS_NO_TEXTO = ['button', 'submit', 'reset', 'image', 'checkbox', 'radio', 'file', 'hidden', 'range', 'color'];
  function esCampoTexto(el) {
    if (!el || el.nodeType !== 1) return false;
    const t = el.tagName;
    if (t === 'TEXTAREA') return true;
    if (t === 'INPUT') return !TIPOS_NO_TEXTO.includes((el.type || 'text').toLowerCase());
    return !!el.isContentEditable && el.getAttribute('contenteditable') !== 'false' && el.getAttribute('role') !== 'button';
  }
  const valorDe = (el) => el.isContentEditable && el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA' ? el.innerText : el.value;

  // ---------------------------------------------------------- contraseñas
  const fueClave = new WeakSet();          // campos que alguna vez fueron type=password
  const clavesId = new Set(), clavesNombre = new Set();
  const RX_CLAVE = /pass|contrase|clave|pwd/i;

  function marcarClave(el) {
    if (!el || el.nodeType !== 1 || el.tagName !== 'INPUT') return;
    fueClave.add(el);
    if (el.id) clavesId.add(el.id);
    const n = el.getAttribute('name'); if (n) clavesNombre.add(n);
    try { el.setAttribute('data-bot-pw', '1'); } catch (e) { /* solo lectura */ }
  }
  function escanearClaves(raiz) {
    try {
      if (raiz.nodeType === 1 && raiz.tagName === 'INPUT' && (raiz.type || '').toLowerCase() === 'password') marcarClave(raiz);
      if (raiz.querySelectorAll) raiz.querySelectorAll('input[type=password]').forEach(marcarClave);
    } catch (e) { /* nodo raro */ }
  }
  function etiquetasDe(el) {
    const t = [];
    try { if (el.labels) for (const l of el.labels) t.push(l.textContent); } catch (e) { /* sin etiquetas */ }
    return t;
  }
  function esClave(el) {
    if (!el || el.nodeType !== 1 || el.tagName !== 'INPUT') return false;
    if ((el.type || '').toLowerCase() === 'password') { marcarClave(el); return true; }
    if (fueClave.has(el) || el.hasAttribute('data-bot-pw')) return true;
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    if (ac === 'current-password' || ac === 'new-password') return true;
    if ((el.id && clavesId.has(el.id)) || (el.getAttribute('name') && clavesNombre.has(el.getAttribute('name')))) return true;
    const textos = [el.id, el.getAttribute('name'), el.getAttribute('placeholder'), el.getAttribute('aria-label'),
      el.getAttribute('formcontrolname')].concat(etiquetasDe(el));
    return textos.some((t) => t && RX_CLAVE.test(t));
  }
  try {
    const obs = new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.type === 'attributes') {
          const el = m.target;
          if (el.tagName === 'INPUT' && ((m.oldValue || '').toLowerCase() === 'password' || (el.type || '').toLowerCase() === 'password')) {
            marcarClave(el);          // ya era (o sigue siendo) una contraseña, aunque ahora se vea como texto
          }
        } else {
          m.removedNodes.forEach((n) => {   // la web cambió el campo por otro nuevo: se recuerdan su id y name
            if (n.nodeType === 1 && n.tagName === 'INPUT' && fueClave.has(n)) marcarClave(n);
          });
          m.addedNodes.forEach(escanearClaves);
        }
      }
    });
    obs.observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['type'], attributeOldValue: true });
  } catch (e) { /* sin observador */ }
  document.addEventListener('DOMContentLoaded', () => escanearClaves(document));

  // ------------------------------------------------------ nombre legible
  // <<selectores-2
  function nombreVisible(el) {
    let n = el.getAttribute('aria-label');
    if (!n && el.labels && el.labels.length) n = norm(el.labels[0].textContent);
    if (!n && (el.tagName === 'INPUT') && ['button', 'submit', 'reset'].includes(el.type)) n = el.value;
    if (!n && el.tagName !== 'INPUT' && el.tagName !== 'SELECT' && el.tagName !== 'TEXTAREA') n = norm(el.innerText || el.textContent);
    if (!n) n = el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('name') || el.id || '';
    n = norm(n);
    return n.length > 60 ? n.slice(0, 57) + '...' : (n || el.tagName.toLowerCase());
  }

  // ---------------------------------------------------------------- selectores
  function rolDe(el) {
    const r = el.getAttribute('role');
    if (r) return r.split(' ')[0];
    const t = el.tagName.toLowerCase();
    if (t === 'button') return 'button';
    if (t === 'a' && el.hasAttribute('href')) return 'link';
    if (t === 'input' && ['button', 'submit', 'reset'].includes(el.type)) return 'button';
    return null;
  }
  function nombreAccesible(el) {
    const a = el.getAttribute('aria-label');
    if (a) return norm(a);
    if (el.tagName === 'INPUT') return norm(el.value);
    return norm(el.textContent);
  }
  function textoMinimo(e, t) {   // e contiene el texto t y ningún hijo lo contiene entero
    if (norm(e.textContent) !== t) return false;
    for (const h of e.children) if (norm(h.textContent) === t) return false;
    return true;
  }
  const esVisible = (e) => {
    try { return e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden'; }
    catch (x) { return true; }
  };
  // Cuántos elementos VISIBLES que casan con `base` (selector CSS) contienen exactamente el texto t.
  // (Los ocultos no cuentan: p. ej. el calendario cerrado de otro campo con los mismos años.)
  function cuentaTexto(base, t) {
    try {
      let n = 0;
      document.querySelectorAll(base).forEach((e) => { if (textoMinimo(e, t) && esVisible(e)) n++; });
      return n;
    } catch (e) { return 0; }
  }

  // ¿Es la raíz de una ventanita (calendario, menú…) añadida directamente al <body>?
  function esRaizPopup(n) {
    if (!n || n.nodeType !== 1 || n.parentElement !== document.body) return false;
    if (n.id && idEstable(n.id)) return false;
    let pos = '';
    try { pos = getComputedStyle(n).position; } catch (e) { return false; }
    return (pos === 'absolute' || pos === 'fixed') && !!claveSignificativa(n);
  }

  /* Ruta CSS (último recurso).  Para elementos dentro de popups no se ancla al <body> con
     nth-of-type (el orden de los popups cambia): se ancla a la clase de la raíz del popup. */
  function ruta(el) {
    const partes = [];
    let n = el;
    while (n && n.nodeType === 1 && n !== document.documentElement) {
      if (n.id && idEstable(n.id)) { partes.unshift('#' + cssEsc(n.id)); break; }
      if (n !== el && esRaizPopup(n)) {
        partes.unshift(n.tagName.toLowerCase() + '.' + cssEsc(claveSignificativa(n)));
        break;
      }
      let i = 1, p = n.previousElementSibling;
      while (p) { if (p.tagName === n.tagName) i++; p = p.previousElementSibling; }
      partes.unshift(n.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      n = n.parentElement;
    }
    return partes.join(' > ');
  }

  // Ancestro más cercano con una clase estable y con significado: devuelve {el, clase}.
  function ancestroConClase(el) {
    let n = el.parentElement, k = 0;
    while (n && n !== document.body && n !== document.documentElement && k++ < 12) {
      const c = claveSignificativa(n);
      if (c) return { el: n, clase: c };
      n = n.parentElement;
    }
    return null;
  }

  // Textos que cambian cada día (fechas, horas, números largos) o muy largos: no sirven para reconocer un
  // elemento que se espera («ACME Detalles … 24/10/2026 11:32 …»).
  const RX_VOLATIL = /\b\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}\b|\b\d{4}[\/\-.]\d{1,2}[\/\-.]\d{1,2}\b|\b\d{1,2}:\d{2}|\d{5,}/;
  const volatil = (t) => RX_VOLATIL.test(t || '') || norm(t).length > 40;
  function fragmentoEstable(t) {       // el trozo más largo sin fechas/horas, de 40 caracteres como mucho
    const trozos = norm(t).split(new RegExp(RX_VOLATIL.source, 'g')).map((x) => x.replace(/^[\s\-–—:,;()\[\]\/|·.]+|[\s\-–—:,;()\[\]\/|·.]+$/g, ''));
    let mejor = '';
    for (const x of trozos) if (x.replace(/[\W_]/g, '').length >= 3 && x.length > mejor.length) mejor = x;
    if (mejor.length > 40) { const c = mejor.slice(0, 40); const k = c.lastIndexOf(' '); mejor = k >= 10 ? c.slice(0, k) : c; }
    return mejor;
  }
  function etiquetaEstable(t) {        // el texto hasta la primera fecha/hora (para el nombre del paso)
    const n = norm(t);
    const m = RX_VOLATIL.exec(n);
    let e = (m ? n.slice(0, m.index) : n).replace(/[\s\-–—:,;(\[\/|·.]+$/, '');
    if (e.replace(/[\W_]/g, '').length < 3) e = fragmentoEstable(n);
    if (e.length > 40) { const c = e.slice(0, 40); const k = c.lastIndexOf(' '); e = k >= 10 ? c.slice(0, k) : c; }
    return e;
  }

  /* Alternativas de selector, de más a menos estable:
     #id, data-testid, [name], rol+nombre, texto (acotado al ancestro con clase propia),
     aria-label, placeholder, clases, ruta CSS.
     Con `soloEstable` (pasos «esperar»): sin textos que cambien (fechas, horas…); en su lugar, clases propias y
     un trozo fijo del texto (:has-text). */
  function candidatos(el, soloEstable) {
    const res = [];
    const add = (s) => { if (s && !res.includes(s)) res.push(s); };
    if (!el || el.nodeType !== 1) return res;
    const tag = el.tagName.toLowerCase();
    let estable = false;       // tiene un identificador propio fiable (id, data-testid o name)

    if (el.id && idEstable(el.id)) { const s = '#' + cssEsc(el.id); if (unico(s, el)) { add(s); estable = true; } }

    for (const a of ['data-testid', 'data-test', 'data-qa', 'data-cy']) {
      const v = el.getAttribute(a);
      if (v) { const s = '[' + a + '="' + esc(v) + '"]'; if (unico(s, el)) { add(s); estable = true; } }
    }

    const name = el.getAttribute('name');
    if (name) {
      let s = tag + '[name="' + esc(name) + '"]';
      if (unico(s, el)) { add(s); estable = true; }
      else if (el.hasAttribute('value')) {
        s = tag + '[name="' + esc(name) + '"][value="' + esc(el.getAttribute('value')) + '"]';
        if (unico(s, el)) { add(s); estable = true; }
      }
    }

    const rol = rolDe(el);
    const nom = nombreAccesible(el);
    if ((rol === 'button' || rol === 'link' || rol === 'menuitem' || rol === 'tab' || rol === 'option') &&
        nom && nom.length <= 80 && !(soloEstable && volatil(nom))) {
      let n = 0;
      document.querySelectorAll('button, a[href], input[type=button], input[type=submit], input[type=reset], [role]')
        .forEach((e) => { if (rolDe(e) === rol && nombreAccesible(e).toLowerCase() === nom.toLowerCase()) n++; });
      if (n === 1) add('role=' + rol + '[name="' + esc(nom) + '"]');
    }

    const t = norm(el.textContent);
    let conTexto = false;
    if (soloEstable && t && volatil(t) && tag !== 'input' && tag !== 'select' && tag !== 'textarea') {
      // texto que cambia: un trozo fijo con :has-text (contiene), acotado a su clase propia si la tiene
      const frag = fragmentoEstable(t);
      if (frag.length >= 6) {
        const propia = clasesEstables(el).find((c) => !RX_CLASE_GENERICA.test(c)) || clasesEstables(el)[0];
        add((propia ? tag + '.' + cssEsc(propia) : tag) + ':has-text("' + esc(frag) + '")');
      }
    } else if (t && t.length <= 80 && tag !== 'input' && tag !== 'select' && tag !== 'textarea' && textoMinimo(el, t)) {
      conTexto = true;
      if (!estable && t.length <= 40) {
        // Texto corto sin id propio (años, meses, días, opciones de menú…): primero acotado a su contenedor.
        const lit = ':text-is("' + esc(t) + '")';
        const anc = ancestroConClase(el);
        if (anc) {
          const base = '.' + cssEsc(anc.clase) + ' ' + tag;
          const n = cuentaTexto(base, t);
          if (n === 1) add(base + lit);
        }
        const propia = clasesEstables(el).find((c) => !RX_CLASE_GENERICA.test(c)) || clasesEstables(el)[0];
        if (propia) {
          const base = tag + '.' + cssEsc(propia);
          const n = cuentaTexto(base, t);
          if (n === 1) add(base + lit);
        }
        const n = cuentaTexto(tag, t);
        if (n === 1) add(tag + lit);
      } else if (cuentaTexto(tag, t) === 1) {
        add(tag + ':text-is("' + esc(t) + '")');
      }
    }

    const aria = el.getAttribute('aria-label');
    if (aria) { const s = tag + '[aria-label="' + esc(aria) + '"]'; if (unico(s, el)) add(s); }
    const ph = el.getAttribute('placeholder');
    if (ph) { const s = tag + '[placeholder="' + esc(ph) + '"]'; if (unico(s, el)) add(s); }

    if (!estable && !conTexto) {
      // Sin texto (iconos, botones con dibujo): clases propias, acotadas a un ancestro con id o clase propia.
      const cl = clasesEstables(el).slice(0, 2);
      if (cl.length) {
        const s = tag + '.' + cl.map(cssEsc).join('.');
        if (unico(s, el)) add(s);
        else {
          let n = el.parentElement, k = 0;
          while (n && n !== document.body && n !== document.documentElement && k++ < 6) {
            const pref = (n.id && idEstable(n.id)) ? '#' + cssEsc(n.id) : (claveSignificativa(n) ? '.' + cssEsc(claveSignificativa(n)) : '');
            if (pref && unico(pref + ' ' + s, el)) { add(pref + ' ' + s); break; }
            n = n.parentElement;
          }
        }
      }
    }

    const principales = res.slice(0, 4);
    principales.push(ruta(el));
    return principales.filter((s, i, a) => s && a.indexOf(s) === i);
  }
  // selectores-2>>
  window.__botSelector = (el) => candidatos(el)[0];

  function objetivoClic(t) {
    const inter = t.closest('button, a[href], input, select, textarea, label, summary, ' +
      '[role=button], [role=menuitem], [role=option], [role=tab], [role=link], [onclick]');
    return inter || t;
  }
  // ------------------------------------------- inicio de sesión (para agrupar sus pasos en uno)
  // Un elemento pertenece a un formulario de inicio de sesión si está en la misma zona (formulario, o el
  // ancestro con el botón de entrar) que un campo de contraseña.  `rol`: campo | enviar | incidental (el ojito
  // de la contraseña, el recuadro td/div de un campo…).
  const RX_ENTRAR = /iniciar|entrar|ingresar|acceder|login|log in|sign in|aceptar|continuar|enviar|submit|conectar/i;
  const RX_OJO = /appended|prepended|mostrar|ocultar|show|hide|toggle|eye|ojo|visibility/i;
  const cuentaCampos = (n) => n.querySelectorAll('input:not([type=hidden]), select, textarea').length;
  function regionLogin(pw) {
    const f = pw.closest('form');
    if (f && cuentaCampos(f) <= 15) return f;
    let region = null;
    for (let n = pw.parentElement, k = 0; n && n !== document.body && k < 8; n = n.parentElement, k++) {
      if (cuentaCampos(n) > 15) break;
      region = n;
      if (cuentaCampos(n) >= 2 && n.querySelector('button, input[type=submit], input[type=button], input[type=image], [role=button], a[href], .dxb')) break;
    }
    return region;
  }
  function envuelveUnCampo(el) {        // el (icono, td, div) es parte del recuadro de un único campo
    for (let n = el, k = 0; n && n.nodeType === 1 && n !== document.body && k < 4; n = n.parentElement, k++) {
      const c = cuentaCampos(n);
      if (c === 1) return true;
      if (c > 1) return false;
    }
    return false;
  }
  function infoLogin(el) {
    try {
      for (const pw of document.querySelectorAll('input[type=password], input[data-bot-pw]')) {
        const reg = regionLogin(pw);
        if (!reg || !reg.contains(el)) continue;
        let rol = 'campo';
        if (!esCampoTexto(el)) {
          const txt = norm(el.innerText || el.value || '');
          const extra = (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '') + ' ' + claseDe(el);
          const boton = el.matches('button, input[type=submit], input[type=button], input[type=image], [role=button], a[href], .dxb, .dxb *');
          if (RX_OJO.test(txt + ' ' + extra)) rol = 'incidental';
          else if (RX_ENTRAR.test(txt) || (el.type || '').toLowerCase() === 'submit') rol = 'enviar';
          else if (envuelveUnCampo(el)) rol = 'incidental';
          else rol = boton ? 'enviar' : 'incidental';
        }
        return { token: 'L:' + location.host + location.pathname + location.hash + ':' + (pw.name || pw.id || 'pw'),
                 rol, host: location.hostname };
      }
    } catch (e) { /* nodo raro */ }
    return null;
  }

  function descripcionElemento(el, soloEstable) {
    const d = { candidatos: candidatos(el, soloEstable), objetivo: nombreVisible(el) };
    if (soloEstable && volatil(d.objetivo)) d.objetivo = etiquetaEstable(d.objetivo) || d.objetivo;
    const login = infoLogin(el);
    if (login) d.login = login;
    return d;
  }

  // -------------------------------------------------------------- filtros
  const ignorar = (e) => !e.isTrusted || (host && e.composedPath().includes(host));
  const origen = (e) => { const p = e.composedPath(); return p.length ? p[0] : e.target; };

  // ------------------------------------------------- selectores de fecha (calendarios)
  const RX_PICKER = /datepicker|calendar|picker|flatpickr|daterangepicker|mat-calendar|react-datepicker|ui-datepicker/i;
  function enPicker(el) {
    for (let n = el; n && n.nodeType === 1 && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      if (RX_PICKER.test(claseDe(n) + ' ' + (n.id || ''))) return true;
    }
    return false;
  }
  const tecleado = new WeakSet();        // campos en los que el usuario escribió con el teclado
  let sesion = null;                     // {base: Map(campo→valor), ids: [], apertura: {id, el}|null, t, n}
  let ultimoClicFuera = null;            // {id, el, t}: último clic fuera de un calendario

  function camposTexto() {
    const r = [];
    document.querySelectorAll('input, textarea').forEach((e) => {
      if (esCampoTexto(e) && (e.type || '').toLowerCase() !== 'password' && !esClave(e) && !enPicker(e)) r.push(e);
    });
    return r;
  }
  function iniciarSesion() {
    const base = new Map();
    camposTexto().forEach((e) => base.set(e, valorDe(e)));
    const ap = ultimoClicFuera && (Date.now() - ultimoClicFuera.t < 15000) ? ultimoClicFuera : null;
    sesion = { base, ids: [], apertura: ap, t: Date.now(), n: 0 };
  }
  function aperturaValida(campo) {
    if (!sesion || !sesion.apertura) return null;
    const el = sesion.apertura.el;
    const cont = (campo.parentElement && campo.parentElement.parentElement) || campo.parentElement;
    return (cont && cont.contains(el)) ? sesion.apertura.id : null;
  }
  /* Compara los campos con los valores de antes del calendario.  Si alguno cambió sin teclear, envía
     un «escribir» con la fecha final (fecha_directa).  Devuelve true si cerró la sesión. */
  function revisarSesion(porSondeo) {
    if (!sesion) return false;
    if (sesion.n === 0) { if (!porSondeo) sesion = null; return !porSondeo; }
    const cambiados = [];
    sesion.base.forEach((antes, campo) => {
      if (!campo.isConnected) return;
      const ahora = valorDe(campo);
      if (ahora !== antes && ahora !== reportado.get(campo) && !tecleado.has(campo) && ahora !== '') cambiados.push(campo);
    });
    if (cambiados.length) {
      cambiados.forEach((campo) => {
        const d = descripcionElemento(campo);
        d.tipo = 'escribir';
        d.valor = valorDe(campo);
        d.password = false;
        d.fecha_directa = true;
        d.picker_ids = sesion.ids.slice();
        d.apertura_id = aperturaValida(campo);
        d.campo = campo.getAttribute('name') || campo.id || 'fecha';
        reportado.set(campo, d.valor);
        enviar(d);
      });
      sesion = null;
      return true;
    }
    if (!porSondeo || Date.now() - sesion.t > 8000) { sesion = null; return true; }   // abandonado sin cambios
    return false;
  }
  setInterval(() => { if (sesion && sesion.n > 0 && Date.now() - sesion.t > 600) revisarSesion(true); }, 250);

  window.addEventListener('input', (e) => {
    if (!e.isTrusted) return;
    const t = origen(e);
    if (t && t.nodeType === 1) tecleado.add(t);
  }, true);

  // ------------------------------------------- ratón encima: menús que se despliegan al pasar
  const RX_MENU = /menu|nav|dropdown|dxm|submenu|item/i;
  const RX_SEPARADOR = /(^|[\s_-])(sub|submenu|sub-menu|dropdown|dropdown-menu|popup|popover|dxm-popup|flyout)([\s_-]|$)/i;
  const VENTANA_APERTURA = 600, PERMANENCIA_MIN = 150, MAX_RATON = 3;
  const posicion = (n) => { try { return getComputedStyle(n).position; } catch (e) { return ''; } };
  function esMenuLike(n) {
    const t = n.tagName;
    if (t === 'A' || t === 'LI' || t === 'BUTTON') return true;
    const r = n.getAttribute('role');
    if (r && /^(menuitem|menuitemcheckbox|menuitemradio|menu|menubar)$/.test(r)) return true;
    if (n.hasAttribute('aria-haspopup') || n.hasAttribute('aria-expanded')) return true;
    return RX_MENU.test(claseDe(n));
  }
  function representante(t) {     // el elemento de menú más profundo que contiene a t
    for (let n = t, k = 0; n && n.nodeType === 1 && n !== document.body && n !== document.documentElement && k < 6; n = n.parentElement, k++) {
      if (esMenuLike(n)) return n;
    }
    return null;
  }
  // Un «separador» es el contenedor de un submenú: entre un elemento de menú y otro de su submenú hay uno.
  function esSeparador(n) {
    if (!n || n.nodeType !== 1) return false;
    if (/^(UL|OL|MENU)$/.test(n.tagName)) return true;
    const r = n.getAttribute('role');
    if (r && /^(menu|menubar|listbox|tree|group)$/.test(r)) return true;
    if (RX_SEPARADOR.test(claseDe(n))) return true;
    const p = posicion(n);
    return p === 'absolute' || p === 'fixed';
  }
  function haySeparador(ext, int) {
    for (let n = int.parentElement; n && n !== ext; n = n.parentElement) if (esSeparador(n)) return true;
    return false;
  }
  function itemDe(x) {               // la opción de menú (li, menuitem…) a la que pertenece x
    let item = x;
    for (let n = x.parentElement, k = 0; n && n !== document.body && k < 4; n = n.parentElement, k++) {
      if (esSeparador(n)) break;
      if (n.tagName === 'LI' || /^menuitem/.test(n.getAttribute('role') || '') || /item/i.test(claseDe(n))) item = n;
    }
    return item;
  }
  function mismoItem(a, b) {
    if (a === b) return true;
    if (a.contains(b)) return !haySeparador(a, b);
    if (b.contains(a)) return !haySeparador(b, a);
    return itemDe(a) === itemDe(b);
  }
  function visibleAhora(e) {
    try {
      if (!e.getClientRects().length) return false;
      const cs = getComputedStyle(e);
      return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0.05;
    } catch (x) { return false; }
  }
  function raizPopup(e) {            // el contenedor flotante (menú, lista…) al que pertenece e
    for (let n = e, k = 0; n && n.nodeType === 1 && n !== document.body && n !== document.documentElement && k < 10; n = n.parentElement, k++) {
      const r = n.getAttribute('role');
      const p = posicion(n);
      if (p === 'absolute' || p === 'fixed' || (r && /^(menu|listbox|dialog|tooltip)$/.test(r)) || RX_SEPARADOR.test(claseDe(n))) return n;
    }
    return null;
  }
  function anotarAbierto(ent, e) {
    if (!e || e.nodeType !== 1 || ent.abiertos.length >= 8) return;
    const x = ent.el;
    if (e === x || e.contains(x) || (host && (e === host || host.contains(e)))) return;
    if (!visibleAhora(e)) return;
    const raiz = raizPopup(e);
    if (!raiz || raiz === x || raiz.contains(x) || ent.abiertos.includes(raiz)) return;
    ent.abiertos.push(raiz);
  }
  function entradaActiva() {
    const u = rastro[rastro.length - 1];
    return u && Date.now() - u.t0 <= VENTANA_APERTURA ? u : null;
  }
  try {   // lo que aparece (se hace visible o se añade) poco después de pasar el ratón por un elemento
    const obsRaton = new MutationObserver((muts) => {
      const ent = entradaActiva();
      if (!ent) return;
      let n = 0;
      for (const m of muts) {
        if (n++ > 40) break;
        if (m.type === 'attributes') anotarAbierto(ent, m.target);
        else m.addedNodes.forEach((a) => anotarAbierto(ent, a));
      }
    });
    obsRaton.observe(document, { subtree: true, childList: true, attributes: true,
      attributeFilter: ['style', 'class', 'hidden', 'aria-hidden', 'aria-expanded', 'open'] });
  } catch (e) { /* sin observador */ }
  function revisarDescendientes(ent) {   // menús CSS (:hover): el submenú es descendiente y no hay cambios en el DOM
    const item = itemDe(ent.el);
    let k = 0;
    for (const d of item.querySelectorAll('ul, ol, [role=menu], [role=listbox], div')) {
      if (k++ > 40) break;
      if (d === ent.el || d.contains(ent.el) || !esSeparador(d) || !visibleAhora(d)) continue;
      if (!d.querySelector('a, li, button, [role=menuitem], [role=option]')) continue;
      if (!ent.abiertos.includes(d)) ent.abiertos.push(d);
      break;
    }
  }
  window.addEventListener('mouseover', (e) => {
    if (!e.isTrusted || ignorar(e) || modo) return;
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    const rep = representante(t);
    const ahora = Date.now();
    const ult = rastro[rastro.length - 1];
    if (ult && !ult.t1 && rep === ult.el) return;
    if (ult && !ult.t1) ult.t1 = ahora;
    if (!rep) return;
    const i = rastro.findIndex((r) => r.el === rep);
    let ent;
    if (i >= 0) {       // ya estaba: pasa al final (orden en que pasó el ratón) y suma lo que estuvo encima
      ent = rastro.splice(i, 1)[0];
      ent.dur += (ent.t1 || ahora) - ent.t0;
      ent.t0 = ahora; ent.t1 = 0;
    } else {
      ent = { el: rep, t0: ahora, t1: 0, dur: 0, abiertos: [] };
    }
    rastro.push(ent);
    if (rastro.length > 30) rastro.shift();
    setTimeout(() => { try { revisarDescendientes(ent); } catch (x) { /* nodo raro */ } }, 120);
  }, true);

  /* Pasos «pasar_raton» que hacen falta antes de un clic en T: los elementos del rastro (≥ 150 ms encima,
     el más profundo de cada opción, sin contar T ni lo que lo envuelve) que abrieron algo que contiene a T
     o a otro elemento elegido (cadena de submenús).  Como máximo 3, en el orden en que pasó el ratón. */
  function pasosRaton(T) {
    const ahora = Date.now();
    let lista = [];
    for (const r of rastro) {
      if (!r.el.isConnected) continue;
      const dur = r.dur + ((r.t1 || ahora) - r.t0);
      const previo = lista.find((x) => mismoItem(x.el, r.el));
      if (previo) {
        previo.dur += dur;
        previo.abiertos = previo.abiertos.concat(r.abiertos);
        if (previo.el.contains(r.el)) previo.el = r.el;
        lista.splice(lista.indexOf(previo), 1);
        lista.push(previo);
      } else {
        lista.push({ el: r.el, dur, abiertos: r.abiertos.slice() });
      }
    }
    lista = lista.filter((x) => x.dur >= PERMANENCIA_MIN && x.el !== T && !T.contains(x.el) && !mismoItem(x.el, T));
    const relacionados = [T];
    const elegidos = [];
    for (let i = lista.length - 1; i >= 0; i--) {
      const x = lista[i];
      const it = itemDe(x.el);
      const rel = relacionados.some((r) => (it !== r && it.contains(r) && haySeparador(it, r)) ||
        x.abiertos.some((a) => a.contains(r) && !a.contains(x.el)));
      if (rel) { elegidos.unshift(x); relacionados.push(x.el); }
    }
    return elegidos.slice(-MAX_RATON);
  }
  function enviarPasosRaton(T) {
    let lista = [];
    try { lista = pasosRaton(T); } catch (e) { lista = []; }
    lista.forEach((x) => {
      const d = descripcionElemento(x.el);
      d.tipo = 'pasar_raton';
      d.auto = true;
      enviar(d);
    });
  }

  // --------------------------------- listas con autocompletar (el valor lo pone la web al elegir)
  const RX_OVERLAY = /overlay|listbox|autocomplete|suggest|dropdown|popup|popover|menu|select/i;
  function esOpcion(el) {
    const r = el.closest('[role=option], [role=menuitem], [role=menuitemradio], [role=treeitem], [role=listbox], [role=menu]');
    if (r) return true;
    for (let n = el, k = 0; n && n.nodeType === 1 && n !== document.body && k < 10; n = n.parentElement, k++) {
      const p = posicion(n);
      if ((p === 'absolute' || p === 'fixed') && RX_OVERLAY.test(claseDe(n) + ' ' + (n.id || ''))) return true;
    }
    return false;
  }
  const RX_COMBO = /autocomplete|combobox|v-select|v-combobox|select2|chosen|choices|multiselect|typeahead|ng-select|mat-select/i;
  function esCombo(el) {
    const r = el.getAttribute('role');
    const ac = (el.getAttribute('aria-autocomplete') || '').toLowerCase();
    if (r === 'combobox' || (ac && ac !== 'none') || /^(listbox|true)$/.test(el.getAttribute('aria-haspopup') || '')) return true;
    if (el.closest('[role=combobox]')) return true;
    for (let n = el.parentElement, k = 0; n && k < 4; n = n.parentElement, k++) if (RX_COMBO.test(claseDe(n))) return true;
    return false;
  }
  let antesOpcion = null;               // {t, base: Map(campo → valor)} al pulsar una opción
  const porOpcion = new WeakMap();      // campo → valor que puso la web al elegir una opción
  const teclasNav = new WeakSet();      // campos en los que se usaron las flechas (elegir con el teclado)
  function revisarOpcion() {
    if (!antesOpcion || Date.now() - antesOpcion.t > 900) return;
    antesOpcion.base.forEach((antes, campo) => {
      if (!campo.isConnected) return;
      const v = valorDe(campo);
      if (v !== antes) porOpcion.set(campo, v);
    });
  }
  window.addEventListener('pointerdown', (e) => {
    if (!e.isTrusted || ignorar(e) || modo) return;
    const t = origen(e);
    if (!t || t.nodeType !== 1 || !esOpcion(t)) return;
    const base = new Map();
    camposTexto().forEach((c) => base.set(c, valorDe(c)));
    antesOpcion = { t: Date.now(), base };
    [60, 300, 800].forEach((ms) => setTimeout(revisarOpcion, ms));
  }, true);

  // Dos clics seguidos en la etiqueta y en el cuadro de UN mismo campo (p. ej. un v-autocomplete).
  const INTERACTIVOS = 'button, a[href], input, select, textarea, [role=button], [role=option], [role=menuitem], [role=tab], [role=link], [onclick]';
  function mismoCampo(a, b) {
    if (!a || !b || a === b || !a.isConnected || !b.isConnected) return false;
    if ((a.matches(INTERACTIVOS) && a.tagName !== 'LABEL') || (b.matches(INTERACTIVOS) && b.tagName !== 'LABEL')) return false;
    let lca = a;
    while (lca && !lca.contains(b)) lca = lca.parentElement;
    if (!lca || lca === document.body || lca === document.documentElement || lca.tagName === 'FORM') return false;
    if (lca.querySelectorAll('*').length > 150) return false;
    const ctl = Array.from(lca.querySelectorAll('input:not([type=hidden]), select, textarea, [role=combobox], [contenteditable=""], [contenteditable=true]'));
    const unicos = ctl.filter((c) => !ctl.some((o) => o !== c && c.contains(o)));
    return unicos.length === 1;
  }

  // ---------------------------------------------------------------- campos
  function volcar(el) {
    if (!el || !esCampoTexto(el)) return;
    const v = valorDe(el);
    if (v === reportado.get(el)) return;
    if (sesion && sesion.n > 0 && !tecleado.has(el) && !esClave(el)) {
      // El calendario puso el valor sin que se tecleara: se envía como fecha directa.
      if (revisarSesion(false)) { if (v === reportado.get(el)) return; }
    }
    const clave = esClave(el);
    let desactivar = false;
    if (!clave) {
      // ¿El valor lo puso la web al elegir una opción de una lista (autocompletar, combobox…)?
      const porOp = porOpcion.has(el) && porOpcion.get(el) === v;
      const combo = esCombo(el) && !tecleado.has(el) && !teclasNav.has(el);
      if (porOp || combo) {
        if (!tecleado.has(el)) {       // no se tecleó nada: el clic en la opción ya lo hace
          reportado.set(el, v);
          porOpcion.delete(el);
          return;
        }
        desactivar = true;             // se tecleó para filtrar y luego se eligió: se conserva desactivado
      }
    }
    reportado.set(el, v);
    tecleado.delete(el);
    teclasNav.delete(el);
    porOpcion.delete(el);
    const d = descripcionElemento(el);
    d.tipo = 'escribir';
    d.valor = v;
    d.password = clave;
    d.campo = el.getAttribute('name') || el.id || (d.password ? 'clave' : (el.type || 'campo'));
    if (desactivar) {
      d.desactivado = true;
      d.nota = 'Valor puesto al elegir una opción de la lista (el clic en la opción ya lo hace); se conserva desactivado.';
    }
    enviar(d);
  }
  window.__botVolcar = () => { revisarSesion(false); volcar(document.activeElement); };

  document.addEventListener('focusin', (e) => {
    const t = origen(e);
    if (esCampoTexto(t) && !reportado.has(t)) reportado.set(t, valorDe(t));
  }, true);
  document.addEventListener('click', (e) => {     // el valor al hacer clic en un campo también es el «de antes»
    const t = origen(e);
    if (e.isTrusted && esCampoTexto(t) && !reportado.has(t)) reportado.set(t, valorDe(t));
  }, true);

  const alCambiar = (e) => {
    if (ignorar(e)) return;
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    if (esCampoTexto(t)) { volcar(t); return; }
    if (e.type !== 'change') return;
    if (t.tagName === 'SELECT') {
      const op = t.selectedOptions && t.selectedOptions[0];
      const d = descripcionElemento(t);
      d.tipo = 'seleccionar';
      d.valor = t.value;
      d.etiqueta = op ? norm(op.textContent) : '';
      enviar(d);
    } else if (t.tagName === 'INPUT' && (t.type === 'checkbox' || t.type === 'radio')) {
      const d = descripcionElemento(t);
      d.tipo = 'marcar';
      d.marcado = !!t.checked;
      enviar(d);
    }
  };
  window.addEventListener('change', alCambiar, true);
  window.addEventListener('focusout', alCambiar, true);

  // ---------------------------------------------------------------- clics
  function omitirClic(el) {
    const t = el.tagName;
    if (t === 'TEXTAREA' || t === 'SELECT' || t === 'OPTION') return true;
    if (t === 'INPUT' && !['button', 'submit', 'reset', 'image'].includes((el.type || 'text').toLowerCase())) return true;
    if (t === 'LABEL' && el.control && !['button', 'submit', 'reset'].includes(el.control.type)) return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function marcarEsperaElemento(e) {
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    const d = descripcionElemento(objetivoClic(t), true);
    d.tipo = 'esperar_elemento';
    d.estado = 'visible';
    enviar(d);
    aplicarModo(null);
  }

  function marcarPasarRaton(e) {
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    const d = descripcionElemento(representante(t) || objetivoClic(t));
    d.tipo = 'pasar_raton';
    d.auto = false;
    enviar(d);
    aplicarModo(null);
  }

  // En los modos «esperar elemento» y «pasar el ratón» el clic no llega a la página.
  ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'dblclick', 'auxclick'].forEach((n) => {
    window.addEventListener(n, (e) => {
      if (!modo || ignorar(e)) return;
      e.preventDefault(); e.stopImmediatePropagation();
    }, true);
  });

  window.addEventListener('click', (e) => {
    if (ignorar(e)) return;
    if (modo) {
      e.preventDefault(); e.stopImmediatePropagation();
      if (modo === 'raton') marcarPasarRaton(e); else marcarEsperaElemento(e);
      return;
    }
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    const el = objetivoClic(t);
    const dentro = enPicker(t) || enPicker(el);
    // Antes de anotar este clic: si el calendario anterior ya cambió algún campo, esa fecha va primero.
    if (!dentro && sesion) revisarSesion(false);
    if (omitirClic(el)) return;
    if (e.detail >= 3) return;
    const d = descripcionElemento(el);
    d.tipo = 'clic';
    d.boton = e.button === 1 ? 'medio' : 'izquierdo';
    d.doble = e.detail === 2;
    d.id = nuevoId();
    const ahora = Date.now();
    if (dentro) {
      if (!sesion) iniciarSesion();
      sesion.n++; sesion.t = ahora; sesion.ids.push(d.id);
      d.picker = true;
      ultimoClicRec = null;
    } else {
      ultimoClicFuera = { id: d.id, el, t: ahora };
      // etiqueta + cuadro del mismo campo en menos de 1 s: el segundo sustituye al primero
      const prev = ultimoClicRec;
      if (prev && !d.doble && ahora - prev.t < 1000 && mismoCampo(prev.el, el)) d.reemplaza = prev.id;
      if (!d.reemplaza) enviarPasosRaton(el);       // menús que había que abrir pasando el ratón
      ultimoClicRec = d.doble ? null : { id: d.id, el, t: ahora };
    }
    enviar(d);
  }, true);

  window.addEventListener('contextmenu', (e) => {
    if (ignorar(e)) return;
    if (modo) { e.preventDefault(); e.stopImmediatePropagation(); return; }
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    enviarPasosRaton(objetivoClic(t));
    const d = descripcionElemento(objetivoClic(t));
    d.tipo = 'clic';
    d.boton = 'derecho';
    d.doble = false;
    d.id = nuevoId();
    enviar(d);
  }, true);

  // ---------------------------------------------------------------- teclas
  window.addEventListener('keydown', (e) => {
    if (ignorar(e)) return;
    if (modo && e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); aplicarModo(null); return; }
    if (/^Arrow(Up|Down)$/.test(e.key)) { const c = origen(e); if (c && esCampoTexto(c)) teclasNav.add(c); return; }
    if (e.key !== 'Enter' && e.key !== 'Escape') return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    const campo = esCampoTexto(t) || t.tagName === 'SELECT';
    if (e.key === 'Enter' && (!campo || t.tagName === 'TEXTAREA' || t.isContentEditable)) return; // en botones/enlaces ya hay un clic
    if (esCampoTexto(t)) volcar(t);       // primero el valor escrito
    const d = campo ? descripcionElemento(t) : { candidatos: [], objetivo: '' };
    d.tipo = 'tecla';
    d.tecla = e.key;
    enviar(d);
  }, true);

  // ------------------------------------------------- modo y barra flotante
  function difundir(m) {
    for (let i = 0; i < window.frames.length; i++) {
      try { window.frames[i].postMessage({ __botModo: m }, '*'); } catch (_) { /* marco inaccesible */ }
    }
  }
  function aplicarModo(m) {
    modo = m;
    if (esTop) actualizarBarra();
    if (!m && caja) caja.style.display = 'none';
    difundir(m);
  }
  window.addEventListener('message', (e) => {
    const d = e.data;
    if (d && typeof d === 'object' && '__botModo' in d && e.source === window.parent) {
      modo = d.__botModo;
      if (!modo && caja) caja.style.display = 'none';
      difundir(modo);
    }
  });

  window.addEventListener('mousemove', (e) => {
    if (!modo || !esTop || ignorar(e) || !caja) return;
    const t = origen(e);
    if (!t || t.nodeType !== 1) return;
    const r = (modo === 'raton' ? (representante(t) || objetivoClic(t)) : objetivoClic(t)).getBoundingClientRect();
    Object.assign(caja.style, { display: 'block', left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' });
  }, true);

  let actualizarBarra = () => {};

  function crearBarra() {
    if (!esTop || host) return;
    host = document.createElement('div');
    host.id = '__bot_host__';
    host.style.cssText = 'all:initial;position:fixed;top:10px;right:10px;z-index:2147483647;';
    sombra = host.attachShadow({ mode: 'open' });
    sombra.innerHTML =
      '<style>' +
      ':host{all:initial}' +
      '.barra{font:13px/1.3 Segoe UI,Arial,sans-serif;background:#1f2937;color:#fff;border-radius:8px;' +
      'box-shadow:0 4px 14px rgba(0,0,0,.4);padding:6px 8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;max-width:560px}' +
      '.asa{cursor:move;font-weight:600;padding:2px 6px;color:#fca5a5;user-select:none}' +
      'button{font:inherit;border:0;border-radius:5px;padding:4px 9px;cursor:pointer;background:#374151;color:#fff}' +
      'button:hover{background:#4b5563}button.act{background:#f59e0b;color:#111}' +
      '#__bot_fin{background:#b91c1c}#__bot_fin:hover{background:#dc2626}' +
      '.panel{display:none;width:100%;gap:6px}.panel.ver{display:flex}' +
      'input,select{flex:1;font:inherit;padding:3px 6px;border-radius:4px;border:1px solid #6b7280;min-width:0}' +
      '.estado{width:100%;font-size:12px;color:#fcd34d;display:none}' +
      '.caja{position:fixed;pointer-events:none;border:2px solid #f59e0b;background:rgba(245,158,11,.18);display:none;box-sizing:border-box}' +
      '</style>' +
      '<div class="caja" id="__bot_caja"></div>' +
      '<div class="barra" id="__bot_barra">' +
      '<span class="asa" id="__bot_asa">&#9679; Grabando</span>' +
      '<button id="__bot_b-elem" type="button">Esperar a un elemento</button>' +
      '<button id="__bot_b-raton" type="button">&#128433; Pasar el ratón</button>' +
      '<button id="__bot_b-texto" type="button">Esperar texto…</button>' +
      '<button id="__bot_b-pag" type="button">&#128190; Guardar esta página</button>' +
      '<button id="__bot_fin" type="button">Terminar</button>' +
      '<div class="panel" id="__bot_panel"><input id="__bot_txt" placeholder="Texto que debe aparecer en la página">' +
      '<button id="__bot_ok" type="button">Añadir</button></div>' +
      '<div class="panel" id="__bot_panel2"><select id="__bot_fmt" aria-label="Formato">' +
      '<option value="pdf">PDF</option><option value="html">HTML</option><option value="csv">CSV (la tabla más grande)</option></select>' +
      '<button id="__bot_ok2" type="button">Añadir paso</button></div>' +
      '<div class="estado" id="__bot_estado">Haz clic en el elemento que hay que esperar (Esc para cancelar)</div>' +
      '</div>';
    caja = sombra.getElementById('__bot_caja');
    const bElem = sombra.getElementById('__bot_b-elem');
    const panel = sombra.getElementById('__bot_panel');
    const panel2 = sombra.getElementById('__bot_panel2');
    const txt = sombra.getElementById('__bot_txt');
    const estado = sombra.getElementById('__bot_estado');

    const bRaton = sombra.getElementById('__bot_b-raton');
    actualizarBarra = () => {
      bElem.classList.toggle('act', modo === 'elemento');
      bRaton.classList.toggle('act', modo === 'raton');
      estado.textContent = modo === 'raton'
        ? 'Haz clic en el elemento sobre el que hay que pasar el ratón (no se hará clic; Esc para cancelar)'
        : 'Haz clic en el elemento que hay que esperar (Esc para cancelar)';
      estado.style.display = modo ? 'block' : 'none';
    };
    bElem.addEventListener('click', () => {
      panel.classList.remove('ver'); panel2.classList.remove('ver');
      aplicarModo(modo === 'elemento' ? null : 'elemento');
    });
    bRaton.addEventListener('click', () => {
      panel.classList.remove('ver'); panel2.classList.remove('ver');
      aplicarModo(modo === 'raton' ? null : 'raton');
    });
    sombra.getElementById('__bot_b-texto').addEventListener('click', () => {
      aplicarModo(null);
      panel2.classList.remove('ver');
      panel.classList.toggle('ver');
      if (panel.classList.contains('ver')) txt.focus();
    });
    sombra.getElementById('__bot_b-pag').addEventListener('click', () => {
      aplicarModo(null);
      panel.classList.remove('ver');
      panel2.classList.toggle('ver');
    });
    const anadirTexto = () => {
      const v = txt.value.trim();
      if (!v) return;
      enviar({ tipo: 'esperar_texto', texto: v });
      txt.value = '';
      panel.classList.remove('ver');
    };
    sombra.getElementById('__bot_ok').addEventListener('click', anadirTexto);
    sombra.getElementById('__bot_ok2').addEventListener('click', () => {
      enviar({ tipo: 'guardar_pagina', formato: sombra.getElementById('__bot_fmt').value, titulo: document.title || '' });
      panel2.classList.remove('ver');
    });
    txt.addEventListener('keydown', (e) => { if (e.key === 'Enter') anadirTexto(); e.stopPropagation(); });
    sombra.getElementById('__bot_fin').addEventListener('click', () => {
      try { window.__botVolcar(); } catch (_) {}
      enviar({ tipo: 'terminar' });
    });

    // Arrastrar la barra
    const asa = sombra.getElementById('__bot_asa');
    asa.addEventListener('mousedown', (e) => {
      const r = host.getBoundingClientRect();
      const dx = e.clientX - r.left, dy = e.clientY - r.top;
      const mover = (m) => { host.style.left = (m.clientX - dx) + 'px'; host.style.top = (m.clientY - dy) + 'px'; host.style.right = 'auto'; };
      const soltar = () => { window.removeEventListener('mousemove', mover, true); window.removeEventListener('mouseup', soltar, true); };
      window.addEventListener('mousemove', mover, true);
      window.addEventListener('mouseup', soltar, true);
      e.preventDefault();
    });

    document.documentElement.appendChild(host);
  }

  const iniciarBarra = () => { try { crearBarra(); } catch (e) { /* página especial */ } };
  if (esTop) {
    if (document.documentElement) iniciarBarra();
    document.addEventListener('DOMContentLoaded', iniciarBarra);
    window.addEventListener('load', iniciarBarra);
    // Si la página reemplaza todo el documento, se vuelve a poner la barra.
    setInterval(() => { if (host && !host.isConnected && document.documentElement) document.documentElement.appendChild(host); }, 1000);
  }

  window.__botGrabador = { version: 5 };
})();
