import pytest
from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig

def test_data_client_config_validation():
    """Test BitbankDataClientConfig validation."""
    # Missing optional keys but validation enforces them
    with pytest.raises(ValueError, match="requires both api_key and api_secret"):
        BitbankDataClientConfig()
        
    # Valid config
    config = BitbankDataClientConfig(
        api_key="key",
        api_secret="secret"
    )
    assert config.api_key == "key"

def test_exec_client_config_validation():
    """Test BitbankExecClientConfig validation."""
    with pytest.raises(ValueError, match="requires both api_key and api_secret"):
        BitbankExecClientConfig()
        
    # Valid config
    config = BitbankExecClientConfig(
        api_key="key",
        api_secret="secret",
        use_pubnub=False
    )
    assert config.api_key == "key"
    assert config.use_pubnub is False
