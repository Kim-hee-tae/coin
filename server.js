const http = require('http');

const host = '0.0.0.0';
const port = process.env.PORT || 3000;

const html = `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Node 테스트 페이지</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        background: #0f172a;
        color: #e2e8f0;
      }
      .card {
        width: min(560px, 90vw);
        padding: 24px;
        border-radius: 16px;
        background: #1e293b;
        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
      }
      h1 {
        margin-top: 0;
      }
      .meta {
        color: #94a3b8;
        font-size: 14px;
      }
      code {
        background: #334155;
        padding: 2px 6px;
        border-radius: 6px;
      }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>✅ Node 테스트 페이지</h1>
      <p>서버가 정상적으로 실행 중입니다.</p>
      <p class="meta">접속 시간: <span id="now"></span></p>
      <p class="meta">실행 명령어: <code>npm start</code></p>
    </main>
    <script>
      document.getElementById('now').textContent = new Date().toLocaleString('ko-KR');
    </script>
  </body>
</html>`;

const server = http.createServer((_req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(html);
});

server.listen(port, host, () => {
  console.log(`Server running at http://${host}:${port}`);
});
