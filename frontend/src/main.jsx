import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// Intercept and safely handle HTMLMediaElement play() interruptions (AbortError)
// This occurs when play() and pause() are called in rapid succession during React re-renders or unmounts.
if (typeof window !== 'undefined') {
  if (typeof HTMLMediaElement !== 'undefined') {
    const originalPlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function (...args) {
      const playPromise = originalPlay.apply(this, args);
      if (playPromise !== undefined && typeof playPromise.catch === 'function') {
        return playPromise.catch((error) => {
          if (
            error.name === 'AbortError' ||
            error.name === 'NotSupportedError' ||
            error.message?.includes('interrupted by a call to pause') ||
            error.message?.includes('no supported source was found')
          ) {
            // Expected browser behavior when audio fails to load or pause is called; safely ignore.
            return;
          }
          throw error;
        });
      }
      return playPromise;
    };
  }

  // Prevent uncaught promise rejection from logging AbortError or NotSupportedError to console
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    const str = String(reason?.message || reason || '');
    if (
      reason?.name === 'AbortError' ||
      reason?.name === 'NotSupportedError' ||
      str.includes('interrupted by a call to pause') ||
      str.includes('no supported source was found') ||
      str.includes('NotSupportedError')
    ) {
      event.preventDefault();
    }
  });
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
