'use client';

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { FaBars, FaDatabase, FaEdit, FaSearch, FaTimes } from 'react-icons/fa';
import SogetiLogo from '@/components/SogetiLogo';
import DataAssessment from './DataAssessment';
import DataQuality from './DataQuality';
import DataOrchestration from './DataOrchestration';
import Monitoring from './Monitoring';
import ChatHistory from './ChatHistory';

export default function Sidebar({ gxEnabled = false }: { gxEnabled?: boolean }) {
  const router = useRouter();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);
  const [showChatSearch, setShowChatSearch] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const raw = window.localStorage.getItem('dharaSidebarCollapsed');
    if (raw == null) return;
    setIsCollapsed(raw === 'true');
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia('(min-width: 1024px)'); // Tailwind lg
    const apply = () => setIsDesktop(!!mql.matches);
    apply();
    if (typeof mql.addEventListener === 'function') mql.addEventListener('change', apply);
    else mql.addListener(apply);
    return () => {
      if (typeof mql.removeEventListener === 'function') mql.removeEventListener('change', apply);
      else mql.removeListener(apply);
    };
  }, []);

  const toggleCollapsed = () => {
    setIsCollapsed((v) => {
      const next = !v;
      if (typeof window !== 'undefined') window.localStorage.setItem('dharaSidebarCollapsed', String(next));
      return next;
    });
  };

  return (
    <>
      {/* Mobile Toggle Button */}
      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={toggleCollapsed}
        className={`fixed top-4 left-4 z-50 rounded-lg border p-3 shadow-lg backdrop-blur lg:hidden transition-all duration-500 ${
          gxEnabled ? 'border-white/10 bg-[#001D2E]/80 text-white' : 'border-black/10 bg-white/80 text-black/80'
        }`}
      >
        {isCollapsed ? <FaBars /> : <FaTimes />}
      </motion.button>

      {/* Sidebar */}
      <motion.aside
        initial={false}
        animate={{
          // Desktop: keep a visible icon rail; Mobile: slide away.
          x: isDesktop ? 0 : isCollapsed ? -320 : 0,
          width: isCollapsed ? 72 : 320,
        }}
        transition={{ type: 'spring', stiffness: 280, damping: 26 }}
        className={`fixed inset-y-0 left-0 z-40 overflow-y-auto border-r transition-all duration-700 backdrop-blur-xl lg:static lg:h-full lg:min-h-0 lg:max-h-none lg:self-stretch lg:shrink-0 ${
          gxEnabled ? 'border-white/10 bg-[#001D2E]/95' : 'border-black/10 bg-white/75'
        }`}
      >
        {/* Desktop collapse rail button (ChatGPT-style) */}
        <div className="hidden lg:flex items-center justify-between px-4 py-3">
          <motion.button
            whileHover={{ scale: 1.04 }}
            whileTap={{ scale: 0.96 }}
            onClick={toggleCollapsed}
            className={`relative inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold transition-all ${
              gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-emerald-500/10' : 'border-black/10 bg-white/85 text-black/70 hover:bg-white'
            }`}
            title={isCollapsed ? 'Open sidebar' : 'Collapse sidebar'}
            aria-label={isCollapsed ? 'Open sidebar' : 'Collapse sidebar'}
          >
            <FaBars className={gxEnabled ? 'text-emerald-400' : 'text-[14px]'} />
            {!isCollapsed && <span>Collapse</span>}
          </motion.button>
        </div>

        {/* Collapsed rail (desktop-like): expand only */}
        {isCollapsed ? (
          <div className="px-3 pb-6" />
        ) : (
          <div className="space-y-8 p-6">
          {/* Header + Sogeti */}
          <motion.div
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.05 }}
          >
            <div className="-ml-7 opacity-95">
              <SogetiLogo className="h-9 w-32" />
            </div>
            <div className="mt-2 pl-10">
              <h2 className={`text-xl font-extrabold tracking-tight [font-family:Helvetica,Arial,sans-serif] ${gxEnabled ? 'text-white' : 'text-zinc-900'}`}>
                AGENT{' '}
                <span className={gxEnabled ? 'text-emerald-400' : 'bg-gradient-to-r from-zinc-900 via-zinc-900 to-zinc-900/60 bg-clip-text text-transparent'}>
                  DHARA
                </span>
              </h2>
              <p className={`mt-1 text-xs ${gxEnabled ? 'text-white/40' : 'text-black/50'}`}>Developed by Sogeti</p>
            </div>
          </motion.div>

          <div className="border-t border-black/10" />

          {/* Chat controls (New / Search) */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.075 }}
            className="space-y-2"
          >
            <motion.button
              whileHover={{ x: 4 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => {
                if (typeof window === 'undefined') return;
                const id = (crypto?.randomUUID ? crypto.randomUUID() : String(Date.now()));
                window.localStorage.setItem('dharaSessionId', id);
                window.localStorage.removeItem('agentThreadId');
                window.localStorage.removeItem('dharaSelectedDataSource');
                window.dispatchEvent(new Event('dhara-session-change'));
                router.push('/chat');
              }}
              className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all ${
                gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-[#002B45]' : 'border-black/10 bg-white/85 text-zinc-900 hover:bg-white'
              }`}
              title="New chat"
              aria-label="New chat"
            >
              <FaEdit className={gxEnabled ? 'text-emerald-400' : 'text-black/60'} />
              <span className="truncate">New chat</span>
            </motion.button>
            <motion.button
              whileHover={{ x: 4 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => {
                if (typeof window === 'undefined') return;
                setShowChatSearch((v) => {
                  const next = !v;
                  // focus the input after it renders
                  if (next) setTimeout(() => window.dispatchEvent(new Event('dhara-focus-chat-search')), 0);
                  return next;
                });
              }}
              className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all ${
                gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-[#002B45]' : 'border-black/10 bg-white/85 text-zinc-900 hover:bg-white'
              }`}
              title="Search chats"
              aria-label="Search chats"
            >
              <FaSearch className={gxEnabled ? 'text-emerald-400' : 'text-black/60'} />
              <span className="truncate">Search chats</span>
            </motion.button>

            <AnimatePresence>
              {showChatSearch && (
                <motion.div
                  initial={{ opacity: 0, height: 0, y: -6 }}
                  animate={{ opacity: 1, height: 'auto', y: 0 }}
                  exit={{ opacity: 0, height: 0, y: -6 }}
                  transition={{ duration: 0.18 }}
                  className="overflow-hidden rounded-xl border border-black/10 bg-white/70 p-3"
                >
                  <ChatHistory expanded />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>

          <div className="border-t border-black/10" />

          {/* Data Pipeline Workflow */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="space-y-3"
          >
            <h3 className={`text-xs font-semibold uppercase tracking-wide ${gxEnabled ? 'text-emerald-400' : 'text-black/55'}`}>
              Quick Actions
            </h3>
            <motion.button
              onClick={() => router.push('/data-pipeline')}
              whileHover={{ scale: 1.02, x: 4 }}
              whileTap={{ scale: 0.98 }}
              className={`group relative flex w-full items-center gap-3 rounded-xl border p-4 text-left transition-all ${
                gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-[#002B45]' : 'border-black/10 bg-white/80 text-zinc-900 hover:border-[#0070AD]/30 hover:bg-white'
              }`}
            >
              <span className={`absolute bottom-0 left-4 right-4 h-0.5 origin-left scale-x-0 rounded-full transition-transform duration-300 group-hover:scale-x-100 ${gxEnabled ? 'bg-emerald-500' : 'bg-[#0070AD]'}`} />
              <motion.span whileHover={{ scale: 1.15, rotate: 5 }}>
                <FaDatabase className={`text-xl ${gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]/80'}`} />
              </motion.span>
              <div className="flex-1 text-left">
                <div className="font-semibold">Data Pipeline</div>
                <div className={`text-xs ${gxEnabled ? 'text-white/40' : 'text-black/55'}`}>Automated ETL Workflow</div>
              </div>
            </motion.button>
          </motion.div>

          <div className="border-t border-black/10" />

          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
            <DataAssessment gxEnabled={gxEnabled} />
          </motion.div>

          <div className="border-t border-black/10" />

          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
            <DataQuality gxEnabled={gxEnabled} />
          </motion.div>

          <div className="border-t border-black/10" />

          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
            <DataOrchestration gxEnabled={gxEnabled} />
          </motion.div>

          <div className="border-t border-black/10" />

          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
            <Monitoring gxEnabled={gxEnabled} />
          </motion.div>

          <div className="border-t border-black/10" />

          {/* ChatHistory is shown under "Search chats" */}
          </div>
        )}
      </motion.aside>

      {!isCollapsed && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={() => setIsCollapsed(true)}
          className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm lg:hidden"
        />
      )}
    </>
  );
}
