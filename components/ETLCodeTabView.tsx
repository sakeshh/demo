'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FaLock, FaLockOpen, FaCopy, FaDownload, FaExclamationTriangle, FaCheckCircle, FaChevronRight } from 'react-icons/fa';
import { DQGateResult, ManualReviewItem } from '@/types/pipeline';
import SQLQualityBadge from '@/components/SQLQualityBadge';
import ManualReviewLane from '@/components/ManualReviewLane';

interface ETLCodeTabViewProps {
  activeTab: 'phase1' | 'phase2' | 'review';
  onTabChange: (tab: 'phase1' | 'phase2' | 'review') => void;
  phase1Code: string | null;
  phase2Code: string | null;
  manualItems: ManualReviewItem[];
  gateResult: DQGateResult | null;
  qualityScore: { score: number; grade: string; warnings_count: number; critical_count: number } | null;
  onResolveItem: (itemId: string, resolutionId: string) => void;
  onSkipItem: (itemId: string) => void;
  onCopy: (text: string) => void;
  onDownload: (text: string, type: 'phase1' | 'phase2') => void;
  onForceUnlock?: () => void;
}

export default function ETLCodeTabView({
  activeTab,
  onTabChange,
  phase1Code,
  phase2Code,
  manualItems,
  gateResult,
  qualityScore,
  onResolveItem,
  onSkipItem,
  onCopy,
  onDownload,
  onForceUnlock,
}: ETLCodeTabViewProps) {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied'>('idle');
  const isPhase2Locked = gateResult ? !gateResult.passed : false;

  const handleCopy = (text: string | null) => {
    if (!text) return;
    onCopy(text);
    setCopyStatus('copied');
    setTimeout(() => setCopyStatus('idle'), 2000);
  };

  const pendingReviewsCount = manualItems.filter(item => !item.default_resolution).length;

  return (
    <div className="rounded-2xl border border-black/10 bg-white/60 shadow-sm overflow-hidden flex flex-col min-h-[600px]">
      {/* Header Tabs */}
      <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-black/10 bg-black/[0.02] p-4 gap-4">
        <div className="flex bg-black/5 p-1 rounded-xl w-fit">
          <button
            type="button"
            onClick={() => onTabChange('phase1')}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all ${
              activeTab === 'phase1' ? 'bg-[#0070AD] text-white shadow-sm' : 'text-zinc-700 hover:text-zinc-950'
            }`}
          >
            Phase 1: Cleanse
          </button>
          <button
            type="button"
            onClick={() => onTabChange('phase2')}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
              activeTab === 'phase2' ? 'bg-[#0070AD] text-white shadow-sm' : 'text-zinc-700 hover:text-zinc-950'
            }`}
          >
            {isPhase2Locked && <FaLock className="text-[10px] text-rose-500" />}
            <span>Phase 2: Transform</span>
          </button>
          <button
            type="button"
            onClick={() => onTabChange('review')}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all relative ${
              activeTab === 'review' ? 'bg-[#0070AD] text-white shadow-sm' : 'text-zinc-700 hover:text-zinc-950'
            }`}
          >
            <span>Manual Review</span>
            {pendingReviewsCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-rose-500 text-white flex items-center justify-center text-[9px] font-black animate-pulse">
                {pendingReviewsCount}
              </span>
            )}
          </button>
        </div>

        {qualityScore && <SQLQualityBadge scoreData={qualityScore} />}
      </div>

      {/* Content Area */}
      <div className="flex-1 flex flex-col p-6 bg-white/40">
        <AnimatePresence mode="wait">
          {/* Phase 1 Code Tab */}
          {activeTab === 'phase1' && (
            <motion.div
              key="phase1"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              className="flex-1 flex flex-col space-y-4"
            >
              <div className="flex items-center justify-between text-xs text-black/55 font-medium">
                <span>Phase 1 active: Cleansing, normalization, and Sentinel nullifications</span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleCopy(phase1Code)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-black/10 bg-white hover:bg-black/[0.02] font-semibold transition-colors"
                  >
                    <FaCopy />
                    <span>{copyStatus === 'copied' ? 'Copied' : 'Copy'}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => phase1Code && onDownload(phase1Code, 'phase1')}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-black/10 bg-white hover:bg-black/[0.02] font-semibold transition-colors"
                  >
                    <FaDownload />
                    <span>Download</span>
                  </button>
                </div>
              </div>
              <textarea
                readOnly
                value={phase1Code || 'No Phase 1 code generated.'}
                className="w-full flex-1 min-h-[400px] rounded-xl border border-black/10 bg-zinc-950 p-4 font-mono text-[11px] leading-relaxed text-emerald-100 placeholder:text-emerald-100/35 outline-none resize-none"
              />
            </motion.div>
          )}

          {/* Phase 2 Code Tab */}
          {activeTab === 'phase2' && (
            <motion.div
              key="phase2"
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              className="flex-1 flex flex-col relative"
            >
              {isPhase2Locked ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-zinc-50/20 backdrop-blur-[2px] rounded-xl border border-dashed border-rose-500/10">
                  <div className="w-16 h-16 bg-rose-500/10 rounded-full flex items-center justify-center text-rose-500 mb-4 shadow-sm animate-bounce">
                    <FaLock className="text-2xl" />
                  </div>
                  <h4 className="text-xl font-bold text-zinc-900 mb-2">Phase 2 Transformations Locked</h4>
                  <p className="text-sm text-black/50 max-w-[500px] mb-6">
                    Data Quality requirements failed for one or more datasets. Business rules and downstream loading patterns have been locked.
                  </p>
                  
                  {gateResult && (
                    <div className="mb-8 w-full max-w-[450px] rounded-xl border border-black/5 bg-white/90 p-4 space-y-2.5 text-left">
                      {Object.entries(gateResult.datasets || {}).map(([dsName, meta]) => (
                        <div key={dsName} className="flex items-center justify-between text-xs">
                          <span className="font-semibold text-zinc-800">{dsName}</span>
                          <span className={meta.phase2_allowed ? 'text-emerald-600 font-semibold' : 'text-rose-600 font-semibold'}>
                            {meta.phase2_allowed ? '✓ Ready' : `⚠️ Score ${meta.dq_score}% < Threshold`}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="flex gap-4">
                    {phase2Code && (
                      <button
                        type="button"
                        onClick={() => onTabChange('phase1')}
                        className="px-5 py-2.5 rounded-xl border border-black/10 bg-white hover:bg-black/[0.02] text-xs font-bold text-zinc-700 transition-colors"
                      >
                        Review Phase 1 Code
                      </button>
                    )}
                    {onForceUnlock && (
                      <button
                        type="button"
                        onClick={onForceUnlock}
                        className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-600 text-xs font-bold text-white shadow-md transition-colors"
                      >
                        Force Unlock Phase 2
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex flex-col space-y-4">
                  <div className="flex items-center justify-between text-xs text-black/55 font-medium">
                    <span>Phase 2 active: Advanced joins, business logic validation, and SCD models</span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => handleCopy(phase2Code)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-black/10 bg-white hover:bg-black/[0.02] font-semibold transition-colors"
                      >
                        <FaCopy />
                        <span>{copyStatus === 'copied' ? 'Copied' : 'Copy'}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => phase2Code && onDownload(phase2Code, 'phase2')}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-black/10 bg-white hover:bg-black/[0.02] font-semibold transition-colors"
                      >
                        <FaDownload />
                        <span>Download</span>
                      </button>
                    </div>
                  </div>
                  <textarea
                    readOnly
                    value={phase2Code || 'No Phase 2 code generated.'}
                    className="w-full flex-1 min-h-[400px] rounded-xl border border-black/10 bg-zinc-950 p-4 font-mono text-[11px] leading-relaxed text-emerald-100 placeholder:text-emerald-100/35 outline-none resize-none"
                  />
                </div>
              )}
            </motion.div>
          )}

          {/* Manual Review Tab */}
          {activeTab === 'review' && (
            <motion.div
              key="review"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex-1 flex flex-col"
            >
              <ManualReviewLane
                items={manualItems}
                onResolve={onResolveItem}
                onSkip={onSkipItem}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
