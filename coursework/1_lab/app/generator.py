"""Однократная загрузка данных при запуске отдельного контейнера."""
import logging
import threading
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from .auth import ServiceTokenClient
from .config import DATA_REVISION, GeneratorSettings, ReportError, install_error_handlers
from .dataset import DemoParams, run_demo_generation

log = logging.getLogger('uvicorn.error')


def initialize(settings, stop):
    settings.validate_runtime()
    tokens = ServiceTokenClient('generator', settings.private_key_file, settings.token_url)
    headers = lambda audience, scope: {'Authorization': 'Bearer ' + tokens.get_token(audience, scope)}
    with httpx.Client(timeout=60) as http:
        for _ in range(120):
            if stop.is_set():
                return
            try:
                r = http.get(settings.gateway_internal_url + '/internal/dataset/state', headers=headers('gateway-internal', 'dataset:state:read'))
                r.raise_for_status()
                state = r.json()['state']
                break
            except (httpx.HTTPError, ReportError, ValueError, KeyError):
                stop.wait(1)
        else:
            log.error('Gateway недоступен; начальная загрузка не запущена')
            return
        if state and state['status'] == 'ready' and (state['details'] or {}).get('revision') == DATA_REVISION:
            log.info('Данные уже загружены; повторная генерация пропущена')
            return
        generation_id = 'init-' + uuid.uuid4().hex

        def publish(status):
            r = http.post(settings.gateway_internal_url + '/internal/dataset/state',
                          headers=headers('gateway-internal', 'dataset:state:update'),
                          json={'generation_id': generation_id, 'status': status, 'details': {'synthetic': True, 'revision': DATA_REVISION}})
            r.raise_for_status()

        try:
            publish('loading')
            run_demo_generation(settings, DemoParams())
            response = http.get(settings.report_internal_url + '/internal/reports/attendance',
                                headers=headers('report-service', 'lab1:verify'),
                                params={'term': 'целостность', 'date_from': '2026-09-07', 'date_to': '2026-12-27'})
            response.raise_for_status()
            if not response.json()['results']:
                raise RuntimeError('Пробный отчёт пуст')
            publish('ready')
            log.info('Начальные данные загружены и проверены')
        except Exception as exc:
            try:
                publish('failed')
            except Exception:
                pass
            log.exception('Начальная загрузка не завершена: %s', type(exc).__name__)


def create_app(settings=None):
    settings = settings or GeneratorSettings()
    settings.validate_runtime()

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()
        threading.Thread(target=initialize, args=(settings, stop), daemon=True).start()
        yield
        stop.set()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    install_error_handlers(app)

    @app.get('/health')
    def health():
        return {'status': 'up'}

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_app(), host='0.0.0.0', port=8002)
