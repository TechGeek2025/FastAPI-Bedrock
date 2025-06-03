# Bedrock Agent Streaming API

A production-ready FastAPI service for streaming responses from AWS Bedrock Agents, designed for deployment on ECS Fargate with IAM role-based authentication.

## 🚀 Features

- **Real-time streaming** of Bedrock Agent responses
- **ECS Fargate ready** with IAM role authentication
- **Production logging** with structured request tracking
- **Health monitoring** with AWS connectivity validation
- **Error resilience** with comprehensive error handling
- **CORS support** for frontend integration
- **Memory efficient** streaming without buffering
- **No Pydantic overhead** for faster performance

## 📋 Prerequisites

- **AWS Account** with Bedrock Agent access
- **ECS Fargate cluster** (or local Docker for development)
- **IAM roles** configured for Bedrock access
- **ECR repository** for container images
- **Python 3.11+** for local development

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Frontend      │───▶│   FastAPI        │───▶│   AWS Bedrock   │
│   (React/etc)   │    │   ECS Fargate    │    │   Agent         │
│                 │◀───│   Service        │◀───│                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
     JSON Stream           IAM Role Auth          Agent Response
```

## 🔧 Installation & Setup

### 1. Clone and Install Dependencies

```bash
git clone <your-repo>
cd bedrock-agent-streaming-api

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

Create a `.env` file:

```bash
AWS_REGION=us-east-1
DEBUG_MODE=false
ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.com
PORT=8000
```

### 3. Local Development with Docker

```bash
# Build the Docker image
docker build -t bedrock-agent-api .

# Run with Docker Compose
docker-compose up
```

## 🚀 Deployment to ECS Fargate

### 1. IAM Roles Setup

#### Task Execution Role
```json
{
  "roleName": "ecsTaskExecutionRole",
  "policies": [
    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
  ]
}
```

#### Task Role (for Bedrock access)
```json
{
  "roleName": "BedrockAgentTaskRole",
  "inlinePolicy": {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "bedrock:InvokeAgent"
        ],
        "Resource": [
          "arn:aws:bedrock:*:YOUR_ACCOUNT:agent/*"
        ]
      }
    ]
  }
}
```

### 2. Build and Push to ECR

```bash
# Authenticate with ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ECR_REPO

# Build and tag
docker build -t bedrock-agent-api .
docker tag bedrock-agent-api:latest YOUR_ECR_REPO:latest

# Push to ECR
docker push YOUR_ECR_REPO:latest
```

### 3. Deploy to ECS

```bash
# Register task definition
aws ecs register-task-definition --cli-input-json file://task-definition.json

# Create or update service
aws ecs update-service \
  --cluster your-cluster \
  --service bedrock-agent-api \
  --task-definition bedrock-agent-streaming-api:LATEST
```

## 📡 API Endpoints

### POST `/api/agent/stream`

Stream responses from a Bedrock Agent.

**Request Body:**
```json
{
  "input_text": "What is machine learning?",
  "agent_id": "YOUR_BEDROCK_AGENT_ID",
  "agent_alias_id": "TSTALIASID",
  "session_id": "optional-session-id",
  "session_attributes": {},
  "prompt_session_attributes": {}
}
```

**Response:** JSON-delimited streaming response

```json
{"type":"start","session_id":"session-123","agent_id":"AGENT123","done":false,"timestamp":"2024-01-01T12:00:00Z"}
{"type":"chunk","content":"Machine learning","accumulated_content":"Machine learning","done":false,"timestamp":"2024-01-01T12:00:00.100Z"}
{"type":"chunk","content":" is a subset","accumulated_content":"Machine learning is a subset","done":false,"timestamp":"2024-01-01T12:00:00.200Z"}
{"type":"completion","final_content":"Machine learning is a subset of artificial intelligence...","done":true,"timestamp":"2024-01-01T12:00:01Z"}
```

**Stream Response Types:**
- `start` - Stream initialization
- `chunk` - Text content chunk
- `trace` - Debug information (only in DEBUG_MODE)
- `return_control` - Function calling events
- `completion` - Stream completion
- `error` - Error occurred

### GET `/health`

Health check endpoint for load balancers.

**Response:**
```json
{
  "status": "healthy",
  "service": "bedrock-agent-streaming",
  "timestamp": "2024-01-01T12:00:00Z",
  "details": {
    "bedrock_client": "initialized",
    "aws_region": "us-east-1",
    "aws_account": "123456789012"
  }
}
```

### GET `/`

API information and available endpoints.

## 🧪 Testing

### Using curl

```bash
# Test streaming endpoint
curl -X POST "http://localhost:8000/api/agent/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "input_text": "Explain quantum computing",
    "agent_id": "YOUR_AGENT_ID"
  }' \
  --no-buffer

# Test health check
curl http://localhost:8000/health
```

### Using Python

```python
import requests
import json

# Stream request
response = requests.post(
    "http://localhost:8000/api/agent/stream",
    json={
        "input_text": "What is artificial intelligence?",
        "agent_id": "YOUR_AGENT_ID"
    },
    stream=True
)

# Process streaming response
for line in response.iter_lines():
    if line:
        chunk = json.loads(line.decode('utf-8'))
        print(f"Type: {chunk['type']}, Content: {chunk.get('content', '')}")
```

### Using JavaScript (Frontend)

```javascript
async function streamBedrock(inputText, agentId) {
  const response = await fetch('/api/agent/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      input_text: inputText,
      agent_id: agentId
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const lines = decoder.decode(value).split('\n');
    for (const line of lines) {
      if (line.trim()) {
        const chunk = JSON.parse(line);
        console.log('Received chunk:', chunk);
        
        if (chunk.type === 'chunk') {
          // Update UI with new content
          updateChatMessage(chunk.content);
        } else if (chunk.type === 'completion') {
          // Stream complete
          console.log('Final content:', chunk.final_content);
        }
      }
    }
  }
}
```

## 🔍 Monitoring & Logging

### Application Logs

The application uses structured logging with the following format:

```
2024-01-01 12:00:00 - app - INFO - Request started - {"request_id": "abc-123", "method": "POST", "url": "/api/agent/stream"}
2024-01-01 12:00:00 - app - INFO - Agent invocation completed - {"session_id": "session-123", "chunks": 15, "content_length": 1250}
```

### Key Metrics to Monitor

- **Request latency** - Time to first chunk and total response time
- **Error rates** - Failed requests by error type
- **Bedrock quota** - Token usage and rate limits
- **Memory usage** - Container memory consumption
- **Active connections** - Concurrent streaming connections

### CloudWatch Log Groups

- **Application logs**: `/ecs/bedrock-agent-streaming-api`
- **Health check logs**: Filter by `"GET /health"`
- **Error logs**: Filter by `"ERROR"` or `"type":"error"`

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock service |
| `DEBUG_MODE` | `false` | Enable trace data in stream response |
| `ALLOWED_ORIGINS` | `*` | CORS allowed origins (comma-separated) |
| `PORT` | `8000` | Port for the FastAPI server |

### ECS Task Definition Settings

| Setting | Recommended | Description |
|---------|-------------|-------------|
| **CPU** | `512` | CPU units (0.5 vCPU) |
| **Memory** | `1024` | Memory in MB |
| **Health Check** | `/health` | Health check endpoint |
| **Log Driver** | `awslogs` | CloudWatch logging |

## 🛡️ Security

### AWS IAM Best Practices

- **Least privilege**: Only grant `bedrock:InvokeAgent` for specific agents
- **Resource-based policies**: Limit access to specific agent ARNs
- **No hardcoded credentials**: Use ECS task roles exclusively
- **Audit trails**: Enable CloudTrail for API monitoring

### Application Security

- **Input validation**: All request data is validated and sanitized
- **CORS configuration**: Restrict origins to known frontends
- **Request logging**: All requests include unique tracking IDs
- **Error handling**: Sensitive information not exposed in error messages

## 🚨 Troubleshooting

### Common Issues

#### 1. "Bedrock client not initialized"
```bash
# Check IAM role permissions
aws sts get-caller-identity

# Verify task role has Bedrock permissions
aws iam get-role-policy --role-name BedrockAgentTaskRole --policy-name BedrockAgentAccess
```

#### 2. "AccessDenied" errors
```bash
# Check if agent exists and permissions are correct
aws bedrock-agent get-agent --agent-id YOUR_AGENT_ID
```

#### 3. Stream timeouts
- Check network connectivity between ECS and Bedrock
- Verify agent response times in CloudWatch
- Increase task timeout settings if needed

#### 4. Memory issues
- Monitor container memory usage in CloudWatch
- Consider increasing task memory allocation
- Check for memory leaks in long-running streams

### Debug Mode

Enable debug mode for additional trace information:

```bash
# Set environment variable
DEBUG_MODE=true

# Restart service
aws ecs update-service --cluster your-cluster --service bedrock-agent-api --force-new-deployment
```

### Log Analysis

```bash
# View recent logs
aws logs tail /ecs/bedrock-agent-streaming-api --follow

# Filter error logs
aws logs filter-events --log-group-name /ecs/bedrock-agent-streaming-api --filter-pattern "ERROR"

# Search by request ID
aws logs filter-events --log-group-name /ecs/bedrock-agent-streaming-api --filter-pattern "abc-123"
```

## 🔄 Performance Optimization

### Scaling Configuration

```json
{
  "service": {
    "desiredCount": 2,
    "deploymentConfiguration": {
      "maximumPercent": 200,
      "minimumHealthyPercent": 50
    }
  },
  "autoScaling": {
    "minCapacity": 2,
    "maxCapacity": 10,
    "targetCPUUtilization": 70
  }
}
```

### Load Balancer Settings

- **Health check interval**: 30 seconds
- **Health check timeout**: 5 seconds
- **Healthy threshold**: 2 checks
- **Unhealthy threshold**: 3 checks

## 📈 Monitoring Dashboard

### Key CloudWatch Metrics

- `AWS/ECS/CPUUtilization`
- `AWS/ECS/MemoryUtilization`
- `AWS/ApplicationELB/RequestCount`
- `AWS/ApplicationELB/ResponseTime`
- Custom metrics for Bedrock API calls

### Recommended Alarms

1. **High CPU usage** (>80% for 5 minutes)
2. **High memory usage** (>90% for 5 minutes)
3. **High error rate** (>5% for 2 minutes)
4. **Health check failures** (>3 consecutive failures)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:

1. Check the [troubleshooting section](#🚨-troubleshooting)
2. Review CloudWatch logs
3. Create an issue in the repository
4. Contact the development team

---

**Built with ❤️ using FastAPI and AWS Bedrock**
