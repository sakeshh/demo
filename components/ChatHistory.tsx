'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { FaRegClock, FaSyncAlt } from 'react-icons/fa';

type SessionSummary = {
  session_id: string;
  updated_at?: number;
  created_at?: number;
  title?: string | null;
  preview?: string | null;
};

function formatDateTime(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  try {
    return d.toLocaleString();
  } catch {
    return d.toISOString();
  }
}

export default function ChatHistory({ expanded = true }: { expanded?: boolean }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/sessions?limit=50');
      const data = await res.json();
      setSessions(Array.isArray(data?.sessions) ? data.sessions : []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const saved = window.localStorage.getItem('dharaSessionId') || 'default';
    setActive(saved);
    if (expanded) refresh();
    const onChange = () => {
      const sid = window.localStorage.getItem('dharaSessionId') || 'default';
      setActive(sid);
    };
    window.addEventListener('dhara-session-change', onChange as EventListener);
    return () => window.removeEventListener('dhara-session-change', onChange as EventListener);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onFocus = () => {
      searchRef.current?.focus();
    };
    window.addEventListener('dhara-focus-chat-search', onFocus as EventListener);
    return () => window.removeEventListener('dhara-focus-chat-search', onFocus as EventListener);
  }, []);

  useEffect(() => {
    if (!expanded) return;
    // focus search when panel opens
    searchRef.current?.focus();
  }, [expanded]);

  const items = useMemo(() => {
    // Always include "default" at top if not present
    const hasDefault = sessions.some((s) => s.session_id === 'default');
    const base = hasDefault
      ? sessions
      : [{ session_id: 'default', title: 'Default', preview: 'Current chat' } as SessionSummary, ...sessions];
    const q = query.trim().toLowerCase();
    if (!q) return base;
    return base.filter((s) => {
      const title = (s.title || s.session_id || '').toLowerCase();
      const preview = (s.preview || '').toLowerCase();
      return title.includes(q) || preview.includes(q);
    });
  }, [sessions, query]);

  const selectSession = (sid: string) => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('dharaSessionId', sid);
    window.dispatchEvent(new Event('dhara-session-change'));
    setActive(sid);
  };

  if (!expanded) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-black/55">Previous chats</h3>
        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={refresh}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-black/10 bg-white/85 px-2 py-1 text-[11px] text-black/70 hover:bg-white disabled:opacity-40"
        >
          <FaSyncAlt className={loading ? 'animate-spin' : ''} />
          Refresh
        </motion.button>
      </div>

      <div className="flex items-center gap-2">
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search chats…"
          className="w-full rounded-xl border border-black/10 bg-white/85 px-3 py-2 text-sm text-zinc-900 outline-none placeholder-black/40 transition-all focus:border-[#0070AD]/40 focus:ring-2 focus:ring-[#0070AD]/20 disabled:opacity-50"
        />
      </div>

      <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
        {items.map((s) => {
          const isActive = active === s.session_id;
          const title = s.title?.trim() || s.session_id;
          const preview = s.preview?.trim();
          return (
            <motion.button
              key={s.session_id}
              whileHover={{ x: 3 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => selectSession(s.session_id)}
              className={`w-full rounded-xl border p-3 text-left transition-colors ${
                isActive
                  ? 'border-[#0070AD]/35 bg-[#0070AD]/10'
                  : 'border-black/10 bg-white/85 hover:border-black/20 hover:bg-white'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-zinc-900">{title}</div>
                  {preview && <div className="mt-1 line-clamp-2 text-xs text-black/60">{preview}</div>}
                </div>
                <div className="flex shrink-0 items-center gap-1 text-[11px] text-black/45">
                  <FaRegClock />
                  {formatDateTime(s.updated_at || s.created_at)}
                </div>
              </div>
            </motion.button>
          );
        })}
        {!items.length && (
          <div className="rounded-xl border border-black/10 bg-white/85 p-3 text-xs text-black/60">
            No saved chats yet.
          </div>
        )}
      </div>
    </div>
  );
}

