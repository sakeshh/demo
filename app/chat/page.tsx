'use client';

import { motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { FaSignOutAlt } from 'react-icons/fa';
import Sidebar from '@/components/Sidebar';
import ChatWindow from '@/components/ChatWindow';
import AnimatedBackground from '@/components/AnimatedBackground';

export default function ChatPage() {
  const router = useRouter();

  const [gxEnabled, setGxEnabled] = useState(false);

  useEffect(() => {
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, []);

  const toggleGx = () => {
    const newVal = !gxEnabled;
    setGxEnabled(newVal);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('gxEnabled', String(newVal));
    }
  };

  const handleSignOut = () => {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem('agentThreadId');
    }
    router.push('/');
  };

  return (
    <div className="relative z-[1] flex min-h-0 w-full flex-1 flex-row overflow-hidden bg-transparent text-zinc-900">
      <AnimatedBackground className="pointer-events-none" />

      <Sidebar gxEnabled={gxEnabled} />

      <main className={`relative z-10 flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden self-stretch backdrop-blur-sm max-lg:pt-14 max-lg:pl-14 max-lg:pr-14 transition-all duration-700 ${
        gxEnabled ? 'bg-[#002B45]/90 text-white shadow-[inset_0_0_100px_rgba(0,112,173,0.2)]' : 'bg-white/60 text-zinc-900'
      }`}>
        <div className="fixed right-8 top-2 z-50 flex items-center gap-3">
          {/* GX Status Pill */}
          <div className="flex items-center gap-2 rounded-full bg-white/40 p-1 px-3 shadow-sm backdrop-blur-xl transition-all hover:bg-white/60">
            <span className={`text-[10px] font-black tracking-tight ${gxEnabled ? 'text-[#0070AD]' : 'text-zinc-500'}`}>GX</span>
            <button
              type="button"
              onClick={toggleGx}
              className={`relative inline-flex h-4 w-7 items-center rounded-full transition-all duration-500 focus:outline-none ${
                gxEnabled ? 'bg-[#0070AD]' : 'bg-zinc-300'
              }`}
            >
              <motion.span
                animate={{ x: gxEnabled ? 14 : 2 }}
                transition={{ type: "spring", stiffness: 500, damping: 30 }}
                className="h-2.5 w-2.5 rounded-full bg-white shadow-sm"
              />
            </button>
          </div>

          {/* Sign Out Pill */}
          <button
            onClick={handleSignOut}
            className="flex items-center gap-2 rounded-full bg-white/40 p-1 px-4 shadow-sm backdrop-blur-xl text-zinc-600 hover:text-red-600 transition-all hover:bg-white/60 group"
          >
            <FaSignOutAlt className="text-[11px] transition-transform group-hover:rotate-12" />
            <span className="text-[10px] font-black uppercase tracking-widest">Sign out</span>
          </button>
        </div>
        <ChatWindow gxEnabled={gxEnabled} />
      </main>
    </div>
  );
}
