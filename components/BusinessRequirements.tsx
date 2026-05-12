'use client';

import { motion } from 'framer-motion';
import { FaArrowRight, FaClipboardList } from 'react-icons/fa';

export default function BusinessRequirements({
  value,
  onChange,
  onNext,
}: {
  value: string;
  onChange: (next: string) => void;
  onNext: () => void;
}) {
  const trimmed = value.trim();
  const examples = [
    'Remove duplicates and standardize date formats',
    'Mask PII fields (email, phone) before export',
    'Validate schema: required columns and types',
    'Generate an ETL pipeline for daily batch loads',
    'Produce a report with quality score and anomalies',
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <div className="mt-1 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[#0070AD]/10 text-[#0070AD]">
          <FaClipboardList className="text-lg" />
        </div>
        <div className="min-w-0">
          <h2 className="text-3xl font-bold text-zinc-900 mb-2">Business Requirements</h2>
          <p className="text-black/60">
            Tell us what you want to achieve. We’ll use this to tailor assessment and ETL suggestions.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <label className="block text-sm font-medium text-black/70">Requirements</label>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={6}
          placeholder="Example: Remove duplicates, mask PII, validate schema, and generate daily ETL pipeline..."
          className="w-full rounded-2xl border border-black/10 bg-white/90 px-4 py-3 text-sm text-zinc-900 outline-none placeholder-black/35 transition-all focus:border-[#0070AD]/40 focus:ring-2 focus:ring-[#0070AD]/20"
        />

        <div className="flex flex-wrap gap-2">
          {examples.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                const next = trimmed ? `${trimmed}\n- ${ex}` : `- ${ex}`;
                onChange(next);
              }}
              className="rounded-full border border-black/10 bg-white/85 px-3 py-1.5 text-xs text-black/70 hover:border-[#0070AD]/25 hover:bg-white"
            >
              + {ex}
            </button>
          ))}
        </div>
      </div>

      <motion.button
        type="button"
        onClick={onNext}
        disabled={!trimmed}
        whileHover={{ scale: trimmed ? 1.02 : 1 }}
        whileTap={{ scale: trimmed ? 0.98 : 1 }}
        className={`inline-flex w-full items-center justify-center gap-2 rounded-xl border px-6 py-3 font-semibold transition-colors ${
          trimmed
            ? 'border-[#0070AD]/40 bg-[#0070AD]/10 text-[#0070AD] hover:bg-[#0070AD]/15 hover:border-[#0070AD]/60'
            : 'cursor-not-allowed border-black/10 bg-white/70 text-black/35'
        }`}
      >
        Continue
        <FaArrowRight className="text-sm" />
      </motion.button>
    </div>
  );
}

