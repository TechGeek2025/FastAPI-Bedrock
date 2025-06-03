// hooks/useBedrockStream.js
import { useState, useCallback, useRef } from 'react';

/**
 * Simple React hook for Bedrock Agent streaming
 */
export const useBedrockStream = (apiBaseUrl = 'http://localhost:8000') => {
  const [content, setContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState(null);
  
  const abortControllerRef = useRef(null);

  const sendMessage = useCallback(async (inputText, agentId) => {
    setIsStreaming(true);
    setError(null);
    setContent('');
    
    // Create abort controller for cancellation
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch(`${apiBaseUrl}/api/agent/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_text: inputText,
          agent_id: agentId
        }),
        signal: abortControllerRef.current.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n').filter(line => line.trim());

        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            
            if (data.type === 'chunk' && data.accumulated_content) {
              setContent(data.accumulated_content);
            } else if (data.type === 'error') {
              throw new Error(data.error);
            }
          } catch (parseError) {
            // Ignore parse errors, continue with other chunks
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  }, [apiBaseUrl]);

  const stopStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  }, []);

  const reset = useCallback(() => {
    setContent('');
    setError(null);
  }, []);

  return {
    content,
    isStreaming,
    error,
    sendMessage,
    stopStream,
    reset
  };
};

// Example usage component
export const SimpleChatBot = () => {
  const { content, isStreaming, error, sendMessage, stopStream, reset } = useBedrockStream();
  const [input, setInput] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isStreaming) {
      sendMessage(input, 'YOUR_AGENT_ID'); // Replace with your agent ID
      setInput('');
    }
  };

  return (
    <div style={{ maxWidth: '600px', margin: '0 auto', padding: '20px' }}>
      <div style={{ 
        minHeight: '200px', 
        border: '1px solid #ddd', 
        padding: '15px', 
        marginBottom: '15px',
        backgroundColor: '#f9f9f9',
        borderRadius: '8px'
      }}>
        {error && (
          <div style={{ color: 'red', marginBottom: '10px' }}>
            Error: {error}
          </div>
        )}
        
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {content}
          {isStreaming && <span>▌</span>}
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <div style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask your question..."
            disabled={isStreaming}
            style={{
              flex: 1,
              padding: '10px',
              border: '1px solid #ddd',
              borderRadius: '4px'
            }}
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            style={{
              padding: '10px 20px',
              backgroundColor: isStreaming ? '#ccc' : '#007bff',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: isStreaming ? 'not-allowed' : 'pointer'
            }}
          >
            {isStreaming ? 'Streaming...' : 'Send'}
          </button>
          
          {isStreaming && (
            <button
              type="button"
              onClick={stopStream}
              style={{
                padding: '10px 15px',
                backgroundColor: '#dc3545',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              Stop
            </button>
          )}
          
          <button
            type="button"
            onClick={reset}
            disabled={isStreaming}
            style={{
              padding: '10px 15px',
              backgroundColor: '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: isStreaming ? 'not-allowed' : 'pointer'
            }}
          >
            Clear
          </button>
        </div>
      </form>
    </div>
  );
};
