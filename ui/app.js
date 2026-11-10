/* Bot Web 3.6 — interfaz «Centro de control».  JavaScript sin dependencias ni paso de compilación: funciona sin Internet.
 *
 * - Todas las llamadas a la API llevan la cabecera X-Bot-Token (el token llega en la dirección: #t=…).
 * - El progreso llega como eventos (GET /api/eventos?desde=N&espera=20, en bucle).
 * - Las preguntas del bot (iniciar sesión, «la contraseña falló») se muestran como ventanas y se contestan con la API.
 * - Todo el texto de la página se crea con h() (textContent): nunca se mete HTML que venga de las páginas web.
 * - v3.5: la página NUNCA se reconstruye entera.  Las secciones con listas (Inicio, Reportes, Páginas, Vigilancia, Correo,
 *   Accesos, Historial, Grabar y Mapear) se quedan vivas al cambiar de sección (se vuelve al instante, con el mismo
 *   desplazamiento, lo abierto sigue abierto) y se ponen al día por detrás; sus filas se pintan por clave
 *   (claveLista) y solo cambian las que cambiaron.  Los eventos actualizan la fila, la cifra o la línea afectada.
 */
(() => {
  'use strict';

  const E = { token: '', ultimo: 0, trabajo: null, oyentes: [], ayuda: null, preguntaAbierta: null, modal: null,
              ajustes: null, sinPermiso: false, oyenteModal: null,
              // v3.5
              vista: null, vistas: new Map(), nav: 0, titActual: ['', ''], curso: new Map(), recien: new Map(),
              trabajoReporte: {}, loteReporte: {}, buscador: null, novedades: 0,
              externos: [] };            // v3.7: lo que ejecutan las tareas de Windows (tabla en_curso)
  const $ = (s, r) => (r || document).querySelector(s);

  // ------------------------------------------------------------------ utilidades
  function leerToken() {
    const m = /[#&]t=([^&]+)/.exec(location.hash);
    if (m) {
      E.token = decodeURIComponent(m[1]);
      try { sessionStorage.setItem('botweb_token', E.token); } catch (e) { /* sin almacenamiento */ }
      const r = /[#&]r=([^&]+)/.exec(location.hash);
      history.replaceState(null, '', '#/' + (r ? decodeURIComponent(r[1]) : 'inicio'));
    } else {
      try { E.token = sessionStorage.getItem('botweb_token') || ''; } catch (e) { E.token = ''; }
    }
  }

  async function api(metodo, ruta, datos) {
    const op = { method: metodo, headers: { 'X-Bot-Token': E.token } };
    if (datos !== undefined) { op.headers['Content-Type'] = 'application/json'; op.body = JSON.stringify(datos); }
    const r = await fetch('/api/' + ruta, op);
    const tipo = r.headers.get('Content-Type') || '';
    if (r.status === 401) { E.sinPermiso = true; mostrarSinPermiso(); throw new Error('Sin permiso'); }
    if (!tipo.includes('application/json')) {
      if (!r.ok) throw new Error('Error ' + r.status);
      return r.blob();
    }
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('Error ' + r.status));
    return j;
  }

  function h(tag, at, ...hijos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(at || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
      else if (k === 'value') e.value = v;
      else if (k === 'checked') e.checked = !!v;
      else if (k === 'html') { /* no se usa: nada de HTML externo */ }
      else e.setAttribute(k, v === true ? '' : String(v));
    }
    const poner = (x) => {
      if (x === null || x === undefined || x === false) return;
      if (Array.isArray(x)) { x.forEach(poner); return; }
      e.appendChild(x instanceof Node ? x : document.createTextNode(String(x)));
    };
    hijos.forEach(poner);
    return e;
  }
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

  // v3.5: iconos de trazo (24×24, sin emojis).  ico('play') → <svg class="ico">.
  const ICONOS = {
    inicio: 'M4 11 12 4l8 7v9h-5v-6H9v6H4z',
    reportes: 'M5 4h14v16H5zM8 8h8M8 12h8M8 16h5',
    paginas: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
    grabar: 'M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0M12 12m-3.5 0a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0',
    mapear: 'M12 12m-7 0a7 7 0 1 0 14 0a7 7 0 1 0-14 0M12 2.5v5M12 16.5v5M2.5 12h5M16.5 12h5',
    vigilancia: 'M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0M12 12 18 6',
    correo: 'M3 6h18v12H3zM3 7l9 6 9-6',
    accesos: 'M8 14a4 4 0 1 1 3.5-6H21v3h-2v3h-3v-3h-4.5A4 4 0 0 1 8 14z',
    historial: 'M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0M12 8v4l3 2',
    ajustes: 'M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1',
    buscar: 'M11 11m-6 0a6 6 0 1 0 12 0a6 6 0 1 0-12 0M20 20l-4.5-4.5',
    play: 'M8 5v14l11-7z',
    parar: 'M7 7h10v10H7z',
    cerrar: 'M6 6l12 12M18 6 6 18',
    mas: 'M12 5v14M5 12h14',
    editar: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
    copiar: 'M9 9h11v11H9zM5 15H4V4h11v1',
    borrar: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
    carpeta: 'M3 6h6l2 2h10v11H3z',
    archivo: 'M6 3h8l4 4v14H6zM14 3v4h4',
    descargar: 'M12 4v11M7 10l5 5 5-5M5 20h14',
    subir: 'M12 19V5M6 11l6-6 6 6',
    bajar: 'M12 5v14M6 13l6 6 6-6',
    refrescar: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7',
    filtros: 'M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1M15 4v4M9 10v4M17 16v4',
    estrella: 'M12 4l2.5 5.2 5.5.8-4 3.9.9 5.6L12 16.9 7.1 19.5 8 13.9 4 10l5.5-.8z',
    campana: 'M6 16v-5a6 6 0 1 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0',
    ok: 'M5 12l5 5 9-10',
    alerta: 'M12 4 2 20h20zM12 10v4M12 17v.5',
    info: 'M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0M12 11v5M12 8v.5',
    atras: 'M15 5l-7 7 7 7',
    menu: 'M4 7h16M4 12h16M4 17h16',
    clip: 'M20 11l-8.5 8.5a5 5 0 0 1-7-7L13 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L14 7',
    pausa: 'M8 5v14M16 5v14',
    calendario: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
    enlace: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
    cargando: 'M12 3a9 9 0 1 0 9 9',
    rayo: 'M13 3 5 14h6l-1 7 8-11h-6z',
  };
  const RELLENOS = new Set(['play', 'parar']);
  const SVG = 'http://www.w3.org/2000/svg';
  function ico(n, clase) {
    const s = document.createElementNS(SVG, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.7');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('focusable', 'false');
    s.setAttribute('class', 'ico' + (clase ? ' ' + clase : ''));
    const p = document.createElementNS(SVG, 'path');
    p.setAttribute('d', ICONOS[n] || ICONOS.info);
    if (RELLENOS.has(n)) p.setAttribute('fill', 'currentColor');
    s.appendChild(p);
    return s;
  }
  // Los textos de los botones que empezaban con un símbolo («▶ Ejecutar», «⚙ Usar filtros», «✕»…) llevan ahora su icono.
  const GLIFOS = [['▶', 'play'], ['●', 'grabar'], ['■', 'parar'], ['⚙', 'filtros'], ['⌖', 'mapear'], ['◎', 'vigilancia'],
    ['▦', 'paginas'], ['↻', 'refrescar'], ['⤓', 'descargar'], ['＋', 'mas'], ['+ ', 'mas'], ['★', 'estrella'], ['✕', 'cerrar'],
    ['🔎', 'buscar'], ['📁', 'carpeta'], ['✉', 'correo'], ['↑', 'subir'], ['↓', 'bajar'], ['←', 'atras']];
  function conIcono(texto) {
    if (typeof texto !== 'string') return { hijos: [texto], soloIcono: false };
    for (const [g, n] of GLIFOS) {
      if (texto.startsWith(g)) {
        const resto = texto.slice(g.length).trim();
        return { hijos: [ico(n), resto], soloIcono: !resto };
      }
    }
    return { hijos: [texto], soloIcono: false };
  }
  const boton = (texto, accion, clase, extra) => {
    const c = conIcono(texto);
    return h('button', Object.assign({ type: 'button', class: 'boton ' + (clase || '') + (c.soloIcono ? ' solo-icono' : ''), onclick: accion }, extra || {}), ...c.hijos);
  };
  const chip = (texto, clase) => h('span', { class: 'chip ' + (clase || '') }, texto);
  const panel = (titulo, ...hijos) => h('div', { class: 'panel' }, titulo ? h('h2', null, titulo) : null, ...hijos);
  function estadoChip(res) {
    if (res === 'ok') return chip('Bien', 'ok');
    if (res === 'error') return chip('Falló', 'error');
    if (res === 'detenido') return chip('Detenido', 'aviso');
    return chip('—');
  }
  function fechaLarga(d) {
    try { return d.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }); }
    catch (e) { return d.toDateString(); }
  }
  // v3.5: fechas cortas para las columnas de datos («hoy 10:23», «ayer 18:00», «27/10 09:30»)
  const dos = (n) => (n < 10 ? '0' : '') + n;
  const isoDia = (d) => d.getFullYear() + '-' + dos(d.getMonth() + 1) + '-' + dos(d.getDate());
  function cuandoCorto(cuando) {
    const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(cuando || '');
    if (!m) return cuando || '';
    const hoy = new Date();
    const ayer = new Date(hoy.getTime() - 864e5);
    const dia = m[1] + '-' + m[2] + '-' + m[3];
    const hm = m[4] + ':' + m[5];
    if (dia === isoDia(hoy)) return 'hoy ' + hm;
    if (dia === isoDia(ayer)) return 'ayer ' + hm;
    return m[3] + '/' + m[2] + ' ' + hm;
  }
  const horaDe = (cuando) => { const m = /(\d\d):(\d\d)/.exec(cuando || ''); return m ? m[1] + ':' + m[2] : ''; };
  // «30/10/2026 8:00:00» (lo que dice el Programador de Windows) → «mañana 08:00»
  function proximaCorta(t) {
    const m = /(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}):(\d\d)/.exec(t || '');
    if (!m) return t || '';
    const iso = m[3] + '-' + dos(+m[2]) + '-' + dos(+m[1]);
    const hoy = new Date();
    const hm = dos(+m[4]) + ':' + m[5];
    if (iso === isoDia(hoy)) return 'hoy ' + hm;
    if (iso === isoDia(new Date(hoy.getTime() + 864e5))) return 'mañana ' + hm;
    return dos(+m[1]) + '/' + dos(+m[2]) + ' ' + hm;
  }
  function duracionTexto(s) {
    if (s === null || s === undefined || s === '') return '';
    s = Math.round(+s);
    if (s < 60) return s + ' s';
    return Math.floor(s / 60) + ' min' + (s % 60 ? ' ' + (s % 60) + ' s' : '');
  }
  const nombreArchivo = (ruta) => String(ruta || '').split(/[\\/]/).pop();
  const normalizar = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  const ICONO_TOAST = { ok: 'ok', error: 'alerta', aviso: 'alerta' };
  function toast(texto, clase, ms) {
    const t = h('div', { class: 'toast ' + (clase || ''), role: clase === 'error' ? 'alert' : 'status' }, ico(ICONO_TOAST[clase] || 'info'), h('div', null, texto));
    $('#toasts').appendChild(t);
    setTimeout(() => t.remove(), ms || 6000);
  }
  function errorToast(e) { toast(e && e.message ? e.message : String(e), 'error', 8000); }

  function titulo(t, sub) {
    E.titActual = [t, sub || ''];
    $('#titulo').textContent = t;
    $('#subtitulo').textContent = sub || '';
    document.title = t + ' — Bot Web';
  }

  function mostrarSinPermiso() {
    const c = $('#contenido');
    c.replaceChildren(panel('Esta ventana no tiene permiso',
      h('p', null, 'Abre la interfaz desde el bot (python bot.py): cada vez se crea un permiso nuevo para esta sesión.')));
  }

  // ------------------------------------------------------------------ ventanas (modales)
  function cerrarModal() {
    cerrarPopFecha(false);                 // v3.6: el calendario de un campo de fecha de la ventana
    const f = $('#modal-fondo');
    f.classList.add('oculto');
    f.replaceChildren();
    const previo = E.modal && E.modal.foco;
    if (E.modal && E.modal.alCerrar) E.modal.alCerrar();
    E.modal = null;
    E.preguntaAbierta = null;
    if (previo && previo.isConnected) { try { previo.focus({ preventScroll: true }); } catch (e) { /* nada */ } }
  }
  function abrirModal(opc) {
    const foco = E.modal ? E.modal.foco : document.activeElement;
    cerrarModal();
    const pie = h('div', { class: 'pie' });
    const caja = h('div', { class: 'modal' + (opc.ancho ? ' ancho' : ''), role: 'dialog', 'aria-modal': 'true',
                            'aria-labelledby': 'modal-titulo' }, h('h2', { id: 'modal-titulo' }, opc.titulo), opc.contenido, pie);
    for (const b of opc.botones || []) pie.appendChild(boton(b.texto, () => b.accion && b.accion(), b.clase));
    const f = $('#modal-fondo');
    f.replaceChildren(caja);
    f.classList.remove('oculto');
    E.modal = { caja, alCerrar: opc.alCerrar, foco };
    caja.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && opc.escape !== false) { ev.preventDefault(); (opc.alEscape || cerrarModal)(); }
      if (ev.key === 'Enter' && opc.alEnter && ev.target.tagName !== 'TEXTAREA' && ev.target.tagName !== 'BUTTON') { ev.preventDefault(); opc.alEnter(); }
      if (ev.key === 'Tab') {                                    // el foco no sale de la ventana
        const foc = [...caja.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.disabled && x.offsetParent !== null);
        if (!foc.length) return;
        const pri = foc[0], ult = foc[foc.length - 1];
        if (ev.shiftKey && document.activeElement === pri) { ev.preventDefault(); ult.focus(); }
        else if (!ev.shiftKey && document.activeElement === ult) { ev.preventDefault(); pri.focus(); }
      }
    });
    const enfocar = caja.querySelector('input:not([type=checkbox]):not([readonly]), select, textarea') || caja.querySelector('.pie button.primario') || caja.querySelector('button');
    // (al instante: con un temporizador, si el usuario —o una prueba— ya estaba escribiendo en otro campo de la ventana,
    // el foco saltaba al primero y lo escrito iba a parar allí)
    if (enfocar) { try { enfocar.focus({ preventScroll: true }); } catch (e) { /* nada */ } }
    return caja;
  }
  function confirmar(tituloTxt, texto, siTxt, peligro) {
    return new Promise((resolver) => {
      abrirModal({ titulo: tituloTxt, contenido: h('p', null, texto), alEscape: () => { cerrarModal(); resolver(false); },
        botones: [{ texto: 'Cancelar', accion: () => { cerrarModal(); resolver(false); } },
                  { texto: siTxt || 'Aceptar', clase: peligro ? 'primario' : 'primario', accion: () => { cerrarModal(); resolver(true); } }] });
    });
  }
  function pedirTexto(tituloTxt, etiqueta, inicial) {
    return new Promise((resolver) => {
      const inp = h('input', { type: 'text', value: inicial || '', 'aria-label': etiqueta });
      const ok = () => { const v = inp.value.trim(); cerrarModal(); resolver(v || null); };
      abrirModal({ titulo: tituloTxt, contenido: h('div', null, h('p', null, etiqueta), inp), alEnter: ok,
        alEscape: () => { cerrarModal(); resolver(null); },
        botones: [{ texto: 'Cancelar', accion: () => { cerrarModal(); resolver(null); } }, { texto: 'Aceptar', clase: 'primario', accion: ok }] });
    });
  }
  function campoClave(valor, etiqueta) {
    const inp = h('input', { type: 'password', value: valor || '', autocomplete: 'new-password', 'aria-label': etiqueta || 'Contraseña' });
    const ver = boton('Mostrar', () => {
      const oculto = inp.type === 'password';
      inp.type = oculto ? 'text' : 'password';
      ver.textContent = oculto ? 'Ocultar' : 'Mostrar';
    }, 'chico');
    return { caja: h('div', { class: 'campo-clave' }, inp, ver), inp };
  }

  // v3.5: un campo de carpeta o de archivo con el botón «Elegir…» (icono de carpeta), que abre el explorador de Windows
  // EN ESTE PC (POST /api/elegir: el servidor del bot abre la ventana y devuelve la ruta elegida).  El campo sigue siendo
  // editable (se puede escribir o pegar la ruta, con plantillas como Correo\{fecha_correo:%Y-%m}).  Al elegir se lanzan
  // los eventos «input» y «change» del campo, así que quien lo escuchaba se entera igual que si se hubiera escrito.
  // opc: { tipo: 'carpeta' | 'archivo' | 'guardar', filtros: [['Excel', '*.xlsx'], …], titulo }.
  // Devuelve la caja (div.campo-ruta) con el campo y el botón; el campo `inp` se sigue usando como antes.
  function campoRuta(inp, opc) {
    opc = opc || {};
    const tipo = opc.tipo || 'carpeta';
    const elegir = boton('📁 Elegir…', async () => {
      elegir.disabled = true;
      try {
        const r = await api('POST', 'elegir', { tipo, inicial: inp.value, filtros: opc.filtros || null, titulo: opc.titulo || null });
        if (r.ruta) {
          inp.value = r.ruta;
          inp.dispatchEvent(new Event('input', { bubbles: true }));
          inp.dispatchEvent(new Event('change', { bubbles: true }));
        }
      } catch (e) { errorToast(e); } finally { elegir.disabled = false; }
    }, 'chico', { 'data-elegir': tipo, title: tipo === 'carpeta' ? 'Elegir la carpeta en el explorador de Windows' : 'Elegir el archivo en el explorador de Windows' });
    return h('div', { class: 'campo-ruta' }, inp, elegir);
  }
  const FILTROS_EXCEL = [['Excel', '*.xlsx'], ['CSV (separado por ;)', '*.csv']];
  const FILTROS_ANOTAR = [['CSV (separado por ;)', '*.csv'], ['Excel', '*.xlsx'], ['Texto', '*.txt']];

  // ------------------------------------------------------------------ v3.7: «Archivo descargado» (nombre y carpeta)
  // El «Nombre del archivo» se escribe SIN la extensión: se pone sola (en el paso «Descargar» se guarda con {ext} al
  // final, igual que flujo.nombre_con_ext / nombre_sin_ext en Python).  Si no se toca, el paso queda como estaba.
  const NOMBRE_ARCHIVO_DEFECTO = '{reporte} {hoy:%Y-%m-%d}';
  const NOMBRE_ARCHIVO_VARIAS = '{reporte} - {nombre} {hoy:%Y-%m-%d}';
  const NOMBRE_PAGINA_DEFECTO = '{pagina} - {variantes}';
  const conExt = (t) => { const n = (t || '').trim(); return !n || n.includes('{ext}') ? n : n + '{ext}'; };
  const sinExt = (t) => { t = t || ''; return t.endsWith('{ext}') ? t.slice(0, -5) : t; };
  // «Se guardará como: Ventas 2026-10-30.xlsx en C:\…» (POST /api/plantilla con «archivo»).  datos() = el cuerpo.
  function vistaArchivo(datos) {
    const el = h('div', { class: 'ayuda', 'data-vista-archivo': '1', 'aria-live': 'polite' });
    let t = null; let n = 0;
    const act = () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const k = ++n;
        try {
          const r = await api('POST', 'plantilla', datos());
          if (k !== n) return;
          el.textContent = r.error ? '⚠ ' + r.error : 'Se guardará como: ' + r.archivo + ' en ' + r.carpeta;
          el.title = r.ruta || '';
        } catch (e) { if (k === n) el.textContent = ''; }
      }, 200);
    };
    act();
    return { el, act };
  }
  // El campo «Nombre del archivo» con sus atajos («Nombre del reporte + fecha», «Nombre que da la web»).
  // opc: { defecto, textoDefecto, web: true|false }
  function campoNombreArchivo(inp, opc) {
    opc = opc || {};
    const poner = (v) => { inp.value = v; inp.dispatchEvent(new Event('input', { bubbles: true })); inp.dispatchEvent(new Event('change', { bubbles: true })); };
    return h('div', { class: 'fila' },
      boton(opc.textoDefecto || 'Nombre del reporte + fecha', () => poner(opc.defecto || NOMBRE_ARCHIVO_DEFECTO), 'chico', { 'data-nombre-rapido': 'reporte' }),
      opc.web === false ? null : boton('Nombre que da la web', () => poner('{nombre}'), 'chico', { 'data-nombre-rapido': 'web' }));
  }

  // ------------------------------------------------------------------ v3.6: campo de fecha con calendario
  // Lo que se guarda sigue siendo el texto de siempre («15/10/2026», «{ayer:%d/%m/%Y}», «{dias:-7}»…: el motor y los
  // reportes guardados no cambian).  analizarFecha / componerFecha hacen lo mismo que plantillas.analizar_fecha /
  // plantilla_fecha en Python (las pruebas comprueban que coinciden).
  const FORMATO_DEFECTO = '%d/%m/%Y';
  const FORMATOS_FECHA = [['%d/%m/%Y', ''], ['%Y-%m-%d', 'como los campos de fecha'], ['%d-%m-%Y', ''], ['%m/%d/%Y', 'el mes primero'],
    ['%d.%m.%Y', ''], ['%Y/%m/%d', ''], ['%d/%m/%y', 'año con 2 cifras'], ['%Y%m%d', 'sin separadores'], ['%d %b %Y', 'mes en inglés']];
  const FECHAS_NOMBRADAS = ['hoy', 'ayer', 'inicio_mes', 'fin_mes', 'inicio_mes_anterior', 'fin_mes_anterior', 'lunes_semana',
    'lunes_semana_anterior', 'domingo_semana_anterior', 'inicio_anio'];
  // Botones de «Cambia sola» (en este orden) y sus nombres en palabras
  const RELATIVAS = [['hoy', 'Hoy'], ['ayer', 'Ayer'], ['dias', 'Hace N días'], ['lunes_semana', 'Lunes de esta semana'],
    ['lunes_semana_anterior', 'Lunes de la semana pasada'], ['domingo_semana_anterior', 'Domingo de la semana pasada'],
    ['inicio_mes', 'Inicio de este mes'], ['fin_mes', 'Fin de este mes'], ['inicio_mes_anterior', 'Inicio del mes anterior'],
    ['fin_mes_anterior', 'Fin del mes anterior'], ['inicio_anio', '1 de enero'], ['fecha', 'El día que se descarga']];
  const PALABRAS_FECHA = { hoy: 'hoy', ayer: 'ayer', lunes_semana: 'lunes de esta semana', lunes_semana_anterior: 'lunes de la semana pasada',
    domingo_semana_anterior: 'domingo de la semana pasada', inicio_mes: 'inicio de este mes', fin_mes: 'fin de este mes',
    inicio_mes_anterior: 'inicio del mes anterior', fin_mes_anterior: 'fin del mes anterior', inicio_anio: '1 de enero',
    fecha: 'el día que se descarga' };
  // Fechas escritas tal cual que se entienden como «fecha fija» (sin aaaammdd; dd/mm antes que mm/dd)
  const FORMATOS_FIJA = ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y', '%Y/%m/%d', '%d/%m/%y', '%m/%d/%Y', '%d %b %Y'];
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  // (Python escribe %b / %B / %a / %A en inglés: así lo escribe también el bot)
  const MESES_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const DIAS_EN = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const DIAS_SEMANA = [['L', 'lunes'], ['M', 'martes'], ['X', 'miércoles'], ['J', 'jueves'], ['V', 'viernes'], ['S', 'sábado'], ['D', 'domingo']];
  const CODIGOS_STRFTIME = 'aAbBcdHIjmMpSUwWxXyYzZ%';

  const sumarDias = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const soloDia = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const lunesDe = (d) => sumarDias(d, -((d.getDay() + 6) % 7));
  function deIso(t) {
    const m = /^(\d{4})-(\d\d)-(\d\d)$/.exec(t || '');
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    return d.getMonth() === +m[2] - 1 && d.getDate() === +m[3] ? d : null;
  }
  // strftime de las fechas (lo mismo que Python para %d %m %Y %y %b %B %a %A %j %%); null si hay otro código
  function strfFecha(d, fmt) {
    let ok = true;
    const s = String(fmt).replace(/%(.)/g, (todo, c) => {
      switch (c) {
        case 'd': return dos(d.getDate());
        case 'm': return dos(d.getMonth() + 1);
        case 'Y': return String(d.getFullYear()).padStart(4, '0');
        case 'y': return dos(d.getFullYear() % 100);
        case 'b': return MESES_EN[d.getMonth()].slice(0, 3);
        case 'B': return MESES_EN[d.getMonth()];
        case 'a': return DIAS_EN[(d.getDay() + 6) % 7].slice(0, 3);
        case 'A': return DIAS_EN[(d.getDay() + 6) % 7];
        case 'j': return String(Math.round((soloDia(d) - new Date(d.getFullYear(), 0, 1)) / 864e5) + 1).padStart(3, '0');
        case '%': return '%';
        default: ok = false; return todo;
      }
    });
    return ok ? s : null;
  }
  const formatoValido = (f) => !!f && /%/.test(f) && [...String(f).matchAll(/%(.?)/g)].every((m) => m[1] && CODIGOS_STRFTIME.includes(m[1]));
  // Lee «15/10/2026» con un formato (exacto, con sus ceros, como strptime + strftime en Python)
  function leerConFormato(s, fmt) {
    const partes = {};
    let rx = '';
    for (let i = 0; i < fmt.length; i++) {
      if (fmt[i] === '%' && i + 1 < fmt.length) {
        const c = fmt[++i];
        if (c === 'd' || c === 'm' || c === 'y') { rx += '(\\d{2})'; partes[Object.keys(partes).length] = c; }
        else if (c === 'Y') { rx += '(\\d{4})'; partes[Object.keys(partes).length] = c; }
        else if (c === 'b') { rx += '(' + MESES_EN.map((x) => x.slice(0, 3)).join('|') + ')'; partes[Object.keys(partes).length] = c; }
        else return null;
      } else rx += fmt[i].replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
    }
    const m = new RegExp('^' + rx + '$').exec(s);
    if (!m) return null;
    let a = null, mes = null, dia = null;
    Object.values(partes).forEach((c, k) => {
      const v = m[k + 1];
      if (c === 'd') dia = +v;
      else if (c === 'm') mes = +v;
      else if (c === 'Y') a = +v;
      else if (c === 'y') a = +v + (+v < 69 ? 2000 : 1900);
      else if (c === 'b') mes = MESES_EN.findIndex((x) => x.slice(0, 3) === v) + 1;
    });
    if (a === null || mes === null || dia === null) return null;
    const d = new Date(a, mes - 1, dia);
    if (d.getFullYear() !== a || d.getMonth() !== mes - 1 || d.getDate() !== dia) return null;
    return strfFecha(d, fmt) === s ? d : null;
  }
  const RX_RELATIVA = new RegExp('^\\{(' + FECHAS_NOMBRADAS.join('|') + '|fecha)(?::([^{}]+))?\\}$');
  function analizarFecha(texto) {
    const t = texto === null || texto === undefined ? '' : String(texto);
    if (!t.trim()) return { modo: 'vacia' };
    const s = t.trim();
    let m = RX_RELATIVA.exec(s);
    if (m && (m[2] === undefined || formatoValido(m[2]))) return { modo: 'relativa', que: m[1], n: null, formato: m[2] === undefined ? null : m[2] };
    m = /^\{dias:\s*([+-]?\d+)\s*(?::([^{}]+))?\}$/.exec(s);
    if (m && (m[2] === undefined || formatoValido(m[2]))) return { modo: 'relativa', que: 'dias', n: parseInt(m[1], 10), formato: m[2] === undefined ? null : m[2] };
    if (s === t && !/[{}]/.test(s)) {
      for (const f of FORMATOS_FIJA) {
        const d = leerConFormato(s, f);
        if (d) return { modo: 'fija', fecha: isoDia(d), formato: f };
      }
    }
    return { modo: 'mano', texto: t };
  }
  function componerFecha(a) {
    const modo = (a && a.modo) || 'vacia';
    const f = (a && a.formato) || null;
    if (modo === 'vacia') return '';
    if (modo === 'mano') return String(a.texto || '');
    if (modo === 'fija') {
      const d = deIso(a.fecha);
      const s = d ? strfFecha(d, f || FORMATO_DEFECTO) : null;
      return s === null ? null : s.replace(/\{/g, '{{').replace(/\}/g, '}}');
    }
    if (a.que === 'dias') return '{dias:' + (parseInt(a.n, 10) || 0) + (f ? ':' + f : '') + '}';
    return '{' + a.que + (f ? ':' + f : '') + '}';
  }
  function fechaRelativa(que, n, hoy) {
    const d = soloDia(hoy || new Date());
    const y = d.getFullYear(), mes = d.getMonth();
    switch (que) {
      case 'ayer': return sumarDias(d, -1);
      case 'dias': return sumarDias(d, parseInt(n, 10) || 0);
      case 'inicio_mes': return new Date(y, mes, 1);
      case 'fin_mes': return new Date(y, mes + 1, 0);
      case 'inicio_mes_anterior': return new Date(y, mes - 1, 1);
      case 'fin_mes_anterior': return new Date(y, mes, 0);
      case 'lunes_semana': return lunesDe(d);
      case 'lunes_semana_anterior': return sumarDias(lunesDe(d), -7);
      case 'domingo_semana_anterior': return sumarDias(lunesDe(d), -1);
      case 'inicio_anio': return new Date(y, 0, 1);
      default: return d;                // hoy, fecha (Repetir por días: hoy si no se repite)
    }
  }
  const fechaDe = (a, hoy) => (a.modo === 'fija' ? deIso(a.fecha) : (a.modo === 'relativa' ? fechaRelativa(a.que, a.n, hoy) : null));
  function palabrasFecha(a) {
    if (a.modo === 'fija') return 'fecha fija';
    if (a.modo !== 'relativa') return '';
    if (a.que !== 'dias') return PALABRAS_FECHA[a.que] || a.que;
    const n = parseInt(a.n, 10) || 0;
    if (n === 0) return 'hoy';
    return n < 0 ? 'hace ' + (-n) + (n === -1 ? ' día' : ' días') : 'dentro de ' + n + (n === 1 ? ' día' : ' días');
  }
  // «ayer · 28/10/2026» (lo mismo que plantillas.describir_fecha)
  function describirFecha(texto, hoy) {
    const a = analizarFecha(texto);
    if (a.modo === 'vacia') return '';
    if (a.modo === 'mano') return String(texto);
    const d = fechaDe(a, hoy);
    const vista = a.modo === 'fija' ? String(texto).trim() : (d ? strfFecha(d, a.formato || FORMATO_DEFECTO) : null);
    return vista === null ? String(texto) : palabrasFecha(a) + ' · ' + vista;
  }
  const fechaEnPalabras = (d) => DIAS_SEMANA[(d.getDay() + 6) % 7][1] + ' ' + d.getDate() + ' de ' + MESES[d.getMonth()] + ' de ' + d.getFullYear();

  // El calendario abierto (uno a la vez).  Va en <body> (fuera de las ventanas, que recortan lo que sobresale) y se
  // coloca junto a su botón; se cierra con Esc, al pulsar fuera, al cerrar la ventana o al cambiar de sección.
  let POP_FECHA = null;
  function cerrarPopFecha(devolverFoco) {
    const p = POP_FECHA;
    if (!p) return;
    POP_FECHA = null;
    p.el.remove();
    p.btn.setAttribute('aria-expanded', 'false');
    if (devolverFoco && p.btn.isConnected) { try { p.btn.focus({ preventScroll: true }); } catch (e) { /* nada */ } }
  }
  function colocarPopFecha() {
    const p = POP_FECHA;
    if (!p) return;
    if (!p.btn.isConnected) { cerrarPopFecha(false); return; }
    const r = p.btn.getBoundingClientRect();
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const vh = window.innerHeight;
    const ancho = Math.min(340, vw - 16);
    p.el.style.width = ancho + 'px';
    const alto = p.el.offsetHeight;
    const izq = Math.min(Math.max(8, r.left), vw - ancho - 8);
    let arriba = r.bottom + 6;
    if (arriba + alto > vh - 8) arriba = r.top - alto - 6;
    if (arriba < 8) arriba = Math.max(8, vh - alto - 8);
    p.el.style.left = Math.round(izq) + 'px';
    p.el.style.top = Math.round(arriba) + 'px';
  }
  let oyentesPopFecha = false;
  function instalarOyentesPopFecha() {
    if (oyentesPopFecha) return;
    oyentesPopFecha = true;
    document.addEventListener('pointerdown', (ev) => {
      const p = POP_FECHA;
      if (p && (!p.btn.isConnected || (!p.el.contains(ev.target) && !p.btn.contains(ev.target)))) cerrarPopFecha(false);
    }, true);
    window.addEventListener('resize', colocarPopFecha);
    document.addEventListener('scroll', (ev) => { if (POP_FECHA && !POP_FECHA.el.contains(ev.target)) colocarPopFecha(); }, true);
    window.addEventListener('hashchange', () => cerrarPopFecha(false));
  }

  // campoFecha(inp, opc): el campo `inp` (el texto que se guarda) queda detrás de un botón que dice la fecha en palabras
  // («ayer · 28/10/2026») y abre el calendario: «Fecha fija» (un día) o «Cambia sola» (Hoy, Ayer, Hace N días, Lunes de
  // esta semana, Inicio del mes…: se recalcula en cada ejecución), con el formato elegido por ejemplos («28/10/2026»,
  // «2026-10-28»…) y «Se escribirá: …».  «Escribir a mano» enseña el campo (plantillas avanzadas).  Como campoRuta: al
  // cambiar se lanzan «input» y «change» del campo, así que quien lo escuchaba se entera igual.
  // opc: { iso: solo fecha fija AAAA-MM-DD (Repetir por días, inicio/fin de un horario); sinFormato: el formato no
  //        importa (correo); formato: el de la web para fechas nuevas; conFecha: ofrecer «El día que se descarga»
  //        ({fecha}, Repetir por días); vacio: texto cuando está vacío (y botón «Quitar la fecha»); prefijo: «Se
  //        escribirá: » (o lo que se diga delante de la vista previa); titulo }
  // Devuelve la caja (div.campo-fecha); `caja.campoFecha` = { abrir, cerrar, poner, pintar } (pruebas).
  function campoFecha(inp, opc) {
    opc = opc || {};
    instalarOyentesPopFecha();
    const iso = !!opc.iso;
    const etiqueta = opc.titulo || inp.getAttribute('aria-label') || 'Fecha';
    const prefijo = opc.prefijo === undefined ? 'Se escribirá: ' : opc.prefijo;
    const btn = h('button', { type: 'button', class: 'fecha-boton', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'data-campo-fecha': '1' });
    const mano = h('button', { type: 'button', class: 'boton chico enlace', 'data-fecha-mano': '1' });
    const vista = h('div', { class: 'ayuda fecha-vista', 'data-fecha-vista': '1' });
    inp.classList.add('fecha-texto');
    const caja = h('div', { class: 'campo-fecha', 'data-fecha': iso ? 'iso' : 'plantilla' }, h('div', { class: 'fecha-linea' }, btn, iso ? null : mano), inp, vista);
    let aMano = false;
    let pedida = 0, temporizador = null;
    const poner = (v) => {
      inp.value = v;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
    };
    function pintar() {
      const a = analizarFecha(inp.value);
      if (a.modo === 'mano') aMano = true;
      inp.classList.toggle('oculto', !aMano || iso);
      mano.replaceChildren(aMano ? 'Usar el calendario' : 'Escribir a mano');
      const d = fechaDe(a);
      let principal, secundario = '';
      if (a.modo === 'vacia') principal = opc.vacio || 'Elegir fecha';
      else if (a.modo === 'mano') principal = 'Escrita a mano';
      else if (iso) { principal = d ? fechaEnPalabras(d) : inp.value; }
      else { principal = palabrasFecha(a); secundario = a.modo === 'fija' ? inp.value.trim() : (d ? strfFecha(d, a.formato || FORMATO_DEFECTO) || '' : ''); }
      btn.replaceChildren(...[ico('calendario'), h('span', { class: 'fecha-palabras' + (a.modo === 'vacia' ? ' vacia' : '') }, principal),
        secundario ? h('span', { class: 'fecha-sep', 'aria-hidden': 'true' }, '·') : null, secundario ? h('span', { class: 'fecha-valor' }, secundario) : null].filter(Boolean));
      btn.setAttribute('aria-label', etiqueta + ': ' + (secundario ? principal + ', ' + secundario : principal) + '. Cambiar la fecha');
      btn.title = a.modo === 'relativa' ? 'Cambia sola: se calcula cada vez que se ejecuta (' + inp.value + ')' : 'Elegir la fecha';
      // vista previa («Se escribirá: …»): con el bot si es una plantilla a mano o un formato raro
      clearTimeout(temporizador);
      const n = ++pedida;
      if (iso || a.modo === 'vacia' || (a.modo === 'fija' && !aMano)) { vista.textContent = ''; return; }
      const local = a.modo === 'relativa' && d ? strfFecha(d, a.formato || FORMATO_DEFECTO) : null;
      if (local !== null && !aMano) { vista.textContent = prefijo + local + (opc.prefijo === undefined ? ' (hoy; se recalcula en cada ejecución)' : ' (se recalcula cada vez)'); return; }
      temporizador = setTimeout(async () => {
        try {
          const r = await api('POST', 'plantilla', { texto: inp.value });
          if (n === pedida) vista.textContent = r.error ? '⚠ ' + r.error : prefijo + r.vista;
        } catch (e) { if (n === pedida) vista.textContent = ''; }
      }, 250);
    }
    inp.addEventListener('input', pintar);
    mano.addEventListener('click', () => {
      if (aMano && analizarFecha(inp.value).modo === 'mano') { abrir(); return; }
      aMano = !aMano;
      pintar();
      if (aMano) inp.focus();
    });
    btn.addEventListener('click', () => { if (POP_FECHA && POP_FECHA.btn === btn) cerrarPopFecha(true); else abrir(); });
    btn.addEventListener('keydown', (ev) => { if (ev.key === 'ArrowDown' && ev.altKey) { ev.preventDefault(); abrir(); } });

    function abrir() {
      cerrarPopFecha(false);
      const a0 = analizarFecha(inp.value);
      const hoy = soloDia(new Date());
      const formatoInicial = a0.modo === 'fija' || a0.modo === 'relativa' ? a0.formato : (iso ? '%Y-%m-%d' : (opc.formato || null));
      const st = {
        modo: iso || opc.soloFija ? 'fija' : (a0.modo === 'relativa' ? 'relativa' : (a0.modo === 'fija' ? 'fija' : (opc.modoInicial || 'relativa'))),
        fecha: a0.modo === 'fija' ? a0.fecha : null,
        que: a0.modo === 'relativa' ? a0.que : null,
        n: a0.modo === 'relativa' && a0.que === 'dias' ? a0.n : -7,
        formato: iso ? '%Y-%m-%d' : formatoInicial,
        implicito: !iso && !formatoInicial,              // {ayer} sin formato = el de siempre (dd/mm/aaaa)
      };
      const elegida = st.fecha ? deIso(st.fecha) : (a0.modo === 'relativa' ? fechaRelativa(a0.que, a0.n, hoy) : null);
      st.mes = new Date((elegida || hoy).getFullYear(), (elegida || hoy).getMonth(), 1);
      st.foco = elegida && elegida.getMonth() === st.mes.getMonth() ? elegida : (hoy.getMonth() === st.mes.getMonth() && hoy.getFullYear() === st.mes.getFullYear() ? hoy : st.mes);
      const el = h('div', { class: 'fecha-pop', role: 'dialog', 'aria-modal': 'false', 'aria-label': etiqueta, 'data-fecha-pop': '1' });
      const fmtActual = () => st.formato || FORMATO_DEFECTO;

      function aplicar() {
        let a;
        if (st.modo === 'fija') { if (!st.fecha) return; a = { modo: 'fija', fecha: st.fecha, formato: st.formato }; }
        else { if (!st.que) return; a = { modo: 'relativa', que: st.que, n: st.que === 'dias' ? st.n : null, formato: st.formato }; }
        const texto = componerFecha(a);
        if (texto === null) { errorPop.textContent = 'Ese formato no se puede usar con una fecha fija: elige otro.'; return; }
        errorPop.textContent = '';
        aMano = false;
        if (texto !== inp.value) poner(texto); else pintar();
        pintarVistaPop();
      }
      // --- modos
      const bModo = (m, t) => h('button', { type: 'button', class: 'fecha-modo', 'data-fecha-modo': m, 'aria-pressed': st.modo === m ? 'true' : 'false',
        onclick: () => { st.modo = m; pintarCuerpo(); aplicar(); enfocarCuerpo(); } }, t);
      const modos = iso || opc.soloFija ? null : h('div', { class: 'fecha-modos', role: 'group', 'aria-label': 'Tipo de fecha' },
        bModo('fija', 'Fecha fija'), bModo('relativa', 'Cambia sola'));
      const cuerpo = h('div', { class: 'fecha-cuerpo' });
      const errorPop = h('div', { class: 'fecha-error', role: 'alert' });
      const vistaPop = h('div', { class: 'fecha-se-escribira', 'data-fecha-se-escribira': '1', 'aria-live': 'polite' });
      // --- calendario
      function pintarCalendario() {
        const y = st.mes.getFullYear(), mes = st.mes.getMonth();
        const tit = h('div', { class: 'cal-titulo', id: 'cal-titulo-' + y + mes, 'aria-live': 'polite' }, MESES[mes] + ' ' + y);
        const cambiarMes = (dm) => {
          const dia = st.foco.getDate();
          st.mes = new Date(y, mes + dm, 1);
          st.foco = new Date(st.mes.getFullYear(), st.mes.getMonth(), Math.min(dia, new Date(st.mes.getFullYear(), st.mes.getMonth() + 1, 0).getDate()));
          pintarCuerpo();
        };
        const cab = h('div', { class: 'cal-cab' },
          h('button', { type: 'button', class: 'boton chico solo-icono', 'aria-label': 'Mes anterior', 'data-cal-anterior': '1', onclick: () => cambiarMes(-1) }, ico('atras')),
          tit,
          h('button', { type: 'button', class: 'boton chico solo-icono cal-sig', 'aria-label': 'Mes siguiente', 'data-cal-siguiente': '1', onclick: () => cambiarMes(1) }, ico('atras')));
        const tabla = h('table', { class: 'cal-rejilla', role: 'grid', 'aria-labelledby': tit.id });
        tabla.appendChild(h('thead', null, h('tr', null, DIAS_SEMANA.map(([l, n]) => h('th', { scope: 'col', abbr: n, title: n }, l)))));
        const tb = h('tbody');
        const primero = new Date(y, mes, 1);
        let d = sumarDias(primero, -((primero.getDay() + 6) % 7));
        const hoyIso = isoDia(hoy);
        for (let semana = 0; semana < 6; semana++) {
          if (semana > 0 && d.getMonth() !== mes) break;
          const tr = h('tr');
          for (let k = 0; k < 7; k++) {
            const dia = d;
            if (dia.getMonth() !== mes) tr.appendChild(h('td', { class: 'fuera' }));
            else {
              const iso_ = isoDia(dia);
              const elegido = st.modo === 'fija' && st.fecha === iso_;
              const b = h('button', { type: 'button', class: 'cal-dia' + (iso_ === hoyIso ? ' hoy' : '') + (elegido ? ' elegido' : ''),
                'data-dia': iso_, tabindex: isoDia(st.foco) === iso_ ? '0' : '-1', 'aria-selected': elegido ? 'true' : 'false',
                'aria-label': fechaEnPalabras(dia) + (iso_ === hoyIso ? ' (hoy)' : ''),
                onclick: () => {
                  st.fecha = iso_; st.foco = dia; aplicar();
                  if (iso || opc.soloFija || opc.sinFormato) cerrarPopFecha(true); else pintarCuerpo(true);
                } }, String(dia.getDate()));
              tr.appendChild(h('td', { role: 'gridcell' }, b));
            }
            d = sumarDias(d, 1);
          }
          tb.appendChild(tr);
        }
        tabla.appendChild(tb);
        tabla.addEventListener('keydown', (ev) => {
          const pasos = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
          let nuevo = null;
          if (pasos[ev.key] !== undefined) nuevo = sumarDias(st.foco, pasos[ev.key]);
          else if (ev.key === 'Home') nuevo = lunesDe(st.foco);
          else if (ev.key === 'End') nuevo = sumarDias(lunesDe(st.foco), 6);
          else if (ev.key === 'PageUp' || ev.key === 'PageDown') {
            const dm = ev.key === 'PageUp' ? -1 : 1;
            const ult = new Date(st.foco.getFullYear(), st.foco.getMonth() + dm + 1, 0).getDate();
            nuevo = new Date(st.foco.getFullYear(), st.foco.getMonth() + dm, Math.min(st.foco.getDate(), ult));
          }
          if (!nuevo) return;
          ev.preventDefault();
          st.foco = nuevo;
          if (nuevo.getMonth() !== st.mes.getMonth() || nuevo.getFullYear() !== st.mes.getFullYear()) {
            st.mes = new Date(nuevo.getFullYear(), nuevo.getMonth(), 1);
            pintarCuerpo(true);
          } else {
            tabla.querySelectorAll('.cal-dia').forEach((x) => x.setAttribute('tabindex', x.dataset.dia === isoDia(nuevo) ? '0' : '-1'));
            const b = tabla.querySelector('.cal-dia[data-dia="' + isoDia(nuevo) + '"]');
            if (b) b.focus();
          }
        });
        const irHoy = h('button', { type: 'button', class: 'boton chico enlace', 'data-cal-hoy': '1', onclick: () => {
          st.mes = new Date(hoy.getFullYear(), hoy.getMonth(), 1); st.foco = hoy; pintarCuerpo(true);
        } }, 'Ir a hoy');
        return [cab, tabla, h('div', { class: 'fila cal-pie' }, irHoy, h('span', { class: 'sub' },
          st.fecha ? 'Elegida: ' + fechaEnPalabras(deIso(st.fecha)) : 'Elige un día'))];
      }
      // --- fechas que cambian solas
      function pintarRelativas() {
        const n = h('input', { type: 'number', min: '0', max: '3660', value: String(Math.abs(st.n === null || st.n === undefined ? 7 : st.n)),
          class: 'corto fecha-n', 'aria-label': 'Número de días', 'data-fecha-n': '1' });
        const futuro = (st.n || 0) > 0;
        const ponerN = () => { const v = Math.max(0, parseInt(n.value, 10) || 0); st.n = futuro ? v : -v; st.que = 'dias'; aplicar(); marcar(); };
        n.addEventListener('input', ponerN);
        n.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); ponerN(); } });
        const chips = h('div', { class: 'fecha-chips', role: 'group', 'aria-label': 'Fechas que cambian solas' });
        const botones = [];
        for (const [k, t] of RELATIVAS) {
          if (k === 'fecha' && !opc.conFecha && st.que !== 'fecha') continue;
          if (k === 'dias') {
            const b = h('button', { type: 'button', class: 'dia-chip ancho', 'data-fecha-rel': 'dias', onclick: () => { ponerN(); } }, futuro ? 'Dentro de' : 'Hace');
            botones.push(b);
            chips.appendChild(h('span', { class: 'fecha-chip-n' }, b, n, h('span', { class: 'sub' }, 'días')));
            continue;
          }
          const b = h('button', { type: 'button', class: 'dia-chip ancho', 'data-fecha-rel': k, onclick: () => { st.que = k; aplicar(); marcar(); } }, t);
          botones.push(b);
          chips.appendChild(b);
        }
        function marcar() {
          botones.forEach((b) => {
            const si = b.dataset.fechaRel === st.que;
            b.classList.toggle('activo', si);
            b.setAttribute('aria-pressed', si ? 'true' : 'false');
          });
        }
        marcar();
        return [chips, h('p', { class: 'sub' }, 'Se calcula cada vez que se ejecuta (hoy es ' + fechaEnPalabras(hoy) + ').')];
      }
      function pintarCuerpo(enfocarDia) {
        if (modos) modos.querySelectorAll('.fecha-modo').forEach((b) => b.setAttribute('aria-pressed', b.dataset.fechaModo === st.modo ? 'true' : 'false'));
        cuerpo.replaceChildren(...(st.modo === 'fija' ? pintarCalendario() : pintarRelativas()));
        pintarVistaPop();
        colocarPopFecha();
        if (enfocarDia) { const b = cuerpo.querySelector('.cal-dia[tabindex="0"]'); if (b) b.focus(); }
      }
      function enfocarCuerpo() {
        const b = cuerpo.querySelector('.cal-dia[tabindex="0"], .dia-chip.activo, .dia-chip');
        if (b) b.focus();
      }
      // --- formato
      let formatoCaja = null;
      if (!iso && !opc.sinFormato) {
        const muestra = fechaDe({ modo: st.modo, fecha: st.fecha, que: st.que || 'hoy', n: st.n }, hoy) || hoy;
        const sel = h('select', { 'aria-label': 'Formato de la fecha', 'data-fecha-formato': '1' },
          FORMATOS_FECHA.map(([f, nota]) => h('option', { value: f }, strfFecha(muestra, f) + (nota ? '  (' + nota + ')' : ''))),
          h('option', { value: '__otro' }, 'Otro…'));
        const otro = h('input', { type: 'text', class: 'oculto', value: '', placeholder: 'p. ej. %d/%m/%Y', 'aria-label': 'Otro formato (códigos de fecha)', 'data-fecha-formato-otro': '1' });
        const conocido = FORMATOS_FECHA.some(([f]) => f === fmtActual());
        sel.value = conocido ? fmtActual() : '__otro';
        if (!conocido) { otro.value = fmtActual(); otro.classList.remove('oculto'); }
        sel.addEventListener('change', () => {
          if (sel.value === '__otro') { otro.classList.remove('oculto'); if (!otro.value) otro.value = fmtActual(); otro.focus(); colocarPopFecha(); return; }
          otro.classList.add('oculto');
          st.formato = sel.value === FORMATO_DEFECTO && st.implicito ? null : sel.value;
          aplicar();
        });
        otro.addEventListener('input', () => {
          const f = otro.value.trim();
          if (!formatoValido(f)) { errorPop.textContent = 'Formato no válido: usa códigos como %d (día), %m (mes), %Y (año).'; return; }
          st.formato = f; st.implicito = false; aplicar();
        });
        formatoCaja = h('div', { class: 'fecha-formato' }, h('label', { class: 'sub' }, 'Formato (como lo escribe la web)'), sel, otro);
      }
      function pintarVistaPop() {
        const a = analizarFecha(inp.value);
        const d = fechaDe(a, hoy);
        if (a.modo === 'vacia' || (st.modo === 'fija' && !st.fecha) || (st.modo === 'relativa' && !st.que)) {
          vistaPop.replaceChildren(h('span', { class: 'sub' }, st.modo === 'fija' ? 'Elige un día en el calendario.' : 'Elige una de las fechas de arriba.'));
          return;
        }
        if (iso) { vistaPop.replaceChildren(h('span', { class: 'sub' }, 'Elegida: '), h('strong', null, d ? fechaEnPalabras(d) : inp.value)); return; }
        const local = a.modo === 'fija' ? inp.value.trim() : (d ? strfFecha(d, a.formato || FORMATO_DEFECTO) : null);
        vistaPop.replaceChildren(h('span', { class: 'sub' }, prefijo), h('strong', { class: 'fecha-valor' }, local === null ? inp.value : local),
          h('span', { class: 'sub' }, a.modo === 'relativa' ? ' (hoy)' : ''));
      }
      const pie = h('div', { class: 'fecha-pie' },
        opc.vacio ? h('button', { type: 'button', class: 'boton chico', 'data-fecha-quitar': '1', onclick: () => { st.fecha = null; st.que = null; poner(''); cerrarPopFecha(true); } }, 'Quitar la fecha') : null,
        iso ? null : h('button', { type: 'button', class: 'boton chico enlace', onclick: () => { cerrarPopFecha(false); aMano = true; pintar(); inp.focus(); } }, 'Escribir a mano'),
        h('span', { class: 'espacio' }),
        h('button', { type: 'button', class: 'boton chico primario', 'data-fecha-listo': '1', onclick: () => cerrarPopFecha(true) }, 'Listo'));
      el.append(...[modos, cuerpo, formatoCaja, errorPop, vistaPop, pie].filter(Boolean));
      el.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); cerrarPopFecha(true); return; }
        if (ev.key === 'Enter' && ev.target.tagName === 'INPUT') { ev.preventDefault(); ev.stopPropagation(); }
        if (ev.key === 'Tab') {                                    // el foco no sale del calendario
          const foc = [...el.querySelectorAll('button, input, select, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.disabled && x.offsetParent !== null && x.getAttribute('tabindex') !== '-1');
          if (!foc.length) return;
          const pri = foc[0], ult = foc[foc.length - 1];
          if (ev.shiftKey && document.activeElement === pri) { ev.preventDefault(); ult.focus(); }
          else if (!ev.shiftKey && document.activeElement === ult) { ev.preventDefault(); pri.focus(); }
        }
      });
      document.body.appendChild(el);
      POP_FECHA = { el, btn };
      btn.setAttribute('aria-expanded', 'true');
      pintarCuerpo();
      enfocarCuerpo();
    }
    pintar();
    caja.campoFecha = { abrir, cerrar: () => cerrarPopFecha(false), poner, pintar };
    return caja;
  }

  // ------------------------------------------------------------------ preguntas del bot
  async function mostrarPreguntas() {
    let r;
    try { r = await api('GET', 'preguntas'); } catch (e) { return; }
    const p = (r.preguntas || [])[0];
    if (!p || E.preguntaAbierta === p.id) return;
    modalPregunta(p);
  }

  function modalPregunta(p) {
    const s = p.solicitud || {};
    const fallida = p.tipo === 'clave_fallida';
    const host = s.host || 'la página';
    const valores = {};
    const filas = [];
    let primeraClave = null;
    for (const c of s.campos || []) {
      if (Object.prototype.hasOwnProperty.call(valores, c.clave)) continue;   // (una caja por campo: si no, se perdería lo escrito)
      let control;
      if (c.tipo === 'clave') {
        const cc = campoClave(c.valor, c.etiqueta);
        control = cc.caja; valores[c.clave] = cc.inp;
        if (!primeraClave) primeraClave = cc.inp;
      } else {
        const inp = h('input', { type: 'text', value: c.valor || '', 'aria-label': c.etiqueta || c.clave });
        control = inp; valores[c.clave] = inp;
      }
      const et = (fallida && c.tipo === 'clave') ? 'Nueva contraseña' : (c.etiqueta || c.clave);
      filas.push(h('label', null, et + (c.requerido === false ? ' (opcional)' : '')), control);
    }
    const recordar = h('input', { type: 'checkbox', checked: true, id: 'preg-recordar' });
    const responder = async (resp) => {
      try { await api('POST', 'preguntas/' + p.id, { respuesta: resp }); } catch (e) { errorToast(e); }
      cerrarModal();
    };
    const enviar = () => {
      const v = {};
      for (const [k, inp] of Object.entries(valores)) v[k] = inp.value;
      // v3.3.1: no se envía una contraseña (u otro dato obligatorio) vacía: el bot no podría entrar
      const vacio = (s.campos || []).find((c) => c.requerido !== false && !(v[c.clave] || '').trim() && (c.tipo === 'clave' || fallida || s.obligatorio));
      if (vacio) { toast('Escribe ' + (vacio.tipo === 'clave' ? (fallida ? 'la contraseña nueva' : 'la contraseña') : '«' + (vacio.etiqueta || vacio.clave) + '»'), 'aviso'); valores[vacio.clave].focus(); return; }
      responder({ valores: v, recordar: fallida ? true : recordar.checked });
    };
    let contenido;
    if (fallida) {
      contenido = h('div', null,
        h('div', { class: 'alerta error' }, 'La página «' + host + '» rechazó la contraseña guardada' +
          (s.usuario ? ' del usuario «' + s.usuario + '»' : '') + '. Lo más probable es que la contraseña se cambiara en la web.'),
        s.error_pagina ? h('p', { class: 'ayuda' }, 'La página dice: «' + s.error_pagina + '»') : null,
        h('p', { class: 'ayuda' }, s.mensaje || ''),
        h('p', { class: 'ayuda' }, 'Escribe la contraseña nueva: se guardará en el Administrador de credenciales de Windows ' +
          '(nunca en un archivo) y el bot volverá a intentarlo. El bot nunca vuelve a enviar una contraseña que la página ya rechazó.'),
        h('div', { class: 'formulario' }, h('label', null, 'Sitio'), h('input', { type: 'text', value: host, readonly: true }), filas));
    } else {
      contenido = h('div', null,
        h('p', { class: s.rechazada ? 'alerta error' : (s.obligatorio ? 'alerta' : 'ayuda') }, s.mensaje || ''),
        s.error_pagina ? h('p', { class: 'ayuda' }, 'La página dice: «' + s.error_pagina + '»') : null,
        h('div', { class: 'formulario' }, filas),
        h('p', null, h('label', { class: 'interruptor', for: 'preg-recordar' }, recordar,
          'Recordar (las contraseñas van al Administrador de credenciales de Windows; el resto a Accesos)')));
    }
    abrirModal({ titulo: fallida ? 'La contraseña de «' + host + '» falló' : 'La página «' + host + '» pide iniciar sesión',
      contenido, alEnter: enviar, alEscape: () => responder(null),
      botones: [{ texto: 'Cancelar', accion: () => responder(null) },
                { texto: fallida ? 'Guardar y reintentar' : 'Aceptar', clase: 'primario', accion: enviar }] });
    E.preguntaAbierta = p.id;
    if (fallida && primeraClave) setTimeout(() => primeraClave.focus(), 40);
  }

  // Cambiar la contraseña de un sitio (Accesos o el aviso «La contraseña de … cambió»)
  function modalClave(host, datos) {
    datos = datos || {};
    const cc = campoClave('', 'Nueva contraseña');
    const usuario = h('input', { type: 'text', value: datos.usuario || '', 'aria-label': 'Usuario' });
    const guardar = async (reintentar) => {
      if (!cc.inp.value) { toast('Escribe la contraseña nueva', 'aviso'); return; }
      try {
        await api('POST', 'accesos/' + encodeURIComponent(host) + '/clave',
          { contrasena: cc.inp.value, usuario: usuario.value, clave: datos.clave || null });
        cc.inp.value = '';
        cerrarModal();
        toast('Contraseña de «' + host + '» guardada', 'ok');
        if (reintentar && datos.reporte_id) {
          await ejecutarReportes([datos.reporte_id], datos.reporte || 'el reporte');
        }
        refrescarCampana();
        refrescarVista('accesos');
      } catch (e) { errorToast(e); }
    };
    const rechazada = datos.rechazada;
    abrirModal({ titulo: rechazada ? 'La contraseña de «' + host + '» falló' : 'Cambiar la contraseña de «' + host + '»',
      contenido: h('div', null,
        rechazada ? h('div', { class: 'alerta error' }, 'La página rechazó la contraseña guardada' +
          (datos.usuario ? ' del usuario «' + datos.usuario + '»' : '') + '. Escribe la nueva para seguir descargando los reportes.') : null,
        h('div', { class: 'formulario' }, h('label', null, 'Sitio'), h('input', { type: 'text', value: host, readonly: true }),
          h('label', null, 'Usuario'), usuario, h('label', null, 'Nueva contraseña'), cc.caja),
        h('p', { class: 'ayuda' }, 'Se guarda en el Administrador de credenciales de Windows, nunca en un archivo.')),
      alEnter: () => guardar(!!datos.reporte_id),
      botones: [{ texto: 'Cancelar', accion: cerrarModal },
                datos.reporte_id ? { texto: 'Guardar y reintentar', clase: 'primario', accion: () => guardar(true) }
                                 : { texto: 'Guardar', clase: 'primario', accion: () => guardar(false) }] });
  }

  // ------------------------------------------------------------------ notificaciones
  async function refrescarCampana() {
    try {
      const r = await api('GET', 'notificaciones?limite=1');
      const c = $('#contador');
      c.textContent = r.no_leidas;
      c.classList.toggle('oculto', !r.no_leidas);
      $('#campana').setAttribute('aria-label', r.no_leidas ? 'Notificaciones (' + r.no_leidas + ' sin leer)' : 'Notificaciones');
    } catch (e) { /* sin conexión */ }
  }
  // v3.5: punto rojo en el icono de Vigilancia del riel cuando hay cortes nuevos sin descargar
  function marcarNovedades(n) {
    E.novedades = n || 0;
    const a = $('#menu a[data-ruta="vigilancia"]');
    if (!a) return;
    let p = a.querySelector('.marca-punto');
    if (E.novedades && !p) { p = h('span', { class: 'marca-punto' }); a.appendChild(p); }
    if (!E.novedades && p) p.remove();
    a.setAttribute('aria-label', E.novedades ? 'Vigilancia (' + E.novedades + ' novedades)' : 'Vigilancia');
  }
  async function abrirNotificacion(n) {
    try { await api('POST', 'notificaciones/' + n.id, { leida: true }); } catch (e) { /* nada */ }
    refrescarCampana();
    const d = n.datos || {};
    if (n.tipo === 'clave_rechazada') {
      modalClave(d.host, { usuario: d.usuario, reporte_id: d.reporte_id, reporte: d.reporte, rechazada: true });
      return;
    }
    if (n.tipo === 'vigilancia' && d.pagina_id) {           // v3.2: novedad en un filtro de una Página
      abrirModal({ titulo: n.titulo, contenido: h('div', null, h('p', null, n.texto), h('p', { class: 'ayuda' }, n.cuando)),
        botones: [{ texto: 'Cerrar', accion: cerrarModal }, { texto: 'Abrir la página', accion: () => { cerrarModal(); location.hash = '#/paginas/' + d.pagina_id; } },
                  { texto: 'Descargar', clase: 'primario', accion: async () => {
                    cerrarModal();
                    try { await api('POST', d.vigilancia_id ? 'vigilancias/' + d.vigilancia_id + '/descargar' : 'paginas/' + d.pagina_id + '/vigilancia/descargar', { texto: d.opcion }); toast('Descargando «' + d.opcion + '»…'); }
                    catch (e) { errorToast(e); }
                  } }] });
      return;
    }
    if (n.tipo === 'pagina' && d.pagina_id) { location.hash = '#/paginas/' + d.pagina_id; return; }
    if (n.tipo === 'correo' || n.tipo === 'correo_sesion' || n.tipo === 'correo_error') {      // v3.4: correo
      abrirModal({ titulo: n.titulo, ancho: (d.archivos || []).length > 0, contenido: h('div', null, h('p', null, n.texto), h('p', { class: 'ayuda' }, n.cuando),
        (d.archivos || []).length ? h('ul', { class: 'lista' }, d.archivos.map(filaArchivo)) : null),
        botones: [{ texto: 'Cerrar', accion: cerrarModal }, { texto: 'Ir a Correo', clase: 'primario', accion: () => { cerrarModal(); location.hash = '#/correo'; } }] });
      return;
    }
    if (n.tipo === 'vigilancia' && d.reporte_id) {
      abrirModal({ titulo: n.titulo, contenido: h('div', null, h('p', null, n.texto), h('p', { class: 'ayuda' }, n.cuando)),
        botones: [{ texto: 'Cerrar', accion: cerrarModal },
                  { texto: 'Descargar', clase: 'primario', accion: async () => {
                    cerrarModal();
                    try { await api('POST', d.vigilancia_id ? 'vigilancias/' + d.vigilancia_id + '/descargar' : 'vigilancia/' + d.reporte_id + '/descargar', { texto: d.opcion }); toast('Descargando «' + d.opcion + '»…'); }
                    catch (e) { errorToast(e); }
                  } }] });
      return;
    }
    abrirModal({ titulo: n.titulo, contenido: h('div', null, h('p', null, n.texto), h('p', { class: 'ayuda' }, n.cuando)),
      botones: [{ texto: 'Cerrar', clase: 'primario', accion: cerrarModal }] });
  }
  function listaNotificaciones(lista) {
    if (!lista.length) return h('p', { class: 'vacio' }, 'No hay notificaciones.');
    return h('ul', { class: 'lista' }, lista.map((n) => h('li', { class: 'clic', tabindex: '0', role: 'button',
      onclick: () => abrirNotificacion(n), onkeydown: (ev) => { if (ev.key === 'Enter') abrirNotificacion(n); } },
      h('span', { class: 'punto ' + (n.leida ? '' : (n.tipo === 'clave_rechazada' ? 'error' : 'aviso')) }),
      h('div', { class: 'crece' }, h('div', null, n.titulo), h('div', { class: 'sub' }, n.cuando + (n.texto ? ' — ' + n.texto : ''))),
      n.leida ? null : chip('nueva', 'marca'))));
  }
  async function panelNotificaciones() {
    let r;
    try { r = await api('GET', 'notificaciones?limite=50'); } catch (e) { errorToast(e); return; }
    abrirModal({ titulo: 'Notificaciones', ancho: true, contenido: listaNotificaciones(r.notificaciones || []),
      botones: [{ texto: 'Marcar todas como leídas', accion: async () => { await api('POST', 'notificaciones', {}); cerrarModal(); refrescarCampana(); } },
                { texto: 'Cerrar', clase: 'primario', accion: cerrarModal }] });
  }

  // ------------------------------------------------------------------ v3.5: lo que está en curso (por reporte)
  // E.curso: reporte_id → {trabajo, pct, texto, optimista}.  Lo pone el clic en «Ejecutar» (al instante, sin esperar al
  // servidor) y lo corrigen los eventos; las vistas pintan esa fila como «en curso» con su barrita cian.
  function cursoPoner(rid, datos) {
    if (rid === null || rid === undefined) return;
    E.curso.set(rid, Object.assign({ pct: 2, texto: '' }, E.curso.get(rid) || {}, datos));
    avisarVistas({ tipo: '_curso', reporte_id: rid });
  }
  function cursoQuitar(rid, estado) {
    if (!E.curso.has(rid)) return;
    E.curso.delete(rid);
    if (estado) E.recien.set(rid, { estado, t: Date.now() });
    avisarVistas({ tipo: '_curso', reporte_id: rid, fin: estado });
  }
  // Ejecutar uno o varios reportes guardados (Inicio, Reportes, paleta): la fila pasa a «en curso» al instante.
  async function ejecutarReportes(ids, nombre, ver) {
    ids.forEach((id, k) => cursoPoner(id, { trabajo: null, pct: 2, texto: k ? 'En cola…' : 'Abriendo la página…', optimista: true }));
    try {
      const t = await api('POST', 'ejecutar', ver === undefined ? { ids } : { ids, ver });
      toast(ids.length === 1 ? 'Ejecutando «' + nombre + '». Puedes seguir trabajando.' : 'Ejecutando ' + ids.length + ' reportes…');
      return t;
    } catch (e) {
      ids.forEach((id) => { const x = E.curso.get(id); if (x && x.optimista && !x.trabajo) { E.curso.delete(id); avisarVistas({ tipo: '_curso', reporte_id: id }); } });
      errorToast(e);
      return null;
    }
  }

  // ------------------------------------------------------------------ eventos
  function pintarTrabajo() {
    const t = E.trabajo;
    const caja = $('#trabajo');
    if (!t || t.estado !== 'en_curso') { caja.classList.add('oculto'); return; }
    caja.classList.remove('oculto');
    const tit = $('#trabajo-titulo');
    if (!tit.firstChild || tit.textContent !== (t.descripcion || 'Trabajando…')) tit.replaceChildren(h('span', { class: 'punto curso' }), t.descripcion || 'Trabajando…');
    tit.title = t.descripcion || '';
    $('#trabajo-texto').textContent = t.texto || '';
    $('#trabajo-texto').title = t.texto || '';
    const pct = t.total && t.paso !== null && t.paso !== undefined && t.paso >= 0 ? Math.min(100, Math.round(100 * (t.paso + 1) / t.total)) : 8;
    $('#trabajo-barra').style.width = pct + '%';
    if (E.trenTrabajo) E.trenTrabajo.style.left = pct + '%';
  }
  function despachar(ev) {
    switch (ev.tipo) {
      case 'trabajo':
        E.trabajo = Object.assign(E.trabajo && E.trabajo.id === ev.trabajo ? E.trabajo : {},
          { id: ev.trabajo, estado: ev.estado, descripcion: ev.descripcion, tipo: ev.tipo_trabajo, texto: ev.estado === 'en_curso' ? 'Empezando…' : ev.resumen });
        if (ev.estado === 'en_curso' && !E.trabajo._t0) E.trabajo._t0 = Date.now();      // v3.7: «lleva 1:23»
        if (ev.estado === 'en_curso') {
          if (ev.reporte_id) { E.trabajoReporte[ev.trabajo] = ev.reporte_id; cursoPoner(ev.reporte_id, { trabajo: ev.trabajo, pct: 4, texto: 'Empezando…', optimista: false }); }
        } else {
          if (ev.resumen) toast(ev.resumen, ev.estado === 'ok' ? 'ok' : (ev.estado === 'detenido' ? 'aviso' : 'error'), 9000);
          refrescarCampana();
          // (v3.5: ya no se recarga la página: cada vista pone al día solo lo suyo; ver avisarVistas)
          for (const [rid, x] of [...E.curso]) {
            if (x.trabajo === ev.trabajo || rid === ev.reporte_id || (x.optimista && !x.trabajo)) cursoQuitar(rid, ev.estado);
          }
          delete E.trabajoReporte[ev.trabajo];
          delete E.loteReporte[ev.trabajo];
        }
        pintarTrabajo();
        break;
      case 'progreso': {
        if (E.trabajo) {
          E.trabajo.paso = ev.i;
          E.trabajo.texto = (ev.i >= 0 ? 'Paso ' + (ev.i + 1) + ': ' : '') + (ev.texto || '') + (ev.reporte ? ' — ' + ev.reporte : '');
          if (ev.total) E.trabajo.total = ev.total;
          pintarTrabajo();
        }
        const rid = E.loteReporte[ev.trabajo] || E.trabajoReporte[ev.trabajo];
        const x = rid && E.curso.get(rid);
        if (x) {
          if (ev.total && ev.i >= 0) x.pct = Math.max(x.pct || 0, Math.min(98, Math.round(100 * (ev.i + 1) / ev.total)));
          x.texto = (ev.i >= 0 ? 'Paso ' + (ev.i + 1) + (ev.total ? ' de ' + ev.total : '') + ': ' : '') + (ev.texto || '');
          avisarVistas({ tipo: '_progreso', reporte_id: rid });
        }
        break;
      }
      case 'lote':
        if (E.trabajo) { E.trabajo.texto = 'Reporte ' + ev.n + ' de ' + ev.total + ': «' + ev.nombre + '»'; E.trabajo.total = ev.total; E.trabajo.paso = ev.n - 1; pintarTrabajo(); }
        if (ev.reporte_id && ev.fase === 'inicio') { E.loteReporte[ev.trabajo] = ev.reporte_id; cursoPoner(ev.reporte_id, { trabajo: ev.trabajo, pct: 4, texto: 'Reporte ' + ev.n + ' de ' + ev.total, optimista: false }); }
        if (ev.reporte_id && ev.fase === 'fin') cursoQuitar(ev.reporte_id, ev.estado === 'ok' ? 'ok' : (ev.estado === 'detenido' ? 'detenido' : 'error'));
        break;
      case 'pregunta': mostrarPreguntas(); break;
      case 'pregunta_fin': if (E.preguntaAbierta === ev.id) cerrarModal(); break;
      case 'aviso':
        if (ev.aviso === 'clave_rechazada') toast('La contraseña de «' + ev.host + '» fue rechazada.', 'error', 9000);
        else if (ev.texto) toast(ev.texto, 'ok', 7000);
        refrescarCampana();
        break;
      case 'vigilancia':
        if (ev.nuevas && ev.nuevas.length) { toast('Novedad: ' + ev.nuevas.join(', '), 'aviso', 10000); marcarNovedades(E.novedades + ev.nuevas.length); }
        refrescarCampana();
        break;
      case 'acceso_probado': toast(ev.texto, ev.ok ? 'ok' : 'error', 9000); break;
      case 'correo': refrescarCampana(); break;          // v3.4: resultado de revisar una búsqueda de correo
      case 'externo': {                                  // v3.7: lo que ejecutan las tareas de Windows (con su progreso)
        const antes = new Map((E.externos || []).map((x) => [x.id, x]));
        E.externos = ev.lista || [];
        for (const x of E.externos) {
          const a = antes.get(x.id);
          if (x.terminado && (!a || !a.terminado)) { refrescarCampana(); ev.termino = true; }
        }
        if (antes.size && [...antes.keys()].some((k) => !E.externos.find((x) => x.id === k))) ev.termino = true;
        break;
      }
      default: break;
    }
    avisarVistas(ev);
    for (const f of E.oyentes) { try { f(ev); } catch (e) { console.error(e); } }
    if (E.oyenteModal) { try { E.oyenteModal(ev); } catch (e) { console.error(e); } }   // v3.1: panel «Usar filtros»
  }
  async function bucleEventos() {
    for (;;) {
      if (E.sinPermiso) return;
      try {
        const r = await api('GET', 'eventos?desde=' + E.ultimo + '&espera=20');
        for (const ev of r.eventos) { if (ev.seq > E.ultimo) { E.ultimo = ev.seq; despachar(ev); } }
        E.ultimo = Math.max(E.ultimo, r.ultimo);
      } catch (e) { if (E.sinPermiso) return; await dormir(2500); }
    }
  }

  // ================================================================== v3.5: vistas vivas y listas por clave
  // claveLista(contenedor, elementos, clave, pintar, opc): deja en `contenedor` un nodo por elemento (el de su clave),
  // en ese orden.  Un nodo solo se vuelve a pintar si sus datos cambiaron (opc.firma, por defecto JSON); los demás no
  // se tocan (ni su foco, ni lo que el usuario tenía abierto).  opc.vacio() = lo que se enseña si no hay ninguno;
  // opc.destello(elemento) = true para resaltar un instante la fila que cambió.
  function claveLista(cont, items, clave, pintar, opc) {
    opc = opc || {};
    const firma = opc.firma || ((x) => JSON.stringify(x));
    const previos = new Map();
    for (const n of [...cont.children]) {
      if (n.dataset && n.dataset.lk !== undefined) previos.set(n.dataset.lk, n); else n.remove();
    }
    const orden = [];
    for (const it of items) {
      const k = String(clave(it));
      const f = firma(it);
      let n = previos.get(k);
      if (n && n._firma === f) { previos.delete(k); orden.push(n); continue; }
      const nuevo = pintar(it);
      nuevo.dataset.lk = k;
      nuevo._firma = f;
      if (n) {
        pasarEstado(n, nuevo);
        n.replaceWith(nuevo);
        previos.delete(k);
        if (opc.destello && opc.destello(it)) destellar(nuevo);
      }
      orden.push(nuevo);
    }
    for (const n of previos.values()) n.remove();
    orden.forEach((n, i) => { if (cont.children[i] !== n) cont.insertBefore(n, cont.children[i] || null); });
    if (!items.length && opc.vacio) { const v = opc.vacio(); v.dataset.lk = '__vacio'; v._firma = '__vacio'; cont.appendChild(v); }
  }
  // Lo que el usuario tenía en un nodo que se vuelve a pintar: <details> abiertos, casillas y el foco.
  function pasarEstado(viejo, nuevo) {
    const dv = viejo.querySelectorAll('details');
    const dn = nuevo.querySelectorAll('details');
    dv.forEach((d, i) => { if (dn[i] && d.open) dn[i].open = true; });
    const act = document.activeElement;
    if (act && (act === viejo || viejo.contains(act))) {
      let destino = nuevo;
      if (act !== viejo) {
        const sel = act.tagName;
        const cand = [...viejo.querySelectorAll(sel)];
        const i = cand.indexOf(act);
        const otros = [...nuevo.querySelectorAll(sel)];
        destino = otros[i] || nuevo;
      }
      setTimeout(() => { try { destino.focus({ preventScroll: true }); } catch (e) { /* nada */ } }, 0);
    }
  }
  function destellar(n) {
    n.classList.remove('destello');
    void n.offsetWidth;                               // (reinicia la animación)
    n.classList.add('destello');
  }
  const esqueleto = () => h('div', { class: 'esqueleto', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('i'), h('i'));
  function demorar(fn, ms) {
    let t = null;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }
  // Pide y pinta de uno en uno: si se pide otra vez mientras tanto, se repite al terminar (nunca pinta datos viejos
  // encima de nuevos).  cargar() → datos (o lanza); pintar(datos).
  function actualizador(cargar, pintar) {
    let enCurso = null, otraVez = false;
    return () => {
      if (enCurso) { otraVez = true; return enCurso; }
      enCurso = (async () => {
        do {
          otraVez = false;
          let datos;
          try { datos = await cargar(); } catch (e) { break; }
          pintar(datos);
        } while (otraVez);
        enCurso = null;
      })();
      return enCurso;
    };
  }
  // Una vista viva recibe TODOS los eventos aunque no se esté viendo (así, al volver, ya está al día).
  function avisarVistas(ev) {
    const lista = [];
    if (E.vista) lista.push(E.vista);
    for (const v of E.vistas.values()) lista.push(v);
    for (const v of lista) {
      if (v && v.ctl && v.ctl.evento) { try { v.ctl.evento(ev, v === E.vista); } catch (e) { console.error(e); } }
    }
  }
  // Pide a la vista `clave` (si existe, se vea o no) que se ponga al día; si no está viva no hace nada.
  function refrescarVista(clave) {
    const v = E.vista && E.vista.clave === clave ? E.vista : E.vistas.get(clave);
    if (v && v.ctl && v.ctl.actualizar) v.ctl.actualizar();
  }
  // Barrita de progreso de la fila de un reporte en curso (sin volver a pintar la fila)
  function pintarBarraFila(cont, rid) {
    const li = cont.querySelector(':scope > [data-lk="' + rid + '"]');
    const x = E.curso.get(rid);
    if (!li || !x) return;
    const i = li.querySelector('.barra > i');
    if (i) i.style.width = Math.max(3, x.pct || 0) + '%';
    const det = li.querySelector('.det');
    if (det && x.texto) det.textContent = x.texto;
    const cu = li.querySelector('.cuando .pct');
    if (cu) cu.textContent = Math.round(x.pct || 0) + ' %';
  }
  // El estado que se ve de un reporte: el que dicen los eventos (en curso / recién terminado) o el guardado.
  function estadoVisto(r) {
    if (E.curso.has(r.id)) return 'curso';
    const rec = E.recien.get(r.id);
    if (rec && Date.now() - rec.t < 20000) return rec.estado === 'detenido' ? 'detenido' : rec.estado;
    return r.resultado || r.estado || '';
  }

  // ================================================================== v3.8: carga, fecha y guía
  // El tren sobre la vía.  PROVISIONAL hasta tener los loaders elegidos: para cambiarlo basta con tren() y su CSS.
  function tren() { return h('div', { class: 'tren', 'aria-hidden': 'true' }, h('div', { class: 'vagon' }), h('div', { class: 'rueda a' }), h('div', { class: 'rueda b' })); }
  function trenDeFila(it) {
    const t = tren();
    if (it.terminado) t.classList.add('parado');
    if (it.pct === null) return t;
    E.trenes = E.trenes || {};
    const antes = E.trenes[it.clave];
    t.style.left = (antes === undefined ? it.pct : antes) + '%';           // (la fila se repinta: sigue desde donde iba)
    E.trenes[it.clave] = it.pct;
    requestAnimationFrame(() => { t.style.left = it.pct + '%'; });
    return t;
  }

  // Qué fecha lleva un valor guardado, en las palabras de las tarjetas
  function modoDeFecha(valor) {
    const a = analizarFecha(valor);
    const n = a.que === 'dias' ? (parseInt(a.n, 10) || 0) : null;
    if (a.modo === 'relativa' && (a.que === 'hoy' || n === 0)) return 'hoy';
    if (a.modo === 'relativa' && (a.que === 'ayer' || n === -1)) return 'ayer';
    if (a.modo === 'fija') return 'exacta';
    return a.modo === 'vacia' ? 'vacia' : 'otra';
  }
  function fechaEnChip(f) {
    if (f.lista && f.estrategia === 'mas_reciente') return 'la más reciente';
    const m = modoDeFecha(f.valor);
    if (m === 'hoy') return 'el día de hoy';
    if (m === 'ayer') return 'el día anterior';
    if (m === 'exacta') return String(f.valor).trim();
    if (m === 'vacia') return 'sin elegir';
    return palabrasFecha(analizarFecha(f.valor)) || 'escrita a mano';
  }
  // selectorFecha({ valor, formato, lista, masReciente }): tres tarjetas (hoy, anterior, exacta), calendario del mes y «Qué
  // baja cada día» calculado con la fecha real de hoy.  `leer()` → { valor, modo, cambiado }.  Guarda las plantillas de
  // siempre ({hoy:formato}, {ayer:formato} o la fecha fija), con el formato del campo.
  function selectorFecha(opc) {
    const original = String(opc.valor === null || opc.valor === undefined ? '' : opc.valor);
    const a0 = analizarFecha(original);
    const fmt = opc.formato || a0.formato || FORMATO_DEFECTO;
    const inicial = opc.masReciente ? 'reciente' : modoDeFecha(original);
    let modo = inicial;
    let fija = a0.modo === 'fija' ? deIso(a0.fecha) : null;
    const hoy = soloDia(new Date());
    let vista = new Date((fija || hoy).getFullYear(), (fija || hoy).getMonth(), 1);
    const caja = h('div', { class: 'sf', 'data-selector-fecha': '1' });
    const TARJETAS = [['hoy', 'El día de hoy', 'Cada día baja el de ese mismo día.'], ['ayer', 'El día anterior', 'Para reportes que salen al día siguiente.'],
      ['exacta', 'Una fecha exacta', 'Siempre la misma: elígela en el calendario.']];
    if (opc.masReciente) TARJETAS.push(['reciente', 'La más reciente', 'Como ahora: la última que haya, sea del día que sea.']);
    const queBaja = (dia) => {           // la fecha que baja el reporte si se ejecuta ese día
      if (modo === 'hoy') return dia;
      if (modo === 'ayer') return sumarDias(dia, -1);
      if (modo === 'exacta') return fija;
      return modo === 'otra' ? fechaDe(a0, dia) : null;
    };
    const textoBaja = (dia) => {
      if (modo === 'reciente') return 'La más reciente';
      if (modo === 'otra' && !queBaja(dia)) return 'Escrita a mano';
      const d = queBaja(dia);
      return d ? (strfFecha(d, fmt) || isoDia(d)) : 'Sin elegir';
    };
    function valor() {
      if (modo === inicial && (modo !== 'exacta' || (a0.modo === 'fija' && fija && a0.fecha === isoDia(fija)))) return original;
      if (modo === 'hoy') return '{hoy:' + fmt + '}';
      if (modo === 'ayer') return '{ayer:' + fmt + '}';
      if (modo === 'exacta' && fija) return componerFecha({ modo: 'fija', fecha: isoDia(fija), formato: fmt });
      return original;
    }
    function pintar() {
      const foco = document.activeElement && caja.contains(document.activeElement) ? document.activeElement.getAttribute('data-sf') : null;
      const elegido = queBaja(hoy);
      const luego = (modo === 'hoy' || modo === 'ayer') ? [queBaja(sumarDias(hoy, 1)), queBaja(sumarDias(hoy, 2))].map(isoDia) : [];
      const celdas = [];
      for (let i = 0; i < (vista.getDay() + 6) % 7; i++) celdas.push(h('span', { class: 'sf-dia nada' }));
      const fin = new Date(vista.getFullYear(), vista.getMonth() + 1, 0).getDate();
      for (let n = 1; n <= fin; n++) {
        const d = new Date(vista.getFullYear(), vista.getMonth(), n);
        const iso = isoDia(d);
        const sel = !!elegido && iso === isoDia(elegido);
        celdas.push(h('button', { type: 'button', class: 'sf-dia' + (sel ? ' elegido' : '') + (luego.includes(iso) ? ' luego' : '') + (iso === isoDia(hoy) ? ' hoy' : ''),
          'data-dia': iso, 'data-sf': 'dia-' + iso, 'aria-label': fechaEnPalabras(d), 'aria-pressed': sel ? 'true' : 'false',
          onclick: () => { modo = 'exacta'; fija = d; pintar(); } }, String(n)));
      }
      const mover = (n) => () => { vista = new Date(vista.getFullYear(), vista.getMonth() + n, 1); pintar(); };
      caja.replaceChildren(...[
        h('div', { class: 'sf-opciones' }, TARJETAS.map(([k, t, d]) => h('button', { type: 'button', class: 'sf-opcion', 'data-opcion-fecha': k, 'data-sf': 'op-' + k, 'aria-pressed': modo === k ? 'true' : 'false',
          onclick: () => { modo = k; if (k === 'exacta' && !fija) fija = hoy; if (fija && k === 'exacta') vista = new Date(fija.getFullYear(), fija.getMonth(), 1); pintar(); } }, h('b', null, t), h('span', null, d)))),
        modo === 'otra' ? h('p', { class: 'ayuda' }, 'Ahora tiene: ' + fechaEnChip({ valor: original }) + '. Si tocas una tarjeta o un día, se cambia.') : null,
        h('div', { class: 'sf-dos' },
          h('div', { class: 'sf-caja' },
            h('div', { class: 'sf-cab' }, h('button', { type: 'button', class: 'boton chico solo-icono', 'aria-label': 'Mes anterior', 'data-sf': 'mes-a', onclick: mover(-1) }, ico('atras')),
              h('div', { class: 'sf-titulo', 'aria-live': 'polite' }, MESES[vista.getMonth()] + ' ' + vista.getFullYear()),
              h('button', { type: 'button', class: 'boton chico solo-icono cal-sig', 'aria-label': 'Mes siguiente', 'data-sf': 'mes-s', onclick: mover(1) }, ico('atras'))),
            h('div', { class: 'sf-mes' }, ['Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá', 'Do'].map((x) => h('div', { class: 'sf-sem' }, x)), celdas),
            h('div', { class: 'sf-ley' }, h('span', null, h('i', { class: 'm-elegido' }), 'La fecha que baja'), h('span', null, h('i', { class: 'm-luego' }), 'Los próximos días'), h('span', null, h('i', { class: 'm-hoy' }), 'Hoy'))),
          h('div', { class: 'sf-caja' }, h('div', { class: 'sf-titulo' }, 'Qué baja cada día'),
            [[0, 'Hoy'], [1, 'Mañana'], [2, 'Pasado mañana']].map(([n, et]) => {
              const d = sumarDias(hoy, n);
              return h('div', { class: 'sf-reg', 'data-baja': String(n) }, h('span', null, h('small', null, et),
                h('b', null, DIAS_SEMANA[(d.getDay() + 6) % 7][1] + ' ' + d.getDate())), h('em', null, textoBaja(d)));
            }))),
        opc.lista ? h('p', { class: 'sf-nota' }, 'Si el reporte de esa fecha todavía no ha salido, el bot no baja uno viejo: el paso falla y te dice por qué.') : null].filter(Boolean));
      if (foco) { const x = caja.querySelector('[data-sf="' + foco + '"]'); if (x) x.focus({ preventScroll: true }); }
    }
    pintar();
    return { caja, leer: () => ({ valor: valor(), modo, cambiado: modo !== inicial || valor() !== original }) };
  }
  // La ventana para elegir una fecha (parada de fecha al mapear)
  function elegirFecha(opc) {
    const sel = selectorFecha(opc);
    abrirModal({ titulo: opc.titulo || '¿De qué fecha lo quieres?', ancho: true, contenido: h('div', { 'data-modal-fecha': '1' }, sel.caja),
      botones: [{ texto: 'Cancelar', accion: cerrarModal }, { texto: 'Aceptar', clase: 'primario', accion: () => { const v = sel.leer().valor; cerrarModal(); opc.alAceptar(v); } }] });
  }
  // El chip «Fecha: …» de un reporte; al guardar queda en el reporte (con su versión anterior guardada)
  function chipFecha(x) {
    const fs = x.fechas || [];
    if (!fs.length) return null;
    const texto = fs.length === 1 ? fechaEnChip(fs[0]) : fs.map((f) => f.nombre + ': ' + fechaEnChip(f)).join(' · ');
    return h('button', { type: 'button', class: 'chip-fecha', 'data-chip-fecha': String(x.id), 'aria-label': 'Cambiar la fecha de ' + x.nombre, onclick: () => modalFechaReporte(x) }, ico('calendario'), 'Fecha: ' + texto);
  }
  function modalFechaReporte(x) {
    const partes = x.fechas.map((f) => ({ f, sel: selectorFecha({ valor: f.valor, formato: f.formato || null, lista: f.lista, masReciente: f.lista && f.estrategia === 'mas_reciente' }) }));
    const zona = h('div');
    let actual = 0;
    const pestanas = h('div', { class: 'sf-pestanas', role: 'group', 'aria-label': 'Qué fecha cambiar' });
    function pintar() {
      pestanas.replaceChildren(...partes.map((p, i) => h('button', { type: 'button', 'aria-pressed': i === actual ? 'true' : 'false', 'data-fecha-paso': String(p.f.paso), onclick: () => { actual = i; pintar(); } }, p.f.nombre)));
      zona.replaceChildren(partes[actual].sel.caja);
    }
    pintar();
    const guardar = async () => {
      const elecciones = {};
      for (const p of partes) {
        const v = p.sel.leer();
        if (!v.cambiado) continue;
        elecciones[p.f.paso] = p.f.lista ? (v.modo === 'reciente' ? { estrategia: 'mas_reciente', valor: '' } : { estrategia: 'por_fecha', valor: v.valor }) : { estrategia: 'fija', valor: v.valor };
      }
      if (!Object.keys(elecciones).length) { cerrarModal(); return; }
      try {
        await api('POST', 'reportes/' + x.id + '/filtros/predeterminado', { elecciones });
        cerrarModal();
        toast('Fecha de «' + x.nombre + '» guardada', 'ok');
        if (E.vista && E.vista.ctl && E.vista.ctl.actualizar) E.vista.ctl.actualizar(true);
      } catch (e) { errorToast(e); }
    };
    abrirModal({ titulo: '¿De qué fecha quieres «' + x.nombre + '»?', ancho: true,
      contenido: h('div', { 'data-modal-fecha': String(x.id) }, partes.length > 1 ? pestanas : null, zona),
      botones: [{ texto: 'Cancelar', accion: cerrarModal }, { texto: 'Guardar la fecha', clase: 'primario', accion: guardar }] });
  }

  // Guía de inicio: oscurece todo menos el elemento real, con un globo y una flecha.  Se puede saltar siempre (Esc o
  // «Saltar»).  Si un destino no está (p. ej. sin reportes), usa otro que explique lo mismo o se salta ese paso.
  const PASOS_GUIA = [
    { sel: '[data-guia="nuevo"]', t: 'Empieza aquí', x: 'Pulsa aquí y pega la dirección de la web. El bot encuentra sus listas, fechas y botones.' },
    { sel: '.fila-rep [data-ejecutar]', t: 'Con un clic lo bajas', x: 'Lo que guardes queda en esta lista, listo para descargar cuando quieras.',
      otro: '[data-guia="reportes"]', xOtro: 'Lo que guardes aparecerá en esta lista. Con un clic lo descargas cuando quieras.' },
    { sel: '[data-chip-fecha]', t: 'Elige de qué fecha', x: '«Hoy» cambia solo: el miércoles baja el del miércoles y el jueves, el del jueves.',
      otro: '[data-guia="parada-fecha"]', xOtro: 'Cada reporte tiene su fecha. «Hoy» cambia sola: el miércoles baja el del miércoles y el jueves, el del jueves.' },
    { sel: '[data-programar]', t: 'Que se haga solo', x: 'Elige días y hora. El bot lo descarga sin que estés aquí.',
      otro: '[data-guia="parada-descargar"]', xOtro: 'Podrás bajarlo ahora o elegir días y hora para que el bot lo haga sin ti.' }];
  let GUIA = null;
  const visibleEn = (sel) => [...document.querySelectorAll('#contenido ' + sel)].find((x) => { const r = x.getBoundingClientRect(); return r.width > 0 && r.height > 0; }) || null;
  function pasosGuia() {
    const res = [];
    for (const p of PASOS_GUIA) {
      if (visibleEn(p.sel)) res.push({ sel: p.sel, t: p.t, x: p.x });
      else if (p.otro && visibleEn(p.otro)) res.push({ sel: p.otro, t: p.t, x: p.xOtro });
    }
    return res;
  }
  function colocarGuia() {
    const g = GUIA;
    if (!g) return;
    let el = visibleEn(g.pasos[g.i].sel);
    while (!el && g.i < g.pasos.length - 1) { g.i++; pintarGuia(); return; }     // (el destino desapareció: el siguiente)
    if (!el) { cerrarGuia(true); return; }
    const r = el.getBoundingClientRect();
    const vw = document.documentElement.clientWidth, vh = window.innerHeight, M = 5;
    Object.assign(g.foco.style, { left: (r.left - M) + 'px', top: (r.top - M) + 'px', width: (r.width + M * 2) + 'px', height: (r.height + M * 2) + 'px' });
    const ancho = g.globo.offsetWidth, alto = g.globo.offsetHeight, FL = 62;
    const abajo = r.bottom + FL + alto + 8 <= vh || r.top - FL - alto - 8 < 0;
    g.globo.classList.toggle('abajo', abajo);
    g.globo.classList.toggle('arriba', !abajo);
    const izq = Math.max(12, Math.min(r.left + r.width / 2 - ancho / 2, vw - ancho - 12));
    const arriba = abajo ? Math.min(r.bottom + FL, vh - alto - 8) : r.top - FL - alto;
    g.globo.style.left = izq + 'px';
    g.globo.style.top = Math.max(8, arriba) + 'px';
    g.flecha.style.left = Math.max(8, Math.min(r.left + r.width / 2 - izq - 22, ancho - 52)) + 'px';
  }
  function pintarGuia() {
    const g = GUIA;
    const p = g.pasos[g.i];
    const el = visibleEn(p.sel);
    if (el) el.scrollIntoView({ block: 'center', inline: 'nearest' });
    const fin = g.i === g.pasos.length - 1;
    g.flecha = document.createElementNS(SVG, 'svg');
    g.flecha.setAttribute('class', 'guia-flecha');
    g.flecha.setAttribute('viewBox', '0 0 44 56');
    g.flecha.setAttribute('aria-hidden', 'true');
    const trazo = document.createElementNS(SVG, 'path');
    trazo.setAttribute('d', 'M22 54V5M8 19 22 4l14 15');
    g.flecha.appendChild(trazo);
    const sig = h('button', { type: 'button', class: 'sig', 'data-guia-siguiente': '1', onclick: () => { if (fin) cerrarGuia(true); else { g.i++; pintarGuia(); } } }, fin ? 'Terminar' : 'Siguiente');
    g.globo.replaceChildren(g.flecha, h('strong', { id: 'guia-titulo' }, p.t), h('p', null, p.x),
      h('div', { class: 'guia-pie' }, h('span', null, 'Paso ' + (g.i + 1) + ' de ' + g.pasos.length), h('button', { type: 'button', 'data-guia-saltar': '1', onclick: () => cerrarGuia(true) }, 'Saltar'), sig));
    // (se repite la entrada del globo en cada paso)
    g.globo.style.animation = 'none';
    void g.globo.offsetWidth;
    g.globo.style.animation = '';
    colocarGuia();
    sig.focus({ preventScroll: true });
  }
  function abrirGuia() {
    if (GUIA || !$('#modal-fondo').classList.contains('oculto')) return false;
    const pasos = pasosGuia();
    if (!pasos.length) return false;
    const g = { pasos, i: 0, foco: h('div', { class: 'guia-foco' }), globo: h('div', { class: 'guia-globo abajo', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'guia-titulo', 'data-guia-globo': '1' }),
      bloqueo: h('div', { class: 'guia-bloqueo' }), previo: document.activeElement, scroll: window.scrollY };
    g.caja = h('div', { id: 'guia' }, g.bloqueo, g.foco, g.globo);
    g.tecla = (ev) => {
      if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); cerrarGuia(true); return; }
      if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'k' || ev.key === 'K')) { ev.preventDefault(); ev.stopPropagation(); return; }
      if (ev.key === 'Tab') {                    // el foco no sale del globo
        const b = [...g.globo.querySelectorAll('button')];
        const i = b.indexOf(document.activeElement);
        ev.preventDefault();
        b[(i + (ev.shiftKey ? -1 : 1) + b.length) % b.length].focus();
      }
    };
    g.colocar = () => colocarGuia();
    g.salir = () => cerrarGuia(false);
    window.addEventListener('keydown', g.tecla, true);
    window.addEventListener('resize', g.colocar);
    window.addEventListener('scroll', g.colocar, true);
    window.addEventListener('hashchange', g.salir);
    g.reloj = setInterval(g.colocar, 400);        // (si la página cambia por detrás: la lista se pone al día)
    GUIA = g;
    document.body.appendChild(g.caja);
    pintarGuia();
    return true;
  }
  function cerrarGuia(vista) {
    const g = GUIA;
    if (!g) return;
    GUIA = null;
    clearInterval(g.reloj);
    window.removeEventListener('keydown', g.tecla, true);
    window.removeEventListener('resize', g.colocar);
    window.removeEventListener('scroll', g.colocar, true);
    window.removeEventListener('hashchange', g.salir);
    g.caja.remove();
    window.scrollTo(0, g.scroll);
    if (vista) api('PUT', 'ajustes', { ajustes: { guia_vista: true } }).then((r) => { E.ajustes = r.ajustes; }).catch(() => {});
    if (g.previo && g.previo.isConnected) { try { g.previo.focus({ preventScroll: true }); } catch (e) { /* nada */ } }
  }
  // «Ver la guía otra vez»: desde cualquier sección (va a Inicio y espera a que esté pintado)
  async function verGuia() {
    if (E.ruta !== 'inicio') location.hash = '#/inicio';
    for (let i = 0; i < 100; i++) {
      if (E.ruta === 'inicio' && E.vista && visibleEn('[data-guia="nuevo"]')) { abrirGuia(); return; }
      await dormir(50);
    }
  }

  // ================================================================== páginas
  const RUTAS = {};
  const NOMBRES = { inicio: 'Inicio', reportes: 'Reportes', editor: 'Editor de pasos', grabar: 'Grabar un reporte',
                    mapear: 'Mapear página', vigilancia: 'Vigilancia', correo: 'Correo', accesos: 'Accesos', historial: 'Historial', ajustes: 'Ajustes' };
  // Vistas que se quedan vivas al cambiar de sección (la clave es la ruta completa: «paginas», no «paginas/3»)
  const VIVAS = ['inicio', 'reportes', 'vigilancia', 'correo', 'accesos', 'historial', 'grabar', 'mapear'];
  E.ruta = '';

  function marcarMenu(pagina) {
    document.querySelectorAll('#menu a').forEach((a) => {
      const activo = a.dataset.ruta === pagina || (['editor', 'paginas'].includes(pagina) && a.dataset.ruta === 'reportes');
      a.classList.toggle('activo', activo);
      if (activo) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    $('.riel').classList.remove('abierto');
    $('#riel-mas').setAttribute('aria-expanded', 'false');
  }

  async function navegar() {
    if (E.sinPermiso) return;
    const partes = (location.hash.replace(/^#\/?/, '') || 'inicio').split('?')[0].split('/');
    const pagina = RUTAS[partes[0]] ? partes[0] : 'inicio';
    const args = partes.slice(1).filter((x) => x !== '').map(decodeURIComponent);
    const query = new URLSearchParams((location.hash.split('?')[1]) || '');
    const clave = pagina + (args.length ? '/' + args.join('/') : '');
    const n = ++E.nav;
    // la vista que se deja: si es viva se guarda tal cual (con su desplazamiento); si no, se descarta
    const ant = E.vista;
    if (ant) {
      ant.scroll = window.scrollY;
      ant.tit = E.titActual.slice();
      ant.nodo.remove();
      if (ant.viva) E.vistas.set(ant.clave, ant);
      else if (ant.ctl && ant.ctl.alSalir) { try { ant.ctl.alSalir(); } catch (e) { console.error(e); } }
    }
    E.vista = null;
    E.ruta = pagina;
    E.oyentes = [];
    marcarMenu(pagina);
    if (pagina === 'mapear' && query.get('reporte')) E.vistas.delete('mapear');      // («Mapear desde aquí» del editor)
    const guardada = E.vistas.get(clave);
    if (guardada) {                                   // al instante, tal como estaba; se pone al día por detrás
      E.vistas.delete(clave);
      E.vista = guardada;
      $('#contenido').replaceChildren(guardada.nodo);
      titulo(...guardada.tit);
      window.scrollTo(0, guardada.scroll || 0);
      if (guardada.ctl.actualizar) guardada.ctl.actualizar(true);
      return;
    }
    titulo(NOMBRES[pagina] || 'Bot Web');
    const c = h('div', { class: 'vista' });
    const esq = setTimeout(() => { if (!c.firstChild) c.appendChild(esqueleto()); }, 120);
    $('#contenido').replaceChildren(c);
    window.scrollTo(0, 0);
    const vista = { clave, nodo: c, ctl: {}, viva: VIVAS.includes(clave), scroll: 0, tit: null };
    let ctl = null;
    try {
      ctl = await RUTAS[pagina](c, args, query);
    } catch (e) {
      console.error('Error al mostrar la página ' + pagina + ': ' + (e && e.message));
      c.appendChild(h('div', { class: 'alerta error' }, 'No se pudo cargar la página: ' + (e && e.message ? e.message : e)));
      vista.viva = false;
    }
    clearTimeout(esq);
    for (const x of c.querySelectorAll(':scope > .esqueleto')) x.remove();
    c.setAttribute('data-pagina', pagina);
    vista.ctl = ctl || {};
    vista.tit = E.titActual.slice();
    if (n !== E.nav) {                                // se cambió de sección mientras cargaba
      if (vista.viva && ctl) E.vistas.set(clave, vista);
      if (E.vista && E.vista.tit) titulo(...E.vista.tit);
      return;
    }
    E.vista = vista;
  }

  // ================================================================== v3.5: paleta de órdenes (Ctrl K)
  // Buscar o ejecutar cualquier cosa: ir a una sección, ejecutar un reporte, abrir una Página, revisar una vigilancia o
  // una búsqueda de correo, grabar, mapear…  Búsqueda difusa sin acentos ni mayúsculas.  ↑ ↓ Enter Esc.
  const SECCIONES = [['inicio', 'Inicio'], ['reportes', 'Reportes'], ['vigilancia', 'Vigilancia'],
    ['correo', 'Correo'], ['historial', 'Historial'], ['grabar', 'Grabar un reporte'], ['mapear', 'Mapear página'], ['accesos', 'Accesos'], ['ajustes', 'Ajustes']];
  // Puntuación: cada palabra buscada debe estar (mejor si al principio de una palabra) o, si no, aparecer en orden.
  function puntuar(texto, palabras) {
    const t = normalizar(texto);
    let total = 0;
    for (const p of palabras) {
      const i = t.indexOf(p);
      if (i >= 0) { total += i === 0 ? 110 : (/[^a-z0-9]/.test(t[i - 1]) ? 100 : 60); continue; }   // (empates: el orden de la lista)
      let pos = -1, saltos = 0;
      for (const ch of p) {
        const k = t.indexOf(ch, pos + 1);
        if (k < 0) return -1;
        saltos += k - pos - 1;
        pos = k;
      }
      total += Math.max(1, 30 - saltos);
    }
    return total;
  }
  async function datosBuscador(forzar) {
    const b = E.buscador;
    if (b && !forzar && Date.now() - b.t < 20000) return b.datos;
    try { E.buscador = { t: Date.now(), datos: await api('GET', 'buscador') }; } catch (e) { /* lo que hubiera */ }
    return E.buscador ? E.buscador.datos : null;
  }
  function opcionesPaleta(d) {
    const ir = (r) => () => { location.hash = '#/' + r; };
    const lista = [];
    for (const r of (d && d.reportes) || []) {
      lista.push({ texto: 'Ejecutar «' + r.nombre + '»', tipo: r.sitio || 'reporte', icono: 'play', extra: r.sitio,
        accion: () => ejecutarReportes([r.id], r.nombre) });
    }
    lista.push({ texto: 'Grabar un reporte nuevo', tipo: 'acción', icono: 'grabar', accion: ir('grabar') });
    lista.push({ texto: 'Mapear una página', tipo: 'acción', icono: 'mapear', accion: ir('mapear') });
    lista.push({ texto: 'Revisar todas las vigilancias', tipo: 'vigilancia', icono: 'vigilancia', accion: async () => {
      try { await api('POST', 'vigilancias/revisar', {}); toast('Revisando todas las vigilancias activas…'); } catch (e) { errorToast(e); } } });
    lista.push({ texto: 'Revisar el correo ahora', tipo: 'correo', icono: 'correo', accion: async () => {
      try { await api('POST', 'correo/revisar', { ver: false }); toast('Revisando el correo (sin abrir navegador)…'); } catch (e) { errorToast(e); } } });
    lista.push({ texto: 'Ver las notificaciones', tipo: 'acción', icono: 'campana', accion: panelNotificaciones });
    for (const [r, n] of SECCIONES) lista.push({ texto: 'Ir a ' + n, tipo: 'sección', icono: r === 'inicio' ? 'inicio' : r, accion: ir(r) });
    for (const p of (d && d.paginas) || []) lista.push({ texto: 'Abrir la página «' + p.nombre + '»', tipo: 'página', icono: 'paginas', accion: ir('paginas/' + p.id) });
    for (const v of (d && d.vigilancias) || []) {
      lista.push({ texto: 'Revisar «' + v.objetivo + '»' + (v.etiqueta ? ' (' + v.etiqueta + ')' : ''), tipo: 'vigilancia' + (v.activa ? '' : ' · pausada'),
        icono: 'vigilancia', accion: async () => {
          try { await api('POST', 'vigilancias/' + v.id + '/revisar', {}); toast('Revisando «' + v.objetivo + '»…'); } catch (e) { errorToast(e); } } });
    }
    for (const b of (d && d.busquedas) || []) {
      lista.push({ texto: 'Revisar el correo «' + b.nombre + '»', tipo: 'correo', icono: 'correo', accion: async () => {
        try { await api('POST', 'correo/busquedas/' + b.id + '/revisar', { ver: false }); toast('Revisando «' + b.nombre + '»…'); } catch (e) { errorToast(e); } } });
    }
    for (const r of (d && d.reportes) || []) lista.push({ texto: 'Editar los pasos de «' + r.nombre + '»', tipo: 'editor', icono: 'editar', accion: ir('editor/' + r.id) });
    return lista;
  }
  // Filtra y ordena (lo exportado para las pruebas: window.__botPaleta.buscar)
  function buscarEnPaleta(lista, q) {
    const palabras = normalizar(q).split(/\s+/).filter(Boolean);
    if (!palabras.length) return lista.slice();
    return lista.map((o, i) => ({ o, i, p: puntuar(o.texto + ' ' + (o.extra || '') + ' ' + o.tipo, palabras) }))
      .filter((x) => x.p >= 0).sort((a, b) => b.p - a.p || a.i - b.i).map((x) => x.o);
  }
  function abrirPaleta() {
    const fondo = $('#paleta');
    if (!fondo.classList.contains('oculto')) { cerrarPaleta(); return; }
    if (E.modal) return;                              // (con una ventana abierta, la paleta no se abre)
    const previo = document.activeElement;
    let todas = opcionesPaleta(E.buscador ? E.buscador.datos : null);
    let vis = todas;
    let sel = 0;
    const entrada = h('input', { type: 'text', id: 'paleta-q', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'paleta-lista',
      'aria-autocomplete': 'list', autocomplete: 'off', spellcheck: 'false', placeholder: 'Escribe: cartera, correo, vigilancia…', 'aria-label': 'Buscar o ejecutar' });
    const lista = h('ul', { id: 'paleta-lista', role: 'listbox', 'aria-label': 'Resultados' });
    const vacio = h('div', { class: 'vacio oculto', role: 'status' });
    const caja = h('div', { class: 'paleta', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Buscar o ejecutar' },
      h('div', { class: 'paleta-entrada' }, ico('buscar'), entrada), lista, vacio,
      h('div', { class: 'pie', 'aria-hidden': 'true' }, '↑↓ moverse · Enter ejecutar · Esc cerrar'));
    const pintar = () => {
      vis = buscarEnPaleta(todas, entrada.value);
      sel = Math.min(sel, Math.max(0, vis.length - 1));
      lista.replaceChildren(...vis.slice(0, 60).map((o, i) => h('li', { id: 'pal-' + i, role: 'option', 'aria-selected': i === sel ? 'true' : 'false',
        'data-i': String(i), onmousemove: () => { if (sel !== i) { sel = i; marcar(); } }, onclick: () => elegir(i) },
        ico(o.icono), h('span', { class: 't' }, o.texto), h('span', { class: 'tipo' }, o.tipo))));
      vacio.textContent = 'Nada coincide con «' + entrada.value + '».';
      vacio.classList.toggle('oculto', vis.length > 0);
      marcar();
    };
    const marcar = () => {
      lista.querySelectorAll('li').forEach((li, i) => li.setAttribute('aria-selected', i === sel ? 'true' : 'false'));
      const li = lista.querySelector('#pal-' + sel);
      if (li) { entrada.setAttribute('aria-activedescendant', li.id); li.scrollIntoView({ block: 'nearest' }); }
      else entrada.removeAttribute('aria-activedescendant');
    };
    const elegir = (i) => { const o = vis[i]; if (!o) return; cerrarPaleta(); o.accion(); };
    entrada.addEventListener('input', () => { sel = 0; pintar(); });
    entrada.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowDown') { ev.preventDefault(); sel = Math.min(vis.length - 1, sel + 1); marcar(); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); sel = Math.max(0, sel - 1); marcar(); }
      else if (ev.key === 'Enter') { ev.preventDefault(); elegir(sel); }
      else if (ev.key === 'Escape') { ev.preventDefault(); cerrarPaleta(); }
      else if (ev.key === 'Tab') ev.preventDefault();
    });
    fondo.onclick = (ev) => { if (ev.target === fondo) cerrarPaleta(); };
    fondo.replaceChildren(caja);
    fondo.classList.remove('oculto');
    E.paleta = { previo, refrescar: () => { todas = opcionesPaleta(E.buscador ? E.buscador.datos : null); pintar(); } };
    pintar();
    entrada.focus();
    datosBuscador().then(() => { if (E.paleta) E.paleta.refrescar(); });
  }
  function cerrarPaleta() {
    const fondo = $('#paleta');
    fondo.classList.add('oculto');
    fondo.replaceChildren();
    const previo = E.paleta && E.paleta.previo;
    E.paleta = null;
    if (previo && previo.isConnected && previo !== document.body) { try { previo.focus({ preventScroll: true }); } catch (e) { /* nada */ } }
  }

  // ------------------------------------------------------------------ Centro de control (Inicio)
  // Una línea de 7 días (área + punto final) hecha a mano en SVG: datos = números, color = variable CSS.
  function chispa(datos, color, etiqueta) {
    const w = 120, hh = 24;
    const max = Math.max(1, ...datos);
    const pts = datos.map((v, i) => [(i / Math.max(1, datos.length - 1)) * (w - 2) + 1, hh - 3 - (v / max) * (hh - 6)]);
    const linea = pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const s = document.createElementNS(SVG, 'svg');
    s.setAttribute('viewBox', '0 0 ' + w + ' ' + hh);
    s.setAttribute('preserveAspectRatio', 'none');
    s.setAttribute('aria-hidden', 'true');
    const area = document.createElementNS(SVG, 'polygon');
    area.setAttribute('points', '1,' + hh + ' ' + linea + ' ' + (w - 1) + ',' + hh);
    area.setAttribute('fill', color);
    area.setAttribute('opacity', '.12');
    const pl = document.createElementNS(SVG, 'polyline');
    pl.setAttribute('points', linea);
    pl.setAttribute('fill', 'none');
    pl.setAttribute('stroke', color);
    pl.setAttribute('stroke-width', '1.5');
    pl.setAttribute('vector-effect', 'non-scaling-stroke');
    pl.setAttribute('stroke-linejoin', 'round');
    s.append(area, pl);
    const ult = pts[pts.length - 1];
    return h('div', { class: 'chispa', title: etiqueta || '' }, s,
      h('i', { class: 'fin', style: 'top:' + (ult[1] / hh * 100).toFixed(1) + '%;background:' + color }),
      h('span', { class: 'solo-lector' }, (etiqueta || 'Últimos 7 días') + ': ' + datos.join(', ')));
  }
  function textoSitio(r) { return r.sitio ? r.sitio.replace(/^www\./, '') : ''; }
  // Una fila del Centro de control (reporte): punto de estado, nombre + sitio, línea de datos, cuándo, acciones.
  function filaInicio(r) {
    const est = estadoVisto(r);
    const x = E.curso.get(r.id);
    const enCurso = est === 'curso';
    const punto = { ok: 'ok', error: 'error', detenido: 'detenido', curso: 'curso', programado: 'programado', nuevo: 'nuevo' }[est] || 'nuevo';
    const NOMBRE_ESTADO = { ok: 'bien', error: 'con error', detenido: 'detenido', curso: 'en curso', programado: 'programado', nuevo: 'sin ejecutar' };
    let det, clase = '';
    if (enCurso) { det = (x && x.texto) || 'Empezando…'; clase = ' vivo'; }
    else if (est === 'error' || est === 'detenido') { det = r.mensaje || (est === 'error' ? 'Falló' : 'Se detuvo'); clase = est === 'error' ? ' err' : ''; }
    else if (est === 'ok' && r.resultado === 'ok') det = [(r.archivos || [])[0], duracionTexto(r.duracion)].filter(Boolean).join(' · ') || 'Descargado';
    else if (est === 'ok') det = 'Terminado ahora mismo';
    else if (r.cuando_texto) det = r.cuando_texto.charAt(0).toUpperCase() + r.cuando_texto.slice(1);
    else det = r.ultima ? 'Última vez: ' + cuandoCorto(r.ultima) : 'Sin ejecutar todavía';
    const linea1 = enCurso ? h('span', { class: 'pct' }, Math.round((x && x.pct) || 0) + ' %')
      : (r.ultima && est !== 'programado' ? cuandoCorto(r.ultima) : (r.programado ? 'próximo' : '—'));
    const linea2 = r.proxima ? proximaCorta(r.proxima) : (r.programado ? 'programado' : 'a mano');
    const pideAccesos = (est === 'error') && /licencia|contrase|acceso|usuario|obligatori|sesi[oó]n/i.test(r.mensaje || '');
    const secundario = pideAccesos ? boton(/licencia/i.test(r.mensaje || '') ? 'Completar Licencia' : 'Revisar Accesos', () => { location.hash = '#/accesos'; }, 'chico sec', { title: 'Abre Accesos para completar el dato que pidió la página' })
      : (est === 'error' ? boton('Editar', () => { location.hash = '#/editor/' + r.id; }, 'chico sec') : null);
    const ejecutar = boton('▶ ' + (enCurso ? 'En curso' : 'Ejecutar'), () => ejecutarReportes([r.id], r.nombre), 'chico' + (est === 'error' ? '' : ' primario'),
      { 'aria-label': 'Ejecutar ' + r.nombre, disabled: enCurso, 'data-ejecutar': String(r.id) });
    return h('li', { class: 'fila-rep', 'data-estado': est, 'data-programado': r.programado ? '1' : null, 'data-reporte-id': String(r.id) },
      h('span', { class: 'punto ' + punto, role: 'img', 'aria-label': NOMBRE_ESTADO[est] || est }),
      h('div', { class: 'nom' }, h('a', { href: '#/editor/' + r.id, title: 'Editar los pasos' }, r.nombre), textoSitio(r) ? h('span', { class: 'sitio' }, textoSitio(r)) : null,
        r.vigilado ? chip('vigilado', 'info') : null),
      h('div', { class: 'cuando' }, linea1, h('br'), linea2),
      h('div', { class: 'acc' }, chipFecha(r), boton('Programar', () => programarReporte(r.id, r.nombre), 'chico sec', { 'data-programar': String(r.id) }), secundario, ejecutar),
      h('div', { class: 'det' + clase, title: det }, det),
      enCurso ? h('div', { class: 'barra', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round((x && x.pct) || 0)), 'aria-label': 'Progreso de ' + r.nombre },
        h('i', { style: 'width:' + Math.max(3, (x && x.pct) || 0) + '%' })) : null);
  }

  // v3.7: «En curso» del Centro de control: lo que hace el bot ahora (lanzado desde aquí o por una tarea de Windows), con
  // su barra de progreso, el paso, el tiempo y Detener (o, si espera para empezar: Ver en vivo / Empezar ya / Cancelar).
  const reloj = (seg) => { seg = Math.max(0, Math.round(seg)); const m = Math.floor(seg / 60); const hh = Math.floor(m / 60);
    return hh ? hh + ':' + dos(m % 60) + ':' + dos(seg % 60) : m + ':' + dos(seg % 60); };
  function fechaLocal(t) { const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?/.exec(t || ''); return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) : null; }
  function itemsEnCurso() {
    const res = [];
    const t = E.trabajo;
    if (t && t.estado === 'en_curso' && !['grabar', 'mapear'].includes(t.tipo)) {
      const pct = t.total && t.paso !== null && t.paso !== undefined && t.paso >= 0 ? Math.min(100, Math.round(100 * (t.paso + 1) / t.total)) : null;
      res.push({ clave: 'ui:' + t.id, origen: 'ui', nombre: t.descripcion || 'Trabajando…', estado: 'en_curso', texto: t.texto || 'Empezando…', pct, t0: t._t0 || Date.now() });
    }
    for (const x of E.externos || []) {
      if (!x._t0) x._t0 = Date.now() - (x.segundos || 0) * 1000;
      const pct = x.estado === 'esperando' ? null : (x.terminado ? 100 : (x.total && x.paso ? Math.min(100, Math.round(100 * x.paso / x.total)) : null));
      const texto = x.estado === 'esperando' ? 'Se ejecutará a las ' + horaDe(x.empieza) + (x.visible ? ' (en vivo)' : ' (en segundo plano)')
        : (x.terminado ? (x.resumen ? x.resumen.charAt(0).toUpperCase() + x.resumen.slice(1) : 'Terminó')
          : (x.total && x.paso ? 'Paso ' + Math.min(x.paso, x.total) + ' de ' + x.total + ': ' : '') + (x.texto || 'Empezando…'));
      res.push({ clave: 'ext:' + x.id, origen: 'tarea', id: x.id, nombre: x.nombre, estado: x.estado, terminado: x.terminado, texto, pct,
        t0: x._t0, empieza: x.empieza, visible: x.visible, pedido: x.pedido });
    }
    return res;
  }
  function tiempoEnCurso(it) {
    if (it.estado === 'esperando') { const f = fechaLocal(it.empieza); return f ? 'empieza en ' + reloj((f.getTime() - Date.now()) / 1000) : ''; }
    if (it.terminado) return '';
    return 'lleva ' + reloj((Date.now() - it.t0) / 1000);
  }
  function filaEnCurso(it) {
    const pedir = (accion, texto) => async (ev) => {
      ev.currentTarget.disabled = true;
      try { await api('POST', 'en_curso/' + it.id + '/' + accion, {}); toast(texto, accion === 'detener' || accion === 'cancelar' ? 'aviso' : 'ok'); }
      catch (e) { errorToast(e); }
    };
    let acciones = [];
    if (it.origen === 'ui') acciones = [boton('Detener', async () => { try { await api('POST', 'detener', {}); toast('Deteniendo…', 'aviso'); } catch (e) { errorToast(e); } }, 'chico', { 'data-detener': it.clave })];
    else if (it.estado === 'esperando') acciones = [it.visible ? null : boton('Ver en vivo', pedir('en_vivo', 'Esta vez se verá en vivo'), 'chico', { 'data-pedir': 'en_vivo' }),
      boton('Empezar ya', pedir('ya', 'Empieza ahora'), 'chico', { 'data-pedir': 'ya' }),
      boton('Cancelar esta ejecución', pedir('cancelar', 'Cancelada: esta vez no se ejecuta'), 'chico peligro', { 'data-pedir': 'cancelar' })];
    else if (!it.terminado) acciones = [boton('Detener', pedir('detener', 'Deteniendo…'), 'chico', { 'data-pedir': 'detener', disabled: it.pedido === 'detener' })];
    const punto = it.terminado ? ({ ok: 'ok', error: 'error', detenido: 'detenido', cancelado: 'detenido' }[it.estado] || 'nuevo') : 'curso';
    return h('li', { class: 'fila-curso', 'data-en-curso-id': it.clave, 'data-estado': it.estado },
      h('span', { class: 'punto ' + punto, 'aria-hidden': 'true' }),
      h('div', { class: 'nom' }, h('strong', null, it.nombre), chip(it.origen === 'ui' ? 'desde el bot' : 'tarea de Windows', it.origen === 'ui' ? 'vivo' : 'info')),
      h('div', { class: 'cuando', 'data-tiempo': '1' }, tiempoEnCurso(it)),
      h('div', { class: 'acc' }, acciones),
      h('div', { class: 'det' + (it.terminado ? (it.estado === 'ok' ? ' t-ok' : ' t-err') : ' vivo'), title: it.texto, 'data-texto': '1' }, it.texto),
      h('div', { class: 'barra via' + (it.pct === null ? ' indeterminada' : ''), role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100',
        'aria-valuenow': it.pct === null ? null : String(it.pct), 'aria-label': 'Progreso de ' + it.nombre },
      h('i', { style: 'width:' + (it.pct === null ? 30 : Math.max(3, it.pct)) + '%' }), trenDeFila(it)));
  }
  function pintarEnCurso(caja) {
    const items = itemsEnCurso();
    caja.classList.toggle('oculto', !items.length);
    let lista = caja.querySelector('ul');
    if (!lista) { lista = h('ul', { class: 'filas', 'aria-label': 'En curso' }); caja.replaceChildren(h('header', null, h('h2', null, 'En curso'), h('span', { class: 'meta' }, 'con su barra de progreso')), lista); }
    claveLista(lista, items, (x) => x.clave, filaEnCurso, { firma: (x) => JSON.stringify([x.estado, x.texto, x.pct, x.visible, x.pedido]) });
    for (const li of lista.children) {
      const it = items.find((x) => x.clave === li.dataset.lk);
      const tt = li.querySelector('[data-tiempo]');
      if (it && tt) tt.textContent = tiempoEnCurso(it);
    }
  }
  // v3.7: «Lo programado»: cada cosa con horario, con su interruptor «En vivo / En segundo plano»
  function filaProgramado(x, alCambiar) {
    const poner = (vivo) => async (ev) => {
      if (vivo === x.en_vivo) return;
      const grupo = ev.currentTarget.parentNode;
      grupo.querySelectorAll('button').forEach((b) => { b.disabled = true; });
      try {
        const r = await api('POST', 'en_vivo', { clave: x.clave, en_vivo: vivo });
        toast((r.tarea_actualizada ? 'Tarea de Windows actualizada: ' : 'Guardado: ') + '«' + x.nombre + '» ' +
          (vivo ? 'se verá en vivo (navegador visible).' : 'se ejecutará en segundo plano (oculto).'), 'ok');
        x.en_vivo = vivo;
        if (alCambiar) alCambiar();
      } catch (e) { errorToast(e); grupo.querySelectorAll('button').forEach((b) => { b.disabled = false; }); }
    };
    const seg = (vivo, texto) => h('button', { type: 'button', 'data-modo': vivo ? 'vivo' : 'fondo', 'aria-pressed': x.en_vivo === vivo ? 'true' : 'false', onclick: poner(vivo) }, texto);
    return h('li', { class: 'fila-prog', 'data-programado': x.clave },
      h('div', { class: 'nom' }, h('strong', null, x.nombre), x.tiene_tarea ? null : chip('sin tarea de Windows', 'aviso')),
      h('div', { class: 'det', title: x.cuando_texto }, (x.proxima ? x.proxima + ' · ' : '') + x.cuando_texto),
      h('div', { class: 'sub' }, x.avisos_texto),
      h('div', { class: 'segmento', role: 'group', 'aria-label': 'Cómo se ve «' + x.nombre + '»', 'data-en-vivo': x.clave },
        seg(true, 'En vivo'), seg(false, 'En segundo plano')));
  }

  RUTAS.inicio = async (c) => {
    let d = null;
    let filtro = 'todos';
    const vistosFeed = new Set();
    const vivosFeed = {};                       // «r12» / «p3» / «c2» / «vig» / «correo» → cuándo se anotó en vivo
    let feedListo = false;
    const kpis = h('section', { class: 'kpis', 'aria-label': 'Resumen de hoy' });
    const filas = h('ul', { class: 'filas', 'data-filtro': 'todos', 'aria-label': 'Reportes' });
    const sinFiltro = h('p', { class: 'fila-vacia oculto' });
    const metaRep = h('span', { class: 'meta' });
    const botonesFiltro = [['todos', 'Todos'], ['error', 'Con error'], ['programados', 'Programados']].map(([v, t]) =>
      h('button', { type: 'button', 'aria-pressed': v === 'todos' ? 'true' : 'false', 'data-filtro': v, onclick: () => ponerFiltro(v) }, t));
    const feed = h('ul', { class: 'feed', 'aria-live': 'polite', 'aria-relevant': 'additions', 'aria-label': 'Actividad en vivo' });
    const miniVig = h('section', { class: 'tarjeta mini', 'aria-label': 'Vigilancia' });
    const miniCorreo = h('section', { class: 'tarjeta mini', 'aria-label': 'Correo' });
    const miniProx = h('section', { class: 'tarjeta mini', 'aria-label': 'Próximas ejecuciones' });
    const cajaCurso = h('section', { class: 'tarjeta en-curso oculto', 'aria-label': 'En curso', 'data-en-curso': '1' });
    const listaProg = h('ul', { class: 'filas', 'aria-label': 'Lo programado' });
    const cajaProg = h('section', { class: 'tarjeta programados oculto', 'aria-label': 'Lo programado', 'data-programados': '1' },
      h('header', null, h('h2', null, 'Lo programado'), h('span', { class: 'meta' }, 'cómo se ve cada ejecución')), listaProg);
    const ir = (r) => () => { location.hash = '#/' + r; };
    // v3.8: las cuatro paradas de «La Ruta» y el botón principal
    const PARADAS = [['Entrar', 'a la web del reporte', 'parada-entrar'], ['Marcar', 'lo que quieres y lo que no', 'parada-marcar'],
      ['Fecha', 'de qué día lo bajas', 'parada-fecha'], ['Descargar', 'ahora o a una hora', 'parada-descargar']];
    const rutaInicio = h('section', { class: 'ruta-tarjeta', 'aria-label': 'Cómo crear un reporte', 'data-ruta-inicio': '1' },
      h('div', { class: 'ruta-cab' }, h('h2', null, 'Cuatro paradas para crear un reporte'),
        h('div', { class: 'fila' }, boton('Ver la guía otra vez', () => verGuia(), 'chico enlace', { 'data-ver-guia': '1' }),
          boton('＋ Nuevo reporte', ir('mapear'), 'primario grande', { 'data-guia': 'nuevo' }))),
      h('div', { class: 'ruta' }, PARADAS.map(([b, s, g]) => h('div', { class: 'parada-ruta', 'data-guia': g }, h('i'), h('b', null, b), h('span', null, s)))));
    c.append(rutaInicio, kpis, cajaCurso,
      h('div', { class: 'cc-rejilla' },
        h('section', { class: 'tarjeta', 'aria-label': 'Reportes', 'data-guia': 'reportes' },
          h('header', null, h('h2', null, 'Reportes'), h('div', { class: 'chips-filtro', role: 'group', 'aria-label': 'Filtrar reportes' }, botonesFiltro), metaRep),
          filas, sinFiltro,
          h('footer', null, boton('● Grabar un reporte nuevo', ir('grabar'), 'chico'), boton('⌖ Mapear una página', ir('mapear'), 'chico'),
            h('span', { class: 'espacio', style: 'flex:1' }), boton('Ver todos los reportes', ir('reportes'), 'chico enlace'))),
        h('section', { class: 'tarjeta', 'aria-label': 'Actividad en vivo' },
          h('header', null, h('h2', null, 'En vivo'), h('span', { class: 'meta' }, h('span', { class: 'en-directo', 'aria-hidden': 'true' }), 'sin recargar')), feed)),
      h('div', { class: 'cc-bajo' }, miniVig, miniCorreo, miniProx), cajaProg);
    filas.appendChild(h('li', { class: 'fila-vacia' }, esqueleto()));

    function ponerFiltro(v) {
      filtro = v;
      filas.setAttribute('data-filtro', v);
      botonesFiltro.forEach((b) => b.setAttribute('aria-pressed', b.dataset.filtro === v ? 'true' : 'false'));
      contarFiltro();
    }
    function contarFiltro() {
      const lista = (d && d.reportes) || [];
      const n = lista.filter((r) => filtro === 'todos' || (filtro === 'error' ? estadoVisto(r) === 'error' : r.programado)).length;
      sinFiltro.textContent = filtro === 'error' ? 'Ningún reporte con error. Todo bien.' : 'Ningún reporte tiene tarea de Windows. Usa «Programar…» en el editor.';
      sinFiltro.classList.toggle('oculto', !(lista.length && !n));
    }
    function kpi(id, et, num, peq, datos, color, ruta, err) {
      return { id, et, num, peq, datos, color, ruta, err };
    }
    function pintarKpis() {
      const k = d.kpi || {};
      const s = d.serie || { descargas: [], total: [], errores: [], novedades: [] };
      const dif = (k.descargas_hoy || 0) - (k.descargas_ayer || 0);
      const enCurso = (E.curso.size || (E.trabajo && E.trabajo.estado === 'en_curso' ? 1 : 0)) + (E.externos || []).filter((x) => !x.terminado).length;
      const lista = [
        kpi('descargas', 'Descargas hoy', k.descargas_hoy || 0, dif ? (dif > 0 ? '+' : '−') + Math.abs(dif) + ' vs. ayer' : 'igual que ayer', s.descargas, 'var(--vivo)', 'historial'),
        kpi('curso', 'En curso', enCurso, enCurso ? 'ahora mismo' : 'nada en marcha', s.total, 'var(--vivo)', 'historial'),
        kpi('error', 'Con error', k.fallidos_hoy || 0, k.fallidos_hoy ? 'necesita tu atención' : 'todo bien', s.errores, 'var(--error)', 'historial', !!k.fallidos_hoy),
        kpi('novedades', 'Novedades', k.novedades || 0, k.novedades ? 'cortes por descargar' : 'sin cortes nuevos', s.novedades, 'var(--aviso)', 'vigilancia')];
      const ETQ = { descargas: 'Descargas por día', curso: 'Ejecuciones por día', error: 'Errores por día', novedades: 'Novedades por día' };
      claveLista(kpis, lista, (x) => x.id, (x) => h('a', { class: 'kpi', href: '#/' + x.ruta, 'data-kpi': x.id, 'aria-label': x.et + ': ' + x.num + ' (' + x.peq + ')' },
        h('div', { class: 'et' }, x.et), h('div', { class: 'num' + (x.err ? ' err' : '') }, String(x.num), h('small', null, x.peq)),
        chispa(x.datos && x.datos.length ? x.datos : [0, 0], x.color, ETQ[x.id] + ' (últimos 7 días)')));
    }
    function pintarFilas() {
      const lista = d.reportes || [];
      claveLista(filas, lista, (r) => r.id, filaInicio, {
        firma: (r) => JSON.stringify([r, estadoVisto(r), E.curso.has(r.id) ? (E.curso.get(r.id).texto ? 1 : 0) : 0]),
        destello: (r) => E.recien.has(r.id) && Date.now() - E.recien.get(r.id).t < 3000,
        vacio: () => h('li', { class: 'fila-vacia' }, 'Todavía no hay reportes. ', h('a', { href: '#/grabar' }, 'Graba el primero'), ' o ', h('a', { href: '#/mapear' }, 'mapea una página'), '.') });
      for (const rid of E.curso.keys()) pintarBarraFila(filas, rid);
      metaRep.textContent = lista.length + (lista.length === 1 ? ' reporte' : ' reportes');
      contarFiltro();
    }
    // --- En vivo
    function itemFeed(it, nuevo) {
      return h('li', { class: nuevo ? 'nuevo' : null, 'data-feed': it.id },
        h('time', { datetime: it.cuando || '' }, it.t),
        h('div', { class: 'texto' }, h('span', { class: it.clase }, it.texto),
          it.chip ? h('div', null, h('span', { class: 'chip-archivo', title: it.chip }, ico('archivo'), it.chip)) : null));
    }
    function anotar(it, nuevo) {
      const vacio = feed.querySelector('.vacio');
      if (vacio) vacio.remove();
      feed.prepend(itemFeed(it, nuevo));
      while (feed.children.length > 40) feed.lastElementChild.remove();
    }
    const ahoraHM = () => { const n = new Date(); return dos(n.getHours()) + ':' + dos(n.getMinutes()); };
    function enVivo(texto, clase, chipTxt, clave) {
      if (clave) vivosFeed[clave] = Date.now();
      anotar({ id: 'v' + Date.now() + Math.random(), t: ahoraHM(), texto, clase, chip: chipTxt }, true);
    }
    function deEjecucion(e) {
      const nombre = e.nombre || 'Reporte';
      const pre = e.correo_id ? 'Correo «' + nombre + '»: ' : (e.pagina_id ? 'Página «' + nombre + '»: ' : '');
      let texto, clase;
      if (e.resultado === 'ok') {
        texto = e.correo_id ? pre + (e.mensaje || 'revisado') : (pre ? pre + 'descargado' : nombre + ' descargado') + (e.duracion ? ' en ' + duracionTexto(e.duracion) : '');
        clase = 't-ok';
      } else if (e.resultado === 'detenido') { texto = (pre || nombre + ' ') + 'se detuvo'; clase = 't-aviso'; }
      else { texto = (pre || nombre + ': ') + (e.mensaje || 'falló'); clase = 't-err'; }
      return { id: 'e' + e.id, cuando: e.cuando, t: horaDe(e.cuando), texto, clase, chip: (e.archivos || []).length ? nombreArchivo(e.archivos[0]) : '',
               clave: e.reporte_id ? 'r' + e.reporte_id : (e.pagina_id ? 'p' + e.pagina_id : (e.correo_id ? 'c' + e.correo_id : '')) };
    }
    function deNotificacion(n) {
      const clase = n.tipo === 'vigilancia' ? 't-aviso' : (n.tipo === 'clave_rechazada' || n.tipo === 'correo_error' ? 't-err' : (n.tipo === 'correo' ? 't-ok' : 't-suave'));
      return { id: 'n' + n.id, cuando: n.cuando, t: horaDe(n.cuando), texto: n.titulo + (n.texto ? ': ' + n.texto : ''), clase,
               clave: n.tipo === 'vigilancia' ? 'vig' : (n.tipo === 'correo' ? 'correo' : '') };
    }
    function itemsServidor() {
      return [...(d.ultimas || []).map(deEjecucion), ...(d.notificaciones || []).map(deNotificacion)]
        .sort((a, b) => (b.cuando || '').localeCompare(a.cuando || '')).slice(0, 16);
    }
    function pintarFeed() {
      const items = itemsServidor();
      if (!feedListo) {
        feed.replaceChildren(...items.map((it) => itemFeed(it, false)));
        if (!items.length) feed.appendChild(h('li', { class: 'vacio' }, h('span'), h('span', { class: 't-suave' }, 'Aquí irá apareciendo lo que hace el bot, sin recargar.')));
        items.forEach((it) => vistosFeed.add(it.id));
        feedListo = true;
        return;
      }
      // después: solo lo nuevo que NO se haya visto ya en vivo (p. ej. lo que hizo una tarea de Windows)
      const nuevos = items.filter((it) => !vistosFeed.has(it.id)).reverse();
      for (const it of nuevos) {
        vistosFeed.add(it.id);
        if (it.clave && vivosFeed[it.clave] && Date.now() - vivosFeed[it.clave] < 5 * 60000) continue;
        anotar(it, true);
      }
    }
    // --- tarjetas de abajo
    let firmaMinis = '';
    function pintarMinis() {
      const f = JSON.stringify([d.vigilancia_novedad, d.correo_ultimo, d.proximas]);
      if (f === firmaMinis) return;
      firmaMinis = f;
      const v = d.vigilancia_novedad;
      if (v) {
        miniVig.replaceChildren(h('div', { class: 'k' }, 'Vigilancia · ' + (v.etiqueta || v.objetivo)),
          h('div', { class: 'v' }, v.texto, h('span', { class: 'nuevo' }, 'NUEVO')),
          h('div', { class: 's' }, [v.periodo, v.objetivo].filter(Boolean).join(' · ')),
          h('div', { class: 'fila' }, boton('⤓ Descargar este corte', async (ev) => {
            ev.currentTarget.disabled = true;
            try { await api('POST', 'vigilancias/' + v.vigilancia_id + '/descargar', { texto: v.texto }); toast('Descargando «' + v.texto + '»…'); }
            catch (e) { errorToast(e); ev.target.disabled = false; }
          }, 'chico primario', { 'data-descargar-corte': String(v.vigilancia_id) }), boton('Ver vigilancias', ir('vigilancia'), 'chico')));
      } else {
        miniVig.replaceChildren(h('div', { class: 'k' }, 'Vigilancia'), h('div', { class: 'v' }, 'Sin cortes nuevos'),
          h('div', { class: 's' }, 'Te aviso aquí en cuanto llegue uno.'),
          h('div', { class: 'fila' }, boton('↻ Revisar todas', async () => { try { await api('POST', 'vigilancias/revisar', {}); toast('Revisando todas las vigilancias activas…'); } catch (e) { errorToast(e); } }, 'chico')));
      }
      const co = d.correo_ultimo;
      if (co) {
        const partes = String(co.mensaje || '').split(/,\s*/);
        const dato = partes.slice().reverse().find((p) => /:\s*\S/.test(p) && !/^Lleg/.test(p)) || (co.resultado === 'ok' ? 'Revisado' : 'Con error');
        const archivo = (co.archivos || [])[0];
        miniCorreo.replaceChildren(h('div', { class: 'k' }, 'Correo · ' + co.nombre),
          h('div', { class: 'v' + (co.resultado === 'ok' ? '' : ' t-err') }, dato),
          h('div', { class: 's' }, [archivo ? nombreArchivo(archivo) : '', cuandoCorto(co.cuando)].filter(Boolean).join(' · ')),
          h('div', { class: 'fila' }, archivo ? boton('Abrir archivo', () => abrirArchivo(archivo, false), 'chico') : null,
            boton('↻ Revisar ahora', async () => { try { await api('POST', 'correo/busquedas/' + co.correo_id + '/revisar', { ver: false }); toast('Revisando «' + co.nombre + '»…'); } catch (e) { errorToast(e); } }, 'chico')));
      } else {
        miniCorreo.replaceChildren(h('div', { class: 'k' }, 'Correo'), h('div', { class: 'v' }, 'Sin revisiones todavía'),
          h('div', { class: 's' }, 'Busca correos, descarga sus adjuntos y copia sus datos.'), h('div', { class: 'fila' }, boton('✉ Ir a Correo', ir('correo'), 'chico')));
      }
      const prox = (d.proximas || []).slice(0, 4);
      miniProx.replaceChildren(h('div', { class: 'k' }, 'Próximas ejecuciones'),
        ...(prox.length ? prox.map((t) => h('div', { class: 'prox', title: (t.proxima || '') + (t.cuando_texto ? ' · ' + t.cuando_texto : '') },
          h('b', null, t.cuando ? cuandoCorto(t.cuando.replace('T', ' ')) : proximaCorta(t.proxima)), h('span', null, t.nombre),
          t.sin_tarea ? h('a', { href: t.correo_id ? '#/correo' : '#/vigilancia', class: 'chip aviso', title: 'Tiene horario pero no tiene tarea en Windows: no se revisará sola' }, 'sin tarea') : null))
          : [h('div', { class: 's' }, 'No hay nada programado. Usa «Programar…» en un reporte o en Vigilancia.')]));
    }
    function pintarSub() {
      const n = new Date();
      let f;
      try { f = n.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'short' }); } catch (e) { f = isoDia(n); }
      const t = d ? d.tareas_activas : 0;
      const sub = f + ' · ' + dos(n.getHours()) + ':' + dos(n.getMinutes()) + ' · ' + (t === 1 ? '1 tarea de Windows activa' : t + ' tareas de Windows activas');
      titulo('¿Qué quieres descargar hoy?', sub);
    }
    function pintarProgramados() {
      const lista = d.programados || [];
      cajaProg.classList.toggle('oculto', !lista.length);
      claveLista(listaProg, lista, (x) => x.clave, (x) => filaProgramado(x, actualizarPronto));
    }
    function pintar() {
      pintarKpis();
      pintarEnCurso(cajaCurso);
      pintarProgramados();
      pintarFilas();
      pintarFeed();
      pintarMinis();
      marcarNovedades((d.kpi || {}).novedades || 0);
    }
    let pedido = 0;
    const actualizar = actualizador(() => { pedido = Date.now(); return api('GET', 'inicio'); }, (x) => {
      d = x;
      if (x.externos) E.externos = x.externos;
      pintar();
      for (const [rid, y] of [...E.recien]) if (y.t < pedido) E.recien.delete(rid);   // (los datos ya lo traen)
      if (E.vista && E.vista.ctl === ctl) pintarSub();
    });
    const actualizarPronto = demorar(actualizar, 400);
    function evento(ev) {
      if (!d) return;
      if (['externo', 'trabajo', 'progreso', 'lote'].includes(ev.tipo)) pintarEnCurso(cajaCurso);      // v3.7
      if (ev.tipo === 'externo') { pintarKpis(); if (ev.termino) actualizarPronto(); return; }
      if (ev.tipo === '_curso') { pintarFilas(); pintarKpis(); if (ev.fin) actualizarPronto(); return; }
      if (ev.tipo === '_progreso') { pintarBarraFila(filas, ev.reporte_id); return; }
      if (ev.tipo === 'trabajo' && ev.estado === 'en_curso') {
        if (['ejecutar', 'lote', 'pagina', 'pagina_varias', 'filtros', 'vigilar', 'correo'].includes(ev.tipo_trabajo)) enVivo(ev.descripcion + ' empezó', 't-vivo', '', ev.reporte_id ? 'r' + ev.reporte_id : '');
        pintarKpis();
        return;
      }
      if (ev.tipo === 'trabajo') {
        if (ev.resumen && !['correo_prueba', 'correo_relacionados', 'pagina_opciones', 'actualizar_filtros', 'mapear', 'grabar'].includes(ev.tipo_trabajo)) {
          const cl = ev.estado === 'ok' ? 't-ok' : (ev.estado === 'detenido' ? 't-aviso' : 't-err');
          const clave = ev.reporte_id ? 'r' + ev.reporte_id : (ev.pagina_id ? 'p' + ev.pagina_id : (ev.correo_id ? 'c' + ev.correo_id : (ev.tipo_trabajo === 'correo' ? 'correo' : '')));
          enVivo(ev.resumen, cl, '', clave);
          if (ev.tipo_trabajo === 'lote' || ev.tipo_trabajo === 'correo') vivosFeed.correo = Date.now();
        }
        actualizarPronto();
        return;
      }
      if (ev.tipo === 'resultado' && (ev.archivos || []).length) {
        const clave = ev.reporte_id ? 'r' + ev.reporte_id : (ev.pagina_id ? 'p' + ev.pagina_id : '');
        enVivo('Archivo guardado', 't-ok', nombreArchivo(ev.archivos[0]) + (ev.archivos.length > 1 ? ' (+' + (ev.archivos.length - 1) + ')' : ''), clave);
        return;
      }
      if (ev.tipo === 'lote' && ev.fase === 'fin' && ev.reporte_id) { vivosFeed['r' + ev.reporte_id] = Date.now(); return; }
      if (ev.tipo === 'vigilancia') {
        if (ev.nuevas && ev.nuevas.length) enVivo('Vigilancia: ' + (ev.nuevas.length === 1 ? 'corte nuevo «' + ev.nuevas[0] + '»' : ev.nuevas.length + ' opciones nuevas: ' + ev.nuevas.join(', ')), 't-aviso', '', 'vig');
        actualizarPronto();
        return;
      }
      if (ev.tipo === 'correo') {
        vivosFeed.correo = Date.now();
        if (ev.busqueda_id) vivosFeed['c' + ev.busqueda_id] = Date.now();
        enVivo(ev.resumen || 'Correo revisado', ev.ok ? 't-ok' : 't-err', (ev.archivos || []).length ? nombreArchivo(ev.archivos[0]) : '', 'c' + (ev.busqueda_id || ''));
        return;
      }
      if (ev.tipo === 'aviso' && ev.texto) { enVivo(ev.texto, ev.aviso === 'clave_rechazada' ? 't-err' : 't-suave'); actualizarPronto(); return; }
      if (ev.tipo === 'aviso' && ev.aviso === 'clave_rechazada') { enVivo('La contraseña de «' + ev.host + '» fue rechazada', 't-err'); return; }
    }
    const ctl = { actualizar, evento };
    await actualizar();
    if (!d) throw new Error('el bot no respondió');
    pintarSub();
    setInterval(() => { if (E.vista && E.vista.ctl === ctl) pintarSub(); }, 30000);
    setInterval(() => { if (E.vista && E.vista.ctl === ctl && !cajaCurso.classList.contains('oculto')) pintarEnCurso(cajaCurso); }, 1000);
    return ctl;
  };

  // ------------------------------------------------------------------ Reportes
  RUTAS.reportes = async (c) => {
    let [r, aj, pags] = await Promise.all([api('GET', 'reportes'), api('GET', 'ajustes'), api('GET', 'paginas').catch(() => ({ paginas: [] }))]);
    E.ajustes = aj.ajustes;
    const marcados = new Set();
    // v3.2: «Sin abrir navegador (en segundo plano)» = lo contrario de «Ver mientras trabaja» (el ajuste general)
    const fondo = interruptorFondo(!aj.ajustes.ver_mientras_trabaja, 'sin-navegador-reportes', async (v) => {
      try { const r2 = await api('PUT', 'ajustes', { ajustes: { ver_mientras_trabaja: !v } }); E.ajustes = r2.ajustes; } catch (e) { errorToast(e); }
    });
    const ejecutar = (ids, nombre) => ejecutarReportes(ids, nombre, !fondo.valor());
    const buscar = h('input', { type: 'search', class: 'buscar-lista', placeholder: 'Filtrar por nombre o web…', 'aria-label': 'Filtrar los reportes por nombre o web' });
    const ul = h('ul', { class: 'filas', 'aria-label': 'Reportes guardados' });
    const meta = h('span', { class: 'meta' });
    function fila(x) {
      const est = estadoVisto(x);
      const enCurso = est === 'curso';
      const cur = E.curso.get(x.id);
      const casilla = h('input', { type: 'checkbox', 'aria-label': 'Elegir ' + x.nombre, checked: marcados.has(x.id) });
      casilla.addEventListener('change', () => { if (casilla.checked) marcados.add(x.id); else marcados.delete(x.id); });
      let sitio = '';
      try { sitio = x.url ? new URL(x.url).hostname : ''; } catch (e) { sitio = ''; }
      const det = enCurso ? ((cur && cur.texto) || 'Empezando…') : (x.resultado === 'error' && x.mensaje ? x.mensaje : (x.url || 'sin dirección'));
      return h('li', { class: 'fila-rep con-casilla', 'data-estado': est || 'nuevo', 'data-reporte-id': String(x.id) }, casilla,
        h('span', { class: 'punto ' + (est || 'nuevo'), role: 'img', 'aria-label': est ? ({ ok: 'bien', error: 'con error', detenido: 'detenido', curso: 'en curso' }[est] || est) : 'sin ejecutar' }),
        h('div', { class: 'nom' }, h('a', { href: '#/editor/' + x.id }, x.nombre), sitio ? h('span', { class: 'sitio' }, sitio) : null,
          x.vigilancia ? chip('vigilado', 'info') : null),
        h('div', { class: 'cuando' }, enCurso ? h('span', { class: 'pct' }, Math.round((cur && cur.pct) || 0) + ' %') : (x.ultima ? cuandoCorto(x.ultima) : 'nunca'), h('br'),
          enCurso ? 'en curso' : (x.resultado === 'ok' ? h('span', { class: 't-ok' }, 'bien') : (x.resultado === 'error' ? h('span', { class: 't-err' }, 'falló') : (x.resultado === 'detenido' ? h('span', { class: 't-aviso' }, 'detenido') : '—')))),
        h('div', { class: 'acc' }, chipFecha(x),
          boton('▶ ' + (enCurso ? 'En curso' : 'Ejecutar'), () => ejecutar([x.id], x.nombre), 'chico primario', { disabled: enCurso, 'aria-label': 'Ejecutar ' + x.nombre }),
          boton('⚙ Usar filtros', () => panelFiltros(x.id), 'chico sec'),
          boton('Editar pasos', () => { location.hash = '#/editor/' + x.id; }, 'chico sec'),
          boton('Duplicar', async () => { try { await api('POST', 'reportes/' + x.id + '/duplicar', {}); toast('Copia creada', 'ok'); actualizar(); } catch (e) { errorToast(e); } }, 'chico sec'),
          boton('Eliminar', async () => {
            if (await confirmar('Eliminar', '¿Mandar «' + x.nombre + '» a la papelera? (Se puede recuperar.)', 'Eliminar', true)) {
              try { await api('DELETE', 'reportes/' + x.id); marcados.delete(x.id); actualizar(); } catch (e) { errorToast(e); }
            }
          }, 'chico peligro sec')),
        h('div', { class: 'det' + (enCurso ? ' vivo' : (x.resultado === 'error' ? ' err' : '')), title: det }, det),
        enCurso ? h('div', { class: 'barra' }, h('i', { style: 'width:' + Math.max(3, (cur && cur.pct) || 0) + '%' })) : null);
    }
    function pintar() {
      const lista = r.reportes || [];
      const q = normalizar(buscar.value.trim());
      const vis = q ? lista.filter((x) => normalizar(x.nombre + ' ' + (x.url || '')).includes(q)) : lista;
      claveLista(ul, vis, (x) => x.id, fila, {
        firma: (x) => JSON.stringify([x, estadoVisto(x), marcados.has(x.id)]),
        destello: (x) => E.recien.has(x.id) && Date.now() - E.recien.get(x.id).t < 3000,
        vacio: () => h('li', { class: 'fila-vacia' }, lista.length ? 'Ningún reporte se llama así.' : 'No hay reportes guardados. Pulsa «Grabar nuevo» para enseñarle al bot el primero.') });
      for (const rid of E.curso.keys()) pintarBarraFila(ul, rid);
      meta.textContent = (q ? vis.length + ' de ' : '') + lista.length + (lista.length === 1 ? ' reporte' : ' reportes');
    }
    buscar.addEventListener('input', pintar);
    const actualizar = actualizador(() => api('GET', 'reportes'), (x) => {
      r = x;
      const ids = new Set((r.reportes || []).map((y) => y.id));
      for (const id of [...marcados]) if (!ids.has(id)) marcados.delete(id);
      pintar();
      api('GET', 'paginas').then((p) => { pags = p; pintarPaginas(); }).catch(() => {});
    });
    const actualizarPronto = demorar(actualizar, 400);
    async function papeleraYActualizar() { await papelera(actualizar); }
    c.appendChild(h('div', { class: 'barra-herr' },
      boton('● Grabar nuevo', () => { location.hash = '#/grabar'; }),
      boton('▶ Ejecutar seleccionados', () => { if (!marcados.size) { toast('Marca algún reporte', 'aviso'); return; } ejecutar([...marcados], 'los reportes elegidos'); }),
      boton('▶ Ejecutar todos', () => { const ids = (r.reportes || []).map((x) => x.id); if (ids.length) ejecutar(ids, 'todos'); }),
      boton('Papelera…', papeleraYActualizar), h('span', { class: 'espacio' }), fondo.caja));
    c.appendChild(h('section', { class: 'tarjeta' }, h('header', null, h('h2', null, 'Reportes guardados'), buscar, meta), ul));
    // v3.8: «Páginas» ya no es una sección: las que había guardadas siguen funcionando y se abren desde aquí
    const ulPag = h('ul', { class: 'lista' });
    const cajaPag = h('section', { class: 'panel oculto', 'data-paginas-guardadas': '1' }, h('h2', null, 'Páginas guardadas'), ulPag);
    function pintarPaginas() {
      const lista = (pags && pags.paginas) || [];
      cajaPag.classList.toggle('oculto', !lista.length);
      claveLista(ulPag, lista, (p) => p.id, (p) => h('li', { 'data-pagina-id': String(p.id) },
        h('div', { class: 'crece' }, h('div', null, h('a', { href: '#/paginas/' + p.id }, p.nombre), p.vigilada ? ' ' : null, p.vigilada ? chip('vigilada', 'info') : null,
          p.nuevas ? ' ' : null, p.nuevas ? chip(p.nuevas + ' nueva(s)', 'marca') : null), h('div', { class: 'sub' }, p.host || p.url || '')),
        p.resultado ? estadoChip(p.resultado) : null,
        boton('Abrir', () => { location.hash = '#/paginas/' + p.id; }, 'chico primario')));
    }
    c.appendChild(cajaPag);
    pintarPaginas();
    pintar();
    return {
      actualizar,
      evento(ev) {
        if (ev.tipo === '_curso') { pintar(); if (ev.fin) actualizarPronto(); return; }
        if (ev.tipo === '_progreso') { pintarBarraFila(ul, ev.reporte_id); return; }
        if (ev.tipo === 'trabajo' && ev.estado !== 'en_curso') actualizarPronto();
      },
    };
  };


  // ------------------------------------------------------------------ Usar filtros (v3.1)
  // Los filtros del reporte (listas «Elegir opción», «Seleccionar» y fechas) con todas sus opciones conocidas: elegir
  // otra (o varias) y descargar sin cambiar el reporte, guardarlo como predeterminado o volver a leer las opciones.
  async function panelFiltros(id, alCambiar) {
    const elecciones = {};            // paso -> {estrategia, valor} | {valores: [...]}
    const varias = new Set();         // pasos con «Elegir varias» activado
    const lectores = {};              // paso -> () => elección actual de sus controles
    const caja = h('div', { 'data-filtros': String(id), class: 'filtros' });
    const estado = h('div', { class: 'alerta oculto', role: 'status' });
    const confirmacion = h('div', { class: 'alerta aviso oculto' });
    let datos = null;
    let trabajoId = null;
    let cambiado = false;
    const pedir = async () => {
      try { datos = await api('POST', 'reportes/' + id + '/filtros', { elecciones }); } catch (e) { errorToast(e); return; }
      pintar();
    };
    const todas = () => { const r = {}; for (const [k, f] of Object.entries(lectores)) { const e = f(); if (e) r[k] = e; } return r; };
    const avisar = (texto, clase) => { estado.textContent = texto; estado.className = 'alerta ' + (clase || ''); };

    function chipsOpcion(o) {
      return [o.mas_reciente ? chip('más reciente', 'ok') : null, o.nueva ? chip('nueva', 'marca') : null,
              o.guardada ? chip('guardada (no está en la última lista)', 'aviso') : null,
              o.detalle ? h('span', { class: 'sub' }, o.detalle) : null];
    }
    function filaLista(f) {
      const sel = h('select', { 'aria-label': f.nombre });
      const etiqueta = (o) => (o.mas_reciente ? '★ ' : '') + o.texto + (o.nueva ? '  — nueva' : '');
      sel.appendChild(h('option', { value: '__mas_reciente' }, 'La más reciente' + (f.mas_reciente ? ' (hoy: ' + f.mas_reciente + ')' : '')));
      if (['primera', 'ultima', 'contiene', 'por_fecha'].includes(f.estrategia_guardada)) {
        sel.appendChild(h('option', { value: '__guardada' }, 'Como está guardado: ' + (E.ayuda && E.ayuda.estrategias ? E.ayuda.estrategias[f.estrategia_guardada] : f.estrategia_guardada) +
          (f.valor_guardado ? ' «' + f.valor_guardado + '»' : '')));
      }
      for (const o of f.opciones) sel.appendChild(h('option', { value: o.texto }, etiqueta(o)));
      const e = elecciones[f.paso];
      if (e && e.valores) sel.value = e.valores[0];
      else if (f.estrategia === 'mas_reciente') sel.value = '__mas_reciente';
      else if (f.estrategia === 'fija' && f.valor) sel.value = f.valor;
      else sel.value = '__guardada';
      if (!sel.value) sel.value = '__mas_reciente';
      const detalle = h('div', { class: 'fila' });
      const pintarDetalle = () => {
        const t = sel.value === '__mas_reciente' ? f.mas_reciente : (sel.value === '__guardada' ? f.actual : sel.value);
        const o = f.opciones.find((x) => x.texto === t);
        detalle.replaceChildren(...(o ? chipsOpcion(o).filter(Boolean) : []));
      };
      // varias opciones (una ejecución por opción)
      const multi = h('ul', { class: 'lista opciones-multi' + (varias.has(f.paso) ? '' : ' oculto') });
      const marcadas = new Set(e && e.valores ? e.valores : (f.actual ? [f.actual] : []));
      for (const o of f.opciones) {
        const cb = h('input', { type: 'checkbox', checked: marcadas.has(o.texto), 'aria-label': o.texto, value: o.texto });
        cb.addEventListener('change', () => { if (cb.checked) marcadas.add(o.texto); else marcadas.delete(o.texto); guardarEleccion(false); });
        multi.appendChild(h('li', null, cb, h('div', { class: 'crece' }, h('div', null, o.texto)), ...chipsOpcion(o)));
      }
      const casVarias = h('input', { type: 'checkbox', checked: varias.has(f.paso), 'aria-label': 'Elegir varias' });
      const leer = () => {
        if (varias.has(f.paso)) {
          const vals = f.opciones.map((o) => o.texto).filter((t) => marcadas.has(t));
          return vals.length ? { valores: vals } : null;
        }
        if (sel.value === '__mas_reciente') return { estrategia: 'mas_reciente', valor: '' };
        if (sel.value === '__guardada') return { estrategia: f.estrategia_guardada, valor: f.valor_guardado };
        return { valores: [sel.value] };
      };
      lectores[f.paso] = leer;
      const dependen = () => datos.filtros.some((g) => g.paso > f.paso && g.clase === 'lista');
      const guardarEleccion = (recargar) => {
        const v = leer();
        if (v) elecciones[f.paso] = v; else delete elecciones[f.paso];
        pintarDetalle();
        if (recargar && dependen()) pedir();          // las listas siguientes pueden depender de esta
      };
      sel.addEventListener('change', () => guardarEleccion(true));
      casVarias.addEventListener('change', () => {
        if (casVarias.checked) varias.add(f.paso); else varias.delete(f.paso);
        multi.classList.toggle('oculto', !casVarias.checked);
        sel.disabled = casVarias.checked;
        guardarEleccion(false);
      });
      sel.disabled = varias.has(f.paso);
      pintarDetalle();
      return [h('div', { class: 'fila' }, h('div', { class: 'crece' }, sel),
                f.opciones.length > 1 ? h('label', { class: 'interruptor' }, casVarias, 'Elegir varias') : null),
              detalle, multi];
    }
    function filaFecha(f) {
      // v3.6: calendario (fecha fija) o «cambia sola» (hoy, ayer, hace N días…) con el formato de la web
      const inp = h('input', { type: 'text', value: f.valor || '', 'aria-label': f.nombre });
      lectores[f.paso] = () => ({ estrategia: 'fija', valor: inp.value });
      inp.addEventListener('input', () => { elecciones[f.paso] = { estrategia: 'fija', valor: inp.value }; });
      return [campoFecha(inp, { formato: f.formato || null, conFecha: true, titulo: f.nombre })];
    }
    function cabecera(f) {
      const nombre = h('strong', null, f.nombre);
      const cab = h('div', { class: 'fila filtro-cab' }, nombre,
        f.vigilado ? chip('vigilado', 'info') : null, f.origen_nombre === 'numero' ? chip('sin nombre', 'aviso') : null,
        h('span', { class: 'sub' }, 'paso ' + f.numero), h('span', { class: 'espacio' }));
      const renombrar = boton('Renombrar', () => {
        const inp = h('input', { type: 'text', value: f.nombre, 'aria-label': 'Nombre del filtro' });
        const guardar = async () => {
          try { await api('POST', 'reportes/' + id + '/filtros/nombre', { paso: f.paso, nombre: inp.value }); cambiado = true; toast('Nombre guardado', 'ok'); pedir(); }
          catch (e) { errorToast(e); }
        };
        inp.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); guardar(); } });
        cab.replaceChildren(h('div', { class: 'crece' }, inp), boton('Guardar', guardar, 'chico primario'), boton('Cancelar', pintar, 'chico'));
        inp.focus();
      }, 'chico');
      cab.appendChild(renombrar);
      return cab;
    }
    function pintar() {
      for (const k of Object.keys(lectores)) delete lectores[k];
      if (!datos.filtros.length) {
        caja.replaceChildren(h('p', { class: 'vacio' }, 'Este reporte no tiene filtros (listas «Elegir opción» o fechas). En el editor usa «Convertir listas…» o «Mapear desde aquí».'));
        return;
      }
      caja.replaceChildren(...datos.filtros.map((f) => {
        const meta = f.clase === 'lista' ? (f.opciones.filter((o) => !o.guardada).length ?
          f.opciones.filter((o) => !o.guardada).length + ' opciones' + (f.cronologica ? ' (de la más reciente a la más antigua)' : '') +
          (f.actualizado ? ' · actualizado el ' + f.actualizado : '') + (f.fuente_texto ? ' (' + f.fuente_texto + ')' : '') :
          'Sin opciones conocidas todavía') : 'Fecha que se escribe: un día del calendario (fecha fija) o una que cambia sola (hoy, ayer, hace N días…).';
        return h('div', { class: 'filtro', 'data-paso': String(f.paso) }, cabecera(f),
          f.clase === 'lista' ? filaLista(f) : filaFecha(f),
          h('div', { class: 'ayuda' }, meta), f.nota ? h('div', { class: 'alerta ' + (f.nota_tipo === 'aviso' ? 'aviso' : '') }, f.nota) : null);
      }));
    }
    const descargar = async (confirmado) => {
      confirmacion.classList.add('oculto');
      try {
        const r = await api('POST', 'reportes/' + id + '/filtros/descargar', { elecciones: todas(), confirmar: !!confirmado,
          ver: !fondoFiltros.valor() });
        if (r.confirmar) {
          confirmacion.replaceChildren(h('span', null, r.mensaje + ' '), boton('Sí, ejecutar ' + r.n + ' veces', () => descargar(true), 'chico primario'), ' ',
            boton('Cancelar', () => confirmacion.classList.add('oculto'), 'chico'));
          confirmacion.classList.remove('oculto');
          return;
        }
        trabajoId = r.id; avisar('Descargando con los filtros elegidos…');
      } catch (e) { errorToast(e); }
    };
    const actualizar = async () => {
      try { const r = await api('POST', 'reportes/' + id + '/filtros/actualizar', { elecciones: todas() }); trabajoId = r.id; avisar('Leyendo las opciones de los filtros en la página (navegador oculto)…'); }
      catch (e) { errorToast(e); }
    };
    const predeterminado = async () => {
      try {
        const r = await api('POST', 'reportes/' + id + '/filtros/predeterminado', { elecciones: todas() });
        cambiado = true;
        toast('Guardado como predeterminado' + (r.cambios.length ? ': ' + r.cambios.join('; ') : ' (sin cambios en las opciones)') +
          '. La versión anterior queda en «Versiones».', 'ok', 9000);
        pedir();
      } catch (e) { errorToast(e); }
    };
    const oyente = (ev) => {
      if (ev.tipo === 'lote') { if (trabajoId) avisar('Ejecución ' + ev.n + ' de ' + ev.total + ': ' + ev.nombre); return; }
      if (ev.tipo === 'vigilancia' && ev.reporte_id === id) { pedir(); return; }
      if (!trabajoId || ev.trabajo !== trabajoId) return;
      if (ev.tipo === 'progreso') avisar((ev.i >= 0 ? 'Paso ' + (ev.i + 1) + ': ' : '') + (ev.texto || ''));
      if (ev.tipo === 'trabajo' && ev.estado !== 'en_curso') { avisar(ev.resumen || '', ev.estado === 'ok' ? 'ok' : 'error'); trabajoId = null; pedir(); }
    };
    try { datos = await api('GET', 'reportes/' + id + '/filtros'); } catch (e) { errorToast(e); return; }
    if (!E.ajustes) { try { E.ajustes = (await api('GET', 'ajustes')).ajustes; } catch (e) { /* por defecto */ } }
    const fondoFiltros = interruptorFondo(!(E.ajustes && E.ajustes.ver_mientras_trabaja), 'sin-navegador-filtros');
    abrirModal({ titulo: 'Filtros de «' + datos.nombre + '»', ancho: true,
      contenido: h('div', null, h('p', { class: 'ayuda' }, 'Elige cualquier opción de cada filtro (o varias: una descarga por opción) y pulsa «Descargar con estos filtros». ' +
        'El reporte guardado no cambia salvo que pulses «Guardar como predeterminado». Las opciones se actualizan solas con cada ejecución y con la vigilancia.'),
        confirmacion, caja, h('div', { class: 'fila' }, fondoFiltros.caja), estado),
      alCerrar: () => { if (E.oyenteModal === oyente) E.oyenteModal = null; if (cambiado && alCambiar) alCambiar(); },
      botones: [{ texto: 'Cerrar', accion: cerrarModal }, { texto: '↻ Actualizar opciones', accion: actualizar },
                { texto: 'Guardar como predeterminado', accion: predeterminado },
                { texto: '⤓ Descargar con estos filtros', clase: 'primario', accion: () => descargar(false) }] });
    E.oyenteModal = oyente;           // sobrevive a navegar() (que vacía E.oyentes al terminar cada trabajo)
    pintar();
  }

  async function papelera(alCambiar) {
    const cambio = () => { if (alCambiar) alCambiar(); else refrescarVista('reportes'); };
    let r;
    try { r = await api('GET', 'papelera'); } catch (e) { errorToast(e); return; }
    const lista = (r.reportes || []).length ? h('ul', { class: 'lista' }, r.reportes.map((x) => h('li', null,
      h('div', { class: 'crece' }, h('div', null, x.nombre), h('div', { class: 'sub' }, 'Eliminado el ' + x.eliminado)),
      boton('Recuperar', async () => { try { await api('POST', 'papelera/' + x.id + '/restaurar', {}); cerrarModal(); toast('«' + x.nombre + '» recuperado', 'ok'); cambio(); } catch (e) { errorToast(e); } }, 'chico'),
      boton('Borrar definitivamente', async () => {
        if (await confirmar('Borrar definitivamente', '«' + x.nombre + '» y su historial se borrarán para siempre. ¿Seguro?', 'Borrar', true)) {
          try { await api('DELETE', 'papelera/' + x.id, { confirmar: true }); cerrarModal(); cambio(); } catch (e) { errorToast(e); }
        }
      }, 'chico peligro')))) : h('p', { class: 'vacio' }, 'La papelera está vacía.');
    abrirModal({ titulo: 'Papelera', contenido: lista, botones: [{ texto: 'Cerrar', clase: 'primario', accion: cerrarModal }] });
  }

  // ------------------------------------------------------------------ Editor de pasos
  const CAMPOS = {
    abrir_url: ['url'], clic: ['selectores', 'objetivo', 'boton', 'doble'], escribir: ['selectores', 'objetivo', 'valor', 'fecha_directa'],
    tecla: ['selectores', 'objetivo', 'tecla'], seleccionar: ['selectores', 'objetivo', 'valor', 'etiqueta'],
    marcar: ['selectores', 'objetivo', 'marcado'], esperar_elemento: ['selectores', 'objetivo', 'estado'], esperar_texto: ['texto'],
    esperar_segundos: ['segundos'], descargar: ['selectores', 'objetivo', 'boton', 'doble', 'nombre', 'carpeta'],
    guardar_pagina: ['formato', 'nombre', 'carpeta'], pasar_raton: ['selectores', 'objetivo'],
    iniciar_sesion: ['sitio', 'campos', 'enviar'], elegir_opcion: ['selectores', 'filtro', 'objetivo', 'estrategia', 'valor'],
  };
  const CON_CARGA = ['abrir_url', 'clic', 'escribir', 'tecla', 'seleccionar', 'marcar', 'descargar', 'iniciar_sesion',
                     'esperar_elemento', 'esperar_texto', 'elegir_opcion'];
  const ETIQUETAS = { url: 'Dirección (URL)', selectores: 'Selectores (uno por línea; el primero que funcione)', objetivo: 'Nombre del elemento',
    boton: 'Botón del ratón', doble: 'Doble clic', valor: 'Texto', fecha_directa: 'Fecha escrita directamente', tecla: 'Tecla (Enter, Escape, Tab…)',
    etiqueta: 'Texto de la opción', marcado: 'Casilla marcada', estado: 'Esperar hasta que esté', texto: 'Texto que debe aparecer',
    segundos: 'Segundos', nombre: 'Guardar como (plantilla)', carpeta: 'Carpeta (vacío = la de descargas)', formato: 'Formato',
    sitio: 'Página (host)', estrategia: 'Qué opción elegir', filtro: 'Nombre del filtro (p. ej. «Elegir corte»)', nota: 'Nota', opcional: 'Opcional (si no aparece, sigue)',
    desactivado: 'Desactivado (no se ejecuta)', timeout: 'Tiempo máximo en segundos (vacío = automático)', pagina: 'Pestaña (1 = la principal)',
    esperar_carga: 'Esperar a que la página cargue después' };
  const SELECTS = { boton: ['izquierdo', 'derecho', 'medio'], estado: ['visible', 'oculto'], formato: ['pdf', 'html', 'csv'],
                    estrategia: ['fija', 'mas_reciente', 'primera', 'ultima', 'contiene', 'por_fecha'] };
  const BOOLS = ['doble', 'fecha_directa', 'marcado', 'opcional', 'desactivado'];
  const PLANTILLA = ['url', 'valor', 'texto', 'nombre', 'carpeta'];

  function vistaPrevia(inp, ctx) {
    const lbl = h('div', { class: 'ayuda' });
    let t = null;
    const act = () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        if (!/\{/.test(inp.value)) { lbl.textContent = ''; return; }
        const reporte = ctx && ctx.reporte ? ctx.reporte() : undefined;   // v3.5: {reporte} con el nombre de verdad
        try { const r = await api('POST', 'plantilla', { texto: inp.value, reporte }); lbl.textContent = r.error ? '⚠ ' + r.error : 'Vista previa: ' + r.vista; }
        catch (e) { lbl.textContent = ''; }
      }, 250);
    };
    inp.addEventListener('input', act);
    act();
    return lbl;
  }

  // ctx (v3.5, opcional): { reporte: () => nombre del reporte } para la vista previa de {reporte}.
  function dialogoPaso(paso, alAceptar, ctx) {
    const p = JSON.parse(JSON.stringify(paso));
    const controles = {};
    const form = h('div', { class: 'formulario' });
    let usarCalendario = null;            // v3.6: pasa el «Texto» de un paso Escribir al campo de fecha
    const add = (clave, control, ayuda, vista) => {
      form.appendChild(h('label', null, ETIQUETAS[clave] || clave));
      form.appendChild(ayuda ? h('div', null, vista || control, ayuda) : (vista || control));
      controles[clave] = control;
    };
    for (const clave of CAMPOS[p.tipo] || []) {
      if (clave === 'selectores') add(clave, h('textarea', { 'aria-label': ETIQUETAS[clave] }, (p.selectores || []).join('\n')));
      else if (clave === 'nombre' && p.tipo === 'descargar') {
        // v3.5: por defecto el archivo se llama como el REPORTE (nombre completo) + la fecha; el de la web es {nombre}
        const inp = h('input', { type: 'text', value: p.nombre || '', placeholder: '{nombre}{ext} (vacío = el nombre que da la web)', 'aria-label': ETIQUETAS.nombre, 'data-nombre-descarga': '1' });
        const poner = (v) => { inp.value = v; inp.dispatchEvent(new Event('input', { bubbles: true })); };
        add(clave, inp, h('div', null, vistaPrevia(inp, ctx),
          h('div', { class: 'ayuda' }, '{reporte} = el nombre completo del reporte (con sus espacios, comas y puntos); {nombre} = el nombre que le da la web al archivo (p. ej. «report_xls»); {ext} = su extensión (.xlsx, .csv…); {hoy:%Y-%m-%d} = la fecha de hoy. Lo normal: «{reporte} {hoy:%Y-%m-%d}{ext}».'),
          h('div', { class: 'fila' },
            boton('Nombre del reporte + fecha', () => poner('{reporte} {hoy:%Y-%m-%d}{ext}'), 'chico', { 'data-nombre-rapido': 'reporte' }),
            boton('Nombre que da la web', () => poner('{nombre}{ext}'), 'chico', { 'data-nombre-rapido': 'web' }))));
      } else if (clave === 'valor' && p.tipo === 'escribir') {
        // v3.6: si escribe una fecha (grabada desde un calendario, o con una plantilla o una fecha), con el calendario
        const inp = h('input', { type: 'text', value: p.valor || '', 'aria-label': ETIQUETAS.valor });
        const zona = h('div', { 'data-valor-escribir': '1' });
        usarCalendario = () => { if (!zona.querySelector('.campo-fecha')) zona.replaceChildren(campoFecha(inp, { conFecha: true, titulo: 'Fecha que se escribe' })); };
        const a = analizarFecha(p.valor);
        if (p.fecha_directa || a.modo === 'fija' || a.modo === 'relativa') usarCalendario();
        else zona.replaceChildren(inp, vistaPrevia(inp, ctx), h('div', null, boton('Es una fecha: elegirla en el calendario', () => usarCalendario(), 'chico enlace', { 'data-usar-calendario': '1' })));
        add(clave, inp, null, zona);
      } else if (clave === 'carpeta') {
        const inp = h('input', { type: 'text', value: p.carpeta || '', 'aria-label': ETIQUETAS.carpeta });
        add(clave, inp, vistaPrevia(inp, ctx), campoRuta(inp, { tipo: 'carpeta', titulo: 'Carpeta donde se guarda el archivo' }));
      }
      else if (clave === 'campos') {
        const filas = (p.campos || []).map((cmp, k) => {
          const inp = h('input', { type: 'text', value: cmp.tipo === 'clave' ? (cmp.secreto || '') : (cmp.valor || ''),
                                   'aria-label': cmp.etiqueta || cmp.clave });
          controles['campo_' + k] = inp;
          return h('div', null, h('div', { class: 'ayuda' }, (cmp.etiqueta || cmp.clave) + (cmp.tipo === 'clave' ? ' — nombre de la contraseña guardada' : '')), inp);
        });
        form.appendChild(h('label', null, 'Campos del formulario'));
        form.appendChild(h('div', null, filas.length ? filas : h('span', { class: 'ayuda' }, 'Sin campos grabados: el bot analiza la página.')));
      } else if (clave === 'enviar') {
        add('enviar', h('textarea', { 'aria-label': 'Botón para entrar' }, ((p.enviar || {}).selectores || []).join('\n')),
          h('div', { class: 'ayuda' }, 'Selectores del botón para entrar (vacío = pulsar Enter).'));
      } else if (SELECTS[clave]) {
        const s = h('select', { 'aria-label': ETIQUETAS[clave] }, SELECTS[clave].map((v) => h('option', { value: v }, clave === 'estrategia' && E.ayuda ? v + ' — ' + E.ayuda.estrategias[v] : v)));
        s.value = p[clave] || SELECTS[clave][0];
        add(clave, s);
      } else if (BOOLS.includes(clave)) {
        add(clave, h('input', { type: 'checkbox', checked: clave === 'marcado' ? p.marcado !== false : !!p[clave], 'aria-label': ETIQUETAS[clave] }));
      } else {
        const inp = h('input', { type: clave === 'segundos' ? 'number' : 'text', value: p[clave] === undefined ? (clave === 'segundos' ? 1 : '') : p[clave], 'aria-label': ETIQUETAS[clave] });
        add(clave, inp, PLANTILLA.includes(clave) ? vistaPrevia(inp, ctx) : null);
      }
    }
    if (usarCalendario && controles.fecha_directa) {
      controles.fecha_directa.addEventListener('change', () => { if (controles.fecha_directa.checked) usarCalendario(); });
    }
    form.appendChild(h('div', { class: 'ancho' }, h('hr')));
    add('nota', h('input', { type: 'text', value: p.nota || '' }));
    for (const b of ['opcional', 'desactivado']) add(b, h('input', { type: 'checkbox', checked: !!p[b] }));
    add('timeout', h('input', { type: 'number', value: p.timeout === undefined || p.timeout === null ? '' : p.timeout, min: '0' }));
    add('pagina', h('input', { type: 'number', value: (p.pagina || 0) + 1, min: '1' }));
    if (CON_CARGA.includes(p.tipo)) {
      const s = h('select', null, h('option', { value: '' }, 'según el reporte'), h('option', { value: 'si' }, 'sí'), h('option', { value: 'no' }, 'no'));
      s.value = p.esperar_carga === true ? 'si' : (p.esperar_carga === false ? 'no' : '');
      add('esperar_carga', s);
    }
    const error = h('div', { class: 'alerta error oculto' });
    const aceptar = async () => {
      const n = Object.assign({}, p);
      for (const [clave, ctl] of Object.entries(controles)) {
        if (clave.startsWith('campo_')) continue;
        if (clave === 'selectores') n.selectores = ctl.value.split('\n').map((x) => x.trim()).filter((x) => x);
        else if (clave === 'enviar') {
          const sels = ctl.value.split('\n').map((x) => x.trim()).filter((x) => x);
          n.enviar = sels.length ? Object.assign({}, p.enviar || {}, { selectores: sels }) : { tecla: 'Enter' };
          if (sels.length) delete n.enviar.tecla;
        } else if (clave === 'esperar_carga') n.esperar_carga = ctl.value === 'si' ? true : (ctl.value === 'no' ? false : null);
        else if (BOOLS.includes(clave)) n[clave] = ctl.checked;
        else if (clave === 'timeout') n.timeout = ctl.value === '' ? null : parseFloat(ctl.value);
        else if (clave === 'segundos') n.segundos = parseFloat(ctl.value || '0');
        else if (clave === 'pagina') n.pagina = Math.max(0, parseInt(ctl.value || '1', 10) - 1);
        else n[clave] = ctl.value;
      }
      if (p.campos) {
        n.campos = p.campos.map((cmp, k) => {
          const x = Object.assign({}, cmp); const v = controles['campo_' + k].value;
          if (x.tipo === 'clave') { delete x.valor; if (v.trim()) x.secreto = v.trim(); else delete x.secreto; } else x.valor = v;
          return x;
        });
      }
      if (n.esperar_carga === null) delete n.esperar_carga;
      if (n.timeout === null) delete n.timeout;
      try {
        const r = await api('POST', 'flujo/paso', { flujo: { pasos: [] }, paso: n });
        if (r.paso.problemas && r.paso.problemas.length) { error.textContent = r.paso.problemas.join('; '); error.classList.remove('oculto'); return; }
        cerrarModal();
        alAceptar(n);
      } catch (e) { error.textContent = e.message; error.classList.remove('oculto'); }
    };
    abrirModal({ titulo: 'Editar paso: ' + ((E.ayuda && E.ayuda.tipos[p.tipo]) || p.tipo), ancho: true, contenido: h('div', null, form, error),
      alEnter: aceptar, botones: [{ texto: 'Cancelar', accion: cerrarModal }, { texto: 'Aceptar', clase: 'primario', accion: aceptar }] });
  }

  RUTAS.editor = async (c, args, query) => {
    if (!E.ayuda) E.ayuda = await api('GET', 'ayuda');
    let id = args[0] && args[0] !== 'nuevo' ? parseInt(args[0], 10) : null;
    let flujo, nombre;
    if (id) {
      const r = await api('GET', 'reportes/' + id);
      flujo = r.flujo; nombre = r.nombre;
    } else {
      flujo = { version: 3, nombre: 'Nuevo reporte', url: '', variables: {}, opciones: Object.assign({}, E.ayuda.opciones_defecto), pasos: [] };
      nombre = 'Nuevo reporte';
    }
    titulo(nombre, id ? 'Reporte número ' + id : 'Reporte sin guardar');
    let sucio = false;
    let ejecutando = null;
    const marcar = () => { sucio = true; $('#subtitulo').textContent = (id ? 'Reporte número ' + id : 'Reporte sin guardar') + ' · cambios sin guardar'; };
    const inNombre = h('input', { type: 'text', value: nombre, 'aria-label': 'Nombre del reporte' });
    const inUrl = h('input', { type: 'url', value: flujo.url || '', 'aria-label': 'Dirección' });
    inNombre.addEventListener('input', marcar); inUrl.addEventListener('input', marcar);
    const cuerpo = h('tbody');
    const avisoPares = h('div', { class: 'alerta oculto' });
    const avisoNombres = h('div', { class: 'alerta oculto', 'data-aviso-nombres': '1' });
    const problemas = h('div', { class: 'alerta error oculto' });
    const ctxPaso = { reporte: () => inNombre.value.trim() || 'Nuevo reporte' };

    const op = flujo.opciones || {};
    const o = {
      navegador: h('select', null, h('option', { value: 'chrome' }, 'Chrome'), h('option', { value: 'msedge' }, 'Edge')),
      timeout_paso: h('input', { type: 'number', value: op.timeout_paso, min: '1' }),
      timeout_descarga: h('input', { type: 'number', value: op.timeout_descarga, min: '10' }),
      pausa_entre_pasos: h('input', { type: 'number', value: op.pausa_entre_pasos, step: '0.1', min: '0' }),
      carpeta_descargas: h('input', { type: 'text', value: op.carpeta_descargas || '' }),
      si_existe: h('select', null, h('option', { value: 'numerar' }, 'numerar «nombre (2)»'), h('option', { value: 'sobrescribir' }, 'sobrescribir')),
      recuperacion_automatica: h('input', { type: 'checkbox', checked: op.recuperacion_automatica !== false }),
      esperar_carga: h('input', { type: 'checkbox', checked: op.esperar_carga !== false }),
      variables: h('input', { type: 'text', value: Object.entries(flujo.variables || {}).map(([k, v]) => k + '=' + v).join('; '), placeholder: 'cliente=Acme; mes=octubre' }),
    };
    o.navegador.value = op.navegador || 'chrome'; o.si_existe.value = op.si_existe || 'numerar';
    const rd = op.repetir_dias || {};
    const dias = {
      modo: h('select', null, h('option', { value: 'no' }, 'No repetir'), Object.entries(E.ayuda.modos_dias).map(([k, v]) => h('option', { value: k }, v))),
      desde: h('input', { type: 'text', value: rd.desde || '', 'aria-label': 'Repetir desde el día' }),
      hasta: h('input', { type: 'text', value: rd.hasta || '', 'aria-label': 'Repetir hasta el día' }),
      n: h('input', { type: 'number', value: rd.n || 7, min: '1', max: '366' }),
    };
    dias.modo.value = rd.modo || 'no';
    // v3.6: los días de «Repetir por días» con el calendario (fechas fijas AAAA-MM-DD, como antes)
    const filaDias = h('div', { class: 'fila', 'data-repetir-desde-hasta': '1' },
      campoFecha(dias.desde, { iso: true, vacio: 'Desde…', titulo: 'Repetir desde el día' }), h('span', { class: 'sub' }, 'hasta'),
      campoFecha(dias.hasta, { iso: true, vacio: 'Hasta… (= el mismo día)', titulo: 'Repetir hasta el día' }));
    const infoDias = h('div', { class: 'ayuda' });
    Object.values(o).concat(Object.values(dias)).forEach((x) => { x.addEventListener('change', () => { marcar(); refrescar(); }); });

    // v3.7: «Archivo descargado»: el nombre de cada paso que guarda un archivo (es el mismo dato que «Guardar como» al
    // editar el paso) y la carpeta del reporte, con «Se guardará como: …».  La extensión se pone sola.
    const archivoNombres = h('div', { class: 'formulario', 'data-archivo-nombres': '1' });
    let vistasArchivo = [];
    const actVistas = () => vistasArchivo.forEach((v) => v.act());
    o.carpeta_descargas.setAttribute('aria-label', 'Carpeta');
    o.carpeta_descargas.addEventListener('input', actVistas);
    inNombre.addEventListener('input', actVistas);
    function pintarArchivo() {
      if (archivoNombres.contains(document.activeElement)) return;          // no se repinta mientras se escribe
      const idx = flujo.pasos.map((p, i) => i).filter((i) => ['descargar', 'guardar_pagina'].includes(flujo.pasos[i].tipo) && !flujo.pasos[i].desactivado);
      const nDesc = idx.filter((i) => flujo.pasos[i].tipo === 'descargar').length;
      vistasArchivo = [];
      if (!idx.length) {
        archivoNombres.replaceChildren(h('label', null, 'Nombre del archivo'), h('div', { class: 'ayuda', 'data-sin-descargas': '1' },
          'Este reporte todavía no descarga ningún archivo. Cuando tenga un paso «Descargar» (al grabarlo, al crear los pasos desde «Mapear página» o con «Insertar paso»), aquí podrás ponerle nombre.'));
        return;
      }
      archivoNombres.replaceChildren(...idx.map((i) => {
        const p = flujo.pasos[i];
        const descarga = p.tipo === 'descargar';
        const que = (p.objetivo || '').trim();
        const etiqueta = idx.length === 1 ? 'Nombre del archivo' : 'Nombre del archivo del paso ' + (i + 1) + (que ? ' («' + que + '»)' : (descarga ? ' (Descargar)' : ' (Guardar página)'));
        const inp = h('input', { type: 'text', value: descarga ? sinExt(p.nombre) : (p.nombre || ''), 'aria-label': etiqueta, 'data-nombre-archivo': String(i),
          placeholder: descarga ? '(vacío = el nombre que da la web)' : 'Pagina_{hoy:%Y-%m-%d}' });
        const vista = vistaArchivo(() => {
          const q = flujo.pasos[i] || p;
          return { archivo: q.tipo, texto: inp.value, reporte: ctxPaso.reporte(), variables: flujo.variables || {}, carpeta: o.carpeta_descargas.value.trim(),
            subcarpeta: q.carpeta || '', formato: q.formato || 'html' };
        });
        vistasArchivo.push(vista);
        inp.addEventListener('input', () => {
          if (!flujo.pasos[i]) return;
          flujo.pasos[i].nombre = descarga ? conExt(inp.value) : inp.value.trim();
          marcar(); vista.act();
        });
        inp.addEventListener('change', () => refrescar());
        return [h('label', null, etiqueta), h('div', null, inp, vista.el,
          p.carpeta ? h('div', { class: 'ayuda' }, 'Este paso tiene su propia carpeta: «' + p.carpeta + '» (se cambia con «Editar» en el paso).') : null,
          descarga ? campoNombreArchivo(inp, { defecto: nDesc > 1 ? NOMBRE_ARCHIVO_VARIAS : NOMBRE_ARCHIVO_DEFECTO }) : null)];
      }).flat(), h('div', { class: 'ancho ayuda' }, 'Escribe el nombre sin la extensión (.xlsx, .csv, .pdf…): se pone sola. Se puede usar {reporte} = el nombre del reporte, {hoy:%Y-%m-%d} = la fecha de hoy, {ayer:%d-%m-%Y}, {nombre} = el nombre que le da la web y las variables del reporte.'));
    }

    function leerFormulario() {
      flujo.nombre = inNombre.value.trim() || 'Nuevo reporte';
      flujo.url = inUrl.value.trim();
      const ops = Object.assign({}, flujo.opciones || {});
      ops.navegador = o.navegador.value; ops.timeout_paso = parseFloat(o.timeout_paso.value || '60');
      ops.timeout_descarga = parseFloat(o.timeout_descarga.value || '600'); ops.pausa_entre_pasos = parseFloat(o.pausa_entre_pasos.value || '0');
      ops.carpeta_descargas = o.carpeta_descargas.value.trim(); ops.si_existe = o.si_existe.value;
      ops.recuperacion_automatica = o.recuperacion_automatica.checked; ops.esperar_carga = o.esperar_carga.checked;
      const m = dias.modo.value;
      ops.repetir_dias = m === 'no' ? null : { modo: m, desde: dias.desde.value, hasta: dias.hasta.value || dias.desde.value, n: parseInt(dias.n.value || '1', 10) };
      flujo.opciones = ops;
      const vars = {};
      o.variables.value.split(';').forEach((par) => { const i = par.indexOf('='); if (i > 0) vars[par.slice(0, i).trim()] = par.slice(i + 1).trim(); });
      flujo.variables = vars;
      filaDias.classList.toggle('oculto', m !== 'fijo');
      dias.n.parentElement.classList.toggle('oculto', m !== 'ultimos');
    }

    async function refrescar() {
      leerFormulario();
      let r;
      try { r = await api('POST', 'flujo/describir', { flujo }); } catch (e) { errorToast(e); return; }
      E.pasosTotal = r.pasos.length;
      cuerpo.replaceChildren(...r.pasos.map((p, i) => filaPaso(p, i, r.pasos.length)));
      if (!r.pasos.length) cuerpo.appendChild(h('tr', null, h('td', { colspan: '5', class: 'vacio' }, 'Sin pasos. Graba el reporte o inserta pasos.')));
      problemas.textContent = (r.problemas || []).join(' · ');
      problemas.classList.toggle('oculto', !(r.problemas || []).length);
      avisoPares.replaceChildren();
      if ((r.pares || []).length) {
        avisoPares.appendChild(h('span', null, 'Hay ' + r.pares.length + ' lista(s) grabadas como «clic para abrir + clic en una opción». Conviértelas en un paso «Elegir opción» para poder elegir «la más reciente» o vigilarlas. '));
        avisoPares.appendChild(boton('Convertir listas…', convertir, 'chico'));
      }
      avisoPares.classList.toggle('oculto', !(r.pares || []).length);
      // v3.5: descargas que se guardan con el nombre fijo que da la web («report_xls (6).xlsx»)
      const nw = r.nombres_web || [];
      avisoNombres.replaceChildren();
      if (nw.length) {
        avisoNombres.appendChild(h('span', null, (nw.length === 1 ? 'El paso ' + (nw[0] + 1) + ' guarda' : 'Los pasos ' + nw.map((i) => i + 1).join(', ') + ' guardan') +
          ' el archivo con el nombre fijo que le da la web («' + (flujo.pasos[nw[0]].nombre || '') + '»): todos los archivos se llaman igual. '));
        avisoNombres.appendChild(boton('Usar el nombre del reporte', usarNombreReporte, 'chico primario', { 'data-usar-nombre-reporte': '1' }));
      }
      avisoNombres.classList.toggle('oculto', !nw.length);
      infoDias.textContent = r.dias && r.dias.length ? 'Se ejecutará ' + r.dias.length + ' veces: del ' + r.dias[0] + ' al ' + r.dias[r.dias.length - 1] +
        '. Usa {fecha} o {fecha:%d/%m/%Y} en los campos de fecha y en el nombre del archivo.' : '';
      pintarArchivo();
    }

    function filaPaso(p, i, total) {
      const clase = p.desactivado ? 'desactivado' : '';
      return h('tr', { class: clase, 'data-indice': String(i) }, h('td', null, String(i + 1)),
        h('td', null, p.accion, p.opcional ? ' ' : null, p.opcional ? chip('opcional') : null, p.auto ? ' ' : null, p.auto ? chip('automático', 'info') : null),
        h('td', { class: 'detalle', title: p.descripcion }, p.detalle || '', (p.problemas || []).length ? h('div', { class: 'problema' }, p.problemas.join('; ')) : null),
        h('td', null, p.nota ? h('span', { class: 'ayuda' }, p.nota) : ''),
        h('td', { class: 'acciones' },
          boton('↑', () => mover(i, -1), 'chico', { 'aria-label': 'Subir', disabled: i === 0 }),
          boton('↓', () => mover(i, 1), 'chico', { 'aria-label': 'Bajar', disabled: i === total - 1 }), ' ',
          boton('Editar', () => dialogoPaso(flujo.pasos[i], (n) => { flujo.pasos[i] = n; marcar(); refrescar(); }, ctxPaso), 'chico'), ' ',
          boton(p.desactivado ? 'Activar' : 'Desactivar', () => { flujo.pasos[i].desactivado = !flujo.pasos[i].desactivado; marcar(); refrescar(); }, 'chico'), ' ',
          boton('Insertar debajo', () => insertar(i + 1), 'chico'), ' ',
          boton('✕', async () => { if (await confirmar('Borrar paso', '¿Borrar el paso ' + (i + 1) + ' («' + p.descripcion + '»)?', 'Borrar', true)) { flujo.pasos.splice(i, 1); marcar(); refrescar(); } }, 'chico peligro', { 'aria-label': 'Borrar paso' })));
    }
    async function usarNombreReporte() {
      leerFormulario();
      try {
        const res = await api('POST', 'flujo/usar_nombre_reporte', { flujo });
        flujo = res.flujo; marcar(); refrescar();
        toast(res.cambios.length + ' descarga(s) se guardarán como «' + flujo.nombre + ' ' + new Date().toISOString().slice(0, 10) + '…». Pulsa Guardar.', 'ok', 9000);
      } catch (e) { errorToast(e); }
    }
    function mover(i, d) {
      const j = i + d;
      if (j < 0 || j >= flujo.pasos.length) return;
      [flujo.pasos[i], flujo.pasos[j]] = [flujo.pasos[j], flujo.pasos[i]];
      marcar(); refrescar();
    }
    function insertar(pos) {
      const tipo = h('select', { 'aria-label': 'Tipo de paso' }, Object.entries(E.ayuda.tipos).map(([k, v]) => h('option', { value: k }, v)));
      tipo.value = 'esperar_elemento';
      abrirModal({ titulo: 'Insertar paso', contenido: h('div', null, h('p', null, '¿Qué tipo de paso?'), tipo), botones: [
        { texto: 'Cancelar', accion: cerrarModal },
        { texto: 'Siguiente', clase: 'primario', accion: () => {
          const base = { tipo: tipo.value };
          if (tipo.value === 'esperar_segundos') base.segundos = 5;
          if (tipo.value === 'guardar_pagina') { base.formato = 'pdf'; base.nombre = 'Pagina_{hoy:%Y-%m-%d}'; }
          if (tipo.value === 'elegir_opcion') base.estrategia = 'mas_reciente';
          if (tipo.value === 'abrir_url') base.url = inUrl.value;
          if (tipo.value === 'descargar') base.nombre = '{reporte} {hoy:%Y-%m-%d}{ext}';
          dialogoPaso(base, (n) => { flujo.pasos.splice(pos, 0, n); marcar(); refrescar(); }, ctxPaso);
        } }] });
    }
    async function convertir() {
      leerFormulario();
      const r = await api('POST', 'flujo/describir', { flujo });
      const filas = r.pares.map(([i, j, t]) => {
        const s = h('select', { 'aria-label': 'Estrategia' }, ['fija', 'mas_reciente', 'primera', 'ultima'].map((v) => h('option', { value: v }, E.ayuda.estrategias[v])));
        const cb = h('input', { type: 'checkbox', checked: true, 'aria-label': 'Convertir' });
        return { i, s, cb, fila: h('li', null, cb, h('div', { class: 'crece' }, 'Pasos ' + (i + 1) + ' y ' + (j + 1) + ': «' + t + '»'), s) };
      });
      abrirModal({ titulo: 'Convertir listas en «Elegir opción»', ancho: true, contenido: h('div', null,
        h('p', { class: 'ayuda' }, 'Cada par «clic para abrir la lista + clic en una opción» pasa a ser un único paso «Elegir opción». Elige qué opción debe tomar el bot (p. ej. «la más reciente» para un corte semanal).'),
        h('ul', { class: 'lista' }, filas.map((f) => f.fila))), botones: [{ texto: 'Cancelar', accion: cerrarModal }, { texto: 'Convertir', clase: 'primario', accion: async () => {
          const pares = filas.filter((f) => f.cb.checked).map((f) => f.i);
          const est = {}; filas.forEach((f) => { est[f.i] = f.s.value; });
          try {
            const res = await api('POST', 'flujo/convertir_listas', { flujo, pares, estrategias: est });
            flujo = res.flujo; cerrarModal(); marcar(); refrescar(); toast(res.mensajes.length + ' lista(s) convertidas. Pulsa Guardar.', 'ok');
          } catch (e) { errorToast(e); }
        } }] });
    }
    async function guardar() {
      leerFormulario();
      try {
        if (id) await api('PUT', 'reportes/' + id, { flujo });
        else { const r = await api('POST', 'reportes', { flujo }); id = r.id; history.replaceState(null, '', '#/editor/' + id); }
        sucio = false;
        titulo(flujo.nombre, 'Reporte número ' + id + ' · guardado');
        toast('Reporte guardado', 'ok');
        return true;
      } catch (e) { errorToast(e); return false; }
    }
    async function ejecutar() {
      leerFormulario();
      try { const t = await api('POST', 'ejecutar', { flujo, reporte_id: id, ver: E.ajustes ? E.ajustes.ver_mientras_trabaja : undefined }); ejecutando = t.id; toast('Ejecutando «' + flujo.nombre + '»…'); }
      catch (e) { errorToast(e); }
    }
    E.oyentes.push((ev) => {
      if (ev.tipo === 'trabajo' && ev.estado === 'en_curso' && ev.tipo_trabajo === 'ejecutar' && ev.descripcion === 'Ejecutar «' + flujo.nombre + '»') {
        ejecutando = ev.trabajo; cuerpo.querySelectorAll('tr').forEach((tr) => { tr.classList.remove('actual', 'ok', 'error'); });
      }
      if (ev.tipo !== 'progreso' || !ejecutando || ev.trabajo !== ejecutando) return;
      const tr = cuerpo.querySelector('tr[data-indice="' + ev.i + '"]');
      if (!tr) return;
      if (ev.estado === 'inicio') { cuerpo.querySelectorAll('tr.actual').forEach((x) => x.classList.remove('actual')); tr.classList.add('actual'); }
      else if (ev.estado === 'ok') { tr.classList.remove('actual'); tr.classList.add('ok'); }
      else if (ev.estado === 'error') { tr.classList.remove('actual'); tr.classList.add('error'); }
    });
    const ef = (t, ctl) => [h('label', null, t), ctl];
    c.appendChild(h('div', { class: 'barra-herr' },
      boton('Guardar', guardar, 'primario'), boton('▶ Ejecutar', ejecutar),
      boton('Convertir listas…', convertir), boton('⚙ Usar filtros', async () => {
        if (!id) { toast('Guarda primero el reporte', 'aviso'); return; }
        if (sucio && !(await guardar())) return;
        panelFiltros(id, () => navegar());
      }), boton('⌖ Mapear desde aquí', async () => {
        if (!id) { toast('Guarda primero el reporte', 'aviso'); return; }
        if (sucio && !(await guardar())) return;
        location.hash = '#/mapear?reporte=' + id;
      }), boton('◎ Vigilar', () => { location.hash = '#/vigilancia'; }), boton('Programar…', () => {
        if (!id) { toast('Guarda primero el reporte', 'aviso'); return; }
        programarReporte(id, flujo.nombre);
      }), h('span', { class: 'espacio' }),
      boton('Volver a Reportes', async () => { if (!sucio || await confirmar('Cambios sin guardar', 'Hay cambios sin guardar. ¿Salir igualmente?', 'Salir')) location.hash = '#/reportes'; })));
    c.appendChild(panel(null, h('div', { class: 'formulario' }, ef('Nombre del reporte', inNombre), ef('Dirección (URL)', inUrl)),
      // v3.7: el nombre y la carpeta de lo que se descarga, a la vista (antes solo dentro de cada paso «Descargar»)
      h('details', { class: 'opciones', open: true, 'data-archivo-descargado': '1' }, h('summary', null, 'Archivo descargado (nombre y carpeta)'),
        archivoNombres,
        h('div', { class: 'formulario', style: 'margin-top:10px' },
          ef('Carpeta', h('div', null, campoRuta(o.carpeta_descargas, { titulo: 'Carpeta de descargas del reporte' }),
            h('div', { class: 'ayuda' }, 'Vacío = la carpeta de descargas del bot (la ruta exacta sale en «Se guardará como»).'))),
          ef('Si el archivo ya existe', o.si_existe))),
      h('details', { class: 'opciones' }, h('summary', null, 'Opciones del reporte (tiempos, navegador, repetir por días)'),
        h('div', { class: 'formulario' }, ef('Navegador', o.navegador), ef('Tiempo máximo por paso (s)', o.timeout_paso),
          ef('Espera máxima de descargas/reportes (s)', o.timeout_descarga), ef('Pausa entre pasos (s)', o.pausa_entre_pasos),
          ef('Recuperación automática de menús', o.recuperacion_automatica), ef('Esperar a que la página cargue', o.esperar_carga),
          ef('Variables', o.variables), ef('Repetir por días', dias.modo), h('label', null, 'Desde / hasta'),
          filaDias, h('label', null, 'Número de días'), h('div', null, dias.n),
          h('div', { class: 'ancho' }, infoDias)))));
    c.appendChild(avisoPares);
    c.appendChild(avisoNombres);
    c.appendChild(problemas);
    c.appendChild(panel(h('span', null, 'Pasos'), h('div', { class: 'barra-herr' }, boton('+ Insertar paso al final', () => insertar(flujo.pasos.length))),
      h('div', { class: 'envoltorio-tabla' }, h('table', { class: 'tabla' }, h('thead', null, h('tr', null, h('th', null, 'Nº'),
        h('th', null, 'Acción'), h('th', null, 'Detalle'), h('th', null, 'Nota'), h('th', null, ''))), cuerpo))));
    await refrescar();
  };

  // v3.4: «Programar…» con el editor «Cuándo» (días, varias horas, horarios distintos por día, cada N horas, mensual…)
  async function programarReporte(id, nombre) {
    let g = {};
    try { g = await api('GET', 'reportes/' + id + '/programar'); } catch (e) { g = {}; }
    const ed = editorCuando(g.guardada || { reglas: [reglaPorDefecto('semanal', { horas: ['07:00'] })] }, { textoNunca: 'Sin programar (solo cuando pulse «Ejecutar»)' });
    abrirModal({ titulo: 'Programar «' + nombre + '»', ancho: true, contenido: h('div', { 'data-modal-programar': 'reporte' },
      h('p', { class: 'ayuda' }, 'Elige cuándo se ejecuta. Se crea una tarea en el Programador de tareas de Windows que ejecuta el reporte (en segundo plano o en vivo: lo eliges en «Avisos y vista»; con tu usuario y solo con la sesión de Windows iniciada): es la tarea la que hace que se ejecute solo. Para «cada día descargar el día anterior» usa {ayer} en el campo de fecha.'),
      g.existe ? h('div', { class: 'alerta ok' }, 'Ya tiene tarea en Windows: ' + (g.descripcion || '') + '. Si la cambias, se sustituye.') : h('div', { class: 'alerta aviso' }, 'Todavía no tiene tarea en Windows: no se ejecuta solo.'),
      ed.caja),
      botones: [{ texto: 'Cancelar', accion: cerrarModal },
        ...(g.existe ? [{ texto: 'Quitar la tarea de Windows', clase: 'peligro', accion: () => quitarTareaWindows('reportes/' + id + '/quitar_tarea') }] : []),
        { texto: 'Ver lo que se creará y crear…', clase: 'primario', accion: async () => {
          const p = ed.leer();
          if (!p.reglas.length) { toast('Elige cuándo se ejecuta (días y horas)', 'aviso'); return; }
          const v = await ed.comprobar();
          if (v && !v.valida) { toast(v.error, 'error'); return; }
          await crearTareaWindows('reportes/' + id + '/programar', { programacion: p }, 'Programar «' + nombre + '»');
        } }] });
  }

  // ------------------------------------------------------------------ v3.2: «Sin abrir navegador»
  const AYUDA_FONDO = 'El bot hace todo por detrás, sin abrir ninguna ventana del navegador: puedes seguir trabajando mientras tanto. ' +
    'Por dentro sigue usando un navegador (Chrome o Edge) invisible. Si la página pide iniciar sesión o la contraseña falla, la pregunta ' +
    'aparece aquí, en el bot. Desmárcalo si quieres ver lo que hace («Ver mientras trabaja»).';
  function interruptorFondo(inicial, id, alCambiar) {
    const cb = h('input', { type: 'checkbox', checked: !!inicial, id, 'data-fondo': '1' });
    if (alCambiar) cb.addEventListener('change', () => alCambiar(cb.checked));
    const caja = h('label', { class: 'interruptor fondo', for: id, title: AYUDA_FONDO }, cb,
      h('span', null, 'Sin abrir navegador (en segundo plano)'), h('span', { class: 'info', 'aria-hidden': 'true' }, 'ⓘ'),
      h('span', { class: 'solo-lector' }, AYUDA_FONDO));
    return { caja, cb, valor: () => cb.checked };
  }
  const NOMBRE_TIPO_FILTRO = { pestana: 'Pestaña', lista: 'Lista', lista_nativa: 'Lista', fecha: 'Fecha', texto: 'Texto', casilla: 'Casilla' };

  // ------------------------------------------------------------------ v3.2: Páginas
  RUTAS.paginas = async (c, args) => {
    E.enFormularioPagina = false;
    if (args[0]) { await formularioPagina(c, parseInt(args[0], 10)); return; }
    location.hash = '#/reportes';      // v3.8: ya no es una sección: las páginas guardadas se abren desde Reportes
  };

  async function formularioPagina(c, id) {
    if (!E.ayuda) E.ayuda = await api('GET', 'ayuda');
    E.enFormularioPagina = true;
    let v = await api('GET', 'paginas/' + id);
    const varias = new Set();          // filtros con «Elegir varias»
    const lectores = {};               // id del filtro -> () => elección actual
    const trayendo = new Set();        // filtros cuyas opciones se están trayendo de la página
    const pedidos = new Set();         // combinaciones ya pedidas (no se piden dos veces)
    let trabajoId = null;
    let pendienteTraer = null;
    let cambioPadre = false;
    const form = h('div', { class: 'pagina-form filtros' });
    const problemas = h('div', { class: 'alerta error oculto' });
    const estado = h('div', { class: 'alerta oculto', role: 'status' });
    const confirmacion = h('div', { class: 'alerta aviso oculto' });
    const archivos = h('ul', { class: 'lista archivos' });
    const favs = h('ul', { class: 'lista' });
    const vigCaja = h('div');
    const configCaja = h('div');
    const historialCaja = h('div');
    const fondo = interruptorFondo(v.sin_navegador, 'sin-navegador-pagina');
    const avisar = (t, cl) => { estado.textContent = t || ''; estado.className = 'alerta ' + (cl || ''); };
    const todas = () => { const r = {}; for (const [k, f] of Object.entries(lectores)) { const e = f(); if (e) r[k] = e; } return r; };
    const dependientes = (fid) => v.filtros.filter((g) => (g.depende_de || []).includes(fid));

    async function recargar() {
      try { v = await api('POST', 'paginas/' + id + '/formulario', { seleccion: todas() }); } catch (e) { errorToast(e); return; }
      pintarFormulario();
      if (cambioPadre) {
        for (const f of v.filtros) {
          if (!f.desconocida || trayendo.has(f.id)) continue;
          const clave = f.id + '|' + JSON.stringify((f.depende_de || []).map((k) => todas()[k]));
          if (pedidos.has(clave)) continue;
          pedidos.add(clave);
          traer(f.id);
          break;
        }
      }
    }
    async function traer(fid) {
      trayendo.add(fid);
      pintarFormulario();
      try {
        const r = await api('POST', 'paginas/' + id + '/traer', { seleccion: todas(), filtro: fid });
        trabajoId = r.id;
        avisar('Trayendo las opciones de la página (por detrás, sin abrir navegador)…');
      } catch (e) {
        trayendo.delete(fid);
        pendienteTraer = fid;
        avisar('Hay otro trabajo en curso: las opciones se traerán cuando termine. (' + e.message + ')', 'aviso');
        pintarFormulario();
      }
    }
    const cambio = (f) => { if (dependientes(f.id).length) { cambioPadre = true; recargar(); } };

    function chipsOpcion(o) {
      return [o.mas_reciente ? chip('más reciente', 'ok') : null, o.nueva ? chip('nueva', 'marca') : null,
              o.detalle ? h('span', { class: 'sub' }, o.detalle) : null];
    }
    function filaLista(f) {
      const e = f.eleccion || {};
      const s = h('select', { 'aria-label': f.nombre });
      if (f.tipo !== 'pestana' && (f.cronologica || e.estrategia === 'mas_reciente')) {
        s.appendChild(h('option', { value: '__mas_reciente' }, 'La más reciente' + (f.mas_reciente ? ' (hoy: ' + f.mas_reciente + ')' : '')));
      }
      if (['primera', 'ultima', 'contiene', 'por_fecha'].includes(e.estrategia)) {
        s.appendChild(h('option', { value: '__estrategia' }, ((E.ayuda && E.ayuda.estrategias[e.estrategia]) || e.estrategia) + (e.valor ? ' «' + e.valor + '»' : '')));
      }
      for (const o of f.opciones) s.appendChild(h('option', { value: o.texto }, (o.mas_reciente ? '★ ' : '') + o.texto + (o.nueva ? '  · nueva' : '')));
      if (e.valores) s.value = e.valores[0];
      else if (e.estrategia === 'mas_reciente') s.value = '__mas_reciente';
      else if (e.estrategia === 'fija') s.value = e.valor;
      else s.value = '__estrategia';
      if (s.selectedIndex < 0 && s.options.length) s.selectedIndex = 0;
      const detalle = h('div', { class: 'fila' });
      const pintarDetalle = () => {
        const t = s.value === '__mas_reciente' ? f.mas_reciente : (s.value === '__estrategia' ? f.actual : s.value);
        const o = f.opciones.find((x) => x.texto === t);
        detalle.replaceChildren(...(o ? chipsOpcion(o).filter(Boolean) : []));
      };
      const marcadas = new Set(e.valores || (f.actual ? [f.actual] : []));
      const contador = h('span', { class: 'sub' });
      const contar = () => { contador.textContent = varias.has(f.id) ? marcadas.size + ' elegida(s): una descarga por cada una' : ''; };
      const multi = h('ul', { class: 'lista opciones-multi' + (varias.has(f.id) ? '' : ' oculto') });
      for (const o of f.opciones) {
        const cb = h('input', { type: 'checkbox', checked: marcadas.has(o.texto), value: o.texto, 'aria-label': o.texto });
        cb.addEventListener('change', () => { if (cb.checked) marcadas.add(o.texto); else marcadas.delete(o.texto); contar(); });
        multi.appendChild(h('li', null, cb, h('div', { class: 'crece' }, o.texto), ...chipsOpcion(o)));
      }
      const casVarias = h('input', { type: 'checkbox', checked: varias.has(f.id), 'aria-label': 'Elegir varias en ' + f.nombre });
      lectores[f.id] = () => {
        if (varias.has(f.id)) { const vals = f.opciones.map((o) => o.texto).filter((t) => marcadas.has(t)); return vals.length ? { valores: vals } : null; }
        if (s.value === '__mas_reciente') return { estrategia: 'mas_reciente', valor: '' };
        if (s.value === '__estrategia') return { estrategia: e.estrategia, valor: e.valor || '' };
        return { estrategia: 'fija', valor: s.value };
      };
      s.addEventListener('change', () => { pintarDetalle(); cambio(f); });
      casVarias.addEventListener('change', () => {
        if (casVarias.checked) varias.add(f.id); else varias.delete(f.id);
        multi.classList.toggle('oculto', !casVarias.checked); s.disabled = casVarias.checked; contar();
      });
      s.disabled = varias.has(f.id);
      contar(); pintarDetalle();
      return [h('div', { class: 'fila' }, h('div', { class: 'crece' }, s),
        f.opciones.length > 1 ? h('label', { class: 'interruptor' }, casVarias, 'Elegir varias') : null, contador), detalle, multi];
    }
    function filaFecha(f) {
      // v3.6: calendario (fecha fija) o «cambia sola» (hoy, ayer, hace N días…) con el formato de la web
      const inp = h('input', { type: 'text', value: (f.eleccion && f.eleccion.valor) || '', 'aria-label': f.nombre });
      lectores[f.id] = () => ({ valor: inp.value });
      return [campoFecha(inp, { formato: f.formato || null, titulo: f.nombre })];
    }
    function filaTexto(f) {
      const inp = h('input', { type: 'text', value: (f.eleccion && f.eleccion.valor) || '', 'aria-label': f.nombre });
      lectores[f.id] = () => ({ valor: inp.value });
      if (f.opciones_busqueda && f.opciones_busqueda.length) {       // v3.3: campo con búsqueda (lupa + tabla)
        const idLista = 'busqueda-' + f.id;
        inp.setAttribute('list', idLista);
        return [inp, h('datalist', { id: idLista }, f.opciones_busqueda.map((o) => h('option', { value: o }))),
          h('div', { class: 'sub' }, 'Elige una fila de la búsqueda (' + f.opciones_busqueda.length + ') o escribe el texto.')];
      }
      return [inp];
    }
    function filaCasilla(f) {
      const cb = h('input', { type: 'checkbox', checked: !!(f.eleccion && f.eleccion.marcado), 'aria-label': f.nombre });
      lectores[f.id] = () => ({ marcado: cb.checked });
      return [h('label', { class: 'interruptor' }, cb, 'marcada')];
    }
    function pintarFormulario() {
      for (const k of Object.keys(lectores)) delete lectores[k];
      titulo(v.nombre, (v.actualizado ? 'opciones actualizadas el ' + v.actualizado : 'todavía no se han leído sus opciones') + (v.host ? ' · ' + v.host : ''));
      problemas.textContent = (v.problemas || []).join(' · ');
      problemas.classList.toggle('oculto', !(v.problemas || []).length);
      if (!v.filtros.length) { form.replaceChildren(h('p', { class: 'vacio' }, 'Esta página no tiene filtros: «Generar y descargar» ejecuta la acción directamente.')); return; }
      form.replaceChildren(...v.filtros.map((f) => {
        const ctl = ['lista', 'lista_nativa', 'pestana'].includes(f.tipo) ? filaLista(f) : (f.tipo === 'fecha' ? filaFecha(f) : (f.tipo === 'casilla' ? filaCasilla(f) : filaTexto(f)));
        const reales = f.opciones.filter((o) => !o.guardada).length;
        const meta = ['lista', 'lista_nativa'].includes(f.tipo) ? (reales ? reales + ' opciones' + (f.cronologica ? ' (de la más reciente a la más antigua)' : '') +
          (f.actualizado ? ' · actualizado el ' + f.actualizado : '') + (f.fuente_texto ? ' (' + f.fuente_texto + ')' : '') : '') :
          (f.tipo === 'fecha' ? 'Fecha que se escribe: un día del calendario o una que cambia sola (hoy, ayer, hace N días…).' : '');
        let nota = null;
        if (trayendo.has(f.id)) nota = h('div', { class: 'alerta fila' }, ico('cargando', 'girando'), 'trayendo opciones…');
        else if (f.nota) nota = h('div', { class: 'alerta ' + (f.desconocida ? 'aviso' : '') }, f.nota + ' ', f.desconocida ? boton('Traer ahora', () => traer(f.id), 'chico') : null);
        return h('div', { class: 'filtro', 'data-filtro': f.id },
          h('div', { class: 'fila filtro-cab' }, h('strong', null, f.nombre), f.vigilado ? chip('vigilado', 'info') : null,
            f.nombre_origen === 'numero' ? h('span', { class: 'chip aviso', title: 'Cámbiale el nombre en «Configurar esta página» (o pulsa «Actualizar opciones»: el bot lee el nombre de la web)' }, 'nombre provisional') : null,
            (f.depende_nombres || []).length ? h('span', { class: 'sub' }, 'depende de ' + f.depende_nombres.map((n) => '«' + n + '»').join(', ')) : null,
            h('span', { class: 'espacio' }), h('span', { class: 'sub' }, NOMBRE_TIPO_FILTRO[f.tipo] || f.tipo)),
          ...ctl, meta ? h('div', { class: 'ayuda' }, meta) : null, nota);
      }));
    }
    function nombreArchivo(ruta) { return ruta.split(/[\\/]/).pop(); }
    function agregarArchivo(ruta, nuevo) {
      const li = h('li', null, h('div', { class: 'crece' }, h('div', null, nombreArchivo(ruta)), h('div', { class: 'sub' }, ruta)),
        nuevo ? chip('nuevo', 'ok') : null,
        boton('Abrir archivo', async () => { try { await api('POST', 'archivos/abrir', { ruta }); } catch (e) { errorToast(e); } }, 'chico'),
        boton('Abrir carpeta', async () => { try { await api('POST', 'archivos/carpeta', { ruta }); } catch (e) { errorToast(e); } }, 'chico'));
      const vacio = archivos.querySelector('.vacio');
      if (vacio) vacio.remove();
      if (nuevo) archivos.prepend(li); else archivos.appendChild(li);
    }
    function pintarArchivos() {
      archivos.replaceChildren();
      const sep = (v.carpeta || '').includes('\\') ? '\\' : '/';
      let n = 0;
      for (const e of v.historial || []) {
        if (e.resultado !== 'ok') continue;
        for (const a of e.archivos || []) { if (n++ < 12) agregarArchivo(v.carpeta + sep + a, false); }
      }
      if (!n) archivos.appendChild(h('li', { class: 'vacio' }, 'Todavía no se ha descargado nada con esta página. Carpeta: ' + v.carpeta));
    }
    function pintarHistorial() {
      const filas = (v.historial || []).map((e) => h('li', null, h('span', { class: 'punto ' + (e.resultado === 'ok' ? 'ok' : (e.resultado === 'error' ? 'error' : 'aviso')) }),
        h('div', { class: 'crece' }, h('div', null, e.cuando), h('div', { class: 'sub' }, e.mensaje || (e.archivos || []).join(', '))),
        e.registro ? boton('Ver registro', () => verRegistro(e), 'chico') : null, e.captura ? boton('Captura del error', () => verCaptura(e), 'chico') : null));
      historialCaja.replaceChildren(filas.length ? h('ul', { class: 'lista' }, filas) : h('p', { class: 'vacio' }, 'Sin ejecuciones todavía.'));
    }
    async function generar(confirmado, extra) {
      confirmacion.classList.add('oculto');
      const datos = Object.assign({ seleccion: todas(), sin_navegador: fondo.valor(), confirmar: !!confirmado }, extra || {});
      try {
        const r = await api('POST', 'paginas/' + id + '/ejecutar', datos);
        if (r.confirmar) {
          confirmacion.replaceChildren(h('span', null, r.mensaje + ' '), boton('Sí, ejecutar ' + r.n + ' veces', () => generar(true, extra), 'chico primario'), ' ',
            boton('Cancelar', () => confirmacion.classList.add('oculto'), 'chico'));
          confirmacion.classList.remove('oculto');
          return;
        }
        trabajoId = r.id;
        avisar(fondo.valor() ? 'Trabajando por detrás (sin abrir navegador)…' : 'Trabajando (navegador visible)…');
      } catch (e) { errorToast(e); }
    }
    async function actualizarOpciones() {
      try { const r = await api('POST', 'paginas/' + id + '/actualizar', { seleccion: todas() }); trabajoId = r.id; avisar('Leyendo las opciones de los filtros en la página (por detrás, sin abrir navegador)…'); }
      catch (e) { errorToast(e); }
    }
    async function guardarFavorito() {
      const n = await pedirTexto('Guardar como favorito', 'Nombre del favorito (p. ej. «Mayorista + corte más reciente + Excel»). Guarda lo que tienes elegido ahora; «La más reciente» se recalcula cada vez.');
      if (!n) return;
      try { const r = await api('POST', 'paginas/' + id + '/favoritos', { nombre: n, seleccion: todas(), sin_navegador: fondo.valor() }); v.favoritos = r.favoritos; pintarFavoritos(); toast('Favorito «' + r.nombre + '» guardado', 'ok'); }
      catch (e) { errorToast(e); }
    }
    async function guardarDefecto() {
      if (!(await confirmar('Valores por defecto', 'Lo que tienes elegido ahora pasará a ser lo que se usa por defecto en esta página (también en la línea de comandos sin --favorito). ¿Guardar?', 'Guardar'))) return;
      try { v = await api('POST', 'paginas/' + id + '/predeterminado', { seleccion: todas() }); varias.clear(); pintarTodo(); toast('Valores por defecto guardados', 'ok'); }
      catch (e) { errorToast(e); }
    }
    function pintarFavoritos() {
      const lista = v.favoritos || [];
      favs.replaceChildren(...(lista.length ? lista.map((fv) => h('li', null,
        h('div', { class: 'crece' }, h('div', null, '★ ' + fv.nombre), h('div', { class: 'sub' }, fv.descripcion)),
        boton('▶ Ejecutar', () => generar(false, { favorito: fv.nombre, seleccion: {} }), 'chico primario'),
        boton('Programar…', () => programarPagina(id, v.nombre, fv.nombre, false), 'chico'),
        boton('Borrar', async () => {
          if (!(await confirmar('Borrar favorito', '¿Borrar el favorito «' + fv.nombre + '»?', 'Borrar', true))) return;
          try { const r = await api('POST', 'paginas/' + id + '/favoritos/borrar', { nombre: fv.nombre }); v.favoritos = r.favoritos; pintarFavoritos(); } catch (e) { errorToast(e); }
        }, 'chico peligro'))) : [h('li', { class: 'vacio' }, 'Sin favoritos. Elige los valores y pulsa «Guardar como favorito…» para ejecutarlos con un clic o programarlos.')]));
    }
    function pintarVigilancia() {
      // v3.3: una Página puede tener VARIAS vigilancias (la misma lista con otros valores, u otras listas)
      const listas = v.filtros.filter((f) => ['lista', 'lista_nativa'].includes(f.tipo));
      if (!listas.length) { vigCaja.replaceChildren(h('p', { class: 'vacio' }, 'Esta página no tiene listas que vigilar.')); return; }
      const obj = { tipo: 'pagina', id, nombre: v.nombre, listas: listas.map((f) => ({ id: f.id, nombre: f.nombre })), favoritos: (v.favoritos || []).map((f) => f.nombre) };
      // v3.5: al cambiar una vigilancia se vuelven a pedir los datos y se repinta SOLO este bloque (no la página)
      const recargar = async () => {
        try { const n = await api('POST', 'paginas/' + id + '/formulario', { seleccion: todas() }); v.vigilancias = n.vigilancias; } catch (e) { return; }
        pintarVigilancia();
        refrescarVista('vigilancia');
      };
      const vigs = v.vigilancias || [];
      vigCaja._obj = obj;
      if (!vigCaja._tarjetas || !vigCaja.contains(vigCaja._tarjetas)) {
        vigCaja._tarjetas = h('div', { class: 'tarjetas-vig' });
        vigCaja.replaceChildren(h('p', { class: 'ayuda' }, 'El bot revisa una lista (p. ej. «Elegir corte») y te avisa cuando llega una opción MÁS RECIENTE que las conocidas («45 - 2026»): aparece en el formulario con la marca «nueva». Puedes vigilar la misma lista con otros valores (p. ej. un reporte y otro), cada una con su descarga automática.'),
          vigCaja._tarjetas, h('div', { class: 'fila' }, boton('＋ Añadir vigilancia', () => modalVigilancia(vigCaja._obj, null, recargar), 'primario'),
            boton('Ver todas en Vigilancia', () => { location.hash = '#/vigilancia'; })));
      }
      claveLista(vigCaja._tarjetas, vigs, (x) => x.id, (x) => tarjetaVigilancia(x, obj, recargar), { vacio: () => h('p', { class: 'vacio' }, 'Sin vigilancias.') });
    }
    function pintarConfig() {
      const d = JSON.parse(JSON.stringify(v.data));
      const nom = h('input', { type: 'text', value: v.nombre, 'aria-label': 'Nombre de la página' });
      const filas = d.filtros.map((f, i) => {
        const n = h('input', { type: 'text', value: f.nombre, 'aria-label': 'Nombre del filtro' });
        const enNom = h('input', { type: 'checkbox', checked: !!f.en_nombre, 'aria-label': 'En el nombre del archivo' });
        const deps = d.filtros.slice(0, i).filter((g) => g.tipo !== 'pestana').map((g) => {
          const cb = h('input', { type: 'checkbox', checked: (f.depende_de || []).includes(g.id), value: g.id });
          return { g, cb, el: h('label', { class: 'interruptor' }, cb, g.nombre) };
        });
        const quitar = h('input', { type: 'checkbox', 'aria-label': 'Quitar el filtro' });
        const tr = h('tr', null, h('td', null, n), h('td', null, chip(NOMBRE_TIPO_FILTRO[f.tipo] || f.tipo, 'info')), h('td', null, enNom),
          h('td', null, ['lista', 'lista_nativa'].includes(f.tipo) && deps.length ? h('div', { class: 'fila' }, deps.map((x) => x.el)) : '—',
            f.depende_auto ? h('div', { class: 'sub' }, 'detectado al leer las opciones') : null),
          h('td', null, h('label', { class: 'interruptor' }, quitar, 'quitar')));
        return { f, n, enNom, deps, quitar, tr };
      });
      const plantilla = h('input', { type: 'text', value: d.nombre_archivo, 'aria-label': 'Nombre de los archivos' });
      const carpetaPag = h('input', { type: 'text', value: (d.opciones || {}).carpeta_descargas || '', placeholder: '(la carpeta de descargas de Ajustes)', 'aria-label': 'Carpeta de los archivos' });
      const a = d.accion || {};
      const tipo = h('select', { 'aria-label': 'Cómo se obtiene el resultado' }, Object.entries(v.tipos_accion).map(([k, t]) => h('option', { value: k }, t)));
      tipo.value = a.tipo || 'descargar';
      const sels = (b) => ((b && b.selectores) || []).join('\n');
      const gen = h('textarea', { 'aria-label': 'Selectores del botón Generar' }, sels(a.generar));
      const genTxt = h('input', { type: 'text', value: (a.generar && a.generar.objetivo) || '', 'aria-label': 'Texto del botón Generar' });
      const desc = h('textarea', { 'aria-label': 'Selectores del botón Descargar' }, sels(a.descargar));
      const descTxt = h('input', { type: 'text', value: (a.descargar && a.descargar.objetivo) || 'Descargar', 'aria-label': 'Texto del botón Descargar' });
      const menu = h('input', { type: 'text', value: (a.menu || []).map((m) => m.objetivo || m.texto).join(' > '), placeholder: 'Vista Exportar', 'aria-label': 'Menú (ratón encima)' });
      const exp = h('input', { type: 'text', value: (a.exportar && a.exportar.objetivo) || 'Exportar', 'aria-label': 'Opción Exportar' });
      const formato = h('select', { 'aria-label': 'Formato' }, ['pdf', 'csv', 'html'].map((x) => h('option', { value: x }, x.toUpperCase())));
      formato.value = a.formato || 'pdf';
      const pest = h('input', { type: 'number', min: '0', value: a.pestana === undefined || a.pestana === null ? 1 : a.pestana, 'aria-label': 'Pestaña del informe' });
      const zonas = { gen: h('div', null, genTxt, gen), desc: h('div', null, descTxt, desc), menu: h('div', null, menu, h('div', { class: 'ayuda' }, 'Opciones del menú sobre las que se pasa el ratón, separadas por «>».')),
        exp: h('div', null, exp), formato: h('div', null, formato), pest: h('div', null, pest, h('div', { class: 'ayuda' }, '1 = la pestaña nueva que abre el informe; 0 = la misma.')) };
      const filasAccion = h('div', { class: 'formulario' });
      const pintarAccion = () => {
        const t = tipo.value;
        filasAccion.replaceChildren(h('label', null, 'Cómo se obtiene el resultado'), tipo);
        if (t === 'pasos') { filasAccion.append(h('label', null, 'Pasos'), h('div', { class: 'ayuda' }, (v.accion_pasos || []).join(' → '))); return; }
        filasAccion.append(h('label', null, t === 'descargar' ? 'Botón que descarga' : 'Botón que genera («Generar», «Ver Reporte», «Consultar»)'), zonas.gen);
        if (t === 'boton_descarga') filasAccion.append(h('label', null, 'Botón de descarga (se habilita al terminar)'), zonas.desc);
        if (t === 'menu_exportar') filasAccion.append(h('label', null, 'Menú (ratón encima)'), zonas.menu, h('label', null, 'Opción que descarga'), zonas.exp);
        if (t === 'guardar_pagina') filasAccion.append(h('label', null, 'Guardar como'), zonas.formato, h('label', null, 'Pestaña del informe'), zonas.pest);
      };
      tipo.addEventListener('change', pintarAccion); pintarAccion();
      let llegada = d.llegada.slice();
      const listaLlegada = h('ol', { class: 'lista pasos-llegada' });
      const pintarLlegada = async () => {
        let desc2 = [];
        try { desc2 = (await api('POST', 'flujo/describir', { flujo: { pasos: llegada } })).pasos; } catch (e) { desc2 = llegada.map((p) => ({ descripcion: p.tipo })); }
        listaLlegada.replaceChildren(...llegada.map((p, i) => h('li', null, h('strong', null, String(i + 1)), h('div', { class: 'crece' }, (desc2[i] || {}).descripcion || p.tipo),
          boton('↑', () => { if (i) { [llegada[i - 1], llegada[i]] = [llegada[i], llegada[i - 1]]; pintarLlegada(); } }, 'chico', { 'aria-label': 'Subir', disabled: i === 0 }),
          boton('Editar', () => dialogoPaso(p, (n) => { llegada[i] = n; pintarLlegada(); }), 'chico'),
          boton('✕', () => { llegada.splice(i, 1); pintarLlegada(); }, 'chico peligro', { 'aria-label': 'Quitar paso' }))));
      };
      pintarLlegada();
      const anadirPaso = () => {
        const t = h('select', { 'aria-label': 'Tipo de paso' }, Object.entries(E.ayuda.tipos).map(([k, x]) => h('option', { value: k }, x)));
        t.value = 'clic';
        abrirModal({ titulo: 'Añadir un paso de llegada', contenido: h('div', null, h('p', null, '¿Qué tipo de paso?'), t), botones: [
          { texto: 'Cancelar', accion: cerrarModal },
          { texto: 'Siguiente', clase: 'primario', accion: () => { const base = { tipo: t.value }; if (t.value === 'abrir_url') base.url = v.url; dialogoPaso(base, (n) => { llegada.push(n); pintarLlegada(); }); } }] });
      };
      const guardar = async () => {
        const nuevo = Object.assign({}, d);
        nuevo.filtros = filas.filter((x) => !x.quitar.checked).map((x) => {
          const f = Object.assign({}, x.f, { nombre: x.n.value.trim(), en_nombre: x.enNom.checked });
          if (x.deps.length && ['lista', 'lista_nativa'].includes(f.tipo)) {
            const deps = x.deps.filter((y) => y.cb.checked && !filas.find((z) => z.f.id === y.g.id).quitar.checked).map((y) => y.g.id);
            if (JSON.stringify(deps) !== JSON.stringify(x.f.depende_de || [])) { f.depende_de = deps; f.depende_manual = true; f.depende_auto = false; }
          }
          if (f.nombre !== x.f.nombre) f.nombre_origen = 'usuario';
          return f;
        });
        nuevo.nombre_archivo = plantilla.value.trim();
        nuevo.opciones = Object.assign({}, d.opciones || {}, { carpeta_descargas: carpetaPag.value.trim() });
        const lineas = (ta) => ta.value.split('\n').map((x) => x.trim()).filter((x) => x);
        const b = (ta, txt) => ({ selectores: lineas(ta), objetivo: txt.value.trim(), texto: txt.value.trim() });
        const t = tipo.value;
        if (t !== 'pasos') {
          nuevo.accion = { tipo: t, generar: b(gen, genTxt) };
          if (t === 'boton_descarga') nuevo.accion.descargar = b(desc, descTxt);
          if (t === 'menu_exportar') { nuevo.accion.menu = menu.value.split('>').map((x) => x.trim()).filter((x) => x).map((x) => ({ texto: x, objetivo: x })); nuevo.accion.exportar = { texto: exp.value.trim(), objetivo: exp.value.trim() }; }
          if (t === 'guardar_pagina') { nuevo.accion.formato = formato.value; nuevo.accion.pestana = parseInt(pest.value || '1', 10); }
        }
        nuevo.llegada = llegada;
        try { v = await api('PUT', 'paginas/' + id, { nombre: nom.value.trim(), data: nuevo }); toast('Página guardada', 'ok'); pintarTodo(); }
        catch (e) { errorToast(e); }
      };
      const tokens = ['{pagina}', '{variantes}', '{hoy:%Y-%m-%d}'].concat(d.filtros.map((f) => '{' + f.nombre + '}'));
      // v3.7: «Archivo descargado» con «Se guardará como: …» (con lo escrito aunque no se haya guardado todavía)
      plantilla.setAttribute('data-nombre-archivo', 'pagina');
      plantilla.placeholder = NOMBRE_PAGINA_DEFECTO;
      const vistaPag = vistaArchivo(() => ({ archivo: 'pagina', texto: plantilla.value, carpeta: carpetaPag.value.trim(), pagina: { nombre: nom.value.trim() || v.nombre,
        data: Object.assign({}, d, { filtros: filas.filter((x) => !x.quitar.checked).map((x) => Object.assign({}, x.f, { nombre: x.n.value.trim() || x.f.nombre, en_nombre: x.enNom.checked })),
          accion: Object.assign({}, d.accion || {}, { tipo: tipo.value, formato: formato.value }) }) } }));
      [plantilla, carpetaPag, nom].concat(filas.map((x) => x.n)).forEach((x) => x.addEventListener('input', vistaPag.act));
      [tipo, formato].concat(filas.map((x) => x.enNom), filas.map((x) => x.quitar)).forEach((x) => x.addEventListener('change', vistaPag.act));
      configCaja.replaceChildren(
        h('div', { class: 'formulario' }, h('label', null, 'Nombre de la página'), nom),
        h('h3', null, 'Archivo descargado'),
        h('div', { class: 'formulario', 'data-archivo-descargado': 'pagina' },
          h('label', null, 'Nombre del archivo'), h('div', null, plantilla, vistaPag.el,
            campoNombreArchivo(plantilla, { textoDefecto: 'Nombre de la página + lo elegido', defecto: NOMBRE_PAGINA_DEFECTO, web: false }),
            h('div', { class: 'ayuda' }, 'Escribe el nombre sin la extensión (se pone sola). Se puede usar: ' + tokens.join(' · ') +
            '. {variantes} = lo elegido en los filtros marcados «en el nombre» (y en los que elijas varias). Ahora: ' + (v.plantilla_vista || ''))),
          h('label', null, 'Carpeta'), h('div', null, campoRuta(carpetaPag, { titulo: 'Carpeta donde se guardan los archivos de la página' }),
            h('div', { class: 'ayuda' }, 'Vacío = la carpeta de descargas del bot (la ruta exacta sale en «Se guardará como»).'))),
        h('h3', null, 'Filtros'),
        h('div', { class: 'envoltorio-tabla' }, h('table', { class: 'tabla' }, h('thead', null, h('tr', null, h('th', null, 'Nombre'), h('th', null, 'Tipo'),
          h('th', null, 'En el nombre del archivo'), h('th', null, 'Sus opciones dependen de'), h('th', null, ''))), h('tbody', null, filas.map((x) => x.tr)))),
        h('h3', null, 'Cómo se obtiene el resultado'), filasAccion,
        h('h3', null, 'Cómo llegar a la página'), h('p', { class: 'ayuda' }, 'Pasos que el bot hace antes de los filtros (abrir la dirección, iniciar sesión si hace falta, clics en menús). El inicio de sesión usa tus Accesos; si falta o falla la contraseña, te la pregunta aquí.'),
        listaLlegada, h('div', { class: 'fila' }, boton('+ Añadir paso', anadirPaso, 'chico')),
        h('div', { class: 'fila', style: 'margin-top:14px' }, boton('Guardar configuración', guardar, 'primario'), h('span', { class: 'espacio' }),
          boton('Eliminar la página', async () => {
            if (!(await confirmar('Eliminar la página', 'Se borrará «' + v.nombre + '», sus favoritos, sus opciones guardadas y su historial. Los reportes no cambian. ¿Seguro?', 'Eliminar', true))) return;
            try { await api('DELETE', 'paginas/' + id, { confirmar: true }); location.hash = '#/reportes'; } catch (e) { errorToast(e); }
          }, 'peligro')));
    }
    function pintarTodo() { pintarFormulario(); pintarFavoritos(); pintarVigilancia(); pintarConfig(); pintarArchivos(); pintarHistorial(); }

    E.oyentes.push((ev) => {
      if (ev.tipo === 'pagina_opciones' && ev.pagina_id === id) { trayendo.clear(); avisar(ev.texto, ev.ok ? 'ok' : 'error'); recargar(); return; }
      if (ev.tipo === 'vigilancia' && ev.pagina_id === id) { recargar(); return; }
      if (ev.tipo === 'lote' && ev.pagina_id === id) { avisar('Ejecución ' + ev.n + ' de ' + ev.total + ': ' + ev.nombre); return; }
      if (ev.tipo === 'resultado' && ev.pagina_id === id) { for (const a of ev.archivos || []) agregarArchivo(a, true); return; }
      if (ev.tipo === 'trabajo' && ev.estado !== 'en_curso' && pendienteTraer && ev.trabajo !== trabajoId) { const f = pendienteTraer; pendienteTraer = null; traer(f); return; }
      if (!trabajoId || ev.trabajo !== trabajoId) return;
      if (ev.tipo === 'progreso' && ev.i >= 0) avisar('Paso ' + (ev.i + 1) + ': ' + (ev.texto || ''));
      if (ev.tipo === 'trabajo' && ev.estado !== 'en_curso') {
        avisar(ev.resumen || '', ev.estado === 'ok' ? 'ok' : 'error');
        trabajoId = null;
        api('GET', 'paginas/' + id + '/historial').then((r) => { v.historial = r.historial; pintarHistorial(); }).catch(() => {});
        if (pendienteTraer) { const f = pendienteTraer; pendienteTraer = null; traer(f); }
      }
    });
    c.appendChild(h('div', { class: 'barra-herr' }, boton('← Reportes', () => { location.hash = '#/reportes'; }), h('span', { class: 'espacio' }),
      v.url ? h('span', { class: 'sub' }, v.url) : null));
    c.appendChild(problemas);
    c.appendChild(panel(null, form, confirmacion,
      h('div', { class: 'fila acciones-pagina', style: 'margin-top:14px' }, boton('⤓ Generar y descargar', () => generar(false), 'primario grande'),
        boton('↻ Actualizar opciones', actualizarOpciones), boton('★ Guardar como favorito…', guardarFavorito), boton('Guardar como valores por defecto', guardarDefecto),
        h('span', { class: 'espacio' }), fondo.caja),
      h('p', { class: 'ayuda' }, 'Pon varias opciones con «Elegir varias» para descargar una vez por cada una (con más de ' + v.max_sin_confirmar + ' ejecuciones te pide confirmación; máximo ' + v.max_ejecuciones + ').'),
      estado));
    c.appendChild(h('div', { class: 'rejilla' },
      h('div', null, panel('Archivos descargados', archivos), panel('Favoritos', favs)),
      h('div', null, panel('Últimas ejecuciones', historialCaja), panel('Vigilancia', vigCaja))));
    c.appendChild(h('details', { class: 'panel opciones config-pagina' }, h('summary', null, 'Configurar esta página (nombres, dependencias, acción, llegada)'), configCaja));
    pintarTodo();
  }

  function programarPagina(id, nombre, favorito, vigilar, extra) {
    const ruta = 'paginas/' + id + (vigilar ? '/vigilancia/programar' : '/programar');
    const lanzar = async (datos) => {
      try {
        const pr = await api('POST', ruta, datos);
        if (await confirmar('Programar', 'Se creará la tarea «' + pr.tarea + '» en el Programador de tareas de Windows con este comando:\n' + pr.comando, 'Crear la tarea')) {
          await api('POST', ruta, Object.assign({ confirmar: true }, datos)); toast('Tarea creada', 'ok');
        }
      } catch (e) { errorToast(e); }
    };
    if (vigilar) { lanzar(extra || {}); return; }
    abrirProgramarPagina(id, nombre, favorito, ruta);
  }
  // v3.4: «Programar…» de una Página / favorito con el editor «Cuándo»
  async function abrirProgramarPagina(id, nombre, favorito, ruta) {
    let g = {};
    try { g = await api('POST', ruta, { favorito, consultar: true }); } catch (e) { g = {}; }
    const ed = editorCuando(g.guardada || { reglas: [reglaPorDefecto('semanal', { horas: ['07:00'] })] }, { textoNunca: 'Sin programar (solo cuando pulse «Generar y descargar»)' });
    const titulo = 'Programar «' + nombre + '»' + (favorito ? ' — ' + favorito : '');
    abrirModal({ titulo, ancho: true, contenido: h('div', { 'data-modal-programar': 'pagina' },
      h('p', { class: 'ayuda' }, 'Elige cuándo se ejecuta. Se crea una tarea en el Programador de tareas de Windows que ejecuta la página ' + (favorito ? 'con el favorito «' + favorito + '» ' : '') +
        '(en segundo plano o en vivo: lo eliges en «Avisos y vista»; con tu usuario y solo con la sesión de Windows iniciada): es la tarea la que hace que se ejecute sola. «La más reciente» se recalcula cada vez.'),
      g.existe ? h('div', { class: 'alerta ok' }, 'Ya tiene tarea en Windows: ' + (g.descripcion || '') + '. Si la cambias, se sustituye.') : h('div', { class: 'alerta aviso' }, 'Todavía no tiene tarea en Windows: no se ejecuta sola.'),
      ed.caja),
      botones: [{ texto: 'Cancelar', accion: cerrarModal },
        ...(g.existe ? [{ texto: 'Quitar la tarea de Windows', clase: 'peligro', accion: () => quitarTareaWindows(ruta, { favorito, quitar: true }) }] : []),
        { texto: 'Ver lo que se creará y crear…', clase: 'primario', accion: async () => {
          const p = ed.leer();
          if (!p.reglas.length) { toast('Elige cuándo se ejecuta (días y horas)', 'aviso'); return; }
          const v = await ed.comprobar();
          if (v && !v.valida) { toast(v.error, 'error'); return; }
          await crearTareaWindows(ruta, { favorito, programacion: p }, titulo);
        } }] });
  }

  // ------------------------------------------------------------------ v3.4: editor «Cuándo» (programación completa)
  // Componente reutilizable (vigilancias, «Programar…» de reportes y Páginas, y lo que venga: correo).  Trabaja con la
  // forma de webbot/horario.py: {reglas: [{tipo: semanal|intervalo|mensual|mensual_semana, …}], inicio, fin}.  La
  // descripción en español y las próximas ejecuciones las calcula el bot (POST /api/horario): una sola implementación.
  const DIAS_CUANDO = [['lun', 'L', 'lunes'], ['mar', 'M', 'martes'], ['mie', 'X', 'miércoles'], ['jue', 'J', 'jueves'],
    ['vie', 'V', 'viernes'], ['sab', 'S', 'sábado'], ['dom', 'D', 'domingo']];
  const LABORABLES = ['lun', 'mar', 'mie', 'jue', 'vie'];
  const MESES_CUANDO = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const TODOS_MESES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  // v3.7: «Avisos y vista» de una programación nueva (igual que horario.EJECUCION_DEFECTO)
  const EJECUCION_DEFECTO = { avisar_antes: 5, avisar_inicio: true, avisar_fin: true, en_vivo: false, ventanita: true };
  const TIPOS_REGLA = [['semanal', 'Días y horas'], ['intervalo', 'Cada N horas en un horario'], ['mensual', 'Mensual: días del mes'],
    ['mensual_semana', 'Mensual: el primer/…/último día de la semana']];
  function reglaPorDefecto(tipo, antes) {
    antes = antes || {};
    const dias = (antes.dias && antes.dias.length) ? antes.dias.slice() : LABORABLES.slice();
    const horas = (antes.horas && antes.horas.length) ? antes.horas.slice() : ['08:00'];
    if (tipo === 'intervalo') return { tipo, dias, cada_min: 120, desde: horas[0] || '08:00', hasta: '18:00' };
    if (tipo === 'mensual') return { tipo, dias_mes: [1], horas, meses: TODOS_MESES.slice() };
    if (tipo === 'mensual_semana') return { tipo, semanas: [1], dias: [dias[0] || 'lun'], horas, meses: TODOS_MESES.slice() };
    return { tipo: 'semanal', dias, horas: antes.tipo === 'intervalo' ? [antes.desde || '08:00'] : horas };
  }
  const familia = (t) => (t === 'mensual_semana' ? 'mensual' : t);

  function editorCuando(prog, opc) {
    opc = opc || {};
    const textoNunca = opc.textoNunca || 'Solo cuando pulse «Revisar ahora»';
    const reglas = JSON.parse(JSON.stringify((prog && prog.reglas) || []));
    let nunca = !reglas.length;
    let ultimaVista = null;
    let temporizador = null;
    let pedida = 0;
    const modo = h('select', { 'aria-label': 'Cuándo', 'data-cuando-modo': '1' }, h('option', { value: 'nunca' }, textoNunca),
      h('option', { value: 'semanal' }, 'Días y horas (p. ej. de lunes a viernes a las 08:00 y 14:00)'),
      h('option', { value: 'intervalo' }, 'Cada N horas en un horario (p. ej. de 08:00 a 18:00 cada 2 h)'),
      h('option', { value: 'mensual' }, 'Mensual (días del mes, último día, el primer lunes…)'),
      h('option', { value: 'varios', disabled: true }, 'Varios horarios distintos (abajo)'));
    const zonaReglas = h('div', { class: 'cuando-reglas', 'data-cuando-reglas': '1' });
    const anadir = boton('＋ Añadir otro horario', () => {
      const ult = reglas[reglas.length - 1];
      reglas.push(reglaPorDefecto(ult ? ult.tipo : 'semanal', ult)); pintarReglas(); cambiado();
    }, 'chico', { 'data-cuando-anadir': '1', title: 'Otro horario con otros días u horas (p. ej. los viernes solo a las 10:00)' });
    // v3.6: con el calendario (fechas fijas AAAA-MM-DD, como antes)
    const inicio = h('input', { type: 'text', value: (prog && prog.inicio) || '', 'aria-label': 'Fecha de inicio' });
    const fin = h('input', { type: 'text', value: (prog && prog.fin) || '', 'aria-label': 'Fecha de fin' });
    inicio.addEventListener('change', () => cambiado()); fin.addEventListener('change', () => cambiado());
    const sinFecha = (inp) => { inp.value = ''; inp.dispatchEvent(new Event('input', { bubbles: true })); };
    const fechas = h('details', { class: 'cuando-fechas' }, h('summary', null, 'Fecha de inicio y de fin (opcional)'),
      h('div', { class: 'fila' }, h('span', { class: 'sub' }, 'Desde'), campoFecha(inicio, { iso: true, vacio: 'sin fecha de inicio', titulo: 'Fecha de inicio' }),
        h('span', { class: 'sub' }, 'hasta'), campoFecha(fin, { iso: true, vacio: 'sin fecha de fin', titulo: 'Fecha de fin' }),
        boton('Sin fechas', () => { sinFecha(inicio); sinFecha(fin); cambiado(); }, 'chico')));
    if (inicio.value || fin.value) fechas.open = true;
    // v3.7 «Avisos y vista»: avisar antes / al empezar / al terminar, en vivo o en segundo plano, y la ventanita
    const ejec = Object.assign({}, EJECUCION_DEFECTO, (prog && prog.ejecucion) || {});
    const avisoAntes = h('select', { 'aria-label': 'Avisarme antes', 'data-ejec-antes': '1', class: 'corto' },
      [[0, 'No'], [1, '1 minuto'], [5, '5 minutos'], [10, '10 minutos'], [15, '15 minutos'], [30, '30 minutos']].map(([v, t]) => h('option', { value: String(v) }, t)));
    avisoAntes.value = String(ejec.avisar_antes);
    const casilla = (clave, texto, marcado) => {
      const cb = h('input', { type: 'checkbox', checked: !!marcado, 'data-ejec': clave });
      cb.addEventListener('change', () => cambiado());
      return { cb, et: h('label', { class: 'interruptor' }, cb, h('span', null, texto)) };
    };
    const avInicio = casilla('avisar_inicio', 'Avisar cuando empieza', ejec.avisar_inicio);
    const avFin = casilla('avisar_fin', 'Avisar cuando termina (con el resultado)', ejec.avisar_fin);
    const ventanita = casilla('ventanita', 'Mostrar una ventanita con la barra de progreso', ejec.ventanita);
    const nombreVista = 'vista-' + Math.random().toString(36).slice(2, 8);
    const radioVista = (valor, texto) => {
      const r = h('input', { type: 'radio', name: nombreVista, value: valor, checked: (valor === 'vivo') === !!ejec.en_vivo, 'data-ejec-vista': valor });
      r.addEventListener('change', () => cambiado());
      return h('label', { class: 'interruptor' }, r, h('span', null, texto));
    };
    avisoAntes.addEventListener('change', () => cambiado());
    const avisos = h('details', { class: 'cuando-avisos', open: true, 'data-cuando-avisos': '1' }, h('summary', null, 'Avisos y vista'),
      h('div', { class: 'cuando-campo' }, h('span', { class: 'cuando-etq' }, 'Avisarme antes'), h('div', { class: 'crece fila' }, avisoAntes,
        h('span', { class: 'sub' }, 'un aviso de Windows: «se ejecutará en 5 min»'))),
      h('div', { class: 'cuando-campo' }, h('span', { class: 'cuando-etq' }, 'Avisos'), h('div', { class: 'crece columna' }, avInicio.et, avFin.et)),
      h('div', { class: 'cuando-campo' }, h('span', { class: 'cuando-etq' }, 'Cómo se ve'), h('div', { class: 'crece columna', role: 'radiogroup', 'aria-label': 'Cómo se ve la ejecución' },
        radioVista('fondo', 'En segundo plano (oculto)'), radioVista('vivo', 'Ver la ejecución en vivo (navegador visible)'), ventanita.et)));
    function leerEjecucion() {
      const vivo = avisos.querySelector('input[data-ejec-vista="vivo"]');
      return { avisar_antes: parseInt(avisoAntes.value, 10) || 0, avisar_inicio: avInicio.cb.checked, avisar_fin: avFin.cb.checked,
        en_vivo: !!(vivo && vivo.checked), ventanita: ventanita.cb.checked };
    }
    const vistaCaja = h('div', { class: 'cuando-vista', 'data-cuando-vista': '1', 'aria-live': 'polite' });
    const cuerpo = h('div', { class: 'cuando-cuerpo' }, zonaReglas, h('div', { class: 'fila' }, anadir), fechas, avisos);
    const caja = h('div', { class: 'cuando', 'data-cuando': '1' }, modo, cuerpo, vistaCaja);

    function leer() {
      if (nunca) return { reglas: [], inicio: '', fin: '' };
      return { reglas: JSON.parse(JSON.stringify(reglas)), inicio: inicio.value || '', fin: fin.value || '', ejecucion: leerEjecucion() };
    }
    function cambiado() {
      clearTimeout(temporizador);
      temporizador = setTimeout(previsualizar, 200);
      if (opc.alCambiar) opc.alCambiar(leer());
    }
    async function previsualizar() {
      const n = ++pedida;
      let v;
      try { v = await api('POST', 'horario', { programacion: leer(), n: 5, vacio: textoNunca }); }
      catch (e) { v = { valida: false, error: e.message || String(e) }; }
      if (n !== pedida) return v;
      ultimaVista = v;
      pintarVista();
      return v;
    }
    function pintarVista() {
      const v = ultimaVista;
      if (!v) { vistaCaja.replaceChildren(); return; }
      if (!v.valida) { vistaCaja.replaceChildren(h('div', { class: 'alerta error' }, v.error)); return; }
      vistaCaja.replaceChildren(h('div', { class: 'alerta ' + (v.vacia ? '' : 'ok') }, h('strong', null, v.vacia ? textoNunca : 'Se ejecutará ' + v.descripcion),
        v.vacia ? null : h('div', { class: 'sub', 'data-cuando-proximas': '1' }, v.proximas.length ? 'Próximas: ' + v.proximas.map((x) => x.texto).join(' · ') : 'No hay ninguna ejecución próxima (¿fecha de fin pasada?)'),
        v.vacia || !v.ejecucion_texto ? null : h('div', { class: 'sub', 'data-cuando-ejecucion': '1' }, v.ejecucion_texto + '.')),
        ...(v.avisos || []).map((a) => h('div', { class: 'alerta aviso' }, a)));
    }
    function chipsDias(r, unico) {
      const cont = h('div', { class: 'dias-chips', role: 'group', 'aria-label': 'Días de la semana' });
      for (const [k, letra, nombre] of DIAS_CUANDO) {
        const b = h('button', { type: 'button', class: 'dia-chip' + (r.dias.includes(k) ? ' activo' : ''), 'aria-pressed': r.dias.includes(k) ? 'true' : 'false', title: nombre, 'data-dia': k }, letra);
        b.addEventListener('click', () => {
          const tiene = r.dias.includes(k);
          if (unico) r.dias = [k];
          else r.dias = DIAS_CUANDO.map((d) => d[0]).filter((d) => (d === k ? !tiene : r.dias.includes(d)));
          pintarReglas(); cambiado();
        });
        cont.appendChild(b);
      }
      if (unico) return cont;
      const rapido = (texto, dias) => boton(texto, () => { r.dias = dias.slice(); pintarReglas(); cambiado(); }, 'chico enlace');
      return h('div', { class: 'fila' }, cont, rapido('Todos', DIAS_CUANDO.map((d) => d[0])), rapido('Lunes a viernes', LABORABLES), rapido('Fines de semana', ['sab', 'dom']));
    }
    function listaHoras(r) {
      const cont = h('div', { class: 'horas-lista', 'data-horas': '1' });
      r.horas.forEach((hh, k) => {
        const inp = h('input', { type: 'time', value: hh, 'aria-label': 'Hora ' + (k + 1) });
        inp.addEventListener('change', () => { if (inp.value) { r.horas[k] = inp.value; cambiado(); } });
        cont.appendChild(h('span', { class: 'hora-item' }, inp, r.horas.length > 1 ? boton('✕', () => { r.horas.splice(k, 1); pintarReglas(); cambiado(); }, 'chico', { 'aria-label': 'Quitar la hora ' + hh }) : null));
      });
      cont.appendChild(boton('＋ hora', () => {
        const ult = r.horas[r.horas.length - 1] || '08:00';
        const hhh = Math.min(23, parseInt(ult.slice(0, 2), 10) + 1);
        r.horas.push((hhh < 10 ? '0' : '') + hhh + ult.slice(2)); pintarReglas(); cambiado();
      }, 'chico', { 'data-anadir-hora': '1' }));
      return cont;
    }
    function chipsMeses(r) {
      const todos = r.meses.length === 12;
      const cont = h('div', { class: 'dias-chips' });
      MESES_CUANDO.forEach((m, k) => {
        const n = k + 1;
        const b = h('button', { type: 'button', class: 'dia-chip ancho' + (r.meses.includes(n) ? ' activo' : ''), 'aria-pressed': r.meses.includes(n) ? 'true' : 'false' }, m);
        b.addEventListener('click', () => { r.meses = r.meses.includes(n) ? r.meses.filter((x) => x !== n) : r.meses.concat([n]).sort((a, b2) => a - b2); pintarReglas(); cambiado(); });
        cont.appendChild(b);
      });
      const d = h('details', null, h('summary', null, todos ? 'Todos los meses (cambiar…)' : 'Solo algunos meses'), h('div', { class: 'fila' }, cont,
        boton('Todos', () => { r.meses = TODOS_MESES.slice(); pintarReglas(); cambiado(); }, 'chico enlace')));
      if (!todos) d.open = true;
      return d;
    }
    function filaCampo(etiqueta, ...hijos) { return h('div', { class: 'cuando-campo' }, h('span', { class: 'cuando-etq' }, etiqueta), h('div', { class: 'crece' }, ...hijos)); }
    function pintarRegla(r, i) {
      const tipo = h('select', { 'aria-label': 'Tipo de horario', 'data-regla-tipo': String(i) }, TIPOS_REGLA.map(([v, t]) => h('option', { value: v }, t)));
      tipo.value = r.tipo;
      tipo.addEventListener('change', () => { reglas[i] = reglaPorDefecto(tipo.value, r); pintarReglas(); cambiado(); });
      const cab = h('div', { class: 'fila' }, h('strong', null, reglas.length > 1 ? 'Horario ' + (i + 1) : 'Horario'), tipo, h('span', { class: 'crece' }),
        reglas.length > 1 ? boton('✕ Quitar este horario', () => { reglas.splice(i, 1); if (!reglas.length) nunca = true; pintarReglas(); cambiado(); }, 'chico peligro') : null);
      const partes = [];
      if (r.tipo === 'semanal') {
        partes.push(filaCampo('Días', chipsDias(r)), filaCampo('Horas', listaHoras(r)));
      } else if (r.tipo === 'intervalo') {
        const enHoras = r.cada_min % 60 === 0;
        const num = h('input', { type: 'number', min: enHoras ? '1' : '15', max: enHoras ? '23' : '1380', value: enHoras ? r.cada_min / 60 : r.cada_min, 'aria-label': 'Cada', class: 'corto' });
        const unidad = h('select', { 'aria-label': 'Unidad', class: 'corto' }, h('option', { value: 'h' }, 'horas'), h('option', { value: 'min' }, 'minutos'));
        unidad.value = enHoras ? 'h' : 'min';
        const leerCada = () => { const n = parseInt(num.value, 10) || 0; r.cada_min = unidad.value === 'h' ? n * 60 : n; cambiado(); };
        num.addEventListener('input', leerCada);
        unidad.addEventListener('change', () => { num.min = unidad.value === 'h' ? '1' : '15'; num.max = unidad.value === 'h' ? '23' : '1380'; leerCada(); });
        const desde = h('input', { type: 'time', value: r.desde, 'aria-label': 'Desde la hora' });
        const hasta = h('input', { type: 'time', value: r.hasta, 'aria-label': 'Hasta la hora' });
        desde.addEventListener('change', () => { r.desde = desde.value || '00:00'; cambiado(); });
        hasta.addEventListener('change', () => { r.hasta = hasta.value || '23:59'; cambiado(); });
        partes.push(filaCampo('Días', chipsDias(r)),
          filaCampo('Cada', h('div', { class: 'fila' }, num, unidad, h('span', { class: 'sub' }, 'de'), desde, h('span', { class: 'sub' }, 'a'), hasta,
            boton('Todo el día', () => { r.desde = '00:00'; r.hasta = '23:59'; pintarReglas(); cambiado(); }, 'chico enlace'))),
          h('div', { class: 'ayuda' }, 'Mínimo cada 15 minutos. La última ejecución es a la hora «a» si cae justo (de 08:00 a 18:00 cada 2 h: 08, 10, 12, 14, 16 y 18).'));
      } else if (r.tipo === 'mensual') {
        const cont = h('div', { class: 'dias-chips mes', role: 'group', 'aria-label': 'Días del mes' });
        for (let n = 1; n <= 31; n++) {
          const b = h('button', { type: 'button', class: 'dia-chip' + (r.dias_mes.includes(n) ? ' activo' : ''), 'aria-pressed': r.dias_mes.includes(n) ? 'true' : 'false', 'data-dia-mes': String(n) }, String(n));
          b.addEventListener('click', () => { r.dias_mes = r.dias_mes.includes(n) ? r.dias_mes.filter((x) => x !== n) : r.dias_mes.concat([n]); ordenarMes(r); pintarReglas(); cambiado(); });
          cont.appendChild(b);
        }
        const ult = h('button', { type: 'button', class: 'dia-chip ancho' + (r.dias_mes.includes('ultimo') ? ' activo' : ''), 'aria-pressed': r.dias_mes.includes('ultimo') ? 'true' : 'false', 'data-dia-mes': 'ultimo' }, 'Último día del mes');
        ult.addEventListener('click', () => { r.dias_mes = r.dias_mes.includes('ultimo') ? r.dias_mes.filter((x) => x !== 'ultimo') : r.dias_mes.concat(['ultimo']); ordenarMes(r); pintarReglas(); cambiado(); });
        cont.appendChild(ult);
        partes.push(filaCampo('Días del mes', cont), filaCampo('Horas', listaHoras(r)), filaCampo('Meses', chipsMeses(r)));
      } else {
        const cont = h('div', { class: 'dias-chips', role: 'group', 'aria-label': 'Qué semana del mes' });
        for (const [k, t] of [[1, 'primer'], [2, 'segundo'], [3, 'tercer'], [4, 'cuarto'], ['ultima', 'último']]) {
          const b = h('button', { type: 'button', class: 'dia-chip ancho' + (r.semanas.includes(k) ? ' activo' : ''), 'aria-pressed': r.semanas.includes(k) ? 'true' : 'false', 'data-semana': String(k) }, t);
          b.addEventListener('click', () => {
            r.semanas = r.semanas.includes(k) ? r.semanas.filter((x) => x !== k) : r.semanas.concat([k]);
            r.semanas.sort((a, b2) => (a === 'ultima' ? 9 : a) - (b2 === 'ultima' ? 9 : b2)); pintarReglas(); cambiado();
          });
          cont.appendChild(b);
        }
        partes.push(filaCampo('El', cont), filaCampo('Día', chipsDias(r)), h('div', { class: 'ayuda' }, 'Ejemplos: el primer lunes de cada mes; el último viernes. Puedes marcar varias semanas y varios días.'),
          filaCampo('Horas', listaHoras(r)), filaCampo('Meses', chipsMeses(r)));
      }
      return h('div', { class: 'cuando-regla', 'data-cuando-regla': String(i) }, cab, ...partes);
    }
    function ordenarMes(r) { r.dias_mes.sort((a, b2) => (a === 'ultimo' ? 99 : a) - (b2 === 'ultimo' ? 99 : b2)); }
    function pintarReglas() {
      const fams = [...new Set(reglas.map((r) => familia(r.tipo)))];
      modo.value = nunca ? 'nunca' : (fams.length === 1 ? fams[0] : 'varios');
      cuerpo.classList.toggle('oculto', nunca);
      zonaReglas.replaceChildren(...(nunca ? [] : reglas.map(pintarRegla)));
    }
    modo.addEventListener('change', () => {
      const v = modo.value;
      if (v === 'nunca') nunca = true;
      else {
        nunca = false;
        if (!reglas.length) reglas.push(reglaPorDefecto(v));
        else for (let i = 0; i < reglas.length; i++) if (familia(reglas[i].tipo) !== v) reglas[i] = reglaPorDefecto(v, reglas[i]);
      }
      pintarReglas(); cambiado();
    });
    pintarReglas();
    previsualizar();
    return { caja, leer, vista: () => ultimaVista, comprobar: previsualizar };
  }

  // v3.4: lo que se creará en el Programador de tareas de Windows, para que el usuario lo confirme.  pr = respuesta de
  // «…/programar» sin confirmar: {tarea, existe, sustituye, descripcion, disparadores, proximas, programa, comando, xml}.
  function confirmarTarea(pr, titulo) {
    return new Promise((resolver) => {
      const no = () => { cerrarModal(); resolver(false); };
      abrirModal({ titulo: titulo || 'Crear la tarea en Windows', ancho: true, alEscape: no, contenido: h('div', { 'data-confirmar-tarea': '1' },
        h('p', null, (pr.existe ? 'Se SUSTITUIRÁ la tarea «' : 'Se creará la tarea «') + pr.tarea + '» en el Programador de tareas de Windows. ' +
          (pr.en_vivo ? 'Se verá en vivo (navegador visible)' : 'Se ejecuta oculta (en segundo plano)') + ', con tu usuario y solo si tienes la sesión de Windows iniciada.'),
        (pr.sustituye || []).length ? h('div', { class: 'alerta aviso' }, 'También se borrará la tarea antigua: ' + pr.sustituye.join(', ')) : null,
        h('div', { class: 'formulario' }, h('label', null, 'Cuándo'), h('strong', null, pr.descripcion),
          h('label', null, 'Próximas'), h('div', null, (pr.proximas || []).map((x) => x.texto).join(' · ') || '—'),
          pr.ejecucion_texto ? h('label', null, 'Avisos y vista') : null, pr.ejecucion_texto ? h('div', { 'data-confirmar-avisos': '1' }, pr.ejecucion_texto) : null,
          h('label', null, 'Disparadores (' + (pr.disparadores || []).length + ')'), h('ul', { class: 'opciones-lista' }, (pr.disparadores || []).map((t) => h('li', null, t))),
          h('label', null, 'Ejecuta'), h('code', { class: 'comando' }, pr.programa || ''),
          h('label', null, 'Comando'), h('code', { class: 'comando' }, pr.comando || '')),
        h('details', null, h('summary', null, 'Ver el XML de la tarea'), h('textarea', { readonly: true, rows: 10, 'aria-label': 'XML de la tarea' }, pr.xml || ''))),
      botones: [{ texto: 'Cancelar', accion: no }, { texto: pr.existe ? 'Sustituir la tarea' : 'Crear la tarea', clase: 'primario', accion: () => { cerrarModal(); resolver(true); } }] });
    });
  }
  // Pide la vista previa (sin confirmar), la enseña y, si el usuario acepta, crea la tarea.  Devuelve true si se creó.
  async function crearTareaWindows(ruta, cuerpo, titulo) {
    try {
      const pr = await api('POST', ruta, cuerpo);
      if (!(await confirmarTarea(pr, titulo))) return false;
      const r = await api('POST', ruta, Object.assign({ confirmar: true }, cuerpo));
      toast('Tarea de Windows ' + (pr.existe ? 'actualizada' : 'creada') + ': ' + pr.descripcion +
        ((r && r.arrancada) ? '. La de hoy ya está en marcha: te avisa y se ejecuta a las ' + r.arrancada + '.' : ''), 'ok', 10000);
      return true;
    } catch (e) { errorToast(e); return false; }
  }
  async function quitarTareaWindows(ruta, cuerpo) {
    try {
      const pr = await api('POST', ruta, cuerpo || {});
      if (!(await confirmar('Quitar la tarea de Windows', 'Se borrará del Programador de tareas de Windows: ' + pr.tareas.join(', ') + '\n' + pr.comandos.join('\n') + '\nDespués solo se ejecutará cuando lo pidas.', 'Quitar la tarea', true))) return false;
      await api('POST', ruta, Object.assign({ confirmar: true }, cuerpo || {}));
      toast('Tarea de Windows quitada', 'ok');
      return true;
    } catch (e) { errorToast(e); return false; }
  }

  // ------------------------------------------------------------------ Grabar
  RUTAS.grabar = async (c) => {
    const est = await api('GET', 'estado');
    const url = h('input', { type: 'url', placeholder: 'https://…', 'aria-label': 'Dirección' });
    const nombre = h('input', { type: 'text', placeholder: 'Ventas diarias', 'aria-label': 'Nombre' });
    const lista = h('ul', { class: 'lista' });
    const estado = h('div', { class: 'ayuda' });
    const empezar = boton('● Empezar a grabar', async () => {
      try { await api('POST', 'grabar', { url: url.value, nombre: nombre.value }); estado.textContent = 'Abriendo el navegador… haz tus pasos en él.'; lista.replaceChildren(); poner(true); }
      catch (e) { errorToast(e); }
    }, 'primario');
    const terminar = boton('■ Terminar', async () => { try { await api('POST', 'grabar/terminar', {}); } catch (e) { errorToast(e); } });
    const resultado = h('div');
    const poner = (grabando) => { empezar.disabled = grabando; terminar.disabled = !grabando; };
    poner(est.grabando);
    const filas = {};
    // v3.5: la vista se queda viva (si se cambia de sección mientras se graba, los pasos siguen llegando aquí)
    const evento = (ev) => {
      if (ev.tipo === 'grab_paso') {
        const li = h('li', null, h('strong', null, String(ev.indice + 1)), h('div', { class: 'crece' }, h('div', null, ev.paso.descripcion)),
          ev.paso.desactivado ? chip('desactivado') : null, ev.paso.auto ? chip('automático', 'info') : null);
        if (filas[ev.indice]) filas[ev.indice].replaceWith(li); else lista.appendChild(li);
        filas[ev.indice] = li;
      } else if (ev.tipo === 'grab_estado') estado.textContent = ev.texto;
      else if (ev.tipo === 'grab_fin') {
        poner(false);
        estado.textContent = 'Grabación terminada: ' + ev.pasos.length + ' pasos.';
        const nom = h('input', { type: 'text', value: (ev.flujo && ev.flujo.nombre) || nombre.value || 'Nuevo reporte', 'aria-label': 'Nombre del reporte' });
        resultado.replaceChildren(panel('Guardar la grabación', h('p', { class: 'ayuda' }, '¿Con qué nombre la guardas? Después podrás revisar y editar los pasos.'),
          h('div', { class: 'fila' }, h('div', { class: 'crece' }, nom), boton('Guardar reporte', async () => {
            try { const r = await api('POST', 'guardar_grabacion', { flujo: ev.flujo, nombre: nom.value, perfil: ev.perfil }); toast('Reporte «' + r.nombre + '» guardado', 'ok'); location.hash = '#/editor/' + r.id; }
            catch (e) { errorToast(e); }
          }, 'primario'))));
      }
    };
    c.appendChild(panel('Grabar un reporte nuevo', h('p', { class: 'ayuda' }, 'Escribe la dirección y pulsa «Empezar a grabar». Se abre el navegador: inicia sesión, elige los filtros, pulsa «Generar» y descarga el archivo como siempre. Los datos de acceso que escribas se guardan solos en Accesos (la contraseña en el Administrador de credenciales). Al acabar pulsa «Terminar» (aquí o en la barra del navegador).'),
      h('div', { class: 'formulario' }, h('label', null, 'Dirección (URL)'), url, h('label', null, 'Nombre (opcional)'), nombre),
      h('div', { class: 'fila' }, empezar, terminar), estado));
    c.appendChild(resultado);
    c.appendChild(panel('Pasos grabados', lista));
    return {
      evento,
      actualizar: async () => { try { const e2 = await api('GET', 'estado'); poner(e2.grabando); } catch (e) { /* nada */ } },
    };
  };

  // ------------------------------------------------------------------ Mapear página
  RUTAS.mapear = async (c, args, query) => {
    if (!E.ayuda) E.ayuda = await api('GET', 'ayuda');
    const r = await api('GET', 'reportes');
    const est = await api('GET', 'estado');
    const selRep = h('select', { 'aria-label': 'Reporte' }, h('option', { value: '' }, '— desde una dirección —'),
      (r.reportes || []).map((x) => h('option', { value: x.id }, x.nombre)));
    if (query.get('reporte')) selRep.value = query.get('reporte');
    const selHasta = h('select', { 'aria-label': 'Hasta qué paso' }, h('option', { value: '' }, 'Automático: justo antes del primer filtro'));
    const url = h('input', { type: 'url', placeholder: 'https://…', 'aria-label': 'Dirección' });
    const estado = h('div', { class: 'ayuda' });
    const acciones = h('div', { class: 'fila' });
    const resultado = h('div');
    // v3.3: qué pestaña del navegador se mapea (automático = la que estás viendo) y por qué un mapa salió vacío
    const selPestana = h('select', { 'aria-label': 'Pestaña a mapear', 'data-pestanas': '1' }, h('option', { value: '' }, 'Automático: la pestaña que estás viendo'));
    const cajaPestana = h('div', { class: 'oculto' }, selPestana);
    const avisosMapa = h('div', { 'data-avisos-mapa': '1' });
    let mapa = null;
    let listo = est.mapeando;
    function pintarPestanas(lista) {
      const previo = selPestana.value;
      selPestana.replaceChildren(h('option', { value: '' }, 'Automático: la pestaña que estás viendo'),
        ...(lista || []).map((p) => h('option', { value: String(p.indice) }, 'Pestaña ' + (p.indice + 1) + ': ' + (p.titulo || p.url) + (p.activa ? ' (la que se ve)' : ''))));
      if ([...selPestana.options].some((o) => o.value === previo)) selPestana.value = previo;
      cajaPestana.classList.toggle('oculto', !lista || lista.length < 2);
      if (cajaPestana.previousElementSibling) cajaPestana.previousElementSibling.classList.toggle('oculto', !lista || lista.length < 2);
    }
    async function refrescarPestanas() {
      try { const d = await api('POST', 'mapa/pestanas', {}); pintarPestanas(d.pestanas); } catch (e) { /* la sesión aún no está lista */ }
    }
    function pintarAvisos(d) {
      const hijos = (d.avisos || []).map((a) => h('div', { class: 'alerta aviso' }, a));
      if (d.diagnostico) hijos.push(h('div', { class: 'ayuda', 'data-diagnostico': '1' }, 'Diagnóstico guardado en: ' + d.diagnostico + ' (captura, direcciones de las pestañas y marcos, controles encontrados y errores; sin contraseñas).'));
      avisosMapa.replaceChildren(...hijos);
    }
    // v3.7: «Archivo descargado» de «Crear pasos» (se recuerda al volver a pintar el mapa); carpeta null = sin tocar
    const archivoMapa = { nombre: NOMBRE_ARCHIVO_DEFECTO, carpeta: null };
    let carpetaRep = '';
    let memMapa = new Map();         // v3.8: lo decidido en cada filtro (se recuerda al «Actualizar opciones»)
    async function cargarPasos() {
      carpetaRep = '';
      selHasta.replaceChildren(h('option', { value: '' }, 'Automático: justo antes del primer filtro'));
      for (const [campo, ocultar] of [[url.parentElement, !!selRep.value], [selHasta.parentElement, !selRep.value]]) {
        campo.classList.toggle('oculto', ocultar);
        campo.previousElementSibling.classList.toggle('oculto', ocultar);
      }
      if (!selRep.value) return;
      const d = await api('GET', 'reportes/' + selRep.value);
      carpetaRep = ((d.flujo || {}).opciones || {}).carpeta_descargas || '';
      d.pasos.forEach((p, i) => selHasta.appendChild(h('option', { value: i }, 'Antes del paso ' + (i + 1) + ': ' + p.descripcion.slice(0, 80))));
    }
    selRep.addEventListener('change', () => cargarPasos().catch(errorToast));
    function pintarAcciones() {
      acciones.replaceChildren(
        boton('Abrir el navegador', iniciar, 'primario', { disabled: listo }),
        boton('Mapear toda la página', () => mapear('todo'), listo ? 'primario' : '', { disabled: !listo }),
        boton('Mapear una parte…', parte, '', { disabled: !listo }),
        boton('↻ Pestañas', refrescarPestanas, 'chico', { disabled: !listo, title: 'Vuelve a mirar qué pestañas hay abiertas en el navegador del mapeo' }),
        boton('Terminar', async () => { try { await api('POST', 'mapa/terminar', {}); } catch (e) { errorToast(e); } listo = false; pintarAcciones(); }, '', { disabled: !listo }));
    }
    async function iniciar() {
      try {
        const d = await api('POST', 'mapa/iniciar', { reporte_id: selRep.value ? parseInt(selRep.value, 10) : null, url: url.value,
          hasta: selHasta.value === '' ? null : parseInt(selHasta.value, 10) });
        estado.textContent = 'Abriendo el navegador' + (d.hasta !== null && d.hasta !== undefined ? ' y ejecutando los pasos 1 a ' + d.hasta : '') + '… (inicia sesión si te lo pide).';
      } catch (e) { errorToast(e); }
    }
    async function mapear(alcance, selector, marco) {
      estado.textContent = 'Buscando los filtros (en la página y en sus marcos; se abren las listas para leer sus opciones)…';
      avisosMapa.replaceChildren();
      try {
        const d = await api('POST', 'mapa/mapear', { alcance, selector, marco: marco || [], reporte_id: selRep.value ? parseInt(selRep.value, 10) : null,
          pestana: selPestana.value === '' ? null : parseInt(selPestana.value, 10) });
        pintarPestanas(d.pestanas);
        pintarAvisos(d);
        if (!d.filtros.length) {
          estado.textContent = 'No se encontró ningún filtro en ' + d.url + ' (pestaña ' + ((d.pestana || 0) + 1) + ').';
          resultado.replaceChildren();
          mapa = null;
          return;
        }
        mapa = d;
        mapa.alcance = alcance === 'parte' ? (selector || 'parte') : 'todo';
        memMapa = new Map();
        const enMarcos = mapa.filtros.filter((f) => (f.marco || []).length).length;
        estado.textContent = 'Se encontraron ' + mapa.filtros.length + ' elementos en ' + mapa.url + ' (pestaña ' + ((mapa.pestana || 0) + 1) + ')' +
          (enMarcos ? ', ' + enMarcos + ' dentro de marcos (iframes)' : '') + '.';
        pintarMapa();
      } catch (e) {
        errorToast(e);
        estado.textContent = 'No se pudo mapear: ' + e.message;
        avisosMapa.replaceChildren(h('div', { class: 'alerta error' }, e.message));
      }
    }
    async function parte() {
      estado.textContent = 'En el navegador, pasa el ratón sobre la parte con los filtros y haz clic (Esc cancela).';
      try {
        const d = await api('POST', 'mapa/parte', { pestana: selPestana.value === '' ? null : parseInt(selPestana.value, 10) });
        if (!d.parte) { estado.textContent = 'Cancelado.'; return; }
        await mapear('parte', d.parte.selector, d.parte.marco);     // v3.8: la parte puede estar dentro de un marco (ERP)
      } catch (e) { errorToast(e); }
    }
    const evento = (ev) => {                          // (v3.5: vista viva: llegan aunque se esté en otra sección)
      if (ev.tipo === 'mapa_listo') { listo = true; estado.textContent = 'Listo: ya puedes navegar a mano si hace falta (también abrir el reporte en otra pestaña) y pulsar «Mapear».'; pintarAcciones(); refrescarPestanas(); }
      if (ev.tipo === 'mapa_fin') { listo = false; estado.textContent = ev.error ? 'La sesión terminó: ' + ev.error : 'Sesión de mapeo cerrada.'; pintarAcciones(); }
    };
    // v3.8: lo encontrado como paradas: de arriba abajo, lo que hará el bot.  La X quita (con «Deshacer»), lo que viene sin
    // marcar por defecto queda en «También encontré» y lo que se deja vacío se salta (no genera ningún paso).
    function pintarMapa() {
      const nomsDescarga = [];
      const lista = h('ol', { class: 'paradas', 'data-paradas': '1' });
      const quitados = h('div', { class: 'mapa-quitados oculto', 'data-quitados': '1' });
      const listaTambien = h('ul');
      const tambien = h('section', { class: 'mapa-tambien oculto', 'data-tambien': '1' }, h('h3', null, 'También encontré'), listaTambien);
      const grande = h('div', { class: 'asi-grande', 'data-cuenta-pasos': '1' });
      const resumen = h('p', { class: 'ayuda', 'data-resumen-pasos': '1' });
      let crear = null;
      function refrescar() {
        const dentro = paradas.filter((x) => x.m.incluido);
        let ref = lista.firstChild;
        for (const x of dentro) {          // (sin volver a colocar lo que ya está en su sitio)
          if (x.li === ref) ref = ref.nextSibling; else lista.insertBefore(x.li, ref);
        }
        while (ref) { const sig = ref.nextSibling; ref.remove(); ref = sig; }
        let n = 0, saltos = 0;
        for (const x of dentro) {
          const vacia = x.vacio();
          x.li.classList.toggle('vacia', vacia);
          if (vacia) saltos++; else n++;
          x.num.textContent = vacia ? '–' : String(n);
        }
        grande.textContent = String(n);
        resumen.textContent = (n === 1 ? 'paso hará el bot' : 'pasos hará el bot') + (saltos ? ' y se saltará ' + saltos + (saltos === 1 ? ' vacío.' : ' vacíos.') : '.');
        if (crear) crear.disabled = !n;
        const fuera = paradas.filter((x) => !x.m.incluido);
        const qui = fuera.filter((x) => x.m.porDefecto);
        quitados.classList.toggle('oculto', !qui.length);
        quitados.replaceChildren(...(qui.length ? [h('span', null, 'Quitaste:')] : []), ...qui.map((x) =>
          boton(x.nombre + ' · Deshacer', () => { x.m.incluido = true; refrescar(); }, 'chico', { 'data-deshacer': String(x.f.k) })));
        const tam = fuera.filter((x) => !x.m.porDefecto);
        tambien.classList.toggle('oculto', !tam.length);
        const filaTam = (x) => h('li', null, chip(x.tipoTxt, 'info'), h('span', { class: 'nom' }, x.nombre),
          boton('＋ Añadir', () => { x.m.incluido = true; refrescar(); }, 'chico', { 'data-anadir-parada': String(x.f.k) }));
        const grupos = [...new Set(tam.map((x) => x.f.grupo).filter(Boolean))];      // (primero lo que no tiene grupo)
        listaTambien.replaceChildren(...tam.filter((x) => !x.f.grupo).map(filaTam),
          ...grupos.flatMap((g) => [h('li', { class: 'mapa-grupo', 'data-grupo': g }, g), ...tam.filter((x) => x.f.grupo === g).map(filaTam)]));
      }
      const paradas = mapa.filtros.map((f) => {
        // (f.secundario: lo secundario de la página va a «También encontré», aunque sea una lista o una fecha)
        const porDefecto = !f.secundario && (['lista', 'lista_nativa', 'fecha'].includes(f.tipo) || (f.tipo === 'accion' && /generar|exportar|descargar|consultar|buscar|ver/i.test(f.etiqueta)) || (f.tipo === 'pestana' && f.activo));
        if (!memMapa.has(f.k)) memMapa.set(f.k, { incluido: porDefecto, porDefecto });
        const m = memMapa.get(f.k);
        const conf = h('div', { class: 'mapa-config' });
        const e = { k: f.k, traer: { get checked() { return m.incluido; } } };
        let vacio = () => false;
        if (f.tipo === 'lista' || f.tipo === 'lista_nativa') {
          const s = h('select', { 'aria-label': 'Estrategia' }, ['fija', 'mas_reciente', 'primera', 'ultima', 'contiene', 'por_fecha'].map((v) => h('option', { value: v }, E.ayuda.estrategias[v])));
          s.value = m.estrategia || (/corte|semana|periodo|período|mes|fecha/i.test(f.etiqueta) ? 'mas_reciente' : 'fija');
          const valor = (f.opciones && f.opciones.length)
            ? h('select', { 'aria-label': 'Opción' }, f.valor ? null : h('option', { value: '' }, '(sin elegir)'), f.opciones.map((x) => h('option', { value: x }, x)))
            : h('input', { type: 'text', value: f.valor || '', 'aria-label': 'Texto' });
          if (f.valor) valor.value = f.valor;
          if (m.valor !== undefined) valor.value = m.valor;
          const actualizar = boton('Actualizar opciones', async () => {
            estado.textContent = 'Eligiendo «' + valor.value + '» y volviendo a leer las listas siguientes…';
            try { const d = await api('POST', 'mapa/actualizar', { k: f.k, valor: valor.value }); mapa.filtros = d.filtros; pintarMapa(); estado.textContent = 'Opciones actualizadas.'; }
            catch (err) { errorToast(err); }
          }, 'chico', { title: 'Elige esta opción en la página y vuelve a leer las listas que dependen de ella' });
          if (m.fecha === undefined) m.fecha = '{hoy:' + FORMATO_DEFECTO + '}';
          const chipF = h('button', { type: 'button', class: 'chip-fecha', 'data-fecha-parada': String(f.k) });
          const pintarValor = () => {
            valor.classList.toggle('oculto', !['fija', 'contiene'].includes(s.value));
            chipF.classList.toggle('oculto', s.value !== 'por_fecha');
            chipF.replaceChildren(ico('calendario'), 'Fecha: ' + fechaEnChip({ valor: m.fecha }));
          };
          chipF.addEventListener('click', () => elegirFecha({ titulo: '¿De qué fecha lo quieres?', valor: m.fecha, formato: FORMATO_DEFECTO, lista: true, alAceptar: (v) => { m.fecha = v; pintarValor(); refrescar(); } }));
          const alCambiar = () => { m.estrategia = s.value; m.valor = valor.value; pintarValor(); refrescar(); };
          s.addEventListener('change', alCambiar);
          valor.addEventListener('change', alCambiar);
          valor.addEventListener('input', alCambiar);
          pintarValor();
          conf.append(s, valor, chipF, actualizar);
          e.leer = () => ({ estrategia: s.value, valor: ['fija', 'contiene'].includes(s.value) ? valor.value : (s.value === 'por_fecha' ? m.fecha : '') });
          vacio = () => ['fija', 'contiene'].includes(s.value) && !String(valor.value).trim();
        } else if (f.tipo === 'fecha') {
          // v3.8: las tres tarjetas y el calendario: «hoy» con el formato del campo de la web, o cualquier otra fecha
          const a = analizarFecha(f.valor);
          const fmt = ({ date: '%Y-%m-%d', 'datetime-local': '%Y-%m-%dT00:00', month: '%Y-%m' })[(f.tipo_campo || '').toLowerCase()] ||
            (a.modo === 'fija' ? a.formato : FORMATO_DEFECTO);
          if (m.fecha === undefined) m.fecha = '{hoy:' + fmt + '}';
          const chipF = h('button', { type: 'button', class: 'chip-fecha', 'data-fecha-parada': String(f.k), 'aria-label': 'Fecha que se escribe en «' + (f.etiqueta || 'la fecha') + '»' });
          const pintarValor = () => chipF.replaceChildren(ico('calendario'), 'Fecha: ' + fechaEnChip({ valor: m.fecha }));
          chipF.addEventListener('click', () => elegirFecha({ titulo: '¿De qué fecha lo quieres?', valor: m.fecha, formato: fmt, alAceptar: (v) => { m.fecha = v; pintarValor(); refrescar(); } }));
          pintarValor();
          conf.append(chipF);
          e.leer = () => ({ fecha: 'plantilla', valor: m.fecha });
        } else if (f.tipo === 'texto') {
          const v = h('input', { type: 'text', value: m.valor !== undefined ? m.valor : (f.valor || ''), 'aria-label': 'Texto' });
          v.addEventListener('input', () => { m.valor = v.value; refrescar(); });
          conf.append(v); e.leer = () => ({ valor: v.value });
          vacio = () => !v.value.trim();
          if (f.busqueda) {
            conf.append(boton('Leer opciones de la búsqueda', async () => {
              estado.textContent = 'Abriendo la búsqueda de «' + f.etiqueta + '» y leyendo sus filas…';
              try { const d = await api('POST', 'mapa/busqueda', { k: f.k }); mapa.filtros = d.filtros; pintarMapa(); estado.textContent = 'Filas de la búsqueda leídas.'; }
              catch (err) { errorToast(err); }
            }, 'chico', { title: 'Pulsa la lupa en la página, lee las filas de la ventanita y la cierra' }));
          }
        } else if (f.tipo === 'casilla') {
          const v = h('input', { type: 'checkbox', checked: !!f.marcado, 'aria-label': 'Marcada' });
          conf.append(h('label', { class: 'interruptor' }, v, 'marcada')); e.leer = () => ({ marcado: v.checked });
        } else if (f.tipo === 'accion') {
          const s = h('select', { 'aria-label': 'Qué hacer' }, h('option', { value: 'clic' }, 'Hacer clic'), h('option', { value: 'descargar' }, 'Hacer clic y descargar el archivo'));
          s.value = f.descarga ? 'descargar' : 'clic';
          const nom = h('input', { type: 'text', value: conExt(archivoMapa.nombre), 'aria-label': 'Nombre del archivo' });
          nomsDescarga.push(nom);
          const pintar = () => nom.classList.toggle('oculto', s.value !== 'descargar');
          s.addEventListener('change', pintar); pintar();
          conf.append(s, nom); e.leer = () => ({ modo: s.value, nombre: nom.value });
        } else { e.leer = () => ({}); }
        e.traer = { get checked() { return m.incluido; } };
        f._e = e;
        const ops = f.opciones && f.opciones.length ? h('details', null, h('summary', null, f.opciones.length + ' opciones'), h('ol', { class: 'opciones-lista' }, f.opciones.map((x) => h('li', null, x)))) :
          (f.error ? h('span', { class: 'ayuda' }, f.error) : (f.opciones ? h('span', { class: 'ayuda' }, 'sin opciones (¿depende de otra lista? usa «Actualizar opciones» en esa)') : null));
        const tipoTxt = f.busqueda ? 'Texto con búsqueda' : (({ pestana: 'Pestaña', lista: 'Lista', lista_nativa: 'Lista', fecha: 'Fecha', texto: 'Texto', casilla: 'Casilla', accion: 'Botón' })[f.tipo] || f.tipo);
        const nombre = f.etiqueta || '(sin nombre)';
        const num = h('div', { class: 'parada-num', 'aria-hidden': 'true' });
        const actual = f.tipo === 'pestana' ? (f.activo ? 'La pestaña que está abierta' : '') : (f.valor && f.tipo !== 'lista' && f.tipo !== 'lista_nativa' && f.tipo !== 'fecha' ? 'Ahora: ' + f.valor : '');
        const li = h('li', { class: 'parada', 'data-parada': String(f.k), 'data-tipo': f.tipo }, num,
          h('div', { class: 'parada-tarj' },
            h('span', { class: 'parada-tipo' }, tipoTxt + ((f.marco || []).length ? ' · en un marco' : '')),
            h('div', { class: 'parada-nombre' }, nombre),
            h('button', { type: 'button', class: 'parada-quitar', 'aria-label': 'Quitar «' + nombre + '»', title: 'Quitar este paso', 'data-quitar': String(f.k), onclick: () => { m.incluido = false; refrescar(); } }, ico('cerrar')),
            h('div', { class: 'parada-cuerpo' }, actual ? h('div', { class: 'ayuda' }, actual) : null,
              h('div', { class: 'parada-vacio', 'data-sin-elegir': '1' }, 'Sin elegir: se lo salta'),
              conf.childNodes.length ? conf : null, ops)));
        const orden = { pestana: 0, accion: 2 }[f.tipo];
        return { f, m, li, num, nombre, tipoTxt, vacio, clave: [orden === undefined ? 1 : orden, f.orden || 0] };
      });
      paradas.sort((a, b) => a.clave[0] - b.clave[0] || a.clave[1] - b.clave[1]);   // (el orden en el que el bot crea los pasos)
      const comp = mapa.comparacion;
      let cambios = null;
      if (comp && (comp.nuevos.length || comp.quitados.length || comp.opciones.length)) {
        cambios = h('div', { class: 'alerta aviso' }, 'Cambios desde el mapa anterior (' + mapa.anterior + '): ',
          comp.nuevos.length ? 'filtros nuevos: ' + comp.nuevos.join(', ') + '. ' : '', comp.quitados.length ? 'ya no están: ' + comp.quitados.join(', ') + '. ' : '',
          comp.opciones.map((o) => 'En «' + o.etiqueta + '»' + (o.nuevas.length ? ' hay opciones nuevas: ' + o.nuevas.join(', ') : '') + (o.quitadas.length ? '; quitadas: ' + o.quitadas.join(', ') : '') + '. '));
      } else if (comp) cambios = h('div', { class: 'alerta ok' }, 'Sin cambios desde el mapa anterior (' + mapa.anterior + ').');
      const destino = h('select', { 'aria-label': 'Destino' }, h('option', { value: 'nuevo' }, 'Crear un reporte nuevo'),
        selRep.value ? h('option', { value: 'reemplazar' }, 'Reemplazar los filtros del reporte elegido (desde el punto de mapeo)') : null,
        selRep.value ? h('option', { value: 'anadir' }, 'Añadir al reporte elegido (en el punto de mapeo)') : null);
      const nombre = h('input', { type: 'text', value: (selRep.value ? selRep.options[selRep.selectedIndex].text + ' (mapeado)' : 'Reporte mapeado'), 'aria-label': 'Nombre del reporte nuevo' });
      const etqNombre = h('label', null, 'Nombre del reporte');
      destino.addEventListener('change', () => { const no = destino.value !== 'nuevo'; nombre.classList.toggle('oculto', no); etqNombre.classList.toggle('oculto', no); });
      const elecciones = () => mapa.filtros.filter((f) => f._e && f._e.traer.checked).map((f) => Object.assign({ k: f.k }, f._e.leer()));
      // v3.7: nombre y carpeta del archivo para los botones «Hacer clic y descargar el archivo» (cambia los que no se
      // hayan cambiado a mano en su fila) y la carpeta del reporte
      const nomArch = h('input', { type: 'text', value: archivoMapa.nombre, placeholder: '(vacío = el nombre que da la web)', 'aria-label': 'Nombre del archivo del reporte', 'data-nombre-archivo': 'mapa' });
      const carpetaArch = h('input', { type: 'text', value: archivoMapa.carpeta === null ? carpetaRep : archivoMapa.carpeta, 'aria-label': 'Carpeta del reporte' });
      const vistaArch = vistaArchivo(() => ({ archivo: 'descargar', texto: nomArch.value, carpeta: carpetaArch.value.trim(),
        reporte: destino.value === 'nuevo' ? (nombre.value.trim() || 'Reporte mapeado') : selRep.options[selRep.selectedIndex].text }));
      nomArch.addEventListener('input', () => {
        const antes = conExt(archivoMapa.nombre);
        archivoMapa.nombre = nomArch.value;
        nomsDescarga.forEach((x) => { if (x.value === antes) x.value = conExt(nomArch.value); });
        vistaArch.act();
      });
      carpetaArch.addEventListener('input', () => { archivoMapa.carpeta = carpetaArch.value; vistaArch.act(); });
      [nombre, destino].forEach((x) => x.addEventListener(x === destino ? 'change' : 'input', vistaArch.act));
      const zonaArchivo = h('div', { 'data-archivo-descargado': 'mapa' }, h('h4', null, 'Archivo descargado'),
        h('div', { class: 'formulario' },
          h('label', null, 'Nombre del archivo'), h('div', null, nomArch, vistaArch.el, campoNombreArchivo(nomArch, { defecto: NOMBRE_ARCHIVO_DEFECTO }),
            h('div', { class: 'ayuda' }, 'Sin la extensión (se pone sola). {reporte} = el nombre del reporte. Se puede cambiar después en el editor.')),
          h('label', null, 'Carpeta'), h('div', null, campoRuta(carpetaArch, { titulo: 'Carpeta de descargas del reporte' }),
            h('div', { class: 'ayuda' }, 'Vacío = la carpeta de descargas del bot.'))));
      const limpio = () => mapa.filtros.map((f) => { const x = Object.assign({}, f); delete x._e; return x; });
      crear = boton('Guardar el reporte', async () => {
        try {
          const cuerpo = { filtros: limpio(), elecciones: elecciones(), destino: destino.value, nombre: nombre.value,
            reporte_id: selRep.value ? parseInt(selRep.value, 10) : null, hasta: selHasta.value === '' ? null : parseInt(selHasta.value, 10), url: mapa.url };
          if (archivoMapa.carpeta !== null) cuerpo.carpeta_descargas = carpetaArch.value.trim();     // v3.7 (sin tocar: la de siempre)
          const d = await api('POST', 'mapa/crear_pasos', cuerpo);
          await api('POST', 'mapa/guardar', { reporte_id: d.id, url: mapa.url, alcance: mapa.alcance, filtros: limpio() });
          toast('Reporte «' + d.nombre + '» guardado', 'ok');
          location.hash = '#/editor/' + d.id;
        } catch (e) { errorToast(e); }
      }, 'primario grande crear', { 'data-crear-pasos': '1' });
      resultado.replaceChildren(h('div', { class: 'vista', 'data-mapa-paradas': '1' },
        h('div', { class: 'mapa-cab' }, h('h2', null, 'Esto es lo que encontré. ¿Lo dejo así?'),
          h('p', null, 'El bot hace las paradas de arriba abajo. Toca la X en lo que no quieras. Lo que dejes vacío, se lo salta.')),
        cambios,
        h('div', { class: 'mapa-dos' },
          h('div', null, lista, quitados, tambien),
          h('aside', { class: 'asi-quedara' }, h('h3', null, 'Así quedará'), grande, resumen,
            h('div', { class: 'formulario' }, selRep.value ? h('label', null, 'Dónde se guarda') : null, selRep.value ? destino : null, etqNombre, nombre),
            zonaArchivo, crear))));
      refrescar();
    }
    c.appendChild(panel('Mapear página / Sacar filtros', h('p', { class: 'ayuda' }, 'El bot abre la página (ejecutando el reporte hasta justo antes de sus filtros e iniciando sesión si hace falta), y encuentra sus filtros: pestañas, listas, fechas, casillas y botones como «Generar». Tú eliges cuáles traer y cómo, y el bot crea los pasos.'),
      h('div', { class: 'formulario' }, h('label', null, 'Reporte'), selRep, h('label', null, 'Ejecutar hasta'), h('div', null, selHasta), h('label', null, 'Dirección'), h('div', null, url),
        h('label', null, 'Pestaña'), cajaPestana),
      acciones, estado, avisosMapa));
    c.appendChild(resultado);
    pintarPestanas(null);
    pintarAcciones();
    await cargarPasos();
    return { evento };
  };

  // ------------------------------------------------------------------ Vigilancia
  // v3.3: varias vigilancias.  Tarjeta de una vigilancia y ventana para añadirla o cambiarla.
  function textoFrecuencia(v) {
    if (v.cuando) return v.cuando;                     // v3.4: el horario completo en español (lo calcula el bot)
    return v.frecuencia === 'horas' ? 'cada ' + v.cada_horas + ' h' : (v.frecuencia === 'diaria' ? 'cada día a las ' + v.hora : 'solo con «Revisar ahora»');
  }
  const tieneHorario = (v) => !!(v.programacion && (v.programacion.reglas || []).length);
  // v3.4: crear (o actualizar) la tarea de Windows de una vigilancia con su horario guardado
  async function activarTareaVigilancia(v, recargar) {
    const ok = await crearTareaWindows('vigilancias/' + v.id + '/programar', {}, 'Activar la vigilancia en Windows');
    if (ok && recargar) recargar();
    return ok;
  }
  // v3.6.1: al GUARDAR un horario se crea (o actualiza) su tarea de Windows directamente: guardar ya es la orden (antes
  // salía otra ventana «Falta un paso: activar…» y, si se cerraba, el horario quedaba guardado pero no hacía nada).
  // Si Windows no la crea, se dice claro que NO se ejecutará sola.
  async function activarAlGuardar(ruta, que) {
    try {
      const r = await api('POST', ruta, { confirmar: true });
      toast('Listo: ' + que + ' se ejecutará sola (' + r.descripcion + ').' + (r.arrancada ? ' La de hoy ya está en marcha: te avisa y se ejecuta a las ' + r.arrancada + '.' : ''), 'ok', 10000);
      return true;
    } catch (e) {
      abrirModal({ titulo: 'No se pudo crear la tarea de Windows', contenido: h('div', { class: 'alerta error', 'data-error-tarea': '1' },
        'El horario se guardó, pero Windows no creó la tarea, así que NO se ejecutará sola. ' + (e.message || String(e))),
        botones: [{ texto: 'Cerrar', accion: cerrarModal }] });
      return false;
    }
  }
  // Tras guardar el horario de una vigilancia: se crea o actualiza su tarea de Windows (o se ofrece quitarla).
  async function avisoTrasGuardarVigilancia(vid, cambioHorario, recargar) {
    let v;
    try { v = (await api('GET', 'vigilancias/' + vid)).vigilancia; } catch (e) { if (recargar) recargar(); return; }
    const t = v.tarea || {};
    if (tieneHorario(v) && (!t.existe || cambioHorario)) {
      await activarAlGuardar('vigilancias/' + vid + '/programar', 'la vigilancia «' + (v.nombre || v.objetivo || ('#' + vid)) + '»');
      if (recargar) recargar();
      return;
    }
    if (!tieneHorario(v) && t.existe) {
      abrirModal({ titulo: '¿Quitar la tarea de Windows?', contenido: h('p', null, 'Ahora esta vigilancia solo se revisa con «Revisar ahora», pero en Windows sigue su tarea (' + t.nombres.join(', ') + '), que la seguirá revisando sola.'),
        botones: [{ texto: 'Dejarla', accion: () => { cerrarModal(); if (recargar) recargar(); } },
          { texto: 'Quitar la tarea de Windows', clase: 'primario', accion: async () => { await quitarTareaWindows('vigilancias/' + vid + '/quitar_tarea'); if (recargar) recargar(); } }] });
      return;
    }
    if (recargar) recargar();
  }
  function tarjetaVigilancia(v, obj, recargar) {
    const ops = v.opciones || [];
    const lista = ops.length ? h('ul', { class: 'lista' }, ops.map((o) => h('li', null, h('div', { class: 'crece' }, h('div', null, o.texto),
      h('div', { class: 'sub' }, (o.periodo ? o.periodo + ' · ' : '') + 'vista el ' + o.primera_vez + (o.descargada ? ' · descargada el ' + o.descargada : ''))),
      o.mas_reciente ? chip('más reciente', 'ok') : null,
      o.nueva && !o.descargada ? chip(o.sin_orden ? 'nueva (sin fecha)' : 'nueva', 'marca') : (o.descargada ? chip('descargada', 'ok') : null),
      boton('Descargar', async () => { try { await api('POST', 'vigilancias/' + v.id + '/descargar', { texto: o.texto }); toast('Descargando «' + o.texto + '»…'); } catch (e) { errorToast(e); } }, 'chico')))) :
      h('p', { class: 'vacio' }, 'Todavía no se ha revisado: pulsa «Revisar ahora» (la primera revisión solo apunta lo que hay).');
    const programar = async () => {
      if (!tieneHorario(v)) { toast('Elige primero cuándo revisar («Cambiar…» → Cuándo)', 'aviso'); modalVigilancia(obj, v, recargar); return; }
      await activarTareaVigilancia(v, recargar);
    };
    // v3.4: ¿tiene tarea de Windows? (lo que hace que se revise sola)
    const t = v.tarea || {};
    let estadoTarea = null;
    if (tieneHorario(v) && v.activa) {
      estadoTarea = t.existe ? h('div', { class: 'sub t-ok', 'data-tarea-vigilancia': 'si' }, 'Tarea de Windows creada' + (t.proxima ? ' (próxima según Windows: ' + t.proxima + ')' : '') + (v.proxima ? ' · próxima revisión: ' + v.proxima : ''))
        : h('div', { class: 'alerta aviso', 'data-tarea-vigilancia': 'no' }, 'Tiene horario (' + v.cuando + '), pero NO tiene tarea en Windows: no se revisará sola. ',
          boton('Activar: crear la tarea en Windows', programar, 'chico primario', { 'data-activar-tarea': String(v.id) }));
    } else if (!tieneHorario(v) && t.existe) {
      estadoTarea = h('div', { class: 'alerta aviso', 'data-tarea-vigilancia': 'sobra' }, 'Solo se revisa con «Revisar ahora», pero en Windows sigue su tarea (' + t.nombres.join(', ') + '). ',
        boton('Quitar la tarea de Windows', async () => { if (await quitarTareaWindows('vigilancias/' + v.id + '/quitar_tarea')) recargar(); }, 'chico'));
    }
    return h('div', { class: 'vigilancia-tarjeta', 'data-vigilancia': String(v.id) },
      h('div', { class: 'fila' }, h('strong', null, v.que || ''), v.etiqueta ? chip(v.etiqueta, 'info') : null,
        v.activa ? chip(textoFrecuencia(v), 'ok') : chip('pausada', 'aviso'), v.auto_descargar ? chip('descarga sola') : null,
        v.nuevas && v.nuevas.length ? chip(v.nuevas.length + ' nueva(s)', 'marca') : null, h('span', { class: 'crece' }), h('span', { class: 'sub' }, '#' + v.id)),
      (v.valores_texto && v.valores_texto.length) ? h('div', { class: 'sub' }, 'Con: ' + v.valores_texto.join(' · ') + (v.favorito ? ' (y el favorito «' + v.favorito + '»)' : '')) :
        (v.favorito ? h('div', { class: 'sub' }, 'Con los valores del favorito «' + v.favorito + '»') : null),
      h('div', { class: 'sub' }, v.ultima_revision ? 'Última revisión: ' + v.ultima_revision + ' — ' + v.ultimo_resultado : 'Todavía no se ha revisado'),
      estadoTarea,
      h('div', { class: 'fila' },
        boton('Revisar ahora', async () => { try { await api('POST', 'vigilancias/' + v.id + '/revisar', {}); toast('Revisando «' + v.objetivo + '»' + (v.etiqueta ? ' (' + v.etiqueta + ')' : '') + '…'); } catch (e) { errorToast(e); } }, 'chico primario'),
        boton('Cambiar…', () => modalVigilancia(obj, v, recargar), 'chico'),
        boton(v.activa ? 'Pausar' : 'Activar', async () => { try { await api('PUT', 'vigilancias/' + v.id, { activa: !v.activa }); recargar(); } catch (e) { errorToast(e); } }, 'chico'),
        tieneHorario(v) ? boton(t.existe ? 'Actualizar la tarea en Windows…' : 'Crear la tarea en Windows…', programar, 'chico') : null,
        t.existe && tieneHorario(v) ? boton('Quitar la tarea', async () => { if (await quitarTareaWindows('vigilancias/' + v.id + '/quitar_tarea')) recargar(); }, 'chico') : null,
        boton('Borrar', async () => {
          if (!(await confirmar('Borrar vigilancia', '¿Borrar esta vigilancia de «' + v.objetivo + '»' + (v.etiqueta ? ' (' + v.etiqueta + ')' : '') + '? (sus opciones vistas se olvidan)', 'Borrar', true))) return;
          try { await api('DELETE', 'vigilancias/' + v.id); recargar(); } catch (e) { errorToast(e); }
        }, 'chico peligro')),
      h('div', { class: 'sub' }, 'Opciones vistas' + (v.n_opciones ? ' (' + v.n_opciones + ')' : '') + (ops.length ? ' — de la más reciente a la más antigua' + (v.n_opciones > ops.length ? ' (las ' + ops.length + ' más recientes)' : '') : '')),
      lista);
  }
  // obj = {tipo: 'reporte', id, nombre, pasos: [[i, texto]], listas_clic: [{par, texto, descripcion, periodo}],
  //        selects: [{paso, texto, descripcion, periodo}]} | {tipo: 'pagina', id, nombre, listas: [{id, nombre}], favoritos: [nombres]}
  // v3.3.1: las listas de un reporte grabadas como clics («abrir la lista» + «clic en la opción») o como lista nativa se
  // ofrecen directamente; al añadir la vigilancia el bot las convierte en «Elegir opción» (con copia en Versiones).
  async function modalVigilancia(obj, v, alGuardar) {
    v = v || {};
    const esPagina = obj.tipo === 'pagina';
    const sinConvertir = {};
    const opcionesReporte = esPagina ? [] : [
      ...(obj.pasos || []).map(([i, t]) => h('option', { value: String(i) }, 'Paso ' + (i + 1) + ': ' + t)),
      ...(v.id ? [] : (obj.listas_clic || []).map((x) => { sinConvertir['par:' + x.par] = x; return h('option', { value: 'par:' + x.par }, x.descripcion); })),
      ...(v.id ? [] : (obj.selects || []).map((x) => { sinConvertir['sel:' + x.paso] = x; return h('option', { value: 'sel:' + x.paso }, x.descripcion); }))];
    const que = esPagina ? h('select', { 'aria-label': 'Lista vigilada' }, obj.listas.map((f) => h('option', { value: f.id }, f.nombre)))
      : h('select', { 'aria-label': 'Filtro vigilado' }, opcionesReporte);
    const estrategia = h('select', { 'aria-label': 'Al ejecutar el reporte, elegir' },
      h('option', { value: 'mas_reciente' }, 'la opción más reciente (p. ej. el último corte)'), h('option', { value: 'fija' }, 'siempre la opción grabada'));
    const zonaConvertir = h('div', { class: 'alerta oculto', 'data-convertir-lista': '1' });
    const pintarConvertir = () => {
      const x = sinConvertir[que.value];
      zonaConvertir.classList.toggle('oculto', !x);
      if (!x) return;
      estrategia.value = x.periodo ? 'mas_reciente' : 'fija';
      zonaConvertir.replaceChildren(h('div', null, 'Esta lista está grabada como clics (o como lista sencilla). Al añadir la vigilancia, el bot la convierte en un paso «Elegir opción» del reporte (antes guarda una copia en «Versiones anteriores», para volver atrás si hace falta).'),
        h('div', { class: 'formulario', style: 'margin-top:8px' }, h('label', null, 'Al ejecutar el reporte, elegir'), estrategia),
        h('div', { class: 'sub' }, 'Opción grabada: «' + x.texto + '»'));
    };
    if (!esPagina) que.addEventListener('change', pintarConvertir);
    if (esPagina) {
      // por defecto, la lista que parece un corte/periodo (la que suele vigilarse); si no, la última
      const periodica = obj.listas.find((f) => /corte|periodo|período|semana|mes|fecha/i.test(f.nombre || ''));
      que.value = v.filtro || (periodica || obj.listas[obj.listas.length - 1] || {}).id || '';
    }
    else if (v.paso !== undefined && v.paso !== null) que.value = String(v.paso);
    // v3.6.1: la lista que CAMBIA (cortes/periodos: «45 - 2026 (…)»): se propone por defecto (antes se proponía la primera,
    // p. ej. la del tipo de reporte, que nunca tiene nada nuevo) y se avisa si se elige otra
    const pasoPeriodo = esPagina ? null : (obj.pasos || []).find(([, t]) => /más reciente|corte|periodo|período|semana/i.test(t || ''));
    const clicPeriodo = esPagina ? null : (obj.listas_clic || []).find((x) => x.periodo);
    const selPeriodo = esPagina ? null : (obj.selects || []).find((x) => x.periodo);
    const valorPeriodo = pasoPeriodo ? String(pasoPeriodo[0]) : clicPeriodo ? 'par:' + clicPeriodo.par : selPeriodo ? 'sel:' + selPeriodo.paso : '';
    const avisoLista = h('div', { class: 'alerta aviso oculto', 'data-aviso-lista-fija': '1' });
    const pintarAvisoLista = () => {
      const otra = !!valorPeriodo && que.value !== valorPeriodo;
      avisoLista.classList.toggle('oculto', !otra);
      if (otra) avisoLista.replaceChildren('Esta lista casi nunca cambia, así que la vigilancia no encontrará nada nuevo. Para vigilar los cortes o periodos elige «',
        [...que.options].find((o) => o.value === valorPeriodo).textContent, '».');
    };
    if (!esPagina && !(v.paso !== undefined && v.paso !== null) && valorPeriodo) { que.value = valorPeriodo; pintarConvertir(); }
    if (!esPagina) { que.addEventListener('change', pintarAvisoLista); pintarAvisoLista(); }
    const nombre = h('input', { type: 'text', value: v.nombre || '', placeholder: '(opcional) p. ej. Cartera', 'aria-label': 'Nombre de la vigilancia' });
    const fav = esPagina ? h('select', { 'aria-label': 'Favorito' }, h('option', { value: '' }, '(valores por defecto)'), (obj.favoritos || []).map((n) => h('option', { value: n }, n))) : null;
    if (fav) fav.value = v.favorito || '';
    const zonaValores = h('div', { class: 'formulario', 'data-valores-vigilancia': '1' });
    const selValores = {};
    let filtrosForm = [];
    const valoresPrevios = Object.assign({}, v.valores || {});
    async function pintarValores() {
      if (!esPagina) return;
      if (!filtrosForm.length) {
        try { filtrosForm = (await api('POST', 'paginas/' + obj.id + '/formulario', { seleccion: {} })).filtros || []; } catch (e) { filtrosForm = []; }
      }
      for (const k of Object.keys(selValores)) { valoresPrevios[k] = leerValor(k) || valoresPrevios[k]; delete selValores[k]; }
      const pos = filtrosForm.findIndex((f) => f.id === que.value);
      const previos = filtrosForm.slice(0, pos < 0 ? 0 : pos).filter((f) => ['lista', 'lista_nativa', 'pestana'].includes(f.tipo));
      zonaValores.replaceChildren();
      for (const f of previos) {
        const s2 = h('select', { 'aria-label': f.nombre, 'data-filtro': f.id }, h('option', { value: '' }, '(del favorito / por defecto)'),
          (f.opciones || []).map((o) => h('option', { value: o.texto }, o.texto)));
        const prev = valoresPrevios[f.id];
        if (prev && prev.valor) {
          if (![...s2.options].some((o) => o.value === prev.valor)) s2.appendChild(h('option', { value: prev.valor }, prev.valor));
          s2.value = prev.valor;
        }
        selValores[f.id] = s2;
        zonaValores.append(h('label', null, f.nombre), s2);
      }
      if (!previos.length) zonaValores.append(h('label', null, ''), h('div', { class: 'ayuda' }, 'Esta lista no tiene filtros antes: no hace falta elegir otros valores.'));
    }
    function leerValor(k) { const s2 = selValores[k]; return s2 && s2.value ? { estrategia: 'fija', valor: s2.value } : null; }
    que.addEventListener('change', () => pintarValores());
    const activa = h('input', { type: 'checkbox', checked: v.id ? !!v.activa : true, 'aria-label': 'Vigilancia activa' });
    // v3.6.1: una vigilancia nueva descarga sola lo nuevo (lo que se espera de ella); se puede desmarcar
    const auto = h('input', { type: 'checkbox', checked: v.id ? !!v.auto_descargar : true, 'aria-label': 'Descargar automáticamente lo nuevo' });
    const sinFecha = h('input', { type: 'checkbox', checked: !!v.descargar_sin_fecha, 'aria-label': 'Descargar también opciones nuevas sin fecha' });
    // v3.4: «Cuándo» completo (días, varias horas, horarios distintos por día, cada N horas en un horario, mensual…)
    const ed = editorCuando(v.programacion || { reglas: [] }, { textoNunca: 'Solo cuando pulse «Revisar ahora»' });
    const progAntes = JSON.stringify(v.programacion || { reglas: [] });
    const guardar = async () => {
      const prog = ed.leer();
      const vp = await ed.comprobar();
      if (vp && !vp.valida) { toast(vp.error, 'error'); return; }
      const datos = { nombre: nombre.value.trim(), activa: activa.checked, auto_descargar: auto.checked, descargar_sin_fecha: sinFecha.checked,
        programacion: prog };
      if (esPagina) {
        const valores = {};
        for (const k of Object.keys(selValores)) { const x = leerValor(k); if (x) valores[k] = x; }
        Object.assign(datos, { pagina_id: obj.id, filtro: que.value, favorito: fav.value, valores });
      } else if (que.value.startsWith('par:')) Object.assign(datos, { reporte_id: obj.id, par: parseInt(que.value.slice(4), 10), estrategia: estrategia.value });
      else if (que.value.startsWith('sel:')) Object.assign(datos, { reporte_id: obj.id, seleccionar: parseInt(que.value.slice(4), 10), estrategia: estrategia.value });
      else Object.assign(datos, { reporte_id: obj.id, paso: parseInt(que.value, 10) });
      try {
        const r = v.id ? await api('PUT', 'vigilancias/' + v.id, datos) : await api('POST', 'vigilancias', datos);
        cerrarModal(); toast(v.id ? 'Vigilancia guardada' : 'Vigilancia añadida', 'ok');
        const guardada = r.vigilancia || {};
        const cambio = JSON.stringify(guardada.programacion || { reglas: [] }) !== progAntes;
        if (guardada.id && guardada.activa) await avisoTrasGuardarVigilancia(guardada.id, cambio && !!v.id, alGuardar);
        else if (alGuardar) alGuardar();
      } catch (e) { errorToast(e); }
    };
    abrirModal({ titulo: (v.id ? 'Cambiar la vigilancia' : 'Añadir vigilancia') + ' — ' + obj.nombre, ancho: true, contenido: h('div', { 'data-modal-vigilancia': '1' },
      h('p', { class: 'ayuda' }, esPagina ? 'Elige la lista que se vigila y, si quieres, con qué valores en los filtros de antes (p. ej. «Seleccione reporte» = «Cartera General»). Puedes añadir otra vigilancia de la misma lista con otros valores: cada una tiene sus opciones vistas, sus avisos y su descarga.' :
        'Elige la lista del reporte que se vigila. Puedes vigilar varias listas del mismo reporte.'),
      h('div', { class: 'formulario' }, h('label', null, esPagina ? 'Lista vigilada' : 'Filtro vigilado'), que, h('label', null, 'Nombre (opcional)'), nombre,
        esPagina ? h('label', null, 'Con los valores de') : null, fav),
      esPagina ? null : avisoLista,
      esPagina ? null : zonaConvertir,
      esPagina ? h('h3', null, 'Valores de los filtros de antes') : null, zonaValores,
      h('div', { class: 'formulario' }, h('label', null, 'Vigilancia activa'), activa,
        h('label', null, 'Descargar automáticamente lo nuevo'), h('div', null, auto, h('div', { class: 'ayuda' }, 'Solo lo MÁS RECIENTE que lo ya conocido cuenta como nuevo; si aparece un corte antiguo (p. ej. «45 - 2023») se apunta sin avisar.')),
        h('label', null, 'Descargar también opciones nuevas sin fecha'), sinFecha),
      h('h3', null, 'Cuándo revisar'),
      h('p', { class: 'ayuda' }, 'Al guardar con un horario, el bot te ofrece crear la tarea en Windows: es la tarea la que hace que se revise sola.'),
      ed.caja),
      botones: [{ texto: 'Cancelar', accion: cerrarModal }, { texto: v.id ? 'Guardar' : 'Añadir vigilancia', clase: 'primario', accion: guardar }] });
    if (!esPagina) pintarConvertir();
    await pintarValores();
  }

  // v3.3.1: «＋ Añadir vigilancia» (arriba): elegir CUALQUIER reporte guardado o Página y después la lista.
  function objetoVigilable(x, tipo) {
    return tipo === 'pagina' ? { tipo: 'pagina', id: x.id, nombre: x.nombre, listas: x.listas, favoritos: x.favoritos }
      : { tipo: 'reporte', id: x.id, nombre: x.nombre, pasos: x.pasos, listas_clic: x.listas_clic || [], selects: x.selects || [] };
  }
  function modalElegirVigilable(d, recargar) {
    const items = [...(d.paginas || []).map((x) => ({ x, tipo: 'pagina' })), ...(d.reportes || []).map((x) => ({ x, tipo: 'reporte' }))];
    const buscar = h('input', { type: 'search', placeholder: 'Buscar un reporte o una página…', 'aria-label': 'Buscar un reporte o una página' });
    const lista = h('ul', { class: 'lista', 'data-candidatos-vigilancia': '1' });
    const explicacion = h('div', { class: 'alerta aviso oculto', 'data-sin-listas': '1' });
    const describir = ({ x, tipo }) => {
      if (tipo === 'pagina') return x.listas.length ? x.listas.length + ' lista(s): ' + x.listas.map((f) => f.nombre).join(', ') : 'sin listas';
      const n = (x.pasos || []).length + (x.listas_clic || []).length + (x.selects || []).length;
      if (!n) return 'sin listas';
      return n + ' lista(s)' + ((x.listas_clic || []).length ? ' (' + x.listas_clic.length + ' grabada(s) como clics: se convierten al añadir)' : '');
    };
    const elegir = ({ x, tipo }) => {
      const conListas = tipo === 'pagina' ? x.listas.length : x.con_listas;
      if (!conListas) {
        explicacion.classList.remove('oculto');
        explicacion.replaceChildren(h('div', null, '«' + x.nombre + '» no tiene ninguna lista (desplegable) en sus ' + (tipo === 'pagina' ? 'filtros' : 'pasos') + ': no hay nada que vigilar.'),
          h('div', null, 'Si la página tiene listas (p. ej. «Elegir corte»), ábrela con «Mapear página», pulsa «Mapear» y guarda el reporte: después podrás vigilar sus listas aquí.'),
          h('div', { class: 'fila', style: 'margin-top:8px' }, boton('Ir a «Mapear página»', () => { cerrarModal(); location.hash = '#/mapear'; }, 'chico')));
        return;
      }
      cerrarModal();
      modalVigilancia(objetoVigilable(x, tipo), null, recargar);
    };
    const pintar = () => {
      const t = buscar.value.trim().toLowerCase();
      const vis = items.filter(({ x }) => !t || x.nombre.toLowerCase().includes(t));
      lista.replaceChildren(...(vis.length ? vis.map((it) => h('li', { class: 'clic', 'data-candidato': it.tipo + '-' + it.x.id, onclick: () => elegir(it) },
        h('div', { class: 'crece' }, h('div', null, it.x.nombre, ' ', it.tipo === 'pagina' ? chip('página', 'info') : chip('reporte')),
          h('div', { class: 'sub' }, describir(it))), boton('Elegir', (ev) => { ev.stopPropagation(); elegir(it); }, 'chico'))) :
        [h('li', { class: 'vacio' }, items.length ? 'Ningún reporte ni página se llama así.' : 'Todavía no hay reportes ni páginas guardados. Graba un reporte o usa «Mapear página».')]));
    };
    buscar.addEventListener('input', pintar);
    pintar();
    abrirModal({ titulo: 'Añadir vigilancia', ancho: true, contenido: h('div', { 'data-modal-elegir-vigilancia': '1' },
      h('p', { class: 'ayuda' }, 'Elige el reporte o la Página que tiene la lista que quieres vigilar (p. ej. «Elegir corte»). Después eliges la lista y cada cuánto revisarla.'),
      buscar, explicacion, h('div', { style: 'max-height:50vh; overflow:auto; margin-top:8px' }, lista)),
      botones: [{ texto: 'Cancelar', accion: cerrarModal }] });
  }

  RUTAS.vigilancia = async (c) => {
    let d = await api('GET', 'vigilancia');
    // v3.5: tras guardar, pausar o borrar se piden los datos otra vez y solo cambian las tarjetas afectadas
    const recargar = () => actualizar();
    const revisarTodas = boton('↻ Revisar todas', async () => {
      try { await api('POST', 'vigilancias/revisar', {}); toast('Revisando todas las vigilancias activas…'); } catch (e) { errorToast(e); }
    });
    const cuenta = h('span', { class: 'sub' });
    const secciones = h('div', { class: 'vista' });
    c.append(h('div', { class: 'barra-herr' }, boton('＋ Añadir vigilancia', () => modalElegirVigilable(d, recargar), 'primario', { 'data-anadir-vigilancia': '1' }),
        revisarTodas, cuenta),
      h('details', { class: 'panel', open: !d.total }, h('summary', null, '¿Qué es la vigilancia?'),
        h('p', { class: 'ayuda' }, 'El bot revisa un filtro (por ejemplo «Elegir corte» de Portal) y te avisa cuando aparece una opción nueva (el corte «45 - 2026 …» de la semana siguiente). Si marcas «descargar automáticamente lo nuevo», ejecuta el reporte o la página con esa opción (una vez por cada opción nueva) y no la vuelve a descargar.'),
        h('p', { class: 'ayuda' }, 'Puedes tener VARIAS vigilancias: otras listas, u otra vez la misma lista con otros valores (p. ej. «Elegir corte» para «Detalles Ventas Mayorista» y, aparte, para «Cartera General»), cada una con sus avisos y su descarga.'),
        h('p', { class: 'ayuda' }, 'Para filtros por días (hoy es 26, mañana 27…): en el editor del reporte usa «Repetir por días» con {fecha}, o, para «cada día descargar el día anterior», escribe {ayer} en el campo de fecha y programa el reporte diario.')),
      secciones);
    // Una sección por Página o reporte con listas (v3.3.1: también las grabadas como clics) y, dentro, una tarjeta por
    // vigilancia.  La sección solo se repinta si cambia su cabecera; las tarjetas, cada una por su cuenta.
    function seccion(it) {
      const x = it.x;
      const obj = objetoVigilable(x, it.tipo);
      const tarjetas = h('div', { class: 'tarjetas-vig' });
      let cab, pie, extra = [];
      if (it.tipo === 'pagina') {
        cab = h('span', null, h('a', { href: '#/paginas/' + x.id }, x.nombre), chip('página', 'info'), x.nuevas.length ? chip(x.nuevas.length + ' nueva(s)', 'marca') : null);
        pie = h('div', { class: 'fila' }, boton('＋ Añadir vigilancia', () => modalVigilancia(obj, null, recargar), 'chico', { 'data-anadir': 'pagina-' + x.id }), boton('Abrir la página', () => { location.hash = '#/paginas/' + x.id; }, 'chico'));
      } else {
        const sinConvertir = (x.listas_clic || []).length + (x.selects || []).length;
        cab = h('span', null, x.nombre, chip('reporte'), x.nuevas.length ? chip(x.nuevas.length + ' nueva(s)', 'marca') : null);
        extra = [sinConvertir ? h('p', { class: 'ayuda' }, (x.listas_clic || []).length ? 'Tiene ' + sinConvertir + ' lista(s) grabada(s) como clics (p. ej. ' + (x.listas_clic[0] || x.selects[0]).descripcion + '). Puedes vigilarlas directamente: al añadir la vigilancia el bot las convierte en «Elegir opción» (con copia en Versiones).'
          : 'Tiene ' + sinConvertir + ' lista(s) sencilla(s): al añadir la vigilancia se convierten en «Elegir opción» (con copia en Versiones).') : null,
          x.repetir_dias !== 'no' ? h('p', { class: 'ayuda' }, 'Este reporte se repite por días: ' + x.repetir_dias) : null];
        pie = h('div', { class: 'fila' }, boton('＋ Añadir vigilancia', () => modalVigilancia(obj, null, recargar), 'chico', { 'data-anadir': 'reporte-' + x.id }),
          x.pasos.length ? boton('⚙ Usar filtros', () => panelFiltros(x.id), 'chico') : boton('Abrir en el editor', () => { location.hash = '#/editor/' + x.id; }, 'chico'));
      }
      const p = panel(cab, tarjetas, ...extra, pie);
      p._tarjetas = tarjetas;
      p._obj = obj;
      return p;
    }
    function pintar() {
      const items = [
        ...(d.paginas || []).filter((x) => x.listas.length || x.vigilancias.length).map((x) => ({ k: 'p' + x.id, tipo: 'pagina', x })),
        ...(d.reportes || []).filter((x) => x.con_listas || x.vigilancias.length).map((x) => ({ k: 'r' + x.id, tipo: 'reporte', x }))];
      const sinVigs = (it) => JSON.stringify([it.tipo, Object.assign({}, it.x, { vigilancias: null, vigilancia: null, opciones: null })]);
      claveLista(secciones, items, (it) => it.k, seccion, { firma: sinVigs,
        vacio: () => panel(null, h('p', { class: 'vacio' }, 'Ningún reporte ni página tiene listas que vigilar todavía. Graba uno o usa «Mapear página».')) });
      for (const it of items) {
        const nodo = secciones.querySelector(':scope > [data-lk="' + it.k + '"]');
        if (nodo && nodo._tarjetas) {
          claveLista(nodo._tarjetas, it.x.vigilancias, (v) => v.id, (v) => tarjetaVigilancia(v, nodo._obj, recargar),
            { vacio: () => h('p', { class: 'vacio' }, 'Sin vigilancias.') });
        }
      }
      revisarTodas.disabled = !d.activas;
      cuenta.textContent = (d.total || 0) + ' vigilancia(s) en total' + (d.activas ? ' · ' + d.activas + ' activa(s)' : '');
    }
    const actualizar = actualizador(() => api('GET', 'vigilancia'), (x) => { d = x; pintar(); });
    const pronto = demorar(actualizar, 400);
    pintar();
    return {
      actualizar,
      evento(ev) {
        if (ev.tipo === 'vigilancia' || (ev.tipo === 'trabajo' && ev.estado !== 'en_curso' && ['vigilar', 'pagina', 'pagina_varias', 'ejecutar', 'lote'].includes(ev.tipo_trabajo))) pronto();
      },
    };
  };

  // ------------------------------------------------------------------ Correo (v3.4)
  // Cuentas (Outlook / Gmail en el navegador, o IMAP) y búsquedas: «¿Qué correo?» (asunto, remitente, fecha, cuerpo,
  // adjuntos), «¿Qué hago con él?» (descargar adjuntos, copiar un texto, copiar una tabla, guardar el cuerpo) y «Cuándo».
  const PROV_CORTO = { outlook_web: 'Outlook', gmail_web: 'Gmail', imap: 'IMAP' };
  function chipSesion(cu) {
    if (cu.proveedor === 'imap') {
      if (!cu.tiene_clave) return chip('falta la contraseña', 'aviso');
      if (cu.estado_sesion === 'caducada') return chip('contraseña rechazada', 'error');
      if (cu.estado_sesion === 'error') return chip('no se pudo conectar', 'error');
      return chip(cu.estado_sesion === 'ok' ? 'conectada ✓' : 'contraseña guardada', 'ok');
    }
    if (cu.estado_sesion === 'ok') return chip('sesión iniciada ✓', 'ok');
    if (cu.estado_sesion === 'caducada') return chip('sesión caducada', 'error');
    if (cu.estado_sesion === 'error') return chip('no se pudo abrir', 'error');
    return chip(cu.perfil_guardado ? 'sesión sin comprobar' : 'falta iniciar sesión', 'aviso');
  }
  async function abrirArchivo(ruta, carpeta) {
    try { await api('POST', 'archivos/' + (carpeta ? 'carpeta' : 'abrir'), { ruta }); } catch (e) { errorToast(e); }
  }
  function filaArchivo(ruta) {
    return h('li', null, h('div', { class: 'crece' }, h('div', null, nombreArchivo(ruta)), h('div', { class: 'sub' }, ruta)),
      boton('Abrir archivo', () => abrirArchivo(ruta, false), 'chico'), boton('Abrir carpeta', () => abrirArchivo(ruta, true), 'chico'));
  }
  async function iniciarSesionCorreo(cu) {
    try {
      await api('POST', 'correo/cuentas/' + cu.id + '/sesion', {});
      toast(cu.proveedor === 'imap' ? 'Probando la conexión IMAP…' : 'Se abre una ventana del navegador: entra tú en «' + cu.nombre + '» (el bot nunca escribe tu contraseña) y espera a que salga la bandeja.', 'ok', 12000);
    } catch (e) { errorToast(e); }
  }

  function modalCuentaCorreo(d, cu, alGuardar) {
    cu = cu || {};
    const tipo = h('select', { 'aria-label': 'Tipo de cuenta', 'data-cuenta-proveedor': '1' }, Object.entries(d.proveedores).map(([k, t]) => h('option', { value: k }, t)));
    tipo.value = cu.proveedor || 'outlook_web';
    const nombre = h('input', { type: 'text', value: cu.nombre || '', placeholder: 'p. ej. Correo de la empresa', 'aria-label': 'Nombre de la cuenta' });
    const direccion = h('input', { type: 'text', value: cu.direccion || '', placeholder: 'reportes@ejemplo.com', 'aria-label': 'Dirección de correo' });
    const url = h('input', { type: 'text', value: cu.url || '', 'aria-label': 'Dirección web del correo' });
    const host = h('input', { type: 'text', value: cu.host || '', placeholder: 'imap.gmail.com', 'aria-label': 'Servidor IMAP' });
    const puerto = h('input', { type: 'number', value: cu.puerto || 993, class: 'corto', 'aria-label': 'Puerto' });
    const usuario = h('input', { type: 'text', value: cu.usuario || '', placeholder: '(la dirección de correo)', 'aria-label': 'Usuario' });
    const ssl = h('input', { type: 'checkbox', checked: cu.ssl !== false, 'aria-label': 'Conexión segura (SSL)' });
    const carpetaImap = h('input', { type: 'text', value: cu.carpeta || 'INBOX', 'aria-label': 'Carpeta' });
    const clave = campoClave('', 'Contraseña IMAP');
    const zona = h('div', { class: 'formulario' });
    const pintar = () => {
      const p = tipo.value;
      url.placeholder = p === 'gmail_web' ? 'https://mail.google.com/mail/u/0/ (por defecto)' : 'https://outlook.cloud.microsoft/mail/inbox (por defecto)';
      const filas = [h('label', null, 'Tipo'), tipo, h('label', null, 'Nombre'), nombre, h('label', null, 'Dirección de correo'), direccion];
      if (p === 'imap') {
        filas.push(h('label', null, 'Servidor IMAP'), host, h('label', null, 'Puerto'), h('div', { class: 'fila' }, puerto, h('label', { class: 'interruptor' }, ssl, 'Conexión segura (SSL)')),
          h('label', null, 'Usuario'), usuario, h('label', null, 'Carpeta'), carpetaImap,
          h('label', null, cu.tiene_clave ? 'Contraseña (déjala vacía para no cambiarla)' : 'Contraseña'), clave.caja,
          h('div', { class: 'ancho alerta' }, 'La contraseña se guarda en el Administrador de credenciales de Windows, nunca en un archivo. ',
            h('strong', null, 'Gmail: '), 'no vale tu contraseña normal; hace falta una «contraseña de aplicación» (Cuenta de Google → Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones) y tener IMAP activado en Gmail. ',
            h('strong', null, 'Outlook/Microsoft 365: '), 'muchas empresas no permiten IMAP con contraseña; si no funciona, usa el tipo «Outlook (en el navegador)».'));
      } else {
        filas.push(h('label', null, 'Dirección web (opcional)'), url,
          h('div', { class: 'ancho alerta' }, 'El bot usa una ventana de navegador propia para esta cuenta. La primera vez pulsa «Iniciar sesión en el correo»: se abre la ventana, ',
            h('strong', null, 'entras tú'), ' (con tu contraseña y, si te lo pide, el código del móvil) y el bot espera a que salga la bandeja. El bot nunca escribe tu contraseña de ' +
            (p === 'gmail_web' ? 'Google' : 'Microsoft') + '. Después ya puede revisar el correo sin abrir ninguna ventana; si la sesión caduca, te avisa.'));
      }
      zona.replaceChildren(...filas);
    };
    tipo.addEventListener('change', pintar);
    pintar();
    const guardar = async () => {
      const datos = { proveedor: tipo.value, nombre: nombre.value, direccion: direccion.value, url: url.value, host: host.value,
        puerto: parseInt(puerto.value, 10) || null, usuario: usuario.value, ssl: ssl.checked, carpeta: tipo.value === 'imap' ? carpetaImap.value : '' };
      if (clave.inp.value) datos.contrasena = clave.inp.value;
      if (tipo.value === 'imap' && !cu.tiene_clave && !clave.inp.value) { toast('Escribe la contraseña (en Gmail, la contraseña de aplicación)', 'aviso'); return; }
      try {
        const r = cu.id ? await api('PUT', 'correo/cuentas/' + cu.id, datos) : await api('POST', 'correo/cuentas', datos);
        clave.inp.value = '';
        cerrarModal();
        toast('Cuenta «' + r.cuenta.nombre + '» guardada', 'ok');
        if (!cu.id && r.cuenta.proveedor !== 'imap') {
          abrirModal({ titulo: 'Iniciar sesión en «' + r.cuenta.nombre + '»', contenido: h('div', null,
            h('p', null, 'Ahora entra una vez en tu correo: se abrirá una ventana del navegador; inicia sesión tú (el bot nunca escribe tu contraseña) y espera a que aparezca la bandeja de entrada. El bot la detecta solo y cierra la ventana.')),
            botones: [{ texto: 'Más tarde', accion: () => { cerrarModal(); if (alGuardar) alGuardar(); } },
              { texto: 'Iniciar sesión en el correo', clase: 'primario', accion: async () => { cerrarModal(); await iniciarSesionCorreo(r.cuenta); if (alGuardar) alGuardar(); } }] });
          return;
        }
        if (alGuardar) alGuardar();
      } catch (e) { errorToast(e); }
    };
    abrirModal({ titulo: cu.id ? 'Cambiar la cuenta «' + cu.nombre + '»' : 'Añadir una cuenta de correo', ancho: true,
      contenido: h('div', { 'data-modal-cuenta-correo': '1' }, zona), alEnter: guardar,
      botones: [{ texto: 'Cancelar', accion: cerrarModal }, { texto: 'Guardar', clase: 'primario', accion: guardar }] });
  }

  // Una acción de «¿Qué hago con él?» como formulario.  `a` se modifica al escribir.
  function filaAccionCorreo(d, a, i, quitar, repintar) {
    const campo = (k, at) => {
      const inp = h('input', Object.assign({ type: 'text', value: a[k] === undefined || a[k] === null ? '' : a[k] }, at || {}));
      inp.addEventListener('input', () => { a[k] = at && at.type === 'number' ? (parseInt(inp.value, 10) || 1) : inp.value; });
      return inp;
    };
    const casilla = (k, texto) => {
      const cb = h('input', { type: 'checkbox', checked: !!a[k] });
      cb.addEventListener('change', () => { a[k] = cb.checked; });
      return h('label', { class: 'interruptor' }, cb, texto);
    };
    const lista = (k, opciones, alCambiar) => {
      const s = h('select', { 'aria-label': k }, Object.entries(opciones).map(([v, t]) => h('option', { value: v }, t)));
      s.value = a[k];
      s.addEventListener('change', () => { a[k] = s.value; if (alCambiar) alCambiar(); });
      return s;
    };
    const tipo = h('select', { 'aria-label': 'Qué hacer', 'data-accion-tipo': String(i) }, Object.entries(d.tipos_accion).map(([v, t]) => h('option', { value: v }, t)));
    tipo.value = a.tipo;
    tipo.addEventListener('change', () => {
      const nuevo = Object.assign({ tipo: tipo.value }, JSON.parse(JSON.stringify(d.acciones_defecto[tipo.value] || {})));
      Object.keys(a).forEach((k) => delete a[k]); Object.assign(a, nuevo); repintar();
    });
    const filas = [];
    const ef = (t, ctl, ayuda) => filas.push(h('label', null, t), ayuda ? h('div', null, ctl, h('div', { class: 'ayuda' }, ayuda)) : ctl);
    const ayudaNombre = 'Vacío = el nombre original. Puedes usar ' + d.plantillas.map((p) => p[0]).join(' ') + '. Si no pones la extensión, se añade la del adjunto.';
    if (a.tipo === 'adjuntos') {
      ef('Solo los que contienen', campo('coincide', { placeholder: '(todos) p. ej. SUPERVISION VENTAS', 'aria-label': 'El nombre del adjunto contiene' }), 'Sin mayúsculas, acentos ni signos: «supervision ventas» vale para «SUPERVISION VENTAS MI EMPRESA V1.4.xlsx».');
      ef('Extensión', campo('extension', { placeholder: '(cualquiera) p. ej. xlsx, csv', 'aria-label': 'Extensión del adjunto' }));
      ef('Carpeta', campoRuta(campo('carpeta', { placeholder: d.carpeta_base, 'aria-label': 'Carpeta donde se guardan' }), { titulo: 'Carpeta donde se guardan los adjuntos' }), 'Vacío = la carpeta de descargas del bot. P. ej. %USERPROFILE%\\Downloads\\migracion o Correo\\{fecha_correo:%Y-%m}.');
      ef('Nombre del archivo', campo('nombre', { placeholder: '(el nombre original)', 'aria-label': 'Nombre del archivo' }), ayudaNombre);
      filas.push(h('span'), casilla('descomprimir', 'Si es un .zip, descomprimirlo (y quedarse con lo que coincide)'));
    } else if (a.tipo === 'texto') {
      const zonaModo = h('div', { class: 'formulario ancho' });
      const pintarModo = () => {
        const f2 = [];
        if (a.modo === 'regex') f2.push(h('label', null, 'Expresión regular'), h('div', null, campo('regex', { placeholder: 'Total ventas:\\s*([\\d.,]+)', 'aria-label': 'Expresión regular' }), h('div', { class: 'ayuda' }, 'Se copia lo que va entre paréntesis (el primer grupo).')));
        else {
          f2.push(h('label', null, a.modo === 'entre' ? 'Desde el texto' : 'El texto que va justo antes'), h('div', null, campo('etiqueta', { placeholder: 'Total ventas:', 'aria-label': 'Texto que va antes' }),
            h('div', { class: 'ayuda' }, a.modo === 'entre' ? 'Se copia lo que hay entre los dos textos.' : 'Se copia lo que va después, hasta el final de la línea (si está vacío, la línea siguiente). Sin mayúsculas ni acentos.')));
          if (a.modo === 'entre') f2.push(h('label', null, 'Hasta el texto'), campo('hasta', { placeholder: '(el final de la línea)', 'aria-label': 'Hasta el texto' }));
        }
        zonaModo.replaceChildren(...f2);
      };
      ef('Nombre del dato', campo('campo', { placeholder: 'p. ej. Total ventas', 'aria-label': 'Nombre del dato' }), 'Sale en el aviso y en el historial: «Total ventas: 1.234».');
      ef('Cómo encontrarlo', lista('modo', d.modos_texto, pintarModo));
      filas.push(zonaModo);
      pintarModo();
      ef('Anotar también en (opcional)', campoRuta(campo('archivo', { placeholder: 'p. ej. Correo\\valores.csv (o .xlsx, .txt)', 'aria-label': 'Archivo donde se anota' }), { tipo: 'guardar', filtros: FILTROS_ANOTAR, titulo: 'Archivo donde se anota el texto' }), 'Una fila por correo: Fecha, Asunto, Campo, Valor.' + (d.hay_excel ? '' : ' (Excel no disponible: usa .csv)'));
    } else if (a.tipo === 'tabla') {
      ef('Número de la tabla', campo('n', { type: 'number', min: '1', class: 'corto', 'aria-label': 'Número de la tabla' }), '1 = la primera tabla del cuerpo (las que solo sirven para maquetar no cuentan). «Probar búsqueda» no la copia: pruébalo con «Revisar ahora».');
      ef('Archivo', campoRuta(campo('archivo', { placeholder: d.hay_excel ? 'p. ej. C:\\Reportes\\Ventas.xlsx (o .csv)' : 'p. ej. C:\\Reportes\\Ventas.csv', 'aria-label': 'Archivo Excel o CSV' }), { tipo: 'guardar', filtros: FILTROS_EXCEL, titulo: 'Archivo Excel o CSV donde se copia la tabla' }), d.hay_excel ? null : 'Excel (.xlsx) no está disponible en este equipo (falta «openpyxl»): usa .csv.');
      ef('Cómo copiarla', lista('modo', d.modos_tabla));
      ef('Hoja (opcional)', campo('hoja', { placeholder: '(la primera; con «una hoja por mes»: OCTUBRE 2026)', 'aria-label': 'Hoja' }));
      filas.push(h('span'), casilla('con_encabezado', 'La primera fila son los títulos (al agregar a un archivo con datos, no se repite)'));
    } else {
      ef('Formato', lista('formato', { html: 'Página web (.html, con su formato)', txt: 'Texto (.txt)' }));
      ef('Carpeta', campoRuta(campo('carpeta', { placeholder: d.carpeta_base, 'aria-label': 'Carpeta' }), { titulo: 'Carpeta donde se guarda el cuerpo del correo' }));
      ef('Nombre del archivo', campo('nombre', { placeholder: '{fecha_correo:%Y-%m-%d %H%M} {asunto}', 'aria-label': 'Nombre del archivo' }));
    }
    return h('div', { class: 'correo-accion', 'data-accion': String(i) },
      h('div', { class: 'fila' }, h('strong', null, (i + 1) + '.'), tipo, h('span', { class: 'crece' }), boton('✕ Quitar', quitar, 'chico peligro')),
      h('div', { class: 'formulario' }, filas));
  }

  async function modalBusquedaCorreo(d, b, alGuardar) {
    b = b ? JSON.parse(JSON.stringify(b)) : { nombre: '', cuenta_id: (d.cuentas[0] || {}).id, activa: true, max_por_vez: d.max_por_vez,
      criterios: Object.assign({}, d.criterios_defecto), acciones: [Object.assign({ tipo: 'adjuntos' }, d.acciones_defecto.adjuntos)], programacion: { reglas: [] } };
    const cr = Object.assign({}, d.criterios_defecto, b.criterios || {});
    const acciones = b.acciones || [];
    const nombre = h('input', { type: 'text', value: b.nombre || '', placeholder: 'p. ej. Ventas diarias', 'aria-label': 'Nombre de la búsqueda' });
    const cuenta = h('select', { 'aria-label': 'Cuenta de correo' }, d.cuentas.map((cu) => h('option', { value: String(cu.id) }, cu.nombre + ' (' + PROV_CORTO[cu.proveedor] + ')')));
    if (b.cuenta_id) cuenta.value = String(b.cuenta_id);
    const activa = h('input', { type: 'checkbox', checked: b.activa !== false });
    // ¿Qué correo?
    const t = (k, ph, et) => h('input', { type: 'text', value: cr[k] || '', placeholder: ph || '', 'aria-label': et || k });
    const asunto = t('asunto', 'p. ej. RESUMEN DE VENTAS MI EMPRESA', 'El asunto contiene');
    const remitente = t('remitente', 'p. ej. reportes@ejemplo.com o Reportes Ventas', 'Remitente');
    const exacto = h('select', { 'aria-label': 'Cómo comparar el remitente' }, h('option', { value: 'no' }, 'contiene'), h('option', { value: 'si' }, 'es exactamente'));
    exacto.value = cr.remitente_exacto ? 'si' : 'no';
    const fecha = h('select', { 'aria-label': 'Fecha del correo', 'data-correo-fecha': '1' }, Object.entries(d.modos_fecha).map(([v, tx]) => h('option', { value: v }, tx)));
    fecha.value = cr.fecha || 'ultimos';
    const dias = h('input', { type: 'number', min: '1', value: cr.dias || 7, class: 'corto', 'aria-label': 'Últimos días' });
    const desde = t('desde', '{dias:-7} o 01/10/2026', 'Desde');
    const hasta = t('hasta', '{hoy} o 31/10/2026', 'Hasta');
    // v3.6: desde / hasta con el calendario (una fecha fija o una que cambia sola: «hace 7 días», «hoy»…)
    const opFecha = { sinFormato: true, prefijo: 'Hoy sería: ', modoInicial: 'relativa' };
    const cajaDesde = campoFecha(desde, Object.assign({ vacio: 'sin límite', titulo: 'Desde (fecha del correo)' }, opFecha));
    const cajaHasta = campoFecha(hasta, Object.assign({ vacio: 'sin límite', titulo: 'Hasta (fecha del correo)' }, opFecha));
    const zonaFecha = h('div', { class: 'fila' });
    const pintarFecha = () => {
      const v = fecha.value;
      zonaFecha.replaceChildren(fecha, ...(v === 'ultimos' ? [h('span', { class: 'sub' }, 'los últimos'), dias, h('span', { class: 'sub' }, 'días')] : []),
        ...(v === 'rango' ? [h('div', { class: 'fecha-rango', 'data-correo-rango': '1' }, h('div', null, h('span', { class: 'sub' }, 'Desde'), cajaDesde),
          h('div', null, h('span', { class: 'sub' }, 'Hasta'), cajaHasta))] : []));
    };
    fecha.addEventListener('change', pintarFecha);
    pintarFecha();
    const cuerpo = h('textarea', { rows: 2, placeholder: 'Uno por línea (opcional). p. ej. Total ventas', 'aria-label': 'El cuerpo contiene' }, (cr.cuerpo || []).join('\n'));
    const conAdjunto = h('input', { type: 'checkbox', checked: !!cr.con_adjunto });
    const reprocesar = h('input', { type: 'checkbox', checked: !!cr.reprocesar, 'data-correo-reprocesar': '1' });     // v3.6.1
    const adjunto = t('adjunto', 'p. ej. SUPERVISION VENTAS', 'El nombre del adjunto contiene');
    const extension = t('extension', 'p. ej. xlsx', 'Extensión del adjunto');
    const buscar = t('buscar', '(automático: el asunto entero)', 'Texto que se escribe en el buscador');
    const carpetaImap = t('carpeta', '(la de la cuenta)', 'Carpeta IMAP');
    const maximo = h('input', { type: 'number', min: '1', max: '100', value: b.max_por_vez || d.max_por_vez, class: 'corto', 'aria-label': 'Como mucho, correos por revisión' });
    const leerCriterios = () => ({ asunto: asunto.value, remitente: remitente.value, remitente_exacto: exacto.value === 'si', fecha: fecha.value,
      dias: parseInt(dias.value, 10) || 7, desde: desde.value, hasta: hasta.value, cuerpo: cuerpo.value.split('\n').map((x) => x.trim()).filter(Boolean),
      con_adjunto: conAdjunto.checked, adjunto: adjunto.value, extension: extension.value, buscar: buscar.value, carpeta: carpetaImap.value,
      reprocesar: reprocesar.checked });
    const resultados = h('div', { 'data-prueba-correo': '1' });
    const probar = async () => {
      resultados.replaceChildren(h('p', { class: 'ayuda fila' }, ico('cargando', 'girando'), 'Buscando en el correo (sin abrir navegador)…'));
      let t2;
      try { t2 = await api('POST', 'correo/probar', { cuenta_id: parseInt(cuenta.value, 10), criterios: leerCriterios(), busqueda_id: b.id || null }); }
      catch (e) { resultados.replaceChildren(h('div', { class: 'alerta error' }, e.message || String(e))); return; }
      let recibido = false;
      const oyente = (ev) => {
        if (ev.tipo === 'correo_prueba' && ev.trabajo === t2.id) {
          recibido = true;
          if (!ev.ok) { resultados.replaceChildren(h('div', { class: 'alerta error' }, ev.error, ev.sesion_caducada ? ' — pulsa «Iniciar sesión en el correo» en la cuenta.' : '')); return; }
          const ms = ev.mensajes || [];
          const buenos = ms.filter((m) => m.coincide).length;
          resultados.replaceChildren(h('div', { class: 'alerta ' + (buenos ? 'ok' : 'aviso') }, buenos ? buenos + ' correo(s) coinciden ahora (no se ha procesado ninguno):' : 'Ahora no hay ningún correo que coincida. Prueba con menos datos o más días.'),
            ms.length ? h('ul', { class: 'lista' }, ms.map((m) => h('li', { 'data-correo-encontrado': '1' }, h('div', { class: 'crece' },
              h('div', null, m.asunto || '(sin asunto)'), h('div', { class: 'sub' }, [m.remitente, m.fecha].filter(Boolean).join(' · ')),
              h('div', { class: 'sub' }, (m.adjuntos && m.adjuntos.length) ? h('span', { class: 'adjuntos' }, ico('clip'), m.adjuntos.join(', ')) : 'sin adjuntos'),
              m.coincide ? null : h('div', { class: 'sub' }, 'No vale: ' + m.motivo)),
              m.coincide ? chip('coincide', 'ok') : chip('no coincide', 'aviso'), m.procesado ? chip((m.estado_procesado === 'error' ? 'procesado con error el ' : 'ya procesado el ') + m.procesado, 'info') : null))) : null);
        } else if (ev.tipo === 'trabajo' && ev.trabajo === t2.id && ev.estado !== 'en_curso' && !recibido) {
          resultados.replaceChildren(h('div', { class: 'alerta error' }, ev.resumen || 'No se pudo probar la búsqueda'));
        }
      };
      E.oyenteModal = oyente;
    };
    // ¿Qué hago con él?
    const zonaAcciones = h('div', { 'data-correo-acciones': '1' });
    const pintarAcciones = () => {
      zonaAcciones.replaceChildren(...(acciones.length ? acciones.map((a, i) => filaAccionCorreo(d, a, i, () => { acciones.splice(i, 1); pintarAcciones(); }, pintarAcciones))
        : [h('p', { class: 'vacio' }, 'Ninguna acción: añade al menos una.')]));
    };
    pintarAcciones();
    const anadir = boton('＋ Añadir acción', () => { acciones.push(Object.assign({ tipo: 'texto' }, JSON.parse(JSON.stringify(d.acciones_defecto.texto)))); pintarAcciones(); }, 'chico', { 'data-anadir-accion': '1' });
    const ed = editorCuando(b.programacion, { textoNunca: 'Solo cuando pulse «Revisar ahora»' });
    const seccion = (tit, ...hijos) => h('section', { class: 'correo-seccion' }, h('h3', null, tit), ...hijos);
    const guardar = async () => {
      const datos = { nombre: nombre.value, cuenta_id: parseInt(cuenta.value, 10), activa: activa.checked, criterios: leerCriterios(), acciones,
        max_por_vez: parseInt(maximo.value, 10) || d.max_por_vez, programacion: ed.leer() };
      const v = await ed.comprobar();
      if (v && !v.valida) { toast(v.error, 'error'); return; }
      try {
        const r = b.id ? await api('PUT', 'correo/busquedas/' + b.id, datos) : await api('POST', 'correo/busquedas', datos);
        cerrarModal();
        toast('Búsqueda «' + r.busqueda.nombre + '» guardada', 'ok');
        await avisoTareaCorreo(r.busqueda, !b.id || r.cambio_horario, alGuardar);
      } catch (e) { errorToast(e); }
    };
    abrirModal({ titulo: b.id ? 'Editar «' + b.nombre + '»' : 'Nueva búsqueda de correo', ancho: true, alCerrar: () => { E.oyenteModal = null; },
      contenido: h('div', { 'data-modal-correo': '1' },
        seccion('Cuenta', h('div', { class: 'formulario', 'data-correo-cuenta': '1' }, h('label', null, 'Nombre de la búsqueda'), nombre, h('label', null, 'Cuenta de correo'), cuenta,
          h('label', null, 'Activa'), h('label', { class: 'interruptor' }, activa, 'Se revisa con «Revisar todas» y con su horario'))),
        seccion('¿Qué correo?', h('p', { class: 'ayuda' }, 'Rellena solo lo que sirva para reconocerlo. No importan las mayúsculas, los acentos ni los signos («S.A.S.» = «SAS»). Se procesan TODOS los correos que coincidan y no se hayan procesado ya, del más reciente al más antiguo. Si no hay ninguno nuevo, «Revisar ahora» vuelve a hacer las acciones con el más reciente (el horario automático, solo con los nuevos).'),
          h('div', { class: 'formulario', 'data-correo-que': '1' },
            h('label', null, 'El asunto contiene'), asunto, h('label', null, 'Remitente'), h('div', { class: 'fila' }, exacto, remitente),
            h('label', null, 'Fecha'), zonaFecha, h('label', null, 'El cuerpo dice'), cuerpo,
            h('label', null, 'Adjuntos'), h('div', null, h('label', { class: 'interruptor' }, conAdjunto, 'Tiene algún adjunto'),
              h('div', { class: 'fila' }, adjunto, extension)),
            h('label', null, 'Ya procesados'), h('div', null, h('label', { class: 'interruptor' }, reprocesar, 'Procesar también los que ya se procesaron'),
              h('div', { class: 'ayuda' }, 'Cada revisión vuelve a hacer las acciones con todos los correos que coincidan, aunque ya se hubieran hecho (p. ej. copiar otra vez el texto). Si no lo marcas, solo los nuevos.'))),
          h('details', null, h('summary', null, 'Más opciones'), h('div', { class: 'formulario' },
            h('label', null, 'Texto del buscador (Outlook)'), h('div', null, buscar, h('div', { class: 'ayuda' }, 'El bot lo PEGA entero en el buscador de Outlook (no lo teclea letra a letra). Si así no encuentra nada, prueba una vez con una parte (hasta la primera coma).')),
            h('label', null, 'Carpeta (IMAP)'), carpetaImap,
            h('label', null, 'Como mucho, correos por revisión'), maximo)),
          h('div', { class: 'fila', style: 'margin-top:8px' }, boton('🔎 Probar búsqueda', probar, 'primario chico', { 'data-probar-correo': '1' }),
            h('span', { class: 'ayuda' }, 'Busca ahora y enseña qué correos coinciden (asunto, remitente, fecha, adjuntos) sin procesar ninguno.')),
          resultados),
        seccion('¿Qué hago con él?', zonaAcciones, h('div', { class: 'fila' }, anadir)),
        seccion('Cuándo', h('p', { class: 'ayuda' }, 'Cuándo revisa el bot el correo él solo (con una tarea de Windows, como las vigilancias).'), ed.caja)),
      botones: [{ texto: 'Cancelar', accion: cerrarModal }, { texto: 'Guardar', clase: 'primario', accion: guardar }] });
  }

  // Tras guardar con horario: si no tiene tarea en Windows (o cambió el horario), decirlo y ofrecer crearla.
  async function avisoTareaCorreo(b, cambio, recargar) {
    const t = b.tarea || {};
    const tiene = (b.programacion && (b.programacion.reglas || []).length);
    if (tiene && (!t.existe || cambio)) {
      await activarAlGuardar('correo/busquedas/' + b.id + '/programar', 'la búsqueda «' + b.nombre + '»');
      if (recargar) recargar();
      return;
    }
    if (!tiene && t.existe) {
      abrirModal({ titulo: '¿Quitar la tarea de Windows?', contenido: h('p', null, 'Ahora esta búsqueda solo se revisa con «Revisar ahora», pero en Windows sigue su tarea (' + t.nombres.join(', ') + ').'),
        botones: [{ texto: 'Dejarla', accion: () => { cerrarModal(); if (recargar) recargar(); } },
          { texto: 'Quitar la tarea de Windows', clase: 'primario', accion: async () => { await quitarTareaWindows('correo/busquedas/' + b.id + '/quitar_tarea'); if (recargar) recargar(); } }] });
      return;
    }
    if (recargar) recargar();
  }

  // v3.5 «Correos relacionados» (como la lista de cortes de una Página): todos los correos que cumplen la búsqueda, del
  // más reciente al más antiguo, con su estado (nuevo / ya procesado / con error / descartado), con un rango de fechas
  // propio y «Cargar más».  «Procesar este» y «Procesar seleccionados» hacen las acciones aunque ya se hubieran hecho.
  function modalRelacionados(d, b, fondo) {
    const rangos = d.rangos || { busqueda: 'las fechas de la búsqueda', 30: 'últimos 30 días', 90: 'últimos 90 días', todas: 'todas las fechas' };
    const porPagina = d.por_pagina || 10;
    const rango = h('select', { 'aria-label': 'Fechas', 'data-rango-relacionados': '1' }, Object.entries(rangos).map(([k, t]) => h('option', { value: k }, t)));
    rango.value = '30';
    const abrirCada = h('input', { type: 'checkbox', checked: true, 'aria-label': 'Abrir cada correo para ver sus adjuntos' });
    const estado = h('div', { class: 'ayuda' });
    const lista = h('ul', { class: 'lista relacionados', 'data-relacionados': String(b.id) });
    const mas = boton('Cargar más', () => cargar(true), 'chico', { 'data-cargar-mas': '1' });
    mas.classList.add('oculto');
    const procesarSel = boton('Procesar seleccionados', () => procesar([...elegidos]), 'chico primario', { 'data-procesar-seleccionados': '1', disabled: true });
    let filas = [];
    const elegidos = new Set();
    let trabajoLista = null;
    let rangoCargado = '30';
    const CHIP = { nuevo: 'info', procesado: 'ok', error: 'error', descartado: 'aviso' };
    const actualizarSel = () => { procesarSel.disabled = !elegidos.size; procesarSel.textContent = 'Procesar seleccionados' + (elegidos.size ? ' (' + elegidos.size + ')' : ''); };
    const pintar = () => {
      lista.replaceChildren(...(filas.length ? filas.map((m) => {
        const cb = h('input', { type: 'checkbox', checked: elegidos.has(m.clave), 'aria-label': 'Elegir «' + (m.asunto || 'correo') + '»' });
        cb.addEventListener('change', () => { if (cb.checked) elegidos.add(m.clave); else elegidos.delete(m.clave); actualizarSel(); });
        return h('li', { 'data-correo-relacionado': m.clave, class: m.mas_reciente ? 'mas-reciente' : null }, cb,
          h('div', { class: 'crece' },
            h('div', null, m.asunto || '(sin asunto)', m.mas_reciente ? ' ' : null, m.mas_reciente ? chip('el más reciente', 'marca') : null),
            h('div', { class: 'sub' }, [m.fecha || 'sin fecha', m.remitente].filter(Boolean).join(' · ')),
            h('div', { class: 'sub' }, m.adjuntos === null || m.adjuntos === undefined ? 'adjuntos: (sin abrir)' : (m.adjuntos.length ? h('span', { class: 'adjuntos' }, ico('clip'), m.adjuntos.join(', ')) : 'sin adjuntos')),
            m.coincide === false && m.motivo ? h('div', { class: 'sub' }, 'Al abrirlo no coincide: ' + m.motivo) : (m.motivo ? h('div', { class: 'sub' }, m.motivo) : null),
            (m.archivos || []).length ? h('ul', { class: 'lista' }, m.archivos.slice(0, 5).map(filaArchivo)) : null),
          chip(m.estado_texto || m.estado, CHIP[m.estado] || ''),
          boton(m.estado === 'nuevo' ? 'Procesar este' : 'Procesar otra vez', () => procesar([m.clave]), 'chico', { 'data-procesar-correo': m.clave }));
      }) : [h('li', { class: 'vacio' }, 'Ningún correo cumple la búsqueda con estas fechas. Prueba con «todas las fechas».')]));
      actualizarSel();
    };
    async function cargar(masDe) {
      const desde = masDe ? filas.length : 0;
      if (!masDe) { filas = []; elegidos.clear(); lista.replaceChildren(h('li', { class: 'vacio' }, ico('cargando', 'girando'), 'Buscando en el correo (sin abrir navegador)…')); }
      estado.textContent = masDe ? 'Cargando más…' : '';
      try {
        const t = await api('POST', 'correo/busquedas/' + b.id + '/relacionados', { rango: masDe ? rangoCargado : rango.value, desde, limite: porPagina, abrir: abrirCada.checked, ver: fondo ? !fondo.valor() : false });
        trabajoLista = t.id; if (!masDe) rangoCargado = rango.value;
      } catch (e) { estado.textContent = ''; lista.replaceChildren(h('li', null, h('div', { class: 'alerta error' }, e.message || String(e)))); }
    }
    async function procesar(claves) {
      if (!claves.length) return;
      const n = claves.length;
      // (confirmar() usa la misma ventana: después se vuelve a abrir esta con la lista tal cual)
      const si = await confirmar('Procesar ' + (n === 1 ? 'este correo' : n + ' correos'), 'Se harán ahora las acciones de «' + b.nombre + '» con ' + (n === 1 ? 'este correo' : 'estos ' + n + ' correos') +
        ', aunque ya se hubieran procesado (se descargan otra vez los adjuntos y se copian los textos).', 'Procesar');
      abrir();
      if (!si) return;
      const cuerpo = { claves, rango: rangoCargado, buscar_hasta: filas.length + 5, ver: fondo ? !fondo.valor() : false };
      try {
        let r = await api('POST', 'correo/busquedas/' + b.id + '/procesar', cuerpo);
        if (r.confirmar) {
          const si2 = await confirmar('Puede duplicar filas', r.mensaje, 'Procesar igualmente', true);
          abrir();
          if (!si2) return;
          r = await api('POST', 'correo/busquedas/' + b.id + '/procesar', Object.assign({ confirmar: true }, cuerpo));
        }
        estado.textContent = 'Procesando ' + (n === 1 ? '1 correo' : n + ' correos') + '…';
        toast('Procesando ' + (n === 1 ? '1 correo' : n + ' correos') + ' de «' + b.nombre + '»…');
      } catch (e) { errorToast(e); }
    }
    const abrir = () => {
      abrirModal({ titulo: 'Correos relacionados — «' + b.nombre + '»', ancho: true, alCerrar: () => { E.oyenteModal = null; },
        contenido: h('div', { 'data-modal-relacionados': String(b.id) },
          h('p', { class: 'ayuda' }, 'Todos los correos que cumplen esta búsqueda (asunto, remitente, cuerpo, adjuntos), del más reciente al más antiguo, aunque ya se hayan procesado. Elige uno o varios y pulsa «Procesar» para hacer sus acciones ahora. Las fechas de esta lista no cambian la búsqueda.'),
          h('div', { class: 'fila' }, h('span', { class: 'sub' }, 'Fechas:'), rango, h('label', { class: 'interruptor' }, abrirCada, 'Abrir cada correo para ver sus adjuntos (más lento)'),
            boton('↻ Buscar', () => cargar(false), 'chico', { 'data-buscar-relacionados': '1' }), h('span', { class: 'crece' }), procesarSel),
          estado, lista, h('div', { class: 'fila' }, mas)),
        botones: [{ texto: 'Cerrar', clase: 'primario', accion: cerrarModal }] });
      E.oyenteModal = (ev) => {
        if (ev.tipo === 'correo_relacionados' && ev.trabajo === trabajoLista) {
          estado.textContent = '';
          if (!ev.ok) { lista.replaceChildren(h('li', null, h('div', { class: 'alerta error' }, ev.error, ev.sesion_caducada ? ' — pulsa «Iniciar sesión en el correo» en la cuenta.' : ''))); return; }
          const vistos = new Set(filas.map((m) => m.clave));
          filas = filas.concat((ev.mensajes || []).filter((m) => !vistos.has(m.clave)));
          mas.classList.toggle('oculto', !ev.hay_mas);
          estado.textContent = filas.length + ' correo(s) · ' + (rangos[ev.rango] || ev.rango);
          pintar();
        } else if (ev.tipo === 'correo' && ev.a_mano && ev.busqueda_id === b.id) {
          const hechos = new Set(ev.claves || []);
          for (const m of filas) if (hechos.has(m.clave)) { m.estado = 'procesado'; m.estado_texto = 'procesado ahora'; }
          elegidos.clear();
          estado.textContent = ev.resumen || '';
          pintar();
        } else if (ev.tipo === 'trabajo' && ev.trabajo === trabajoLista && ev.estado !== 'en_curso' && ev.estado !== 'ok') {
          estado.textContent = ''; if (!filas.length) lista.replaceChildren(h('li', null, h('div', { class: 'alerta error' }, ev.resumen || 'No se pudo buscar')));
        }
      };
    };
    abrir();
    cargar(false);
  }

  function tarjetaBusquedaCorreo(d, b, recargar, fondo) {
    const t = b.tarea || {};
    const tiene = (b.programacion.reglas || []).length > 0;
    const programar = async () => {
      if (!tiene) { toast('Elige primero cuándo revisarla («Editar» → Cuándo)', 'aviso'); modalBusquedaCorreo(d, b, recargar); return; }
      if (await crearTareaWindows('correo/busquedas/' + b.id + '/programar', {}, 'Revisar el correo «' + b.nombre + '»')) recargar();
    };
    let estadoTarea = null;
    if (tiene && b.activa) {
      estadoTarea = t.existe ? h('div', { class: 'sub t-ok', 'data-tarea-correo': 'si' }, 'Tarea de Windows creada' + (b.proxima ? ' · próxima revisión: ' + b.proxima : ''))
        : h('div', { class: 'alerta aviso', 'data-tarea-correo': 'no' }, 'Tiene horario (' + b.cuando + '), pero NO tiene tarea en Windows: no se revisará solo. ',
          boton('Activar: crear la tarea en Windows', programar, 'chico primario'));
    } else if (!tiene && t.existe) {
      estadoTarea = h('div', { class: 'alerta aviso' }, 'Solo se revisa con «Revisar ahora», pero en Windows sigue su tarea. ',
        boton('Quitar la tarea de Windows', async () => { if (await quitarTareaWindows('correo/busquedas/' + b.id + '/quitar_tarea')) recargar(); }, 'chico'));
    }
    const procesados = b.procesados || [];
    const listaProc = procesados.length ? h('ul', { class: 'lista' }, procesados.map((p) => h('li', null, h('div', { class: 'crece' },
      h('div', null, p.asunto || '(sin asunto)'), h('div', { class: 'sub' }, [p.fecha, p.remitente, 'procesado el ' + p.cuando].filter(Boolean).join(' · ')),
      (p.valores || []).length ? h('div', { class: 'sub' }, p.valores.map((v) => v[0] + ': ' + v[1]).join(' · ')) : null,
      p.mensaje ? h('div', { class: 'sub' }, p.mensaje) : null,
      (p.archivos || []).length ? h('ul', { class: 'lista' }, p.archivos.map(filaArchivo)) : null),
      p.estado === 'ok' ? chip('hecho', 'ok') : chip(p.estado === 'error' ? 'con error' : p.estado, p.estado === 'error' ? 'error' : 'aviso'),
      boton('Volver a procesar', async () => {
        if (!(await confirmar('Volver a procesar', 'La próxima revisión volverá a procesar «' + (p.asunto || 'este correo') + '» (si sigue coincidiendo): descargará otra vez los adjuntos y copiará los textos.', 'Volver a procesar'))) return;
        try { await api('POST', 'correo/busquedas/' + b.id + '/reprocesar', { clave: p.clave }); toast('Se procesará en la próxima revisión', 'ok'); recargar(); } catch (e) { errorToast(e); }
      }, 'chico')))) : h('p', { class: 'vacio' }, 'Todavía no ha procesado ningún correo.');
    return h('div', { class: 'panel correo-tarjeta', 'data-busqueda': String(b.id) },
      h('div', { class: 'fila' }, h('strong', null, b.nombre), chip(b.cuenta || '(sin cuenta)', 'info'),
        b.activa ? chip(b.cuando, 'ok') : chip('pausada', 'aviso'), h('span', { class: 'crece' }), h('span', { class: 'sub' }, '#' + b.id)),
      h('div', { class: 'sub' }, '¿Qué correo? ' + b.que_texto),
      h('div', { class: 'sub' }, '¿Qué hago? ' + (b.acciones_texto || []).join(' · ')),
      h('div', { class: 'sub' }, b.ultima_revision ? 'Última revisión: ' + b.ultima_revision + ' — ' + b.ultimo_resultado : 'Todavía no se ha revisado'),
      estadoTarea,
      h('div', { class: 'fila' },
        boton('Revisar ahora', async () => { try { await api('POST', 'correo/busquedas/' + b.id + '/revisar', { ver: !fondo.valor() }); toast('Revisando «' + b.nombre + '»…'); } catch (e) { errorToast(e); } }, 'chico primario', { 'data-revisar-correo': String(b.id) }),
        boton('Editar', () => modalBusquedaCorreo(d, b, recargar), 'chico', { 'data-editar-correo': String(b.id) }),
        boton('✉ Correos relacionados', () => modalRelacionados(d, b, fondo), 'chico', { 'data-relacionados-correo': String(b.id) }),
        boton(t.existe ? 'Actualizar la tarea en Windows…' : 'Programar…', programar, 'chico'),
        t.existe ? boton('Quitar la tarea', async () => { if (await quitarTareaWindows('correo/busquedas/' + b.id + '/quitar_tarea')) recargar(); }, 'chico') : null,
        boton(b.activa ? 'Pausar' : 'Activar', async () => { try { await api('POST', 'correo/busquedas/' + b.id + '/activar', { activa: !b.activa }); recargar(); } catch (e) { errorToast(e); } }, 'chico'),
        boton('Borrar', async () => {
          if (!(await confirmar('Borrar búsqueda', '¿Borrar «' + b.nombre + '»? Se olvida qué correos había procesado (los archivos descargados no se borran).' + (t.existe ? ' Antes se te ofrecerá quitar su tarea de Windows.' : ''), 'Borrar', true))) return;
          if (t.existe && !(await quitarTareaWindows('correo/busquedas/' + b.id + '/quitar_tarea'))) return;
          try { await api('DELETE', 'correo/busquedas/' + b.id); recargar(); } catch (e) { errorToast(e); }
        }, 'chico peligro')),
      h('details', null, h('summary', null, 'Últimos correos procesados' + (procesados.length ? ' (' + procesados.length + ')' : '')), listaProc));
  }

  RUTAS.correo = async (c) => {
    let d = await api('GET', 'correo');
    titulo('Correo', 'busca correos, descarga sus adjuntos y copia textos de ellos');
    const recargar = () => actualizar();
    const fondo = interruptorFondo(true, 'sin-navegador-correo');
    c.appendChild(h('details', { class: 'panel ayuda-correo', open: !(d.busquedas || []).length },
      h('summary', null, '¿Cómo funciona? (ejemplo)'),
      h('p', null, '1) Añade tu cuenta de correo (Outlook de la empresa, Gmail u otra por IMAP) y pulsa «Iniciar sesión en el correo»: se abre una ventana y entras tú una vez. ',
        '2) Crea una búsqueda: dile cómo reconocer el correo (asunto, quién lo manda, fecha, parte del cuerpo, adjuntos) y qué hacer con él. Pulsa «Probar búsqueda» para ver qué correos coinciden ahora. ',
        '3) Elige cuándo revisarlo y activa la tarea de Windows.'),
      h('p', { class: 'ayuda' }, 'Ejemplo: asunto «RESUMEN DE VENTAS MI EMPRESA», últimos 7 días → descargar el adjunto que contiene «SUPERVISION VENTAS» como «Ventas {fecha_correo:%Y-%m-%d}.xlsx» en «%USERPROFILE%\\Downloads\\migracion», copiar lo que va después de «Total ventas:» → de lunes a viernes a las 09:00 y 15:00. ',
        'Cada correo se procesa una sola vez; si llegan varios, se procesan todos (del más reciente al más antiguo). Al llegar uno verás un aviso como «Llegó «RESUMEN DE VENTAS…»: 1 archivo guardado, Total ventas: 1.234».')));
    // Cuentas (una fila por cuenta, pintada por su número)
    const filaCuenta = (cu) => h('li', { class: 'correo-cuenta', 'data-cuenta': String(cu.id) }, h('div', { class: 'crece' },
      h('div', { class: 'fila' }, h('strong', null, cu.nombre), chip(PROV_CORTO[cu.proveedor] || cu.proveedor, 'info'), chipSesion(cu)),
      h('div', { class: 'sub mono' }, [cu.direccion, cu.proveedor === 'imap' ? cu.host + ':' + cu.puerto : cu.url_efectiva, cu.busquedas.length ? 'la usan: ' + cu.busquedas.join(', ') : ''].filter(Boolean).join(' · ')),
      cu.sesion_texto && cu.estado_sesion !== 'ok' ? h('div', { class: 'sub' }, cu.sesion_texto) : null),
      cu.proveedor === 'imap' ? boton('Probar conexión', () => iniciarSesionCorreo(cu), 'chico primario', { 'data-sesion-cuenta': String(cu.id) })
        : boton('Iniciar sesión en el correo', () => iniciarSesionCorreo(cu), 'chico ' + (cu.estado_sesion === 'ok' ? '' : 'primario'), { 'data-sesion-cuenta': String(cu.id) }),
      cu.proveedor === 'imap' ? null : boton('Comprobar sesión', async () => { try { await api('POST', 'correo/cuentas/' + cu.id + '/probar', {}); toast('Comprobando la sesión de «' + cu.nombre + '» sin abrir navegador…'); } catch (e) { errorToast(e); } }, 'chico'),
      boton('Cambiar…', () => modalCuentaCorreo(d, cu, recargar), 'chico'),
      boton('Borrar', async () => {
        if (!(await confirmar('Borrar cuenta', '¿Borrar la cuenta «' + cu.nombre + '»? (La sesión guardada del navegador se queda en perfiles\\correo_' + cu.id + '.)', 'Borrar', true))) return;
        try { await api('DELETE', 'correo/cuentas/' + cu.id); recargar(); } catch (e) { errorToast(e); }
      }, 'chico peligro'));
    const listaCuentas = h('ul', { class: 'lista' });
    const nuevaCuenta = boton('＋ Añadir cuenta', () => modalCuentaCorreo(d, null, recargar), 'chico', { 'data-nueva-cuenta': '1' });
    c.appendChild(panel('Cuentas de correo', listaCuentas, h('div', { class: 'fila' }, nuevaCuenta)));
    // Búsquedas
    const revisarTodas = boton('↻ Revisar todas', async () => { try { await api('POST', 'correo/revisar', { ver: !fondo.valor() }); toast('Revisando el correo…'); } catch (e) { errorToast(e); } });
    c.appendChild(h('div', { class: 'barra-herr' },
      boton('＋ Nueva búsqueda', () => { if (!(d.cuentas || []).length) { toast('Primero añade una cuenta de correo', 'aviso'); modalCuentaCorreo(d, null, recargar); return; } modalBusquedaCorreo(d, null, recargar); }, 'primario', { 'data-nueva-busqueda': '1' }),
      revisarTodas, h('span', { class: 'espacio' }), fondo.caja));
    const listaBusquedas = h('div', { class: 'vista' });
    c.appendChild(listaBusquedas);
    function pintar() {
      const cuentas = d.cuentas || [];
      claveLista(listaCuentas, cuentas, (cu) => cu.id, filaCuenta, { vacio: () => h('li', { class: 'vacio' }, 'Todavía no hay ninguna cuenta.') });
      nuevaCuenta.classList.toggle('primario', !cuentas.length);
      const busq = d.busquedas || [];
      revisarTodas.classList.toggle('oculto', !busq.length);
      claveLista(listaBusquedas, busq, (b) => b.id, (b) => tarjetaBusquedaCorreo(d, b, recargar, fondo),
        { vacio: () => panel(null, h('p', { class: 'vacio' }, 'No hay búsquedas de correo. Pulsa «Nueva búsqueda».')) });
    }
    const actualizar = actualizador(() => api('GET', 'correo'), (x) => { d = x; pintar(); });
    const pronto = demorar(actualizar, 400);
    pintar();
    return {
      actualizar,
      evento(ev, visible) {
        if (ev.tipo === 'correo_sesion') { if (visible) toast(ev.texto, ev.ok ? 'ok' : 'error', 10000); pronto(); }
        if (ev.tipo === 'correo') { if (ev.sesion_caducada && visible) toast(ev.resumen, 'error', 12000); pronto(); }
        if (ev.tipo === 'trabajo' && ev.estado !== 'en_curso' && /^correo/.test(ev.tipo_trabajo || '')) pronto();
      },
    };
  };

  // ------------------------------------------------------------------ Accesos
  RUTAS.accesos = async (c) => {
    let d = await api('GET', 'accesos');
    c.appendChild(h('p', { class: 'ayuda' }, 'Datos con los que el bot inicia sesión en cada página. Las contraseñas están en el Administrador de credenciales de Windows (aquí nunca se muestran). La primera vez que las escribes (al grabar o cuando el bot te las pide) se guardan solas; si una página las rechaza, el bot te avisa y no vuelve a probar la misma.'));
    const sitios = h('div', { class: 'vista' });
    c.appendChild(sitios);
    const tarjeta = (s) => {
      const filas = s.campos.map((f) => h('li', null, h('div', { class: 'crece' }, h('div', null, f.etiqueta || f.clave),
        h('div', { class: 'sub mono' }, f.tipo === 'clave' ? 'contraseña «' + f.secreto + '»' + (f.ultimo_ok ? ' · funcionó el ' + f.ultimo_ok : '') : (f.valor || '—')),
        (f.tipo === 'clave' && f.estado === 'rechazada' && f.motivo) ? h('div', { class: 'sub' }, 'La página dijo: «' + f.motivo + '»' +
          (f.motivo_obligatorio ? ' — eso es un dato obligatorio vacío, no la contraseña: puedes quitar la marca.' : '')) : null),
        f.tipo === 'clave' ? (f.estado === 'rechazada' ? chip('rechazada el ' + f.rechazada_en, 'error') : (f.estado === 'guardada' ? chip('guardada', 'ok') : chip('falta', 'aviso'))) : null));
      return panel(h('span', null, s.host, s.estado === 'rechazada' ? chip('contraseña rechazada', 'error') : (s.estado === 'falta' ? chip('falta la contraseña', 'aviso') : chip('al día', 'ok'))),
        h('ul', { class: 'lista' }, filas.length ? filas : h('li', { class: 'vacio' }, 'Sin campos')),
        s.reportes.length ? h('p', { class: 'ayuda' }, 'Lo usan: ' + s.reportes.map((r) => r.nombre).join(', ')) : null,
        h('div', { class: 'fila' },
          boton('Cambiar contraseña', () => modalClave(s.host, { usuario: s.usuario, clave: (s.campos.find((f) => f.tipo === 'clave') || {}).clave, rechazada: s.estado === 'rechazada' }), 'primario'),
          boton('Probar acceso', async () => { try { await api('POST', 'accesos/' + encodeURIComponent(s.host) + '/probar', {}); toast('Probando el acceso a «' + s.host + '»…'); } catch (e) { errorToast(e); } }),
          // v3.3.1: la marca «rechazada» puede ser un error (p. ej. la puso un campo obligatorio vacío, no la contraseña)
          s.estado === 'rechazada' ? boton('Quitar marca de rechazada', async () => {
            if (!(await confirmar('Quitar marca de rechazada', 'El bot volverá a usar la contraseña guardada de «' + s.host + '». Hazlo solo si sabes que la contraseña es correcta (p. ej. la marca la puso un dato obligatorio vacío, como la Licencia). ¿Seguro?', 'Quitar la marca'))) return;
            try { await api('POST', 'accesos/' + encodeURIComponent(s.host) + '/quitar_rechazo', {}); toast('Marca quitada', 'ok'); actualizar(); } catch (e) { errorToast(e); }
          }, '', { 'data-quitar-rechazo': '1' }) : null,
          boton('Borrar', async () => {
            if (await confirmar('Borrar accesos', 'Se borran los datos guardados de «' + s.host + '» (y sus contraseñas guardadas en Accesos). ¿Seguro?', 'Borrar', true)) {
              try { await api('DELETE', 'accesos/' + encodeURIComponent(s.host)); actualizar(); } catch (e) { errorToast(e); }
            }
          }, 'peligro')));
    };
    const pintar = () => claveLista(sitios, d.sitios || [], (s) => s.host, tarjeta, { vacio: () => panel(null, h('p', { class: 'vacio' }, 'Todavía no hay datos de acceso guardados.')) });
    const actualizar = actualizador(() => api('GET', 'accesos'), (x) => { d = x; pintar(); });
    const pronto = demorar(actualizar, 400);
    pintar();
    return {
      actualizar,
      evento(ev) {
        if (ev.tipo === 'acceso_probado' || (ev.tipo === 'aviso' && /clave|acceso/.test(ev.aviso || '')) || (ev.tipo === 'trabajo' && ev.estado !== 'en_curso')) pronto();
      },
    };
  };

  // ------------------------------------------------------------------ Historial
  RUTAS.historial = async (c) => {
    let d = await api('GET', 'historial?limite=150');
    let filtro = 'todos';
    const lista = h('ul', { class: 'filas', 'aria-label': 'Ejecuciones' });
    const meta = h('span', { class: 'meta' });
    const botonesFiltro = [['todos', 'Todas'], ['error', 'Con error'], ['ok', 'Bien']].map(([v, t]) =>
      h('button', { type: 'button', 'aria-pressed': v === 'todos' ? 'true' : 'false', 'data-filtro': v, onclick: () => { filtro = v; botonesFiltro.forEach((b) => b.setAttribute('aria-pressed', b.dataset.filtro === v ? 'true' : 'false')); pintar(); } }, t));
    const fila = (e) => {
      const det = e.mensaje || (e.archivos || []).map(nombreArchivo).join(', ');
      const est = e.resultado === 'ok' ? 'ok' : (e.resultado === 'error' ? 'error' : 'detenido');
      return h('li', { class: 'fila-rep', 'data-estado': e.resultado, 'data-ejecucion': String(e.id) },
        h('span', { class: 'punto ' + est, role: 'img', 'aria-label': { ok: 'bien', error: 'falló', detenido: 'detenido' }[est] }),
        h('div', { class: 'nom' }, e.pagina_id ? h('a', { href: '#/paginas/' + e.pagina_id }, e.nombre) : (e.correo_id ? h('a', { href: '#/correo' }, e.nombre) : (e.reporte_id ? h('a', { href: '#/editor/' + e.reporte_id }, e.nombre) : e.nombre)),
          e.pagina_id ? chip('página', 'info') : null, e.correo_id ? chip('correo', 'info') : null),
        h('div', { class: 'cuando' }, cuandoCorto(e.cuando), h('br'), e.duracion ? duracionTexto(e.duracion) : { ok: 'bien', error: 'falló', detenido: 'detenido' }[est]),
        h('div', { class: 'acc' }, e.registro ? boton('Ver registro', () => verRegistro(e), 'chico') : null,
          e.captura ? boton('Captura del error', () => verCaptura(e), 'chico sec') : null),
        h('div', { class: 'det' + (est === 'error' ? ' err' : ''), title: e.mensaje || '' }, det || '—'));
    };
    function pintar() {
      const todas = d.historial || [];
      const vis = filtro === 'todos' ? todas : todas.filter((e) => (filtro === 'ok' ? e.resultado === 'ok' : e.resultado !== 'ok'));
      claveLista(lista, vis, (e) => e.id, fila, { vacio: () => h('li', { class: 'fila-vacia' }, todas.length ? 'Ninguna ejecución con ese filtro.' : 'Todavía no hay ejecuciones.') });
      meta.textContent = (filtro === 'todos' ? '' : vis.length + ' de ') + todas.length + ' ejecuciones';
    }
    c.appendChild(h('section', { class: 'tarjeta' }, h('header', null, h('h2', null, 'Ejecuciones'),
      h('div', { class: 'chips-filtro', role: 'group', 'aria-label': 'Filtrar' }, botonesFiltro), meta), lista));
    pintar();
    const actualizar = actualizador(() => api('GET', 'historial?limite=150'), (x) => { d = x; pintar(); });
    const pronto = demorar(actualizar, 500);
    return { actualizar, evento: (ev) => { if ((ev.tipo === 'trabajo' && ev.estado !== 'en_curso') || ev.tipo === 'correo') pronto(); } };
  };
  async function verRegistro(e) {
    try {
      const r = await api('GET', 'historial/' + e.id + '/registro');
      abrirModal({ titulo: 'Registro — ' + e.nombre + ' (' + e.cuando + ')', ancho: true, contenido: h('div', null, h('p', { class: 'ayuda' }, r.ruta), h('pre', { class: 'registro' }, r.texto)),
        botones: [{ texto: 'Cerrar', clase: 'primario', accion: cerrarModal }] });
    } catch (err) { errorToast(err); }
  }
  async function verCaptura(e) {
    try {
      const b = await api('GET', 'historial/' + e.id + '/captura');
      const u = URL.createObjectURL(b);
      abrirModal({ titulo: 'Captura del error — ' + e.nombre, ancho: true, contenido: h('img', { class: 'captura', src: u, alt: 'Captura de la página cuando falló' }),
        alCerrar: () => URL.revokeObjectURL(u), botones: [{ texto: 'Cerrar', clase: 'primario', accion: cerrarModal }] });
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ Ajustes
  RUTAS.ajustes = async (c) => {
    const d = await api('GET', 'ajustes');
    const a = d.ajustes;
    const f = {
      navegador: h('select', null, h('option', { value: 'chrome' }, 'Chrome'), h('option', { value: 'msedge' }, 'Edge')),
      timeout_paso: h('input', { type: 'number', value: a.timeout_paso, min: '1' }),
      timeout_descarga: h('input', { type: 'number', value: a.timeout_descarga, min: '10' }),
      pausa_entre_pasos: h('input', { type: 'number', value: a.pausa_entre_pasos, step: '0.1', min: '0' }),
      carpeta_descargas: h('input', { type: 'text', value: a.carpeta_descargas || '', placeholder: d.carpeta_descargas_defecto }),
      recuperacion_automatica: h('input', { type: 'checkbox', checked: a.recuperacion_automatica }),
      esperar_carga: h('input', { type: 'checkbox', checked: a.esperar_carga }),
      ver_mientras_trabaja: h('input', { type: 'checkbox', checked: a.ver_mientras_trabaja }),
    };
    f.navegador.value = a.navegador || 'chrome';
    const guardar = async () => {
      const n = {};
      for (const [k, ctl] of Object.entries(f)) n[k] = ctl.type === 'checkbox' ? ctl.checked : (ctl.type === 'number' ? parseFloat(ctl.value) : ctl.value);
      try { const r = await api('PUT', 'ajustes', { ajustes: n }); E.ajustes = r.ajustes; toast('Ajustes guardados', 'ok'); } catch (e) { errorToast(e); }
    };
    const ef = (t, ctl, ayuda) => [h('label', null, t), ayuda ? h('div', null, ctl, h('div', { class: 'ayuda' }, ayuda)) : ctl];
    c.appendChild(panel('Valores para los reportes nuevos', h('div', { class: 'formulario' },
      ef('Navegador', f.navegador), ef('Tiempo máximo por paso (s)', f.timeout_paso), ef('Espera máxima de descargas/reportes (s)', f.timeout_descarga, 'Lo que puede tardar un reporte en generarse (p. ej. Portal tarda ~80 s).'),
      ef('Pausa entre pasos (s)', f.pausa_entre_pasos), ef('Carpeta de descargas', campoRuta(f.carpeta_descargas, { titulo: 'Carpeta de descargas del bot' })),
      ef('Recuperación automática', f.recuperacion_automatica, 'Si un elemento de un menú no se ve, pasar el ratón por el menú o volver a abrir la lista.'),
      ef('Esperar a que la página cargue', f.esperar_carga, 'Ruedas o barras de «cargando…» y peticiones pendientes. Los menús y listas abiertos no cuentan.'),
      ef('Ver mientras trabaja', f.ver_mientras_trabaja, 'Navegador visible al ejecutar desde esta ventana (las tareas programadas van ocultas).')),
      h('div', { class: 'fila' }, boton('Guardar ajustes', guardar, 'primario'))));
    c.appendChild(panel('Guía de inicio', h('p', { class: 'ayuda' }, 'Te enseña con flechas dónde está cada cosa. Se puede saltar en cualquier momento.'),
      h('div', { class: 'fila' }, boton('Ver la guía otra vez', () => verGuia(), '', { 'data-ver-guia': '1' }))));
    c.appendChild(panel('Acerca de', h('p', { class: 'ayuda' }, 'Bot Web ' + ((E.estado && E.estado.version) || '') + ' · base de datos: ' + d.base_de_datos),
      h('p', { class: 'ayuda' }, 'La ventana clásica sigue disponible con: python bot.py --clasica')));
  };

  // ------------------------------------------------------------------ arranque
  async function arrancar() {
    leerToken();
    // v3.5: iconos del riel y de la cabecera, paleta (Ctrl K) y menú «Más» (pantallas estrechas)
    document.querySelectorAll('[data-ico]').forEach((el) => el.prepend(ico(el.dataset.ico)));
    $('#campana').prepend(ico('campana'));
    $('#btn-paleta').prepend(ico('buscar'));
    $('#btn-paleta').addEventListener('click', abrirPaleta);
    $('#trabajo-detener').prepend(ico('parar'));
    E.trenTrabajo = tren();
    $('#trabajo .via').appendChild(E.trenTrabajo);
    window.addEventListener('keydown', (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === 'k' || ev.key === 'K')) { ev.preventDefault(); abrirPaleta(); }
    });
    $('#riel-mas').addEventListener('click', () => {
      const abierto = $('.riel').classList.toggle('abierto');
      $('#riel-mas').setAttribute('aria-expanded', abierto ? 'true' : 'false');
    });
    document.addEventListener('click', (ev) => {
      if ($('.riel').classList.contains('abierto') && !ev.target.closest('.riel')) { $('.riel').classList.remove('abierto'); $('#riel-mas').setAttribute('aria-expanded', 'false'); }
    });
    window.__botPaleta = { opciones: () => opcionesPaleta(E.buscador ? E.buscador.datos : null), buscar: buscarEnPaleta, normalizar };   // (pruebas)
    window.__botGuia = { abrir: abrirGuia, activa: () => !!GUIA, pasos: pasosGuia };   // (pruebas, v3.8)
    window.__botFechas = { analizar: analizarFecha, componer: componerFecha, describir: describirFecha, strf: strfFecha };   // (pruebas, v3.6)
    $('#campana').addEventListener('click', panelNotificaciones);
    $('#trabajo-detener').addEventListener('click', async () => { try { await api('POST', 'detener', {}); toast('Deteniendo…', 'aviso'); } catch (e) { errorToast(e); } });
    window.addEventListener('hashchange', navegar);
    if (!E.token) { mostrarSinPermiso(); return; }
    try {
      E.estado = await api('GET', 'estado');
    } catch (e) { return; }
    E.ultimo = E.estado.evento || 0;
    $('#version').textContent = 'v' + E.estado.version;
    $('#version').title = 'Bot Web ' + E.estado.version;
    if (E.estado.trabajo) { E.trabajo = E.estado.trabajo; pintarTrabajo(); }
    try { E.ayuda = await api('GET', 'ayuda'); } catch (e) { /* se pide luego */ }
    refrescarCampana();
    await navegar();
    if ((E.estado.preguntas || []).length) mostrarPreguntas();
    else if (E.estado.guia_pendiente && E.ruta === 'inicio') abrirGuia();   // v3.8: la primera vez
    setTimeout(() => datosBuscador(), 1500);          // (la paleta ya tiene sus datos cuando se abra)
    bucleEventos();
    const latido = () => api('POST', 'latido', {}).catch(() => {});
    latido();
    setInterval(latido, 10000);
  }
  arrancar();
})();
