import { motion } from 'framer-motion';
import logoImg from '../assets/logo.png';

/**
 * MessageBubble Component
 *
 * Handles 4 primary states:
 * 1. User Message (with optional corrected_terms tags/chips highlighted in soft yellow)
 * 2. Data Unavailable State (distinct, calm informational bubble in soft neutral blue/sky tone; no SQL, no chart)
 * 3. Clarification Question State (soft amber card prompting user for details; no SQL, no chart)
 * 4. Normal Answer State (assistant analysis card with confidence badge, optional "View SQL" drawer button, explanation, and results)
 */
export default function MessageBubble({
  role = 'assistant',
  content = '',
  rawContent = '',
  interpretedText = null,
  correctedTerms = [],
  dataAvailable = true,
  unavailableMessage = null,
  needsClarification = false,
  clarificationQuestion = null,
  needsConfirmation = false,
  confirmationQuestion = null,
  suggestedValue = null,
  confidence = 1.0,
  sql = null,
  queryData = null,
  onViewSQL = null,
  onLearnSQL = null,
  onConfirmWrite = null,
  onCancelWrite = null,
  originalQuestion = '',
  timestamp = '',
  children = null,
}) {
  const isUser = role === 'user';

  // Extract resolved values supporting both direct props and queryData object
  const resolvedDataAvailable =
    queryData?.data_available !== undefined
      ? Boolean(queryData.data_available)
      : dataAvailable !== undefined
      ? Boolean(dataAvailable)
      : true;

  const resolvedUnavailableMessage =
    queryData?.unavailable_message || unavailableMessage || '';

  const resolvedNeedsClarification =
    queryData?.needs_clarification !== undefined
      ? Boolean(queryData.needs_clarification)
      : Boolean(needsClarification);

  const resolvedClarificationQuestion =
    queryData?.clarification_question || clarificationQuestion || '';

  const resolvedNeedsConfirmation =
    queryData?.needs_confirmation !== undefined
      ? Boolean(queryData.needs_confirmation)
      : Boolean(needsConfirmation);

  const resolvedConfirmationQuestion =
    queryData?.confirmation_question || confirmationQuestion || '';

  const resolvedSuggestedValue =
    queryData?.suggested_value || suggestedValue || null;

  const resolvedSql = queryData?.sql ?? sql;
  const resolvedConfidence = queryData?.confidence ?? confidence;
  const resolvedExplanation = queryData?.explanation || content || '';
  const resolvedCorrectedTerms =
    (queryData?.corrected_terms && queryData.corrected_terms.length > 0)
      ? queryData.corrected_terms
      : (Array.isArray(correctedTerms) ? correctedTerms : []);

  // Compare cleaned versions to detect raw vs interpreted differences
  const cleanRaw = (rawContent || content || '').trim().toLowerCase().replace(/[.,/#!$%^&*;:{}=\-_`~()?]/g, '');
  const cleanInterpreted = (interpretedText || '').trim().toLowerCase().replace(/[.,/#!$%^&*;:{}=\-_`~()?]/g, '');
  const isMeaningfullyDifferent = Boolean(
    isUser &&
    cleanInterpreted &&
    cleanRaw &&
    cleanInterpreted !== cleanRaw
  );

  const displayText = (isMeaningfullyDifferent && interpretedText) ? interpretedText : (content || rawContent);

  // Confidence badge color mapping for normal query answers
  const confVal = typeof resolvedConfidence === 'number' ? resolvedConfidence : 1.0;
  const confPercent = Math.round(confVal * 100);
  let badgeColorClass = 'bg-emerald-50 text-emerald-800 border-emerald-200/80';
  let badgeDotClass = 'bg-emerald-500';
  if (confVal < 0.5) {
    badgeColorClass = 'bg-rose-50 text-rose-800 border-rose-200/80';
    badgeDotClass = 'bg-rose-500';
  } else if (confVal <= 0.8) {
    badgeColorClass = 'bg-amber-50 text-amber-800 border-amber-200/80';
    badgeDotClass = 'bg-amber-500';
  }

  // -------------------------------------------------------------
  // STATE 1: User Message
  // -------------------------------------------------------------
  if (isUser) {
    const hasCorrections = resolvedCorrectedTerms && resolvedCorrectedTerms.length > 0;

    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex w-full my-2 sm:my-2.5 justify-end"
      >
        <div className="max-w-[88%] sm:max-w-[80%] md:max-w-[72%] flex flex-col items-end">
          
          {/* Corrected Terms Chips / Banner (Rendered above the user bubble) */}
          {hasCorrections && (
            <div className="flex flex-col items-end gap-1.5 mb-2 max-w-full">
              {resolvedCorrectedTerms.map((term, idx) => (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, scale: 0.96 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.15 }}
                  className="inline-flex items-center flex-wrap gap-1.5 px-2.5 py-1 rounded-xl text-xs bg-white/95 border border-slate-200/90 text-slate-700 shadow-2xs backdrop-blur-xs font-normal"
                >
                  <span className="text-slate-500">Considered</span>
                  <span className="font-mono text-slate-600 line-through decoration-slate-400">
                    '{term.original}'
                  </span>
                  <span className="text-slate-500">as</span>
                  <span className="px-1.5 py-0.5 rounded-md bg-yellow-100/90 text-yellow-900 border border-yellow-300/80 font-semibold font-mono text-[11px] shadow-2xs">
                    '{term.corrected}'
                  </span>
                </motion.div>
              ))}
            </div>
          )}

          {/* User Bubble Box */}
          <div
            title={isMeaningfullyDifferent ? `Original: ${rawContent || content}` : undefined}
            className="px-3.5 py-2.5 sm:px-4 sm:py-3 text-sm leading-relaxed shadow-xs transition-colors duration-150 break-words bg-gradient-to-r from-teal-600 to-teal-700 text-white rounded-2xl rounded-br-xs shadow-sm shadow-teal-700/10"
          >
            <div>{displayText}</div>

            {/* Subtle caption if text was interpreted differently and no explicit chips */}
            {isMeaningfullyDifferent && !hasCorrections && (
              <div className="text-[11px] text-teal-100/80 mt-1.5 pt-1.5 border-t border-teal-500/30 flex items-center gap-1 font-normal tracking-wide">
                <span>Heard as: {interpretedText}</span>
              </div>
            )}
          </div>

          {/* Timestamp */}
          {timestamp && (
            <span className="text-[10px] text-slate-400 mt-1 px-1 font-sans">
              {timestamp}
            </span>
          )}
        </div>
      </motion.div>
    );
  }

  // -------------------------------------------------------------
  // STATE 2: Data Unavailable State (Calm, neutral informational bubble)
  // -------------------------------------------------------------
  if (!resolvedDataAvailable) {
    const unavailText =
      resolvedUnavailableMessage ||
      resolvedExplanation ||
      'This information is not tracked in the connected database schema.';

    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex w-full my-2 sm:my-2.5 justify-start"
      >
        <div className="w-full max-w-[96%] sm:max-w-[92%] md:max-w-[88%] flex flex-col items-start">
          <div className="w-full bg-gradient-to-br from-sky-50/95 via-blue-50/70 to-slate-50/90 border border-sky-200/80 rounded-2xl rounded-bl-xs p-3.5 sm:p-4 shadow-2xs backdrop-blur-xs text-slate-800">
            
            {/* Header: Calm info badge and label */}
            <div className="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-sky-200/50">
              <div className="flex items-center gap-2 min-w-0">
                <span className="w-5 h-5 rounded-full bg-sky-200/80 text-sky-800 flex items-center justify-center text-xs font-bold shrink-0">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </span>
                <span className="font-semibold text-xs text-sky-950 uppercase tracking-wider">
                  Information
                </span>
              </div>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-sky-100 text-sky-800 border border-sky-200 shrink-0">
                Data Unavailable in Schema
              </span>
            </div>

            {/* Informational Message Text */}
            <p className="text-xs sm:text-sm text-slate-700 leading-relaxed font-normal">
              {unavailText}
            </p>
          </div>

          {/* Timestamp */}
          {timestamp && (
            <span className="text-[10px] text-slate-400 mt-1 px-1 font-sans">
              {timestamp}
            </span>
          )}
        </div>
      </motion.div>
    );
  }

  // -------------------------------------------------------------
  // STATE 2b: Confirmation Question State (Did you mean...?)
  // -------------------------------------------------------------
  if (resolvedNeedsConfirmation) {
    const confText =
      resolvedConfirmationQuestion ||
      resolvedExplanation ||
      (resolvedSuggestedValue ? `Did you mean '${resolvedSuggestedValue}'?` : 'Please confirm your request.');

    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex w-full my-2 sm:my-2.5 justify-start"
      >
        <div className="w-full max-w-[96%] sm:max-w-[92%] md:max-w-[88%] flex flex-col items-start">
          <div className="w-full bg-indigo-50/90 border border-indigo-200/90 rounded-2xl rounded-bl-xs p-3.5 sm:p-4 shadow-2xs text-indigo-950 backdrop-blur-xs">
            <div className="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-indigo-200/60">
              <div className="flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-indigo-200/80 text-indigo-900 flex items-center justify-center text-xs font-bold shrink-0">
                  ?
                </span>
                <span className="font-bold text-xs uppercase tracking-wider text-indigo-900">
                  Confirmation Required
                </span>
              </div>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-indigo-200/60 text-indigo-800">
                Did You Mean?
              </span>
            </div>
            <p className="text-xs sm:text-sm leading-relaxed text-indigo-950 font-medium whitespace-pre-line">
              {confText}
            </p>
            {resolvedSuggestedValue && (
              <div className="mt-2.5 pt-2 border-t border-indigo-200/50 flex flex-wrap items-center gap-2 text-xs text-indigo-700">
                <span>Suggested match:</span>
                <span className="px-2 py-0.5 rounded-md bg-indigo-100 text-indigo-900 font-semibold font-mono text-[11px] border border-indigo-300">
                  {resolvedSuggestedValue}
                </span>
                <span className="text-[11px] text-indigo-500 italic">(Reply "yes" to view)</span>
              </div>
            )}
          </div>

          {timestamp && (
            <span className="text-[10px] text-slate-400 mt-1 px-1 font-sans">
              {timestamp}
            </span>
          )}
        </div>
      </motion.div>
    );
  }

  // -------------------------------------------------------------
  // STATE 3: Clarification Question State (Amber prompt card)
  // -------------------------------------------------------------
  if (resolvedNeedsClarification) {
    const clarifText =
      resolvedClarificationQuestion ||
      resolvedExplanation ||
      'Could you please clarify your request?';

    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex w-full my-2 sm:my-2.5 justify-start"
      >
        <div className="w-full max-w-[96%] sm:max-w-[92%] md:max-w-[88%] flex flex-col items-start">
          <div className="w-full bg-amber-50/90 border border-amber-200/90 rounded-2xl rounded-bl-xs p-3.5 sm:p-4 shadow-2xs text-amber-950 backdrop-blur-xs">
            <div className="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-amber-200/60">
              <div className="flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-amber-200/80 text-amber-900 flex items-center justify-center text-xs font-bold shrink-0">
                  ?
                </span>
                <span className="font-bold text-xs uppercase tracking-wider text-amber-900">
                  Clarification Required
                </span>
              </div>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-200/60 text-amber-800">
                Ambiguous Query
              </span>
            </div>
            <p className="text-xs sm:text-sm leading-relaxed text-amber-900">
              {clarifText}
            </p>
          </div>

          {/* Timestamp */}
          {timestamp && (
            <span className="text-[10px] text-slate-400 mt-1 px-1 font-sans">
              {timestamp}
            </span>
          )}
        </div>
      </motion.div>
    );
  }

  // -------------------------------------------------------------
  // STATE 4: Normal Answer / Assistant Query Response
  // -------------------------------------------------------------
  const isComplexAnswer = Boolean(resolvedSql || queryData);

  // Simple assistant conversational message (e.g. welcome message, status notice, write execution result)
  if (!isComplexAnswer) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex w-full my-2 sm:my-2.5 justify-start"
      >
        <div className="w-full max-w-full sm:max-w-[96%] md:max-w-[92%] flex flex-col items-start">
          <div className={`px-3.5 py-2.5 sm:px-4 sm:py-3 text-sm leading-relaxed shadow-2xs break-words ${content?.startsWith('⚠️') ? 'bg-amber-50/95 border border-amber-200 text-amber-900 font-medium' : 'bg-white border border-slate-200/80 text-slate-800'} rounded-2xl rounded-bl-xs`}>
            {content}
          </div>
          {children}
          {timestamp && (
            <span className="text-[10px] text-slate-400 mt-1 px-1 font-sans">
              {timestamp}
            </span>
          )}
        </div>
      </motion.div>
    );
  }

  // Assistant query analysis card with SQL drawer trigger, explanation, and results
  const isWriteQuery = queryData?.query_type === 'write';

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex w-full my-2 sm:my-3 justify-start"
    >
      <div className="w-full max-w-full sm:max-w-[96%] md:max-w-[92%] flex flex-col items-start">
        <div className="w-full bg-white/95 border border-slate-200/80 rounded-2xl rounded-bl-xs p-3.5 sm:p-4 shadow-2xs hover:border-slate-300 transition-colors">
          
          {/* Top Meta Bar */}
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2.5 pb-2.5 border-b border-slate-100">
            <div className="flex items-center gap-2 min-w-0">
              <img
                src={logoImg}
                alt="NL2SQL"
                className="w-4 h-4 sm:w-5 sm:h-5 object-contain shrink-0"
              />
              <span className="text-xs font-semibold text-slate-800 truncate">
                Assistant Analysis
              </span>

              {isWriteQuery && (
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 border ${
                  queryData?.status === 'executed' || (!queryData?.isPendingWrite && (queryData?.rows_affected !== undefined || queryData?.result?.length))
                    ? 'bg-emerald-100 text-emerald-900 border-emerald-300'
                    : queryData?.status === 'cancelled'
                    ? 'bg-slate-100 text-slate-700 border-slate-300'
                    : queryData?.status === 'failed'
                    ? 'bg-rose-100 text-rose-900 border-rose-300'
                    : 'bg-amber-100 text-amber-900 border-amber-300'
                }`}>
                  {queryData?.status === 'executed' || (!queryData?.isPendingWrite && (queryData?.rows_affected !== undefined || queryData?.result?.length))
                    ? 'Write Operation (Executed)'
                    : queryData?.status === 'cancelled'
                    ? 'Write Operation (Cancelled)'
                    : queryData?.status === 'failed'
                    ? 'Write Operation (Failed)'
                    : 'Write Operation (Pending)'}
                </span>
              )}
            </div>

            <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
              {/* Confidence Badge */}
              <span className={`inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-0.5 rounded-full text-[11px] sm:text-xs font-medium border ${badgeColorClass}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${badgeDotClass}`}></span>
                {confPercent}% confident
              </span>

              {/* View SQL Drawer Trigger Button (Only when SQL exists) */}
              {resolvedSql && onViewSQL && (
                <button
                  type="button"
                  onClick={() => onViewSQL(queryData || { sql: resolvedSql, explanation: resolvedExplanation })}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-teal-50 hover:bg-teal-100/80 border border-teal-200/70 text-teal-800 text-xs font-semibold transition-all shadow-2xs group min-h-[30px]"
                  title="Inspect generated SQL in sidebar"
                >
                  <svg className="w-3.5 h-3.5 text-teal-600 font-bold shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                  <span>View SQL</span>
                </button>
              )}

              {/* Learn SQL Educational Modal Trigger Button (Only when SQL exists) */}
              {resolvedSql && onLearnSQL && (
                <button
                  type="button"
                  onClick={() =>
                    onLearnSQL({
                      sql: resolvedSql,
                      explanation: resolvedExplanation,
                      queryData,
                      rawContent,
                      content,
                      originalQuestion: originalQuestion || queryData?.user_question,
                      result: (queryData?.result && queryData.result.length > 0) ? queryData.result : [],
                      rows_affected: queryData?.rows_affected,
                      isPendingWrite: isWriteQuery,
                      notice: queryData?.notice,
                    })
                  }
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-indigo-50 hover:bg-indigo-100/80 border border-indigo-200/70 text-indigo-800 text-xs font-semibold transition-all shadow-2xs group min-h-[30px]"
                  title="Learn how your question became SQL"
                >
                  <svg className="w-3.5 h-3.5 text-indigo-600 font-bold shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                  </svg>
                  <span>Learn SQL</span>
                </button>
              )}
            </div>
          </div>

          {/* Execution Status Banner (when confirmed, cancelled, or failed) */}
          {queryData?.executionStatus && (
            <div className={`mb-2.5 p-2.5 rounded-xl text-xs sm:text-sm font-medium border whitespace-pre-line ${
              queryData.status === 'executed'
                ? 'bg-emerald-50/90 text-emerald-900 border-emerald-200'
                : queryData.status === 'failed'
                ? 'bg-rose-50/90 text-rose-900 border-rose-200'
                : 'bg-amber-50/90 text-amber-900 border-amber-200'
            }`}>
              {queryData.executionStatus}
            </div>
          )}

          {/* Explanation Text */}
          {resolvedExplanation ? (
            resolvedExplanation.startsWith('⚠️') ? (
              <div className="p-3 rounded-xl bg-amber-50/90 border border-amber-200 text-amber-900 text-xs sm:text-sm leading-relaxed font-medium whitespace-pre-line">
                {resolvedExplanation}
              </div>
            ) : (
              <p className="text-xs sm:text-sm text-slate-700 leading-relaxed font-normal whitespace-pre-line">
                {resolvedExplanation}
              </p>
            )
          ) : (queryData?.result && queryData.result.length > 0) ? (
            <p className="text-xs sm:text-sm text-slate-700 leading-relaxed font-normal whitespace-pre-line">
              Found {queryData.result.length} matching record{queryData.result.length === 1 ? '' : 's'}.
            </p>
          ) : (
            <p className="text-xs sm:text-sm text-slate-500 italic">
              Query executed successfully.
            </p>
          )}

          {/* Pending Write Operation Action Banner (Confirm & Execute / Cancel) */}
          {isWriteQuery && (queryData?.isPendingWrite || queryData?.status === 'pending') && (
            <div className="mt-3 p-3 rounded-xl bg-amber-50/95 border border-amber-200/90 flex flex-wrap items-center justify-between gap-2.5 shadow-2xs">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
                <span className="text-xs font-semibold text-amber-900">
                  Approval Required: This write query will modify records in your database.
                </span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => onCancelWrite && onCancelWrite(queryData)}
                  className="px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-700 hover:text-slate-900 bg-white hover:bg-slate-100 border border-slate-300 transition-all shadow-2xs cursor-pointer min-h-[30px]"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => onConfirmWrite && onConfirmWrite(queryData)}
                  className="px-3.5 py-1.5 rounded-xl text-xs font-semibold text-white bg-amber-600 hover:bg-amber-700 transition-all shadow-2xs flex items-center gap-1.5 cursor-pointer min-h-[30px]"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                  </svg>
                  <span>Confirm & Execute</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Child Components (e.g. Table / Chart Result Display) */}
        {children}

        {/* Timestamp */}
        {timestamp && (
          <span className="text-[10px] text-slate-400 mt-1 px-1 font-sans">
            {timestamp}
          </span>
        )}
      </div>
    </motion.div>
  );
}
