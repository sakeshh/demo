'use client';

import { motion } from 'framer-motion';
import { FaExclamationTriangle, FaCheckCircle, FaPlus } from 'react-icons/fa';

export default function DataQuality({ gxEnabled = false }: { gxEnabled?: boolean }) {
  return (
    <motion.div
      className="space-y-4"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1, ease: 'easeOut' }}
    >
      <h3 className={`mb-3 text-xs font-semibold uppercase tracking-wide ${gxEnabled ? 'text-emerald-400' : 'text-black/55'}`}>
        Data Quality & Validation
      </h3>

      <div className="space-y-2">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all ${
            gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-[#002B45]' : 'border-black/10 bg-white/85 text-zinc-900 hover:bg-white'
          }`}
        >
          <motion.span whileHover={{ scale: 1.12, rotate: 5 }}>
            <FaExclamationTriangle className="text-amber-400" />
          </motion.span>
          View Anomalies
        </motion.button>

        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all ${
            gxEnabled ? 'border-white/10 bg-[#002B45]/80 text-white hover:bg-[#002B45]' : 'border-black/10 bg-white/85 text-zinc-900 hover:bg-white'
          }`}
        >
          <motion.span whileHover={{ scale: 1.12, rotate: 5 }}>
            <FaCheckCircle className={gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]'} />
          </motion.span>
          Apply Validation Rules
        </motion.button>

        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-semibold transition-all ${
            gxEnabled ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20' : 'border-[#0070AD]/40 bg-[#0070AD]/15 text-[#0070AD] hover:bg-[#0070AD]/20'
          }`}
        >
          <motion.span whileHover={{ scale: 1.12, rotate: 5 }}>
            <FaPlus />
          </motion.span>
          Add Custom Rule
        </motion.button>
      </div>
    </motion.div>
  );
}
