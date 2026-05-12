'use client';

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FaFileAlt,
  FaEye,
  FaDownload,
  FaChevronDown,
} from 'react-icons/fa';

const DATA_SOURCE_OPTIONS = ['File', 'Database', 'Azure Blob', 'API'] as const;

export default function DataAssessment({ gxEnabled = false }: { gxEnabled?: boolean }) {
  const [selected, setSelected] = useState<string>(DATA_SOURCE_OPTIONS[0]);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('click', onDoc);
    return () => document.removeEventListener('click', onDoc);
  }, []);

  return (
    <motion.div
      className="space-y-4"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
    >
      <h3 className={`mb-3 text-xs font-semibold uppercase tracking-wide ${gxEnabled ? 'text-emerald-400' : 'text-black/55'}`}>
        Intelligent Data Assessment
      </h3>

      <div ref={rootRef}>
        <label className={`mb-2 block text-xs font-medium ${gxEnabled ? 'text-white/40' : 'text-black/55'}`}>Select Data Source</label>
        <div className="relative">
          <motion.button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className={`flex w-full items-center justify-between gap-2 rounded-xl border px-3 py-2.5 text-left text-sm font-medium outline-none backdrop-blur-sm transition-all ${
              gxEnabled 
                ? 'border-emerald-500/30 bg-[#002B45]/80 text-white hover:border-emerald-500/50 hover:bg-[#002B45] focus-visible:border-emerald-500/50' 
                : 'border-[#0070AD]/35 bg-white/85 text-zinc-900 hover:border-[#0070AD]/50 hover:bg-white focus-visible:border-[#0070AD]/50 focus-visible:ring-2 focus-visible:ring-[#0070AD]/20'
            }`}
            whileTap={{ scale: 0.995 }}
            aria-haspopup="listbox"
            aria-expanded={open}
          >
            <span>{selected}</span>
            <FaChevronDown
              className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${open ? 'rotate-180' : ''} ${gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]/80'}`}
            />
          </motion.button>

          <AnimatePresence>
            {open && (
              <motion.ul
                role="listbox"
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.18, ease: 'easeOut' }}
                className={`absolute left-0 right-0 top-[calc(100%+6px)] z-50 overflow-hidden rounded-xl border py-1 shadow-[0_20px_50px_rgba(0,0,0,0.12)] backdrop-blur-xl ${
                  gxEnabled ? 'border-white/10 bg-[#001D2E]/95' : 'border-black/10 bg-white/95'
                }`}
              >
                {DATA_SOURCE_OPTIONS.map((option) => {
                  const isActive = option === selected;
                  return (
                    <li key={option} role="option" aria-selected={isActive}>
                      <button
                        type="button"
                        className={`flex w-full px-3 py-2.5 text-left text-sm transition-colors ${
                          isActive
                            ? gxEnabled ? 'bg-emerald-500/20 font-medium text-emerald-400' : 'bg-[#0070AD]/10 font-medium text-[#0070AD]'
                            : gxEnabled ? 'text-zinc-100 hover:bg-white/5' : 'text-zinc-900 hover:bg-black/5'
                        }`}
                        onClick={() => {
                          setSelected(option);
                          setOpen(false);
                        }}
                      >
                        {option}
                      </button>
                    </li>
                  );
                })}
              </motion.ul>
            )}
          </AnimatePresence>
        </div>
      </div>

      <div className="space-y-2">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all ${
            gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-[#002B45]' : 'border-black/10 bg-white/85 text-zinc-900 hover:bg-white'
          }`}
        >
          <motion.span whileHover={{ scale: 1.12, rotate: 5 }}>
            <FaEye className={gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]/80'} />
          </motion.span>
          View Schema
        </motion.button>

        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all ${
            gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-[#002B45]' : 'border-black/10 bg-white/85 text-zinc-900 hover:bg-white'
          }`}
        >
          <motion.span whileHover={{ scale: 1.12, rotate: 5 }}>
            <FaFileAlt className={gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]/80'} />
          </motion.span>
          View Metadata
        </motion.button>

        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-semibold transition-all ${
            gxEnabled ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20' : 'border-[#0070AD]/40 bg-[#0070AD]/15 text-[#0070AD] hover:bg-[#0070AD]/20'
          }`}
        >
          <motion.span whileHover={{ scale: 1.12, rotate: 5 }}>
            <FaDownload />
          </motion.span>
          Download Assessment Report
        </motion.button>
      </div>
    </motion.div>
  );
}
