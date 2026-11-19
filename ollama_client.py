"""Cliente JSON compartido: exclusivamente Ollama local, sin proxies."""
import json
import socket
from urllib import error, request as http
from urllib.parse import urlsplit


class OllamaError(ValueError):
    pass


def generate_json(config, *, system, prompt, schema, num_predict=2400):
    base_url = config['OLLAMA_URL'].rstrip('/')
    parsed = urlsplit(base_url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise OllamaError('Configurá Ollama con una dirección HTTP local.')
    payload = {
        'model': config['OLLAMA_MODEL'], 'stream': False, 'format': schema,
        'options': {'temperature': 0, 'num_predict': num_predict},
        'system': system, 'prompt': prompt,
    }
    query = http.Request(base_url + '/api/generate', data=json.dumps(payload).encode('utf-8'),
                         headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with http.build_opener(http.ProxyHandler({})).open(query, timeout=config['OLLAMA_TIMEOUT']) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise OllamaError('Ollama devolvió una salida demasiado grande. El borrador anterior se conserva.')
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or envelope.get('done') is not True:
            raise OllamaError('Ollama no completó una salida válida. El borrador anterior se conserva.')
        return json.loads(envelope['response'])
    except error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            raise OllamaError(f'El modelo {config["OLLAMA_MODEL"]} no está disponible. Descargalo con ollama pull {config["OLLAMA_MODEL"]}.') from exc
        raise OllamaError('Ollama devolvió un error. Revisá el servicio local; el borrador anterior se conserva.') from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OllamaError('Ollama tardó demasiado. Volvé a intentar; el borrador anterior se conserva.') from exc
    except error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise OllamaError('Ollama tardó demasiado. El borrador anterior se conserva.') from exc
        raise OllamaError('No se pudo conectar con Ollama local. Abrí Ollama o ejecutá ollama serve. El borrador anterior se conserva.') from exc
    except OSError as exc:
        raise OllamaError('Se interrumpió la conexión con Ollama local. Volvé a intentar; el borrador anterior se conserva.') from exc
    except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise OllamaError('Ollama devolvió una salida JSON inválida. El borrador anterior se conserva.') from exc
