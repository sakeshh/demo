'use client';

import { motion } from 'framer-motion';
import { FaLock, FaLockOpen, FaInfoCircle, FaShieldAlt } from 'react-icons/fa';
import { DQGateResult } from '@/types/pipeline';

interface RequirementsPhasePanelProps {
  datasetName: string;
  gateResult: DQGateResult | null;
  threshold: number;
  generationMode: 'cleanse_only' | 'full';
  forceUnlock: boolean;
  
  // Phase 1 States
  neverDropRows: boolean;
  onNeverDropRowsChange: (val: boolean) => void;
  requiredColumns: string;
  onRequiredColumnsChange: (val: string) => void;
  excludeColumns: string;
  onExcludeColumnsChange: (val: string) => void;
  outlierStrategy: 'flag' | 'clip' | 'cap';
  onOutlierStrategyChange: (val: 'flag' | 'clip' | 'cap') => void;
  
  // Phase 2 States
  notes: string;
  onNotesChange: (val: string) => void;
  scdType: 'type1' | 'type2' | 'none';
  onScdTypeChange: (val: 'type1' | 'type2' | 'none') => void;
  hashPhone: boolean;
  onHashPhoneChange: (val: boolean) => void;
  maskEmail: boolean;
  onMaskEmailChange: (val: boolean) => void;
}

export default function RequirementsPhasePanel({
  datasetName,
  gateResult,
  threshold,
  generationMode,
  forceUnlock,
  
  neverDropRows,
  onNeverDropRowsChange,
  requiredColumns,
  onRequiredColumnsChange,
  excludeColumns,
  onExcludeColumnsChange,
  outlierStrategy,
  onOutlierStrategyChange,
  
  notes,
  onNotesChange,
  scdType,
  onScdTypeChange,
  hashPhone,
  onHashPhoneChange,
  maskEmail,
  onMaskEmailChange,
}: RequirementsPhasePanelProps) {
  // Check if this specific dataset passes Phase 2
  const dsMeta = gateResult?.datasets?.[datasetName] ?? { phase2_allowed: true, dq_score: 100 };
  const isBlocked = !dsMeta.phase2_allowed;
  const isPhase2Locked = generationMode === 'cleanse_only' || (isBlocked && !forceUnlock);

  const fieldClass = "w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-[#0070AD]/50 outline-none transition-colors";
  const labelClass = "block text-[11px] font-black uppercase tracking-widest text-black/45 mb-1.5";

  return (
    <div className="space-y-6">
      {/* Dataset Info Header */}
      <div className="flex items-center justify-between pb-2 border-b border-black/5">
        <h4 className="text-md font-bold text-zinc-800">
          Dataset Rules: <span className="text-[#0070AD]">{datasetName}</span>
        </h4>
        <div className="text-xs font-semibold text-black/50">
          DQ Score: {dsMeta.dq_score}% (Threshold: {threshold}%)
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* PHASE 1: CLEANSE RULES */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 pb-1 border-b border-black/[0.03]">
            <span className="text-xs font-bold text-emerald-600 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/10">
              Phase 1: Cleanse
            </span>
            <span className="text-xs text-black/40">Always active</span>
          </div>

          {/* Never Drop Rows Checkbox */}
          <label className="flex items-start gap-3 cursor-pointer p-3 rounded-xl bg-black/[0.01] hover:bg-black/[0.02] border border-black/5 transition-colors">
            <input
              type="checkbox"
              checked={neverDropRows}
              onChange={(e) => onNeverDropRowsChange(e.target.checked)}
              className="mt-1 h-4 w-4 rounded border-black/20 text-[#0070AD] focus:ring-[#0070AD]/30"
            />
            <span className="text-xs text-zinc-700">
              <span className="font-bold block text-zinc-800">Never drop rows</span>
              Prefer filling missing data over dropping rows.
            </span>
          </label>

          {/* Outlier Strategy Selector */}
          <div>
            <span className={labelClass}>Outlier Strategy</span>
            <div className="flex gap-2">
              {(['flag', 'clip', 'cap'] as const).map((strategy) => (
                <button
                  key={strategy}
                  type="button"
                  onClick={() => onOutlierStrategyChange(strategy)}
                  className={`flex-1 rounded-lg py-1.5 text-xs font-bold capitalize border transition-all ${
                    outlierStrategy === strategy
                      ? 'bg-emerald-600 text-white border-emerald-600'
                      : 'bg-white border-black/10 hover:border-black/20 text-zinc-700'
                  }`}
                >
                  {strategy}
                </button>
              ))}
            </div>
          </div>

          {/* Required Columns */}
          <div>
            <span className={labelClass}>Required Columns</span>
            <textarea
              value={requiredColumns}
              onChange={(e) => onRequiredColumnsChange(e.target.value)}
              placeholder="e.g. CustomerID, Email (comma or newline separated)"
              rows={2}
              className={fieldClass}
            />
          </div>

          {/* Exclude Columns */}
          <div>
            <span className={labelClass}>Exclude Columns</span>
            <textarea
              value={excludeColumns}
              onChange={(e) => onExcludeColumnsChange(e.target.value)}
              placeholder="Columns to leave completely untouched"
              rows={2}
              className={fieldClass}
            />
          </div>
        </div>

        {/* PHASE 2: TRANSFORM RULES */}
        <div className={`space-y-4 transition-opacity duration-300 relative ${isPhase2Locked ? 'opacity-50' : 'opacity-100'}`}>
          {isPhase2Locked && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-zinc-50/40 backdrop-blur-[1px] rounded-xl border border-dashed border-rose-500/20 text-center p-4">
              <div className="w-10 h-10 rounded-full bg-rose-500/10 flex items-center justify-center text-rose-500 mb-2">
                <FaLock />
              </div>
              <p className="text-xs font-bold text-rose-700">Phase 2: Transform Gated</p>
              {generationMode === 'cleanse_only' ? (
                <p className="text-[10px] text-zinc-500 max-w-[200px]">
                  Mode set to Cleanse Only. Enable Full Pipeline to configure.
                </p>
              ) : (
                <p className="text-[10px] text-zinc-500 max-w-[200px]">
                  DQ score ({dsMeta.dq_score}%) falls below threshold ({threshold}%). Use Force Unlock to bypass.
                </p>
              )}
            </div>
          )}

          <div className="flex items-center justify-between pb-1 border-b border-black/[0.03]">
            <span className="text-xs font-bold text-[#0070AD] bg-[#0070AD]/10 px-2 py-0.5 rounded-full border border-[#0070AD]/10">
              Phase 2: Transform
            </span>
            <div className="flex items-center gap-1 text-xs text-black/40">
              {isPhase2Locked ? <FaLock /> : <FaLockOpen />}
              <span>{isPhase2Locked ? 'Locked' : 'Unlocked'}</span>
            </div>
          </div>

          {/* SCD Type Selector */}
          <div>
            <span className={labelClass}>Slowly Changing Dimension (SCD) Pattern</span>
            <select
              value={scdType}
              onChange={(e) => onScdTypeChange(e.target.value as 'type1' | 'type2' | 'none')}
              disabled={isPhase2Locked}
              className={fieldClass}
            >
              <option value="none">No History (Overwrite/Truncate)</option>
              <option value="type1">SCD Type 1 (Updates in-place)</option>
              <option value="type2">SCD Type 2 (Maintains history logs)</option>
            </select>
          </div>

          {/* Privacy Transforms */}
          <div>
            <span className={labelClass}>Privacy Transforms</span>
            <div className="space-y-2">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={hashPhone}
                  onChange={(e) => onHashPhoneChange(e.target.checked)}
                  disabled={isPhase2Locked}
                  className="h-4 w-4 rounded border-black/20 text-[#0070AD] focus:ring-[#0070AD]/30"
                />
                <span className="text-xs text-zinc-700 font-medium">Hash phone columns</span>
              </label>

              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={maskEmail}
                  onChange={(e) => onMaskEmailChange(e.target.checked)}
                  disabled={isPhase2Locked}
                  className="h-4 w-4 rounded border-black/20 text-[#0070AD] focus:ring-[#0070AD]/30"
                />
                <span className="text-xs text-zinc-700 font-medium">Mask email columns</span>
              </label>
            </div>
          </div>

          {/* Business notes */}
          <div>
            <span className={labelClass}>Business notes</span>
            <textarea
              value={notes}
              onChange={(e) => onNotesChange(e.target.value)}
              disabled={isPhase2Locked}
              placeholder="Explain constraints or engineering handoff rules."
              rows={3}
              className={fieldClass}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
