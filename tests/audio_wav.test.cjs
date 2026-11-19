const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('la captura del navegador produce WAV mono PCM de 16 bits y 16 kHz', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../static/audio-wav.js'), 'utf8');
  const context = { window: {}, Blob };
  vm.runInNewContext(source, context);
  const { encodeWav } = context.window.VoxAudio;
  for (const rate of [16000, 44100, 48000]) {
    const chunk = new Float32Array(rate / 2).fill(0.5);
    const blob = encodeWav([chunk, chunk], rate);
    const view = new DataView(await blob.arrayBuffer());
    assert.equal(blob.type, 'audio/wav');
    assert.equal(blob.size, 32044);
    assert.equal(view.getUint16(20, true), 1); // PCM
    assert.equal(view.getUint16(22, true), 1); // mono
    assert.equal(view.getUint32(24, true), 16000);
    assert.equal(view.getUint16(34, true), 16);
    assert.equal(view.getUint32(40, true), 32000);
    assert.equal(view.getInt16(44, true), 16384);
  }
  const clipped = encodeWav([new Float32Array([2, -2])], 16000);
  const view = new DataView(await clipped.arrayBuffer());
  assert.equal(view.getInt16(44, true), 32767);
  assert.equal(view.getInt16(46, true), -32768);
});

test('el worklet envía muestras y confirma la detención sin seguir grabando', () => {
  let Recorder;
  const messages = [];
  class Processor { constructor() { this.port = { postMessage: data => messages.push(data) }; } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/recorder-worklet.js'), 'utf8'), {
    AudioWorkletProcessor: Processor,
    registerProcessor: (name, type) => { assert.equal(name, 'phrase-recorder'); Recorder = type; },
  });
  const recorder = new Recorder();
  const input = new Float32Array([0.1, 0.2]);
  recorder.process([[input]]);
  assert.equal(messages.length, 1);
  assert.notEqual(messages[0].samples, input);
  recorder.port.onmessage({ data: 'stop' });
  assert.equal(messages[1].stopped, true);
  recorder.process([[input]]);
  assert.equal(messages.length, 2);
});

test('la interfaz informa permiso denegado y libera el micrófono antes de transcribir', async () => {
  for (const denied of [true, false]) {
    const elements = Object.fromEntries(['record-start', 'record-stop', 'voice-status', 'voice-text']
      .map(id => [id, { disabled: false, handlers: {}, addEventListener(event, callback) { this.handlers[event] = callback; } }]));
    const panel = { dataset: { statusUrl: '/estado', transcribeUrl: '/transcribir', workletUrl: '/worklet' } };
    let stopped = false;
    let uploads = 0;
    let microphoneRequested = false;
    let audioResumed = false;
    const avatarStates = [];
    class Context {
      constructor() { this.state = 'running'; this.sampleRate = 48000; this.audioWorklet = { addModule: async () => {} }; }
      async resume() { audioResumed = true; }
      async close() { this.state = 'closed'; }
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    }
    class Recorder {
      constructor() {
        this.port = { postMessage: () => this.port.onmessage({ data: { stopped: true } }) };
      }
      connect() { this.port.onmessage({ data: { samples: new Float32Array(480) } }); }
      disconnect() {}
    }
    const browser = {
      document: { querySelector: () => panel, getElementById: id => elements[id] },
      navigator: { mediaDevices: { getUserMedia: async () => {
        microphoneRequested = true;
        assert.equal(audioResumed, true);
        if (denied) { const error = new Error(); error.name = 'NotAllowedError'; throw error; }
        return { getTracks: () => [{ stop: () => { stopped = true; } }] };
      } } },
      AudioContext: Context, AudioWorkletNode: Recorder,
      window: {
        AudioWorkletNode: Recorder, VoxAudio: { encodeWav: () => new Blob() }, addEventListener() {},
        VoxBoard: {
          setAvatarState: state => avatarStates.push(state),
          executeCommand: transcript => {
            assert.equal(transcript, 'hola clase');
            avatarStates.push('idle');
            return { recognized: false, message: 'Comando no reconocido. Probá decir «mostrar ciclo del agua».' };
          },
        },
      },
      setTimeout, clearTimeout,
      AbortSignal,
      encodeWav: () => new Blob(),
      fetch: async url => {
        if (url === '/estado') return { ok: true, json: async () => ({ available: true }) };
        assert.equal(stopped, true);
        uploads++;
        return { ok: true, json: async () => ({ text: 'hola clase', message: '' }) };
      },
    };
    const script = fs.readFileSync(path.join(__dirname, '../static/voice.js'), 'utf8');
    vm.runInNewContext(script, browser);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(microphoneRequested, false);
    const starting = elements['record-start'].handlers.click();
    // El micrófono se solicita durante el clic, sin esperar al servidor.
    assert.equal(microphoneRequested, true);
    await starting;
    if (denied) {
      assert.match(elements['voice-status'].textContent, /no tiene permiso/);
      assert.equal(elements['record-start'].disabled, false);
      assert.equal(uploads, 0);
      assert.equal(avatarStates.at(-1), 'idle');
    } else {
      assert.equal(elements['record-stop'].disabled, false);
      assert.equal(avatarStates.at(-1), 'listening');
      await elements['record-stop'].handlers.click();
      assert.equal(uploads, 1);
      assert.equal(elements['voice-text'].textContent, 'hola clase');
      assert.match(elements['voice-status'].textContent, /mostrar ciclo del agua/);
      assert.equal(avatarStates.at(-1), 'idle');
      assert.equal(elements['record-start'].disabled, false);
      assert.equal(elements['record-stop'].disabled, true);
    }
  }
});
