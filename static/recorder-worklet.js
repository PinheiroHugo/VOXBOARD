// Captura mono local. La salida queda en silencio para evitar realimentación.
class PhraseRecorder extends AudioWorkletProcessor {
  constructor(options = {}) {
    super();
    this.recording = true;
    this.autoStop = Boolean(options.processorOptions?.autoStop);
    this.elapsed = 0;
    this.voiced = 0;
    this.silence = 0;
    this.hasSpeech = false;
    this.rate = globalThis.sampleRate || 48000;
    this.port.onmessage = ({ data }) => {
      if (data === 'stop') {
        this.recording = false;
        this.port.postMessage({ stopped: true });
      }
    };
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (this.recording && channel) {
      const samples = channel.slice();
      this.port.postMessage({ samples }, [samples.buffer]);
      if (this.autoStop) {
        const milliseconds = channel.length / this.rate * 1000;
        let energy = 0;
        for (const sample of channel) energy += sample * sample;
        const level = Math.sqrt(energy / channel.length);
        this.elapsed += milliseconds;
        if (!this.hasSpeech) {
          this.voiced = level >= 0.012 ? this.voiced + milliseconds : Math.max(0, this.voiced - milliseconds * 2);
          this.hasSpeech = this.voiced >= 140;
        } else {
          this.silence = level < 0.009 ? this.silence + milliseconds : 0;
        }
        if ((this.hasSpeech && this.silence >= 900) || (!this.hasSpeech && this.elapsed >= 6500)) {
          this.recording = false;
          this.port.postMessage({ autoStop: this.hasSpeech ? 'pause' : 'no-speech' });
        }
      }
    }
    return true;
  }
}
registerProcessor('phrase-recorder', PhraseRecorder);
