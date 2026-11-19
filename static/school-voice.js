(() => {
  'use strict';
  const panel = document.querySelector('.voice-panel');
  const preview = document.getElementById('school-preview');
  const description = document.getElementById('preview-description');
  const status = document.getElementById('school-command-status');
  const confirm = document.getElementById('confirm-command');
  const cancel = document.getElementById('cancel-command');
  let pending = null;
  let saving = false;
  function clear() { pending = null; preview.hidden = true; }
  async function post(url, body) {
    const response = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(15000),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'El servidor no pudo procesar el comando.');
    return data;
  }
  window.VoxVoiceHooks = {
    onStart() { clear(); status.textContent = ''; },
    onError() { clear(); },
    async onText(text) {
      clear();
      if (!text.trim()) return 'No se reconoció texto. Volvé a grabar el comando.';
      const data = await post(panel.dataset.previewUrl, { text });
      pending = data;
      description.textContent = `${data.name} (ID: ${data.student_id}) — ${data.context || ''} — ${data.kind === 'grade' ? 'Nota: ' + data.value : 'Asistencia: ' + data.value}. Todavía no se guardó.`;
      preview.hidden = false;
      return 'Revisá la vista previa y pulsá Confirmar o Cancelar.';
    },
  };
  cancel.addEventListener('click', () => {
    if (saving) return;
    clear(); status.textContent = 'Comando cancelado. Se conservó el dato anterior.';
  });
  confirm.addEventListener('click', async () => {
    if (!pending || saving) return;
    saving = true; confirm.disabled = cancel.disabled = true;
    document.getElementById('record-start').disabled = true;
    try {
      const result = await post(panel.dataset.confirmUrl, { token: pending.token });
      if (result.kind === 'grade') {
        document.getElementById(`grade-${result.student_id}`).value = result.value;
      } else {
        const radio = document.querySelector(`input[name="status_${result.student_id}"][value="${result.value}"]`);
        if (radio) radio.checked = true;
      }
      clear(); status.textContent = result.message;
    } catch (error) {
      status.textContent = error.message || 'No se pudo confirmar. Volvé a intentar.';
    } finally {
      saving = false; confirm.disabled = cancel.disabled = false;
      document.getElementById('record-start').disabled = false;
    }
  });
})();
