'use client';

import { motion } from 'framer-motion';
import { FaToggleOff, FaToggleOn, FaShieldAlt, FaLock, FaLockOpen, FaCheckCircle, FaExclamationCircle } from 'react-icons/fa';
import { DQGateResult } from '@/types/pipeline';

interface GenerationModeSelectorProps {
  generationMode: 'cleanse_only' | 'full';
  onChange: (mode: 'cleanse_only' | 'full') => void;
  gateResult: DQGateResult | null;
  forceUnlock: boolean;
  onForceUnlockChange: (val: boolean) => void;
}

export default function GenerationModeSelector({
  generationMode,
  onChange,
  gateResult,
  forceUnlock,
  onForceUnlockChange,
}: GenerationModeSelectorProps) {
  const isLocked = gateResult ? !gateResult.passed : false;
  const isPhase2Disabled = isLocked && !forceUnlock;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-black/10 bg-white/60 p-6 shadow-sm space-y-5"
    >
      <div>
        <h3 className="text-lg font-bold text-zinc-900 mb-1">Select Generation Mode</h3>
        <p className="text-xs text-black/50">Determine whether to generate basic cleaning or complex business transformations</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Cleanse Only Option */}
        <motion.button
          type="button"
          onClick={() => onChange('cleanse_only')}
          className={`p-5 rounded-xl border text-left flex flex-col justify-between h-40 transition-all duration-300 relative overflow-hidden ${
            generationMode === 'cleanse_only'
              ? 'border-[#0070AD]/60 bg-[#0070AD]/10 shadow-[0_0_30px_rgba(0,112,173,0.12)]'
              : 'border-black/10 bg-white/85 hover:border-[#0070AD]/30 hover:bg-white'
          }`}
          whileHover={{ y: -2 }}
          whileTap={{ scale: 0.98 }}
        >
          <div className="w-full flex items-center justify-between">
            <span className="text-sm font-bold text-zinc-900">Cleanse Only (Phase 1)</span>
            <FaCheckCircle className={`text-lg ${generationMode === 'cleanse_only' ? 'text-[#0070AD]' : 'text-black/10'}`} />
          </div>
          <div className="mt-2 space-y-1">
            <p className="text-xs text-black/60 font-medium">Runs Raw → _Clean transformations only.</p>
            <p className="text-[10px] text-black/45">Includes trimming, casing, Sentinel/Null replacements, and deduplication.</p>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-500/10 text-emerald-700 border border-emerald-500/20">
            Always Unlocked
          </span>
        </motion.button>

        {/* Full Pipeline Option */}
        <motion.button
          type="button"
          onClick={() => onChange('full')}
          className={`p-5 rounded-xl border text-left flex flex-col justify-between h-40 transition-all duration-300 relative overflow-hidden ${
            generationMode === 'full'
              ? 'border-[#0070AD]/60 bg-[#0070AD]/10 shadow-[0_0_30px_rgba(0,112,173,0.12)]'
              : 'border-black/10 bg-white/85 hover:border-[#0070AD]/30 hover:bg-white'
          }`}
          whileHover={{ y: -2 }}
          whileTap={{ scale: 0.98 }}
        >
          <div className="w-full flex items-center justify-between">
            <span className="text-sm font-bold text-zinc-900">Full Pipeline (Phase 1 + 2)</span>
            <div className="flex items-center gap-1.5">
              {isLocked ? (
                forceUnlock ? (
                  <FaLockOpen className="text-amber-500 text-sm" />
                ) : (
                  <FaLock className="text-rose-500 text-sm" />
                )
              ) : (
                <FaLockOpen className="text-emerald-500 text-sm" />
              )}
              <FaCheckCircle className={`text-lg ${generationMode === 'full' ? 'text-[#0070AD]' : 'text-black/10'}`} />
            </div>
          </div>
          <div className="mt-2 space-y-1">
            <p className="text-xs text-black/60 font-medium">Runs Raw → _Clean → _Transformed steps.</p>
            <p className="text-[10px] text-black/45">Includes join routing, business rule validations, and SCD models.</p>
          </div>
          <div className="flex items-center gap-2">
            {isLocked ? (
              forceUnlock ? (
                <span className="text-[10px] px-2 py-0.5 rounded-full font-bold bg-amber-500/10 text-amber-700 border border-amber-500/20">
                  Force Unlocked
                </span>
              ) : (
                <span className="text-[10px] px-2 py-0.5 rounded-full font-bold bg-rose-500/10 text-rose-700 border border-rose-500/20">
                  Gated / Locked
                </span>
              )
            ) : (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-500/10 text-emerald-700 border border-emerald-500/20">
                Unlocked
              </span>
            )}
          </div>
        </motion.button>
      </div>

      {/* Force Unlock Control for Locks */}
      {isLocked && generationMode === 'full' && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="flex flex-col md:flex-row md:items-center justify-between gap-3 p-4 rounded-xl border border-rose-500/10 bg-rose-500/5"
        >
          <div className="flex items-center gap-2 text-rose-700 dark:text-rose-400">
            <FaExclamationCircle className="flex-shrink-0" />
            <p className="text-xs font-semibold">
              Data quality issues block Phase 2 transformation generation.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onForceUnlockChange(!forceUnlock)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all border ${
              forceUnlock
                ? 'bg-amber-500/15 border-amber-500/30 text-amber-800 hover:bg-amber-500/20'
                : 'bg-white border-black/10 text-zinc-700 hover:bg-black/[0.02]'
            }`}
          >
            {forceUnlock ? <FaToggleOn className="text-lg text-amber-600" /> : <FaToggleOff className="text-lg text-black/30" />}
            <span>Force Unlock Phase 2</span>
          </button>
        </motion.div>
      )}
    </motion.div>
  );
}
