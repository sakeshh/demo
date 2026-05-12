'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FaCode,
  FaEye,
  FaSave,
  FaPlay,
  FaUndo,
  FaRedo,
  FaEdit,
  FaTrash,
  FaBars,
} from 'react-icons/fa';
import { TRANSFORMATION_TYPES } from '@/types';

interface TransformationStep {
  id: string;
  type: string;
  order: number;
}

export default function DataTransformation() {
  const [transformationType, setTransformationType] = useState('rename');
  const [scriptType, setScriptType] = useState<'python' | 'sql'>('python');
  const [steps, setSteps] = useState<TransformationStep[]>([
    { id: '1', type: 'Rename Columns', order: 1 },
    { id: '2', type: 'Filter Rows', order: 2 },
  ]);

  const handleDeleteStep = (id: string) => {
    setSteps(steps.filter((step) => step.id !== id));
  };

  return (
    <motion.div
      className="space-y-4"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.2 }}
    >
      <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
        Smart Data Transformation
      </h3>

      {/* Transformation Type Selector */}
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-2">
          Transformation Type
        </label>
        <div className="relative">
          <select
            value={transformationType}
            onChange={(e) => setTransformationType(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none bg-white appearance-none"
          >
            {TRANSFORMATION_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
          <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
      </div>

      {/* Custom Script Editor Toggle (shown when Custom Script is selected) */}
      {transformationType === 'custom' && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="space-y-2"
        >
          <label className="block text-xs font-medium text-slate-600 mb-2">
            Script Language
          </label>
          <div className="flex gap-2">
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => setScriptType('python')}
              className={`flex-1 px-3 py-2 text-sm font-medium rounded-lg transition-all ${
                scriptType === 'python'
                  ? 'bg-blue-600 text-white shadow-md'
                  : 'bg-white text-slate-700 border border-slate-300'
              }`}
            >
              Python
            </motion.button>
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => setScriptType('sql')}
              className={`flex-1 px-3 py-2 text-sm font-medium rounded-lg transition-all ${
                scriptType === 'sql'
                  ? 'bg-blue-600 text-white shadow-md'
                  : 'bg-white text-slate-700 border border-slate-300'
              }`}
            >
              SQL
            </motion.button>
          </div>
        </motion.div>
      )}

      {/* Dynamic Parameters Section */}
      <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
        <label className="block text-xs font-medium text-slate-600 mb-2">
          Parameters
        </label>
        <div className="space-y-2">
          <input
            type="text"
            placeholder="Parameter 1"
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none"
          />
          <input
            type="text"
            placeholder="Parameter 2"
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none"
          />
        </div>
      </div>

      {/* Preview Button */}
      <motion.button
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 hover:border-indigo-300 transition-all"
      >
        <FaEye className="text-indigo-600" />
        Preview Changes
      </motion.button>

      {/* Transformation Pipeline */}
      <div className="mt-4">
        <label className="block text-xs font-medium text-slate-600 mb-2">
          Transformation Pipeline
        </label>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          <AnimatePresence>
            {steps.map((step, index) => (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                className="flex items-center gap-2 p-2 bg-white border border-slate-200 rounded-lg group hover:border-indigo-300 transition-all"
              >
                <div className="flex items-center gap-2 flex-1">
                  <FaBars className="text-slate-400 cursor-move" />
                  <span className="text-xs font-medium text-slate-700">
                    {index + 1}. {step.type}
                  </span>
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button className="p-1.5 text-slate-500 hover:text-indigo-600 transition-colors">
                    <FaEdit className="w-3 h-3" />
                  </button>
                  <button
                    onClick={() => handleDeleteStep(step.id)}
                    className="p-1.5 text-slate-500 hover:text-red-600 transition-colors"
                  >
                    <FaTrash className="w-3 h-3" />
                  </button>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="space-y-2">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium text-white bg-gradient-to-r from-indigo-600 to-purple-600 rounded-lg hover:shadow-md transition-all"
        >
          <FaSave />
          Save Template
        </motion.button>

        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium text-white bg-gradient-to-r from-green-600 to-teal-600 rounded-lg hover:shadow-md transition-all"
        >
          <FaPlay />
          Apply Transformation
        </motion.button>

        {/* Undo/Redo */}
        <div className="flex gap-2">
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-all"
          >
            <FaUndo />
            Undo
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-all"
          >
            <FaRedo />
            Redo
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}
