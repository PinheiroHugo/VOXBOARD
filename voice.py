"""Transcripción local de frases WAV PCM mono, 16 bits y 16 kHz."""
import importlib.util
import io
import json
from pathlib import Path
from threading import Lock
import wave

from flask import Blueprint, jsonify, request

MAX_AUDIO_BYTES = 1_000_000
MAX_FRAMES = 30 * 16000


def read_audio(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(),
                    audio.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('Usá audio WAV PCM mono de 16 bits y 16 kHz.')
            frames = audio.getnframes()
            if not 0 < frames <= MAX_FRAMES:
                raise ValueError('Grabá una frase de hasta 30 segundos.')
            pcm = audio.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError('El audio está incompleto. Volvé a grabar la frase.')
            return pcm
    except (wave.Error, EOFError) as error:
        raise ValueError('El archivo no es un audio WAV válido. Volvé a grabar.') from error


def create_voice_blueprint(model_path):
    blueprint = Blueprint('voice', __name__)
    model_path = Path(model_path)
    model = None
    model_lock = Lock()

    def unavailable():
        if not model_path.is_dir():
            return 'Falta el modelo de voz. Colocá vosk-model-small-es-0.42 dentro de la carpeta models y volvé a intentar.'
        if importlib.util.find_spec('vosk') is None:
            return 'Falta instalar Vosk en el entorno de Python. Instalá requirements.txt y reiniciá la aplicación.'
        return None

    @blueprint.get('/api/voz/estado')
    def status():
        error = unavailable()
        return jsonify(available=error is None, message=error or 'Micrófono listo para grabar una frase.')

    @blueprint.post('/api/voz/transcribir')
    def transcribe():
        nonlocal model
        error = unavailable()
        if error:
            return jsonify(error=error), 503
        if request.content_length and request.content_length > MAX_AUDIO_BYTES:
            return jsonify(error='El audio es demasiado largo. Grabá hasta 30 segundos.'), 413
        data = request.stream.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            return jsonify(error='El audio es demasiado largo. Grabá hasta 30 segundos.'), 413
        try:
            pcm = read_audio(data)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        try:
            from vosk import KaldiRecognizer, Model
            with model_lock:
                if model is None:
                    # Ruta explícita: nunca se buscan ni descargan modelos en internet.
                    model = Model(str(model_path))
        except Exception:
            return jsonify(error='No se pudo cargar Vosk o el modelo local. Revisá la instalación y que la carpeta del modelo esté completa.'), 503
        try:
            recognizer = KaldiRecognizer(model, 16000)
            parts = []
            for offset in range(0, len(pcm), 8000):
                if recognizer.AcceptWaveform(pcm[offset:offset + 8000]):
                    parts.append(json.loads(recognizer.Result()).get('text', ''))
            parts.append(json.loads(recognizer.FinalResult()).get('text', ''))
            text = ' '.join(part.strip() for part in parts if part.strip())
        except Exception:
            return jsonify(error='No se pudo transcribir el audio. Volvé a grabar la frase.'), 500
        return jsonify(text=text, message='' if text else 'No se reconoció texto. Hablá cerca del micrófono y volvé a intentar.')

    return blueprint
