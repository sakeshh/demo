'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { FaCheck, FaTimes, FaExclamationTriangle } from 'react-icons/fa';

interface SemanticColumnEditorProps {
  columnName: string;
  currentType: string;
  currentSubType: string;
  currentPii: string;
  onSave: (updates: { semantic_type: string; sub_type: string; pii_level: 'none' | 'low' | 'medium' | 'high' }) => void;
  onCancel: () => void;
}

const SEMANTIC_TYPES = [
  { value: 'id', label: 'ID / Identifier' },
  { value: 'metric', label: 'Metric (Measure)' },
  { value: 'categorical', label: 'Categorical' },
  { value: 'date', label: 'Date / Datetime' },
  { value: 'string', label: 'String' },
];

const SUB_TYPES = [
  { value: 'unknown', label: 'Unknown / None' },
  { value: 'pk', label: 'Primary Key (pk)' },
  { value: 'fk', label: 'Foreign Key (fk)' },
  { value: 'email', label: 'Email' },
  { value: 'phone', label: 'Phone Number' },
  { value: 'zip_code', label: 'Zip / Postal Code' },
  { value: 'ssn', label: 'SSN (Social Security)' },
  { value: 'uuid', label: 'UUID / GUID' },
  { value: 'currency', label: 'Currency / Amount' },
  { value: 'age', label: 'Age' },
  { value: 'percentage', label: 'Percentage' },
  { value: 'status_flag', label: 'Status Flag' },
  { value: 'country', label: 'Country' },
  { value: 'gender', label: 'Gender' },
];

const PII_LEVELS = [
  { value: 'none', label: 'None' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];

export default function SemanticColumnEditor({
  columnName,
  currentType,
  currentSubType,
  currentPii,
  onSave,
  onCancel,
}: SemanticColumnEditorProps) {
  const [semType, setSemType] = useState(currentType || 'string');
  const [subType, setSubType] = useState(currentSubType || 'unknown');
  const [piiLevel, setPiiLevel] = useState<'none' | 'low' | 'medium' | 'high'>(
    (currentPii as any) || 'none'
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      semantic_type: semType,
      sub_type: subType,
      pii_level: piiLevel,
    });
  };

  const showPiiWarning = piiLevel === 'high';

  return (
    <motion.form
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      onSubmit={handleSubmit}
      className="p-4 rounded-xl border border-[#0070AD]/20 bg-[#0070AD]/5 space-y-4 my-2 text-xs"
    >
      <div className="flex items-center justify-between">
        <span className="font-bold text-zinc-900">
          Edit Column: <code className="text-[#0070AD]">{columnName}</code>
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="p-1 text-black/45 hover:text-black hover:bg-black/5 rounded"
          >
            <FaTimes />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Semantic Type Selection */}
        <div>
          <label className="block text-[10px] font-black uppercase text-black/50 mb-1">
            Semantic Type
          </label>
          <select
            value={semType}
            onChange={(e) => setSemType(e.target.value)}
            className="w-full px-2 py-1.5 border border-black/10 rounded bg-white text-black outline-none focus:border-[#0070AD]/40"
          >
            {SEMANTIC_TYPES.map((opt) => (
              <option key={opt.value} value={opt.value} className="text-black bg-white">
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Logical Sub-type Selection */}
        <div>
          <label className="block text-[10px] font-black uppercase text-black/50 mb-1">
            Sub-type / logical type
          </label>
          <select
            value={subType}
            onChange={(e) => setSubType(e.target.value)}
            className="w-full px-2 py-1.5 border border-black/10 rounded bg-white text-black outline-none focus:border-[#0070AD]/40"
          >
            {SUB_TYPES.map((opt) => (
              <option key={opt.value} value={opt.value} className="text-black bg-white">
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* PII Level Selection */}
        <div>
          <label className="block text-[10px] font-black uppercase text-black/50 mb-1">
            PII Level
          </label>
          <select
            value={piiLevel}
            onChange={(e) => setPiiLevel(e.target.value as any)}
            className="w-full px-2 py-1.5 border border-black/10 rounded bg-white text-black outline-none focus:border-[#0070AD]/40"
          >
            {PII_LEVELS.map((opt) => (
              <option key={opt.value} value={opt.value} className="text-black bg-white">
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {showPiiWarning && (
        <div className="flex items-start gap-2 text-[10px] text-amber-700 bg-amber-500/10 p-2.5 rounded-lg border border-amber-500/20 leading-relaxed font-semibold">
          <FaExclamationTriangle className="text-amber-600 mt-0.5 flex-shrink-0" />
          <span>
            Setting PII to High raises this dataset&apos;s DQ Gate passing threshold by +15 in Phase 2 transforms.
          </span>
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 border border-black/10 hover:border-black/20 font-semibold rounded text-zinc-700"
        >
          Cancel
        </button>
        <button
          type="submit"
          className="px-3 py-1.5 bg-[#0070AD] hover:bg-[#0070AD]/90 font-bold text-white rounded shadow-sm flex items-center gap-1.5"
        >
          <FaCheck />
          <span>Apply Override</span>
        </button>
      </div>
    </motion.form>
  );
}
