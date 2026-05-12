'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';

const COLORS = ['#0070AD', '#12ABDB', '#eab308', '#f97316', '#ec4899', '#a855f7'];

export default function Confetti({ trigger = true }: { trigger?: boolean }) {
  const [particles, setParticles] = useState<Array<{ id: number; x: number; color: string; delay: number; size: number }>>([]);

  useEffect(() => {
    if (!trigger) return;
    const count = 50;
    const next = Array.from({ length: count }, (_, i) => ({
      id: i,
      x: (i / count) * 100 - 50,
      color: COLORS[i % COLORS.length],
      delay: Math.random() * 0.5,
      size: 6 + Math.random() * 8,
    }));
    setParticles(next);
  }, [trigger]);

  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden z-50">
      {particles.map((p) => (
        <motion.div
          key={p.id}
          className="absolute left-1/2 top-1/2 rounded-sm"
          style={{
            width: p.size,
            height: p.size * 1.5,
            backgroundColor: p.color,
            rotate: Math.random() * 360,
            x: '-50%',
            y: '-50%',
          }}
          initial={{ opacity: 1, y: 0, x: '-50%' }}
          animate={{
            opacity: [1, 1, 0],
            y: [0, 400],
            x: [`-50%`, `calc(-50% + ${p.x * 8}px)`],
            rotate: 360 * 2,
          }}
          transition={{
            duration: 2,
            delay: p.delay,
            ease: 'easeOut',
          }}
        />
      ))}
    </div>
  );
}
