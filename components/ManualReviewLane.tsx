'use client';

import { motion } from 'framer-motion';
import { FaInfoCircle, FaCheck, FaTimes, FaAngleRight } from 'react-icons/fa';
import { ManualReviewItem } from '@/types/pipeline';

interface ManualReviewLaneProps {
  items: ManualReviewItem[];
  onResolve: (itemId: string, resolutionId: string) => void;
  onSkip: (itemId: string) => void;
}

export default function ManualReviewLane({
  items,
  onResolve,
  onSkip,
}: ManualReviewLaneProps) {
  if (items.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-black/[0.01] rounded-xl border border-dashed border-black/10 min-h-[300px]">
        <div className="w-12 h-12 bg-emerald-500/10 rounded-full flex items-center justify-center text-emerald-500 mb-3">
          <FaCheck className="text-lg" />
        </div>
        <h4 className="text-sm font-bold text-zinc-900 mb-1">Zero Pending Manual Reviews</h4>
        <p className="text-xs text-black/55">All data exceptions have been successfully handled.</p>
      </div>
    );
  }

  const getSeverityStyle = (severity: string) => {
    const s = String(severity || 'medium').toLowerCase();
    if (s === 'high') {
      return { text: 'text-rose-600', bg: 'bg-rose-500/10', border: 'border-rose-500/20' };
    }
    if (s === 'low') {
      return { text: 'text-zinc-600', bg: 'bg-zinc-500/10', border: 'border-zinc-500/20' };
    }
    return { text: 'text-amber-600', bg: 'bg-amber-500/10', border: 'border-amber-500/20' };
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-bold text-zinc-800">Pending Review Items ({items.length})</h4>
        <p className="text-xs text-black/45">Manual decisions required to generate production rules</p>
      </div>

      <div className="grid grid-cols-1 gap-4 max-h-[480px] overflow-y-auto pr-1">
        {items.map((item, index) => {
          const sevColors = getSeverityStyle(item.severity);
          return (
            <motion.div
              key={item.id || index}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
              className="rounded-xl border border-black/10 bg-white/90 p-5 shadow-sm space-y-3 relative overflow-hidden"
            >
              {/* Card Header */}
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    {item.dataset && (
                      <span className="font-semibold text-xs text-zinc-900 bg-black/5 px-2 py-0.5 rounded">
                        Dataset: {item.dataset}
                      </span>
                    )}
                    {item.column && (
                      <span className="font-mono text-xs text-[#0070AD] bg-[#0070AD]/5 px-2 py-0.5 rounded">
                        Column: {item.column}
                      </span>
                    )}
                  </div>
                  <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${sevColors.bg} ${sevColors.text} border ${sevColors.border}`}>
                    Severity: {item.severity}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onSkip(item.id)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-black/10 bg-white text-xs font-semibold text-zinc-700 hover:bg-black/[0.02] transition-colors"
                  >
                    <FaTimes className="text-black/30" />
                    <span>Skip</span>
                  </button>
                  {item.default_resolution && (
                    <button
                      type="button"
                      onClick={() => onResolve(item.id, item.default_resolution!)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[#0070AD] hover:bg-[#0070AD]/90 text-xs font-bold text-white shadow-sm transition-all"
                    >
                      <FaCheck />
                      <span>Resolve</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Message Details */}
              <div className="flex items-start gap-2 text-xs text-zinc-700 p-3 rounded-lg bg-black/[0.01] border border-black/[0.03]">
                <FaInfoCircle className="text-[#0070AD] mt-0.5 flex-shrink-0" />
                <div>
                  <p className="font-medium text-zinc-800 leading-relaxed">{item.message}</p>
                  {item.guidance && (
                    <p className="text-[10px] text-black/50 mt-1 pl-0.5">
                      💡 Guidance: {item.guidance}
                    </p>
                  )}
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
