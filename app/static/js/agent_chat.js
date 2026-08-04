// Agent 对话流式解析（P3 实现）
// 接口: POST /api/agent/chat（SSE），前端使用 fetch + ReadableStream 解析，
// 因为 EventSource 仅支持 GET，无法携带 POST 请求体。
