/* Mapeador del Bot Web: encuentra los filtros de una página (o de una parte de ella).
 *
 * mapeador.py lo inyecta (en el documento principal y en CADA marco/iframe) precedido de los bloques de selectores de
 * grabador.js (<<selectores-1 / <<selectores-2), así que aquí se pueden usar candidatos(el), nombreVisible(el), norm,
 * claseDe…
 *
 * window.__botMapear({raiz, base}) → {filtros: [{k, tipo, etiqueta, valor, opciones, selectores, orden, activo, marcado,
 *   tipo_campo, x, y, …}], errores: [{control, error}], info: {listo, clave, controles, url, titulo}}
 *   tipo: pestana | lista (propia: Vuetify, combobox, DevExpress…) | lista_nativa (<select>) | fecha | texto | casilla |
 *   accion.  `base` = primer número k de este documento (los k son únicos entre todos los marcos de la pestaña).
 *   Cada elemento queda marcado con data-bot-mapa=k (mapeador.py abre las listas propias para leer sus opciones).
 *   v3.3: un control que falla al analizarlo no estropea el mapa: va a `errores` y se sigue con los demás.
 * window.__botResumenControles() → resumen de los controles del documento para el diagnóstico (sin los valores de
 *   los campos de contraseña).
 * window.__botSelectorDe(el) → el mejor selector del elemento (para la cadena de iframes).
 * window.__botLeerBusqueda(k) → filas de la ventanita de búsqueda que abrió el botón de búsqueda del filtro k.
 * window.__botElegirParte() → Promise: el usuario pasa el ratón y hace clic en un contenedor (Esc cancela);
 *   devuelve {selector, descripcion} o null.
 */
  const visible = (e) => {
    if (!e || !e.getClientRects().length) return false;
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity || '1') < 0.05) return false;
    const r = e.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const RX_ACCION = /^(generar|buscar|consultar|ver reporte|ver informe|exportar|descargar|filtrar|aplicar|procesar|mostrar|ejecutar|search|export|download|apply|submit|enviar|aceptar)\b/i;
  const RX_FECHA = /fecha|date|desde|hasta|inicio|final|from\b|to\b|picker|calendar|calendario|día|dia\b/i;
  const RX_CLASE_FECHA = /datepicker|date-?picker|hasdatepicker|flatpickr|daterange|(^|[\s_-])date([\s_-]|$)|calendar|fecha|dxeCalendar/i;
  const RX_LUPA = /fa-search|glyphicon-search|bi-search|mdi-magnify|icon-search|(^|[\s_-])(search|lupa|buscar|magnify)([\s_-]|$)/i;
  const SEL_LISTA_PROPIA = '.v-select, .v-autocomplete, .v-combobox, [role=combobox], [aria-haspopup=listbox], .select2-container, ' +
    'mat-select, .mat-select, .mat-mdc-select, .el-select, .ant-select, .p-dropdown, .dx-selectbox, .choices, .vs__dropdown-toggle, ' +
    '.multiselect, .dropdown-toggle[data-toggle=dropdown], .dropdown-toggle[data-bs-toggle=dropdown]';
  const SEL_BOTON = 'button, [role=button], input[type=submit], input[type=button], input[type=image], a.btn, a.v-btn, a[download], ' +
    'a[class*=btn], a[class*=button], a[href^="javascript:"], a[onclick], .dxbButton, .dx-button, li.dxm-item, .dxm-item';

  function textoCorto(n) {
    if (esCarga(n)) return '';
    const t = norm(n && (n.innerText || n.textContent));
    return t.length > 0 && t.length <= 60 ? t : '';
  }
  function sinControles(n) {
    try { return !n.querySelector('input:not([type=hidden]), select, textarea, button, [role=combobox], [role=button]'); } catch (e) { return true; }
  }
  // v3.1: textos que no sirven como etiqueta: «Open»/«Close» (aria-label que Vuetify pone a sus listas), «Abrir»,
  // nombres de iconos («mdi-menu-down»), flechas…  (la misma lista que flujo.etiqueta_generica)
  const RX_GENERICA = /^(open|close|abrir|cerrar|toggle|menu|menú|clear|borrar|limpiar|expand|collapse|desplegar|plegar|mostrar|ocultar|show|hide|appended action|prepended action|dropdown|select|seleccionar|elegir|lista|la lista|list|listbox|combobox|options|opciones|search|buscar|arrow(?:[ _-][\w-]*)?|chevron(?:[ _-][\w-]*)?|caret(?:[ _-][\w-]*)?|(?:mdi|fa|fas|far|bi|icon|material-icons)(?:[ _-][\w-]*)?|div|span|input|label|button|svg|path|li|ul|form|▾|▼|⌄|˅)$/i;
  // v3.8: textos del panel de «cargando» (DevExpress: «Espere…»): nunca son la etiqueta de un filtro
  const RX_CARGA = /^(espere|esperando|cargando|loading|please wait|procesando|wait)\b/i;
  function esCarga(n) {
    if (!n || n.nodeType !== 1) return false;
    if (/(^|\s)dxlp|LoadingPanel/i.test(claseDe(n)) || /LoadingPanel|_LP$|_LPV$/i.test(n.id || '')) return true;
    try { return !!n.closest('[class*=dxlp], [id*=LoadingPanel]'); } catch (e) { return false; }
  }
  const util = (x) => { const t = norm(x); return t.length >= 2 && t.length <= 80 && !RX_GENERICA.test(t) && !RX_CARGA.test(t) ? t : ''; };
  // v3.8: una lista sin etiqueta útil cuyas opciones son formatos de archivo («XLSX», «PDF»…) se llama «Formato»
  const RX_FORMATO = /^(xlsx?|pdf|csv|docx?|rtf|html?|txt|xml|json|mht|png|excel|word)$/i;
  function etiquetaDeLista(t, valor, opciones) {
    const textos = [valor].concat(opciones || []).map(norm).filter(Boolean);
    const formatos = textos.length && textos.every((x) => RX_FORMATO.test(x));
    if (formatos && !/format|tipo|export|archivo|salida/i.test(t || '')) return 'Formato';
    // ERP real (07/11/2026): la lista del formato no tiene etiqueta y el nombre sale del id («cmbTablaExportType»)
    if (/export\s*(type|format)|exporttype|tipo\s*(de\s*)?export/i.test(t || '')) return 'Formato';
    return t;
  }
  // v3.8: filtros de columna de una rejilla (ASPxGridView: fila de filtros con «…_DXFREditorcolN»): secundarios, con el
  // nombre de la cabecera de su columna
  const GRUPO_COLUMNAS = 'Filtros de las columnas de la tabla';
  function columnaDeRejilla(el) {
    const fila = el.closest('tr[id$="_DXFilterRow"], tr[class*="dxgvFilterRow"]');
    const m = /^(.*)_DXFREditorcol(\d+)(?:_I)?$/.exec(el.id || '');
    if (!fila && !m) return null;
    let et = '';
    let n = m ? parseInt(m[2], 10) + 1 : 0;
    if (m) { const cab = document.getElementById(m[1] + '_col' + m[2]); if (cab) et = util(textoCorto(cab)); }
    if (!et && fila) {
      let c = el;
      while (c && c.parentElement !== fila) c = c.parentElement;
      const i = c ? Array.prototype.indexOf.call(fila.children, c) : -1;
      if (!n && i >= 0) n = i + 1;
      const pref = m ? m[1] : (fila.id || '').replace(/_DXFilterRow$/, '');
      let cabs = null;
      try { cabs = pref ? document.querySelector('tr[id^="' + pref + '_DXHeadersRow"]') : null; } catch (e) { cabs = null; }
      if (!cabs) for (let p = fila.previousElementSibling; p && !cabs; p = p.previousElementSibling) if (sinControles(p)) cabs = p;
      if (cabs && i >= 0 && cabs.children[i]) et = util(textoCorto(cabs.children[i]));
    }
    return { etiqueta: et || ('Columna ' + (n || '?')) };
  }
  // v3.8: id de ASP.NET (WebForms): fijo aunque lleve números («ctl00_formContent_wuc_1000_01_…»), así que en el ERP
  // se prefiere a la ruta CSS (que cambia si la página añade un bloque)
  const RX_ID_ASP = /^(ctl\d{2}|MainContent|formContent|mainFormPage|ContentPlaceHolder\w*)[_$]|_(formContent|MainContent)_/;
  function selectorAsp(el) {
    for (let n = el, k = 0; n && n.nodeType === 1 && k < 3; n = n.parentElement, k++) {
      const id = n.id || '';
      if (!id || id.length > 200 || !RX_ID_ASP.test(id)) continue;
      const base = '#' + cssEsc(id);
      if (n === el) { if (unico(base, el)) return base; continue; }
      const cl = clasesEstables(el)[0];
      const s = base + ' ' + el.tagName.toLowerCase() + (cl ? '.' + cssEsc(cl) : '');
      if (unico(s, el)) return s;
    }
    return '';
  }
  // v3.8: casilla de DevExpress (ASPxCheckBox): un <span> con clases …CheckBoxChecked/Unchecked y un <input> oculto
  // «…_S» (valor C/U); el <input type=checkbox> no existe
  const SEL_CASILLA_DX = 'span[id$="_S_D"], .dxICheckBox, [class*=dxICheckBox], .dxichSys';
  function marcadaDx(sp) {
    const c = claseDe(sp);
    if (/Unchecked/i.test(c)) return false;
    if (/Checked/i.test(c)) return true;
    const i = sp.querySelector('input');
    return !!i && /^(c|checked|true|1)$/i.test(i.value || '');
  }
  function etiquetaDeCasillaDx(sp) {
    const raiz = sp.closest('[class*=dxeBase], .dxichCellSys, td') || sp.parentElement;
    for (let n = raiz, k = 0; n && k < 3; n = n.parentElement, k++) {
      const l = n.querySelector && n.querySelector('label, .dxichTextCellSys, [class*=dxichTextCell]');
      if (l && !l.contains(sp)) { const t = util(l.innerText || l.textContent); if (t) return t; }
      for (let s = n.nextElementSibling, j = 0; s && j < 2; s = s.nextElementSibling, j++) {
        if (sinControles(s)) { const t = util(textoCorto(s)); if (t) return t; }
      }
    }
    return '';
  }
  // v3.8: campo de búsqueda doble (código + descripción, p. ej. «wbeEmpleado_txtCod_I» y «wbeEmpleado_txtDescrip_I»,
  // con un «…_txtId» oculto y una lupa): UN filtro de texto con búsqueda, con la etiqueta de su fila («Empleado»)
  const RX_PARTE_DOBLE = /^(.+?)_(?:txt|tb)?(Cod|Codigo|Código|Id|Descrip|Descripcion|Descripción|Nombre)(?:_I)?$/i;
  function etiquetaDeFila(el) {
    for (let n = el, k = 0; n && k < 10; n = n.parentElement, k++) {
      if (n.tagName !== 'TD' && n.tagName !== 'TH') continue;
      for (let p = n.previousElementSibling, j = 0; p && j < 2; p = p.previousElementSibling, j++) {
        if (!sinControles(p)) break;
        const t = util(textoCorto(p));
        if (t) return t;
      }
    }
    return '';
  }

  // v3.3: nombre legible a partir del name/id de ASP.NET o DevExpress: «ctl00$formContent$txtFechaIni» → «Fecha Ini»,
  // «MainContent_ddlLocalidad» → «Localidad», «…_cbAlmacen_I» → «Almacen».
  function humanizar(s) {
    if (!s) return '';
    let partes = String(s).split(/[$:]/).pop().split('_').filter(Boolean);
    while (partes.length > 1 && /^(I|B-?\d*|DDD.*|S|VI|KBS|CD|ET|Raw|Input|D|L|LB|C|CB)$/.test(partes[partes.length - 1])) partes.pop();
    let t = partes.length ? partes[partes.length - 1] : '';
    if (/^ctl\d+$/i.test(t)) return '';
    let fecha = false;
    const m = /^(txt|tb|ddl|cbo|cmb|cb|lst|lb|lbx|chk|cbx|rb|rdb|rbl|date|dte|dt|de|dx|asp|btn|ibtn|lnk|sel|inp|input|fld|field|hdn|hf|num|spn|se)(?=[A-Z0-9])/.exec(t);
    if (m) { fecha = /^(date|dte|dt|de)$/.test(m[1]); t = t.slice(m[1].length); }
    t = t.replace(/([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2').replace(/[_\-.]+/g, ' ');
    t = norm(t);
    if (!t || !/[A-Za-zÁÉÍÓÚáéíóúñÑ]{2,}/.test(t)) return '';
    if (fecha && !/fecha|date/i.test(t)) t = 'Fecha ' + t;
    return t.charAt(0).toUpperCase() + t.slice(1);
  }
  // texto de la celda anterior en la misma fila de una tabla (`<td>Fecha Inicial</td><td><input></td>`) o, si no hay,
  // la cabecera de esa columna
  function etiquetaDeCelda(el) {
    const celda = el.closest('td, th');
    if (!celda) return '';
    for (let p = celda.previousElementSibling, k = 0; p && k < 3; p = p.previousElementSibling, k++) {
      if (!sinControles(p)) break;
      const t = util(textoCorto(p));
      if (t) return t;
    }
    const fila = celda.parentElement;
    const tabla = celda.closest('table');
    if (fila && tabla) {
      const i = Array.prototype.indexOf.call(fila.children, celda);
      const cab = tabla.querySelector('thead tr') || (fila.previousElementSibling && sinControles(fila.previousElementSibling) ? fila.previousElementSibling : null);
      if (cab && cab !== fila && cab.children[i] && sinControles(cab.children[i])) return util(textoCorto(cab.children[i]));
    }
    return '';
  }
  // texto suelto justo antes del campo dentro del mismo padre («Desde: <input>»)
  function textoAnterior(el) {
    let t = '';
    for (let n = el.previousSibling, k = 0; n && k < 4; n = n.previousSibling, k++) {
      if (n.nodeType === 3) { t = norm(n.textContent) + (t ? ' ' + t : ''); if (t) break; continue; }
      if (n.nodeType !== 1) continue;
      if (!sinControles(n) || /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(n.tagName)) break;
      if (/^(BR|I|IMG|SVG)$/.test(n.tagName)) continue;
      t = textoCorto(n);
      if (t) break;
    }
    return util(t);
  }
  // DevExpress: leyendas de los editores (dxeCaption) y del FormLayout (dxflCaption)
  function etiquetaDevExpress(el) {
    const caja = el.closest('.dxflItem, .dxflGroupCell, tr, .dxeRoot, [class*=dxe], .dxflNestedControlCell');
    for (let n = el, k = 0; n && k < 6; n = n.parentElement, k++) {
      const cap = n.querySelector && n.querySelector('.dxeCaption, .dxflCaption, [class*=dxeCaption], [class*=dxflCaption], [id$="_CaptionCell"]');
      if (cap && !cap.contains(el)) { const t = util(cap.innerText || cap.textContent); if (t) return t; }
      if (caja && n === caja) break;
    }
    return '';
  }
  // Etiqueta del filtro: <label>, etiqueta flotante (Vuetify, Material), aria, DevExpress, leyenda, texto de ayuda
  // («hint») del campo, celda anterior de la tabla, texto anterior, placeholder, title o el name/id legible.
  // Nunca se descarta un control por no tener etiqueta.
  function etiquetaDe(el, envoltorio) {
    let t = '';
    try { if (el.labels && el.labels.length) t = util(el.labels[0].innerText || el.labels[0].textContent); } catch (e) {}
    if (!t && el.id) { try { const l = document.querySelector('label[for="' + cssEsc(el.id) + '"]'); if (l) t = util(l.innerText); } catch (e) {} }
    const w = envoltorio || el;
    if (!t && w.querySelector) {
      const fl = w.querySelector('label, .v-label, .mat-form-field-label, .mat-mdc-floating-label, .ant-form-item-label, legend');
      if (fl) t = util(fl.innerText || fl.textContent);
    }
    if (!t) t = util(el.getAttribute('aria-label'));
    if (!t && el.getAttribute('aria-labelledby')) {
      t = util(el.getAttribute('aria-labelledby').split(/\s+/).map((i) => { const l = document.getElementById(i); return l ? l.textContent : ''; }).join(' '));
    }
    if (!t) t = etiquetaDevExpress(w);
    if (!t) { const fs = w.closest('fieldset'); const lg = fs && fs.querySelector('legend'); if (lg) t = util(lg.innerText); }
    if (!t && w.querySelector) {
      // texto de ayuda del propio campo (Vuetify «hint»/persistent-hint, Material mat-hint, Bootstrap form-text)
      const hint = w.querySelector('.v-messages__message, .mat-hint, .mat-mdc-form-field-hint, .form-text, .help-block');
      if (hint) t = util(hint.innerText || hint.textContent);
    }
    if (!t) t = etiquetaDeCelda(w);
    if (!t) t = textoAnterior(w);
    if (!t) {
      // texto de ayuda justo antes del campo (en el mismo bloque o en el bloque anterior)
      let n = w;
      for (let nivel = 0; nivel < 3 && n && !t; nivel++, n = n.parentElement) {
        for (let p = n.previousElementSibling, k = 0; p && k < 2 && !t; p = p.previousElementSibling, k++) {
          // v3.8: un menú de la web (barra de arriba) no es la etiqueta del campo que tiene al lado
          if (sinControles(p) && visible(p) && !(p.matches && p.matches('nav, [role=menubar], [role=menu], [class*=dxm-main], ul, ol'))) t = util(textoCorto(p));
          if (!sinControles(p)) break;
        }
        if (n.parentElement && n.parentElement.querySelectorAll('input:not([type=hidden]), select, textarea, [role=combobox]').length > 1) break;
      }
    }
    if (!t) t = util(el.getAttribute('placeholder')) || util(el.getAttribute('title'));
    if (!t) t = humanizar(el.getAttribute('name')) || humanizar(el.id) || humanizar(w.id);
    return t.replace(/[:*]+$/, '').trim().slice(0, 80);
  }
  function valorPropio(w) {
    const sel = w.querySelector('.v-select__selection-text, .v-select__selection, .v-chip__content, .select2-selection__rendered, ' +
      '.mat-select-value-text, .mat-mdc-select-value-text, .ant-select-selection-item, .p-dropdown-label, .filter-option-inner-inner');
    if (sel) return norm(sel.innerText || sel.textContent);
    const i = w.querySelector('input:not([type=hidden])');
    if (i && i.value) return norm(i.value);
    return '';
  }
  function objetivoDeLista(w) {
    // dónde hacer clic para abrir la lista: el recuadro del campo (Vuetify: .v-field) o el propio elemento
    return w.querySelector('.v-field') || w.querySelector('[role=combobox]') || w;
  }
  // DevExpress (ASPxComboBox / ASPxDateEdit): el campo «…_I» dentro de una tabla «…» con el botón «…_B-1»; la lista
  // está (oculta) en «…_DDD_L» con filas .dxeListBoxItem y el calendario en «…_DDD_C».
  function devExpress(e) {
    const id = e.id || '';
    if (!/_I$/.test(id)) return null;
    const base = id.slice(0, -2);
    const caja = document.getElementById(base) || e.closest('table[class*=dxeButtonEdit], .dxeButtonEditSys, [class*=dxeButtonEdit]');
    const lista = document.getElementById(base + '_DDD_L') || document.getElementById(base + '_L');
    const cal = document.getElementById(base + '_DDD_C');
    let boton = document.getElementById(base + '_B-1') || (caja && caja.querySelector('[id$="_B-1"], .dxeButtonEditButton, td[class*=dxeButton]'));
    // v3.8: los botones propios de un ButtonEdit («…_B0», «…_B1»: la lupa) no abren ninguna lista
    if (boton && /_B\d+$/.test(boton.id || '') && !document.getElementById(base + '_DDD_PW-1')) boton = null;
    if (cal || /dxeCalendar|DateEdit/i.test(claseDe(caja) + ' ' + (caja ? caja.id : ''))) return { tipo: 'fecha', caja: caja || e };
    if (lista || boton) {
      let ops = [];
      if (lista) ops = Array.from(lista.querySelectorAll('.dxeListBoxItem, [class*=dxeListBoxItem], td.dxeLTM, li'))
        .map((o) => norm(o.textContent)).filter((t) => t);
      return { tipo: 'lista', caja: caja && caja.contains(e) ? caja : e, opciones: Array.from(new Set(ops)) };
    }
    return null;
  }
  // botón de búsqueda (lupa) junto a un campo de texto: «Cuenta No. [____] (lupa)» que abre una ventanita con una tabla
  function botonBusqueda(e) {
    let n = e.parentElement;
    for (let nivel = 0; n && nivel < 3; nivel++, n = n.parentElement) {
      const campos = n.querySelectorAll('input:not([type=hidden]), select, textarea');
      if (campos.length > 1) break;
      for (const b of n.querySelectorAll('button, a, input[type=button], input[type=image], input[type=submit], span[onclick], i[onclick]')) {
        if (b === e || !visible(b)) continue;
        const pista = [claseDe(b), b.id, b.getAttribute('name'), b.getAttribute('title'), b.getAttribute('aria-label'),
          b.innerHTML.slice(0, 300), b.getAttribute('value')].join(' ');
        const t = norm(b.innerText || b.value || '');
        if (RX_LUPA.test(pista) || /^btnS[A-Z]|buscar|search|lupa/i.test(b.id + ' ' + (b.getAttribute('name') || '')) ||
            (/^\.\.\.$|^…$/.test(t))) {
          if (t && RX_ACCION.test(t) && !/^buscar$|^search$/i.test(t)) continue;      // «Ver Reporte» no es una lupa
          return b;
        }
      }
    }
    return null;
  }
  function esFechaCampo(e, tipo, et) {
    if (['date', 'datetime-local', 'month', 'week'].includes(tipo)) return true;
    const p = e.parentElement, g = p && p.parentElement;
    const pistas = [et, e.id, e.getAttribute('name'), e.getAttribute('placeholder'), claseDe(e), p ? claseDe(p) + ' ' + (p.id || '') : ''].join(' ');
    if (RX_FECHA.test(pistas)) return true;
    if (RX_CLASE_FECHA.test(claseDe(e) + ' ' + (p ? claseDe(p) : '') + ' ' + (g ? claseDe(g) : ''))) return true;
    if (e.getAttribute('data-provide') === 'datepicker' || e.hasAttribute('data-date-format')) return true;
    if (p && p.querySelector('.fa-calendar, .glyphicon-calendar, .bi-calendar, .mdi-calendar, [class*=calendar]')) return true;
    return /^\d{1,4}[\/\-.]\d{1,2}[\/\-.]\d{1,4}$/.test(e.value || '');
  }
  function describir(el) {
    if (!el || !el.tagName) return String(el);
    let d = el.tagName.toLowerCase();
    if (el.id) d += '#' + el.id;
    else if (el.getAttribute && el.getAttribute('name')) d += '[name=' + el.getAttribute('name') + ']';
    else if (claseDe(el)) d += '.' + claseDe(el).trim().split(/\s+/).slice(0, 2).join('.');
    return d.slice(0, 100);
  }

  window.__botSelectorDe = (el) => { try { return candidatos(el)[0] || null; } catch (e) { return null; } };

  window.__botMapear = (a) => {
    a = a || {};
    let raiz = document.body || document.documentElement;
    if (a.raiz) { try { raiz = document.querySelector(a.raiz) || raiz; } catch (e) { /* selector no válido: todo */ } }
    const base = parseInt(a.base || 0, 10) || 0;
    document.querySelectorAll('[data-bot-mapa]').forEach((e) => e.removeAttribute('data-bot-mapa'));
    document.querySelectorAll('[data-bot-busca]').forEach((e) => e.removeAttribute('data-bot-busca'));
    const host = document.getElementById('__bot_host__');
    const res = [];
    const errores = [];
    const usados = new Set();
    const ya = (e) => { for (const u of usados) if (u === e || u.contains(e)) return true; return false; };
    const intentar = (el, fn) => {
      try { fn(); }
      catch (e) { errores.push({ control: describir(el), error: String((e && e.message) || e).slice(0, 200) }); }
    };
    const anotar = (el, d) => {
      d.k = base + res.length;
      el.setAttribute('data-bot-mapa', String(d.k));
      let r = { top: 0, left: 0 };
      try { r = el.getBoundingClientRect(); } catch (e) { /* nada */ }
      d.y = Math.round(r.top + scrollY); d.x = Math.round(r.left + scrollX);
      try { d.selectores = candidatos(el); } catch (e) { d.selectores = []; }
      try {
        const asp = selectorAsp(el);
        if (asp) d.selectores = [asp].concat(d.selectores.filter((s) => s !== asp));
      } catch (e) { /* nada */ }
      if (!d.selectores.length) d.selectores = ['[data-bot-mapa="' + d.k + '"]'];
      try {
        const col = columnaDeRejilla(el);
        if (col) { d.secundario = true; d.grupo = GRUPO_COLUMNAS; d.etiqueta = col.etiqueta; }
      } catch (e) { /* nada */ }
      res.push(d);
    };
    const dentro = (e) => raiz.contains(e) && !(host && host.contains(e)) && visible(e);
    const todos = (sel) => { try { return Array.from(raiz.querySelectorAll(sel)); } catch (e) { errores.push({ control: sel, error: String(e) }); return []; } };

    // pestañas
    for (const t of todos('[role=tab], .v-tab, .nav-tabs .nav-link, .mat-tab-label, .mat-mdc-tab, .ui-tabs-anchor, .dxtc-tab')) {
      intentar(t, () => {
        if (!dentro(t) || ya(t)) return;
        const et = norm(t.innerText || t.textContent);
        if (!et) return;
        usados.add(t);
        anotar(t, { tipo: 'pestana', etiqueta: et.slice(0, 80), activo: t.getAttribute('aria-selected') === 'true' ||
          /(^|\s)(active|v-tab--selected|mat-tab-label-active|v-slide-group-item--active|dxtc-activeTab)(\s|$)/.test(claseDe(t)) });
      });
    }
    // v3.8: campos de búsqueda dobles (código + descripción + lupa) → un filtro
    const dobles = new Map();
    for (const e of todos('input[id]')) {
      const m = RX_PARTE_DOBLE.exec(e.id);
      if (!m) continue;
      if (!dobles.has(m[1])) dobles.set(m[1], {});
      const papel = /^(cod|codigo|código)$/i.test(m[2]) ? 'cod' : (/^id$/i.test(m[2]) ? 'id' : 'desc');
      dobles.get(m[1])[papel] = e;
    }
    for (const [pref, g] of dobles) {
      const principal = (g.cod && visible(g.cod)) ? g.cod : ((g.desc && visible(g.desc)) ? g.desc : null);
      if (!principal || !(g.cod && g.desc) || ya(principal) || !dentro(principal)) continue;
      intentar(principal, () => {
        for (const x of [g.cod, g.desc, g.id]) {
          if (!x) continue;
          usados.add(x);
          const caja = document.getElementById(x.id.replace(/_I$/, ''));
          if (caja && caja !== x && !caja.contains(principal)) usados.add(caja);
        }
        let lupa = null;
        for (const b of todos('[id^="' + pref + '_"]')) {
          if ([g.cod, g.desc, g.id].includes(b) || !visible(b)) continue;
          if (/^(INPUT|TEXTAREA|SELECT)$/.test(b.tagName) && !/^(button|image|submit)$/i.test(b.type || '')) continue;
          if (b.querySelector('input:not([type=hidden]), table')) continue;
          const pista = b.id + ' ' + claseDe(b) + ' ' + (b.getAttribute('title') || '') + ' ' + (b.innerHTML || '').slice(0, 200);
          if (/_B\d+$|btn|buscar|busqueda|búsqueda|lupa|search|ButtonEditButton|Ellipsis/i.test(pista)) { lupa = b; break; }
        }
        if (!lupa) lupa = botonBusqueda(g.desc || principal);
        const et = etiquetaDeFila(principal) || humanizar(pref.replace(/^[a-z]{2,4}(?=[A-Z])/, '')) || etiquetaDe(principal);
        const d = { tipo: 'texto', tipo_campo: 'text', etiqueta: et, valor: principal.value || '', solo_lectura: !!principal.readOnly, doble: true };
        if (lupa) {
          usados.add(lupa);
          let sels = [];
          try { sels = candidatos(lupa); } catch (x) { sels = []; }
          const asp = selectorAsp(lupa);
          if (asp) sels = [asp].concat(sels.filter((s) => s !== asp));
          d.busqueda = { selectores: sels, etiqueta: norm(lupa.getAttribute('title') || lupa.getAttribute('aria-label') || '') };
        }
        anotar(principal, d);
        if (lupa) lupa.setAttribute('data-bot-busca', String(d.k));
      });
    }
    // v3.8: casillas de DevExpress (ASPxCheckBox: <span> con su estado en la clase)
    for (const sp of todos(SEL_CASILLA_DX)) {
      intentar(sp, () => {
        if (ya(sp) || !dentro(sp)) return;
        if (sp.parentElement && sp.parentElement.closest(SEL_CASILLA_DX)) return;
        usados.add(sp);
        sp.querySelectorAll('input').forEach((i) => usados.add(i));
        anotar(sp, { tipo: 'casilla', tipo_campo: 'casilla', etiqueta: etiquetaDeCasillaDx(sp) || etiquetaDe(sp), marcado: marcadaDx(sp), dx: 'casilla' });
      });
    }
    // DevExpress: listas (ASPxComboBox) y fechas (ASPxDateEdit)
    for (const e of todos('input[id$="_I"]')) {
      intentar(e, () => {
        if (ya(e) || !dentro(e)) return;
        const dx = devExpress(e);
        if (!dx) return;
        usados.add(dx.caja);
        if (dx.tipo === 'fecha') {
          anotar(e, { tipo: 'fecha', tipo_campo: 'text', etiqueta: etiquetaDe(e, dx.caja), valor: e.value || '', dx: 'fecha' });
        } else {
          anotar(dx.caja, { tipo: 'lista', etiqueta: etiquetaDeLista(etiquetaDe(e, dx.caja), e.value || '', dx.opciones), valor: norm(e.value || ''), dx: 'combo',
            opciones: dx.opciones.length ? dx.opciones : null });
        }
      });
    }
    // listas propias (Vuetify, combobox…): se marca el envoltorio y se abre su recuadro
    for (const w of todos(SEL_LISTA_PROPIA)) {
      intentar(w, () => {
        if (!dentro(w) || ya(w)) return;
        // los desplegables de Bootstrap de la barra o del menú lateral del sitio (usuario, avisos…) no son filtros
        if (w.matches('.dropdown-toggle') && w.closest('nav, .navbar, header, .main-header, .main-sidebar, .sidebar, [role=navigation]')) return;
        let env = w;
        const v = w.closest('.v-input, .mat-form-field, .mat-mdc-form-field, .ant-select, .el-select');
        if (v && raiz.contains(v)) env = v;
        if (ya(env)) return;
        usados.add(env);
        const obj = objetivoDeLista(env);
        const campo = env.querySelector('input:not([type=hidden])') || obj;
        anotar(obj, { tipo: 'lista', etiqueta: etiquetaDe(campo, env), valor: valorPropio(env), opciones: null });
      });
    }
    // listas nativas
    for (const s of todos('select')) {
      intentar(s, () => {
        if (ya(s) || !dentro(s)) return;
        usados.add(s);
        const ops = Array.from(s.options).filter((o) => !o.disabled).map((o) => norm(o.text)).filter((t) => t);
        const valorSel = s.selectedIndex >= 0 ? norm(s.options[s.selectedIndex].text) : '';
        anotar(s, { tipo: 'lista_nativa', etiqueta: etiquetaDeLista(etiquetaDe(s), valorSel, ops), valor: valorSel,
          opciones: ops });
      });
    }
    // campos (fechas, textos —con lupa de búsqueda o no—), casillas
    for (const e of todos('input, textarea, [role=checkbox], [role=switch]')) {
      intentar(e, () => {
        if (ya(e) || !dentro(e)) return;
        const tipo = (e.getAttribute('type') || (e.tagName === 'TEXTAREA' ? 'textarea' : 'text')).toLowerCase();
        if (['hidden', 'submit', 'button', 'reset', 'image', 'file', 'password'].includes(tipo)) return;
        const rol = e.getAttribute('role');
        if (tipo === 'checkbox' || tipo === 'radio' || rol === 'checkbox' || rol === 'switch') {
          usados.add(e);
          const marcado = 'checked' in e ? !!e.checked : e.getAttribute('aria-checked') === 'true';
          anotar(e, { tipo: 'casilla', tipo_campo: tipo === 'radio' ? 'radio' : 'casilla', etiqueta: etiquetaDe(e), marcado });
          return;
        }
        const et = etiquetaDe(e);
        const valor = e.value || '';
        const lupa = botonBusqueda(e);
        usados.add(e);
        if (lupa) {
          usados.add(lupa);
          const d = { tipo: 'texto', tipo_campo: tipo, etiqueta: et, valor, solo_lectura: !!e.readOnly };
          let sels = [];
          try { sels = candidatos(lupa); } catch (x) { sels = []; }
          d.busqueda = { selectores: sels, etiqueta: norm(lupa.getAttribute('title') || lupa.getAttribute('aria-label') || lupa.innerText || lupa.value || '') };
          anotar(e, d);
          lupa.setAttribute('data-bot-busca', String(d.k));
          return;
        }
        anotar(e, { tipo: esFechaCampo(e, tipo, et) ? 'fecha' : 'texto', tipo_campo: tipo, etiqueta: et, valor,
          solo_lectura: !!e.readOnly });
      });
    }
    // botones de acción (Generar, Buscar, Consultar, Ver Reporte, Exportar, Descargar…), también los <input type=image>,
    // los enlaces con aspecto de botón (LinkButton de ASP.NET) y las opciones de los menús de DevExpress
    for (const b of todos(SEL_BOTON)) {
      intentar(b, () => {
        if (ya(b) || !dentro(b)) return;
        const esDxMenu = /(^|\s)dxm-item(\s|$)/.test(claseDe(b));
        const contenido = esDxMenu ? (b.querySelector('.dxm-content') || b) : b;
        const t = norm(contenido.innerText || b.value || b.getAttribute('alt') || b.getAttribute('aria-label') || b.getAttribute('title') || '');
        if (!t || t.length > 40) return;
        const conSubmenu = esDxMenu && /export/i.test(t) && !RX_ACCION.test(t);
        if (!RX_ACCION.test(t) && !conSubmenu) return;
        usados.add(b);
        const d = { tipo: 'accion', etiqueta: t, descarga: /exportar|descargar|export|download/i.test(t) && !conSubmenu || b.hasAttribute('download') };
        if (esDxMenu) d.menu = true;
        if (conSubmenu) d.submenu = true;
        anotar(esDxMenu ? contenido : b, d);
      });
    }
    res.sort((p, q) => (p.y - q.y) || (p.x - q.x));
    res.forEach((d, i) => { d.orden = i; });
    let clave = false;
    try { clave = Array.from(document.querySelectorAll('input[type=password]')).some(visible); } catch (e) { /* nada */ }
    let controles = 0;
    try { controles = document.querySelectorAll('input:not([type=hidden]), select, textarea, button').length; } catch (e) { /* nada */ }
    return { filtros: res, errores, info: { listo: document.readyState, clave, controles, url: location.href, titulo: document.title || '' } };
  };

  // Resumen de los controles (diagnóstico): nunca el valor de un campo de contraseña.
  window.__botResumenControles = () => {
    const res = [];
    const lista = document.querySelectorAll('input, select, textarea, button, [role=combobox], [role=button], [role=tab], a[class*=btn], .dxm-item');
    for (const e of Array.from(lista).slice(0, 300)) {
      try {
        const tipo = (e.getAttribute('type') || '').toLowerCase();
        const d = { tag: e.tagName.toLowerCase(), tipo, id: e.id || '', name: e.getAttribute('name') || '',
          clase: claseDe(e).slice(0, 80), role: e.getAttribute('role') || '', visible: visible(e) };
        try { d.etiqueta = etiquetaDe(e); } catch (x) { d.etiqueta = '(error: ' + String(x).slice(0, 60) + ')'; }
        if (e.tagName === 'SELECT') d.opciones = e.options.length;
        if (e.tagName === 'BUTTON' || /^(submit|button|image)$/.test(tipo) || e.tagName === 'A' || e.getAttribute('role')) {
          d.texto = norm(e.innerText || e.value || e.getAttribute('alt') || '').slice(0, 60);
        } else if (tipo !== 'password' && e.tagName !== 'SELECT' && !/clave|password|contrase|pwd|pass/i.test(d.id + ' ' + d.name)) {
          d.valor = String(e.value || '').slice(0, 60);
        }
        res.push(d);
      } catch (x) { res.push({ error: String(x).slice(0, 100) }); }
    }
    return { url: location.href, titulo: document.title || '', listo: document.readyState, total: lista.length, controles: res };
  };

  // v3.8: trozo de HTML alrededor de cada filtro marcado (diagnóstico): sin valores de campos ni contraseñas
  window.__botExtractos = () => {
    const res = {};
    for (const el of Array.from(document.querySelectorAll('[data-bot-mapa]')).slice(0, 120)) {
      try {
        const zona = (el.parentElement && el.parentElement.outerHTML.length <= 1500) ? el.parentElement : el;
        const c = zona.cloneNode(true);
        c.querySelectorAll('input[type=password]').forEach((x) => x.remove());
        let h = c.outerHTML.replace(/\s(value|data-value|aria-valuetext)="[^"]*"/gi, '').replace(/<option\b[^>]*>[^<]*<\/option>/gi, '<option/>');
        h = h.replace(/\s+/g, ' ');
        res[el.getAttribute('data-bot-mapa')] = h.length > 400 ? h.slice(0, 400) + '…' : h;
      } catch (e) { /* nada */ }
    }
    return res;
  };

  // Filas de la ventanita de búsqueda (tabla dentro de un modal/diálogo/ventana emergente visible).
  window.__botLeerBusqueda = () => {
    const SEL_POP = '.modal.in, .modal.show, .modal[style*="block"], [role=dialog], .ui-dialog, .dxpc-content, .dxpcLite, .popup, .k-window';
    const pops = Array.from(document.querySelectorAll(SEL_POP)).filter(visible);
    const zonas = pops.length ? pops : [];
    for (const z of zonas) {
      const tabla = Array.from(z.querySelectorAll('table')).filter(visible).find((t) => t.querySelectorAll('tbody tr td').length);
      if (!tabla) continue;
      const filas = [];
      for (const tr of Array.from(tabla.querySelectorAll('tbody tr')).slice(0, 300)) {
        const celdas = Array.from(tr.querySelectorAll('td')).map((c) => norm(c.innerText || c.textContent)).filter((t) => t);
        if (celdas.length && !/no (data|hay)|sin (datos|registros)|no records/i.test(celdas.join(' '))) filas.push(celdas);
      }
      let sel = '';
      try { sel = candidatos(tabla)[0] || ''; } catch (e) { sel = ''; }
      return { filas, tabla: sel, abierta: true };
    }
    return { filas: [], tabla: '', abierta: false };
  };

  // «Mapear una parte»: el usuario elige un contenedor con el ratón (se resalta) y hace clic.
  // v3.8: se instala en cada documento (también dentro de los iframes); `a.aviso` = enseñar el letrero (solo arriba);
  // window.__botCancelarParte() lo quita cuando el usuario ya eligió en otro documento.
  window.__botElegirParte = (a) => new Promise((resolver) => {
    a = a || { aviso: true };
    if (window.__botCancelarParte) window.__botCancelarParte();
    const marco = document.createElement('div');
    marco.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483646;border:3px solid #e30613;' +
      'background:rgba(227,6,19,.08);border-radius:6px;transition:all .05s';
    const aviso = document.createElement('div');
    aviso.textContent = 'Pasa el ratón sobre la parte de la página con los filtros y haz clic (Esc cancela)';
    aviso.style.cssText = 'position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#111827;' +
      'color:#fff;padding:8px 14px;border-radius:8px;font:14px Segoe UI,Arial,sans-serif;pointer-events:none';
    document.documentElement.appendChild(marco);
    if (a.aviso !== false) document.documentElement.appendChild(aviso);
    let actual = null;
    const elegible = (e) => {
      // sube hasta un contenedor que tenga algún control (para no elegir un texto suelto)
      for (let n = e; n && n !== document.documentElement; n = n.parentElement) {
        if (n.querySelector && n.querySelector('input, select, textarea, button, [role=combobox], [role=tab], iframe')) return n;
      }
      return e;
    };
    const mover = (ev) => {
      const e = elegible(ev.target);
      if (!e || e === actual) return;
      actual = e;
      const r = e.getBoundingClientRect();
      marco.style.left = r.left + 'px'; marco.style.top = r.top + 'px'; marco.style.width = r.width + 'px'; marco.style.height = r.height + 'px';
    };
    const fin = (valor) => {
      document.removeEventListener('mousemove', mover, true);
      document.removeEventListener('click', clic, true);
      document.removeEventListener('keydown', tecla, true);
      marco.remove(); aviso.remove();
      if (window.__botCancelarParte === cancelar) window.__botCancelarParte = null;
      resolver(valor);
    };
    const cancelar = () => fin(null);
    window.__botCancelarParte = cancelar;
    const clic = (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      const e = elegible(ev.target);
      let sel = '';
      try { sel = candidatos(e)[0] || ''; } catch (x) { sel = ''; }
      fin(sel ? { selector: sel, descripcion: nombreVisible(e) } : null);
    };
    const tecla = (ev) => { if (ev.key === 'Escape') { ev.preventDefault(); fin(null); } };
    document.addEventListener('mousemove', mover, true);
    document.addEventListener('click', clic, true);
    document.addEventListener('keydown', tecla, true);
  });
