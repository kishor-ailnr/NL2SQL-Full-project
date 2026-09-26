/**
 * messageFormatter.js
 * -------------------
 * Single unified formatter function for query responses.
 *
 * Used by BOTH:
 * 1. Live query send path (handleSend in ChatWindow.jsx)
 * 2. History reload path (loadConversationMessages in ChatWindow.jsx)
 *
 * Ensures consistent rendering decisions across:
 * - result table
 * - clarification question
 * - confirmation ("did you mean?") question
 * - data unavailable card
 * - plain text / write operations
 */

export function formatAssistantMessage(item, userQuestion = '', customId = null, timestamp = null) {
  if (!item) return null;

  const isUnavailable =
    item.data_available === false ||
    item.query_type === 'unavailable' ||
    Boolean(item.unavailable_message);

  const isConfirmation =
    !isUnavailable &&
    (Boolean(item.needs_confirmation) ||
      item.query_type === 'confirmation' ||
      Boolean(item.confirmation_question));

  const isClarification =
    !isUnavailable &&
    !isConfirmation &&
    (Boolean(item.needs_clarification) ||
      item.query_type === 'clarification' ||
      Boolean(item.clarification_question) ||
      (!item.sql && Boolean(item.explanation) && (!item.result || item.result.length === 0)));

  const isWrite = item.query_type === 'write';
  const hasResults = Array.isArray(item.result) && item.result.length > 0;

  // Decide renderType
  let renderType = 'result';
  if (isUnavailable) {
    renderType = 'unavailable';
  } else if (isConfirmation) {
    renderType = 'confirmation';
  } else if (isClarification) {
    renderType = 'clarification';
  } else if (isWrite) {
    renderType = 'write';
  } else if (!item.sql && !hasResults) {
    renderType = 'plain_text';
  }

  // Consistent resolved text content
  const confirmationText =
    item.confirmation_question ||
    (isConfirmation ? (item.explanation || (item.suggested_value ? `Did you mean '${item.suggested_value}'? Reply yes to see that record.` : '')) : '');

  const clarificationText =
    item.clarification_question ||
    (isClarification ? item.explanation : '');

  const unavailableText =
    item.unavailable_message ||
    (isUnavailable ? (item.explanation || 'This information is not tracked in the connected database schema.') : '');

  const explanation =
    (isConfirmation ? confirmationText : null) ||
    (isClarification ? clarificationText : null) ||
    (isUnavailable ? unavailableText : null) ||
    item.explanation ||
    (hasResults ? `Found ${item.result.length} matching record${item.result.length === 1 ? '' : 's'}.` : '');

  const resolvedTime =
    timestamp ||
    item.timestamp ||
    new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const queryData = {
    ...item,
    query_id: item.query_id || customId || `msg-${Date.now()}`,
    user_question: userQuestion || item.user_question || item.nl_query || '',
    query_type: item.query_type || (isUnavailable ? 'unavailable' : isConfirmation ? 'confirmation' : isClarification ? 'clarification' : isWrite ? 'write' : 'select'),
    sql: (isUnavailable || isClarification || isConfirmation) ? null : (item.sql || null),
    explanation,
    result: item.result || [],
    chart_type: item.chart_type || 'none',
    confidence: item.confidence !== undefined ? item.confidence : (isClarification ? 0.3 : isConfirmation ? 0.85 : 1.0),
    data_available: !isUnavailable,
    unavailable_message: isUnavailable ? unavailableText : null,
    needs_confirmation: isConfirmation,
    confirmation_question: isConfirmation ? confirmationText : null,
    suggested_value: item.suggested_value || null,
    needs_clarification: isClarification,
    clarification_question: isClarification ? clarificationText : null,
    isPendingWrite: isWrite && item.status !== 'executed' && item.status !== 'cancelled' && item.status !== 'failed',
    status: item.status || (isWrite ? (item.isPendingWrite === false ? 'executed' : 'pending') : undefined),
    corrected_terms: item.corrected_terms || [],
    renderType,
  };

  return {
    id: customId || `asst-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    role: 'assistant',
    userQuestion: userQuestion || item.user_question || item.nl_query || '',
    queryData,
    content: explanation,
    timestamp: resolvedTime,
    renderType,
  };
}
