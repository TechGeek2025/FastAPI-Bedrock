# FastAPI ECS Service for Bedrock Agent Streaming (Production Ready)

## requirements.txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
boto3==1.34.0
python-multipart==0.0.6
python-dotenv==1.0.0

## app.py
import json
import logging
import asyncio
import time
import uuid
from typing import AsyncGenerator, Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import boto3
from botocore.exceptions import ClientError, BotoCoreError
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d'
)
logger = logging.getLogger(__name__)

# Global variables for AWS clients
bedrock_agent_runtime = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global bedrock_agent_runtime
    
    # Startup
    logger.info("Application starting up")
    try:
        bedrock_agent_runtime = boto3.client(
            'bedrock-agent-runtime',
            region_name=os.getenv('AWS_REGION', 'us-east-1')
        )
        logger.info("Bedrock Agent Runtime client initialized successfully")
        
        # Test credentials on startup
        await validate_aws_credentials()
        
    except Exception as e:
        logger.error(f"Failed to initialize Bedrock client: {e}")
        
    yield
    
    # Shutdown
    logger.info("Application shutting down")

async def validate_aws_credentials():
    """Validate AWS credentials and Bedrock access on startup"""
    try:
        # Test STS to verify credentials
        sts_client = boto3.client('sts', region_name=os.getenv('AWS_REGION', 'us-east-1'))
        identity = sts_client.get_caller_identity()
        
        logger.info(f"AWS credentials valid - Account: {identity['Account']}, ARN: {identity['Arn']}")
        
        # Note: We can't easily test Bedrock without a real agent ID
        # But STS test confirms credentials are working
        
    except Exception as e:
        logger.error(f"AWS credential validation failed: {e}")
        # Don't exit - let the health check handle it

# Initialize FastAPI app
app = FastAPI(
    title="Bedrock Agent Streaming API",
    description="FastAPI service for streaming Bedrock Agent responses",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with timing and request ID"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    start_time = time.time()
    
    # Log request start
    logger.info(
        f"Request started",
        extra={
            "request_id": request_id,
            "method": request.method,
            "url": str(request.url),
            "client_ip": request.client.host,
            "user_agent": request.headers.get("user-agent", "")
        }
    )
    
    response = await call_next(request)
    
    # Log request completion
    process_time = time.time() - start_time
    logger.info(
        f"Request completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "process_time": f"{process_time:.4f}s"
        }
    )
    
    # Add request ID to response headers
    response.headers["X-Request-ID"] = request_id
    
    return response

def validate_agent_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean agent request data"""
    errors = []
    
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    
    # Validate required fields
    if not data.get("input_text") or not isinstance(data["input_text"], str):
        errors.append("input_text is required and must be a non-empty string")
    
    if not data.get("agent_id") or not isinstance(data["agent_id"], str):
        errors.append("agent_id is required and must be a non-empty string")
    
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    
    # Clean and set defaults
    clean_data = {
        "input_text": data["input_text"].strip(),
        "agent_id": data["agent_id"].strip(),
        "agent_alias_id": data.get("agent_alias_id", "TSTALIASID"),
        "session_id": data.get("session_id"),
        "session_attributes": data.get("session_attributes") or {},
        "prompt_session_attributes": data.get("prompt_session_attributes") or {}
    }
    
    # Validate optional fields
    if not isinstance(clean_data["session_attributes"], dict):
        raise HTTPException(status_code=400, detail="session_attributes must be an object")
    
    if not isinstance(clean_data["prompt_session_attributes"], dict):
        raise HTTPException(status_code=400, detail="prompt_session_attributes must be an object")
    
    return clean_data

def create_stream_chunk(
    chunk_type: str,
    content: str = "",
    accumulated_content: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    trace_data: Optional[Dict[str, Any]] = None,
    return_control_data: Optional[Dict[str, Any]] = None,
    final_content: Optional[str] = None,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    done: bool = False
) -> Dict[str, Any]:
    """Create a standardized stream chunk"""
    chunk = {
        "type": chunk_type,
        "content": content,
        "done": done,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Add optional fields only if they have values
    if accumulated_content is not None:
        chunk["accumulated_content"] = accumulated_content
    if session_id:
        chunk["session_id"] = session_id
    if agent_id:
        chunk["agent_id"] = agent_id
    if trace_data:
        chunk["trace_data"] = trace_data
    if return_control_data:
        chunk["return_control_data"] = return_control_data
    if final_content is not None:
        chunk["final_content"] = final_content
    if error:
        chunk["error"] = error
    if error_code:
        chunk["error_code"] = error_code
    
    return chunk

class BedrockAgentStreamer:
    """Async handler for Bedrock Agent streaming responses"""
    
    def __init__(self, agent_id: str, agent_alias_id: str = "TSTALIASID"):
        self.agent_id = agent_id
        self.agent_alias_id = agent_alias_id
        
    async def invoke_agent_stream(
        self, 
        input_text: str, 
        session_id: Optional[str] = None,
        session_attributes: Optional[Dict[str, str]] = None,
        prompt_session_attributes: Optional[Dict[str, str]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream responses from Bedrock Agent asynchronously"""
        
        if not bedrock_agent_runtime:
            yield create_stream_chunk(
                chunk_type="error",
                error="Bedrock client not initialized",
                done=True
            )
            return
            
        try:
            # Generate session ID if not provided
            if not session_id:
                session_id = f"session-{int(time.time())}-{uuid.uuid4().hex[:8]}"
                
            logger.info(f"Starting agent invocation - Agent: {self.agent_id}, Session: {session_id}")
            
            # Prepare the request parameters
            request_params = {
                'agentId': self.agent_id,
                'agentAliasId': self.agent_alias_id,
                'sessionId': session_id,
                'inputText': input_text
            }
            
            # Add session attributes if provided
            if session_attributes:
                request_params['sessionAttributes'] = session_attributes
                
            if prompt_session_attributes:
                request_params['promptSessionAttributes'] = prompt_session_attributes
                
            # Send initial chunk to indicate start
            yield create_stream_chunk(
                chunk_type="start",
                session_id=session_id,
                agent_id=self.agent_id
            )
            
            # Run the synchronous boto3 call in a thread pool
            response = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: bedrock_agent_runtime.invoke_agent(**request_params)
            )
            
            # Process the event stream
            event_stream = response.get('completion', [])
            accumulated_text = ""
            chunk_count = 0
            
            for event in event_stream:
                chunk_count += 1
                
                # Process chunk events
                if 'chunk' in event:
                    chunk_data = event['chunk']
                    
                    # Handle bytes data
                    if 'bytes' in chunk_data:
                        try:
                            # Decode the chunk content
                            decoded_data = json.loads(chunk_data['bytes'].decode('utf-8'))
                            
                            # Extract text content
                            if 'outputText' in decoded_data:
                                text_content = decoded_data['outputText']
                                accumulated_text += text_content
                                
                                yield create_stream_chunk(
                                    chunk_type="chunk",
                                    content=text_content,
                                    accumulated_content=accumulated_text
                                )
                                
                        except (json.JSONDecodeError, UnicodeDecodeError) as e:
                            logger.warning(f"Failed to decode chunk: {e}")
                            
                # Process trace events
                elif 'trace' in event:
                    trace = event['trace']
                    logger.debug(f"Trace event: {trace}")
                    
                    # Only yield trace data in debug mode
                    if os.getenv("DEBUG_MODE", "false").lower() == "true":
                        yield create_stream_chunk(
                            chunk_type="trace",
                            trace_data=trace
                        )
                    
                # Process return control events (for function calling)
                elif 'returnControl' in event:
                    return_control = event['returnControl']
                    logger.info(f"Return control event: {return_control}")
                    
                    yield create_stream_chunk(
                        chunk_type="return_control",
                        return_control_data=return_control
                    )
                    
                # Add small delay to prevent overwhelming
                await asyncio.sleep(0.01)
                    
            # Send completion signal
            yield create_stream_chunk(
                chunk_type="completion",
                final_content=accumulated_text,
                session_id=session_id,
                done=True
            )
            
            logger.info(f"Agent invocation completed - Session: {session_id}, Chunks: {chunk_count}, Content length: {len(accumulated_text)}")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"AWS Client Error: {error_code} - {error_message}")
            
            yield create_stream_chunk(
                chunk_type="error",
                error=f"AWS Error ({error_code}): {error_message}",
                error_code=error_code,
                done=True
            )
            
        except BotoCoreError as e:
            logger.error(f"Boto Core Error: {e}")
            yield create_stream_chunk(
                chunk_type="error",
                error=f"Boto Error: {str(e)}",
                done=True
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during agent invocation: {e}", exc_info=True)
            yield create_stream_chunk(
                chunk_type="error",
                error=f"Server Error: {str(e)}",
                done=True
            )

async def generate_json_stream(agent_request: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """Generate JSON-delimited stream for the frontend"""
    
    streamer = BedrockAgentStreamer(
        agent_id=agent_request["agent_id"],
        agent_alias_id=agent_request["agent_alias_id"]
    )
    
    try:
        async for chunk in streamer.invoke_agent_stream(
            input_text=agent_request["input_text"],
            session_id=agent_request["session_id"],
            session_attributes=agent_request["session_attributes"],
            prompt_session_attributes=agent_request["prompt_session_attributes"]
        ):
            # Convert to JSON and add newline delimiter
            json_line = json.dumps(chunk, ensure_ascii=False) + '\n'
            yield json_line
            
    except Exception as e:
        logger.error(f"Error in JSON stream generation: {e}", exc_info=True)
        error_chunk = create_stream_chunk(
            chunk_type="error",
            error=f"Stream Error: {str(e)}",
            done=True
        )
        yield json.dumps(error_chunk) + '\n'

# API Endpoints
@app.post("/api/agent/stream")
async def stream_agent_response(request: Request):
    """
    Stream responses from Bedrock Agent
    
    Expected JSON body:
    {
        "input_text": "Your question here",
        "agent_id": "YOUR_BEDROCK_AGENT_ID", 
        "agent_alias_id": "TSTALIASID",  // optional
        "session_id": "session-123",     // optional
        "session_attributes": {},        // optional
        "prompt_session_attributes": {}  // optional
    }
    
    Returns: JSON-delimited streaming response
    """
    request_id = getattr(request.state, 'request_id', 'unknown')
    
    try:
        # Parse and validate request body
        body = await request.json()
        agent_request = validate_agent_request(body)
        
        logger.info(f"Starting agent stream request", extra={
            "request_id": request_id,
            "agent_id": agent_request["agent_id"],
            "session_id": agent_request["session_id"],
            "input_length": len(agent_request["input_text"])
        })
        
        return StreamingResponse(
            generate_json_stream(agent_request),
            media_type="application/json",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive", 
                "X-Content-Type-Options": "nosniff",
                "X-Request-ID": request_id
            }
        )
        
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in request body", extra={"request_id": request_id})
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in stream endpoint: {e}", extra={"request_id": request_id}, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers"""
    try:
        health_data = {
            "status": "healthy",
            "service": "bedrock-agent-streaming",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "details": {
                "bedrock_client": "initialized" if bedrock_agent_runtime else "not_initialized",
                "aws_region": os.getenv('AWS_REGION', 'us-east-1'),
                "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}"
            }
        }
        
        # Simple connectivity test
        if bedrock_agent_runtime:
            try:
                # Test STS to verify credentials are working
                sts_client = boto3.client('sts', region_name=os.getenv('AWS_REGION', 'us-east-1'))
                identity = sts_client.get_caller_identity()
                health_data["details"]["aws_account"] = identity.get('Account', 'unknown')
            except Exception as e:
                health_data["status"] = "unhealthy"
                health_data["details"]["credential_error"] = str(e)
                return health_data, 503
        else:
            health_data["status"] = "unhealthy"
            health_data["details"]["error"] = "Bedrock client not initialized"
            return health_data, 503
            
        return health_data
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "bedrock-agent-streaming", 
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }, 503

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Bedrock Agent Streaming API",
        "version": "1.0.0",
        "endpoints": {
            "stream": "POST /api/agent/stream",
            "health": "GET /health",
            "docs": "GET /docs"
        },
        "timestamp": datetime.utcnow().isoformat()
    }

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors"""
    request_id = getattr(request.state, 'request_id', 'unknown')
    
    logger.error(
        f"Unhandled exception: {exc}",
        extra={"request_id": request_id},
        exc_info=True
    )
    
    return {
        "error": "Internal server error",
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat()
    }, 500

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False,
        access_log=True,
        log_level="info"
    )

## Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

## docker-compose.yml (for local testing)
version: '3.8'
services:
  bedrock-agent-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - AWS_REGION=us-east-1
      - DEBUG_MODE=false
      - ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001
      # In ECS, credentials come from IAM roles
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

## ECS Task Definition (task-definition.json)
{
  "family": "bedrock-agent-streaming-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/BedrockAgentTaskRole",
  "containerDefinitions": [
    {
      "name": "bedrock-agent-api",
      "image": "YOUR_ECR_REPO:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "AWS_REGION",
          "value": "us-east-1"
        },
        {
          "name": "DEBUG_MODE", 
          "value": "false"
        },
        {
          "name": "ALLOWED_ORIGINS",
          "value": "https://your-frontend-domain.com"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/bedrock-agent-streaming-api",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "curl -f http://localhost:8000/health || exit 1"
        ],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}

## Example usage with curl
# Stream request
curl -X POST "http://localhost:8000/api/agent/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "input_text": "What is the weather like today?",
    "agent_id": "YOUR_AGENT_ID",
    "agent_alias_id": "TSTALIASID",
    "session_id": "test-session-123"
  }' \
  --no-buffer

# Health check
curl http://localhost:8000/health

## .env.example
AWS_REGION=us-east-1
DEBUG_MODE=false
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001
PORT=8000
