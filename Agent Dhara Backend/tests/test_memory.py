from __future__ import annotations
import os
import pytest
from unittest.mock import patch, MagicMock
from agent.memory import (
    _zep_enabled,
    get_zep_client,
    get_zep_checkpointer,
    remember_fact,
    recall_dataset_facts,
    add_run_episode,
    get_session_context_summary
)

def test_zep_disabled_by_default():
    # Make sure env vars are cleared
    with patch.dict(os.environ, {"ZEP_API_KEY": "", "DHARA_ZEP_ENABLED": ""}):
        assert not _zep_enabled()
        assert get_zep_client() is None
        assert get_zep_checkpointer() is None
        
        # Safe execution of no-ops
        remember_fact("sess", "fact", "entity")
        assert recall_dataset_facts("sess", "entity") == []
        add_run_episode("sess", "summary")
        assert get_session_context_summary("sess") == ""

@patch("agent.memory.get_zep_client")
def test_zep_remember_fact(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    with patch.dict(os.environ, {"ZEP_API_KEY": "testkey", "DHARA_ZEP_ENABLED": "1"}):
        remember_fact("test_session", "orders.amount must be positive", "orders")
        
        mock_client.memory.add.assert_called_once_with(
            session_id="test_session",
            messages=[{"role": "user", "content": "orders.amount must be positive",
                       "metadata": {"entity": "orders", "type": "business_rule"}}]
        )

@patch("agent.memory.get_zep_client")
def test_zep_recall_dataset_facts(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # Setup mock search results
    mock_msg1 = MagicMock()
    mock_msg1.message.content = "Fact 1"
    mock_msg2 = MagicMock()
    mock_msg2.message.content = "Fact 2"
    mock_client.memory.search.return_value = [mock_msg1, mock_msg2]
    
    with patch.dict(os.environ, {"ZEP_API_KEY": "testkey", "DHARA_ZEP_ENABLED": "1"}):
        facts = recall_dataset_facts("test_sess", "orders")
        assert facts == ["Fact 1", "Fact 2"]
        mock_client.memory.search.assert_called_once()
