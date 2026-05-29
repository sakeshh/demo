'use client';

import { motion } from 'framer-motion';
import { FaShieldAlt, FaLock, FaLockOpen, FaExclamationTriangle, FaCheckCircle } from 'react-icons/fa';
import { DQGateResult } from '@/types/pipeline';

interface DQGateDashboardProps {
  gateResult: DQGateResult | null;
  threshold: number;
  onThresholdChange: (val: number) => void;
}

export default function DQGateDashboard({
  gateResult,
  threshold,
  onThresholdChange,
}: DQGateDashboardProps) {
  if (!gateResult) return null;

  const { passed, score, has_high_pii, datasets = {} } = gateResult;

  const getGradeColor = (grade: string) => {
    switch (grade) {
      case 'A':
        return { text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' };
      case 'B':
        return { text: 'text-teal-600 dark:text-teal-400', bg: 'bg-teal-500/10', border: 'border-teal-500/20' };
      case 'C':
        return { text: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' };
      default:
        return { text: 'text-rose-600 dark:text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/20' };
    }
  };

  const getBarColor = (score: number, reqThreshold: number) => {
    if (score >= reqThreshold + 10) return 'bg-emerald-500';
    if (score >= reqThreshold) return 'bg-teal-500';
    if (score >= reqThreshold - 10) return 'bg-amber-500';
    return 'bg-rose-500';
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      className="relative overflow-hidden rounded-2xl border border-black/10 bg-white/60 p-6 shadow-sm backdrop-blur-md"
    >
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-black/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#0070AD]/10 flex items-center justify-center text-[#0070AD]">
            <FaShieldAlt className="text-xl" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-zinc-900">Data Quality Gate Dashboard</h3>
            <p className="text-xs text-black/50">Configure quality gate standards for Phase 2 loading</p>
          </div>
        </div>

        {has_high_pii && (
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-700 border border-amber-500/20">
            <FaExclamationTriangle className="text-amber-600 animate-pulse" />
            <span>High PII Elevated Threshold (+15)</span>
          </div>
        )}
      </div>

      {/* Dataset Scores Grid */}
      <div className="py-6 space-y-4">
        {Object.entries(datasets).map(([dsName, meta]) => {
          const colors = getGradeColor(meta.grade);
          return (
            <div key={dsName} className="space-y-1.5">
              <div className="flex items-center justify-between text-sm">
                <span className="font-semibold text-zinc-800">{dsName}</span>
                <div className="flex items-center gap-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${colors.bg} ${colors.text} border ${colors.border}`}>
                    Grade {meta.grade} ({meta.dq_score}%)
                  </span>
                  {meta.phase2_allowed ? (
                    <span className="flex items-center gap-1 text-emerald-600 text-xs font-semibold">
                      <FaLockOpen className="text-emerald-500" />
                      <span>Unlocked</span>
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-rose-600 text-xs font-semibold">
                      <FaLock className="text-rose-500" />
                      <span>Locked</span>
                    </span>
                  )}
                </div>
              </div>
              <div className="h-3 w-full bg-black/5 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${meta.dq_score}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                  className={`h-full rounded-full ${getBarColor(meta.dq_score, threshold)}`}
                />
              </div>
              {!meta.phase2_allowed && (
                <p className="text-[11px] text-rose-500/80 font-medium pl-1">
                  ⚠️ {meta.reason}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* Threshold Slider control */}
      <div className="pt-4 border-t border-black/5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex-1 space-y-1">
          <div className="flex justify-between text-sm font-semibold text-zinc-800">
            <span>Quality Threshold: {threshold}%</span>
            <span className="text-xs text-black/40">Default is 70%</span>
          </div>
          <input
            type="range"
            min="50"
            max="95"
            value={threshold}
            onChange={(e) => onThresholdChange(Number(e.target.value))}
            className="w-full h-1.5 bg-black/10 rounded-lg appearance-none cursor-pointer accent-[#0070AD]"
          />
        </div>

        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl bg-black/[0.02] border border-black/5 min-w-[220px]">
          {passed ? (
            <>
              <FaCheckCircle className="text-emerald-500 text-lg flex-shrink-0" />
              <div className="text-left">
                <p className="text-xs font-bold text-zinc-800">Overall Gate: PASSED</p>
                <p className="text-[10px] text-black/50">Phase 2 code available for all tables</p>
              </div>
            </>
          ) : (
            <>
              <FaExclamationTriangle className="text-amber-500 text-lg flex-shrink-0" />
              <div className="text-left">
                <p className="text-xs font-bold text-zinc-800">Overall Gate: BLOCKED</p>
                <p className="text-[10px] text-black/50">Some datasets locked for Phase 2</p>
              </div>
            </>
          )}
        </div>
      </div>
    </motion.div>
  );
}
