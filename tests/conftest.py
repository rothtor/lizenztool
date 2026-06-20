import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from lizenztool.api import app


@pytest.fixture
def client():
    """FastAPI TestClient for integration tests."""
    return TestClient(app)


@pytest.fixture
def mock_config():
    """Mock app config with default values."""
    from lizenztool.config import AppConfig, StyleConfig, OutputConfig, IntegrationsConfig

    return AppConfig(
        style=StyleConfig(),
        output=OutputConfig(),
        integrations=IntegrationsConfig(
            flickr_api_key="test_flickr_key",
            dvids_api_key="test_dvids_key",
        ),
        presets={
            "standard": StyleConfig(bar_ratio=0.06, bar_opacity=0),
            "minimal": StyleConfig(bar_ratio=0.04, bar_opacity=150),
            "bold": StyleConfig(bar_ratio=0.06, bar_opacity=245),
        }
    )
