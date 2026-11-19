(() => {
  'use strict';
  const mode = document.getElementById('voice-mode');
  const summary = document.getElementById('session-summary');
  const status = document.getElementById('summary-status');
  let timer, queue = Promise.resolve();
  let saved = summary.value;
  let recordingMode;

  function save() {
    clearTimeout(timer);
    const value = summary.value;
    status.textContent = 'Guardando resumen…';
    const task = queue.catch(() => {}).then(async () => {
      const response = await fetch(summary.dataset.saveUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ summary: value }), signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo guardar el resumen.');
      saved = value;
      if (summary.value === value) status.textContent = 'Resumen guardado.';
    });
    queue = task;
    task.catch(() => { status.textContent = 'No se pudo guardar el resumen. Conservá esta página y pulsá Guardar resumen para reintentar.'; });
    return task;
  }
  summary.addEventListener('input', () => {
    status.textContent = 'Cambios pendientes de guardar…';
    clearTimeout(timer); timer = setTimeout(() => save().catch(() => {}), 600);
  });
  document.getElementById('save-summary').addEventListener('click', () => save().catch(() => {}));
  window.addEventListener('beforeunload', event => {
    if (summary.value !== saved) { event.preventDefault(); event.returnValue = ''; }
  });
  window.VoxVoiceHooks = {
    onStart() { recordingMode = mode.value; mode.disabled = true; },
    onFinish() { mode.disabled = false; },
    async onText(text) {
      if (recordingMode !== 'dictation') {
        const result = window.VoxBoard.executeCommand(text);
        return text.trim() ? result.message : `No se reconoció texto. ${result.message}`;
      }
      if (!text.trim()) return 'No se reconoció texto. El resumen no cambió.';
      const updated = summary.value + (summary.value ? '\n' : '') + text;
      if (updated.length > 20000) throw new Error('El resumen supera 20000 caracteres. Reducilo antes de volver a dictar.');
      summary.value = updated;
      await save();
      return 'Frase añadida al resumen y guardada.';
    },
  };
})();
