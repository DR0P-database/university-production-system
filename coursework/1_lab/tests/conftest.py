import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.setup import generate_secrets
from app.config import GatewaySettings


@pytest.fixture(scope='session')
def keys(tmp_path_factory):
    path = tmp_path_factory.mktemp('keys')
    generate_secrets(path, key_size=2048)
    return path


@pytest.fixture
def settings(keys, tmp_path):
    return GatewaySettings(
        user_public_key_file=keys/'user_public.pem',
        service_issuer_public_key_file=keys/'service_issuer_public.pem',
        user_issuer_private_key_file=keys/'user_private.pem',
        service_issuer_private_key_file=keys/'service_issuer_private.pem',
        clients_file=keys/'clients.json', users_file=keys/'users.json',
        replay_db_file=tmp_path/'state.sqlite',
        service_client_private_key_file=keys/'gateway_client_private.pem')


@pytest.fixture
def passwords(keys):
    return {line.split(':',1)[0]:line.split(':',1)[1].strip().split()[0]
            for line in (keys/'demo-credentials.txt').read_text().splitlines()
            if line and not line.startswith('#') and ':' in line}
