from __future__ import annotations
import os
import sqlite3
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from pydantic import BaseModel
from typing import Literal, Optional, List

from agent.chat_graph import (
    build_chat_graph,
    run_chat,
    UserIntent,
    get_semantic_match,
    _classify_intent_structured,
    map_intent_to_action
)

class TestAgenticChat(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        # Ignore errors if DB file is locked in Windows
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_sqlite_checkpointer_persistence(self):
        db_path = os.path.join(self.tmp_dir, "test_checkpointer.db")
        
        # Initialize checkpointer
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        checkpointer.setup()
        
        # Build graph
        graph = build_chat_graph(checkpointer=checkpointer)
        self.assertIsNotNone(graph)
        
        # Run once to set some state
        config = {"configurable": {"thread_id": "thread_123"}}
        state = {"session_id": "sess_123", "message": "hello"}
        
        # We should be able to invoke and save state
        res = graph.invoke(state, config)
        self.assertIsNotNone(res)
        
        # Get state from checkpointer
        saved_state = graph.get_state(config)
        self.assertEqual(saved_state.values.get("session_id"), "sess_123")
        
        conn.close()

    @patch("agent.chat_graph._get_embeddings")
    def test_semantic_routing(self, mock_get_emb):
        mock_emb = MagicMock()
        mock_get_emb.return_value = mock_emb
        
        # Mock embedding vectors: if all vectors are identical, the first key "view data" will be matched.
        mock_emb.embed_documents.return_value = [[1.0, 0.0]] * 18
        mock_emb.embed_query.return_value = [1.0, 0.0]
        
        match = get_semantic_match("preview table data")
        self.assertIsNotNone(match)
        # Since all reference vectors are mocked as identical, it matches the first phrase: "view data" -> "set_action"
        self.assertEqual(match[0], "set_action")
        
        # Fallback/no match
        mock_emb.embed_query.return_value = [0.0, 1.0]
        match = get_semantic_match("something completely random")
        self.assertIsNone(match)

    def test_map_intent_to_action(self):
        # Ambiguous intent
        intent = UserIntent(
            category="clean",
            target_table=None,
            confidence=0.8,
            clarification_needed=True,
            clarification_question="Which table do you want to clean?",
            suggested_options=["orders", "customers"]
        )
        ctx = {"last_table_list": ["orders", "customers"]}
        action, args = map_intent_to_action(intent, "clean", ctx)
        self.assertEqual(action, "convo_clarify")
        self.assertEqual(args["original_action"], "show_cleaning_recommendations")
        self.assertEqual(args["question"], "Which table do you want to clean?")
        
        # Unambiguous intent
        intent2 = UserIntent(
            category="profile",
            target_table="orders",
            confidence=1.0,
            clarification_needed=False,
            clarification_question=None,
            suggested_options=None
        )
        action2, args2 = map_intent_to_action(intent2, "profile orders", ctx)
        self.assertEqual(action2, "generate_report_selected")
        self.assertEqual(ctx["selected_table"], "orders")

    @patch("agent.chat_graph._classify_intent_structured")
    def test_run_chat_clarification_and_resume(self, mock_classify):
        db_path = os.path.join(self.tmp_dir, "checkpointer.db")
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        checkpointer.setup()
        
        # Setup mock LLM router response
        mock_intent = UserIntent(
            category="clean",
            target_table=None,
            confidence=0.9,
            clarification_needed=True,
            clarification_question="Which table to clean?",
            suggested_options=["orders"]
        )
        mock_classify.return_value = mock_intent
        
        # Mock load_session to keep context stable
        with patch("agent.chat_graph.load_session") as mock_load, \
             patch("agent.chat_graph.save_session") as mock_save:
            
            mock_sess = {"session_id": "sess_456", "context": {"last_table_list": ["orders"]}}
            mock_load.return_value = mock_sess
            
            # 1. Run first time: should interrupt and return convo_clarify card
            out = run_chat(
                session_id="sess_456",
                message="clean data",
                thread_id="thread_456",
                checkpointer=checkpointer
            )
            
            self.assertEqual(out["payload"]["step"], "convo_clarify")
            self.assertEqual(out["payload"]["status"], "paused")
            self.assertEqual(out["payload"]["clarification_card"]["question"], "Which table to clean?")
            self.assertEqual(out["payload"]["clarification_card"]["options"], ["orders"])
            
            # 2. Resume with target table
            with patch("agent.chat_graph._node_show_cleaning_recommendations") as mock_clean_node:
                mock_clean_node.return_value = {"reply": "Here are cleaning recs for orders", "payload": {"step": "clean_done"}}
                
                out_resume = run_chat(
                    session_id="sess_456",
                    message="orders",
                    thread_id="thread_456",
                    resume_value="orders",
                    checkpointer=checkpointer
                )
                
                self.assertEqual(out_resume["reply"], "Here are cleaning recs for orders")
                self.assertEqual(out_resume["payload"]["step"], "clean_done")
                
        conn.close()

if __name__ == "__main__":
    unittest.main()
