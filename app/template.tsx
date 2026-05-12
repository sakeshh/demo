'use client';

import { motion } from 'framer-motion';

export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      className="flex min-h-dvh h-dvh w-full flex-col"
      /* Opacity only: `y` transform creates a containing block and breaks `position:fixed`
         (e.g. /chat) so it no longer covers the full viewport. */
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  );
}
