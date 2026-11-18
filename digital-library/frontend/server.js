const http = require("http");
const fs = require("fs");
const path = require("path");

const host = process.env.HOST || "127.0.0.1";
const port = Number(process.env.PORT || 4173);
const root = __dirname;
const routes = {
  "/api/member":process.env.MEMBER_URL || "http://127.0.0.1:8001",
  "/api/catalog":process.env.CATALOG_URL || "http://127.0.0.1:8002",
  "/api/reservations":process.env.RESERVATION_URL || "http://127.0.0.1:8003",
  "/api/notifications":process.env.NOTIFICATION_URL || "http://127.0.0.1:8004",
  "/api/fine":process.env.FINE_URL || "http://127.0.0.1:8005",
  "/api/loans":process.env.LENDING_URL || "http://127.0.0.1:8006",
  "/api/availability":process.env.AVAILABILITY_URL || "http://127.0.0.1:8007"
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
      signal: AbortSignal.timeout(15000),
      body:["GET","HEAD"].includes(request.method) ? undefined : await new Promise((resolve,reject) => {
        let body="";
        request.on("data",chunk => body += chunk);
        request.on("end",() => resolve(body));
        request.on("error",reject);
      })
    });
    const headers = {"Content-Type":upstream.headers.get("content-type") || "application/json"};
    if (upstream.headers.has("location")) {
      const location = new URL(upstream.headers.get("location"), target);
      if (location.origin === new URL(target).origin) {
        headers.Location = `${prefix}${location.pathname}${location.search}`;
      }
    }
    response.writeHead(upstream.status,headers);
    response.end(Buffer.from(await upstream.arrayBuffer()));
  } catch {
    response.writeHead(503,{"Content-Type":"application/json"});
    response.end(JSON.stringify({detail:"Library service unavailable"}));
  }
}

const server = http.createServer((request,response) => {
  const incoming = new URL(request.url,`http://${host}:${port}`);
  if (incoming.pathname === "/health") {
    response.writeHead(200,{"Content-Type":"application/json"});
    return response.end(JSON.stringify({status:"ok"}));
  }
  const prefix = Object.keys(routes).find(route => incoming.pathname === route || incoming.pathname.startsWith(`${route}/`));
  if (prefix) return proxy(request,response,prefix,routes[prefix]);

  const publicFiles = {"/":"index.html", "/index.html":"index.html", "/styles.css":"styles.css", "/app.js":"app.js"};
  const file = publicFiles[incoming.pathname];
  if (!file) { response.writeHead(404); return response.end("Not found"); }
  const filePath = path.join(root,file);
  fs.readFile(filePath,(error,data) => {
    if (error) { response.writeHead(404); return response.end("Not found"); }
    response.writeHead(200,{"Content-Type":types[path.extname(filePath)] || "application/octet-stream"});
    response.end(data);
  });
});

server.listen(port,host,() => console.log(`Bibliotheca is running at http://${host}:${port}`));
