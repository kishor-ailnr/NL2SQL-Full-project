import { useState, useEffect } from 'react';
import ConnectDBScreen from './components/ConnectDBScreen';
import ChatWindow from './components/ChatWindow';
import HelpSidebar from './components/HelpSidebar';
import { getSessionStatus, connectDB } from './api/client';
import logoImg from './assets/logo.png';

export default function App() {
  const [screen, setScreen] = useState('connect'); // 'connect' | 'chat'
  const [session, setSession] = useState(null);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [sessionExpiredNotice, setSessionExpiredNotice] = useState('');
  const [isRestoringSession, setIsRestoringSession] = useState(true);

  // Check and restore persisted session from localStorage on mount
  useEffect(() => {
    const restoreSession = async () => {
      let storedData = null;
      try {
        const storedStr = localStorage.getItem('nl2sql_session');
        if (!storedStr) {
          setIsRestoringSession(false);
          return;
        }

        storedData = JSON.parse(storedStr);
        if (!storedData?.session_id) {
          localStorage.removeItem('nl2sql_session');
          setIsRestoringSession(false);
          return;
        }

        // Verify with backend that session is active or restorable
        const status = await getSessionStatus(storedData.session_id);
        if (status?.valid === true || status?.status === 'connected') {
          const mergedSession = {
            ...storedData,
            ...status,
            status: 'connected',
          };
          setSession(mergedSession);
          setScreen('chat');
          setSessionExpiredNotice('');
        } else if (storedData.db_type === 'demo' && storedData.demo_name) {
          // Seamlessly re-connect demo session if expired
          const reconnected = await connectDB({
            db_type: 'demo',
            demo_name: storedData.demo_name,
          });
          const mergedSession = {
            ...storedData,
            ...reconnected,
            status: 'connected',
          };
          localStorage.setItem('nl2sql_session', JSON.stringify(mergedSession));
          setSession(mergedSession);
          setScreen('chat');
          setSessionExpiredNotice('');
        } else {
          throw new Error('Your previous session expired, please reconnect.');
        }
      } catch (err) {
        if (storedData?.db_type === 'demo' && storedData?.demo_name) {
          try {
            const reconnected = await connectDB({
              db_type: 'demo',
              demo_name: storedData.demo_name,
            });
            const mergedSession = {
              ...storedData,
              ...reconnected,
              status: 'connected',
            };
            localStorage.setItem('nl2sql_session', JSON.stringify(mergedSession));
            setSession(mergedSession);
            setScreen('chat');
            setSessionExpiredNotice('');
            return;
          } catch (reconnectErr) {
            console.warn('Demo session auto-reconnect fallback failed:', reconnectErr.message);
          }
        }
        console.warn('Session restoration failed:', err.message);
        localStorage.removeItem('nl2sql_session');
        setSession(null);
        setScreen('connect');
        setSessionExpiredNotice('Your previous session expired, please reconnect.');
      } finally {
        setIsRestoringSession(false);
      }
    };

    restoreSession();
  }, []);

  const handleConnected = (sessionData) => {
    try {
      localStorage.setItem('nl2sql_session', JSON.stringify(sessionData));
    } catch (e) {
      console.warn('Could not save session to localStorage:', e);
    }
    setSession(sessionData);
    setScreen('chat');
    setSessionExpiredNotice('');
  };

  const handleDisconnect = () => {
    localStorage.removeItem('nl2sql_session');
    setSession(null);
    setScreen('connect');
    setSessionExpiredNotice('');
  };

  return (
    <div className="h-screen h-[100dvh] w-screen max-w-full bg-[#F8FAFB] text-slate-800 flex flex-col overflow-hidden relative selection:bg-teal-100 selection:text-teal-900">
      
      {/* Subtle Ambient Decorative Gradient Glows */}
      <div className="fixed top-[-10%] left-[-5%] w-[45vw] h-[45vw] rounded-full bg-teal-200/20 blur-[130px] pointer-events-none -z-10" />
      <div className="fixed bottom-[-10%] right-[-5%] w-[45vw] h-[45vw] rounded-full bg-indigo-200/15 blur-[140px] pointer-events-none -z-10" />

      {/* Top Navbar - Full Width Edge-to-Edge (60-68px desktop, 56-64px mobile) */}
      <header className="w-full h-14 sm:h-16 px-3 sm:px-6 md:px-8 border-b border-slate-200/80 bg-white/95 backdrop-blur-md shrink-0 z-30 flex items-center justify-between shadow-2xs">
        
        {/* Logo & App Brand */}
        <div className="flex items-center gap-2.5 sm:gap-3 min-w-0">
          <img
            src={logoImg}
            alt="NL2SQL Logo"
            className="h-8 sm:h-9 w-auto object-contain drop-shadow-2xs transition-transform duration-200 hover:scale-105 shrink-0"
          />
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-extrabold text-sm sm:text-base tracking-tight text-slate-900 truncate">
              NL-to-SQL Assistant
            </span>
            <span className="hidden md:inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold bg-teal-50 text-teal-800 border border-teal-200/60 shrink-0">
              AI Query Engine
            </span>
          </div>
        </div>

        {/* Right Header Navigation & Help Trigger */}
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          {screen === 'chat' && session && (
            <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200 shrink-0">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              Active Session
            </span>
          )}

          {/* Persistent Help / Guide Button */}
          <button
            onClick={() => setIsHelpOpen(true)}
            className="px-2.5 py-1.5 sm:px-3 sm:py-1.5 rounded-xl bg-white hover:bg-teal-50/80 border border-slate-200/90 hover:border-teal-300 text-slate-700 hover:text-teal-800 transition-all text-xs font-semibold flex items-center gap-1.5 shadow-2xs group min-h-[36px]"
            title="Open User Guide & Help"
          >
            <span className="w-5 h-5 rounded-full bg-slate-100 group-hover:bg-teal-600 text-slate-600 group-hover:text-white flex items-center justify-center font-bold text-xs transition-colors shrink-0">
              ?
            </span>
            <span className="hidden sm:inline">Guide</span>
          </button>
        </div>

      </header>

      {/* Main Content Area: Fills 100% of remaining vertical space */}
      <main className={`flex-1 min-h-0 w-full overflow-hidden flex flex-col ${screen === 'connect' ? 'overflow-y-auto items-center justify-center p-4 sm:p-6' : ''}`}>
        {isRestoringSession ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-500">
            <svg className="animate-spin w-7 h-7 text-teal-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span className="text-xs font-medium tracking-wide">Restoring your workspace...</span>
          </div>
        ) : screen === 'connect' ? (
          <div className="w-full max-w-xl my-auto">
            <ConnectDBScreen onConnected={handleConnected} initialNotice={sessionExpiredNotice} />
          </div>
        ) : (
          <ChatWindow session={session} onDisconnect={handleDisconnect} />
        )}
      </main>

      {/* Global Help / Orientation Drawer (Left Slide-in) */}
      <HelpSidebar
        isOpen={isHelpOpen}
        onClose={() => setIsHelpOpen(false)}
      />

    </div>
  );
}
