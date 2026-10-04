"""One disposable parser process per file; limits complement OS isolation."""
import json
import sys
from pathlib import Path

def main():
    payload = json.loads(sys.stdin.read())
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (110, 115))
        resource.setrlimit(resource.RLIMIT_AS, (3*1024**3, 3*1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64*1024**2, 64*1024**2))
    except ImportError:
        pass  # Windows: supervisor timeout still applies; deploy with a Job Object/container.
    # Defense in depth for Python libraries. Native decoders still require an OS
    # sandbox/network policy in deployments handling adversarial files.
    if not payload.get('config', {}).get('external_ai'):
        def offline(event, args):
            if event in ('socket.connect', 'socket.getaddrinfo'):
                raise PermissionError('Network disabled for local inspection')
        sys.addaudithook(offline)
    from evidex.inspection.pipeline import analyze
    from evidex.inspection.validation import InvalidFile
    from evidex.core.storage import atomic_json
    try:
        result = analyze(payload['path'], payload['name'], payload['output'], payload.get('config'))
    except InvalidFile as ex:
        result = {'verdict':'inconclusive', 'processing_status':'rejected', 'summary':str(ex)}
    except Exception as ex:
        result = {'verdict':'inconclusive', 'processing_status':'failed',
                  'summary':'El análisis no pudo completarse.', 'error_type':type(ex).__name__}
    atomic_json(Path(payload['output'])/'result.json', result)

if __name__ == '__main__':
    main()
