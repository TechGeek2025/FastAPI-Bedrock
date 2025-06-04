from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import boto3
import json
import logging
from typing import Generator
from pydantic import BaseModel
import asyncio
import threading
from queue import Queue

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bedrock Agent Streaming API")

# Pydantic models for request/response
class ChatRequest(BaseModel):
    message: str
    agent_id: str
    agent_alias_id: str = "TSTALIASID"  # Default test alias
    session_id: str = "default-session"

class BedrockAgentClient:
    def __init__(self):
        # Initialize Bedrock Agent Runtime client
        # ECS task role should have bedrock:InvokeAgent permissions
        self.client = boto3.client('bedrock-agent-runtime')
    
    def invoke_agent_stream(self, agent_id: str, agent_alias_id: str, 
                          session_id: str, input_text: str) -> Generator[str, None, None]:
        """
        Invoke Bedrock agent and yield streaming responses
        """
        try:
            response = self.client.invoke_agent(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
                sessionId=session_id,
                inputText=input_text
            )
            
            # Process the streaming response
            event_stream = response['completion']
            
            for event in event_stream:
                if 'chunk' in event:
                    chunk = event['chunk']
                    if 'bytes' in chunk:
                        # Decode the bytes and yield as JSON
                        chunk_text = chunk['bytes'].decode('utf-8')
                        yield json.dumps({'text': chunk_text, 'type': 'content'}) + '\n'
                
                elif 'trace' in event:
                    # Handle trace events (optional - for debugging)
                    trace = event['trace']
                    logger.info(f"Trace event: {trace}")
                    yield json.dumps({'trace': str(trace), 'type': 'trace'}) + '\n'
                
                elif 'returnControl' in event:
                    # Handle return control events
                    control = event['returnControl']
                    yield json.dumps({'control': control, 'type': 'control'}) + '\n'
                
        except Exception as e:
            logger.error(f"Error invoking Bedrock agent: {str(e)}")
            yield json.dumps({'error': str(e), 'type': 'error'}) + '\n'

# Initialize Bedrock client
bedrock_client = BedrockAgentClient()

@app.get("/health")
async def health_check():
    """Health check endpoint for ECS"""
    return {"status": "healthy", "service": "bedrock-agent-api"}

@app.post("/chat")
async def stream_chat(request: ChatRequest):
    """
    Stream chat responses from Bedrock agent
    """
    try:
        def generate_response():
            # Add start signal
            yield json.dumps({"type": "start", "message": "Starting conversation with agent"}) + '\n'
            
            # Stream responses from Bedrock agent
            for chunk in bedrock_client.invoke_agent_stream(
                agent_id=request.agent_id,
                agent_alias_id=request.agent_alias_id,
                session_id=request.session_id,
                input_text=request.message
            ):
                yield chunk
            
            # Send end signal
            yield json.dumps({"type": "end", "message": "Conversation completed"}) + '\n'
        
        return StreamingResponse(
            generate_response(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )
    
    except Exception as e:
        logger.error(f"Error in stream_chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



# For testing purposes
@app.get("/")
async def root():
    return {
        "message": "Bedrock Agent Streaming API",
        "endpoints": {
            "health": "/health",
            "stream_chat": "POST /chat"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
