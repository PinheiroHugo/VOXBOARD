(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const character = byId('vox-character');
  const panel = document.querySelector('.home-vox-zone');
  const start = byId('record-start'), stop = byId('record-stop');
  const status = byId('voice-status');
  const catalog = byId('vox-resources');
  const resources = JSON.parse(catalog.textContent);
  const fields = byId('vox-school-fields'), previewBox = byId('vox-school-preview');
  const dialog = byId('vox-resource-dialog');
  const motion = window.VoxMotion?.create(character);
  const setState = state => motion ? motion.setState(state) : character.dataset.state = state;
  let pending = null, preview = null, busy = false;

  function clearPending() { pending = preview = null; fields.hidden = previewBox.hidden = true; }
  function idle() {
    if (motion) motion.finish(); else character.dataset.state = 'idle';
    start.hidden = false; start.textContent = 'Hablar con Vox'; stop.hidden = true;
  }
  function openDetails(...ids) { ids.forEach(id => { if (byId(id)) byId(id).open = true; }); }
  async function post(url, body) {
    const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(15000) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo completar el comando. Volvé a intentar.');
    return data;
  }
  function ask(needs, kind) {
    fields.hidden = false; previewBox.hidden = true;
    byId('vox-course-field').hidden = !needs.includes('course');
    byId('vox-student-field').hidden = !needs.includes('student');
    byId('vox-grade-field').hidden = !needs.includes('value') || kind !== 'grade';
    byId('vox-attendance-field').hidden = !needs.includes('value') || kind !== 'attendance';
    return 'Completá los datos indicados y pulsá Continuar. No hace falta repetir la frase.';
  }
  async function resume() {
    if (!pending) return '';
    const dateInput = byId('vox-date');
    dateInput.disabled = true;
    let result;
    try {
      result = await post(panel.dataset.previewUrl, { ...pending.values, text: pending.text,
        class_date: dateInput.value, course_id: panel.dataset.activeCourse || null });
    } finally { dateInput.disabled = false; }
    if (result.needs.length) return ask(result.needs, result.kind);
    preview = result.preview; pending = null; fields.hidden = true; previewBox.hidden = false;
    byId('vox-confirm-command').disabled = false;
    byId('vox-preview-description').textContent = `${preview.name} (ID: ${preview.student_id}) · ${preview.context} · ${preview.kind === 'grade' ? 'Nota: ' : 'Asistencia: '}${preview.value}. Todavía no se guardó.`;
    setState('recognized');
    return 'Revisá el estudiante y el dato. Solo se guardará si pulsás Confirmar.';
  }
  async function continueCommand(action) {
    if (busy) return;
    busy = true; start.disabled = true;
    byId('vox-date').disabled = true;
    try { status.textContent = await action(); }
    catch (error) { setState('uncertain'); status.textContent = error.message || 'No se pudo continuar. Volvé a intentar.'; }
    finally { busy = false; start.disabled = false; byId('vox-date').disabled = false; }
  }
  function cancelPending() { if (busy) return; clearPending(); setState('idle'); status.textContent = 'Comando cancelado. No se modificaron los registros.'; }

  window.VoxVoiceHooks = {
    readyMessage: 'Pulsá Hablar con Vox y pedime un recurso. Al hacer una pausa terminaré de escucharte.',
    recordingMessage: 'Te escucho… Hacé una pausa al terminar o pulsá Terminar de hablar.',
    onStart() { clearPending(); setState('preparing'); },
    onRecording() { setState('listening'); start.hidden = true; stop.hidden = false; },
    onProcessing() { setState('processing'); stop.hidden = true; start.hidden = false; start.textContent = 'Procesando…'; },
    onError() { clearPending(); idle(); setState('uncertain'); },
    onCancel() { clearPending(); setState('idle'); },
    onNoSpeech() { setState('idle'); return 'No detecté voz. Pulsá Hablar con Vox para volver a intentarlo.'; },
    onFinish: idle,
    async onText(text) {
      clearPending();
      const resourceId = window.VoxResourceCommands.match(text, resources);
      if (resourceId) {
        const title = resources.find(([id]) => id === resourceId)[1];
        byId('vox-resource-title').textContent = title;
        byId('vox-resource-image').src = catalog.dataset.root + resourceId + '.svg';
        byId('vox-resource-image').alt = 'Ilustración de ' + title;
        const message = resourceId === 'ciclo-del-agua' ? 'Abrí el ciclo del agua' : 'Abrí: ' + title;
        byId('vox-resource-message').textContent = message;
        if (!dialog.open) dialog.showModal();
        setState('recognized');
        return message;
      }
      const command = window.VoxResourceCommands.normalize(text);
      const courseQueries = {
        'mostrar mi curso': '', 'mostrar estudiantes': '#estudiantes',
        'mostrar estudiantes del curso': '#estudiantes', 'mostrar sesiones': '#historial',
        'mostrar sesiones de clase': '#historial',
      };
      if (Object.hasOwn(courseQueries, command)) {
        window.location.assign(panel.dataset.courseUrl + courseQueries[command]);
        return 'Abriendo tu curso anual activo.';
      }
      const menus = {
        'mostrar comentarios de boletin': ['tracking-menu', 'home-comments'],
      };
      if (menus[command]) { openDetails(...menus[command]); setState('recognized'); return 'Abrí la información que pediste.'; }
      if (['mostrar rendimiento', 'mostrar rendimiento del curso', 'mostrar cuadro de honor'].includes(command)) {
        window.location.assign(panel.dataset.performanceUrl + (command === 'mostrar cuadro de honor' ? '#cuadro-de-honor' : ''));
        return 'Abriendo el seguimiento del curso.';
      }
      if (['mostrar asistencia', 'mostrar calificaciones', 'mostrar notas'].includes(command)) {
        const section = command === 'mostrar asistencia' ? 'asistencia' : 'calificaciones';
        window.location.assign(panel.dataset.dailyUrl + '?fecha=' + encodeURIComponent(byId('vox-date').value) + '&seccion=' + section);
        return 'Abriendo el registro de la fecha para el curso activo.';
      }
      if (/^(marcar(?:\s|$)|registrar nota(?:\s|$))/.test(command)) {
        pending = { type: 'school', text, values: {} };
        return resume();
      }
      setState('uncertain');
      return 'No reconocí el comando. Pulsá Hablar con Vox y probá «mostrar ciclo del agua» o «registrar nota 85 al estudiante uno».';
    },
  };
  byId('vox-close-resource').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { setState('idle'); start.focus(); });
  byId('vox-complete-command').addEventListener('submit', event => {
    event.preventDefault();
    if (!pending) return;
    pending.values = { ...pending.values, student_id: byId('vox-student').value,
      value: byId('vox-grade-field').hidden ? byId('vox-attendance-value').value : byId('vox-grade-value').value };
    continueCommand(resume);
  });
  byId('vox-date').addEventListener('change', () => {
    if (preview) {
      pending = { type: 'school', text: preview.source_text, values: { student_id: preview.student_id, value: preview.value } };
      preview = null; previewBox.hidden = true;
      byId('vox-confirm-command').disabled = true;
    }
    if (pending) continueCommand(resume);
  });
  byId('vox-cancel-pending').addEventListener('click', cancelPending);
  byId('vox-cancel-confirmation').addEventListener('click', cancelPending);
  byId('vox-confirm-command').addEventListener('click', () => continueCommand(async () => {
    if (!preview) return 'No hay un cambio pendiente de confirmar.';
    const button = byId('vox-confirm-command'), cancel = byId('vox-cancel-confirmation');
    button.disabled = cancel.disabled = true;
    try {
      const result = await post(panel.dataset.confirmUrl, { token: preview.token });
      clearPending(); setState('recognized'); return result.message;
    } finally { button.disabled = cancel.disabled = false; }
  }));
})();
