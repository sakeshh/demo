'use client';

import { motion } from 'framer-motion';
import { FaCheckCircle, FaExclamationTriangle, FaTimesCircle, FaPlay, FaSpinner } from 'react-icons/fa';
import { ValidationResult } from '@/types/pipeline';

interface RequirementValidatorProps {
  validation: ValidationResult | null;
  onGenerate: () => void;
  busy: boolean;
}

export default function RequirementValidator({
  validation,
  onGenerate,
  busy,
}: RequirementValidatorProps) {
  if (!validation) return null;

  const { success, checks = [] } = validation;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-black/10 bg-white/60 p-6 shadow-sm space-y-4"
    >
      <div>
        <h3 className="text-md font-bold text-zinc-900 mb-1">Preflight Requirement Validation</h3>
        <p className="text-xs text-black/50">Verifies business rules safety and quality metrics before planning</p>
      </div>

      <div className="space-y-2 border-y border-black/5 py-4">
        {checks.map((check) => (
          <div key={check.id} className="flex items-start gap-2.5 text-xs text-zinc-700">
            {check.status === 'success' && (
              <FaCheckCircle className="text-emerald-500 mt-0.5 flex-shrink-0 text-sm" />
            )}
            {check.status === 'warning' && (
              <FaExclamationTriangle className="text-amber-500 mt-0.5 flex-shrink-0 text-sm" />
            )}
            {check.status === 'error' && (
              <FaTimesCircle className="text-rose-500 mt-0.5 flex-shrink-0 text-sm" />
            )}
            <div>
              <span className="font-semibold block text-zinc-800">{check.label}</span>
              {check.message && <span className="text-black/45 block text-[10px] mt-0.5">{check.message}</span>}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between pt-2">
        <div className="text-xs text-black/50 font-medium">
          {success ? (
            <span className="text-emerald-600 font-semibold">✓ Rules validated successfully. Ready to build plan.</span>
          ) : (
            <span className="text-rose-600 font-semibold">⚠️ Address rule warnings/errors before building.</span>
          )}
        </div>

        <button
          type="button"
          disabled={busy}
          onClick={onGenerate}
          className={`inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-bold text-white shadow-md transition-all ${
            success
              ? 'bg-emerald-600 hover:bg-emerald-700 active:scale-98'
              : 'bg-zinc-400 cursor-not-allowed opacity-50'
          }`}
        >
          {busy ? (
            <>
              <FaSpinner className="animate-spin text-sm" />
              <span>Building Plan...</span>
            </>
          ) : (
            <>
              <FaPlay className="text-xs" />
              <span>Build ETL Plan</span>
            </>
          )}
        </button>
      </div>
    </motion.div>
  );
}
