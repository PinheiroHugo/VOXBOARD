(() => {
'use strict';
const { encodeWav } = window.VoxAudio;

const panel = document.querySelector('.voice-panel');
const start = document.getElementById('record-start');
const stop = document.getElementById('record-stop');
const cancel = document.getElementById('record-cancel');
const status = document.getElementById('voice-status');
const text = document.getElementById('voice-text');
let stream, context, source, recorder, timer, chunks, finish;
let state = 'idle';
let leaving = false;
let captureId = 0;
let stopReason = 'manual';
let cancelPreparation;
const hooks = window.VoxVoiceHooks || {};
const setAvatar = value => window.VoxBoard?.setAvatarState(value);

function withTimeout(promise, milliseconds, message) {
  let timeout;
  return Promise.race([
    promise,
    new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error(message)), milliseconds); }),
  ]).finally(() => clearTimeout(timeout));
}

async function release() {
  clearTimeout(timer);
  stream?.getTracks().forEach(track => track.stop());
  source?.disconnect(); recorder?.disconnect();
  if (context && context.state !== 'closed') await context.close();
  stream = context = source = recorder = null;
}

async function checkModel() {
  const response = await fetch(panel.dataset.statusUrl, { signal: AbortSignal.timeout(10000), cache: 'no-store' });
  if (!response.ok) throw new Error('No se pudo consultar el servidor de VOXBOARD. Comprobá la conexión y que el servidor esté funcionando.');
  const data = await response.json();
  if (!data.available) throw new Error(data.message);
}

function showError(error) {
  setAvatar('idle');
  hooks.onError?.();
  const messages = {
    NotAllowedError: 'El navegador no tiene permiso de micrófono. Permití el acceso desde el icono junto a la dirección y volvé a intentar.',
    NotFoundError: 'No se encontró un micrófono. Conectá uno y volvé a intentar.',
    NotReadableError: 'No se puede usar el micrófono. Revisá si otra aplicación lo está utilizando.',
    TimeoutError: 'El servidor de VOXBOARD no respondió. Revisá la conexión y volvé a intentar.',
  };
  status.textContent = messages[error.name] || error.message || 'No se pudo grabar la frase.';
}

start.addEventListener('click', async () => {
  if (state !== 'idle') return;
  state = 'starting'; start.disabled = true;
  const generation = ++captureId;
  stopReason = 'manual';
  if (cancel) { cancel.hidden = false; cancel.disabled = false; }
  setAvatar('idle');
  hooks.onStart?.();
  status.textContent = 'Preparando el micrófono…';
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      throw new Error('Esta vista no permite grabar. Abrí VOXBOARD directamente en Chrome o Edge mediante HTTPS (o localhost en el equipo servidor), sin incrustarlo dentro de otra página.');
    }
    // Activar audio dentro del clic, antes de cualquier espera de red.
    // Algunos navegadores suspenden AudioContext si se crea después de un fetch.
    context = new AudioContext();
    context.resume().catch(() => {});
    status.textContent = 'Esperando permiso de micrófono. Revisá el aviso del navegador junto a la dirección.';
    let acceptingStream = true;
    const microphone = navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false })
      .then(value => {
        if (!acceptingStream || leaving || generation !== captureId) {
          value.getTracks().forEach(track => track.stop());
          throw new Error('Se canceló la solicitud del micrófono. Volvé a intentar.');
        }
        return value;
      });
    const canceled = new Promise((_, reject) => {
      cancelPreparation = () => reject(new Error('Captura cancelada.'));
    });
    try {
      stream = await withTimeout(Promise.race([microphone, canceled]), 30000, 'No se recibió permiso del micrófono. Permití el acceso desde el icono junto a la dirección y volvé a intentar.');
    } finally {
      acceptingStream = false;
      if (generation === captureId) cancelPreparation = null;
    }
    if (leaving) { await release(); return; }
    status.textContent = 'Preparando la grabación local…';
    await withTimeout(context.resume(), 5000, 'El navegador mantiene el audio suspendido. Abrí la aplicación directamente en Chrome o Edge y volvé a intentar.');
    if (generation !== captureId) return;
    await checkModel();
    if (generation !== captureId) return;
    await withTimeout(context.audioWorklet.addModule(panel.dataset.workletUrl), 10000, 'No se pudo cargar el grabador. Recargá la página con Ctrl+F5.');
    if (generation !== captureId) return;
    chunks = [];
    recorder = new AudioWorkletNode(context, 'phrase-recorder', {
      processorOptions: { autoStop: panel.dataset.autoStop === 'true' },
    });
    recorder.port.onmessage = ({ data }) => {
      if (data.samples) chunks.push(data.samples);
      if (data.stopped) finish?.();
      if (data.autoStop && state === 'recording') {
        stopReason = data.autoStop;
        stop.click();
      }
    };
    source = context.createMediaStreamSource(stream);
    source.connect(recorder); recorder.connect(context.destination);
    state = 'recording'; stop.disabled = false;
    hooks.onRecording?.();
    setAvatar('listening');
    status.textContent = hooks.recordingMessage || 'Grabando… Hablá y pulsá Detener y transcribir.';
    timer = setTimeout(() => stop.click(), 30000);
  } catch (error) {
    if (generation !== captureId) return;
    if (cancel) cancel.hidden = true;
    await release(); state = 'idle'; start.disabled = false; showError(error); hooks.onFinish?.();
  }
});

stop.addEventListener('click', async () => {
  if (state !== 'recording') return;
  state = 'processing'; stop.disabled = true; clearTimeout(timer);
  if (cancel) { cancel.hidden = true; cancel.disabled = true; }
  hooks.onProcessing?.();
  setAvatar('idle');
  status.textContent = 'Transcribiendo en el servidor de VOXBOARD… La primera vez puede tardar unos segundos.';
  try {
    const stopped = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('No se pudo detener la captura. Volvé a grabar.')), 2000);
      finish = () => { clearTimeout(timeout); resolve(); };
    });
    recorder.port.postMessage('stop');
    await stopped;
    const audio = encodeWav(chunks, context.sampleRate);
    await release(); chunks = [];
    if (stopReason === 'no-speech') {
      text.textContent = 'No se detectó voz.';
      status.textContent = hooks.onNoSpeech?.() || 'No se detectó voz. Pulsá el botón para volver a intentarlo.';
      return;
    }
    const response = await fetch(panel.dataset.transcribeUrl, {
      method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: audio,
      signal: AbortSignal.timeout(120000),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo transcribir la frase.');
    text.textContent = data.text || 'Sin texto reconocido.';
    if (hooks.onText) {
      status.textContent = await hooks.onText(data.text || '') || data.message || 'Transcripción completada.';
    } else {
      const result = window.VoxBoard.executeCommand(data.text || '');
      status.textContent = data.text ? result.message : `${data.message || 'No se reconoció texto.'} ${result.message}`;
    }
  } catch (error) {
    await release();
    showError(error instanceof TypeError ? new Error('No se pudo conectar con VOXBOARD. Revisá la conexión y el servidor y volvé a intentar.') : error);
  } finally {
    state = 'idle'; start.disabled = false; finish = null;
    hooks.onFinish?.();
  }
});

cancel?.addEventListener('click', async () => {
  if (!['starting', 'recording'].includes(state)) return;
  ++captureId;
  cancelPreparation?.(); cancelPreparation = null;
  state = 'canceling';
  start.disabled = true; stop.disabled = true; cancel.disabled = true;
  await release(); chunks = [];
  state = 'idle'; start.disabled = false; cancel.hidden = true;
  setAvatar('idle'); hooks.onCancel?.(); hooks.onFinish?.();
  status.textContent = 'Grabación cancelada. Pulsá el botón para volver a intentarlo.';
});

window.addEventListener('pagehide', () => { ++captureId; cancelPreparation?.(); cancelPreparation = null; leaving = true; setAvatar('idle'); release(); });
start.disabled = false;
checkModel().then(() => {
  if (state === 'idle') status.textContent = hooks.readyMessage || 'Listo. Pulsá Grabar frase y permití el acceso al micrófono.';
}).catch(error => { if (state === 'idle') showError(error); });
})();
