'use client';

import { motion, AnimatePresence } from 'framer-motion';

export type ToastType = 'success' | 'error' | 'info';

interface ToastProps {
  message: string;
  type?: ToastType;
  visible: boolean;
  onClose?: () => void;
}

const styles: Record<ToastType, string> = {
  success: 'border-[#0070AD]/50 bg-[#0070AD]/10',
  error: 'border-red-500/50 bg-red-950/80',
  info: 'border-zinc-500/50 bg-zinc-900/90',
};

export default function Toast({ message, type = 'info', visible, onClose }: ToastProps) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, x: 100 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 100 }}
          transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          className={`fixed bottom-6 right-6 z-50 px-4 py-3 rounded-lg border shadow-lg ${styles[type]} text-zinc-200`}
        >
          <p className="text-sm font-medium">{message}</p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
