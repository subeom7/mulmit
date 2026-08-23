"""컨테이너가 실제로 보는 환경변수 — 게이트를 코드에 두고 compose에 안 넣으면 조용히 꺼진다.

`app/config.py`에 게이트를 선언하고 서버 `.env`를 채워도, `docker-compose.yml`이
그 이름을 컨테이너로 넘겨주지 않으면 프로세스는 값을 못 본다. 실패가 아니라
**기본값(꺼짐)으로 동작**하기 때문에 배포는 성공한 것처럼 보이고 화면에서는
섹션이 그냥 없다. 배포 로그에도, 테스트에도 아무 흔적이 없다.

여기서 두 가지를 나눠 본다. 게이트는 **web도** 봐야 한다 — 서빙 판정을 web이
하므로 게이트가 ingest에만 있으면 수집은 되는데 화면에서 사라진다. 반대로 키는
**ingest에만** 있으면 된다: 저장분을 내보내는 데 키가 필요 없으니, 굳이 web
컨테이너까지 비밀을 퍼뜨릴 이유가 없다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
CONFIG = (ROOT / "app" / "config.py").read_text(encoding="utf-8")

GATES = sorted(set(re.findall(r"^([A-Z0-9_]+_ENABLED)\s*=\s*_bool\(", CONFIG, re.M)))
KEYS = sorted(set(re.findall(r"^([A-Z0-9_]*API_KEY)\s*=\s*os\.environ", CONFIG, re.M)))


def _env(service: str) -> dict:
    # PyYAML이 `<<: *app-env` 병합을 풀어 주므로 서비스가 실제로 받는 표가 나온다.
    return COMPOSE["services"][service].get("environment") or {}


def test_the_lists_are_not_empty():
    """정규식이 헛돌면 아래 테스트들이 통과가 아니라 무의미해진다."""
    assert len(GATES) >= 25, GATES
    assert len(KEYS) >= 10, KEYS


@pytest.mark.parametrize("gate", GATES)
def test_every_gate_reaches_both_containers(gate: str):
    for service in ("web", "ingest"):
        assert gate in _env(service), (
            f"{gate}이 config.py에 있는데 compose의 {service}로 안 넘어간다. "
            "서버 .env를 채워도 컨테이너는 기본값(꺼짐)을 본다."
        )


@pytest.mark.parametrize("key", KEYS)
def test_every_api_key_reaches_the_collector(key: str):
    assert key in _env("ingest"), f"{key}가 ingest로 안 넘어가면 그 lane은 수집을 못 한다"


def test_the_youtube_key_stays_out_of_the_web_container():
    """저장된 목록을 내보내는 데 키는 필요 없다 — 없는 곳에는 두지 않는다."""
    assert "YOUTUBE_API_KEY" not in _env("web")
    assert "YOUTUBE_ENABLED" in _env("web")


def test_this_guard_can_actually_fail():
    """빠뜨린 이름을 정말로 잡는지."""
    assert "NOT_A_REAL_GATE_ENABLED" not in _env("web")
