'use client';

import { motion } from 'framer-motion';
import { FaCheckCircle, FaExclamationTriangle, FaTimesCircle } from 'react-icons/fa';

interface SQLQualityBadgeProps {
  scoreData: {
    score: number;
    grade: string;
    warnings_count?: number;
    critical_count?: number;
  };
}

export default function SQLQualityBadge({ scoreData }: SQLQualityBadgeProps) {
  const { score, grade, warnings_count = 0, critical_count = 0 } = scoreData;

  const getGradeStyle = (g: string) => {
    const gradeUpper = String(g || 'B').toUpperCase().trim();
    switch (gradeUpper) {
      case 'A':
        return { text: 'text-emerald-700 dark:text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' };
      case 'B':
        return { text: 'text-teal-700 dark:text-teal-400', bg: 'bg-teal-500/10', border: 'border-teal-500/20' };
      case 'C':
        return { text: 'text-amber-700 dark:text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' };
      default:
        return { text: 'text-rose-700 dark:text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/20' };
    }
  };

  const style = getGradeStyle(grade);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className={`inline-flex items-center gap-3 px-3 py-1.5 rounded-xl border ${style.bg} ${style.border} ${style.text}`}
    >
      <div className="flex items-center gap-1.5">
        {grade === 'F' ? (
          <FaTimesCircle className="text-rose-500 text-sm" />
        ) : critical_count > 0 ? (
          <FaExclamationTriangle className="text-amber-500 text-sm animate-pulse" />
        ) : (
          <FaCheckCircle className="text-emerald-500 text-sm" />
        )}
        <span className="text-xs font-black tracking-wide uppercase">
          ETL Quality Grade: {grade} ({score}%)
        </span>
      </div>

      {(warnings_count > 0 || critical_count > 0) && (
        <div className="flex items-center gap-1.5 pl-2.5 border-l border-current/25 text-[10px] font-bold">
          {critical_count > 0 && (
            <span className="text-rose-600 dark:text-rose-400">
              {critical_count} critical
            </span>
          )}
          {warnings_count > 0 && (
            <span className="text-amber-600 dark:text-amber-400">
              {warnings_count} warnings
            </span>
          )}
        </div>
      )}
    </motion.div>
  );
}
