export const conversationTurnCount = (conversation) => {
  const explicitTurnCount = Number(conversation?.turn_count);
  if (Number.isFinite(explicitTurnCount) && explicitTurnCount >= 0) {
    return explicitTurnCount;
  }

  if (Array.isArray(conversation?.messages)) {
    const userTurns = conversation.messages.filter((message) => message?.role === 'user').length;
    if (userTurns > 0) return userTurns;
    return Math.ceil(conversation.messages.length / 2);
  }

  const messageCount = Number(conversation?.message_count) || 0;
  return Math.ceil(messageCount / 2);
};

export const formatTurnCount = (conversation) => {
  const turns = conversationTurnCount(conversation);
  return `${turns} turn${turns === 1 ? '' : 's'}`;
};
