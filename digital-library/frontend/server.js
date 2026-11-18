const http = require("http");
const fs = require("fs");
const path = require("path");

const host = "127.0.0.1";
const port = 4173;
const root = __dirname;
const routes = {
  "/api/member":"http://127.0.0.1:8001",
  "/api/catalog":"http://127.0.0.1:8002",
  "/api/reservations":"http://127.0.0.1:8003",
  "/api/notifications":"http://127.0.0.1:8004",
  "/api/fine":"http://127.0.0.1:8005",
  "/api/loans":"http://127.0.0.1:8006",
  "/api/availability":"http://127.0.0.1:8007"
};

const types = {
  ".html":"text/html; charset=utf-8",
  ".css":"text/css; charset=utf-8",
  ".js":"text/javascript; charset=utf-8",
  ".svg":"image/svg+xml",
  ".png":"image/png",
  ".jpg":"image/jpeg",
  ".jpeg":"image/jpeg"
};

async function proxy(request,response,prefix,target) {
  const incoming = new URL(request.url, `http://${host}:${port}`);
  const upstreamUrl = `${target}${incoming.pathname.slice(prefix.length)}${incoming.search}`;
  try {
    const upstream = await fetch(upstreamUrl,{
      method:request.method,
      headers:{"Content-Type":request.headers["content-type"] || "application/json"},
      body:["GET","HEAD"].includes(request.method) ? undefined : await new Promise((resolve,reject) => {
        let body="";
        request.on("data",chunk => body += chunk);
        request.on("end",() => resolve(body));
        request.on("error",reject);
      })
    });
    response.writeHead(upstream.status,{"Content-Type":upstream.headers.get("content-type") || "application/json"});
    response.end(Buffer.from(await upstream.arrayBuffer()));
  } catch {
    response.writeHead(503,{"Content-Type":"application/json"});
    response.end(JSON.stringify({detail:"Library service unavailable"}));
  }
}

const server = http.createServer((request,response) => {
  const incoming = new URL(request.url,`http://${host}:${port}`);
  const prefix = Object.keys(routes).find(route => incoming.pathname.startsWith(route));
  if (prefix) return proxy(request,response,prefix,routes[prefix]);

  let filePath = incoming.pathname === "/" ? path.join(root,"index.html") : path.join(root,incoming.pathname);
  if (!filePath.startsWith(root)) { response.writeHead(403); return response.end(); }
  fs.readFile(filePath,(error,data) => {
    if (error) { response.writeHead(404); return response.end("Not found"); }
    response.writeHead(200,{"Content-Type":types[path.extname(filePath)] || "application/octet-stream"});
    response.end(data);
  });
});

server.listen(port,host,() => console.log(`Bibliotheca is running at http://${host}:${port}`));
