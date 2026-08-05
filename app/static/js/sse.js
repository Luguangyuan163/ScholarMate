// SSE 流式读取工具：优先流式（打字机效果），不支持 ReadableStream 的环境
// （如旧版 WebView2 / 部分嵌入式浏览器）自动降级为一次性解析，保证内容显示。
window.SSEUtil = {
  async readBody(resp, onEvent) {
    const canStream =
      resp.body && typeof resp.body.getReader === "function";
    if (canStream) {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();
        for (const part of parts) onEvent(part);
      }
    } else {
      const text = await resp.text();
      const parts = text.split("\n\n");
      for (const part of parts) {
        if (part.trim()) onEvent(part);
      }
    }
  },
};
