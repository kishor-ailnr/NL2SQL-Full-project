import { useState, useRef, useEffect, startTransition } from 'react';
import { motion } from 'framer-motion';
import MessageBubble from './MessageBubble';
import VoiceButton from './VoiceButton';
import SQLPreviewPanel from './SQLPreviewPanel';
import ChartPanel from './ChartPanel';
import ConfirmModal from './ConfirmModal';
import HistorySidebar from './HistorySidebar';
import SQLDrawer from './SQLDrawer';
import LearnSQLModal from './LearnSQLModal';
import {
  sendQuery,
  confirmWrite,
  createConversation,
  getConversations,
  getConversationMessages,
  deleteConversation,
  getDatabaseSchema,
} from '../api/client';
import { formatAssistantMessage } from '../utils/messageFormatter';
import { AiLoadingState } from './lightswind/ai-loading-state';

const INITIAL_WELCOME = {
  id: 'init-1',
  role: 'assistant',
  content: 'Hello! I am your NL-to-SQL Assistant. Ask me a question about your database in natural language (e.g., "Show all patients older than 40" or "List top 5 products by revenue").',
  timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
};

export default function ChatWindow({ session, onDisconnect }) {
  const sessionId = session?.session_id || 'N/A';
  const tables = session?.tables || [];

  const [messages, setMessages] = useState([INITIAL_WELCOME]);
  const [inputValue, setInputValue] = useState('');
  const [isPending, setIsPending] = useState(false);
  const [showTables, setShowTables] = useState(false);
  const [selectedTable, setSelectedTable] = useState(null);
  const [schemaData, setSchemaData] = useState(session?.schema || session?.schema_info || {});
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Sync or fetch database schema metadata (table columns, types)
  useEffect(() => {
    if (session?.schema && Object.keys(session.schema).length > 0) {
      setSchemaData(session.schema);
    } else if (session?.schema_info && Object.keys(session.schema_info).length > 0) {
      setSchemaData(session.schema_info);
    } else if (sessionId && sessionId !== 'N/A') {
      getDatabaseSchema(sessionId)
        .then((data) => {
          if (data?.schema && Object.keys(data.schema).length > 0) {
            setSchemaData(data.schema);
          }
        })
        .catch((err) => {
          console.warn('Could not prefetch database schema:', err.message);
        });
    }
  }, [sessionId, session]);

  // Handle clicking on an individual table pill to toggle its headers/columns
  const handleToggleTable = async (tableName) => {
    if (selectedTable === tableName) {
      // Toggle closed if clicked again
      setSelectedTable(null);
      return;
    }

    setSelectedTable(tableName);

    // If columns for this table are not yet cached in state, fetch them
    if (!schemaData[tableName] && sessionId && sessionId !== 'N/A') {
      setSchemaLoading(true);
      try {
        const data = await getDatabaseSchema(sessionId);
        if (data?.schema) {
          setSchemaData(data.schema);
        }
      } catch (err) {
        console.warn('Failed to fetch schema for table:', tableName, err.message);
      } finally {
        setSchemaLoading(false);
      }
    }
  };

  // Active columns for currently selected table
  const activeTableColumns = (schemaData?.[selectedTable] || []).map((col) => {
    if (typeof col === 'string') {
      return { name: col, type: 'TEXT', primary_key: false };
    }
    return {
      name: col.name || col.column_name || String(col),
      type: col.type || 'TEXT',
      primary_key: Boolean(col.primary_key),
      nullable: col.nullable !== false,
    };
  });

  // Multi-conversation state
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [conversationsError, setConversationsError] = useState(null);

  // SQL Drawer state (right-side slide-in)
  const [activeSQLQuery, setActiveSQLQuery] = useState(null);
  const [isSQLDrawerOpen, setIsSQLDrawerOpen] = useState(false);

  // Learn SQL Modal state (educational dialog)
  const [activeLearnSQLData, setActiveLearnSQLData] = useState(null);
  const [isLearnSQLModalOpen, setIsLearnSQLModalOpen] = useState(false);

  // Confirm Modal state for Write operations
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [pendingWriteQuery, setPendingWriteQuery] = useState(null);

  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const isSendingRef = useRef(false);

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isPending]);

  // Auto-resize textarea to fit multiline content up to max-height without synchronous layout thrashing
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    if (typeof CSS !== 'undefined' && CSS.supports && CSS.supports('field-sizing', 'content')) {
      return;
    }
    requestAnimationFrame(() => {
      if (!el) return;
      el.style.height = 'auto';
      const targetHeight = Math.min(el.scrollHeight, 140);
      el.style.height = `${Math.max(38, targetHeight)}px`;
    });
  }, [inputValue]);

  // Load conversations on session mount
  const fetchConversations = async (autoSelect = false) => {
    if (!sessionId || sessionId === 'N/A') return;
    setConversationsLoading(true);
    setConversationsError(null);
    try {
      const data = await getConversations(sessionId);
      const convList = data?.conversations || [];
      setConversations(convList);

      if (autoSelect) {
        if (convList.length > 0) {
          handleSelectConversation(convList[0].conversation_id);
        } else {
          handleNewChat();
        }
      }
    } catch (err) {
      console.warn('Failed to fetch conversations:', err.message);
      setConversationsError('Could not load chat history.');
    } finally {
      setConversationsLoading(false);
    }
  };

  useEffect(() => {
    fetchConversations(true);
  }, [sessionId]);

  // Handler for creating a fresh conversation
  const handleNewChat = async () => {
    if (!sessionId || sessionId === 'N/A') return;
    try {
      const res = await createConversation(sessionId);
      if (res?.conversation_id) {
        setActiveConversationId(res.conversation_id);
        setMessages([
          {
            ...INITIAL_WELCOME,
            id: `init-${Date.now()}`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
        setConversations((prev) => [
          {
            conversation_id: res.conversation_id,
            title: 'New Chat',
            created_at: res.created_at,
          },
          ...prev.filter((c) => c.conversation_id !== res.conversation_id),
        ]);
      }
    } catch (err) {
      console.warn('Failed to create new conversation:', err.message);
    }
  };

  // Handler for switching to an existing conversation
  const handleSelectConversation = async (convId) => {
    if (!convId) return;
    setActiveConversationId(convId);
    try {
      const data = await getConversationMessages(convId);
      const msgList = data?.messages || [];

      if (msgList.length === 0) {
        setMessages([
          {
            ...INITIAL_WELCOME,
            id: `init-${Date.now()}`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
        return;
      }

      const formatted = [];
      msgList.forEach((m, idx) => {
        // User question message
        formatted.push({
          id: `user-${convId}-${idx}`,
          role: 'user',
          content: m.nl_query,
          raw_content: m.nl_query,
          interpreted_text: null,
          timestamp: m.timestamp,
        });

        // Assistant query response message formatted with shared function
        formatted.push(
          formatAssistantMessage(m, m.nl_query, `asst-${convId}-${idx}`, m.timestamp)
        );
      });

      setMessages(formatted);
    } catch (err) {
      console.warn('Failed to load conversation messages:', err.message);
    }
  };

  // Handler for deleting a conversation
  const handleDeleteConversation = async (convId) => {
    if (!convId) return;
    try {
      await deleteConversation(convId);
      // Immediately remove from sidebar list
      setConversations((prev) => prev.filter((c) => c.conversation_id !== convId));

      // If the deleted conversation was the active one, reset to clean new-chat state
      if (convId === activeConversationId) {
        setActiveConversationId(null);
        setMessages([
          {
            ...INITIAL_WELCOME,
            id: `init-${Date.now()}`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
        setInputValue('');
      }
    } catch (err) {
      console.warn('Failed to delete conversation:', err.message);
    }
  };

  const handleOpenSQL = (queryData) => {
    setActiveSQLQuery(queryData);
    setIsSQLDrawerOpen(true);
  };

  const handleOpenLearnSQL = (learnData) => {
    setActiveLearnSQLData(learnData);
    setIsLearnSQLModalOpen(true);
  };

  const handleSend = async (e) => {
    if (e) e.preventDefault();
    const text = inputValue.trim();
    if (!text || isPending || isSendingRef.current) return;
    isSendingRef.current = true;

    let targetConvId = activeConversationId;
    if (!targetConvId) {
      try {
        const newConv = await createConversation(sessionId);
        targetConvId = newConv.conversation_id;
        setActiveConversationId(targetConvId);
      } catch (convErr) {
        console.warn('Failed to initialize conversation before send:', convErr);
      }
    }

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const userMsgId = `user-${Date.now()}`;
    const userMessage = {
      id: userMsgId,
      role: 'user',
      content: text,
      raw_content: text,
      interpreted_text: null,
      timestamp: timeStr,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsPending(true);

    try {
      const queryResponse = await sendQuery({
        session_id: sessionId,
        conversation_id: targetConvId,
        text,
        language: 'auto',
      });

      // Update matching user message with interpreted_text and corrected_terms if returned
      if (
        queryResponse?.interpreted_text ||
        (queryResponse?.corrected_terms && queryResponse.corrected_terms.length > 0)
      ) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === userMsgId
              ? {
                  ...msg,
                  interpreted_text: queryResponse.interpreted_text || msg.interpreted_text,
                  corrected_terms: queryResponse.corrected_terms || [],
                }
              : msg
          )
        );
      }

      const isWrite = queryResponse.query_type === 'write';
      const assistantMessage = formatAssistantMessage(
        {
          ...queryResponse,
          isPendingWrite: isWrite,
          status: isWrite ? 'pending' : undefined,
        },
        text,
        `asst-${Date.now()}`,
        timeStr
      );

      setMessages((prev) => {
        if (queryResponse?.query_id && prev.some((m) => m.queryData?.query_id === queryResponse.query_id)) {
          return prev;
        }
        return [...prev, assistantMessage];
      });

      if (isWrite) {
        setPendingWriteQuery({
          ...queryResponse,
          user_question: text,
        });
        setIsModalOpen(true);
      }

      // Refresh conversations list to show updated title
      fetchConversations(false);
    } catch (err) {
      console.warn('sendQuery API error:', err.message);
      const errorMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: `❌ ${err.message}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsPending(false);
      isSendingRef.current = false;
    }
  };

  const handleConfirmWrite = async (targetQuery = pendingWriteQuery) => {
    const activeQuery = targetQuery || pendingWriteQuery;
    const queryId = activeQuery?.query_id;
    if (!queryId) return;

    try {
      const res = await confirmWrite({
        session_id: sessionId,
        query_id: queryId,
        confirmed: true,
      });

      startTransition(() => {
        setIsModalOpen(false);

        if (res?.status === 'error') {
          const errContent = `❌ Write Execution Failed: ${res?.error || 'Database operation failed.'}`;
          setMessages((prev) =>
            prev.map((msg) => {
              const isTarget =
                msg.queryData?.query_id === queryId ||
                (msg.role === 'assistant' && msg.queryData?.query_type === 'write' && msg.queryData?.isPendingWrite);
              if (!isTarget) return msg;

              return {
                ...msg,
                content: errContent,
                queryData: {
                  ...msg.queryData,
                  status: 'failed',
                  isPendingWrite: false,
                  executionStatus: errContent,
                  rows_affected: 0,
                  result: [],
                  error: res?.error,
                },
              };
            })
          );
          setPendingWriteQuery(null);
          return;
        }

        let statusContent = `✅ Executed — ${res?.rows_affected ?? 0} row${res?.rows_affected === 1 ? '' : 's'} affected.`;
        if (res?.rows_affected === 0) {
          statusContent = res?.notice 
            ? `⚠️ ${res.notice}` 
            : '⚠️ Executed — 0 rows affected. No matching record was found to update.';
        } else if (res?.notice) {
          statusContent = `✅ Executed — ${res.rows_affected} row${res.rows_affected === 1 ? '' : 's'} affected.\n⚠️ ${res.notice}`;
        }

        // Update the existing pending message in place rather than appending a duplicate card
        setMessages((prev) =>
          prev.map((msg) => {
            const isTarget =
              msg.queryData?.query_id === queryId ||
              (msg.role === 'assistant' && msg.queryData?.query_type === 'write' && msg.queryData?.isPendingWrite);
            if (!isTarget) return msg;

            return {
              ...msg,
              content: statusContent,
              queryData: {
                ...msg.queryData,
                status: 'executed',
                isPendingWrite: false,
                executionStatus: statusContent,
                rows_affected: res?.rows_affected,
                result: res?.result || [],
                chart_type: res?.chart_type || (res?.result?.length ? 'table' : 'none'),
                notice: res?.notice,
              },
            };
          })
        );
        setPendingWriteQuery(null);
      });
    } catch (err) {
      console.warn('confirmWrite API error:', err.message);
      startTransition(() => {
        setIsModalOpen(false);
        const errContent = `❌ Write Execution Failed: ${err.message}`;
        setMessages((prev) =>
          prev.map((msg) => {
            const isTarget =
              msg.queryData?.query_id === queryId ||
              (msg.role === 'assistant' && msg.queryData?.query_type === 'write' && msg.queryData?.isPendingWrite);
            if (!isTarget) return msg;

            return {
              ...msg,
              content: errContent,
              queryData: {
                ...msg.queryData,
                status: 'failed',
                isPendingWrite: false,
                executionStatus: errContent,
              },
            };
          })
        );
        setPendingWriteQuery(null);
      });
    }
  };

  const handleCancelWrite = async (targetQuery = pendingWriteQuery) => {
    const activeQuery = targetQuery || pendingWriteQuery;
    const queryId = activeQuery?.query_id;
    if (queryId) {
      try {
        await confirmWrite({
          session_id: sessionId,
          query_id: queryId,
          confirmed: false,
        });
      } catch (err) {
        console.warn('cancel confirmWrite notification failed:', err.message);
      }
    }

    startTransition(() => {
      setIsModalOpen(false);
      const cancelContent = '⚠️ Query cancelled. No changes were made to the database.';
      setMessages((prev) =>
        prev.map((msg) => {
          const isTarget =
            msg.queryData?.query_id === queryId ||
            (msg.role === 'assistant' && msg.queryData?.query_type === 'write' && msg.queryData?.isPendingWrite);
          if (!isTarget) return msg;

          return {
            ...msg,
            content: cancelContent,
            queryData: {
              ...msg.queryData,
              status: 'cancelled',
              isPendingWrite: false,
              executionStatus: cancelContent,
            },
          };
        })
      );
      setPendingWriteQuery(null);
    });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(e);
    }
  };

  const handleVoiceComplete = (transcript) => {
    if (!transcript) return;
    setInputValue(transcript);
  };

  return (
    <div className="w-full h-full flex flex-col min-h-0 overflow-hidden bg-[#F8FAFB]">
      
      {/* History Drawer Component (Left Slide-in) */}
      <HistorySidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        conversations={conversations}
        activeConversationId={activeConversationId}
        loading={conversationsLoading}
        error={conversationsError}
        onRefresh={() => fetchConversations(false)}
        onNewChat={handleNewChat}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={handleDeleteConversation}
      />

      {/* SQL Drawer Component (Right Slide-in) */}
      <SQLDrawer
        queryData={activeSQLQuery}
        isOpen={isSQLDrawerOpen}
        onClose={() => setIsSQLDrawerOpen(false)}
      />

      {/* Compact Database & Session Toolbar (Desktop & Mobile-adapted) */}
      <div className="w-full border-b border-slate-200/80 bg-white/95 backdrop-blur-md shrink-0 px-3 sm:px-6 md:px-8 py-2 sm:py-2.5 z-10 shadow-2xs">
        <div className="flex items-center justify-between gap-2 overflow-x-auto no-scrollbar py-0.5">
          
          <div className="flex items-center gap-1.5 sm:gap-2.5 shrink-0 flex-nowrap">
            {/* History Toggle Button */}
            <button
              type="button"
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className="px-2.5 py-1.5 rounded-xl bg-white hover:bg-slate-50 border border-slate-200/90 text-slate-700 text-xs font-semibold flex items-center gap-1.5 shadow-2xs transition-all hover:border-teal-300 min-h-[36px]"
              title="Toggle Chat History"
            >
              <svg className="w-4 h-4 text-teal-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <span className="hidden sm:inline">Chats</span>
              {conversations.length > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 text-slate-600 font-mono">
                  {conversations.length}
                </span>
              )}
            </button>

            {/* + New Chat Quick Button */}
            <button
              type="button"
              onClick={handleNewChat}
              className="px-2.5 py-1.5 rounded-xl bg-teal-50 hover:bg-teal-100 text-teal-700 border border-teal-200/80 text-xs font-semibold flex items-center gap-1.5 shadow-2xs transition-all hover:border-teal-300 active:scale-95 min-h-[36px]"
              title="Start a new chat"
            >
              <svg className="w-3.5 h-3.5 text-teal-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M12 4v16m8-8H4" />
              </svg>
              <span className="whitespace-nowrap">New Chat</span>
            </button>

            <div className="h-4 w-px bg-slate-200 mx-0.5 hidden sm:block shrink-0" />

            {/* Status Badge */}
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] sm:text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200 shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                <span>Connected</span>
              </span>
              <span className="text-[11px] text-slate-400 font-mono hidden md:inline truncate max-w-[130px]" title={sessionId}>
                {sessionId}
              </span>
            </div>

            {/* Toggleable Table List Pills */}
            <button
              type="button"
              onClick={() => {
                setShowTables((prev) => {
                  const next = !prev;
                  if (!next) setSelectedTable(null);
                  return next;
                });
              }}
              className="text-xs font-medium text-teal-700 hover:text-teal-900 flex items-center gap-1 bg-teal-50/60 hover:bg-teal-100/70 px-2.5 py-1 rounded-lg border border-teal-200/60 transition-colors shrink-0 min-h-[32px] cursor-pointer"
              title="Toggle database table list"
            >
              <span className="whitespace-nowrap">{tables.length} tables</span>
              <svg className={`w-3.5 h-3.5 transition-transform duration-150 ${showTables ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          </div>

          {/* Disconnect Button */}
          <button
            onClick={onDisconnect}
            className="px-2.5 sm:px-3 py-1.5 text-xs font-semibold text-slate-600 hover:text-rose-700 bg-white hover:bg-rose-50 border border-slate-200 hover:border-rose-200 rounded-xl transition-all flex items-center gap-1.5 shadow-2xs shrink-0 min-h-[36px]"
            title="Disconnect from database"
          >
            <svg className="w-3.5 h-3.5 text-rose-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            <span className="hidden sm:inline">Disconnect</span>
          </button>
        </div>

        {/* Collapsible Tables Drawer & Headers */}
        {showTables && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className="mt-2.5 pt-2 border-t border-slate-100 flex flex-col gap-2.5"
          >
            {/* Table Name Chips (Clickable to view/hide headers) */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mr-1">
                Tables:
              </span>
              {tables.map((table, idx) => {
                const isSelected = selectedTable === table;
                const colCount = schemaData?.[table]?.length;

                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleToggleTable(table)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-all flex items-center gap-1.5 shadow-2xs cursor-pointer border ${
                      isSelected
                        ? 'bg-teal-600 text-white border-teal-700 shadow-xs ring-2 ring-teal-500/25 font-semibold'
                        : 'bg-white hover:bg-teal-50/80 text-slate-700 hover:text-teal-900 border-slate-200 hover:border-teal-300'
                    }`}
                    title={isSelected ? `Click to hide headers of ${table}` : `Click to view headers of ${table}`}
                  >
                    {/* Database Table Icon */}
                    <svg
                      className={`w-3.5 h-3.5 shrink-0 ${isSelected ? 'text-teal-100' : 'text-slate-400'}`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="2"
                        d="M3 10h18M3 14h18m-9-4v8m-7 4h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                      />
                    </svg>
                    <span>{table}</span>
                    {typeof colCount === 'number' && colCount > 0 && (
                      <span
                        className={`text-[10px] px-1.5 py-0.2 rounded-full font-sans font-medium ${
                          isSelected
                            ? 'bg-teal-700/90 text-teal-100'
                            : 'bg-slate-100 text-slate-500'
                        }`}
                      >
                        {colCount}
                      </span>
                    )}
                    {/* Dropdown Caret */}
                    <svg
                      className={`w-3 h-3 transition-transform duration-150 ${
                        isSelected ? 'rotate-180 text-white' : 'text-slate-400'
                      }`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                );
              })}
            </div>

            {/* Expanded Table Headers / Columns Section */}
            {selectedTable && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.15 }}
                className="p-3 rounded-xl bg-gradient-to-r from-slate-50 via-teal-50/40 to-slate-50 border border-teal-200/80 shadow-2xs backdrop-blur-xs"
              >
                <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-teal-100">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="w-2 h-2 rounded-full bg-teal-500 animate-pulse"></span>
                    <span className="text-xs font-semibold text-slate-800">
                      Headers of table <span className="font-mono text-teal-700 font-bold bg-teal-100/70 px-1.5 py-0.5 rounded text-[11px]">{selectedTable}</span>:
                    </span>
                    <span className="text-[11px] text-slate-500 font-sans">
                      ({activeTableColumns.length} {activeTableColumns.length === 1 ? 'header' : 'headers'})
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => setSelectedTable(null)}
                    className="text-[11px] font-semibold text-slate-500 hover:text-slate-800 flex items-center gap-1 px-2 py-0.5 rounded-md hover:bg-slate-200/60 transition-colors"
                    title="Close table headers"
                  >
                    <span>Close</span>
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {schemaLoading ? (
                  <div className="flex items-center gap-2 py-2 text-xs text-slate-500">
                    <span className="w-3.5 h-3.5 border-2 border-teal-600 border-t-transparent rounded-full animate-spin"></span>
                    <span>Loading headers...</span>
                  </div>
                ) : activeTableColumns.length === 0 ? (
                  <p className="text-xs text-slate-500 italic py-1">
                    No headers found for table '{selectedTable}'.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto pt-0.5">
                    {activeTableColumns.map((col, cIdx) => (
                      <div
                        key={cIdx}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-white border border-slate-200/90 hover:border-teal-400 hover:shadow-2xs transition-all select-all font-mono"
                        title={`${col.name} (${col.type})${col.primary_key ? ' - Primary Key' : ''}`}
                      >
                        <span className="font-semibold text-slate-800 text-[11px]">
                          {col.name}
                        </span>
                        <span className="text-[9px] font-sans font-bold uppercase px-1.5 py-0.2 rounded bg-slate-100 text-slate-500 border border-slate-200/60">
                          {col.type}
                        </span>
                        {col.primary_key && (
                          <span
                            className="text-[9px] font-sans font-bold px-1.5 py-0.2 rounded bg-amber-100 text-amber-800 border border-amber-300"
                            title="Primary Key"
                          >
                            PK
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            )}
          </motion.div>
        )}
      </div>

      {/* Scrollable Message List (Full Height, Independent Scrolling) */}
      <div className="flex-1 min-h-0 overflow-y-auto w-full">
        <div className="w-full max-w-4xl lg:max-w-5xl mx-auto px-3 sm:px-6 md:px-8 py-4 sm:py-6 space-y-4">
          {messages.map((msg) => {
            if (msg.role === 'user') {
              return (
                <MessageBubble
                  key={msg.id}
                  role="user"
                  content={msg.content}
                  rawContent={msg.raw_content || msg.content}
                  interpretedText={msg.interpreted_text}
                  correctedTerms={msg.corrected_terms}
                  timestamp={msg.timestamp}
                />
              );
            }

            if (msg.queryData) {
              const isUnavailable = msg.queryData.data_available === false;
              const isConfirmation = msg.queryData.needs_confirmation;
              const isClarif = msg.queryData.needs_clarification;

              return (
                <MessageBubble
                  key={msg.id}
                  role="assistant"
                  queryData={msg.queryData}
                  content={msg.queryData.explanation || msg.queryData.unavailable_message}
                  dataAvailable={msg.queryData.data_available}
                  unavailableMessage={msg.queryData.unavailable_message}
                  needsConfirmation={isConfirmation}
                  confirmationQuestion={msg.queryData.confirmation_question}
                  suggestedValue={msg.queryData.suggested_value}
                  needsClarification={isClarif}
                  clarificationQuestion={msg.queryData.clarification_question}
                  confidence={msg.queryData.confidence}
                  sql={msg.queryData.sql}
                  originalQuestion={msg.userQuestion || msg.queryData?.user_question}
                  onViewSQL={handleOpenSQL}
                  onLearnSQL={handleOpenLearnSQL}
                  onConfirmWrite={handleConfirmWrite}
                  onCancelWrite={handleCancelWrite}
                  timestamp={msg.timestamp}
                >
                  {/* Table / Chart Result Display: when data is available, not clarification, not confirmation, and results exist */}
                  {!isClarif && !isConfirmation && !isUnavailable && msg.queryData.result && msg.queryData.result.length > 0 && (
                    <ChartPanel
                      result={msg.queryData.result}
                      chart_type={msg.queryData.chart_type || 'table'}
                    />
                  )}
                </MessageBubble>
              );
            }

            // Execution messages or general assistant messages with result table
            const hasDirectResults = Array.isArray(msg.result) && msg.result.length > 0;
            return (
              <MessageBubble
                key={msg.id}
                role="assistant"
                content={msg.content}
                sql={msg.sql}
                originalQuestion={msg.userQuestion || msg.queryData?.user_question}
                queryData={msg.queryData}
                onViewSQL={msg.sql ? handleOpenSQL : undefined}
                onLearnSQL={msg.sql ? handleOpenLearnSQL : undefined}
                onConfirmWrite={handleConfirmWrite}
                onCancelWrite={handleCancelWrite}
                timestamp={msg.timestamp}
              >
                {hasDirectResults && (
                  <div className="w-full mt-3">
                    <ChartPanel
                      result={msg.result}
                      chart_type={msg.chart_type || 'table'}
                    />
                  </div>
                )}
              </MessageBubble>
            );
          })}

          {/* Lightswind UI AI Loading State Indicator */}
          {isPending && (
            <motion.div
              initial={{ opacity: 0, y: 8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.2 }}
              className="flex w-full my-3 justify-start"
            >
              <AiLoadingState
                label="Analyzing & thinking..."
                sublabel="Translating question & verifying SQL"
                variant="PulseBeam"
                theme="glass"
                size="md"
                showTimer={true}
                showBadge={true}
                className="bg-white/95 text-teal-900 border-teal-200/80 shadow-2xs hover:border-teal-300"
              />
            </motion.div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Centered Static Bottom Search Bar (No surrounding background layout) */}
      <div className="w-full shrink-0 z-20 flex justify-center px-4 pt-1 pb-[max(1rem,env(safe-area-inset-bottom))] bg-transparent">
        <div className="w-full max-w-3xl lg:max-w-4xl">
          <form onSubmit={handleSend} className="w-full">
            <div className="flex items-center gap-2 p-1.5 sm:p-2 bg-white border border-slate-200/90 hover:border-slate-300 focus-within:border-teal-500/80 focus-within:ring-2 focus-within:ring-teal-500/20 rounded-full shadow-sm sm:shadow-md transition-all">
              
              {/* Text Input / Multiline Textarea */}
              <textarea
                ref={textareaRef}
                rows={1}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question about your database in natural language..."
                disabled={isPending}
                className="flex-1 max-h-32 min-h-[38px] px-3 sm:px-4 py-2 text-sm text-slate-800 placeholder-slate-400 bg-transparent resize-none focus:outline-none disabled:opacity-60 leading-normal font-sans"
              />

              {/* Voice Button */}
              <div className="shrink-0 flex items-center justify-center">
                <VoiceButton
                  onTranscript={handleVoiceComplete}
                  onRecordingComplete={handleVoiceComplete}
                  disabled={isPending}
                />
              </div>

              {/* Send Button */}
              <button
                type="submit"
                disabled={!inputValue.trim() || isPending}
                className="min-h-[40px] sm:min-h-[44px] px-4 sm:px-5 py-2 sm:py-2.5 rounded-full bg-teal-600 hover:bg-teal-700 text-white font-medium text-xs sm:text-sm shadow-sm transition-all flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed shrink-0 active:scale-95"
                title="Send message (Enter)"
              >
                <span>Send</span>
                <svg className="w-4 h-4 rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>

            </div>
          </form>
        </div>
      </div>

      {/* SQL Drawer Slide-in */}
      <SQLDrawer
        isOpen={isSQLDrawerOpen}
        queryData={activeSQLQuery}
        onClose={() => setIsSQLDrawerOpen(false)}
      />

      {/* Learn SQL Educational Modal */}
      <LearnSQLModal
        isOpen={isLearnSQLModalOpen}
        data={activeLearnSQLData}
        onClose={() => setIsLearnSQLModalOpen(false)}
      />

      {/* Confirm Modal Overlay for Write Operations */}
      <ConfirmModal
        isOpen={isModalOpen}
        sql={pendingWriteQuery?.sql}
        explanation={pendingWriteQuery?.explanation}
        onConfirm={handleConfirmWrite}
        onCancel={handleCancelWrite}
      />
    </div>
  );
}
